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
from collections import deque
from typing import List

from utils import Error

import pythoncom
import win32com.client  # required to use CZEMApi.ocx (Carl Zeiss EM API)
from win32com.client import VARIANT  # required for API function calls
import comtypes.client as cc


class SEM:
    """Base class for remote SEM control. Implements minimum parameter handling.
    Unimplemented methods raise a NotImplementedError - they must be implemented
    in child classes."""

    def __init__(self, config, sysconfig):
        """Initialize SEM base class."""
        self.cfg = config  # user/project configuration (ConfigParser object)
        self.syscfg = sysconfig  # system configuration
        self.load_system_constants()
        # Last known SEM stage positions in micrometres
        self.last_known_x = None
        self.last_known_y = None
        self.last_known_z = None
        # self.error_state: see list in utils.py; no error -> error_state = 0
        # self.error_info: further description / exception error message
        self.error_state = Error.none
        self.error_info = ''
        # Check if specified device is recognized
        recognized_devices = json.loads(self.syscfg['device']['sem_recognized'])
        # Use device selection from system configuration
        self.cfg['sem']['device'] = self.syscfg['device']['sem']
        if self.cfg['sem']['device'] not in recognized_devices:
            self.cfg['sem']['device'] = 'NOT RECOGNIZED'
        self.device_name = self.cfg['sem']['device']
        # IP address and port to communicate with SEM
        self.ip_address = self.syscfg['device']['sem_ip_address']
        if not self.ip_address:
            self.ip_address = None
        port_str = self.syscfg['device']['sem_port']
        try:
            self.port = int(port_str)
        except ValueError:
            self.port = None
        # In simulation mode, there is no connection to the SEM hardware
        self.simulation_mode = (
            self.cfg['sys']['simulation_mode'].lower() == 'true')
        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')
        # self.use_sem_stage: True if microtome is not used or if katana
        # microtome or GCIB are used (but only for XY in that case)
        self.use_sem_stage = (
            self.cfg['sys']['use_microtome'].lower() == 'false'
            or (self.cfg['sys']['use_microtome'].lower() == 'true'
                and self.syscfg['device']['microtome']
                in ['ConnectomX katana', 'GCIB']))
        # The target EHT (= high voltage, in kV) and beam current (in pA)
        # are (as implemented at the moment in SBEMimage) global settings for
        # any given acquisition, whereas dwell time, pixel size and frame size
        # can automatically change between overviews, grids and single frames.
        self.target_eht = float(self.cfg['sem']['eht'])
        self.target_beam_current = int(float(self.cfg['sem']['beam_current']))
        self.target_aperture_size = float(self.cfg['sem']['aperture_size'])
        self.target_high_current = False
        # self.stage_rotation: rotation angle of SEM stage (0° by default)
        self.stage_rotation = 0
        # 'Grab frame' settings: these are the settings for acquiring single
        # frames with the SEM using the 'Grab frame' feature in SBEMimage.
        # dwell time provided in microseconds, pixel size in nanometres
        if self.cfg['sem']['grab_frame_dwell_time_selector'] == 'None':
            self.grab_dwell_time_selector = self.DWELL_TIME_DEFAULT_INDEX
        else:
            self.grab_dwell_time_selector = int(
                self.cfg['sem']['grab_frame_dwell_time_selector'])
        if self.cfg['sem']['grab_frame_dwell_time'] == 'None':
            self.grab_dwell_time = self.DWELL_TIME[self.grab_dwell_time_selector]
        else:
            self.grab_dwell_time = float(self.cfg['sem']['grab_frame_dwell_time'])
        self.grab_pixel_size = float(self.cfg['sem']['grab_frame_pixel_size'])
        if self.cfg['sem']['grab_frame_size_selector'] == 'None':
            self.grab_frame_size_selector = self.STORE_RES_DEFAULT_INDEX_TILE
        else:
            self.grab_frame_size_selector = int(
                self.cfg['sem']['grab_frame_size_selector'])
        # Bit depth selector (0: 8 bit [default]; 1: 16 bit). Selects the
        # image bit depth to be used for acquisition.
        self.bit_depth_selector = 0
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
        self.stage_move_check_interval = float(
            self.cfg['sem']['stage_move_check_interval'])
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
        # SEM stage motor tolerances
        self.xy_tolerance = float(
            self.syscfg['stage']['sem_xy_tolerance'])
        self.z_tolerance = float(
            self.syscfg['stage']['sem_z_tolerance'])
        # Motor diagnostics
        self.total_xyz_move_counter = json.loads(
            self.syscfg['stage']['sem_xyz_move_counter'])
        self.slow_xy_move_counter = int(
            self.syscfg['stage']['sem_slow_xy_move_counter'])
        self.failed_xyz_move_counter = json.loads(
            self.syscfg['stage']['sem_failed_xyz_move_counter'])
        # Maintenance moves
        self.use_maintenance_moves = (
            self.syscfg['stage']['sem_use_maintenance_moves'].lower() == 'true')
        self.maintenance_move_interval = int(
            self.syscfg['stage']['sem_maintenance_move_interval'])
        # Deques for last 200 moves (0 = ok; 1 = warning)
        self.slow_xy_move_warnings = deque(maxlen=200)
        self.failed_x_move_warnings = deque(maxlen=200)
        self.failed_y_move_warnings = deque(maxlen=200)
        self.failed_z_move_warnings = deque(maxlen=200)

    def __str__(self):
        return self.device_name

    def load_system_constants(self):
        """Load all SEM-related constants from system configuration."""
        # self.BEAM_CURRENT_MODES: available beam current modes
        self.BEAM_CURRENT_MODES = json.loads(self.syscfg['sem']['beam_current_modes'])
        self.BEAM_CURRENT_MODE = json.loads(self.syscfg['sem']['beam_current_mode'])
        # self.HAS_HIGH_CURRENT: if has high current mode
        self.HAS_HIGH_CURRENT = bool(self.syscfg['sem']['has_high_current'])
        # self.STORE_RES: available store resolutions (= frame size in pixels)
        self.STORE_RES = json.loads(self.syscfg['sem']['store_res'])
        # self.STORE_RES_DEFAULT_INDEX_TILE: default store resolution for new grids and grabbing tiles
        self.STORE_RES_DEFAULT_INDEX_TILE = int(self.syscfg['sem']['store_res_default_index_tile'])
        # self.STORE_RES_DEFAULT_INDEX_OV: default store resolution for OVs
        self.STORE_RES_DEFAULT_INDEX_OV = int(self.syscfg['sem']['store_res_default_index_ov'])
        # self.STORE_RES_DEFAULT_INDEX_STUB_OV: default store resolution for stub OV tiles
        self.STORE_RES_DEFAULT_INDEX_STUB_OV = int(self.syscfg['sem']['store_res_default_index_stub_ov'])
        # self.DWELL_TIME: available dwell times in microseconds
        self.DWELL_TIME = json.loads(self.syscfg['sem']['dwell_time'])
        # self.DWELL_TIME_DEFAULT_INDEX: default dwell time
        self.DWELL_TIME_DEFAULT_INDEX = int(self.syscfg['sem']['dwell_time_default_index'])
        # self.APERTURE_SIZE: available aperture sizes in microns
        self.APERTURE_SIZE = json.loads(self.syscfg['sem']['aperture_size'])
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
        self.cfg['sem']['stage_move_check_interval'] = str(
            self.stage_move_check_interval)
        self.cfg['sem']['eht'] = '{0:.2f}'.format(self.target_eht)
        self.cfg['sem']['beam_current'] = str(int(self.target_beam_current))
        self.cfg['sem']['aperture_size'] = str(self.target_aperture_size)
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
        self.syscfg['stage']['sem_xy_tolerance'] = str(self.xy_tolerance)
        self.syscfg['stage']['sem_z_tolerance'] = str(self.z_tolerance)
        # Motor diagnostics
        self.syscfg['stage']['sem_xyz_move_counter'] = json.dumps(
            self.total_xyz_move_counter)
        self.syscfg['stage']['sem_slow_xy_move_counter'] = str(
            self.slow_xy_move_counter)
        self.syscfg['stage']['sem_failed_xyz_move_counter'] = json.dumps(
            self.failed_xyz_move_counter)
        # Maintenance moves
        self.syscfg['stage']['sem_use_maintenance_moves'] = str(
            self.use_maintenance_moves)
        self.syscfg['stage']['sem_maintenance_move_interval'] = str(int(
            self.maintenance_move_interval))

    def turn_eht_on(self):
        """Turn EHT (= high voltage) on."""
        raise NotImplementedError

    def turn_eht_off(self):
        """Turn EHT (= high voltage) off."""
        raise NotImplementedError

    def is_eht_on(self):
        """Return True if EHT is on."""
        raise NotImplementedError

    def is_eht_off(self):
        """Return True if EHT is off."""
        raise NotImplementedError

    def get_eht(self):
        """Read current EHT (in kV) from SmartSEM."""
        raise NotImplementedError

    def set_eht(self, target_eht):
        """Save the target EHT (in kV, rounded to 2 decimal places) and set
        the actual EHT to this target value.
        """
        self.target_eht = round(target_eht, 2)
        # Setting SEM to target EHT must be implemented in child class!

    def has_vp(self):
        """Return True if VP is fitted."""
        raise NotImplementedError

    def is_hv_on(self):
        """Return True if HV is on."""
        raise NotImplementedError

    def is_vp_on(self):
        """Return True if VP is on."""
        raise NotImplementedError

    def get_chamber_pressure(self):
        """Read current chamber pressure from SmartSEM."""
        raise NotImplementedError

    def get_vp_target(self):
        """Read current VP target pressure from SmartSEM."""
        raise NotImplementedError

    def set_hv(self):
        """Set HV (= High Vacuum)."""
        raise NotImplementedError

    def set_vp(self):
        """Set VP (= Variable Pressure)."""
        raise NotImplementedError

    def set_vp_target(self, target_pressure):
        """Set the VP target pressure."""
        raise NotImplementedError

    def has_fcc(self):
        """Return True if FCC is fitted."""
        raise NotImplementedError

    def is_fcc_on(self):
        """Return True if FCC is on."""
        raise NotImplementedError

    def is_fcc_off(self):
        """Return True if FCC is off."""
        raise NotImplementedError

    def get_fcc_level(self):
        """Read current FCC (0-100) from SmartSEM."""
        raise NotImplementedError

    def turn_fcc_on(self):
        """Turn FCC (= Focal Charge Compensator) on."""
        raise NotImplementedError

    def turn_fcc_off(self):
        """Turn FCC (= Focal Charge Compensator) off."""
        raise NotImplementedError

    def set_fcc_level(self, target_fcc_level):
        """Set the FCC to this target value."""
        raise NotImplementedError

    def get_beam_current(self):
        """Read beam current (in pA) from SmartSEM."""
        raise NotImplementedError

    def set_beam_current(self, target_current):
        """Save the target beam current (in pA) and set the SEM's beam to this
        target current."""
        self.target_beam_current = target_current
        # Setting SEM to target beam current must be implemented in child class!

    def get_high_current(self):
        """Read high current mode from SmartSEM."""
        raise NotImplementedError

    def set_high_current(self, high_current):
        """Save the target high current mode and set the SEM value."""
        self.target_high_current = high_current
        # Setting SEM to target high current must be implemented in child class!

    def get_aperture_size(self):
        """Read aperture size (in μm) from SmartSEM."""
        raise NotImplementedError

    def set_aperture_size(self, aperture_size_index):
        """Save the aperture size (in μm) and set the SEM's beam to this
        aperture size."""
        self.target_aperture_size = self.APERTURE_SIZE[aperture_size_index]
        # Setting SEM to target aperture size must be implemented in child class!

    def apply_beam_settings(self):
        """Set the SEM to the current target EHT voltage and beam current."""
        raise NotImplementedError

    def get_detector_list(self) -> List[str]:
        """Return a list of all available detectors."""
        raise NotImplementedError

    def get_detector(self) -> str:
        """Return the currently selected detector."""
        raise NotImplementedError

    def set_detector(self, detector_name: str) -> None:
        """Select the detector specified by 'detector_name'."""
        raise NotImplementedError
 
    def apply_grab_settings(self):
        """Set the SEM to the current grab settings (stored in
        self.grab_dwell_time, self.grab_pixel_size, and
        self.grab_frame_size_selector)."""
        raise NotImplementedError

    def apply_frame_settings(self, frame_size_selector, pixel_size, dwell_time):
        """Set SEM to the specified frame settings (frame size, pixel size and
        dwell time)."""
        raise NotImplementedError

    def get_frame_size_selector(self):
        """Read the current frame size selector from the SEM."""
        raise NotImplementedError

    def get_frame_size(self):
        raise NotImplementedError

    def set_frame_size(self, frame_size_selector):
        """Set SEM to frame size specified by frame_size_selector."""
        raise NotImplementedError

    def get_mag(self):
        """Read current magnification from SEM."""
        raise NotImplementedError

    def set_mag(self, target_mag):
        """Set SEM magnification to target_mag."""
        raise NotImplementedError

    def get_pixel_size(self):
        """Read current magnification from the SEM and convert it into
        pixel size in nm.
        """
        raise NotImplementedError

    def set_pixel_size(self, pixel_size):
        """Set SEM to the magnification corresponding to pixel_size."""
        raise NotImplementedError

    def get_scan_rate(self):
        """Read the current scan rate from the SEM"""
        raise NotImplementedError

    def set_scan_rate(self, scan_rate_selector):
        """Set SEM to pixel scan rate specified by scan_rate_selector."""
        raise NotImplementedError

    def set_dwell_time(self, dwell_time):
        """Convert dwell time into scan rate and call self.set_scan_rate()
        """
        raise NotImplementedError

    def set_scan_rotation(self, angle):
        """Set the scan rotation angle (in degrees)."""
        raise NotImplementedError
    
    def set_bit_depth(self, bit_depth_selector: int):
        """Set the bit depth selector."""
        self.bit_depth_selector = bit_depth_selector

    def acquire_frame(self, save_path_filename, extra_delay=0):
        """Acquire a full frame and save it to save_path_filename.
        All imaging parameters must be applied BEFORE calling this function.
        To avoid grabbing the image before it is acquired completely, an
        additional waiting period after the cycle time (extra_delay, in seconds)
        may be necessary. The delay specified in syscfg (self.DEFAULT_DELAY)
        is added by default for cycle times > 0.5 s."""
        raise NotImplementedError

    def save_frame(self, save_path_filename):
        """Save the frame currently displayed in SmartSEM."""
        raise NotImplementedError

    def get_wd(self):
        """Return current working distance
        (in metres [because SmartSEM uses metres])."""
        raise NotImplementedError

    def set_wd(self, target_wd):
        """Set working distance to target working distance (in metres)"""
        raise NotImplementedError

    def get_stig_xy(self):
        """Read XY stigmation parameters (in %) from SEM, as a tuple"""
        raise NotImplementedError

    def set_stig_xy(self, target_stig_x, target_stig_y):
        """Set X and Y stigmation parameters (in %)."""
        raise NotImplementedError

    def get_stig_x(self):
        """Read X stigmation parameter (in %) from SEM."""
        raise NotImplementedError

    def set_stig_x(self, target_stig_x):
        """Set X stigmation parameter (in %)."""
        raise NotImplementedError

    def get_stig_y(self):
        """Read Y stigmation parameter (in %) from SEM."""
        raise NotImplementedError

    def set_stig_y(self, target_stig_y):
        """Set Y stigmation parameter (in %)."""
        raise NotImplementedError

    def set_beam_blanking(self, enable_blanking):
        """Enable beam blanking if enable_blanking == True."""
        raise NotImplementedError

    def run_autofocus(self):
        """Run ZEISS autofocus, break if it takes longer than 1 min."""
        raise NotImplementedError

    def run_autostig(self):
        """Run ZEISS autostig, break if it takes longer than 1 min."""
        raise NotImplementedError

    def run_autofocus_stig(self):
        """Run combined ZEISS autofocus and autostig, break if it takes
        longer than 1 min."""
        raise NotImplementedError

    def get_stage_x(self):
        """Read X stage position (in micrometres) from SEM."""
        raise NotImplementedError

    def get_stage_y(self):
        """Read Y stage position (in micrometres) from SEM."""
        raise NotImplementedError

    def get_stage_z(self):
        """Read Z stage position (in micrometres) from SEM."""
        raise NotImplementedError

    def get_stage_xy(self):
        """Read XY stage position (in micrometres) from SEM, return as tuple"""
        raise NotImplementedError

    def get_stage_xyz(self):
        """Read XYZ stage position (in micrometres) from SEM, return as tuple"""
        raise NotImplementedError

    def get_stage_t(self):
        """Read stage tilt (in degrees) from SEM"""
        raise NotImplementedError

    def get_stage_r(self):
        """Read stage rotation (in degrees) from SEM"""
        raise NotImplementedError

    def get_stage_tr(self):
        """Read tilt (degrees) and stage rotation (degrees) from SEM
        as a tuple"""
        raise NotImplementedError

    def move_stage_to_x(self, x):
        """Move stage to coordinate x, provided in microns."""
        raise NotImplementedError

    def move_stage_to_y(self, y):
        """Move stage to coordinate y, provided in microns."""
        raise NotImplementedError

    def move_stage_to_z(self, z):
        """Move stage to coordinate y, provided in microns."""
        raise NotImplementedError

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates x and y, provided as tuple or list
        in microns."""
        raise NotImplementedError

    def stage_move_duration(self, from_x, from_y, to_x, to_y):
        """Calculate the duration of a stage move in seconds using the
        motor speeds specified in the configuration."""
        duration_x = abs(to_x - from_x) / self.motor_speed_x
        duration_y = abs(to_y - from_y) / self.motor_speed_y
        return max(duration_x, duration_y) + self.stage_move_wait_interval

    def reset_stage_move_counters(self):
        """Reset all the counters that keep track of motor moves."""
        self.total_xyz_move_counter = [[0, 0, 0], [0, 0, 0], [0, 0]]
        self.failed_xyz_move_counter = [0, 0, 0]
        self.slow_xy_move_counter = 0
        self.slow_xy_move_warnings.clear()
        self.failed_x_move_warnings.clear()
        self.failed_y_move_warnings.clear()
        self.failed_z_move_warnings.clear()

    def reset_error_state(self):
        """Reset the error state (to 'no error') and clear self.error_info."""
        self.error_state = Error.none
        self.error_info = ''

    def disconnect(self):
        """Disconnect from the SEM."""
        raise NotImplementedError
