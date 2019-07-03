# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module controls the 3View hardware (motorized stage and knife) via
   DigitalMicrograph.
   The DM script SBEMimage_DMcom_GMS2.s must be running in DM.
   Communication with Digital Micrograph (DM) is achieved by read/write file
   operations. The following files are used:
      DMcom.trg - Trigger file
                  Signals that a command is waiting to be read
      DMcom.in - Command/parameter file
                 Contains a command and (optional) up to two parameters
      DMcom.out - Contains output/return value(s)
      DMcom.err - This file signals that a critical error occured.
      DMcom.ack - Acknowledges that a command has been received and processed.
      DMcom.wng - Signals a warning (= error that could be resolved).
"""

import os
from time import sleep
import json
import utils


class Microtome:
    """
    Base class for microtome control. It implements minimum config/parameter handling
    and interactions with GUI. Undefined methods have to be implemented in the child class.
    """
    def __init__(self, config, sysconfig):
        self.cfg = config
        self.syscfg = sysconfig
        self.last_known_x = None
        self.last_known_y = None
        self.last_known_z = None
        self.prev_known_z = None
        if self.cfg['microtome']['last_known_z'] == 'None':
            self.z_prev_session = None
        else:
            self.z_prev_session = float(
                self.cfg['microtome']['last_known_z'])
        self.error_state = 0
        self.error_cause = ''       # additional info on error
        self.motor_warning = False  # True when motors slower than expected
        self.device_name = self.cfg['microtome']['device']
        self.simulation_mode = self.cfg['sys']['simulation_mode'] == 'True'
        # The following three parameters cannot be changed remotely,
        # must be set in DM before acquisition. Pre-acquisition dialog box
        # asks user to ensure the settings in cfg match the DM settings.
        self.knife_cut_speed = float(self.cfg['microtome']['knife_cut_speed'])
        self.knife_retract_speed = float(
            self.cfg['microtome']['knife_retract_speed'])
        self.use_oscillation = bool(self.cfg['microtome']['knife_oscillation'])
        # Full cut duration can currently only be changed in config file
        self.full_cut_duration = float(
            self.cfg['microtome']['full_cut_duration'])
        # Sweep distance can currently only be changed in config file
        self.sweep_distance = int(self.cfg['microtome']['sweep_distance'])
        if (self.sweep_distance < 30) or (self.sweep_distance > 1000):
            # If outside permitted range, set to 70 nm as default:
            self.sweep_distance = 70
            self.cfg['microtome']['sweep_distance'] = '70'

        # The following parameters can be set from SBEMimage GUI:
        self.stage_move_wait_interval = float(
            self.cfg['microtome']['stage_move_wait_interval'])
        self.motor_speed_x = float(self.cfg['microtome']['motor_speed_x'])
        self.motor_speed_y = float(self.cfg['microtome']['motor_speed_y'])
        self.motor_limits = [
            int(self.cfg['microtome']['stage_min_x']),
            int(self.cfg['microtome']['stage_max_x']),
            int(self.cfg['microtome']['stage_min_y']),
            int(self.cfg['microtome']['stage_max_y'])]
        self.stage_calibration = [
            float(self.cfg['microtome']['stage_scale_factor_x']),
            float(self.cfg['microtome']['stage_scale_factor_y']),
            float(self.cfg['microtome']['stage_rotation_angle_x']),
            float(self.cfg['microtome']['stage_rotation_angle_y'])]

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
            self.error_cause = 'microtome.do_sweep: sweep distance out of range'
        elif self.error_state == 0:
            raise NotImplementedError

    def cut(self):
        # only used for testing
        raise NotImplementedError

    def retract_knife(self):
        # only used for testing
        raise NotImplementedError

    def get_motor_speeds(self):
        return self.motor_speed_x, self.motor_speed_y

    def set_motor_speeds(self, motor_speed_x, motor_speed_y):
        self.motor_speed_x = motor_speed_x
        self.motor_speed_y = motor_speed_y
        self.cfg['microtome']['motor_speed_x'] = str(motor_speed_x)
        self.cfg['microtome']['motor_speed_y'] = str(motor_speed_y)
        # Save in sysconfig:
        self.syscfg['stage']['microtome_motor_speed'] = str(
            [self.motor_speed_x, self.motor_speed_y])
        return self.write_motor_speeds_to_script()

    def write_motor_speeds_to_script(self):
        raise NotImplementedError

    def get_stage_move_wait_interval(self):
        return self.stage_move_wait_interval

    def set_stage_move_wait_interval(self, wait_interval):
        self.stage_move_wait_interval = wait_interval
        self.cfg['microtome']['stage_move_wait_interval'] = str(wait_interval)

    def get_motor_limits(self):
        return self.motor_limits

    def set_motor_limits(self, limits):
        self.motor_limits = limits
        self.cfg['microtome']['stage_min_x'] = str(limits[0])
        self.cfg['microtome']['stage_max_x'] = str(limits[1])
        self.cfg['microtome']['stage_min_y'] = str(limits[2])
        self.cfg['microtome']['stage_max_y'] = str(limits[3])
        # Save data in sysconfig:
        self.syscfg['stage']['microtome_motor_limits'] = str(self.motor_limits)

    def move_stage_to_x(self, x):
        # only used for testing
        raise NotImplementedError

    def move_stage_to_y(self, y):
        # only used for testing
        raise NotImplementedError

    def calculate_stage_move_duration(self, target_x, target_y):
        """Use the last known position and the given target position
           to calculate how much time it will take for the motors to move
           to target position.
        """
        duration_x = abs(target_x - self.last_known_x) / self.motor_speed_x
        duration_y = abs(target_y - self.last_known_y) / self.motor_speed_y
        return max(duration_x, duration_y)

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

    def get_stage_z_prev_session(self):
        return self.z_prev_session

    def move_stage_to_z(self, z, safe_mode=True):
        """Move stage to new z position. Used during stack acquisition
           before each cut and for sweeps."""
        raise NotImplementedError

    def get_last_known_xy(self):
        return self.last_known_x, self.last_known_y

    def get_last_known_z(self):
        return self.last_known_z

    def get_prev_known_z(self):
        return self.prev_known_z

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

    def get_error_state(self):
        # Return current error_state
        return self.error_state

    def get_error_cause(self):
        return self.error_cause

    def motor_warning_received(self):
        return self.motor_warning

    def get_knife_cut_speed(self):
        return self.knife_cut_speed

    def set_knife_cut_speed(self, cut_speed):
        self.knife_cut_speed = cut_speed
        self.cfg['microtome']['knife_cut_speed'] = '{0:.1f}'.format(cut_speed)

    def get_knife_retract_speed(self):
        return self.knife_retract_speed

    def set_knife_retract_speed(self, retract_speed):
        self.knife_retract_speed = retract_speed
        self.cfg['microtome']['knife_retract_speed'] = '{0:.1f}'.format(
            retract_speed)

    def is_oscillation_enabled(self):
        return self.use_oscillation

    def set_oscillation_enabled(self, status):
        self.use_oscillation = status
        self.cfg['microtome']['knife_oscillation'] = str(status)

    def get_stage_calibration(self):
        return self.stage_calibration

    def set_stage_calibration(self, eht, params):
        self.stage_calibration = params
        self.cfg['microtome']['stage_scale_factor_x'] = str(params[0])
        self.cfg['microtome']['stage_scale_factor_y'] = str(params[1])
        self.cfg['microtome']['stage_rotation_angle_x'] = str(params[2])
        self.cfg['microtome']['stage_rotation_angle_y'] = str(params[3])
        # Save data in sysconfig:
        calibration_data = json.loads(self.syscfg['stage']['microtome_calibration_data'])
        eht = int(eht * 1000)  # Dict keys in system config use volts, not kV
        calibration_data[str(eht)] = params
        self.syscfg['stage']['microtome_calibration_data'] = json.dumps(calibration_data)

    def update_stage_calibration(self, eht):
        eht = int(eht * 1000)  # Dict keys in system config use volts, not kV
        success = True
        try:
            calibration_data = json.loads(
                self.syscfg['stage']['microtome_calibration_data'])
            available_eht = [int(s) for s in calibration_data.keys()]
        except:
            available_eht = []
            success = False

        if success:
            if eht in available_eht:
                params = calibration_data[str(eht)]
            else:
                success = False
                # Fallback option: nearest among the available EHT calibrations
                new_eht = 1500
                min_diff = abs(eht - 1500)
                for eht_choice in available_eht:
                    diff = abs(eht - eht_choice)
                    if diff < min_diff:
                        min_diff = diff
                        new_eht = eht_choice
                params = calibration_data[str(new_eht)]
            self.cfg['microtome']['stage_scale_factor_x'] = str(params[0])
            self.cfg['microtome']['stage_scale_factor_y'] = str(params[1])
            self.cfg['microtome']['stage_rotation_angle_x'] = str(params[2])
            self.cfg['microtome']['stage_rotation_angle_y'] = str(params[3])
            self.stage_calibration = params
        return success

    def get_full_cut_duration(self):
        return self.full_cut_duration

    def set_full_cut_duration(self, cut_duration):
        self.full_cut_duration = cut_duration
        self.cfg['microtome']['full_cut_duration'] = str(cut_duration)
        # Save duration in sysconfig:
        self.syscfg['knife']['full_cut_duration'] = str(cut_duration)

    def get_sweep_distance(self):
        return self.sweep_distance


class Microtome_3View(Microtome):
    """
    Refactored DM class which inherits basic functionality from MicrotomeBase.
    TODO: untested.
    """
    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)

        # Perform handshake and read initial X/Y/Z.
        if not self.simulation_mode:
            self._send_dm_command('Handshake')
            # DM script should react to trigger file by reading command file
            # usually within <0.1 s.
            sleep(1)  # Give DM plenty of time to write response into file.
            if self._dm_handshake_success():
                # Get initial X/Y/Z
                current_z = self.get_stage_z(wait_interval=1)
                current_x, current_y = self.get_stage_xy(wait_interval=1)
                if ((current_x is None) or (current_y is None)
                        or (current_z is None)):
                    self.error_state = 101
                    self.error_cause = ('microtome.__init__: could not read '
                                        'initial stage position')
                elif current_z < 0:
                    self.error_state = 101
                    self.error_cause = ('microtome.__init__: stage z position '
                                        'must not be negative.')
                # Check if z coordinate matches z from previous session:
                elif (self.z_prev_session is not None
                      and abs(current_z - self.z_prev_session) > 0.01):
                    self.error_state = 206
                    self.error_cause = ('microtome.__init__: stage z position '
                                        'mismatch')
                # Update motor speed calibration in DM script:
                success = self.write_motor_speeds_to_script()
                if not success and self.error_state == 0:
                    self.error_state = 101
                    self.error_cause = ('microtome.__init__: could not set '
                                        'motor speed calibration')
            else:
                self.error_state = 101
                self.error_cause = 'microtome.__init__: handshake failed'

    def _send_dm_command(self, cmd, set_values=[]):
        """Send a command to the DM script."""
        # First, if output file exists, delete it to ensure old values are gone
        if os.path.isfile('..\\dm\\DMcom.out'):
            os.remove('..\\dm\\DMcom.out')
        # Try to open command file:
        success, cmd_file = utils.try_to_open('..\\dm\\DMcom.in', 'w+')
        if success:
            cmd_file.write(cmd)
            for item in set_values:
                cmd_file.write('\n' + str(item))
            cmd_file.close()
            # Create new trigger file:
            success, trg_file = utils.try_to_open('..\\dm\\DMcom.trg', 'w+')
            if success:
                trg_file.close()
            elif self.error_state == 0:
                self.error_state = 102
                self.error_cause = ('microtome._send_dm_command: could not '
                                    'create trigger file')
        elif self.error_state == 0:
            self.error_state = 102
            self.error_cause = ('microtome._send_dm_command: could not write '
                                'to command file')

    def _read_dm_return_values(self):
        """Try to read return file and, if successful, return values."""
        return_values = []
        success, return_file = utils.try_to_open('..\\dm\\DMcom.out', 'r')
        if success:
            for line in return_file:
                return_values.append(line.rstrip())
            return_file.close()
        elif self.error_state == 0:
            self.error_state = 104
            self.error_cause = ('microtome._read_dm_return_values: could not '
                                'read from return file')
        if return_values == []:
            return_values = [None, None]
        return return_values

    def _dm_handshake_success(self):
        """Verify that handshake command has worked."""
        read_success = True
        return_value = None
        try:
            file_handle = open('..\\dm\\DMcom.out', 'r')
        except:
            # Try once more:
            sleep(1)
            try:
                file_handle = open('..\\dm\\DMcom.out', 'r')
            except:
                read_success = False
        if read_success:
            return_value = file_handle.readline().rstrip()
            if return_value == 'OK':
                return True
        else:
            # Error state assigned in self.__init__()
            return False

    def do_full_cut(self):
        """Perform a full cut cycle. This is the only knife control function
           used during stack acquisitions.
        """
        self._send_dm_command('MicrotomeStage_FullCut')
        sleep(0.2)

    def do_full_approach_cut(self):
        """Perform a full cut cycle under the assumption that knife is
           already neared."""
        self._send_dm_command('MicrotomeStage_FullApproachCut')
        sleep(0.2)

    def do_sweep(self, z_position):
        """Perform a sweep by cutting slightly above the surface."""
        if (((self.sweep_distance < 30) or (self.sweep_distance > 1000))
                and self.error_state == 0):
            self.error_state = 205
            self.error_cause = 'microtome.do_sweep: sweep distance out of range'
        elif self.error_state == 0:
            # Move to new z position:
            sweep_z_position = z_position - (self.sweep_distance / 1000)
            self.move_stage_to_z(sweep_z_position)
            if self.error_state > 0:
                # Try again:
                self.reset_error_state()
                sleep(2)
                self.move_stage_to_z(sweep_z_position)
            if self.error_state == 0:
                # Do a cut cycle above the sample surface to clear away debris:
                self.do_full_cut()
                sleep(self.full_cut_duration)
                # Cutting error?
                if os.path.isfile('..\\dm\\DMcom.err'):
                    self.error_state = 205
                    self.error_cause = ('microtome.do_sweep: error during '
                                        'cutting cycle')
                elif not os.path.isfile('..\\dm\\DMcom.ac2'):
                    # Cut cycle was not carried out:
                    self.error_state = 103
                    self.error_cause = ('microtome.do_sweep: command not '
                                        'processed by DM script')

            # Move to previous z position (before sweep):
            self.move_stage_to_z(z_position)
            if self.error_state > 0:
                # try again:
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
        if os.path.isfile('..\\dm\\DMcom.ack'):
            os.remove('..\\dm\\DMcom.ack')
        self._send_dm_command('SetMotorSpeedCalibrationXY',
                              [self.motor_speed_x, self.motor_speed_y])
        sleep(1)
        # Did it work?
        if os.path.isfile('..\\dm\\DMcom.ack'):
            success = True
        else:
            sleep(2)
            success = os.path.isfile('..\\dm\\DMcom.ack')
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
        """Get current XY coordinates from DM"""
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
        """Move stage to coordinates X/Y. This function is called during
           acquisitions. It includes waiting times. The other move functions
           below do not.
        """
        x, y = coordinates
        if os.path.isfile('..\\dm\\DMcom.ack'):
            os.remove('..\\dm\\DMcom.ack')
        self._send_dm_command('MicrotomeStage_SetPositionXY_Confirm', [x, y])
        sleep(0.2)
        # Wait for the time it takes the motors to move:
        move_duration = self.calculate_stage_move_duration(x, y)
        sleep(move_duration + 0.1)
        # Additional waiting time to let vibrations subside:
        sleep(self.stage_move_wait_interval)
        # Is there a problem with the motors or was the command not executed?
        if os.path.isfile('..\\dm\\DMcom.ack'):
            # Everything ok! Accept new position as last known position
            self.last_known_x, self.last_known_y = x, y
            # Check if there was a warning:
            if os.path.isfile('..\\dm\\DMcom.wng'):
                # There was a warning from the script - motors may have
                # moved too slowly
                self.motor_warning = True
        elif os.path.isfile('..\\dm\\DMcom.err') and self.error_state == 0:
            # Error: motors did not reach the target position!
            self.error_state = 201
            self.error_cause = ('microtome.move_stage_to_xy: did not reach '
                                'target xy position')
        elif self.error_state == 0:
            # If neither .ack nor .err exist, the command was not processed:
            self.error_state = 103
            self.error_cause = ('microtome.move_stage_to_xy: command not '
                                'processed by DM script')

    def get_stage_z(self, wait_interval=0.5):
        """Get current Z coordinate from DM"""
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
            self.cfg['microtome']['last_known_z'] = str(z)
        return z

    def get_stage_z_prev_session(self):
        return self.z_prev_session

    def move_stage_to_z(self, z, safe_mode=True):
        """Move stage to new z position. Used during stack acquisition
           before each cut and for sweeps."""
        if os.path.isfile('..\\dm\\DMcom.ack'):
            os.remove('..\\dm\\DMcom.ack')
        if (((self.last_known_z >= 0) and (abs(z - self.last_known_z) > 0.205))
                and self.error_state == 0 and safe_mode):
            # Z should not move more than ~200 nm during stack acq!
            self.error_state = 203
            self.error_cause = ('microtome.move_stage_to_z: Z move too '
                                'large (> 200 nm)')
        else:
            self._send_dm_command('MicrotomeStage_SetPositionZ_Confirm', [z])
            sleep(1)  # wait for command to be read and executed
            # Is there a problem with the motors?
            if os.path.isfile('..\\dm\\DMcom.ack'):
                # Everything ok! Accept new position as last known position
                self.prev_known_z = self.last_known_z
                self.last_known_z = z
                self.cfg['microtome']['last_known_z'] = str(z)
            elif os.path.isfile('..\\dm\\DMcom.err') and self.error_state == 0:
                # There was an error during the move!
                self.error_state = 202
                self.error_cause = ('microtome.move_stage_to_z: did not reach '
                                    'target z position')
            elif self.error_state == 0:
                # If neither .ack nor .err exist, the command was not processed:
                self.error_state = 103
                self.error_cause = ('move_stage_to_z: command not processed '
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
        # Check if error ocurred during self.do_full_cut():
        if self.error_state == 0 and os.path.isfile('..\\dm\\DMcom.err'):
            self.error_state = 204
            self.error_cause = ('microtome.do_full_cut: error during '
                                'cutting cycle')
        elif not os.path.isfile('..\\dm\\DMcom.ac2'):
            # Cut cycle was not carried out within the specified time limit.
            self.error_state = 103
            self.error_cause = ('microtome.do_full_cut: command not '
                                'processed by DM script')
            duration_exceeded = True
            # Wait another 10 sec maximum:
            for i in range(10):
                sleep(1)
                if os.path.isfile('..\\dm\\DMcom.ac2'):
                    self.error_state = 0
                    self.error_cause = ''
                    break
        return duration_exceeded

    def reset_error_state(self):
        self.error_state = 0
        self.error_cause = ''
        self.motor_warning = False
        if os.path.isfile('..\\dm\\DMcom.err'):
            os.remove('..\\dm\\DMcom.err')
        if os.path.isfile('..\\dm\\DMcom.wng'):
            os.remove('..\\dm\\DMcom.wng')
