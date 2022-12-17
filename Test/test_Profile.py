from lib.oven import Profile
import os
import json

def get_profile():
    profile_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'storage', 'profiles', "test-fast.json"))
    print(profile_path)
    with open(profile_path) as infile:
        profile_json = json.dumps(json.load(infile))
    profile = Profile(profile_json)

    return profile


def test_get_target_temperature():
    profile = get_profile()

    temperature = profile.get_target_temperature(3000)
    assert int(temperature) == 178

    temperature = profile.get_target_temperature(6004)
    assert temperature == 801.0


def test_shift_remaining_segments():
    profile = get_profile()

    now = 6000
    shift_seconds = 100
    profile.shift_remaining_segments(now, shift_seconds)

    assert profile.data[0][0] == 0
    assert profile.data[1][0] == 3600
    assert profile.data[2][0] == 10900
    assert profile.data[3][0] == 14500
    assert profile.data[4][0] == 16500
    assert profile.data[5][0] == 19500


def test_get_next_point():
    profile = get_profile()

    now = 6000
    segment = profile.get_next_point(now)
    assert segment == 2

    now = 14405
    segment = profile.get_next_point(now)
    assert segment == 4
