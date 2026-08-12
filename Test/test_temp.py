import pytest

from lib.temp import (
    c_to_f,
    delta_to_c,
    delta_to_display,
    display_pidstats,
    display_profile_data,
    f_to_c,
    to_c,
    to_display,
)
import config


def test_c_to_f():
    assert c_to_f(0) == 32.0
    assert c_to_f(100) == 212.0
    assert c_to_f(-40) == -40.0


def test_f_to_c():
    assert f_to_c(32) == 0.0
    assert f_to_c(212) == 100.0
    assert f_to_c(-40) == -40.0


def test_round_trip():
    for c in (-273, -40, 0, 25, 100, 1240, 2000):
        assert c_to_f(f_to_c(c)) == pytest.approx(c)
        assert f_to_c(c_to_f(c)) == pytest.approx(c)


def test_to_display_celsius_scale(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'c')
    assert to_display(100) == 100


def test_to_display_fahrenheit_scale(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    assert to_display(100) == 212.0


def test_to_c_celsius_scale(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'c')
    assert to_c(100) == 100


def test_to_c_fahrenheit_scale(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    assert to_c(212) == pytest.approx(100)


def test_delta_conversions(monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    # a 1 degree fahrenheit difference is 5/9 degree celsius
    assert delta_to_c(5) == pytest.approx(5 * 5 / 9)
    assert delta_to_display(delta_to_c(5)) == pytest.approx(5)

    monkeypatch.setattr(config, 'temp_scale', 'c')
    assert delta_to_c(5) == 5
    assert delta_to_display(5) == 5


def test_display_profile_data(monkeypatch):
    data = [[0, 0], [3600, 100], [7200, -40]]
    monkeypatch.setattr(config, 'temp_scale', 'f')
    out = display_profile_data(data)
    assert out[0] == (0, 32.0)
    assert out[1] == (3600, 212.0)
    assert out[2] == (7200, -40.0)

    monkeypatch.setattr(config, 'temp_scale', 'c')
    out = display_profile_data(data)
    assert out == [(0, 0), (3600, 100), (7200, -40)]


def test_display_pidstats(monkeypatch):
    stats = {
        'setpoint': 100, 'ispoint': 50, 'err': 50, 'errDelta': 0.5,
        'p': 50, 'i': 25, 'd': 1.5, 'pid': 0.5, 'out': 0.5,
        'kp': 1, 'ki': 1, 'kd': 1, 'time': 1.0, 'timeDelta': 1.0,
    }
    monkeypatch.setattr(config, 'temp_scale', 'f')
    out = display_pidstats(stats)
    assert out['setpoint'] == pytest.approx(212.0)
    assert out['ispoint'] == pytest.approx(122.0)
    assert out['err'] == pytest.approx(90.0)
    assert out['errDelta'] == pytest.approx(0.9)
    assert out['p'] == pytest.approx(90.0)
    assert out['i'] == pytest.approx(45.0)
    assert out['d'] == pytest.approx(2.7)
    assert out['pid'] == 0.5
    assert out['out'] == 0.5
    # non-temperature fields are untouched
    assert out['kp'] == 1


def test_display_pidstats_celsius_scale(monkeypatch):
    stats = {'setpoint': 100, 'ispoint': 50, 'err': 50}
    monkeypatch.setattr(config, 'temp_scale', 'c')
    out = display_pidstats(stats)
    assert out == stats


def test_display_pidstats_empty():
    assert display_pidstats({}) == {}


def test_display_pidstats_missing_keys():
    assert display_pidstats({'pid': 1}) == {'pid': 1}
