# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
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
from time import sleep, time
from queue import Queue
from PIL import Image
from skimage.io import imread
from skimage.feature import register_translation
import numpy as np
from imreg_dft import translation
from zipfile import ZipFile

from viewport_dlg_windows import ImportImageDlg

from imported_img import ImportedImages

from PyQt5.uic import loadUi
from PyQt5.QtCore import Qt, QObject, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon, QPalette, QColor, QFont, \
    QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, \
    QFileDialog, QLineEdit, QDialogButtonBox, QHeaderView, QPushButton

import utils
import acq_func

GRAY = QColor(Qt.lightGray)
GREEN = QColor(Qt.green)
YELLOW = QColor(Qt.yellow)

class ImportMagCDlg(QDialog):
    """Import MagC metadata."""

    def __init__(self, config, grid_manager, coordinate_system, stage,
            sem, ovm, viewport, gui_items, trigger, queue):
        super().__init__()
        self.cfg = config
        self.gm = grid_manager
        self.cs = coordinate_system
        self.stage = stage
        self.sem = sem
        self.ovm = ovm
        self.viewport = viewport
        self.gui_items = gui_items
        self.trigger = trigger
        self.queue = queue

        self.target_dir = os.path.join(
            self.cfg['acq']['base_dir'], 'overviews', 'imported')
        loadUi(os.path.join('..', 'gui', 'import_magc_metadata_dlg.ui'), self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon(os.path.join('..', 'img', 'icon_16px.ico')))
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(
            QIcon(os.path.join('..','img','selectdir.png')))
        self.pushButton_selectFile.setIcon(
            QIcon(os.path.join('..', 'img', 'selectdir.png')))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))
        self.setFixedSize(self.size())
        self.pushButton_import.accepted.connect(self.import_metadata)
        self.pushButton_import.rejected.connect(self.accept)
        store_res_list = [
            '%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_frameSize.addItems(store_res_list)
        self.comboBox_frameSize.setCurrentIndex(5)
        self.show()

    def _add_to_main_log(self, msg):
        """Add entry to the log in the main window"""
        msg = utils.format_log_entry(msg)
        # Send entry to main window via queue and trigger:
        self.queue.put(msg)
        self.trigger.s.emit()

    def import_metadata(self):
        # read sections from MagC yaml
        magc_file_path = os.path.normpath(
            self.lineEdit_fileName.text())
        if not os.path.isfile(magc_file_path):
            self._add_to_main_log('MagC file not found')
            self.accept()
            return

        self.gm.magc_sections_path = magc_file_path
        with open(magc_file_path, 'r') as f:
            sectionsYAML = yaml.full_load(f)
        sections, landmarks = (
            utils.sectionsYAML_to_sections_landmarks(
                sectionsYAML))

        if 'sourceROIsUpdatedFromSBEMimage' in sectionsYAML:
            result = QMessageBox.question(
                self, 'Section import',
                'Use section locations that have been previously updated '
                'in SBEMimage?',
                QMessageBox.Yes| QMessageBox.No)
            if result == QMessageBox.Yes:
                for sectionId, sectionXYA in \
                    sectionsYAML['sourceROIsUpdatedFromSBEMimage'].items():
                    sections[int(sectionId)] = {
                    'center': [float(a) for a in sectionXYA[:2]],
                    'angle': float( (-sectionXYA[2] + 90) % 360)}
                self.acq.magc_roi_mode = False

        n_sections = len(
            [k for k in sections.keys()
            if str(k).isdigit()])
        self._add_to_main_log(
            str(n_sections)
            + ' MagC sections have been loaded.')
        #--------------------------------------
        # import wafer overview if file present

        dir_sections = os.path.dirname(magc_file_path)
        im_names = [im_name for im_name in os.listdir(dir_sections)
            if ('wafer' in im_name)
                and (os.path.splitext(im_name)[1] in ['.tif', '.png'])]
        if im_names == []:
            self._add_to_main_log('No wafer picture was found. Insert it manually.')
        elif len(im_names) == 1:
            im_path = os.path.normpath(
                os.path.join(dir_sections, im_names[0]))

            selection_success = True
            selected_filename = os.path.basename(im_path)
            timestamp = str(datetime.datetime.now())
            # Remove some characters from timestamp to get valid file name:
            timestamp = timestamp[:19].translate(
                {ord(c): None for c in ' :-.'})
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
                    new_img_number = self.imported.number_imported
                    self.imported.add_image()
                    width, height = imported_img.size
                    self.imported[new_img_number].image_src = target_path
                    self.imported[new_img_number].description = selected_filename
                    self.imported[new_img_number] = [width, height]
                    self.imported[new_img_number].pixel_size = 1000
                    self.imported[new_img_number].centre_sx_sy = [width//2, height//2]
                    self.viewport.mv_draw()

            else:
                QMessageBox.warning(self, 'Error',
                                    'Specified file not found.',
                                    QMessageBox.Ok)
                selection_success = False


        dialog = ImportImageDlg(
            ImportedImages(self.cfg),
            os.path.join(self.cfg['acq']['base_dir'], 'imported'))
        dialog.doubleSpinBox_pixelSize.setEnabled(False)
        dialog.doubleSpinBox_posX.setEnabled(False)
        dialog.doubleSpinBox_posY.setEnabled(False)
        dialog.spinBox_rotation.setEnabled(False)

        # pre-filling the dialog if wafer image present
        # and no ambiguity in choosing the file
        magc_file_folder = os.path.dirname(magc_file_path)
        im_names = [im_name for im_name in os.listdir(magc_file_folder)
            if ('wafer' in im_name)
                and (os.path.splitext(im_name)[1] in ['.tif', '.png'])]
        if len(im_names) == 0:
            self._add_to_main_log('''No wafer picture was found.
                Select the wafer image manually.''')
        elif len(im_names) > 1:

            self._add_to_main_log(
                'There is more than one image available in the folder '
                'containing the .magc section description file.'
                'Select the wafer image manually')
        elif len(im_names) == 1:
            im_path = os.path.normpath(
                os.path.join(magc_file_folder, im_names[0]))

            dialog.lineEdit_fileName.setText(im_path)
            dialog.lineEdit_name.setText(
                os.path.splitext(
                    os.path.basename(im_path))[0])

        if dialog.exec_():
            self._add_to_main_log('debug_executed')
            print('debug_importImg')

            # # # selection_success = True
            # # # selected_filename = os.path.basename(im_path)
            # # # timestamp = str(datetime.datetime.now())
            # # # # Remove some characters from timestamp to get valid file name:
            # # # timestamp = timestamp[:19].translate(
                # # # {ord(c): None for c in ' :-.'})
            # # # target_path = os.path.join(self.target_dir,
                           # # # os.path.splitext(selected_filename)[0] +
                           # # # '_' + timestamp + '.png')
            # # # if os.path.isfile(im_path):
                # # # # Copy file to data folder as png:
                # # # try:
                    # # # imported_img = Image.open(im_path)
                    # # # imported_img.save(target_path)
                # # # except Exception as e:
                    # # # QMessageBox.warning(
                        # # # self, 'Error',
                        # # # 'Could not load image file.' + str(e),
                         # # # QMessageBox.Ok)
                    # # # selection_success = False

                # # # if selection_success:
                    # # # new_img_number = self.ovm.get_number_imported()
                    # # # self.ovm.add_imported_img()
                    # # # width, height = imported_img.size
                    # # # self.ovm.set_imported_img_file(
                        # # # new_img_number, target_path)
                    # # # self.ovm.set_imported_img_name(new_img_number,
                                                   # # # selected_filename)
                    # # # self.ovm.set_imported_img_size_px_py(
                        # # # new_img_number, width, height)
                    # # # self.ovm.set_imported_img_pixel_size(
                        # # # new_img_number, 1000)
                    # # # self.cs.set_imported_img_centre_s(
                        # # # new_img_number,
                        # # # [width//2, height//2])

                    # # # self.viewport.mv_load_last_imported_image()
                    # # # self.viewport.mv_draw()

            # # # else:
                # # # QMessageBox.warning(self, 'Error',
                                    # # # 'Specified file not found.',
                                    # # # QMessageBox.Ok)
                # # # selection_success = False
        #--------------------------------------

        #---------------------------------------
        # populate the grids and the sectionList
        frame_size_selector = self.comboBox_frameSize.currentIndex()
        pixel_size = self.doubleSpinBox_pixelSize.value()
        tile_overlap = self.doubleSpinBox_tileOverlap.value()

        sectionListView = self.gui_items['sectionList']
        sectionListModel = sectionListView.model()

        sectionListModel.clear()
        sectionListModel.setHorizontalHeaderItem(
            0, QStandardItem('Section'))
        sectionListModel.setHorizontalHeaderItem(
            1, QStandardItem('State'))
        header = sectionListView.horizontalHeader()
        for i in range(2):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)

        self.gm.delete_all_grid_above_index(0)
        for section in range(n_sections):
            self.gm.add_new_grid()
        for idx, section in sections.items():
            if str(idx).isdigit(): # to exclude tissueROI and landmarks
                self.gm[idx].size = [self.spinBox_rows.value(),
                                     self.spinBox_cols.value()]
                self.gm[idx].frame_size_selector = tile_size_selector
                self.gm[idx].pixel_size = pixel_size
                self.gm[idx].overlap = tile_overlap
                self.gm[idx].activate_all_tiles()
                self.gm[idx].rotation = (180 - float(section['angle'])) % 360
                self.gm[idx].centre_sx_sy = list(map(float, section['center']))
                self.gm[idx].update_tile_positions()

                # populate the sectionList
                item1 = QStandardItem(str(idx))
                item1.setCheckable(True)
                item2 = QStandardItem('')
                item2.setBackground(GRAY)
                item2.setCheckable(False)
                item2.setSelectable(False)
                sectionListModel.appendRow([item1, item2])
                sectionListView.setRowHeight(idx, 40)
        #---------------------------------------

        #---------------------------------------
        # Update config with MagC items
        self.gm.magc_sections = sections
        self.gm.magc_selected_sections = []
        self.gm.magc_checked_sections = []
        self.gm.magc_landmarks = landmarks
        # xxx does importing a new magc file always require
        # a wafer_calibration ?
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
        selected_file = os.path.join(
            '..', 'magc', 'example', 'magc_433_sections.magc')
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
        self.pushButton_selectFile.setIcon(
            QIcon(os.path.join('..','img','selectdir.png')))
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
        self.pushButton_validateCalibration.clicked.connect(
            self.validate_calibration)
        self.show()

    def _add_to_main_log(self, msg):
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
            if i not in [3,4]: # fixed width for target columns
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        self.lTable.setColumnWidth(3, 70)
        self.lTable.setColumnWidth(4, 70)
        self.lTable.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)

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
                item0.setBackground(GREEN)

                item3 = QStandardItem(str(sourceTarget['target'][0]))
                item3.setBackground(GREEN)

                item4 = QStandardItem(str(sourceTarget['target'][1]))
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
            item3.setBackground(GRAY)

            item4 = self.lTable.model().item(row, 4)
            item4.setData('', Qt.DisplayRole)
            item4.setBackground(GRAY)

            del landmarks[str(row)]['target']

            # update table
            item0 = self.lTable.model().item(row, 0)
            item0.setBackground(GRAY)

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
            item0.setBackground(GREEN)

            item3 = self.lTable.model().item(row, 3)
            item3.setData(str(x), Qt.DisplayRole)
            item3.setBackground(GREEN)

            item4 = self.lTable.model().item(row, 4)
            item4.setData(str(y), Qt.DisplayRole)
            item4.setBackground(GREEN)

            item6 = self.lTable.indexWidget(landmarkModel.index(row, 6))
            item6.setEnabled(True)

            item7 = self.lTable.indexWidget(landmarkModel.index(row, 7))
            item7.setEnabled(True)

            # update landmarks
            landmarks[str(row)]['target'] = [x,y]

            # compute transform and update landmarks
            nLandmarks = len(landmarks)
            calibratedLandmarkIds = [
                int(id)
                for id,landmark
                in landmarks.items()
                # if 'target' in landmark]
                if self.lTable.model().item(int(id), 0).background().color()
                   == GREEN]
            noncalibratedLandmarkIds = (
                set(range(nLandmarks)) - set(calibratedLandmarkIds))
            print('calibratedLandmarkIds', calibratedLandmarkIds)


            if len(calibratedLandmarkIds) > 1: # at least 2 landmarks needed
                # calculating the wafer transform from source to target.
                # Using all possible landmarks available in the target
                # (minimum 2)

                x_landmarks_source = np.array([landmarks[str(i)]['source'][0]
                    for i in range(nLandmarks)])
                y_landmarks_source = np.array([landmarks[str(i)]['source'][1]
                    for i in range(nLandmarks)])

                # taking only the source landmarks for which there is a
                # corresponding target landmark
                x_landmarks_source_partial = np.array(
                    [landmarks[str(i)]['source'][0]
                     for i in calibratedLandmarkIds])
                y_landmarks_source_partial = np.array(
                    [landmarks[str(i)]['source'][1]
                     for i in calibratedLandmarkIds])

                x_landmarks_target_partial = np.array(
                    [landmarks[str(i)]['target'][0]
                     for i in calibratedLandmarkIds])
                y_landmarks_target_partial = np.array(
                    [landmarks[str(i)]['target'][1]
                     for i in calibratedLandmarkIds])

                waferTransform = utils.rigidT(
                    x_landmarks_source_partial, y_landmarks_source_partial,
                    x_landmarks_target_partial, y_landmarks_target_partial)[0]

                # compute all targetLandmarks
                x_target_updated_landmarks, y_target_updated_landmarks = (
                    utils.applyRigidT(
                        x_landmarks_source, y_landmarks_source, waferTransform))

                # x_target_updated_landmarks = -x_target_updated_landmarks
                # x axis flipping on Merlin

                # set the new target landmarks that were missing
                for noncalibratedLandmarkId in noncalibratedLandmarkIds:
                    x = x_target_updated_landmarks[noncalibratedLandmarkId]
                    y = y_target_updated_landmarks[noncalibratedLandmarkId]
                    landmarks[str(noncalibratedLandmarkId)]['target'] = [x,y]

                    item0 = self.lTable.model().item(noncalibratedLandmarkId, 0)
                    item0.setBackground(YELLOW)

                    item3 = self.lTable.model().item(noncalibratedLandmarkId, 3)
                    item3.setData(str(x), Qt.DisplayRole)
                    item3.setBackground(YELLOW)

                    item4 = self.lTable.model().item(noncalibratedLandmarkId, 4)
                    item4.setData(str(y), Qt.DisplayRole)
                    item4.setBackground(YELLOW)

                    item6 = self.lTable.indexWidget(landmarkModel.index(
                        noncalibratedLandmarkId, 6))
                    item6.setEnabled(True)

                    item7 = self.lTable.indexWidget(landmarkModel.index(
                        noncalibratedLandmarkId, 7))
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
            # self.cs.set_mv_centre_d(
            #     self.cs.get_grid_origin_d(grid_number=row))
            # self.viewport.mv_draw()
        return callback_goto_landmark

    def validate_calibration(self):
        # with open(self.cfg['magc']['sections_path'], 'r') as f:
            # sections = utils.sectionsYAML_to_sections_landmarks(
            # yaml.full_load(f))[0]
        sections = json.loads(self.cfg['magc']['sections'])
        landmarks = json.loads(self.cfg['magc']['landmarks'])

        nLandmarks = len(landmarks)
        calibratedLandmarkIds = [int(id)
            for id,landmark
            in landmarks.items()
            if self.lTable.model().item(int(id), 0).background().color()
                == GREEN]

        if len(calibratedLandmarkIds) != nLandmarks:
            self._add_to_main_log(
                'Cannot validate wafer calibration: all target landmarks '
                'must be validated.')

        else:
            x_landmarks_source = [landmarks[str(i)]['source'][0]
                for i in range(len(landmarks))]
            y_landmarks_source = [landmarks[str(i)]['source'][1]
                for i in range(len(landmarks))]

            x_landmarks_target = [landmarks[str(i)]['target'][0]
                for i in range(len(landmarks))]
            y_landmarks_target = [landmarks[str(i)]['target'][1]
                for i in range(len(landmarks))]

            print('x_landmarks_source, y_landmarks_source, x_landmarks_target, '
                  'y_landmarks_target', x_landmarks_source, y_landmarks_source,
                  x_landmarks_target, y_landmarks_target)

            waferTransform = utils.affineT(
                x_landmarks_source, y_landmarks_source,
                x_landmarks_target, y_landmarks_target)

            print('waferTransform', waferTransform)
            self.cfg['magc']['wafer_transform'] = json.dumps(
                waferTransform.tolist())

            # compute new grid locations
            # (always transform from reference source)
            nSections = len([k for k in sections.keys() if str(k).isdigit()])
            print('nSections', nSections)

            x_source = np.array(
                [sections[str(k)]['center'][0] for k in range(nSections)])
            y_source = np.array(
                [sections[str(k)]['center'][1] for k in range(nSections)])

            x_target, y_target = utils.applyAffineT(
                x_source, y_source, waferTransform)

            transformAngle = -utils.getAffineRotation(waferTransform)
            angles_target = [
                (180 - sections[str(k)]['angle'] + transformAngle) % 360
                for k in range(nSections)]

            # update grids
            print('self.gm.get_number_grids()', self.gm.get_number_grids())
            for grid_number in range(self.gm.get_number_grids()):
                self.gm.set_rotation(grid_number, angles_target[grid_number])
                self.gm.set_grid_centre_s(grid_number,
                    [x_target[grid_number], y_target[grid_number]])
                self.gm.calculate_grid_map(grid_number)

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
            wafer_img_number_list = [
                i for (i,f) in enumerate(imported_img_file_list)
                if 'wafer' in os.path.basename(f)]
            if len(wafer_img_number_list) != 1:
                print('There should be exactly one imported image with '
                      '"wafer" in its name')
            else:
                wafer_img_number = wafer_img_number_list[0]
                waferTransformAngle = -utils.getAffineRotation(waferTransform)
                waferTransformScaling = utils.getAffineScaling(waferTransform)
                im_center_source_s = self.cs.get_imported_img_centre_s(
                    wafer_img_number)
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

                self.ovm.set_imported_img_rotation(
                    wafer_img_number, waferTransformAngle % 360)
                self.ovm.set_imported_img_pixel_size(
                    wafer_img_number, 1000 * waferTransformScaling)
                # self.ovm.set_imported_img_size_px_py(self, img_number, px, py)
                self.cs.set_imported_img_centre_s(
                    wafer_img_number, im_center_target_s)

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
