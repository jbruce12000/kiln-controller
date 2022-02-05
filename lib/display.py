import tm1637
import logging

log = logging.getLogger(__name__)


class TM1637(object):
    def __init__(self,
                 clk_pin,
                 dat_pin):

        self.clk_pin = clk_pin
        self.dat_pin = dat_pin

        try:
            import tm1637
            self.tm = tm1637.TM1637(clk=clk_pin,
                                    dio=dat_pin)
        except ImportError as e:
            log.warning('import failure: \n%s' % e)

    def temp(self,
             t):
        self.tm.number(t)

    def time(self,
             h,
             m):
        self.tm.numbers(h, m, True)

    def text(self,
             text):
        self.tm.show(text[0:4])

    def off(self):
        self.tm.write([0, 0, 0, 0])
