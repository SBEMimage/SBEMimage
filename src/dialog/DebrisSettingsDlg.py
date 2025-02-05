from statistics import mean
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class DebrisSettingsDlg(QDialog):
    """Adjust the settings for debris detection and removal: Detection area,
    detection method and parameters, max. number of sweeps, and what to do when
    max. sweep number reached.
    """

    def __init__(self, ovm, image_inspector, acq):
        super().__init__()
        self.ovm = ovm
        self.img_inspector = image_inspector
        self.acq = acq
        loadUi('gui/debris_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        # Detection area
        if self.ovm.use_auto_debris_area:
            self.radioButton_autoSelection.setChecked(True)
        else:
            self.radioButton_fullSelection.setChecked(True)
        # Extra margin around detection area in pixels
        self.spinBox_debrisMargin.setValue(
            self.ovm.auto_debris_area_margin)
        self.spinBox_maxSweeps.setValue(self.acq.max_number_sweeps)
        self.doubleSpinBox_diffMean.setValue(
            self.img_inspector.mean_diff_threshold)
        self.doubleSpinBox_diffSD.setValue(
            self.img_inspector.stddev_diff_threshold)
        self.spinBox_diffHistogram.setValue(
            self.img_inspector.histogram_diff_threshold)
        self.spinBox_diffPixels.setValue(
            self.img_inspector.image_diff_threshold)
        self.checkBox_showDebrisArea.setChecked(
            self.ovm.detection_area_visible)
        self.checkBox_continueAcq.setChecked(
            self.acq.continue_after_max_sweeps)
        # Detection methods
        self.radioButton_methodQuadrant.setChecked(
            self.img_inspector.debris_detection_method == 0)
        self.radioButton_methodPixel.setChecked(
            self.img_inspector.debris_detection_method == 1)
        self.radioButton_methodHistogram.setChecked(
            self.img_inspector.debris_detection_method == 2)
        self.radioButton_methodQuadrant.toggled.connect(
            self.update_option_selection)
        self.radioButton_methodHistogram.toggled.connect(
            self.update_option_selection)
        self.update_option_selection()
        self.show_moving_averages()
        # Button to reset moving averages
        self.pushButton_resetAvg.clicked.connect(
            self.reset_moving_averages)

    def update_option_selection(self):
        """Let user only change the parameters for the currently selected
        detection method. The other input fields are deactivated.
        """
        if self.radioButton_methodQuadrant.isChecked():
            self.doubleSpinBox_diffMean.setEnabled(True)
            self.doubleSpinBox_diffSD.setEnabled(True)
            self.spinBox_diffPixels.setEnabled(False)
            self.spinBox_diffHistogram.setEnabled(False)
        elif self.radioButton_methodPixel.isChecked():
             self.doubleSpinBox_diffMean.setEnabled(False)
             self.doubleSpinBox_diffSD.setEnabled(False)
             self.spinBox_diffPixels.setEnabled(True)
             self.spinBox_diffHistogram.setEnabled(False)
        elif self.radioButton_methodHistogram.isChecked():
             self.doubleSpinBox_diffMean.setEnabled(False)
             self.doubleSpinBox_diffSD.setEnabled(False)
             self.spinBox_diffPixels.setEnabled(False)
             self.spinBox_diffHistogram.setEnabled(True)

    def show_moving_averages(self):
        """Show current moving averages for mean and SD differences
        if more than two values (each) available.
        """
        if len(self.img_inspector.mean_diffs) > 2:
            self.lineEdit_diffMeanAvg.setText(
                f'{mean(self.img_inspector.mean_diffs):.2f}')
        else:
            self.lineEdit_diffMeanAvg.setText('-')
        if len(self.img_inspector.stddev_diffs) > 2:
            self.lineEdit_diffSDAvg.setText(
                f'{mean(self.img_inspector.stddev_diffs):.2f}')
        else:
            self.lineEdit_diffSDAvg.setText('-')

    def reset_moving_averages(self):
        self.img_inspector.mean_diffs.clear()
        self.img_inspector.stddev_diffs.clear()
        self.show_moving_averages()

    def accept(self):
        self.ovm.auto_debris_area_margin = self.spinBox_debrisMargin.value()
        self.acq.max_number_sweeps = self.spinBox_maxSweeps.value()
        self.img_inspector.mean_diff_threshold = (
            self.doubleSpinBox_diffMean.value())
        self.img_inspector.stddev_diff_threshold = (
            self.doubleSpinBox_diffSD.value())
        self.img_inspector.histogram_diff_threshold = (
            self.spinBox_diffHistogram.value())
        self.img_inspector.image_diff_threshold = (
            self.spinBox_diffPixels.value())
        self.ovm.use_auto_debris_area = (
            self.radioButton_autoSelection.isChecked())
        self.ovm.detection_area_visible = (
            self.checkBox_showDebrisArea.isChecked())
        self.acq.continue_after_max_sweeps = (
            self.checkBox_continueAcq.isChecked())
        if self.radioButton_methodQuadrant.isChecked():
            self.img_inspector.debris_detection_method = 0
        elif self.radioButton_methodPixel.isChecked():
            self.img_inspector.debris_detection_method = 1
        elif self.radioButton_methodHistogram.isChecked():
            self.img_inspector.debris_detection_method = 2
        super().accept()
