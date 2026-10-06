#!/usr/bin/env python

import time
import os
import sys
import csv
import logging
import json
import datetime
import tarfile
import io
import re
import base64
import subprocess
import importlib
import threading

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

from temp import f_to_c, c_to_f, to_c
from oven import SimulatedOven, RealOven, Profile
from ovenWatcher import OvenWatcher
from scheduler import Scheduler
from tuner import Tuner, DEFAULT_METHOD
from alerts import (AlertStore, AlertManager, LogSink, MqttSink,
                     WebhookSink, ALERTS, validate_delivery)
from mqttout import enabled as mqtt_enabled
from firing_db import FiringDb

app = bottle.Bottle()

public_root = os.path.join(os.path.dirname(os.path.realpath(__file__)), "public")

# alerts are created before the oven so detection code can be attached
# the moment it exists. LogSink records every alert to the daemon log.
# the mqtt and webhook sinks read their settings live from the same
# store as the web ui, so they self-disable until switched on; neither
# can block heater control (mqtt publishes queue on its network thread,
# webhook posts run on throwaway daemon threads).
alert_store = AlertStore()
alert_manager = AlertManager(alert_store)
alert_manager.add_sink(LogSink())
try:
    alert_manager.add_sink(MqttSink(alert_store))
except Exception as e:
    log.error("could not start mqtt alert sink: %s" % e)
try:
    alert_manager.add_sink(WebhookSink(alert_store))
except Exception as e:
    log.error("could not start webhook alert sink: %s" % e)

if config.simulate == True:
    log.info("this is a simulation")
    oven = SimulatedOven()
else:
    log.info("this is a real kiln")
    oven = RealOven()
ovenWatcher = OvenWatcher(oven)
# this ovenwatcher is used in the oven class for restarts
oven.set_ovenwatcher(ovenWatcher)
oven.set_alert_manager(alert_manager)
tuner = Tuner(oven)

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
        # pausing from any other state would leave the oven thread in a
        # PAUSED state with no profile, which it cannot run
        if oven.state != 'RUNNING':
            return { "success" : False,
                     "error" : "cannot pause, oven state is %s" % (oven.state) }
        oven.state = 'PAUSED'

    if bottle.request.json['cmd'] == 'resume':
        log.info("api resume command received")
        if oven.state != 'PAUSED':
            return { "success" : False,
                     "error" : "cannot resume, oven state is %s" % (oven.state) }
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
    archive. refused while a firing is active so the journal replay can
    never interfere with kiln control.'''
    if _firing_active():
        return bottle.HTTPResponse(
            json.dumps({"success": False,
                        "error": "config dump is disabled while a firing is active"}),
            status=409,
            headers={'Content-Type': 'application/json'})
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

def _firing_active():
    '''True while a kiln firing is in progress or paused. the config dump
    replays the journal, which can take minutes, so it is refused during
    a firing to keep the oven loop free from interference.'''
    return getattr(oven, 'state', None) in ('RUNNING', 'PAUSED')

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

def gather_log_lines(since=None, until=None):
    '''gather kiln log lines from the systemd journal for the
    kiln-controller unit. returns the lines in chronological order
    (journalctl already emits them that way), de-duplicated without
    reordering so firing samples stay in the order they were logged.
    since/until optionally bound the query ("YYYY-MM-DD HH:MM:SS");
    bounded queries return in milliseconds, while a full replay has no
    timeout applied -- the journal can legitimately take minutes to
    replay after weeks of two-second oven samples -- which is why
    api_dump refuses to run while a firing is active, and why request
    handlers must never trigger a full replay (it would stall the
    whole server; the firings snapshot below exists for that reason).'''
    cmd = ["journalctl", "-u", "kiln-controller", "--no-pager"]
    if since is not None:
        _check_journal_bound(since)
        cmd += ["--since", since]
    if until is not None:
        _check_journal_bound(until)
        cmd += ["--until", until]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    return list(dict.fromkeys(out.decode('utf-8', errors='replace').splitlines()))


def _check_journal_bound(value):
    '''validate a --since/--until bound so only calendar timestamps
    ever reach the journalctl command line.'''
    if not re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', value or ''):
        raise ValueError("invalid journal time bound %r" % (value,))


# firing export - parse past firings out of the journal logs so the
# config tab can offer them as csv downloads. a firing starts at a
# "Running schedule <name>" line (logged by oven.run_profile, whatever
# started the run) and owns every "temp=..., target=..., ..." sample
# line after it until the next firing starts. samples before the first
# start marker belong to no firing and are skipped.
#
# one logical firing usually spans several "Running schedule" lines:
# every process restart mid-firing (config save, reboot, crash) logs a
# fresh one when the automatic restart resumes the schedule. those
# continuations are consolidated back into a single firing (see
# _continuation): a start marker preceded by an "automatically
# restarting profile = ...<name>" line for the same profile always
# continues it, as does a same-profile start within FIRING_MERGE_GAP
# of the previous end.
FIRING_START_RE = re.compile(r'Running schedule (\S+) starting at')
FIRING_RESUME_RE = re.compile(r'automatically restarting profile = (\S+) at minute')
FIRING_SAMPLE_RE = re.compile(
    r'temp=([\d.\-]+), target=([\d.\-]+), error=([\d.\-]+), '
    r'pid=([\d.\-]+), p=([\d.\-]+), i=([\d.\-]+), d=([\d.\-]+), '
    r'heat_on=([\d.\-]+), heat_off=([\d.\-]+), '
    r'run_time=(\d+), total_time=(\d+), time_left=(\d+)')
FIRING_TIME_RE = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})')
FIRING_CSV_COLUMNS = [
    'timestamp', 'profile', 'run_time', 'total_time', 'time_left',
    'temp', 'target', 'error', 'pid', 'p', 'i', 'd',
    'heat_on', 'heat_off',
]
FIRING_LIST_LIMIT = 20
FIRING_MERGE_GAP = 120  # seconds: same-profile restarts within this merge

# short-lived cache so picking a firing from the list and then
# downloading it does not replay the (minutes-long) journal twice.
# NOTE: a full journal replay runs for minutes and must never execute
# in a request handler: this process is single-threaded (gevent), so a
# blocking replay stalls every websocket and http request until it
# finishes. instead a background thread keeps a snapshot of the most
# recent firing metadata (profile, start/end, sample count, plus the
# time bounds needed to re-query one firing). request handlers only
# serve the snapshot or run small bounded (--since/--until) queries,
# which return in milliseconds. the snapshot is built newest-first
# from the journal tail, so recent firings never wait behind ancient
# history; later refreshes only fetch what is new.
_firings_lock = threading.Lock()
_firings_state = {"metas": [], "last_line": None, "last_stamp": None,
                  "resume_pending": None,
                  "updated": 0.0, "refreshing": False, "error": None}
FIRINGS_REFRESH_INTERVAL = 300  # seconds between background refreshes
FIRING_BOUND_SLOP = 120  # seconds of padding around a firing's time bounds


def _firing_second(stamp):
    '''"2026-08-12 19:20:18,345" -> "2026-08-12 19:20:18" for use as a
    journalctl --since/--until bound.'''
    return stamp[:19]


def _shift_seconds(stamp19, delta):
    '''shift a second-precision stamp by delta seconds, for padding
    firing time bounds.'''
    dt = datetime.datetime.strptime(stamp19, "%Y-%m-%d %H:%M:%S")
    return (dt + datetime.timedelta(seconds=delta)).strftime("%Y-%m-%d %H:%M:%S")


def _merge_firing_lines(lines):
    '''fold raw journal lines into the snapshot. returns 'ok' when the
    lines were consumed, or 'lost-anchor' when an incremental update no
    longer connects to the previously seen log (rotation/vacuum), in
    which case the caller must do a full rebuild.'''
    with _firings_lock:
        last_line = _firings_state["last_line"]
        lines = list(lines)
        if last_line is None:
            new_lines = lines
        elif last_line in lines:
            new_lines = lines[lines.index(last_line) + 1:]
        else:
            return 'lost-anchor'
        metas = _firings_state["metas"]
        for line in new_lines:
            resume = FIRING_RESUME_RE.search(line)
            if resume:
                _firings_state["resume_pending"] = \
                    _resume_profile_name(resume.group(1))
            else:
                start = FIRING_START_RE.search(line)
                if start:
                    stamp = _firing_timestamp(line)
                    profile = start.group(1)
                    resumed = _firings_state["resume_pending"] == profile
                    _firings_state["resume_pending"] = None
                    if metas and _continuation(metas[-1]["profile"],
                                               metas[-1]["end"],
                                               profile, stamp, resumed):
                        pass  # restart-resume of the previous firing
                    else:
                        if metas and stamp:
                            # the firing that just ended runs until this
                            # one starts
                            metas[-1]["until"] = _firing_second(stamp)
                        meta = {"profile": profile,
                                "start": stamp, "end": '', "samples": 0,
                                "since": None, "until": None}
                        if stamp:
                            meta["since"] = _shift_seconds(
                                _firing_second(stamp), -FIRING_BOUND_SLOP)
                        metas.append(meta)
                elif metas and FIRING_SAMPLE_RE.search(line):
                    stamp = _firing_timestamp(line)
                    metas[-1]["samples"] += 1
                    if stamp:
                        metas[-1]["end"] = stamp
            _firings_state["last_line"] = line
            stamp = _firing_timestamp(line)
            if stamp:
                _firings_state["last_stamp"] = _firing_second(stamp)
        return 'ok'


def _reverse_tail_lines(want_starts):
    '''yield journal lines newest-first, stopping once want_starts
    "Running schedule" markers have been yielded (inclusive), then
    stop the journal tail. plain reverse streaming only: filtering
    flags change journalctl's seeking and can stall on a huge journal.
    background thread only.'''
    proc = None
    try:
        proc = subprocess.Popen(["journalctl", "-u", "kiln-controller",
                                 "--no-pager", "-r"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                text=True, errors="replace")
        starts = 0
        previous = None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line == previous:
                continue
            previous = line
            yield line
            if FIRING_START_RE.search(line):
                starts += 1
                if starts >= want_starts:
                    break
    finally:
        if proc is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


# when the kiln fired in the last week the tail build only needs this
# small window (seconds); otherwise it streams the journal tail above
_TAIL_FAST_DAYS = 7


def _tail_build_firings():
    '''(re)build the snapshot from recent firings: parse just the last
    week when it holds enough firing starts, else stream the journal
    tail newest-first until enough starts are seen. then consolidate
    and keep the newest FIRING_LIST_LIMIT. the slow path takes a
    couple of minutes on a gigabyte journal but runs in the
    background, never stalling the server.'''
    want = FIRING_LIST_LIMIT + 1
    since = (datetime.datetime.now() -
             datetime.timedelta(days=_TAIL_FAST_DAYS)).strftime(
                 "%Y-%m-%d %H:%M:%S")
    recent = gather_log_lines(since=since)
    if sum(1 for line in recent if FIRING_START_RE.search(line)) >= want:
        raw = recent
        chronological = True
    else:
        raw = list(_reverse_tail_lines(want))
        chronological = False
    ordered = raw if chronological else list(reversed(raw))
    merged = consolidate_firings(parse_firings(ordered))[-FIRING_LIST_LIMIT:]
    metas = []
    for firing in merged:
        meta = {"profile": firing["profile"],
                "start": firing["start"], "end": firing["end"],
                "samples": len(firing["samples"]), "since": None,
                "until": None}
        if firing["start"]:
            meta["since"] = _shift_seconds(
                _firing_second(firing["start"]), -FIRING_BOUND_SLOP)
        metas.append(meta)
    for i in range(len(metas) - 1):
        if metas[i + 1]["start"]:
            metas[i]["until"] = _firing_second(metas[i + 1]["start"])
    with _firings_lock:
        _firings_state["metas"] = metas
        # anchor incremental refreshes at the newest raw line seen
        if raw:
            anchor = raw[0] if not chronological else raw[-1]
        else:
            anchor = None
        _firings_state["last_line"] = anchor
        stamp = _firing_timestamp(anchor) if anchor else ''
        _firings_state["last_stamp"] = _firing_second(stamp) if stamp \
            else None
        _firings_state["resume_pending"] = None


def _refresh_firings_snapshot():
    '''extend the snapshot with whatever the journal gained since the
    last refresh, or (re)build it from the journal tail when empty or
    disconnected from it. runs in a background thread so the
    minutes-long full replay never stalls the server; see the note on
    _firings_lock above.'''
    try:
        with _firings_lock:
            anchored = _firings_state["last_line"] is not None
            last_stamp = _firings_state["last_stamp"]
        if not anchored:
            _tail_build_firings()
        else:
            lines = gather_log_lines(since=last_stamp)
            if _merge_firing_lines(lines) == 'lost-anchor':
                _tail_build_firings()
        with _firings_lock:
            _firings_state["updated"] = time.time()
            _firings_state["error"] = None
    except Exception as e:
        log.error("firings snapshot refresh failed: %s" % e)
        with _firings_lock:
            _firings_state["error"] = str(e)
    finally:
        with _firings_lock:
            _firings_state["refreshing"] = False


def _spawn_firings_refresh():
    '''start a background snapshot refresh unless one is already
    running. returns True when a refresh was started. safe to call
    from request handlers: it never blocks.'''
    with _firings_lock:
        if _firings_state["refreshing"]:
            return False
        _firings_state["refreshing"] = True
    thread = threading.Thread(target=_refresh_firings_snapshot, daemon=True)
    thread.start()
    return True


def _firings_snapshot():
    '''a copy of the snapshot for serving from request handlers.'''
    with _firings_lock:
        return {"metas": [dict(m) for m in _firings_state["metas"]],
                "updated": _firings_state["updated"],
                "refreshing": _firings_state["refreshing"],
                "error": _firings_state["error"]}


def _resume_profile_name(path):
    '''"automatically restarting profile" logs a profile file path;
    reduce it to the profile name for comparison with "Running
    schedule <name>" lines.'''
    base = path.rsplit('/', 1)[-1]
    return base[:-5] if base.endswith('.json') else base


def _stamp_gap_seconds(end_stamp, start_stamp):
    '''seconds from the previous firing's end stamp to the next
    firing's start stamp ("2026-08-12 19:20:18,345" with millis).
    None when either stamp is missing or unparsable.'''
    try:
        if not end_stamp or not start_stamp:
            return None
        end = datetime.datetime.strptime(end_stamp, "%Y-%m-%d %H:%M:%S,%f")
        start = datetime.datetime.strptime(start_stamp, "%Y-%m-%d %H:%M:%S,%f")
        return (start - end).total_seconds()
    except (ValueError, TypeError):
        return None


def _continuation(prev_profile, prev_end, profile, start, resumed):
    '''True when a "Running schedule <profile>" line continues the
    previous firing instead of starting a new one: same profile plus
    either an automatic-restart resume marker for it, or a start
    within FIRING_MERGE_GAP of the previous end.'''
    if profile != prev_profile:
        return False
    if resumed:
        return True
    gap = _stamp_gap_seconds(prev_end, start)
    return gap is not None and 0 <= gap <= FIRING_MERGE_GAP


def _firing_timestamp(line):
    '''the in-process timestamp (config.log_format) embedded in a
    journal line, e.g. "2026-08-12 19:20:18,345". empty string when
    the line carries none.'''
    m = FIRING_TIME_RE.search(line)
    return m.group(1) if m else ''


def _firing_sample_row(line, profile):
    '''parse a sample log line into a csv row dict, or None when the
    line carries no sample.'''
    sample = FIRING_SAMPLE_RE.search(line)
    if not sample:
        return None
    return {"timestamp": _firing_timestamp(line), "profile": profile,
            "run_time": sample.group(10),
            "total_time": sample.group(11),
            "time_left": sample.group(12),
            "temp": sample.group(1), "target": sample.group(2),
            "error": sample.group(3), "pid": sample.group(4),
            "p": sample.group(5), "i": sample.group(6),
            "d": sample.group(7), "heat_on": sample.group(8),
            "heat_off": sample.group(9)}


def parse_firings(log_lines):
    '''group journal log lines into firings. returns a list of
    {"id", "profile", "start", "end", "resumed", "samples": [row,
    ...]} dicts in chronological order, ids are the index in that
    list. each row has the FIRING_CSV_COLUMNS keys. continuations are
    NOT merged here; use consolidate_firings for that.'''
    firings = []
    current = None
    pending_resume = None
    for line in log_lines:
        resume = FIRING_RESUME_RE.search(line)
        if resume:
            pending_resume = _resume_profile_name(resume.group(1))
            continue
        start = FIRING_START_RE.search(line)
        if start:
            current = {"id": len(firings),
                       "profile": start.group(1),
                       "start": _firing_timestamp(line),
                       "end": '',
                       "resumed": pending_resume == start.group(1),
                       "samples": []}
            pending_resume = None
            firings.append(current)
            continue
        if current is not None:
            row = _firing_sample_row(line, current["profile"])
            if row is not None:
                current["samples"].append(row)
                if row["timestamp"]:
                    current["end"] = row["timestamp"]
    return firings


def consolidate_firings(firings):
    '''fold continuations (see _continuation) back into the firing
    they resume, concatenating samples. returns a new list keeping
    the first segment's id/start so csv lookups by (profile, start)
    keep working.'''
    merged = []
    for firing in firings:
        if merged and _continuation(merged[-1]["profile"],
                                    merged[-1]["end"],
                                    firing["profile"], firing["start"],
                                    firing.get("resumed")):
            merged[-1]["samples"].extend(firing["samples"])
            if firing["end"]:
                merged[-1]["end"] = firing["end"]
        else:
            merged.append({"id": firing["id"],
                           "profile": firing["profile"],
                           "start": firing["start"],
                           "end": firing["end"],
                           "samples": list(firing["samples"])})
    return merged


def firing_duration(firing):
    '''whole seconds from a firing's start to its end, or 0 when
    either stamp is missing.'''
    gap = _stamp_gap_seconds(firing.get("start"), firing.get("end"))
    return int(gap) if gap is not None and gap >= 0 else 0


def get_firings_snapshot():
    '''the firing metadata snapshot, kicking off a background refresh
    when it is empty or stale. never blocks on the journal: callers
    get whatever is cached plus refreshing/error status.'''
    snap = _firings_snapshot()
    if (not snap["metas"] or
            time.time() - snap["updated"] > FIRINGS_REFRESH_INTERVAL) \
            and not snap["refreshing"]:
        _spawn_firings_refresh()
        snap["refreshing"] = True
    return snap


def firing_to_csv(firing):
    '''render one parsed firing as csv text.'''
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(FIRING_CSV_COLUMNS)
    for row in firing["samples"]:
        writer.writerow([row.get(col, '') for col in FIRING_CSV_COLUMNS])
    return out.getvalue()


def _firing_filename(firing):
    '''attachment filename for a firing csv, safe for content-disposition.'''
    profile = re.sub(r'[^A-Za-z0-9._-]+', '-', firing["profile"])
    start = re.sub(r'[^0-9]+', '', firing["start"]) or str(firing["id"])
    return 'firing-%s-%s.csv' % (profile or 'unnamed', start)


# firing list and csv export are served from db/firings.db (see
# lib/firing_db.py), which records every duty-cycle broadcast. the
# journal-parsing helpers above remain for the log-based diagnostics,
# but the export panel no longer replays the journal: db queries
# return in milliseconds. csv rendering still runs on an isolated
# worker thread (below) so even a large firing never blocks the
# gevent hub; the request greenlet only yields (gevent.sleep) waiting
# for it.

def _wall_to_stamp(wall):
    '''epoch seconds -> "2026-08-12 19:20:18,345" journal-style stamp
    (local time, millis after a comma). empty string when unparsable.'''
    try:
        dt = datetime.datetime.fromtimestamp(float(wall))
        return "%s,%03d" % (dt.strftime("%Y-%m-%d %H:%M:%S"),
                            int(dt.microsecond / 1000))
    except (TypeError, ValueError, OverflowError, OSError):
        return ''


def _open_read_db():
    '''open the firing db without pruning. prune runs at start-up on
    its own thread (see FiringDb); export opens must stay read-cheap
    and never spawn maintenance work. returns None on failure.'''
    try:
        return FiringDb(prune_on_start=False)
    except Exception as e:
        log.error("could not open firing db for export: %s" % e)
        return None


def _get_db_firings(limit=FIRING_LIST_LIMIT):
    '''newest-first firing metas from the db: [{id, profile, start,
    end, duration, samples}]. ids are stable db row ids. raises on
    db errors so callers can report them.'''
    db = _open_read_db()
    if db is None:
        raise RuntimeError("could not open firing database")
    try:
        rows = db._con.execute(
            "SELECT f.id, f.profile,"
            " COUNT(s.id), MIN(s.t), MAX(s.t)"
            " FROM firings f LEFT JOIN samples s"
            " ON s.firing_id = f.id"
            " GROUP BY f.id ORDER BY f.id DESC LIMIT ?",
            (limit,)).fetchall()
    finally:
        db.close()
    metas = []
    for fid, profile, count, first, last in rows:
        start = _wall_to_stamp(first) if first else ''
        end = _wall_to_stamp(last) if last else ''
        duration = 0
        if first and last and last >= first:
            duration = int(last - first)
        metas.append({"id": fid, "profile": profile, "start": start,
                      "end": end, "duration": duration,
                      "samples": count or 0})
    return metas


def _db_row_to_csv_row(row, firing, step):
    '''one db sample row -> FIRING_CSV_COLUMNS dict. row is the flat
    (t, runtime, temp, target, heat, err, pid, p, i, d, out) sample
    columns; firing carries profile/total_time. heat_on/off derive
    from the normalized pid output (out * step), exactly how the oven
    loop computes them (see oven.heat_then_cool); the raw heat value
    is only a fallback for rows stored without out.'''
    t, runtime, temp, target, heat, err, pid, p, i, d, out = row
    total = firing.get("totaltime")
    try:
        runtime_f = float(runtime)
    except (TypeError, ValueError):
        runtime_f = 0
    try:
        total_f = float(total)
    except (TypeError, ValueError):
        total_f = 0
    try:
        out_f = float(out) if out is not None else None
    except (TypeError, ValueError):
        out_f = None
    if out_f is not None:
        heat_on = out_f * step
        heat_off = step - heat_on
    else:
        try:
            heat_on = float(heat) if heat is not None else 0.0
        except (TypeError, ValueError):
            heat_on = 0.0
        if heat_on <= 1.0 and heat_on >= 0.0:
            # legacy real-oven on/off flag: scale to seconds
            heat_on = heat_on * step
        heat_off = step - heat_on
    if heat_off < 0:
        heat_off = 0.0

    def f2(value):
        try:
            return "%.2f" % float(value)
        except (TypeError, ValueError):
            return ''

    return {"timestamp": _wall_to_stamp(t), "profile": firing.get("profile"),
            "run_time": int(runtime_f), "total_time": int(total_f),
            "time_left": int(total_f - runtime_f),
            "temp": f2(temp), "target": f2(target),
            "error": f2(err),
            "pid": f2(pid), "p": f2(p),
            "i": f2(i), "d": f2(d),
            "heat_on": "%.2f" % heat_on, "heat_off": "%.2f" % heat_off}


def _db_firing_to_csv(firing, rows, step):
    '''render one db firing as csv text with FIRING_CSV_COLUMNS.'''
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(FIRING_CSV_COLUMNS)
    for row in rows:
        csv_row = _db_row_to_csv_row(row, firing, step)
        writer.writerow([csv_row.get(col, '') for col in FIRING_CSV_COLUMNS])
    return out.getvalue()


# csv worker jobs: the request greenlet spawns one daemon thread per
# download and yields (gevent.sleep) until it finishes, so the gevent
# hub stays responsive to other clients while a large firing renders.
DB_CSV_TIMEOUT = 30.0  # seconds a download waits for its worker
DB_CSV_POLL = 0.05  # seconds between completion checks
_csv_jobs_lock = threading.Lock()
_csv_jobs = {}
_csv_job_next = [0]


def _start_csv_build(firing_id):
    '''render preparation on an isolated daemon thread. returns a job
    id the request greenlet can wait on via _wait_csv_job.'''
    with _csv_jobs_lock:
        _csv_job_next[0] += 1
        job_id = "csv-%d" % _csv_job_next[0]
        _csv_jobs[job_id] = {"done": False, "csv": None,
                             "filename": None, "error": None,
                             "status": None}
    thread = threading.Thread(target=_build_csv_job,
                              args=(job_id, firing_id,), daemon=True)
    thread.start()
    return job_id


def _build_csv_job(job_id, firing_id):
    '''worker body: load one firing from the db and render its csv.
    always marks the job done (with csv or error) so waiters never
    hang. runs off the gevent hub.'''
    result = {"done": True, "csv": None, "filename": None,
              "error": "unknown error", "status": 500}
    try:
        try:
            step = float(getattr(config, "sensor_time_wait", 2)) or 2.0
        except (TypeError, ValueError):
            step = 2.0
        db = _open_read_db()
        if db is None:
            result.update(error="could not open firing database",
                          status=500)
        else:
            try:
                frow = db._con.execute(
                    "SELECT id, profile, totaltime FROM firings"
                    " WHERE id = ?",
                    (firing_id,)).fetchone()
                if frow is None:
                    result.update(error="firing not found", status=404)
                else:
                    rows = db._con.execute(
                        "SELECT t, runtime, temp, target, heat,"
                        " err, pid, p, i, d, out"
                        " FROM samples WHERE firing_id = ?"
                        " ORDER BY id",
                        (frow[0],)).fetchall()
                    if not rows:
                        result.update(
                            error="no samples found for this firing",
                            status=404)
                    else:
                        firing = {"id": frow[0], "profile": frow[1],
                                  "totaltime": frow[2], "start": ""}
                        first_t = rows[0][0]
                        if first_t:
                            firing["start"] = _wall_to_stamp(first_t)
                        result.update(
                            csv=_db_firing_to_csv(firing, rows, step),
                            filename=_firing_filename(firing),
                            error=None, status=200)
            finally:
                db.close()
    except Exception as e:
        log.error("csv export failed for firing %s: %s" % (firing_id, e))
        result.update(error="csv export failed: %s" % e, status=500)
    with _csv_jobs_lock:
        stored = _csv_jobs.get(job_id)
        if stored is not None:
            stored.update(result)


def _wait_csv_job(job_id, timeout=DB_CSV_TIMEOUT):
    '''yield (gevent.sleep, never block the hub) until the worker
    marks the job done. returns the job dict, or None on timeout.'''
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _csv_jobs_lock:
            job = _csv_jobs.get(job_id)
            done = bool(job and job.get("done"))
            snapshot = dict(job) if job else None
        if done:
            return snapshot
        # yield to the hub instead of blocking it: gevent is not
        # monkey-patched here, so a plain join/sleep would stall
        # every other request.
        gevent.sleep(DB_CSV_POLL)
    return None


@app.get('/api/firings')
def api_firings():
    '''list the most recent firings stored in db/firings.db, newest
    first so the latest firing is on top. the db query returns in
    milliseconds, so unlike the old journal replay this needs no
    background snapshot. each entry carries its stable db id (for
    /api/firings/<id>/csv), profile name, start/end timestamps,
    duration, and sample count. updated/refreshing/error are kept so
    the ui polling logic keeps working (refreshing is always False;
    /api/firings/refresh is a no-op).'''
    try:
        metas = _get_db_firings()
        error = None
    except Exception as e:
        log.error("firing list failed: %s" % e)
        metas = []
        error = str(e)
    return json.dumps({"success": True, "firings": metas,
                       "updated": time.time(),
                       "refreshing": False,
                       "error": error})


@app.post('/api/firings/refresh')
def api_firings_refresh():
    '''no-op kept for compatibility: the db-backed listing is always
    current, so there is nothing to refresh in the background.'''
    return {"success": True, "refreshing": False}


@app.get('/api/firings/<fid>/csv')
def api_firing_csv(fid):
    '''download one firing from db/firings.db as csv. fid is the db id
    from /api/firings. rendering runs on an isolated worker thread;
    this handler only yields waiting for it, so other requests stay
    responsive even for large firings.'''
    try:
        wanted = int(fid)
    except (TypeError, ValueError):
        return bottle.HTTPResponse(
            json.dumps({"success": False, "error": "invalid firing id"}),
            status=400,
            headers={'Content-Type': 'application/json'})
    job_id = _start_csv_build(wanted)
    job = _wait_csv_job(job_id)
    with _csv_jobs_lock:
        _csv_jobs.pop(job_id, None)
    if job is None:
        return bottle.HTTPResponse(
            json.dumps({"success": False,
                        "error": "csv export timed out, try again"}),
            status=503,
            headers={'Content-Type': 'application/json'})
    if not job.get("csv"):
        return bottle.HTTPResponse(
            json.dumps({"success": False,
                        "error": job.get("error") or "export failed"}),
            status=job.get("status") or 500,
            headers={'Content-Type': 'application/json'})
    return bottle.HTTPResponse(
        job["csv"],
        headers={'Content-Type': 'text/csv',
                 'Content-Disposition': 'attachment; filename="%s"'
                 % (job.get("filename") or ("firing-%s.csv" % wanted))})


# firing history for live clients. a client that (re)connects mid-firing
# only sees live ticks from that moment on; the overview graph and the
# details charts would otherwise start empty instead of showing the
# whole firing. the client fetches this once per run (on the status
# backlog) and merges it with the live feed, so any drop only leaves a
# gap that the next backfill closes. compact columnar rows keep the
# one-time transfer small; floats are rounded except the pid time,
# which the client uses as its dedupe watermark.
HISTORY_COLS = ["t", "td", "sp", "isp", "err", "ed",
                "p", "i", "d", "kp", "ki", "kd", "pid", "out",
                "rt", "temp", "tgt", "heat", "tt", "cost", "hr",
                "cu", "te"]
# short column -> flat sample column (pid loop terms live in
# samples now; sp/isp map to target/temp; kp/ki/kd/totaltime come
# from the firing row)
_HISTORY_PID_KEYS = {"t": "t", "td": "dt", "sp": "target",
                     "isp": "temp", "err": "err", "ed": "ed",
                     "p": "p", "i": "i", "d": "d",
                     "kp": "kp", "ki": "ki", "kd": "kd",
                     "pid": "pid", "out": "out"}
_HISTORY_SAMPLE_KEYS = ("runtime", "temp", "target", "heat",
                        "totaltime", "cost", "heat_rate", "catching_up",
                        "temp_errors")


def _r2(value):
    '''round a display float to 2dp, or None when missing/unparsable.'''
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _history_row(pid, sample):
    '''one db sample -> HISTORY_COLS row. pid and sample are flat
    dicts keyed by storage column name (see _HISTORY_PID_KEYS /
    _HISTORY_SAMPLE_KEYS); kp/ki/kd/totaltime are filled from the
    firing row by the caller.'''
    if not isinstance(pid, dict):
        pid = {}
    row = []
    for col in HISTORY_COLS[:14]:
        key = _HISTORY_PID_KEYS[col]
        value = pid.get(key)
        if col == "t":
            try:
                row.append(float(value) if value is not None else None)
            except (TypeError, ValueError):
                row.append(None)
        elif col == "out":
            try:
                row.append(round(float(value), 4)
                           if value is not None else None)
            except (TypeError, ValueError):
                row.append(None)
        else:
            row.append(_r2(value))
    for key in _HISTORY_SAMPLE_KEYS:
        value = sample.get(key)
        if key in ("cu",):
            row.append(int(bool(value)))
        elif key in ("te",):
            try:
                row.append(int(value) if value is not None else None)
            except (TypeError, ValueError):
                row.append(None)
        else:
            row.append(_r2(value))
    return row


def _current_run_started():
    '''run_started of the firing in progress, or None. the watcher
    stamps it when a run begins (start button, schedule, api,
    automatic restart).'''
    try:
        started = getattr(ovenWatcher, 'started', None)
        return started.timestamp() if started else None
    except Exception:
        return None


@app.get('/api/history')
def api_history():
    '''full sample history of one firing from db/firings.db, oldest
    first. query ?run_started=<epoch> (from the status backlog), or
    omit it for the firing in progress. a single indexed query, so
    this runs in the request handler like the firing list. returns
    {run_started, profile, cols, rows}; rows are HISTORY_COLS arrays
    with rounded display floats (pid time t keeps full precision as
    the client dedupe key).'''
    wanted = bottle.request.query.get('run_started')
    if wanted:
        try:
            wanted = float(wanted)
        except (TypeError, ValueError):
            return bottle.HTTPResponse(
                json.dumps({"success": False,
                            "error": "invalid run_started"}),
                status=400,
                headers={'Content-Type': 'application/json'})
    else:
        wanted = _current_run_started()
        if wanted is None:
            return bottle.HTTPResponse(
                json.dumps({"success": False,
                            "error": "no firing in progress"}),
                status=404,
                headers={'Content-Type': 'application/json'})
    db = _open_read_db()
    if db is None:
        return bottle.HTTPResponse(
            json.dumps({"success": False,
                        "error": "could not open firing database"}),
            status=500,
            headers={'Content-Type': 'application/json'})
    try:
        frow = db._con.execute(
            "SELECT id, profile, run_started, totaltime, kp, ki, kd"
            " FROM firings WHERE run_started = ?",
            (wanted,)).fetchone()
        if frow is None:
            return bottle.HTTPResponse(
                json.dumps({"success": False,
                            "error": "firing not found"}),
                status=404,
                headers={'Content-Type': 'application/json'})
        srows = db._con.execute(
            "SELECT t, dt, err, ed, p, i, d, pid, out,"
            " runtime, temp, target, heat, cost, heat_rate,"
            " catching_up, temp_errors"
            " FROM samples WHERE firing_id = ? ORDER BY id",
            (frow[0],)).fetchall()
        rows = []
        for srow in srows:
            # pid/sample dicts are keyed by storage column name, as
            # _HISTORY_PID_KEYS / _HISTORY_SAMPLE_KEYS expect
            pid = {"t": srow[0], "dt": srow[1], "err": srow[2],
                   "ed": srow[3], "p": srow[4], "i": srow[5],
                   "d": srow[6], "pid": srow[7], "out": srow[8],
                   "target": srow[11], "temp": srow[10],
                   "kp": frow[4], "ki": frow[5], "kd": frow[6]}
            sample = {"runtime": srow[9], "temp": srow[10],
                      "target": srow[11], "heat": srow[12],
                      "totaltime": frow[3], "cost": srow[13],
                      "heat_rate": srow[14], "catching_up": srow[15],
                      "temp_errors": srow[16]}
            rows.append(_history_row(pid, sample))
        return json.dumps({"success": True, "run_started": frow[2],
                           "profile": frow[1],
                           "cols": HISTORY_COLS, "rows": rows})
    except bottle.HTTPResponse:
        raise
    except Exception as e:
        log.error("history export failed: %s" % e)
        return bottle.HTTPResponse(
            json.dumps({"success": False,
                        "error": "history export failed: %s" % e}),
            status=500,
            headers={'Content-Type': 'application/json'})
    finally:
        db.close()

def find_profile(wanted):
    '''
    given a wanted profile name, find it and return the parsed
    json profile object or None.
    profiles are stored in celsius, so the raw file is returned
    without any display-scale conversion.
    unreadable or invalid files are skipped so one corrupt profile
    cannot break running or scheduling a firing.
    '''
    try:
        profile_files = os.listdir(profile_path)
    except OSError:
        profile_files = []
    for filename in profile_files:
        path = os.path.join(profile_path, filename)
        try:
            with open(path, 'r') as f:
                profile = json.load(f)
        except Exception as e:
            log.error("skipping unreadable profile %s: %s" % (path, e))
            continue
        if not isinstance(profile, dict):
            log.error("skipping malformed profile %s" % (path))
            continue
        if profile.get('name') == wanted:
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
    alert_manager.emit('run_started',
                       context={'profile': wanted,
                                'startat_minutes': startat})
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
    chain_after = json_body.get('chain_after')
    if chain_after:
        if isinstance(chain_after, str) and chain_after.startswith('sched:'):
            anchor = chain_after[len('sched:'):]
            if not any(e['id'] == anchor for e in scheduler.list()):
                return { "success" : False, "error" : "chain_after schedule %s not found" % anchor }
        elif isinstance(chain_after, str) and chain_after.startswith('run:'):
            try:
                int(chain_after[len('run:'):])
            except ValueError:
                return { "success" : False, "error" : "invalid chain_after %s" % chain_after }
        else:
            return { "success" : False, "error" : "invalid chain_after %s" % chain_after }
    entry = scheduler.add(wanted, epoch, startat=startat, chain_after=chain_after)
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

def chain_anchor_ready(chain_after):
    '''True when the firing a scheduled run is chained after has actually
    ended. a run: anchor is satisfied once the oven has finished any firing
    whose sequence is at least the one it was created against (catch-up can
    stretch a firing, so the real end is when the oven stops being busy, not
    the nominal profile end). a sched: anchor is satisfied once that
    schedule has fired (started or was skipped).'''
    if chain_after.startswith('run:'):
        try:
            return oven.ended_run_sequence >= int(chain_after[len('run:'):])
        except (TypeError, ValueError):
            return False
    if chain_after.startswith('sched:'):
        anchor = chain_after[len('sched:'):]
        for entry in scheduler.list():
            if entry['id'] == anchor:
                return bool(entry.get('fired'))
        return False
    return False

def fire_scheduled_run(entry):
    '''
    callback used by the scheduler to start a scheduled kiln run.
    returns True if the run started.
    '''
    chain_after = entry.get("chain_after")
    if chain_after:
        # a chained firing starts shortly after the firing it follows
        # really ends, not at its estimated start_time.
        if not chain_anchor_ready(chain_after):
            return False
        if oven.state != "IDLE":
            return False
        if time.time() < oven.idle_since + config.schedule_chain_buffer:
            return False
    elif oven.state != "IDLE":
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
scheduler.alert_emit = alert_manager.emit

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

@app.get('/api/alerts')
def api_alerts():
    '''return the alert registry with enabled flags, ordered by
    criticality descending, plus the delivery settings, for the config
    tab alerts panel.'''
    return json.dumps({'success': True,
                       'alerts': alert_store.definitions(),
                       'delivery': alert_store.delivery_settings(),
                       'mqtt_configured': mqtt_enabled()})


@app.post('/api/alerts')
def api_alerts_save():
    '''enable or disable alerts and/or update delivery settings.
    body: {"enabled": {<alert_id>: <bool>},
           "delivery": {"mqtt_enabled": bool, "mqtt_topic": str,
                        "webhook_enabled": bool, "webhook_url": str}}
    both maps are optional but everything present is validated up front,
    so a bad request never partially saves. returns the full updated
    registry so clients can resync.'''
    body = bottle.request.json
    if not isinstance(body, dict) or \
            ('enabled' not in body and 'delivery' not in body):
        log.error("alerts save rejected: nothing to save in request")
        return bottle.HTTPResponse(json.dumps({"success": False,
                                               "error": "nothing to save"}),
                                   status=400,
                                   headers={'Content-Type': 'application/json'})
    updates = body.get('enabled')
    if 'enabled' in body:
        if not isinstance(updates, dict) or not updates:
            log.error("alerts save rejected: no enabled map in request")
            return bottle.HTTPResponse(json.dumps({"success": False,
                                                   "error": "no enabled map in request"}),
                                       status=400,
                                       headers={'Content-Type': 'application/json'})
        known_ids = {a['id'] for a in ALERTS}
        unknown = sorted(k for k in updates if k not in known_ids)
        if unknown:
            log.error("alerts save rejected: unknown ids %s" % unknown)
            return bottle.HTTPResponse(json.dumps({"success": False,
                                                   "error": "unknown alert ids: %s" % ', '.join(unknown)}),
                                       status=400,
                                       headers={'Content-Type': 'application/json'})
    delivery_updates = body.get('delivery', {})
    if not isinstance(delivery_updates, dict):
        log.error("alerts save rejected: delivery must be a map")
        return bottle.HTTPResponse(json.dumps({"success": False,
                                               "error": "delivery must be a map"}),
                                   status=400,
                                   headers={'Content-Type': 'application/json'})
    try:
        clean_delivery, _ = validate_delivery(delivery_updates)
    except ValueError as e:
        log.error("alerts save rejected: %s" % e)
        return bottle.HTTPResponse(json.dumps({"success": False,
                                               "error": str(e)}),
                                   status=400,
                                   headers={'Content-Type': 'application/json'})
    # everything validated; apply it all
    if 'enabled' in body:
        for alert_id, value in updates.items():
            alert_store.set_enabled(alert_id, value)
    if clean_delivery or 'delivery' in body:
        alert_store.set_delivery(clean_delivery)
    return {"success": True,
            "alerts": alert_store.definitions(),
            "delivery": alert_store.delivery_settings(),
            "mqtt_configured": mqtt_enabled()}

@app.post('/api/tune')
def handle_tune():
    '''PID auto-tuner endpoint. start begins a tuning run in a background
    greenlet, status returns current progress, stop aborts.'''
    body = bottle.request.json or {}
    cmd = body.get('cmd')

    if cmd == 'start':
        if oven.state not in ("IDLE", "TUNING"):
            return {"success": False,
                    "error": "cannot tune while a schedule is running (state: %s)" % oven.state}
        # only reject while a tuning run is actually in flight; DONE and
        # ERROR are terminal states that must allow starting again
        # (previously anything but IDLE was rejected, which locked the
        # tuner up after its first run)
        if tuner.state in (Tuner.HEATING, Tuner.COOLING, Tuner.CALCULATING):
            return {"success": False, "error": "tuner is already running"}

        target_temp = body.get('target_temp')
        if target_temp is None:
            return {"success": False, "error": "target_temp is required"}

        method = body.get('method', DEFAULT_METHOD)
        tangent_divisor = body.get('tangent_divisor', 8)

        try:
            target_c = to_c(float(target_temp))
        except (ValueError, TypeError):
            return {"success": False, "error": "invalid target_temp"}

        try:
            tangent_divisor = float(tangent_divisor)
        except (ValueError, TypeError):
            return {"success": False, "error": "invalid tangent_divisor"}

        if tangent_divisor < 2:
            return {"success": False, "error": "tangent_divisor must be >= 2"}

        log.info("api tune start: target=%.1f method=%s tangent_divisor=%.0f" %
                 (float(target_temp), method, tangent_divisor))
        threading.Thread(target=tuner.start, args=(target_c, method, tangent_divisor), daemon=True).start()
        return {"success": True}

    elif cmd == 'status':
        return {"success": True, **tuner.get_status()}

    elif cmd == 'stop':
        log.info("api tune stop")
        tuner.stop()
        return {"success": True}

    return {"success": False, "error": "unknown tune command"}

########################################################################
# community profiles - browse, download, and share profiles with the
# shared kiln-profiles github repo (see the settings in config.py).
# downloads are public; sharing forks the repo and opens a pull request
# using the sharer's own github token.

# a small cache for the remote listing so manual browsing doesn't slam
# the github api rate limit (60/hr unauthenticated)
_remote_cache = {"at": 0.0, "data": None}
REMOTE_CACHE_TTL = 60  # seconds


def _repo_owner_repo():
    '''parse "owner/repo" out of config.kiln_profiles_repo'''
    url = str(getattr(config, "kiln_profiles_repo", "")).rstrip("/")
    marker = "github.com/"
    if marker not in url:
        return None
    return url.split(marker, 1)[1].strip("/") or None


def _github_headers(token=None):
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "kiln-controller"}
    if token:
        headers["Authorization"] = "token %s" % token
    return headers


def _github_api_url(path):
    return "https://api.github.com/" + path.lstrip("/")


def _raw_url(path):
    repo = _repo_owner_repo()
    if not repo:
        return None
    return "https://raw.githubusercontent.com/%s/%s/%s" % (repo, config.kiln_profiles_branch, path)


def list_remote_profiles(force=False):
    '''list the categories and profiles in the community repo from the
    schedules.json index file. cached so manual browsing doesn't slam the
    github pages endpoint.'''
    if not force and _remote_cache["data"] is not None and time.time() - _remote_cache["at"] < REMOTE_CACHE_TTL:
        return _remote_cache["data"]
    index_url = str(getattr(config, "kiln_profiles_index_url", "")).strip()
    if not index_url:
        return {"success": False, "error": "kiln_profiles_index_url not configured"}
    try:
        resp = requests.get(index_url, headers=_github_headers(), timeout=15)
        resp.raise_for_status()
        index = resp.json()
        if not isinstance(index, list):
            return {"success": False, "error": "unexpected response from the kiln-profiles repo"}
        categories, tags, profiles = [], [], []
        seen_cats, seen_tags = set(), set()
        for entry in index:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            name = str(entry["name"])
            category = str(entry.get("category") or "uncategorized")
            entry_tags = [str(t) for t in (entry.get("tags") or []) if str(t).strip()]
            if category not in seen_cats:
                seen_cats.add(category)
                categories.append(category)
            for tag in entry_tags:
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    tags.append(tag)
            local_name = name + ".json"
            profiles.append({
                "category": category,
                "name": name,
                "path": "%s/%s" % (category, local_name),
                "tags": entry_tags,
                "description": entry.get("description") or "",
                "units": entry.get("units") or "",
                "installed": os.path.isfile(os.path.join(profile_path, local_name)),
            })
    except Exception as e:
        log.error("could not list community profiles: %s" % e)
        return {"success": False, "error": "could not reach the kiln-profiles repo: %s" % e}
    data = {"success": True, "upload_enabled": bool(_repo_owner_repo()),
            "categories": categories, "tags": tags, "profiles": profiles}
    _remote_cache.update({"at": time.time(), "data": data})
    return data


def import_profile(profile):
    '''save a community profile into the local profiles directory,
    normalizing it to the internal celsius convention. raises ValueError
    on invalid profiles.'''
    if not isinstance(profile, dict):
        raise ValueError("invalid profile")
    if not valid_profile_name(profile.get("name")):
        raise ValueError("invalid profile name")
    if not isinstance(profile.get("data"), list):
        raise ValueError("profile has no data")
    profile["name"] = str(profile["name"])
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
    token = str(body.get("github_token") or "").strip()
    if not token:
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "sharing is disabled (no github token provided)"}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    if not isinstance(profile, dict) or not profile.get("name"):
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "no profile in request"}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    name = str(profile["name"])
    if not valid_profile_name(name):
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
    try:
        pr_url, pr_number = share_profile_as_pr(profile, category, token)
    except Exception as e:
        log.error("could not submit community profile: %s" % e)
        return bottle.HTTPResponse(json.dumps({"success": False, "error": "share failed: %s" % e}),
                                   status=400,
                                   headers={"Content-Type": "application/json"})
    log.info("shared profile %s to %s as pull request #%s" % (name, category, pr_number))
    _remote_cache["data"] = None  # local installed state changed
    return json.dumps({"success": True, "name": name, "category": category,
                       "pr_url": pr_url, "pr_number": pr_number})


def _ensure_fork(owner_repo, token):
    '''return the "user/repo" of the authenticated user's fork of
    owner_repo, creating it if it does not exist and best-effort syncing
    it to the upstream default branch.'''
    user = requests.get(_github_api_url("user"), headers=_github_headers(token), timeout=15)
    user.raise_for_status()
    username = user.json()["login"]
    fork_repo = "%s/%s" % (username, owner_repo.split("/", 1)[1])
    if requests.get(_github_api_url("repos/%s" % fork_repo), headers=_github_headers(token),
                    timeout=15).status_code == 404:
        requests.post(_github_api_url("repos/%s/forks" % owner_repo),
                      json={"default_branch_only": True},
                      headers=_github_headers(token), timeout=15)
        # forking is asynchronous; poll until the fork is ready
        deadline = time.time() + 60
        while time.time() < deadline:
            # yield to the gevent hub instead of blocking it: this runs in
            # a request greenlet and gevent is not monkey-patched here
            gevent.sleep(2)
            if requests.get(_github_api_url("repos/%s" % fork_repo), headers=_github_headers(token),
                            timeout=15).status_code == 200:
                break
        else:
            raise RuntimeError("your fork did not finish syncing, try again in a moment")
    # best-effort: bring the fork's branch up to date with the upstream
    try:
        requests.post(_github_api_url("repos/%s/merge-upstream" % fork_repo),
                      json={"branch": config.kiln_profiles_branch},
                      headers=_github_headers(token), timeout=15)
    except Exception:
        pass
    return fork_repo


def share_profile_as_pr(profile, category, token):
    '''fork the kiln-profiles repo, commit the profile to a feature branch
    in the fork, and open a pull request back to the shared repo. returns
    the (html_url, number) of the pull request.'''
    name = profile["name"]
    owner_repo = _repo_owner_repo()
    branch = config.kiln_profiles_branch
    fork_repo = _ensure_fork(owner_repo, token)
    username = fork_repo.split("/", 1)[0]

    refs = requests.get(_github_api_url("repos/%s/git/ref/heads/%s" % (fork_repo, branch)),
                        headers=_github_headers(token), timeout=15)
    refs.raise_for_status()
    feature_branch = "kiln-share-%s" % re.sub(r"[^A-Za-z0-9_.-]", "-", name)
    requests.post(_github_api_url("repos/%s/git/refs" % fork_repo),
                  json={"ref": "refs/heads/%s" % feature_branch, "sha": refs.json()["object"]["sha"]},
                  headers=_github_headers(token), timeout=15)

    requests.put(_github_api_url("repos/%s/contents/%s/%s.json" % (fork_repo, category, name)),
                 json={
                     "message": "share %s" % name,
                     "content": base64.b64encode(json.dumps(profile).encode("utf-8")).decode("ascii"),
                     "branch": feature_branch,
                 },
                 headers=_github_headers(token), timeout=20)

    pr = requests.post(_github_api_url("repos/%s/pulls" % owner_repo),
                       json={
                           "title": "Add schedule %s (%s)" % (name, category),
                           "head": "%s:%s" % (username, feature_branch),
                           "base": branch,
                           "body": profile.get("description") or "Community kiln schedule.",
                       },
                       headers=_github_headers(token), timeout=20)
    pr.raise_for_status()
    pr_json = pr.json()
    return pr_json.get("html_url"), pr_json.get("number")

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
                try:
                    msgdict = json.loads(message)
                except ValueError as e:
                    # one bad message must not kill the control greenlet
                    log.error("ignoring malformed message: %s" % (e))
                    msgdict = {}
                if msgdict.get("cmd") == "RUN":
                    log.info("RUN command received")
                    profile_obj = msgdict.get('profile')
                    if not profile_obj:
                        # previously this fell through and raised
                        # NameError on the undefined profile variable,
                        # silently killing the websocket
                        log.error("RUN command without a profile, ignoring")
                    else:
                        try:
                            # the profile comes in display scale from the ui,
                            # store/use it internally in celsius
                            profile = Profile(json.dumps(add_temp_units(profile_obj)))
                            oven.run_profile(profile)
                            ovenWatcher.record(profile)
                        except Exception as e:
                            log.error("could not start run from control socket: %s" % (e))
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
            gevent.sleep(1)
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
                else:
                  msgdict["resp"] = "FAIL"
                wsock.send(json.dumps(msgdict))
                #wsock.send(get_profiles())
            elif msgdict.get("cmd") == "PUT":
                log.info("PUT command received")
                profile_obj = msgdict.get('profile')
                #force = msgdict.get('force', False)
                force = True
                if profile_obj:
                    #del msgdict["cmd"]
                    if not isinstance(profile_obj, dict) or \
                            not valid_profile_name(profile_obj.get('name')):
                        # invalid names are rejected up front (they
                        # would escape the profiles directory as
                        # filenames); the error travels back so the ui
                        # can show it instead of asking to overwrite
                        name = profile_obj.get('name') \
                            if isinstance(profile_obj, dict) \
                            else profile_obj
                        msgdict["resp"] = "FAIL"
                        msgdict["error"] = \
                            invalid_profile_name_error(name)
                    elif save_profile(profile_obj, force):
                        msgdict["resp"] = "OK"
                    else:
                        msgdict["resp"] = "FAIL"
                    log.debug("websocket (storage) sent: %s" % message)

                    wsock.send(json.dumps(msgdict))
                    wsock.send(get_profiles())
            gevent.sleep(1)
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
        gevent.sleep(1)
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
        gevent.sleep(1)
    log.info("websocket (status) closed")


def valid_profile_name(name):
    '''profile names become filenames under the profiles directory; keep
    them to a safe character set so a crafted name like "../foo" cannot
    read or write outside that directory'''
    if not name or not isinstance(name, str):
        return False
    return bool(re.match(r"^[A-Za-z0-9._-]+$", name))


def invalid_profile_name_error(name):
    '''human-readable reason a schedule name was rejected for saving.
    shown in the web ui, which slugifies names before sending but must
    still report server-side rejections.'''
    return ("invalid schedule name %r: use letters, numbers, dots, "
            "dashes and underscores (spaces become dashes)" % (name,))


def get_profiles():
    '''return all readable profiles in the display scale. corrupt or
    malformed files are skipped so one bad file cannot break the
    storage websocket for every client.'''
    try:
        profile_files = os.listdir(profile_path)
    except OSError:
        profile_files = []
    profiles = []
    for filename in profile_files:
        path = os.path.join(profile_path, filename)
        try:
            with open(path, 'r') as f:
                profile = json.load(f)
        except Exception as e:
            log.error("skipping unreadable profile %s: %s" % (path, e))
            continue
        if not isinstance(profile, dict):
            log.error("skipping malformed profile %s" % (path))
            continue
        profiles.append(profile)
    profiles = normalize_temp_units(profiles)
    return json.dumps(sorted(profiles, key=lambda x: x.get("name", "")))


def save_profile(profile, force=False):
    if not isinstance(profile, dict) or not valid_profile_name(profile.get('name')):
        log.error("refusing to save profile with unsafe name %r" % (profile.get('name') if isinstance(profile, dict) else profile,))
        return False
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
    _remote_cache["data"] = None  # community "installed" state changed
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
    if not isinstance(profile, dict) or not valid_profile_name(profile.get('name')):
        log.error("refusing to delete profile with unsafe name %r" % (profile.get('name') if isinstance(profile, dict) else profile,))
        return False
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    os.remove(filepath)
    log.info("Deleted %s" % filepath)
    _remote_cache["data"] = None  # community "installed" state changed
    return True

def get_config():
    return json.dumps({"simulate": config.simulate,
        "temp_scale": config.temp_scale,
        "time_scale_slope": config.time_scale_slope,
        "time_scale_profile": config.time_scale_profile,
        "kwh_rate": config.kwh_rate,
        "currency_type": config.currency_type,
        "github_sharing_enabled": bool(_repo_owner_repo())})    

def main():
    ip = "0.0.0.0"
    port = config.listening_port
    log.info("listening on %s:%d" % (ip, port))
    alert_manager.emit('controller_restarted',
                       context={'simulate': bool(config.simulate),
                                'port': port})

    # run the scheduled runs background loop. this is a gevent greenlet
    # that yields to the hub, so it must NOT use blocking time.sleep.
    # gevent is not monkey-patched in this project.
    def schedule_tick():
        scheduler.fire_due()
        gevent.spawn_later(config.schedule_poll_interval, schedule_tick)

    gevent.spawn_later(config.schedule_poll_interval, schedule_tick)

    # the firing list/csv export reads db/firings.db directly (indexed
    # queries, milliseconds), so no snapshot warm-up is needed here.
    # (the journal snapshot machinery above stays for log diagnostics.)

    server = WSGIServer((ip, port), app,
                        handler_class=WebSocketHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
