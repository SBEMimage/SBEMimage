from qtpy.QtCore import Qt
from qtpy.QtGui import QPixmap
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class FocusGradientSettingsDlg(QDialog):
    """Select the tiles to calculate the working distance gradient."""

    def __init__(self, gm, current_grid):
        super().__init__()
        self.gm = gm
        self.current_grid = current_grid
        loadUi('gui/wd_gradient_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_currentGrid.setText(self.gm.get_grid_label(current_grid))
        self.grid_illustration.setPixmap(QPixmap('img/grid.png'))
        self.ref_tiles = self.gm[self.current_grid].wd_gradient_ref_tiles
        # Backup variable for currently selected reference tiles:
        self.prev_ref_tiles = self.ref_tiles.copy()
        # Set up tile selectors for the reference tiles:
        number_of_tiles = self.gm[self.current_grid].number_tiles
        tile_list_str = ['-']
        for tile in range(number_of_tiles):
            tile_list_str.append(str(tile))
        for i in range(3):
            if self.ref_tiles[i] >= number_of_tiles:
                self.ref_tiles[i] = -1

        self.comboBox_tileUpperLeft.blockSignals(True)
        self.comboBox_tileUpperLeft.addItems(tile_list_str)
        self.comboBox_tileUpperLeft.setCurrentIndex(self.ref_tiles[0] + 1)
        self.comboBox_tileUpperLeft.currentIndexChanged.connect(
            self.update_settings)
        self.comboBox_tileUpperLeft.blockSignals(False)

        self.comboBox_tileUpperRight.blockSignals(True)
        self.comboBox_tileUpperRight.addItems(tile_list_str)
        self.comboBox_tileUpperRight.setCurrentIndex(self.ref_tiles[1] + 1)
        self.comboBox_tileUpperRight.currentIndexChanged.connect(
            self.update_settings)
        self.comboBox_tileUpperRight.blockSignals(False)

        self.comboBox_tileLowerLeft.blockSignals(True)
        self.comboBox_tileLowerLeft.addItems(tile_list_str)
        self.comboBox_tileLowerLeft.setCurrentIndex(self.ref_tiles[2] + 1)
        self.comboBox_tileLowerLeft.currentIndexChanged.connect(
            self.update_settings)
        self.comboBox_tileLowerLeft.blockSignals(False)

        self.update_settings()

    def update_settings(self):
        """Get selected working distances and calculate origin WD and
        gradient if possible.
        """
        self.ref_tiles[0] = self.comboBox_tileUpperLeft.currentIndex() - 1
        self.ref_tiles[1] = self.comboBox_tileUpperRight.currentIndex() - 1
        self.ref_tiles[2] = self.comboBox_tileLowerLeft.currentIndex() - 1

        if self.ref_tiles[0] >= 0:
            self.label_t1.setText('Tile ' + str(self.ref_tiles[0]) + ':')
            wd = self.gm[self.current_grid][self.ref_tiles[0]].wd
            self.doubleSpinBox_t1.setValue(wd * 1000)
        else:
            self.label_t1.setText('Tile (-) :')
            self.doubleSpinBox_t1.setValue(0)
        if self.ref_tiles[1] >= 0:
            self.label_t2.setText('Tile ' + str(self.ref_tiles[1]) + ':')
            wd = self.gm[self.current_grid][self.ref_tiles[1]].wd
            self.doubleSpinBox_t2.setValue(wd * 1000)
        else:
            self.label_t2.setText('Tile (-) :')
            self.doubleSpinBox_t2.setValue(0)
        if self.ref_tiles[2] >= 0:
            self.label_t3.setText('Tile ' + str(self.ref_tiles[2]) + ':')
            wd = self.gm[self.current_grid][self.ref_tiles[2]].wd
            self.doubleSpinBox_t3.setValue(wd * 1000)
        else:
            self.label_t3.setText('Tile (-) :')
            self.doubleSpinBox_t3.setValue(0)

        self.gm[self.current_grid].wd_gradient_ref_tiles = self.ref_tiles
        # Try to calculate focus map:
        self.success = self.gm[self.current_grid].calculate_wd_gradient()
        if self.success:
            params = self.gm[self.current_grid].wd_gradient_params
            # print(params)
            current_status_str = (
                'WD: ' + '{:.6f}'.format(params[0] * 1000)
                + ' mm;\n' + chr(8710)
                + 'x: ' + '{:.6f}'.format(params[1] * 1000)
                + '; ' + chr(8710) + 'y: ' + '{:.6f}'.format(params[2] * 1000))
        else:
            current_status_str = 'Insufficient or incorrect tile selection'

        self.textEdit_originGradients.setText(current_status_str)

    def accept(self):
        if self.success:
            super().accept()
        else:
            QMessageBox.warning(
                self, 'Error',
                'Insufficient or incorrect tile selection. Cannot calculate '
                'origin working distance and focus gradient.',
                 QMessageBox.Ok)

    def reject(self):
        # Restore previous selection:
        self.gm[self.current_grid].wd_gradient_ref_tiles = self.prev_ref_tiles
        # Recalculate with previous setting:
        self.gm[self.current_grid].calculate_wd_gradient()
        super().reject()
