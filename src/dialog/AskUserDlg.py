from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class AskUserDlg(QDialog):
    """Specify for which events the program should let the user decide how
    to proceed. The "Ask User" functionality is currently only used for
    debris detection. Will be expanded, work in progress...
    """

    def __init__(self):
        super().__init__()
        loadUi('gui/ask_user_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
