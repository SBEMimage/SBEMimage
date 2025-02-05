from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class GCIBSettingsDlg(QDialog):
    """[WIP] Settings dialog for the GCIB system. Currently not more than a placeholder.
    """
    def __init__(self, microtome):
        super().__init__()
        self.microtome = microtome

        loadUi('gui/gcib_settings_dlg.ui', self)

        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()

        # Set up COM port selector
        # TODO: set up serial selector
        # self.comboBox_portSelector.addItems(utils.get_serial_ports())
        # self.comboBox_portSelector.setCurrentIndex(0)
        # self.comboBox_portSelector.currentIndexChanged.connect(
        #     self.reconnect)

        self.display_connection_status()
        self.display_current_settings()
        self.doubleSpinBox_millCycle.setValue(self.microtome.mill_cycle)
        self.checkBox_useContinuousRotation.setChecked(bool(self.microtome.continuous_rot))

    def reconnect(self):
        pass

    def display_connection_status(self):
        pass
        # pal = QPalette(self.label_connectionStatus.palette())
        # if self.microtome.connected:
        #     # Use red colour if not connected
        #     pal.setColor(QPalette.WindowText, QColor(Qt.black))
        #     self.label_connectionStatus.setPalette(pal)
        #     self.label_connectionStatus.setText('katana microtome connected.')
        # else:
        #     pal.setColor(QPalette.WindowText, QColor(Qt.red))
        #     self.label_connectionStatus.setPalette(pal)
        #     self.label_connectionStatus.setText(
        #         'katana microtome is not connected.')

    def display_current_settings(self):
        # TODO: add parameters from config (non-adjustable for now)
        pass

    def accept(self):
        self.microtome.mill_cycle = self.doubleSpinBox_millCycle.value()
        self.microtome.continuous_rot = int(self.checkBox_useContinuousRotation.isChecked())
        super().accept()
