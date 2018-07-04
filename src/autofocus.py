# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""
This module provides automatic focusing and stigmation. Two methods are
implemented: (1) SmartSEM autofocus called in user-specified intervals on
selected tiles. (2) Heuristic algorithm as used in Briggman et al., 2011,
described in Binding et al., 2012; Method (2) is experimental, testing in
progress.

"""

import json
import numpy as np
from math import sqrt, exp, sin, cos
from time import sleep, time
from scipy.misc import imsave
from scipy.signal import correlate2d, fftconvolve


class Autofocus():

    def __init__(self, config, sem, acq_queue, acq_trigger):
        self.cfg = config
        self.sem = sem
        self.queue = acq_queue
        self.trigger = acq_trigger
        self.method = int(self.cfg['autofocus']['method'])
        self.ref_tiles = json.loads(self.cfg['autofocus']['ref_tiles'])
        self.interval = int(self.cfg['autofocus']['interval'])
        self.autostig_delay = int(self.cfg['autofocus']['autostig_delay'])
        self.pixel_size = float(self.cfg['autofocus']['pixel_size'])
        # Maximum allowed change in focus/stigmation:
        self.max_wd_diff, self.max_sx_diff, self.max_sy_diff = json.loads(
            self.cfg['autofocus']['max_wd_stig_diff'])
        # For heuristic autofocus:
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
        self.foc_est = {}
        self.astgx_est = {}
        self.astgy_est = {}

    def is_active(self):
        return (self.cfg['acq']['use_autofocus'] == 'True')

    def get_method(self):
        return self.method

    def set_method(self, method):
        self.method = method
        self.cfg['autofocus']['method'] = str(method)

    def get_ref_tiles(self):
        return self.ref_tiles

    def set_ref_tiles(self, ref_tile_list):
        self.ref_tiles = ref_tile_list
        self.cfg['autofocus']['ref_tiles'] = json.dumps(ref_tile_list)

    def get_interval(self):
        return self.interval

    def set_interval(self, interval):
        self.interval = interval
        self.cfg['autofocus']['interval'] = str(interval)

    def get_autostig_delay(self):
        return self.autostig_delay

    def set_autostig_delay(self, delay):
        self.autostig_delay = delay
        self.cfg['autofocus']['autostig_delay'] = str(delay)

    def get_pixel_size(self):
        return self.pixel_size

    def set_pixel_size(self, pixel_size):
        self.pixel_size = pixel_size
        self.cfg['autofocus']['pixel_size'] = str(pixel_size)

    def get_max_wd_stig_diff(self):
        return [self.max_wd_diff, self.max_sx_diff, self.max_sy_diff]

    def set_max_wd_stig_diff(self, max_diffs):
        self.max_wd_diff, self.max_sx_diff, self.max_sy_diff = max_diffs
        self.cfg['autofocus']['max_wd_stig_diff'] = str(max_diffs)

    def check_wd_stig_diff(self, prev_wd, prev_sx, prev_sy):
        diff_wd = abs(self.sem.get_wd() - prev_wd)
        diff_sx = abs(self.sem.get_stig_x() - prev_sx)
        diff_sy = abs(self.sem.get_stig_y() - prev_sy)
        return (diff_wd <= self.max_wd_diff
                and diff_sx <= self.max_sx_diff
                and diff_sy <= self.max_sy_diff)

    def is_active_current_slice(self, slice_counter):
        autofocus_current_slice, autostig_current_slice = False, False
        if slice_counter > 0:
            autofocus_current_slice = (slice_counter % self.interval == 0)
        if -1 < self.autostig_delay < slice_counter:
            autostig_current_slice = ((
                (slice_counter - self.autostig_delay) % self.interval) == 0)
        return (autofocus_current_slice, autostig_current_slice)

    def is_tile_selected(self, grid_number, tile_number):
        grid_tile_str = str(grid_number) + '.' + str(tile_number)
        return (grid_tile_str in self.ref_tiles)

    def run_zeiss_af(self, autofocus=True, autostig=True):
        msg = 'CTRL: SmartSEM AF did not run.'
        if autofocus or autostig:
            # Switch to autofocus settings:
            self.sem.apply_frame_settings(0, self.pixel_size, 0.8)
            sleep(0.5)
            if autofocus and autostig:
                # Perform combined autofocus + autostig:
                # Call SmartSEM routine:
                success = self.sem.run_autofocus_stig()
                if success:
                    msg = ('CTRL: Completed SmartSEM autofocus + '
                           'autostig procedure.')
                else:
                    msg = ('CTRL: ERROR during SmartSEM autofocus + '
                           'autostig procedure.')
            elif autofocus:
                # Call SmartSEM routine:
                success = self.sem.run_autofocus()
                if success:
                    msg = ('CTRL: Completed SmartSEM autofocus '
                           'procedure.')
                else:
                    msg = ('CTRL: ERROR during SmartSEM autofocus '
                           'procedure.')
            else:
                success = self.sem.run_autostig()
                if success:
                    msg = ('CTRL: Completed SmartSEM autostig '
                           'procedure.')
                else:
                    msg = ('CTRL: ERROR during SmartSEM autostig '
                           'procedure.')
        return msg

    # ===== Below: Heuristic autofocus =======

    def process_heuristic_new_image(self, img, tile_key, slice_counter):
        """Compute single-image estimators as described in
           Binding et al., 2013"""

        # image provided as numpy array.
        # Crop image to 512x512:
        height, width = img.shape[0], img.shape[1]
        img = img[int(height/2 - 256):int(height/2 + 256),
                  int(width/2 - 256):int(width/2 + 256)]
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
            return wd_corr, ax_corr, ay_corr
        else:
            return None, None, None

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

    def get_heuristic_deltas(self):
        return [self.wd_delta, self.stig_x_delta, self.stig_y_delta]

    def set_heuristic_deltas(self, deltas):
        self.wd_delta, self.stig_x_delta, self.stig_y_delta = deltas
        self.cfg['autofocus']['heuristic_deltas'] = str(deltas)

    def get_heuristic_calibration(self):
        return self.heuristic_calibration

    def set_heuristic_calibration(self, calib):
        self.heuristic_calibration = calib
        self.cfg['autofocus']['heuristic_calibration'] = str(calib)

    def get_heuristic_rot_scale(self):
        return [self.rot_angle, self.scale_factor]

    def set_heuristic_rot_scale(self, rot_scale):
        self.rot_angle, self.scale_factor = rot_scale
        self.cfg['autofocus']['heuristic_rot_scale'] = str(
            [self.rot_angle, self.scale_factor])
