import json
import threading
import types

import pytest

import ovenWatcher
import config


class FakeOven:
    def __init__(self, state="IDLE"):
        self.time_step = 1
        self.state = state

    def get_state(self):
        return {
            'state': self.state,
            'temperature': 100,
            'target': 200,
            'runtime': 60,
        }


def make_watcher(state="IDLE"):
    # construct without starting the real thread
    watcher = ovenWatcher.OvenWatcher.__new__(ovenWatcher.OvenWatcher)
    threading.Thread.__init__(watcher)
    watcher.last_profile = None
    watcher.started = None
    watcher.observers = []
    watcher.mqtt = None
    watcher.daemon = True
    watcher.oven = FakeOven(state)
    return watcher


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.dead = False

    def send(self, message):
        if self.dead:
            raise OSError("socket closed")
        self.sent.append(message)


def test_watcher_is_daemon_thread():
    watcher = make_watcher()
    assert watcher.daemon is True


def test_record():
    watcher = make_watcher()
    profile = types.SimpleNamespace(name="test-fast", data=[[0, 200]])
    watcher.record(profile)
    assert watcher.last_profile is profile
    assert watcher.started is not None


def test_add_observer_sends_backlog():
    watcher = make_watcher()
    # the backlog profile data is celsius internally, it is reported
    # in the display scale (f by default)
    profile = types.SimpleNamespace(name="test-fast", data=[[0, 200]])
    watcher.record(profile)
    sock = FakeSocket()
    watcher.add_observer(sock)
    assert len(sock.sent) == 1
    payload = json.loads(sock.sent[0])
    assert payload['type'] == 'backlog'
    assert payload['profile']['name'] == 'test-fast'
    assert payload['profile']['data'][0][0] == 0
    assert payload['profile']['data'][0][1] == pytest.approx(392.0)  # 200c -> 392f
    assert 'log' not in payload


def test_backlog_profile_data_c_scale(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'c')
    watcher = make_watcher()
    profile = types.SimpleNamespace(name="test-fast", data=[[0, 200]])
    watcher.record(profile)
    sock = FakeSocket()
    watcher.add_observer(sock)
    payload = json.loads(sock.sent[0])
    assert payload['profile']['data'] == [[0, 200]]  # celsius stays as-is


def test_backlog_includes_run_started():
    watcher = make_watcher()
    profile = types.SimpleNamespace(name="test-fast", data=[[0, 200]])
    watcher.record(profile)
    sock = FakeSocket()
    watcher.add_observer(sock)
    payload = json.loads(sock.sent[0])
    assert payload['run_started'] == watcher.started.timestamp()


def test_backlog_run_started_null_when_idle():
    watcher = make_watcher()
    sock = FakeSocket()
    watcher.add_observer(sock)
    payload = json.loads(sock.sent[0])
    assert payload['run_started'] is None


def test_run_loop_stamps_run_started(monkeypatch):
    watcher = make_watcher(state="RUNNING")
    profile = types.SimpleNamespace(name="test-fast", data=[[0, 200]])
    watcher.record(profile)
    sock = FakeSocket()
    watcher.observers.append(sock)

    sleeps = [0]

    def fake_sleep(secs):
        sleeps[0] += 1
        if sleeps[0] >= 2:
            raise StopIteration

    monkeypatch.setattr(ovenWatcher.time, 'sleep', fake_sleep)

    with pytest.raises(StopIteration):
        watcher.run()

    payload = json.loads(sock.sent[0])
    assert payload['run_started'] == watcher.started.timestamp()


def test_add_observer_no_profile():
    watcher = make_watcher()
    sock = FakeSocket()
    watcher.add_observer(sock)
    payload = json.loads(sock.sent[0])
    assert payload['profile'] is None


def test_notify_all_sends_state():
    watcher = make_watcher()
    sock = FakeSocket()
    watcher.observers.append(sock)
    watcher.notify_all({'temperature': 123})
    assert json.loads(sock.sent[-1]) == {'temperature': 123}


def test_notify_all_removes_dead_socket():
    watcher = make_watcher()
    sock = FakeSocket()
    watcher.observers.append(sock)
    sock.dead = True
    watcher.notify_all({'temperature': 123})
    assert sock not in watcher.observers


def test_notify_all_removes_adjacent_dead_sockets():
    '''removing while iterating used to skip the socket right after a
    dead one, leaving it in the list for another round'''
    watcher = make_watcher()
    alive = FakeSocket()
    dead1, dead2 = FakeSocket(), FakeSocket()
    dead1.dead = dead2.dead = True
    watcher.observers.extend([dead1, dead2, alive])

    watcher.notify_all({'temperature': 123})

    assert watcher.observers == [alive]
    assert json.loads(alive.sent[-1]) == {'temperature': 123}


def test_add_observer_then_notify_all():
    watcher = make_watcher()
    sock = FakeSocket()
    watcher.add_observer(sock)
    watcher.notify_all({'state': 'RUNNING'})
    # first message is the backlog, then the state
    assert json.loads(sock.sent[1]) == {'state': 'RUNNING'}


def test_run_loop(monkeypatch):
    watcher = make_watcher(state="RUNNING")
    sock = FakeSocket()
    watcher.observers.append(sock)

    sleeps = [0]

    def fake_sleep(secs):
        sleeps[0] += 1
        if sleeps[0] >= 2:
            raise StopIteration

    monkeypatch.setattr(ovenWatcher.time, 'sleep', fake_sleep)

    with pytest.raises(StopIteration):
        watcher.run()

    assert len(sock.sent) == 2
    assert json.loads(sock.sent[0])['state'] == 'RUNNING'


class FakeMqttOut:
    def __init__(self):
        self.published = []

    def publish(self, state):
        self.published.append(state)


def test_run_loop_publishes_to_mqtt_when_enabled(monkeypatch):
    watcher = make_watcher(state="RUNNING")
    profile = types.SimpleNamespace(name="test-fast", data=[[0, 200]])
    watcher.record(profile)
    mqtt = FakeMqttOut()
    watcher.mqtt = mqtt
    sock = FakeSocket()
    watcher.observers.append(sock)

    sleeps = [0]

    def fake_sleep(secs):
        sleeps[0] += 1
        if sleeps[0] >= 2:
            raise StopIteration

    monkeypatch.setattr(ovenWatcher.time, 'sleep', fake_sleep)

    with pytest.raises(StopIteration):
        watcher.run()

    assert len(mqtt.published) == 2
    assert mqtt.published[0]['state'] == 'RUNNING'
    assert mqtt.published[0]['run_started'] == watcher.started.timestamp()


def test_run_loop_skips_mqtt_when_disabled(monkeypatch):
    watcher = make_watcher(state="RUNNING")
    sock = FakeSocket()
    watcher.observers.append(sock)

    sleeps = [0]

    def fake_sleep(secs):
        sleeps[0] += 1
        if sleeps[0] >= 2:
            raise StopIteration

    monkeypatch.setattr(ovenWatcher.time, 'sleep', fake_sleep)

    with pytest.raises(StopIteration):
        watcher.run()

    assert len(sock.sent) == 2


def test_watcher_init_creates_mqtt_only_when_enabled(monkeypatch):
    monkeypatch.setattr(ovenWatcher.OvenWatcher, 'start', lambda self: None)
    monkeypatch.setattr(ovenWatcher, 'mqtt_enabled', lambda: False)
    instances = []

    def fake_mqttout():
        obj = object()
        instances.append(obj)
        return obj

    monkeypatch.setattr(ovenWatcher, 'MqttOut', fake_mqttout)

    watcher = make_watcher(state="IDLE")
    ovenWatcher.OvenWatcher.__init__(watcher, watcher.oven)

    assert instances == []
    assert watcher.mqtt is None


def test_watcher_init_creates_mqtt_when_enabled(monkeypatch):
    monkeypatch.setattr(ovenWatcher.OvenWatcher, 'start', lambda self: None)
    monkeypatch.setattr(ovenWatcher, 'mqtt_enabled', lambda: True)
    instances = []

    def fake_mqttout():
        obj = object()
        instances.append(obj)
        return obj

    monkeypatch.setattr(ovenWatcher, 'MqttOut', fake_mqttout)

    watcher = make_watcher(state="IDLE")
    ovenWatcher.OvenWatcher.__init__(watcher, watcher.oven)

    assert len(instances) == 1
    assert watcher.mqtt is instances[0]


def test_add_observer_send_failure_logged(caplog):
    watcher = make_watcher()
    profile = types.SimpleNamespace(name="test-fast", data=[[0, 200]])
    watcher.record(profile)
    dead = FakeSocket()
    dead.dead = True
    watcher.add_observer(dead)
    assert watcher.observers == [dead]
    assert any('Could not send backlog' in r.message for r in caplog.records)


def test_notify_all_removes_falsy_observer():
    watcher = make_watcher()
    sock = FakeSocket()
    watcher.observers = [sock, None]
    watcher.notify_all({'state': 'IDLE'})
    assert watcher.observers == [sock]
