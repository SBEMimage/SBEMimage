# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""
This module provides automatic focusing and stigmation. Two methods are
implemented: (1) SmartSEM autofocus, which is called in user-specified
intervals on selected tiles. (2) Heuristic algorithm as used in Briggman
et al., 2011, described in Binding et al., 2012.

"""

import json
import numpy as np
from math import sqrt, exp, sin, cos
from statistics import mean
from time import sleep, time
from scipy.signal import correlate2d, fftconvolve


class Autofocus():

    def __init__(self, config, sem, grid_manager,
                 main_controls_trigger, main_controls_queue):
        self.cfg = config
        self.sem = sem
        self.gm = grid_manager
        self.trigger = main_controls_trigger
        self.queue = main_controls_queue
        self.method = int(self.cfg['autofocus']['method'])
        self.tracking_mode = int(self.cfg['autofocus']['tracking_mode'])
        self.interval = int(self.cfg['autofocus']['interval'])
        self.autostig_delay = int(self.cfg['autofocus']['autostig_delay'])
        self.pixel_size = float(self.cfg['autofocus']['pixel_size'])
        # Maximum allowed change in focus/stigmation:
        self.max_wd_diff, self.max_stig_x_diff, self.max_stig_y_diff = (
            json.loads(self.cfg['autofocus']['max_wd_stig_diff']))
        # For heuristic autofocus:
        # Dictionary of cropped central tile areas, kept in memory
        # for processing during cut cycle:
        self.img = {}
        self.wd_delta, self.stig_x_delta, self.stig_y_delta = json.loads(
            self.cfg['autofocus']['heuristic_deltas'])
        self.heuristic_calibration = json.loads(
            self.cfg['autofocus']['heuristic_calibration'])
        self.rot_angle, self.scale_factor = json.loads(
            self.cfg['autofocus']['heuristic_rot_scale'])
        self.ACORR_WIDTH = 64
        self.fi_mask = np.empty((self.ACORR_WIDTH, self.ACORR_WIDTH))
        self.fo_mask = np.empty((self.ACORR_WIDTH, self.ACORR_WIDTH))
        self.apx_mask = np.empty((self.ACORR_WIDTH, self.ACORR_WIDTH))
        self.amx_mask = np.empty((self.ACORR_WIDTH, self.ACORR_WIDTH))
        self.apy_mask = np.empty((self.ACORR_WIDTH, self.ACORR_WIDTH))
        self.amy_mask = np.empty((self.ACORR_WIDTH, self.ACORR_WIDTH))
        self.make_heuristic_weight_function_masks()
        # Estimators (dicts with tile keys):
        self.foc_est = {}
        self.astgx_est = {}
        self.astgy_est = {}
        # Computed corrections:
        self.wd_stig_corr = {}
        # If MagC mode active, enforce method and tracking mode
        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')
        if self.magc_mode:
            self.method = 0         # SmartSEM autofocus
            self.tracking_mode = 0  # Track selected, approx. others

    def save_to_cfg(self):
        """Save current status of autofocus to ConfigParser object. Note that
        autofocus reference tiles are managed by the grid_manager."""
        self.cfg['autofocus']['method'] = str(self.method)
        self.cfg['autofocus']['tracking_mode'] = str(self.tracking_mode)
        self.cfg['autofocus']['max_wd_stig_diff'] = str(
            [self.max_wd_diff, self.max_stig_x_diff, self.max_stig_y_diff])
        self.cfg['autofocus']['interval'] = str(self.interval)
        self.cfg['autofocus']['autostig_delay'] = str(self.autostig_delay)
        self.cfg['autofocus']['pixel_size'] = str(self.pixel_size)
        self.cfg['autofocus']['heuristic_deltas'] = str(
            [self.wd_delta, self.stig_x_delta, self.stig_y_delta])
        self.cfg['autofocus']['heuristic_calibration'] = str(
            self.heuristic_calibration)
        self.cfg['autofocus']['heuristic_rot_scale'] = str(
            [self.rot_angle, self.scale_factor])

    def approximate_wd_stig_in_grid(self, grid_index):
        """Approximate the working distance and stigmation parameters for all
        non-selected active tiles in the specified grid. Simple approach for
        now: use the settings of the nearest (selected) neighbour."""
        active_tiles = self.gm[grid_index].active_tiles
        autofocus_ref_tiles = self.gm[grid_index].autofocus_ref_tiles()
        if active_tiles and autofocus_ref_tiles:
            for tile in active_tiles:
                min_dist = 10**6
                nearest_tile = None
                for af_tile in autofocus_ref_tiles:
                    dist = self.gm[grid_index].distance_between_tiles(
                        tile, af_tile)
                    if dist < min_dist:
                        min_dist = dist
                        nearest_tile = af_tile
                # Set focus parameters for current tile to those of the nearest
                # autofocus tile
                self.gm[grid_index][tile].wd = (
                    self.gm[grid_index][nearest_tile].wd)
                self.gm[grid_index][tile].stig_xy = (
                    self.gm[grid_index][nearest_tile].stig_xy)

    def wd_stig_diff_below_max(self, prev_wd, prev_sx, prev_sy):
        diff_wd = abs(self.sem.get_wd() - prev_wd)
        diff_sx = abs(self.sem.get_stig_x() - prev_sx)
        diff_sy = abs(self.sem.get_stig_y() - prev_sy)
        return (diff_wd <= self.max_wd_diff
                and diff_sx <= self.max_stig_x_diff
                and diff_sy <= self.max_stig_y_diff)

    def current_slice_active(self, slice_counter):
        autofocus_active, autostig_active = False, False
        if slice_counter > 0:
            autofocus_active = (slice_counter % self.interval == 0)
        if -1 < self.autostig_delay < slice_counter:
            autostig_active = ((
                (slice_counter - self.autostig_delay) % self.interval) == 0)
        return autofocus_active, autostig_active

    def run_zeiss_af(self, autofocus=True, autostig=True):
        """Call the SmartSEM autofocus and autostigmation routines
        separately, or the combined routine, or no routine at all. Return a
        message that the routine was completed or an error message if not.
        """

        msg = 'CTRL: SmartSEM AF did not run.'
        if autofocus or autostig:
            # Switch to autofocus settings:
            self.sem.apply_frame_settings(0, self.pixel_size, 0.8)
            # unfreeze does not seem to help to change scanrate during autofocus
            # self.sem.sem_api.Execute('CMD_UNFREEZE_ALL')
            sleep(0.5)

            if autofocus and autostig:
                if self.magc_mode:
                    # Run SmartSEM autofocus-autostig-autofocus sequence:
                    msg = 'SmartSEM autofocus-autostig-autofocus (MagC)'
                    success = self.sem.run_autofocus()
                    sleep(0.5)
                    if success:
                        success = self.sem.run_autostig()
                        sleep(0.5)
                        if success:
                            success = self.sem.run_autofocus()
                else:
                    msg = 'SmartSEM autofocus + autostig procedure'
                    # Perform combined autofocus + autostig:
                    success = self.sem.run_autofocus_stig()
            elif autofocus:
                msg = 'SmartSEM autofocus procedure'
                # Call only SmartSEM autofocus routine:
                success = self.sem.run_autofocus()
            else:
                msg = 'SmartSEM autostig procedure'
                # Call only SmartSEM autostig routine:
                success = self.sem.run_autostig()

        if success:
            msg = 'CTRL: Completed ' + msg + '.'
        else:
            msg = 'CTRL: ERROR during ' + msg + '.'

        return msg

    # ===== Below: Heuristic autofocus =======

    def crop_tile_for_heuristic_af(self, tile_img, tile_key):
        """Crop tile_img provided as numpy array. Save in dictionary with
           tile_key."""
        # Crop image to 512x512:
        height, width = tile_img.shape[0], tile_img.shape[1]
        self.img[tile_key] = tile_img[int(height/2 - 256):int(height/2 + 256),
                                      int(width/2 - 256):int(width/2 + 256)]

    def process_image_for_heuristic_af(self, tile_key):
        """Compute single-image estimators as described in
           Binding et al., 2013"""

        # image provided as numpy array from dictionary,
        # already cropped to 512x512
        img = self.img[tile_key]
        mean = int(np.mean(img))
        # recast as int16 before mean subtraction
        img = img.astype(np.int16)
        img -= mean
        # Autocorrelation:
        norm = np.sum(img ** 2)
        autocorr = fftconvolve(img, img[::-1, ::-1])/norm
        height, width = autocorr.shape[0], autocorr.shape[1]
        # Crop to 64-pixel central region:
        autocorr = autocorr[int(height/2 - 32):int(height/2 + 32),
                            int(width/2 - 32):int(width/2 + 32)]
        # Calculate coefficients:
        fi = self.muliply_with_mask(autocorr, self.fi_mask)
        fo = self.muliply_with_mask(autocorr, self.fo_mask)
        apx = self.muliply_with_mask(autocorr, self.apx_mask)
        amx = self.muliply_with_mask(autocorr, self.amx_mask)
        apy = self.muliply_with_mask(autocorr, self.apy_mask)
        amy = self.muliply_with_mask(autocorr, self.amy_mask)
        # Check if tile_key already in dictionary:
        if not (tile_key in self.foc_est):
            self.foc_est[tile_key] = []
        if not (tile_key in self.astgx_est):
            self.astgx_est[tile_key] = []
        if not (tile_key in self.astgy_est):
            self.astgy_est[tile_key] = []
        # Calculate single-image estimators for current tile key:
        if len(self.foc_est[tile_key]) > 1:
            self.foc_est[tile_key].pop(0)
        self.foc_est[tile_key].append(
            (fi - fo) / (fi + fo))
        if len(self.astgx_est[tile_key]) > 1:
            self.astgx_est[tile_key].pop(0)
        self.astgx_est[tile_key].append(
            (apx - amx) / (apx + amx))
        if len(self.astgy_est[tile_key]) > 1:
            self.astgy_est[tile_key].pop(0)
        self.astgy_est[tile_key].append(
            (apy - amy) / (apy + amy))

    def get_heuristic_corrections(self, tile_key):
        """Use the estimators to calculate corrections."""

        if (len(self.foc_est[tile_key]) > 1
            and len(self.astgx_est[tile_key]) > 1
            and len(self.astgy_est[tile_key]) > 1):

            wd_corr = (self.heuristic_calibration[0]
                  * (self.foc_est[tile_key][0] - self.foc_est[tile_key][1]))
            a1 = (self.heuristic_calibration[1]
                  * (self.astgx_est[tile_key][0] - self.astgx_est[tile_key][1]))
            a2 = (self.heuristic_calibration[2]
                  * (self.astgy_est[tile_key][0] - self.astgy_est[tile_key][1]))

            ax_corr = a1 * cos(self.rot_angle) - a2 * sin(self.rot_angle)
            ay_corr = a1 * sin(self.rot_angle) + a2 * cos(self.rot_angle)
            ax_corr *= self.scale_factor
            ay_corr *= self.scale_factor
            # Are results within permissible range?
            within_range = (abs(wd_corr/1000) <= self.max_wd_diff
                            and abs(ax_corr) <= self.max_stig_x_diff
                            and abs(ay_corr) <= self.max_stig_y_diff)
            if within_range:
                # Store corrections for this tile:
                self.wd_stig_corr[tile_key] = [wd_corr/1000, ax_corr, ay_corr]
            else:
                self.wd_stig_corr[tile_key] = [0, 0, 0]

            return wd_corr, ax_corr, ay_corr, within_range
        else:
            return None, None, None, False

    def get_heuristic_average_grid_correction(self, grid_index):
        wd_corr = []
        stig_x_corr = []
        stig_y_corr = []
        for tile_key in self.wd_stig_corr:
            g = int(tile_key.split('.')[0])
            if g == grid_index:
                wd_corr.append(self.wd_stig_corr[tile_key][0])
                stig_x_corr.append(self.wd_stig_corr[tile_key][1])
                stig_y_corr.append(self.wd_stig_corr[tile_key][2])
        if wd_corr:
            return (mean(wd_corr), mean(stig_x_corr), mean(stig_y_corr))
        else:
            return (None, None, None)

    def apply_heuristic_tile_corrections(self):
        """Apply individual tile corrections for the specified grid."""
        for tile_key in self.wd_stig_corr:
            g, t = tile_key.split('.')
            g, t = int(g), int(t)
            self.gm.adjust_tile_wd(g, t, self.wd_stig_corr[tile_key][0])
            self.gm.adjust_tile_stig_xy(
                g, t, *self.wd_stig_corr[tile_key][1:3])

    def make_heuristic_weight_function_masks(self):
        # Parameters as given in Binding et al. 2013:
        α = 6
        β = 0.5
        γ = 3
        δ = 0.5
        ε = 9

        for i in range(self.ACORR_WIDTH):
            for j in range(self.ACORR_WIDTH):
                x, y = i - self.ACORR_WIDTH/2, j - self.ACORR_WIDTH/2
                r = sqrt(x**2 + y**2)
                if r == 0:
                # Prevent division by zero:
                    r = 1
                sinφ = x/r
                cosφ = y/r
                exp_astig = exp(-r**2/α) - exp(-r**2/β)

                # Six masks for the calculation of coefficients
                # fi, fo, apx, amx, apy, amy
                self.fi_mask[i, j] = exp(-r**2/γ) - exp(-r**2/δ)
                self.fo_mask[i, j] = exp(-r**2/ε) - exp(-r**2/γ)
                self.apx_mask[i, j] = sinφ**2 * exp_astig
                self.amx_mask[i, j] = cosφ**2 * exp_astig
                self.apy_mask[i, j] = 0.5 * (sinφ + cosφ)**2 * exp_astig
                self.amy_mask[i, j] = 0.5 * (sinφ - cosφ)**2 * exp_astig

    def muliply_with_mask(self, autocorr, mask):
        numerator_sum = 0
        norm = 0
        for i in range(self.ACORR_WIDTH):
            for j in range(self.ACORR_WIDTH):
                numerator_sum += autocorr[i, j] * mask[i, j]
                norm += mask[i, j]
        return numerator_sum / norm
