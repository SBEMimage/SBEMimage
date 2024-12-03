# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================


import os
from time import sleep

import utils
from constants import Error
from microtome_control import Microtome


class Microtome_3View(Microtome):
    """
    This class contains the methods to control a 3View microtome via
    DigitalMicrograph (DM).
    The DM script SBEMimage_DMcom_GMS2.s (or SBEMimage_DMcom_GMS3.s for GMS3)
    must be running in DM to receive commands from SBEMimage and transmit them
    to the 3View hardware (XY stage and knife arm).
    Communication with DM is achieved by read/write file operations.
    The following files are used:
      DMcom.in:   Command/parameter file. Contains a command and up to
                  two optional parameters.
      DMcom.cmd:  The file 'DMcom.in' is renamed to 'DMcom.cmd' to trigger
                  its contents to be processed by DM.
      DMcom.out:  Contains return value(s) from DM
      DMcom.ack:  Confirms that a command has been received and processed.
      DMcom.ac2:  Confirms that a full cut cycle has been completed.
      DMcom.wng:  Signals a warning (a problem occurred, but could be resolved).
      DMcom.err:  Signals that a critical error occured.

    The 3View knife parameters (knife speeds, osciallation on/off) cannot be
    changed remotely via SBEMimage; they must be set in DM before the
    acquisition starts. The pre-acquisition dialog box asks the user
    to ensure these settings match the DM settings (for logging purposes).
    """

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        # Paths to DM communication files
        self.INPUT_FILE = os.path.join('..', 'dm', 'DMcom.in')
        self.COMMAND_FILE = os.path.join('..', 'dm', 'DMcom.cmd')
        self.OUTPUT_FILE = os.path.join('..', 'dm', 'DMcom.out')
        self.ACK_FILE = os.path.join('..', 'dm', 'DMcom.ack')
        self.ACK_CUT_FILE = os.path.join('..', 'dm', 'DMcom.ac2')
        self.WARNING_FILE = os.path.join('..', 'dm', 'DMcom.wng')
        self.ERROR_FILE = os.path.join('..', 'dm', 'DMcom.err')

        # Perform handshake and read initial X/Y/Z
        if not self.simulation_mode and self.error_state == Error.none:
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
                    self.error_state = Error.dm_init
                    self.error_info = ('microtome.__init__: could not read '
                                       'initial stage position')
                elif current_z < 0:
                    self.error_state = Error.dm_init
                    self.error_info = ('microtome.__init__: stage z position '
                                       'must not be negative.')
                # Check if current Z coordinate matches last known Z from
                # previous session
                elif (self.stage_z_prev_session is not None
                      and abs(current_z - self.stage_z_prev_session) > 0.01):
                    self.error_state = Error.mismatch_z
                    self.error_info = ('microtome.__init__: stage z position '
                                       'mismatch')
                # Update motor speeds in DM script
                success = self.update_motor_speeds_in_dm_script()
                # If update unsuccesful, set new error state unless microtome
                # is already in an error state after reading the coordinates.
                if not success and self.error_state == Error.none:
                    self.error_state = Error.dm_init
                    self.error_info = ('microtome.__init__: could not update '
                                       'DM script with current motor speeds')
            else:
                self.error_state = Error.dm_init
                self.error_info = 'microtome.__init__: handshake failed'

    def _send_dm_command(self, cmd, set_values=[]):
        """Send a command to the DigitalMicrograph script."""
        # If output file exists, delete it to ensure old return values are gone.
        # Use try_to_remove() because there may be delays in DM when
        # DM is writing to that file.
        if os.path.isfile(self.OUTPUT_FILE):
            utils.try_to_remove(self.OUTPUT_FILE)
        # Delete .ack and .ac2 files
        if os.path.isfile(self.ACK_FILE):
            os.remove(self.ACK_FILE)
        if os.path.isfile(self.ACK_CUT_FILE):
            os.remove(self.ACK_CUT_FILE)
        # Try to open input file
        success, input_file = utils.try_to_open(self.INPUT_FILE, 'w+')
        if success:
            input_file.write(cmd)
            for item in set_values:
                input_file.write('\n' + str(item))
            input_file.close()
            # Trigger DM script by renaming input file to command file
            try:
                os.rename(self.INPUT_FILE, self.COMMAND_FILE)
            except Exception as e:
                if self.error_state == Error.none:
                    self.error_state = Error.dm_comm_send
                    self.error_info = ('microtome._send_dm_command: could not '
                                       'rename input file (' + str(e) + ')')
        elif self.error_state == Error.none:
            self.error_state = Error.dm_comm_send
            self.error_info = ('microtome._send_dm_command: could not write '
                               'to input file')

    def _read_dm_return_values(self):
        """Try to read output file and, if successful, return values."""
        return_values = []
        success, return_file = utils.try_to_open(self.OUTPUT_FILE, 'r')
        if success:
            for line in return_file:
                return_values.append(line.rstrip())
            return_file.close()
        elif self.error_state == Error.none:
            self.error_state = Error.dm_comm_retval
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
                and self.error_state == Error.none):
            self.error_state = Error.sweeping
            self.error_info = 'microtome.do_sweep: sweep distance out of range'
        elif self.error_state == Error.none:
            # Move to new z position
            sweep_z_position = z_position - (self.sweep_distance / 1000)
            self.move_stage_to_z(sweep_z_position)
            if self.error_state != Error.none:
                # Try again
                self.reset_error_state()
                sleep(2)
                self.move_stage_to_z(sweep_z_position)
            if self.error_state == Error.none:
                # Do a cut cycle above the sample surface to clear away debris
                self.do_full_cut()
                sleep(self.full_cut_duration)
                # Check if error occurred during cut cycle.
                if os.path.isfile(self.ERROR_FILE):
                    self.error_state = Error.sweeping
                    self.error_info = ('microtome.do_sweep: error during '
                                       'cutting cycle')
                elif not os.path.isfile(self.ACK_CUT_FILE):
                    # Cut cycle was not carried out
                    self.error_state = Error.dm_comm_response
                    self.error_info = ('microtome.do_sweep: command not '
                                       'processed by DM script')

            # Move to previous z position (before sweep)
            self.move_stage_to_z(z_position)
            if self.error_state != Error.none:
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

    def update_motor_speeds_in_dm_script(self):
        self._send_dm_command('SetMotorSpeedXY',
                              [self.motor_speed_x, self.motor_speed_y])
        sleep(1)
        # Check if command was processed by DM
        if os.path.isfile(self.ACK_FILE):
            success = True
        else:
            sleep(2)
            success = os.path.isfile(self.ACK_FILE)
        if not success:
            # Command was not processed
            if self.error_state == Error.none:
                self.error_state = Error.dm_comm_response
                self.error_info = ('microtome.update_motor_speeds_in_dm_script: '
                                   'command not processed by DM script')
        return success

    def measure_motor_speeds(self):
        """Send command to DM script to measure motor speeds. The script
        will run the measurement routine and write the measured speeds into the
        output file. Read the output file and return the speeds.
        """
        self._send_dm_command('MeasureMotorSpeedXY')
        sleep(0.2)
        duration = 0
        # Measurement routine should be running in DM now.
        # Wait for up to 90 sec or until ack file found.
        for i in range(90):
            sleep(1)
            duration += 1
            if os.path.isfile(self.ACK_FILE):
                # Measurement is done, read the measured speeds
                speed_x, speed_y = self._read_dm_return_values()
                try:
                    speed_x = float(speed_x)
                    speed_y = float(speed_y)
                except:
                    speed_x, speed_y = None, None
                return speed_x, speed_y

        # Measurement command was not processed/finished within 90 s
        if self.error_state == Error.none:
            self.error_state = Error.dm_comm_response
            self.error_info = ('microtome.measure_motor_speeds: '
                               'DM script timeout')
        return None, None

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
        acquisitions. It includes waiting times.
        """
        x, y = coordinates
        self._send_dm_command('MicrotomeStage_SetPositionXY_Confirm', [x, y])
        sleep(0.2)
        # Wait for the time it takes the motors to move
        # plus stage_move_wait_interval
        x_move_duration, y_move_duration = self.rel_stage_move_duration(x, y)
        sleep(max(x_move_duration, y_move_duration)
              + self.stage_move_wait_interval
              + 0.2)
        # Update counters (number of moves, distance, duration)
        self.total_xyz_move_counter[0][0] += 1
        self.total_xyz_move_counter[1][0] += 1
        # Update total distance moves
        self.total_xyz_move_counter[0][1] += abs(x - self.last_known_x)
        self.total_xyz_move_counter[1][1] += abs(y - self.last_known_y)
        # Update total move duration
        self.total_xyz_move_counter[0][2] += x_move_duration
        self.total_xyz_move_counter[1][2] += y_move_duration
        # Check if the command was processed successfully
        if os.path.isfile(self.ACK_FILE):
            self.last_known_x, self.last_known_y = x, y
            self.slow_xy_move_warnings.append(0)
            self.failed_x_move_warnings.append(0)
            self.failed_y_move_warnings.append(0)
        else:
            # Wait for up to 3 additional seconds (DM script will try
            # to read coordinates again to confirm move)
            if self.stage_move_wait_interval < 3:
                sleep(3 - self.stage_move_wait_interval)
            # Check again for ACK_FILE
            if os.path.isfile(self.ACK_FILE):
                # Move was carried out, but with a delay.
                self.last_known_x, self.last_known_y = x, y
                # Check if there was a warning
                if os.path.isfile(self.WARNING_FILE):
                    # There was a warning from the script - motors may have
                    # moved too slowly, but they reached the target position
                    # after an extra 1.5s delay.
                    self.slow_xy_move_warnings.append(1)
                    self.slow_xy_move_counter += 1
                else:
                    self.slow_xy_move_warnings.append(0)
                # Move did not fail: Update deques
                self.failed_x_move_warnings.append(0)
                self.failed_y_move_warnings.append(0)
            elif os.path.isfile(self.ERROR_FILE) and self.error_state == Error.none:
                # Move was not confirmed and error file exists:
                # The motors did not reach the target position.
                self.error_state = Error.stage_xy
                self.error_info = ('microtome.move_stage_to_xy: did not reach '
                                   'target xy position')
                # Read last known position (written into output file by DM
                # if a move fails.)
                current_xy = self._read_dm_return_values()
                if len(current_xy) == 2:
                    prev_x = self.last_known_x
                    prev_y = self.last_known_y
                    try:
                        self.last_known_x = float(current_xy[0])
                        self.last_known_y = float(current_xy[1])
                    except:
                        # keep previous coordinates
                        self.last_known_x = prev_x
                        self.last_known_y = prev_y
                    # Check which of the motors failed to reach target, and
                    # update counters accordingly
                    if abs(x - self.last_known_x) > 0.002:
                        self.failed_xyz_move_counter[0] += 1
                        self.failed_x_move_warnings.append(1)
                    else:
                        self.failed_x_move_warnings.append(0)
                    if abs(y - self.last_known_y) > self.xy_tolerance:
                        self.failed_xyz_move_counter[1] += 1
                        self.failed_y_move_warnings.append(1)
                    else:
                        self.failed_y_move_warnings.append(0)

            elif self.error_state == Error.none:
                # If neither .ack nor .err exist, the command was not processed
                self.error_state = Error.dm_comm_response
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
                self.error_state = Error.mismatch_z
            self.prev_known_z = self.last_known_z
            self.last_known_z = z
        return z

    def move_stage_to_z(self, z, safe_mode=True):
        """Move stage to new z position. Used during stack acquisitions
        before each cut and for sweeps.
        """
        if (((self.last_known_z >= 0) and (abs(z - self.last_known_z) > 0.205))
                and self.error_state == Error.none and safe_mode):
            # Z must not change more than ~200 nm during stack acquisitions!
            self.error_state = Error.stage_z_move
            self.error_info = ('microtome.move_stage_to_z: Z move too '
                               'large (> 200 nm)')
        else:
            self._send_dm_command('MicrotomeStage_SetPositionZ_Confirm', [z])
            sleep(1)  # wait for command to be read and executed
            self.total_xyz_move_counter[2][0] += 1
            # Update total distance moved in z
            self.total_xyz_move_counter[2][1] += abs(z - self.last_known_z)
            # Check if command was processed
            if os.path.isfile(self.ACK_FILE):
                # Accept new position as last known position
                self.prev_known_z = self.last_known_z
                self.last_known_z = z
                self.failed_z_move_warnings.append(0)
            else:
                # Wait an additional two seconds and check again for ACK_FILE
                sleep(2)
                if os.path.isfile(self.ACK_FILE):
                    self.prev_known_z = self.last_known_z
                    self.last_known_z = z
                    self.failed_z_move_warnings.append(0)
                elif os.path.isfile(self.ERROR_FILE) and self.error_state == Error.none:
                    # There was an error during the move
                    self.error_state = Error.stage_z
                    self.error_info = ('microtome.move_stage_to_z: '
                                       'did not reach target z position')
                    self.failed_xyz_move_counter[2] += 1
                    self.failed_z_move_warnings.append(1)
                    # Read last known position (written into output file by DM
                    # if a move fails.)
                    current_z = self._read_dm_return_values()
                    if len(current_z) == 1:
                        try:
                            self.last_known_z = float(current_z[0])
                        except:
                            pass  # keep current coordinates
                elif self.error_state == Error.none:
                    # If neither .ack nor .err exist, command was not processed
                    self.error_state = Error.dm_comm_response
                    self.error_info = ('move_stage_to_z: command not processed '
                                       'by DM script')

    def stop_script(self):
        self._send_dm_command('StopScript')
        sleep(0.2)

    def near_knife(self):
        # only used for testing
        self._send_dm_command('MicrotomeStage_Near')
        sleep(4)

    def clear_knife(self):
        # only used for testing
        self._send_dm_command('MicrotomeStage_Clear')
        sleep(4)

    def check_cut_cycle_status(self):
        # Excess duration of cutting cycle in seconds
        delay = 0
        # Check if error occurred during self.do_full_cut()
        if self.error_state == Error.none and os.path.isfile(self.ERROR_FILE):
            self.error_state = Error.cutting
            self.error_info = ('microtome.do_full_cut: error during '
                               'cutting cycle')
        elif not os.path.isfile(self.ACK_CUT_FILE):
            # Cut cycle was not carried out within the specified time limit
            self.error_state = Error.dm_comm_response
            self.error_info = ('microtome.do_full_cut: command not '
                               'processed by DM script')
            # Wait for another 15 sec maximum until cut is confirmed (.ac2
            # file found or error file found.
            for i in range(15):
                sleep(1)
                delay += 1
                if os.path.isfile(self.ACK_CUT_FILE):
                    # Cut is confirmed after delay, reset error state
                    self.error_state = Error.none
                    self.error_info = ''
                    break
                elif os.path.isfile(self.ERROR_FILE):
                    # An error occurred during the excess duration
                    self.error_state = Error.cutting
                    self.error_info = ('microtome.do_full_cut: error during '
                                       'cutting cycle')
                    break
        return delay

    def reset_error_state(self):
        self.error_state = Error.none
        self.error_info = ''
        if os.path.isfile(self.ERROR_FILE):
            os.remove(self.ERROR_FILE)
        if os.path.isfile(self.WARNING_FILE):
            os.remove(self.WARNING_FILE)
