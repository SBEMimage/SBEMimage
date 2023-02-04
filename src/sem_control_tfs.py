# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2023 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module provides the commands to operate the SEM. Only the functions
that are actually required in SBEMimage have been implemented."""

from sem_control import SEM
from utils import Error

try:
    import PyPhenom as ppi  # required for Phenom API
except:
    pass

class SEM_Phenom(SEM):
    """Implements all methods for remote control of Phenom SEMs via the
    Phenom remote control API. Currently supported: Phenom Pharos."""

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        if not self.simulation_mode:
            exception_msg = ''
            try:
                self.sem_api = ppi.Phenom(phenom_id, username, password)
                if self.sem_api is not None:
                    self.sem_api.Activate()
                    self.sem_api.Load()
                    self.sem_api.MoveToNavCam()
                ret_val = (self.sem_api is not None)
            except Exception as e:
                ret_val = False
                exception_msg = str(e)
            if not ret_val:
                self.error_state = Error.smartsem_api
                self.error_info = (
                    f'sem.__init__: remote API control could not be '
                    f'initialised (ret_val: {ret_val}). {exception_msg}')
            elif self.use_sem_stage:
                # Read current SEM stage coordinates
                self.last_known_x, self.last_known_y, self.last_known_z = (
                    self.get_stage_xyz())
        else:
            self.sem_api = ppi.Phenom('Simulator', '', '')

    def turn_eht_on(self):
        self.eht_on = True
        return True

    def turn_eht_off(self):
        self.eht_on = False
        return True

    def is_eht_on(self):
        return self.eht_on

    def is_eht_off(self):
        return not self.eht_on

    def get_eht(self):
        return self.target_eht

    def set_eht(self, target_eht):
        self.target_eht = round(target_eht, 2)
        return True

    def has_vp(self):
        return False

    def is_hv_on(self):
        return True

    def is_vp_on(self):
        return False

    def get_chamber_pressure(self):
        raise NotImplementedError

    def get_vp_target(self):
        raise NotImplementedError

    def set_hv(self):
        raise NotImplementedError

    def set_vp(self):
        raise NotImplementedError

    def set_vp_target(self, target_pressure):
        raise NotImplementedError

    def has_fcc(self):
        return False
 
    def is_fcc_on(self):
        raise NotImplementedError

    def is_fcc_off(self):
        raise NotImplementedError

    def get_fcc_level(self):
        raise NotImplementedError

    def turn_fcc_on(self):
        raise NotImplementedError

    def turn_fcc_off(self):
        raise NotImplementedError

    def set_fcc_level(self, target_fcc_level):
        raise NotImplementedError

    def get_beam_current(self):
        return self.target_beam_current

    def set_beam_current(self, target_current):
        self.target_beam_current = target_current
        return True

    def get_high_current(self):
        return self.target_high_current

    def set_high_current(self, high_current):
        self.target_high_current = high_current
        return True

    def get_aperture_size(self):
        return 30  # micrometres

    def set_aperture_size(self, aperture_size_index):
        pass

    def apply_beam_settings(self):
        pass

    def get_detector_list(self):
        return ['All', 'NorthSouth', 'EastWest', 'A', 'B', 'C', 'D', 'Sed']

    def get_detector(self):
        return self.detector

    def set_detector(self, detector_name):
        if detector_name in self.get_detector_list():
            self.detector = detector_name

    def apply_grab_settings(self):
        self.apply_frame_settings(
            self.grab_frame_size_selector,
            self.grab_pixel_size,
            self.grab_dwell_time)

    def apply_frame_settings(self, frame_size_selector, pixel_size, dwell_time):
        """Apply the frame settings (pixel size and dwell time).
        Frame Size is kept around for compatibility"""
        ret  = self.set_dwell_time(dwell_time)
        ret &= self.set_frame_size(frame_size_selector)
        ret &= self.set_pixel_size(pixel_size)
        return ret

    def get_frame_size_selector(self):
        return self.frame_size_selector

    def get_frame_size(self):
        raise NotImplementedError

    def set_frame_size(self, frame_size_selector):
        self.frame_size_selector = frame_size_selector
        return True

    def get_mag(self):
        return self.mag

    def set_mag(self, target_mag):
        self.mag = target_mag
        return True

    def get_pixel_size(self):
        return self.MAG_PX_SIZE_FACTOR / (self.mag
                   * self.STORE_RES[self.frame_size_selector][0])

    def set_pixel_size(self, pixel_size):
        self.mag = int(self.MAG_PX_SIZE_FACTOR /
                       (self.STORE_RES[self.frame_size_selector][0] * pixel_size))
        return True

    def get_scan_rate(self):
        raise NotImplementedError

    def set_scan_rate(self, scan_rate_selector):
        raise NotImplementedError

    def set_dwell_time(self, dwell_time):
        self.dwell_time = dwell_time
        return True

    def set_scan_rotation(self, angle):
        return True

    def acquire_frame(self, save_path_filename, extra_delay=0):
        """Acquire a full frame and save it to save_path_filename.
        All imaging parameters must be applied BEFORE calling this function.
        To avoid grabbing the image before it is acquired completely, an
        additional waiting period after the cycle time (extra_delay, in seconds)
        may be necessary. The delay specified in syscfg (self.DEFAULT_DELAY)
        is added by default for cycle times > 0.5 s."""

        return True

    def save_frame(self, save_path_filename):
        self.acquire_frame(save_path_filename)

    def get_wd(self):
        return self.wd

    def set_wd(self, target_wd):
        self.wd = target_wd
        return True

    def get_stig_xy(self):
        return self.stig_x, self.stig_y

    def set_stig_xy(self, target_stig_x, target_stig_y):
        self.stig_x = target_stig_x
        self.stig_y = target_stig_y
        return True

    def get_stig_x(self):
        return self.stig_x

    def set_stig_x(self, target_stig_x):
        self.stig_x = target_stig_x
        return True

    def get_stig_y(self):
        return self.stig_y

    def set_stig_y(self, target_stig_y):
        self.stig_y = target_stig_y
        return True

    def set_beam_blanking(self, enable_blanking):
        return True

    def run_autofocus(self):
        return True

    def run_autostig(self):
        return True

    def run_autofocus_stig(self):
        return True

    def get_stage_x(self):
        return self.last_known_x

    def get_stage_y(self):
        return self.last_known_y

    def get_stage_z(self):
        return self.last_known_z

    def get_stage_xy(self):
        return self.last_known_x, self.last_known_y

    def get_stage_xyz(self):
        return self.last_known_x, self.last_known_y, self.last_known_z

    def move_stage_to_x(self, x):
        self.last_known_x = x

    def move_stage_to_y(self, y):
        self.last_known_y = y

    def move_stage_to_z(self, z):
        self.last_known_z = z

    def move_stage_to_xy(self, coordinates):
        self.last_known_x, self.last_known_y = coordinates

    def stage_move_duration(self, from_x, from_y, to_x, to_y):
        duration_x = abs(to_x - from_x) / self.motor_speed_x
        duration_y = abs(to_y - from_y) / self.motor_speed_y
        return max(duration_x, duration_y) + self.stage_move_wait_interval

    def reset_stage_move_counters(self):
        self.total_xyz_move_counter = [[0, 0, 0], [0, 0, 0], [0, 0]]
        self.failed_xyz_move_counter = [0, 0, 0]
        self.slow_xy_move_counter = 0
        self.slow_xy_move_warnings.clear()
        self.failed_x_move_warnings.clear()
        self.failed_y_move_warnings.clear()
        self.failed_z_move_warnings.clear()

    def reset_error_state(self):
        self.error_state = Error.none
        self.error_info = ''

    def disconnect(self):
        self.sem_api.Unload()
