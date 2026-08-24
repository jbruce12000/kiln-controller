import config


def test_listening_port():
    assert config.listening_port == 9099


def test_cost_settings():
    assert config.kwh_rate == 0.1319
    assert config.kw_elements == 9.460
    assert config.currency_type == "$"


def test_sensor_settings():
    assert config.sensor_time_wait == 2
    assert config.temperature_average_samples == 10


def test_throttle_settings():
    assert config.throttle_below_temp == 300
    assert config.throttle_percent == 20


def test_emergency_shutoff():
    assert config.emergency_shutoff_temp == 2264
    assert config.ignore_temp_too_high is False


def test_emergency_heat_rate():
    assert config.emergency_heat_rate == 23
    assert config.emergency_heat_rate_window == 22.5
    assert config.ignore_heat_rate_too_low is False


def test_temp_scale():
    assert config.temp_scale == "f"


def test_thermocouple_selection():
    assert config.max31855 == 1
    assert config.max31856 == 0


def test_automatic_restart_settings():
    assert config.automatic_restarts is True
    assert config.automatic_restart_window == 15


def test_alert_thresholds():
    '''thresholds tuned in the alerts section of config.py. ids line up
    with the alert registry in lib/alerts.py'''
    assert config.cooled_safe_temp == 150
    assert config.relay_stuck_on_rise == 25
    assert config.relay_stuck_on_window == 10
    assert config.temp_implausible_jump == 50
    assert config.tc_error_percent_limit == 30
    assert config.catch_up_stalled_minutes == 15
    assert config.alert_webhook_timeout == 10


def test_profiles_directory_points_at_storage():
    assert config.kiln_profiles_directory.endswith(
        'storage' + config.os.sep + 'profiles')
