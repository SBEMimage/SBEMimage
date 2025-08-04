from time import time, sleep
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class GridRotationDlg(QDialog):
    """Change the rotation angle of a selected grid."""

    def __init__(self, selected_grid, gm, viewport_trigger, magc_mode=False):
        self.selected_grid = selected_grid
        self.gm = gm
        self.viewport_trigger = viewport_trigger
        self.magc_mode = magc_mode
        self.rotation_in_progress = False
        self.gm[self.selected_grid].auto_update_tile_positions = False
        super().__init__()
        loadUi('gui/change_grid_rotation_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.label_description.setText(
            f'Rotation of selected grid {self.selected_grid} in degrees:')

        # Keep current angle and origin to enable undo option
        self.previous_angle = self.gm[selected_grid].rotation
        self.previous_origin_sx_sy = self.gm[selected_grid].origin_sx_sy
        # Set initial values:
        self.doubleSpinBox_angle.setValue(self.previous_angle)
        # Slider value 0..719 (twice the angle in degrees) for 0.5 degree steps
        self.horizontalSlider_angle.setValue(
            self.doubleSpinBox_angle.value() * 2)

        self.horizontalSlider_angle.valueChanged.connect(self.update_spinbox)
        self.doubleSpinBox_angle.valueChanged.connect(self.update_slider)

    def keyPressEvent(self, event):
        # Catch KeyPressEvent when user presses Enter (otherwise dialog would exit.)
        if event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
            event.accept()

    def update_spinbox(self):
        self.doubleSpinBox_angle.blockSignals(True)
        self.doubleSpinBox_angle.setValue(
            self.horizontalSlider_angle.value() / 2)
        self.doubleSpinBox_angle.blockSignals(False)
        self.update_grid()

    def update_slider(self):
        self.horizontalSlider_angle.blockSignals(True)
        self.horizontalSlider_angle.setValue(
            self.doubleSpinBox_angle.value() * 2)
        self.horizontalSlider_angle.blockSignals(False)
        self.update_grid()

    def update_grid(self):
        """Apply the new rotation angle and redraw the viewport."""
        self.time_of_last_rotation = time()
        if not self.rotation_in_progress:
            # Start thread to ensure viewport is drawn with labels and previews
            # after rotation completed.
            self.rotation_in_progress = True
            utils.run_log_thread(self.update_viewport_with_delay)
        if self.radioButton_pivotCentre.isChecked():
            # Get current centre of grid:
            centre_dx, centre_dy = self.gm[self.selected_grid].centre_dx_dy
            # Set new angle
            self.gm[self.selected_grid].rotation = self.doubleSpinBox_angle.value()
            self.gm[self.selected_grid].rotate_around_grid_centre(centre_dx, centre_dy)
        else:
            self.gm[self.selected_grid].rotation = self.doubleSpinBox_angle.value()
        # Update tile positions:
        self.gm[self.selected_grid].update_tile_positions()
        # Emit signal to redraw:
        self.viewport_trigger.transmit('DRAW VP NO LABELS')

    def draw_with_labels(self):
        self.viewport_trigger.transmit('DRAW VP')

    def update_viewport_with_delay(self):
        """Redraw the viewport without suppressing labels/previews after at
        least 0.3 seconds have passed since last update of the rotation angle."""
        finish_trigger = utils.Trigger()
        finish_trigger.signal.connect(self.draw_with_labels)
        current_time = self.time_of_last_rotation
        while (current_time - self.time_of_last_rotation < 0.3):
            sleep(0.1)
            current_time += 0.1
        self.rotation_in_progress = False
        finish_trigger.signal.emit()

    def reject(self):
        # Revert to previous angle and origin:
        self.gm[self.selected_grid].rotation = self.previous_angle
        self.gm[self.selected_grid].origin_sx_sy = self.previous_origin_sx_sy
        self.viewport_trigger.transmit('DRAW VP')
        super().reject()

    def accept(self):
        # Calculate new grid map with new rotation angle
        self.gm[self.selected_grid].update_tile_positions()
        if self.magc_mode:
            self.gm.array_write()
        # Restore default behaviour for updating tile positions
        self.gm[self.selected_grid].auto_update_tile_positions = True
        super().accept()
