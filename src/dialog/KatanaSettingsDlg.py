from qtpy.QtCore import Qt
from qtpy.QtGui import QPalette, QColor
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class KatanaSettingsDlg(QDialog):
    """Adjust settings for the katana microtome.
    (Under development)
    """

    def __init__(self, microtome):
        super().__init__()
        self.microtome = microtome
        loadUi('gui/katana_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()

        # Set up COM port selector
        available_ports = utils.get_serial_ports()
        self.comboBox_portSelector.addItems(available_ports)
        if self.microtome.selected_port in available_ports:
            self.comboBox_portSelector.setCurrentIndex(
                available_ports.index(self.microtome.selected_port))
        else:
            self.comboBox_portSelector.setCurrentIndex(0)
        self.comboBox_portSelector.currentIndexChanged.connect(
            self.connect_to_new_com_port)

        self.display_connection_status()
        self.display_current_settings()

    def connect_to_new_com_port(self):
        """Attempt connection to new port."""
        self.microtome.selected_port = self.comboBox_portSelector.currentText()
        self.microtome.connect()
        self.display_connection_status()

    def display_connection_status(self):
        # Show message in dialog whether or not katana is connected.
        pal = QPalette(self.label_connectionStatus.palette())
        if self.microtome.connected:
            # Use red colour if not connected
            pal.setColor(QPalette.WindowText, QColor(Qt.black))
            self.label_connectionStatus.setPalette(pal)
            self.label_connectionStatus.setText('katana microtome connected.')
        else:
            pal.setColor(QPalette.WindowText, QColor(Qt.red))
            self.label_connectionStatus.setPalette(pal)
            self.label_connectionStatus.setText(
                'katana microtome is not connected.')

    def display_current_settings(self):
        self.spinBox_knifeCutSpeed.setValue(
            self.microtome.knife_cut_speed)
        self.spinBox_knifeFastSpeed.setValue(
            self.microtome.knife_fast_speed)
        cut_window_start, cut_window_end = (
            self.microtome.cut_window_start, self.microtome.cut_window_end)
        self.spinBox_cutWindowStart.setValue(cut_window_start)
        self.spinBox_cutWindowEnd.setValue(cut_window_end)

        self.checkBox_useOscillation.setChecked(
            self.microtome.use_oscillation)
        self.spinBox_oscAmplitude.setValue(
            self.microtome.oscillation_amplitude)
        self.spinBox_oscFrequency.setValue(
            self.microtome.oscillation_frequency)
        if not self.microtome.simulation_mode and self.microtome.connected:
            self.doubleSpinBox_zPosition.setValue(self.microtome.get_stage_z())
        z_range_min, z_range_max = self.microtome.z_range
        self.doubleSpinBox_zRangeMin.setValue(z_range_min)
        self.doubleSpinBox_zRangeMax.setValue(z_range_max)
        # Retraction clearance is stored in nanometres, display in micrometres
        self.doubleSpinBox_retractClearance.setValue(
            self.microtome.retract_clearance / 1000)

    def accept(self):
        new_com_port = self.comboBox_portSelector.currentText()
        new_cut_speed = self.spinBox_knifeCutSpeed.value()
        new_fast_speed = self.spinBox_knifeFastSpeed.value()
        new_cut_start = self.spinBox_cutWindowStart.value()
        new_cut_end = self.spinBox_cutWindowEnd.value()
        new_osc_frequency = self.spinBox_oscFrequency.value()
        new_osc_amplitude = self.spinBox_oscAmplitude.value()
        # retract_clearance in nanometres
        new_retract_clearance = (
            self.doubleSpinBox_retractClearance.value() * 1000)
        # End position of cut window must be smaller than start position:
        if new_cut_end < new_cut_start:
            self.microtome.selected_port = new_com_port
            self.microtome.knife_cut_speed = new_cut_speed
            self.microtome.knife_fast_speed = new_fast_speed
            self.microtome.cut_window_start = new_cut_start
            self.microtome.cut_window_end = new_cut_end
            self.microtome.use_oscillation = (
                self.checkBox_useOscillation.isChecked())
            self.microtome.oscillation_frequency = new_osc_frequency
            self.microtome.oscillation_amplitude = new_osc_amplitude
            self.microtome.retract_clearance = new_retract_clearance
            super().accept()
        else:
            QMessageBox.warning(
                self, 'Invalid input',
                'The start position of the cutting window must be larger '
                'than the end position.',
                QMessageBox.Ok)
