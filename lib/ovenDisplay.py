import threading,logging,json,time,datetime
from oven import Oven
log = logging.getLogger(__name__)

class OvenDisplay(threading.Thread):
    def __init__(self,oven,ovenWatcher):
        self.last_profile = None
        self.last_log = []
        self.started = None
        self.recording = False
        self.observers = []
        threading.Thread.__init__(self)
        self.daemon = True
        self.oven = oven
        self.ovenWatcher = ovenWatcher
        ovenWatcher.add_observer(self)
        # TODO - move to config
        self.sleep_time = 0.1
        self.start()

    def run(self):
        while True:
            #oven_state = self.oven.get_state()
            #update_display(oven_state)    
            time.sleep(self.sleep_time)

    def update_display(self, oven_state):
        log.info(oven_state)

    def send(self,oven_state):
        self.update_display(oven_state)



    