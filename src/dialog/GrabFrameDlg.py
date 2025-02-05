import datetime
import os
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox, QApplication
from qtpy.uic import loadUi

import constants
import utils


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
        loadUi('gui/grab_frame_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
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
        self.comboBox_bitDepth.addItems(['8 bit', '16 bit'])
        # Button to load current SEM imaging parameters.
        # For now, only enabled for ZEISS SEMs.
        self.pushButton_getFromSEM.clicked.connect(self.get_settings_from_sem)
        self.pushButton_getFromSEM.setEnabled(
            self.sem.device_name.startswith("ZEISS"))
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
                self.acq.base_dir, self.file_name + constants.FRAME_IMAGE_FORMAT)):
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
        bit_depth_selector = self.comboBox_bitDepth.currentIndex()
        self.sem.apply_grab_settings()
        self.sem.set_bit_depth(bit_depth_selector)
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
            os.path.join(self.acq.base_dir, self.file_name + constants.FRAME_IMAGE_FORMAT),
            self.acq.stage)
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
                + self.file_name + constants.FRAME_IMAGE_FORMAT +
                ' in the current base directory.',
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
        full_file_name = self.file_name + constants.FRAME_IMAGE_FORMAT
        success = self.sem.save_frame(
            os.path.join(self.acq.base_dir, full_file_name),
            self.acq.stage)
        if success:
            utils.log_info('SEM', 'Single frame saved (Grab dialog).')
            QMessageBox.information(
                self, 'Frame saved',
                'The current image shown in SmartSEM was saved as '
                + full_file_name + ' in the current base directory.',
                QMessageBox.Ok)
        else:
            QMessageBox.warning(
                self, 'Error',
                'An error ocurred while attempting to save the current '
                'SmartSEM image: '
                + self.sem.error_info,
                QMessageBox.Ok)
            self.sem.reset_error_state()
