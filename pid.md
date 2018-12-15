* create a stepped schedule

200
220
200
220

* set i=0
* set d=0
* set p=5

run schedule
if oscillation is sustained stop
otherwise, double p

once oscillation is sustained
* record P as Ku
* record period of oscillation as Pu

set p=Ku/1.7
set i=Pu/2
set d=Pu/8

-------------------------------------------------------------------------------
another method (for just PI control)
https://pdfs.semanticscholar.org/e719/f259f6c93b9a897a214824e562c886aa80b9.pdf


use step schedule
set d=0
set p=1
you should see some overshoot and barely observable undershoot
if not, change p until that's true (up or down)

next measure T between high peak and low peak
set i=T*1.5
set p=.8*lastp

p=1*.8 = .8
i=1040-315 = 725s * 1.5 = 1088

-------------------------------------------------------------------------------
https://www.eurotherm.com/pid-control-made-easy

similar to above for PI

p=2*25=50 (that's 25F overshoot times 2)
i=725*1.5 = 1088
d = 1088/5 = 217



