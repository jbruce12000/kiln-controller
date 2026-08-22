'''Tests for the Pottery Firing Schedule Generator front-end module
(public/assets/js/schedule-generator.js). The pure algorithm functions are
top-level in that file, so they are extracted from the real file and
executed with quickjs, matching the approach in
test_frontend_schedule_display.py. Skipped if the quickjs module is not
installed.

All generated schedules are in Fahrenheit (units == 'f'): Orton cone peak
temperatures are published in Celsius and converted once at generation
time. The UI converts values for display to match config.temp_scale.'''

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
    ambient = re.search(r'\nvar SG_AMBIENT_F = (\d+);', src)
    assert ambient, 'SG_AMBIENT_F not found'
    context.eval('var SG_AMBIENT_F = %s;' % ambient.group(1))
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
    for value in (20, 120, 500, 600, 2232):
        assert abs(js.eval(back % value) - value) < 1e-9


def test_convert_rate(js):
    # rates scale by ratio only, no 32-degree offset
    assert js.eval("sgConvertRate(90, 'f', 'c')") == 50
    assert js.eval("sgConvertRate(50, 'c', 'f')") == 90
    assert js.eval("sgConvertRate(120, 'f', 'f')") == 120


########################################################################
# candling hold tiers (thickness of thickest piece -> hold minutes)
#
# sgCandlingHoldMin is the single source of truth: sgGenerateSchedule
# calls it, so these tiers are exactly what generated schedules get.
########################################################################

@pytest.mark.parametrize('mm,hold', [
    (1, 0), (8, 0), (11, 0), (12, 0), (19, 0),
    (20, 30), (21, 60), (25, 60), (40, 60),
])
def test_candling_hold_tiers(js, mm, hold):
    assert js.eval('sgCandlingHoldMin(%d)' % mm) == hold


########################################################################
# generated schedules vs reference outputs
#
# Every number below is Fahrenheit. Cone peaks originate as Orton °C data
# in SG_CONE_PEAKS_C and are rounded to whole °F at generation time
# (e.g. cone 6 = 1222 C -> 2232 F), so glaze ramps end at peak - 100 F.
########################################################################

# reference: glaze, cone 6, 8mm stoneware-equivalent input
REFERENCE_GLAZE_CONE6 = {
    "units": "f",
    "segments": [
        {"from": 70, "to": 120, "rate": 50, "hold": 0},   # room temp
        {"from": 120, "to": 500, "rate": 80, "hold": 0},
        {"from": 500, "to": 600, "rate": 60, "hold": 0},
        {"from": 600, "to": 2132, "rate": 120, "hold": 0},   # peak - 100
        {"from": 2132, "to": 2232, "rate": 40, "hold": 15},
    ],
    "peak_temp": 2232,
    "total_hours": 22.9,
    "segment_count": 5,
}

# reference: bisque, cone 6, 8mm
REFERENCE_BISQUE_CONE6 = {
    "units": "f",
    "segments": [
        {"from": 70, "to": 120, "rate": 50, "hold": 0},   # room temp
        {"from": 120, "to": 500, "rate": 80, "hold": 0},
        {"from": 500, "to": 600, "rate": 60, "hold": 0},
        {"from": 600, "to": 2232, "rate": 100, "hold": 20},
    ],
    "peak_temp": 2232,
    "total_hours": 24.1,
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
    result = gen(js, '06', 'glaze', 8)          # cone 06 = 999 C = 1830 F
    assert result['peak_temp'] == 1830
    assert abs(result['total_hours'] - 19.6) < 0.051
    assert result['segments'][3]['to'] == 1730  # peak - 100
    assert result['segments'][4]['to'] == 1830
    assert result['segments'][4]['hold'] == 15


def test_glaze_cone10_reference(js):
    result = gen(js, '10', 'glaze', 8)          # cone 10 = 1305 C = 2381 F
    assert result['peak_temp'] == 2381
    assert abs(result['total_hours'] - 24.2) < 0.051
    assert result['segments'][3]['to'] == 2281  # peak - 100


def test_bisque_thick_piece_gets_candling(js):
    result = gen(js, '6', 'bisque', 25)
    assert result['segments'][0]['hold'] == 60
    assert len(result['segments']) == 4         # bisque stays 4 segments
    assert result['segments'][3]['hold'] == 20  # bisque soak unchanged


########################################################################
# all cones produce sane schedules
########################################################################

EXPECTED_PEAKS_F = {
    '06': 1830, '05': 1888, '04': 1945, '03': 2014, '02': 2048,
    '01': 2079, '1': 2109, '2': 2124, '3': 2134, '4': 2167,
    '5': 2185, '6': 2232, '7': 2264, '8': 2305, '9': 2336, '10': 2381,
}


@pytest.mark.parametrize('cone', list(EXPECTED_PEAKS_F.keys()))
def test_all_cones_peak_temps(js, cone):
    result = gen(js, cone, 'glaze', 8)
    assert result['units'] == 'f'
    assert result['peak_temp'] == EXPECTED_PEAKS_F[cone]
    assert result['segments'][-1]['to'] == EXPECTED_PEAKS_F[cone]
    assert result['segments'][-2]['to'] == EXPECTED_PEAKS_F[cone] - 100


@pytest.mark.parametrize('cone', list(EXPECTED_PEAKS_F.keys()))
def test_all_cones_monotonic_and_complete(js, cone):
    result = gen(js, cone, 'glaze', 8)
    segs = result['segments']
    assert result['segment_count'] == len(segs)
    temps = [segs[0]['from']] + [s['to'] for s in segs]
    assert temps == sorted(temps)
    assert segs[0]['from'] == 70  # room temperature (SG_AMBIENT_F)
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


########################################################################
# total time arithmetic
########################################################################

def test_total_hours_is_sum_of_segment_durations(js):
    result = gen(js, '6', 'glaze', 21)  # 21mm adds a 60 min candling hold
    manual = 0.0
    for s in result['segments']:
        manual += (s['to'] - s['from']) / s['rate'] + s['hold'] / 60
    assert abs(result['total_hours'] - round(manual * 10) / 10) < 1e-9
