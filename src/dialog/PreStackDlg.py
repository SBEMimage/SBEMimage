from qtpy.QtCore import Qt
from qtpy.QtGui import QFont
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils
from dialog.SetStartTileDlg import SetStartTileDlg


class PreStackDlg(QDialog):
    """This dialog is called before starting a stack. It lets the user view a
    summary of the stack acquisition setup. It also shows several settings that
    can only be changed in DM and lets the user adjust them for logging
    purposes.
    """

    def __init__(self, acq, sem, microtome, autofocus, ovm, gm):
        super().__init__()
        self.acq = acq
        self.sem = sem
        self.microtome = microtome
        self.gm = gm
        loadUi('gui/pre_stack_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        # Different labels if stack is paused ('Continue' instead of 'Start')
        if self.acq.acq_paused:
            self.pushButton_startAcq.setText('Continue acquisition')
            self.setWindowTitle('Continue acquisition')
        self.pushButton_startAcq.clicked.connect(self.accept)
        self.pushButton_editInterruption.clicked.connect(
            self.edit_interruption_point)
        boldFont = QFont()
        boldFont.setBold(True)
        # Show the most relevant current settings for the acquisition
        self.label_stackName.setText(self.acq.stack_name)
        self.label_sliceCounter.setText(str(self.acq.slice_counter))
        self.label_beamSettings.setText(self.sem.get_beam_label())
        if self.acq.take_overviews:
            number_ov = ovm.total_number_active_overviews()
        else:
            number_ov = 0
        self.label_gridSetup.setText(
            f'{number_ov} overview(s), '
            f'{self.gm.total_number_active_grids()} grid(s);')
        self.label_totalActiveTiles.setText(
            f'{self.gm.total_number_active_tiles()} active tile(s)')
        if self.acq.use_autofocus:
            if autofocus.method == 0:
                self.label_autofocusActive.setFont(boldFont)
                self.label_autofocusActive.setText('Active (SEM)')
            elif autofocus.method == 1:
                self.label_autofocusActive.setFont(boldFont)
                self.label_autofocusActive.setText('Active (heuristic)')
            if autofocus.method == 3:
                self.label_autofocusActive.setFont(boldFont)
                self.label_autofocusActive.setText('Active (MAPFoSt)')
        else:
            self.label_autofocusActive.setText('Inactive')
        if self.gm.wd_gradient_active():
            self.label_gradientActive.setFont(boldFont)
            self.label_gradientActive.setText('Active')
        else:
            self.label_gradientActive.setText('Inactive')
        if self.gm.intervallic_acq_active() or ovm.intervallic_acq_active():
            self.label_intervallicActive.setFont(boldFont)
            self.label_intervallicActive.setText('Active')
        else:
            self.label_intervallicActive.setText('Inactive')
        self.show_interruption_point()
        self.doubleSpinBox_brightness.setValue(self.sem.bsd_brightness)
        self.doubleSpinBox_contrast.setValue(self.sem.bsd_contrast)
        self.spinBox_bias.setValue(int(self.sem.bsd_bias))
        if self.microtome is None:
            self.groupBox_dmSettings.setEnabled(False)
        if self.microtome is not None and self.microtome.device_name != 'GCIB':
            self.checkBox_oscillation.setChecked(self.microtome.use_oscillation)
            self.doubleSpinBox_cutSpeed.setValue(
                self.microtome.knife_cut_speed / 1000)
            self.doubleSpinBox_retractSpeed.setValue(
                self.microtome.knife_retract_speed / 1000)

    def edit_interruption_point(self):
        dialog = SetStartTileDlg(self.acq, self.gm)
        dialog.exec()
        # Update interruption point label
        self.show_interruption_point()

    def show_interruption_point(self):
        if self.acq.acq_interrupted:
            boldFont = QFont()
            boldFont.setBold(True)
            self.label_interruption.setFont(boldFont)
            self.label_interruption.setText(
                f'Yes, in grid {self.acq.acq_interrupted_at[0]} '
                f'at tile {self.acq.acq_interrupted_at[1]}')
        else:
            self.label_interruption.setText('None')

    def accept(self):
        # Save updated settings
        self.sem.bsd_contrast = self.doubleSpinBox_contrast.value()
        self.sem.bsd_brightness = self.doubleSpinBox_brightness.value()
        self.sem.bsd_bias = self.spinBox_bias.value()
        if self.microtome is not None and self.microtome.device_name != 'GCIB':
            self.microtome.use_oscillation = self.checkBox_oscillation.isChecked()
            self.microtome.knife_cut_speed = int(
                self.doubleSpinBox_cutSpeed.value() * 1000)
            self.microtome.knife_retract_speed = int(
                self.doubleSpinBox_retractSpeed.value() * 1000)
        super().accept()
