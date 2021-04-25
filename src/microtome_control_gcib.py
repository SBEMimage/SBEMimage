import time
from time import sleep
import json
import numpy as np
from microtome_control import BFRemover
import utils
from utils import Error


try:
    import ftdidio
    _ftdidio_avail = True
except ImportError as e:
    _ftdidio_avail = False

# TODO: beam deceleration should be controlled elsewhere
try:
    import ftdirelais
    _ftdirelais_avail = True
except ImportError as e:
    _ftdirelais_avail = False

_ftdi_utils_avail = _ftdidio_avail and _ftdirelais_avail


class GCIB(BFRemover):
    """
    [WIP]
    Requires stage hook.
    Todo:
        * use consistent error states.
        * remove redundant interface to SEMstage
        * Update full_cut_duration when changing mill_cycle / mill_duration
        * Unify mill_cycle and mill_duration!
    """

    def __init__(self, config: dict, sysconfig: dict, stage):
        """

        Args:
            config:
            sysconfig:
            stage: Stage class must implement XYZ translation, tilt and rotation.
        """
        super().__init__(config, sysconfig)
        self.cfg = config
        self.syscfg = sysconfig
        self.stage = stage
        self.error_state = Error.none
        self.error_info = ''
        self.acq = None
        self.simulation_mode = (
            self.cfg['sys']['simulation_mode'].lower() == 'true')

        if not _ftdi_utils_avail and not self.simulation_mode:
            self.error_state = Error.configuration
            self.error_info = (
                f'ImportError: {self} implementation requires package "ftdidio"'
                f' and "ftdirelais", which could not be imported.')

        # Load device name and other settings from sysconfig. These
        # settings overwrite the settings in config.
        recognized_devices = json.loads(
            self.syscfg['device']['microtome_recognized'])
        self.cfg['microtome']['device'] = self.syscfg['device']['microtome']
        if self.cfg['microtome']['device'] not in recognized_devices:
            self.cfg['microtome']['device'] = 'NOT RECOGNIZED'
        self.device_name = self.cfg['microtome']['device']

        self._pos_prior_mill_mov = None
        # Catch errors that occur while reading configuration and converting
        # the string values into floats or integers
        try:
            # Duration of a full cut cycle in seconds
            self.mill_cycle = float(self.cfg['gcib']['mill_cycle'])
            self._ftdi_serial = str(self.cfg['gcib']['ftdi_serial'])
            self.continuous_rot = int(self.cfg['gcib']['continuous_rot'])
            self.xyzt_milling = np.array(json.loads(self.cfg['gcib']['xyzt_milling']))
            self.full_cut_duration = self.mill_cycle
        except Exception as e:
            self.error_state = Error.configuration
            self.error_info = str(e)
            return  # return here otherwise this error will be overwritten by the next lines
        
        if _ftdi_utils_avail and not self.simulation_mode:
            try:
                self._ftdi_device = ftdidio.Ftdidio()
            except Exception as e:
                self.error_state = Error.configuration
                self.error_info = f'Could not initialize ftdidio: {str(e)}'
            # try:
            #     self._ftdirelais = ftdirelais.Ftdirelais()
            # except Exception as e:
            #     self.error_state = Error.configuration
            #     self.error_info = f'Could not initialize ftdirelais: {str(e)}'
            self._connect_blanking()
            # self._connect_relais()

    def _connect_blanking(self):
        try:
            self._ftdi_device.open(serial=self._ftdi_serial)
            self._ftdi_device.set_mask(1)
            self._blank_beam()
            msg = f'GCIB: Connected ftdidio.'
            utils.log_info(msg)
        except ftdidio.FtdidioError as e:
            self.error_state = Error.move_init
            self.error_info = str(e)

    def _disconnect_blanking(self):
        """
        Disconnect from ftdi device. Tries to blank beam.
        """
        try:
            self._blank_beam()
            self._ftdi_device.close()
        except ftdidio.FtdidioError as e:
            self.error_state = Error.move_init
            self.error_info = str(e)

    def _blank_beam(self):
        self._ftdi_device.set_bit(1)

    def _unblank_beam(self):
        self._ftdi_device.clear_bit(1)

    def _connect_relais(self):
        try:
            self._ftdirelais.open(serial='4')
            msg = f'GCIB: Connected ftdi relais.'
            utils.log_info(msg)
        except Exception as e:
            self.error_state = Error.configuration
            self.error_info = f'Could not initialize ftdirelais: {str(e)}'

    def _disconnect_relais(self):
        try:
            self._ftdirelais.close()
        except Exception as e:
            self.error_state = Error.configuration
            self.error_info = f'Could not initialize ftdirelais: {str(e)}'

    def _relais_on(self):
        self._ftdirelais.set_relais_0()

    def _relais_off(self):
        self._ftdirelais.clear_relais_0()

    def save_to_cfg(self):
        self.cfg['microtome']['full_cut_duration'] = str(self.mill_cycle)
        self.cfg['gcib']['ftdi_serial'] = str(self._ftdi_serial)
        self.cfg['gcib']['xyzt_milling'] = str(self.xyzt_milling.tolist())
        self.cfg['gcib']['mill_cycle'] = str(self.mill_cycle)
        self.cfg['gcib']['continuous_rot'] = str(self.continuous_rot)
        self.cfg['gcib']['last_known_z'] = str(self.last_known_z)
        # TODO: why is this called here?
        self.stage.save_to_cfg()

    def do_full_cut(self, **kwargs):
        self.do_full_removal(**kwargs)
        return

    def move_stage_to_millpos(self):
        """
        Sets '_pos_prior_mill_mov' to current stage position. Moves the stage to R=120.


        """
        # move_to_xyzt will set rotation to self.stage.rotation, no need to store r explicitly
        if np.all(self.xyzt_milling == 0):
            self.error_info = 'NotInitializedError: Location parameters for milling have not been set.'
            self.error_state = Error.move_params
            return
        x, y, z, t, r = self.stage.get_stage_xyztr()
        msg = f'GCIB: Start position for milling cycle X={x}, Y={y}, Z={z}, T={t}, R={r}.'
        utils.log_info(msg)
        if not np.isclose(t, 0, atol=1e-4):
            self.error_state = Error.move_unsafe
            self.error_info = (f'UnsafeMovementError: Current t position is supposed to be close to 0,'
                               f'instead got: {t} != 0.')
            return
        # This is pure safety measure - this would be possible
        if not np.isclose(t, 0):
            self.error_info = 'UnsafeMovementError: Current tilt angle is not close to 0. As a safety measure, ' \
                              'this is currently not supported.'
            self.error_state = Error.move_unsafe
            return
        x_mill, y_mill, z_mill, t_mill = self.xyzt_milling
        if z < z_mill:
            self.error_state = Error.move_unsafe
            self.error_info = (f'UnsafeMovementError: Current z position is smaller than the '
                               f'one given as milling location: {z} < {z_mill}.')
            return
        self._pos_prior_mill_mov = [x, y, z, t, r]
        msg = f'Stored position prior to mill movement: {self._pos_prior_mill_mov}'
        utils.log_info(msg)

        if self.simulation_mode:
            time.sleep(self.full_cut_duration)
            return
        self.stage.move_stage_to_z(z_mill)
        # TODO: maybe tilt at the very end for safety reasons if z_mill is high..
        self.stage.move_stage_to_xyzt(x_mill, y_mill, z_mill, t_mill)
        # # Only needed if non-continuous rotation.
        # self.stage.move_stage_delta_r(120, no_wait=True)
        msg = f'GCIB: Reached mill position: X={x_mill}, Y={y_mill}, Z={z_mill}, T={t_mill}, R=120.'
        utils.log_info(msg)

    def move_stage_to_pos_prior_mill_mov(self):
        """
        Sets '_pos_prior_mill_mov' to None.

        """
        if self._pos_prior_mill_mov is None:
            self.error_info = 'UnsafeMovementError: Position prior to mill movement is None.'
            self.error_state = Error.move_params
            return
        x, y, z, t, r = self._pos_prior_mill_mov
        if not np.isclose(t, 0, atol=1e-4):
            self.error_state = Error.move_unsafe
            self.error_info = (f'UnsafeMovementError: Tilt position before milling is supposed to be close to 0,'
                               f'instead got: {t} != 0.')
            return
        x_mill, y_mill, z_mill, t_mill = self.xyzt_milling
        # move stage to initial position, first tilt to 0 degree
        self.stage.move_stage_to_r(r, no_wait=True)
        # TODO: will still wait for the rotation to finish within move_stage_to_xyztr, as rotating is the slowest part
        self.stage.move_stage_to_xyztr(x_mill, y_mill, z_mill, t, r)
        _, _, _, t_curr, _ = self.stage.get_stage_xyztr()
        # double check tilt position
        if not np.isclose(t_curr, 0, atol=1e-4):
            self.error_state = Error.move_unsafe
            self.error_info = (f'IncosistentMoveError: Target t position is supposed to be close to 0,'
                               f'instead got: {t} != 0.')
            return
        # move XYR
        self.stage.move_stage_to_xyztr(x, y, z_mill, t, r)
        # move Z at the very end
        self.stage.move_stage_to_xyztr(x, y, z, t, r)
        self._pos_prior_mill_mov = None
        # TODO: any check required?
        # _, _, _, _, r_dest = self.stage.get_stage_xyztr()
        # if not np.isclose(r_dest, self.stage.stage_rotation, atol=1e-4):
        #     self.error_state = Error.move_unsafe
        #     self.error_info = (f'IncosistentMoveError: Current r position is supposed to be close to '
        #                        f'self.stage.stage_rotation={self.stage.stage_rotation},'
        #                        f'instead got: {r_dest} != 0.')
        #     return
        msg = f'GCIB: Reached original position after milling cycle: X={x}, Y={y}, Z={z}, T={t}, R={r}.'
        utils.log_info(msg)

    def do_full_removal(self, mill_duration=None, testing=False):
        """Perform a full milling cycle. This is the only removal function
           used during stack acquisitions.
        """
        if mill_duration is None:
            mill_duration = self.mill_cycle
        # self._relais_off()
        self.move_stage_to_millpos()
        # mill_duration==0 is only required to test stage transitions
        dt_milling = time.time()
        if mill_duration > 0:
            self._unblank_beam()
        self.rotate360(mill_duration)
        if mill_duration > 0:
            self._blank_beam()
        dt_milling = time.time() - dt_milling
        utils.log_info(f'GCIB: GCIB was unblanked with stage in focus position for {dt_milling:.1f} s')
        self.move_stage_to_pos_prior_mill_mov()
        # self._relais_on()
        if testing:
            return
        # TODO: requires further investigation (might disappear with proper gold coating and electron irradiation)
        dt_sleep = 0
        if dt_sleep > 0:
            msg = f'GCIB: Sleeping for {dt_sleep} s to lose charge on sample.'
            utils.log_info(msg)
            sleep(dt_sleep)

    def rotate360(self, mill_duration):
        """
        Args:
            mill_duration: Total mill duration in seconds.
        """
        # Hayworth et al, 2019, Nat. Methods: Three evenly spaced azimuthal
        # directions for 360 deg and 360 s per mill cycle
        if not self.continuous_rot:
            start = time.time()
            while True:  # loop while < mill duration
                start_invertall = time.time()
                while True:  # sleep for 10s after rotating to new azimuth
                    dt_intervall = time.time() - start_invertall
                    dt = time.time() - start
                    if self.acq is not None and self.acq.acq_paused and self.acq.pause_state == 1:
                        break
                    if dt_intervall >= 10 or dt >= mill_duration:
                        break
                    time.sleep(0.2)
                # pause_state==1 -> pause immediately
                if dt >= mill_duration or (self.acq is not None and self.acq.acq_paused and self.acq.pause_state == 1):
                    break
                self.stage.move_stage_delta_r(120, no_wait=False)
        else:
            dt_per_2deg = mill_duration / 180
            for deg in range(360):
                if self.acq is not None and self.acq.acq_paused and self.acq.pause_state == 1:
                    break
                start = time.time()
                self.stage.move_stage_delta_r(2)
                dt = time.time() - start
                if dt > dt_per_2deg:
                    msg = (f'GCIB: WARNING: Rotation speed was slower ({dt:.3f} s) than requested by the target mill '
                           f'cycle ({dt_per_2deg:.2f s}).')
                    utils.log_info(msg)
                else:
                    sleep(dt_per_2deg - dt)

    def move_stage_to_z(self, z):
        return self.stage.move_stage_to_z(z)

    def move_stage_to_xy(self, coordinates):
        return self.stage.move_stage_to_xy(coordinates)

    def get_stage_x(self):
        return self.stage.get_stage_x()

    def get_stage_y(self):
        return self.stage.get_stage_y()

    def get_stage_xy(self):
        return self.stage.get_stage_xy()

    def get_stage_xyz(self):
        return self.stage.get_stage_xyz()

    @property
    def last_known_y(self):
        return self.stage.last_known_xy[1]

    @property
    def last_known_x(self):
        return self.stage.last_known_xy[0]

    @property
    def last_known_z(self):
        return self.stage.last_known_z

    def do_sweep(self, z_position):
        return

    def check_cut_cycle_status(self):
        return

