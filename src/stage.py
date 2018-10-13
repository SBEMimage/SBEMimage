# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module provides generic get/move functions for the stage.
Depending on the initialization, either the microtome stage or the SEM stage
is used when carrying out the commands.
"""

class Stage():

    def __init__(self, sem, microtome, use_microtome=True):
        # Select the stage to be used:
        if use_microtome:
            self._stage = microtome
        else:
            self._stage = sem
        self.last_known_x = None
        self.last_known_y = None
        self.last_known_z = None
        self.prev_known_z = None

    def get_x(self, wait_time=0):
        return self._stage.get_stage_x()

    def get_y(self, wait_time=0):
        return self._stage.get_stage_y()

    def get_z(self, wait_time=0):
        return self._stage.get_stage_z()

    def get_xy(self, wait_time=0):
        return self._stage.get_stage_xy()

    def move_to_x(self, x):
        return self._stage.move_stage_to_x(x)

    def move_to_y(self, y):
        return self._stage.move_stage_to_y(y)

    def move_to_z(self, z):
        return self._stage.move_stage_to_z(z)

    def move_to_xy(self, coordinates):
        return self._stage.move_stage_to_xy(coordinates)

    def get_last_known_xy(self):
        return (self.last_known_x, self.last_known_y)

    def get_last_known_z(self):
        return self.last_known_z

    def get_prev_known_z(self):
        return self.prev_known_z
