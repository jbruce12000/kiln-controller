#!/usr/bin/env python
import requests
import json
import time
import datetime
import logging
import os

# this monitors your kiln stats every N seconds
# if X checks fail, an alert is sent to a slack channel
# configure an incoming web hook on the slack channel
# set slack_hook_url to that

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def truncate(n, decimals=0):
    multiplier = 10 ** decimals
    return int(n * multiplier) / multiplier

class Watcher(object):

    def __init__(self,kiln_url,slack_hook_url,bad_check_limit=6,temp_error_limit=10,sleepfor=10):
        self.kiln_url = kiln_url
        self.slack_hook_url = slack_hook_url
        self.bad_check_limit = bad_check_limit
        self.temp_error_limit = temp_error_limit
        self.sleepfor = sleepfor
        self.bad_checks = 0
        self.prev_state = {}
        self.state = {}
        self.stats = {}
        self.last_error = None

    def get_stats(self):
        try:
            r = requests.get(self.kiln_url,timeout=2)
            log.info(r.json())
            self.prev_state = self.state
            self.state = r.json()

        except requests.exceptions.Timeout as err:
            log.error("network timeout. check kiln_url and port.", err)
            self.state = {"err": "Timeout querying kiln"}
        except requests.exceptions.ConnectionError as err:
            log.error("network connection error. check kiln_url and port.", err)
            self.state = {"err": "Network error querying kiln"}
        except Exception as err:
            log.error("Unknown error", err)
            self.state = {"err": "Unknown error querying kiln"}

    def get_notifications(self):
        if self.state is None or self.prev_state is None:
            return None
        if 'state' in self.prev_state and 'state' in self.state and self.state['state'] != self.prev_state['state']:
            return "Kiln is now " + self.state['state']

        time_left_message = ""
        if 'totaltime' in self.state and 'runtime' in self.state:
            total_time = self.state['totaltime']      
            run_time = self.state['runtime']  
            time_left = total_time - run_time    
            time_left_str = str(datetime.timedelta(seconds=round(time_left)))
            time_left_message = "Remaining: " + time_left_str;
        if 'temperature' in self.prev_state and 'temperature' in self.state and truncate(self.state['temperature'], -2) != truncate(self.prev_state['temperature'], -2):
            return "Kiln reached {0:2.0f}°C. ".format(self.state['temperature']) + time_left_message

        return None

    def send_alert(self,msg):
        log.info("sending alert: %s" % msg)
        try: 
            r = requests.post(self.slack_hook_url, json={'text': msg })
        except:
            pass

    def get_errors(self):
        self.stats = {}
        if (self.state is None):
            return None
        
        if ('err' in self.state):
            return self.state['err']

        if ('state' not in self.state):
            return "missing state"
        
        if (self.state['state'] == "IDLE"):
            return None

        if ('pidstats' in self.state):
            self.stats = self.state['pidstats']
        else:
            return "No pid stats"

        if 'time' not in self.stats:
            return "No data"
        if 'err' in self.stats:
            if abs(self.stats['err']) > self.temp_error_limit:
                return "Temp out of whack %0.2f" % self.stats['err']
        return None

    def run(self):
        log.info("started watching %s" % self.kiln_url)
        while(True):
            self.get_stats()

            try:
                notifications = self.get_notifications()
                if notifications is not None:
                    log.info(notifications)
                    self.send_alert(notifications)
            except Exception as err:
                pass

            error = self.get_errors()
            if error is not None:
                log.error(error)
                self.bad_checks = self.bad_checks + 1
            else:
                self.bad_checks = 0
                try:
                    if self.stats is not None and 'ispoint' in self.stats and 'setpoint' in self.stats and 'err' in self.stats:
                        log.info("OK temp=%0.2f target=%0.2f error=%0.2f" % (self.stats['ispoint'],self.stats['setpoint'],self.stats['err']))
                except Exception as err:
                    log.error(err)
                if (self.last_error is not None):
                    self.send_alert("Error resolved: " + self.last_error)
                    self.last_error = None

            if self.bad_checks >= self.bad_check_limit:
                self.last_error = error
                self.send_alert(error)
                msg = "Error: kiln needs checking. %s" % json.dumps(self.stats,indent=2, sort_keys=True)
                self.send_alert(msg)
                self.bad_checks = 0
            
            time.sleep(self.sleepfor)

if __name__ == "__main__":

    watcher = Watcher(
        kiln_url = os.environ['KILN_URL'], 
        slack_hook_url = os.environ['SLACK_URL'],
        bad_check_limit = 3,
        temp_error_limit = 10,
        sleepfor = 10 )

    watcher.run()
