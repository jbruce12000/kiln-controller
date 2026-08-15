#!/usr/bin/env python

import time
import os
import sys
import logging
import json
import datetime
import tarfile
import io
import re
import base64
import subprocess
import importlib

import requests

import bottle
import gevent
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

from temp import f_to_c, c_to_f
from urllib.parse import quote
from oven import SimulatedOven, RealOven, Profile
from ovenWatcher import OvenWatcher
from scheduler import Scheduler

app = bottle.Bottle()

public_root = os.path.join(os.path.dirname(os.path.realpath(__file__)), "public")

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
    return bottle.static_file('index.html', root=public_root)

@app.route('/state')
def state():
    return bottle.redirect('/#details')

@app.get('/api/stats')
def handle_stats():
    log.info("/api/stats command received")
    if hasattr(oven,'pid'):
        if hasattr(oven.pid,'pidstats'):
            return json.dumps(oven.get_display_pidstats())


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

        if not start_run(wanted, startat):
            return { "success" : False, "error" : "profile %s not found" % wanted }

    # schedule a kiln run for a future date and time
    if bottle.request.json['cmd'] == 'schedule':
        return api_schedule(bottle.request.json)

    # cancel a scheduled kiln run
    if bottle.request.json['cmd'] == 'cancel_schedule':
        return api_cancel_schedule(bottle.request.json)

    # list scheduled kiln runs
    if bottle.request.json['cmd'] == 'list_schedules':
        return api_list_schedules()

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
                return json.dumps(oven.get_display_pidstats())

    return { "success" : True }

@app.get('/api/dump')
def api_dump():
    '''download config, state, all profiles, and logs as a tar.gz
    archive.'''
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as tar:
        _tar_add_path(tar, 'config.py', config.__file__)
        _tar_add_path(tar, 'state.json', config.automatic_restart_state_file)
        for filename in profile_files():
            _tar_add_path(tar, os.path.join('profiles', filename),
                          os.path.join(profile_path, filename))
        _tar_add_bytes(tar, 'kiln.logs',
                       '\n'.join(gather_log_lines()) + '\n')
    out.seek(0)
    return bottle.HTTPResponse(
        out.getvalue(),
        headers={
            'Content-Type': 'application/gzip',
            'Content-Disposition': 'attachment; filename="kiln-config-dump.tar.gz"',
        })

def profile_files():
    '''list the stored profile filenames, or [] if the directory
    cannot be read.'''
    try:
        return [f for f in os.listdir(profile_path)
                if os.path.isfile(os.path.join(profile_path, f))]
    except Exception:
        return []

def _tar_add_bytes(tar, arcname, text):
    '''add an in-memory text file to a tar archive.'''
    encoded = text.encode('utf-8', errors='replace')
    info = tarfile.TarInfo(arcname)
    info.size = len(encoded)
    tar.addfile(info, io.BytesIO(encoded))

def _tar_add_path(tar, arcname, path):
    '''add a file from disk to a tar archive, skipping it if it
    cannot be read.'''
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            _tar_add_bytes(tar, arcname, f.read())
    except Exception:
        log.error("could not add %s to config dump" % path)

def gather_log_lines():
    '''gather the kiln log lines from the systemd journal for the
    kiln-controller unit. returns a sorted, de-duplicated list of
    lines.'''
    try:
        out = subprocess.check_output(
            "timeout 60 journalctl -u kiln-controller --no-pager 2>/dev/null",
            shell=True, stderr=subprocess.DEVNULL, timeout=70)
    except Exception:
        return []
    return sorted(set(out.decode('utf-8', errors='replace').splitlines()))

def find_profile(wanted):
    '''
    given a wanted profile name, find it and return the parsed
    json profile object or None.
    profiles are stored in celsius, so the raw file is returned
    without any display-scale conversion.
    '''
    try:
        profile_files = os.listdir(profile_path)
    except:
        profile_files = []
    for filename in profile_files:
        with open(os.path.join(profile_path, filename), 'r') as f:
            profile = json.load(f)
        if profile['name'] == wanted:
            return profile
    return None

def start_run(wanted, startat=0, allow_seek=None):
    '''
    start a kiln run of the wanted profile. startat is in minutes.
    allow_seek defaults to True unless startat is given. pass
    allow_seek=False for scheduled runs so they always start from
    the beginning regardless of the current kiln temperature.
    returns True if the run started, False if the profile was not found.
    '''
    if allow_seek is None:
        allow_seek = True
        if startat > 0:
            allow_seek = False

    # get the wanted profile/kiln schedule
    profile = find_profile(wanted)
    if profile is None:
        log.error("profile %s not found" % wanted)
        return False

    # disk profiles tagged temp_units "c" are already internal celsius.
    # legacy profiles predate temp_units and are stored in fahrenheit.
    # convert those to celsius before running, the same way the ui does.
    if profile.get("temp_units") != "c":
        profile = convert_to_c(profile)
        profile["temp_units"] = "c"

    # FIXME juggling of json should happen in the Profile class
    profile_json = json.dumps(profile)
    profile = Profile(profile_json)
    oven.run_profile(profile, startat=startat, allow_seek=allow_seek)
    ovenWatcher.record(profile)
    return True

def parse_start_time(value):
    '''
    convert a start time from a unix epoch (int/float) or an ISO 8601
    string into unix epoch seconds. returns a float.
    '''
    if value is None or isinstance(value, bool):
        raise ValueError("start_time is required")
    if isinstance(value, (int, float)):
        epoch = float(value)
    else:
        text = str(value).strip()
        try:
            # naive datetimes are treated as local time which is what
            # someone scheduling their own kiln expects
            dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("start_time must be a unix epoch or an ISO 8601 string")
        epoch = dt.timestamp()
    if epoch <= time.time():
        raise ValueError("start_time must be in the future")
    return epoch

def api_schedule(json_body):
    '''
    handle the api schedule command. schedules a kiln run of the given
    profile at the given start_time.
    '''
    wanted = json_body.get('profile')
    if not wanted:
        return { "success" : False, "error" : "profile is required" }
    if find_profile(wanted) is None:
        return { "success" : False, "error" : "profile %s not found" % wanted }
    try:
        epoch = parse_start_time(json_body.get('start_time'))
    except ValueError as e:
        return { "success" : False, "error" : str(e) }
    startat = json_body.get('startat', 0) or 0
    entry = scheduler.add(wanted, epoch, startat=startat)
    log.info("api scheduled profile %s at %s" % (wanted, epoch))
    return { "success" : True, "id" : entry["id"], "profile" : wanted, "start_time" : epoch }

def api_cancel_schedule(json_body):
    '''
    handle the api cancel_schedule command. cancels a scheduled run.
    '''
    sid = json_body.get('id')
    if not sid:
        return { "success" : False, "error" : "id is required" }
    if scheduler.cancel(sid):
        return { "success" : True }
    return { "success" : False, "error" : "schedule %s not found" % sid }

def api_list_schedules():
    '''
    handle the api list_schedules command. returns all scheduled runs.
    '''
    return { "success" : True, "schedules" : scheduler.list() }

def fire_scheduled_run(entry):
    '''
    callback used by the scheduler to start a scheduled kiln run.
    returns True if the run started.
    '''
    if oven.state != "IDLE":
        log.warning("schedule %s (%s) skipped, oven state = %s" % (entry["id"], entry["profile"], oven.state))
        return False
    startat = entry.get("startat", 0) or 0
    # a scheduled run always starts from the beginning (or the requested
    # startat) regardless of how hot the kiln is from a previous run.
    if not start_run(entry["profile"], startat, allow_seek=False):
        log.error("schedule %s could not fire, profile %s not found" % (entry["id"], entry["profile"]))
        return False
    log.info("schedule %s fired, starting profile %s" % (entry["id"], entry["profile"]))
    return True

# scheduled runs - fires future firings when their time arrives
scheduler = Scheduler()
scheduler.fire_callback = fire_scheduled_run

def reload_config_module():
    '''reload the config module so the running process picks up the
    new values without a restart. the cached bytecode is removed first
    so an mtime+size collision (two writes within the same second of
    identical length) cannot load a stale .pyc.'''
    cached = getattr(config, '__cached__', None)
    if cached:
        try:
            os.remove(cached)
        except OSError:
            pass
    importlib.reload(config)

def save_config(text):
    '''validate and write config.py, then reload the config module so
    the running process uses the new values. if the reload fails the
    previous config is restored and the reload is retried.'''
    compile(text, 'config.py', 'exec')
    with open(config.__file__, 'r') as f:
        original = f.read()
    with open(config.__file__, 'w') as f:
        f.write(text)
    try:
        reload_config_module()
    except Exception:
        with open(config.__file__, 'w') as f:
            f.write(original)
        reload_config_module()
        raise

@app.get('/api/config/editor')
def api_config_editor():
    '''return the raw contents of config.py for editing.'''
    try:
        with open(config.__file__, 'r') as f:
            text = f.read()
    except Exception as e:
        log.error("could not read config.py: %s" % e)
        return bottle.HTTPResponse(str(e), status=500)
    return bottle.HTTPResponse(text, headers={'Content-Type': 'text/plain'})

@app.post('/api/config/editor')
def api_config_editor_save():
    '''save new config.py contents and reload the config module so the
    running process uses the new values.'''
    body = bottle.request.json
    if not body or 'config' not in body:
        log.error("config.py save rejected: no config in request")
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "no config in request"}),
                                   status=400,
                                   headers={'Content-Type': 'application/json'})
    try:
        save_config(body['config'])
    except SyntaxError as e:
        log.error("config.py syntax error, save rejected: %s" % e)
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "syntax error: %s" % e}),
                                   status=400,
                                   headers={'Content-Type': 'application/json'})
    except Exception as e:
        log.error("config.py save/reload failed: %s" % e)
        return bottle.HTTPResponse(json.dumps({"success": False, "error": str(e)}),
                                   status=400,
                                   headers={'Content-Type': 'application/json'})
    log.info("config.py saved and reloaded via web ui")
    # a full restart is required for settings only read at startup (PID
    # constants, sensor timing, board selection, simulate flag). if the
    # config reload above succeeded, we know the new config is good, so
    # schedule the restart. any active firing resumes from the automatic
    # restart state file when the process comes back up.
    response = {"success": True, "restart_scheduled": True}
    if oven.state == "RUNNING" and not config.automatic_restarts:
        response["restart_scheduled"] = False
        response["warning"] = ("config saved and reloaded in-process, but the full restart was skipped "
                               "because a firing is active and automatic_restarts is False, so the run "
                               "would be lost. startup-only settings (PID, sensor timing, board) still "
                               "need a restart.")
        log.warning(response["warning"])
    else:
        def _do_restart():
            # give the http response a moment to flush to the browser first
            gevent.sleep(1)
            log.info("restarting process now")
            sys.stdout.flush()
            sys.stderr.flush()
            logging.shutdown()
            os.execv(sys.executable, [sys.executable] + sys.argv)
        gevent.spawn(_do_restart)
        log.info("process restart scheduled")
    return response

########################################################################
# community profiles - browse, download, and upload profiles to/from the
# shared kiln-profiles github repo (see the settings in config.py).
# downloads are public; uploads need config.github_token.

# a small cache for the remote listing so manual browsing doesn't slam
# the github api rate limit (60/hr unauthenticated, 5000/hr with token)
_remote_cache = {"at": 0.0, "data": None}
REMOTE_CACHE_TTL = 60  # seconds


def _repo_owner_repo():
    '''parse "owner/repo" out of config.kiln_profiles_repo'''
    url = str(getattr(config, "kiln_profiles_repo", "")).rstrip("/")
    marker = "github.com/"
    if marker not in url:
        return None
    return url.split(marker, 1)[1].strip("/") or None


def _github_headers():
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "kiln-controller"}
    token = getattr(config, "github_token", "") or ""
    if token:
        headers["Authorization"] = "token %s" % token
    return headers


def _github_url(path):
    repo = _repo_owner_repo()
    if not repo:
        return None
    return "https://api.github.com/repos/%s/%s" % (repo, path)


def _raw_url(path):
    repo = _repo_owner_repo()
    if not repo:
        return None
    return "https://raw.githubusercontent.com/%s/%s/%s" % (repo, config.kiln_profiles_branch, path)


def list_remote_profiles(force=False):
    '''list the categories and profiles in the community repo. cached so
    manual browsing doesn't slam the github api rate limit.'''
    if not force and _remote_cache["data"] is not None and time.time() - _remote_cache["at"] < REMOTE_CACHE_TTL:
        return _remote_cache["data"]
    if not _repo_owner_repo():
        return {"success": False, "error": "kiln_profiles_repo must be a github.com URL"}
    try:
        root = requests.get(_github_url("contents"), params={"ref": config.kiln_profiles_branch},
                            headers=_github_headers(), timeout=15).json()
        if not isinstance(root, list):
            return {"success": False, "error": "unexpected response from the kiln-profiles repo"}
        categories = [e["name"] for e in root if isinstance(e, dict) and e.get("type") == "dir"]
        profiles = []
        for category in categories:
            listing = requests.get(_github_url("contents/" + quote(category)),
                                   params={"ref": config.kiln_profiles_branch},
                                   headers=_github_headers(), timeout=15).json()
            if not isinstance(listing, list):
                continue
            for entry in listing:
                if not isinstance(entry, dict) or entry.get("type") != "file":
                    continue
                if not entry["name"].endswith(".json"):
                    continue
                local_name = entry["name"][:-5]
                profiles.append({
                    "category": category,
                    "name": local_name,
                    "path": entry["path"],
                    "size": entry.get("size"),
                    "download_url": entry.get("download_url"),
                    "installed": os.path.isfile(os.path.join(profile_path, local_name + ".json")),
                })
    except Exception as e:
        log.error("could not list community profiles: %s" % e)
        return {"success": False, "error": "could not reach the kiln-profiles repo: %s" % e}
    data = {"success": True, "upload_enabled": bool(getattr(config, "github_token", "") or ""),
            "categories": categories, "profiles": profiles}
    _remote_cache.update({"at": time.time(), "data": data})
    return data


def import_profile(profile):
    '''save a community profile into the local profiles directory,
    normalizing it to the internal celsius convention. raises ValueError
    on invalid profiles.'''
    if not isinstance(profile, dict):
        raise ValueError("invalid profile")
    name = profile.get("name")
    if not name or not re.match(r"^[A-Za-z0-9._-]+$", str(name)):
        raise ValueError("invalid profile name")
    if not isinstance(profile.get("data"), list):
        raise ValueError("profile has no data")
    profile["name"] = str(name)
    if profile.get("temp_units") != "c":
        profile = convert_to_c(profile)
        profile["temp_units"] = "c"
    os.makedirs(profile_path, exist_ok=True)
    filepath = os.path.join(profile_path, profile["name"] + ".json")
    with open(filepath, "w+") as f:
        f.write(json.dumps(profile))
    log.info("imported community profile %s" % profile["name"])
    return filepath


@app.get('/api/profiles/remote')
def api_profiles_remote():
    return json.dumps(list_remote_profiles())


@app.post('/api/profiles/remote/import')
def api_profiles_remote_import():
    body = bottle.request.json or {}
    path = body.get("path") or ""
    if not path or ".." in path or not path.endswith(".json"):
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "invalid profile path"}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    if not _repo_owner_repo():
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "kiln_profiles_repo must be a github.com URL"}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    try:
        resp = requests.get(_raw_url(path), headers=_github_headers(), timeout=15)
        resp.raise_for_status()
        profile = resp.json()
        import_profile(profile)
    except ValueError as e:
        return bottle.HTTPResponse(json.dumps({"success": False, "error": str(e)}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    except Exception as e:
        log.error("could not import community profile: %s" % e)
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "could not download profile: %s" % e}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    _remote_cache["data"] = None  # installed state changed
    return json.dumps({"success": True, "name": profile["name"]})


@app.post('/api/profiles/remote/upload')
def api_profiles_remote_upload():
    body = bottle.request.json or {}
    profile = body.get("profile") or {}
    category = str(body.get("category") or "pottery")
    if not (getattr(config, "github_token", "") or ""):
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "sharing is disabled (no github_token configured)"}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    if not isinstance(profile, dict) or not profile.get("name"):
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "no profile in request"}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    name = str(profile["name"])
    if not re.match(r"^[A-Za-z0-9._-]+$", name):
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "invalid profile name"}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    if not re.match(r"^[A-Za-z0-9._-]+$", category):
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "invalid category"}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    if not _repo_owner_repo():
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "kiln_profiles_repo must be a github.com URL"}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    try:
        # save locally first (normalizes to celsius), then share
        import_profile(profile)
    except ValueError as e:
        return bottle.HTTPResponse(json.dumps({"success": False, "error": str(e)}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    api_path = "contents/%s/%s.json" % (category, name)
    try:
        existing = requests.get(_github_url(api_path), params={"ref": config.kiln_profiles_branch},
                                headers=_github_headers(), timeout=15)
        payload = {
            "message": "share %s" % name,
            "content": base64.b64encode(json.dumps(profile).encode("utf-8")).decode("ascii"),
            "branch": config.kiln_profiles_branch,
        }
        if existing.status_code == 200:
            payload["sha"] = existing.json().get("sha")
        resp = requests.put(_github_url(api_path), json=payload, headers=_github_headers(), timeout=20)
        resp.raise_for_status()
    except Exception as e:
        log.error("could not upload community profile: %s" % e)
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "upload failed: %s" % e}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    log.info("shared profile %s to %s" % (name, category))
    _remote_cache["data"] = None  # listing changed
    return json.dumps({"success": True, "name": name, "category": category})

@app.route('/<filename:path>')
def send_static(filename):
    log.debug("serving %s" % filename)
    return bottle.static_file(filename, root=public_root)


def get_websocket_from_request():
    env = bottle.request.environ
    wsock = env.get('wsgi.websocket')
    if not wsock:
        bottle.abort(400, 'Expected WebSocket request.')
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
                        # the profile comes in display scale from the ui,
                        # store/use it internally in celsius
                        profile_obj = add_temp_units(profile_obj)
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
            wsock.receive()
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
    return json.dumps(sorted(profiles, key=lambda x: x["name"]))


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
    profile['temp_units'] = "c"
    if config.temp_scale == "f":
        profile = convert_to_c(profile)
    return profile

def convert_to_c(profile):
    '''convert profile data from fahrenheit to celsius'''
    profile["data"] = [(secs, f_to_c(temp)) for (secs, temp) in profile["data"]]
    return profile

def convert_to_f(profile):
    '''convert profile data from celsius to fahrenheit'''
    profile["data"] = [(secs, c_to_f(temp)) for (secs, temp) in profile["data"]]
    return profile

def normalize_temp_units(profiles):
    '''convert stored profiles (celsius by convention) to the display
    scale. legacy fahrenheit-stored profiles are converted to celsius
    when the display scale is celsius.'''
    normalized = []
    for profile in profiles:
        stored_units = profile.get("temp_units")
        if stored_units == "c" and config.temp_scale == "f":
            profile = convert_to_f(profile)
            profile["temp_units"] = "f"
        elif stored_units == "f" and config.temp_scale == "c":
            profile = convert_to_c(profile)
            profile["temp_units"] = "c"
        normalized.append(profile)
    return normalized

def delete_profile(profile):
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    os.remove(filepath)
    log.info("Deleted %s" % filepath)
    return True

def get_config():
    return json.dumps({"simulate": config.simulate,
        "temp_scale": config.temp_scale,
        "time_scale_slope": config.time_scale_slope,
        "time_scale_profile": config.time_scale_profile,
        "kwh_rate": config.kwh_rate,
        "currency_type": config.currency_type,
        "github_sharing_enabled": bool(getattr(config, "github_token", "") or "")})    

def main():
    ip = "0.0.0.0"
    port = config.listening_port
    log.info("listening on %s:%d" % (ip, port))

    # run the scheduled runs background loop. this is a gevent greenlet
    # that yields to the hub, so it must NOT use blocking time.sleep.
    # gevent is not monkey-patched in this project.
    def schedule_tick():
        scheduler.fire_due()
        gevent.spawn_later(config.schedule_poll_interval, schedule_tick)

    gevent.spawn_later(config.schedule_poll_interval, schedule_tick)

    server = WSGIServer((ip, port), app,
                        handler_class=WebSocketHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
