Logs for a Kiln Run
===================

Logs from the app on the pi go to /var/log/daemon.log and look like this...

    Jan 21 06:25:40 raspberrypi python[286]: 2019-01-21 06:25:40,390 INFO oven: temp =1092.4, target=1093.2, pid=1.000, heat_on=2.00, heat_off=0.00, run_time=15993, total_time=48780, time_left=32786

| log entry | meaning |
| --------- | ------- |
|temp | temperature read by thermocouple |
|target | target temperature |
|pid | pid value for that 2s |
|heat_on | number of seconds the elements were on |
|heat_off | number of seconds the elements were off |
|run_time | seconds since start of schedule|
|total_time | total seconds for schedule |
|time_left | seconds left till the end of schedule|

It's trivial to convert the data to csv...

    grep "INFO oven" daemon.log|sed 's/temp=//'|sed 's/target=//'|sed 's/heat_on=//'|sed 's/heat_off=//'|sed 's/run_time=//'|sed 's/total_time=//'|sed 's/time_left=//'|sed 's/pid=//'|sed 's/.*: //' >out2.csv

Here is a slow glaze firing imported into google docs. Make sure to check out the report tab.

https://docs.google.com/spreadsheets/d/1Lcp88P1cNNzYWgKDfnd5UaPVqLuBdAT3lkpfcZMKEBM/edit#gid=2116406322
