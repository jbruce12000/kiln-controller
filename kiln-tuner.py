import os
import sys
import csv
import time
import argparse


try:
    sys.dont_write_bytecode = True
    import config
    sys.dont_write_bytecode = False

except:
    print("Could not import config file.")
    print("Copy config.py.EXAMPLE to config.py and adapt it for your setup.")
    exit(1)

script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir + '/lib/')
profile_path = os.path.join(script_dir, "storage", "profiles")

from oven import RealOven, SimulatedOven


def tune(csvfile, targettemp):
    # open the file to log data to
    f = open(csvfile, 'w')
    csvout = csv.writer(f)
    csvout.write(['time', 'temperature'])

    # construct the oven
    if config.simulate:
        oven = SimulatedOven()
    else:
        oven = RealOven()

    # Main loop:
    #
    # * heat the oven to the target temperature at maximum burn.
    # * when we reach it turn the heating off completely.
    # * wait for it to decay back to the target again.
    # * quit
    #
    # We record the temperature every config.sensor_time_wait
    try:
        stage = 'heating'
        if not config.simulate:
            oven.output.heat(1, tuning=True)

        while True:
            temp = oven.board.temp_sensor.temperature + \
                config.thermocouple_offset

            csvout.writerow([time.time(), temp])
            csvout.flush()

            if stage == 'heating':
                if temp > targettemp:
                    if not config.simulate:
                        oven.output.heat(0)
                    stage = 'decaying'

            elif stage == 'decaying':
                if temp < targettemp:
                    break

            sys.stdout.write(f"\n{stage} {temp}/{targettemp}           ")
            sys.stdout.flush()
            time.sleep(config.sensor_time_wait)

        f.close()

    finally:
        # ensure we always shut the oven down!
        if not config.simulate:
            oven.output.heat(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Record data for kiln tuning')
    parser.add_argument('csvfile', type=str, help="The CSV file to write to.")
    parser.add_argument('--targettemp', type='int', default=400, help="The target temperature to drive the kiln to.")
    args = parser.parse_args()

    tune(args.csvfile, args.targettemp)
