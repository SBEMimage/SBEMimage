import os
from qtpy.QtCore import QRectF
from qtpy.QtGui import QPixmap, QPainter, QColor

from Grid import Grid
from image_io import imread
import numpy as np
import utils


class Overview(Grid):
    def __init__(self, coordinate_system, sem,
                 ov_active, centre_sx_sy, frame_size, frame_size_selector,
                 pixel_size, dwell_time, dwell_time_selector, 
                 bit_depth_selector, acq_interval,
                 acq_interval_offset, wd_stig_xy, vp_file_path,
                 debris_detection_area):

        # Use default OV frame size selector if selector not specified
        if frame_size_selector is None:
            frame_size_selector = sem.STORE_RES_DEFAULT_INDEX_OV

        # Initialize the overview as a 1x1 grid
        super().__init__(coordinate_system, sem,
                         active=ov_active, origin_sx_sy=centre_sx_sy,
                         rotation=0, size=[1, 1], overlap=0, row_shift=0,
                         active_tiles=[0], frame_size=frame_size,
                         frame_size_selector=frame_size_selector,
                         pixel_size=pixel_size, dwell_time=dwell_time,
                         dwell_time_selector=dwell_time_selector,
                         bit_depth_selector=bit_depth_selector,
                         display_colour=10, acq_interval=acq_interval,
                         acq_interval_offset=acq_interval_offset,
                         wd_stig_xy=wd_stig_xy)

        self.image = None
        self.vp_file_path = vp_file_path    # this will load the image if found
        self.debris_detection_area = debris_detection_area

    @property
    def centre_sx_sy(self):
        """Override centre_sx_sy from the parent class. Since overviews are 1x1
        grids, the centre is the same as the origin.
        """
        return self._origin_sx_sy

    @centre_sx_sy.setter
    def centre_sx_sy(self, sx_sy):
        self._origin_sx_sy = np.array(sx_sy)

    @property
    def centre_dx_dy(self):
        return self.cs.convert_s_to_d(self._origin_sx_sy)

    @property
    def magnification(self):
        return (self.sem.MAG_PX_SIZE_FACTOR
                / (self.frame_size[0] * self.pixel_size))

    @magnification.setter
    def magnification(self, mag):
        # Calculate and set pixel size:
        self.pixel_size = (self.sem.MAG_PX_SIZE_FACTOR
                           / (self.frame_size[0] * mag))

    @property
    def vp_file_path(self):
        return self._vp_file_path

    @vp_file_path.setter
    def vp_file_path(self, file_path):
        self._vp_file_path = file_path
        # Load OV image as QPixmap:
        if os.path.isfile(file_path):
            self.image = utils.image_to_QPixmap(imread(file_path))
        else:
            # Show blue transparent ROI when no OV image found
            blank = QPixmap(self.width_p(), self.height_p())
            blank.fill(QColor(255, 255, 255, 0))
            self.image = blank
            qp = QPainter()
            qp.begin(self.image)
            qp.setPen(QColor(0, 0, 255, 0))
            qp.setBrush(QColor(0, 0, 255, 70))
            qp.drawRect(QRectF(0, 0, self.width_p(), self.height_p()))
            qp.end()

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
                if not grid_manager[grid_index].active:
                    continue
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
                top_left_px = np.clip(
                    top_left_px - margin, 0, self.width_p())
                top_left_py = np.clip(
                    top_left_py - margin, 0, self.height_p())
                bottom_right_px = np.clip(
                    bottom_right_px + margin, 0, self.width_p())
                bottom_right_py = np.clip(
                    bottom_right_py + margin, 0, self.height_p())
            # set calculated detection area:
            self.debris_detection_area = [
                top_left_px, top_left_py, bottom_right_px, bottom_right_py]
        else:
            # set full detection area:
            self.debris_detection_area = [0, 0, self.width_p(), self.height_p()]
