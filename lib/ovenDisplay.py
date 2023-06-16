import threading,logging,json,time,datetime
from oven import Oven
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
fnt25 = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 25, encoding="unic")
fnt50 = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 50, encoding="unic")
fnt75 = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 75, encoding="unic")

class OvenDisplay(threading.Thread):
    def __init__(self,oven,ovenWatcher):
        self.last_profile = None
        self.last_log = []
        self.started = None
        self.recording = False
        self.observers = []
        threading.Thread.__init__(self)
        self.daemon = True
        # oven setup
        self.oven = oven
        self.ovenWatcher = ovenWatcher
        ovenWatcher.add_observer(self)
        # TODO - move to config
        self.sleep_time = 0.1
        draw.rectangle((0, 0, width, height), (0, 0, 0))
        self.text("Initialising...", (25, 25), fnt25, (255,255,255))
        displayhatmini.display()
        displayhatmini.set_led(0.0, 0.0, 0.0)
        self.start()

    def run(self):
        while True:
            #oven_state = self.oven.get_state()
            #update_display(oven_state)    
            time.sleep(self.sleep_time)

    # {'cost': 0, 'runtime': 0, 'temperature': 23.176953125, 'target': 0, 'state': 'IDLE', 'heat': 0, 'totaltime': 0, 'kwh_rate': 0.33631, 'currency_type': '£', 'profile': None, 'pidstats': {}}
    # {'cost': 0.003923616666666667, 'runtime': 0.003829, 'temperature': 23.24140625, 'target': 100.00079770833334, 'state': 'RUNNING', 'heat': 1.0, 'totaltime': 3600, 'kwh_rate': 0.33631, 'currency_type': '£', 'profile': 'test-200-250', 'pidstats': {'time': 1686902305.0, 'timeDelta': 5.027144, 'setpoint': 100.00079770833334, 'ispoint': 23.253125, 'err': 76.74767270833334, 'errDelta': 0, 'p': 1918.6918177083335, 'i': 0, 'd': 0, 'kp': 25, 'ki': 10, 'kd': 200, 'pid': 0, 'out': 1}}
    def update_display(self, oven_state_json):
        draw.rectangle((0, 0, width, height), (0, 0, 0))
        log.info(oven_state_json)
        state = json.loads(oven_state_json)
        log.info(state)
        if (state['temperature'] is not None):
            self.text("{0:2.0f}°C".format(state['temperature']), (25, 25), fnt75, (255, 255, 255))
        else:
            self.text("---°C", (25, 25), fnt75, (255, 255, 255))

        if (state['target'] is not None):
            self.text("Target: {0:2.0f}°C".format(state['target']), (25, 100), fnt25, (255, 255, 255))
        else:
            self.text("Target: ---°C", (25, 100), fnt25, (255, 255, 255))

        if (state['profile'] is not None):
            self.text(state['profile'], (25, 175), fnt25, (255, 255, 255))
        else:
            self.text("No Programme", (25, 175), fnt25, (255, 255, 255))

        displayhatmini.display()

        if (state['state'] is None):
            displayhatmini.set_led(0.0, 0.0, 0.0)
        else:
            if (state['state'] is None or state['state'] == 'IDLE'):
                displayhatmini.set_led(0.0, 0.2, 0.0)
            else:
                self.text(state['state'], (25, 200), fnt25, (255, 255, 255))
                if (state['heat'] == 1.0):
                    displayhatmini.set_led(1.0, 0.0, 0.0)
                else:
                    displayhatmini.set_led(0.0, 0.0, 1.0)
        

    def send(self,oven_state):
        self.update_display(oven_state)

    def text(self, text, position, fnt, color):
        #fnt = ImageFont.load_default()
        draw.text(position, text, font=fnt, fill=color)

    