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

import os
import json
from qtpy.QtGui import QTransform

import utils
from image_io import imread
from utils import round_xy, image_to_QPixmap


class ImportedImage:
    def __init__(self, image_src, description, centre_sx_sy, rotation,
                 size, pixel_size, enabled, transparency, is_array=False):
        self._image_src = image_src   # Path to image file
        self.description = description
        self.centre_sx_sy = centre_sx_sy
        self._rotation = rotation
        self.size = size
        self.pixel_size = pixel_size
        self.enabled = enabled
        self.transparency = transparency
        self.is_array = is_array
        self._load_image()

    def __del__(self):
        if os.path.exists(self._image_src):
            os.remove(self._image_src)

    def _load_image(self):
        # Load image as QPixmap
        if os.path.isfile(self.image_src):
            try:
                image = imread(self.image_src)
                height, width = image.shape[:2]
                self.size = [width, height]
                self.image = image_to_QPixmap(image)
                if self.rotation != 0:
                    trans = QTransform()
                    trans.rotate(self.rotation)
                    self.image = self.image.transformed(trans)
            except:
                self.image = None
        else:
            self.image = None

    @property
    def centre_sx_sy(self):
        return self._centre_sx_sy

    @centre_sx_sy.setter
    def centre_sx_sy(self, sx_sy):
        self._centre_sx_sy = list(sx_sy)

    @property
    def image_src(self):
        return self._image_src

    @image_src.setter
    def image_src(self, src):
        self._image_src = src
        self._load_image()

    @property
    def rotation(self):
        return self._rotation

    @rotation.setter
    def rotation(self, new_rotation):
        self._rotation = new_rotation
        self._load_image()

    def flip_x(self):
        trans = QTransform()
        trans.setMatrix(
            -1,0,0,
            0,1,0,
            0,0,1,
            )
        self.image = self.image.transformed(trans)
        

class ImportedImages(list):

    def __init__(self, config, base_dir):
        super().__init__()
        self.cfg = config
        self.number_imported = 0

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
        size = json.loads(imported['size'])
        pixel_size = json.loads(imported['pixel_size'])
        if 'enabled' in imported:
            enabled = json.loads(imported['enabled'])
        else:
            enabled = [True for _ in size]
        transparency = json.loads(imported['transparency'])
        if 'is_array' in imported:
            is_array = json.loads(imported['is_array'])
        else:
            is_array = [False for _ in size]

        for i in range(number_imported):
            self.add_image(image_src[i], description[i], centre_sx_sy[i], rotation[i],
                           size[i], pixel_size[i], enabled[i], transparency[i], is_array[i])

    def save_to_cfg(self):
        imported = self.cfg['imported']
        imported['number_imported'] = str(len(self))
        imported['image_src'] = json.dumps(
            [image.image_src for image in self])
        imported['description'] = json.dumps(
            [image.description for image in self])
        imported['centre_sx_sy'] = str(
            [round_xy(img.centre_sx_sy)
             for img in self])
        imported['rotation'] = str(
            [img.rotation for img in self])
        imported['size'] = str(
            [img.size for img in self])
        imported['pixel_size'] = str(
            [img.pixel_size for img in self])
        imported['enabled'] = json.dumps(
            [image.enabled for image in self])
        imported['transparency'] = str(
            [img.transparency for img in self])
        imported['is_array'] = json.dumps(
            [image.is_array for image in self])

    def add_image(self, image_src, description, centre_sx_sy, rotation,
                  size, pixel_size, enabled, transparency, is_array=False):
        new_imported_image = ImportedImage(image_src, description, centre_sx_sy, rotation,
                                           size, pixel_size, enabled, transparency, is_array)
        self.append(new_imported_image)
        return new_imported_image

    def delete_image(self, index):
        """Delete the imported image at index"""
        del self[index]

    def delete_all_images(self):
        """Delete all imported images"""
        while len(self) > 0:
            self.delete_image(-1)

    def find_array_image(self):
        for imported_image in self:
            if imported_image.is_array:
                return imported_image
        return None
