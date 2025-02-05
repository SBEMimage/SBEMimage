import os
import string
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QApplication, QMessageBox
from qtpy.uic import loadUi

import utils


class MirrorDriveDlg(QDialog):
    """Select a mirror drive from all available drives."""

    def __init__(self, acquisition):
        super().__init__()
        self.acq = acquisition
        loadUi('gui/mirror_drive_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.available_drives = []
        self.label_text.setText('Please wait. Searching for drives...')
        QApplication.processEvents()
        # Search for drives in thread. If it gets stuck because drives are
        # not accessible, user can still cancel dialog.
        utils.run_log_thread(self.search_drives)

    def search_drives(self):
        # Search for all available drives:
        self.available_drives = [
            '%s:' % d for d in string.ascii_uppercase
            if os.path.exists('%s:' % d)]
        if self.available_drives:
            self.comboBox_allDrives.addItems(self.available_drives)
            current_index = self.comboBox_allDrives.findText(
                self.acq.mirror_drive)
            if current_index == -1:
                current_index = 0
            self.comboBox_allDrives.setCurrentIndex(current_index)
            # Restore label after searching for available drives:
            self.label_text.setText('Select drive for mirroring acquired data:')

    def accept(self):
        if self.available_drives:
            if (self.comboBox_allDrives.currentText()[0]
                == self.acq.base_dir[0]):
                QMessageBox.warning(
                    self, 'Error',
                    'The mirror drive must be different from the '
                    'base directory drive!', QMessageBox.Ok)
            else:
                self.acq.mirror_drive = (
                    self.comboBox_allDrives.currentText())
                self.acq.mirror_drive_dir = os.path.join(
                    self.acq.mirror_drive, self.acq.base_dir[2:])
                super().accept()
