from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class AutofocusZEISSParamsDlg(QDialog):
    """Dialog to adjust parameters for the ZEISS (SmartSEM) Autofocus."""

    def __init__(self, autofocus):
        super().__init__()
        self.autofocus = autofocus
        loadUi('gui/autofocus_zeiss_params_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.doubleSpinBox_pixelSize.setValue(self.autofocus.pixel_size)

    def accept(self):
        self.autofocus.pixel_size = self.doubleSpinBox_pixelSize.value()
        super().accept()
