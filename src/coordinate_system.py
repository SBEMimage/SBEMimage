# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module maintains the coordinate systems and the stage calibration, and
   provides conversion functionality. It also keeps track of the Viewport scale
   factors and display position coordinates.
   One-letter abbreviations for the type of coordinates used:
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

    def __init__(self, config, sysconfig):
        """Initialize with the user configuration and the system
        configuration."""
        self.cfg = config
        self.syscfg = sysconfig

        if ((self.cfg['sys']['use_microtome'].lower() == 'true')
                and (int(self.syscfg['device']['microtome']) != 5)):
            self._device = 'microtome'
        else:
            self._device = 'sem'
        # Load current stage calibration and calculate transformation factors
        initial_eht = float(self.cfg['sem']['eht'])
        self.calibration_found = False
        self.load_stage_calibration(initial_eht)
        self.apply_stage_calibration()

        # Viewport (vp): centre position of visible area and scaling
        self._vp_centre_dx_dy = json.loads(
            self.cfg['viewport']['vp_centre_dx_dy'])
        self._vp_scale = float(self.cfg['viewport']['vp_scale'])
        self.update_vp_origin_dx_dy()

        # Slice-by-Slice Viewer (sv): scaling and offsets
        # Tiles and OVs have different scale factors.
        self._sv_scale_tile = float(self.cfg['viewport']['sv_scale_tile'])
        self._sv_scale_ov = float(self.cfg['viewport']['sv_scale_ov'])
        # Origin (= upper left corner) of the currently displayed tile
        # relative to the Slice-by-Slice Viewer origin.
        self.sv_tile_vx_vy = [int(self.cfg['viewport']['sv_offset_x_tile']),
                              int(self.cfg['viewport']['sv_offset_y_tile'])]
        # Origin of the current OV relative to the Slice-by-Slice Viewer origin
        self.sv_ov_vx_vy = [int(self.cfg['viewport']['sv_offset_x_ov']),
                            int(self.cfg['viewport']['sv_offset_y_ov'])]

    def save_to_cfg(self):
        """Save current parameters to the self.cfg ConfigParser object.
        The stage calibration parameters are saved to self.syscfg whenever
        the calibration is changed at runtime.
        """
        # Stage calibration parameters
        self.cfg[self._device]['stage_scale_factor_x'] = str(
            self.stage_calibration[0])
        self.cfg[self._device]['stage_scale_factor_y'] = str(
            self.stage_calibration[1])
        self.cfg[self._device]['stage_rotation_angle_x'] = str(
            self.stage_calibration[2])
        self.cfg[self._device]['stage_rotation_angle_y'] = str(
            self.stage_calibration[3])
        # Viewport parameters
        self.cfg['viewport']['vp_centre_dx_dy'] = str(
            utils.round_xy(self.vp_centre_dx_dy))
        self.cfg['viewport']['vp_scale'] = str(round(self.vp_scale, 3))
        self.cfg['viewport']['sv_scale_tile'] = str(
            round(self.sv_scale_tile, 3))
        self.cfg['viewport']['sv_scale_ov'] = str(round(self.sv_scale_ov, 3))
        self.cfg['viewport']['sv_offset_x_tile'] = str(self.sv_tile_vx_vy[0])
        self.cfg['viewport']['sv_offset_y_tile'] = str(self.sv_tile_vx_vy[1])
        self.cfg['viewport']['sv_offset_x_ov'] = str(self.sv_ov_vx_vy[0])
        self.cfg['viewport']['sv_offset_y_ov'] = str(self.sv_ov_vx_vy[1])

    def load_stage_calibration(self, eht):
        eht = int(eht * 1000)  # Dict keys in system config use volts, not kV
        try:
            calibration_params = json.loads(
                self.syscfg['stage'][self._device + '_calibration_params'])
            available_eht_keys = [int(s) for s in calibration_params.keys()]
        except:
            raise Exception(
                'Missing or corrupt calibration data. '
                'Check system configuration!')
        if eht in available_eht_keys:
            self.stage_calibration = calibration_params[str(eht)]
            self.calibration_found = True
        else:
            # Fallback option: nearest among the available EHT calibrations
            closest_eht = 1500  # default if no other closer EHT found.
            min_diff = abs(eht - closest_eht)
            for eht_choice in available_eht_keys:
                diff = abs(eht - eht_choice)
                if diff < min_diff:
                    min_diff = diff
                    closest_eht = eht_choice
            self.stage_calibration = calibration_params[str(closest_eht)]
            self.calibration_found = False

    def apply_stage_calibration(self):
        """(Re)load rotation and scale parameters and compute rotation
        matrix elements.
        """
        self.scale_x, self.scale_y, θ_x, θ_y = self.stage_calibration
        θ_diff = θ_x - θ_y
        if cos(θ_diff) == 0:
            raise ValueError('Illegal values of the stage rotation angles. '
                             'X and Y axes would coincide!')
        # Elements of the rotation matrix are precomputed here to enable
        # faster conversions between SEM and stage coordinates. The matrix
        # elements only change if the user recalibrates the stage.
        # Rotation matrix:   ⎛ a  b ⎞
        #                    ⎝ c  d ⎠
        self.rot_mat_a = cos(θ_y) / cos(θ_diff)
        self.rot_mat_b = -sin(θ_y) / cos(θ_diff)
        self.rot_mat_c = sin(θ_x) / cos(θ_diff)
        self.rot_mat_d = cos(θ_x) / cos(θ_diff)
        self.rot_mat_determinant = (
            self.rot_mat_a * self.rot_mat_d - self.rot_mat_b * self.rot_mat_c)
        if self.rot_mat_determinant == 0:
            raise ValueError('Illegal values of the stage rotation angles. '
                             'Rotation matrix determinant is zero!')

    def save_stage_calibration(self, eht, new_stage_calibration):
        """Save the new_stage_calibration for the specified eht in the system
        configuration.
        """
        self.stage_calibration = new_stage_calibration
        calibration_params = json.loads(
            self.syscfg['stage'][self._device + '_calibration_params'])
        eht = int(eht * 1000)  # Dict keys in system config use volts, not kV
        calibration_params[str(eht)] = self.stage_calibration
        self.syscfg['stage'][self._device + '_calibration_params'] = json.dumps(
            calibration_params)

    def convert_to_s(self, d_coordinates):
        """Convert SEM XY coordinates provided as a tuple or list into stage
        coordinates. The SEM coordinates [dx, dy] are multiplied with the
        rotation matrix.
        """
        dx, dy = d_coordinates
        stage_x = (self.rot_mat_a * dx + self.rot_mat_b * dy) * self.scale_x
        stage_y = (self.rot_mat_c * dx + self.rot_mat_d * dy) * self.scale_y
        return [stage_x, stage_y]

    def convert_to_d(self, s_coordinates):
        """Convert stage XY coordinates provided as a tuple or list into
        SEM coordinates. The stage coordinates are multiplied with the
        inverse of the rotation matrix.
        """
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
        relative to the Viewport origin.
        """
        dx, dy = d_coordinates
        return [int((dx - self._vp_origin_dx_dy[0]) * self._vp_scale),
                int((dy - self._vp_origin_dx_dy[1]) * self._vp_scale)]

    def convert_to_sv(self, d_coordinates, tile_display=True):
        """Convert SEM coordinates in microns (relative to image origin) to
        pixel coordinates in Slice-by-Slice Viewer.
        """
        dx, dy = d_coordinates
        if tile_display:
            scale = self._sv_scale_tile
            offset_x, offset_y = self.sv_tile_vx_vy
        else:
            scale = self._sv_scale_ov
            offset_x, offset_y = self.sv_ov_vx_vy
        return [int(dx * scale + offset_x), int(dy * scale + offset_y)]

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
        """Recalculate the coordinates of the upper left corner of the visible
        area in the Viewport.
        """
        dx, dy = self._vp_centre_dx_dy
        self._vp_origin_dx_dy = [
            dx - 0.5 * utils.VP_WIDTH / self._vp_scale,
            dy - 0.5 * utils.VP_HEIGHT / self._vp_scale]

    @property
    def sv_scale_tile(self):
        return self._sv_scale_tile

    @sv_scale_tile.setter
    def sv_scale_tile(self, new_scale):
        old_scale = self._sv_scale_tile
        self._sv_scale_tile = new_scale
        self.sv_tile_vx_vy = self._adjust_sv_offset(self.sv_tile_vx_vy,
                                                    new_scale / old_scale)
    @property
    def sv_scale_ov(self):
        return self._sv_scale_ov

    @sv_scale_ov.setter
    def sv_scale_ov(self, new_scale):
        old_scale = self._sv_scale_ov
        self._sv_scale_ov = new_scale
        self.sv_ov_vx_vy = self._adjust_sv_offset(self.sv_ov_vx_vy,
                                                  new_scale / old_scale)

    def _adjust_sv_offset(self, old_vx_vy, zoom_ratio):
        """Adjust the origin coordinates (= offset) of the tile/OV displayed
        in the Slice-by-Slice Viewer.
        """
        old_vx, old_vy = old_vx_vy
        dx = utils.VP_WIDTH // 2 - old_vx
        dy = utils.VP_HEIGHT // 2 - old_vy
        return [int(old_vx - zoom_ratio * dx + dx),
                int(old_vy - zoom_ratio * dy + dy)]