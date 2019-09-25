# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module contains all magc components that can be put outside the core of SBEMImage."""

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
from time import sleep, time
from queue import Queue
from PIL import Image
from skimage.io import imread
from skimage.feature import register_translation
import numpy as np
from imreg_dft import translation
from zipfile import ZipFile

from PyQt5.uic import loadUi
from PyQt5.QtCore import Qt, QObject, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon, QPalette, QColor, QFont, \
                        QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, \
                            QFileDialog, QLineEdit, QDialogButtonBox, \
                            QHeaderView, QPushButton

import utils
import acq_func

class ImportMagCDlg(QDialog):
    """Import MagC metadata."""

    def __init__(self, config, grid_manager, coordinate_system, stage, sem, ovm, viewport, gui_items, trigger, queue):
        super().__init__()
        self.gm = grid_manager
        self.stage = stage
        self.cs = coordinate_system
        self.gui_items = gui_items
        self.trigger = trigger
        self.queue = queue
        self.cfg = config
        self.sem = sem
        self.ovm = ovm
        self.viewport = viewport
        self.target_dir = os.path.join(self.cfg['acq']['base_dir'], 'overviews', 'imported')
        loadUi(os.path.join('..', 'gui', 'import_magc_metadata_dlg.ui'), self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon(os.path.join('..', 'img', 'icon_16px.ico')))
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(QIcon(os.path.join('..','img','selectdir.png')))
        self.pushButton_selectFile.setIcon(QIcon(os.path.join('..', 'img', 'selectdir.png')))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))
        self.setFixedSize(self.size())
        self.pushButton_import.accepted.connect(self.import_metadata)
        self.pushButton_import.rejected.connect(self.accept)
        store_res_list = [
            '%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_tileSize.addItems(store_res_list)
        self.comboBox_tileSize.setCurrentIndex(5)
        self.show()

    def add_to_main_log(self, msg):
        """Add entry to the log in the main window"""
        msg = utils.format_log_entry(msg)
        # Send entry to main window via queue and trigger:
        self.queue.put(msg)
        self.trigger.s.emit()

    def import_metadata(self):
        color_not_acquired = QColor(Qt.lightGray)
        color_acquired = QColor(Qt.green)
        color_acquiring = QColor(Qt.yellow)
        #-----------------------------
        # read sections from MagC JSON
        file_name = self.lineEdit_fileName.text()
        if not os.path.isfile(file_name):
            self.add_to_main_log('MagC file not found')
        else:
            with open(file_name, 'r') as f:
                sectionsYAML = yaml.full_load(f)
            sections = {}
            landmarks = {}
            for sectionId, sectionXYA in sectionsYAML['tissue'].items():
                sections[int(sectionId)] = {
                'center': [float(a) for a in sectionXYA[:2]],
                'angle': float( (-sectionXYA[2] + 90) % 360)}
            if 'tissueROI' in sectionsYAML:
                tissueROIIndex = int(list(sectionsYAML['tissueROI'].keys())[0])
                sections['tissueROI-' + str(tissueROIIndex)] = {
                'center': sectionsYAML['tissueROI'][tissueROIIndex]}
            if 'landmarks' in sectionsYAML:
                for landmarkId, landmarkXY in sectionsYAML['landmarks'].items():
                    landmarks[int(landmarkId)] = {
                    'source': landmarkXY}
            n_sections = len([k for k in sections.keys() if str(k).isdigit()])
            self.add_to_main_log(str(n_sections) + ' MagC sections have been loaded.')
            #-----------------------------

            #--------------------------------------
            # import wafer overview if file present
            dir_sections = os.path.dirname(os.path.normpath(file_name))
            im_names = [im_name for im_name in os.listdir(dir_sections) if
                ('wafer' in im_name) and
                (os.path.splitext(im_name)[1] in ['.tif', '.png'])]
            if im_names == []:
                self.add_to_main_log('No wafer picture was found.')
            elif len(im_names) == 1:
                im_path = os.path.normpath(os.path.join(dir_sections, im_names[0]))

                selection_success = True
                selected_filename = os.path.basename(im_path)
                timestamp = str(datetime.datetime.now())
                # Remove some characters from timestamp to get valid file name:
                timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
                target_path = os.path.join(self.target_dir,
                               os.path.splitext(selected_filename)[0] +
                               '_' + timestamp + '.png')
                if os.path.isfile(im_path):
                    # Copy file to data folder as png:
                    try:
                        imported_img = Image.open(im_path)
                        imported_img.save(target_path)
                    except Exception as e:
                        QMessageBox.warning(
                            self, 'Error',
                            'Could not load image file.' + str(e),
                             QMessageBox.Ok)
                        selection_success = False

                    if selection_success:
                        new_img_number = self.ovm.get_number_imported()
                        self.ovm.add_imported_img()
                        width, height = imported_img.size
                        self.ovm.set_imported_img_file(
                            new_img_number, target_path)
                        self.ovm.set_imported_img_name(new_img_number,
                                                       selected_filename)
                        self.ovm.set_imported_img_size_px_py(
                            new_img_number, width, height)
                        self.ovm.set_imported_img_pixel_size(
                            new_img_number, 1000)
                        self.cs.set_imported_img_centre_s(
                            new_img_number,
                            [width//2, height//2])

                        self.viewport.mv_load_last_imported_image()
                        self.viewport.mv_draw()

                else:
                    QMessageBox.warning(self, 'Error',
                                        'Specified file not found.',
                                        QMessageBox.Ok)
                    selection_success = False
            else:
                self.add_to_main_log('There are more than 1 picture available in the folder containing the .magc section description file. Please place only one wafer picture (.tif) in the folder.')
            #--------------------------------------

            #---------------------------------------
            # populate the grids and the sectionList
            tile_size_selector = self.comboBox_tileSize.currentIndex()
            pixel_size = self.doubleSpinBox_pixelSize.value()

            sectionListModel = self.gui_items['sectionList'].model()
            sectionListModel.clear()
            sectionListModel.setHorizontalHeaderItem(0, QStandardItem('Section'))
            sectionListModel.setHorizontalHeaderItem(1, QStandardItem('State'))
            header = self.gui_items['sectionList'].horizontalHeader()
            for i in range(2):
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            header.setStretchLastSection(True)

            self.gm.delete_all_grids()
            for section in range(n_sections):
                self.gm.add_new_grid()
            for idx, section in sections.items():
                if str(idx).isdigit(): # to exclude tissueROI and landmarks
                    self.gm.set_grid_size(idx,
                                          (self.spinBox_rows.value(),
                                          self.spinBox_cols.value()))
                    self.gm.set_tile_size_selector(idx, tile_size_selector)
                    self.gm.set_pixel_size(idx, pixel_size)
                    self.gm.select_all_tiles(idx)
                    self.gm.calculate_grid_map(grid_number=idx)
                    self.gm.set_rotation(idx, (180-float(section['angle'])) % 360)
                    self.gm.set_grid_center_s(idx, list(map(float, section['center'])))

                    # populate the sectionList
                    item1 = QStandardItem(str(idx))
                    item1.setCheckable(True)
                    item2 = QStandardItem('')
                    item2.setBackground(color_not_acquired)
                    item2.setCheckable(False)
                    item2.setSelectable(False)
                    sectionListModel.appendRow([item1, item2])
            #---------------------------------------

            #---------------------------------------
            # Update config with MagC items
            self.cfg['sys']['magc_mode'] = 'True'
            self.cfg['magc']['sections'] = json.dumps(sections)
            self.cfg['magc']['selected_sections'] = '[]'
            self.cfg['magc']['checked_sections'] = '[]'
            self.cfg['magc']['landmarks'] = json.dumps(landmarks)
            # xxx does importing a new magc file always require a wafer_calibration ?
            # ---------------------------------------

            # enable wafer configuration button
            self.queue.put('MAGC ENABLE CALIBRATION')
            self.trigger.s.emit()
            self.queue.put('MAGC WAFER NOT CALIBRATED')
            self.trigger.s.emit()

        self.accept()

    def select_file(self):
        # # start_path = 'C:\\'
        # # selected_file = str(QFileDialog.getOpenFileName(
                # # self, 'Select MagC metadata file',
                # # start_path,
                # # 'MagC files (*.magc)'
                # # )[0])
        selected_file = os.path.join('..', 'magc_433_sections.magc')
        if len(selected_file) > 0:
            selected_file = os.path.normpath(selected_file)
            self.lineEdit_fileName.setText(selected_file)

    def accept(self):
        super(ImportMagCDlg, self).accept()

#------------------------------------------------------------------------------

class ImportWaferImageDlg(QDialog):
    """Import a wafer image into the viewport for MagC."""

    def __init__(self, ovm, cs, target_dir):
        self.ovm = ovm
        self.cs = cs
        self.target_dir = target_dir
        super().__init__()
        loadUi(os.path.join('..','gui','import_wafer_image_dlg.ui'), self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon(os.path.join('..','img','icon_16px.ico')))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(QIcon(os.path.join('..','img','selectdir.png')))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))

    def select_file(self):
        # Let user select image to be imported:
        start_path = os.getenv('SystemDrive')
        selected_file = str(QFileDialog.getOpenFileName(
                self, 'Select image',
                start_path,
                'Images (*.tif *.png *.bmp *.jpg)'
                )[0])
        if len(selected_file) > 0:
            selected_file = os.path.normpath(selected_file)
            self.lineEdit_fileName.setText(selected_file)

    def accept(self):
        selection_success = True
        selected_path = os.path.normpath(self.lineEdit_fileName.text())
        selected_filename = os.path.basename(selected_path)
        timestamp = str(datetime.datetime.now())
        # Remove some characters from timestamp to get valid file name:
        timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
        target_path = os.path.join(self.target_dir,
                       os.path.splitext(selected_filename)[0] +
                       '_' + timestamp + '.png')
        if os.path.isfile(selected_path):
            # Copy file to data folder as png:
            try:
                imported_img = Image.open(selected_path)
                imported_img.save(target_path)
            except Exception as e:
                QMessageBox.warning(
                    self, 'Error',
                    'Could not load image file.' + str(e),
                     QMessageBox.Ok)
                selection_success = False

            if selection_success:
                new_img_number = self.ovm.get_number_imported()
                self.ovm.add_imported_img()
                width, height = imported_img.size
                self.ovm.set_imported_img_file(
                    new_img_number, target_path)
                self.ovm.set_imported_img_name(new_img_number,
                                               selected_filename)
                self.ovm.set_imported_img_size_px_py(
                    new_img_number, width, height)
                self.ovm.set_imported_img_pixel_size(
                    new_img_number, 1000)
                self.cs.set_imported_img_centre_s(
                    new_img_number,
                    [width//2, height//2])
        else:
            QMessageBox.warning(self, 'Error',
                                'Specified file not found.',
                                QMessageBox.Ok)
            selection_success = False

        if selection_success:
            super().accept()

#------------------------------------------------------------------------------

class WaferCalibrationDlg(QDialog):
    """Wafer calibration."""

    def __init__(self, config, stage, ovm, cs, gm, viewport, queue, trigger):
        super().__init__()
        self.cfg = config
        self.stage = stage
        self.ovm = ovm
        self.cs = cs
        self.gm = gm
        self.viewport = viewport
        self.trigger = trigger
        self.queue = queue
        loadUi(os.path.join('..', 'gui', 'wafer_calibration_dlg.ui'), self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon(os.path.join('..', 'img', 'icon_16px.ico')))
        self.setFixedSize(self.size())
        self.lTable = self.tableView_magc_landmarkTable
        self.initLandmarkList()
        self.pushButton_cancel.clicked.connect(self.accept)
        self.pushButton_validateCalibration.clicked.connect(self.validate_calibration)
        self.show()

    def add_to_main_log(self, msg):
        """Add entry to the log in the main window"""
        msg = utils.format_log_entry(msg)
        # Send entry to main window via queue and trigger:
        self.queue.put(msg)
        self.trigger.s.emit()

    def initLandmarkList(self):

        # initialize the landmarkTableModel (QTableView)
        landmarkModel = QStandardItemModel(0, 0)
        landmarkModel.setHorizontalHeaderItem(0, QStandardItem(''))
        landmarkModel.setHorizontalHeaderItem(1, QStandardItem('Source x'))
        landmarkModel.setHorizontalHeaderItem(2, QStandardItem('Source y'))
        landmarkModel.setHorizontalHeaderItem(3, QStandardItem('Target x'))
        landmarkModel.setHorizontalHeaderItem(4, QStandardItem('Target y'))
        landmarkModel.setHorizontalHeaderItem(5, QStandardItem('Set'))
        landmarkModel.setHorizontalHeaderItem(6, QStandardItem('Move'))
        landmarkModel.setHorizontalHeaderItem(7, QStandardItem('Clear'))
        self.lTable.setModel(landmarkModel)

        header = self.lTable.horizontalHeader()
        for i in range(8):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        self.lTable.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        landmarkModel = self.lTable.model()
        landmarks = json.loads(self.cfg['magc']['landmarks'])
        for id, (key,sourceTarget) in enumerate(landmarks.items()):
            item0 = QStandardItem(str(key))

            item1 = QStandardItem(str(sourceTarget['source'][0]))

            item2 = QStandardItem(str(sourceTarget['source'][1]))

            item5 = QPushButton('Set')
            item5.setFixedSize(QSize(50, 40))
            item5.clicked.connect(self.set_landmark(id))

            item6 = QPushButton('Go to')
            item6.setFixedSize(QSize(60, 40))
            item6.clicked.connect(self.goto_landmark(id))

            if self.cfg['sys']['simulation_mode'] == 'True':
                item5.setEnabled(False)
                item6.setEnabled(False)

            item7 = QPushButton('Clear')
            item7.setFixedSize(QSize(60, 40))
            item7.clicked.connect(self.clear_landmark(id))

            if 'target' in sourceTarget:
                item0.setBackground(QColor(Qt.green))

                item3 = QStandardItem(str(sourceTarget['target'][0]))
                item3.setBackground(QColor(Qt.green))

                item4 = QStandardItem(str(sourceTarget['target'][1]))
                item4.setBackground(QColor(Qt.green))
            else:
                item0.setBackground(QColor(Qt.lightGray))

                item3 = QStandardItem('')
                item3.setBackground(QColor(Qt.lightGray))

                item4 = QStandardItem('')
                item4.setBackground(QColor(Qt.lightGray))

                item6.setEnabled(False)
                item7.setEnabled(False)

            item3.setCheckable(False)
            item4.setCheckable(False)

            landmarkModel.appendRow([item0, item1, item2, item3, item4])
            self.lTable.setIndexWidget(landmarkModel.index(id, 5), item5)
            self.lTable.setIndexWidget(landmarkModel.index(id, 6), item6)
            self.lTable.setIndexWidget(landmarkModel.index(id, 7), item7)

    def clear_landmark(self, row):
        def callback_clear_landmark():
            landmarks = json.loads(self.cfg['magc']['landmarks'])
            landmarkModel = self.lTable.model()

            item3 = self.lTable.model().item(row, 3)
            item3.setData('', Qt.DisplayRole)
            item3.setBackground(QColor(Qt.lightGray))

            item4 = self.lTable.model().item(row, 4)
            item4.setData('', Qt.DisplayRole)
            item4.setBackground(QColor(Qt.lightGray))

            del landmarks[str(row)]['target']

            # update table
            item0 = self.lTable.model().item(row, 0)
            item0.setBackground(QColor(Qt.lightGray))

            item6 = self.lTable.indexWidget(landmarkModel.index(row, 6))
            item6.setEnabled(False)

            item7 = self.lTable.indexWidget(landmarkModel.index(row, 7))
            item7.setEnabled(False)

            # update cfg
            self.cfg['magc']['landmarks'] = json.dumps(landmarks)

        return callback_clear_landmark

    def set_landmark(self, row):
        def callback_set_landmark():
            landmarks = json.loads(self.cfg['magc']['landmarks'])
            x,y = self.stage.get_xy()
            print('xlandmark, ylandmark', x, y)
            landmarkModel = self.lTable.model()

            # update table
            item0 = self.lTable.model().item(row, 0)
            item0.setBackground(QColor(Qt.green))

            item3 = self.lTable.model().item(row, 3)
            item3.setData(str(x), Qt.DisplayRole)
            item3.setBackground(QColor(Qt.green))

            item4 = self.lTable.model().item(row, 4)
            item4.setData(str(y), Qt.DisplayRole)
            item4.setBackground(QColor(Qt.green))

            item6 = self.lTable.indexWidget(landmarkModel.index(row, 6))
            item6.setEnabled(True)

            item7 = self.lTable.indexWidget(landmarkModel.index(row, 7))
            item7.setEnabled(True)

            # update landmarks
            landmarks[str(row)]['target'] = [x,y]

            # compute transform and update landmarks
            nLandmarks = len(landmarks)
            calibratedLandmarkIds = [int(id)
                for id,landmark
                in landmarks.items()
                # if 'target' in landmark]
                if self.lTable.model().item(int(id), 0).background().color() == QColor(Qt.green)]
            noncalibratedLandmarkIds = set(range(nLandmarks)) - set(calibratedLandmarkIds)
            print('calibratedLandmarkIds', calibratedLandmarkIds)


            if len(calibratedLandmarkIds) > 1: # at least 2 landmarks needed
                # calculating the wafer transform from source to target. Using all possible landmarks available in the target (minimum 2)

                x_landmarks_source = np.array([landmarks[str(i)]['source'][0]
                    for i in range(nLandmarks)])
                y_landmarks_source = np.array([landmarks[str(i)]['source'][1]
                    for i in range(nLandmarks)])

                # taking only the source landmarks for which there is a corresponding target landmark
                x_landmarks_source_partial = np.array([landmarks[str(i)]['source'][0]
                    for i in calibratedLandmarkIds])
                y_landmarks_source_partial = np.array([landmarks[str(i)]['source'][1]
                    for i in calibratedLandmarkIds])

                x_landmarks_target_partial = np.array([landmarks[str(i)]['target'][0]
                    for i in calibratedLandmarkIds])
                y_landmarks_target_partial = np.array([landmarks[str(i)]['target'][1]
                    for i in calibratedLandmarkIds])

                waferTransform = utils.rigidT(
                    x_landmarks_source_partial, y_landmarks_source_partial,
                    x_landmarks_target_partial, y_landmarks_target_partial)[0]

                # compute all targetLandmarks
                x_target_updated_landmarks, y_target_updated_landmarks = utils.applyRigidT(
                    x_landmarks_source, y_landmarks_source, waferTransform)

                # x_target_updated_landmarks = -x_target_updated_landmarks # x axis flipping on Merlin

                # set the new target landmarks that were missing
                for noncalibratedLandmarkId in noncalibratedLandmarkIds:
                    x = x_target_updated_landmarks[noncalibratedLandmarkId]
                    y = y_target_updated_landmarks[noncalibratedLandmarkId]
                    landmarks[str(noncalibratedLandmarkId)]['target'] = [x,y]

                    item0 = self.lTable.model().item(noncalibratedLandmarkId, 0)
                    item0.setBackground(QColor(Qt.yellow))

                    item3 = self.lTable.model().item(noncalibratedLandmarkId, 3)
                    item3.setData(str(x), Qt.DisplayRole)
                    item3.setBackground(QColor(Qt.yellow))

                    item4 = self.lTable.model().item(noncalibratedLandmarkId, 4)
                    item4.setData(str(y), Qt.DisplayRole)
                    item4.setBackground(QColor(Qt.yellow))

                    item6 = self.lTable.indexWidget(landmarkModel.index(noncalibratedLandmarkId, 6))
                    item6.setEnabled(True)

                    item7 = self.lTable.indexWidget(landmarkModel.index(noncalibratedLandmarkId, 7))
                    item7.setEnabled(True)


            # update cfg
            self.cfg['magc']['landmarks'] = json.dumps(landmarks)

        return callback_set_landmark

    def goto_landmark(self, row):
        def callback_goto_landmark():
            item3 = self.lTable.model().item(row, 3)
            item4 = self.lTable.model().item(row, 4)
            x = float(self.lTable.model().data(item3.index()))
            y = float(self.lTable.model().data(item4.index()))

            print('Landmark: moving to', x, y)
            self.stage.move_to_xy([x,y])
            # xxx move viewport
            # self.cs.set_mv_centre_d(self.cs.get_grid_origin_d(grid_number=row))
            # self.viewport.mv_draw()
        return callback_goto_landmark

    def validate_calibration(self):
        landmarks = json.loads(self.cfg['magc']['landmarks'])
        sections = json.loads(self.cfg['magc']['sections'])

        nLandmarks = len(landmarks)
        calibratedLandmarkIds = [int(id)
            for id,landmark
            in landmarks.items()
            if self.lTable.model().item(int(id), 0).background().color() == QColor(Qt.green)]

        if len(calibratedLandmarkIds) != nLandmarks:
            self.add_to_main_log(
            '''
            Cannot validate wafer calibration: all target landmarks must be validated
            ''')

        else:
            x_landmarks_source = [landmarks[str(i)]['source'][0]
                for i in range(len(landmarks))]
            y_landmarks_source = [landmarks[str(i)]['source'][1]
                for i in range(len(landmarks))]

            x_landmarks_target = [landmarks[str(i)]['target'][0]
                for i in range(len(landmarks))]
            y_landmarks_target = [landmarks[str(i)]['target'][1]
                for i in range(len(landmarks))]

            print('x_landmarks_source, y_landmarks_source, x_landmarks_target, y_landmarks_target', x_landmarks_source, y_landmarks_source, x_landmarks_target, y_landmarks_target)

            waferTransform = utils.affineT(
                x_landmarks_source, y_landmarks_source,
                x_landmarks_target, y_landmarks_target)

            print('waferTransform', waferTransform)
            self.cfg['magc']['wafer_transform'] = json.dumps(waferTransform.tolist())

            # compute new grid locations (always transform from reference source)
            nSections = len([k for k in sections.keys() if str(k).isdigit()])
            print('nSections', nSections)

            x_source = np.array([sections[str(k)]['center'][0] for k in range(nSections)])
            y_source = np.array([sections[str(k)]['center'][1] for k in range(nSections)])

            x_target, y_target = utils.applyAffineT(x_source, y_source, waferTransform)

            transformAngle = -utils.getAffineRotation(waferTransform)
            angles_target = [(180 - sections[str(k)]['angle'] + transformAngle) % 360
                for k in range(nSections)]

            # update grids
            print('self.gm.get_number_grids()', self.gm.get_number_grids())
            for grid_number in range(self.gm.get_number_grids()):
                self.gm.set_rotation(grid_number, angles_target[grid_number])
                self.cs.set_grid_origin_s(grid_number,
                    [x_target[grid_number], y_target[grid_number]])
            self.viewport.mv_draw()

            # # # update wafer picture

            # # landmarks_source_v = [self.cs.convert_to_v([x,y])
                # # for (x,y) in
                # # zip(x_landmarks_source, y_landmarks_source)]
            # # landmarks_target_v = [self.cs.convert_to_v([x,y])
                # # for (x,y) in
                # # zip(x_landmarks_target, y_landmarks_target)]

            # # landmarks_source_v_x = [l[0] for l in landmarks_source_v]
            # # landmarks_source_v_y = [l[1] for l in landmarks_source_v]

            # # landmarks_target_v_x = [l[0] for l in landmarks_target_v]
            # # landmarks_target_v_y = [l[1] for l in landmarks_target_v]

            # # waferTransform_v = utils.rigidT(
                # # landmarks_source_v_x, landmarks_source_v_y,
                # # landmarks_target_v_x, landmarks_target_v_y)[0]

            imported_img_file_list = self.ovm.get_imported_img_file_list()
            wafer_img_number_list = [i for (i,f) in enumerate(imported_img_file_list)
                if 'wafer' in os.path.basename(f)]
            if len(wafer_img_number_list) != 1:
                print('There should be exactly one imported image with "wafer" in its name')
            else:
                wafer_img_number = wafer_img_number_list[0]
                waferTransformAngle = -utils.getAffineRotation(waferTransform)
                waferTransformScaling = utils.getAffineScaling(waferTransform)
                im_center_source_s = self.cs.get_imported_img_centre_s(wafer_img_number)
                im_center_target_s = utils.applyAffineT(
                    [im_center_source_s[0]],
                    [im_center_source_s[1]],
                    waferTransform)
                im_center_target_s = [float(a[0]) for a in im_center_target_s]

                # im_center_source_v = self.cs.convert_to_v(im_center_source_s)
                # im_center_target_v = utils.applyRigidT(
                    # [im_center_source_v[0]],
                    # [im_center_source_v[1]],
                    # waferTransform_v)

                self.ovm.set_imported_img_rotation(wafer_img_number, waferTransformAngle % 360)
                self.ovm.set_imported_img_pixel_size(wafer_img_number, 1000 * waferTransformScaling)
                # self.ovm.set_imported_img_size_px_py(self, img_number, px, py)
                self.cs.set_imported_img_centre_s(wafer_img_number, im_center_target_s)

                # update drawn image
                self.viewport.mv_load_imported_image(wafer_img_number)
                self.viewport.mv_draw()

            # update cfg
            self.cfg['magc']['wafer_calibrated'] = 'True'
            self.cfg['magc']['landmarks'] = json.dumps(landmarks)

            # update flag
            self.queue.put('MAGC WAFER CALIBRATED')
            self.trigger.s.emit()

            self.accept()

    def accept(self):
        super().accept()
