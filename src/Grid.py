from math import radians, cos, sin, sqrt
import numpy as np
from statistics import mean
from typing import List

import ArrayData
import constants
import utils
from Tile import Tile


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

    def size_p(self):
        return self.width_p(), self.height_p()

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

    def set_array_display_colour(self):
        if self.roi_index is not None:
            self.set_display_colour(self.roi_index % 10)
        elif self.array_index is not None:
            self.set_display_colour(self.array_index % 10)

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

    def tile_size_p(self):
        """Return tile size in pixels."""
        return self.frame_size[:2]

    def tile_width_p(self):
        """Return tile width in pixels."""
        return self.frame_size[0]

    def tile_height_p(self):
        """Return tile height in pixels."""
        return self.frame_size[1]

    def tile_depth(self):
        """Return tile height in pixels."""
        return self.frame_size[2] if len(self.frame_size) > 2 else 1

    def tile_size_d(self):
        """Return tile size in microns."""
        return np.array(self.frame_size[:2]) * self.pixel_size / 1000

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

    def activate_tiles_from_mask(self, mask):
        """Activate tiles based on a boolean mask."""
        mask = mask.flatten()
        if len(mask) != self.number_tiles:
            raise ValueError('Mask length does not match number of tiles.')
        self.active_tiles = np.where(mask)[0].tolist()
