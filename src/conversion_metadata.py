import json
import os


class ConversionMetadata:
    # json filename and keys for metadata
    JSON_FILENAME = "conversion_metadata.json"
    CURRENT_ID = "current_id"
    CURRENT_DATASET_SHAPE = "current_dataset_shape"
    FIRST_SLICE = "first_slice_no_of_current_dataset"
    CONVERTED_FILES = "converted_files"
    OV_CENTRE_SX_SY = "ov_centre_sx_sy"
    OV_ROTATION = "ov_rotation"
    OV_SIZE = "ov_size"
    OV_PIXEL_SIZE = "ov_pixel_size"
    SLICE_THICKNESS = "slice_thickness"

    def __init__(self):
        self._metadata = {self.CURRENT_ID: 0, self.CURRENT_DATASET_SHAPE: [], self.CONVERTED_FILES: []}

    def create_metadata_from_file(self, json_file_path):
        with open(json_file_path, 'r', encoding='utf-8') as f:
            self._metadata = json.load(f)

    def add_metadata_for_id(self, current_id, current_dataset_shape, first_slice_no_of_current_dataset,
                            ov_centre_sx_sy, ov_rotation, ov_size, ov_pixel_size, slice_thickness):
        self._metadata[self.CURRENT_ID] = current_id
        self._metadata[self.CURRENT_DATASET_SHAPE] = current_dataset_shape
        self._metadata[self.FIRST_SLICE] = first_slice_no_of_current_dataset
        new_id_metadata = {self.OV_CENTRE_SX_SY: ov_centre_sx_sy,
                           self.OV_ROTATION: ov_rotation,
                           self.OV_SIZE: ov_size,
                           self.OV_PIXEL_SIZE: ov_pixel_size,
                           self.SLICE_THICKNESS: slice_thickness}
        self._metadata[self.CONVERTED_FILES].append(new_id_metadata)

    def write_metadata(self, output_dir):
        json_file = os.path.join(output_dir, self.JSON_FILENAME)
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(self._metadata, f, ensure_ascii=False, indent=4)

    def __eq__(self, other):
        metadata_same = True
        if self.ov_centre_sx_sy != other.ov_centre_sx_sy:
            metadata_same = False
        if self.ov_rotation != other.ov_rotation:
            metadata_same = False
        if self.ov_size != other.ov_size:
            metadata_same = False
        if self.ov_pixel_size != other.ov_pixel_size:
            metadata_same = False
        if self.slice_thickness != other.slice_thickness:
            metadata_same = False

        return metadata_same

    @property
    def current_id(self):
        return self._metadata[self.CURRENT_ID]

    @current_id.setter
    def current_id(self, value):
        self._metadata[self.CURRENT_ID] = value

    @property
    def current_dataset_shape(self):
        return self._metadata[self.CURRENT_DATASET_SHAPE]

    @current_dataset_shape.setter
    def current_dataset_shape(self, value):
        self._metadata[self.CURRENT_DATASET_SHAPE] = value

    @property
    def first_slice_no_of_current_dataset(self):
        return self._metadata[self.FIRST_SLICE]

    @first_slice_no_of_current_dataset.setter
    def first_slice_no_of_current_dataset(self, value):
        self._metadata[self.FIRST_SLICE] = value

    @property
    def ov_centre_sx_sy(self):
        return self._metadata[self.CONVERTED_FILES][self.current_id][self.OV_CENTRE_SX_SY]

    @ov_centre_sx_sy.setter
    def ov_centre_sx_sy(self, value):
        self._metadata[self.CONVERTED_FILES][self.current_id][self.OV_CENTRE_SX_SY] = value

    @property
    def ov_rotation(self):
        return self._metadata[self.CONVERTED_FILES][self.current_id][self.OV_ROTATION]

    @ov_rotation.setter
    def ov_rotation(self, value):
        self._metadata[self.CONVERTED_FILES][self.current_id][self.OV_ROTATION] = value

    @property
    def ov_size(self):
        return self._metadata[self.CONVERTED_FILES][self.current_id][self.OV_SIZE]

    @ov_size.setter
    def ov_size(self, value):
        self._metadata[self.CONVERTED_FILES][self.current_id][self.OV_SIZE] = value

    @property
    def ov_pixel_size(self):
        return self._metadata[self.CONVERTED_FILES][self.current_id][self.OV_PIXEL_SIZE]

    @ov_pixel_size.setter
    def ov_pixel_size(self, value):
        self._metadata[self.CONVERTED_FILES][self.current_id][self.OV_PIXEL_SIZE] = value

    @property
    def slice_thickness(self):
        return self._metadata[self.CONVERTED_FILES][self.current_id][self.SLICE_THICKNESS]

    @slice_thickness.setter
    def slice_thickness(self, value):
        self._metadata[self.CONVERTED_FILES][self.current_id][self.SLICE_THICKNESS] = value



