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
from qtpy.QtWidgets import QDialog, QMessageBox, QFileDialog, QHeaderView, QPushButton
from time import strftime, localtime
import utils

import ArrayData
from viewport_dlg_windows import ImportImageDlg


GRAY = QColor(Qt.lightGray)
GREEN = QColor(Qt.green)
YELLOW = QColor(Qt.yellow)


class ArrayImportCDlg(QDialog):
    """Import Array data."""

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
        self.target_dir = os.path.join(self.acq.base_dir, 'overviews', 'imported')
        loadUi(os.path.join('..', 'gui', 'array_data_import_dlg.ui'), self)
        self.default_array_path = os.path.join('..', 'array', 'example', 'wafer_example1.json')
        self.lineEdit_fileName.setText(self.default_array_path)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon(os.path.join('..', 'img', 'icon_16px.ico')))
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(QIcon(os.path.join('..', 'img', 'selectdir.png')))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))
        self.setFixedSize(self.size())
        self.pushButton_import.accepted.connect(self.import_data)
        self.pushButton_import.rejected.connect(self.accept)
        store_res_list = ['%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_frameSize.addItems(store_res_list)
        self.comboBox_frameSize.setCurrentIndex(len(store_res_list) - 1)
        if 'multisem' in self.sem.device_name.lower():
            self.comboBox_frameSize.setEnabled(False)
            self.comboBox_frameSize.setCurrentIndex(0)
            self.spinBox_rows.setEnabled(False)
            self.spinBox_cols.setEnabled(False)
            self.spinBox_rows.setValue(1)
            self.spinBox_cols.setValue(1)
        self.show()

    def import_data(self):
        #-----------------------------
        # read sections from data file
        data_path = os.path.normpath(self.lineEdit_fileName.text())
        ext = os.path.splitext(data_path)[-1].lower()
        if not os.path.isfile(data_path):
            msg = (f'The file could not be found with the following path: {data_path}')
            utils.log_info(
                'Array-CTRL',
                msg)
            QMessageBox.critical(self, 'Warning', msg)
            self.accept()
            return
        elif not (ext == '.magc' or ext == '.yml' or ext == '.yaml' or ext == '.json'):
            msg = 'The file chosen should be in the correct format (.magc/.yml/.yaml/.json).'
            utils.log_info(
                'Array-CTRL',
                msg)
            QMessageBox.critical(self, 'Warning', msg)
            self.accept()
            return

        self.main_controls_trigger.transmit('ARRAY RESET')
        self.gm.array_read(data_path)
        array_data = self.gm.array_data

        # load ROIs updated by user manually
        if self.checkBox.isChecked():
            if not array_data.sbemimage_sections:
                msg = ('The array file does not contain information from a previous'
                       ' SBEMimage session. Please try another file, or uncheck the option'
                       ' in the import dialog.')
                utils.log_info(
                    'Array-CTRL',
                    msg)
                QMessageBox.critical(self, 'Warning', msg)
                return
            else:
                utils.log_info(
                    'Array-CTRL',
                    f'{len(array_data.sbemimage_sections)} Array sections have been loaded.')
        else:
            utils.log_info(
                'Array-CTRL',
                f'{len(array_data.sections)} Array sections have been loaded.')
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

        self.gm[0].origin_sx_sy = [0, 0]

        sections = array_data.sections
        if isinstance(sections, dict):
            sections = list(sections.values())

        #for _ in range(len(sections) - 1):
        #    self.gm.add_new_grid([0, 0])

        for index, section in enumerate(sections):
            if len(section.get('rois', [])) > 0:
                # TODO: support multiple roi/grids
                grid_section = section['rois'][0]
            else:
                grid_section = section['sample']

            center, size, angle = utils.calc_rotated_rect(grid_section['polygon'])
            grid = self.gm.add_new_grid_from_roi(grid_section['center'], size, -grid_section['angle'] % 360)

            #grid = self.gm[index]
            grid.auto_update_tile_positions = False
            #grid.size = [
            #    self.spinBox_rows.value(),
            #    self.spinBox_cols.value()]
            grid.display_colour = 1
            #grid.frame_size_selector = frame_size_selector
            #grid.pixel_size = pixel_size
            grid.overlap = tile_overlap
            grid.activate_all_tiles()
            #grid.rotation = -grid_section['angle'] % 360
            # Update tile positions after initializing all grid attributes
            grid.update_tile_positions()
            # centre must be finally set after updating tile positions
            grid.auto_update_tile_positions = True
            #grid.centre_sx_sy = grid_section['center']

            # load autofocus points
            if self.checkBox.isChecked() and array_data.sbemimage_sections:
                if 'focus' in array_data.sbemimage_sections[index]:
                    self.gm[index].array_autofocus_points_source = array_data.sbemimage_sections[index]['focus']
                    # for point in magc['sbemimage_sections'][key]['focus']:
                        # self.gm.magc_add_autofocus_point(
                            # key,
                            # point)

            elif 'focus' in section:
                for point in section['focus'].values():
                    self.gm.array_add_autofocus_point(
                        index,
                        point['location'])

            # self.gm[key].magc_polyroi_points_source = [
                # (-10, 0),
                # ( 10, 0),
                # ( 10, 20),
                # (-10, 20)]

            # populate the section_table
            item1 = QStandardItem(str(index))
            item1.setCheckable(True)
            item2 = QStandardItem('')
            item2.setBackground(GRAY)
            item2.setCheckable(False)
            item2.setSelectable(False)
            table_model.appendRow([item1, item2])
            table_view.setRowHeight(index, 40)
        #-----------------------------------------

        #------------------------------
        # todo: does importing a new data file always require
        # a wafer_calibration ?
        #------------------------------

        # enable wafer configuration buttons
        self.main_controls_trigger.transmit('ARRAY WAFER NOT CALIBRATED')
        self.main_controls_trigger.transmit('ARRAY ENABLE IMAGE IMPORT')

        # activate stage show
        self.main_controls_trigger.transmit('ACTIVATE SHOW STAGE')

        if len(array_data.landmarks) > 2:
            self.main_controls_trigger.transmit('ARRAY ENABLE CALIBRATION')

        self.main_controls_trigger.transmit('DRAW VP')
        self.accept()

    def select_file(self):
        start_path = self.lineEdit_fileName.text()
        selected_file = str(QFileDialog.getOpenFileName(
                self, 'Select Array data file',
                start_path,
                'Sections files (*.yml;*.yaml;*.json);;MagC files (*.magc)'
                )[0])
        if len(selected_file) > 0:
            selected_file = os.path.normpath(selected_file)
            self.lineEdit_fileName.setText(selected_file)

    def accept(self):
        super(ArrayImportCDlg, self).accept()

#------------------------------------------------------------------------------

class ImportWaferImageDlg(QDialog):
    """Import a wafer image into the viewport for Array."""

    def __init__(self, acq, imported, data_path,
                 main_controls_trigger):
        super().__init__()
        self.acq = acq
        self.imported = imported
        self.main_controls_trigger = main_controls_trigger
        self.imported_dir = os.path.join(
            self.acq.base_dir, 'overviews', 'imported')
        if data_path is None:
            data_path = 'C:/'
        self.wafer_image_dir = os.path.dirname(data_path)

        import_image_dialog = ImportImageDlg(
            self.imported,
            self.imported_dir)
        import_image_dialog.doubleSpinBox_pixelSize.setEnabled(False)
        import_image_dialog.doubleSpinBox_pixelSize.setValue(1000)
        import_image_dialog.doubleSpinBox_posX.setEnabled(False)
        import_image_dialog.doubleSpinBox_posY.setEnabled(False)
        import_image_dialog.spinBox_rotation.setEnabled(False)
        import_image_dialog.start_path = self.wafer_image_dir

        # pre-filling the ImportImageDialog if wafer image (unique) present
        image_names = [image_name for image_name in os.listdir(self.wafer_image_dir)
                       if ('wafer' in image_name.lower())
                       and (os.path.splitext(image_name)[1] in ['.tif', '.tiff', '.png', '.jpg'])]
        if len(image_names) == 0:
            utils.log_info(
                'Array-CTRL',
                ('No wafer picture was found. '
                    + 'Select the wafer image manually.'))
        elif len(image_names) > 1:
            utils.log_info(
                'Array-CTRL',
                ('There is more than one image available in the folder '
                    + 'containing the array section file.'
                    + 'Select the wafer image manually'))
        elif len(image_names) == 1:
            # pre-fill the import dialog
            image_path = os.path.normpath(
                os.path.join(self.wafer_image_dir, image_names[0]))
            import_image_dialog.lineEdit_fileName.setText(image_path)
            import_image_dialog.lineEdit_name.setText(
                os.path.splitext(
                    os.path.basename(image_path))[0])

        current_imported_number = self.imported.number_imported
        import_image_dialog.exec()

        if self.imported.number_imported == current_imported_number:
            utils.log_info(
                'Array-CTRL',
                ('No wafer image overview was added.'
                    + 'You can still do it by selecting "Import Image"'
                    + 'in the Array tab.'))
        else:
            wafer_image = self.imported[-1]
            wafer_image.centre_sx_sy = np.divide(wafer_image.size, 2).astype(int)
            self.main_controls_trigger.transmit('SHOW IMPORTED')
            self.main_controls_trigger.transmit('DRAW VP')
            utils.log_info(
                'Array-CTRL',
                'Image successfully imported.')

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
        self.lTable = self.tableView_array_landmarkTable
        self.init_landmarks()
        self.pushButton_cancel.clicked.connect(self.accept)
        self.pushButton_validateCalibration.clicked.connect(self.validate_calibration)
        self.show()

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
            source = landmark.get('source')
            target = landmark.get('target')

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
            x,y = self.stage.get_xy()
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
            self.gm.array_data.landmarks[row]['target'] = [x, y]

            # compute transform and update landmarks
            n_landmarks = len(self.gm.array_data.landmarks)

            calibrated_landmark_ids = [
                id for id in self.gm.array_data.landmarks
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

                x_landmarks_source = np.array([
                    self.gm.array_data.landmarks[i]['source'][0]
                    for i in range(n_landmarks)])
                y_landmarks_source = np.array([
                    self.gm.array_data.landmarks[i]['source'][1]
                    for i in range(n_landmarks)])

                # taking only the source landmarks for which there is a
                # corresponding target landmark
                x_landmarks_source_partial = np.array(
                    [self.gm.array_data.landmarks[i]['source'][0]
                     for i in calibrated_landmark_ids])
                y_landmarks_source_partial = np.array(
                    [self.gm.array_data.landmarks[i]['source'][1]
                     for i in calibrated_landmark_ids])

                x_landmarks_target_partial = np.array(
                    [self.gm.array_data.landmarks[i]['target'][0]
                     for i in calibrated_landmark_ids])
                y_landmarks_target_partial = np.array(
                    [self.gm.array_data.landmarks[i]['target'][1]
                     for i in calibrated_landmark_ids])

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
                    self.gm.array_data.landmarks[noncalibrated_landmark_id]['target'] = [x, y]

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
            self.stage.move_to_xy([x,y])

            # move viewport to landmark
            self.cs.vp_centre_dx_dy = self.cs.convert_s_to_d([x,y])
            self.main_controls_trigger.transmit('DRAW VP')

        return callback_goto_landmark

    def validate_calibration(self):
        calibrated_landmark_ids = [
            id for id in self.gm.array_data.landmarks
            if self.lTable.model().item(id, 0).background().color() == GREEN]

        n_landmarks = len(self.gm.array_data.landmarks)

        if len(calibrated_landmark_ids) != n_landmarks:
            utils.log_info(
                'Array-CTRL',
                ('Cannot validate wafer calibration: all target landmarks '
                    +'must first be validated.'))
        else:
            x_landmarks_source = [
                self.gm.array_data.landmarks['source'][i][0]
                for i in range(n_landmarks)]
            y_landmarks_source = [
                self.gm.array_data.landmarks['source'][i][1]
                for i in range(n_landmarks)]

            x_landmarks_target = [
                self.gm.array_data.landmarks['target'][i][0]
                for i in range(n_landmarks)]
            y_landmarks_target = [
                self.gm.array_data.landmarks['target'][i][1]
                for i in range(n_landmarks)]

            flip_x = self.gm.sem.device_name.lower() in [
                    'zeiss merlin',
                    'zeiss sigma',
                    ]

            self.gm.array_data.transform = ArrayData.affine_t(
                x_landmarks_source,
                y_landmarks_source,
                x_landmarks_target,
                y_landmarks_target,
                flip_x=flip_x,
                )

            # compute new grid locations
            # (always transform from reference source)
            n_sections = len(self.gm.array_data.sections)

            # ROI has priority over section:
            # if a ROI is defined:
                # use the ROI
            # else:
                # use the section
            x_source = np.array([
                self.gm.array_data.sections[k]['rois'][0]['center'][0]
                    if 'rois' in self.gm.array_data.sections[k]
                    else self.gm.array_data.sections[k]['sample']['center'][0]
                    for k in sorted(self.gm.array_data.sections)
                    ])
            y_source = np.array([
                self.gm.array_datasections[k]['rois'][0]['center'][1]
                    if 'rois' in self.gm.array_data.sections[k]
                    else self.gm.array_data.sections[k]['sample']['center'][1]
                    for k in sorted(self.gm.array_data.sections)
                    ])

            angles_source = np.array([
                self.gm.array_datasections[k]['rois'][0]['angle']
                    if 'rois' in self.gm.array_data.sections[k]
                    else self.gm.array_data.sections[k]['sample']['angle']
                    for k in sorted(self.gm.array_data.sections)
                    ])

            x_target, y_target = ArrayData.apply_affine_t(
                x_source,
                y_source,
                self.gm.array_data.transform,
                flip_x=flip_x)

            transformAngle = -ArrayData.get_affine_rotation(
                self.gm.array_data.transform)
            angles_target = (angles_source + transformAngle) % 360

            # update grids
            for grid_number in range(self.gm.number_grids):
                self.gm[grid_number].auto_update_tile_positions = False
                self.gm[grid_number].rotation = angles_target[grid_number]
                self.gm[grid_number].update_tile_positions()
                self.gm[grid_number].auto_update_tile_positions = True
                self.gm[grid_number].centre_sx_sy = [
                    x_target[grid_number],
                    y_target[grid_number]]

            self.main_controls_trigger.transmit('DRAW VP')

            # update wafer picture
            if self.imported[0] is not None:
                waferTransformAngle = -ArrayData.get_affine_rotation(
                    self.gm.array_data.transform)
                waferTransformScaling = ArrayData.get_affine_scaling(
                    self.gm.array_data.transform)

                image_center_target_s = ArrayData.apply_affine_t(
                    [self.imported[0].centre_sx_sy[0]],
                    [self.imported[0].centre_sx_sy[1]],
                    self.gm.array_data.transform,
                    flip_x=flip_x)

                image_center_target_s = [float(a[0]) for a in image_center_target_s]

                # image_center_source_v = self.cs.convert_to_v(image_center_source_s)
                # image_center_target_v = array_utils.applyRigidT(
                    # [image_center_source_v[0]],
                    # [image_center_source_v[1]],
                    # waferTransform_v)

                self.imported[0].rotation = (0 - waferTransformAngle) % 360
                self.imported[0].pixel_size = 1000 * waferTransformScaling
                self.imported[0].centre_sx_sy = image_center_target_s
                self.imported[0].flip_x()

            # update drawn image
            self.main_controls_trigger.transmit('DRAW VP')

            # update calibration flag
            self.gm.array_data.calibrated = True
            self.main_controls_trigger.transmit('ARRAY WAFER CALIBRATED')

            self.accept()

    def accept(self):
        super(WaferCalibrationDlg, self).accept()

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
                'ZEN experiment setup (*.json)'
                )[0])
        if len(selected_file) > 0:
            selected_file = os.path.normpath(selected_file)
            if os.path.splitext(selected_file)[1] == '.json':
                self.lineEdit_fileName.setText(selected_file)

    def accept(self):
        super(ImportZENExperimentDlg, self).accept()
