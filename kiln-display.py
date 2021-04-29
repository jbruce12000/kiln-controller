#!/usr/bin/env python

from os import supports_dir_fd
import websocket
import json
import time
import datetime
import argparse
import digitalio
import board
import adafruit_rgb_display.st7789 as st7789
from PIL import Image, ImageDraw, ImageFont

# This is designed to drive an Adafruit Mini PiTFT 1.3" (https://www.adafruit.com/product/4484)
#
# You will require a copy of DroidSans.ttf in /home/pi
#
# As this occupies the GPIOs currently used as defaults in config.py, you'll have to rewrire your Pi.
# Remember to update config.py with the new ones!
#
# Technically you do not need to install numpy, but it is very much recommended as the
# non-numpy fallback code will consume much CPU.


def display(hostname, minupdatesecs, font_ttf):
    status_ws = websocket.WebSocket()
    storage_ws = websocket.WebSocket()

    # Configuration for CS and DC pins for Raspberry Pi
    cs_pin = digitalio.DigitalInOut(board.CE0)
    dc_pin = digitalio.DigitalInOut(board.D25)
    reset_pin = None
    BAUDRATE = 64000000  # The pi can be very fast!
    # Create the ST7789 display:
    display = st7789.ST7789(
        board.SPI(),
        cs=cs_pin,
        dc=dc_pin,
        rst=reset_pin,
        baudrate=BAUDRATE,
        height=240, y_offset=80, rotation=180
    )
    display.fill()

    # turn backlight on
    backlight = digitalio.DigitalInOut(board.D22)
    backlight.switch_to_output()
    backlight.value = True

    # create screen and font
    screen = Image.new("RGB", (display.width, display.height), (0, 0, 0))
    screend = ImageDraw.Draw(screen)
    screenfont = ImageFont.truetype(font_ttf, 46)
    chartminx = 0
    chartw = display.width
    chartminy = int(display.height / 2)
    charth = int(display.height / 2)

    # main loop
    cur_profile = None
    last_update = datetime.datetime.now()
    while True:
        # gather data from kiln controller.
        try:
            msg = json.loads(status_ws.recv())
            if msg.get('profile') and not cur_profile:
                storage_ws.send('GET')
                for profile in json.loads(storage_ws.recv()):
                    if profile['name'] == msg.get('profile'):
                        cur_profile = profile
                        break

            elif not msg.get('profile'):
                cur_profile = None

        except websocket.WebSocketException:
            try:
                status_ws.connect(f'ws://{hostname}/status')
                storage_ws.connect(f'ws://{hostname}/storage')
            except Exception:
                time.sleep(5)

            continue

        # we don't need to update ALL the time
        if (datetime.datetime.now() - last_update).total_seconds() < minupdatesecs:
            continue
        last_update = datetime.datetime.now()

        # setup the basic display
        screend.rectangle([0, 0, display.width, display.height], fill='black')
        screend.line([chartminx, chartminy, chartminx + chartw, chartminy], fill='white')

        # show the current temperature
        if msg.get('temperature'):
            temp = int(msg['temperature'])
            text = f"{temp}°"
            (tw, th) = screenfont.getsize(text)
            screend.text((0, display.height - th), text, font=screenfont, fill='blue')

        # inform if we're actively heating
        if msg.get('heat'):
            spot_radius = 20
            spot_x = (display.width - spot_radius) / 2
            spot_y = display.height - spot_radius - 5
            screend.ellipse((spot_x, spot_y, spot_x + spot_radius, spot_y + spot_radius), fill='red')

        # if we have a profile, show details of that!
        if cur_profile:
            cur_profile_data = cur_profile['data']

            # compute ranges of data
            mintime = min([i[0] for i in cur_profile_data])
            maxtime = max([i[0] for i in cur_profile_data])
            timerange = maxtime - mintime
            mintemp = 0
            maxtemp = max([i[1] for i in cur_profile_data])
            temprange = maxtemp - mintemp

            # draw chart of the temperature profie
            line = []
            for i in sorted(cur_profile_data, key=lambda x: x[0]):
                x = chartminx + (((i[0] - mintime) * chartw) / timerange)
                y = chartminy - (((i[1] - mintemp) * charth) / temprange)
                line.extend([x, y])
            screend.line(line, fill='yellow')

            # draw current position as a blue line
            cur_time = msg['runtime'] if msg['runtime'] > 0 else 0
            cur_time_x = ((cur_time - mintime) * chartw) / timerange
            cur_temp = int(msg['temperature'])
            cur_temp_y = ((cur_temp - mintemp) * charth) / temprange
            screend.line([chartminx + cur_time_x, chartminy, chartminx + cur_time_x, chartminy - charth], fill='blue')

            # draw target temperature
            target = int(msg['target'])
            text = f"{target}°"
            (tw, th) = screenfont.getsize(text)
            screend.text((display.width - tw, display.height - th), text, font=screenfont, fill='yellow')

            # show where we are
            time_done = msg['runtime'] if msg['runtime'] > 0 else 0
            time_done_mins = int((time_done / 60) % 60)
            time_done_hours = int(time_done / 60 / 60)
            screend.text((0, chartminy), f"{time_done_hours:02d}:{time_done_mins:02d}", font=screenfont, fill='blue')

            # show how long we have left
            time_left = msg['totaltime'] - msg['runtime']
            time_left_mins = int((time_left / 60) % 60)
            time_left_hours = int((time_left / 60) / 60)
            text = f"{time_left_hours:02d}:{time_left_mins:02d}"
            (tw, th) = screenfont.getsize(text)
            screend.text((display.width - tw, chartminy), text, font=screenfont, fill='white')

        # update display
        display.image(screen)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Log kiln data for analysis.')
    parser.add_argument('--hostname', type=str, default="localhost:8081", help="The kiln-controller hostname:port")
    parser.add_argument('--minupdatesecs', type=int, default="10", help="Number of seconds between screen updates")
    parser.add_argument('--font_ttf', type=str, default='/home/pi/DroidSans.ttf', help="Font to use for text display")
    args = parser.parse_args()

    display(args.hostname, args.minupdatesecs, args.font_ttf)
