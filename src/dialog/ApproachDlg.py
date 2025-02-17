from time import sleep
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils
from constants import Error


class ApproachDlg(QDialog):
    """Remove slices without imaging. User can specify how many slices and
    the cutting thickness.
    """

    def __init__(self, microtome, main_controls_trigger):
        super().__init__()
        self.microtome = microtome
        self.main_controls_trigger = main_controls_trigger
        loadUi('gui/approach_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
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
        if self.microtome.error_state == Error.mismatch_z:
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
