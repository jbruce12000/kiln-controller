'''Tests for the config editor: reading/writing config.py, reloading the
config module, restoring on a bad save, and scheduling a full restart.

The controller is loaded with a stub oven so no hardware or simulation
threads spawn. The config module is replaced per-test by a throwaway
module backed by a tmp file, so the real config.py is never touched.'''

import importlib.util
import io
import json
import os
import re
import sys
import types
import uuid

import pytest

import oven
import ovenWatcher

CONFIG_TMPL = '''simulate = True
automatic_restarts = True
kwh_rate = 0.1319
'''


def edit_rate(text, rate):
    text, n = re.subn(r'(kwh_rate\s*=\s*)[0-9.]+', r'\g<1>%s' % rate, text, count=1)
    assert n == 1, 'could not find kwh_rate to edit'
    return text


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


class FakeConfigFinder:
    '''meta-path finder so importlib.reload() can resolve a module that
    was created from a throwaway file instead of an import.'''

    def __init__(self, name, spec):
        self.name = name
        self.spec = spec

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.name:
            return self.spec
        return None


class StubOvenWatcher:
    def __init__(self, oven, *args, **kwargs):
        pass

    def record(self, profile):
        pass


def load_controller():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'kiln-controller.py'))
    spec = importlib.util.spec_from_file_location('kiln_controller_config_editor', path)
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
def fake_config(monkeypatch, tmp_path):
    '''a real module loaded from a throwaway config.py so save_config()
    and reload_config_module() run their real code without touching the
    repo's config.py.'''
    path = tmp_path / 'config.py'
    path.write_text(CONFIG_TMPL)
    name = 'fake_kiln_config_%s' % uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    finder = FakeConfigFinder(name, spec)
    sys.meta_path.insert(0, finder)
    monkeypatch.setattr(controller, 'config', module)
    try:
        yield module, path
    finally:
        sys.modules.pop(name, None)
        sys.meta_path.remove(finder)


@pytest.fixture
def spawn_log(monkeypatch):
    '''record gevent.spawn calls instead of actually running greenlets,
    so the restart greenlet never os.execv's the test process.'''
    spawned = []

    def spawn(fn, *args, **kwargs):
        spawned.append(fn)
        return types.SimpleNamespace(fn=fn)

    monkeypatch.setattr(controller.gevent, 'spawn', spawn)
    return spawned


def post_config(body_dict):
    '''drive the bottle app directly with a WSGI environ, the way a real
    browser POST to /api/config/editor would arrive.'''
    body = json.dumps(body_dict).encode()
    env = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': '/api/config/editor',
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


########################################################################
# reload_config_module / save_config
########################################################################

def test_save_config_valid_updates_module_and_file(fake_config):
    module, path = fake_config
    new_rate = 1.234
    assert controller.save_config(edit_rate(CONFIG_TMPL, new_rate)) is None
    assert module.kwh_rate == new_rate
    assert 'kwh_rate = 1.234' in path.read_text()


def test_save_config_valid_reloads_other_settings(fake_config):
    module, path = fake_config
    text = CONFIG_TMPL.replace('automatic_restarts = True', 'automatic_restarts = False')
    controller.save_config(text)
    assert module.automatic_restarts is False


def test_save_config_syntax_error_rejected_file_unchanged(fake_config):
    module, path = fake_config
    bad = 'kwh_rate = = = 1.23\nthis is not valid python (((\n'
    with pytest.raises(SyntaxError):
        controller.save_config(bad)
    content = path.read_text()
    assert 'kwh_rate = = =' not in content
    assert 'kwh_rate = 0.1319' in content
    assert module.kwh_rate == 0.1319


def test_save_config_reload_error_restores_original(fake_config):
    module, path = fake_config
    evil = CONFIG_TMPL.replace(
        'simulate = True',
        'simulate = True\nraise RuntimeError("boom")\nsimulate = True')
    evil = edit_rate(evil, 4.56)
    with pytest.raises(RuntimeError):
        controller.save_config(evil)
    assert 'raise RuntimeError' not in path.read_text()
    assert module.kwh_rate == 0.1319
    assert module.simulate is True


########################################################################
# GET /api/config/editor
########################################################################

def test_api_config_editor_returns_config_text(fake_config):
    resp = controller.api_config_editor()
    assert resp.headers['Content-Type'].startswith('text/plain')
    body = resp.body.decode() if isinstance(resp.body, bytes) else resp.body
    assert 'kwh_rate = 0.1319' in body


def test_api_config_editor_500_on_unreadable(fake_config, monkeypatch):
    module, path = fake_config
    monkeypatch.setattr(module, '__file__', str(path) + '.missing')
    resp = controller.api_config_editor()
    assert resp.status_code == 500


########################################################################
# POST /api/config/editor
########################################################################

def test_post_valid_config_schedules_restart(fake_config, spawn_log):
    module, path = fake_config
    new_rate = 2.22
    out, resp = post_config({'config': edit_rate(CONFIG_TMPL, new_rate)})
    assert out['status'] == '200 OK', (out['status'], resp)
    assert json.loads(resp) == {'success': True, 'restart_scheduled': True}
    assert module.kwh_rate == new_rate
    assert len(spawn_log) == 1
    assert callable(spawn_log[0])


def test_post_valid_config_idle_still_restarts(fake_config, spawn_log):
    controller.oven.state = 'IDLE'
    out, resp = post_config({'config': CONFIG_TMPL})
    assert json.loads(resp)['restart_scheduled'] is True
    assert len(spawn_log) == 1


def test_post_running_without_auto_restart_skips_restart(fake_config, spawn_log):
    controller.oven.state = 'RUNNING'
    text = CONFIG_TMPL.replace('automatic_restarts = True', 'automatic_restarts = False')
    out, resp = post_config({'config': text})
    assert out['status'] == '200 OK', (out['status'], resp)
    body = json.loads(resp)
    assert body['success'] is True
    assert body['restart_scheduled'] is False
    assert 'warning' in body
    assert len(spawn_log) == 0


def test_post_missing_config_rejected(fake_config, spawn_log):
    out, resp = post_config({})
    assert out['status'] == '400 Bad Request', (out['status'], resp)
    assert json.loads(resp)['success'] is False
    assert len(spawn_log) == 0


def test_post_syntax_error_rejected_file_unchanged(fake_config, spawn_log):
    module, path = fake_config
    out, resp = post_config({'config': 'kwh_rate = = = 1.23\n((('})
    assert out['status'] == '400 Bad Request', (out['status'], resp)
    assert json.loads(resp)['success'] is False
    assert 'kwh_rate = 0.1319' in path.read_text()
    assert module.kwh_rate == 0.1319
    assert len(spawn_log) == 0


def test_post_reload_error_rejected_config_restored(fake_config, spawn_log):
    module, path = fake_config
    evil = CONFIG_TMPL.replace('simulate = True', 'simulate = True\nraise RuntimeError("boom")')
    out, resp = post_config({'config': evil})
    assert out['status'] == '400 Bad Request', (out['status'], resp)
    assert json.loads(resp)['success'] is False
    assert module.kwh_rate == 0.1319
    assert len(spawn_log) == 0


def test_post_restart_greenlet_execs_process(fake_config, spawn_log, monkeypatch):
    execv_calls = []
    monkeypatch.setattr(controller.gevent, 'sleep', lambda secs: None)
    monkeypatch.setattr(controller.os, 'execv',
                        lambda path, argv: execv_calls.append((path, argv)))
    monkeypatch.setattr(controller.logging, 'shutdown', lambda: None)

    out, resp = post_config({'config': edit_rate(CONFIG_TMPL, 2.5)})
    assert out['status'] == '200 OK', (out['status'], resp)
    assert len(spawn_log) == 1

    spawn_log[0]()  # run the restart greenlet

    assert len(execv_calls) == 1
    assert execv_calls[0][0] == sys.executable
