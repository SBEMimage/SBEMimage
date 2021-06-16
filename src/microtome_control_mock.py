# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2021 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This file contains the class Microtome_Mock that simulates the behaviour of 
a microtome (including XY stage control) for testing purposes.
"""


from utils import Error
from microtome_control import Microtome


class Microtome_Mock(Microtome):
    """Mock microtome (minimal implementation)"""

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        self.last_known_x = 0
        self.last_known_y = 0
        self.last_known_z = 0

    def do_full_cut(self):
        pass

    def do_full_approach_cut(self):
        pass

    def do_sweep(self, z_position):
        """Perform a sweep by cutting slightly above the surface."""
        if (((self.sweep_distance < 30) or (self.sweep_distance > 1000))
                and self.error_state == Error.none):
            self.error_state = Error.sweeping
            self.error_info = 'microtome.do_sweep: sweep distance out of range'
        elif self.error_state == Error.none:
            pass

    def cut(self):
        pass

    def retract_knife(self):
        pass

    def set_motor_speeds(self, motor_speed_x, motor_speed_y):
        self.motor_speed_x = motor_speed_x
        self.motor_speed_y = motor_speed_y
        return True

    def measure_motor_speeds(self):
        raise NotImplementedError

    def update_motor_speeds_in_dm_script(self):
        raise NotImplementedError

    def stop_script(self):
        raise NotImplementedError

    def near_knife(self):
        pass

    def clear_knife(self):
        pass

    def check_cut_cycle_status(self):
        return 0  # delay in seconds

    def get_stage_xy(self):
        return self.last_known_x, self.last_known_y

    def move_stage_to_xy(self, coordinates):
        x, y = coordinates
        self.last_known_x = x 
        self.last_known_y = y 

    def get_stage_z(self, wait_interval=1.0):
        return self.last_known_z

    def move_stage_to_z(self, z, safe_mode=True):
        if (((self.last_known_z >= 0) and (abs(z - self.last_known_z) > 0.205))
                and self.error_state == Error.none and safe_mode):
            self.error_state = Error.stage_z_move
            self.error_info = ('microtome.move_stage_to_z: Z move too '
                               'large (> 200 nm)')
        else:
            self.last_known_z = z

    def reset_error_state(self):
        self.error_state = Error.none
        self.error_info = ''
        