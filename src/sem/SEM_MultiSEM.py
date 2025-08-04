import json
import sys
from time import sleep

import comtypes
from qtpy.QtWidgets import QMessageBox
from comtypes import client as cc

from constants import Error
from sem.SEM import SEM


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
                'SBEMimage error',
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
                    QMessageBox.critical(self,'SBEMimage error',
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
                QMessageBox.critical(self, 'SBEMimage error',
                    'Failure to turn the beam off',
                    QMessageBox.Ok)
                return False
            else:
                return True
        else:
            self.error_state = Error.eht
            self.error_info = (
                f'sem.turn_eht_off: command failed (ret_val: {ret_val})')
            QMessageBox.critical(self, 'SBEMimage error',
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
