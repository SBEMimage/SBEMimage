from qtpy.QtCore import Qt
from qtpy.QtGui import QPixmap
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils
from constants import VERSION


class AboutBox(QDialog):
    """Show the About dialog box with info about SBEMimage and the current
    version and release date.
    """

    def __init__(self):
        super().__init__()
        loadUi('gui/about_box.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        if 'dev' in VERSION.lower():
            self.label_version.setText(f'DEVELOPMENT VERSION ({VERSION})')
        else:
            self.label_version.setText('Version ' + VERSION)
        self.labelIcon.setPixmap(QPixmap('img/logo.png'))
        # Enable links to documentation and GitHub
        self.label_readthedocs.setText('<a href="https://sbemimage.github.io/sbemimage">'
                                       'sbemimage.github.io/sbemimage</a>')
        self.label_readthedocs.setOpenExternalLinks(True)
        self.label_github.setText('<a href="https://github.com/SBEMimage">'
                                  'github.com/SBEMimage</a>')
        self.label_github.setOpenExternalLinks(True)
        self.setFixedSize(self.size())
        self.show()
