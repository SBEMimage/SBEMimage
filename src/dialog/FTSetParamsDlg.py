from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class FTSetParamsDlg(QDialog):
    """Read working distance and stigmation parameters from user input or
    from SmartSEM for setting WD/STIG for individual tiles/OVs in the
    focus tool.
    """

    def __init__(self, sem, current_wd, current_stig_x, current_stig_y,
                 simulation_mode=False):
        super().__init__()
        self.sem = sem
        loadUi('gui/focus_tool_set_params_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        if simulation_mode:
            self.pushButton_getFromSmartSEM.setEnabled(False)
        self.pushButton_getFromSmartSEM.clicked.connect(self.get_from_sem)
        self.pushButton_resetFocusParams.clicked.connect(self.reset)
        if current_wd is not None:
            self.doubleSpinBox_currentFocus.setValue(1000 * current_wd)
        else:
            self.doubleSpinBox_currentFocus.setValue(0)
        if current_stig_x is not None:
            self.doubleSpinBox_currentStigX.setValue(current_stig_x)
        else:
            self.doubleSpinBox_currentStigX.setValue(0)
        if current_stig_y is not None:
            self.doubleSpinBox_currentStigY.setValue(current_stig_y)
        else:
            self.doubleSpinBox_currentStigY.setValue(0)

    def get_from_sem(self):
        self.doubleSpinBox_currentFocus.setValue(1000 * self.sem.get_wd())
        self.doubleSpinBox_currentStigX.setValue(self.sem.get_stig_x())
        self.doubleSpinBox_currentStigY.setValue(self.sem.get_stig_y())

    def reset(self):
        self.doubleSpinBox_currentFocus.setValue(0)
        self.doubleSpinBox_currentStigX.setValue(0)
        self.doubleSpinBox_currentStigY.setValue(0)

    def accept(self):
        self.new_wd = self.doubleSpinBox_currentFocus.value() / 1000
        self.new_stig_x = self.doubleSpinBox_currentStigX.value()
        self.new_stig_y = self.doubleSpinBox_currentStigY.value()
        super().accept()
