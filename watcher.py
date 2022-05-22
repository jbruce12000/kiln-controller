#!/usr/bin/env python
import requests
import json
import time
import datetime

# this monitors your kiln stats every N seconds
# if X checks fail, an alert is sent to a slack channel
# configure an incoming web hook on the slack channel
# set slack_hook_url to that

def get_stats():
    try:
        r = requests.get(kiln_url)
        return r.json()
    except:
        return {}

def send_alert(msg):
    try: 
        r = requests.post(slack_hook_url, json={'text': msg })
    except:
        pass

if __name__ == "__main__":

    kiln_url = "http://0.0.0.0:8081/api/stats"
    slack_hook_url = "you must set this"

    bad_check_limit = 6
    bad_checks = 0
    temp_error_limit = 10
    sleepfor = 10

    while(True):
        stats = get_stats()

        if 'time' not in stats:
            bad_checks = bad_checks + 1
            print("no data")
        if 'err' in stats:
            if abs(stats['err']) > temp_error_limit:
                bad_checks = bad_checks + 1
                print ("temp out of whack")
        if bad_checks >= bad_check_limit:
            print("ERR sending alert")
            msg = "error kiln needs help. %s" % json.dumps(stats,indent=2, sort_keys=True)
            send_alert(msg)
            bad_checks = 0
        else:
            print("OK %s" % datetime.datetime.now())

        time.sleep(sleepfor)

