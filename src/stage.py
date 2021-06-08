# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This class is a wrapper for generic stage functions. Within the SBEMimage
acquisition loop and in other SBEMimage modules, commands like this can be used
to control the stage: self.stage.get_x(), self.stage.move_to_xy()...
Depending on the initialization, either the microtome stage or the SEM stage or
some other custom stage will be used when carrying out the commands.
"""


class Stage:
    def __init__(self, sem, microtome, use_microtome=True):
        self.microtome = microtome
        self.use_microtome = use_microtome
        # Select the stage to be used:
        if use_microtome and microtome.device_name not in ['ConnectomX katana', 'GCIB']:
            # Use microtome for X, Y, Z control
            self._stage = microtome
            self.use_microtome_xy = True
            self.use_microtome_z = True
        elif use_microtome:
            # Use SEM stage for X, Y control, and microtome for Z control
            self._stage = sem
            self.use_microtome_xy = False
            self.use_microtome_z = True
        else:
            # Use SEM stage for X, Y, Z control
            self._stage = sem
            self.use_microtome_xy = False
            self.use_microtome_z = False

    def __str__(self):
        return str(self._stage)

    def get_x(self):
        return self._stage.get_stage_x()

    def get_y(self):
        return self._stage.get_stage_y()

    def get_z(self):
        if self.use_microtome_z:
            return self.microtome.get_stage_z()
        else:
            return self._stage.get_stage_z()

    def get_xy(self):
        return self._stage.get_stage_xy()

    def get_xyz(self):
        if self.use_microtome_z:
            x, y = self._stage.get_stage_xy()
            z = self.microtome.get_stage_z()
            return x, y, z
        else:
            return self._stage.get_stage_xyz()

    def move_to_x(self, x):
        return self._stage.move_stage_to_x(x)

    def move_to_y(self, y):
        return self._stage.move_stage_to_y(y)

    def move_to_z(self, z, safe_mode=True):
        if self.use_microtome_z:
            return self.microtome.move_stage_to_z(z, safe_mode)
        else:
            return self._stage.move_stage_to_z(z)

    def move_to_xy(self, coordinates):
        return self._stage.move_stage_to_xy(coordinates)

    @property
    def last_known_x(self):
        return self._stage.last_known_x

    @property
    def last_known_y(self):
        return self._stage.last_known_y

    @property
    def last_known_xy(self):
        return self._stage.last_known_x, self._stage.last_known_y

    @property
    def last_known_z(self):
        if self.use_microtome_z:
            return self.microtome.last_known_z
        else:
            return self._stage.last_known_z

    @property
    def error_state(self):
        return self._stage.error_state

    @error_state.setter
    def error_state(self, new_error_state):
        self._stage.error_state = new_error_state

    @property
    def error_info(self):
        return self._stage.error_info

    def reset_error_state(self):
        self._stage.reset_error_state()

    @property
    def stage_move_wait_interval(self):
        return self._stage.stage_move_wait_interval

    @stage_move_wait_interval.setter
    def stage_move_wait_interval(self, wait_interval):
        self._stage.stage_move_wait_interval = wait_interval

    @property
    def motor_speed_x(self):
        return self._stage.motor_speed_x

    @property
    def motor_speed_y(self):
        return self._stage.motor_speed_y

    def set_motor_speeds(self, motor_speed_x, motor_speed_y):
        if self.use_microtome and self.use_microtome_xy and not self.microtome.device_name == 'GCIB':
            return self._stage.set_motor_speeds(motor_speed_x, motor_speed_y)
        elif self.microtome.device_name == 'GCIB':
            return True
        else:
            # motor speeds can currently not be set for SEM stage
            return False

    def update_motor_speed(self):
        if self.use_microtome and self.use_microtome_xy and self.microtome.device_name == 'Gatan 3View':
            return self._stage.update_motor_speeds_in_dm_script()
        elif self.microtome.device_name in ['ConnectomX katana', 'GCIB']:
            return True
        else:
            # Speeds can currently not be updated for SEM stage
            return False

    def measure_motor_speeds(self):
        if self.use_microtome and self.use_microtome_xy and not self.microtome.device_name == 'GCIB':
            return self._stage.measure_motor_speeds()
        else:
            # Speeds can currently not be measured for SEM stage
            return None, None

    def stage_move_duration(self, from_x, from_y, to_x, to_y):
        return self._stage.stage_move_duration(
            from_x, from_y, to_x, to_y)

    @property
    def limits(self):
        return self._stage.stage_limits

    def pos_within_limits(self, s_coordinates):
        """Return True if s_coordinates are located within the motor limits
        of the current stage."""
        limits = self._stage.stage_limits
        within_x = limits[0] <= s_coordinates[0] <= limits[1]
        within_y = limits[2] <= s_coordinates[1] <= limits[3]
        return within_x and within_y

    @property
    def xy_tolerance(self):
        return self._stage.xy_tolerance

    @property
    def z_tolerance(self):
        return self._stage.z_tolerance

    @property
    def total_xyz_move_counter(self):
        return self._stage.total_xyz_move_counter

    @property
    def failed_xyz_move_counter(self):
        return self._stage.failed_xyz_move_counter

    @property
    def slow_xy_move_counter(self):
        return self._stage.slow_xy_move_counter

    @property
    def slow_xy_move_warnings(self):
        return self._stage.slow_xy_move_warnings

    @property
    def failed_x_move_warnings(self):
        return self._stage.failed_x_move_warnings

    @property
    def failed_y_move_warnings(self):
        return self._stage.failed_y_move_warnings

    @property
    def failed_z_move_warnings(self):
        return self._stage.failed_z_move_warnings

    def reset_stage_move_counters(self):
        return self._stage.reset_stage_move_counters()

    @property
    def use_maintenance_moves(self):
        return self._stage.use_maintenance_moves

    @property
    def maintenance_move_interval(self):
        return self._stage.maintenance_move_interval
