#!/usr/bin/env python

import time
import os
import sys
import logging
import json

import bottle
import gevent
import geventwebsocket
#from bottle import post, get
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
from geventwebsocket import WebSocketError

# try/except removed here on purpose so folks can see why things break
import config

logging.basicConfig(level=config.log_level, format=config.log_format)
log = logging.getLogger("kiln-controller")
log.info("Starting kiln controller")

script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir + '/lib/')
profile_path = config.kiln_profiles_directory

from oven import SimulatedOven, RealOven, Profile
from ovenWatcher import OvenWatcher

app = bottle.Bottle()

if config.simulate == True:
    log.info("this is a simulation")
    oven = SimulatedOven()
else:
    log.info("this is a real kiln")
    oven = RealOven()
ovenWatcher = OvenWatcher(oven)
# this ovenwatcher is used in the oven class for restarts
oven.set_ovenwatcher(ovenWatcher)

@app.route('/')
def index():
    return bottle.redirect('/picoreflow/index.html')

@app.get('/api/stats')
def handle_api():
    log.info("/api/stats command received")
    if hasattr(oven,'pid'):
        if hasattr(oven.pid,'pidstats'):
            return json.dumps(oven.pid.pidstats)


@app.post('/api')
def handle_api():
    log.info("/api is alive")


    # run a kiln schedule
    if bottle.request.json['cmd'] == 'run':
        wanted = bottle.request.json['profile']
        log.info('api requested run of profile = %s' % wanted)

        # start at a specific minute in the schedule
        # for restarting and skipping over early parts of a schedule
        startat = 0;      
        if 'startat' in bottle.request.json:
            startat = bottle.request.json['startat']

        #Shut off seek if start time has been set
        allow_seek = True
        if startat > 0:
            allow_seek = False

        # get the wanted profile/kiln schedule
        profile = find_profile(wanted)
        if profile is None:
            return { "success" : False, "error" : "profile %s not found" % wanted }

        # FIXME juggling of json should happen in the Profile class
        profile_json = json.dumps(profile)
        profile = Profile(profile_json)
        oven.run_profile(profile, startat=startat, allow_seek=allow_seek)
        ovenWatcher.record(profile)

    if bottle.request.json['cmd'] == 'pause':
        log.info("api pause command received")
        oven.state = 'PAUSED'

    if bottle.request.json['cmd'] == 'resume':
        log.info("api resume command received")
        oven.state = 'RUNNING'

    if bottle.request.json['cmd'] == 'stop':
        log.info("api stop command received")
        oven.abort_run()

    if bottle.request.json['cmd'] == 'memo':
        log.info("api memo command received")
        memo = bottle.request.json['memo']
        log.info("memo=%s" % (memo))

    # get stats during a run
    if bottle.request.json['cmd'] == 'stats':
        log.info("api stats command received")
        if hasattr(oven,'pid'):
            if hasattr(oven.pid,'pidstats'):
                return json.dumps(oven.pid.pidstats)

    return { "success" : True }

def find_profile(wanted):
    '''
    given a wanted profile name, find it and return the parsed
    json profile object or None.
    '''
    #load all profiles from disk
    profiles = get_profiles()
    json_profiles = json.loads(profiles)

    # find the wanted profile
    for profile in json_profiles:
        if profile['name'] == wanted:
            return profile
    return None

@app.route('/picoreflow/:filename#.*#')
def send_static(filename):
    log.debug("serving %s" % filename)
    return bottle.static_file(filename, root=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "public"))


def get_websocket_from_request():
    env = bottle.request.environ
    wsock = env.get('wsgi.websocket')
    if not wsock:
        abort(400, 'Expected WebSocket request.')
    return wsock


@app.route('/control')
def handle_control():
    wsock = get_websocket_from_request()
    log.info("websocket (control) opened")
    while True:
        try:
            message = wsock.receive()
            if message:
                log.info("Received (control): %s" % message)
                msgdict = json.loads(message)
                if msgdict.get("cmd") == "RUN":
                    log.info("RUN command received")
                    profile_obj = msgdict.get('profile')
                    if profile_obj:
                        profile_json = json.dumps(profile_obj)
                        profile = Profile(profile_json)
                    oven.run_profile(profile)
                    ovenWatcher.record(profile)
                elif msgdict.get("cmd") == "SIMULATE":
                    log.info("SIMULATE command received")
                    #profile_obj = msgdict.get('profile')
                    #if profile_obj:
                    #    profile_json = json.dumps(profile_obj)
                    #    profile = Profile(profile_json)
                    #simulated_oven = Oven(simulate=True, time_step=0.05)
                    #simulation_watcher = OvenWatcher(simulated_oven)
                    #simulation_watcher.add_observer(wsock)
                    #simulated_oven.run_profile(profile)
                    #simulation_watcher.record(profile)
                elif msgdict.get("cmd") == "STOP":
                    log.info("Stop command received")
                    oven.abort_run()
            time.sleep(1)
        except WebSocketError as e:
            log.error(e)
            break
    log.info("websocket (control) closed")


@app.route('/storage')
def handle_storage():
    wsock = get_websocket_from_request()
    log.info("websocket (storage) opened")
    while True:
        try:
            message = wsock.receive()
            if not message:
                break
            log.debug("websocket (storage) received: %s" % message)

            try:
                msgdict = json.loads(message)
            except:
                msgdict = {}

            if message == "GET":
                log.info("GET command received")
                wsock.send(get_profiles())
            elif msgdict.get("cmd") == "DELETE":
                log.info("DELETE command received")
                profile_obj = msgdict.get('profile')
                if delete_profile(profile_obj):
                  msgdict["resp"] = "OK"
                wsock.send(json.dumps(msgdict))
                #wsock.send(get_profiles())
            elif msgdict.get("cmd") == "PUT":
                log.info("PUT command received")
                profile_obj = msgdict.get('profile')
                #force = msgdict.get('force', False)
                force = True
                if profile_obj:
                    #del msgdict["cmd"]
                    if save_profile(profile_obj, force):
                        msgdict["resp"] = "OK"
                    else:
                        msgdict["resp"] = "FAIL"
                    log.debug("websocket (storage) sent: %s" % message)

                    wsock.send(json.dumps(msgdict))
                    wsock.send(get_profiles())
            time.sleep(1) 
        except WebSocketError:
            break
    log.info("websocket (storage) closed")


@app.route('/config')
def handle_config():
    wsock = get_websocket_from_request()
    log.info("websocket (config) opened")
    while True:
        try:
            message = wsock.receive()
            wsock.send(get_config())
        except WebSocketError:
            break
        time.sleep(1)
    log.info("websocket (config) closed")


@app.route('/status')
def handle_status():
    wsock = get_websocket_from_request()
    ovenWatcher.add_observer(wsock)
    log.info("websocket (status) opened")
    while True:
        try:
            message = wsock.receive()
            wsock.send("Your message was: %r" % message)
        except WebSocketError:
            break
        time.sleep(1)
    log.info("websocket (status) closed")


def get_profiles():
    try:
        profile_files = os.listdir(profile_path)
    except:
        profile_files = []
    profiles = []
    for filename in profile_files:
        with open(os.path.join(profile_path, filename), 'r') as f:
            profiles.append(json.load(f))
    profiles = normalize_temp_units(profiles)
    return json.dumps(profiles)


def save_profile(profile, force=False):
    profile=add_temp_units(profile)
    profile_json = json.dumps(profile)
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    if not force and os.path.exists(filepath):
        log.error("Could not write, %s already exists" % filepath)
        return False
    with open(filepath, 'w+') as f:
        f.write(profile_json)
        f.close()
    log.info("Wrote %s" % filepath)
    return True

def add_temp_units(profile):
    """
    always store the temperature in degrees c
    this way folks can share profiles
    """
    if "temp_units" in profile:
        return profile
    profile['temp_units']="c"
    if config.temp_scale=="c":
        return profile
    if config.temp_scale=="f":
        profile=convert_to_c(profile);
        return profile

def convert_to_c(profile):
    newdata=[]
    for (secs,temp) in profile["data"]:
        temp = (5/9)*(temp-32)
        newdata.append((secs,temp))
    profile["data"]=newdata
    return profile

def convert_to_f(profile):
    newdata=[]
    for (secs,temp) in profile["data"]:
        temp = ((9/5)*temp)+32
        newdata.append((secs,temp))
    profile["data"]=newdata
    return profile

def normalize_temp_units(profiles):
    normalized = []
    for profile in profiles:
        if "temp_units" in profile:
            if config.temp_scale == "f" and profile["temp_units"] == "c": 
                profile = convert_to_f(profile)
                profile["temp_units"] = "f"
        normalized.append(profile)
    return normalized

def delete_profile(profile):
    profile_json = json.dumps(profile)
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    os.remove(filepath)
    log.info("Deleted %s" % filepath)
    return True

def get_config():
    return json.dumps({"temp_scale": config.temp_scale,
        "time_scale_slope": config.time_scale_slope,
        "time_scale_profile": config.time_scale_profile,
        "kwh_rate": config.kwh_rate,
        "currency_type": config.currency_type})    

def main():
    ip = "0.0.0.0"
    port = config.listening_port
    log.info("listening on %s:%d" % (ip, port))

    server = WSGIServer((ip, port), app,
                        handler_class=WebSocketHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
