'''Tests for the Pottery Firing Schedule Generator front-end module
(public/assets/js/schedule-generator.js). The pure algorithm functions are
top-level in that file, so they are extracted from the real file and
executed with quickjs, matching the approach in
test_frontend_schedule_display.py. Skipped if the quickjs module is not
installed.

The generator is a faithful port of ClayCalc's firing schedule generator
(https://claycalc.com/calculators/firing-schedule-generator). Like
ClayCalc's engines it works natively in Celsius: schedules carry
units == 'c', and the UI converts them for display to match
config.temp_scale. All expected values below were captured from
ClayCalc's live API in August 2026.'''

import json
import os
import re

import pytest

quickjs = pytest.importorskip('quickjs')

JS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                       'public', 'assets', 'js',
                                       'schedule-generator.js'))


def _balanced_end(src, open_idx):
    '''return the index just past the brace block opening at open_idx,
    including any trailing semicolon'''
    depth = 1
    i = open_idx + 1
    while depth > 0:
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
        i += 1
    if i < len(src) and src[i] == ';':
        i += 1
    return i


def extract(src, pattern):
    '''extract a top-level var declaration or function by regex'''
    m = re.search(pattern, src)
    if not m:
        raise AssertionError('pattern %r not found in %s' % (pattern, JS_PATH))
    if m.group(0).lstrip().startswith('function'):
        return src[m.start():_balanced_end(src, m.end() - 1)]
    # var declaration: from match through the closing brace of the object
    return src[m.start():_balanced_end(src, src.index('{', m.start()))]


@pytest.fixture(scope='module')
def js():
    src = open(JS_PATH).read()
    context = quickjs.Context()
    # scalar vars need a plain regex (extract() assumes a brace block)
    ambient = re.search(r'\nvar SG_AMBIENT_C = (\d+);', src)
    assert ambient, 'SG_AMBIENT_C not found'
    context.eval('var SG_AMBIENT_C = %s;' % ambient.group(1))
    context.eval(extract(src, r'\nvar SG_CONE_PEAKS_C = \{'))
    context.eval(extract(src, r'\nfunction sgCToF\([^)]*\)\s*\{'))
    context.eval(extract(src, r'\nfunction sgRateCToF\([^)]*\)\s*\{'))
    context.eval(extract(src, r'\nfunction sgConvertTemp\([^)]*\)\s*\{'))
    context.eval(extract(src, r'\nfunction sgConvertRate\([^)]*\)\s*\{'))
    context.eval(extract(src, r'\nfunction sgCandlingHoldMin\([^)]*\)\s*\{'))
    context.eval(extract(src, r'\nfunction sgGenerateSchedule\([^)]*\)\s*\{'))
    return context


def gen(js, cone, firing_type, mm):
    return json.loads(js.eval(
        'JSON.stringify(sgGenerateSchedule(%r, %r, %d))' % (cone, firing_type, mm)))


########################################################################
# unit conversions
########################################################################

def test_c_to_f(js):
    assert js.eval('sgCToF(0)') == 32
    assert js.eval('sgCToF(100)') == 212
    assert js.eval('sgCToF(1222)') == 2231.6


def test_rate_c_to_f(js):
    assert js.eval('sgRateCToF(50)') == 90
    assert js.eval('sgRateCToF(40)') == 72


def test_convert_temp(js):
    # same-unit conversion is a no-op
    assert js.eval("sgConvertTemp(212, 'f', 'f')") == 212
    assert js.eval("sgConvertTemp(100, 'c', 'c')") == 100
    # offset conversions
    assert js.eval("sgConvertTemp(32, 'f', 'c')") == 0
    assert js.eval("sgConvertTemp(212, 'f', 'c')") == 100
    assert js.eval("sgConvertTemp(0, 'c', 'f')") == 32
    assert js.eval("sgConvertTemp(999, 'c', 'f')") == 1830.2


def test_convert_temp_roundtrip(js):
    back = "sgConvertTemp(sgConvertTemp(%d, 'f', 'c'), 'c', 'f')"
    for value in (20, 120, 500, 600, 1222):
        assert abs(js.eval(back % value) - value) < 1e-9


def test_convert_rate(js):
    # rates scale by ratio only, no 32-degree offset
    assert js.eval("sgConvertRate(90, 'f', 'c')") == 50
    assert js.eval("sgConvertRate(50, 'c', 'f')") == 90
    assert js.eval("sgConvertRate(120, 'f', 'f')") == 120


########################################################################
# candling hold tiers (thickness of thickest piece -> hold minutes)
#
# Boundaries probed from ClayCalc's live API (Aug 2026): 8 mm -> no hold,
# 9 mm -> 30 min, 15 mm -> 30 min, 16 mm -> 60 min. sgGenerateSchedule
# calls this helper, so these tiers are exactly what schedules get.
########################################################################

@pytest.mark.parametrize('mm,hold', [
    (1, 0), (8, 0),
    (9, 30), (12, 30), (15, 30),
    (16, 60), (17, 60), (20, 60), (25, 60), (40, 60),
])
def test_candling_hold_tiers(js, mm, hold):
    assert js.eval('sgCandlingHoldMin(%d)' % mm) == hold


########################################################################
# generated schedules vs reference outputs
#
# Every number below is Celsius, exactly as returned by ClayCalc's
# engine. Glaze ends with a two-segment approach (peak - 100 C, then
# peak); bisque ramps straight to peak. The 500 -> 600 C segment crosses
# the quartz inversion at 573 C.
########################################################################

# reference: glaze, cone 6, 8mm stoneware-equivalent input
REFERENCE_GLAZE_CONE6 = {
    "units": "c",
    "segments": [
        {"from": 20, "to": 120, "rate": 50, "hold": 0},
        {"from": 120, "to": 500, "rate": 80, "hold": 0},
        {"from": 500, "to": 600, "rate": 60, "hold": 0},
        {"from": 600, "to": 1122, "rate": 120, "hold": 0},   # peak - 100
        {"from": 1122, "to": 1222, "rate": 40, "hold": 15},
    ],
    "peak_temp": 1222,
    "total_hours": 15.5,
    "segment_count": 5,
}

# reference: bisque, cone 6, 8mm
REFERENCE_BISQUE_CONE6 = {
    "units": "c",
    "segments": [
        {"from": 20, "to": 120, "rate": 50, "hold": 0},
        {"from": 120, "to": 500, "rate": 80, "hold": 0},
        {"from": 500, "to": 600, "rate": 60, "hold": 0},
        {"from": 600, "to": 1222, "rate": 100, "hold": 20},
    ],
    "peak_temp": 1222,
    "total_hours": 15,
    "segment_count": 4,
}


def _assert_matches(actual, expected):
    for key, exp in expected.items():
        got = actual[key]
        if key == 'total_hours':
            assert abs(got - exp) < 0.051, '%s: %r != %r' % (key, got, exp)
        elif key == 'segments':
            assert len(got) == len(exp)
            for a, b in zip(got, exp):
                for field in ('from', 'to', 'rate', 'hold'):
                    assert a[field] == b[field], \
                        '%s: %r != %r' % (field, a[field], b[field])
        else:
            assert got == exp, '%s: %r != %r' % (key, got, exp)


def test_glaze_cone6_reference(js):
    _assert_matches(gen(js, '6', 'glaze', 8), REFERENCE_GLAZE_CONE6)


def test_bisque_cone6_reference(js):
    _assert_matches(gen(js, '6', 'bisque', 8), REFERENCE_BISQUE_CONE6)


def test_glaze_cone06_reference(js):
    result = gen(js, '06', 'glaze', 8)
    assert result['peak_temp'] == 999
    assert abs(result['total_hours'] - 13.7) < 0.051
    assert result['segments'][3]['to'] == 899   # peak - 100
    assert result['segments'][4]['to'] == 999
    assert result['segments'][4]['hold'] == 15


def test_glaze_cone10_reference(js):
    result = gen(js, '10', 'glaze', 8)
    assert result['peak_temp'] == 1305
    assert abs(result['total_hours'] - 16.2) < 0.051
    assert result['segments'][3]['to'] == 1205  # peak - 100


def test_bisque_thick_piece_gets_candling(js):
    result = gen(js, '6', 'bisque', 25)
    assert result['segments'][0]['hold'] == 60
    assert len(result['segments']) == 4         # bisque stays 4 segments
    assert result['segments'][3]['hold'] == 20  # bisque soak unchanged


def test_quartz_inversion_is_crossed_slowly(js):
    # the 500 -> 600 C segment must bracket the 573 C inversion point
    for cone in ('06', '6', '10'):
        for ftype in ('glaze', 'bisque'):
            s = gen(js, cone, ftype, 8)['segments'][2]
            assert s['from'] <= 573 <= s['to']
            assert s['rate'] == 60


def test_segment_notes_match_claycalc(js):
    notes = [s['note'] for s in gen(js, '6', 'glaze', 8)['segments']]
    assert notes[0] == 'Steam & mechanical water release'
    assert notes[1] == 'Chemical water & organic burnout'
    assert notes[2] == 'Quartz inversion zone \u2014 573\u00b0C critical'
    assert notes[3] == 'Approach peak temperature'
    assert notes[4] == 'Final approach & soak'


########################################################################
# all cones produce sane schedules
########################################################################

EXPECTED_PEAKS_C = {
    '06': 999, '05': 1031, '04': 1063, '03': 1101, '02': 1120,
    '01': 1137, '1': 1154, '2': 1162, '3': 1168, '4': 1186,
    '5': 1196, '6': 1222, '7': 1240, '8': 1263, '9': 1280, '10': 1305,
}


@pytest.mark.parametrize('cone', list(EXPECTED_PEAKS_C.keys()))
def test_all_cones_peak_temps(js, cone):
    result = gen(js, cone, 'glaze', 8)
    assert result['units'] == 'c'
    assert result['peak_temp'] == EXPECTED_PEAKS_C[cone]
    assert result['segments'][-1]['to'] == EXPECTED_PEAKS_C[cone]
    assert result['segments'][-2]['to'] == EXPECTED_PEAKS_C[cone] - 100


@pytest.mark.parametrize('cone', list(EXPECTED_PEAKS_C.keys()))
def test_all_cones_monotonic_and_complete(js, cone):
    result = gen(js, cone, 'glaze', 8)
    segs = result['segments']
    assert result['segment_count'] == len(segs)
    temps = [segs[0]['from']] + [s['to'] for s in segs]
    assert temps == sorted(temps)
    assert segs[0]['from'] == 20
    for s in segs:
        assert s['rate'] > 0
        assert s['hold'] >= 0


########################################################################
# thickness warnings
########################################################################

@pytest.mark.parametrize('mm,warned', [(8, False), (20, False), (21, True), (40, True)])
def test_thick_piece_warning(js, mm, warned):
    result = gen(js, '6', 'glaze', mm)
    has_warning = len(result['warnings']) > 0
    assert has_warning is warned


def test_thick_piece_warning_shape(js):
    # ClayCalc returns {message, severity} objects; we mirror that so the
    # renderer can style by severity
    w = gen(js, '6', 'bisque', 25)['warnings']
    assert len(w) == 1
    assert w[0]['severity'] == 'warning'
    assert '>20mm' in w[0]['message']


########################################################################
# total time arithmetic
########################################################################

def test_total_hours_is_sum_of_segment_durations(js):
    result = gen(js, '6', 'glaze', 16)  # 16mm adds a 60 min candling hold
    manual = 0.0
    for s in result['segments']:
        manual += (s['to'] - s['from']) / s['rate'] + s['hold'] / 60
    assert abs(result['total_hours'] - round(manual * 10) / 10) < 1e-9
