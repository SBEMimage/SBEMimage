# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module manages the overview images, the stub overview image, and
   the imported images.
"""

import os
import json

import utils


class OverviewManager(object):

    def __init__(self, config, sem, coordinate_system):
        self.cfg = config
        self.sem = sem
        self.cs = coordinate_system
        self.number_ov = int(self.cfg['overviews']['number_ov'])
        self.ov_rotation = json.loads(self.cfg['overviews']['ov_rotation'])
        self.ov_size_selector = json.loads(
            self.cfg['overviews']['ov_size_selector'])
        self.ov_size_px_py = json.loads(
            self.cfg['overviews']['ov_size_px_py'])
        self.ov_magnification = json.loads(
            self.cfg['overviews']['ov_magnification'])
        self.ov_dwell_time = json.loads(self.cfg['overviews']['ov_dwell_time'])
        self.ov_dwell_time_selector = json.loads(
            self.cfg['overviews']['ov_dwell_time_selector'])
        self.ov_wd = json.loads(self.cfg['overviews']['ov_wd'])
        self.ov_file_list = json.loads(
            self.cfg['overviews']['ov_viewport_images'])
        self.ov_acq_interval = json.loads(
            self.cfg['overviews']['ov_acq_interval'])
        self.ov_acq_interval_offset = json.loads(
            self.cfg['overviews']['ov_acq_interval_offset'])
        self.debris_detection_area = json.loads(
            self.cfg['debris']['detection_area'])
        self.auto_debris_area_margin = int(
            self.cfg['debris']['auto_area_margin'])
        # Stub OV settings:
        # The acq parameters (frame size, dwell time, magnification) can only
        # be changed manually in the config file, are therefore loaded as
        # constants.
        self.stub_ov_grid = []
        self.stub_ov_size_selector = int(
            self.cfg['overviews']['stub_ov_size_selector'])
        self.STUB_OV_SIZE = json.loads(self.cfg['overviews']['stub_ov_size'])
        self.STUB_OV_FRAME_SIZE_SELECTOR = int(
            self.cfg['overviews']['stub_ov_frame_size_selector'])
        self.STUB_OV_MAGNIFICATION = int(
            self.cfg['overviews']['stub_ov_magnification'])
        self.STUB_OV_DWELL_TIME = float(
            self.cfg['overviews']['stub_ov_dwell_time'])
        self.stub_ov_file = self.cfg['overviews']['stub_ov_viewport_image']

        self.STUB_OV_FRAME_WIDTH = (
            self.sem.STORE_RES[self.STUB_OV_FRAME_SIZE_SELECTOR][0])
        self.STUB_OV_FRAME_HEIGHT = (
            self.sem.STORE_RES[self.STUB_OV_FRAME_SIZE_SELECTOR][1])
        self.STUB_OV_OVERLAP = int(self.cfg['overviews']['stub_ov_overlap'])
        self.STUB_OV_PIXEL_SIZE = (
            self.sem.MAG_PX_SIZE_FACTOR
            / (self.STUB_OV_FRAME_WIDTH * self.STUB_OV_MAGNIFICATION))
        self.calculate_stub_ov_grid()

        # Imported images:
        self.number_imported = int(self.cfg['overviews']['number_imported'])
        self.imported_file_list = json.loads(
            self.cfg['overviews']['imported_images'])
        self.imported_names = json.loads(
            self.cfg['overviews']['imported_names'])
        self.imported_rotation = json.loads(
            self.cfg['overviews']['imported_rotation'])
        self.imported_pixel_size = json.loads(
            self.cfg['overviews']['imported_pixel_size'])
        self.imported_size_px_py = json.loads(
            self.cfg['overviews']['imported_size_px_py'])
        self.imported_transparency = json.loads(
            self.cfg['overviews']['imported_transparency'])

    def add_new_ov(self):
        new_ov_number = self.number_ov
        y_pos = utils.fit_in_range(new_ov_number * 40, 0, 400)
        self.cs.set_ov_centre_s(new_ov_number, [0, y_pos])
        self.set_ov_size_selector(new_ov_number, 2)
        self.set_ov_rotation(new_ov_number, 0)
        self.set_ov_magnification(new_ov_number, 360)
        self.set_ov_dwell_time_selector(new_ov_number, 4)
        self.set_ov_wd(new_ov_number, 0)
        self.set_ov_acq_interval(new_ov_number, 1)
        self.set_ov_acq_interval_offset(new_ov_number, 0)
        self.update_ov_file_list(new_ov_number, '')
        self.set_ov_debris_detection_area(new_ov_number, [])
        self.number_ov += 1
        self.cfg['overviews']['number_ov'] = str(self.number_ov)

    def delete_ov(self):
        # Delete last item from each variable:
        self.cs.delete_ov_centre(self.number_ov - 1)
        del self.ov_rotation[-1]
        self.cfg['overviews']['ov_rotation'] = str(self.ov_rotation)
        del self.ov_size_selector[-1]
        self.cfg['overviews']['ov_size_selector'] = str(self.ov_size_selector)
        del self.ov_size_px_py[-1]
        self.cfg['overviews']['ov_size_px_py'] = str(self.ov_size_px_py)
        del self.ov_magnification[-1]
        self.cfg['overviews']['ov_magnification'] = str(self.ov_magnification)
        del self.ov_dwell_time[-1]
        self.cfg['overviews']['ov_dwell_time'] = str(self.ov_dwell_time)
        del self.ov_dwell_time_selector[-1]
        self.cfg['overviews']['ov_dwell_time_selector'] = str(
            self.ov_dwell_time_selector)
        del self.ov_wd[-1]
        self.cfg['overviews']['ov_wd'] = str(self.ov_wd)
        del self.debris_detection_area[-1]
        self.cfg['debris']['detection_area'] = str(self.debris_detection_area)
        del self.ov_file_list[-1]
        self.cfg['overviews']['ov_viewport_images'] = json.dumps(
            self.ov_file_list)
        del self.ov_acq_interval[-1]
        self.cfg['overviews']['ov_acq_interval'] = str(self.ov_acq_interval)
        del self.ov_acq_interval_offset[-1]
        self.cfg['overviews']['ov_acq_interval_offset'] = str(
            self.ov_acq_interval_offset)
        # Number of OV:
        self.number_ov -= 1
        self.cfg['overviews']['number_ov'] = str(self.number_ov)

    def get_number_ov(self):
        return self.number_ov

    def get_ov_str_list(self):
        return ['OV %d' % r for r in range(0, self.number_ov)]

    def get_ov_size_selector(self, ov_number):
        return self.ov_size_selector[ov_number]

    def set_ov_size_selector(self, ov_number, size_selector):
        if ov_number < len(self.ov_size_selector):
            self.ov_size_selector[ov_number] = size_selector
        else:
            self.ov_size_selector.append(size_selector)
        self.cfg['overviews']['ov_size_selector'] = str(
            self.ov_size_selector)
        # Update explicit storage of frame size:
        if ov_number < len(self.ov_size_px_py):
            self.ov_size_px_py[ov_number] = (
                self.sem.STORE_RES[size_selector])
        else:
            self.ov_size_px_py.append(
                self.sem.STORE_RES[size_selector])
        self.cfg['overviews']['ov_size_px_py'] = str(self.ov_size_px_py)

    def get_ov_size_px_py(self, ov_number):
        return self.ov_size_px_py[ov_number]

    def get_ov_width_p(self, ov_number):
        return self.sem.STORE_RES[self.ov_size_selector[ov_number]][0]

    def get_ov_height_p(self, ov_number):
        return self.sem.STORE_RES[self.ov_size_selector[ov_number]][1]

    def get_ov_width_d(self, ov_number):
        return (self.get_ov_width_p(ov_number)
               * self.get_ov_pixel_size(ov_number) / 1000)

    def get_ov_height_d(self, ov_number):
        return (self.get_ov_height_p(ov_number)
               * self.get_ov_pixel_size(ov_number) / 1000)

    def get_ov_size_dx_dy(self, ov_number):
        return (self.get_ov_width_p(ov_number)
               * self.get_ov_pixel_size(ov_number) / 1000,
               self.get_ov_height_p(ov_number)
               * self.get_ov_pixel_size(ov_number) / 1000)

    def get_ov_rotation(self, ov_number):
        return self.ov_rotation[ov_number]

    def set_ov_rotation(self, ov_number, rotation):
        if ov_number < len(self.ov_rotation):
            self.ov_rotation[ov_number] = rotation
        else:
            self.ov_rotation.append(rotation)
        self.cfg['overviews']['ov_rotation'] = str(self.ov_rotation)

    def get_ov_magnification(self, ov_number):
        return self.ov_magnification[ov_number]

    def set_ov_magnification(self, ov_number, mag):
        if ov_number < len(self.ov_magnification):
            self.ov_magnification[ov_number] = mag
        else:
            self.ov_magnification.append(mag)
        self.cfg['overviews']['ov_magnification'] = str(
            self.ov_magnification)

    def get_ov_pixel_size(self, ov_number):
        return (self.sem.MAG_PX_SIZE_FACTOR
                / (self.get_ov_width_p(ov_number)
                * self.ov_magnification[ov_number]))

    def get_ov_dwell_time(self, ov_number):
        return self.ov_dwell_time[ov_number]

    def set_ov_dwell_time(self, ov_number, dwell_time):
        self.ov_dwell_time[ov_number] = dwell_time
        self.cfg['overviews']['ov_dwell_time'] = str(
            self.ov_dwell_time)

    def get_ov_dwell_time_selector(self, ov_number):
        return self.ov_dwell_time_selector[ov_number]

    def set_ov_dwell_time_selector(self, ov_number, selector):
        if ov_number < len(self.ov_dwell_time_selector):
            self.ov_dwell_time_selector[ov_number] = selector
        else:
            self.ov_dwell_time_selector.append(selector)
        self.cfg['overviews']['ov_dwell_time_selector'] = str(
            self.ov_dwell_time_selector)
        # Update explict storage of dwell times:
        if ov_number < len(self.ov_dwell_time):
            self.ov_dwell_time[ov_number] = self.sem.DWELL_TIME[selector]
        else:
            self.ov_dwell_time.append(self.sem.DWELL_TIME[selector])
        self.cfg['overviews']['ov_dwell_time'] = str(self.ov_dwell_time)

    def get_ov_wd(self, ov_number):
        return self.ov_wd[ov_number]

    def set_ov_wd(self, ov_number, wd):
        if ov_number < len(self.ov_wd):
            self.ov_wd[ov_number] = wd
        else:
            self.ov_wd.append(wd)
        self.cfg['overviews']['ov_wd'] = str(self.ov_wd)

    def get_ov_acq_settings(self, ov_number):
        return [self.ov_size_selector[ov_number],
                self.ov_magnification[ov_number],
                self.ov_dwell_time[ov_number],
                self.ov_wd[ov_number]]

    def get_ov_acq_interval(self, ov_number):
        return self.ov_acq_interval[ov_number]

    def set_ov_acq_interval(self, ov_number, interval):
        if ov_number < len(self.ov_acq_interval):
            self.ov_acq_interval[ov_number] = interval
        else:
            self.ov_acq_interval.append(interval)
        self.cfg['overviews']['ov_acq_interval'] = str(self.ov_acq_interval)

    def get_ov_acq_interval_offset(self, ov_number):
        return self.ov_acq_interval_offset[ov_number]

    def set_ov_acq_interval_offset(self, ov_number, offset):
        if ov_number < len(self.ov_acq_interval_offset):
            self.ov_acq_interval_offset[ov_number] = offset
        else:
            self.ov_acq_interval_offset.append(offset)
        self.cfg['overviews']['ov_acq_interval_offset'] = str(
            self.ov_acq_interval_offset)

    def is_intervallic_acq_active(self):
        sum_intervals = 0
        for ov_number in range(self.number_ov):
            sum_intervals += self.ov_acq_interval[ov_number]
        if sum_intervals > self.number_ov:
            return True
        else:
            return False

    def is_slice_active(self, ov_number, slice_counter):
        offset = self.ov_acq_interval_offset[ov_number]
        if slice_counter >= offset:
            is_active = (slice_counter - offset) % self.ov_acq_interval[ov_number] == 0
        else:
            is_active = False
        return is_active

    def get_ov_file_list(self):
        return self.ov_file_list

    def get_ov_bounding_box(self, ov_number):
        centre_dx, centre_dy = self.cs.get_ov_centre_d(ov_number)
        # Top left corner of OV in d coordinate system:
        width, height = self.get_ov_size_dx_dy(ov_number)
        top_left_dx = centre_dx - width/2
        top_left_dy = centre_dy - height/2
        bottom_right_dx = top_left_dx + width
        bottom_right_dy = top_left_dy + height
        return (top_left_dx, top_left_dy, bottom_right_dx, bottom_right_dy)

    def update_ov_file_list(self, ov_number, img_path_file_name):
        if ov_number < len(self.ov_file_list):
            self.ov_file_list[ov_number] = img_path_file_name
        else:
            self.ov_file_list.append(img_path_file_name)
        self.cfg['overviews']['ov_viewport_images'] = json.dumps(
            self.ov_file_list)

    def get_ov_cycle_time(self, ov_number):
        # Calculate cycle time from SmartSEM data:
        scan_speed = self.sem.DWELL_TIME.index(self.ov_dwell_time[ov_number])
        size_selector = self.ov_size_selector[ov_number]
        return (self.sem.CYCLE_TIME[size_selector][scan_speed] + 0.2)

    def get_stub_ov_file(self):
        return self.stub_ov_file

    def set_stub_ov_file(self, img_path_file_name):
        self.stub_ov_file = img_path_file_name
        self.cfg['overviews']['stub_ov_viewport_image'] = str(
            self.stub_ov_file)

    def get_stub_ov_size_selector(self):
        return self.stub_ov_size_selector

    def set_stub_ov_size_selector(self, size_selector):
        self.stub_ov_size_selector = size_selector
        self.cfg['overviews']['stub_ov_size_selector'] = str(
            self.stub_ov_size_selector)
        self.calculate_stub_ov_grid()

    def get_stub_ov_grid(self):
        return self.stub_ov_grid

    def calculate_stub_ov_grid(self):
        self.stub_ov_grid = []
        if self.stub_ov_size_selector not in range(7):
            self.stub_ov_size_selector = 4
        self.stub_ov_rows = self.STUB_OV_SIZE[self.stub_ov_size_selector][0]
        self.stub_ov_cols = self.STUB_OV_SIZE[self.stub_ov_size_selector][1]

        ij_grid = []
        for i in range(self.stub_ov_rows):
            for j in range(self.stub_ov_cols):
                if i % 2 == 0:
                    ij_grid.append((j, i))
                else:
                    ij_grid.append((self.stub_ov_cols-1-j, i))
        for (col, row) in ij_grid:
            delta_x = (col * (self.STUB_OV_FRAME_WIDTH
                       - self.STUB_OV_OVERLAP)
                       * self.STUB_OV_PIXEL_SIZE / 1000)
            delta_y = (row * (self.STUB_OV_FRAME_HEIGHT
                       - self.STUB_OV_OVERLAP)
                       * self.STUB_OV_PIXEL_SIZE / 1000)
            (rel_stage_x, rel_stage_y) = (
                self.cs.convert_to_s((delta_x, delta_y)))
            target_x, target_y = (
                self.cs.add_stub_ov_origin_s((rel_stage_x, rel_stage_y)))
            if self.cs.is_within_stage_limits((target_x, target_y)):
                self.stub_ov_grid.append((col, row, target_x, target_y))

    def get_stub_ov_full_size(self):
        width = (self.stub_ov_cols * self.STUB_OV_FRAME_WIDTH
                 - (self.stub_ov_cols-1) * self.STUB_OV_OVERLAP)
        height = (self.stub_ov_rows * self.STUB_OV_FRAME_HEIGHT
                  - (self.stub_ov_rows-1) * self.STUB_OV_OVERLAP)
        return width, height

    def add_imported_img(self):
        new_img_number = self.number_imported
        self.cs.set_imported_img_centre_s(new_img_number, [0, 0])
        self.set_imported_img_rotation(new_img_number, 0)
        self.set_imported_img_file(new_img_number, '')
        self.set_imported_img_size_px_py(new_img_number, 0, 0)
        self.set_imported_img_pixel_size(new_img_number, 10)
        self.set_imported_img_transparency(new_img_number, 0)

        self.number_imported += 1
        self.cfg['overviews']['number_imported'] = str(self.number_imported)

    def delete_imported_img(self, img_number):
        if img_number < self.number_imported:
            self.cs.delete_imported_img_centre(img_number)
            del self.imported_file_list[img_number]
            self.cfg['overviews']['imported_images'] = json.dumps(
                self.imported_file_list)
            del self.imported_names[img_number]
            self.cfg['overviews']['imported_names'] = json.dumps(
                self.imported_names)
            del self.imported_pixel_size[img_number]
            self.cfg['overviews']['imported_pixel_size'] = str(
                self.imported_pixel_size)
            del self.imported_size_px_py[img_number]
            self.cfg['overviews']['imported_size_px_py'] = str(
                self.imported_size_px_py)
            del self.imported_transparency[img_number]
            self.cfg['overviews']['imported_transparency'] = str(
                self.imported_transparency)
            del self.imported_rotation[img_number]
            self.cfg['overviews']['imported_rotation'] = str(
                self.imported_rotation)
            # Number of imported images:
            self.number_imported -= 1
            self.cfg['overviews']['number_imported'] = str(
                self.number_imported)

    def get_number_imported(self):
        return self.number_imported

    def get_imported_img_name(self, img_number):
        return self.imported_names[img_number]

    def set_imported_img_name(self, img_number, name):
        if img_number < len(self.imported_names):
            self.imported_names[img_number] = name
        else:
            self.imported_names.append(name)
        self.cfg['overviews']['imported_names'] = json.dumps(
            self.imported_names)

    def get_imported_img_rotation(self, img_number):
        return self.imported_rotation[img_number]

    def set_imported_img_rotation(self, img_number, angle):
        if img_number < len(self.imported_rotation):
            self.imported_rotation[img_number] = angle
        else:
            self.imported_rotation.append(angle)
        self.cfg['overviews']['imported_rotation'] = str(
            self.imported_rotation)

    def get_imported_img_pixel_size(self, img_number):
        return self.imported_pixel_size[img_number]

    def set_imported_img_pixel_size(self, img_number, pixel_size):
        if img_number < len(self.imported_pixel_size):
            self.imported_pixel_size[img_number] = pixel_size
        else:
            self.imported_pixel_size.append(pixel_size)
        self.cfg['overviews']['imported_pixel_size'] = str(
            self.imported_pixel_size)

    def get_imported_img_width_p(self, img_number):
        return self.imported_size_px_py[img_number][0]

    def get_imported_img_height_p(self, img_number):
        return self.imported_size_px_py[img_number][1]

    def get_imported_img_width_d(self, img_number):
        return (self.get_imported_img_width_p(img_number)
                * self.get_imported_img_pixel_size(img_number) / 1000)

    def get_imported_img_height_d(self, img_number):
        return (self.get_imported_img_height_p(img_number)
                * self.get_imported_img_pixel_size(img_number) / 1000)

    def set_imported_img_size_px_py(self, img_number, px, py):
        if img_number < len(self.imported_size_px_py):
            self.imported_size_px_py[img_number] = [px, py]
        else:
            self.imported_size_px_py.append([px, py])
        self.cfg['overviews']['imported_size_px_py'] = str(
            self.imported_size_px_py)

    def get_imported_img_file(self, img_number):
        return self.imported_file_list[img_number]

    def set_imported_img_file(self, img_number, file):
        if img_number < len(self.imported_file_list):
            self.imported_file_list[img_number] = file
        else:
            self.imported_file_list.append(file)
        self.cfg['overviews']['imported_images'] = json.dumps(
            self.imported_file_list)

    def get_imported_img_file_list(self):
        return self.imported_file_list

    def get_imported_img_file_name_list(self):
        return [os.path.basename(s) for s in self.imported_file_list]

    def get_imported_img_transparency(self, img_number):
        return self.imported_transparency[img_number]

    def set_imported_img_transparency(self, img_number, transparency):
        if img_number < len(self.imported_transparency):
            self.imported_transparency[img_number] = transparency
        else:
            self.imported_transparency.append(transparency)
        self.cfg['overviews']['imported_transparency'] = str(
            self.imported_transparency)

    def get_ov_auto_debris_detection_area_margin(self):
        return self.auto_debris_area_margin

    def set_ov_auto_debris_detection_area_margin(self, margin):
        self.auto_debris_area_margin = margin
        self.cfg['debris']['auto_area_margin'] = str(self.auto_debris_area_margin)

    def get_ov_debris_detection_area(self, ov_number):
        return self.debris_detection_area[ov_number]

    def set_ov_debris_detection_area(self, ov_number, area):
        if ov_number < len(self.debris_detection_area):
            self.debris_detection_area[ov_number] = list(area)
        else:
            self.debris_detection_area.append(list(area))
        self.cfg['debris']['detection_area'] = str(
            self.debris_detection_area)

    def update_all_ov_debris_detections_areas(self, gm):
        for ov_number in range(self.number_ov):
            self.update_ov_debris_detection_area(ov_number, gm)

    def update_ov_debris_detection_area(self, ov_number, gm):
        if self.cfg['debris']['auto_detection_area'] == 'False':
            # set full detection area:
            self.set_ov_debris_detection_area(ov_number,
                [0, 0,
                 self.get_ov_width_p(ov_number),
                 self.get_ov_height_p(ov_number)])
        else:
            (ov_top_left_dx, ov_top_left_dy,
             ov_bottom_right_dx, ov_bottom_right_dy) = (
                self.get_ov_bounding_box(ov_number))
            ov_pixel_size = self.get_ov_pixel_size(ov_number)
            top_left_dx_min, top_left_dy_min = None, None
            bottom_right_dx_max, bottom_right_dy_max = None, None
            #extra_margin = 20
            # Check all grids for active tile overlap with OV
            for grid_number in range(gm.get_number_grids()):
                for tile_number in gm.get_active_tiles(grid_number):
                    (top_left_dx, top_left_dy,
                     bottom_right_dx, bottom_right_dy) = (
                        gm.get_tile_bounding_box(grid_number, tile_number))
                    # Is tile within OV?
                    overlap = not (top_left_dx >= ov_bottom_right_dx
                                   or top_left_dy >= ov_bottom_right_dy
                                   or bottom_right_dx <= ov_top_left_dx
                                   or bottom_right_dy <= ov_top_left_dy)
                    if overlap:
                        # transform coordinates to d coord. rel. to OV image:
                        top_left_dx -= ov_top_left_dx
                        top_left_dy -= ov_top_left_dy
                        bottom_right_dx -= ov_top_left_dx
                        bottom_right_dy -= ov_top_left_dy

                        if (top_left_dx_min is None
                            or top_left_dx < top_left_dx_min):
                            top_left_dx_min = top_left_dx
                        if (top_left_dy_min is None
                            or top_left_dy < top_left_dy_min):
                            top_left_dy_min = top_left_dy
                        if (bottom_right_dx_max is None
                            or bottom_right_dx > bottom_right_dx_max):
                            bottom_right_dx_max = bottom_right_dx
                        if (bottom_right_dy_max is None
                            or bottom_right_dy > bottom_right_dy_max):
                            bottom_right_dy_max = bottom_right_dy

            if top_left_dx_min is None:
                top_left_px, top_left_py = 0, 0
                bottom_right_px = self.get_ov_width_p(ov_number)
                bottom_right_py = self.get_ov_height_p(ov_number)
            else:
                # Now in pixel coordinates of OV image:
                top_left_px = int(top_left_dx_min * 1000 / ov_pixel_size)
                top_left_py = int(top_left_dy_min * 1000 / ov_pixel_size)
                bottom_right_px = int(
                    bottom_right_dx_max * 1000 / ov_pixel_size)
                bottom_right_py = int(
                    bottom_right_dy_max * 1000 / ov_pixel_size)
                # Add/subract margin and must fit in OV image:
                top_left_px = utils.fit_in_range(
                    top_left_px - self.auto_debris_area_margin,
                    0, self.get_ov_width_p(ov_number))
                top_left_py = utils.fit_in_range(
                    top_left_py - self.auto_debris_area_margin,
                    0, self.get_ov_height_p(ov_number))
                bottom_right_px = utils.fit_in_range(
                    bottom_right_px + self.auto_debris_area_margin,
                    0, self.get_ov_width_p(ov_number))
                bottom_right_py = utils.fit_in_range(
                    bottom_right_py + self.auto_debris_area_margin,
                    0, self.get_ov_height_p(ov_number))

            # set detection area:
            self.set_ov_debris_detection_area(ov_number,
                [top_left_px, top_left_py, bottom_right_px, bottom_right_py])
