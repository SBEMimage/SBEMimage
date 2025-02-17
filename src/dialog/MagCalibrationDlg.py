from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class MagCalibrationDlg(QDialog):
    """Calibrate the relationship between magnification and pixel size."""

    def __init__(self, sem):
        super().__init__()
        self.sem = sem
        loadUi('gui/mag_calibration_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_calibrationFactor.setText(
            str(self.sem.MAG_PX_SIZE_FACTOR))
        self.comboBox_frameWidth.addItems(['2048', '4096'])
        self.comboBox_frameWidth.setCurrentIndex(1)
        self.pushButton_calculate.clicked.connect(
            self.calculate_calibration_factor)

    def calculate_calibration_factor(self):
        """Calculate the mag calibration factor from the frame width, the
        magnification and the pixel size.
        """
        frame_width = int(str(self.comboBox_frameWidth.currentText()))
        pixel_size = self.doubleSpinBox_pixelSize.value()
        mag = self.spinBox_mag.value()
        new_factor = int(mag * frame_width * pixel_size)
        user_choice = QMessageBox.information(
            self, 'Calculated calibration factor',
            'Result:\nNew magnification calibration factor: %d '
            '\n\nDo you want to use this value?' % new_factor,
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_choice == QMessageBox.Ok:
            self.lineEdit_calibrationFactor.setText(str(new_factor))

    def accept(self):
        self.sem.MAG_PX_SIZE_FACTOR = int(self.lineEdit_calibrationFactor.text())
        super().accept()
