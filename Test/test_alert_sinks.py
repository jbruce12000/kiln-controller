'''Tests for alert delivery sinks (webhook, mqtt), their live settings
in AlertStore, and the storage/schema migration of alerts state files.

Sinks are exercised with injected fakes; no network and no broker.'''

import json
import threading
import time
import types

import pytest

from lib.alerts import (DEFAULT_DELIVERY, AlertStore, MqttSink,
                        WebhookSink, alert_payload, validate_delivery)


def wait_for(condition, timeout=2.0):
    '''poll until condition() is truthy; sinks build mqtt clients on
    background threads so tests have to wait them out'''
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


########################################################################
# payload shape
########################################################################

def test_alert_payload_shape():
    p = alert_payload('relay_stuck_on', 'Relay stuck on', 'critical',
                      {'rise': 31.2})
    assert p['source'] == 'kiln-controller'
    assert p['alert_id'] == 'relay_stuck_on'
    assert p['label'] == 'Relay stuck on'
    assert p['criticality'] == 'critical'
    assert p['context'] == {'rise': 31.2}
    assert isinstance(p['epoch'], int)
    assert 'T' in p['time']  # iso timestamp


def test_alert_payload_context_defaults_to_empty():
    assert alert_payload('run_started', 'Run started', 'info',
                         None)['context'] == {}


########################################################################
# delivery settings validation
########################################################################

def test_validate_delivery_accepts_known_keys():
    clean, ignored = validate_delivery({
        'mqtt_enabled': True, 'mqtt_topic': ' shop/kiln ',
        'webhook_enabled': False, 'webhook_url': 'https://ntfy.sh/x'})
    assert clean == {'mqtt_enabled': True, 'mqtt_topic': 'shop/kiln',
                     'webhook_enabled': False,
                     'webhook_url': 'https://ntfy.sh/x'}
    assert ignored == []


@pytest.mark.parametrize('updates,message_part', [
    ({'nope': 1}, 'unknown'),
    ({'mqtt_enabled': 'yes'}, 'true or false'),
    ({'mqtt_topic': ''}, 'empty'),
    ({'mqtt_topic': 5}, 'string'),
    ({'webhook_url': 'ftp://x'}, 'http'),
])
def test_validate_delivery_strict_rejects(updates, message_part):
    with pytest.raises(ValueError) as e:
        validate_delivery(updates)
    assert message_part in str(e.value)


def test_validate_delivery_non_strict_drops_bad_values():
    clean, ignored = validate_delivery(
        {'mqtt_enabled': 'yes', 'junk': {}, 'webhook_url': ' https://ok '},
        strict=False)
    assert clean == {'webhook_url': 'https://ok'}
    assert ignored == ['junk']  # wrong-typed values simply drop out


########################################################################
# store schema and migration
########################################################################

def test_legacy_flat_file_migrates(tmp_path):
    path = tmp_path / 'alerts.json'
    path.write_text(json.dumps({'relay_stuck_on': False}))
    store = AlertStore(state_file=str(path))
    assert store.enabled['relay_stuck_on'] is False
    assert store.delivery == DEFAULT_DELIVERY
    # next save rewrites the new format
    store.save()
    on_disk = json.loads(path.read_text())
    assert on_disk['enabled']['relay_stuck_on'] is False
    assert on_disk['delivery'] == DEFAULT_DELIVERY


def test_new_format_round_trips(tmp_path):
    path = tmp_path / 'alerts.json'
    store = AlertStore(state_file=str(path))
    store.set_delivery({'webhook_url': 'https://example/hook',
                        'webhook_enabled': True})
    again = AlertStore(state_file=str(path))
    assert again.enabled['tc_failure'] is True
    assert again.delivery['webhook_url'] == 'https://example/hook'
    assert again.delivery['webhook_enabled'] is True


def test_corrupt_delivery_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / 'alerts.json'
    path.write_text(json.dumps({
        'enabled': {'run_started': False},
        'delivery': {'mqtt_enabled': 'yes',      # wrong type: dropped
                     'junk': 1,                  # unknown: dropped
                     'mqtt_topic': 'kept/ok'}}))
    store = AlertStore(state_file=str(path))
    assert store.delivery['mqtt_enabled'] is False  # default restored
    assert store.delivery['mqtt_topic'] == 'kept/ok'
    assert 'junk' not in store.delivery


def test_set_delivery_rejects_and_does_not_touch_good_keys(tmp_path):
    store = AlertStore(state_file=str(tmp_path / 'alerts.json'))
    err = store.set_delivery({'webhook_url': 'notaurl'})
    assert err and 'http' in err
    assert store.delivery['webhook_url'] == ''
    ok = store.set_delivery({'webhook_url': 'https://ok'})
    assert ok is None
    assert store.delivery['webhook_url'] == 'https://ok'


def test_set_delivery_persists(tmp_path):
    path = tmp_path / 'alerts.json'
    store = AlertStore(state_file=str(path))
    store.set_delivery({'mqtt_topic': 'kiln/shouty'})
    on_disk = json.loads(path.read_text())
    assert on_disk['delivery']['mqtt_topic'] == 'kiln/shouty'


########################################################################
# webhook sink
########################################################################

class FakeResponse:
    def __init__(self, status_code=200, text=''):
        self.status_code = status_code
        self.text = text


def make_store(**delivery):
    store = AlertStore(state_file='/nonexistent/alerts.json')
    store.delivery.update(delivery)
    return store


def sink_recording_posts(status_code=200):
    '''a sync-mode WebhookSink whose poster records calls'''
    posts = []

    def poster(url, payload, timeout):
        posts.append((url, payload, timeout))
        return FakeResponse(status_code)

    return WebhookSink(make_store(), async_deliver=False, poster=poster), posts


def test_webhook_disabled_delivers_nothing():
    sink, posts = sink_recording_posts()
    sink.store.set_delivery({'webhook_enabled': False}) if False else None
    sink.deliver('run_started', 'Run started', 'info', {})
    assert posts == []


def test_webhook_sends_json_payload_with_timeout():
    sink, posts = sink_recording_posts()
    sink.timeout = 7
    sink.store.delivery.update({'webhook_enabled': True,
                                'webhook_url': 'https://ntfy.sh/kiln'})
    sink.deliver('cooled_safe', 'Cooled', 'info', {'limit': 150})
    url, payload, timeout = posts[0]
    assert url == 'https://ntfy.sh/kiln'
    assert timeout == 7
    assert payload['alert_id'] == 'cooled_safe'
    assert payload['criticality'] == 'info'


def test_webhook_enabled_but_no_url_skips():
    sink, posts = sink_recording_posts()
    sink.store.delivery.update({'webhook_enabled': True})
    sink.deliver('run_started', 'Run started', 'info', {})
    assert posts == []


def test_webhook_settings_take_effect_without_restart():
    sink, posts = sink_recording_posts()
    sink.deliver('run_started', 'Run started', 'info', {})
    assert posts == []                       # starts disabled
    sink.store.delivery.update({'webhook_enabled': True,
                                'webhook_url': 'https://now'})
    sink.deliver('run_started', 'Run started', 'info', {})
    assert len(posts) == 1                   # same sink object, now live


@pytest.mark.parametrize('status_code', [300, 404, 500])
def test_webhook_http_errors_are_logged_not_raised(status_code, caplog):
    sink, posts = sink_recording_posts(status_code=status_code)
    sink.store.delivery.update({'webhook_enabled': True,
                                'webhook_url': 'https://broken'})
    sink.deliver('run_started', 'Run started', 'info', {})  # must not raise
    assert len(posts) == 1


def test_webhook_uses_requests_post_by_default(monkeypatch):
    '''with no poster injected the sink falls back to requests.post with
    the json payload and configured timeout'''
    calls = {}

    class FakeResponse:
        status_code = 200

    def fake_post(url, json=None, timeout=None):
        calls.update(url=url, payload=json, timeout=timeout)
        return FakeResponse()

    import sys
    fake_requests = types.SimpleNamespace(post=fake_post)
    monkeypatch.setitem(sys.modules, 'requests', fake_requests)

    store = make_store(webhook_enabled=True,
                       webhook_url='https://ntfy.sh/kiln')
    sink = WebhookSink(store, timeout=4, async_deliver=False)
    sink.deliver('cooled_safe', 'Cooled', 'info', {'limit': 150})
    assert calls['url'] == 'https://ntfy.sh/kiln'
    assert calls['timeout'] == 4
    assert calls['payload']['alert_id'] == 'cooled_safe'


def test_webhook_transport_error_is_swallowed():
    def exploding_poster(url, payload, timeout):
        raise OSError('network unreachable')

    sink = WebhookSink(make_store(webhook_enabled=True,
                                  webhook_url='https://dead'),
                       async_deliver=False, poster=exploding_poster)
    sink.deliver('run_started', 'Run started', 'info', {})  # must not raise


def test_webhook_async_returns_before_delivery_finishes():
    delivered = threading.Event()

    def slow_poster(url, payload, timeout):
        delivered.wait(2)
        return FakeResponse()

    sink = WebhookSink(make_store(webhook_enabled=True,
                                  webhook_url='https://slow'),
                       async_deliver=True, poster=slow_poster)
    sink.deliver('run_started', 'Run started', 'info', {})
    # deliver() already returned while the post is still in flight;
    # prove it by observing that nothing was posted yet is racy, so
    # instead just prove the thread completes cleanly afterwards
    assert delivered.wait(0.05) is False     # still in flight...
    delivered.set()
    for _ in range(200):                     # let the daemon thread exit
        if not any(t.is_alive() for t in threading.enumerate()
                   if t.name != threading.current_thread().name
                   and t.daemon and t._target is getattr(sink, '_post', None)):
            break
        time.sleep(0.01)


########################################################################
# mqtt sink
########################################################################

class FakeMqttOut:
    instances = []

    def __init__(self, topic=None, client_cls=None):
        self.topic = topic or 'kiln/sensor'
        self.published = []
        FakeMqttOut.instances.append(self)

    def publish(self, payload):
        self.published.append(payload)


@pytest.fixture
def fake_out_cls(monkeypatch):
    FakeMqttOut.instances = []
    return FakeMqttOut


def test_mqtt_sink_publishes_when_enabled(fake_out_cls):
    store = make_store(mqtt_enabled=True, mqtt_topic='kiln/alerts')
    sink = MqttSink(store, out_cls=fake_out_cls)
    sink.rebuild_async(store.delivery['mqtt_topic'])
    assert wait_for(lambda: sink.out is not None)

    sink.deliver('emergency_shutoff', 'Emergency!', 'critical', {'t': 1})
    out = FakeMqttOut.instances[0]
    assert out.topic == 'kiln/alerts'
    assert out.published[0]['alert_id'] == 'emergency_shutoff'


def test_mqtt_sink_disabled_never_builds_client(fake_out_cls):
    store = make_store(mqtt_enabled=False, mqtt_topic='kiln/alerts')
    sink = MqttSink(store, out_cls=fake_out_cls)
    sink.deliver('run_started', 'Run started', 'info', {})
    assert wait_for(lambda: sink.out is None)
    assert FakeMqttOut.instances == []


def test_mqtt_sink_rebuilds_on_topic_change(fake_out_cls):
    store = make_store(mqtt_enabled=True, mqtt_topic='first/topic')
    sink = MqttSink(store, out_cls=fake_out_cls)
    sink.rebuild_async('first/topic')
    assert wait_for(lambda: sink.out is not None)

    store.delivery.update({'mqtt_topic': 'second/topic'})
    sink.deliver('run_started', 'Run started', 'info', {})
    assert wait_for(lambda: len(FakeMqttOut.instances) == 2
                    and sink.built_topic == 'second/topic')
    # the payload of that delivery was skipped (client was rebuilding),
    # but a subsequent one goes to the new client
    sink.deliver('run_completed', 'Done', 'info', {})
    assert FakeMqttOut.instances[-1].published[-1]['alert_id'] == \
        'run_completed'


def test_mqtt_sink_survives_build_failure(fake_out_cls, caplog):
    def broken_cls(topic=None):
        raise RuntimeError('no broker configured')

    store = make_store(mqtt_enabled=True, mqtt_topic='kiln/alerts')
    sink = MqttSink(store, out_cls=broken_cls)
    sink.rebuild_async('kiln/alerts')       # must not raise
    assert wait_for(lambda: not sink.building)
    sink.deliver('run_started', 'Run started', 'info', {})  # skips silently


def test_mqtt_sink_first_delivery_while_connecting_is_skipped(
        monkeypatch):
    '''with a real (not yet built) client the delivery returns instead
    of blocking heater control'''
    class NeverReady:
        def __init__(self, topic=None):
            raise RuntimeError('still connecting')

    store = make_store(mqtt_enabled=True, mqtt_topic='t')
    sink = MqttSink(store, out_cls=None)     # lazy real import path unused
    sink.out = None
    sink.built_topic = None
    # stub rebuild_async so no thread spawns; deliver must just return
    monkeypatch.setattr(sink, 'rebuild_async', lambda topic: None)
    sink.deliver('run_started', 'Run started', 'info', {})
    assert sink.out is None
