'''Tests for the front-end UI work in public/assets/js/kiln-controller.js:
websocket auto-reconnect, the overview schedule label, and the config
editor tab. Pure functions are extracted from the real file and executed
with quickjs. Skipped if the quickjs module (a quick JS engine) is not
installed.'''

import os
import re
import json

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
    context.eval(extract_function(src, 'profileDescription'))
    context.eval(extract_function(src, 'toggleSimBadge'))
    context.eval(extract_function(src, 'updateOverviewStatus'))
    context.eval(extract_function(src, 'clear_persisted_all'))
    context.eval(extract_function(src, 'prune_persisted_all'))
    context.eval(extract_function(src, 'apiGet'))
    context.eval(extract_function(src, 'loadRemoteProfiles'))
    context.eval(extract_function(src, 'populateShareCategories'))
    context.eval(extract_function(src, 'importRemoteProfile'))
    context.eval(extract_function(src, 'shareProfile'))
    context.eval(extract_function(src, 'escHtml'))
    context.eval(extract_function(src, 'remoteFilterMatches'))
    context.eval(extract_function(src, 'renderRemoteProfiles'))
    context.eval(extract_function(src, 'isoLocal'))
    context.eval(extract_function(src, 'pad2'))
    context.eval(extract_function(src, 'formatDuration'))
    context.eval(extract_function(src, 'profileDurationSeconds'))
    context.eval(extract_function(src, 'scheduleAfter'))
    context.eval(extract_function(src, 'clearScheduleChain'))
    context.eval(extract_function(src, 'renderScheduleAfterList'))
    context.eval('var SCHEDULE_CHAIN_BUFFER = 60;')
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
# schedule description hover in the overview tab
########################################################################

def test_label_title_shows_running_profile_description(js):
    js.eval('var profiles = [{ name: "cone-05", description: "Bisque to cone 05" }];')
    js.eval('var running_profile_name = "cone-05";')
    js.eval('var selected_profile_name = "bisque-06";')
    js.eval('var el = { innerHTML: "", title: "" };')
    js.eval('function $(id) { return id === "selected_profile_label" ? el : null; }')
    js.eval('updateSelectedProfileLabel();')
    assert js.eval('el.title') == 'Bisque to cone 05'


def test_label_title_shows_selected_profile_description(js):
    js.eval('var profiles = [{ name: "bisque-06", description: "Ware bisque" }];')
    js.eval('var running_profile_name = null;')
    js.eval('var selected_profile_name = "bisque-06";')
    js.eval('var el = { innerHTML: "", title: "" };')
    js.eval('function $(id) { return id === "selected_profile_label" ? el : null; }')
    js.eval('updateSelectedProfileLabel();')
    assert js.eval('el.title') == 'Ware bisque'


def test_label_title_empty_without_description(js):
    js.eval('var profiles = [{ name: "legacy" }];')
    js.eval('var running_profile_name = null;')
    js.eval('var selected_profile_name = "legacy";')
    js.eval('var el = { innerHTML: "", title: "stale" };')
    js.eval('function $(id) { return id === "selected_profile_label" ? el : null; }')
    js.eval('updateSelectedProfileLabel();')
    assert js.eval('el.title') == ''


def test_profile_description_lookup(js):
    js.eval('var profiles = [{ name: "a", description: "first" }, { name: "b" }];')
    assert js.eval('profileDescription("a")') == 'first'
    assert js.eval('profileDescription("b")') == ''
    assert js.eval('profileDescription("missing")') == ''
    js.eval('profiles = undefined;')
    assert js.eval('profileDescription("a")') == ''


def test_profile_editor_has_description_field():
    # the edit page in the schedules tab must offer a description input
    html = open(os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                             'public', 'index.html'))).read()
    assert re.search(r'id="form_profile_description"', html)
    assert re.search(r'Description', html)


def test_edit_mode_populates_and_save_sends_description():
    src = open(JS_PATH).read()
    assert "$('form_profile_description').value = prof.description || '';" in src, \
        'enterEditMode must load the profile description'
    assert '"description": $(\'form_profile_description\').value' in src, \
        'saveProfile must include the description in the PUT payload'


########################################################################
# simulation badge
########################################################################

def test_sim_badge_shown_in_simulation(js):
    js.eval('var el = { style: { display: "" } };')
    js.eval('document = { getElementById: function(id) { return id === "sim_badge" ? el : null; } };')
    js.eval('toggleSimBadge(true);')
    assert js.eval('el.style.display') == 'inline-flex'


def test_sim_badge_hidden_when_real(js):
    js.eval('var el = { style: { display: "inline-flex" } };')
    js.eval('document = { getElementById: function(id) { return id === "sim_badge" ? el : null; } };')
    js.eval('toggleSimBadge(false);')
    assert js.eval('el.style.display') == 'none'


def test_sim_badge_ignores_missing_element(js):
    js.eval('document = { getElementById: function(id) { return null; } };')
    assert js.eval('(function(){ try { toggleSimBadge(true); return "ok"; } catch (e) { return "throw"; } })()') == 'ok'


########################################################################
# overview status badge
########################################################################

def test_status_badge_running(js):
    js.eval('state = "RUNNING";')
    js.eval('var el = { className: "", innerHTML: "" };')
    js.eval('document = { getElementById: function(id) { return id === "overview_status" ? el : null; } };')
    js.eval('updateOverviewStatus();')
    assert js.eval('el.innerHTML') == 'Running'
    assert js.eval('el.className') == 'badge overview-status text-bg-success'


def test_status_badge_idle(js):
    js.eval('state = "IDLE";')
    js.eval('var el = { className: "", innerHTML: "" };')
    js.eval('document = { getElementById: function(id) { return id === "overview_status" ? el : null; } };')
    js.eval('updateOverviewStatus();')
    assert js.eval('el.innerHTML') == 'Idle'
    assert js.eval('el.className') == 'badge overview-status text-bg-secondary'


def test_status_badge_paused(js):
    js.eval('state = "PAUSED";')
    js.eval('var el = { className: "", innerHTML: "" };')
    js.eval('document = { getElementById: function(id) { return id === "overview_status" ? el : null; } };')
    js.eval('updateOverviewStatus();')
    assert js.eval('el.innerHTML') == 'Paused'
    assert js.eval('el.className') == 'badge overview-status text-bg-warning'


def test_status_badge_unknown_state(js):
    js.eval('state = "WARPED";')
    js.eval('var el = { className: "", innerHTML: "" };')
    js.eval('document = { getElementById: function(id) { return id === "overview_status" ? el : null; } };')
    js.eval('updateOverviewStatus();')
    assert js.eval('el.innerHTML') == 'WARPED'
    assert js.eval('el.className') == 'badge overview-status text-bg-secondary'


def test_status_badge_ignores_missing_element(js):
    js.eval('state = "IDLE";')
    js.eval('document = { getElementById: function(id) { return null; } };')
    assert js.eval('(function(){ try { updateOverviewStatus(); return "ok"; } catch (e) { return "throw"; } })()') == 'ok'


def test_overview_heading_orders_status_between_name_and_sim():
    html = open(os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                             'public', 'index.html'))).read()
    m = re.search(r'selected_profile_label.*?overview_status.*?sim_badge', html, re.S)
    assert m, 'status badge must sit between the schedule name and the simulation badge'


def test_config_socket_updates_sim_badge():
    src = open(JS_PATH).read()
    assert 'simulate = x.simulate' in src
    assert 'toggleSimBadge(simulate)' in src


########################################################################
# persisted details pruning
########################################################################

def test_prune_persisted_all_drops_entries_older_than_cutoff(js):
    js.eval('var STORAGE_KEY = "kiln-controller-all";')
    js.eval('all = [{ time: 100, v: 1 }, { time: 200, v: 2 }, { time: 300, v: 3 }];')
    js.eval('var stored = null;')
    js.eval('localStorage = { setItem: function(k, v) { stored = v; }, removeItem: function(k) {} };')
    js.eval('save_timer = null;')
    js.eval('detailsInited = false;')
    js.eval('function drawall(d) {}')
    js.eval('function windowed_data() { return all; }')
    js.eval('prune_persisted_all(200);')
    assert js.eval('all.length') == 2
    assert js.eval('all[0].time') == 200
    assert js.eval('all[1].time') == 300
    assert js.eval('JSON.parse(stored).length') == 2


def test_prune_persisted_all_keeps_exact_cutoff(js):
    js.eval('var STORAGE_KEY = "kiln-controller-all";')
    js.eval('all = [{ time: 200, v: 1 }];')
    js.eval('var stored = null;')
    js.eval('localStorage = { setItem: function(k, v) { stored = v; }, removeItem: function(k) {} };')
    js.eval('save_timer = null;')
    js.eval('detailsInited = false;')
    js.eval('function drawall(d) {}')
    js.eval('function windowed_data() { return all; }')
    js.eval('prune_persisted_all(200);')
    assert js.eval('all.length') == 1


def test_backlog_prunes_stale_details():
    src = open(JS_PATH).read()
    # a client connecting into a firing that started while it was away must
    # drop persisted details older than the run start time
    assert 'prune_persisted_all(x.run_started)' in src
    # ...but a page that stays open and already knows the run must not
    # prune its live data
    assert 'adopting_run' in src


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


def test_config_dump_button_lives_at_bottom_of_config_tab():
    # the debug panel holding the config dump moved off the details tab
    # to the bottom of the config tab
    html = open(os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                             'public', 'index.html'))).read()
    m = re.search(r'id="tab-config"(.*?)id="tab-details"', html, re.S)
    assert m, 'config tab must appear before details tab in index.html'
    assert 'download_dump()' in m.group(1), \
        'config dump button must live in the config tab'
    m = re.search(r'id="tab-details".*?</section>', html, re.S)
    assert 'download_dump()' not in m.group(0), \
        'config dump button must not remain in the details tab'


########################################################################
# schedules tab: profile rows during a run
########################################################################

def _setup_profiles_context(js):
    '''load renderProfiles() with a minimal DOM: two profiles, a stubbed
    profiles_list element, and a no-op listScheduledRuns().'''
    src = open(JS_PATH).read()
    js.eval(extract_function(src, 'profileDuration'))
    js.eval(extract_function(src, 'renderProfiles'))
    js.eval('var el = { innerHTML: "" };')
    js.eval("$ = function (id) { return id === 'profiles_list' ? el : null; };")
    js.eval('var profiles = ['
            '  { name: "bisque", data: [[0, 65], [3600, 500]] },'
            '  { name: "glaze", data: [[0, 65], [1800, 400]] }'
            '];')
    js.eval('var selected_profile_name = null;')
    js.eval('var listScheduledRuns = function () {};')


def _render_profiles(js):
    js.eval('renderProfiles();')
    return js.eval('el.innerHTML')


def test_running_profile_row_hides_run_edit_and_delete(js):
    # the running row's Stop button is the only stop control in the ui,
    # so edit/delete are hidden: deleting the row would leave an active
    # firing unstoppable until it finished
    _setup_profiles_context(js)
    js.eval('running_profile_name = "bisque";')
    html = _render_profiles(js)

    assert 'abortTask()' in html                 # Stop stays
    assert 'selectProfile(0, true)' not in html  # Run swapped for Stop
    assert 'editProfile(0)' not in html          # Edit hidden
    assert 'selectProfile(0, null)' not in html  # Delete hidden

    # rows that are not running keep every button
    assert 'selectProfile(1, true)' in html      # Run
    assert 'scheduleProfile(1)' in html          # Schedule
    assert 'editProfile(1)' in html              # Edit
    assert 'selectProfile(1, null)' in html      # Delete


def test_edit_and_delete_return_when_the_run_ends(js):
    _setup_profiles_context(js)
    js.eval('running_profile_name = "bisque";')
    _render_profiles(js)

    # the firing completes (or is stopped): running_profile_name clears
    # and the buttons must come back without a page reload
    js.eval('running_profile_name = null;')
    html = _render_profiles(js)

    assert 'abortTask()' not in html
    assert 'editProfile(0)' in html
    assert 'selectProfile(0, null)' in html


########################################################################
# community schedules (kiln-profiles repo)
########################################################################

def test_schedules_tab_has_community_panel():
    html = open(os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                             'public', 'index.html'))).read()
    assert 'id="remote_profiles_list"' in html
    assert 'id="btn_refresh_remote"' in html
    assert 'loadRemoteProfiles(true)' in html  # Refresh forces a reload


def test_profile_editor_has_share_row():
    html = open(os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                             'public', 'index.html'))).read()
    assert 'id="share_profile_row"' in html
    assert 'id="form_share_category"' in html
    assert 'id="form_share_token"' in html
    assert 'shareProfile()' in html


def test_profiles_tab_loads_remote_profiles_on_show():
    src = open(JS_PATH).read()
    m = re.search(r"if \(name === 'profiles'\)\s*\{[^}]*renderProfiles\(\);[^}]*loadRemoteProfiles\(\);", src)
    assert m, 'showTab must load the community profiles when the schedules tab opens'


def test_remote_import_posts_path():
    src = open(JS_PATH).read()
    assert "fetch('/api/profiles/remote/import'" in src
    assert "JSON.stringify({ path: path })" in src


def test_share_profile_posts_editor_with_temp_units():
    src = open(JS_PATH).read()
    assert "fetch('/api/profiles/remote/upload'" in src
    assert '"temp_units": temp_scale' in src
    assert 'form_share_category' in src


def test_config_socket_toggles_share_row():
    src = open(JS_PATH).read()
    assert 'x.github_sharing_enabled' in src
    assert "shareRow.style.display = upload_enabled ? '' : 'none'" in src


def test_load_remote_profiles_renders_install_buttons(js):
    js.eval('var list_el = { innerHTML: "" };')
    js.eval('var share_el = { style: { display: "" } };')
    js.eval('var cat_sel = { innerHTML: "" };')
    js.eval('var els = {'
            '  remote_profiles_list: list_el,'
            '  share_profile_row: share_el,'
            '  form_share_category: cat_sel };')
    js.eval('function $(id) { return els[id] || null; }')
    js.eval('var seen = [];')
    js.eval('var remote_profiles_loaded = false;')
    js.eval('apiGet = function(url, cb) { seen.push(url); cb({'
            '  success: true,'
            '  upload_enabled: false,'
            '  categories: ["pottery", "glass"],'
            '  profiles: [{ name: "cone-05", category: "pottery",'
            '              path: "pottery/cone-05.json", size: 400, installed: false }]'
            '}); };')
    js.eval('loadRemoteProfiles();')
    assert js.eval('seen[0]') == '/api/profiles/remote'
    assert 'cone-05' in js.eval('list_el.innerHTML')
    assert 'Import' in js.eval('list_el.innerHTML') or 'Install' in js.eval('list_el.innerHTML')
    # categories are offered in the share select
    assert 'pottery' in js.eval('cat_sel.innerHTML')
    assert 'glass' in js.eval('cat_sel.innerHTML')
    # upload disabled -> share row stays hidden
    assert js.eval('share_el.style.display') == 'none'


def test_load_remote_profiles_shows_installed_state(js):
    js.eval('var list_el = { innerHTML: "" };')
    js.eval('var share_el = { style: { display: "" } };')
    js.eval('var cat_sel = { innerHTML: "" };')
    js.eval('var els = {'
            '  remote_profiles_list: list_el,'
            '  share_profile_row: share_el,'
            '  form_share_category: cat_sel };')
    js.eval('function $(id) { return els[id] || null; }')
    js.eval('var remote_profiles_loaded = false;')
    js.eval('apiGet = function(url, cb) { cb({'
            '  success: true,'
            '  upload_enabled: true,'
            '  categories: ["pottery"],'
            '  profiles: [{ name: "cone-05", category: "pottery",'
            '              path: "pottery/cone-05.json", installed: true }]'
            '}); };')
    js.eval('loadRemoteProfiles();')
    assert 'installed' in js.eval('list_el.innerHTML')
    assert js.eval('share_el.style.display') == ''


def test_load_remote_profiles_shows_error(js):
    js.eval('var list_el = { innerHTML: "" };')
    js.eval('function $(id) { return id === "remote_profiles_list" ? list_el : null; }')
    js.eval('var remote_profiles_loaded = false;')
    js.eval('apiGet = function(url, cb) { cb({ success: false, error: "repo unreachable" }); };')
    js.eval('loadRemoteProfiles();')
    assert 'repo unreachable' in js.eval('list_el.innerHTML')


def test_community_panel_has_search_filter():
    html = open(os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                             'public', 'index.html'))).read()
    assert 'id="remote_filter_input"' in html
    assert 'applyRemoteFilter()' in html


def test_remote_filter_matches_category(js):
    js.eval('var p = { name: "cone-05-long-bisque", category: "pottery", tags: ["bisque"] };')
    assert js.eval('remoteFilterMatches(p, "pottery")') is True
    assert js.eval('remoteFilterMatches(p, "POTTERY")') is True  # case-insensitive


def test_remote_filter_matches_tag(js):
    js.eval('var p = { name: "cone-05-long-bisque", category: "pottery", tags: ["bisque", "cone05"] };')
    assert js.eval('remoteFilterMatches(p, "bisque")') is True
    assert js.eval('remoteFilterMatches(p, "cone05")') is True


def test_remote_filter_matches_description(js):
    js.eval('var p = { name: "bq1000", category: "pottery", tags: [],'
            '          description: "fires to cone 05 with a soak" };')
    assert js.eval('remoteFilterMatches(p, "soak")') is True
    assert js.eval('remoteFilterMatches(p, "Cone")') is True  # case-insensitive
    assert js.eval('remoteFilterMatches(p, "enamel")') is False


def test_remote_filter_no_match(js):
    js.eval('var p = { name: "cone-05-long-bisque", category: "pottery", tags: ["bisque"] };')
    assert js.eval('remoteFilterMatches(p, "metal")') is False
    assert js.eval('remoteFilterMatches(p, "")') is True  # empty shows everything


def test_render_remote_profiles_filters_rows(js):
    js.eval('remote_profiles = ['
            '  { name: "cone-05", category: "pottery", tags: ["bisque"], path: "pottery/cone-05.json" },'
            '  { name: "slumped", category: "glass", tags: ["slumping"], path: "glass/slumped.json" }'
            '];')
    js.eval('var els = {'
            '  remote_profiles_list: { innerHTML: "" },'
            '  remote_filter_input: { value: "bisque" } };')
    js.eval('function $(id) { return els[id] || null; }')
    js.eval('renderRemoteProfiles();')
    html = js.eval('els.remote_profiles_list.innerHTML')
    assert 'cone-05' in html
    assert 'slumped' not in html


def test_render_remote_profiles_no_match_message(js):
    js.eval('remote_profiles = ['
            '  { name: "cone-05", category: "pottery", tags: ["bisque"], path: "pottery/cone-05.json" }'
            '];')
    js.eval('var els = {'
            '  remote_profiles_list: { innerHTML: "" },'
            '  remote_filter_input: { value: "metal" } };')
    js.eval('function $(id) { return els[id] || null; }')
    js.eval('renderRemoteProfiles();')
    assert 'metal' in js.eval('els.remote_profiles_list.innerHTML')
    assert 'No community schedules match' in js.eval('els.remote_profiles_list.innerHTML')


def test_render_remote_profiles_shows_tags(js):
    js.eval('remote_profiles = ['
            '  { name: "cone-05", category: "pottery", tags: ["bisque", "cone05"], path: "pottery/cone-05.json" }'
            '];')
    js.eval('var els = {'
            '  remote_profiles_list: { innerHTML: "" },'
            '  remote_filter_input: { value: "" } };')
    js.eval('function $(id) { return els[id] || null; }')
    js.eval('renderRemoteProfiles();')
    html = js.eval('els.remote_profiles_list.innerHTML')
    assert 'bisque' in html
    assert 'cone05' in html
    assert 'text-bg-light' in html


def test_delete_profile_reloads_remote_installed_state():
    src = open(JS_PATH).read()
    body = extract_function(src, 'deleteProfile')
    # deleting a local profile must refresh the community list so the
    # installed badge is not stuck
    assert 'remote_profiles_loaded = false' in body
    assert 'loadRemoteProfiles()' in body


def test_share_profile_requires_a_name(js):
    js.eval('var growls = [];')
    js.eval('showGrowl = function(m) { growls.push(m); };')
    js.eval('var els = { form_profile_name: { value: "" }, form_share_category: { value: "pottery" } };')
    js.eval('function $(id) { return els[id] || null; }')
    js.eval('graph = { profile: { data: [[0, 20], [100, 30]] } };')
    js.eval('shareProfile();')
    assert 'Enter a schedule name first' in js.eval('growls[0]')
    assert js.eval('growls.length') == 1


def test_share_profile_posts_upload(js):
    js.eval('var growls = [];')
    js.eval('showGrowl = function(m) { growls.push(m); };')
    js.eval('var els = {'
            '  form_profile_name: { value: "my-bisque" },'
            '  form_profile_description: { value: "a bisque firing" },'
            '  form_share_category: { value: "pottery" },'
            '  form_share_token: { value: "" } };')
    js.eval('function $(id) { return els[id] || null; }')
    js.eval('graph = { profile: { data: [[0, 65], [3600, 1708]] } };')
    js.eval('temp_scale = "f";')
    js.eval('var posted = null;')
    js.eval('fetch = function(url, opts) {'
            '  posted = { url: url, opts: opts };'
            '  return Promise.resolve({ json: function() { return Promise.resolve({ success: true, name: "my-bisque", pr_url: "https://github.com/x/pull/1" }); } });'
            '};')
    js.eval('ws_storage = { send: function() {} };')
    js.eval('renderProfiles = function() {};')
    js.eval('shareProfile();')
    for _ in range(10):
        js.execute_pending_job()
    assert js.eval('posted.url') == '/api/profiles/remote/upload'
    body = json.loads(js.eval('posted.opts.body'))
    assert body['category'] == 'pottery'
    assert body['profile']['name'] == 'my-bisque'
    assert body['profile']['description'] == 'a bisque firing'
    assert body['profile']['temp_units'] == 'f'
    assert body['github_token'] == ''
    # the profile is submitted as a pull request, with a link
    growls = js.eval('growls.join(",")')
    assert 'pull request' in growls
    assert 'view PR' in growls


def test_share_profile_sends_and_remembers_github_token(js):
    js.eval('var growls = [];')
    js.eval('showGrowl = function(m) { growls.push(m); };')
    js.eval('var els = {'
            '  form_profile_name: { value: "my-bisque" },'
            '  form_profile_description: { value: "" },'
            '  form_share_category: { value: "pottery" },'
            '  form_share_token: { value: "ghp_abc123" } };')
    js.eval('function $(id) { return els[id] || null; }')
    js.eval('graph = { profile: { data: [[0, 65], [3600, 1708]] } };')
    js.eval('temp_scale = "c";')
    js.eval('var stored = null;')
    js.eval('localStorage = { getItem: function() { return null; },'
            '  setItem: function(k, v) { stored = v; } };')
    js.eval('var posted = null;')
    js.eval('fetch = function(url, opts) {'
            '  posted = { url: url, opts: opts };'
            '  return Promise.resolve({ json: function() { return Promise.resolve({ success: true, name: "my-bisque" }); } });'
            '};')
    js.eval('ws_storage = { send: function() {} };')
    js.eval('renderProfiles = function() {};')
    js.eval('shareProfile();')
    for _ in range(10):
        js.execute_pending_job()
    body = json.loads(js.eval('posted.opts.body'))
    assert body['github_token'] == 'ghp_abc123'
    # the token is remembered for next time
    assert js.eval('stored') == 'ghp_abc123'


def test_import_remote_profile_posts_and_refreshes(js):
    js.eval('var growls = [];')
    js.eval('showGrowl = function(m) { growls.push(m); };')
    js.eval('var sent = null;')
    js.eval('var reloaded = null;')
    js.eval('var rerendered = null;')
    js.eval('ws_storage = { send: function(m) { sent = m; } };')
    js.eval('var posted = null;')
    js.eval('fetch = function(url, opts) {'
            '  posted = { url: url, opts: opts };'
            '  return Promise.resolve({ json: function() { return Promise.resolve({ success: true, name: "cone-05" }); } });'
            '};')
    js.eval('renderProfiles = function() { rerendered = true; };')
    js.eval('loadRemoteProfiles = function(force) { reloaded = force; };')
    js.eval('importRemoteProfile("pottery/cone-05.json");')
    for _ in range(10):
        js.execute_pending_job()
    assert js.eval('posted.url') == '/api/profiles/remote/import'
    assert json.loads(js.eval('posted.opts.body')) == {'path': 'pottery/cone-05.json'}
    assert 'Installed' in js.eval('growls.join(",")')
    assert js.eval('sent') == 'GET'
    assert js.eval('reloaded') is True   # force a reload to update installed state
    assert js.eval('rerendered') is True


########################################################################
# scheduling a firing after the current one finishes
########################################################################

def test_profile_duration_seconds(js):
    js.eval('profiles = [{ name: "candling", data: [[0, 65], [2040, 150], [45240, 150]] }];')
    assert js.eval('profileDurationSeconds("candling")') == 45240
    assert js.eval('profileDurationSeconds("nope")') == 0


def test_schedule_after_sets_datetime(js):
    js.eval('var el = { value: "" };')
    js.eval('var hidden = { value: "" };')
    js.eval('var note = { style: { display: "none" } };')
    js.eval('function $(id) {'
            '  if (id === "schedule_datetime") return el;'
            '  if (id === "schedule_chain_after") return hidden;'
            '  if (id === "schedule_chain_note") return note;'
            '  return null; }')
    js.eval('scheduleAfter(1787000000, "run:7");')
    # isoLocal produces a local-time 'YYYY-MM-DDTHH:MM' string (minute precision)
    assert js.eval('el.value.length > 0')
    import datetime as _dt
    parsed = _dt.datetime.fromisoformat(js.eval('el.value'))
    assert abs(parsed.timestamp() - 1787000000) <= 60
    # the chain reference is remembered and the note explains the estimate
    assert js.eval('hidden.value') == 'run:7'
    assert js.eval('note.style.display') == ''


def test_clear_schedule_chain(js):
    js.eval('var hidden = { value: "run:7" };')
    js.eval('var note = { style: { display: "" } };')
    js.eval('function $(id) {'
            '  if (id === "schedule_chain_after") return hidden;'
            '  if (id === "schedule_chain_note") return note;'
            '  return null; }')
    js.eval('clearScheduleChain();')
    assert js.eval('hidden.value') == ''
    assert js.eval('note.style.display') == 'none'


def _schedule_after_stub(js, shown='', inner=''):
    js.eval('Date.now = function() { return 1000000000000; };')
    js.eval('var sched_after = { style: { display: %r } };' % shown)
    js.eval('var sched_list = { innerHTML: %r };' % inner)
    js.eval('function $(id) {'
            '  if (id === "schedule_after") return sched_after;'
            '  if (id === "schedule_after_list") return sched_list;'
            '  return null; }')


def test_render_schedule_after_list_lists_running_and_scheduled(js):
    _schedule_after_stub(js)
    future = 1000000000 + 10000   # now + 10000s
    js.eval('oven_status = { state: "RUNNING", profile: "candling", runtime: 3600,'
            ' totaltime: 45240, run_id: 3 };')
    js.eval('profiles = ['
            '  { name: "candling", data: [[0, 65], [2040, 150], [45240, 150]] },'
            '  { name: "cone-05-long-bisque", data: [[0, 65], [46800, 1708]] }'
            '];')
    js.eval('function apiPost(obj, cb) {'
            '  cb({ success: true, schedules: [{ profile: "cone-05-long-bisque",'
            '                                    id: "aa11bb22",'
            '                                    start_time: %d, startat: 0, fired: false }] });'
            '}' % future)
    js.eval('function formatDuration(s) { return "DUR" + s; }')
    js.eval('function escHtml(s) { return s; }')
    js.eval('renderScheduleAfterList();')
    html = js.eval('sched_list.innerHTML')
    assert 'candling' in html
    assert 'cone-05-long-bisque' in html
    assert 'running' in html
    assert 'scheduled' in html
    assert 'After this' in html
    assert js.eval('sched_after.style.display') == ''   # container is visible
    # running firing: chains after run 3, starting ~1 min after its actual end
    assert "scheduleAfter(%d, 'run:3')" % (1000000000 + 45240 - 3600 + 60) in html
    # scheduled firing: chains after the schedule id, ~1 min after its actual end
    assert "scheduleAfter(%d, 'sched:aa11bb22')" % (future + 46800 + 60) in html


def test_render_schedule_after_list_sorts_by_finish(js):
    _schedule_after_stub(js)
    future = 1000000000 + 10000   # now + 10000s
    js.eval('oven_status = { state: "RUNNING", profile: "long", runtime: 0, totaltime: 90000 };')
    js.eval('profiles = ['
            '  { name: "long", data: [[0, 65], [90000, 500]] },'
            '  { name: "short", data: [[0, 65], [1800, 200]] }'
            '];')
    js.eval('function apiPost(obj, cb) {'
            '  cb({ success: true, schedules: [{ profile: "short",'
            '                                    start_time: %d, startat: 0, fired: false }] });'
            '}' % future)
    js.eval('function formatDuration(s) { return "DUR" + s; }')
    js.eval('function escHtml(s) { return s; }')
    js.eval('renderScheduleAfterList();')
    html = js.eval('sched_list.innerHTML')
    # the short scheduled firing finishes first (future + 1800), so it is listed first
    assert html.index('short') < html.index('long')


def test_render_schedule_after_list_hides_when_nothing_to_chain(js):
    _schedule_after_stub(js, shown='block')
    js.eval('oven_status = { state: "IDLE", profile: null };')
    js.eval('profiles = [];')
    js.eval('function apiPost(obj, cb) { cb({ success: true, schedules: [] }); }')
    js.eval('renderScheduleAfterList();')
    assert js.eval('sched_after.style.display') == 'none'
    assert js.eval('sched_list.innerHTML') == ''
