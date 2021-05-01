import logging
from lib.max31856 import MAX31856

########################################################################
#
#   General options

### Logging
log_level = logging.INFO
log_format = '%(asctime)s %(levelname)s %(name)s: %(message)s'

### Server
listening_ip = "0.0.0.0"
listening_port = 8081

### Cost Estimate
kwh_rate        = 0.1319  # Rate in currency_type to calculate cost to run job
currency_type   = "$"   # Currency Symbol to show when calculating cost to run job

########################################################################
#
#   GPIO Setup (BCM SoC Numbering Schema)
#
#   Check the RasPi docs to see where these GPIOs are
#   connected on the P1 header for your board type/rev.
#   These were tested on a Pi B Rev2 but of course you
#   can use whichever GPIO you prefer/have available.

### Outputs
gpio_heat = 23  # Switches zero-cross solid-state-relay

### Thermocouple Adapter selection:
#   max31855 - bitbang SPI interface
#   max31856 - bitbang SPI interface. must specify thermocouple_type.
max31855 = 1
max31856 = 0
# see lib/max31856.py for other thermocouple_type, only applies to max31856
thermocouple_type = MAX31856.MAX31856_S_TYPE

### Thermocouple Connection (using bitbang interfaces)
gpio_sensor_cs = 27
gpio_sensor_clock = 22
gpio_sensor_data = 17
gpio_sensor_di = 10 # only used with max31856

### duty cycle of the entire system in seconds. Every N seconds a decision
### is made about switching the relay[s] on & off and for how long.
### The thermocouple is read five times during this period and the highest
### value is used.
sensor_time_wait = 2


########################################################################
#
#   PID parameters
#
# These parameters work well with the simulated oven. You must tune them
# to work well with your specific kiln. Note that the integral pid_ki is
# inverted so that a smaller number means more integral action.
pid_kp = 25   # Proportional
pid_ki = 200  # Integral
pid_kd = 200  # Derivative


########################################################################
#
# Initial heating and Integral Windup
#
# During initial heating, if the temperature is constantly under the
# setpoint,large amounts of Integral can accumulate. This accumulation
# causes the kiln to run above the setpoint for potentially a long
# period of time. These settings allow integral accumulation only when
# the temperature is within stop_integral_windup_margin percent below
# or above the setpoint. This applies only to the integral.
stop_integral_windup = True
stop_integral_windup_margin = 10

########################################################################
#
#   Simulation parameters
simulate = True
sim_t_env      = 60.0   # deg C
sim_c_heat     = 100.0  # J/K  heat capacity of heat element
sim_c_oven     = 5000.0 # J/K  heat capacity of oven
sim_p_heat     = 5450.0 # W    heating power of oven
sim_R_o_nocool = 1.0    # K/W  thermal resistance oven -> environment
sim_R_o_cool   = 0.05   # K/W  " with cooling
sim_R_ho_noair = 0.1    # K/W  thermal resistance heat element -> oven
sim_R_ho_air   = 0.05   # K/W  " with internal air circulation


########################################################################
#
#   Time and Temperature parameters
#
# If you change the temp_scale, all settings in this file are assumed to
# be in that scale.

temp_scale          = "f" # c = Celsius | f = Fahrenheit - Unit to display
time_scale_slope    = "h" # s = Seconds | m = Minutes | h = Hours - Slope displayed in temp_scale per time_scale_slope
time_scale_profile  = "m" # s = Seconds | m = Minutes | h = Hours - Enter and view target time in time_scale_profile

# emergency shutoff the profile if this temp is reached or exceeded.
# This just shuts off the profile. If your SSR is working, your kiln will
# naturally cool off. If your SSR has failed/shorted/closed circuit, this
# means your kiln receives full power until your house burns down.
# this should not replace you watching your kiln or use of a kiln-sitter
emergency_shutoff_temp = 2264 #cone 7

# If the kiln cannot heat or cool fast enough and is off by more than
# kiln_must_catch_up_max_error  the entire schedule is shifted until
# the desired temperature is reached. If your kiln cannot attain the
# wanted temperature, the schedule will run forever.
kiln_must_catch_up = True
kiln_must_catch_up_max_error = 10 #degrees

# thermocouple offset
# If you put your thermocouple in ice water and it reads 36F, you can
# set set this offset to -4 to compensate.  This probably means you have a
# cheap thermocouple.  Invest in a better thermocouple.
thermocouple_offset=0

# some kilns/thermocouples start erroneously reporting "short" errors at higher temperatures
# due to plasma forming in the kiln.
# Set this to False to ignore these errors and assume the temperature reading was correct anyway
honour_theromocouple_short_errors = True

# number of samples of temperature to average.
# If you suffer from the high temperature kiln issue and have set honour_theromocouple_short_errors to False,
# you will likely need to increase this (eg I use 40)
temperature_average_samples = 5
