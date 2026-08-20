/* ═══════════════════════════════════════════════════════════════════════════
   Pottery Firing Schedule Generator tab ── removable feature module

   Generates multi-segment kiln firing schedules entirely in the browser.
   Segment structure, ramp rates, thickness-based candling holds, and
   per-cone peak temperatures follow standard ceramic practice (Orton
   cone data, quartz inversion at 573 degC). No network calls are made.

   The pure algorithm functions live at the top level (sg prefix) so the
   test suite can extract and execute them (see Test/test_frontend_
   schedule_generator.py). All UI code lives in the closure below.

   This file injects its own nav item and tab section, so index.html only
   needs the single <script> tag that loads it (after kiln-controller.js,
   so the TABS list and tab-click bindings already exist).

   TO UNINSTALL: delete this file and remove the script tag from
   public/index.html.
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── pure algorithm (top-level for testability) ─────────────────────────── */

var SG_CONES = ['06', '05', '04', '03', '02', '01', '1', '2', '3', '4', '5',
                '6', '7', '8', '9', '10'];

/* peak temperature (degC) per cone */
var SG_CONE_PEAKS_C = {
    '06': 999, '05': 1031, '04': 1063, '03': 1101, '02': 1120,
    '01': 1137, '1': 1154, '2': 1162, '3': 1168, '4': 1186,
    '5': 1196, '6': 1222, '7': 1240, '8': 1263, '9': 1280, '10': 1305
};

function sgCToF(c) { return c * 9 / 5 + 32; }

function sgRateCToF(r) { return r * 9 / 5; }

/* candling hold at 120 degC based on thickest piece in the load */
function sgCandlingHoldMin(mm) {
    if (mm >= 20) { return 60; }
    if (mm >= 12) { return 30; }
    return 0;
}

function sgGenerateSchedule(cone, firingType, thicknessMm) {
    var peak = SG_CONE_PEAKS_C[cone];
    var segments = [
        { from: 20,  to: 120,       rate: 50,  hold: sgCandlingHoldMin(thicknessMm),
          note: 'Steam & mechanical water release' },
        { from: 120, to: 500,       rate: 80,  hold: 0,
          note: 'Chemical water & organic burnout' },
        { from: 500, to: 600,       rate: 60,  hold: 0,
          note: 'Quartz inversion zone \u2014 573\u00b0C critical' }
    ];
    if (firingType === 'bisque') {
        segments.push({ from: 600, to: peak, rate: 100, hold: 20,
                        note: 'Final bisque temperature' });
    } else {
        segments.push({ from: 600, to: peak - 100, rate: 120, hold: 0,
                        note: 'Approach peak temperature' });
        segments.push({ from: peak - 100, to: peak, rate: 40, hold: 15,
                        note: 'Final approach & soak' });
    }

    var warnings = [];
    if (thicknessMm > 20) {
        warnings.push({
            severity: 'warning',
            message: 'Very thick pieces (>20mm) need additional soaking time and may require a candling segment of 2\u20134 hours.'
        });
    }

    var total = 0;
    for (var i = 0; i < segments.length; i++) {
        var s = segments[i];
        total += (s.to - s.from) / s.rate + s.hold / 60;
    }

    return {
        segments: segments,
        peak_temp_c: peak,
        total_hours: Math.round(total * 10) / 10,
        segment_count: segments.length,
        warnings: warnings
    };
}

/* ── UI ─────────────────────────────────────────────────────────────────── */

(function () {
    'use strict';

    /* register the tab (kiln-controller.js has already defined TABS) */
    if (typeof TABS !== 'undefined' && TABS.indexOf('schedgen') === -1) {
        TABS.push('schedgen');
    }

    function $(id) { return document.getElementById(id); }
    var lastValues = null;

    function inject() {
        var nav = document.querySelector('.navbar-nav');
        if (!nav || $('tab-schedgen')) { return; }  // already injected

        var li = document.createElement('li');
        li.className = 'nav-item';
        li.innerHTML = '<a class="nav-link" data-tab="schedgen" href="#schedgen">' +
                       '<i class="bi bi-box-seam"></i>&nbsp; Schedule Gen</a>';
        nav.appendChild(li);

        /* init() already bound the pre-existing nav links, so bind ours now */
        li.querySelector('a').addEventListener('click', function () {
            showTab('schedgen');
            history.replaceState(null, '', '#schedgen');
        });

        var section = document.createElement('section');
        section.id = 'tab-schedgen';
        section.className = 'tab-pane';
        section.style.display = 'none';
        section.innerHTML =
            '<div class="panel panel-default">' +
            ' <div class="panel-heading"><strong>Pottery Firing Schedule Generator</strong>' +
            '  <span class="text-muted fw-normal small">&nbsp;runs locally in your browser</span></div>' +
            ' <div class="panel-body">' +
            '  <p class="text-muted mb-2">Generates a planning schedule for bisque or glaze firings with critical holds and quartz-inversion slowdowns.</p>' +
            '  <div class="row g-2">' +
            '   <div class="col-6 col-md-4"><label class="form-label small mb-1">Target Cone</label>' +
            '    <select id="sg_cone" class="form-select form-select-sm"></select></div>' +
            '   <div class="col-6 col-md-4"><label class="form-label small mb-1">Firing Type</label>' +
            '    <select id="sg_type" class="form-select form-select-sm">' +
            '     <option value="bisque">Bisque</option>' +
            '     <option value="glaze" selected>Glaze</option></select></div>' +
            '   <div class="col-6 col-md-4"><label class="form-label small mb-1">Thickest Piece (mm)</label>' +
            '    <input id="sg_thickness" type="number" min="1" step="1" value="8" class="form-control form-control-sm" />' +
            '    <div class="small text-muted" id="sg_thickness_in"></div></div>' +
            '  </div>' +
            '  <div class="btn-group btn-group-sm mt-3">' +
            '   <button id="sg_calculate" type="button" class="btn btn-success"><i class="bi bi-magic"></i> Generate Schedule</button>' +
            '  </div>' +
            '  <div id="sg_error" class="alert alert-danger mt-3 mb-0" style="display:none"></div>' +
            '  <div id="sg_results" style="display:none">' +
            '   <div id="sg_summary" class="d-flex flex-wrap gap-3 mt-3"></div>' +
            '   <div id="sg_warnings"></div>' +
            '   <div class="table-responsive mt-2"><table class="table table-sm table-striped align-middle mb-0">' +
            '    <thead><tr><th>#</th><th>From</th><th>To</th><th>Rate</th><th>Hold</th><th>Note</th></tr></thead>' +
            '    <tbody id="sg_segments"></tbody></table></div>' +
            '   <div class="input-group input-group-sm mt-3" style="max-width: 480px">' +
            '    <span class="input-group-text">Save as Schedule</span>' +
            '    <input id="sg_name" type="text" class="form-control" />' +
            '    <button id="sg_save" type="button" class="btn btn-success"><i class="bi bi-save"></i> Save</button>' +
            '    <button id="sg_cancel" type="button" class="btn btn-outline-secondary"><i class="bi bi-x-lg"></i> Cancel</button>' +
            '   </div>' +
            '   <div class="small text-muted mt-1">Saved schedules appear on the Schedules tab. Always verify against witness cones.</div>' +
            '  </div>' +
            ' </div>' +
            '</div>';

        document.querySelector('.container-fluid.py-3').appendChild(section);

        var coneSel = $('sg_cone');
        for (var i = 0; i < SG_CONES.length; i++) {
            var opt = document.createElement('option');
            opt.value = SG_CONES[i];
            opt.textContent = 'Cone ' + SG_CONES[i];
            if (SG_CONES[i] === '6') { opt.selected = true; }
            coneSel.appendChild(opt);
        }

        $('sg_thickness').addEventListener('input', updateInches);
        $('sg_calculate').addEventListener('click', calculate);
        $('sg_save').addEventListener('click', saveAsSchedule);
        $('sg_cancel').addEventListener('click', cancelSchedule);
        updateInches();
    }

    function updateInches() {
        var mm = parseFloat($('sg_thickness').value);
        var el = $('sg_thickness_in');
        if (!el) { return; }
        el.textContent = (isNaN(mm) || mm <= 0) ? '' :
            '\u2248 ' + (mm / 25.4).toFixed(2) + ' in';
    }

    function setError(msg) {
        var e = $('sg_error');
        e.innerHTML = msg;
        e.style.display = msg ? '' : 'none';
    }

    /* ── generate + render ──────────────────────────────────────────────── */

    function calculate() {
        var mm = parseFloat($('sg_thickness').value);
        if (isNaN(mm) || mm < 1) {
            setError('Enter a valid thickness (mm \u2265 1).');
            return;
        }
        setError('');

        lastValues = sgGenerateSchedule($('sg_cone').value, $('sg_type').value, mm);
        render();
    }

    function cancelSchedule() {
        lastValues = null;
        setError('');
        $('sg_results').style.display = 'none';
    }

    function render() {
        var v = lastValues;

        $('sg_summary').innerHTML =
            summaryCard('Peak Temp', v.peak_temp_c + '&deg;C / ' + Math.round(sgCToF(v.peak_temp_c)) + '&deg;F') +
            summaryCard('Total Time', v.total_hours + ' hrs') +
            summaryCard('Segments', v.segment_count);

        $('sg_warnings').innerHTML = (v.warnings || []).map(function (w) {
            return '<div class="alert alert-warning py-2 px-3 mt-2 mb-0 small">' + w.message + '</div>';
        }).join('');

        var rows = '';
        for (var i = 0; i < v.segments.length; i++) {
            var s = v.segments[i];
            rows += '<tr>' +
                '<td>' + (i + 1) + '</td>' +
                '<td>' + s.from + '&deg;C / ' + Math.round(sgCToF(s.from)) + '&deg;F</td>' +
                '<td>' + s.to + '&deg;C / ' + Math.round(sgCToF(s.to)) + '&deg;F</td>' +
                '<td>' + s.rate + '&deg;C/hr / ' + Math.round(sgRateCToF(s.rate)) + '&deg;F/hr</td>' +
                '<td>' + (s.hold ? s.hold + ' min' : '&mdash;') + '</td>' +
                '<td class="small text-muted">' + s.note + '</td>' +
                '</tr>';
        }
        $('sg_segments').innerHTML = rows;

        $('sg_name').value = defaultName();
        $('sg_results').style.display = '';
    }

    function summaryCard(label, value) {
        return '<div class="stat-box" style="min-width:150px"><div class="stat-tag">' + label.toUpperCase() + '</div>' +
               '<div class="stat-cell"><div class="stat-bottom">' + value + '</div></div></div>';
    }

    function defaultName() {
        return 'cone' + $('sg_cone').value + '-' + $('sg_type').value + '-gen';
    }

    /* ── convert to a kiln-controller profile and save ──────────────────── */

    function segmentsToProfile(name) {
        var segs = lastValues.segments;
        var t = 0;
        var data = [];
        for (var i = 0; i < segs.length; i++) {
            var s = segs[i];
            if (i === 0) {
                data.push([0, Math.round(sgCToF(s.from))]);
            }
            t += (s.to - s.from) / s.rate * 3600;  // seconds
            data.push([Math.round(t), Math.round(sgCToF(s.to))]);
            if (s.hold > 0) {
                t += s.hold * 60;
                data.push([Math.round(t), Math.round(sgCToF(s.to))]);
            }
        }

        /* profiles must be strictly increasing in time */
        var clean = [];
        var last = -1;
        for (var j = 0; j < data.length; j++) {
            if (data[j][0] > last) {
                clean.push(data[j]);
                last = data[j][0];
            }
        }

        return {
            type: 'profile',
            name: name,
            description: 'Generated cone ' + $('sg_cone').value + ' ' +
                         $('sg_type').value + ' firing (' + lastValues.total_hours + ' hrs)',
            tags: formTags(),
            data: clean
        };
    }

    /* every form value, stored as a filterable tag on the saved schedule */
    function formTags() {
        var tags = ['cone' + $('sg_cone').value, $('sg_type').value];
        var mm = parseFloat($('sg_thickness').value);
        if (!isNaN(mm) && mm > 0) {
            tags.push(mm + 'mm');
        }
        return tags;
    }

    function saveAsSchedule() {
        if (!lastValues) { return; }
        var name = $('sg_name').value.trim();
        if (!name) {
            showGrowl('<i class="bi bi-exclamation-triangle-fill"></i> Give the schedule a name first.', 'error');
            return;
        }
        var ws = window.ws_storage;
        if (!ws || ws.readyState !== 1) {
            showGrowl('<i class="bi bi-exclamation-triangle-fill"></i> Storage connection not ready - try again in a moment.', 'error');
            return;
        }
        ws.send(JSON.stringify({ cmd: 'PUT', profile: segmentsToProfile(name) }));
        showGrowl('<i class="bi bi-check-lg"></i> Saved <b>' + name + '</b> to Schedules.', 'success');
    }

    /* scripts load at the end of <body>, so the DOM is ready */
    inject();

    /* honor a #schedgen deep link; openTabFromHash ran before this tab
       was registered, so re-run it when the hash points here */
    if (window.location.hash === '#schedgen' && typeof openTabFromHash === 'function') {
        openTabFromHash();
    }

})();
