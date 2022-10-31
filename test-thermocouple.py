#!/usr/bin/env python
import config
import adafruit_max31855
from digitalio import DigitalInOut
import time
import datetime
import busio

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

spi = busio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
cs = DigitalInOut(config.spi_cs)
sensor = adafruit_max31855.MAX31855(spi, cs)

print("\nSPI configured as:\n")
print("    config.spi_sclk = %s BCM pin" % (config.spi_sclk));
print("    config.spi_mosi = %s BCM pin" % (config.spi_mosi));
print("    config.spi_miso = %s BCM pin" % (config.spi_miso));
print("    config.spi_cs   = %s BCM pin\n" % (config.spi_cs));

while(True):
   time.sleep(1)
   temp = sensor.temperature
   scale = "C"
   if config.temp_scale == "f":
      temp = temp * (9/5) + 32 
      scale ="F"
   print("%s %0.2f%s" %(datetime.datetime.now(),temp,scale))
