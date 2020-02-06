# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module manages the overview images (region-of-interest overviews [OV]
and stub overviews), as well as single imported images. It can add, delete and
modify overviews, and read parameters from existing overviews.
The classes Overview, StubOverview and ImportedImage are derived from class
Grid in grid_manager.py.
The instance of the OverviewManager class used throughout SBEMimage as self.ovm
(ovm short for overview_manager).
The attributes of overviews be accessed with square brackets, for
example:
self.ovm[ov_index].dwell_time  (dwell_time of the specified overview)
self.ovm['stub'].size  (size of the stub overview grid)
"""

import os
import json

import utils
from grid_manager import Grid


class Overview(Grid):
    def __init__(self, coordinate_system, sem,
                 ov_active, centre_sx_sy, frame_size, frame_size_selector,
                 pixel_size, dwell_time, dwell_time_selector, acq_interval,
                 acq_interval_offset, wd_stig_xy, vp_file_path,
                 debris_detection_area):

        # Initialize the overview as a 1x1 grid
        super().__init__(coordinate_system, sem,
                         active=ov_active, origin_sx_sy=centre_sx_sy,
                         rotation=0, size=[1, 1], overlap=0, row_shift=0,
                         active_tiles=[0], frame_size=frame_size,
                         frame_size_selector=frame_size_selector,
                         pixel_size=pixel_size, dwell_time=dwell_time,
                         dwell_time_selector=dwell_time_selector,
                         display_colour=10, acq_interval=acq_interval,
                         acq_interval_offset=acq_interval_offset,
                         wd_stig_xy=wd_stig_xy)

        self.vp_file_path = vp_file_path
        self.debris_detection_area = debris_detection_area

    # The following property overrides centre_sx_sy from the parent class.
    # Since overviews are 1x1 grids, the centre is the same as the origin.
    @property
    def centre_sx_sy(self):
        return self._origin_sx_sy

    @centre_sx_sy.setter
    def centre_sx_sy(self, sx_sy):
        self._origin_sx_sy = list(sx_sy)

    @property
    def magnification(self):
        return (self.sem.MAG_PX_SIZE_FACTOR
                / (self.frame_size[0] * self.pixel_size))

    @magnification.setter
    def magnification(self, mag):
        # Calculate and set pixel size:
        self.pixel_size = (self.sem.MAG_PX_SIZE_FACTOR
                           / (self.frame_size[0] * mag))

    def bounding_box(self):
        centre_dx, centre_dy = self.centre_dx_dy
        # Top left corner of OV in d coordinate system:
        top_left_dx = centre_dx - self.width_d()/2
        top_left_dy = centre_dy - self.height_d()/2
        bottom_right_dx = top_left_dx + self.width_d()
        bottom_right_dy = top_left_dy + self.height_d()
        return (top_left_dx, top_left_dy, bottom_right_dx, bottom_right_dy)

    def update_debris_detection_area(self, grid_manager,
                                     auto_detection=True, margin=0):
        """Change the debris detection area to cover all tiles from all grids
        that fall within the overview specified by ov_number."""
        if auto_detection:
            (ov_top_left_dx, ov_top_left_dy,
             ov_bottom_right_dx, ov_bottom_right_dy) = self.bounding_box()
            ov_pixel_size = self.pixel_size
            # The following corner coordinates define the debris detection area
            top_left_dx_min, top_left_dy_min = None, None
            bottom_right_dx_max, bottom_right_dy_max = None, None
            # Check all grids for active tile overlap with OV
            for grid_index in range(grid_manager.number_grids):
                for tile_index in grid_manager[grid_index].active_tiles:
                    (min_dx, max_dx, min_dy, max_dy) = (
                        grid_manager[grid_index].tile_bounding_box(tile_index))
                    # Is tile within OV?
                    overlap = not (min_dx >= ov_bottom_right_dx
                                   or min_dy >= ov_bottom_right_dy
                                   or max_dx <= ov_top_left_dx
                                   or max_dy <= ov_top_left_dy)
                    if overlap:
                        # transform coordinates to d coord. rel. to OV image:
                        min_dx -= ov_top_left_dx
                        min_dy -= ov_top_left_dy
                        max_dx -= ov_top_left_dx
                        max_dy -= ov_top_left_dy

                        if (top_left_dx_min is None
                            or min_dx < top_left_dx_min):
                            top_left_dx_min = min_dx
                        if (top_left_dy_min is None
                            or min_dy < top_left_dy_min):
                            top_left_dy_min = min_dy
                        if (bottom_right_dx_max is None
                            or max_dx > bottom_right_dx_max):
                            bottom_right_dx_max = max_dx
                        if (bottom_right_dy_max is None
                            or max_dy > bottom_right_dy_max):
                            bottom_right_dy_max = max_dy

            if top_left_dx_min is None:
                top_left_px, top_left_py = 0, 0
                bottom_right_px = self.width_p()
                bottom_right_py = self.height_p()
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
                    top_left_px - margin, 0, self.width_p())
                top_left_py = utils.fit_in_range(
                    top_left_py - margin, 0, self.height_p())
                bottom_right_px = utils.fit_in_range(
                    bottom_right_px + margin, 0, self.width_p())
                bottom_right_py = utils.fit_in_range(
                    bottom_right_py + margin, 0, self.height_p())
            # set calculated detection area:
            self.debris_detection_area = [
                top_left_px, top_left_py, bottom_right_px, bottom_right_py]
        else:
            # set full detection area:
            self.debris_detection_area = [0, 0, self.width_p(), self.height_p()]

class StubOverview(Grid):

    GRID_SIZE = [[2, 2], [3, 3], [5, 4], [6, 5], [7, 6], [8, 7], [9, 8]]

    def __init__(self, coordinate_system, sem,
                 centre_sx_sy, grid_size_selector, overlap, frame_size_selector,
                 pixel_size, dwell_time_selector, vp_file_path):

        # Initialize the stub overview as a grid
        super().__init__(coordinate_system, sem,
                         active=True, origin_sx_sy=centre_sx_sy,
                         rotation=0, size=self.GRID_SIZE[grid_size_selector],
                         overlap=overlap, row_shift=0, active_tiles=[],
                         frame_size=[], frame_size_selector=frame_size_selector,
                         pixel_size=pixel_size, dwell_time=0.8,
                         dwell_time_selector=dwell_time_selector,
                         display_colour=11)

        self.vp_file_path = vp_file_path
        self._grid_size_selector = grid_size_selector

    @property
    def grid_size_selector(self):
        return self._grid_size_selector

    @grid_size_selector.setter
    def grid_size_selector(self, selector):
        self._grid_size_selector = selector
        self.size = self.GRID_SIZE[selector]
        self.update_tile_positions()


class OverviewManager:

    def __init__(self, config, sem, coordinate_system):
        self.cfg = config
        self.sem = sem
        self.cs = coordinate_system
        self.number_ov = int(self.cfg['overviews']['number_ov'])


        # Load OV parameters from user configuration
        ov_active = json.loads(self.cfg['overviews']['ov_active'])
        ov_centre_sx_sy = json.loads(self.cfg['overviews']['ov_centre_sx_sy'])
        ov_rotation = json.loads(self.cfg['overviews']['ov_rotation'])
        ov_size = json.loads(self.cfg['overviews']['ov_size'])
        ov_size_selector = json.loads(self.cfg['overviews']['ov_size_selector'])

        ov_pixel_size = json.loads(
            self.cfg['overviews']['ov_pixel_size'])
        # self.calculate_ov_mag_from_pixel_size()
        ov_dwell_time = json.loads(self.cfg['overviews']['ov_dwell_time'])
        ov_dwell_time_selector = json.loads(
            self.cfg['overviews']['ov_dwell_time_selector'])
        ov_wd_stig_xy = json.loads(self.cfg['overviews']['ov_wd_stig_xy'])
        ov_acq_interval = json.loads(
            self.cfg['overviews']['ov_acq_interval'])
        ov_acq_interval_offset = json.loads(
            self.cfg['overviews']['ov_acq_interval_offset'])
        ov_vp_file_paths = json.loads(
            self.cfg['overviews']['ov_viewport_images'])
        debris_detection_area = json.loads(
            self.cfg['debris']['detection_area'])

        # Create OV objects
        self.__overviews = []
        for i in range(self.number_ov):
            overview = Overview(self.cs, self.sem, ov_active[i]==1,
                                ov_centre_sx_sy[i], ov_size[i],
                                ov_size_selector[i], ov_pixel_size[i],
                                ov_dwell_time[i], ov_dwell_time_selector[i],
                                ov_acq_interval[i], ov_acq_interval_offset[i],
                                ov_wd_stig_xy[i], ov_vp_file_paths[i],
                                debris_detection_area[i])
            self.__overviews.append(overview)

        self.auto_debris_area_margin = int(
            self.cfg['debris']['auto_area_margin'])

        # Load stub OV settings
        # The acq parameters (frame size, pixel size, dwell time) can at the
        # moment only be changed manually in the config file.

        stub_ov_centre_sx_sy = json.loads(
            self.cfg['overviews']['stub_ov_centre_sx_sy'])
        stub_ov_grid_size_selector = int(
            self.cfg['overviews']['stub_ov_grid_size_selector'])
        stub_ov_overlap = int(self.cfg['overviews']['stub_ov_overlap'])
        stub_ov_frame_size_selector = int(
            self.cfg['overviews']['stub_ov_frame_size_selector'])
        stub_ov_pixel_size = float(self.cfg['overviews']['stub_ov_pixel_size'])
        stub_ov_dwell_time = int(
            self.cfg['overviews']['stub_ov_dwell_time_selector'])
        stub_ov_file_path = (
            self.cfg['overviews']['stub_ov_viewport_image'])

        self.__stub_overview = StubOverview(self.cs, self.sem,
                                            stub_ov_centre_sx_sy,
                                            stub_ov_grid_size_selector,
                                            stub_ov_overlap,
                                            stub_ov_frame_size_selector,
                                            stub_ov_pixel_size,
                                            stub_ov_dwell_time,
                                            stub_ov_file_path)

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

    def __getitem__(self, ov_index):
        """Return the Overview object selected by index."""
        if ov_index == 'stub':
            return self.__stub_overview
        elif ov_index < self.number_ov:
            return self.__overviews[ov_index]
        else:
            return None

    def save_to_cfg(self):
        self.cfg['overviews']['number_ov'] = str(self.number_ov)

        self.cfg['overviews']['ov_active'] = str(
            [int(ov.active) for ov in self.__overviews])
        self.cfg['overviews']['ov_centre_sx_sy'] = str(
            [ov.centre_sx_sy for ov in self.__overviews])
        self.cfg['overviews']['ov_rotation'] = str(
            [ov.rotation for ov in self.__overviews])
        self.cfg['overviews']['ov_size'] = str(
            [ov.frame_size for ov in self.__overviews])
        self.cfg['overviews']['ov_size_selector'] = str(
            [ov.frame_size_selector for ov in self.__overviews])
        self.cfg['overviews']['ov_pixel_size'] = str(
            [ov.pixel_size for ov in self.__overviews])
        self.cfg['overviews']['ov_dwell_time'] = str(
            [ov.dwell_time for ov in self.__overviews])
        self.cfg['overviews']['ov_dwell_time_selector'] = str(
            [ov.dwell_time_selector for ov in self.__overviews])
        self.cfg['overviews']['ov_wd_stig_xy'] = str(
            [ov.wd_stig_xy for ov in self.__overviews])
        self.cfg['overviews']['ov_acq_interval'] = str(
            [ov.acq_interval for ov in self.__overviews])
        self.cfg['overviews']['ov_acq_interval_offset'] = str(
            [ov.acq_interval_offset for ov in self.__overviews])
        self.cfg['overviews']['ov_viewport_images'] = json.dumps(
            [ov.vp_file_path for ov in self.__overviews])
        self.cfg['debris']['detection_area'] = str(
            [ov.debris_detection_area for ov in self.__overviews])
        self.cfg['debris']['auto_area_margin'] = str(
            self.auto_debris_area_margin)
        # Stub OV
        self.cfg['overviews']['stub_ov_centre_sx_sy'] = str(
            self.__stub_overview.centre_sx_sy)
        self.cfg['overviews']['stub_ov_grid_size_selector'] = str(
            self.__stub_overview.grid_size_selector)
        self.cfg['overviews']['stub_ov_overlap'] = str(
            self.__stub_overview.overlap)
        self.cfg['overviews']['stub_ov_frame_size_selector'] = str(
            self.__stub_overview.frame_size_selector)
        self.cfg['overviews']['stub_ov_pixel_size'] = str(
            self.__stub_overview.pixel_size)
        self.cfg['overviews']['stub_ov_dwell_time'] = str(
            self.__stub_overview.dwell_time)
        self.cfg['overviews']['stub_ov_viewport_image'] = str(
            self.__stub_overview.vp_file_path)


    def add_new_overview(self):
        new_ov_index = self.number_ov
        # Position new OV next to previous OV
        x_pos, y_pos = self.__overviews[new_ov_index - 1].centre_sx_sy
        y_pos += 50

        new_ov = Overview(self.cs, self.sem, ov_active=True,
                          centre_sx_sy=[x_pos, y_pos], frame_size=[2048, 1536],
                          frame_size_selector=2, pixel_size=155.0,
                          dwell_time=0.8, dwell_time_selector=4,
                          acq_interval=1, acq_interval_offset=0,
                          wd_stig_xy=0, vp_file_path='',
                          debris_detection_area=[])
        self.__overviews.append(new_ov)
        self.number_ov += 1

    def delete_overview(self):
        """Delete the overview with the highest grid index."""
        self.number_ov -= 1
        del self.__overviews[-1]

    def ov_selector_list(self):
        return ['OV %d' % r for r in range(0, self.number_ov)]

    def max_acq_interval(self):
        """Return the maximum value of the acquisition interval across
        all overviews."""
        acq_intervals = []
        for overview in self.__overviews:
            acq_intervals.append(overview.acq_interval)
        return max(acq_intervals)

    def max_acq_interval_offset(self):
        """Return the maximum value of the acquisition interval offset
        across all overviews."""
        acq_interval_offsets = []
        for overview in self.__overviews:
            acq_interval_offsets.append(overview.acq_interval_offset)
        return max(acq_interval_offsets)

    def intervallic_acq_active(self):
        """Return True if intervallic acquisition is active for at least
        one overview, otherwise return False."""
        for overview in self.__overviews:
            if overview.acq_interval > 1:
                return True
        return False

    def update_all_debris_detections_areas(self, grid_manager):
        auto_detection = (
            self.cfg['debris']['auto_detection_area'].lower() == 'true')
        for overview in self.__overviews:
            overview.update_debris_detection_area(
                grid_manager, auto_detection, self.auto_debris_area_margin)


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



