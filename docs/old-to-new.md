Old to New
==========

This describes how to migrate from the old version of the code to the new.

## History

In early 2023 I rewrote most of the kiln-controller back-end code. It was a major change with all new classes. Lots of libraries were removed and the Adafruit blinka library was chosen which allows for a hundred or more supported boards in addition to raspberry pis.

## Why Swap?

As of 2023 I stopped supporting and adding features to the old code. It still works, but I no longer use it, update it, test it, or change it.

## Easiest possible migration

The easiest way to convert from the old code to the new is to use software spi, also known as bitbanging, to grab data from the thermocouple board. You will not have to make any wiring changes. You'll only need to change config.py and test it to make sure it works.

  1. make a backup of config.py. You'll need it for the next step.

  cp config.py config.py.bak

  2. find these settings in config.py.bak and change them in config.py:

  gpio_sensor_cs = 27
  gpio_sensor_clock = 22
  gpio_sensor_data = 17
  gpio_sensor_di = 10
  gpio_heat = 23

  change them in config.py to look like so:

  spi_cs = board.D27
  spi_sclk = board.D22
  spi_miso = board.D17
  spi_mosi = board.D10 #this one is not actually used, so set it or not
  gpio_heat = board.D23

  3. test the thermocouple board and thermocouple

  cd kiln-controller
  source venv/bin/activate
  ./test-thermocouple.py

  You should see that software spi is configured. You should see the pin configuration printed out. You should see the temperature reported every second.

  4. test output

  cd kiln-controller
  source venv/bin/activate
  ./test-output.py

  Every 5 seconds, verify the output is flipped from on to off or vice versa.


