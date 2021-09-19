
import board
import digitalio
import adafruit_max31856
import RPi.GPIO as GPIO
import time

# Create sensor object, communicating over the board's default SPI bus
spi = board.SPI()

# allocate a CS pin and set the direction
cs = digitalio.DigitalInOut(board.D5)
cs.direction = digitalio.Direction.OUTPUT

# create a thermocouple object with the above
thermocouple = adafruit_max31856.MAX31856(spi, cs)

# print the temperature!
print(thermocouple.temperature)

relay1 = 23
relay2 = 24
trigger1 = 20
trigger2 = 21

GPIO.setmode(GPIO.BCM)
GPIO.setup(relay1, GPIO.OUT)
GPIO.setup(relay2, GPIO.OUT)
GPIO.setup(trigger1, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(trigger2, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

while True:
    print(thermocouple.temperature)
#    print("RELAY ON")
#    GPIO.output(relay1, 0) #ON
    GPIO.output(relay1, 1) #OFF
    GPIO.output(relay2, 1)
    time.sleep(5)
#    print("RELAY OFF")
#    GPIO.output(relay1, 0)
    GPIO.output(relay2, 0)
    time.sleep(5)
