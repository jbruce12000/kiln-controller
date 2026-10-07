"""GET /api/history: full firing history from db/firings.db."""
import json
import types

import config

from test_kiln_controller import controller, _seed_db, _use_db


def _history(monkeypatch, tmp_path, **params):
    '''seed two samples and call api_history with a stubbed query.'''
    path, ids = _seed_db(tmp_path, firings=1, samples_per=2)
    _use_db(monkeypatch, path)
    monkeypatch.setattr(controller.bottle, 'request',
                        types.SimpleNamespace(query=dict(params)))
    return controller.api_history(), ids


def test_history_returns_full_firing_oldest_first(monkeypatch, tmp_path):
    resp, ids = _history(monkeypatch, tmp_path,
                         run_started=str(1700000000.0))
    payload = json.loads(resp)
    assert payload['success'] is True
    assert payload['run_started'] == 1700000000.0
    assert payload['profile'] == 'cone-05'
    assert payload['cols'] == controller.HISTORY_COLS
    assert len(payload['rows']) == 2
    i = {name: payload['cols'].index(name) for name in payload['cols']}
    # runtime order ascending; rounded display floats
    assert payload['rows'][0][i['rt']] == 0
    assert payload['rows'][1][i['rt']] == 2
    assert payload['rows'][0][i['temp']] == 65.0
    # seed pidstats lack t: falls back to the record time, ordered
    assert payload['rows'][0][i['t']] <= payload['rows'][1][i['t']]
    assert payload['rows'][0][i['p']] == 1.0


def test_history_rounds_and_keeps_pid_time(monkeypatch, tmp_path):
    from firing_db import FiringDb
    path = str(tmp_path / "h.db")
    db = FiringDb(path, prune_on_start=False)
    db.record_state({
        'runtime': 3.333, 'temperature': 100.126, 'target': 200.129,
        'state': 'RUNNING', 'heat': 1.0, 'totaltime': 100.0,
        'cost': 0.1, 'heat_rate': 50.0, 'catching_up': True,
        'temp_errors': 2, 'profile': 'cone-05', 'run_id': 1,
        'pidstats': {'time': 1700000001.123456, 'err': 99.999,
                     'out': 0.12345, 'p': 1.005},
        'run_started': 1700000000.0})
    db.close()
    monkeypatch.setattr(config, 'firing_db_file', path, raising=False)
    monkeypatch.setattr(
        controller.bottle, 'request',
        types.SimpleNamespace(query={'run_started': '1700000000.0'}))
    payload = json.loads(controller.api_history())
    i = {name: payload['cols'].index(name) for name in payload['cols']}
    row = payload['rows'][0]
    assert row[i['temp']] == 100.13
    assert row[i['err']] == 100.0
    assert row[i['out']] == 0.1235
    assert row[i['t']] == 1700000001.123456
    assert row[i['cu']] == 1
    assert row[i['te']] == 2


def test_history_defaults_to_current_run(monkeypatch, tmp_path):
    path, ids = _seed_db(tmp_path)
    _use_db(monkeypatch, path)
    ts = types.SimpleNamespace(timestamp=lambda: 1700000000.0)
    started = types.SimpleNamespace(
        started=ts, active_run_started=lambda: ts)
    monkeypatch.setattr(controller, 'ovenWatcher', started)
    monkeypatch.setattr(
        controller.bottle, 'request',
        types.SimpleNamespace(query={}))
    payload = json.loads(controller.api_history())
    assert payload['success'] is True
    assert len(payload['rows']) == 2


def test_history_no_run_in_progress(monkeypatch):
    monkeypatch.setattr(controller, 'ovenWatcher',
                        types.SimpleNamespace(started=None))
    monkeypatch.setattr(
        controller.bottle, 'request',
        types.SimpleNamespace(query={}))
    resp = controller.api_history()
    assert resp.status_code == 404
    assert json.loads(resp.body)['success'] is False


def test_history_rejects_bad_run_started(monkeypatch):
    monkeypatch.setattr(
        controller.bottle, 'request',
        types.SimpleNamespace(query={'run_started': 'nope'}))
    resp = controller.api_history()
    assert resp.status_code == 400


def test_history_unknown_firing_is_404(monkeypatch, tmp_path):
    path, _ = _seed_db(tmp_path)
    _use_db(monkeypatch, path)
    monkeypatch.setattr(
        controller.bottle, 'request',
        types.SimpleNamespace(query={'run_started': '1999999999.0'}))
    resp = controller.api_history()
    assert resp.status_code == 404
