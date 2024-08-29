# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module manages all imported images. Currently, only single images can
be imported, but this could be extended to image stacks / 3D volumes in the
future.
"""

import json
import numpy as np
import os
from qtpy.QtGui import QTransform

import utils
from image_io import imread, imread_metadata
from utils import round_xy, image_to_QPixmap


class ImportedImage:
    def __init__(self, image_src, description, centre_sx_sy, rotation, flipped,
                 size, pixel_size, enabled, transparency, is_array=False):
        self.image_src = image_src   # Path to image file
        self.description = description
        self.centre_sx_sy = centre_sx_sy
        self.rotation = rotation
        self.flipped = flipped
        self.size = size
        self.pixel_size = pixel_size
        self.image_pixel_size = pixel_size
        self.enabled = enabled
        self.transparency = transparency
        self.is_array = is_array
        self.load_image()

    def load_image(self):
        # Load image as QPixmap
        self.source_image = None
        self.image = None
        if os.path.isfile(self.image_src):
            try:
                metadata = imread_metadata(self.image_src)
                image_pixel_size = metadata.get('pixel_size')
                if image_pixel_size is not None:
                    self.image_pixel_size = image_pixel_size[0] * 1e3
                image = imread(self.image_src)
                height, width = image.shape[:2]
                self.size = [width, height]
                self.source_image = image_to_QPixmap(image)
                self.update_image()
            except:
                pass

    def update_image(self):
        if self.rotation != 0 or self.flipped:
            transform = QTransform()
            transform.rotate(self.rotation)
            if self.flipped:
                transform.scale(1, -1)
            self.image = self.source_image.transformed(transform)
        else:
            self.image = self.source_image

    @property
    def centre_sx_sy(self):
        return self._centre_sx_sy

    @centre_sx_sy.setter
    def centre_sx_sy(self, sx_sy):
        self._centre_sx_sy = list(sx_sy)

    @property
    def scale(self):
        return self.pixel_size / self.image_pixel_size
        

class ImportedImages(list):

    def __init__(self, config, base_dir):
        super().__init__()
        self.cfg = config

        target_dir = os.path.join(base_dir, 'imported')
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir)
            except Exception as e:
                utils.log_error(
                    'Array-CTRL',
                    f'Could not create directory {target_dir} for imported '
                    f'images. Make sure the drive/folder is available for '
                    f'write access. {str(e)}')
                return
        self.target_dir = target_dir

        # Load parameters from session configuration
        imported = self.cfg['imported']
        number_imported = int(imported['number_imported'])
        image_src = json.loads(imported['image_src'])
        description = json.loads(imported['description'])
        centre_sx_sy = json.loads(imported['centre_sx_sy'])
        rotation = json.loads(imported['rotation'])
        flipped = json.loads(imported['flipped'])
        size = json.loads(imported['size'])
        pixel_size = json.loads(imported['pixel_size'])
        enabled = json.loads(imported['enabled'])
        transparency = json.loads(imported['transparency'])
        is_array = json.loads(imported['is_array'])

        # For backward compatibility
        while len(flipped) < number_imported:
            flipped.append(False)
        while len(enabled) < number_imported:
            enabled.append(True)
        while len(is_array) < number_imported:
            is_array.append(False)

        for i in range(number_imported):
            self.add_image(image_src[i], description[i], centre_sx_sy[i], rotation[i], flipped[i],
                           size[i], pixel_size[i], enabled[i], transparency[i], is_array[i])

    @property
    def number_imported(self):
        return len(self)

    def save_to_cfg(self):
        imported = self.cfg['imported']
        imported['number_imported'] = str(self.number_imported)
        imported['image_src'] = json.dumps(
            [image.image_src for image in self])
        imported['description'] = json.dumps(
            [image.description for image in self])
        imported['centre_sx_sy'] = utils.serialise_list(
            [round_xy(img.centre_sx_sy)
             for img in self])
        imported['rotation'] = str(
            [img.rotation for img in self])
        imported['flipped'] = json.dumps(
            [img.flipped for img in self])
        imported['size'] = utils.serialise_list(
            [img.size for img in self])
        imported['pixel_size'] = str(
            [img.pixel_size for img in self])
        imported['enabled'] = json.dumps(
            [image.enabled for image in self])
        imported['transparency'] = str(
            [img.transparency for img in self])
        imported['is_array'] = json.dumps(
            [image.is_array for image in self])

    def add_image(self, image_src, description, centre_sx_sy, rotation, flipped,
                  size, pixel_size, enabled, transparency, is_array=False):
        new_imported_image = ImportedImage(image_src, description, centre_sx_sy, rotation, flipped,
                                           size, pixel_size, enabled, transparency, is_array)
        self.append(new_imported_image)
        return new_imported_image

    def delete_image(self, index):
        """Delete the imported image at index"""
        del self[index]

    def delete_all_images(self):
        """Release all imported images"""
        while len(self) > 0:
            self.delete_image(-1)

    def find_array_image(self):
        for imported_image in self:
            if imported_image.is_array:
                return imported_image
        return None

    def find_array_image_index(self):
        for index, imported_image in enumerate(self):
            if imported_image.is_array:
                return index
        return None

    def update_array_image(self, transform):
        array_image = self.find_array_image()
        if array_image:
            angle = utils.get_transform_angle(transform)
            scale = utils.get_transform_scale(transform)

            center = np.array(array_image.size) * array_image.image_pixel_size / 1000 / 2
            image_center_target_s = utils.apply_transform(center, transform)

            if not array_image.flipped:
                angle = -angle
            array_image.rotation = angle % 360
            array_image.pixel_size = array_image.image_pixel_size * scale
            array_image.centre_sx_sy = image_center_target_s
            array_image.update_image()
