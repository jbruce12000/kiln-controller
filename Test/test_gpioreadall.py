import io

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
                        lambda *a, **k: FakeProc(b'5: ip pu | hi // GPIO5 = input\n'))
    assert gpioreadall.pin_state(5) == ('GPIO5', 'IN ^', 1)


def test_pin_state_input_pulldown(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'5: ip pd | lo // GPIO5 = input\n'))
    assert gpioreadall.pin_state(5) == ('GPIO5', 'IN v', 0)


def test_pin_state_input_no_pull(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'5: ip -- | hi // GPIO5 = input\n'))
    assert gpioreadall.pin_state(5) == ('GPIO5', 'IN', 1)


def test_pin_state_output(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'23: op -- | hi // GPIO23 = output\n'))
    assert gpioreadall.pin_state(23) == ('GPIO23', 'OUT', 1)


def test_pin_state_alt(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'14: a4 -- | hi // PIN8/GPIO14 = TXD0\n'))
    name, mode, value = gpioreadall.pin_state(14)
    assert name == 'TXD0'
    assert mode == 'ALT4'
    assert value == 1


def test_pin_state_parse_failure(monkeypatch):
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'garbage output\n'))
    name, mode, value = gpioreadall.pin_state(0)
    assert name == 'GPIO0'
    assert mode == 'IN'
    assert value == 0


def test_pin_state_calls_pinctrl(monkeypatch):
    captured = []

    def fake_run(args, stdout=None):
        captured.append(args)
        return FakeProc(b'5: op -- | hi // GPIO5 = output\n')

    monkeypatch.setattr(gpioreadall.subprocess, 'run', fake_run)
    gpioreadall.pin_state(5)
    assert captured == [['pinctrl', 'get', '5']]


def test_get_hardware_revision(monkeypatch):
    monkeypatch.setattr('builtins.open',
                        lambda *a, **k: io.StringIO('Revision : a020d3\n'))
    assert gpioreadall.get_hardware_revision() == 0xa020d3


def test_main_new_style_board(monkeypatch, capsys):
    monkeypatch.setattr(gpioreadall, 'get_hardware_revision', lambda: 0xc03111)
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'23: op -- | hi // GPIO23 = output\n'))
    gpioreadall.main()
    out = capsys.readouterr().out
    assert 'Pi 4B' in out


def test_main_old_style_board(monkeypatch, capsys):
    monkeypatch.setattr(gpioreadall, 'get_hardware_revision', lambda: 0x0d)
    monkeypatch.setattr(gpioreadall.subprocess, 'run',
                        lambda *a, **k: FakeProc(b'23: op -- | hi // GPIO23 = output\n'))
    gpioreadall.main()
    out = capsys.readouterr().out
    assert 'Pi B' in out
