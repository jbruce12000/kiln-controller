# PID Tuning Using Ziegler-Nicols

This uses the Ziegler Nicols method to estimate values for the Kp/Ki/Kd PID control values.

The method implemented here is taken from ["Ziegler–Nichols Tuning Method"](https://www.ias.ac.in/article/fulltext/reso/025/10/1385-1397) by Vishakha Vijay Patel

One issue with Ziegler Nicols is that is a **heuristic**: it generally works quite well, but it might not be the optimal values. Further manual adjustment may be necessary.

  - make sure the kiln-controller is **stopped**
  - make sure your kiln is in the same state it will be in during a normal firing. For instance, if you use a kiln vent during normal firing, make sure it is on.
  - make sure the kiln is completely cool. We need to record the data starting from room temperature to correctly measure the effect of kiln/heating.

## Step 1: Stop the kiln-controller process

If the kiln controller auto-starts, you'll need to stop it before tuning...

```sudo service kiln-controller stop```

After, you're done with the tuning process, just reboot and the kiln-controller will automatically restart.

## Step 2: Run the Auto-Tuner

run the auto-tuner:
```
source venv/bin/activate; ./kiln-tuner.py
```

The kiln-tuner will heat your kiln to 400F. Next it will start cooling. Once the temperature goes back to 400F, the PID values are calculated and the program ends. The output will look like this:

```
stage = cooling, actual = 401.51, target = 400.00
stage = cooling, actual = 401.26, target = 400.00
stage = cooling, actual = 401.01, target = 400.00
stage = cooling, actual = 400.77, target = 400.00
stage = cooling, actual = 400.52, target = 400.00
stage = cooling, actual = 400.28, target = 400.00
stage = cooling, actual = 400.03, target = 400.00
stage = cooling, actual = 399.78, target = 400.00
pid_kp = 14.231158917317776
pid_ki = 4.745613033146341
pid_kd = 240.27736881914797
```

## Step 3: Replace the PID parameters in config.py

Copy & paste the pid_kp, pid_ki, and pid_kd values into config.py and restart the kiln-controller. Test out the values by firing your kiln. They may require manual adjustment.

## The values didn't work for me.

The Ziegler Nicols estimate requires that your graph look similar to this: [kiln-tuner-example.png](kiln-tuner-example.png). The smooth linear part of the chart is very important. If it is too short, try increasing the target temperature (see later). The red diagonal line **must** follow the smooth part of your chart closely.

## My diagonal line isn't right

You might need to adjust the line parameters to make it fit your data properly. You'll do this using previously saved data without the need to heat & cool again. 

```
source venv/bin/activate;./kiln-tuner.py -c -s -d 4
```

| Parameter | Description |
| --------- | ----------- |
| -c | calculate only (don't heat/cool and record) |
| -s | show plot (requires pyplot be installed in the virtual env) |
| -d float | tangent divisor which modifies which part of the profile is used to calculate the line. Must be >= 2.0. Vary it to get a better fit. |

## Changing the target temperature

By default it is 400F. You can change this as follows:

```
python kiln-tuner.py -t 500
```
