from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class CutDurationDlg(QDialog):
    """Dialog to set the duration in seconds of a full cut cycle (near, cut,
    clear).
    """

    def __init__(self, microtome):
        super().__init__()
        self.microtome = microtome
        loadUi('gui/cut_duration_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.doubleSpinBox_cutDuration.setValue(
            self.microtome.full_cut_duration)

    def accept(self):
        self.microtome.full_cut_duration = (
            self.doubleSpinBox_cutDuration.value())
        super().accept()
