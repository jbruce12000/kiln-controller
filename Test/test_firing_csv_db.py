"""db-backed firing list/csv export (kiln-controller endpoints)."""
import csv
import io
import json
import threading

import config

from test_kiln_controller import controller, _seed_db, _use_db


def test_csv_renders_on_worker_thread(monkeypatch, tmp_path):
    '''the csv body is built on an isolated daemon thread, never on
    the requesting (gevent) thread.'''
    path, ids = _seed_db(tmp_path)
    _use_db(monkeypatch, path)
    seen = {}
    real_build = controller._build_csv_job

    def spy_build(job_id, firing_id):
        seen['worker'] = threading.get_ident()
        seen['daemon'] = threading.current_thread().daemon
        return real_build(job_id, firing_id)

    monkeypatch.setattr(controller, '_build_csv_job', spy_build)
    seen['caller'] = threading.get_ident()
    resp = controller.api_firing_csv(str(ids[0][0]))
    assert resp.status_code == 200
    assert seen['worker'] != seen['caller']
    assert seen['daemon'] is True


def test_csv_row_mapping(monkeypatch, tmp_path):
    '''db sample -> FIRING_CSV_COLUMNS mapping incl. derived fields.'''
    from firing_db import FiringDb
    path = str(tmp_path / "m.db")
    db = FiringDb(path, prune_on_start=False)
    db.record_state({
        'runtime': 10.0, 'temperature': 100.0, 'target': 200.0,
        'state': 'RUNNING', 'heat': 1.0, 'totaltime': 100.0,
        'cost': 0.1, 'heat_rate': 50.0, 'catching_up': False,
        'temp_errors': 0, 'profile': 'cone-05', 'run_id': 1,
        'pidstats': {'err': 100.0, 'pid': 20.0, 'p': 10.0,
                     'i': 8.0, 'd': 2.0, 'out': 0.5},
        'run_started': 1700000000.0})
    fid = db._con.execute("SELECT id FROM firings").fetchone()[0]
    db.close()
    monkeypatch.setattr(config, 'firing_db_file', path, raising=False)
    resp = controller.api_firing_csv(str(fid))
    assert resp.status_code == 200
    header, row = list(csv.reader(io.StringIO(resp.body.strip())))
    assert header == controller.FIRING_CSV_COLUMNS
    cols = dict(zip(controller.FIRING_CSV_COLUMNS, row))
    assert cols['profile'] == 'cone-05'
    assert cols['run_time'] == '10'
    assert cols['total_time'] == '100'
    assert cols['time_left'] == '90'
    assert cols['temp'] == '100.00'
    assert cols['target'] == '200.00'
    assert cols['error'] == '100.00'
    assert cols['pid'] == '20.00'
    assert cols['p'] == '10.00'
    # out=0.5 over the 2s duty cycle -> 1s on / 1s off
    assert cols['heat_on'] == '1.00'
    assert cols['heat_off'] == '1.00'
    assert cols['timestamp']


def test_csv_unknown_firing_is_404(monkeypatch, tmp_path):
    path, _ = _seed_db(tmp_path)
    _use_db(monkeypatch, path)
    resp = controller.api_firing_csv('99999')
    assert resp.status_code == 404
    assert json.loads(resp.body)['success'] is False
