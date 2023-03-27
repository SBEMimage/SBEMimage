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
from utils import Error, load_csv

try:
    import PyPhenom as ppi  # required for Phenom API
except:
    pass


class SEM_Phenom(SEM):
    """Implements all methods for remote control of Phenom SEMs via the
    Phenom remote control API. Currently supported: Phenom Pharos."""

    PPAPI_CREDENTIALS_FILENAME = '../credentials/ppapi_credentials.txt'
    DEFAULT_DETECTOR = ppi.DetectorMode.All

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        self.detector = self.DEFAULT_DETECTOR
        if not self.simulation_mode:
            exception_msg = ''
            phenom_id, username, password = load_csv(self.PPAPI_CREDENTIALS_FILENAME)
            try:
                self.sem_api = ppi.Phenom(phenom_id, username, password)
                if self.sem_api is not None:
                    self.sem_api.Activate()
                    self.sem_api.Load()
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
                self.last_known_x, self.last_known_y, self.last_known_z = self.get_stage_xyz()
        else:
            self.sem_api = ppi.Phenom('Simulator', '', '')

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
        self.target_eht = -self.sem_api.GetSemHighTension() * 1e-3
        return self.target_eht

    def set_eht(self, target_eht):
        """Save the target EHT (in kV) and set the EHT to this target value."""
        # Call method in parent class
        super().set_eht(target_eht)
        # target_eht given in kV
        # TFS uses negative tension value
        self.sem_api.SetSemHighTension(-self.target_eht * 1e+3)
        return True

    def has_vp(self):
        return True

    def is_hv_on(self):
        """Return True if High Vacuum is on."""
        return self.sem_api.SemGetVacuumChargeReduction() == ppi.VacuumChargeReduction.High

    def is_vp_on(self):
        """Return True if VP is on."""
        return False

    def get_chamber_pressure(self):
        """Read current chamber pressure from SmartSEM."""
        return self.sem_api.SemGetVacuumChargeReductionState().pressureEstimate

    def get_vp_target(self):
        """Read current VP target pressure from SmartSEM."""
        return self.sem_api.SemGetVacuumChargeReductionState().target

    def set_hv(self):
        """Set HV (= High Vacuum)."""
        self.sem_api.SemSetTargetVacuumChargeReduction(ppi.VacuumChargeReduction.High)

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
        """Set the SEM to the current target EHT voltage and beam current."""
        self.sem_api.SetSemHighTension(self.target_eht * 1e+3)

    def get_detector_list(self):
        """Return a list of all available detectors."""
        return ppi.DetectorMode.names

    def get_detector(self):
        """Return the currently selected detector."""
        return self.detector

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
        self.mag = int(self.MAG_PX_SIZE_FACTOR / (self.frame_size[0] * self.pixel_size))
        return self.mag

    def set_mag(self, target_mag):
        self.mag = target_mag
        return True

    def get_pixel_size(self):
        # m -> nm
        return self.sem_api.GetHFW() / self.frame_size[0] * 1e+9

    def set_pixel_size(self, pixel_size):
        # pixel_size in [nm]
        self.pixel_size = pixel_size
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
        return True

    def acquire_frame(self, save_path_filename, extra_delay=0):
        """Acquire a full frame and save it to save_path_filename.
        All imaging parameters must be applied BEFORE calling this function.
        To avoid grabbing the image before it is acquired completely, an
        additional waiting period after the cycle time (extra_delay, in seconds)
        may be necessary. The delay specified in syscfg (self.DEFAULT_DELAY)
        is added by default for cycle times > 0.5 s."""

        dwell_time = self.dwell_time * 1e-6    # convert us to s
        scan_params = ppi.ScanParamsEx()
        scan_params.dwellTime = float(dwell_time)
        scan_params.scale = 1.0
        scan_params.size = ppi.Size(self.frame_size[0], self.frame_size[1])
        scan_params.hdr = (self.bit_depth_selector == 1)
        scan_params.center = ppi.Position(0, 0)
        scan_params.detector = self.detector
        scan_params.nFrames = 2

        try:
            self.sem_api.MoveToSem()

            acq = self.sem_api.SemAcquireImageEx(scan_params)

            if save_path_filename.lower().endswith('.bmp'):
                conversion = ppi.SaveConversion.ToCompatibleFormat
            else:
                conversion = ppi.SaveConversion.NoConversion
            ppi.Save(acq, save_path_filename, conversion)
            return True
        except:
            return False

    def save_frame(self, save_path_filename):
        self.acquire_frame(save_path_filename)

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

    def run_autofocus(self):
        self.sem_api.SemAutoFocus()
        return True

    def run_autostig(self):
        self.sem_api.SemAutoStigmate()
        return True

    def run_autofocus_stig(self):
        return self.sem_api.SemAutoFocus() and self.sem_api.SemAutoStigmate()

    def get_stage_x(self):
        """Read X stage position (in micrometres) from SEM."""
        # m -> um
        self.last_known_x = self.sem_api.GetStageModeAndPosition().position.x * 1e-6
        return self.last_known_x

    def get_stage_y(self):
        """Read Y stage position (in micrometres) from SEM."""
        # m -> um
        self.last_known_y = -self.sem_api.GetStageModeAndPosition().position.y * 1e-6
        return self.last_known_y

    def get_stage_z(self):
        return self.last_known_z

    def get_stage_xy(self):
        return self.last_known_x, self.last_known_y

    def get_stage_xyz(self):
        return self.last_known_x, self.last_known_y, self.last_known_z

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
        self.sem_api.MoveTo(x * 1e-6, y * -1e-6)    # um -> m
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
