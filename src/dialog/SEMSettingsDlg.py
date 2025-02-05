from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class SEMSettingsDlg(QDialog):
    """SEM settings dialog window to adjust target EHT and target beam
    current, aperture size, high current option, and detector selection.
    The current actual beam settings and the current working distance
    and stigmation parameters are displayed.
    """
    def __init__(self, sem):
        super().__init__()
        self.sem = sem
        # Read actual values
        self.actual_eht = self.sem.get_eht()
        self.beam_mode = self.sem.BEAM_CURRENT_MODE.lower()

        loadUi('gui/sem_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()

        self.doubleSpinBox_actualEHT.setValue(self.actual_eht)
        self.doubleSpinBox_EHT.setValue(self.sem.target_eht)

        self.spinBox_beamCurrent.setEnabled(self.beam_mode == 'current')
        self.doubleSpinBox_spotSize.setEnabled(self.beam_mode.startswith('spot'))
        self.comboBox_beamSize.setEnabled(self.beam_mode.startswith('aperture'))
        if self.beam_mode.startswith('aperture'):
            self.actual_aperture_size = self.sem.get_aperture_size()
            self.spinBox_actualBeamSize.setValue(self.actual_aperture_size)
            self.comboBox_beamSize.clear()
            self.comboBox_beamSize.addItems(map(str, self.sem.APERTURE_SIZE))
            self.comboBox_beamSize.setCurrentText(str(self.sem.target_aperture_size))
        elif self.beam_mode.startswith('spot'):
            self.actual_spot_size = self.sem.get_spot_size()
            self.doubleSpinBox_actualSpotSize.setValue(self.actual_spot_size)
            self.doubleSpinBox_spotSize.setValue(self.sem.target_spot_size)
        else:
            self.actual_beam_current = self.sem.get_beam_current()
            self.spinBox_actualBeamCurrent.setValue(self.actual_beam_current)
            self.spinBox_beamCurrent.setValue(self.sem.target_beam_current)

        self.checkBox_highCurrent.setEnabled(self.sem.HAS_HIGH_CURRENT)
        if self.sem.HAS_HIGH_CURRENT:
            self.actual_high_current = self.sem.get_high_current()
            self.checkBox_highCurrent.setChecked(self.actual_high_current)

        # Display current working distance and stigmation parameters
        self.lineEdit_currentFocus.setText(
            '{0:.6f}'.format(sem.get_wd() * 1000))
        self.lineEdit_currentStigX.setText('{0:.6f}'.format(sem.get_stig_x()))
        self.lineEdit_currentStigY.setText('{0:.6f}'.format(sem.get_stig_y()))
        # Show available detectors and set current detector
        try:
            available_detectors = self.sem.get_detector_list()
            current_detector = self.sem.get_detector()
            self.comboBox_detector.addItems(available_detectors)
            if current_detector in available_detectors:
                self.comboBox_detector.setCurrentText(current_detector)
        except NotImplementedError:
            self.comboBox_detector.setEnabled(False)
        # brightness/contrast
        self.has_brightness = self.sem.has_brightness()
        self.has_contrast = self.sem.has_contrast()
        self.has_auto_brightness_contrast = self.sem.has_auto_brightness_contrast()
        self.doubleSpinBox_brightness.setEnabled(self.has_brightness)
        if self.has_brightness:
            self.update_brightness_control()
            self.brightness_initial = self.brightness
            self.doubleSpinBox_brightness.valueChanged.connect(self.brightness_changed)
        self.doubleSpinBox_contrast.setEnabled(self.has_contrast)
        if self.has_contrast:
            self.update_contrast_control()
            self.contrast_initial = self.contrast
            self.doubleSpinBox_contrast.valueChanged.connect(self.contrast_changed)
        self.pushButton_auto_brightness_contrast.setEnabled(self.has_auto_brightness_contrast)
        if self.has_auto_brightness_contrast:
            self.update_auto_brightness_contrast_control()
            self.auto_brightness_contrast_initial = self.sem.get_auto_brightness_contrast()
            self.pushButton_auto_brightness_contrast.clicked.connect(self.auto_brightness_contrast_clicked)

    def brightness_changed(self):
        self.brightness = self.doubleSpinBox_brightness.value() / 100
        self.sem.set_brightness(self.brightness)

    def update_brightness_control(self):
        self.brightness = self.sem.get_brightness()
        self.doubleSpinBox_brightness.setValue(self.brightness * 100)

    def contrast_changed(self):
        self.contrast = self.doubleSpinBox_contrast.value() / 100
        self.sem.set_contrast(self.contrast)

    def update_contrast_control(self):
        self.contrast = self.sem.get_contrast()
        self.doubleSpinBox_contrast.setValue(self.contrast * 100)

    def auto_brightness_contrast_clicked(self):
        enabled = not self.sem.get_auto_brightness_contrast()
        self.sem.set_auto_brightness_contrast(enabled)
        self.update_brightness_control()
        self.update_contrast_control()
        self.update_auto_brightness_contrast_control()

    def update_auto_brightness_contrast_control(self):
        enabled = self.sem.get_auto_brightness_contrast()
        self.pushButton_auto_brightness_contrast.setCheckable(enabled)
        self.pushButton_auto_brightness_contrast.setChecked(enabled)
        self.doubleSpinBox_brightness.setEnabled(self.has_brightness and not enabled)
        self.doubleSpinBox_contrast.setEnabled(self.has_contrast and not enabled)

    def accept(self):
        self.target_eht = self.doubleSpinBox_EHT.value()
        if self.target_eht != self.actual_eht:
            self.sem.set_eht(self.target_eht)

        if self.beam_mode.startswith('aperture'):
            self.target_aperture_size = self.comboBox_beamSize.currentIndex()
            if self.target_aperture_size != self.actual_aperture_size:
                self.sem.set_aperture_size(self.target_aperture_size)
        elif self.beam_mode.startswith('spot'):
            self.target_spot_size = self.doubleSpinBox_spotSize.value()
            if self.target_spot_size != self.actual_spot_size:
                self.sem.set_spot_size(self.target_spot_size)
        else:
            self.target_beam_current = self.spinBox_beamCurrent.value()
            if self.target_beam_current != self.actual_beam_current:
                self.sem.set_beam_current(self.target_beam_current)

        if self.sem.HAS_HIGH_CURRENT:
            self.target_high_current = self.checkBox_highCurrent.isChecked()
            if self.target_high_current != self.actual_high_current:
                self.sem.set_high_current(self.target_high_current)

        selected_detector = self.comboBox_detector.currentText()
        if selected_detector:
            self.sem.set_detector(selected_detector)

        super().accept()

    def reject(self):
        if (self.has_auto_brightness_contrast and
                self.sem.get_auto_brightness_contrast() != self.auto_brightness_contrast_initial):
            self.sem.set_auto_brightness_contrast(self.auto_brightness_contrast_initial)
        if self.has_brightness:
            self.sem.set_brightness(self.brightness_initial)
        if self.has_contrast:
            self.sem.set_contrast(self.contrast_initial)
        super().reject()
