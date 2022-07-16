#!/usr/bin/env python

if __name__ == "__main__":
    pins = list(range(0,40))
        GPIO.setup(pins, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
