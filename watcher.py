#!/usr/bin/env python
import requests
import json
import time
import datetime
import logging

# this monitors your kiln stats every N seconds
# if X checks fail, an alert is sent to a slack channel
# configure an incoming web hook on the slack channel
# set slack_hook_url to that

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

class Watcher(object):

    def __init__(self,kiln_url,slack_hook_url,bad_check_limit=6,temp_error_limit=10,sleepfor=10):
        self.kiln_url = kiln_url
        self.slack_hook_url = slack_hook_url
        self.bad_check_limit = bad_check_limit
        self.temp_error_limit = temp_error_limit
        self.sleepfor = sleepfor
        self.bad_checks = 0
        self.stats = {}

    def get_stats(self):
        try:
            r = requests.get(self.kiln_url,timeout=1)
            return r.json()
        except:
            return {}

    def send_alert(self,msg):
        log.error("sending alert: %s" % msg)
        try: 
            r = requests.post(self.slack_hook_url, json={'text': msg })
        except:
            pass

    def has_errors(self):
        if 'time' not in self.stats:
            log.error("no data")
            return True
        if 'err' in self.stats:
            if abs(self.stats['err']) > self.temp_error_limit:
                log.error("temp out of whack %0.2f" % self.stats['err'])
                return True
        return False 

    def run(self):
        log.info("started watching %s" % self.kiln_url)
        while(True):
            self.stats = self.get_stats()
            if self.has_errors():
                self.bad_checks = self.bad_checks + 1
            else:
                log.info("OK temp=%0.2f target=%0.2f error=%0.2f" % (self.stats['ispoint'],self.stats['setpoint'],self.stats['err']))

            if self.bad_checks >= self.bad_check_limit:
                msg = "error kiln needs help. %s" % json.dumps(self.stats,indent=2, sort_keys=True)
                self.send_alert(msg)
                self.bad_checks = 0
            
            time.sleep(self.sleepfor)

if __name__ == "__main__":

    watcher = Watcher(
        kiln_url = "http://0.0.0.0:8082/api/stats",
        slack_hook_url = "you must add this"
        bad_check_limit = 6,
        temp_error_limit = 10,
        sleepfor = 10 )

    watcher.run()
