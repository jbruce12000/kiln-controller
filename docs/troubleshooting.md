Troubleshooting
==========

When I started this project, I'd never worked with RPi gpio.  I think I got
just about everything backwards possible.  I blew up a MAX-31855 chip... POOF,
up in smoke!

So, invest a little time to learn the hardware and the software available to
you to verify everything works as expected.

## Breadboard Orientation

![Image](https://github.com/jbruce12000/kiln-controller/blob/master/public/assets/images/breadboard.png)

If you're using a breadboard with a labeled break-out board, verify:

* where pin one is using a multimeter.  it sounds stupid, but it will save you time.
* measure the voltage between all the 3V3 pins and a GND pin
* measure the voltage between all the GND pins and a GND pin
* measure the voltage between the 5V pins and a GND pin

## Test Each GPIO Pin

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
