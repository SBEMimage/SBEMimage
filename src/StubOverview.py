import os

import utils
from Grid import Grid
from image_io import imread


class StubOverview(Grid):

    def __init__(self, coordinate_system, sem,
                 centre_sx_sy, grid_size, overlap, frame_size_selector,
                 pixel_size, dwell_time_selector, vp_file_path):

        # Initialize the stub overview as a grid
        super().__init__(coordinate_system, sem,
                         active=True, origin_sx_sy=[0, 0],
                         rotation=0, size=grid_size,
                         overlap=overlap, row_shift=0, active_tiles=[],
                         frame_size=None, frame_size_selector=frame_size_selector,
                         pixel_size=pixel_size, dwell_time=None,
                         dwell_time_selector=dwell_time_selector,
                         bit_depth_selector=0,
                         display_colour=11)

        self.lm_mode = False
        # Set the centre coordinates, which will update the origin.
        self.centre_sx_sy = centre_sx_sy
        # QPixmaps of current stub OV (original and downsampled)
        self.pixmaps_ = {1: None, 2: None, 4: None, 8: None, 16: None}
        # QPixmaps are loaded when file path is set/changed.
        self.vp_file_path = vp_file_path

    def image(self, mag=1):
        if mag in [1, 2, 4, 8, 16]:
            return self.pixmaps_[mag]
        return None

    @property
    def vp_file_path(self):
        return self._vp_file_path

    @vp_file_path.setter
    def vp_file_path(self, file_path):
        self._vp_file_path = file_path
        # Release old images
        del self.pixmaps_
        self.pixmaps_ = {1: None, 2: None, 4: None, 8: None, 16: None}
        # Load images as QPixmaps:
        file_exists = os.path.isfile(file_path)
        for level, mag in enumerate([1, 2, 4, 8, 16]):
            image = None
            if file_exists:
                image = imread(file_path, level=level)
                if image is not None:
                    image = utils.image_to_QPixmap(image)
            self.pixmaps_[mag] = image
