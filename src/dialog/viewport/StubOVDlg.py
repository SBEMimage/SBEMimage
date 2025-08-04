from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox, QApplication
from qtpy.uic import loadUi
from queue import Queue

import acq_func
import utils


class StubOVDlg(QDialog):
    """Acquire a stub overview image. The user can specify the location
    in stage coordinates and the size of the grid.
    """

    def __init__(self, centre_sx_sy,
                 sem, stage, ovm, acq, img_inspector, viewport_trigger):
        super().__init__()
        loadUi('gui/stub_ov_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.sem = sem
        self.stage = stage
        self.ovm = ovm
        self.acq = acq
        self.img_inspector = img_inspector
        self.viewport_trigger = viewport_trigger
        self.acq_in_progress = False
        self.error_msg_from_acq_thread = ''

        # Set up trigger and queue to update dialog GUI during acquisition
        self.stub_dlg_trigger = utils.Trigger()
        self.stub_dlg_trigger.signal.connect(self.process_thread_signal)
        self.abort_queue = Queue()
        self.pushButton_acquire.clicked.connect(self.start_stub_ov_acquisition)
        self.pushButton_abort.clicked.connect(self.abort)
        self.checkBox_LmMode.setEnabled(self.sem.has_lm_mode())
        self.checkBox_LmMode.stateChanged.connect(self.update_settings_from_ovm)
        self.update_settings_from_ovm()
        self.spinBox_X.setValue(int(round(centre_sx_sy[0])))
        self.spinBox_Y.setValue(int(round(centre_sx_sy[1])))
        self.spinBox_rows.valueChanged.connect(
            self.update_dimension_and_duration_display)
        self.spinBox_cols.valueChanged.connect(
            self.update_dimension_and_duration_display)
        self.spinBox_magnification.valueChanged.connect(
            self.set_magnification)
        # Save previous settings. If user aborts the stub OV acquisition
        # revert to these settings.
        stub_ovm = self.get_selected_stub_ovm()
        self.previous_lm_mode = self.checkBox_LmMode.isChecked()
        self.previous_centre_sx_sy = stub_ovm.centre_sx_sy
        self.previous_grid_size = stub_ovm.size

    def process_thread_signal(self):
        """Process commands from the queue when a trigger signal occurs
        while the acquisition of the stub overview is running.
        """
        cmd = self.stub_dlg_trigger.queue.get()
        msg = cmd['msg']
        args = cmd['args']
        kwargs = cmd['kwargs']
        if msg == 'UPDATE XY':
            self.viewport_trigger.transmit('UPDATE XY')
        elif msg == 'DRAW VP':
            self.viewport_trigger.transmit('DRAW VP')
        elif msg == 'UPDATE PROGRESS':
            percentage = int(str(args[0]))
            self.progressBar.setValue(percentage)
        elif msg == 'STUB OV SUCCESS':
            self.viewport_trigger.transmit('STUB OV SUCCESS')
            self.pushButton_acquire.setEnabled(True)
            self.pushButton_abort.setEnabled(False)
            self.buttonBox.setEnabled(True)
            self.spinBox_X.setEnabled(True)
            self.spinBox_Y.setEnabled(True)
            self.spinBox_rows.setEnabled(True)
            self.spinBox_cols.setEnabled(True)
            QMessageBox.information(
                self, 'Stub Overview acquisition complete',
                'The stub overview was completed successfully.',
                QMessageBox.Ok)
            self.acq_in_progress = False
            self.close()
        elif msg == 'STUB OV FAILURE':
            self.viewport_trigger.transmit('STUB OV FAILURE')
            QMessageBox.warning(
                self, 'Error during stub overview acquisition',
                'An error occurred during the acquisition of the stub '
                'overview mosaic: ' + self.error_msg_from_acq_thread,
                QMessageBox.Ok)
            self.error_msg_from_acq_thread = ''
            self.acq_in_progress = False
            self.close()
        elif msg == 'STUB OV ABORT':
            self.viewport_trigger.transmit('STATUS IDLE')
            # Restore previous grid size and grid position
            stub_ovm = self.get_selected_stub_ovm(self.previous_lm_mode)
            stub_ovm.size = self.previous_grid_size
            stub_ovm.centre_sx_sy = self.previous_centre_sx_sy
            QMessageBox.information(
                self, 'Stub Overview acquisition aborted',
                'The stub overview acquisition was aborted.',
                QMessageBox.Ok)
            self.acq_in_progress = False
            self.close()
        else:
            # Use as error message
            self.error_msg_from_acq_thread = msg

    def get_selected_stub_ovm(self, lm_mode=None):
        if lm_mode is None:
            lm_mode = self.checkBox_LmMode.isChecked()
        if lm_mode:
            stub_ovm = self.ovm['stub_lm']
        else:
            stub_ovm = self.ovm['stub']
        return stub_ovm

    def set_magnification(self):
        stub_ovm = self.get_selected_stub_ovm()
        magnification = self.spinBox_magnification.value()
        stub_ovm.pixel_size = self.sem.MAG_PX_SIZE_FACTOR / (magnification * stub_ovm.frame_size[0])
        self.update_dimension_and_duration_display()

    def update_settings_from_ovm(self):
        stub_ovm = self.get_selected_stub_ovm()
        magnification = int(self.sem.MAG_PX_SIZE_FACTOR / (stub_ovm.frame_size[0] * stub_ovm.pixel_size))
        self.spinBox_magnification.setValue(magnification)
        self.spinBox_rows.setValue(stub_ovm.size[0])
        self.spinBox_cols.setValue(stub_ovm.size[1])
        self.update_dimension_and_duration_display()

    def update_dimension_and_duration_display(self):
        rows = self.spinBox_rows.value()
        cols = self.spinBox_cols.value()
        stub_ovm = self.get_selected_stub_ovm()
        tile_width = stub_ovm.frame_size[0]
        tile_height = stub_ovm.frame_size[1]
        overlap = stub_ovm.overlap
        pixel_size = stub_ovm.pixel_size
        cycle_time = stub_ovm.tile_cycle_time()
        motor_move_time = 0
        if len(stub_ovm) >= 2:
            ov0, ov1 = stub_ovm[0], stub_ovm[1]
            if ov0 is not None and ov1 is not None:
                motor_move_time = self.stage.stage_move_duration(*ov0.sx_sy, *ov1.sx_sy)
        width = int(
            (cols * tile_width - (cols - 1) * overlap) * pixel_size / 1000)
        height = int(
            (rows * tile_height - (rows - 1) * overlap) * pixel_size / 1000)
        duration = int(round(
            (rows * cols * (cycle_time + motor_move_time) + 30) / 60))
        dimension_str = str(width) + ' µm × ' + str(height) + ' µm'
        duration_str = 'Up to ~' + str(duration) + ' min'
        self.label_dimension.setText(dimension_str)
        self.label_duration.setText(duration_str)

    def start_stub_ov_acquisition(self):
        """Acquire the stub overview. Acquisition routine runs in a thread."""
        lm_mode = self.checkBox_LmMode.isChecked()
        # Start acquisition if EHT is on
        if lm_mode or self.sem.is_eht_on():
            self.acq_in_progress = True
            centre_sx_sy = self.spinBox_X.value(), self.spinBox_Y.value()
            grid_size = [self.spinBox_rows.value(), self.spinBox_cols.value()]
            # Change the Stub Overview to the requested grid size and centre
            stub_ovm = self.get_selected_stub_ovm()
            if lm_mode:
                # get correct pixel size value for discrete LM FOV steps
                self.sem.set_em_mode(lm_mode=True)
                self.sem.apply_frame_settings(stub_ovm.frame_size_selector, stub_ovm.pixel_size, stub_ovm.dwell_time)
                stub_ovm.pixel_size = self.sem.get_pixel_size()
            stub_ovm.size = grid_size               # triggers tiles update
            stub_ovm.centre_sx_sy = centre_sx_sy    # triggers tiles update
            self.viewport_trigger.transmit(
                'CTRL: Acquisition of stub overview image started.')
            self.pushButton_acquire.setEnabled(False)
            self.pushButton_abort.setEnabled(True)
            self.buttonBox.setEnabled(False)
            self.spinBox_X.setEnabled(False)
            self.spinBox_Y.setEnabled(False)
            self.spinBox_rows.setEnabled(False)
            self.spinBox_cols.setEnabled(False)
            self.progressBar.setValue(0)
            self.viewport_trigger.transmit('STATUS BUSY STUB')
            QApplication.processEvents()
            utils.run_log_thread(acq_func.acquire_stub_ov,
                                 self.sem, self.stage,
                                 stub_ovm, self.acq,
                                 self.img_inspector,
                                 self.stub_dlg_trigger,
                                 self.abort_queue)
        else:
            QMessageBox.warning(
                self, 'EHT off',
                'EHT / high voltage is off. Please turn '
                'it on before starting the acquisition.',
                QMessageBox.Ok)

    def abort(self):
        if self.abort_queue.empty():
            self.abort_queue.put('ABORT')
            self.pushButton_abort.setEnabled(False)

    def closeEvent(self, event):
        if not self.acq_in_progress:
            event.accept()
        else:
            event.ignore()
