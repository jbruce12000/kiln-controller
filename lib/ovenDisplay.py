import threading,logging,json,time,datetime
from oven import Oven
from displayhatmini import DisplayHATMini
log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("""This requires PIL/Pillow, try:

sudo apt install python3-pil

""")

class OvenDisplay(threading.Thread):
    def __init__(self,oven,ovenWatcher):
        self.last_profile = None
        self.last_log = []
        self.started = None
        self.recording = False
        self.observers = []
        threading.Thread.__init__(self)
        self.daemon = True
        # display HAT setup
        self.width = DisplayHATMini.WIDTH
        self.height = DisplayHATMini.HEIGHT
        self.buffer = Image.new("RGB", (self.width, self.height))
        self.draw = ImageDraw.Draw(self.buffer)
        self.displayhatmini = DisplayHATMini(self.buffer)
        self.displayhatmini.set_led(0.05, 0.05, 0.05)
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

    def update_display(self, oven_state):
        log.info(oven_state)
        self.text(oven_state, (25, 25), 15, (255, 255, 255))
        self.displayhatmini.display()


    def send(self,oven_state):
        self.update_display(oven_state)

    def text(self, text, position, size, color):
        fnt = ImageFont.load_default()
        self.draw.text(position, text, font=fnt, fill=color)

    