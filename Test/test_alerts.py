'''Tests for the alert registry (lib/alerts.py) and the /api/alerts
endpoints that back the Alerts panel on the config tab.

The controller is loaded with a stub oven so no hardware or simulation
threads spawn, the same way test_config_editor.py does it. The alert
store used by the api is pointed at a throwaway file so storage/alerts.json
is never touched.'''

import importlib.util
import io
import json
import os
import types
import uuid

import pytest

import alerts as alerts_module
import oven
import ovenWatcher
from alerts import ALERTS, CRITICALITY_ORDER, CRITICAL, AlertStore


class StubOven:
    '''replaces SimulatedOven/RealOven so importing the controller
    does not spawn any hardware or simulation threads.'''

    def __init__(self, *args, **kwargs):
        self.pid = types.SimpleNamespace(pidstats={})
        self.state = 'IDLE'

    def set_ovenwatcher(self, watcher):
        pass

    def set_alert_manager(self, manager):
        pass

    def run_profile(self, profile, startat=0, allow_seek=True):
        pass

    def abort_run(self):
        pass


class StubOvenWatcher:
    def __init__(self, oven, *args, **kwargs):
        pass

    def record(self, profile):
        pass


def load_controller():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'kiln-controller.py'))
    spec = importlib.util.spec_from_file_location('kiln_controller_alerts', path)
    module = importlib.util.module_from_spec(spec)

    saved = (oven.SimulatedOven, oven.RealOven, ovenWatcher.OvenWatcher)
    oven.SimulatedOven = StubOven
    oven.RealOven = StubOven
    ovenWatcher.OvenWatcher = StubOvenWatcher
    try:
        spec.loader.exec_module(module)
    finally:
        oven.SimulatedOven, oven.RealOven, ovenWatcher.OvenWatcher = saved
    return module


controller = load_controller()


########################################################################
# fixtures
########################################################################

@pytest.fixture
def store(tmp_path):
    '''an AlertStore backed by a throwaway file'''
    return AlertStore(state_file=str(tmp_path / 'alerts.json'))


@pytest.fixture
def fake_alert_store(monkeypatch, tmp_path):
    '''point the controller's alert store at a throwaway file so api
    calls run their real code without touching storage/alerts.json'''
    path = str(tmp_path / ('alerts-%s.json' % uuid.uuid4().hex))
    monkeypatch.setattr(controller.alert_store, 'state_file', path)
    monkeypatch.setattr(controller.alert_store, 'enabled',
                        {a['id']: True for a in ALERTS})
    monkeypatch.setattr(controller.alert_store, 'delivery',
                        dict(alerts_module.DEFAULT_DELIVERY))
    return path


def wsgi(method, path, body=None):
    env = {
        'REQUEST_METHOD': method,
        'PATH_INFO': path,
        'SERVER_NAME': 'localhost',
        'SERVER_PORT': '80',
        'wsgi.input': io.BytesIO(body or b''),
        'wsgi.errors': io.StringIO(),
        'CONTENT_TYPE': 'application/json',
        'CONTENT_LENGTH': str(len(body or b'')),
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': 'http',
    }
    out = {}

    def start_response(status, headers, exc_info=None):
        out['status'] = status
        out['headers'] = dict(headers)

    resp = b''.join(controller.app(env, start_response))
    return out, resp


########################################################################
# registry
########################################################################

def test_registry_is_ordered_by_criticality_descending():
    ranks = {tier: i for i, tier in enumerate(CRITICALITY_ORDER)}
    seen = [ranks[a['criticality']] for a in ALERTS]
    assert seen == sorted(seen), 'registry must be ordered criticality descending'
    assert seen[0] == ranks[CRITICAL]


def test_registry_ids_are_unique_snake_case():
    ids = [a['id'] for a in ALERTS]
    assert len(ids) == len(set(ids))
    for alert_id in ids:
        assert alert_id == alert_id.lower()
        assert alert_id.replace('_', '').isalnum()


def test_registry_entries_are_complete():
    for a in ALERTS:
        assert a['criticality'] in CRITICALITY_ORDER
        assert a['label'] and isinstance(a['label'], str)
        assert a['description'] and isinstance(a['description'], str)


def test_registry_has_no_empty_tiers():
    tiers = {a['criticality'] for a in ALERTS}
    assert tiers == set(CRITICALITY_ORDER)


########################################################################
# AlertStore
########################################################################

def test_defaults_all_enabled_with_no_file(store, tmp_path):
    defs = store.definitions()
    assert len(defs) == len(ALERTS)
    assert all(d['enabled'] for d in defs)
    assert not os.path.exists(tmp_path / 'alerts.json')


def test_set_enabled_persists_and_reloads(store, tmp_path):
    target = ALERTS[0]['id']
    assert store.set_enabled(target, False) is True
    assert os.path.exists(tmp_path / 'alerts.json')

    again = AlertStore(state_file=str(tmp_path / 'alerts.json'))
    assert again.definitions()[0]['enabled'] is False
    assert all(d['enabled'] for d in again.definitions()
               if d['id'] != target)


def test_set_enabled_unknown_id_rejected(store):
    assert store.set_enabled('no_such_alert', False) is False
    # nothing was written
    assert all(d['enabled'] for d in store.definitions())


def test_set_enabled_idempotent_writes_once(store, tmp_path):
    target = ALERTS[0]['id']
    assert store.set_enabled(target, True) is True  # already true, no write
    assert not os.path.exists(tmp_path / 'alerts.json')


def test_load_survives_unknown_and_bad_values(store, tmp_path):
    path = tmp_path / 'alerts.json'
    data = {ALERTS[0]['id']: False, 'ghost': False, 'also_ghost': 'yes'}
    path.write_text(json.dumps(data))
    again = AlertStore(state_file=str(path))
    flags = {d['id']: d['enabled'] for d in again.definitions()}
    assert flags[ALERTS[0]['id']] is False
    assert flags[ALERTS[1]['id']] is True


def test_load_survives_corrupt_file(tmp_path):
    path = tmp_path / 'alerts.json'
    path.write_text('{not json')
    store = AlertStore(state_file=str(path))
    assert all(d['enabled'] for d in store.definitions())


def test_save_creates_missing_directories(tmp_path):
    deep = tmp_path / 'a' / 'b' / 'alerts.json'
    store = AlertStore(state_file=str(deep))
    store.set_enabled(ALERTS[0]['id'], False)
    assert deep.exists()


########################################################################
# GET/POST /api/alerts
########################################################################

def test_api_get_returns_registry_ordered(fake_alert_store):
    out, resp = wsgi('GET', '/api/alerts')
    assert out['status'] == '200 OK', out['status']
    body = json.loads(resp)
    assert body['success'] is True
    alerts = body['alerts']
    assert [a['id'] for a in alerts] == [a['id'] for a in ALERTS]


def test_api_post_updates_and_persists(fake_alert_store):
    target = ALERTS[-1]['id']
    body = json.dumps({'enabled': {target: False}}).encode()
    out, resp = wsgi('POST', '/api/alerts', body)
    assert out['status'] == '200 OK', out['status']

    result = json.loads(resp)
    assert result['success'] is True
    updated = {a['id']: a['enabled'] for a in result['alerts']}
    assert updated[target] is False

    with open(fake_alert_store) as infile:
        saved = json.load(infile)
    assert saved['enabled'][target] is False


def test_api_post_accepts_multiple_ids_at_once(fake_alert_store):
    body = json.dumps({'enabled': {ALERTS[0]['id']: False,
                                   ALERTS[1]['id']: False}}).encode()
    out, resp = wsgi('POST', '/api/alerts', body)
    assert out['status'] == '200 OK', out['status']
    updated = {a['id']: a['enabled'] for a in json.loads(resp)['alerts']}
    assert updated[ALERTS[0]['id']] is False
    assert updated[ALERTS[1]['id']] is False


def test_api_post_missing_map_rejected(fake_alert_store):
    out, resp = wsgi('POST', '/api/alerts', json.dumps({}).encode())
    assert out['status'] == '400 Bad Request', out['status']
    assert json.loads(resp)['success'] is False


def test_api_post_unknown_id_rejected_without_partial_save(fake_alert_store):
    good = ALERTS[0]['id']
    body = json.dumps({'enabled': {good: False,
                                   'no_such_alert': True}}).encode()
    out, resp = wsgi('POST', '/api/alerts', body)
    assert out['status'] == '400 Bad Request', out['status']
    assert 'no_such_alert' in json.loads(resp)['error']
    # the valid id must NOT have been applied
    current = {a['id']: a['enabled'] for a in controller.alert_store.definitions()}
    assert current[good] is True
    assert not os.path.exists(fake_alert_store)


def test_api_post_invalid_json_rejected(fake_alert_store):
    out, resp = wsgi('POST', '/api/alerts', b'{oops')
    assert out['status'] in ('400 Bad Request', '500 Internal Server Error')


def test_api_get_includes_delivery_and_mqtt_state(fake_alert_store):
    out, resp = wsgi('GET', '/api/alerts')
    body = json.loads(resp)
    assert body['success'] is True
    assert body['delivery']['mqtt_topic']
    assert isinstance(body['mqtt_configured'], bool)


def test_api_post_delivery_settings_save(fake_alert_store):
    body = json.dumps({'delivery': {
        'webhook_enabled': True,
        'webhook_url': 'https://ntfy.sh/my-kiln'}}).encode()
    out, resp = wsgi('POST', '/api/alerts', body)
    assert out['status'] == '200 OK', out['status']
    result = json.loads(resp)
    assert result['success'] is True
    assert result['delivery']['webhook_enabled'] is True
    assert result['delivery']['webhook_url'] == 'https://ntfy.sh/my-kiln'
    with open(fake_alert_store) as infile:
        saved = json.load(infile)
    assert saved['delivery']['webhook_enabled'] is True


def test_api_post_bad_delivery_rejects_without_partial_save(fake_alert_store):
    target = ALERTS[0]['id']
    # a valid alert toggle AND a bad delivery value in one request:
    # the whole request must be rejected, nothing saved
    body = json.dumps({'enabled': {target: False},
                       'delivery': {'webhook_url': 'notaurl'}}).encode()
    out, resp = wsgi('POST', '/api/alerts', body)
    assert out['status'] == '400 Bad Request'
    result = json.loads(resp)
    assert 'http' in result['error']
    # nothing saved at all: the state file is never even created
    assert not os.path.exists(fake_alert_store)


def test_api_post_unknown_delivery_key_rejected(fake_alert_store):
    body = json.dumps({'delivery': {'pushover_key': 'xyz'}}).encode()
    out, _ = wsgi('POST', '/api/alerts', body)
    assert out['status'] == '400 Bad Request'


def test_api_post_empty_body_rejected(fake_alert_store):
    out, _ = wsgi('POST', '/api/alerts', b'{}')
    assert out['status'] == '400 Bad Request'
