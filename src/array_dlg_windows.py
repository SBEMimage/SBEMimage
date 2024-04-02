# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module contains several Array dialogs."""

import numpy as np
import os
from qtpy.uic import loadUi
from qtpy.QtCore import Qt, QSize
from qtpy.QtGui import QIcon, QColor, QStandardItem, QStandardItemModel
from qtpy.QtWidgets import QDialog, QFileDialog, QHeaderView, QPushButton
from time import strftime, localtime
import utils

import ArrayData


GRAY = QColor(Qt.lightGray)
GREEN = QColor(Qt.green)
YELLOW = QColor(Qt.yellow)


class ArrayCalibrationDlg(QDialog):
    """Array calibration."""

    def __init__(self, config, stage, ovm, cs, gm, imported, main_controls_trigger):
        super().__init__()
        self.cfg = config
        self.stage = stage
        self.ovm = ovm
        self.cs = cs
        self.gm = gm
        self.imported = imported
        self.main_controls_trigger = main_controls_trigger
        loadUi(os.path.join('..', 'gui', 'array_calibration_dlg.ui'), self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.lTable = self.tableView_array_landmarkTable
        self.init_landmarks()
        self.pushButton_cancel.clicked.connect(self.accept)
        self.pushButton_validateCalibration.clicked.connect(self.validate_calibration)

    def init_landmarks(self):
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
            if i not in [3, 4]:  # fixed width for target columns
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        self.lTable.setColumnWidth(3, 70)
        self.lTable.setColumnWidth(4, 70)
        self.lTable.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        landmark_model = self.lTable.model()

        for index, (key, landmark) in enumerate(sorted(self.gm.array_data.landmarks.items())):
            # the target key does not exist until it is either
            # manually defined
            # or inferred when enough (>=2) other target landmarks
            # have been defined
            source = landmark.get('source', {}).get('location')
            target = landmark.get('target', {}).get('location')

            item0 = QStandardItem(f'{key}')
            item1 = QStandardItem(f'{source[0]:.3f}')
            item2 = QStandardItem(f'{source[1]:.3f}')

            item5 = QPushButton('Set')
            item5.setFixedSize(QSize(50, 40))
            item5.clicked.connect(self.set_landmark(index))

            item6 = QPushButton('Go to')
            item6.setFixedSize(QSize(60, 40))
            item6.clicked.connect(self.goto_landmark(index))

            if self.cfg['sys']['simulation_mode'] == 'True':
                item5.setEnabled(False)
                item6.setEnabled(False)

            item7 = QPushButton('Clear')
            item7.setFixedSize(QSize(60, 40))
            item7.clicked.connect(self.clear_landmark(index))

            if target is not None:
                item0.setBackground(GREEN)

                item3 = QStandardItem(f'{target[0]:.3f}')
                item3.setBackground(GREEN)

                item4 = QStandardItem(f'{target[1]:.3f}')
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
            self.lTable.setIndexWidget(landmark_model.index(index, 5), item5)
            self.lTable.setIndexWidget(landmark_model.index(index, 6), item6)
            self.lTable.setIndexWidget(landmark_model.index(index, 7), item7)

    def clear_landmark(self, row):
        def callback_clear_landmark():
            landmark_model = self.lTable.model()

            item3 = self.lTable.model().item(row, 3)
            item3.setData('', Qt.DisplayRole)
            item3.setBackground(GRAY)

            item4 = self.lTable.model().item(row, 4)
            item4.setData('', Qt.DisplayRole)
            item4.setBackground(GRAY)

            del self.gm.array_data.landmarks[row]['target']

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
            x, y = self.stage.get_xy()
            utils.log_info(
                'Array-CTRL',
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
            self.gm.set_array_landmark(row, [x, y])

            # compute transform and update landmarks
            landmarks = self.gm.array_data.landmarks
            n_landmarks = len(landmarks)

            calibrated_landmark_ids = [
                id for id in landmarks
                if self.lTable.model().item(id, 0).background().color() == GREEN]

                # the green color shows that the landmark has been
                # manually calibrated by the user
                # if the landmark is yellow, it means that it has
                # only been inferred and not manually calibrated
                # here we are using only the manually calibrated landmarks
            noncalibrated_landmark_ids = (set(range(n_landmarks)) - set(calibrated_landmark_ids))

            if len(calibrated_landmark_ids) > 1:  # at least 2 landmarks needed
                # calculating the wafer transform from source to target.
                # Using all possible landmarks available in the target
                # (minimum 2)

                source_landmarks = self.gm.array_data.get_landmarks()
                target_landmarks = self.gm.array_data.get_landmarks(landmark_type='target')

                x_landmarks_source = np.array([landmark[0] for landmark in source_landmarks.values()])
                y_landmarks_source = np.array([landmark[1] for landmark in source_landmarks.values()])

                # taking only the source landmarks for which there is a
                # corresponding target landmark
                x_landmarks_source_partial = np.array([source_landmarks[index][0] for index in calibrated_landmark_ids])
                y_landmarks_source_partial = np.array([source_landmarks[index][1] for index in calibrated_landmark_ids])

                x_landmarks_target_partial = np.array([target_landmarks[index][0] for index in calibrated_landmark_ids])
                y_landmarks_target_partial = np.array([target_landmarks[index][1] for index in calibrated_landmark_ids])

                flip_x = self.gm.sem.device_name.lower() in [
                        'zeiss merlin',
                        'zeiss sigma',
                        ]

                if len(calibrated_landmark_ids) < 3:
                    get_transform = ArrayData.rigid_t
                    apply_transform = ArrayData.apply_rigid_t
                else:
                    get_transform = ArrayData.affine_t
                    apply_transform = ArrayData.apply_affine_t

                self.gm.array_data.transform = get_transform(
                    x_landmarks_source_partial,
                    y_landmarks_source_partial,
                    x_landmarks_target_partial,
                    y_landmarks_target_partial,
                    flip_x=flip_x)

                # compute all targetLandmarks
                x_target_updated_landmarks, y_target_updated_landmarks = (
                    apply_transform(
                        x_landmarks_source,
                        y_landmarks_source,
                        self.gm.array_data.transform,
                        flip_x=flip_x,
                        ))

                # x_target_updated_landmarks = -x_target_updated_landmarks
                # x axis flipping on Merlin?

                # set the new target landmarks that were missing
                for noncalibrated_landmark_id in noncalibrated_landmark_ids:
                    x = x_target_updated_landmarks[noncalibrated_landmark_id]
                    y = y_target_updated_landmarks[noncalibrated_landmark_id]
                    self.gm.set_array_landmark(noncalibrated_landmark_id, [x, y])

                    item0 = self.lTable.model().item(
                        noncalibrated_landmark_id,
                        0)
                    item0.setBackground(YELLOW)

                    item3 = self.lTable.model().item(
                        noncalibrated_landmark_id,
                        3)
                    item3.setData(
                        f'{x:.3f}',
                        Qt.DisplayRole)
                    item3.setBackground(YELLOW)

                    item4 = self.lTable.model().item(
                        noncalibrated_landmark_id,
                        4)
                    item4.setData(
                        f'{y:.3f}',
                        Qt.DisplayRole)
                    item4.setBackground(YELLOW)

                    item6 = self.lTable.indexWidget(
                                landmark_model.index(
                                    noncalibrated_landmark_id,
                                    6))
                    item6.setEnabled(True)

                    item7 = self.lTable.indexWidget(
                                landmark_model.index(
                                    noncalibrated_landmark_id,
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
                'Array-STAGE',
                f'Landmark: moving stage to ({x},{y})')
            self.stage.move_to_xy([x, y])

            # move viewport to landmark
            self.cs.vp_centre_dx_dy = self.cs.convert_s_to_d([x, y])
            self.main_controls_trigger.transmit('DRAW VP')

        return callback_goto_landmark

    def validate_calibration(self):
        landmarks = self.gm.get_array_landmarks()
        n_landmarks = len(landmarks)
        calibrated_landmark_ids = [
            id for id in landmarks
            if self.lTable.model().item(id, 0).background().color() == GREEN]

        if len(calibrated_landmark_ids) != n_landmarks:
            utils.log_info(
                'Array-CTRL',
                'Cannot validate wafer calibration: all target landmarks '
                'must first be validated.')
        else:
            self.gm.array_landmark_calibration()
            self.gm.array_update_grids()
            flip_x = self.gm.sem.device_name.lower() in [
                'zeiss merlin',
                'zeiss sigma',
            ]
            self.imported.update_array_image(self.gm.array_data.transform, flip_x)

            # update drawn image
            self.main_controls_trigger.transmit('DRAW VP')

            # update calibration flag
            self.gm.array_data.calibrated = True
            self.main_controls_trigger.transmit('ARRAY IMAGE CALIBRATED')

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
            QIcon(os.path.join('..', 'img', 'selectdir.png')))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))
        self.setFixedSize(self.size())
        self.buttonBox.accepted.connect(self.import_zen)
        self.buttonBox.rejected.connect(self.accept)

    def import_zen(self):
        #-----------------------------
        # read sections from zen .json experiment file
        selected_file = os.path.normpath(
            self.lineEdit_fileName.text())

        if not os.path.isfile(selected_file):
            utils.log_info(
                'Array-CTRL',
                'ZEN input file not found')
            self.accept()
            return
        elif os.path.splitext(selected_file)[1] != '.json':
            utils.log_info(
                'Array-CTRL',
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
        start_path = 'C:/'
        selected_file = str(QFileDialog.getOpenFileName(
                self, 'Select ZEN experiment file',
                start_path,
                filter='ZEN experiment setup (*.json)'
                )[0])
        if selected_file:
            selected_file = os.path.normpath(selected_file)
            if os.path.splitext(selected_file)[1] == '.json':
                self.lineEdit_fileName.setText(selected_file)

    def accept(self):
        super().accept()
