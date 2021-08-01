# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""
This module controls the microtome hardware (knife and motorized stage) via
DigitalMicrograph (3View) or a serial port (katana). In addition, it implements an
alternative removal approach via the separate GCIB class.


                                  BFRemover (abc)
                                /               \
                               /                 \
            Microtome (base class)               GCIB
              /                \
             /                  \
     Microtome_3View     Microtome_katana

"""

import json
from collections import deque
from abc import ABC, abstractmethod
import utils
from utils import Error


class BFRemover(ABC):
    """WIP
    Todo:
        * rename abstract methods which are too specific (e.g. cut, knife, etc).
        * add __init__ with generic properties here? e.g. passing cfg and sys_cfg and setting device_name
    """

    def __init__(self, config, sysconfig):
        self.cfg = config
        self.syscfg = sysconfig
        self.error_state = Error.none
        self.error_info = ''
        self.device_name = 'Abstract block-face remover.'
        self.full_cut_duration = None  # use @property, @abstractmethod

    def __str__(self):
        return self.device_name

    # necessary methods which must be implemented
    @abstractmethod
    def save_to_cfg(self):
        pass

    @abstractmethod
    def do_full_cut(self):
        """Perform a full cut cycle. This is the only knife control function
           used during stack acquisitions.
        """
        pass

    @abstractmethod
    def do_sweep(self, z_position):
        """Perform a sweep by cutting slightly above the surface."""
        pass

    def move_stage_to_z(self, z):
        """Move stage to new z position. Used during stack acquisition
           before each cut and for sweeps. Required in Acquisition.do_cut.
        """
        pass

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates X/Y. This function is called during
           acquisitions. It includes waiting times. The other move functions
           below do not.
        """
        raise NotImplementedError

    def reset_error_state(self):
        self.error_state = Error.none
        self.error_info = ''

    # Optional motor movements, e.g. these are available if SEM stage is active and must then
    # not be used from this class.

    def move_stage_to_x(self, x):
        # only used for testing
        raise NotImplementedError

    def move_stage_to_y(self, y):
        # only used for testing
        raise NotImplementedError

    def get_stage_xy(self):
        raise NotImplementedError

    def get_stage_x(self):
        return self.get_stage_xy()[0]

    def get_stage_y(self):
        return self.get_stage_xy()[1]

    def get_stage_xyz(self):
        x, y = self.get_stage_xy()
        z = self.get_stage_z()
        return x, y, z

    def get_stage_z(self, wait_interval=0.5):
        """Get current Z coordinate from DM"""
        raise NotImplementedError


class Microtome(BFRemover):
    """Base class for microtome control. It implements minimum config/parameter
    handling. Undefined methods have to be implemented in the child class,
    otherwise NotImplementedError is raised.
    """
    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        self.motor_warning = False  # True when motors slower than expected
        # Load device name and other settings from sysconfig. These
        # settings overwrite the settings in config.
        recognized_devices = json.loads(
            self.syscfg['device']['microtome_recognized'])
        # Use device selection from system configuration
        self.cfg['microtome']['device'] = self.syscfg['device']['microtome']
        if self.cfg['microtome']['device'] not in recognized_devices:
            self.cfg['microtome']['device'] = 'NOT RECOGNIZED'
        self.device_name = self.cfg['microtome']['device']
        # Get microtome stage limits from systemcfg
        # self.stage_limits: [min_x, max_x, min_y, max_y] in micrometres
        self.stage_limits = json.loads(
            self.syscfg['stage']['microtome_stage_limits'])
        # Get microtome motor speeds from syscfg
        self.motor_speed_x, self.motor_speed_y = (
            json.loads(self.syscfg['stage']['microtome_motor_speed']))
        # Knife settings in system config override the session config settings.
        self.cfg['microtome']['full_cut_duration'] = (
            self.syscfg['knife']['full_cut_duration'])
        self.cfg['microtome']['sweep_distance'] = (
            self.syscfg['knife']['sweep_distance'])
        # The following variables contain the last known (verified) position
        # of the microtome stage in X, Y, Z.
        self.last_known_x = None
        self.last_known_y = None
        self.last_known_z = None
        # self.prev_known_z stores the previous Z coordinate. It is used to
        # ensure that Z moves cannot be larger than 200 nm in safe mode.
        self.prev_known_z = None
        # self.stage_z_prev_session stores the last known Z coordinate at the end of
        # the previous session associated with the current session configuration.
        if self.cfg['microtome']['last_known_z'].lower() == 'none':
            self.stage_z_prev_session = None
        else:
            try:
                self.stage_z_prev_session = float(
                    self.cfg['microtome']['last_known_z'])
            except Exception as e:
                self.error_state = Error.configuration
                self.error_info = str(e)
                return
        try:
            self.z_range = json.loads(
                self.syscfg['stage']['microtome_z_range'])
        except Exception as e:
            self.error_state = Error.configuration
            self.error_info = str(e)
            return
        self.simulation_mode = (
            self.cfg['sys']['simulation_mode'].lower() == 'true')
        self.use_oscillation = (
            self.cfg['microtome']['knife_oscillation'].lower() == 'true')

        # Catch errors that occur while reading configuration and converting
        # the string values into floats or integers
        try:
            # Knife cut speed in nm/s
            self.knife_cut_speed = int(float(
                self.cfg['microtome']['knife_cut_speed']))
            # Knife cut speed for fast cutting, typically for approach, nm/s
            self.knife_fast_speed = int(float(
                self.cfg['microtome']['knife_fast_speed']))
            # Knife retract speed in nm/s
            self.knife_retract_speed = int(float(
                self.cfg['microtome']['knife_retract_speed']))
            # Start and end position of cutting window, in nm
            self.cut_window_start = int(float(
                self.cfg['microtome']['knife_cut_start']))
            self.cut_window_end = int(float(
                self.cfg['microtome']['knife_cut_end']))
            # Knife oscillation frequency in Hz
            self.oscillation_frequency = int(float(
                self.cfg['microtome']['knife_osc_frequency']))
            # Knife oscillation amplitude in nm
            self.oscillation_amplitude = int(float(
                self.cfg['microtome']['knife_osc_amplitude']))
            # Duration of a full cut cycle in seconds
            self.full_cut_duration = float(
                self.cfg['microtome']['full_cut_duration'])
            # Sweep distance (lowering of Z position in nm before sweep)
            self.sweep_distance = int(float(
                self.cfg['microtome']['sweep_distance']))
            if (self.sweep_distance < 30) or (self.sweep_distance > 1000):
                # If outside permitted range, set to 70 nm as default
                self.sweep_distance = 70
                self.cfg['microtome']['sweep_distance'] = '70'
            # self.stage_move_wait_interval is the amount of time in seconds
            # that SBEMimage waits after a stage move before taking an image.
            self.stage_move_wait_interval = float(
                self.cfg['microtome']['stage_move_wait_interval'])
            # Motor tolerance
            self.xy_tolerance = float(
                self.syscfg['stage']['microtome_xy_tolerance'])
            self.z_tolerance = float(
                self.syscfg['stage']['microtome_z_tolerance'])
            # Motor diagnostics
            self.total_xyz_move_counter = json.loads(
                self.syscfg['stage']['microtome_xyz_move_counter'])
            self.slow_xy_move_counter = int(
                self.syscfg['stage']['microtome_slow_xy_move_counter'])
            self.failed_xyz_move_counter = json.loads(
                self.syscfg['stage']['microtome_failed_xyz_move_counter'])
            # Maintenance moves
            self.use_maintenance_moves = (
                self.syscfg['stage']['microtome_use_maintenance_moves'].lower()
                == 'true')
            self.maintenance_move_interval = int(
                self.syscfg['stage']['microtome_maintenance_move_interval'])
            # Deques for last 200 moves (0 = ok; 1 = warning)
            self.slow_xy_move_warnings = deque(maxlen=200)
            self.failed_x_move_warnings = deque(maxlen=200)
            self.failed_y_move_warnings = deque(maxlen=200)
            self.failed_z_move_warnings = deque(maxlen=200)

        except Exception as e:
            self.error_state = Error.configuration
            self.error_info = str(e)

    def save_to_cfg(self):
        self.cfg['microtome']['stage_move_wait_interval'] = str(
            self.stage_move_wait_interval)
        # Save stage limits in cfg and syscfg
        self.cfg['microtome']['stage_min_x'] = str(self.stage_limits[0])
        self.cfg['microtome']['stage_max_x'] = str(self.stage_limits[1])
        self.cfg['microtome']['stage_min_y'] = str(self.stage_limits[2])
        self.cfg['microtome']['stage_max_y'] = str(self.stage_limits[3])
        self.syscfg['stage']['microtome_stage_limits'] = str(self.stage_limits)
        # Save motor speeds to cfg and syscfg
        self.cfg['microtome']['motor_speed_x'] = str(self.motor_speed_x)
        self.cfg['microtome']['motor_speed_y'] = str(self.motor_speed_y)
        self.syscfg['stage']['microtome_motor_speed'] = str(
            [self.motor_speed_x, self.motor_speed_y])
        self.cfg['microtome']['knife_cut_speed'] = str(int(
            self.knife_cut_speed))
        self.cfg['microtome']['knife_retract_speed'] = str(int(
            self.knife_retract_speed))
        self.cfg['microtome']['knife_fast_speed'] = str(int(
            self.knife_fast_speed))
        self.cfg['microtome']['knife_cut_start'] = str(int(
            self.cut_window_start))
        self.cfg['microtome']['knife_cut_end'] = str(int(
            self.cut_window_end))
        self.cfg['microtome']['knife_oscillation'] = str(self.use_oscillation)
        self.cfg['microtome']['knife_osc_frequency'] = str(int(
            self.oscillation_frequency))
        self.cfg['microtome']['knife_osc_amplitude'] = str(int(
            self.oscillation_amplitude))
        self.cfg['microtome']['last_known_z'] = str(self.last_known_z)
        # Save full cut duration in both cfg and syscfg
        self.cfg['microtome']['full_cut_duration'] = str(self.full_cut_duration)
        self.syscfg['knife']['full_cut_duration'] = str(self.full_cut_duration)
        # Motor tolerance
        self.syscfg['stage']['microtome_xy_tolerance'] = str(self.xy_tolerance)
        self.syscfg['stage']['microtome_z_tolerance'] = str(self.z_tolerance)
        # Motor diagnostics
        # Round floats
        self.total_xyz_move_counter = utils.round_floats(
            self.total_xyz_move_counter)
        self.syscfg['stage']['microtome_xyz_move_counter'] = json.dumps(
            self.total_xyz_move_counter)
        self.syscfg['stage']['microtome_slow_xy_move_counter'] = str(
            self.slow_xy_move_counter)
        self.syscfg['stage']['microtome_failed_xyz_move_counter'] = json.dumps(
            self.failed_xyz_move_counter)
        # Maintenance moves
        self.syscfg['stage']['microtome_use_maintenance_moves'] = str(
            self.use_maintenance_moves)
        self.syscfg['stage']['microtome_maintenance_move_interval'] = str(int(
            self.maintenance_move_interval))

    def __str__(self):
        return self.device_name

    def do_full_cut(self):
        """Perform a full cut cycle. This is the only knife control function
           used during stack acquisitions.
        """
        raise NotImplementedError

    def do_full_approach_cut(self):
        """Perform a full cut cycle under the assumption that knife is
           already neared."""
        raise NotImplementedError

    def do_sweep(self, z_position):
        """Perform a sweep by cutting slightly above the surface."""
        if (((self.sweep_distance < 30) or (self.sweep_distance > 1000))
                and self.error_state == Error.none):
            self.error_state = Error.sweeping
            self.error_info = 'microtome.do_sweep: sweep distance out of range'
        elif self.error_state == Error.none:
            raise NotImplementedError

    def cut(self):
        # only used for testing
        raise NotImplementedError

    def retract_knife(self):
        # only used for testing
        raise NotImplementedError

    def set_motor_speeds(self, motor_speed_x, motor_speed_y):
        self.motor_speed_x = motor_speed_x
        self.motor_speed_y = motor_speed_y
        return self.update_motor_speeds_in_dm_script()

    def measure_motor_speeds(self):
        raise NotImplementedError

    def update_motor_speeds_in_dm_script(self):
        raise NotImplementedError

    def rel_stage_move_duration(self, target_x, target_y):
        """Use the last known position and the given target position
           to calculate how much time it will take for the motors to move
           to target position. Add self.stage_move_wait_interval.
        """
        duration_x = abs(target_x - self.last_known_x) / self.motor_speed_x
        duration_y = abs(target_y - self.last_known_y) / self.motor_speed_y
        return duration_x + self.stage_move_wait_interval, duration_y + self.stage_move_wait_interval

    def stage_move_duration(self, from_x, from_y, to_x, to_y):
        """Return the total duration for a move including the
        stage_move_wait_interval.
        """
        duration_x = abs(to_x - from_x) / self.motor_speed_x
        duration_y = abs(to_y - from_y) / self.motor_speed_y
        return max(duration_x, duration_y) + self.stage_move_wait_interval

    def stop_script(self):
        raise NotImplementedError

    def near_knife(self):
        raise NotImplementedError

    def clear_knife(self):
        raise NotImplementedError

    def check_cut_cycle_status(self):
        raise NotImplementedError

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
        raise NotImplementedError
