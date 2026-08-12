'''Tests that the front-end displays schedule durations longer than a day
correctly. The formatting helpers in public/assets/js/kiln-controller.js are
pure functions, so they are extracted from the real file and executed with
quickjs. Skipped if the quickjs module (a quick JS engine) is not installed.'''

import os
import re

import pytest

quickjs = pytest.importorskip('quickjs')

JS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                       'public', 'assets', 'js',
                                       'kiln-controller.js'))


def extract_function(src, name):
    m = re.search(r'\nfunction %s\([^)]*\)\s*\{' % re.escape(name), src)
    if not m:
        raise AssertionError(
            'function %s not found in %s' % (name, JS_PATH))
    start = m.end() - 1
    depth = 1
    i = start + 1
    while depth > 0:
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
        i += 1
    return src[m.start():i]


@pytest.fixture(scope='module')
def js():
    src = open(JS_PATH).read()
    context = quickjs.Context()
    context.eval(extract_function(src, 'formatDuration'))
    context.eval(extract_function(src, 'formatCountdown'))
    context.eval(extract_function(src, 'profileDuration'))
    return context


########################################################################
# formatDuration
########################################################################

def test_duration_over_one_day(js):
    assert js.eval('formatDuration(26 * 3600)') == '1 02:00:00'


def test_duration_multiple_days(js):
    assert js.eval('formatDuration(50 * 3600 + 3600 + 61)') == '2 03:01:01'


def test_duration_exactly_one_day(js):
    assert js.eval('formatDuration(24 * 3600)') == '1 00:00:00'


def test_duration_subday(js):
    assert js.eval('formatDuration(6 * 3600 + 5 * 60 + 4)') == '06:05:04'


def test_duration_zero(js):
    assert js.eval('formatDuration(0)') == '00:00:00'


def test_duration_negative_clamps_to_zero(js):
    assert js.eval('formatDuration(-3600)') == '00:00:00'


########################################################################
# formatCountdown (scheduled runs "starts in ..." display)
########################################################################

def test_countdown_over_one_day(js):
    assert js.eval('formatCountdown(26 * 3600)') == '1 02:00:00'


def test_countdown_multiple_days(js):
    assert js.eval('formatCountdown(100 * 3600 + 12 * 3600)') == '4 16:00:00'


########################################################################
# profileDuration (saved schedules "duration ..." display)
########################################################################

def test_profile_duration_over_one_day(js):
    data = '[[0, 200], [26 * 3600, 2000]]'
    assert js.eval('profileDuration(%s)' % data) == '1 02:00:00'


def test_profile_duration_multiple_days(js):
    data = '[[0, 200], [100 * 3600, 2000]]'
    assert js.eval('profileDuration(%s)' % data) == '4 04:00:00'


def test_profile_duration_takes_last_point(js):
    data = '[[0, 200], [26 * 3600 + 30.7, 2000]]'
    assert js.eval('profileDuration(%s)' % data) == '1 02:00:30'


def test_profile_duration_subday(js):
    data = '[[0, 200], [90 * 60, 2000]]'
    assert js.eval('profileDuration(%s)' % data) == '01:30:00'


def test_profile_duration_empty(js):
    assert js.eval('profileDuration([])') == '00:00:00'


########################################################################
# running run ETA display
########################################################################

def test_running_eta_uses_day_aware_formatter():
    # the ETA shown while a run is in progress must go through the
    # day-aware formatter, not the old HH:MM:SS that wraps past 24h
    src = open(JS_PATH).read()
    m = re.search(r'var eta = ([^;]+);', src)
    assert m, 'eta computation not found in %s' % JS_PATH
    assert 'formatDuration' in m.group(1)
    assert 'toISOString' not in m.group(1)


def test_backlog_clears_storage_when_idle():
    # when the server reports no run in progress on connect, the client
    # must wipe stored details data left over from a previous firing
    src = open(JS_PATH).read()
    m = re.search(r'if \(!x\.run_started\)\s*\{(.{0,300}?)clear_persisted_all\(\);',
                  src, re.S)
    assert m, 'backlog handler must clear stored data when the server is idle'


def test_download_logs_uses_api_endpoint():
    # the logs download button must hit the /api/logs endpoint so it is
    # not shadowed by the static-file catch-all route
    src = open(JS_PATH).read()
    assert "'/api/logs'" in src or '"/api/logs"' in src
