import logging

########################################################################
simulate = False
kiln_must_catch_up = True
kiln_must_catch_up_max_error = 10
#
#   General options

### Logging
log_level = logging.INFO
log_format = '%(asctime)s %(levelname)s %(name)s: %(message)s'

### Server
listening_ip = "0.0.0.0"
listening_port = 8081

### Cost Estimate
kwh_rate        = 0.18  # Rate in currency_type to calculate cost to run job
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
heater_invert = 0 # switches the polarity of the heater control

### Thermocouple Adapter selection:
#   max31855 - bitbang SPI interface
#   max31855spi - kernel SPI interface
#   max6675 - bitbang SPI interface
max31855 = 1
max6675 = 0
max31855spi = 0 # if you use this one, you MUST reassign the default GPIO pins
max31856 = 0

### Thermocouple Connection (using bitbang interfaces)
gpio_sensor_cs = 27
gpio_sensor_clock = 22
gpio_sensor_data = 17

### Thermocouple SPI Connection (using adafrut drivers + kernel SPI interface)
spi_sensor_chip_id = 0

### duty cycle of the entire system in seconds. Every N seconds a decision
### is made about switching the relay[s] on & off and for how long.
### The thermocouple is read five times during this period and the highest
### value is used.
sensor_time_wait = 2


########################################################################
#
#   PID parameters

pid_kp = 25  # Proportional
pid_ki = 1088  # Integration
pid_kd = 217  # Derivative was 217


########################################################################
#
#   Simulation parameters

sim_t_env      = 25.0   # deg C
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

temp_scale          = "f" # c = Celsius | f = Fahrenheit - Unit to display 
time_scale_slope    = "h" # s = Seconds | m = Minutes | h = Hours - Slope displayed in temp_scale per time_scale_slope
time_scale_profile  = "m" # s = Seconds | m = Minutes | h = Hours - Enter and view target time in time_scale_profile

# emergency shutoff the kiln if this temp is reached.
# when solid state relays fail, they usually fail closed.  this means your
# kiln receives full power until your house burns down.
# this should not replace you watching your kiln or use of a kiln-sitter
emergency_shutoff_temp = 2250

# not used yet
# if measured value is N degrees below set point
warning_temp_low = 5

# not used yet
# if measured value is N degrees above set point
warning_temp_high = 5

# thermocouple offset
# If you put your thermocouple in ice water and it reads 36F, you can
# set set this offset to -4 to compensate.  This probably means you have a
# cheap thermocouple.  Invest in a better thermocouple.
thermocouple_offset=0
