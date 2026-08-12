import importlib.util
import os
import re

import pytest


def load_tuner():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'kiln-tuner.py'))
    spec = importlib.util.spec_from_file_location('kiln_tuner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tuner = load_tuner()


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
