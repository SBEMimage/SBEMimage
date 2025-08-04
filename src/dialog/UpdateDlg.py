import os
import requests
import shutil
from zipfile import ZipFile
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QApplication, QMessageBox
from qtpy.uic import loadUi

import utils


class UpdateDlg(QDialog):
    """Update SBEMimage by downloading latest version from GitHub."""

    def __init__(self):
        super().__init__()
        loadUi('gui/update_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.pushButton_update.clicked.connect(self.update)
        self.show()

    def update(self):
        self.pushButton_update.setText('Busy')
        self.pushButton_update.setEnabled(False)
        QApplication.processEvents()
        url = "https://github.com/SBEMimage/SBEMimage/archive/master.zip"
        try:
            response = requests.get(url, stream=True)
            with open('master.zip', 'wb') as file:
                shutil.copyfileobj(response.raw, file)
            del response
        except:
            QMessageBox.warning(
                self, 'Error',
                'Could not download current version from GitHub. Check your '
                'internet connection. ',
                QMessageBox.Ok)
        else:
            # Get directory of current installation
            install_path = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))
            try:
                with ZipFile("master.zip", "r") as zip_object:
                    for zip_info in zip_object.infolist():
                        if zip_info.filename[-1] == '/':
                            continue
                        # Remove string 'SBEMimage-master/'
                        zip_info.filename = zip_info.filename[17:]
                        # print(zip_info.filename)
                        zip_object.extract(zip_info, install_path)
            except:
                QMessageBox.warning(
                self, 'Error',
                'Could not extract downloaded GitHub archive.',
                QMessageBox.Ok)
            else:
                QMessageBox.information(
                self, 'Update complete',
                'SBEMimage was updated to the most recent version. '
                'You must restart the program to use the updated version.',
                QMessageBox.Ok)
                self.pushButton_update.setText('Update now')
                self.pushButton_update.setEnabled(True)
