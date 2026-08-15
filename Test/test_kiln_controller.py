import datetime
import importlib.util
import io
import json
import os
import tarfile
import time
import types
import base64

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
        self.run_sequence = 0
        self.ended_run_sequence = 0
        self.idle_since = time.time()

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
                      'time_scale_profile', 'kwh_rate', 'currency_type',
                      'github_sharing_enabled'}
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


def test_save_profile_persists_description(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    profile = {'name': 'foo', 'data': [[0, 200], [3600, 2000]],
               'description': 'Bisque to cone 05'}

    assert controller.save_profile(dict(profile)) is True
    saved = json.loads((tmp_path / 'foo.json').read_text())
    assert saved['description'] == 'Bisque to cone 05'


def test_get_profiles_returns_description(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    (tmp_path / 'a.json').write_text(
        json.dumps({'name': 'a', 'data': [[0, 0]],
                    'description': 'my bisque schedule'}))

    profiles = json.loads(controller.get_profiles())
    assert profiles[0]['description'] == 'my bisque schedule'


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


def test_api_schedule_chain_after_run(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name})
    resp = controller.api_schedule({'profile': 'cone-05-long-bisque',
                                    'start_time': time.time() + 3600,
                                    'chain_after': 'run:3'})
    assert resp['success'] is True
    assert scheduler.list()[0]['chain_after'] == 'run:3'


def test_api_schedule_chain_after_schedule(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name})
    anchor = controller.api_schedule({'profile': 'cone-05-long-bisque',
                                      'start_time': time.time() + 3600})
    resp = controller.api_schedule({'profile': 'cone-05-long-bisque',
                                    'start_time': time.time() + 7200,
                                    'chain_after': 'sched:' + anchor['id']})
    assert resp['success'] is True
    assert scheduler.list()[1]['chain_after'] == 'sched:' + anchor['id']


def test_api_schedule_chain_after_missing_schedule_rejected(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name})
    resp = controller.api_schedule({'profile': 'cone-05-long-bisque',
                                    'start_time': time.time() + 3600,
                                    'chain_after': 'sched:nope'})
    assert resp['success'] is False
    assert 'not found' in resp['error']
    assert scheduler.list() == []


def test_api_schedule_chain_after_garbage_rejected(scheduler, monkeypatch):
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name})
    for bad in ('run:xyz', 'banana'):
        resp = controller.api_schedule({'profile': 'cone-05-long-bisque',
                                        'start_time': time.time() + 3600,
                                        'chain_after': bad})
        assert resp['success'] is False
        assert scheduler.list() == []


def test_fire_scheduled_run_chained_waits_for_actual_end(monkeypatch):
    # a chained firing must wait for the firing it follows to really end
    # (catch-up can stretch a run past its nominal duration), so it stays
    # quiet while the oven is busy even after its estimated start_time.
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name, 'data': [[0, 200]]})
    monkeypatch.setattr(controller.ovenWatcher, 'record', lambda profile: None)
    monkeypatch.setattr(controller.oven, 'ended_run_sequence', 2)
    monkeypatch.setattr(controller.oven, 'idle_since', time.time() - 5)
    entry = {'id': 'abc', 'profile': 'cone-05-long-bisque', 'startat': 0,
             'chain_after': 'run:5'}

    # anchor run (sequence 5) has not ended yet
    assert controller.fire_scheduled_run(entry) is False

    # anchor ended, but the oven is still running something else
    monkeypatch.setattr(controller.oven, 'ended_run_sequence', 5)
    monkeypatch.setattr(controller.oven, 'state', 'RUNNING')
    assert controller.fire_scheduled_run(entry) is False

    # oven idle but still inside the chain buffer
    monkeypatch.setattr(controller.oven, 'state', 'IDLE')
    monkeypatch.setattr(controller.oven, 'idle_since', time.time())
    assert controller.fire_scheduled_run(entry) is False

    # anchor ended, oven idle, buffer elapsed -> fires
    monkeypatch.setattr(controller.oven, 'idle_since', time.time() - 120)
    calls = []
    def fake_run_profile(profile, startat=0, allow_seek=True):
        calls.append((profile.name, startat, allow_seek))
    monkeypatch.setattr(controller.oven, 'run_profile', fake_run_profile)
    assert controller.fire_scheduled_run(entry) is True
    assert calls == [('cone-05-long-bisque', 0, False)]


def test_fire_scheduled_run_chained_after_schedule(monkeypatch, scheduler):
    # chained after a scheduled run: waits until that schedule has fired.
    monkeypatch.setattr(controller, 'find_profile', lambda name: {'name': name, 'data': [[0, 200]]})
    monkeypatch.setattr(controller.oven, 'state', 'IDLE')
    monkeypatch.setattr(controller.oven, 'idle_since', time.time() - 120)
    monkeypatch.setattr(controller.ovenWatcher, 'record', lambda profile: None)
    anchor = scheduler.add('cone-05-long-bisque', time.time() + 3600)
    entry = {'id': 'abc', 'profile': 'cone-05-long-bisque', 'startat': 0,
             'chain_after': 'sched:' + anchor['id']}

    # anchor has not fired yet
    assert controller.fire_scheduled_run(entry) is False

    scheduler.mark_fired(anchor)
    calls = []
    def fake_run_profile(profile, startat=0, allow_seek=True):
        calls.append((profile.name, startat, allow_seek))
    monkeypatch.setattr(controller.oven, 'run_profile', fake_run_profile)
    assert controller.fire_scheduled_run(entry) is True
    assert calls == [('cone-05-long-bisque', 0, False)]


def test_chained_firing_waits_for_real_end_end_to_end(monkeypatch, tmp_path):
    # full chain through the real scheduler + a real oven: a firing chained
    # after the one in progress waits until that firing actually ends (a
    # catch-up extension just means it ends later than its nominal time),
    # then starts after the chain buffer.
    import json as _json
    import lib.scheduler as schedmod
    from lib.oven import Oven, Profile

    monkeypatch.setattr(config, 'automatic_restarts', False)
    sched = schedmod.Scheduler(state_file=str(tmp_path / 'schedules.json'))
    sched.fire_callback = controller.fire_scheduled_run
    monkeypatch.setattr(controller, 'scheduler', sched)
    real = Oven()
    monkeypatch.setattr(controller, 'oven', real)
    monkeypatch.setattr(controller, 'find_profile',
                        lambda name: {'name': name, 'data': [[0, 200], [600, 200]], 'temp_units': 'c'})
    monkeypatch.setattr(config, 'schedule_chain_buffer', 60)

    # a firing is in progress
    real.run_profile(Profile(_json.dumps({'name': 'p', 'data': [[0, 200], [600, 200]]})),
                     startat=0, allow_seek=False)
    assert real.run_sequence == 1

    # chain a firing after the current one; start_time is just an estimate
    resp = controller.api_schedule({'profile': 'p',
                                    'start_time': time.time() + 600,
                                    'chain_after': 'run:1'})
    assert resp['success'] is True

    # while the anchor runs, the chained firing waits and is never skipped
    sched.fire_due()
    assert sched.list()[0]['fired'] is False
    assert sched.list()[0]['status'] == 'waiting'

    # the anchor actually ends (completion or catch-up stretch both land here)
    real.abort_run()
    assert real.ended_run_sequence == 1

    # still inside the chain buffer: not fired yet
    sched.fire_due()
    assert sched.list()[0]['fired'] is False

    # buffer elapsed: the chained firing fires
    monkeypatch.setattr(real, 'idle_since', time.time() - 120)
    sched.fire_due()
    runs = sched.list()
    assert runs[0]['fired'] is True
    assert runs[0]['status'] == 'fired'


def test_start_run_converts_legacy_fahrenheit_profile(monkeypatch):
    # legacy profiles predate temp_units and are stored in fahrenheit.
    # start_run must convert them to celsius before running, otherwise a
    # scheduled run targets 212f for a profile that says 100f.
    started = []
    def fake_run_profile(profile, startat=0, allow_seek=True):
        started.append(profile.get_target_temperature(0))
    monkeypatch.setattr(controller, 'find_profile',
                        lambda name: {'name': 'test-200-250',
                                      'data': [[0, 100], [480, 200],
                                               [2000, 200], [2300, 250],
                                               [3600, 250]]})
    monkeypatch.setattr(controller.oven, 'run_profile', fake_run_profile)
    monkeypatch.setattr(controller.ovenWatcher, 'record', lambda profile: None)

    assert controller.start_run('test-200-250') is True
    assert started[0] == pytest.approx((100 - 32) * 5 / 9)  # 100f, not 100c


def test_start_run_keeps_celsius_profile_untouched(monkeypatch):
    started = []
    def fake_run_profile(profile, startat=0, allow_seek=True):
        started.append(profile.get_target_temperature(0))
    monkeypatch.setattr(controller, 'find_profile',
                        lambda name: {'name': 'cone-05-long-bisque',
                                      'temp_units': 'c',
                                      'data': [[0, 100], [3600, 100]]})
    monkeypatch.setattr(controller.oven, 'run_profile', fake_run_profile)
    monkeypatch.setattr(controller.ovenWatcher, 'record', lambda profile: None)

    assert controller.start_run('cone-05-long-bisque') is True
    assert started[0] == 100


########################################################################
# community profiles (kiln-profiles repo)
########################################################################

class FakeResp:
    '''minimal requests.Response stand-in for monkeypatched requests.'''

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError('http %s' % self.status_code)


def _reset_remote_cache(monkeypatch):
    monkeypatch.setattr(controller, '_remote_cache', {'at': 0.0, 'data': None})


def _fake_index():
    '''fake schedules.json index: a json array of profiles with
    category/tags/description like the real community repo.'''
    return [
        {'type': 'profile', 'name': 'slumped-plate', 'category': 'glass',
         'tags': ['slumping', 'glass'], 'units': 'F',
         'description': 'slump a plate', 'data': [[0, 65], [3600, 1200]]},
        {'type': 'profile', 'name': 'cone-05-long-bisque', 'category': 'pottery',
         'tags': ['bisque', 'cone05', 'pottery'], 'units': 'F',
         'description': 'a long bisque firing', 'data': [[0, 65], [46800, 1708]]},
    ]


def _fake_index_get():
    def fake_get(url, params=None, headers=None, timeout=None):
        assert url == 'https://jbruce12000.github.io/kiln-profiles/schedules.json', url
        return FakeResp(_fake_index())
    return fake_get


def post_json(path, body_dict):
    '''drive the bottle app directly with a WSGI environ, the way a real
    browser POST would arrive.'''
    body = json.dumps(body_dict).encode()
    env = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': path,
        'SERVER_NAME': 'localhost',
        'SERVER_PORT': '80',
        'wsgi.input': io.BytesIO(body),
        'wsgi.errors': io.StringIO(),
        'CONTENT_TYPE': 'application/json',
        'CONTENT_LENGTH': str(len(body)),
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': 'http',
    }
    out = {}

    def start_response(status, headers, exc_info=None):
        out['status'] = status
        out['headers'] = dict(headers)

    resp = b''.join(controller.app(env, start_response))
    return out, resp


def test_list_remote_profiles_parses_categories_and_files(monkeypatch, tmp_path):
    monkeypatch.setattr(controller.requests, 'get', _fake_index_get())
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    _reset_remote_cache(monkeypatch)

    data = controller.list_remote_profiles(force=True)
    assert data['success'] is True
    assert data['categories'] == ['glass', 'pottery']
    assert data['tags'] == ['slumping', 'glass', 'bisque', 'cone05', 'pottery']
    assert data['upload_enabled'] is True  # sharing needs no controller token anymore
    assert sorted(p['name'] for p in data['profiles']) == ['cone-05-long-bisque', 'slumped-plate']
    pottery = next(p for p in data['profiles'] if p['name'] == 'cone-05-long-bisque')
    assert pottery['category'] == 'pottery'
    assert pottery['path'] == 'pottery/cone-05-long-bisque.json'
    assert pottery['tags'] == ['bisque', 'cone05', 'pottery']
    assert pottery['description'] == 'a long bisque firing'
    assert pottery['units'] == 'F'
    assert pottery['installed'] is False


def test_list_remote_profiles_reports_installed_and_upload_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(controller.requests, 'get', _fake_index_get())
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    (tmp_path / 'cone-05-long-bisque.json').write_text('{}')
    _reset_remote_cache(monkeypatch)

    data = controller.list_remote_profiles(force=True)
    assert data['upload_enabled'] is True
    pottery = next(p for p in data['profiles'] if p['name'] == 'cone-05-long-bisque')
    assert pottery['installed'] is True
    glass = next(p for p in data['profiles'] if p['name'] == 'slumped-plate')
    assert glass['installed'] is False


def test_list_remote_profiles_served_from_cache(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        return FakeResp(_fake_index())
    monkeypatch.setattr(controller.requests, 'get', fake_get)
    _reset_remote_cache(monkeypatch)

    controller.list_remote_profiles(force=True)
    controller.list_remote_profiles()  # served from the cache, no new calls
    assert len(calls) == 1  # one fetch of the index, then cached


def test_list_remote_profiles_bad_index_url(monkeypatch):
    monkeypatch.setattr(config, 'kiln_profiles_index_url', '')
    _reset_remote_cache(monkeypatch)
    data = controller.list_remote_profiles(force=True)
    assert data['success'] is False
    assert 'kiln_profiles_index_url' in data['error']


def test_delete_profile_invalidates_remote_installed_state(monkeypatch, tmp_path):
    monkeypatch.setattr(controller.requests, 'get', _fake_index_get())
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    _reset_remote_cache(monkeypatch)
    (tmp_path / 'cone-05-long-bisque.json').write_text('{}')

    data = controller.list_remote_profiles(force=True)
    assert next(p for p in data['profiles']
                if p['name'] == 'cone-05-long-bisque')['installed'] is True
    assert controller._remote_cache['data'] is not None

    # deleting the local profile must drop the stale installed state
    controller.delete_profile({'name': 'cone-05-long-bisque'})
    assert controller._remote_cache['data'] is None

    data = controller.list_remote_profiles(force=True)
    assert next(p for p in data['profiles']
                if p['name'] == 'cone-05-long-bisque')['installed'] is False


def test_save_profile_invalidates_remote_installed_state(monkeypatch, tmp_path):
    monkeypatch.setattr(controller.requests, 'get', _fake_index_get())
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    _reset_remote_cache(monkeypatch)

    data = controller.list_remote_profiles(force=True)
    assert next(p for p in data['profiles']
                if p['name'] == 'slumped-plate')['installed'] is False

    controller.save_profile({'name': 'slumped-plate', 'data': [[0, 20]], 'temp_units': 'c'})
    assert controller._remote_cache['data'] is None

    data = controller.list_remote_profiles(force=True)
    assert next(p for p in data['profiles']
                if p['name'] == 'slumped-plate')['installed'] is True


def test_import_profile_converts_legacy_fahrenheit(monkeypatch, tmp_path):
    # repo profiles are stored untagged in fahrenheit (legacy format);
    # importing must convert them to celsius like the run path does
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    profile = {'name': 'cone-05-long-bisque', 'type': 'profile',
               'data': [[0, 65], [46800, 1708]], 'tags': ['bisque'],
               'description': 'a cone 05 bisque firing'}
    filepath = controller.import_profile(profile)
    saved = json.loads(open(filepath).read())
    assert saved['temp_units'] == 'c'
    assert saved['data'][0][1] == pytest.approx((65 - 32) * 5 / 9)
    assert saved['data'][1][1] == pytest.approx((1708 - 32) * 5 / 9)
    assert saved['description'] == 'a cone 05 bisque firing'
    assert saved['tags'] == ['bisque']


def test_import_profile_keeps_tagged_celsius(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    profile = {'name': 'glass-fuse', 'temp_units': 'c', 'data': [[0, 20]]}
    filepath = controller.import_profile(profile)
    saved = json.loads(open(filepath).read())
    assert saved['temp_units'] == 'c'
    assert saved['data'] == [[0, 20]]


def test_import_profile_rejects_bad_name(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    with pytest.raises(ValueError):
        controller.import_profile({'name': '../evil', 'data': [[0, 20]]})
    assert list(tmp_path.iterdir()) == []


def test_import_profile_rejects_missing_data(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    with pytest.raises(ValueError):
        controller.import_profile({'name': 'cone-05-long-bisque'})


def test_api_profiles_remote_import(monkeypatch, tmp_path):
    profile = {'name': 'cone-05-long-bisque', 'type': 'profile',
               'data': [[0, 65], [46800, 1708]], 'description': 'bisque firing'}
    monkeypatch.setattr(controller.requests, 'get',
                        lambda *a, **k: FakeResp(profile))
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    _reset_remote_cache(monkeypatch)

    out, resp = post_json('/api/profiles/remote/import',
                          {'path': 'pottery/cone-05-long-bisque.json'})
    assert out['status'] == '200 OK', (out['status'], resp)
    assert json.loads(resp) == {'success': True, 'name': 'cone-05-long-bisque'}
    saved = json.loads((tmp_path / 'cone-05-long-bisque.json').read_text())
    assert saved['temp_units'] == 'c'
    assert saved['data'][0][1] == pytest.approx((65 - 32) * 5 / 9)


def test_api_profiles_remote_import_rejects_bad_path(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    _reset_remote_cache(monkeypatch)
    out, resp = post_json('/api/profiles/remote/import',
                          {'path': '../../etc/passwd.json'})
    assert out['status'] == '400 Bad Request'
    assert json.loads(resp)['success'] is False


def test_api_profiles_remote_upload_disabled_without_token(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    out, resp = post_json('/api/profiles/remote/upload',
                          {'category': 'pottery',
                           'profile': {'name': 'x', 'data': [[0, 20]]}})
    assert out['status'] == '400 Bad Request'
    assert 'disabled' in json.loads(resp)['error']


def _fake_share_flow(fork_missing=True):
    '''fake the fork-and-PR endpoints used by the share endpoint.'''
    calls = []
    prs = []
    contents = []
    fork_checked = [0]

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        if url == 'https://api.github.com/user':
            return FakeResp({'login': 'sharer'})
        if url == 'https://api.github.com/repos/sharer/kiln-profiles':
            fork_checked[0] += 1
            if fork_missing and fork_checked[0] == 1:
                return FakeResp({'message': 'not found'}, status_code=404)
            return FakeResp({'full_name': 'sharer/kiln-profiles'})
        if url.endswith('/repos/sharer/kiln-profiles/git/ref/heads/main'):
            return FakeResp({'object': {'sha': 'base-sha-123'}})
        raise AssertionError('unexpected get url: %s' % url)

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(url)
        if url == 'https://api.github.com/repos/jbruce12000/kiln-profiles/forks':
            return FakeResp({'full_name': 'sharer/kiln-profiles'}, status_code=202)
        if url == 'https://api.github.com/repos/sharer/kiln-profiles/merge-upstream':
            return FakeResp({})
        if url == 'https://api.github.com/repos/sharer/kiln-profiles/git/refs':
            assert json['ref'] == 'refs/heads/kiln-share-my-bisque'
            assert json['sha'] == 'base-sha-123'
            return FakeResp({'ref': json['ref']}, status_code=201)
        if url == 'https://api.github.com/repos/jbruce12000/kiln-profiles/pulls':
            prs.append(json)
            return FakeResp({'html_url': 'https://github.com/jbruce12000/kiln-profiles/pull/12',
                             'number': 12})
        raise AssertionError('unexpected post url: %s' % url)

    def fake_put(url, json=None, headers=None, timeout=None):
        calls.append(url)
        if url == 'https://api.github.com/repos/sharer/kiln-profiles/contents/pottery/my-bisque.json':
            contents.append(json)
            return FakeResp({'content': {}}, status_code=201)
        raise AssertionError('unexpected put url: %s' % url)

    return fake_get, fake_post, fake_put, calls, prs, contents


def test_api_profiles_remote_upload_opens_pull_request(monkeypatch, tmp_path):
    fake_get, fake_post, fake_put, calls, prs, contents = _fake_share_flow()
    monkeypatch.setattr(controller.requests, 'get', fake_get)
    monkeypatch.setattr(controller.requests, 'post', fake_post)
    monkeypatch.setattr(controller.requests, 'put', fake_put)
    monkeypatch.setattr(controller.time, 'sleep', lambda s: None)
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    _reset_remote_cache(monkeypatch)

    out, resp = post_json('/api/profiles/remote/upload', {
        'category': 'pottery',
        'github_token': 'user-token',
        'profile': {'name': 'my-bisque', 'data': [[0, 65], [3600, 1708]],
                    'description': 'shared schedule'},
    })
    assert out['status'] == '200 OK', (out['status'], resp)
    body = json.loads(resp)
    assert body['success'] is True
    assert body['pr_url'] == 'https://github.com/jbruce12000/kiln-profiles/pull/12'
    assert body['pr_number'] == 12

    # the file is committed to the sharer's fork on a feature branch
    assert len(contents) == 1
    assert contents[0]['branch'] == 'kiln-share-my-bisque'
    uploaded = json.loads(base64.b64decode(contents[0]['content']).decode('utf-8'))
    assert uploaded['name'] == 'my-bisque'
    assert uploaded['temp_units'] == 'c'
    assert uploaded['description'] == 'shared schedule'
    assert uploaded['data'][0][1] == pytest.approx((65 - 32) * 5 / 9)

    # the pull request targets the shared repo with head = sharer's fork
    assert len(prs) == 1
    assert prs[0]['base'] == 'main'
    assert prs[0]['head'] == 'sharer:kiln-share-my-bisque'
    assert prs[0]['title'] == 'Add schedule my-bisque (pottery)'

    # the profile was also saved locally in celsius
    saved = json.loads((tmp_path / 'my-bisque.json').read_text())
    assert saved['temp_units'] == 'c'


def test_api_profiles_remote_upload_reuses_existing_fork(monkeypatch, tmp_path):
    fake_get, fake_post, fake_put, calls, prs, contents = _fake_share_flow(fork_missing=False)
    monkeypatch.setattr(controller.requests, 'get', fake_get)
    monkeypatch.setattr(controller.requests, 'post', fake_post)
    monkeypatch.setattr(controller.requests, 'put', fake_put)
    monkeypatch.setattr(controller, 'profile_path', str(tmp_path))
    _reset_remote_cache(monkeypatch)

    out, resp = post_json('/api/profiles/remote/upload', {
        'category': 'pottery',
        'github_token': 'user-token',
        'profile': {'name': 'my-bisque', 'data': [[0, 65], [3600, 1708]]},
    })
    assert out['status'] == '200 OK', (out['status'], resp)
    assert json.loads(resp)['pr_number'] == 12
    # the fork already existed, so no "create fork" call was made
    assert not any(url.endswith('/forks') for url in calls)
    assert any(url.endswith('/merge-upstream') for url in calls)
