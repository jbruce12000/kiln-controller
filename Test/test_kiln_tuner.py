import importlib
import importlib.util
import os
import re
import sys
import types

import pytest

import config


def load_tuner():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'kiln-tuner.py'))
    spec = importlib.util.spec_from_file_location('kiln_tuner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tuner = load_tuner()


class FakeClock:
    '''deterministic clock for recordprofile(): the fake ovens do not
    sleep, so with the real clock every sample lands microseconds apart
    and the tangent fit can degenerate (negative L) depending on timer
    jitter and machine load. Evenly spaced stamps give the recorded
    curve a meaningful time axis.'''
    def __init__(self, start=1000000.0, step=1.0):
        self.now = start
        self.step = step

    def time(self):
        now = self.now
        self.now += self.step
        return now


def fake_clock(monkeypatch):
    '''replace the time module kiln-tuner.py stamps rows with; it only
    ever calls time.time()'''
    clock = FakeClock()
    monkeypatch.setattr(tuner, 'time', types.SimpleNamespace(time=clock.time))
    return clock


def write_curve(tmp_path, filename="tuning.csv", with_cooling=True):
    '''two-segment heating curve:
       t 0..60:  temp = 5*t      (0..300)
       t 61..100: temp = 300 + 20*(t-60)  (320..1100)
    '''
    path = tmp_path / filename
    start = 1000000.0
    with open(path, 'w') as f:
        f.write('time,temperature\n')
        for t in range(0, 61):
            f.write('%f,%f\n' % (start + t, 5 * t))
        for t in range(61, 101):
            f.write('%f,%f\n' % (start + t, 300 + 20 * (t - 60)))
        if with_cooling:
            for i, temp in enumerate((900, 700, 500)):
                f.write('%f,%f\n' % (start + 101 + i, temp))
    return path


def parse_output(out):
    def grab(name):
        m = re.search(r'^\s*pid_%s\s*=\s*([-\d.]+)' % name, out, re.MULTILINE)
        assert m, "could not find pid_%s in output:\n%s" % (name, out)
        return float(m.group(1))
    return grab('kp'), grab('ki'), grab('kd')


def test_default_method_is_critically_damped():
    assert tuner.DEFAULT_METHOD == 'critically_damped'


def test_zn_tables():
    cd = tuner.ZN_TABLES['critically_damped']
    assert cd['factor'] == 0.6
    assert cd['ti'] == 4.0
    assert cd['td'] == 1.0

    qd = tuner.ZN_TABLES['quarter_decay']
    assert qd['factor'] == 1.2
    assert qd['ti'] == 2.0
    assert qd['td'] == 0.5


def test_line():
    assert tuner.line(2, 3, 4) == 11
    assert tuner.line(0, 5, 100) == 5


def test_invline():
    assert tuner.invline(2, 3, 11) == 4
    assert tuner.invline(1, 0, 7) == 7


def test_calculate_critically_damped(tmp_path, capsys):
    csvfile = write_curve(tmp_path)
    tuner.calculate(str(csvfile))
    out = capsys.readouterr().out
    kp, ki, kd = parse_output(out)

    # L = 45, T = 55 for this curve. output is rounded to 3 decimals.
    assert kp == pytest.approx(0.6 * 55 / 45, abs=0.001)
    assert ki == pytest.approx((4 * 45) / (0.6 * 55 / 45), abs=0.001)
    assert kd == pytest.approx((0.6 * 55 / 45) * 45, abs=0.001)
    assert "critically_damped" in out


def test_calculate_quarter_decay(tmp_path, capsys):
    csvfile = write_curve(tmp_path)
    tuner.calculate(str(csvfile), method='quarter_decay')
    out = capsys.readouterr().out
    kp, ki, kd = parse_output(out)

    assert kp == pytest.approx(1.2 * 55 / 45, abs=0.001)
    assert ki == pytest.approx((2 * 45) / (1.2 * 55 / 45), abs=0.001)
    assert kd == pytest.approx((1.2 * 55 / 45) * 0.5 * 45, abs=0.001)


def test_calculate_some_overshoot(tmp_path, capsys):
    csvfile = write_curve(tmp_path)
    tuner.calculate(str(csvfile), method='some_overshoot')
    out = capsys.readouterr().out
    kp, _, _ = parse_output(out)
    assert kp == pytest.approx(1.0 * 55 / 45, abs=0.001)


def test_calculate_ignores_cooling_portion(tmp_path, capsys):
    # with or without the cooling tail the result must be identical
    csv_with = write_curve(tmp_path, with_cooling=True)
    csv_without = write_curve(tmp_path, "tuning2.csv", with_cooling=False)

    tuner.calculate(str(csv_with))
    kp1, ki1, kd1 = parse_output(capsys.readouterr().out)
    tuner.calculate(str(csv_without))
    kp2, ki2, kd2 = parse_output(capsys.readouterr().out)

    assert (kp1, ki1, kd1) == (kp2, ki2, kd2)


def test_calculate_bad_tangent_divisor(tmp_path):
    csvfile = write_curve(tmp_path)
    with pytest.raises(ValueError):
        tuner.calculate(str(csvfile), tangentdivisor=1)


def test_calculate_unknown_method(tmp_path):
    csvfile = write_curve(tmp_path)
    with pytest.raises(ValueError):
        tuner.calculate(str(csvfile), method='bogus')


def test_calculate_flat_curve_raises(tmp_path):
    csvfile = tmp_path / 'flat.csv'
    with open(csvfile, 'w') as f:
        f.write('time,temperature\n')
        for i in range(100):
            f.write('%f,%f\n' % (1000000.0 + i, 500.0))
    with pytest.raises(ValueError):
        tuner.calculate(str(csvfile))


def test_calculate_no_data_raises(tmp_path):
    csvfile = tmp_path / 'empty.csv'
    csvfile.write_text('time,temperature\n')
    with pytest.raises(ValueError):
        tuner.calculate(str(csvfile))


def test_find_tangent_known_curve():
    xdata = list(range(0, 61)) + list(range(61, 101))
    ydata = [5 * t for t in range(0, 61)] + [300 + 20 * (t - 60) for t in range(61, 101)]
    L, T, tmin, tmax, slope, offset, lo, hi = tuner.find_tangent(xdata, ydata, 8)
    assert tmin == (66, 420)
    assert tmax == (80, 700)
    assert slope == 20
    assert L == 45
    assert T == 55


########################################################################
# find_tangent error paths
########################################################################

def test_find_tangent_not_enough_points_raises():
    # curve never reaches the upper tangent threshold
    with pytest.raises(ValueError):
        tuner.find_tangent([0, 1, 2, 3], [0, 0, 0, 50], 8)


def test_find_tangent_flat_mid_raises():
    # two distinct tangent points with identical temperature -> slope 0
    with pytest.raises(ValueError):
        tuner.find_tangent([0, 1, 2], [70, 70, 20], 8)


def test_find_tangent_bad_process_params_raises():
    # tangent crosses the starting temperature before the first sample
    with pytest.raises(ValueError):
        tuner.find_tangent([0, 1, 2, 3, 4], [50, 100, 60, 30, 10], 8)


########################################################################
# calculate edge cases
########################################################################

def test_calculate_ignores_bad_rows(tmp_path, capsys):
    csvfile = tmp_path / 'messy.csv'
    with open(csvfile, 'w') as f:
        f.write('time,temperature\n')
        f.write('not-a-time,hello\n')
        f.write('%f,%f\n' % (1000000.0, 0.0))
        for t in range(0, 61):
            f.write('%f,%f\n' % (1000000.0 + t, 5 * t))
        for t in range(61, 101):
            f.write('%f,%f\n' % (1000000.0 + t, 300 + 20 * (t - 60)))
    tuner.calculate(str(csvfile))
    kp, ki, kd = parse_output(capsys.readouterr().out)
    assert kp == pytest.approx(0.6 * 55 / 45, abs=0.001)


def test_calculate_showplot(tmp_path, capsys, monkeypatch):
    calls = []
    fake = types.SimpleNamespace(
        scatter=lambda *a, **k: calls.append('scatter'),
        plot=lambda *a, **k: calls.append('plot'),
        show=lambda: calls.append('show'),
    )
    monkeypatch.setitem(sys.modules, 'matplotlib',
                        types.SimpleNamespace(pyplot=fake))

    csvfile = write_curve(tmp_path)
    tuner.calculate(str(csvfile), showplot=True)

    assert 'scatter' in calls
    assert 'plot' in calls
    assert 'show' in calls
    kp, _, _ = parse_output(capsys.readouterr().out)
    assert kp == pytest.approx(0.6 * 55 / 45, abs=0.001)


########################################################################
# recordprofile
########################################################################

def make_sim_oven():
    '''a simulated oven that produces a realistic S-shaped heating
    curve: the element heats up quickly but the oven lags behind it,
    so the recorded curve starts slow and then ramps up.'''
    instances = []

    class FakeSimOven:
        def __init__(self):
            instances.append(self)
            self.target = 0
            self.temp = 20.0
            self.t_h = 20.0
            self.state = None

        def heat_then_cool(self):
            if self.target:
                self.t_h += 40.0
                self.temp += 0.3 * (self.t_h - self.temp)
            else:
                self.temp -= 15.0

        @property
        def board(self):
            return types.SimpleNamespace(
                temp_sensor=types.SimpleNamespace(temperature=lambda: self.temp))

    return FakeSimOven, instances


def test_recordprofile_simulated(tmp_path, monkeypatch, capsys):
    import csv as csvmod
    oven_mod = importlib.import_module('oven')

    FakeSimOven, instances = make_sim_oven()
    monkeypatch.setattr(config, 'simulate', True)
    monkeypatch.setattr(config, 'automatic_restarts', True)
    monkeypatch.setattr(oven_mod, 'SimulatedOven', FakeSimOven)
    fake_clock(monkeypatch)

    csvfile = tmp_path / 'recorded.csv'
    tuner.recordprofile(str(csvfile), 100.0)

    # the tuner turns off automatic restarts while driving the oven
    assert config.automatic_restarts is False
    assert len(instances) == 1
    assert instances[0].state == 'TUNING'

    rows = list(csvmod.DictReader(open(csvfile)))
    assert len(rows) >= 3
    temps = [float(r['temperature']) for r in rows]
    # the first sample is taken after one heat step, so it is already
    # above ambient
    assert temps[0] > tuner.to_display(20.0)
    assert temps[-1] == pytest.approx(tuner.to_display(instances[0].temp))


def test_recordprofile_real_oven_always_cools_down(tmp_path, monkeypatch, capsys):
    import csv as csvmod
    oven_mod = importlib.import_module('oven')

    instances = []

    class FakeRealOven:
        def __init__(self):
            instances.append(self)
            self.target = 0
            self.temp = 20.0
            self.t_h = 20.0
            self.state = None
            self.cool_calls = []
            self.output = types.SimpleNamespace(
                heat=self.heat,
                cool=self.cool,
            )

        def heat(self, secs):
            self.t_h += 40.0
            self.temp += 0.3 * (self.t_h - self.temp)

        def cool(self, secs):
            self.cool_calls.append(secs)
            self.temp -= 15.0

        @property
        def board(self):
            return types.SimpleNamespace(
                temp_sensor=types.SimpleNamespace(temperature=lambda: self.temp))

    monkeypatch.setattr(config, 'simulate', False)
    monkeypatch.setattr(config, 'automatic_restarts', True)
    monkeypatch.setattr(oven_mod, 'RealOven', FakeRealOven)
    fake_clock(monkeypatch)

    csvfile = tmp_path / 'recorded-real.csv'
    tuner.recordprofile(str(csvfile), 100.0)

    assert len(instances) == 1
    # the finally block always shuts the kiln down, even after cooling
    assert instances[0].cool_calls and instances[0].cool_calls[-1] == 0

    rows = list(csvmod.DictReader(open(csvfile)))
    assert len(rows) >= 3


########################################################################
# main / cli
########################################################################

def test_main_calculate_only(tmp_path, capsys, monkeypatch):
    csvfile = write_curve(tmp_path)
    monkeypatch.setattr(sys, 'argv',
                        ['kiln-tuner.py', '--calculate_only', '--csvfile', str(csvfile)])
    tuner.main()
    kp, ki, kd = parse_output(capsys.readouterr().out)
    assert kp == pytest.approx(0.6 * 55 / 45, abs=0.001)


def test_main_records_then_calculates(tmp_path, capsys, monkeypatch):
    oven_mod = importlib.import_module('oven')

    FakeSimOven, instances = make_sim_oven()
    monkeypatch.setattr(config, 'simulate', True)
    monkeypatch.setattr(config, 'automatic_restarts', True)
    monkeypatch.setattr(oven_mod, 'SimulatedOven', FakeSimOven)
    fake_clock(monkeypatch)
    monkeypatch.setattr(sys, 'argv',
                        ['kiln-tuner.py', '--target_temp', '300', '--csvfile', str(tmp_path / 'tuning.csv')])

    tuner.main()

    out = capsys.readouterr().out
    assert 'stage = heating' in out
    assert 'stage = cooling' in out
    kp, ki, kd = parse_output(out)
    assert kp > 0
    assert (tmp_path / 'tuning.csv').exists()


def test_missing_config_exits(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == 'config':
            raise ImportError('blocked')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', blocked)

    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'kiln-tuner.py'))
    spec = importlib.util.spec_from_file_location('kiln_tuner_missing_config', path)
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(SystemExit):
        spec.loader.exec_module(module)
