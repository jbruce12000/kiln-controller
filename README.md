Kiln-Controller
==========

Turns a Raspberry Pi into a cheap, universal & web-enabled kiln controller.
Of course, since it is basically just a robot sensing temperature and controlling
environmental agitators (heating/cooling) you can use it as inspiration / basis
when you're in need of a PID based temperature controller for your project.
Don't forget to share and drop a link, when you do :)

**Standard Interface**

![Image](https://apollo.open-resource.org/_media/mission:resources:picoreflow_webinterface.jpg)

**Curve Editor**

![Image](https://apollo.open-resource.org/_media/mission:resources:picoreflow_webinterface_edit.jpg)

## Hardware

  * Raspberry Pi (Rev 2B)
  * MAX 31855/6675 Cold-Junction K-Type Thermocouple
  * GPIO driven Solid-State-Relays/MOSFETs

## Installation

#### Ubuntu/Raspbian libraries

    $ sudo apt-get install python-pip python-dev libevent-dev python-virtualenv

### Quick Start for all linux environments

    $ git clone https://github.com/jbruce12000/kiln-controller.git 
    $ cd kiln-controller
    $ virtualenv venv
    $ source venv/bin/activate
    $ pip install -r requirements.txt
    $ ./kiln-controller.py

## Configuration

All parameters are defined in config.py, just copy the example and review/change to your mind's content.

    $ cp config.py.EXAMPLE config.py


### Autostart Server onBoot
If you want the server to autostart on boot, run the following commands

    sudo cp /home/pi/picoReflow/lib/init/reflow /etc/init.d/
    sudo chmod +x /etc/init.d/reflow
    sudo update-rc.d reflow defaults

### Client Access

Open Browser and goto http://127.0.0.1:8080 (for local development) or the IP
of your PI and the port defined in config.py (default 8080).

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

