# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module controls the microtome hardware (knife and motorized stage) via
   DigitalMicrograph (3View) or a serial port (katana).

                Microtome (base class)
                  /                \
                 /                  \
         Microtome_3View     Microtome_katana
"""

import os
import json
import serial

from time import sleep

import utils


class Microtome:
    """Base class for microtome control. It implements minimum config/parameter
    handling. Undefined methods have to be implemented in the child class,
    otherwise NotImplementedError is raised.
    """
    def __init__(self, config, sysconfig):
        self.cfg = config
        self.syscfg = sysconfig
        self.error_state = 0
        self.error_info = ''
        self.motor_warning = False  # True when motors slower than expected
        # Load device name and other settings from sysconfig. These
        # settings overwrite the settings in config.
        recognized_devices = json.loads(self.syscfg['device']['recognized'])
        try:
            self.cfg['microtome']['device'] = (
                recognized_devices[int(self.syscfg['device']['microtome'])])
        except:
            self.cfg['microtome']['device'] = 'NOT RECOGNIZED'
        self.device_name = self.cfg['microtome']['device']
        # Get microtome stage limits from systemcfg
        # self.stage_limits: [min_x, max_x, min_y, max_y] in micrometres
        self.stage_limits = json.loads(
            self.syscfg['stage']['microtome_stage_limits'])
        # Get microtome motor speeds from syscfg
        self.motor_speed_x, self.motor_speed_y = (
            json.loads(self.syscfg['stage']['microtome_motor_speed']))
        # Knife settings in system config override the user config settings.
        self.cfg['microtome']['full_cut_duration'] = (
            self.syscfg['knife']['full_cut_duration'])
        self.cfg['microtome']['sweep_distance'] = (
            self.syscfg['knife']['sweep_distance'])
        # The following variables contain the last known (verified) position
        # of the microtome stage in X, Y, Z.
        self.last_known_x = None
        self.last_known_y = None
        self.last_known_z = None
        # self.prev_known_z stores the previous Z coordinate. It is used to
        # ensure that Z moves cannot be larger than 200 nm in safe mode.
        self.prev_known_z = None
        # self.stage_z_prev_session stores the last known Z coordinate at the end of
        # the previous session associated with the current user configuration.
        if self.cfg['microtome']['last_known_z'].lower() == 'none':
            self.stage_z_prev_session = None
        else:
            try:
                self.stage_z_prev_session = float(
                    self.cfg['microtome']['last_known_z'])
            except Exception as e:
                self.error_state = 701
                self.error_info = str(e)
                return
        try:
            self.z_range = json.loads(
                self.syscfg['stage']['microtome_z_range'])
        except Exception as e:
            self.error_state = 701
            self.error_info = str(e)
            return
        self.simulation_mode = (
            self.cfg['sys']['simulation_mode'].lower() == 'true')
        self.use_oscillation = (
            self.cfg['microtome']['knife_oscillation'].lower() == 'true')

        # Catch errors that occur while reading configuration and converting
        # the string values into floats or integers
        try:
            # Knife cut speed in nm/s
            self.knife_cut_speed = int(float(
                self.cfg['microtome']['knife_cut_speed']))
            # Knife cut speed for fast cutting, typically for approach, nm/s
            self.knife_fast_speed = int(float(
                self.cfg['microtome']['knife_fast_speed']))
            # Knife retract speed in nm/s
            self.knife_retract_speed = int(float(
                self.cfg['microtome']['knife_retract_speed']))
            # Start and end position of cutting window, in nm
            self.cut_window_start = int(float(
                self.cfg['microtome']['knife_cut_start']))
            self.cut_window_end = int(float(
                self.cfg['microtome']['knife_cut_end']))
            # Knife oscillation frequency in Hz
            self.oscillation_frequency = int(float(
                self.cfg['microtome']['knife_osc_frequency']))
            # Knife oscillation amplitude in nm
            self.oscillation_amplitude = int(float(
                self.cfg['microtome']['knife_osc_amplitude']))
            # Duration of a full cut cycle in seconds
            self.full_cut_duration = float(
                self.cfg['microtome']['full_cut_duration'])
            # Sweep distance (lowering of Z position in nm before sweep)
            self.sweep_distance = int(float(
                self.cfg['microtome']['sweep_distance']))
            if (self.sweep_distance < 30) or (self.sweep_distance > 1000):
                # If outside permitted range, set to 70 nm as default
                self.sweep_distance = 70
                self.cfg['microtome']['sweep_distance'] = '70'
            # self.stage_move_wait_interval is the amount of time in seconds
            # that SBEMimage waits after a stage move before taking an image.
            self.stage_move_wait_interval = float(
                self.cfg['microtome']['stage_move_wait_interval'])

        except Exception as e:
            self.error_state = 701
            self.error_info = str(e)

    def save_to_cfg(self):
        self.cfg['microtome']['stage_move_wait_interval'] = str(
            self.stage_move_wait_interval)
        # Save stage limits in cfg and syscfg
        self.cfg['microtome']['stage_min_x'] = str(self.stage_limits[0])
        self.cfg['microtome']['stage_max_x'] = str(self.stage_limits[1])
        self.cfg['microtome']['stage_min_y'] = str(self.stage_limits[2])
        self.cfg['microtome']['stage_max_y'] = str(self.stage_limits[3])
        self.syscfg['stage']['microtome_stage_limits'] = str(self.stage_limits)
        # Save motor speeds to cfg and syscfg
        self.cfg['microtome']['motor_speed_x'] = str(self.motor_speed_x)
        self.cfg['microtome']['motor_speed_y'] = str(self.motor_speed_y)
        self.syscfg['stage']['microtome_motor_speed'] = str(
            [self.motor_speed_x, self.motor_speed_y])
        self.cfg['microtome']['knife_cut_speed'] = str(int(
            self.knife_cut_speed))
        self.cfg['microtome']['knife_retract_speed'] = str(int(
            self.knife_retract_speed))
        self.cfg['microtome']['knife_fast_speed'] = str(int(
            self.knife_fast_speed))
        self.cfg['microtome']['knife_cut_start'] = str(int(
            self.cut_window_start))
        self.cfg['microtome']['knife_cut_end'] = str(int(
            self.cut_window_end))
        self.cfg['microtome']['knife_oscillation'] = str(self.use_oscillation)
        self.cfg['microtome']['knife_osc_frequency'] = str(int(
            self.oscillation_frequency))
        self.cfg['microtome']['knife_osc_amplitude'] = str(int(
            self.oscillation_amplitude))
        self.cfg['microtome']['last_known_z'] = str(self.last_known_z)
        # Save full cut duration in both cfg and syscfg
        self.cfg['microtome']['full_cut_duration'] = str(self.full_cut_duration)
        self.syscfg['knife']['full_cut_duration'] = str(self.full_cut_duration)

    def do_full_cut(self):
        """Perform a full cut cycle. This is the only knife control function
           used during stack acquisitions.
        """
        raise NotImplementedError

    def do_full_approach_cut(self):
        """Perform a full cut cycle under the assumption that knife is
           already neared."""
        raise NotImplementedError

    def do_sweep(self, z_position):
        """Perform a sweep by cutting slightly above the surface."""
        if (((self.sweep_distance < 30) or (self.sweep_distance > 1000))
                and self.error_state == 0):
            self.error_state = 205
            self.error_info = 'microtome.do_sweep: sweep distance out of range'
        elif self.error_state == 0:
            raise NotImplementedError

    def cut(self):
        # only used for testing
        raise NotImplementedError

    def retract_knife(self):
        # only used for testing
        raise NotImplementedError

    def set_motor_speeds(self, motor_speed_x, motor_speed_y):
        self.motor_speed_x = motor_speed_x
        self.motor_speed_y = motor_speed_y
        return self.write_motor_speeds_to_script()

    def write_motor_speeds_to_script(self):
        raise NotImplementedError

    def move_stage_to_x(self, x):
        # only used for testing
        raise NotImplementedError

    def move_stage_to_y(self, y):
        # only used for testing
        raise NotImplementedError

    def rel_stage_move_duration(self, target_x, target_y):
        """Use the last known position and the given target position
           to calculate how much time it will take for the motors to move
           to target position. Add self.stage_move_wait_interval.
        """
        duration_x = abs(target_x - self.last_known_x) / self.motor_speed_x
        duration_y = abs(target_y - self.last_known_y) / self.motor_speed_y
        return max(duration_x, duration_y) + self.stage_move_wait_interval

    def stage_move_duration(self, from_x, from_y, to_x, to_y):
        duration_x = abs(to_x - from_x) / self.motor_speed_x
        duration_y = abs(to_y - from_y) / self.motor_speed_y
        return max(duration_x, duration_y) + self.stage_move_wait_interval

    def get_stage_xy(self, wait_interval=0.25):
        """Get current XY coordinates from DM"""
        raise NotImplementedError

    def get_stage_x(self):
        return self.get_stage_xy()[0]

    def get_stage_y(self):
        return self.get_stage_xy()[1]

    def get_stage_xyz(self):
        x, y = self.get_stage_xy()
        z = self.get_stage_z()
        return x, y, z

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates X/Y. This function is called during
           acquisitions. It includes waiting times. The other move functions
           below do not.
        """
        raise NotImplementedError

    def get_stage_z(self, wait_interval=0.5):
        """Get current Z coordinate from DM"""
        raise NotImplementedError

    def move_stage_to_z(self, z, safe_mode=True):
        """Move stage to new z position. Used during stack acquisition
           before each cut and for sweeps."""
        raise NotImplementedError

    def stop_script(self):
        raise NotImplementedError

    def near_knife(self):
        raise NotImplementedError

    def clear_knife(self):
        raise NotImplementedError

    def check_for_cut_cycle_error(self):
        raise NotImplementedError

    def reset_error_state(self):
        raise NotImplementedError


class Microtome_3View(Microtome):
    """
    This class contains the methods to control a 3View microtome via
    DigitalMicrograph (DM).
    The DM script SBEMimage_DMcom_GMS2.s (or SBEMimage_DMcom_GMS3.s for GMS3)
    must be running in DM to receive commands from SBEMimage and transmit them
    to the 3View hardware (XY stage and knife arm).
    Communication with DM is achieved by read/write file operations.
    The following files are used:
      DMcom.trg:  Trigger file
                  Its existence signals that a command is waiting to be read.
      DMcom.in:   Command/parameter file
                  Contains a command and (optional) up to two parameters
      DMcom.out:  Contains output/return value(s)
      DMcom.ack:  Confirms that a command has been received and processed.
      DMcom.ac2:  Confirms that a full cut cycle has been completed.
      DMcom.wng:  Signals a warning (= error that could be resolved).
      DMcom.err:  Signals that a critical error occured.

    The 3View knife parameters (knife speeds, osciallation on/off) cannot be
    changed remotely via SBEMimage; they must be set in DM before the
    acquisition starts. The pre-acquisition dialog box asks the user
    to ensure these settings match the DM settings (for logging purposes).
    """

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        # Paths to DM communication files
        self.TRIGGER_FILE = os.path.join('..', 'dm', 'DMcom.trg')
        self.INPUT_FILE = os.path.join('..', 'dm', 'DMcom.in')
        self.OUTPUT_FILE = os.path.join('..', 'dm', 'DMcom.out')
        self.ACK_FILE = os.path.join('..', 'dm', 'DMcom.ack')
        self.ACK_CUT_FILE = os.path.join('..', 'dm', 'DMcom.ac2')
        self.WARNING_FILE = os.path.join('..', 'dm', 'DMcom.wng')
        self.ERROR_FILE = os.path.join('..', 'dm', 'DMcom.err')

        # Perform handshake and read initial X/Y/Z
        if not self.simulation_mode and self.error_state == 0:
            self._send_dm_command('Handshake')
            # DM script should react to trigger file by reading command file
            # usually within 0.1 s (default check interval)
            sleep(1)  # Give DM plenty of time to write response into file
            if self._dm_handshake_success():
                # Get initial X/Y/Z with long wait intervals (1s) for responses
                current_z = self.get_stage_z(wait_interval=1)
                current_x, current_y = self.get_stage_xy(wait_interval=1)
                if ((current_x is None) or (current_y is None)
                        or (current_z is None)):
                    self.error_state = 101
                    self.error_info = ('microtome.__init__: could not read '
                                       'initial stage position')
                elif current_z < 0:
                    self.error_state = 101
                    self.error_info = ('microtome.__init__: stage z position '
                                       'must not be negative.')
                # Check if current Z coordinate matches last known Z from
                # previous session
                elif (self.stage_z_prev_session is not None
                      and abs(current_z - self.stage_z_prev_session) > 0.01):
                    self.error_state = 206
                    self.error_info = ('microtome.__init__: stage z position '
                                       'mismatch')
                # Update motor speeds in DM script
                success = self.write_motor_speeds_to_script()
                # If update unsuccesful, set new error state unless microtome
                # is already in an error state after reading the coordinates.
                if not success and self.error_state == 0:
                    self.error_state = 101
                    self.error_info = ('microtome.__init__: could not send '
                                       'current motor speeds to DM')
            else:
                self.error_state = 101
                self.error_info = 'microtome.__init__: handshake failed'

    def _send_dm_command(self, cmd, set_values=[]):
        """Send a command to the DigitalMicrograph script."""
        # First, if output file exists, delete it to ensure old values are gone
        if os.path.isfile(self.OUTPUT_FILE):
            os.remove(self.OUTPUT_FILE)
        # Try to open command file
        success, cmd_file = utils.try_to_open(self.INPUT_FILE, 'w+')
        if success:
            cmd_file.write(cmd)
            for item in set_values:
                cmd_file.write('\n' + str(item))
            cmd_file.close()
            # Create new trigger file
            success, trg_file = utils.try_to_open(self.TRIGGER_FILE, 'w+')
            if success:
                trg_file.close()
            elif self.error_state == 0:
                self.error_state = 102
                self.error_info = ('microtome._send_dm_command: could not '
                                   'create trigger file')
        elif self.error_state == 0:
            self.error_state = 102
            self.error_info = ('microtome._send_dm_command: could not write '
                               'to command file')

    def _read_dm_return_values(self):
        """Try to read return file and, if successful, return values."""
        return_values = []
        success, return_file = utils.try_to_open(self.OUTPUT_FILE, 'r')
        if success:
            for line in return_file:
                return_values.append(line.rstrip())
            return_file.close()
        elif self.error_state == 0:
            self.error_state = 104
            self.error_info = ('microtome._read_dm_return_values: could not '
                               'read from output file')
        if return_values == []:
            return_values = [None, None]
        return return_values

    def _dm_handshake_success(self):
        """Verify that handshake command has worked."""
        read_success = True
        return_value = None
        try:
            file_handle = open(self.OUTPUT_FILE, 'r')
        except:
            # Try once more
            sleep(1)
            try:
                file_handle = open(self.OUTPUT_FILE, 'r')
            except:
                read_success = False
        if read_success:
            return_value = file_handle.readline().rstrip()
            file_handle.close()
            if return_value == 'OK':
                return True
        else:
            # Error state assigned in self.__init__()
            return False

    def do_full_cut(self):
        """Perform a full cut cycle. This is the only knife control function
        used during a stack acquisitions.
        """
        self._send_dm_command('MicrotomeStage_FullCut')
        sleep(0.2)

    def do_full_approach_cut(self):
        """Perform a full cut cycle under the assumption that the knife is
        already neared. This function is called repeatedly from the approach
        dialog (ApproachDlg) after the knife has been neared.
        """
        self._send_dm_command('MicrotomeStage_FullApproachCut')
        sleep(0.2)

    def do_sweep(self, z_position):
        """Perform a sweep by cutting slightly above the surface."""
        if (((self.sweep_distance < 30) or (self.sweep_distance > 1000))
                and self.error_state == 0):
            self.error_state = 205
            self.error_info = 'microtome.do_sweep: sweep distance out of range'
        elif self.error_state == 0:
            # Move to new z position
            sweep_z_position = z_position - (self.sweep_distance / 1000)
            self.move_stage_to_z(sweep_z_position)
            if self.error_state > 0:
                # Try again
                self.reset_error_state()
                sleep(2)
                self.move_stage_to_z(sweep_z_position)
            if self.error_state == 0:
                # Do a cut cycle above the sample surface to clear away debris
                self.do_full_cut()
                sleep(self.full_cut_duration)
                # Check if error occurred during cut cycle.
                if os.path.isfile(self.ERROR_FILE):
                    self.error_state = 205
                    self.error_info = ('microtome.do_sweep: error during '
                                       'cutting cycle')
                elif not os.path.isfile(self.ACK_CUT_FILE):
                    # Cut cycle was not carried out
                    self.error_state = 103
                    self.error_info = ('microtome.do_sweep: command not '
                                       'processed by DM script')

            # Move to previous z position (before sweep)
            self.move_stage_to_z(z_position)
            if self.error_state > 0:
                # Try again
                sleep(2)
                self.reset_error_state()
                self.move_stage_to_z(z_position)

    def cut(self):
        # only used for testing
        self._send_dm_command('MicrotomeStage_Cut')
        sleep(1.2/self.knife_cut_speed)

    def retract_knife(self):
        # only used for testing
        self._send_dm_command('MicrotomeStage_Retract')
        sleep(1.2/self.knife_retract_speed)

    def write_motor_speeds_to_script(self):
        self._send_dm_command('SetMotorSpeedCalibrationXY',
                              [self.motor_speed_x, self.motor_speed_y])
        sleep(1)
        # Check if command was processed by DM
        if os.path.isfile(self.ACK_FILE):
            success = True
        else:
            sleep(2)
            success = os.path.isfile(self.ACK_FILE)
        return success

    def move_stage_to_x(self, x):
        # only used for testing
        self._send_dm_command('MicrotomeStage_SetPositionX', [x])
        sleep(0.5)
        self.get_stage_xy()

    def move_stage_to_y(self, y):
        # only used for testing
        self._send_dm_command('MicrotomeStage_SetPositionY', [y])
        sleep(0.5)
        self.get_stage_xy()

    def get_stage_xy(self, wait_interval=0.25):
        """Get current XY coordinates from DM."""
        success = True
        self._send_dm_command('MicrotomeStage_GetPositionXY')
        sleep(wait_interval)
        answer = self._read_dm_return_values()
        try:
            x, y = float(answer[0]), float(answer[1])
        except:
            x, y = None, None
            success = False
        if success:
            self.last_known_x, self.last_known_y = x, y
        return x, y

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates (X, Y). This function is called during
        acquisitions. It includes waiting times. The other move functions
        below do not.
        """
        x, y = coordinates
        self._send_dm_command('MicrotomeStage_SetPositionXY_Confirm', [x, y])
        sleep(0.2)
        # Wait for the time it takes the motors to move
        move_duration = self.rel_stage_move_duration(x, y)
        sleep(move_duration + 0.1)
        # Check if the command was processed successfully
        if os.path.isfile(self.ACK_FILE):
            self.last_known_x, self.last_known_y = x, y
            # Check if there was a warning
            if os.path.isfile(self.WARNING_FILE):
                # There was a warning from the script - motors may have
                # moved too slowly
                self.motor_warning = True
        elif os.path.isfile(self.ERROR_FILE) and self.error_state == 0:
            # Error: Motors did not reach the target position
            self.error_state = 201
            self.error_info = ('microtome.move_stage_to_xy: did not reach '
                               'target xy position')
        elif self.error_state == 0:
            # If neither .ack nor .err exist, the command was not processed
            self.error_state = 103
            self.error_info = ('microtome.move_stage_to_xy: command not '
                               'processed by DM script')

    def get_stage_z(self, wait_interval=0.5):
        """Get current Z coordinate from DM."""
        success = True
        self._send_dm_command('MicrotomeStage_GetPositionZ')
        sleep(wait_interval)
        answer = self._read_dm_return_values()
        try:
            z = float(answer[0])
        except:
            z = None
            success = False
        if success:
            if (self.last_known_z is not None
                and abs(z - self.last_known_z) > 0.01):
                self.error_state = 206
            self.prev_known_z = self.last_known_z
            self.last_known_z = z
        return z

    def move_stage_to_z(self, z, safe_mode=True):
        """Move stage to new z position. Used during stack acquisitions
        before each cut and for sweeps.
        """
        if (((self.last_known_z >= 0) and (abs(z - self.last_known_z) > 0.205))
                and self.error_state == 0 and safe_mode):
            # Z must not change more than ~200 nm during stack acquisitions!
            self.error_state = 203
            self.error_info = ('microtome.move_stage_to_z: Z move too '
                               'large (> 200 nm)')
        else:
            self._send_dm_command('MicrotomeStage_SetPositionZ_Confirm', [z])
            sleep(1)  # wait for command to be read and executed
            # Check if command was processed
            if os.path.isfile(self.ACK_FILE):
                # Accept new position as last known position
                self.prev_known_z = self.last_known_z
                self.last_known_z = z
            elif os.path.isfile(self.ERROR_FILE) and self.error_state == 0:
                # There was an error during the move
                self.error_state = 202
                self.error_info = ('microtome.move_stage_to_z: did not reach '
                                   'target z position')
            elif self.error_state == 0:
                # If neither .ack nor .err exist, the command was not processed
                self.error_state = 103
                self.error_info = ('move_stage_to_z: command not processed '
                                   'by DM script')

    def stop_script(self):
        self._send_dm_command('Stop')
        sleep(0.2)

    def near_knife(self):
        # only used for testing
        self._send_dm_command('MicrotomeStage_Near')
        sleep(4)

    def clear_knife(self):
        # only used for testing
        self._send_dm_command('MicrotomeStage_Clear')
        sleep(4)

    def check_for_cut_cycle_error(self):
        duration_exceeded = False
        # Check if error ocurred during self.do_full_cut()
        if self.error_state == 0 and os.path.isfile(self.ERROR_FILE):
            self.error_state = 204
            self.error_info = ('microtome.do_full_cut: error during '
                               'cutting cycle')
        elif not os.path.isfile(self.ACK_CUT_FILE):
            # Cut cycle was not carried out within the specified time limit
            self.error_state = 103
            self.error_info = ('microtome.do_full_cut: command not '
                               'processed by DM script')
            duration_exceeded = True
            # Wait for another 10 sec maximum
            for i in range(10):
                sleep(1)
                if os.path.isfile(self.ACK_CUT_FILE):
                    self.error_state = 0
                    self.error_info = ''
                    break
        return duration_exceeded

    def reset_error_state(self):
        self.error_state = 0
        self.error_info = ''
        self.motor_warning = False
        if os.path.isfile(self.ERROR_FILE):
            os.remove(self.ERROR_FILE)
        if os.path.isfile(self.WARNING_FILE):
            os.remove(self.WARNING_FILE)


class Microtome_katana(Microtome):
    """
    Class for ConnectomX katana microtome. This microtome provides cutting
    functionality and controls the Z position. X and Y are controlled by the
    SEM stage. The microtome hardware is controlled via COM port commands.
    """

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        self.selected_port = sysconfig['device']['katana_com_port']
        self.clear_position = int(sysconfig['knife']['katana_clear_position'])
        self.retract_clearance = int(
            sysconfig['stage']['katana_retract_clearance'])
        # Realtime parameters
        self.encoder_position = None
        self.knife_position = None
        self.current_osc_freq = None
        self.current_osc_amp = None
        # Connection status:
        self.connected = False
        # Try to connect with current selected port
        self.connect()
        if self.connected:
            # wait after opening port for arduino to initialise (won't be
            # necessary in future when using extra usb-serial chip)
            sleep(1)
            # initial comm is lost when on arduino usb port. (ditto)
            self._send_command(' ')
            # clear any incoming data from the serial buffer (probably
            # not necessary here)
            self.com_port.flushInput()
            # need to delay after opening port before sending anything.
            # 0.2s fails. 0.25s seems to be always OK. Suggest >0.3s for
            # reliability.
            sleep(0.3)
            # if this software is the first to interact with the hardware
            # after power-on, then the motor parameters need to be set
            # (no harm to do anyway)
            self.initialise_motor()
            # get the initial Z position from the encoder
            self.last_known_z = self.get_stage_z()
            print('Starting Z position: ' + str(self.last_known_z) + 'µm')

    def save_to_cfg(self):
        super().save_to_cfg()
        # Save kantana-specific keys sysconfig
        self.sysconfig['device']['katana_com_port'] = self.selected_port
        self.sysconfig['knife']['katana_clear_position'] = int(
            self.clear_position)
        self.sysconfig['stage']['katana_retract_clearance'] = int(
            self.retract_clearance)

    def connect(self):
        # Open COM port
        if not self.simulation_mode:
            self.com_port = serial.Serial()
            self.com_port.port = self.selected_port
            self.com_port.baudrate = 115200
            self.com_port.bytesize = 8
            self.com_port.parity = 'N'
            self.com_port.stopbits = 1
            # With no timeout, this code freezes if it doesn't get a response.
            self.com_port.timeout = 0.5
            try:
                self.com_port.open()
                self.connected = True
                # print('Connection to katana successful.')
            except Exception as e:
                print('Connection to katana failed: ' + repr(e))

    def initialise_motor(self):
         self._send_command('XM2')
         self._send_command('XY13,1')
         self._send_command('XY11,300')
         self._send_command('XY3,-3000000')
         self._send_command('XY4,3000000')
         self._send_command('XY2,0')
         self._send_command('XY6,1')
         self._send_command('XY12,0')

    def _send_command(self, cmd):
        """Send command to katana via serial port."""
        self.com_port.write((cmd + '\r').encode())
        # always need some delay after sending command.
        # suggest to keep 0.05 for now
        sleep(0.05)

    def _read_response(self):
        """Read a response from katana via the serial port."""
        return self.com_port.readline(13).decode()
        # Katana returns CR character at end of line (this is how our motor
        # controller works so it is easiest to keep it this way)

    def _wait_until_knife_stopped(self):
        print('waiting for knife to stop...')
        # initial delay to make sure we don't check before knife has
        # started moving!
        sleep(0.25)
        # knifeStatus = self._read_response()
        self.com_port.flushInput()
        while True:
            self._send_command('KKP')   # KKP queries knife movement status
            # reset it here just in case no response on next line
            knife_status = 'KKP:1'
            knife_status = self._read_response()
            knife_status = knife_status.rstrip();
            # print(" knife status: " + knifeStatus)

            # optional to show knife position so user knows it hasn't frozen!
            # _read_realtime_data is not as robust as other com port reads, and
            # there is no error check, so it should only be used for display
            # purposes. (it is very fast though, so you can use it in a loop
            # to update the GUI)
            self._read_realtime_data()
            print("Knife status: "
                  + knife_status
                  + ", \tKnife pos: "
                  + str(self.knife_position)
                  + "µm")

            if knife_status == 'KKP:0':    # If knife is not moving
                # print('Knife stationary')
                return 0
            # re-check every 0.2s. Repeated queries like this shouldnt be more
            # often than every 0.025s (risks overflowing the microtome
            # serial buffer)
            sleep(0.2)

    def _bytes_to_num(self, val_str, start, end):
        val = 0
        for i in range (start, end + 1):
            val += val_str[i] * (2**(8 * (i - start)))
        return(val)

    def _read_realtime_data(self):
        # _read_realtime_data gets the data as bytes rather than ascii. It is
        # not as robust as other com port reads, and there is no error check,
        # so it should only be used for display purposes. (it is very fast #
        # though, so you can use it in a loop to update the GUI)
        self.com_port.flushInput()
        self._send_command('KRT')
        datalength = 10
        c = self.com_port.read(datalength)
        # Can't get arduino to send negative number in binary. Temporary
        # solution is to add large number before sending and then subtract
        # it here
        self.encoder_position = self._bytes_to_num(c, 0, 3) - 10000000
        # nice to see where the knife is whilst we wait for a slow movement:
        self.knife_position = self._bytes_to_num(c, 4, 5)
        # the following gets retrieved because (when I get around to
        # implementing it) the knife will have a 'resonance mode' option. So
        # the frequency will shift to keep the knife at max amplitude
        self.current_osc_freq = self._bytes_to_num(c, 6, 7)
        # measured amplitude in nm. (Arduino scales it by 100)
        self.current_osc_amp = self._bytes_to_num(c, 8, 9) / 100
        # print(str(katana.encoderPos)+" \t"+str(katana.knifepos)
        #       +" \t"+str(katana.oscfreq)+" \t"+str(katana.oscAmp))

    def _reached_target(self):
         """Check to see if the z motor is still moving (returns 1 if target
         reached, otherwise 0 if still moving."""
         self.com_port.flushInput()
         self._send_command('XY23')
         # XY23 passes through to the motor controller.
         sleep(0.03)
         response = self._read_response()
         if response.startswith('XY23'):
             response = response.rstrip()
             response = response.replace('XY23:', '')
             status = response.split(',')
             # print(status[1])
             return int(status[1])
         else:
             return 0

    def do_full_cut(self):
        """Perform a full cut cycle."""
        # Move to cutting window
        # (good practice to check the knife is not moving before starting)
        self._wait_until_knife_stopped()
        print('Moving to cutting position '
              + str(self.cut_window_start) + ' ...')
        self._send_command('KMS' + str(self.knife_fast_speed))
        # send required speed. The reason I'm setting it every time before
        # moving is that I'm using two different speeds
        # (knifeFastSpeed & knifeCutSpeed)
        self._send_command('KKM' + str(self.cut_window_start))   # send required position

        # Turn oscillator on
        self._wait_until_knife_stopped()
        if self.is_oscillation_enabled():
            # turn oscillator on
            self._send_command('KO' + str(self.oscillation_frequency))
            self._send_command('KOA' + str(self.oscillation_amplitude))

        # Cut sample
        print('Cutting sample...')
        self._send_command('KMS' + str(self.knife_cut_speed))
        self._send_command('KKM' + str(self.cut_window_end))

        # Turn oscillator off
        self._wait_until_knife_stopped()
        if self.is_oscillation_enabled():
            self._send_command('KOA0')

        # Drop sample
        print('Dropping sample by ' + str(self.retract_clearance/1000) + 'µm...')
        # TODO: discuss how Z is handled:
        # drop sample before knife retract
        self.move_stage_to_z(
            desiredzPos - self.retract_clearance, 100)

        # Retract knife
        print('Retracting knife...')
        self._send_command('KMS' + str(self.knife_fast_speed))
        self._send_command('KKM' + str(self.clear_position))

        # Raise sample to cutting plane
        self._wait_until_knife_stopped()
        print('Returning sample to cutting plane...')
        self.move_stage_to_z(desiredzPos, 100)

    def do_full_approach_cut(self):
        """Perform a full cut cycle under the assumption that knife is
           already neared."""
        pass

    def do_sweep(self, z_position):
        """Perform a sweep by cutting slightly above the surface."""
        pass

    def cut(self):
        # only used for testing
        pass

    def retract_knife(self):
        # only used for testing
        pass

    def get_stage_z(self, wait_interval=0.5):
        """Get current Z position"""
        self.com_port.flushInput()
        self._send_command('KE')
        response = self._read_response()
        # response will look like 'KE:120000' (for position of 0.12mm)
        response = response.rstrip();
        response = response.replace('KE:', '')
        z = int(response)
        return z

    def get_stage_z_prev_session(self):
        return self.stage_z_prev_session

    def move_stage_to_z(self, z, speed, safe_mode=True):
        """Move to specified Z position, and block until it is reached."""
        print('Moving to Z=' + str(z) + 'µm...')
        self._send_command('KT' + str(z) + ',' + str(speed))
        response = self._read_response()
        response = response.rstrip()
        while self._reached_target() != 1:
        # _reached_target() returns 1 when stage is at target position
            self._read_realtime_data()
            print('stage pos: ' + str(self.encoder_position))
            sleep(0.05)
        print('stage finished moving')

    def near_knife(self):
        # only used for testing
        pass

    def clear_knife(self):
        # only used for testing
        pass

    def get_clear_position(self):
        return self.clear_position

    def set_clear_position(self, clear_position):
        self.clear_position = int(clear_position)

    def get_retract_clearance(self):
        return self.retract_clearance

    def set_retract_clearance(self, retract_clearance):
        self.retract_clearance = int(retract_clearance)

    def check_for_cut_cycle_error(self):
        pass

    def reset_error_state(self):
        self.error_state = 0
        self.error_info = ''
        self.motor_warning = False

    def disconnect(self):
        if self.connected:
            self.com_port.close()
            print(f'katana: Connection closed (Port {self.com_port.port}).')