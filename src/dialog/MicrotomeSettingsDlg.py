from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils
from dialog.SetStagePositionDlg import SetStagePositionDlg
from dialog.MotorStatusDlg import MotorStatusDlg


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
        loadUi('gui/microtome_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
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
        dialog.exec()

    def open_set_stage_position_dlg(self):
        dialog = SetStagePositionDlg(self.stage, self.main_controls_trigger)
        dialog.exec()

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
