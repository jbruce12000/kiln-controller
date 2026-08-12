import io

import pytest

import gpioreadall


class FakeProc:
    def __init__(self, stdout):
        self.stdout = stdout


def test_modes():
    assert gpioreadall.MODES[0] == 'IN'
    assert gpioreadall.MODES[1] == 'OUT'
    assert len(gpioreadall.MODES) == 8


def test_header_is_40_pins():
    assert len(gpioreadall.HEADER) == 40
    # power pins are strings, gpios are ints
    assert gpioreadall.HEADER[0] == '3.3v'
    assert isinstance(gpioreadall.HEADER[7], int)


def test_pi_model():
    assert gpioreadall.PiModel[0x11] == '4B'
    assert gpioreadall.PiModel[0x12] == 'Zero2W'


def test_pin_state_input_pullup(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'GPIO 5: level=1 fsel=0 func=INPUT pull=UP\n'))
    assert gpioreadall.pin_state(5) == ('GPIO5', 'IN ^', 1)


def test_pin_state_input_pulldown(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'GPIO 5: level=0 fsel=0 func=INPUT pull=DOWN\n'))
    assert gpioreadall.pin_state(5) == ('GPIO5', 'IN v', 0)


def test_pin_state_input_no_pull(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'GPIO 5: level=1 fsel=0 func=INPUT\n'))
    assert gpioreadall.pin_state(5) == ('GPIO5', 'IN', 1)


def test_pin_state_output(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'GPIO 23: level=1 fsel=1 func=OUTPUT\n'))
    assert gpioreadall.pin_state(23) == ('GPIO23', 'OUT', 1)


def test_pin_state_alt(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'GPIO 8: level=0 fsel=2 func=ALT5\n'))
    name, mode, value = gpioreadall.pin_state(8)
    assert name == 'ALT5'
    assert mode == 'ALT5'
    assert value == 0


def test_pin_state_no_fsel(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'GPIO 0: level=1 func=SPI0_CE0_N\n'))
    name, mode, value = gpioreadall.pin_state(0)
    assert name == 'SPI0_CE0_N'
    assert mode == ''
    assert value == 1


def test_pin_state_calls_raspi_gpio(monkeypatch):
    captured = []

    def fake_run(args, stdout=None):
        captured.append(args)
        return FakeProc(b'GPIO 5: level=1 fsel=1 func=OUTPUT\n')

    monkeypatch.setattr(gpioreadall.subprocess, 'run', fake_run)
    gpioreadall.pin_state(5)
    assert captured == [['raspi-gpio', 'get', '5']]


def test_get_hardware_revision(monkeypatch):
    monkeypatch.setattr('builtins.open',
                        lambda *a, **k: io.StringIO('Revision : a020d3\n'))
    assert gpioreadall.get_hardware_revision() == 0xa020d3


def test_main_new_style_board(monkeypatch, capsys):
    monkeypatch.setattr(gpioreadall, 'get_hardware_revision', lambda: 0xc03111)
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'GPIO 23: level=1 fsel=1 func=OUTPUT\n'))
    gpioreadall.main()
    out = capsys.readouterr().out
    assert 'Pi 4B' in out


def test_main_old_style_board(monkeypatch, capsys):
    monkeypatch.setattr(gpioreadall, 'get_hardware_revision', lambda: 0x0d)
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'GPIO 23: level=1 fsel=1 func=OUTPUT\n'))
    gpioreadall.main()
    out = capsys.readouterr().out
    assert 'Pi B' in out
