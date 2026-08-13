'''Tests for the front-end UI work in public/assets/js/kiln-controller.js:
websocket auto-reconnect, the overview schedule label, and the config
editor tab. Pure functions are extracted from the real file and executed
with quickjs. Skipped if the quickjs module (a quick JS engine) is not
installed.'''

import os
import re

import pytest

quickjs = pytest.importorskip('quickjs')

JS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                       'public', 'assets', 'js',
                                       'kiln-controller.js'))


def extract_function(src, name):
    m = re.search(r'\n\s*function %s\([^)]*\)\s*\{' % re.escape(name), src)
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


@pytest.fixture
def js():
    src = open(JS_PATH).read()
    context = quickjs.Context()
    context.eval(extract_function(src, 'make_socket'))
    context.eval(extract_function(src, 'schedule_reconnect'))
    context.eval(extract_function(src, 'updateSelectedProfileLabel'))
    return context


########################################################################
# websocket auto-reconnect
########################################################################

def test_make_socket_connects_to_host_path(js):
    js.eval('var host = "ws://localhost:9099";')
    js.eval('window = {};')
    js.eval('function WebSocket(url) { this.url = url; }')
    js.eval('var ws = make_socket("status");')
    assert js.eval('ws.url') == 'ws://localhost:9099/status'
    # the socket is registered as a global so init() can attach handlers
    assert js.eval('window["ws_status"] === ws')


def test_reconnect_backoff_doubles_then_caps(js):
    js.eval('var reconnect_attempts = {};')
    js.eval('var reconnect_max_delay = 15000;')
    js.eval('var reconnect_pending = {};')
    js.eval('var timers = [];')
    js.eval('setTimeout = function(fn, delay) { timers.push({ fn: fn, delay: delay }); };')
    js.eval('window = {};')
    js.eval('function make_socket(name) {'
            '  window["ws_" + name] = { onopen: null, onmessage: null, onclose: null };'
            '  return window["ws_" + name];'
            '}')
    js.eval('function showGrowl() {}')
    # init() wires each socket's onclose to schedule a reconnect
    js.eval('function init_onclose() { schedule_reconnect("status"); }')
    js.eval('window["ws_status"] = { onopen: function(){}, onmessage: function(){}, onclose: init_onclose };')

    js.eval('schedule_reconnect("status");')
    assert js.eval('timers[0].delay') == 3000

    # simulate six disconnect/reconnect cycles
    js.eval('''
        for (var i = 0; i < 6; i++) {
            var t = timers[timers.length - 1];
            t.fn();
            window["ws_status"].onclose();
        }
        var delays = timers.map(function(t) { return t.delay; });
        var delays_ok = JSON.stringify(delays) ===
            JSON.stringify([3000, 6000, 12000, 15000, 15000, 15000, 15000]);
    ''')
    assert js.eval('delays_ok')


def test_reconnect_reuses_handlers_and_reports_reconnected(js):
    js.eval('var reconnect_attempts = {};')
    js.eval('var reconnect_max_delay = 15000;')
    js.eval('var reconnect_pending = {};')
    js.eval('var timers = [];')
    js.eval('setTimeout = function(fn, delay) { timers.push({ fn: fn, delay: delay }); };')
    js.eval('window = {};')
    js.eval('function make_socket(name) {'
            '  window["ws_" + name] = { onopen: null, onmessage: null, onclose: null };'
            '  return window["ws_" + name];'
            '}')
    js.eval('var growls = 0;')
    js.eval('showGrowl = function() { growls++; };')
    js.eval('var onmessageFn = function() { return "msg-handler"; };')
    js.eval('var oncloseFn = function() {};')
    js.eval('window["ws_status"] = { onopen: function(){}, onmessage: onmessageFn, onclose: oncloseFn };')

    js.eval('schedule_reconnect("status");')
    js.eval('timers[0].fn();')  # reconnect opens
    js.eval('window["ws_status"].onopen();')  # browser fires onopen

    # the new socket keeps the message handler from the old one
    assert js.eval('window["ws_status"].onmessage === onmessageFn')
    # the status socket shows a growl and resets the attempt counter
    assert js.eval('growls') == 1
    assert js.eval('reconnect_attempts["status"]') == 0


def test_all_sockets_reconnect_on_close():
    src = open(JS_PATH).read()
    for name in ('status', 'control', 'config', 'storage'):
        assert re.search(r"schedule_reconnect\('%s'\)" % name, src), \
            'no reconnect for %s socket' % name


########################################################################
# overview schedule label
########################################################################

def test_label_shows_running_profile(js):
    js.eval('var running_profile_name = "cone-05-long-bisque";')
    js.eval('var selected_profile_name = "bisque-06";')
    js.eval('var el = { innerHTML: "" };')
    js.eval('function $(id) { return id === "selected_profile_label" ? el : null; }')
    js.eval('updateSelectedProfileLabel();')
    assert js.eval('el.innerHTML') == 'cone-05-long-bisque'


def test_label_shows_selected_when_not_running(js):
    js.eval('var running_profile_name = null;')
    js.eval('var selected_profile_name = "bisque-06";')
    js.eval('var el = { innerHTML: "" };')
    js.eval('function $(id) { return id === "selected_profile_label" ? el : null; }')
    js.eval('updateSelectedProfileLabel();')
    assert js.eval('el.innerHTML') == 'bisque-06'


def test_label_placeholder_when_nothing_selected(js):
    js.eval('var running_profile_name = null;')
    js.eval('var selected_profile_name = null;')
    js.eval('var el = { innerHTML: "" };')
    js.eval('function $(id) { return id === "selected_profile_label" ? el : null; }')
    js.eval('updateSelectedProfileLabel();')
    assert js.eval('el.innerHTML') == 'Select Profile'


########################################################################
# config editor tab
########################################################################

def test_tabs_include_config():
    src = open(JS_PATH).read()
    assert re.search(
        r"var TABS = \[\s*'overview'\s*,\s*'details'\s*,\s*'profiles'\s*,\s*'config'\s*\]",
        src)


def test_save_config_posts_editor_contents():
    src = open(JS_PATH).read()
    assert re.search(r"fetch\('/api/config/editor'", src)
    assert re.search(r"method: 'POST'", src)
    assert "JSON.stringify({ config: $('config_editor').value })" in src


def test_save_config_handles_restart_and_warning_responses():
    src = open(JS_PATH).read()
    assert 'resp.restart_scheduled' in src
    assert 'resp.warning' in src
    assert 'ERROR 96' in src  # save-rejected growl


def test_config_tab_loads_editor_on_show():
    src = open(JS_PATH).read()
    m = re.search(r"if \(name === 'config'\)\s*\{[^}]*loadConfigEditor\(\);", src)
    assert m, 'showTab must load the config editor when the config tab opens'
    assert re.search(r"fetch\('/api/config/editor'\)", src)
    assert "if (!r.ok)" in src  # non-200 responses are surfaced as errors
