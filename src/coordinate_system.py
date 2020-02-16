# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module maintains the coordinate systems and the stage calibration, and
   provides conversion functionality.
   One-letter abbreviations for type of coordinates:
       s - Microtome or SEM stage coordinates in microns. Stage origin at (0, 0)
           _s, sx, sy, sx_sy
       d - SEM coordinates in microns, origin (0, 0) coincides with stage origin
           _d, dx, dy, dx_dy
       v - Pixel coordinates within Viewport window (vx: 0..1000, vy: 0..800)
           _v, vx, vy, vx_vy

"""

from math import sin, cos
import json

import utils


class CoordinateSystem:

    VP_WIDTH = 1000
    VP_HEIGHT = 800

    def __init__(self, config, sysconfig):
        self.cfg = config
        self.syscfg = sysconfig

        # Load current stage calibration and calculate transformation factors
        initial_eht = float(self.cfg['sem']['eht'])
        self.calibration_found = False
        self.load_stage_calibration(initial_eht)
        self.apply_stage_calibration()

        # Viewport (vp): visible window position and scaling:
        self._vp_centre_dx_dy = json.loads(
            self.cfg['viewport']['vp_centre_dx_dy'])
        self._vp_scale = float(self.cfg['viewport']['vp_scale'])
        self.update_vp_origin_dx_dy()

        # Slice-by-Slice Viewer (sv): scaling and offsets
        # Two different scale factors for tiles and OVs
        self.sv_scale_tile = float(self.cfg['viewport']['sv_scale_tile'])
        self.sv_scale_ov = float(self.cfg['viewport']['sv_scale_ov'])
        self.sv_tile_vx_vy = [int(self.cfg['viewport']['sv_offset_x_tile']),
                              int(self.cfg['viewport']['sv_offset_x_tile'])]
        self.sv_ov_vx_vy = [int(self.cfg['viewport']['sv_offset_x_ov']),
                            int(self.cfg['viewport']['sv_offset_x_ov'])]

    def save_to_cfg(self):
        if self.cfg['sys']['use_microtome'].lower() == 'true':
            type_of_stage = 'microtome'
        else:
            type_of_stage = 'sem'
        self.cfg[type_of_stage]['stage_scale_factor_x'] = str(
            self.stage_calibration[0])
        self.cfg[type_of_stage]['stage_scale_factor_y'] = str(
            self.stage_calibration[1])
        self.cfg[type_of_stage]['stage_rotation_angle_x'] = str(
            self.stage_calibration[2])
        self.cfg[type_of_stage]['stage_rotation_angle_y'] = str(
            self.stage_calibration[3])

        self.cfg['viewport']['vp_centre_dx_dy'] = str(
            utils.round_xy(self.vp_centre_dx_dy))
        self.cfg['viewport']['vp_scale'] = str(self.vp_scale)

        self.cfg['viewport']['sv_scale_tile'] = str(self.sv_scale_ov)
        self.cfg['viewport']['sv_scale_ov'] = str(self.sv_scale_ov)


    def load_stage_calibration(self, eht):
        eht = int(eht * 1000)  # Dict keys in system config use volts, not kV
        if self.cfg['sys']['use_microtome'].lower() == 'true':
            type_of_stage = 'microtome'
        else:
            type_of_stage = 'sem'
        try:
            calibration_params = json.loads(
                self.syscfg['stage'][type_of_stage + '_calibration_params'])
            available_eht = [int(s) for s in calibration_params.keys()]
        except:
            raise Exception(
                'Missing or corrupt calibration data. '
                'Check system configuration!')
        if eht in available_eht:
            self.stage_calibration = calibration_params[str(eht)]
            self.calibration_found = True
        else:
            # Fallback option: nearest among the available EHT calibrations
            new_eht = 1500
            min_diff = abs(eht - 1500)
            for eht_choice in available_eht:
                diff = abs(eht - eht_choice)
                if diff < min_diff:
                    min_diff = diff
                    new_eht = eht_choice
            self.stage_calibration = calibration_params[str(new_eht)]
            self.calibration_found = False

    def apply_stage_calibration(self):
        """(Re)load rotation and scale parameters and compute rotation
        matrix elements."""
        self.scale_x = float(self.stage_calibration[0])
        self.scale_y = float(self.stage_calibration[1])
        rot_x = float(self.stage_calibration[2])
        rot_y = float(self.stage_calibration[3])
        angle_diff = rot_x - rot_y
        if cos(angle_diff) == 0:
            raise ValueError('Illegal values of the stage rotation angles. '
                             'X and Y axes would coincide!')
        # Elements of the rotation matrix are precomputed here to enable
        # faster computation of the conversions between SEM and stage
        # coordinates. The matrix elements only change if the user recalibrates
        # the stage.
        self.rot_mat_a = cos(rot_y) / cos(angle_diff)
        self.rot_mat_b = -sin(rot_y) / cos(angle_diff)
        self.rot_mat_c = sin(rot_x) / cos(angle_diff)
        self.rot_mat_d = cos(rot_x) / cos(angle_diff)
        self.rot_mat_determinant = (
            self.rot_mat_a * self.rot_mat_d - self.rot_mat_b * self.rot_mat_c)
        if self.rot_mat_determinant == 0:
            raise ValueError('Illegal values of the stage rotation angles. '
                             'Rotation matrix determinant is zero!')

    def save_stage_calibration(self, eht, new_stage_calibration):
        self.stage_calibration = new_stage_calibration
        # Save in system configuration
        if self.cfg['sys']['use_microtome'].lower() == 'true':
            type_of_stage = 'microtome'
        else:
            type_of_stage = 'sem'
        calibration_params = json.loads(
            self.syscfg['stage'][type_of_stage + '_calibration_params'])
        eht = int(eht * 1000)  # Dict keys in system config use volts, not kV
        calibration_params[str(eht)] = self.stage_calibration
        self.syscfg['stage'][type_of_stage + '_calibration_data'] = json.dumps(
            calibration_params)

    def convert_to_s(self, d_coordinates):
        """Convert SEM XY coordinates provided as a tuple or list into stage
        coordinates. The SEM coordinates [dx, dy] are multiplied with the
        rotation matrix."""
        dx, dy = d_coordinates
        stage_x = (self.rot_mat_a * dx + self.rot_mat_b * dy) * self.scale_x
        stage_y = (self.rot_mat_c * dx + self.rot_mat_d * dy) * self.scale_y
        return [stage_x, stage_y]

    def convert_to_d(self, s_coordinates):
        """Convert stage XY coordinates provided as a tuple or list into
        SEM coordinates. The stage coordinates are multiplied with the
        inverse of the rotation matrix."""
        stage_x, stage_y = s_coordinates
        stage_x /= self.scale_x
        stage_y /= self.scale_y
        dx = ((self.rot_mat_d * stage_x - self.rot_mat_b * stage_y)
              / self.rot_mat_determinant)
        dy = ((-self.rot_mat_c * stage_x + self.rot_mat_a * stage_y)
              / self.rot_mat_determinant)
        return [dx, dy]

    def convert_to_v(self, d_coordinates):
        """Convert SEM XY coordinates into Viewport window coordinates.
        These coordinates in units of pixels specify an object's location
        relative to the Viewport origin """
        dx, dy = d_coordinates
        return [int((dx - self._vp_origin_dx_dy[0]) * self._vp_scale),
                int((dy - self._vp_origin_dx_dy[1]) * self._vp_scale)]

    @property
    def vp_centre_dx_dy(self):
        return self._vp_centre_dx_dy

    @vp_centre_dx_dy.setter
    def vp_centre_dx_dy(self, dx_dy):
        self._vp_centre_dx_dy = list(dx_dy)
        self.update_vp_origin_dx_dy()

    @property
    def vp_scale(self):
        return self._vp_scale

    @vp_scale.setter
    def vp_scale(self, new_scale):
        self._vp_scale = new_scale
        self.update_vp_origin_dx_dy()

    def update_vp_origin_dx_dy(self):
        # Recalculate upper left corner of visible window
        dx, dy = self._vp_centre_dx_dy
        self._vp_origin_dx_dy = [
            dx - self.VP_WIDTH / self._vp_scale,
            dy - self.VP_HEIGHT / self._vp_scale]
