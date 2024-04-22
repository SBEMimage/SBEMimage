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

import numpy as np
import os
from time import sleep
import json

import utils
from constants import Error
from image_io import imread, imwrite
from sem_control import SEM


class SEM_Mock(SEM):
    """Mock SEM (minimal implementation)"""

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        self.mag = 1000
        self.dwell_time = 1
        self.frame_size_selector = self.STORE_RES_DEFAULT_INDEX_TILE
        self.wd = 0.005
        self.stig_x = 0
        self.stig_y = 0
        self.last_known_x = 0
        self.last_known_y = 0
        self.last_known_z = 0
        self.mock_type = self.cfg['acq']['mock_type']
        self.previous_acq_dir = self.cfg['acq']['mock_prev_acq_dir']
        self.detector = ''
        # Select default detector
        self.set_detector(self.syscfg['sem']['default_detector'])

    def turn_eht_on(self):
        return True

    def turn_eht_off(self):
        return True

    def is_eht_on(self):
        return True

    def is_eht_off(self):
        return False

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
        return 30  # micrometres

    def set_aperture_size(self, aperture_size_index):
        pass

    def apply_beam_settings(self):
        pass

    def get_detector_list(self):
        return ['Mock BSD', 'Mock ET', 'Mock XYZ']

    def get_detector(self):
        return self.detector

    def set_detector(self, detector_name):
        if detector_name in self.get_detector_list():
            self.detector = detector_name

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
            self.CYCLE_TIME[frame_size_selector][scan_speed])
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

    def _generate_uniform_noise_image(self, width, height, bitsize=8):
        """Create empty image with random grey values"""
        max_val = 2 ** bitsize - 1
        dtype = np.dtype(f'u{bitsize // 8}')
        mock_image = np.random.randint(0, max_val, size=(height, width), dtype=dtype)  # uniform distribution
        return mock_image

    def _generate_gaussian_noise_image(self, width, height, bitsize=8):
        """Create empty image with random grey values"""
        max_val = 2 ** bitsize - 1
        dtype = np.dtype(f'u{bitsize // 8}')
        gaussian_noise = np.clip(np.random.normal(loc=0.5, scale=0.5 / 3, size=(height, width)), 0, 1)
        mock_image = (gaussian_noise * max_val).astype(dtype)   # gaussian distribution
        return mock_image

    def _calc_shape(self, *args, **kwargs):
        y, x = args
        h, w = y.shape
        xtotal, ytotal = kwargs.get('totals', [0, 0])
        xoffset, yoffset = kwargs.get('offsets', [0, 0])
        image = (1 + np.cos((xoffset + x / w) / xtotal * 2 * np.pi)
                 * np.cos((yoffset + y / h) / ytotal * 2 * np.pi)) / 2
        return image

    def _generate_shape_pattern_image(self, save_path_filename, width, height, bitsize=8):
        """Create empty image with shape grey values"""
        # TODO: set ncols, nrows to make tiled grid pattern
        ncols, nrows = 1, 1
        norm_save_path = os.path.normpath(save_path_filename).replace('\\', '/')
        offset_index = 0
        if '/overviews/' not in norm_save_path:
            index_items = norm_save_path.split('/')[:-1]
            for index_item in reversed(index_items):
                if index_item.startswith('t'):
                    index_str = index_item[1:]
                    if index_str.isnumeric():
                        offset_index = int(index_str)
                        break
        offsets = [offset_index % ncols, int(offset_index / ncols)]
        totals = [ncols, nrows]
        dtype = np.dtype(f'u{bitsize // 8}')
        shape_image = np.fromfunction(self._calc_shape, (height, width), dtype=np.float32,
                                      totals=totals, offsets=offsets)
        noise_image = np.random.random_sample((height, width))
        mock_image = utils.float2int_image(
            np.clip(0.8 * shape_image + 0.2 * noise_image, 0, 1),
            target_dtype=dtype)
        return mock_image

    def _grab_image_from_previous_acq_dir(self, save_path_filename, width, height, bitsize=8):
        """Grab image with matching overview / tile / slice number from previous acquisition.
        If dimensions don't match then generate a random noise image."""
        save_path = os.path.normpath(save_path_filename)
        save_path, save_extension = os.path.splitext(save_path)
        if save_path.endswith('.ome'):
            save_extension = '.ome' + save_extension
            save_path = save_path.rstrip('.ome')
        if '.tif' in save_extension:
            save_path_parts = save_path.split(os.sep)
            save_file = save_path_parts[-1]
            save_path_parts = save_path_parts[:-1]
            save_file_parts = save_file.split('_')
            save_parts = save_path_parts + save_file_parts

            is_overview = False
            for part in save_parts:
                if part.startswith('ov'):
                    is_overview = True

            mock_path = os.path.normpath(self.previous_acq_dir)
            mock_path_parts = mock_path.split(os.sep)
            mock_stack_name = mock_path_parts[-1]

            if is_overview:
                # overview
                ov_index = utils.find_path_numeric_key(save_parts, 'ov')
                slice_index = utils.find_path_numeric_key(save_parts, 's')
                relative_path = utils.ov_relative_save_path(mock_stack_name, ov_index, slice_index)
            else:
                # grid tile
                grid_index = utils.find_path_numeric_key(save_parts, 'g')
                array_index = utils.find_path_numeric_key(save_parts, 'a')
                roi_index = utils.find_path_numeric_key(save_parts, 'roi')
                tile_index = utils.find_path_numeric_key(save_parts, 't')
                slice_index = utils.find_path_numeric_key(save_parts, 's')
                relative_path = utils.tile_relative_save_path(mock_stack_name, grid_index, array_index,
                                                              roi_index, tile_index, slice_index)

            mock_image_path = os.path.join(mock_path, relative_path)

            if os.path.isfile(mock_image_path):
                mock_image = imread(mock_image_path)
                if mock_image.shape[:2] == (height, width):
                    return mock_image

        return self._generate_uniform_noise_image(width, height, bitsize)

    def acquire_frame(self, save_path_filename, stage=None, extra_delay=0):
        width = self.STORE_RES[self.frame_size_selector][0]
        height = self.STORE_RES[self.frame_size_selector][1]
        bitsize = (self.bit_depth_selector + 1) * 8
        mock_type = self.mock_type.lower()

        if 'previous' in mock_type:
            mock_image = self._grab_image_from_previous_acq_dir(save_path_filename, width, height, bitsize)
        elif 'shape' in mock_type:
            mock_image = self._generate_shape_pattern_image(save_path_filename, width, height, bitsize)
        elif 'gaussian' in mock_type:
            mock_image = self._generate_gaussian_noise_image(width, height, bitsize)
        else:
            mock_image = self._generate_uniform_noise_image(width, height, bitsize)

        sleep(self.current_cycle_time + self.additional_cycle_time)
        imwrite(save_path_filename, mock_image, metadata=self.get_grab_metadata(stage))
        return True

    def save_frame(self, save_path_filename, stage=None):
        self.acquire_frame(save_path_filename, stage=stage)
        
    def save_to_cfg(self):
        # Mock SEM settings
        self.cfg['acq']['mock_type'] = self.mock_type
        self.cfg['acq']['mock_prev_acq_dir'] = self.previous_acq_dir
        super().save_to_cfg()
    
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
