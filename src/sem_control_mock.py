# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2021 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This file contains the class SEM_Mock that simulates the behaviour of 
an SEM for testing purposes.
"""

import random
import numpy as np

from time import sleep
from skimage import io

from sem_control import SEM
from utils import Error
import os


class SEM_Mock(SEM):
    """Mock SEM (minimal implementation)"""

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        self.eht_on = False
        self.mag = 1000
        self.dwell_time = 1
        self.frame_size_selector = self.STORE_RES_DEFAULT_INDEX_TILE
        self.wd = 0.005
        self.stig_x = 0
        self.stig_y = 0
        self.last_known_x = 0
        self.last_known_y = 0
        self.last_known_z = 0
        self.mock_type = "noise"
        self.previous_acq_dir = None

    def turn_eht_on(self):
        self.eht_on = True
        return True

    def turn_eht_off(self):
        self.eht_on = False
        return True

    def is_eht_on(self):
        return self.eht_on

    def is_eht_off(self):
        return not self.eht_on

    def get_eht(self):
        return self.target_eht

    def set_eht(self, target_eht):
        self.target_eht = round(target_eht, 2)
        return True

    def has_vp(self):
        return False

    def is_hv_on(self):
        return True

    def is_vp_on(self):
        return False

    def get_chamber_pressure(self):
        raise NotImplementedError

    def get_vp_target(self):
        raise NotImplementedError

    def set_hv(self):
        raise NotImplementedError

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
        raise NotImplementedError

    def set_aperture_size(self, aperture_size_index):
        raise NotImplementedError

    def apply_beam_settings(self):
        pass

    def apply_grab_settings(self):
        self.apply_frame_settings(
            self.grab_frame_size_selector,
            self.grab_pixel_size,
            self.grab_dwell_time)

    def apply_frame_settings(self, frame_size_selector, pixel_size, dwell_time):
        self.set_mag(int(self.MAG_PX_SIZE_FACTOR /
            (self.STORE_RES[frame_size_selector][0] * pixel_size)))
        self.set_dwell_time(dwell_time)
        self.set_frame_size(frame_size_selector)
        scan_speed = self.DWELL_TIME.index(dwell_time)
        self.current_cycle_time = (
            self.CYCLE_TIME[frame_size_selector][scan_speed] + 0.3)
        if self.current_cycle_time < 0.8:
            self.current_cycle_time = 0.8
        return True

    def get_frame_size_selector(self):
        return self.frame_size_selector

    def get_frame_size(self):
        raise NotImplementedError

    def set_frame_size(self, frame_size_selector):
        self.frame_size_selector = frame_size_selector
        return True

    def get_mag(self):
        return self.mag

    def set_mag(self, target_mag):
        self.mag = target_mag
        return True

    def get_pixel_size(self):
        return self.MAG_PX_SIZE_FACTOR / (self.mag
                   * self.STORE_RES[self.frame_size_selector][0])

    def set_pixel_size(self, pixel_size):
        self.mag = int(self.MAG_PX_SIZE_FACTOR /
                       (self.STORE_RES[self.frame_size_selector][0] * pixel_size))
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

    def _generate_random_image(self, width, height):
        """Create empty image with random grey values"""
        # TODO: Add location-dependent patterns
        mock_image = np.zeros((height, width), dtype=np.uint8)
        for row in range(height):
            for col in range(width):
                mock_image[row, col] = random.randint(0, 255)
        return mock_image

    def _grab_image_from_previous_acq_dir(self, save_path_filename, width, height):
        """Grab image with matching overview id / grid id and slice number from previous acquisition. If dimensions
        don't match then generate a random noise image."""

        if not save_path_filename.endswith(".tif"):
            return self._generate_random_image(width, height)

        save_path = os.path.normpath(save_path_filename)
        save_path = save_path.split(os.sep)
        mock_path = os.path.normpath(self.previous_acq_dir)
        mock_path = mock_path.split(os.sep)

        slice_no = save_path[-1].split("_")[-1]
        mock_stack_name = mock_path[-1]

        if save_path[-2].startswith("ov"):
            # path for overviews
            overview_id = save_path[-2]
            mock_image_name = "_".join([mock_stack_name, overview_id, slice_no])
            mock_image_path = os.path.join(self.previous_acq_dir, "overviews", overview_id, mock_image_name)
        else:
            # path for tiles
            grid_id = save_path[-3]
            tile_id = save_path[-2]
            mock_image_name = "_".join([mock_stack_name, grid_id, tile_id, slice_no])
            mock_image_path = os.path.join(self.previous_acq_dir, "tiles", grid_id, tile_id, mock_image_name)

        if os.path.isfile(mock_image_path):
            mock_image = io.imread(mock_image_path)
            if mock_image.shape == (height, width):
                return mock_image

        return self._generate_random_image(width, height)

    def acquire_frame(self, save_path_filename, extra_delay=0):
        width = self.STORE_RES[self.frame_size_selector][0]
        height = self.STORE_RES[self.frame_size_selector][1]

        if self.mock_type == "noise":
            mock_image = self._generate_random_image(width, height)
        else:
            mock_image = self._grab_image_from_previous_acq_dir(save_path_filename, width, height)

        sleep(self.current_cycle_time + self.additional_cycle_time)
        io.imsave(save_path_filename, mock_image,
                  check_contrast=False)
        return True

    def save_frame(self, save_path_filename):
        self.acquire_frame(save_path_filename)

    def get_wd(self):
        return self.wd

    def set_wd(self, target_wd):
        self.wd = target_wd
        return True

    def get_stig_xy(self):
        return self.stig_x, self.stig_y

    def set_stig_xy(self, target_stig_x, target_stig_y):
        self.stig_x = target_stig_x
        self.stig_y = target_stig_y
        return True

    def get_stig_x(self):
        return self.stig_x

    def set_stig_x(self, target_stig_x):
        self.stig_x = target_stig_x
        return True

    def get_stig_y(self):
        return self.stig_y

    def set_stig_y(self, target_stig_y):
        self.stig_y = target_stig_y
        return True

    def set_beam_blanking(self, enable_blanking):
        return True

    def run_autofocus(self):
        return True

    def run_autostig(self):
        return True

    def run_autofocus_stig(self):
        return True

    def get_stage_x(self):
        return self.last_known_x

    def get_stage_y(self):
        return self.last_known_y

    def get_stage_z(self):
        return self.last_known_z

    def get_stage_xy(self):
        return self.last_known_x, self.last_known_y

    def get_stage_xyz(self):
        return self.last_known_x, self.last_known_y, self.last_known_z

    def move_stage_to_x(self, x):
        self.last_known_x = x

    def move_stage_to_y(self, y):
        self.last_known_y = y

    def move_stage_to_z(self, z):
        self.last_known_z = z

    def move_stage_to_xy(self, coordinates):
        self.last_known_x, self.last_known_y = coordinates

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
        return True