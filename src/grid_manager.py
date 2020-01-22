# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2019 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module manages the grids. It holds all the grid parameters and provides
   getter and setter access to other modules, adds and deletes grids,
   calculates position and focus maps.
"""

import os
import json
import utils
import yaml
import numpy as np
from statistics import mean
from math import sqrt, radians, sin, cos


class Tile:
    # Keep as class or as dict in class grid?

    def __init__(self, px_py=[0, 0], dx_dy=[0, 0], sx_sy=[0, 0],
                 wd=0, stig_xy=[0, 0], tile_active=False,
                 af_ref_tile=False, grad_ref_tile=False):
        # Relative pixel coordinates, unrotated: Upper left (origin) tile: 0, 0
        self.px_py = px_py
        # Actual SEM coordinates (distances as shown in SEM images)
        self.dx_dy = dx_dy
        # Stage coordinates in microns. The stage calibration parameters are
        # needed to calculated these coordinates.
        self.sx_sy = sx_sy
        # wd: working distance in m
        self.wd = wd
        # stig_xy: stigmation parameters in %
        self.stig_xy = stig_xy
        self.tile_active = tile_active
        self.af_ref_tile = af_ref_tile
        self.grad_ref_tile = grad_ref_tile

class Grid:

    def __init__(self, origin_sx_sy=[0, 0], rotation=0, size=[5, 5],
                 overlap=200, row_shift=0, grid_active=True, active_tiles=[],
                 tile_size_px_py=[4096, 3072], tile_size_selector=4,
                 pixel_size=10.0, dwell_time=0.8, dwell_time_selector=4,
                 display_colour=0, acq_interval=1, acq_interval_offset=0,
                 use_wd_gradient=True, wd_gradient_tiles=[-1, -1, -1],
                 wd_gradient_params=[0, 0, 0]):
        # The origin of the grid is the stage position of tile 0.
        self.origin_sx_sy = origin_sx_sy
        self.rotation = rotation
        self.size = size
        self.number_tiles = self.size[0] * self.size[1]
        self.overlap = overlap
        self.row_shift = row_shift
        self.grid_active = grid_active
        self.active_tiles = active_tiles
        self.tile_size_px_py = tile_size_px_py
        self.tile_size_selector = tile_size_selector
        self.pixel_size = pixel_size
        self.dwell_time = dwell_time
        self.dwell_time_selector = dwell_time_selector
        self.display_colour = display_colour
        self.acq_interval = acq_interval
        self.acq_interval_offset = acq_interval_offset
        self.use_wd_gradient = use_wd_gradient
        self.wd_gradient_tiles = wd_gradient_tiles
        self.wd_gradient_params = wd_gradient_params
        self.initialize_tiles()
        # Calculate pixel and SEM coordinates
        self.calculate_tile_positions()
        # Set active tiles and wd_gradient_tiles
        for tile_number in self.active_tiles:
            self.tiles[tile_number].tile_active = True
        for tile_number in self.wd_gradient_tiles:
            # Unselected gradient tiles are set to -1, therefore check if >= 0
            if tile_number >= 0:
                self.tiles[tile_number].grad_ref_tile = True

    def __getitem__(self, index):
        """Return the Tile object selected by index."""
        if index < self.number_tiles:
            return self.tiles[index]
        else:
            return None

    def __setitem__(self, index, item):
        if index < self.number_tiles:
            self.tiles[index] = item

    def initialize_tiles(self):
        # Create list of tile objects
        self.tiles = [Tile() for i in range(self.number_tiles)]

    def calculate_tile_positions(self):
        # Calculate tile positions in pixel coordinates (unrotated), and in
        # SEM coordinates taking into account rotation. This method is called
        # when a new grid is created or an existing grid is changed.
        rows, cols = self.size
        width_p, height_p = self.tile_size_px_py
        theta = radians(self.rotation)

        for y_pos in range(rows):
            for x_pos in range(cols):
                tile_number = x_pos + y_pos * cols
                x_coord = x_pos * (width_p - self.overlap)
                y_coord = y_pos * (height_p - self.overlap)
                # Introduce alternating shift in x direction
                # to avoid quadruple beam exposure:
                x_shift = self.row_shift * (y_pos % 2)
                x_coord += x_shift
                # Save position (non-rotated)
                self.tiles[tile_number].px_py = [x_coord, y_coord]
                if theta > 0:
                    # Rotate coordinates
                    x_coord_rot = x_coord * cos(theta) - y_coord * sin(theta)
                    y_coord_rot = x_coord * sin(theta) + y_coord * cos(theta)
                    x_coord, y_coord = x_coord_rot, y_coord_rot
                # Save SEM coordinates in microns (includes rotation)
                self.tiles[tile_number].dx_dy = [
                    x_coord * self.pixel_size / 1000,
                    y_coord * self.pixel_size / 1000]

    def get_grid_map_p(self):
        return [self.tiles[t].px_py for t in range(self.number_tiles)]

    def get_grid_map_d(self):
        return [self.tiles[t].dx_dy for t in range(self.number_tiles)]

    def set_wd(self, wd):
        for tile in self.tiles:
            tile.wd = wd

    def average_wd(self):
        wd_list = []
        for tile in self.tiles:
            if tile.wd > 0:
                wd_list.append(tile.wd)
        if wd_list:
            return mean(wd_list)
        else:
            return None

    def set_stig_xy(self, stig_xy):
        for tile in self.tiles:
            tile.stig_xy = stig_xy

    def average_stig_xy(self):
        stig_x_list = []
        stig_y_list = []
        for tile in self.tiles:
            if tile.wd > 0:
                # A working distance of 0 means that focus parameters have
                # not been set for this tile and it can be disregarded.
                stig_x_list.append(tile.stig_xy[0])
                stig_y_list.append(tile.stig_xy[1])
        if stig_x_list:
            return mean(stig_x_list), mean(stig_y_list)
        else:
            return None, None

    def distance_between_tiles(self, tile_number1, tile_number2):
        """Compute the distance between two tile centres in microns."""
        dx1, dy1 = self.tiles[tile_number1].dx_dy
        dx2, dy2 = self.tiles[tile_number2].dx_dy
        return sqrt((dx1 - dx2)**2 + (dy1 - dy2)**2)


class GridManager:

    def __init__(self, config, sem, coordinate_system):
        self.cfg = config
        self.sem = sem
        self.cs = coordinate_system
        # Load grid parameters stored in configuration.
        self.number_grids = int(self.cfg['grids']['number_grids'])
        origin_sx_sy = json.loads(self.cfg['grids']['origin_sx_sy'])
        rotation = json.loads(self.cfg['grids']['rotation'])
        size = json.loads(self.cfg['grids']['size'])
        overlap = json.loads(self.cfg['grids']['overlap'])
        row_shift = json.loads(self.cfg['grids']['row_shift'])
        grid_active = json.loads(self.cfg['grids']['grid_active'])
        active_tiles = json.loads(self.cfg['grids']['active_tiles'])
        tile_size_px_py = json.loads(self.cfg['grids']['tile_size_px_py'])
        tile_size_selector = json.loads(
            self.cfg['grids']['tile_size_selector'])
        pixel_size = json.loads(self.cfg['grids']['pixel_size'])
        dwell_time = json.loads(self.cfg['grids']['dwell_time'])
        dwell_time_selector = json.loads(
            self.cfg['grids']['dwell_time_selector'])
        display_colour = json.loads(self.cfg['grids']['display_colour'])
        origin_wd = json.loads(self.cfg['grids']['origin_wd'])
        acq_interval = json.loads(self.cfg['grids']['acq_interval'])
        acq_interval_offset = json.loads(
            self.cfg['grids']['acq_interval_offset'])
        use_wd_gradient = json.loads(
            self.cfg['grids']['use_adaptive_focus'])
        wd_gradient_tiles = json.loads(
            self.cfg['grids']['adaptive_focus_tiles'])
        wd_gradient_params = json.loads(
            self.cfg['grids']['adaptive_focus_gradient'])

        # Create a list of grid objects
        self.__grids = []
        for i in range(self.number_grids):
            grid = Grid(origin_sx_sy[i], rotation[i], size[i], overlap[i],
                        row_shift[i], grid_active[i]==1, active_tiles[i],
                        tile_size_px_py[i], tile_size_selector[i],
                        pixel_size[i], dwell_time[i], dwell_time_selector[i],
                        display_colour[i], acq_interval[i],
                        acq_interval_offset[i], use_wd_gradient[i]==1,
                        wd_gradient_tiles[i], wd_gradient_params[i])
            self.__grids.append(grid)


    def save_to_cfg(self):
        """Save current grid configuration to ConfigParser object self.cfg."""
        self.cfg['grids']['number_grids'] = str(self.number_grids)

        origin_sx_sy = []
        rotation = []
        size = []
        overlap = []
        row_shift = []
        grid_active = []
        active_tiles = []
        tile_size_px_py = []
        tile_size_selector = []
        pixel_size = []
        dwell_time = []
        dwell_time_selector = []
        display_colour = []
        origin_wd = []
        acq_interval = []
        acq_interval_offset = []
        wd_gradient_tiles = []
        wd_gradient_params = []
        use_wd_gradient = []

        for grid in self.__grids:
            origin_sx_sy.append(grid.origin_sx_sy)
            rotation.append(grid.rotation)
            size.append(grid.size)
            overlap.append(grid.overlap)
            row_shift.append(grid.row_shift)
            grid_active.append(int(grid.grid_active))
            active_tiles.append(grid.active_tiles)
            tile_size_px_py.append(grid.tile_size_px_py)
            tile_size_selector.append(grid.tile_size_selector)
            pixel_size.append(grid.pixel_size)
            dwell_time.append(grid.dwell_time)
            dwell_time_selector.append(grid.dwell_time_selector)
            display_colour.append(grid.display_colour)
            # origin_wd.append(grid.origin_wd)
            origin_wd.append(0)
            acq_interval.append(grid.acq_interval)
            acq_interval_offset.append(grid.acq_interval_offset)
            use_wd_gradient.append(int(grid.use_wd_gradient))
            wd_gradient_tiles.append(grid.wd_gradient_tiles)
            wd_gradient_params.append(grid.wd_gradient_params)


        self.cfg['grids']['origin_sx_sy'] = str(origin_sx_sy)
        self.cfg['grids']['rotation'] = str(rotation)
        self.cfg['grids']['size'] = str(size)
        self.cfg['grids']['overlap'] = str(overlap)
        self.cfg['grids']['row_shift'] = str(row_shift)
        self.cfg['grids']['grid_active'] = str(grid_active)
        self.cfg['grids']['active_tiles'] = str(active_tiles)
        self.cfg['grids']['tile_size_px_py'] = str(tile_size_px_py)
        self.cfg['grids']['tile_size_selector'] = str(tile_size_selector)
        self.cfg['grids']['pixel_size'] = str(pixel_size)
        self.cfg['grids']['dwell_time'] = str(dwell_time)
        self.cfg['grids']['dwell_time_selector'] = str(dwell_time_selector)
        self.cfg['grids']['display_colour'] = str(display_colour)
        self.cfg['grids']['origin_wd'] = str(origin_wd)
        self.cfg['grids']['acq_interval'] = str(acq_interval)
        self.cfg['grids']['acq_interval_offset'] = str(acq_interval_offset)
        self.cfg['grids']['use_adaptive_focus'] = str(use_wd_gradient)
        self.cfg['grids']['adaptive_focus_tiles'] = str(wd_gradient_tiles)
        self.cfg['grids']['adaptive_focus_gradient'] = str(
            wd_gradient_params)

        # Save the working distances and stigmation parameters of those tiles
        # that are active and/or selected for the autofocus and/or the
        # working distance gradient.
        wd_stig_dict = {}
        for g in range(self.number_grids):
            for t in range(self.__grids[g].number_tiles):
                tile_key = str(g) + '.' + str(t)
                if (self.__grids[g][t].wd > 0
                    and (self.__grids[g][t].tile_active
                         or self.__grids[g][t].af_ref_tile
                         or self.__grids[g][t].grad_ref_tile)):
                    # Only save tiles with WD != 0 which are active or
                    # selected for autofocus or wd gradient.
                    wd_stig_dict[tile_key] = [
                        round(self.__grids[g][t].wd, 9),  # WD
                        round(self.__grids[g][t].stig_xy[0], 6),  # Stig X
                        round(self.__grids[g][t].stig_xy[1], 6)   # Stig Y
                    ]
        # Save as JSON string in config:
        self.cfg['grids']['wd_stig_params'] = json.dumps(wd_stig_dict)

    def add_new_grid(self):
        new_grid_number = self.number_grids
        # Position new grid next to the previous grid
        x_pos, y_pos = self.get_grid_origin_s(new_grid_number - 1)
        y_pos += 50
        # Set tile size and overlap according to store resolutions available
        if len(self.sem.STORE_RES) > 4:
            tile_size_px_py = [4096, 3072]
            tile_size_selector = 4
            overlap = 200
        else:
            tile_size_px_py = [3072, 2304]
            tile_size_selector = 3
            overlap = 150
        # Set grid colour
        if self.cfg['sys']['magc_mode'].lower() != 'true':
            # Cycle through available colours
            display_colour = new_grid_number % 10
        else: # use green by default in magc_mode
            display_colour = 1

        new_grid = Grid(origin_sx_sy=[x_pos, y_pos], rotation=0, size=[5, 5],
                        overlap=overlap, row_shift=0, grid_active=True,
                        active_tiles=[], tile_size_px_py=tile_size_px_py,
                        tile_size_selector=tile_size_selector, pixel_size=10.0,
                        dwell_time=0.8, dwell_tile_selector=4,
                        display_colour=display_colour, acq_interval=1,
                        acq_interval_offset=0, use_wd_gradient=False,
                        wd_gradient_tiles=[-1, -1, -1],
                        wd_gradient_params=[0, 0, 0])
        self.__grids.append(new_grid)
        self.number_grids += 1

    def delete_grid(self):
        self.number_grids -= 1
        del self.__grids[-1]

    def get_number_grids(self):
        return self.number_grids

    def get_grid_origin_s(self, grid_number):
        return self.__grids[grid_number].origin_sx_sy

    def get_grid_origin_d(self, grid_number):
        return self.cs.convert_to_d(self.__grids[grid_number].origin_sx_sy)

    def get_grid_origin_p(self, grid_number):
        dx, dy = self.get_grid_origin_d(grid_number)
        # Divide by pixel size to get pixel coordinates
        return (int(dx * 1000 / self.cs.CS_PIXEL_SIZE),
                int(dy * 1000 / self.cs.CS_PIXEL_SIZE))

    def set_grid_origin_s(self, grid_number, s_coordinates):
        """Set the origin of the grid in stage coordinates."""
        self.__grids[grid_number].origin_sx_sy = list(s_coordinates)

    def add_grid_origin_s(self, grid_number, s_coordinates):
        # Adds the grid origin's stage coordinates to the
        # coordinates given as parameter:
        diff_x, diff_y = s_coordinates
        origin_x, origin_y = self.get_grid_origin_s(grid_number)
        return (origin_x + diff_x, origin_y + diff_y)

    def set_grid_centre_s(self, grid_number, new_centre):
        new_x, new_y = new_centre
        old_x, old_y = self.get_grid_centre_s(grid_number)
        print('Old grid centre: ', old_x, old_y)
        origin_x, origin_y = self.get_grid_origin_s(grid_number)
        print('Old grid origin: ', origin_x, origin_y)

        self.set_grid_origin_s(grid_number,
            [origin_x + new_x - old_x, origin_y + new_y - old_y])

    def get_grid_centre_s(self, grid_number):
        return self.cs.convert_to_s(self.get_grid_centre_d(grid_number))

    def get_grid_centre_d(self, grid_number):
        """Return the SEM coordinates of the centre of the specified grid."""
        width_d, height_d = self.get_grid_size_dx_dy(grid_number)
        origin_dx, origin_dy = self.get_grid_origin_d(grid_number)
        tile_width_d = self.get_tile_width_d(grid_number)
        tile_height_d = self.get_tile_height_d(grid_number)
        # Calculate centre coordinates of unrotated grid
        centre_dx = origin_dx - tile_width_d / 2 + width_d / 2
        centre_dy = origin_dy - tile_height_d / 2 + height_d / 2
        theta = radians(self.get_rotation(grid_number))
        if theta > 0:
            # Rotate the centre (with origin as pivot)
            centre_dx -= origin_dx
            centre_dy -= origin_dy
            centre_dx_rot = centre_dx * cos(theta) - centre_dy * sin(theta)
            centre_dy_rot = centre_dx * sin(theta) + centre_dy * cos(theta)
            centre_dx = centre_dx_rot + origin_dx
            centre_dy = centre_dy_rot + origin_dy
        return centre_dx, centre_dy

    def rotate_around_grid_centre(self, grid_number, centre_dx, centre_dy):
        """Update the grid origin after rotating the grid around the
        grid centre by the specified rotation angle."""
        # Calculate origin of the unrotated grid:
        width_d, height_d = self.get_grid_size_dx_dy(grid_number)
        tile_width_d = self.get_tile_width_d(grid_number)
        tile_height_d = self.get_tile_height_d(grid_number)
        origin_dx = centre_dx - width_d / 2 + tile_width_d / 2
        origin_dy = centre_dy - height_d / 2 + tile_height_d / 2
        # Rotate grid origin around grid centre:
        theta = radians(self.get_rotation(grid_number))
        if theta > 0:
            origin_dx -= centre_dx
            origin_dy -= centre_dy
            origin_dx_rot = origin_dx * cos(theta) - origin_dy * sin(theta)
            origin_dy_rot = origin_dx * sin(theta) + origin_dy * cos(theta)
            origin_dx = origin_dx_rot + centre_dx
            origin_dy = origin_dy_rot + centre_dy
        # Update grid with the new origin:
        self.set_grid_origin_s(
            grid_number, self.cs.convert_to_s((origin_dx, origin_dy)))

    def update_tile_positions(self, grid_number):
        """Calculate new tile positions after grid has been
        modified, rotated."""
        self.__grids[grid_number].calculate_tile_positions()

    def get_grid_size(self, grid_number):
        return self.__grids[grid_number].size

    def get_grid_size_px_py(self, grid_number):
        cols = self.__grids[grid_number].size[1]
        width = (cols * self.__grids[grid_number].tile_size_px_py[0]
                 - (cols - 1) * self.__grids[grid_number].overlap
                 + self.__grids[grid_number].row_shift)
        rows = self.__grids[grid_number].size[0]
        height = (rows * self.__grids[grid_number].tile_size_px_py[1]
                 - (rows - 1) * self.__grids[grid_number].overlap)
        return width, height

    def get_grid_size_dx_dy(self, grid_number):
        width_p, height_p = self.get_grid_size_px_py(grid_number)
        width_d = width_p * self.__grids[grid_number].pixel_size / 1000
        height_d = height_p * self.__grids[grid_number].pixel_size / 1000
        return width_d, height_d

    def set_grid_size(self, grid_number, new_size):
        """Change the size (rows, cols) of the specified grid. Preserve
        current pattern of actives tiles and tile parameters when grid
        is extended."""
        if grid_number < self.number_grids:
            if self.__grids[grid_number].size != list(new_size):
                old_rows, old_cols = self.__grids[grid_number].size
                old_number_tiles = old_rows * old_cols
                new_rows, new_cols = new_size
                new_number_tiles = new_rows * new_cols
                self.__grids[grid_number].size = list(new_size)
                self.__grids[grid_number].number_tiles = new_number_tiles
                # Save old tile objects
                old_tiles = self.__grids[grid_number].tiles
                # Initialize new tile list
                self.__grids[grid_number].initialize_tiles()
                new_active_tiles = []
                new_wd_gradient_tiles = []
                # Preserve locations of active tiles and settings
                for t in range(old_number_tiles):
                    # Calculate coordinate in grid of old size:
                    x_pos = t % old_cols
                    y_pos = t // old_cols
                    # Calculate tile number in new grid:
                    if (x_pos < new_cols) and (y_pos < new_rows):
                        new_t = x_pos + y_pos * new_cols
                        # Use tile from previous grid at the new position
                        self.__grids[grid_number][new_t] = old_tiles[t]
                        if self.__grids[grid_number][new_t].tile_active:
                            new_active_tiles.append(new_t)
                        if self.__grids[grid_number][new_t].grad_ref_tile:
                            new_wd_gradient_tiles.append(new_t)
                self.__grids[grid_number].active_tiles = new_active_tiles
                self.__grids[grid_number].wd_gradient_tiles = (
                    new_wd_gradient_tiles)

    def get_number_rows(self, grid_number):
        return self.__grids[grid_number].size[0]

    def get_number_cols(self, grid_number):
        return self.__grids[grid_number].size[1]

    def get_number_tiles(self, grid_number):
        return self.__grids[grid_number].number_tiles

    def get_rotation(self, grid_number):
        return self.__grids[grid_number].rotation

    def set_rotation(self, grid_number, rotation):
        if grid_number < self.number_grids:
            self.__grids[grid_number].rotation = rotation

    def get_display_colour(self, grid_number):
        return utils.COLOUR_SELECTOR[self.__grids[grid_number].display_colour]

    def get_display_colour_index(self, grid_number):
        return self.__grids[grid_number].display_colour

    def set_display_colour(self, grid_number, colour):
        if grid_number < self.number_grids:
            self.__grids[grid_number].display_colour = colour

    def get_overlap(self, grid_number):
        return self.__grids[grid_number].overlap

    def set_overlap(self, grid_number, overlap):
        if grid_number < self.number_grids:
            self.__grids[grid_number].overlap = overlap

    def get_row_shift(self, grid_number):
        return self.__grids[grid_number].row_shift

    def set_row_shift(self, grid_number, row_shift):
        if grid_number < self.number_grids:
            self.__grids[grid_number].row_shift = row_shift

    def get_tile_size_px_py(self, grid_number):
        return self.__grids[grid_number].tile_size_px_py

    def get_tile_size_selector(self, grid_number):
        return self.__grids[grid_number].tile_size_selector

    def set_tile_size_selector(self, grid_number, selector):
        if grid_number < self.number_grids:
            self.__grids[grid_number].tile_size_selector = selector
            # Update explicit storage of frame size:
            if selector < len(self.sem.STORE_RES):
                self.__grids[grid_number].tile_size_px_py = (
                    self.sem.STORE_RES[selector])

    def get_tile_width_p(self, grid_number):
        return self.__grids[grid_number].tile_size_px_py[0]

    def get_tile_height_p(self, grid_number):
        return self.__grids[grid_number].tile_size_px_py[1]

    def get_tile_width_d(self, grid_number):
        return (self.__grids[grid_number].tile_size_px_py[0]
                * self.__grids[grid_number].pixel_size / 1000)

    def get_tile_height_d(self, grid_number):
        return (self.__grids[grid_number].tile_size_px_py[1]
                * self.__grids[grid_number].pixel_size / 1000)

    def set_tile_size_px_py(self, grid_number, tile_size_px_py):
        if grid_number < self.number_grids:
            self.__grids[grid_number].tile_size_px_py = tile_size_px_py

    def get_tile_position_d(self, grid_number, tile_number):
        return tuple(self.__grids[grid_number][tile_number].dx_dy)

    def get_grid_map_p(self, grid_number):
        return self.__grids[grid_number].get_grid_map_p()

    def get_grid_map_d(self, grid_number):
        return self.__grids[grid_number].get_grid_map_d()

    def get_pixel_size(self, grid_number):
        return self.__grids[grid_number].pixel_size

    def set_pixel_size(self, grid_number, pixel_size):
        if grid_number < self.number_grids:
            self.__grids[grid_number].pixel_size = pixel_size

    def get_dwell_time(self, grid_number):
        return self.__grids[grid_number].dwell_time

    def set_dwell_time(self, grid_number, dwell_time):
        if grid_number < self.number_grids:
            self.__grids[grid_number].dwell_time = dwell_time

    def get_dwell_time_selector(self, grid_number):
        return self.__grids[grid_number].dwell_time_selector

    def set_dwell_time_selector(self, grid_number, selector):
        if grid_number < self.number_grids:
            self.__grids[grid_number].dwell_time_selector = selector
            # Update explict storage of dwell times
            if selector < len(self.sem.DWELL_TIME):
                self.__grids[grid_number].dwell_time = (
                    self.sem.DWELL_TIME[selector])

    def get_tile_wd(self, grid_number, tile_number):
        return self.__grids[grid_number][tile_number].wd

    def set_tile_wd(self, grid_number, tile_number, wd):
        if grid_number < self.number_grids:
            self.__grids[grid_number][tile_number].wd = wd

    def adjust_tile_wd(self, grid_number, tile_number, delta):
        if grid_number < self.number_grids:
            self.__grids[grid_number][tile_number].wd += delta

    def get_average_grid_wd(self, grid_number):
        return self.__grids[grid_number].average_wd()

    def get_distance_between_tiles(self, grid, tile1, tile2):
        return self.__grids[grid_number].distance_between_tiles(tile1, tile2)

    def get_tile_stig_xy(self, grid_number, tile_number):
        return self.__grids[grid_number][tile_number].stig_xy

    def set_tile_stig_xy(self, grid_number, tile_number,
                         stig_x, stig_y):
        if grid_number < self.number_grids:
            self.__grids[grid_number][tile_number].stig_xy = [stig_x, stig_y]

    def adjust_tile_stig_xy(self, grid_number, tile_number,
                            delta_stig_x, delta_stig_y):
        if grid_number < self.number_grids:
            self.__grids[grid_number][tile_number].stig_xy[0] += delta_stig_x
            self.__grids[grid_number][tile_number].stig_xy[1] += delta_stig_y

    def get_average_grid_stig_xy(self, grid_number):
        return self.__grids[grid_number].average_stig_xy()

    def get_tile_stig_x(self, grid_number, tile_number):
        return self.__grids[grid_number][tile_number].stig_xy[0]

    def set_tile_stig_x(self, grid_number, tile_number, stig_x):
        if grid_number < self.number_grids:
            self.__grids[grid_number][tile_number].stig_xy[0] = stig_x

    def get_tile_stig_y(self, grid_number, tile_number):
        return self.__grids[grid_number][tile_number].stig_xy[1]

    def set_tile_stig_y(self, grid_number, tile_number, stig_y):
        if grid_number < self.number_grids:
            self.__grids[grid_number][tile_number].stig_xy[1] = stig_y

    def get_active_tiles(self, grid_number):
        if grid_number < self.number_grids:
            return self.__grids[grid_number].active_tiles

    def set_active_tiles(self, grid_number, active_tiles):
        if grid_number < self.number_grids:
            self.__grids[grid_number].active_tiles = active_tiles

    def get_active_tile_key_list(self):
        active_tile_key_list = []
        for grid_number in range(self.number_grids):
            for tile_number in self.get_active_tiles(grid_number):
                active_tile_key_list.append(
                    str(grid_number) + '.' + str(tile_number))
        return active_tile_key_list

    def get_number_active_tiles(self, grid_number):
        return len(self.__grids[grid_number].active_tiles)

    def get_total_number_active_tiles(self):
        # Count all active tiles across all grids:
        sum_active_tiles = 0
        for grid_number in range(self.number_grids):
            sum_active_tiles += self.__grids[grid_number].number_active_tiles
        return sum_active_tiles

    def get_active_tile_str_list(self, grid_number):
        return ['Tile %d' % t for t in self.__grids[grid_number].active_tiles]

    def get_tile_str_list(self, grid_number):
        return ['Tile %d' % t
                for t in range(self.__grids[grid_number].number_tiles)]

    def get_grid_str_list(self):
        return ['Grid %d' % g for g in range(self.number_grids)]

    def get_acq_interval(self, grid_number):
        return self.__grids[grid_number].acq_interval

    def get_max_acq_interval(self):
        acq_intervals = []
        for grid_number in range(self.number_grids):
            acq_intervals.append(self.__grids[grid_number].acq_interval)
        return max(acq_intervals)

    def set_acq_interval(self, grid_number, interval):
        if grid_number < self.number_grids:
           self.__grids[grid_number].acq_interval = interval

    def get_acq_interval_offset(self, grid_number):
        return self.__grids[grid_number].acq_interval_offset

    def get_max_acq_interval_offset(self):
        acq_interval_offsets = []
        for grid_number in range(self.number_grids):
            acq_interval_offsets.append(
                self.__grids[grid_number].acq_interval_offset)
        return max(acq_interval_offsets)

    def set_acq_interval_offset(self, grid_number, offset):
        if grid_number < self.number_grids:
            self.__grids[grid_number].acq_interval_offset = offset

    def is_intervallic_acq_active(self):
        for grid_number in range(self.number_grids):
            if self.__grids[grid_number].acq_interval > 1:
                return True
        return False

    def is_slice_active(self, grid_number, slice_counter):
        offset = self.__grids[grid_number].acq_interval_offset
        interval = self.__grids[grid_number].acq_interval
        if slice_counter >= offset:
            return (slice_counter - offset) % interval == 0
        return False

    def get_tile_cycle_time(self, grid_number):
        # Calculate cycle time from SmartSEM data:
        size_selector = self.__grids[grid_number].tile_size_selector
        scan_speed = self.sem.DWELL_TIME.index(
            self.__grids[grid_number].dwell_time)
        return (self.sem.CYCLE_TIME[size_selector][scan_speed] + 0.2)

    def get_adaptive_focus_tiles(self, grid_number):
        return self.__grids[grid_number].wd_gradient_tiles

    def set_adaptive_focus_tiles(self, grid_number, tiles):
        if grid_number < self.number_grids:
            self.__grids[grid_number].wd_gradient_tiles = tiles

    def is_adaptive_focus_tile(self, grid_number, tile_number):
        return (tile_number in self.__grids[grid_number].wd_gradient_tiles)

    def get_adaptive_focus_gradient(self, grid_number):
        return self.__grids[grid_number].wd_gradient

    def set_adaptive_focus_gradient(self, grid_number, gradient):
        if grid_number < self.number_grids:
            self.__grids[grid_number].wd_gradient = gradient

    def is_adaptive_focus_active(self, grid_number=-1):
        if grid_number == -1:
            for grid_number in range(self.number_grids):
                if self.__grids[grid_number].use_wd_gradient:
                    return True
            return False
        else:
            return self.__grids[grid_number].use_wd_gradient

    def set_adaptive_focus_enabled(self, grid_number, status_enabled):
        if grid_number < self.number_grids:
            self.__grids[grid_number].use_wd_gradient = status_enabled

    def get_af_tile_str_list(self, grid_number):
        str_list = []
        for tile in self.__grids[grid_number].wd_gradient_tiles:
            if tile >= 0:
                str_list.append('Tile %d' % tile)
            else:
                str_list.append('No tile selected')
        return str_list

    def set_stig_for_grid(self, grid_number, stig_x, stig_y):
        """Set all tiles to specified stig_xy."""
        self.__grids[grid_number].set_stig_xy([stig_x, stig_y])

    def set_initial_wd_stig_for_grid(self, grid_number, wd, stig_x, stig_y):
        """Set all tiles that are uninitialized to specified working
        distance and stig_xy."""
        for tile_number in range(self.__grids[grid_number].number_tiles):
            if self.__grids[grid_number][tile_number].wd == 0:
                self.__grids[grid_number][tile_number].wd = wd
                self.__grids[grid_number][tile_number].stig_xy = [stig_x, stig_y]

    def calculate_focus_gradient(self, grid_number):
        # TODO: rewrite this
        success = True
        af_tiles = self.af_tiles[grid_number]
        if af_tiles[0] >= 0:
            row_length = self.size[grid_number][1]
            row0 = af_tiles[0] // row_length
            row1 = af_tiles[1] // row_length
            # Tile1 must be right of Tile0 and in the same row:
            if (af_tiles[1] > af_tiles[0]) and (row0 == row1):
                x_diff = af_tiles[1] - af_tiles[0]
                wd_delta_x = (
                    self.grid_map_wd_stig[grid_number][af_tiles[1]][0]
                    - self.grid_map_wd_stig[grid_number][af_tiles[0]][0])/x_diff
            else:
                success = False
            # Tile3 must be below Tile0 and in the same column:
            col0 = af_tiles[0] % row_length
            col2 = af_tiles[2] % row_length
            if (af_tiles[2] > af_tiles[0]) and (col0 == col2):
                y_diff = (af_tiles[2] - af_tiles[0]) // row_length
                wd_delta_y = (
                    self.grid_map_wd_stig[grid_number][af_tiles[2]][0]
                    - self.grid_map_wd_stig[grid_number][af_tiles[0]][0])/y_diff
            else:
                success = False

            if success:
                self.af_gradient[grid_number] = [
                    round(wd_delta_x, 12),
                    round(wd_delta_y, 12)]
                self.cfg['grids']['adaptive_focus_gradient'] = str(
                    self.af_gradient)
                # Calculate wd at the origin of the tiling:
                x_diff_origin = af_tiles[0] % row_length
                y_diff_origin = af_tiles[0] // row_length
                self.origin_wd[grid_number] = round(
                      self.grid_map_wd_stig[grid_number][af_tiles[0]][0]
                      - (x_diff_origin * wd_delta_x)
                      - (y_diff_origin * wd_delta_y), 9)
                self.cfg['grids']['origin_wd'] = str(self.origin_wd)

                # Update wd for full grid:
                for y_pos in range(0, self.size[grid_number][0]):
                    for x_pos in range(0, self.size[grid_number][1]):
                        tile_number = y_pos * row_length + x_pos
                        self.grid_map_wd_stig[grid_number][tile_number][0] = (
                                self.origin_wd[grid_number]
                                + x_pos * wd_delta_x
                                + y_pos * wd_delta_y)
        else:
            success = False
        return success

    def get_gapped_grid_map_p(self, grid_number):
        """Return unrotated grid map in pixel coordinates with gaps between
        the tiles. The gaps are 5% of tile width/height.
        """
        # TODO: rewrite
        gapped_tile_map = {}
        rows, cols = self.size[grid_number]
        width_p, height_p = self.tile_size_px_py[grid_number]
        for y_pos in range(rows):
            for x_pos in range(cols):
                tile_number = x_pos + y_pos * cols
                x_coord = 1.05 * x_pos * width_p
                y_coord = 1.05 * y_pos * height_p
                x_coord += self.row_shift[grid_number] * (y_pos % 2)
                # Format of gapped pixel grid map (always non-rotated):
                # 0: x-coordinate, 1: y-coordinate
                gapped_tile_map[tile_number] = [x_coord, y_coord]
        return gapped_tile_map

    def save_grid_setup(self, timestamp):
        """Save the current grid setup in a text file in the meta\logs folder.
        This assumes that base directory and logs subdirectory have already
        been created."""
        file_name = os.path.join(
            self.cfg['acq']['base_dir'],
            'meta', 'logs', 'gridmap_' + timestamp + '.txt')
        with open(file_name, 'w') as grid_map_file:
            for g in range(self.number_grids):
                for t in range(self.__grids[g].number_tiles):
                    grid_map_file.write(
                        str(g) + '.' + str(t) + ';' +
                        str(self.__grids[g][t].dx_dy[0]) + ';' +
                        str(self.__grids[g][t].dx_dy[1]) + ';' +
                        str(self.__grids[g][t].tile_active) + '\n')
        return file_name

    def load_wd_stig_params_from_config(self):
        wd_stig_dict = json.loads(self.cfg['grids']['wd_stig_params'])
        for tile_key in wd_stig_dict:
            g_str, t_str = tile_key.split('.')
            g, t = int(g_str), int(t_str)
            wd_stig_xy = wd_stig_dict[tile_key]
            self.__grids[g][t].wd = wd_stig_xy[0]
            self.__grids[g][t].stig_xy = [wd_stig_xy[1], wd_stig_xy[2]]

    def reset_wd_stig_params(self, grid_number):
        for tile in self.__grids[grid_number].tiles:
            if tile.wd > 0:
                tile.wd = 0
                tile.stig_xy = [0, 0]

    def sort_acq_order(self, grid_number):
        # Use snake pattern to minimize number of long motor moves:
        rows, cols = self.__grids[grid_number].size
        ordered_active_tiles = []

        for row_pos in range(rows):
            if (row_pos % 2 == 0):
                start_col, end_col, step = 0, cols, 1
            else:
                start_col, end_col, step = cols-1, -1, -1
            for col_pos in range(start_col, end_col, step):
                tile_number = row_pos * cols + col_pos
                if self.__grids[grid_number][tile_number].tile_active:
                    ordered_active_tiles.append(tile_number)

        self.__grids[grid_number].active_tiles = ordered_active_tiles

    def select_tile(self, grid_number, tile_number):
        self.__grids[grid_number][tile_number].tile_active = True
        self.__grids[grid_number].active_tiles.append(tile_number)
        self.sort_acq_order(grid_number)

    def deselect_tile(self, grid_number, tile_number):
        self.__grids[grid_number][tile_number].tile_active = False
        self.__grids[grid_number].active_tiles.remove(tile_number)
        self.sort_acq_order(grid_number)

    def toggle_tile(self, grid_number, tile_number):
        if self.__grids[grid_number][tile_number].tile_active:
            self.deselect_tile(grid_number, tile_number)
            text = ' deselected.'
        else:
            self.select_tile(grid_number, tile_number)
            text = ' selected.'
        return 'CTRL: Tile ' + str(grid_number) + '.' + str(tile_number) + text

    def get_tile_coordinates_relative_d(self, grid_number, tile_number):
        # Tile position in SEM coordinates relative to grid origin:
        return self.__grids[grid_number][tile_number].dx_dy

    def get_tile_coordinates_d(self, grid_number, tile_number):
        """Provide location of tile centre in SEM coordinates
        (units: microns)."""
        origin_dx, origin_dy = self.get_grid_origin_d(grid_number)
        dx, dy = self.get_tile_coordinates_relative_d(grid_number, tile_number)
        return origin_dx + dx, origin_dy + dy

    def get_tile_coordinates_relative_p(self, grid_number, tile_number):
        # Tile position in SEM pixel coordinates relative to grid origin:
        return self.__grids[grid_number][tile_number].px_py

    def get_tile_coordinates_p(self, grid_number, tile_number):
        origin_px, origin_py = self.get_grid_origin_p(grid_number)
        px, py = self.get_tile_coordinates_relative_p
        return origin_px + px, origin_py + py

    def get_tile_coordinates_for_registration(self, grid_number, tile_number):
        """Provide tile location (upper left corner of tile) in nanometres.
        """
        dx, dy = self.get_tile_coordinates_d(grid_number, tile_number)
        width_d = self.get_tile_width_d(grid_number)
        height_d = self.get_tile_height_d(grid_number)
        return int((dx - width_d/2) * 1000), int((dy - height_d/2) * 1000)

    def get_tile_coordinates_s(self, grid_number, tile_number):
        # TODO
        sx_sy = self.cs.convert_to_s(
            tuple(self.__grids[grid_number][tile_number].dx_dy))
        return self.add_grid_origin_s(grid_number, sx_sy)

    def reset_active_tiles(self, grid_number):
        for tile_number in range(self.__grids[grid_number].number_tiles):
            self.__grids[grid_number][tile_number].tile_active = False
        self.__grids[grid_number].active_tiles = []

    def select_all_tiles(self, grid_number):
        self.__grids[grid_number].active_tiles = []
        for tile_number in range(self.__grids[grid_number].number_tiles):
            self.__grids[grid_number].active_tiles.append(tile_number)
            self.__grids[grid_number][tile_number].tile_active = True
        self.sort_acq_order(grid_number)

    def get_tile_bounding_box(self, grid_number, tile_number):
        grid_origin_dx, grid_origin_dy = self.get_grid_origin_d(grid_number)
        grid_map_d = self.__grids[grid_number].get_grid_map_d()
        tile_width_d = self.get_tile_width_d(grid_number)
        tile_height_d = self.get_tile_height_d(grid_number)
        # Calculate bounding box (unrotated):
        top_left_dx = (grid_origin_dx
            + grid_map_d[tile_number][0] - tile_width_d/2)
        top_left_dy = (grid_origin_dy
            + grid_map_d[tile_number][1] - tile_height_d/2)
        points_x = [top_left_dx, top_left_dx + tile_width_d,
                    top_left_dx, top_left_dx + tile_width_d]
        points_y = [top_left_dy, top_left_dy,
                    top_left_dy + tile_height_d, top_left_dy + tile_height_d]
        theta = radians(self.get_rotation(grid_number))
        if theta > 0:
            pivot_dx = top_left_dx + tile_width_d/2
            pivot_dy = top_left_dy + tile_height_d/2
            for i in range(4):
                points_x[i] -= pivot_dx
                points_y[i] -= pivot_dy
                x_rot = points_x[i] * cos(theta) - points_y[i] * sin(theta)
                y_rot = points_x[i] * sin(theta) + points_y[i] * cos(theta)
                points_x[i] = x_rot + pivot_dx
                points_y[i] = y_rot + pivot_dy
        # Find the maximum and minimum x and y coordinates:
        max_dx, min_dx = max(points_x), min(points_x)
        max_dy, min_dy = max(points_y), min(points_y)

        return min_dx, max_dx, min_dy, max_dy

    def get_adaptive_focus_enabled(self, grid_number):
        return self.af_active[grid_number]

# ----------------------------- MagC functions ---------------------------------

    def propagate_source_grid_to_target_grid(self, source_grid_number,
        target_grid_number, sections):
        s = source_grid_number
        t = target_grid_number
        if s == t:
            return

        sourceSectionCenter = np.array(sections[s]['center'])
        targetSectionCenter = np.array(sections[t]['center'])

        sourceSectionAngle = sections[s]['angle'] % 360
        targetSectionAngle = sections[t]['angle'] % 360

        sourceGridRotation = self.get_rotation(s)

        sourceGridCenter = np.array(self.get_grid_centre_s(s))

        if self.cfg['magc']['wafer_calibrated'] == 'True':
            # transform back the grid coordinates in non-transformed coordinates
            waferTransform = np.array(
                json.loads(self.cfg['magc']['wafer_transform']))
            # inefficient but ok for now:
            waferTransformInverse = utils.invertAffineT(waferTransform)
            result = utils.applyAffineT(
                [sourceGridCenter[0]], [sourceGridCenter[1]],
                waferTransformInverse)
            sourceGridCenter = [result[0][0], result[1][0]]

        sourceSectionGrid = sourceGridCenter - sourceSectionCenter
        sourceSectionGridDistance = np.linalg.norm(sourceSectionGrid)
        sourceSectionGridAngle = np.angle(
            np.dot(sourceSectionGrid, [1, 1j]), deg=True)

        new_grid_rotation = (((180-targetSectionAngle + sourceGridRotation -
                             (180-sourceSectionAngle))) % 360)
        self.set_rotation(t, new_grid_rotation)

        self.set_grid_size(t, self.get_grid_size(s))
        self.set_overlap(t, self.get_overlap(s))
        self.set_row_shift(t, self.get_row_shift(s))
        self.set_number_active_tiles(t, self.get_number_active_tiles(s))
        self.set_active_tiles(t, self.get_active_tiles(s))
        if len(self.sem.STORE_RES) > 4:
            # Merlin
            self.set_tile_size_px_py(t, self.get_tile_size_px_py(s))
            self.set_tile_size_selector(t, self.get_tile_size_selector(s))
        else:
            # Sigma
            self.set_tile_size_px_py(t, self.get_tile_size_px_py(s))
            self.set_tile_size_selector(t, self.get_tile_size_selector(s))
        self.set_pixel_size(t, self.get_pixel_size(s))
        self.set_dwell_time(t, self.get_dwell_time(s))
        self.set_dwell_time_selector(t, self.get_dwell_time_selector(s))
        self.set_acq_interval(t, self.get_acq_interval(s))
        self.set_acq_interval_offset(t, self.get_acq_interval_offset(s))
        self.set_adaptive_focus_enabled(t, self.get_adaptive_focus_enabled(s))
        self.set_adaptive_focus_tiles(t, self.get_adaptive_focus_tiles(s))
        self.set_adaptive_focus_gradient(t, self.get_adaptive_focus_gradient(s))

        ###############################################
        # --- setting the autofocus reference tiles ---
        ref_tile_list = json.loads(self.cfg['autofocus']['ref_tiles'])
        # get ref tiles from source
        source_ref_tiles = []
        for tile_key in ref_tile_list:
            grid, tile = tile_key.split('.')
            grid, tile = int(grid), int(tile)
            if grid == s:
                source_ref_tiles.append(tile)
        # remove ref tiles from target
        ref_tile_list = [key for key in ref_tile_list if
            int(key.split('.')[0]) != t]

        # add source ref tiles to target
        for source_ref_tile in source_ref_tiles:
            ref_tile_list.append(str(t) + '.' + str(source_ref_tile))

        # sort the tile list
        ref_tile_list.sort()

        # save the new tile list
        self.cfg['autofocus']['ref_tiles'] = json.dumps(ref_tile_list)

        ###############################################

        targetSectionGridAngle = (
            sourceSectionGridAngle + sourceSectionAngle - targetSectionAngle)

        targetGridCenterComplex = np.dot(targetSectionCenter, [1,1j]) \
            + sourceSectionGridDistance \
            * np.exp(1j * np.radians(targetSectionGridAngle))
        targetGridCenter = (
            np.real(targetGridCenterComplex), np.imag(targetGridCenterComplex))

        if self.cfg['magc']['wafer_calibrated'] == 'True':
            # transform the grid coordinates to wafer coordinates
            waferTransform = np.array(
                json.loads(self.cfg['magc']['wafer_transform']))
            result = utils.applyAffineT(
                [targetGridCenter[0]], [targetGridCenter[1]], waferTransform)
            targetGridCenter = [result[0][0], result[1][0]]

        self.set_grid_centre_s(t, targetGridCenter)
        self.update_tile_positions(t)

    def delete_all_but_last_grid(self):
        for grid_number in range(self.number_grids - 1):
            self.delete_grid()

    def update_source_ROIs_from_grids(self):
        if self.cfg['magc']['wafer_calibrated'] == 'True':
            waferTransform = np.array(json.loads(
                self.cfg['magc']['wafer_transform']))
            waferTransformInverse = utils.invertAffineT(waferTransform)
            transform_angle = -utils.getAffineRotation(waferTransform)

        sections_path = self.cfg['magc']['sections_path']
        with open(sections_path, 'r') as f:
            sections_yaml = yaml.full_load(f)
        sections_yaml['sourceROIsUpdatedFromSBEMimage'] = {}

        for grid_number in range(self.number_grids):
            target_ROI = self.get_grid_centre_s(grid_number)
            target_ROI_angle = self.get_rotation(grid_number)

            if self.cfg['magc']['wafer_calibrated'] == 'True':
                # transform back the grid coordinates
                # in non-transformed coordinates
                result = utils.applyAffineT(
                    [target_ROI[0]],
                    [target_ROI[1]],
                    waferTransformInverse)
                source_ROI = [result[0][0], result[1][0]]
                source_ROI_angle = (
                    (-90 + target_ROI_angle - transform_angle) % 360)
            else:
                source_ROI = target_ROI
                source_ROI_angle = (-90 + target_ROI_angle) % 360
            sections_yaml['sourceROIsUpdatedFromSBEMimage'][grid_number] = [
                float(source_ROI[0]),
                float(source_ROI[1]),
                float(source_ROI_angle)]

        with open(sections_path, 'w') as f:
            yaml.dump(sections_yaml,
                f,
                default_flow_style=False,
                sort_keys=False)

# ------------------------- End of MagC functions ------------------------------