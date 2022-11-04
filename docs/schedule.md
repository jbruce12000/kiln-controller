Scheduling a Kiln Run
=====================

Our lives are busy. Sometimes you'll want your kiln to start at a scheduled time. This is really easy to do with the **at** command.


## Install the scheduler

This installs and starts the **at** scheduler.

    sudo apt-get update
    sudo apt-get install at

### Verify Time Settings

Verify the date and time and time zone are right on your system...

    date

    Fri 04 Nov 2022 01:01:14 PM EDT

If yours looks right, proceed to Examples. If not, you need to execute commands to set it. On a raspberry-pi, this is easiest by running

    sudo raspi-config

Localisation Options -> Timezone -> Pick one -> Ok


## Examples

Start a biscuit firing at 5am tomorrow morning...

    at 5:00am friday <<END
    curl -d '{"cmd":"run", "profile":"cone-05-long-bisque"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api
    END

Start a glaze firing in 15 minutes and start a kiln watcher...

    at now +15 minutes <<END
    curl -d '{"cmd":"run", "profile":"cone-6-long-glaze"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api
    source ~/kiln-controller/venv/bin/activate; ~/kiln-controller/watcher.jbruce.py
    END

List scheduled jobs...

    atq

Remove scheduled jobs...
 
    atrm jobid

where jobid is an integer that came from the atq output
