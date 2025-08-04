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

from abc import ABC, abstractmethod

from constants import Error


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
