from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class SetStartTileDlg(QDialog):
    """Adjust the grid/tile at which to (re)start the acquisition."""

    def __init__(self, acquisition, grid_manager):
        super().__init__()
        self.acq = acquisition
        self.gm = grid_manager
        loadUi('gui/set_start_tile_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        if self.acq.acq_interrupted:
            self.label_acqstatus1.setText(
                'The acquisition was interrupted/paused')
            grid_index, tile_index = self.acq.acq_interrupted_at
        else:
            self.label_acqstatus1.setText(
                'The acquisition was not interrupted')
            grid_index = None
            # Find first tile to be acquired
            for g in range(self.gm.number_grids):
                if (self.gm[g].active
                        and self.gm[g].active_tiles):
                    # First active grid
                    grid_index = g
                    break
            if grid_index is not None:
                # First active tile in first active grid
                tile_index = self.gm[grid_index].active_tiles[0]
            else:
                grid_index, tile_index = 0, 0

        if grid_index is not None:
            grid = self.gm[grid_index]
            grid_label = grid.get_label(grid_index)

            self.label_acqstatus2.setText(
                f'and will (re)start at tile {tile_index} in {grid_label}.')

            # Populate grid selector
            self.comboBox_gridSelector.clear()
            self.comboBox_gridSelector.addItems(self.gm.grid_selector_list())
            self.comboBox_gridSelector.setCurrentIndex(grid_index)
            self.comboBox_gridSelector.currentIndexChanged.connect(
                self.update_tile_selector)
            # Populate tile selector
            self.update_tile_selector()
            # Select current tile (+1 to account for entry 'Select tile')
            self.comboBox_tileSelector.setCurrentIndex(tile_index + 1)

    def update_tile_selector(self):
        """Populate the tile selector with the active tiles of the currently
        selected grid.
        """
        selected_grid = self.comboBox_gridSelector.currentIndex()
        self.comboBox_tileSelector.clear()
        self.comboBox_tileSelector.addItems(
            ['Select tile']
            + self.gm[selected_grid].tile_selector_list())
        self.comboBox_tileSelector.setCurrentIndex(0)

    def accept(self):
        grid_index = self.comboBox_gridSelector.currentIndex()
        tile_index = self.comboBox_tileSelector.currentIndex() - 1
        if tile_index == -1:
            QMessageBox.warning(
                self, 'No tile selected',
                'Please select a tile or click "Cancel"',
                QMessageBox.Ok)
        elif not self.gm[grid_index][tile_index].tile_active:
            QMessageBox.warning(
                self, 'Select active tile',
                'The tile you selected is currently inactive. Please select '
                'an active tile.',
                QMessageBox.Ok)
        else:
            # Set selected tile as new interruption point
            self.acq.set_interruption_point(grid_index, tile_index,
                                            during_acq=False)
            super().accept()
