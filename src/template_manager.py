import os
import json
from math import sin, cos, radians
from collections import Counter
import imageio
import cv2
import tqdm
import scipy.ndimage
import numpy as np
import utils
from grid_manager import Grid, GridManager


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


class TemplateManager:
    # TODO: add multi-template support...
    # TODO: add multiprocessing with shared (Raw)Array (multiprocessing.Array supports concurrent writes with locking)
    # TODO: add parameters to config
    def __init__(self, ovm):
        self.cfg = ovm.cfg
        self.sem = ovm.sem
        self.cs = ovm.cs
        self.ovm = ovm
        self.template = None
        self._img_arr = None
        self._stub_ov_arr = None
        # Load OV parameters from session configuration
        centre_sx_sy = json.loads(self.cfg['gcib']['template_centre_sx_sy'])
        rotation = json.loads(self.cfg['gcib']['template_rotation'])
        w_h = json.loads(self.cfg['gcib']['template_w_h'])
        self.pixel_size = json.loads(self.cfg['overviews']['stub_ov_pixel_size'])
        self.stub_ov_viewport_image = self.cfg['overviews']['stub_ov_viewport_image']
        self.add_new_template(centre_sx_sy, rotation, *w_h)

    @property
    def img_arr(self):
        if self._img_arr is None and os.path.isfile(self.stub_ov_viewport_image):
            self._img_arr = self.calc_img_arr()
        return self._img_arr

    @property
    def stub_ov_arr(self):
        if self._stub_ov_arr is None:
            self._stub_ov_arr = imageio.imread(self.stub_ov_viewport_image).swapaxes(1, 0)
        return self._stub_ov_arr

    def delete_cache(self):
        self._img_arr = None
        self._stub_ov_arr = None

    def save_to_cfg(self):
        self.cfg['gcib']['template_rotation'] = str(self.template.rotation)
        self.cfg['gcib']['template_centre_sx_sy'] = str(utils.round_xy(self.template.centre_sx_sy, 0))
        self.cfg['gcib']['template_w_h'] = str(utils.round_xy(self.template.frame_size, 0))

    def add_new_template(self, centre_sx_sy, rotation, w, h):
        self.template = Template(self.cs, self.sem, centre_sx_sy, rotation, self.pixel_size, w, h)
        self._img_arr = None

    def delete_template(self):
        """Delete the template with the highest grid index."""
        self.template = Template(self.cs, self.sem, [0, 0], 0, self.pixel_size, 0, 0)
        self._img_arr = None

    def draw_template(self, x, y, w, h):
        """
        """
        centre_sx_sy = self.cs.convert_d_to_s((x + w / 2, y + h / 2))
        self.add_new_template(centre_sx_sy, 0, w, h)

    def _run_template_matching(self, ds: float = 5, sigma: float = 1, n_rotations: int = 60, threshold=0.7,
                               min_cc_cnt: int = 5, max_cc_cnt: int = 5000):
        """

        Args:
            ds: Down sampling applied to template and stub OV.
            sigma: Sigma for Gaussian Smoothing. Applied to stub OV and template image.
            n_rotations: Number of rotations to use for template matching. Applies equi-distant rotations to template
                between 0 and 360 and uses each version for template matching.
            threshold: Threshold to consider a match.
            min_cc_cnt:
            max_cc_cnt:

        Returns:
            Locations of connected components of high matching scores in relative SEM (d) coordinates
            (distances as shown in SEM images) with grid rotation applied (if theta > 0).
        """
        temp = self.img_arr.astype(np.float32)
        stubov = self.stub_ov_arr.astype(np.float32)
        stubov_sh_orig = stubov.shape
        if ds != 1:
            temp = scipy.ndimage.zoom(temp, 1 / ds, order=3)
            stubov = scipy.ndimage.zoom(stubov, 1 / ds, order=3)
        # store effective down sampling (deviation < 1/10000 ..):
        ds = np.mean(np.array(stubov_sh_orig) / np.array(stubov.shape))
        if sigma > 0:
            temp = scipy.ndimage.gaussian_filter(temp, sigma)
            stubov = scipy.ndimage.gaussian_filter(stubov, sigma)
        out_angles = np.ones_like(stubov).astype(np.int32) * -360
        out_scores = np.zeros_like(stubov).astype(np.float32)
        # make stubov rotatable without losing pixels by padding to square extent of c^2 = X^2 + Y^2
        # maybe can be solved more elegant by bordermode / value in warpAffine
        pad_extent = ((np.sqrt(stubov.shape[0]**2 + stubov.shape[1]**2) - np.array(stubov.shape)) / 2).astype(np.int)
        stubov = np.pad(stubov, ((pad_extent[0], pad_extent[0]), (pad_extent[1], pad_extent[1])), constant_values=0)
        # get center in pixels relative to stub ov origin
        center = tuple((stubov.shape[0] // 2, stubov.shape[1] // 2))
        for angle in tqdm.tqdm(np.linspace(0, 360, n_rotations, endpoint=False), total=n_rotations, desc='Templates'):
            # rotate stub ov and extract template; instead of rotating template, rotate stub ov with -angle
            # rotate the stub ov to prevent introduction of black pixels in the template
            stub_ov_warped = cv2.warpAffine(stubov, cv2.getRotationMatrix2D(center, -angle, 1), stubov.shape[:2])
            stub_ov_warped = np.pad(stub_ov_warped, ((temp.shape[0] // 2, temp.shape[0] // 2),
                                                     (temp.shape[1] // 2, temp.shape[1] // 2)))
            for flip in [[1, 1], [1, -1], [-1, 1], [-1, -1]]:
                # TODO: use mask to ignore padded area (e.g. use -1 values); unclear how mask alters behavior of matchTemplate
                out_ = cv2.matchTemplate(stub_ov_warped, temp[::flip[0], ::flip[1]], cv2.TM_CCOEFF_NORMED)
                # rotate back to original frame
                out_ = cv2.warpAffine(out_, cv2.getRotationMatrix2D(center, angle, 1), out_.shape[:2])[pad_extent[0]:-pad_extent[0], pad_extent[1]:-pad_extent[1]]
                # merge previous runs

                out_[out_ < threshold] = 0
                # out_.shape is off by +1 compared to out.shape due to template matching, ignore this shift.
                mask_angle = out_[:out_scores.shape[0], :out_scores.shape[1]] > out_scores
                # update scores
                out_scores[mask_angle] = out_[:out_scores.shape[0], :out_scores.shape[1]][mask_angle]
                # update angles
                out_angles[mask_angle] = angle  # +angle because we rotated the stub ov
                del out_

        # might be useful for GUI
        # imageio.imsave(self.stub_ov_viewport_image[:-4] + '_MASK.tif', (out_scores > threshold).astype(np.uint16) * 255)
        # imageio.imsave(self.stub_ov_viewport_image[:-4] + '_ANGLES.tif', (out_angles + 360).astype(np.uint16))

        # Compute position of stub overview (upper left corner) and its
        # width and height
        origin_stub = np.array(self.ovm['stub'].origin_dx_dy)  # copy array!
        origin_stub[0] -= self.ovm['stub'].tile_width_d() / 2
        origin_stub[1] -= self.ovm['stub'].tile_height_d() / 2

        # find most common angle for each connected component
        dc_angles = {}
        dc_locs = {}
        lbl, nb_objs = scipy.ndimage.label(out_scores >= threshold)  # label array, number of objects
        if nb_objs == 0:
            return dc_locs, dc_angles
        # this loop could be heavily optimized in cython
        for ix, cnt in zip(*np.unique(lbl, return_counts=True)):
            if ix == 0 or min_cc_cnt > cnt or max_cc_cnt < cnt:
                print(f'Skipped match with ID={ix} and N={cnt} pixel support.')
                continue
            locs = np.where(lbl == ix)
            angles = self.template.rotation + out_angles[locs]
            dc_angles[ix] = Counter(angles).most_common(1)[0][0]  # first element, and (angle, counts)[0]
            dc_locs[ix] = (np.transpose(locs).mean(axis=0) * ds * self.pixel_size / 1000 + origin_stub)
            out_angles[locs] = dc_angles[ix]

        return dc_locs, dc_angles

    def place_grids_template_matching(self, gm: GridManager):
        """
        Requires already existing grids
        Returns:

        """
        dc_locs, dc_angles = self._run_template_matching()

        grid_index = gm.number_grids - 2  # get previous grid index
        grid = gm[grid_index]
        tile_width = grid.tile_width_d()
        tile_height = grid.tile_height_d()
        # size[rows, cols]
        size = [np.int(np.ceil(self.template.tile_height_d() / tile_height)),
                np.int(np.ceil(self.template.tile_width_d() / tile_width))]

        for k in dc_locs:
            loc_d = dc_locs[k]
            loc_s = self.cs.convert_d_to_s(loc_d)
            rot = dc_angles[k]
            gm.add_new_grid(rotation=rot, size=size,
                            frame_size_selector=grid.frame_size_selector,
                            dwell_time=grid.dwell_time,
                            dwell_time_selector=grid.dwell_time_selector,
                            pixel_size=grid.pixel_size)
            gm[gm.number_grids - 1].centre_sx_sy = loc_s
            gm[gm.number_grids - 1].update_tile_positions()

    def calc_img_arr(self):
        """

        Returns:
            Template image array in with shape XY.
        """
        stub_ov = imageio.imread(self.stub_ov_viewport_image)
        # Compute position of stub overview (upper left corner) and its
        # width and height
        dx, dy = self.ovm['stub'].origin_dx_dy
        dx -= self.ovm['stub'].tile_width_d() / 2
        dy -= self.ovm['stub'].tile_height_d() / 2
        # get center in pixels relative to stub ov origin
        dx_tp, dy_tp = self.template.origin_dx_dy
        dx_tp -= self.template.tile_width_d() / 2
        dy_tp -= self.template.tile_height_d() / 2
        angle = self.template.rotation
        # get template bounding box
        lower_p_x = int((dx_tp - dx) / self.pixel_size * 1000)
        lower_p_y = int((dy_tp - dy) / self.pixel_size * 1000)
        upper_p_x = lower_p_x + int(self.template.frame_size[0])
        upper_p_y = lower_p_y + int(self.template.frame_size[1])
        # retrieve template pixels
        if angle != 0:
            # get template transformation
            center = (self.template.origin_dx_dy - np.array([dx, dy])) / self.pixel_size * 1000
            center = tuple(center.astype(np.int))
            A = cv2.getRotationMatrix2D(center, angle, 1)
            # rotate stub ov and extract template
            stub_ov_warped = cv2.warpAffine(stub_ov, A, stub_ov.shape[:2])
            res = cv2.getRectSubPix(stub_ov_warped, tuple(map(int, self.template.frame_size)), center)
        else:
            res = stub_ov[lower_p_y:upper_p_y, lower_p_x:upper_p_x]
        return res.swapaxes(1, 0)
