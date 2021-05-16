"""
max31856.py

Class which defines interaction with the MAX31856 sensor.

Copyright (c) 2019 John Robinson
Author: John Robinson

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
import logging
import warnings

import Adafruit_GPIO as Adafruit_GPIO
import Adafruit_GPIO.SPI as SPI


class MAX31856(object):
    """Class to represent an Adafruit MAX31856 thermocouple temperature
    measurement board.
    """

    # Board Specific Constants
    MAX31856_CONST_THERM_LSB = 2**-7
    MAX31856_CONST_THERM_BITS = 19
    MAX31856_CONST_CJ_LSB = 2**-6
    MAX31856_CONST_CJ_BITS = 14

    ### Register constants, see data sheet Table 6 (in Rev. 0) for info.
    # Read Addresses
    MAX31856_REG_READ_CR0 = 0x00
    MAX31856_REG_READ_CR1 = 0x01
    MAX31856_REG_READ_MASK = 0x02
    MAX31856_REG_READ_CJHF = 0x03
    MAX31856_REG_READ_CJLF = 0x04
    MAX31856_REG_READ_LTHFTH = 0x05
    MAX31856_REG_READ_LTHFTL = 0x06
    MAX31856_REG_READ_LTLFTH = 0x07
    MAX31856_REG_READ_LTLFTL = 0x08
    MAX31856_REG_READ_CJTO = 0x09
    MAX31856_REG_READ_CJTH = 0x0A  # Cold-Junction Temperature Register, MSB
    MAX31856_REG_READ_CJTL = 0x0B  # Cold-Junction Temperature Register, LSB
    MAX31856_REG_READ_LTCBH = 0x0C # Linearized TC Temperature, Byte 2
    MAX31856_REG_READ_LTCBM = 0x0D # Linearized TC Temperature, Byte 1
    MAX31856_REG_READ_LTCBL = 0x0E # Linearized TC Temperature, Byte 0
    MAX31856_REG_READ_FAULT = 0x0F # Fault status register

    # Write Addresses
    MAX31856_REG_WRITE_CR0 = 0x80
    MAX31856_REG_WRITE_CR1 = 0x81
    MAX31856_REG_WRITE_MASK = 0x82
    MAX31856_REG_WRITE_CJHF = 0x83
    MAX31856_REG_WRITE_CJLF = 0x84
    MAX31856_REG_WRITE_LTHFTH = 0x85
    MAX31856_REG_WRITE_LTHFTL = 0x86
    MAX31856_REG_WRITE_LTLFTH = 0x87
    MAX31856_REG_WRITE_LTLFTL = 0x88
    MAX31856_REG_WRITE_CJTO = 0x89
    MAX31856_REG_WRITE_CJTH = 0x8A  # Cold-Junction Temperature Register, MSB
    MAX31856_REG_WRITE_CJTL = 0x8B  # Cold-Junction Temperature Register, LSB

    # Pre-config Register Options
    MAX31856_CR0_READ_ONE = 0x40 # One shot reading, delay approx. 200ms then read temp registers
    MAX31856_CR0_READ_CONT = 0x80 # Continuous reading, delay approx. 100ms between readings

    # Thermocouple Types
    MAX31856_B_TYPE = 0x0 # Read B Type Thermocouple
    MAX31856_E_TYPE = 0x1 # Read E Type Thermocouple
    MAX31856_J_TYPE = 0x2 # Read J Type Thermocouple
    MAX31856_K_TYPE = 0x3 # Read K Type Thermocouple
    MAX31856_N_TYPE = 0x4 # Read N Type Thermocouple
    MAX31856_R_TYPE = 0x5 # Read R Type Thermocouple
    MAX31856_S_TYPE = 0x6 # Read S Type Thermocouple
    MAX31856_T_TYPE = 0x7 # Read T Type Thermocouple

    def __init__(self, tc_type=MAX31856_S_TYPE, units="c", avgsel=0x0, ac_freq_50hz=False, ocdetect=0x1, software_spi=None, hardware_spi=None, gpio=None):
        """
        Initialize MAX31856 device with software SPI on the specified CLK,
        CS, and DO pins.  Alternatively can specify hardware SPI by sending an
        SPI.SpiDev device in the spi parameter.

        Args:
            tc_type (1-byte Hex): Type of Thermocouple.  Choose from class variables of the form
                MAX31856.MAX31856_X_TYPE.
            avgsel (1-byte Hex): Type of Averaging.  Choose from values in CR0 table of datasheet.
                Default is single sample.
            ac_freq_50hz: Set to True if your AC frequency is 50Hz, Set to False for 60Hz,
            ocdetect: Detect open circuit errors (ie broken thermocouple). Choose from values in CR1 table of datasheet
            software_spi (dict): Contains the pin assignments for software SPI, as defined below:
                clk (integer): Pin number for software SPI clk
                cs (integer): Pin number for software SPI cs
                do (integer): Pin number for software SPI MISO
                di (integer): Pin number for software SPI MOSI
            hardware_spi (SPI.SpiDev): If using hardware SPI, define the connection
        """
        self._logger = logging.getLogger('Adafruit_MAX31856.MAX31856')
        self._spi = None
        self.tc_type = tc_type
        self.avgsel = avgsel
        self.units = units
        self.noConnection = self.shortToGround = self.shortToVCC = self.unknownError = False

        # Handle hardware SPI
        if hardware_spi is not None:
            self._logger.debug('Using hardware SPI')
            self._spi = hardware_spi
        elif software_spi is not None:
            self._logger.debug('Using software SPI')
            # Default to platform GPIO if not provided.
            if gpio is None:
                gpio = Adafruit_GPIO.get_platform_gpio()
            self._spi = SPI.BitBang(gpio, software_spi['clk'], software_spi['di'],
                                                  software_spi['do'], software_spi['cs'])
        else:
            raise ValueError(
                'Must specify either spi for for hardware SPI or clk, cs, and do for softwrare SPI!')
        self._spi.set_clock_hz(5000000)
        # According to Wikipedia (on SPI) and MAX31856 Datasheet:
        #   SPI mode 1 corresponds with correct timing, CPOL = 0, CPHA = 1
        self._spi.set_mode(1)
        self._spi.set_bit_order(SPI.MSBFIRST)

        self.cr0 = self.MAX31856_CR0_READ_CONT | ((ocdetect & 3) << 4) | (1 if ac_freq_50hz else 0)
        self.cr1 = (((self.avgsel & 7) << 4) + (self.tc_type & 0x0f))

        # Setup for reading continuously with T-Type thermocouple
        self._write_register(self.MAX31856_REG_WRITE_CR0, 0)
        self._write_register(self.MAX31856_REG_WRITE_CR1, self.cr1)
        self._write_register(self.MAX31856_REG_WRITE_CR0, self.cr0)

    @staticmethod
    def _cj_temp_from_bytes(msb, lsb):
        """
        Takes in the msb and lsb from a Cold Junction (CJ) temperature reading and converts it
        into a decimal value.

        This function was removed from readInternalTempC() and moved to its own method to allow for
            easier testing with standard values.

        Args:
            msb (hex): Most significant byte of CJ temperature
            lsb (hex): Least significant byte of a CJ temperature

        """
        #            (((msb w/o +/-) shifted by number of 1 byte above lsb)
        #                                  + val_low_byte)
        #                                          >> shifted back by # of dead bits
        temp_bytes = (((msb & 0x7F) << 8) + lsb) >> 2

        if msb & 0x80:
            # Negative Value.  Scale back by number of bits
            temp_bytes -= 2**(MAX31856.MAX31856_CONST_CJ_BITS -1)

        #        temp_bytes*value of lsb
        temp_c = temp_bytes*MAX31856.MAX31856_CONST_CJ_LSB

        return temp_c

    @staticmethod
    def _thermocouple_temp_from_bytes(byte0, byte1, byte2):
        """
        Converts the thermocouple byte values to a decimal value.

        This function was removed from readInternalTempC() and moved to its own method to allow for
            easier testing with standard values.

        Args:
            byte2 (hex): Most significant byte of thermocouple temperature
            byte1 (hex): Middle byte of thermocouple temperature
            byte0 (hex): Least significant byte of a thermocouple temperature

        Returns:
            temp_c (float): Temperature in degrees celsius
        """
        #            (((val_high_byte w/o +/-) shifted by 2 bytes above LSB)
        #                 + (val_mid_byte shifted by number 1 byte above LSB)
        #                                             + val_low_byte )
        #                              >> back shift by number of dead bits
        temp_bytes = (((byte2 & 0x7F) << 16) + (byte1 << 8) + byte0)
        temp_bytes = temp_bytes >> 5

        if byte2 & 0x80:
            temp_bytes -= 2**(MAX31856.MAX31856_CONST_THERM_BITS -1)

        #        temp_bytes*value of LSB
        temp_c = temp_bytes*MAX31856.MAX31856_CONST_THERM_LSB

        return temp_c

    def read_internal_temp_c(self):
        """
        Return internal temperature value in degrees celsius.
        """
        val_low_byte = self._read_register(self.MAX31856_REG_READ_CJTL)
        val_high_byte = self._read_register(self.MAX31856_REG_READ_CJTH)

        temp_c = MAX31856._cj_temp_from_bytes(val_high_byte, val_low_byte)
        self._logger.debug("Cold Junction Temperature {0} deg. C".format(temp_c))

        return temp_c

    def read_temp_c(self):
        """
        Return the thermocouple temperature value in degrees celsius.
        """
        val_low_byte = self._read_register(self.MAX31856_REG_READ_LTCBL)
        val_mid_byte = self._read_register(self.MAX31856_REG_READ_LTCBM)
        val_high_byte = self._read_register(self.MAX31856_REG_READ_LTCBH)

        temp_c = MAX31856._thermocouple_temp_from_bytes(val_low_byte, val_mid_byte, val_high_byte)

        self._logger.debug("Thermocouple Temperature {0} deg. C".format(temp_c))

        return temp_c

    def read_fault_register(self):
        """Return bytes containing fault codes and hardware problems.

        TODO: Could update in the future to return human readable values
        """
        reg = self._read_register(self.MAX31856_REG_READ_FAULT)
        return reg

    def _read_register(self, address):
        """
        Reads a register at address from the MAX31856

        Args:
            address (8-bit Hex): Address for read register.  Format 0Xh. Constants listed in class
                as MAX31856_REG_READ_*

        Note:
            SPI transfer method is used.  The address is written in as the first byte, and then a
            dummy value as the second byte. The data from the sensor is contained in the second
            byte, the dummy byte is only used to keep the SPI clock ticking as we read in the
            value.  The first returned byte is discarded because no data is transmitted while
            specifying the register address.
        """
        raw = self._spi.transfer([address, 0x00])
        if raw is None or len(raw) != 2:
            raise RuntimeError('Did not read expected number of bytes from device!')

        value = raw[1]
        self._logger.debug('Read Register: 0x{0:02X}, Raw Value: 0x{1:02X}'.format(
            (address & 0xFFFF), (value & 0xFFFF)))
        return value

    def _write_register(self, address, write_value):
        """
        Writes to a register at address from the MAX31856

        Args:
            address (8-bit Hex): Address for read register.  Format 0Xh. Constants listed in class
                as MAX31856_REG_WRITE_*
            write_value (8-bit Hex): Value to write to the register
        """
        self._spi.transfer([address, write_value])
        self._logger.debug('Wrote Register: 0x{0:02X}, Value 0x{1:02X}'.format((address & 0xFF),
                                                                            (write_value & 0xFF)))

        # If we've gotten this far without an exception, the transmission must've gone through
        return True

    # Deprecated Methods
    def readTempC(self):    #pylint: disable-msg=invalid-name
        """Depreciated due to Python naming convention, use read_temp_c instead
        """
        warnings.warn("Depreciated due to Python naming convention, use read_temp_c() instead", DeprecationWarning)
        return read_temp_c(self)

    def readInternalTempC(self):    #pylint: disable-msg=invalid-name
        """Depreciated due to Python naming convention, use read_internal_temp_c instead
        """
        warnings.warn("Depreciated due to Python naming convention, use read_internal_temp_c() instead", DeprecationWarning)
        return read_internal_temp_c(self)

    # added by jbruce to mimic MAX31855 lib
    def to_c(self, celsius):
        '''Celsius passthrough for generic to_* method.'''
        return celsius

    def to_k(self, celsius):
        '''Convert celsius to kelvin.'''
        return celsius + 273.15

    def to_f(self, celsius):
        '''Convert celsius to fahrenheit.'''
        return celsius * 9.0/5.0 + 32

    def checkErrors(self):
        data = self.read_fault_register()
        self.noConnection = (data & 0x00000001) != 0
        self.unknownError = (data & 0xfe) != 0

    def get(self):
        self.checkErrors()
        celcius = self.read_temp_c()
        return getattr(self, "to_" + self.units)(celcius)


if __name__ == "__main__":

    # Multi-chip example
    import time
    cs_pins = [6]
    clock_pin = 13
    data_pin = 5
    di_pin = 26
    units = "c"
    thermocouples = []
    for cs_pin in cs_pins:
        thermocouples.append(MAX31856(avgsel=0, ac_freq_50hz=True, tc_type=MAX31856.MAX31856_K_TYPE, software_spi={'clk': clock_pin, 'cs': cs_pin, 'do': data_pin, 'di': di_pin}, units=units))

    running = True
    while(running):
        try:
            for thermocouple in thermocouples:
                rj = thermocouple.read_internal_temp_c()
                tc = thermocouple.get()
                print("tc: {} and rj: {}, NC:{} ??:{}".format(tc, rj, thermocouple.noConnection, thermocouple.unknownError))
            time.sleep(1)
        except KeyboardInterrupt:
            running = False
    for thermocouple in thermocouples:
        thermocouple.cleanup()
