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

from PyQt5.QtGui import QPixmap, QTransform

import utils


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

    def _load_image(self):
        # Load image as QPixmap
        if os.path.isfile(self.image_src):
            try:
                self.image = QPixmap(self.image_src)
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



class ImportedImages:

    def __init__(self, config):
        self.cfg = config
        self.number_imported = int(self.cfg['imported']['number_imported'])

        # Load parameters from session configuration
        image_src = json.loads(self.cfg['imported']['image_src'])
        description = json.loads(self.cfg['imported']['description'])
        centre_sx_sy = json.loads(self.cfg['imported']['centre_sx_sy'])
        rotation = json.loads(self.cfg['imported']['rotation'])
        size = json.loads(self.cfg['imported']['size'])
        pixel_size = json.loads(self.cfg['imported']['pixel_size'])
        transparency = json.loads(self.cfg['imported']['transparency'])

        # Create ImportedImage objects
        self.__imported_images = []
        for i in range(self.number_imported):
            imported_img = ImportedImage(image_src[i], description[i],
                                         centre_sx_sy[i], rotation[i],
                                         size[i], pixel_size[i],
                                         transparency[i])
            self.__imported_images.append(imported_img)

    def __getitem__(self, index):
        """Return the ImportedImage object selected by index."""
        if index < self.number_imported:
            return self.__imported_images[index]
        else:
            return None

    def save_to_cfg(self):
        self.cfg['imported']['number_imported'] = str(self.number_imported)
        self.cfg['imported']['image_src'] = json.dumps(
            [img.image_src for img in self.__imported_images])
        self.cfg['imported']['description']= json.dumps(
            [img.description for img in self.__imported_images])
        self.cfg['imported']['centre_sx_sy']= str(
            [utils.round_xy(img.centre_sx_sy)
             for img in self.__imported_images])
        self.cfg['imported']['rotation']= str(
            [img.rotation for img in self.__imported_images])
        self.cfg['imported']['size']= str(
            [img.size for img in self.__imported_images])
        self.cfg['imported']['pixel_size']= str(
            [img.pixel_size for img in self.__imported_images])
        self.cfg['imported']['transparency']= str(
            [img.transparency for img in self.__imported_images])

    def add_image(self):
        new_index = self.number_imported
        new_image = ImportedImage(image_src='', description='',
                                  centre_sx_sy=[0, 0], rotation=0,
                                  size=[1000, 1000], pixel_size=10,
                                  transparency=0)
        self.__imported_images.append(new_image)
        self.number_imported += 1

    def delete_image(self, index):
        """Delete the imported image at index"""
        self.number_imported -= 1
        del self.__imported_images[index]

    def delete_all_images(self):
        """Delete all imported images"""
        if self.number_imported>0:
            for id in range(self.number_imported):
                self.delete_image(self.number_imported - id - 1)

    def get_imported_img_file_list(self):
        return self.imported_file_list

    def get_imported_img_file_name_list(self):
        return [os.path.basename(s) for s in self.imported_file_list]


