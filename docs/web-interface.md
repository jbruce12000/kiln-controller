# Kiln Controller Web Interface

The kiln controller runs a web application that you access from any browser on
your local network -- phone, tablet, laptop, or desktop. Open it at
`http://<your-pi-ip>:<port>` (default port 9099, set in `config.py`).

The interface has four tabs: **Overview**, **Details**, **Schedules**, and
**Config**.

---

## Overview

The main screen shows your selected firing profile as a green line on a chart.
When a firing is running, a live temperature line draws over it in real time so
you can see how well the kiln is tracking the schedule.

- **Status badge** -- shows Idle, Running, or Paused.
- **Simulation badge** -- appears when the controller is in simulation mode
  (no real kiln hardware).
- **Time Left / Elapsed** -- countdown and elapsed time during a firing.

**To start a firing:** go to the Schedules tab, pick a profile, and click
**Run**.

**To schedule a firing for later:** click **Schedule** on any profile, choose
a date and time, and confirm.

---

## Details

This tab is for tuning and troubleshooting. It shows live PID data -- the
numbers that control how the kiln heats.

**Stat boxes** at the top display:

| Box | What it shows |
|-----|---------------|
| TEMP | Current kiln temperature and target temperature |
| ERROR | How far off the kiln is from the target (now, 1-min avg, 5-min avg, 15-min avg) |
| HEAT | What percentage of heater power is being used |
| CATCH UP | How much time the kiln has spent behind schedule |
| COST | Running cost of the firing so far (element wattage x hours on, at your electricity rate) |

**Charts** show temperature, error, heat output, heat rate (how fast the
temperature is climbing or falling, in degrees per hour), PID components,
and thermocouple read errors over time. Use the **Window** slider to zoom
into recent data or view the entire run.

---

## Schedules

This is where you manage your firing profiles.

### Scheduled Runs

Shows any upcoming firings with a countdown to when they start. Click
**Cancel** to remove a scheduled run.

### Saved Schedules

Lists all profiles stored on the controller. For each one you can:

- **Run** -- start the firing immediately
- **Schedule** -- pick a future date and time
- **Edit** -- open the profile in the editor
- **Delete** -- remove the profile (with confirmation)

While a profile is running, its **Run**, **Edit**, and **Delete** buttons are
replaced by a single **Stop** button. The row carries the only stop control,
so hiding edit and delete guarantees a firing cannot be left running with no
way to stop it from the interface. The buttons return when the run finishes.

### Editing a Profile

Click **New Schedule** or **Edit** on an existing profile to open the editor.

- Enter a **name** and optional **description**.
- Add, remove, or reorder points in the table. Each point has a time and a
  temperature. The slope between points is shown automatically.
- You can also **drag points directly on the chart** to adjust them.
- Click **Save** when done. The controller validates that times increase
  monotonically before saving.

### Scheduling a Firing

Click **Schedule** on any profile. A dialog lets you:

- Pick a date and time, or use the quick buttons (+15 min, +1 hr, +3 hr,
  +1 day).
- **Chain after another firing** -- if a run is in progress or scheduled, you
  can choose "After this" to start your new firing shortly after the previous
  one finishes. This is great for multi-step firings (bisque then glaze, for
  example).

Scheduled runs survive a reboot as long as the controller restarts
automatically.

### Community Profiles

Browse and install profiles shared by other users from the
[kiln-profiles](https://github.com/jbruce12000/kiln-profiles) GitHub
repository.

- Use the **search box** to filter by name, category, or tag.
- Click **Install** to download a profile to your controller.
- If you've created a useful profile, you can **Share** it to the community
  (requires a free GitHub token).

---

## Config

Lets you edit `config.py` directly in the browser. The file contains all
controller settings including PID parameters, temperature scale, safety limits,
simulation options, and more.

- Edit the text in the editor.
- Click **Save & Restart**.
- The controller validates your changes, saves the file, and restarts.
- The page reconnects automatically. If a firing was in progress, it resumes.

**Be careful** -- incorrect changes can prevent the controller from starting.
Keep a backup of a known-working config.

### Alerts

The **Alerts** panel lists every condition that can raise an alert, ordered
most critical first:

- **Critical** -- safety events: emergency shutoff, kiln not heating fast
  enough, relay stuck on, thermocouple failure, implausible temperature
  readings.
- **Warning** -- degraded runs: aborted firings, power-outage restarts,
  falling behind schedule, missed scheduled runs.
- **Info** -- normal lifecycle events worth knowing about: run started,
  run completed, cooled to safe temperature, controller restarted.

Toggle any checkbox to enable or disable that alert. Changes are saved
immediately to `storage/alerts.json` (no restart required) and survive a
reboot.

All of these conditions are detected live by the controller. When a
detected alert fires it is written to the daemon log, tagged
`ALERT [CRITICALITY]`, with details about the run (profile, temperature,
reason). Repeating conditions are rate limited to at most one alert every
5 minutes; lifecycle events (run started/completed/aborted, restarts)
always come through. Disabling an alert silences it completely -- the
detector still runs, but nothing is announced.

#### Alert delivery

The **Delivery** section at the bottom of the panel chooses where fired
alerts go beyond the daemon log. Both options take effect immediately when
toggled (no restart) and their settings are saved in the same
`storage/alerts.json` file as the alert checkboxes.

- **Send alerts over MQTT** -- publishes each alert as json on its own
  topic (default `kiln/alert`), next to the live state stream, so Home
  Assistant or Node-RED can trigger notifications or automations. Requires
  the broker settings (`mqtt_enable`, `mqtt_host`, ...) in `config.py`;
  until those exist the panel shows a hint.
- **Post alerts to a webhook** -- posts each alert as json to any url that
  accepts a POST: ntfy (`https://ntfy.sh/<your-topic>`), Discord or Slack
  incoming webhooks, Home Assistant webhooks, Pushover, or your own
  receiver. Posts run on a background thread with a timeout
  (`alert_webhook_timeout` in `config.py`) so a slow endpoint can never
  stall heater control.

Every delivery carries the same json payload:

```json
{
  "source": "kiln-controller",
  "alert_id": "relay_stuck_on",
  "label": "Relay stuck on",
  "criticality": "critical",
  "context": {"rise": 31.2, "minutes": 10, "temperature": 212},
  "time": "2026-08-23T14:43:50",
  "epoch": 1787485430
}
```

Detection thresholds live in the alerts section of `config.py`
(`cooled_safe_temp`, `relay_stuck_on_rise`, `relay_stuck_on_window`,
`temp_implausible_jump`, `catch_up_stalled_minutes`).

### PID Auto-Tuner

At the bottom of the Config tab, the **PID Auto-Tuner** calculates optimal PID
values for your kiln using the Ziegler-Nichols open-loop method.

**How it works:**

1. Enter a **target temperature**, pick a **tuning method**, and set the
   **tangent divisor** (leave the defaults unless you know you need to change
   them).
2. Click **Start Tuning**. The tuner takes control of the kiln and heats at
   full power until the target is reached, then lets it cool back down.
3. The heating curve is recorded and analyzed to compute dead time and time
   constant. PID values are calculated using Ziegler-Nichols formulas.
4. The new values are written to `config.py` and the controller restarts
   automatically.

The **Overview** tab shows the live temperature during tuning. The
**Details** tab shows temp, target, and heat percentage.

**Tuning methods:**

| Method | Description |
|--------|-------------|
| Critically Damped | No overshoot (recommended starting point) |
| Some Overshoot | ~20% overshoot, faster settling |
| Quarter Decay | ~25% overshoot, classic Ziegler-Nichols |

**Tangent Divisor** controls where on the heating curve the tangent line is
fitted. The default of 8 works well for most kilns. Increase it if the heating
curve has irregular bumps.

No schedule can run while tuning. The tuner will refuse to start if the oven is
not idle.

**Warning:** Tuning automatically writes PID values to `config.py` and restarts
the server. This will change how your kiln heats.

### Key settings

| Setting | What it does |
|---------|--------------|
| `temp_scale` | `"f"` for Fahrenheit, `"c"` for Celsius |
| `simulate` | `True` to run in simulation mode (no hardware needed) |
| `listening_port` | Port the web server runs on (default 9099) |
| `pid_kp`, `pid_ki`, `pid_kd` | PID tuning parameters (run the auto-tuner first) |
| `emergency_shutoff_temp` | Temperature at which the firing is aborted for safety |
| `cooled_safe_temp` | Below this temperature a finished kiln counts as safe to open (Alerts panel) |
| `automatic_restarts` | Resume firing automatically after a power outage |
| `kwh_rate`, `currency_type` | Cost settings for the firing cost estimate |

See the full `config.py` file and its comments for every available setting.

### Config Dump

At the very bottom of the Config tab, **Config Dump** downloads a zip of your
config, profiles, state, and logs -- useful when asking for help on the forum
or filing a bug report.

---

## Connection Status

The top-right corner shows whether the browser is connected to the controller.
If it says "Reconnecting", the connection was lost (e.g., Wi-Fi hiccup). The
interface reconnects automatically -- no action needed.

Multiple devices can view the interface simultaneously. Open it on your phone
and laptop at the same time.

---

## Theme

Click the moon/sun icon in the navbar to toggle between dark and light themes.
Your preference is remembered across page loads.

---

## Troubleshooting

### "Reconnecting" in the top-right corner / can't reach the interface

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

### Temperature reads 0 or shows wild fluctuations

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

### Temperature reads a constant wrong value

- **Thermocouple offset.** If your thermocouple reads consistently high or
  low, set `thermocouple_offset` in `config.py` to compensate. For example,
  if it reads 36F in ice water, set `thermocouple_offset = -4`.
- **Wrong thermocouple board.** Make sure `max31855 = 1` or `max31856 = 1`
  matches the board you actually have. The MAX31855 only works with K-type
  thermocouples.

### Kiln overshoots the target temperature

This is the most common tuning problem.

- **PID control window too narrow.** Increase `pid_control_window` (try 15
  or 20). A wider window lets PID control kick in sooner as the kiln
  approaches the target.
- **PID not tuned.** Run the PID Auto-Tuner on the Config tab. Manual
  tuning guide: [PID Tuning](pid_tuning.md).
- **Throttling not aggressive enough.** Lower `throttle_percent` (try 15 or
  10) and raise `throttle_below_temp` to limit power at low temperatures
  where overshoot is worst.
- **Integral windup.** If the error chart (Details tab) shows a large
  positive area under the curve, the integral term is too strong. Increase
  `pid_ki` (recall it's inverted -- a larger number means less integral).

### Kiln can't reach the target temperature

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

### Firing aborts unexpectedly

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

### "An oven is not a time-machine" error when saving a profile

Times in the profile must strictly increase. You can't have two points at the
same time or a point earlier than the previous one. Edit the table and make
sure each time value is greater than the one before it.

### Config save fails / controller won't start after editing config

- **Syntax error.** The controller validates `config.py` before saving, but
  if you manage to save a broken config (e.g., an undefined variable), the
  controller may crash on restart.
- **Fix via SSH.** Log into the Pi, edit `config.py` with a text editor,
  and restart the controller.
- **Restore from backup.** If you downloaded a Config Dump before making
  changes, extract `config.py` from the archive and copy it back.

### Firing doesn't resume after a power outage

- **Check `automatic_restarts`.** It must be `True` in `config.py`.
- **Check the restart window.** Power must come back within
  `automatic_restart_window` minutes (default 15). If the Pi was off longer
  than that, the firing is considered too risky to resume.
- **Check auto-start on boot.** The controller must start automatically
  when the Pi boots. Run `./start-on-boot` to set this up. Without it,
  the process never starts and can't resume the firing.
- **Check the state file.** The restart state is saved to `state.json`. Make
  sure `automatic_restart_state_file` points to a real path outside `/tmp`.

### Scheduled firing doesn't start on time

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

### Cost estimate seems wrong

- **Check `kw_elements`.** This should be the total kilowattage of all
  elements when fully on, not per-element.
- **Check `kwh_rate`.** This is cost per kilowatt-hour in your currency.
  Divide your total electricity bill by total kWh usage for an accurate
  rate.

### Charts on the Details tab are empty

- **No firing data yet.** The charts only populate during a running firing.
  Start a simulation (`simulate = True` in config) to see how they look.
- **Page was reloaded mid-firing.** Tuning data is stored in browser
  memory and localStorage. If you cleared browser data or used incognito
  mode, the history is lost. The charts will fill in again as new data
  arrives.

### Community profiles won't load

- **Check internet from the Pi.** SSH in and run
  `curl -s https://jbruce12000.github.io/kiln-profiles/schedules.json | head`.
  If that fails, the Pi can't reach the profile index.
- **GitHub Pages down.** The community index is hosted on GitHub Pages.
  Temporary outages happen. Try again later.

### Multiple browser tabs / devices show different data

This shouldn't happen -- all clients receive the same live data. If it does:

- **Refresh all tabs.** One tab may have an old WebSocket connection.
- **Check for stale localStorage.** The Details tab caches tuning data in
  the browser. A hard refresh (Ctrl+Shift+R) clears the current session
  data.

### The interface is very slow or unresponsive

- **Old browser.** The interface uses modern JavaScript features. Make sure
  your browser is up to date.
- **Too much tuning data.** After a very long firing (many hours), the
  Details tab charts may slow down. Refresh the page to clear the in-memory
  data and start fresh.

### Getting more help

If none of the above fixes your issue:

1. Download a **Config Dump** from the Config tab.
2. Check the [troubleshooting guide](troubleshooting.md) for hardware issues.
3. Open an issue on the [GitHub issue tracker](https://github.com/jbruce12000/kiln-controller/issues)
   and attach the config dump.
