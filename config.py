import logging
import os
from digitalio import DigitalInOut
import busio

########################################################################
#
#   General options

### Logging
log_level = logging.INFO
log_format = '%(asctime)s %(levelname)s %(name)s: %(message)s'

### Server
listening_port = 8081

########################################################################
# Cost Information
#
# This is used to calculate a cost estimate before a run. It's also used
# to produce the actual cost during a run. My kiln has three
# elements that when my switches are set to high, consume 9460 watts.
kwh_rate        = 0.1319  # cost per kilowatt hour per currency_type to calculate cost to run job
kw_elements     = 9.460 # if the kiln elements are on, the wattage in kilowatts
currency_type   = "$"   # Currency Symbol to show when calculating cost to run job

########################################################################
#
# Hardware Setup (uses BCM Pin Numbering)
#
# kiln-controller.py uses SPI interface from the blinka library to read
# temperature data from the adafruit-31855 or adafruit-31856.
# Blinka supports many different boards. I've only tested raspberry pi.
#
# SPI uses 3 or 4 pins. On the raspberry pi, you MUST use predefined
# pins. In the case of the adafruit-31855, only 3 pins are used:
#
#    SPI0_SCLK = BCM pin 11 = CLK on the adafruit-31855
#    SPI0_MOSI = BCM pin 10 = not connected
#    SPI0_MISO = BCM pin 9  = D0 on the adafruit-31855
#   
# plus a GPIO output to connect to CS. You can use any GPIO pin you want.
# I chose gpio pin 5:
#
#    GPIO5    = BCM pin 5   = CS on the adafruit-31855
#
# To control the kiln, one gpio pin is used as an output. Pick any 
# you like. I chose gpio pin 23. This output is used to control a
# zero-cross solid-state-relay.
try:
    import board
    spi_sclk  = board.D11 #spi clock
    spi_mosi  = board.D10 #spi Microcomputer Out Serial In (not connected) 
    spi_miso  = board.D9  #spi Microcomputer In Serial Out
    spi_cs    = board.D5  #spi Chip Select
    gpio_heat = board.D23 #output that controls relay
except NotImplementedError:
    print("not running on blinka recognized board, probably a simulation")

### Thermocouple Adapter selection:
#   max31855 - bitbang SPI interface
#   max31856 - bitbang SPI interface. must specify thermocouple_type.
max31855 = 1
max31856 = 0
# uncomment this if using MAX-31856
#thermocouple_type = ThermocoupleType.S

# here are the possible max-31856 thermocouple types
#   ThermocoupleType.B
#   ThermocoupleType.E
#   ThermocoupleType.J
#   ThermocoupleType.K
#   ThermocoupleType.N
#   ThermocoupleType.R
#   ThermocoupleType.S
#   ThermocoupleType.T

########################################################################
#
# duty cycle of the entire system in seconds
# 
# Every N seconds a decision is made about switching the relay[s] 
# on & off and for how long. The thermocouple is read 
# temperature_average_samples times during and the average value is used.
sensor_time_wait = 2


########################################################################
#
#   PID parameters
#
# These parameters control kiln temperature change. These settings work
# well with the simulated oven. You must tune them to work well with 
# your specific kiln. Note that the integral pid_ki is
# inverted so that a smaller number means more integral action.
pid_kp = 25   # Proportional 25,200,200
pid_ki = 10   # Integral
pid_kd = 200  # Derivative

########################################################################
#
# Initial heating and Integral Windup
#
# this setting is deprecated and is no longer used. this happens by
# default and is the expected behavior.
stop_integral_windup = True

########################################################################
#
#   Simulation parameters
simulate = True
sim_t_env      = 60.0   # deg C
sim_c_heat     = 500.0  # J/K  heat capacity of heat element
sim_c_oven     = 5000.0 # J/K  heat capacity of oven
sim_p_heat     = 5450.0 # W    heating power of oven
sim_R_o_nocool = 0.5   # K/W  thermal resistance oven -> environment
sim_R_o_cool   = 0.05   # K/W  " with cooling
sim_R_ho_noair = 0.1    # K/W  thermal resistance heat element -> oven
sim_R_ho_air   = 0.05   # K/W  " with internal air circulation
sim_speedup_factor = 1000


########################################################################
#
#   Time and Temperature parameters
#
# If you change the temp_scale, all settings in this file are assumed to
# be in that scale.
temp_scale          = "f" # c = Celsius | f = Fahrenheit - Unit to display
time_scale_slope    = "h" # s = Seconds | m = Minutes | h = Hours - Slope displayed in temp_scale per time_scale_slope
time_scale_profile  = "h" # s = Seconds | m = Minutes | h = Hours - Enter and view target time in time_scale_profile

# emergency shutoff the profile if this temp is reached or exceeded.
# This just shuts off the profile. If your SSR is working, your kiln will
# naturally cool off. If your SSR has failed/shorted/closed circuit, this
# means your kiln receives full power until your house burns down.
# this should not replace you watching your kiln or use of a kiln-sitter
emergency_shutoff_temp = 2264 #cone 7

# If the current temperature is outside the pid control window,
# delay the schedule until it does back inside. This allows for heating
# and cooling as fast as possible and not continuing until temp is reached.
kiln_must_catch_up = True

# This setting is required. 
# This setting defines the window within which PID control occurs.
# Outside this window (N degrees below or above the current target)
# the elements are either 100% on because the kiln is too cold
# or 100% off because the kiln is too hot. No integral builds up
# outside the window. The bigger you make the window, the more
# integral you will accumulate. This should be a positive integer.
pid_control_window = 50 #degrees

# thermocouple offset
# If you put your thermocouple in ice water and it reads 36F, you can
# set set this offset to -4 to compensate.  This probably means you have a
# cheap thermocouple.  Invest in a better thermocouple.
thermocouple_offset=0

# number of samples of temperature to take over each duty cycle.
# The larger the number, the more load on the board. K type 
# thermocouples have a precision of about 1/2 degree C. 
# The median of these samples is used for the temperature.
temperature_average_samples = 40 

# Thermocouple AC frequency filtering - set to True if in a 50Hz locale, else leave at False for 60Hz locale
ac_freq_50hz = False

########################################################################
# Emergencies - or maybe not
########################################################################
# There are all kinds of emergencies that can happen including:
# - temperature is too high (emergency_shutoff_temp exceeded)
# - lost connection to thermocouple
# - unknown error with thermocouple
# - too many errors in a short period from thermocouple
# but in some cases, you might want to ignore a specific error, log it,
# and continue running your profile instead of having the process die.
#
# You should only set these to True if you experience a problem
# and WANT to ignore it to complete a firing.
ignore_temp_too_high = False
ignore_tc_lost_connection = False
ignore_tc_cold_junction_range_error = False
ignore_tc_range_error = False
ignore_tc_cold_junction_temp_high = False
ignore_tc_cold_junction_temp_low = False
ignore_tc_temp_high = False
ignore_tc_temp_low = False
ignore_tc_voltage_error = False
ignore_tc_short_errors = False 
ignore_tc_unknown_error = False

# This overrides all possible thermocouple errors and prevents the 
# process from exiting.
ignore_tc_too_many_errors = False

########################################################################
# automatic restarts - if you have a power brown-out and the raspberry pi
# reboots, this restarts your kiln where it left off in the firing profile.
# This only happens if power comes back before automatic_restart_window
# is exceeded (in minutes). The kiln-controller.py process must start
# automatically on boot-up for this to work.
# DO NOT put automatic_restart_state_file anywhere in /tmp. It could be
# cleaned up (deleted) by the OS on boot.
# The state file is written to disk every sensor_time_wait seconds (2s by default)
# and is written in the same directory as config.py.
automatic_restarts = False
automatic_restart_window = 15 # max minutes since power outage
automatic_restart_state_file = os.path.abspath(os.path.join(os.path.dirname( __file__ ),'state.json'))

########################################################################
# load kiln profiles from this directory
# created a repo where anyone can contribute profiles. The objective is
# to load profiles from this repository by default.
# See https://github.com/jbruce12000/kiln-profiles
kiln_profiles_directory = os.path.abspath(os.path.join(os.path.dirname( __file__ ),"storage", "profiles")) 
#kiln_profiles_directory = os.path.abspath(os.path.join(os.path.dirname( __file__ ),'..','kiln-profiles','pottery')) 

