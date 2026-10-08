import threading
import time
import datetime
import logging
import json
import config
import os
import digitalio
import adafruit_bitbangio as bitbangio
import statistics
from temp import to_c, to_display, delta_to_c, delta_to_display, display_pidstats

log = logging.getLogger(__name__)

# run-end reasons for abort_run(). 'completed' and 'stopped' are normal
# operation; anything else is an abort worth a run_aborted alert.
END_COMPLETED = 'completed'
END_STOPPED = 'stopped'

class DupFilter(object):
    def __init__(self):
        self.msgs = set()

    def filter(self, record):
        rv = record.msg not in self.msgs
        self.msgs.add(record.msg)
        return rv

class Duplogger():
    def __init__(self):
        self.log = logging.getLogger("%s.dupfree" % (__name__))
        dup_filter = DupFilter()
        self.log.addFilter(dup_filter)
    def logref(self):
        return self.log

duplog = Duplogger().logref()

class Output(object):
    '''This represents a GPIO output that controls a solid
    state relay to turn the kiln elements on and off.
    inputs
        config.gpio_heat
        config.gpio_heat_invert
    '''
    def __init__(self):
        self.active = False
        self.heater = digitalio.DigitalInOut(config.gpio_heat) 
        self.heater.direction = digitalio.Direction.OUTPUT 
        self.off = config.gpio_heat_invert
        self.on = not self.off

    def heat(self,sleepfor):
        self.heater.value = self.on
        time.sleep(sleepfor)

    def cool(self,sleepfor):
        '''no active cooling, so sleep'''
        self.heater.value = self.off
        time.sleep(sleepfor)

# wrapper for blinka board
class Board(object):
    '''This represents a blinka board where this code
    runs.
    '''
    def __init__(self):
        log.info("board: %s" % (self.name))
        self.temp_sensor.start()

class RealBoard(Board):
    '''Each board has a thermocouple board attached to it.
    Any blinka board that supports SPI can be used. The
    board is automatically detected by blinka.
    '''
    def __init__(self):
        self.name = None
        self.load_libs()
        self.temp_sensor = self.choose_tempsensor()
        Board.__init__(self) 

    def load_libs(self):
        import board
        self.name = board.board_id

    def choose_tempsensor(self):
        if config.max31855:
            return Max31855()
        if config.max31856:
            return Max31856()

class SimulatedBoard(Board):
    '''Simulated board used during simulations.
    See config.simulate
    '''
    def __init__(self):
        self.name = "simulated"
        self.temp_sensor = TempSensorSimulated()
        Board.__init__(self) 

class TempSensor(threading.Thread):
    '''Used by the Board class. Each Board must have
    a TempSensor.
    '''
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.time_step = config.sensor_time_wait
        self.status = ThermocoupleTracker()

class TempSensorSimulated(TempSensor):
    '''Simulates a temperature sensor '''
    def __init__(self):
        TempSensor.__init__(self)
        self.simulated_temperature = to_c(config.sim_t_env)
    def temperature(self):
        return self.simulated_temperature

class TempSensorReal(TempSensor):
    '''real temperature sensor that takes many measurements
       during the time_step
       inputs
           config.temperature_average_samples 
    '''
    def __init__(self):
        TempSensor.__init__(self)
        self.sleeptime = self.time_step / float(config.temperature_average_samples)
        self.temptracker = TempTracker() 
        self.spi_setup()
        self.cs = digitalio.DigitalInOut(config.spi_cs)

    def spi_setup(self):
        if(hasattr(config,'spi_sclk') and
           hasattr(config,'spi_mosi') and
           hasattr(config,'spi_miso')):
            self.spi = bitbangio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
            log.info("Software SPI selected for reading thermocouple")
        else:
            import board
            self.spi = board.SPI();
            log.info("Hardware SPI selected for reading thermocouple")

    def get_temperature(self):
        '''read temp from tc. thermocouple libs report celsius and the
        server always works in celsius, so no conversion is done here.
        conversion to the display scale happens at the api boundaries.'''
        try:
            temp = self.raw_temp() # raw_temp provided by subclasses
            self.status.good()
            return temp
        except ThermocoupleError as tce:
            raw = getattr(tce, "orig_message", None)
            if raw and raw != tce.message:
                detail = "%s (raw: %s)" % (tce.message, raw)
            else:
                detail = tce.message
            if tce.ignore:
                log.error("Problem reading temp (ignored) %s" % (detail))
                self.status.good()
            else:
                # exc_info logs the traceback including the chained
                # underlying RuntimeError, so "unknown" errors can be
                # diagnosed from the log.
                log.error("Problem reading temp %s" % (detail), exc_info=True)
                self.status.bad()
        return None

    def temperature(self):
        '''average temp over a duty cycle'''
        return self.temptracker.get_avg_temp()

    def run(self):
        while True:
            temp = self.get_temperature()
            if temp:
                self.temptracker.add(temp)
            time.sleep(self.sleeptime)

class TempTracker(object):
    '''creates a sliding window of N temperatures per
       config.sensor_time_wait
    '''
    def __init__(self):
        self.size = config.temperature_average_samples
        # start empty: seeding with zeros made the median report 0 degC
        # until the window filled, hiding the first real readings
        self.temps = []

    def add(self,temp):
        self.temps.append(temp)
        while(len(self.temps) > self.size):
            del self.temps[0]

    def get_avg_temp(self, chop=25):
        '''
        take the median of the given values. this used to take an avg
        after getting rid of outliers. median works better.
        '''
        if not self.temps:
            # no reading yet; report zero rather than crash
            return 0
        return statistics.median(self.temps)

class ThermocoupleTracker(object):
    '''Keeps sliding window to track successful/failed calls to get temp
       over the last two duty cycles.
    '''
    def __init__(self):
        self.size = config.temperature_average_samples * 2 
        self.status = [True for i in range(self.size)]
        # percent of failed reads over the rolling window that counts as
        # "too many errors" (alert + possible abort, see alerts section
        # of config.py)
        self.limit = config.tc_error_percent_limit

    def good(self):
        '''True is good!'''
        self.status.append(True)
        del self.status[0]

    def bad(self):
        '''False is bad!'''
        self.status.append(False)
        del self.status[0]

    def error_percent(self):
        errors = sum(i == False for i in self.status) 
        return (errors/self.size)*100

    def duty_cycle_errors(self):
        '''number of failed reads within the most recent duty cycle.
           the window holds temperature_average_samples * 2 reads (two
           duty cycles); the newest half is the current one.'''
        samples = int(self.size / 2)
        return sum(1 for ok in self.status[-samples:] if ok == False)

    def over_error_limit(self):
        if self.error_percent() > self.limit:
            return True
        return False

class Max31855(TempSensorReal):
    '''each subclass expected to handle errors and get temperature'''
    def __init__(self):
        TempSensorReal.__init__(self)
        log.info("thermocouple MAX31855")
        import adafruit_max31855
        self.thermocouple = adafruit_max31855.MAX31855(self.spi, self.cs)

    def raw_temp(self):
        try:
            return self.thermocouple.temperature_NIST
        except RuntimeError as rte:
            if rte.args and rte.args[0]:
                raise Max31855_Error(rte.args[0]) from rte
            # Bare RuntimeError() with no message has been seen from
            # blinka/spi layers; keep the repr so the logs show more
            # than just "unknown".
            raise Max31855_Error(repr(rte)) from rte

class ThermocoupleError(Exception):
    '''
    thermocouple exception parent class to handle mapping of error messages
    and make them consistent across adafruit libraries. Also set whether
    each exception should be ignored based on settings in config.py.
    '''
    def __init__(self, message):
        self.ignore = False
        self.message = message
        self.map_message()
        self.set_ignore()
        super().__init__(self.message)

    def set_ignore(self):
        if self.message == "not connected" and config.ignore_tc_lost_connection == True:
            self.ignore = True
        if self.message == "short circuit" and config.ignore_tc_short_errors == True:
            self.ignore = True
        if self.message == "unknown" and config.ignore_tc_unknown_error == True:
            self.ignore = True
        if self.message == "cold junction range fault" and config.ignore_tc_cold_junction_range_error == True:
            self.ignore = True
        if self.message == "thermocouple range fault" and config.ignore_tc_range_error == True:
            self.ignore = True
        if self.message == "cold junction temp too high" and config.ignore_tc_cold_junction_temp_high == True:
            self.ignore = True
        if self.message == "cold junction temp too low" and config.ignore_tc_cold_junction_temp_low == True:
            self.ignore = True
        if self.message == "thermocouple temp too high" and config.ignore_tc_temp_high == True:
            self.ignore = True
        if self.message == "thermocouple temp too low" and config.ignore_tc_temp_low == True:
            self.ignore = True
        if self.message == "voltage too high or low" and config.ignore_tc_voltage_error == True:
            self.ignore = True

    def map_message(self):
        try:
            self.message = self.map[self.orig_message]
        except KeyError:
            self.message = "unknown"

class Max31855_Error(ThermocoupleError):
    '''
    All children must set self.orig_message and self.map
    '''
    def __init__(self, message):
        self.orig_message = message
        # this purposefully makes "fault reading" and
        # "Total thermoelectric voltage out of range..." unknown errors
        self.map = {
            "thermocouple not connected" : "not connected",
            "short circuit to ground" : "short circuit",
            "short circuit to power" : "short circuit",
            }
        super().__init__(message)

class Max31856_Error(ThermocoupleError):
    def __init__(self, message):
        self.orig_message = message
        self.map = {
            "cj_range" : "cold junction range fault",
            "tc_range" : "thermocouple range fault",
            "cj_high"  : "cold junction temp too high",
            "cj_low"   : "cold junction temp too low",
            "tc_high"  : "thermocouple temp too high",
            "tc_low"   : "thermocouple temp too low",
            "voltage"  : "voltage too high or low", 
            "open_tc"  : "not connected"
            }
        super().__init__(message)

class Max31856(TempSensorReal):
    '''each subclass expected to handle errors and get temperature'''
    def __init__(self):
        TempSensorReal.__init__(self)
        log.info("thermocouple MAX31856")
        import adafruit_max31856
        self.thermocouple = adafruit_max31856.MAX31856(self.spi,self.cs,
                                        thermocouple_type=config.thermocouple_type)
        if (config.ac_freq_50hz == True):
            self.thermocouple.noise_rejection = 50
        else:
            self.thermocouple.noise_rejection = 60

    def raw_temp(self):
        # The underlying adafruit library does not throw exceptions
        # for thermocouple errors. Instead, they are stored in 
        # dict named self.thermocouple.fault. Here we check that
        # dict for errors and raise an exception.
        # and raise Max31856_Error(message)
        temp = self.thermocouple.temperature
        for k,v in self.thermocouple.fault.items():
            if v:
                raise Max31856_Error(k)
        return temp

class Oven(threading.Thread):
    '''parent oven class. this has all the common code
       for either a real or simulated oven'''
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.temperature = 0
        self.time_step = config.sensor_time_wait
        self.alert_manager = None
        # set by set_ovenwatcher() after construction; the control
        # thread starts in __init__ (subclasses) and may attempt an
        # automatic restart before the watcher is attached, so this
        # defaults to None and automatic_restart() tolerates it.
        self.ovenwatcher = None
        # always-on detector state that must survive across runs.
        # None means "no previous reading yet".
        self.last_plausible_temp = None
        self.relay_off_temps = []
        # one-shot per process life: only decide once whether a past
        # outage left an unresumed firing behind
        self.restart_outage_checked = False
        self.cooled_safe_armed_for = None
        self.reset()
        # each firing gets an increasing run_sequence. ended_run_sequence
        # remembers the highest sequence that has finished so scheduled
        # firings chained after a run can wait for its real end (catch-up
        # can stretch a firing past its nominal profile duration).
        self.run_sequence = 0
        self.ended_run_sequence = 0
        self.idle_since = time.time()

    def reset(self):
        self.cost = 0
        self.state = "IDLE"
        self.profile = None
        self.start_time = 0
        self.runtime = 0
        self.totaltime = 0
        self.target = 0
        self.heat = 0
        self.heat_rate = 0
        self.heat_rate_temps = []
        self.emergency_heat_rate_temps = []
        self.pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
        self.catching_up = False
        # how long the current catch-up stall has lasted (see
        # check_catch_up_stalled); reset ends any measured episode
        self.catch_up_since = None
        self.catch_up_alerted = False

    @staticmethod
    def get_start_from_temperature(profile, temp):
        target_temp = profile.get_target_temperature(0)
        if temp > target_temp + 5:
            startat = profile.find_next_time_from_temperature(temp)
            log.info("seek_start is in effect, starting at: {} s, {} deg".format(round(startat), round(to_display(temp))))
        else:
            startat = 0
        return startat

    def set_heat_rate(self,runtime,temp):
        '''heat rate is the heating rate in degrees/hour
        '''
        # arbitrary number of samples
        # the time this covers changes based on a few things
        numtemps = 60
        self.heat_rate_temps.append((runtime,temp))
         
        # drop old temps off the list
        if len(self.heat_rate_temps) > numtemps:
            self.heat_rate_temps = self.heat_rate_temps[-1*numtemps:]
        time2 = self.heat_rate_temps[-1][0]
        time1 = self.heat_rate_temps[0][0]
        temp2 = self.heat_rate_temps[-1][1]
        temp1 = self.heat_rate_temps[0][1]
        if time2 > time1:
            self.heat_rate = ((temp2 - temp1) / (time2 - time1))*3600

    def run_profile(self, profile, startat=0, allow_seek=True):
        log.debug('run_profile run on thread' + threading.current_thread().name)
        runtime = startat * 60
        if allow_seek:
            if self.state == 'IDLE':
                if config.seek_start:
                    temp = self.board.temp_sensor.temperature()  # Defined in a subclass
                    runtime += self.get_start_from_temperature(profile, temp)

        self.reset()
        self.startat = startat * 60
        self.runtime = runtime
        # derive start_time from the (possibly seek-adjusted) runtime so
        # update_runtime() preserves it instead of resetting to zero
        self.start_time = self.get_start_time()
        self.profile = profile
        self.totaltime = profile.get_duration()
        self.run_sequence += 1
        self.state = "RUNNING"
        # a new firing invalidates any cooled_safe alert armed by the
        # previous one: the kiln is about to get hot again
        self.cooled_safe_armed_for = None
        log.info("Running schedule %s starting at %d minutes" % (profile.name,startat))
        log.info("Starting")

    def abort_run(self, reason='stopped'):
        '''end the active run. reason records why it ended so alerts can
        tell a clean finish from a failure: 'completed' (schedule ran to
        its end), 'stopped' (user or api requested stop), anything else
        is treated as an abort worth alerting on.'''
        # capture run context before reset() clears it
        context = {
            'profile': self.profile.name if self.profile else None,
            'run_id': self.run_sequence,
            'runtime_minutes': round(self.runtime / 60),
            'cost': round(self.cost, 2),
            'reason': reason,
        }
        was_active = self.state in ('RUNNING', 'PAUSED')
        self.ended_run_sequence = max(self.ended_run_sequence, self.run_sequence)
        self.idle_since = time.time()
        self.reset()
        # the firing's identity ends here: clear the watcher's stamp
        # synchronously so the save below writes run_started=None and
        # later idle broadcasts/db writes cannot reuse the finished
        # firing's stamp. tolerant of test stubs without clear().
        try:
            watcher = getattr(self, 'ovenwatcher', None)
            if watcher is not None:
                if hasattr(watcher, 'clear'):
                    watcher.clear()
                else:
                    watcher.started = None
        except Exception:
            pass
        self.save_automatic_restart_state()
        self.end_of_run(reason, context, was_active)

    def end_of_run(self, reason, context, was_active):
        '''emit lifecycle alerts for a just-ended run and arm the
        cooled_safe alert if the kiln is still too hot to open.'''
        if was_active:
            if reason == END_COMPLETED:
                self._emit('run_completed', **context)
            elif reason != END_STOPPED:
                # user-requested stops are normal operation, not errors
                self._emit('run_aborted', **context)

        # arm cooled_safe for this ended run unless the kiln is already
        # below the safe temperature. cleared when fired, or when another
        # run starts.
        temp = self._current_temp()
        if temp is not None and temp > to_c(config.cooled_safe_temp):
            self.cooled_safe_armed_for = context.get('run_id')

    def _current_temp(self):
        '''current thermocouple reading in celsius (offset applied), or
        None if it cannot be read right now'''
        try:
            return (self.board.temp_sensor.temperature() +
                    delta_to_c(config.thermocouple_offset))
        except Exception:
            return None

    def get_start_time(self):
        # epoch seconds so elapsed-time math is immune to local-time
        # (daylight-saving) changes while a firing is running
        return time.time() - self.runtime

    def kiln_must_catch_up(self):
        '''shift the whole schedule forward in time by one time_step
        to wait for the kiln to catch up'''
        if config.kiln_must_catch_up == True:
            temp = self.board.temp_sensor.temperature() + \
                delta_to_c(config.thermocouple_offset)
            window = delta_to_c(config.pid_control_window)
            # kiln too cold, wait for it to heat up
            if self.target - temp > window:
                log.info("kiln must catch up, too cold, shifting schedule")
                self.start_time = self.get_start_time()
                self.catching_up = True;
                return
            # kiln too hot, wait for it to cool down
            if temp - self.target > window:
                log.info("kiln must catch up, too hot, shifting schedule")
                self.start_time = self.get_start_time()
                self.catching_up = True;
                return
            self.catching_up = False;

    def update_runtime(self):

        runtime_delta = time.time() - self.start_time
        if runtime_delta < 0:
            runtime_delta = 0

        self.runtime = runtime_delta

    def update_target_temp(self):
        self.target = self.profile.get_target_temperature(self.runtime)

    def reset_if_emergency(self):
        '''reset if the temperature is way TOO HOT, or other critical errors detected.
           emits the matching alert whether or not the run is aborted:
           the ignore_* flags decide whether to keep firing, but either
           way you want to know it happened.'''
        temp = self._current_temp()
        if (temp is not None and
                temp >= to_c(config.emergency_shutoff_temp)):
            log.info("emergency!!! temperature too high")
            self._emit('emergency_shutoff',
                       temperature=to_display(temp),
                       limit=config.emergency_shutoff_temp,
                       profile=self.profile.name if self.profile else None)
            if config.ignore_temp_too_high == False:
                self.abort_run(reason='temperature too high')

        if self.board.temp_sensor.status.over_error_limit():
            log.info("emergency!!! too many errors in a short period")
            try:
                error_percent = round(self.board.temp_sensor.status.error_percent())
            except Exception:
                error_percent = None
            self._emit('tc_failure', error_percent=error_percent)
            if config.ignore_tc_too_many_errors == False:
                self.abort_run(reason='too many thermocouple errors')

        self.check_heat_rate_emergency()

    def target_is_rising(self):
        '''True if the profile currently demands the kiln heat up, i.e.
        the target temperature is rising. the heat-rate emergency only
        applies during heating segments so that holds and cooling
        phases don't trip it.'''
        if self.profile is None:
            return False
        return (self.profile.get_target_temperature(self.runtime + 1) >
                self.profile.get_target_temperature(self.runtime))

    def check_heat_rate_emergency(self):
        '''abort the run if the kiln cannot heat at
        config.emergency_heat_rate for config.emergency_heat_rate_window
        minutes while the profile demands heating. this can mean a
        failed heating element or a relay stuck open.'''
        if not config.emergency_heat_rate or not config.emergency_heat_rate_window:
            return

        # only heating segments demand the kiln heat up; drop the window
        # so a fresh heating segment doesn't inherit stale samples
        if not self.target_is_rising():
            self.emergency_heat_rate_temps = []
            return

        window = config.emergency_heat_rate_window * 60  # seconds

        temp = self.board.temp_sensor.temperature() + \
            delta_to_c(config.thermocouple_offset)
        self.emergency_heat_rate_temps.append((self.runtime, temp))

        # keep only the samples inside the rolling window
        self.emergency_heat_rate_temps = [
            (t, x) for (t, x) in self.emergency_heat_rate_temps
            if t >= self.runtime - window]

        if len(self.emergency_heat_rate_temps) < 2:
            return

        time1 = self.emergency_heat_rate_temps[0][0]
        temp1 = self.emergency_heat_rate_temps[0][1]
        time2 = self.emergency_heat_rate_temps[-1][0]
        temp2 = self.emergency_heat_rate_temps[-1][1]

        # wait for a full window of samples before trusting the rate
        if time2 - time1 < window:
            return

        rate = ((temp2 - temp1) / (time2 - time1)) * 3600  # celsius/hour
        if rate < delta_to_c(config.emergency_heat_rate):
            log.info("emergency!!! heat rate too low: %0.1f deg/hour" % (delta_to_display(rate)))
            self._emit('heat_rate_too_low',
                       rate_per_hour=round(delta_to_display(rate), 1),
                       minimum=config.emergency_heat_rate,
                       profile=self.profile.name if self.profile else None)
            if config.ignore_heat_rate_too_low == False:
                self.abort_run(reason='heat rate too low')

    def reset_if_schedule_ended(self):
        if self.runtime > self.totaltime:
            log.info("schedule ended, shutting down")
            log.info("total cost = %s%.2f" % (config.currency_type,self.cost))
            self.abort_run(reason=END_COMPLETED)

    def check_safety_detectors(self):
        '''always-on detectors that run in every state: implausible
        temperature jumps and a relay stuck closed while the elements
        are commanded off. these matter most when the kiln is idle,
        which is exactly when nothing else is watching.'''
        temp = self._current_temp()
        if temp is None:
            return

        # temp_implausible: one reading that leaps from the previous one
        # means sensor or wiring trouble (kilns cannot physically change
        # this fast)
        if self.last_plausible_temp is not None:
            jump = abs(temp - self.last_plausible_temp)
            if jump > delta_to_c(config.temp_implausible_jump):
                self._emit('temp_implausible',
                           previous=to_display(self.last_plausible_temp),
                           current=to_display(temp),
                           state=self.state)
                # re-baseline so sustained garbage alerts once per
                # cooldown instead of every duty cycle
                self.last_plausible_temp = temp
                self.relay_off_temps = []
                return
        self.last_plausible_temp = temp

        # relay_stuck_on: elements commanded fully off but temperature
        # keeps climbing over the window. some rise is expected right
        # after shutoff while the elements dump their stored heat, hence
        # the generous threshold.
        if self.state == 'TUNING' or self.heat:
            # tuning drives the output directly without updating heat,
            # and any commanded heat obviously explains a rising kiln
            self.relay_off_temps = []
            return

        now = time.time()
        window = config.relay_stuck_on_window * 60
        self.relay_off_temps.append((now, temp))
        self.relay_off_temps = [(t, x) for (t, x) in self.relay_off_temps
                                if t >= now - window]
        first_time = self.relay_off_temps[0][0]
        first_temp = self.relay_off_temps[0][1]
        if now - first_time >= window * 0.9 and \
                temp - first_temp > delta_to_c(config.relay_stuck_on_rise):
            self._emit('relay_stuck_on',
                       rise=round(delta_to_display(temp - first_temp), 1),
                       minutes=config.relay_stuck_on_window,
                       temperature=to_display(temp))
            # clear so it can fire again after another full window
            self.relay_off_temps = []

    def check_catch_up_stalled(self):
        '''alert when the kiln has continuously failed to keep up with
        its schedule for catch_up_stalled_minutes. fires once per stall.'''
        if not self.catching_up:
            self.catch_up_since = None
            self.catch_up_alerted = False
            return
        if self.catch_up_since is None:
            self.catch_up_since = time.time()
            return
        if not self.catch_up_alerted and \
                time.time() - self.catch_up_since >= config.catch_up_stalled_minutes * 60:
            self.catch_up_alerted = True
            self._emit('catch_up_stalled',
                       minutes=config.catch_up_stalled_minutes,
                       profile=self.profile.name if self.profile else None)

    def check_cooled_safe(self):
        '''fire and disarm the armed cooled_safe alert once the kiln has
        cooled below cooled_safe_temp'''
        if self.cooled_safe_armed_for is None:
            return
        temp = self._current_temp()
        if temp is None:
            return
        if temp <= to_c(config.cooled_safe_temp):
            run_id = self.cooled_safe_armed_for
            self.cooled_safe_armed_for = None
            self._emit('cooled_safe',
                       run_id=run_id,
                       temperature=to_display(temp),
                       limit=config.cooled_safe_temp)

    def check_unresumed_outage(self):
        '''one-shot check at startup: if the automatic restart state file
        says a firing was active but the file is older than the restart
        window, power failed mid-firing and came back too late to resume.'''
        if not config.automatic_restarts == True:
            return
        if not os.path.isfile(config.automatic_restart_state_file):
            return
        if not self.state_file_is_old():
            # file is fresh; should_i_automatic_restart will handle it
            return
        try:
            with open(config.automatic_restart_state_file) as infile:
                d = json.load(infile)
        except (IOError, ValueError):
            return
        if d.get('state') in ('RUNNING', 'PAUSED'):
            self._emit('restart_not_resumed',
                       profile=d.get('profile'),
                       runtime_minutes=round(float(d.get('runtime', 0)) / 60))

    def update_cost(self):
        if self.heat:
            cost = (config.kwh_rate * config.kw_elements) * ((self.heat)/3600)
        else:
            cost = 0
        self.cost = self.cost + cost

    def get_state(self):
        temp = 0
        try:
            temp = self.board.temp_sensor.temperature() + delta_to_c(config.thermocouple_offset)
        except AttributeError:
            # this happens at start-up with a simulated oven
            temp = 0
            pass

        self.set_heat_rate(self.runtime,temp)

        temp_errors = 0
        try:
            temp_errors = self.board.temp_sensor.status.duty_cycle_errors()
        except AttributeError:
            # start-up with a simulated oven
            pass

        state = {
            'cost': self.cost,
            'runtime': self.runtime,
            'temperature': to_display(temp),
            'target': to_display(self.target),
            'state': self.state,
            'heat': self.heat,
            'time_step': self.time_step,
            'heat_rate': delta_to_display(self.heat_rate),
            'totaltime': self.totaltime,
            'kwh_rate': config.kwh_rate,
            'currency_type': config.currency_type,
            'profile': self.profile.name if self.profile else None,
            'run_id': self.run_sequence,
            'pidstats': self.get_display_pidstats(),
            'catching_up': self.catching_up,
            'temp_errors': temp_errors,
        }
        return state

    def get_display_pidstats(self):
        '''pid stats are kept in celsius internally; report them in the
        display scale'''
        return display_pidstats(self.pid.pidstats)

    def save_state(self):
        # atomic write (tmp + rename) with fsync: a power cut mid-write
        # must leave either the previous state or the new one, never a
        # truncated file that can never resume.
        # run_started (owned by the watcher) and ended_run_sequence are
        # saved too so an automatic restart resumes the SAME firing
        # identity instead of starting a new one in the db and ui.
        tmp = config.automatic_restart_state_file + ".tmp"
        state = self.get_state()
        watcher = getattr(self, 'ovenwatcher', None)
        try:
            if hasattr(watcher, 'active_run_started'):
                started = watcher.active_run_started()
            elif self.state in ('RUNNING', 'PAUSED'):
                started = getattr(watcher, 'started', None)
            else:
                started = None
            state['run_started'] = started.timestamp() if started else None
        except Exception:
            state['run_started'] = None
        state['ended_run_sequence'] = self.ended_run_sequence
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, config.automatic_restart_state_file)

    def state_file_is_old(self):
        '''returns True is state files is older than 15 mins default
                   False if younger
                   True if state file cannot be opened or does not exist
        '''
        if os.path.isfile(config.automatic_restart_state_file):
            state_age = os.path.getmtime(config.automatic_restart_state_file)
            now = time.time()
            minutes = (now - state_age)/60
            if(minutes <= config.automatic_restart_window):
                return False
        return True

    def save_automatic_restart_state(self):
        # only save state if the feature is enabled
        if not config.automatic_restarts == True:
            return False
        self.save_state()

    def should_i_automatic_restart(self):
        # only automatic restart if the feature is enabled
        if not config.automatic_restarts == True:
            return False
        if self.state_file_is_old():
            duplog.info("automatic restart not possible. state file does not exist or is too old.")
            return False

        try:
            with open(config.automatic_restart_state_file) as infile:
                d = json.load(infile)
        except (IOError, ValueError) as e:
            # torn write from an unclean shutdown (or a hand edit):
            # never raise out of the check -- the run() error handler
            # would overwrite the file and destroy the resume. loudly
            # decline instead so the next tick can retry.
            log.error("automatic restart not possible. state file unreadable: %s" % (e))
            return False
        if d.get("state") not in ("RUNNING", "PAUSED"):
            duplog.info("automatic restart not possible. state = %s" % (d.get("state")))
            return False
        return True

    def automatic_restart(self):
        with open(config.automatic_restart_state_file) as infile: d = json.load(infile)
        startat = d["runtime"]/60
        filename = "%s.json" % (d["profile"])
        profile_path = os.path.abspath(os.path.join(os.path.dirname( __file__ ), '..', 'storage','profiles',filename))

        log.info("automatically restarting profile = %s at minute = %d" % (profile_path,startat))
        with open(profile_path) as infile:
            profile_json = json.dumps(json.load(infile))
        profile = Profile(profile_json)
        resume_state = d.get("state")
        self.run_profile(profile, startat=startat, allow_seek=False)  # We don't want a seek on an auto restart.
        # a restart continues the SAME firing, it does not start a new
        # one: restore the saved run identity so the ui, the scheduler
        # chain anchors (run:N) and the firing db (keyed by run_started)
        # all treat pre- and post-reboot samples as one firing.
        # old state files predate these keys and fall back to the fresh
        # identity run_profile() just created.
        try:
            saved_run_id = int(d.get("run_id", 0) or 0)
        except (TypeError, ValueError):
            saved_run_id = 0
        if saved_run_id > 0:
            self.run_sequence = saved_run_id
            try:
                saved_ended = int(d.get("ended_run_sequence", 0) or 0)
            except (TypeError, ValueError):
                saved_ended = 0
            if 0 <= saved_ended < saved_run_id:
                self.ended_run_sequence = max(self.ended_run_sequence,
                                              saved_ended)
            else:
                self.ended_run_sequence = max(self.ended_run_sequence,
                                              saved_run_id - 1)
        saved_run_started = d.get("run_started")
        if resume_state == "PAUSED":
            # the outage struck while paused: stay paused (and do not
            # silently unpause someone's kiln), runtime stays frozen.
            self.state = "PAUSED"
        self.cost = d["cost"]
        time.sleep(1)
        # the control thread starts before the watcher is attached at
        # boot; a missing watcher must not fail the restart (the
        # firing itself already resumed above).
        watcher = getattr(self, 'ovenwatcher', None)
        if watcher is not None:
            try:
                valid_started = (float(saved_run_started)
                                 if saved_run_started is not None else None)
            except (TypeError, ValueError):
                valid_started = None
            try:
                watcher.record(profile, started=valid_started)
            except TypeError:
                # third-party/test stub with the old record(profile)
                # signature: fall back to a fresh timestamp
                watcher.record(profile)
        else:
            log.error("restarted without ovenwatcher; new clients will miss this run's backlog")
        self._emit('restart_resumed',
                   profile=d["profile"],
                   runtime_minutes=round(startat),
                   cost=round(self.cost, 2))

    def set_ovenwatcher(self,watcher):
        log.info("ovenwatcher set in oven class")
        self.ovenwatcher = watcher

    def set_alert_manager(self, manager):
        '''attach the process-wide AlertManager so detection code can
        emit alerts. may stay None (e.g. kiln-tuner.py), in which case
        _emit does nothing.'''
        self.alert_manager = manager

    def _emit(self, alert_id, **context):
        '''emit an alert through the manager if one is attached. never
        raises: alerting must not be able to take down heater control.'''
        if self.alert_manager is None:
            return False
        try:
            return self.alert_manager.emit(alert_id, context=context)
        except Exception as e:
            log.error("could not emit alert %s: %s" % (alert_id, e))
            return False

    def run(self):
        while True:
            # never let an unhandled error kill this thread: that would
            # silently stop heater control while the ui keeps looking
            # normal. log the error, get back to a safe idle state (relay
            # off), and keep going.
            try:
                self._run_once()
            except StopIteration:
                # loop-termination sentinel, not an error
                raise
            except Exception as e:
                log.error("oven control loop error: %s" % (e))
                try:
                    if self.state in ("RUNNING", "PAUSED"):
                        self.abort_run(reason='control loop error')
                    else:
                        # not in a firing (e.g. a failed automatic
                        # restart while IDLE): get safe WITHOUT saving,
                        # so the restart file survives and the next
                        # tick retries instead of giving up forever.
                        # reset() also cuts the relay on real ovens.
                        self.reset()
                except Exception as abort_error:
                    log.error("could not reset oven after control loop "
                              "error: %s" % (abort_error))
                time.sleep(1)

    def _run_once(self):
        log.debug('Oven running on ' + threading.current_thread().name)
        if self.state == "IDLE":
            if not self.restart_outage_checked:
                self.restart_outage_checked = True
                self.check_unresumed_outage()
            if self.should_i_automatic_restart() == True:
                self.automatic_restart()
            self.check_safety_detectors()
            self.check_cooled_safe()
            time.sleep(1)
            return
        if self.state in ("PAUSED", "RUNNING") and self.profile is None:
            # inconsistent state, e.g. pause/resume requested while idle.
            # return to idle instead of crashing on the missing profile
            log.error("%s state without a profile, returning to IDLE" % (self.state))
            self.reset()
            time.sleep(1)
            return
        if self.state == "PAUSED":
            self.start_time = self.get_start_time()
            self.update_runtime()
            self.update_target_temp()
            # paused firings save too: an outage while paused must
            # resume paused (see automatic_restart), not rewind to
            # the last RUNNING sample and silently unpause.
            self.save_automatic_restart_state()
            self.heat_then_cool()
            self.reset_if_emergency()
            self.reset_if_schedule_ended()
            self.check_safety_detectors()
            return
        if self.state == "RUNNING":
            self.update_cost()
            self.save_automatic_restart_state()
            self.kiln_must_catch_up()
            self.update_runtime()
            self.update_target_temp()
            self.heat_then_cool()
            self.reset_if_emergency()
            self.reset_if_schedule_ended()
            self.check_safety_detectors()
            self.check_catch_up_stalled()
            return

        # unrecognized state (e.g. "TUNING" while the autotuner is
        # driving the oven directly): do nothing, just wait quietly
        time.sleep(self.time_step)

class SimulatedOven(Oven):

    def __init__(self):
        self.board = SimulatedBoard()
        self.t_env = to_c(config.sim_t_env)
        self.c_heat = config.sim_c_heat
        self.c_oven = config.sim_c_oven
        self.p_heat = config.sim_p_heat
        self.R_o_nocool = config.sim_R_o_nocool
        self.R_ho_noair = config.sim_R_ho_noair
        self.R_ho = self.R_ho_noair
        self.speedup_factor = config.sim_speedup_factor

        # set temps to the temp of the surrounding environment
        self.t = self.t_env  # deg C temp of oven (internal)
        self.t_h = self.t_env # deg C temp of heating element

        super().__init__()

        self.start_time = self.get_start_time();

        # start thread
        self.start()
        log.info("SimulatedOven started")

    # runtime is in sped up time, start_time is epoch seconds (real time)
    def get_start_time(self):
        return time.time() - self.runtime / self.speedup_factor

    def update_runtime(self):
        runtime_delta = (time.time() - self.start_time) * self.speedup_factor
        if runtime_delta < 0:
            runtime_delta = 0

        self.runtime = runtime_delta

    def update_target_temp(self):
        self.target = self.profile.get_target_temperature(self.runtime)

    def heating_energy(self,pid):
        # using pid here simulates the element being on for
        # only part of the time_step
        self.Q_h = self.p_heat * self.time_step * pid

    def temp_changes(self):
        #temperature change of heat element by heating
        self.t_h += self.Q_h / self.c_heat

        #energy flux heat_el -> oven
        self.p_ho = (self.t_h - self.t) / self.R_ho

        #temperature change of oven and heating element
        self.t += self.p_ho * self.time_step / self.c_oven
        self.t_h -= self.p_ho * self.time_step / self.c_heat

        #temperature change of oven by cooling to environment
        self.p_env = (self.t - self.t_env) / self.R_o_nocool
        self.t -= self.p_env * self.time_step / self.c_oven
        self.temperature = self.t
        self.board.temp_sensor.simulated_temperature = self.t

    def heat_then_cool(self):
        now_simulator = datetime.datetime.fromtimestamp(self.start_time + self.runtime)
        pid = self.pid.compute(self.target,
                               self.board.temp_sensor.temperature() +
                               delta_to_c(config.thermocouple_offset), now_simulator)

        heat_on = float(self.time_step * pid)
        heat_off = float(self.time_step * (1 - pid))

        self.heating_energy(pid)
        self.temp_changes()

        # self.heat is for the front end to display if the heat is on
        self.heat = 0.0
        if heat_on > 0:
            self.heat = heat_on

        log.info("simulation: -> %dW heater: %.0f -> %dW oven: %.0f -> %dW env" % (int(self.p_heat * pid),
            to_display(self.t_h),
            int(self.p_ho),
            to_display(self.t),
            int(self.p_env)))

        time_left = self.totaltime - self.runtime

        try:
            ps = self.get_display_pidstats()
            log.info("temp=%.2f, target=%.2f, error=%.2f, pid=%.2f, p=%.2f, i=%.2f, d=%.2f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d" %
                (ps['ispoint'],
                ps['setpoint'],
                ps['err'],
                ps['pid'],
                ps['p'],
                ps['i'],
                ps['d'],
                heat_on,
                heat_off,
                self.runtime,
                self.totaltime,
                time_left))
        except KeyError:
            pass

        # we don't actually spend time heating & cooling during
        # a simulation, so sleep.
        time.sleep(self.time_step / self.speedup_factor)


class RealOven(Oven):

    def __init__(self):
        self.board = RealBoard()
        self.output = Output()
        self.reset()

        # call parent init
        Oven.__init__(self)

        # start thread
        self.start()

    def reset(self):
        super().reset()
        self.output.cool(0)

    def heat_then_cool(self):
        pid = self.pid.compute(self.target,
                               self.board.temp_sensor.temperature() +
                               delta_to_c(config.thermocouple_offset), datetime.datetime.now())

        heat_on = float(self.time_step * pid)
        heat_off = float(self.time_step * (1 - pid))

        # self.heat is element-on seconds within this duty cycle, for
        # the front end display (heat / time_step) and update_cost().
        # it must stay in the same units as SimulatedOven (heat_on).
        self.heat = 0.0
        if heat_on > 0:
            self.heat = heat_on

        if heat_on:
            self.output.heat(heat_on)
        if heat_off:
            self.output.cool(heat_off)
        time_left = self.totaltime - self.runtime
        try:
            ps = self.get_display_pidstats()
            log.info("temp=%.2f, target=%.2f, error=%.2f, pid=%.2f, p=%.2f, i=%.2f, d=%.2f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d" %
                (ps['ispoint'],
                ps['setpoint'],
                ps['err'],
                ps['pid'],
                ps['p'],
                ps['i'],
                ps['d'],
                heat_on,
                heat_off,
                self.runtime,
                self.totaltime,
                time_left))
        except KeyError:
            pass

class Profile():
    def __init__(self, json_data):
        obj = json.loads(json_data)
        self.name = obj["name"]
        self.data = sorted(obj["data"])

    def get_duration(self):
        return max([t for (t, x) in self.data])

    #  x = (y-y1)(x2-x1)/(y2-y1) + x1
    @staticmethod
    def find_x_given_y_on_line_from_two_points(y, point1, point2):
        if point1[0] > point2[0]: return 0  # time2 before time1 makes no sense in kiln segment
        if point1[1] >= point2[1]: return 0 # Zero will crach. Negative temeporature slope, we don't want to seek a time.
        dy = point2[1] - point1[1]
        if dy == 0: return 0
        x = (y - point1[1]) * (point2[0] -point1[0] ) / dy + point1[0]
        return x

    def find_next_time_from_temperature(self, temperature):
        time = 0 # The seek function will not do anything if this returns zero, no useful intersection was found
        for index, point2 in enumerate(self.data):
            if point2[1] >= temperature:
                if index > 0: #  Zero here would be before the first segment
                    if self.data[index - 1][1] <= temperature: # We have an intersection
                        time = self.find_x_given_y_on_line_from_two_points(temperature, self.data[index - 1], point2)
                        if time == 0:
                            if self.data[index - 1][1] == point2[1]: # It's a flat segment that matches the temperature
                                time = self.data[index - 1][0]
                                break

        return time

    def get_surrounding_points(self, time):
        if time > self.get_duration():
            return (None, None)

        prev_point = None
        next_point = None

        for i in range(len(self.data)):
            if time < self.data[i][0]:
                if i == 0:
                    # before the first point: hold the starting
                    # temperature. data[i-1] here would be data[-1],
                    # wrongly wrapping around to the profile's LAST point
                    prev_point = self.data[0]
                    next_point = self.data[0]
                else:
                    prev_point = self.data[i-1]
                    next_point = self.data[i]
                break

        return (prev_point, next_point)

    def get_target_temperature(self, time):
        if time > self.get_duration():
            return 0

        if time == self.get_duration():
            # exactly at the end there is no next point to interpolate
            # from; hold the final temperature instead of crashing
            return self.data[-1][1]

        (prev_point, next_point) = self.get_surrounding_points(time)

        dt = float(next_point[0] - prev_point[0])
        if dt == 0:
            return prev_point[1]
        incl = float(next_point[1] - prev_point[1]) / dt
        temp = prev_point[1] + (time - prev_point[0]) * incl
        return temp


class PID():

    def __init__(self, ki=1, kp=1, kd=1):
        self.ki = ki
        self.kp = kp
        self.kd = kd
        self.lastNow = datetime.datetime.now()
        self.iterm = 0
        self.lastErr = 0
        self.pidstats = {}

    # FIX - this was using a really small window where the PID control
    # takes effect from -1 to 1. I changed this to various numbers and
    # settled on -50 to 50 and then divide by 50 at the end. This results
    # in a larger PID control window and much more accurate control...
    # instead of what used to be binary on/off control.
    def compute(self, setpoint, ispoint, now):
        # epoch deltas keep the PID insensitive to local-time
        # (daylight-saving) changes between calls. keep sub-second
        # precision: truncating to whole seconds made consecutive stamps
        # land unevenly once the control loop's real period drifted past
        # time_step, so pairs were recorded as e.g. dt=3 when only ~2s
        # elapsed. clients derive the heat-rate graph from these stamps,
        # which showed up as a recurring dip to ~2/3 of the true rate,
        # and it quantized errDelta for the kd term.
        now_epoch = now.timestamp()
        timeDelta = now_epoch - self.lastNow.timestamp()

        window_size = 100

        error = float(setpoint - ispoint)

        # this removes the need for config.stop_integral_windup
        # it turns the controller into a binary on/off switch
        # any time it's outside the window defined by
        # config.pid_control_window
        output = 0
        out4logs = 0
        dErr = 0
        if error < (-1 * delta_to_c(config.pid_control_window)):
            log.info("kiln outside pid control window, max cooling")
            output = 0
            # it is possible to set self.iterm=0 here and also below
            # but I dont think its needed
        elif error > (1 * delta_to_c(config.pid_control_window)):
            log.info("kiln outside pid control window, max heating")
            output = 1
            if config.throttle_below_temp and config.throttle_percent:
                if setpoint <= to_c(config.throttle_below_temp):
                    output = config.throttle_percent/100
                    log.info("max heating throttled at %d percent below %d degrees to prevent overshoot" % (config.throttle_percent,config.throttle_below_temp))
        else:
            ki = self.ki if self.ki else 1
            self.iterm += (error * timeDelta * (1/ki))
            if timeDelta > 0:
                dErr = (error - self.lastErr) / timeDelta
            else:
                dErr = 0
            output = self.kp * error + self.iterm + self.kd * dErr
            output = sorted([-1 * window_size, output, window_size])[1]
            out4logs = output
            output = float(output / window_size)
            
        self.lastErr = error
        self.lastNow = now

        # no active cooling
        if output < 0:
            output = 0

        self.pidstats = {
            'time': now_epoch,
            'timeDelta': timeDelta,
            'setpoint': setpoint,
            'ispoint': ispoint,
            'err': error,
            'errDelta': dErr,
            'p': self.kp * error,
            'i': self.iterm,
            'd': self.kd * dErr,
            'kp': self.kp,
            'ki': self.ki,
            'kd': self.kd,
            'pid': out4logs,
            'out': output,
        }

        return output
