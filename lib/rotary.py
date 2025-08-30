# Rotary encoder class based on pigpio library
# version: 0.2.5

try:
    import pigpio
except ModuleNotFoundError:
    import sys
    from unittest.mock import MagicMock
    sys.modules['pigpio'] = MagicMock()


import time

# States
dt_gpio1 = 'D'  # dt_gpio is high
dt_gpio0 = 'd'  # dt_gpio is low
clk_gpio1 = 'C'  # clk_gpio is high
clk_gpio0 = 'c'  # clk_gpio is low

# State sequences
SEQUENCE_UP = dt_gpio1 + clk_gpio1 + dt_gpio0 + clk_gpio0
SEQUENCE_DOWN = clk_gpio1 + dt_gpio1 + clk_gpio0 + dt_gpio0


class Rotary:

    sequence = ''

    # Default values for the rotary encoder
    min = 0
    max = 100
    scale = 1
    debounce = 300
    _counter = 0
    last_counter = 0
    rotary_callback = None

    # Default values for the sw_gpioitch
    sw_gpio_debounce = 300
    long_press_opt = False
    sw_gpio_short_callback = None
    sw_gpio_long_callback = None
    up_callback = None
    down_callback = None
    sw_short_callback = None
    sw_long_callback = None
    sw_debounce = None

    wait_time = time.time()
    long = False

    def __init__(self, clk_gpio=None, dt_gpio=None, sw_gpio=None, debug=False):
        if not (clk_gpio and dt_gpio):
            raise BaseException("clk_gpio and dt_gpio pin must be specified!")
        
        self.DEBUG = debug
        self.pi = pigpio.pi()
        self.clk_gpio = clk_gpio
        self.dt_gpio = dt_gpio
        self.pi.set_glitch_filter(self.clk_gpio, self.debounce)
        self.pi.set_glitch_filter(self.dt_gpio, self.debounce)
        if sw_gpio is not None:
            self.sw_gpio = sw_gpio
            self.pi.set_pull_up_down(self.sw_gpio, pigpio.PUD_UP)
            self.pi.set_glitch_filter(self.sw_gpio, self.sw_gpio_debounce)
        self.setup_pigpio_callbacks()

    def setup_pigpio_callbacks(self):
        self.pi.callback(self.clk_gpio, pigpio.FALLING_EDGE, self.clk_gpio_fall)
        self.pi.callback(self.clk_gpio, pigpio.RISING_EDGE, self.clk_gpio_rise)
        self.pi.callback(self.dt_gpio, pigpio.FALLING_EDGE, self.dt_gpio_fall)
        self.pi.callback(self.dt_gpio, pigpio.RISING_EDGE, self.dt_gpio_rise)
        if self.sw_gpio is not None:
            self.pi.callback(self.sw_gpio, pigpio.FALLING_EDGE, self.sw_gpio_fall)
            self.pi.callback(self.sw_gpio, pigpio.RISING_EDGE, self.sw_gpio_rise)

    @property
    def counter(self):
        return self._counter

    @counter.setter
    def counter(self, value):
        if self._counter != value:
            self._counter = value
            if self.rotary_callback:
                self.rotary_callback(self._counter)

    def clk_gpio_fall(self, _gpio, _level, _tick):
        if self.DEBUG:
            print(self.sequence + ':{}'.format(clk_gpio1))
        if len(self.sequence) > 2:
            self.sequence = ''
        self.sequence += clk_gpio1

    def clk_gpio_rise(self, _gpio, _level, _tick):
        if self.DEBUG:
            print(self.sequence + ':{}'.format(clk_gpio0))
        self.sequence += clk_gpio0
        if self.sequence == SEQUENCE_UP:
            if self.counter < self.max:
                self.counter += self.scale
            if self.up_callback:
                self.up_callback(self._counter)
            self.sequence = ''

    def dt_gpio_fall(self, _gpio, _level, _tick):
        if self.DEBUG:
            print(self.sequence + ':{}'.format(dt_gpio1))
        if len(self.sequence) > 2:
            self.sequence = ''
        self.sequence += dt_gpio1

    def dt_gpio_rise(self, _gpio, _level, _tick):
        if self.DEBUG:
            print(self.sequence + ':{}'.format(dt_gpio0))
        self.sequence += dt_gpio0
        if self.sequence == SEQUENCE_DOWN:
            if self.counter > self.min:
                self.counter -= self.scale
            if self.down_callback:
                self.down_callback(self._counter)
            self.sequence = ''

    def sw_gpio_rise(self, _gpio, _level, _tick):
        if self.long_press_opt:
            if not self.long:
                self.short_press()

    def sw_gpio_fall(self, _gpio, _level, _tick):
        if self.long_press_opt:
            self.long = False
            press_time = time.time()
            while self.pi.read(self.sw_gpio) == 0:
                self.wait_time = time.time()
                time.sleep(0.1)
                if self.wait_time - press_time > 1.5:
                    self.long_press()
                    self.long = True
                    break
        else:
            self.short_press()

    def setup_rotary(
            self,
            rotary_callback=None,
            up_callback=None,
            down_callback=None,
            min=None,
            max=None,
            scale=None,
            debounce=None,
         ):
        if not (rotary_callback or up_callback or down_callback):
            print('At least one callback should be given')
        # rotary callback has to be set first since the self.counter property depends on it
        self.rotary_callback = rotary_callback
        self.up_callback = up_callback
        self.down_callback = down_callback
        if min is not None:
            self.min = min
            self.counter = self.min
            self.last_counter = self.min
        if max is not None:
            self.max = max
        if scale is not None:
            self.scale = scale
        if debounce is not None:
            self.debounce = debounce
            self.pi.set_glitch_filter(self.clk_gpio, self.debounce)
            self.pi.set_glitch_filter(self.dt_gpio, self.debounce)

    def setup_switch(self,
                     sw_short_callback=None,
                     sw_long_callback=None,
                     debounce=None,
                     long_press=None
                     ):
        assert sw_short_callback is not None or sw_long_callback is not None
        if sw_short_callback is not None:
            self.sw_short_callback = sw_short_callback
        if sw_long_callback is not None:
            self.sw_long_callback = sw_long_callback
        if debounce is not None:
            self.sw_debounce = debounce
            self.pi.set_glitch_filter(self.sw_gpio, self.sw_debounce)
        if long_press is not None:
            self.long_press_opt = long_press

    @staticmethod
    def watch():
        """
        A simple convenience function to have a waiting loop
        """
        while True:
            time.sleep(10)

    def short_press(self):
        self.sw_short_callback()

    def long_press(self):
        self.sw_long_callback()