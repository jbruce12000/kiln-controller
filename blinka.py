#!/usr/bin/env python
import adafruit_max31855
from digitalio import DigitalInOut

try:
    import board
except NotImplementedError:
    print("not running on Raspberry PI, assuming simulation")


spi = board.SPI()
cs = DigitalInOut(board.D5)
sensor = adafruit_max31855.MAX31855(spi, cs)
print(sensor.temperature)
