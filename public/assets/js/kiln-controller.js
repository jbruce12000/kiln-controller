var state = "IDLE";
var state_last = "";
var run_started = null;
var running_profile_name = null;
var running_profile_name_last = null;
var backlog_profile_name = null;
var graph = {
    profile: { label: "Profile", data: [], color: "#75890c", draggable: false, visible: true },
    live: { label: "Live", data: [], color: "#ffffff", draggable: false, visible: true }
};
var profiles = [];
var selected_profile = 0;
var selected_profile_name = '';
var temp_scale = "c";
var time_scale_slope = "s";
var time_scale_profile = "h";
var time_scale_long = "Seconds";
var temp_scale_display = "C";
var kwh_rate = 0.26;
var currency_type = "EUR";

var PROFILE_DS = 0;
var LIVE_DS = 1;

var chart = null;

// tuning state
var all = [];
var STORAGE_KEY = 'kiln-controller-all';
try {
    var saved_all = localStorage.getItem(STORAGE_KEY);
    if (saved_all) {
        var parsed_all = JSON.parse(saved_all);
        if (Array.isArray(parsed_all)) { all = parsed_all; }
    }
} catch (e) {
    all = [];
}
var table = "";
var tableBuilt = false;
var charts = {};
var detailsInited = false;

var save_timer = null;
function persist_all() {
    if (save_timer) { return; }
    save_timer = setTimeout(function() {
        save_timer = null;
        try {
            var slice = all.length > 6000 ? all.slice(-6000) : all;
            localStorage.setItem(STORAGE_KEY, JSON.stringify(slice));
        } catch (e) {}
    }, 2000);
}
function flush_all() {
    if (save_timer) {
        clearTimeout(save_timer);
        save_timer = null;
    }
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(all.slice(-6000)));
    } catch (e) {}
}
function clear_persisted_all() {
    all = [];
    if (save_timer) {
        clearTimeout(save_timer);
        save_timer = null;
    }
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
    if (detailsInited && table) {
        table.replaceData(latest(20));
        drawall(windowed_data());
    }
}
window.addEventListener('pagehide', flush_all);

var TABS = ['overview', 'details', 'profiles'];

var protocol = 'ws:';
if (window.location.protocol == 'https:') {
    protocol = 'wss:';
}
var host = "" + protocol + "//" + window.location.hostname + ":" + window.location.port;
var ws_status = new WebSocket(host+"/status");
var ws_control = new WebSocket(host+"/control");
var ws_config = new WebSocket(host+"/config");
var ws_storage = new WebSocket(host+"/storage");

var socket_states = {
    status: false,
    control: false,
    config: false,
    storage: false
};

function update_conn_indicator() {
    var all = socket_states.status && socket_states.control &&
              socket_states.config && socket_states.storage;
    var el = $('conn_indicator');
    if (all) {
        el.classList.add('connected');
        el.classList.remove('disconnected');
        $('conn_text').innerHTML = 'Connected';
    }
    else {
        el.classList.remove('connected');
        el.classList.add('disconnected');
        $('conn_text').innerHTML = 'Reconnecting';
    }
}

function socket_opened(name) {
    socket_states[name] = true;
    update_conn_indicator();
}

function socket_closed(name) {
    socket_states[name] = false;
    update_conn_indicator();
}

function $(id) {
    return document.getElementById(id);
}

function show(el) {
    el.style.display = '';
}

function hide(el) {
    el.style.display = 'none';
}

function showGrowl(html, type, delay) {
    var container = $('toastContainer');
    var toast = document.createElement('div');
    toast.className = 'toast align-items-center text-white border-0';
    toast.setAttribute('role', 'alert');
    if (type == 'success') { toast.classList.add('bg-success'); }
    else if (type == 'error') { toast.classList.add('bg-danger'); }
    else { toast.classList.add('bg-dark'); }
    toast.innerHTML = '<div class="d-flex"><div class="toast-body">' + html + '</div>' +
        '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
    container.appendChild(toast);
    var bsToast = new bootstrap.Toast(toast, { delay: (delay === undefined ? 5000 : delay) });
    toast.addEventListener('hidden.bs.toast', function() { toast.remove(); });
    bsToast.show();
}

/* ---------------------------------------------------------------------------
   Tabs
--------------------------------------------------------------------------- */

function openTabFromHash() {
    var h = window.location.hash.replace('#', '');
    if (TABS.indexOf(h) !== -1) {
        showTab(h);
    } else {
        showTab('overview');
    }
}

function showTab(name) {
    for (var i = 0; i < TABS.length; i++) {
        var pane = $('tab-' + TABS[i]);
        if (pane) {
            pane.style.display = (TABS[i] === name) ? '' : 'none';
        }
    }
    var links = document.querySelectorAll('.nav-link[data-tab]');
    for (var j = 0; j < links.length; j++) {
        if (links[j].getAttribute('data-tab') === name) {
            links[j].classList.add('active');
        } else {
            links[j].classList.remove('active');
        }
    }
    if (name === 'details') {
        initDetails();
    } else if (name === 'profiles') {
        renderProfiles();
    } else if (name === 'overview' && chart) {
        chart.resize();
    }
}

function initDetails() {
    if (!detailsInited) {
        create_charts();
        drawall(all);
        create_table([]);
        detailsInited = true;
        return;
    }
    var k;
    for (k in charts) {
        if (charts.hasOwnProperty(k)) {
            charts[k].resize();
        }
    }
    if (table) {
        table.redraw();
    }
}

/* ---------------------------------------------------------------------------
   Theme toggle
--------------------------------------------------------------------------- */

function currentTheme() {
    return document.documentElement.classList.contains('light') ? 'light' : 'dark';
}

function toggleTheme() {
    setTheme(currentTheme() === 'light' ? 'dark' : 'light');
}

function setTheme(theme) {
    var root = document.documentElement;
    if (theme === 'light') {
        root.classList.add('light');
    } else {
        root.classList.remove('light');
    }
    try {
        localStorage.setItem('kiln-theme', theme);
    } catch (e) {}
    var icon = $('theme_icon');
    if (icon) {
        icon.className = theme === 'light' ? 'bi bi-sun' : 'bi bi-moon-stars';
    }
    applyChartTheme();
}

function themeColors() {
    var light = currentTheme() === 'light';
    return {
        axis: light ? 'rgba(40,38,34,0.75)' : 'rgba(216,211,197,0.85)',
        axisDim: light ? 'rgba(40,38,34,0.6)' : 'rgba(216,211,197,0.7)',
        grid: light ? 'rgba(40,38,34,0.14)' : 'rgba(216,211,197,0.2)',
        gridDim: light ? 'rgba(40,38,34,0.1)' : 'rgba(216,211,197,0.15)',
        live: light ? '#4a4640' : '#ffffff',
        liveFill: light ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.18)'
    };
}

function applyChartTheme() {
    var tc = themeColors();
    if (chart) {
        var ds = chart.data.datasets;
        if (ds[LIVE_DS]) {
            ds[LIVE_DS].borderColor = tc.live;
            ds[LIVE_DS].backgroundColor = tc.liveFill;
        }
        chart.options.scales.x.ticks.color = tc.axis;
        chart.options.scales.y.ticks.color = tc.axis;
        chart.options.scales.x.grid.color = tc.grid;
        chart.options.scales.y.grid.color = tc.grid;
        chart.update('none');
    }
    for (var k in charts) {
        if (charts.hasOwnProperty(k) && charts[k]) {
            var c = charts[k];
            c.options.scales.x.ticks.color = tc.axisDim;
            c.options.scales.y.ticks.color = tc.axisDim;
            c.options.scales.x.grid.color = tc.gridDim;
            c.options.scales.y.grid.color = tc.gridDim;
            if (c.options.plugins && c.options.plugins.legend && c.options.plugins.legend.labels) {
                c.options.plugins.legend.labels.color = tc.axis;
            }
            c.data.datasets.forEach(function(ds2) {
                if (ds2.label === 'temp') {
                    ds2.borderColor = tc.live;
                    ds2.backgroundColor = tc.live;
                }
            });
            c.update('none');
        }
    }
}

/* ---------------------------------------------------------------------------
   Overview graph
--------------------------------------------------------------------------- */

function createChart() {
    var tc = themeColors();
    chart = new Chart($('graph_canvas'), {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'Profile',
                    data: [],
                    order: 2,
                    borderColor: '#75890c',
                    backgroundColor: '#75890c',
                    borderWidth: 2,
                    pointRadius: 0,
                    pointBackgroundColor: '#75890c',
                    pointBorderColor: '#75890c',
                    pointHitRadius: 30,
                    pointHoverRadius: 6,
                    showLine: true,
                    fill: false,
                    spanGaps: true,
                    tension: 0,
                    dragData: false
                },
                {
                    label: 'Live',
                    data: [],
                    order: 1,
                    borderColor: tc.live,
                    backgroundColor: tc.liveFill,
                    borderWidth: 2,
                    pointRadius: 0,
                    showLine: true,
                    fill: false,
                    spanGaps: true,
                    tension: 0,
                    dragData: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: 'nearest', intersect: true },
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false },
                dragData: {
                    dragX: true,
                    dragY: true,
                    round: 0,
                    showTooltip: false,
                    onDrag: dragUpdate,
                    onDragEnd: dragEnd
                }
            },
            scales: {
                x: {
                    type: 'linear',
                    min: 0,
                    ticks: {
                        stepSize: 3600,
                        maxRotation: 0,
                        callback: timeTickFormatter,
                        color: tc.axis,
                        font: { family: "Digi", size: 14, weight: "normal" }
                    },
                    grid: { color: tc.grid }
                },
                y: {
                    type: 'linear',
                    min: 0,
                    ticks: {
                        stepSize: 50,
                        color: tc.axis,
                        font: { family: "Digi", size: 14, weight: "normal" }
                    },
                    grid: { color: tc.grid }
                }
            }
        }
    });
}

function syncChartData() {
    var ds = chart.data.datasets;
    ds[PROFILE_DS].data = graph.profile.data.map(function(p) { return { x: p[0], y: p[1] }; });
    ds[LIVE_DS].data = graph.live.data.map(function(p) { return { x: p[0], y: p[1] }; });
    chart.update('none');
}

function axisStep(max) {
    if (max > 3600) { return 3600; }
    if (max > 360) { return 120; }
    if (max > 60) { return 60; }
    return 1;
}

function yStep(max) {
    if (max > 1000) { return 200; }
    if (max > 500) { return 100; }
    if (max > 200) { return 50; }
    return 25;
}

function updateAxis() {
    var minX = Infinity, maxX = 0, maxY = 0;
    var allpts = graph.profile.data.concat(graph.live.data);
    for (var i = 0; i < allpts.length; i++) {
        if (allpts[i][0] > maxX) { maxX = allpts[i][0]; }
        if (allpts[i][0] < minX) { minX = allpts[i][0]; }
        if (allpts[i][1] > maxY) { maxY = allpts[i][1]; }
    }
    if (minX === Infinity) { minX = 0; }
    var xs = axisStep(maxX);
    chart.options.scales.x.min = minX > 0 ? Math.floor(minX / xs) * xs : 0;
    chart.options.scales.x.max = maxX > 0 ? Math.ceil(maxX / xs) * xs : xs;
    chart.options.scales.x.ticks.stepSize = xs;
    var ys = yStep(maxY);
    chart.options.scales.y.min = 0;
    chart.options.scales.y.max = maxY > 0 ? Math.ceil(maxY / ys) * ys : 100;
    chart.options.scales.y.ticks.stepSize = ys;
    chart.update('none');
}

function dragUpdate(e, datasetIndex, index, value) {
    if (datasetIndex !== PROFILE_DS) { return; }
    if (value === null || value === undefined || value.x === undefined) { return; }
    value.x = Math.max(0, value.x);
    value.y = Math.max(0, value.y);
    graph.profile.data[index] = [value.x, value.y];
    if (value.x > chart.options.scales.x.max) {
        var xs = axisStep(value.x);
        chart.options.scales.x.max = Math.ceil(value.x / xs) * xs;
    }
    if (value.y > chart.options.scales.y.max) {
        var ys = yStep(value.y);
        chart.options.scales.y.max = Math.ceil(value.y / ys) * ys;
    }
}

function dragEnd(e, datasetIndex, index, value) {
    if (datasetIndex !== PROFILE_DS) { return; }
    if (value !== null && value !== undefined && value.x !== undefined) {
        graph.profile.data[index] = [value.x, value.y];
    }
    updateAxis();
    updateProfileTable();
}

function setEditMode(on) {
    chart.data.datasets[PROFILE_DS].pointRadius = on ? 4 : 0;
    chart.data.datasets[PROFILE_DS].pointHitRadius = on ? 30 : 0;
    chart.data.datasets[PROFILE_DS].dragData = !!on;
    chart.update('none');
}

/* ---------------------------------------------------------------------------
   Overview profile operations
--------------------------------------------------------------------------- */

  function updateProfile(id)
  {
      selected_profile = id;
      selected_profile_name = profiles[id].name;
      graph.profile.data = profiles[id].data;
      if (state != "RUNNING" && state != "PAUSED") {
          graph.live.data = [];
      }
      syncChartData();
      updateAxis();
      updateProfileTable();
      renderProfiles();
  }

  function adoptProfile(name)
  {
      if (!name) { return; }
      for (var i = 0; i < profiles.length; i++) {
          if (profiles[i].name == name) {
              selected_profile_name = name;
              updateProfile(i);
              if ($('e2')) { $('e2').value = String(i); }
              return;
          }
      }
  }

function deleteProfile()
{
    var profile = { "type": "profile", "data": "", "name": selected_profile_name };
    var delete_struct = { "cmd": "DELETE", "profile": profile };

    ws_storage.send(JSON.stringify(delete_struct));
    ws_storage.send('GET');

    if (profiles.length > 0) { selected_profile_name = profiles[0].name; }

    state="IDLE";
    hide($('profile_editor'));
    $('e2').value = String(0);
    setEditMode(false);
    syncChartData();
    updateAxis();
    chart.resize();
}

function slopeIcon(slope) {
    if (slope == "up") { return "bi-arrow-up-circle"; }
    if (slope == "down") { return "bi-arrow-down-circle"; }
    return "bi-arrow-right-circle";
}

function updateProfileTable()
{
    var dps = 0;
    var slope = "";
    var color = "";

    var html = '<h3>Schedule Points</h3><div class="table-responsive" style="scroll: none"><table class="table table-striped">';
        html += '<tr><th style="width: 50px">#</th><th>Target Time in ' + time_scale_long+ '</th><th>Target Temperature in °'+temp_scale_display+'</th><th>Slope in &deg;'+temp_scale_display+'/'+time_scale_slope+'</th><th>Action</th></tr>';

    for(var i=0; i<graph.profile.data.length;i++)
    {
        if (i>=1) dps =  ((graph.profile.data[i][1]-graph.profile.data[i-1][1])/(graph.profile.data[i][0]-graph.profile.data[i-1][0]) * 10) / 10;
        if (dps  > 0) { slope = "up";     color="rgba(206, 5, 5, 1)"; } else
        if (dps  < 0) { slope = "down";   color="rgba(23, 108, 204, 1)"; dps *= -1; } else
        if (dps == 0) { slope = "right";  color="grey"; }

        html += '<tr><td><h4>' + (i+1) + '</h4></td>';
        html += '<td><input type="text" class="form-control point-input" id="profiletable-0-'+i+'" value="'+ timeProfileFormatter(graph.profile.data[i][0],true) + '" /></td>';
        html += '<td><input type="text" class="form-control point-input" id="profiletable-1-'+i+'" value="'+ graph.profile.data[i][1] + '" /></td>';
        html += '<td><div class="input-group"><span class="bi ' + slopeIcon(slope) + ' input-group-text ds-trend" style="background: '+color+'"></span><input type="text" class="form-control ds-input ds-slope" readonly value="' + formatDPS(dps) + '" /></div></td>';
        html += '<td><div class="btn-group btn-group-sm">';
        html += '<button type="button" class="btn btn-outline-secondary" onclick="newPointAt(' + i + ')" title="Add point after"><i class="bi bi-plus"></i></button>';
        html += '<button type="button" class="btn btn-outline-danger" onclick="delPointAt(' + i + ')" title="Delete point"><i class="bi bi-dash-lg"></i></button>';
        html += '</div></td></tr>';
    }

    html += '</table></div>';

    $('profile_table').innerHTML = html;
}

function timeProfileFormatter(val, down) {
    var rval = val
    switch(time_scale_profile){
        case "m":
            if (down) {rval = val / 60;} else {rval = val * 60;}
            break;
        case "h":
            if (down) {rval = val / 3600;} else {rval = val * 3600;}
            break;
    }
    return Math.round(rval);
}

function formatDPS(val) {
    var tval = val;
    if (time_scale_slope == "m") {
        tval = val * 60;
    }
    if (time_scale_slope == "h") {
        tval = (val * 60) * 60;
    }
    return Math.round(tval);
}

function hazardTemp(){

    if (temp_scale == "f") {
        return (1500 * 9 / 5) + 32
    }
    else {
        return 1500
    }
}

function timeTickFormatter(val) {
    var max = this.max;
    if(max>3600) {
        return Math.floor(val/3600);
    }
    if(max>60) {
        return Math.floor(val/60);
    }
    return val;
}

function runTask()
{
    var cmd =
    {
        "cmd": "RUN",
        "profile": profiles[selected_profile]
    }

    graph.live.data = [];
    syncChartData();
    updateAxis();

    clear_persisted_all();

    ws_control.send(JSON.stringify(cmd));

}

function runTaskSimulation()
{
    var cmd =
    {
        "cmd": "SIMULATE",
        "profile": profiles[selected_profile]
    }

    graph.live.data = [];
    syncChartData();
    updateAxis();

    clear_persisted_all();

    ws_control.send(JSON.stringify(cmd));

}

function abortTask()
{
    var cmd = {"cmd": "STOP"};
    ws_control.send(JSON.stringify(cmd));
}

function enterNewMode()
{
    state="EDIT"
    show($('profile_editor'));
    $('form_profile_name').value = '';
    $('form_profile_name').setAttribute('placeholder', 'Please enter a name');
    graph.profile.data = [];
    syncChartData();
    updateAxis();
    updateProfileTable();
    show($('profile_table'));
    showTab('profiles');
}

function enterEditMode(i)
{
    if (i === undefined) { i = selected_profile; }
    var prof = profiles[i];
    if (!prof) { return; }
    state="EDIT";
    show($('profile_editor'));
    $('form_profile_name').value = prof.name;
    graph.profile.data = prof.data;
    syncChartData();
    updateAxis();
    updateProfileTable();
    show($('profile_table'));
    showTab('profiles');
}

function leaveEditMode()
{
    // keep the selection unchanged unless this was a brand new schedule
    // (or a rename), in which case adopt the name that was just worked on.
    var name = $('form_profile_name').value;
    var exists = false;
    for (var i = 0; i < profiles.length; i++) {
        if (profiles[i].name === name) { exists = true; break; }
    }
    if (!exists) { selected_profile_name = name; }
    ws_storage.send('GET');
    state="IDLE";
    hide($('profile_editor'));
    hide($('profile_table'));
    setEditMode(false);
    syncChartData();
    updateAxis();
    renderProfiles();
}

function newPoint()
{
    var pointx;
    if(graph.profile.data.length > 0)
    {
        pointx = parseInt(graph.profile.data[graph.profile.data.length-1][0])+15;
    }
    else
    {
        pointx = 0;
    }
    graph.profile.data.push([pointx, Math.floor((Math.random()*230)+25)]);
    syncChartData();
    updateAxis();
    updateProfileTable();
}

function delPoint()
{
    graph.profile.data.splice(-1,1)
    syncChartData();
    updateAxis();
    updateProfileTable();
}

function delPointAt(i)
{
    graph.profile.data.splice(i,1)
    syncChartData();
    updateAxis();
    updateProfileTable();
}

function newPointAt(i)
{
    var pointx;
    var pointy;
    if (graph.profile.data.length > 0) {
        var cur = graph.profile.data[i];
        var next = graph.profile.data[i+1];
        pointx = next ? parseInt((cur[0] + next[0]) / 2) : parseInt(cur[0]) + 15;
        pointy = cur[1];
    } else {
        pointx = 0;
        pointy = 25;
    }
    graph.profile.data.splice(i+1, 0, [pointx, pointy]);
    syncChartData();
    updateAxis();
    updateProfileTable();
}

function toggleTable()
{
    var t = $('profile_table');
    if(t.style.display == 'none')
    {
        show(t);
    }
    else
    {
        hide(t);
    }
}

function toggleLive()
{
    graph.live.visible = !graph.live.visible;
    chart.data.datasets[LIVE_DS].hidden = !graph.live.visible;
    chart.update('none');
}

function saveProfile()
{
    var name = $('form_profile_name').value;
    var data = [];
    var last = -1;

    for(var i=0; i<graph.profile.data.length;i++)
    {
        var p = graph.profile.data[i];
        if(p[0] > last)
        {
          data.push([p[0], p[1]]);
        }
        else
        {
          showGrowl("<i class=\"bi bi-exclamation-triangle-fill\"></i> <b>ERROR 88:</b><br/>An oven is not a time-machine", 'error', 5000);
          return false;
        }

        last = p[0];
    }

    var profile = { "type": "profile", "data": data, "name": name }
    var put = { "cmd": "PUT", "profile": profile }

    ws_storage.send(JSON.stringify(put));

    leaveEditMode();
}

function overwriteProfile()
{
    saveProfile();
}

function populateProfileSelect()
{
    var sel = $('e2');
    sel.innerHTML = '';
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.text = 'Select Profile';
    sel.appendChild(placeholder);
    for (var i = 0; i < profiles.length; i++) {
        var opt = document.createElement('option');
        opt.value = String(i);
        opt.text = profiles[i].name;
        sel.appendChild(opt);
    }
}

/* ---------------------------------------------------------------------------
   Profiles tab
--------------------------------------------------------------------------- */

function apiPost(obj, cb) {
    fetch('/api', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(obj)
    })
    .then(function(r) { return r.json(); })
    .then(cb)
    .catch(function(err) {
        showGrowl('API error: ' + err, 'error', 5000);
    });
}

function pad2(n) {
    return n < 10 ? '0' + n : '' + n;
}

function isoLocal(d) {
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + 'T' +
        pad2(d.getHours()) + ':' + pad2(d.getMinutes());
}

function scheduleProfile(i) {
    if (!profiles.length || !profiles[i]) {
        showGrowl('<i class="bi bi-exclamation-triangle-fill"></i> <b>ERROR 93:</b><br/>No schedule selected.', 'error', 5000);
        return;
    }
    selected_profile = i;
    $('schedule_profile_name').innerHTML = profiles[i].name;
    $('schedule_datetime').value = isoLocal(new Date(Date.now() + 60 * 60 * 1000));
    var modal = new bootstrap.Modal($('scheduleModal'));
    modal.show();
}

function setScheduleOffset(minutes) {
    $('schedule_datetime').value = isoLocal(new Date(Date.now() + minutes * 60 * 1000));
}

function submitSchedule() {
    var dt = $('schedule_datetime').value;
    if (!dt) {
        showGrowl('<i class="bi bi-exclamation-triangle-fill"></i> <b>ERROR 90:</b><br/>Please pick a date and time.', 'error', 5000);
        return;
    }
    apiPost({
        cmd: 'schedule',
        profile: profiles[selected_profile].name,
        start_time: dt
    }, function(resp) {
        if (resp.success) {
            showGrowl('Firing scheduled for <b>' + new Date(resp.start_time * 1000).toLocaleString() + '</b>', 'success', 5000);
            var modal = bootstrap.Modal.getInstance($('scheduleModal'));
            if (modal) { modal.hide(); }
            listScheduledRuns();
        } else {
            showGrowl('<i class="bi bi-exclamation-triangle-fill"></i> <b>ERROR 91:</b><br/>' + (resp.error || 'Could not schedule firing.'), 'error', 5000);
        }
    });
}

function scheduleTime(entry) {
    return new Date(entry.start_time * 1000).toLocaleString();
}

function formatCountdown(secs) {
    secs = Math.max(0, Math.floor(secs));
    var d = Math.floor(secs / 86400);
    var h = Math.floor((secs % 86400) / 3600);
    var m = Math.floor((secs % 3600) / 60);
    var s = secs % 60;
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    return d + ' ' + pad(h) + ':' + pad(m) + ':' + pad(s);
}

var pending_schedules = [];
var schedule_timer = null;

function startScheduleTimer() {
    if (schedule_timer) { return; }
    schedule_timer = setInterval(function() {
        if (pending_schedules.length === 0) { return; }
        var now = Date.now() / 1000;
        for (var i = 0; i < pending_schedules.length; i++) {
            var r = pending_schedules[i];
            var el = document.getElementById('schedule-countdown-' + r.id);
            if (el) {
                el.textContent = r.start_time - now > 0
                    ? formatCountdown(r.start_time - now)
                    : 'starting...';
            }
        }
    }, 1000);
}

function listScheduledRuns() {
    var list = $('scheduled_runs_list');
    if (!list) { return; }
    apiPost({ cmd: 'list_schedules' }, function(resp) {
        var runs = (resp && resp.schedules) ? resp.schedules.filter(function(r) { return !r.fired; }) : [];
        if (runs.length === 0) {
            list.innerHTML = '<p class="ds-empty">No runs scheduled.</p>';
            pending_schedules = [];
            return;
        }
        pending_schedules = runs;
        startScheduleTimer();
        var html = '';
        for (var i = 0; i < runs.length; i++) {
            var r = runs[i];
            var left = r.start_time - (Date.now() / 1000);
            html += '<div class="profile-row">'
                + '<div class="profile-info">'
                + '<div class="profile-name">' + r.profile + ' <span class="badge text-bg-primary">pending</span></div>'
                + '<div class="profile-meta">Starts ' + scheduleTime(r) + ' &middot; in <span id="schedule-countdown-' + r.id + '">' + (left > 0 ? formatCountdown(left) : 'starting...') + '</span></div>'
                + '</div>'
                + '<div class="btn-group">'
                + '<button type="button" class="btn btn-outline-danger btn-sm" onclick="cancelSchedule(\'' + r.id + '\')"><i class="bi bi-x-lg"></i> Cancel</button>'
                + '</div></div>';
        }
        list.innerHTML = html;
    });
}

function cancelSchedule(id) {
    apiPost({ cmd: 'cancel_schedule', id: id }, function(resp) {
        if (resp.success) {
            showGrowl('Scheduled run cancelled.', 'success', 5000);
        } else {
            showGrowl('<i class="bi bi-exclamation-triangle-fill"></i> <b>ERROR 92:</b><br/>' + (resp.error || 'Could not cancel schedule.'), 'error', 5000);
        }
        listScheduledRuns();
    });
}

function profileDuration(data) {
    var secs = 0;
    if (data.length > 0) {
        secs = parseInt(data[data.length-1][0]);
    }
    return new Date(secs * 1000).toISOString().substr(11, 8);
}

function renderProfiles()
{
    var list = $('profiles_list');
    if (!list) { return; }
    var html = '';
    if (profiles.length === 0) {
        html = '<p class="ds-empty">No schedules saved yet. Create one with <i class="bi bi-file-earmark-plus"></i> New Schedule.</p>';
    }
    for (var i = 0; i < profiles.length; i++) {
        var p = profiles[i];
        var current = (p.name === selected_profile_name);
        var running = (p.name === running_profile_name);
        html += '<div class="profile-row">'
            + '<div class="profile-info">'
            + '<div class="profile-name">' + p.name
            + (running ? ' <span class="badge text-bg-danger">running</span>' : '')
            + (current ? ' <span class="badge text-bg-success">selected</span>' : '') + '</div>'
            + '<div class="profile-meta">' + p.data.length + ' points &middot; duration ' + profileDuration(p.data) + '</div>'
            + '</div>'
            + '<div class="btn-group">'
            + '<button type="button" class="btn btn-success btn-sm" onclick="selectProfile(' + i + ', true)"><i class="bi bi-play-fill"></i> Run</button>'
            + '<button type="button" class="btn btn-outline-secondary btn-sm" onclick="scheduleProfile(' + i + ')"><i class="bi bi-calendar-plus"></i> Schedule</button>'
            + '<button type="button" class="btn btn-outline-secondary btn-sm" onclick="editProfile(' + i + ')"><i class="bi bi-pencil"></i> Edit</button>'
            + '<button type="button" class="btn btn-outline-secondary btn-sm" onclick="selectProfile(' + i + ', null)"><i class="bi bi-trash"></i> Delete</button>'
            + '</div>'
            + '</div>';
    }
    list.innerHTML = html;
    listScheduledRuns();
}

function selectProfile(i, run)
{
    selected_profile = i;
    if ($('e2')) { $('e2').value = String(i); }
    updateProfile(i);
    renderProfiles();
    if (run === true) {
        runTask();
    } else if (run === false) {
        editProfile(i);
    } else {
        var d = new bootstrap.Modal($('delProfileModal'));
        d.show();
    }
}

function editProfile(i)
{
    enterEditMode(i);
}

/* ---------------------------------------------------------------------------
   Tuning
--------------------------------------------------------------------------- */

function rnd(number) {
  return Number(number).toFixed(2);
}

function average(field, minutes, data) {
  if (data.length === 0) {
    return 0;
  }
  var t = data[data.length - 1].time;
  var oldest = t - (60 * minutes);
  var sum = 0;
  var count = 0;
  for (var i = 0; i < data.length; i++) {
    if (data[i].time >= oldest) {
      sum += data[i][field];
      count++;
    }
  }
  return count ? sum / count : 0;
}

function percent_catching_up(data) {
  var slip = 0;
  var total = 0;
  for (var i = 0; i < data.length; i++) {
    var d = data[i];
    total += d.timeDelta;
    if (d.catching_up) {
      slip += d.timeDelta;
    }
  }
  return total ? slip / total * 100 : 0;
}

function clock_tick(val) {
  return new Date(val * 1000).toLocaleTimeString([], { hour12: false });
}

function make_line_chart(id) {
  var tc = themeColors();
  return new Chart($(id), {
    type: 'line',
    data: { datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', intersect: false },
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 }, color: tc.axis } },
        tooltip: {
          enabled: true,
          callbacks: {
            title: function(items) {
              if (items.length > 0) { return unix_to_yymmdd_hhmmss(items[0].parsed.x); }
              return '';
            },
            label: function(context) {
              return context.dataset.label + ': ' + context.parsed.y;
            }
          }
        },
        dragData: false
      },
      scales: {
        x: {
          type: 'linear',
          ticks: { maxTicksLimit: 8, maxRotation: 0, callback: clock_tick, color: tc.axisDim },
          grid: { color: tc.gridDim }
        },
        y: {
          ticks: { color: tc.axisDim },
          grid: { color: tc.gridDim }
        }
      }
    }
  });
}

function create_charts() {
  var tc = themeColors();
  charts.temps = make_line_chart('chart-temps');
  charts.temps.data.datasets = [
    {
      label: 'target',
      data: [],
      dragData: false,
      order: 2,
      borderColor: '#9cb310',
      backgroundColor: '#9cb310',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0
    },
    {
      label: 'temp',
      data: [],
      dragData: false,
      order: 1,
      borderColor: tc.live,
      backgroundColor: tc.live,
      borderWidth: 2,
      pointRadius: 0,
      tension: 0
    },
    {
      label: 'catchup',
      type: 'scatter',
      data: [],
      dragData: false,
      order: 3,
      showLine: false,
      pointRadius: 3,
      pointBackgroundColor: '#6ec6ff'
    }
  ];

  charts.error = make_line_chart('chart-error');
  charts.error.data.datasets = [line_dataset('error', '#ff8a80')];

  charts.heat = make_line_chart('chart-heat');
  charts.heat.data.datasets = [line_dataset('heat', '#ffb14e')];

  charts.p = make_line_chart('chart-p');
  charts.p.data.datasets = [line_dataset('p', '#6ec6ff')];

  charts.i = make_line_chart('chart-i');
  charts.i.data.datasets = [line_dataset('i', '#6ec6ff')];

  charts.d = make_line_chart('chart-d');
  charts.d.data.datasets = [line_dataset('d', '#6ec6ff')];

  applyChartTheme();
}

function line_dataset(name, color) {
  return {
    label: name,
    data: [],
    dragData: false,
    borderColor: color,
    backgroundColor: color,
    borderWidth: 2,
    pointRadius: 0,
    tension: 0
  };
}

function set_chart_data(chart, rows, key) {
  var data = [];
  for (var i = 0; i < rows.length; i++) {
    data.push({ x: rows[i].time, y: rows[i][key] });
  }
  chart.data.datasets[0].data = data;
  chart.update('none');
}

function drawall(data) {
  draw_temps(data);
  draw_error(data);
  draw_heat(data);
  draw_p(data);
  draw_i(data);
  draw_d(data);
}

function draw_temps(data) {
  var i;
  var setpoint = [];
  var ispoint = [];
  var catchup = [];
  for (i = 0; i < data.length; i++) {
    var d = data[i];
    setpoint.push({ x: d.time, y: d.setpoint });
    ispoint.push({ x: d.time, y: d.ispoint });
    if (d.catchingup !== null && d.catchingup !== undefined) {
      catchup.push({ x: d.time, y: d.catchingup });
    }
  }
  charts.temps.data.datasets[0].data = setpoint;
  charts.temps.data.datasets[1].data = ispoint;
  charts.temps.data.datasets[2].data = catchup;
  charts.temps.update('none');
}

function draw_error(data) {
  set_chart_data(charts.error, data, 'err');
}

function draw_heat(data) {
  set_chart_data(charts.heat, data, 'out');
}

function draw_p(data) {
  set_chart_data(charts.p, data, 'p');
}

function draw_i(data) {
  set_chart_data(charts.i, data, 'i');
}

function draw_d(data) {
  set_chart_data(charts.d, data, 'd');
}

function unix_to_yymmdd_hhmmss(t) {
  var date = new Date(t * 1000);
  var newd = new Date(date.getTime() - date.getTimezoneOffset()*60000);
  return newd.toISOString().replace("T"," ").substring(0, 19);
}

function latest(n) {
  return all.slice(-n).reverse();
}

var window_minutes = 2;
var window_all = true;

function windowed_data() {
  if (window_all || all.length === 0) { return all; }
  var last = all[all.length - 1].time;
  var cutoff = last - window_minutes * 60;
  var out = [];
  for (var i = 0; i < all.length; i++) {
    if (all[i].time >= cutoff) { out.push(all[i]); }
  }
  return out;
}

function tune_window_change() {
  var slider = document.getElementById('window_slider');
  var v = parseInt(slider.value, 10);
  var max = parseInt(slider.max, 10);
  var label = document.getElementById('window_label');
  if (v >= max) {
    window_all = true;
    label.innerHTML = 'All';
  } else {
    window_all = false;
    window_minutes = v;
    label.innerHTML = v + ' min';
  }
  drawall(windowed_data());
}

function create_table(data) {
  table = new Tabulator("#state-table", {
    height: 300,
    data: data,
    layout: "fitColumns",
    columns: [
      { title: "DateTime", field: "datetime" },
      { title: "Target", field: "setpoint" },
      { title: "Temp", field: "ispoint" },
      { title: "Error", field: "err" },
      { title: "P", field: "p" },
      { title: "I", field: "i" },
      { title: "D", field: "d" },
      { title: "Heat", field: "out" },
      { title: "Catching Up", field: "catching_up" },
      { title: "Time Delta", field: "timeDelta" }
    ]
  });
  table.on("tableBuilt", function() {
    tableBuilt = true;
    if (all.length > 0) {
      table.replaceData(latest(20));
    }
  });
}

function csv_string() {
  table.download("csv", "kiln-state.csv");
}

/* ---------------------------------------------------------------------------
   Init
--------------------------------------------------------------------------- */

function init()
{
    if(!("WebSocket" in window))
    {
        showGrowl("Your browser does not support WebSockets. Please use a modern browser.", 'error', 0);
        return;
    }

    createChart();

    var icon = $('theme_icon');
    if (icon) {
        icon.className = currentTheme() === 'light' ? 'bi bi-sun' : 'bi bi-moon-stars';
    }

    // tab switching
    var links = document.querySelectorAll('.nav-link[data-tab]');
    for (var li = 0; li < links.length; li++) {
        (function(link) {
            link.addEventListener('click', function() {
                var tab = link.getAttribute('data-tab');
                showTab(tab);
                history.replaceState(null, '', '#' + tab);
            });
        })(links[li]);
    }
    window.addEventListener('hashchange', openTabFromHash);

    $('window_slider').addEventListener('input', tune_window_change);

    $('e2').addEventListener('change', function(e)
    {
        var val = this.value;
        if (val !== '') {
            updateProfile(parseInt(val));
        }
    });

    // link the schedule table back to the graph
    $('profile_table').addEventListener('change', function(e)
    {
        var t = e.target;
        if (!t.id || t.id.indexOf('profiletable-') !== 0) { return; }
        var id = t.id;
        var value = parseInt(t.value);
        var fields = id.split("-");
        var col = parseInt(fields[1]);
        var row = parseInt(fields[2]);

        if (graph.profile.data.length > 0) {
            if (col == 0) {
                graph.profile.data[row][col] = timeProfileFormatter(value,false);
            }
            else {
                graph.profile.data[row][col] = value;
            }
            syncChartData();
            updateAxis();
        }
        updateProfileTable();
    });

    // Status Socket ////////////////////////////////

    ws_status.onopen = function()
    {
        console.log("Status Socket has been opened");
        socket_opened('status');
    };

    ws_status.onclose = function()
    {
        showGrowl("<i class=\"bi bi-exclamation-triangle-fill\"></i> <b>ERROR 1:</b><br/>Status Websocket not available", 'error', 5000);
        socket_closed('status');
    };

    ws_status.onmessage = function(e)
    {
        var x = JSON.parse(e.data);

        if (x.type == "backlog")
        {
            // the backlog is the first message sent to a new client, so it
            // identifies the run already in progress. adopt it without
            // clearing stored data, so a page refresh mid-run is not lost.
            run_started = x.run_started || null;

            if (x.profile)
            {
                backlog_profile_name = typeof x.profile == 'object' ? x.profile.name : x.profile;
                adoptProfile(backlog_profile_name);
            }

            for (var j = 0; j < x.log.length; j++) {
                var v = x.log[j];
                graph.live.data.push([v.runtime, v.temperature]);
                syncChartData();
                updateAxis();
            }
        }

        // a new run_started means a fresh firing has begun, no matter
        // how it was started (start button, scheduled run, api command,
        // automatic restart). wipe the stored details data and load the
        // reported profile so the main page reflects the actual run.
        if (x.run_started && x.run_started !== run_started) {
            run_started = x.run_started;
            clear_persisted_all();
            if (x.profile) {
                adoptProfile(typeof x.profile == 'object' ? x.profile.name : x.profile);
            }
        }

        // track which schedule is running so the Saved Schedules list
        // can show a status. re-render only when it changes.
        running_profile_name = (x.state == "RUNNING" || x.state == "PAUSED") ? (x.profile || null) : null;
        if (running_profile_name !== running_profile_name_last) {
            running_profile_name_last = running_profile_name;
            if (!running_profile_name) { backlog_profile_name = null; }
            renderProfiles();
        }

        if(state!="EDIT")
        {
            state = x.state;
            if (state!=state_last)
            {
                if(state_last == "RUNNING" && state != "PAUSED" )
                {
                    showGrowl("<i class=\"bi bi-exclamation-triangle-fill\"></i> <b>Run completed</b>", 'success', 0);
                }
            }

            if(state=="RUNNING")
            {
                hide($('nav_start'));
                show($('nav_stop'));

                graph.live.data.push([x.runtime, x.temperature]);
                syncChartData();
                updateAxis();

                var left = parseInt(x.totaltime-x.runtime);
                var eta = new Date(left * 1000).toISOString().substr(11, 8);

                $('eta').innerHTML = eta;
            }
            else
            {
                show($('nav_start'));
                hide($('nav_stop'));
                $('eta').innerHTML = '--:--:--';
            }

            state_last = state;

        }

        // tuning feed
        if (x.pidstats && x.pidstats.time) {
            x.pidstats["datetime"] = unix_to_yymmdd_hhmmss(x.pidstats.time);
            x.pidstats.err = x.pidstats.err * -1;
            x.pidstats.out = x.pidstats.out * 100;
            x.pidstats.catching_up = x.catching_up;
            if (x.catching_up == true) {
                x.pidstats.catchingup = x.pidstats.ispoint;
            }
            all.push(x.pidstats);
            persist_all();

            if (detailsInited && tableBuilt) {
                table.replaceData(latest(20));
                drawall(windowed_data());
            }

            $("error-current").innerHTML = rnd(x.pidstats.err);
            $("error-1min").innerHTML = rnd(average("err", 1, all));
            $("error-5min").innerHTML = rnd(average("err", 5, all));
            $("error-15min").innerHTML = rnd(average("err", 15, all));
            $("temp").innerHTML = rnd(x.pidstats.ispoint);
            $("target").innerHTML = rnd(x.pidstats.setpoint);
            $("heat-pct").innerHTML = rnd(x.pidstats.out);
            $("catching-up").innerHTML = rnd(percent_catching_up(all));
        }

        $("raw_state").innerHTML = "<pre>" + JSON.stringify(x, null, 2) + "</pre>";
    };

    // Config Socket /////////////////////////////////

    ws_config.onopen = function()
    {
        ws_config.send('GET');
        socket_opened('config');
    };

    ws_config.onclose = function()
    {
        socket_closed('config');
    };

    ws_config.onmessage = function(e)
    {
        var x = JSON.parse(e.data);
        temp_scale = x.temp_scale;
        time_scale_slope = x.time_scale_slope;
        time_scale_profile = x.time_scale_profile;
        kwh_rate = x.kwh_rate;
        currency_type = x.currency_type;

        if (temp_scale == "c") {temp_scale_display = "C";} else {temp_scale_display = "F";}

        switch(time_scale_profile){
            case "s":
                time_scale_long = "Seconds";
                break;
            case "m":
                time_scale_long = "Minutes";
                break;
            case "h":
                time_scale_long = "Hours";
                break;
        }

    }

    // Control Socket ////////////////////////////////

    ws_control.onopen = function()
    {
        socket_opened('control');
    };

    ws_control.onclose = function()
    {
        socket_closed('control');
    };

    ws_control.onmessage = function(e)
    {
        var x = JSON.parse(e.data);
        graph.live.data.push([x.runtime, x.temperature]);
        syncChartData();
        updateAxis();
    }

    // Storage Socket ///////////////////////////////

    ws_storage.onopen = function()
    {
        ws_storage.send('GET');
        socket_opened('storage');
    };

    ws_storage.onclose = function()
    {
        socket_closed('storage');
    };

    ws_storage.onmessage = function(e)
    {
        var message = JSON.parse(e.data);

        if(message.resp)
        {
            if(message.resp == "FAIL")
            {
                if (confirm('Overwrite?'))
                {
                    message.force=true;
                    ws_storage.send(JSON.stringify(message));
                }
            }

            return;
        }

        //the message is an array of profiles
        //FIXME: this should be better, maybe a {"profiles": ...} container?
        profiles = message;
        var valid_profile_names = profiles.map(function(a) {return a.name;});
        // if a run is in progress, keep the currently running profile
        // selected instead of defaulting to the first one
        var running_name = running_profile_name || backlog_profile_name;
        if (running_name && valid_profile_names.indexOf(running_name) !== -1) {
            selected_profile_name = running_name;
        }
        // check if current selected value is a valid profile name
        // if not, update with first available profile name
        if (
          valid_profile_names.length > 0 &&
          valid_profile_names.indexOf(selected_profile_name) === -1
        ) {
          selected_profile = 0;
          selected_profile_name = valid_profile_names[0];
        }

        populateProfileSelect();

        var matched = false;
        for (var i=0; i<profiles.length; i++)
        {
            if (profiles[i].name == selected_profile_name)
            {
                selected_profile = i;
                $('e2').value = String(i);
                updateProfile(i);
                matched = true;
            }
        }

        if (!matched && profiles.length > 0) {
            selected_profile = 0;
            $('e2').value = String(0);
            updateProfile(0);
        }

        renderProfiles();
    };
}

init();
openTabFromHash();
