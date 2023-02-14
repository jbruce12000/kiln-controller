import config
import time
import datetime
from lib.oven import RealBoard
import logging

logging.basicConfig(level=config.log_level, format=config.log_format)
log = logging.getLogger("test-tempsensor")
log.info("Starting Test")

try:
    import board
except NotImplementedError:
    print("not running a recognized blinka board, exiting...")
    import sys
    sys.exit()

########################################################################
#
# To test your thermocouple and the kiln-controller TempSensor code...
#
# This code functions a lot like test-thermocouple.py but uses the
# actual kiln-controller code instead of calling the Adafruit libraries directly.
########################################################################


print("\nboard: %s" % (board.board_id))
if config.max31855:
    print("thermocouple: adafruit max31855")
if config.max31856:
    print("thermocouple: adafruit max31856")

print("SPI configured as:\n")
print("    config.spi_sclk = %s BCM pin" % (config.spi_sclk))
print("    config.spi_mosi = %s BCM pin" % (config.spi_mosi))
print("    config.spi_miso = %s BCM pin" % (config.spi_miso))
print("    config.spi_cs   = %s BCM pin\n" % (config.spi_cs))
print("Degrees displayed in %s\n" % (config.temp_scale))

oven_board = RealBoard()

while True:
   time.sleep(1)
   temp = oven_board.temp_sensor.temperature()
   scale = "C"
   if config.temp_scale == "f":
      scale ="F"
   print("%s %0.2f%s" %(datetime.datetime.now(),temp,scale))
