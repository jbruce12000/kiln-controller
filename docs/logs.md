Logs for a Kiln Run
===================

Logs from the app on the pi go to **/var/log/daemon.log** and look like this...

    May 14 22:36:09 kiln python[350]: 2022-05-14 22:36:09,824 INFO oven: temp=1888.40, target=1888.00, error=-0.40, pid=54.33, p=-3.99, i=69.11, d=-10.79, heat_on=1.09, heat_off=0.91, run_time=27250, total_time=27335, time_left=84

| log variable | meaning |
| ------------ | ------- |
|temp | temperature read by thermocouple |
|target | target temperature |
|error | difference between target and temp |
|pid | pid value for that 2s |
|p | proportional value for that 2s |
|i | integral value for that 2s |
|d | derivative value for that 2s |
|heat_on | number of seconds the elements were on |
|heat_off | number of seconds the elements were off |
|run_time | seconds since start of schedule|
|total_time | total seconds for schedule |
|time_left | seconds left till the end of schedule|


Here is a project I use to read logs to help troubleshoot logs you post...

https://github.com/jbruce12000/kiln-stats

---

# Recording a Firing to CSV with kiln-logger.py

The daemon log above is good for troubleshooting, but it is prose buried in
**/var/log/daemon.log**. When you want the numbers themselves -- for
graphing, spreadsheets, or attaching to a bug report -- use
**kiln-logger.py**.

It connects to the same live status feed the web interface charts
(`ws://<host>:<port>/status`) and writes one row per sample to a csv file.
The controller broadcasts oven state every `sensor_time_wait` seconds
(2s by default), so an hour-long firing produces roughly 1800 rows.

## How to run it

Run it on any machine that can reach the controller (the pi itself, or your
laptop) while the kiln-controller process is up. A firing does not have to
be running -- idle states are logged too. Let it run for the whole firing;
it exits only when you kill it with ctrl-c.

```
source venv/bin/activate
./kiln-logger.py --hostname kiln.local:9099 --csvfile firing.csv --pidstats
```

Use the same host and port you point your browser at (see `listening_port`
in config.py). The script's own default is `localhost:8081`.

| Option | Meaning |
| ------ | ------- |
| `--hostname` | host:port of the controller (default `localhost:8081`) |
| `--csvfile` | where to write the csv (default `/tmp/kilnstats.csv`) |
| `--pidstats` | include PID columns (p, i, d, err, out, ...) |
| `--noprofilestats` | omit the standard profile columns |
| `--stdout` | also print each row to the terminal (tab separated) |

## Output columns

With the defaults plus `--pidstats` you get two groups of columns:

| standard column | meaning |
| --------------- | ------- |
| stamp | unix time the logger received the row (local clock of the machine running the logger) |
| runtime | seconds since the schedule started |
| temperature | thermocouple temperature |
| target | schedule target temperature right now |
| state | IDLE / RUNNING / PAUSED ... |
| heat | heater output for this sample |
| totaltime | total seconds in the schedule |
| profile | name of the running schedule |

| pid column | meaning |
| ---------- | ------- |
| pid_time / pid_timeDelta | PID loop timestamp and seconds since the previous compute |
| pid_setpoint / pid_ispoint | target vs measured temperature |
| pid_err / pid_errDelta | error and its rate of change |
| pid_p / pid_i / pid_d | proportional, integral, derivative terms |
| pid_kp / pid_ki / pid_kd | active tuning constants |
| pid_pid / pid_out | raw PID output (-50..50) and normalized duty cycle (0..1) |

## Behavior notes

* The csv file is **overwritten** each time you start the logger, so use a
  fresh filename per firing if you want to keep histories.
* Rows are stamped when the logger *receives* them; there may be a small
  skew versus the controller's own timestamps.
* If the network drops, the logger retries every 5 seconds indefinitely and
  keeps appending to the same file, so brief wifi hiccups do not lose the run.

## Analyzing the data

Any spreadsheet opens the csv directly. For pandas:

```python
import pandas as pd
df = pd.read_csv("firing.csv")
df.plot(x="stamp", y=["temperature", "target"])
```

For posting logs when asking for help, see also the **Config Dump** button
on the Config tab of the web interface, which bundles config, profiles,
state, and logs into one download (see the
[Web Interface Guide](web-interface.md)).
