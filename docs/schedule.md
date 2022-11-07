Scheduling a Kiln Run
=====================

Our lives are busy. Sometimes you'll want your kiln to start at a scheduled time. This is really easy to do with the **at** command. Scheduled events persist if the raspberry pi reboots.

## Install the scheduler

This installs and starts the **at** scheduler.

    sudo apt-get update
    sudo apt-get install at

### Verify Time Settings

Verify the date and time and time zone are right on your system:

    date

If yours looks right, proceed to **Examples**. If not, you need to execute commands to set it. On a raspberry-pi, this is easiest by running...

    sudo raspi-config

Localisation Options -> Timezone -> Pick one -> Ok


## Examples

Start a biscuit firing at 5am Friday morning:

    at 5:00am friday <<END
    curl -d '{"cmd":"run", "profile":"cone-05-long-bisque"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api
    END

Start a glaze firing in 15 minutes and start a kiln watcher. This is really useful because the kiln watcher should page you in slack if something is wrong with the firing:

    at now +15 minutes <<END
    curl -d '{"cmd":"run", "profile":"cone-6-long-glaze"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api
    source ~/kiln-controller/venv/bin/activate; ~/kiln-controller/watcher.jbruce.py
    END

Start a biscuit fire at 1a tomorrow, but skip the first two hours [120 minutes] of candling because I know my wares are dry. Start a kiln watcher 15 minutes later to give the kiln time to reach temperature so the watcher does not page me. 

    at 1am tomorrow <<END
    curl -d '{"cmd":"run", "profile":"cone-05-long-bisque","startat":120}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api
    END
    at 1:15am tomorrow <<END
    source ~/kiln-controller/venv/bin/activate; ~/kiln-controller/watcher.jbruce.py
    END

Stop any running firing at 3pm tomorrow:

    at 3pm tomorrow <<END
    curl -d '{"cmd":"stop"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api
    END

Start a 15 hour long glaze firing in 5 minutes and schedule for graphs from [kiln-stats](https://github.com/jbruce12000/kiln-stats) to be created on the raspberry-pi afterward and make the graphs available via a web server running on port 8000. You can do all kinds of interesting things with this. You could create a single job for the webserver and a job per hour to update the graphs. This way you can see detailed graphs of PID params and how the system is responding to them.

    at now + 5 minutes <<END
    curl -d '{"cmd":"run", "profile":"cone-6-long-glaze"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api
    END 

    at now + 16 hours <<END
    source ~/kiln-stats/venv/bin/activate; cd ~/kiln-stats/scripts/; cat /var/log/daemon.log |~/kiln-stats/scripts/log-splitter.pl |grep ^1>~/kiln-stats/input/daemon.log; ~/kiln-stats/scripts/go; cd ~/kiln-stats/output; python3 -m http.server
    END

List scheduled jobs...

    atq

Remove scheduled jobs...
 
    atrm jobid

where jobid is an integer that came from the atq output
