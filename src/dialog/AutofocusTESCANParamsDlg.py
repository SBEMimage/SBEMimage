from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class AutofocusTESCANParamsDlg(QDialog):
    """Dialog to adjust parameters for the TESCAN Autofocus."""

    def __init__(self, autofocus):
        super().__init__()
        self.autofocus = autofocus
        loadUi('gui/autofocus_tescan_params_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.doubleSpinBox_WDrange.setValue(self.autofocus.wd_range)
        self.doubleSpinBox_WDstep.setValue(self.autofocus.wd_final_step)
        self.doubleSpinBox_autostigRange.setValue(self.autofocus.autostig_range)

    def accept(self):
        self.autofocus.wd_range = self.doubleSpinBox_WDrange.value()
        self.autofocus.wd_final_step = self.doubleSpinBox_WDstep.value()
        self.autofocus.autostig_range = self.doubleSpinBox_autostigRange.value()
        super().accept()
