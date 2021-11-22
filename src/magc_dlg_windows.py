# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module contains several MagC dialogs."""

import os
import re
import string
import threading
import datetime
import glob
import json
import validators
import csv
import requests
import shutil
import yaml

from random import random
from time import sleep, time, strftime, localtime
from PIL import Image
from skimage.io import imread
from skimage.feature import register_translation
import numpy as np
from imreg_dft import translation
from zipfile import ZipFile

from viewport_dlg_windows import ImportImageDlg

from PyQt5.uic import loadUi
from PyQt5.QtCore import Qt, QObject, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon, QPalette, QColor, QFont, \
    QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, \
    QFileDialog, QLineEdit, QDialogButtonBox, QHeaderView, QPushButton

import utils
import acq_func

import magc_utils

GRAY = QColor(Qt.lightGray)
GREEN = QColor(Qt.green)
YELLOW = QColor(Qt.yellow)

class ImportMagCDlg(QDialog):
    """Import MagC metadata."""

    def __init__(self, acq, grid_manager, sem, imported,
                 coordinate_system, gui_items, main_controls_trigger):
        super().__init__()
        self.acq = acq
        self.gm = grid_manager
        self.sem = sem
        self.imported = imported
        self.cs = coordinate_system
        self.gui_items = gui_items
        self.main_controls_trigger = main_controls_trigger
        self.target_dir = os.path.join(
            self.acq.base_dir, 'overviews', 'imported')
        loadUi(os.path.join(
            '..', 'gui', 'import_magc_metadata_dlg.ui'),
            self)
        self.default_magc_path = os.path.join(
            '..', 'magc', 'example', 'wafer_example1.magc')
        self.lineEdit_fileName.setText(self.default_magc_path)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon(os.path.join(
            '..', 'img', 'icon_16px.ico')))
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(
            QIcon(os.path.join('..','img','selectdir.png')))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))
        self.setFixedSize(self.size())
        self.pushButton_import.accepted.connect(self.import_magc)
        self.pushButton_import.rejected.connect(self.accept)
        store_res_list = [
            '%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_frameSize.addItems(store_res_list)
        self.comboBox_frameSize.setCurrentIndex(3)
        if 'multisem' in self.sem.device_name.lower():
            self.comboBox_frameSize.setEnabled(False)
            self.comboBox_frameSize.setCurrentIndex(0)
            self.spinBox_rows.setEnabled(False)
            self.spinBox_cols.setEnabled(False)
            self.spinBox_rows.setValue(1)
            self.spinBox_cols.setValue(1)
        self.show()

    def import_magc(self):
        #-----------------------------
        # read sections from MagC file (.magc, .ini based)
        magc_path = os.path.normpath(
            self.lineEdit_fileName.text())
        if not os.path.isfile(magc_path):
            msg = ('The .magc file could not be found '
                f'with the following path: {magc_path}')
            utils.log_info(
                'MagC-CTRL',
                msg)
            QMessageBox.critical(self, 'Warning', msg)
            self.accept()
            return
        elif not magc_path.endswith('.magc'):
            msg = 'The file chosen should be in .magc format.'
            utils.log_info(
                'MagC-CTRL',
                msg)
            QMessageBox.critical(self, 'Warning', msg)
            self.accept()
            return

        self.main_controls_trigger.transmit('MAGC RESET')
        magc = magc_utils.read_magc(magc_path)

        # load ROIs updated by user manually
        if self.checkBox.isChecked():
            if not magc['sbemimage_sections']:
                msg = ('The .magc file does not contain information from a previous'
                    ' SBEMimage session. Please try another file, or uncheck the option'
                    ' in the import dialog.')
                utils.log_info(
                    'MagC-CTRL',
                    msg)
                QMessageBox.critical(self, 'Warning', msg)
                return
            else:
                utils.log_info(
                    'MagC-CTRL',
                    f'{len(magc["sbemimage_sections"])} MagC sections have been loaded.')
        else:
            utils.log_info(
                'MagC-CTRL',
                f'{len(magc["sections"])} MagC sections have been loaded.')
        #-----------------------------

        #-----------------------------------------
        # populate the grids and the section_table
        frame_size_selector = self.comboBox_frameSize.currentIndex()
        pixel_size = self.doubleSpinBox_pixelSize.value()
        tile_overlap = self.doubleSpinBox_tileOverlap.value()

        table_view = self.gui_items['section_table']
        table_model = table_view.model()

        table_model.clear()
        table_model.setHorizontalHeaderItem(
            0, QStandardItem('Section'))
        table_model.setHorizontalHeaderItem(
            1, QStandardItem('State'))
        header = table_view.horizontalHeader()
        for i in range(2):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)

        # self.gm.magc_delete_autofocus_points(0)
        # self.gm[0].magc_polyroi_points_source = [
            # (-10, 0),
            # ( 10, 0),
            # ( 10, 20),
            # (-10, 20)]

        self.gm[0].origin_sx_sy = [0,0]

        if self.checkBox.isChecked():
            number_grids = len(magc['sbemimage_sections'])
        else:
            number_grids = len(magc['sections'])
        for s in range(number_grids-1):
            self.gm.add_new_grid([0, 0])

        if self.checkBox.isChecked():
            keys = magc['sbemimage_sections'].keys()
        else:
            keys = magc['sections'].keys()

        for key in keys:
            if self.checkBox.isChecked():
                section = magc['sbemimage_sections'][key]
            else:
                # use the ROI if present, else use the section
                try:
                    section = magc['rois'][key]
                except KeyError:
                    section = magc['sections'][key]

            self.gm[key].auto_update_tile_positions = False
            self.gm[key].size = [
                self.spinBox_rows.value(),
                self.spinBox_cols.value()]
            self.gm[key].display_colour = 1
            self.gm[key].frame_size_selector = frame_size_selector
            self.gm[key].pixel_size = pixel_size
            self.gm[key].overlap = tile_overlap
            self.gm[key].activate_all_tiles()
            self.gm[key].rotation = (0 - section['angle']) % 360
            # Update tile positions after initializing all grid attributes
            self.gm[key].update_tile_positions()
            # centre must be finally set after updating tile positions
            self.gm[key].auto_update_tile_positions = True
            self.gm[key].centre_sx_sy = section['center']

            # load autofocus points
            if (self.checkBox.isChecked() and magc['sbemimage_sections']):
                if 'focus' in magc['sbemimage_sections'][key]:
                    self.gm[key].magc_autofocus_points_source = magc['sbemimage_sections'][key]['focus']
                    # for point in magc['sbemimage_sections'][key]['focus']:
                        # self.gm.magc_add_autofocus_point(
                            # key,
                            # point)

            elif key in magc['focus']:
                for point in magc['focus'][key]['polygon']:
                    self.gm.magc_add_autofocus_point(
                        key,
                        point)

            # self.gm[key].magc_polyroi_points_source = [
                # (-10, 0),
                # ( 10, 0),
                # ( 10, 20),
                # (-10, 20)]

            # populate the section_table
            item1 = QStandardItem(str(key))
            item1.setCheckable(True)
            item2 = QStandardItem('')
            item2.setBackground(GRAY)
            item2.setCheckable(False)
            item2.setSelectable(False)
            table_model.appendRow([item1, item2])
            table_view.setRowHeight(key, 40)
        #-----------------------------------------

        #------------------------------
        # Update config with MagC items
        self.gm.magc = magc
        # todo: does importing a new magc file always require
        # a wafer_calibration ?
        #------------------------------

        # enable wafer configuration buttons
        self.main_controls_trigger.transmit('MAGC WAFER NOT CALIBRATED')
        self.main_controls_trigger.transmit('MAGC ENABLE WAFER IMAGE IMPORT')
        
        if len(magc['landmarksEM']['source']) > 2:
            self.main_controls_trigger.transmit('MAGC ENABLE CALIBRATION')

        self.main_controls_trigger.transmit('DRAW VP')
        self.accept()

    def select_file(self):
        start_path = f'C:{os.sep}'
        selected_file = str(QFileDialog.getOpenFileName(
                self, 'Select MagC metadata file',
                start_path,
                'MagC files (*.magc)'
                )[0])
        if len(selected_file) > 0:
            selected_file = os.path.normpath(selected_file)
            self.lineEdit_fileName.setText(selected_file)

    def accept(self):
        super(ImportMagCDlg, self).accept()

#------------------------------------------------------------------------------

class ImportWaferImageDlg(QDialog):
    """Import a wafer image into the viewport for MagC."""

    def __init__(self, acq, imported, wafer_im_dir,
                 main_controls_trigger):
        super().__init__()
        self.acq = acq
        self.imported = imported
        self.main_controls_trigger = main_controls_trigger
        self.imported_dir = os.path.join(
            self.acq.base_dir, 'overviews', 'imported')
        self.wafer_im_dir = wafer_im_dir

        import_img_dlg = ImportImageDlg(
            self.imported,
            self.imported_dir)
        import_img_dlg.doubleSpinBox_pixelSize.setEnabled(False)
        import_img_dlg.doubleSpinBox_pixelSize.setValue(1000)
        import_img_dlg.doubleSpinBox_posX.setEnabled(False)
        import_img_dlg.doubleSpinBox_posY.setEnabled(False)
        import_img_dlg.spinBox_rotation.setEnabled(False)

        # pre-filling the ImportImageDialog if wafer image (unique) present
        im_names = [im_name for im_name in os.listdir(self.wafer_im_dir)
            if ('wafer' in im_name.lower())
                and (os.path.splitext(im_name)[1] in ['.tif', '.png', '.jpg'])]
        if len(im_names) == 0:
            utils.log_info(
                'MagC-CTRL',
                ('No wafer picture was found. '
                    + 'Select the wafer image manually.'))
        elif len(im_names) > 1:
            utils.log_info(
                'MagC-CTRL',
                ('There is more than one image available in the folder '
                    + 'containing the .magc section description file.'
                    + 'Select the wafer image manually'))
        elif len(im_names) == 1:
            # pre-fill the import dialog
            im_path = os.path.normpath(
                os.path.join(self.wafer_im_dir, im_names[0]))
            import_img_dlg.lineEdit_fileName.setText(im_path)
            import_img_dlg.lineEdit_name.setText(
                os.path.splitext(
                    os.path.basename(im_path))[0])

        current_imported_number = self.imported.number_imported
        if import_img_dlg.exec_():
            pass

        if self.imported.number_imported == current_imported_number:
            utils.log_info(
                'MagC-CTRL',
                ('You have not added a wafer image overview.'
                    + 'You can still do it by selecting "Import Wafer Image"'
                    + 'in the MagC tab.'))
        else:
            wafer_im = self.imported[-1]
            width, height = wafer_im.size
            wafer_im.pixel_size = 1000
            wafer_im.centre_sx_sy = [width//2, height//2]
            self.main_controls_trigger.transmit('SHOW IMPORTED')
            self.main_controls_trigger.transmit('DRAW VP')
            utils.log_info(
                'MagC-CTRL',
                'Wafer image succesfully imported.')

#------------------------------------------------------------------------------

class WaferCalibrationDlg(QDialog):
    """Wafer calibration."""

    def __init__(self, config, stage, ovm, cs, gm, imported, main_controls_trigger):
        super().__init__()
        self.cfg = config
        self.stage = stage
        self.ovm = ovm
        self.cs = cs
        self.gm = gm
        self.imported = imported
        self.main_controls_trigger = main_controls_trigger
        loadUi(os.path.join('..', 'gui', 'wafer_calibration_dlg.ui'), self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon(os.path.join('..', 'img', 'icon_16px.ico')))
        self.setFixedSize(self.size())
        self.lTable = self.tableView_magc_landmarkTable
        self.initLandmarkList()
        self.pushButton_cancel.clicked.connect(self.accept)
        self.pushButton_validateCalibration.clicked.connect(
            self.validate_calibration)
        self.show()

    def initLandmarkList(self):

        # initialize the landmarkTableModel (QTableView)
        landmark_model = QStandardItemModel(0, 0)
        landmark_model.setHorizontalHeaderItem(0, QStandardItem(' Landmark '))
        landmark_model.setHorizontalHeaderItem(1, QStandardItem(' Source X '))
        landmark_model.setHorizontalHeaderItem(2, QStandardItem(' Source Y '))
        landmark_model.setHorizontalHeaderItem(3, QStandardItem('Target X'))
        landmark_model.setHorizontalHeaderItem(4, QStandardItem('Target Y'))
        landmark_model.setHorizontalHeaderItem(5, QStandardItem('Set'))
        landmark_model.setHorizontalHeaderItem(6, QStandardItem('Move'))
        landmark_model.setHorizontalHeaderItem(7, QStandardItem('Clear'))
        self.lTable.setModel(landmark_model)

        header = self.lTable.horizontalHeader()
        for i in range(8):
            if i not in [3,4]: # fixed width for target columns
                header.setSectionResizeMode(
                    i, QHeaderView.ResizeToContents)

        self.lTable.setColumnWidth(3, 70)
        self.lTable.setColumnWidth(4, 70)
        self.lTable.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)

        landmark_model = self.lTable.model()

        for id_lmk,key in enumerate(
                        sorted(
                            self.gm.magc['landmarksEM']['source'])):

            # the target key does not exist until it is either
            # manually defined
            # or inferred when enough (>=2) other target landmarks
            # have been defined

            item0 = QStandardItem(f'{key}')
            item1 = QStandardItem(
                f'{self.gm.magc["landmarksEM"]["source"][key][0]:.3f}')
            item2 = QStandardItem(
                f'{self.gm.magc["landmarksEM"]["source"][key][1]:.3f}')

            item5 = QPushButton('Set')
            item5.setFixedSize(QSize(50, 40))
            item5.clicked.connect(self.set_landmark(id_lmk))

            item6 = QPushButton('Go to')
            item6.setFixedSize(QSize(60, 40))
            item6.clicked.connect(self.goto_landmark(id_lmk))

            if self.cfg['sys']['simulation_mode'] == 'True':
                item5.setEnabled(False)
                item6.setEnabled(False)

            item7 = QPushButton('Clear')
            item7.setFixedSize(QSize(60, 40))
            item7.clicked.connect(self.clear_landmark(id_lmk))

            if key in self.gm.magc['landmarksEM']['target']:
                item0.setBackground(GREEN)

                item3 = QStandardItem(
                    f'{self.gm.magc["landmarksEM"]["target"][key][0]:.3f}')
                item3.setBackground(GREEN)

                item4 = QStandardItem(
                    f'{self.gm.magc["landmarksEM"]["target"][key][1]:.3f}')
                item4.setBackground(GREEN)
            else:
                item0.setBackground(GRAY)

                item3 = QStandardItem('')
                item3.setBackground(GRAY)

                item4 = QStandardItem('')
                item4.setBackground(GRAY)

                item6.setEnabled(False)
                item7.setEnabled(False)

            item3.setCheckable(False)
            item4.setCheckable(False)

            landmark_model.appendRow([item0, item1, item2, item3, item4])
            self.lTable.setIndexWidget(landmark_model.index(id_lmk, 5), item5)
            self.lTable.setIndexWidget(landmark_model.index(id_lmk, 6), item6)
            self.lTable.setIndexWidget(landmark_model.index(id_lmk, 7), item7)

    def clear_landmark(self, row):
        def callback_clear_landmark():
            landmark_model = self.lTable.model()

            item3 = self.lTable.model().item(row, 3)
            item3.setData('', Qt.DisplayRole)
            item3.setBackground(GRAY)

            item4 = self.lTable.model().item(row, 4)
            item4.setData('', Qt.DisplayRole)
            item4.setBackground(GRAY)

            del self.gm.magc['landmarksEM']['target'][row]

            # update table
            item0 = self.lTable.model().item(row, 0)
            item0.setBackground(GRAY)

            item6 = self.lTable.indexWidget(landmark_model.index(row, 6))
            item6.setEnabled(False)

            item7 = self.lTable.indexWidget(landmark_model.index(row, 7))
            item7.setEnabled(False)

        return callback_clear_landmark

    def set_landmark(self, row):
        def callback_set_landmark():
            x,y = self.stage.get_xy()
            utils.log_info(
                'MagC-CTRL',
                f'Adding landmark ({x},{y})')
            landmark_model = self.lTable.model()

            # update table
            item0 = self.lTable.model().item(row, 0)
            item0.setBackground(GREEN)

            item3 = self.lTable.model().item(row, 3)
            item3.setData(
                f'{x:.3f}',
                Qt.DisplayRole)
            item3.setBackground(GREEN)

            item4 = self.lTable.model().item(row, 4)
            item4.setData(
                f'{y:.3f}',
                Qt.DisplayRole)
            item4.setBackground(GREEN)

            item6 = self.lTable.indexWidget(
                        landmark_model.index(
                            row,
                            6))
            item6.setEnabled(True)

            item7 = self.lTable.indexWidget(
                        landmark_model.index(
                            row,
                            7))
            item7.setEnabled(True)

            # update landmarks
            self.gm.magc['landmarksEM']['target'][row] = [x,y]

            # compute transform and update landmarks
            n_landmarks = len(self.gm.magc['landmarksEM']['source'])

            calibratedLandmarkIds = [
                id for id
                in self.gm.magc['landmarksEM']['source']
                if self.lTable.model().item(id, 0).background().color()==GREEN]

                # the green color shows that the landmark has been
                # manually calibrated by the user
                # if the landmark is yellow, it means that it has
                # only been inferred and not manually calibrated
                # here we are using only the manually calibrated landmarks
            noncalibratedLandmarkIds = (
                set(range(n_landmarks)) - set(calibratedLandmarkIds))
            utils.log_info(
                'MagC-DEBUG',
                f'calibratedLandmarkIds {calibratedLandmarkIds}')

            if len(calibratedLandmarkIds) > 1: # at least 2 landmarks needed
                # calculating the wafer transform from source to target.
                # Using all possible landmarks available in the target
                # (minimum 2)

                x_landmarks_source = np.array([
                    self.gm.magc['landmarksEM']['source'][i][0]
                    for i in range(n_landmarks)])
                y_landmarks_source = np.array([
                    self.gm.magc['landmarksEM']['source'][i][1]
                    for i in range(n_landmarks)])

                # taking only the source landmarks for which there is a
                # corresponding target landmark
                x_landmarks_source_partial = np.array(
                    [self.gm.magc['landmarksEM']['source'][i][0]
                     for i in calibratedLandmarkIds])
                y_landmarks_source_partial = np.array(
                    [self.gm.magc['landmarksEM']['source'][i][1]
                     for i in calibratedLandmarkIds])

                x_landmarks_target_partial = np.array(
                    [self.gm.magc['landmarksEM']['target'][i][0]
                     for i in calibratedLandmarkIds])
                y_landmarks_target_partial = np.array(
                    [self.gm.magc['landmarksEM']['target'][i][1]
                     for i in calibratedLandmarkIds])

                self.gm.magc['transform'] = magc_utils.rigidT(
                    x_landmarks_source_partial, y_landmarks_source_partial,
                    x_landmarks_target_partial, y_landmarks_target_partial)[0]

                # compute all targetLandmarks
                x_target_updated_landmarks, y_target_updated_landmarks = (
                    magc_utils.applyRigidT(
                        x_landmarks_source,
                        y_landmarks_source,
                        self.gm.magc['transform']))

                # x_target_updated_landmarks = -x_target_updated_landmarks
                # x axis flipping on Merlin?

                # set the new target landmarks that were missing
                for noncalibratedLandmarkId in noncalibratedLandmarkIds:
                    x = x_target_updated_landmarks[noncalibratedLandmarkId]
                    y = y_target_updated_landmarks[noncalibratedLandmarkId]
                    # (self.cs.magc_landmarks
                        # [str(noncalibratedLandmarkId)]['target']) = [x,y]
                    self.gm.magc['landmarksEM']['target'][noncalibratedLandmarkId] = [x,y]

                    item0 = self.lTable.model().item(
                        noncalibratedLandmarkId,
                        0)
                    item0.setBackground(YELLOW)

                    item3 = self.lTable.model().item(
                        noncalibratedLandmarkId,
                        3)
                    item3.setData(
                        f'{x:.3f}',
                        Qt.DisplayRole)
                    item3.setBackground(YELLOW)

                    item4 = self.lTable.model().item(
                        noncalibratedLandmarkId,
                        4)
                    item4.setData(
                        f'{y:.3f}',
                        Qt.DisplayRole)
                    item4.setBackground(YELLOW)

                    item6 = self.lTable.indexWidget(
                                landmark_model.index(
                                    noncalibratedLandmarkId,
                                    6))
                    item6.setEnabled(True)

                    item7 = self.lTable.indexWidget(
                                landmark_model.index(
                                    noncalibratedLandmarkId,
                                    7))
                    item7.setEnabled(True)

        return callback_set_landmark

    def goto_landmark(self, row):
        def callback_goto_landmark():
            item3 = self.lTable.model().item(row, 3)
            item4 = self.lTable.model().item(row, 4)
            x = float(self.lTable.model().data(item3.index()))
            y = float(self.lTable.model().data(item4.index()))

            utils.log_info(
                'MagC-STAGE',
                f'Landmark: moving stage to ({x},{y})')
            self.stage.move_to_xy([x,y])
            # xxx move viewport
            # self.cs.set_mv_centre_d(
            #     self.cs.get_grid_origin_d(grid_number=row))
            # self.main_controls_trigger.transmit('DRAW VP')

        return callback_goto_landmark

    def validate_calibration(self):
        calibratedLandmarkIds = [
            id for id
            in self.gm.magc['landmarksEM']['source']
            if self.lTable.model().item(id, 0).background().color()==GREEN]

        n_landmarks = len(self.gm.magc['landmarksEM']['source'])

        if len(calibratedLandmarkIds) != n_landmarks:
            utils.log_info(
                'MagC-CTRL',
                ('Cannot validate wafer calibration: all target landmarks '
                    +'must first be validated.'))
        else:
            x_landmarks_source = [
                self.gm.magc['landmarksEM']['source'][i][0]
                for i in range(n_landmarks)]
            y_landmarks_source = [
                self.gm.magc['landmarksEM']['source'][i][1]
                for i in range(n_landmarks)]

            x_landmarks_target = [
                self.gm.magc['landmarksEM']['target'][i][0]
                for i in range(n_landmarks)]
            y_landmarks_target = [
                self.gm.magc['landmarksEM']['target'][i][1]
                for i in range(n_landmarks)]

            utils.log_info(
                'MagC-DEBUG',
                ('x_landmarks_source, y_landmarks_source, x_landmarks_target, '
                  'y_landmarks_target ' + str((x_landmarks_source, y_landmarks_source,
                  x_landmarks_target, y_landmarks_target))))

            self.gm.magc['transform'] = magc_utils.affineT(
                x_landmarks_source, y_landmarks_source,
                x_landmarks_target, y_landmarks_target)

            utils.log_info(
                'MagC-DEBUG',
                f'waferTransform {self.gm.magc["transform"]}')

            # compute new grid locations
            # (always transform from reference source)
            n_sections = len(self.gm.magc['sections'])
            utils.log_info(
                'MagC-DEBUG',
                f'n_sections {n_sections}')

            x_source = np.array(
                [self.gm.magc['sections'][k]['center'][0]
                    for k in sorted(self.gm.magc['sections'])])
            y_source = np.array(
                [self.gm.magc['sections'][k]['center'][1]
                    for k in sorted(self.gm.magc['sections'])])

            x_target, y_target = magc_utils.applyAffineT(
                x_source,
                y_source,
                self.gm.magc['transform'])

            transformAngle = -magc_utils.getAffineRotation(
                self.gm.magc['transform'])
            angles_target = [
                (180 - self.gm.magc['sections'][k]['angle'] + transformAngle) % 360
                for k in sorted(self.gm.magc['sections'])]

            # update grids
            utils.log_info(
                'MagC-DEBUG',
                f'self.gm.number_grids: {self.gm.number_grids}')
            for grid_number in range(self.gm.number_grids):

                self.gm[grid_number].rotation = angles_target[grid_number]

                self.gm[grid_number].centre_sx_sy = [
                    x_target[grid_number],
                    y_target[grid_number]]
                self.gm[grid_number].update_tile_positions()

            self.main_controls_trigger.transmit('DRAW VP')

            # update wafer picture
            if self.imported[0] is not None:
                waferTransformAngle = -magc_utils.getAffineRotation(
                    self.gm.magc['transform'])
                waferTransformScaling = magc_utils.getAffineScaling(
                    self.gm.magc['transform'])

                im_center_target_s = magc_utils.applyAffineT(
                    [self.imported[0].centre_sx_sy[0]],
                    [self.imported[0].centre_sx_sy[1]],
                    self.gm.magc['transform'])

                im_center_target_s = [float(a[0]) for a in im_center_target_s]

                # im_center_source_v = self.cs.convert_to_v(im_center_source_s)
                # im_center_target_v = magc_utils.applyRigidT(
                    # [im_center_source_v[0]],
                    # [im_center_source_v[1]],
                    # waferTransform_v)

                self.imported[0].rotation = waferTransformAngle % 360
                self.imported[0].pixel_size = 1000 * waferTransformScaling

                self.imported[0].centre_sx_sy = im_center_target_s

            # update drawn image
            self.main_controls_trigger.transmit('DRAW VP')

            # update calibration flag
            self.gm.magc['calibrated'] = True
            self.main_controls_trigger.transmit('MAGC WAFER CALIBRATED')

            self.accept()

    def accept(self):
        super().accept()

class ImportZENExperimentDlg(QDialog):
    """Import a ZEN experiment setup."""

    def __init__(self, msem_variables, main_controls_trigger):
        super().__init__()
        self.msem_variables = msem_variables
        self.main_controls_trigger = main_controls_trigger
        loadUi(os.path.join(
            '..', 'gui', 'import_zen_dlg.ui'),
            self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon(os.path.join(
            '..', 'img', 'icon_16px.ico')))
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(
            QIcon(os.path.join('..','img','selectdir.png')))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))
        self.setFixedSize(self.size())
        self.buttonBox.accepted.connect(self.import_zen)
        self.buttonBox.rejected.connect(self.accept)
        self.show()

    def import_zen(self):
        #-----------------------------
        # read sections from zen .json experiment file
        selected_file = os.path.normpath(
            self.lineEdit_fileName.text())

        if not os.path.isfile(selected_file):
            utils.log_info(
                'MagC-CTRL',
                'ZEN input file not found')
            self.accept()
            return
        elif os.path.splitext(selected_file)[1] != '.json':
            utils.log_info(
                'MagC-CTRL',
                'The file chosen should be in .json format')
            self.accept()
            return

        # update zen experiment flag
        self.main_controls_trigger.transmit(
            'MSEM GUI-'
            + os.path.join(
                os.path.basename(
                    os.path.dirname(selected_file)),
                os.path.basename(selected_file))
            + '-green-'
            + os.path.splitext(
                self.output_name(selected_file))[0])

        self.msem_variables['zen_input_path'] = selected_file

    def output_name(self, path):
        name = os.path.splitext(os.path.basename(path))[0]
        output = (
            name
            + '_from_SBEMimage_'
            + strftime("%Y_%m_%d_%H_%M_%S", localtime())
            + '.json')
        return output

    def select_file(self):
        start_path = 'C:\\'
        selected_file = str(QFileDialog.getOpenFileName(
                self, 'Select ZEN experiment file',
                start_path,
                'ZEN experiment setup (*.json)'
                )[0])
        if len(selected_file) > 0:
            selected_file = os.path.normpath(selected_file)
            if os.path.splitext(selected_file)[1] == '.json':
                self.lineEdit_fileName.setText(selected_file)

    def accept(self):
        super(ImportZENExperimentDlg, self).accept()