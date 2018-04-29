# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module provides integrity and quality checks for overview and
   tile images.
"""

import os
import json
import numpy as np

from scipy import ndimage
from scipy.misc import imresize, imsave
from PIL import Image

import utils


class ImageInspector(object):

    def __init__(self, config, overview_manager):
        self.cfg = config
        self.ovm = overview_manager
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
        self.debris_roi_min_area = int(
            self.cfg['debris']['minimum_detection_area'])
        self.debris_roi_quadrant_threshold = int(
            self.cfg['debris']['quadrant_threshold'])
        self.mean_diff_threshold = float(
            self.cfg['debris']['mean_diff_threshold'])
        self.stddev_diff_threshold = float(
            self.cfg['debris']['stddev_diff_threshold'])
        self.histogram_diff_threshold = int(
            self.cfg['debris']['histogram_diff_threshold'])
        self.pixel_diff_threshold = int(
            self.cfg['debris']['pixel_diff_threshold'])

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

    def process_tile(self, filename, grid_number, tile_number, slice_number):
        img = None
        mean, stddev = 0, 0
        range_test_passed, slice_by_slice_test_passed = False, False
        frozen_frame_error = False
        grab_incomplete = False
        load_error = False
        tile_selected = False
        try:
            img = Image.open(filename)
            load_error = False
        except:
            load_error = True

        if not load_error:
            img = np.array(img)
            # calculate mean and stddev:
            mean = np.mean(img)
            stddev = np.std(img)
            # Compare with previous mean and std to check for same-frame
            # error in SmartSEM:
            if self.prev_img_mean_stddev == [mean, stddev]:
                frozen_frame_error = True
                self.prev_img_mean_stddev = [0, 0]
            else:
                frozen_frame_error = False
                self.prev_img_mean_stddev = [mean, stddev]

            height, width = img.shape[0], img.shape[1]
            # Was complete image grabbed? Test final line of image is black:
            final_line = img[height-1:height,:]
            if np.min(final_line) == np.max(final_line):
                grab_incomplete = True
            else:
                grab_incomplete = False

            tile_key = ('g' + str(grid_number).zfill(utils.GRID_DIGITS)
                        + '_' + 't' + str(tile_number).zfill(utils.TILE_DIGITS))
            tile_key_short = str(grid_number) + '.' + str(tile_number)

            # Save preview image:
            preview = imresize(img, (384, 512))
            imsave(self.base_dir + '\\workspace\\' + tile_key + '.png', preview)

            # Save reslice line in memory:
            # Take a 400-px line from centre of the image:
            self.tile_reslice_line[tile_key] = (
                img[int(height/2):int(height/2)+1,
                    int(width/2)-200:int(width/2)+200])

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

        return (img, mean, stddev,
                range_test_passed, slice_by_slice_test_passed,
                tile_selected,
                load_error, grab_incomplete, frozen_frame_error)

    def save_tile_reslice_and_stats(self, grid_number, tile_number,
                                    slice_number):
        tile_key = ('g' + str(grid_number).zfill(utils.GRID_DIGITS)
                    + '_' + 't' + str(tile_number).zfill(utils.TILE_DIGITS))
        # Write mean, stddev to file:
        stat_filename = self.base_dir + '\\meta\\stats\\' + tile_key + '.dat'
        with open(stat_filename, 'a') as file:
            file.write(str(slice_number).zfill(utils.SLICE_DIGITS)
                       + ';' + str(self.tile_means[tile_key][-1][1])
                       + ';' + str(self.tile_stddevs[tile_key][-1][1]) + '\n')

        # Open reslice file if it exists:
        reslice_filename = (self.base_dir + '\\workspace\\reslices\\r_'
                            + tile_key + '.png')
        if os.path.isfile(reslice_filename):
            reslice_img = np.array(Image.open(reslice_filename))
            new_reslice_img = np.concatenate(
                (reslice_img, self.tile_reslice_line[tile_key]))
            imsave(reslice_filename, new_reslice_img)
        else:
            imsave(reslice_filename, self.tile_reslice_line[tile_key])

    def process_ov(self, filename, ov_number, slice_number):
        mean = [0, 0, 0, 0, 0]
        stddev = [0, 0, 0, 0, 0]
        range_test_passed = False
        grab_incomplete = False
        load_error = False

        # Try to load OV from disk:
        try:
            img = Image.open(filename)
            load_error = False
        except:
            load_error = True

        if not load_error:
            img = np.array(img)
            height, width = img.shape[0], img.shape[1]

            # Was complete image grabbed? Test final line of image is black:
            final_line = img[height-1:height,:]
            if np.min(final_line) == np.max(final_line):
                grab_incomplete = True
            else:
                grab_incomplete = False

            # Compute mean and stddev for four quadrants
            # and for full OV image
            (top_left_px, top_left_py, bottom_right_px, bottom_right_py) = (
                self.ovm.get_ov_debris_detection_area(ov_number))
            area_height = bottom_right_py - top_left_py
            area_width = bottom_right_px - top_left_px

            # Crop:
            full_roi = img[top_left_py:bottom_right_py,
                           top_left_px:bottom_right_px]
            if not ov_number in self.ov_images:
                self.ov_images[ov_number] = []
            if len(self.ov_images[ov_number]) > 1:
                self.ov_images[ov_number].pop(0)
            self.ov_images[ov_number].append((slice_number, full_roi))

            quadrant1 = full_roi[0:int(area_height/2),
                                 0:int(area_width/2)]
            quadrant2 = full_roi[0:int(area_height/2),
                                 int(area_width/2):area_width]
            quadrant3 = full_roi[int(area_height/2):area_height,
                                 0:int(area_width/2)]
            quadrant4 = full_roi[int(area_height/2):area_height,
                                 int(area_width/2):int(area_width)]

            mean = [np.mean(quadrant1),
                    np.mean(quadrant2),
                    np.mean(quadrant3),
                    np.mean(quadrant4),
                    np.mean(img)]

            stddev = [np.std(quadrant1),
                      np.std(quadrant2),
                      np.std(quadrant3),
                      np.std(quadrant4),
                      np.std(img)]

            # Save mean and stddev in ov list:
            if not ov_number in self.ov_means:
                self.ov_means[ov_number] = []
            if len(self.ov_means[ov_number]) > 1:
                self.ov_means[ov_number].pop(0)
            # Add the newest:
            self.ov_means[ov_number].append(mean)

            if not ov_number in self.ov_stddevs:
                self.ov_stddevs[ov_number] = []
            if len(self.ov_stddevs[ov_number]) > 1:
                self.ov_stddevs[ov_number].pop(0)
            # Add the newest:
            self.ov_stddevs[ov_number].append(stddev)

            # Save line for reslice in memory. Only saved to disk if OV accepted:
            self.ov_reslice_line[ov_number] = (
                img[int(height/2):int(height/2)+1,
                    int(width/2)-200:int(width/2)+200])

            # Perform range check:
            range_test_passed = (
                (self.mean_lower_limit <= mean[4] <= self.mean_upper_limit) and
                (self.stddev_lower_limit <= stddev[4] <= self.stddev_upper_limit))

        return (img, mean[4], stddev[4], range_test_passed,
                load_error, grab_incomplete)

    def save_ov_reslice_and_stats(self, ov_number, slice_number):
        # Write mean, stddev to file:
        stats_filename = (self.base_dir + '\\meta\\stats\\OV'
                          + str(ov_number).zfill(utils.OV_DIGITS) + '.dat')
        with open(stats_filename, 'a') as file:
            file.write(str(slice_number) + ';'
                       + str(self.ov_means[ov_number][-1][4]) + ';'
                       + str(self.ov_stddevs[ov_number][-1][4]) + '\n')

        # Reslice:
        # Open reslice file if it exists:
        reslice_filename = (self.base_dir
                            + '\\workspace\\reslices\\r_OV'
                            + str(ov_number).zfill(utils.OV_DIGITS)
                            + '.png')
        if os.path.isfile(reslice_filename):
            reslice_img = np.array(Image.open(reslice_filename))
            new_reslice_img = np.concatenate(
                (reslice_img, self.ov_reslice_line[ov_number]))
            imsave(reslice_filename, new_reslice_img)
        else:
            imsave(reslice_filename, self.ov_reslice_line[ov_number])

    def detect_debris(self, ov_number, method):
        debris_detected = False
        msg = 'CTRL: No debris detection method selected.'

        if method == 0:
            # calculate the maximum difference in mean and stddev across
            # four quadrants and full image:
            diff_mean = 0
            diff_stddev = 0
            debris_bb = self.ovm.get_ov_debris_detection_area(ov_number)
            debris_roi_area = ((debris_bb[2] - debris_bb[0])
                               * (debris_bb[3] - debris_bb[1]))
            if debris_roi_area < self.debris_roi_quadrant_threshold:
                # use full image if roi too smoll:
                start_i = 4
            else:
                # use four quadrants and roi:
                start_i = 0
            for i in range(start_i, 5):
                mean_i = abs(self.ov_means[ov_number][-1][i]
                             - self.ov_means[ov_number][-2][i])
                if mean_i > diff_mean:
                    diff_mean = mean_i
                stddev_i = abs(self.ov_stddevs[ov_number][-1][i]
                               - self.ov_stddevs[ov_number][-2][i])
                if stddev_i > diff_stddev:
                    diff_stddev = stddev_i

            msg = ('CTRL: OV: max. diff_mean: {0:.2f}'.format(diff_mean)
                   + '; max. diff_stddev: {0:.2f}'.format(diff_stddev))

            debris_detected = ((diff_mean > self.mean_diff_threshold) or
                               (diff_stddev > self.stddev_diff_threshold))

        if method == 1:
            # Histogram analysis
            # Histogram from previous OV:
            hist1 = ndimage.histogram(
                self.ov_images[ov_number][-2][1], 0, 255, 256)
            # Histrogram from current OV
            hist2 = ndimage.histogram(
                self.ov_images[ov_number][-1][1], 0, 255, 256)
            hist_diff_sum = 0
            for i in range(0, 256):
                hist_diff_sum += abs(hist1[i] - hist2[i])
            msg = 'CTRL: OV: hist_diff_sum: ' + str(hist_diff_sum)
            debris_detected = (hist_diff_sum > self.histogram_diff_threshold)

        if method == 2:
            # Pixel difference analysis
            ov_diff_img = np.substract(
                self.ov_images[ov_number][-2][1],
                self.ov_images[ov_number][-1][1])
            pixel_diff_sum = np.sum(ov_diff_img)
            msg = 'CTRL: OV: pixel_diff_sum: ' + str(pixel_diff_sum)
            debris_detected = (pixel_diff_sum > self.pixel_diff_threshold)

        return debris_detected, msg

    def discard_last_ov(self, ov_number):
        # Delete last entries in means/stddevs list:
        self.ov_means[ov_number].pop()
        self.ov_stddevs[ov_number].pop()
        # Delete last image:
        self.ov_images[ov_number].pop()

    def reset_tile_stats(self):
        self.tile_means = {}
        self.tile_stddevs = {}
        self.tile_reslice_line = {}
