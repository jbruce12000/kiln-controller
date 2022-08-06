#!/usr/bin/env python

import board
import adafruit_dotstar
import config
import ast
from time import sleep
from math import ceil
from adafruit_led_animation.helper import PixelSubset
from adafruit_led_animation.animation.rainbowchase import RainbowChase
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.comet import Comet
from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.color import PURPLE


time_int = 0.5


class KilnStatus:
    def __init__(self, status_fp):
        self.state = 'STARTUP'
        self.heat = False
        self.temp = 0.0
        self.target = 0.0
        self.runtime = 0.0
        self.totaltime = 0.0
        self.delay = 0.5
        self.status_fp = status_fp
        self.speed = 0.1

    def check_status(self):
        with open(self.status_fp, 'r') as f:
            status = ast.literal_eval(f.readline().strip())
        self.state = status['state']
        self.heat = status['heat']
        self.temp = status['temperature']
        self.target = status['target']
        self.totaltime = status['totaltime']
        self.runtime = status['runtime']

# {'runtime': 0,
#  'temperature': 78.41890624999999,
#  'target': 0,
#  'state': 'IDLE',
#  'heat': 0,
#  'totaltime': 0,
#  'kwh_rate': 0.1319,
#  'currency_type': '$',
#  'profile': None,
#  'pidstats': {}}


def update_status(kiln_status):
    """Monitor button that reverses rainbow direction and changes blink speed.
    Assume button is active low.
    """

    kiln_status.check_status()


def task_strip_top(pixels, kiln_status):
    while True:
        if kiln_status.state == 'STARTUP':
            top = RainbowChase(pixels,
                               kiln_status.speed,
                               size=2,
                               spacing=3,
                               reverse=False,
                               step=8)
        elif kiln_status.state == 'IDLE':
            top = Pulse(pixels,
                        kiln_status.speed,
                        (135, 135, 135),
                        period=5)
        elif kiln_status.state == 'RUNNING':
            top = Comet(pixels,
                        kiln_status.speed,
                        (120, 200, 180),
                        tail_length=10,
                        reverse=False,
                        bounce=False,
                        ring=True)
        elif kiln_status.state == 'EMERGENCY RESET':
            top = Blink(pixels,
                        0.7,
                        (255, 0, 0))
    return(top)

def task_strip_right(pixels, kiln_status):
    r_blink = Blink(pixels, speed=0.5, color=PURPLE)
    return(r_blink)

def main():

    # setup

    status_fp = config.status_file

    kiln_status = KilnStatus(status_fp)

    dotstar_num = config.dotstar_num = 27
    dotstar_clk = config.gpio_dotstar_clk = 19  # pin 35
    dotstar_dat = config.gpio_dotstar_dat = 13  # pin 33

    pixels = adafruit_dotstar.DotStar(getattr(board, 'D%s' % dotstar_clk),
                                      getattr(board, 'D%s' % dotstar_dat),
                                      dotstar_num)

    substrip_len = ceil(dotstar_num/3.0)

    strip_left = PixelSubset(pixels,
                             0,
                             substrip_len)

    strip_right = PixelSubset(pixels,
                              dotstar_num - substrip_len,
                              dotstar_num)

    strip_top = PixelSubset(pixels,
                            substrip_len,
                            dotstar_num - substrip_len)

    l_blink = Blink(strip_left, speed=0.5, color=PURPLE)

    while True:
        kiln_status.check_status()
        animations = AnimationSequence(
        AnimationGroup(
            l_blink,
            task_strip_right(strip_right, kiln_status),
            task_strip_top(strip_top, kiln_status)
        )
        animations.animate()
        sleep(time_int)

if __name__ == "__main__":
    main()
