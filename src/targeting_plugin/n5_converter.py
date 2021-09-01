import os
import pybdv
from pybdv import BdvDataset
from skimage.io import imread, imsave
import numpy as np
import json

# TODO - need to add extra dependencies: pybdv and z5py
from src import utils
from src.targeting_plugin.conversion_metadata import ConversionMetadata
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

        self._current_dataset = None
        self._make_metadata()
        self._initialise_n5()

    def write_slice(self, path_to_tiff_slice):
        if self._current_dataset is not None:
            slice_image = imread(path_to_tiff_slice)
            self._add_slice_to_current_dataset(slice_image, self.acq.slice_counter)

    def update_ov_settings(self):
        """Update settings for the overview - if relevant settings have changed, it will increase the current id
        and save the new settings to the json"""
        current_metadata = ConversionMetadata()
        self._add_default_metadata_for_id(current_metadata, self._conversion_metadata.CURRENT_ID)

        if not current_metadata == self._conversion_metadata:
            self._add_default_metadata_for_id(self._conversion_metadata, self._conversion_metadata.current_id + 1)
            self._conversion_metadata.write_metadata(self._output_dir)
            self._initialise_n5()

    def _make_metadata(self):
        """Create default metadata, or read any existing from json file"""
        default_metadata = ConversionMetadata()
        self._add_default_metadata_for_id(default_metadata, 0)
        metadata_file = self._generate_metadata_path()

        if os.path.isfile(metadata_file):
            saved_metadata = ConversionMetadata()
            saved_metadata.create_metadata_from_file(metadata_file)

            # If metadata the same, use saved metadata, otherwise increment id and save new defaults
            if default_metadata == saved_metadata and \
                    self.acq.slice_counter > saved_metadata.first_slice_no_of_current_dataset:
                self._conversion_metadata = saved_metadata
            else:
                self._add_default_metadata_for_id(saved_metadata, saved_metadata.current_id + 1)
                self._conversion_metadata = saved_metadata
                self._conversion_metadata.write_metadata(self._output_dir)
        else:
            self._conversion_metadata = default_metadata
            self._conversion_metadata.write_metadata(self._output_dir)

    def _add_default_metadata_for_id(self, metadata, id):
        ov_size = self.ovm[self.ov_index].frame_size
        # TODO - check in overview frame size is it listed xy or yx??
        current_dataset_shape = (self._initial_z_depth, ov_size[1], ov_size[0])
        metadata.add_metadata_for_id(id,
                                     current_dataset_shape,
                                     self.acq.slice_counter,
                                     self.ovm[self.ov_index].centre_sx_sy,
                                     self.ovm[self.ov_index].rotation,
                                     ov_size,
                                     self.ovm[self.ov_index].pixel_size,
                                     self.acq.slice_thickness)

    def _generate_output_dir(self):
        n5_ov_dir_name = f'ov{str(self.ov_index).zfill(OV_DIGITS)}_n5'
        output_dir_path = os.path.join(self.base_dir, 'overviews', n5_ov_dir_name)
        if not os.path.exists(output_dir_path):
            subdirectory_list = [
                'overviews',
                f'overviews\\{n5_ov_dir_name}'
            ]
            success, exception_str = utils.create_subdirectories(
                self.base_dir, subdirectory_list)
            if not success:
                return
                # TODO - stop acquistion somehow? & handle this failure properly, so next time you try it will
                # create a totally new n5_converter

        return output_dir_path

    def _generate_n5_path(self):
        return os.path.join(self._output_dir,
                            f"{self.stack_name}_ov{str(self.ov_index).zfill(OV_DIGITS)}_"
                            f"{self._conversion_metadata.current_id}.n5")

    def _generate_metadata_path(self):
        return os.path.join(self._output_dir, ConversionMetadata.JSON_FILENAME)

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
        assert(slice_image.shape[0] == self._conversion_metadata.current_dataset_shape[1])
        assert(slice_image.shape[1] == self._conversion_metadata.current_dataset_shape[2])

        # add dummy first dimension to slice, so it's 3d
        slice_image = np.expand_dims(slice_image, axis=0)

        start_slice = slice_counter - self._conversion_metadata.first_slice_no_of_current_dataset
        self._current_dataset[start_slice:start_slice + 1,
                              0:self._conversion_metadata.current_dataset_shape[1],
                              0:self._conversion_metadata.current_dataset_shape[2]] = slice_image

    def _initialise_n5(self):
        n5_path = self._generate_n5_path()
        # resolution in micrometer
        resolution = [self._conversion_metadata.slice_thickness/1000,
                      self._conversion_metadata.ov_pixel_size/1000,
                      self._conversion_metadata.ov_pixel_size/1000]

        # If n5 file doesn't exist, create it, otherwise open existing one
        if not os.path.isfile(n5_path):
            # Have to be careful with downsampling factors vs chunk size. When you write continuously to a
            # BdvDataset, in order to downsample in z it will first read a chunk from the top level dataset that is
            # == to the size that will produce one slice in the smallest downsampling level. i.e. if your factors
            # are: [2,2,2], [2,2,2], [2,2,2], then at the deepest level, the downsampling is 8, 8, 8. Therefore,
            # an area with a z thickness of 8 will be read, processed, downsampled etc, and then written back into
            # the various downsampling levels. To make this read efficient your chunk size should be larger than or
            # equal to the highest downsampling in z ( i.e. 8 for this case). Otherwise, if it is e.g. chunking of 1
            # in z, then as each slice is written, it will need to access more and more chunks to read this 8 depth
            # initial volume - which is very slow! Optimum seems to be z chunk size equal to highest downsampling in
            # z For x/y, larger chunk sizes are more efficient for reading and writing slice by slice, as again to
            # read or write an 8 z slice full size volume, means you have to touch fewer chunks (aim so that total
            # amount of data is around the same as a 64x64x64 chunk)
            # TODO - you get small performance increases by
            #  modifying the BdvDataset code to hold on to the file handle and not reopen the n5 file at various steps
            pybdv.initialize_bdv(n5_path, self._conversion_metadata.current_dataset_shape, np.uint8,
                                 downscale_factors=[[2, 2, 2], [2, 2, 2], [2, 2, 2]],
                                 resolution=resolution, unit=self._physical_unit, chunks=(8, 128, 128),
                                 affine=self._generate_affine(resolution))

        self._current_dataset = BdvDataset(n5_path, setup_id=0, timepoint=0)


