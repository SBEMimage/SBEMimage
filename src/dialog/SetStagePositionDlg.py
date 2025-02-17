from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QApplication, QMessageBox
from qtpy.uic import loadUi

import utils
from constants import Error


class SetStagePositionDlg(QDialog):
    """Set stage position to XYZ coordinates selected by user."""

    def __init__(self, stage, main_controls_trigger):
        super().__init__()
        self.stage = stage
        loadUi('gui/set_stage_position_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
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
