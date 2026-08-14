import json
import os
import sys
import types

import pytest

import config
import mqttout


class FakeClient:
    def __init__(self, rc=0, connect_error=None, publish_error=None):
        self.rc = rc
        self.connect_error = connect_error
        self.publish_error = publish_error
        self.calls = []
        self.loop_started = False
        self.published = []

    def username_pw_set(self, user, password):
        self.calls.append(('userpass', user, password))

    def connect(self, host, port):
        if self.connect_error:
            raise self.connect_error
        self.calls.append(('connect', host, port))

    def loop_start(self):
        self.loop_started = True

    def publish(self, topic, payload):
        if self.publish_error:
            raise self.publish_error
        self.published.append((topic, payload))
        return types.SimpleNamespace(rc=self.rc)


@pytest.fixture
def mqtt_config(monkeypatch):
    def set(enable=True, **kw):
        monkeypatch.setattr(config, 'mqtt_enable', enable, raising=False)
        for key, value in kw.items():
            monkeypatch.setattr(config, key, value, raising=False)
    return set


def test_disabled_by_default(monkeypatch):
    monkeypatch.delattr(config, 'mqtt_enable', raising=False)
    out = mqttout.MqttOut()
    assert out.enabled is False
    assert out.client is None


def test_publish_noop_when_disabled(monkeypatch):
    monkeypatch.delattr(config, 'mqtt_enable', raising=False)
    out = mqttout.MqttOut(client_cls=FakeClient)
    out.publish({'temperature': 100})
    assert out.client is None


def test_connect_and_publish(mqtt_config, monkeypatch):
    mqtt_config(enable=True, mqtt_host='broker.home', mqtt_port=1884,
                mqtt_user='u', mqtt_pass='p', mqtt_topic='kiln/upstairs',
                mqtt_kiln_name='my-kiln')
    client = FakeClient()
    out = mqttout.MqttOut(client_cls=lambda: client)

    assert out.enabled is True
    assert out.client is client
    assert client.loop_started is True
    assert ('connect', 'broker.home', 1884) in client.calls
    assert ('userpass', 'u', 'p') in client.calls

    out.publish({'state': 'RUNNING', 'temperature': 212.0})

    assert len(client.published) == 1
    topic, payload = client.published[0]
    assert topic == 'kiln/upstairs'
    message = json.loads(payload)
    assert message['state'] == 'RUNNING'
    assert message['temperature'] == 212.0
    assert message['name'] == 'my-kiln'


def test_defaults_when_settings_absent(mqtt_config, monkeypatch):
    for attr in ('mqtt_host', 'mqtt_port', 'mqtt_topic', 'mqtt_kiln_name',
                 'mqtt_user', 'mqtt_pass'):
        monkeypatch.delattr(config, attr, raising=False)
    mqtt_config(enable=True)
    client = FakeClient()
    out = mqttout.MqttOut(client_cls=lambda: client)

    assert ('connect', 'localhost', 1883) in client.calls
    out.publish({'state': 'IDLE'})
    assert client.published[0][0] == 'kiln/sensor'
    # no kiln name configured, so nothing is added to the payload
    assert json.loads(client.published[0][1]) == {'state': 'IDLE'}


def test_publish_does_not_mutate_state(mqtt_config):
    mqtt_config(enable=True, mqtt_topic='kiln/sensor', mqtt_kiln_name='my-kiln')
    client = FakeClient()
    out = mqttout.MqttOut(client_cls=lambda: client)
    state = {'state': 'RUNNING', 'temperature': 100}
    out.publish(state)
    assert state == {'state': 'RUNNING', 'temperature': 100}
    assert 'name' not in state


def test_publish_error_rc_logged(mqtt_config, caplog):
    mqtt_config(enable=True, mqtt_topic='kiln/sensor')
    client = FakeClient(rc=4)
    out = mqttout.MqttOut(client_cls=lambda: client)
    out.publish({'state': 'IDLE'})
    assert any('mqtt publish returned rc=4' in r.message for r in caplog.records)


def test_publish_exception_caught(mqtt_config, caplog):
    mqtt_config(enable=True, mqtt_topic='kiln/sensor')
    client = FakeClient(publish_error=OSError('broker gone'))
    out = mqttout.MqttOut(client_cls=lambda: client)
    out.publish({'state': 'IDLE'})  # must not raise
    assert any('mqtt publish failed' in r.message for r in caplog.records)


def test_connect_failure_disables_client(mqtt_config, caplog):
    mqtt_config(enable=True, mqtt_host='broker.home')
    out = mqttout.MqttOut(client_cls=lambda: FakeClient(connect_error=OSError('refused')))
    assert out.client is None
    out.publish({'state': 'IDLE'})  # must not raise


def test_paho_not_imported_when_disabled(monkeypatch):
    monkeypatch.delattr(config, 'mqtt_enable', raising=False)
    monkeypatch.delattr(config, 'mqtt_host', raising=False)
    mqttout.MqttOut()
    assert 'paho' not in sys.modules


def test_paho_listed_in_requirements():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    with open(os.path.join(root, 'requirements.txt')) as f:
        requirements = f.read()
    assert 'paho-mqtt' in requirements
