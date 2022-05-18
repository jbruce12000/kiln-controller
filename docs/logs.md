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


If you need to send kiln logs to someone for troubleshooting:

```
cd kiln-controller
./ziplogs
```

that creates a file named kiln.logs.gz in the current directory suitable for
posting.

Here is a project I use to read logs to help troubleshoot logs you post...

https://github.com/jbruce12000/kiln-stats
