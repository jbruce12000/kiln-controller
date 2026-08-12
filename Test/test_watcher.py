import types

import pytest

import watcher


def make_watcher(**kwargs):
    defaults = dict(kiln_url="http://example.com/api/stats",
                    slack_hook_url="http://hooks.example.com/xx",
                    bad_check_limit=6,
                    temp_error_limit=10,
                    sleepfor=10)
    defaults.update(kwargs)
    return watcher.Watcher(**defaults)


def test_init_defaults():
    w = make_watcher()
    assert w.bad_check_limit == 6
    assert w.temp_error_limit == 10
    assert w.sleepfor == 10
    assert w.bad_checks == 0
    assert w.stats == {}


def test_get_stats_success(monkeypatch):
    class FakeResponse:
        def json(self):
            return {'temp': 200}

    def fake_get(url, timeout):
        assert timeout == 1
        return FakeResponse()

    monkeypatch.setattr(watcher.requests, 'get', fake_get)
    w = make_watcher()
    assert w.get_stats() == {'temp': 200}


def test_get_stats_timeout(monkeypatch):
    def fake_get(url, timeout):
        raise watcher.requests.exceptions.Timeout()

    monkeypatch.setattr(watcher.requests, 'get', fake_get)
    w = make_watcher()
    assert w.get_stats() == {}


def test_get_stats_connection_error(monkeypatch):
    def fake_get(url, timeout):
        raise watcher.requests.exceptions.ConnectionError()

    monkeypatch.setattr(watcher.requests, 'get', fake_get)
    w = make_watcher()
    assert w.get_stats() == {}


def test_get_stats_other_error(monkeypatch):
    def fake_get(url, timeout):
        raise ValueError('boom')

    monkeypatch.setattr(watcher.requests, 'get', fake_get)
    w = make_watcher()
    assert w.get_stats() == {}


def test_send_alert_posts(monkeypatch):
    posted = {}

    def fake_post(url, json):
        posted['url'] = url
        posted['json'] = json

    monkeypatch.setattr(watcher.requests, 'post', fake_post)
    w = make_watcher()
    w.send_alert("kiln needs help")
    assert posted['url'] == "http://hooks.example.com/xx"
    assert posted['json'] == {'text': 'kiln needs help'}


def test_send_alert_survives_error(monkeypatch):
    def fake_post(url, json):
        raise OSError('no network')

    monkeypatch.setattr(watcher.requests, 'post', fake_post)
    w = make_watcher()
    w.send_alert("kiln needs help")  # must not raise


def test_has_errors_no_data():
    w = make_watcher()
    assert w.has_errors() is True


def test_has_errors_temp_out_of_whack():
    w = make_watcher()
    w.stats = {'time': 1, 'err': 50}
    assert w.has_errors() is True


def test_has_errors_within_limit():
    w = make_watcher()
    w.stats = {'time': 1, 'err': 2}
    assert w.has_errors() is False


def test_has_errors_at_limit_boundary():
    # errors exactly at the limit are OK (must be greater)
    w = make_watcher(temp_error_limit=10)
    w.stats = {'time': 1, 'err': 10}
    assert w.has_errors() is False


def test_run_loop_alerts_after_limit(monkeypatch):
    w = make_watcher(bad_check_limit=2, sleepfor=1)
    sent = []
    monkeypatch.setattr(watcher.requests, 'get',
                        lambda url, timeout: types.SimpleNamespace(json=lambda: {}))
    monkeypatch.setattr(w, 'send_alert', lambda msg: sent.append(msg))

    sleeps = [0]

    def fake_sleep(secs):
        sleeps[0] += 1
        if sleeps[0] >= 4:
            raise StopIteration

    monkeypatch.setattr(watcher.time, 'sleep', fake_sleep)

    with pytest.raises(StopIteration):
        w.run()

    assert len(sent) == 2  # resets each time it hits the limit
    assert all("error kiln needs help" in msg for msg in sent)
