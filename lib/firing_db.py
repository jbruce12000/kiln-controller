"""SQLite persistence for kiln firings.

Every OvenWatcher duty cycle (~config.sensor_time_wait, 2s by default)
calls FiringDb.record_state() with the same dict broadcast on
ws:///status (see Oven.get_state() + run_started).

Layout (db/firings.db), normalized so nothing is stored twice:
  firings(id, profile, run_id, run_started UNIQUE, started_wall,
          totaltime, kp, ki, kd)
    one row per firing. totaltime and the pid constants are fixed for
    the run, so they live here instead of on every sample.
  samples(id, firing_id -> firings.id,
          t, runtime, temp, target, state, heat, cost, heat_rate,
          catching_up, temp_errors,
          dt, err, ed, p, i, d, pid, out)
    one row per duty cycle. pid loop terms are flat typed columns
    (dt=timeDelta, ed=errDelta); t is the canonical sample time (the
    pid compute time, else the record time).

Deliberately NOT stored per sample, because they duplicate other
columns or rows:
  - pidstats JSON (repeated key strings on every row)
  - ispoint/setpoint (== temp/target)
  - run_started/profile/run_id per sample (== the firings row)
  - wall_time alongside the pid time (merged into t)

Writes must never break heater control, so record_state() catches and
logs all sqlite errors and returns False instead of raising.
"""

import logging
import os
import sqlite3
import threading
import time

log = logging.getLogger(__name__)

SCHEMA_FIRINGS = """
CREATE TABLE IF NOT EXISTS firings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile TEXT,
    run_id INTEGER,
    run_started REAL UNIQUE,
    started_wall REAL,
    totaltime REAL,
    kp REAL,
    ki REAL,
    kd REAL
)
"""

SCHEMA_SAMPLES = """
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firing_id INTEGER REFERENCES firings(id),
    t REAL,
    runtime REAL,
    temp REAL,
    target REAL,
    state TEXT,
    heat REAL,
    cost REAL,
    heat_rate REAL,
    catching_up INTEGER,
    temp_errors INTEGER,
    dt REAL,
    err REAL,
    ed REAL,
    p REAL,
    i REAL,
    d REAL,
    pid REAL,
    out REAL
)
"""

IDX_SAMPLES_FIRING = """
CREATE INDEX IF NOT EXISTS idx_samples_firing
ON samples (firing_id, id)
"""

# any of these columns means the db predates the flat schema and must
# be wiped for a clean start (see _wipe_legacy).
LEGACY_SAMPLE_COLUMNS = ("pidstats", "wall_time", "run_started",
                         "profile", "run_id")


def default_db_path():
    """db/firings.db next to the repo root (lib/..)."""
    here = os.path.dirname(os.path.realpath(__file__))
    return os.path.abspath(os.path.join(here, "..", "db", "firings.db"))


def configured_db_path():
    """config.firing_db_file when set, else the default location."""
    try:
        import config
        path = getattr(config, "firing_db_file", None)
        if path:
            return os.path.abspath(path)
    except Exception:
        pass
    return default_db_path()


DEFAULT_MAX_FIRINGS = 10


def get_max_firings():
    """config.firing_db_max_firings when set and valid, else 10."""
    try:
        import config
        value = getattr(config, "firing_db_max_firings",
                        DEFAULT_MAX_FIRINGS)
        return int(value)
    except Exception:
        return DEFAULT_MAX_FIRINGS


def _columns(con, table):
    try:
        return {row[1] for row in
                con.execute("PRAGMA table_info(%s)" % table).fetchall()}
    except Exception:
        return set()


class FiringDb:
    """tiny append-only store; one writer thread (OvenWatcher)."""

    def __init__(self, path=None, max_firings=None, prune_on_start=True):
        self.path = os.path.abspath(path or configured_db_path())
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        # watcher thread owns writes; allow use from tests/other threads
        self._con = sqlite3.connect(self.path, timeout=10,
                                    check_same_thread=False)
        try:
            self._con.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        self._wipe_legacy()
        with self._con:
            self._con.execute(SCHEMA_FIRINGS)
            self._con.execute(SCHEMA_SAMPLES)
            self._con.execute(IDX_SAMPLES_FIRING)
        # run_started -> firing_id cache so each sample is one INSERT
        self._firing_ids = {}
        if prune_on_start:
            # prune on an isolated daemon thread so a large backlog
            # never blocks start-up or heater control.
            self.prune_old_firings_in_background(max_keep=max_firings)

    def _wipe_legacy(self):
        """drop pre-flat-schema tables for a clean start. the old
        layout stored pidstats JSON plus per-sample copies of the
        firing row; it is not migrated, it is replaced."""
        cols = _columns(self._con, "samples")
        if cols and cols.intersection(LEGACY_SAMPLE_COLUMNS):
            log.info("wiping legacy firing db schema for a clean start")
            with self._con:
                self._con.execute("DROP TABLE IF EXISTS samples")
                self._con.execute("DROP TABLE IF EXISTS firings")

    @staticmethod
    def _fnum(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _ensure_firing(self, oven_state, pid, run_started):
        """return the firing row id for this run_started, creating it
        with the run-fixed fields (profile, totaltime, pid constants)."""
        if run_started in self._firing_ids:
            return self._firing_ids[run_started]
        cur = self._con.execute(
            "SELECT id FROM firings WHERE run_started = ?", (run_started,))
        row = cur.fetchone()
        if row:
            self._firing_ids[run_started] = row[0]
            return row[0]
        cur = self._con.execute(
            "INSERT INTO firings (profile, run_id, run_started,"
            " started_wall, totaltime, kp, ki, kd)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (oven_state.get("profile"),
             oven_state.get("run_id"),
             run_started,
             time.time(),
             self._fnum(oven_state.get("totaltime")),
             self._fnum(pid.get("kp")),
             self._fnum(pid.get("ki")),
             self._fnum(pid.get("kd"))))
        firing_id = cur.lastrowid
        self._firing_ids[run_started] = firing_id
        return firing_id

    def record_state(self, oven_state):
        """persist one duty-cycle broadcast. never raises; True on write."""
        try:
            pid = oven_state.get("pidstats") or {}
            if not isinstance(pid, dict):
                pid = {}
            t = self._fnum(pid.get("time"))
            if t is None:
                t = time.time()
            run_started = oven_state.get("run_started")
            with self._lock:
                with self._con:
                    if run_started is not None:
                        firing_id = self._ensure_firing(oven_state, pid,
                                                        run_started)
                    else:
                        firing_id = None
                    self._con.execute(
                        "INSERT INTO samples (firing_id,"
                        " t, runtime, temp, target, state, heat,"
                        " cost, heat_rate, catching_up, temp_errors,"
                        " dt, err, ed, p, i, d, pid, out)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                        " ?, ?, ?, ?, ?, ?, ?, ?)",
                        (firing_id,
                         t,
                         self._fnum(oven_state.get("runtime")),
                         self._fnum(oven_state.get("temperature")),
                         self._fnum(oven_state.get("target")),
                         oven_state.get("state"),
                         self._fnum(oven_state.get("heat")),
                         self._fnum(oven_state.get("cost")),
                         self._fnum(oven_state.get("heat_rate")),
                         int(bool(oven_state.get("catching_up"))),
                         oven_state.get("temp_errors"),
                         self._fnum(pid.get("timeDelta")),
                         self._fnum(pid.get("err")),
                         self._fnum(pid.get("errDelta")),
                         self._fnum(pid.get("p")),
                         self._fnum(pid.get("i")),
                         self._fnum(pid.get("d")),
                         self._fnum(pid.get("pid")),
                         self._fnum(pid.get("out"))))
            return True
        except Exception as e:
            log.error("could not write firing sample: %s" % e)
            return False

    def close(self):
        try:
            self._con.close()
        except Exception:
            pass

    def prune_old_firings(self, max_keep=None):
        """delete firings (and their samples) beyond the newest max_keep.

        max_keep None reads config.firing_db_max_firings (default 10).
        max_keep <= 0 keeps everything. idle samples (firing_id NULL)
        are never touched. returns (deleted_firings, deleted_samples).
        never raises; errors are logged and (0, 0) is returned.
        """
        if max_keep is None:
            max_keep = get_max_firings()
        try:
            max_keep = int(max_keep)
        except Exception:
            log.error("invalid max_keep %r, skipping prune" % (max_keep,))
            return (0, 0)
        if max_keep <= 0:
            return (0, 0)
        try:
            with self._lock:
                with self._con:
                    keep_rows = self._con.execute(
                        "SELECT id FROM firings ORDER BY id DESC LIMIT ?",
                        (max_keep,)).fetchall()
                    keep_ids = [r[0] for r in keep_rows]
                    if not keep_ids:
                        return (0, 0)
                    placeholders = ",".join("?" for _ in keep_ids)
                    cur = self._con.execute(
                        "DELETE FROM samples WHERE firing_id IS NOT NULL"
                        " AND firing_id NOT IN (%s)" % placeholders,
                        keep_ids)
                    deleted_samples = cur.rowcount or 0
                    cur = self._con.execute(
                        "DELETE FROM firings WHERE id NOT IN (%s)"
                        % placeholders, keep_ids)
                    deleted_firings = cur.rowcount or 0
                    # drop cached ids for firings that no longer exist
                    for started, fid in list(self._firing_ids.items()):
                        if fid not in keep_ids:
                            # the row may still exist when fewer than
                            # max_keep firings remain; only drop ids that
                            # were actually deleted
                            cur = self._con.execute(
                                "SELECT 1 FROM firings WHERE id = ?", (fid,))
                            if cur.fetchone() is None:
                                del self._firing_ids[started]
            if deleted_firings:
                log.info("pruned %d old firing(s), %d sample(s)" %
                         (deleted_firings, deleted_samples))
            return (deleted_firings, deleted_samples)
        except Exception as e:
            log.error("could not prune old firings: %s" % e)
            return (0, 0)

    def prune_old_firings_in_background(self, max_keep=None):
        """prune old firings on an isolated daemon thread. returns it."""
        if max_keep is None:
            max_keep = get_max_firings()
        thread = threading.Thread(
            target=self.prune_old_firings, args=(max_keep,), daemon=True)
        thread.start()
        return thread
