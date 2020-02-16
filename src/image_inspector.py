# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2019 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module provides integrity and quality checks for overview and
   tile images.
"""

import os
import json
import numpy as np

from imageio import imwrite
from scipy.signal import medfilt2d
from PIL import Image
from PIL.ImageQt import ImageQt
Image.MAX_IMAGE_PIXELS = None
from PyQt5.QtGui import QPixmap


from time import sleep

import psutil

import utils


class ImageInspector(object):

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

        self.update_acq_settings()
        self.update_debris_settings()
        self.update_monitoring_settings()

    def update_acq_settings(self):
        self.base_dir = self.cfg['acq']['base_dir']

    def update_debris_settings(self):
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

    def update_monitoring_settings(self):
        # read params for monitoring image stats of tiles and OVs:
        self.mean_lower_limit = int(self.cfg['monitoring']['mean_lower_limit'])
        self.mean_upper_limit = int(self.cfg['monitoring']['mean_upper_limit'])
        self.stddev_lower_limit = int(
            self.cfg['monitoring']['stddev_lower_limit'])
        self.stddev_upper_limit = int(
            self.cfg['monitoring']['stddev_upper_limit'])
        self.monitoring_tiles = json.loads(
            self.cfg['monitoring']['monitor_tiles'])
        self.tile_mean_threshold = float(
            self.cfg['monitoring']['tile_mean_threshold'])
        self.tile_stddev_threshold = float(
            self.cfg['monitoring']['tile_stddev_threshold'])

    def process_tile(self, filename, grid_index, tile_index, slice_number):
        img = None
        mean, stddev = 0, 0
        range_test_passed, slice_by_slice_test_passed = False, False
        frozen_frame_error = False
        grab_incomplete = False
        load_error = False
        tile_selected = False

        if (self.cfg['sys']['magc_mode'] == 'True'
            and psutil.virtual_memory()[2] > 50):
            print('### WARNING ### Memory usage '
                + str(psutil.virtual_memory()[2])
                + ' too high. The tiles are not checked any more')

            range_test_passed, slice_by_slice_test_passed = True, True
            frozen_frame_error = False
            grab_incomplete = False
            load_error = False
            tile_selected = True
            return (np.zeros((1000,1000)), mean, stddev,
                    range_test_passed, slice_by_slice_test_passed,
                    tile_selected,
                    load_error, grab_incomplete, frozen_frame_error)

        try:
            img = Image.open(filename)
        except Exception as e:
            print(repr(e))
            load_error = True
        if not load_error:
            img = np.array(img)
            height, width = img.shape[0], img.shape[1]

            tile_key = ('g' + str(grid_index).zfill(utils.GRID_DIGITS)
                        + '_' + 't' + str(tile_index).zfill(utils.TILE_DIGITS))
            tile_key_short = str(grid_index) + '.' + str(tile_index)

            # Save preview image:
            img_tostring = img.tostring()
            preview_img = Image.frombytes(
                'L', (width, height),
                img_tostring).resize((512, 384), resample=2)
            # preview_img.save(os.path.join(
            #     self.base_dir, 'workspace', tile_key + '.png'))
            # Convert to QPixmap and save in grid_manager
            self.gm[grid_index][tile_index].preview_img = QPixmap.fromImage(
                ImageQt(preview_img))

            # calculate mean and stddev:
            mean = np.mean(img)
            stddev = np.std(img)
            # Compare with previous mean and std to check for same-frame
            # error in SmartSEM:
            if self.prev_img_mean_stddev == [mean, stddev]:
                frozen_frame_error = True
            else:
                frozen_frame_error = False
                self.prev_img_mean_stddev = [mean, stddev]

            # Was complete image grabbed? Test if first or final line of image
            # is black/white/uniform greyscale (bug in SmartSEM)
            first_line = img[0:1,:]
            final_line = img[height-1:height,:]
            if (np.min(first_line) == np.max(first_line) or
                np.min(final_line) == np.max(final_line)):
                grab_incomplete = True
            else:
                grab_incomplete = False

            # Save reslice line in memory. Take a 400-px line from the centre
            # of the image. This works for all frame resolutions.
            img_reslice_line = img[int(height/2):int(height/2)+1,
                int(width/2)-200:int(width/2)+200]
            self.tile_reslice_line[tile_key] = (img_reslice_line)

            # Save mean and std in memory:
            # Add key to dictionary if tile is new:
            if not tile_key in self.tile_means:
                self.tile_means[tile_key] = []
            # Save mean and stddev in tile list:
            if len(self.tile_means[tile_key]) > 1:
                # Remove the oldest entry:
                self.tile_means[tile_key].pop(0)
            # Add the newest:
            self.tile_means[tile_key].append((slice_number, mean))

            if not tile_key in self.tile_stddevs:
                self.tile_stddevs[tile_key] = []
            if len(self.tile_stddevs[tile_key]) > 1:
                self.tile_stddevs[tile_key].pop(0)
            # Add the newest:
            self.tile_stddevs[tile_key].append((slice_number, stddev))

            if (tile_key_short in self.monitoring_tiles
                or 'all' in self.monitoring_tiles):
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
            # Perform range test:
            range_test_passed = (
                (self.mean_lower_limit <= mean <= self.mean_upper_limit)
                and (self.stddev_lower_limit <= stddev <= self.stddev_upper_limit))

            # Perform other tests here to decide whether tile is selected for
            # acquisition or discarded:
            # ...
            tile_selected = True

            del img_tostring
            del preview_img
            del first_line
            del final_line

        return (img, mean, stddev,
                range_test_passed, slice_by_slice_test_passed,
                tile_selected,
                load_error, grab_incomplete, frozen_frame_error)

    def save_tile_stats(self, grid_index, tile_index, slice_number):
        """Write mean and SD of specified tile to disk."""
        success = True
        tile_key = ('g' + str(grid_index).zfill(utils.GRID_DIGITS)
                    + '_' + 't' + str(tile_index).zfill(utils.TILE_DIGITS))
        if tile_key in self.tile_means and tile_key in self.tile_stddevs:
            stats_filename = os.path.join(
                self.base_dir, 'meta', 'stats', tile_key + '.dat')
            # Append to existing file or create new file
            try:
                with open(stats_filename, 'a') as file:
                    file.write(str(slice_number).zfill(utils.SLICE_DIGITS)
                               + ';' + str(self.tile_means[tile_key][-1][1])
                               + ';' + str(self.tile_stddevs[tile_key][-1][1])
                               + '\n')
            except:
                success = False # writing to disk failed
        else:
            success = False # mean/SD not available
        return success

    def save_tile_reslice(self, grid_index, tile_index):
        """Write reslice line of specified tile to disk."""
        tile_key = ('g' + str(grid_index).zfill(utils.GRID_DIGITS)
                    + '_' + 't' + str(tile_index).zfill(utils.TILE_DIGITS))
        success = True
        if (tile_key in self.tile_reslice_line
            and self.tile_reslice_line[tile_key].shape[1] == 400):
            reslice_filename = os.path.join(
                self.base_dir, 'workspace', 'reslices',
                'r_' + tile_key + '.png')
            reslice_img = None
            # Open reslice file if it exists and save updated reslice:
            try:
                if os.path.isfile(reslice_filename):
                    reslice_img = np.array(Image.open(reslice_filename))
                if reslice_img is not None and reslice_img.shape[1] == 400:
                    new_reslice_img = np.concatenate(
                        (reslice_img, self.tile_reslice_line[tile_key]))
                    imwrite(reslice_filename, new_reslice_img)
                else:
                    imwrite(reslice_filename, self.tile_reslice_line[tile_key])
            except:
                success = False # couldn't write to disk
        else:
            success = False # no new reslice line available
        return success

    def process_ov(self, filename, ov_number, slice_number):
        """Load overview image from disk and perform standard tests."""
        ov_img = None
        mean, stddev = 0, 0
        load_error = False
        grab_incomplete = False
        range_test_passed = False
        # Try to load OV from disk:
        try:
            ov_img = Image.open(filename)
        except:
            load_error = True

        if not load_error:
            ov_img = np.array(ov_img)
            height, width = ov_img.shape[0], ov_img.shape[1]

            # Was complete image grabbed? Test if final line of image is black:
            final_line = ov_img[height-1:height,:]
            grab_incomplete = (np.min(final_line) == np.max(final_line))

            if not ov_number in self.ov_images:
                self.ov_images[ov_number] = []
            if len(self.ov_images[ov_number]) > 1:
                # Only keep the current and the previous OV
                self.ov_images[ov_number].pop(0)
            self.ov_images[ov_number].append((slice_number, ov_img))

            # Calculate mean and standard deviation:
            mean = np.mean(ov_img)
            stddev = np.std(ov_img)

            # Save mean and stddev in lists:
            if not ov_number in self.ov_means:
                self.ov_means[ov_number] = []
            if len(self.ov_means[ov_number]) > 1:
                self.ov_means[ov_number].pop(0)
            self.ov_means[ov_number].append(mean)

            if not ov_number in self.ov_stddevs:
                self.ov_stddevs[ov_number] = []
            if len(self.ov_stddevs[ov_number]) > 1:
                self.ov_stddevs[ov_number].pop(0)
            self.ov_stddevs[ov_number].append(stddev)

            # Save reslice line in memory. Take a 400-px line from the centre
            # of the image. This works for all frame resolutions.
            # Only saved to disk later if OV accepted.
            self.ov_reslice_line[ov_number] = (
                ov_img[int(height/2):int(height/2)+1,
                       int(width/2)-200:int(width/2)+200])

            # Perform range check:
            range_test_passed = (
                (self.mean_lower_limit <= mean <= self.mean_upper_limit) and
                (self.stddev_lower_limit <= stddev <= self.stddev_upper_limit))

        return (ov_img, mean, stddev,
                range_test_passed, load_error, grab_incomplete)

    def save_ov_stats(self, ov_number, slice_number):
        """Write mean and SD of specified overview image to disk."""
        success = True
        if ov_number in self.ov_means and ov_number in self.ov_stddevs:
            stats_filename = os.path.join(
                self.base_dir, 'meta', 'stats',
                'OV' + str(ov_number).zfill(utils.OV_DIGITS) + '.dat')
            # Append to existing file or create new file
            try:
                with open(stats_filename, 'a') as file:
                    file.write(str(slice_number) + ';'
                               + str(self.ov_means[ov_number][-1]) + ';'
                               + str(self.ov_stddevs[ov_number][-1]) + '\n')
            except:
                success = False # couldn't write to disk
        else:
            success = False # No stats available for this OV
        return success

    def save_ov_reslice(self, ov_number):
        """Write new reslice line of specified overview image to disk."""
        success = True
        if (ov_number in self.ov_reslice_line
            and self.ov_reslice_line[ov_number].shape[1] == 400):
            reslice_filename = os.path.join(
                self.base_dir, 'workspace', 'reslices',
                'r_OV' + str(ov_number).zfill(utils.OV_DIGITS) + '.png')
            reslice_img = None
            # Open reslice file if it exists and save updated reslice:
            try:
                if os.path.isfile(reslice_filename):
                    reslice_img = np.array(Image.open(reslice_filename))
                if reslice_img is not None and reslice_img.shape[1] == 400:
                    new_reslice_img = np.concatenate(
                        (reslice_img, self.ov_reslice_line[ov_number]))
                    imwrite(reslice_filename, new_reslice_img)
                else:
                    imwrite(reslice_filename, self.ov_reslice_line[ov_number])
            except:
                success = False
        else:
            success = False
        return success

    def detect_debris(self, ov_number, method):
        debris_detected = False
        msg = 'CTRL: No debris detection method selected.'
        ov_roi = [None, None]
        # Crop to current debris detection area:
        top_left_px, top_left_py, bottom_right_px, bottom_right_py = (
            self.ovm.get_ov_debris_detection_area(ov_number))
        for i in range(2):
            ov_img = self.ov_images[ov_number][i][1]
            ov_roi[i] = ov_img[top_left_py:bottom_right_py,
                               top_left_px:bottom_right_px]
        height, width = ov_roi[0].shape

        if method == 0:
            # Calculate the maximum difference in mean and stddev across
            # four quadrants and full ROI:
            means = {}
            stddevs = {}
            max_diff_mean = 0
            max_diff_stddev = 0
            # Compute mean and stddev for four quadrants
            # and for full ROI
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
                # Use only full ROI if ROI too small for quadrants:
                start_i = 4
                var_str = 'OV ROI (no quadrants)'
            else:
                # Use four quadrants and ROI for comparisons:
                start_i = 0
                var_str = 'OV quadrants'
            for i in range(start_i, 5):
                diff_mean_i = abs(means[1][i] - means[0][i])
                if diff_mean_i > max_diff_mean:
                    max_diff_mean = diff_mean_i
                diff_stddev_i = abs(stddevs[1][i] - stddevs[0][i])
                if diff_stddev_i > max_diff_stddev:
                    max_diff_stddev = diff_stddev_i

            msg = ('CTRL: ' + var_str
                   + ': max. diff_M: {0:.2f}'.format(max_diff_mean)
                   + '; max. diff_SD: {0:.2f}'.format(max_diff_stddev))

            debris_detected = ((max_diff_mean > self.mean_diff_threshold) or
                               (max_diff_stddev > self.stddev_diff_threshold))

        if method == 1:
            # Compare the histogram count from the difference image to user-
            # specified threshold.

            # Apply median filter to denoise images:
            ov_curr = medfilt2d(ov_roi[1], self.median_filter_kernel_size)
            ov_prev = medfilt2d(ov_roi[0], self.median_filter_kernel_size)

            # Pixel difference
            # Recast as int16 before subtraction:
            ov_curr = ov_curr.astype(np.int16)
            ov_prev = ov_prev.astype(np.int16)
            ov_diff_img = np.absolute(np.subtract(ov_curr, ov_prev))
            # Histogram of difference image:
            diff_histogram, bin_edges = np.histogram(ov_diff_img, 256, [0, 256])
            # Compute sum for counts above lower limit:
            diff_sum = 0
            for i in range(self.image_diff_hist_lower_limit, 256):
                diff_sum += diff_histogram[i]
            threshold = self.image_diff_threshold * height * width / 1e6
            msg = ('CTRL: OV: image_diff_hist_sum: ' + str(diff_sum)
                   + ' (curr. threshold: ' + str(int(threshold)) + ')')
            debris_detected = (diff_sum > threshold)

        if method == 2:
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

            msg = ('CTRL: OV: hist_diff_sum: ' + str(hist_diff_sum)
                   + ' (curr. threshold: ' + str(int(threshold)) + ')')
            debris_detected = (hist_diff_sum > threshold)

        return debris_detected, msg

    def discard_last_ov(self, ov_number):
        if self.ov_means and self.ov_stddevs:
            # Delete last entries in means/stddevs list:
            self.ov_means[ov_number].pop()
            self.ov_stddevs[ov_number].pop()
        if self.ov_images:
            # Delete last image:
            self.ov_images[ov_number].pop()

    def reset_tile_stats(self):
        self.tile_means = {}
        self.tile_stddevs = {}
        self.tile_reslice_line = {}
