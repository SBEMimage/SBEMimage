import numpy as np

from Grid import Grid


class Template(Grid):
    def __init__(self, coordinate_system, sem, centre_sx_sy, rotation, pixel_size, w, h):

        # Initialize the overview as a 1x1 grid
        super().__init__(coordinate_system, sem, origin_sx_sy=centre_sx_sy,
                         rotation=rotation, size=[1, 1], overlap=0, row_shift=0,
                         active_tiles=[0], frame_size=(w, h), display_colour=8,
                         frame_size_selector=-1, pixel_size=pixel_size)
        self._origin_sx_sy = centre_sx_sy

    @property
    def centre_sx_sy(self):
        """Override centre_sx_sy from the parent class. Since tempaltes are 1x1
        grids, the centre is the same as the origin.
        """
        return self._origin_sx_sy

    @centre_sx_sy.setter
    def centre_sx_sy(self, sx_sy):
        self._origin_sx_sy = np.array(sx_sy)

    def bounding_box(self):
        centre_dx, centre_dy = self.centre_dx_dy
        # Top left corner of template in d coordinate system:
        top_left_dx = centre_dx - self.width_d()/2
        top_left_dy = centre_dy - self.height_d()/2
        bottom_right_dx = top_left_dx + self.width_d()
        bottom_right_dy = top_left_dy + self.height_d()
        return top_left_dx, top_left_dy, bottom_right_dx, bottom_right_dy
