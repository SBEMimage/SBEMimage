import configparser
import json
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class DeviceSelectionDlg(QDialog):
    """Select SEM/microtome presets to be loaded into the system configuration.
    """

    def __init__(self, presets_enabled, selected_presets):
        super().__init__()
        self.selected_presets = selected_presets
        self.presets_enabled = presets_enabled
        loadUi('gui/device_selection_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        syscfg = configparser.ConfigParser()
        try:
            with open('src/default_cfg/system.cfg', 'r') as file:
                syscfg.read_file(file)
        except Exception as e:
            QMessageBox.warning(
                self, 'Error',
                'Could not read list of supported devices from system.cfg\n'
                'Exception: ' + str(e),
                QMessageBox.Ok)
            return

        sem_list = ['None'] + json.loads(syscfg['device']['sem_recognized'])
        microtome_list = (
            ['None'] + json.loads(syscfg['device']['microtome_recognized']))

        # Populate comboboxes with names of supported devices
        self.comboBox_SEMs.addItems(sem_list)
        self.comboBox_microtomes.addItems(microtome_list)
        if self.selected_presets[0] is not None:
            self.comboBox_SEMs.setCurrentIndex(
                self.comboBox_SEMs.findText(self.selected_presets[0]))
        if self.selected_presets[1] is not None:
            self.comboBox_microtomes.setCurrentIndex(
                self.comboBox_microtomes.findText(self.selected_presets[1]))

        # Only enable comboboxes if "load presets" checked
        self.checkBox_loadPresets.stateChanged.connect(
            self.enable_device_selectors)
        self.checkBox_loadPresets.setChecked(self.presets_enabled)

    def enable_device_selectors(self):
        self.comboBox_SEMs.setEnabled(
            self.checkBox_loadPresets.isChecked())
        self.comboBox_microtomes.setEnabled(
            self.checkBox_loadPresets.isChecked())

    def accept(self):
        if self.checkBox_loadPresets.isChecked():
            self.presets_enabled = True
            if str(self.comboBox_SEMs.currentText()) != 'None':
                self.selected_presets[0] = str(self.comboBox_SEMs.currentText())
            else:
                self.selected_presets[0] = None
            if str(self.comboBox_microtomes.currentText()) != 'None':
                self.selected_presets[1] = str(
                    self.comboBox_microtomes.currentText())
            else:
                self.selected_presets[1] = None
        else:
            self.presets_enabled = False
            self.selected_presets = [None, None]
        super().accept()
