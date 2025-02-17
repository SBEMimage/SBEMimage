from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QDialogButtonBox
from qtpy.uic import loadUi

import utils


class ModifyImageDlg(QDialog):
    """Modify an imported image (size, rotation, transparency)"""

    def __init__(self, selected_image, grid_manager,
                 viewport_trigger):
        self.viewport_trigger = viewport_trigger
        self.gm = grid_manager
        self.selected_image = selected_image
        super().__init__()
        loadUi('gui/modify_image_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())

        self.lineEdit_selectedImage.setText(
            self.selected_image.description)
        pos_x, pos_y = self.selected_image.centre_sx_sy
        self.doubleSpinBox_posX.setValue(pos_x)
        self.doubleSpinBox_posY.setValue(pos_y)
        self.doubleSpinBox_pixelSize.setValue(
            self.selected_image.pixel_size)
        self.doubleSpinBox_rotation.setValue(
            self.selected_image.rotation)
        self.checkBox_flipped.setChecked(
            self.selected_image.flipped)
        self.doubleSpinBox_transparency.setValue(
            self.selected_image.transparency)
        # Use "Apply" button to show changes in viewport
        apply_button = self.buttonBox.button(QDialogButtonBox.Apply)
        cancel_button = self.buttonBox.button(QDialogButtonBox.Cancel)
        cancel_button.setAutoDefault(False)
        cancel_button.setDefault(False)
        apply_button.setDefault(True)
        apply_button.setAutoDefault(True)
        apply_button.clicked.connect(self.apply_changes)

    def apply_changes(self):
        """Apply the current settings and redraw the image in the viewport."""
        imported = self.selected_image
        imported.centre_sx_sy = [
            self.doubleSpinBox_posX.value(),
            self.doubleSpinBox_posY.value()]
        imported.pixel_size = (
            self.doubleSpinBox_pixelSize.value())
        imported.rotation = (
            self.doubleSpinBox_rotation.value())
        imported.flipped = (
            self.checkBox_flipped.isChecked())
        imported.transparency = (
            self.doubleSpinBox_transparency.value())
        imported.update_image()
        if imported.is_array:
            self.gm.array_update_data_image_properties(imported)
        # Emit signals to redraw Viewport:
        self.viewport_trigger.transmit('DRAW VP')
