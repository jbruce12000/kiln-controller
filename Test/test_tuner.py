import types

from lib.tuner import Tuner


class StubOven:
    def __init__(self, state='IDLE'):
        self.state = state
        self.output = types.SimpleNamespace(cool=lambda secs: None)
        self.heat = 0


def make_tuner(oven_state='IDLE'):
    oven = StubOven(oven_state)
    return Tuner(oven), oven


def stub_tuning_steps(tuner, monkeypatch, calls):
    '''replace the blocking/hardware parts so start() runs instantly'''
    monkeypatch.setattr(tuner, '_record', lambda target: calls.append('record'))

    def fake_calculate():
        calls.append('calc')
        tuner.pid_values = {'kp': 1.0, 'ki': 1.0, 'kd': 1.0}

    monkeypatch.setattr(tuner, '_calculate', fake_calculate)
    monkeypatch.setattr(tuner, '_apply_pid', lambda: calls.append('apply'))


def test_start_runs_full_sequence(monkeypatch):
    tuner, oven = make_tuner()
    calls = []
    stub_tuning_steps(tuner, monkeypatch, calls)

    tuner.start(100.0)

    assert tuner.state == Tuner.DONE
    assert oven.state == 'IDLE'
    assert calls == ['record', 'calc', 'apply']


def test_start_allowed_again_after_done(monkeypatch):
    '''the tuner must be re-runnable without a process restart; it used to
    lock up after its first run because DONE was treated as "running"'''
    tuner, oven = make_tuner()
    calls = []
    stub_tuning_steps(tuner, monkeypatch, calls)

    tuner.start(100.0)
    assert tuner.state == Tuner.DONE

    tuner.start(150.0)
    assert tuner.state == Tuner.DONE
    assert calls == ['record', 'calc', 'apply'] * 2


def test_start_allowed_again_after_error(monkeypatch):
    '''a failed tuning run must not block future attempts'''
    tuner, oven = make_tuner()
    calls = []
    stub_tuning_steps(tuner, monkeypatch, calls)

    def boom():
        raise ValueError('no usable data')

    monkeypatch.setattr(tuner, '_record', lambda target: calls.append('record'))
    monkeypatch.setattr(tuner, '_calculate', boom)

    tuner.start(100.0)
    assert tuner.state == Tuner.ERROR

    stub_tuning_steps(tuner, monkeypatch, calls)
    tuner.start(100.0)
    assert tuner.state == Tuner.DONE


def test_stop_during_record_returns_to_idle(monkeypatch):
    '''stopping mid-tune used to leave the state stuck at HEATING forever'''
    tuner, oven = make_tuner()
    started = []

    def fake_record(target):
        started.append(1)
        tuner.stop()    # user hits stop while the heating loop is running

    monkeypatch.setattr(tuner, '_record', fake_record)

    tuner.start(100.0)  # record exits early on _stop_requested

    assert started == [1]
    assert tuner.state == Tuner.IDLE
    assert oven.state == 'IDLE'


def test_start_rejected_when_oven_busy():
    tuner, oven = make_tuner(oven_state='RUNNING')

    tuner.start(100.0)

    assert tuner.state == Tuner.ERROR
    assert 'busy' in tuner.error
    assert oven.state == 'RUNNING'
