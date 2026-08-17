Troubleshooting
==========

When I started this project, I'd never worked with RPi gpio.  I think I got
just about everything backwards possible.  I blew up a MAX-31855 chip... POOF,
up in smoke!

So, invest a little time to learn the hardware and the software available to
you to verify everything works as expected.

## Can't reach the web interface

The browser can't talk to the controller. Try these in order:

1. **Check the controller is running.** SSH into your Pi and run
   `ps aux | grep kiln-controller`. If it's not running, start it with
   `source venv/bin/activate; ./kiln-controller.py`.
2. **Check the port.** Make sure the URL in your browser matches the
   `listening_port` in `config.py` (default 9099).
3. **Check the network.** Make sure your browser device is on the same
   network as the Pi. Try pinging the Pi from another device.
4. **Check the firewall.** If you've configured a firewall on the Pi, make
   sure the listening port is open.
5. **Try a different browser or device.** Sometimes browser extensions or
   caching cause issues.

*Related: [#265](https://github.com/jbruce12000/kiln-controller/issues/265)*

---

## Temperature reads 0 or shows wild fluctuations

- **Check thermocouple wiring.** A loose connection causes erratic or zero
  readings. Power off the Pi, re-seat the thermocouple wires, and restart.
- **Check thermocouple type.** The config must match your thermocouple. If
  you're using a MAX31856, make sure `thermocouple_type` in `config.py`
  matches the type of thermocouple you plugged in (K, S, R, etc.).
- **Check SPI pins.** If you're using software SPI, verify the pin numbers
  in `config.py` match your wiring. Run `./gpioreadall.py` to inspect pin
  states.
- **Use the test script.** Run `./test-thermocouple.py` with the virtual
  environment activated to read the thermocouple directly outside the
  controller.

*Related: [#223](https://github.com/jbruce12000/kiln-controller/issues/223), [#227](https://github.com/jbruce12000/kiln-controller/issues/227)*

---

## Temperature reads a constant wrong value

- **Thermocouple offset.** If your thermocouple reads consistently high or
  low, set `thermocouple_offset` in `config.py` to compensate. For example,
  if it reads 36F in ice water, set `thermocouple_offset = -4`.
- **Wrong thermocouple board.** Make sure `max31855 = 1` or `max31856 = 1`
  matches the board you actually have. The MAX31855 only works with K-type
  thermocouples.

---

## Temperature doesn't update during a firing

- **Check the overview tab.** If the status badge shows "Running" but the
  chart is flat, the WebSocket may have disconnected. Refresh the page.
- **Check the server logs.** SSH into the Pi and look for errors in the
  terminal output or journal (`journalctl -u kiln-controller`).
- **WiFi dropping out.** The Raspberry Pi Zero in particular is known for
  WiFi instability at high temperatures. Consider adding a heat sink to
  the Pi or moving it away from the kiln. A small display connected
  directly to the Pi can serve as a fallback when WiFi is unreliable.

*Related: [#263](https://github.com/jbruce12000/kiln-controller/issues/263)*

---

## Kiln overshoots the target temperature

This is the most common tuning problem.

- **PID not tuned.** Run the PID Auto-Tuner on the Config tab. Manual
  tuning guide: [PID Tuning](pid_tuning.md).
- **Throttling not aggressive enough.** Lower `throttle_percent` (try 15 or
  10) and raise `throttle_below_temp` to limit power at low temperatures
  where overshoot is worst.
- **Integral windup.** If the error chart (Details tab) shows a large
  positive area under the curve, the integral term is too strong. Increase
  `pid_ki` (recall it's inverted -- a larger number means less integral).

*Related: [#96](https://github.com/jbruce12000/kiln-controller/issues/96)*

---

## Kiln can't reach the target temperature

- **Elements undersized.** Check that `kw_elements` in `config.py` matches
  your actual element wattage. If the kiln physically can't heat fast enough,
  no software fix will help.
- **Throttling too aggressive.** Raise `throttle_percent` or lower
  `throttle_below_temp` if the kiln is being held back at low power.
- **Emergency heat rate too high.** If the firing aborts with a heat rate
  error, either fix the hardware issue or increase `emergency_heat_rate` to
  a value your kiln can achieve.
- **Check the relay.** If the heat percentage on the Details tab shows 100%
  but the kiln isn't heating, the relay or SSR may be faulty. Run
  `./test-output.py` to verify the GPIO pin is switching.

---

## Kiln gets stuck cooling or can't catch up

When the kiln is too hot or too cold for the current point in the schedule,
the `kiln_must_catch_up` feature shifts the schedule forward to wait. If the
kiln can't reach the target, the schedule shifts repeatedly and the kiln
appears stuck.

- **On cooling segments**, `kiln_must_catch_up` can hold for hours if the
  kiln is above the target and can't cool fast enough. Consider disabling
  `kiln_must_catch_up` (`False` in config) for schedules with steep cooling
  segments, or increase `pid_control_window` so the PID controller can
  manage the transition.
- **Check element wattage.** If the kiln can't heat fast enough during ramp
  segments, the schedule will keep shifting and the firing will take much
  longer than expected.
- **Verify the profile.** Open the profile in the editor and check that the
  target temperatures and ramp times are realistic for your kiln.

*Related: [#161](https://github.com/jbruce12000/kiln-controller/issues/161), [#77](https://github.com/jbruce12000/kiln-controller/issues/77)*

---

## Firing aborts unexpectedly

- **Emergency shutoff.** Check if `emergency_shutoff_temp` is set too low.
  The firing stops if the kiln reaches this temperature. Increase it if
  your intended firing temperature is higher.
- **Heat rate failure.** The controller aborts if the kiln can't keep up
  with the required heating rate. Check the `emergency_heat_rate` and
  `emergency_heat_rate_window` settings. A failed heating element or stuck
  relay can also cause this.
- **Too many thermocouple errors.** If the thermocouple loses connection
  repeatedly, the controller shuts down. Check wiring. If you're getting
  spurious errors you want to ignore, set `ignore_tc_too_many_errors = True`
  in `config.py` -- but only as a last resort.
- **Temperature drops during a hold.** If the kiln cools below the target
  during a hold segment and `kiln_must_catch_up` is enabled, the schedule
  shifts and the firing continues. But if the drop is sudden (e.g., element
  failure), the emergency shutoff may trigger.

*Related: [#17](https://github.com/jbruce12000/kiln-controller/issues/17)*

---

## "An oven is not a time-machine" error when saving a profile

Times in the profile must strictly increase. You can't have two points at the
same time or a point earlier than the previous one. Edit the table and make
sure each time value is greater than the one before it.

---

## Config save fails / controller won't start after editing config

- **Syntax error.** The controller validates `config.py` before saving, but
  if you manage to save a broken config (e.g., an undefined variable), the
  controller may crash on restart.
- **Fix via SSH.** Log into the Pi, edit `config.py` with a text editor,
  and restart the controller.
- **Restore from backup.** If you downloaded a Config Dump before making
  changes, extract `config.py` from the archive and copy it back.

---

## Firing doesn't resume after a power outage

- **Check `automatic_restarts`.** It must be `True` in `config.py`.
- **Check the restart window.** Power must come back within
  `automatic_restart_window` minutes (default 15). If the Pi was off longer
  than that, the firing is considered too risky to resume.
- **Check auto-start on boot.** The controller must start automatically
  when the Pi boots. Run `./start-on-boot` to set this up. Without it,
  the process never starts and can't resume the firing.
- **Check the state file.** The restart state is saved to `state.json`. Make
  sure `automatic_restart_state_file` points to a real path outside `/tmp`.

---

## Scheduled firing doesn't start on time

- **Controller must be running.** Scheduled firings only fire if the
  `kiln-controller.py` process is running. If it crashed or wasn't started,
  schedules are ignored. They're saved to disk, so they'll fire once the
  process restarts -- but the start time has passed.
- **Check the schedule poll interval.** `schedule_poll_interval` (default 1s)
  controls how often the scheduler checks. Leave it at 1 unless you have a
  reason to change it.
- **Clock skew.** If the Pi's clock is wrong (e.g., it hasn't synced NTP
  after a long power outage), scheduled times will be off. Run `date` on
  the Pi to check.

---

## PID auto-tuner doesn't produce good values

- **Heating curve must be clean.** The tuner needs a smooth, monotonic
  heating curve. Make sure the kiln is at room temperature before starting.
  Remove any schedule that might interfere.
- **Tangent divisor.** If the heating curve has bumps or noise, increase
  the tangent divisor (try 12 or 16). If the curve is very flat, decrease
  it (try 4 or 6).
- **Target temperature.** Choose a target well above room temperature but
  below your emergency shutoff. 400F is a good default for most kilns.
- **Tuning method.** "Critically Damped" (no overshoot) is the safest
  starting point. If the kiln heats slowly, try "Quarter Decay" for more
  aggressive PID values.
- **After tuning, run a test firing.** Start a simulation (`simulate = True`)
  and watch the Details tab. If the kiln overshoots, increase `pid_ki`
  (it's inverted). If it's too sluggish, decrease `pid_ki`.

*Related: [#96](https://github.com/jbruce12000/kiln-controller/issues/96)*

---

## gpioreadall.py fails on newer Raspberry Pi OS

Newer versions of Raspberry Pi OS have removed the `raspi-gpio` utility
that `gpioreadall.py` uses. If you get an error running the script, update
to the latest version of the controller which uses `pinctrl` instead.

If you're on an older version, you can fix it manually by replacing the
`pin_state` function in `gpioreadall.py` with a version that calls
`pinctrl get <pin>` instead of `raspi-gpio`.

*Related: [#260](https://github.com/jbruce12000/kiln-controller/issues/260)*

---

## Cost estimate seems wrong

- **Check `kw_elements`.** This should be the total kilowattage of all
  elements when fully on, not per-element.
- **Check `kwh_rate`.** This is cost per kilowatt-hour in your currency.
  Divide your total electricity bill by total kWh usage for an accurate
  rate.

---

## Charts on the Details tab are empty

- **No firing data yet.** The charts only populate during a running firing.
  Start a simulation (`simulate = True` in config) to see how they look.
- **Page was reloaded mid-firing.** Tuning data is stored in browser
  memory and localStorage. If you cleared browser data or used incognito
  mode, the history is lost. The charts will fill in again as new data
  arrives.

---

## Community profiles won't load

- **Check internet from the Pi.** SSH in and run
  `curl -s https://jbruce12000.github.io/kiln-profiles/schedules.json | head`.
  If that fails, the Pi can't reach the profile index.
- **GitHub Pages down.** The community index is hosted on GitHub Pages.
  Temporary outages happen. Try again later.

---

## Multiple browser tabs / devices show different data

This shouldn't happen -- all clients receive the same live data. If it does:

- **Refresh all tabs.** One tab may have an old WebSocket connection.
- **Check for stale localStorage.** The Details tab caches tuning data in
  the browser. A hard refresh (Ctrl+Shift+R) clears the current session
  data.

---

## The interface is very slow or unresponsive

- **Old browser.** The interface uses modern JavaScript features. Make sure
  your browser is up to date.
- **Too much tuning data.** After a very long firing (many hours), the
  Details tab charts may slow down. Refresh the page to clear the in-memory
  data and start fresh.

---

## Hardware Diagnostics

### Breadboard Orientation

![Image](https://github.com/jbruce12000/kiln-controller/blob/master/public/assets/images/breadboard.png)

If you're using a breadboard with a labeled break-out board, verify:

* where pin one is using a multimeter.  it sounds stupid, but it will save you time.
* measure the voltage between all the 3V3 pins and a GND pin
* measure the voltage between all the GND pins and a GND pin
* measure the voltage between the 5V pins and a GND pin

### Test Each GPIO Pin

I thought at one point that I had fried my RPi.  I needed to verify that it
still worked as expected.  Here's what I did to verify GPIO on my pi.

```source venv/bin/activate; ./gpioreadall.py```

and you'll get output that looks something like this...

```
 +-----+-----+---------+------+---+---Pi 3---+---+------+---------+-----+-----+
 | BCM | wPi |   Name  | Mode | V | Physical | V | Mode | Name    | wPi | BCM |
 +-----+-----+---------+------+---+----++----+---+------+---------+-----+-----+
 |     |     |    3.3v |      |   |  1 || 2  |   |      | 5v      |     |     |
 |   2 |   8 |   SDA.1 |   IN | 1 |  3 || 4  |   |      | 5v      |     |     |
 |   3 |   9 |   SCL.1 |   IN | 1 |  5 || 6  |   |      | 0v      |     |     |
 |   4 |   7 | GPIO. 7 |   IN | 0 |  7 || 8  | 0 | IN   | TxD     | 15  | 14  |
 |     |     |      0v |      |   |  9 || 10 | 1 | IN   | RxD     | 16  | 15  |
 |  17 |   0 | GPIO. 0 |   IN | 0 | 11 || 12 | 1 | IN   | GPIO. 1 | 1   | 18  |
 |  27 |   2 | GPIO. 2 |   IN | 0 | 13 || 14 |   |      | 0v      |     |     |
 |  22 |   3 | GPIO. 3 |   IN | 0 | 15 || 16 | 0 | IN   | GPIO. 4 | 4   | 23  |
 |     |     |    3.3v |      |   | 17 || 18 | 0 | IN   | GPIO. 5 | 5   | 24  |
 |  10 |  12 |    MOSI |   IN | 0 | 19 || 20 |   |      | 0v      |     |     |
 |   9 |  13 |    MISO |   IN | 0 | 21 || 22 | 0 | IN   | GPIO. 6 | 6   | 25  |
 |  11 |  14 |    SCLK |   IN | 0 | 23 || 24 | 1 | IN   | CE0     | 10  | 8   |
 |     |     |      0v |      |   | 25 || 26 | 1 | IN   | CE1     | 11  | 7   |
 |   0 |  30 |   SDA.0 |   IN | 0 | 27 || 28 | 1 | IN   | SCL.0   | 31  | 1   |
 |   5 |  21 | GPIO.21 |   IN | 0 | 29 || 30 |   |      | 0v      |     |     |
 |   6 |  22 | GPIO.22 |   IN | 0 | 31 || 32 | 0 | IN   | GPIO.26 | 26  | 12  |
 |  13 |  23 | GPIO.23 |   IN | 0 | 33 || 34 |   |      | 0v      |     |     |
 |  19 |  24 | GPIO.24 |   IN | 0 | 35 || 36 | 0 | IN   | GPIO.27 | 27  | 16  |
 |  26 |  25 | GPIO.25 |   IN | 0 | 37 || 38 | 0 | IN   | GPIO.28 | 28  | 20  |
 |     |     |      0v |      |   | 39 || 40 | 0 | IN   | GPIO.29 | 29  | 21  |
 +-----+-----+---------+------+---+----++----+---+------+---------+-----+-----+
 | BCM | wPi |   Name  | Mode | V | Physical | V | Mode | Name    | wPi | BCM |
 +-----+-----+---------+------+---+---Pi 3---+---+------+---------+-----+-----+
```

make sure all the GPIO pins you want to test have a **Mode** of **IN** to make it in input
if not, set the mode for each.. 

so, for example, to set **BCM** pin 4 as an input

```gpio -g mode 4 input```

verify it got set correctly using

```gpio readall```

enable pull-down resistor for pin 4 to make sure **V** stays zero when nothing is connected to the input 

```gpio -g mode 4 down```

This will show you the output of gpio readall every 2 seconds. This way you can concentrate on
moving a wire to each gpio pin and then look up to verify **V** has changed as you expect without
having to type.

```watch ./gpioreadall.py```

* connect a 3V3 pin in series to a 1k ohm resistor
* connect the other end of the resistor to each gpio pin one at a time
* when it is connected V should be 1
* when it is disconnected V should be 0

---

## Getting more help

If none of the above fixes your issue:

1. Download a **Config Dump** from the Details tab.
2. Check the [Web Interface Guide](web-interface.md) for feature documentation.
3. Open an issue on the [GitHub issue tracker](https://github.com/jbruce12000/kiln-controller/issues)
   and attach the config dump.

---

## Common Problems Index

| Problem | Section |
|---------|---------|
| Can't reach the web interface | [Can't reach the web interface](#cant-reach-the-web-interface) |
| Temperature reads 0 or is erratic | [Temperature reads 0 or shows wild fluctuations](#temperature-reads-0-or-shows-wild-fluctuations) |
| Temperature reads a constant wrong value | [Temperature reads a constant wrong value](#temperature-reads-a-constant-wrong-value) |
| Temperature doesn't update during a firing | [Temperature doesn't update during a firing](#temperature-doesnt-update-during-a-firing) |
| Kiln overshoots the target | [Kiln overshoots the target temperature](#kiln-overshoots-the-target-temperature) |
| Kiln can't reach the target | [Kiln can't reach the target temperature](#kiln-cant-reach-the-target-temperature) |
| Kiln gets stuck cooling / can't catch up | [Kiln gets stuck cooling or can't catch up](#kiln-gets-stuck-cooling-or-cant-catch-up) |
| Firing aborts unexpectedly | [Firing aborts unexpectedly](#firing-aborts-unexpectedly) |
| Firing doesn't resume after power outage | [Firing doesn't resume after a power outage](#firing-doesnt-resume-after-a-power-outage) |
| Scheduled firing doesn't start on time | [Scheduled firing doesn't start on time](#scheduled-firing-doesnt-start-on-time) |
| PID auto-tuner doesn't produce good values | [PID auto-tuner doesn't produce good values](#pid-auto-tuner-doesnt-produce-good-values) |
| gpioreadall.py fails on newer Raspberry Pi OS | [gpioreadall.py fails on newer Raspberry Pi OS](#gpioreadallpy-fails-on-newer-raspberry-pi-os) |
| Cost estimate seems wrong | [Cost estimate seems wrong](#cost-estimate-seems-wrong) |
| Charts on the Details tab are empty | [Charts on the Details tab are empty](#charts-on-the-details-tab-are-empty) |
| Interface is slow or unresponsive | [The interface is very slow or unresponsive](#the-interface-is-very-slow-or-unresponsive) |
