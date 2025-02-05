import math
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox, QApplication
from qtpy.uic import loadUi

import constants
import utils
from UpdateQThread import UpdateQThread


class VariablePressureDlg(QDialog):
    """Set Variable Pressure / High Vacuum."""

    def __init__(self, sem):
        super().__init__()
        self.sem = sem
        self.hv = True
        self.vp = False
        self.target = 0
        self.current = 0
        loadUi('gui/variable_pressure_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_hv.clicked.connect(self.set_hv)
        self.pushButton_vp.clicked.connect(self.set_vp)
        self.lineEdit_target.editingFinished.connect(self.target_text_changed)
        self.horizontalSlider_target.valueChanged.connect(self.target_slider_changed)
        self.comboBox_units.currentTextChanged.connect(self.units_changed)
        self.units = self.comboBox_units.currentText()
        try:
            self.target = self.sem.get_vp_target()
            self.update_target_pressure_text()
            self.update_target_pressure_slider()
            self.thread = UpdateQThread(1)
            self.thread.update.connect(self.update)
            self.thread.start()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Could not read variable pressure settings: '
                + str(e),
                QMessageBox.Ok)
        QApplication.processEvents()

    def set_hv(self):
        try:
            self.sem.set_hv()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Unable to set hv: '
                + str(e),
                QMessageBox.Ok)

    def set_vp(self):
        try:
            self.sem.set_vp()
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Unable to set vp: '
                + str(e),
                QMessageBox.Ok)

    def units_changed(self, text):
        self.units = text
        self.update_target_pressure_text()

    def update(self):
        self.hv = self.sem.is_hv_on()
        self.vp = self.sem.is_vp_on()
        self.current = self.sem.get_chamber_pressure()
        self.pushButton_hv.setEnabled(self.vp)
        self.pushButton_vp.setEnabled(self.hv)
        self.update_pressure(self.lineEdit_current, self.current)

    def update_target_pressure_text(self):
        self.lineEdit_target.blockSignals(True)
        self.update_pressure(self.lineEdit_target, self.target)
        self.lineEdit_target.blockSignals(False)

    def update_target_pressure_slider(self):
        self.horizontalSlider_target.blockSignals(True)
        if self.target > 0:
            value = math.log10(self.target) * 100
        else:
            value = self.horizontalSlider_target.minimum()
        self.horizontalSlider_target.setValue(value)
        self.horizontalSlider_target.blockSignals(False)

    def update_pressure(self, textEdit, value):
        unit_value = value * constants.PRESSURE_FROM_SEM[self.units]
        textEdit.setText("{:.2e}".format(unit_value))

    def target_text_changed(self):
        try:
            unit_value = float(self.lineEdit_target.text())
            self.target = unit_value * constants.PRESSURE_TO_SEM[self.units]
            self.update_target_pressure_slider()
            self.sem.set_vp_target(self.target)
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Invalid value: '
                + str(e),
                QMessageBox.Ok)

    def target_slider_changed(self):
        try:
            self.target = 10 ** (self.horizontalSlider_target.value() * 0.01)
            self.update_target_pressure_text()
            self.sem.set_vp_target(self.target)
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Invalid value: '
                + str(e),
                QMessageBox.Ok)

    def reject(self):
        try:
            self.thread.stop()
        except Exception:
            pass
        super().reject()

    def closeEvent(self, event):
        try:
            self.thread.stop()
        except Exception:
            pass
        event.accept()
