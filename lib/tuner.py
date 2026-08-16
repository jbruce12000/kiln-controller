import os
import re
import time
import logging

import config
from temp import to_display, delta_to_c

log = logging.getLogger(__name__)

########################################################################
# Ziegler-Nichols open loop (process reaction curve) tuning
#
# See kiln-tuner.py for the full theory. This module wraps the same
# logic for use inside the running kiln-controller process.
#
# The tuner drives the oven directly (bypassing PID) to produce a
# process reaction curve, then fits a tangent line to the steepest
# section and derives L (dead time) and T (time constant) for the
# Ziegler-Nichols formulas.

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


def _line(a, b, x):
    return a * x + b


def _invline(a, b, y):
    return (y - b) / a


def _find_tangent(xdata, ydata, tangentdivisor):
    '''measure the dead time L and time constant T from the process
    reaction curve.'''
    miny = min(ydata)
    maxy = max(ydata)
    midy = (maxy + miny) / 2
    yoffset = int((maxy - miny) / tangentdivisor)
    tangent_min = tangent_max = None
    for i in range(len(xdata)):
        rowx = xdata[i]
        rowy = ydata[i]
        if rowy >= (midy - yoffset) and tangent_min is None:
            tangent_min = (rowx, rowy)
        elif rowy >= (midy + yoffset) and tangent_max is None:
            tangent_max = (rowx, rowy)

    if tangent_min is None or tangent_max is None:
        raise ValueError(
            "could not find tangent points. is the heating curve "
            "monotonic? try a different tangent divisor.")
    if tangent_max[0] == tangent_min[0]:
        raise ValueError(
            "could not compute a tangent slope. the heating curve "
            "is too flat. try a different tangent divisor.")

    tangent_slope = ((tangent_max[1] - tangent_min[1]) /
                     (tangent_max[0] - tangent_min[0]))
    if tangent_slope == 0:
        raise ValueError(
            "could not compute a tangent line. the heating curve "
            "is too flat. try a different tangent divisor.")
    tangent_offset = tangent_min[1] - _line(tangent_slope, 0, tangent_min[0])

    lower_crossing_x = _invline(tangent_slope, tangent_offset, miny)
    upper_crossing_x = _invline(tangent_slope, tangent_offset, maxy)

    L = lower_crossing_x - min(xdata)
    T = upper_crossing_x - lower_crossing_x

    if L <= 0 or T <= 0:
        raise ValueError(
            "invalid process parameters L=%s, T=%s. the heating curve "
            "does not look like a step response." % (L, T))

    return L, T


class Tuner:
    '''Drives the oven at full power to produce a process reaction curve,
    then computes Ziegler-Nichols PID values and applies them to
    config.py.'''

    IDLE = "IDLE"
    HEATING = "HEATING"
    COOLING = "COOLING"
    CALCULATING = "CALCULATING"
    DONE = "DONE"
    ERROR = "ERROR"

    def __init__(self, oven):
        self.oven = oven
        self.state = self.IDLE
        self.csv_data = []
        self.pid_values = None
        self.error = None
        self.target_temp_c = None
        self.start_time = None
        self.method = DEFAULT_METHOD
        self.tangent_divisor = 8
        self._stop_requested = False

    def start(self, target_temp_c, method=DEFAULT_METHOD, tangent_divisor=8):
        '''Run the full tuning sequence. Must be called from a gevent
        greenlet or background thread since it blocks during recording.'''
        if self.oven.state not in ("IDLE", "TUNING"):
            log.error("cannot tune, oven state is %s" % self.oven.state)
            self.state = self.ERROR
            self.error = "oven is busy (state: %s)" % self.oven.state
            return

        self.state = self.HEATING
        self.phase = "heating"
        self.csv_data = []
        self.pid_values = None
        self.error = None
        self.target_temp_c = target_temp_c
        self.start_time = time.time()
        self.method = method
        self.tangent_divisor = tangent_divisor
        self._stop_requested = False

        log.info("tuner starting, target=%.1f %s, method=%s" %
                 (to_display(target_temp_c), config.temp_scale, method))

        # take control of the oven
        self.oven.state = "TUNING"
        self.oven.target = target_temp_c

        try:
            self._record(target_temp_c)

            if self._stop_requested:
                return

            self.state = self.CALCULATING
            self.phase = None
            self._calculate()

            if not self._stop_requested:
                self._apply_pid()
                self.state = self.DONE
                log.info("tuner done, kp=%.3f ki=%.3f kd=%.3f" %
                         (self.pid_values["kp"], self.pid_values["ki"],
                          self.pid_values["kd"]))
        except Exception as e:
            log.error("tuner error: %s" % e)
            self.state = self.ERROR
            self.error = str(e)
        finally:
            # always shut off the relay and return oven to idle
            try:
                if not config.simulate:
                    self.oven.output.cool(0)
                else:
                    self.oven.target = 0
            except Exception:
                pass
            self.oven.state = "IDLE"
            self.oven.heat = 0

    def _record(self, target_temp_c):
        '''Heat to target, then cool back to target, recording temperature
        every config.sensor_time_wait seconds.'''
        sleepfor = config.sensor_time_wait
        using_sim = config.simulate

        # --- heating phase ---
        self.phase = "heating"
        self.oven.heat = 1
        while True:
            if self._stop_requested:
                return

            if using_sim:
                self.oven.heat_then_cool()
                # SimulatedOven sets heat = time_step * pid which can
                # exceed 1.0; clamp so the OvenWatcher broadcasts a
                # sane 0-1 value to the frontend.
                self.oven.heat = min(self.oven.heat, 1.0)
            else:
                self.oven.output.heat(sleepfor)

            temp = (self.oven.board.temp_sensor.temperature() +
                    delta_to_c(config.thermocouple_offset))
            self.csv_data.append((time.time(), to_display(temp)))

            # update oven attributes so OvenWatcher broadcasts progress
            self.oven.runtime = time.time() - self.start_time
            self.oven.target = target_temp_c
            self.oven.heat = 1

            log.debug("tuner heating: actual=%.2f target=%.2f" %
                      (to_display(temp), to_display(target_temp_c)))

            if to_display(temp) >= to_display(target_temp_c):
                break

            # safety check
            if to_display(temp) >= config.emergency_shutoff_temp:
                raise ValueError(
                    "emergency shutoff: temperature %.1f reached "
                    "emergency_shutoff_temp %.1f" %
                    (to_display(temp), config.emergency_shutoff_temp))

        if self._stop_requested:
            return

        # --- cooling phase ---
        self.phase = "cooling"
        self.oven.heat = 0
        if using_sim:
            self.oven.target = 0

        while True:
            if self._stop_requested:
                return

            if using_sim:
                self.oven.heat_then_cool()
                self.oven.heat = 0
            else:
                self.oven.output.cool(sleepfor)

            temp = (self.oven.board.temp_sensor.temperature() +
                    delta_to_c(config.thermocouple_offset))
            self.csv_data.append((time.time(), to_display(temp)))

            self.oven.runtime = time.time() - self.start_time
            self.oven.heat = 0

            log.debug("tuner cooling: actual=%.2f target=%.2f" %
                      (to_display(temp), to_display(target_temp_c)))

            if to_display(temp) <= to_display(target_temp_c):
                break

    def _calculate(self):
        '''Parse recorded data and compute Ziegler-Nichols PID values.'''
        tangentdivisor = self.tangent_divisor
        method = self.method

        if tangentdivisor < 2:
            raise ValueError("tangent_divisor must be >= 2")
        if method not in ZN_TABLES:
            raise ValueError("unknown tuning method %s" % method)

        # parse recorded data
        xdata = []
        ydata = []
        if not self.csv_data:
            raise ValueError("no tuning data recorded")

        filemintime = self.csv_data[0][0]
        for rowtime, temp in self.csv_data:
            xdata.append(rowtime - filemintime)
            ydata.append(temp)

        if len(xdata) < 2:
            raise ValueError("not enough data points to tune")

        # only use the heating portion (up to first time max temp is reached)
        max_temp = max(ydata)
        heating_end = ydata.index(max_temp) + 1
        xdata = xdata[:heating_end]
        ydata = ydata[:heating_end]

        if len(xdata) < 2:
            raise ValueError("not enough heating data to tune against")

        L, T = _find_tangent(xdata, ydata, tangentdivisor)

        rule = ZN_TABLES[method]
        Kp = rule["factor"] * (T / L)
        Ti = rule["ti"] * L
        Td = rule["td"] * L

        # oven.py uses inverted integral: iterm += err * dt * (1/pid_ki)
        # so pid_ki = Ti / Kp makes integral gain match Ki = Kp / Ti
        pid_kp = Kp
        pid_ki = Ti / Kp
        pid_kd = Kp * Td

        self.pid_values = {
            "kp": round(pid_kp, 3),
            "ki": round(pid_ki, 3),
            "kd": round(pid_kd, 3),
        }
        log.info("tuner calculated: L=%.1f T=%.1f kp=%.3f ki=%.3f kd=%.3f" %
                 (L, T, pid_kp, pid_ki, pid_kd))

    def _apply_pid(self):
        '''Write the calculated PID values into config.py and reload.'''
        if not self.pid_values:
            return

        kp = self.pid_values["kp"]
        ki = self.pid_values["ki"]
        kd = self.pid_values["kd"]

        # read current config.py
        config_path = config.__file__
        with open(config_path, 'r') as f:
            text = f.read()

        # replace pid lines
        text = re.sub(r'pid_kp\s*=\s*[\d.]+', 'pid_kp = %s' % kp, text)
        text = re.sub(r'pid_ki\s*=\s*[\d.]+', 'pid_ki = %s' % ki, text)
        text = re.sub(r'pid_kd\s*=\s*[\d.]+', 'pid_kd = %s' % kd, text)

        # validate syntax before writing
        compile(text, 'config.py', 'exec')

        # write the file
        with open(config_path, 'w') as f:
            f.write(text)

        log.info("tuner wrote pid_kp=%.3f pid_ki=%.3f pid_kd=%.3f to %s" %
                 (kp, ki, kd, config_path))

        # reload config module
        cached = getattr(config, '__cached__', None)
        if cached:
            try:
                os.remove(cached)
            except OSError:
                pass
        import importlib
        importlib.reload(config)

    def stop(self):
        '''Abort tuning. The record loop will exit on next iteration.'''
        self._stop_requested = True
        log.info("tuner stop requested")

    def get_status(self):
        '''Return current tuning status.'''
        elapsed = 0
        if self.start_time:
            elapsed = time.time() - self.start_time

        temperature = None
        try:
            temperature = to_display(
                self.oven.board.temp_sensor.temperature() +
                delta_to_c(config.thermocouple_offset))
        except Exception:
            pass

        return {
            "state": self.state,
            "phase": getattr(self, 'phase', None),
            "temperature": temperature,
            "target": to_display(self.target_temp_c) if self.target_temp_c else None,
            "elapsed": round(elapsed),
            "data_points": len(self.csv_data),
            "pid_values": self.pid_values,
            "method": self.method,
            "error": self.error,
        }
