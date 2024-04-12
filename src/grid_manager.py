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
import os

import numpy as np
from statistics import mean
from typing import List
from math import sqrt, radians, sin, cos
import scipy

import ArrayData
import constants
from image_io import imread
import utils



class Tile:
    """Store the positions of a tile, its working distance and stigmation
    parameters, and whether the tile is active and used as a reference tile.
    Note that the tile size and all acquisition parameters are set in
    class Grid because all tiles in a grid have the same size and
    acquisition parameters.
    """

    # TBD: Keep this class or include as dict in class Grid?
    # Or make this a dataclass (new in Python 3.7)?

    def __init__(self, px_py=(0, 0), dx_dy=(0, 0), sx_sy=(0, 0),
                 wd=0, stig_xy=(0, 0), tile_active=False,
                 autofocus_active=False, wd_grad_active=False):
        # Relative pixel (p) coordinates of the tile, unrotated grid:
        # Upper left (origin) tile: 0, 0
        self.px_py = np.array(px_py)
        # Relative SEM (d) coordinates (distances as shown in SEM images)
        # with grid rotation applied (if theta <> 0)
        self.dx_dy = np.array(dx_dy)
        # Absolute stage coordinates in microns. The stage calibration
        # parameters are needed to calculate these coordinates.
        self.sx_sy = np.array(sx_sy)
        # wd: working distance in m
        self.wd = wd
        # stig_xy: stigmation parameters in %
        self.stig_xy = stig_xy
        # The following booleans indicate whether the tile
        # is active (= will be acquired), and whether it is used as a
        # reference tile for the autofocus (af) and the focus gradient (grad).
        self.tile_active = tile_active
        self.autofocus_active = autofocus_active
        self.wd_grad_active = wd_grad_active
        self.preview_img = None

    @property
    def preview_src(self):
        return self._preview_src

    @preview_src.setter
    def preview_src(self, src):
        self._preview_src = src
        if os.path.isfile(src):
            try:
                self.preview_img = utils.image_to_QPixmap(imread(src))
            except:
                self.preview_img = None
        else:
            self.preview_img = None


class Grid(list):
    """Store all grid parameters and a list of Tile objects."""

    def __init__(self, coordinate_system, sem,
                 active=True, origin_sx_sy=(0, 0), sw_sh=(0, 0), rotation=0,
                 size=(5, 5), overlap=None, row_shift=0, active_tiles=None,
                 frame_size=None, frame_size_selector=None,
                 pixel_size=10.0, dwell_time=None, dwell_time_selector=None,
                 bit_depth_selector=0, display_colour=0,
                 acq_interval=1, acq_interval_offset=0,
                 wd_stig_xy=(0, 0, 0), use_wd_gradient=False,
                 wd_gradient_ref_tiles=None,
                 wd_gradient_params=None):
        super().__init__()
        self.cs = coordinate_system
        self.sem = sem
        if active_tiles is None:
            active_tiles = []
        if wd_gradient_ref_tiles is None:
            wd_gradient_ref_tiles = [-1, -1, -1]
        if wd_gradient_params is None:
            wd_gradient_params = [0, 0, 0]
        # If auto_update_tile_positions is True, every change to an attribute
        # that influences the tile positions (for example, rotation or overlap)
        # will automatically update the tile positions (default behaviour).
        # For the initialization of the grid here in __init__,
        # auto_update_tile_positions is first set to False to avoid repeated
        # tile position updates. After initialization is complete, it is set
        # to True.
        self.auto_update_tile_positions = False

        # The origin of the grid (origin_sx_sy) is the stage position of tile 0.
        self._origin_sx_sy = np.array(origin_sx_sy)
        self._origin_dx_dy = self.cs.convert_s_to_d(origin_sx_sy)
        # Size of the grid: [rows, cols]
        self._size = size
        self.number_tiles = self.size[0] * self.size[1]
        self.sw_sh = sw_sh
        # Rotation in degrees
        self.rotation = rotation
        # Every other row of tiles is shifted by row_shift (number of pixels)
        self.row_shift = row_shift
        # The boolean active indicates whether the grid will be acquired
        # or skipped.
        self.active = active

        # Use device-dependent default for frame size if no frame size selector specified
        if frame_size_selector is None:
            frame_size_selector = self.sem.STORE_RES_DEFAULT_INDEX_TILE

        self.frame_size = frame_size
        # Setting the frame_size_selector will automatically update the frame
        # size unless the selector is -1.
        self.frame_size_selector = frame_size_selector

        # Overlap between neighbouring tiles in pixels.
        # If not specified, use 5% of the image width, rounded to 10px
        if overlap is None:
            overlap = round(0.05 * self.frame_size[0], -1)

        self.overlap = overlap

        # Use device-dependent default for dwell time if no dwell time selector specified
        if dwell_time_selector is None:
            dwell_time_selector = self.sem.DWELL_TIME_DEFAULT_INDEX

        # Dwell time in microseconds (float)
        self.dwell_time = dwell_time
        self.dwell_time_selector = dwell_time_selector

        # Bit depth selector: 0: 8 bit (default); 1: 16 bit
        self.bit_depth_selector = bit_depth_selector

        # Pixel size in nm (float)
        self.pixel_size = pixel_size

        # Colour of the grid in the Viewport. See utils.COLOUR_SELECTOR
        self.display_colour = display_colour
        self.acq_interval = acq_interval
        self.acq_interval_offset = acq_interval_offset
        self.wd_stig_xy = list(wd_stig_xy)
        self.use_wd_gradient = use_wd_gradient
        self.initialize_tiles()
        self.update_tile_positions()
        # Restore default for updating tile positions
        self.auto_update_tile_positions = True
        # active_tiles: a list of tile numbers that are active in this grid
        self.active_tiles = active_tiles
        # Set wd_gradient_ref_tiles, which will set the bool flags in
        # self
        self.wd_gradient_ref_tiles = wd_gradient_ref_tiles
        self.wd_gradient_params = wd_gradient_params

        #----- Array variables -----#
        # used in Array: these autofocus locations are defined relative to the
        # center of the non-rotated grid.
        self.array_autofocus_points_source = []
        self.array_index = None
        self.roi_index = None
        #--------------------------#

    def get_label(self, grid_index):
        if self.roi_index is not None:
            label = 'ROI '
            if self.array_index is not None:
                label += f'{self.array_index}.'
            label += f'{self.roi_index}'
        else:
            label = f'GRID {grid_index}'
        return label

    def initialize_tiles(self):
        """Create list of tile objects with default parameters."""
        self.clear()
        self.extend([Tile() for _ in range(self.number_tiles)])

    def update_tile_positions(self):
        """Calculate tile positions relative to the grid origin in pixel
        coordinates (unrotated), in SEM coordinates taking into account
        rotation, and absolute stage positions. This method must be called
        when a new grid is created or an existing grid is changed in order
        to update the coordinates.
        """
        rows, cols = self.size
        width_p, height_p = self.frame_size[0], self.frame_size[1]
        theta = radians(self.rotation)

        for y_pos in range(rows):
            for x_pos in range(cols):
                tile_index = x_pos + y_pos * cols
                x_coord = x_pos * (width_p - self.overlap)
                y_coord = y_pos * (height_p - self.overlap)
                # Introduce alternating shift in x direction
                # to avoid quadruple beam exposure:
                x_shift = self.row_shift * (y_pos % 2)
                x_coord += x_shift
                # Save position (non-rotated)
                self[tile_index].px_py = np.array([x_coord, y_coord])
                if theta != 0:
                    # Rotate coordinates
                    x_coord_rot = x_coord * cos(theta) - y_coord * sin(theta)
                    y_coord_rot = x_coord * sin(theta) + y_coord * cos(theta)
                    x_coord, y_coord = x_coord_rot, y_coord_rot
                # Save SEM coordinates in microns (include rotation)
                self[tile_index].dx_dy = np.array([
                    x_coord * self.pixel_size / 1000,
                    y_coord * self.pixel_size / 1000])

        # Now calculate absolute stage positions.
        for tile in self:
            tile.sx_sy = self.cs.convert_d_to_s(tile.dx_dy) + self.origin_sx_sy

    def calculate_wd_gradient(self):
        """Calculate the working distance gradient for this grid using
        the three reference tiles. At the moment, this method requires
        that the three reference tiles form a right-angled triangle. This
        could be made more flexible.
        """
        success = True
        ref_tiles = self.wd_gradient_ref_tiles
        if ref_tiles[0] >= 0:
            row_length = self.size[1]
            row0 = ref_tiles[0] // row_length
            row1 = ref_tiles[1] // row_length
            # Tile1 must be right of Tile0 and in the same row:
            if (ref_tiles[1] > ref_tiles[0]) and (row0 == row1):
                x_diff = ref_tiles[1] - ref_tiles[0]
                slope_x = (self[ref_tiles[0]].wd
                           - self[ref_tiles[1]].wd)/x_diff
            else:
                success = False
            # Tile3 must be below Tile0 and in the same column:
            col0 = ref_tiles[0] % row_length
            col2 = ref_tiles[2] % row_length
            if (ref_tiles[2] > ref_tiles[0]) and (col0 == col2):
                y_diff = (ref_tiles[2] - ref_tiles[0]) // row_length
                slope_y = (self[ref_tiles[0]].wd
                           - self[ref_tiles[2]].wd)/y_diff
            else:
                success = False

            if success:
                self.wd_gradient_params[1] = round(slope_x, 12)
                self.wd_gradient_params[2] = round(slope_y, 12)
                # Calculate wd at the origin of the grid:
                x_diff_origin = ref_tiles[0] % row_length
                y_diff_origin = ref_tiles[0] // row_length
                wd_at_origin = round(
                    self[ref_tiles[0]].wd
                    - (x_diff_origin * slope_x)
                    - (y_diff_origin * slope_y), 9)
                self.wd_gradient_params[0] = wd_at_origin

                # Update wd for full grid:
                for y_pos in range(self.size[0]):
                    for x_pos in range(self.size[1]):
                        tile_index = y_pos * row_length + x_pos
                        self[tile_index].wd = (
                            wd_at_origin
                            + x_pos * slope_x
                            + y_pos * slope_y)
        else:
            success = False
        return success

    @property
    def origin_sx_sy(self):
        return self._origin_sx_sy

    @origin_sx_sy.setter
    def origin_sx_sy(self, sx_sy):
        self._origin_sx_sy = np.array(sx_sy)
        self._origin_dx_dy = self.cs.convert_s_to_d(sx_sy)
        if self.auto_update_tile_positions:
            self.update_tile_positions()

    @property
    def origin_dx_dy(self):
        return self._origin_dx_dy

    @origin_dx_dy.setter
    def origin_dx_dy(self, dx_dy):
        self._origin_dx_dy = np.array(dx_dy)
        self._origin_sx_sy = self.cs.convert_d_to_s(dx_dy)
        if self.auto_update_tile_positions:
            self.update_tile_positions()

    @property
    def centre_sx_sy(self) -> np.ndarray:
        """Calculate the centre coordinates of the grid as the midpoint
        between the origin (= first tile) and last tile of the grid."""
        return (self._origin_sx_sy + self[-1].sx_sy) / 2

    @centre_sx_sy.setter
    def centre_sx_sy(self, sx_sy: np.ndarray):
        self.origin_sx_sy = self._origin_sx_sy + sx_sy - self.centre_sx_sy

    @property
    def centre_dx_dy(self):
        return self.cs.convert_s_to_d(self.centre_sx_sy)

    @property
    def rotation(self):
        return self._rotation

    @rotation.setter
    def rotation(self, new_rotation):
        self._rotation = new_rotation
        if self.auto_update_tile_positions:
            self.update_tile_positions()

    def rotate_around_grid_centre(self, centre_dx, centre_dy):
        """Update the grid origin after rotating the grid around the
        grid centre by the current rotation angle.
        """
        # Calculate origin of the unrotated grid:
        origin_dx = centre_dx - self.width_d() / 2 + self.tile_width_d() / 2
        origin_dy = centre_dy - self.height_d() / 2 + self.tile_height_d() / 2
        # Rotate grid origin around grid centre:
        theta = radians(self.rotation)
        if theta != 0:
            origin_dx -= centre_dx
            origin_dy -= centre_dy
            origin_dx_rot = origin_dx * cos(theta) - origin_dy * sin(theta)
            origin_dy_rot = origin_dx * sin(theta) + origin_dy * cos(theta)
            origin_dx = origin_dx_rot + centre_dx
            origin_dy = origin_dy_rot + centre_dy
        # Update grid with the new origin:
        self.origin_sx_sy = self.cs.convert_d_to_s((origin_dx, origin_dy))

    def tile_positions_p(self) -> List[np.ndarray]:
        """Return list of relative pixel positions of all tiles in the grid."""
        return [self[t].px_py for t in range(self.number_tiles)]

    def gapped_tile_positions_p(self):
        """Return unrotated tile positions in pixel coordinates with gaps
        between the tiles. The gaps are 5% of tile width/height.
        """
        gapped_tile_positions = {}
        rows, cols = self.size
        width_p, height_p = self.frame_size
        for y_pos in range(rows):
            for x_pos in range(cols):
                tile_index = x_pos + y_pos * cols
                x_coord = 1.05 * x_pos * width_p
                y_coord = 1.05 * y_pos * height_p
                x_coord += self.row_shift * (y_pos % 2)
                gapped_tile_positions[tile_index] = [x_coord, y_coord]
        return gapped_tile_positions

    @property
    def size(self):
        return self._size

    @size.setter
    def size(self, new_size):
        """Change the size (rows, cols) of the specified grid. Preserve
        current pattern of actives tiles and tile parameters when grid
        is extended.
        """
        if self._size != list(new_size):
            old_rows, old_cols = self._size
            old_number_tiles = old_rows * old_cols
            new_rows, new_cols = new_size
            new_number_tiles = new_rows * new_cols
            self._size = list(new_size)
            self.number_tiles = new_number_tiles
            # Save old tile objects
            old_tiles = self.copy()
            # Initialize new tile list
            self.initialize_tiles()
            new_active_tiles = []
            new_wd_gradient_ref_tiles = []
            # Preserve locations of active tiles and settings
            for t in range(old_number_tiles):
                # Calculate coordinate in grid of old size:
                x_pos = t % old_cols
                y_pos = t // old_cols
                # Calculate tile number in new grid:
                if (x_pos < new_cols) and (y_pos < new_rows):
                    new_t = x_pos + y_pos * new_cols
                    # Use tile from previous grid at the new position
                    self[new_t] = old_tiles[t]
                    if self[new_t].tile_active:
                        new_active_tiles.append(new_t)
                    if self[new_t].wd_grad_active:
                        new_wd_gradient_ref_tiles.append(new_t)
            self.active_tiles = new_active_tiles
            self.wd_gradient_ref_tiles = (
                new_wd_gradient_ref_tiles)
            if self.auto_update_tile_positions:
                self.update_tile_positions()

    def width_p(self):
        """Return width of the grid in pixels."""
        columns = self.size[1]
        return (columns * self.frame_size[0] - (columns - 1) * self.overlap
                + self.row_shift)

    def height_p(self):
        """Return height of the grid in pixels."""
        rows = self.size[0]
        return rows * self.frame_size[1] - (rows - 1) * self.overlap

    def width_d(self):
        """Return width of the grid in micrometres."""
        return self.width_p() * self.pixel_size / 1000

    def height_d(self):
        """Return height of the grid in micrometres."""
        return self.height_p() * self.pixel_size / 1000

    def number_rows(self):
        return self.size[0]

    def number_cols(self):
        return self.size[1]

    @property
    def overlap(self):
        return self._overlap

    @overlap.setter
    def overlap(self, new_overlap):
        self._overlap = new_overlap
        if self.auto_update_tile_positions:
            self.update_tile_positions()

    @property
    def row_shift(self):
        return self._row_shift

    @row_shift.setter
    def row_shift(self, new_row_shift):
        self._row_shift = new_row_shift
        if self.auto_update_tile_positions:
            self.update_tile_positions()

    def display_colour_rgb(self):
        return constants.COLOUR_SELECTOR[self.display_colour]

    def set_display_colour(self, colour):
        self.display_colour = colour

    # Note: At the moment, all supported SEMs use a frame size selector that
    # determines the frame size. Changing the frame size selector automatically
    # updates the frame size (width, height), which is stored separately.
    # TODO: To support custom (individually settable) frame sizes, the frame
    # size selector can be set to -1 and SBEMimage would then use the stored
    # frame size.
    @property
    def frame_size_selector(self):
        return self._frame_size_selector

    @frame_size_selector.setter
    def frame_size_selector(self, selector):
        self._frame_size_selector = selector
        if selector == -1:
            return
        # Update explicit storage of frame size
        if selector is not None and selector < len(self.sem.STORE_RES):
            self.frame_size = self.sem.STORE_RES[selector]
        if self.auto_update_tile_positions:
            self.update_tile_positions()

    def tile_width_p(self):
        """Return tile width in pixels."""
        return self.frame_size[0]

    def tile_height_p(self):
        """Return tile height in pixels."""
        return self.frame_size[1]

    def tile_depth(self):
        """Return tile height in pixels."""
        return self.frame_size[2] if len(self.frame_size) > 2 else 1

    def tile_width_d(self):
        """Return tile width in microns."""
        return self.frame_size[0] * self.pixel_size / 1000

    def tile_height_d(self):
        """Return tile height in microns."""
        return self.frame_size[1] * self.pixel_size / 1000

    @property
    def pixel_size(self):
        return self._pixel_size

    @pixel_size.setter
    def pixel_size(self, new_pixel_size):
        self._pixel_size = new_pixel_size
        if self.auto_update_tile_positions:
            self.update_tile_positions()

    @property
    def dwell_time_selector(self):
        return self._dwell_time_selector

    @dwell_time_selector.setter
    def dwell_time_selector(self, selector):
        self._dwell_time_selector = selector
        # Update explict storage of dwell times
        if selector < len(self.sem.DWELL_TIME):
            self.dwell_time = self.sem.DWELL_TIME[selector]

    def number_active_tiles(self):
        return len(self.active_tiles)

    def active_tile_selector_list(self):
        return ['Tile %d' % t for t in self.active_tiles]

    def tile_selector_list(self):
        return ['Tile %d' % t for t in range(self.number_tiles)]

    @property
    def wd_gradient_ref_tiles(self):
        return self._wd_gradient_ref_tiles

    @wd_gradient_ref_tiles.setter
    def wd_gradient_ref_tiles(self, ref_tiles):
        if len(ref_tiles) != 3:
            self._wd_gradient_ref_tiles = [-1, -1, -1]
        else:
            for i in range(3):
                if ref_tiles[i] > self.number_tiles:
                    ref_tiles[i] = -1
            self._wd_gradient_ref_tiles = ref_tiles
            # Set bool flags for ref tiles
            for tile_index in range(self.number_tiles):
                self[tile_index].wd_grad_active = (
                    tile_index in ref_tiles)

    def wd_gradient_ref_tile_selector_list(self):
        selector_list = []
        for tile_index in self.wd_gradient_ref_tiles:
            if tile_index >= 0:
                selector_list.append('Tile %d' % tile_index)
            else:
                selector_list.append('No tile selected')
        return selector_list

    def slice_active(self, slice_counter):
        offset = self.acq_interval_offset
        if slice_counter >= offset:
            return (slice_counter - offset) % self.acq_interval == 0
        return False

    def set_wd_for_all_tiles(self, wd):
        """Set the same working distance for all tiles in the grid."""
        for tile in self:
            tile.wd = wd

    def set_wd_stig_xy_for_uninitialized_tiles(self, wd, stig_xy):
        """Set all tiles that are uninitialized to specified working
        distance and stig_xy."""
        for tile in self:
            if tile.wd == 0:
                tile.wd = wd
                tile.stig_xy = stig_xy

    def average_wd(self):
        """Return the average working distance of all tiles in the grid
        for which the working distance has been set."""
        wd_list = []
        for tile in self:
            # Tiles with wd == 0 are ignored.
            if tile.wd > 0:
                wd_list.append(tile.wd)
        if wd_list:
            return mean(wd_list)
        else:
            return None

    def average_wd_of_autofocus_ref_tiles(self):
        wd_list = []
        for tile in self:
            if tile.autofocus_active:
                wd_list.append(tile.wd)
        if wd_list:
            return mean(wd_list)
        else:
            return None

    def set_wd_stig_from_calibrated_points(self):
        """
        Interpolates the wd,stig values of the calibrated points
        and apply them to all tiles in the grid
        Used in magc_mode.
        """
        if not hasattr(self, "AFAS_results"):
            # no focus points were defined for that grid
            # or the autofocus/stig failed
            return
        wd_calibrated_points = np.array([
            [
                r[0][0],
                r[0][1],
                r[1][0],
            ]
            for r in self.AFAS_results
        ])
        stigx_calibrated_points = np.array([
            [
                r[0][0],
                r[0][1],
                r[1][1],
            ]
            for r in self.AFAS_results
        ])
        stigy_calibrated_points = np.array([
            [
                r[0][0],
                r[0][1],
                r[1][2],
            ]
            for r in self.AFAS_results
        ])
        xy_tiles = [tile.sx_sy for tile in self]
        wd_tiles, wd_outliers = ArrayData.focus_points_from_focused_points(
            wd_calibrated_points,
            xy_tiles,
        )
        if len(wd_outliers)>0:
            utils.log_warning(f"There are autofocus outliers: {wd_outliers}")
        stigx_tiles, stigx_outliers = ArrayData.focus_points_from_focused_points(
            stigx_calibrated_points,
            xy_tiles,
        )
        if len(stigx_outliers)>0:
            utils.log_warning(f"There are autostig_x outliers: {stigx_outliers}")
        stigy_tiles, stigy_outliers = ArrayData.focus_points_from_focused_points(
            stigy_calibrated_points,
            xy_tiles,
        )
        if len(stigy_outliers)>0:
            utils.log_warning(f"There are autostig_y outliers: {stigy_outliers}")

        for tile, wd, stigx, stigy in zip(
            self, wd_tiles, stigx_tiles, stigy_tiles
        ):
            tile.wd = wd[2]
            tile.stig_xy = stigx[2], stigy[2]

    def set_stig_xy_for_all_tiles(self, stig_xy):
        """Set the same stigmation parameters for all tiles in the grid."""
        for tile in self:
            tile.stig_xy = stig_xy

    def average_stig_xy(self):
        """Return the average stigmation parameters of all tiles in the grid
        for which these parameters have been set."""
        stig_x_list = []
        stig_y_list = []
        for tile in self:
            if tile.wd > 0:
                # A working distance of 0 means that focus parameters have
                # not been set for this tile and it can be disregarded.
                stig_x_list.append(tile.stig_xy[0])
                stig_y_list.append(tile.stig_xy[1])
        if stig_x_list:
            return mean(stig_x_list), mean(stig_y_list)
        else:
            return None, None

    def average_stig_xy_of_autofocus_ref_tiles(self):
        stig_x_list = []
        stig_y_list = []
        for tile in self:
            if tile.autofocus_active:
                stig_x, stig_y = tile.stig_xy
                stig_x_list.append(stig_x)
                stig_y_list.append(stig_y)
        if stig_x_list and stig_y_list:
            return [mean(stig_x_list), mean(stig_y_list)]
        else:
            return [None, None]

    def reset_wd_stig_xy(self):
        for tile in self:
            tile.wd = 0
            tile.stig_xy = 0

    def distance_between_tiles(self, tile_index1, tile_index2) -> float:
        """Compute the distance between two tile centres in microns."""
        dx1, dy1 = self[tile_index1].dx_dy
        dx2, dy2 = self[tile_index2].dx_dy
        return sqrt((dx1 - dx2)**2 + (dy1 - dy2)**2)

    @property
    def active_tiles(self):
        return self._active_tiles

    @active_tiles.setter
    def active_tiles(self, new_active_tiles):
        # Remove out-of-range active tiles
        self._active_tiles = [tile_index for tile_index in new_active_tiles
                              if tile_index < self.number_tiles]
        # Set boolean flags to True for active tiles, otherwise to False
        for tile_index in range(self.number_tiles):
            if tile_index in new_active_tiles:
                self[tile_index].tile_active = True
            else:
                self[tile_index].tile_active = False
        # Update tile acquisition order
        self.sort_tile_acq_order()

    def activate_tile(self, tile_index):
        """Set tile with tile_index to status 'active' (will be acquired)."""
        self[tile_index].tile_active = True
        self._active_tiles.append(tile_index)
        self.sort_tile_acq_order()

    def deactivate_tile(self, tile_index):
        """Set tile with tile_index to status 'inactive' (will not be
        acquired).
        """
        self[tile_index].tile_active = False
        self._active_tiles.remove(tile_index)
        self.sort_tile_acq_order()

    def toggle_active_tile(self, tile_index):
        """Toggle active/inactive status of tile with tile_index and return
        message for log."""
        if self[tile_index].tile_active:
            self.deactivate_tile(tile_index)
            return ' deactivated.'
        else:
            self.activate_tile(tile_index)
            return ' activated.'

    def deactivate_all_tiles(self):
        for tile in self:
            tile.tile_active = False
        self._active_tiles = []

    def activate_all_tiles(self):
        self.active_tiles = [t for t in range(self.number_tiles)]

    def sort_tile_acq_order(self):
        """Use snake pattern to minimize number of long motor moves.
        This could be optimized further."""
        rows, cols = self.size
        ordered_active_tiles = []
        for row_pos in range(rows):
            if row_pos % 2 == 0:
                start_col, end_col, step = 0, cols, 1
            else:
                start_col, end_col, step = cols-1, -1, -1
            for col_pos in range(start_col, end_col, step):
                tile_index = row_pos * cols + col_pos
                if self[tile_index].tile_active:
                    ordered_active_tiles.append(tile_index)
        self._active_tiles = ordered_active_tiles

    def tile_bounding_box(self, tile_index):
        """Return the bounding box of the specified tile in SEM coordinates."""
        grid_origin_dx, grid_origin_dy = self.origin_dx_dy
        tile_dx, tile_dy = self[tile_index].dx_dy
        tile_width_d = self.tile_width_d()
        tile_height_d = self.tile_height_d()
        # Calculate bounding box (unrotated):
        top_left_dx = grid_origin_dx + tile_dx - tile_width_d/2
        top_left_dy = grid_origin_dy + tile_dy - tile_height_d/2
        points_x = [top_left_dx, top_left_dx + tile_width_d,
                    top_left_dx, top_left_dx + tile_width_d]
        points_y = [top_left_dy, top_left_dy,
                    top_left_dy + tile_height_d, top_left_dy + tile_height_d]
        theta = radians(self.rotation)
        if theta != 0:
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

    def tile_cycle_time(self):
        """Calculate cycle time from SmartSEM data."""
        size_selector = self.frame_size_selector
        scan_speed = self.sem.DWELL_TIME.index(self.dwell_time)
        return self.sem.CYCLE_TIME[size_selector][scan_speed] + 0.2

    def autofocus_ref_tiles(self):
        """Return tile indices of autofocus ref tiles in this grid."""
        autofocus_ref_tiles = []
        for tile_index in range(self.number_tiles):
            if self[tile_index].autofocus_active:
                autofocus_ref_tiles.append(tile_index)
        return autofocus_ref_tiles

    def corner_tiles(self):
        """Return indices of corner tiles."""
        rows = self.number_rows()
        cols = self.number_cols()
        return [
            0,
            cols-1,
            cols * (rows - 1),
            cols*rows - 1]

    def bounding_box(self):
        """Return bounding box of (rotated) grid."""
        bounding_boxes_of_corner_tiles = np.array([
            self.tile_bounding_box(corner_tile_index)
                for corner_tile_index in self.corner_tiles()])
        min_x = np.min(bounding_boxes_of_corner_tiles.T[0])
        max_x = np.max(bounding_boxes_of_corner_tiles.T[1])
        min_y = np.min(bounding_boxes_of_corner_tiles.T[2])
        max_y = np.max(bounding_boxes_of_corner_tiles.T[3])
        return min_x, max_x, min_y, max_y

    def clear_all_tile_previews(self):
        """Clear all preview images in this grid."""
        for tile in self:
            tile.preview_src = ''  # Setter will set preview_img to None


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
        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')
        self.array_data = ArrayData.ArrayData(self.sem.device_name)

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
        grids_data['origin_sx_sy'] = str(
            [utils.round_xy(grid.origin_sx_sy) for grid in self])
        grids_data['sw_sh'] = str(
            [utils.round_xy(grid.sw_sh) for grid in self])
        grids_data['rotation'] = str(
            [grid.rotation for grid in self])
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

        # Save tile previews currently held in memory as pngs
        base_dir = self.cfg['acq']['base_dir']
        for grid_index in range(self.number_grids):
            for tile_index in range(self[grid_index].number_tiles):
                preview_path = utils.tile_preview_save_path(
                    base_dir, grid_index, None, None, tile_index)
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
        if self.sem.syscfg['device']['microtome'] == '6':  # or GCIB in use
            # Cycle through available colours.
            display_colour = (
                (self[new_grid_index - 1].display_colour + 1) % 10)
        else:
            # Use green by default in magc_mode.
            display_colour = 1

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
            new_grid.set_display_colour(roi_index % 10)

    def array_create_grids(self, imported_image):
        self.delete_array_grids(keep_template_grids=True)

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

        for array_index, rois in self.array_data.get_rois().items():
            for roi_index, roi in rois.items():
                center, size, rotation = self.array_data.get_roi_stage_properties(roi, imported_image)
                self.add_new_grid_from_roi(array_index, roi_index, center, size, rotation)
                # add focus points to grid
                grid_index = self.number_grids - 1
                for point in self.array_data.get_focus_points_in_roi(array_index, roi):
                    self.array_add_autofocus_point(
                        grid_index,
                        point['location'])

        for landmark_id, landmark in self.get_array_landmarks().items():
            # apply image transformation to landmarks
            location = utils.apply_transform(landmark, transform)
            self.set_array_landmark(landmark_id, location, landmark_type='stage')
            if landmark_id not in self.get_array_landmarks('target'):
                self.set_array_landmark(landmark_id, location, landmark_type='target')

    def array_update_grids(self, imported_image):
        # compute new grid locations
        # (always transform from reference source)
        for array_index, rois in self.array_data.get_rois().items():
            for roi_index, roi in rois.items():
                grid = self.find_roi_grid(array_index, roi_index)
                if grid:
                    center, _, rotation = self.array_data.get_roi_stage_properties(roi, imported_image)
                    grid.auto_update_tile_positions = False
                    grid.rotation = rotation
                    grid.update_tile_positions()
                    grid.auto_update_tile_positions = True
                    grid.centre_sx_sy = center

    def add_new_grid_from_roi(self, array_index, roi_index, center, size, rotation):
        # use first matching roi grid as template
        template_index = self.find_template_grid_index(roi_index)
        if template_index is None:
            template_index = 0

        grid = self[template_index]
        tile_width = grid.tile_width_d()
        tile_height = grid.tile_height_d()

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
        if roi_index is not None:
            new_grid.set_display_colour(roi_index % 10)
        elif array_index is not None:
            new_grid.set_display_colour(array_index % 10)

        # centre must be finally set after updating tile positions
        new_grid.auto_update_tile_positions = True
        new_grid.centre_sx_sy = center
        return new_grid

    def array_landmark_calibration(self):
        array_data = self.array_data
        source_landmarks = array_data.get_landmarks(landmark_type='source').values()
        target_landmarks = array_data.get_landmarks(landmark_type='target').values()
        array_data.transform = utils.create_point_transform(source_landmarks, target_landmarks)

    def find_template_grid_index(self, roi_index):
        for index, grid in enumerate(self):
            if grid.roi_index == roi_index and grid.array_index is None:
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
    ):
        source_grid = self[source_grid_index]
        roi_index = source_grid.roi_index
        source = self.array_data.get_roi(source_grid.array_index, roi_index)
        source_section_center = np.array(source['center'])
        source_section_angle = source['angle'] % 360

        source_grid_center = utils.apply_transform(source_grid.centre_sx_sy, np.linalg.inv(self.array_data.transform))

        source_section_grid = source_grid_center - source_section_center
        source_section_grid_distance = np.linalg.norm(source_section_grid)
        source_section_grid_angle = np.angle(complex(*source_section_grid), deg=True)

        for target_grid_index in target_grid_indices:
            target_grid = self[target_grid_index]

            if target_grid.roi_index == roi_index and source_grid_index != target_grid_index:
                target = self.array_data.get_roi(target_grid.array_index, roi_index)
                target_section_center = np.array(target['center'])
                target_section_angle = target['angle'] % 360

                # set all parameters in target grid
                target_grid_rotation = (source_grid.rotation - source_section_angle + target_section_angle) % 360

                target_grid.rotation = target_grid_rotation
                target_grid.size = source_grid.size
                target_grid.overlap = source_grid.overlap
                target_grid.row_shift = source_grid.row_shift
                target_grid.active_tiles = source_grid.active_tiles
                target_grid.frame_size_selector = (
                    source_grid.frame_size_selector)
                target_grid.pixel_size = source_grid.pixel_size
                target_grid.dwell_time_selector = (
                    source_grid.dwell_time_selector)
                target_grid.acq_interval = source_grid.acq_interval

                target_grid.acq_interval_offset = source_grid.acq_interval_offset
                target_grid.autofocus_ref_tiles = source_grid.autofocus_ref_tiles
                target_grid.array_autofocus_points_source = copy.deepcopy(
                    source_grid.array_autofocus_points_source)
                # xxx self.set_adaptive_focus_enabled(t, self.get_adaptive_focus_enabled(s))
                # xxx self.set_adaptive_focus_tiles(t, self.get_adaptive_focus_tiles(s))
                # xxx self.set_adaptive_focus_gradient(t, self.get_adaptive_focus_gradient(s))

                target_section_grid_angle = (source_section_grid_angle + source_section_angle - target_section_angle)

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
        center, size, rotation = self.array_data.get_roi_stage_properties(source, imported_image)

        grid.centre_sx_sy = center
        grid.rotation = rotation

# ------------------------- End of Array functions ------------------------------
