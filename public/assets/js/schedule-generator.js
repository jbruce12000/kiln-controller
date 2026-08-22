/* ═══════════════════════════════════════════════════════════════════════════
   Schedule Generator tab ── removable feature module
   
   Generates multi-segment pottery firing schedules entirely in the browser.
   The algorithm is a faithful port of ClayCalc's firing schedule generator
   (https://claycalc.com/calculators/firing-schedule-generator), verified
   against its live API in Aug 2026: segment structure, C/hr ramp rates,
   thickness-based candling holds, warnings, and per-cone peak values.

   Like ClayCalc's PHP engines, everything is generated in metric:
   Celsius temperatures, C/hr rates. Schedules carry units:'c'; the UI
   converts them for display to match config.temp_scale, and saved
   profiles are stored in the active scale.

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

var SG_CONE_PEAKS_C = {
    '06': 999, '05': 1031, '04': 1063, '03': 1101, '02': 1120,
    '01': 1137, '1': 1154, '2': 1162, '3': 1168, '4': 1186,
    '5': 1196, '6': 1222, '7': 1240, '8': 1263, '9': 1280, '10': 1305
};

/* Room temperature where schedules begin (Celsius, per ClayCalc). */
var SG_AMBIENT_C = 20;

/* ── conversions ────────────────────────────────────────────────────────── */


function sgCToF(c) { return c * 9 / 5 + 32; }

function sgRateCToF(r) { return r * 9 / 5; }

/* Convert a temperature/rate between unit systems ('f' or 'c').
   Rates convert by ratio only; temperatures carry the 32-degree offset. */
function sgConvertTemp(value, from, to) {
    if (from === to) { return value; }
    return (from === 'f') ? (value - 32) * 5 / 9 : value * 9 / 5 + 32;
}

function sgConvertRate(value, from, to) {
    if (from === to) { return value; }
    return (from === 'f') ? value * 5 / 9 : value * 9 / 5;
}


/* ── candling hold minutes based on thickest piece in the load (millimeters) ──── */

function sgCandlingHoldMin(mm) {
    if (mm >= 16) { return 60; }
    if (mm >= 9) { return 30; }
    return 0;
}


/* ── generate a pottery firing schedule ──────────────────────────────────────

   cone: cone number string (e.g. '6', '06', '10')
   firingType: 'glaze' | 'bisque'
   thicknessIn: thickest piece thickness in millimeters (min 1)
   
   Returns: {kind:'pottery', units:'c', segments, peak_temp, total_hours,
            segment_count, warnings}

   Temperatures are Celsius and rates C/hr (ClayCalc parity); callers
   convert with sgConvertTemp/sgConvertRate to match config.temp_scale.
   
   Generates a multi-segment kiln firing schedule for pottery using Orton cone data.
   Segments follow standard Orton heating profile with candling hold for thick pieces.
   */ 

function sgGenerateSchedule(cone, firingType, thicknessIn) {
    var t = parseFloat(thicknessIn);
    
    if (isNaN(t) || t < 1) {
        return {kind: 'pottery', units: 'c', segments: [], peak_temp: 0, total_hours: 0, segment_count: 0, warnings: []};
    }
    
    /* Look up the peak temperature using the exact cone string.
       SG_CONE_PEAKS_C has keys like '06' (999 C) and '6' (1222 C).
       Values mirror ClayCalc's engine exactly; no conversion needed. */
    var peak = SG_CONE_PEAKS_C[String(cone)];
    if (peak === undefined) {
        return {kind: 'pottery', units: 'c', segments: [], peak_temp: 0, total_hours: 0, segment_count: 0, warnings: []};
    }
    
    var segments = [];
    var warnings = [];
    
    /* ---- ClayCalc firing stages (all values Celsius as published) ----

       Holds/soaks are their own segments: a hold segment has from == to
       and rate == 0, meaning "maintain this temperature for hold minutes".
       Shared stages for glaze and bisque:
         1. Candling:  20 -> 120 C at 50 C/hr; thick loads add a candling
                       hold segment (sgCandlingHoldMin: >=9 mm -> 30 min,
                       >=16 mm -> 60 min)
         2. Burnout:   120 -> 500 C at 80 C/hr
         3. Inversion: 500 -> 600 C at 60 C/hr (quartz inversion at 573 C)
       Then:
         Glaze:  600 -> (peak - 100) at 120 C/hr, (peak - 100) -> peak at
                 40 C/hr, then a 15 min hold segment at peak
         Bisque: 600 -> peak at 100 C/hr, then a 20 min hold segment */

    /* Segment 1: steam & mechanical water release */
    var candlingHold = sgCandlingHoldMin(t);
    if (t > 20) {
        warnings.push({
            severity: 'warning',
            message: 'Very thick pieces (>20mm) need additional soaking time ' +
                     'and may require a candling segment of 2\u20134 hours.'
        });
    }

    segments.push({
        from: SG_AMBIENT_C, to: 120, rate: 50, hold: 0,
        note: 'Steam & mechanical water release'
    });

    /* Candling hold: maintain 120 C for the thickness-derived time */
    if (candlingHold > 0) {
        segments.push({
            from: 120, to: 120, rate: 0, hold: candlingHold,
            note: 'Candling hold'
        });
    }

    /* Segment 2: chemical water & organic burnout */
    segments.push({
        from: 120, to: 500, rate: 80, hold: 0,
        note: 'Chemical water & organic burnout'
    });

    /* Segment 3: quartz inversion zone */
    segments.push({
        from: 500, to: 600, rate: 60, hold: 0,
        note: 'Quartz inversion zone \u2014 573\u00b0C critical'
    });

    /* Remaining segments: glaze or bisque profile */
    if (firingType === 'glaze') {
        segments.push({
            from: 600, to: peak - 100, rate: 120, hold: 0,
            note: 'Approach peak temperature'
        });
        segments.push({
            from: peak - 100, to: peak, rate: 40, hold: 0,
            note: 'Final approach'
        });
        segments.push({
            from: peak, to: peak, rate: 0, hold: 15,
            note: 'Soak at cone ' + cone + ' peak'
        });
    } else {
        segments.push({
            from: 600, to: peak, rate: 100, hold: 0,
            note: 'Final bisque temperature'
        });
        segments.push({
            from: peak, to: peak, rate: 0, hold: 20,
            note: 'Bisque soak'
        });
    }
    
    /* ---- calculate total hours ---- */
    /* Rates are in °C/hr, holds in minutes. Hold segments have
       rate == 0 and from == to, contributing only their hold time. */
    
    var total = 0;
    for (var i = 0; i < segments.length; i++) {
        var s = segments[i];
        var segmentTime = (s.to !== s.from)
            ? (s.to - s.from) / s.rate   /* hours */
            : 0;                         /* hold segment: no ramp time */
        var holdHours = 0;
        if (s.hold > 0) {
            holdHours = s.hold / 60;  /* convert minutes to hours */
        }
        total += segmentTime + holdHours;
    }
    var totalHours = Math.round(total * 10) / 10;  /* round to 1 decimal place */
    
    return {
        kind: 'pottery',
        units: 'c',
        segments: segments,
        peak_temp: peak,
        total_hours: totalHours,
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
            ' <div class="panel-heading"><strong>Schedule Generator</strong></div>' +
            ' <div class="panel-body">' +
            '  <p class="text-muted mb-2">Generates pottery firing schedules entirely in your browser.</p>' +
            '  <div id="sg-pottery-form" class="sg-form pottery-form">' +
            '   <div class="row g-2">' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Target Cone</label>' +
            '     <select id="sg_cone" class="form-select form-select-sm"></select></div>' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Firing Type</label>' +
            '     <select id="sg_type" class="form-select form-select-sm">' +
            '      <option value="bisque">Bisque</option>' +
            '      <option value="glaze" selected>Glaze</option></select></div>' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Thickest Piece (mm)</label>' +
            '     <input id="sg_thickness" type="number" min="1" step="1" value="8" class="form-control form-control-sm" />' +
            '     <div class="small text-muted" id="sg_thickness_in"></div></div>' +
            '   </div>' +
            '   <div class="btn-group btn-group-sm mt-3">' +
            '    <button id="sg_calculate" type="button" class="btn btn-success"><i class="bi bi-magic"></i> Generate Schedule</button>' +
            '   </div>' +
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
            '   <div class="small text-muted mt-1">Saved schedules appear on the Schedules tab. Always verify against witness cones/or test pieces.</div>' +
            '  </div>' +
            ' </div>' +
            '</div>';

        document.querySelector('.container-fluid.py-3').appendChild(section);

        /* init pottery form */
        initPotteryForm();
    }

    /* ── shared UI state helpers ─────────────────────────────────────────── */

    function setError(msg) {
        var el = $('sg_error');
        if (!msg) { el.style.display = 'none'; el.innerHTML = ''; return; }
        el.innerHTML = msg;
        el.style.display = '';
    }

    function updateInches() {
        var mm = parseFloat($('sg_thickness').value);
        if (isNaN(mm) || mm <= 0) { $('sg_thickness_in').textContent = ''; return; }
        $('sg_thickness_in').textContent = '\u2248 ' + (mm / 25.4).toFixed(2) + ' in';
    }

    function cancelSchedule() {
        lastValues = null;
        setError('');
        $('sg_results').style.display = 'none';
        $('sg_name').value = '';
    }

    /* ── pottery form initialization ─────────────────────────────────────── */

    function initPotteryForm() {
        var coneSel = $('sg_cone');
        for (var i = 0; i < SG_CONES.length; i++) {
            var opt = document.createElement('option');
            opt.value = SG_CONES[i];
            opt.textContent = 'Cone ' + SG_CONES[i];
            if (SG_CONES[i] === '6') { opt.selected = true; }
            coneSel.appendChild(opt);
        }

        $('sg_thickness').addEventListener('input', updateInches);
        $('sg_calculate').addEventListener('click', calculatePottery);
        $('sg_save').addEventListener('click', saveAsSchedule);
        $('sg_cancel').addEventListener('click', cancelSchedule);
        updateInches();
    }

    function calculatePottery() {
        var cone = $('sg_cone').value;
        var firingType = $('sg_type').value;
        var mm = parseFloat($('sg_thickness').value);
        if (isNaN(mm) || mm < 1) {
            setError('Enter a valid thickness (mm \u2265 1).');
            return;
        }
        setError('');

        lastValues = sgGenerateSchedule(cone, firingType, mm);
        render();
    }

    /* ── render ──────────────────────────────────────────────────────────── */

    function render() {
        var v = lastValues;
        /* schedules carry their own units; display matches config.temp_scale
           (global kept current by kiln-controller.js; falls back to f) */
        var scale = (typeof temp_scale !== 'undefined' && temp_scale === 'c') ? 'c' : 'f';
        var units = v.units || 'f';
        var unitLabel = (scale === 'c') ? '&deg;C' : '&deg;F';

        /* render summary */
        $('sg_summary').innerHTML = '';

        var peakDisp = Math.round(sgConvertTemp(v.peak_temp, units, scale));
        $('sg_summary').innerHTML =
            summaryCard('Peak Temp', peakDisp + unitLabel) +
            summaryCard('Total Time', v.total_hours + ' hrs') +
            summaryCard('Segments', v.segment_count);

        /* render warnings */
        $('sg_warnings').innerHTML = (v.warnings || []).map(function (w) {
            /* generator emits plain strings; tolerate {severity,message} objects too */
            var severity = (w && typeof w === 'object') ? (w.severity || 'warning') : 'warning';
            var message = (w && typeof w === 'object') ? w.message : String(w);
            return '<div class="alert alert-' + severity + ' py-2 px-3 mt-2 mb-0 small">' + message + '</div>';
        }).join('');

        /* render segments */
        var rows = '';
        for (var i = 0; i < v.segments.length; i++) {
            var s = v.segments[i];
            var fromD = Math.round(sgConvertTemp(s.from, units, scale));
            var toD = Math.round(sgConvertTemp(s.to, units, scale));
            var rateD = Math.round(sgConvertRate(s.rate, units, scale));
            rows += '<tr>' +
                '<td>' + (i + 1) + '</td>' +
                '<td>' + fromD + unitLabel + '</td>' +
                '<td>' + toD + unitLabel + '</td>' +
                '<td>' + (s.rate > 0 ? rateD + unitLabel + '/hr' : '&mdash;') + '</td>' +
                '<td>' + (s.hold ? s.hold + ' min' : '&mdash;') + '</td>' +
                '<td class="small text-muted">' + s.note + '</td>' +
                '</tr>';
        }
        $('sg_segments').innerHTML = rows;

        /* save button name */
        $('sg_name').value = defaultName($('sg_cone').value, $('sg_type').value);

        $('sg_results').style.display = '';
    }

    function summaryCard(label, value) {
        return '<div class="stat-box" style="min-width:150px"><div class="stat-tag">' + label.toUpperCase() + '</div>' +
               '<div class="stat-cell"><div class="stat-bottom">' + value + '</div></div></div>';
    }

    function defaultName(key, tr) {
        if (key && tr) {
            return key.toLowerCase() + '-' + tr + '-gen';
        }
        return 'schedule-gen';
    }

    /* ── convert to profile and save ─────────────────────────────────────── */

    function segmentsToProfile(name) {
        var segs = lastValues.segments;
        var scale = (typeof temp_scale !== 'undefined' && temp_scale === 'c') ? 'c' : 'f';
        var units = (lastValues && lastValues.units) || 'f';
        var t = 0;
        var data = [];
        for (var i = 0; i < segs.length; i++) {
            var s = segs[i];
            if (i === 0) {
                data.push([0, Math.round(sgConvertTemp(s.from, units, scale))]);
            }
            if (s.rate > 0 && s.to !== s.from) {
                t += (s.to - s.from) / s.rate * 3600;  // seconds (rate ratio is scale-independent)
            }
            data.push([Math.round(t), Math.round(sgConvertTemp(s.to, units, scale))]);
            if (s.hold > 0) {
                /* hold: maintain the arrival temperature for hold minutes;
                   emit a plateau keypoint converted to the active scale */
                t += s.hold * 60;
                data.push([Math.round(t), Math.round(sgConvertTemp(s.to, units, scale))]);
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
            description: 'Generated ' + lastValues.kind + ' schedule (' + lastValues.total_hours + ' hrs)',
            tags: formTags(),
            data: clean
        };
    }

    /* every form value, stored as a filterable tag on the saved schedule */
    function formTags() {
        var cone = $('sg_cone').value;
        var type = $('sg_type').value;
        var mm = parseFloat($('sg_thickness').value);
        var tags = ['cone' + cone, type];
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