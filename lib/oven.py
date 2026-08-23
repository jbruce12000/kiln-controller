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
            if tce.ignore:
                log.error("Problem reading temp (ignored) %s" % (tce.message))
                self.status.good()
            else:
                log.error("Problem reading temp %s" % (tce.message))
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
        self.limit = 30

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
                raise Max31855_Error(rte.args[0])
            raise Max31855_Error('unknown')

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
        log.info("Running schedule %s starting at %d minutes" % (profile.name,startat))
        log.info("Starting")

    def abort_run(self):
        self.ended_run_sequence = max(self.ended_run_sequence, self.run_sequence)
        self.idle_since = time.time()
        self.reset()
        self.save_automatic_restart_state()

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
        '''reset if the temperature is way TOO HOT, or other critical errors detected'''
        if (self.board.temp_sensor.temperature() + delta_to_c(config.thermocouple_offset) >=
            to_c(config.emergency_shutoff_temp)):
            log.info("emergency!!! temperature too high")
            if config.ignore_temp_too_high == False:
                self.abort_run()
        
        if self.board.temp_sensor.status.over_error_limit():
            log.info("emergency!!! too many errors in a short period")
            if config.ignore_tc_too_many_errors == False:
                self.abort_run()

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
            if config.ignore_heat_rate_too_low == False:
                self.abort_run()

    def reset_if_schedule_ended(self):
        if self.runtime > self.totaltime:
            log.info("schedule ended, shutting down")
            log.info("total cost = %s%.2f" % (config.currency_type,self.cost))
            self.abort_run()

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
        with open(config.automatic_restart_state_file, 'w', encoding='utf-8') as f:
            json.dump(self.get_state(), f, ensure_ascii=False, indent=4)

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

        with open(config.automatic_restart_state_file) as infile:
            d = json.load(infile)
        if d["state"] != "RUNNING":
            duplog.info("automatic restart not possible. state = %s" % (d["state"]))
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
        self.run_profile(profile, startat=startat, allow_seek=False)  # We don't want a seek on an auto restart.
        self.cost = d["cost"]
        time.sleep(1)
        self.ovenwatcher.record(profile)

    def set_ovenwatcher(self,watcher):
        log.info("ovenwatcher set in oven class")
        self.ovenwatcher = watcher

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
                    self.abort_run()
                except Exception as abort_error:
                    log.error("could not reset oven after control loop "
                              "error: %s" % (abort_error))
                time.sleep(1)

    def _run_once(self):
        log.debug('Oven running on ' + threading.current_thread().name)
        if self.state == "IDLE":
            if self.should_i_automatic_restart() == True:
                self.automatic_restart()
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
            self.heat_then_cool()
            self.reset_if_emergency()
            self.reset_if_schedule_ended()
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

        # self.heat is for the front end to display if the heat is on
        self.heat = 0.0
        if heat_on > 0:
            self.heat = 1.0

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
