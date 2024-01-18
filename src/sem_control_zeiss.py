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

import json
import os
import sys
from qtpy.QtWidgets import QMessageBox
from time import sleep

try:
    import comtypes
    import comtypes.client as cc
    import pythoncom
    import win32com.client  # required to use CZEMApi.ocx (Carl Zeiss EM API)
    from win32com.client import VARIANT  # required for API function calls
except:
    pass

import constants
from constants import Error
from image_io import imread, imwrite
from sem_control import SEM
import utils


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

    def sem_get(self, key):
        try:
            return self.sem_api.Get(key, 0)[1]
        except Exception as e:
            utils.log_error(f"Unable to get SEM.{key} error: {e}")
        return ""

    def sem_set(self, key, value, convert_variant=True):
        try:
            if convert_variant:
                value = VARIANT(pythoncom.VT_R4, value)
            return self.sem_api.Set(key, value)[0]
        except Exception as e:
            utils.log_error(f"Unable to set SEM.{key} error: {e}")
        return 0

    def sem_execute(self, key):
        try:
            return self.sem_api.Execute(key)
        except Exception as e:
            utils.log_error(f"Unable to execute SEM.{key} error: {e}")
        return 0

    def sem_stage_busy(self):
        try:
            return self.sem_api.Get('DP_STAGE_IS')[1] == 'Busy'
        except Exception as e:
            utils.log_error(f"Unable to get SEM.DP_STAGE_IS error: {e}")
        return False

    def turn_eht_on(self):
        """Turn EHT (= high voltage) on. Return True if successful,
        otherwise False."""
        ret_val = self.sem_execute('CMD_BEAM_ON')
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
        ret_val = self.sem_execute('CMD_EHT_OFF')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.eht
            self.error_info = (
                f'sem.turn_eht_off: command failed (ret_val: {ret_val})')
            return False

    def is_eht_on(self):
        """Return True if EHT is on."""
        return self.sem_get('DP_RUNUPSTATE') == 'Beam On'

    def is_eht_off(self):
        """Return True if EHT is off. This is not the same as "not is_eht_on()"
        because there are intermediate beam states between on and off."""
        return self.sem_get('DP_RUNUPSTATE') == 'EHT Off'

    def get_eht(self):
        """Return current SmartSEM EHT setting in kV."""
        return self.sem_get('AP_MANUALKV') / 1000

    def set_eht(self, target_eht):
        """Save the target EHT (in kV) and set the EHT to this target value."""
        # Call method in parent class
        super().set_eht(target_eht)
        # target_eht given in kV
        ret_val = self.sem_set('AP_MANUALKV', target_eht * 1000)
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
            return "yes" in self.sem_get('DP_VP_SYSTEM').lower()
        return False

    def is_hv_on(self):
        """Return True if HV (= High Vacuum) is on."""
        return "vacuum" in self.sem_get('DP_VAC_MODE').lower()

    def is_vp_on(self):
        """Return True if VP is on."""
        return "variable" in self.sem_get('DP_VAC_MODE').lower()

    def get_chamber_pressure(self):
        """Read current chamber pressure from SmartSEM."""
        return self.sem_get('AP_CHAMBER_PRESSURE')

    def get_vp_target(self):
        """Read current VP target pressure from SmartSEM."""
        return self.sem_get('AP_HP_TARGET')

    def set_hv(self):
        """Set HV."""
        ret_val = self.sem_execute('CMD_GOTO_HV')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.hp_hv
            self.error_info = (
                f'sem.set_hv: command failed (ret_val: {ret_val})')
            return False

    def set_vp(self):
        """Set VP."""
        ret_val = self.sem_execute('CMD_GOTO_VP')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.hp_hv
            self.error_info = (
                f'sem.set_vp: command failed (ret_val: {ret_val})')
            return False

    def set_vp_target(self, target_pressure):
        """Set the VP target pressure."""
        ret_val = self.sem_set('AP_HP_TARGET', target_pressure)
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
            return "yes" in self.sem_get('DP_CAPCC_FITTED').lower()
        return False

    def is_fcc_on(self):
        """Return True if FCC is on."""
        return "on" in self.sem_get('DP_CC_STATUS').lower()

    def is_fcc_off(self):
        """Return True if FCC is off."""
        return "off" in self.sem_get('DP_CC_STATUS').lower()

    def get_fcc_level(self):
        """Read current FCC pressure (0-100) from SmartSEM."""
        return self.sem_get('AP_CC_PRESSURE')

    def turn_fcc_on(self):
        """Turn FCC on."""
        ret_val = self.sem_execute('CMD_CC_IN')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.fcc
            self.error_info = (
                f'sem.turn_fcc_on: command failed (ret_val: {ret_val})')
            return False

    def turn_fcc_off(self):
        """Turn FCC off."""
        ret_val = self.sem_execute('CMD_CC_OUT')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.fcc
            self.error_info = (
                f'sem.turn_fcc_off: command failed (ret_val: {ret_val})')
            return False

    def set_fcc_level(self, target_fcc_level):
        """Save the target FCC (0-100) and set the FCC to this target value."""
        ret_val = self.sem_set('AP_CC_PRESSURE', target_fcc_level)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.fcc
            self.error_info = (
                f'sem.set_fcc_level: command failed (ret_val: {ret_val})')
            return False

    def set_mode_normal(self):
        """Sets mode NORMAL (not split, not reduced, not emission)"""
        ret_val = self.sem_execute('CMD_MODE_NORMAL')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.mode_normal
            self.error_info = (
                f'sem.mode_normal: command failed (ret_val: {ret_val})')
            return False

    def get_beam_current(self):
        """Read beam current (in pA) from SmartSEM."""
        return int(round(self.sem_get('AP_IPROBE') * 10**12))

    def set_beam_current(self, target_current):
        """Save the target beam current (in pA) and set the SEM's beam to this
        target current."""
        # Call method in parent class
        super().set_beam_current(target_current)
        # target_current given in pA
        ret_val = self.sem_set('AP_IPROBE', target_current * 10**(-12))
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.beam_current
            self.error_info = (
                f'sem.set_beam_current: command failed (ret_val: {ret_val})')
            return False

    def get_high_current(self):
        """Read high current mode from SmartSEM."""
        if self.HAS_HIGH_CURRENT:
            return "on" in self.sem_get('DP_HIGH_CURRENT').lower()

    def set_high_current(self, target_high_current):
        """Save the target high current mode and set the SEM value."""
        # Call method in parent class
        super().set_high_current(target_high_current)
        if self.HAS_HIGH_CURRENT:
            ret_val = self.sem_set('DP_HIGH_CURRENT', int(self.target_high_current))
            if ret_val == 0:
                return True
            else:
                self.error_state = Error.high_current
                self.error_info = (
                    f'sem.set_high_current: command failed (ret_val: {ret_val})')
                return False
        return True

    def get_aperture_size(self):
        """Read aperture size (in μm) from SmartSEM."""
        return round(self.sem_get('AP_APERTURESIZE') * 10**6, 1)

    def set_aperture_size(self, aperture_size_index):
        """Save the aperture size (in μm) and set the SEM's beam to this
        aperture size."""
        # Call method in parent class
        super().set_aperture_size(aperture_size_index)
        # aperture_size given in μm
        ret_val = self.sem_set('DP_APERTURE', aperture_size_index)
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
        ret_val4 = self.set_high_current(self.target_high_current)
        return ret_val1 and ret_val2 and ret_val3 and ret_val4

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
        return ret_val1 and ret_val2 and ret_val3

    def get_frame_size_selector(self):
        """Read the current store resolution from the SEM and return the
        corresponding frame size selector.
        """
        ret_val = self.sem_get('DP_IMAGE_STORE')
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
        self.sem_set('DP_FREEZE_ON', 2)  # 2 = freeze on command
        ret_val = self.sem_set('DP_IMAGE_STORE', frame_size_selector)
        # Changing this parameter causes an 'unfreeze' command.
        # Freeze again, immediately:
        self.sem_execute('CMD_FREEZE_ALL')
        # Change back to 'freeze on end of frame' (0)
        self.sem_set('DP_FREEZE_ON', 0)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.frame_size
            self.error_info = (
                f'sem.set_frame_size: command failed (ret_val: {ret_val})')
            return False

    def set_frame_size(self, frame_size_selector):
        """Set SEM to frame size specified by frame_size_selector."""
        ret_val = self.sem_set('DP_IMAGE_STORE', frame_size_selector)
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
        return self.sem_get('AP_MAG')

    def set_mag(self, target_mag):
        """Set SEM magnification to target_mag."""
        ret_val = self.sem_set('AP_MAG', str(target_mag), convert_variant=False)
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
        frame_size_selector = self.get_frame_size_selector()
        mag = int(self.MAG_PX_SIZE_FACTOR /
                  (self.STORE_RES[frame_size_selector][0] * pixel_size))
        return self.set_mag(mag)

    def get_scan_rate(self):
        """Read the current scan rate from the SEM"""
        return int(self.sem_get('DP_SCANRATE'))

    def set_scan_rate(self, scan_rate_selector):
        """Set SEM to pixel scan rate specified by scan_rate_selector."""
        ret_val = self.sem_execute('CMD_SCANRATE'
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
        ret_val1 = self.sem_set('DP_SCAN_ROT', int(angle > 0))
        ret_val2 = self.sem_set('AP_SCANROTATION', angle)
        sleep(0.5)  # how long of a delay is necessary?
        return ret_val1 == 0 and ret_val2 == 0

    def acquire_frame(self, save_path_filename, extra_delay=0):
        """Acquire a full frame and save it to save_path_filename.
        All imaging parameters must be applied BEFORE calling this function.
        To avoid grabbing the image before it is acquired completely, an
        additional waiting period after the cycle time (extra_delay, in seconds)
        may be necessary. The delay specified in syscfg (self.DEFAULT_DELAY)
        is added by default for cycle times > 0.5 s."""

        if self.simulation_mode:
            self.error_state = Error.grab_image
            self.error_info = f'sem.save_frame: simulation mode'
            return False

        self.sem_execute('CMD_UNFREEZE_ALL')

        if (
            self.magc_mode
            and self.device_name.lower() in [
                'zeiss merlin',
                'zeiss sigma',
                ]
        ):
            sleep(0.5)

        self.sem_execute('CMD_FREEZE_ALL') # Assume 'freeze on end of frame'

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

        return self.save_frame(save_path_filename)

    def save_frame(self, save_path_filename):
        """Save the frame currently displayed in SmartSEM."""

        if self.simulation_mode:
            self.error_state = Error.grab_image
            self.error_info = f'sem.save_frame: simulation mode'
            return False

        # for (ome).tif write to temp file, then rewrite with metadata
        ext = os.path.splitext(save_path_filename)[1].lower()
        rewrite_file = ext in ['.tif', '.tiff']
        if rewrite_file:
            grab_filename = os.path.join(os.path.dirname(save_path_filename), 'grab' + constants.TEMP_IMAGE_FORMAT)
        else:
            grab_filename = save_path_filename
        ret_val = self.sem_api.Grab(0, 0, 1024, 768, 0, grab_filename)
        if ret_val == 0:
            if rewrite_file:
                metadata = {
                    'pixel_size': [self.grab_pixel_size, self.grab_pixel_size],
                    'position': [self.last_known_x, self.last_known_y]
                }
                image = imread(grab_filename)
                imwrite(save_path_filename, image, metadata)
            return True
        else:
            self.error_state = Error.grab_image
            self.error_info = (
                f'sem.save_frame: command failed (ret_val: {ret_val})')
            return False

    def get_wd(self):
        """Return current working distance in metres."""
        return float(self.sem_get('AP_WD'))

    def set_wd(self, target_wd):
        """Set working distance to target working distance (in metres)."""
        ret_val = self.sem_set('AP_WD', target_wd)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.working_distance
            self.error_info = (
                f'sem.set_wd: command failed (ret_val: {ret_val})')
            return False

    def get_stig_xy(self):
        """Return XY stigmation parameters in %, as a tuple."""
        stig_x = self.sem_get('AP_STIG_X')
        stig_y = self.sem_get('AP_STIG_Y')
        return float(stig_x), float(stig_y)

    def set_stig_xy(self, target_stig_x, target_stig_y):
        """Set X and Y stigmation parameters (in %)."""
        ret_val1 = self.sem_set('AP_STIG_X', target_stig_x)
        ret_val2 = self.sem_set('AP_STIG_Y', target_stig_y)
        if ret_val1 == 0 and ret_val2 == 0:
            return True
        else:
            self.error_state = Error.stig_xy
            self.error_info = (
                f'sem.set_stig_xy: command failed (ret_vals: {ret_val1}, '
                f'{ret_val1})')
            return False

    def get_stig_x(self):
        """Read X stigmation parameter (in %) from SEM."""
        return float(self.sem_get('AP_STIG_X'))

    def set_stig_x(self, target_stig_x):
        """Set X stigmation parameter (in %)."""
        ret_val = self.sem_set('AP_STIG_X', target_stig_x)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.stig_xy
            self.error_info = (
                f'sem.set_stig_x: command failed (ret_val: {ret_val})')
            return False

    def get_stig_y(self):
        """Read Y stigmation parameter (in %) from SEM."""
        return float(self.sem_get('AP_STIG_Y'))

    def set_stig_y(self, target_stig_y):
        """Set Y stigmation parameter (in %)."""
        ret_val = self.sem_set('AP_STIG_Y', target_stig_y)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.stig_xy
            self.error_info = (
                f'sem.set_stig_y: command failed (ret_val: {ret_val})')
            return False

    def set_beam_blanking(self, enable_blanking):
        """Enable beam blanking if enable_blanking == True."""
        ret_val = self.sem_set('DP_BEAM_BLANKING', int(enable_blanking))
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.beam_blanking
            self.error_info = (
                f'sem.set_beam_blanking: command failed (ret_val: {ret_val})')
            return False

    def run_autofocus(self):
        """Run ZEISS autofocus, break if it takes longer than 1 min."""
        self.sem_execute('CMD_UNFREEZE_ALL')
        sleep(1)
        ret_val = self.sem_execute('CMD_AUTO_FOCUS_FINE')
        sleep(1)
        timeout_counter = 0
        while self.sem_get('DP_AUTO_FUNCTION') == 'Focus':
            sleep(1)
            timeout_counter += 1
            if timeout_counter > 60:
                ret_val = 1
                break
        if not self.magc_mode:
            self.sem_execute('CMD_FREEZE_ALL')
        # Error state is set in acquisition.py when this function is
        # called via autofocus.py
        return ret_val == 0

    def run_autostig(self):
        """Run ZEISS autostig, break if it takes longer than 1 min."""
        self.sem_execute('CMD_UNFREEZE_ALL')
        sleep(1)
        ret_val = self.sem_execute('CMD_AUTO_STIG')
        sleep(1)
        timeout_counter = 0
        while self.sem_get('DP_AUTO_FN_STATUS') == 'Busy':
            sleep(1)
            timeout_counter += 1
            if timeout_counter > 60:
                ret_val = 1
                break
        if not self.magc_mode:
            self.sem_execute('CMD_FREEZE_ALL')
        # Error state is set in acquisition.py when this function is
        # called via autofocus.py
        return ret_val == 0

    def run_autofocus_stig(self):
        """Run combined ZEISS autofocus and autostig, break if it takes
        longer than 1 min."""
        self.sem_execute('CMD_UNFREEZE_ALL')
        sleep(1)
        ret_val = self.sem_execute('CMD_FOCUS_STIG')
        sleep(1)
        timeout_counter = 0
        while self.sem_get('DP_AUTO_FN_STATUS') == 'Busy':
            sleep(1)
            timeout_counter += 1
            if timeout_counter > 60:
                ret_val = 1
                break
        self.sem_execute('CMD_FREEZE_ALL')
        # Error state is set in acquisition.py when this function is
        # called via autofocus.py
        return ret_val == 0

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

    def get_stage_xyztr(self):
        """Read XYZ stage position (in micrometres) and tilt and
        rotation angles (in degree) from SEM."""
        x, y, z, t, r = self.sem_api.GetStagePosition()[1:6]
        self.last_known_x, self.last_known_y, self.last_known_z = (
            x * 10**6, y * 10**6, z * 10**6)
        return self.last_known_x, self.last_known_y, self.last_known_z, t, r

    def get_stage_t(self):
        """Read stage tilt (in degrees) from SEM"""
        x, y, z, t, r = self.sem_api.GetStagePosition()[1:6]
        return t

    def get_stage_r(self):
        """Read stage rotation (in degrees) from SEM"""
        x, y, z, t, r = self.sem_api.GetStagePosition()[1:6]
        return r

    def get_stage_tr(self):
        """Read tilt (degrees) and stage rotation (degrees) from SEM
        as a tuple"""
        x, y, z, t, r = self.sem_api.GetStagePosition()[1:6]
        return t,r

    def move_stage_to_x(self, x):
        """Move stage to coordinate x, provided in microns"""
        x /= 10**6   # convert to metres
        y = self.get_stage_y() / 10**6
        z = self.get_stage_z() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.stage_rotation, 0)
        while self.sem_stage_busy():
            sleep(self.stage_move_check_interval)
        sleep(self.stage_move_wait_interval)
        self.last_known_x = self.sem_api.GetStagePosition()[1] * 10**6

    def move_stage_to_y(self, y):
        """Move stage to coordinate y, provided in microns"""
        y /= 10**6   # convert to metres
        x = self.get_stage_x() / 10**6
        z = self.get_stage_z() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.stage_rotation, 0)
        while self.sem_stage_busy():
            sleep(self.stage_move_check_interval)
        sleep(self.stage_move_wait_interval)
        self.last_known_y = self.sem_api.GetStagePosition()[2] * 10**6

    def move_stage_to_z(self, z):
        """Move stage to coordinate z, provided in microns"""
        z /= 10**6   # convert to metres
        x = self.get_stage_x() / 10**6
        y = self.get_stage_y() / 10**6
        self.sem_api.MoveStage(x, y, z, 0, self.stage_rotation, 0)
        while self.sem_stage_busy():
            sleep(self.stage_move_check_interval)
        sleep(self.stage_move_wait_interval)
        self.last_known_z = self.sem_api.GetStagePosition()[3] * 10**6

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates x and y, provided in microns"""
        x, y = coordinates
        x /= 10**6   # convert to metres
        y /= 10**6
        z = self.get_stage_z() / 10**6

        # adding a magc_mode as precaution
        # should this not be the standard way to make a stage movement:
        # keep the other parameters constant by reading them first?
        if self.magc_mode:
            t,r = self.get_stage_tr()
        else:
            r = self.stage_rotation
            t = 0

        self.sem_api.MoveStage(x, y, z, t, r, 0)

        while self.sem_stage_busy():
            sleep(self.stage_move_check_interval)
        sleep(self.stage_move_wait_interval)
        new_x, new_y = self.sem_api.GetStagePosition()[1:3]
        self.last_known_x, self.last_known_y = new_x * 10**6, new_y * 10**6

    def move_stage_to_r(self, new_r, no_wait=False):
        """Move stage to rotation angle r (in degrees)"""
        x, y, z, t, r = self.sem_api.GetStagePosition()[1:6]
        self.sem_api.MoveStage(x, y, z, t, new_r, 0)
        if no_wait:
            sleep(self.stage_move_wait_interval)
            return
        while self.sem_stage_busy():
            sleep(self.stage_move_check_interval)
        sleep(self.stage_move_wait_interval)

    def move_stage_delta_r(self, delta_r, no_wait=False):
        """Rotate stage by angle r (in degrees)"""
        x, y, z, t, r = self.sem_api.GetStagePosition()[1:6]
        self.sem_api.MoveStage(x, y, z, t, r + delta_r, 0)
        if no_wait:
            sleep(self.stage_move_wait_interval)
            return
        while self.sem_stage_busy():
            sleep(self.stage_move_check_interval)
        sleep(self.stage_move_wait_interval)

    def move_stage_to_xyzt(self, x, y, z, t):
        """Move stage to coordinates x and y, z (in microns) and tilt angle t (in degrees)."""
        x /= 10**6   # convert to metres
        y /= 10**6
        z /= 10**6
        self.sem_api.MoveStage(x, y, z, t, self.stage_rotation, 0)
        while self.sem_stage_busy():
            sleep(self.stage_move_check_interval)
        sleep(self.stage_move_wait_interval)

    def move_stage_to_xyztr(self, x, y, z, t, r):
        """Move stage to coordinates x and y, z (in microns), tilt and rotation angles t, r (in degrees)."""
        x /= 10**6   # convert to metres
        y /= 10**6
        z /= 10**6
        self.sem_api.MoveStage(x, y, z, t, r, 0)
        while self.sem_stage_busy():
            sleep(self.stage_move_check_interval)
        sleep(self.stage_move_wait_interval)

    def show_about_box(self):
        """Display the SmartSEM Remote API About Dialog Box."""
        self.sem_api.AboutBox()

    def disconnect(self):
        if not self.simulation_mode:
            ret_val = self.sem_api.ClosingControl()
        else:
            ret_val = 0

        if ret_val == 0:
            utils.log_info('SEM', 'Disconnected from SmartSEM.')
            return True
        else:
            utils.log_error('SEM', f'ERROR disconnecting from SmartSEM (ret_val: {ret_val}).')
            return False


class SEM_MultiSEM(SEM):
    """Implements all methods for remote control of ZEISS MultiSEM via the
    mSEMService API."""

    def __init__(self, config, sysconfig):
        """Load all settings and initialize remote connection to MultiSEM."""
        # do not use  __init__ from base class (which loads all settings from
        # config and sysconfig) because some single beam parameters do not
        # apply to MultiSEM
        # TODO: Better use base class constructor and then ignore single-beam
        # parameters and define additional parameters if necessary

        super().__init__(config, sysconfig)
        self.cfg = config  # user/project configuration (ConfigParser object)
        self.syscfg = sysconfig  # system configuration
        self.load_system_constants()
        # Last known SEM stage positions in micrometres
        self.last_known_x = None
        self.last_known_y = None
        self.last_known_z = None
        # self.error_state: see list in utils.py; no error -> error_state = Error.none
        # self.error_info: further description / exception error message
        self.error_state = Error.none
        self.error_info = ''
        # Use device selection from system configuration
        self.cfg['sem']['device'] = self.syscfg['device']['sem']
        if self.cfg['sem']['device'] not in self.recognized_devices:
            self.cfg['sem']['device'] = 'NOT RECOGNIZED'
        self.device_name = self.cfg['sem']['device']
        # In simulation mode, there is no connection to the SEM hardware
        self.simulation_mode = (
            self.cfg['sys']['simulation_mode'].lower() == 'true')
        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')
        # self.use_sem_stage: True if microtome not used
        self.use_sem_stage = (
            self.cfg['sys']['use_microtome'].lower() == 'false')
        if not self.use_sem_stage:
            QMessageBox.critical(self,
                'MultiSEM device error:'
                '\nuse_microtome is set to True in the configuration file'
                '\n Please set use_microtome to False in the configuration file'
                '\n then start again SBEMimage.',
                QMessageBox.Ok)
            print('Error in the configuration file:'
              '\n use_microtome must be set to False with the MultiSEM.\n')
            sys.exit()

        # The target EHT (= high voltage, in kV) and beam current (in pA)
        # are (as implemented at the moment in SBEMimage) global settings for
        # any given acquisition, whereas dwell time, pixel size and frame size
        # can automatically change between overviews, grids and single frames.
        self.target_eht = float(self.cfg['sem']['eht'])
        self.target_beam_current = int(float(self.cfg['sem']['beam_current']))
        # self.stage_rotation: rotation angle of SEM stage (0° by default)
        self.stage_rotation = 0
        # 'Grab frame' settings: these are the settings for acquiring single
        # frames with the SEM using the 'Grab frame' feature in SBEMimage.
        # dwell time provided in microseconds, pixel size in nanometres
        self.grab_dwell_time = float(self.cfg['sem']['grab_frame_dwell_time'])
        self.grab_pixel_size = float(self.cfg['sem']['grab_frame_pixel_size'])

        # no use of this variable in MultiSEM
        # keep this variable for now, may be deleted later
        self.grab_frame_size_selector = 0

        # The cycle time is total duration to acquire a full frame.
        # self.current_cycle_time will be set (in seconds) the first time when
        # self.apply_frame_settings() is called.
        self.current_cycle_time = 0
        self.additional_cycle_time = 0
        # self.stage_move_wait_interval: the time in seconds SBEMimage pauses
        # after each stage move before acquiring the next image. This delay
        # allows potential vibrations of the stage to subside.
        self.stage_move_wait_interval = float(
            self.cfg['sem']['stage_move_wait_interval'])
        # self.stage_limits: range of the SEM XY motors in micrometres
        # [x_min, x_max, y_min, y_max]
        self.stage_limits = json.loads(
            self.syscfg['stage']['sem_stage_limits'])
        # speed in microns/second of X and Y stage motors
        self.motor_speed_x, self.motor_speed_y = (
            json.loads(self.syscfg['stage']['sem_motor_speed']))
        # Back-scatter detector (BSD) contrast, brightness, and bias voltage
        self.bsd_contrast = float(self.cfg['sem']['bsd_contrast'])
        self.bsd_brightness = float(self.cfg['sem']['bsd_brightness'])
        self.bsd_bias = float(self.cfg['sem']['bsd_bias'])
        # self.auto_beam_blank: currently unused
        self.auto_beam_blank = (
            self.cfg['sem']['auto_beam_blank'].lower() == 'true')

        if not self.simulation_mode:
            exception_msg = ''
            try:
                # The API must have been installed with the instructions in the
                # mSEMService API
                tlb_id = comtypes.GUID(
                    '{b361561d-01e4-4251-b6de-0440d12ce6bd}')
                cc.GetModule((tlb_id, 1, 0))
                import comtypes.gen.ZeissmSEMWrapper as ZeissCOMLib
                self.sem_api = cc.CreateObject(
                    'ZeissmSEMWrapper.Commands',
                    None, None,
                    ZeissCOMLib.ICommands)
                ret_val = self.sem_api.Execute('CMD_INITIALIZE')
            except Exception as e:
                ret_val = 1
                exception_msg = str(e)
            if ret_val != 0:   # In mSEMService API, '0' means success
                self.error_state = Error.smartsem_api
                self.error_info = (
                    f'sem.__init__: remote API control could not be '
                    f'initalized (ret_val: {ret_val}). {exception_msg}')
            elif self.use_sem_stage:
                # Read current SEM stage coordinates
                self.last_known_x, self.last_known_y, self.last_known_z = (
                    self.get_stage_xyz())

    def load_system_constants(self):
        """Load all SEM-related constants from system configuration."""
        # self.STORE_RES: available store resolutions (= frame size in pixels)
        self.STORE_RES = json.loads(self.syscfg['sem']['store_res'])
        # self.DWELL_TIME: available dwell times in microseconds
        self.DWELL_TIME = json.loads(self.syscfg['sem']['dwell_time'])
        # Cycle times: Duration of scanning one full frame, depends on
        # scan rate and frame size:
        # cycle_time[frame_size_selector][scan_rate] -> duration in sec
        cycle_time = json.loads(self.syscfg['sem']['cycle_time'])
        # Convert string keys to int
        self.CYCLE_TIME = {int(k): v for k, v in cycle_time.items()}
        # self.DEFAULT_DELAY: delay in seconds after cycle time before
        # image is grabbed by SBEMimage
        self.DEFAULT_DELAY = float(self.syscfg['sem']['delay_after_cycle_time'])
        # self.MAG_PX_SIZE_FACTOR is needed to calculate the magnification
        # as a function of frame resolution and pixel size (in nm):
        # M = MAG_PX_SIZE_FACTOR / (STORE_RES_X * PX_SIZE)
        self.MAG_PX_SIZE_FACTOR = int(self.syscfg['sem']['mag_px_size_factor'])

    def save_to_cfg(self):
        """Save current values of attributes to config and sysconfig objects."""
        self.syscfg['sem']['mag_px_size_factor'] = str(self.MAG_PX_SIZE_FACTOR)
        self.cfg['sem']['stage_min_x'] = str(self.stage_limits[0])
        self.cfg['sem']['stage_max_x'] = str(self.stage_limits[1])
        self.cfg['sem']['stage_min_y'] = str(self.stage_limits[2])
        self.cfg['sem']['stage_max_y'] = str(self.stage_limits[3])
        self.syscfg['stage']['sem_stage_limits'] = str(self.stage_limits)
        self.syscfg['stage']['sem_motor_speed'] = str(
            [self.motor_speed_x, self.motor_speed_y])
        self.cfg['sem']['motor_speed_x'] = str(self.motor_speed_x)
        self.cfg['sem']['motor_speed_y'] = str(self.motor_speed_y)
        self.cfg['sem']['stage_move_wait_interval'] = str(
            self.stage_move_wait_interval)
        self.cfg['sem']['eht'] = '{0:.2f}'.format(self.target_eht)
        self.cfg['sem']['beam_current'] = str(int(self.target_beam_current))
        self.cfg['sem']['grab_frame_dwell_time'] = str(self.grab_dwell_time)
        self.cfg['sem']['grab_frame_pixel_size'] = '{0:.1f}'.format(
            self.grab_pixel_size)
        self.cfg['sem']['grab_frame_size_selector'] = str(
            self.grab_frame_size_selector)
        self.cfg['sem']['grab_frame_size_xy'] = str(
            self.STORE_RES[self.grab_frame_size_selector])
        self.cfg['sem']['bsd_contrast'] = str(self.bsd_contrast)
        self.cfg['sem']['bsd_brightness'] = str(self.bsd_brightness)
        self.cfg['sem']['bsd_bias'] = str(self.bsd_bias)
        self.cfg['sem']['auto_beam_blank'] = str(self.auto_beam_blank)

    def turn_eht_on(self):
        """Turn EHT (= high voltage) on. Return True if successful,
        otherwise False."""
        # first check current beam state
        is_beam_on = self.sem_api.Get_ReturnTypeDouble('DP_IS_BEAM_ON')
        if is_beam_on == 1:
            return True
        elif is_beam_on == 0.5:
            QMessageBox.warning(self,
                'The current state of the beam cannot be determined '
                '(probably currently ramping up or down).'
                '\n\nPlease try to turn on again in 30 seconds.',
                QMessageBox.Ok)
            return False
        # turn on if beam currently off
        elif is_beam_on == 0:
            ret_val = self.sem_api.Execute('CMD_BEAM_ON')
            if ret_val == -1:
                return True # this case should not happen
            elif ret_val == 0:
                sleep(1)
                wait_beam_on = self.sem_api.Execute('CMD_WAIT_BEAM_ON')
                if wait_beam_on != 0:
                    self.error_state = Error.eht
                    self.error_info = (
                        f'sem.turn_eht_on: command failed (wait_beam_on: {wait_beam_on})')
                    QMessageBox.critical(self,
                        'Failure to turn the beam on',
                        QMessageBox.Ok)
                    return False
                else:
                    return True

    def turn_eht_off(self):
        """Turn EHT (= high voltage) off. Return True if successful,
        otherwise False."""
        ret_val = self.sem_api.Execute('CMD_BEAM_OFF')
        if ret_val == -1:
            return True
        elif ret_val == 0:
            sleep(1)
            wait_beam_off = self.sem_api.Execute('CMD_WAIT_BEAM_OFF')
            if wait_beam_off != 0:
                self.error_state = Error.eht
                self.error_info = (
                    f'sem.turn_eht_off: command failed (wait_beam_off: {wait_beam_off})')
                QMessageBox.critical(self,
                    'Failure to turn the beam off',
                    QMessageBox.Ok)
                return False
            else:
                return True
        else:
            self.error_state = Error.eht
            self.error_info = (
                f'sem.turn_eht_off: command failed (ret_val: {ret_val})')
            QMessageBox.critical(self,
                'Failure to turn the beam on',
                QMessageBox.Ok)
            return False

    def is_eht_on(self):
        """Return True if EHT is on."""
        is_beam_on = self.sem_api.Get_ReturnTypeDouble('DP_IS_BEAM_ON')
        if is_beam_on == 1:
            return True
        else:
            return False

    def is_eht_off(self):
        """Return True if EHT is off. This is not the same as "not is_eht_on()"
        because there are intermediate beam states between on and off."""
        is_beam_on = self.sem_api.Get_ReturnTypeDouble('DP_IS_BEAM_ON')
        if is_beam_on == 0:
            return True
        else:
            # is_beam_on could be equal to 0.5 if indeterminate
            # this case also returns False. One should not proceed
            # if there is an ambiguous answer
            return False

    def get_eht(self):
        """Return current echuck voltage in kV."""
        return (self.sem_api
                .Get_ReturnTypeDouble('AP_ECHUCK_VOLTAGE_MONITOR') / 1000)

    def set_eht(self, target_eht):
        """Save the target echuck voltage (in kV) and set the EHT to this target value."""
        # Call method in parent class
        super().set_eht(target_eht)
        # target_eht given in kV
        ret_val = self.sem_api.Set_PassedTypeDouble(
            'AP_ECHUCK_TARGET_VOLTAGE',
            target_eht * 1000)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.eht
            self.error_info = (
                f'sem.set_eht: command failed (ret_val: {ret_val})')
            return False

    def get_beam_current(self):
        """Read the current of the echuck source (in pA)."""
        return int(round(self.sem_api.Get_ReturnTypeDouble('AP_ECHUCK_CURRENT_MONITOR') * 1000))

    def set_beam_current(self, target_current):
        """This command does not exist in the MultiSEM."""
        return NotImplementedError

    def apply_beam_settings(self):
        """Set the target echuck voltage.
        Function kept from the single beam implementation
        for compatibility."""
        ret_val1 = self.set_eht(self.target_eht)
        # ret_val2 = self.set_beam_current(self.target_beam_current)
        return ret_val1 == 0

    def has_brightness(self):
        """Return True if supports brightness control."""
        return True

    def has_contrast(self):
        """Return True if supports contrast control."""
        return True

    def get_brightness(self):
        """Read SmartSEM brightness (0-1)."""
        return self.sem_api.Get_ReturnTypeDouble('AP_BRIGHTNESS') / 100

    def get_contrast(self):
        """Read SmartSEM contrast (0-1)."""
        return self.sem_api.Get_ReturnTypeDouble('AP_CONTRAST') / 100

    def set_brightness(self, brightness):
        """Write SmartSEM brightness (0-1)."""
        ret_val = self.sem_api.Set_ReturnTypeDouble(
            'AP_BRIGHTNESS',
            brightness * 100)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.brightness_contrast
            self.error_info = (
                f'sem.set_brightness: command failed (ret_val: {ret_val})'
            )
            return False

    def set_contrast(self, contrast):
        """Write SmartSEM contrast (0-1)."""
        ret_val = self.sem_api.Set_ReturnTypeDouble(
            'AP_CONTRAST',
            contrast * 100)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.brightness_contrast
            self.error_info = (
                f'sem.set_contrast: command failed (ret_val: {ret_val})'
            )
            return False

    def apply_grab_settings(self):
        """Set the SEM to the current grab settings."""
        self.apply_frame_settings(
            self.grab_frame_size_selector,
            self.grab_pixel_size,
            self.grab_dwell_time)

    def apply_frame_settings(self, frame_size_selector, pixel_size, dwell_time):
        """Apply the frame settings (pixel size and dwell time).
        Frame Size is kept around for compatibility"""
        ret_val3 = self.set_dwell_time(dwell_time)
        # Load cycle time for current settings
        scan_speed = self.DWELL_TIME.index(dwell_time)
        # 0.3 s and 0.8 s are safety margins
        self.current_cycle_time = (
            self.CYCLE_TIME[frame_size_selector][scan_speed] + 0.3)
        if self.current_cycle_time < 0.8:
            self.current_cycle_time = 0.8
        return ret_val3

    def set_frame_size(self, frame_size_selector):
        """There is no frame size setting in MultiSEM.
        Kept here for compatibility only."""
        return True

    def get_mag(self):
        """Mag kept to fake value 1000 in MultiSEM"""
        return 1000

    def set_mag(self, target_mag):
        """Mag kept to fake value 1000 in MultiSEM"""
        return True

    def set_scan_rate(self, scan_rate_selector):
        """Set scan rate specified by scan_rate_selector."""
        ret_val = (self.sem_api
            .Set_PassedTypeDouble(
                'DP_SCANRATE',
                scan_rate_selector))
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
        """Set the scan rotation angle (in degrees)."""
        # set angle in [-180:180]
        angle = angle % 360
        if angle > 180:
            angle = angle - 360
        ret_val1 = self.sem_api.Set_PassedTypeDouble(
            'AP_SCANROTATION',
            angle)
        sleep(0.5)  # how long of a delay is necessary?
        return ret_val1 == 0

    def get_wd(self):
        """In MultiSEM WD is kept to a fake value"""
        return 1.4 * 1e-3

    def set_wd(self, target_wd):
        """In MultiSEM WD is not used."""
        return True

    def get_stig_xy(self):
        """Return XY stigmation parameters in %, as a tuple."""
        stig_x = self.sem_api.Get_ReturnTypeDouble('AP_STIG_X')
        stig_y = self.sem_api.Get_ReturnTypeDouble('AP_STIG_Y')
        return float(stig_x), float(stig_y)

    def set_stig_xy(self, target_stig_x, target_stig_y):
        """Set X and Y stigmation parameters (in %)."""
        ret_val1 = self.sem_api.Set_ReturnTypeDouble(
            'AP_STIG_X',
            target_stig_x)
        ret_val2 = self.sem_api.Set_ReturnTypeDouble(
            'AP_STIG_Y',
            target_stig_y)
        if ret_val1 == 0 and ret_val2 == 0:
            return True
        else:
            self.error_state = Error.stig_xy
            self.error_info = (
                f'sem.set_stig_xy: command failed (ret_vals: {ret_val1}, '
                f'{ret_val2})')
            return False

    def get_stig_x(self):
        """Read X stigmation parameter (in %) from SEM."""
        return float(self.sem_api.Get_ReturnTypeDouble('AP_STIG_X'))

    def set_stig_x(self, target_stig_x):
        """Set X stigmation parameter (in %)."""
        ret_val = self.sem_api.Set_ReturnTypeDouble(
            'AP_STIG_X',
            target_stig_x)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.stig_xy
            self.error_info = (
                f'sem.set_stig_x: command failed (ret_val: {ret_val})')
            return False

    def get_stig_y(self):
        """Read Y stigmation parameter (in %) from SEM."""
        return float(self.sem_api.Get_ReturnTypeDouble('AP_STIG_Y'))

    def set_stig_y(self, target_stig_y):
        """Set Y stigmation parameter (in %)."""
        ret_val = self.sem_api.Set_ReturnTypeDouble(
            'AP_STIG_Y',
            target_stig_y)
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.stig_xy
            self.error_info = (
                f'sem.set_stig_y: command failed (ret_val: {ret_val})')
            return False

    def get_stage_x(self):
        """Read X stage position (in micrometres) from SEM."""
        self.last_known_x = self.sem_api.Get_ReturnTypeDouble('AP_STAGE_AT_X')
        return self.last_known_x

    def get_stage_y(self):
        """Read Y stage position (in micrometres) from SEM."""
        self.last_known_x = self.sem_api.Get_ReturnTypeDouble('AP_STAGE_AT_Y')
        return self.last_known_y

    def get_stage_z(self):
        """Read Z stage position (in micrometres) from SEM."""
        self.last_known_x = self.sem_api.Get_ReturnTypeDouble('AP_STAGE_AT_Z')
        return self.last_known_z

    def get_stage_xy(self):
        """Read XY stage position (in micrometres) from SEM."""
        return self.get_stage_x(), self.get_stage_y()

    def get_stage_xyz(self):
        """Read XYZ stage position (in micrometres) from SEM."""
        return self.get_stage_x(), self.get_stage_y(), self.get_stage_z()

    def move_stage_to_x(self, x):
        """Move stage to coordinate x, provided in microns"""
        move_x_success = self.sem_api.Set_ReturnTypeDouble(
            'AP_STAGE_GOTO_X',
            x)
        if move_x_success != 0:
            self.error_state = Error.stage_xy
            self.error_info = (
                f'sem.move_stage_to_x: command failed '
                f'(move_x_success: {move_x_success})')
            return False

        # wait for stage settling
        stage_settled = self.sem_api.Execute('CMD_WAIT_STAGE_SETTLED')

        if stage_settled != 0:
            self.error_state = Error.stage_xy
            self.error_info = (
                f'sem.move_stage_to_x: command failed '
                f'(stage_settled: {stage_settled})')
            return False
        # update self.last_known_x
        self.get_stage_x()

    def move_stage_to_y(self, y):
        """Move stage to coordinate y, provided in microns"""
        move_y_success = self.sem_api.Set_ReturnTypeDouble(
            'AP_STAGE_GOTO_Y',
            y)
        if move_y_success != 0:
            self.error_state = Error.stage_xy
            self.error_info = (
                f'sem.move_stage_to_y: command failed '
                f'(move_y_success: {move_y_success})')
            return False

        # wait for stage settling
        stage_settled = self.sem_api.Execute('CMD_WAIT_STAGE_SETTLED')

        if stage_settled != 0:
            self.error_state = Error.stage_xy
            self.error_info = (
                f'sem.move_stage_to_y: command failed '
                f'(stage_settled: {stage_settled})')
            return False
        # update self.last_known_y
        self.get_stage_y()

    def move_stage_to_z(self, z):
        """Move stage to coordinate z, provided in microns"""
        move_z_success = self.sem_api.Set_ReturnTypeDouble(
            'AP_STAGE_GOTO_Z',
            z)
        if move_z_success != 0:
            self.error_state = Error.stage_z_move
            self.error_info = (
                f'sem.move_stage_to_z: command failed '
                f'(move_z_success: {move_z_success})')
            return False

        # wait for stage settling
        stage_settled = self.sem_api.Execute('CMD_WAIT_STAGE_SETTLED')

        if stage_settled != 0:
            self.error_state = Error.stage_z_move
            self.error_info = (
                f'sem.move_stage_to_z: command failed '
                f'(stage_settled: {stage_settled})')
            return False
        # update self.last_known_z
        self.get_stage_z()

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates x and y, provided in microns"""
        x, y = coordinates
        move_x_success = self.sem_api.Set_ReturnTypeDouble(
            'AP_STAGE_GOTO_X',
            x)
        move_y_success = self.sem_api.Set_ReturnTypeDouble(
            'AP_STAGE_GOTO_Y',
            y)

        if move_x_success != 0 or move_y_success != 0:
            self.error_state = Error.stage_xy
            self.error_info = (
                f'sem.move_stage_to_xy: command failed '
                f'\n(move_x_success: {move_x_success}) '
                f'\n(move_y_success: {move_y_success})')
            return False

        # wait for stage settling
        stage_settled = self.sem_api.Execute('CMD_WAIT_STAGE_SETTLED')

        if stage_settled != 0:
            self.error_state = Error.stage_xy
            self.error_info = (
                f'sem.move_stage_to_xy: command failed '
                f'(stage_settled: {stage_settled})')
            return False
        # update self.last_known_x and self.last_known_x
        self.get_stage_x()
        self.get_stage_y()

    def disconnect(self):
        log_msg = 'MultiSEM: No function for API closing implemented.'
        return log_msg

    def check_system_sanity(self):
        system_sanity = self.sem_api.Execute('CMD_CHECK_SYSTEM_SANITY')
        if system_sanity == 0:
            return True
        elif system_sanity == -101:
            self.error_state = Error.multisem_beam_control
            self.error_info = (
                f'sem.check_system_sanity: command failed. '
                f'Beam control not possible. Check HV and vacuum '
                f'(system_sanity: {system_sanity})')
            return False
        elif system_sanity == -102:
            self.error_state = Error.multisem_imaging
            self.error_info = (
                f'sem.check_system_sanity: command failed. '
                f'Imaging not possible. Make sure '
                f'Image Acquisition PCs are connected. '
                f'(system_sanity: {system_sanity})')
            return False
        elif system_sanity == -103:
            self.error_state = Error.multisem_alignment
            self.error_info = (
                f'sem.check_system_sanity: command failed. '
                f'Auto alignment is not possible. '
                f'Check configuration of matlab webservice. '
                f'(system_sanity: {system_sanity})')
            return False
        else:
            return False

    def create_metadata_thumbnails(self):
        ret_val = self.sem_api.Execute('CMD_EXPERIMENT_FINISHED')
        if ret_val == 0:
            return True
        else:
            self.error_state = Error.multisem_failed_to_write
            self.error_info = (
                f'sem.create_metadata_thumbnails: command failed. '
                f'(ret_val: {ret_val})')
            return False

    # def set_beam_blanking(self, enable_blanking):
    # def acquire_frame(self, save_path_filename, extra_delay=0):
    # def save_frame(self, save_path_filename):
    # def get_wd(self):
    # def set_wd(self, target_wd):
    # def run_autofocus(self):
    # def run_autostig(self):
    # def run_autofocus_stig(self):


# ------------ additional MultiSEM functions not present in single beam machines -------------
    # def acquire_frame_mFov(self, save_path_filename, extra_delay=0):
    # '''Acquire mFov'''

    # def acquire_mFOV(self):
    # def acquire_sFOV(self):


        # need for an unfreeze?
        # DP_IMAGE_LOCATION
        # STR_COORDINATES_FILENAME
        # STR_CHANGE_PATH_OF_IMAGE_RECORDS
        # STR_CHANGE_PATH_OF_META_RECORDS

        # self.sem_api.Execute('CMD_TRIGGER_ACQUISITION')

        # Execute('CMD_WAIT_ACQUISITION_COMPLETE')
        # Execute('CMD_WAIT_SCAN_COMPLETE')