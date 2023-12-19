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

from image_io import imread_metadata, imread
from utils import round_xy, uint8_image, color_image, norm_image_quantiles, image_to_QPixmap


class ImportedImage:
    def __init__(self, image_src, description, centre_sx_sy, rotation,
                 size, pixel_size, transparency):
        self._image_src = image_src   # Path to image file
        self.description = description
        self.centre_sx_sy = centre_sx_sy
        self._rotation = rotation
        self.size = size
        self.pixel_size = pixel_size
        self.transparency = transparency
        self._load_image()

    def __del__(self):
        os.remove(self._image_src)

    def _load_image(self):
        # Load image as QPixmap
        if os.path.isfile(self.image_src):
            try:
                image = norm_image_quantiles(imread(self.image_src))
                height, width = image.shape[:2]
                self.size = [width, height]
                self.image = image_to_QPixmap(image)
                pixel_size_um = imread_metadata(self.image_src).get('pixel_size', [])
                if len(pixel_size_um) > 0:
                    self.pixel_size = pixel_size_um[0] * 1000     # [um] -> [nm]
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
        

class ImportedImages:

    def __init__(self, config):
        self.cfg = config
        self.number_imported = 0
        imported = self.cfg['imported']
        number_imported = int(imported['number_imported'])

        # Load parameters from session configuration
        image_src = json.loads(imported['image_src'])
        description = json.loads(imported['description'])
        centre_sx_sy = json.loads(imported['centre_sx_sy'])
        rotation = json.loads(imported['rotation'])
        size = json.loads(imported['size'])
        pixel_size = json.loads(imported['pixel_size'])
        transparency = json.loads(imported['transparency'])

        # Create ImportedImage objects
        self.__imported_images = []
        for i in range(number_imported):
            self.add_image(image_src[i], description[i], centre_sx_sy[i], rotation[i],
                           size[i], pixel_size[i], transparency[i])

    def __getitem__(self, index):
        """Return the ImportedImage object selected by index."""
        if index < self.number_imported:
            return self.__imported_images[index]
        else:
            return None

    def save_to_cfg(self):
        self.cfg['imported']['number_imported'] = str(self.number_imported)
        self.cfg['imported']['image_src'] = json.dumps(
            [image.image_src for image in self.__imported_images])
        self.cfg['imported']['description'] = json.dumps(
            [image.description for image in self.__imported_images])
        self.cfg['imported']['centre_sx_sy'] = str(
            [round_xy(img.centre_sx_sy)
             for img in self.__imported_images])
        self.cfg['imported']['rotation'] = str(
            [img.rotation for img in self.__imported_images])
        self.cfg['imported']['size'] = str(
            [img.size for img in self.__imported_images])
        self.cfg['imported']['pixel_size'] = str(
            [img.pixel_size for img in self.__imported_images])
        self.cfg['imported']['transparency'] = str(
            [img.transparency for img in self.__imported_images])

    def add_image(self, image_src, description, centre_sx_sy, rotation,
                  size, pixel_size, transparency):
        new_imported_image = ImportedImage(image_src, description, centre_sx_sy, rotation,
                                           size, pixel_size, transparency)
        self.__imported_images.append(new_imported_image)
        self.number_imported += 1
        return new_imported_image

    def delete_image(self, index):
        """Delete the imported image at index"""
        del self.__imported_images[index]
        self.number_imported -= 1

    def delete_all_images(self):
        """Delete all imported images"""
        while self.__imported_images:
            self.delete_image(-1)
