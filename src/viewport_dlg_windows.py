# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This modules contains all dialog windows that are called from the
Viewport."""

import os
import threading
import datetime

from time import time, sleep
from queue import Queue
from PIL import Image

from PyQt5.uic import loadUi
from PyQt5.QtCore import Qt, QObject, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, QFileDialog, \
                            QDialogButtonBox

import utils
import acq_func


class Trigger(QObject):
    """Custom signal for updating GUI from within running threads."""
    s = pyqtSignal()

# ------------------------------------------------------------------------------

class StubOVDlg(QDialog):
    """Acquire a stub overview image. The user can specify the location
       in stage coordinates and the size of the grid.
    """

    def __init__(self, centre_sx_sy, grid_size_selector,
                 sem, stage, ovm, stack, viewport_trigger, viewport_queue):
        super().__init__()
        loadUi('..\\gui\\stub_ov_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.base_dir = stack.base_dir
        self.slice_counter = stack.slice_counter
        self.sem = sem
        self.stage = stage
        self.ovm = ovm
        self.viewport_trigger = viewport_trigger
        self.viewport_queue = viewport_queue
        # Set up trigger and queue to update dialog GUI during approach:
        self.stub_dlg_trigger = Trigger()
        self.stub_dlg_trigger.s.connect(self.process_thread_signal)
        self.stub_dlg_queue = Queue()
        self.abort_queue = Queue()
        self.acq_in_progress = False
        self.pushButton_acquire.clicked.connect(self.acquire_stub_ov)
        self.pushButton_abort.clicked.connect(self.abort)
        self.spinBox_X.setValue(centre_sx_sy[0])
        self.spinBox_Y.setValue(centre_sx_sy[1])
        self.grid_size_selector = grid_size_selector
        self.durations = []

        # Show available grid sizes and the corresponding estimated
        # durations in min
        tile_width = self.ovm['stub'].frame_size[0]
        tile_height = self.ovm['stub'].frame_size[1]
        overlap = self.ovm['stub'].overlap
        pixel_size = self.ovm['stub'].pixel_size
        cycle_time = self.ovm['stub'].tile_cycle_time()
        motor_move_time = self.stage.stage_move_duration(
            *self.ovm['stub'][0].sx_sy, *self.ovm['stub'][1].sx_sy)

        self.grid_size_list = []
        for grid_size in self.ovm['stub'].GRID_SIZE:
            rows, cols = grid_size
            width = int(
                (cols * tile_width - (cols-1) * overlap) * pixel_size / 1000)
            height = int(
                (rows * tile_height - (rows-1) * overlap) * pixel_size / 1000)
            duration = int(round(
                (rows * cols * (cycle_time + motor_move_time)) / 60))

            self.grid_size_list.append(
                str(width) + ' µm × ' + str(height) + ' µm')
            self.durations.append('Up to ~' + str(duration) + ' min')
        # Grid size selection:
        self.comboBox_sizeSelector.addItems(self.grid_size_list)
        self.comboBox_sizeSelector.setCurrentIndex(self.grid_size_selector)
        self.comboBox_sizeSelector.currentIndexChanged.connect(
            self.update_duration)
        self.label_duration.setText(self.durations[self.grid_size_selector])
        self.previous_centre_sx_sy = self.ovm['stub'].centre_sx_sy
        self.previous_grid_size_selector = self.ovm['stub'].grid_size_selector

    def process_thread_signal(self):
        """Process commands from the queue when a trigger signal occurs
           while the acquisition of the stub overview is running.
        """
        msg = self.stub_dlg_queue.get()
        if msg == 'UPDATE XY':
            self.show_new_stage_pos()
        elif msg[:15] == 'UPDATE PROGRESS':
            percentage = int(msg[15:])
            self.progressBar.setValue(percentage)
        elif msg == 'STUB OV SUCCESS':
            self.viewport_queue.put('STUB OV SUCCESS')
            self.viewport_trigger.s.emit()
            self.pushButton_acquire.setEnabled(True)
            self.pushButton_abort.setEnabled(False)
            self.buttonBox.setEnabled(True)
            self.spinBox_X.setEnabled(True)
            self.spinBox_Y.setEnabled(True)
            self.comboBox_sizeSelector.setEnabled(True)
            QMessageBox.information(
                self, 'Stub Overview acquisition complete',
                'The stub overview was completed successfully.',
                QMessageBox.Ok)
            self.acq_in_progress = False
        elif msg == 'STUB OV FAILURE':
            self.viewport_queue.put('STUB OV FAILURE')
            self.viewport_trigger.s.emit()
            # Restore previous origin:
            self.ovm['stub'].centre_sx_sy = self.previous_centre_sx_sy
            self.ovm['stub'].grid_size_selector = (
                self.previous_grid_size_selector)
            QMessageBox.warning(
                self, 'Error during stub overview acquisition',
                'An error occurred during the acquisition of the stub '
                'overview mosaic. The most likely cause are incorrect '
                'settings of the stage X/Y motor ranges or speeds. Home '
                'the stage and check whether the range limits specified '
                'in SBEMimage are correct.',
                QMessageBox.Ok)
            self.acq_in_progress = False
            self.close()
        elif msg == 'STUB OV ABORT':
            self.viewport_queue.put('STATUS IDLE')
            self.viewport_trigger.s.emit()
            # Restore previous origin:
            self.ovm['stub'].centre_sx_sy = self.previous_centre_sx_sy
            self.ovm['stub'].grid_size_selector = (
                self.previous_grid_size_selector)
            QMessageBox.information(
                self, 'Stub Overview acquisition aborted',
                'The stub overview acquisition was aborted.',
                QMessageBox.Ok)
            self.acq_in_progress = False
            self.close()

    def update_duration(self):
        self.label_duration.setText(self.durations[
            self.comboBox_sizeSelector.currentIndex()])

    def show_new_stage_pos(self):
        self.viewport_queue.put('UPDATE XY')
        self.viewport_trigger.s.emit()

    def add_to_log(self, msg):
        self.viewport_queue.put(msg)
        self.viewport_trigger.s.emit()

    def acquire_stub_ov(self):
        """Acquire the stub overview. Acquisition routine runs in
           a thread.
        """
        # Start acquisition only if EHT is on:
        if self.sem.is_eht_on() or True:
            self.acq_in_progress = True
            centre_sx_sy = self.spinBox_X.value(), self.spinBox_Y.value()
            grid_size_selector = self.comboBox_sizeSelector.currentIndex()
            # Change the Stub Overview to the requested grid size and centre
            self.ovm['stub'].grid_size_selector = grid_size_selector
            self.ovm['stub'].centre_sx_sy = centre_sx_sy

            self.add_to_log(
                'CTRL: User-requested acquisition of stub OV mosaic started.')
            self.pushButton_acquire.setEnabled(False)
            self.pushButton_abort.setEnabled(True)
            self.buttonBox.setEnabled(False)
            self.spinBox_X.setEnabled(False)
            self.spinBox_Y.setEnabled(False)
            self.comboBox_sizeSelector.setEnabled(False)
            self.progressBar.setValue(0)
            self.viewport_queue.put('STATUS BUSY STUB')
            self.viewport_trigger.s.emit()
            QApplication.processEvents()
            stub_acq_thread = threading.Thread(
                                  target=acq_func.acquire_stub_ov,
                                  args=(self.base_dir, self.slice_counter,
                                        self.sem, self.stage, self.ovm,
                                        self.stub_dlg_trigger,
                                        self.stub_dlg_queue,
                                        self.abort_queue,))
            stub_acq_thread.start()
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
        loadUi('..\\gui\\wd_gradient_tile_selection_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.grid_illustration.setPixmap(QPixmap('..\\img\\grid.png'))
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

    def __init__(self, selected_grid, gm, cfg,
                 viewport_trigger, viewport_queue):
        self.selected_grid = selected_grid
        self.gm = gm
        self.cfg = cfg
        self.viewport_trigger = viewport_trigger
        self.viewport_queue = viewport_queue
        self.rotation_in_progress = False
        super().__init__()
        loadUi('..\\gui\\change_grid_rotation_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
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
        """Apply the new rotation angle and redraw the viewport"""
        self.time_of_last_rotation = time()
        if not self.rotation_in_progress:
            # Start thread to ensure viewport is drawn with labels and previews
            # after rotation completed.
            self.rotation_in_progress = True
            update_viewport_with_delay_thread = threading.Thread(
                target=self.update_viewport_with_delay,
                args=())
            update_viewport_with_delay_thread.start()
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
        self.viewport_queue.put('DRAW VP NO LABELS')
        self.viewport_trigger.s.emit()

    def draw_with_labels(self):
        self.viewport_queue.put('DRAW VP')
        self.viewport_trigger.s.emit()

    def update_viewport_with_delay(self):
        """Redraw the viewport without suppressing labels/previews after at
        least 0.3 seconds have passed since last update of the rotation angle."""
        finish_trigger = Trigger()
        finish_trigger.s.connect(self.draw_with_labels)
        current_time = self.time_of_last_rotation
        while (current_time - self.time_of_last_rotation < 0.3):
            sleep(0.1)
            current_time += 0.1
        self.rotation_in_progress = False
        finish_trigger.s.emit()

    def reject(self):
        # Revert to previous angle and origin:
        self.gm[self.selected_grid].rotation = self.previous_angle
        self.gm[self.selected_grid].origin_sx_sy = self.previous_origin_sx_sy
        self.viewport_queue.put('DRAW VP')
        self.viewport_trigger.s.emit()
        super().reject()

    def accept(self):
        # Calculate new grid map with new rotation angle:
        self.gm[self.selected_grid].update_tile_positions()
        if self.cfg['sys']['magc_mode'] == 'True':
            self.gm.update_source_ROIs_from_grids()
        super().accept()

# ------------------------------------------------------------------------------

class ImportImageDlg(QDialog):
    """Import an image into the viewport."""

    def __init__(self, imported_images, target_dir):
        self.imported = imported_images
        self.target_dir = target_dir
        super().__init__()
        loadUi('..\\gui\\import_image_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(QIcon('..\\img\\selectdir.png'))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))

    def select_file(self):
        # Let user select image to be imported:
        start_path = 'C:\\'
        selected_file = str(QFileDialog.getOpenFileName(
            self, 'Select image',
            start_path,
            'Images (*.tif *.png *.bmp *.jpg)'
            )[0])
        if len(selected_file) > 0:
            # Replace forward slashes with backward slashes:
            selected_file = selected_file.replace('/', '\\')
            self.lineEdit_fileName.setText(selected_file)
            self.lineEdit_name.setText(
                os.path.splitext(os.path.basename(selected_file))[0])

    def accept(self):
        selection_success = True
        selected_path = self.lineEdit_fileName.text()
        selected_filename = os.path.basename(selected_path)
        timestamp = str(datetime.datetime.now())
        # Remove some characters from timestap to get valid file name:
        timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
        target_path = (self.target_dir + '\\'
                       + os.path.splitext(selected_filename)[0]
                       + '_' + timestamp + '.png')
        if os.path.isfile(selected_path):
            # Copy file to data folder as png:
            try:
                imported_img = Image.open(selected_path)
                imported_img.save(target_path)
            except Exception as e:
                QMessageBox.warning(
                    self, 'Error',
                    'Could not load image file: ' + str(e),
                     QMessageBox.Ok)
                selection_success = False

            if selection_success:
                new_index = self.imported.number_imported
                self.imported.add_image()
                self.imported[new_index].image_src = target_path
                self.imported[new_index].centre_sx_sy = [
                    self.doubleSpinBox_posX.value(),
                    self.doubleSpinBox_posY.value()]
                self.imported[new_index].rotation = (
                    self.spinBox_rotation.value())
                self.imported[new_index].description = (
                    self.lineEdit_name.text())
                width, height = imported_img.size
                self.imported[new_index].size = [width, height]
                self.imported[new_index].pixel_size = (
                    self.doubleSpinBox_pixelSize.value())
                self.imported[new_index].transparency = (
                    self.spinBox_transparency.value())
                if self.imported[new_index].image is None:
                    QMessageBox.warning(
                        self, 'Error',
                        'Could not load image as QPixmap.',
                         QMessageBox.Ok)
        else:
            QMessageBox.warning(self, 'Error',
                                'Specified file not found.',
                                QMessageBox.Ok)
            selection_success = False

        if selection_success:
            super().accept()

# ------------------------------------------------------------------------------

class AdjustImageDlg(QDialog):
    """Adjust an imported image (size, rotation, transparency)"""

    def __init__(self, imported_images, selected_img,
                 viewport_trigger, viewport_queue):
        self.imported = imported_images
        self.viewport_trigger = viewport_trigger
        self.viewport_queue = viewport_queue
        self.selected_img = selected_img
        super().__init__()
        loadUi('..\\gui\\adjust_imported_image_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_selectedImage.setText(
            self.imported[self.selected_img].description)
        pos_x, pos_y = self.imported[self.selected_img].centre_sx_sy
        self.doubleSpinBox_posX.setValue(pos_x)
        self.doubleSpinBox_posY.setValue(pos_y)
        self.doubleSpinBox_pixelSize.setValue(
            self.imported[self.selected_img].pixel_size)
        self.spinBox_rotation.setValue(
            self.imported[self.selected_img].rotation)
        self.spinBox_transparency.setValue(
            self.imported[self.selected_img].transparency)
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
        self.imported[self.selected_img].centre_sx_sy = [
            self.doubleSpinBox_posX.value(),
            self.doubleSpinBox_posY.value()]
        self.imported[self.selected_img].pixel_size = (
            self.doubleSpinBox_pixelSize.value())
        self.imported[self.selected_img].rotation = (
            self.spinBox_rotation.value())
        self.imported[self.selected_img].transparency = (
            self.spinBox_transparency.value())
        # Emit signals to redraw Viewport:
        self.viewport_queue.put('DRAW VP')
        self.viewport_trigger.s.emit()

# ------------------------------------------------------------------------------

class DeleteImageDlg(QDialog):
    """Delete an imported image from the viewport."""

    def __init__(self, imported_images):
        self.imported = imported_images
        super().__init__()
        loadUi('..\\gui\\delete_image_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Populate the list widget with existing imported images:
        img_list = []
        for i in range(self.imported.number_imported):
            img_list.append(str(i) + ' - ' + self.imported[i].description)
        self.listWidget_imagelist.addItems(img_list)

    def accept(self):
        selected_img = self.listWidget_imagelist.currentRow()
        if selected_img is not None:
            self.imported.delete_image(selected_img)
        super().accept()
