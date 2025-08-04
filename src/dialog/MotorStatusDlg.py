from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class MotorStatusDlg(QDialog):
    """Show numbers of total motor moves, failed moves, and slow moves."""

    def __init__(self, stage):
        super().__init__()
        self.stage = stage
        loadUi('gui/motor_status_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
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
