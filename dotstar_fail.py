# SPDX-FileCopyrightText: 2021 Kattni Rembor for Adafruit Industries
# SPDX-License-Identifier: MIT

"""
 5This example blinks the LEDs purple at a 0.5 second interval.
 6
 7For QT Py Haxpress and a NeoPixel strip. Update pixel_pin and pixel_num to match your wiring if
 8using a different board or form of NeoPixels.
 9
This example will run on SAMD21 (M0) Express boards (such as Circuit Playground Express or QT Py
Haxpress), but not on SAMD21 non-Express boards (such as QT Py or Trinket).
"""
import config
import board
import adafruit_dotstar

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.color import PURPLE

dotstar_num = config.dotstar_num = 27
dotstar_clk = config.gpio_dotstar_clk = 19  # pin 35
dotstar_dat = config.gpio_dotstar_dat = 13  # pin 33

pixels = adafruit_dotstar.DotStar(getattr(board, 'D%s' % dotstar_clk),
                                  getattr(board, 'D%s' % dotstar_dat),
                                  dotstar_num)

blink = Blink(pixels, speed=0.5, color=PURPLE)

while True:
    blink.animate()