import os
import pybdv
from pybdv import BdvDataset
from skimage.io import imread, imsave
import numpy as np

# TODO - need to add extra dependencies: pybdv and z5py

from src.utils import OV_DIGITS


class OnTheFlyOverviewN5Converter:

    def __init__(self, acq, ovm, ov_index):
        self.acq = acq
        self.ovm = ovm
        self.ov_index = ov_index

        self.base_dir = acq.base_dir
        self.stack_name = acq.stack_name
        self._output_dir = self._generate_output_dir()

        # Z depth to initialise n5 datasets to (there's no performance penalty for initialising to very large z depth,
        # so make sure this is big enough to contain all the z slices you want to acquire)
        self._initial_z_depth = 100000
        self._physical_unit = "micron"

        # current n5 id - when settings change (e.g. cutting depth / size of overview etc.), it will be written to a new
        # n5 with id + 1
        self._current_id = -1
        self._current_dataset = None
        self._current_dataset_shape = []
        self._first_slice_no_of_current_dataset = 0

        # current settings: these are settings that if changed, need a new n5 to be created
        # TODO - others to go here? e.g. if current slice counter or z_diff are manually changed?
        # TODO - current images are placed at (0,0) for xy, in future it would be good to place them at their proper
        # location via the affine transform. Then people could move their overviews and still have them display
        # correctly
        self._ov_centre_sx_sy = ovm[ov_index].centre_sx_sy
        self._ov_rotation = ovm[ov_index].rotation
        self._ov_size = ovm[ov_index].frame_size
        self._ov_pixel_size = ovm[ov_index].pixel_size
        self._slice_thickness = acq.slice_thickness

        self._initialise_new_n5()

    def write_slice(self, path_to_tiff_slice):
        if self._current_dataset is not None:
            slice_image = imread(path_to_tiff_slice)
            self._add_slice_to_current_dataset(slice_image, self.acq.slice_counter)

    def update_ov_settings(self):
        settings_changed = False
        overview = self.ovm[self.ov_index]

        if overview.centre_sx_sy != self._ov_centre_sx_sy:
            self._ov_centre_sx_sy = overview.centre_sx_sy
            settings_changed = True
        if overview.rotation != self._ov_rotation:
            self._ov_rotation = overview.rotation
            settings_changed = True
        if overview.frame_size != self._ov_size:
            self._ov_size = overview.frame_size
            settings_changed = True
        if overview.pixel_size != self._ov_pixel_size:
            self._ov_pixel_size = overview.pixel_size
            settings_changed = True
        if self.acq.slice_thickness != self._slice_thickness:
            self._slice_thickness = self.acq.slice_thickness
            settings_changed = True

        if settings_changed:
            self._initialise_new_n5()

    def _generate_output_dir(self):
        return os.path.join(self.base_dir, 'overviews', f'ov{str(self.ov_index).zfill(OV_DIGITS)}_n5')

    def _generate_n5_path(self):
        return os.path.join(self._output_dir,
                            f"{self.stack_name}_ov{str(self.ov_index).zfill(OV_DIGITS)}_{self._current_id}.n5")

    def _generate_affine(self, resolution):
        # scales to resolution and translates by total z depth + 1/2 the z resolution.
        # The 1/2 z resolution is necessary, as bdv normally centres the first pixel about zero, i.e. the image
        # actually starts from -1/2 the z resolution. We want it to actually start from 0 to more closely mirror the
        # sbem acquisition process.
        affine = [resolution[2], 0.0, 0.0, 0.0,
                  0.0, resolution[1], 0.0, 0.0,
                  0.0, 0.0, resolution[0], self.acq.total_z_diff + (0.5*resolution[0])]
        return affine

    def _add_slice_to_current_dataset(self, slice_image, slice_counter):
        # xy extent of slice must be the same as the dataset
        assert(slice_image.shape[0] == self._current_dataset_shape[1])
        assert(slice_image.shape[1] == self._current_dataset_shape[2])

        # add dummy first dimension to slice, so it's 3d
        slice_image = np.expand_dims(slice_image, axis=0)

        start_slice = slice_counter - self._first_slice_no_of_current_dataset
        self._current_dataset[start_slice:start_slice + 1, 0:self._current_dataset_shape[1], 0:self._current_dataset_shape[2]] = slice_image

    def _initialise_new_n5(self):
        self._current_id = self._current_id + 1
        # TODO - check in overview frame size is it listed xy or yx??
        self._current_dataset_shape = (self._initial_z_depth, self._ov_size[1], self._ov_size[0])

        n5_path = self._generate_n5_path()
        # resolution in micrometer
        resolution = [self._slice_thickness/1000, self._ov_pixel_size/1000, self._ov_pixel_size/1000]

        # Have to be careful with downsampling factors vs chunk size. When you write continuously to a BdvDataset,
        # in order to downsample in z it will first read a chunk from the top level dataset that is == to the size
        # that will produce one slice in the smallest downsampling level. i.e. if your factors are: [2,2,2], [2,2,2],
        # [2,2,2], then at the deepest level, the downsampling is 8, 8, 8. Therefore, an area with a z thickness of 8
        # will be read, processed, downsampled etc, and then written back into the various downsampling levels. To
        # make this read efficient your chunk size should be larger than or equal to the highest downsampling in z (
        # i.e. 8 for this case). Otherwise, if it is e.g. chunking of 1 in z, then as each slice is written,
        # it will need to access more and more chunks to read this 8 depth initial volume - which is very slow!
        # Optimum seems to be z chunk size equal to highest downsampling in z
        # For x/y, larger chunk sizes are more efficient for reading and writing slice by slice, as again to read
        # or write an 8 z slice full size volume, means you have to touch fewer chunks
        # (aim so that total amount of data is around the same as a 64x64x64 chunk)
        # TODO - you get small performance increases by modifying the BdvDataset code to hold on to the file handle and
        # not reopen the n5 file at various steps
        pybdv.initialize_bdv(n5_path, self._current_dataset_shape, np.uint8,
                             downscale_factors=[[2, 2, 2], [2, 2, 2], [2, 2, 2]],
                             resolution=resolution, unit=self._physical_unit, chunks=(8, 128, 128),
                             affine=self._generate_affine(resolution))

        self._current_dataset = BdvDataset(n5_path, setup_id=0, timepoint=0)
        self._first_slice_no_of_current_dataset = self.acq.slice_counter
