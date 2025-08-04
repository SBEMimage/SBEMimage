from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class PauseDlg(QDialog):
    """This dialog is called when the user clicks 'PAUSE' to pause a running
    acquisition. In the dialog, the user can then choose between two options:
    (1) Pause as soon as possible (after acquisition of the current OV or tile
    is complete). (2) Pause after imaging of the current slice is completed and
    the surface has been cut.
    """

    def __init__(self):
        super().__init__()
        loadUi('gui/pause_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.pause_type = 0  # don't pause (when user clicks 'Cancel')
        self.pushButton_pauseNow.clicked.connect(self.pause_now)
        self.pushButton_pauseAfterSlice.clicked.connect(self.pause_later)

    def pause_now(self):
        self.pause_type = 1  # pause immediately
        self.accept()

    def pause_later(self):
        self.pause_type = 2  # pause after slice is completed
        self.accept()

    def accept(self):
        super().accept()
