import threading,logging,json,time,datetime
from oven import Oven, Profile
from displayhatmini import DisplayHATMini
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# display HAT setup
width = DisplayHATMini.WIDTH
height = DisplayHATMini.HEIGHT
buffer = Image.new("RGB", (width, height))
displayhatmini = DisplayHATMini(buffer)
displayhatmini.set_led(0.0, 0.2, 0.0)
draw = ImageDraw.Draw(buffer)
# Font path on a Raspberry Pi running Raspbian
font_path = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
fnt25 = ImageFont.truetype(font_path, 25, encoding="unic")
fnt50 = ImageFont.truetype(font_path, 50, encoding="unic")
fnt75 = ImageFont.truetype(font_path, 75, encoding="unic")

class OvenDisplay(threading.Thread):
    def __init__(self,oven,ovenWatcher,sleepTime):
        self.last_profile = None
        self.last_log = []
        self.started = None
        self.recording = False
        self.observers = []
        self.profiles = None
        self.profile = None
        threading.Thread.__init__(self)
        self.display_lock = threading.Lock()
        self.daemon = True
        # oven setup
        self.oven = oven
        self.ovenWatcher = ovenWatcher
        ovenWatcher.add_observer(self)
        self.sleep_time = sleepTime
        with self.display_lock:
            draw.rectangle((0, 0, width, height), (0, 0, 0))
            self.text("Initialising...", (25, 25), fnt25, (255,255,255))
            displayhatmini.display()
            displayhatmini.set_led(0.0, 0.0, 0.0)
        self.start()

    def run(self):
        while True:
            a_pressed = displayhatmini.read_button(displayhatmini.BUTTON_A)
            b_pressed = displayhatmini.read_button(displayhatmini.BUTTON_B)
            x_pressed = displayhatmini.read_button(displayhatmini.BUTTON_X)
            y_pressed = displayhatmini.read_button(displayhatmini.BUTTON_Y)
            if (x_pressed):
                self.start_oven()
            if (y_pressed):
                self.stop_oven()
            if (a_pressed):
                self.prev_profile()
            if (b_pressed):
                self.next_profile()
            self.update_display(self.oven.get_state())
            time.sleep(self.sleep_time)

    def update_profiles(self, new_profiles):
        log.info("New profiles ")
        log.info(new_profiles)
        self.profiles = new_profiles

    # Example contents of oven_state
    # {'cost': 0, 'runtime': 0, 'temperature': 23.176953125, 'target': 0, 'state': 'IDLE', 'heat': 0, 'totaltime': 0, 'kwh_rate': 0.33631, 'currency_type': '£', 'profile': None, 'pidstats': {}}
    # {'cost': 0.003923616666666667, 'runtime': 0.003829, 'temperature': 23.24140625, 'target': 100.00079770833334, 'state': 'RUNNING', 'heat': 1.0, 'totaltime': 3600, 'kwh_rate': 0.33631, 'currency_type': '£', 'profile': 'test-200-250', 'pidstats': {'time': 1686902305.0, 'timeDelta': 5.027144, 'setpoint': 100.00079770833334, 'ispoint': 23.253125, 'err': 76.74767270833334, 'errDelta': 0, 'p': 1918.6918177083335, 'i': 0, 'd': 0, 'kp': 25, 'ki': 10, 'kd': 200, 'pid': 0, 'out': 1}}
    def update_display(self, oven_state):
        with self.display_lock:
            draw.rectangle((0, 0, width, height), (0, 0, 0))
            # TODO - remove this - will use up too much disk
            log.info(oven_state)
            if (oven_state['temperature'] is not None):
                self.text("{0:2.0f}°C".format(oven_state['temperature']), (10, 10), fnt75, (255, 255, 255))
            else:
                self.text("---°C", (10, 10), fnt75, (255, 255, 255))

            if (oven_state['target'] is not None):
                self.text("Target: {0:2.0f}°C".format(oven_state['target']), (10, 90), fnt25, (255, 255, 255))
            else:
                self.text("Target: ---°C", (10, 90), fnt25, (255, 255, 255))


            if (oven_state['profile'] is not None):
                active_profile_name = oven_state['profile']
            else:
                if (self.profile is not None):
                    active_profile_name = self.profile['name']
                else:
                    active_profile_name = 'No Programme'

            self.text(active_profile_name, (10, 125), fnt25, (100, 255, 255))

            if (oven_state['state'] is None):
                self.text("Initialising", (10, 10), fnt25, (255, 255, 255))
                displayhatmini.set_led(0.0, 0.0, 0.0)
            else:
                self.text(oven_state['state'], (10, 160), fnt25, (255, 255, 255))
                if (oven_state['state'] == 'IDLE'):
                    if (self.profile is None):
                        # no light indicates we can't start a programme
                        displayhatmini.set_led(0.0, 0.0, 0.0)
                    else:
                        # green light indicates we can start a programme
                        displayhatmini.set_led(0.0, 0.5, 0.0)
                else:
                    self.text(oven_state['state'], (10, 160), fnt25, (255, 255, 255))
                    if (oven_state['heat'] == 1.0):
                        displayhatmini.set_led(1.0, 0.0, 0.0)
                    else:
                        displayhatmini.set_led(0.0, 0.0, 1.0)
                    message = ''
                    message_colour = (0,255,255)
                    if (oven_state['totaltime'] is not None and oven_state['runtime'] is not None):
                        total_time = oven_state['totaltime']      
                        run_time = oven_state['runtime']  
                        time_left = total_time - run_time    
                        time_left_str = str(datetime.timedelta(seconds=round(time_left)))
                        message = 'Remaining: ' + time_left_str;
                    if (oven_state['status'] is not None and oven_state['status'] != ""):
                        message = oven_state['status']
                        message_colour = (255,0,0)
                    self.text(message, (10, 195), fnt25, message_colour)
            displayhatmini.display()

    def send(self,oven_state_json):
        #log.info(oven_state_json)
        oven_state = json.loads(oven_state_json)
        self.update_display(oven_state)

    def text(self, text, position, fnt, color):
        draw.text(position, text, font=fnt, fill=color)

    def stop_oven(self):
        log.info("Aborting run")
        self.oven.abort_run()

    def start_oven(self):
        if (self.profile is None):
            log.error("No programme to start")
        else:
            log.info("Starting run " + self.profile['name'])
            profile_json = json.dumps(self.profile)
            oven_profile = Profile(profile_json)
            self.oven.run_profile(oven_profile)

    def prev_profile(self):
        log.info("Prev profile")
        idx = self.find_profile_idx()
        new_idx = (idx - 1) % len(self.profiles)
        self.profile = self.profiles[new_idx]

    def next_profile(self):
        log.info("Next profile")
        idx = self.find_profile_idx()
        new_idx = (idx + 1) % len(self.profiles)
        self.profile = self.profiles[new_idx]

    def find_profile_idx(self):
        for idx, p in enumerate(self.profiles):
            if (p == self.profile):
                return idx
        return 0
