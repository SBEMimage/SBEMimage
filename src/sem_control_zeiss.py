# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module provides the commands to operate the SEM. Only the functions
that are actually required in SBEMimage have been implemented."""

from time import sleep

import json
import pythoncom
import win32com.client  # required to use CZEMApi.ocx (Carl Zeiss EM API)
from win32com.client import VARIANT  # required for API function calls

import utils
from utils import Error
from sem_control import SEM


class SEM_SmartSEM(SEM):
    """Implements all methods for remote control of ZEISS SEMs via the
    SmartSEM remote control API. Currently supported: Merlin, GeminiSEM,
    Ultra Plus, and Sigma."""

    # Variant conversions for passing values between Python and COM:
    # https://www.oreilly.com/library/view/python-programming-on/1565926218/ch12s03s06.html

    def __init__(self, config, sysconfig):
        """Load all settings and initialize remote connection to SmartSEM."""
        # Call __init__ from base class (which loads all settings from
        # config and sysconfig).
        super().__init__(config, sysconfig)
        if not self.simulation_mode:
            exception_msg = ''
            try:
                # Dispatch SmartSEM Remote API: CZEMApi.ocx must be registered
                # in the Windows registry ('CZ.EMApiCtrl.1').
                self.sem_api = win32com.client.Dispatch('CZ.EMApiCtrl.1')
                ret_val = self.sem_api.InitialiseRemoting()
            except Exception as e:
                ret_val = 1
                exception_msg = str(e)
            if ret_val != 0:   # In ZEISS API, response of '0' means success
                self.error_state = Error.smartsem_api
                self.error_info = (
                    f'sem.__init__: remote API control could not be '
                    f'initialised (ret_val: {ret_val}). {exception_msg}')
            elif self.use_sem_stage:
                # Read current SEM stage coordinates
                self.last_known_x, self.last_known_y, self.last_known_z = (
                    self.get_stage_xyz())
        else:
            self.sem_api = None

    def turn_eht_on(self):
        """Turn EHT (= high voltage) on. Return True if successful,
        otherwise False."""
        ret_val = self.sem_api.Execute('CMD_BEAM_ON')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.eht
            self.error_info = (
                f'sem.turn_eht_on: command failed (ret_val: {ret_val})')
            return False

    def turn_eht_off(self):
        """Turn EHT (= high voltage) off. Return True if successful,
        otherwise False."""
        ret_val = self.sem_api.Execute('CMD_EHT_OFF')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.eht
            self.error_info = (
                f'sem.turn_eht_off: command failed (ret_val: {ret_val})')
            return False

    def is_eht_on(self):
        """Return True if EHT is on."""
        return (self.sem_api.Get('DP_RUNUPSTATE', 0)[1] == 'Beam On')

    def is_eht_off(self):
        """Return True if EHT is off. This is not the same as "not is_eht_on()"
        because there are intermediate beam states between on and off."""
        return (self.sem_api.Get('DP_RUNUPSTATE', 0)[1] == 'EHT Off')

    def get_eht(self):
        """Return current SmartSEM EHT setting in kV."""
        return self.sem_api.Get('AP_MANUALKV', 0)[1] / 1000

    def set_eht(self, target_eht):
        """Save the target EHT (in kV) and set the EHT to this target value."""
        # Call method in parent class
        super().set_eht(target_eht)
        # target_eht given in kV
        variant = VARIANT(pythoncom.VT_R4, target_eht * 1000)
        ret_val = self.sem_api.Set('AP_MANUALKV', variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.eht
            self.error_info = (
                f'sem.set_eht: command failed (ret_val: {ret_val})')
            return False

    def has_vp(self):
        """Return True if VP (= Variable Pressure) is fitted."""
        if not self.simulation_mode:
            return "yes" in self.sem_api.Get('DP_VP_SYSTEM', 0)[1].lower()
        return False

    def is_hv_on(self):
        """Return True if HV (= High Vacuum) is on."""
        return "vacuum" in self.sem_api.Get('DP_VAC_MODE', 0)[1].lower()

    def is_vp_on(self):
        """Return True if VP is on."""
        return "variable" in self.sem_api.Get('DP_VAC_MODE', 0)[1].lower()

    def get_chamber_pressure(self):
        """Read current chamber pressure from SmartSEM."""
        response = self.sem_api.Get('AP_CHAMBER_PRESSURE', 0)
        return response[1]

    def get_vp_target(self):
        """Read current VP target pressure from SmartSEM."""
        response = self.sem_api.Get('AP_HP_TARGET', 0)
        return response[1]

    def set_hv(self):
        """Set HV."""
        ret_val = self.sem_api.Execute('CMD_GOTO_HV')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.hp_hv
            self.error_info = (
                f'sem.set_hv: command failed (ret_val: {ret_val})')
            return False

    def set_vp(self):
        """Set VP."""
        ret_val = self.sem_api.Execute('CMD_GOTO_VP')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.hp_hv
            self.error_info = (
                f'sem.set_vp: command failed (ret_val: {ret_val})')
            return False

    def set_vp_target(self, target_pressure):
        """Set the VP target pressure."""
        variant = VARIANT(pythoncom.VT_R4, target_pressure)
        ret_val = self.sem_api.Set('AP_HP_TARGET', variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.hp_hv
            self.error_info = (
                f'sem.set_vp_target: command failed (ret_val: {ret_val})')
            return False

    def has_fcc(self):
        """Return True if FCC (= Focal Charge Compensator) is fitted."""
        if not self.simulation_mode:
            return "yes" in self.sem_api.Get('DP_CAPCC_FITTED', 0)[1].lower()
        return False

    def is_fcc_on(self):
        """Return True if FCC is on."""
        return "yes" in self.sem_api.Get('DP_CAPCC_INUSE', 0)[1].lower()

    def is_fcc_off(self):
        """Return True if FCC is off."""
        return "no" in self.sem_api.Get('DP_CAPCC_INUSE', 0)[1].lower()

    def get_fcc_level(self):
        """Read current FCC pressure (0-100) from SmartSEM."""
        response = self.sem_api.Get('AP_CC_PRESSURE', 0)
        return response[1]

    def turn_fcc_on(self):
        """Turn FCC on."""
        ret_val = self.sem_api.Execute('CMD_CC_IN')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.fcc
            self.error_info = (
                f'sem.turn_fcc_on: command failed (ret_val: {ret_val})')
            return False

    def turn_fcc_off(self):
        """Turn FCC off."""
        ret_val = self.sem_api.Execute('CMD_CC_OUT')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.fcc
            self.error_info = (
                f'sem.turn_fcc_off: command failed (ret_val: {ret_val})')
            return False

    def set_fcc_level(self, target_fcc_level):
        """Save the target FCC (0-100) and set the FCC to this target value."""
        variant = VARIANT(pythoncom.VT_R4, target_fcc_level)
        ret_val = self.sem_api.Set('AP_CC_PRESSURE', variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.fcc
            self.error_info = (
                f'sem.set_fcc_level: command failed (ret_val: {ret_val})')
            return False

    def get_beam_current(self):
        """Read beam current (in pA) from SmartSEM."""
        return int(round(self.sem_api.Get('AP_IPROBE', 0)[1] * 10**12))

    def set_beam_current(self, target_current):
        """Save the target beam current (in pA) and set the SEM's beam to this
        target current."""
        # Call method in parent class
        super().set_beam_current(target_current)
        # target_current given in pA
        variant = VARIANT(pythoncom.VT_R4, target_current * 10**(-12))
        ret_val = self.sem_api.Set('AP_IPROBE', variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.beam_current
            self.error_info = (
                f'sem.set_beam_current: command failed (ret_val: {ret_val})')
            return False

    def get_aperture_size(self):
        """Read aperture size (in μm) from SmartSEM."""
        return round(self.sem_api.Get('AP_APERTURESIZE', 0)[1] * 10**6, 1)

    def set_aperture_size(self, aperture_size_index):
        """Save the aperture size (in μm) and set the SEM's beam to this
        aperture size."""
        # Call method in parent class
        super().set_aperture_size(aperture_size_index)
        # aperture_size given in μm
        selector_variant = VARIANT(pythoncom.VT_R4, aperture_size_index)
        ret_val = self.sem_api.Set('DP_APERTURE', selector_variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.aperture_size
            self.error_info = (
                f'sem.set_aperture_size: command failed (ret_val: {ret_val})')
            return False

    def apply_beam_settings(self):
        """Set the SEM to the target EHT voltage and beam current."""
        ret_val1 = self.set_eht(self.target_eht)
        ret_val2 = self.set_beam_current(self.target_beam_current)
        ret_val3 = self.set_aperture_size(self.APERTURE_SIZE.index(self.target_aperture_size))
        return (ret_val1 and ret_val2 and ret_val3)

    def apply_grab_settings(self):
        """Set the SEM to the current grab settings."""
        self.apply_frame_settings(
            self.grab_frame_size_selector,
            self.grab_pixel_size,
            self.grab_dwell_time)

    def apply_frame_settings(self, frame_size_selector, pixel_size, dwell_time):
        """Apply the frame settings (frame size, pixel size and dwell time)."""
        # The pixel size determines the magnification
        mag = int(self.MAG_PX_SIZE_FACTOR /
                  (self.STORE_RES[frame_size_selector][0] * pixel_size))
        ret_val1 = self.set_mag(mag)                        # Sets SEM mag
        ret_val2 = self.set_dwell_time(dwell_time)          # Sets SEM scan rate
        ret_val3 = self.set_frame_size(frame_size_selector) # Sets SEM store res

        # Load SmartSEM cycle time for current settings
        scan_speed = self.DWELL_TIME.index(dwell_time)
        # 0.3 s and 0.8 s are safety margins
        self.current_cycle_time = (
            self.CYCLE_TIME[frame_size_selector][scan_speed] + 0.3)
        if self.current_cycle_time < 0.8:
            self.current_cycle_time = 0.8
        return (ret_val1 and ret_val2 and ret_val3)

    def get_frame_size_selector(self):
        """Read the current store resolution from the SEM and return the
        corresponding frame size selector.
        """
        ret_val = self.sem_api.Get('DP_IMAGE_STORE', 0)[1]
        try:
            frame_size = [int(x) for x in ret_val.split('*')]
            frame_size_selector = self.STORE_RES.index(frame_size)
        except:
            frame_size_selector = 0  # default fallback
        return frame_size_selector

    def set_frame_size_and_freeze(self, frame_size_selector):
        """Set SEM to frame size specified by frame_size_selector and freeze
        the frame. Only works well on Merlin/Gemini. OBSOLETE.
        """
        freeze_variant = VARIANT(pythoncom.VT_R4, 2)  # 2 = freeze on command
        self.sem_api.Set('DP_FREEZE_ON', freeze_variant)
        selector_variant = VARIANT(pythoncom.VT_R4, frame_size_selector)
        ret_val = self.sem_api.Set('DP_IMAGE_STORE', selector_variant)[0]
        # Changing this parameter causes an 'unfreeze' command.
        # Freeze again, immediately:
        self.sem_api.Execute('CMD_FREEZE_ALL')
        # Change back to 'freeze on end of frame' (0)
        freeze_variant = VARIANT(pythoncom.VT_R4, 0)
        self.sem_api.Set('DP_FREEZE_ON', freeze_variant)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.frame_size
            self.error_info = (
                f'sem.set_frame_size: command failed (ret_val: {ret_val})')
            return False

    def set_frame_size(self, frame_size_selector):
        """Set SEM to frame size specified by frame_size_selector."""
        selector_variant = VARIANT(pythoncom.VT_R4, frame_size_selector)
        ret_val = self.sem_api.Set('DP_IMAGE_STORE', selector_variant)[0]
        # Note: Changing this parameter causes an 'unfreeze' command.
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.frame_size
            self.error_info = (
                f'sem.set_frame_size: command failed (ret_val: {ret_val})')
            return False

    def get_mag(self):
        """Read current magnification from SEM."""
        return self.sem_api.Get('AP_MAG', 0)[1]

    def set_mag(self, target_mag):
        """Set SEM magnification to target_mag."""
        ret_val = self.sem_api.Set('AP_MAG', str(target_mag))[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.magnification
            self.error_info = (
                f'sem.set_mag: command failed (ret_val: {ret_val})')
            return False

    def get_pixel_size(self):
        """Read current magnification from the SEM and convert it into
        pixel size in nm.
        """
        current_mag = self.get_mag()
        current_frame_size_selector = self.get_frame_size_selector()
        return self.MAG_PX_SIZE_FACTOR / (current_mag
                   * self.STORE_RES[current_frame_size_selector][0])

    def set_pixel_size(self, pixel_size):
        """Set SEM to the magnification corresponding to pixel_size."""
        mag = int(self.MAG_PX_SIZE_FACTOR /
                  (self.STORE_RES[frame_size_selector][0] * pixel_size))
        return self.set_mag(mag)

    def get_scan_rate(self):
        """Read the current scan rate from the SEM"""
        return int(self.sem_api.Get('DP_SCANRATE', 0)[1])

    def set_scan_rate(self, scan_rate_selector):
        """Set SEM to pixel scan rate specified by scan_rate_selector."""
        ret_val = self.sem_api.Execute('CMD_SCANRATE'
                                       + str(scan_rate_selector))
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.scan_rate
            self.error_info = (
                f'sem.set_scan_rate: command failed (ret_val: {ret_val})')
            return False

    def set_dwell_time(self, dwell_time):
        """Convert dwell time into scan rate and call self.set_scan_rate()."""
        return self.set_scan_rate(self.DWELL_TIME.index(dwell_time))

    def set_scan_rotation(self, angle):
        """Set the scan rotation angle (in degrees). Enable scan rotation
        for angles > 0."""
        if angle > 0:
            enable_variant = VARIANT(pythoncom.VT_R4, 1)
        else:
            enable_variant = VARIANT(pythoncom.VT_R4, 0)
        ret_val1 = self.sem_api.Set('DP_SCAN_ROT', enable_variant)[0]
        angle_variant = VARIANT(pythoncom.VT_R4, angle)
        ret_val2 = self.sem_api.Set('AP_SCANROTATION', angle_variant)[0]
        sleep(0.5)  # how long of a delay is necessary?
        return ret_val1 == 0 and ret_val2 == 0

    def acquire_frame(self, save_path_filename, extra_delay=0):
        """Acquire a full frame and save it to save_path_filename.
        All imaging parameters must be applied BEFORE calling this function.
        To avoid grabbing the image before it is acquired completely, an
        additional waiting period after the cycle time (extra_delay, in seconds)
        may be necessary. The delay specified in syscfg (self.DEFAULT_DELAY)
        is added by default for cycle times > 0.5 s."""
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        self.sem_api.Execute('CMD_FREEZE_ALL') # Assume 'freeze on end of frame'

        self.additional_cycle_time = extra_delay
        if self.current_cycle_time > 0.5:
            self.additional_cycle_time += self.DEFAULT_DELAY

        sleep(self.current_cycle_time + self.additional_cycle_time)
        # This sleep interval could be used to carry out other operations in
        # parallel while waiting for the new image.
        # Wait longer if necessary before grabbing image
        while self.sem_api.Get('DP_FROZEN')[1] == 'Live':
            sleep(0.1)
            self.additional_cycle_time += 0.1

        ret_val = self.sem_api.Grab(0, 0, 1024, 768, 0,
                                    save_path_filename)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.grab_image
            self.error_info = (
                f'sem.acquire_frame: command failed (ret_val: {ret_val})')
            return False

    def save_frame(self, save_path_filename):
        """Save the frame currently displayed in SmartSEM."""
        ret_val = self.sem_api.Grab(0, 0, 1024, 768, 0,
                                    save_path_filename)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.grab_image
            self.error_info = (
                f'sem.save_frame: command failed (ret_val: {ret_val})')
            return False

    def get_wd(self):
        """Return current working distance in metres."""
        return float(self.sem_api.Get('AP_WD', 0)[1])

    def set_wd(self, target_wd):
        """Set working distance to target working distance (in metres)."""
        variant = VARIANT(pythoncom.VT_R4, target_wd)
        ret_val = self.sem_api.Set('AP_WD', variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.working_distance
            self.error_info = (
                f'sem.set_wd: command failed (ret_val: {ret_val})')
            return False

    def get_stig_xy(self):
        """Return XY stigmation parameters in %, as a tuple."""
        stig_x = self.sem_api.Get('AP_STIG_X', 0)[1]
        stig_y = self.sem_api.Get('AP_STIG_Y', 0)[1]
        return (float(stig_x), float(stig_y))

    def set_stig_xy(self, target_stig_x, target_stig_y):
        """Set X and Y stigmation parameters (in %)."""
        variant_x = VARIANT(pythoncom.VT_R4, target_stig_x)
        ret_val1 = self.sem_api.Set('AP_STIG_X', variant_x)[0]
        variant_y = VARIANT(pythoncom.VT_R4, target_stig_y)
        ret_val2 = self.sem_api.Set('AP_STIG_Y', variant_y)[0]
        if (ret_val1 == 0) and (ret_val2 == 0):
            return True
        else:
            self.error_state = Error.stig_xy
            self.error_info = (
                f'sem.set_stig_xy: command failed (ret_vals: {ret_val1}, '
                f'{ret_val1})')
            return False

    def get_stig_x(self):
        """Read X stigmation parameter (in %) from SEM."""
        return float(self.sem_api.Get('AP_STIG_X', 0)[1])

    def set_stig_x(self, target_stig_x):
        """Set X stigmation parameter (in %)."""
        variant_x = VARIANT(pythoncom.VT_R4, target_stig_x)
        ret_val = self.sem_api.Set('AP_STIG_X', variant_x)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.stig_xy
            self.error_info = (
                f'sem.set_stig_x: command failed (ret_val: {ret_val})')
            return False

    def get_stig_y(self):
        """Read Y stigmation parameter (in %) from SEM."""
        return float(self.sem_api.Get('AP_STIG_Y', 0)[1])

    def set_stig_y(self, target_stig_y):
        """Set Y stigmation parameter (in %)."""
        variant_y = VARIANT(pythoncom.VT_R4, target_stig_y)
        ret_val = self.sem_api.Set('AP_STIG_Y', variant_y)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.stig_xy
            self.error_info = (
                f'sem.set_stig_y: command failed (ret_val: {ret_val})')
            return False

    def set_beam_blanking(self, enable_blanking):
        """Enable beam blanking if enable_blanking == True."""
        if enable_blanking:
            blank_variant = VARIANT(pythoncom.VT_R4, 1)
        else:
            blank_variant = VARIANT(pythoncom.VT_R4, 0)
        ret_val = self.sem_api.Set('DP_BEAM_BLANKING', blank_variant)[0]
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.beam_blanking
            self.error_info = (
                f'sem.set_beam_blanking: command failed (ret_val: {ret_val})')
            return False

    def run_autofocus(self):
        """Run ZEISS autofocus, break if it takes longer than 1 min."""
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        sleep(1)
        ret_val = self.sem_api.Execute('CMD_AUTO_FOCUS_FINE')
        sleep(1)
        timeout_counter = 0
        while self.sem_api.Get('DP_AUTO_FUNCTION', 0)[1] == 'Focus':
            sleep(1)
            timeout_counter += 1
            if timeout_counter > 60:
                ret_val = 1
                break
        if not self.magc_mode:
            self.sem_api.Execute('CMD_FREEZE_ALL')
        # Error state is set in acquisition.py when this function is
        # called via autofocus.py
        return (ret_val == 0)

    def run_autostig(self):
        """Run ZEISS autostig, break if it takes longer than 1 min."""
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        sleep(1)
        ret_val = self.sem_api.Execute('CMD_AUTO_STIG')
        sleep(1)
        timeout_counter = 0
        while self.sem_api.Get('DP_AUTO_FN_STATUS', 0)[1] == 'Busy':
            sleep(1)
            timeout_counter += 1
            if timeout_counter > 60:
                ret_val = 1
                break
        if not self.magc_mode:
            self.sem_api.Execute('CMD_FREEZE_ALL')
        # Error state is set in acquisition.py when this function is
        # called via autofocus.py
        return (ret_val == 0)

    def run_autofocus_stig(self):
        """Run combined ZEISS autofocus and autostig, break if it takes
        longer than 1 min."""
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        sleep(1)
        ret_val = self.sem_api.Execute('CMD_FOCUS_STIG')
        sleep(1)
        timeout_counter = 0
        while self.sem_api.Get('DP_AUTO_FN_STATUS', 0)[1] == 'Busy':
            sleep(1)
            timeout_counter += 1
            if timeout_counter > 60:
                ret_val = 1
                break
        self.sem_api.Execute('CMD_FREEZE_ALL')
        # Error state is set in acquisition.py when this function is
        # called via autofocus.py
        return (ret_val == 0)

    def get_stage_x(self):
        """Read X stage position (in micrometres) from SEM."""
        self.last_known_x = self.sem_api.GetStagePosition()[1] * 10**6
        return self.last_known_x

    def get_stage_y(self):
        """Read Y stage position (in micrometres) from SEM."""
        self.last_known_y = self.sem_api.GetStagePosition()[2] * 10**6
        return self.last_known_y

    def get_stage_z(self):
        """Read Z stage position (in micrometres) from SEM."""
        self.last_known_z = self.sem_api.GetStagePosition()[3] * 10**6
        return self.last_known_z

    def get_stage_xy(self):
        """Read XY stage position (in micrometres) from SEM."""
        x, y = self.sem_api.GetStagePosition()[1:3]
        self.last_known_x, self.last_known_y = x * 10**6, y * 10**6
        return self.last_known_x, self.last_known_y

    def get_stage_xyz(self):
        """Read XYZ stage position (in micrometres) from SEM."""
        x, y, z = self.sem_api.GetStagePosition()[1:4]
        self.last_known_x, self.last_known_y, self.last_known_z = (
            x * 10**6, y * 10**6, z * 10**6)
        return self.last_known_x, self.last_known_y, self.last_known_z

    def move_stage_to_x(self, x):
        """Move stage to coordinate x, provided in microns"""
        x /= 10**6   # convert to metres
        y = self.get_stage_y() / 10**6
        z = self.get_stage_z() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.stage_rotation, 0)
        while self.sem_api.Get('DP_STAGE_IS') == 'Busy':
            sleep(0.2)
        sleep(self.stage_move_wait_interval)
        self.last_known_x = self.sem_api.GetStagePosition()[1] * 10**6

    def move_stage_to_y(self, y):
        """Move stage to coordinate y, provided in microns"""
        y /= 10**6   # convert to metres
        x = self.get_stage_x() / 10**6
        z = self.get_stage_z() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.stage_rotation, 0)
        while self.sem_api.Get('DP_STAGE_IS') == 'Busy':
            sleep(0.2)
        sleep(self.stage_move_wait_interval)
        self.last_known_y = self.sem_api.GetStagePosition()[2] * 10**6

    def move_stage_to_z(self, z):
        """Move stage to coordinate z, provided in microns"""
        z /= 10**6   # convert to metres
        x = self.get_stage_x() / 10**6
        y = self.get_stage_y() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.stage_rotation, 0)
        while self.sem_api.Get('DP_STAGE_IS') == 'Busy':
            sleep(0.2)
        sleep(self.stage_move_wait_interval)
        self.last_known_z = self.sem_api.GetStagePosition()[3] * 10**6

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates x and y, provided in microns"""
        x, y = coordinates
        x /= 10**6   # convert to metres
        y /= 10**6
        z = self.get_stage_z() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.stage_rotation, 0)
        while self.sem_api.Get('DP_STAGE_IS') == 'Busy':
            sleep(0.2)
        sleep(self.stage_move_wait_interval)
        new_x, new_y = self.sem_api.GetStagePosition()[1:3]
        self.last_known_x, self.last_known_y = new_x * 10**6, new_y * 10**6

    def show_about_box(self):
        """Display the SmartSEM Remote API About Dialog Box."""
        self.sem_api.AboutBox()

    def disconnect(self):
        ret_val = self.sem_api.ClosingControl()
        if ret_val == 0:
            utils.log_info('SEM', 'Disconnected from SmartSEM.')
            return True
        else:
            utils.log_error('SEM', f'ERROR disconnecting from SmartSEM (ret_val: {ret_val}).')
            return False
