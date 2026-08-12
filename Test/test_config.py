import config


def test_listening_port():
    assert config.listening_port == 9099


def test_cost_settings():
    assert config.kwh_rate == 0.1319
    assert config.kw_elements == 9.460
    assert config.currency_type == "$"


def test_pid_defaults():
    assert config.pid_kp == 3.47
    assert config.pid_ki == 37.154
    assert config.pid_kd == 111.864


def test_sensor_settings():
    assert config.sensor_time_wait == 2
    assert config.temperature_average_samples == 10


def test_throttle_settings():
    assert config.throttle_below_temp == 300
    assert config.throttle_percent == 20


def test_emergency_shutoff():
    assert config.emergency_shutoff_temp == 2264
    assert config.ignore_temp_too_high is False


def test_temp_scale():
    assert config.temp_scale == "f"


def test_thermocouple_selection():
    assert config.max31855 == 1
    assert config.max31856 == 0


def test_automatic_restart_settings():
    assert config.automatic_restarts is True
    assert config.automatic_restart_window == 15


def test_profiles_directory_points_at_storage():
    assert config.kiln_profiles_directory.endswith(
        'storage' + config.os.sep + 'profiles')
