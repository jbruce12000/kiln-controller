#!/usr/bin/env python
import config
from digitalio import DigitalInOut
import time
import datetime
import busio

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

spi = None
if(hasattr(board,'SCLK') and
    hasattr(board,'MOSI') and
    hasattr(board,'MISO')):
    if(board.SCLK == config.spi_sclk and
        board.MOSI == config.spi_mosi and
        board.MISO == config.spi_miso):
        spi = board.SPI();
        print("Hardware SPI selected for reading thermocouple")

if spi is None:
    spi = bitbangio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
    print("Software SPI selected for reading thermocouple")

cs = DigitalInOut(config.spi_cs)
sensor = None

print("\nboard: %s" % (board.board_id))
if(config.max31855):
    import adafruit_max31855
    print("thermocouple: adafruit max31855")
    sensor = adafruit_max31855.MAX31855(spi, cs)
if(config.max31856):
    import adafruit_max31856
    print("thermocouple: adafruit max31856")
    sensor = adafruit_max31856.MAX31856(spi, cs)

print("SPI configured as:\n")
print("    config.spi_sclk = %s BCM pin" % (config.spi_sclk))
print("    config.spi_mosi = %s BCM pin" % (config.spi_mosi))
print("    config.spi_miso = %s BCM pin" % (config.spi_miso))
print("    config.spi_cs   = %s BCM pin\n" % (config.spi_cs))
print("Degrees displayed in %s\n" % (config.temp_scale))


while(True):
   time.sleep(1)
   temp = sensor.temperature
   scale = "C"
   if config.temp_scale == "f":
      temp = temp * (9/5) + 32 
      scale ="F"
   print("%s %0.2f%s" %(datetime.datetime.now(),temp,scale))