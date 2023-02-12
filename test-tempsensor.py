#!/usr/bin/env python
import config
from digitalio import DigitalInOut
import time
import datetime
# import busio
# import adafruit_bitbangio as bitbangio
from lib.oven import RealBoard
import logging

logging.basicConfig(level=config.log_level, format=config.log_format)
log = logging.getLogger("test-tenpsensor")
log.info("Starting Test")

try:
    import board
except NotImplementedError:
    print("not running a recognized blinka board, exiting...")
    import sys
    sys.exit()

########################################################################
#
# To test your thermocouple...
#
# Edit config.py and set the following in that file to match your
# hardware setup: SPI_SCLK, SPI_MOSI, SPI_MISO, SPI_CS
#
# then run this script...
# 
# ./test-thermocouple.py
#
# It will output a temperature in degrees every second. Touch your
# thermocouple to heat it up and make sure the value changes. Accuracy
# of my thermocouple is .25C.
########################################################################

# try:
#     spi = busio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
# except ValueError as ex:
#     if config.max31855: #  Try software SPI
#         spi = bitbangio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
#         print('Using software pins for SPI.')
#     else:
#         raise ex
#
# cs = DigitalInOut(config.spi_cs)
# sensor = None

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
