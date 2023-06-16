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
displayhatmini.set_led(0.05, 0.05, 0.05)
draw = ImageDraw.Draw(buffer)
fnt50 = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 50, encoding="unic")
fnt25 = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 25, encoding="unic")

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
        self.start()

    def run(self):
        while True:
            #oven_state = self.oven.get_state()
            #update_display(oven_state)    
            time.sleep(self.sleep_time)

    # {'cost': 0, 'runtime': 0, 'temperature': 23.176953125, 'target': 0, 'state': 'IDLE', 'heat': 0, 'totaltime': 0, 'kwh_rate': 0.33631, 'currency_type': '£', 'profile': None, 'pidstats': {}}
    def update_display(self, oven_state):
        draw.rectangle((0, 0, width, height), (0, 0, 0))
        log.info(oven_state)
        state = json.loads(oven_state)
        log.info(state)
        self.text("{0:2.1f}".format(state['temperature']), (25, 25), fnt50, (255, 255, 255))
        self.text("{0:2.1f}".format(state['target']), (25, 75), fnt25, (255, 255, 255))
        displayhatmini.display()

    def send(self,oven_state):
        self.update_display(oven_state)

    def text(self, text, position, fnt, color):
        #fnt = ImageFont.load_default()
        draw.text(position, text, font=fnt, fill=color)

    