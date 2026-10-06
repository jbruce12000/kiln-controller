import sqlite3
import time

import config
from firing_db import FiringDb, get_max_firings


def make_state(run_started, profile="p", run_id=1, runtime=0):
    return {
        'runtime': runtime,
        'temperature': 100.0,
        'target': 200.0,
        'state': 'RUNNING',
        'heat': 1.0,
        'totaltime': 100,
        'cost': 0.1,
        'heat_rate': 50.0,
        'catching_up': False,
        'temp_errors': 0,
        'profile': profile,
        'run_id': run_id,
        'pidstats': {'p': 1},
        'run_started': run_started,
    }


def _columns(con, table):
    return {row[1] for row in
            con.execute("PRAGMA table_info(%s)" % table).fetchall()}


def test_schema_is_flat_and_deduped(tmp_path):
    '''no pidstats JSON, no per-sample copies of firing fields, no
    dual timestamps: pid terms are typed columns, run-fixed fields
    live on the firing row once.'''
    db = FiringDb(str(tmp_path / "t.db"), prune_on_start=False)
    con = sqlite3.connect(db.path)
    assert _columns(con, "firings") == {
        "id", "profile", "run_id", "run_started", "started_wall",
        "totaltime", "kp", "ki", "kd"}
    assert _columns(con, "samples") == {
        "id", "firing_id",
        "t", "runtime", "temp", "target", "state", "heat",
        "cost", "heat_rate", "catching_up", "temp_errors",
        "dt", "err", "ed", "p", "i", "d", "pid", "out"}
    db.close()


def test_record_flattens_pidstats(tmp_path):
    db = FiringDb(str(tmp_path / "t.db"), prune_on_start=False)
    db.record_state({
        'runtime': 10.0, 'temperature': 100.5, 'target': 200.5,
        'state': 'RUNNING', 'heat': 1.2, 'totaltime': 1000,
        'cost': 0.5, 'heat_rate': 99.9, 'catching_up': True,
        'temp_errors': 3, 'profile': 'flat', 'run_id': 7,
        'pidstats': {'time': 1700000042.5, 'timeDelta': 2.0,
                     'err': -100.25, 'errDelta': 0.5,
                     'p': 10.0, 'i': 8.0, 'd': 2.0,
                     'kp': 4.112, 'ki': 32.972, 'kd': 139.384,
                     'pid': 20.0, 'out': 0.75},
        'run_started': 1700000000.0})
    con = sqlite3.connect(db.path)
    srow = con.execute(
        "SELECT t, runtime, temp, target, state, heat, cost,"
        " heat_rate, catching_up, temp_errors,"
        " dt, err, ed, p, i, d, pid, out, firing_id"
        " FROM samples").fetchone()
    assert srow[:18] == (1700000042.5, 10.0, 100.5, 200.5, 'RUNNING',
                         1.2, 0.5, 99.9, 1, 3,
                         2.0, -100.25, 0.5,
                         10.0, 8.0, 2.0, 20.0, 0.75)
    frow = con.execute(
        "SELECT profile, run_id, run_started, totaltime, kp, ki, kd"
        " FROM firings WHERE id = ?", (srow[18],)).fetchone()
    assert frow == ('flat', 7, 1700000000.0, 1000, 4.112, 32.972,
                    139.384)
    db.close()


def test_sample_time_falls_back_to_record_time(tmp_path):
    '''samples recorded without a pid time still get a canonical t.'''
    before = time.time()
    db = FiringDb(str(tmp_path / "t.db"), prune_on_start=False)
    db.record_state(make_state(None))
    con = sqlite3.connect(db.path)
    (t,) = con.execute("SELECT t FROM samples").fetchone()
    assert before <= t <= time.time()
    db.close()


def test_legacy_db_is_wiped_clean(tmp_path):
    '''a pre-flat-schema db (pidstats JSON etc.) is dropped, not
    migrated, the first time it is opened.'''
    path = str(tmp_path / "legacy.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE firings (id INTEGER PRIMARY KEY,"
                " profile TEXT, run_started REAL UNIQUE)")
    con.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY,"
                " firing_id INTEGER, run_started REAL, wall_time REAL,"
                " profile TEXT, run_id INTEGER, pidstats TEXT)")
    con.execute("INSERT INTO firings (profile, run_started)"
                " VALUES ('old', 1.0)")
    con.commit()
    con.close()
    db = FiringDb(path, prune_on_start=False)
    con = sqlite3.connect(db.path)
    assert "pidstats" not in _columns(con, "samples")
    assert "wall_time" not in _columns(con, "samples")
    assert con.execute("SELECT COUNT(*) FROM firings").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM samples").fetchone() == (0,)
    # and the fresh schema still records afterwards
    assert db.record_state(make_state(1700000000.0)) is True
    assert con.execute("SELECT COUNT(*) FROM samples").fetchone() == (1,)
    db.close()


def test_default_max_firings_is_10():
    assert config.firing_db_max_firings == 10
    assert get_max_firings() == 10


def test_get_max_firings_falls_back_on_bad_config(monkeypatch):
    monkeypatch.setattr(config, 'firing_db_max_firings', 'junk',
                        raising=False)
    assert get_max_firings() == 10


def test_prune_keeps_newest_n(tmp_path):
    db = FiringDb(str(tmp_path / "t.db"), prune_on_start=False)
    for i in range(5):
        db.record_state(make_state(1000.0 + i, profile="p%d" % i))
    assert db.prune_old_firings(2) == (3, 3)
    con = sqlite3.connect(db.path)
    remaining = [r[0] for r in con.execute(
        "SELECT profile FROM firings ORDER BY id")]
    assert remaining == ["p3", "p4"]
    assert con.execute("SELECT COUNT(*) FROM samples").fetchone() == (2,)
    db.close()


def test_prune_keeps_idle_samples(tmp_path):
    db = FiringDb(str(tmp_path / "t.db"), prune_on_start=False)
    idle = make_state(None, profile=None)
    idle['state'] = 'IDLE'
    db.record_state(idle)
    for i in range(3):
        db.record_state(make_state(2000.0 + i))
    db.prune_old_firings(1)
    con = sqlite3.connect(db.path)
    assert con.execute("SELECT COUNT(*) FROM firings").fetchone() == (1,)
    # 1 idle (firing_id NULL) + 1 surviving firing sample
    assert con.execute("SELECT COUNT(*) FROM samples").fetchone() == (2,)
    assert con.execute(
        "SELECT COUNT(*) FROM samples WHERE firing_id IS NULL").fetchone() \
        == (1,)
    db.close()


def test_prune_nonpositive_keeps_everything(tmp_path):
    db = FiringDb(str(tmp_path / "t.db"), prune_on_start=False)
    for i in range(3):
        db.record_state(make_state(3000.0 + i))
    assert db.prune_old_firings(0) == (0, 0)
    assert db.prune_old_firings(-1) == (0, 0)
    con = sqlite3.connect(db.path)
    assert con.execute("SELECT COUNT(*) FROM firings").fetchone() == (3,)
    db.close()


def test_startup_prune_runs_in_background(tmp_path):
    db = FiringDb(str(tmp_path / "t.db"), prune_on_start=False)
    for i in range(4):
        db.record_state(make_state(4000.0 + i))
    db.close()
    db2 = FiringDb(str(tmp_path / "t.db"), max_firings=2,
                   prune_on_start=False)
    # isolated daemon thread: join it here; production never blocks on it
    thread = db2.prune_old_firings_in_background(max_keep=2)
    assert thread.daemon is True
    thread.join(timeout=10)
    con = sqlite3.connect(db2.path)
    assert con.execute("SELECT COUNT(*) FROM firings").fetchone() == (2,)
    db2.close()


def test_init_prunes_on_start(tmp_path):
    db = FiringDb(str(tmp_path / "t.db"), prune_on_start=False)
    for i in range(4):
        db.record_state(make_state(6000.0 + i))
    db.close()
    db2 = FiringDb(str(tmp_path / "t.db"), max_firings=2,
                   prune_on_start=True)
    # __init__ already spawned the background prune; wait for threads
    deadline = time.time() + 10
    while time.time() < deadline:
        con = sqlite3.connect(db2.path)
        if con.execute("SELECT COUNT(*) FROM firings").fetchone() == (2,):
            break
        time.sleep(0.05)
    con = sqlite3.connect(db2.path)
    assert con.execute("SELECT COUNT(*) FROM firings").fetchone() == (2,)
    db2.close()


def test_prune_uses_config_default_when_no_arg(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'firing_db_max_firings', 1, raising=False)
    db = FiringDb(str(tmp_path / "t.db"), prune_on_start=False)
    for i in range(3):
        db.record_state(make_state(5000.0 + i))
    assert db.prune_old_firings() == (2, 2)
    db.close()
