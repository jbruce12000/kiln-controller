/* ═══════════════════════════════════════════════════════════════════════════
   Schedule Generator tab ── removable feature module
   
   Generates multi-segment kiln firing schedules entirely in the browser.
   Supports both pottery firing and steel heat treatment schedules.
   Segment structure, ramp rates, thickness-based candling holds, and
   per-cone peak temperatures follow standard ceramic practice (Orton
   cone data, quartz inversion at 573 degC).
   Heat treatment data sourced from knifemakercompanion.com and
   Lucifer Furnaces chart, merged into SG_STEELS.

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

/* 44 knife steels merged from KMC datasheet and Lucifer Furnaces chart.
   Fields: name, family, harden[lo,hi], temper|anneal|normalize ([lo,hi] or null),
   quench str, soak [lo,hi]min|null (datasheet harden soak),
   normHold [lo,hi]|null, hrc str, cryo str. */
var SG_STEELS = {
    /* Carbon */
    1045: { name: '1045', family: 'Carbon',
        harden: [1500,1550], temper: [400,650], anneal: null, normalize: [1600,1600],
        quench: 'Water or brine', soak: [10,15], normHold: [10,10],
        hrc: '55-58', cryo: '' },
    1075: { name: '1075', family: 'Carbon',
        harden: [1475,1500], temper: [300,450], anneal: null, normalize: [1600,1600],
        quench: 'Fast oil', soak: [5,10], normHold: [10,10],
        hrc: '64-65', cryo: '' },
    1084: { name: '1084', family: 'Carbon',
        harden: [1475,1500], temper: [300,450], anneal: null, normalize: [1600,1600],
        quench: 'Fast oil', soak: [5,10], normHold: [10,10],
        hrc: '64-65', cryo: '' },
    1095: { name: '1095', family: 'Carbon',
        harden: [1475,1500], temper: [300,450], anneal: null, normalize: [1600,1600],
        quench: 'Fast oil', soak: [5,10], normHold: [10,10],
        hrc: '65', cryo: '' },
    '1080SQ': { name: '1080-SQ', family: 'Carbon',
        harden: [1475,1500], temper: [300,450], anneal: null, normalize: [1600,1600],
        quench: 'Fast oil', soak: [5,10], normHold: [10,10],
        hrc: '64-65', cryo: '' },
    /* Carbon-Alloy */
    '125CRL': { name: '125CRL', family: 'Carbon-Alloy',
        harden: [1500,1550], temper: [375,425], anneal: null, normalize: [1650,1650],
        quench: 'Oil', soak: [5,10], normHold: [15,15],
        hrc: '65-67', cryo: '' },
    '15N20': { name: '15N20', family: 'Carbon-Alloy',
        harden: [1475,1480], temper: [375,475], anneal: null, normalize: [1600,1600],
        quench: 'Fast oil (Parks-50)', soak: [5,15], normHold: [10,10],
        hrc: '64-65', cryo: '' },
    '80CRV2': { name: '80CRV2', family: 'Carbon-Alloy',
        harden: [1475,1480], temper: [375,475], anneal: null, normalize: [1600,1600],
        quench: 'Fast oil (Parks-50)', soak: [5,10], normHold: [15,15],
        hrc: '61-63', cryo: '' },
    5160: { name: '5160', family: 'Carbon-Alloy',
        harden: [1500,1525], temper: [400,500], anneal: null, normalize: [1600,1600],
        quench: 'Oil', soak: [5,10], normHold: [15,15],
        hrc: '56-60', cryo: '' },
    52100: { name: '52100', family: 'Carbon-Alloy',
        harden: [1475,1480], temper: [350,500], anneal: null, normalize: [1550,1650],
        quench: 'Medium oil (Parks AAA)', soak: [5,15], normHold: [10,15],
        hrc: '64-65', cryo: '' },
    1040: { name: '1040', family: 'Carbon-Alloy',
        harden: [1550,1550], temper: null, anneal: [1550,1550], normalize: [1650,1650],
        quench: 'Water', soak: null, normHold: null,
        hrc: '', cryo: '' },
    4130: { name: '4130', family: 'Carbon-Alloy',
        harden: [1600,1600], temper: null, anneal: [1575,1575], normalize: [1625,1625],
        quench: 'Oil', soak: null, normHold: null,
        hrc: '', cryo: '' },
    4140: { name: '4140', family: 'Carbon-Alloy',
        harden: [1575,1575], temper: [400,1200], anneal: [1550,1550], normalize: [1600,1600],
        quench: 'Oil', soak: null, normHold: null,
        hrc: '', cryo: '' },
    /* Tool */
    A2: { name: 'A-2', family: 'Tool',
        harden: [1750,1750], temper: [400,500], anneal: [1550,1600], normalize: null,
        quench: 'Air', soak: [30,30], normHold: null,
        hrc: '60-62', cryo: '' },
    D2: { name: 'D-2', family: 'Tool',
        harden: [1850,1850], temper: [400,525], anneal: [1600,1650], normalize: null,
        quench: 'Oil or air', soak: [30,30], normHold: null,
        hrc: '60-62', cryo: '' },
    L6: { name: 'L-6', family: 'Tool',
        harden: [1450,1500], temper: [400,500], anneal: null, normalize: null,
        quench: 'Oil', soak: [10,20], normHold: null,
        hrc: '56-60', cryo: '' },
    O1: { name: 'O-1', family: 'Tool',
        harden: [1450,1450], temper: [375,475], anneal: [1400,1450], normalize: [1600,1600],
        quench: 'Oil', soak: [10,20], normHold: null,
        hrc: '60-62', cryo: '' },
    W1: { name: 'W-1', family: 'Tool',
        harden: [1450,1500], temper: [375,475], anneal: [1360,1400], normalize: [1450,1600],
        quench: 'Water or brine', soak: [5,10], normHold: null,
        hrc: '65-67', cryo: '' },
    W2: { name: 'W-2', family: 'Tool',
        harden: [1450,1500], temper: [375,475], anneal: null, normalize: null,
        quench: 'Water or brine', soak: [5,10], normHold: null,
        hrc: '65-67', cryo: '' },
    A6: { name: 'A6', family: 'Tool',
        harden: [1800,1875], temper: [400,1000], anneal: [1600,1650], normalize: null,
        quench: 'Air', soak: null, normHold: null,
        hrc: '', cryo: '' },
    S7: { name: 'S7', family: 'Tool',
        harden: [1650,1750], temper: [400,1200], anneal: [1500,1550], normalize: null,
        quench: 'Oil', soak: null, normHold: null,
        hrc: '', cryo: '' },
    H13: { name: 'H13', family: 'Tool',
        harden: [1825,1875], temper: [1000,1200], anneal: [1550,1650], normalize: null,
        quench: 'Air or oil', soak: null, normHold: null,
        hrc: '', cryo: '' },
    M2: { name: 'M2', family: 'Tool',
        harden: [2150,2250], temper: [1000,1200], anneal: [1600,1650], normalize: null,
        quench: 'Air, oil or salt', soak: null, normHold: null,
        hrc: '', cryo: '' },
    T2: { name: 'T2', family: 'Tool',
        harden: [2300,2375], temper: [1000,1100], anneal: [1600,1650], normalize: null,
        quench: 'Air, oil or salt', soak: null, normHold: null,
        hrc: '', cryo: '' },
    /* Stainless */
    '440C': { name: '440C', family: 'Stainless',
        harden: [1900,1950], temper: [375,450], anneal: null, normalize: [1850,1850],
        quench: 'Plate quench or oil', soak: [30,30], normHold: [20,30],
        hrc: '60-61', cryo: '-320 °F for 4-6 hr' },
    NITROV: { name: 'Nitro-V', family: 'Stainless',
        harden: [1900,1900], temper: [350,425], anneal: null, normalize: [1850,1850],
        quench: 'Plate quench', soak: [5,10], normHold: [15,20],
        hrc: '64-65', cryo: '-100 °F for 1 hr' },
    '154CM': { name: '154-CM', family: 'Stainless',
        harden: [1950,2050], temper: [400,500], anneal: null, normalize: null,
        quench: 'Plate quench or oil', soak: [30,30], normHold: null,
        hrc: '62-63', cryo: '-100 °F for 1-2 hr' },
    AEBL: { name: 'AEB-L', family: 'Stainless',
        harden: [1950,2050], temper: [375,475], anneal: null, normalize: null,
        quench: 'Plate quench', soak: [10,15], normHold: null,
        hrc: '62-63', cryo: '-100 °F for 30-60 min' },
    '420HC': { name: '420-HC', family: 'Stainless',
        harden: [1850,1950], temper: [350,400], anneal: null, normalize: null,
        quench: 'Air or oil', soak: [20,30], normHold: null,
        hrc: '56-58', cryo: '' },
    '440A': { name: '440-A', family: 'Stainless',
        harden: [1850,1950], temper: [350,400], anneal: null, normalize: null,
        quench: 'Air or oil', soak: [30,30], normHold: null,
        hrc: '55-58', cryo: '' },
    '440B': { name: '440-B', family: 'Stainless',
        harden: [1850,1950], temper: [350,400], anneal: null, normalize: null,
        quench: 'Air or oil', soak: [30,30], normHold: null,
        hrc: '58-60', cryo: '' },
    /* Powder Stainless */
    CPM154CM: { name: 'CPM 154-CM', family: 'Powder Stainless',
        harden: [1950,2050], temper: [400,500], anneal: null, normalize: null,
        quench: 'Plate quench or oil', soak: [30,30], normHold: null,
        hrc: '62-63', cryo: '-100 °F for 1-2 hr' },
    CPMS30V: { name: 'CPM S30-V', family: 'Powder Stainless',
        harden: [2000,2050], temper: [400,500], anneal: null, normalize: null,
        quench: 'Plate quench or air', soak: [20,30], normHold: null,
        hrc: '60-61', cryo: '-100 °F for 1-2 hr' },
    CPMS35VN: { name: 'CPM S35-VN', family: 'Powder Stainless',
        harden: [2050,2050], temper: [400,500], anneal: null, normalize: null,
        quench: 'Plate quench or air', soak: [15,30], normHold: null,
        hrc: '60-61', cryo: '-100 °F for 1-2 hr' },
    CPM20CV: { name: 'CPM 20CV', family: 'Powder Stainless',
        harden: [1960,2050], temper: [400,800], anneal: null, normalize: null,
        quench: 'Gas or oil quench to below 125 F', soak: [20,30], normHold: null,
        hrc: '58-60', cryo: '-100 °F for 1-2 hr' },
    CPMMAGNACUT: { name: 'CPM MagnaCut', family: 'Powder Stainless',
        harden: [1950,2050], temper: [300,450], anneal: null, normalize: null,
        quench: 'Plate or positive pressure quench to below 125 F', soak: [20,30], normHold: null,
        hrc: '60-63', cryo: '-100 °F for 1 hr' },
    CPMS45VN: { name: 'CPM S45VN', family: 'Powder Stainless',
        harden: [1900,2000], temper: [400,750], anneal: null, normalize: null,
        quench: 'Plate or air quench to below 125 F', soak: [15,30], normHold: null,
        hrc: '59-61', cryo: '-100 °F for 1-2 hr' },
    CPMS90V: { name: 'CPM S90V', family: 'Powder Stainless',
        harden: [2100,2150], temper: [400,750], anneal: null, normalize: null,
        quench: 'Salt, gas or vacuum quench to below 125 F', soak: [20,20], normHold: null,
        hrc: '58-61', cryo: '-100 °F for 1-2 hr' },
    M390: { name: 'M390', family: 'Powder Stainless',
        harden: [2000,2100], temper: [400,450], anneal: null, normalize: null,
        quench: 'Oil or gas quench then cool to room temp', soak: [20,30], normHold: null,
        hrc: '60-62', cryo: '-110 °F for 2 hr' },
    /* Powder Tool */
    CPM3V: { name: 'CPM 3-V', family: 'Powder Tool',
        harden: [1900,1950], temper: [400,500], anneal: null, normalize: null,
        quench: 'Plate quench or oil', soak: [15,30], normHold: null,
        hrc: '58-60', cryo: '' },
    CPMD2: { name: 'CPM D-2', family: 'Powder Tool',
        harden: [1850,1850], temper: [400,500], anneal: null, normalize: null,
        quench: 'Oil or air', soak: [20,30], normHold: null,
        hrc: '61-62', cryo: '-100 °F for 1-2 hr' },
    CPMM4: { name: 'CPM M-4', family: 'Powder Tool',
        harden: [2150,2150], temper: [400,550], anneal: null, normalize: null,
        quench: 'Air or salt bath', soak: [30,30], normHold: null,
        hrc: '64-66', cryo: '' },
    CPM4V: { name: 'CPM 4V', family: 'Powder Tool',
        harden: [1875,1950], temper: [1000,1100], anneal: null, normalize: [1600,1600],
        quench: 'Air, gas or warm oil quench', soak: [15,30], normHold: [20,20],
        hrc: '62-64', cryo: '-100 °F for 1-2 hr' },
    CPMCRUWEAR: { name: 'CPM CruWear', family: 'Powder Tool',
        harden: [1850,2050], temper: [900,1050], anneal: null, normalize: [1600,1600],
        quench: 'Air or gas quench to below 125 F', soak: [20,45], normHold: [20,20],
        hrc: '60-64', cryo: '-100 °F for 1-2 hr' }
};

/* ── conversions ────────────────────────────────────────────────────────── */

function sgFToC(f) { return (f - 32) * 5 / 9; }

function sgCToF(c) { return c * 9 / 5 + 32; }

function sgRateCToF(r) { return r * 9 / 5; }

function sgCToFPair(c) { return [c * 9 / 5 + 32]; }

/* ── ramp rate: F/hr based on thickness in inches ──────────────────────── */

function sgRampRateF(tin) {
    if (tin <= 2) return 400;
    if (tin <= 4) return 200;
    return 100;
}

/* ── candling hold at 120 degF based on thickest piece in the load (inches) ──── */

function sgCandlingHoldMin(mm) {
    if (mm >= 20) { return 60; }
    if (mm >= 12) { return 30; }
    return 0;
}

/* ── steel heat treatment soak minutes ─────────────────────────────────────

   treatment: 'harden' | 'normalize' | 'temper' | 'anneal'
   thicknessIn: thickness in inches (decimal)
   steel: steel object from SG_STEELS (may be null for per-inch defaults)
   
   Returns soak minutes (integer).                   */ 

function sgSteelSoakMin(treatment, thicknessIn, steel) {
    var t = parseFloat(thicknessIn);
    if (isNaN(t) || t <= 0) return 0;

    if (steel && steel.soak && steel.soak[treatment]) {
        var soak = steel.soak[treatment];
        var mid = (soak[0] + soak[1]) / 2;
        return Math.min(600, Math.max(round5(mid), Math.ceil(t * 60)));
    }

    if (steel && steel.normHold && steel.normHold[treatment]) {
        var nh = steel.normHold[treatment];
        var mid = (nh[0] + nh[1]) / 2;
        return Math.min(600, Math.max(round5(mid), Math.ceil(t * 30), 20));
    }

    /* per-inch floors */
    if (treatment === 'harden')    return Math.min(600, Math.max(30, Math.round(t * 60 / 0.125)));
    if (treatment === 'temper')    return 120;
    if (treatment === 'anneal')    return Math.min(120, Math.max(60, Math.round(t * 60 / 0.125)));
    if (treatment === 'normalize') return Math.min(30, Math.max(20, Math.round(t * 20 / 0.125)));
    return 0;
}

function round5(v) { return Math.round(v / 5) * 5; }

/* ── generate a pottery firing schedule ──────────────────────────────────────

   cone: cone number string (e.g. '6', '06', '10')
   firingType: 'glaze' | 'bisque'
   thicknessIn: thickest piece thickness in millimeters (min 1)
   
   Returns: {kind:'pottery', units:'c', segments, peak_temp_c, total_hours, segment_count, warnings}
   
   Generates a multi-segment kiln firing schedule for pottery using Orton cone data.
   Segments follow standard Orton heating profile with candling hold for thick pieces.
   */ 

function sgGenerateSchedule(cone, firingType, thicknessIn) {
    var t = parseFloat(thicknessIn);
    
    if (isNaN(t) || t < 1) {
        return {kind: 'pottery', units: 'c', segments: [], peak_temp_c: 0, total_hours: 0, segment_count: 0, warnings: []};
    }
    
    /* Look up peak temperature using the exact cone string.
       SG_CONE_PEAKS_C has keys like '06' (→999) and '6' (→1222). */
    var peakF = SG_CONE_PEAKS_C[String(cone)];
    if (peakF === undefined) {
        return {kind: 'pottery', units: 'c', segments: [], peak_temp_c: 0, total_hours: 0, segment_count: 0, warnings: []};
    }
    
    var segments = [];
    var warnings = [];
    
    /* ---- Orton heating profile ----
       Both glaze and bisque start with:
         1. 20°F → 120°F at 50°F/hr
         2. 120°F → 500°F at 80°F/hr
         3. 500°F → 600°F at 60°F/hr
       
       Then differ:
         Glaze: 600°F → 1122°F at 120°F/hr, then 1122°F → 1222°F at 40°F/hr with 15 min soak
         Bisque: 600°F → 1222°F at 100°F/hr with 20 min soak
       
       Candling hold: added to first segment hold when thickness >= 21mm
       Cool down: 1222°F → 20°F at 50°F/hr */
    
    /* Segment 1: initial heat 20 -> 120 (may include candling hold in hold field) */
    var candlingHold = 0;
    if (t >= 21) { candlingHold = 60; warnings.push(' thick piece candling hold'); }
    else if (t >= 20) { candlingHold = 30; }
    
    var seg1Hold = (candlingHold > 0) ? 60 : 0;
    segments.push({
        from: 20, to: 120, rate: 50, hold: seg1Hold,
        note: 'Initial heat to 120°F' + (candlingHold > 0 ? ' + candling hold' : '')
    });
    
    /* Segment 2: ramp 120 -> 500 */
    segments.push({
        from: 120, to: 500, rate: 80, hold: 0,
        note: 'Ramp to 500°F'
    });
    
    /* Segment 3: ramp 500 -> 600 */
    segments.push({
        from: 500, to: 600, rate: 60, hold: 0,
        note: 'Ramp to 600°F'
    });
    
    /* Segment 4 & 5: glaze or bisque profile */
    if (firingType === 'glaze') {
        /* Glaze: 600 -> (peak-100) at 120, then (peak-100) -> peak at 40 with 15 min soak */
        /* Segment 4: 600 -> (peak - 100) */
        segments.push({
            from: 600, to: peakF - 100, rate: 120, hold: 0,
            note: 'Ramp to glaze peak intermediate temperature'
        });
        /* Segment 5: (peak - 100) -> peak at 40 with 15 min soak */
        segments.push({
            from: peakF - 100, to: peakF, rate: 40, hold: 15,
            note: 'Soak at cone ' + cone + ' glaze peak temperature 15 min'
        });
    } else {
        /* Bisque: 600 -> peak at 100 with 20 min soak */
        /* Segment 4: 600 -> peak */
        segments.push({
            from: 600, to: peakF, rate: 100, hold: 20,
            note: 'Soak at cone ' + cone + ' bisque peak temperature 20 min'
        });
    }
    
    /* ---- calculate total hours ---- */
    /* Rates are in °F/hr, holds in minutes.
       Time = (temperature_difference / rate) + (hold_minutes / 60) */
    /* All segments have rate > 0; hold minutes converted to hours */
    
    var total = 0;
    for (var i = 0; i < segments.length; i++) {
        var s = segments[i];
        var segmentTime = (s.to - s.from) / s.rate;  /* hours */
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
        peak_temp_c: peakF,
        total_hours: totalHours,
        segment_count: segments.length,
        warnings: warnings
    };
}

/* ── default peak temperature for a treatment/steel combo ─────────────────── */

function sgSteelDefaultTempF(key, tr) {
    var steel = SG_STEELS[key];
    if (!steel) return null;
    var range = steel[tr];
    if (!range || range.length < 2) return null;
    return round5((range[0] + range[1]) / 2);
}

/* ── generate a steel heat treatment schedule ──────────────────────────────

   key: steel id string (e.g. 'O1', '1095', 'M2')
   tr: treatment type: 'harden' | 'temper' | 'anneal' | 'normalize'
   targetF: target temperature in F (must be within steel.harden/range or steel.normalize/range)
   thicknessIn: thickness in inches (decimal, min .01, max 12)
   soakMin: additional soak minutes at target temp (optional, min 5, max 1440)
   
   Returns: {kind:'steel', units:'f', segments, peak_temp_f, total_hours, segment_count,
             warnings, quench, hrc}
   
   Throws Error on: unknown steel, unavailable treatment, out-of-range target,
   bad thickness (>12). Segments start from 70°F.
   
   harden segment sequence:
     1. preheat 70→1200 @ramp_rate hold eqHold=max(15,min(60,round(30*t)))
     2. ramp 1200→target @ramp_rate hold 0
     3. soak target→target (soakMin minutes)
     4. quench (oil/air/water per steel)
     5. temper single segment (if tr=== 'harden' or 'temper')
   
   anneal sequence:
     1. heat target→1000 @40F/hr hold 0
     2. furnace-cool 1000→70
   
   normalize sequence:
     1. same as harden but normalize peak instead of harden peak
     2. air cool from normalize peak
   
   warnings: 'info' renders alert-info, else alert-warning
     - quench outside kiln (harden)
     - cryo note (harden+steel.cryo)
     - double temper (temper twice)
     - reduced ramp if rate!=400
     - >=2300F kiln capability
     - anneal leave-kiln-closed info
    */ 

function sgGenerateSteelSchedule(key, tr, targetF, thicknessIn, soakMin) {
    var steel = SG_STEELS[key];
    if (!steel) throw new Error('Unknown steel: ' + key);

    var availableTreatments = [];
    if (steel.harden)      availableTreatments.push('harden');
    if (steel.temper)      availableTreatments.push('temper');
    if (steel.anneal)      availableTreatments.push('anneal');
    if (steel.normalize)   availableTreatments.push('normalize');

    if (availableTreatments.indexOf(tr) === -1) {
        throw new Error('Unavailable treatment "' + tr + '" for steel ' + key);
    }

    var t = parseFloat(thicknessIn);
    if (isNaN(t) || t <= 0 || t > 12) {
        throw new Error('Bad thickness: ' + thicknessIn + ' (must be >0 and <=12)');
    }

    var targetC = sgFToC(targetF);
    var hRange = steel.harden;
    var tRange = steel.temper;
    var aRange = steel.anneal;
    var nRange = steel.normalize;
    var quench = steel.quench;
    var cryo = steel.cryo;
    var hrcRange = steel.hrc;

    /* validate target temp against treatment */
    if (tr === 'harden' && (targetF < hRange[0] || targetF > hRange[1])) {
        throw new Error('Out-of-range target ' + targetF + 'F for harden of ' + key +
                        ' (valid: ' + hRange[0] + '-' + hRange[1] + 'F)');
    }
    if (tr === 'temper' && tRange && (targetF < tRange[0] || targetF > tRange[1])) {
        throw new Error('Out-of-range target ' + targetF + 'F for temper of ' + key);
    }
    if (tr === 'anneal' && aRange && (targetF < aRange[0] || targetF > aRange[1])) {
        throw new Error('Out-of-range target ' + targetF + 'F for anneal of ' + key);
    }
    if (tr === 'normalize' && nRange && (targetF < nRange[0] || targetF > nRange[1])) {
        throw new Error('Out-of-range target ' + targetF + 'F for normalize of ' + key);
    }

    var rate = sgRampRateF(t);
    var eqHold = Math.max(15, Math.min(60, Math.round(30 * t)));
    var soak = sgSteelSoakMin(tr, t, steel);
    if (soakMin !== undefined && soakMin > 0) soak = soakMin;

    var segments = [];
    var peakTempF = 0;
    var warnings = [];

    /* ---- harden ---- */
    if (tr === 'harden') {
        /* 1. preheat 70→1200 @rate hold eqHold */
        segments.push({
            from: 70, to: 1200, rate: rate, hold: eqHold,
            note: 'Preheat to soak temperature'
        });

        /* 2. ramp 1200→target @rate hold 0 */
        segments.push({
            from: 1200, to: targetF, rate: rate, hold: 0,
            note: 'Ramp to target temperature'
        });

        /* 3. soak at target */
        if (soak > 0) {
            segments.push({
                from: targetF, to: targetF, rate: 0, hold: soak,
                note: 'Soak at target temperature ' + soak + ' min'
            });
        }

        /* 4. quench */
        segments.push({
            from: targetF, to: targetF, rate: 0, hold: 0,
            note: 'Quench: ' + quench
        });

        peakTempF = targetF;

        /* quench warning: oil quench can be outside kiln */
        if (tr === 'harden' && quench.indexOf('Oil') !== -1) {
            warnings.push({ severity: 'info', message: 'Quench medium may require removal from kiln' });
        }

        /* cryo note */
        if (cryo && cryo !== '') {
            warnings.push({ severity: 'info', message: 'Cryo: ' + cryo });
        }

        /* hrc */
        var hrc = hrcRange || '';

        /* 5. temper single segment (if not already tempered) */
        if (t !== 1) { /* skip temper for 1040 which has null temper */ 
            var defaultTemp = sgSteelDefaultTempF(key, 'temper');
            if (defaultTemp) {
                segments.push({
                    from: targetF, to: defaultTemp, rate: rate, hold: 0,
                    note: 'Temper at ' + defaultTemp + '°F'
                });
            }
        }
    }

    /* ---- standalone temper ---- */
    if (tr === 'temper') {
        var defaultTemp = sgSteelDefaultTempF(key, 'temper');
        if (defaultTemp) {
            segments.push({
                from: 70, to: defaultTemp, rate: rate, hold: 0,
                note: 'Temper at ' + defaultTemp + '°F'
            });
        }
        peakTempF = defaultTemp || 0;
        warnings.push({ severity: 'info', message: 'Temper segment added' });
    }

    /* ---- anneal ---- */
    if (tr === 'anneal') {
        /* Heat to 1000 @40F/hr, then furnace cool to 70 */
        if (targetF > 1000) {
            segments.push({
                from: targetF, to: 1000, rate: 40, hold: 0,
                note: 'Cool to 1000°F for anneal'
            });
        } else {
            segments.push({
                from: targetF, to: 1000, rate: 40, hold: 0,
                note: 'Heat to 1000°F for anneal'
            });
        }
        /* furnace cool 1000→70 */
        segments.push({
            from: 1000, to: 70, rate: 40, hold: 0,
            note: 'Furnace cool to 70°F'
        });
        peakTempF = 1000;
        warnings.push({ severity: 'info', message: 'Anneal: leave kiln closed for furnace cool' });
    }

    /* ---- normalize ---- */
    if (tr === 'normalize') {
        var nPeak = nRange ? (nRange[0] + nRange[1]) / 2 : targetF;
        var nTempF = round5(nPeak);
        /* ramp 70→nPeak @rate hold eqHold */
        segments.push({
            from: 70, to: nTempF, rate: rate, hold: eqHold,
            note: 'Ramp to normalize temperature'
        });
        /* air cool */
        segments.push({
            from: nTempF, to: nTempF, rate: 0, hold: 0,
            note: 'Air cool from normalize temperature'
        });
        peakTempF = nTempF;
    }

    /* ---- common: validate ramp rate warning ---- */
    if (rate !== 400) {
        warnings.push({ severity: 'info', message: 'Ramp rate reduced to ' + rate + '°F/hr for thickness' });
    }

    /* ---- >=2300F kiln capability warning ---- */
    if (peakTempF >= 2300) {
        warnings.push({ severity: 'warning', message: 'Peak temperature >=2300°F requires kiln capable of very high heat' });
    }

    /* ---- total hours calculation ---- */
    var total = 0;
    for (var i = 0; i < segments.length; i++) {
        var s = segments[i];
        /* zero-rate rows (quench, air cool) contribute no ramp time */
        if (s.rate > 0 && s.to !== s.from) {
            total += Math.abs(s.to - s.from) / s.rate * 3600;  // seconds
        }
        if (s.hold > 0) {
            total += s.hold * 60;  // seconds
        }
    }
    var totalHours = Math.round(total / 3600 * 10) / 10;

    var quenchSummary = quench;

    return {
        kind: 'steel',
        units: 'f',
        segments: segments,
        peak_temp_f: peakTempF,
        total_hours: totalHours,
        segment_count: segments.length,
        warnings: warnings,
        quench: quenchSummary,
        hrc: hrcRange || ''
    };
}

/* ── tags ────────────────────────────────────────────────────────────────── */

function sgPotteryTags(cone, type, mm) {
    return ['pottery', 'cone' + cone, type, String(mm) + 'mm'];
}

function sgSteelTags(key, tr, tin) {
    var steel = SG_STEELS[key];
    var steelKey = steel ? steel.name.toLowerCase().replace(/[^a-z0-9]/gi, '') : key.toLowerCase();
    return ['steel', steelKey, tr, String(tin).replace('.', '') + 'in'];
}

/* ── default name for saved schedule ─────────────────────────────────────── */

function defaultName(key, tr) {
    if (key && tr) {
        return key.toLowerCase() + '-' + tr + '-gen';
    }
    return 'schedule-gen';
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
    var currentKind = 'pottery';  // 'pottery' or 'steel'

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
            ' <div class="panel-heading"><strong>Schedule Generator</strong>' +
            '  <span class="text-muted fw-normal small">&nbsp;runs locally in your browser</span></div>' +
            ' <div class="panel-body">' +
            '  <p class="text-muted mb-2">Generates firing schedules for pottery or steel heat treatments. Schedules are tagged pottery or steel on save.</p>' +
            '  <div class="btn-group btn-group-sm mb-3" role="group" aria-label="Schedule type">' +
            '   <button id="sg_kind_pottery" type="button" class="btn btn-outline-secondary active"><i class="bi bi-cup-hot"></i> Pottery</button>' +
            '   <button id="sg_kind_steel" type="button" class="btn btn-outline-secondary"><i class="bi bi-hammer"></i> Steel</button>' +
            '  </div>' +
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
            '  <div id="sg-steel-form" class="sg-form steel-form" style="display:none">' +
            '   <div class="row g-2">' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Steel</label>' +
            '     <select id="sg_steel" class="form-select form-select-sm"></select></div>' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Treatment</label>' +
            '     <select id="sg_treatment" class="form-select form-select-sm"></select></div>' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Target °F</label>' +
            '     <select id="sg_target_f" class="form-select form-select-sm"></select></div>' +
            '   </div>' +
            '   <div class="row g-2">' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Thickness (in)</label>' +
            '     <input id="sg_steel_thickness" type="number" min="0.01" max="12" step="0.125" class="form-control form-control-sm" /></div>' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Target HRC</label>' +
            '     <select id="sg_target_hrc" class="form-select form-select-sm"></select></div>' +
            '   </div>' +
            '   <div class="row g-2">' +
            '    <div class="col-6"><label class="form-label small mb-1">Soak min (at target)</label>' +
            '     <input id="sg_soak_min" type="number" min="5" max="1440" class="form-control form-control-sm" /></div>' +
            '    <div class="col-6"><label class="form-label small mb-1">Ramp rate</label>' +
            '     <select id="sg_ramp_rate" class="form-select form-select-sm"><option value="400">400°F/hr</option><option value="200">200°F/hr</option><option value="100">100°F/hr</option></select></div>' +
            '   </div>' +
            '   <div class="row g-2">' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Soak hint</label>' +
            '     <div id="sg_soak_hint" class="small text-muted"></div></div>' +
            '    <div class="col-6 col-md-4"><label class="form-label small mb-1">Ramp hint</label>' +
            '     <div id="sg_ramp_hint" class="small text-muted"></div></div>' +
            '   </div>' +
            '   <div class="text-center mt-2">' +
            '    <button id="sg_steel_preset" type="button" class="btn btn-outline-secondary btn-sm">Select blade stock...</button>' +
            '   </div>' +
            '   <div class="btn-group btn-group-sm mt-3">' +
            '    <button id="sg_steel_calculate" type="button" class="btn btn-success"><i class="bi bi-magic"></i> Generate Schedule</button>' +
            '   </div>' +
            '   <div class="small text-muted mt-1" id="sg_steel_info"></div>' +
            '  </div>' +
            '  <div class="sg-blade-stocks mt-3" style="display:none">' +
            '   <div class="text-center small">' +
            '    <button class="btn btn-link btn-sm preset" data-thick="1/16">1/16" .0625</button>' +
            '    <button class="btn btn-link btn-sm preset" data-thick="3/32">3/32" .09375</button>' +
            '    <button class="btn btn-link btn-sm preset" data-thick="1/8">1/8" .125</button>' +
            '    <button class="btn btn-link btn-sm preset" data-thick="5/32">5/32" .15625</button>' +
            '    <button class="btn btn-link btn-sm preset" data-thick="3/16">3/16" .1875</button>' +
            '    <button class="btn btn-link btn-sm preset" data-thick="1/4">1/4" .25</button>' +
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

        /* init steel form */
        initSteelForm();

        /* kind switcher */
        $('sg_kind_pottery').addEventListener('click', function () { setKind('pottery'); });
        $('sg_kind_steel').addEventListener('click', function () { setKind('steel'); });
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

    /* toggle between the pottery and steel forms */
    function setKind(kind) {
        currentKind = kind;
        setError('');
        $('sg_results').style.display = 'none';
        $('sg-pottery-form').style.display = kind === 'pottery' ? '' : 'none';
        $('sg-steel-form').style.display = kind === 'steel' ? '' : 'none';
        $('sg_kind_pottery').classList.toggle('active', kind === 'pottery');
        $('sg_kind_steel').classList.toggle('active', kind === 'steel');
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

    /* ── steel form initialization ───────────────────────────────────────── */

    function initSteelForm() {
        /* populate steel select optgroups by family */
        var steelSel = $('sg_steel');
        var families = ['Carbon', 'Carbon-Alloy', 'Tool', 'Stainless', 'Powder Stainless', 'Powder Tool'];
        var lastFamily = '';

        for (var id in SG_STEELS) {
            var s = SG_STEELS[id];
            if (!s) continue;
            var family = s.family;
            if (family !== lastFamily) {
                if (lastFamily !== '') {
                    var optGrp = document.createElement('optgroup');
                    optGrp.label = lastFamily;
                    steelSel.appendChild(optGrp);
                }
                lastFamily = family;
            }
            var opt = document.createElement('option');
            opt.value = id;
            opt.textContent = s.name;
            steelSel.appendChild(opt);
        }
        /* first entry selected by default */
        if (steelSel.options.length > 0) {
            steelSel.selectedIndex = 0;
        }

        /* rebuild treatment + target + HRC selects when steel changes */
        steelSel.addEventListener('change', function() {
            var steelId = this.value;
            rebuildTreatmentSelect(steelId);
            rebuildTargetSelect(steelId, $('sg_treatment').value);
            rebuildHrcSelect(steelId);
            updateSteelBlurb();
        });

        /* rebuild target select when treatment changes */
        $('sg_treatment').addEventListener('change', function() {
            rebuildTargetSelect($('sg_steel').value, this.value);
            updateSteelBlurb();
        });

        /* populate treatment + target + HRC selects for the selected steel */
        rebuildTreatmentSelect(steelSel.value);
        rebuildTargetSelect(steelSel.value, $('sg_treatment').value);
        rebuildHrcSelect(steelSel.value);
        updateSteelBlurb();

        /* thickness input */
        $('sg_steel_thickness').addEventListener('input', function() {
            updateThicknessHint(this.value);
        });

        /* soak min input */
        $('sg_soak_min').addEventListener('input', function() {
            updateSoakHint(this.value);
        });

        /* preset blade stock buttons */
        document.querySelectorAll('.sg-blade-stocks .preset').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var thick = this.getAttribute('data-thick');
                parseAndSetThick(thick);
            });
        });

        /* calculate button (steel form has its own; sg_calculate is the pottery one) */
        $('sg_steel_calculate').addEventListener('click', calculateSteel);

        /* update blurb initially */
        updateSteelBlurb();
    }

    function rebuildTreatmentSelect(steelId) {
        var tSel = $('sg_treatment');
        /* remove existing options except first blank */
        while (tSel.length > 1) { tSel.remove(1); }

        var steel = SG_STEELS[steelId];
        if (!steel) { return; }

        var treatments = [];
        if (steel.harden) treatments.push('harden');
        if (steel.temper) treatments.push('temper');
        if (steel.anneal) treatments.push('anneal');
        if (steel.normalize) treatments.push('normalize');

        for (var i = 0; i < treatments.length; i++) {
            var opt = document.createElement('option');
            opt.value = treatments[i];
            opt.textContent = treatments[i].charAt(0).toUpperCase() + treatments[i].slice(1);
            if (treatments[i] === 'harden') { opt.selected = true; }
            tSel.appendChild(opt);
        }
    }

    /* fill the target temperature drop-down with the selected steel's
       datasheet range for the chosen treatment, in 25 degF steps */
    function rebuildTargetSelect(steelId, tr) {
        var fSel = $('sg_target_f');
        while (fSel.length > 0) { fSel.remove(0); }

        var steel = SG_STEELS[steelId];
        var range = steel && steel[tr];
        if (!range || range.length < 2) { return; }

        var lo = range[0];
        var hi = range[1];
        var temps = [];
        if (hi > lo) {
            for (var t = lo; t <= hi; t += 25) { temps.push(t); }
            if (temps[temps.length - 1] !== hi) { temps.push(hi); }
        } else {
            temps.push(lo);
        }

        /* preselect the middle of the datasheet range */
        var mid = Math.floor((temps.length - 1) / 2);
        for (var i = 0; i < temps.length; i++) {
            var opt = document.createElement('option');
            opt.value = String(temps[i]);
            opt.textContent = temps[i] + '\u00B0F';
            if (i === mid) { opt.selected = true; }
            fSel.appendChild(opt);
        }
    }

    /* fill the HRC drop-down with the steel's advisable hardness range */
    function rebuildHrcSelect(steelId) {
        var hSel = $('sg_target_hrc');
        while (hSel.length > 0) { hSel.remove(0); }

        var steel = SG_STEELS[steelId];
        var m = String((steel && steel.hrc) || '').match(/(\d+)(?:\s*-\s*(\d+))?/);

        /* steels without a datasheet range get an empty marker option */
        if (!m) {
            var na = document.createElement('option');
            na.value = '';
            na.textContent = '\u2014';
            hSel.appendChild(na);
            return;
        }

        var lo = parseInt(m[1], 10);
        var hi = m[2] !== undefined ? parseInt(m[2], 10) : lo;
        var mid = Math.floor((lo + hi) / 2);
        for (var v = lo; v <= hi; v++) {
            var opt = document.createElement('option');
            opt.value = String(v);
            opt.textContent = v + ' HRC';
            if (v === mid) { opt.selected = true; }
            hSel.appendChild(opt);
        }
    }

    function updateSteelBlurb() {
        var steelId = $('sg_steel').value;
        var tr = $('sg_treatment').value;
        var steel = SG_STEELS[steelId];
        var hintEl = $('sg_soak_hint');
        var rampHintEl = $('sg_ramp_hint');
        var infoEl = $('sg_steel_info');

        if (!steel) { return; }

        /* soak hint */
        if (steel.soak && steel.soak[tr]) {
            var soak = steel.soak[tr];
            hintEl.textContent = 'Datasheet soak: ' + soak[0] + '-' + soak[1] + ' min';
        } else {
            var t = parseFloat($('sg_steel_thickness').value) || 0.125;
            var soakMin = sgSteelSoakMin(tr, t, steel);
            hintEl.textContent = 'Calculated soak: ' + soakMin + ' min (rule)';
        }

        /* ramp hint */
        var t = parseFloat($('sg_steel_thickness').value) || 0.125;
        var rate = sgRampRateF(t);
        rampHintEl.textContent = 'Ramp rate: ' + rate + '°F/hr';

        /* info line */
        var info = 'Quench: ' + steel.quench;
        infoEl.textContent = info;
    }

    function updateThicknessHint(val) {
        if (!val) { return; }
        var num = parseFloat(val);
        if (isNaN(num)) return;
        var rate = sgRampRateF(num);
        $('sg_ramp_hint').textContent = 'Ramp rate: ' + rate + '°F/hr';
        /* update soak hint */
        var tr = $('sg_treatment').value;
        if (tr) {
            updateSteelBlurb();
        }
    }

    function updateSoakHint(val) {
        if (!val) { return; }
        var num = parseFloat(val);
        if (isNaN(num)) return;
        var steelId = $('sg_steel').value;
        var tr = $('sg_treatment').value;
        var steel = SG_STEELS[steelId];
        var hintEl = $('sg_soak_hint');
        if (steel && steel.soak && steel.soak[tr]) {
            hintEl.textContent = 'Datasheet soak: ' + steel.soak[tr][0] + '-' + steel.soak[tr][1] + ' min';
        } else {
            hintEl.textContent = 'Calculated soak: ' + sgSteelSoakMin(tr, num, steel) + ' min (rule)';
        }
    }

    function parseAndSetThick(thickStr) {
        var map = {
            '1/16': '0.0625',
            '3/32': '0.09375',
            '1/8': '0.125',
            '5/32': '0.15625',
            '3/16': '0.1875',
            '1/4': '0.25'
        };
        var val = map[thickStr] || thickStr;
        $('sg_steel_thickness').value = val;
        $('sg_steel_thickness').dispatchEvent(new Event('input'));
    }

    /* ── calculate: pottery or steel ─────────────────────────────────────── */

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
        currentKind = 'pottery';
        render();
    }

    function calculateSteel() {
        var key = $('sg_steel').value;
        var tr = $('sg_treatment').value;
        var targetF = parseFloat($('sg_target_f').value);
        var thicknessIn = $('sg_steel_thickness').value;
        var soakMin = parseFloat($('sg_soak_min').value);

        if (!key) {
            setError('Select a steel.');
            return;
        }
        if (!tr) {
            setError('Select a treatment.');
            return;
        }
        if (isNaN(targetF) || targetF < 100 || targetF > 2500) {
            setError('Enter a valid target temperature (100-2500°F).');
            return;
        }
        if (isNaN(thicknessIn) || thicknessIn <= 0 || thicknessIn > 12) {
            setError('Enter a valid thickness (0.01-12 in).');
            return;
        }
        setError('');

        try {
            lastValues = sgGenerateSteelSchedule(key, tr, targetF, thicknessIn, soakMin);
            currentKind = 'steel';
            render();
        } catch (e) {
            setError('Error: ' + e.message);
        }
    }

    /* ── render ──────────────────────────────────────────────────────────── */

    function render() {
        var v = lastValues;

        /* show/hide forms */
        var potForm = $('sg-pottery-form');
        var steelForm = $('sg-steel-form');
        if (currentKind === 'pottery') {
            potForm.style.display = '';
            steelForm.style.display = 'none';
        } else {
            potForm.style.display = 'none';
            steelForm.style.display = '';
        }

        /* render summary */
        $('sg_summary').innerHTML = '';

        if (currentKind === 'pottery') {
            var peakF = Math.round(sgCToF(v.peak_temp_c));
            $('sg_summary').innerHTML =
                summaryCard('Peak Temp', peakF + '&deg;F') +
                summaryCard('Total Time', v.total_hours + ' hrs') +
                summaryCard('Segments', v.segment_count);
        } else {
            $('sg_summary').innerHTML =
                summaryCard('Peak Temp', v.peak_temp_f + '&deg;F') +
                summaryCard('Total Time', v.total_hours + ' hrs') +
                summaryCard('Segments', v.segment_count);
        }

        /* render warnings */
        $('sg_warnings').innerHTML = (v.warnings || []).map(function (w) {
            return '<div class="alert alert-' + w.severity + ' py-2 px-3 mt-2 mb-0 small">' + w.message + '</div>';
        }).join('');

        /* render segments */
        var rows = '';
        for (var i = 0; i < v.segments.length; i++) {
            var s = v.segments[i];
            rows += '<tr>' +
                '<td>' + (i + 1) + '</td>' +
                '<td>' + s.from + '&deg;F</td>' +
                '<td>' + s.to + '&deg;F</td>' +
                '<td>' + s.rate + '&deg;F/hr</td>' +
                '<td>' + (s.hold ? s.hold + ' min' : '&mdash;') + '</td>' +
                '<td class="small text-muted">' + s.note + '</td>' +
                '</tr>';
        }
        $('sg_segments').innerHTML = rows;

        /* save button name */
        $('sg_name').value = defaultName(
            currentKind === 'steel' ? $('sg_steel').value : $('sg_cone').value,
            currentKind === 'steel' ? $('sg_treatment').value : $('sg_type').value
        );

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
        var t = 0;
        var data = [];
        for (var i = 0; i < segs.length; i++) {
            var s = segs[i];
            if (i === 0) {
                data.push([0, Math.round(s.from)]);
            }
            if (s.rate > 0 && s.to !== s.from) {
                t += (s.to - s.from) / s.rate * 3600;  // seconds
            }
            data.push([Math.round(t), Math.round(s.to)]);
            if (s.hold > 0) {
                t += s.hold * 60;
                data.push([Math.round(t), Math.round(s.to)]);
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
        if (currentKind === 'pottery') {
            var cone = $('sg_cone').value;
            var type = $('sg_type').value;
            var mm = parseFloat($('sg_thickness').value);
            var tags = ['cone' + cone, type];
            if (!isNaN(mm) && mm > 0) {
                tags.push(mm + 'mm');
            }
            return tags;
        } else {  /* steel */
            var key = $('sg_steel').value;
            var tr = $('sg_treatment').value;
            var tin = $('sg_steel_thickness').value;
            var tags = sgSteelTags(key, tr, tin);
            var hrc = $('sg_target_hrc').value;
            if (hrc) { tags.push(hrc + 'hrc'); }
            return tags;
        }
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