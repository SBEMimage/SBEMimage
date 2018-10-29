# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module provides the commands to operate the SEM. It calls the
   low-level functions of the Carl Zeiss EM API. Only the functions that are
   actually needed in SBEMimage have been implemented. The module has so far
   been tested with a ZEISS Merlin SEM, but should in principle (with minor
   modifications) work with all ZEISS SEMs that can be controlled via SmartSEM.

   TODO: Make SEM() the parent class for SEM_Merlin(), SEM_Sigma() and
   SEM_Quanta().
"""

from time import sleep

import json
import pythoncom
import win32com.client   # required to access CZEMApi.ocx (Carl Zeiss EM API)
from win32com.client import VARIANT  # necessary for API function calls

class SEM():

    def __init__(self, config, sysconfig):
        self.cfg = config
        self.syscfg = sysconfig
        self.last_known_x = None
        self.last_known_y = None
        self.last_known_z = None
        # self.error_state: see error codes in stack_acquisition.py
        # Must be reset with self.reset_error_state()
        self.error_state = 0
        self.error_cause = ''
        self.device_name = self.cfg['sem']['device']
        self.simulation_mode = self.cfg['sys']['simulation_mode'] == 'True'
        self.load_system_constants()
        # Set beam parameters
        self.eht = float(self.cfg['sem']['eht'])
        self.beam_current = float(self.cfg['sem']['beam_current'])
        self.rotation = 0  # 0 for now
        # Settings for 'Grab frame' dialog
        self.grab_dwell_time = float(self.cfg['sem']['grab_frame_dwell_time'])
        self.grab_pixel_size = float(self.cfg['sem']['grab_frame_pixel_size'])
        self.grab_frame_size_selector = int(
            self.cfg['sem']['grab_frame_size_selector'])
        # Save selected frame size in pixels in config file
        self.cfg['sem']['grab_frame_size_xy'] = str(
            self.STORE_RES[self.grab_frame_size_selector])
        # Cycle time = total duration to acquire a full frame
        # self.cycle_time holds the cycle time for the current frame settings,
        # will be set the first time when self.apply_frame_settings() is called.
        self.current_cycle_time = 0
        # Stage parameters:
        self.stage_move_wait_interval = float(
            self.cfg['sem']['stage_move_wait_interval'])
        self.motor_speed_x = float(self.cfg['sem']['motor_speed_x'])
        self.motor_speed_y = float(self.cfg['sem']['motor_speed_y'])
        self.motor_limits = [
            int(self.cfg['sem']['stage_min_x']),
            int(self.cfg['sem']['stage_max_x']),
            int(self.cfg['sem']['stage_min_y']),
            int(self.cfg['sem']['stage_max_y'])]
        self.stage_calibration = [
            float(self.cfg['sem']['stage_scale_factor_x']),
            float(self.cfg['sem']['stage_scale_factor_y']),
            float(self.cfg['sem']['stage_rotation_angle_x']),
            float(self.cfg['sem']['stage_rotation_angle_y'])]

        if not self.simulation_mode:
            # Dispatch Merlin API (CZ EM API OLE Control):
            # CZEMApi.ocx must be registered in the Windows registry!
            # 'CZ.EMApiCtrl.1'  {71BD42C4-EBD3-11D0-AB3A-444553540000}
            try:
                self.sem_api = win32com.client.Dispatch('CZ.EMApiCtrl.1')
                ret_val = self.sem_api.InitialiseRemoting()
            except:
                ret_val = 1
            if ret_val != 0:    # In ZEISS API, response of '0' means success
                self.error_state = 301
                self.error_cause = (
                    'sem.__init__: remote API control could not be initalized.')
            elif config['sys']['use_microtome'] == 'False':
                # Load SEM stage coordinates:
                self.last_known_x, self.last_known_y, self.last_known_z = (
                    self.get_stage_xyz())

    def load_system_constants(self):
        """Load all constant parameters from system config."""
        self.STORE_RES = json.loads(self.syscfg['sem']['store_res'])
        self.DWELL_TIME = json.loads(self.syscfg['sem']['dwell_time'])
        # Cycle times: Duration of scanning one full frame, depends on
        # scan rate and frame size:
        # cycle_time[frame_size_selector][scan_rate] -> duration in sec
        cycle_time = json.loads(self.syscfg['sem']['cycle_time'])
        # Convert string keys to int:
        self.CYCLE_TIME = {int(k): v for k, v in cycle_time.items()}
        self.DEFAULT_DELAY = float(self.syscfg['sem']['delay_after_cycle_time'])
        # self.MAG_PX_SIZE_FACTOR is needed to calculate the magnification
        # as a function of frame resolution and pixel size (in nm):
        # M = MAG_PX_SIZE_FACTOR / (STORE_RES_X * PX_SIZE)
        self.MAG_PX_SIZE_FACTOR = int(self.syscfg['sem']['mag_px_size_factor'])

    def get_mag_px_size_factor(self):
        return self.MAG_PX_SIZE_FACTOR

    def set_mag_px_size_factor(self, new_factor):
        self.MAG_PX_SIZE_FACTOR = new_factor
        # Save in sysconfig:
        self.syscfg['sem']['mag_px_size_factor'] = str(new_factor)

    def turn_eht_on(self):
        ret_val = self.sem_api.Execute('CMD_BEAM_ON')
        if ret_val == 0:
            return True
        else:
            self.error_state = 306
            self.error_cause = 'sem.turn_eht_on: command failed'
            return False

    def turn_eht_off(self):
        ret_val = self.sem_api.Execute('CMD_EHT_OFF')
        if ret_val == 0:
            return True
        else:
            self.error_state = 306
            self.error_cause = 'sem.turn_eht_off: command failed'
            return False

    def is_eht_on(self):
        return (self.sem_api.Get('DP_RUNUPSTATE', 0)[1] == 'Beam On')

    def is_eht_off(self):
        # This is not the same as "not is_eht_on()" because there are
        # intermediate beam states between on and off.
        return (self.sem_api.Get('DP_RUNUPSTATE', 0)[1] == 'EHT Off')

    def get_eht(self):
        """Return the target EHT, which is not necessarily the current EHT
           in SmartSEM
        """
        return self.eht

    def set_eht(self, target_eht):
        """Save the target EHT and set the EHT in SmartSEM
           to this target value.
        """
        self.eht = target_eht
        self.cfg['sem']['eht'] = '{0:.2f}'.format(target_eht)
        # target_eht given in kV
        variant = VARIANT(pythoncom.VT_R4, target_eht * 1000)
        ret_val = self.sem_api.Set('AP_MANUALKV', variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = 306
            self.error_cause = 'sem.set_eht: command failed'
            return False

    def get_beam_current(self):
        """Return the target beam current, which is not necessarily the
           current beam current in SmartSEM
        """
        return self.beam_current

    def set_beam_current(self, target_current):
        """Save the target beam current in pA and set the beam in SmartSEM
           to this target current.
        """
        self.beam_current = target_current
        self.cfg['sem']['beam_current'] = str(target_current)
        # target_current given in pA
        variant = VARIANT(pythoncom.VT_R4, target_current * 10**(-12))
        ret_val = self.sem_api.Set('AP_IPROBE', variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = 307
            self.error_cause = 'sem.set_beam_current: command failed'
            return False

    def apply_beam_settings(self):
        """"Set the SEM to the target EHT voltage and beam current."""
        ret_val1 = self.set_eht(self.eht)
        ret_val2 = self.set_beam_current(self.beam_current)
        return (ret_val1 and ret_val2)

    def get_grab_settings(self):
        return [self.grab_frame_size_selector,
                self.grab_pixel_size,
                self.grab_dwell_time]

    def set_grab_settings(self, frame_size_selector, pixel_size, dwell_time):
        self.grab_frame_size_selector = frame_size_selector
        self.cfg['sem']['grab_frame_size_selector'] = str(
            self.grab_frame_size_selector)
        # Explicit storage of frame size in pixels:
        self.cfg['sem']['grab_frame_size_xy'] = str(
            self.STORE_RES[self.grab_frame_size_selector])
        self.grab_pixel_size = pixel_size
        self.cfg['sem']['grab_frame_pixel_size'] = str(
            self.grab_pixel_size)
        self.grab_dwell_time = dwell_time
        self.cfg['sem']['grab_frame_dwell_time'] = str(
            self.grab_dwell_time)

    def apply_grab_settings(self):
        self.apply_frame_settings(
            self.grab_frame_size_selector,
            self.grab_pixel_size,
            self.grab_dwell_time)

    def apply_frame_settings(self, frame_size_selector, pixel_size, dwell_time):
        """Apply the frame settings (frame size, pixel size and dwell time)."""
        ret_val1 = self.set_frame_size(frame_size_selector)
        # The pixel size determines the magnification:
        mag = int(self.MAG_PX_SIZE_FACTOR /
                  (self.STORE_RES[frame_size_selector][0] * pixel_size))
        ret_val2 = self.set_mag(mag)
        ret_val3 = self.set_dwell_time(dwell_time)
        # Load cycle time for current settings from SmartSEM data
        scan_speed = self.DWELL_TIME.index(dwell_time)
        # 0.3 s and 0.8 s are safety margins
        self.current_cycle_time = (
            self.CYCLE_TIME[frame_size_selector][scan_speed] + 0.3)
        if self.current_cycle_time < 0.8:
            self.current_cycle_time = 0.8
        return (ret_val1 and ret_val2 and ret_val3)

    def set_frame_size(self, frame_size_selector):
        freeze_variant = VARIANT(pythoncom.VT_R4, 2)  # 2 = freeze on command
        self.sem_api.Set('DP_FREEZE_ON', freeze_variant)
        selector_variant = VARIANT(pythoncom.VT_R4, frame_size_selector)
        ret_val = self.sem_api.Set('DP_IMAGE_STORE', selector_variant)[0]
        # Changing this parameter causes an 'unfreeze' command.
        # Freeze again, immediately:
        self.sem_api.Execute('CMD_FREEZE_ALL')
        # Change back to 'freeze on end of frame' (0)
        freeze_variant = VARIANT(pythoncom.VT_R4, 0)  # 0 = freeze on end of frame
        self.sem_api.Set('DP_FREEZE_ON', freeze_variant)
        if ret_val == 0:
            return True
        else:
            self.error_state = 308
            self.error_cause = 'sem.set_frame_size: command failed'
            return False

    def get_mag(self):
        return self.sem_api.Get('AP_MAG', 0)[1]

    def set_mag(self, target_mag):
        ret_val = self.sem_api.Set('AP_MAG', str(target_mag))[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = 309
            self.error_cause = 'sem.set_mag: command failed'
            return False

    def set_scan_rate(self, scan_rate_selector):
        ret_val = self.sem_api.Execute('CMD_SCANRATE'
                                       + str(scan_rate_selector))
        if ret_val == 0:
            return True
        else:
            self.error_state = 310
            self.error_cause = 'sem.set_scan_rate: command failed'
            return False

    def set_dwell_time(self, dwell_time):
        """Translates dwell time into scan rate and calls self.set_scan_rate()
        """
        return self.set_scan_rate(self.DWELL_TIME.index(dwell_time))

    def acquire_frame(self, save_path_filename, extra_delay=0):
        """Acquire a full frame and save it to save_path_filename.
           All imaging parameters must be applied BEFORE calling this function.
           To avoid grabbing the image before it is acquired completely, an
           additional waiting period after the cycle time may be necessary.
           The delay specified in syscfg is added by default for
           cycle times > 0.5 s.
        """
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        self.sem_api.Execute('CMD_FREEZE_ALL') # Assume 'freeze on end of frame'
        if self.current_cycle_time > 0.5:
            delay_after_cycle_time = self.DEFAULT_DELAY
        else:
            delay_after_cycle_time = 0
        sleep(self.current_cycle_time + delay_after_cycle_time + extra_delay)
        # This sleep interval could be used to carry out other operations in
        # parallel while waiting for the new image.
        ret_val = self.sem_api.Grab(0, 0, 1024, 768, 0,
                                    save_path_filename)
        if ret_val == 0:
            return True
        else:
            self.error_state = 302
            self.error_cause = 'sem.acquire_frame: command failed'
            return False

    def save_frame(self, save_path_filename):
        """Save the frame currently displayed in SmartSEM."""
        ret_val = self.sem_api.Grab(0, 0, 1024, 768, 0,
                                    save_path_filename)
        if ret_val == 0:
            return True
        else:
            self.error_state = 302
            self.error_cause = 'sem.save_frame: command failed'
            return False

    def get_wd(self):
        """Return current working distance in metres."""
        return float(self.sem_api.Get('AP_WD', 0)[1])

    def set_wd(self, target_wd):
        """Set working distance to target distance (in metres)."""
        variant = VARIANT(pythoncom.VT_R4, target_wd)
        ret_val = self.sem_api.Set('AP_WD', variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = 311
            self.error_cause = 'sem.set_wd: command failed'
            return False

    def get_stig_xy(self):
        """Return XY stigmator parameters in %, as a tuple """
        stig_x = self.sem_api.Get('AP_STIG_X', 0)[1]
        stig_y = self.sem_api.Get('AP_STIG_Y', 0)[1]
        return (float(stig_x), float(stig_y))

    def set_stig_xy(self, target_stig_x, target_stig_y):
        variant_x = VARIANT(pythoncom.VT_R4, target_stig_x)
        ret_val1 = self.sem_api.Set('AP_STIG_X', variant_x)[0]
        variant_y = VARIANT(pythoncom.VT_R4, target_stig_y)
        ret_val2 = self.sem_api.Set('AP_STIG_Y', variant_y)[0]
        if (ret_val1 == 0) and (ret_val2 == 0):
            return True
        else:
            self.error_state = 312
            self.error_cause = 'sem.set_stig_xy: command failed'
            return False

    def get_stig_x(self):
        return float(self.sem_api.Get('AP_STIG_X', 0)[1])

    def set_stig_x(self, target_stig_x):
        variant_x = VARIANT(pythoncom.VT_R4, target_stig_x)
        ret_val = self.sem_api.Set('AP_STIG_X', variant_x)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = 312
            self.error_cause = 'sem.set_stig_x: command failed'
            return False

    def get_stig_y(self):
        return float(self.sem_api.Get('AP_STIG_Y', 0)[1])

    def set_stig_y(self, target_stig_y):
        variant_y = VARIANT(pythoncom.VT_R4, target_stig_y)
        ret_val = self.sem_api.Set('AP_STIG_Y', variant_y)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = 312
            self.error_cause = 'sem.set_stig_y: command failed'
            return False

    def set_beam_blanking(self, should_be_blanked):
        if should_be_blanked:
            blank_variant = VARIANT(pythoncom.VT_R4, 1)
        else:
            blank_variant = VARIANT(pythoncom.VT_R4, 0)
        ret_val = self.sem_api.Set('DP_BEAM_BLANKING', blank_variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = 313
            self.error_cause = 'sem.set_beam_blanking: command failed'
            return False

    def run_autofocus(self):
        """Run ZEISS autofocus, break if it takes longer than 1 min."""
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        sleep(1)
        ret_val = self.sem_api.Execute('CMD_AUTO_FOCUS_FINE')
        timeout_counter = 0
        while self.sem_api.Get('DP_AUTO_FN_STATUS', 0)[1] == 'Busy':
            sleep(1)
            timeout_counter += 1
            if timeout_counter > 60:
                ret_val = 1
                break
        self.sem_api.Execute('CMD_FREEZE_ALL')
        # Error state is set in stack_acquisition.py when this function is
        # called via autofocus.py
        return (ret_val == 0)

    def run_autostig(self):
        """Run ZEISS autostig, break if it takes longer than 1 min."""
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        sleep(1)
        ret_val = self.sem_api.Execute('CMD_AUTO_STIG')
        timeout_counter = 0
        while self.sem_api.Get('DP_AUTO_FN_STATUS', 0)[1] == 'Busy':
            sleep(1)
            timeout_counter += 1
            if timeout_counter > 60:
                ret_val = 1
                break
        self.sem_api.Execute('CMD_FREEZE_ALL')
        # Error state is set in stack_acquisition.py when this function is
        # called via autofocus.py
        return (ret_val == 0)

    def run_autofocus_stig(self):
        """Run combined ZEISS autofocus and autostig, break if it takes
           longer than 1 min.
        """
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        sleep(1)
        ret_val = self.sem_api.Execute('CMD_FOCUS_STIG')
        timeout_counter = 0
        while self.sem_api.Get('DP_AUTO_FN_STATUS', 0)[1] == 'Busy':
            sleep(1)
            timeout_counter += 1
            if timeout_counter > 60:
                ret_val = 1
                break
        self.sem_api.Execute('CMD_FREEZE_ALL')
        # Error state is set in stack_acquisition.py when this function is
        # called via autofocus.py
        return (ret_val == 0)

    def get_stage_x(self):
        # Return in microns
        self.last_known_x = self.sem_api.GetStagePosition()[1] * 10**6
        return self.last_known_x

    def get_stage_y(self):
        self.last_known_y = self.sem_api.GetStagePosition()[2] * 10**6
        return self.last_known_y

    def get_stage_z(self):
        self.last_known_z = self.sem_api.GetStagePosition()[3] * 10**6
        return self.last_known_z

    def get_stage_xy(self):
        x, y = self.sem_api.GetStagePosition()[1:3]
        self.last_known_x, self.last_known_y = x * 10**6, y * 10**6
        return (self.last_known_x, self.last_known_y)

    def get_stage_xyz(self):
        x, y, z = self.sem_api.GetStagePosition()[1:4]
        self.last_known_x, self.last_known_y, self.last_known_z = (
            x * 10**6, y * 10**6, z * 10**6)
        return (self.last_known_x, self.last_known_y, self.last_known_z)

    def get_last_known_xy(self):
        return (self.last_known_x, self.last_known_y)

    def get_last_known_z(self):
        return self.last_known_z

    def move_stage_to_x(self, x):
        """Move stage to coordinate x, provided in microns"""
        x /= 10**6   # convert to metres
        y = self.get_stage_y() / 10**6
        z = self.get_stage_z() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.rotation, 0)
        # TODO: wait time
        while self.sem_api.Get('DP_STAGE_IS') == 'Busy':
            sleep(0.2)
        sleep(3)  # for testing purposes

    def move_stage_to_y(self, y):
        """Move stage to coordinate y, provided in microns"""
        y /= 10**6   # convert to metres
        x = self.get_stage_x() / 10**6
        z = self.get_stage_z() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.rotation, 0)
        # TODO: wait time
        while self.sem_api.Get('DP_STAGE_IS') == 'Busy':
            sleep(0.2)
        sleep(3)  # for testing purposes

    def move_stage_to_z(self, z):
        """Move stage to coordinate y, provided in microns"""
        z /= 10**6   # convert to metres
        x = self.get_stage_x() / 10**6
        y = self.get_stage_y() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.rotation, 0)
        # TODO: wait time
        while self.sem_api.Get('DP_STAGE_IS') == 'Busy':
            sleep(0.2)
        sleep(3)  # for testing purposes

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates x and y, provided in microns"""
        x, y = coordinates
        x /= 10**6   # convert to metres
        y /= 10**6
        z = self.get_stage_z() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.rotation, 0)
        # TODO: wait time
        while self.sem_api.Get('DP_STAGE_IS') == 'Busy':
            sleep(0.2)
        sleep(3)  # for testing purposes

    def get_stage_move_wait_interval(self):
        return self.stage_move_wait_interval

    def set_stage_move_wait_interval(self, wait_interval):
        self.stage_move_wait_interval = wait_interval
        self.cfg['sem']['stage_move_wait_interval'] = str(wait_interval)

    def get_motor_speed_calibration(self):
        return (self.motor_speed_x, self.motor_speed_y)

    def get_motor_limits(self):
        return self.motor_limits

    def get_stage_calibration(self):
        return self.stage_calibration

    def update_stage_calibration(self, eht):
        eht = int(eht * 1000)  # Dict keys in system config use volts, not kV
        success = True
        try:
            calibration_data = json.loads(
                self.syscfg['stage']['sem_calibration_data'])
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

            self.cfg['sem']['stage_scale_factor_x'] = str(params[0])
            self.cfg['sem']['stage_scale_factor_y'] = str(params[1])
            self.cfg['sem']['stage_rotation_angle_x'] = str(params[2])
            self.cfg['sem']['stage_rotation_angle_y'] = str(params[3])
            self.stage_calibration = params
        return success

    def show_about_box(self):
        self.sem_api.AboutBox()

    def get_error_state(self):
        return self.error_state

    def get_error_cause(self):
        return self.error_cause

    def reset_error_state(self):
        self.error_state = 0
        self.error_cause = ''

    def disconnect(self):
        ret_val = self.sem_api.ClosingControl()
        if ret_val == 0:
            log_msg = 'SEM: Disconnected from SmartSEM.'
        else:
            log_msg = 'SEM: ERROR disconnecting from SmartSEM.'
        return log_msg
