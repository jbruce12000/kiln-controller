Tuning PID Values
=================

This animation is worth a thousand words...

![Image](https://upload.wikimedia.org/wikipedia/commons/3/33/PID_Compensation_Animated.gif)

## The Goal
A controller with properly tuned PID values reacts quickly to changes in the set point, but does not overshoot much.  It settles quickly from any oscillations and hovers really close to the set point.  What do I mean by close? The average error for my kiln on a 13 hour schedule is .75 degrees F... and I have a noisy thermocouple, so it is possible to do even better.

## The Tuning Process

### Automatic Tuning

Contributor [ADQ](https://github.com/adq) worked hard on creating a [Ziegler Nicols auto-tuner](ziegler_tuning.md) which is python script that heats your kiln, saves data to a csv, and then gives you PID parameters for config.py.

### Manual Tuning

Even if you used the tuner above, it's likely you'll need to do some manual tuning. Let's start with some reasonable values for PID settings in config.py...

    pid_kp = 20
    pid_ki = 50
    pid_kd = 100

When you change values, change only one at a time and watch the impact. Change values by either doubling or halving.

Run a test schedule. I used a schedule that switches between 200 and 250 F every 30 minutes. The kiln will likely shoot past 200. This is normal. We'll eventually get rid of most of the overshoot, but probably not all.

Let's balance pid_ki first (the integral). The lower the pid_ki, the greater the impact it will have on the system. If a system is consistently low or high, the integral is used to help bring the system closer to the set point. The integral accumulates over time and has [potentially] a bigger and bigger impact.

* If you have a steady state (no oscillations), but the temperature is always above the set point, increase pid_ki.
* If you have a steady state (no oscillations), but the temperature is always below the set point, decrease pid_ki.
* If you have an oscillation but the temperature is mostly above the setpoint, increase pid_ki.
* If you have an oscillation but the temperature is mostly below the setpoint, decrease pid_ki.

Let's set pid_kp next (proportional). Think of pid_kp as a dimmable light switch that turns on the heat when below the set point and turns it off when above. The brightness of the dimmable light is defined by pid_kp. Be careful reducing pid_kp too much. It can result in strange behavior.

* If you have oscillations that don't stop or increase in size, reduce pid_kp
* If you have too much overshoot (after adjusting pid_kd), reduce pid_kp
* If you approach the set point wayyy tooo sloooowly, increase pid_kp
 
Now set pid_kd (derivative). pid_kd makes an impact when there is a change in temperature. It's used to reduce oscillations.

* If you have oscillations that take too long to settle, increase pid_kd
* If you have crazy, unpredictable behavior from the controller, reduce pid_kd

Expect some overshoot as the kiln reaches the set temperature the first time, but no oscillation.  Any holds or ramps after that should have a smooth transition and should remain really close to the set point [1 or 2 degrees F].

## Troubleshooting

* only change one value at a time, then test it.
* change values by doubling or halving
