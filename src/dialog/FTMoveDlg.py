from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils
from constants import Error


class FTMoveDlg(QDialog):
    """Move the stage to the selected tile or OV position."""

    def __init__(self, stage, grid_manager, ov_manager,
                 grid_index, tile_index, ov_index):
        super().__init__()
        self.stage = stage
        self.gm = grid_manager
        self.ovm = ov_manager
        self.ov_index = ov_index
        self.grid_index = grid_index
        self.tile_index = tile_index
        self.error = False
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.move_completed)
        loadUi('gui/focus_tool_move_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_move.clicked.connect(self.start_move)
        if ov_index >= 0:
            self.label_moveTarget.setText('OV ' + str(ov_index))
        elif grid_index >= 0 and tile_index >= 0:
            grid_label = grid_manager.get_grid_label(grid_index)
            self.label_moveTarget.setText(
                f'{grid_label} Tile: {tile_index}' % (grid_index, tile_index))

    def start_move(self):
        self.error = False
        self.pushButton_move.setText('Busy... please wait.')
        self.pushButton_move.setEnabled(False)
        utils.run_log_thread(self.move_and_wait)

    def move_and_wait(self):
        # Load target coordinates
        if self.ov_index >= 0:
            stage_x, stage_y = self.ovm[self.ov_index].centre_sx_sy
        elif self.tile_index >= 0:
            stage_x, stage_y = self.gm[self.grid_index][self.tile_index].sx_sy
        # Now move the stage
        self.stage.move_to_xy((stage_x, stage_y))
        if self.stage.error_state != Error.none:
            self.error = True
            self.stage.reset_error_state()
        # Signal that move complete
        self.finish_trigger.signal.emit()

    def move_completed(self):
        if self.error:
            QMessageBox.warning(self, 'Error',
                'An error was detected during the move. '
                'Please try again.',
                QMessageBox.Ok)
        else:
            QMessageBox.information(self, 'Move complete',
                'The stage has been moved to the selected position. '
                'The Viewport will be updated after pressing OK.',
                QMessageBox.Ok)
            super().accept()
        # Enable button again
        self.pushButton_move.setText('Move again')
        self.pushButton_move.setEnabled(True)
