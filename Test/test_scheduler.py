import time

import pytest

from lib.scheduler import Scheduler


@pytest.fixture
def scheduler(tmp_path):
    return Scheduler(state_file=str(tmp_path / 'schedules.json'))


########################################################################
# add / list / cancel
########################################################################

def test_add_creates_entry(scheduler):
    entry = scheduler.add('cone-05-long-bisque', time.time() + 3600)
    assert entry['id']
    assert entry['profile'] == 'cone-05-long-bisque'
    assert entry['fired'] is False
    assert entry['status'] == 'pending'
    assert len(scheduler.list()) == 1


def test_add_persists_across_reload(tmp_path):
    s1 = Scheduler(state_file=str(tmp_path / 'schedules.json'))
    s1.add('cone-05-long-bisque', 1234567890)
    s2 = Scheduler(state_file=str(tmp_path / 'schedules.json'))
    runs = s2.list()
    assert len(runs) == 1
    assert runs[0]['profile'] == 'cone-05-long-bisque'
    assert runs[0]['start_time'] == 1234567890


def test_load_missing_file_gives_empty_list(tmp_path):
    s = Scheduler(state_file=str(tmp_path / 'does-not-exist.json'))
    assert s.list() == []


def test_load_bad_json_gives_empty_list(tmp_path):
    path = tmp_path / 'schedules.json'
    path.write_text('not json')
    s = Scheduler(state_file=str(path))
    assert s.list() == []


def test_cancel(scheduler):
    entry = scheduler.add('cone-05-long-bisque', time.time() + 3600)
    assert scheduler.cancel(entry['id']) is True
    assert scheduler.list() == []


def test_cancel_missing_returns_false(scheduler):
    assert scheduler.cancel('nope') is False


def test_cancel_keeps_unrelated_runs(scheduler):
    a = scheduler.add('profile-a', time.time() + 3600)
    b = scheduler.add('profile-b', time.time() + 7200)
    assert scheduler.cancel(a['id']) is True
    assert [r['profile'] for r in scheduler.list()] == ['profile-b']


def test_save_creates_missing_directory(tmp_path):
    s = Scheduler(state_file=str(tmp_path / 'nested' / 'dir' / 'schedules.json'))
    s.add('cone-6-long-glaze', time.time() + 3600)
    assert (tmp_path / 'nested' / 'dir' / 'schedules.json').exists()


########################################################################
# firing
########################################################################

def test_pending_only_due_and_unfired(scheduler):
    scheduler.add('a', time.time() + 3600)
    past = scheduler.add('b', time.time() - 10)
    assert [e['id'] for e in scheduler.pending()] == [past['id']]


def test_pending_excludes_fired(scheduler):
    entry = scheduler.add('b', time.time() - 10)
    scheduler.mark_fired(entry)
    assert scheduler.pending() == []


def test_fire_calls_callback_and_marks_fired(scheduler):
    calls = []
    scheduler.fire_callback = lambda entry: calls.append(entry) or True
    entry = scheduler.add('b', time.time() - 10)
    scheduler.fire(entry)
    assert calls == [entry]
    runs = scheduler.list()
    assert runs[0]['fired'] is True
    assert runs[0]['status'] == 'fired'


def test_fire_marks_skipped_when_callback_fails(scheduler):
    scheduler.fire_callback = lambda entry: False
    entry = scheduler.add('b', time.time() - 10)
    scheduler.fire(entry)
    runs = scheduler.list()
    assert runs[0]['fired'] is True
    assert runs[0]['status'] == 'skipped'


def test_fire_marks_skipped_when_no_callback(scheduler):
    entry = scheduler.add('b', time.time() - 10)
    scheduler.fire(entry)
    runs = scheduler.list()
    assert runs[0]['fired'] is True
    assert runs[0]['status'] == 'skipped'


def test_fire_handles_callback_exception(scheduler):
    def boom(entry):
        raise RuntimeError('boom')
    scheduler.fire_callback = boom
    entry = scheduler.add('b', time.time() - 10)
    scheduler.fire(entry)
    runs = scheduler.list()
    assert runs[0]['fired'] is True
    assert runs[0]['status'] == 'skipped'


########################################################################
# chaining a firing after another
########################################################################

def test_add_chained_entry_stores_chain_after(scheduler):
    entry = scheduler.add('b', time.time() + 3600, chain_after='run:7')
    assert entry['chain_after'] == 'run:7'


def test_pending_includes_chained_before_start_time(scheduler):
    # a chained run is pending immediately; its start_time is only an
    # estimate, and the real start waits for the firing it follows.
    entry = scheduler.add('b', time.time() + 3600, chain_after='run:7')
    assert [e['id'] for e in scheduler.pending()] == [entry['id']]


def test_fire_chained_waits_instead_of_skipping(scheduler):
    scheduler.fire_callback = lambda entry: False
    entry = scheduler.add('b', time.time() - 10, chain_after='run:7')
    scheduler.fire(entry)
    runs = scheduler.list()
    assert runs[0]['fired'] is False
    assert runs[0]['status'] == 'waiting'
    # still pending so the next poll retries it
    assert [e['id'] for e in scheduler.pending()] == [entry['id']]


def test_fire_chained_succeeds_like_any_other(scheduler):
    calls = []
    scheduler.fire_callback = lambda entry: calls.append(entry) or True
    entry = scheduler.add('b', time.time() - 10, chain_after='run:7')
    scheduler.fire(entry)
    runs = scheduler.list()
    assert calls == [entry]
    assert runs[0]['fired'] is True
    assert runs[0]['status'] == 'fired'


def test_cancel_removes_chained_runs(scheduler):
    anchor = scheduler.add('a', time.time() + 3600)
    chained = scheduler.add('b', time.time() + 7200, chain_after='sched:' + anchor['id'])
    assert scheduler.cancel(anchor['id']) is True
    remaining = scheduler.list()
    assert all(e['id'] != anchor['id'] for e in remaining)
    assert all(e['id'] != chained['id'] for e in remaining)


def test_run_loop_fires_due_runs_until_interrupted(scheduler, monkeypatch):
    import lib.scheduler as sched_mod

    fired = []
    scheduler.fire_callback = lambda entry: fired.append(entry['profile']) or True
    scheduler.add('cone-05-long-bisque', time.time() - 10)

    sleeps = []

    def fake_sleep(secs):
        sleeps.append(secs)
        raise KeyboardInterrupt

    monkeypatch.setattr(sched_mod.time, 'sleep', fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        scheduler.run()

    assert fired == ['cone-05-long-bisque']
    assert sleeps
    runs = scheduler.list()
    assert runs[0]['fired'] is True
    assert runs[0]['status'] == 'fired'


def test_run_loop_keeps_going_after_callback_error(scheduler, monkeypatch):
    import lib.scheduler as sched_mod

    def boom(entry):
        raise RuntimeError('kaboom')

    scheduler.fire_callback = boom
    scheduler.add('cone-05-long-bisque', time.time() - 10)

    sleeps = []

    def fake_sleep(secs):
        sleeps.append(secs)
        if len(sleeps) >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(sched_mod.time, 'sleep', fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        scheduler.run()

    assert len(sleeps) == 2
    # the failing run is marked skipped, not retried forever
    runs = scheduler.list()
    assert runs[0]['status'] == 'skipped'


def test_run_loop_survives_fire_due_error(scheduler, monkeypatch):
    import lib.scheduler as sched_mod

    def boom():
        raise RuntimeError('pending exploded')

    monkeypatch.setattr(scheduler, 'pending', boom)

    sleeps = []

    def fake_sleep(secs):
        sleeps.append(secs)
        raise KeyboardInterrupt

    monkeypatch.setattr(sched_mod.time, 'sleep', fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        scheduler.run()

    assert len(sleeps) == 1
