from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils
from dialog.AutofocusTESCANParamsDlg import AutofocusTESCANParamsDlg
from dialog.AutofocusZEISSParamsDlg import AutofocusZEISSParamsDlg


class AutofocusSettingsDlg(QDialog):
    """Dialog to adjust settings for the SEM autofocus, the heuristic autofocus,
    MAPFoSt, AFSS and for tracking the focus/stig when refocusing manually.
    """
    def __init__(self, sem, autofocus, grid_manager, image_inspector):
        super().__init__()
        self.sem = sem
        self.autofocus = autofocus
        self.gm = grid_manager
        self.img_inspector = image_inspector
        loadUi('gui/autofocus_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        if self.autofocus.method == 0:
            self.radioButton_useSEM.setChecked(True)
        elif self.autofocus.method == 1:
            self.radioButton_useHeuristic.setChecked(True)
        elif self.autofocus.method == 2:
            self.radioButton_useTrackingOnly.setChecked(True)
        elif self.autofocus.method == 3:
            self.radioButton_useMAPFoSt.setChecked(True)
        elif self.autofocus.method == 4:
            self.radioButton_useAFSS.setChecked(True)
        self.radioButton_useSEM.toggled.connect(self.group_box_update)
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
        # SEM autofocus
        self.spinBox_interval.setValue(self.autofocus.interval)
        self.spinBox_autostigDelay.setValue(self.autofocus.autostig_delay)
        if self.autofocus.mapfost_large_aberrations:
            self.radioButton_mapfost_largeaberr.setChecked(True)
        if self.sem.device_name.startswith("ZEISS"):
            self.label_af_params.setText(
                "SmartSEM autofocus/autostigmator parameters:")
            self.radioButton_useSEM.setText(
                "Use SmartSEM autofocus/autostigmator")
            self.toolButton_autofocusParameters.clicked.connect(
                self.open_zeiss_params_dlg)
        elif self.sem.device_name.startswith("TESCAN"):
            self.radioButton_useSEM.setText(
                "Use TESCAN autofocus/autostigmator")
            self.label_af_params.setText(
                "TESCAN autofocus/autostigmator parameters:")
            self.toolButton_autofocusParameters.clicked.connect(
                self.open_tescan_params_dlg)
        else:
            self.toolButton_autofocusParameters.setEnabled(False)
        # Heuristic autofocus
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
        # Automated Focus/Stigmator Series:
        self.spinBox_afss_interval.setValue(self.autofocus.interval)  # shared with SEM autofocus
        self.spinBox_afss_offset.setValue(self.autofocus.afss_offset)
        self.doubleSpinBox_afss_wdDiff.setValue(self.autofocus.afss_wd_delta * 1000000)
        self.doubleSpinBox_afss_stigXDiff.setValue(self.autofocus.afss_stig_x_delta)
        self.doubleSpinBox_afss_stigYDiff.setValue(self.autofocus.afss_stig_y_delta)
        self.spinBox_afss_rounds.setValue(self.autofocus.afss_rounds)
        cons_modes = ['Average', 'Specific', 'Specific: Focus, Average: Stig']
        self.comboBox_afss_consensus_mode.addItems(cons_modes)
        self.comboBox_afss_consensus_mode.setCurrentIndex(self.autofocus.afss_consensus_mode)
        self.checkBox_afss_drift_corrected.setChecked(self.autofocus.afss_drift_corrected)
        self.checkBox_afss_autostig_active.setChecked(self.autofocus.afss_autostig_active)
        self.spinBox_afss_fails.setValue(self.autofocus.afss_max_fails)
        self.doubleSpinBox_afss_rmse_limit.setValue(self.autofocus.afss_rmse_limit)
        self.checkBox_afss_background_mode.setChecked(self.autofocus.afss_background_mode)
        self.mode_keys = ('focus', 'stig_x', 'stig_y')
        self.mode_vals = ('AutoFocus', 'AutoStigX', 'AutoStigY')
        self.afss_modes = dict(zip(self.mode_keys, self.mode_vals))
        self.comboBox_afss_mode.addItems(list(self.mode_vals))
        self.comboBox_afss_mode.setCurrentIndex(self.mode_keys.index(self.autofocus.afss_mode))
        self.comboBox_afss_upcoming_mode.addItems(list(self.mode_vals))
        # Resolve upcoming AFSS mode
        if self.autofocus.afss_upcoming_mode is None:
            self.autofocus.afss_upcoming_mode = self.autofocus.next_afss_mode()
        if not self.autofocus.acquisition_running:
            self.comboBox_afss_upcoming_mode.setCurrentIndex(self.mode_keys.index(self.autofocus.afss_upcoming_mode))
        # Disable AFSS setters if AutoStigmator is disabled
        if not self.autofocus.afss_autostig_active:
            self.comboBox_afss_mode.setEnabled(False)
            self.comboBox_afss_upcoming_mode.setEnabled(False)
        # Ensure correct AFSS setters when acquisition is running
        if self.autofocus.acquisition_running:
            self.comboBox_afss_mode.setEnabled(False)
            if self.autofocus.afss_autostig_active:
                self.comboBox_afss_upcoming_mode.setEnabled(True)
                up_ind = self.mode_keys.index(self.autofocus.afss_upcoming_mode)
                self.comboBox_afss_upcoming_mode.setCurrentIndex(up_ind)
        else:
            self.comboBox_afss_upcoming_mode.setEnabled(False)
        # User enables/disables AutoStigmator
        self.checkBox_afss_autostig_active.stateChanged.connect(self.switch_afss_mode_combobox)
            
        # Disable some settings if Array mode is active
        if self.gm.array_mode:
            self.radioButton_useHeuristic.setEnabled(False)
            self.radioButton_useTrackingOnly.setEnabled(False)
            self.radioButton_useMAPFoSt.setEnabled(False)
            self.radioButton_useAFSS.setEnabled(False)
            self.comboBox_trackingMode.setEnabled(False)
            self.spinBox_interval.setEnabled(False)
            # make autostig interval work on grids instead of slices
            self.label_autostig_delay_1.setText('Autostig interval (grids) ')

    def switch_afss_mode_combobox(self, state):
        if state == Qt.Checked:
            if self.autofocus.acquisition_running:
                self.comboBox_afss_mode.setEnabled(False)
            else:
                self.comboBox_afss_mode.setEnabled(True)
            if self.autofocus.afss_active:
                self.comboBox_afss_mode.setCurrentIndex(self.mode_keys.index(self.autofocus.afss_mode))
                self.comboBox_afss_upcoming_mode.setEnabled(True)
                self.comboBox_afss_upcoming_mode.setCurrentIndex(
                    self.mode_keys.index(self.autofocus.afss_upcoming_mode))
        else:
            self.comboBox_afss_mode.setEnabled(False)
            self.comboBox_afss_upcoming_mode.setEnabled(False)
            if not self.autofocus.acquisition_running:
                self.comboBox_afss_mode.setCurrentIndex(self.mode_keys.index('focus'))
            self.comboBox_afss_upcoming_mode.setCurrentIndex(self.mode_keys.index('focus'))

    def group_box_update(self):
        mapfost_enabled = False
        if self.radioButton_useSEM.isChecked():
            sem_af_enabled = True
            heuristic_enabled = False
            diffs_enabled = True
            afss_enabled = False
        elif self.radioButton_useHeuristic.isChecked():
            sem_af_enabled = False
            heuristic_enabled = True
            diffs_enabled = True
            afss_enabled = False
        elif self.radioButton_useTrackingOnly.isChecked():
            sem_af_enabled = False
            heuristic_enabled = False
            diffs_enabled = False
            afss_enabled = False
        elif self.radioButton_useMAPFoSt.isChecked():
            sem_af_enabled = True  # mapfost uses intervall and pixel size value.
            heuristic_enabled = False
            diffs_enabled = True
            mapfost_enabled = True  # TODO: add mapfost parameter group
            afss_enabled = False
        elif self.radioButton_useAFSS.isChecked():
            sem_af_enabled = False
            heuristic_enabled = False
            diffs_enabled = True
            afss_enabled = True
        self.groupBox_SEM_af.setEnabled(sem_af_enabled)
        self.groupBox_heuristic_af.setEnabled(heuristic_enabled)
        self.groupBox_AFSS_af.setEnabled(afss_enabled)
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

    def open_zeiss_params_dlg(self):
        sub_dialog = AutofocusZEISSParamsDlg(self.autofocus)
        sub_dialog.exec()

    def open_tescan_params_dlg(self):
        sub_dialog = AutofocusTESCANParamsDlg(self.autofocus)
        sub_dialog.exec()

    def accept(self):
        error_str = ''
        if self.radioButton_useSEM.isChecked():
            self.autofocus.method = 0
        elif self.radioButton_useHeuristic.isChecked():
            self.autofocus.method = 1
        elif self.radioButton_useTrackingOnly.isChecked():
            self.autofocus.method = 2
        elif self.radioButton_useMAPFoSt.isChecked():
            self.autofocus.method = 3
        elif self.radioButton_useAFSS.isChecked():
            self.autofocus.method = 4

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
        # self.autofocus.pixel_size = self.doubleSpinBox_pixelSize.value()
        self.autofocus.wd_delta = self.doubleSpinBox_wdDiff.value() / 1000000
        self.autofocus.stig_x_delta = self.doubleSpinBox_stigXDiff.value()
        self.autofocus.stig_y_delta = self.doubleSpinBox_stigYDiff.value()

        # AFSS
        self.autofocus.interval = max(self.spinBox_afss_interval.value(), self.spinBox_afss_rounds.value())
        self.autofocus.afss_wd_delta = self.doubleSpinBox_afss_wdDiff.value() / 1000000
        self.autofocus.afss_stig_x_delta = self.doubleSpinBox_afss_stigXDiff.value()
        self.autofocus.afss_stig_y_delta = self.doubleSpinBox_afss_stigYDiff.value()
        self.autofocus.afss_rounds = self.spinBox_afss_rounds.value()
        self.autofocus.afss_offset = self.spinBox_afss_offset.value()
        self.autofocus.afss_consensus_mode = self.comboBox_afss_consensus_mode.currentIndex()
        self.autofocus.afss_drift_corrected = self.checkBox_afss_drift_corrected.isChecked()
        self.autofocus.afss_autostig_active = self.checkBox_afss_autostig_active.isChecked()
        self.autofocus.afss_max_fails = self.spinBox_afss_fails.value()
        self.autofocus.afss_rmse_limit = self.doubleSpinBox_afss_rmse_limit.value()
        self.autofocus.afss_background_mode = self.checkBox_afss_background_mode.isChecked()
        self.autofocus.afss_mode = self.mode_keys[self.comboBox_afss_mode.currentIndex()]
        self.autofocus.afss_upcoming_mode = self.mode_keys[self.comboBox_afss_upcoming_mode.currentIndex()]
        self.img_inspector.afss_drift_corr = self.checkBox_afss_drift_corrected.isChecked()
        if not self.autofocus.acquisition_running:
            self.autofocus.afss_upcoming_mode = self.autofocus.next_afss_mode()
            self.comboBox_afss_upcoming_mode = self.autofocus.afss_upcoming_mode
        else:
            self.comboBox_afss_upcoming_mode = self.autofocus.afss_upcoming_mode

        self.autofocus.heuristic_calibration = [
            self.doubleSpinBox_focusCalib.value(),
            self.doubleSpinBox_stigXCalib.value(),
            self.doubleSpinBox_stigYCalib.value()]
        self.autofocus.rot_angle = self.doubleSpinBox_stigRot.value()
        self.autofocus.scale_factor = self.doubleSpinBox_stigScale.value()
        self.autofocus.mapfost_large_aberrations = self.radioButton_mapfost_largeaberr.isChecked()
        if not error_str:
            super().accept()
        else:
            QMessageBox.warning(self, 'Error', error_str, QMessageBox.Ok)
