import threading,logging,time,json
import os
import config
from datetime import datetime, timedelta
from lib.display import Display
from lib.rotaryinput import RotaryInput

log = logging.getLogger(__name__)

def get_profiles():
    try:
        profile_files = os.listdir(config.kiln_profiles_directory)
    except:
        profile_files = []
    profiles = []
    for filename in profile_files:
        with open(os.path.join(config.kiln_profiles_directory, filename), 'r') as f:
            profiles.append(json.load(f))
    return profiles

class LCD():
    def __init__(self):
        self.clear()

    def write_string(self, string):
        s = self.text[self.cursor[0]]
        self.text[self.cursor[0]] = s[:self.cursor[1]] + string + s[self.cursor[1]+len(string):]
   
    def clear(self):
        self.text = [' ' * 16, ' ' * 16]
        self.cursor = (0, 0)
    
    def cursor_pos(self, pos):
        self.cursor = pos

    def show(self):
        #os.system('clear')
        print('-'*18)
        for t in self.text:
            print('|'+t+'|')
        print('-'*18)

#lcd = LCD()
lcd = Display()

class MenuNode():
    def __init__(self, text=None, type='menu', children=[], action=None, profile=None):
        self.parent = None
        self.type = type
        self.text = text
        self.action = action
        self.children = children
        self.profile = profile
        for child in children:
            child.set_parent(self)
        self.reset()
   
    def add_child(self, child):
        if self.children == None:
            self.children = []
        child.set_parent(self)
        self.children.append(child)
   
    def set_parent(self, parent):
        self.parent = parent
   
    def update_index(self, direction):
        self.index = max(0, min(self.index+direction, len(self.children)-1))
   
    def display_as_child(self, selected):
        return ('>' if selected else ' ') + self.text.ljust(14, ' ')[:14:] + ('>' if self.type == 'menu' else ' ')
   
    def display_confirm_options(self):
        no = ('>' if self.index == 0 else ' ') + self.children[0].text
        yes = ('>' if self.index == 1 else ' ') + self.children[1].text
        return no.ljust(16-len(yes), ' ') + yes
   
    def reset(self):
        self.index = 0
   


class Menu():
    def __init__(self, profiles, oven):
            self.build_menu(profiles)
            self.node = None
            self.oven = oven
            #self.node = self.off.children[1].children[1]
            #self.node.index = 1
   
    def build_menu(self, profiles):
        self.off = MenuNode(type='menu', children=[
            MenuNode(text='Back', action=self.go_up),
            MenuNode(text='Profiles', children=self.build_profiles_list(profiles))
        ])

        self.running = MenuNode(type='menu', children=[
            MenuNode(text='Back', action=self.go_up),
            MenuNode(text='Abort profile', children=[self.create_confirm_node(self.abort_profile)])
        ])
   
    def build_profiles_list(self, profiles):
        nodes = [MenuNode(text='Back', action=self.go_up)]
        for profile in profiles:
            node = MenuNode(text=profile['name'], profile=profile, children=[
                                MenuNode(text='Back', action=self.go_up),
                                MenuNode(text='Start', children=[self.create_confirm_node(self.start_profile, profile)])
                            ])
            nodes.append(node)
        return nodes
   
    def create_confirm_node(self, action, profile=None):
        return MenuNode(text='  Are you sure?', type='confirm', profile=profile, children=[
            MenuNode(text='No', action=self.go_up),
            MenuNode(text='Yes', action=action)
        ])
   
    def click(self):
        if self.node is None:
            # select menu based on oven state
            self.node = self.off if self.oven.profile is None else self.running
            return

        child = self.node.children[self.node.index]
        if child.action != None:
            child.action()
        elif len(child.children) == 0:
            return
        else:
            self.node = child
            while len(self.node.children) == 1:
                self.node = self.node.children[0]
           

    def next(self):
        if self.node is not None:
            self.node.update_index(1)

    def previous(self):
        if self.node is not None:
            self.node.update_index(-1)
   
    def go_up(self):
        self.node = self.node.parent
        while self.node is not None and len(self.node.children) == 1:
                self.node = self.node.parent
   
    def start_profile(self):
        self.oven.run_json_profile(json.dumps(self.node.profile))
        #self.oven.profile = self.node.profile
        self.node.reset()
        self.node = None

    def abort_profile(self):
        #self.oven.profile = None
        self.oven.abort_run()
        self.node.reset()
        self.node = None


fake_profiles = [{'profile': 'Bisque'}, {'profile': 'Glaze'}, {'profile': 'GlazeHigh'}, {'profile': 'Earthen'}]
real_profiles = get_profiles()
class OvenDisplay(threading.Thread):
    def __init__(self,oven):
        log.info('Starting oven display')
        threading.Thread.__init__(self)
        self.sleep_time = 1
        #self.daemon = True
        self.oven = oven
        log.info(real_profiles)
        self.menu = Menu(real_profiles, oven)
        self.input = RotaryInput()
        self.input.on_next(self.next)
        self.input.on_previous(self.previous)
        self.input.on_click(self.click)
        self.start()

    def next(self):
        self.menu.next()
        self.update_display()

    def previous(self):
        self.menu.previous()
        self.update_display()

    def click(self):
        self.menu.click()
        self.update_display()

    def run(self):
        while True:
            self.update_display()
            #inp = input()
            #if inp == 'a':
            #    self.menu.previous()
            #if inp == 'd':
            #    self.menu.next()
            #if inp == 'w':
            #    self.menu.click()
            time.sleep(self.sleep_time)
   
    def update_display(self):
        node = self.menu.node
        if node is None:
            self.show_status()
        elif node.type == 'menu':
            first_index = max(0, min(node.index, len(node.children)-2))
            new_text = [node.children[first_index].display_as_child(node.index == first_index)]
            if first_index+1 < len(node.children):
                new_text.append(node.children[first_index+1].display_as_child(node.index == first_index+1))
            lcd.set_text(new_text)
        elif node.type == 'confirm':
            lcd.set_text([node.text, node.display_confirm_options()])
           
    def show_status(self):
        new_text = [(str(round(self.oven.board.temp_sensor.temperature + config.thermocouple_offset)) +
                          #('/' + str(round(self.oven.target)) if self.oven.target > 0 else '')).ljust(12, ' ') +
                          #(str(self.oven.load) + '%' if self.oven.load > 0 else ' OFF') +
                          ('/' + str(round(self.oven.target)) if self.oven.target > 0 else '')).ljust(12, ' ') +
                          ('   H' if (self.oven.heat > 0 and self.oven.profile is not None) else ' OFF')]
        if self.oven.profile is None:
            new_text.append('Kiln on standby')
        else:
            time_left = timedelta(seconds=self.oven.totaltime - self.oven.runtime)
            new_text.append(self.oven.profile.name.ljust(10, ' ')[:10:] + ' ' + (datetime.now() + time_left).strftime("%H:%M"))
        lcd.set_text(new_text, True)

class Oven():
    def __init__(self):
        self.profile = None
        self.temp = 1030
        self.target_temp = 1035
        self.load = 75
        self.heating = True