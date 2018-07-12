# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module contains all dialog windows."""

import os
import shutil
import re
import string
import threading
import datetime
import glob
import json
import validators
from random import random
from time import sleep, time
from validate_email import validate_email
from math import atan, sqrt
from queue import Queue
from PIL import Image

from PyQt5.uic import loadUi
from PyQt5.QtCore import Qt, QObject, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon, QPalette, QColor, QFont
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, \
                            QFileDialog, QLineEdit, QDialogButtonBox

import utils
import acq_func


class Trigger(QObject):
    """Custom signal for updating GUI from within running threads."""
    s = pyqtSignal()

#------------------------------------------------------------------------------

class ConfigDlg(QDialog):
    """Ask the user to select a configuration file. The previously used
       configuration is preselected in the list widget. If no previously used
       configuration found, use default.ini. If status.dat does not exists,
       show warning message box."""

    def __init__(self, VERSION):
        super(ConfigDlg, self).__init__()
        loadUi('..\\gui\\config_dlg.ui', self)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.label_version.setText('Version ' + VERSION)
        self.labelIcon.setPixmap(QPixmap('..\\img\\logo.png'))
        self.label_website.setText('<a href="https://github.com/SBEMimage">'
                                   'https://github.com/SBEMimage</a>')
        self.label_website.setOpenExternalLinks(True)
        self.setFixedSize(self.size())
        self.show()
        self.abort = False
        # Populate the list widget with existing .ini files
        inifile_list = []
        for file in os.listdir('..\\cfg'):
            if file.endswith('.ini'):
                inifile_list.append(file)
        self.listWidget_filelist.addItems(inifile_list)
        # Which .ini file was used previously? Check in status.dat
        if os.path.isfile('..\\cfg\\status.dat'):
            status_file = open('..\\cfg\\status.dat', 'r')
            last_inifile = status_file.readline()
            status_file.close()
            try:
                last_item_used = self.listWidget_filelist.findItems(
                    last_inifile, Qt.MatchExactly)[0]
                self.listWidget_filelist.setCurrentItem(last_item_used)
            except:
                # If the file indicated in status.dat does not exist,
                # select default.ini.
                # This dialog is called from SBEMimage.py only if default.ini
                # is found in cfg directory.
                default_item = self.listWidget_filelist.findItems(
                    'default.ini', Qt.MatchExactly)[0]
                self.listWidget_filelist.setCurrentItem(default_item)
        else:
            # If status.dat does not exists, the program crashed or a second
            # instance is running. Display a warning and select default.ini
            default_item = self.listWidget_filelist.findItems(
                'default.ini', Qt.MatchExactly)[0]
            self.listWidget_filelist.setCurrentItem(default_item)
            QMessageBox.warning(
                self, 'Problem detected: Crash or other SBEMimage instance '
                'running',
                'WARNING: SBEMimage appears to have crashed during the '
                'previous run, or there is already another instance of '
                'SBEMimage running. Please either close the other instance '
                'or abort this one.\n\n'
                'If you are restarting a stack after a crash, doublecheck '
                'all settings before restarting!',
                QMessageBox.Ok)

    def reject(self):
        self.abort = True
        super(ConfigDlg, self).reject()

    def get_ini_file(self):
        if not self.abort:
            return self.listWidget_filelist.currentItem().text()
        else:
            return 'abort'

#------------------------------------------------------------------------------

class SaveConfigDlg(QDialog):
    """Save current configuration in a new config file."""

    def __init__(self):
        super(SaveConfigDlg, self).__init__()
        loadUi('..\\gui\\save_config_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_cfgFileName.setText('')
        self.file_name = None

    def get_file_name(self):
        return self.file_name

    def accept(self):
        # Replace spaces in file name with underscores.
        without_spaces = self.lineEdit_cfgFileName.text().replace(' ', '_')
        self.lineEdit_cfgFileName.setText(without_spaces)
        # Check whether characters in name are permitted.
        # Use may not overwrite "default.ini"
        reg = re.compile('^[a-zA-Z0-9_-]+$')
        if (reg.match(self.lineEdit_cfgFileName.text())
            and self.lineEdit_cfgFileName.text().lower != 'default'):
            self.file_name = self.lineEdit_cfgFileName.text() + '.ini'
            super(SaveConfigDlg, self).accept()
        else:
            QMessageBox.warning(
                self, 'Error',
                'Name contains forbidden characters.',
                QMessageBox.Ok)

#------------------------------------------------------------------------------

class SEMSettingsDlg(QDialog):
    """Let user change SEM beam settings (target EHT, taget beam current).
       Display current working distance and stigmation.
    """
    def __init__(self, sem):
        super(SEMSettingsDlg, self).__init__()
        self.sem = sem
        loadUi('..\\gui\\sem_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Display current target settings:
        self.doubleSpinBox_EHT.setValue(self.sem.get_eht())
        self.spinBox_beamCurrent.setValue(self.sem.get_beam_current())
        # Display current focus/stig:
        self.lineEdit_currentFocus.setText(
            '{0:.6f}'.format(sem.get_wd() * 1000))
        self.lineEdit_currentStigX.setText('{0:.6f}'.format(sem.get_stig_x()))
        self.lineEdit_currentStigY.setText('{0:.6f}'.format(sem.get_stig_y()))

    def accept(self):
        self.sem.set_eht(self.doubleSpinBox_EHT.value())
        self.sem.set_beam_current(self.spinBox_beamCurrent.value())
        super(SEMSettingsDlg, self).accept()

#------------------------------------------------------------------------------

class MicrotomeSettingsDlg(QDialog):
    """Adjust stage motor limits and wait interval after stage moves."""

    def __init__(self, microtome):
        super(MicrotomeSettingsDlg, self).__init__()
        self.microtome = microtome
        loadUi('..\\gui\\microtome_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()

        # Display settings that can only be changed in DM:
        self.lineEdit_knifeCutSpeed.setText(
            str(self.microtome.get_knife_cut_speed()))
        self.lineEdit_knifeRetractSpeed.setText(
            str(self.microtome.get_knife_retract_speed()))
        self.checkBox_useOscillation.setChecked(
            self.microtome.is_oscillation_enabled())
        # Settings changeable in GUI:
        self.doubleSpinBox_waitInterval.setValue(
            self.microtome.get_stage_move_wait_interval())
        current_motor_limits = self.microtome.get_motor_limits()
        self.spinBox_stageMinX.setValue(current_motor_limits[0])
        self.spinBox_stageMaxX.setValue(current_motor_limits[1])
        self.spinBox_stageMinY.setValue(current_motor_limits[2])
        self.spinBox_stageMaxY.setValue(current_motor_limits[3])

        # Other settings that can be changed in SBEMimage,
        # but in a different dialog (CalibrationDgl):
        current_calibration = self.microtome.get_stage_calibration()
        self.lineEdit_scaleFactorX.setText(str(current_calibration[0]))
        self.lineEdit_scaleFactorY.setText(str(current_calibration[1]))
        self.lineEdit_rotationX.setText(str(current_calibration[2]))
        self.lineEdit_rotationY.setText(str(current_calibration[3]))
        # Motor speeds:
        speed_x, speed_y = self.microtome.get_motor_speed_calibration()
        self.lineEdit_speedX.setText(str(speed_x))
        self.lineEdit_speedY.setText(str(speed_y))

    def accept(self):
        self.microtome.set_stage_move_wait_interval(
            self.doubleSpinBox_waitInterval.value())
        self.microtome.set_motor_limits([
            self.spinBox_stageMinX.value(), self.spinBox_stageMaxX.value(),
            self.spinBox_stageMinY.value(), self.spinBox_stageMaxY.value()])
        super(MicrotomeSettingsDlg, self).accept()

#------------------------------------------------------------------------------

class CalibrationDlg(QDialog):
    """Calibrate the stage (rotation and scaling) and the motor speeds."""

    def __init__(self, config, microtome, sem):
        super(CalibrationDlg, self).__init__()
        self.base_dir = config['acq']['base_dir']
        self.microtome = microtome
        self.sem = sem
        self.current_eht = self.sem.get_eht()
        loadUi('..\\gui\\calibration_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_EHT.setText('{0:.2f}'.format(self.current_eht))
        params = self.microtome.get_stage_calibration()
        self.doubleSpinBox_stageScaleFactorX.setValue(params[0])
        self.doubleSpinBox_stageScaleFactorY.setValue(params[1])
        self.doubleSpinBox_stageRotationX.setValue(params[2])
        self.doubleSpinBox_stageRotationY.setValue(params[3])
        speed_x, speed_y = self.microtome.get_motor_speed_calibration()
        self.doubleSpinBox_motorSpeedX.setValue(speed_x)
        self.doubleSpinBox_motorSpeedY.setValue(speed_y)
        self.pushButton_startImageAcq.clicked.connect(
            self.acquire_calibration_images)
        if config['sys']['simulation_mode'] == 'True':
            self.pushButton_startImageAcq.setEnabled(False)
        self.pushButton_calcStage.clicked.connect(
            self.calculate_stage_parameters)
        self.pushButton_calcMotor.clicked.connect(
            self.calculate_motor_parameters)

    def calculate_motor_parameters(self):
        """Calculate the motor speeds from the duration measurements provided
           by the user and let user confirm the new speeds."""
        duration_x = self.doubleSpinBox_durationX.value()
        duration_y = self.doubleSpinBox_durationY.value()
        motor_speed_x = 1000 / duration_x
        motor_speed_y = 1000 / duration_y
        user_choice = QMessageBox.information(
            self, 'Calculated parameters',
            'Results:\nMotor speed X: ' + '{0:.2f}'.format(motor_speed_x)
            + ';\nMotor speed Y: ' + '{0:.2f}'.format(motor_speed_y)
            + '\n\nDo you want to use these values?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_choice == QMessageBox.Ok:
            self.doubleSpinBox_motorSpeedX.setValue(motor_speed_x)
            self.doubleSpinBox_motorSpeedY.setValue(motor_speed_y)

    def acquire_calibration_images(self):
        """Acquire three images to be used for the stage calibration"""
        # TODO: error handling!
        reply = QMessageBox.information(
            self, 'Acquire calibration images',
            'Three images will be acquired and saved in the base '
            'directory: start.tif, shift_x.tif, shift_y.tif. '
            'The current stage position will be used as a starting point.',
            QMessageBox.Ok | QMessageBox.Cancel)
        if reply == QMessageBox.Ok:
            thread = threading.Thread(target=self.acq_thread)
            thread.start()

    def acq_thread(self):
        """Acquisition thread for three images used for the stage calibration.
           Frame settings are fixed for now. Currently no error handling.
        """
        shift = self.spinBox_shift.value()
        self.sem.apply_frame_settings(4, 10, 0.8)
        start_x, start_y = self.microtome.get_stage_xy(1)
        # First image:
        self.sem.acquire_frame(self.base_dir + '\\start.tif')
        # X shift:
        self.microtome.move_stage_to_xy((start_x + shift, start_y))
        # Second image:
        self.sem.acquire_frame(self.base_dir + '\\shift_x.tif')
        # Y shift:
        self.microtome.move_stage_to_xy((start_x, start_y + shift))
        # Third image:
        self.sem.acquire_frame(self.base_dir + '\\shift_y.tif')
        # Back to initial position:
        self.microtome.move_stage_to_xy((start_x, start_y))

    def calculate_stage_parameters(self):
        """Calculate the rotation angles and scale factors from the user input.
           The user provides the pixel position of any object that can be
           identified in all three acquired test images. From this, the program
           calculates the difference the object was shifted in pixels, and the
           angle with respect to the x or y axis.
        """
        # Pixel positions:
        x1x = self.spinBox_x1x.value()
        x1y = self.spinBox_x1y.value()
        x2x = self.spinBox_x2x.value()
        x2y = self.spinBox_x2y.value()
        y1x = x1x
        y1y = x1y
        y2x = self.spinBox_y2x.value()
        y2y = self.spinBox_y2y.value()
        shift = self.spinBox_shift.value()
        pixel_size = self.spinBox_pixelsize.value()
        # Distances in pixels
        delta_xx = x1x - x2x
        delta_xy = x2y - x1y
        delta_yx = y1x - y2x
        delta_yy = y2y - y1y
        # Rotation angles:
        rot_x = atan(delta_xy/delta_xx)
        rot_y = atan(delta_yx/delta_yy)
        # Scale factors:
        scale_x = shift / (sqrt(delta_xx**2 + delta_xy**2) * pixel_size / 1000)
        scale_y = shift / (sqrt(delta_yx**2 + delta_yy**2) * pixel_size / 1000)

        user_choice = QMessageBox.information(
            self, 'Calculated parameters',
            'Results:\nRotation X: ' + '{0:.5f}'.format(rot_x)
            + ';\nRotation Y: ' + '{0:.5f}'.format(rot_y)
            + '\nScale factor X: ' + '{0:.5f}'.format(scale_x)
            + ';\nScale factor Y: ' + '{0:.5f}'.format(scale_y)
            + '\n\nDo you want to use these values?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_choice == QMessageBox.Ok:
            self.doubleSpinBox_stageScaleFactorX.setValue(scale_x)
            self.doubleSpinBox_stageScaleFactorY.setValue(scale_y)
            self.doubleSpinBox_stageRotationX.setValue(rot_x)
            self.doubleSpinBox_stageRotationY.setValue(rot_y)

    def accept(self):
        stage_params = [
            self.doubleSpinBox_stageScaleFactorX.value(),
            self.doubleSpinBox_stageScaleFactorY.value(),
            self.doubleSpinBox_stageRotationX.value(),
            self.doubleSpinBox_stageRotationY.value()]
        self.microtome.set_stage_calibration(self.current_eht, stage_params)
        success = self.microtome.set_motor_speed_calibration(
            self.doubleSpinBox_motorSpeedX.value(),
            self.doubleSpinBox_motorSpeedY.value())
        if not success:
            QMessageBox.warning(
                self, 'Error updating motor speeds',
                'Motor calibration could not be updated in DM script.',
                QMessageBox.Ok)
        super(CalibrationDlg, self).accept()

#------------------------------------------------------------------------------

class OVSettingsDlg(QDialog):
    """Let the user change all settings for each overview image."""

    def __init__(self, ovm, sem, current_ov):
        super(OVSettingsDlg, self).__init__()
        self.ovm = ovm
        self.sem = sem
        self.current_ov = current_ov
        self.settings_changed = False
        loadUi('..\\gui\\overview_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Set up OV selector:
        self.comboBox_OVSelector.addItems(self.ovm.get_ov_str_list())
        self.comboBox_OVSelector.setCurrentIndex(self.current_ov)
        self.comboBox_OVSelector.currentIndexChanged.connect(self.change_ov)
        # Set up other comboboxes:
        store_res_list = [
            '%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_frameSize.addItems(store_res_list)
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        # Add and delete button:
        self.pushButton_save.clicked.connect(self.save_current_settings)
        self.pushButton_addOV.clicked.connect(self.add_ov)
        self.pushButton_deleteOV.clicked.connect(self.delete_ov)
        self.update_buttons()
        self.show_current_settings()
        self.show_frame_size()

    def show_current_settings(self):
        self.comboBox_frameSize.setCurrentIndex(
            self.ovm.get_ov_size_selector(self.current_ov))
        self.spinBox_magnification.setValue(
            self.ovm.get_ov_magnification(self.current_ov))
        self.comboBox_dwellTime.setCurrentIndex(
            self.ovm.get_ov_dwell_time_selector(self.current_ov))
        self.spinBox_acqInterval.setValue(
            self.ovm.get_ov_acq_interval(self.current_ov))
        self.spinBox_acqIntervalOffset.setValue(
            self.ovm.get_ov_acq_interval_offset(self.current_ov))

    def show_frame_size(self):
        """Calculate and show frame size depending on user selection."""
        frame_size_selector = self.ovm.get_ov_size_selector(self.current_ov)
        pixel_size = self.ovm.get_ov_pixel_size(self.current_ov)
        width = self.sem.STORE_RES[frame_size_selector][0] * pixel_size / 1000
        height = self.sem.STORE_RES[frame_size_selector][1] * pixel_size / 1000
        self.label_frameSize.setText('{0:.1f} × '.format(width)
                                    + '{0:.1f}'.format(height))

    def change_ov(self):
        self.current_ov = self.comboBox_OVSelector.currentIndex()
        self.update_buttons()
        self.show_current_settings()

    def update_buttons(self):
        """Update labels on buttons and disable/enable delete button
           depending on which OV is selected. OV 0 cannot be deleted.
           Only the last OV can be deleted. Reason: preserve identities of
           overviews during stack acq.
        """
        if self.current_ov == 0:
            self.pushButton_deleteOV.setEnabled(False)
        else:
            self.pushButton_deleteOV.setEnabled(
                self.current_ov == self.ovm.get_number_ov() - 1)
        # Show current OV number on delete and save buttons
        self.pushButton_save.setText(
            'Save settings for OV %d' % self.current_ov)
        self.pushButton_deleteOV.setText('Delete OV %d' % self.current_ov)

    def save_current_settings(self):
        self.ovm.set_ov_size_selector(self.current_ov,
            self.comboBox_frameSize.currentIndex())
        self.ovm.set_ov_magnification(self.current_ov,
            self.spinBox_magnification.value())
        self.ovm.set_ov_dwell_time_selector(self.current_ov,
            self.comboBox_dwellTime.currentIndex())
        self.ovm.set_ov_acq_interval(self.current_ov,
            self.spinBox_acqInterval.value())
        self.ovm.set_ov_acq_interval_offset(self.current_ov,
            self.spinBox_acqIntervalOffset.value())
        # Delete current preview image:
        self.ovm.update_ov_file_list(self.current_ov, '')
        self.settings_changed = True

    def add_ov(self):
        self.ovm.add_new_ov()
        self.settings_changed = True
        self.current_ov = self.ovm.get_number_ov() - 1
        # Update OV selector:
        self.comboBox_OVSelector.blockSignals(True)
        self.comboBox_OVSelector.clear()
        self.comboBox_OVSelector.addItems(self.ovm.get_ov_str_list())
        self.comboBox_OVSelector.setCurrentIndex(self.current_ov)
        self.comboBox_OVSelector.blockSignals(False)
        self.update_buttons()
        self.show_current_settings()
        self.show_frame_size()

    def delete_ov(self):
        self.ovm.delete_ov()
        self.settings_changed = True
        self.current_ov = self.ovm.get_number_ov() - 1
        # Update OV selector:
        self.comboBox_OVSelector.blockSignals(True)
        self.comboBox_OVSelector.clear()
        self.comboBox_OVSelector.addItems(self.ovm.get_ov_str_list())
        self.comboBox_OVSelector.setCurrentIndex(self.current_ov)
        self.comboBox_OVSelector.blockSignals(False)
        self.update_buttons()
        self.show_current_settings()
        self.show_frame_size()

#------------------------------------------------------------------------------

class ImportImageDlg(QDialog):
    """Import an image into the viewport."""

    def __init__(self, ovm, cs, target_dir):
        self.ovm = ovm
        self.cs = cs
        self.target_dir = target_dir
        super(ImportImageDlg, self).__init__()
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
            except:
                QMessageBox.warning(
                    self, 'Error',
                    'Could not load image file.',
                     QMessageBox.Ok)
                selection_success = False

            if selection_success:
                new_img_number = self.ovm.get_number_imported()
                self.ovm.add_imported_img()
                self.cs.set_imported_img_centre_s(
                    new_img_number,
                    [self.doubleSpinBox_posX.value(),
                     self.doubleSpinBox_posY.value()])
                self.ovm.set_imported_img_rotation(
                    new_img_number, self.spinBox_rotation.value())
                self.ovm.set_imported_img_file(
                    new_img_number, target_path)
                self.ovm.set_imported_img_name(new_img_number,
                                               self.lineEdit_name.text())
                width, height = imported_img.size
                self.ovm.set_imported_img_size_px_py(
                    new_img_number, width, height)
                self.ovm.set_imported_img_pixel_size(
                    new_img_number, self.doubleSpinBox_pixelSize.value())
                self.ovm.set_imported_img_transparency(
                    new_img_number, self.spinBox_transparency.value())
        else:
            QMessageBox.warning(self, 'Error',
                                'Specified file not found.',
                                QMessageBox.Ok)
            selection_success = False

        if selection_success:
            super(ImportImageDlg, self).accept()

#------------------------------------------------------------------------------

class AdjustImageDlg(QDialog):
    """Adjust an imported image (size, rotation, transparency)"""

    def __init__(self, ovm, cs, selected_img,
                 main_window_queue, main_window_trigger):
        self.ovm = ovm
        self.cs = cs
        self.main_window_queue = main_window_queue
        self.main_window_trigger = main_window_trigger
        self.selected_img = selected_img
        super(AdjustImageDlg, self).__init__()
        loadUi('..\\gui\\adjust_imported_image_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_selectedImage.setText(
            self.ovm.get_imported_img_name(self.selected_img))
        pos_x, pos_y = self.cs.get_imported_img_centre_s(self.selected_img)
        self.doubleSpinBox_posX.setValue(pos_x)
        self.doubleSpinBox_posY.setValue(pos_y)
        self.doubleSpinBox_pixelSize.setValue(
            self.ovm.get_imported_img_pixel_size(self.selected_img))
        self.spinBox_rotation.setValue(
            self.ovm.get_imported_img_rotation(self.selected_img))
        self.spinBox_transparency.setValue(
            self.ovm.get_imported_img_transparency(self.selected_img))
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
        self.cs.set_imported_img_centre_s(
            self.selected_img,
            [self.doubleSpinBox_posX.value(),
             self.doubleSpinBox_posY.value()])
        self.ovm.set_imported_img_pixel_size(
            self.selected_img, self.doubleSpinBox_pixelSize.value())
        self.ovm.set_imported_img_rotation(
            self.selected_img, self.spinBox_rotation.value())
        self.ovm.set_imported_img_transparency(
            self.selected_img, self.spinBox_transparency.value())
        # Emit signals to reload and redraw:
        self.main_window_queue.put('RELOAD IMPORTED' + str(self.selected_img))
        self.main_window_trigger.s.emit()

#------------------------------------------------------------------------------

class DeleteImageDlg(QDialog):
    """Delete an imported image from the viewport."""

    def __init__(self, ovm):
        self.ovm = ovm
        super(DeleteImageDlg, self).__init__()
        loadUi('..\\gui\\delete_image_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Populate the list widget with existing imported images:
        img_list = []
        for i in range(self.ovm.get_number_imported()):
            img_list.append(str(i) + ' - ' + self.ovm.get_imported_img_name(i))
        self.listWidget_imagelist.addItems(img_list)

    def accept(self):
        selected_img = self.listWidget_imagelist.currentRow()
        if selected_img is not None:
            self.ovm.delete_imported_img(selected_img)
        super(DeleteImageDlg, self).accept()

#------------------------------------------------------------------------------

class GridSettingsDlg(QDialog):
    """Let the user change all settings for each grid."""

    def __init__(self, grid_manager, sem, current_grid):
        super(GridSettingsDlg, self).__init__()
        self.gm = grid_manager
        self.sem = sem
        self.current_grid = current_grid
        self.settings_changed = False
        loadUi('..\\gui\\grid_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Set up grid selector:
        self.comboBox_gridSelector.addItems(self.gm.get_grid_str_list())
        self.comboBox_gridSelector.setCurrentIndex(self.current_grid)
        self.comboBox_gridSelector.currentIndexChanged.connect(
            self.change_grid)
        # Set up colour selector:
        for i in range(len(utils.COLOUR_SELECTOR)):
            rgb = utils.COLOUR_SELECTOR[i]
            colour_icon = QPixmap(20, 10)
            colour_icon.fill(QColor(rgb[0], rgb[1], rgb[2]))
            self.comboBox_colourSelector.addItem(QIcon(colour_icon), '')
        store_res_list = [
            '%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_tileSize.addItems(store_res_list)
        self.comboBox_tileSize.currentIndexChanged.connect(
            self.show_tile_size_and_dose)
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        self.comboBox_dwellTime.currentIndexChanged.connect(
            self.show_tile_size_and_dose)
        self.doubleSpinBox_pixelSize.valueChanged.connect(
            self.show_tile_size_and_dose)
        # Adaptive focus tool button:
        self.toolButton_adaptiveFocus.clicked.connect(
            self.open_adaptive_focus_dlg)
        # Save, add and delete button:
        self.pushButton_save.clicked.connect(self.save_current_settings)
        self.pushButton_addGrid.clicked.connect(self.add_grid)
        self.pushButton_deleteGrid.clicked.connect(self.delete_grid)
        self.update_buttons()
        self.show_current_settings()
        self.show_tile_size_and_dose()

    def show_current_settings(self):
        self.comboBox_colourSelector.setCurrentIndex(
            self.gm.get_display_colour_index(self.current_grid))
        # Adaptive focus:
        self.checkBox_adaptiveFocus.setChecked(
            self.gm.is_adaptive_focus_active(self.current_grid))

        self.spinBox_rows.setValue(self.gm.get_number_rows(self.current_grid))
        self.spinBox_cols.setValue(self.gm.get_number_cols(self.current_grid))
        self.spinBox_overlap.setValue(self.gm.get_overlap(self.current_grid))
        self.spinBox_shift.setValue(self.gm.get_row_shift(self.current_grid))

        self.doubleSpinBox_pixelSize.setValue(
            self.gm.get_pixel_size(self.current_grid))
        self.comboBox_tileSize.setCurrentIndex(
            self.gm.get_tile_size_selector(self.current_grid))
        self.comboBox_dwellTime.setCurrentIndex(
            self.gm.get_dwell_time_selector(self.current_grid))
        self.spinBox_acqInterval.setValue(
            self.gm.get_acq_interval(self.current_grid))
        self.spinBox_acqIntervalOffset.setValue(
            self.gm.get_acq_interval_offset(self.current_grid))

    def show_tile_size_and_dose(self):
        """Calculate and display the tile size and the dose for the current
           settings. Updated in real-time as user changes dwell time, frame
           resolution and pixel size.
        """
        tile_size_selector = self.comboBox_tileSize.currentIndex()
        pixel_size = self.doubleSpinBox_pixelSize.value()
        width = self.sem.STORE_RES[tile_size_selector][0] * pixel_size / 1000
        height = self.sem.STORE_RES[tile_size_selector][1] * pixel_size / 1000
        self.label_tileSize.setText('{0:.1f} × '.format(width)
                                    + '{0:.1f}'.format(height))
        current = self.sem.get_beam_current()
        dwell_time = float(self.comboBox_dwellTime.currentText())
        pixel_size = self.doubleSpinBox_pixelSize.value()
        # Calculate the electron dose in electrons per square nanometre.
        dose = (current * 10**(-12) / (1.602 * 10**(-19))
                * dwell_time * 10**(-6) / (pixel_size**2))
        self.label_dose.setText('{0:.1f}'.format(dose))

    def change_grid(self):
        self.current_grid = self.comboBox_gridSelector.currentIndex()
        self.update_buttons()
        self.show_current_settings()
        self.show_tile_size_and_dose()

    def update_buttons(self):
        """Update labels on buttons and disable/enable delete button
           depending on which grid is selected. Grid 0 cannot be deleted.
           Only the last grid can be deleted. Reason: preserve identities of
           grids and tiles within grids.
        """
        if self.current_grid == 0:
            self.pushButton_deleteGrid.setEnabled(False)
        else:
            self.pushButton_deleteGrid.setEnabled(
                self.current_grid == self.gm.get_number_grids() - 1)
        self.pushButton_save.setText(
            'Save settings for grid %d' % self.current_grid)
        self.pushButton_deleteGrid.setText('Delete grid %d' % self.current_grid)

    def add_grid(self):
        self.gm.add_new_grid()
        self.settings_changed = True
        self.current_grid = self.gm.get_number_grids() - 1
        # Update grid selector:
        self.comboBox_gridSelector.blockSignals(True)
        self.comboBox_gridSelector.clear()
        self.comboBox_gridSelector.addItems(self.gm.get_grid_str_list())
        self.comboBox_gridSelector.setCurrentIndex(self.current_grid)
        self.comboBox_gridSelector.blockSignals(False)
        self.update_buttons()
        self.show_current_settings()
        self.show_tile_size_and_dose()

    def delete_grid(self):
        user_reply = QMessageBox.question(
                        self, 'Delete grid',
                        'This will delete grid %d.\n\n'
                        'Do you wish to proceed?' % self.current_grid,
                        QMessageBox.Ok | QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            self.gm.delete_grid()
            self.settings_changed = True
            self.current_grid = self.gm.get_number_grids() - 1
            # Update grid selector:
            self.comboBox_gridSelector.blockSignals(True)
            self.comboBox_gridSelector.clear()
            self.comboBox_gridSelector.addItems(self.gm.get_grid_str_list())
            self.comboBox_gridSelector.setCurrentIndex(self.current_grid)
            self.comboBox_gridSelector.blockSignals(False)
            self.update_buttons()
            self.show_current_settings()
            self.show_tile_size_and_dose()

    def save_current_settings(self):
        error_msg = ''
        self.settings_changed = True
        self.gm.set_grid_size(self.current_grid,
                              (self.spinBox_rows.value(),
                              self.spinBox_cols.value()))
        self.gm.set_tile_size_selector(self.current_grid,
                                       self.comboBox_tileSize.currentIndex())
        tile_width_p = self.gm.get_tile_width_p(self.current_grid)
        input_overlap = self.spinBox_overlap.value()
        input_shift = self.spinBox_shift.value()
        if -0.3 * tile_width_p <= input_overlap < 0.3 * tile_width_p:
            self.gm.set_overlap(self.current_grid, input_overlap)
        else:
            error_msg = ('Overlap outside of allowed '
                         'range (-30% .. 30% frame width).')
        if 0 <= input_shift <= tile_width_p:
            self.gm.set_row_shift(self.current_grid, input_shift)
        else:
            error_msg = ('Row shift outside of allowed '
                         'range (0 .. frame width).')
        self.gm.set_display_colour(
            self.current_grid, self.comboBox_colourSelector.currentIndex())
        self.gm.set_adaptive_focus_enabled(self.current_grid,
            self.checkBox_adaptiveFocus.isChecked())
        # Acquisition parameters:
        self.gm.set_pixel_size(self.current_grid,
            self.doubleSpinBox_pixelSize.value())
        self.gm.set_dwell_time_selector(self.current_grid,
            self.comboBox_dwellTime.currentIndex())
        self.gm.set_acq_interval(
            self.current_grid, self.spinBox_acqInterval.value())
        self.gm.set_acq_interval_offset(
            self.current_grid, self.spinBox_acqIntervalOffset.value())
        # Recalculate grid:
        self.gm.calculate_grid_map(self.current_grid)

        if error_msg:
            QMessageBox.warning(self, 'Error', error_msg, QMessageBox.Ok)

    def open_adaptive_focus_dlg(self):
        sub_dialog = AdaptiveFocusSettingsDlg(self.gm, self.current_grid)
        sub_dialog.exec_()

#------------------------------------------------------------------------------

class AdaptiveFocusSettingsDlg(QDialog):
    """Select the tiles to calculate the gradient for the adaptive focus."""

    def __init__(self, gm, current_grid):
        super(AdaptiveFocusSettingsDlg, self).__init__()
        self.gm = gm
        self.current_grid = current_grid
        loadUi('..\\gui\\adaptive_focus_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_currentGrid.setText('Grid ' + str(current_grid))
        self.grid_illustration.setPixmap(QPixmap('..\\img\\grid.png'))
        self.af_tiles = self.gm.get_adaptive_focus_tiles(self.current_grid)
        # Backup variable for currently selected adaptive focus tiles:
        self.prev_af_tiles = self.af_tiles.copy()
        # Set up tile selectors for adaptive focus tiles:
        number_of_tiles = self.gm.get_number_tiles(self.current_grid)
        tile_list_str = ['-']
        for tile in range(0, number_of_tiles):
            tile_list_str.append(str(tile))
        for i in range(3):
            if self.af_tiles[i] >= number_of_tiles:
                self.af_tiles[i] = -1

        self.comboBox_tileUpperLeft.blockSignals(True)
        self.comboBox_tileUpperLeft.addItems(tile_list_str)
        self.comboBox_tileUpperLeft.setCurrentIndex(self.af_tiles[0] + 1)
        self.comboBox_tileUpperLeft.currentIndexChanged.connect(
            self.update_settings)
        self.comboBox_tileUpperLeft.blockSignals(False)

        self.comboBox_tileUpperRight.blockSignals(True)
        self.comboBox_tileUpperRight.addItems(tile_list_str)
        self.comboBox_tileUpperRight.setCurrentIndex(self.af_tiles[1] + 1)
        self.comboBox_tileUpperRight.currentIndexChanged.connect(
            self.update_settings)
        self.comboBox_tileUpperRight.blockSignals(False)

        self.comboBox_tileLowerLeft.blockSignals(True)
        self.comboBox_tileLowerLeft.addItems(tile_list_str)
        self.comboBox_tileLowerLeft.setCurrentIndex(self.af_tiles[2] + 1)
        self.comboBox_tileLowerLeft.currentIndexChanged.connect(
            self.update_settings)
        self.comboBox_tileLowerLeft.blockSignals(False)

        self.update_settings()

    def update_settings(self):
        """Get selected working distances and calculate origin WD and
           gradient if possible.
        """
        self.af_tiles[0] = self.comboBox_tileUpperLeft.currentIndex() - 1
        self.af_tiles[1] = self.comboBox_tileUpperRight.currentIndex() - 1
        self.af_tiles[2] = self.comboBox_tileLowerLeft.currentIndex() - 1

        if self.af_tiles[0] >= 0:
            self.label_t1.setText('Tile ' + str(self.af_tiles[0]) + ':')
            wd = self.gm.get_tile_wd(self.current_grid, self.af_tiles[0])
            if wd == 0:
                wd = self.sem.get_wd()
            self.doubleSpinBox_t1.setValue(wd * 1000)
        else:
            self.label_t1.setText('Tile (-) :')
            self.doubleSpinBox_t1.setValue(0)
        if self.af_tiles[1] >= 0:
            self.label_t2.setText('Tile ' + str(self.af_tiles[1]) + ':')
            wd = self.gm.get_tile_wd(self.current_grid, self.af_tiles[1])
            if wd == 0:
                wd = self.sem.get_wd()
            self.doubleSpinBox_t2.setValue(wd * 1000)
        else:
            self.label_t2.setText('Tile (-) :')
            self.doubleSpinBox_t2.setValue(0)
        if self.af_tiles[2] >= 0:
            self.label_t3.setText('Tile ' + str(self.af_tiles[2]) + ':')
            wd = self.gm.get_tile_wd(self.current_grid, self.af_tiles[2])
            if wd == 0:
                wd = self.sem.get_wd()
            self.doubleSpinBox_t3.setValue(wd * 1000)
        else:
            self.label_t3.setText('Tile (-) :')
            self.doubleSpinBox_t3.setValue(0)

        self.gm.set_adaptive_focus_tiles(self.current_grid, self.af_tiles)
        # Try to calculate focus map:
        self.af_success = self.gm.calculate_focus_map(self.current_grid)
        if self.af_success:
            grad = self.gm.get_adaptive_focus_gradient(self.current_grid)
            wd = self.gm.get_tile_wd(self.current_grid, 0)
            current_status_str = (
                'WD: ' + '{0:.6f}'.format(wd * 1000)
                + ' mm;\n' + chr(8710)
                + 'x: ' + '{0:.6f}'.format(grad[0] * 1000)
                + '; ' + chr(8710) + 'y: ' + '{0:.6f}'.format(grad[1] * 1000))
        else:
            current_status_str = 'Insufficient or incorrect tile selection'

        self.textEdit_originGradients.setText(current_status_str)

    def accept(self):
        if self.af_success:
            super(AdaptiveFocusSettingsDlg, self).accept()
        else:
            QMessageBox.warning(
                self, 'Error',
                'Insufficient or incorrect tile selection. Cannot calculate '
                'origin working distance and focus gradient.',
                 QMessageBox.Ok)

    def reject(self):
        # Restore previous selection:
        self.gm.set_adaptive_focus_tiles(self.current_grid, self.prev_af_tiles)
        # Recalculate with previous setting:
        self.gm.calculate_focus_map(self.current_grid)
        super(AdaptiveFocusSettingsDlg, self).reject()

#------------------------------------------------------------------------------

class AcqSettingsDlg(QDialog):
    """Let user adjust acquisition settings."""

    def __init__(self, config, stack):
        super(AcqSettingsDlg, self).__init__()
        self.cfg = config
        self.stack = stack
        loadUi('..\\gui\\acq_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_selectDir.clicked.connect(self.select_directory)
        self.pushButton_selectDir.setIcon(QIcon('..\\img\\selectdir.png'))
        self.pushButton_selectDir.setIconSize(QSize(16, 16))
        # Display current settings:
        self.lineEdit_baseDir.setText(self.cfg['acq']['base_dir'])
        self.spinBox_sliceThickness.setValue(self.stack.get_slice_thickness())
        self.spinBox_numberSlices.setValue(self.stack.get_number_slices())
        self.spinBox_sliceCounter.setValue(self.stack.get_slice_counter())
        self.doubleSpinBox_zDiff.setValue(self.stack.get_total_z_diff())
        self.checkBox_sendMetaData.setChecked(
            self.cfg['sys']['send_metadata'] == 'True')
        self.update_server_lineedit()
        self.checkBox_sendMetaData.stateChanged.connect(
            self.update_server_lineedit)
        self.checkBox_EHTOff.setChecked(
            self.cfg['acq']['eht_off_after_stack'] == 'True')
        self.lineEdit_metaDataServer.setText(
            self.cfg['sys']['metadata_server_url'])
        self.lineEdit_adminEmail.setText(
            self.cfg['sys']['metadata_server_admin'])
        self.lineEdit_projectName.setText(
            self.cfg['sys']['metadata_project_name'])

    def select_directory(self):
        """Let user select the base directory for the stack acquisition.
           Note that the final subfolder name in the directory string is used as
           the name of the stack in SBEMimage.
        """
        if len(self.cfg['acq']['base_dir']) > 2:
            start_path = self.cfg['acq']['base_dir'][:3]
        else:
            start_path = 'C:\\'
        directory = str(QFileDialog.getExistingDirectory(
                            self, 'Select Directory',
                            start_path,
                            QFileDialog.ShowDirsOnly))
        if len(directory) > 0:
            # Replace forward slashes with backward slashes:
            directory = directory.replace('/', '\\')
            self.lineEdit_baseDir.setText(directory)
            self.cfg['acq']['base_dir'] = directory

    def update_server_lineedit(self):
        status = self.checkBox_sendMetaData.isChecked()
        self.lineEdit_projectName.setEnabled(status)

    def accept(self):
        success = True
        self.cfg['acq']['base_dir'] = self.lineEdit_baseDir.text()
        # Remove spaces if necessary:
        if ' ' in self.cfg['acq']['base_dir']:
            self.cfg['acq']['base_dir'] = (
                self.cfg['acq']['base_dir'].replace(' ', '_'))
            self.lineEdit_baseDir.setText(self.cfg['acq']['base_dir'])
        if 5 <= self.spinBox_sliceThickness.value() <= 200:
            self.stack.set_slice_thickness(self.spinBox_sliceThickness.value())
        number_slices = self.spinBox_numberSlices.value()
        self.stack.set_number_slices(number_slices)
        if (self.spinBox_sliceCounter.value() <= number_slices
            or number_slices == 0):
            self.stack.set_slice_counter(self.spinBox_sliceCounter.value())
        self.stack.set_total_z_diff(self.doubleSpinBox_zDiff.value())
        self.cfg['acq']['eht_off_after_stack'] = str(
            self.checkBox_EHTOff.isChecked())
        self.cfg['sys']['send_metadata'] = str(
            self.checkBox_sendMetaData.isChecked())
        if self.checkBox_sendMetaData.isChecked():
            server_url = self.lineEdit_metaDataServer.text()
            if validators.url(server_url):
                self.cfg['sys']['metadata_server_url'] = server_url
            else:
                QMessageBox.warning(
                    self, 'Error',
                    'Metadata server URL is invalid. Change the URL in the '
                    'system configuration file.',
                    QMessageBox.Ok)
                success = False
            self.cfg['sys']['metadata_project_name'] = (
                self.lineEdit_projectName.text())
        if ((number_slices > 0)
            and (self.spinBox_sliceCounter.value() > number_slices)):
            QMessageBox.warning(
                self, 'Error',
                'Slice counter must be smaller than or equal to '
                'target number of slices.', QMessageBox.Ok)
            success = False
        if success:
            super(AcqSettingsDlg, self).accept()

#------------------------------------------------------------------------------

class PreStackDlg(QDialog):
    """Let user check the acquisition settings before starting a stack.
       Also show settings that can only be changed in DM and let user adjust
       them for logging purposes.
    """

    def __init__(self, config, ovm, gm, paused):
        super(PreStackDlg, self).__init__()
        self.cfg = config
        self.ovm = ovm
        self.gm = gm
        loadUi('..\\gui\\pre_stack_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Different labels if stack is paused ('Continue' instead of 'Start'):
        if paused:
            self.pushButton_startAcq.setText('Continue acquisition')
            self.setWindowTitle('Continue acquisition')
        self.pushButton_startAcq.clicked.connect(self.accept)
        boldFont = QFont()
        boldFont.setBold(True)
        # Show the most relevant current settings for the acquisition:
        base_dir = self.cfg['acq']['base_dir']
        self.label_stackName.setText(base_dir[base_dir.rfind('\\') + 1:])
        self.label_beamSettings.setText(
            self.cfg['sem']['eht'] + ' keV, '
            + self.cfg['sem']['beam_current'] + ' pA')
        self.label_gridSetup.setText(
            self.cfg['overviews']['number_ov'] + ' overview(s), '
            + self.cfg['grids']['number_grids'] + ' grid(s);')
        self.label_totalActiveTiles.setText(
            str(self.gm.get_total_number_active_tiles()) + ' active tile(s)')
        if self.cfg['acq']['use_autofocus'] == 'True':
            if int(self.cfg['autofocus']['method']) == 0:
                self.label_autofocusActive.setFont(boldFont)
                self.label_autofocusActive.setText('Active (SmartSEM)')
            elif int(self.cfg['autofocus']['method']) == 1:
                self.label_autofocusActive.setFont(boldFont)
                self.label_autofocusActive.setText('Active (heuristic)')
        else:
            self.label_autofocusActive.setText('Inactive')
        if self.gm.is_adaptive_focus_active():
            self.label_adaptiveActive.setFont(boldFont)
            self.label_adaptiveActive.setText('Active')
        else:
            self.label_adaptiveActive.setText('Inactive')
        if (self.gm.is_intervallic_acq_active()
            or self.ovm.is_intervallic_acq_active()):
            self.label_intervallicActive.setFont(boldFont)
            self.label_intervallicActive.setText('Active')
        else:
            self.label_intervallicActive.setText('Inactive')
        if self.cfg['acq']['interrupted'] == 'True':
            position = json.loads(self.cfg['acq']['interrupted_at'])
            self.label_interruption.setFont(boldFont)
            self.label_interruption.setText(
                'Yes, in grid ' + str(position[0]) + ' at tile '
                + str(position[1]))
        else:
            self.label_interruption.setText('None')
        self.doubleSpinBox_cutSpeed.setValue(
            float(self.cfg['microtome']['knife_cut_speed']))
        self.doubleSpinBox_retractSpeed.setValue(
            float(self.cfg['microtome']['knife_retract_speed']))
        self.doubleSpinBox_brightness.setValue(
            float(self.cfg['sem']['bsd_brightness']))
        self.doubleSpinBox_contrast.setValue(
            float(self.cfg['sem']['bsd_contrast']))
        self.spinBox_bias.setValue(
            int(self.cfg['sem']['bsd_bias']))
        self.checkBox_oscillation.setChecked(
            self.cfg['microtome']['knife_oscillation'] == 'True')

    def accept(self):
        self.cfg['microtome']['knife_cut_speed'] = str(
            self.doubleSpinBox_cutSpeed.value())
        self.cfg['microtome']['knife_retract_speed'] = str(
            self.doubleSpinBox_retractSpeed.value())
        self.cfg['sem']['bsd_contrast'] = str(
            self.doubleSpinBox_contrast.value())
        self.cfg['sem']['bsd_brightness'] = str(
            self.doubleSpinBox_brightness.value())
        self.cfg['sem']['bsd_bias'] = str(
            self.spinBox_bias.value())
        self.cfg['microtome']['knife_oscillation'] = str(
            self.checkBox_oscillation.isChecked())
        super(PreStackDlg, self).accept()

#------------------------------------------------------------------------------

class PauseDlg(QDialog):
    """Let the user pause a running acquisition. Two options: (1) Pause as soon
       as possible (after the current image is acquired.) (2) Pause after the
       current slice is imaged and cut.
    """

    def __init__(self):
        super(PauseDlg, self).__init__()
        loadUi('..\\gui\\pause_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pause_type = 0
        self.pushButton_pauseNow.clicked.connect(self.pause_now)
        self.pushButton_pauseAfterSlice.clicked.connect(self.pause_later)

    def pause_now(self):
        self.pause_type = 1
        self.accept()

    def pause_later(self):
        self.pause_type = 2
        self.accept()

    def get_user_choice(self):
        return self.pause_type

    def accept(self):
        super(PauseDlg, self).accept()

#------------------------------------------------------------------------------

class ExportDlg(QDialog):
    """Export image list in TrakEM2 format."""

    def __init__(self, config):
        super(ExportDlg, self).__init__()
        self.cfg = config
        loadUi('..\\gui\\export_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.pushButton_export.clicked.connect(self.export_list)
        self.spinBox_untilSlice.setValue(int(self.cfg['acq']['slice_counter']))
        self.show()

    def export_list(self):
        self.pushButton_export.setText('Busy')
        self.pushButton_export.setEnabled(False)
        QApplication.processEvents()
        start_slice = self.spinBox_fromSlice.value()
        end_slice = self.spinBox_untilSlice.value()
        # Read all imagelist files into memory:
        imagelist_str = []
        imagelist_data = []
        file_list = glob.glob(self.cfg['acq']['base_dir']
                              + '\\meta\\logs\\'  'imagelist*.txt')
        file_list.sort()
        for file in file_list:
            with open(file) as f:
                imagelist_str.extend(f.readlines())
        if len(imagelist_str) > 0:
            # split strings, store entries in variables, find minimum x and y:
            min_x = 1000000
            min_y = 1000000
            for line in imagelist_str:
                elements = line.split(';')
                z = int(elements[3])
                if start_slice <= z <= end_slice:
                    x = int(elements[1])
                    if x < min_x:
                        min_x = x
                    y = int(elements[2])
                    if y < min_y:
                        min_y = y
                    imagelist_data.append([elements[0], x, y, z])
            # Subtract minimum values:
            number_entries = len(imagelist_data)
            for i in range(0, number_entries):
                imagelist_data[i][1] -= min_x
                imagelist_data[i][2] -= min_y
            # Write to output file:
            try:
                output_file = (self.cfg['acq']['base_dir'] +
                               '\\trakem2_imagelist_slice' + str(start_slice) +
                               'to' + str(end_slice) + '.txt')
                with open(output_file, 'w') as f:
                    for item in imagelist_data:
                        f.write(item[0] + '\t'
                                + str(item[1]) + '\t'
                                + str(item[2]) + '\t'
                                + str(item[3]) + '\n')
            except:
                QMessageBox.warning(self, 'Error',
                        'An error ocurred while writing the output file.',
                        QMessageBox.Ok)
            else:
                QMessageBox.information(
                        self, 'Export completed',
                        'A total of ' + str(number_entries) + ' entries were '
                        'processed.\n\nThe output file\n'
                        'trakem2_imagelist_slice' + str(start_slice) +
                        'to' + str(end_slice) + '.txt\n'
                        'was written to the current base directory\n' +
                        self.cfg['acq']['base_dir'] + '.',
                        QMessageBox.Ok)
        else:
            QMessageBox.warning(
                self, 'Error',
                'No image metadata found.',
                QMessageBox.Ok)
        self.pushButton_export.setText('Export')
        self.pushButton_export.setEnabled(True)
        QApplication.processEvents()

#------------------------------------------------------------------------------

class EmailMonitoringSettingsDlg(QDialog):
    """Adjust settings for the e-mail monitoring feature."""

    def __init__(self, config, stack):
        super(EmailMonitoringSettingsDlg, self).__init__()
        self.cfg = config
        self.stack = stack
        loadUi('..\\gui\\email_monitoring_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_notificationEmail.setText(
            self.cfg['monitoring']['user_email'])
        self.lineEdit_secondaryNotificationEmail.setText(
            self.cfg['monitoring']['cc_user_email'])
        self.spinBox_reportInterval.setValue(
            int(self.cfg['monitoring']['report_interval']))
        self.lineEdit_selectedOV.setText(
            self.cfg['monitoring']['watch_ov'][1:-1])
        self.lineEdit_selectedTiles.setText(
            self.cfg['monitoring']['watch_tiles'][1:-1].replace('"', ''))
        self.checkBox_sendLogFile.setChecked(
            self.cfg['monitoring']['send_logfile'] == 'True')
        self.checkBox_sendDebrisErrorLogFiles.setChecked(
            self.cfg['monitoring']['send_additional_logs'] == 'True')
        self.checkBox_sendViewport.setChecked(
            self.cfg['monitoring']['send_viewport'] == 'True')
        self.checkBox_sendOverviews.setChecked(
            self.cfg['monitoring']['send_ov'] == 'True')
        self.checkBox_sendTiles.setChecked(
            self.cfg['monitoring']['send_tiles'] == 'True')
        self.checkBox_sendOVReslices.setChecked(
            self.cfg['monitoring']['send_ov_reslices'] == 'True')
        self.checkBox_sendTileReslices.setChecked(
            self.cfg['monitoring']['send_tile_reslices'] == 'True')
        self.checkBox_allowEmailControl.setChecked(
            self.cfg['monitoring']['remote_commands_enabled'] == 'True')
        self.checkBox_allowEmailControl.stateChanged.connect(
            self.update_remote_option_input)
        self.update_remote_option_input()
        self.spinBox_remoteCheckInterval.setValue(
            int(self.cfg['monitoring']['remote_check_interval']))
        self.lineEdit_account.setText(self.cfg['sys']['email_account'])
        self.lineEdit_password.setEchoMode(QLineEdit.Password)
        self.lineEdit_password.setText(self.stack.get_remote_password())

    def update_remote_option_input(self):
        status = self.checkBox_allowEmailControl.isChecked()
        self.spinBox_remoteCheckInterval.setEnabled(status)
        self.lineEdit_password.setEnabled(status)

    def accept(self):
        error_str = ''
        email1 = self.lineEdit_notificationEmail.text()
        email2 = self.lineEdit_secondaryNotificationEmail.text()
        if validate_email(email1):
            self.cfg['monitoring']['user_email'] = email1
        else:
            error_str = 'Primary e-mail address badly formatted or missing.'
        # Second user e-mail is optional
        if validate_email(email2) or not email2:
            self.cfg['monitoring']['cc_user_email'] = (
                self.lineEdit_secondaryNotificationEmail.text())
        else:
            error_str = 'Secondary e-mail address badly formatted.'
        self.cfg['monitoring']['report_interval'] = str(
            self.spinBox_reportInterval.value())

        success, ov_list = utils.validate_ov_list(
            self.lineEdit_selectedOV.text())
        if success:
            self.cfg['monitoring']['watch_ov'] = str(ov_list)
        else:
            error_str = 'List of selected overviews badly formatted.'

        success, tile_list = utils.validate_tile_list(
            self.lineEdit_selectedTiles.text())
        if success:
            self.cfg['monitoring']['watch_tiles'] = json.dumps(tile_list)
        else:
            error_str = 'List of selected tiles badly formatted.'

        self.cfg['monitoring']['send_logfile'] = str(
            self.checkBox_sendLogFile.isChecked())
        self.cfg['monitoring']['send_additional_logs'] = str(
            self.checkBox_sendDebrisErrorLogFiles.isChecked())
        self.cfg['monitoring']['send_viewport'] = str(
            self.checkBox_sendViewport.isChecked())
        self.cfg['monitoring']['send_ov'] = str(
            self.checkBox_sendOverviews.isChecked())
        self.cfg['monitoring']['send_tiles'] = str(
            self.checkBox_sendTiles.isChecked())
        self.cfg['monitoring']['send_ov_reslices'] = str(
            self.checkBox_sendOVReslices.isChecked())
        self.cfg['monitoring']['send_tile_reslices'] = str(
            self.checkBox_sendTileReslices.isChecked())
        self.cfg['monitoring']['remote_commands_enabled'] = str(
            self.checkBox_allowEmailControl.isChecked())
        self.cfg['monitoring']['remote_check_interval'] = str(
            self.spinBox_remoteCheckInterval.value())
        self.stack.set_remote_password(self.lineEdit_password.text())
        if not error_str:
            super(EmailMonitoringSettingsDlg, self).accept()
        else:
            QMessageBox.warning(self, 'Error', error_str, QMessageBox.Ok)

#------------------------------------------------------------------------------

class DebrisSettingsDlg(QDialog):
    """Adjust the options for debris detection and removal: Detection area,
       detection method, max. number of sweeps, and what to do when max.
       number reached.
    """

    def __init__(self, config, ovm):
        super(DebrisSettingsDlg, self).__init__()
        self.cfg = config
        self.ovm = ovm
        loadUi('..\\gui\\debris_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Detection area:
        if self.cfg['debris']['auto_detection_area'] == 'True':
            self.radioButton_autoSelection.setChecked(True)
        else:
            self.radioButton_fullSelection.setChecked(True)
        # Extra margin around detection area in pixels:
        self.spinBox_debrisMargin.setValue(
            self.ovm.get_ov_auto_debris_detection_area_margin())
        self.spinBox_maxSweeps.setValue(
            int(self.cfg['debris']['max_number_sweeps']))
        self.doubleSpinBox_diffMean.setValue(
            float(self.cfg['debris']['mean_diff_threshold']))
        self.doubleSpinBox_diffSD.setValue(
            float(self.cfg['debris']['stddev_diff_threshold']))
        self.spinBox_diffHistogram.setValue(
            int(self.cfg['debris']['histogram_diff_threshold']))
        self.spinBox_diffPixels.setValue(
            int(self.cfg['debris']['image_diff_threshold']))
        self.checkBox_showDebrisArea.setChecked(
            self.cfg['debris']['show_detection_area'] == 'True')
        self.checkBox_continueAcq.setChecked(
            self.cfg['debris']['continue_after_max_sweeps'] == 'True')
        # Detection methods:
        self.radioButton_methodQuadrant.setChecked(
            self.cfg['debris']['detection_method'] == '0')
        self.radioButton_methodPixel.setChecked(
            self.cfg['debris']['detection_method'] == '1')
        self.radioButton_methodHistogram.setChecked(
            self.cfg['debris']['detection_method'] == '2')
        self.radioButton_methodQuadrant.toggled.connect(
            self.update_option_selection)
        self.radioButton_methodHistogram.toggled.connect(
            self.update_option_selection)
        self.update_option_selection()

    def update_option_selection(self):
        """Let user only change the parameters for the currently selected
           detection method. The other input fields are deactivated.
        """
        if self.radioButton_methodQuadrant.isChecked():
            self.doubleSpinBox_diffMean.setEnabled(True)
            self.doubleSpinBox_diffSD.setEnabled(True)
            self.spinBox_diffPixels.setEnabled(False)
            self.spinBox_diffHistogram.setEnabled(False)
        elif self.radioButton_methodPixel.isChecked():
             self.doubleSpinBox_diffMean.setEnabled(False)
             self.doubleSpinBox_diffSD.setEnabled(False)
             self.spinBox_diffPixels.setEnabled(True)
             self.spinBox_diffHistogram.setEnabled(False)
        elif self.radioButton_methodHistogram.isChecked():
             self.doubleSpinBox_diffMean.setEnabled(False)
             self.doubleSpinBox_diffSD.setEnabled(False)
             self.spinBox_diffPixels.setEnabled(False)
             self.spinBox_diffHistogram.setEnabled(True)

    def accept(self):
        self.ovm.set_ov_auto_debris_detection_area_margin(
            self.spinBox_debrisMargin.value())
        self.cfg['debris']['max_number_sweeps'] = str(
            self.spinBox_maxSweeps.value())
        self.cfg['debris']['mean_diff_threshold'] = str(
            self.doubleSpinBox_diffMean.value())
        self.cfg['debris']['stddev_diff_threshold'] = str(
            self.doubleSpinBox_diffSD.value())
        self.cfg['debris']['histogram_diff_threshold'] = str(
            self.spinBox_diffHistogram.value())
        self.cfg['debris']['image_diff_threshold'] = str(
            self.spinBox_diffPixels.value())
        self.cfg['debris']['auto_detection_area'] = str(
            self.radioButton_autoSelection.isChecked())
        self.cfg['debris']['show_detection_area'] = str(
            self.checkBox_showDebrisArea.isChecked())
        self.cfg['debris']['continue_after_max_sweeps'] = str(
            self.checkBox_continueAcq.isChecked())
        if self.radioButton_methodQuadrant.isChecked():
            self.cfg['debris']['detection_method'] = '0'
        elif self.radioButton_methodPixel.isChecked():
            self.cfg['debris']['detection_method'] = '1'
        elif self.radioButton_methodHistogram.isChecked():
            self.cfg['debris']['detection_method'] = '2'
        super(DebrisSettingsDlg, self).accept()

#------------------------------------------------------------------------------

class AskUserDlg(QDialog):
    """Specify for which events the program should let the user decide how
       to proceed. The "Ask User" functionality is currently only used for
       debris detection. Will be expanded, work in progress...
    """

    def __init__(self):
        super(AskUserDlg, self).__init__()
        loadUi('..\\gui\\ask_user_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()

#------------------------------------------------------------------------------

class MirrorDriveDlg(QDialog):
    """Select a mirror drive from all available drives."""

    def __init__(self, config):
        super(MirrorDriveDlg, self).__init__()
        self.cfg = config
        loadUi('..\\gui\\mirror_drive_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.available_drives = []
        self.label_text.setText('Please wait. Searching for drives...')
        QApplication.processEvents()
        # Search for drives in thread. If it gets stuck because drives are
        # not accessible, user can still cancel dialog.
        t = threading.Thread(target=self.search_drives)
        t.start()

    def search_drives(self):
        # Search for all available drives:
        self.available_drives = [
            '%s:' % d for d in string.ascii_uppercase
            if os.path.exists('%s:' % d)]
        if self.available_drives:
            self.comboBox_allDrives.addItems(self.available_drives)
            current_index = self.comboBox_allDrives.findText(
                self.cfg['sys']['mirror_drive'])
            if current_index == -1:
                current_index = 0
            self.comboBox_allDrives.setCurrentIndex(current_index)
            # Restore label after searching for available drives:
            self.label_text.setText('Select drive for mirroring acquired data:')

    def accept(self):
        if self.available_drives:
            if (self.comboBox_allDrives.currentText()[0]
                == self.cfg['acq']['base_dir'][0]):
                QMessageBox.warning(
                    self, 'Error',
                    'The mirror drive must be different from the '
                    'base directory drive!', QMessageBox.Ok)
            else:
                self.cfg['sys']['mirror_drive'] = (
                    self.comboBox_allDrives.currentText())
                super(MirrorDriveDlg, self).accept()

#------------------------------------------------------------------------------

class ImageMonitoringSettingsDlg(QDialog):
    """Adjust settings to monitor overviews and tiles. A test if image is
       within mean/SD range is performed for all images if option is activated.
       Tile-by-tile comparisons are performed for the selected tiles.
    """
    def __init__(self, config):
        super(ImageMonitoringSettingsDlg, self).__init__()
        self.cfg = config
        loadUi('..\\gui\\image_monitoring_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.spinBox_meanMin.setValue(
            int(self.cfg['monitoring']['mean_lower_limit']))
        self.spinBox_meanMax.setValue(
            int(self.cfg['monitoring']['mean_upper_limit']))
        self.spinBox_stddevMin.setValue(
            int(self.cfg['monitoring']['stddev_lower_limit']))
        self.spinBox_stddevMax.setValue(
            int(self.cfg['monitoring']['stddev_upper_limit']))
        self.lineEdit_monitorTiles.setText(
            self.cfg['monitoring']['monitor_tiles'][1:-1])
        self.lineEdit_monitorTiles.setText(
            self.cfg['monitoring']['monitor_tiles'][1:-1].replace('"', ''))
        self.doubleSpinBox_meanThreshold.setValue(
            float(self.cfg['monitoring']['tile_mean_threshold']))
        self.doubleSpinBox_stdDevThreshold.setValue(
            float(self.cfg['monitoring']['tile_stddev_threshold']))

    def accept(self):
        error_str = ''
        self.cfg['monitoring']['mean_lower_limit'] = str(
            self.spinBox_meanMin.value())
        self.cfg['monitoring']['mean_upper_limit'] = str(
            self.spinBox_meanMax.value())
        self.cfg['monitoring']['stddev_lower_limit'] = str(
            self.spinBox_stddevMin.value())
        self.cfg['monitoring']['stddev_upper_limit'] = str(
            self.spinBox_stddevMax.value())

        tile_str = self.lineEdit_monitorTiles.text().strip()
        if tile_str == 'all':
            self.cfg['monitoring']['monitor_tiles'] = '["all"]'
        else:
            success, tile_list = utils.validate_tile_list(tile_str)
            if success:
                self.cfg['monitoring']['monitor_tiles'] = json.dumps(tile_list)
            else:
                error_str = 'List of selected tiles badly formatted.'

        self.cfg['monitoring']['tile_mean_threshold'] = str(
            self.doubleSpinBox_meanThreshold.value())
        self.cfg['monitoring']['tile_stddev_threshold'] = str(
            self.doubleSpinBox_stdDevThreshold.value())
        if not error_str:
            super(ImageMonitoringSettingsDlg, self).accept()
        else:
            QMessageBox.warning(self, 'Error', error_str, QMessageBox.Ok)

#------------------------------------------------------------------------------

class AutofocusSettingsDlg(QDialog):
    """Adjust settings for the ZEISS autofocus or the heuristic autofocus."""

    def __init__(self, autofocus):
        super(AutofocusSettingsDlg, self).__init__()
        self.af = autofocus
        loadUi('..\\gui\\autofocus_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        if self.af.get_method() == 0:
            self.radioButton_useSmartSEM.setChecked(True)
        elif self.af.get_method() == 1:
            self.radioButton_useHeuristic.setChecked(True)
        self.radioButton_useSmartSEM.toggled.connect(self.group_box_update)
        self.group_box_update()
        self.lineEdit_refTiles.setText(
            str(self.af.get_ref_tiles())[1:-1].replace('\'', ''))
        max_diff = self.af.get_max_wd_stig_diff()
        self.doubleSpinBox_maxWDDiff.setValue(max_diff[0] * 1000000)
        self.doubleSpinBox_maxStigXDiff.setValue(max_diff[1])
        self.doubleSpinBox_maxStigYDiff.setValue(max_diff[2])
        self.spinBox_interval.setValue(self.af.get_interval())
        self.spinBox_autostigDelay.setValue(self.af.get_autostig_delay())
        self.doubleSpinBox_pixelSize.setValue(self.af.get_pixel_size())
        # For heuristic autofocus:
        deltas = self.af.get_heuristic_deltas()
        self.doubleSpinBox_wdDiff.setValue(deltas[0] * 1000000)
        self.doubleSpinBox_stigXDiff.setValue(deltas[1])
        self.doubleSpinBox_stigYDiff.setValue(deltas[2])
        calib = self.af.get_heuristic_calibration()
        self.doubleSpinBox_focusCalib.setValue(calib[0])
        self.doubleSpinBox_stigXCalib.setValue(calib[1])
        self.doubleSpinBox_stigYCalib.setValue(calib[2])
        rot, scale = self.af.get_heuristic_rot_scale()
        self.doubleSpinBox_stigRot.setValue(rot)
        self.doubleSpinBox_stigScale.setValue(scale)

    def group_box_update(self):
        status = self.radioButton_useSmartSEM.isChecked()
        self.groupBox_ZEISS_af.setEnabled(status)
        self.groupBox_heuristic_af.setEnabled(not status)

    def accept(self):
        error_str = ''
        if self.radioButton_useSmartSEM.isChecked():
            self.af.set_method(0)
        else:
            self.af.set_method(1)

        success, tile_list = utils.validate_tile_list(
            self.lineEdit_refTiles.text())
        if success:
            self.af.set_ref_tiles(tile_list)
        else:
            error_str = 'List of selected tiles badly formatted.'
        max_diffs = [self.doubleSpinBox_maxWDDiff.value() / 1000000,
                     self.doubleSpinBox_maxStigXDiff.value(),
                     self.doubleSpinBox_maxStigYDiff.value()]
        self.af.set_max_wd_stig_diff(max_diffs)
        self.af.set_interval(self.spinBox_interval.value())
        self.af.set_autostig_delay(self.spinBox_autostigDelay.value())
        self.af.set_pixel_size(self.doubleSpinBox_pixelSize.value())
        deltas = [self.doubleSpinBox_wdDiff.value() / 1000000,
                  self.doubleSpinBox_stigXDiff.value(),
                  self.doubleSpinBox_stigYDiff.value()]
        self.af.set_heuristic_deltas(deltas)
        self.af.set_heuristic_calibration(
            [self.doubleSpinBox_focusCalib.value(),
             self.doubleSpinBox_stigXCalib.value(),
             self.doubleSpinBox_stigYCalib.value()])
        self.af.set_heuristic_rot_scale(
            [self.doubleSpinBox_stigRot.value(),
             self.doubleSpinBox_stigScale.value()])
        if not error_str:
            super(AutofocusSettingsDlg, self).accept()
        else:
            QMessageBox.warning(self, 'Error', error_str, QMessageBox.Ok)

#------------------------------------------------------------------------------

class PlasmaCleanerDlg(QDialog):
    """Set parameters for the downstream asher, run it."""

    def __init__(self, plc_):
        super(PlasmaCleanerDlg, self).__init__()
        self.plc = plc_
        loadUi('..\\gui\\plasma_cleaner_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('icon.ico'))
        self.setFixedSize(self.size())
        self.show()
        try:
            self.spinBox_currentPower.setValue(self.plc.get_power())
            self.spinBox_currentDuration.setValue(self.plc.get_duration())
        except:
            QMessageBox.warning(
                self, 'Error',
                'Could not read current settings from plasma cleaner.',
                QMessageBox.Ok)
        self.pushButton_setTargets.clicked.connect(self.set_target_parameters)
        self.pushButton_startCleaning.clicked.connect(self.start_cleaning)
        self.pushButton_abortCleaning.clicked.connect(self.abort_cleaning)

    def set_target_parameters(self):
        try:
            self.plc.set_power(self.spinBox_targetPower.value())
            sleep(0.5)
            self.lineEdit_currentPower.setText(str(self.plc.get_power()))
            self.plc.set_duration(self.spinBox_targetDuration.value())
            sleep(0.5)
            self.lineEdit_currentDuration.setText(str(self.plc.get_duration()))
        except:
            QMessageBox.warning(
                self, 'Error',
                'An error occured when sending the target settings '
                'to the plasma cleaner.',
                QMessageBox.Ok)

    def start_cleaning(self):
        result = QMessageBox.warning(
                     self, 'About to ignite plasma',
                     'Are you sure you want to run the plasma cleaner at ' +
                     self.lineEdit_currentPower.text() + ' W for ' +
                     self.lineEdit_currentDuration.text() + ' min?',
                     QMessageBox.Ok | QMessageBox.Cancel)
        if result == QMessageBox.Ok:
            result = QMessageBox.warning(
                self, 'WARNING: Check vacuum Status',
                'IMPORTANT: \nPlease confirm with "OK" that the SEM chamber '
                'is at HIGH VACUUM.\nIf not, ABORT!',
                QMessageBox.Ok | QMessageBox.Abort)
            if result == QMessageBox.Ok:
                self.pushButton_startCleaning.setEnabled(False)
                self.pushButton_abortCleaning.setEnabled(True)
                # TODO: Thread, show cleaning status.
                self.plc.perform_cleaning()

    def abort_cleaning(self):
        self.plc.abort_cleaning()
        self.pushButton_startCleaning.setEnabled(True)
        self.pushButton_startCleaning.setText(
            'Start in-chamber cleaning process')
        self.pushButton_abortCleaning.setEnabled(False)

#------------------------------------------------------------------------------

class ApproachDlg(QDialog):
    """Remove slices without imaging. User can specify how many slices and
       the cutting thickness.
    """

    def __init__(self, microtome, main_window_queue, main_window_trigger):
        super(ApproachDlg, self).__init__()
        self.microtome = microtome
        self.main_window_queue = main_window_queue
        self.main_window_trigger = main_window_trigger
        loadUi('..\\gui\\approach_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Set up trigger and queue to update dialog GUI during approach:
        self.progress_trigger = Trigger()
        self.progress_trigger.s.connect(self.update_progress)
        self.finish_trigger = Trigger()
        self.finish_trigger.s.connect(self.finish_approach)
        self.spinBox_numberSlices.setRange(1, 100)
        self.spinBox_numberSlices.setSingleStep(1)
        self.spinBox_numberSlices.setValue(5)
        self.spinBox_numberSlices.valueChanged.connect(self.update_progress)
        self.pushButton_startApproach.clicked.connect(self.start_approach)
        self.pushButton_abortApproach.clicked.connect(self.abort_approach)
        self.pushButton_startApproach.setEnabled(True)
        self.pushButton_abortApproach.setEnabled(False)
        self.slice_counter = 0
        self.approach_in_progress = False
        self.max_slices = self.spinBox_numberSlices.value()
        self.update_progress()

    def add_to_log(self, msg):
        self.main_window_queue.put(utils.format_log_entry(msg))
        self.main_window_trigger.s.emit()

    def update_progress(self):
        self.max_slices = self.spinBox_numberSlices.value()
        if self.slice_counter > 0:
            remaining_time_str = (
                '    ' + str(int((self.max_slices - self.slice_counter)*12))
                + ' seconds left')
        else:
            remaining_time_str = ''
        self.label_statusApproach.setText(str(self.slice_counter) + '/'
                                          + str(self.max_slices)
                                          + remaining_time_str)
        self.progressBar_approach.setValue(
            int(self.slice_counter/self.max_slices * 100))

    def start_approach(self):
        self.aborted = False
        self.pushButton_startApproach.setEnabled(False)
        self.pushButton_abortApproach.setEnabled(True)
        self.buttonBox.setEnabled(False)
        self.spinBox_thickness.setEnabled(False)
        self.spinBox_numberSlices.setEnabled(False)
        self.main_window_queue.put('APPROACH BUSY')
        self.main_window_trigger.s.emit()
        thread = threading.Thread(target=self.approach_thread)
        thread.start()

    def finish_approach(self):
        self.add_to_log('3VIEW: Clearing knife.')
        self.microtome.clear_knife()
        if self.microtome.get_error_state() > 0:
            self.add_to_log('CTRL: Error clearing knife.')
            self.microtome.reset_error_state()
            QMessageBox.warning(self, 'Error',
                                'Warning: Clearing the knife failed. '
                                'Try to clear manually.', QMessageBox.Ok)
        self.main_window_queue.put('STATUS IDLE')
        self.main_window_trigger.s.emit()
        # Show message box to user and reset counter and progress bar:
        if not self.aborted:
            QMessageBox.information(
                self, 'Approach finished',
                str(self.max_slices) + ' slices have been cut successfully. '
                'Total sample depth removed: '
                + str(self.max_slices * self.thickness / 1000) + ' µm.',
                QMessageBox.Ok)
            self.slice_counter = 0
            self.update_progress()
        else:
            QMessageBox.warning(
                self, 'Approach aborted',
                str(self.slice_counter) + ' slices have been cut. '
                'Total sample depth removed: '
                + str(self.slice_counter * self.thickness / 1000) + ' µm.',
                QMessageBox.Ok)
            self.slice_counter = 0
            self.update_progress()
        self.pushButton_startApproach.setEnabled(True)
        self.pushButton_abortApproach.setEnabled(False)
        self.buttonBox.setEnabled(True)
        self.spinBox_thickness.setEnabled(True)
        self.spinBox_numberSlices.setEnabled(True)
        self.approach_in_progress = False

    def approach_thread(self):
        self.approach_in_progress = True
        self.slice_counter = 0
        self.max_slices = self.spinBox_numberSlices.value()
        self.thickness = self.spinBox_thickness.value()
        self.progress_trigger.s.emit()
        # Get current z position of stage:
        z_position = self.microtome.get_stage_z(wait_interval=1)
        if z_position is None or z_position < 0:
            # Try again:
            z_position = self.microtome.get_stage_z(wait_interval=2)
            if z_position is None or z_position < 0:
                self.add_to_log(
                    'CTRL: Error reading Z position. Approach aborted.')
                self.microtome.reset_error_state()
                self.aborted = True
        self.main_window_queue.put('UPDATE Z')
        self.main_window_trigger.s.emit()
        self.microtome.near_knife()
        self.add_to_log('3VIEW: Moving knife to near position.')
        if self.microtome.get_error_state() > 0:
            self.add_to_log(
                'CTRL: Error moving knife to near position. Approach aborted.')
            self.aborted = True
            self.microtome.reset_error_state()
        # ====== Approach loop =========
        while (self.slice_counter < self.max_slices) and not self.aborted:
            # Move to new z position:
            z_position = z_position + (self.thickness / 1000)
            self.add_to_log(
                '3VIEW: Move to new Z: ' + '{0:.3f}'.format(z_position))
            self.microtome.move_stage_to_z(z_position)
            # Show new Z position in main window:
            self.main_window_queue.put('UPDATE Z')
            self.main_window_trigger.s.emit()
            # Check if there were microtome problems:
            if self.microtome.get_error_state() > 0:
                self.add_to_log(
                    'CTRL: Z stage problem detected. Approach aborted.')
                self.aborted = True
                self.microtome.reset_error_state()
                break
            self.add_to_log('3VIEW: Cutting in progress ('
                            + str(self.thickness) + ' nm cutting thickness).')
            # Do the approach cut (cut, retract, in near position)
            self.microtome.do_full_approach_cut()
            sleep(10)
            if self.microtome.get_error_state() > 0:
                self.add_to_log(
                    'CTRL: Cutting problem detected. Approach aborted.')
                self.aborted = True
                self.microtome.reset_error_state()
                break
            else:
                self.add_to_log('3VIEW: Approach cut completed.')
                self.slice_counter += 1
                # Update progress bar and slice counter
                self.progress_trigger.s.emit()
        # ====== End of approach loop =========
        # Signal that thread is done:
        self.finish_trigger.s.emit()

    def abort_approach(self):
        self.aborted = True
        self.pushButton_abortApproach.setEnabled(False)

    def closeEvent(self, event):
        if not self.approach_in_progress:
            event.accept()
        else:
            event.ignore()

    def accept(self):
        if not self.approach_in_progress:
            super(ApproachDlg, self).accept()

#------------------------------------------------------------------------------

class GrabFrameDlg(QDialog):
    """Acquires or saves a single frame from SmartSEM."""

    def __init__(self, config, sem, main_window_queue, main_window_trigger):
        super(GrabFrameDlg, self).__init__()
        self.cfg = config
        self.sem = sem
        self.main_window_queue = main_window_queue
        self.main_window_trigger = main_window_trigger
        self.finish_trigger = Trigger()
        self.finish_trigger.s.connect(self.scan_complete)
        loadUi('..\\gui\\grab_frame_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        timestamp = str(datetime.datetime.now())
        # Remove some characters from timestap to get valid file name:
        timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
        self.file_name = 'image_' + timestamp
        self.lineEdit_filename.setText(self.file_name)
        frame_size, pixel_size, dwell_time = self.sem.get_grab_settings()
        store_res_list = [
            '%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_frameSize.addItems(store_res_list)
        self.comboBox_frameSize.setCurrentIndex(frame_size)
        self.doubleSpinBox_pixelSize.setValue(pixel_size)
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        self.comboBox_dwellTime.setCurrentIndex(
            self.sem.DWELL_TIME.index(dwell_time))
        self.pushButton_scan.clicked.connect(self.scan_frame)
        self.pushButton_save.clicked.connect(self.save_frame)

    def scan_frame(self):
        """Scan and save a single frame using the current grab settings."""
        self.file_name = self.lineEdit_filename.text()
        # Save and apply grab settings:
        selected_dwell_time = self.sem.DWELL_TIME[
            self.comboBox_dwellTime.currentIndex()]
        self.sem.set_grab_settings(self.comboBox_frameSize.currentIndex(),
                                   self.doubleSpinBox_pixelSize.value(),
                                   selected_dwell_time)
        self.sem.apply_grab_settings()
        self.pushButton_scan.setText('Wait')
        self.pushButton_scan.setEnabled(False)
        self.pushButton_save.setEnabled(False)
        QApplication.processEvents()
        thread = threading.Thread(target=self.perform_scan)
        thread.start()

    def perform_scan(self):
        """Acquire a new frame. Executed in a thread because it may take some
           time and GUI should not freeze.
        """
        self.scan_success = self.sem.acquire_frame(
            self.cfg['acq']['base_dir'] + '\\' + self.file_name + '.tif')
        self.finish_trigger.s.emit()

    def scan_complete(self):
        """This function is called when the scan is complete.
           Reset the GUI and show result of grab command.
        """
        self.pushButton_scan.setText('Scan and grab')
        self.pushButton_scan.setEnabled(True)
        self.pushButton_save.setEnabled(True)
        if self.scan_success:
            self.add_to_log('CTRL: Single frame acquired by user.')
            QMessageBox.information(
                self, 'Frame acquired',
                'The image was acquired and saved as '
                + self.file_name +
                '.tif in the current base directory.',
                QMessageBox.Ok)
        else:
            QMessageBox.warning(
                self, 'Error',
                'An error ocurred while attempting to acquire the frame: '
                + self.sem.get_error_cause(),
                QMessageBox.Ok)
            self.sem.reset_error_state()

    def save_frame(self):
        """Save the image currently visible in SmartSEM."""
        self.file_name = self.lineEdit_filename.text()
        success = self.sem.save_frame(
            self.cfg['acq']['base_dir'] + '\\' + self.file_name + '.tif')
        if success:
            self.add_to_log('CTRL: Single frame saved by user.')
            QMessageBox.information(
                self, 'Frame saved',
                'The current image shown in SmartSEM was saved as '
                + self.file_name + '.tif in the current base directory.',
                QMessageBox.Ok)
        else:
            QMessageBox.warning(
                self, 'Error',
                'An error ocurred while attempting to save the current '
                'SmarSEM image: '
                + self.sem.get_error_cause(),
                QMessageBox.Ok)
            self.sem.reset_error_state()

    def add_to_log(self, msg):
        """Use trigger and queue to add an entry to the main log."""
        self.main_window_queue.put(utils.format_log_entry(msg))
        self.main_window_trigger.s.emit()

#------------------------------------------------------------------------------

class EHTDlg(QDialog):
    """Show EHT status and let user switch beam on or off."""

    def __init__(self, sem):
        super(EHTDlg, self).__init__()
        self.sem = sem
        loadUi('..\\gui\\eht_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_on.clicked.connect(self.turn_on)
        self.pushButton_off.clicked.connect(self.turn_off)
        self.update_status()

    def update_status(self):
        if self.sem.is_eht_on():
            pal = QPalette(self.label_EHTStatus.palette())
            pal.setColor(QPalette.WindowText, QColor(Qt.red))
            self.label_EHTStatus.setPalette(pal)
            self.label_EHTStatus.setText('ON')
            self.pushButton_on.setEnabled(False)
            self.pushButton_off.setEnabled(True)
        else:
            pal = QPalette(self.label_EHTStatus.palette())
            pal.setColor(QPalette.WindowText, QColor(Qt.black))
            self.label_EHTStatus.setPalette(pal)
            self.label_EHTStatus.setText('OFF')
            self.pushButton_on.setEnabled(True)
            self.pushButton_off.setEnabled(False)

    def turn_on(self):
        self.pushButton_on.setEnabled(False)
        self.pushButton_on.setText('Wait')
        thread = threading.Thread(target=self.send_on_cmd_and_wait)
        thread.start()

    def turn_off(self):
        self.pushButton_off.setEnabled(False)
        self.pushButton_off.setText('Wait')
        QApplication.processEvents()
        thread = threading.Thread(target=self.send_off_cmd_and_wait)
        thread.start()

    def send_on_cmd_and_wait(self):
        self.sem.turn_eht_on()
        max_wait_time = 15
        while not self.sem.is_eht_on() and max_wait_time > 0:
            sleep(1)
            max_wait_time -= 1
        self.pushButton_on.setText('ON')
        self.update_status()

    def send_off_cmd_and_wait(self):
        self.sem.turn_eht_off()
        max_wait_time = 15
        while not self.sem.is_eht_off() and max_wait_time > 0:
            sleep(1)
            max_wait_time -= 1
        self.pushButton_off.setText('OFF')
        self.update_status()

#------------------------------------------------------------------------------

class FTSetParamsDlg(QDialog):
    """Read working distance and stigmation values from user input or
       from SmarSEM. Used for setting WD/STIG for individual tiles in
       focus tool.
    """

    def __init__(self, sem, current_wd, current_stig_x, current_stig_y):
        super(FTSetParamsDlg, self).__init__()
        self.sem = sem
        loadUi('..\\gui\\focus_tool_set_params_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_getFromSmartSEM.clicked.connect(self.get_from_sem)
        if current_wd is not None:
            self.doubleSpinBox_currentFocus.setValue(1000 * current_wd)
        else:
            self.doubleSpinBox_currentFocus.setValue(1000 * self.sem.get_wd())
        if current_stig_x is not None:
            self.doubleSpinBox_currentStigX.setValue(current_stig_x)
        else:
            self.doubleSpinBox_currentStigX.setValue(self.sem.get_stig_x())
        if current_stig_y is not None:
            self.doubleSpinBox_currentStigY.setValue(current_stig_y)
        else:
            self.doubleSpinBox_currentStigY.setValue(self.sem.get_stig_y())

    def get_from_sem(self):
        self.doubleSpinBox_currentFocus.setValue(1000 * self.sem.get_wd())
        self.doubleSpinBox_currentStigX.setValue(self.sem.get_stig_x())
        self.doubleSpinBox_currentStigY.setValue(self.sem.get_stig_y())

    def return_params(self):
        return (self.new_wd, self.new_stig_x, self.new_stig_y)

    def accept(self):
        self.new_wd = self.doubleSpinBox_currentFocus.value() / 1000
        self.new_stig_x = self.doubleSpinBox_currentStigX.value()
        self.new_stig_y = self.doubleSpinBox_currentStigY.value()
        self.sem.set_wd(self.new_wd)
        self.sem.set_stig_xy(self.new_stig_x, self.new_stig_y)
        super(FTSetParamsDlg, self).accept()

#------------------------------------------------------------------------------

class MotorTestDlg(QDialog):
    """Perform a random-walk XYZ motor test. Experimental, only for testing/
       debugging."""

    def __init__(self, cfg, microtome, main_window_queue, main_window_trigger):
        super(MotorTestDlg, self).__init__()
        self.cfg = cfg
        self.microtome = microtome
        self.main_window_queue = main_window_queue
        self.main_window_trigger = main_window_trigger
        loadUi('..\\gui\\motor_test_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Set up trigger and queue to update dialog GUI during approach:
        self.progress_trigger = Trigger()
        self.progress_trigger.s.connect(self.update_progress)
        self.finish_trigger = Trigger()
        self.finish_trigger.s.connect(self.test_finished)
        self.spinBox_duration.setRange(1, 9999)
        self.spinBox_duration.setSingleStep(10)
        self.spinBox_duration.setValue(10)
        self.pushButton_startTest.clicked.connect(self.start_random_walk)
        self.pushButton_abortTest.clicked.connect(self.abort_random_walk)
        self.pushButton_startTest.setEnabled(True)
        self.pushButton_abortTest.setEnabled(False)
        self.test_in_progress = False
        self.start_time = None

    def add_to_log(self, msg):
        self.main_window_queue.put(utils.format_log_entry(msg))
        self.main_window_trigger.s.emit()

    def update_progress(self):
        if self.start_time is not None:
            elapsed_time = time() - self.start_time
            if elapsed_time > self.duration * 60:
                self.test_in_progress = False
                self.progressBar.setValue(100)
            else:
                self.progressBar.setValue(
                    int(elapsed_time/(self.duration * 60) * 100))

    def start_random_walk(self):
        self.aborted = False
        self.start_z = self.microtome.get_stage_z()
        if self.start_z is not None:
            self.pushButton_startTest.setEnabled(False)
            self.pushButton_abortTest.setEnabled(True)
            self.buttonBox.setEnabled(False)
            self.spinBox_duration.setEnabled(False)
            self.progressBar.setValue(0)
            thread = threading.Thread(target=self.random_walk_thread)
            thread.start()
        else:
            self.microtome.reset_error_state()
            QMessageBox.warning(self, 'Error',
                'Could not read current z stage position',
                QMessageBox.Ok)

    def abort_random_walk(self):
        self.aborted = True
        self.test_in_progress = False

    def test_finished(self):
        self.add_to_log('3VIEW: Motor test finished.')
        self.add_to_log('3VIEW: Moving back to starting z position.')
        # Safe mode must be set to false because diff likely > 200 nm
        self.microtome.move_stage_to_z(self.start_z, safe_mode=False)
        if self.microtome.get_error_state() > 0:
            self.microtome.reset_error_state()
            QMessageBox.warning(
                self, 'Error',
                'Error moving stage back to starting position. Please '
                'check the current z coordinate before (re)starting a stack.',
                QMessageBox.Ok)
        if self.aborted:
            QMessageBox.information(
                self, 'Aborted',
                'Motor test was aborted by user.'
                + '\nPlease make sure that z coordinate is back at starting '
                'position of ' + str(self.start_z) + '.',
                QMessageBox.Ok)
        else:
            QMessageBox.information(
                self, 'Test complete',
                'Motor test complete.\nA total of '
                + str(self.number_tests) + ' xyz moves were performed.\n'
                'Number of errors: ' + str(self.number_errors)
                + '\nPlease make sure that z coordinate is back at starting '
                'position of ' + str(self.start_z) + '.',
                QMessageBox.Ok)
        self.pushButton_startTest.setEnabled(True)
        self.pushButton_abortTest.setEnabled(False)
        self.buttonBox.setEnabled(True)
        self.spinBox_duration.setEnabled(True)
        self.test_in_progress = False

    def random_walk_thread(self):
        self.test_in_progress = True
        self.duration = self.spinBox_duration.value()
        self.start_time = time()
        self.progress_trigger.s.emit()
        self.number_tests = 0
        self.number_errors = 0
        current_x, current_y = 0, 0
        current_z = self.start_z
        # Open log file:
        logfile = open(self.cfg['acq']['base_dir'] + '\\motor_test_log.txt',
                       'w', buffering=1)
        while self.test_in_progress:
            # Start random walk
            current_x += (random() - 0.5) * 50
            current_y += (random() - 0.5) * 50
            if self.number_tests % 2 == 0:
                current_z += (random() - 0.5) * 0.2
            else:
                current_z += 0.025
            if current_z < 0:
                current_z = 0
            # If end of permissable range is reached, go back to starting point
            if (abs(current_x) > 600 or
                abs(current_y) > 600 or
                current_z > 600):
                current_x, current_y = 0, 0
                current_z = self.start_z
            logfile.write('{0:.3f}, '.format(current_x)
                          + '{0:.3f}, '.format(current_y)
                          + '{0:.3f}'.format(current_z) + '\n')
            self.microtome.move_stage_to_xy((current_x, current_y))
            if self.microtome.get_error_state() > 0:
                self.number_errors += 1
                logfile.write('ERROR DURING XY MOVE: '
                              + self.microtome.get_error_cause()
                              + '\n')
                self.microtome.reset_error_state()
            else:
                self.microtome.move_stage_to_z(current_z)
                if self.microtome.get_error_state() > 0:
                    self.number_errors += 1
                    logfile.write('ERROR DURING Z MOVE: '
                                  + self.microtome.get_error_cause()
                                  + '\n')
                    self.microtome.reset_error_state()
                else:
                    logfile.write('OK\n')

            self.number_tests += 1
            self.update_progress()
        logfile.write('NUMBER OF ERRORS: ' + str(self.number_errors))
        logfile.close()
        # Signal that thread is done:
        self.finish_trigger.s.emit()

    def abort_test(self):
        self.aborted = True
        self.pushButton_abortTest.setEnabled(False)

    def closeEvent(self, event):
        if not self.test_in_progress:
            event.accept()
        else:
            event.ignore()

    def accept(self):
        if not self.approach_in_progress:
            super(MotorTestDlg, self).accept()

#------------------------------------------------------------------------------

class StubOVDlg(QDialog):
    """Acquire a stub overview mosaic image. The user can specify the location
       in stage coordinates and the size of the mosaic.
    """

    def __init__(self, position, size_selector,
                 base_dir, slice_counter,
                 sem, microtome, ovm, cs,
                 main_window_queue, main_window_trigger):
        super(StubOVDlg, self).__init__()
        loadUi('..\\gui\\stub_ov_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.base_dir = base_dir
        self.slice_counter = slice_counter
        self.sem = sem
        self.microtome = microtome
        self.ovm = ovm
        self.cs = cs
        self.main_window_queue = main_window_queue
        self.main_window_trigger = main_window_trigger
        # Set up trigger and queue to update dialog GUI during approach:
        self.acq_thread_trigger = Trigger()
        self.acq_thread_trigger.s.connect(self.process_thread_signal)
        self.acq_thread_queue = Queue()
        self.abort_queue = Queue()
        self.acq_in_progress = False
        self.pushButton_acquire.clicked.connect(self.acquire_stub_ov)
        self.pushButton_abort.clicked.connect(self.abort)
        self.spinBox_X.setValue(position[0])
        self.spinBox_Y.setValue(position[1])
        self.size_selector = size_selector
        self.size_list = []
        self.durations = []
        for i in range(7):
            # Show available mosaic sizes and the corresponding estimated
            # durations in min
            rows, cols = ovm.STUB_OV_SIZE[i][0], ovm.STUB_OV_SIZE[i][1]
            width = int((cols * ovm.STUB_OV_FRAME_WIDTH
                        - (cols-1) * ovm.STUB_OV_OVERLAP)
                        * ovm.STUB_OV_PIXEL_SIZE / 1000)
            height = int((rows * ovm.STUB_OV_FRAME_HEIGHT
                         - (rows-1) * ovm.STUB_OV_OVERLAP)
                         * ovm.STUB_OV_PIXEL_SIZE / 1000)
            time = int(round((rows * cols * 10 + 20) / 60))
            self.size_list.append(str(width) + ' µm × ' + str(height) + ' µm')
            self.durations.append('Up to ' + str(time) + ' min')
        # Grid size selection:
        self.comboBox_sizeSelector.addItems(self.size_list)
        self.comboBox_sizeSelector.setCurrentIndex(self.size_selector)
        self.comboBox_sizeSelector.currentIndexChanged.connect(
            self.update_duration)
        self.label_duration.setText(self.durations[2])
        self.previous_centre = self.cs.get_stub_ov_centre_s()
        self.previous_origin = self.cs.get_stub_ov_origin_s()
        self.previous_size_selector = self.ovm.get_stub_ov_size_selector()

    def process_thread_signal(self):
        """Process commands from the queue when a trigger signal occurs
           while the acquisition of the stub overview is running.
        """
        msg = self.acq_thread_queue.get()
        if msg == 'UPDATE STAGEPOS':
            self.show_new_stage_pos()
        elif msg[:15] == 'UPDATE PROGRESS':
            percentage = int(msg[15:])
            self.progressBar.setValue(percentage)
        elif msg == 'STUB OV SUCCESS':
            self.main_window_queue.put('STUB OV SUCCESS')
            self.main_window_trigger.s.emit()
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
            self.main_window_queue.put('STUB OV FAILURE')
            self.main_window_trigger.s.emit()
            # Restore previous origin:
            self.cs.set_stub_ov_origin_s(self.previous_origin)
            self.cs.set_stub_ov_centre_s(self.previous_centre)
            self.ovm.set_stub_ov_size_selector(self.previous_size_selector)
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
            self.main_window_queue.put('STATUS IDLE')
            self.main_window_trigger.s.emit()
            # Restore previous origin:
            self.cs.set_stub_ov_origin_s(self.previous_origin)
            self.cs.set_stub_ov_centre_s(self.previous_centre)
            self.ovm.set_stub_ov_size_selector(self.previous_size_selector)
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
        self.main_window_queue.put('UPDATE XY')
        self.main_window_trigger.s.emit()

    def add_to_log(self, msg):
        self.main_window_queue.put(utils.format_log_entry(msg))
        self.main_window_trigger.s.emit()

    def acquire_stub_ov(self):
        """Acquire the stub overview. Acquisition routine runs in
           a thread.
        """
        # Save previous stub OV origin in case user aborts acq:
        self.acq_in_progress = True
        position = (self.spinBox_X.value(), self.spinBox_Y.value())
        size_selector = self.comboBox_sizeSelector.currentIndex()
        self.add_to_log(
            'CTRL: User-requested acquisition of stub OV mosaic started.')
        self.pushButton_acquire.setEnabled(False)
        self.pushButton_abort.setEnabled(True)
        self.buttonBox.setEnabled(False)
        self.spinBox_X.setEnabled(False)
        self.spinBox_Y.setEnabled(False)
        self.comboBox_sizeSelector.setEnabled(False)
        self.progressBar.setValue(0)
        self.main_window_queue.put('STUB OV BUSY')
        self.main_window_trigger.s.emit()
        QApplication.processEvents()
        stub_acq_thread = threading.Thread(
                              target=acq_func.acquire_stub_ov,
                              args=(self.base_dir, self.slice_counter,
                                    self.sem, self.microtome,
                                    position, size_selector,
                                    self.ovm, self.cs,
                                    self.acq_thread_queue,
                                    self.acq_thread_trigger,
                                    self.abort_queue,))
        stub_acq_thread.start()

    def abort(self):
        if self.abort_queue.empty():
            self.abort_queue.put('ABORT')
            self.pushButton_abort.setEnabled(False)

    def closeEvent(self, event):
        if not self.acq_in_progress:
            event.accept()
        else:
            event.ignore()

#------------------------------------------------------------------------------

class AboutBox(QDialog):
    """Show the About dialog box with info about SBEMimage and the current
       version and release date.
    """

    def __init__(self, VERSION):
        super(AboutBox, self).__init__()
        loadUi('..\\gui\\about_box.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.label_version.setText('Version ' + VERSION)
        self.labelIcon.setPixmap(QPixmap('..\\img\\logo.png'))
        self.setFixedSize(self.size())
        self.show()
