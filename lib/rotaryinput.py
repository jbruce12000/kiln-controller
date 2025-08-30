from RPi_GPIO_Rotary import rotary

class RotaryInput():
    def __init__(self):
        ## Initialise (clk, dt, sw, ticks)
        self.input = rotary.Rotary(18,15,14,2)
        self.input.start()
    
    def on_next(self, action):
        self.input.register(increment=action)
    
    def on_previous(self, action):
        self.input.register(decrement=action)
    
    def on_click(self, action):
        self.input.register(pressed=action)
    
    def stop(self):
        self.input.stop()