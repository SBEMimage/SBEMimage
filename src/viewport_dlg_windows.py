# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This modules contains all dialog windows that are called from the
Viewport."""

import datetime
import os
from queue import Queue
from time import time, sleep

from qtpy.uic import loadUi
from qtpy.QtCore import Qt, QSize
from qtpy.QtGui import QPixmap, QIcon
from qtpy.QtWidgets import QApplication, QDialog, QMessageBox, QFileDialog, \
                           QDialogButtonBox, QListWidgetItem

import acq_func
from image_io import imread, imwrite, imread_metadata
import utils


# ------------------------------------------------------------------------------

class StubOVDlg(QDialog):
    """Acquire a stub overview image. The user can specify the location
    in stage coordinates and the size of the grid.
    """

    def __init__(self, centre_sx_sy,
                 sem, stage, ovm, acq, img_inspector, viewport_trigger):
        super().__init__()
        loadUi('../gui/stub_ov_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.sem = sem
        self.stage = stage
        self.ovm = ovm
        self.acq = acq
        self.img_inspector = img_inspector
        self.viewport_trigger = viewport_trigger
        self.acq_in_progress = False
        self.error_msg_from_acq_thread = ''

        # Set up trigger and queue to update dialog GUI during acquisition
        self.stub_dlg_trigger = utils.Trigger()
        self.stub_dlg_trigger.signal.connect(self.process_thread_signal)
        self.abort_queue = Queue()
        self.pushButton_acquire.clicked.connect(self.start_stub_ov_acquisition)
        self.pushButton_abort.clicked.connect(self.abort)
        self.checkBox_LmMode.setEnabled(self.sem.has_lm_mode())
        self.checkBox_LmMode.stateChanged.connect(self.update_settings_from_ovm)
        self.update_settings_from_ovm()
        self.spinBox_X.setValue(int(round(centre_sx_sy[0])))
        self.spinBox_Y.setValue(int(round(centre_sx_sy[1])))
        self.spinBox_rows.valueChanged.connect(
            self.update_dimension_and_duration_display)
        self.spinBox_cols.valueChanged.connect(
            self.update_dimension_and_duration_display)
        self.spinBox_magnification.valueChanged.connect(
            self.set_magnification)
        # Save previous settings. If user aborts the stub OV acquisition
        # revert to these settings.
        stub_ovm = self.get_selected_stub_ovm()
        self.previous_lm_mode = self.checkBox_LmMode.isChecked()
        self.previous_centre_sx_sy = stub_ovm.centre_sx_sy
        self.previous_grid_size = stub_ovm.size

    def process_thread_signal(self):
        """Process commands from the queue when a trigger signal occurs
        while the acquisition of the stub overview is running.
        """
        cmd = self.stub_dlg_trigger.queue.get()
        msg = cmd['msg']
        args = cmd['args']
        kwargs = cmd['kwargs']
        if msg == 'UPDATE XY':
            self.viewport_trigger.transmit('UPDATE XY')
        elif msg == 'DRAW VP':
            self.viewport_trigger.transmit('DRAW VP')
        elif msg == 'UPDATE PROGRESS':
            percentage = int(str(args[0]))
            self.progressBar.setValue(percentage)
        elif msg == 'STUB OV SUCCESS':
            self.viewport_trigger.transmit('STUB OV SUCCESS')
            self.pushButton_acquire.setEnabled(True)
            self.pushButton_abort.setEnabled(False)
            self.buttonBox.setEnabled(True)
            self.spinBox_X.setEnabled(True)
            self.spinBox_Y.setEnabled(True)
            self.spinBox_rows.setEnabled(True)
            self.spinBox_cols.setEnabled(True)
            QMessageBox.information(
                self, 'Stub Overview acquisition complete',
                'The stub overview was completed successfully.',
                QMessageBox.Ok)
            self.acq_in_progress = False
            self.close()
        elif msg == 'STUB OV FAILURE':
            self.viewport_trigger.transmit('STUB OV FAILURE')
            QMessageBox.warning(
                self, 'Error during stub overview acquisition',
                'An error occurred during the acquisition of the stub '
                'overview mosaic: ' + self.error_msg_from_acq_thread,
                QMessageBox.Ok)
            self.error_msg_from_acq_thread = ''
            self.acq_in_progress = False
            self.close()
        elif msg == 'STUB OV ABORT':
            self.viewport_trigger.transmit('STATUS IDLE')
            # Restore previous grid size and grid position
            stub_ovm = self.get_selected_stub_ovm(self.previous_lm_mode)
            stub_ovm.size = self.previous_grid_size
            stub_ovm.centre_sx_sy = self.previous_centre_sx_sy
            QMessageBox.information(
                self, 'Stub Overview acquisition aborted',
                'The stub overview acquisition was aborted.',
                QMessageBox.Ok)
            self.acq_in_progress = False
            self.close()
        else:
            # Use as error message
            self.error_msg_from_acq_thread = msg

    def get_selected_stub_ovm(self, lm_mode=None):
        if lm_mode is None:
            lm_mode = self.checkBox_LmMode.isChecked()
        if lm_mode:
            stub_ovm = self.ovm['stub_lm']
        else:
            stub_ovm = self.ovm['stub']
        return stub_ovm

    def set_magnification(self):
        stub_ovm = self.get_selected_stub_ovm()
        magnification = self.spinBox_magnification.value()
        stub_ovm.pixel_size = self.sem.MAG_PX_SIZE_FACTOR / (magnification * stub_ovm.frame_size[0])
        self.update_dimension_and_duration_display()

    def update_settings_from_ovm(self):
        stub_ovm = self.get_selected_stub_ovm()
        magnification = int(self.sem.MAG_PX_SIZE_FACTOR / (stub_ovm.frame_size[0] * stub_ovm.pixel_size))
        self.spinBox_magnification.setValue(magnification)
        self.spinBox_rows.setValue(stub_ovm.size[0])
        self.spinBox_cols.setValue(stub_ovm.size[1])
        self.update_dimension_and_duration_display()

    def update_dimension_and_duration_display(self):
        rows = self.spinBox_rows.value()
        cols = self.spinBox_cols.value()
        stub_ovm = self.get_selected_stub_ovm()
        tile_width = stub_ovm.frame_size[0]
        tile_height = stub_ovm.frame_size[1]
        overlap = stub_ovm.overlap
        pixel_size = stub_ovm.pixel_size
        cycle_time = stub_ovm.tile_cycle_time()
        motor_move_time = 0
        if len(stub_ovm) >= 2:
            ov0, ov1 = stub_ovm[0], stub_ovm[1]
            if ov0 is not None and ov1 is not None:
                motor_move_time = self.stage.stage_move_duration(*ov0.sx_sy, *ov1.sx_sy)
        width = int(
            (cols * tile_width - (cols - 1) * overlap) * pixel_size / 1000)
        height = int(
            (rows * tile_height - (rows - 1) * overlap) * pixel_size / 1000)
        duration = int(round(
            (rows * cols * (cycle_time + motor_move_time) + 30) / 60))
        dimension_str = str(width) + ' µm × ' + str(height) + ' µm'
        duration_str = 'Up to ~' + str(duration) + ' min'
        self.label_dimension.setText(dimension_str)
        self.label_duration.setText(duration_str)

    def start_stub_ov_acquisition(self):
        """Acquire the stub overview. Acquisition routine runs in a thread."""
        lm_mode = self.checkBox_LmMode.isChecked()
        # Start acquisition if EHT is on
        if lm_mode or self.sem.is_eht_on():
            self.acq_in_progress = True
            centre_sx_sy = self.spinBox_X.value(), self.spinBox_Y.value()
            grid_size = [self.spinBox_rows.value(), self.spinBox_cols.value()]
            # Change the Stub Overview to the requested grid size and centre
            stub_ovm = self.get_selected_stub_ovm()
            if lm_mode:
                # get correct pixel size value for discrete LM FOV steps
                self.sem.set_em_mode(lm_mode=True)
                self.sem.apply_frame_settings(stub_ovm.frame_size_selector, stub_ovm.pixel_size, stub_ovm.dwell_time)
                stub_ovm.pixel_size = self.sem.get_pixel_size()
            stub_ovm.size = grid_size               # triggers tiles update
            stub_ovm.centre_sx_sy = centre_sx_sy    # triggers tiles update
            self.viewport_trigger.transmit(
                'CTRL: Acquisition of stub overview image started.')
            self.pushButton_acquire.setEnabled(False)
            self.pushButton_abort.setEnabled(True)
            self.buttonBox.setEnabled(False)
            self.spinBox_X.setEnabled(False)
            self.spinBox_Y.setEnabled(False)
            self.spinBox_rows.setEnabled(False)
            self.spinBox_cols.setEnabled(False)
            self.progressBar.setValue(0)
            self.viewport_trigger.transmit('STATUS BUSY STUB')
            QApplication.processEvents()
            utils.run_log_thread(acq_func.acquire_stub_ov,
                                 self.sem, self.stage,
                                 stub_ovm, self.acq,
                                 self.img_inspector,
                                 self.stub_dlg_trigger,
                                 self.abort_queue)
        else:
            QMessageBox.warning(
                self, 'EHT off',
                'EHT / high voltage is off. Please turn '
                'it on before starting the acquisition.',
                QMessageBox.Ok)

    def abort(self):
        if self.abort_queue.empty():
            self.abort_queue.put('ABORT')
            self.pushButton_abort.setEnabled(False)

    def closeEvent(self, event):
        if not self.acq_in_progress:
            event.accept()
        else:
            event.ignore()


# ------------------------------------------------------------------------------

class FocusGradientTileSelectionDlg(QDialog):

    def __init__(self, current_ref_tiles):
        super().__init__()
        self.selected = None
        loadUi('../gui/wd_gradient_tile_selection_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.grid_illustration.setPixmap(QPixmap('../img/grid.png'))
        if current_ref_tiles[0] >= 0:
            self.pushButton_pos0.setText(str(current_ref_tiles[0]))
        else:
            self.pushButton_pos0.setText('-')
        if current_ref_tiles[1] >= 0:
            self.pushButton_pos1.setText(str(current_ref_tiles[1]))
        else:
            self.pushButton_pos1.setText('-')
        if current_ref_tiles[2] >= 0:
            self.pushButton_pos2.setText(str(current_ref_tiles[2]))
        else:
            self.pushButton_pos2.setText('-')
        self.pushButton_pos0.clicked.connect(self.select_pos0)
        self.pushButton_pos1.clicked.connect(self.select_pos1)
        self.pushButton_pos2.clicked.connect(self.select_pos2)

    def select_pos0(self):
        self.selected = 0
        super().accept()

    def select_pos1(self):
        self.selected = 1
        super().accept()

    def select_pos2(self):
        self.selected = 2
        super().accept()


# ------------------------------------------------------------------------------
class GridRotationDlg(QDialog):
    """Change the rotation angle of a selected grid."""

    def __init__(self, selected_grid, gm, viewport_trigger, magc_mode=False):
        self.selected_grid = selected_grid
        self.gm = gm
        self.viewport_trigger = viewport_trigger
        self.magc_mode = magc_mode
        self.rotation_in_progress = False
        self.gm[self.selected_grid].auto_update_tile_positions = False
        super().__init__()
        loadUi('../gui/change_grid_rotation_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.label_description.setText(
            f'Rotation of selected grid {self.selected_grid} in degrees:')

        # Keep current angle and origin to enable undo option
        self.previous_angle = self.gm[selected_grid].rotation
        self.previous_origin_sx_sy = self.gm[selected_grid].origin_sx_sy
        # Set initial values:
        self.doubleSpinBox_angle.setValue(self.previous_angle)
        # Slider value 0..719 (twice the angle in degrees) for 0.5 degree steps
        self.horizontalSlider_angle.setValue(
            self.doubleSpinBox_angle.value() * 2)

        self.horizontalSlider_angle.valueChanged.connect(self.update_spinbox)
        self.doubleSpinBox_angle.valueChanged.connect(self.update_slider)

    def keyPressEvent(self, event):
        # Catch KeyPressEvent when user presses Enter (otherwise dialog would exit.)
        if event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
            event.accept()

    def update_spinbox(self):
        self.doubleSpinBox_angle.blockSignals(True)
        self.doubleSpinBox_angle.setValue(
            self.horizontalSlider_angle.value() / 2)
        self.doubleSpinBox_angle.blockSignals(False)
        self.update_grid()

    def update_slider(self):
        self.horizontalSlider_angle.blockSignals(True)
        self.horizontalSlider_angle.setValue(
            self.doubleSpinBox_angle.value() * 2)
        self.horizontalSlider_angle.blockSignals(False)
        self.update_grid()

    def update_grid(self):
        """Apply the new rotation angle and redraw the viewport."""
        self.time_of_last_rotation = time()
        if not self.rotation_in_progress:
            # Start thread to ensure viewport is drawn with labels and previews
            # after rotation completed.
            self.rotation_in_progress = True
            utils.run_log_thread(self.update_viewport_with_delay)
        if self.radioButton_pivotCentre.isChecked():
            # Get current centre of grid:
            centre_dx, centre_dy = self.gm[self.selected_grid].centre_dx_dy
            # Set new angle
            self.gm[self.selected_grid].rotation = self.doubleSpinBox_angle.value()
            self.gm[self.selected_grid].rotate_around_grid_centre(centre_dx, centre_dy)
        else:
            self.gm[self.selected_grid].rotation = self.doubleSpinBox_angle.value()
        # Update tile positions:
        self.gm[self.selected_grid].update_tile_positions()
        # Emit signal to redraw:
        self.viewport_trigger.transmit('DRAW VP NO LABELS')

    def draw_with_labels(self):
        self.viewport_trigger.transmit('DRAW VP')

    def update_viewport_with_delay(self):
        """Redraw the viewport without suppressing labels/previews after at
        least 0.3 seconds have passed since last update of the rotation angle."""
        finish_trigger = utils.Trigger()
        finish_trigger.signal.connect(self.draw_with_labels)
        current_time = self.time_of_last_rotation
        while (current_time - self.time_of_last_rotation < 0.3):
            sleep(0.1)
            current_time += 0.1
        self.rotation_in_progress = False
        finish_trigger.signal.emit()

    def reject(self):
        # Revert to previous angle and origin:
        self.gm[self.selected_grid].rotation = self.previous_angle
        self.gm[self.selected_grid].origin_sx_sy = self.previous_origin_sx_sy
        self.viewport_trigger.transmit('DRAW VP')
        super().reject()

    def accept(self):
        # Calculate new grid map with new rotation angle
        self.gm[self.selected_grid].update_tile_positions()
        if self.magc_mode:
            self.gm.array_write()
        # Restore default behaviour for updating tile positions
        self.gm[self.selected_grid].auto_update_tile_positions = True
        super().accept()


# ------------------------------------------------------------------------------
class TemplateRotationDlg(QDialog):
    """Change the rotation angle of a selected grid."""

    def __init__(self, tm, viewport_trigger):
        self.template = tm.template
        self.tm = tm
        self.viewport_trigger = viewport_trigger
        self.rotation_in_progress = False
        super().__init__()
        loadUi('../gui/change_grid_rotation_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.label_description.setText(
            f'Rotation of selected grid template in degrees:')

        # Keep current angle and origin to enable undo option
        self.previous_angle = self.template.rotation
        self.previous_origin_sx_sy = self.template.origin_sx_sy
        # Set initial values:
        self.doubleSpinBox_angle.setValue(self.previous_angle)
        # Slider value 0..719 (twice the angle in degrees) for 0.5 degree steps
        self.horizontalSlider_angle.setValue(
            self.doubleSpinBox_angle.value() * 2)

        self.horizontalSlider_angle.valueChanged.connect(self.update_spinbox)
        self.doubleSpinBox_angle.valueChanged.connect(self.update_slider)

    def keyPressEvent(self, event):
        # Catch KeyPressEvent when user presses Enter (otherwise dialog would exit.)
        if event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
            event.accept()

    def update_spinbox(self):
        self.doubleSpinBox_angle.blockSignals(True)
        self.doubleSpinBox_angle.setValue(
            self.horizontalSlider_angle.value() / 2)
        self.doubleSpinBox_angle.blockSignals(False)
        self.update_template()

    def update_slider(self):
        self.horizontalSlider_angle.blockSignals(True)
        self.horizontalSlider_angle.setValue(
            self.doubleSpinBox_angle.value() * 2)
        self.horizontalSlider_angle.blockSignals(False)
        self.update_template()

    def update_template(self):
        """Apply the new rotation angle and redraw the viewport."""
        self.time_of_last_rotation = time()
        if not self.rotation_in_progress:
            # Start thread to ensure viewport is drawn with labels and previews
            # after rotation completed.
            self.rotation_in_progress = True
            utils.run_log_thread(self.update_viewport_with_delay)
        if self.radioButton_pivotCentre.isChecked():
            # Get current centre of grid:
            centre_dx, centre_dy = self.template.centre_dx_dy
            # Set new angle
            self.template.rotation = self.doubleSpinBox_angle.value()
            self.template.rotate_around_grid_centre(centre_dx, centre_dy)
        else:
            self.template.rotation = self.doubleSpinBox_angle.value()
        # Emit signal to redraw:
        self.viewport_trigger.transmit('DRAW VP NO LABELS')

    def draw_with_labels(self):
        self.viewport_trigger.transmit('DRAW VP')

    def update_viewport_with_delay(self):
        """Redraw the viewport without suppressing labels/previews after at
        least 0.3 seconds have passed since last update of the rotation angle."""
        finish_trigger = utils.Trigger()
        finish_trigger.signal.connect(self.draw_with_labels)
        current_time = self.time_of_last_rotation
        while current_time - self.time_of_last_rotation < 0.3:
            sleep(0.1)
            current_time += 0.1
        self.rotation_in_progress = False
        finish_trigger.signal.emit()

    def reject(self):
        # Revert to previous angle and origin:
        self.template.rotation = self.previous_angle
        self.template.origin_sx_sy = self.previous_origin_sx_sy
        self.viewport_trigger.transmit('DRAW VP')
        super().reject()

    def accept(self):
        self.tm.calc_img_arr()
        super().accept()


# ------------------------------------------------------------------------------
class ImportImageDlg(QDialog):
    """Import an image into the viewport."""

    def __init__(self, imported_images, viewport_trigger, start_path=None):
        self.start_path = start_path
        self.imported = imported_images
        self.viewport_trigger = viewport_trigger
        super().__init__()
        loadUi('../gui/import_image_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(QIcon('../img/selectdir.png'))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))

    def select_file(self):
        # Let user select image to be imported:
        if self.start_path:
            start_path = self.start_path
        else:
            start_path = 'C:/'
        selected_file = str(QFileDialog.getOpenFileName(
            self, 'Select image',
            start_path,
            filter='Images (*)'
            )[0])

        if selected_file:
            selected_file = os.path.normpath(selected_file)
            self.start_path = selected_file
            self.lineEdit_fileName.setText(selected_file)
            self.lineEdit_name.setText(
                utils.get_image_file_title(selected_file))
            try:
                metadata = imread_metadata(selected_file)
                pixel_size = metadata.get('pixel_size')
                if pixel_size:
                    pxel_size_nm = pixel_size[0] * 1e3
                    self.doubleSpinBox_pixelSize.setValue(pxel_size_nm)
                position = metadata.get('position')
                if position:
                    self.doubleSpinBox_posX.setValue(position[0])
                    self.doubleSpinBox_posY.setValue(position[1])
                rotation = metadata.get('rotation')
                if rotation is not None:
                    self.doubleSpinBox_rotation.setValue(rotation)
            except TypeError:
                QMessageBox.critical(self,
                                     'SBEMimage error',
                                     f'Unsupported image format: {selected_file}',
                                     QMessageBox.Ok)

    def accept(self):
        import_success = False
        error_msg = ''
        pixel_size = self.doubleSpinBox_pixelSize.value()
        selected_path = os.path.normpath(
            self.lineEdit_fileName.text())
        selected_filename = os.path.basename(selected_path)
        timestamp = str(datetime.datetime.now())
        # Remove extra characters from timestamp:
        timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
        filename, ext = selected_filename.split('.', 1)
        # format conversion
        if ext.lower() == 'zarr':
            ext = 'ome.zarr'
        elif not ext.lower() == 'ome.zarr':
            ext = 'ome.tif'
        if os.path.isfile(selected_path):
            try:
                metadata = imread_metadata(selected_path)
                size = metadata['size'][0] * metadata['size'][1]
                if size > 10 * 1e6:
                    # if image dimension > 10MP scale down
                    target_pixel_size_um = [2, 2]   # reduced pixel size
                    metadata['pixel_size'] = target_pixel_size_um
                else:
                    target_pixel_size_um = None

                new_source_pixel_size = metadata.get('pixel_size')
                if new_source_pixel_size:
                    pixel_size = new_source_pixel_size[0] * 1e3  # um -> nm
                else:
                    metadata['pixel_size'] = [pixel_size * 1e-3] * 2  # nm -> um

                image = imread(selected_path, target_pixel_size_um=target_pixel_size_um,
                               render=False)
                target_path = os.path.join(
                    self.imported.target_dir,
                    filename)

                target_path += '_' + timestamp + '.' + ext

                imwrite(target_path, image, metadata=metadata, npyramid_add=4, pyramid_downsample=2)

                centre_sx_sy = [self.doubleSpinBox_posX.value(), self.doubleSpinBox_posY.value()]
                rotation = self.doubleSpinBox_rotation.value()
                flipped = self.checkBox_flipped.isChecked()
                transparency = self.doubleSpinBox_transparency.value()
                description = self.lineEdit_name.text()
                imported_image = self.imported.add_image(target_path, description, centre_sx_sy, rotation, flipped,
                                                         [], pixel_size, True, transparency)
                if imported_image.image is not None:
                    import_success = True

            except Exception as e:
                error_msg = str(e)

        if import_success:
            self.viewport_trigger.transmit('SHOW IMPORTED')
            super().accept()
        else:
            QMessageBox.warning(
                self, 'Error',
                'Error importing image file: ' + error_msg,
                QMessageBox.Ok)


# ------------------------------------------------------------------------------

class ModifyImagesDlg(QDialog):
    """Modify imported images from the viewport."""

    def __init__(self, imported_images, viewport_trigger):
        self.imported = imported_images
        self.viewport_trigger = viewport_trigger
        super().__init__()
        loadUi('../gui/modify_images_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.pushButton_import.clicked.connect(self.import_image)
        self.pushButton_delete.clicked.connect(self.delete_imported)
        self.pushButton_modify.clicked.connect(self.modify_imported)
        self.populate_image_list()

    def populate_image_list(self):
        # Populate the list widget with existing imported images:
        #self.listWidget_imagelist.itemChanged.disconnect()
        self.listWidget_imagelist.clear()
        for index, imported_image in enumerate(self.imported):
            item = QListWidgetItem(str(index) + ' - ' + imported_image.description)
            item.setCheckState(Qt.CheckState.Checked)
            self.listWidget_imagelist.addItem(item)
        self.listWidget_imagelist.itemChanged.connect(self.item_changed)

    def item_changed(self, item):
        index = self.listWidget_imagelist.row(item)
        checked = (item.checkState() == Qt.CheckState.Checked)
        self.imported[index].enabled = checked
        self.viewport_trigger.transmit('DRAW VP')

    def import_image(self):
        dialog = ImportImageDlg(self.imported, self.viewport_trigger)
        if dialog.exec():
            self.populate_image_list()
            self.viewport_trigger.transmit('DRAW VP')

    def delete_imported(self):
        index = self.listWidget_imagelist.currentRow()
        if index is not None:
            self.imported.delete_image(index)
            self.populate_image_list()
            self.viewport_trigger.transmit('DRAW VP')

    def modify_imported(self):
        index = self.listWidget_imagelist.currentRow()
        if index is not None:
            selected_image = self.imported[index]
            dialog = ModifyImageDlg(selected_image,
                                    self.viewport_trigger)
            dialog.exec()


# ------------------------------------------------------------------------------

class ModifyImageDlg(QDialog):
    """Modify an imported image (size, rotation, transparency)"""

    def __init__(self, selected_image,
                 viewport_trigger):
        self.viewport_trigger = viewport_trigger
        self.selected_image = selected_image
        super().__init__()
        loadUi('../gui/modify_image_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())

        self.lineEdit_selectedImage.setText(
            self.selected_image.description)
        pos_x, pos_y = self.selected_image.centre_sx_sy
        self.doubleSpinBox_posX.setValue(pos_x)
        self.doubleSpinBox_posY.setValue(pos_y)
        self.doubleSpinBox_pixelSize.setValue(
            self.selected_image.pixel_size)
        self.doubleSpinBox_rotation.setValue(
            self.selected_image.rotation)
        self.checkBox_flipped.setChecked(
            self.selected_image.flipped)
        self.doubleSpinBox_transparency.setValue(
            self.selected_image.transparency)
        # Use "Apply" button to show changes in viewport
        apply_button = self.buttonBox.button(QDialogButtonBox.Apply)
        cancel_button = self.buttonBox.button(QDialogButtonBox.Cancel)
        cancel_button.setAutoDefault(False)
        cancel_button.setDefault(False)
        apply_button.setDefault(True)
        apply_button.setAutoDefault(True)
        apply_button.clicked.connect(self.apply_changes)

    def apply_changes(self):
        """Apply the current settings and redraw the image in the viewport."""
        self.selected_image.centre_sx_sy = [
            self.doubleSpinBox_posX.value(),
            self.doubleSpinBox_posY.value()]
        self.selected_image.pixel_size = (
            self.doubleSpinBox_pixelSize.value())
        self.selected_image.rotation = (
            self.doubleSpinBox_rotation.value())
        self.selected_image.flipped = (
            self.checkBox_flipped.isChecked())
        self.selected_image.transparency = (
            self.doubleSpinBox_transparency.value())
        self.selected_image.update_image()
        # Emit signals to redraw Viewport:
        self.viewport_trigger.transmit('DRAW VP')
