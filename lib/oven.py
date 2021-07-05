import threading
import time
import random
import datetime
import logging
import json
import config

log = logging.getLogger(__name__)

class Output(object):
    def __init__(self):
        self.active = False
        self.load_libs()

    def load_libs(self):
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(config.gpio_heat, GPIO.OUT)
            self.active = True
            self.GPIO = GPIO
        except:
            msg = "Could not initialize GPIOs, oven operation will only be simulated!"
            log.warning(msg)
            self.active = False

    def heat(self,sleepfor):
        self.GPIO.output(config.gpio_heat, self.GPIO.HIGH)
        time.sleep(sleepfor)
        self.GPIO.output(config.gpio_heat, self.GPIO.LOW)

    def cool(self,sleepfor):
        '''no active cooling, so sleep'''
        time.sleep(sleepfor)

# FIX - Board class needs to be completely removed
class Board(object):
    def __init__(self):
        self.name = None
        self.active = False
        self.temp_sensor = None
        self.gpio_active = False
        self.load_libs()
        self.create_temp_sensor()
        self.temp_sensor.start()

    def load_libs(self):
        if config.max31855:
            try:
                #from max31855 import MAX31855, MAX31855Error
                self.name='MAX31855'
                self.active = True
                log.info("import %s " % (self.name))
            except ImportError:
                msg = "max31855 config set, but import failed" 
                log.warning(msg)

        if config.max31856:
            try:
                #from max31856 import MAX31856, MAX31856Error
                self.name='MAX31856'
                self.active = True
                log.info("import %s " % (self.name))
            except ImportError:
                msg = "max31856 config set, but import failed" 
                log.warning(msg)

    def create_temp_sensor(self):
        if config.simulate == True:
            self.temp_sensor = TempSensorSimulate()
        else:
            self.temp_sensor = TempSensorReal()

class BoardSimulated(object):
    def __init__(self):
        self.temp_sensor = TempSensorSimulated()
 
class TempSensor(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.temperature = 0
        self.time_step = config.sensor_time_wait

class TempSensorSimulated(TempSensor):
    '''not much here, just need to be able to set the temperature'''
    def __init__(self):
        TempSensor.__init__(self)

class TempSensorReal(TempSensor):
    '''real temperature sensor thread that takes N measurements
       during the time_step'''
    def __init__(self):
        TempSensor.__init__(self)
        if config.max31855:
            log.info("init MAX31855")
            from max31855 import MAX31855, MAX31855Error
            self.thermocouple = MAX31855(config.gpio_sensor_cs,
                                     config.gpio_sensor_clock,
                                     config.gpio_sensor_data,
                                     config.temp_scale)

        if config.max31856:
            log.info("init MAX31856")
            from max31856 import MAX31856
            software_spi = { 'cs': config.gpio_sensor_cs,
                             'clk': config.gpio_sensor_clock,
                             'do': config.gpio_sensor_data,
                              ### MARK TILLES ADDED
                             'di': config.gpio_sensor_di,
                             #'gpio': config.gpio_heat
                             }
                            
            self.thermocouple = MAX31856(tc_type=config.thermocouple_type,
                                         software_spi = software_spi,
                                         units = config.temp_scale
                                         )

    def run(self):
        '''take 5 measurements over each time period and return the
        average'''
        while True:
            maxtries = 5 
            sleeptime = self.time_step / float(maxtries)
            temps = []
            for x in range(0,maxtries):
                try:
                    temp = self.thermocouple.get()
                    temps.append(temp)
                except Exception:
                    log.exception("problem reading temp")
                time.sleep(sleeptime)
            self.temperature = sum(temps)/len(temps)

class Oven(threading.Thread):
    '''parent oven class. this has all the common code
       for either a real or simulated oven'''
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.temperature = 0
        self.time_step = config.sensor_time_wait
        self.reset()

    def reset(self):
        self.state = "IDLE"
        self.profile = None
        self.start_time = 0
        self.runtime = 0
        self.totaltime = 0
        self.target = 0
        self.heat = 0
        self.pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)

    def run_profile(self, profile, startat=0):
        log.info("Running schedule %s" % profile.name)
        self.reset()
        self.profile = profile
        self.totaltime = profile.get_duration()
        self.state = "RUNNING"
        self.start_time = datetime.datetime.now()
        self.startat = startat * 60
        log.info("Starting")

    def abort_run(self):
        self.reset()

    def kiln_must_catch_up(self):
        '''shift the whole schedule forward in time by one time_step
        to wait for the kiln to catch up'''
        if config.kiln_must_catch_up == True:
            temp = self.board.temp_sensor.temperature + \
                config.thermocouple_offset
            # kiln too cold, wait for it to heat up
            if self.target - temp > config.kiln_must_catch_up_max_error:
                log.info("kiln must catch up, too cold, shifting schedule")
                self.start_time = self.start_time + \
                    datetime.timedelta(seconds=self.time_step)
            # kiln too hot, wait for it to cool down
            if temp - self.target > config.kiln_must_catch_up_max_error:
                log.info("kiln must catch up, too hot, shifting schedule")
                self.start_time = self.start_time + \
                    datetime.timedelta(seconds=self.time_step)

    def update_runtime(self):
        runtime_delta = datetime.datetime.now() - self.start_time
        if self.startat > 0:
            self.runtime = self.startat + runtime_delta.total_seconds()
        else:
            self.runtime = runtime_delta.total_seconds()

    def update_target_temp(self):
        self.target = self.profile.get_target_temperature(self.runtime)

    def reset_if_emergency(self):
        '''reset if the temperature is way TOO HOT'''
        if (self.board.temp_sensor.temperature + config.thermocouple_offset >=
            config.emergency_shutoff_temp):
            log.info("emergency!!! temperature too high, shutting down")
            self.reset()

    def reset_if_schedule_ended(self):
        if self.runtime > self.totaltime:
            log.info("schedule ended, shutting down")
            self.reset()

    def get_state(self):
        state = {
            'runtime': self.runtime,
            'temperature': self.board.temp_sensor.temperature + config.thermocouple_offset,
            'target': self.target,
            'state': self.state,
            'heat': self.heat,
            'totaltime': self.totaltime,
            'profile': self.profile.name if self.profile else None,
        }
        return state

    def run(self):
        while True:
            if self.state == "IDLE":
                time.sleep(1)
                continue
            if self.state == "RUNNING":
                self.kiln_must_catch_up()
                self.update_runtime()
                self.update_target_temp()
                self.heat_then_cool()
                self.reset_if_emergency()
                self.reset_if_schedule_ended()


class SimulatedOven(Oven):

    def __init__(self):
        self.reset()
        self.board = BoardSimulated()

        self.t_env = config.sim_t_env
        self.c_heat = config.sim_c_heat
        self.c_oven = config.sim_c_oven
        self.p_heat = config.sim_p_heat
        self.R_o_nocool = config.sim_R_o_nocool
        self.R_ho_noair = config.sim_R_ho_noair
        self.R_ho = self.R_ho_noair

        # set temps to the temp of the surrounding environment
        self.t = self.t_env # deg C temp of oven
        self.t_h = self.t_env #deg C temp of heating element
        
        # call parent init
        Oven.__init__(self)
        
        # start thread
        self.start()
        log.info("SimulatedOven started")

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
        self.board.temp_sensor.temperature = self.t

    def heat_then_cool(self):
        pid = self.pid.compute(self.target,
                               self.board.temp_sensor.temperature +
                               config.thermocouple_offset)
        heat_on = float(self.time_step * pid)
        heat_off = float(self.time_step * (1 - pid))

        self.heating_energy(pid)
        self.temp_changes()

        # self.heat is for the front end to display if the heat is on
        self.heat = 0.0
        if heat_on > 0:
            self.heat = heat_on

        log.info("simulation: -> %dW heater: %.0f -> %dW oven: %.0f -> %dW env"            % (int(self.p_heat * pid),
            self.t_h,
            int(self.p_ho),
            self.t,
            int(self.p_env)))

        time_left = self.totaltime - self.runtime
        log.info("temp=%.2f, target=%.2f, pid=%.3f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d" %
            (self.board.temp_sensor.temperature + config.thermocouple_offset,
             self.target,
             pid,
             heat_on,
             heat_off,
             self.runtime,
             self.totaltime,
             time_left))
        
        # we don't actually spend time heating & cooling during
        # a simulation, so sleep. 
        time.sleep(self.time_step)


class RealOven(Oven):

    def __init__(self):
        self.board = Board()
        self.output = Output()
        self.reset()

        # call parent init
        Oven.__init__(self)

        # start thread
        self.start()

    def heat_then_cool(self):
        pid = self.pid.compute(self.target,
                               self.board.temp_sensor.temperature +
                               config.thermocouple_offset)
        heat_on = float(self.time_step * pid)
        heat_off = float(self.time_step * (1 - pid))

        # self.heat is for the front end to display if the heat is on
        self.heat = 0.0
        if heat_on > 0:
            self.heat = 1.0

        self.output.heat(heat_on)
        self.output.cool(heat_off)
        time_left = self.totaltime - self.runtime
        log.info("temp=%.2f, target=%.2f, pid=%.3f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d" %
            (self.board.temp_sensor.temperature + config.thermocouple_offset,
             self.target,
             pid,
             heat_on,
             heat_off,
             self.runtime,
             self.totaltime,
             time_left))

class Profile():
    def __init__(self, json_data):
        obj = json.loads(json_data)
        self.name = obj["name"]
        self.data = sorted(obj["data"])

    def get_duration(self):
        return max([t for (t, x) in self.data])

    def get_surrounding_points(self, time):
        if time > self.get_duration():
            return (None, None)

        prev_point = None
        next_point = None

        for i in range(len(self.data)):
            if time < self.data[i][0]:
                prev_point = self.data[i-1]
                next_point = self.data[i]
                break

        return (prev_point, next_point)

    def get_target_temperature(self, time):
        if time > self.get_duration():
            return 0

        (prev_point, next_point) = self.get_surrounding_points(time)

        incl = float(next_point[1] - prev_point[1]) / float(next_point[0] - prev_point[0])
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

    # FIX - this was using a really small window where the PID control
    # takes effect from -1 to 1. I changed this to various numbers and 
    # settled on -50 to 50 and then divide by 50 at the end. This results
    # in a larger PID control window and much more accurate control...
    # instead of what used to be binary on/off control.
    def compute(self, setpoint, ispoint):
        now = datetime.datetime.now()
        timeDelta = (now - self.lastNow).total_seconds()

        window_size = 100

        error = float(setpoint - ispoint)

        if self.ki > 0:
            self.iterm += (error * timeDelta * (1/self.ki))
        
        dErr = (error - self.lastErr) / timeDelta
        output = self.kp * error + self.iterm + self.kd * dErr
        out4logs = output
        output = sorted([-1 * window_size, output, window_size])[1]
        self.lastErr = error
        self.lastNow = now

        # not actively cooling, so
        if output < 0:
            output = 0

        #if output > 1:
        #    output = 1

        output = float(output / window_size)

        if out4logs > 0:        
            log.info("pid percents pid=%0.2f p=%0.2f i=%0.2f d=%0.2f" % (out4logs,
                ((self.kp * error)/out4logs)*100, 
                (self.iterm/out4logs)*100,
                ((self.kd * dErr)/out4logs)*100)) 

        return output
