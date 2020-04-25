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

GRAY = QColor(Qt.lightGray)
GREEN = QColor(Qt.green)
YELLOW = QColor(Qt.yellow)

class ImportMagCDlg(QDialog):
    """Import MagC metadata."""

    def __init__(self, acq, grid_manager, sem, imported,
                 gui_items, main_controls_trigger):
        super().__init__()
        self.acq = acq
        self.gm = grid_manager
        self.sem = sem
        self.imported = imported
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
        self.main_controls_trigger.transmit(msg)

    def import_metadata(self):
        #-----------------------------
        # read sections from MagC yaml
        magc_file_path = os.path.normpath(
            self.lineEdit_fileName.text())
        if not os.path.isfile(magc_file_path):
            self._add_to_main_log('MagC file not found')
            self.accept()
            return
        elif os.path.splitext(magc_file_path)[1] != '.magc':
            self._add_to_main_log(
                'The file chosen should be in .magc format')
            self.accept()
            return

        self.gm.magc_sections_path = magc_file_path
        with open(magc_file_path, 'r') as f:
            sectionsYAML = yaml.full_load(f)
        sections, landmarks = (utils
            .sectionsYAML_to_sections_landmarks(sectionsYAML))

        # load ROIs updated by user manually
        if 'sourceROIsUpdatedFromSBEMimage' in sectionsYAML:
            result = QMessageBox.question(
                self, 'Section import',
                'Use section locations that have been previously updated '
                'in SBEMimage instead of the locations '
                'in the original .magc file?',
                QMessageBox.Yes| QMessageBox.No)
            if result == QMessageBox.Yes:
                for sectionId, sectionXYA in \
                    sectionsYAML['sourceROIsUpdatedFromSBEMimage'].items():
                    sections[int(sectionId)] = {
                        'center': [float(a) for a in sectionXYA[:2]],
                        'angle': float( (-sectionXYA[2] + 90) % 360)}
                # deactivate roi_mode: the grid locations are now custom
                # they are not calculated any more
                # based on the ROI defined inside a section
                self.gm.magc_roi_mode = False

        n_sections = len(
            [k for k in sections.keys()
            if str(k).isdigit()]) # discard tissueROI-35
        self._add_to_main_log(
            str(n_sections)
            + ' MagC sections have been loaded.')
        #-----------------------------

        #-----------------------
        # import wafer overview
        self.imported.delete_all_images()
        magc_file_dir = os.path.dirname(magc_file_path)

        import_wafer_dlg = ImportWaferImageDlg(
            self.acq, self.imported, magc_file_dir,
            self.main_controls_trigger)
        #-----------------------

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

        self.gm.delete_all_grids_above_index(0)
        for s in range(n_sections-1):
            self.gm.add_new_grid([0, 0])
        for idx, section in sections.items():
            if str(idx).isdigit(): # to exclude tissueROI and landmarks
                self.gm[idx].auto_update_tile_positions = False
                self.gm[idx].size = [
                    self.spinBox_rows.value(),
                    self.spinBox_cols.value()]
                self.gm[idx].display_colour = 1
                self.gm[idx].frame_size_selector = frame_size_selector
                self.gm[idx].pixel_size = pixel_size
                self.gm[idx].overlap = tile_overlap
                self.gm[idx].activate_all_tiles()
                self.gm[idx].rotation = (180 - float(section['angle'])) % 360
                self.gm[idx].centre_sx_sy = list(map(float, section['center']))
                # Update tile positions after initializing all grid attributes
                self.gm[idx].update_tile_positions()
                self.gm[idx].auto_update_tile_positions = True

                # populate the section_table
                item1 = QStandardItem(str(idx))
                item1.setCheckable(True)
                item2 = QStandardItem('')
                item2.setBackground(GRAY)
                item2.setCheckable(False)
                item2.setSelectable(False)
                table_model.appendRow([item1, item2])
                table_view.setRowHeight(idx, 40)
        self.main_controls_trigger.transmit('DRAW VP')
        #-----------------------------------------

        #------------------------------
        # Update config with MagC items
        self.gm.magc_sections = sections
        self.gm.magc_selected_sections = []
        self.gm.magc_checked_sections = []
        self.gm.magc_landmarks = landmarks
        # xxx does importing a new magc file always require
        # a wafer_calibration ?
        self.gm.magc_wafer_calibrated = False
        #------------------------------

        # enable wafer configuration buttons
        self.main_controls_trigger.transmit('MAGC ENABLE CALIBRATION')
        self.main_controls_trigger.transmit('MAGC WAFER NOT CALIBRATED')
        self.main_controls_trigger.transmit('MAGC ENABLE WAFER IMAGE IMPORT')

        self.accept()

    def select_file(self):
        start_path = 'C:\\'
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
            self._add_to_main_log('No wafer picture was found. '
                'Select the wafer image manually.')
        elif len(im_names) > 1:
            self._add_to_main_log(
                'There is more than one image available in the folder '
                'containing the .magc section description file.'
                'Select the wafer image manually')
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
            self._add_to_main_log(
                'You have not added a wafer image overview.'
                'You can still do it by selecting "Import Wafer Image"'
                'in the MagC tab.')
        else:
            wafer_im = self.imported[-1]
            width, height = wafer_im.size
            wafer_im.pixel_size = 1000
            wafer_im.centre_sx_sy = [width//2, height//2]
            self.main_controls_trigger.transmit('DRAW VP')
            self._add_to_main_log(
                'Wafer image succesfully imported.')

    def _add_to_main_log(self, msg):
        """Add entry to the log in the main window"""
        msg = utils.format_log_entry(msg)
        self.main_controls_trigger.transmit(msg)

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
        landmark_model.setHorizontalHeaderItem(0, QStandardItem(''))
        landmark_model.setHorizontalHeaderItem(1, QStandardItem('Source x'))
        landmark_model.setHorizontalHeaderItem(2, QStandardItem('Source y'))
        landmark_model.setHorizontalHeaderItem(3, QStandardItem('Target x'))
        landmark_model.setHorizontalHeaderItem(4, QStandardItem('Target y'))
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
        for id,(key,source_target) \
            in enumerate(self.gm.magc_landmarks.items()):

            # source_target is a dictionary for each landmark
            # that contains two keys
            # source: the landmark in source coordinates
            # target: the landmark in target coordinates
            # the target key does not exist until it is either
            # manually defined
            # or inferred when enough (2) other target landmarks
            # have been defined

            item0 = QStandardItem(str(key))
            item1 = QStandardItem(str(source_target['source'][0]))
            item2 = QStandardItem(str(source_target['source'][1]))

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

            if 'target' in source_target:
                item0.setBackground(GREEN)

                item3 = QStandardItem(str(source_target['target'][0]))
                item3.setBackground(GREEN)

                item4 = QStandardItem(str(source_target['target'][1]))
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
            self.lTable.setIndexWidget(landmark_model.index(id, 5), item5)
            self.lTable.setIndexWidget(landmark_model.index(id, 6), item6)
            self.lTable.setIndexWidget(landmark_model.index(id, 7), item7)

    def clear_landmark(self, row):
        def callback_clear_landmark():
            landmark_model = self.lTable.model()

            item3 = self.lTable.model().item(row, 3)
            item3.setData('', Qt.DisplayRole)
            item3.setBackground(GRAY)

            item4 = self.lTable.model().item(row, 4)
            item4.setData('', Qt.DisplayRole)
            item4.setBackground(GRAY)

            del self.gm.magc_landmarks[str(row)]['target']

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
            print('xlandmark, ylandmark', x, y)
            landmark_model = self.lTable.model()

            # update table
            item0 = self.lTable.model().item(row, 0)
            item0.setBackground(GREEN)

            item3 = self.lTable.model().item(row, 3)
            item3.setData(str(x), Qt.DisplayRole)
            item3.setBackground(GREEN)

            item4 = self.lTable.model().item(row, 4)
            item4.setData(str(y), Qt.DisplayRole)
            item4.setBackground(GREEN)

            item6 = self.lTable.indexWidget(landmark_model.index(row, 6))
            item6.setEnabled(True)

            item7 = self.lTable.indexWidget(landmark_model.index(row, 7))
            item7.setEnabled(True)

            # update landmarks
            self.gm.magc_landmarks[str(row)]['target'] = [x,y]

            # compute transform and update landmarks
            nLandmarks = len(self.gm.magc_landmarks)
            calibratedLandmarkIds = [
                int(id) for id,landmark
                in self.gm.magc_landmarks.items()
                if (self.lTable.model().item(int(id), 0)
                    .background().color() == GREEN)]
                # the green color shows that the landmark has been
                # manually calibrated by the user
                # if the landmark is yellow, it means that it has
                # only been inferred and not manually calibrated
                # here we are using only the manually calibrated landmarks
            noncalibratedLandmarkIds = (
                set(range(nLandmarks)) - set(calibratedLandmarkIds))
            print('calibratedLandmarkIds', calibratedLandmarkIds)

            if len(calibratedLandmarkIds) > 1: # at least 2 landmarks needed
                # calculating the wafer transform from source to target.
                # Using all possible landmarks available in the target
                # (minimum 2)

                x_landmarks_source = np.array([
                    self.gm.magc_landmarks[str(i)]['source'][0]
                    for i in range(nLandmarks)])
                y_landmarks_source = np.array([
                    self.gm.magc_landmarks[str(i)]['source'][1]
                    for i in range(nLandmarks)])

                # taking only the source landmarks for which there is a
                # corresponding target landmark
                x_landmarks_source_partial = np.array(
                    [self.gm.magc_landmarks[str(i)]['source'][0]
                     for i in calibratedLandmarkIds])
                y_landmarks_source_partial = np.array(
                    [self.gm.magc_landmarks[str(i)]['source'][1]
                     for i in calibratedLandmarkIds])

                x_landmarks_target_partial = np.array(
                    [self.gm.magc_landmarks[str(i)]['target'][0]
                     for i in calibratedLandmarkIds])
                y_landmarks_target_partial = np.array(
                    [self.gm.magc_landmarks[str(i)]['target'][1]
                     for i in calibratedLandmarkIds])

                self.gm.magc_wafer_transform = utils.rigidT(
                    x_landmarks_source_partial, y_landmarks_source_partial,
                    x_landmarks_target_partial, y_landmarks_target_partial)[0]

                # compute all targetLandmarks
                x_target_updated_landmarks, y_target_updated_landmarks = (
                    utils.applyRigidT(
                        x_landmarks_source,
                        y_landmarks_source,
                        self.gm.magc_wafer_transform))

                # x_target_updated_landmarks = -x_target_updated_landmarks
                # x axis flipping on Merlin

                # set the new target landmarks that were missing
                for noncalibratedLandmarkId in noncalibratedLandmarkIds:
                    x = x_target_updated_landmarks[noncalibratedLandmarkId]
                    y = y_target_updated_landmarks[noncalibratedLandmarkId]
                    (self.gm.magc_landmarks
                        [str(noncalibratedLandmarkId)]['target']) = [x,y]

                    item0 = self.lTable.model().item(noncalibratedLandmarkId, 0)
                    item0.setBackground(YELLOW)

                    item3 = self.lTable.model().item(noncalibratedLandmarkId, 3)
                    item3.setData(str(x), Qt.DisplayRole)
                    item3.setBackground(YELLOW)

                    item4 = self.lTable.model().item(noncalibratedLandmarkId, 4)
                    item4.setData(str(y), Qt.DisplayRole)
                    item4.setBackground(YELLOW)

                    item6 = self.lTable.indexWidget(landmark_model.index(
                        noncalibratedLandmarkId, 6))
                    item6.setEnabled(True)

                    item7 = self.lTable.indexWidget(landmark_model.index(
                        noncalibratedLandmarkId, 7))
                    item7.setEnabled(True)

        return callback_set_landmark

    def goto_landmark(self, row):
        def callback_goto_landmark():
            item3 = self.lTable.model().item(row, 3)
            item4 = self.lTable.model().item(row, 4)
            x = float(self.lTable.model().data(item3.index()))
            y = float(self.lTable.model().data(item4.index()))

            self._add_to_main_log(
                'Landmark: moving to '
                + str(x) + ',' + str(y))
            self.stage.move_to_xy([x,y])
            # xxx move viewport
            # self.cs.set_mv_centre_d(
            #     self.cs.get_grid_origin_d(grid_number=row))
            # self.main_controls_trigger.transmit('DRAW VP')

        return callback_goto_landmark

    def validate_calibration(self):
        calibratedLandmarkIds = [
            int(id) for id,landmark
            in self.gm.magc_landmarks.items()
            if (self.lTable.model().item(int(id), 0)
                .background().color() == GREEN)]

        n_landmarks = len(self.gm.magc_landmarks)

        if len(calibratedLandmarkIds) != n_landmarks:
            self._add_to_main_log(
                'Cannot validate wafer calibration: all target landmarks '
                'must first be validated.')
        else:
            x_landmarks_source = [
                self.gm.magc_landmarks[str(i)]['source'][0]
                for i in range(n_landmarks)]
            y_landmarks_source = [
                self.gm.magc_landmarks[str(i)]['source'][1]
                for i in range(n_landmarks)]

            x_landmarks_target = [
                self.gm.magc_landmarks[str(i)]['target'][0]
                for i in range(n_landmarks)]
            y_landmarks_target = [
                self.gm.magc_landmarks[str(i)]['target'][1]
                for i in range(n_landmarks)]

            print('x_landmarks_source, y_landmarks_source, x_landmarks_target, '
                  'y_landmarks_target', x_landmarks_source, y_landmarks_source,
                  x_landmarks_target, y_landmarks_target)

            self.gm.magc_wafer_transform = utils.affineT(
                x_landmarks_source, y_landmarks_source,
                x_landmarks_target, y_landmarks_target)

            print('waferTransform', self.gm.magc_wafer_transform)

            # compute new grid locations
            # (always transform from reference source)
            nSections = len(
                [k for k in self.gm.magc_sections.keys()
                    if str(k).isdigit()])
            print('nSections', nSections)

            x_source = np.array(
                [self.gm.magc_sections[str(k)]['center'][0]
                    for k in range(nSections)])
            y_source = np.array(
                [self.gm.magc_sections[str(k)]['center'][1]
                    for k in range(nSections)])

            x_target, y_target = utils.applyAffineT(
                x_source,
                y_source,
                self.gm.magc_wafer_transform)

            transformAngle = -utils.getAffineRotation(
                self.gm.magc_wafer_transform)
            angles_target = [
                (180 - self.gm.magc_sections[str(k)]['angle'] + transformAngle) % 360
                for k in range(nSections)]

            # update grids
            print('self.gm.number_grids', self.gm.number_grids)
            for grid_number in range(self.gm.get_number_grids):

                self.gm[grid_number].rotation = angles_target[grid_number]

                self.gm[grid_number].centre_sx_sy = [
                    x_target[grid_number],
                    y_target[grid_number]]
                self.gm[grid_number].update_tile_positions()

            self.main_controls_trigger.transmit('DRAW VP')

            # update wafer picture
            waferTransformAngle = -utils.getAffineRotation(
                self.gm.magc_wafer_transform)
            waferTransformScaling = utils.getAffineScaling(
                self.gm.magc_wafer_transform)

            im_center_target_s = utils.applyAffineT(
                [self.imported[0].centre_sx_sy[0]],
                [self.imported[0].centre_sx_sy[1]],
                self.gm.magc_wafer_transform)

            im_center_target_s = [float(a[0]) for a in im_center_target_s]

            # im_center_source_v = self.cs.convert_to_v(im_center_source_s)
            # im_center_target_v = utils.applyRigidT(
                # [im_center_source_v[0]],
                # [im_center_source_v[1]],
                # waferTransform_v)

            self.imported[0].rotation = waferTransformAngle % 360
            self.imported[0].pixel_size = 1000 * waferTransformScaling

            self.imported[0].centre_sx_sy = im_center_target_s

            # update drawn image
            self.main_controls_trigger.transmit('DRAW VP')

            # update calibration flag
            self.gm.magc_wafer_calibrated = True
            self._transmit_cmd('MAGC WAFER CALIBRATED')

            self.accept()

    def accept(self):
        super().accept()

    def _add_to_main_log(self, msg):
        """Add entry to the log in the main window"""
        msg = utils.format_log_entry(msg)
        self.main_controls_trigger.transmit(msg)
