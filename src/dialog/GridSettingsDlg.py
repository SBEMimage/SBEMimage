from qtpy.QtCore import Qt
from qtpy.QtGui import QPixmap, QColor, QIcon
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import constants
import utils
from dialog.FocusGradientSettingsDlg import FocusGradientSettingsDlg


class GridSettingsDlg(QDialog):
    """Dialog for changing grid settings and for adding/deleting grids."""

    def __init__(self, grid_manager, sem, selected_grid, main_controls_trigger,
                 magc_mode=False):
        super().__init__()
        self.gm = grid_manager
        self.sem = sem
        self.current_grid = selected_grid
        self.main_controls_trigger = main_controls_trigger
        self.magc_mode = magc_mode
        loadUi('gui/grid_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        # Set up grid selector:
        self.comboBox_gridSelector.addItems(self.gm.grid_selector_list())
        self.comboBox_gridSelector.setCurrentIndex(self.current_grid)
        self.comboBox_gridSelector.currentIndexChanged.connect(
            self.change_grid)
        # Set up colour selector:
        for i in range(len(constants.COLOUR_SELECTOR)):
            rgb = constants.COLOUR_SELECTOR[i]
            colour_icon = QPixmap(20, 10)
            colour_icon.fill(QColor(*rgb))
            self.comboBox_colourSelector.addItem(QIcon(colour_icon), '')
        if self.gm[self.current_grid].active:
            self.radioButton_active.setChecked(True)
        else:
            self.radioButton_inactive.setChecked(True)
        self.radioButton_active.toggled.connect(self.update_active_status)
        self.update_active_status()
        store_res_list = [
            f'{res[0]} × {res[1]}' for res in self.sem.STORE_RES]
        self.comboBox_tileSize.addItems(store_res_list)
        self.comboBox_tileSize.currentIndexChanged.connect(
            self.show_frame_size_and_dose)
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        self.comboBox_dwellTime.currentIndexChanged.connect(
            self.show_frame_size_and_dose)
        self.doubleSpinBox_pixelSize.valueChanged.connect(
            self.show_frame_size_and_dose)
        self.comboBox_bitDepth.addItems(['8 bit', '16 bit'])
        # Focus gradient feature, disabled for TESCAN SEMs
        self.toolButton_focusGradient.clicked.connect(
            self.open_focus_gradient_dlg)
        if sem.device_name.startswith("TESCAN"):
            self.checkBox_focusGradient.setEnabled(False)
            self.toolButton_focusGradient.setEnabled(False)
        # Button to load current SEM imaging parameters.
        # For now, only enabled for ZEISS SEMs.
        self.pushButton_getFromSEM.clicked.connect(self.get_settings_from_sem)
        self.pushButton_getFromSEM.setEnabled(
            self.sem.device_name.startswith("ZEISS"))
        # Buttons to reset tile previews and wd/stig parameters
        self.pushButton_resetTilePreviews.clicked.connect(
            self.reset_tile_previews)
        self.pushButton_resetFocusParams.clicked.connect(
            self.reset_wd_stig_params)
        # Save, add, and delete buttons
        self.pushButton_save.clicked.connect(self.save_current_settings)
        self.pushButton_addGrid.clicked.connect(self.add_grid)
        self.pushButton_deleteGrid.clicked.connect(self.delete_grid)
        self.update_buttons()
        self.show_current_settings()
        self.show_frame_size_and_dose()
        if 'multisem' in self.sem.device_name.lower():
            # in multisem ROIs are used instead of grids
            # the smallest possible grid is kept for compatibility
            self.spinBox_rows.setEnabled(False)
            self.spinBox_rows.setValue(1)
            self.spinBox_cols.setEnabled(False)
            self.spinBox_cols.setValue(1)
            self.comboBox_tileSize.setEnabled(False)
            self.comboBox_tileSize.setCurrentIndex(0)
            self.spinBox_shift.setEnabled(False)

    def update_active_status(self):
        # If current grid is inactive, disable GUI elements
        b = self.radioButton_active.isChecked()
        tescan_sem = self.sem.device_name.startswith("TESCAN")
        self.spinBox_rows.setEnabled(b)
        self.spinBox_cols.setEnabled(b)
        self.spinBox_overlap.setEnabled(b)
        self.spinBox_shift.setEnabled(b)
        self.doubleSpinBox_rotation.setEnabled(b)
        self.comboBox_tileSize.setEnabled(b)
        self.comboBox_dwellTime.setEnabled(b)
        self.doubleSpinBox_pixelSize.setEnabled(b)
        self.checkBox_focusGradient.setEnabled(b and not tescan_sem)
        self.toolButton_focusGradient.setEnabled(b and not tescan_sem)
        self.pushButton_resetFocusParams.setEnabled(b)
        self.spinBox_acqInterval.setEnabled(b)
        self.spinBox_acqIntervalOffset.setEnabled(b)

    def get_settings_from_sem(self):
        """Load current SEM settings for frame size, pixel size, and
        dwell time, and set the spin box and the combo boxes to these values.
        """
        current_frame_size_selector = self.sem.get_frame_size_selector()
        current_pixel_size = self.sem.get_pixel_size()
        current_scan_rate = self.sem.get_scan_rate()
        self.comboBox_tileSize.setCurrentIndex(current_frame_size_selector)
        self.comboBox_dwellTime.setCurrentIndex(current_scan_rate)
        self.doubleSpinBox_pixelSize.setValue(current_pixel_size)

    def show_current_settings(self):
        grid = self.gm[self.current_grid]
        self.comboBox_colourSelector.setCurrentIndex(
            grid.display_colour)
        self.checkBox_focusGradient.setChecked(
            grid.use_wd_gradient)
        self.spinBox_rows.setValue(grid.number_rows())
        self.spinBox_cols.setValue(grid.number_cols())
        self.spinBox_overlap.setValue(int(grid.overlap))
        self.doubleSpinBox_rotation.setValue(
            grid.rotation)
        self.spinBox_shift.setValue(grid.row_shift)
        self.doubleSpinBox_pixelSize.setValue(
            grid.pixel_size)
        self.comboBox_tileSize.setCurrentIndex(
            grid.frame_size_selector)
        self.comboBox_dwellTime.setCurrentIndex(
            grid.dwell_time_selector)
        self.comboBox_bitDepth.setCurrentIndex(
            grid.bit_depth_selector)
        self.spinBox_acqInterval.setValue(
            grid.acq_interval)
        self.spinBox_acqIntervalOffset.setValue(
            grid.acq_interval_offset)

    def show_frame_size_and_dose(self):
        """Calculate and display the tile size and the dose for the current
        settings. Updated in real-time as user changes dwell time, frame
        resolution and pixel size.
        """
        frame_size_selector = self.comboBox_tileSize.currentIndex()
        pixel_size = self.doubleSpinBox_pixelSize.value()
        width = self.sem.STORE_RES[frame_size_selector][0] * pixel_size / 1000
        height = self.sem.STORE_RES[frame_size_selector][1] * pixel_size / 1000
        self.label_tileSize.setText(f'{width:.1f} × {height:.1f}')
        current = self.sem.target_beam_current
        dwell_time = float(self.comboBox_dwellTime.currentText())
        pixel_size = self.doubleSpinBox_pixelSize.value()
        # Show electron dose in electrons per square nanometre.
        self.label_dose.setText('{0:.1f}'.format(
            utils.calculate_electron_dose(current, dwell_time, pixel_size)))

    def change_grid(self):
        self.current_grid = self.comboBox_gridSelector.currentIndex()
        if self.gm[self.current_grid].active:
            self.radioButton_active.setChecked(True)
        else:
            self.radioButton_inactive.setChecked(True)
        self.update_active_status()
        self.update_buttons()
        self.show_current_settings()
        self.show_frame_size_and_dose()

    def update_buttons(self):
        """Update labels on buttons and disable/enable delete button
        depending on which grid is selected. Grid 0 cannot be deleted.
        Only the last grid can be deleted. Reason: preserve identities of
        grids and tiles within grids.
        """
        grid_label = self.gm.get_grid_label(self.current_grid)
        if self.current_grid == 0:
            self.pushButton_deleteGrid.setEnabled(False)
        else:
            self.pushButton_deleteGrid.setEnabled(
                self.current_grid == (self.gm.number_grids - 1))
        self.pushButton_save.setText(
            f'Save settings for {grid_label}')
        self.pushButton_deleteGrid.setText(
            f'Delete {grid_label}')

    def add_grid(self):
        active = self.radioButton_active.isChecked()
        frame_size_selector = self.comboBox_tileSize.currentIndex()
        frame_size = self.comboBox_tileSize.currentText()
        input_overlap = self.spinBox_overlap.value()
        pixel_size = self.doubleSpinBox_pixelSize.value()
        dwell_time_selector = self.comboBox_dwellTime.currentIndex()
        dwell_time = self.comboBox_dwellTime.currentText()
        bit_depth_selector = self.comboBox_bitDepth.currentIndex()
        rotation = self.doubleSpinBox_rotation.value()
        input_shift = self.spinBox_shift.value()
        acq_interval = self.spinBox_acqInterval.value()
        acq_interval_offset = self.spinBox_acqIntervalOffset.value()
        size = [self.spinBox_rows.value(), self.spinBox_cols.value()]
        self.gm.add_new_grid(active=active,
                             frame_size=frame_size, frame_size_selector=frame_size_selector,
                             overlap=input_overlap, pixel_size=pixel_size,
                             dwell_time=dwell_time, dwell_time_selector=dwell_time_selector,
                             bit_depth_selector=bit_depth_selector,
                             rotation=rotation, row_shift=input_shift,
                             acq_interval=acq_interval, acq_interval_offset=acq_interval_offset,
                             size=size)
        self.current_grid = self.gm.number_grids - 1
        # Update grid selector:
        self.comboBox_gridSelector.blockSignals(True)
        self.comboBox_gridSelector.clear()
        self.comboBox_gridSelector.addItems(self.gm.grid_selector_list())
        self.comboBox_gridSelector.setCurrentIndex(self.current_grid)
        self.comboBox_gridSelector.blockSignals(False)
        self.change_grid()
        self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def delete_grid(self):
        user_reply = QMessageBox.question(
                        self, 'Delete grid',
                        'This will delete grid %d.\n\n'
                        'Do you wish to proceed?' % self.current_grid,
                        QMessageBox.Ok | QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            self.gm.delete_grid()
            self.current_grid = self.gm.number_grids - 1
            # Update grid selector:
            self.comboBox_gridSelector.blockSignals(True)
            self.comboBox_gridSelector.clear()
            self.comboBox_gridSelector.addItems(self.gm.grid_selector_list())
            self.comboBox_gridSelector.setCurrentIndex(self.current_grid)
            self.comboBox_gridSelector.blockSignals(False)
            self.change_grid()
            self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def reset_tile_previews(self):
        user_reply = QMessageBox.question(
            self, 'Reset tile previews',
            f'This will clear all tile preview images in the Viewport for '
            f'{self.gm.get_grid_label(self.current_grid)}',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            self.gm[self.current_grid].clear_all_tile_previews()
            self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def reset_wd_stig_params(self):
        user_reply = QMessageBox.question(
            self, 'Reset focus/astigmatism parameters',
            f'This will reset the focus and astigmatism parameters for '
            f'all tiles in grid {self.current_grid}.\n'
            f'Proceed?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_reply == QMessageBox.Ok:
            self.gm[self.current_grid].set_wd_for_all_tiles(0)
            self.gm[self.current_grid].set_stig_xy_for_all_tiles([0, 0])
            self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def save_current_settings(self):
        error_msg = ''
        # Update tile positions only once after updating all grid attributes
        self.gm[self.current_grid].auto_update_tile_positions = False

        if self.magc_mode:
            # Preserve centre coordinates of MagC grids
            prev_grid_centre = self.gm[self.current_grid].centre_sx_sy

        self.gm[self.current_grid].active = self.radioButton_active.isChecked()
        self.gm[self.current_grid].size = [self.spinBox_rows.value(),
                                           self.spinBox_cols.value()]
        self.gm[self.current_grid].frame_size_selector = (
            self.comboBox_tileSize.currentIndex())
        tile_width_p = self.gm[self.current_grid].tile_width_p()
        input_overlap = self.spinBox_overlap.value()
        input_shift = self.spinBox_shift.value()
        if -0.3 * tile_width_p <= input_overlap < 0.3 * tile_width_p:
            self.gm[self.current_grid].overlap = input_overlap
        else:
            error_msg = ('Overlap outside of allowed '
                         'range (-30% .. 30% frame width).')
        if 0 <= input_shift <= tile_width_p:
            self.gm[self.current_grid].row_shift = input_shift
        else:
            error_msg = ('Row shift outside of allowed '
                         'range (0 .. frame width).')
        self.gm[self.current_grid].display_colour = (
            self.comboBox_colourSelector.currentIndex())
        self.gm[self.current_grid].use_wd_gradient = (
            self.checkBox_focusGradient.isChecked())
        if self.checkBox_focusGradient.isChecked():
            self.gm[self.current_grid].calculate_wd_gradient()
        # Acquisition parameters:
        self.gm[self.current_grid].pixel_size = (
            self.doubleSpinBox_pixelSize.value())
        self.gm[self.current_grid].dwell_time_selector = (
            self.comboBox_dwellTime.currentIndex())
        self.gm[self.current_grid].bit_depth_selector = (
            self.comboBox_bitDepth.currentIndex())
        self.gm[self.current_grid].acq_interval = (
            self.spinBox_acqInterval.value())
        self.gm[self.current_grid].acq_interval_offset = (
            self.spinBox_acqIntervalOffset.value())
        # Recalculate tile positions after all parameter updates, except rotation (see below)
        self.gm[self.current_grid].update_tile_positions()

        # Now apply rotation if the rotation angle was changed.
        new_rotation = self.doubleSpinBox_rotation.value()
        if new_rotation != self.gm[self.current_grid].rotation:
          # Get current centre of grid
          centre_dx, centre_dy = self.gm[self.current_grid].centre_dx_dy
          # Set new angle, perform rotation to get new grid origin, and update tile positions
          self.gm[self.current_grid].rotation = new_rotation
          self.gm[self.current_grid].rotate_around_grid_centre(centre_dx, centre_dy)
          self.gm[self.current_grid].update_tile_positions()

        self.gm[self.current_grid].auto_update_tile_positions = True

        if self.magc_mode:
            self.gm[self.current_grid].centre_sx_sy = prev_grid_centre
            self.gm.array_write()
        # Restore default behaviour for updating tile positions
        if error_msg:
            QMessageBox.warning(self, 'Error', error_msg, QMessageBox.Ok)
        else:
            self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def open_focus_gradient_dlg(self):
        sub_dialog = FocusGradientSettingsDlg(self.gm, self.current_grid)
        sub_dialog.exec()
