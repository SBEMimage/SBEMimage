# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2019 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module controls the downstream asher GV10x (ibss Group Inc., Burlingame,
   CA, USA) via a COM port.
"""

from time import sleep
import serial

class PlasmaCleaner():

    def __init__(self, selected_port):
        self.com_port = serial.Serial()
        self.com_port.port = selected_port
        self.com_port.baudrate = 9600
        self.com_port.bytesize = 8
        self.com_port.parity = 'N'
        self.com_port.stopbits = 1
        self.com_port.timeout = None
        self.connection_success = False
        try:
            self.com_port.open()
            self.connection_success = True
        except:
            self.connection_success = False

    def version(self):
        """Read version info from the device. Serves as a functional test."""
        CRLF = serial.to_bytes([13, 10])
        self.com_port.write(b'F' + CRLF)
        sleep(0.1)
        msg = self.com_port.readline().decode('utf-8')
        msg2 = self.com_port.readline().decode('utf-8')
        return (msg, msg2)

    def read_response(self):
        """Read a response from the device. Note that when setting parameters,
           the response of the device must be read, otherwise the command is
           not processed.
        """
        return self.com_port.readline().decode('utf-8')

    def get_power(self):
        """Read the current power setting (in W)."""
        CRLF = serial.to_bytes([13, 10])
        self.com_port.write(b'W' + CRLF)
        sleep(0.1)
        msg = self.com_port.readline().decode('utf-8')
        watts = int(msg[1]) * 10 + int(msg[2])
        return watts

    def set_power(self, target_power):
        """Set the power in watts."""
        CRLF = serial.to_bytes([13, 10])
        m = target_power // 10
        n = target_power % 10
        mn_str = str(m) + str(n)
        msg = b'W' + mn_str.encode('utf-8') + CRLF
        self.com_port.write(msg)
        sleep(0.5)
        self.read_response() # Must be read, otherwise command not processed.

    def get_duration(self):
        """Get current duration setting in minutes."""
        CRLF = serial.to_bytes([13, 10])
        self.com_port.write(b'M' + CRLF)
        sleep(0.1)
        msg = self.com_port.readline().decode('utf-8')
        minutes = int(msg[1]) * 10 + int(msg[2])
        return minutes

    def set_duration(self, target_duration):
        """Set duration in minutes."""
        CRLF = serial.to_bytes([13, 10])
        m = target_duration // 10
        n = target_duration % 10
        mn_str = str(m) + str(n)
        msg = b'M' + mn_str.encode('utf-8') + CRLF
        self.com_port.write(msg)
        sleep(0.5)
        self.read_response()

    def perform_cleaning(self):
        """Run a cleaning cycle with current parameters."""
        CRLF = serial.to_bytes([13, 10])
        self.com_port.write(b'P1' + CRLF)
        sleep(0.5)
        msg = self.com_port.readline()
        return str(msg)

    def abort_cleaning(self):
        CRLF = serial.to_bytes([13, 10])
        self.com_port.write(b'P0' + CRLF)
        sleep(0.5)
        msg = self.com_port.readline()
        return str(msg)

    def connection_established(self):
        return self.connection_success

    def close_port(self):
        if self.connection_success:
            self.com_port.close()
            return 'CTRL: ' + self.com_port.port + ' closed.'
