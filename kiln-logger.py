#!/usr/bin/env python
'''kiln-logger: record a firing to a csv file for offline analysis.

Connects to the kiln-controller status websocket and appends every
broadcast it receives to a csv file, one row per sample (the controller
broadcasts oven state every config.sensor_time_wait seconds, 2s by
default). The web ui draws its live charts from this same feed; this
script is the "write it to disk" client, useful for spreadsheets,
pandas, or attaching to a bug report.

Run it while the controller is up (a firing does not have to be in
progress -- idle states are logged too), then let it run for the whole
firing. It exits only when killed (ctrl-c):

    source venv/bin/activate
    ./kiln-logger.py --hostname kiln.local:8081 --csvfile firing.csv

Options:
    --hostname        host:port of the controller (default localhost:8081)
    --csvfile         output csv path (default /tmp/kilnstats.csv)
    --pidstats        include PID columns (p, i, d, err, out, ...)
    --noprofilestats  omit the standard profile columns
    --stdout          also print each row to the terminal (tab separated)

Behavior notes:
    * 'stamp' records when the logger received the message locally, not
      when the controller produced it.
    * the first message on a new connection ("backlog") carries profile
      and run metadata rather than a sample, so it is not written.
    * if the connection drops the logger retries every 5 seconds and
      keeps appending to the same file.
'''

import websocket
import json
import time
import csv
import argparse
import sys


# columns written by default: the standard oven-state broadcast.
# 'stamp' is added locally at receive time; the rest come from the
# controller's status message (see oven.get_state()).
STD_HEADER = [
    'stamp',
    'runtime',
    'temperature',
    'target',
    'state',
    'heat',
    'totaltime',
    'profile',
]


# extra columns written with --pidstats: the message's nested pidstats
# dict (see PID.compute) flattened into pid_<name> columns.
PID_HEADER = [
    'pid_time',
    'pid_timeDelta',
    'pid_setpoint',
    'pid_ispoint',
    'pid_err',
    'pid_errDelta',
    'pid_p',
    'pid_i',
    'pid_d',
    'pid_kp',
    'pid_ki',
    'pid_kd',
    'pid_pid',
    'pid_out',
]


def logger(hostname, csvfile, noprofilestats, pidstats, stdout):
    '''subscribe to ws://<hostname>/status and append every broadcast
    to csvfile. never returns; kill the process (ctrl-c) to stop.'''
    status_ws = websocket.WebSocket()

    csv_fields = []
    if not noprofilestats:
        csv_fields += STD_HEADER
    if pidstats:
        csv_fields += PID_HEADER

    out = open(csvfile, 'w')
    csv_out = csv.DictWriter(out, csv_fields, extrasaction='ignore')
    csv_out.writeheader()

    if stdout:
        csv_stdout = csv.DictWriter(sys.stdout, csv_fields, extrasaction='ignore', delimiter='\t')
        csv_stdout.writeheader()
    else:
        csv_stdout = None

    while True:
        try:
            msg = json.loads(status_ws.recv())

        except websocket.WebSocketException:
            # connection dropped or never came up: retry until it works
            try:
                status_ws.connect(f'ws://{hostname}/status')
            except Exception:
                time.sleep(5)

            continue

        if msg.get('type') == 'backlog':
            # run metadata sent once to each new client, not a sample
            continue

        if not noprofilestats:
            # the broadcast carries no wall clock of its own, so stamp
            # rows with our local receive time
            msg['stamp'] = time.time()
        if pidstats and 'pidstats' in msg:
            # flatten the nested pidstats dict into pid_<name> columns
            for k, v in msg.get('pidstats', {}).items():
                msg[f"pid_{k}"] = v

        csv_out.writerow(msg)
        out.flush()

        if stdout:
            for k in list(msg.keys()):
                v = msg[k]
                if isinstance(v, float):
                    msg[k] = '{:5.3f}'.format(v)
            csv_stdout.writerow(msg)
            sys.stdout.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Log kiln data for analysis.')
    parser.add_argument('--hostname', type=str, default="localhost:8081", help="The kiln-controller hostname:port")
    parser.add_argument('--csvfile', type=str, default="/tmp/kilnstats.csv", help="Where to write the kiln stats to")
    parser.add_argument('--pidstats', action='store_true', help="Include PID stats")
    parser.add_argument('--noprofilestats', action='store_true', help="Do not store profile stats (default is to store them)")
    parser.add_argument('--stdout', action='store_true', help="Also print to stdout")
    args = parser.parse_args()

    logger(args.hostname, args.csvfile, args.noprofilestats, args.pidstats, args.stdout)
