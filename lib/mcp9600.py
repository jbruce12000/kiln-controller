#!/usr/bin/env python3

import board
import busio
import adafruit_mcp9600
import glob

class OvenMCP9600(object):
    '''adafruit mcp9600 thermocouple board
     Requires:
     - The [GPIO Library](https://code.google.com/p/raspberry-gpio-python/) (Already on most Raspberry Pi OS builds)
     - A [Raspberry Pi](http://www.raspberrypi.org/)

    '''
    def __init__(self, units = "c"):
        '''Initialize library

        Parameters:
        - units:     (optional) unit of measurement to return. ("c" (default) | "k" | "f")

        '''
        self.i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        self.mcp = adafruit_mcp9600.MCP9600(self.i2c)
        self.units = units
        self.tempC = None
        self.referenceTempC = None
        self.noConnection = self.shortToGround = self.shortToVCC = self.unknownError = False

    def get(self):
        '''Reads SPI bus and returns current value of thermocouple.'''
        self.read()
        self.checkErrors()
        return getattr(self, "to_" + self.units)(self.data_to_LinearizedTempC())

    def get_rj(self):
        '''Reads SPI bus and returns current value of reference junction.'''
        self.read()
        return getattr(self, "to_" + self.units)(self.data_to_rj_temperature())

    def read(self):
        '''Reads temperature from thermocouple and code junction'''
        try:
            # Save data
            self.tempC = self.mcp.temperature
            self.referenceTempC = self.mcp.ambient_temperature
            self.noConnection = False
        except:
            self.noConnection = True

    def checkErrors(self, data_32 = None):
        '''Checks error bits to see if there are any SCV, SCG, or OC faults'''
        self.shortToGround = self.shortToVCC = self.unknownError = False

    def data_to_rj_temperature(self, data_32 = None):
        '''Returns reference junction temperature in C.'''
        return self.referenceTempC

    def to_c(self, celsius):
        '''Celsius passthrough for generic to_* method.'''
        return celsius

    def to_k(self, celsius):
        '''Convert celsius to kelvin.'''
        return celsius + 273.15

    def to_f(self, celsius):
        '''Convert celsius to fahrenheit.'''
        return celsius * 9.0/5.0 + 32

    def cleanup(self):
        '''Selective GPIO cleanup'''
        print("In mcp9600.cleanup")

    def data_to_LinearizedTempC(self, data_32 = None):
        '''Returns hot junction temp'''
        return self.tempC

class MCP9600Error(Exception):
     def __init__(self, value):
         self.value = value
     def __str__(self):
         return repr(self.value)
