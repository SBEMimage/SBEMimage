import os
import re
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class SaveConfigDlg(QDialog):
    """Save current session configuration in a new .ini file."""

    def __init__(self, syscfg_file='', new_syscfg=False):
        super().__init__()
        self.new_syscfg = new_syscfg
        loadUi('gui/save_config_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_cfgFileName.setText('')
        # lineEdit for syscfg is disabled by default
        self.lineEdit_syscfgFileName.setText(syscfg_file)
        self.file_name = None
        self.sysfile_name = None
        # Show message if a new system configuration file will be created
        # and enable lineEdit
        if new_syscfg:
            QMessageBox.information(
                self, 'New session and system configuration',
                'You are about to save a custom session configuration based '
                'on default.ini. Please also choose a name for your '
                'system configuration in this dialog.\n\n'
                'To create additional session configuration files (after creating '
                'this new one), please load an existing .ini file and save it '
                'under a new name.',
                QMessageBox.Ok)
            self.lineEdit_syscfgFileName.setEnabled(True)
            self.label_syscfgInput.setText(
                'Choose name for your system configuration:')

    def accept(self):
        success = True
        # Replace spaces in file name with underscores.
        self.lineEdit_cfgFileName.setText(
            self.lineEdit_cfgFileName.text().strip().replace(' ', '_'))
        self.lineEdit_syscfgFileName.setText(
            self.lineEdit_syscfgFileName.text().strip().replace(' ', '_'))
        # Check whether characters in name are permitted.
        reg = re.compile('^[a-zA-Z0-9_-]+$')
        if not (reg.match(self.lineEdit_cfgFileName.text())
                and (reg.match(self.lineEdit_syscfgFileName.text())
                     or not self.new_syscfg)):
            success = False
            QMessageBox.warning(
                self, 'Error',
                'Name is empty or badly formatted.',
                QMessageBox.Ok)
        # default.ini and system.cfg may not be chosen.
        if (self.lineEdit_cfgFileName.text().lower() == 'default' or
            self.lineEdit_syscfgFileName.text().lower() == 'system'):
            success = False
            QMessageBox.warning(
                self, 'Error',
                'You cannot choose "default" for the session configuration or '
                '"system" for the system configuration.',
                QMessageBox.Ok)
        # Check if files already exist
        if success:
            self.file_name = self.lineEdit_cfgFileName.text() + '.ini'
            if (os.path.isfile(os.path.join('cfg', self.file_name))):
                success = False
                QMessageBox.warning(
                    self, 'Error',
                    'Session configuration with that name already exists!',
                    QMessageBox.Ok)
            self.sysfile_name = self.lineEdit_syscfgFileName.text() + '.cfg'
            if self.new_syscfg and os.path.isfile(
                    os.path.join('cfg', self.sysfile_name)):
                success = False
                QMessageBox.warning(
                    self, 'Error',
                    'System configuration with that name already exists!',
                    QMessageBox.Ok)

        if success:
            super().accept()
