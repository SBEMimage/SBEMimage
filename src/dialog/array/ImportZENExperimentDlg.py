import os
from time import strftime, localtime

from qtpy.QtCore import Qt, QSize
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QDialog, QFileDialog
from qtpy.uic import loadUi

import utils


class ImportZENExperimentDlg(QDialog):
    """Import a ZEN experiment setup."""

    def __init__(self, msem_variables, main_controls_trigger):
        super().__init__()
        self.msem_variables = msem_variables
        self.main_controls_trigger = main_controls_trigger
        loadUi(os.path.join(
            'gui', 'import_zen_dlg.ui'),
            self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(QIcon(os.path.join(
            'img', 'icon_16px.ico')))
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(
            QIcon(os.path.join('img', 'selectdir.png')))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))
        self.setFixedSize(self.size())
        self.buttonBox.accepted.connect(self.import_zen)
        self.buttonBox.rejected.connect(self.accept)

    def import_zen(self):
        #-----------------------------
        # read sections from zen .json experiment file
        selected_file = os.path.normpath(
            self.lineEdit_fileName.text())

        if not os.path.isfile(selected_file):
            utils.log_info(
                'Array-CTRL',
                'ZEN input file not found')
            self.accept()
            return
        elif os.path.splitext(selected_file)[1] != '.json':
            utils.log_info(
                'Array-CTRL',
                'The file chosen should be in .json format')
            self.accept()
            return

        # update zen experiment flag
        self.main_controls_trigger.transmit(
            'MSEM GUI-'
            + os.path.join(
                os.path.basename(
                    os.path.dirname(selected_file)),
                os.path.basename(selected_file))
            + '-green-'
            + os.path.splitext(
                self.output_name(selected_file))[0])

        self.msem_variables['zen_input_path'] = selected_file

    def output_name(self, path):
        name = os.path.splitext(os.path.basename(path))[0]
        output = (
            name
            + '_from_SBEMimage_'
            + strftime("%Y_%m_%d_%H_%M_%S", localtime())
            + '.json')
        return output

    def select_file(self):
        start_path = 'C:/'
        selected_file = str(QFileDialog.getOpenFileName(
                self, 'Select ZEN experiment file',
                start_path,
                filter='ZEN experiment setup (*.json)'
                )[0])
        if selected_file:
            selected_file = os.path.normpath(selected_file)
            if os.path.splitext(selected_file)[1] == '.json':
                self.lineEdit_fileName.setText(selected_file)

    def accept(self):
        super().accept()
