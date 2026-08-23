import threading,logging,json,time,datetime
from temp import display_profile_data
from mqttout import enabled as mqtt_enabled, MqttOut
log = logging.getLogger(__name__)

class OvenWatcher(threading.Thread):
    def __init__(self,oven):
        self.last_profile = None
        self.started = None
        self.observers = []
        threading.Thread.__init__(self)
        self.daemon = True
        self.oven = oven
        self.mqtt = MqttOut() if mqtt_enabled() else None
        self.start()

# FIXME - need to save runs of schedules in near-real-time
# FIXME - this will enable re-start in case of power outage
# FIXME - re-start also requires safety start (pausing at the beginning
# until a temp is reached)
# FIXME - re-start requires a time setting in minutes.  if power has been
# out more than N minutes, don't restart
# FIXME - this should not be done in the Watcher, but in the Oven class

    def run(self):
        while True:
            oven_state = self.oven.get_state()

            # stamp the run start time so clients can tell when a new run
            # has begun (from the start button, a scheduled run, an api
            # command, or an automatic restart)
            if self.started:
                oven_state['run_started'] = self.started.timestamp()
            else:
                oven_state['run_started'] = None

            if self.mqtt:
                self.mqtt.publish(oven_state)

            self.notify_all(oven_state)
            time.sleep(self.oven.time_step)

    def record(self, profile):
        self.last_profile = profile
        self.started = datetime.datetime.now()

    def add_observer(self,observer):
        if self.last_profile:
            p = {
                "name": self.last_profile.name,
                "data": display_profile_data(self.last_profile.data),
                "type" : "profile"
            }
        else:
            p = None
        
        backlog = {
            'type': "backlog",
            'profile': p,
            'run_started': self.started.timestamp() if self.started else None,
        }
        backlog_json = json.dumps(backlog)
        try:
            observer.send(backlog_json)
        except:
            log.error("Could not send backlog to new observer")
        
        self.observers.append(observer)

    def notify_all(self,message):
        message_json = json.dumps(message)
        log.debug("sending to %d clients: %s"%(len(self.observers),message_json))

        # iterate over a copy: removing a dead socket mid-loop would
        # otherwise skip the socket right after it
        for wsock in list(self.observers):
            if wsock:
                try:
                    wsock.send(message_json)
                except:
                    log.error("could not write to socket %s"%wsock)
                    self.observers.remove(wsock)
            else:
                self.observers.remove(wsock)
