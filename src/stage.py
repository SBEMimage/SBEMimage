# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This class is a wrapper for generic stage functions.
Depending on the initialization, either the microtome stage or the SEM stage
is used when carrying out the commands.
"""

class Stage():

    def __init__(self, sem, microtome, use_microtome=True):
        self.use_microtome = use_microtome
        # Select the stage to be used:
        if use_microtome:
            self._stage = microtome
        else:
            self._stage = sem

    def get_x(self):
        return self._stage.get_stage_x()

    def get_y(self):
        return self._stage.get_stage_y()

    def get_z(self):
        return self._stage.get_stage_z()

    def get_xy(self):
        return self._stage.get_stage_xy()

    def get_xyz(self):
        return self._stage.get_stage_xyz()

    def move_to_x(self, x):
        return self._stage.move_stage_to_x(x)

    def move_to_y(self, y):
        return self._stage.move_stage_to_y(y)

    def move_to_z(self, z):
        return self._stage.move_stage_to_z(z)

    def move_to_xy(self, coordinates):
        return self._stage.move_stage_to_xy(coordinates)

    def get_last_known_xy(self):
        return self._stage.get_last_known_xy()

    def get_last_known_z(self):
        return self._stage.get_last_known_z()

    def get_error_state(self):
        return self._stage.get_error_state()

    def get_error_cause(self):
        return self._stage.get_error_cause()

    def reset_error_state(self):
        self._stage.reset_error_state()

    def get_stage_move_wait_interval(self):
        return self._stage.get_stage_move_wait_interval()

    def set_stage_move_wait_interval(self, wait_interval):
        return self._stage.set_stage_move_wait_interval(wait_interval)

    def get_stage_calibration(self):
        return self._stage.get_stage_calibration()

    def set_stage_calibration(self, current_eht, stage_params):
        if self.use_microtome:
            return self._stage.set_stage_calibration(current_eht, stage_params)

    def get_motor_speeds(self):
        return self._stage.get_motor_speeds()

    def set_motor_speeds(self, motor_speed_x, motor_speed_y):
        if self.use_microtome:
            return self._stage.set_motor_speeds(motor_speed_x, motor_speed_y)

    def update_motor_speed(self):
        if self.use_microtome:
            return self._stage.write_motor_speeds_to_script()
        else:
            return True

    def calculate_stage_move_duration(self, from_x, from_y, to_x, to_y):
        return self._stage.calculate_stage_move_duration(from_x, from_y, to_x, to_y)
