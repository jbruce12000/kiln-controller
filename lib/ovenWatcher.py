import threading,logging,json,time,datetime
from temp import display_profile_data
from mqttout import enabled as mqtt_enabled, MqttOut
log = logging.getLogger(__name__)

class OvenWatcher(threading.Thread):
    def __init__(self,oven,db=None):
        self.last_profile = None
        self.started = None
        self.observers = []
        threading.Thread.__init__(self)
        self.daemon = True
        self.oven = oven
        self.mqtt = MqttOut() if mqtt_enabled() else None
        # sqlite persistence for every duty cycle; a failed open must
        # never stop heater control, so fall back to no db on error.
        if db is None:
            try:
                from firing_db import FiringDb
                db = FiringDb()
            except Exception as e:
                log.error("could not open firing db: %s" % e)
                db = None
        self.db = db
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
            # command, or an automatic restart). idle broadcasts carry
            # None: reusing the previous stamp would attach idle samples
            # to the finished firing in the db.
            try:
                active = self.active_run_started()
            except Exception:
                active = None
            if active is not None:
                oven_state['run_started'] = active.timestamp()
            else:
                # drop the identity the moment the oven goes idle so
                # the backlog and later broadcasts cannot reuse it
                if getattr(self, 'started', None) is not None and \
                        getattr(getattr(self, 'oven', None),
                                'state', None) not in ('RUNNING', 'PAUSED'):
                    self.started = None
                oven_state['run_started'] = None

            if self.mqtt:
                self.mqtt.publish(oven_state)

            # persist the same broadcast locally every duty cycle.
            # getattr: tests build watchers via __new__ without __init__,
            # so self.db may not exist; db failures must never break
            # the broadcast loop.
            try:
                db = getattr(self, 'db', None)
                if db is not None:
                    db.record_state(oven_state)
            except Exception as e:
                log.error("firing db write failed: %s" % e)

            self.notify_all(oven_state)
            time.sleep(self.oven.time_step)

    def record(self, profile, started=None):
        self.last_profile = profile
        if started is None:
            self.started = datetime.datetime.now()
        elif isinstance(started, datetime.datetime):
            self.started = started
        else:
            # epoch seconds (e.g. restored after an automatic restart
            # so the resumed firing keeps its original identity)
            self.started = datetime.datetime.fromtimestamp(float(started))

    def clear(self):
        '''end the current run identity. called when a firing ends so
        later idle broadcasts carry run_started=None instead of the
        previous firing's stamp (which would attach idle samples to
        that firing in the db and make the ui think a run is still
        in progress). last_profile is kept for display.'''
        self.started = None

    def active_run_started(self):
        '''run start time while a firing is active, else None. gates
        on the oven state so a stale stamp can never leak into idle
        broadcasts, backlogs, or db writes.'''
        if getattr(getattr(self, 'oven', None), 'state', None) \
                not in ('RUNNING', 'PAUSED'):
            return None
        return getattr(self, 'started', None)

    def add_observer(self,observer):
        if self.last_profile:
            p = {
                "name": self.last_profile.name,
                "data": display_profile_data(self.last_profile.data),
                "type" : "profile"
            }
        else:
            p = None
        
        try:
            active = self.active_run_started()
        except Exception:
            active = None
        backlog = {
            'type': "backlog",
            'profile': p,
            'run_started': active.timestamp() if active else None,
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
