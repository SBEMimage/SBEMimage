from time import sleep
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox, QApplication
from qtpy.uic import loadUi

import constants
import utils
from UpdateQThread import UpdateQThread


class ChargeCompensatorDlg(QDialog):
    """Set Charge Compensator & level."""

    def __init__(self, sem):
        super().__init__()
        self.sem = sem
        self.state = False
        self.value = 0
        self.vacuum_pressure = 0
        loadUi('gui/charge_compensator_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_on.clicked.connect(self.turn_on)
        self.pushButton_off.clicked.connect(self.turn_off)
        self.doubleSpinBox_level.valueChanged.connect(self.value_changed)
        self.horizontalSlider_level.valueChanged.connect(self.slider_changed)
        self.comboBox_units.currentTextChanged.connect(self.units_changed)
        self.units = self.comboBox_units.currentText()
        try:
            self.state = self.sem.is_fcc_on()
            self.value = self.sem.get_fcc_level()
            self.update_buttons()
            self.update_value()
            self.update_slider()
            self.thread = UpdateQThread(1)
            self.thread.update.connect(self.update)
            self.thread.start()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Could not read charge compensator settings: '
                + str(e),
                QMessageBox.Ok)
        QApplication.processEvents()

    def turn_on(self):
        try:
            self.sem.turn_fcc_on()
            sleep(0.1)
            self.set_fcc_level(self.value)
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Unable to enable fcc: '
                + str(e),
                QMessageBox.Ok)

    def turn_off(self):
        try:
            self.sem.turn_fcc_off()
            self.value = 0
            self.update_value()
            self.update_slider()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Unable to disable fcc: '
                + str(e),
                QMessageBox.Ok)

    def units_changed(self, text):
        self.units = text
        self.update_pressure()

    def update(self):
        self.state = self.sem.is_fcc_on()
        self.vacuum_pressure = self.sem.get_chamber_pressure()
        self.update_buttons()
        self.update_pressure()

    def update_pressure(self):
        unit_value = self.vacuum_pressure * constants.PRESSURE_FROM_SEM[self.units]
        self.lineEdit_vacuumPressure.setText("{:.2e}".format(unit_value))

    def update_buttons(self):
        self.pushButton_on.setEnabled(not self.state)
        self.pushButton_off.setEnabled(self.state)

    def value_changed(self, value):
        self.set_fcc_level(value)
        self.update_slider()

    def slider_changed(self):
        self.set_fcc_level(self.horizontalSlider_level.value() * 0.1)
        self.update_value()

    def update_value(self):
        self.doubleSpinBox_level.blockSignals(True)
        self.doubleSpinBox_level.setValue(self.value)
        self.doubleSpinBox_level.blockSignals(False)

    def update_slider(self):
        self.horizontalSlider_level.blockSignals(True)
        self.horizontalSlider_level.setValue(self.value * 10)
        self.horizontalSlider_level.blockSignals(False)

    def set_fcc_level(self, value):
        if not 0 <= value <= 100:
            QMessageBox.warning(
                self, 'Error',
                    'Please enter a value between 0 and 100', QMessageBox.Ok)
        else:
            self.value = value
            if self.state:
                self.sem.set_fcc_level(value)
