# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module contains MainControls, the main window of the application, from
which the acquisition thread is started.

The 'Main Controls' window consists of four tabs:
    (1) Main controls: action buttons, settings, stack progress and main log;
    (2) Focus tool;
    (3) Functions for testing/debugging;
    (4) MagC module.

The 'Main Controls' window is a QMainWindow, and it launches the Viewport
window (in viewport.py) as a QWidget.
"""
import os
import sys
import threading
import json

from time import sleep

from PyQt5.QtWidgets import QApplication, QTableWidgetSelectionRange, \
                            QAbstractItemView, QPushButton
from PyQt5.QtCore import Qt, QRect, QSize, QEvent, QItemSelection, \
                         QItemSelectionModel, QModelIndex
from PyQt5.QtGui import QIcon, QPalette, QColor, QPixmap, QKeyEvent, \
                        QStatusTipEvent, QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QInputDialog, QLineEdit, \
                            QHeaderView
from PyQt5.uic import loadUi

import acq_func
import utils
from utils import Error
from sem_control_zeiss import SEM_SmartSEM
from sem_control_fei import SEM_Quanta
from microtome_control_gatan import Microtome_3View
from microtome_control_katana import Microtome_katana
from microtome_control_gcib import GCIB
from stage import Stage
from plasma_cleaner import PlasmaCleaner
from acquisition import Acquisition
from notifications import Notifications
from overview_manager import OverviewManager
from imported_img import ImportedImages
from grid_manager import GridManager
from coordinate_system import CoordinateSystem
from viewport import Viewport
from image_inspector import ImageInspector
from autofocus import Autofocus
from main_controls_dlg_windows import SEMSettingsDlg, MicrotomeSettingsDlg, \
                                      GridSettingsDlg, OVSettingsDlg, \
                                      AcqSettingsDlg, PreStackDlg, PauseDlg, \
                                      AutofocusSettingsDlg, DebrisSettingsDlg, \
                                      EmailMonitoringSettingsDlg, \
                                      ImageMonitoringSettingsDlg, ExportDlg, \
                                      SaveConfigDlg, PlasmaCleanerDlg, \
                                      VariablePressureDlg, ChargeCompensatorDlg, \
                                      ApproachDlg, MirrorDriveDlg, EHTDlg, \
                                      StageCalibrationDlg, MagCalibrationDlg, \
                                      GrabFrameDlg, FTSetParamsDlg, FTMoveDlg, \
                                      AskUserDlg, UpdateDlg, CutDurationDlg, \
                                      KatanaSettingsDlg, SendCommandDlg, \
                                      MotorTestDlg, MotorStatusDlg, AboutBox, GCIBSettingsDlg

from magc_dlg_windows import ImportMagCDlg, ImportWaferImageDlg, \
                          WaferCalibrationDlg


class MainControls(QMainWindow):

    def __init__(self, config, sysconfig, config_file, VERSION):
        super().__init__()
        self.cfg = config
        self.syscfg = sysconfig
        self.cfg_file = config_file
        self.syscfg_file = self.cfg['sys']['sys_config_file']
        self.VERSION = VERSION
    
        # Show progress bar in console during start-up. The percentages are
        # just estimates, but helpful for user to see that initialization
        # is in progress.
        utils.show_progress_in_console(0)

        # Set up the main control variables
        self.busy = False
        self.simulation_mode = (
            self.cfg['sys']['simulation_mode'].lower() == 'true')
        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')
        self.use_microtome = (
            self.cfg['sys']['use_microtome'].lower() == 'true')
        self.statusbar_msg = ''

        # If workspace folder does not exist, create it.
        workspace_dir = os.path.join(self.cfg['acq']['base_dir'], 'workspace')
        if not os.path.exists(workspace_dir):
            self.try_to_create_directory(workspace_dir)

        # Current OV and grid indices selected from dropdown list,
        # displayed in Main Controls GUI.
        self.ov_index_dropdown = 0
        self.grid_index_dropdown = 0

        # Set up trigger and queue to update Main Controls from the
        # acquisition thread or dialog windows.
        self.trigger = utils.Trigger()
        self.trigger.signal.connect(self.process_signal)

        utils.show_progress_in_console(10)

        # Initialize SEM
        if self.syscfg['device']['sem'] in ['1', '2', '3', '4']:  # ZEISS SEMs
            # Create SEM instance to control SEM via SmartSEM API
            self.sem = SEM_SmartSEM(self.cfg, self.syscfg)
            if self.sem.error_state != Error.none:
                QMessageBox.warning(
                    self, 'Error initializing SmartSEM Remote API',
                    'initialisation of the SmartSEM Remote API failed. Please '
                    'verify that the Remote API is installed and configured '
                    'correctly.'
                    '\nSBEMimage will be run in simulation mode.',
                    QMessageBox.Ok)
                self.simulation_mode = True
        else:
            # No other SEMs supported at the moment
            self.sem = None
            utils.log_warning(
                'SEM', 'No SEM found, or incompatible SEM selected.')
            QMessageBox.warning(
                self, 'No SEM found',
                'No SEM was found, or an incompatible SEM was selected. '
                'Check your system configuration file.'
                '\nSBEMimage will be run in simulation mode.',
                QMessageBox.Ok)
            self.simulation_mode = True

        utils.show_progress_in_console(20)

        # Initialize coordinate system object
        self.cs = CoordinateSystem(self.cfg, self.syscfg)

        # Set up the objects to manage overviews, grids, and imported images
        self.ovm = OverviewManager(self.cfg, self.sem, self.cs)
        self.gm = GridManager(self.cfg, self.sem, self.cs)
        self.imported = ImportedImages(self.cfg)

        # Notify user if imported images could not be loaded
        for i in range(self.imported.number_imported):
            if self.imported[i].image is None:
                QMessageBox.warning(self, 'Error loading imported image',
                                          f'Imported image number {i} could not '
                                          f'be loaded. Check if the folder containing '
                                          f'the image ({self.imported[i].image_src}) was deleted or '
                                          f'moved, or if the image file is damaged or in '
                                          f'the wrong format.', QMessageBox.Ok)
                utils.log_error(
                    'CTRL', f'Error loading imported image {i}')

        utils.show_progress_in_console(30)

        # Initialize microtome
        if self.use_microtome and (self.syscfg['device']['microtome'] == '0'):
            # Create object for 3View microtome (control via DigitalMicrograph)
            self.microtome = Microtome_3View(self.cfg, self.syscfg)
            if self.microtome.error_state in [Error.dm_init, Error.dm_comm_send, Error.dm_comm_response, Error.dm_comm_retval]:
                utils.log_warning('CTRL', 'Error initializing DigitalMicrograph API')
                QMessageBox.warning(
                    self, 'Error initializing DigitalMicrograph API',
                    'Have you forgotten to start the communication '
                    'script in DM? \nIf yes, please load the '
                    'script and click "Execute".'
                    '\n\nIs the Z coordinate negative? \nIf yes, '
                    'please set it to zero or a positive value.',
                    QMessageBox.Retry)
                # Try again
                self.microtome = Microtome_3View(self.cfg, self.syscfg)
                if self.microtome.error_state in [Error.dm_init, Error.dm_comm_send, Error.dm_comm_response, Error.dm_comm_retval]:
                    utils.log_error('CTRL', 'Error initializing DigitalMicrograph API')
                    QMessageBox.warning(
                        self, 'Error initializing DigitalMicrograph API',
                        'The second attempt to initialise the DigitalMicrograph '
                        'API failed.\nSBEMimage will be run in simulation '
                        'mode.',
                        QMessageBox.Ok)
                    self.simulation_mode = True
                else:
                    utils.log_info(
                        'CTRL',
                        'Second attempt to initialize '
                        'DigitalMicrograph API successful.')
        elif self.use_microtome and (self.syscfg['device']['microtome'] == '5'):
            # Initialize katana microtome
            self.microtome = Microtome_katana(self.cfg, self.syscfg)
        elif self.use_microtome and (self.syscfg['device']['microtome'] == '6'):
            self.microtome = GCIB(self.cfg, self.syscfg, self.sem)
        else:
            # Otherwise use SEM stage
            self.microtome = None

        if self.microtome is not None and self.microtome.error_state == Error.configuration:
            QMessageBox.warning(
                self, 'Error loading microtome configuration',
                'While loading the microtome settings SBEMimage encountered '
                'the following error: \n'
                + self.microtome.error_info
                + '\nPlease inspect the configuration file(s). SBEMimage will '
                'be closed.',
                QMessageBox.Ok)
            self.close()

        utils.show_progress_in_console(60)

        # Initialize the stage object to control either the microtome
        # or SEM stage
        self.stage = Stage(self.sem, self.microtome,
                           self.use_microtome)

        self.img_inspector = ImageInspector(self.cfg, self.ovm, self.gm)

        self.autofocus = Autofocus(self.cfg, self.sem, self.gm)

        self.notifications = Notifications(self.cfg, self.syscfg, self.trigger)

        self.acq = Acquisition(self.cfg, self.syscfg,
                               self.sem, self.microtome, self.stage,
                               self.ovm, self.gm, self.cs, self.img_inspector,
                               self.autofocus, self.notifications, self.trigger)
        # enable pause while milling
        if self.use_microtome and (self.syscfg['device']['microtome'] == '6'):
            self.microtome.acq = self.acq
        # Check if plasma cleaner is installed and load its COM port.
        self.cfg['sys']['plc_installed'] = self.syscfg['plc']['installed']
        self.cfg['sys']['plc_com_port'] = self.syscfg['plc']['com_port']
        self.plc_installed = (
            self.cfg['sys']['plc_installed'].lower() == 'true')
        self.plc_initialized = False

        # Check if VP and FCC installed
        self.cfg['sys']['vp_installed'] = self.syscfg['vp']['installed']
        if self.syscfg['vp']['installed'].lower() == 'true':
            self.vp_installed = self.sem.has_vp()
        else:
            self.vp_installed = False
        self.fcc_installed = self.sem.has_fcc()

        self.initialize_main_controls_gui()

        # Set up grid/tile selectors.
        self.update_main_controls_grid_selector()
        self.update_main_controls_ov_selector()

        # Display current settings and stage position in Main Controls Window.
        self.show_current_settings()
        self.show_current_stage_xy()
        self.show_current_stage_z()

        # Show estimates for stack acquisition
        self.show_stack_acq_estimates()

        # Restrict GUI (microtome-specific functionality) if no microtome used
        if not self.use_microtome or self.syscfg['device']['microtome'] == '6':
            self.restrict_gui_for_sem_stage()

        if self.syscfg['device']['microtome'] != '6':
            self.restrict_gui_wo_gcib()

        # Now show main window:
        self.show()
        QApplication.processEvents()

        utils.show_progress_in_console(80)

        # First log messages
        utils.log_info('CTRL', 'SBEMimage Version ' + self.VERSION)

        # Initialize viewport window
        self.viewport = Viewport(self.cfg, self.sem, self.stage, self.cs,
                                 self.ovm, self.gm, self.imported,
                                 self.autofocus, self.acq, self.img_inspector,
                                 self.trigger)
        self.viewport.show()

        # Draw the viewport canvas
        self.viewport.vp_draw()

        # Initialize focus tool
        self.ft_initialize()

        # When simulation mode active, disable all acquisition-related functions
        if self.simulation_mode:
            self.restrict_gui_for_simulation_mode()
        else:
            self.actionLeaveSimulationMode.setEnabled(False)

        # Check if there is a previous acquisition to be be restarted.
        if self.acq.acq_paused:
            self.show_stack_progress()
            self.pushButton_startAcq.setText('CONTINUE')
            self.pushButton_resetAcq.setEnabled(True)

        # *** for debugging ***
        #self.restrict_gui(False)

        utils.show_progress_in_console(100)

        print('\n\nReady.\n')
        self.set_statusbar('Ready.')

        if self.simulation_mode:
            utils.log_warning('CTRL', 'Simulation mode active.')
            QMessageBox.information(
                self, 'Simulation mode active',
                'SBEMimage is running in simulation mode. You can change most '
                'settings and use the Viewport, but no commands can be sent '
                'to the SEM and the microtome. Stack acquisition is '
                'deactivated.'
                '\n\nTo leave simulation mode, select: '
                '\nMenu  →  Configuration  →  Leave simulation mode',
                QMessageBox.Ok)
        elif not self.cs.calibration_found:
            QMessageBox.warning(
                self, 'Missing stage calibration',
                'No stage calibration settings were found for the currently '
                'selected EHT. Please calibrate the stage:'
                '\nMenu  →  Calibration  →  Stage calibration',
                QMessageBox.Ok)
        # Diplay warning if z coordinate differs from previous session
        if self.use_microtome and self.microtome.error_state == Error.mismatch_z:
            self.microtome.reset_error_state()
            QMessageBox.warning(
                self, 'Stage Z position',
                'The current Z position does not match the Z position '
                'recorded in the current configuration file '
                '({0:.3f}).'.format(self.microtome.stage_z_prev_session)
                + ' Please make sure that the Z position is correct.',
                QMessageBox.Ok)

        # If user has selected the default.ini configuration, provide some
        # guidance
        if self.cfg_file == 'default.ini':
            # Check how many .cfg files exist
            cfgfile_counter = 0
            for file in os.listdir('..\\cfg'):
                if file.endswith('.cfg'):
                    cfgfile_counter += 1
            if cfgfile_counter > 1:
                # Explain that default.ini will use the default system
                # configuration.
                QMessageBox.warning(
                    self, 'Default user and system configuration',
                    'You have selected default.ini to load SBEMimage, but '
                    'there is at least one custom system configuration file '
                    'available for this installation.\nPlease note that '
                    'default.ini will use the unmodified default system '
                    'configuration (system.cfg), which will probably not work '
                    'for your setup.'
                    '\n\nIf you want to create new user configuration files, '
                    'you should first load a configuration other than '
                    'default.ini.',
                    QMessageBox.Ok)
            elif self.simulation_mode:
                # Show welcome message if SBEMimage is started with default.ini
                # in simulation mode and no custom system configuration exists.
                QMessageBox.information(
                    self, 'Welcome to SBEMimage',
                    'You can explore the user interface in simulation mode. If you '
                    'want to get started with using SBEMimage on your '
                    'SEM/microtome setup, save the current configuration '
                    'under a new name. This will create a new custom user '
                    'configuration file and a system configuration file:\n'
                    'Menu  →  Configuration  →  Save as new configuration file'
                    '\n\nThen leave the simulation mode:\n'
                    'Menu  →  Configuration  →  Leave simulation mode'
                    '\nRestart SBEMimage and load your new configuration file.'
                    '\n\nFollow the instructions in the user guide '
                    '(sbemimage.readthedocs.io) to calibrate your setup.',
                    QMessageBox.Ok)

    def initialize_main_controls_gui(self):
        """Load and set up the Main Controls GUI"""
        loadUi('..\\gui\\main_window.ui', self)
        if self.VERSION.lower() == 'dev':
            self.setWindowTitle(
                'SBEMimage - Main Controls - DEVELOPMENT VERSION')
            # Disable 'Update' function (would overwrite current (local) changes
            # in the code of the development version with the current version
            # in the master branch.)
            self.actionUpdate.setEnabled(False)
        else:
            self.setWindowTitle('SBEMimage - Main Controls')

        app_icon = QIcon()
        app_icon.addFile('..\\img\\icon_16px.ico', QSize(16, 16))
        app_icon.addFile('..\\img\\icon_48px.ico', QSize(48, 48))
        self.setWindowIcon(app_icon)
        #self.setFixedSize(self.size())
        self.move(1120, 20)
        self.hide() # hide window until fully initialized
        # Connect text area to logging
        utils.set_log_text_handler(self.textarea_log)
        # Pushbuttons
        self.pushButton_SEMSettings.clicked.connect(self.open_sem_dlg)
        self.pushButton_SEMSettings.setIcon(QIcon('..\\img\\settings.png'))
        self.pushButton_SEMSettings.setIconSize(QSize(16, 16))
        self.pushButton_microtomeSettings.clicked.connect(
            self.open_microtome_dlg)
        self.pushButton_microtomeSettings.setIcon(
            QIcon('..\\img\\settings.png'))
        self.pushButton_microtomeSettings.setIconSize(QSize(16, 16))
        self.pushButton_gridSettings.clicked.connect(
            lambda: self.open_grid_dlg(self.grid_index_dropdown))
        self.pushButton_gridSettings.setIcon(QIcon('..\\img\\settings.png'))
        self.pushButton_gridSettings.setIconSize(QSize(16, 16))
        self.pushButton_OVSettings.setIcon(QIcon('..\\img\\settings.png'))
        self.pushButton_OVSettings.setIconSize(QSize(16, 16))
        self.pushButton_OVSettings.clicked.connect(self.open_ov_dlg)
        self.pushButton_acqSettings.clicked.connect(
            self.open_acq_settings_dlg)
        self.pushButton_acqSettings.setIcon(QIcon('..\\img\\settings.png'))
        self.pushButton_acqSettings.setIconSize(QSize(16, 16))
        # Command buttons
        self.pushButton_doApproach.clicked.connect(self.open_approach_dlg)
        self.pushButton_doSweep.clicked.connect(self.manual_sweep)
        self.pushButton_grabFrame.clicked.connect(self.open_grab_frame_dlg)
        self.pushButton_saveViewport.clicked.connect(
            self.save_viewport_screenshot)
        self.pushButton_VP.clicked.connect(
            self.open_variable_pressure_dlg)
        self.pushButton_FCC.clicked.connect(
            self.open_charge_compensator_dlg)
        self.pushButton_EHTToggle.clicked.connect(self.open_eht_dlg)
        # Acquisition control buttons
        self.pushButton_startAcq.clicked.connect(self.open_pre_stack_dlg)
        self.pushButton_pauseAcq.clicked.connect(self.pause_acquisition)
        self.pushButton_resetAcq.clicked.connect(self.reset_acquisition)
        # Tool buttons for acquisition options
        self.toolButton_monitoringSettings.clicked.connect(
            self.open_email_monitoring_dlg)
        self.toolButton_OVSettings.clicked.connect(self.open_ov_dlg)
        self.toolButton_debrisDetection.clicked.connect(self.open_debris_dlg)
        self.toolButton_mirrorDrive.clicked.connect(
            self.open_mirror_drive_dlg)
        self.toolButton_monitorTiles.clicked.connect(
            self.open_image_monitoring_dlg)
        self.toolButton_autofocus.clicked.connect(self.open_autofocus_dlg)
        self.toolButton_plasmaCleaner.clicked.connect(
            self.initialize_plasma_cleaner)
        self.toolButton_askUserMode.clicked.connect(self.open_ask_user_dlg)
        # Menu bar
        self.actionSEMSettings.triggered.connect(self.open_sem_dlg)
        self.actionMicrotomeSettings.triggered.connect(self.open_microtome_dlg)
        self.actionGridSettings.triggered.connect(
            lambda: self.open_grid_dlg(self.grid_index_dropdown))
        self.actionAcquisitionSettings.triggered.connect(
            self.open_acq_settings_dlg)
        self.actionMonitoringSettings.triggered.connect(
            self.open_email_monitoring_dlg)
        self.actionOverviewSettings.triggered.connect(self.open_ov_dlg)
        self.actionDebrisDetectionSettings.triggered.connect(
            self.open_debris_dlg)
        self.actionAskUserModeSettings.triggered.connect(
            self.open_ask_user_dlg)
        self.actionDiskMirroringSettings.triggered.connect(
            self.open_mirror_drive_dlg)
        self.actionTileMonitoringSettings.triggered.connect(
            self.open_image_monitoring_dlg)
        self.actionAutofocusSettings.triggered.connect(self.open_autofocus_dlg)
        self.actionPlasmaCleanerSettings.triggered.connect(
            self.initialize_plasma_cleaner)
        self.actionVariablePressureSettings.triggered.connect(
            self.open_variable_pressure_dlg)
        self.actionChargeCompensatorSettings.triggered.connect(
            self.open_charge_compensator_dlg)
        self.actionSaveConfig.triggered.connect(self.save_settings)
        self.actionSaveNewConfig.triggered.connect(
            self.open_save_settings_new_file_dlg)
        self.actionLeaveSimulationMode.triggered.connect(
            self.leave_simulation_mode)
        self.actionAboutBox.triggered.connect(self.open_about_box)
        self.actionStageCalibration.triggered.connect(
            self.open_calibration_dlg)
        self.actionMagnificationCalibration.triggered.connect(
            self.open_mag_calibration_dlg)
        self.actionCutDuration.triggered.connect(
            self.open_cut_duration_dlg)
        self.actionExport.triggered.connect(self.open_export_dlg)
        self.actionUpdate.triggered.connect(self.open_update_dlg)
        # Buttons for testing purposes (third tab)
        self.pushButton_testGetMag.clicked.connect(self.test_get_mag)
        self.pushButton_testSetMag.clicked.connect(self.test_set_mag)
        self.pushButton_testGetFocus.clicked.connect(self.test_get_wd)
        self.pushButton_testSetFocus.clicked.connect(self.test_set_wd)
        self.pushButton_testRunAutofocus.clicked.connect(self.test_autofocus)
        self.pushButton_testRunAutostig.clicked.connect(self.test_autostig)
        self.pushButton_testRunAutofocusStig.clicked.connect(self.test_autofocus_stig)
        self.pushButton_testRunAutofocusMapfost.clicked.connect(self.test_autofocus_mapfost)
        self.pushButton_testZeissAPIVersion.clicked.connect(
            self.test_zeiss_api_version)
        self.pushButton_testGetStage.clicked.connect(self.test_get_stage)
        self.pushButton_testSetStage.clicked.connect(self.test_set_stage)
        self.pushButton_testNearKnife.clicked.connect(self.test_near_knife)
        self.pushButton_testClearKnife.clicked.connect(self.test_clear_knife)
        self.pushButton_testGetMillPos.clicked.connect(self.test_get_mill_pos)
        self.pushButton_testMoveMillPos.clicked.connect(self.test_set_mill_pos)
        self.pushButton_testMovePriorMillPos.clicked.connect(self.test_set_pos_prior_mill_mov)
        self.pushButton_testSendCommand.clicked.connect(
            self.open_send_command_dlg)
        self.pushButton_testStopDMScript.clicked.connect(
            self.test_stop_dm_script)
        self.pushButton_testSendEMail.clicked.connect(self.test_send_email)
        self.pushButton_testPlasmaCleaner.clicked.connect(
            self.test_plasma_cleaner)
        self.pushButton_testServerRequest.clicked.connect(
            self.test_server_request)
        self.pushButton_testMotors.clicked.connect(self.open_motor_test_dlg)
        self.pushButton_testMotorStatusDlg.clicked.connect(
            self.open_motor_status_dlg)
        self.pushButton_testDebrisDetection.clicked.connect(
            self.debris_detection_test)
        self.pushButton_testCustom.clicked.connect(self.custom_test)
        # Checkboxes:
        self.checkBox_useMonitoring.setChecked(self.acq.use_email_monitoring)
        self.checkBox_takeOV.setChecked(self.acq.take_overviews)
        if not self.checkBox_takeOV.isChecked():
            # Deactivate debris detection option when overviews deactivated:
            self.acq.use_debris_detection = False
            self.checkBox_useDebrisDetection.setChecked(False)
            self.checkBox_useDebrisDetection.setEnabled(False)
        self.checkBox_useDebrisDetection.setChecked(
            self.acq.use_debris_detection)
        self.checkBox_askUser.setChecked(self.acq.ask_user_mode)
        self.checkBox_mirrorDrive.setChecked(self.acq.use_mirror_drive)
        self.checkBox_monitorTiles.setChecked(self.acq.monitor_images)
        self.checkBox_useAutofocus.setChecked(self.acq.use_autofocus)
        # Change label of option 'Autofocus' to 'Focus tracking'
        # if method 2 (focus tracking) is selected
        if self.autofocus.method == 2:
            self.checkBox_useAutofocus.setText('Focus tracking')
        # Checkbox updates:
        self.checkBox_useMonitoring.stateChanged.connect(
            self.update_acq_options)
        self.checkBox_takeOV.stateChanged.connect(self.update_acq_options)
        self.checkBox_useDebrisDetection.stateChanged.connect(
            self.update_acq_options)
        self.checkBox_askUser.stateChanged.connect(self.update_acq_options)
        self.checkBox_mirrorDrive.stateChanged.connect(self.update_acq_options)
        self.checkBox_monitorTiles.stateChanged.connect(
            self.update_acq_options)
        self.checkBox_useAutofocus.stateChanged.connect(
            self.update_acq_options)
        # Focus tool zoom 2x
        self.checkBox_zoom.stateChanged.connect(self.ft_toggle_zoom)
        # Progress bar for stack acquisitions:
        self.progressBar.setValue(0)
        # Limit the log to user-specified number of most recent lines
        self.textarea_log.setMaximumBlockCount(
            int(self.cfg['monitoring']['max_log_line_count']))

        # Enable plasma cleaner GUI elements if plasma cleaner installed.
        self.toolButton_plasmaCleaner.setEnabled(self.plc_installed)
        self.checkBox_plasmaCleaner.setEnabled(self.plc_installed)
        self.actionPlasmaCleanerSettings.setEnabled(self.plc_installed)

        # Enable Variable Pressure GUI elements if installed.
        self.pushButton_VP.setEnabled(self.vp_installed)
        self.actionVariablePressureSettings.setEnabled(self.vp_installed)

        # Enable Focal Charge Compensator GUI elements if installed.
        self.pushButton_FCC.setEnabled(self.fcc_installed)
        self.actionChargeCompensatorSettings.setEnabled(self.fcc_installed)

        #-------MagC-------#

        if not self.magc_mode:
            # disable MagC tab
            self.tabWidget.setTabEnabled(3, False)
            self.actionImportMagCMetadata.setEnabled(False)
            # activate MagC with a double-click on the MagC tab
            self.tabWidget.setTabToolTip(3, 'Double-click to toggle MagC mode')
            self.tabWidget.tabBarDoubleClicked.connect(self.activate_magc_mode)
        else:
            self.initialize_magc_gui()

    def activate_magc_mode(self, tabIndex):
        if tabIndex != 3:
            return

        if self.cfg_file == 'default.ini':
            QMessageBox.information(
                self, 'Activating MagC mode',
                'Please activate MagC mode from a configuration file other '
                'than default.ini.',
                QMessageBox.Ok)
            return

        answer = QMessageBox.question(
            self, 'Activating MagC mode',
            'Do you want to activate the MagC mode?'
            '\n\nMake sure you have saved everything you need '
            'in the current session. \nYou will be prompted to '
            'enter a name for a new configuration file and '
            'SBEMimage will close. \nThe MagC mode will be active '
            'at the next start if you select the new configuration file.',
            QMessageBox.Yes| QMessageBox.No)
        if answer != QMessageBox.Yes:
            return

        dialog = SaveConfigDlg(self.syscfg_file)
        dialog.label.setText('Name of new MagC config file')
        dialog.label_line1.setText('Choose a name for the new MagC configuration')
        dialog.label_line2.setText('file. If the configuration file already exists,')
        dialog.label_line3.setText('then it will be overwritten.')
        dialog.label_line4.setText('Use only A-Z, a-z, 0-9, and hyphen/underscore.')
        dialog.label_line5.setText('.ini will be added automatically')

        if dialog.exec_():
            self.cfg_file = dialog.file_name
            self.cfg['sys']['magc_mode'] = 'True'
            self.cfg['sys']['use_microtome'] = 'False'
            self.save_config_to_disk()

            # close SBEMimage properly
            self.viewport.active = False
            self.viewport.close()
            QApplication.processEvents()
            sleep(1)
            # Recreate status.dat to indicate that program was closed
            # normally and didn't crash:
            with open(os.path.join('..','cfg','status.dat'), 'w+') as f:
                f.write(self.cfg_file)
            print('Closed by user.\n')
            sys.exit()

    def try_to_create_directory(self, new_directory):
        """Create directory. If not possible: error message"""
        try:
            os.makedirs(new_directory)
        except Exception as e:
            QMessageBox.warning(
                self, 'Could not create directory',
                f'Could not create directory {new_directory}: {str(e)}',
                QMessageBox.Ok)

    def update_main_controls_grid_selector(self, grid_index=0):
        """Update the combo box for grid selection in Main Controls window."""
        if grid_index >= self.gm.number_grids:
            grid_index = 0
        self.comboBox_gridSelector.blockSignals(True)
        self.comboBox_gridSelector.clear()
        grid_list_str = self.gm.grid_selector_list()
        for i in range(self.gm.number_grids):
            colour_icon = QPixmap(18, 9)
            rgb = self.gm[i].display_colour_rgb()
            colour_icon.fill(QColor(rgb[0], rgb[1], rgb[2]))
            self.comboBox_gridSelector.addItem(
                QIcon(colour_icon), '   ' + grid_list_str[i])
        self.grid_index_dropdown = grid_index
        self.comboBox_gridSelector.setCurrentIndex(grid_index)
        self.comboBox_gridSelector.currentIndexChanged.connect(
            self.change_grid_settings_display)
        self.comboBox_gridSelector.blockSignals(False)

    def update_main_controls_ov_selector(self, ov_index=0):
        """Update the combo box for OV selection in the Main Controls window."""
        if ov_index >= self.ovm.number_ov:
            ov_index = 0
        self.comboBox_OVSelector.blockSignals(True)
        self.comboBox_OVSelector.clear()
        ov_list_str = self.ovm.ov_selector_list()
        self.comboBox_OVSelector.addItems(ov_list_str)
        self.ov_index_dropdown = ov_index
        self.comboBox_OVSelector.setCurrentIndex(ov_index)
        self.comboBox_OVSelector.currentIndexChanged.connect(
            self.change_ov_settings_display)
        self.comboBox_OVSelector.blockSignals(False)

    def change_grid_settings_display(self):
        self.grid_index_dropdown = self.comboBox_gridSelector.currentIndex()
        self.show_current_settings()

    def change_ov_settings_display(self):
        self.ov_index_dropdown = self.comboBox_OVSelector.currentIndex()
        self.show_current_settings()

    def show_current_settings(self):
        """Show current settings in the upper part of the Main Conrols window"""
        # Installed devices:
        self.label_SEM.setText(self.sem.device_name)
        if self.use_microtome:
            self.label_microtome.setText(self.microtome.device_name)
        else:
            self.groupBox_stage.setTitle('Stage (no microtome)')
            self.label_microtome.setText(self.sem.device_name)
        # SEM beam settings:
        self.label_beamSettings.setText(
            '{0:.2f}'.format(self.sem.target_eht) + ' kV / '
            + str(self.sem.target_beam_current) + ' pA / '
            + str(self.sem.target_aperture_size) + ' μm')
        # Show dwell time, pixel size, and frame size for current grid:
        self.label_tileDwellTime.setText(
            str(self.gm[self.grid_index_dropdown].dwell_time) + ' µs')
        self.label_tilePixelSize.setText(
            str(self.gm[self.grid_index_dropdown].pixel_size) + ' nm')
        self.label_tileSize.setText(
            str(self.gm[self.grid_index_dropdown].tile_width_p())
            + ' × '
            + str(self.gm[self.grid_index_dropdown].tile_height_p()))
        # Show settings for current OV:
        self.label_OVDwellTime.setText(
            str(self.ovm[self.ov_index_dropdown].dwell_time) + ' µs')
        self.label_OVMagnification.setText(
            str(self.ovm[self.ov_index_dropdown].magnification))
        self.label_OVSize.setText(
            str(self.ovm[self.ov_index_dropdown].width_p())
            + ' × '
            + str(self.ovm[self.ov_index_dropdown].height_p()))
        ov_centre = self.ovm[self.ov_index_dropdown].centre_sx_sy
        self.label_OVLocation.setText('X: {0:.3f}'.format(ov_centre[0])
                                      + ', Y: {0:.3f}'.format(ov_centre[1]))
        # Debris detection area
        if self.acq.use_debris_detection:
            self.label_debrisDetectionArea.setText(
                str(self.ovm[self.ov_index_dropdown].debris_detection_area))
        else:
            self.label_debrisDetectionArea.setText('-')
        # Grid parameters
        grid_origin = self.gm[self.grid_index_dropdown].origin_sx_sy
        self.label_gridOrigin.setText('X: {0:.3f}'.format(grid_origin[0])
                                      + ', Y: {0:.3f}'.format(grid_origin[1]))
        # Tile grid parameters
        grid_size = self.gm[self.grid_index_dropdown].size
        self.label_gridSize.setText(str(grid_size[0]) + ' × ' +
                                    str(grid_size[1]))
        self.label_numberActiveTiles.setText(
            str(self.gm[self.grid_index_dropdown].number_active_tiles()))
        # Acquisition parameters
        self.lineEdit_baseDir.setText(self.acq.base_dir)
        self.label_numberSlices.setText(str(self.acq.number_slices))
        if self.use_microtome:
            self.label_sliceThickness.setText(
                str(self.acq.slice_thickness) + ' nm')
        else:
            self.label_sliceThickness.setText('---')

    def show_stack_acq_estimates(self):
        """Read current estimates from the stack instance and display
           them in the main window.
        """
        # Get current estimates:
        (min_dose, max_dose, total_area, total_z, total_data,
        total_imaging, total_stage_moves, total_cutting,
        date_estimate, remaining_time) = self.acq.calculate_estimates()
        total_duration = total_imaging + total_stage_moves + total_cutting
        if min_dose == max_dose:
            self.label_dose.setText(
                '{0:.1f}'.format(min_dose) + ' electrons per nm²')
        else:
            self.label_dose.setText(
                '{0:.2f}'.format(min_dose) + ' .. '
                + '{0:.1f}'.format(max_dose) + ' electrons per nm²')
        if total_duration == 0:
            total_duration = 1  # prevent division by zero
        days, hours, minutes = utils.get_days_hours_minutes(total_duration)
        self.label_totalDuration.setText(
            f'{days} d {hours} h {minutes} min     '
            f'({total_imaging/total_duration * 100:.1f}% / '
            f'{total_stage_moves/total_duration * 100:.1f}% / '
            f'{total_cutting/total_duration * 100:.1f}%)')
        self.label_totalArea.setText('{0:.1f}'.format(total_area) + ' µm²')
        self.label_totalZ.setText('{0:.1f}'.format(total_z) + ' µm')
        self.label_totalData.setText('{0:.1f}'.format(total_data) + ' GB')
        days, hours, minutes = utils.get_days_hours_minutes(remaining_time)
        self.label_dateEstimate.setText(
            date_estimate + f'   ({days} d {hours} h {minutes} min remaining)')

    def update_acq_options(self):
        """Update the options for the stack acquisition selected by the user
        in the GUI (check boxes in acquisition panel)."""
        self.acq.use_email_monitoring = (
            self.checkBox_useMonitoring.isChecked())
        self.acq.take_overviews = self.checkBox_takeOV.isChecked()
        if not self.checkBox_takeOV.isChecked():
            # Deactivate debris detection option when no overviews are taken
            self.checkBox_useDebrisDetection.setChecked(False)
            self.checkBox_useDebrisDetection.setEnabled(False)
        else:
            # Activate debris detection
            self.checkBox_useDebrisDetection.setEnabled(True)
        self.acq.use_debris_detection = (
            self.checkBox_useDebrisDetection.isChecked())
        self.acq.ask_user_mode = self.checkBox_askUser.isChecked()
        self.acq.use_mirror_drive = self.checkBox_mirrorDrive.isChecked()
        self.acq.monitor_images = self.checkBox_monitorTiles.isChecked()
        self.acq.use_autofocus = self.checkBox_useAutofocus.isChecked()
        # Show updated stack estimates (depend on options selected)
        self.show_stack_acq_estimates()
        # Show updated debris detectiona area
        self.show_current_settings()
        # Redraw Viewport canvas (some labels may have changed)
        self.viewport.vp_draw()

# ----------------------------- MagC tab ---------------------------------------

    def initialize_magc_gui(self):
        self.gm.magc_selected_sections = []
        self.gm.magc_checked_sections = []
        self.gm.magc_wafer_calibrated = False
        self.actionImportMagCMetadata.triggered.connect(
            self.magc_open_import_dlg)

        # initialize the section_table (QTableView)
        model = QStandardItemModel(0, 0)
        model.setHorizontalHeaderItem(0, QStandardItem('Section'))
        model.setHorizontalHeaderItem(1, QStandardItem('State'))
        self.tableView_magc_sections.setModel(model)
        (self.tableView_magc_sections.selectionModel()
            .selectionChanged
            .connect(self.magc_actions_selected_sections_changed))

        header = self.tableView_magc_sections.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)

        self.tableView_magc_sections.doubleClicked.connect(
            self.magc_double_clicked_section)

        # set logo
        self.collectomeLogo.setScaledContents(True)
        self.collectomeLogo.setPixmap(
            QPixmap(os.path.join('..','magc','img','collectome_logo.png')))

        # initialize other MagC GUI items
        self.pushButton_magc_importMagc.clicked.connect(
            self.magc_open_import_dlg)
        self.pushButton_magc_waferCalibration.clicked.connect(
            self.magc_open_wafer_calibration_dlg)
        self.pushButton_magc_resetMagc.clicked.connect(self.magc_reset)
        self.pushButton_magc_selectAll.clicked.connect(self.magc_select_all)
        self.pushButton_magc_deselectAll.clicked.connect(self.magc_deselect_all)
        self.pushButton_magc_checkSelected.clicked.connect(
            self.magc_check_selected)
        self.pushButton_magc_uncheckSelected.clicked.connect(
            self.magc_uncheck_selected)
        self.pushButton_magc_invertSelection.clicked.connect(
            self.magc_invert_selection)
        self.pushButton_magc_selectChecked.clicked.connect(
            self.magc_select_checked)
        self.pushButton_magc_okStringSections.clicked.connect(
            self.magc_select_string_sections)
        self.pushButton_magc_importWaferImage.clicked.connect(
            self.magc_open_import_wafer_image)
        if self.gm.magc_sections_path == '':
            self.pushButton_magc_importWaferImage.setEnabled(False)
        self.pushButton_magc_addSection.clicked.connect(
            self.magc_add_section)
        if not self.gm.magc_wafer_calibrated:
            self.pushButton_magc_addSection.setEnabled(False)
        self.pushButton_magc_deleteLastSection.clicked.connect(
            self.magc_delete_last_section)

        self.pushButton_magc_waferCalibration.setStyleSheet(
            'background-color: lightgray')
        self.pushButton_magc_waferCalibration.setEnabled(False)

        # deactivate some core SBEMimage functions
        self.pushButton_microtomeSettings.setEnabled(False)
        self.actionMicrotomeSettings.setEnabled(False)
        self.actionDebrisDetectionSettings.setEnabled(False)
        self.actionAskUserModeSettings.setEnabled(False)

    def magc_select_all(self):
        model = self.tableView_magc_sections.model()
        self.magc_select_rows(range(model.rowCount()))

    def magc_deselect_all(self):
        self.tableView_magc_sections.clearSelection()

    def magc_check_selected(self):
        selectedRows = [
            id.row() for id
                in self.tableView_magc_sections
                    .selectedIndexes()]
        self.magc_set_check_rows(selectedRows, Qt.Checked)
        self.magc_update_checked_sections_to_config()

    def magc_uncheck_selected(self):
        selectedRows = [
            id.row() for id
                in self.tableView_magc_sections
                    .selectedIndexes()]
        self.magc_set_check_rows(selectedRows, Qt.Unchecked)
        self.magc_update_checked_sections_to_config()

    def magc_invert_selection(self):
        selectedRows = [
            id.row() for id
                in self.tableView_magc_sections
                    .selectedIndexes()]
        model = tableView.model()
        rowsToSelect = set(range(model.rowCount())) - set(selectedRows)
        self.magc_select_rows(rowsToSelect)

    def magc_select_checked(self):
        model = self.tableView_magc_sections.model()
        checkedRows = []
        for r in range(model.rowCount()):
            item = model.item(r, 0)
            if item.checkState() == Qt.Checked:
                checkedRows.append(r)
        self.magc_select_rows(checkedRows)

    def magc_select_string_sections(self):
        userString = self.textEdit_magc_stringSections.toPlainText()
        indexes = utils.get_indexes_from_user_string(userString)
        if indexes:
            self.magc_select_rows(indexes)
            (self.tableView_magc_sections
                .verticalScrollBar()
                .setValue(indexes[0]))
            utils.log_info(
                'Custom section string selection: '
                + userString)
        else:
            utils.log_error(
                'Something wrong in your input. Use 2,5,3 or 2-30 or 2-30-5')

    def magc_set_check_rows(self, rows, check_state):
        model = self.tableView_magc_sections.model()
        model.blockSignals(True) # prevent slowness
        for row in rows:
            item = model.item(row, 0)
            item.setCheckState(check_state)
        model.blockSignals(False)
        self.tableView_magc_sections.setFocus()

    def magc_select_rows(self, rows):
        tableView = self.tableView_magc_sections
        tableView.clearSelection()
        selectionModel = tableView.selectionModel()
        model = tableView.model()
        selection = QItemSelection()
        for row in rows:
            index = model.index(row, 0)
            selection.merge(
                QItemSelection(index, index),
                QItemSelectionModel.Select)
        selectionModel.select(selection, QItemSelectionModel.Select)
        self.tableView_magc_sections.setFocus()

    def magc_actions_selected_sections_changed(
        self, changedSelected, changedDeselected):

        # update color of selected/deselected sections
        for changedSelectedIndex in changedSelected.indexes():
            row = changedSelectedIndex.row()
            self.gm[row].display_colour = 0
        for changedDeselectedIndex in changedDeselected.indexes():
            row = changedDeselectedIndex.row()
            self.gm[row].display_colour = 1
        self.viewport.vp_draw()
        # update config
        self.gm.magc_selected_sections = [
            id.row() for id
                in self.tableView_magc_sections
                    .selectedIndexes()]

    def magc_update_checked_sections_to_config(self):
        checkedSections = []
        model = self.tableView_magc_sections.model()
        for r in range(model.rowCount()):
            item = model.item(r, 0)
            if item.checkState() == Qt.Checked:
                checkedSections.append(r)
        self.gm.magc_checked_sections = checkedSections

    def magc_double_clicked_section(self, doubleClickedIndex):
        row = doubleClickedIndex.row()
        model = doubleClickedIndex.model()
        firstColumnIndex = model.index(row, 0)
        # the index and the key of the section should in theory be the same,
        # just in case
        sectionKey = int(model.data(firstColumnIndex))
        self.cs.vp_centre_dx_dy = self.gm[row].centre_dx_dy
        self.viewport.vp_draw()
        if self.gm.magc_wafer_calibrated:
            utils.log_info('Section ' + str(sectionKey)
                                + ' has been double-clicked. Moving to section...')
            # set scan rotation
            theta = self.gm[row].rotation
            self.sem.set_scan_rotation(theta)
            # set stage
            grid_center_s = self.gm[row].centre_sx_sy
            self.stage.move_to_xy(grid_center_s)
        else:
            utils.log_warning(
                'Section ' + str(sectionKey)
                + ' has been double-clicked. Wafer is not '
                + 'calibrated, therefore no stage movement.')

    def magc_set_section_state_in_table(self, msg):
        model = self.tableView_magc_sections.model()
        section_number, state = msg.split('-')[1:]
        if state == 'acquiring':
            state_color = QColor(Qt.yellow)
        elif state == 'acquired':
            state_color = QColor(Qt.green)
        else:
            state_color = QColor(Qt.lightGray)
        item = model.item(int(section_number), 1)
        item.setBackground(state_color)
        index = model.index(int(section_number), 1)
        self.tableView_magc_sections.scrollTo(index,
            QAbstractItemView.PositionAtCenter)

    def magc_reset(self):
        model = self.tableView_magc_sections.model()
        model.removeRows(0, model.rowCount(), QModelIndex())
        self.gm.magc_sections_path = ''
        self.gm.magc_wafer_calibrated = False
        self.gm.magc_selected_sections = []
        self.gm.magc_checked_sections = []
        self.gm.delete_all_grids_above_index(0)
        self.viewport.update_grids()
        # unenable wafer calibration button
        self.pushButton_magc_waferCalibration.setEnabled(False)
        # unenable wafer image import
        self.pushButton_magc_importWaferImage.setEnabled(False)
        # change wafer flag
        self.pushButton_magc_waferCalibration.setStyleSheet(
            'background-color: lightgray')
        # delete all imported images in viewport
        self.imported.delete_all_images()
        self.viewport.vp_draw()


    def magc_open_import_wafer_image(self):
        target_dir = os.path.join(
            self.acq.base_dir,
            'overviews', 'imported')
        if not os.path.exists(target_dir):
            self.try_to_create_directory(target_dir)
        import_wafer_dlg = ImportWaferImageDlg(
            self.acq, self.imported,
            os.path.dirname(self.gm.magc_sections_path),
            self.trigger)

    def magc_add_section(self):
        self.gm.add_new_grid()
        grid_index = self.gm.number_grids - 1
        self.gm[grid_index].origin_sx_sy = list(*self.stage.get_xy())

        # set same properties as previous section if it exists
        if grid_index != 0:
            self.gm[grid_index].rotation = self.gm[grid_index-1].rotation
            self.gm[grid_index].size = self.gm[grid_index-1].size
            self.gm[grid_index].frame_size_selector = (
                self.gm[grid_index-1].frame_size_selector)
            self.gm[grid_index].pixel_size = self.gm[grid_index-1].pixel_size

        self.gm[grid_index].update_tile_positions()
        self.update_from_grid_dlg()

        # add section to the section_table
        item1 = QStandardItem(str(grid_index))
        item1.setCheckable(True)
        item2 = QStandardItem('')
        item2.setBackground(color_not_acquired)
        item2.setCheckable(False)
        item2.setSelectable(False)
        tableView = self.tableView_magc_sections
        model = tableView.model()
        model.appendRow([item1, item2])

    def magc_delete_last_section(self):
        # remove section from list
        model = self.tableView_magc_sections.model()
        lastSectionNumber = model.rowCount()-1
        model.removeRow(lastSectionNumber)
        # unselect and uncheck section
        if lastSectionNumber in self.gm.magc_selected_sections:
            self.gm.magc_selected_sections.remove(lastSectionNumber)

        if lastSectionNumber in self.gm.magc_checked_sections:
            self.gm.magc_checked_sections.remove(lastSectionNumber)

        # remove grid
        self.gm.delete_grid()
        self.update_from_grid_dlg()

    def magc_open_import_dlg(self):
        gui_items = {'section_table': self.tableView_magc_sections,}
        dialog = ImportMagCDlg(self.acq, self.gm, self.sem, self.imported,
                               gui_items, self.trigger)
        if dialog.exec_():
            # self.tabWidget.setTabEnabled(3, True)
            self.update_from_grid_dlg()

    def magc_open_wafer_calibration_dlg(self):
        dialog = WaferCalibrationDlg(self.cfg, self.stage, self.ovm, self.cs,
                                     self.gm, self.imported, self.trigger)
        if dialog.exec_():
            pass
# --------------------------- End of MagC tab ----------------------------------


# =============== Below: all methods that open dialog windows ==================

    def open_mag_calibration_dlg(self):
        dialog = MagCalibrationDlg(self.sem)
        if dialog.exec_():
            # Show updated OV magnification
            self.show_current_settings()

    def open_save_settings_new_file_dlg(self):
        """Open dialog window to let user save the current configuration under
        a new name.
        """
        # Check if the current configuration is default.ini
        if self.cfg_file == 'default.ini':
            new_syscfg = True
            dialog = SaveConfigDlg('', new_syscfg)
        else:
            new_syscfg = False
            dialog = SaveConfigDlg(self.syscfg_file)
        if dialog.exec_():
            self.cfg_file = dialog.file_name
            if new_syscfg:
                self.syscfg_file = dialog.sysfile_name
                self.cfg['sys']['sys_config_file'] = self.syscfg_file
            self.save_config_to_disk()
            # Show new config file name in status bar
            self.set_statusbar('Ready.')

    def open_sem_dlg(self):
        dialog = SEMSettingsDlg(self.sem)
        if dialog.exec_():
            if self.microtome is not None:
                # Update stage calibration (EHT may have changed)
                self.cs.load_stage_calibration(self.sem.target_eht)
                self.cs.apply_stage_calibration()
            self.show_current_settings()
            # Electron dose may have changed
            self.show_stack_acq_estimates()
            if self.ovm.use_auto_debris_area:
                self.ovm.update_all_debris_detections_areas(self.gm)
            self.viewport.vp_draw()
            if not self.cs.calibration_found:
                utils.log_error(
                    'CTRL', 'Warning - No stage calibration found for '
                    'current EHT.')
                QMessageBox.warning(
                    self, 'Missing stage calibration',
                    'No stage calibration settings were found for the '
                    'currently selected EHT. Please calibrate the stage:'
                    '\nMenu  →  Calibration  →  Stage calibration',
                    QMessageBox.Ok)

    def open_microtome_dlg(self):
        if self.microtome is not None:
            if self.microtome.device_name == 'Gatan 3View':
                dialog = MicrotomeSettingsDlg(self.microtome, self.sem, self.cs,
                                              self.use_microtome)
                if dialog.exec_():
                    self.show_current_settings()
                    self.show_stack_acq_estimates()
                    self.viewport.vp_draw()
            elif self.microtome.device_name == 'ConnectomX katana':
                dialog = KatanaSettingsDlg(self.microtome)
                dialog.exec_()
            elif self.microtome.device_name == 'GCIB':
                dialog = GCIBSettingsDlg(self.microtome)
                dialog.exec_()
        else:
            utils.log_error('No microtome-related functions are available'
                ' because no microtome is configured in the current session')

    def open_calibration_dlg(self):
        prev_calibration = self.cs.stage_calibration
        dialog = StageCalibrationDlg(self.cs, self.stage, self.sem,
                                     self.acq.base_dir)
        if dialog.exec_() and self.cs.stage_calibration != prev_calibration:
            # Recalculate all grids and debris detection areas
            for grid_index in range(self.gm.number_grids):
                self.gm[grid_index].update_tile_positions()
            if self.ovm.use_auto_debris_area:
                self.ovm.update_all_debris_detections_areas(self.gm)
            self.viewport.vp_draw()

    def open_cut_duration_dlg(self):
        dialog = CutDurationDlg(self.microtome)
        dialog.exec_()

    def open_ov_dlg(self):
        dialog = OVSettingsDlg(self.ovm, self.sem, self.ov_index_dropdown,
                               self.trigger)
        # self.update_from_ov_dlg() is called when user saves settings
        # or adds/deletes OVs.
        dialog.exec_()

    def update_from_ov_dlg(self):
        self.update_main_controls_ov_selector(self.ov_index_dropdown)
        self.ft_update_ov_selector(self.ft_selected_ov)
        self.viewport.update_ov()
        if self.ovm.use_auto_debris_area:
            self.ovm.update_all_debris_detections_areas(self.gm)
        self.show_current_settings()
        self.show_stack_acq_estimates()
        self.viewport.vp_draw()

    def open_grid_dlg(self, selected_grid):
        dialog = GridSettingsDlg(self.gm, self.sem, selected_grid,
                                 self.trigger, self.magc_mode)
        # self.update_from_grid_dlg() is called when user saves settings
        # or adds/deletes grids.
        dialog.exec_()

    def update_from_grid_dlg(self):
        # Update selectors:
        self.update_main_controls_grid_selector(self.grid_index_dropdown)
        self.ft_update_grid_selector(self.ft_selected_grid)
        self.ft_update_tile_selector()
        if self.ft_selected_ov == -1:
            self.ft_clear_wd_stig_display()
        self.viewport.update_grids()
        if self.ovm.use_auto_debris_area:
            self.ovm.update_all_debris_detections_areas(self.gm)
        self.show_current_settings()
        self.show_stack_acq_estimates()
        self.viewport.vp_draw()

    def open_acq_settings_dlg(self):
        dialog = AcqSettingsDlg(self.acq, self.notifications,
                                self.use_microtome)
        if dialog.exec_():
            self.show_current_settings()
            self.show_stack_acq_estimates()
            self.show_stack_progress()   # Slice number may have changed.

    def open_pre_stack_dlg(self):
        # Calculate new estimates first, then open dialog:
        self.show_stack_acq_estimates()
        dialog = PreStackDlg(self.acq, self.sem, self.microtome,
                             self.autofocus, self.ovm, self.gm)
        if dialog.exec_():
            self.show_current_settings()
            self.start_acquisition()

    def open_export_dlg(self):
        dialog = ExportDlg(self.acq)
        dialog.exec_()

    def open_update_dlg(self):
        dialog = UpdateDlg()
        dialog.exec_()

    def open_email_monitoring_dlg(self):
        dialog = EmailMonitoringSettingsDlg(self.acq, self.notifications)
        dialog.exec_()

    def open_debris_dlg(self):
        dialog = DebrisSettingsDlg(self.ovm, self.img_inspector, self.acq)
        if dialog.exec_():
            self.ovm.update_all_debris_detections_areas(self.gm)
            self.show_current_settings()
            self.viewport.vp_draw()

    def open_ask_user_dlg(self):
        dialog = AskUserDlg()
        dialog.exec_()

    def open_mirror_drive_dlg(self):
        dialog = MirrorDriveDlg(self.acq)
        dialog.exec_()

    def open_image_monitoring_dlg(self):
        dialog = ImageMonitoringSettingsDlg(self.img_inspector)
        dialog.exec_()

    def open_autofocus_dlg(self):
        dialog = AutofocusSettingsDlg(self.autofocus, self.gm, self.magc_mode)
        if dialog.exec_():
            if self.autofocus.method == 2:
                self.checkBox_useAutofocus.setText('Focus tracking')
            else:
                self.checkBox_useAutofocus.setText('Autofocus')
            self.viewport.vp_draw()

    def open_plasma_cleaner_dlg(self):
        dialog = PlasmaCleanerDlg(self.plasma_cleaner)
        dialog.exec_()

    def open_approach_dlg(self):
        dialog = ApproachDlg(self.microtome, self.trigger)
        dialog.exec_()

    def open_grab_frame_dlg(self):
        dialog = GrabFrameDlg(self.sem, self.acq, self.trigger)
        dialog.exec_()

    def open_variable_pressure_dlg(self):
        dialog = VariablePressureDlg(self.sem)
        dialog.exec_()

    def open_charge_compensator_dlg(self):
        dialog = ChargeCompensatorDlg(self.sem)
        dialog.exec_()

    def open_eht_dlg(self):
        dialog = EHTDlg(self.sem)
        dialog.exec_()

    def open_motor_test_dlg(self):
        dialog = MotorTestDlg(self.microtome, self.acq, self.trigger)
        dialog.exec_()

    def open_motor_status_dlg(self):
        dialog = MotorStatusDlg(self.stage)
        dialog.exec_()

    def open_send_command_dlg(self):
        dialog = SendCommandDlg(self.microtome)
        dialog.exec_()

    def open_about_box(self):
        dialog = AboutBox(self.VERSION)
        dialog.exec_()

# ============ Below: stack progress update and signal processing ==============

    def show_stack_progress(self):
        current_slice = self.acq.slice_counter
        if self.acq.number_slices > 0:
            self.label_sliceCounter.setText(
                str(current_slice) + '      (' + chr(8710) + 'Z = '
                + '{0:.3f}'.format(self.acq.total_z_diff) + ' µm)')
            self.progressBar.setValue(
                current_slice / self.acq.number_slices * 100)
        else:
            self.label_sliceCounter.setText(
                str(current_slice) + "      (no cut after acq.)")

    def show_current_stage_xy(self):
        xy_pos = self.stage.last_known_xy
        if xy_pos[0] is None or xy_pos[1] is None:
            pos_info = ('X: unknown    Y: unknown')
        else:
            pos_info = ('X: {0:.3f}    Y: {1:.3f}'.format(*xy_pos))
        self.label_currentStageXY.setText(pos_info)
        QApplication.processEvents() # ensures changes are shown without delay

    def show_current_stage_z(self):
        z_pos = self.stage.last_known_z
        if z_pos is None:
            pos_info = 'Z: unknown'
        else:
            pos_info = 'Z: {0:.3f}'.format(z_pos)
        self.label_currentStageZ.setText(pos_info)
        QApplication.processEvents()

    def set_statusbar(self, msg):
        """Set the status bar of the main controls window."""
        # self.statusbar_msg is needed to override the status tips. See event()
        self.statusbar_msg = (
            msg
            + f' Active configuration: {self.cfg_file} /'
            + f' {self.syscfg_file}')
        self.statusBar().showMessage(self.statusbar_msg)

    def set_status(self, label_text, statusbar_text, busy_state):
        """Set status of Main Controls: Label in GUI (acquisition panel),
        message in status bar, and 'busy' state (True/False)."""
        pal = QPalette(self.label_acqIndicator.palette())
        pal.setColor(QPalette.WindowText, QColor(Qt.red))
        self.label_acqIndicator.setPalette(pal)
        self.label_acqIndicator.setText(label_text)
        self.set_statusbar(statusbar_text)
        self.busy = busy_state

    def event(self, e):
        """Override status tips when hovering with mouse over menu."""
        if e.type() == QEvent.StatusTip:
            e = QStatusTipEvent(self.statusbar_msg)
        return super().event(e)

    def process_signal(self):
        """Process signals from the acquisition thread, the viewport, or from
        dialog windows. The trigger/queue approach is required to pass
        information between threads and to allow the GUI to be updated from a
        thread.
        """
        msg = self.trigger.queue.get()
        if msg == 'STATUS IDLE':
            self.set_status('', 'Ready.', False)
        elif msg == 'STATUS BUSY APPROACH':
            self.set_status('Busy.', 'Approach cutting in progress...', True)
        elif msg == 'STATUS BUSY OV':
            self.set_status(
                'Busy.', 'Overview acquisition in progress...', True)
        elif msg == 'STATUS BUSY STUB':
            self.set_status(
                'Busy.', 'Stub overview acquisition in progress...', True)
        elif msg == 'STATUS BUSY STAGE MOVE':
            self.set_status('Busy.', 'Stage move in progress...', True)
        elif msg == 'STATUS BUSY GRAB IMAGE':
            self.set_status(
                'Busy.', 'Acquisition of single image in progress...', True)
        elif msg == 'UPDATE XY':
            self.show_current_stage_xy()
        elif msg == 'UPDATE XY FT':
            self.ft_show_updated_stage_position()
        elif msg == 'UPDATE Z':
            self.show_current_stage_z()
        elif msg == 'UPDATE PROGRESS':
            self.show_stack_progress()
            self.show_stack_acq_estimates()
            self.viewport.m_show_motor_status()
        elif msg == 'MANUAL SWEEP SUCCESS':
            self.manual_sweep_success(True)
        elif msg == 'MANUAL SWEEP FAILURE':
            self.manual_sweep_success(False)
        elif msg == 'REMOTE STOP':
            self.remote_stop()
        elif msg == 'ERROR PAUSE':
            self.error_pause()
        elif msg == 'COMPLETION STOP':
            self.completion_stop()
        elif msg == 'ACQ NOT IN PROGRESS':
            self.set_status('', 'Ready.', False)
            self.acq_not_in_progress_update_gui()
        elif msg == 'SAVE CFG':
            self.save_settings()
        elif msg.startswith('ACQ IND OV'):
            self.viewport.vp_toggle_ov_acq_indicator(
                int(msg[len('ACQ IND OV'):]))
        elif msg[:12] == 'ACQ IND TILE':
            position = msg[12:].split('.')
            self.viewport.vp_toggle_tile_acq_indicator(
                int(position[0]), int(position[1]))
        elif msg == 'RESTRICT GUI':
            self.restrict_gui(True)
        elif msg == 'RESTRICT VP GUI':
            self.viewport.restrict_gui(True)
        elif msg == 'UNRESTRICT GUI':
            self.restrict_gui(False)
        elif msg[:8] == 'SHOW MSG':
            QMessageBox.information(self,
                'Message received from remote server',
                'Message text: ' + msg[8:],
                 QMessageBox.Ok)
        elif msg == 'GRID SETTINGS CHANGED':
            self.update_from_grid_dlg()
        elif msg == 'OV SETTINGS CHANGED':
            self.update_from_ov_dlg()
        elif msg[:18] == 'GRAB VP SCREENSHOT':
            self.viewport.grab_viewport_screenshot(msg[18:])
        elif msg == 'DRAW VP':
            self.viewport.vp_draw()
        elif msg == 'DRAW VP NO LABELS':
            self.viewport.vp_draw(suppress_labels=True, suppress_previews=True)
        elif msg[:12] == 'INCIDENT LOG':
            self.viewport.show_in_incident_log(msg[12:])
        elif msg[:15] == 'GET CURRENT LOG':
            try:
                self.write_current_log_to_file(msg[15:])
            except Exception as e:
                utils.log_error('CTRL', 'Could not write current log to disk: '
                                + str(e))
        elif msg == 'MAGC WAFER CALIBRATED':
            self.pushButton_magc_waferCalibration.setStyleSheet('background-color: green')
        elif msg == 'MAGC WAFER NOT CALIBRATED':
            self.pushButton_magc_waferCalibration.setStyleSheet('background-color: yellow')
        elif msg == 'MAGC ENABLE CALIBRATION':
            self.pushButton_magc_waferCalibration.setEnabled(True)
        elif msg == 'MAGC UNENABLE CALIBRATION':
            self.pushButton_magc_waferCalibration.setEnabled(False)
        elif msg == 'MAGC ENABLE WAFER IMAGE IMPORT':
            self.pushButton_magc_importWaferImage.setEnabled(True)
        elif 'SET SECTION STATE' in msg:
            self.magc_set_section_state_in_table(msg)
        elif msg == 'REFRESH OV':
            self.acquire_ov()
        elif msg == 'SHOW CURRENT SETTINGS':
            self.show_current_settings()
            self.show_stack_acq_estimates()
        elif msg == 'LOAD IN FOCUS TOOL':
            self.ft_set_selection_from_viewport()
        elif msg == 'UPDATE FT TILE SELECTOR':
            self.ft_update_tile_selector()
        elif msg == 'MOVE STAGE':
            self.move_stage()
        elif msg == 'ADD TILE FOLDER':
            self.add_tile_folder()
        elif msg == 'IMPORT IMG':
            self.open_import_image_dlg()
        elif msg[:19] == 'ADJUST IMPORTED IMG':
            selected_img = int(msg[19:])
            self.open_adjust_image_dlg(selected_img)
        elif msg == 'DELETE IMPORTED IMG':
            self.open_delete_image_dlg()
        elif msg[:20] == 'CHANGE GRID ROTATION':
            selected_grid = int(msg[20:])
            self.open_change_grid_rotation_dlg(selected_grid)
        elif 'OPEN GRID SETTINGS' in msg:
            grid_index = int(msg.split('INGS')[1])
            self.open_grid_dlg(grid_index)
        elif msg == 'Z WARNING':
            QMessageBox.warning(
                self, 'Z position mismatch',
                'The current Z position does not match the last known '
                'Z position in SBEMimage. Have you manually changed Z in '
                'the meantime? Make sure that the Z position is correct '
                'before (re)starting the stack.',
                QMessageBox.Ok)
        elif msg == 'FOCUS ALERT':
            QMessageBox.warning(
                self, 'Focus/stigmation change detected',
                'SBEMimage has detected an unexpected change in '
                'focus/stigmation parameters. Target settings have been '
                'restored.', QMessageBox.Ok)
        elif msg == 'MAG ALERT':
            QMessageBox.warning(
                self, 'Magnification change detected',
                'SBEMimage has detected an unexpected change in '
                'magnification. Target setting has been restored.',
                QMessageBox.Ok)
        elif msg.startswith('ASK DEBRIS FIRST OV'):
            ov_index = int(msg[len('ASK DEBRIS FIRST OV'):])
            self.viewport.vp_show_overview_for_user_inspection(ov_index)
            msgBox = QMessageBox(self)
            msgBox.setIcon(QMessageBox.Question)
            msgBox.setWindowTitle('Please inspect overview image quality')
            msgBox.setText(
                f'Is the overview image OV {ov_index} now shown in the '
                f'Viewport clean and of good quality (no debris or other image '
                f'defects)?\n\n'
                f'(This confirmation is required for the first slice to be '
                f'imaged after (re)starting an acquisition.)')
            msgBox.addButton(QPushButton('  Image is fine!  '),
                             QMessageBox.YesRole)
            msgBox.addButton(QPushButton('  There is debris.  '),
                             QMessageBox.NoRole)
            msgBox.addButton(QPushButton('Abort'),
                             QMessageBox.RejectRole)
            reply = msgBox.exec_()
            # Redraw with previous settings
            self.viewport.vp_draw()
            self.acq.user_reply = reply
        elif msg.startswith('ASK DEBRIS CONFIRMATION'):
            ov_index = int(msg[len('ASK DEBRIS CONFIRMATION'):])
            self.viewport.vp_show_overview_for_user_inspection(ov_index)
            msgBox = QMessageBox(self)
            msgBox.setIcon(QMessageBox.Question)
            msgBox.setWindowTitle('Potential debris detected - please confirm')
            msgBox.setText(
                f'Is debris visible in the detection area of OV {ov_index} now '
                f'shown in the Viewport?\n\n'
                f'(Potential debris has been detected in this overview image. '
                f'If you get several false positives in a row, you may need to '
                f'adjust your detection thresholds.)')
            msgBox.addButton(QPushButton('  Yes, there is debris.  '),
                             QMessageBox.YesRole)
            msgBox.addButton(QPushButton('  No debris, continue!  '),
                             QMessageBox.NoRole)
            msgBox.addButton(QPushButton('Abort'),
                             QMessageBox.RejectRole)
            reply = msgBox.exec_()
            # Redraw with previous settings
            self.viewport.vp_draw()
            self.acq.user_reply = reply
        elif msg == 'ASK IMAGE ERROR OVERRIDE':
            reply = QMessageBox.question(
                self, 'Image inspector',
                'The current image has failed the image inspector tests.\n'
                'Would you like to proceed anyway?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes)
            self.acq.user_reply = reply
        else:
            # If msg is not a command, show it in log:
            # TODO: remove
            self.textarea_log.appendPlainText(msg)

    def add_tile_folder(self):
        """Add a folder for a new tile to be acquired while the acquisition
        is running."""
        grid = self.viewport.selected_grid
        tile = self.viewport.selected_tile
        tile_folder = os.path.join(
            self.acq.base_dir, 'tiles',
            'g' + str(grid).zfill(utils.GRID_DIGITS),
            't' + str(tile).zfill(utils.TILE_DIGITS))
        if not os.path.exists(tile_folder):
            self.try_to_create_directory(tile_folder)
        if self.acq.use_mirror_drive:
            mirror_tile_folder = os.path.join(
                self.acq.mirror_drive, tile_folder[2:])
            if not os.path.exists(mirror_tile_folder):
                self.try_to_create_directory(mirror_tile_folder)

    def restrict_gui(self, b):
        """Disable GUI elements during acq or when program is busy."""
        # Partially disable/enable the tests and the focus tool
        self.restrict_focus_tool_gui(b)
        self.restrict_tests_gui(b)
        b ^= True
        # Settings buttons
        self.pushButton_SEMSettings.setEnabled(b)
        self.pushButton_microtomeSettings.setEnabled(b)
        self.pushButton_OVSettings.setEnabled(b)
        self.pushButton_gridSettings.setEnabled(b)
        self.pushButton_acqSettings.setEnabled(b)
        # Other buttons
        self.pushButton_doApproach.setEnabled(b)
        self.pushButton_doSweep.setEnabled(b)
        self.pushButton_grabFrame.setEnabled(b)
        self.pushButton_EHTToggle.setEnabled(b)
        # Checkboxes
        self.checkBox_mirrorDrive.setEnabled(b)
        self.toolButton_mirrorDrive.setEnabled(b)
        self.checkBox_takeOV.setEnabled(b)
        self.toolButton_OVSettings.setEnabled(b)
        if self.plc_installed:
            self.checkBox_plasmaCleaner.setEnabled(b)
            self.toolButton_plasmaCleaner.setEnabled(b)
        # Start, reset buttons
        self.pushButton_startAcq.setEnabled(b)
        self.pushButton_resetAcq.setEnabled(b)
        # Disable/enable menu
        self.menubar.setEnabled(b)
        # Restrict GUI (microtome-specific functionality) if no microtome used
        if not self.use_microtome or self.syscfg['device']['microtome'] == '6':
            self.restrict_gui_for_sem_stage()

        if self.syscfg['device']['microtome'] != '6':
            self.restrict_gui_wo_gcib()

    def restrict_focus_tool_gui(self, b):
        b ^= True
        self.pushButton_focusToolStart.setEnabled(b)
        self.pushButton_focusToolMove.setEnabled(b)
        self.checkBox_zoom.setEnabled(b)

    def restrict_tests_gui(self, b):
        b ^= True
        self.pushButton_testGetMag.setEnabled(b)
        self.pushButton_testSetMag.setEnabled(b)
        self.pushButton_testGetFocus.setEnabled(b)
        self.pushButton_testSetFocus.setEnabled(b)
        self.pushButton_testRunAutofocus.setEnabled(b)
        self.pushButton_testRunAutostig.setEnabled(b)
        self.pushButton_testRunAutofocusStig.setEnabled(b)
        self.pushButton_testRunAutofocusMapfost.setEnabled(b)
        self.pushButton_testZeissAPIVersion.setEnabled(b)
        self.pushButton_testGetStage.setEnabled(b)
        self.pushButton_testSetStage.setEnabled(b)
        self.pushButton_testNearKnife.setEnabled(b)
        self.pushButton_testClearKnife.setEnabled(b)
        self.pushButton_testGetMillPos.setEnabled(b)
        self.pushButton_testMoveMillPos.setEnabled(b)
        self.pushButton_testMovePriorMillPos.setEnabled(b)
        self.pushButton_testStopDMScript.setEnabled(b)
        self.pushButton_testPlasmaCleaner.setEnabled(b)
        self.pushButton_testMotors.setEnabled(b)
        self.pushButton_testSendCommand.setEnabled(b)

    def restrict_gui_for_simulation_mode(self):
        self.pushButton_SEMSettings.setEnabled(False)
        self.pushButton_startAcq.setEnabled(False)
        self.pushButton_doApproach.setEnabled(False)
        self.pushButton_doSweep.setEnabled(False)
        self.pushButton_grabFrame.setEnabled(False)
        self.pushButton_EHTToggle.setEnabled(False)
        self.actionSEMSettings.setEnabled(False)
        self.actionStageCalibration.setEnabled(False)
        self.actionPlasmaCleanerSettings.setEnabled(False)
        # Tests and focus tool
        self.restrict_focus_tool_gui(True)
        self.restrict_tests_gui(True)

    def restrict_gui_for_sem_stage(self):
        self.pushButton_doApproach.setEnabled(False)
        self.pushButton_doSweep.setEnabled(False)
        self.pushButton_testNearKnife.setEnabled(False)
        self.pushButton_testClearKnife.setEnabled(False)
        self.pushButton_testStopDMScript.setEnabled(False)
        self.checkBox_useDebrisDetection.setEnabled(False)
        self.toolButton_debrisDetection.setEnabled(False)
        self.actionCutDuration.setEnabled(False)

    def restrict_gui_wo_gcib(self):
        self.pushButton_testGetMillPos.setEnabled(False)
        self.pushButton_testMoveMillPos.setEnabled(False)
        self.pushButton_testMovePriorMillPos.setEnabled(False)

    #TODO: remove
    def add_to_log(self, text):
        """Update the log from the main thread."""
        self.textarea_log.appendPlainText(utils.format_log_entry(text))

    def write_current_log_to_file(self, filename):
        with open(filename, 'w') as f:
            f.write(self.textarea_log.toPlainText())

# ====================== Below: Manual SBEM commands ===========================

    def manual_sweep(self):
        user_reply = QMessageBox.question(
            self, 'Sweep surface',
            'This will perform a sweep cycle.\n\nDo you wish to proceed?',
            QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            # Perform sweep: do a cut slightly above current surface
            utils.log_info('KNIFE', 'Performing user-requested sweep.')
            self.restrict_gui(True)
            self.viewport.restrict_gui(True)
            QApplication.processEvents()
            utils.run_log_thread(acq_func.manual_sweep,
                                 self.microtome,
                                 self.trigger)
            self.set_status('Busy.', 'Sweep in progress...', True)

    def manual_sweep_success(self, success):
        self.show_current_stage_z()
        if success:
            utils.log_info('KNIFE', 'User-requested sweep completed.')
        else:
            utils.log_error('KNIFE', 'ERROR ocurred during sweep.')
            QMessageBox.warning(self, 'Error during sweep',
                'An error occurred during the sweep cycle. '
                'Please check the microtome status in DM '
                'and the current Z position.', QMessageBox.Ok)
        self.restrict_gui(False)
        self.viewport.restrict_gui(False)
        self.set_status('', 'Ready.', False)

    def save_viewport_screenshot(self):
        file_name, ok_button_clicked = QInputDialog.getText(
            self, 'Save current viewport screenshot as',
            'File name (.png will be added; File will be saved in '
            'current base directory): ', QLineEdit.Normal, 'current_viewport')
        if ok_button_clicked:
            self.viewport.grab_viewport_screenshot(
                os.path.join(self.acq.base_dir, file_name + '.png'))
            utils.log_info(
                'CTRL', 'Saved screenshot of current Viewport to base directory.')

# ======================= Test functions in third tab ==========================

    def test_get_mag(self):
        mag = self.sem.get_mag()
        utils.log_info('SEM', 'Current magnification: ' + '{0:.2f}'.format(mag))

    def test_set_mag(self):
        self.sem.set_mag(1000)
        if self.sem.error_state != Error.none:
            utils.log_error('SEM', '' + self.sem.error_info)
            self.sem.reset_error_state()
        else:
            utils.log_info('SEM', 'Magnification set to 1000.00')

    def test_get_wd(self):
        wd = self.sem.get_wd()
        utils.log_info(
            'SEM', 'Current working distance in mm: '
            + '{0:.4f}'.format(wd * 1000))

    def test_set_wd(self):
        self.sem.set_wd(0.006)
        if self.sem.error_state != Error.none:
            utils.log_error('SEM', '' + self.sem.error_info)
            self.sem.reset_error_state()
        else:
            utils.log_info('SEM', 'Working distance set to 6 mm.')

    def test_autofocus(self):
        self.sem.run_autofocus()
        utils.log_info('SEM', 'SmartSEM autofocus routine called.')

    def test_autostig(self):
        self.sem.run_autostig()
        utils.log_info('SEM', 'SmartSEM autostig routine called.')

    def test_autofocus_stig(self):
        self.sem.run_autofocus_stig()
        utils.log_info('SEM', 'SmartSEM autofocus and autostig routine called.')

    def test_autofocus_mapfost(self):
        self.autofocus.run_mapfost_af()
        utils.log_info('SEM', 'MAPFoSt autofocus called.')

    def test_zeiss_api_version(self):
        self.sem.show_about_box()

    def test_get_stage(self):
        try:
            current_pos = self.microtome.stage.get_stage_xyztr()
        except AttributeError:
            current_pos = self.stage.get_xy()
        if current_pos is not None:
            pos_fmt = [f"{p:.2f}" for p in current_pos]
            if len(current_pos) > 2:
                utils.log_info(
                    f'{self.stage}: Current XYZTR parameters: {pos_fmt}')
            else:
                utils.log_info(
                    f'{self.stage}: Current XY parameters: {pos_fmt}')
        else:
            utils.log_error(
                'STAGE: Error - could not read current X position.')

    def test_set_stage(self):
        current_x = self.stage.get_x()
        self.stage.move_to_x(current_x + 10)
        utils.log_info(
            'STAGE: New X position should be: '
            + '{0:.2f}'.format(current_x + 10))

    def test_near_knife(self):
        if self.use_microtome:
            user_reply = QMessageBox.question(
                self, 'Move knife to "Near" position',
                    'Please confirm that you want to move the knife to the '
                    '"Near" position.',
                    QMessageBox.Ok | QMessageBox.Cancel)
            if user_reply == QMessageBox.Cancel:
                return
            self.microtome.near_knife()
            utils.log_info('KNIFE', 'Position should be NEAR.')
        else:
            utils.log_warning('CTRL', 'No microtome, or microtome not active.')

    def test_clear_knife(self):
        if self.use_microtome:
            self.microtome.clear_knife()
            utils.log_info('KNIFE', 'Position should be CLEAR.')
        else:
            utils.log_warning('CTRL', 'No microtome, or microtome not active.')

    def test_get_mill_pos(self):
        if self.use_microtome:
            pos_fmt = [f"{p:.2f}" for p in self.microtome.xyzt_milling]
            utils.log_info('GCIB', f'Mill position (XYZT) {pos_fmt}.')
        else:
            utils.log_warning('CTRL', 'No microtome, or microtome not active.')

    def test_set_mill_pos(self):
        if self.use_microtome:
            self.microtome.move_stage_to_millpos()
            if self.microtome.error_state != 0:
                utils.log_info('CTRL', f'Microtome error {self.microtome.error_state}: {self.microtome.error_info}')
                self.microtome.reset_error_state()
        else:
            utils.log_warning('CTRL', 'No microtome, or microtome not active.')

    def test_set_pos_prior_mill_mov(self):
        if self.use_microtome:
            self.microtome.move_stage_to_pos_prior_mill_mov()
            if self.microtome.error_state != 0:
                utils.log_info('CTRL', f'Microtome error {self.microtome.error_state}: {self.microtome.error_info}')
                self.microtome.reset_error_state()
        else:
            utils.log_warning('CTRL', 'No microtome, or microtome not active.')

    def test_stop_dm_script(self):
        if self.use_microtome:
            self.microtome.stop_script()
            utils.log_info('CTRL', 'STOP command sent to DM script.')
        else:
            utils.log_warning('CTRL', 'No microtome, or microtome not active.')

    def test_send_email(self):
        """Send test e-mail to the specified user email addresses."""
        utils.log_info('CTRL', 'Trying to send test e-mail.')
        success, error_msg = self.notifications.send_email(
            'Test mail', 'This mail was sent for testing purposes.')
        if success:
            utils.log_info('CTRL', 'E-mail was sent via '
                            + self.notifications.smtp_server)
            QMessageBox.information(
                self, 'E-mail test',
                'E-mail was sent via ' + self.notifications.smtp_server
                + ' to ' + str(self.notifications.user_email_addresses)
                + '. Check your inbox.',
                QMessageBox.Ok)
        else:
            utils.log_error('CTRL', 'Error: Could not send e-mail.')
            QMessageBox.warning(
                self, 'E-mail test failed',
                'A error occurred while trying to send a test e-mail to '
                + str(self.notifications.user_email_addresses) + ' via '
                + self.notifications.smtp_server
                + ': ' + error_msg,
                QMessageBox.Ok)

    def test_plasma_cleaner(self):
        if self.plc_installed:
            utils.log_info(
                'CTRL', 'Testing serial connection to plasma cleaner.')
            utils.log_info('CTRL', '' + self.plasma_cleaner.version())
        else:
            utils.log_error('CTRL', 'Plasma cleaner not installed/activated.')

    def test_server_request(self):
        url = self.cfg['sys']['metadata_server_url'] + '/version'
        status, command, msg = utils.meta_server_get_request(url)
        if status == 100:
            QMessageBox.warning(self, 'Server test',
                                'Server test failed. Server probably '
                                'not active.',
                                QMessageBox.Ok)
        else:
            QMessageBox.information(self, 'Server test',
                                    'Version: ' + str(msg),
                                    QMessageBox.Ok)

    def debris_detection_test(self):
        # Uses overview images t1.tif and t2.tif in current base directory
        # to run the debris detection in the current detection area.
        test_image1 = os.path.join(self.acq.base_dir, 't1.tif')
        test_image2 = os.path.join(self.acq.base_dir, 't2.tif')

        if os.path.isfile(test_image1) and os.path.isfile(test_image2):
            self.img_inspector.process_ov(test_image1, 0, 0)
            self.img_inspector.process_ov(test_image2, 0, 1)
            # Run the tests
            debris_detected0, msg0 = self.img_inspector.detect_debris(0, 0)
            debris_detected1, msg1 = self.img_inspector.detect_debris(0, 1)
            debris_detected2, msg2 = self.img_inspector.detect_debris(0, 2)
            QMessageBox.information(
                self, 'Debris detection test results',
                'Method 0:\n' + str(debris_detected0) + '; ' + msg0
                + '\nThresholds were (mean/stddev): '
                + str(self.img_inspector.mean_diff_threshold)
                + ', ' + str(self.img_inspector.stddev_diff_threshold)
                + '\n\nMethod 1: ' + str(debris_detected1) + '; ' + msg1
                + '\n\nMethod 2: ' + str(debris_detected2) + '; ' + msg2,
                QMessageBox.Ok)
            # Clean up:
            self.img_inspector.discard_last_ov(0)
            self.img_inspector.discard_last_ov(0)
        else:
            QMessageBox.warning(
                self, 'Debris detection test',
                'This test expects two test overview images (t1.tif and '
                't2.tif) in the current base directory.',
                QMessageBox.Ok)

    def custom_test(self):
        # Used for custom tests...
        pass

# ==============================================================================

    def initialize_plasma_cleaner(self):
        if not self.plc_initialized:
            result = QMessageBox.question(
                self, 'initialising plasma cleaner',
                'Is the plasma cleaner GV10x DS connected and switched on?',
                QMessageBox.Yes| QMessageBox.No)
            if result == QMessageBox.Yes:
                self.plasma_cleaner = PlasmaCleaner(
                    self.cfg['sys']['plc_com_port'])
                if self.plasma_cleaner.connection_established():
                    utils.log_info('CTRL', 'Plasma cleaner initialised, ver. '
                                    + self.plasma_cleaner.version()[0])
                    self.plc_initialized = True
                    self.open_plasma_cleaner_dlg()
                else:
                    utils.log_error(
                        'CTRL', 'Error: Plasma cleaner could not be initialised')
        else:
            self.open_plasma_cleaner_dlg()

    def start_acquisition(self):
        """Start or restart an acquisition. This function is called when user
           clicks on start button. All functionality is contained
           in module stack_acquisition.py
        """
        if (self.acq.slice_counter > self.acq.number_slices
                and self.acq.number_slices != 0):
            QMessageBox.information(
                self, 'Check Slice Counter',
                'Slice counter is larger than maximum slice number. Please '
                'adjust the slice counter.',
                QMessageBox.Ok)
        elif (self.acq.slice_counter == self.acq.number_slices
                and self.acq.number_slices != 0):
            QMessageBox.information(
                self, 'Target number of slices reached',
                'The target number of slices has been acquired. Please click '
                '"Reset" to start a new stack.',
                QMessageBox.Ok)
        elif self.cfg_file == 'default.ini':
            QMessageBox.information(
                self, 'Save configuration under new name',
                'Please save the current configuration file "default.ini" '
                'under a new name before starting the stack.',
                QMessageBox.Ok)
        elif (self.acq.use_email_monitoring
                and self.notifications.remote_commands_enabled
                and not self.notifications.remote_cmd_email_pw):
            QMessageBox.information(
                self, 'Password missing',
                'You have enabled remote commands via e-mail (see e-mail '
                'monitoring settings), but have not provided a password!',
                QMessageBox.Ok)
        elif self.sem.is_eht_off():
            QMessageBox.information(
                self, 'EHT off',
                'EHT / high voltage is off. Please turn '
                'it on before starting the acquisition.',
                QMessageBox.Ok)
        else:
            self.restrict_gui(True)
            self.viewport.restrict_gui(True)
            self.pushButton_startAcq.setText('START')
            self.pushButton_startAcq.setEnabled(False)
            self.pushButton_pauseAcq.setEnabled(True)
            self.pushButton_resetAcq.setEnabled(False)
            self.show_stack_acq_estimates()
            # Indicate in GUI that stack is running now
            self.set_status(
                'Acquisition in progress', 'Acquisition in progress.', True)

            # Start the thread running the stack acquisition
            # All source code in stack_acquisition.py
            # Thread is stopped by either stop or pause button
            utils.run_log_thread(self.acq.run)

    def pause_acquisition(self):
        """Pause the acquisition after user has clicked 'Pause' button. Let
        user decide whether to stop immediately or after finishing current
        slice.
        """
        if not self.acq.acq_paused:
            dialog = PauseDlg()
            dialog.exec_()
            pause_type = dialog.pause_type
            if pause_type == 1 or pause_type == 2:
                utils.log_info('CTRL', 'PAUSE command received.')
                self.pushButton_pauseAcq.setEnabled(False)
                self.acq.pause_acquisition(pause_type)
                self.pushButton_startAcq.setText('CONTINUE')
                QMessageBox.information(
                    self, 'Acquisition being paused',
                    'Please wait until the pause status is confirmed in '
                    'the log before interacting with the program.',
                    QMessageBox.Ok)

    def reset_acquisition(self):
        """Reset the acquisition status."""
        result = QMessageBox.question(
                    self, 'Reset stack',
                    'Are you sure you want to reset the stack? The slice '
                    'counter and ∆z will be set to zero. If the '
                    'current acquisition is paused or interrupted, the '
                    'status information of the current slice will be '
                    'deleted.',
                    QMessageBox.Yes| QMessageBox.No)
        if result == QMessageBox.Yes:
            utils.log_info('CTRL', 'RESET command received.')
            result = QMessageBox.question(
                         self, 'Clear tile previews and overview images?',
                         'Would you like all current tile previews and '
                         'overview images in the Viewport to be cleared?',
                         QMessageBox.Yes| QMessageBox.No)
            if result == QMessageBox.Yes:
                for grid_index in range(self.gm.number_grids):
                    self.gm[grid_index].clear_all_tile_previews()
                for ov_index in range(self.ovm.number_ov):
                    self.ovm[ov_index].vp_file_path = ''
                self.viewport.vp_draw()
            self.acq.reset_acquisition()
            self.pushButton_resetAcq.setEnabled(False)
            self.pushButton_pauseAcq.setEnabled(False)
            self.pushButton_startAcq.setEnabled(True)
            self.label_sliceCounter.setText('---')
            self.progressBar.setValue(0)
            self.show_stack_acq_estimates()
            self.pushButton_startAcq.setText('START')

    def completion_stop(self):
        utils.log_info('CTRL', 'Target slice number reached.')
        self.pushButton_resetAcq.setEnabled(True)
        QMessageBox.information(
            self, 'Acquisition complete',
            'The stack has been acquired.',
            QMessageBox.Ok)

    def remote_stop(self):
        utils.log_info('CTRL', 'STOP/PAUSE command received remotely.')
        self.pushButton_resetAcq.setEnabled(True)
        self.pushButton_pauseAcq.setEnabled(False)
        self.pushButton_startAcq.setEnabled(True)
        self.pushButton_startAcq.setText('CONTINUE')
        QMessageBox.information(
            self, 'Acquisition stopped',
            'Acquisition was stopped remotely.',
            QMessageBox.Ok)

    def error_pause(self):
        """Notify user in main window that an error has occurred. All error
           handling inside stack_acquisition.py.
        """
        self.pushButton_resetAcq.setEnabled(True)
        self.pushButton_pauseAcq.setEnabled(False)
        self.pushButton_startAcq.setText('CONTINUE')
        QMessageBox.information(
            self, 'ERROR: Acquisition paused',
            f'Error {self.acq.error_state} '
            f'({utils.Errors[self.acq.error_state]}) has occurred '
            f'(see log). Acquisition has been paused.',
            QMessageBox.Ok)

    def acq_not_in_progress_update_gui(self):
        self.restrict_gui(False)
        self.viewport.restrict_gui(False)
        self.pushButton_startAcq.setEnabled(True)
        self.pushButton_pauseAcq.setEnabled(False)
        if self.acq.acq_paused:
            self.pushButton_resetAcq.setEnabled(True)

    def leave_simulation_mode(self):
        reply = QMessageBox.information(
            self, 'Deactivate simulation mode',
            'Click OK to deactivate simulation mode and save the current '
            'settings. \nPlease note that you have to restart SBEMimage '
            'for the change to take effect.',
            QMessageBox.Ok | QMessageBox.Cancel)
        if reply == QMessageBox.Ok:
            self.simulation_mode = False
            self.actionLeaveSimulationMode.setEnabled(False)
            self.save_settings()

    def save_settings(self):
        if self.cfg_file != 'default.ini':
            self.save_config_to_disk()
        elif self.acq.acq_paused:
            QMessageBox.information(
                self, 'Cannot save configuration',
                'The current configuration file "default.ini" cannot be '
                'modified. To save the current configuration to a new file '
                'name, please select "Save as new configuration file" from '
                'the menu.',
                QMessageBox.Ok)

    def save_config_to_disk(self):
        """Save the updated ConfigParser objects for the user and the
        system configuration to disk.
        """
        self.acq.save_to_cfg()
        self.gm.save_to_cfg()
        self.ovm.save_to_cfg()
        self.imported.save_to_cfg()
        self.autofocus.save_to_cfg()
        self.sem.save_to_cfg()
        if self.microtome is not None:
            self.microtome.save_to_cfg()
        self.cs.save_to_cfg()
        self.viewport.save_to_cfg()
        self.img_inspector.save_to_cfg()
        self.notifications.save_to_cfg()
        # Save settings from Main Controls
        self.cfg['sys']['simulation_mode'] = str(self.simulation_mode)

        # Write config to disk:
        with open(os.path.join('..', 'cfg', self.cfg_file), 'w') as f:
            self.cfg.write(f)
        # Also save system settings:
        with open(os.path.join(
            '..', 'cfg', self.cfg['sys']['sys_config_file']), 'w') as f:
            self.syscfg.write(f)
        utils.log_info('CTRL', 'Settings saved to disk.')

    def closeEvent(self, event):
        if self.microtome is not None and self.microtome.error_state == Error.configuration:
            if self.sem.sem_api is not None:
                self.sem.disconnect()
            print('\n\nError in configuration file. Aborted.\n')
            event.accept()
            sys.exit()
        elif not self.busy:
            result = QMessageBox.question(
                self, 'Exit',
                'Are you sure you want to exit the program?',
                QMessageBox.Yes| QMessageBox.No)
            if result == QMessageBox.Yes:
                if not self.simulation_mode:
                    if (self.use_microtome
                            and self.microtome.device_name == 'Gatan 3View'):
                        self.microtome.stop_script()
                        utils.log_info('CTRL', 'Disconnected from DM/3View.')
                    elif (self.use_microtome
                        and self.microtome.device_name == 'ConnectomX katana'):
                        self.microtome.disconnect()
                    if self.sem.sem_api is not None:
                        self.sem.disconnect()
                if self.plc_initialized:
                    plasma_log_msg = self.plasma_cleaner.close_port()
                    utils.log_info(plasma_log_msg)
                if self.acq.acq_paused:
                    if not(self.cfg_file == 'default.ini'):
                        QMessageBox.information(
                            self, 'Resume acquisition later',
                            'The current acquisition is paused. The current '
                            'settings and acquisition status will be saved '
                            'now, so that the acquisition can be resumed '
                            'after restarting the program with the current '
                            'configuration file.',
                            QMessageBox.Ok)
                        self.save_settings()
                    else:
                        result = QMessageBox.question(
                            self, 'Save settings?',
                            'Do you want to save the current settings to a '
                            'new configuration file?',
                            QMessageBox.Yes| QMessageBox.No)
                        if result == QMessageBox.Yes:
                            self.open_save_settings_new_file_dlg()
                else:
                    if not(self.cfg_file == 'default.ini'):
                        result = QMessageBox.question(
                            self, 'Save settings?',
                            'Do you want to save the current settings '
                            'to the configuration file '
                            + self.cfg_file + '? ',
                            QMessageBox.Yes| QMessageBox.No)
                        if result == QMessageBox.Yes:
                            self.save_settings()
                    else:
                        result = QMessageBox.question(
                            self, 'Save settings?',
                            'Do you want to save the current '
                            'settings to a new configuration file? ',
                            QMessageBox.Yes| QMessageBox.No)
                        if result == QMessageBox.Yes:
                            self.open_save_settings_new_file_dlg()
                self.viewport.active = False
                self.viewport.close()
                QApplication.processEvents()
                sleep(1)
                # Recreate status.dat to indicate that program was closed
                # normally and didn't crash:
                status_file = open('..\\cfg\\status.dat', 'w+')
                status_file.write(self.cfg_file)
                status_file.close()
                print('Closed by user.\n')
                event.accept()
            else:
                event.ignore()
        else:
            QMessageBox.information(
                self, 'Program busy',
                'SBEMimage is currently busy. Please wait until the current '
                'action is completed, or pause/abort the action.',
                QMessageBox.Ok)
            event.ignore()

# ===================== Below: Focus Tool (ft) functions =======================

    def ft_initialize(self):
        """Initialize the Focus Tool's control variables and GUI elements."""
        # Focus tool (ft) control variables
        self.ft_mode = 0  # see ft_start() for explanation
        self.ft_selected_grid = 0
        self.ft_selected_tile = -1  # -1: none selected
        self.ft_selected_ov = -1
        self.ft_selected_wd = None
        self.ft_selected_stig_x = None
        self.ft_selected_stig_y = None
        self.ft_cycle_counter = 0
        self.ft_zoom = False
        self.ft_use_current_position = False
        self.checkBox_useCurrentPos.stateChanged.connect(
            self.ft_toggle_use_current_position)

        # self.ft_locations: Focus locations around the centre of the selected
        # tile / starting position. The first cycle uses the centre coordinates.
        # For the following cycles, the stage is moved to neighbouring locations
        # in a clockwise direction to avoid (re)focusing on the same area of
        # the sample.
        self.ft_locations = [
            (0, 0),
            (600, 0),
            (600, 450),
            (0, 450),
            (-600, 450),
            (-600, 0),
            (-600, -450),
            (0, 450),
            (600, 450)]

        # Focus tool buttons
        self.pushButton_focusToolStart.clicked.connect(self.ft_start)
        self.pushButton_focusToolMove.clicked.connect(self.ft_open_move_dlg)
        self.pushButton_focusToolSet.clicked.connect(
            self.ft_open_set_params_dlg)
        self.pushButton_moveUp.clicked.connect(self.ft_move_up)
        self.pushButton_moveDown.clicked.connect(self.ft_move_down)
        # Default pixel size is 6 nm.
        self.spinBox_ftPixelSize.setValue(6)
        # Default dwell time is dwell time selector 4
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        self.comboBox_dwellTime.setCurrentIndex(4)
        # Selectors
        self.ft_update_grid_selector()
        self.ft_update_tile_selector()
        self.ft_update_ov_selector()
        # Initialize Pixmap for Focus Tool:
        self.ft_clear_display()

    def ft_clear_display(self):
        blank = QPixmap(512, 384)
        blank.fill(QColor(0, 0, 0))
        self.img_focusToolViewer.setPixmap(blank)

    def ft_start(self):
        """Run the through-focus cycle: (1) Move to selected tile or OV.
        (2) Acquire image series at specified settings. (3) Let user select
        the best image.
        """
        if self.ft_mode == 0: # User has clicked on "Run cycle"
            if ((self.ft_selected_tile >=0) or (self.ft_selected_ov >= 0)
                    or self.ft_use_current_position):
                self.ft_run_cycle()
            else:
                QMessageBox.information(
                    self, 'Select tile/OV',
                    'Before starting a through-focus cycle, you must select a '
                    'tile or an overview image, or choose the option "Use '
                    'current stage position".',
                    QMessageBox.Ok)

        elif self.ft_mode == 1:
            # User has clicked 'Done' to select the best focus from the acquired
            # images. The selected working distance is saved for this tile/OV
            # unless 'use current stage position' is selected.
            self.ft_selected_wd += self.ft_fdeltas[self.ft_index]
            self.sem.set_wd(self.ft_selected_wd)
            save_new_wd = True
            if self.ft_use_current_position:
                save_new_wd = self.ft_ask_user_save()
            if save_new_wd:
                if self.ft_selected_ov >= 0:
                    self.ovm[self.ft_selected_ov].wd_stig_xy[0] = (
                        self.ft_selected_wd)
                elif self.ft_selected_tile >= 0:
                    self.gm[self.ft_selected_grid][self.ft_selected_tile].wd = (
                        self.ft_selected_wd)
                    if self.gm[self.ft_selected_grid].use_wd_gradient:
                        # Recalculate with new wd
                        self.gm[self.ft_selected_grid].calculate_wd_gradient()
                    self.viewport.vp_draw()
            self.ft_reset()

        elif self.ft_mode == 2:
            # User has clicked 'Done' to select the best stigmation (X)
            # parameter. The selected stig_x parameter is saved.
            self.ft_selected_stig_x += self.ft_sdeltas[self.ft_index]
            self.sem.set_stig_x(self.ft_selected_stig_x)
            save_new_stig_x = True
            if self.ft_use_current_position:
                save_new_stig_x = self.ft_ask_user_save()
            if save_new_stig_x:
                if self.ft_selected_ov >= 0:
                    self.ovm[self.ft_selected_ov].wd_stig_xy[1] = (
                        self.ft_selected_stig_x)
                elif self.ft_selected_tile >= 0:
                    self.gm[self.ft_selected_grid][
                            self.ft_selected_tile].stig_xy[0] = (
                        self.ft_selected_stig_x)
            self.ft_reset()

        elif self.ft_mode == 3:
            # User has clicked 'Done' to select the best stigmation (Y)
            # parameter. The selected stig_y parameter is saved.
            self.ft_selected_stig_y += self.ft_sdeltas[self.ft_index]
            self.sem.set_stig_y(self.ft_selected_stig_y)
            save_new_stig_y = True
            if self.ft_use_current_position:
                save_new_stig_y = self.ft_ask_user_save()
            if save_new_stig_y:
                if self.ft_selected_ov >= 0:
                    self.ovm[self.ft_selected_ov].wd_stig_xy[2] = (
                        self.ft_selected_stig_y)
                elif self.ft_selected_tile >= 0:
                    self.gm[self.ft_selected_grid][
                            self.ft_selected_tile].stig_xy[1] = (
                        self.ft_selected_stig_y)
            self.ft_reset()

    def ft_ask_user_save(self):
        selected_str = ''
        if self.ft_selected_ov >= 0:
            selected_str = 'overview ' + str(self.ft_selected_ov)
        elif self.ft_selected_tile >= 0:
            selected_str = ('tile ' + str(self.ft_selected_grid)
                            + '.' + str(self.ft_selected_tile))
        if self.ft_mode == 1:
            parameter_str = 'working distance'
        elif self.ft_mode == 2:
            parameter_str = 'X stigmation parameter'
        elif self.ft_mode == 3:
            parameter_str = 'Y stigmation parameter'
        if selected_str:
            user_response = QMessageBox.question(
                self, f'Save updated {parameter_str}?',
                f'Save updated {parameter_str} for selected {selected_str}?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes)
            return (user_response == QMessageBox.Yes)
        else:
            return False

    def ft_open_set_params_dlg(self):
        """Open a dialog box to let user manually set the working distance and
        stigmation x/y for the selected tile/OV.
        """
        if (self.ft_selected_tile >=0) or (self.ft_selected_ov >= 0):
            dialog = FTSetParamsDlg(self.sem, self.ft_selected_wd,
                                    self.ft_selected_stig_x,
                                    self.ft_selected_stig_y,
                                    self.simulation_mode)
            if dialog.exec_():
                self.ft_selected_wd = dialog.new_wd
                self.ft_selected_stig_x = dialog.new_stig_x
                self.ft_selected_stig_y = dialog.new_stig_y
                self.ft_update_wd_display()
                self.ft_update_stig_display()
                if self.ft_selected_ov >= 0:
                    self.ovm[self.ft_selected_ov].wd_stig_xy = [
                        self.ft_selected_wd,
                        self.ft_selected_stig_x,
                        self.ft_selected_stig_y]
                elif self.ft_selected_tile >= 0:
                    self.gm[self.ft_selected_grid][self.ft_selected_tile].wd = (
                        self.ft_selected_wd)
                    self.gm[self.ft_selected_grid][
                            self.ft_selected_tile].stig_xy = (
                        [self.ft_selected_stig_x, self.ft_selected_stig_y])
                    if self.gm[self.ft_selected_grid].use_wd_gradient:
                        # Recalculate with new wd:
                        self.gm[self.ft_selected_grid].calculate_wd_gradient()
                    self.viewport.vp_draw()
                # Set SEM to new values
                self.sem.set_wd(self.ft_selected_wd)
                self.sem.set_stig_xy(
                    self.ft_selected_stig_x, self.ft_selected_stig_y)
        else:
            QMessageBox.information(
                self, 'Select target tile/OV',
                'To manually set WD/stigmation parameters, you must first '
                'select a tile or an overview.',
                QMessageBox.Ok)

    def ft_show_updated_stage_position(self):
        # Update stage position in main controls tab
        self.show_current_stage_xy()
        # Activate stage position indicator if not active already
        if not self.viewport.show_stage_pos:
            self.viewport.vp_activate_checkbox_show_stage_pos()
        # Set zoom
        self.cs.vp_scale = 8
        self.viewport.vp_adjust_zoom_slider()
        # Recentre at current stage position and redraw
        self.cs.vp_centre_dx_dy = self.cs.convert_to_d(self.stage.last_known_xy)
        self.viewport.vp_draw()

    def ft_open_move_dlg(self):
        """Open dialog box to let user manually move to the stage position of
        the currently selected tile/OV without acquiring a through-focus
        series. This can be used to move to a tile position to focus with the
        SEM control software and then manually set the tile/OV to the new focus
        parameters."""
        if (self.ft_selected_tile >=0) or (self.ft_selected_ov >= 0):
            dialog = FTMoveDlg(self.microtome, self.cs, self.gm,
                               self.ft_selected_grid, self.ft_selected_tile,
                               self.ft_selected_ov)
            if dialog.exec_():
                self.ft_cycle_counter = 0
                self.ft_show_updated_stage_position()
        else:
            QMessageBox.information(
                self, 'Select tile/OV',
                'You must first select a tile or an overview to use the '
                '"Move" function.',
                QMessageBox.Ok)

    def ft_run_cycle(self):
        """Restrict the GUI, read the cycle parameters from the GUI, and
        launch the cycle (stage move followed by through-focus acquisition)
        in a thread.
        """
        self.set_status(
            'Busy.', 'Focus tool image acquisition in progress...', True)
        self.pushButton_focusToolStart.setText('Busy')
        self.pushButton_focusToolStart.setEnabled(False)
        self.pushButton_focusToolMove.setEnabled(False)
        self.pushButton_focusToolSet.setEnabled(False)
        self.spinBox_ftPixelSize.setEnabled(False)
        self.checkBox_useCurrentPos.setEnabled(False)
        self.comboBox_dwellTime.setEnabled(False)
        self.verticalSlider_ftDelta.setEnabled(False)
        self.radioButton_focus.setEnabled(False)
        self.radioButton_stigX.setEnabled(False)
        self.radioButton_stigY.setEnabled(False)
        self.comboBox_selectGridFT.setEnabled(False)
        self.comboBox_selectTileFT.setEnabled(False)
        self.comboBox_selectOVFT.setEnabled(False)
        # Disable menu
        self.menubar.setEnabled(False)
        # Disable the other tabs:
        self.tabWidget.setTabEnabled(0, False)
        self.tabWidget.setTabEnabled(2, False)
        # Restrict viewport:
        self.viewport.restrict_gui(True)
        # Use current WD/Stig if selected working distance == 0 or None:
        if self.ft_selected_wd is None or self.ft_selected_wd == 0:
            self.ft_selected_wd = self.sem.get_wd()
            self.ft_selected_stig_x, self.ft_selected_stig_y = (
                self.sem.get_stig_xy())
        self.ft_pixel_size = self.spinBox_ftPixelSize.value()
        self.ft_dwell_time = self.sem.DWELL_TIME[
            self.comboBox_dwellTime.currentIndex()]
        self.ft_slider_delta = self.verticalSlider_ftDelta.value() + 1
        self.ft_clear_display()
        QApplication.processEvents()
        utils.run_log_thread(self.ft_move_and_acq_thread)

    def ft_move_and_acq_thread(self):
        """Move to the target stage position with error handling, then acquire
        through-focus series.
        """
        move_success = True
        if not self.ft_use_current_position:
            if self.ft_selected_ov >= 0:
                stage_x, stage_y = self.ovm[self.ft_selected_ov].centre_dx_dy
            elif self.ft_selected_tile >= 0:
                stage_x, stage_y = self.cs.convert_to_d(
                    self.gm[self.ft_selected_grid][self.ft_selected_tile].sx_sy)
            # Get the shifts for the current focus area and add them to the
            # centre coordinates in the SEM coordinate system. Then convert to
            # stage coordinates and move.
            delta_x, delta_y = self.ft_locations[self.ft_cycle_counter]
            stage_x += delta_x * self.ft_pixel_size/1000
            stage_y += delta_y * self.ft_pixel_size/1000
            stage_x, stage_y = self.cs.convert_to_s((stage_x, stage_y))
            self.stage.move_to_xy((stage_x, stage_y))
            if self.stage.error_state != Error.none:
                self.stage.reset_error_state()
                # Try again
                sleep(2)
                self.stage.move_to_xy((stage_x, stage_y))
                if self.stage.error_state != Error.none:
                    move_success = False
                    utils.log_error('STAGE: Failed to move to selected '
                                    'tile/OV for focus tool cycle.')

        # Use signal for update because we are in the focus tool acq thread
        self.trigger.transmit('UPDATE XY FT')
        if move_success:
            if self.radioButton_focus.isChecked():
                self.ft_delta = (
                    0.00000004 * self.ft_slider_delta * self.ft_pixel_size)
                self.ft_acquire_focus_series()

            if self.radioButton_stigX.isChecked():
                self.ft_delta = (
                    0.008 * self.ft_slider_delta * self.ft_pixel_size)
                self.ft_acquire_stig_series(0)

            if self.radioButton_stigY.isChecked():
                self.ft_delta = (
                    0.008 * self.ft_slider_delta * self.ft_pixel_size)
                self.ft_acquire_stig_series(1)
        else:
            self.ft_reset()

    def ft_reset(self):
        """Reset focus tool GUI to starting configuration."""
        self.pushButton_focusToolStart.setText('Run cycle')
        self.pushButton_focusToolStart.setEnabled(True)
        self.pushButton_focusToolMove.setEnabled(True)
        self.pushButton_focusToolSet.setEnabled(True)
        # Arrow keys are disabled
        self.pushButton_moveUp.setEnabled(False)
        self.pushButton_moveDown.setEnabled(False)
        self.spinBox_ftPixelSize.setEnabled(True)
        self.checkBox_useCurrentPos.setEnabled(True)
        self.checkBox_zoom.setEnabled(False)
        self.comboBox_dwellTime.setEnabled(True)
        self.verticalSlider_ftDelta.setEnabled(True)
        self.radioButton_focus.setEnabled(True)
        self.radioButton_stigX.setEnabled(True)
        self.radioButton_stigY.setEnabled(True)
        if not self.ft_use_current_position:
            self.comboBox_selectGridFT.setEnabled(True)
            self.comboBox_selectTileFT.setEnabled(True)
            self.comboBox_selectOVFT.setEnabled(True)
        # Enable menu
        self.menubar.setEnabled(True)
        # Enable the other tabs:
        self.tabWidget.setTabEnabled(0, True)
        self.tabWidget.setTabEnabled(2, True)
        # Unrestrict viewport:
        self.viewport.restrict_gui(False)
        self.ft_mode = 0

    def ft_series_complete(self):
        self.set_status(
            '', 'Ready.', False)
        self.pushButton_focusToolStart.setText('Done')
        self.pushButton_focusToolStart.setEnabled(True)
        # Enable arrow keys and zoom checkbox
        self.pushButton_moveUp.setEnabled(True)
        self.pushButton_moveDown.setEnabled(True)
        self.checkBox_zoom.setEnabled(True)
        # Increase counter to move to fresh area for next cycle:
        self.ft_cycle_counter += 1
        # Go back to the centre after a full clockwise cycle
        if self.ft_cycle_counter > 8:
            self.ft_cycle_counter = 0

    def ft_acquire_focus_series(self):
        """Acquire through-focus series."""
        self.sem.apply_frame_settings(
            1, self.ft_pixel_size, self.ft_dwell_time)
        self.sem.set_beam_blanking(0)
        self.ft_series_img = []
        self.ft_series_wd_values = []
        deltas = [-4, -3, -2, -1, 0, 1, 2, 3, 4]
        self.ft_fdeltas = [self.ft_delta * x for x in deltas]
        for i in range(9):
            self.sem.set_wd(self.ft_selected_wd + self.ft_fdeltas[i])
            self.ft_series_wd_values.append(
                self.ft_selected_wd + self.ft_fdeltas[i])
            filename = os.path.join(
                self.acq.base_dir, 'workspace', 'ft' + str(i) + '.bmp')
            self.sem.acquire_frame(filename)
            self.ft_series_img.append(QPixmap(filename))
        self.sem.set_beam_blanking(1)
        # Display image with current focus:
        self.ft_index = 4
        self.ft_display_during_cycle()
        self.ft_mode = 1
        self.ft_series_complete()

    def ft_acquire_stig_series(self, xy_choice):
        """Acquire image series with incrementally changing XY stigmation
        parameters.
        """
        self.sem.apply_frame_settings(
            1, self.ft_pixel_size, self.ft_dwell_time)
        self.sem.set_beam_blanking(0)
        self.ft_series_img = []
        self.ft_series_stig_x_values = []
        self.ft_series_stig_y_values = []
        deltas = [-4, -3, -2, -1, 0, 1, 2, 3, 4]
        self.ft_sdeltas = [self.ft_delta * x for x in deltas]
        for i in range(9):
            if xy_choice == 0:
                self.sem.set_stig_x(
                    self.ft_selected_stig_x + self.ft_sdeltas[i])
                self.ft_series_stig_x_values.append(
                    self.ft_selected_stig_x + self.ft_sdeltas[i])
            else:
                self.sem.set_stig_y(
                    self.ft_selected_stig_y + self.ft_sdeltas[i])
                self.ft_series_stig_y_values.append(
                    self.ft_selected_stig_y + self.ft_sdeltas[i])
            filename = os.path.join(
                self.acq.base_dir, 'workspace', 'ft' + str(i) + '.bmp')
            self.sem.acquire_frame(filename)
            self.ft_series_img.append(QPixmap(filename))
        self.sem.set_beam_blanking(1)
        # Display image at current stigmation setting:
        self.ft_index = 4
        self.ft_display_during_cycle()
        if xy_choice == 0:
            self.ft_mode = 2
        else:
            self.ft_mode = 3
        self.ft_series_complete()

    def ft_display_during_cycle(self):
        if self.ft_zoom:
            cropped_img = self.ft_series_img[self.ft_index].copy(
                QRect(128, 96, 256, 192))
            self.img_focusToolViewer.setPixmap(cropped_img.scaledToWidth(512))
        else:
            self.img_focusToolViewer.setPixmap(
                self.ft_series_img[self.ft_index])
        # Display current wd/stig settings:
        if self.radioButton_focus.isChecked():
            self.lineEdit_currentFocus.setText('{0:.6f}'.format(
                self.ft_series_wd_values[self.ft_index] * 1000))
        if self.radioButton_stigX.isChecked():
            self.lineEdit_currentStigX.setText('{0:.6f}'.format(
                self.ft_series_stig_x_values[self.ft_index]))
        if self.radioButton_stigY.isChecked():
            self.lineEdit_currentStigY.setText('{0:.6f}'.format(
                self.ft_series_stig_y_values[self.ft_index]))

    def ft_move_up(self):
        if self.ft_mode > 0:
            if self.ft_index < 8:
                self.ft_index += 1
                self.ft_display_during_cycle()

    def ft_move_down(self):
        if self.ft_mode > 0:
            if self.ft_index > 0:
                self.ft_index -= 1
                self.ft_display_during_cycle()

    def ft_update_stig_display(self):
        self.lineEdit_currentStigX.setText(
            '{0:.6f}'.format(self.ft_selected_stig_x))
        self.lineEdit_currentStigY.setText(
            '{0:.6f}'.format(self.ft_selected_stig_y))

    def ft_update_wd_display(self):
        self.lineEdit_currentFocus.setText(
            '{0:.6f}'.format(self.ft_selected_wd * 1000))

    def ft_clear_wd_stig_display(self):
        self.lineEdit_currentFocus.setText('')
        self.lineEdit_currentStigX.setText('')
        self.lineEdit_currentStigY.setText('')

    def ft_update_grid_selector(self, grid_index=0):
        if grid_index >= self.gm.number_grids:
            grid_index = 0
        self.comboBox_selectGridFT.blockSignals(True)
        self.comboBox_selectGridFT.clear()
        self.comboBox_selectGridFT.addItems(self.gm.grid_selector_list())
        self.comboBox_selectGridFT.setCurrentIndex(grid_index)
        self.ft_selected_grid = grid_index
        self.comboBox_selectGridFT.currentIndexChanged.connect(
            self.ft_change_grid_selection)
        self.comboBox_selectGridFT.blockSignals(False)

    def ft_update_tile_selector(self, current_tile=-1):
        self.comboBox_selectTileFT.blockSignals(True)
        self.comboBox_selectTileFT.clear()
        # If wd gradient activated for selected grid, only show reference tiles!
        if self.gm[self.ft_selected_grid].use_wd_gradient:
            self.comboBox_selectTileFT.addItems(
                ['Select tile']
                + self.gm[self.ft_selected_grid].wd_gradient_ref_tile_selector_list())
            self.label_AFnotification.setText(
                'Adaptive focus active in this grid.')
        else:
            self.comboBox_selectTileFT.addItems(
                ['Select tile']
                + self.gm[self.ft_selected_grid].tile_selector_list())
            self.label_AFnotification.setText('')

        self.comboBox_selectTileFT.setCurrentIndex(current_tile + 1)
        if (self.gm[self.ft_selected_grid].use_wd_gradient
            and current_tile >= 0):
            self.ft_selected_tile = (
                self.gm[self.ft_selected_grid].wd_gradient_ref_tiles[
                    current_tile])
        else:
            self.ft_selected_tile = current_tile
        self.comboBox_selectTileFT.currentIndexChanged.connect(
            self.ft_load_selected_tile)
        self.comboBox_selectTileFT.blockSignals(False)

    def ft_update_ov_selector(self, ov_index=-1):
        if ov_index >= self.ovm.number_ov:
            ov_index = -1
        self.comboBox_selectOVFT.blockSignals(True)
        self.comboBox_selectOVFT.clear()
        self.comboBox_selectOVFT.addItems(
            ['Select OV'] + self.ovm.ov_selector_list())
        self.comboBox_selectOVFT.setCurrentIndex(ov_index + 1)
        self.ft_selected_ov = ov_index
        self.comboBox_selectOVFT.currentIndexChanged.connect(
            self.ft_load_selected_ov)
        self.comboBox_selectOVFT.blockSignals(False)

    def ft_change_grid_selection(self):
        self.ft_selected_grid = self.comboBox_selectGridFT.currentIndex()
        self.ft_update_tile_selector()

    def ft_load_selected_tile(self):
        current_selection = self.comboBox_selectTileFT.currentIndex() - 1
        if (self.gm[self.ft_selected_grid].use_wd_gradient
            and current_selection >= 0):
            self.ft_selected_tile = (
                self.gm[self.ft_selected_grid].wd_gradient_ref_tiles[
                    current_selection])
        else:
            self.ft_selected_tile = current_selection
        # show current focus and stig:
        if self.ft_selected_tile >= 0:
            self.ft_update_ov_selector(-1)
            self.ft_selected_wd = (
                self.gm[self.ft_selected_grid][self.ft_selected_tile].wd)
            self.ft_selected_stig_x, self.ft_selected_stig_y = (
                self.gm[self.ft_selected_grid][self.ft_selected_tile].stig_xy)
            self.ft_update_wd_display()
            self.ft_update_stig_display()
        elif self.ft_selected_ov == -1:
            self.ft_clear_wd_stig_display()

        if (self.acq.use_autofocus
            and self.gm[self.ft_selected_grid][
                        self.ft_selected_tile].autofocus_active):
            self.label_AFnotification.setText(
                'WD/STIG of selected tile are being tracked.')
        elif self.gm[self.ft_selected_grid].use_wd_gradient:
            self.label_AFnotification.setText(
                'Adaptive focus active in this grid.')
        else:
            self.label_AFnotification.setText('')
        self.ft_cycle_counter = 0
        # Clear current image:
        self.ft_clear_display()

    def ft_load_selected_ov(self):
        self.ft_selected_ov = self.comboBox_selectOVFT.currentIndex() - 1
        if self.ft_selected_ov >= 0:
            self.ft_update_tile_selector(-1)
            (self.ft_selected_wd, self.ft_selected_stig_x,
             self.ft_selected_stig_y) = self.ovm[self.ft_selected_ov].wd_stig_xy
            self.ft_update_wd_display()
            self.ft_update_stig_display()
        elif self.ft_selected_tile == -1:
            self.ft_clear_wd_stig_display()
        self.ft_cycle_counter = 0
        # Clear current image:
        self.ft_clear_display()

    def ft_set_selection_from_viewport(self):
        """Load the tile/OV currently selected by right mouse click and context
        menu in the Viewport.
        """
        selected_ov = self.viewport.selected_ov
        selected_grid = self.viewport.selected_grid
        selected_tile = self.viewport.selected_tile
        if (selected_grid is not None) and (selected_tile is not None):
            self.ft_selected_grid = selected_grid
            if self.gm[selected_grid].use_wd_gradient:
                af_tiles = self.gm[selected_grid].wd_gradient_ref_tiles
                if selected_tile in af_tiles:
                    self.ft_selected_tile = af_tiles.index(selected_tile)
                else:
                    self.ft_selected_tile = -1
            else:
                self.ft_selected_tile = selected_tile
            self.comboBox_selectGridFT.blockSignals(True)
            self.comboBox_selectGridFT.setCurrentIndex(self.ft_selected_grid)
            self.comboBox_selectGridFT.blockSignals(False)
            self.ft_update_tile_selector(self.ft_selected_tile)
            self.comboBox_selectOVFT.blockSignals(True)
            self.comboBox_selectOVFT.setCurrentIndex(0)
            self.comboBox_selectOVFT.blockSignals(False)
            self.ft_load_selected_tile()
            self.ft_selected_ov = -1
        elif selected_ov is not None:
            self.ft_selected_ov = selected_ov
            self.comboBox_selectOVFT.blockSignals(True)
            self.comboBox_selectOVFT.setCurrentIndex(self.ft_selected_ov + 1)
            self.comboBox_selectOVFT.blockSignals(False)
            self.comboBox_selectTileFT.blockSignals(True)
            self.comboBox_selectTileFT.setCurrentIndex(0)
            self.comboBox_selectTileFT.blockSignals(False)
            self.ft_load_selected_ov()
            self.ft_selected_tile = -1
        # Clear current image:
        self.ft_clear_display()
        # Switch to Focus Tool tab:
        self.tabWidget.setCurrentIndex(1)
        self.ft_cycle_counter = 0

    def ft_toggle_zoom(self):
        self.ft_zoom ^= True
        if self.ft_mode > 0:
            self.ft_display_during_cycle()

    def ft_toggle_use_current_position(self):
        self.ft_use_current_position = self.checkBox_useCurrentPos.isChecked()
        # Disable tile/OV selectors if 'use current position' option active
        self.comboBox_selectGridFT.setEnabled(not self.ft_use_current_position)
        self.comboBox_selectTileFT.setEnabled(not self.ft_use_current_position)
        self.comboBox_selectOVFT.setEnabled(not self.ft_use_current_position)

    def keyPressEvent(self, event):
        if (type(event) == QKeyEvent) and (self.tabWidget.currentIndex() == 1):
            if event.key() == Qt.Key_PageUp:
                self.ft_move_up()
            elif event.key() == Qt.Key_PageDown:
                self.ft_move_down()

    def wheelEvent(self, event):
        if self.tabWidget.currentIndex() == 1:
            if event.angleDelta().y() > 0:
                self.ft_move_up()
            elif event.angleDelta().y() < 0:
                self.ft_move_down()
