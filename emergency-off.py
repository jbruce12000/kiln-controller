#!/usr/bin/env python
import config
import digitalio
import time
import datetime

try:
    import board
except NotImplementedError:
    print("not running a recognized blinka board, exiting...")
    import sys
    sys.exit()

########################################################################
#
# shut down the mergency relais

# Edit config.py and set the following in that file to match your
# hardware setup: gpio_emergency
########################################################################

emergency = digitalio.DigitalInOut(config.gpio_emergency)
emergency.direction = digitalio.Direction.OUTPUT

print("\nboard: %s" % (board.board_id))
print("emergency configured as config.gpio_emergency = %s BCM pin\n" % (config.gpio_emergency))

print("\nsetting emergency IO low")
emergency.value = False
