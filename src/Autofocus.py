# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2022 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""
This module provides automatic focusing and stigmation. Two methods are
implemented: (1) SmartSEM autofocus, which is called in user-specified
intervals on selected tiles. (2) Heuristic algorithm as used in Briggman
et al. (2011), described in Appendix A of Binding et al. (2012).
"""

from copy import deepcopy
import json
from math import sqrt, exp, sin, cos
from matplotlib import pyplot as plt
import numpy as np
import os.path
import random
from scipy.signal import fftconvolve
from statistics import mean
from time import sleep
from typing import Tuple, Optional

import autofocus_mapfost
import utils
from constants import *


class Autofocus:

    def __init__(self, config, sem, grid_manager):
        self.cfg = config
        self.sem = sem
        self.gm = grid_manager
        self.method = int(self.cfg['autofocus']['method'])
        self.tracking_mode = int(self.cfg['autofocus']['tracking_mode'])
        self.interval = int(self.cfg['autofocus']['interval'])
        self.autostig_delay = int(self.cfg['autofocus']['autostig_delay'])
        self.use_smartsem = self.sem.device_name.startswith("ZEISS")
         
        # Maximum allowed change in focus/stigmation
        self.max_wd_diff, self.max_stig_x_diff, self.max_stig_y_diff = (
            json.loads(self.cfg['autofocus']['max_wd_stig_diff']))

        # SEM autofocus parameters (autofocus/autostigmator provided by the SEM manufacturers)
        self.pixel_size = float(self.cfg['autofocus']['pixel_size'])
        self.wd_range = float(self.cfg['autofocus']['wd_range'])
        self.wd_final_step = float(self.cfg['autofocus']['wd_final_step'])
        self.autostig_range = float(self.cfg['autofocus']['autostig_range'])

        # For the heuristic autofocus method, a dictionary of cropped central
        # tile areas is kept in memory for processing during the cut cycles.
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
        # Estimators (dicts with tile keys)
        self.foc_est = {}
        self.astgx_est = {}
        self.astgy_est = {}
        # Computed corrections for heuristic autofocus
        self.wd_stig_corr = {}
        # If MagC mode active, enforce method and tracking mode
        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')
        if self.gm.array_mode:
            self.method = 0         # SmartSEM autofocus
            self.tracking_mode = 0  # Track selected, approx. others

        self.MAPFOST_PATCH_SIZE = [768, 768]
        self.MAPFOST_FRAME_RESOLUTION = 2
        self.mapfost_wd_pert = float(self.cfg['autofocus']['mapfost_wd_perturbations'])
        self.mapfost_dwell_time = float(self.cfg['autofocus']['mapfost_dwell_time'])
        self.mapfost_max_iters = int(self.cfg['autofocus']['mapfost_maximum_iterations'])
        self.mapfost_conv_thresh = float(self.cfg['autofocus']['mapfost_convergence_threshold_um'])
        self.mapfost_large_aberrations = int(self.cfg['autofocus']['mapfost_large_aberrations'])

        # Mapfost Calibration Parameters
        self.mapfost_probe_conv = float(self.cfg['autofocus']['mapfost_probe_convergence_angle'])
        self.mapfost_stig_rot = float(self.cfg['autofocus']['mapfost_astig_rotation_deg'])
        self.mapfost_stig_scale = json.loads(self.cfg['autofocus']['mapfost_astig_scaling'])

        # Automated Focus/Stigmator Series
        self.afss_wd_delta = json.loads(self.cfg['autofocus']['afss_wd_delta'])
        self.afss_stig_x_delta = json.loads(self.cfg['autofocus']['afss_stig_x_delta'])
        self.afss_stig_y_delta = json.loads(self.cfg['autofocus']['afss_stig_y_delta'])
        self.afss_data = {'dwd': 0, 'dsx': 0, 'dsy': 0, 'afss_rounds': 0, 'ref_tiles': []}
        self.afss_grid_ind: Optional[int] = None
        self.afss_rounds = json.loads(self.cfg['autofocus']['afss_rounds'])  # Number of induced focus/stig deviations
        self.afss_offset = json.loads(self.cfg['autofocus']['afss_offset'])  # Skip slices before first AFSS activation
        self.afss_current_round = 0  # Position of current WD/stig deviation within AFSS series
        self.afss_next_activation = 0  # Slice nr. of nearest planned AFSS run
        self.afss_perturbation_series = {}  # Multiplication factors for WD/Stig deltas
        self.afss_wd_stig_orig = {}  # Original values before the AFSS started: d = {tile_keys:[[wd, dummy=0], (sx,sy)]}
        # dict = {tile_keys: {slice_nrs: [ (wd, dummy=0), (sx,sy), sharpness, img_full_path, stddev, [shift_vec] ]}}
        self.afss_wd_stig_corr = {}
        self.afss_wd_stig_corr_optima = {}  # Computed corrections AFSS: dict = {tile_keys: [wd/stig opt.val, fit_rmse]}
        self.afss_mode = self.cfg['autofocus']['afss_mode']
        self.afss_upcoming_mode = None
        self.afss_consensus_mode = int(self.cfg['autofocus']['afss_consensus_mode'])
        self.afss_drift_corrected = (self.cfg['autofocus']['afss_drift_corrected'].lower() == 'true')
        self.afss_autostig_active = (self.cfg['autofocus']['afss_autostig_active'].lower() == 'true')
        self.afss_active = False
        self.afss_hyper_perturbation_series = {}
        self.afss_shuffle = False
        self.afss_hyper_shuffle = False
        self.afss_filter_outliers = True
        self.afss_weighted_averaging = True
        self.afss_avg_corr = None
        self.afss_max_fails = json.loads(self.cfg['autofocus']['afss_max_fails'])
        self.afss_rmse_limit = float(self.cfg['autofocus']['afss_rmse_limit'])
        self.afss_background_mode = (self.cfg['autofocus']['afss_background_mode'].lower() == 'true')
        self.acquisition_running = False
        self.afss_min_good_fits = int(self.cfg['autofocus']['min_fits'])
        self.afss_stats = {'avg': 0, 'n_failed': 0, 'n_out_of_lim': 0, 'n_outliers': 0}
        self.afss_min_slope = 0.5  # Slope limit for sharpness linear fit
        self.save_reg_coll = False  # Enable/Disable saving images of registered series to stats folder

    def save_to_cfg(self):
        """Save current autofocus settings to ConfigParser object. Note that
        autofocus reference tiles are managed in grid_manager.
        """
        self.cfg['autofocus']['method'] = str(self.method)
        self.cfg['autofocus']['tracking_mode'] = str(self.tracking_mode)
        self.cfg['autofocus']['max_wd_stig_diff'] = str(
            [self.max_wd_diff, self.max_stig_x_diff, self.max_stig_y_diff])
        self.cfg['autofocus']['interval'] = str(self.interval)
        self.cfg['autofocus']['autostig_delay'] = str(self.autostig_delay)
        self.cfg['autofocus']['pixel_size'] = str(self.pixel_size)
        self.cfg['autofocus']['wd_range'] = str(self.wd_range)
        self.cfg['autofocus']['wd_final_step'] = str(self.wd_final_step)
        self.cfg['autofocus']['autostig_range'] = str(self.autostig_range)
        self.cfg['autofocus']['heuristic_deltas'] = str(
            [self.wd_delta, self.stig_x_delta, self.stig_y_delta])
        self.cfg['autofocus']['heuristic_calibration'] = str(
            self.heuristic_calibration)
        self.cfg['autofocus']['heuristic_rot_scale'] = str(
            [self.rot_angle, self.scale_factor])
        self.cfg['autofocus']['afss_wd_delta'] = str(self.afss_wd_delta)
        self.cfg['autofocus']['afss_stig_x_delta'] = str(self.afss_stig_x_delta)
        self.cfg['autofocus']['afss_stig_y_delta'] = str(self.afss_stig_y_delta)
        self.cfg['autofocus']['afss_rounds'] = str(self.afss_rounds)
        self.cfg['autofocus']['afss_offset'] = str(self.afss_offset)
        self.cfg['autofocus']['afss_consensus_mode'] = str(self.afss_consensus_mode)
        self.cfg['autofocus']['afss_drift_corrected'] = str(self.afss_drift_corrected)
        self.cfg['autofocus']['afss_autostig_active'] = str(self.afss_autostig_active)
        self.cfg['autofocus']['afss_mode'] = str(self.afss_mode)
        self.cfg['autofocus']['afss_max_fails'] = str(self.afss_max_fails)
        self.cfg['autofocus']['afss_rmse_limit'] = str(self.afss_rmse_limit)
        self.cfg['autofocus']['afss_background_mode'] = str(self.afss_background_mode)
        self.cfg['autofocus']['min_fits'] = str(self.afss_min_good_fits)
        
    def approximate_wd_stig_in_grid(self, grid_index):
        """Approximate the working distance and stigmation parameters for all
        non-selected active tiles in the specified grid. Simple approach for
        now: use the settings of the nearest (selected) neighbour.
        TODO: Best fit of parameters using available reference tiles
        """
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
        is_below = (diff_wd <= self.max_wd_diff and diff_sx <= self.max_stig_x_diff
                    and diff_sy <= self.max_stig_y_diff)
        return is_below

    def current_slice_active(self, slice_counter):
        autofocus_active, autostig_active = False, False
        if slice_counter > 0:
            autofocus_active = (slice_counter % self.interval == 0)
        if -1 < self.autostig_delay < slice_counter:
            autostig_active = ((
                (slice_counter - self.autostig_delay) % self.interval) == 0)
        return autofocus_active, autostig_active

    def run_sem_af(self, autofocus=True, autostig=True):
        """Call the SEM autofocus and autostigmation routines
        separately, or the combined routine, or no routine at all. Return a
        message that the routine was completed or an error message if not.
        """
        assert autostig or autofocus  
        msg = 'SEM AF did not run.'
        if autofocus or autostig:
            # Switch to autofocus settings
            # TODO: allow different dwell times
            if self.use_smartsem: 
                self.sem.apply_frame_settings(0, self.pixel_size, 0.8)
                sleep(0.5)
            if autofocus and autostig:
                if self.gm.array_mode:
                    # Run SmartSEM autofocus-autostig-autofocus sequence
                    # TODO: Check compatibility of Array with non-SmartSEM autofocus
                    msg = 'SmartSEM autofocus-autostig-autofocus (Array)'
                    success = self.sem.run_autofocus()
                    sleep(0.5)
                    if success:
                        success = self.sem.run_autostig()
                        sleep(0.5)
                        if success:
                            success = self.sem.run_autofocus()
                else:
                    msg = 'SEM autofocus + autostig procedure'
                    # Perform combined autofocus + autostig
                    success = self.sem.run_autofocus_stig(
                        self.wd_range, self.wd_final_step, self.autostig_range)
            elif autofocus:
                msg = 'SEM autofocus procedure'
                # Call only autofocus routine
                success = self.sem.run_autofocus(
                        self.wd_range, self.wd_final_step)
            else:
                msg = 'SEM autostig procedure'
                # Call only autostig routine
                success = self.sem.run_autostig(self.autostig_range)
        if success:
            msg = 'Completed ' + msg + '.'
        else:
            msg = 'ERROR during ' + msg + '.'
        return msg

    def run_mapfost_af(self, aberr_mode_bools=[1,1,1], large_aberrations=0, pixel_size=None, max_wd_stigx_stigy= None) -> str:
        """
        MAPFoSt (cf. Binding et al. 2013)
        implementation by Rangoli Saxena, 2020.
        Returns:

        """
        try:
            if pixel_size is None:
                pixel_size = self.pixel_size
            self.sem.apply_frame_settings(self.MAPFOST_FRAME_RESOLUTION, pixel_size , self.mapfost_dwell_time)
            mapfost_params = {'num_aperture': self.mapfost_probe_conv,
                              'stig_rot_deg': self.mapfost_stig_rot,
                              'stig_scale': self.mapfost_stig_scale,
                              'crop_size': self.MAPFOST_PATCH_SIZE}
            corrections = autofocus_mapfost.run(self.sem, working_distance_perturbations=[self.mapfost_wd_pert],
                                                mapfost_params=mapfost_params, max_iters = self.mapfost_max_iters,
                                                convergence_threshold = self.mapfost_conv_thresh,
                                                aberr_mode_bools=aberr_mode_bools, large_aberrations=large_aberrations,
                                                max_wd_stigx_stigy=max_wd_stigx_stigy)
            msg = 'Completed MAPFoSt AF. \n List of corrections : \n' + str(corrections)
        except Exception as e:
            msg = f'CTRL: Exception ({str(e)}) during MAPFoSt AF.'
        return msg


    def calibrate_mapfost_af(self, calib_mode) -> str:
        """
        MAPFoSt calibration
        Rangoli Saxena, 2020.
        Still in development. In case of issues, please raise them on github to help make this better.
        Returns: mapfost calibration parameters

        """
        try:
            self.sem.apply_frame_settings(self.MAPFOST_FRAME_RESOLUTION, self.pixel_size, self.mapfost_dwell_time)
            mapfost_params = {'num_aperture': self.mapfost_probe_conv,
                              'stig_rot_deg': 0,
                              'stig_scale': [1.,1.],
                              'crop_size': self.MAPFOST_PATCH_SIZE}
            calib_param = autofocus_mapfost.calibrate(self.sem, mapfost_params=mapfost_params,
                                                      calib_mode=calib_mode)
            msg = calib_param
        except Exception as e:
            msg = f'CTRL: Exception ({str(e)}) during MAPFoSt AF.'
        return msg


    # ================ Below: methods for heuristic autofocus ==================

    def prepare_tile_for_heuristic_af(self, tile_img, tile_key):
        """Crop tile_img provided as numpy array. Save in dictionary with
        tile_key.
        """
        height, width = tile_img.shape[0], tile_img.shape[1]
        # Crop image to 512 x 512 central area
        self.img[tile_key] = tile_img[int(height/2 - 256):int(height/2 + 256),
                                      int(width/2 - 256):int(width/2 + 256)]

    def process_image_for_heuristic_af(self, tile_key):
        """Compute single-image estimators as described in Appendix A of
        Binding et al. (2013).
        """

        # The image from the dictionary self.img is provided as a numpy array
        # and already cropped to 512 x 512 pixels
        img = self.img[tile_key]
        mean = int(np.mean(img))
        # Recast as int16 and subtract mean
        img = img.astype(np.int16)
        img -= mean
        # Autocorrelation
        norm = np.sum(img ** 2)
        autocorr = fftconvolve(img, img[::-1, ::-1]) / norm
        height, width = autocorr.shape[0], autocorr.shape[1]
        # Crop to 64 x 64 px central region
        autocorr = autocorr[int(height/2 - 32):int(height/2 + 32),
                            int(width/2 - 32):int(width/2 + 32)]
        # Calculate coefficients
        fi = self.muliply_with_mask(autocorr, self.fi_mask)
        fo = self.muliply_with_mask(autocorr, self.fo_mask)
        apx = self.muliply_with_mask(autocorr, self.apx_mask)
        amx = self.muliply_with_mask(autocorr, self.amx_mask)
        apy = self.muliply_with_mask(autocorr, self.apy_mask)
        amy = self.muliply_with_mask(autocorr, self.amy_mask)
        # Check if tile_key not in dictionary yet
        if not (tile_key in self.foc_est):
            self.foc_est[tile_key] = []
        if not (tile_key in self.astgx_est):
            self.astgx_est[tile_key] = []
        if not (tile_key in self.astgy_est):
            self.astgy_est[tile_key] = []
        # Calculate single-image estimators for current tile key
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
            # Check if results are within permissible range
            within_range = (abs(wd_corr/1000) <= self.max_wd_diff
                            and abs(ax_corr) <= self.max_stig_x_diff
                            and abs(ay_corr) <= self.max_stig_y_diff)
            if within_range:
                # Store corrections for this tile in dictionary
                self.wd_stig_corr[tile_key] = [wd_corr/1000, ax_corr, ay_corr]
            else:
                self.wd_stig_corr[tile_key] = [0, 0, 0]

            return wd_corr, ax_corr, ay_corr, within_range
        else:
            return None, None, None, False

    def get_heuristic_average_grid_correction(self, grid_index):
        """Use the available corrections for the reference tiles in the grid
        specified by grid_index to calculate the average corrections for the
        entire grid.
        """
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
        """Apply individual tile corrections."""
        for tile_key in self.wd_stig_corr:
            g, t = tile_key.split('.')
            g, t = int(g), int(t)
            self.gm[g][t].wd += self.wd_stig_corr[tile_key][0]
            self.gm[g][t].stig_xy[0] += self.wd_stig_corr[tile_key][1]
            self.gm[g][t].stig_xy[1] += self.wd_stig_corr[tile_key][2]

    def make_heuristic_weight_function_masks(self):
        # Parameters as given in Appendix A of Binding et al. 2013
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
                    r = 1  # Prevent division by zero
                sinφ = x/r
                cosφ = y/r
                exp_astig = exp(-r**2/α) - exp(-r**2/β)

                # Six masks for the calculation of coefficients:
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

    def reset_heuristic_corrections(self):
        self.foc_est = {}
        self.astgx_est = {}
        self.astgy_est = {}
        self.wd_stig_corr = {}


    # ================ Methods for Automated Focus/Stigmator Series ==================

    def get_average_afss_correction(self, do_filtering: bool, do_weighted_average: bool):
        #  Function for mode='Average' in f(apply_afss_corrections)
        valid_diffs = {}
        m = self.afss_mode
        dd = {FOCUS: (0, 0), STIG_X: (1, 0), STIG_Y: (1, 1)}
        self.afss_stats = {'avg': 0, 'n_failed': 0, 'n_out_of_lim': 0, 'n_outliers': 0}

        # Remove corrupted results from optima dict due unsuccessful fit(s)
        d = deepcopy(self.afss_wd_stig_corr_optima)
        for t, vals in list(d.items()):
            rmse_val = vals[1]
            if rmse_val == -1:
                self.afss_stats['n_failed'] += 1
                del d[t]
            if rmse_val > self.afss_rmse_limit:
                self.afss_stats['n_out_of_lim'] += 1
                del d[t]

        # Get optimal WD/Stig differences for set of valid results
        for tile_key, vals in d.items():
            valid_diffs[tile_key] = vals[0] - self.afss_wd_stig_orig[tile_key][dd[m][0]][dd[m][1]]

        # Remove outliers from set of optimal WD/Stig differences
        diffs = list(valid_diffs.values())
        if do_filtering and len(diffs) > 2:
            diffs_filtered = utils.filter_outliers(np.asarray(diffs))
            self.afss_stats['n_outliers'] = len(diffs) - len(diffs_filtered)
            diffs = diffs_filtered
            # Remove filtered entries from helper dict (used in weights)
            for k, v in list(valid_diffs.items()):
                if v not in diffs:
                    del (valid_diffs[k])

        # Final check if amount of remaining differences is sufficient
        if len(valid_diffs) < self.afss_min_good_fits:
            avg = np.nan
        # Perform weighted averaging if applicable
        elif do_weighted_average and len(diffs) > 1:
            # Weights for weighted average are calculated from RMSE values
            rmse_ = [self.afss_wd_stig_corr_optima[key][1] for key in valid_diffs.keys()]
            weights = utils.get_weights(rmse_, smallest_weight=0.3)
            # Prevent division by zero if by any change the sum of weight is zero
            if np.sum(weights) == 0:
                weights[0] -= 1e-9
            avg = np.average(diffs, weights=weights)
        else:
            avg = np.mean(diffs)

        self.afss_avg_corr = avg
        self.afss_stats['avg'] = avg


    def afss_verify_results(self) -> Tuple[int, dict, bool, dict]:
        rej_fits = {}
        rej_thr = {}
        diffs_passed = False
        num_good_fits = -1

        LUT = {FOCUS: (0, 0, self.max_wd_diff, 10 ** 6, 'WD', 'um'),
               STIG_X: (1, 0, self.max_stig_x_diff, 1, 'StigX', '%'),
               STIG_Y: (1, 1, self.max_stig_y_diff, 1, 'StigY', '%')
               }

        # Determine averaging mode
        is_avg_mode = (self.afss_consensus_mode == 0 or (self.afss_consensus_mode == 2 and self.afss_mode != FOCUS))

        # Early return for invalid average mode
        if is_avg_mode and self.afss_avg_corr is None:
            return num_good_fits, rej_fits, diffs_passed, rej_thr

        # Remove corrupted results from optima dict, due unsuccessful fit(s)
        opts = self.afss_wd_stig_corr_optima
        for t, vals in list(opts.items()):
            rmse_val = vals[1]
            if rmse_val > self.afss_rmse_limit or rmse_val == -1:
                del opts[t]
                rej_fits[t] = (rmse_val, f'Tile {t} fit rejected.')

        num_good_fits = len(opts)
        if num_good_fits == 0:
            diffs_passed = False
            return num_good_fits, rej_fits, diffs_passed, rej_thr

        attr = LUT[self.afss_mode]

        if is_avg_mode:
            if np.isnan(self.afss_avg_corr):
                num_good_fits = -1
                diffs_passed = False
            else:
                diff = abs(self.afss_avg_corr)
                d1 = round(self.afss_avg_corr * attr[3], 3)
                d2 = round(attr[2] * attr[3], 3)
                unit = attr[5]
                msg = f'Average {attr[4]} correction: {d1} {unit} (Limit: {d2} {unit})'
                if diff > attr[2]:  # Average diff is out of range
                    rej_thr[list(opts.keys())[0]] = (d1, msg)
                else:
                    diffs_passed = True
            return num_good_fits, rej_fits, diffs_passed, rej_thr

        # Check that computed optimal WD and Stigmator values
        # of all reference tiles are below WD/Stig thresholds
        diffs_passed = True
        for tile_key, opt in opts.items():
            i1, i2 = attr[0], attr[1]
            diff = opt[0] - self.afss_wd_stig_orig[tile_key][i1][i2]
            diff = round(abs(diff), 6)
            if diff > attr[2]:
                d1 = round(diff * attr[3], 3)
                d2 = round(attr[2] * attr[3], 3)
                unit = attr[5]
                msg = f'Tile {tile_key}: diff{attr[4]}: {d1} {unit}, limit: {d2} {unit}'
                rej_thr[tile_key] = (d1, msg, self.afss_wd_stig_orig[tile_key])

            diffs_passed &= diff <= attr[2]

        return num_good_fits, rej_fits, diffs_passed, rej_thr


    def afss_compute_pair_drifts(self):
        for tile_key in self.afss_wd_stig_corr:
            filenames = []
            for slice_nr in self.afss_wd_stig_corr[tile_key]:
                img_path = self.afss_wd_stig_corr[tile_key][slice_nr][3]
                filenames.append(img_path)
            newest_img_pair_fns = filenames[-2:]

            # Cross-correlation using opencv lib
            shift_vec = utils.compute_shifts_cv2(newest_img_pair_fns)
            self.afss_wd_stig_corr[tile_key][slice_nr].append(shift_vec)


    def process_afss_collections(self):

        for tile_key in self.afss_wd_stig_corr:
            fns = []
            shifts = []

            # Collect shift vectors and image filenames
            for i, slice_nr in enumerate(self.afss_wd_stig_corr[tile_key]):
                fns.append(self.afss_wd_stig_corr[tile_key][slice_nr][3])
                if i != 0:  # Skip reading shift vector of first image as this was not registered to anything
                    shifts.append(self.afss_wd_stig_corr[tile_key][slice_nr][5][0])

            # Load tile-image data, align them translationally and perform cropping
            cumm_shifts = np.cumsum(shifts, axis=0)
            ic = utils.load_image_collection(fns)
            ic = utils.shift_collection(ic, cumm_shifts)
            ic = utils.crop_image_collection(ic, cumm_shifts)

            # Validate image collection after cropping
            coll_sharpness = [np.nan] * len(ic)  # Defaults to NaNs if not valid
            if utils.validate_img_collection(ic):
                coll_sharpness = utils.get_collection_sharpness(ic, metric='edges')

                # Save sharpness plots to project stats folder
                if self.save_reg_coll:
                    prefix = os.path.join(self.cfg['acq']['base_dir'], 'meta', 'stats')
                    utils.store_reg_coll(ic, fns, prefix)

            # Fill the results' dict with sharpness values from drift-corrected image collection
            for i, slice_nr in enumerate(self.afss_wd_stig_corr[tile_key]):
                self.afss_wd_stig_corr[tile_key][slice_nr][2] = coll_sharpness[i]

        return


    def fit_afss_collections(self, plot_results=True):

        def norm_data(arr: np.ndarray) -> np.ndarray:
            arr -= np.min(arr)
            arr /= np.max(arr)
            return arr

        m = self.afss_mode
        rmse_lim = self.afss_rmse_limit
        fit_slope = self.afss_min_slope

        for tile_key in self.afss_wd_stig_corr:
            tile_dict = self.afss_wd_stig_corr[tile_key]  # Values of particular tile to be processed
            x_vals = np.asarray([], dtype=float)
            y_vals = np.asarray([], dtype=float)
            y_vals_std = np.asarray([], dtype=float)

            # Read WD/stig_x/stig_y, sharpness values
            d = {FOCUS: (0, 0), STIG_X: (1, 0), STIG_Y: (1, 1)}
            x_orig = self.afss_wd_stig_orig[tile_key][d[m][0]][d[m][1]]  # for plotting purposes
            for slice_nr in tile_dict:
                x_vals = np.append(x_vals, tile_dict[slice_nr][d[m][0]][d[m][1]])  # WD, StigX or StigY series
                y_vals = np.append(y_vals, tile_dict[slice_nr][2])  # List of sharpness values
                y_vals_std = np.append(y_vals_std, tile_dict[slice_nr][4])  # List of 'contrast' values

            # Combined sharpness metric
            y_vals = np.sqrt(norm_data(norm_data(y_vals) ** 2 + norm_data(y_vals_std) ** 2))

            # Fit sharpness values with second-order polynom or linear fit
            x_opt, y_opt, rmse, x_fit, y_fit, fit_valid = utils.afss_fit_poly(x_vals, y_vals)

            if not fit_valid:
                x_opt, y_opt, rmse, x_fit, y_fit, fit_valid = utils.afss_fit_linear(x_vals, y_vals, fit_slope)

            # Store results and proceed with plotting
            rmse_mod = -1 if not fit_valid else rmse
            self.afss_wd_stig_corr_optima[tile_key] = list((x_opt, rmse_mod))

            # Save resulting plots into the 'meta/stats/' folder
            if plot_results:
                plot_path = self.generate_afss_plot_path(tile_key)
                self.plot_afss_series(
                    np.asarray(x_vals),
                    np.asarray(y_vals),
                    x_fit, y_fit, x_opt, y_opt,
                    x_orig, rmse,
                    plot_path
                )

        if self.afss_consensus_mode == 0 or (self.afss_consensus_mode == 2 and self.afss_mode != FOCUS):
            self.get_average_afss_correction(self.afss_filter_outliers, self.afss_weighted_averaging)

        # Reset the correction dictionary to prepare it for next AFSS run
        self.afss_wd_stig_corr = {}


    def generate_afss_plot_path(self, tile_key: str) -> str:
        # Generate plot name: basedir + 'slice_nr'_'grid_nr'_'tile_nr'_'focus/x_stig/y_stig_polyfit'.png
        tile_dict = self.afss_wd_stig_corr[tile_key]
        g, t = tile_key.split('.')
        # First slice number of AFSS series
        first_slice_nr: str = 's' + str(next(iter(tile_dict))).zfill(utils.SLICE_DIGITS)
        tile_key_full = ('g' + str(g).zfill(utils.GRID_DIGITS) + '_' + 't' + str(t).zfill(utils.TILE_DIGITS))
        plot_name = "_".join([first_slice_nr, tile_key_full, self.afss_mode, 'polyfit'])
        plot_fn = os.path.join(self.cfg['acq']['base_dir'], 'meta', 'stats', plot_name + '.png')
        return plot_fn


    def plot_afss_series(self,
                         x_vals: np.ndarray, y_vals: np.ndarray,
                         x_fit: np.ndarray, y_fit: np.ndarray,
                         x_opt: Optional[float], y_opt: Optional[float],
                         x_orig: float, err: float,
                         path: str
                         ):
        if self.afss_mode == FOCUS:  # rescale x axis to millimetres
            x_vals *= 10 ** 3
            x_fit *= 10 ** 3
            if x_opt is not None:
               x_opt *= 10 ** 3
            x_orig *= 10 ** 3
            round_digits = 6
            unit = 'mm'
        else:
            round_digits = 3
            unit = '%'

        fig, ax = plt.subplots()
        plt.rcParams['figure.figsize'] = (12, 8)
        plt.rcParams.update({'font.size': 12})
        ax.plot(x_vals, y_vals, 'o', label='Data')
        ax.plot(x_fit, y_fit, '-', label=f'Fit, RMSE = {np.round(err, 4)} (limit = {self.afss_rmse_limit})')
        ax.axvline(x_orig, color='k', linestyle=':', label=f'Previous setting: {round(x_orig, round_digits)} {unit}')
        if x_opt is not None:
            label = f"New optimum at: {round(x_opt, round_digits)} {unit}, diff = {round(x_opt - x_orig, round_digits)} {unit}"
            ax.plot(x_opt, y_opt, 'o', label=label)
        ax.legend()
        ax.set_title(str.split(os.path.basename(path), '.')[0] + '_series')
        x_labels = {FOCUS: 'Working distance [mm]', STIG_X: 'StigX [%]', STIG_Y: 'StigY [%]'}
        plt.xlabel([val for key, val in x_labels.items() if key == self.afss_mode][0])
        plt.ylabel('Sharpness [arb.u]')
        plt.savefig(path, dpi=100)
        plt.cla()
        plt.close(fig)

    @staticmethod
    def parse_tile_key(tile_key: str) -> Tuple[int, int]:
        """Parses tile_key into g and t, ensuring exactly two components."""
        parts = tile_key.split('.')

        # Check if there are exactly two components
        if len(parts) != 2:
            raise ValueError(f"Invalid tile_key format: {tile_key}. Expected format 'g.t' with exactly two parts.")

        g, t = map(int, parts)
        return g, t

    def update_original_values(self, tile_key, mode):
        """Updates original values based on background mode switch."""

        if self.afss_background_mode:
            return

        g, t = self.parse_tile_key(tile_key)
        if mode == FOCUS:
            self.afss_wd_stig_orig[tile_key][0][0] = self.gm[g][t].wd
        elif mode == STIG_X or mode == STIG_Y:
            self.afss_wd_stig_orig[tile_key][1] = self.gm[g][t].stig_xy
        return

    def generate_wd_message(self, tile_key, cons_mode, applied_wd):
        """Generates log message for the WD update."""

        def_msg = ''
        wd_orig = self.afss_wd_stig_orig[tile_key][0][0]
        if tile_key not in self.afss_wd_stig_corr_optima:
            return f'CTRL: Tile {tile_key}, fit not reliable. Original WD will be applied.'

        if cons_mode in (SPECIFIC, FOCUS_SPC_STIG_AVG):
            diff = applied_wd - wd_orig
            return f'CTRL: Tile {tile_key}, delta WD = {diff * 10 ** 6:.3f} um.'
        return def_msg

    def generate_stig_message(self, tile_key, cons_mode, applied_stig_xy):
        """Generates log message for the Stig update."""

        stig_x_orig, stig_y_orig = self.afss_wd_stig_orig[tile_key][1]
        stig_x_new, stig_y_new = applied_stig_xy
        def_msg = ''

        if tile_key not in self.afss_wd_stig_corr_optima:
            return f'CTRL: Tile {tile_key}, fit not reliable. Original {self.afss_mode} will be applied.'

        if cons_mode == SPECIFIC:
            if self.afss_mode == STIG_X:
                diff = stig_x_new - stig_x_orig
                return f'CTRL: Tile {tile_key}, delta StigX = {diff:.3f} %.'

            if self.afss_mode == STIG_Y:
                diff = stig_y_new - stig_y_orig
                return f'CTRL: Tile {tile_key}, delta StigY = {diff:.3f} %.'

        return def_msg

    def update_wd(self, tile_key, cons_mode):
        """Updates WD for a given tile based on the AFSS consensus mode."""

        wd_orig = self.afss_wd_stig_orig[tile_key][0][0]
        mean_diff = self.afss_stats['avg']
        g, t = self.parse_tile_key(tile_key)

        applied_wd = wd_orig  # Defaults to original WD
        if cons_mode == SPECIFIC and tile_key in self.afss_wd_stig_corr_optima:
            wd_opt = self.afss_wd_stig_corr_optima[tile_key][0]
            applied_wd = wd_opt
        elif cons_mode in (AVG, FOCUS_SPC_STIG_AVG):
            applied_wd = mean_diff + wd_orig

        self.gm[g][t].wd = applied_wd

        return applied_wd

    def update_stig_x(self, tile_key, cons_mode):
        """Updates stig values based on the mode (STIG_X)."""

        stig_x_orig, stig_y_orig = self.afss_wd_stig_orig[tile_key][1]
        mean_diff = self.afss_stats['avg']
        g, t = self.parse_tile_key(tile_key)

        applied_stig_x = stig_x_orig
        if cons_mode == SPECIFIC and tile_key in self.afss_wd_stig_corr_optima:
            stig_x_opt = self.afss_wd_stig_corr_optima[tile_key][0]
            applied_stig_x = stig_x_opt
        elif cons_mode in (AVG, FOCUS_SPC_STIG_AVG):
            applied_stig_x = mean_diff + stig_x_orig

        applied_stig_xy = (applied_stig_x, stig_y_orig)
        self.gm[g][t].stig_xy = applied_stig_xy

        return applied_stig_xy

    def update_stig_y(self, tile_key, cons_mode):
        """Updates stig values based on the mode (STIG_Y)."""

        stig_x_orig, stig_y_orig = self.afss_wd_stig_orig[tile_key][1]
        mean_diff = self.afss_stats['avg']
        g, t = self.parse_tile_key(tile_key)

        applied_stig_y = stig_y_orig
        if cons_mode == SPECIFIC and tile_key in self.afss_wd_stig_corr_optima:
            stig_y_opt = self.afss_wd_stig_corr_optima[tile_key][0]
            applied_stig_y = stig_y_opt
        elif cons_mode in (AVG, FOCUS_SPC_STIG_AVG):
            applied_stig_y = mean_diff + stig_y_orig

        applied_stig_xy = (stig_x_orig, applied_stig_y)
        self.gm[g][t].stig_xy = applied_stig_xy

        return applied_stig_xy

    def update_stig_xy(self, tile_key, cons_mode, afss_mode):
        """Updates both StigX and StigY values based on the mode."""
        if afss_mode == STIG_X:
            return self.update_stig_x(tile_key, cons_mode)
        elif afss_mode == STIG_Y:
            return self.update_stig_y(tile_key, cons_mode)
        else:
            raise ValueError(f"Invalid mode: {afss_mode}. Expected STIG_X or STIG_Y.")

    def apply_afss_corrections(self) -> dict:
        """Applies individual tile corrections and generate log messages."""

        cons_mode: str = (AVG, SPECIFIC, FOCUS_SPC_STIG_AVG)[self.afss_consensus_mode]
        afss_mode = self.afss_mode

        if cons_mode == AVG or (cons_mode == FOCUS_SPC_STIG_AVG and afss_mode != FOCUS):
            self.get_average_afss_correction(self.afss_filter_outliers, self.afss_weighted_averaging)

        msgs = {}
        for tile_key in self.afss_wd_stig_orig:

            if afss_mode == FOCUS:
                applied_wd = self.update_wd(tile_key, cons_mode)
                msgs[tile_key] = self.generate_wd_message(tile_key, cons_mode, applied_wd)

            elif afss_mode in [STIG_X, STIG_Y]:
                applied_stig_xy = self.update_stig_xy(tile_key, cons_mode, afss_mode)
                msgs[tile_key] = self.generate_stig_message(tile_key, cons_mode, applied_stig_xy)

            # Update WD/STIG orig dictionary
            self.update_original_values(tile_key, self.afss_mode)

        return msgs


    def next_afss_mode(self):
        """
        Returns the next AFSS mode in a cyclic sequence (focus -> stig_x -> stig_y -> focus).
        If autostig is not active, defaults to 'FOCUS'.
        """
        default_mode = FOCUS
        mode_transitions = {FOCUS: STIG_X, STIG_X: STIG_Y, STIG_Y: FOCUS}

        if self.afss_autostig_active:
            return mode_transitions.get(self.afss_mode, default_mode)

        return default_mode


    def get_afss_factors(self):
        # Get list of WD or Stig perturbation factors to be used in automated focus/stig series
        do_reflect = True
        do_duplicate = True

        tile_keys = self.afss_data['ref_tiles']

        if self.afss_rounds == 3:
            series = np.asarray((-1, 0, 1), dtype=float)
            for key in tile_keys:
                self.afss_perturbation_series[key] = series
        else:
            if self.afss_rounds == 4:
                do_reflect = False
                do_duplicate = False

            series = np.linspace(-1, 1, self.afss_rounds)
            if do_reflect:
                new = []
                x = series
                for i in range(len(x)):
                    new.append(x[i])
                    new.append(x[::-1][i])
                # 'Reflected' series: fcts = [-1, 1, -0.5, 0.5, 0]
                series = np.asarray(new[:len(x)])
            if do_duplicate:
                new = []
                for x in np.linspace(-1, 1, int(np.ceil(self.afss_rounds / 2))):
                    new.append(x)
                    new.append(x)
                # 'Duplicated' series: fcts = [-1, -1, 0, 0, 1]
                series = np.asarray(new[:self.afss_rounds])
            if self.afss_shuffle:
                # 'Shuffled' series:  fcts = [0, -0.5, 1.0, -1.0, 0.5]
                random.shuffle(list(series))
            if self.afss_hyper_shuffle:
                fcts = np.tile(series, (len(tile_keys), 1))
                for line in fcts:
                    np.random.shuffle(line)
                for i, key in enumerate(tile_keys):
                    self.afss_perturbation_series[key] = fcts[i, :]
            else:
                for key in tile_keys:
                    self.afss_perturbation_series[key] = series


    def reset_afss_corrections(self):
        self.afss_wd_stig_corr = {}
        self.afss_wd_stig_corr_optima = {}
        self.afss_avg_corr = None
        self.afss_stats = {'avg': 0, 'n_failed': 0, 'n_out_of_lim': 0, 'n_outliers': 0}


    def afss_set_orig_wd_stig(self):
        self.afss_current_round = 0
        for tile_key in self.afss_wd_stig_orig:
            grid_index, tile_index = map(int, str.split(tile_key, '.'))
            self.gm[grid_index][tile_index].wd = self.afss_wd_stig_orig[tile_key][0][0]
            self.gm[grid_index][tile_index].stig_xy = self.afss_wd_stig_orig[tile_key][1]

    def format_afss_message(self, delta_wd, delta_stig):
        progress = f'({self.afss_current_round + 1}/{self.afss_data["afss_rounds"]})'
        formats = {
            FOCUS: f'Focus series active {progress}: delta WD = {delta_wd * 1e6:+.3f} um',
            STIG_X: f'Stigmator X series active {progress}: delta StigX = {delta_stig[0]:+.2f} %',
            STIG_Y: f'Stigmator Y series active {progress}: delta StigY = {delta_stig[1]:+.2f} %'
        }
        return formats.get(self.afss_mode, f'Unknown mode {self.afss_mode}')
