'''Tests for alert detection: the AlertManager emission pipeline and the
per-condition detectors wired into the oven control loop and scheduler.

Ovens are built bare (no control thread) with a fake board, mirroring
the patterns used in test_oven.py. A recording sink is attached to a
real AlertManager so tests can assert exactly which alerts fired.'''

import json
import os
import time
import types

import pytest

from lib.alerts import ALERTS, AlertStore, AlertManager, LogSink
from lib.oven import END_COMPLETED, END_STOPPED, Oven, Profile
from lib.scheduler import Scheduler
from lib.temp import delta_to_c, to_c
import config


########################################################################
# helpers
########################################################################

class FakeThermocoupleStatus:
    def __init__(self):
        self.errors = 0

    def over_error_limit(self):
        return self.errors > 0

    def duty_cycle_errors(self):
        return self.errors


class FakeTempSensor:
    def __init__(self, temp):
        self.temp = temp
        self.status = FakeThermocoupleStatus()

    def temperature(self):
        return self.temp


class FakeBoard:
    def __init__(self, temp):
        self.temp_sensor = FakeTempSensor(temp)


class RecordingSink:
    def __init__(self):
        self.calls = []

    def deliver(self, alert_id, label, criticality, context):
        self.calls.append((alert_id, label, criticality, context))


def recording_manager(enabled_ids=None):
    '''a real AlertManager whose sink records deliveries'''
    store = AlertStore(state_file='/nonexistent/alerts.json')
    if enabled_ids is not None:
        for a in ALERTS:
            store.enabled[a['id']] = a['id'] in enabled_ids
    manager = AlertManager(store)
    sink = RecordingSink()
    manager.add_sink(sink)
    return manager, sink


def make_oven(temp_c=20.0):
    '''a bare oven (no control thread) with a fake board and an
    attached recording manager'''
    manager, sink = recording_manager()
    oven = Oven()
    oven.board = FakeBoard(temp_c)
    oven.set_alert_manager(manager)
    return oven, manager, sink


def fast_profile():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        'test-fast.json'))
    with open(path) as infile:
        return Profile(json.dumps(json.load(infile)))


@pytest.fixture
def no_restart_writes(monkeypatch):
    '''keep tests from writing the real automatic-restart state file'''
    monkeypatch.setattr(config, 'automatic_restarts', False)


class FakeClock:
    '''replaces lib.oven time.time so detectors can be driven forward'''

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    '''one controllable clock driving both oven detectors (time.time)
    and AlertManager cooldowns (time.monotonic)'''
    clock = FakeClock()
    import lib.oven as oven_module
    import lib.alerts as alerts_module
    monkeypatch.setattr(oven_module.time, 'time', clock)
    monkeypatch.setattr(alerts_module.time, 'monotonic', clock)
    return clock


########################################################################
# AlertManager
########################################################################

def test_emit_delivers_label_criticality_and_context():
    manager, sink = recording_manager()
    assert manager.emit('run_completed', context={'profile': 'bisque'}) is True
    alert_id, label, criticality, context = sink.calls[0]
    assert alert_id == 'run_completed'
    assert label == 'Run completed'
    assert criticality == 'info'
    assert context == {'profile': 'bisque'}


def test_emit_suppressed_when_disabled_in_store():
    manager, sink = recording_manager(enabled_ids=['relay_stuck_on'])
    assert manager.emit('relay_stuck_on', context={}) is True
    assert manager.emit('temp_implausible', context={}) is False
    assert [c[0] for c in sink.calls] == ['relay_stuck_on']


def test_emit_unknown_id_rejected_without_delivery():
    manager, sink = recording_manager()
    assert manager.emit('not_a_real_alert') is False
    assert sink.calls == []


def test_condition_cooldown_suppresses_repeats(fake_clock):
    manager, sink = recording_manager()
    assert manager.emit('temp_implausible') is True
    fake_clock.advance(10)
    assert manager.emit('temp_implausible') is False
    assert len(sink.calls) == 1


def test_condition_cooldown_expires(fake_clock):
    manager, sink = recording_manager()
    manager.condition_cooldown = 300
    assert manager.emit('temp_implausible') is True
    fake_clock.advance(301)
    assert manager.emit('temp_implausible') is True
    assert len(sink.calls) == 2


def test_event_alerts_bypass_cooldown(fake_clock):
    manager, sink = recording_manager()
    for _ in range(3):
        assert manager.emit('run_started') is True
    assert len(sink.calls) == 3


def test_sink_failure_does_not_block_other_sinks():
    manager, _ = recording_manager()

    class ExplodingSink:
        def deliver(self, *args):
            raise RuntimeError('boom')

    later = RecordingSink()
    manager.add_sink(ExplodingSink())
    manager.add_sink(later)
    assert manager.emit('run_completed') is True
    assert len(later.calls) == 1


def test_logsink_delivers_warning(caplog):
    sink = LogSink()
    with caplog.at_level('WARNING', logger='alerts'):
        sink.deliver('emergency_shutoff', 'Emergency shutoff fired',
                     'critical', {'temperature': 2300})
    assert 'Emergency shutoff fired' in caplog.text
    assert 'temperature' in caplog.text


########################################################################
# existing conditions wired to emissions
########################################################################

def test_emergency_shutoff_emits_and_aborts(no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(2400))  # above the 2264F limit
    oven.state = 'RUNNING'
    oven.profile = fast_profile()
    oven.reset_if_emergency()
    ids = [c[0] for c in sink.calls]
    assert 'emergency_shutoff' in ids
    assert oven.state == 'IDLE'


def test_emergency_shutoff_emits_even_when_ignored(monkeypatch, no_restart_writes):
    monkeypatch.setattr(config, 'ignore_temp_too_high', True)
    oven, _, sink = make_oven(temp_c=to_c(2400))
    oven.state = 'RUNNING'
    oven.profile = fast_profile()
    oven.reset_if_emergency()
    assert 'emergency_shutoff' in [c[0] for c in sink.calls]
    # ignored: the run keeps going
    assert oven.state == 'RUNNING'


def test_tc_failure_emits_and_aborts(no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(212))
    oven.state = 'RUNNING'
    oven.profile = fast_profile()
    oven.board.temp_sensor.status.errors = 99
    oven.reset_if_emergency()
    ids = [c[0] for c in sink.calls]
    assert 'tc_failure' in ids
    assert oven.state == 'IDLE'


def test_heat_rate_too_low_emits_and_aborts(no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(212))
    oven.state = 'RUNNING'
    oven.profile = fast_profile()
    # emergency_heat_rate_window is 22.5 min; place the run inside
    # test-fast's ramp segment (3600s..10800s) so target_is_rising()
    # applies. seed one old sample one full window back; the check
    # appends the current board reading. the kiln moved 1F over the
    # window -> rate far below the minimum
    window = config.emergency_heat_rate_window * 60
    oven.emergency_heat_rate_temps = [(5000 - window, to_c(213))]
    oven.runtime = 5000
    oven.check_heat_rate_emergency()
    ids = [c[0] for c in sink.calls]
    assert 'heat_rate_too_low' in ids
    assert oven.state == 'IDLE'
    aborted = [c for c in sink.calls if c[0] == 'run_aborted']
    assert aborted and aborted[0][3]['reason'] == 'heat rate too low'


########################################################################
# run-end reasons
########################################################################

def test_natural_completion_emits_run_completed(no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(500))  # kiln still hot at the end
    oven.state = 'RUNNING'
    oven.profile = fast_profile()
    oven.run_sequence = 4
    oven.runtime = oven.totaltime + 1
    oven.reset_if_schedule_ended()
    ids = [c[0] for c in sink.calls]
    assert 'run_completed' in ids
    assert 'run_aborted' not in ids
    completed = next(c for c in sink.calls if c[0] == 'run_completed')
    assert completed[3]['profile'] == 'test-fast'
    # test-fast ends at 801F, well above cooled_safe_temp, so armed
    assert oven.cooled_safe_armed_for == 4


def test_abort_emits_run_aborted_with_reason(no_restart_writes):
    oven, _, sink = make_oven()
    oven.state = 'RUNNING'
    oven.profile = fast_profile()
    oven.abort_run(reason='temperature too high')
    aborted = [c for c in sink.calls if c[0] == 'run_aborted']
    assert len(aborted) == 1
    assert aborted[0][3]['reason'] == 'temperature too high'
    assert [c[0] for c in sink.calls if c[0] == 'run_completed'] == []


def test_user_stop_is_silent(no_restart_writes):
    oven, _, sink = make_oven()
    oven.state = 'RUNNING'
    oven.profile = fast_profile()
    oven.abort_run(END_STOPPED)
    ids = [c[0] for c in sink.calls]
    assert 'run_aborted' not in ids
    assert 'run_completed' not in ids


def test_end_while_idle_emits_nothing(no_restart_writes):
    oven, _, sink = make_oven()
    oven.state = 'IDLE'
    oven.abort_run(reason='temperature too high')
    assert sink.calls == []


########################################################################
# cooled_safe
########################################################################

def test_cooled_safe_not_armed_when_already_cool(no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(90))
    oven.state = 'RUNNING'
    oven.profile = fast_profile()
    oven.abort_run(reason=END_COMPLETED)
    assert oven.cooled_safe_armed_for is None
    assert [c[0] for c in sink.calls if c[0] == 'cooled_safe'] == []


def test_cooled_safe_fires_once_cool(no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(500))
    oven.state = 'RUNNING'
    oven.profile = fast_profile()
    oven.run_sequence = 7
    oven.abort_run(reason=END_COMPLETED)
    assert oven.cooled_safe_armed_for == 7

    oven.board.temp_sensor.temp = to_c(120)  # below the 150F threshold
    oven.check_cooled_safe()
    fired = [c for c in sink.calls if c[0] == 'cooled_safe']
    assert len(fired) == 1
    assert fired[0][3]['run_id'] == 7
    assert oven.cooled_safe_armed_for is None

    # stays disarmed
    oven.check_cooled_safe()
    assert len([c for c in sink.calls if c[0] == 'cooled_safe']) == 1


def test_new_run_disarms_cooled_safe(no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(500))
    oven.cooled_safe_armed_for = 3
    oven.run_profile(fast_profile(), allow_seek=False)
    assert oven.cooled_safe_armed_for is None


########################################################################
# relay_stuck_on / temp_implausible
########################################################################

def test_relay_stuck_on_fires_after_window(fake_clock, no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(600))
    window = config.relay_stuck_on_window * 60

    oven.check_safety_detectors()  # baseline
    steps = 12
    for _ in range(steps):
        fake_clock.advance(window / steps)
        oven.board.temp_sensor.temp += delta_to_c(
            (config.relay_stuck_on_rise + 10) / steps)
        oven.check_safety_detectors()

    fired = [c for c in sink.calls if c[0] == 'relay_stuck_on']
    assert len(fired) == 1
    assert fired[0][3]['rise'] > config.relay_stuck_on_rise
    # buffer was cleared: no immediate second firing
    oven.check_safety_detectors()
    assert len([c for c in sink.calls if c[0] == 'relay_stuck_on']) == 1


def test_relay_detector_clears_when_heat_commanded(fake_clock, no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(600))
    oven.check_safety_detectors()
    oven.heat = 1.0
    oven.check_safety_detectors()
    assert oven.relay_off_temps == []


def test_relay_detector_skips_tuning_state(fake_clock, no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(600))
    oven.state = 'TUNING'
    oven.check_safety_detectors()
    assert oven.relay_off_temps == []
    assert [c[0] for c in sink.calls if c[0] == 'relay_stuck_on'] == []


def test_small_rise_does_not_fire(fake_clock, no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(600))
    window = config.relay_stuck_on_window * 60
    oven.check_safety_detectors()
    for _ in range(6):  # residual-heat level rise only
        fake_clock.advance(window / 6)
        oven.board.temp_sensor.temp += delta_to_c(1)
        oven.check_safety_detectors()
    assert [c[0] for c in sink.calls if c[0] == 'relay_stuck_on'] == []


def test_temp_implausible_jump_fires_then_rebaselines(fake_clock, no_restart_writes):
    oven, _, sink = make_oven(temp_c=to_c(200))
    oven.check_safety_detectors()  # baseline
    oven.board.temp_sensor.temp = to_c(400)  # absurd leap
    oven.check_safety_detectors()
    fired = [c for c in sink.calls if c[0] == 'temp_implausible']
    assert len(fired) == 1
    # context carries both readings in the display scale (fahrenheit)
    assert fired[0][3]['previous'] == pytest.approx(200)
    assert fired[0][3]['current'] == pytest.approx(400)
    # rebaselined: same reading again does not refire inside cooldown
    oven.check_safety_detectors()
    assert len([c for c in sink.calls if c[0] == 'temp_implausible']) == 1


########################################################################
# catch_up_stalled
########################################################################

def test_catch_up_stall_fires_once_per_episode(fake_clock, no_restart_writes):
    oven, _, sink = make_oven()
    oven.state = 'RUNNING'
    oven.profile = fast_profile()

    oven.catching_up = True
    oven.check_catch_up_stalled()          # starts the timer
    fake_clock.advance(config.catch_up_stalled_minutes * 60 + 5)
    oven.check_catch_up_stalled()          # past the limit: fires
    oven.check_catch_up_stalled()          # does not repeat this episode
    assert len([c for c in sink.calls if c[0] == 'catch_up_stalled']) == 1

    # recovery ends the episode; a new stall can fire again
    oven.catching_up = False
    oven.check_catch_up_stalled()
    oven.catching_up = True
    oven.check_catch_up_stalled()
    fake_clock.advance(config.catch_up_stalled_minutes * 60 + 5)
    oven.check_catch_up_stalled()
    assert len([c for c in sink.calls if c[0] == 'catch_up_stalled']) == 2


########################################################################
# power-outage pair
########################################################################

def stale_running_state(tmp_path, monkeypatch, name='state.json'):
    path = tmp_path / name
    path.write_text(json.dumps({'state': 'RUNNING',
                                'profile': 'bisque-fire',
                                'runtime': 3600}))
    old = time.time() - (config.automatic_restart_window + 30) * 60
    os.utime(path, (old, old))
    monkeypatch.setattr(config, 'automatic_restart_state_file', str(path))
    return path


@pytest.fixture
def restarts_on(no_restart_writes):
    '''outage detection only runs when automatic restarts are enabled;
    re-enable it after the no_restart_writes fixture turned it off'''
    config.automatic_restarts = True
    yield
    config.automatic_restarts = False


def test_restart_not_resumed_detected(tmp_path, monkeypatch,
                                      no_restart_writes, restarts_on):
    stale_running_state(tmp_path, monkeypatch)

    oven, _, sink = make_oven()
    oven.restart_outage_checked = False
    oven.check_unresumed_outage()
    fired = [c for c in sink.calls if c[0] == 'restart_not_resumed']
    assert len(fired) == 1
    assert fired[0][3]['profile'] == 'bisque-fire'
    assert fired[0][3]['runtime_minutes'] == 60


def test_no_false_alarm_for_fresh_or_idle_state_files(
        tmp_path, monkeypatch, no_restart_writes, restarts_on):
    oven, _, sink = make_oven()

    # fresh RUNNING file: should_i_automatic_restart handles it instead
    fresh = tmp_path / 'fresh.json'
    fresh.write_text(json.dumps({'state': 'RUNNING', 'profile': 'p'}))
    monkeypatch.setattr(config, 'automatic_restart_state_file', str(fresh))
    oven.check_unresumed_outage()
    assert sink.calls == []

    # stale but idle file: clean shutdown, nothing to report
    idle = tmp_path / 'idle.json'
    idle.write_text(json.dumps({'state': 'IDLE', 'profile': None}))
    old = time.time() - (config.automatic_restart_window + 30) * 60
    os.utime(idle, (old, old))
    monkeypatch.setattr(config, 'automatic_restart_state_file', str(idle))
    oven.check_unresumed_outage()
    assert sink.calls == []


def test_outage_check_runs_once_from_idle_loop(tmp_path, monkeypatch,
                                               no_restart_writes, restarts_on):
    stale_running_state(tmp_path, monkeypatch)

    should_calls = []

    oven, _, sink = make_oven()
    oven.restart_outage_checked = False
    monkeypatch.setattr(oven, 'should_i_automatic_restart',
                        lambda: should_calls.append(1))

    class NoSleep:
        count = 0

        def __call__(self, secs):
            NoSleep.count += 1
            if NoSleep.count >= 3:
                raise StopIteration

    import lib.oven as oven_module
    monkeypatch.setattr(oven_module.time, 'sleep', NoSleep())
    with pytest.raises(StopIteration):
        oven._run_once()
        oven._run_once()
        oven._run_once()

    assert len([c for c in sink.calls if c[0] == 'restart_not_resumed']) == 1
    assert len(should_calls) == 3  # idle loop kept running normally


def test_restart_resumed_emitted(tmp_path, monkeypatch, no_restart_writes):
    '''the full automatic_restart path emits restart_resumed'''
    tmp_path_state = tmp_path / 'state.json'
    tmp_path_state.write_text(json.dumps({
        'state': 'RUNNING', 'profile': 'alerttest-prof-xyz',
        'runtime': 1800, 'cost': 1.25}))
    monkeypatch.setattr(config, 'automatic_restart_state_file',
                        str(tmp_path_state))

    # automatic_restart reads its profile from storage/profiles; use a
    # unique name so parallel runs cannot collide, cleaned up after
    profiles_dir = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', 'storage', 'profiles'))
    prof_path = os.path.join(profiles_dir, 'alerttest-prof-xyz.json')
    with open(prof_path, 'w') as f:
        json.dump({'name': 'alerttest-prof-xyz',
                   'data': [[0, 80], [60, 200]]}, f)
    try:
        oven, _, sink = make_oven()
        oven.ovenwatcher = types.SimpleNamespace(record=lambda p: None)
        monkeypatch.setattr(Oven, 'run_profile', lambda self, p, **kw: None)
        import lib.oven as oven_module
        monkeypatch.setattr(oven_module.time, 'sleep', lambda s: None)

        oven.automatic_restart()
        fired = [c for c in sink.calls if c[0] == 'restart_resumed']
        assert len(fired) == 1
        assert fired[0][3]['profile'] == 'alerttest-prof-xyz'
        assert fired[0][3]['runtime_minutes'] == 30
    finally:
        os.remove(prof_path)


########################################################################
# scheduled_run_missed
########################################################################

def test_scheduler_missed_run_emits_alert(tmp_path):
    sched = Scheduler(state_file=str(tmp_path / 'sched.json'))
    emitted = []
    sched.alert_emit = lambda alert_id, context=None: emitted.append(
        (alert_id, context))

    sched.add('bisque-fire', start_time=time.time() - 60)
    sched.fire_callback = lambda e: False  # cannot start (profile missing)
    sched.fire_due()

    assert len(emitted) == 1
    assert emitted[0][0] == 'scheduled_run_missed'
    assert emitted[0][1]['profile'] == 'bisque-fire'
    assert sched.list()[0]['status'] == 'skipped'


def test_scheduler_chained_wait_does_not_emit(tmp_path):
    sched = Scheduler(state_file=str(tmp_path / 'sched.json'))
    emitted = []
    sched.alert_emit = lambda alert_id, context=None: emitted.append(alert_id)

    entry = sched.add('glaze-fire', start_time=time.time())
    entry['chain_after'] = 'run:1'
    sched.fire_callback = lambda e: False  # anchor not finished -> wait
    sched.fire_due()

    assert emitted == []
    assert sched.list()[0]['status'] == 'waiting'


########################################################################
# disabled flags actually gate detection end to end
########################################################################

def test_disabled_condition_never_delivered(fake_clock, no_restart_writes):
    manager, sink = recording_manager(enabled_ids=[])
    oven = Oven()
    oven.board = FakeBoard(to_c(200))
    oven.set_alert_manager(manager)
    oven.check_safety_detectors()
    oven.board.temp_sensor.temp = to_c(500)
    oven.check_safety_detectors()
    assert sink.calls == []
