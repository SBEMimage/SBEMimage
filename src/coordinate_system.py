# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2019 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module maintains the coordinate systems and the stage calibration, and
   provides conversion functionality.
   One-letter abbreviations for type of coordinates use in this module and
   everywhere else in SBEMimage code:
       s - Microtome or SEM stage in microns. Stage origin at (0, 0)
           _s, sx, sy, sx_sy
       d - SEM coordinates in microns, origin (0, 0) coincides with stage origin
           _d, dx, dy, dx_dy
       [p - Same as d, but in 10-nm pixels; perhaps obsolete]
       v - Pixel coordinates within Viewport window (vx: 0..1000, vy: 0..800)
           _v, vx, vy, vx_vy

       TODO: Location management of overviews, stubs, ... to be moved to
       OverviewManager
"""

from math import sin, cos
import json

class CoordinateSystem():

    def __init__(self, config, sysconfig):
        self.cfg = config
        self.syscfg = sysconfig
        # The pixel size of the global coordinate system is fixed at 10 nm:
        self.CS_PIXEL_SIZE = 10   # This may become obsolete.
        # Current positions of overviews, the stub overview,
        # and imported images (this will be moved to OverviewManager):
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
        # Load current stage calibration and calculate transformation factors
        initial_eht = float(self.cfg['sem']['eht'])
        self.calibration_found = False
        self.load_stage_calibration(initial_eht)
        self.apply_stage_calibration()

    def save_to_cfg(self):
        self.cfg['overviews']['ov_centre_sx_sy'] = str(
            self.ov_centre_sx_sy)
        self.cfg['overviews']['stub_ov_centre_sx_sy'] = str(
            self.stub_ov_centre_sx_sy)
        self.cfg['overviews']['stub_ov_origin_sx_sy'] = str(
            self.stub_ov_origin_sx_sy)
        self.cfg['overviews']['imported_centre_sx_sy'] = str(
            self.imported_img_centre_sx_sy)
        self.cfg['viewport']['mv_centre_dx_dy'] = str(self.mv_centre_dx_dy)
        self.cfg['viewport']['mv_scale'] = str(self.mv_scale)

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
        coordinates. The SEM coordinates (dx, dy) are multiplied with the
        rotation matrix."""
        dx, dy = d_coordinates
        stage_x = (self.rot_mat_a * dx + self.rot_mat_b * dy) * self.scale_x
        stage_y = (self.rot_mat_c * dx + self.rot_mat_d * dy) * self.scale_y
        return stage_x, stage_y

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
        return dx, dy

    def convert_to_v(self, d_coordinates):
        """Convert SEM XY coordinates into Viewport window coordinates.
        These coordinates in units of pixels specify an object's location
        relative to the Viewport origin """
        dx, dy = d_coordinates
        return (int((dx - self.mv_dx_dy[0]) * self.mv_scale),
                int((dy - self.mv_dx_dy[1]) * self.mv_scale))

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