import numpy as np
import os

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
        # Release old image
        if self.preview_img is not None:
            del self.preview_img
        self.preview_img = None
        if os.path.isfile(src):
            try:
                self.preview_img = utils.image_to_QPixmap(imread(src))
            except:
                pass
