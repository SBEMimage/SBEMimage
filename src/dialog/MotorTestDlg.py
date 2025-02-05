import datetime
import os
from random import random
from time import time, sleep
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox, QApplication
from qtpy.uic import loadUi

import utils
from constants import Error


class MotorTestDlg(QDialog):
    """Perform a random-walk-like XYZ motor test. Experimental, only for
    testing/debugging. Only works with a microtome for now."""

    def __init__(self, microtome, acq, main_controls_trigger):
        super().__init__()
        self.microtome = microtome
        self.acq = acq
        self.main_controls_trigger = main_controls_trigger
        loadUi('gui/motor_test_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
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
