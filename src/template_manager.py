import os
import json
from PyQt5.QtGui import QPixmap, QPainter, QColor

import imageio
import numpy as np
import utils
from grid_manager import Grid


class Template(Grid):
    def __init__(self, coordinate_system, sem, centre_sx_sy, rotation, pixel_size, w, h):

        # Initialize the overview as a 1x1 grid
        super().__init__(coordinate_system, sem, origin_sx_sy=centre_sx_sy,
                         rotation=rotation, size=[1, 1], overlap=0, row_shift=0,
                         active_tiles=[0], frame_size=(w, h), display_colour=8,
                         frame_size_selector=None,
                         pixel_size=pixel_size)
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


class TemplateManager:
    def __init__(self, config, sem, coordinate_system):
        self.cfg = config
        self.sem = sem
        self.cs = coordinate_system
        self._img_arr = None
        # Load OV parameters from user configuration
        centre_sx_sy = json.loads(self.cfg['gcib']['template_centre_sx_sy'])
        rotation = json.loads(self.cfg['gcib']['template_rotation'])
        w_h = json.loads(self.cfg['gcib']['template_w_h'])
        self.pixel_size = json.loads(self.cfg['overviews']['stub_ov_pixel_size'])
        self.stub_ov_viewport_image = self.cfg['overviews']['stub_ov_viewport_image']
        self.template = Template(self.cs, self.sem, centre_sx_sy, rotation, self.pixel_size, *w_h)

    def save_to_cfg(self):
        self.cfg['gcib']['template_rotation'] = str(self.template.rotation)
        self.cfg['gcib']['template_centre_sx_sy'] = str(utils.round_xy(self.template.centre_sx_sy, 0))
        self.cfg['gcib']['template_w_h'] = str(utils.round_xy(self.template.frame_size, 0))

    def add_new_template(self, centre_sx_sy, rotation, w, h):
        self.template = Template(self.cs, self.sem, centre_sx_sy, rotation, self.pixel_size, w, h)

    def delete_template(self):
        """Delete the template with the highest grid index."""
        self.template = Template(self.cs, self.sem, [0, 0], 0, self.pixel_size, 0, 0)

    def draw_template(self, x, y, w, h):
        """
        make template deletable
        See how to get pixel data from rotated rectangles https://stackoverflow.com/questions/11627362/how-to-straighten-a-rotated-rectangle-area-of-an-image-using-opencv-in-python/48553593#48553593
        see _vp_place_stub_overview for how to get the stub overview image data"""
        centre_sx_sy = self.cs.convert_d_to_s((x + w / 2, y + h / 2))

        self.add_new_template(centre_sx_sy, 0, w, h)

    @property
    def img_arr(self):
        if self._img_arr is None and os.path.isfile(self.stub_ov_viewport_image):
            self._img_arr = imageio.imread(self.stub_ov_viewport_image)
        return self._img_arr
