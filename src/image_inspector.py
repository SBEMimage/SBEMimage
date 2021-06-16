# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module provides integrity and quality checks (including debris
detection) for overview and tile images."""

import os
import json
import psutil
import numpy as np

from time import sleep
from imageio import imwrite
from scipy.signal import medfilt2d
from collections import deque
from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt5.QtGui import QPixmap

import utils

# Remove image size limit in PIL (Pillow) to prevent DecompressionBombError
Image.MAX_IMAGE_PIXELS = None

# Preview image width in pixels
PREVIEW_IMG_WIDTH = 512

class ImageInspector:

    def __init__(self, config, overview_manager, grid_manager):
        self.cfg = config
        self.ovm = overview_manager
        self.gm = grid_manager
        self.tile_means = {}
        self.tile_stddevs = {}
        self.tile_reslice_line = {}
        self.ov_means = {}
        self.ov_stddevs = {}
        self.ov_images = {}
        self.ov_reslice_line = {}
        self.prev_img_mean_stddev = [0, 0]
        # Moving average of mean and stddev differences in debris detection
        # region(s)
        self.mean_diffs = deque(maxlen=10)
        self.stddev_diffs = deque(maxlen=10)

        # Load parameters for OV/tile monitoring from config
        self.mean_lower_limit = int(self.cfg['monitoring']['mean_lower_limit'])
        self.mean_upper_limit = int(self.cfg['monitoring']['mean_upper_limit'])
        self.stddev_lower_limit = int(
            self.cfg['monitoring']['stddev_lower_limit'])
        self.stddev_upper_limit = int(
            self.cfg['monitoring']['stddev_upper_limit'])
        self.monitoring_tile_list = json.loads(
            self.cfg['monitoring']['tile_list'])
        self.tile_mean_threshold = float(
            self.cfg['monitoring']['tile_mean_threshold'])
        self.tile_stddev_threshold = float(
            self.cfg['monitoring']['tile_stddev_threshold'])

        # Load parameters for debris detection from config
        self.debris_detection_method = int(
            self.cfg['debris']['detection_method'])
        self.debris_roi_min_quadrant_area = int(
            self.cfg['debris']['min_quadrant_area'])
        self.mean_diff_threshold = float(
            self.cfg['debris']['mean_diff_threshold'])
        self.stddev_diff_threshold = float(
            self.cfg['debris']['stddev_diff_threshold'])
        self.image_diff_threshold = int(
            self.cfg['debris']['image_diff_threshold'])
        self.median_filter_kernel_size = int(
            self.cfg['debris']['median_filter_kernel_size'])
        self.image_diff_hist_lower_limit = int(
            self.cfg['debris']['image_diff_hist_lower_limit'])
        self.histogram_diff_threshold = int(
            self.cfg['debris']['histogram_diff_threshold'])

        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')

    def save_to_cfg(self):
        """Save all parameters managed by image_inspector to config."""
        self.cfg['monitoring']['mean_lower_limit'] = str(self.mean_lower_limit)
        self.cfg['monitoring']['mean_upper_limit'] = str(self.mean_upper_limit)
        self.cfg['monitoring']['stddev_lower_limit'] = str(
            self.stddev_lower_limit)
        self.cfg['monitoring']['stddev_upper_limit'] = str(
            self.stddev_upper_limit)
        self.cfg['monitoring']['tile_list'] = json.dumps(
            self.monitoring_tile_list)
        self.cfg['monitoring']['tile_mean_threshold'] = str(
            self.tile_mean_threshold)
        self.cfg['monitoring']['tile_stddev_threshold'] = str(
            self.tile_stddev_threshold)
        self.cfg['debris']['detection_method'] = str(
            self.debris_detection_method)
        self.cfg['debris']['min_quadrant_area'] = str(
            self.debris_roi_min_quadrant_area)
        self.cfg['debris']['mean_diff_threshold'] = str(
            self.mean_diff_threshold)
        self.cfg['debris']['stddev_diff_threshold'] = str(
            self.stddev_diff_threshold)
        self.cfg['debris']['image_diff_threshold'] = str(
            self.image_diff_threshold)
        self.cfg['debris']['median_filter_kernel_size'] = str(
            self.median_filter_kernel_size)
        self.cfg['debris']['image_diff_hist_lower_limit'] = str(
            self.image_diff_hist_lower_limit)
        self.cfg['debris']['histogram_diff_threshold'] = str(
            self.histogram_diff_threshold)

    def load_and_inspect(self, filename):
        """Load filename with error handling, convert to numpy array, calculate
        mean and stddev, and check if image appears incomplete.
        """
        img = None
        mean, stddev = 0, 0
        load_error = False
        load_exception = ''
        grab_incomplete = False

        try:
            # TODO: Switch to skimage / imageio?
            img = Image.open(filename)
        except Exception as e:
            load_exception = str(e)
            load_error = True
        if not load_error:
            img = np.array(img)

            # Calculate mean and stddev
            mean = np.mean(img)
            stddev = np.std(img)

            # Was complete image grabbed? Test if first or final line of image
            # is black/white/uniform greyscale
            height = img.shape[0]
            first_line = img[0:1,:]
            final_line = img[height-1:height,:]
            grab_incomplete = (np.min(first_line) == np.max(first_line) or
                               np.min(final_line) == np.max(final_line))

        return img, mean, stddev, load_error, load_exception, grab_incomplete


    def process_tile(self, filename, grid_index, tile_index, slice_counter):
        range_test_passed, slice_by_slice_test_passed = False, False
        frozen_frame_error = False
        tile_selected = False

        # Skip tests in MagC mode if memory usage too high
        # TODO: Look into this
        if self.magc_mode and psutil.virtual_memory()[2] > 50:
            print('### WARNING ### Memory usage '
                  + str(psutil.virtual_memory()[2])
                  + ' too high. Tile checks will be skipped.')
            range_test_passed, slice_by_slice_test_passed = True, True
            frozen_frame_error = False
            grab_incomplete = False
            load_error = False
            tile_selected = True
            return (np.zeros((1000,1000)), mean, stddev,
                    range_test_passed, slice_by_slice_test_passed,
                    tile_selected,
                    load_error, grab_incomplete, frozen_frame_error)
        # End of MagC-specific code

        img, mean, stddev, load_error, load_exception, grab_incomplete = (
            self.load_and_inspect(filename))

        if not load_error:

            tile_key = ('g' + str(grid_index).zfill(utils.GRID_DIGITS)
                        + '_' + 't' + str(tile_index).zfill(utils.TILE_DIGITS))
            tile_key_short = str(grid_index) + '.' + str(tile_index)

            # Save preview image
            height, width = img.shape[0], img.shape[1]
            img_tostring = img.tostring()
            preview_img = Image.frombytes(
                'L', (width, height),
                img_tostring).resize((
                    PREVIEW_IMG_WIDTH, 
                    int(PREVIEW_IMG_WIDTH * height / width)), 
                    resample=Image.BILINEAR)

            # Convert to QPixmap and save in grid_manager
            self.gm[grid_index][tile_index].preview_img = QPixmap.fromImage(
                ImageQt(preview_img))

            # Compare with previous mean and std to check for frozen frame
            # error in SmartSEM
            if self.prev_img_mean_stddev == [mean, stddev]:
                frozen_frame_error = True
            else:
                frozen_frame_error = False
                self.prev_img_mean_stddev = [mean, stddev]

            # Save reslice line in memory. Take a 400-px line from the centre
            # of the image. This works for all frame resolutions.
            img_reslice_line = img[int(height/2):int(height/2)+1,
                int(width/2)-200:int(width/2)+200]
            self.tile_reslice_line[tile_key] = (img_reslice_line)

            # Save mean and std in memory. Add key to dictionary if tile is new.
            if not tile_key in self.tile_means:
                self.tile_means[tile_key] = []
            # Save mean and stddev in tile list
            if len(self.tile_means[tile_key]) > 1:
                # Remove the oldest entry
                self.tile_means[tile_key].pop(0)
            # Add the newest
            self.tile_means[tile_key].append((slice_counter, mean))

            if not tile_key in self.tile_stddevs:
                self.tile_stddevs[tile_key] = []
            if len(self.tile_stddevs[tile_key]) > 1:
                self.tile_stddevs[tile_key].pop(0)
            self.tile_stddevs[tile_key].append((slice_counter, stddev))

            if (tile_key_short in self.monitoring_tile_list
                or 'all' in self.monitoring_tile_list):
                if len(self.tile_means[tile_key]) > 1:
                    diff_mean = abs(self.tile_means[tile_key][0][1]
                                    - self.tile_means[tile_key][1][1])
                else:
                    diff_mean = 0

                if len(self.tile_stddevs[tile_key]) > 1:
                    diff_stddev = abs(self.tile_stddevs[tile_key][0][1]
                                      - self.tile_stddevs[tile_key][1][1])
                else:
                    diff_stddev = 0
                slice_by_slice_test_passed = (
                    (diff_mean <= self.tile_mean_threshold)
                    and (diff_stddev <= self.tile_stddev_threshold))
            else:
                slice_by_slice_test_passed = None

            # Perform range test
            range_test_passed = (
                (self.mean_lower_limit <= mean <= self.mean_upper_limit) and
                (self.stddev_lower_limit <= stddev <= self.stddev_upper_limit))

            # Perform other tests here to decide whether tile is selected for
            # acquisition or discarded:
            # ...
            tile_selected = True

            del img_tostring
            del preview_img

        return (img, mean, stddev,
                range_test_passed, slice_by_slice_test_passed, tile_selected,
                load_error, load_exception, grab_incomplete, frozen_frame_error)

    def save_tile_stats(self, base_dir, grid_index, tile_index, slice_counter):
        """Write mean and SD of specified tile to disk."""
        success = True
        error_msg = ''
        tile_key = ('g' + str(grid_index).zfill(utils.GRID_DIGITS)
                    + '_' + 't' + str(tile_index).zfill(utils.TILE_DIGITS))
        if tile_key in self.tile_means and tile_key in self.tile_stddevs:
            stats_filename = os.path.join(
                base_dir, 'meta', 'stats', tile_key + '.dat')
            # Append to existing file or create new file
            try:
                with open(stats_filename, 'a') as file:
                    file.write(str(slice_counter).zfill(utils.SLICE_DIGITS)
                               + ';' + str(self.tile_means[tile_key][-1][1])
                               + ';' + str(self.tile_stddevs[tile_key][-1][1])
                               + '\n')
            except Exception as e:
                success = False  # writing to disk failed
                error_msg = str(e)
        else:
            success = False  # mean/SD not available
            error_msg = 'Mean/StdDev of specified tile not found.'
        return success, error_msg

    def save_tile_reslice(self, base_dir, grid_index, tile_index):
        """Write reslice line of specified tile to disk."""
        tile_key = ('g' + str(grid_index).zfill(utils.GRID_DIGITS)
                    + '_' + 't' + str(tile_index).zfill(utils.TILE_DIGITS))
        success = True
        error_msg = ''
        if (tile_key in self.tile_reslice_line
            and self.tile_reslice_line[tile_key].shape[1] == 400):
            reslice_filename = os.path.join(
                base_dir, 'workspace', 'reslices', 'r_' + tile_key + '.png')
            reslice_img = None
            # Open reslice file if it exists and save updated reslice
            try:
                if os.path.isfile(reslice_filename):
                    reslice_img = np.array(Image.open(reslice_filename))
                if reslice_img is not None and reslice_img.shape[1] == 400:
                    new_reslice_img = np.concatenate(
                        (reslice_img, self.tile_reslice_line[tile_key]))
                    imwrite(reslice_filename, new_reslice_img)
                else:
                    imwrite(reslice_filename, self.tile_reslice_line[tile_key])
            except Exception as e:
                success = False  # couldn't write to disk
                error_msg = str(e)
        else:
            success = False  # no new reslice line available
            error_msg = 'Could not update reslice image for specified tile.'
        return success, error_msg

    def process_ov(self, filename, ov_index, slice_counter):
        """Load overview image from disk and perform standard tests."""
        range_test_passed = False

        ov_img, mean, stddev, load_error, load_exception, grab_incomplete = (
            self.load_and_inspect(filename))

        if not load_error:

            if not (ov_index in self.ov_images):
                self.ov_images[ov_index] = []
            if len(self.ov_images[ov_index]) > 1:
                # Only keep the current and the previous OV
                self.ov_images[ov_index].pop(0)
            self.ov_images[ov_index].append((slice_counter, ov_img))

            # Save mean and stddev in lists:
            if not (ov_index in self.ov_means):
                self.ov_means[ov_index] = []
            if len(self.ov_means[ov_index]) > 1:
                self.ov_means[ov_index].pop(0)
            self.ov_means[ov_index].append(mean)

            if not (ov_index in self.ov_stddevs):
                self.ov_stddevs[ov_index] = []
            if len(self.ov_stddevs[ov_index]) > 1:
                self.ov_stddevs[ov_index].pop(0)
            self.ov_stddevs[ov_index].append(stddev)

            # Save reslice line in memory. Take a 400-px line from the centre
            # of the image. This works for all frame resolutions.
            # Only saved to disk later if OV accepted.
            height, width = ov_img.shape[0], ov_img.shape[1]
            self.ov_reslice_line[ov_index] = (
                ov_img[int(height/2):int(height/2)+1,
                       int(width/2)-200:int(width/2)+200])

            # Perform range check
            range_test_passed = (
                (self.mean_lower_limit <= mean <= self.mean_upper_limit) and
                (self.stddev_lower_limit <= stddev <= self.stddev_upper_limit))

        return (ov_img, mean, stddev,
                range_test_passed, load_error, load_exception, grab_incomplete)

    def save_ov_stats(self, base_dir, ov_index, slice_counter):
        """Write mean and SD of specified overview image to disk."""
        success = True
        error_msg = ''
        if ov_index in self.ov_means and ov_index in self.ov_stddevs:
            stats_filename = os.path.join(
                base_dir, 'meta', 'stats',
                'OV' + str(ov_index).zfill(utils.OV_DIGITS) + '.dat')
            # Append to existing file or create new file
            try:
                with open(stats_filename, 'a') as file:
                    file.write(str(slice_counter) + ';'
                               + str(self.ov_means[ov_index][-1]) + ';'
                               + str(self.ov_stddevs[ov_index][-1]) + '\n')
            except Exception as e:
                success = False  # couldn't write to disk
                error_msg = str(e)
        else:
            success = False  # No stats available for this OV
            error_msg = 'Mean/StdDev of specified OV not found.'
        return success, error_msg

    def save_ov_reslice(self, base_dir, ov_index):
        """Write new reslice line of specified overview image to disk."""
        success = True
        error_msg = ''
        if (ov_index in self.ov_reslice_line
            and self.ov_reslice_line[ov_index].shape[1] == 400):
            reslice_filename = os.path.join(
                base_dir, 'workspace', 'reslices',
                'r_OV' + str(ov_index).zfill(utils.OV_DIGITS) + '.png')
            reslice_img = None
            # Open reslice file if it exists and save updated reslice
            try:
                if os.path.isfile(reslice_filename):
                    reslice_img = np.array(Image.open(reslice_filename))
                if reslice_img is not None and reslice_img.shape[1] == 400:
                    new_reslice_img = np.concatenate(
                        (reslice_img, self.ov_reslice_line[ov_index]))
                    imwrite(reslice_filename, new_reslice_img)
                else:
                    imwrite(reslice_filename, self.ov_reslice_line[ov_index])
            except Exception as e:
                success = False
                error_msg = str(e)
        else:
            success = False
            error_msg = 'Could not update reslice image for specified OV.'
        return success, error_msg

    def detect_debris(self, ov_index):
        debris_detected = False
        msg = 'No debris detection method selected.'
        ov_roi = [None, None]
        # Crop to current debris detection area
        top_left_px, top_left_py, bottom_right_px, bottom_right_py = (
            self.ovm[ov_index].debris_detection_area)
        for i in range(2):
            ov_img = self.ov_images[ov_index][i][1]
            ov_roi[i] = ov_img[top_left_py:bottom_right_py,
                               top_left_px:bottom_right_px]
        height, width = ov_roi[0].shape

        if self.debris_detection_method == 0:
            # Calculate the maximum difference in mean and stddev across
            # four quadrants and full ROI.
            means = {}
            stddevs = {}
            max_diff_mean = 0
            max_diff_stddev = 0
            area_height = bottom_right_py - top_left_py
            area_width = bottom_right_px - top_left_px
            quadrant_area = (area_height * area_width)/4

            for i in range(2):
                quadrant1 = ov_roi[i][0:int(area_height/2),
                                      0:int(area_width/2)]
                quadrant2 = ov_roi[i][0:int(area_height/2),
                                      int(area_width/2):area_width]
                quadrant3 = ov_roi[i][int(area_height/2):area_height,
                                      0:int(area_width/2)]
                quadrant4 = ov_roi[i][int(area_height/2):area_height,
                                      int(area_width/2):int(area_width)]
                means[i] = [np.mean(quadrant1), np.mean(quadrant2),
                            np.mean(quadrant3), np.mean(quadrant4),
                            np.mean(ov_roi[i])]
                stddevs[i] = [np.std(quadrant1), np.std(quadrant2),
                              np.std(quadrant3), np.std(quadrant4),
                              np.std(ov_roi[i])]

            if quadrant_area < self.debris_roi_min_quadrant_area:
                # Use only full ROI if ROI too small for quadrants
                start_i = 4
                var_str = 'OV ROI (no quadrants)'
            else:
                # Use four quadrants and ROI for comparisons
                start_i = 0
                var_str = 'OV quadrants'
            for i in range(start_i, 5):
                diff_mean_i = abs(means[1][i] - means[0][i])
                if diff_mean_i > max_diff_mean:
                    max_diff_mean = diff_mean_i
                diff_stddev_i = abs(stddevs[1][i] - stddevs[0][i])
                if diff_stddev_i > max_diff_stddev:
                    max_diff_stddev = diff_stddev_i

            msg = (var_str
                   + ': max. diff_M: {0:.2f}'.format(max_diff_mean)
                   + '; max. diff_SD: {0:.2f}'.format(max_diff_stddev))

            debris_detected = ((max_diff_mean > self.mean_diff_threshold) or
                               (max_diff_stddev > self.stddev_diff_threshold))

            # If no debris detected, add max_diff_mean and max_diff_stddev to
            # deques to calculate moving average for display in debris settings
            # dialog. This makes it easier for the user to set appropriate
            # thresholds.
            if not debris_detected:
                self.mean_diffs.append(max_diff_mean)
                self.stddev_diffs.append(max_diff_stddev)

        elif self.debris_detection_method == 1:
            # Compare the histogram count from the difference image to user-
            # specified threshold.

            # Apply median filter to denoise images
            ov_curr = medfilt2d(ov_roi[1], self.median_filter_kernel_size)
            ov_prev = medfilt2d(ov_roi[0], self.median_filter_kernel_size)

            # Pixel difference. Recast as int16 before subtraction
            ov_curr = ov_curr.astype(np.int16)
            ov_prev = ov_prev.astype(np.int16)
            ov_diff_img = np.absolute(np.subtract(ov_curr, ov_prev))
            # Histogram of difference image
            diff_histogram, bin_edges = np.histogram(ov_diff_img, 256, [0, 256])
            # Compute sum for counts above lower limit
            diff_sum = 0
            for i in range(self.image_diff_hist_lower_limit, 256):
                diff_sum += diff_histogram[i]
            threshold = self.image_diff_threshold * height * width / 1e6
            msg = ('OV: image_diff_hist_sum: ' + str(diff_sum)
                   + ' (curr. threshold: ' + str(int(threshold)) + ')')
            debris_detected = (diff_sum > threshold)

        else:
            # Compare histograms directly (this is not very effective,
            # for testing purposes.)
            hist_diff_sum = 0
            # Histogram from previous OV:
            hist1, bin_edges = np.histogram(ov_roi[0], 256, [0, 256])
            # Histogram from current OV
            hist2, bin_edges = np.histogram(ov_roi[1], 256, [0, 256])
            for i in range(256):
                hist_diff_sum += abs(hist1[i] - hist2[i])
            threshold = self.histogram_diff_threshold * height * width / 1e6

            msg = ('OV: hist_diff_sum: ' + str(hist_diff_sum)
                   + ' (curr. threshold: ' + str(int(threshold)) + ')')
            debris_detected = (hist_diff_sum > threshold)

        return debris_detected, msg

    def discard_last_ov(self, ov_index):
        if self.ov_means and self.ov_stddevs:
            # Delete last entries in means/stddevs list
            self.ov_means[ov_index].pop()
            self.ov_stddevs[ov_index].pop()
        if self.ov_images:
            # Delete last image
            self.ov_images[ov_index].pop()

    def reset_tile_stats(self):
        self.tile_means = {}
        self.tile_stddevs = {}
        self.tile_reslice_line = {}
