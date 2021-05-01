Tuning PID Values
=================

This animation is worth a thousand words...

![Image](https://upload.wikimedia.org/wikipedia/commons/3/33/PID_Compensation_Animated.gif)

## The Goal
A controller with properly tuned PID values reacts quickly to changes in the set point, but does not overshoot much.  It settles quickly from any oscillations and hovers really close to the set point.  What do I mean by close? The average error for my kiln on a 13 hour schedule is .75 degrees F... and I have a noisy thermocouple, so it is possible to do even better.

## Try the Existing Values

My kiln is Skutt KS-1018 with a kiln vent.  Try the current settings for pid_kp, pid_ki, and pid_kd and if they work for you, you're done.  Otherwise, you have some experimentation ahead of you.  The following exercise took me about 2 hours of testing. 

## The Tuning Process

in config.py set the PID values like so...

    pid_kp = 1.0
    pid_ki = 0.0
    pid_kd = 0.0

run a test schedule. I used a schedule that switches between 200 and 250 F every 30 minutes.

What you are looking for is overshoot (in my case 25F) past 200F to 225F. The next thing the controller should do is undershoot by just a little below the set point of 200F. If these two things happen, great.  If not, you will need to change pid_kp to a higher or lower value.

Once you get the overshoot and minimal undershoot, you need to record some values.  First grab the overshoot... in my case 25F.

    pid_kp = 25

Measure the time in seconds from high peak to low peak. In my case this was 725 seconds.  Multiply that number by 1.5 to get the Integral. So 725 * 1.5 = 1088.

    pid_ki = 1088

Now set the derivative at 1/5 of the Integral. So 1088/5 = 217

    pid_kd = 217

in essence these values mean...

| setting | Value | Action |
| ------- | ----- | ------ |
| pid_kp | 25 | react pretty slowly |
| pid_ki | 1088 | predict really far forward in time and make changes early |
| pid_kd | 217 | heavily dampen oscillations |

Now, run the test schedule again and see how well it works.  Expect some overshoot as the kiln reaches the set temperature the first time, but no oscillation.  Any holds or ramps after that should have a smooth transition and should remain really close to the set point [1 or 2 degrees F].

## Troubleshooting

* only change one value at a time, then test it.
* If there is too much overshoot, decrease pid_kp.
* If the temp is always below the set point, decrease pid_ki (which increases the integral action).
* if the above does not work, try the Ziegler / Nichols method https://blog.opticontrols.com/archives/477
