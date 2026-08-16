import importlib.util
import json
import os

import pytest


def load_logger():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'kiln-logger.py'))
    spec = importlib.util.spec_from_file_location('kiln_logger', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


logger_mod = load_logger()


def test_headers():
    assert logger_mod.STD_HEADER == [
        'stamp', 'runtime', 'temperature', 'target', 'state', 'heat',
        'totaltime', 'profile']
    assert 'pid_pid' in logger_mod.PID_HEADER
    assert 'pid_out' in logger_mod.PID_HEADER


class FakeStatusWS:
    def __init__(self, messages):
        self.messages = list(messages)
        self.connected = False

    def recv(self):
        if self.messages:
            return self.messages.pop(0)
        raise logger_mod.websocket.WebSocketException("no more messages")

    def connect(self, url):
        self.connected = True
        raise Exception("cannot connect")


def run_logger(monkeypatch, tmp_path, messages, **kwargs):
    fake_ws = FakeStatusWS(messages)
    monkeypatch.setattr(logger_mod.websocket, 'WebSocket', lambda: fake_ws)

    sleeps = [0]

    def fake_sleep(secs):
        sleeps[0] += 1
        raise StopIteration

    monkeypatch.setattr(logger_mod.time, 'sleep', fake_sleep)

    csvfile = str(tmp_path / 'out.csv')
    stdout = kwargs.pop('stdout', False)
    with pytest.raises(StopIteration):
        logger_mod.logger('localhost:9099', csvfile, stdout=stdout, **kwargs)
    return csvfile, fake_ws


def make_state(runtime, **extra):
    msg = {
        'state': 'RUNNING',
        'runtime': runtime,
        'temperature': 200.0,
        'target': 300.0,
        'heat': 1,
        'totaltime': 1000,
        'profile': 'test-fast',
    }
    msg.update(extra)
    return msg


def read_csv(csvfile):
    import csv
    with open(csvfile) as f:
        return list(csv.DictReader(f))


def test_logger_writes_profile_and_pid_stats(monkeypatch, tmp_path):
    state = make_state(10, pidstats={'pid': 0.5, 'out': 0.25})
    messages = [
        json.dumps({'type': 'backlog', 'profile': None}),  # skipped
        json.dumps(state),
    ]
    csvfile, fake_ws = run_logger(monkeypatch, tmp_path, messages,
                                  noprofilestats=False, pidstats=True)

    rows = read_csv(csvfile)
    assert len(rows) == 1
    row = rows[0]
    assert row['state'] == 'RUNNING'
    assert row['runtime'] == '10'
    assert row['temperature'] == '200.0'
    assert row['stamp'] != ''
    assert row['pid_pid'] == '0.5'
    assert row['pid_out'] == '0.25'
    # raw nested pidstats must not leak through
    assert 'pidstats' not in row


def test_logger_skips_backlog(monkeypatch, tmp_path):
    state = make_state(10)
    messages = [
        json.dumps({'type': 'backlog', 'profile': None}),
        json.dumps(state),
    ]
    csvfile, _ = run_logger(monkeypatch, tmp_path, messages,
                            noprofilestats=False, pidstats=False)
    rows = read_csv(csvfile)
    assert len(rows) == 1


def test_logger_noprofilestats_drops_profile_fields(monkeypatch, tmp_path):
    state = make_state(10, pidstats={'pid': 0.5})
    messages = [json.dumps(state)]
    csvfile, _ = run_logger(monkeypatch, tmp_path, messages,
                            noprofilestats=True, pidstats=True)
    rows = read_csv(csvfile)
    assert len(rows) == 1
    row = rows[0]
    assert 'stamp' not in row
    assert 'runtime' not in row
    assert 'pid_pid' in row
    assert row['pid_pid'] == '0.5'


def test_logger_stdout_also_writes_stdout(monkeypatch, tmp_path, capsys):
    state = make_state(10)
    messages = [json.dumps(state)]
    csvfile, _ = run_logger(monkeypatch, tmp_path, messages,
                            noprofilestats=False, pidstats=False, stdout=True)
    out = capsys.readouterr().out
    # stdout has a header + one data row
    assert 'runtime' in out
    assert '10' in out
    rows = read_csv(csvfile)
    assert len(rows) == 1


def test_logger_reconnects_on_websocket_error(monkeypatch, tmp_path):
    messages = [
        json.dumps(make_state(10)),
        json.dumps(make_state(20)),
    ]
    csvfile, fake_ws = run_logger(monkeypatch, tmp_path, messages,
                                  noprofilestats=False, pidstats=False)
    # recv exhausted -> WebSocketException -> connect() attempted
    assert fake_ws.connected is True
    rows = read_csv(csvfile)
    assert len(rows) == 2


def test_logger_reconnects_after_websocket_error(monkeypatch, tmp_path):
    sleeps = [0]

    def fake_sleep(secs):
        sleeps[0] += 1
        if sleeps[0] >= 2:
            raise StopIteration

    monkeypatch.setattr(logger_mod.websocket, 'WebSocket',
                        lambda: FakeStatusWS([]))
    monkeypatch.setattr(logger_mod.time, 'sleep', fake_sleep)

    csvfile = str(tmp_path / 'out.csv')
    with pytest.raises(StopIteration):
        logger_mod.logger('localhost:9099', csvfile,
                          noprofilestats=True, pidstats=False, stdout=False)
    assert sleeps[0] == 2
