import json
import logging
import os
import threading
import time
import uuid

import config

log = logging.getLogger(__name__)


class Scheduler(object):
    '''Persists and fires kiln runs that have been scheduled to start at
    a specific date and time. Entries are saved to disk so scheduled runs
    survive a reboot.'''

    def __init__(self, state_file=None, poll_interval=None):
        self.state_file = state_file or config.schedule_state_file
        self.poll_interval = poll_interval or config.schedule_poll_interval
        self.lock = threading.Lock()
        self.schedules = []
        self.fire_callback = None
        self.load()

    def load(self):
        '''read scheduled runs from disk'''
        try:
            with open(self.state_file) as infile:
                self.schedules = json.load(infile)
        except (IOError, ValueError):
            self.schedules = []

    def save(self):
        '''write scheduled runs to disk so they survive a reboot'''
        dirname = os.path.dirname(self.state_file)
        if dirname and not os.path.isdir(dirname):
            os.makedirs(dirname)
        with open(self.state_file, 'w') as outfile:
            json.dump(self.schedules, outfile, indent=4, ensure_ascii=False)

    def add(self, profile, start_time, startat=0):
        '''schedule a firing of the given profile at start_time
        (unix epoch seconds). returns the new schedule entry.'''
        entry = {
            'id': uuid.uuid4().hex[:8],
            'profile': profile,
            'start_time': start_time,
            'startat': startat,
            'created_at': time.time(),
            'fired': False,
            'status': 'pending',
        }
        with self.lock:
            self.schedules.append(entry)
            self.save()
        log.info("scheduled profile %s to start at %d" % (profile, start_time))
        return entry

    def cancel(self, sid):
        '''cancel a scheduled run. returns True if it was cancelled.'''
        with self.lock:
            for i, entry in enumerate(self.schedules):
                if entry['id'] == sid:
                    del self.schedules[i]
                    self.save()
                    return True
        return False

    def list(self):
        '''return all scheduled runs'''
        with self.lock:
            return list(self.schedules)

    def pending(self, now=None):
        '''scheduled runs whose start time has arrived and which have not
        yet fired'''
        now = time.time() if now is None else now
        pending = []
        with self.lock:
            for entry in self.schedules:
                if not entry.get('fired') and entry['start_time'] <= now:
                    pending.append(entry)
        return pending

    def mark_fired(self, entry, fired=True, status='fired'):
        '''record that a scheduled run fired (or was skipped)'''
        with self.lock:
            for e in self.schedules:
                if e['id'] == entry['id']:
                    e['fired'] = fired
                    e['status'] = status
                    e['fired_at'] = time.time()
                    self.save()
                    return

    def fire(self, entry):
        '''attempt to start a due run using fire_callback. the callback
        returns True if the run started, False if it could not (oven busy,
        profile missing, etc).'''
        started = False
        if self.fire_callback:
            try:
                started = self.fire_callback(entry) or False
            except Exception as e:
                log.error("error firing schedule %s: %s" % (entry['id'], e))
        else:
            log.error("no fire_callback set, not firing schedule %s" % entry['id'])
        if started:
            self.mark_fired(entry, fired=True, status='fired')
        else:
            self.mark_fired(entry, fired=True, status='skipped')

    def fire_due(self):
        '''attempt to fire every scheduled run whose time has arrived'''
        for entry in self.pending():
            self.fire(entry)

    def run(self):
        '''background loop that fires due runs. call this from a greenlet
        or thread. NOTE: uses a blocking time.sleep so it is only safe in
        a dedicated thread, not inside a gevent hub. the kiln-controller
        drives the scheduler with a yielding ticker instead (see
        kiln-controller.py).'''
        log.info("scheduler started, checking every %d seconds" % self.poll_interval)
        while True:
            try:
                self.fire_due()
            except Exception as e:
                log.error("scheduler error: %s" % e)
            time.sleep(self.poll_interval)
