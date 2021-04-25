# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module contains all dialog windows that are called from the Main
Controls, and the startup dialog (ConfigDlg).
"""

import math
import os
import re
import string
import threading
import datetime
import glob
import json
import validators
import requests
import shutil
import configparser

from random import random
from time import sleep, time

from validate_email import validate_email
from math import atan, atan2, sqrt
from statistics import mean
from PIL import Image
from skimage.io import imread
from skimage.feature import register_translation
import numpy as np
from imreg_dft import translation
from zipfile import ZipFile

from PyQt5.uic import loadUi
from PyQt5.QtCore import Qt, QObject, QSize, pyqtSignal, QThread
from PyQt5.QtGui import QPixmap, QIcon, QPalette, QColor, QFont
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, \
                            QFileDialog, QLineEdit, QDialogButtonBox

import utils
from utils import Error
import acq_func


class UpdateQThread(QThread):
    """Helper for updating QDialogs using QThread"""
    update = pyqtSignal()

    def __init__(self, secs):
        self.active = True
        self.secs = secs
        QThread.__init__(self)

    def run(self):
        while self.active:
            self.update.emit()
            sleep(self.secs)

    def stop(self):
        self.active = False


class ConfigDlg(QDialog):
    """Start-up dialog window that lets user select a configuration file.

    The previously used configuration is preselected in the list widget. If no
    previously used configuration can be found, use default.ini. If status.dat
    does not exists, show warning message box.
    """

    def __init__(self, VERSION):
        super().__init__()
        self.device_presets_selection = [None, None]
        self.load_presets_enabled = False
        loadUi('..\\gui\\config_dlg.ui', self)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        if 'dev' in VERSION.lower():
            self.label_version.setText(f'DEVELOPMENT VERSION ({VERSION})')
        else:
            self.label_version.setText('Version ' + VERSION)
        self.labelIcon.setPixmap(QPixmap('..\\img\\logo.png'))
        self.label_website.setText('<a href="https://github.com/SBEMimage">'
                                   'https://github.com/SBEMimage</a>')
        self.label_website.setOpenExternalLinks(True)
        self.setFixedSize(self.size())
        self.show()
        self.abort = False
        # Connect button to load device selection dialog
        self.pushButton_deviceSelection.clicked.connect(
           self.open_device_selection_dlg)

        # Populate the list widget with existing .ini files
        inifile_list = []
        for file in os.listdir('..\\cfg'):
            if file.endswith('.ini'):
                inifile_list.append(file)
        self.listWidget_filelist.addItems(inifile_list)
        self.listWidget_filelist.itemSelectionChanged.connect(
            self.ini_file_selection_changed)

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
            # If status.dat does not exist, the program must have crashed or a
            # second instance is running. Preselect default.ini in the list,
            # and display a warning. The warning is suppressed if
            # inifile_list contains only default.ini.
            default_item = self.listWidget_filelist.findItems(
                'default.ini', Qt.MatchExactly)[0]
            self.listWidget_filelist.setCurrentItem(default_item)
            if len(inifile_list) > 1:
                QMessageBox.warning(
                    self, 'Warning: Crash occurred or other SBEMimage instance '
                    'is running',
                    'SBEMimage appears to have crashed during the '
                    'previous run, or another instance of SBEMimage is already '
                    'running. Please close the other instance or abort this '
                    'one.\n\n'
                    'If you want to continue an acquisition after a crash, '
                    'double-check all settings before restarting!\n\n'
                    'You can report a crash here, ideally with the error '
                    'message(s) shown in the Console window: '
                    'https://github.com/SBEMimage/SBEMimage/issues',
                    QMessageBox.Ok)

    def ini_file_selection_changed(self):
        # Disable device presets selection button if default.ini selected
        if self.listWidget_filelist.currentItem().text() == 'default.ini':
            self.pushButton_deviceSelection.setEnabled(False)
        else:
            self.pushButton_deviceSelection.setEnabled(True)
        
    def open_device_selection_dlg(self):
        dialog = DeviceSelectionDlg(self.load_presets_enabled,
                                    self.device_presets_selection)
        if dialog.exec_():
            self.device_presets_selection = dialog.selected_presets
            self.load_presets_enabled = dialog.presets_enabled

    def reject(self):
        self.abort = True
        super().reject()

    def get_ini_file(self):
        if not self.abort:
            return self.listWidget_filelist.currentItem().text()
        else:
            return 'abort'

# ------------------------------------------------------------------------------

class DeviceSelectionDlg(QDialog):
    """Select SEM/microtome presets to be loaded into the system configuration.
    """

    def __init__(self, presets_enabled, selected_presets):
        super().__init__()
        self.selected_presets = selected_presets
        self.presets_enabled = presets_enabled
        loadUi('..\\gui\\device_selection_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        syscfg = configparser.ConfigParser()
        try:
            with open('..\\cfg\\system.cfg', 'r') as file:
                syscfg.read_file(file)
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Could not read list of supported devices from system.cfg\n'
                'Exception: ' + str(e),
                QMessageBox.Ok)
            return

        sem_list = ['None'] + json.loads(syscfg['device']['sem_recognized'])
        microtome_list = (
            ['None'] + json.loads(syscfg['device']['microtome_recognized']))
        
        # Populate comboboxes with names of supported devices
        self.comboBox_SEMs.addItems(sem_list)
        self.comboBox_microtomes.addItems(microtome_list)
        if self.selected_presets[0] is not None:
            self.comboBox_SEMs.setCurrentIndex(
                self.comboBox_SEMs.findText(self.selected_presets[0]))
        if self.selected_presets[1] is not None:
            self.comboBox_microtomes.setCurrentIndex(
                self.comboBox_microtomes.findText(self.selected_presets[1]))

        # Only enable comboboxes if "load presets" checked
        self.checkBox_loadPresets.stateChanged.connect(
            self.enable_device_selectors)
        self.checkBox_loadPresets.setChecked(self.presets_enabled)

    def enable_device_selectors(self):
        self.comboBox_SEMs.setEnabled(
            self.checkBox_loadPresets.isChecked())
        self.comboBox_microtomes.setEnabled(
            self.checkBox_loadPresets.isChecked())

    def accept(self):
        if self.checkBox_loadPresets.isChecked():
            self.presets_enabled = True
            if str(self.comboBox_SEMs.currentText()) != 'None':
                self.selected_presets[0] = str(self.comboBox_SEMs.currentText())
            else:
                self.selected_presets[0] = None
            if str(self.comboBox_microtomes.currentText()) != 'None':
                self.selected_presets[1] = str(
                    self.comboBox_microtomes.currentText())
            else:
                self.selected_presets[1] = None
        else:
            self.presets_enabled = False
            self.selected_presets = [None, None]
        super().accept()

# ------------------------------------------------------------------------------

class SaveConfigDlg(QDialog):
    """Save current user configuration in a new config (.ini) file."""

    def __init__(self, syscfg_file='', new_syscfg=False):
        super().__init__()
        self.new_syscfg = new_syscfg
        loadUi('..\\gui\\save_config_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_cfgFileName.setText('')
        # lineEdit for syscfg is disabled by default
        self.lineEdit_syscfgFileName.setText(syscfg_file)
        self.file_name = None
        self.sysfile_name = None
        # Show message if a new system configuration file will be created
        # and enable lineEdit
        if new_syscfg:
            QMessageBox.information(
                self, 'New user and system configuration',
                'You are about to save a custom user configuation based '
                'on default.ini. Please also choose a name for your '
                'system configuration in this dialog. The name you choose '
                'will be used for all future user configurations '
                'on this setup.\n\n'
                'To create additional user configurations (after creating '
                'this new one), please load any existing .ini file other than '
                'default.ini and save it under a new name.',
                QMessageBox.Ok)
            self.lineEdit_syscfgFileName.setEnabled(True)
            self.label_syscfgInput.setText(
                'Choose name for your system configuration:')

    def accept(self):
        success = True
        # Replace spaces in file name with underscores.
        self.lineEdit_cfgFileName.setText(
            self.lineEdit_cfgFileName.text().strip().replace(' ', '_'))
        self.lineEdit_syscfgFileName.setText(
            self.lineEdit_syscfgFileName.text().strip().replace(' ', '_'))
        # Check whether characters in name are permitted.
        reg = re.compile('^[a-zA-Z0-9_-]+$')
        if not (reg.match(self.lineEdit_cfgFileName.text())
                and (reg.match(self.lineEdit_syscfgFileName.text())
                     or not self.new_syscfg)):
            success = False
            QMessageBox.warning(
                self, 'Error',
                'Name is empty or badly formatted.',
                QMessageBox.Ok)
        # default.ini and system.cfg may not be chosen.
        if (self.lineEdit_cfgFileName.text().lower() == 'default' or
            self.lineEdit_syscfgFileName.text().lower() == 'system'):
            success = False
            QMessageBox.warning(
                self, 'Error',
                'You cannot choose "default" for the user configuration or '
                '"system" for the system configuration.',
                QMessageBox.Ok)
        # Check if files already exist
        if success:
            self.file_name = self.lineEdit_cfgFileName.text() + '.ini'
            if (os.path.isfile(os.path.join('..', 'cfg', self.file_name))):
                success = False
                QMessageBox.warning(
                    self, 'Error',
                    'User configuration with that name already exists!',
                    QMessageBox.Ok)
            self.sysfile_name = self.lineEdit_syscfgFileName.text() + '.cfg'
            if self.new_syscfg and os.path.isfile(
                    os.path.join('..', 'cfg', self.sysfile_name)):
                success = False
                QMessageBox.warning(
                    self, 'Error',
                    'System configuration with that name already exists!',
                    QMessageBox.Ok)

        if success:
            super().accept()

# ------------------------------------------------------------------------------

class SEMSettingsDlg(QDialog):
    """SEM beam settings dialog window to adjust target EHT and target beam
    current. The current actual beam settings and the current working distance
    and stigmation parameters are displayed.
    """
    def __init__(self, sem):
        super().__init__()
        self.sem = sem
        # Read actual values
        self.actual_eht = self.sem.get_eht()
        self.actual_beam_current = self.sem.get_beam_current()
        self.actual_aperture_size = self.sem.get_aperture_size()
        self.actual_high_current = self.sem.get_high_current()

        loadUi('..\\gui\\sem_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Display actual settings from SmartSEM
        self.doubleSpinBox_actualEHT.setValue(self.actual_eht)
        self.spinBox_actualBeamCurrent.setValue(self.actual_beam_current)
        self.spinBox_actualBeamSize.setValue(self.actual_aperture_size)
        self.checkBox_highCurrent.setEnabled(self.sem.HAS_HIGH_CURRENT)
        self.checkBox_highCurrent.setChecked(self.actual_high_current)
        # Update/disable appropriate GUI elements
        self.spinBox_beamCurrent.setEnabled(self.sem.BEAM_CURRENT_MODE == 'current')
        self.comboBox_beamSize.setEnabled(self.sem.BEAM_CURRENT_MODE != 'current')
        # Display current target settings
        self.doubleSpinBox_EHT.setValue(self.sem.target_eht)
        self.spinBox_beamCurrent.setValue(self.sem.target_beam_current)
        self.comboBox_beamSize.addItems(map(str, self.sem.APERTURE_SIZE))
        self.comboBox_beamSize.setCurrentText(str(self.sem.target_aperture_size))
        # Display current working distance and stigmation parameters
        self.lineEdit_currentFocus.setText(
            '{0:.6f}'.format(sem.get_wd() * 1000))
        self.lineEdit_currentStigX.setText('{0:.6f}'.format(sem.get_stig_x()))
        self.lineEdit_currentStigY.setText('{0:.6f}'.format(sem.get_stig_y()))

    def accept(self):
        self.target_eht = self.doubleSpinBox_EHT.value()
        if self.target_eht != self.actual_eht:
            self.sem.set_eht(self.target_eht)

        self.target_beam_current = self.spinBox_beamCurrent.value()
        if self.target_beam_current != self.actual_beam_current:
            self.sem.set_beam_current(self.target_beam_current)

        self.target_aperture_size = self.comboBox_beamSize.currentIndex()
        if self.target_aperture_size != self.actual_aperture_size:
            self.sem.set_aperture_size(self.target_aperture_size)

        self.target_high_current = self.checkBox_highCurrent.isChecked()
        if self.target_high_current != self.actual_high_current:
            self.sem.set_high_current(self.target_high_current)

        super().accept()

# ------------------------------------------------------------------------------

class MicrotomeSettingsDlg(QDialog):
    """Microtome settings dialog window to adjust stage motor limits and the
    wait interval after stage moves. Other settings are only displayed, but
    cannot be changed here.
    """

    def __init__(self, microtome, sem, stage, coordinate_system,
                 main_controls_trigger, microtome_active=True):
        super().__init__()
        self.microtome = microtome
        self.sem = sem
        self.stage = stage
        self.cs = coordinate_system
        self.main_controls_trigger = main_controls_trigger
        self.microtome_active = microtome_active
        loadUi('..\\gui\\microtome_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Labels and selection options depend on whether microtome stage or
        # SEM stage is used.
        if self.microtome_active:
            self.label_selectedStage.setText('Microtome stage active.')
            # Enabled motor status button (disabled by default)
            self.pushButton_showMotorStatus.setEnabled(True)
            self.pushButton_showMotorStatus.clicked.connect(
                self.open_motor_status_dlg)
            # Display those settings that can only be changed in DM
            self.lineEdit_knifeCutSpeed.setText(
                str(self.microtome.knife_cut_speed / 1000))
            self.lineEdit_knifeRetractSpeed.setText(
                str(self.microtome.knife_retract_speed / 1000))
            self.checkBox_useOscillation.setChecked(
                self.microtome.use_oscillation)
            # Settings changeable in SBEMimage
            self.doubleSpinBox_waitInterval.setValue(
                self.microtome.stage_move_wait_interval)
            current_motor_limits = self.microtome.stage_limits
            current_calibration = self.cs.stage_calibration
            speed_x, speed_y = (
                self.microtome.motor_speed_x, self.microtome.motor_speed_y)
            # Maintenance moves
            self.checkBox_enableMaintenanceMoves.setChecked(
                self.microtome.use_maintenance_moves)
            self.update_maintenance_move_interval_spinbox()
            self.checkBox_enableMaintenanceMoves.stateChanged.connect(
                self.update_maintenance_move_interval_spinbox)
            self.spinBox_maintenanceMoveInterval.setValue(
                self.microtome.maintenance_move_interval)
        else:
            self.label_selectedStage.setText('SEM stage active.')
            # Display stage limits. Not editable for SEM at the moment.
            self.spinBox_stageMaxX.setMaximum(200000)
            self.spinBox_stageMaxY.setMaximum(200000)
            self.spinBox_stageMinX.setMaximum(0)
            self.spinBox_stageMinY.setMaximum(0)
            self.spinBox_stageMinX.setEnabled(False)
            self.spinBox_stageMaxX.setEnabled(False)
            self.spinBox_stageMinY.setEnabled(False)
            self.spinBox_stageMaxY.setEnabled(False)
            current_motor_limits = self.sem.stage_limits
            current_calibration = self.cs.stage_calibration
            speed_x, speed_y = self.sem.motor_speed_x, self.sem.motor_speed_y
            self.doubleSpinBox_waitInterval.setValue(
                self.sem.stage_move_wait_interval)
            # Maintenance moves
            self.checkBox_enableMaintenanceMoves.setChecked(
                self.sem.use_maintenance_moves)
            self.update_maintenance_move_interval_spinbox()
            self.checkBox_enableMaintenanceMoves.stateChanged.connect(
                self.update_maintenance_move_interval_spinbox)
            self.spinBox_maintenanceMoveInterval.setValue(
                self.sem.maintenance_move_interval)

        # Push button to set the XYZ stage position
        self.pushButton_setStagePosition.clicked.connect(
            self.open_set_stage_position_dlg)
        self.spinBox_stageMinX.setValue(current_motor_limits[0])
        self.spinBox_stageMaxX.setValue(current_motor_limits[1])
        self.spinBox_stageMinY.setValue(current_motor_limits[2])
        self.spinBox_stageMaxY.setValue(current_motor_limits[3])
        # Show other relevant settings that can be changed in SBEMimage,
        # but in a different dialog (CalibrationDlg)
        self.lineEdit_scaleFactorX.setText(str(current_calibration[0]))
        self.lineEdit_scaleFactorY.setText(str(current_calibration[1]))
        self.lineEdit_rotationX.setText(str(current_calibration[2]))
        self.lineEdit_rotationY.setText(str(current_calibration[3]))
        # Motor speeds and tolerances
        # TODO: Make tolerances editable and update tolerances in DM script
        # from SBEMimage
        self.lineEdit_speedX.setText(str(speed_x))
        self.lineEdit_speedY.setText(str(speed_y))
        # Tolerances are stored in microns, but displayed in nm.
        self.spinBox_xyTolerance.setValue(
            int(self.microtome.xy_tolerance * 1000))
        self.spinBox_zTolerance.setValue(
            int(self.microtome.z_tolerance * 1000))

    def open_motor_status_dlg(self):
        dialog = MotorStatusDlg(self.microtome)
        dialog.exec_()

    def open_set_stage_position_dlg(self):
        dialog = SetStagePositionDlg(self.stage, self.main_controls_trigger)
        dialog.exec_()

    def update_maintenance_move_interval_spinbox(self):
        self.spinBox_maintenanceMoveInterval.setEnabled(
            self.checkBox_enableMaintenanceMoves.isChecked())

    def accept(self):
        if self.microtome_active:
            self.microtome.stage_move_wait_interval = (
                self.doubleSpinBox_waitInterval.value())
            self.microtome.stage_limits = [
                self.spinBox_stageMinX.value(), self.spinBox_stageMaxX.value(),
                self.spinBox_stageMinY.value(), self.spinBox_stageMaxY.value()]
            self.microtome.use_maintenance_moves = (
                self.checkBox_enableMaintenanceMoves.isChecked())
            self.microtome.maintenance_move_interval = (
                self.spinBox_maintenanceMoveInterval.value())
        else:
            self.sem.set_stage_move_wait_interval(
                self.doubleSpinBox_waitInterval.value())
            self.sem.use_maintenance_moves = (
                self.checkBox_enableMaintenanceMoves.isChecked())
            self.sem.maintenance_move_interval = (
                self.spinBox_maintenanceMoveInterval.value())

        super().accept()

# ------------------------------------------------------------------------------

class MotorStatusDlg(QDialog):
    """Show numbers of total motor moves, failed moves, and slow moves."""

    def __init__(self, stage):
        super().__init__()
        self.stage = stage
        loadUi('..\\gui\\motor_status_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_update.clicked.connect(self.show_current_stats)
        self.pushButton_reset.clicked.connect(self.reset_counters)
        self.show_current_stats()

    def reset_counters(self):
        reply = QMessageBox.warning(
            self, 'Reset all motor move counters',
            'This will reset all counters that keep track of the XYZ motor '
            'moves (total numbers, distances, durations). A reset should '
            'usually only be performed after the motors have been replaced. '
            'Are you sure you want to reset the counters?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if reply == QMessageBox.Cancel:
            return
        self.stage.reset_stage_move_counters()
        self.show_current_stats()

    def show_current_stats(self):
        x_total, y_total, z_total = self.stage.total_xyz_move_counter
        self.spinBox_xMotorTotal.setValue(x_total[0])
        self.spinBox_yMotorTotal.setValue(y_total[0])
        self.spinBox_zMotorTotal.setValue(z_total[0])
        x_failed, y_failed, z_failed = self.stage.failed_xyz_move_counter
        self.spinBox_xMotorFailed.setValue(x_failed)
        self.spinBox_yMotorFailed.setValue(y_failed)
        self.spinBox_zMotorFailed.setValue(z_failed)
        self.spinBox_xySlowMoveWarnings.setValue(
            self.stage.slow_xy_move_counter)
        recent_count_x = len(self.stage.failed_x_move_warnings)
        if recent_count_x == 0:
            recent_percentage_failed_x = 0
        else:
            recent_percentage_failed_x = (
                self.stage.failed_x_move_warnings.count(1) / recent_count_x)
        recent_count_y = len(self.stage.failed_y_move_warnings)
        if recent_count_y == 0:
            recent_percentage_failed_y = 0
        else:
            recent_percentage_failed_y = (
                self.stage.failed_y_move_warnings.count(1) / recent_count_y)
        recent_count_z = len(self.stage.failed_z_move_warnings)
        if recent_count_z == 0:
            recent_percentage_failed_z = 0
        else:
            recent_percentage_failed_z = (
                self.stage.failed_z_move_warnings.count(1) / recent_count_z)
        recent_count_slow = len(self.stage.slow_xy_move_warnings)
        if recent_count_slow == 0:
            recent_percentage_slow = 0
        else:
            recent_percentage_slow = (
                self.stage.slow_xy_move_warnings.count(1)
                / recent_count_slow)

        if x_total[0] == 0:
            total_percentage_failed_x = 0
        else:
            total_percentage_failed_x = x_failed/x_total[0]
        if y_total[0] == 0:
            total_percentage_failed_y = 0
        else:
            total_percentage_failed_y = y_failed/y_total[0]
        if z_total[0] == 0:
            total_percentage_failed_z = 0
        else:
            total_percentage_failed_z = z_failed/z_total[0]
        if min(x_total[0], y_total[0]) == 0:
            total_percentage_slow = 0
        else:
            total_percentage_slow = (
                self.stage.slow_xy_move_counter/min(x_total[0], y_total[0]))

        self.lineEdit_xRecentFailed.setText(
            f'{100 * total_percentage_failed_x:.5f} % failed / '
            f'{100 * recent_percentage_failed_x:.1f} % '
            f'in recent {recent_count_x}')
        self.lineEdit_yRecentFailed.setText(
            f'{100 * total_percentage_failed_y:.5f} % failed / '
            f'{100 * recent_percentage_failed_y:.1f} % '
            f'in recent {recent_count_y}')
        self.lineEdit_zRecentFailed.setText(
            f'{100 * total_percentage_failed_z:.5f} % failed / '
            f'{100 * recent_percentage_failed_z:.1f} % '
            f'in recent {recent_count_z}')
        self.lineEdit_xyRecentSlowMoveWarnings.setText(
            f'{100 * total_percentage_slow:.5f} % slow / '
            f'{100 * recent_percentage_slow:.1f} % '
            f'in recent {recent_count_slow}')

        if x_total[0] == 0:
            avg_dist_x = 0
            avg_duration_x = 0
        else:
            avg_dist_x = x_total[1]/x_total[0]
            avg_duration_x = x_total[2]/x_total[0]
        if y_total[0] == 0:
            avg_dist_y = 0
            avg_duration_y = 0
        else:
            avg_dist_y = y_total[1]/y_total[0]
            avg_duration_y = y_total[2]/y_total[0]
        if z_total[0] == 0:
            avg_dist_z = 0
        else:
            avg_dist_z = int(z_total[1]/z_total[0] * 1000)

        # Choose appropriate units for X and Y distance: in metres if >10m,
        # in mm if >10mm, otherwise in microns.
        if x_total[1] > 10000000:    # 10 m
            x_total_dist_str = f'{(x_total[1] / 1000000):.1f} m'
        elif x_total[1] > 10000:     # 10 mm
            x_total_dist_str = f'{(x_total[1] / 1000):.1f} mm'
        else:
            x_total_dist_str = f'{int(x_total[1])} µm'
        if y_total[1] > 10000000:    # 10 m
            y_total_dist_str = f'{(y_total[1] / 1000000):.1f} m'
        elif y_total[1] > 10000:     # 10 mm
            y_total_dist_str = f'{(y_total[1] / 1000):.1f} mm'
        else:
            y_total_dist_str = f'{int(y_total[1])} µm'
        # For Z distance, use mm if >10mm
        if z_total[1] > 10000:
            z_total_dist_str = f'{(z_total[1] / 1000):.3f} mm'
        else:
            z_total_dist_str = f'{z_total[1]:.3f} µm'

        self.lineEdit_xDistance.setText(
            f'{x_total_dist_str}; avg./move: {avg_dist_x:.1f} µm')
        self.lineEdit_yDistance.setText(
            f'{y_total_dist_str}; avg./move: {avg_dist_y:.1f} µm')
        self.lineEdit_zDistance.setText(
            f'{z_total_dist_str}; avg./move: {avg_dist_z} nm')

        # Choose appropriate units for X and Y total move durations:
        # In hours and minutes if >600 s (10 min), otherwise in seconds
        if x_total[2] > 600:
            hours, minutes = utils.get_hours_minutes(x_total[2])
            x_total_dur_str = f'{hours} h {minutes} min'
        else:
            x_total_dur_str = f'{x_total[2]:.1f} s'
        if y_total[2] > 600:
            hours, minutes = utils.get_hours_minutes(y_total[2])
            y_total_dur_str = f'{hours} h {minutes} min'
        else:
            y_total_dur_str = f'{y_total[2]:.1f} s'

        self.lineEdit_xDuration.setText(
            f'{x_total_dur_str}; avg./move: {avg_duration_x:.2f} s')
        self.lineEdit_yDuration.setText(
            f'{y_total_dur_str}; avg./move: {avg_duration_y:.2f} s')

        self.doubleSpinBox_motorSpeedX.setValue(self.stage.motor_speed_x)
        self.doubleSpinBox_motorSpeedY.setValue(self.stage.motor_speed_y)

        self.spinBox_xyTolerance.setValue(
            int(self.stage.xy_tolerance * 1000))  # show in microns (* 1000)
        self.spinBox_zTolerance.setValue(
            int(self.stage.z_tolerance * 1000))

# ------------------------------------------------------------------------------

class SetStagePositionDlg(QDialog):
    """Set stage position to XYZ coordinates selected by user."""

    def __init__(self, stage, main_controls_trigger):
        super().__init__()
        self.stage = stage
        loadUi('..\\gui\\set_stage_position_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        QApplication.processEvents()
        self.busy = False
        self.main_controls_trigger = main_controls_trigger
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.move_completed)
        self.pushButton_move.clicked.connect(self.start_move)
        # Show current XYZ
        self.doubleSpinBox_X.setValue(self.stage.last_known_x)
        self.doubleSpinBox_Y.setValue(self.stage.last_known_y)
        # Read current Z
        self.last_known_z = self.stage.get_z()
        self.doubleSpinBox_Z.setValue(self.last_known_z)

    def start_move(self):
        self.busy = True
        self.error = False
        self.aborted = False
        # Load target coordinates
        stage_x = self.doubleSpinBox_X.value()
        stage_y = self.doubleSpinBox_Y.value()
        stage_z = self.doubleSpinBox_Z.value()
        # User must confirm if Z move larger than 200 nanometres
        z_diff = abs(stage_z - self.last_known_z)
        response = None
        if z_diff > 0.200:
            response = QMessageBox.warning(
                self, 'Confirm Z move',
                f'This will move Z by {z_diff:.3f} µm. Please confirm!',
                QMessageBox.Ok | QMessageBox.Cancel)
        if response == QMessageBox.Cancel:
            self.aborted = True
            self.move_completed()
        else:
            self.pushButton_move.setText('Busy... please wait.')
            self.pushButton_move.setEnabled(False)
            utils.run_log_thread(self.move_to_position,
                                 stage_x, stage_y, stage_z)

    def move_to_position(self, stage_x, stage_y, stage_z):
        self.stage.move_to_xy((stage_x, stage_y))
        if self.stage.error_state != Error.none:
            self.error = True
            self.stage.reset_error_state()
        else:
            self.stage.move_to_z(stage_z, safe_mode=False)
            if self.stage.error_state != Error.none:
                self.error = True
                self.stage.reset_error_state()
        self.finish_trigger.signal.emit()

    def move_completed(self):
        self.busy = False
        # Update Main Controls position display and Viewport
        self.main_controls_trigger.transmit('UPDATE XY')
        self.main_controls_trigger.transmit('UPDATE Z')
        self.main_controls_trigger.transmit('DRAW VP')
        if self.error:
            QMessageBox.warning(self, 'Error',
                'An error was detected during the move. '
                'Please try again.',
                QMessageBox.Ok)
        elif self.aborted:
            QMessageBox.warning(self, 'Aborted',
                'The move was aborted.',
                QMessageBox.Ok)
        else:
            QMessageBox.information(self, 'Move complete',
                'The stage has been moved to the selected position. ',
                QMessageBox.Ok)
        # Close the dialog
        super().accept()

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if not self.busy:
            event.accept()
        else:
            event.ignore()

# ------------------------------------------------------------------------------

class KatanaSettingsDlg(QDialog):
    """Adjust settings for the katana microtome.
    (Under development)
    """

    def __init__(self, microtome):
        super().__init__()
        self.microtome = microtome
        loadUi('..\\gui\\katana_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()

        # Set up COM port selector
        self.comboBox_portSelector.addItems(utils.get_serial_ports())
        self.comboBox_portSelector.setCurrentIndex(0)
        self.comboBox_portSelector.currentIndexChanged.connect(
            self.reconnect)

        self.display_connection_status()
        self.display_current_settings()

    def reconnect(self):
        pass

    def display_connection_status(self):
        # Show message in dialog whether or not katana is connected.
        pal = QPalette(self.label_connectionStatus.palette())
        if self.microtome.connected:
            # Use red colour if not connected
            pal.setColor(QPalette.WindowText, QColor(Qt.black))
            self.label_connectionStatus.setPalette(pal)
            self.label_connectionStatus.setText('katana microtome connected.')
        else:
            pal.setColor(QPalette.WindowText, QColor(Qt.red))
            self.label_connectionStatus.setPalette(pal)
            self.label_connectionStatus.setText(
                'katana microtome is not connected.')

    def display_current_settings(self):
        self.spinBox_knifeCutSpeed.setValue(
            self.microtome.knife_cut_speed)
        self.spinBox_knifeFastSpeed.setValue(
            self.microtome.knife_fast_speed)
        cut_window_start, cut_window_end = (
            self.microtome.cut_window_start, self.microtome.cut_window_end)
        self.spinBox_cutWindowStart.setValue(cut_window_start)
        self.spinBox_cutWindowEnd.setValue(cut_window_end)

        self.checkBox_useOscillation.setChecked(
            self.microtome.use_oscillation)
        self.spinBox_oscAmplitude.setValue(
            self.microtome.oscillation_amplitude)
        self.spinBox_oscFrequency.setValue(
            self.microtome.oscillation_frequency)
        if not self.microtome.simulation_mode and self.microtome.connected:
            self.doubleSpinBox_zPosition.setValue(self.microtome.get_stage_z())
        z_range_min, z_range_max = self.microtome.z_range
        self.doubleSpinBox_zRangeMin.setValue(z_range_min)
        self.doubleSpinBox_zRangeMax.setValue(z_range_max)
        # Retraction clearance is stored in nanometres, display in micrometres
        self.doubleSpinBox_retractClearance.setValue(
            self.microtome.retract_clearance / 1000)

    def accept(self):
        new_cut_speed = self.spinBox_knifeCutSpeed.value()
        new_fast_speed = self.spinBox_knifeFastSpeed.value()
        new_cut_start = self.spinBox_cutWindowStart.value()
        new_cut_end = self.spinBox_cutWindowEnd.value()
        new_osc_frequency = self.spinBox_oscFrequency.value()
        new_osc_amplitude = self.spinBox_oscAmplitude.value()
        # retract_clearance in nanometres
        new_retract_clearance = (
            self.doubleSpinBox_retractClearance.value() * 1000)
        # End position of cut window must be smaller than start position:
        if new_cut_end < new_cut_start:
            self.microtome.knife_cut_speed = new_cut_speed
            self.microtome.knife_fast_speed = new_fast_speed
            self.microtome.cut_window_start = new_cut_start
            self.microtome.cut_window_end = new_cut_end
            self.microtome.use_oscillation = (
                self.checkBox_useOscillation.isChecked())
            self.microtome.oscillation_frequency = new_osc_frequency
            self.microtome.oscillation_amplitude = new_osc_amplitude
            self.microtome.retract_clearance = new_retract_clearance
            super().accept()
        else:
            QMessageBox.warning(
                self, 'Invalid input',
                'The start position of the cutting window must be larger '
                'than the end position.',
                QMessageBox.Ok)

# ------------------------------------------------------------------------------


class GCIBSettingsDlg(QDialog):
    """[WIP] Settings dialog for the GCIB system. Currently not more than a placeholder.
    """
    def __init__(self, microtome):
        super().__init__()
        self.microtome = microtome

        loadUi('..\\gui\\gcib_settings_dlg.ui', self)

        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()

        # Set up COM port selector
        # TODO: set up serial selector
        # self.comboBox_portSelector.addItems(utils.get_serial_ports())
        # self.comboBox_portSelector.setCurrentIndex(0)
        # self.comboBox_portSelector.currentIndexChanged.connect(
        #     self.reconnect)

        self.display_connection_status()
        self.display_current_settings()
        self.doubleSpinBox_millCycle.setValue(self.microtome.mill_cycle)
        self.checkBox_useContinuousRotation.setChecked(bool(self.microtome.continuous_rot))

    def reconnect(self):
        pass

    def display_connection_status(self):
        pass
        # pal = QPalette(self.label_connectionStatus.palette())
        # if self.microtome.connected:
        #     # Use red colour if not connected
        #     pal.setColor(QPalette.WindowText, QColor(Qt.black))
        #     self.label_connectionStatus.setPalette(pal)
        #     self.label_connectionStatus.setText('katana microtome connected.')
        # else:
        #     pal.setColor(QPalette.WindowText, QColor(Qt.red))
        #     self.label_connectionStatus.setPalette(pal)
        #     self.label_connectionStatus.setText(
        #         'katana microtome is not connected.')

    def display_current_settings(self):
        # TODO: add parameters from config (non-adjustable for now)
        pass

    def accept(self):
        self.microtome.mill_cycle = self.doubleSpinBox_millCycle.value()
        self.microtome.continuous_rot = int(self.checkBox_useContinuousRotation.isChecked())
        super().accept()

# ------------------------------------------------------------------------------


class StageCalibrationDlg(QDialog):
    """Dialog window to calibrate the stage (rotation angles and scale factors)
    and the motor speeds.

    The stage can be calibrated manually by providing shift vectors obtained
    from image comparisons, or with an automated procedure.
    To determine the (microtome) motor speeds, the user needs to run a
    script in Digital Micrograph. TODO: develop automated procedure to update
    motor speeds.
    """

    def __init__(self, coordinate_system, stage, sem, base_dir):
        super().__init__()
        self.cs = coordinate_system
        self.stage = stage
        self.sem = sem
        self.base_dir = base_dir

        self.x_shift_vector = [0, 0]
        self.y_shift_vector = [0, 0]
        self.motor_speed_x, self.motor_speed_y = None, None
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.process_pixel_shifts)
        self.finish_trigger_motor_speeds = utils.Trigger()
        self.finish_trigger_motor_speeds.signal.connect(
            self.show_measured_motor_speeds)
        self.update_calc_trigger = utils.Trigger()
        self.update_calc_trigger.signal.connect(self.update_log)
        self.calc_exception = None
        self.busy = False

        loadUi('..\\gui\\stage_calibration_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.arrow_symbol1.setPixmap(QPixmap('..\\img\\arrow.png'))
        self.arrow_symbol2.setPixmap(QPixmap('..\\img\\arrow.png'))
        self.lineEdit_EHT.setText('{0:.2f}'.format(self.sem.target_eht))
        params = self.cs.stage_calibration
        self.doubleSpinBox_stageScaleFactorX.setValue(params[0])
        self.doubleSpinBox_stageScaleFactorY.setValue(params[1])
        self.doubleSpinBox_stageRotationX.setValue(params[2])
        self.doubleSpinBox_stageRotationY.setValue(params[3])
        self.doubleSpinBox_motorSpeedX.setValue(self.stage.motor_speed_x)
        self.doubleSpinBox_motorSpeedY.setValue(self.stage.motor_speed_y)
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        self.comboBox_dwellTime.setCurrentIndex(4)
        # TODO: use a list instead:
        self.comboBox_package.addItems(['cv2', 'imreg_dft', 'skimage'])
        self.pushButton_startImageAcq.clicked.connect(
            self.start_stage_calibration_procedure)
        if self.sem.simulation_mode:
            self.pushButton_startImageAcq.setEnabled(False)
        self.pushButton_helpCalibration.clicked.connect(self.show_help)
        self.pushButton_calcStage.clicked.connect(
            self.calculate_calibration_parameters_from_user_input)
        self.pushButton_measureMotorSpeeds.clicked.connect(
            self.measure_motor_speeds)

    def measure_motor_speeds(self):
        """Run the measurement routine in a thread."""
        self.busy = True  # This prevents user from closing the dialog window
        self.pushButton_measureMotorSpeeds.setEnabled(False)
        self.pushButton_startImageAcq.setEnabled(False)
        self.pushButton_measureMotorSpeeds.setText('Please wait... (~1 min)')
        utils.run_log_thread(self.run_motor_speed_measurement)

    def run_motor_speed_measurement(self):
        self.motor_speed_x, self.motor_speed_y = (
            self.stage.measure_motor_speeds())
        self.finish_trigger_motor_speeds.signal.emit()

    def show_measured_motor_speeds(self):
        self.busy = False
        self.pushButton_measureMotorSpeeds.setEnabled(True)
        self.pushButton_startImageAcq.setEnabled(True)
        self.pushButton_measureMotorSpeeds.setText('Measure XY motor speeds')
        if self.motor_speed_x is None or self.stage.error_state != Error.none:
            self.stage.reset_error_state()
            QMessageBox.warning(self, 'Error',
                                'XY motor speed measurement failed.',
                                QMessageBox.Ok)
            return
        user_choice = QMessageBox.information(
            self, 'Measured XY motor speeds',
            'Results:\nMotor speed X: ' + '{0:.1f}'.format(self.motor_speed_x)
            + ';\nMotor speed Y: ' + '{0:.1f}'.format(self.motor_speed_y)
            + '\n\nDo you want to use these values?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_choice == QMessageBox.Ok:
            self.doubleSpinBox_motorSpeedX.setValue(self.motor_speed_x)
            self.doubleSpinBox_motorSpeedY.setValue(self.motor_speed_y)

    def show_help(self):
        QMessageBox.information(
            self, 'Stage calibration procedure',
            'If you click on "Start automatic calibration", '
            'three images will be acquired and saved in the current base '
            'directory: start.tif, shift_x.tif, shift_y.tif. '
            'You can set the pixel size and dwell time for these images and '
            'specify how far the stage should move along the X and the Y axis. '
            'The X/Y moves must be small enough to allow some overlap between '
            'the test images. The frame size is set automatically. '
            'Make sure that structure is visible in the images, and that the '
            'beam is focused.\n'
            'The current stage position will be used as the starting '
            'position. The recommended starting position is the centre of the '
            'stage (0, 0).\n'
            'Shift vectors between the acquired images will be computed using '
            'a function from the selected package (cv2, imreg_dft or skimage). '
            'Angles and scale factors will then be computed from these '
            'shifts.\n\n'
            'Alternatively, you can manually provide the pixel shifts by '
            'looking at the calibration images start.tif, shift_x.tif, and '
            'shift_y.tif and measuring the difference (with ImageJ, for '
            'example) in the XY pixel position for some feature in the image. '
            'Click on "Calculate" to calculate the calibration parameters '
            'from these shifts.',
            QMessageBox.Ok)

    def start_stage_calibration_procedure(self):
        """Acquire three images to be used for the stage calibration.
        See text in information message box for explanation.
        """
        if not self.sem.is_eht_on():
            QMessageBox.warning(
                self, 'EHT off', 'EHT / high voltage is off. Please turn '
                'it on before starting the calibration.', QMessageBox.Ok)
            return
        reply = QMessageBox.information(
            self, 'Start calibration procedure',
            'This will acquire three images and save them in the current base '
            'directory: start.tif, shift_x.tif, shift_y.tif. '
            'Structure must be visible in the images, and the beam must be '
            'focused.\nThe current stage position will be used as the starting '
            'position. The recommended starting position is the centre of the '
            'stage (0, 0). Angles and scale factors will be computed from the '
            'shifts between the acquired test images.\n'
            'Proceed?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if reply == QMessageBox.Ok:
            self.busy = True
            self.plainTextEdit_calibLog.setPlainText('Acquiring images...')
            self.pushButton_startImageAcq.setText('Busy')
            self.pushButton_startImageAcq.setEnabled(False)
            self.pushButton_measureMotorSpeeds.setEnabled(False)
            self.pushButton_calcStage.setEnabled(False)
            # Acquire images in thread
            utils.run_log_thread(self.calibration_images_acq_thread)

    def calibration_images_acq_thread(self):
        """Acquisition thread for three images used for the stage calibration.
        Frame settings are fixed for now. Currently no error handling. XY shifts
        are computed from images with imreg_dft or skimage.
        """
        shift = self.spinBox_shift.value()
        pixel_size = self.spinBox_pixelsize.value()
        dwell_time = self.sem.DWELL_TIME[self.comboBox_dwellTime.currentIndex()]
        # Use frame size 4 if available, otherwise 3
        if len(self.sem.STORE_RES) > 4:
            frame_size_selector = 4
        else:
            frame_size_selector = 3

        self.sem.apply_frame_settings(
            frame_size_selector, pixel_size, dwell_time)

        start_x, start_y = self.stage.get_xy()
        # Acquire first image at starting position
        self.sem.acquire_frame(self.base_dir + '\\start.tif')
        # Shift along X stage
        self.stage.move_to_xy((start_x + shift, start_y))
        # Second image, at new X position (Y unchanged from starting position)
        self.sem.acquire_frame(self.base_dir + '\\shift_x.tif')
        # Shift along Y direction, X back to starting position
        self.stage.move_to_xy((start_x, start_y + shift))
        # Acquire third and final image, at new Y position
        self.sem.acquire_frame(self.base_dir + '\\shift_y.tif')
        # Move back to starting position
        self.stage.move_to_xy((start_x, start_y))
        # Show in log that calculation begins now
        self.update_calc_trigger.signal.emit()
        # Load images and calculate shifts:
        start_img = imread(os.path.join(self.base_dir, 'start.tif'), 1)
        shift_x_img = imread(os.path.join(self.base_dir, 'shift_x.tif'), 1)
        shift_y_img = imread(os.path.join(self.base_dir, 'shift_y.tif'), 1)
        self.calc_exception = None
        try:
            # # [::-1] to use x, y, z order
            if self.comboBox_package.currentIndex() == 0:  # cv2 calculation selected
                start_img = (start_img*255).astype(np.uint8)
                shift_x_img = (shift_x_img*255).astype(np.uint8)
                shift_y_img = (shift_y_img*255).astype(np.uint8)
                x_shift = utils.align_images_cv2(shift_x_img, start_img)
                y_shift = utils.align_images_cv2(shift_y_img, start_img)
            elif self.comboBox_package.currentIndex() == 1:
                x_shift = translation(
                    start_img, shift_x_img, filter_pcorr=3)['tvec'][::-1]
                y_shift = translation(
                    start_img, shift_y_img, filter_pcorr=3)['tvec'][::-1]
            else:  # use skimage.register_translation
                x_shift = register_translation(start_img, shift_x_img)[0][::-1]
                y_shift = register_translation(start_img, shift_y_img)[0][::-1]
            x_shift = x_shift.astype(np.int)
            y_shift = y_shift.astype(np.int)
            self.x_shift_vector = [x_shift[0], x_shift[1]]
            self.y_shift_vector = [y_shift[0], y_shift[1]]
        except Exception as e:
            self.calc_exception = str(e)
        self.finish_trigger.signal.emit()

    def update_log(self):
        self.plainTextEdit_calibLog.appendPlainText(
            'Now computing pixel shifts...')

    def process_pixel_shifts(self):
        """Show the pixel shifts computed from the calibration images, and
        calculate the calibration parameters from these shifts.
        """
        self.pushButton_startImageAcq.setText('Start')
        self.pushButton_startImageAcq.setEnabled(True)
        self.pushButton_measureMotorSpeeds.setEnabled(True)
        self.pushButton_calcStage.setEnabled(True)
        if self.calc_exception is None:
            # Show the vectors in the textbox and the spinboxes
            self.plainTextEdit_calibLog.setPlainText(
                'Shift_X: [{0:.1f}, {1:.1f}], '
                'Shift_Y: [{2:.1f}, {3:.1f}]'.format(
                *self.x_shift_vector, *self.y_shift_vector))
            # Absolute values for the GUI
            if self.comboBox_package.currentIndex() == 2:
                self.spinBox_x2x.setValue(abs(self.x_shift_vector[0]))
                self.spinBox_x2y.setValue(abs(self.x_shift_vector[1]))
                self.spinBox_y2x.setValue(abs(self.y_shift_vector[0]))
                self.spinBox_y2y.setValue(abs(self.y_shift_vector[1]))
            else:
                self.spinBox_x2x.setValue(self.x_shift_vector[0])
                self.spinBox_x2y.setValue(self.x_shift_vector[1])
                self.spinBox_y2x.setValue(self.y_shift_vector[0])
                self.spinBox_y2y.setValue(self.y_shift_vector[1])

            # Now calculate parameters:
            self.calculate_calibration_parameters()
        else:
            QMessageBox.warning(
                self, 'Error',
                'An exception occured while computing the translations: '
                + self.calc_exception,
                QMessageBox.Ok)
            self.busy = False

    def calculate_calibration_parameters(self):
        """Calculate the calibration parameters (angles and scale factors) from
        the current shift vectors.
        """
        shift = self.spinBox_shift.value()
        pixel_size = self.spinBox_pixelsize.value()

        # Use absolute values for now, TODO: revisit for the Sigma stage
        delta_xx, delta_xy = (
            abs(self.x_shift_vector[0]), abs(self.x_shift_vector[1]))
        delta_yx, delta_yy = (
            abs(self.y_shift_vector[0]), abs(self.y_shift_vector[1]))
        # Rotation angles (in radians)
        rot_x = atan(delta_xy/delta_xx)
        rot_y = atan(delta_yx/delta_yy)
        # Scale factors
        scale_x = shift / (sqrt(delta_xx**2 + delta_xy**2) * pixel_size / 1000)
        scale_y = shift / (sqrt(delta_yx**2 + delta_yy**2) * pixel_size / 1000)

        # Alternative calc.
        x_abs = np.linalg.norm(self.x_shift_vector)
        y_abs = np.linalg.norm(self.y_shift_vector)
        # Rotation angles:
        rot_x_alt = np.arccos(self.x_shift_vector[0] / x_abs)
        rot_y_alt = np.arccos(self.y_shift_vector[1] / y_abs)
        # Scale factors:
        scale_x_alt = shift / (x_abs * pixel_size / 1000)
        scale_y_alt = shift / (y_abs * pixel_size / 1000)

        # Alternative calc. with atan2
        # This only works if the reference vector is (0, 0)
        rot2_x = atan2(self.x_shift_vector[1], self.x_shift_vector[0])
        rot2_y = atan2(self.y_shift_vector[0], self.y_shift_vector[1])

        scale_x = scale_x_alt
        scale_y = scale_y_alt
        rot_x = rot_x_alt
        rot_y = rot_y_alt

        self.busy = False
        user_choice = QMessageBox.information(
            self, 'Calculated parameters',
            'Results:\n'
            + 'Scale factor X: ' + '{0:.5f}'.format(scale_x)
            + ';\nScale factor Y: ' + '{0:.5f}'.format(scale_y)
            + '\nRotation X: ' + '{0:.5f}'.format(rot_x)
            + ';\nRotation Y: ' + '{0:.5f}'.format(rot_y)
            + '\n\nDo you want to use these values?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_choice == QMessageBox.Ok:
            self.doubleSpinBox_stageScaleFactorX.setValue(scale_x)
            self.doubleSpinBox_stageScaleFactorY.setValue(scale_y)
            self.doubleSpinBox_stageRotationX.setValue(rot_x)
            self.doubleSpinBox_stageRotationY.setValue(rot_y)

    def calculate_calibration_parameters_from_user_input(self):
        """Calculate the rotation angles and scale factors from the user input.
        The user provides the pixel position of any object that can be
        identified in all three acquired test images. From this, the program
        calculates the difference the object was shifted in pixels, and the
        angle with respect to the x or y axis.
        """
        # Pixel position input from GUI
        x1x = self.spinBox_x1x.value()
        x1y = self.spinBox_x1y.value()
        x2x = self.spinBox_x2x.value()
        x2y = self.spinBox_x2y.value()
        y1x = self.spinBox_y1x.value()
        y1y = self.spinBox_y1y.value()
        y2x = self.spinBox_y2x.value()
        y2y = self.spinBox_y2y.value()

        # Distances in pixels
        delta_xx = x2x - x1x
        delta_xy = x2y - x1y
        delta_yx = y2x - y1x
        delta_yy = y2y - y1y
        if delta_xx == 0 or delta_yy == 0:
            QMessageBox.warning(
                self, 'Error computing stage calibration',
                'Please check your input values.',
                QMessageBox.Ok)
        else:
            self.plainTextEdit_calibLog.setPlainText(
                'Using pixel shifts specified on the right side as input...')
            self.x_shift_vector = [delta_xx, delta_xy]
            self.y_shift_vector = [delta_yx, delta_yy]
            self.calculate_calibration_parameters()

    def accept(self):
        if not self.busy:
            stage_params = [
                self.doubleSpinBox_stageScaleFactorX.value(),
                self.doubleSpinBox_stageScaleFactorY.value(),
                self.doubleSpinBox_stageRotationX.value(),
                self.doubleSpinBox_stageRotationY.value()]
            # Save and apply new stage calibration and motor speeds
            self.cs.save_stage_calibration(self.sem.target_eht, stage_params)
            self.cs.apply_stage_calibration()
            success = self.stage.set_motor_speeds(
                self.doubleSpinBox_motorSpeedX.value(),
                self.doubleSpinBox_motorSpeedY.value())

            if not success:
                QMessageBox.warning(
                    self, 'Error updating motor speeds',
                    'Motor speeds could not be updated.',
                    QMessageBox.Ok)
            super().accept()

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if not self.busy:
            event.accept()
        else:
            event.ignore()

# ------------------------------------------------------------------------------

class MagCalibrationDlg(QDialog):
    """Calibrate the relationship between magnification and pixel size."""

    def __init__(self, sem):
        super().__init__()
        self.sem = sem
        loadUi('..\\gui\\mag_calibration_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.spinBox_calibrationFactor.setValue(
            self.sem.MAG_PX_SIZE_FACTOR)
        self.comboBox_frameWidth.addItems(['2048', '4096'])
        self.comboBox_frameWidth.setCurrentIndex(1)
        self.pushButton_calculate.clicked.connect(
            self.calculate_calibration_factor)

    def calculate_calibration_factor(self):
        """Calculate the mag calibration factor from the frame width, the
        magnification and the pixel size.
        """
        frame_width = int(str(self.comboBox_frameWidth.currentText()))
        pixel_size = self.doubleSpinBox_pixelSize.value()
        mag = self.spinBox_mag.value()
        new_factor = mag * frame_width * pixel_size
        user_choice = QMessageBox.information(
            self, 'Calculated calibration factor',
            'Result:\nNew magnification calibration factor: %d '
            '\n\nDo you want to use this value?' % new_factor,
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_choice == QMessageBox.Ok:
            self.spinBox_calibrationFactor.setValue(new_factor)

    def accept(self):
        self.sem.MAG_PX_SIZE_FACTOR = self.spinBox_calibrationFactor.value()
        super().accept()

# ------------------------------------------------------------------------------

class CutDurationDlg(QDialog):
    """Dialog to set the duration in seconds of a full cut cycle (near, cut,
    clear).
    """

    def __init__(self, microtome):
        super().__init__()
        self.microtome = microtome
        loadUi('..\\gui\\cut_duration_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.doubleSpinBox_cutDuration.setValue(
            self.microtome.full_cut_duration)

    def accept(self):
        self.microtome.full_cut_duration = (
            self.doubleSpinBox_cutDuration.value())
        super().accept()

# ------------------------------------------------------------------------------

class OVSettingsDlg(QDialog):
    """Dialog window to adjust settings for overview images, and to add/delete
    overview images.
    """

    def __init__(self, ovm, sem, current_ov, main_controls_trigger):
        super().__init__()
        self.ovm = ovm
        self.sem = sem
        self.current_ov = current_ov
        self.main_controls_trigger = main_controls_trigger
        loadUi('..\\gui\\overview_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Set up OV selector
        self.comboBox_OVSelector.addItems(self.ovm.ov_selector_list())
        self.comboBox_OVSelector.setCurrentIndex(self.current_ov)
        self.comboBox_OVSelector.currentIndexChanged.connect(self.change_ov)
        if self.ovm[self.current_ov].active:
            self.radioButton_active.setChecked(True)
        else:
            self.radioButton_inactive.setChecked(True)
        self.radioButton_active.toggled.connect(self.update_active_status)
        self.update_active_status()
        # Set up other comboboxes
        store_res_list = [
            '%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_frameSize.addItems(store_res_list)
        self.comboBox_frameSize.currentIndexChanged.connect(
            self.update_pixel_size)
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        # Update pixel size when mag changed
        self.spinBox_magnification.valueChanged.connect(self.update_pixel_size)
        # Button to clear OV image in Viewport
        self.pushButton_clearViewportImage.clicked.connect(
            self.clear_viewport_image)
        # Save, add and delete buttons
        self.pushButton_save.clicked.connect(self.save_current_settings)
        self.pushButton_addOV.clicked.connect(self.add_ov)
        self.pushButton_deleteOV.clicked.connect(self.delete_ov)
        self.update_buttons()
        self.show_current_settings()
        self.show_frame_size()

    def update_active_status(self):
        # If current OV is inactive, disable GUI elements
        b = self.radioButton_active.isChecked()
        self.comboBox_frameSize.setEnabled(b)
        self.spinBox_magnification.setEnabled(b)
        self.comboBox_dwellTime.setEnabled(b)
        self.spinBox_acqInterval.setEnabled(b)
        self.spinBox_acqIntervalOffset.setEnabled(b)

    def show_current_settings(self):
        self.comboBox_frameSize.setCurrentIndex(
            self.ovm[self.current_ov].frame_size_selector)
        self.spinBox_magnification.setValue(
            self.ovm[self.current_ov].magnification)
        self.doubleSpinBox_pixelSize.setValue(
            self.ovm[self.current_ov].pixel_size)
        self.comboBox_dwellTime.setCurrentIndex(
            self.ovm[self.current_ov].dwell_time_selector)
        self.spinBox_acqInterval.setValue(
            self.ovm[self.current_ov].acq_interval)
        self.spinBox_acqIntervalOffset.setValue(
            self.ovm[self.current_ov].acq_interval_offset)

    def update_pixel_size(self):
        """Calculate pixel size from current magnification and display it."""
        pixel_size = (
            self.sem.MAG_PX_SIZE_FACTOR
            / (self.sem.STORE_RES[self.comboBox_frameSize.currentIndex()][0]
            * self.spinBox_magnification.value()))
        self.doubleSpinBox_pixelSize.setValue(pixel_size)

    def show_frame_size(self):
        """Calculate and show frame size depending on user selection."""
        frame_size_selector = self.ovm[self.current_ov].frame_size_selector
        pixel_size = self.ovm[self.current_ov].pixel_size
        width = self.sem.STORE_RES[frame_size_selector][0] * pixel_size / 1000
        height = self.sem.STORE_RES[frame_size_selector][1] * pixel_size / 1000
        self.label_frameSize.setText('{0:.1f} × '.format(width)
                                    + '{0:.1f}'.format(height))

    def change_ov(self):
        self.current_ov = self.comboBox_OVSelector.currentIndex()
        if self.ovm[self.current_ov].active:
            self.radioButton_active.setChecked(True)
        else:
            self.radioButton_inactive.setChecked(True)
        self.update_active_status()
        self.update_buttons()
        self.show_current_settings()

    def update_buttons(self):
        """Update labels on buttons and disable/enable delete button depending
        on which OV is selected. OV 0 cannot be deleted. Only the last OV (with
        the highest index) can be deleted. Reason: preserve identities of
        overviews during stack acq.
        """
        if self.current_ov == 0:
            self.pushButton_deleteOV.setEnabled(False)
        else:
            self.pushButton_deleteOV.setEnabled(
                self.current_ov == self.ovm.number_ov - 1)
        # Show current OV number on delete and save buttons
        self.pushButton_save.setText(
            'Save settings for OV %d' % self.current_ov)
        self.pushButton_deleteOV.setText('Delete OV %d' % self.current_ov)

    def clear_viewport_image(self):
        self.ovm[self.current_ov].vp_file_path = ''
        self.main_controls_trigger.transmit('OV SETTINGS CHANGED')

    def save_current_settings(self):
        self.ovm[self.current_ov].active = self.radioButton_active.isChecked()
        # Save previous values of frame size and magnification. If the new
        # values are different from the previous ones, reset current OV image
        # shown in Viewport.
        self.prev_frame_size = self.ovm[self.current_ov].frame_size_selector
        self.prev_mag = self.ovm[self.current_ov].magnification
        self.ovm[self.current_ov].frame_size_selector = (
            self.comboBox_frameSize.currentIndex())
        self.ovm[self.current_ov].magnification = (
            self.spinBox_magnification.value())
        self.ovm[self.current_ov].dwell_time_selector = (
            self.comboBox_dwellTime.currentIndex())
        self.ovm[self.current_ov].acq_interval = (
            self.spinBox_acqInterval.value())
        self.ovm[self.current_ov].acq_interval_offset = (
            self.spinBox_acqIntervalOffset.value())
        if ((self.comboBox_frameSize.currentIndex() != self.prev_frame_size)
            or (self.spinBox_magnification.value() != self.prev_mag)):
            # Reset path to current overview image in Viewport
            self.ovm[self.current_ov].vp_file_path = ''
        self.main_controls_trigger.transmit('OV SETTINGS CHANGED')

    def add_ov(self):
        frame_size_selector = self.comboBox_frameSize.currentIndex()
        frame_size = self.comboBox_frameSize.currentText()
        pixel_size = self.doubleSpinBox_pixelSize.value()
        dwell_time_selector = self.comboBox_dwellTime.currentIndex()
        dwell_time = self.comboBox_dwellTime.currentText()
        acq_interval = self.spinBox_acqInterval.value()
        acq_interval_offset = self.spinBox_acqIntervalOffset.value()
        self.ovm.add_new_overview(frame_size=frame_size, frame_size_selector=frame_size_selector, pixel_size=pixel_size,
                                  dwell_time_selector=dwell_time_selector, dwell_time=dwell_time,
                                  acq_interval=acq_interval, acq_interval_offset=acq_interval_offset)
        self.current_ov = self.ovm.number_ov - 1
        # Update OV selector:
        self.comboBox_OVSelector.blockSignals(True)
        self.comboBox_OVSelector.clear()
        self.comboBox_OVSelector.addItems(self.ovm.ov_selector_list())
        self.comboBox_OVSelector.setCurrentIndex(self.current_ov)
        self.comboBox_OVSelector.blockSignals(False)
        self.change_ov()
        self.main_controls_trigger.transmit('OV SETTINGS CHANGED')

    def delete_ov(self):
        self.ovm.delete_overview()
        self.current_ov = self.ovm.number_ov - 1
        # Update OV selector:
        self.comboBox_OVSelector.blockSignals(True)
        self.comboBox_OVSelector.clear()
        self.comboBox_OVSelector.addItems(self.ovm.ov_selector_list())
        self.comboBox_OVSelector.setCurrentIndex(self.current_ov)
        self.comboBox_OVSelector.blockSignals(False)
        self.change_ov()
        self.main_controls_trigger.transmit('OV SETTINGS CHANGED')

# ------------------------------------------------------------------------------

class GridSettingsDlg(QDialog):
    """Dialog for changing grid settings and for adding/deleting grids."""

    def __init__(self, grid_manager, sem, selected_grid, main_controls_trigger,
                 magc_mode=False):
        super().__init__()
        self.gm = grid_manager
        self.sem = sem
        self.current_grid = selected_grid
        self.main_controls_trigger = main_controls_trigger
        self.magc_mode = magc_mode
        loadUi('..\\gui\\grid_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Set up grid selector:
        self.comboBox_gridSelector.addItems(self.gm.grid_selector_list())
        self.comboBox_gridSelector.setCurrentIndex(self.current_grid)
        self.comboBox_gridSelector.currentIndexChanged.connect(
            self.change_grid)
        # Set up colour selector:
        for i in range(len(utils.COLOUR_SELECTOR)):
            rgb = utils.COLOUR_SELECTOR[i]
            colour_icon = QPixmap(20, 10)
            colour_icon.fill(QColor(rgb[0], rgb[1], rgb[2]))
            self.comboBox_colourSelector.addItem(QIcon(colour_icon), '')
        if self.gm[self.current_grid].active:
            self.radioButton_active.setChecked(True)
        else:
            self.radioButton_inactive.setChecked(True)
        self.radioButton_active.toggled.connect(self.update_active_status)
        self.update_active_status()
        store_res_list = [
            '%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_tileSize.addItems(store_res_list)
        self.comboBox_tileSize.currentIndexChanged.connect(
            self.show_frame_size_and_dose)
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        self.comboBox_dwellTime.currentIndexChanged.connect(
            self.show_frame_size_and_dose)
        self.doubleSpinBox_pixelSize.valueChanged.connect(
            self.show_frame_size_and_dose)
        # Adaptive focus tool button:
        self.toolButton_focusGradient.clicked.connect(
            self.open_focus_gradient_dlg)
        # Button to load current SEM imaging parameters
        self.pushButton_getFromSEM.clicked.connect(self.get_settings_from_sem)
        # Buttons to reset tile previews and wd/stig parameters
        self.pushButton_resetTilePreviews.clicked.connect(
            self.reset_tile_previews)
        self.pushButton_resetFocusParams.clicked.connect(
            self.reset_wd_stig_params)
        # Save, add, and delete buttons
        self.pushButton_save.clicked.connect(self.save_current_settings)
        self.pushButton_addGrid.clicked.connect(self.add_grid)
        self.pushButton_deleteGrid.clicked.connect(self.delete_grid)
        self.update_buttons()
        self.show_current_settings()
        self.show_frame_size_and_dose()
        # Inactivate 'add grid' button in magc_mode
        # (should be done in MagC panel instead)
        if self.magc_mode:
            self.pushButton_addGrid.setEnabled(False)
        if 'multisem' in self.sem.device_name.lower():
            # in multisem ROIs are used instead of grids
            # the smallest possible grid is kept for compatibility
            self.spinBox_rows.setEnabled(False)
            self.spinBox_rows.setValue(1)
            self.spinBox_cols.setEnabled(False)
            self.spinBox_cols.setValue(1)
            self.comboBox_tileSize.setEnabled(False)
            self.comboBox_tileSize.setCurrentIndex(0)
            self.spinBox_shift.setEnabled(False)

    def update_active_status(self):
        # If current grid is inactive, disable GUI elements
        b = self.radioButton_active.isChecked()
        self.spinBox_rows.setEnabled(b)
        self.spinBox_cols.setEnabled(b)
        self.spinBox_overlap.setEnabled(b)
        self.spinBox_shift.setEnabled(b)
        self.doubleSpinBox_rotation.setEnabled(b)
        self.comboBox_tileSize.setEnabled(b)
        self.comboBox_dwellTime.setEnabled(b)
        self.doubleSpinBox_pixelSize.setEnabled(b)
        self.checkBox_focusGradient.setEnabled(b)
        self.toolButton_focusGradient.setEnabled(b)
        self.pushButton_resetFocusParams.setEnabled(b)
        self.spinBox_acqInterval.setEnabled(b)
        self.spinBox_acqIntervalOffset.setEnabled(b)

    def get_settings_from_sem(self):
        """Load current SEM settings for frame size, pixel size, and
        dwell time, and set the spin box and the combo boxes to these values.
        """
        current_frame_size_selector = self.sem.get_frame_size_selector()
        current_pixel_size = self.sem.get_pixel_size()
        current_scan_rate = self.sem.get_scan_rate()
        self.comboBox_tileSize.setCurrentIndex(current_frame_size_selector)
        self.comboBox_dwellTime.setCurrentIndex(current_scan_rate)
        self.doubleSpinBox_pixelSize.setValue(current_pixel_size)

    def show_current_settings(self):
        self.comboBox_colourSelector.setCurrentIndex(
            self.gm[self.current_grid].display_colour)
        self.checkBox_focusGradient.setChecked(
            self.gm[self.current_grid].use_wd_gradient)
        self.spinBox_rows.setValue(self.gm[self.current_grid].number_rows())
        self.spinBox_cols.setValue(self.gm[self.current_grid].number_cols())
        self.spinBox_overlap.setValue(self.gm[self.current_grid].overlap)
        self.doubleSpinBox_rotation.setValue(
            self.gm[self.current_grid].rotation)
        self.spinBox_shift.setValue(self.gm[self.current_grid].row_shift)

        self.doubleSpinBox_pixelSize.setValue(
            self.gm[self.current_grid].pixel_size)
        self.comboBox_tileSize.setCurrentIndex(
            self.gm[self.current_grid].frame_size_selector)
        self.comboBox_dwellTime.setCurrentIndex(
            self.gm[self.current_grid].dwell_time_selector)
        self.spinBox_acqInterval.setValue(
            self.gm[self.current_grid].acq_interval)
        self.spinBox_acqIntervalOffset.setValue(
            self.gm[self.current_grid].acq_interval_offset)

    def show_frame_size_and_dose(self):
        """Calculate and display the tile size and the dose for the current
        settings. Updated in real-time as user changes dwell time, frame
        resolution and pixel size.
        """
        frame_size_selector = self.comboBox_tileSize.currentIndex()
        pixel_size = self.doubleSpinBox_pixelSize.value()
        width = self.sem.STORE_RES[frame_size_selector][0] * pixel_size / 1000
        height = self.sem.STORE_RES[frame_size_selector][1] * pixel_size / 1000
        self.label_tileSize.setText('{0:.1f} × '.format(width)
                                    + '{0:.1f}'.format(height))
        current = self.sem.target_beam_current
        dwell_time = float(self.comboBox_dwellTime.currentText())
        pixel_size = self.doubleSpinBox_pixelSize.value()
        # Show electron dose in electrons per square nanometre.
        self.label_dose.setText('{0:.1f}'.format(
            utils.calculate_electron_dose(current, dwell_time, pixel_size)))

    def change_grid(self):
        self.current_grid = self.comboBox_gridSelector.currentIndex()
        if self.gm[self.current_grid].active:
            self.radioButton_active.setChecked(True)
        else:
            self.radioButton_inactive.setChecked(True)
        self.update_active_status()
        self.update_buttons()
        self.show_current_settings()
        self.show_frame_size_and_dose()

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
                self.current_grid == (self.gm.number_grids - 1))
        self.pushButton_save.setText(
            'Save settings for grid %d' % self.current_grid)
        self.pushButton_deleteGrid.setText('Delete grid %d' % self.current_grid)

    def add_grid(self):
        active = self.radioButton_active.isChecked()
        frame_size_selector = self.comboBox_tileSize.currentIndex()
        frame_size = self.comboBox_tileSize.currentText()
        input_overlap = self.spinBox_overlap.value()
        pixel_size = self.doubleSpinBox_pixelSize.value()
        dwell_time_selector = self.comboBox_dwellTime.currentIndex()
        dwell_time = self.comboBox_dwellTime.currentText()
        rotation = self.doubleSpinBox_rotation.value()
        input_shift = self.spinBox_shift.value()
        acq_interval = self.spinBox_acqInterval.value()
        acq_interval_offset = self.spinBox_acqIntervalOffset.value()
        size = [self.spinBox_rows.value(), self.spinBox_cols.value()]
        self.gm.add_new_grid(active=active,
                             frame_size=frame_size, frame_size_selector=frame_size_selector,
                             overlap=input_overlap, pixel_size=pixel_size,
                             dwell_time_selector=dwell_time_selector, dwell_time=dwell_time,
                             rotation=rotation, row_shift=input_shift,
                             acq_interval=acq_interval, acq_interval_offset=acq_interval_offset,
                             size=size)
        self.current_grid = self.gm.number_grids - 1
        # Update grid selector:
        self.comboBox_gridSelector.blockSignals(True)
        self.comboBox_gridSelector.clear()
        self.comboBox_gridSelector.addItems(self.gm.grid_selector_list())
        self.comboBox_gridSelector.setCurrentIndex(self.current_grid)
        self.comboBox_gridSelector.blockSignals(False)
        self.change_grid()
        self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def delete_grid(self):
        user_reply = QMessageBox.question(
                        self, 'Delete grid',
                        'This will delete grid %d.\n\n'
                        'Do you wish to proceed?' % self.current_grid,
                        QMessageBox.Ok | QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            self.gm.delete_grid()
            self.current_grid = self.gm.number_grids - 1
            # Update grid selector:
            self.comboBox_gridSelector.blockSignals(True)
            self.comboBox_gridSelector.clear()
            self.comboBox_gridSelector.addItems(self.gm.grid_selector_list())
            self.comboBox_gridSelector.setCurrentIndex(self.current_grid)
            self.comboBox_gridSelector.blockSignals(False)
            self.change_grid()
            self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def reset_tile_previews(self):
        user_reply = QMessageBox.question(
            self, 'Reset tile previews',
            f'This will clear all tile preview images in the Viewport for '
            f'grid {self.current_grid}.\n',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            self.gm[self.current_grid].clear_all_tile_previews()
            self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def reset_wd_stig_params(self):
        user_reply = QMessageBox.question(
            self, 'Reset focus/astigmatism parameters',
            f'This will reset the focus and astigmatism parameters for '
            f'all tiles in grid {self.current_grid}.\n'
            f'Proceed?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            self.gm[self.current_grid].set_wd_for_all_tiles(0)
            self.gm[self.current_grid].set_stig_xy_for_all_tiles([0, 0])
            self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def save_current_settings(self):
        error_msg = ''
        # Update tile positions only once after updating all grid attributes
        self.gm[self.current_grid].auto_update_tile_positions = False

        if self.magc_mode:
            # Preserve centre coordinates of MagC grids
            prev_grid_centre = self.gm[self.current_grid].centre_sx_sy

        self.gm[self.current_grid].active = self.radioButton_active.isChecked()
        self.gm[self.current_grid].size = [self.spinBox_rows.value(),
                                           self.spinBox_cols.value()]
        self.gm[self.current_grid].frame_size_selector = (
            self.comboBox_tileSize.currentIndex())
        tile_width_p = self.gm[self.current_grid].tile_width_p()
        input_overlap = self.spinBox_overlap.value()
        input_shift = self.spinBox_shift.value()
        if -0.3 * tile_width_p <= input_overlap < 0.3 * tile_width_p:
            self.gm[self.current_grid].overlap = input_overlap
        else:
            error_msg = ('Overlap outside of allowed '
                         'range (-30% .. 30% frame width).')
        # Get current centre of grid:
        centre_dx, centre_dy = self.gm[self.current_grid].centre_dx_dy
        # Set new angle
        self.gm[self.current_grid].rotation = (
            self.doubleSpinBox_rotation.value())
        self.gm[self.current_grid].rotate_around_grid_centre(centre_dx, centre_dy)
        if 0 <= input_shift <= tile_width_p:
            self.gm[self.current_grid].row_shift = input_shift
        else:
            error_msg = ('Row shift outside of allowed '
                         'range (0 .. frame width).')
        self.gm[self.current_grid].display_colour = (
            self.comboBox_colourSelector.currentIndex())
        self.gm[self.current_grid].use_wd_gradient = (
            self.checkBox_focusGradient.isChecked())
        if self.checkBox_focusGradient.isChecked():
            self.gm[self.current_grid].calculate_wd_gradient()
        # Acquisition parameters:
        self.gm[self.current_grid].pixel_size = (
            self.doubleSpinBox_pixelSize.value())
        self.gm[self.current_grid].dwell_time_selector = (
            self.comboBox_dwellTime.currentIndex())
        self.gm[self.current_grid].acq_interval = (
            self.spinBox_acqInterval.value())
        self.gm[self.current_grid].acq_interval_offset = (
            self.spinBox_acqIntervalOffset.value())
        # Finally, recalculate tile positions
        self.gm[self.current_grid].update_tile_positions()
        self.gm[self.current_grid].auto_update_tile_positions = True
        if self.magc_mode:
            self.gm[self.current_grid].centre_sx_sy = prev_grid_centre
            self.gm.update_source_ROIs_from_grids()
        # Restore default behaviour for updating tile positions
        if error_msg:
            QMessageBox.warning(self, 'Error', error_msg, QMessageBox.Ok)
        else:
            self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def open_focus_gradient_dlg(self):
        sub_dialog = FocusGradientSettingsDlg(self.gm, self.current_grid)
        sub_dialog.exec_()

# ------------------------------------------------------------------------------

class FocusGradientSettingsDlg(QDialog):
    """Select the tiles to calculate the working distance gradient."""

    def __init__(self, gm, current_grid):
        super().__init__()
        self.gm = gm
        self.current_grid = current_grid
        loadUi('..\\gui\\wd_gradient_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_currentGrid.setText('Grid ' + str(current_grid))
        self.grid_illustration.setPixmap(QPixmap('..\\img\\grid.png'))
        self.ref_tiles = self.gm[self.current_grid].wd_gradient_ref_tiles
        # Backup variable for currently selected reference tiles:
        self.prev_ref_tiles = self.ref_tiles.copy()
        # Set up tile selectors for the reference tiles:
        number_of_tiles = self.gm[self.current_grid].number_tiles
        tile_list_str = ['-']
        for tile in range(number_of_tiles):
            tile_list_str.append(str(tile))
        for i in range(3):
            if self.ref_tiles[i] >= number_of_tiles:
                self.ref_tiles[i] = -1

        self.comboBox_tileUpperLeft.blockSignals(True)
        self.comboBox_tileUpperLeft.addItems(tile_list_str)
        self.comboBox_tileUpperLeft.setCurrentIndex(self.ref_tiles[0] + 1)
        self.comboBox_tileUpperLeft.currentIndexChanged.connect(
            self.update_settings)
        self.comboBox_tileUpperLeft.blockSignals(False)

        self.comboBox_tileUpperRight.blockSignals(True)
        self.comboBox_tileUpperRight.addItems(tile_list_str)
        self.comboBox_tileUpperRight.setCurrentIndex(self.ref_tiles[1] + 1)
        self.comboBox_tileUpperRight.currentIndexChanged.connect(
            self.update_settings)
        self.comboBox_tileUpperRight.blockSignals(False)

        self.comboBox_tileLowerLeft.blockSignals(True)
        self.comboBox_tileLowerLeft.addItems(tile_list_str)
        self.comboBox_tileLowerLeft.setCurrentIndex(self.ref_tiles[2] + 1)
        self.comboBox_tileLowerLeft.currentIndexChanged.connect(
            self.update_settings)
        self.comboBox_tileLowerLeft.blockSignals(False)

        self.update_settings()

    def update_settings(self):
        """Get selected working distances and calculate origin WD and
        gradient if possible.
        """
        self.ref_tiles[0] = self.comboBox_tileUpperLeft.currentIndex() - 1
        self.ref_tiles[1] = self.comboBox_tileUpperRight.currentIndex() - 1
        self.ref_tiles[2] = self.comboBox_tileLowerLeft.currentIndex() - 1

        if self.ref_tiles[0] >= 0:
            self.label_t1.setText('Tile ' + str(self.ref_tiles[0]) + ':')
            wd = self.gm[self.current_grid][self.ref_tiles[0]].wd
            self.doubleSpinBox_t1.setValue(wd * 1000)
        else:
            self.label_t1.setText('Tile (-) :')
            self.doubleSpinBox_t1.setValue(0)
        if self.ref_tiles[1] >= 0:
            self.label_t2.setText('Tile ' + str(self.ref_tiles[1]) + ':')
            wd = self.gm[self.current_grid][self.ref_tiles[1]].wd
            self.doubleSpinBox_t2.setValue(wd * 1000)
        else:
            self.label_t2.setText('Tile (-) :')
            self.doubleSpinBox_t2.setValue(0)
        if self.ref_tiles[2] >= 0:
            self.label_t3.setText('Tile ' + str(self.ref_tiles[2]) + ':')
            wd = self.gm[self.current_grid][self.ref_tiles[2]].wd
            self.doubleSpinBox_t3.setValue(wd * 1000)
        else:
            self.label_t3.setText('Tile (-) :')
            self.doubleSpinBox_t3.setValue(0)

        self.gm[self.current_grid].wd_gradient_ref_tiles = self.ref_tiles
        # Try to calculate focus map:
        self.success = self.gm[self.current_grid].calculate_wd_gradient()
        if self.success:
            params = self.gm[self.current_grid].wd_gradient_params
            # print(params)
            current_status_str = (
                'WD: ' + '{:.6f}'.format(params[0] * 1000)
                + ' mm;\n' + chr(8710)
                + 'x: ' + '{:.6f}'.format(params[1] * 1000)
                + '; ' + chr(8710) + 'y: ' + '{:.6f}'.format(params[2] * 1000))
        else:
            current_status_str = 'Insufficient or incorrect tile selection'

        self.textEdit_originGradients.setText(current_status_str)

    def accept(self):
        if self.success:
            super().accept()
        else:
            QMessageBox.warning(
                self, 'Error',
                'Insufficient or incorrect tile selection. Cannot calculate '
                'origin working distance and focus gradient.',
                 QMessageBox.Ok)

    def reject(self):
        # Restore previous selection:
        self.gm[self.current_grid].wd_gradient_ref_tiles = self.prev_ref_tiles
        # Recalculate with previous setting:
        self.gm[self.current_grid].calculate_wd_gradient()
        super().reject()

# ------------------------------------------------------------------------------

class AcqSettingsDlg(QDialog):
    """Dialog for adjusting acquisition settings."""

    def __init__(self, acquisition, notifications, use_microtome=True):
        super().__init__()
        self.acq = acquisition
        self.notifications = notifications
        loadUi('..\\gui\\acq_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_selectDir.clicked.connect(self.select_directory)
        self.pushButton_selectDir.setIcon(QIcon('..\\img\\selectdir.png'))
        self.pushButton_selectDir.setIconSize(QSize(16, 16))
        # Display current settings:
        self.lineEdit_baseDir.setText(self.acq.base_dir)
        self.lineEdit_baseDir.textChanged.connect(self.update_stack_name)
        self.update_stack_name()
        self.new_base_dir = ''
        self.spinBox_sliceThickness.setValue(self.acq.slice_thickness)
        self.spinBox_numberSlices.setValue(self.acq.number_slices)
        self.spinBox_sliceCounter.setValue(self.acq.slice_counter)
        self.doubleSpinBox_zDiff.setValue(self.acq.total_z_diff)
        self.checkBox_sendMetaData.setChecked(self.acq.send_metadata)
        self.update_server_lineedit()
        self.checkBox_sendMetaData.stateChanged.connect(
            self.update_server_lineedit)
        self.checkBox_EHTOff.setChecked(self.acq.eht_off_after_stack)
        self.lineEdit_metaDataServer.setText(
            self.notifications.metadata_server_url)
        self.lineEdit_adminEmail.setText(
            self.notifications.metadata_server_admin_email)
        self.lineEdit_projectName.setText(self.acq.metadata_project_name)
        # Disable two spinboxes when SEM stage used
        if not use_microtome:
            self.spinBox_sliceThickness.setEnabled(False)
            self.doubleSpinBox_zDiff.setEnabled(False)

    def select_directory(self):
        """Let user select the base directory for the stack acquisition.
        Note that the final subfolder name in the directory string is used as
        the name of the stack in SBEMimage.
        """
        if len(self.acq.base_dir) > 2:
            start_path = self.acq.base_dir[:3]
        else:
            start_path = 'C:\\'
        self.lineEdit_baseDir.setText(
            str(QFileDialog.getExistingDirectory(
                self, 'Select Directory',
                start_path,
                QFileDialog.ShowDirsOnly)).replace('/', '\\'))

    def update_server_lineedit(self):
        self.lineEdit_projectName.setEnabled(
            self.checkBox_sendMetaData.isChecked())

    def update_stack_name(self):
        base_dir = self.lineEdit_baseDir.text().rstrip(r'\/ ')
        self.label_stackName.setText(base_dir[base_dir.rfind('\\') + 1:])

    def accept(self):
        success = True
        selected_dir = self.lineEdit_baseDir.text()
        # Remove trailing slashes and whitespace
        modified_dir = selected_dir.rstrip(r'\/ ')
        # Replace spaces and forward slashes
        modified_dir = modified_dir.replace(' ', '_').replace('/', '\\')
        # Notify user if directory was modified
        if modified_dir != selected_dir:
            self.lineEdit_baseDir.setText(modified_dir)
            self.update_stack_name()
            QMessageBox.information(
                self, 'Base directory name modified',
                'The selected base directory was modified by removing '
                'trailing slashes and whitespace and replacing spaces with '
                'underscores and forward slashes with backslashes.',
                QMessageBox.Ok)
        # Check if path contains a drive letter
        reg = re.compile('^[a-zA-Z]:\\\$')
        if not reg.match(modified_dir[:3]):
            success = False
            QMessageBox.warning(
                self, 'Error',
                'Please specify the full path to the base directory. It '
                'must begin with a drive letter, for example: "D:\\..."',
                QMessageBox.Ok)
        else:
            # If workspace directory does not yet exist, create it to test
            # whether path is valid and accessible
            workspace_dir = os.path.join(modified_dir, 'workspace')
            try:
                if not os.path.exists(workspace_dir):
                    os.makedirs(workspace_dir)
            except Exception as e:
                success = False
                QMessageBox.warning(
                    self, 'Error',
                    'The selected base directory is invalid or '
                    'inaccessible: ' + str(e),
                    QMessageBox.Ok)
        min_slice_thickness = 5
        if self.acq.syscfg['device']['microtome'] == '6':
            min_slice_thickness = 0
        if min_slice_thickness <= self.spinBox_sliceThickness.value() <= 200:
            self.acq.slice_thickness = self.spinBox_sliceThickness.value()
        number_slices = self.spinBox_numberSlices.value()
        self.acq.number_slices = number_slices
        if (self.spinBox_sliceCounter.value() <= number_slices
            or number_slices == 0):
            self.acq.slice_counter = self.spinBox_sliceCounter.value()
        self.acq.total_z_diff = self.doubleSpinBox_zDiff.value()
        self.acq.eht_off_after_stack = self.checkBox_EHTOff.isChecked()
        self.acq.send_metadata = self.checkBox_sendMetaData.isChecked()
        if self.checkBox_sendMetaData.isChecked():
            metadata_server_url = self.lineEdit_metaDataServer.text()
            if not validators.url(metadata_server_url):
                QMessageBox.warning(
                    self, 'Error',
                    'Metadata server URL is invalid. Change the URL in the '
                    'system configuration file.',
                    QMessageBox.Ok)
            self.acq.metadata_project_name = self.lineEdit_projectName.text()
        if ((number_slices > 0)
            and (self.spinBox_sliceCounter.value() > number_slices)):
            QMessageBox.warning(
                self, 'Error',
                'Slice counter must be smaller than or equal to '
                'target number of slices.', QMessageBox.Ok)
            success = False
        if success:
            self.acq.base_dir = modified_dir
            if self.acq.number_slices > self.acq.slice_counter:
                self.acq.stack_completed = False
            super().accept()

# ------------------------------------------------------------------------------

class PreStackDlg(QDialog):
    """This dialog is called before starting a stack. It lets the user view a
    summary of the stack acquisition setup. It also shows several settings that
    can only be changed in DM and lets the user adjust them for logging
    purposes.
    """

    def __init__(self, acq, sem, microtome, autofocus, ovm, gm):
        super().__init__()
        self.acq = acq
        self.sem = sem
        self.microtome = microtome
        self.gm = gm
        loadUi('..\\gui\\pre_stack_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Different labels if stack is paused ('Continue' instead of 'Start')
        if self.acq.acq_paused:
            self.pushButton_startAcq.setText('Continue acquisition')
            self.setWindowTitle('Continue acquisition')
        self.pushButton_startAcq.clicked.connect(self.accept)
        self.pushButton_editInterruption.clicked.connect(
            self.edit_interruption_point)
        boldFont = QFont()
        boldFont.setBold(True)
        # Show the most relevant current settings for the acquisition
        self.label_stackName.setText(self.acq.stack_name)
        self.label_sliceCounter.setText(str(self.acq.slice_counter))
        self.label_beamSettings.setText(
            f'{self.sem.target_eht:.2f} keV, '
            f'{self.sem.target_beam_current} pA, '
            f'{self.sem.target_aperture_size} μm')
        if self.acq.take_overviews:
            number_ov = ovm.total_number_active_overviews()
        else:
            number_ov = 0
        self.label_gridSetup.setText(
            f'{number_ov} overview(s), '
            f'{self.gm.total_number_active_grids()} grid(s);')
        self.label_totalActiveTiles.setText(
            f'{self.gm.total_number_active_tiles()} active tile(s)')
        if self.acq.use_autofocus:
            if autofocus.method == 0:
                self.label_autofocusActive.setFont(boldFont)
                self.label_autofocusActive.setText('Active (SmartSEM)')
            elif autofocus.method == 1:
                self.label_autofocusActive.setFont(boldFont)
                self.label_autofocusActive.setText('Active (heuristic)')
            if autofocus.method == 3:
                self.label_autofocusActive.setFont(boldFont)
                self.label_autofocusActive.setText('Active (MAPFoSt)')
        else:
            self.label_autofocusActive.setText('Inactive')
        if self.gm.wd_gradient_active():
            self.label_gradientActive.setFont(boldFont)
            self.label_gradientActive.setText('Active')
        else:
            self.label_gradientActive.setText('Inactive')
        if self.gm.intervallic_acq_active() or ovm.intervallic_acq_active():
            self.label_intervallicActive.setFont(boldFont)
            self.label_intervallicActive.setText('Active')
        else:
            self.label_intervallicActive.setText('Inactive')
        self.show_interruption_point()
        self.doubleSpinBox_brightness.setValue(self.sem.bsd_brightness)
        self.doubleSpinBox_contrast.setValue(self.sem.bsd_contrast)
        self.spinBox_bias.setValue(self.sem.bsd_bias)
        if self.microtome is not None and self.microtome.device_name != 'GCIB':
            self.checkBox_oscillation.setChecked(self.microtome.use_oscillation)
            self.doubleSpinBox_cutSpeed.setValue(
                self.microtome.knife_cut_speed / 1000)
            self.doubleSpinBox_retractSpeed.setValue(
                self.microtome.knife_retract_speed / 1000)

    def edit_interruption_point(self):
        dialog = SetStartTileDlg(self.acq, self.gm)
        dialog.exec_()
        # Update interruption point label
        self.show_interruption_point()

    def show_interruption_point(self):
        if self.acq.acq_interrupted:
            boldFont = QFont()
            boldFont.setBold(True)
            self.label_interruption.setFont(boldFont)
            self.label_interruption.setText(
                f'Yes, in grid {self.acq.acq_interrupted_at[0]} '
                f'at tile {self.acq.acq_interrupted_at[1]}')
        else:
            self.label_interruption.setText('None')

    def accept(self):
        # Save updated settings
        self.sem.bsd_contrast = self.doubleSpinBox_contrast.value()
        self.sem.bsd_brightness = self.doubleSpinBox_brightness.value()
        self.sem.bsd_bias = self.spinBox_bias.value()
        if self.microtome is not None and self.microtome.device_name != 'GCIB':
            self.microtome.use_oscillation = self.checkBox_oscillation.isChecked()
            self.microtome.knife_cut_speed = int(
                self.doubleSpinBox_cutSpeed.value() * 1000)
            self.microtome.knife_retract_speed = int(
                self.doubleSpinBox_retractSpeed.value() * 1000)
        super().accept()

# ------------------------------------------------------------------------------

class SetStartTileDlg(QDialog):
    """Adjust the grid/tile at which to (re)start the acquisition."""

    def __init__(self, acquisition, grid_manager):
        super().__init__()
        self.acq = acquisition
        self.gm = grid_manager
        loadUi('..\\gui\\set_start_tile_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        if self.acq.acq_interrupted:
            self.label_acqstatus1.setText(
                'The acquisition was interrupted/paused')
            grid_index, tile_index = self.acq.acq_interrupted_at
        else:
            self.label_acqstatus1.setText(
                'The acquisition was not interrupted')
            grid_index = None
            # Find first tile to be acquired
            for g in range(self.gm.number_grids):
                if (self.gm[g].active
                        and self.gm[g].active_tiles):
                    # First active grid
                    grid_index = g
                    break
            if grid_index is not None:
                # First active tile in first active grid
                tile_index = self.gm[grid_index].active_tiles[0]
            else:
                grid_index, tile_index = 0, 0

        self.label_acqstatus2.setText(
            f'and will (re)start at tile {tile_index} in grid {grid_index}.')

        # Populate grid selector
        self.comboBox_gridSelector.clear()
        self.comboBox_gridSelector.addItems(self.gm.grid_selector_list())
        self.comboBox_gridSelector.setCurrentIndex(grid_index)
        self.comboBox_gridSelector.currentIndexChanged.connect(
            self.update_tile_selector)
        # Populate tile selector
        self.update_tile_selector()
        # Select current tile (+1 to account for entry 'Select tile')
        self.comboBox_tileSelector.setCurrentIndex(tile_index + 1)

    def update_tile_selector(self):
        """Populate the tile selector with the active tiles of the currently
        selected grid.
        """
        selected_grid = self.comboBox_gridSelector.currentIndex()
        self.comboBox_tileSelector.clear()
        self.comboBox_tileSelector.addItems(
            ['Select tile']
            + self.gm[selected_grid].tile_selector_list())
        self.comboBox_tileSelector.setCurrentIndex(0)

    def accept(self):
        grid_index = self.comboBox_gridSelector.currentIndex()
        tile_index = self.comboBox_tileSelector.currentIndex() - 1
        if tile_index == -1:
            QMessageBox.warning(
                self, 'No tile selected',
                'Please select a tile or click "Cancel"',
                QMessageBox.Ok)
        elif not self.gm[grid_index][tile_index].tile_active:
            QMessageBox.warning(
                self, 'Select active tile',
                'The tile you selected is currently inactive. Please select '
                'an active tile.',
                QMessageBox.Ok)
        else:
            # Set selected tile as new interruption point
            self.acq.set_interruption_point(grid_index, tile_index,
                                            during_acq=False)
            super().accept()

# ------------------------------------------------------------------------------

class PauseDlg(QDialog):
    """This dialog is called when the user clicks 'PAUSE' to pause a running
    acquisition. In the dialog, the user can then choose between two options:
    (1) Pause as soon as possible (after acquisition of the current OV or tile
    is complete). (2) Pause after imaging of the current slice is completed and
    the surface has been cut.
    """

    def __init__(self):
        super().__init__()
        loadUi('..\\gui\\pause_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pause_type = 0  # don't pause (when user clicks 'Cancel')
        self.pushButton_pauseNow.clicked.connect(self.pause_now)
        self.pushButton_pauseAfterSlice.clicked.connect(self.pause_later)

    def pause_now(self):
        self.pause_type = 1  # pause immediately
        self.accept()

    def pause_later(self):
        self.pause_type = 2  # pause after slice is completed
        self.accept()

    def accept(self):
        super().accept()

# ------------------------------------------------------------------------------

class ExportDlg(QDialog):
    """Export image list in TrakEM2 format."""

    def __init__(self, acq):
        super().__init__()
        self.acq = acq
        loadUi('..\\gui\\export_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.pushButton_export.clicked.connect(self.export_list)
        self.spinBox_untilSlice.setValue(int(self.acq.slice_counter))
        self.show()

    def export_list(self):
        self.pushButton_export.setText('Busy')
        self.pushButton_export.setEnabled(False)
        QApplication.processEvents()
        base_dir = self.acq.base_dir
        target_grid_index = str(
            self.spinBox_gridNumber.value()).zfill(utils.GRID_DIGITS)
        pixel_size = self.doubleSpinBox_pixelSize.value()
        start_slice = self.spinBox_fromSlice.value()
        end_slice = self.spinBox_untilSlice.value()
        # Read all imagelist files into memory
        imagelist_str = []
        imagelist_data = []
        file_list = glob.glob(
            os.path.join(base_dir, 'meta', 'logs', 'imagelist*.txt'))
        file_list.sort()
        for file in file_list:
            with open(file) as f:
                imagelist_str.extend(f.readlines())
        if len(imagelist_str) > 0:
            # split strings, store entries in variables, find minimum x and y
            min_x = 10000000
            min_y = 10000000
            for line in imagelist_str:
                elements = line.split(';')
                # elements[0]: relative path to tile image
                # elements[1]: x coordinate in nm
                # elements[2]: y coordinate in nm
                # elements[3]: z coordinate in nm
                # elements[4]: slice number
                slice_number = int(elements[4])
                grid_index = elements[0][7:11]
                if (start_slice <= slice_number <= end_slice
                    and grid_index == target_grid_index):
                    x = int(int(elements[1]) / pixel_size)
                    if x < min_x:
                        min_x = x
                    y = int(int(elements[2]) / pixel_size)
                    if y < min_y:
                        min_y = y
                    imagelist_data.append([elements[0], x, y, slice_number])
            # Subtract minimum values to obtain bounding box with (0, 0) as
            # origin in top-left corner.
            for item in imagelist_data:
                item[1] -= min_x
                item[2] -= min_y
            # Write to output file
            try:
                output_file = os.path.join(base_dir,
                                           'trakem2_imagelist_slice'
                                           + str(start_slice)
                                           + 'to'
                                           + str(end_slice)
                                           + '.txt')
                with open(output_file, 'w') as f:
                    for item in imagelist_data:
                        f.write(item[0] + '\t'
                                + str(item[1]) + '\t'
                                + str(item[2]) + '\t'
                                + str(item[3]) + '\n')
            except Exception as e:
                QMessageBox.warning(
                    self, 'Error',
                    'An error ocurred while writing the output file: ' + str(e),
                    QMessageBox.Ok)
            else:
                QMessageBox.information(
                    self, 'Export completed',
                    f'A total of {len(imagelist_data)} tile entries were '
                    f'processed.\n\nThe output file\n'
                    f'trakem2_imagelist_slice{start_slice}to{end_slice}.txt\n'
                    f'was written to the current base directory\n'
                    f'{base_dir}.',
                    QMessageBox.Ok)
        else:
            QMessageBox.warning(
                self, 'Error',
                'No image metadata found.',
                QMessageBox.Ok)
        self.pushButton_export.setText('Export')
        self.pushButton_export.setEnabled(True)
        QApplication.processEvents()

# ------------------------------------------------------------------------------

class UpdateDlg(QDialog):
    """Update SBEMimage by downloading latest version from GitHub."""

    def __init__(self):
        super().__init__()
        loadUi('..\\gui\\update_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.pushButton_update.clicked.connect(self.update)
        self.show()

    def update(self):
        self.pushButton_update.setText('Busy')
        self.pushButton_update.setEnabled(False)
        QApplication.processEvents()
        url = "https://github.com/SBEMimage/SBEMimage/archive/master.zip"
        try:
            response = requests.get(url, stream=True)
            with open('master.zip', 'wb') as file:
                shutil.copyfileobj(response.raw, file)
            del response
        except:
            QMessageBox.warning(
                self, 'Error',
                'Could not download current version from GitHub. Check your '
                'internet connection. ',
                QMessageBox.Ok)
        else:
            # Get directory of current installation
            install_path = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))
            try:
                with ZipFile("master.zip", "r") as zip_object:
                    for zip_info in zip_object.infolist():
                        if zip_info.filename[-1] == '/':
                            continue
                        # Remove string 'SBEMimage-master/'
                        zip_info.filename = zip_info.filename[17:]
                        # print(zip_info.filename)
                        zip_object.extract(zip_info, install_path)
            except:
                QMessageBox.warning(
                self, 'Error',
                'Could not extract downloaded GitHub archive.',
                QMessageBox.Ok)
            else:
                QMessageBox.information(
                self, 'Update complete',
                'SBEMimage was updated to the most recent version. '
                'You must restart the program to use the updated version.',
                QMessageBox.Ok)
                self.pushButton_update.setText('Update now')
                self.pushButton_update.setEnabled(True)

# ------------------------------------------------------------------------------

class EmailMonitoringSettingsDlg(QDialog):
    """Adjust settings for e-mail monitoring: e-mail addresses, status report
    options, and remote control through e-mail commands.
    """

    def __init__(self, acquisition, notifications):
        super().__init__()
        self.acq = acquisition
        self.notifications = notifications
        loadUi('..\\gui\\email_monitoring_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_notificationEmail.setText(
            self.notifications.user_email_addresses[0])
        self.lineEdit_secondaryNotificationEmail.setText(
            self.notifications.user_email_addresses[1])
        self.spinBox_reportInterval.setValue(self.acq.status_report_interval)
        self.lineEdit_selectedOV.setText(str(
            self.notifications.status_report_ov_list)[1:-1])
        self.lineEdit_selectedTiles.setText(str(
            self.notifications.status_report_tile_list)[1:-1].replace('\'', ''))
        self.checkBox_sendLogFile.setChecked(self.notifications.send_logfile)
        self.checkBox_sendIncidentLogFile.setChecked(
            self.notifications.send_additional_logs)
        self.checkBox_sendViewport.setChecked(
            self.notifications.send_viewport_screenshot)
        self.checkBox_sendOverviews.setChecked(self.notifications.send_ov)
        self.checkBox_sendOverviews.stateChanged.connect(
            self.update_ov_list_input)
        self.checkBox_sendTiles.setChecked(self.notifications.send_tiles)
        self.checkBox_sendTiles.stateChanged.connect(
            self.update_tile_list_input)
        self.checkBox_sendOVReslices.setChecked(
            self.notifications.send_ov_reslices)
        self.checkBox_sendOVReslices.stateChanged.connect(
            self.update_ov_list_input)
        self.checkBox_sendTileReslices.setChecked(
            self.notifications.send_tile_reslices)
        self.checkBox_sendTileReslices.stateChanged.connect(
            self.update_tile_list_input)
        self.checkBox_allowEmailControl.setChecked(
            self.notifications.remote_commands_enabled)
        self.checkBox_allowEmailControl.stateChanged.connect(
            self.update_remote_option_input)
        self.update_remote_option_input()
        self.spinBox_remoteCheckInterval.setValue(
            self.acq.remote_check_interval)
        self.lineEdit_account.setText(self.notifications.email_account)
        # Show password as string of asterisks
        self.lineEdit_password.setEchoMode(QLineEdit.Password)
        self.lineEdit_password.setText(self.notifications.remote_cmd_email_pw)

    def update_ov_list_input(self):
        self.lineEdit_selectedOV.setEnabled(
            (self.checkBox_sendOverviews.isChecked()
             or self.checkBox_sendOVReslices.isChecked()))

    def update_tile_list_input(self):
        self.lineEdit_selectedTiles.setEnabled(
            (self.checkBox_sendTiles.isChecked()
             or self.checkBox_sendTileReslices.isChecked()))

    def update_remote_option_input(self):
        status = self.checkBox_allowEmailControl.isChecked()
        self.spinBox_remoteCheckInterval.setEnabled(status)
        self.lineEdit_password.setEnabled(status)

    def accept(self):
        error_str = ''
        email1 = self.lineEdit_notificationEmail.text()
        email2 = self.lineEdit_secondaryNotificationEmail.text()
        if validate_email(email1):
            self.notifications.user_email_addresses[0] = email1
        else:
            error_str = (
                'First user e-mail address incorrectly formatted or missing.')
        # Second user e-mail is optional
        if validate_email(email2) or not email2:
            self.notifications.user_email_addresses[1] = (
                self.lineEdit_secondaryNotificationEmail.text())
        else:
            error_str = 'Second user e-mail address incorrectly formatted.'
        self.acq.status_report_interval = self.spinBox_reportInterval.value()

        success, ov_list = utils.validate_ov_list(
            self.lineEdit_selectedOV.text())
        if success:
            self.notifications.status_report_ov_list = ov_list
        else:
            error_str = 'List of selected overviews incorrectly formatted.'

        success, tile_list = utils.validate_tile_list(
            self.lineEdit_selectedTiles.text())
        if success:
            self.notifications.status_report_tile_list = tile_list
        else:
            error_str = 'List of selected tiles incorrectly formatted.'

        self.notifications.send_logfile = self.checkBox_sendLogFile.isChecked()
        self.notifications.send_additional_logs = (
            self.checkBox_sendIncidentLogFile.isChecked())
        self.notifications.send_viewport_screenshot = (
            self.checkBox_sendViewport.isChecked())
        self.notifications.send_ov = (
            self.checkBox_sendOverviews.isChecked())
        self.notifications.send_tiles = (
            self.checkBox_sendTiles.isChecked())
        self.notifications.send_ov_reslices = (
            self.checkBox_sendOVReslices.isChecked())
        self.notifications.send_tile_reslices = (
            self.checkBox_sendTileReslices.isChecked())
        self.notifications.remote_commands_enabled = (
            self.checkBox_allowEmailControl.isChecked())
        self.acq.remote_check_interval = (
            self.spinBox_remoteCheckInterval.value())
        self.notifications.remote_cmd_email_pw = self.lineEdit_password.text()
        if not error_str:
            super().accept()
        else:
            QMessageBox.warning(self, 'Error', error_str, QMessageBox.Ok)

# ------------------------------------------------------------------------------

class DebrisSettingsDlg(QDialog):
    """Adjust the settings for debris detection and removal: Detection area,
    detection method and parameters, max. number of sweeps, and what to do when
    max. sweep number reached.
    """

    def __init__(self, ovm, image_inspector, acq):
        super().__init__()
        self.ovm = ovm
        self.img_inspector = image_inspector
        self.acq = acq
        loadUi('..\\gui\\debris_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Detection area
        if self.ovm.use_auto_debris_area:
            self.radioButton_autoSelection.setChecked(True)
        else:
            self.radioButton_fullSelection.setChecked(True)
        # Extra margin around detection area in pixels
        self.spinBox_debrisMargin.setValue(
            self.ovm.auto_debris_area_margin)
        self.spinBox_maxSweeps.setValue(self.acq.max_number_sweeps)
        self.doubleSpinBox_diffMean.setValue(
            self.img_inspector.mean_diff_threshold)
        self.doubleSpinBox_diffSD.setValue(
            self.img_inspector.stddev_diff_threshold)
        self.spinBox_diffHistogram.setValue(
            self.img_inspector.histogram_diff_threshold)
        self.spinBox_diffPixels.setValue(
            self.img_inspector.image_diff_threshold)
        self.checkBox_showDebrisArea.setChecked(
            self.ovm.detection_area_visible)
        self.checkBox_continueAcq.setChecked(
            self.acq.continue_after_max_sweeps)
        # Detection methods
        self.radioButton_methodQuadrant.setChecked(
            self.img_inspector.debris_detection_method == 0)
        self.radioButton_methodPixel.setChecked(
            self.img_inspector.debris_detection_method == 1)
        self.radioButton_methodHistogram.setChecked(
            self.img_inspector.debris_detection_method == 2)
        self.radioButton_methodQuadrant.toggled.connect(
            self.update_option_selection)
        self.radioButton_methodHistogram.toggled.connect(
            self.update_option_selection)
        self.update_option_selection()
        self.show_moving_averages()
        # Button to reset moving averages
        self.pushButton_resetAvg.clicked.connect(
            self.reset_moving_averages)

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

    def show_moving_averages(self):
        """Show current moving averages for mean and SD differences
        if more than two values (each) available.
        """
        if len(self.img_inspector.mean_diffs) > 2:
            self.lineEdit_diffMeanAvg.setText(
                f'{mean(self.img_inspector.mean_diffs):.2f}')
        else:
            self.lineEdit_diffMeanAvg.setText('-')
        if len(self.img_inspector.stddev_diffs) > 2:
            self.lineEdit_diffSDAvg.setText(
                f'{mean(self.img_inspector.stddev_diffs):.2f}')
        else:
            self.lineEdit_diffSDAvg.setText('-')

    def reset_moving_averages(self):
        self.img_inspector.mean_diffs.clear()
        self.img_inspector.stddev_diffs.clear()
        self.show_moving_averages()

    def accept(self):
        self.ovm.auto_debris_area_margin = self.spinBox_debrisMargin.value()
        self.acq.max_number_sweeps = self.spinBox_maxSweeps.value()
        self.img_inspector.mean_diff_threshold = (
            self.doubleSpinBox_diffMean.value())
        self.img_inspector.stddev_diff_threshold = (
            self.doubleSpinBox_diffSD.value())
        self.img_inspector.histogram_diff_threshold = (
            self.spinBox_diffHistogram.value())
        self.img_inspector.image_diff_threshold = (
            self.spinBox_diffPixels.value())
        self.ovm.use_auto_debris_area = (
            self.radioButton_autoSelection.isChecked())
        self.ovm.detection_area_visible = (
            self.checkBox_showDebrisArea.isChecked())
        self.acq.continue_after_max_sweeps = (
            self.checkBox_continueAcq.isChecked())
        if self.radioButton_methodQuadrant.isChecked():
            self.img_inspector.debris_detection_method = 0
        elif self.radioButton_methodPixel.isChecked():
            self.img_inspector.debris_detection_method = 1
        elif self.radioButton_methodHistogram.isChecked():
            self.img_inspector.debris_detection_method = 2
        super().accept()

# ------------------------------------------------------------------------------

class AskUserDlg(QDialog):
    """Specify for which events the program should let the user decide how
    to proceed. The "Ask User" functionality is currently only used for
    debris detection. Will be expanded, work in progress...
    """

    def __init__(self):
        super().__init__()
        loadUi('..\\gui\\ask_user_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()

# ------------------------------------------------------------------------------

class MirrorDriveDlg(QDialog):
    """Select a mirror drive from all available drives."""

    def __init__(self, acquisition):
        super().__init__()
        self.acq = acquisition
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
        utils.run_log_thread(self.search_drives)

    def search_drives(self):
        # Search for all available drives:
        self.available_drives = [
            '%s:' % d for d in string.ascii_uppercase
            if os.path.exists('%s:' % d)]
        if self.available_drives:
            self.comboBox_allDrives.addItems(self.available_drives)
            current_index = self.comboBox_allDrives.findText(
                self.acq.mirror_drive)
            if current_index == -1:
                current_index = 0
            self.comboBox_allDrives.setCurrentIndex(current_index)
            # Restore label after searching for available drives:
            self.label_text.setText('Select drive for mirroring acquired data:')

    def accept(self):
        if self.available_drives:
            if (self.comboBox_allDrives.currentText()[0]
                == self.acq.base_dir[0]):
                QMessageBox.warning(
                    self, 'Error',
                    'The mirror drive must be different from the '
                    'base directory drive!', QMessageBox.Ok)
            else:
                self.acq.mirror_drive = (
                    self.comboBox_allDrives.currentText())
                self.acq.mirror_drive_dir = os.path.join(
                    self.acq.mirror_drive, self.acq.base_dir[2:])
                super().accept()

# ------------------------------------------------------------------------------

class ImageMonitoringSettingsDlg(QDialog):
    """Adjust settings to monitor overviews and tiles. A test if a given image
    is within mean/SD range is performed for all acquired images if this feature
    is activated. Tile-by-tile comparisons are performed for the selected tiles
    only.
    """
    def __init__(self, image_inspector):
        super().__init__()
        self.img_inspector = image_inspector
        loadUi('..\\gui\\image_monitoring_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.spinBox_meanMin.setValue(self.img_inspector.mean_lower_limit)
        self.spinBox_meanMax.setValue(self.img_inspector.mean_upper_limit)
        self.spinBox_stddevMin.setValue(self.img_inspector.stddev_lower_limit)
        self.spinBox_stddevMax.setValue(self.img_inspector.stddev_upper_limit)
        self.lineEdit_monitorTiles.setText(str(
            self.img_inspector.monitoring_tile_list)[1:-1].replace('\'', ''))
        self.doubleSpinBox_meanThreshold.setValue(
            self.img_inspector.tile_mean_threshold)
        self.doubleSpinBox_stdDevThreshold.setValue(
            self.img_inspector.tile_stddev_threshold)

    def accept(self):
        error_str = ''
        self.img_inspector.mean_lower_limit = self.spinBox_meanMin.value()
        self.img_inspector.mean_upper_limit = self.spinBox_meanMax.value()
        self.img_inspector.stddev_lower_limit = self.spinBox_stddevMin.value()
        self.img_inspector.stddev_upper_limit = self.spinBox_stddevMax.value()

        tile_str = self.lineEdit_monitorTiles.text().strip()
        if tile_str == 'all':
            self.img_inspector.monitoring_tile_list = ['all']
        else:
            success, tile_list = utils.validate_tile_list(tile_str)
            if success:
                self.img_inspector.monitoring_tile_list = tile_list
            else:
                error_str = 'List of selected tiles badly formatted.'

        self.img_inspector.tile_mean_threshold = (
            self.doubleSpinBox_meanThreshold.value())
        self.img_inspector.tile_stddev_threshold = (
            self.doubleSpinBox_stdDevThreshold.value())
        if not error_str:
            super().accept()
        else:
            QMessageBox.warning(self, 'Error', error_str, QMessageBox.Ok)

# ------------------------------------------------------------------------------

class AutofocusSettingsDlg(QDialog):
    """Adjust settings for the ZEISS autofocus, the heuristic autofocus,
    and tracking the focus/stig when refocusing manually.
    """
    def __init__(self, autofocus, grid_manager, magc_mode=False):
        super().__init__()
        self.autofocus = autofocus
        self.gm = grid_manager
        loadUi('..\\gui\\autofocus_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        if self.autofocus.method == 0:
            self.radioButton_useSmartSEM.setChecked(True)
        elif self.autofocus.method == 1:
            self.radioButton_useHeuristic.setChecked(True)
        elif self.autofocus.method == 2:
            self.radioButton_useTrackingOnly.setChecked(True)
        elif self.autofocus.method == 3:
            self.radioButton_useMAPFoSt.setChecked(True)
        self.radioButton_useSmartSEM.toggled.connect(self.group_box_update)
        self.radioButton_useHeuristic.toggled.connect(self.group_box_update)
        self.radioButton_useTrackingOnly.toggled.connect(self.group_box_update)
        self.radioButton_useMAPFoSt.toggled.connect(self.group_box_update)
        self.group_box_update()
        # General settings
        self.lineEdit_refTiles.setText(
            str(self.gm.autofocus_ref_tiles)[1:-1].replace('\'', ''))
        if self.autofocus.tracking_mode == 1:
            self.lineEdit_refTiles.setEnabled(False)
        self.doubleSpinBox_maxWDDiff.setValue(
            self.autofocus.max_wd_diff * 1000000)
        self.doubleSpinBox_maxStigXDiff.setValue(
            self.autofocus.max_stig_x_diff)
        self.doubleSpinBox_maxStigYDiff.setValue(
            self.autofocus.max_stig_y_diff)
        self.comboBox_trackingMode.addItems(['Track selected, approx. others',
                                             'Track all active tiles',
                                             'Average over selected',
                                             'Track selected, fit others (global)'])
        self.comboBox_trackingMode.setCurrentIndex(
            self.autofocus.tracking_mode)
        self.comboBox_trackingMode.currentIndexChanged.connect(
            self.change_tracking_mode)
        # SmartSEM autofocus
        self.spinBox_interval.setValue(self.autofocus.interval)
        self.spinBox_autostigDelay.setValue(self.autofocus.autostig_delay)
        self.doubleSpinBox_pixelSize.setValue(self.autofocus.pixel_size)
        # For heuristic autofocus:
        self.doubleSpinBox_wdDiff.setValue(
            self.autofocus.wd_delta * 1000000)
        self.doubleSpinBox_stigXDiff.setValue(
            self.autofocus.stig_x_delta)
        self.doubleSpinBox_stigYDiff.setValue(
            self.autofocus.stig_y_delta)
        self.doubleSpinBox_focusCalib.setValue(
            self.autofocus.heuristic_calibration[0])
        self.doubleSpinBox_stigXCalib.setValue(
            self.autofocus.heuristic_calibration[1])
        self.doubleSpinBox_stigYCalib.setValue(
            self.autofocus.heuristic_calibration[2])
        self.doubleSpinBox_stigRot.setValue(self.autofocus.rot_angle)
        self.doubleSpinBox_stigScale.setValue(self.autofocus.scale_factor)
        # Disable some settings if MagC mode is active
        if magc_mode:
            self.radioButton_useHeuristic.setEnabled(False)
            self.radioButton_useTrackingOnly.setEnabled(False)
            self.radioButton_useMAPFoSt.setEnabled(False)
            self.comboBox_trackingMode.setEnabled(False)
            self.spinBox_interval.setEnabled(False)
            # make autostig interval work on grids instead of slices
            self.label_fdp_4.setText('Autostig interval (grids) ')

    def group_box_update(self):
        mapfost_enabled = False
        if self.radioButton_useSmartSEM.isChecked():
            zeiss_enabled = True
            heuristic_enabled = False
            diffs_enabled = True
        elif self.radioButton_useHeuristic.isChecked():
            zeiss_enabled = False
            heuristic_enabled = True
            diffs_enabled = True
        elif self.radioButton_useTrackingOnly.isChecked():
            zeiss_enabled = False
            heuristic_enabled = False
            diffs_enabled = False
        elif self.radioButton_useMAPFoSt.isChecked():
            zeiss_enabled = True  # mapfost uses intervall and pixel size value.
            heuristic_enabled = False
            diffs_enabled = True
            mapfost_enabled = True  # TODO: add mapfost parameter group
        self.groupBox_ZEISS_af.setEnabled(zeiss_enabled)
        self.groupBox_heuristic_af.setEnabled(heuristic_enabled)
        self.doubleSpinBox_maxWDDiff.setEnabled(diffs_enabled)
        self.doubleSpinBox_maxStigXDiff.setEnabled(diffs_enabled)
        self.doubleSpinBox_maxStigYDiff.setEnabled(diffs_enabled)

    def change_tracking_mode(self):
        """Let user confirm switch to "track all"."""
        if self.comboBox_trackingMode.currentIndex() == 1:
            response = QMessageBox.information(
                self, 'Track all tiles',
                'This will select all active tiles for autofocus tracking and '
                'overwrite the current selection of reference tiles. '
                'Continue?',
                QMessageBox.Ok, QMessageBox.Cancel)
            if response == QMessageBox.Ok:
                self.lineEdit_refTiles.setText(
                    str(self.gm.active_tile_key_list())[1:-1].replace('\'', ''))
                self.lineEdit_refTiles.setEnabled(False)
            else:
                # Revert to tracking mode 0:
                self.comboBox_trackingMode.blockSignals(True)
                self.comboBox_trackingMode.setCurrentIndex(0)
                self.comboBox_trackingMode.blockSignals(False)
        else:
            self.lineEdit_refTiles.setEnabled(True)

    def accept(self):
        error_str = ''
        if self.radioButton_useSmartSEM.isChecked():
            self.autofocus.method = 0
        elif self.radioButton_useHeuristic.isChecked():
            self.autofocus.method = 1
        elif self.radioButton_useTrackingOnly.isChecked():
            self.autofocus.method = 2
        elif self.radioButton_useMAPFoSt.isChecked():
            self.autofocus.method = 3

        success, tile_list = utils.validate_tile_list(
            self.lineEdit_refTiles.text())
        if success:
            self.gm.autofocus_ref_tiles = tile_list
        else:
            error_str = 'List of selected tiles badly formatted.'
        self.autofocus.tracking_mode = (
            self.comboBox_trackingMode.currentIndex())
        self.autofocus.max_wd_diff = (
            self.doubleSpinBox_maxWDDiff.value() / 1000000)
        self.autofocus.max_stig_x_diff = (
            self.doubleSpinBox_maxStigXDiff.value())
        self.autofocus.max_stig_y_diff = (
            self.doubleSpinBox_maxStigYDiff.value())
        self.autofocus.interval = self.spinBox_interval.value()
        self.autofocus.autostig_delay = self.spinBox_autostigDelay.value()
        self.autofocus.pixel_size = self.doubleSpinBox_pixelSize.value()
        self.autofocus.wd_delta = self.doubleSpinBox_wdDiff.value() / 1000000
        self.autofocus.stig_x_delta = self.doubleSpinBox_stigXDiff.value()
        self.autofocus.stig_y_delta = self.doubleSpinBox_stigYDiff.value()
        self.autofocus.heuristic_calibration = [
            self.doubleSpinBox_focusCalib.value(),
            self.doubleSpinBox_stigXCalib.value(),
            self.doubleSpinBox_stigYCalib.value()]
        self.autofocus.rot_angle = self.doubleSpinBox_stigRot.value()
        self.autofocus.scale_factor = self.doubleSpinBox_stigScale.value()
        if not error_str:
            super().accept()
        else:
            QMessageBox.warning(self, 'Error', error_str, QMessageBox.Ok)

# ------------------------------------------------------------------------------

class RunAutofocusDlg(QDialog):
    """Run the autofocus/autostigmator or both and use method specifed by
    user (SmartSEM or MAPFoSt).
    """
    def __init__(self, autofocus, sem):
        super().__init__()
        self.autofocus = autofocus
        self.sem = sem
        self.use_autofocus = False
        self.use_autostig = False
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.autofocus_completed)
        self.new_wd_stig = None, None, None
        self.busy = False
        self.af_msg = None

        loadUi('..\\gui\\run_autofocus_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()

        self.comboBox_method.addItems(['SmartSEM', 'MAPFoSt'])
        self.comboBox_method.setCurrentIndex(0)
        self.comboBox_mode.addItems(
            ['Autofocus + stig', 'Autofocus only', 'Autostig only'])
        self.comboBox_mode.setCurrentIndex(0)

        self.pushButton_run.clicked.connect(self.run_autofocus)

    def run_autofocus(self):
        method = self.comboBox_method.currentIndex()
        mode = self.comboBox_mode.currentIndex()
        if method == 1:
            if mode != 0:
                utils.run_log_thread(f'MAPFoSt always corrects focus and stigmation.')
            try:
                utils.run_log_thread(self.call_mapfost_af_routine)
            except ImportError:
                # MAPFoSt disabled for now
                QMessageBox.information(
                    self, 'MAPFoSt',
                    'MAPFoSt Autofocus not available yet.',
                    QMessageBox.Ok)
        elif method == 0:
            if mode == 0:
                self.use_autofocus = True
                self.use_autostig = True
            elif mode == 1:
                self.use_autofocus = True
                self.use_autostig = False
            else:
                self.use_autofocus = False
                self.use_autostig = True

            self.pushButton_run.setText('Busy... please wait')
            self.pushButton_run.setEnabled(False)
            utils.run_log_thread(self.call_zeiss_af_routine)

    def call_zeiss_af_routine(self):
        self.busy = True
        self.af_msg = self.autofocus.run_zeiss_af(
            self.use_autofocus, self.use_autostig)
        self.finish_trigger.signal.emit()

    def call_mapfost_af_routine(self):
        self.busy = True
        af_kwargs = dict(defocus_arr=self.autofocus.mapfost_defocus_trials, rot=self.autofocus.rot_angle_mafpsot,
                         scale=self.autofocus.scale_factor_mapfost, na=self.autofocus.na_mapfost)
        self.af_msg = self.autofocus.run_mapfost_af(**af_kwargs)
        self.finish_trigger.signal.emit()

    def autofocus_completed(self):
        self.busy = False
        self.pushButton_run.setText('Run')
        self.pushButton_run.setEnabled(True)
        if 'ERROR' in self.af_msg:
            self.new_wd_stig = None, None, None
            QMessageBox.warning(
                self, 'SmartSEM Autofocus error',
                'An error occurred while running the SmartSEM Autofocus',
                QMessageBox.Ok)
            utils.log_error('SEM', self.af_msg)
        else:
            self.new_wd_stig = self.sem.get_wd(), *self.sem.get_stig_xy()
            QMessageBox.information(
                self, 'SmartSEM Autofocus completed',
                f'New working distance and stigmation:\n'
                f'{utils.format_wd_stig(*self.new_wd_stig)}',
                QMessageBox.Ok)
            utils.log_info('SEM', self.af_msg)
            self.accept()

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if not self.busy:
            event.accept()
        else:
            event.ignore()

# ------------------------------------------------------------------------------

class PlasmaCleanerDlg(QDialog):
    """Set parameters for the downstream asher, run it."""

    def __init__(self, plc):
        super().__init__()
        self.plc = plc
        loadUi('..\\gui\\plasma_cleaner_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('icon.ico'))
        self.setFixedSize(self.size())
        self.show()
        try:
            self.spinBox_currentPower.setValue(self.plc.get_power())
            self.spinBox_currentDuration.setValue(self.plc.get_duration())
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Could not read current settings from plasma cleaner: '
                + str(e),
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


# ------------------------------------------------------------------------------

class VariablePressureDlg(QDialog):
    """Set Variable Pressure / High Vacuum."""

    def __init__(self, sem):
        super().__init__()
        self.sem = sem
        self.hv = True
        self.vp = False
        self.target = 0
        self.current = 0
        loadUi('..\\gui\\variable_pressure_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_hv.clicked.connect(self.set_hv)
        self.pushButton_vp.clicked.connect(self.set_vp)
        self.lineEdit_target.editingFinished.connect(self.target_text_changed)
        self.horizontalSlider_target.valueChanged.connect(self.target_slider_changed)
        self.comboBox_units.currentTextChanged.connect(self.units_changed)
        self.units = self.comboBox_units.currentText()
        try:
            self.target = self.sem.get_vp_target()
            self.update_target_pressure_text()
            self.update_target_pressure_slider()
            self.thread = UpdateQThread(1)
            self.thread.update.connect(self.update)
            self.thread.start()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Could not read variable pressure settings: '
                + str(e),
                QMessageBox.Ok)
        QApplication.processEvents()

    def set_hv(self):
        try:
            self.sem.set_hv()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Unable to set hv: '
                + str(e),
                QMessageBox.Ok)

    def set_vp(self):
        try:
            self.sem.set_vp()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Unable to set vp: '
                + str(e),
                QMessageBox.Ok)

    def units_changed(self, text):
        self.units = text
        self.update_target_pressure_text()

    def update(self):
        self.hv = self.sem.is_hv_on()
        self.vp = self.sem.is_vp_on()
        self.current = self.sem.get_chamber_pressure()
        self.pushButton_hv.setEnabled(self.vp)
        self.pushButton_vp.setEnabled(self.hv)
        self.update_pressure(self.lineEdit_current, self.current)

    def update_target_pressure_text(self):
        self.lineEdit_target.blockSignals(True)
        self.update_pressure(self.lineEdit_target, self.target)
        self.lineEdit_target.blockSignals(False)

    def update_target_pressure_slider(self):
        self.horizontalSlider_target.blockSignals(True)
        self.horizontalSlider_target.setValue(math.log10(self.target) * 100)
        self.horizontalSlider_target.blockSignals(False)

    def update_pressure(self, textEdit, value):
        unit_value = value * utils.PRESSURE_FROM_SEM[self.units]
        textEdit.setText("{:.2e}".format(unit_value))

    def target_text_changed(self):
        try:
            unit_value = float(self.lineEdit_target.text())
            self.target = unit_value * utils.PRESSURE_TO_SEM[self.units]
            self.update_target_pressure_slider()
            self.sem.set_vp_target(self.target)
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Invalid value: '
                + str(e),
                QMessageBox.Ok)

    def target_slider_changed(self):
        try:
            self.target = 10 ** (self.horizontalSlider_target.value() * 0.01)
            self.update_target_pressure_text()
            self.sem.set_vp_target(self.target)
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Invalid value: '
                + str(e),
                QMessageBox.Ok)

    def reject(self):
        try:
            self.thread.stop()
        except Exception:
            pass
        super().reject()

    def closeEvent(self, event):
        try:
            self.thread.stop()
        except Exception:
            pass
        event.accept()


# ------------------------------------------------------------------------------

class ChargeCompensatorDlg(QDialog):
    """Set Charge Compensator & level."""

    def __init__(self, sem):
        super().__init__()
        self.sem = sem
        self.state = False
        self.value = 0
        self.vacuum_pressure = 0
        loadUi('..\\gui\\charge_compensator_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_on.clicked.connect(self.turn_on)
        self.pushButton_off.clicked.connect(self.turn_off)
        self.doubleSpinBox_level.valueChanged.connect(self.value_changed)
        self.horizontalSlider_level.valueChanged.connect(self.slider_changed)
        self.comboBox_units.currentTextChanged.connect(self.units_changed)
        self.units = self.comboBox_units.currentText()
        try:
            self.state = self.sem.is_fcc_on()
            self.value = self.sem.get_fcc_level()
            self.update_buttons()
            self.update_value()
            self.update_slider()
            self.thread = UpdateQThread(1)
            self.thread.update.connect(self.update)
            self.thread.start()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Could not read charge compensator settings: '
                + str(e),
                QMessageBox.Ok)
        QApplication.processEvents()

    def turn_on(self):
        try:
            self.sem.turn_fcc_on()
            sleep(0.1)
            self.set_fcc_level(self.value)
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Unable to enable fcc: '
                + str(e),
                QMessageBox.Ok)

    def turn_off(self):
        try:
            self.sem.turn_fcc_off()
            self.value = 0
            self.update_value()
            self.update_slider()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Unable to disable fcc: '
                + str(e),
                QMessageBox.Ok)

    def units_changed(self, text):
        self.units = text
        self.update_pressure()

    def update(self):
        self.state = self.sem.is_fcc_on()
        self.vacuum_pressure = self.sem.get_chamber_pressure()
        self.update_buttons()
        self.update_pressure()

    def update_pressure(self):
        unit_value = self.vacuum_pressure * utils.PRESSURE_FROM_SEM[self.units]
        self.lineEdit_vacuumPressure.setText("{:.2e}".format(unit_value))

    def update_buttons(self):
        self.pushButton_on.setEnabled(not self.state)
        self.pushButton_off.setEnabled(self.state)

    def value_changed(self, value):
        self.set_fcc_level(value)
        self.update_slider()

    def slider_changed(self):
        self.set_fcc_level(self.horizontalSlider_level.value() * 0.1)
        self.update_value()

    def update_value(self):
        self.doubleSpinBox_level.blockSignals(True)
        self.doubleSpinBox_level.setValue(self.value)
        self.doubleSpinBox_level.blockSignals(False)

    def update_slider(self):
        self.horizontalSlider_level.blockSignals(True)
        self.horizontalSlider_level.setValue(self.value * 10)
        self.horizontalSlider_level.blockSignals(False)

    def set_fcc_level(self, value):
        if not 0 <= value <= 100:
            QMessageBox.warning(
                self, 'Error',
                    'Please enter a value between 0 and 100', QMessageBox.Ok)
        else:
            self.value = value
            if self.state:
                self.sem.set_fcc_level(value)


# ------------------------------------------------------------------------------

class ApproachDlg(QDialog):
    """Remove slices without imaging. User can specify how many slices and
    the cutting thickness.
    """

    def __init__(self, microtome, main_controls_trigger):
        super().__init__()
        self.microtome = microtome
        self.main_controls_trigger = main_controls_trigger
        loadUi('..\\gui\\approach_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Set up trigger and queue to update dialog GUI during approach
        self.progress_trigger = utils.Trigger()
        self.progress_trigger.signal.connect(self.update_progress)
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.finish_approach)
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
        self.aborted = False
        self.z_mismatch = False
        self.max_slices = self.spinBox_numberSlices.value()
        # Approach cut duration for 3View. TODO: more general solution for
        # other microtomes
        self.approach_cut_duration = self.microtome.full_cut_duration - 3
        self.update_progress()

    def update_progress(self):
        self.max_slices = self.spinBox_numberSlices.value()
        if self.slice_counter > 0:
            remaining_time_str = (
                '    ' + str(int((self.max_slices - self.slice_counter)
                * self.approach_cut_duration))
                + ' seconds left')
        else:
            remaining_time_str = ''
        self.label_statusApproach.setText(str(self.slice_counter) + '/'
                                          + str(self.max_slices)
                                          + remaining_time_str)
        self.progressBar_approach.setValue(
            int(self.slice_counter/self.max_slices * 100))

    def start_approach(self):
        self.pushButton_startApproach.setEnabled(False)
        self.pushButton_abortApproach.setEnabled(True)
        self.buttonBox.setEnabled(False)
        self.spinBox_thickness.setEnabled(False)
        self.spinBox_numberSlices.setEnabled(False)
        self.main_controls_trigger.transmit('STATUS BUSY APPROACH')
        utils.run_log_thread(self.approach_thread)

    def finish_approach(self):
        # Move knife to "Clear" position
        utils.log_info('KNIFE', 'Moving to "Clear" position.')
        self.microtome.clear_knife()
        if self.microtome.error_state != Error.none:
            utils.log_error('KNIFE', 'Error moving to "Clear" position.')
            self.microtome.reset_error_state()
            QMessageBox.warning(self, 'Error',
                                'Warning: Move to "Clear" position failed. '
                                'Try to move to "Clear" position manually.',
                                QMessageBox.Ok)
        self.main_controls_trigger.transmit('STATUS IDLE')
        # Show message box to user and reset counter and progress bar
        if not self.aborted:
            QMessageBox.information(
                self, 'Approach finished',
                str(self.max_slices) + ' slices have been cut successfully. '
                'Total sample depth removed: '
                + str(self.max_slices * self.thickness / 1000) + ' µm.',
                QMessageBox.Ok)
            self.slice_counter = 0
            self.update_progress()
        elif self.z_mismatch:
            # Show warning message if Z mismatch detected
            self.microtome.reset_error_state()
            QMessageBox.warning(
                self, 'Z position mismatch',
                'The current Z position does not match the last known '
                'Z position in SBEMimage. Have you manually changed Z? '
                'Make sure that the Z position is correct before cutting.',
                QMessageBox.Ok)
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
        self.aborted = False
        self.z_mismatch = False
        self.slice_counter = 0
        self.max_slices = self.spinBox_numberSlices.value()
        self.thickness = self.spinBox_thickness.value()
        self.progress_trigger.signal.emit()
        # Get current z position of stage
        z_position = self.microtome.get_stage_z(wait_interval=1)
        if z_position is None or z_position < 0:
            # Try again
            z_position = self.microtome.get_stage_z(wait_interval=2)
            if z_position is None or z_position < 0:
                utils.log_error(
                    'STAGE',
                    'Error reading Z position. Approach aborted.')
                self.microtome.reset_error_state()
                self.aborted = True
        if self.microtome.error_state == 206:
            self.microtome.reset_error_state()
            self.z_mismatch = True
            self.aborted = True
            utils.log_error(
                'STAGE',
                'Z position mismatch. Approach aborted.')
        self.main_controls_trigger.transmit('UPDATE Z')
        if not self.aborted:
            self.microtome.near_knife()
            utils.log_info('KNIFE', 'Moving to "Near" position.')
            if self.microtome.error_state != Error.none:
                utils.log_error(
                    'KNIFE',
                    'Error moving to "Near" position. '
                    'Approach aborted.')
                self.aborted = True
                self.microtome.reset_error_state()
        # ====== Approach loop =========
        while (self.slice_counter < self.max_slices) and not self.aborted:
            # Move to new z position
            z_position = z_position + (self.thickness / 1000)
            utils.log_info(
                'STAGE',
                'Move to new Z: ' + '{0:.3f}'.format(z_position))
            self.microtome.move_stage_to_z(z_position)
            # Show new Z position in main window
            self.main_controls_trigger.transmit('UPDATE Z')
            # Check if there were microtome problems
            if self.microtome.error_state != Error.none:
                utils.log_error(
                    'STAGE',
                    'Error during Z move '
                    f'({self.microtome.error_state}). Approach aborted.')
                self.aborted = True
                self.microtome.reset_error_state()
                break
            utils.log_info('KNIFE', 'Cutting in progress ('
                            + str(self.thickness) + ' nm cutting thickness).')
            # Do the approach cut (cut, retract, in near position)
            self.microtome.do_full_approach_cut()
            sleep(self.approach_cut_duration)
            if self.microtome.error_state != Error.none:
                utils.log_error(
                    'KNIFE',
                    'Cutting problem detected. Approach aborted.')
                self.aborted = True
                self.microtome.reset_error_state()
                break
            else:
                utils.log_info('KNIFE', 'Approach cut completed.')
                self.slice_counter += 1
                # Update progress bar and slice counter
                self.progress_trigger.signal.emit()
        # ====== End of approach loop =========
        # Signal that thread is done:
        self.finish_trigger.signal.emit()

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
            super().accept()

# ------------------------------------------------------------------------------

class GrabFrameDlg(QDialog):
    """Dialog to let user acquire a single frame from the SEM at the current
    stage position.
    """

    def __init__(self, sem, acq, main_controls_trigger):
        super().__init__()
        self.sem = sem
        self.acq = acq
        self.main_controls_trigger = main_controls_trigger
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.scan_complete)
        loadUi('..\\gui\\grab_frame_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        timestamp = str(datetime.datetime.now())
        # Remove some characters from timestap to get valid file name
        timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
        self.file_name = 'image_' + timestamp
        self.lineEdit_filename.setText(self.file_name)
        store_res_list = [
            '%d × %d' % (res[0], res[1]) for res in self.sem.STORE_RES]
        self.comboBox_frameSize.addItems(store_res_list)
        self.comboBox_frameSize.setCurrentIndex(
            self.sem.grab_frame_size_selector)
        # no frame size selection with the MultiSEM
        if self.sem.device_name == 'MultiSEM':
            self.comboBox_frameSize.setEnabled(False)
        self.doubleSpinBox_pixelSize.setValue(self.sem.grab_pixel_size)
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        self.comboBox_dwellTime.setCurrentIndex(
            self.sem.DWELL_TIME.index(self.sem.grab_dwell_time))
        self.pushButton_getFromSEM.clicked.connect(self.get_settings_from_sem)
        self.pushButton_scan.clicked.connect(self.scan_frame)
        self.pushButton_save.clicked.connect(self.save_frame)

    def get_settings_from_sem(self):
        """Load current SEM settings for frame size, pixel size, and
        dwell time, and set the spin box and the combo boxes to these values.
        """
        current_frame_size_selector = self.sem.get_frame_size_selector()
        current_pixel_size = self.sem.get_pixel_size()
        current_scan_rate = self.sem.get_scan_rate()
        self.comboBox_frameSize.setCurrentIndex(current_frame_size_selector)
        self.comboBox_dwellTime.setCurrentIndex(current_scan_rate)
        self.doubleSpinBox_pixelSize.setValue(current_pixel_size)

    def file_name_already_exists(self):
        if os.path.isfile(os.path.join(
                self.acq.base_dir, self.file_name + '.tif')):
            QMessageBox.information(
                self, 'File name already exists',
                'A file with the same name already exists in the base '
                'directory. Please choose a different name.',
                QMessageBox.Ok)
            return True
        return False

    def scan_frame(self):
        """Scan and save a single frame using the current grab settings."""
        self.file_name = self.lineEdit_filename.text()
        if self.file_name_already_exists():
            return
        # Save and apply grab settings
        self.sem.grab_frame_size_selector = (
            self.comboBox_frameSize.currentIndex())
        self.sem.grab_pixel_size = self.doubleSpinBox_pixelSize.value()
        self.sem.grab_dwell_time = self.sem.DWELL_TIME[
            self.comboBox_dwellTime.currentIndex()]
        self.sem.apply_grab_settings()
        self.pushButton_scan.setText('Wait')
        self.pushButton_scan.setEnabled(False)
        self.pushButton_save.setEnabled(False)
        QApplication.processEvents()
        self.main_controls_trigger.transmit('STATUS BUSY GRAB IMAGE')
        utils.run_log_thread(self.perform_scan)

    def perform_scan(self):
        """Acquire a new frame. Executed in a thread because it may take some
        time and GUI should not freeze.
        """
        self.scan_success = self.sem.acquire_frame(
            self.acq.base_dir + '\\' + self.file_name + '.tif')
        self.finish_trigger.signal.emit()

    def scan_complete(self):
        """This function is called when the scan is complete.
        Reset the GUI and show result of grab command.
        """
        self.main_controls_trigger.transmit('STATUS IDLE')
        self.pushButton_scan.setText('Scan and grab')
        self.pushButton_scan.setEnabled(True)
        self.pushButton_save.setEnabled(True)
        if self.scan_success:
            utils.log_info('SEM', 'Single frame acquired (Grab dialog).')
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
                + self.sem.error_info,
                QMessageBox.Ok)
            self.sem.reset_error_state()

    def save_frame(self):
        """Save the image currently visible in SmartSEM."""
        self.file_name = self.lineEdit_filename.text()
        if self.file_name_already_exists():
            return
        success = self.sem.save_frame(os.path.join(
            self.acq.base_dir, self.file_name + '.tif'))
        if success:
            utils.log_info('SEM', 'Single frame saved (Grab dialog).')
            QMessageBox.information(
                self, 'Frame saved',
                'The current image shown in SmartSEM was saved as '
                + self.file_name + '.tif in the current base directory.',
                QMessageBox.Ok)
        else:
            QMessageBox.warning(
                self, 'Error',
                'An error ocurred while attempting to save the current '
                'SmartSEM image: '
                + self.sem.error_info,
                QMessageBox.Ok)
            self.sem.reset_error_state()

# ------------------------------------------------------------------------------

class EHTDlg(QDialog):
    """Show EHT status and let user switch beam on or off."""

    def __init__(self, sem):
        super().__init__()
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
        utils.run_log_thread(self.send_on_cmd_and_wait)

    def turn_off(self):
        self.pushButton_off.setEnabled(False)
        self.pushButton_off.setText('Wait')
        QApplication.processEvents()
        utils.run_log_thread(self.send_off_cmd_and_wait)

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

# ------------------------------------------------------------------------------

class FTSetParamsDlg(QDialog):
    """Read working distance and stigmation parameters from user input or
    from SmartSEM for setting WD/STIG for individual tiles/OVs in the
    focus tool.
    """

    def __init__(self, sem, current_wd, current_stig_x, current_stig_y,
                 simulation_mode=False):
        super().__init__()
        self.sem = sem
        loadUi('..\\gui\\focus_tool_set_params_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        if simulation_mode:
            self.pushButton_getFromSmartSEM.setEnabled(False)
        self.pushButton_getFromSmartSEM.clicked.connect(self.get_from_sem)
        self.pushButton_resetFocusParams.clicked.connect(self.reset)
        if current_wd is not None:
            self.doubleSpinBox_currentFocus.setValue(1000 * current_wd)
        else:
            self.doubleSpinBox_currentFocus.setValue(0)
        if current_stig_x is not None:
            self.doubleSpinBox_currentStigX.setValue(current_stig_x)
        else:
            self.doubleSpinBox_currentStigX.setValue(0)
        if current_stig_y is not None:
            self.doubleSpinBox_currentStigY.setValue(current_stig_y)
        else:
            self.doubleSpinBox_currentStigY.setValue(0)

    def get_from_sem(self):
        self.doubleSpinBox_currentFocus.setValue(1000 * self.sem.get_wd())
        self.doubleSpinBox_currentStigX.setValue(self.sem.get_stig_x())
        self.doubleSpinBox_currentStigY.setValue(self.sem.get_stig_y())

    def reset(self):
        self.doubleSpinBox_currentFocus.setValue(0)
        self.doubleSpinBox_currentStigX.setValue(0)
        self.doubleSpinBox_currentStigY.setValue(0)

    def accept(self):
        self.new_wd = self.doubleSpinBox_currentFocus.value() / 1000
        self.new_stig_x = self.doubleSpinBox_currentStigX.value()
        self.new_stig_y = self.doubleSpinBox_currentStigY.value()
        super().accept()

# ------------------------------------------------------------------------------

class FTMoveDlg(QDialog):
    """Move the stage to the selected tile or OV position."""

    def __init__(self, microtome, coordinate_system, grid_manager,
                 grid_index, tile_index, ov_index):
        super().__init__()
        self.microtome = microtome
        self.cs = coordinate_system
        self.gm = grid_manager
        self.ov_index = ov_index
        self.grid_index = grid_index
        self.tile_index = tile_index
        self.error = False
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.move_completed)
        loadUi('..\\gui\\focus_tool_move_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_move.clicked.connect(self.start_move)
        if ov_index >= 0:
            self.label_moveTarget.setText('OV ' + str(ov_index))
        elif (grid_index >= 0) and (tile_index >= 0):
            self.label_moveTarget.setText(
                'Grid: %d, Tile: %d' % (grid_index, tile_index))

    def start_move(self):
        self.error = False
        self.pushButton_move.setText('Busy... please wait.')
        self.pushButton_move.setEnabled(False)
        utils.run_log_thread(self.move_and_wait)

    def move_and_wait(self):
        # Load target coordinates
        if self.ov_index >= 0:
            stage_x, stage_y = self.ovm[self.ov_index].centre_sx_sy
        elif self.tile_index >= 0:
            stage_x, stage_y = self.gm[self.grid_index][self.tile_index].sx_sy
        # Now move the stage
        self.microtome.move_stage_to_xy((stage_x, stage_y))
        if self.microtome.error_state != Error.none:
            self.error = True
            self.microtome.reset_error_state()
        # Signal that move complete
        self.finish_trigger.signal.emit()

    def move_completed(self):
        if self.error:
            QMessageBox.warning(self, 'Error',
                'An error was detected during the move. '
                'Please try again.',
                QMessageBox.Ok)
        else:
            QMessageBox.information(self, 'Move complete',
                'The stage has been moved to the selected position. '
                'The Viewport will be updated after pressing OK.',
                QMessageBox.Ok)
            super().accept()
        # Enable button again
        self.pushButton_move.setText('Move again')
        self.pushButton_move.setEnabled(True)

# ------------------------------------------------------------------------------

class MotorTestDlg(QDialog):
    """Perform a random-walk-like XYZ motor test. Experimental, only for
    testing/debugging. Only works with a microtome for now."""

    def __init__(self, microtome, acq, main_controls_trigger):
        super().__init__()
        self.microtome = microtome
        self.acq = acq
        self.main_controls_trigger = main_controls_trigger
        loadUi('..\\gui\\motor_test_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        # Set up trigger and queue to update dialog GUI during approach
        self.progress_trigger = utils.Trigger()
        self.progress_trigger.signal.connect(self.update_progress)
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.test_finished)
        self.spinBox_duration.setRange(1, 9999)
        self.spinBox_duration.setSingleStep(10)
        self.spinBox_duration.setValue(10)
        self.pushButton_startTest.clicked.connect(self.start_random_walk)
        self.pushButton_abortTest.clicked.connect(self.abort_random_walk)
        if self.microtome is None:
            QMessageBox.information(
                self, 'Only for microtome stage testing',
                'This test dialog can currently only be used '
                'for testing a microtome stage.',
                QMessageBox.Ok)
            self.pushButton_startTest.setEnabled(False)
        else:
            self.pushButton_startTest.setEnabled(True)
        self.pushButton_abortTest.setEnabled(False)
        self.test_in_progress = False
        self.start_time = None

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
        self.pushButton_startTest.setText('Wait')
        self.pushButton_startTest.setEnabled(False)
        # First make sure the knife is in "Clear" position
        utils.log_info('KNIFE', 'Moving to "Clear" position.')
        QApplication.processEvents()
        self.microtome.clear_knife()
        if self.microtome.error_state != Error.none:
            utils.log_error('KNIFE', 'Error moving to "Clear" position.')
            self.microtome.reset_error_state()
            self.pushButton_startTest.setText('Start')
            self.pushButton_startTest.setEnabled(True)
            QMessageBox.warning(self, 'Error',
                                'Warning: Move to "Clear" position failed. '
                                'Try to move to "Clear" position manually.',
                                QMessageBox.Ok)
        else:
            self.start_z = self.microtome.get_stage_z()
            if self.start_z is not None:
                utils.log_info('CTRL', 'Motor test started.')
                self.pushButton_startTest.setText('Busy')
                self.pushButton_abortTest.setEnabled(True)
                self.buttonBox.setEnabled(False)
                self.checkBox_XYonly.setEnabled(False)
                self.spinBox_duration.setEnabled(False)
                self.progressBar.setValue(0)
                utils.run_log_thread(self.random_walk_thread)
            else:
                self.microtome.reset_error_state()
                self.pushButton_startTest.setText('Start')
                self.pushButton_startTest.setEnabled(True)
                QMessageBox.warning(self, 'Error',
                    'Could not read current z stage position',
                    QMessageBox.Ok)

    def abort_random_walk(self):
        self.aborted = True
        self.test_in_progress = False

    def test_finished(self):
        utils.log_info('CTRL', 'Motor test finished.')
        utils.log_info('STAGE', 'Moving back to starting Z position.')
        # Safe mode must be set to false because diff likely > 200 nm
        self.microtome.move_stage_to_z(self.start_z, safe_mode=False)
        if self.microtome.error_state != Error.none:
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
                + '\nPlease make sure that the z coordinate is back at '
                'starting position ' + str(self.start_z) + '.',
                QMessageBox.Ok)
        else:
            QMessageBox.information(
                self, 'Test complete',
                'Motor test complete.\nA total of '
                + str(self.number_moves) + ' moves were performed.\n'
                'Number of X motor errors: ' + str(self.number_errors_x)
                + '; Number of Y motor errors: ' + str(self.number_errors_y)
                + '; Number of Z motor errors: ' + str(self.number_errors_z)
                + '\nPlease make sure that the Z coordinate is back at '
                'starting position ' + str(self.start_z) + '.',
                QMessageBox.Ok)
        self.pushButton_startTest.setText('Start')
        self.pushButton_startTest.setEnabled(True)
        self.pushButton_abortTest.setEnabled(False)
        self.checkBox_XYonly.setEnabled(True)
        self.buttonBox.setEnabled(True)
        self.spinBox_duration.setEnabled(True)
        self.test_in_progress = False

    def random_walk_thread(self):
        self.test_in_progress = True
        self.duration = self.spinBox_duration.value()
        self.use_z_moves = not self.checkBox_XYonly.isChecked()
        self.start_time = time()
        self.progress_trigger.signal.emit()
        self.number_moves = 0
        self.number_errors_x = 0
        self.number_errors_y = 0
        self.number_errors_z = 0
        current_x, current_y = 0, 0
        current_z = self.start_z
        timestamp = str(datetime.datetime.now())
        timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
        # Open log file
        logfile = open(os.path.join(self.acq.base_dir,
                       'motor_test_log_' + timestamp + '.txt'),
                       'w', buffering=1)
        if not self.use_z_moves:
            logfile.write('Z motor will not be used during this test.\n\n')
        while self.test_in_progress:
            # Start 'random' walk
            if self.number_moves % 36 == 0:
                dist = 400  # longer move every 36th move
            else:
                dist = 80
            current_x += (random() - 0.5) * dist
            current_y += (random() - 0.5) * dist
            if self.use_z_moves:
                if self.number_moves % 6 == 0:
                    current_z += (random() - 0.5) * 0.2
                else:
                    current_z += 0.025
                if current_z < 1:
                    # At Z below 1 micron, Z motor appears imprecise in general
                    current_z = 1
            # If end of permissable range is reached, go back to starting point
            if (current_x < self.microtome.stage_limits[0]
                or current_x > self.microtome.stage_limits[1]
                or current_y < self.microtome.stage_limits[2]
                or current_y > self.microtome.stage_limits[3]
                or current_z > 600):
                current_x, current_y = 0, 0
                current_z = self.start_z
            logfile.write('Move to: {0:.3f}, '.format(current_x)
                          + '{0:.3f}, '.format(current_y)
                          + '{0:.3f}'.format(current_z) + '\n')
            self.microtome.move_stage_to_xy((current_x, current_y))
            self.number_moves += 2
            if self.microtome.error_state != Error.none:
                mismatch_x = self.microtome.last_known_x - current_x
                mismatch_y = self.microtome.last_known_y - current_y
                logfile.write('ERROR DURING XY MOVE: '
                              + self.microtome.error_info
                              + '; mismatch X: '
                              + '{0:.3f}'.format(mismatch_x)
                              + ', mismatch Y:'
                              + '{0:.3f}'.format(mismatch_y)
                              + '\n')
                self.microtome.reset_error_state()
                if abs(mismatch_x) > self.microtome.xy_tolerance:
                    self.number_errors_x += 1
                if abs(mismatch_y) > self.microtome.xy_tolerance:
                    self.number_errors_y += 1
            else:
                logfile.write('OK (XY)\n')

            if self.use_z_moves:
                self.microtome.move_stage_to_z(current_z, safe_mode=False)
                self.number_moves += 1
                if self.microtome.error_state != Error.none:
                    self.number_errors_z += 1
                    logfile.write('ERROR DURING Z MOVE: '
                                  + self.microtome.error_info
                                  + '; last known Z: '
                                  + str(self.microtome.last_known_z)
                                  + '\n')
                    self.microtome.reset_error_state()
                else:
                    logfile.write('OK (Z)\n')
            sleep(1)
            self.progress_trigger.signal.emit()
        logfile.write('\nNUMBER OF MOVES: ' + str(self.number_moves))
        logfile.write('\nNUMBER OF X ERRORS: ' + str(self.number_errors_x))
        logfile.write('\nNUMBER OF Y ERRORS: ' + str(self.number_errors_y))
        if self.use_z_moves:
            logfile.write('\nNUMBER OF Z ERRORS: ' + str(self.number_errors_z))
        logfile.close()
        # Signal that thread is done
        self.finish_trigger.signal.emit()

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
            super().accept()

# ------------------------------------------------------------------------------

class SendCommandDlg(QDialog):
    """Send a command to DM (for testing purposes)."""

    def __init__(self, microtome):
        super().__init__()
        self.microtome = microtome
        loadUi('..\\gui\\send_dm_command_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_sendCommand.clicked.connect(self.send_command)
        self.pushButton_checkResponse.clicked.connect(self.check_response)
        self.comboBox_command.addItems(
            ['Handshake',
             'MicrotomeStage_Cut',
             'MicrotomeStage_Retract',
             'MicrotomeStage_Clear',
             'MicrotomeStage_Near',
             'MicrotomeStage_FullCut',
             'MicrotomeStage_FullApproachCut',
             'MicrotomeStage_GetPositionX',
             'MicrotomeStage_GetPositionY',
             'MicrotomeStage_GetPositionXY',
             'MicrotomeStage_GetPositionZ',
             'MicrotomeStage_SetPositionX',
             'MicrotomeStage_SetPositionY',
             'MicrotomeStage_SetPositionXY',
             'MicrotomeStage_SetPositionXY_Confirm',
             'MicrotomeStage_SetPositionZ',
             'MicrotomeStage_SetPositionZ_Confirm',
             'SetMotorSpeedXY',
             'MeasureMotorSpeedXY',
             'StopScript'])
        self.comboBox_command.setEditable(True)

    def send_command(self):
        """Read the command string and the two parameters from the GUI elements
        and send them to DigitalMicrograph.
        """
        cmd = self.comboBox_command.currentText()
        param1 = self.doubleSpinBox_param1.value()
        param2 = self.doubleSpinBox_param2.value()

        # For some commands, ask for confirmation (for safety reasons)
        if cmd in ['MicrotomeStage_Cut', 'MicrotomeStage_Near',
                   'MicrotomeStage_FullCut', 'MicrotomeStage_FullApproachCut',
                   'MicrotomeStage_SetPositionZ',
                   'MicrotomeStage_SetPositionZ_Confirm', 'SetMotorSpeedXY']:
            user_reply = QMessageBox.question(
                self, 'Send command to DM',
                    f'Please confirm that you want to send the command {cmd} '
                    f'to the DigitalMicrograph script.',
                    QMessageBox.Ok | QMessageBox.Cancel)
            if user_reply == QMessageBox.Cancel:
                return

        # Clear output text field
        self.plainTextEdit_scriptResponse.setPlainText('')
        if (cmd.startswith('MicrotomeStage_SetPosition') or
                cmd.startswith('SetMotorSpeed')):
            self.microtome._send_dm_command(cmd, [param1, param2])
        else:
            self.microtome._send_dm_command(cmd)
        sleep(0.5)

    def check_response(self):
        """Read the output file DMcom.out and display its contents. Check for
        the existence of the other signal files.
        """
        if os.path.isfile(self.microtome.OUTPUT_FILE):
            return_values = self.microtome._read_dm_return_values()
        else:
            return_values = 'No output file generated'
        script_response = 'DMcom.out: ' + str(return_values) + '\n'
        # Check files
        if os.path.isfile(self.microtome.ACK_FILE):
            script_response += (
                'Command execution confirmed: '
                + self.microtome.ACK_FILE + '\n')
        if os.path.isfile(self.microtome.ACK_CUT_FILE):
            script_response += (
                'Cut execution confirmed: '
                + self.microtome.ACK_CUT_FILE + '\n')
        if os.path.isfile(self.microtome.WARNING_FILE):
            script_response += (
                'Warning: ' + self.microtome.WARNING_FILE + '\n')
        if os.path.isfile(self.microtome.ERROR_FILE):
            script_response += (
                'Error: ' + self.microtome.ERROR_FILE + '\n')
        # Error state
        script_response += (f'Error state: {self.microtome.error_state} '
                            f'{self.microtome.error_info}')
        # Display in GUI
        self.plainTextEdit_scriptResponse.setPlainText(script_response)
        self.microtome.reset_error_state()

# ------------------------------------------------------------------------------

class AboutBox(QDialog):
    """Show the About dialog box with info about SBEMimage and the current
    version and release date.
    """

    def __init__(self, VERSION):
        super().__init__()
        loadUi('..\\gui\\about_box.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        if 'dev' in VERSION.lower():
            self.label_version.setText(f'DEVELOPMENT VERSION ({VERSION})')
        else:
            self.label_version.setText('Version ' + VERSION)
        self.labelIcon.setPixmap(QPixmap('..\\img\\logo.png'))
        # Enable links to readthedocs and GitHub
        self.label_readthedocs.setText('<a href="https://sbemimage.readthedocs.io">'
                                       'https://sbemimage.readthedocs.io</a>')
        self.label_readthedocs.setOpenExternalLinks(True)
        self.label_github.setText('<a href="https://github.com/SBEMimage">'
                                  'https://github.com/SBEMimage</a>')
        self.label_github.setOpenExternalLinks(True)
        self.setFixedSize(self.size())
        self.show()
