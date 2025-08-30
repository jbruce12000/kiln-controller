import logging
import threading
from RPLCD.i2c import CharLCD

log = logging.getLogger(__name__)
lock = threading.Lock()

class Display(object):
    def __init__(self):
        self.width = 16
        self.height = 2
        self.lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1,
              cols=self.width, rows=self.height,
              auto_linebreaks=False,
              backlight_enabled=True)
        self.lcd.cursor_mode = 'hide'
        self.clear()
        self.last_text = [''.ljust(self.width, ' ')] * self.height
    
    def set_text(self, lines, force_redraw=True):
        lines = list(map(lambda l: l.ljust(self.width, ' '), lines))
        while len(lines) < self.height:
            lines.append(''.ljust(self.width, ' '))
        diffs = []
        for j in range(0, len(lines)):
            if (len(lines[j]) is not len(self.last_text[j])):
                log.info('########### ' + lines[j] + ' - ' + self.last_text[j])
            for i in range(0, len(lines[j])):
                if lines[j][i] != self.last_text[j][i]:
                    diffs.append((j, i))
        if len(diffs) > 0:
            log.info('setting text to ' + str(lines))
            with lock:
                if len(diffs) < self.width*self.height/4 and not force_redraw:
                    log.info('updating only diffs')
                    for diff in diffs:
                        c = str(lines[diff[0]][diff[1]])
                        #log.info('updating pos ' + str(diff) + ' to "' + c + '"')
                        self.lcd.cursor_pos = diff
                        self.lcd.write_string(c)
                    self.lcd.cursor_pos = (0, 0)
                else:
                    log.info('updating full display')
                    #self.clear()
                    self.lcd.cursor_pos = (0, 0)
                    for line in lines:
                        self.lcd.write_string(line)
                        self.lcd.crlf()
                    self.lcd.cursor_pos = (0, 0)
                log.info('updating last_text from\n' + str(self.last_text) + ' to\n' + str(lines))
                self.last_text = lines

    def clear(self):
        self.lcd.clear()