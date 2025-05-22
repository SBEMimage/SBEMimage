# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module manages the grids. It can add, delete and modify grids, and read
parameters from existing grids. Naming convention for coordinates: s for stage,
d for SEM, p for pixels. Relative coordinates are relative to the grid origin.
Absolute coordinates are relative to the stage origin.
The instance of the GridManager class used throughout SBEMimage is self.gm
(gm short for grid_manager).
The attributes of grids and tiles can be accessed with square brackets, for
example:
self.gm[grid_index].rotation  (rotation angle of specified grid)
self.gm[grid_index][tile_index].sx_sy  (stage position of specified tile)
"""


import cmath
import copy
import json
import numpy as np
import os
import scipy

import ArrayData
import utils
from Grid import Grid
from image_io import imread


class GridManager(list):

    def __init__(self, config, sem, coordinate_system):
        super().__init__()
        self.cfg = config
        self.sem = sem
        self.cs = coordinate_system
        self.template_grid_index = 0
        # Load grid parameters stored as lists in configuration.
        grids_data = self.cfg['grids']
        self.number_grids = int(grids_data['number_grids'])
        grid_active = json.loads(grids_data['grid_active'])
        origin_sx_sy = json.loads(grids_data['origin_sx_sy'])
        # * backward compatibility:
        if 'sw_sh' in grids_data:
            sw_sh = json.loads(grids_data['sw_sh'])
        else:
            sw_sh = []
        rotation = json.loads(grids_data['rotation'])
        size = json.loads(grids_data['size'])
        overlap = json.loads(grids_data['overlap'])
        row_shift = json.loads(grids_data['row_shift'])
        active_tiles = json.loads(grids_data['active_tiles'])
        frame_size = json.loads(grids_data['tile_size'])
        frame_size_selector = json.loads(
            grids_data['tile_size_selector'])
        pixel_size = json.loads(grids_data['pixel_size'])
        dwell_time = json.loads(grids_data['dwell_time'])
        dwell_time_selector = json.loads(
            grids_data['dwell_time_selector'])
        # * backward compatibility:
        if 'bit_depth_selector' in grids_data:
            bit_depth_selector = json.loads(
                grids_data['bit_depth_selector'])
        else:
            bit_depth_selector = []
        display_colour = json.loads(grids_data['display_colour'])
        wd_stig_xy = json.loads(grids_data['wd_stig_xy'])
        acq_interval = json.loads(grids_data['acq_interval'])
        acq_interval_offset = json.loads(
            grids_data['acq_interval_offset'])
        use_wd_gradient = json.loads(
            grids_data['use_wd_gradient'])
        wd_gradient_ref_tiles = json.loads(
            grids_data['wd_gradient_ref_tiles'])
        wd_gradient_params = json.loads(
            grids_data['wd_gradient_params'])
        if 'array_index' in grids_data:
            array_index = json.loads(
                grids_data['array_index'])
        else:
            array_index = []
        if 'roi_index' in grids_data:
            roi_index = json.loads(
                grids_data['roi_index'])
        else:
            roi_index = []

        # Backward compatibility for loading older config files
        if len(grid_active) < self.number_grids:
            grid_active = [1] * self.number_grids
        if len(wd_stig_xy) < self.number_grids:
            wd_stig_xy = [[0, 0, 0]] * self.number_grids
        if len(wd_gradient_params) < self.number_grids:
            wd_gradient_params = [[0, 0, 0]] * self.number_grids
        if len(sw_sh) < self.number_grids:
            sw_sh = [(0, 0)] * self.number_grids
        if len(bit_depth_selector) < self.number_grids:
            bit_depth_selector = [0] * self.number_grids
        if len(array_index) < self.number_grids:
            array_index = [None] * self.number_grids
        if len(roi_index) < self.number_grids:
            roi_index = [None] * self.number_grids

        # Create a list of grid objects with the parameters read from
        # the session configuration.
        for i in range(self.number_grids):
            grid = Grid(self.cs, self.sem, grid_active[i] == 1, origin_sx_sy[i], sw_sh[i],
                        rotation[i], size[i], overlap[i], row_shift[i],
                        active_tiles[i], frame_size[i], frame_size_selector[i],
                        pixel_size[i], dwell_time[i], dwell_time_selector[i],
                        bit_depth_selector[i],
                        display_colour[i], acq_interval[i],
                        acq_interval_offset[i], wd_stig_xy[i],
                        use_wd_gradient[i] == 1, wd_gradient_ref_tiles[i],
                        wd_gradient_params[i])
            grid.array_index = array_index[i]
            grid.roi_index = roi_index[i]
            self.append(grid)

        # Load working distance and stigmation parameters
        wd_stig_dict = json.loads(grids_data['wd_stig_params'])
        for tile_key, wd_stig_xy in wd_stig_dict.items():
            grid_index, tile_index = (int(s) for s in tile_key.split('.'))
            if (grid_index < self.number_grids) and (tile_index < self[grid_index].number_tiles):
                self[grid_index][tile_index].wd = wd_stig_xy[0]
                self[grid_index][tile_index].stig_xy = [wd_stig_xy[1], wd_stig_xy[2]]

        # Load autofocus reference tiles
        self._autofocus_ref_tiles = json.loads(
            self.cfg['autofocus']['ref_tiles'])
        for tile_key in self._autofocus_ref_tiles:
            grid_index, tile_index = (int(s) for s in tile_key.split('.'))
            if (grid_index < self.number_grids) and (tile_index < self[grid_index].number_tiles):
                self[grid_index][tile_index].autofocus_active = True

        # aberration gradient
        self.aberr_gradient_params = None

        # Load tile previews for active tiles if available and if source tiles
        # are present at the current slice number in the base directory
        base_dir = self.cfg['acq']['base_dir']
        stack_name = base_dir[os.path.normpath(base_dir).rfind(os.sep) + 1:]
        slice_counter = int(self.cfg['acq']['slice_counter'])
        for grid_index in range(self.number_grids):
            grid = self[grid_index]
            array_index, roi_index = grid.array_index, grid.roi_index
            slice_index = slice_counter if grid.roi_index is None else None
            prev_slice_index = slice_counter - 1 if grid.roi_index is None else None
            for tile_index in self[grid_index].active_tiles:
                preview_path = utils.tile_preview_save_path(base_dir, grid_index, array_index, roi_index, tile_index)
                tile_path_current = os.path.join(
                    base_dir, utils.tile_relative_save_path(
                        stack_name, grid_index, array_index, roi_index, tile_index, slice_index))
                tile_path_previous = os.path.join(
                    base_dir, utils.tile_relative_save_path(
                        stack_name, grid_index, array_index, roi_index, tile_index, prev_slice_index))
                if (os.path.isfile(preview_path)
                    and (os.path.isfile(tile_path_current)
                         or os.path.isfile(tile_path_previous))):
                    grid[tile_index].preview_img = utils.image_to_QPixmap(imread(preview_path))
                else:
                    grid[tile_index].preview_img = None

        # initialize Array settings
        array_path = grids_data.get('array_file')
        self.array_data = ArrayData.ArrayData(array_path)
        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')

    def get_grid_label(self, grid_index):
        if grid_index is not None:
            return self[grid_index].get_label(grid_index)
        else:
            return ''

    def fit_apply_aberration_gradient(self):
        dc_aberr = dict()
        dc_pos = dict()
        cnt = 0
        for tile_key in self.autofocus_ref_tiles:
            g, t = (int(s) for s in tile_key.split('.'))
            if (g < self.number_grids) and (t < self[g].number_tiles):
                stig_xy = self[g][t].stig_xy
                dc_aberr[(g, t)] = (self[g][t].wd, stig_xy[0], stig_xy[1])
                dc_pos[(g, t)] = self[g][t].sx_sy  # stage coordinates
                cnt += 1
        # make use of python dict's order sensitivity
        arr_pos = np.array(list(dc_pos.values()))
        arr_aberr = np.array(list(dc_aberr.values()))

        # best-fit linear plane
        a = np.c_[arr_pos[:, 0], arr_pos[:, 1], np.ones(arr_pos.shape[0])]
        params_wd, res_wd, _, _ = scipy.linalg.lstsq(a, arr_aberr[:, 0])  # wd
        params_stigx, res_stigx, _, _ = scipy.linalg.lstsq(a, arr_aberr[:, 1])  # stigx
        params_stigy, res_stigy, _, _ = scipy.linalg.lstsq(a, arr_aberr[:, 2])  # stigy
        self.aberr_gradient_params = dict(wd=params_wd, stigx=params_stigx, stigy=params_stigy)

        for g in range(self.number_grids):
            for t in range(self[g].number_tiles):
                corrected_wd = np.sum(self[g][t].sx_sy * params_wd[:2]) + params_wd[2]
                corrected_stigx = np.sum(self[g][t].sx_sy * params_stigx[:2]) + params_stigx[2]
                corrected_stigy = np.sum(self[g][t].sx_sy * params_stigy[:2]) + params_stigy[2]
                self[g][t].stig_xy = (corrected_stigx, corrected_stigy)
                self[g][t].wd = corrected_wd

    def save_to_cfg(self):
        """Save current grid configuration to ConfigParser object self.cfg.
        The reasons why all grid parameters are saved as lists in the user
        configuration are backward compatibility and readability."""
        grids_data = self.cfg['grids']
        grids_data['number_grids'] = str(self.number_grids)
        grids_data['grid_active'] = str(
            [int(grid.active) for grid in self])
        grids_data['origin_sx_sy'] = utils.serialise_list(
            [utils.round_xy(grid.origin_sx_sy) for grid in self])
        grids_data['sw_sh'] = utils.serialise_list(
            [utils.round_xy(grid.sw_sh) for grid in self])
        grids_data['rotation'] = utils.serialise_list(
            [utils.round_floats(grid.rotation, 1) for grid in self])
        grids_data['size'] = str(
            [grid.size for grid in self])
        grids_data['overlap'] = str(
            [grid.overlap for grid in self])
        grids_data['row_shift'] = str(
            [grid.row_shift for grid in self])
        grids_data['active_tiles'] = str(
            [grid.active_tiles for grid in self])
        grids_data['tile_size'] = str(
            [grid.frame_size for grid in self])
        grids_data['tile_size_selector'] = str(
            [grid.frame_size_selector for grid in self])
        grids_data['pixel_size'] = str(
            [grid.pixel_size for grid in self])
        grids_data['dwell_time'] = str(
            [grid.dwell_time for grid in self])
        grids_data['dwell_time_selector'] = str(
            [grid.dwell_time_selector for grid in self])
        grids_data['bit_depth_selector'] = str(
            [grid.bit_depth_selector for grid in self])
        grids_data['display_colour'] = str(
            [grid.display_colour for grid in self])
        grids_data['wd_stig_xy'] = str(
            [grid.wd_stig_xy for grid in self])
        grids_data['acq_interval'] = str(
            [grid.acq_interval for grid in self])
        grids_data['acq_interval_offset'] = str(
            [grid.acq_interval_offset for grid in self])
        grids_data['use_wd_gradient'] = str(
            [int(grid.use_wd_gradient) for grid in self])
        grids_data['wd_gradient_ref_tiles'] = str(
            [grid.wd_gradient_ref_tiles for grid in self])
        grids_data['wd_gradient_params'] = str(
            [grid.wd_gradient_params for grid in self])
        grids_data['array_index'] = (str(
            [grid.array_index for grid in self])
            .replace('None', 'null'))
        grids_data['roi_index'] = (str(
            [grid.roi_index for grid in self])
            .replace('None', 'null'))
        if self.array_mode:
            array_path = self.array_data.path
        else:
            array_path = ''
        grids_data['array_file'] = array_path

        # Save the working distances and stigmation parameters of those tiles
        # that are active and/or selected for the autofocus and/or the
        # working distance gradient.
        wd_stig_dict = {}
        for grid_index in range(self.number_grids):
            for tile_index in range(self[grid_index].number_tiles):
                tile_key = str(grid_index) + '.' + str(tile_index)
                if (self[grid_index][tile_index].wd > 0
                    and (self[grid_index][tile_index].tile_active
                         or self[grid_index][tile_index].autofocus_active
                         or self[grid_index][tile_index].wd_grad_active)):
                    # Only save tiles with WD != 0 which are active or
                    # selected for autofocus or wd gradient.
                    wd_stig_dict[tile_key] = [
                        round(self[grid_index][tile_index].wd, 9),
                        round(self[grid_index][tile_index].stig_xy[0], 6),
                        round(self[grid_index][tile_index].stig_xy[1], 6)
                    ]
        # Save as JSON string in config:
        grids_data['wd_stig_params'] = json.dumps(wd_stig_dict)
        # Also save list of autofocus reference tiles.
        self.cfg['autofocus']['ref_tiles'] = json.dumps(
            self.autofocus_ref_tiles)

        # Save tile previews currently held in memory
        # TODO: store with image_io / metadata
        base_dir = self.cfg['acq']['base_dir']
        for grid_index in range(self.number_grids):
            grid = self[grid_index]
            for tile_index in range(self[grid_index].number_tiles):
                preview_path = utils.tile_preview_save_path(
                    base_dir, grid_index, grid.array_index, grid.roi_index, tile_index)
                img = self[grid_index][tile_index].preview_img
                if img is not None:
                    img.save(preview_path)

    def add_new_grid(self, origin_sx_sy=None, sw_sh=(0, 0), active=True,
                     frame_size=None, frame_size_selector=None, overlap=None,
                     pixel_size=10.0, dwell_time=None, dwell_time_selector=None,
                     bit_depth_selector=0,
                     rotation=0, row_shift=0, acq_interval=1, acq_interval_offset=0,
                     wd_stig_xy=(0, 0, 0), use_wd_gradient=False,
                     wd_gradient_ref_tiles=None, wd_gradient_params=None,
                     size=(5, 5)):
        """Add new grid with default parameters. A new grid is always added
        at the next available grid index, after all existing grids."""
        new_grid_index = self.number_grids
        if origin_sx_sy is None:
            # Position new grid next to the previous grid
            # (default behaviour for adding grids manually in the Viewport)
            x_pos, y_pos = self[new_grid_index - 1].origin_sx_sy
            y_pos += 50
        else:
            x_pos, y_pos = origin_sx_sy

        # Set grid colour
        # Cycle through available colours.
        display_colour = (self[new_grid_index - 1].display_colour + 1) % 10

        new_grid = Grid(self.cs, self.sem,
                        active=active, origin_sx_sy=[x_pos, y_pos], sw_sh=sw_sh,
                        rotation=rotation, size=size, overlap=overlap, row_shift=row_shift,
                        active_tiles=[], frame_size=frame_size,
                        frame_size_selector=frame_size_selector, pixel_size=pixel_size,
                        dwell_time=dwell_time, dwell_time_selector=dwell_time_selector,
                        bit_depth_selector=bit_depth_selector,
                        display_colour=display_colour, acq_interval=acq_interval,
                        acq_interval_offset=acq_interval_offset, wd_stig_xy=wd_stig_xy,
                        use_wd_gradient=use_wd_gradient,
                        wd_gradient_ref_tiles=wd_gradient_ref_tiles,
                        wd_gradient_params=wd_gradient_params)

        self.append(new_grid)
        self.number_grids += 1
        return new_grid

    def delete_grid(self):
        """Delete the grid with the highest grid index. Grids at indices that
        are smaller than the highest index cannot be deleted because otherwise
        grid identities cannot be preserved."""
        if self.number_grids > 0:
            grid = self[-1]
            self.remove(grid)
            del grid
            self.number_grids -= 1

    def delete_array_grids(self, keep_template_grids=False):
        """Delete all array grids"""
        for grid in reversed(self):
            if grid.roi_index is not None and (grid.array_index is not None or not keep_template_grids):
                self.remove(grid)
                del grid
        self.number_grids = len(self)

    # TODO: support drawing rotated grids
    def draw_grid(self, x, y, w, h):
        """Draw grid/tiles rectangle using mouse"""
        # Use attributes of grid at template_grid_index for new grid
        if self.template_grid_index >= self.number_grids:
            self.template_grid_index = 0
        grid = self[self.template_grid_index]

        tile_width = grid.tile_width_d()
        tile_height = grid.tile_height_d()

        origin_sx_sy = self.cs.convert_d_to_s((x + tile_width / 2, y + tile_height / 2))

        # size[rows, cols]
        size = [int(np.ceil(h / tile_height)), int(np.ceil(w / tile_width))]

        # do not use rotation of previous grid!
        new_grid = self.add_new_grid(origin_sx_sy=origin_sx_sy, sw_sh=(w, h), active=grid.active,
                                      frame_size=grid.frame_size, frame_size_selector=grid.frame_size_selector,
                                      overlap=grid.overlap, pixel_size=grid.pixel_size,
                                      dwell_time=grid.dwell_time, dwell_time_selector=grid.dwell_time_selector,
                                      bit_depth_selector=grid.bit_depth_selector,
                                      rotation=0, row_shift=grid.row_shift,
                                      acq_interval=grid.acq_interval, acq_interval_offset=grid.acq_interval_offset,
                                      wd_stig_xy=grid.wd_stig_xy, use_wd_gradient=grid.use_wd_gradient,
                                      wd_gradient_ref_tiles=grid.wd_gradient_ref_tiles, wd_gradient_params=grid.wd_gradient_params,
                                      size=size)

    def tile_position_for_registration(self, grid_index, tile_index):
        """Provide tile location (upper left corner of tile) in nanometres.
        TODO: What is the best way to deal with grid rotations?
        """
        dx, dy = self.cs.convert_s_to_d(
            self[grid_index][tile_index].sx_sy)
        width_d = self[grid_index].width_d()
        height_d = self[grid_index].height_d()
        return int((dx - width_d/2) * 1000), int((dy - height_d/2) * 1000)

    def total_number_active_grids(self):
        """Return the total number of active grids."""
        sum_active_grids = 0
        for grid in self:
            if grid.active:
                sum_active_grids += 1
        return sum_active_grids

    def total_number_active_tiles(self):
        """Return total number of active tiles across all active grids."""
        sum_active_tiles = 0
        for grid in self:
            if grid.active:
                sum_active_tiles += grid.number_active_tiles()
        return sum_active_tiles

    def active_tile_key_list(self):
        tile_key_list = []
        for g in range(self.number_grids):
            for t in self[g].active_tiles:
                if self[g][t].tile_active:
                    tile_key_list.append(str(g) + '.' + str(t))
        return tile_key_list

    def grid_selector_list(self):
        return [grid.get_label(grid_index) for grid_index, grid in enumerate(self)]

    def max_acq_interval(self):
        """Return the maximum value of the acquisition interval across
        all grids."""
        acq_intervals = []
        for grid in self:
            acq_intervals.append(grid.acq_interval)
        return max(acq_intervals)

    def max_acq_interval_offset(self):
        """Return the maximum value of the acquisition interval offset
        across all grids."""
        acq_interval_offsets = []
        for grid in self:
            acq_interval_offsets.append(grid.acq_interval_offset)
        return max(acq_interval_offsets)

    def intervallic_acq_active(self):
        """Return True if intervallic acquisition is active for at least
        one active grid, otherwise return False."""
        for grid in self:
            if grid.acq_interval > 1 and grid.active:
                return True
        return False

    def wd_gradient_active(self, grid_index=-1):
        """Return True if wd gradient is active for specified grid, else False.
        If grid_index == -1, return True if wd gradient is active for any grid,
        else False."""
        if grid_index == -1:
            for grid in self:
                if grid.use_wd_gradient and grid.active:
                    return True
            return False
        else:
            return (self[grid_index].use_wd_gradient
                    and self[grid_index].active)

    def save_tile_positions_to_disk(self, base_dir, timestamp):
        """Save the current grid setup in a text file in the logs folder.
        This assumes that base directory and logs subdirectory have already
        been created.
        """
        file_name = os.path.join(
            base_dir, 'meta', 'logs', 'tilepos_' + timestamp + '.txt')
        with open(file_name, 'w') as grid_map_file:
            for g in range(self.number_grids):
                for t in range(self[g].number_tiles):
                    grid_map_file.write(
                        str(g) + '.' + str(t) + ';' +
                        str(self[g][t].px_py[0]) + ';' +
                        str(self[g][t].px_py[1]) + '\n')
        return file_name

    def delete_all_autofocus_ref_tiles(self):
        self._autofocus_ref_tiles = []
        for g in range(self.number_grids):
            for t in range(self[g].number_tiles):
                self[g][t].autofocus_active = False

    @property
    def autofocus_ref_tiles(self):
        """Return updated list of autofocus_ref_tiles."""
        self._autofocus_ref_tiles = []
        for g in range(self.number_grids):
            for t in range(self[g].number_tiles):
                if self[g][t].autofocus_active:
                    self._autofocus_ref_tiles.append(str(g) + '.' + str(t))
        return self._autofocus_ref_tiles

    @autofocus_ref_tiles.setter
    def autofocus_ref_tiles(self, new_ref_tiles):
        """Set new autofocus reference tiles and update entries in Tile
        objects."""
        self.delete_all_autofocus_ref_tiles()
        self._autofocus_ref_tiles = new_ref_tiles
        for tile_key in self._autofocus_ref_tiles:
            g, t = (int(s) for s in tile_key.split('.'))
            self[g][t].autofocus_active = True

    def make_all_active_tiles_autofocus_ref_tiles(self):
        self.delete_all_autofocus_ref_tiles()
        for g in range(self.number_grids):
            for t in self[g].active_tiles:
                self._autofocus_ref_tiles.append(str(g) + '.' + str(t))
                self[g][t].autofocus_active = True

    def deactivate_grid(self, grid_index):
        """Deactivate grid with grid_index."""
        self[grid_index].active = False

    def activate_grid(self, grid_index):
        """Activate grid with grid_index."""
        self[grid_index].active = True

# ----------------------------- Array functions ---------------------------------

    @property
    def array_mode(self):
        return self.array_data.active

    def array_read(self, path):
        self.array_data.read_data(path)

    # deprecated: save grids instead
    def array_write(self):
        #self.array_data.write_data(self)
        pass

    def array_reset(self):
        self.array_data.reset()

    def set_template_grids(self):
        grid = self[self.number_grids - 1]
        nrois = self.array_data.get_nrois()
        for roi_index in range(nrois):
            new_grid = self.add_new_grid(origin_sx_sy=grid.origin_sx_sy, sw_sh=grid.sw_sh, size=grid.size,
                                         rotation=grid.rotation, active=False,
                                         frame_size=grid.frame_size, frame_size_selector=grid.frame_size_selector,
                                         overlap=grid.overlap, pixel_size=grid.pixel_size,
                                         dwell_time=grid.dwell_time, dwell_time_selector=grid.dwell_time_selector,
                                         bit_depth_selector=grid.bit_depth_selector,
                                         row_shift=grid.row_shift,
                                         acq_interval=grid.acq_interval, acq_interval_offset=grid.acq_interval_offset,
                                         wd_stig_xy=grid.wd_stig_xy, use_wd_gradient=grid.use_wd_gradient,
                                         wd_gradient_ref_tiles=grid.wd_gradient_ref_tiles,
                                         wd_gradient_params=grid.wd_gradient_params)

            new_grid.array_index = None
            new_grid.roi_index = roi_index
            new_grid.auto_update_tile_positions = True
            new_grid.set_array_display_colour()

    def array_update_data_image_properties(self, imported_image):
        image_center = np.multiply(imported_image.size, imported_image.image_pixel_size / 1e3 / 2)
        transform1 = utils.create_transform(translate=-image_center)
        if imported_image.flipped:
            transform2 = utils.create_transform(scale=[1, -1])
        else:
            transform2 = utils.create_transform(scale=[1, 1])
        transform3 = utils.create_transform(angle=-imported_image.rotation,
                                           translate=imported_image.centre_sx_sy,
                                           scale=imported_image.scale)
        transform = utils.combine_transforms([transform1, transform2, transform3])
        self.array_data.transform = transform

        for landmark_id, landmark in self.get_array_landmarks().items():
            # apply image transformation to landmarks
            location = utils.apply_transform(landmark, transform)
            self.set_array_landmark(landmark_id, location, landmark_type='stage')
            self.set_array_landmark(landmark_id, location, landmark_type='target')

    def add_new_grid_from_overview_roi(self, array_index, roi_index, roi_center, size, ov_position):
        # rescale roi_center and size to the SEM coordinate system
        roi_center = [roi_center[0] / self.cs.scale_x, roi_center[1] / self.cs.scale_y]
        size = [size[0] / self.cs.scale_x, size[1] / self.cs.scale_y]
        
        # convert the roi_center to stage coordinates and add the ov_position offset
        roi_stage_coords = self.cs.convert_d_to_s(roi_center) + ov_position

        grid_index = self.find_grid_index(roi_index, array_index)
        if grid_index is None:
            # add new grid if it doesn't already exist
            self.add_new_grid_from_roi(array_index, roi_index, roi_stage_coords, size, 0)
        else:
            # otherwise, update the grid attributes
            self.update_grid_from_roi(grid_index, roi_stage_coords, size, 0)

    def update_grid_tiles_with_mask(self, array_index, roi_index, mask):
        grid_index = self.find_grid_index(roi_index, array_index)
        if grid_index is None:
            return

        grid = self[grid_index]
        overlap_um = grid.overlap * grid.pixel_size * 1e-3
        
        # get the size of the ROI (not the grid size)
        w, h = grid.sw_sh
        mask = np.asarray(mask, dtype=np.uint8)

        # pad mask to match tile size
        px_size_y = mask.shape[0] / h
        px_size_x = mask.shape[1] / w
        
        # actual grid size is the number of tiles in the grid minus the overlap
        grid_height = grid.tile_height_d() * grid.size[0] - overlap_um * (grid.size[0] - 1)
        grid_width = grid.tile_width_d() * grid.size[1] - overlap_um * (grid.size[1] - 1)

        # pad the mask to match the grid size
        dh = (grid_height - h) / 2
        dw = (grid_width - w) / 2
        mask = np.pad(mask, ((round(dh * px_size_y), round(dh * px_size_y)),
                        (round(dw * px_size_x), round(dw * px_size_x))))

        # reshape mask to match tiles in grid
        mask = utils.resize_image_max_pool(mask, (grid.size[1], grid.size[0]))
        grid.activate_tiles_from_mask(mask)

    def array_create_grids(self, imported_image):
        sem_stage_flipped = self.cs.get_sem_stage_flipped()
        self.delete_array_grids(keep_template_grids=True)
        for array_index, rois in self.array_data.get_rois().items():
            for roi_index, roi in rois.items():
                center, size, rotation = (
                    self.array_data.get_roi_stage_properties(roi, imported_image, sem_stage_flipped))
                self.add_new_grid_from_roi(array_index, roi_index, center, size, rotation)
                # add focus points to grid
                grid_index = self.number_grids - 1
                for point in self.array_data.get_focus_points_in_roi(array_index, roi):
                    self.array_add_autofocus_point(
                        grid_index,
                        point['location'])

    def array_update_grids(self, imported_image):
        # compute new grid locations
        # (always transform from reference source)
        sem_stage_flipped = self.cs.get_sem_stage_flipped()
        for array_index, rois in self.array_data.get_rois().items():
            for roi_index, roi in rois.items():
                grid = self.find_roi_grid(array_index, roi_index)
                if grid:
                    center, _, rotation = (
                        self.array_data.get_roi_stage_properties(roi, imported_image, sem_stage_flipped))
                    grid.auto_update_tile_positions = False
                    grid.rotation = rotation
                    grid.update_tile_positions()
                    grid.auto_update_tile_positions = True
                    grid.centre_sx_sy = center

    def update_grid_from_roi(self, grid_index, center, size, rotation):
        grid = self[grid_index]
        overlap_um = grid.overlap * grid.pixel_size * 1e-3
        # effective tile size is equivalent to tile size minus overlap
        tile_width = grid.tile_width_d() - overlap_um
        tile_height = grid.tile_height_d() - overlap_um
        w, h = size
        tiles = [int(np.ceil(h / tile_height)), int(np.ceil(w / tile_width))]
        grid.size = tiles
        grid.rotation = rotation
        grid.auto_update_tile_positions = True
        grid.centre_sx_sy = center
        grid.sw_sh = size

    def add_new_grid_from_roi(self, array_index, roi_index, center, size, rotation):
        # use first matching roi grid as template
        template_index = self.find_grid_index(roi_index)
        if template_index is None:
            template_index = 0

        grid = self[template_index]
        overlap_um = grid.overlap * grid.pixel_size * 1e-3

        # effective tile size is equivalent to tile size minus overlap
        tile_width = grid.tile_width_d() - overlap_um
        tile_height = grid.tile_height_d() - overlap_um

        w, h = size
        tiles = [int(np.ceil(h / tile_height)), int(np.ceil(w / tile_width))]

        new_grid = self.add_new_grid(origin_sx_sy=center, sw_sh=size, size=tiles, rotation=rotation,
                                     frame_size=grid.frame_size, frame_size_selector=grid.frame_size_selector,
                                     overlap=grid.overlap, pixel_size=grid.pixel_size,
                                     dwell_time=grid.dwell_time, dwell_time_selector=grid.dwell_time_selector,
                                     bit_depth_selector=grid.bit_depth_selector,
                                     row_shift=grid.row_shift,
                                     acq_interval=grid.acq_interval, acq_interval_offset=grid.acq_interval_offset,
                                     wd_stig_xy=grid.wd_stig_xy, use_wd_gradient=grid.use_wd_gradient,
                                     wd_gradient_ref_tiles=grid.wd_gradient_ref_tiles,
                                     wd_gradient_params=grid.wd_gradient_params)

        new_grid.array_index = array_index
        new_grid.roi_index = roi_index
        new_grid.set_array_display_colour()
        # centre must be finally set after updating tile positions
        new_grid.auto_update_tile_positions = True
        new_grid.centre_sx_sy = center
        return new_grid

    def array_landmark_calibration(self):
        array_data = self.array_data
        source_landmarks = array_data.get_landmarks(landmark_type='source').values()
        target_landmarks = array_data.get_landmarks(landmark_type='target').values()
        array_data.transform = utils.create_point_transform(source_landmarks, target_landmarks)

    def find_grid_index(self, roi_index, array_index=None):
        # leave array_index None for template grids
        for index, grid in enumerate(self):
            if grid.roi_index == roi_index and grid.array_index == array_index:
                return index
        return None

    def find_roi_grid(self, array_index, roi_index):
        for grid in self:
            if grid.array_index == array_index and grid.roi_index == roi_index:
                return grid
        return None

    def get_array_landmarks(self, landmark_type='source'):
        return self.array_data.get_landmarks(landmark_type)

    def set_array_landmark(self, landmark_id, location, landmark_type='target'):
        self.array_data.set_landmark(landmark_id, location, landmark_type)

    def array_autofocus_points(self, grid_index):
        """The magc_autofocus_points_source are in non-rotated grid coordinates
        without wafer transform.
        This function calculates the af_points according to current
        grid location and rotation in stage coordinates"""

        return self.array_convert_to_current_grid(
            grid_index,
            self[grid_index].array_autofocus_points_source)

    def array_convert_to_current_grid(self, grid_index, input_points):
        if len(input_points) == 0:
            return []
        grid = self[grid_index]
        transformed_points = []
        scale_factor = (
            ArrayData.get_affine_scaling(self.array_data.transform.T)
            if self.array_data.calibrated
            else 1
        )
        grid_center_c = np.dot(grid.centre_sx_sy, [1, 1j])
        for point in input_points:
            point_c = np.dot(point, [1, 1j])
            transformed_point_c = (
                grid_center_c
                + (
                    point_c
                    * scale_factor
                    * np.exp(1j * np.radians(grid.rotation))
                )
            )
            transformed_points.append([
                np.real(transformed_point_c),
                np.imag(transformed_point_c),
            ])
        return transformed_points

    def array_convert_to_source(self, grid_index, input_points):
        """
        Converts coordinates of points back to non-rotated, non-wafer-transformed cooordinates
        If the wafer is calibrated (i.e. self.array['transform'] has been applied),
        then the distance to the center of the grid must be scaled according to the transform
        """
        grid = self[grid_index]
        transformed_points = []

        scale_factor = (
            1 / float(ArrayData.get_affine_scaling(self.array_data.transform.T))
            if self.array_data.calibrated
            else 1
        )
        # _c indicates complex number
        grid_center_c = np.dot(
            grid.centre_sx_sy,
            [1, 1j],
        )
        for point in input_points:
            point_c = np.dot(point, [1, 1j])
            transformed_point_c = (
                (point_c - grid_center_c)
                * np.exp(1j * np.radians(-grid.rotation))
                * scale_factor
            )
            transformed_points.append([
                np.real(transformed_point_c),
                np.imag(transformed_point_c),
            ])
        return transformed_points

    def array_add_autofocus_point(self, grid_index, input_af_point):
        """input_af_point is in stage coordinates of
        the translated, rotated grid.
        This function transforms input_af_point to
        the coordinates relative to a non-translated, non-rotated grid
        in source pixel coordinates (LM wafer image)"""

        transformed_af_point = self.array_convert_to_source(
            grid_index,
            [input_af_point])[0]

        self[grid_index].array_autofocus_points_source.append(
            transformed_af_point)

    def array_delete_last_autofocus_point(self, grid_index):
        if len(self[grid_index].array_autofocus_points_source) > 0:
            del self[grid_index].array_autofocus_points_source[-1]
        # magc_utils.write_magc(self)

    def array_delete_autofocus_points(self, grid_index):
        self[grid_index].array_autofocus_points_source = []
        # magc_utils.write_magc(self)

    def array_propagate_source_grid_to_target_grid(
        self,
        source_grid_index,
        target_grid_indices,
        imported_image
    ):
        sem_stage_flipped = self.cs.get_sem_stage_flipped()
        source_grid = self[source_grid_index]
        roi_index = source_grid.roi_index
        source = self.array_data.get_roi(source_grid.array_index, roi_index)

        _, _, source_rotation = (
            self.array_data.get_roi_stage_properties(source, imported_image, sem_stage_flipped))

        source_section_center = np.array(source['center']) - np.array(imported_image.origin)
        source_section_angle = source['angle'] % 360

        source_grid_center = utils.apply_transform(source_grid.centre_sx_sy, np.linalg.inv(self.array_data.transform))

        source_section_grid = source_grid_center - source_section_center
        source_section_grid_distance = np.linalg.norm(source_section_grid)
        source_section_grid_angle = np.angle(complex(*source_section_grid), deg=True)

        for target_grid_index in target_grid_indices:
            target_grid = self[target_grid_index]

            if target_grid.roi_index == roi_index and source_grid_index != target_grid_index:
                target = self.array_data.get_roi(target_grid.array_index, roi_index)
                if target is not None:

                    _, _, target_rotation = (
                        self.array_data.get_roi_stage_properties(target, imported_image, sem_stage_flipped))

                    target_section_center = np.array(target['center']) - np.array(imported_image.origin)
                    target_section_angle = target['angle'] % 360

                    # set all parameters in target grid
                    target_grid_rotation = (source_grid.rotation - source_rotation + target_rotation) % 360

                    target_grid.rotation = target_grid_rotation
                    target_grid.size = source_grid.size
                    target_grid.overlap = source_grid.overlap
                    target_grid.row_shift = source_grid.row_shift
                    target_grid.active_tiles = source_grid.active_tiles
                    target_grid.frame_size_selector = source_grid.frame_size_selector
                    target_grid.pixel_size = source_grid.pixel_size
                    target_grid.dwell_time_selector = source_grid.dwell_time_selector
                    target_grid.acq_interval = source_grid.acq_interval

                    target_grid.acq_interval_offset = source_grid.acq_interval_offset
                    target_grid.autofocus_ref_tiles = source_grid.autofocus_ref_tiles
                    target_grid.array_autofocus_points_source = copy.deepcopy(
                        source_grid.array_autofocus_points_source)
                    # xxx self.set_adaptive_focus_enabled(t, self.get_adaptive_focus_enabled(s))
                    # xxx self.set_adaptive_focus_tiles(t, self.get_adaptive_focus_tiles(s))
                    # xxx self.set_adaptive_focus_gradient(t, self.get_adaptive_focus_gradient(s))

                    target_section_grid_angle = source_section_grid_angle + source_section_angle - target_section_angle

                    target_grid_center_complex = (
                        complex(*target_section_center)
                        + source_section_grid_distance
                        * cmath.rect(1, np.radians(target_section_grid_angle)))
                    target_grid_center = (
                        np.real(target_grid_center_complex),
                        np.imag(target_grid_center_complex))

                    target_grid_center = utils.apply_transform(target_grid_center, self.array_data.transform)

                    target_grid.update_tile_positions()
                    target_grid.centre_sx_sy = target_grid_center

    def array_revert_grid(self, grid_index, imported_image):
        grid = self[grid_index]
        roi_index = grid.roi_index
        source = self.array_data.get_roi(grid.array_index, roi_index)
        center, size, rotation = (
            self.array_data.get_roi_stage_properties(source, imported_image, self.cs.get_sem_stage_flipped()))

        grid.centre_sx_sy = center
        grid.rotation = rotation

    def array_activate_grids(self, roi_index):
        for grid in self:
            if grid.roi_index == roi_index:
                grid.active = True

    def array_deactivate_grids(self, roi_index):
        for grid in self:
            if grid.roi_index == roi_index:
                grid.active = False

# ------------------------- End of Array functions ------------------------------
