#!/usr/bin/env python

import os
import sys
import csv
import time
import argparse

from temp import to_c, to_display, delta_to_c

try:
        sys.dont_write_bytecode = True
        import config
        sys.dont_write_bytecode = False

except ImportError:
        print("Could not import config file.")
        print("Copy config.py.EXAMPLE to config.py and adapt it for your setup.")
        exit(1)


########################################################################
# Ziegler-Nichols open loop (process reaction curve) tuning
#
# The kiln is heated at full power and the temperature is recorded to a
# csv file. The heating curve is the process reaction curve. A tangent
# line is drawn through the steepest (mid) section of that curve and
# from it we measure:
#
#   L  - the dead time (lag): time between the start of the step and
#        where the tangent crosses the starting temperature.
#   T  - the time constant: the time it takes the tangent to span from
#        the starting temperature up to the final temperature.
#
# These two numbers feed the classic Ziegler-Nichols open loop rules.
#
# The classic ZN PID rule is aggressive and gives roughly a 25%
# overshoot (quarter amplitude decay). A kiln should not overshoot a
# target cone temperature, so this tuner defaults to the critically
# damped rule that eliminates overshoot.
#
# tuning rule          Kp        Ti       Td        overshoot
# --------------------------------------------------------------
# quarter_decay        1.2 T/L   2 L      0.5 L     ~25%
# some_overshoot       1.0 T/L   4 L      1.0 L     ~20%
# critically_damped    0.6 T/L   4 L      1.0 L     ~0%  (default)
#
# The values printed for config.py are in the units oven.py expects.
# NOTE: pid_ki in oven.py is inverted (iterm uses 1/ki), so the value
# printed here is Ti / Kp. A smaller pid_ki means MORE integral action.
#
# See: Ziegler & Nichols, "Optimum Settings for Automatic Controllers",
# ASME Transactions 64 (1942), pp. 759-768.

ZN_TABLES = {
    "quarter_decay": {
        "factor": 1.2,
        "ti": 2.0,
        "td": 0.5,
        "desc": "classic Ziegler-Nichols, quarter amplitude decay (~25% overshoot)",
    },
    "some_overshoot": {
        "factor": 1.0,
        "ti": 4.0,
        "td": 1.0,
        "desc": "Ziegler-Nichols, some overshoot (~20% overshoot)",
    },
    "critically_damped": {
        "factor": 0.6,
        "ti": 4.0,
        "td": 1.0,
        "desc": "Ziegler-Nichols, critically damped (no overshoot)",
    },
}

DEFAULT_METHOD = "critically_damped"


def recordprofile(csvfile, targettemp):
    '''heat the kiln from ambient to targettemp (celsius, internal
    scale) at max power and back, recording the temperature in the
    display scale every config.sensor_time_wait seconds.
    This produces the process reaction curve used for tuning.
    '''

    script_dir = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, script_dir + '/lib/')

    from oven import RealOven, SimulatedOven

    # open the file to log data to
    f = open(csvfile, 'w')
    csvout = csv.writer(f)
    csvout.writerow(['time', 'temperature'])

    # the tuner drives the oven directly, so the oven's background run()
    # thread must not try an automatic restart from a saved state file
    # (it needs an ovenwatcher, which the tuner never sets).
    config.automatic_restarts = False

    # construct the oven
    if config.simulate:
        oven = SimulatedOven()
        oven.target = targettemp * 2  # insures max heating for simulation
    else:
        oven = RealOven()

    # put the oven in a state the background run() thread ignores, so it
    # never drives the oven or busy-loops during the tuning run
    oven.state = "TUNING"

    # Main loop:
    #
    # * heat the oven to the target temperature at maximum burn.
    # * when we reach it turn the heating off completely.
    # * wait for it to decay back to the target again.
    # * quit
    #
    # We record the temperature every config.sensor_time_wait
    try:

        # heating to target
        temp = 0
        sleepfor = config.sensor_time_wait
        stage = "heating"
        while(temp <= targettemp):
            if config.simulate:
                oven.heat_then_cool()
            else:
                oven.output.heat(sleepfor)
            temp = oven.board.temp_sensor.temperature() + \
                delta_to_c(config.thermocouple_offset)

            print("stage = %s, actual = %.2f, target = %.2f" % (stage,to_display(temp),to_display(targettemp)))
            csvout.writerow([time.time(), to_display(temp)])
            f.flush()

        # overshoot past target and then cooling down to target
        stage = "cooling"
        if config.simulate:
            oven.target = 0
        while(temp >= targettemp):
            if config.simulate:
                oven.heat_then_cool()
            else:
                oven.output.cool(sleepfor)
            temp = oven.board.temp_sensor.temperature() + \
                delta_to_c(config.thermocouple_offset)

            print("stage = %s, actual = %.2f, target = %.2f" % (stage,to_display(temp),to_display(targettemp)))
            csvout.writerow([time.time(), to_display(temp)])
            f.flush()

    finally:
        f.close()
        # ensure we always shut the oven down!
        if not config.simulate:
            oven.output.cool(0)


def line(a, b, x):
    return a * x + b


def invline(a, b, y):
    return (y - b) / a


def plot(xdata, ydata,
         tangent_min, tangent_max, tangent_slope, tangent_offset,
         lower_crossing_x, upper_crossing_x):
    from matplotlib import pyplot

    minx = min(xdata)
    maxx = max(xdata)
    miny = min(ydata)
    maxy = max(ydata)

    pyplot.scatter(xdata, ydata)

    pyplot.plot([minx, maxx], [miny, miny], '--', color='purple')
    pyplot.plot([minx, maxx], [maxy, maxy], '--', color='purple')

    pyplot.plot(tangent_min[0], tangent_min[1], 'v', color='red')
    pyplot.plot(tangent_max[0], tangent_max[1], 'v', color='red')
    pyplot.plot([minx, maxx], [line(tangent_slope, tangent_offset, minx), line(tangent_slope, tangent_offset, maxx)], '--', color='red')

    pyplot.plot([lower_crossing_x, lower_crossing_x], [miny, maxy], '--', color='black')
    pyplot.plot([upper_crossing_x, upper_crossing_x], [miny, maxy], '--', color='black')

    pyplot.show()


def find_tangent(xdata, ydata, tangentdivisor):
    '''measure the dead time L and time constant T from the process
    reaction curve. The tangent line is drawn through two points on the
    mid section of the heating curve.
    '''
    # gather points for tangent line
    miny = min(ydata)
    maxy = max(ydata)
    midy = (maxy + miny) / 2
    yoffset = int((maxy - miny) / tangentdivisor)
    tangent_min = tangent_max = None
    for i in range(0, len(xdata)):
        rowx = xdata[i]
        rowy = ydata[i]

        if rowy >= (midy - yoffset) and tangent_min is None:
            tangent_min = (rowx, rowy)
        elif rowy >= (midy + yoffset) and tangent_max is None:
            tangent_max = (rowx, rowy)

    if tangent_min is None or tangent_max is None:
        raise ValueError(
            "could not find tangent points. is the heating curve "
            "monotonic? try a different --tangent_divisor.")
    if tangent_max[0] == tangent_min[0]:
        raise ValueError(
            "could not compute a tangent slope. the heating curve "
            "is too flat. try a different --tangent_divisor.")

    # calculate tangent line to the main temperature curve
    tangent_slope = (tangent_max[1] - tangent_min[1]) / (tangent_max[0] - tangent_min[0])
    if tangent_slope == 0:
        raise ValueError(
            "could not compute a tangent line. the heating curve "
            "is too flat. try a different --tangent_divisor.")
    tangent_offset = tangent_min[1] - line(tangent_slope, 0, tangent_min[0])

    # determine the point at which the tangent line crosses the
    # min/max temperatures
    lower_crossing_x = invline(tangent_slope, tangent_offset, miny)
    upper_crossing_x = invline(tangent_slope, tangent_offset, maxy)

    # compute Ziegler-Nichols process parameters
    L = lower_crossing_x - min(xdata)
    T = upper_crossing_x - lower_crossing_x

    if L <= 0 or T <= 0:
        raise ValueError(
            "invalid process parameters L=%s, T=%s. the heating curve "
            "does not look like a step response." % (L, T))

    return L, T, tangent_min, tangent_max, tangent_slope, tangent_offset, \
        lower_crossing_x, upper_crossing_x


def calculate(filename, method=DEFAULT_METHOD, tangentdivisor=8, showplot=False):
    '''parse the recorded tuning curve and print Ziegler-Nichols PID
    values ready to paste into config.py
    '''
    if tangentdivisor < 2:
        raise ValueError("--tangent_divisor must be >= 2")
    if method not in ZN_TABLES:
        raise ValueError("unknown tuning method %s" % method)

    # parse the csv file
    xdata = []
    ydata = []
    filemintime = None
    with open(filename) as f:
        for row in csv.DictReader(f):
            try:
                rowtime = float(row['time'])
                temp = float(row['temperature'])
                if filemintime is None:
                    filemintime = rowtime

                xdata.append(rowtime - filemintime)
                ydata.append(temp)
            except ValueError:
                continue  # just ignore bad values!

    if not xdata:
        raise ValueError("no data found in %s" % filename)

    # only use the heating portion of the curve (up to the first time
    # the maximum temperature is reached). the cooling portion is not
    # part of the process reaction curve.
    max_temp = max(ydata)
    heating_end = ydata.index(max_temp) + 1
    xdata = xdata[:heating_end]
    ydata = ydata[:heating_end]

    if len(xdata) < 2:
        raise ValueError("not enough heating data to tune against")

    L, T, tangent_min, tangent_max, tangent_slope, tangent_offset, \
        lower_crossing_x, upper_crossing_x = \
        find_tangent(xdata, ydata, tangentdivisor)

    rule = ZN_TABLES[method]

    # Ziegler-Nichols open loop PID
    Kp = rule["factor"] * (T / L)
    Ti = rule["ti"] * L
    Td = rule["td"] * L

    # oven.py uses an inverted integral: iterm += err * dt * (1/pid_ki)
    # so pid_ki = Ti / Kp makes the integral gain match Ki = Kp / Ti.
    pid_kp = Kp
    pid_ki = Ti / Kp
    pid_kd = Kp * Td

    # output the process model
    print("=" * 64)
    print("Ziegler-Nichols open loop tuning: %s" % method)
    print("  %s" % rule["desc"])
    print("-" * 64)
    print("  dead time  L = %8.1f s" % L)
    print("  time const T = %8.1f s" % T)
    print("  ratio     L/T = %8.3f" % (L / T))
    print("-" * 64)
    print("Copy these values into config.py:")
    print("  pid_kp = %s" % round(pid_kp, 3))
    print("  pid_ki = %s" % round(pid_ki, 3))
    print("  pid_kd = %s" % round(pid_kd, 3))
    print("-" * 64)
    print("NOTE: pid_ki is the inverted integral convention used by")
    print("oven.py (a smaller pid_ki gives MORE integral action).")
    print("Start with these values and fine tune from there.")

    if showplot:
        plot(xdata, ydata,
             tangent_min, tangent_max, tangent_slope, tangent_offset,
             lower_crossing_x, upper_crossing_x)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Kiln tuner')
    parser.add_argument('-c', '--calculate_only', action='store_true')
    parser.add_argument('-t', '--target_temp', type=float, default=400, help="Target temperature")
    parser.add_argument('-d', '--tangent_divisor', type=float, default=8, help="Adjust the tangent calculation to fit better. Must be >= 2 (default 8).")
    parser.add_argument('-m', '--method', default=DEFAULT_METHOD,
                        choices=list(ZN_TABLES.keys()),
                        help="Ziegler-Nichols tuning rule (default %s)" % DEFAULT_METHOD)
    parser.add_argument('-s', '--showplot', action='store_true', help="draw plot so you can see tangent line and possibly change")
    parser.add_argument('--csvfile', type=str, default="tuning.csv", help="tuning curve csv file (default tuning.csv)")
    args = parser.parse_args()

    target = args.target_temp
    # the cli argument is in the display scale (config.temp_scale),
    # the oven works in celsius internally
    target = to_c(target)
    tangentdivisor = args.tangent_divisor

    # default behavior is to record profile to csv file tuning.csv
    # and then calculate pid values and print them
    if args.calculate_only:
        calculate(args.csvfile, args.method, tangentdivisor, args.showplot)
    else:
        recordprofile(args.csvfile, target)
        calculate(args.csvfile, args.method, tangentdivisor, args.showplot)
