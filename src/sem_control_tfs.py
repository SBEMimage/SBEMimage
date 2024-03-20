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

import numpy as np
from time import sleep

try:
    # required for Phenom API
    import PyPhenom as ppi
    from PyPhenom import OperationalMode
except:
    pass

from constants import Error
from image_io import imwrite
from sem_control import SEM
import utils


class SEM_Phenom(SEM):
    """Implements all methods for remote control of Phenom SEMs via the
    Phenom remote control API. Currently supported: Phenom Pharos."""

    PPAPI_CREDENTIALS_FILENAME = '../credentials/ppapi_credentials.txt'
    DEFAULT_DETECTOR = ppi.DetectorMode.All

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)

        self.sem_api = None
        self.detector = self.DEFAULT_DETECTOR

        if not self.simulation_mode:
            try:
                phenom_id, username, password = utils.load_csv(self.PPAPI_CREDENTIALS_FILENAME)
                if len(username) == 0:
                    username = ''
                if len(password) == 0:
                    password = ''
                self.sem_api = ppi.Phenom(phenom_id, username, password)
            except Exception as e:
                self.error_state = Error.smartsem_api
                self.error_info = str(e)
                self.simulation_mode = True
        if self.simulation_mode:
            self.sem_api = ppi.Phenom('Simulator', '', '')

        if self.sem_api is not None:
            self.sem_api.Activate()
            if self.use_sem_stage:
                # Read current SEM stage coordinates
                self.last_known_x, self.last_known_y = self.get_stage_xy()
        else:
            self.error_state = Error.smartsem_api
            self.error_info = ''

    def has_lm_mode(self):
        return True

    def turn_eht_on(self):
        return True

    def turn_eht_off(self):
        return True

    def is_eht_on(self):
        return True

    def is_eht_off(self):
        return False

    def get_eht(self):
        """Return current SmartSEM EHT setting in kV."""
        # TFS uses negative tension value
        self.target_eht = self.sem_api.GetSemHighTension() * -1e-3
        return self.target_eht

    def set_eht(self, target_eht):
        """Save the target EHT (in kV) and set the EHT to this target value."""
        # Call method in parent class
        super().set_eht(target_eht)
        # target_eht given in kV
        # TFS uses negative tension value
        self.sem_api.SetSemHighTension(self.target_eht * -1e+3)
        return True

    def has_brightness(self):
        """Return True if supports brightness control."""
        return True

    def has_contrast(self):
        """Return True if supports contrast control."""
        return True

    def has_auto_brightness_contrast(self):
        """Return True if supports auto brightness/contrast control."""
        return True

    def get_brightness(self):
        """Read SmartSEM brightness (0-1)."""
        return self.sem_api.GetSemBrightness()

    def get_contrast(self):
        """Read SmartSEM contrast (0-1)."""
        return self.sem_api.GetSemContrast()

    def get_auto_brightness_contrast(self):
        """Return True if auto active, otherwise False."""
        return False

    def set_brightness(self, brightness):
        """Write SmartSEM brightness (0-1)."""
        self.sem_api.SetSemBrightness(brightness)

    def set_contrast(self, contrast):
        """Write SmartSEM contrast (0-1)."""
        self.sem_api.SetSemContrast(contrast)

    def set_auto_brightness_contrast(self, enable=True):
        """Perform or set auto contrast brightness."""
        self.sem_api.SemAutoContrastBrightness()

    def has_vp(self):
        if not self.simulation_mode:
            return True
        else:
            return False

    def is_hv_on(self):
        """Return True if High Vacuum is on."""
        return False

    def is_vp_on(self):
        """Return True if VP is on."""
        return False

    def get_chamber_pressure(self):
        """Read current chamber pressure from SmartSEM."""
        # Pascal -> Bar
        return self.sem_api.SemGetVacuumChargeReductionState().pressureEstimate * 1e-5

    def get_vp_target(self):
        """Read current VP target pressure from SmartSEM."""
        # Pascal -> Bar
        return self.sem_api.SemGetVacuumChargeReductionState().target * 1e-5

    def set_hv(self):
        """Set HV (= High Vacuum)."""
        self.sem_api.SemSetTargetVacuumChargeReduction(ppi.VacuumChargeReduction.High)

    def set_vp(self):
        pass

    def set_vp_target(self, target_pressure):
        pass

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
        """Set the SEM to the current target EHT voltage and beam current."""
        self.set_eht(self.target_eht)

    def get_detector_list(self):
        """Return a list of all available detectors."""
        return ppi.DetectorMode.names

    def get_detector(self):
        """Return the currently selected detector."""
        return str(self.detector)

    def set_detector(self, detector_name):
        """Select the detector specified by 'detector_name'."""
        self.detector = ppi.DetectorMode.names[detector_name]

    def apply_grab_settings(self):
        """Set the SEM to the current grab settings (stored in
        self.grab_dwell_time, self.grab_pixel_size, and
        self.grab_frame_size_selector)."""
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
        """Get the current frame size selector."""
        return self.frame_size_selector

    def get_frame_size(self):
        """Get the current frame size."""
        return self.frame_size

    def set_frame_size(self, frame_size_selector):
        """Set SEM to frame size specified by frame_size_selector."""
        self.frame_size_selector = frame_size_selector
        self.frame_size = self.STORE_RES[frame_size_selector]
        return True

    def get_mag(self):
        self.mag = int(self.MAG_PX_SIZE_FACTOR / (self.frame_size[0] * self.grab_pixel_size))
        return self.mag

    def set_mag(self, target_mag):
        self.mag = target_mag
        return True

    def get_pixel_size(self):
        # m -> nm
        return self.sem_api.GetHFW() / self.frame_size[0] * 1e+9

    def set_pixel_size(self, pixel_size):
        # pixel_size in [nm]
        self.grab_pixel_size = pixel_size
        self.sem_api.SetHFW(self.frame_size[0] * pixel_size * 1e-9)
        self.mag = self.get_mag()
        return True

    def get_scan_rate(self):
        raise NotImplementedError

    def set_scan_rate(self, scan_rate_selector):
        raise NotImplementedError

    def set_dwell_time(self, dwell_time):
        self.dwell_time = dwell_time
        return True

    def set_scan_rotation(self, angle):
        self.scan_rotation = angle
        self.sem_api.SetSemRotation(-np.deg2rad(angle))
        return True

    def acquire_frame(self, save_path_filename, stage=None, extra_delay=0):
        """Acquire a full frame and save it to save_path_filename.
        All imaging parameters must be applied BEFORE calling this function.
        To avoid grabbing the image before it is acquired completely, an
        additional waiting period after the cycle time (extra_delay, in seconds)
        may be necessary. The delay specified in syscfg (self.DEFAULT_DELAY)
        is added by default for cycle times > 0.5 s."""

        scan_params = ppi.ScanParamsEx()
        scan_params.dwellTime = float(self.dwell_time * 1e-6)   # convert us to s
        scan_params.scale = 1.0
        scan_params.size = ppi.Size(self.frame_size[0], self.frame_size[1])
        scan_params.hdr = (self.bit_depth_selector == 1)
        scan_params.center = ppi.Position(0, 0)
        scan_params.detector = self.detector
        scan_params.nFrames = 1

        try:
            mode = self.sem_api.GetOperationalMode()
            if mode == OperationalMode.Loadpos:
                utils.log_info('SEM', 'Moving to load position')
                self.sem_api.Load()
            if mode != OperationalMode.LiveSem:
                utils.log_info('SEM', 'Moving to EM mode')
                self.sem_api.MoveToSem()
                self.move_stage_to_xy((self.last_known_x, self.last_known_y))
                self.set_scan_rotation(self.scan_rotation)
                self.set_pixel_size(self.grab_pixel_size)

            self.sem_api.SemUnblankBeam()

            if extra_delay > 0:
                sleep(extra_delay)

            acq = self.sem_api.SemAcquireImageEx(scan_params)
            image = np.asarray(acq.image)
            imwrite(save_path_filename, image, metadata=self.get_grab_metadata(stage))
            return True
        except Exception as e:
            self.error_state = Error.grab_image
            self.error_info = f'sem.acquire_frame: command failed ({e})'
            utils.log_error('SEM', self.error_info)
            return False

    def acquire_frame_lm(self, save_path_filename, stage=None, extra_delay=0):
        scan_params = ppi.CamParams()  # use default size
        scan_params.size = ppi.Size(self.frame_size[0], self.frame_size[1])
        scan_params.nFrames = 1

        try:
            mode = self.sem_api.GetOperationalMode()
            if mode == OperationalMode.Loadpos:
                utils.log_info('SEM', 'Moving to load position')
                self.sem_api.Load()
            if mode != OperationalMode.LiveNavCam:
                utils.log_info('SEM', 'Moving to LM mode')
                self.sem_api.MoveToNavCam()
                self.move_stage_to_xy((self.last_known_x, self.last_known_y))
                self.set_scan_rotation(self.scan_rotation)
                self.set_pixel_size(self.grab_pixel_size)

            if extra_delay > 0:
                sleep(extra_delay)

            acq = self.sem_api.NavCamAcquireImage(scan_params)
            data = np.asarray(acq.image)
            if acq.image.encoding == ppi.PixelType.RGB:
                # API returns multi-type array; convert to simple type
                data = np.asarray(data.tolist(), dtype=np.uint8)
            imwrite(save_path_filename, data, metadata=self.get_grab_metadata(stage))
            return True
        except Exception as e:
            self.error_state = Error.grab_image
            self.error_info = f'sem.acquire_frame_lm: command failed ({e})'
            utils.log_error('SEM', self.error_info)
            return False

    def save_frame(self, save_path_filename, stage=None):
        """Only supports (re)acquiring frame, requiring providing acquisition parameters"""
        return self.acquire_frame(save_path_filename, stage=stage)

    def get_wd(self):
        """Return current working distance in metres."""
        return self.sem_api.GetSemWD()

    def set_wd(self, target_wd):
        """Set working distance to target working distance (in metres)."""
        self.sem_api.SetSemWD(target_wd)
        return True

    def get_stig_xy(self):
        stigmate = self.sem_api.GetSemStigmate()
        self.stig_x, self.stig_y = stigmate.x, stigmate.y
        return self.stig_x, self.stig_y

    def set_stig_xy(self, target_stig_x, target_stig_y):
        self.sem_api.SetSemStigmate(ppi.Position(target_stig_x, target_stig_y))
        self.stig_x = target_stig_x
        self.stig_y = target_stig_y
        return True

    def get_stig_x(self):
        self.get_stig_xy()
        return self.stig_x

    def set_stig_x(self, target_stig_x):
        self.set_stig_xy(target_stig_x, self.stig_y)
        return True

    def get_stig_y(self):
        self.get_stig_xy()
        return self.stig_y

    def set_stig_y(self, target_stig_y):
        self.set_stig_xy(self.stig_x, target_stig_y)
        self.stig_y = target_stig_y
        return True

    def set_beam_blanking(self, enable_blanking):
        self.sem_api.SemBlankBeam()
        return True

    def run_autofocus(self, *args):
        self.sem_api.SemAutoFocus()
        return True

    def run_autostig(self, *args):
        self.sem_api.SemAutoStigmate()
        return True

    def run_autofocus_stig(self, *args):
        return self.run_autofocus() and self.run_autostig()

    def get_stage_x(self):
        """Read X stage position (in micrometres) from SEM."""
        # m -> um
        self.last_known_x = self.sem_api.GetStageModeAndPosition().position.x * 1e+6
        return self.last_known_x

    def get_stage_y(self):
        """Read Y stage position (in micrometres) from SEM."""
        # m -> um
        self.last_known_y = self.sem_api.GetStageModeAndPosition().position.y * 1e+6
        return self.last_known_y

    def get_stage_z(self):
        return self.last_known_z

    def get_stage_xy(self):
        return self.get_stage_x(), self.get_stage_y()

    def get_stage_xyz(self):
        return self.get_stage_x(), self.get_stage_y(), self.last_known_z

    def move_stage_to_x(self, x):
        """Move stage to coordinate x, provided in microns"""
        y = self.get_stage_y()
        self.move_stage_to_xy((x, y))

    def move_stage_to_y(self, y):
        """Move stage to coordinate y, provided in microns"""
        x = self.get_stage_x()
        self.move_stage_to_xy((x, y))

    def move_stage_to_z(self, z):
        self.last_known_z = z

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates x and y, provided in microns"""
        x, y = coordinates
        self.sem_api.MoveTo(x * 1e-6, y * 1e-6)    # um -> m
        self.get_stage_x()
        self.get_stage_y()

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
