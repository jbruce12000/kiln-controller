Kiln Controller
==========

Turns a Raspberry Pi into a cheap, web-enabled kiln controller.

## Features

  * easy to install and run on most Raspberry Pi versions
  * easy to create new kiln schedules and edit / modify existing schedules
  * no limit to runtime - fire for days if you want
  * view status from multiple devices at once - computer, tablet etc
  * firing cost estimate
  * NIST-linearized conversion for accurate K type thermocouple readings
  * supports PID parameters you tune to your kiln

**Standard Interface**

![Image](https://apollo.open-resource.org/_media/mission:resources:picoreflow_webinterface.jpg)

**Curve Editor**

![Image](https://apollo.open-resource.org/_media/mission:resources:picoreflow_webinterface_edit.jpg)

## Hardware

  * Raspberry Pi
  * MAX 31855/6675 Cold-Junction K-Type Thermocouple
  * GPIO driven Solid-State-Relay

## Installation

### Raspbian

Download [NOOBs](https://www.raspberrypi.org/downloads/noobs/). Copy files to an SD card. Install raspian on RPi using NOOBs.

    $ sudo apt-get install python-pip python-dev libevent-dev python-virtualenv
    $ git clone https://github.com/jbruce12000/kiln-controller.git
    $ cd kiln-controller
    $ virtualenv venv
    $ source venv/bin/activate
    $ pip install greenlet bottle gevent gevent-websocket

Note: the above steps work on ubuntu if you prefer

### Raspberry PI deployment

If you want to deploy the code on a PI for production:

    $ cd kiln-controller
    $ virtualenv venv
    $ source venv/bin/activate
    $ pip install RPi.GPIO

If you also want to use the in-kernel SPI drivers with a MAX31855 sensor:

    $ pip install Adafruit-MAX31855

## Configuration

All parameters are defined in config.py, just copy the example and review/change to your mind's content.

    $ cp config.py.EXAMPLE config.py

## Usage

### Server Startup

    $ ./kiln-controller.py

### Autostart Server onBoot
If you want the server to autostart on boot, run the following commands

    $ /home/pi/kiln-controller/start-on-boot

### Client Access

Open Browser and goto http://127.0.0.1:8080 (for local development) or the IP
of your PI and the port defined in config.py (default 8080).

### Simulation

Select a profile and click Start. If you do not have a raspberry pi connected
and configured, or if you don't install the Adafruit-MAX31855 library, then
your run will be simulated.  Simulations run at near real time and kiln
characteristics are defined in config.py.

## License

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

## Support & Contact

Please use the issue tracker for project related issues.

More info: https://apollo.open-resource.org/mission:resources:picoreflow
