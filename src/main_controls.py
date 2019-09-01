# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module controls the main window GUI, from which acquisitions are
   started. The window contains three tabs: (1) main controls, settings, stack
   progress and main log; (2) focus tool; (3) functions for testing/debugging.
   This window is a QMainWindow and it launches the Viewport window as a
   QWidget.
"""

import os
import threading
import shutil
import json

from time import sleep
from queue import Queue

from PyQt5.QtWidgets import QApplication, QTableWidgetSelectionRange
from PyQt5.QtCore import QObject, Qt, QRect, QSize, pyqtSignal, QEvent, \
                        QItemSelection, QItemSelectionModel, QModelIndex
from PyQt5.QtGui import QIcon, QPalette, QColor, QPixmap, QKeyEvent, \
                        QStatusTipEvent, \
                        QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QInputDialog, QLineEdit, \
                            QHeaderView
from PyQt5.uic import loadUi

import acq_func
import utils
from sem_control import SEM_SmartSEM
from microtome_control import Microtome_3View
from stage import Stage
from plasma_cleaner import PlasmaCleaner
from stack_acquisition import Stack
from overview_manager import OverviewManager
from grid_manager import GridManager
from coordinate_system import CoordinateSystem
from viewport import Viewport
from image_inspector import ImageInspector
from autofocus import Autofocus
from dlg_windows import SEMSettingsDlg, MicrotomeSettingsDlg, \
                        GridSettingsDlg, AutofocusSettingsDlg, \
                        EmailMonitoringSettingsDlg, DebrisSettingsDlg, \
                        ImageMonitoringSettingsDlg, AcqSettingsDlg, \
                        SaveConfigDlg, PlasmaCleanerDlg, OVSettingsDlg, \
                        ApproachDlg, MirrorDriveDlg, ExportDlg, MotorTestDlg, \
                        CalibrationDlg, MagCalibrationDlg, PreStackDlg, \
                        PauseDlg, StubOVDlg, EHTDlg, GrabFrameDlg, \
                        FTSetParamsDlg, FTMoveDlg, AskUserDlg, \
                        ImportImageDlg, AdjustImageDlg, DeleteImageDlg, \
                        UpdateDlg, CutDurationDlg, GridRotationDlg, AboutBox, \
                        ImportMagCDlg, ImportWaferImageDlg, WaferCalibrationDlg             
                        


class Trigger(QObject):
    # A custom signal for receiving updates and requests from the viewport
    # window and the stack acquisition thread
    s = pyqtSignal()


class MainControls(QMainWindow):

    def __init__(self, config, sysconfig, config_file, VERSION):
        super().__init__()
        self.cfg = config
        self.syscfg = sysconfig
        self.cfg_file = config_file
        self.syscfg_file = self.cfg['sys']['sys_config_file']
        self.VERSION = VERSION
        self.calibration_found = None

        # Show progress of initialization in console window:
        utils.show_progress_in_console(0)
        self.load_gui()
        utils.show_progress_in_console(30)
        self.import_system_settings()
        self.initial_setup()
        # Display all settings read from config file:
        self.show_current_settings()
        self.show_current_stage_xy()
        self.show_current_stage_z()
        utils.show_progress_in_console(80)
        self.show_estimates()
        # Now show main window:
        self.show()
        QApplication.processEvents()
        # Initialize viewport window:
        self.viewport = Viewport(self.cfg, self.sem, self.stage,
                                 self.ovm, self.gm, self.cs, self.af,
                                 self.viewport_trigger,
                                 self.viewport_queue)
        self.viewport.show()
        # Draw the workspace
        self.viewport.mv_draw()

        # Initialize focus tool:
        self.ft_initialize()

        # When simulation mode active, disable all acquisition-related functions
        if self.simulation_mode:
            self.restrict_gui_for_simulation_mode()
        else:
            self.actionLeaveSimulationMode.setEnabled(False)

        utils.show_progress_in_console(100)

        # Finally, check if there is a previous acquisition
        # to be be restarted:
        if self.stack.is_paused():
            self.acq_paused = True
            self.update_stack_progress()
            self.pushButton_startAcq.setText('CONTINUE')
            self.pushButton_resetAcq.setEnabled(True)

        print('\n\nReady.\n')
        self.set_statusbar('Ready.')
        if self.simulation_mode:
            self.add_to_log('CTRL: Simulation mode active.')
            QMessageBox.information(
                self, 'Simulation mode active',
                'SBEMimage is running in simulation mode. You can change most '
                'settings and use the Viewport, but no commands can be sent '
                'to the SEM and the microtome. Stack acquisition is '
                'deactivated.'
                '\n\nTo leave simulation mode, select: '
                '\nMenu  →  Configuration  →  Leave simulation mode',
                QMessageBox.Ok)
        elif not self.calibration_found:
            QMessageBox.warning(
                self, 'Missing stage calibration',
                'No stage calibration settings were found for the currently '
                'selected EHT. Please calibrate the stage:'
                '\nMenu  →  Calibration  →  Stage calibration',
                QMessageBox.Ok)
        # Diplay warning if z coordinate differs from previous session
        if self.use_microtome and self.microtome.get_error_state() == 206:
            self.microtome.reset_error_state()
            QMessageBox.warning(
                self, 'Stage Z position',
                'The current Z position does not match the Z position '
                'recorded in the current configuration file '
                '({0:.3f}).'.format(self.microtome.get_stage_z_prev_session())
                + ' Please make sure that the Z position is correct.',
                QMessageBox.Ok)

        # ------ MagC operations ------
        self.cfg['magc']['selected_sections'] = '[]'
        self.cfg['magc']['checked_sections'] = '[]'
        # for now, start of SBEMimage restarts all sections and wafer_calibration
        self.cfg['magc']['wafer_calibrated'] = 'False'
        # ------ End of MagC operations ------

    def load_gui(self):
        """Load and set up the GUI."""
        loadUi('..\\gui\\main_window.ui', self)
        self.setWindowTitle('SBEMimage - Main Controls')
        app_icon = QIcon()
        app_icon.addFile('..\\img\\icon_16px.ico', QSize(16, 16))
        app_icon.addFile('..\\img\\icon_48px.ico', QSize(48, 48))
        self.setWindowIcon(app_icon)
        self.setFixedSize(self.size())
        self.move(1120, 20)
        self.hide() # hide window until fully initialized
        # # Disable MagC tab at start of the program:
        # self.tabWidget.setTabEnabled(3, False)
        # Pushbuttons
        self.pushButton_SEMSettings.clicked.connect(self.open_sem_dlg)
        self.pushButton_SEMSettings.setIcon(QIcon('..\\img\\settings.png'))
        self.pushButton_SEMSettings.setIconSize(QSize(16, 16))
        self.pushButton_microtomeSettings.clicked.connect(
            self.open_microtome_dlg)
        self.pushButton_microtomeSettings.setIcon(
            QIcon('..\\img\\settings.png'))
        self.pushButton_microtomeSettings.setIconSize(QSize(16, 16))
        self.pushButton_gridSettings.clicked.connect(self.open_grid_dlg)
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
        self.pushButton_doSweep.clicked.connect(self.sweep)
        self.pushButton_grabFrame.clicked.connect(self.open_grab_frame_dlg)
        self.pushButton_saveViewport.clicked.connect(self.save_viewport)
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
        self.actionGridSettings.triggered.connect(self.open_grid_dlg)
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
        self.actionImportMagCMetadata.triggered.connect(
            self.open_magc_import_dlg)
        # Buttons for testing purposes (third tab)
        self.pushButton_testGetMag.clicked.connect(self.test_get_mag)
        self.pushButton_testSetMag.clicked.connect(self.test_set_mag)
        self.pushButton_testGetFocus.clicked.connect(self.test_get_wd)
        self.pushButton_testSetFocus.clicked.connect(self.test_set_wd)
        self.pushButton_testRunAutofocus.clicked.connect(self.test_autofocus)
        self.pushButton_testRunAutostig.clicked.connect(self.test_autostig)
        self.pushButton_testRunAutofocusStig.clicked.connect(
            self.test_autofocus_stig)
        self.pushButton_testZeissAPIVersion.clicked.connect(
            self.test_zeiss_api_version)
        self.pushButton_testGetStage.clicked.connect(self.test_get_stage)
        self.pushButton_testSetStage.clicked.connect(self.test_set_stage)
        self.pushButton_testNearKnife.clicked.connect(self.test_near_knife)
        self.pushButton_testClearKnife.clicked.connect(self.test_clear_knife)
        self.pushButton_testStopDMScript.clicked.connect(
            self.test_stop_dm_script)
        self.pushButton_testSendEMail.clicked.connect(self.test_send_email)
        self.pushButton_testPlasmaCleaner.clicked.connect(
            self.test_plasma_cleaner)
        self.pushButton_testServerRequest.clicked.connect(
            self.test_server_request)
        self.pushButton_testMotors.clicked.connect(self.open_motor_test_dlg)
        self.pushButton_testDebrisDetection.clicked.connect(
            self.debris_detection_test)
        self.pushButton_testCustom.clicked.connect(self.custom_test)
        # Checkboxes:
        self.checkBox_useMonitoring.setChecked(
            self.cfg['acq']['use_email_monitoring'] == 'True')
        self.checkBox_takeOV.setChecked(
            self.cfg['acq']['take_overviews'] == 'True')
        if not self.checkBox_takeOV.isChecked():
            # Deactivate debris detection option when overviews deactivated:
            self.cfg['acq']['use_debris_detection'] = 'False'
            self.checkBox_useDebrisDetection.setChecked(False)
            self.checkBox_useDebrisDetection.setEnabled(False)
        self.checkBox_useDebrisDetection.setChecked(
            self.cfg['acq']['use_debris_detection'] == 'True')
        self.checkBox_askUser.setChecked(
            self.cfg['acq']['ask_user'] == 'True')
        self.checkBox_mirrorDrive.setChecked(
            self.cfg['sys']['use_mirror_drive'] == 'True')
        self.checkBox_monitorTiles.setChecked(
            self.cfg['acq']['monitor_images'] == 'True')
        self.checkBox_useAutofocus.setChecked(
            self.cfg['acq']['use_autofocus'] == 'True')
        if int(self.cfg['autofocus']['method']) == 2:
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
        # Limit the log to user-specified number of most recent lines:
        self.textarea_log.setMaximumBlockCount(
            int(self.cfg['monitoring']['max_log_line_count']))

        #------- GUI for MagC tab ---------------------------------
        # initialize the sectionList (QTableView)
        sectionListModel = QStandardItemModel(0, 0)
        sectionListModel.setHorizontalHeaderItem(0, QStandardItem('Sections'))
        sectionListModel.setHorizontalHeaderItem(1, QStandardItem('State'))
        self.tableView_magc_sectionList.setModel(sectionListModel)
        self.tableView_magc_sectionList.selectionModel().selectionChanged.connect(self.magc_actions_selected_sections_changed)

        header = self.tableView_magc_sectionList.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        # header.setStretchLastSection(True)

        self.tableView_magc_sectionList.doubleClicked.connect(self.double_clicked_section)
        
        # set logo
        self.collectomeLogo.setScaledContents(True)
        self.collectomeLogo.setPixmap(QPixmap(os.path.join('..','img','magc','collectome_logo.png')))

        # initialize other MagC GUI items
        self.pushButton_magc_importMagc.clicked.connect(self.open_magc_import_dlg)
        self.pushButton_magc_waferCalibration.clicked.connect(self.open_magc_wafer_calibration_dlg)
        self.pushButton_magc_resetMagc.clicked.connect(self.reset_magc)
        self.pushButton_magc_selectAll.clicked.connect(self.magc_select_all)
        self.pushButton_magc_deselectAll.clicked.connect(self.magc_deselect_all)
        self.pushButton_magc_checkSelected.clicked.connect(self.magc_check_selected)
        self.pushButton_magc_uncheckSelected.clicked.connect(self.magc_uncheck_selected)
        self.pushButton_magc_invertSelection.clicked.connect(self.magc_invert_selection)
        self.pushButton_magc_selectChecked.clicked.connect(self.magc_select_checked)
        self.pushButton_magc_okStringSections.clicked.connect(self.magc_select_string_sections)
        self.pushButton_magc_importWaferImage.clicked.connect(self.open_import_wafer_image)
        self.pushButton_magc_addSection.clicked.connect(self.add_section)
        if self.cfg['magc']['wafer_calibrated'] == 'False':
            self.pushButton_magc_addSection.setEnabled(False)
        self.pushButton_magc_deleteLastSection.clicked.connect(self.delete_last_section)
        self.waferCalibrationFlag.setStyleSheet('background-color: yellow')
        #------- end of GUI for MagC tab ---------------------------------   
        
    def import_system_settings(self):
        """Import settings from the system configuration file."""
        # Device names
        recognized_devices = json.loads(self.syscfg['device']['recognized'])
        try:
            self.cfg['sem']['device'] = (
                recognized_devices[int(self.syscfg['device']['sem'])])
        except:
            self.cfg['sem']['device'] = 'NOT RECOGNIZED'
        try:
            self.cfg['microtome']['device'] = (
                recognized_devices[int(self.syscfg['device']['microtome'])])
        except:
            self.cfg['microtome']['device'] = 'NOT RECOGNIZED'

        # Get microtome motor limits from system cfg file:
        motor_limits = json.loads(self.syscfg['stage']['microtome_motor_limits'])
        self.cfg['microtome']['stage_min_x'] = str(motor_limits[0])
        self.cfg['microtome']['stage_max_x'] = str(motor_limits[1])
        self.cfg['microtome']['stage_min_y'] = str(motor_limits[2])
        self.cfg['microtome']['stage_max_y'] = str(motor_limits[3])
        # Get SEM motor limits from system cfg file:
        motor_limits = json.loads(self.syscfg['stage']['sem_motor_limits'])
        self.cfg['sem']['stage_min_x'] = str(motor_limits[0])
        self.cfg['sem']['stage_max_x'] = str(motor_limits[1])
        self.cfg['sem']['stage_min_y'] = str(motor_limits[2])
        self.cfg['sem']['stage_max_y'] = str(motor_limits[3])
        # Get microtome motor speeds from system cfg file:
        motor_speed = json.loads(self.syscfg['stage']['microtome_motor_speed'])
        self.cfg['microtome']['motor_speed_x'] = str(motor_speed[0])
        self.cfg['microtome']['motor_speed_y'] = str(motor_speed[1])
        # Get SEM motor speeds from system cfg file:
        motor_speed = json.loads(self.syscfg['stage']['sem_motor_speed'])
        self.cfg['sem']['motor_speed_x'] = str(motor_speed[0])
        self.cfg['sem']['motor_speed_y'] = str(motor_speed[1])
        # Knife settings:
        self.cfg['microtome']['full_cut_duration'] = (
            self.syscfg['knife']['full_cut_duration'])
        self.cfg['microtome']['sweep_distance'] = (
            self.syscfg['knife']['sweep_distance'])
        # Plasma cleaner:
        self.cfg['sys']['plc_installed'] = self.syscfg['plc']['installed']
        self.cfg['sys']['plc_com_port'] = self.syscfg['plc']['com_port']
        # E-Mail settings:
        self.cfg['sys']['email_account'] = self.syscfg['email']['account']
        self.cfg['sys']['email_smtp'] = self.syscfg['email']['smtp_server']
        self.cfg['sys']['email_imap'] = self.syscfg['email']['imap_server']
        # Meta server:
        self.cfg['sys']['metadata_server_url'] = (
            self.syscfg['metaserver']['url'])
        self.cfg['sys']['metadata_server_admin'] = (
            self.syscfg['metaserver']['admin_email'])

    def initial_setup(self):
        """Set up the main control variables, the triggers/queues,
           the instances for controlling the SEM and the 3View. Also create
           instances of the grid manager, OV manager, image_inspector,
           autofocus and the stack object. Initialize the APIs.
        """
        self.acq_in_progress = False
        self.acq_paused = False
        self.simulation_mode = self.cfg['sys']['simulation_mode'] == 'True'
        self.use_microtome = self.cfg['sys']['use_microtome'] == 'True'
        self.plc_installed = self.cfg['sys']['plc_installed'] == 'True'
        self.plc_initialized = False
        self.statusbar_msg = ''

        # If workspace does not exist, create directories:
        workspace_dir = self.cfg['acq']['base_dir'] + '\\workspace'
        if not os.path.exists(workspace_dir):
            self.try_to_create_directory(workspace_dir)

        # Current OV and grid settings displayed in GUI:
        self.current_ov = 0
        self.current_grid = 0

        # Set up trigger to update information from Viewport:
        self.viewport_trigger = Trigger()
        self.viewport_trigger.s.connect(self.process_viewport_signal)
        self.viewport_queue = Queue()

        # Set up update function that is called during main acquisition loop
        # in thread:
        self.acq_trigger = Trigger()
        self.acq_trigger.s.connect(self.process_acq_signal)
        self.acq_queue = Queue()

        # First log message:
        self.add_to_log('CTRL: SBEMimage Version ' + self.VERSION)

        utils.show_progress_in_console(40)

        # Initialize coordinate system
        self.cs = CoordinateSystem(self.cfg)

        if self.cfg['sem']['device'] in [
            "ZEISS Merlin", "ZEISS Sigma", "ZEISS GeminiSEM",
            "ZEISS Ultra Plus"]:
            # Initialize SEM instance to control SmartSEM API:
            self.sem = SEM_SmartSEM(self.cfg, self.syscfg)
            if self.sem.get_error_state() > 0:
                self.add_to_log('SEM: Error initializing SmartSEM Remote API.')
                self.add_to_log('SEM: ' + self.sem.get_error_cause())
                QMessageBox.warning(
                    self, 'Error initializing SmartSEM Remote API',
                    'Initalization of the SmartSEM Remote API failed. Please '
                    'verify that the Remote API is installed and configured '
                    'correctly.'
                    '\nSBEMimage will be run in simulation mode.',
                    QMessageBox.Ok)
                self.simulation_mode = True
                self.cfg['sys']['simulation_mode'] = 'True'

        # Set up overviews:
        self.ovm = OverviewManager(self.cfg, self.sem, self.cs)
        # Set up grids:
        self.gm = GridManager(self.cfg, self.sem, self.cs)
        # Set up grid/tile selectors:
        self.update_main_controls_grid_selector()
        self.update_main_controls_ov_selector()

        utils.show_progress_in_console(50)

        # Initialize DM-3View interface:
        if (self.use_microtome
            and self.cfg['microtome']['device'] == 'Gatan 3View'):
            self.microtome = Microtome_3View(self.cfg, self.syscfg)
            if self.microtome.get_error_state() == 101:
                self.add_to_log('3VIEW: Error initializing DigitalMicrograph API.')
                self.add_to_log('3VIEW: ' + self.microtome.get_error_cause())
                QMessageBox.warning(
                    self, 'Error initializing DigitalMicrograph API',
                    'Have you forgotten to start the communication '
                    'script in DM? \nIf yes, please load the '
                    'script and click "Execute".'
                    '\n\nIs the Z coordinate negative? \nIf yes, '
                    'please set it to zero or a positive value.',
                    QMessageBox.Retry)
                # Try again:
                self.microtome = Microtome_3View(self.cfg, self.syscfg)
                if self.microtome.get_error_state() > 0:
                    self.add_to_log(
                        '3VIEW: Error initializing DigitalMicrograph API '
                        '(second attempt).')
                    self.add_to_log('3VIEW: ' + self.microtome.get_error_cause())
                    QMessageBox.warning(
                        self, 'Error initializing DigitalMicrograph API',
                        'The second attempt to initalize the DigitalMicrograph '
                        'API failed.\nSBEMimage will be run in simulation mode.',
                        QMessageBox.Ok)
                    self.simulation_mode = True
                    self.cfg['sys']['simulation_mode'] = 'True'
                else:
                    self.add_to_log('3VIEW: Second attempt to initialize '
                                    'DigitalMicrograph API successful.')

            # Update calibration of microtome stage for current EHT:
            self.calibration_found = (
                self.microtome.update_stage_calibration(self.sem.get_eht()))
            self.cs.apply_stage_calibration()
            if not self.calibration_found:
                self.add_to_log(
                    'CTRL: Warning - No stage calibration found for current EHT.')

        else:
            # No microtome - use SEM stage
            self.microtome = None
            # Update calibration of SEM stage for current EHT:
            self.calibration_found = (
                self.sem.update_stage_calibration(self.sem.get_eht()))
            self.cs.apply_stage_calibration()
            if not self.calibration_found:
                self.add_to_log(
                    'CTRL: Warning - No stage calibration found for current EHT.')
            # Restrict GUI: microtome functions are not available:
            self.restrict_gui_for_sem_stage()

        utils.show_progress_in_console(70)
        # Stage instance:
        self.stage = Stage(self.sem, self.microtome,
                           self.use_microtome)

        # Enable plasma cleaner tool button if plasma cleaner installed:
        self.toolButton_plasmaCleaner.setEnabled(self.plc_installed)
        self.checkBox_plasmaCleaner.setEnabled(self.plc_installed)
        self.actionPlasmaCleanerSettings.setEnabled(self.plc_installed)

        # Set up Image Inspector instance:
        self.img_inspector = ImageInspector(self.cfg, self.ovm)

        # Set up autofocus instance:
        self.af = Autofocus(self.cfg, self.sem, self.gm,
                            self.acq_queue, self.acq_trigger)
        # Finally, the stack instance:
        self.stack = Stack(self.cfg,
                           self.sem, self.microtome, self.stage,
                           self.ovm, self.gm, self.cs,
                           self.img_inspector, self.af,
                           self.acq_queue, self.acq_trigger)

    def try_to_create_directory(self, new_directory):
        """Create directory. If not possible: error message"""
        try:
            os.makedirs(new_directory)
        except:
            QMessageBox.warning(
                self, 'Could not create directory',
                'Could not create directory "%s". Make sure the drive/folder '
                'is available for write access.' % new_directory,
                QMessageBox.Ok)

    def update_main_controls_grid_selector(self, current_grid=0):
        """Update the combo box for grid selection in the main window."""
        if current_grid >= self.gm.get_number_grids():
            current_grid = 0
        self.comboBox_gridSelector.blockSignals(True)
        self.comboBox_gridSelector.clear()
        grid_list_str = self.gm.get_grid_str_list()
        for i in range(self.gm.get_number_grids()):
            colour_icon = QPixmap(18, 9)
            rgb = self.gm.get_display_colour(i)
            colour_icon.fill(QColor(rgb[0], rgb[1], rgb[2]))
            self.comboBox_gridSelector.addItem(
                QIcon(colour_icon), '   ' + grid_list_str[i])
        self.current_grid = current_grid
        self.comboBox_gridSelector.setCurrentIndex(current_grid)
        self.comboBox_gridSelector.currentIndexChanged.connect(
            self.change_grid_settings_display)
        self.comboBox_gridSelector.blockSignals(False)

    def update_main_controls_ov_selector(self, current_ov=0):
        """Update the combo box for OV selection in the main window."""
        if current_ov >= self.ovm.get_number_ov():
            current_ov = 0
        self.comboBox_OVSelector.blockSignals(True)
        self.comboBox_OVSelector.clear()
        ov_list_str = self.ovm.get_ov_str_list()
        self.comboBox_OVSelector.addItems(ov_list_str)
        self.current_ov = current_ov
        self.comboBox_OVSelector.setCurrentIndex(current_ov)
        self.comboBox_OVSelector.currentIndexChanged.connect(
            self.change_ov_settings_display)
        self.comboBox_OVSelector.blockSignals(False)

    def change_grid_settings_display(self):
        self.current_grid = self.comboBox_gridSelector.currentIndex()
        self.show_current_settings()

    def change_ov_settings_display(self):
        self.current_ov = self.comboBox_OVSelector.currentIndex()
        self.show_current_settings()

    def show_current_settings(self):
        """Show current settings in the upper part of the main window"""
        # Installed devices:
        self.label_SEM.setText(self.sem.device_name)
        if self.use_microtome:
            self.label_microtome.setText(self.microtome.device_name)
        else:
            self.groupBox_stage.setTitle('Stage (no microtome)')
            self.label_microtome.setText(self.sem.device_name)
        # SEM beam settings:
        self.label_beamSettings.setText(
            '{0:.2f}'.format(self.sem.get_eht()) + ' kV / '
            + str(self.sem.get_beam_current()) + ' pA')
        # Show dwell time, pixel size, and frame size for current grid:
        self.label_tileDwellTime.setText(
            str(self.gm.get_dwell_time(self.current_grid)) + ' µs')
        self.label_tilePixelSize.setText(
            str(self.gm.get_pixel_size(self.current_grid)) + ' nm')
        self.label_tileSize.setText(
            str(self.gm.get_tile_width_p(self.current_grid))
            + ' × '
            + str(self.gm.get_tile_height_p(self.current_grid)))
        # Show settings for current OV:
        self.label_OVDwellTime.setText(
            str(self.ovm.get_ov_dwell_time(self.current_ov)) + ' µs')
        self.label_OVMagnification.setText(
            str(self.ovm.get_ov_magnification(self.current_ov)))
        self.label_OVSize.setText(
            str(self.ovm.get_ov_width_p(self.current_ov))
            + ' × '
            + str(self.ovm.get_ov_height_p(self.current_ov)))
        ov_centre = self.cs.get_ov_centre_s(self.current_ov)
        ov_centre_str = ('X: {0:.3f}'.format(ov_centre[0])
                         + ', Y: {0:.3f}'.format(ov_centre[1]))
        self.label_OVLocation.setText(ov_centre_str)
        # Debris detection area:
        if bool(self.cfg['acq']['use_debris_detection']):
            self.label_debrisDetectionArea.setText(
                str(self.ovm.get_ov_debris_detection_area(self.current_ov)))
        else:
            self.label_debrisDetectionArea.setText('-')
        # Grid parameters
        grid_origin = self.cs.get_grid_origin_s(self.current_grid)
        grid_origin_str = ('X: {0:.3f}'.format(grid_origin[0])
                           + ', Y: {0:.3f}'.format(grid_origin[1]))
        self.label_gridOrigin.setText(grid_origin_str)
        # Tile grid parameters:
        grid_size = self.gm.get_grid_size(self.current_grid)
        self.label_gridSize.setText(str(grid_size[0]) + ' × ' +
                                    str(grid_size[1]))
        self.label_numberActiveTiles.setText(
            str(self.gm.get_number_active_tiles(self.current_grid)))
        # Acquisition parameters
        self.lineEdit_baseDir.setText(self.cfg['acq']['base_dir'])
        self.label_numberSlices.setText(self.cfg['acq']['number_slices'])
        if self.use_microtome:
            self.label_sliceThickness.setText(
                self.cfg['acq']['slice_thickness'] + ' nm')
        else:
            self.label_sliceThickness.setText('---')

    def show_estimates(self):
        """Read current estimates from the stack instance and display
           them in the main window.
        """
        # Get current estimates:
        (min_dose, max_dose, total_area, total_z, total_data,
        total_imaging, total_stage_moves, total_cutting,
        date_estimate) = self.stack.calculate_estimates()
        total_duration = total_imaging + total_stage_moves + total_cutting
        minutes, seconds = divmod(int(total_duration), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        if min_dose == max_dose:
            self.label_dose.setText(
                '{0:.1f}'.format(min_dose) + ' electrons per nm²')
        else:
            self.label_dose.setText(
                '{0:.2f}'.format(min_dose) + ' .. '
                + '{0:.1f}'.format(max_dose) + ' electrons per nm²')
        if total_duration == 0:
            total_duration = 1  # prevent division by zero
        self.label_totalDuration.setText(
            f'{days} d {hours} h {minutes} min     '
            f'({total_imaging/total_duration * 100:.1f}% / '
            f'{total_stage_moves/total_duration * 100:.1f}% / '
            f'{total_cutting/total_duration * 100:.1f}%)')
        self.label_totalArea.setText('{0:.1f}'.format(total_area) + ' µm²')
        self.label_totalZ.setText('{0:.1f}'.format(total_z) + ' µm')
        self.label_totalData.setText('{0:.1f}'.format(total_data) + ' GB')
        self.label_dateEstimate.setText(date_estimate)

    def update_acq_options(self):
        self.cfg['acq']['use_email_monitoring'] = str(
            self.checkBox_useMonitoring.isChecked())
        self.cfg['acq']['take_overviews'] = str(
            self.checkBox_takeOV.isChecked())
        if not self.checkBox_takeOV.isChecked():
            # Deactivate debris detection option when no overviews:
            self.checkBox_useDebrisDetection.setChecked(False)
            self.checkBox_useDebrisDetection.setEnabled(False)
        else:
            # Activate
            self.checkBox_useDebrisDetection.setEnabled(True)
        self.cfg['acq']['use_debris_detection'] = str(
            self.checkBox_useDebrisDetection.isChecked())
        self.cfg['acq']['ask_user'] = str(self.checkBox_askUser.isChecked())
        self.cfg['sys']['use_mirror_drive'] = str(
            self.checkBox_mirrorDrive.isChecked())
        self.cfg['acq']['monitor_images'] = str(
            self.checkBox_monitorTiles.isChecked())
        self.cfg['acq']['use_autofocus'] = str(
            self.checkBox_useAutofocus.isChecked())
        self.show_estimates()
        self.viewport.mv_draw()

#--------------- MagC tab------------------------------------
    def magc_select_all(self):
        tableView = self.tableView_magc_sectionList
        model = tableView.model()
        self.magc_select_rows(range(model.rowCount()))

    def magc_deselect_all(self):
        tableView = self.tableView_magc_sectionList
        tableView.clearSelection()

    def magc_check_selected(self):
        tableView = self.tableView_magc_sectionList
        selectedRows = [id.row() for id in tableView.selectedIndexes()]
        self.magc_set_check_rows(selectedRows, Qt.Checked)
        self.magc_update_checked_sections_to_config()
        
    def magc_uncheck_selected(self):
        tableView = self.tableView_magc_sectionList
        selectedRows = [id.row() for id in tableView.selectedIndexes()]
        self.magc_set_check_rows(selectedRows, Qt.Unchecked)
        self.magc_update_checked_sections_to_config()
        
    def magc_invert_selection(self):
        tableView = self.tableView_magc_sectionList
        selectedRows = [id.row() for id in tableView.selectedIndexes()]
        model = tableView.model()
        rowsToSelect = set(range(model.rowCount())) - set(selectedRows)
        self.magc_select_rows(rowsToSelect)

    def magc_select_checked(self):
        tableView = self.tableView_magc_sectionList
        model = tableView.model()
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
            self.tableView_magc_sectionList.verticalScrollBar().setValue(indexes[0])
            self.add_to_log('Custom section string selection: ' + userString)
        else:
            self.add_to_log('Something wrong in your input. Use 2,5,3 or 2-30 or 2-30-5')       
        
    def magc_set_check_rows(self, rows, check_state):
        tableView = self.tableView_magc_sectionList
        model = tableView.model()
        model.blockSignals(True) # prevent slowness
        for row in rows:
            item = model.item(row, 0)
            item.setCheckState(check_state)
        model.blockSignals(False)
        self.tableView_magc_sectionList.setFocus()
       
    def magc_select_rows(self, rows):
        tableView = self.tableView_magc_sectionList
        tableView.clearSelection()
        model = tableView.model()
        selectionModel = tableView.selectionModel()
        selection = QItemSelection()
        for row in rows:
            index = model.index(row, 0)
            selection.merge(QItemSelection(index, index), QItemSelectionModel.Select)
        selectionModel.select(selection, QItemSelectionModel.Select)
        self.tableView_magc_sectionList.setFocus()
        
    def magc_actions_selected_sections_changed(self, changedSelected, changedDeselected):
        # update color of selected/deselected sections
        for changedSelectedIndex in changedSelected.indexes():
            row = changedSelectedIndex.row()
            self.gm.set_display_colour(grid_number=row, colour=0)
        for changedDeselectedIndex in changedDeselected.indexes():
            row = changedDeselectedIndex.row()
            self.gm.set_display_colour(grid_number=row, colour=1)
        self.viewport.mv_draw()
        # update config
        tableView = self.tableView_magc_sectionList
        selectedRows = [id.row() for id in tableView.selectedIndexes()]
        self.cfg['magc']['selected_sections'] = json.dumps(selectedRows)

    def magc_update_checked_sections_to_config(self):
        checkedSections = []
        tableView = self.tableView_magc_sectionList
        model = tableView.model()
        for r in range(model.rowCount()):
            item = model.item(r, 0)
            if item.checkState() == Qt.Checked:
                checkedSections.append(r)
        self.cfg['magc']['checked_sections'] = str(checkedSections)

    def double_clicked_section(self, doubleClickedIndex):
        row = doubleClickedIndex.row()
        model = doubleClickedIndex.model()
        firstColumnIndex = model.index(row, 0)
        sectionKey = int(model.data(firstColumnIndex)) # the index and the key of the section should in theory be the same, just in case 
        self.cs.set_mv_centre_d(self.cs.get_grid_origin_d(grid_number=row))
        self.viewport.mv_draw()
        if self.cfg['magc']['wafer_calibrated'] == 'True':
            self.add_to_log('Section ' + str(sectionKey) + ' has been double-clicked. Moving to section...')
            # xxx moving to the center of the section. To compute the center we need
            # grid_origin, grid_size, grid_rotation. Need rotation implementation.
            # Moving to grid origin for now
            # grid_size = self.gm.get_grid_size(grid_number=row)
            grid_origin = self.cs.get_grid_origin_s(grid_number=row)
            self.stage.move_to_xy(grid_origin)
        else:
            self.add_to_log('Section ' + str(sectionKey) + ' has been double-clicked. Wafer is not calibrated, therefore no stage movement.')
    def reset_magc(self):
        self.cfg['magc']['wafer_calibrated'] = 'False'
        self.cfg['magc']['selected_sections'] = '[]'
        self.cfg['magc']['checked_sections'] = '[]'
        self.gm.delete_all_but_last_grid()
        self.viewport.update_grids()
        self.viewport.mv_draw()
        tableModel = self.tableView_magc_sectionList.model()
        tableModel.removeRows(0, tableModel.rowCount(), QModelIndex())
        
    def open_import_wafer_image(self):    
        target_dir = os.path.join(self.cfg['acq']['base_dir'], 'overviews', 'imported')
        if not os.path.exists(target_dir):
            self.try_to_create_directory(target_dir)
        dialog = ImportWaferImageDlg(self.ovm, self.cs, target_dir)
        if dialog.exec_():
            self.viewport.mv_load_last_imported_image()
            self.viewport.mv_draw()
        
    def add_section(self):
        self.gm.add_new_grid()
        grid_number = self.gm.get_number_grids() - 1
        self.cs.set_grid_origin_s(grid_number, list(*self.stage.get_xy()))
        
        # set same properties as previous section if it exists
        if grid_number != 0:
            self.gm.set_rotation(grid_number,
                    self.gm.get_rotation(grid_number-1))
            self.gm.set_grid_size(grid_number,
                    *self.gm.get_grid_size(grid_number-1))
            self.gm.set_tile_size_selector(grid_number, 
                    self.gm.get_tile_size_selector(grid_number-1))
            self.gm.set_pixel_size(grid_number,
                    self.gm.get_pixel_size(grid_number-1))
        self.gm.calculate_grid_map(grid_number)
        self.update_from_grid_dlg()
        
        # add section to the sectionList
        item1 = QStandardItem(str(grid_number))
        item1.setCheckable(True)
        item2 = QStandardItem('')
        item2.setBackground(color_not_acquired)
        item2.setCheckable(False)
        item2.setSelectable(False)
        tableView = self.tableView_magc_sectionList
        sectionListModel = tableView.model()
        sectionListModel.appendRow([item1, item2])
        
    def delete_last_section(self):
        # remove grid
        self.gm.delete_grid()        
        self.update_from_grid_dlg()
        # remove section from list
        tableView = self.tableView_magc_sectionList
        sectionListModel = tableView.model()
        sectionListModel.removeRow(sectionListModel.rowCount()-1)

    def open_magc_wafer_calibration_dlg(self):
        dialog = WaferCalibrationDlg(self.cfg, self.stage, self.ovm, self.cs, self.gm, self.viewport, self.acq_queue, self.acq_trigger)
        if dialog.exec_():
            pass
    
    
#--------------- End of MagC tab------------------------------------
    
        
# ============== Below: all methods that open dialog windows ==================

    def open_save_settings_new_file_dlg(self):
        dialog = SaveConfigDlg()
        if dialog.exec_():
            if self.cfg['sys']['sys_config_file'] == 'system.cfg':
                self.cfg['sys']['sys_config_file'] = 'this_system.cfg'
            self.gm.save_wd_stig_data_to_cfg()
            self.cfg_file = dialog.get_file_name()
            # Write all settings to disk
            file = open('..\\cfg\\' + self.cfg_file, 'w')
            self.cfg.write(file)
            file.close()
            # also save system settings:
            file = open('..\\cfg\\' + self.cfg['sys']['sys_config_file'], 'w')
            self.syscfg.write(file)
            file.close()
            self.add_to_log('CTRL: Settings saved to disk.')
            # Show new config file name in status bar:
            self.set_statusbar('Ready.')

    def open_sem_dlg(self):
        dialog = SEMSettingsDlg(self.sem)
        if dialog.exec_():
            self.calibration_found = True
            if self.microtome is not None:
                # Update stage calibration (EHT may have changed):
                self.calibration_found = (
                    self.microtome.update_stage_calibration(self.sem.get_eht()))
                self.cs.apply_stage_calibration()
            self.show_current_settings()
            # Electron dose may have changed:
            self.show_estimates()
            if (self.cfg['debris']['auto_detection_area'] == 'True'):
                self.ovm.update_all_ov_debris_detections_areas(self.gm)
            self.viewport.mv_draw()
            if not self.calibration_found:
                self.add_to_log(
                    'CTRL: Warning - No stage calibration found for current EHT.')
                QMessageBox.warning(
                    self, 'Missing stage calibration',
                    'No stage calibration settings were found for the currently '
                    'selected EHT. Please calibrate the stage:'
                    '\nMenu  →  Calibration  →  Stage calibration',
                    QMessageBox.Ok)

    def open_microtome_dlg(self):
        dialog = MicrotomeSettingsDlg(self.microtome, self.sem,
                                      self.use_microtome)
        if dialog.exec_():
            self.cs.load_stage_limits()
            self.viewport.mv_load_stage_limits()
            self.show_current_settings()
            self.show_estimates()
            self.viewport.mv_draw()

    def open_calibration_dlg(self):
        dialog = CalibrationDlg(self.cfg, self.stage, self.sem)
        if dialog.exec_():
            self.cs.apply_stage_calibration()
            if (self.cfg['debris']['auto_detection_area'] == 'True'):
                self.ovm.update_all_ov_debris_detections_areas(self.gm)
            self.viewport.mv_draw()

    def open_mag_calibration_dlg(self):
        dialog = MagCalibrationDlg(self.sem, self.ovm)
        if dialog.exec_():
            # Show updated OV mag:
            self.show_current_settings()

    def open_cut_duration_dlg(self):
        dialog = CutDurationDlg(self.microtome)
        dialog.exec_()

    def open_ov_dlg(self):
        dialog = OVSettingsDlg(self.ovm, self.sem, self.current_ov,
                               self.acq_queue, self.acq_trigger)
        # self.update_from_ov_dlg() is called when user saves settings
        # or adds/deletes OVs.
        dialog.exec_()

    def update_from_ov_dlg(self):
        self.update_main_controls_ov_selector(self.current_ov)
        self.ft_update_ov_selector(self.ft_selected_ov)
        self.viewport.update_ov()
        if bool(self.cfg['debris']['auto_detection_area']):
            self.ovm.update_all_ov_debris_detections_areas(self.gm)
        self.show_current_settings()
        self.show_estimates()
        self.viewport.mv_draw()

    def open_import_image_dlg(self):
        target_dir = self.cfg['acq']['base_dir'] + '\\overviews\\imported'
        if not os.path.exists(target_dir):
            self.try_to_create_directory(target_dir)
        dialog = ImportImageDlg(self.ovm, self.cs, target_dir)
        if dialog.exec_():
            self.viewport.mv_load_last_imported_image()
            self.viewport.mv_draw()

    def open_adjust_image_dlg(self, selected_img):
        dialog = AdjustImageDlg(self.ovm, self.cs, selected_img,
                                self.acq_queue, self.acq_trigger)
        dialog.exec_()

    def open_delete_image_dlg(self):
        dialog = DeleteImageDlg(self.ovm)
        if dialog.exec_():
            self.viewport.mv_load_all_imported_images()
            self.viewport.mv_draw()

    def open_grid_dlg(self):
        dialog = GridSettingsDlg(self.gm, self.sem, self.current_grid,
                                 self.cfg, self.acq_queue, self.acq_trigger)
        # self.update_from_grid_dlg() is called when user saves settings
        # or adds/deletes grids.
        dialog.exec_()

    def update_from_grid_dlg(self):
        # Update selectors:
        self.update_main_controls_grid_selector(self.current_grid)
        self.ft_update_grid_selector(self.ft_selected_grid)
        self.ft_update_tile_selector()
        if self.ft_selected_ov == -1:
            self.ft_clear_wd_stig_display()
        self.viewport.update_grids()
        if (self.cfg['debris']['auto_detection_area'] == 'True'):
            self.ovm.update_all_ov_debris_detections_areas(self.gm)
        self.show_current_settings()
        self.show_estimates()
        self.viewport.mv_draw()

    def open_change_grid_rotation_dlg(self, selected_grid):
        dialog = GridRotationDlg(selected_grid, self.gm, self.acq_queue, self.acq_trigger)
        if dialog.exec_():
            if self.cfg['debris']['auto_detection_area'] == 'True':
                self.ovm.update_all_ov_debris_detections_areas(self.gm)
                self.viewport.mv_draw()

    def open_acq_settings_dlg(self):
        dialog = AcqSettingsDlg(self.cfg, self.stack)
        if dialog.exec_():
            self.show_current_settings()
            self.show_estimates()
            self.img_inspector.update_acq_settings()
            self.update_stack_progress()   # Slice number may have changed.
            # If workspace directory does not yet exist, create it:
            workspace_dir = self.cfg['acq']['base_dir'] + '\\workspace'
            if not os.path.exists(workspace_dir):
                self.try_to_create_directory(workspace_dir)

    def open_pre_stack_dlg(self):
        # Calculate new estimates first, then open dialog:
        self.show_estimates()
        dialog = PreStackDlg(self.cfg, self.ovm, self.gm,
                             paused=self.acq_paused)
        if dialog.exec_():
            self.show_current_settings()
            self.start_acquisition()

    def open_export_dlg(self):
        dialog = ExportDlg(self.cfg)
        dialog.exec_()
        
    def open_update_dlg(self):
        dialog = UpdateDlg()
        dialog.exec_()

    def open_magc_import_dlg(self):
        gui_items = {
        'sectionList': self.tableView_magc_sectionList,
        }
        dialog = ImportMagCDlg(self.cfg, self.gm, self.cs, self.stage, self.sem, self.ovm, self.viewport, gui_items, self.acq_trigger, self.acq_queue)
        if dialog.exec_():
            # self.tabWidget.setTabEnabled(3, True)
            self.update_from_grid_dlg()

    def open_email_monitoring_dlg(self):
        dialog = EmailMonitoringSettingsDlg(self.cfg, self.stack)
        dialog.exec_()

    def open_debris_dlg(self):
        dialog = DebrisSettingsDlg(self.cfg, self.ovm)
        if dialog.exec_():
            self.ovm.update_all_ov_debris_detections_areas(self.gm)
            self.show_current_settings()
            self.img_inspector.update_debris_settings()
            self.viewport.mv_draw()

    def open_ask_user_dlg(self):
        dialog = AskUserDlg()
        dialog.exec_()

    def open_mirror_drive_dlg(self):
        dialog = MirrorDriveDlg(self.cfg)
        dialog.exec_()

    def open_image_monitoring_dlg(self):
        dialog = ImageMonitoringSettingsDlg(self.cfg)
        if dialog.exec_():
            self.img_inspector.update_monitoring_settings()

    def open_autofocus_dlg(self):
        dialog = AutofocusSettingsDlg(self.af, self.gm)
        if dialog.exec_():
            if self.af.get_method() == 2:
                self.checkBox_useAutofocus.setText('Focus tracking')
            else:
                self.checkBox_useAutofocus.setText('Autofocus')
            self.viewport.mv_draw()

    def open_plasma_cleaner_dlg(self):
        dialog = PlasmaCleanerDlg(self.plasma_cleaner)
        dialog.exec_()

    def open_approach_dlg(self):
        # Trigger and queue needed to pass updates to main window (z coordinate)
        dialog = ApproachDlg(self.microtome, self.acq_queue, self.acq_trigger)
        dialog.exec_()

    def open_grab_frame_dlg(self):
        dialog = GrabFrameDlg(self.cfg, self.sem,
                              self.acq_queue, self.acq_trigger)
        dialog.exec_()

    def open_eht_dlg(self):
        dialog = EHTDlg(self.sem)
        dialog.exec_()

    def open_motor_test_dlg(self):
        dialog = MotorTestDlg(self.cfg, self.microtome,
                              self.acq_queue, self.acq_trigger)
        dialog.exec_()

    def open_stub_ov_dlg(self):
        position = self.viewport.mv_get_stub_ov_centre()
        if position[0] is None:
            position = self.cs.get_stub_ov_centre_s()
        size_selector = self.ovm.get_stub_ov_size_selector()
        dialog = StubOVDlg(position,
                           size_selector,
                           self.cfg['acq']['base_dir'],
                           self.stack.get_slice_counter(),
                           self.sem, self.stage,
                           self.ovm, self.cs,
                           self.acq_queue, self.acq_trigger)
        dialog.exec_()

    def open_about_box(self):
        dialog = AboutBox(self.VERSION)
        dialog.exec_()

# ============ Below: stack progress update and signal processing =============

    def update_stack_progress(self):
        current_slice = self.stack.get_slice_counter()
        if self.stack.get_number_slices() > 0:
            self.label_sliceCounter.setText(
                str(current_slice) + '      (' + chr(8710) + 'Z = '
                + '{0:.3f}'.format(self.stack.get_total_z_diff()) + ' µm)')
            self.progressBar.setValue(
                current_slice / self.stack.get_number_slices() * 100)
        else:
            self.label_sliceCounter.setText(
                str(current_slice) + "      (no cut after acq.)")

    def show_current_stage_xy(self):
        xy_pos = self.stage.get_last_known_xy()
        if xy_pos[0] is None or xy_pos[1] is None:
            pos_info = ('X: unknown    Y: unknown')
        else:
            pos_info = ('X: {0:.3f}    Y: {1:.3f}'.format(*xy_pos))
        self.label_currentStageXY.setText(pos_info)
        QApplication.processEvents() # ensures changes are shown without delay

    def show_current_stage_z(self):
        z_pos = self.stage.get_last_known_z()
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

    def set_status(self, text):
        """Set status label in GUI (acquisition panel)."""
        pal = QPalette(self.label_acqIndicator.palette())
        pal.setColor(QPalette.WindowText, QColor(Qt.red))
        self.label_acqIndicator.setPalette(pal)
        self.label_acqIndicator.setText(text)

    def event(self, e):
        """Override status tips when hovering with mouse over menu."""
        if e.type() == QEvent.StatusTip:
            e = QStatusTipEvent(self.statusbar_msg)
        return super().event(e)

    def process_acq_signal(self):
        """Process signals from acquisition thread and from dialog windows.
           The trigger/queue approach is required to pass information
           between threads.
        """
        msg = self.acq_queue.get()
        if msg == 'OV SUCCESS':
            self.acquire_ov_success(True)
        elif msg == 'OV FAILURE':
            self.acquire_ov_success(False)
        elif msg == 'STUB OV SUCCESS':
            self.acquire_stub_ov_success(True)
        elif msg == 'STUB OV FAILURE':
            self.acquire_stub_ov_success(False)
        elif msg == 'STUB OV BUSY':
            self.set_status('Busy.')
            self.set_statusbar(
                'Stub overview acquisition in progress...')
        elif msg == 'APPROACH BUSY':
            self.set_status('Busy.')
            self.set_statusbar(
                'Approach cutting in progress...')
        elif msg == 'STATUS IDLE':
            self.set_status('')
            self.set_statusbar('Ready.')
        elif msg == 'SWEEP SUCCESS':
            self.show_current_stage_z()
            self.sweep_success(True)
        elif msg == 'SWEEP FAILURE':
            self.show_current_stage_z()
            self.sweep_success(False)
        elif msg == 'MOVE SUCCESS':
            self.move_stage_success(True)
        elif msg == 'MOVE FAILURE':
            self.move_stage_success(False)
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
        elif msg == 'UPDATE XY':
            self.show_current_stage_xy()
        elif msg == 'UPDATE Z':
            self.show_current_stage_z()
        elif msg == 'UPDATE PROGRESS':
            self.update_stack_progress()
            self.show_estimates()
        elif msg == 'ASK DEBRIS FIRST OV':
            reply = QMessageBox.question(
                self, 'Debris on first OV? User input required',
                'Is the overview image that has just been acquired free from '
                'debris?',
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Abort,
                QMessageBox.Yes)
            self.stack.set_user_reply(reply)
        elif msg == 'ASK DEBRIS CONFIRMATION':
            reply = QMessageBox.question(
                self, 'Debris detection',
                'Potential debris has been detected in the area of interest. '
                'Can you confirm that debris is visible in the detection '
                'area?',
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Abort,
                QMessageBox.Yes)
            self.stack.set_user_reply(reply)
        elif msg == 'ASK IMAGE ERROR OVERRIDE':
            reply = QMessageBox.question(
                self, 'Image inspector',
                'The current image has failed the image inspector tests.\n'
                'Would you like to proceed anyway?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes)
            self.stack.set_user_reply(reply)
        elif msg == 'REMOTE STOP':
            self.remote_stop()
        elif msg == 'ERROR PAUSE':
            self.error_pause()
        elif msg == 'COMPLETION STOP':
            self.completion_stop()
        elif msg == 'ACQ NOT IN PROGRESS':
            self.acq_not_in_progress_update_gui()
        elif msg == 'SAVE CFG':
            self.save_settings()
        elif msg[:10] == 'ACQ IND OV':
            self.viewport.mv_toggle_ov_acq_indicator(int(msg[10:]))
        elif msg[:12] == 'ACQ IND TILE':
            position = msg[12:].split('.')
            self.viewport.mv_toggle_tile_acq_indicator(
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
        elif msg[:12] == 'MV UPDATE OV':
            self.viewport.mv_load_overview(int(msg[12:]))
            self.viewport.mv_draw()
        elif msg[:18] == 'GRAB VP SCREENSHOT':
            self.viewport.grab_viewport_screenshot(msg[18:])
        elif msg[:15] == 'RELOAD IMPORTED':
            self.viewport.mv_load_imported_image(int(msg[15:]))
            self.viewport.mv_draw()
        elif msg == 'DRAW MV':
            self.viewport.mv_draw()
        elif msg == 'DRAW MV NO LABELS':
            self.viewport.mv_draw(suppress_labels=True, suppress_previews=True)
        elif msg[:6] == 'VP LOG':
            self.viewport.add_to_viewport_log(msg[6:])
        elif msg[:15] == 'GET CURRENT LOG':
            self.write_current_log_to_file(msg[15:])
        else:
            # If msg is not a command, show it in log:
            self.textarea_log.appendPlainText(msg)

    def process_viewport_signal(self):
        """Process signals from the viewport."""
        msg = self.viewport_queue.get()
        if msg == 'REFRESH OV':
            self.acquire_ov()
        elif msg == 'ACQUIRE STUB OV':
            self.open_stub_ov_dlg()
        elif msg == 'SHOW CURRENT SETTINGS':
            self.show_current_settings()
            self.show_estimates()
        elif msg == 'LOAD IN FOCUS TOOL':
            self.ft_set_selection_from_mv()
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
        else:
            # If msg is not a command, show it in log:
            self.textarea_log.appendPlainText(msg)

    def add_tile_folder(self):
        grid = self.viewport.mv_get_selected_grid()
        tile = self.viewport.mv_get_selected_tile()
        tile_folder = (self.cfg['acq']['base_dir']
                      + '\\tiles\\g'
                      + str(grid).zfill(utils.GRID_DIGITS)
                      + '\\t'
                      + str(tile).zfill(utils.TILE_DIGITS))
        if not os.path.exists(tile_folder):
            self.try_to_create_directory(tile_folder)
        if self.cfg['sys']['use_mirror_drive'] == 'True':
            mirror_tile_folder = (
                self.cfg['sys']['mirror_drive'] + tile_folder[2:])
            if not os.path.exists(mirror_tile_folder):
                self.try_to_create_directory(mirror_tile_folder)

    def restrict_gui(self, b):
        """Disable GUI elements during acq or when program is busy."""
        b ^= True
        # Settings buttons:
        self.pushButton_SEMSettings.setEnabled(b)
        self.pushButton_microtomeSettings.setEnabled(b)
        self.pushButton_OVSettings.setEnabled(b)
        self.pushButton_gridSettings.setEnabled(b)
        self.pushButton_acqSettings.setEnabled(b)
        # Other buttons:
        self.pushButton_doApproach.setEnabled(b)
        self.pushButton_doSweep.setEnabled(b)
        self.pushButton_grabFrame.setEnabled(b)
        self.pushButton_EHTToggle.setEnabled(b)
        # Checkboxes:
        self.checkBox_mirrorDrive.setEnabled(b)
        self.toolButton_mirrorDrive.setEnabled(b)
        self.checkBox_takeOV.setEnabled(b)

        self.toolButton_OVSettings.setEnabled(b)
        if self.plc_installed:
            self.checkBox_plasmaCleaner.setEnabled(b)
            self.toolButton_plasmaCleaner.setEnabled(b)
        # Start, reset buttons:
        self.pushButton_startAcq.setEnabled(b)
        self.pushButton_resetAcq.setEnabled(b)
        # Disable/enable the communication tests and the focus tool:
        self.tabWidget.setTabEnabled(1, b)
        self.tabWidget.setTabEnabled(2, b)
        # Disable/enable menu
        self.menubar.setEnabled(b)

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
        # Tests and focus tool:
        self.pushButton_focusToolStart.setEnabled(False)
        self.checkBox_zoom.setEnabled(False)
        self.pushButton_testGetMag.setEnabled(False)
        self.pushButton_testSetMag.setEnabled(False)
        self.pushButton_testGetFocus.setEnabled(False)
        self.pushButton_testSetFocus.setEnabled(False)
        self.pushButton_testRunAutofocus.setEnabled(False)
        self.pushButton_testRunAutostig.setEnabled(False)
        self.pushButton_testRunAutofocusStig.setEnabled(False)
        self.pushButton_testZeissAPIVersion.setEnabled(False)
        self.pushButton_testGetStage.setEnabled(False)
        self.pushButton_testSetStage.setEnabled(False)
        self.pushButton_testNearKnife.setEnabled(False)
        self.pushButton_testClearKnife.setEnabled(False)
        self.pushButton_testStopDMScript.setEnabled(False)
        self.pushButton_testPlasmaCleaner.setEnabled(False)
        self.pushButton_testMotors.setEnabled(False)

    def restrict_gui_for_sem_stage(self):
        self.pushButton_doApproach.setEnabled(False)
        self.pushButton_doSweep.setEnabled(False)
        self.pushButton_testNearKnife.setEnabled(False)
        self.pushButton_testClearKnife.setEnabled(False)
        self.pushButton_testStopDMScript.setEnabled(False)
        self.checkBox_useDebrisDetection.setEnabled(False)
        self.toolButton_debrisDetection.setEnabled(False)
        self.actionCutDuration.setEnabled(False)

    def add_to_log(self, text):
        """Update the log from the main thread."""
        self.textarea_log.appendPlainText(utils.format_log_entry(text))

    def write_current_log_to_file(self, filename):
        with open(filename, 'w') as f:
            f.write(self.textarea_log.toPlainText())

# ==================== Below: Manual SBEM commands ============================

    def acquire_ov(self):
        """Acquire one selected or all overview images."""
        ov_selection = self.viewport.mv_get_current_ov()
        if ov_selection > -2:
            user_reply = None
            if (ov_selection == -1) and (self.ovm.get_number_ov() > 1):
                user_reply = QMessageBox.question(
                    self, 'Acquisition of all overview images',
                    'This will acquire all overview images.\n\n' +
                    'Do you wish to proceed?',
                    QMessageBox.Ok | QMessageBox.Cancel)
            if (user_reply == QMessageBox.Ok or ov_selection >= 0
                or (self.ovm.get_number_ov() == 1 and ov_selection == -1)):
                base_dir = self.cfg['acq']['base_dir']
                self.add_to_log(
                    'CTRL: User-requested acquisition of OV image(s) started')
                self.restrict_gui(True)
                self.viewport.restrict_gui(True)
                self.set_status('Busy.')
                self.set_statusbar('Overview acquisition in progress...')
                # Start OV acquisition thread:
                ov_acq_thread = threading.Thread(
                    target=acq_func.acquire_ov,
                    args=(base_dir, ov_selection,
                          self.sem, self.stage,
                          self.ovm, self.cs,
                          self.acq_queue, self.acq_trigger,))
                ov_acq_thread.start()
        else:
            QMessageBox.information(
                self, 'Acquisition of overview image(s)',
                'Please select "All OVs" or a single OV from the '
                'pull-down menu.',
                QMessageBox.Ok)

    def acquire_ov_success(self, success):
        if success:
            self.add_to_log(
                'CTRL: User-requested acquisition of overview(s) completed.')
        else:
            self.add_to_log('CTRL: ERROR ocurred during overview acquisition.')
            QMessageBox.warning(
                self, 'Error during overview acquisition',
                'An error occurred during the acquisition of the overview(s) '
                'at the current location(s). The most likely cause are incorrect '
                'settings of the stage X/Y motor ranges or speeds. Home the '
                'stage and check whether the range limits specified in '
                'SBEMimage are correct.', QMessageBox.Ok)
        self.restrict_gui(False)
        self.viewport.restrict_gui(False)
        self.set_status('')
        self.set_statusbar('Ready.')

    def acquire_stub_ov_success(self, success):
        if success:
            self.add_to_log(
                'CTRL: User-requested acquisition of stub overview mosaic '
                'completed.')
            # Load and show new OV images:
            self.viewport.mv_show_new_stub_overview()
            # Reset user-selected stub_ov_centre:
            self.viewport.mv_reset_stub_ov_centre()
            # Copy to mirror drive:
            if self.cfg['sys']['use_mirror_drive'] == 'True':
                mirror_path = (self.cfg['sys']['mirror_drive']
                              + self.cfg['acq']['base_dir'][2:]
                              + '\\overviews\\stub')
                if not os.path.exists(mirror_path):
                    try:
                        os.makedirs(mirror_path)
                    except:
                        self.add_to_log(
                            'CTRL: Creating directory on mirror drive failed.')
                try:
                    shutil.copy(self.ovm.get_stub_ov_file(), mirror_path)
                except:
                    self.add_to_log(
                        'CTRL: Copying stub overview image to mirror drive '
                        'failed.')

        else:
            self.add_to_log('CTRL: ERROR ocurred during stub overview '
                            'acquisition.')

        self.set_status('')
        self.set_statusbar('Ready.')

    def move_stage(self):
        target_pos = self.viewport.mv_get_selected_stage_pos()
        user_reply = QMessageBox.question(
            self, 'Move to selected stage position',
            'This will move the stage to the coordinates '
            'X: {0:.3f}, '.format(target_pos[0])
            + 'Y: {0:.3f}'.format(target_pos[1]),
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            self.add_to_log('CTRL: Performing user-requested stage move')
            self.restrict_gui(True)
            self.viewport.restrict_gui(True)
            QApplication.processEvents()
            move_thread = threading.Thread(target=acq_func.move,
                                           args=(self.stage,
                                                 target_pos,
                                                 self.acq_queue,
                                                 self.acq_trigger,))
            move_thread.start()
            self.set_status('Busy.')
            self.set_statusbar('Stage move in progress...')

    def move_stage_success(self, success):
        if success:
            self.add_to_log('CTRL: User-requested stage move completed.')
            self.viewport.mv_draw()
        else:
            self.add_to_log('CTRL: ERROR ocurred during stage move.')
            QMessageBox.warning(
                self, 'Error during stage move',
                'An error occurred during the requested stage move. ' +
                'Please check the microtome status in DM.',
                QMessageBox.Ok)
        self.restrict_gui(False)
        self.viewport.restrict_gui(False)
        self.set_status('')
        self.set_statusbar('Ready.')

    def sweep(self):
        user_reply = QMessageBox.question(
                        self, 'Sweep surface',
                        'This will perform a sweep cycle.\n\n' +
                        'Do you wish to proceed?',
                        QMessageBox.Ok | QMessageBox.Cancel,
                        QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            # Perform sweep: do a cut slightly above current surface:
            self.add_to_log('CTRL: Performing user-requested sweep')
            self.restrict_gui(True)
            self.viewport.restrict_gui(True)
            QApplication.processEvents()
            user_sweep_thread = threading.Thread(target=acq_func.sweep,
                                                 args=(self.microtome,
                                                       self.acq_queue,
                                                       self.acq_trigger,))
            user_sweep_thread.start()
            self.set_status('Busy.')
            self.set_statusbar('Sweep in progress...')

    def sweep_success(self, success):
        if success:
            self.add_to_log('CTRL: User-requested sweep completed.')
        else:
            self.add_to_log('CTRL: ERROR ocurred during sweep.')
            QMessageBox.warning(self, 'Error during sweep',
                'An error occurred during the sweep cycle. '
                'Please check the microtome status in DM '
                'and the current Z position.', QMessageBox.Ok)
        self.restrict_gui(False)
        self.viewport.restrict_gui(False)
        self.set_status('')
        self.set_statusbar('Ready.')

    def save_viewport(self):
        (file_name, user_edit) = QInputDialog.getText(
            self, 'Save current viewport screenshot as',
            'File name (.png will be added; File will be saved in '
            'current base directory): ', QLineEdit.Normal, 'current_viewport')
        if user_edit:
            self.viewport.grab_viewport_screenshot(
                self.cfg['acq']['base_dir'] + '\\' + file_name + '.png')
            self.add_to_log('CTRL: Saved current viewport to disk.')

# ===================== Test functions in third tab ===========================

    def test_get_mag(self):
        mag = self.sem.get_mag()
        self.add_to_log('SEM: Current magnification: ' + '{0:.2f}'.format(mag))

    def test_set_mag(self):
        self.sem.set_mag(1000)
        if self.sem.get_error_state() > 0:
            self.add_to_log('SEM: ' + self.sem.get_error_cause())
            self.sem.reset_error_state()
        else:
            self.add_to_log('SEM: Magnification set to 1000.00')

    def test_get_wd(self):
        wd = self.sem.get_wd()
        self.add_to_log(
            'SEM: Current working distance in mm: '
            + '{0:.4f}'.format(wd * 1000))

    def test_set_wd(self):
        self.sem.set_wd(0.006)
        if self.sem.get_error_state() > 0:
            self.add_to_log('SEM: ' + self.sem.get_error_cause())
            self.sem.reset_error_state()
        else:
            self.add_to_log('SEM: Working distance set to 6 mm.')

    def test_autofocus(self):
        self.sem.run_autofocus()
        self.add_to_log('SEM: SmartSEM autofocus routine called.')

    def test_autostig(self):
        self.sem.run_autostig()
        self.add_to_log('SEM: SmartSEM autostig routine called.')

    def test_autofocus_stig(self):
        self.sem.run_autofocus_stig()
        self.add_to_log('SEM: SmartSEM autofocus and autostig routine called.')

    def test_zeiss_api_version(self):
        self.sem.show_about_box()

    def test_get_stage(self):
        current_x = self.stage.get_x()
        if current_x is not None:
            self.add_to_log(
                '3VIEW: Current stage X position: '
                '{0:.2f}'.format(current_x))
        else:
            self.add_to_log(
                '3VIEW: Error - could not read current stage x position.')

    def test_set_stage(self):
        current_x = self.stage.get_x()
        self.stage.move_to_x(current_x + 10)
        self.add_to_log(
            '3VIEW: New stage X position should be: '
            + '{0:.2f}'.format(current_x + 10))

    def test_near_knife(self):
        if self.use_microtome:
            self.microtome.near_knife()
            self.add_to_log('3VIEW: Knife position should be NEAR')
        else:
            self.add_to_log('3VIEW: Microtome not active.')

    def test_clear_knife(self):
        if self.use_microtome:
            self.microtome.clear_knife()
            self.add_to_log('3VIEW: Knife position should be CLEAR')
        else:
            self.add_to_log('3VIEW: Microtome not active.')

    def test_stop_dm_script(self):
        if self.use_microtome:
            self.microtome.stop_script()
            self.add_to_log('3VIEW: STOP command sent to DM script.')
        else:
            self.add_to_log('3VIEW: Microtome not active.')

    def test_send_email(self):
        """Send test e-mail to the primary user."""
        self.add_to_log('CTRL: Trying to send test e-mail.')
        success = utils.send_email(
            smtp_server=self.cfg['sys']['email_smtp'],
            sender=self.cfg['sys']['email_account'],
            recipients=[self.cfg['monitoring']['user_email']],
            subject='Test mail',
            main_text='This mail was sent for testing purposes.',
            files=[])
        if success:
            self.add_to_log('CTRL: E-mail was sent via '
                            + self.cfg['sys']['email_smtp'])
            QMessageBox.information(
                self, 'E-mail test',
                'E-mail was sent via ' + self.cfg['sys']['email_smtp']
                + ' to ' + self.cfg['monitoring']['user_email']
                + '. Check your inbox.',
                QMessageBox.Ok)
        else:
            self.add_to_log('CTRL: Error: Could not send e-mail.')
            QMessageBox.warning(
                self, 'E-mail test failed',
                'A error occurred while trying to send a test e-mail to '
                + self.cfg['monitoring']['user_email'] + ' via '
                + self.cfg['sys']['email_smtp'],
                QMessageBox.Ok)

    def test_plasma_cleaner(self):
        if self.plc_installed:
            self.add_to_log(
                'CTRL: Testing serial connection to plasma cleaner.')
            self.add_to_log('CTRL: ' + self.plasma_cleaner.version())
        else:
            self.add_to_log('CTRL: Plasma cleaner not installed/activated.')

    def test_server_request(self):
        url = self.cfg['sys']['metadata_server_url'] + '/version'
        status, command, msg = utils.meta_server_get_request(url)
        if status == 100:
            QMessageBox.warning(self, 'Server test',
                                'Server test failed. Server probably not active.',
                                QMessageBox.Ok)
        else:
            QMessageBox.information(self, 'Server test',
                                    'Version: ' + str(msg),
                                    QMessageBox.Ok)

    def debris_detection_test(self):
        # Uses overview images t1.tif and t2.tif in current base directory
        # to run the debris detection in the current detection area.
        test_image1 = self.cfg['acq']['base_dir'] + '\\t1.tif'
        test_image2 = self.cfg['acq']['base_dir'] + '\\t2.tif'

        if os.path.isfile(test_image1) and os.path.isfile(test_image2):
            self.img_inspector.process_ov(test_image1, 0, 0)
            self.img_inspector.process_ov(test_image2, 0, 1)
            # Run the tests:
            debris_detected0, msg0 = self.img_inspector.detect_debris(0, 0)
            debris_detected1, msg1 = self.img_inspector.detect_debris(0, 1)
            debris_detected2, msg2 = self.img_inspector.detect_debris(0, 2)
            QMessageBox.information(
                self, 'Debris detection test results',
                'Method 0:\n' + str(debris_detected0) + '; ' + msg0
                + '\nThresholds were (mean/stddev): '
                + self.cfg['debris']['mean_diff_threshold']
                + ', ' + self.cfg['debris']['stddev_diff_threshold']
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

# =============================================================================

    def initialize_plasma_cleaner(self):
        if not self.plc_initialized:
            result = QMessageBox.question(
                self, 'Initalizing plasma cleaner',
                'Is the plasma cleaner GV10x DS connected and switched on?',
                QMessageBox.Yes| QMessageBox.No)
            if result == QMessageBox.Yes:
                self.plasma_cleaner = PlasmaCleaner(
                    self.cfg['sys']['plc_com_port'])
                if self.plasma_cleaner.connection_established():
                    self.add_to_log('CTRL: Plasma cleaner initalized, ver. '
                                    + self.plasma_cleaner.version()[0])
                    self.plc_initialized = True
                    self.open_plasma_cleaner_dlg()
                else:
                    self.add_to_log(
                        'CTRL: Error: Plasma cleaner could not be initalized')
        else:
            self.open_plasma_cleaner_dlg()

    def start_acquisition(self):
        """Start or restart an acquisition. This function is called when user
           clicks on start button. All functionality is contained
           in module stack_acquisition.py
        """
        slice_counter = self.stack.get_slice_counter()
        number_slices = self.stack.get_number_slices()
        if slice_counter > number_slices and number_slices != 0:
            QMessageBox.warning(
                self, 'Check Slice Counter',
                'Slice counter is larger than maximum slice number. Please '
                'adjust the slice counter.',
                QMessageBox.Ok)
        elif slice_counter == number_slices and number_slices != 0:
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
        elif not self.sem.is_eht_on():
            QMessageBox.warning(
                self, 'EHT off',
                'EHT / high voltage is off. Please turn '
                'it on before starting the acquisition.',
                QMessageBox.Ok)
        elif not self.acq_in_progress:
            self.acq_in_progress = True
            self.acq_paused = False
            self.restrict_gui(True)
            self.viewport.restrict_gui(True)
            self.pushButton_startAcq.setText('START')
            self.pushButton_startAcq.setEnabled(False)
            self.pushButton_pauseAcq.setEnabled(True)
            self.pushButton_resetAcq.setEnabled(False)
            self.show_estimates()
            # Indicate in GUI that stack is running now:
            self.set_status('Acquisition in progress')
            self.set_statusbar('Acquisition in progress.')

            # Start the thread running the stack acquisition
            # All source code in stack_acquisition.py
            # Thread is stopped by either stop or pause button
            stack_thread = threading.Thread(target=self.stack.run)
            stack_thread.start()

    def pause_acquisition(self):
        """Let user pause the acquisition."""
        if self.acq_in_progress and not self.acq_paused:
            dialog = PauseDlg()
            dialog.exec_()
            pause_type = dialog.get_user_choice()
        else:
            pause_type = 0
        if pause_type == 1 or pause_type == 2:
            self.add_to_log('CTRL: PAUSE command received.')
            self.pushButton_pauseAcq.setEnabled(False)
            self.stack.pause_acquisition(pause_type)
            self.pushButton_startAcq.setText('CONTINUE')
            self.acq_paused = True
            QMessageBox.information(
                self, 'Acquisition being paused',
                'Please wait until the pause status is confirmed in the log '+
                'before interacting with the program.',
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
            self.add_to_log('CTRL: RESET command received.')
            self.stack.reset_acquisition()
            self.pushButton_resetAcq.setEnabled(False)
            self.pushButton_pauseAcq.setEnabled(False)
            self.pushButton_startAcq.setEnabled(True)
            self.label_sliceCounter.setText('---')
            self.progressBar.setValue(0)
            self.acq_in_progress = False
            self.acq_paused = False
            self.pushButton_startAcq.setText('START')

    def completion_stop(self):
        self.add_to_log('CTRL: Target slice number reached.')
        self.acq_in_progress = False
        self.acq_paused = True
        self.pushButton_resetAcq.setEnabled(True)
        QMessageBox.information(
            self, 'Acquisition complete',
            'The stack has been acquired.',
            QMessageBox.Ok)

    def remote_stop(self):
        self.add_to_log('CTRL: STOP/PAUSE command received remotely.')
        self.pushButton_resetAcq.setEnabled(True)
        self.pushButton_pauseAcq.setEnabled(False)
        self.pushButton_startAcq.setEnabled(True)
        self.acq_in_progress = False
        self.acq_paused = True
        self.pushButton_startAcq.setText('CONTINUE')
        QMessageBox.information(
            self, 'Acquisition stopped',
            'Acquisition was stopped remotely.',
            QMessageBox.Ok)

    def error_pause(self):
        """Notify user in main window that an error has occurred. All error
           handling inside stack_acquisition.py.
        """
        self.acq_in_progress = False
        self.acq_paused = True
        self.pushButton_resetAcq.setEnabled(True)
        self.pushButton_pauseAcq.setEnabled(False)
        self.pushButton_startAcq.setText('CONTINUE')
        QMessageBox.information(
            self, 'ERROR: Acquisition paused',
            'Acquisition was paused because an error has occured (see log).',
            QMessageBox.Ok)

    def acq_not_in_progress_update_gui(self):
        self.acq_in_progress = False
        self.set_status('')
        self.set_statusbar('Ready.')
        self.restrict_gui(False)
        self.viewport.restrict_gui(False)
        self.pushButton_startAcq.setEnabled(True)
        self.pushButton_pauseAcq.setEnabled(False)
        if self.acq_paused == True:
            self.pushButton_resetAcq.setEnabled(True)

    def leave_simulation_mode(self):
        reply = QMessageBox.information(
            self, 'Deactivate simulation mode',
            'Click OK to deactivate simulation mode and save the current '
            'settings. \nPlease note that you have to restart SBEMimage '
            'for the change to take effect.',
            QMessageBox.Ok | QMessageBox.Cancel)
        if reply == QMessageBox.Ok:
            self.cfg['sys']['simulation_mode'] = 'False'
            self.actionLeaveSimulationMode.setEnabled(False)
            self.save_settings()

    def save_settings(self):
        if self.cfg_file != 'default.ini':
            if self.cfg['sys']['sys_config_file'] == 'system.cfg':
                # Preserve system.cfg as template, rename:
                self.cfg['sys']['sys_config_file'] = 'this_system.cfg'
            # Save current WD/STIG data to config:
            self.gm.save_wd_stig_data_to_cfg()
            # Write config to disk:
            cfgfile = open('..\\cfg\\' + self.cfg_file, 'w')
            self.cfg.write(cfgfile)
            cfgfile.close()
            # Also save system settings:
            syscfgfile = open('..\\cfg\\'
                              + self.cfg['sys']['sys_config_file'], 'w')
            self.syscfg.write(syscfgfile)
            syscfgfile.close()
            self.add_to_log('CTRL: Settings saved to disk.')
        elif not self.acq_in_progress:
            QMessageBox.information(
                self, 'Cannot save configuration',
                'The current configuration file "default.ini" cannot be '
                'modified. To save the current configuration to a new file '
                'name, please select "Save as new configuration file" from '
                'the menu.',
                QMessageBox.Ok)

    def closeEvent(self, event):
        if not self.acq_in_progress:
            result = QMessageBox.question(
                self, 'Exit',
                'Are you sure you want to exit the program?',
                QMessageBox.Yes| QMessageBox.No)
            if result == QMessageBox.Yes:
                if not self.simulation_mode:
                    if self.use_microtome:
                        self.microtome.stop_script()
                        self.add_to_log('3VIEW: Disconnected from DM/3View.')
                    sem_log_msg = self.sem.disconnect()
                    self.add_to_log('SEM: ' + sem_log_msg)
                if self.plc_initialized:
                    plasma_log_msg = self.plasma_cleaner.close_port()
                    self.add_to_log(plasma_log_msg)
                if self.acq_paused:
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
                self.viewport.deactivate()
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
                self, 'Acquisition in progress',
                'If you want to quit, please first stop the current '
                'acquisition.',
                QMessageBox.Ok)
            event.ignore()

# ===================== Below: Focus Tool (ft) functions ======================

    def ft_initialize(self):
        # Focus tool (ft) control variables
        self.ft_mode = 0
        self.ft_selected_grid = 0
        self.ft_selected_tile = -1
        self.ft_selected_ov = -1
        self.ft_selected_wd = None
        self.ft_selected_stig_x = None
        self.ft_selected_stig_y = None
        self.ft_counter = 0
        self.ft_zoom = False
        # Focus tool start and set buttons:
        self.pushButton_focusToolStart.clicked.connect(self.ft_start)
        self.pushButton_focusToolMove.clicked.connect(self.ft_open_move_dlg)
        self.pushButton_focusToolSet.clicked.connect(
            self.ft_open_set_params_dlg)
        # Default pixel size:
        self.spinBox_ftPixelSize.setValue(6)
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
        """ Run the tool: (1) Move to selected tile or OV. (2) Acquire image
        series at specified settings. (3) Let user select the best image
        """
        if self.ft_mode == 0: # User has clicked on "Start"
            if (self.ft_selected_tile >=0) or (self.ft_selected_ov >= 0):
                self.ft_run_cycle()
            else:
                QMessageBox.information(
                    self, 'Select target tile/OV',
                    'Before using this tool, you have to select a tile or '
                    'an overview image.',
                    QMessageBox.Ok)

        elif self.ft_mode == 1: # User has selected best focus
            # Set WD as selected by user:
            self.ft_selected_wd += self.ft_fdeltas[self.ft_index]
            self.sem.set_wd(self.ft_selected_wd)
            # Save wd for OV or in tile grid:
            if self.ft_selected_ov >= 0:
                self.ovm.set_ov_wd(self.ft_selected_ov, self.ft_selected_wd)
            elif self.ft_selected_tile >= 0:
                self.gm.set_tile_wd(self.ft_selected_grid,
                                    self.ft_selected_tile,
                                    self.ft_selected_wd)
                if self.gm.is_adaptive_focus_active(self.ft_selected_grid):
                    # Recalculate with new wd:
                    self.gm.calculate_focus_gradient(self.ft_selected_grid)
                self.viewport.mv_draw()
            self.ft_reset()

        elif self.ft_mode == 2: # User has selected best stigmation in X
            # Set StigX as selected by user:
            self.ft_selected_stig_x += self.ft_sdeltas[self.ft_index]
            self.sem.set_stig_x(self.ft_selected_stig_x)
            # Save StigX for OV or in tile grid:
            if self.ft_selected_ov >= 0:
                self.ovm.set_ov_stig_x(
                    self.ft_selected_ov, self.ft_selected_stig_x)
            elif self.ft_selected_tile >= 0:
                self.gm.set_tile_stig_x(self.ft_selected_grid,
                                        self.ft_selected_tile,
                                        self.ft_selected_stig_x)
            self.ft_reset()

        elif self.ft_mode == 3: # User has selected best stigmation in Y
            # Set StigY as selected by user:
            self.ft_selected_stig_y += self.ft_sdeltas[self.ft_index]
            self.sem.set_stig_y(self.ft_selected_stig_y)
            # Save StigX for OV or in tile grid:
            if self.ft_selected_ov >= 0:
                self.ovm.set_ov_stig_y(
                    self.ft_selected_ov, self.ft_selected_stig_y)
            elif self.ft_selected_tile >= 0:
                self.gm.set_tile_stig_y(self.ft_selected_grid,
                                        self.ft_selected_tile,
                                        self.ft_selected_stig_y)
            self.ft_reset()

    def ft_open_set_params_dlg(self):
        if (self.ft_selected_tile >=0) or (self.ft_selected_ov >= 0):
            dialog = FTSetParamsDlg(self.sem, self.ft_selected_wd,
                                    self.ft_selected_stig_x,
                                    self.ft_selected_stig_y,
                                    self.simulation_mode)
            if dialog.exec_():
                new_params = dialog.return_params()
                self.ft_selected_wd = new_params[0]
                self.ft_selected_stig_x, self.ft_selected_stig_y = (
                    new_params[1:3])
                self.ft_update_wd_display()
                self.ft_update_stig_display()
                if self.ft_selected_ov >= 0:
                    self.ovm.set_ov_wd(self.ft_selected_ov,
                                       self.ft_selected_wd)
                    self.ovm.set_ov_stig_xy(self.ft_selected_ov,
                                            self.ft_selected_stig_x,
                                            self.ft_selected_stig_y)
                elif self.ft_selected_tile >= 0:
                    self.gm.set_tile_wd(self.ft_selected_grid,
                                        self.ft_selected_tile,
                                        self.ft_selected_wd)
                    self.gm.set_tile_stig_xy(
                        self.ft_selected_grid,
                        self.ft_selected_tile,
                        self.ft_selected_stig_x,
                        self.ft_selected_stig_y)
                    if self.gm.is_adaptive_focus_active(self.ft_selected_grid):
                        # Recalculate with new wd:
                        self.gm.calculate_focus_gradient(self.ft_selected_grid)
                    self.viewport.mv_draw()
                # Also set SEM to new values:
                self.sem.set_wd(self.ft_selected_wd)
                self.sem.set_stig_xy(
                    self.ft_selected_stig_x, self.ft_selected_stig_y)

        else:
            QMessageBox.information(
                self, 'Select target tile/OV',
                'To set specific WD/stigmation values, you have to select '
                'a tile or an overview.',
                QMessageBox.Ok)

    def ft_open_move_dlg(self):
        if (self.ft_selected_tile >=0) or (self.ft_selected_ov >= 0):
            dialog = FTMoveDlg(self.microtome, self.cs, self.gm,
                               self.ft_selected_grid, self.ft_selected_tile,
                               self.ft_selected_ov)
            dialog.exec_()
            # Update stage position in main controls tab
            self.show_current_stage_xy()
        else:
            QMessageBox.information(
                self, 'Select tile/OV',
                'You must first select a tile or an overview to use the '
                '"Move" function.',
                QMessageBox.Ok)

    def ft_run_cycle(self):
        self.pushButton_focusToolStart.setText('Busy')
        self.pushButton_focusToolStart.setEnabled(False)
        self.pushButton_focusToolMove.setEnabled(False)
        self.pushButton_focusToolSet.setEnabled(False)
        self.spinBox_ftPixelSize.setEnabled(False)
        self.checkBox_zoom.setEnabled(False)
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
        # Use current WD/Stig if selected working distance == 0:
        if self.ft_selected_wd == 0:
            self.ft_selected_wd = self.sem.get_wd()
            self.ft_selected_stig_x, self.ft_selected_stig_y = self.sem.get_stig_xy()

        self.ft_pixel_size = self.spinBox_ftPixelSize.value()
        self.ft_slider_delta = self.verticalSlider_ftDelta.value() + 1
        blank_img = QPixmap(512, 384)
        blank_img.fill(QColor(0, 0, 0))
        self.img_focusToolViewer.setPixmap(blank_img)
        QApplication.processEvents()
        ft_thread = threading.Thread(target=self.ft_acq_series_thread)
        ft_thread.start()

    def ft_acq_series_thread(self):
        # Move to stage pos of selected tile:
        if self.ft_selected_ov >= 0:
            # Use overview selection:
            stage_x, stage_y = self.cs.get_ov_centre_s(self.ft_selected_ov)
        elif self.ft_selected_tile >= 0:
            stage_x, stage_y = self.gm.get_tile_coordinates_s(
                self.ft_selected_grid, self.ft_selected_tile)
        # Move stage:
        stage_x += self.ft_counter * 800 * self.ft_pixel_size/1000
        stage_y += self.ft_counter * 800 * self.ft_pixel_size/1000
        # Move in thread:
        self.stage.move_to_xy((stage_x, stage_y))

        if self.radioButton_focus.isChecked():
            self.ft_delta = (
                0.00000004 * self.ft_slider_delta * self.ft_pixel_size)
            self.ft_acquire_focus_series()

        if self.radioButton_stigX.isChecked():
            self.ft_delta = (
                0.008 * self.ft_slider_delta * self.ft_pixel_size)
            self.ft_acquire_stig_series(0)

        if self.radioButton_stigY.isChecked():
            self.ft_delta = 0.008 * self.ft_slider_delta * self.ft_pixel_size
            self.ft_acquire_stig_series(1)

    def ft_reset(self):
        self.pushButton_focusToolStart.setText('Start')
        self.pushButton_focusToolStart.setEnabled(True)
        self.pushButton_focusToolMove.setEnabled(True)
        self.pushButton_focusToolSet.setEnabled(True)
        self.spinBox_ftPixelSize.setEnabled(True)
        self.checkBox_zoom.setEnabled(True)
        self.verticalSlider_ftDelta.setEnabled(True)
        self.radioButton_focus.setEnabled(True)
        self.radioButton_stigX.setEnabled(True)
        self.radioButton_stigY.setEnabled(True)
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
        self.pushButton_focusToolStart.setText('Done')
        self.pushButton_focusToolStart.setEnabled(True)
        # Stage position may have changed. Update in main controls tab
        self.show_current_stage_xy()
        # Increase counter to move to fresh area for next cycle:
        self.ft_counter += 1
        if self.ft_counter > 10:
            self.ft_counter = 0

    def ft_acquire_focus_series(self):
        self.sem.apply_frame_settings(1, self.ft_pixel_size, 0.8)
        self.sem.set_beam_blanking(0)
        self.ft_series_img = []
        self.ft_series_wd_values = []
        deltas = [-4, -3, -2, -1, 0, 1, 2, 3, 4]
        self.ft_fdeltas = [self.ft_delta * x for x in deltas]
        for i in range(9):
            self.sem.set_wd(self.ft_selected_wd + self.ft_fdeltas[i])
            self.ft_series_wd_values.append(
                self.ft_selected_wd + self.ft_fdeltas[i])
            filename = (self.cfg['acq']['base_dir']
                        + '\\workspace\\ft' + str(i) + '.bmp')
            self.sem.acquire_frame(filename)
            self.ft_series_img.append(QPixmap(filename))
        self.sem.set_beam_blanking(1)
        # Display current focus:
        self.ft_index = 4
        self.ft_display_during_cycle()
        self.ft_mode = 1
        self.ft_series_complete()

    def ft_acquire_stig_series(self, xy_choice):
        self.sem.apply_frame_settings(1, self.ft_pixel_size, 0.8)
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
            filename = (self.cfg['acq']['base_dir']
                        + '\\workspace\\ft' + str(i) + '.bmp')
            self.sem.acquire_frame(filename)
            self.ft_series_img.append(QPixmap(filename))
        self.sem.set_beam_blanking(1)
        # Display at current stigmation setting:
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

    def ft_update_grid_selector(self, current_grid=0):
        if current_grid >= self.gm.get_number_grids():
            current_grid = 0
        self.comboBox_selectGridFT.blockSignals(True)
        self.comboBox_selectGridFT.clear()
        self.comboBox_selectGridFT.addItems(self.gm.get_grid_str_list())
        self.comboBox_selectGridFT.setCurrentIndex(current_grid)
        self.ft_selected_grid = current_grid
        self.comboBox_selectGridFT.currentIndexChanged.connect(
            self.ft_change_grid_selection)
        self.comboBox_selectGridFT.blockSignals(False)

    def ft_update_tile_selector(self, current_tile=-1):
        self.comboBox_selectTileFT.blockSignals(True)
        self.comboBox_selectTileFT.clear()
        # If adaptive focus activated for selected grid, only show af_tiles!
        if self.gm.is_adaptive_focus_active(self.ft_selected_grid):
            self.comboBox_selectTileFT.addItems(
                ['Select tile']
                + self.gm.get_af_tile_str_list(self.ft_selected_grid))
            self.label_AFnotification.setText(
                'Adaptive focus active in this grid.')
        else:
            self.comboBox_selectTileFT.addItems(
                ['Select tile']
                + self.gm.get_tile_str_list(self.ft_selected_grid))
            self.label_AFnotification.setText('')

        self.comboBox_selectTileFT.setCurrentIndex(current_tile + 1)
        if (self.gm.is_adaptive_focus_active(self.ft_selected_grid)
            and current_tile >= 0):
            self.ft_selected_tile = self.gm.get_adaptive_focus_tiles(
                self.ft_selected_grid)[current_tile]
        else:
            self.ft_selected_tile = current_tile
        self.comboBox_selectTileFT.currentIndexChanged.connect(
            self.ft_load_selected_tile)
        self.comboBox_selectTileFT.blockSignals(False)

    def ft_update_ov_selector(self, current_ov=-1):
        if current_ov >= self.ovm.get_number_ov():
            current_ov = -1
        self.comboBox_selectOVFT.blockSignals(True)
        self.comboBox_selectOVFT.clear()
        self.comboBox_selectOVFT.addItems(
            ['Select OV'] + self.ovm.get_ov_str_list())
        self.comboBox_selectOVFT.setCurrentIndex(current_ov + 1)
        self.ft_selected_ov = current_ov
        self.comboBox_selectOVFT.currentIndexChanged.connect(
            self.ft_load_selected_ov)
        self.comboBox_selectOVFT.blockSignals(False)

    def ft_change_grid_selection(self):
        self.ft_selected_grid = self.comboBox_selectGridFT.currentIndex()
        self.ft_update_tile_selector()

    def ft_load_selected_tile(self):
        current_selection = self.comboBox_selectTileFT.currentIndex() - 1
        if (self.gm.is_adaptive_focus_active(self.ft_selected_grid)
            and current_selection >= 0):
            self.ft_selected_tile = self.gm.get_adaptive_focus_tiles(
                self.ft_selected_grid)[current_selection]
        else:
            self.ft_selected_tile = current_selection
        # show current focus and stig:
        if self.ft_selected_tile >= 0:
            #self.ft_selected_wd = self.sem.get_wd()
            self.ft_update_ov_selector(-1)
            #if self.gm.is_adaptive_focus_active(self.ft_selected_grid):
            self.ft_selected_wd = self.gm.get_tile_wd(
                self.ft_selected_grid, self.ft_selected_tile)
            self.ft_selected_stig_x, self.ft_selected_stig_y = (
                self.gm.get_tile_stig_xy(
                    self.ft_selected_grid, self.ft_selected_tile))
            self.ft_update_wd_display()
            self.ft_update_stig_display()
        elif self.ft_selected_ov == -1:
            self.ft_clear_wd_stig_display()

        if (self.af.is_active() and self.af.is_ref_tile(
                self.ft_selected_grid, self.ft_selected_tile)):
            self.label_AFnotification.setText(
                'WD/STIG of selected tile are being tracked.')
        elif self.gm.is_adaptive_focus_active(self.ft_selected_grid):
            self.label_AFnotification.setText(
                'Adaptive focus active in this grid.')
        else:
            self.label_AFnotification.setText('')
        # Clear current image:
        self.ft_clear_display()

    def ft_load_selected_ov(self):
        self.ft_selected_ov = self.comboBox_selectOVFT.currentIndex() - 1
        if self.ft_selected_ov >= 0:
            self.ft_update_tile_selector(-1)
            self.ft_selected_wd = self.ovm.get_ov_wd(self.ft_selected_ov)
            self.ft_selected_stig_x, self.ft_selected_stig_y = (
                self.ovm.get_ov_stig_xy(self.ft_selected_ov))
            self.ft_update_wd_display()
            self.ft_update_stig_display()
        elif self.ft_selected_tile == -1:
            self.ft_clear_wd_stig_display()
        # Clear current image:
        self.ft_clear_display()

    def ft_set_selection_from_mv(self):
        selected_ov = self.viewport.mv_get_selected_ov()
        selected_grid = self.viewport.mv_get_selected_grid()
        selected_tile = self.viewport.mv_get_selected_tile()
        if (selected_grid is not None) and (selected_tile is not None):
            self.ft_selected_grid = selected_grid
            if self.gm.is_adaptive_focus_active(selected_grid):
                af_tiles = self.gm.get_adaptive_focus_tiles(selected_grid)
                if selected_tile in af_tiles:
                    self.ft_selected_tile = af_tiles.index(selected_tile)
                else:
                    self.ft_selected_tile = -1
            else:
                self.ft_selected_tile = selected_tile
            self.comboBox_selectGridFT.blockSignals(True)
            self.comboBox_selectGridFT.setCurrentIndex(self.ft_selected_grid)
            self.comboBox_selectGridFT.blockSignals(False)
            self.comboBox_selectTileFT.blockSignals(True)
            self.comboBox_selectTileFT.setCurrentIndex(
                self.ft_selected_tile + 1)
            self.comboBox_selectTileFT.blockSignals(False)
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

    def ft_toggle_zoom(self):
        self.ft_zoom = self.ft_zoom == False
        if self.ft_mode > 0:
            self.ft_display_during_cycle()

    def keyPressEvent(self, event):
        if (type(event) == QKeyEvent) and (self.tabWidget.currentIndex() == 1):
            if event.key() == Qt.Key_PageUp:
                self.ft_move_up()
            if event.key() == Qt.Key_PageDown:
                self.ft_move_down()

    def wheelEvent(self, event):
        if self.tabWidget.currentIndex() == 1:
            #print('Wheel event', event.angleDelta())
            if event.angleDelta().y() > 0:
                self.ft_move_up()
            if event.angleDelta().y() < 0:
                self.ft_move_down()
