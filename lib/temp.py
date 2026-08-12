import config

########################################################################
# temperature unit conversions
#
# The server works internally in celsius. config.py settings that are
# temperatures (or temperature deltas) are written in the display scale
# (config.temp_scale). Convert at the boundaries:
#
#   to_c / delta_to_c        : display scale -> internal celsius
#   to_display / delta_to_display : internal celsius -> display scale
########################################################################

def c_to_f(value):
    return (value * 9 / 5) + 32


def f_to_c(value):
    return (5 / 9) * (value - 32)


def to_display(temp):
    '''convert an absolute celsius temperature to the display scale.'''
    if config.temp_scale.lower() == "f":
        return c_to_f(temp)
    return temp


def to_c(temp):
    '''convert an absolute display-scale temperature to celsius.'''
    if config.temp_scale.lower() == "f":
        return f_to_c(temp)
    return temp


def delta_to_display(delta):
    '''convert a celsius temperature difference to the display scale.'''
    if config.temp_scale.lower() == "f":
        return delta * (9 / 5)
    return delta


def delta_to_c(delta):
    '''convert a display-scale temperature difference to celsius.'''
    if config.temp_scale.lower() == "f":
        return delta * (5 / 9)
    return delta


def display_profile_data(data):
    '''convert a list of (time, celsius) points to the display scale.'''
    return [(t, to_display(temp)) for (t, temp) in data]


def display_pidstats(pidstats):
    '''convert pid stats (celsius internally) to the display scale.'''
    out = dict(pidstats)
    for key in ('setpoint', 'ispoint'):
        if key in out:
            out[key] = to_display(out[key])
    for key in ('err', 'errDelta', 'p', 'i', 'd'):
        if key in out:
            out[key] = delta_to_display(out[key])
    return out
