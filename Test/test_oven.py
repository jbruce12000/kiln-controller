import datetime
import json
import os
import sys
import time
import types

import pytest

from lib.oven import (
    DupFilter,
    Duplogger,
    Max31855_Error,
    Max31856_Error,
    Oven,
    PID,
    Profile,
    SimulatedOven,
    TempSensorReal,
    TempTracker,
    ThermocoupleTracker,
)
import config
from lib.temp import to_c


def get_profile(file="test-fast.json"):
    profile_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Test', file))
    with open(profile_path) as infile:
        profile_json = json.dumps(json.load(infile))
    return Profile(profile_json)


class FakeThermocoupleStatus:
    def __init__(self):
        self.errors = 0

    def over_error_limit(self):
        return False

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


@pytest.fixture
def no_auto_restarts(monkeypatch):
    monkeypatch.setattr(config, 'automatic_restarts', False)
    monkeypatch.setattr(config, 'thermocouple_offset', 0)


########################################################################
# Profile
########################################################################

def test_get_target_temperature():
    profile = get_profile()

    assert int(profile.get_target_temperature(3000)) == 200
    assert profile.get_target_temperature(6004) == 801.0


def test_get_target_temperature_after_end_is_zero():
    profile = get_profile()
    assert profile.get_target_temperature(20000) == 0


def test_get_duration():
    profile = get_profile()
    assert profile.get_duration() == 19400


def test_find_time_from_temperature():
    profile = get_profile()

    assert profile.find_next_time_from_temperature(500) == 4800
    assert profile.find_next_time_from_temperature(2004) == 10857.6
    assert profile.find_next_time_from_temperature(1900) == 10400.0


def test_find_time_odd_profile():
    profile = get_profile("test-cases.json")

    assert profile.find_next_time_from_temperature(500) == 4200
    assert profile.find_next_time_from_temperature(2023) == 16676.0


def test_find_time_below_start_is_zero():
    profile = get_profile()
    assert profile.find_next_time_from_temperature(100) == 0


def test_find_x_given_y_on_line_from_two_points():
    profile = get_profile()

    p1 = [3600, 200]
    p2 = [10800, 2000]
    assert profile.find_x_given_y_on_line_from_two_points(500, p1, p2) == 4800

    # flat or descending segments should return 0 (no seek)
    assert profile.find_x_given_y_on_line_from_two_points(500, [3600, 200], [10800, 200]) == 0
    assert profile.find_x_given_y_on_line_from_two_points(500, [3600, 600], [10800, 600]) == 0
    assert profile.find_x_given_y_on_line_from_two_points(500, [3600, 500], [10800, 500]) == 0
    assert profile.find_x_given_y_on_line_from_two_points(500, [10800, 600], [3600, 600]) == 0


def test_get_surrounding_points():
    profile = get_profile()
    prev, nxt = profile.get_surrounding_points(5000)
    assert prev == [3600, 200]
    assert nxt == [10800, 2000]
    assert profile.get_surrounding_points(20000) == (None, None)


def test_profile_sorts_data():
    profile = Profile('{"name": "x", "data": [[3600, 200], [0, 100]]}')
    assert profile.data == [[0, 100], [3600, 200]]


########################################################################
# PID
########################################################################

def test_pid_max_heating():
    pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
    out = pid.compute(500, 100, datetime.datetime(2020, 1, 1))
    assert out == 1
    assert pid.pidstats['err'] == 400


def test_pid_max_cooling():
    pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
    out = pid.compute(100, 500, datetime.datetime(2020, 1, 1))
    assert out == 0
    assert pid.pidstats['err'] == -400


def test_pid_throttle_below_threshold(monkeypatch):
    # config.throttle_below_temp is in the display scale (f here), the
    # pid compares against the celsius setpoint internally
    monkeypatch.setattr(config, 'throttle_below_temp', 300)
    monkeypatch.setattr(config, 'throttle_percent', 20)
    pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
    # 200f setpoint = 93.3c, below 300f = 148.9c -> throttled
    out = pid.compute(to_c(200), 50, datetime.datetime(2020, 1, 1))
    assert out == pytest.approx(0.2)


def test_pid_throttle_below_threshold_celsius(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'c')
    monkeypatch.setattr(config, 'throttle_below_temp', 150)
    monkeypatch.setattr(config, 'throttle_percent', 20)
    pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
    out = pid.compute(100, 50, datetime.datetime(2020, 1, 1))
    assert out == pytest.approx(0.2)


def test_pid_no_throttle_above_threshold(monkeypatch):
    monkeypatch.setattr(config, 'throttle_below_temp', 300)
    monkeypatch.setattr(config, 'throttle_percent', 20)
    pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
    # 1000c setpoint is way above 300f = 148.9c -> no throttle
    out = pid.compute(1000, 100, datetime.datetime(2020, 1, 1))
    assert out == 1


def test_pid_inside_window():
    pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
    now1 = datetime.datetime(2020, 1, 1)
    now2 = now1 + datetime.timedelta(seconds=2)
    pid.lastNow = now1
    out = pid.compute(100, 98, now2)
    assert 0 <= out <= 1
    assert 'setpoint' in pid.pidstats
    assert pid.pidstats['setpoint'] == 100
    assert pid.pidstats['ispoint'] == 98
    assert pid.pidstats['err'] == 2
    assert pid.pidstats['timeDelta'] == 2
    assert pid.pidstats['out'] == 1.0  # clamped to the window


def test_pid_never_outputs_negative():
    pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
    now1 = datetime.datetime(2020, 1, 1)
    now2 = now1 + datetime.timedelta(seconds=2)
    pid.lastNow = now1
    out = pid.compute(100, 102, now2)
    assert out == 0


def test_pid_time_delta_unaffected_by_dst():
    # PID timeDelta must measure real elapsed time, not naive wall-clock
    # difference. across the spring-forward transition naive subtraction
    # reports 2 hours even though only 1 hour really passed.
    old_tz = os.environ.get('TZ')
    os.environ['TZ'] = 'America/New_York'
    time.tzset()
    try:
        pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
        now1 = datetime.datetime(2020, 3, 8, 1, 30)  # before the 2am jump
        now2 = datetime.datetime(2020, 3, 8, 3, 30)  # after the jump
        pid.lastNow = now1
        pid.compute(100, 98, now2)
        assert pid.pidstats['timeDelta'] == pytest.approx(3600, abs=2)
    finally:
        if old_tz is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = old_tz
        time.tzset()


########################################################################
# Oven
########################################################################

def test_get_start_from_temperature():
    profile = get_profile()
    # above the initial profile temp by more than 5 degrees -> seek forward
    assert Oven.get_start_from_temperature(profile, 250) == 3800
    # at or near the starting temp -> start at zero
    assert Oven.get_start_from_temperature(profile, 200) == 0
    assert Oven.get_start_from_temperature(profile, 100) == 0


def test_set_heat_rate():
    oven = Oven()
    oven.set_heat_rate(0, 100)
    oven.set_heat_rate(60, 200)
    assert oven.heat_rate == pytest.approx(6000)


def test_set_heat_rate_when_no_time_elapsed():
    oven = Oven()
    oven.set_heat_rate(0, 100)
    oven.set_heat_rate(0, 100)
    assert oven.heat_rate == 0


def test_set_heat_rate_caps_window():
    oven = Oven()
    for i in range(70):
        oven.set_heat_rate(i, i * 10)
    assert len(oven.heat_rate_temps) == 60


def test_run_profile(no_auto_restarts):
    oven = Oven()
    profile = get_profile()
    oven.run_profile(profile, startat=10, allow_seek=False)
    assert oven.state == "RUNNING"
    assert oven.runtime == 600
    assert oven.startat == 600
    assert oven.totaltime == 19400
    assert oven.profile is profile


def test_run_profile_seek_start_time_matches_runtime(no_auto_restarts, monkeypatch):
    '''seek offset must be reflected in start_time so update_runtime
    preserves the sought position. previously start_time was derived from
    startat alone and the seek silently reset to zero unless
    kiln_must_catch_up happened to shift it back.'''
    monkeypatch.setattr(config, 'kiln_must_catch_up', False)
    oven = Oven()
    oven.board = FakeBoard(250)  # kiln still hot from a previous run
    oven.run_profile(get_profile(), startat=0, allow_seek=True)
    # seek found 3800s into the profile for a 250c oven
    assert oven.runtime == 3800
    # start_time must be set back by the runtime, not just startat
    offset = time.time() - oven.start_time
    assert offset == pytest.approx(3800, abs=2)
    # and update_runtime keeps the sought position instead of zeroing it
    oven.update_runtime()
    assert oven.runtime == pytest.approx(3800, abs=2)
    oven.update_target_temp()
    assert oven.target == pytest.approx(250.0)


def test_run_profile_no_seek_start_time_matches_startat(no_auto_restarts):
    oven = Oven()
    oven.board = FakeBoard(250)
    oven.run_profile(get_profile(), startat=10, allow_seek=False)
    assert oven.runtime == 600
    offset = time.time() - oven.start_time
    assert offset == pytest.approx(600, abs=2)
    oven.update_runtime()
    assert oven.runtime == pytest.approx(600, abs=2)
    oven.update_target_temp()
    assert oven.target == pytest.approx(200.0)


def test_run_sequence_increments_and_run_id_in_status(no_auto_restarts):
    # each firing gets a fresh run_id so a scheduled firing can chain
    # after the specific run that is in progress.
    oven = Oven()
    oven.board = FakeBoard(250)
    oven.run_profile(get_profile(), startat=0, allow_seek=False)
    assert oven.run_sequence == 1
    assert oven.get_state()['run_id'] == 1
    oven.run_profile(get_profile(), startat=0, allow_seek=False)
    assert oven.run_sequence == 2
    assert oven.get_state()['run_id'] == 2


def test_abort_run_tracks_ended_sequence_and_idle_since(no_auto_restarts):
    import time as _time
    oven = Oven()
    oven.board = FakeBoard(250)
    oven.run_profile(get_profile(), startat=0, allow_seek=False)
    seq = oven.run_sequence
    oven.abort_run()
    assert oven.ended_run_sequence == seq
    assert oven.idle_since == pytest.approx(_time.time(), abs=5)
    assert oven.state == "IDLE"
    # a new firing gets a higher sequence; the ended sequence only
    # advances when that firing actually ends
    oven.run_profile(get_profile(), startat=0, allow_seek=False)
    assert oven.run_sequence == seq + 1
    assert oven.ended_run_sequence == seq


def test_get_state():
    oven = Oven()
    state = oven.get_state()
    assert state['state'] == 'IDLE'
    assert state['profile'] is None
    assert state['pidstats'] == {}
    for key in ('cost', 'runtime', 'temperature', 'target', 'heat',
                'heat_rate', 'totaltime', 'kwh_rate', 'currency_type',
                'profile', 'pidstats', 'catching_up', 'temp_errors'):
        assert key in state


def test_get_state_reports_duty_cycle_read_errors():
    oven = Oven()
    oven.board = FakeBoard(250)
    oven.board.temp_sensor.status.errors = 4
    assert oven.get_state()['temp_errors'] == 4


def test_get_state_reports_display_scale(monkeypatch):
    # internally everything is celsius, get_state reports the display scale
    monkeypatch.setattr(config, 'temp_scale', 'f')
    oven = Oven()
    oven.board = FakeBoard(100)     # 100c internal
    oven.target = 200               # 200c internal
    oven.heat_rate = 300            # 300 c/hr internal
    state = oven.get_state()
    assert state['temperature'] == pytest.approx(212.0)  # 100c -> 212f
    assert state['target'] == pytest.approx(392.0)       # 200c -> 392f
    assert state['heat_rate'] == pytest.approx(540.0)    # 300 c/hr -> 540 f/hr

    monkeypatch.setattr(config, 'temp_scale', 'c')
    oven2 = Oven()
    oven2.board = FakeBoard(100)
    oven2.target = 200
    oven2.heat_rate = 300
    state2 = oven2.get_state()
    assert state2['temperature'] == 100.0
    assert state2['target'] == 200.0
    assert state2['heat_rate'] == 300.0


def test_get_state_reports_display_pidstats(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    oven = Oven()
    oven.pid.pidstats = {
        'setpoint': 200, 'ispoint': 100, 'err': 100,
        'errDelta': 0.5, 'p': 100, 'i': 50, 'd': 2, 'pid': 0.5, 'out': 0.5,
    }
    ps = oven.get_display_pidstats()
    assert ps['setpoint'] == pytest.approx(392.0)
    assert ps['ispoint'] == pytest.approx(212.0)
    assert ps['err'] == pytest.approx(180.0)
    assert ps['errDelta'] == pytest.approx(0.9)
    assert ps['p'] == pytest.approx(180.0)
    assert ps['i'] == pytest.approx(90.0)
    assert ps['d'] == pytest.approx(3.6)
    assert ps['pid'] == 0.5
    assert ps['out'] == 0.5


def test_emergency_shutoff_compares_config_in_display_scale(no_auto_restarts, monkeypatch):
    # config.emergency_shutoff_temp is in the display scale (f), the
    # sensor reports celsius, so a 1000c oven must trip a 2264f cutoff
    monkeypatch.setattr(config, 'emergency_shutoff_temp', 2264)
    oven = Oven()
    oven.board = FakeBoard(1000)  # 1000c = 1832f, below 2264f
    oven.state = 'RUNNING'
    oven.reset_if_emergency()
    assert oven.state == 'RUNNING'

    oven2 = Oven()
    oven2.board = FakeBoard(1500)  # 1500c = 2732f, above 2264f
    oven2.state = 'RUNNING'
    oven2.reset_if_emergency()
    assert oven2.state == 'IDLE'


def test_get_start_from_temperature_reports_display_scale(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    profile = get_profile()
    # 250c = 482f -> seek forward
    assert Oven.get_start_from_temperature(profile, 250) == 3800
    # 200c = 392f is at the initial profile temp -> start at zero
    assert Oven.get_start_from_temperature(profile, 200) == 0


def test_update_target_temp():
    oven = Oven()
    oven.profile = get_profile()
    oven.runtime = 3000
    oven.update_target_temp()
    assert oven.target == 200


def test_update_cost():
    oven = Oven()
    oven.heat = 1.0
    oven.update_cost()
    assert oven.cost == pytest.approx(config.kwh_rate * config.kw_elements * (1.0 / 3600))
    oven.heat = 0
    oven.update_cost()
    assert oven.cost == pytest.approx(config.kwh_rate * config.kw_elements * (1.0 / 3600))


def test_reset():
    oven = Oven()
    oven.state = 'RUNNING'
    oven.reset()
    assert oven.state == 'IDLE'
    assert oven.cost == 0
    assert oven.target == 0
    assert oven.heat == 0


def test_reset_if_schedule_ended(no_auto_restarts):
    oven = Oven()
    oven.runtime = 20000
    oven.totaltime = 19400
    oven.state = 'RUNNING'
    oven.reset_if_schedule_ended()
    assert oven.state == 'IDLE'


def test_reset_if_schedule_ended_not_ended():
    oven = Oven()
    oven.runtime = 100
    oven.totaltime = 19400
    oven.state = 'RUNNING'
    oven.reset_if_schedule_ended()
    assert oven.state == 'RUNNING'


def test_reset_if_emergency_too_hot(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_shutoff_temp', 2264)
    oven = Oven()
    oven.board = FakeBoard(3000)
    oven.state = 'RUNNING'
    oven.reset_if_emergency()
    assert oven.state == 'IDLE'


def test_reset_if_emergency_ignored_when_told_to(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_shutoff_temp', 2264)
    monkeypatch.setattr(config, 'ignore_temp_too_high', True)
    oven = Oven()
    oven.board = FakeBoard(3000)
    oven.state = 'RUNNING'
    oven.reset_if_emergency()
    assert oven.state == 'RUNNING'


def test_target_is_rising():
    oven = Oven()
    oven.profile = get_profile()
    # 6000s is on the rising 200->2000c segment
    oven.runtime = 6000
    assert oven.target_is_rising() is True
    # 15000s is on the flat 2250c hold
    oven.runtime = 15000
    assert oven.target_is_rising() is False
    # 18000s is on the cooling 2250->700c segment
    oven.runtime = 18000
    assert oven.target_is_rising() is False
    oven.profile = None
    assert oven.target_is_rising() is False


def _seed_heat_rate_window(oven, temp1):
    window = config.emergency_heat_rate_window * 60
    oven.emergency_heat_rate_temps = [(oven.runtime - window, temp1)]


def test_reset_if_emergency_heat_rate_too_low(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_heat_rate', 23)
    monkeypatch.setattr(config, 'emergency_heat_rate_window', 22.5)
    oven = Oven()
    oven.profile = get_profile()
    oven.runtime = 6000  # rising segment
    oven.state = 'RUNNING'
    _seed_heat_rate_window(oven, 0)
    oven.board = FakeBoard(1)  # only 1c rise over the window
    oven.reset_if_emergency()
    assert oven.state == 'IDLE'


def test_reset_if_emergency_heat_rate_fast_enough(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_heat_rate', 23)
    monkeypatch.setattr(config, 'emergency_heat_rate_window', 22.5)
    oven = Oven()
    oven.profile = get_profile()
    oven.runtime = 6000  # rising segment
    oven.state = 'RUNNING'
    _seed_heat_rate_window(oven, 0)
    oven.board = FakeBoard(100)  # 100c rise over the window
    oven.reset_if_emergency()
    assert oven.state == 'RUNNING'


def test_reset_if_emergency_heat_rate_ignored_when_told_to(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_heat_rate', 23)
    monkeypatch.setattr(config, 'emergency_heat_rate_window', 22.5)
    monkeypatch.setattr(config, 'ignore_heat_rate_too_low', True)
    oven = Oven()
    oven.profile = get_profile()
    oven.runtime = 6000
    oven.state = 'RUNNING'
    _seed_heat_rate_window(oven, 0)
    oven.board = FakeBoard(1)
    oven.reset_if_emergency()
    assert oven.state == 'RUNNING'


def test_reset_if_emergency_heat_rate_disabled(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_heat_rate', 0)
    monkeypatch.setattr(config, 'emergency_heat_rate_window', 22.5)
    oven = Oven()
    oven.profile = get_profile()
    oven.runtime = 6000
    oven.state = 'RUNNING'
    _seed_heat_rate_window(oven, 0)
    oven.board = FakeBoard(1)
    oven.reset_if_emergency()
    assert oven.state == 'RUNNING'


def test_reset_if_emergency_heat_rate_needs_full_window(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_heat_rate', 23)
    monkeypatch.setattr(config, 'emergency_heat_rate_window', 22.5)
    oven = Oven()
    oven.profile = get_profile()
    oven.runtime = 6000
    oven.state = 'RUNNING'
    oven.emergency_heat_rate_temps = []
    oven.board = FakeBoard(1)
    oven.reset_if_emergency()
    assert oven.state == 'RUNNING'


def test_reset_if_emergency_heat_rate_skipped_on_flat_segment(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_heat_rate', 23)
    monkeypatch.setattr(config, 'emergency_heat_rate_window', 22.5)
    oven = Oven()
    oven.profile = get_profile()
    oven.runtime = 15000  # flat 2250c hold
    oven.state = 'RUNNING'
    _seed_heat_rate_window(oven, 0)
    oven.board = FakeBoard(1)
    oven.reset_if_emergency()
    assert oven.state == 'RUNNING'


def test_reset_if_emergency_heat_rate_skipped_on_cooling_segment(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_heat_rate', 23)
    monkeypatch.setattr(config, 'emergency_heat_rate_window', 22.5)
    oven = Oven()
    oven.profile = get_profile()
    oven.runtime = 18000  # cooling 2250->700c segment
    oven.state = 'RUNNING'
    _seed_heat_rate_window(oven, 0)
    oven.board = FakeBoard(1)
    oven.reset_if_emergency()
    assert oven.state == 'RUNNING'


def test_kiln_must_catch_up_too_cold(monkeypatch):
    monkeypatch.setattr(config, 'kiln_must_catch_up', True)
    monkeypatch.setattr(config, 'pid_control_window', 5)
    oven = Oven()
    oven.board = FakeBoard(400)
    oven.target = 500
    oven.kiln_must_catch_up()
    assert oven.catching_up is True


def test_kiln_must_catch_up_too_hot(monkeypatch):
    monkeypatch.setattr(config, 'kiln_must_catch_up', True)
    monkeypatch.setattr(config, 'pid_control_window', 5)
    oven = Oven()
    oven.board = FakeBoard(600)
    oven.target = 500
    oven.kiln_must_catch_up()
    assert oven.catching_up is True


def test_kiln_must_catch_up_within_window(monkeypatch):
    monkeypatch.setattr(config, 'kiln_must_catch_up', True)
    monkeypatch.setattr(config, 'pid_control_window', 5)
    oven = Oven()
    oven.board = FakeBoard(501)
    oven.target = 500
    oven.kiln_must_catch_up()
    assert oven.catching_up is False


def test_kiln_must_catch_up_disabled(monkeypatch):
    monkeypatch.setattr(config, 'kiln_must_catch_up', False)
    oven = Oven()
    oven.board = FakeBoard(400)
    oven.target = 500
    oven.kiln_must_catch_up()
    assert oven.catching_up is False


def test_save_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'automatic_restart_state_file',
                        str(tmp_path / 'state.json'))
    oven = Oven()
    oven.state = 'RUNNING'
    oven.cost = 1.25
    oven.save_state()
    with open(tmp_path / 'state.json') as f:
        d = json.load(f)
    assert d['state'] == 'RUNNING'
    assert d['cost'] == 1.25


def test_save_automatic_restart_state_disabled(monkeypatch):
    monkeypatch.setattr(config, 'automatic_restarts', False)
    oven = Oven()
    assert oven.save_automatic_restart_state() is False


def test_save_automatic_restart_state_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'automatic_restarts', True)
    monkeypatch.setattr(config, 'automatic_restart_state_file',
                        str(tmp_path / 'state.json'))
    oven = Oven()
    assert oven.save_automatic_restart_state() is not False
    assert os.path.exists(tmp_path / 'state.json')


def test_state_file_is_old(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'automatic_restart_state_file',
                        str(tmp_path / 'state.json'))
    oven = Oven()
    # missing file counts as old
    assert oven.state_file_is_old() is True

    state_file = tmp_path / 'state.json'
    state_file.write_text(json.dumps({'state': 'RUNNING'}))
    old = datetime.datetime.now().timestamp() - 60 * 60
    os.utime(state_file, (old, old))
    assert oven.state_file_is_old() is True

    fresh = datetime.datetime.now().timestamp()
    os.utime(state_file, (fresh, fresh))
    assert oven.state_file_is_old() is False


def test_should_i_automatic_restart(tmp_path, monkeypatch):
    state_file = tmp_path / 'state.json'
    monkeypatch.setattr(config, 'automatic_restart_state_file', str(state_file))
    monkeypatch.setattr(config, 'automatic_restarts', True)

    oven = Oven()
    # old/missing state file -> no restart
    assert oven.should_i_automatic_restart() is False

    fresh = datetime.datetime.now().timestamp()
    state_file.write_text(json.dumps({'state': 'RUNNING', 'runtime': 60}))
    os.utime(state_file, (fresh, fresh))
    assert oven.should_i_automatic_restart() is True

    state_file.write_text(json.dumps({'state': 'IDLE', 'runtime': 60}))
    os.utime(state_file, (fresh, fresh))
    assert oven.should_i_automatic_restart() is False


def test_automatic_restart(tmp_path, monkeypatch):
    storage = tmp_path / 'storage'
    profiles_dir = storage / 'profiles'
    profiles_dir.mkdir(parents=True)
    with open(profiles_dir / 'test-fast.json', 'w') as f:
        f.write(open(os.path.join(os.path.dirname(__file__), 'test-fast.json')).read())

    state_file = tmp_path / 'state.json'
    state_file.write_text(json.dumps({
        'state': 'RUNNING', 'runtime': 60, 'profile': 'test-fast', 'cost': 3.5
    }))

    monkeypatch.setattr(config, 'automatic_restart_state_file', str(state_file))
    monkeypatch.setattr(oven_module(), '__file__', str(storage / 'oven.py'))
    monkeypatch.setattr(oven_module().time, 'sleep', lambda s: None)

    oven = Oven()
    recorder = types.SimpleNamespace(record=lambda profile: None)
    oven.ovenwatcher = recorder

    calls = {}

    def fake_run_profile(self, profile, startat=0, allow_seek=True):
        calls['profile'] = profile
        calls['startat'] = startat
        calls['allow_seek'] = allow_seek

    monkeypatch.setattr(oven_module().Oven, 'run_profile', fake_run_profile)

    oven.automatic_restart()

    assert calls['startat'] == 1
    assert calls['allow_seek'] is False
    assert calls['profile'].name == 'test-fast'
    assert oven.cost == 3.5


def test_run_unknown_state_does_not_auto_restart(monkeypatch):
    '''the autotuner puts its oven in state TUNING; the background
    run() loop must not check for an automatic restart then.'''
    oven = Oven()
    oven.state = "TUNING"

    restart_checked = []

    def fake_should_restart():
        restart_checked.append(True)
        return True

    def fake_sleep(secs):
        raise StopIteration

    monkeypatch.setattr(oven_module().Oven, 'should_i_automatic_restart',
                        fake_should_restart)
    monkeypatch.setattr(oven_module().time, 'sleep', fake_sleep)

    with pytest.raises(StopIteration):
        oven.run()

    assert restart_checked == []
    assert oven.state == "TUNING"


########################################################################
# Oven.run() loop branches
########################################################################

def test_run_idle_restarts_when_asked(monkeypatch):
    oven = Oven()
    oven.state = "IDLE"
    restart_calls = []
    sleeps = []

    monkeypatch.setattr(oven_module().Oven, 'should_i_automatic_restart', lambda self: True)
    monkeypatch.setattr(oven_module().Oven, 'automatic_restart', lambda self: restart_calls.append(1))

    def fake_sleep(secs):
        sleeps.append(secs)
        if len(sleeps) >= 2:
            raise StopIteration

    monkeypatch.setattr(oven_module().time, 'sleep', fake_sleep)

    with pytest.raises(StopIteration):
        oven.run()

    assert restart_calls == [1, 1]
    assert sleeps == [1, 1]


def test_run_idle_waits_when_no_restart_wanted(monkeypatch):
    oven = Oven()
    oven.state = "IDLE"
    restart_calls = []

    monkeypatch.setattr(oven_module().Oven, 'should_i_automatic_restart', lambda self: False)
    monkeypatch.setattr(oven_module().Oven, 'automatic_restart', lambda self: restart_calls.append(1))

    def fake_sleep(secs):
        raise StopIteration

    monkeypatch.setattr(oven_module().time, 'sleep', fake_sleep)

    with pytest.raises(StopIteration):
        oven.run()

    assert restart_calls == []


def test_run_paused_branch(monkeypatch):
    oven = Oven()
    oven.state = "PAUSED"
    calls = []

    monkeypatch.setattr(oven_module().Oven, 'update_runtime', lambda self: calls.append('runtime'))
    monkeypatch.setattr(oven_module().Oven, 'update_target_temp', lambda self: calls.append('target'))
    monkeypatch.setattr(oven_module().Oven, 'heat_then_cool',
                        lambda self: calls.append('heat'), raising=False)
    monkeypatch.setattr(oven_module().Oven, 'reset_if_emergency', lambda self: calls.append('emergency'))

    def ended(self):
        calls.append('ended')
        if calls.count('ended') >= 2:
            raise StopIteration

    monkeypatch.setattr(oven_module().Oven, 'reset_if_schedule_ended', ended)

    with pytest.raises(StopIteration):
        oven.run()

    assert calls == (['runtime', 'target', 'heat', 'emergency', 'ended'] * 2)


def test_run_running_branch(monkeypatch):
    oven = Oven()
    oven.state = "RUNNING"
    calls = []

    monkeypatch.setattr(oven_module().Oven, 'update_cost', lambda self: calls.append('cost'))
    monkeypatch.setattr(oven_module().Oven, 'save_automatic_restart_state', lambda self: calls.append('save'))
    monkeypatch.setattr(oven_module().Oven, 'kiln_must_catch_up', lambda self: calls.append('catch'))
    monkeypatch.setattr(oven_module().Oven, 'update_runtime', lambda self: calls.append('runtime'))
    monkeypatch.setattr(oven_module().Oven, 'update_target_temp', lambda self: calls.append('target'))
    monkeypatch.setattr(oven_module().Oven, 'heat_then_cool',
                          lambda self: calls.append('heat'), raising=False)
    monkeypatch.setattr(oven_module().Oven, 'reset_if_emergency', lambda self: calls.append('emergency'))

    def ended(self):
        calls.append('ended')
        if calls.count('ended') >= 2:
            raise StopIteration

    monkeypatch.setattr(oven_module().Oven, 'reset_if_schedule_ended', ended)

    with pytest.raises(StopIteration):
        oven.run()

    assert calls == (['cost', 'save', 'catch', 'runtime', 'target', 'heat', 'emergency', 'ended'] * 2)


def oven_module():
    import lib.oven
    return lib.oven


########################################################################
# SimulatedOven
########################################################################

def make_sim():
    sim = SimulatedOven.__new__(SimulatedOven)
    sim.t = 100.0
    sim.t_h = 200.0
    sim.t_env = 65.0
    sim.c_heat = 500.0
    sim.c_oven = 5000.0
    sim.p_heat = 5450.0
    sim.R_o_nocool = 0.5
    sim.R_ho = 0.1
    sim.R_ho_noair = 0.1
    sim.speedup_factor = 1
    sim.time_step = config.sensor_time_wait
    sim.temperature = 100.0
    sim.target = 0
    sim.runtime = 0
    sim.totaltime = 0
    sim.start_time = time.mktime(datetime.datetime(2020, 1, 1).timetuple())
    sim.heat = 0
    sim.cost = 0
    sim.board = types.SimpleNamespace(
        temp_sensor=types.SimpleNamespace(
            temperature=lambda: sim.t,
            simulated_temperature=sim.t,
        )
    )
    sim.pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
    return sim


def test_sim_heating_energy():
    sim = make_sim()
    sim.heating_energy(0.5)
    assert sim.Q_h == pytest.approx(5450 * sim.time_step * 0.5)


def test_sim_temp_changes(monkeypatch):
    sim = make_sim()
    sim.heating_energy(1.0)
    sim.temp_changes()
    assert sim.temperature == sim.t
    assert sim.board.temp_sensor.simulated_temperature == sim.t
    assert sim.p_ho > 0.0     # heat moved into the oven
    assert sim.t_h > 200.0    # heater got hotter
    assert sim.t > 100.0      # oven heated up


def test_sim_heat_then_cool_heating(monkeypatch):
    monkeypatch.setattr(oven_module().time, 'sleep', lambda s: None)
    monkeypatch.setattr(config, 'thermocouple_offset', 0)
    sim = make_sim()
    sim.target = 5000  # far above, max heating
    sim.totaltime = 10000
    sim.heat_then_cool()
    assert sim.heat == pytest.approx(sim.time_step)  # pid output 1.0


def test_sim_heat_then_cool_cooling(monkeypatch):
    monkeypatch.setattr(oven_module().time, 'sleep', lambda s: None)
    monkeypatch.setattr(config, 'thermocouple_offset', 0)
    sim = make_sim()
    sim.target = 0  # far below, no heat
    sim.totaltime = 10000
    sim.heat_then_cool()
    assert sim.heat == 0.0


def test_sim_get_start_time():
    sim = make_sim()
    sim.speedup_factor = 2
    sim.runtime = 100
    start = sim.get_start_time()
    offset = time.time() - start
    assert offset == pytest.approx(50, abs=1)  # 100 sim-seconds at 2x speedup


def test_sim_update_runtime(monkeypatch):
    clock = {'epoch': 1_600_000_000.0}
    monkeypatch.setattr(oven_module().time, 'time', lambda: clock['epoch'])
    sim = make_sim()
    sim.speedup_factor = 1
    sim.start_time = clock['epoch'] - 100  # 100s ago
    sim.update_runtime()
    assert sim.runtime == 100

    sim.speedup_factor = 2
    sim.update_runtime()
    assert sim.runtime == 200


def test_runtime_survives_spring_forward(monkeypatch):
    # the wall clock jumps forward an hour during the firing; the
    # elapsed-time tracking must keep using real time, not local time
    clock = {'epoch': 1_600_000_000.0, 'wall': 0}
    monkeypatch.setattr(oven_module().time, 'time', lambda: clock['epoch'])

    class FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(clock['epoch'] + clock['wall'])

    monkeypatch.setattr(oven_module().datetime, 'datetime', FakeDateTime)
    oven = Oven()
    oven.board = FakeBoard(250)
    oven.run_profile(get_profile(), startat=0, allow_seek=False)
    assert oven.runtime == 0

    clock['epoch'] += 1200
    oven.update_runtime()
    assert oven.runtime == pytest.approx(1200)

    # the DST transition happens here: local time jumps ahead 3600s while
    # only 1200 more real seconds passed
    clock['epoch'] += 1200
    clock['wall'] += 3600
    oven.update_runtime()
    assert oven.runtime == pytest.approx(2400)


def test_runtime_survives_fall_back(monkeypatch):
    # the wall clock jumps back an hour during the firing; runtime must
    # not be clamped to zero as it would if it tracked local time
    clock = {'epoch': 1_600_000_000.0, 'wall': 0}
    monkeypatch.setattr(oven_module().time, 'time', lambda: clock['epoch'])

    class FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(clock['epoch'] + clock['wall'])

    monkeypatch.setattr(oven_module().datetime, 'datetime', FakeDateTime)
    oven = Oven()
    oven.board = FakeBoard(250)
    oven.run_profile(get_profile(), startat=0, allow_seek=False)
    assert oven.runtime == 0

    clock['epoch'] += 1200
    oven.update_runtime()
    assert oven.runtime == pytest.approx(1200)

    # the DST transition happens here: local time falls back 3600s while
    # only 1200 more real seconds passed
    clock['epoch'] += 1200
    clock['wall'] -= 3600
    oven.update_runtime()
    assert oven.runtime == pytest.approx(2400)


def test_sim_runtime_survives_dst(monkeypatch):
    # the simulated oven's runtime is sped-up time but is still anchored
    # to the real clock, so a DST transition cannot corrupt it
    clock = {'epoch': 1_600_000_000.0}
    monkeypatch.setattr(oven_module().time, 'time', lambda: clock['epoch'])
    sim = make_sim()
    sim.speedup_factor = 2
    sim.start_time = clock['epoch']
    clock['epoch'] += 600
    sim.update_runtime()
    assert sim.runtime == pytest.approx(1200)
    # fall-back: local time goes back an hour, real time keeps going
    clock['epoch'] += 600
    sim.update_runtime()
    assert sim.runtime == pytest.approx(2400)


########################################################################
# TempTracker / ThermocoupleTracker
########################################################################

def test_temp_tracker_window():
    tracker = TempTracker()
    assert len(tracker.temps) == config.temperature_average_samples
    for i in range(20):
        tracker.add(1)
    assert len(tracker.temps) == config.temperature_average_samples
    assert tracker.get_avg_temp() == 1


def test_temp_tracker_median():
    tracker = TempTracker()
    tracker.add(10)
    tracker.add(20)
    tracker.add(30)
    tracker.add(1000)  # outlier, median ignores it
    temps = sorted(tracker.temps)
    assert tracker.get_avg_temp() == temps[len(temps) // 2]


def test_thermocouple_tracker_error_percent():
    tracker = ThermocoupleTracker()
    for _ in range(7):
        tracker.bad()
    assert tracker.error_percent() == pytest.approx((7 / tracker.size) * 100)
    assert tracker.over_error_limit() is True


def test_thermocouple_tracker_under_limit():
    tracker = ThermocoupleTracker()
    for _ in range(6):
        tracker.bad()
    assert tracker.over_error_limit() is False


def test_thermocouple_tracker_good_resets():
    tracker = ThermocoupleTracker()
    for _ in range(tracker.size):
        tracker.bad()
    for _ in range(tracker.size):
        tracker.good()
    assert tracker.error_percent() == 0


def test_thermocouple_tracker_duty_cycle_errors_counts_current_cycle():
    # window spans two duty cycles; only the newest half counts
    tracker = ThermocoupleTracker()
    half = int(tracker.size / 2)
    for _ in range(tracker.size):
        tracker.bad()
    for _ in range(half - 3):               # most of the current cycle recovers
        tracker.good()
    assert tracker.duty_cycle_errors() == 3


def test_thermocouple_tracker_duty_cycle_errors_zero_when_all_good():
    tracker = ThermocoupleTracker()
    for _ in range(tracker.size):
        tracker.good()
    assert tracker.duty_cycle_errors() == 0


########################################################################
# TempSensorReal.get_temperature (always returns celsius internally)
########################################################################

class StubTempStatus:
    def __init__(self):
        self.good_calls = 0
        self.bad_calls = 0

    def good(self):
        self.good_calls += 1

    def bad(self):
        self.bad_calls += 1


def make_sensor(value=25.0, error=None):
    '''TempSensorReal without __init__, which would touch real hardware.'''
    sensor = TempSensorReal.__new__(TempSensorReal)
    sensor.status = StubTempStatus()

    def raw_temp():
        if error is not None:
            raise error
        return value

    sensor.raw_temp = raw_temp
    return sensor


def test_get_temperature_returns_celsius_unaffected_by_scale(monkeypatch):
    # the sensor always reports celsius; the display-scale conversion
    # happens at the api boundaries, not at the sensor
    monkeypatch.setattr(config, 'temp_scale', 'c')
    sensor = make_sensor(25.0)
    assert sensor.get_temperature() == 25.0
    assert sensor.status.good_calls == 1
    assert sensor.status.bad_calls == 0

    monkeypatch.setattr(config, 'temp_scale', 'f')
    sensor = make_sensor(25.0)
    assert sensor.get_temperature() == 25.0
    assert sensor.status.good_calls == 1

    # -40 F == -40 C, so both scales read the same value
    monkeypatch.setattr(config, 'temp_scale', 'c')
    c = make_sensor(-40.0)
    monkeypatch.setattr(config, 'temp_scale', 'f')
    f = make_sensor(-40.0)
    assert c.get_temperature() == f.get_temperature() == -40.0


def test_get_temperature_fahrenheit_boiling_and_freezing(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    assert make_sensor(100.0).get_temperature() == 100.0
    assert make_sensor(0.0).get_temperature() == 0.0


def test_get_temperature_scale_case_insensitive(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'F')
    sensor = make_sensor(0.0)
    assert sensor.get_temperature() == 0.0


def test_get_temperature_error_ignored_marks_good(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    monkeypatch.setattr(config, 'ignore_tc_lost_connection', True)
    sensor = make_sensor(error=Max31855_Error('thermocouple not connected'))
    assert sensor.get_temperature() is None
    assert sensor.status.good_calls == 1
    assert sensor.status.bad_calls == 0


def test_get_temperature_error_marks_bad(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'c')
    monkeypatch.setattr(config, 'ignore_tc_lost_connection', False)
    sensor = make_sensor(error=Max31855_Error('thermocouple not connected'))
    assert sensor.get_temperature() is None
    assert sensor.status.good_calls == 0
    assert sensor.status.bad_calls == 1


########################################################################
# Thermocouple errors
########################################################################

def test_max31855_error_mapping():
    err = Max31855_Error('thermocouple not connected')
    assert err.message == 'not connected'
    assert err.ignore is False
    err = Max31855_Error('random nonsense')
    assert err.message == 'unknown'


def test_max31856_error_mapping():
    err = Max31856_Error('tc_range')
    assert err.message == 'thermocouple range fault'
    err = Max31856_Error('open_tc')
    assert err.message == 'not connected'
    err = Max31856_Error('voltage')
    assert err.message == 'voltage too high or low'


def test_thermocouple_error_ignore(monkeypatch):
    monkeypatch.setattr(config, 'ignore_tc_lost_connection', True)
    err = Max31855_Error('thermocouple not connected')
    assert err.ignore is True

    monkeypatch.setattr(config, 'ignore_tc_lost_connection', False)
    err = Max31855_Error('thermocouple not connected')
    assert err.ignore is False


########################################################################
# DupFilter / Duplogger
########################################################################

def test_dup_filter_deduplicates():
    f = DupFilter()
    assert f.filter(types.SimpleNamespace(msg='hello')) is True
    assert f.filter(types.SimpleNamespace(msg='hello')) is False
    assert f.filter(types.SimpleNamespace(msg='world')) is True


def test_duplogger_returns_logger():
    logger = Duplogger().logref()
    assert logger.name.endswith('.dupfree')


def test_simulated_oven_constructor(monkeypatch):
    started = []

    def fake_start(self):
        started.append(True)

    monkeypatch.setattr(oven_module().Oven, 'start', fake_start)

    sim = SimulatedOven()

    assert sim.board is not None
    assert sim.state == 'IDLE'
    assert sim.target == 0
    assert sim.t_env == pytest.approx(to_c(config.sim_t_env))
    assert sim.speedup_factor == config.sim_speedup_factor
    assert sim.run_sequence == 0
    assert started == [True]


########################################################################
# small gap fillers
########################################################################

def test_reset_if_emergency_too_many_errors(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_heat_rate', 0)
    monkeypatch.setattr(config, 'ignore_tc_too_many_errors', False)
    oven = Oven()
    oven.state = 'RUNNING'
    status = types.SimpleNamespace(over_error_limit=lambda: True)
    oven.board = types.SimpleNamespace(
        temp_sensor=types.SimpleNamespace(temperature=lambda: 100, status=status))
    oven.reset_if_emergency()
    assert oven.state == 'IDLE'


def test_update_runtime_clamps_negative_start(monkeypatch):
    oven = Oven()
    oven.start_time = time.time() + 300
    oven.update_runtime()
    assert oven.runtime == 0


def test_should_i_automatic_restart_disabled(monkeypatch):
    monkeypatch.setattr(config, 'automatic_restarts', False)
    oven = Oven()
    assert oven.should_i_automatic_restart() is False


def test_set_ovenwatcher(monkeypatch):
    oven = Oven()
    watcher = types.SimpleNamespace()
    oven.set_ovenwatcher(watcher)
    assert oven.ovenwatcher is watcher


def test_sim_update_runtime_clamps_negative_start(monkeypatch):
    monkeypatch.setattr(oven_module().Oven, 'start', lambda self: None)
    sim = SimulatedOven()
    sim.start_time = time.time() + 300
    sim.update_runtime()
    assert sim.runtime == 0


def test_sim_update_target_temp(monkeypatch):
    monkeypatch.setattr(oven_module().Oven, 'start', lambda self: None)
    sim = SimulatedOven()
    sim.profile = get_profile()
    sim.runtime = 60
    sim.update_target_temp()
    assert sim.target == sim.profile.get_target_temperature(60)


def test_sim_heat_then_cool_missing_pidstats(monkeypatch):
    sim = make_sim()
    sim.pid.pidstats = {}
    monkeypatch.setattr(oven_module().time, 'sleep', lambda secs: None)
    sim.heat_then_cool()


def test_thermocouple_error_ignore_all_flags(monkeypatch):
    monkeypatch.setattr(config, 'ignore_tc_lost_connection', True)
    monkeypatch.setattr(config, 'ignore_tc_short_errors', True)
    monkeypatch.setattr(config, 'ignore_tc_unknown_error', True)
    monkeypatch.setattr(config, 'ignore_tc_cold_junction_range_error', True)
    monkeypatch.setattr(config, 'ignore_tc_range_error', True)
    monkeypatch.setattr(config, 'ignore_tc_cold_junction_temp_high', True)
    monkeypatch.setattr(config, 'ignore_tc_cold_junction_temp_low', True)
    monkeypatch.setattr(config, 'ignore_tc_temp_high', True)
    monkeypatch.setattr(config, 'ignore_tc_temp_low', True)
    monkeypatch.setattr(config, 'ignore_tc_voltage_error', True)

    cases = [
        (Max31855_Error('thermocouple not connected'), 'not connected'),
        (Max31855_Error('short circuit to ground'), 'short circuit'),
        (Max31855_Error('random nonsense'), 'unknown'),
        (Max31856_Error('cj_range'), 'cold junction range fault'),
        (Max31856_Error('tc_range'), 'thermocouple range fault'),
        (Max31856_Error('cj_high'), 'cold junction temp too high'),
        (Max31856_Error('cj_low'), 'cold junction temp too low'),
        (Max31856_Error('tc_high'), 'thermocouple temp too high'),
        (Max31856_Error('tc_low'), 'thermocouple temp too low'),
        (Max31856_Error('voltage'), 'voltage too high or low'),
    ]
    for err, expected in cases:
        assert err.ignore is True, expected
        assert err.message == expected


def test_reset_if_emergency_heat_rate_waiting_for_full_window(no_auto_restarts, monkeypatch):
    monkeypatch.setattr(config, 'emergency_heat_rate', 23)
    monkeypatch.setattr(config, 'emergency_heat_rate_window', 22.5)
    oven = Oven()
    oven.profile = get_profile()
    oven.runtime = 6000  # rising segment
    oven.state = 'RUNNING'
    # one recent sample: window not yet full, so the rate is not trusted
    oven.emergency_heat_rate_temps = [(oven.runtime - 60, 0)]
    oven.board = FakeBoard(100)
    oven.reset_if_emergency()
    assert oven.state == 'RUNNING'
    assert len(oven.emergency_heat_rate_temps) == 2


########################################################################
# hardware classes (blinka deps faked)
########################################################################

class FakeDigitalInOut:
    def __init__(self, pin):
        self.pin = pin
        self.direction = None
        self.value = None


def _patch_hardware_deps(monkeypatch):
    monkeypatch.setattr(oven_module(), 'digitalio',
                        types.SimpleNamespace(
                            DigitalInOut=FakeDigitalInOut,
                            Direction=types.SimpleNamespace(OUTPUT=1)))
    monkeypatch.setattr(oven_module(), 'bitbangio',
                        types.SimpleNamespace(SPI=lambda *a, **k: 'spi-bus'))
    monkeypatch.setattr(config, 'gpio_heat', 23, raising=False)
    monkeypatch.setattr(config, 'gpio_heat_invert', False, raising=False)
    monkeypatch.setattr(config, 'spi_sclk', 1, raising=False)
    monkeypatch.setattr(config, 'spi_mosi', 2, raising=False)
    monkeypatch.setattr(config, 'spi_miso', 3, raising=False)
    monkeypatch.setattr(config, 'spi_cs', 4, raising=False)
    monkeypatch.setattr(config, 'sensor_time_wait', 2, raising=False)
    monkeypatch.setattr(config, 'temperature_average_samples', 5, raising=False)


def test_output_heater_cycles(monkeypatch):
    _patch_hardware_deps(monkeypatch)
    out = oven_module().Output()
    assert out.on is True
    assert out.off is False
    assert out.heater.direction == 1
    out.heat(0)
    assert out.heater.value is True
    out.cool(0)
    assert out.heater.value is False


def test_temp_sensor_real_init_and_run(monkeypatch):
    _patch_hardware_deps(monkeypatch)
    sensor = oven_module().TempSensorReal()
    assert sensor.sleeptime == 0.4
    assert sensor.spi == 'spi-bus'
    assert isinstance(sensor.cs, FakeDigitalInOut)
    assert sensor.temperature() == 0  # empty tracker medians to 0

    monkeypatch.setattr(sensor, 'get_temperature', lambda: 120.0)
    sleeps = [0]

    def fake_sleep(secs):
        sleeps[0] += 1
        if sleeps[0] >= 3:
            raise StopIteration

    monkeypatch.setattr(oven_module().time, 'sleep', fake_sleep)

    with pytest.raises(StopIteration):
        sensor.run()
    assert sensor.temptracker.get_avg_temp() == 120.0


def test_max31855_sensor(monkeypatch):
    _patch_hardware_deps(monkeypatch)

    class GoodTC:
        temperature_NIST = 25.0

        def __init__(self, spi, cs):
            pass

    monkeypatch.setitem(sys.modules, 'adafruit_max31855',
                        types.SimpleNamespace(MAX31855=GoodTC))
    sensor = oven_module().Max31855()
    assert sensor.raw_temp() == 25.0

    class ErrTC:
        def __init__(self, spi, cs):
            pass

        @property
        def temperature_NIST(self):
            raise RuntimeError('fault reading')

    monkeypatch.setitem(sys.modules, 'adafruit_max31855',
                        types.SimpleNamespace(MAX31855=ErrTC))
    sensor2 = oven_module().Max31855()
    with pytest.raises(Max31855_Error) as exc:
        sensor2.raw_temp()
    assert exc.value.message == 'unknown'

    class EmptyErrTC:
        def __init__(self, spi, cs):
            pass

        @property
        def temperature_NIST(self):
            raise RuntimeError()

    monkeypatch.setitem(sys.modules, 'adafruit_max31855',
                        types.SimpleNamespace(MAX31855=EmptyErrTC))
    sensor3 = oven_module().Max31855()
    with pytest.raises(Max31855_Error) as exc:
        sensor3.raw_temp()
    assert exc.value.message == 'unknown'


def test_max31856_sensor(monkeypatch):
    _patch_hardware_deps(monkeypatch)
    monkeypatch.setattr(config, 'thermocouple_type', 'K')
    monkeypatch.setattr(config, 'ac_freq_50hz', True)

    class FakeTC:
        temperature = 120.0
        fault = {}
        noise_rejection = None

        def __init__(self, spi, cs, thermocouple_type=None):
            pass

    monkeypatch.setitem(sys.modules, 'adafruit_max31856',
                        types.SimpleNamespace(MAX31856=FakeTC,
                                              ThermocoupleType=types.SimpleNamespace(K='K')))
    sensor = oven_module().Max31856()
    assert sensor.thermocouple.noise_rejection == 50
    assert sensor.raw_temp() == 120.0

    monkeypatch.setattr(config, 'ac_freq_50hz', False)
    sensor2 = oven_module().Max31856()
    assert sensor2.thermocouple.noise_rejection == 60
    sensor2.thermocouple.fault = {'cj_range': True, 'voltage': False}
    with pytest.raises(Max31856_Error) as exc:
        sensor2.raw_temp()
    assert exc.value.message == 'cold junction range fault'


def test_real_board_choose_tempsensor(monkeypatch):
    _patch_hardware_deps(monkeypatch)

    class FakeSensor:
        def __init__(self):
            self.started = False

        def start(self):
            self.started = True

    fake_sensor = FakeSensor()
    monkeypatch.setattr(oven_module(), 'Max31855', lambda: fake_sensor)
    monkeypatch.setitem(sys.modules, 'board',
                        types.SimpleNamespace(board_id='TEST_BOARD'))

    board = oven_module().RealBoard()
    assert board.name == 'TEST_BOARD'
    assert board.temp_sensor is fake_sensor
    assert fake_sensor.started is True

    class FakeSensor2:
        def start(self):
            pass

    fake2 = FakeSensor2()
    monkeypatch.setattr(config, 'max31855', 0)
    monkeypatch.setattr(config, 'max31856', 1)
    monkeypatch.setattr(oven_module(), 'Max31856', lambda: fake2)
    board2 = oven_module().RealBoard()
    assert board2.temp_sensor is fake2


def test_real_oven(monkeypatch):
    _patch_hardware_deps(monkeypatch)

    class FakeSensor:
        def start(self):
            pass

        def temperature(self):
            return 100.0

    monkeypatch.setattr(oven_module(), 'Max31855', lambda: FakeSensor())
    monkeypatch.setitem(sys.modules, 'board',
                        types.SimpleNamespace(board_id='TEST_BOARD'))
    monkeypatch.setattr(oven_module().Oven, 'start', lambda self: None)

    oven = oven_module().RealOven()
    assert oven.state == 'IDLE'
    assert oven.output is not None
    assert oven.board.name == 'TEST_BOARD'

    heat_calls = []
    cool_calls = []
    monkeypatch.setattr(oven.output, 'heat', lambda s: heat_calls.append(s))
    monkeypatch.setattr(oven.output, 'cool', lambda s: cool_calls.append(s))
    monkeypatch.setattr(oven, 'pid', types.SimpleNamespace(
        compute=lambda setpoint, ispoint, now: 0.4,
        pidstats={'ispoint': 100, 'setpoint': 200, 'err': -100, 'errDelta': 0,
                  'p': 0, 'i': 0, 'd': 0, 'pid': 0, 'out': 0.4}))
    monkeypatch.setattr(oven, 'runtime', 10)
    monkeypatch.setattr(oven, 'totaltime', 100)
    monkeypatch.setattr(oven, 'time_step', 2)

    oven.heat_then_cool()
    assert oven.heat == 1.0
    assert heat_calls == [0.8]
    assert cool_calls == [1.2]


def test_temp_sensor_simulated_temperature(monkeypatch):
    monkeypatch.setattr(config, 'sim_t_env', 77)
    sensor = oven_module().TempSensorSimulated()
    assert sensor.temperature() == to_c(77)


def test_temp_sensor_real_hardware_spi(monkeypatch):
    _patch_hardware_deps(monkeypatch)
    for attr in ('spi_sclk', 'spi_mosi', 'spi_miso'):
        monkeypatch.delattr(config, attr, raising=False)
    monkeypatch.setitem(sys.modules, 'board',
                        types.SimpleNamespace(SPI=lambda: 'hw-spi'))
    sensor = oven_module().TempSensorReal()
    assert sensor.spi == 'hw-spi'
