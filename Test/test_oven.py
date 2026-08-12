import datetime
import json
import os
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
    def over_error_limit(self):
        return False


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
    offset = (datetime.datetime.now() - oven.start_time).total_seconds()
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
    offset = (datetime.datetime.now() - oven.start_time).total_seconds()
    assert offset == pytest.approx(600, abs=2)
    oven.update_runtime()
    assert oven.runtime == pytest.approx(600, abs=2)
    oven.update_target_temp()
    assert oven.target == pytest.approx(200.0)


def test_get_state():
    oven = Oven()
    state = oven.get_state()
    assert state['state'] == 'IDLE'
    assert state['profile'] is None
    assert state['pidstats'] == {}
    for key in ('cost', 'runtime', 'temperature', 'target', 'heat',
                'heat_rate', 'totaltime', 'kwh_rate', 'currency_type',
                'profile', 'pidstats', 'catching_up'):
        assert key in state


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
    sim.start_time = datetime.datetime(2020, 1, 1)
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
    offset = (datetime.datetime.now() - start).total_seconds()
    assert offset == pytest.approx(50, abs=1)  # 100 sim-seconds at 2x speedup


def test_sim_update_runtime(monkeypatch):
    class FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime(2020, 1, 1, 0, 0, 0)

    monkeypatch.setattr(oven_module().datetime, 'datetime', FakeDateTime)
    sim = make_sim()
    sim.speedup_factor = 1
    sim.start_time = datetime.datetime(2019, 12, 31, 23, 58, 20)  # 100s ago
    sim.update_runtime()
    assert sim.runtime == 100

    sim.speedup_factor = 2
    sim.update_runtime()
    assert sim.runtime == 200


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
