import datetime
import importlib.util
import io
import json
import os
import tarfile
import time
import types

import bottle
import pytest

import config
import oven
import ovenWatcher


class StubOven:
    '''replaces SimulatedOven/RealOven so importing the controller
    does not spawn any hardware or simulation threads.'''

    def __init__(self, *args, **kwargs):
        self.pid = types.SimpleNamespace(pidstats={})
        self.state = 'IDLE'

    def set_ovenwatcher(self, watcher):
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
    spec = importlib.util.spec_from_file_location('kiln_controller', path)
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
# routes
########################################################################

def test_index_serves_spa(monkeypatch):
    html = controller.index()
    assert html.headers['Content-Type'].startswith('text/html')


def test_state_redirects_to_details():
    with pytest.raises(bottle.HTTPResponse) as excinfo:
        controller.state()
    assert excinfo.value.status_code == 302
    assert excinfo.value.headers['Location'].endswith('/#details')


def test_api_dump_returns_targz(monkeypatch, tmp_path):
    monkeypatch.setattr(
        controller.subprocess, 'check_output',
        lambda *a, **k: b'2024-01-01 INFO oven: temp=100\n'
                        b'2024-01-01 ERROR kiln-controller: boom\n')
    state_file = tmp_path / 'state.json'
    state_file.write_text('{"state": "RUNNING"}')
    monkeypatch.setattr(config, 'automatic_restart_state_file', str(state_file))
    profiles_dir = tmp_path / 'profiles'
    profiles_dir.mkdir()
    (profiles_dir / 'cone-05.json').write_text(
        json.dumps({'name': 'cone-05', 'data': [[0, 200]]}))
    (profiles_dir / 'bisque.json').write_text(
        json.dumps({'name': 'bisque', 'data': [[0, 100]]}))
    monkeypatch.setattr(controller, 'profile_path', str(profiles_dir))

    resp = controller.api_dump()
    assert resp.headers['Content-Type'] == 'application/gzip'
    assert 'attachment' in resp.headers['Content-Disposition']
    assert 'kiln-config-dump.tar.gz' in resp.headers['Content-Disposition']

    tar = tarfile.open(fileobj=io.BytesIO(resp.body), mode='r:gz')
    assert set(tar.getnames()) == {
        'config.py', 'state.json',
        'profiles/cone-05.json', 'profiles/bisque.json',
        'kiln.logs',
    }
    assert 'INFO oven: temp=100' in tar.extractfile('kiln.logs').read().decode()
    assert '{"state": "RUNNING"}' in tar.extractfile('state.json').read().decode()
    profile = json.loads(tar.extractfile('profiles/cone-05.json').read().decode())
    assert profile == {'name': 'cone-05', 'data': [[0, 200]]}
    # config.py must be the real repo config
    assert 'emergency_shutoff_temp' in tar.extractfile('config.py').read().decode()


def test_api_dump_without_profiles(monkeypatch, tmp_path):
    monkeypatch.setattr(controller.subprocess, 'check_output',
                        lambda *a, **k: b'')
    state_file = tmp_path / 'state.json'
    state_file.write_text('{}')
    monkeypatch.setattr(config, 'automatic_restart_state_file', str(state_file))
    profiles_dir = tmp_path / 'profiles'
    profiles_dir.mkdir()
    monkeypatch.setattr(controller, 'profile_path', str(profiles_dir))
    resp = controller.api_dump()
    tar = tarfile.open(fileobj=io.BytesIO(resp.body), mode='r:gz')
    assert set(tar.getnames()) == {'config.py', 'state.json', 'kiln.logs'}


########################################################################
# config helpers
########################################################################

def test_get_config():
    d = json.loads(controller.get_config())
    assert set(d) == {'simulate', 'temp_scale', 'time_scale_slope',
                      'time_scale_profile', 'kwh_rate', 'currency_type'}
    assert d['kwh_rate'] == config.kwh_rate
    assert d['simulate'] == config.simulate


########################################################################
# temperature unit helpers
########################################################################

def test_convert_to_c():
    profile = {'data': [[0, 32], [100, 212]]}
    out = controller.convert_to_c(profile)
    assert out['data'] == [(0, 0.0), (100, 100.0)]


def test_convert_to_f():
    profile = {'data': [[0, 0], [100, 100]]}
    out = controller.convert_to_f(profile)
    assert out['data'] == [(0, 32.0), (100, 212.0)]


def test_convert_to_c_empty_data():
    assert controller.convert_to_c({'data': []})['data'] == []


def test_convert_to_f_empty_data():
    assert controller.convert_to_f({'data': []})['data'] == []


def test_convert_round_trip():
    profile = {'data': [[0, -40], [3600, 25], [7200, 100], [10800, 2000]]}
    original = [tuple(p) for p in profile['data']]
    out = controller.convert_to_f(controller.convert_to_c(profile))
    assert len(out['data']) == len(original)
    for (s1, t1), (s2, t2) in zip(out['data'], original):
        assert s1 == pytest.approx(s2)
        assert t1 == pytest.approx(t2)


def test_get_config_temp_scale(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'c')
    assert json.loads(controller.get_config())['temp_scale'] == 'c'
    monkeypatch.setattr(config, 'temp_scale', 'f')
    assert json.loads(controller.get_config())['temp_scale'] == 'f'


def test_add_temp_units_converts_even_if_already_tagged(monkeypatch):
    # incoming profiles are always display scale, so the temp_units tag
    # is ignored and the data is force-converted to celsius for storage
    monkeypatch.setattr(config, 'temp_scale', 'f')
    profile = {'name': 'x', 'temp_units': 'c', 'data': [[0, 32]]}
    out = controller.add_temp_units(profile)
    assert out['temp_units'] == 'c'
    assert out['data'] == [(0, 0.0)]


def test_add_temp_units_f_scale_converts(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    profile = {'name': 'x', 'data': [[0, 32], [100, 212]]}
    out = controller.add_temp_units(profile)
    assert out['temp_units'] == 'c'
    assert out['data'] == [(0, 0.0), (100, 100.0)]


def test_add_temp_units_c_scale_no_conversion(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'c')
    profile = {'name': 'x', 'data': [[0, 0], [100, 100]]}
    out = controller.add_temp_units(profile)
    assert out['temp_units'] == 'c'
    assert out['data'] == [[0, 0], [100, 100]]


def test_normalize_temp_units(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    profiles = [
        {'name': 'a', 'temp_units': 'c', 'data': [[0, 0], [100, 100]]},
        {'name': 'b', 'data': [[0, 200]]},
    ]
    out = controller.normalize_temp_units(profiles)
    assert out[0]['temp_units'] == 'f'
    assert out[0]['data'] == [(0, 32.0), (100, 212.0)]
    assert 'temp_units' not in out[1]


def test_normalize_temp_units_c_scale_converts_f_stored(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'c')
    profiles = [
        {'name': 'a', 'temp_units': 'c', 'data': [[0, 0]]},
        {'name': 'b', 'temp_units': 'f', 'data': [[0, 32]]},
    ]
    out = controller.normalize_temp_units(profiles)
    assert out[0]['data'] == [[0, 0]]
    assert out[0]['temp_units'] == 'c'
    assert out[1]['data'] == [(0, 0.0)]
    assert out[1]['temp_units'] == 'c'


def test_normalize_temp_units_f_scale_untouched(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    profile = {'name': 'a', 'temp_units': 'f', 'data': [[0, 32], [100, 212]]}
    out = controller.normalize_temp_units([profile])
    assert out[0]['temp_units'] == 'f'
    assert out[0]['data'] == [[0, 32], [100, 212]]


def test_normalize_temp_units_mixed_scales(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    profiles = [
        {'name': 'a', 'temp_units': 'c', 'data': [[0, 0], [100, 100]]},
        {'name': 'b', 'temp_units': 'f', 'data': [[0, 32]]},
    ]
    out = controller.normalize_temp_units(profiles)
    assert out[0]['temp_units'] == 'f'
    assert out[0]['data'] == [(0, 32.0), (100, 212.0)]
    assert out[1]['temp_units'] == 'f'
    assert out[1]['data'] == [[0, 32]]


########################################################################
# profile storage helpers
########################################################################

def test_get_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    (tmp_path / 'a.json').write_text(
        json.dumps({'name': 'a', 'temp_units': 'c', 'data': [[0, 0], [100, 100]]}))
    (tmp_path / 'b.json').write_text(
        json.dumps({'name': 'b', 'data': [[0, 32]]}))

    profiles = json.loads(controller.get_profiles())
    assert len(profiles) == 2
    by_name = {p['name']: p for p in profiles}
    assert set(by_name) == {'a', 'b'}
    # config.temp_scale is f, so c-stored profiles come back in f
    assert by_name['a']['temp_units'] == 'f'
    assert by_name['a']['data'] == [[0, 32.0], [100, 212.0]]
    assert 'temp_units' not in by_name['b']


def test_get_profiles_missing_directory(monkeypatch):
    monkeypatch.setattr(controller, 'profile_path', '/nonexistent/dir/xyz')
    assert controller.get_profiles() == '[]'


def test_get_profiles_c_scale_untouched(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    monkeypatch.setattr(config, 'temp_scale', 'c')
    (tmp_path / 'a.json').write_text(
        json.dumps({'name': 'a', 'temp_units': 'c', 'data': [[0, 0], [100, 100]]}))

    profiles = json.loads(controller.get_profiles())
    assert profiles[0]['temp_units'] == 'c'
    assert profiles[0]['data'] == [[0, 0], [100, 100]]


def test_get_profiles_sorted_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    for name in ('zebra', 'alpha', 'mike'):
        (tmp_path / (name + '.json')).write_text(
            json.dumps({'name': name, 'data': [[0, 0]]}))

    profiles = json.loads(controller.get_profiles())
    assert [p['name'] for p in profiles] == ['alpha', 'mike', 'zebra']


def test_find_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    (tmp_path / 'test-fast.json').write_text(
        json.dumps({'name': 'test-fast', 'data': [[0, 200]]}))

    profile = controller.find_profile('test-fast')
    assert profile['name'] == 'test-fast'
    assert controller.find_profile('missing') is None


def test_find_profile_returns_raw_celsius_storage(monkeypatch, tmp_path):
    # profiles are stored in celsius, find_profile must hand back the
    # raw stored values regardless of the display scale
    monkeypatch.setattr(config, 'temp_scale', 'f')
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    (tmp_path / 'x.json').write_text(
        json.dumps({'name': 'x', 'temp_units': 'c', 'data': [[0, 100]]}))

    profile = controller.find_profile('x')
    assert profile['data'] == [[0, 100]]  # 100c, not 212f


def test_save_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    profile = {'name': 'foo', 'data': [[0, 200], [3600, 2000]]}

    assert controller.save_profile(dict(profile)) is True
    assert (tmp_path / 'foo.json').exists()
    # force=False refuses to overwrite
    assert controller.save_profile(dict(profile)) is False
    # force=True overwrites
    assert controller.save_profile(dict(profile), force=True) is True

    saved = json.loads((tmp_path / 'foo.json').read_text())
    assert saved['name'] == 'foo'
    assert saved['temp_units'] == 'c'


def test_delete_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    (tmp_path / 'bar.json').write_text(
        json.dumps({'name': 'bar', 'data': []}))
    assert controller.delete_profile({'name': 'bar'}) is True
    assert not (tmp_path / 'bar.json').exists()


def test_delete_profile_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    with pytest.raises(FileNotFoundError):
        controller.delete_profile({'name': 'nope'})


########################################################################
# scheduled runs
########################################################################

@pytest.fixture
def scheduler(monkeypatch, tmp_path):
    from lib.scheduler import Scheduler
    sched = Scheduler(state_file=str(tmp_path / 'schedules.json'))
    monkeypatch.setattr(controller, 'scheduler', sched)
    return sched


def test_parse_start_time_epoch():
    now = time.time() + 3600
    assert controller.parse_start_time(now) == now


def test_parse_start_time_iso():
    epoch = controller.parse_start_time('2030-01-02T03:04')
    assert epoch == datetime.datetime(2030, 1, 2, 3, 4).timestamp()


def test_parse_start_time_iso_with_seconds():
    epoch = controller.parse_start_time('2030-01-02T03:04:05')
    assert epoch == datetime.datetime(2030, 1, 2, 3, 4, 5).timestamp()


def test_parse_start_time_rejects_garbage():
    with pytest.raises(ValueError):
        controller.parse_start_time('not a time')


def test_parse_start_time_rejects_past():
    with pytest.raises(ValueError):
        controller.parse_start_time(time.time() - 60)


def test_parse_start_time_rejects_none():
    with pytest.raises(ValueError):
        controller.parse_start_time(None)


def test_api_schedule(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name})
    future = time.time() + 3600
    resp = controller.api_schedule({'profile': 'cone-05-long-bisque', 'start_time': future})
    assert resp['success'] is True
    assert resp['profile'] == 'cone-05-long-bisque'
    runs = scheduler.list()
    assert len(runs) == 1
    assert runs[0]['id'] == resp['id']
    assert runs[0]['start_time'] == future


def test_api_schedule_iso_string(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name})
    resp = controller.api_schedule({'profile': 'cone-05-long-bisque', 'start_time': '2030-01-02T03:04'})
    assert resp['success'] is True
    assert resp['start_time'] == controller.parse_start_time('2030-01-02T03:04')


def test_api_schedule_missing_profile(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: None)
    resp = controller.api_schedule({'profile': 'nope', 'start_time': time.time() + 3600})
    assert resp['success'] is False
    assert 'not found' in resp['error']


def test_api_schedule_rejects_past_time(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name})
    resp = controller.api_schedule({'profile': 'cone-05-long-bisque', 'start_time': time.time() - 60})
    assert resp['success'] is False
    assert 'future' in resp['error']
    assert scheduler.list() == []


def test_api_cancel_schedule(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name})
    resp = controller.api_schedule({'profile': 'cone-05-long-bisque', 'start_time': time.time() + 3600})
    cancelled = controller.api_cancel_schedule({'id': resp['id']})
    assert cancelled['success'] is True
    assert scheduler.list() == []


def test_api_cancel_schedule_missing(scheduler):
    resp = controller.api_cancel_schedule({'id': 'nope'})
    assert resp['success'] is False


def test_api_list_schedules(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name})
    controller.api_schedule({'profile': 'cone-05-long-bisque', 'start_time': time.time() + 3600})
    resp = controller.api_list_schedules()
    assert resp['success'] is True
    assert len(resp['schedules']) == 1


def test_fire_scheduled_run_idle(monkeypatch):
    calls = []
    def fake_run_profile(profile, startat=0, allow_seek=True):
        calls.append((profile.name, startat, allow_seek))
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name, 'data': [[0, 200]]})
    monkeypatch.setattr(controller.oven, 'state', 'IDLE')
    monkeypatch.setattr(controller.oven, 'run_profile', fake_run_profile)
    monkeypatch.setattr(controller.ovenWatcher, 'record', lambda profile: None)
    entry = {'id': 'abc', 'profile': 'cone-05-long-bisque', 'startat': 0}
    assert controller.fire_scheduled_run(entry) is True
    # scheduled runs never seek, even when the kiln is hot from a
    # previous run. they always start from the beginning.
    assert calls == [('cone-05-long-bisque', 0, False)]


def test_fire_scheduled_run_busy_oven(monkeypatch):
    monkeypatch.setattr(controller.oven, 'state', 'RUNNING')
    entry = {'id': 'abc', 'profile': 'cone-05-long-bisque', 'startat': 0}
    assert controller.fire_scheduled_run(entry) is False


def test_fire_scheduled_run_missing_profile(monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: None)
    monkeypatch.setattr(controller.oven, 'state', 'IDLE')
    entry = {'id': 'abc', 'profile': 'nope', 'startat': 0}
    assert controller.fire_scheduled_run(entry) is False


def test_fire_scheduled_run_with_startat(monkeypatch):
    calls = []
    def fake_run_profile(profile, startat=0, allow_seek=True):
        calls.append((profile.name, startat, allow_seek))
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name, 'data': [[0, 200]]})
    monkeypatch.setattr(controller.oven, 'state', 'IDLE')
    monkeypatch.setattr(controller.oven, 'run_profile', fake_run_profile)
    monkeypatch.setattr(controller.ovenWatcher, 'record', lambda profile: None)
    entry = {'id': 'abc', 'profile': 'cone-05-long-bisque', 'startat': 60}
    assert controller.fire_scheduled_run(entry) is True
    assert calls == [('cone-05-long-bisque', 60, False)]
