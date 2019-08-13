# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module maintains the internal coordinate systems and reference points
   and provides conversion functionality.
   Letter abbreviations for coordinate systems:
       s - SBEM stage in microns. Motor origin: (0, 0)
       d - SEM coordinates as displayed in SmartSEM (in microns),
           origin (0, 0) coincides with stage origin
       p - Same as d, but in 10-nm pixels
       v - Pixel coordinates within Viewport window (X:0..1000, Y:0..800)
"""

from math import sin, cos
import json

class CoordinateSystem():

    def __init__(self, config):
        self.cfg = config
        # The pixel size of the global coordinate system is fixed at 10 nm:
        self.CS_PIXEL_SIZE = 10
        # Current positions of grids, overviews, the stub overview,
        # and imported images:
        self.grid_origin_sx_sy = json.loads(self.cfg['grids']['origin_sx_sy'])
        self.ov_centre_sx_sy = json.loads(
            self.cfg['overviews']['ov_centre_sx_sy'])
        self.stub_ov_centre_sx_sy = json.loads(
            self.cfg['overviews']['stub_ov_centre_sx_sy'])
        self.stub_ov_origin_sx_sy = json.loads(
            self.cfg['overviews']['stub_ov_origin_sx_sy'])
        self.imported_img_centre_sx_sy = json.loads(
            self.cfg['overviews']['imported_centre_sx_sy'])
        # Mosaic viewer (mv): visible window position and scaling:
        self.mv_centre_dx_dy = json.loads(
            self.cfg['viewport']['mv_centre_dx_dy'])
        self.mv_scale = float(self.cfg['viewport']['mv_scale'])
        # Upper left corner of visible window
        self.mv_dx_dy = (self.mv_centre_dx_dy[0] - 500 / self.mv_scale,
                         self.mv_centre_dx_dy[1] - 400 / self.mv_scale)
        # Load current stage parameters and calculate transformation factors:
        self.load_stage_calibration()
        self.load_stage_limits()

    def load_stage_calibration(self):
        """(Re)load rotation and scale parameters and compute
            transformation factors; (re)load current stage motor limits.
        """
        if self.cfg['sys']['use_microtome'] == 'True':
            device = 'microtome'
        else:
            device = 'sem'
        rot_x = float(self.cfg[device]['stage_rotation_angle_x'])
        rot_y = float(self.cfg[device]['stage_rotation_angle_y'])
        self.scale_x = float(self.cfg[device]['stage_scale_factor_x'])
        self.scale_y = float(self.cfg[device]['stage_scale_factor_y'])
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

    def load_stage_limits(self):
        if self.cfg['sys']['use_microtome'] == 'True':
            device = 'microtome'
        else:
            device = 'sem'
        self.stage_limits = [
            int(self.cfg[device]['stage_min_x']),
            int(self.cfg[device]['stage_max_x']),
            int(self.cfg[device]['stage_min_y']),
            int(self.cfg[device]['stage_max_y'])]

    def convert_to_s(self, d_coordinates):
        """Convert SEM coordinates into stage coordinates.
        The SEM coordinates (dx, dy) are multiplied with the rotation matrix."""
        dx, dy = d_coordinates
        stage_x = (self.rot_mat_a * dx + self.rot_mat_b * dy) * self.scale_x
        stage_y = (self.rot_mat_c * dx + self.rot_mat_d * dy) * self.scale_y
        return stage_x, stage_y

    def convert_to_d(self, s_coordinates):
        """Convert stage coordinates into SEM coordinates.
        The stage coordinates are multiplied with the inverse of the rotation
        matrix."""
        stage_x, stage_y = s_coordinates
        stage_x /= self.scale_x
        stage_y /= self.scale_y
        dx = ((self.rot_mat_d * stage_x - self.rot_mat_b * stage_y)
              / self.rot_mat_determinant)
        dy = ((-self.rot_mat_c * stage_x + self.rot_mat_a * stage_y)
              / self.rot_mat_determinant)
        return dx, dy

    def convert_to_v(self, d_coordinates):
        """Convert SEM coordinates into viewport window coordinates. """
        dx, dy = d_coordinates
        return (int((dx - self.mv_dx_dy[0]) * self.mv_scale),
                int((dy - self.mv_dx_dy[1]) * self.mv_scale))

    def get_grid_origin_s(self, grid_number):
        return self.grid_origin_sx_sy[grid_number]

    def set_grid_origin_s(self, grid_number, s_coordinates):
        if grid_number < len(self.grid_origin_sx_sy):
            self.grid_origin_sx_sy[grid_number] = list(s_coordinates)
        else:
            self.grid_origin_sx_sy.append(list(s_coordinates))
        self.cfg['grids']['origin_sx_sy'] = str(self.grid_origin_sx_sy)

    def get_grid_origin_d(self, grid_number):
        return self.convert_to_d(self.grid_origin_sx_sy[grid_number])

    def get_grid_origin_p(self, grid_number):
        dx, dy = self.get_grid_origin_d(grid_number)
        # Divide by pixel size to get pixel coordinates
        return (int(dx * 1000 / self.CS_PIXEL_SIZE),
                int(dy * 1000 / self.CS_PIXEL_SIZE))

    def delete_grid_origin(self, grid_number):
        if grid_number < len(self.grid_origin_sx_sy):
            del self.grid_origin_sx_sy[grid_number]
            self.cfg['grids']['origin_sx_sy'] = str(self.grid_origin_sx_sy)

    def add_grid_origin_s(self, grid_number, s_coordinates):
        # Adds the tiling origin's stage coordinates to the
        # coordinates given as parameter:
        return (self.grid_origin_sx_sy[grid_number][0] + s_coordinates[0],
                self.grid_origin_sx_sy[grid_number][1] + s_coordinates[1])

    def set_ov_centre_s(self, ov_number, s_coordinates):
        if ov_number < len(self.ov_centre_sx_sy):
            self.ov_centre_sx_sy[ov_number] = list(s_coordinates)
        else:
            self.ov_centre_sx_sy.append(list(s_coordinates))
        self.cfg['overviews']['ov_centre_sx_sy'] = str(self.ov_centre_sx_sy)

    def get_ov_centre_s(self, ov_number):
        return self.ov_centre_sx_sy[ov_number]

    def get_ov_centre_d(self, ov_number):
        return self.convert_to_d(self.ov_centre_sx_sy[ov_number])

    def delete_ov_centre(self, ov_number):
        if ov_number < len(self.ov_centre_sx_sy):
            del self.ov_centre_sx_sy[ov_number]
            self.cfg['overviews']['ov_centre_sx_sy'] = str(
                self.ov_centre_sx_sy)

    def set_stub_ov_centre_s(self, s_coordinates):
        self.stub_ov_centre_sx_sy = list(s_coordinates)
        self.cfg['overviews']['stub_ov_centre_sx_sy'] = str(
            self.stub_ov_centre_sx_sy)

    def get_stub_ov_centre_s(self):
        return self.stub_ov_centre_sx_sy

    def set_stub_ov_origin_s(self, s_coordinates):
        self.stub_ov_origin_sx_sy = list(s_coordinates)
        self.cfg['overviews']['stub_ov_origin_sx_sy'] = str(
            self.stub_ov_origin_sx_sy)

    def get_stub_ov_origin_s(self):
        return self.stub_ov_origin_sx_sy

    def get_stub_ov_origin_d(self):
        return self.convert_to_d(self.stub_ov_origin_sx_sy)

    def add_stub_ov_origin_s(self, s_coordinates):
        return (self.stub_ov_origin_sx_sy[0] + s_coordinates[0],
                self.stub_ov_origin_sx_sy[1] + s_coordinates[1])

    def get_imported_img_centre_s(self, img_number):
        return self.imported_img_centre_sx_sy[img_number]

    def get_imported_img_centre_d(self, img_number):
        return self.convert_to_d(
            self.imported_img_centre_sx_sy[img_number])

    def set_imported_img_centre_s(self, img_number, s_coordinates):
        if img_number < len(self.imported_img_centre_sx_sy):
            self.imported_img_centre_sx_sy[img_number] = list(
                s_coordinates)
        else:
            self.imported_img_centre_sx_sy.append(list(s_coordinates))
        self.cfg['overviews']['imported_centre_sx_sy'] = str(
            self.imported_img_centre_sx_sy)

    def delete_imported_img_centre(self, img_number):
        if img_number < len(self.imported_img_centre_sx_sy):
            del self.imported_img_centre_sx_sy[img_number]
            self.cfg['overviews']['imported_centre_sx_sy'] = str(
                self.imported_img_centre_sx_sy)

    def get_mv_centre_d(self):
        return self.mv_centre_dx_dy

    def set_mv_centre_d(self, d_coordinates):
        self.mv_centre_dx_dy = list(d_coordinates)
        self.cfg['viewport']['mv_centre_dx_dy'] = str(self.mv_centre_dx_dy)
        # Recalculate upper left corner of visible window:
        self.mv_dx_dy = (self.mv_centre_dx_dy[0] - 500 / self.mv_scale,
                         self.mv_centre_dx_dy[1] - 400 / self.mv_scale)

    def get_mv_scale(self):
        return self.mv_scale

    def set_mv_scale(self, new_scale):
        self.mv_scale = new_scale
        self.cfg['viewport']['mv_scale'] = str(new_scale)
        # Recalculate upper left corner of visible window
        self.mv_dx_dy = (self.mv_centre_dx_dy[0] - 500 / self.mv_scale,
                         self.mv_centre_dx_dy[1] - 400 / self.mv_scale)

    def get_stage_limits(self):
        return self.stage_limits

    def get_dx_dy_range(self):
        min_sx, max_sx, min_sy, max_sy = self.stage_limits
        dx = [0, 0, 0, 0]
        dy = [0, 0, 0, 0]
        dx[0], dy[0] = self.convert_to_d((min_sx, min_sy))
        dx[1], dy[1] = self.convert_to_d((max_sx, min_sy))
        dx[2], dy[2] = self.convert_to_d((max_sx, max_sy))
        dx[3], dy[3] = self.convert_to_d((min_sx, max_sy))
        return min(dx), max(dx), min(dy), max(dy)

    def is_within_stage_limits(self, s_coordinates):
        within_x = (
            self.stage_limits[0] <= s_coordinates[0] <= self.stage_limits[1])
        within_y = (
            self.stage_limits[2] <= s_coordinates[1] <= self.stage_limits[3])
        return within_x and within_y
