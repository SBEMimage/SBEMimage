from qtpy.QtCore import Qt
from qtpy.QtGui import QPixmap
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class FocusGradientTileSelectionDlg(QDialog):

    def __init__(self, current_ref_tiles):
        super().__init__()
        self.selected = None
        loadUi('gui/wd_gradient_tile_selection_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.grid_illustration.setPixmap(QPixmap('img/grid.png'))
        if current_ref_tiles[0] >= 0:
            self.pushButton_pos0.setText(str(current_ref_tiles[0]))
        else:
            self.pushButton_pos0.setText('-')
        if current_ref_tiles[1] >= 0:
            self.pushButton_pos1.setText(str(current_ref_tiles[1]))
        else:
            self.pushButton_pos1.setText('-')
        if current_ref_tiles[2] >= 0:
            self.pushButton_pos2.setText(str(current_ref_tiles[2]))
        else:
            self.pushButton_pos2.setText('-')
        self.pushButton_pos0.clicked.connect(self.select_pos0)
        self.pushButton_pos1.clicked.connect(self.select_pos1)
        self.pushButton_pos2.clicked.connect(self.select_pos2)

    def select_pos0(self):
        self.selected = 0
        super().accept()

    def select_pos1(self):
        self.selected = 1
        super().accept()

    def select_pos2(self):
        self.selected = 2
        super().accept()
