# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module controls the viewport window, which consists of three tabs:
    - the viewport (mv)  [formerly called Mosaic Viewer, therefore 'mv']
    - the slice viewer (sv),
    - the reslice/statistics tab (m)  ['monitoring']
"""

import os
import datetime
import numpy as np
from PIL import Image
from math import log, sqrt
from statistics import mean

from PyQt5.uic import loadUi
from PyQt5.QtWidgets import QWidget, QApplication, QMessageBox, QMenu
from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont, QIcon, QPen, \
                        QBrush, QTransform
from PyQt5.QtCore import Qt, QObject, QRect, QPoint, QSize

import utils
from dlg_windows import AdaptiveFocusSelectionDlg


class Viewport(QWidget):

    # Fixed window/viewer parameters:
    WINDOW_MARGIN_X = 20
    WINDOW_MARGIN_Y = 40
    VIEWER_WIDTH = 1000
    VIEWER_HEIGHT = 800
    VIEWER_OV_ZOOM_F1 = 1.0
    VIEWER_OV_ZOOM_F2 = 1.03
    VIEWER_TILE_ZOOM_F1 = 5.0
    VIEWER_TILE_ZOOM_F2 = 1.04

    def __init__(self, config, sem, stage,
                 ov_manager, grid_manager, coordinate_system,
                 autofocus, trigger, queue):
        super().__init__()
        self.cfg = config
        self.sem = sem
        self.stage = stage
        self.gm = grid_manager
        self.ovm = ov_manager
        self.cs = coordinate_system
        self.af = autofocus
        self.trigger = trigger
        self.queue = queue
        # Set limits for viewport panning:
        self.VC_MIN_X, self.VC_MAX_X, self.VC_MIN_Y, self.VC_MAX_Y = (
            self.cs.get_dx_dy_range())
        # Set zoom parameters depending on which stage is selected:
        if self.cfg['sys']['use_microtome'] == 'True':
            self.VIEWER_ZOOM_F1 = 0.2
            self.VIEWER_ZOOM_F2 = 1.05
        else:
            self.VIEWER_ZOOM_F1 = 0.0055
            self.VIEWER_ZOOM_F2 = 1.085

        # Shared control variables:
        self.acq_in_progress = False
        self.viewport_active = True
        self.number_grids = self.gm.get_number_grids()
        self.number_ov = self.ovm.get_number_ov()
        self.number_imported = self.ovm.get_number_imported()
        # for mouse operations (dragging, measuring):
        self.drag_origin = (0, 0)
        self.fov_drag_active = False
        self.tile_paint_mode_active = False
        self.measure_p1 = (None, None)
        self.measure_p2 = (None, None)
        self.measure_complete = False
        self.stub_ov_centre = [None, None]
        self.help_panel_visible = False

        self.load_gui()
        # Initialize viewport tabs:
        self.mv_initialize()  # Mosaic viewer
        self.sv_initialize()  # Slice viewer
        self.m_initialize()   # Monitoring tab
        self.setMouseTracking(True)

    def load_gui(self):
        loadUi('..\\gui\\viewport.ui', self)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setWindowTitle('SBEMimage - Viewport')
        # Display current settings:
        self.setFixedSize(self.size())
        self.move(20, 20)
        # Deactivate buttons for imaging if in simulation mode:
        if self.cfg['sys']['simulation_mode'] == 'True':
            self.pushButton_refreshOVs.setEnabled(False)
            self.pushButton_acquireStubOV.setEnabled(False)

    def deactivate(self):
        self.viewport_active = False

    def restrict_gui(self, b):
        b ^= True
        self.acq_in_progress ^= True
        self.pushButton_refreshOVs.setEnabled(b)
        self.pushButton_acquireStubOV.setEnabled(b)
        if not b:
            self.radioButton_fromStack.setChecked(not b)
        self.radioButton_fromSEM.setEnabled(b)

    def update_grids(self):
        self.number_grids = self.gm.get_number_grids()
        self.mv_current_grid = -1
        self.cfg['viewport']['mv_current_grid'] = '-1'
        if self.sv_current_grid >= self.number_grids:
            self.sv_current_grid = self.number_grids - 1
            self.cfg['viewport']['sv_current_grid'] = str(self.sv_current_grid)
            self.sv_current_tile = -1
            self.cfg['viewport']['sv_current_tile'] = '-1'
        if self.m_current_grid >= self.number_grids:
            self.m_current_grid = self.number_grids - 1
            self.cfg['viewport']['m_current_grid'] = str(self.m_current_grid)
            self.m_current_tile = -1
            self.cfg['viewport']['m_current_tile'] = '-1'
        self.mv_update_grid_selector(self.mv_current_grid)
        self.sv_update_grid_selector(self.sv_current_grid)
        self.sv_update_tile_selector(self.sv_current_tile)
        self.m_update_grid_selector(self.m_current_grid)
        self.m_update_tile_selector(self.m_current_tile)

    def update_ov(self):
        self.number_ov = self.ovm.get_number_ov()
        self.mv_current_ov = -1
        self.cfg['viewport']['mv_current_ov'] = '-1'
        self.mv_load_all_overviews()
        self.mv_update_ov_selector()
        self.sv_update_ov_selector()
        self.m_update_ov_selector()

    def update_measure_buttons(self):
        if self.mv_measure_active:
            self.pushButton_measureMosaic.setIcon(
                QIcon('..\\img\\measure-active.png'))
            self.pushButton_measureMosaic.setIconSize(QSize(16, 16))
        else:
            self.pushButton_measureMosaic.setIcon(
                QIcon('..\\img\\measure.png'))
            self.pushButton_measureMosaic.setIconSize(QSize(16, 16))
        if self.sv_measure_active:
            self.pushButton_measureSlice.setIcon(
                QIcon('..\\img\\measure-active.png'))
            self.pushButton_measureSlice.setIconSize(QSize(16, 16))
        else:
            self.pushButton_measureSlice.setIcon(
                QIcon('..\\img\\measure.png'))
            self.pushButton_measureSlice.setIconSize(QSize(16, 16))

    def grab_viewport_screenshot(self, save_path_filename):
        viewport_screenshot = self.grab()
        viewport_screenshot.save(save_path_filename)

    def add_to_viewport_log(self, text):
        timestamp = str(datetime.datetime.now())
        self.textarea_incidentLog.appendPlainText(
            timestamp[:22] + ' | Slice ' + text)

    def transmit_cmd(self, cmd):
        """ Transmit command to the main window thread. """
        self.queue.put(cmd)
        self.trigger.s.emit()

    def add_to_main_log(self, msg):
        """ Add entry to the log in the main window """
        msg = utils.format_log_entry(msg)
        # Send entry to main window via queue and trigger:
        self.queue.put(msg)
        self.trigger.s.emit()

    def closeEvent(self, event):
        if self.viewport_active:
            QMessageBox.information(self, 'Closing Viewport',
                'Close viewport window by closing main window of the '
                'application.', QMessageBox.Ok)
            event.ignore()
        else:
            event.accept()

# ========================= Below: mouse functions ============================

    def setMouseTracking(self, flag):
        """Recursively activate or deactive mouse tracking in a widget"""
        def recursive_set(parent):
            for child in parent.findChildren(QObject):
                try:
                    child.setMouseTracking(flag)
                except:
                    pass
                recursive_set(child)
        QWidget.setMouseTracking(self, flag)
        recursive_set(self)

    def mousePressEvent(self, event):
        p = event.pos()
        px, py = p.x() - self.WINDOW_MARGIN_X, p.y() - self.WINDOW_MARGIN_Y
        mouse_pos_within_viewer = (
            px in range(self.VIEWER_WIDTH) and py in range(self.VIEWER_HEIGHT))
        mouse_pos_within_plot_area = (
            px in range(445, 940) and py in range(22, 850))

        if ((event.button() == Qt.LeftButton)
            and (self.tabWidget.currentIndex() < 2)
            and mouse_pos_within_viewer):

            self.selected_grid, self.selected_tile = \
                self.mv_get_grid_tile_mouse_selection(px, py)
            self.selected_ov = self.mv_get_ov_mouse_selection(px, py)
            self.selected_imported = (
                self.mv_get_imported_mouse_selection(px, py))

            # Shift pressed in first tab? Toggle tile selection:
            if ((self.tabWidget.currentIndex() == 0)
               and (QApplication.keyboardModifiers() == Qt.ShiftModifier)):
                if (self.mv_current_grid >= -2
                   and self.selected_grid is not None
                   and self.selected_tile is not None):
                    if self.acq_in_progress:
                        user_reply = QMessageBox.question(self,
                            'Confirm tile selection',
                            'Stack acquisition in progress! Please confirm '
                            'that you want to select/deselect this tile. The '
                            'selection will become effective after imaging of '
                            'the current grid is completed.',
                            QMessageBox.Ok | QMessageBox.Cancel)
                        if user_reply == QMessageBox.Ok:
                            msg = self.gm.toggle_tile(self.selected_grid,
                                                      self.selected_tile)
                            if self.af.get_tracking_mode() == 1:
                                self.af.toggle_ref_tile(self.selected_grid,
                                                        self.selected_tile)
                            self.add_to_main_log(msg)
                            self.mv_update_after_tile_selection()
                            # Make sure folder exists:
                            self.transmit_cmd('ADD TILE FOLDER')
                    else:
                        # If no acquisition in progress,
                        # first toggle current tile:
                        self.gm.toggle_tile(self.selected_grid,
                                            self.selected_tile)
                        if self.af.get_tracking_mode() == 1:
                            self.af.toggle_ref_tile(self.selected_grid,
                                                    self.selected_tile)
                        self.mv_draw()
                        # Then enter paint mode until mouse button released.
                        self.tile_paint_mode_active = True

            # Check if ctrl key is pressed -> Move OV:
            elif ((self.tabWidget.currentIndex() == 0)
                and (QApplication.keyboardModifiers() == Qt.ControlModifier)
                and self.mv_current_ov >= -2
                and not self.acq_in_progress):
                if self.selected_ov is not None and self.selected_ov >= 0:
                    self.ov_drag_active = True
                    self.drag_origin = (px, py)
                    self.stage_pos_backup = self.cs.get_ov_centre_s(
                        self.selected_ov)

            # Check if alt key is pressed -> Move grid:
            elif ((self.tabWidget.currentIndex() == 0)
                and (QApplication.keyboardModifiers() == Qt.AltModifier)
                and self.mv_current_grid >= -2
                and not self.acq_in_progress):
                if self.selected_grid is not None and self.selected_grid >= 0:
                    self.grid_drag_active = True
                    self.drag_origin = (px, py)
                    # Save coordinates in case user wants to undo:
                    self.stage_pos_backup = self.cs.get_grid_origin_s(
                        self.selected_grid)

            # Check if ctrl+alt keys are pressed -> Move imported image:
            elif ((self.tabWidget.currentIndex() == 0)
                and (QApplication.keyboardModifiers()
                    == (Qt.ControlModifier | Qt.AltModifier))):
                if self.selected_imported is not None:
                    self.imported_img_drag_active = True
                    self.drag_origin = (px, py)
                    # Save coordinates in case user wants to undo:
                    self.stage_pos_backup = self.cs.get_imported_img_centre_s(
                        self.selected_imported)

            # No key pressed? -> Pan:
            elif (QApplication.keyboardModifiers() == Qt.NoModifier):
                # Move the viewport's FOV
                self.fov_drag_active = True
                # For now, disable showing saturated pixels (too slow)
                if self.show_saturated_pixels:
                    self.checkBox_showSaturated.setChecked(False)
                    self.show_saturated_pixels = False
                    self.cfg['viewport']['show_saturated_pixels'] = 'False'
                self.drag_origin = (p.x() - self.WINDOW_MARGIN_X,
                                    p.y() - self.WINDOW_MARGIN_Y)
        # Now right mouse button for context menus and measuring:
        if ((event.button() == Qt.RightButton)
           and (self.tabWidget.currentIndex() < 2)
           and mouse_pos_within_viewer):

            if self.tabWidget.currentIndex() == 0:
                if self.mv_measure_active:
                    self.mv_start_measure(px - 500, py - 400)
                else:
                    self.mv_show_context_menu(p)

            elif self.tabWidget.currentIndex() == 1:
                if self.sv_measure_active:
                    self.sv_start_measure(px, py)
                else:
                    self.sv_show_context_menu(p)

        # Left mouse click in statistics tab:
        if ((event.button() == Qt.LeftButton)
            and (self.tabWidget.currentIndex() == 2)
            and mouse_pos_within_plot_area
            and self.m_tab_populated):
            self.m_selected_plot_slice = utils.fit_in_range(
                int((px - 445)/3), 0, 164)
            self.m_draw_plots()
            if self.m_selected_slice_number is not None:
                self.m_draw_histogram()
                self.m_draw_reslice()

    def mouseDoubleClickEvent(self, event):
        p = event.pos()
        px, py = p.x() - self.WINDOW_MARGIN_X, p.y() - self.WINDOW_MARGIN_Y
        if px in range(self.VIEWER_WIDTH) and py in range(self.VIEWER_HEIGHT):
            if self.tabWidget.currentIndex() == 0:
                self.mv_mouse_zoom(px, py, 2)
            elif self.tabWidget.currentIndex() == 1:
                # Disable native resolution:
                self.cfg['viewport']['show_native_resolution'] = 'False'
                self.horizontalSlider_SV.setEnabled(True)
                self.checkBox_setNativeRes.setChecked(False)
                # Zoom in:
                self.sv_mouse_zoom(px, py, 2)

    def mouseMoveEvent(self, event):
        p = event.pos()
        px, py = p.x() - self.WINDOW_MARGIN_X, p.y() - self.WINDOW_MARGIN_Y
        # Show current stage and SEM coordinates at mouse position
        mouse_pos_within_viewer = (
            px in range(self.VIEWER_WIDTH) and py in range(self.VIEWER_HEIGHT))
        if ((self.tabWidget.currentIndex() == 0)
                and mouse_pos_within_viewer):
            sx, sy = self.mv_get_stage_coordinates_from_mouse_position(px, py)
            dx, dy = self.cs.convert_to_d((sx, sy))
            self.label_mousePos.setText(
                'Stage: {0:.1f}, '.format(sx)
                + '{0:.1f}; '.format(sy)
                + 'SEM: {0:.1f}, '.format(dx)
                + '{0:.1f}'.format(dy))
        else:
            self.label_mousePos.setText('-')

        # Move tiling or FOV:
        if self.grid_drag_active:
            # Change cursor appearence:
            self.setCursor(Qt.SizeAllCursor)
            drag_vector = (px - self.drag_origin[0],
                           py - self.drag_origin[1])
            # Update drag origin
            self.drag_origin = (px, py)
            self.mv_reposition_grid(drag_vector)
            self.mv_draw()
        elif self.ov_drag_active:
            self.setCursor(Qt.SizeAllCursor)
            drag_vector = (px - self.drag_origin[0],
                           py - self.drag_origin[1])
            self.drag_origin = (px, py)
            self.mv_reposition_ov(drag_vector)
            self.mv_draw()
        elif self.imported_img_drag_active:
            self.setCursor(Qt.SizeAllCursor)
            drag_vector = (px - self.drag_origin[0],
                           py - self.drag_origin[1])
            self.drag_origin = (px, py)
            self.mv_reposition_imported_img(drag_vector)
            self.mv_draw()
        elif self.fov_drag_active:
            self.setCursor(Qt.SizeAllCursor)
            drag_vector = (self.drag_origin[0] - px, self.drag_origin[1] - py)
            self.drag_origin = (px, py)
            if self.tabWidget.currentIndex() == 0:
                self.mv_shift_fov(drag_vector)
                self.mv_draw()
            if self.tabWidget.currentIndex() == 1:
                self.sv_shift_fov(drag_vector)
                self.sv_draw()
        elif self.tile_paint_mode_active:
            # Toggle tiles in "painting" mode.
            prev_selected_grid = self.selected_grid
            prev_selected_tile = self.selected_tile
            self.selected_grid, self.selected_tile = \
                self.mv_get_grid_tile_mouse_selection(px, py)
            # If mouse has moved to a new tile, toggle it:
            if (self.selected_grid is not None
                and self.selected_tile is not None):
                if ((self.selected_grid == prev_selected_grid
                     and self.selected_tile != prev_selected_tile)
                    or self.selected_grid != prev_selected_grid):
                        self.gm.toggle_tile(self.selected_grid,
                                            self.selected_tile)
                        if self.af.get_tracking_mode() == 1:
                            self.af.toggle_ref_tile(self.selected_grid,
                                                    self.selected_tile)
                        self.mv_draw()
            else:
                # Disable paint mode when mouse moved beyond grid edge.
                self.tile_paint_mode_active = False

        elif ((self.tabWidget.currentIndex() == 0)
            and mouse_pos_within_viewer
            and self.mv_measure_active):
                # Change cursor appearence:
                self.setCursor(Qt.CrossCursor)
        elif ((self.tabWidget.currentIndex() == 1)
            and mouse_pos_within_viewer
            and self.sv_measure_active):
                self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if not self.mv_measure_active:
            self.setCursor(Qt.ArrowCursor)
        if (event.button() == Qt.LeftButton):
            self.fov_drag_active = False
            if self.grid_drag_active:
                self.grid_drag_active = False
                user_reply = QMessageBox.question(
                    self, 'Repositioning tile grid',
                    'You have repositioned the selected tile grid. Please '
                    'confirm the new position. Click "Cancel" to undo.',
                    QMessageBox.Ok | QMessageBox.Cancel)
                if user_reply == QMessageBox.Cancel:
                    # Restore origin coordinates:
                    self.cs.set_grid_origin_s(
                        self.selected_grid, self.stage_pos_backup)
            if self.ov_drag_active:
                self.ov_drag_active = False
                user_reply = QMessageBox.question(
                    self, 'Repositioning overview',
                    'You have repositioned the selected overview. Please '
                    'confirm the new position. Click "Cancel" to undo.',
                    QMessageBox.Ok | QMessageBox.Cancel)
                if user_reply == QMessageBox.Cancel:
                    # Restore origin coordinates:
                    self.cs.set_ov_centre_s(
                        self.selected_ov, self.stage_pos_backup)
                else:
                    # Remove current preview image from file list:
                    self.ovm.update_ov_file_list(self.selected_ov, '')
                    # Show blue transparent ROI:
                    self.ov_img[self.selected_ov].fill(QColor(255, 255, 255, 0))
                    self.mv_qp.begin(self.ov_img[self.selected_ov])
                    self.mv_qp.setPen(QColor(0, 0, 255, 0))
                    self.mv_qp.setBrush(QColor(0, 0, 255, 70))
                    self.mv_qp.drawRect(
                        0, 0,
                        self.ovm.get_ov_width_p(self.selected_ov),
                        self.ovm.get_ov_height_p(self.selected_ov))
                    self.mv_qp.end()
            if self.tile_paint_mode_active:
                self.tile_paint_mode_active = False
                self.mv_update_after_tile_selection()
            if self.imported_img_drag_active:
                self.imported_img_drag_active = False
                user_reply = QMessageBox.question(
                    self, 'Repositioning imported image',
                    'You have repositioned the selected imported image. Please '
                    'confirm the new position. Click "Cancel" to undo.',
                    QMessageBox.Ok | QMessageBox.Cancel)
                if user_reply == QMessageBox.Cancel:
                    # Restore origin coordinates:
                    self.cs.set_imported_img_centre_s(
                        self.selected_imported, self.stage_pos_backup)
            # Update viewport:
            self.ovm.update_all_ov_debris_detections_areas(self.gm)
            self.mv_draw()
            self.transmit_cmd('SHOW CURRENT SETTINGS')

    def wheelEvent(self, event):
        if self.tabWidget.currentIndex() == 1:
            if event.angleDelta().y() > 0:
                self.sv_slice_fwd()
            if event.angleDelta().y() < 0:
                self.sv_slice_bwd()
        if self.tabWidget.currentIndex() == 0:
            p = event.pos()
            px, py = p.x() - self.WINDOW_MARGIN_X, p.y() - self.WINDOW_MARGIN_Y
            mouse_pos_within_viewer = (
                px in range(self.VIEWER_WIDTH) and py in range(self.VIEWER_HEIGHT))
            if mouse_pos_within_viewer:
                if event.angleDelta().y() > 0:
                    self.mv_mouse_zoom(px, py, 1.25)
                if event.angleDelta().y() < 0:
                    self.mv_mouse_zoom(px, py, 0.8)

# ================= Below: Mosaic Viewer (mv) functions =======================

    def mv_initialize(self):
        self.mv_current_grid = int(self.cfg['viewport']['mv_current_grid'])
        self.mv_current_ov = int(self.cfg['viewport']['mv_current_ov'])
        self.mv_tile_preview_mode = int(
            self.cfg['viewport']['mv_tile_preview_mode'])
        self.mv_scale = self.cs.get_mv_scale()
        self.mv_centre_dx_dy = self.cs.get_mv_centre_d()
        self.grid_origin_sx_sy = (None, None)
        self.grid_origin_sx_sy_backup = (None, None)
        # display options:
        self.stub_ov_exists = False
        self.show_stub_ov = self.cfg['viewport']['show_stub_ov'] == 'True'
        self.show_imported = self.cfg['viewport']['show_imported'] == 'True'
        self.show_labels = (
            self.cfg['viewport']['show_labels'] == 'True')
        self.show_axes = self.cfg['viewport']['show_axes'] == 'True'
        self.show_native_res = (
            self.cfg['viewport']['show_native_resolution'] == 'True')
        self.show_saturated_pixels = (
            self.cfg['viewport']['show_saturated_pixels'] == 'True')
        self.show_stage_pos = False
        # Acq indicators:
        self.tile_indicator_on = False
        self.tile_indicator_pos = [None, None]
        self.ov_indicator_on = False
        self.ov_indicator_pos = None

        self.selected_grid = None
        self.selected_tile = None
        self.selected_ov = None
        self.selected_imported = None
        self.grid_drag_active = False
        self.ov_drag_active = False
        self.imported_img_drag_active = False
        self.mv_measure_active = False

        self.mv_load_stage_limits()

        # Canvas:
        self.mv_canvas = QPixmap(self.VIEWER_WIDTH, self.VIEWER_HEIGHT)
        # Help panel:
        self.mv_help_panel_img = QPixmap('..\\img\\help-viewport.png')
        # QPainter:
        self.mv_qp = QPainter()

        # Load overview files into memory:
        self.mv_load_all_overviews()
        self.mv_load_stub_overview()
        self.mv_load_all_imported_images()

        # Buttons:
        self.pushButton_refreshOVs.clicked.connect(self.mv_refresh_overviews)
        self.pushButton_acquireStubOV.clicked.connect(
            self.mv_acquire_stub_overview)
        self.pushButton_measureMosaic.clicked.connect(self.mv_toggle_measure)
        self.pushButton_measureMosaic.setIcon(QIcon('..\\img\\measure.png'))
        self.pushButton_measureMosaic.setIconSize(QSize(16, 16))
        self.pushButton_helpViewport.clicked.connect(self.mv_toggle_help_panel)
        self.pushButton_helpSliceViewer.clicked.connect(
            self.mv_toggle_help_panel)
        # Slider for zoom:
        self.horizontalSlider_MV.valueChanged.connect(self.mv_adjust_scale)
        self.horizontalSlider_MV.setValue(
            log(self.cs.get_mv_scale() / self.VIEWER_ZOOM_F1,
                self.VIEWER_ZOOM_F2))
        # Tile Preview selector:
        self.comboBox_tilePreviewSelectorMV.addItems(
            ['Hide tile previews',
             'Show tile previews',
             'Tile previews, no grid(s)',
             'Tile previews with gaps'])
        self.comboBox_tilePreviewSelectorMV.setCurrentIndex(
            self.mv_tile_preview_mode)
        self.comboBox_tilePreviewSelectorMV.currentIndexChanged.connect(
            self.mv_change_tile_preview_mode)

        # Connect and populate grid/tile/roi comboboxes:
        self.comboBox_gridSelectorMV.currentIndexChanged.connect(
            self.mv_change_grid_selection)
        self.mv_update_grid_selector(self.mv_current_grid)
        self.comboBox_OVSelectorMV.currentIndexChanged.connect(
            self.mv_change_ov_selection)
        self.mv_update_ov_selector(self.mv_current_ov)

        self.checkBox_showLabels.setChecked(self.show_labels)
        self.checkBox_showLabels.stateChanged.connect(
            self.mv_toggle_show_labels)
        self.checkBox_showAxes.setChecked(self.show_axes)
        self.checkBox_showAxes.stateChanged.connect(self.mv_toggle_show_axes)
        self.checkBox_showImported.setChecked(self.show_imported)
        self.checkBox_showImported.stateChanged.connect(
            self.mv_toggle_show_imported)
        self.checkBox_showStubOV.setChecked(self.show_stub_ov)
        self.checkBox_showStubOV.stateChanged.connect(
            self.mv_toggle_show_stub_ov)
        self.checkBox_showStagePos.setChecked(self.show_stage_pos)
        self.checkBox_showStagePos.stateChanged.connect(
            self.mv_toggle_show_stage_pos)

    def mv_update_grid_selector(self, current_grid=-1):
        # Set up grid selector:
        if current_grid >= self.number_grids:
            current_grid = -1
        self.comboBox_gridSelectorMV.blockSignals(True)
        self.comboBox_gridSelectorMV.clear()
        self.comboBox_gridSelectorMV.addItems(
            ['Hide grids', 'All grids'] + self.gm.get_grid_str_list())
        self.comboBox_gridSelectorMV.setCurrentIndex(current_grid + 2)
        self.comboBox_gridSelectorMV.blockSignals(False)

    def mv_update_ov_selector(self, current_ov=-1):
        self.comboBox_OVSelectorMV.blockSignals(True)
        self.comboBox_OVSelectorMV.clear()
        self.comboBox_OVSelectorMV.addItems(
            ['Hide OVs', 'All OVs'] + self.ovm.get_ov_str_list())
        self.comboBox_OVSelectorMV.setCurrentIndex(current_ov + 2)
        self.comboBox_OVSelectorMV.blockSignals(False)

    def mv_change_tile_preview_mode(self):
        self.mv_tile_preview_mode = (
            self.comboBox_tilePreviewSelectorMV.currentIndex())
        self.cfg['viewport']['mv_tile_preview_mode'] = str(
            self.mv_tile_preview_mode)
        if self.mv_tile_preview_mode == 3:
            # Hide OVs:
            self.comboBox_OVSelectorMV.blockSignals(True)
            self.comboBox_OVSelectorMV.setCurrentIndex(0)
            self.mv_current_ov = -2
            self.comboBox_OVSelectorMV.blockSignals(False)
            # Hide stub:
            self.show_stub_ov = False
            self.checkBox_showStubOV.setChecked(self.show_stub_ov)
        self.mv_draw()

    def mv_change_grid_selection(self):
        self.mv_current_grid = self.comboBox_gridSelectorMV.currentIndex() - 2
        self.cfg['viewport']['mv_current_grid'] = str(self.mv_current_grid)
        self.mv_draw()

    def mv_change_ov_selection(self):
        self.mv_current_ov = self.comboBox_OVSelectorMV.currentIndex() - 2
        self.cfg['viewport']['mv_current_ov'] = str(self.mv_current_ov)
        self.mv_draw()

    def mv_toggle_show_labels(self):
        # update variable show_labels and redraw
        self.show_labels = self.checkBox_showLabels.isChecked()
        self.cfg['viewport']['show_labels'] = str(self.show_labels)
        self.mv_draw()

    def mv_toggle_show_axes(self):
        self.show_axes = self.checkBox_showAxes.isChecked()
        self.cfg['viewport']['show_axes'] = str(self.show_axes)
        self.mv_draw()

    def mv_toggle_show_stub_ov(self):
        self.show_stub_ov = self.checkBox_showStubOV.isChecked()
        self.cfg['viewport']['show_stub_ov'] = str(self.show_stub_ov)
        self.mv_draw()

    def mv_toggle_show_imported(self):
        self.show_imported = self.checkBox_showImported.isChecked()
        self.cfg['viewport']['show_imported'] = str(self.show_imported)
        self.mv_draw()

    def mv_toggle_tile_acq_indicator(self, grid_number, tile_number):
        self.tile_indicator_on ^= True
        self.tile_indicator_pos = [grid_number, tile_number]
        self.mv_draw()

    def mv_toggle_ov_acq_indicator(self, ov_number):
        self.ov_indicator_on ^= True
        self.ov_indicator_pos = ov_number
        self.mv_draw()

    def mv_toggle_show_stage_pos(self):
        self.show_stage_pos ^= True
        self.mv_draw()

    def mv_load_stage_limits(self):
        (self.min_sx, self.max_sx,
            self.min_sy, self.max_sy) = self.cs.get_stage_limits()

    def mv_load_all_overviews(self):
        """Load the images specified in the OV file list into memory """
        self.ov_img = []
        # Load the OV image:
        ov_file_list = self.ovm.get_ov_file_list()
        for i in range(self.number_ov):
            if os.path.isfile(ov_file_list[i]):
                self.ov_img.append(QPixmap(ov_file_list[i]))
            else:
                # Show blue transparent ROI when no OV image found
                blank = QPixmap(self.ovm.get_ov_width_p(i),
                                self.ovm.get_ov_height_p(i))
                blank.fill(QColor(255, 255, 255, 0))
                self.ov_img.append(blank)
                self.mv_qp.begin(self.ov_img[i])
                self.mv_qp.setPen(QColor(0, 0, 255, 0))
                self.mv_qp.setBrush(QColor(0, 0, 255, 70))
                self.mv_qp.drawRect(0, 0,
                         self.ovm.get_ov_width_p(i),
                         self.ovm.get_ov_height_p(i))
                self.mv_qp.end()

    def mv_load_overview(self, ov_number):
        # (Re)load a single OV:
        if ov_number < self.number_ov:
            ov_file_list = self.ovm.get_ov_file_list()
            if os.path.isfile(ov_file_list[ov_number]):
                self.ov_img[ov_number] = QPixmap(ov_file_list[ov_number])

    def mv_load_stub_overview(self):
        """Load the most recent stub OV image into memory"""
        # Load stub OV image:
        stub_ov_file = self.ovm.get_stub_ov_file()
        if os.path.isfile(stub_ov_file):
            self.stub_ov_img = QPixmap(stub_ov_file)
            self.stub_ov_exists = True
        else:
            self.stub_ov_exists = False

    def mv_load_all_imported_images(self):
        """Load all imported images into memory. Clear all previously loaded
        images.
        """
        self.imported_img = []
        self.imported_img_opacity = []
        self.number_imported = self.ovm.get_number_imported()
        for i in range(self.number_imported):
            self.mv_load_imported_image(i)

    def mv_load_last_imported_image(self):
        """Load the most recent imported image into memory and enable the
        option 'show imported images'.
        """
        self.number_imported = self.ovm.get_number_imported()
        new_image_number = self.number_imported - 1
        self.mv_load_imported_image(new_image_number)
        self.show_imported = True
        self.cfg['viewport']['show_imported'] = 'True'
        self.checkBox_showImported.setChecked(True)

    def mv_load_imported_image(self, img_number):
        """Load the specified imported image into memory."""
        file_name = self.ovm.get_imported_img_file(img_number)
        angle = self.ovm.get_imported_img_rotation(img_number)
        opacity = 1 - self.ovm.get_imported_img_transparency(img_number)/100
        if os.path.isfile(file_name):
            try:
                img = QPixmap(file_name)
                if angle != 0:
                    trans = QTransform()
                    trans.rotate(angle)
                    img = img.transformed(trans)
            except:
                img = None
        else:
            img = None
        if img_number < len(self.imported_img):
            self.imported_img[img_number] = img
            self.imported_img_opacity[img_number] = opacity
        else:
            self.imported_img.append(img)
            self.imported_img_opacity.append(opacity)
        if img is None:
            QMessageBox.warning(self, 'Error loading imported image',
                                f'Imported image number {img_number} could not '
                                f'be loaded. Check if the folder containing '
                                f'the image ({file_name}) was deleted or '
                                f'moved, or if the image file is damaged or in '
                                f'the wrong format.', QMessageBox.Ok)

    def mv_update_after_tile_selection(self):
        # Update tile selectors:
        if self.sv_current_grid == self.selected_grid:
            self.sv_update_tile_selector()
        if self.m_current_grid == self.selected_grid:
            self.m_update_tile_selector()
        self.ovm.update_all_ov_debris_detections_areas(self.gm)
        self.transmit_cmd('SHOW CURRENT SETTINGS')
        self.mv_draw()

    def mv_show_context_menu(self, p):
        px, py = p.x() - self.WINDOW_MARGIN_X, p.y() - self.WINDOW_MARGIN_Y
        if px in range(self.VIEWER_WIDTH) and py in range(self.VIEWER_HEIGHT):
            self.selected_grid, self.selected_tile = \
                self.mv_get_grid_tile_mouse_selection(px, py)
            self.selected_ov = self.mv_get_ov_mouse_selection(px, py)
            self.selected_imported = (
                self.mv_get_imported_mouse_selection(px, py))
            sx, sy = self.mv_get_stage_coordinates_from_mouse_position(px, py)
            dx, dy = self.cs.convert_to_d((sx, sy))
            current_pos_str = ('Move stage to X: {0:.3f}, '.format(sx)
                               + 'Y: {0:.3f}'.format(sy))
            self.selected_stage_pos = (sx, sy)

            menu = QMenu()
            action1 = menu.addAction('Load tile/OV in Slice Viewer')
            action1.triggered.connect(self.sv_load_selected)
            action2 = menu.addAction('Load tile/OV in Focus Tool')
            action2.triggered.connect(self.mv_load_selected_in_ft)
            action3 = menu.addAction('Load tile/OV statistics')
            action3.triggered.connect(self.m_load_selected)
            menu.addSeparator()
            action4 = menu.addAction('Select all tiles in grid')
            action4.triggered.connect(self.mv_select_all_tiles)
            action5 = menu.addAction('Deselect all tiles in grid')
            action5.triggered.connect(self.mv_deselect_all_tiles)
            if self.af.get_method() == 2:
                action6 = menu.addAction('Select/deselect for focus tracking')
            else:
                action6 = menu.addAction('Select/deselect for autofocus')
            action6.triggered.connect(self.mv_toggle_tile_autofocus)
            action7 = menu.addAction('Select/deselect for adaptive focus')
            action7.triggered.connect(self.mv_toggle_tile_adaptive_focus)
            menu.addSeparator()
            action8 = menu.addAction(current_pos_str)
            action8.triggered.connect(self.mv_move_to_stage_pos)
            action9 = menu.addAction('Set stub OV centre')
            action9.triggered.connect(self.mv_set_stub_ov_centre)
            menu.addSeparator()
            action10 = menu.addAction('Import and place image')
            action10.triggered.connect(self.mv_import_image)
            action11 = menu.addAction('Adjust imported image')
            action11.triggered.connect(self.mv_adjust_imported_image)
            action12 = menu.addAction('Delete imported image')
            action12.triggered.connect(self.mv_delete_imported_image)
            if ('magc_mode' in self.cfg['sys'] 
            and self.cfg['sys']['magc_mode'] == 'True'):
                
                menu.addSeparator()
                action13 = menu.addAction('MagC|Propagate grid to all sections')
                action13.triggered.connect(self.mv_propagate_grid_all_sections)
                action14 = menu.addAction('MagC|Propagate grid to selected sections')
                action14.triggered.connect(self.mv_propagate_grid_selected_sections)

            if (self.selected_tile is None) and (self.selected_ov is None):
                action1.setEnabled(False)
                action2.setEnabled(False)
                action3.setEnabled(False)
            if self.selected_grid is None:
                action4.setEnabled(False)
                action5.setEnabled(False)
            if self.af.get_tracking_mode() == 1:
                action6.setEnabled(False)
            if self.selected_imported is None:
                action11.setEnabled(False)
            if self.ovm.get_number_imported == 0:
                action12.setEnabled(False)
            if self.acq_in_progress:
                action2.setEnabled(False)
                action4.setEnabled(False)
                action5.setEnabled(False)
                action6.setEnabled(False)
                action7.setEnabled(False)
                action8.setEnabled(False)
                action9.setEnabled(False)
            if self.cfg['sys']['simulation_mode'] == 'True':
                action8.setEnabled(False)
                action9.setEnabled(False)
            menu.exec_(self.mapToGlobal(p))

    def mv_get_selected_stage_pos(self):
        return self.selected_stage_pos

    def mv_load_selected_in_ft(self):
        self.transmit_cmd('LOAD IN FOCUS TOOL')

    def mv_move_to_stage_pos(self):
        self.transmit_cmd('MOVE STAGE')

    def mv_set_stub_ov_centre(self):
        self.stub_ov_centre = self.selected_stage_pos
        self.mv_acquire_stub_overview()

    def mv_get_stub_ov_centre(self):
        return self.stub_ov_centre

    def mv_reset_stub_ov_centre(self):
        self.stub_ov_centre = [None, None]

    def mv_get_stage_coordinates_from_mouse_position(self, px, py):
        dx, dy = px - 500, py - 400
        mv_centre_dx, mv_centre_dy = self.cs.get_mv_centre_d()
        mv_scale = self.cs.get_mv_scale()
        dx_pos, dy_pos = (mv_centre_dx + dx / mv_scale,
                          mv_centre_dy + dy / mv_scale)
        sx_pos, sy_pos = self.cs.convert_to_s((dx_pos, dy_pos))
        return (sx_pos, sy_pos)

    def mv_draw(self):
        """Draw all elements on mosaic viewer canvas"""
        show_debris_area = self.cfg['debris']['show_detection_area'] == 'True'
        if self.ov_drag_active or self.grid_drag_active:
            show_debris_area = False
        # Start with empty black canvas, size fixed (1000 x 800):
        self.mv_canvas.fill(Qt.black)
        # Begin painting on canvas:
        self.mv_qp.begin(self.mv_canvas)
        # First, show stub OV if option selected:
        if self.show_stub_ov and self.stub_ov_exists:
            self.mv_place_stub_overview()
        # Place OV overviews over stub OV:
        if self.mv_current_ov == -1:
            for i in range(self.number_ov):
                self.mv_place_overview(i, show_debris_area)
        if self.mv_current_ov >= 0:
            self.mv_place_overview(self.mv_current_ov, show_debris_area)
        # Tile preview mode:
        if self.mv_tile_preview_mode == 0:
            show_grid, show_previews, with_gaps = True, False, False
        if self.mv_tile_preview_mode == 1:
            show_grid, show_previews, with_gaps = True, True, False
        if self.mv_tile_preview_mode == 2:
            show_grid, show_previews, with_gaps = False, True, False
        if self.mv_tile_preview_mode == 3:
            show_grid, show_previews, with_gaps = False, True, True
        if self.mv_current_grid == -1:
            for i in range(self.number_grids):
                self.mv_place_grid(i, show_grid,
                                show_previews, with_gaps)
        if self.mv_current_grid >= 0:
            self.mv_place_grid(self.mv_current_grid, show_grid,
                            show_previews, with_gaps)
        # Finally, show imported images:
        if self.show_imported and (self.number_imported > 0):
            for i in range(self.number_imported):
                self.mv_place_imported_img(i)
        # Show stage boundaries (motor limits)
        self.mv_draw_stage_boundaries()
        # Show axes:
        if self.show_axes:
            self.mv_draw_stage_axes()
        if self.mv_measure_active:
            self.mv_draw_measure_labels()
        # Show help panel:
        if self.help_panel_visible:
            self.mv_qp.drawPixmap(800, 310, self.mv_help_panel_img)

        if self.cfg['sys']['simulation_mode'] == 'True':
            # Simulation mode indicator:
            self.mv_qp.setPen(QPen(QColor(0, 0, 0), 1, Qt.SolidLine))
            self.mv_qp.setBrush(QColor(0, 0, 0, 255))
            self.mv_qp.drawRect(0, 0, 140, 20)
            self.mv_qp.setPen(QPen(QColor(255, 0, 0), 1, Qt.SolidLine))
            self.mv_qp.drawText(5, 15, 'SIMULATION MODE')
        # Show current stage position:
        if self.show_stage_pos:
            # Coordinates within mv_qp:
            stage_x_v, stage_y_v = self.cs.convert_to_v(self.cs.convert_to_d(
                self.stage.get_last_known_xy()))
            size = int(self.cs.get_mv_scale() * 5)
            if size < 10:
                size = 10
            self.mv_qp.setPen(QPen(QColor(255, 0, 0), 2, Qt.SolidLine))
            self.mv_qp.setBrush(QColor(255, 0, 0, 0))
            self.mv_qp.drawEllipse(QPoint(stage_x_v, stage_y_v), size, size)
            self.mv_qp.setBrush(QColor(255, 0, 0, 0))
            self.mv_qp.drawEllipse(QPoint(stage_x_v, stage_y_v), int(size/2), int(size/2))
            self.mv_qp.drawLine(stage_x_v - 1.25 * size, stage_y_v,
                                stage_x_v + 1.25 * size, stage_y_v)
            self.mv_qp.drawLine(stage_x_v, stage_y_v - 1.25 * size,
                                stage_x_v, stage_y_v + 1.25 * size)

        self.mv_qp.end()
        # All elements have been drawn, show them:
        self.mosaic_viewer.setPixmap(self.mv_canvas)
        # Update text labels:
        mv_scale = self.cs.get_mv_scale()
        self.label_FOVSize.setText(
            '{0:.1f}'.format(self.VIEWER_WIDTH / mv_scale)
            + ' µm × '
            + '{0:.1f}'.format(self.VIEWER_HEIGHT / mv_scale) + ' µm')

    def mv_calculate_visible_area(self, vx, vy, w_px, h_px, resize_ratio):
        crop_area = QRect(0, 0, w_px, h_px)
        vx_cropped, vy_cropped = vx, vy
        visible = self.mv_element_is_visible(vx, vy, w_px, h_px, resize_ratio)
        if visible:
            if (vx >= 0) and (vy >= 0):
                crop_area = QRect(0, 0,
                                  (self.VIEWER_WIDTH - vx) / resize_ratio,
                                  self.VIEWER_HEIGHT / resize_ratio)
            if (vx >= 0) and (vy < 0):
                crop_area = QRect(0, -vy / resize_ratio,
                                  (self.VIEWER_WIDTH - vx) / resize_ratio,
                                  (self.VIEWER_HEIGHT) / resize_ratio)
                vy_cropped = 0
            if (vx < 0) and (vy < 0):
                crop_area = QRect(-vx / resize_ratio, -vy / resize_ratio,
                                  (self.VIEWER_WIDTH) / resize_ratio,
                                  (self.VIEWER_HEIGHT) / resize_ratio)
                vx_cropped, vy_cropped = 0, 0
            if (vx < 0) and (vy >= 0):
                crop_area = QRect(-vx / resize_ratio, 0,
                                  (self.VIEWER_WIDTH) / resize_ratio,
                                  (self.VIEWER_HEIGHT - vy) / resize_ratio)
                vx_cropped = 0
        return visible, crop_area, vx_cropped, vy_cropped

    def mv_element_is_visible(self, vx, vy, w_px, h_px, resize_ratio):
        if ((-vx >= w_px * resize_ratio) or (-vy >= h_px * resize_ratio)
            or (vx >= self.VIEWER_WIDTH) or (vy >= self.VIEWER_HEIGHT)):
            visible = False
        else:
            visible = True
        return visible

    def mv_place_stub_overview(self):
        """Place stub overview image into the mosaic viewer canvas.
           Crop and resize the image before placing it.
        """
        # qp must be active
        viewport_pixel_size = 1000 / self.cs.get_mv_scale()
        resize_ratio = self.ovm.STUB_OV_PIXEL_SIZE / viewport_pixel_size
        # Compute position of stub overview (upper left corner) and its
        # width and height
        dx, dy = self.cs.get_stub_ov_origin_d()
        dx -= 1024/2 * self.ovm.STUB_OV_PIXEL_SIZE / 1000
        dy -= 768/2 * self.ovm.STUB_OV_PIXEL_SIZE / 1000
        vx, vy = self.cs.convert_to_v((dx, dy))
        width_px, height_px = self.ovm.get_stub_ov_full_size()
        # Crop and resize stub OV before placing it into viewport:
        (visible, crop_area, vx_rel, vy_rel) = self.mv_calculate_visible_area(
             vx, vy, width_px, height_px, resize_ratio)
        if visible:
            cropped_img = self.stub_ov_img.copy(crop_area)
            v_width = cropped_img.size().width()
            cropped_resized_img = cropped_img.scaledToWidth(
                v_width * resize_ratio)
            # Draw stub OV:
            self.mv_qp.drawPixmap(vx_rel, vy_rel, cropped_resized_img)
            # Draw grey rectangle around stub OV:
            pen = QPen(QColor(50, 50, 50), 1, Qt.SolidLine)
            self.mv_qp.setPen(pen)
            self.mv_qp.drawRect(vx - 1, vy - 1,
                             width_px * resize_ratio + 1,
                             height_px * resize_ratio + 1)

    def mv_place_imported_img(self, img_number):
        """Place imported image specified by img_number into the viewport."""
        if self.imported_img[img_number] is not None:
            viewport_pixel_size = 1000 / self.cs.get_mv_scale()
            img_pixel_size = self.ovm.get_imported_img_pixel_size(img_number)
            resize_ratio = img_pixel_size / viewport_pixel_size

            # Compute position of image in viewport:
            dx, dy = self.cs.get_imported_img_centre_d(img_number)
            # Get width and height of the imported QPixmap:
            width = self.imported_img[img_number].width()
            height = self.imported_img[img_number].height()
            pixel_size = self.ovm.get_imported_img_pixel_size(img_number)
            dx -= (width * pixel_size / 1000)/2
            dy -= (height * pixel_size / 1000)/2
            vx, vy = self.cs.convert_to_v((dx, dy))
            # Crop and resize image before placing it into viewport:
            visible, crop_area, vx_rel, vy_rel = self.mv_calculate_visible_area(
                vx, vy, width, height, resize_ratio)
            if visible:
                cropped_img = self.imported_img[img_number].copy(crop_area)
                v_width = cropped_img.size().width()
                cropped_resized_img = cropped_img.scaledToWidth(
                    v_width * resize_ratio)
                self.mv_qp.setOpacity(self.imported_img_opacity[img_number])
                self.mv_qp.drawPixmap(vx_rel, vy_rel, cropped_resized_img)
                self.mv_qp.setOpacity(1)

    def mv_place_overview(self, ov_number, show_debris_area):
        """Place OV overview image specified by ov_number into the mosaic
        viewer canvas. Crop and resize the image before placing it.
        """
        # Load, resize and crop OV for display
        viewport_pixel_size = 1000 / self.cs.get_mv_scale()
        ov_pixel_size = self.ovm.get_ov_pixel_size(ov_number)
        resize_ratio = ov_pixel_size / viewport_pixel_size
        # Load OV centre in SEM coordinates:
        dx, dy = self.cs.get_ov_centre_d(ov_number)
        # First, calculate origin of OV image with respect to
        # SEM coordinate system:
        dx -= self.ovm.get_ov_width_d(ov_number)/2
        dy -= self.ovm.get_ov_height_d(ov_number)/2
        width_px = self.ovm.get_ov_width_p(ov_number)
        height_px = self.ovm.get_ov_height_p(ov_number)
        # Convert to viewport window coordinates:
        vx, vy = self.cs.convert_to_v((dx, dy))
        # Crop and resize OV before placing it into viewport:
        visible, crop_area, vx_rel, vy_rel = self.mv_calculate_visible_area(
            vx, vy, width_px, height_px, resize_ratio)
        if visible:
            cropped_img = self.ov_img[ov_number].copy(crop_area)
            v_width = cropped_img.size().width()
            cropped_resized_img = cropped_img.scaledToWidth(
                v_width * resize_ratio)
            if not (self.ov_drag_active and ov_number == self.selected_ov):
                # Draw OV:
                self.mv_qp.drawPixmap(vx_rel, vy_rel, cropped_resized_img)
            # draw blue rectangle around OV:
            self.mv_qp.setPen(QPen(QColor(0, 0, 255), 2, Qt.SolidLine))
            if (self.ov_indicator_pos == ov_number) and self.ov_indicator_on:
                indicator_colour = QColor(128, 0, 128, 80)
                self.mv_qp.setBrush(indicator_colour)
            else:
                self.mv_qp.setBrush(QColor(0, 0, 255, 0))

            self.mv_qp.drawRect(vx, vy,
                             width_px * resize_ratio,
                             height_px * resize_ratio)

            if show_debris_area:
                # w3, w4 are fudge factors for clearer display
                w3 = utils.fit_in_range(self.cs.get_mv_scale()/2, 1, 3)
                w4 = utils.fit_in_range(self.cs.get_mv_scale(), 5, 9)

                area = self.ovm.get_ov_debris_detection_area(ov_number)
                (top_left_dx, top_left_dy,
                 bottom_right_dx, bottom_right_dy) = area
                width = bottom_right_dx - top_left_dx
                height = bottom_right_dy - top_left_dy
                if width == self.ovm.get_ov_width_p(ov_number):
                    w3, w4 = 3, 6

                pen = QPen(QColor(0, 0, 255), 2, Qt.DashDotLine)
                self.mv_qp.setPen(pen)
                self.mv_qp.setBrush(QColor(0, 0, 0, 0))
                self.mv_qp.drawRect(vx + top_left_dx * resize_ratio - w3,
                                 vy + top_left_dy * resize_ratio - w3,
                                 width * resize_ratio + w4,
                                 height * resize_ratio + w4)
            if self.show_labels:
                font_size = int(self.cs.get_mv_scale() * 8)
                if font_size < 12:
                    font_size = 12
                self.mv_qp.setPen(QColor(0, 0, 255))
                self.mv_qp.setBrush(QColor(0, 0, 255))
                ov_label_rect = QRect(vx, vy - int(4/3 * font_size),
                                    int(font_size * 3.6), int(4/3 * font_size))
                self.mv_qp.drawRect(ov_label_rect)
                self.mv_qp.setPen(QColor(255, 255, 255))
                font = QFont()
                font.setPixelSize(font_size)
                self.mv_qp.setFont(font)
                self.mv_qp.drawText(ov_label_rect,
                                    Qt.AlignVCenter | Qt.AlignHCenter,
                                    'OV %d' % ov_number)

    def mv_place_grid(self, grid_number, show_grid=True,
                      show_previews=False, with_gaps=False):
        mv_scale = self.cs.get_mv_scale()
        # Calculate origin of the tile map with respect to mosaic viewer
        dx, dy = self.cs.get_grid_origin_d(grid_number)
        dx -= self.gm.get_tile_width_d(grid_number)/2
        dy -= self.gm.get_tile_height_d(grid_number)/2
        origin_vx, origin_vy = self.cs.convert_to_v((dx, dy))
        width_px, height_px = self.gm.get_grid_size_px_py(grid_number)

        viewport_pixel_size = 1000 / mv_scale
        grid_pixel_size = self.gm.get_pixel_size(grid_number)
        resize_ratio = grid_pixel_size / viewport_pixel_size

        visible = self.mv_element_is_visible(
            origin_vx, origin_vy, width_px, height_px, resize_ratio)

        if visible:
            if with_gaps:
                tile_map = self.gm.get_gapped_grid_map(grid_number)
            else:
                tile_map = self.gm.get_grid_map_d(grid_number)
            # active tiles in current grid:
            active_tiles = self.gm.get_active_tiles(grid_number)
            tile_width_v = self.gm.get_tile_width_d(grid_number) * mv_scale
            tile_height_v = self.gm.get_tile_height_d(grid_number) * mv_scale
            base_dir = self.cfg['acq']['base_dir']
            font_size1 = int(tile_width_v/5)
            font_size1 = utils.fit_in_range(font_size1, 2, 120)
            font_size2 = int(tile_width_v/11)
            font_size2 = utils.fit_in_range(font_size2, 1, 40)

            if (show_previews
                    and not self.fov_drag_active
                    and not self.grid_drag_active
                    and self.cs.get_mv_scale() > 1.4):
                # Previews are disabled when FOV or grid is being dragged or
                # when sufficiently zoomed out.
                width_px = self.gm.get_tile_width_p(grid_number)
                height_px = self.gm.get_tile_height_p(grid_number)

                for tile in active_tiles:
                    vx = origin_vx + tile_map[tile][0] * mv_scale
                    vy = origin_vy + tile_map[tile][1] * mv_scale
                    tile_visible = self.mv_element_is_visible(
                        vx, vy, width_px, height_px, resize_ratio)
                    if tile_visible:
                        # load current tile preview:
                        tile_preview_filename = (
                            base_dir + '\\'
                            + utils.get_tile_preview_save_path(grid_number, tile))
                        if os.path.exists(tile_preview_filename):
                            tile_img = QPixmap(tile_preview_filename)
                            # Scale image from 512px to current tile width:
                            tile_img = tile_img.scaledToWidth(tile_width_v)
                            # Draw:
                            self.mv_qp.drawPixmap(vx, vy, tile_img)

            # Display grid lines
            size = self.gm.get_grid_size(grid_number)
            rows, cols = size[0], size[1]
            # Load grid colour:
            rgb = self.gm.get_display_colour(grid_number)
            grid_colour = QColor(rgb[0], rgb[1], rgb[2], 255)
            indicator_colour = QColor(128, 00, 128, 80)
            grid_pen = QPen(grid_colour, 1, Qt.SolidLine)
            grid_brush_active_tile = QBrush(QColor(rgb[0], rgb[1], rgb[2], 40),
                                            Qt.SolidPattern)
            grid_brush_transparent = QBrush(QColor(255, 255, 255, 0),
                                            Qt.SolidPattern)
            font = QFont()
            for tile in range(rows * cols):
                self.mv_qp.setPen(grid_pen)
                if tile in active_tiles:
                    self.mv_qp.setBrush(grid_brush_active_tile)
                else:
                    self.mv_qp.setBrush(grid_brush_transparent)
                if ((self.tile_indicator_pos == [grid_number, tile])
                    and self.tile_indicator_on):
                    self.mv_qp.setBrush(indicator_colour)
                # tile rectangles
                if show_grid:
                    self.mv_qp.drawRect(origin_vx + tile_map[tile][0] * mv_scale,
                        origin_vy + tile_map[tile][1] * mv_scale,
                        tile_width_v, tile_height_v)
                if self.show_labels:
                    if tile in active_tiles:
                        self.mv_qp.setPen(QColor(255, 255, 255))
                        font.setBold(True)
                    else:
                        self.mv_qp.setPen(QColor(rgb[0], rgb[1], rgb[2]))
                        font.setBold(False)
                    pos_x = (origin_vx + tile_map[tile][0] * mv_scale
                            + tile_width_v/2)
                    pos_y = (origin_vy + tile_map[tile][1] * mv_scale
                            + tile_height_v/2)
                    position_rect = QRect(pos_x - tile_width_v/2,
                                          pos_y - tile_height_v/2,
                                          tile_width_v, tile_height_v)
                    # Show tile number
                    font.setPixelSize(int(font_size1))
                    self.mv_qp.setFont(font)
                    self.mv_qp.drawText(position_rect,
                                     Qt.AlignVCenter | Qt.AlignHCenter,
                                     str(tile))
                    # Show autofocus/gradient marker and working distance
                    font = QFont()
                    font.setPixelSize(int(font_size2))
                    font.setBold(True)
                    self.mv_qp.setFont(font)
                    position_rect = QRect(
                        pos_x - tile_width_v,
                        pos_y - tile_height_v
                        - tile_height_v/4,
                        2 * tile_width_v, 2 * tile_height_v)

                    show_grad_label = (
                        self.gm.is_adaptive_focus_tile(grid_number, tile)
                        and self.gm.is_adaptive_focus_active(grid_number))
                    show_af_label = (
                        self.af.is_ref_tile(grid_number, tile)
                        and self.af.is_active()
                        and self.af.get_method() < 2)
                    show_tracking_label = (
                        self.af.is_ref_tile(grid_number, tile)
                        and self.af.is_active()
                        and self.af.get_method() == 2)

                    if show_grad_label and show_af_label:
                        self.mv_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'GRAD + AF')
                    elif show_grad_label and show_tracking_label:
                        self.mv_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'GRAD + TRACK')
                    elif show_grad_label:
                        self.mv_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'GRADIENT')
                    elif show_af_label:
                        self.mv_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'AUTOFOCUS')
                    elif show_tracking_label:
                        self.mv_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'TRACKED FOCUS')

                    font.setBold(False)
                    self.mv_qp.setFont(font)
                    if (self.gm.get_tile_wd(grid_number, tile) != 0
                        and (tile in active_tiles or show_grad_label
                        or show_af_label or show_tracking_label)):
                        position_rect = QRect(
                            pos_x - tile_width_v,
                            pos_y - tile_height_v
                            + tile_height_v/4,
                            2 * tile_width_v, 2 * tile_height_v)
                        self.mv_qp.drawText(
                            position_rect,
                            Qt.AlignVCenter | Qt.AlignHCenter,
                            'WD: {0:.6f}'.format(
                            self.gm.get_tile_wd(grid_number, tile) * 1000))

            if self.show_labels:
                fontsize = int(self.cs.get_mv_scale() * 8)
                if fontsize < 12:
                    fontsize = 12

                font.setPixelSize(fontsize)
                self.mv_qp.setFont(font)
                self.mv_qp.setPen(grid_colour)
                self.mv_qp.setBrush(grid_colour)
                grid_label_rect = QRect(origin_vx, origin_vy - int(4/3 * fontsize),
                                        int(5.3 * fontsize), int(4/3 * fontsize))
                self.mv_qp.drawRect(grid_label_rect)
                if self.gm.get_display_colour_index(grid_number) in [1, 2, 3]:
                    self.mv_qp.setPen(QColor(0, 0, 0))
                else:
                    self.mv_qp.setPen(QColor(255, 255, 255))

                self.mv_qp.drawText(grid_label_rect,
                                    Qt.AlignVCenter | Qt.AlignHCenter,
                                    'GRID %d' % grid_number)

    def mv_draw_stage_boundaries(self):
        """Show bounding box around area accessible to the stage motors:
           Compute stage corner coordinates for viewport
        """
        b_left = self.cs.convert_to_v(self.cs.convert_to_d(
            (self.min_sx, self.min_sy)))
        b_top = self.cs.convert_to_v(self.cs.convert_to_d(
            (self.max_sx, self.min_sy)))
        b_right = self.cs.convert_to_v(self.cs.convert_to_d(
            (self.max_sx, self.max_sy)))
        b_bottom = self.cs.convert_to_v(self.cs.convert_to_d(
            (self.min_sx, self.max_sy)))
        self.mv_qp.setPen(QColor(255, 255, 255))
        self.mv_qp.drawLine(b_left[0], b_left[1], b_top[0], b_top[1])
        self.mv_qp.drawLine(b_top[0], b_top[1], b_right[0], b_right[1])
        self.mv_qp.drawLine(b_right[0], b_right[1], b_bottom[0], b_bottom[1])
        self.mv_qp.drawLine(b_bottom[0], b_bottom[1], b_left[0], b_left[1])
        if self.show_labels:
            # Show corner stage coordinates:
            font = QFont()
            font.setPixelSize(12)
            self.mv_qp.setFont(font)
            self.mv_qp.drawText(b_left[0]-75, b_left[1],
                             'X: {0:.0f} µm'.format(self.min_sx))
            self.mv_qp.drawText(b_left[0]-75, b_left[1]+15,
                             'Y: {0:.0f} µm'.format(self.min_sy))
            self.mv_qp.drawText(b_top[0]-20, b_top[1]-25,
                             'X: {0:.0f} µm'.format(self.max_sx))
            self.mv_qp.drawText(b_top[0]-20, b_top[1]-10,
                             'Y: {0:.0f} µm'.format(self.min_sy))
            self.mv_qp.drawText(b_right[0]+10, b_right[1],
                             'X: {0:.0f} µm'.format(self.max_sx))
            self.mv_qp.drawText(b_right[0]+10, b_right[1]+15,
                             'Y: {0:.0f} µm'.format(self.max_sy))
            self.mv_qp.drawText(b_bottom[0]-20, b_bottom[1]+15,
                             'X: {0:.0f} µm'.format(self.min_sx))
            self.mv_qp.drawText(b_bottom[0]-20, b_bottom[1]+30,
                             'Y: {0:.0f} µm'.format(self.max_sy))

    def mv_draw_stage_axes(self):
        # Stage x-axis:
        x_axis_start = self.cs.convert_to_v(self.cs.convert_to_d(
            (self.min_sx - 100, 0)))
        x_axis_end = self.cs.convert_to_v(self.cs.convert_to_d(
            (self.max_sx + 100, 0)))
        # Stage y-axis:
        y_axis_start = self.cs.convert_to_v(self.cs.convert_to_d(
            (0, self.min_sy - 100)))
        y_axis_end = self.cs.convert_to_v(self.cs.convert_to_d(
            (0, self.max_sy + 100)))
        self.mv_qp.setPen(QPen(QColor(255, 255, 255), 1, Qt.DashLine))
        self.mv_qp.drawLine(x_axis_start[0], x_axis_start[1],
                         x_axis_end[0], x_axis_end[1])
        self.mv_qp.drawLine(y_axis_start[0], y_axis_start[1],
                         y_axis_end[0], y_axis_end[1])
        if self.show_labels:
            font = QFont()
            font.setPixelSize(12)
            self.mv_qp.drawText(x_axis_end[0] + 10, x_axis_end[1], 'stage x-axis')
            self.mv_qp.drawText(y_axis_end[0] + 10, y_axis_end[1] + 10,
                             'stage y-axis')

    def mv_draw_measure_labels(self):
        self.mv_qp.setPen(QPen(QColor(255, 165, 0), 2, Qt.SolidLine))
        self.mv_qp.setBrush(QColor(0, 0, 0, 0))
        if not (self.measure_p1 == (None, None)):
            p1_x, p1_y = self.cs.convert_to_v(self.measure_p1)
            self.mv_qp.drawEllipse(QPoint(p1_x, p1_y), 4, 4)
            self.mv_qp.drawLine(p1_x, p1_y-10, p1_x, p1_y+10)
            self.mv_qp.drawLine(p1_x-10, p1_y, p1_x+10, p1_y)
        if not (self.measure_p2 == (None, None)):
            p2_x, p2_y = self.cs.convert_to_v(self.measure_p2)
            self.mv_qp.drawEllipse(QPoint(p2_x, p2_y), 4, 4)
            self.mv_qp.drawLine(p2_x, p2_y-10, p2_x, p2_y+10)
            self.mv_qp.drawLine(p2_x-10, p2_y, p2_x+10, p2_y)

        if self.measure_complete:
            # Draw line between p1 and p2:
            p1_x, p1_y = self.cs.convert_to_v(self.measure_p1)
            p2_x, p2_y = self.cs.convert_to_v(self.measure_p2)
            self.mv_qp.drawLine(p1_x, p1_y, p2_x, p2_y)
            distance = sqrt((self.measure_p1[0] - self.measure_p2[0])**2
                            + (self.measure_p1[1] - self.measure_p2[1])**2)
            self.mv_qp.setPen(QPen(QColor(0, 0, 0), 1, Qt.SolidLine))
            self.mv_qp.setBrush(QColor(0, 0, 0, 255))
            self.mv_qp.drawRect(920, 780, 80, 20)
            self.mv_qp.setPen(QPen(QColor(255, 165, 0), 1, Qt.SolidLine))
            if distance < 1:
                self.mv_qp.drawText(925, 795,
                    str((int(distance * 1000))) + ' nm')
            else:
                self.mv_qp.drawText(925, 795,
                    '{0:.2f}'.format(distance) + ' µm')

    def mv_start_measure(self, dx, dy):
        mv_centre_dx, mv_centre_dy = self.cs.get_mv_centre_d()
        mv_scale = self.cs.get_mv_scale()
        if self.measure_p1 == (None, None) or self.measure_complete:
            self.measure_p1 = (mv_centre_dx + dx / mv_scale,
                               mv_centre_dy + dy / mv_scale)
            self.measure_complete = False
            self.measure_p2 = (None, None)
            self.mv_draw()
        elif self.measure_p2 == (None, None):
            self.measure_p2 = (mv_centre_dx + dx / mv_scale,
                               mv_centre_dy + dy / mv_scale)
            self.measure_complete = True
            self.mv_draw()

    def mv_adjust_scale(self):
        # Recalculate scaling factor:
        new_mv_scale = (
            self.VIEWER_ZOOM_F1
            * (self.VIEWER_ZOOM_F2)**self.horizontalSlider_MV.value())
        self.cs.set_mv_scale(new_mv_scale)
        # Redraw viewport:
        self.mv_draw()

    def mv_mouse_zoom(self, px, py, factor):
        # Recalculate scaling factor:
        old_mv_scale = self.cs.get_mv_scale()
        new_mv_scale = utils.fit_in_range(
            factor * old_mv_scale,
            self.VIEWER_ZOOM_F1,
            self.VIEWER_ZOOM_F1 * (self.VIEWER_ZOOM_F2)**99)  # 99 is max slider value
        self.cs.set_mv_scale(new_mv_scale)
        self.horizontalSlider_MV.blockSignals(True)
        self.horizontalSlider_MV.setValue(
            log(new_mv_scale / self.VIEWER_ZOOM_F1, self.VIEWER_ZOOM_F2))
        self.horizontalSlider_MV.blockSignals(False)
        # Recentre, so that mouse position is preserved:
        current_centre_dx, current_centre_dy = self.cs.get_mv_centre_d()
        x_shift = px - 500
        y_shift = py - 400
        scale_diff = 1 / new_mv_scale - 1 / old_mv_scale
        new_centre_dx = current_centre_dx - x_shift * scale_diff
        new_centre_dy = current_centre_dy - y_shift * scale_diff

        new_centre_dx = utils.fit_in_range(
            new_centre_dx, self.VC_MIN_X, self.VC_MAX_X)
        new_centre_dy = utils.fit_in_range(
            new_centre_dy, self.VC_MIN_Y, self.VC_MAX_Y)
        # Set new mv_centre coordinates:
        self.cs.set_mv_centre_d((new_centre_dx, new_centre_dy))
        # Redraw viewport:
        self.mv_draw()

    def mv_shift_fov(self, shift_vector):
        dx, dy = shift_vector
        current_centre_dx, current_centre_dy = self.cs.get_mv_centre_d()
        mv_scale = self.cs.get_mv_scale()
        new_centre_dx = current_centre_dx + dx / mv_scale
        new_centre_dy = current_centre_dy + dy / mv_scale
        new_centre_dx = utils.fit_in_range(
            new_centre_dx, self.VC_MIN_X, self.VC_MAX_X)
        new_centre_dy = utils.fit_in_range(
            new_centre_dy, self.VC_MIN_Y, self.VC_MAX_Y)
        # Set new mv_centre coordinates:
        self.cs.set_mv_centre_d((new_centre_dx, new_centre_dy))

    def mv_reposition_ov(self, shift_vector):
        dx, dy = shift_vector
        # current position:
        (old_ov_dx, old_ov_dy) = \
            self.cs.get_ov_centre_d(self.selected_ov)
        mv_scale = self.cs.get_mv_scale()
        # Move tiling along shift vector:
        new_ov_dx = old_ov_dx + dx / mv_scale
        new_ov_dy = old_ov_dy + dy / mv_scale
        # Set new origin:
        self.cs.set_ov_centre_s(self.selected_ov,
            self.cs.convert_to_s((new_ov_dx, new_ov_dy)))
        self.mv_draw()

    def mv_reposition_imported_img(self, shift_vector):
        dx, dy = shift_vector
        # current position:
        (old_origin_dx, old_origin_dy) = \
            self.cs.get_imported_img_centre_d(self.selected_imported)
        mv_scale = self.cs.get_mv_scale()
        # Move tiling along shift vector:
        new_origin_dx = old_origin_dx + dx / mv_scale
        new_origin_dy = old_origin_dy + dy / mv_scale
        # Set new origin:
        self.cs.set_imported_img_centre_s(self.selected_imported,
            self.cs.convert_to_s((new_origin_dx, new_origin_dy)))

    def mv_reposition_grid(self, shift_vector):
        dx, dy = shift_vector
        # current position:
        (old_grid_origin_dx, old_grid_origin_dy) = \
            self.cs.get_grid_origin_d(self.selected_grid)
        mv_scale = self.cs.get_mv_scale()
        # Move tiling along shift vector:
        new_grid_origin_dx = old_grid_origin_dx + dx / mv_scale
        new_grid_origin_dy = old_grid_origin_dy + dy / mv_scale
        # Set new origin:
        self.cs.set_grid_origin_s(self.selected_grid,
            self.cs.convert_to_s((new_grid_origin_dx, new_grid_origin_dy)))

    def mv_get_current_grid(self):
        return self.mv_current_grid

    def mv_get_current_ov(self):
        return self.mv_current_ov

    def mv_get_selected_grid(self):
        return self.selected_grid

    def mv_get_selected_tile(self):
        return self.selected_tile

    def mv_get_selected_ov(self):
        return self.selected_ov

    def mv_get_grid_tile_mouse_selection(self, px, py):
        if self.mv_current_grid == -2:
            grid_range = []
            selected_grid, selected_tile = None, None
        elif self.mv_current_grid == -1:
            grid_range = reversed(range(self.number_grids))
            selected_grid, selected_tile = None, None
        elif self.mv_current_grid >= 0:
            grid_range = range(self.mv_current_grid, self.mv_current_grid + 1)
            selected_grid, selected_tile = self.mv_current_grid, None

        for grid_number in grid_range:
            # Calculate origin of the tile map with respect to mosaic viewer
            dx, dy = self.cs.get_grid_origin_d(grid_number)
            mv_scale = self.cs.get_mv_scale()
            pixel_size = self.gm.get_pixel_size(grid_number)
            dx -= self.gm.get_tile_width_d(grid_number)/2
            dy -= self.gm.get_tile_height_d(grid_number)/2
            pixel_offset_x, pixel_offset_y = self.cs.convert_to_v((dx, dy))
            cols = self.gm.get_number_cols(grid_number)
            rows = self.gm.get_number_rows(grid_number)
            overlap = self.gm.get_overlap(grid_number)
            shift = (self.gm.get_row_shift(grid_number) * pixel_size
                     / 1000 * mv_scale)
            tile_width_p = self.gm.get_tile_width_p(grid_number)
            tile_height_p = self.gm.get_tile_height_p(grid_number)
            p_width = (((tile_width_p - overlap) * pixel_size)
                       / 1000 * mv_scale)
            p_height = (((tile_height_p - overlap) * pixel_size)
                        / 1000 * mv_scale)
            x, y = px - pixel_offset_x, py - pixel_offset_y
            if x >= 0 and y >= 0:
                j = y // p_height
                if j % 2 == 0:
                    i = x // p_width
                elif x > shift:
                    i = (x - shift) // p_width
                else:
                    i = cols
                if (i < cols) and (j < rows):
                    selected_tile = int(i + j * cols)
                else:
                    selected_tile = None
                if selected_tile in range(
                    self.gm.get_number_tiles(grid_number)):
                    selected_grid = grid_number
                    break
                else:
                    selected_tile = None
            # Also check whether grid label clicked:
            f = int(self.cs.get_mv_scale() * 8)
            if f < 12:
                f = 12
            label_width = int(5.3 * f)
            label_height = int(4/3 * f)
            l_y = y + label_height
            if x >= 0 and l_y >= 0 and selected_grid is None:
                if x < label_width and l_y < label_height:
                    selected_grid = grid_number
                    break

        return selected_grid, selected_tile

    def mv_get_ov_mouse_selection(self, px, py):
        if self.mv_current_ov == -2:
            selected_ov = None
        elif self.mv_current_ov == -1:
            selected_ov = None
            for ov_number in reversed(range(self.number_ov)):
                # Calculate origin of the overview with respect to mosaic viewer
                dx, dy = self.cs.get_ov_centre_d(ov_number)
                dx -= self.ovm.get_ov_width_d(ov_number)/2
                dy -= self.ovm.get_ov_height_d(ov_number)/2
                pixel_offset_x, pixel_offset_y = self.cs.convert_to_v((dx, dy))
                mv_scale = self.cs.get_mv_scale()
                p_width = self.ovm.get_ov_width_d(ov_number) * mv_scale
                p_height = self.ovm.get_ov_height_d(ov_number) * mv_scale
                x, y = px - pixel_offset_x, py - pixel_offset_y
                if x >= 0 and y >= 0:
                    if x < p_width and y < p_height:
                        selected_ov = ov_number
                        break
                    else:
                        selected_ov = None
                # Also check whether label clicked:
                f = int(self.cs.get_mv_scale() * 8)
                if f < 12:
                    f = 12
                label_width = int(f * 3.6)
                label_height = int(4/3 * f)
                l_y = y + label_height
                if x >= 0 and l_y >= 0 and selected_ov is None:
                    if x < label_width and l_y < label_height:
                        selected_ov = ov_number
                        break
        elif self.mv_current_ov >= 0:
            selected_ov = self.mv_current_ov
        return selected_ov

    def mv_get_imported_mouse_selection(self, px, py):
        selected_imported = None
        if self.show_imported:
            for img_number in reversed(range(self.number_imported)):
                # Calculate origin of the image with respect to mosaic viewer
                # Use width and heigh of loaded image (may be rotated
                # and therefore larger than original image)
                if self.imported_img[img_number] is not None:
                    dx, dy = self.cs.get_imported_img_centre_d(img_number)
                    pixel_size = self.ovm.get_imported_img_pixel_size(
                        img_number)
                    width_d = (self.imported_img[img_number].size().width()
                               * pixel_size / 1000)
                    height_d = (self.imported_img[img_number].size().height()
                                * pixel_size / 1000)
                    dx -= width_d/2
                    dy -= height_d/2
                    pixel_offset_x, pixel_offset_y = self.cs.convert_to_v(
                        (dx, dy))
                    mv_scale = self.cs.get_mv_scale()
                    p_width = width_d * mv_scale
                    p_height = height_d * mv_scale
                    x, y = px - pixel_offset_x, py - pixel_offset_y
                    if x >= 0 and y >= 0:
                        if x < p_width and y < p_height:
                            selected_imported = img_number
                            break
        return selected_imported

    def mv_select_all_tiles(self):
        if self.selected_grid is not None:
            self.gm.select_all_tiles(self.selected_grid)
            if self.af.get_tracking_mode() == 1:
                self.af.select_all_active_tiles()
            self.add_to_main_log('CTRL: All tiles in grid %d selected.'
                                 % self.selected_grid)
            self.mv_update_after_tile_selection()

    def mv_deselect_all_tiles(self):
       if self.selected_grid is not None:
            self.gm.reset_active_tiles(self.selected_grid)
            if self.af.get_tracking_mode() == 1:
                self.af.reset_ref_tiles()
            self.add_to_main_log('CTRL: All tiles in grid %d deselected.'
                                 % self.selected_grid)
            self.mv_update_after_tile_selection()

    def mv_toggle_tile_autofocus(self):
        if self.selected_grid is not None and self.selected_tile is not None:
            ref_tiles = self.af.get_ref_tiles()
            tile_id = str(self.selected_grid) + '.' + str(self.selected_tile)
            if tile_id in ref_tiles:
                ref_tiles.remove(tile_id)
            else:
                ref_tiles.append(tile_id)
            self.af.set_ref_tiles(ref_tiles)
            self.mv_draw()

    def mv_toggle_tile_adaptive_focus(self):
        if self.selected_grid is not None and self.selected_tile is not None:
            af_tiles = self.gm.get_adaptive_focus_tiles(self.selected_grid)
            if self.selected_tile in af_tiles:
                af_tiles[af_tiles.index(self.selected_tile)] = -1
            else:
                # Let user choose the intended relative position of the tile:
                dialog = AdaptiveFocusSelectionDlg(af_tiles)
                if dialog.exec_():
                    if dialog.selected is not None:
                        af_tiles[dialog.selected] = self.selected_tile
            self.gm.set_adaptive_focus_tiles(self.selected_grid, af_tiles)
            self.transmit_cmd('UPDATE FT TILE SELECTOR')
            self.mv_draw()

    def mv_toggle_measure(self):
        self.mv_measure_active = not self.mv_measure_active
        if self.mv_measure_active:
            self.sv_measure_active = False
        self.measure_p1 = (None, None)
        self.measure_p2 = (None, None)
        self.measure_complete = False
        self.update_measure_buttons()
        self.mv_draw()

    def mv_toggle_help_panel(self):
        self.help_panel_visible ^= True
        if self.help_panel_visible:
            self.pushButton_helpViewport.setStyleSheet(
                'QPushButton {color: #FF6A22;}')
            self.pushButton_helpSliceViewer.setStyleSheet(
                'QPushButton {color: #FF6A22;}')
        else:
            self.pushButton_helpViewport.setStyleSheet(
                'QPushButton {color: #000000;}')
            self.pushButton_helpSliceViewer.setStyleSheet(
                'QPushButton {color: #000000;}')
        self.mv_draw()
        self.sv_draw()

    def mv_import_image(self):
        self.transmit_cmd('IMPORT IMG')

    def mv_adjust_imported_image(self):
        self.transmit_cmd('ADJUST IMPORTED IMG' + str(self.selected_imported))

    def mv_delete_imported_image(self):
        self.transmit_cmd('DELETE IMPORTED IMG')

    def mv_refresh_overviews(self):
        self.transmit_cmd('REFRESH OV')

    def mv_acquire_stub_overview(self):
        self.transmit_cmd('ACQUIRE STUB OV')

    def mv_show_new_stub_overview(self):
        self.checkBox_showStubOV.setChecked(True)
        self.show_stub_ov = True
        self.cfg['viewport']['show_stub_ov'] = 'True'
        self.mv_load_stub_overview()
        self.mv_draw()

    def mv_propagate_grid_selected_sections(self):
        print('selected_sections', self.cfg['MagC']['selected_sections'])
        pass
        
    def mv_propagate_grid_all_sections(self):
        pass
        
# =================== Below: Slice Viewer (sv) functions ======================

    def sv_initialize(self):
        self.slice_view_images = []
        self.slice_view_index = 0    # slice_view_index: 0..max_slices
        self.max_slices = 10  # default value

        self.sv_current_grid = int(self.cfg['viewport']['sv_current_grid'])
        self.sv_current_tile = int(self.cfg['viewport']['sv_current_tile'])
        self.sv_current_ov = int(self.cfg['viewport']['sv_current_ov'])
        self.sv_scale_tile = float(self.cfg['viewport']['sv_scale_tile'])
        self.sv_scale_ov = float(self.cfg['viewport']['sv_scale_ov'])

        self.sv_measure_active = False
        self.sv_canvas = QPixmap(self.VIEWER_WIDTH, self.VIEWER_HEIGHT)
        # Help panel:
        self.sv_help_panel_img = QPixmap('..\\img\\help-sliceviewer.png')
        self.sv_qp = QPainter()

        self.pushButton_reloadSV.clicked.connect(self.sv_load_slices)
        self.pushButton_measureSlice.clicked.connect(self.sv_toggle_measure)
        self.pushButton_measureSlice.setIcon(QIcon('..\\img\\measure.png'))
        self.pushButton_measureSlice.setIconSize(QSize(16, 16))
        self.pushButton_sliceBWD.clicked.connect(self.sv_slice_bwd)
        self.pushButton_sliceFWD.clicked.connect(self.sv_slice_fwd)

        self.horizontalSlider_SV.valueChanged.connect(self.sv_adjust_scale)
        if self.sv_current_ov >= 0:
            self.horizontalSlider_SV.setValue(
                log(self.sv_scale_ov / self.VIEWER_OV_ZOOM_F1,
                    self.VIEWER_OV_ZOOM_F2))
        else:
            self.horizontalSlider_SV.setValue(
                log(self.sv_scale_tile / self.VIEWER_TILE_ZOOM_F1,
                    self.VIEWER_TILE_ZOOM_F2))

        self.comboBox_gridSelectorSV.currentIndexChanged.connect(
            self.sv_change_grid_selection)
        self.sv_update_grid_selector(self.sv_current_grid)
        self.comboBox_tileSelectorSV.currentIndexChanged.connect(
            self.sv_change_tile_selection)
        self.sv_update_tile_selector(self.sv_current_tile)
        self.comboBox_OVSelectorSV.currentIndexChanged.connect(
            self.sv_change_ov_selection)
        self.sv_update_ov_selector(self.sv_current_ov)

        self.checkBox_setNativeRes.setChecked(self.show_native_res)
        self.checkBox_setNativeRes.stateChanged.connect(
            self.sv_toggle_show_native_resolution)
        if self.show_native_res:
            self.horizontalSlider_SV.setEnabled(False)
            self.sv_set_native_resolution()
        self.checkBox_showSaturated.setChecked(self.show_saturated_pixels)
        self.checkBox_showSaturated.stateChanged.connect(
            self.sv_toggle_show_saturated_pixels)

        self.lcdNumber_sliceIndicator.display(0)
        self.spinBox_maxSlices.setRange(1, 20)
        self.spinBox_maxSlices.setSingleStep(1)
        self.spinBox_maxSlices.setValue(self.max_slices)
        self.spinBox_maxSlices.valueChanged.connect(self.sv_set_max_slices)
        # Painting
        # Empty slice viewer canvas with instructions:
        self.sv_canvas.fill(Qt.black)
        self.sv_qp.begin(self.sv_canvas)
        self.sv_qp.setPen(QColor(255, 255, 255))
        position_rect = QRect(150, 380, 700, 40)
        self.sv_qp.drawRect(position_rect)
        self.sv_qp.drawText(position_rect,
                         Qt.AlignVCenter | Qt.AlignHCenter,
                         'Select tile or overview from controls below '
                         'and click "(Re)load" to display the images from the '
                         'most recent slices.')
        self.sv_instructions_displayed = True
        self.sv_qp.end()
        self.slice_viewer.setPixmap(self.sv_canvas)

    def sv_update_grid_selector(self, current_grid=0):
        if current_grid >= self.number_grids:
            current_grid = 0
        self.comboBox_gridSelectorSV.blockSignals(True)
        self.comboBox_gridSelectorSV.clear()
        self.comboBox_gridSelectorSV.addItems(self.gm.get_grid_str_list())
        self.comboBox_gridSelectorSV.setCurrentIndex(current_grid)
        self.comboBox_gridSelectorSV.blockSignals(False)

    def sv_update_tile_selector(self, current_tile=-1):
        self.comboBox_tileSelectorSV.blockSignals(True)
        self.comboBox_tileSelectorSV.clear()
        self.comboBox_tileSelectorSV.addItems(
            ['Select tile']
            + self.gm.get_active_tile_str_list(self.sv_current_grid))
        self.comboBox_tileSelectorSV.setCurrentIndex(current_tile + 1)
        self.comboBox_tileSelectorSV.blockSignals(False)

    def sv_update_ov_selector(self, current_ov=-1):
        if current_ov >= self.number_ov:
            current_ov = -1
        self.comboBox_OVSelectorSV.blockSignals(True)
        self.comboBox_OVSelectorSV.clear()
        self.comboBox_OVSelectorSV.addItems(
            ['Select OV'] + self.ovm.get_ov_str_list())
        self.comboBox_OVSelectorSV.setCurrentIndex(current_ov + 1)
        self.comboBox_OVSelectorSV.blockSignals(False)

    def sv_slice_fwd(self):
        if self.slice_view_index < 0:
            self.slice_view_index += 1
            self.lcdNumber_sliceIndicator.display(self.slice_view_index)
            # For now, disable showing saturated pixels (too slow)
            if self.show_saturated_pixels:
                self.checkBox_showSaturated.setChecked(False)
                self.show_saturated_pixels = False
                self.cfg['viewport']['show_saturated_pixels'] = 'False'
            self.sv_draw()

    def sv_slice_bwd(self):
        if (self.slice_view_index > (-1) * (self.max_slices-1)) and \
           ((-1) * self.slice_view_index < len(self.slice_view_images)-1):
            self.slice_view_index -= 1
            self.lcdNumber_sliceIndicator.display(self.slice_view_index)
            # For now, disable showing saturated pixels (too slow)
            if self.show_saturated_pixels:
                self.checkBox_showSaturated.setChecked(False)
                self.show_saturated_pixels = False
                self.cfg['viewport']['show_saturated_pixels'] = 'False'
            self.sv_draw()

    def sv_set_max_slices(self):
        self.max_slices = self.spinBox_maxSlices.value()

    def sv_adjust_scale(self):
        # Recalculate scale factor
        # This depends on whether OV or a tile is displayed.
        if self.sv_current_ov >= 0:
            previous_scaling_ov = self.sv_scale_ov
            self.sv_scale_ov = (
                self.VIEWER_OV_ZOOM_F1
                * self.VIEWER_OV_ZOOM_F2**self.horizontalSlider_SV.value())
            self.cfg['viewport']['sv_scale_ov'] = str(self.sv_scale_ov)
            ratio = self.sv_scale_ov/previous_scaling_ov
            # Offsets must be adjusted to keep slice view centred:
            current_offset_x_ov = int(self.cfg['viewport']['sv_offset_x_ov'])
            current_offset_y_ov = int(self.cfg['viewport']['sv_offset_y_ov'])
            dx = 500 - current_offset_x_ov
            dy = 400 - current_offset_y_ov
            new_offset_x_ov = int(current_offset_x_ov - ratio * dx + dx)
            new_offset_y_ov = int(current_offset_y_ov - ratio * dy + dy)
            self.cfg['viewport']['sv_offset_x_ov'] = str(new_offset_x_ov)
            self.cfg['viewport']['sv_offset_y_ov'] = str(new_offset_y_ov)
        else:
            previous_scaling = self.sv_scale_tile
            self.sv_scale_tile = (
                self.VIEWER_TILE_ZOOM_F1
                * self.VIEWER_TILE_ZOOM_F2**self.horizontalSlider_SV.value())
            self.cfg['viewport']['sv_scale_tile'] = str(self.sv_scale_tile)
            ratio = self.sv_scale_tile/previous_scaling
            # Offsets must be adjusted to keep slice view centred:
            current_offset_x = int(self.cfg['viewport']['sv_offset_x_tile'])
            current_offset_y = int(self.cfg['viewport']['sv_offset_y_tile'])
            dx = 500 - current_offset_x
            dy = 400 - current_offset_y
            new_offset_x = int(current_offset_x - ratio * dx + dx)
            new_offset_y = int(current_offset_y - ratio * dy + dy)
            self.cfg['viewport']['sv_offset_x_tile'] = str(new_offset_x)
            self.cfg['viewport']['sv_offset_y_tile'] = str(new_offset_y)
        # For now, disable showing saturated pixels (too slow)
        if self.show_saturated_pixels:
            self.checkBox_showSaturated.setChecked(False)
            self.show_saturated_pixels = False
            self.cfg['viewport']['show_saturated_pixels'] = 'False'
        # Redraw viewport:
        self.sv_draw()

    def sv_mouse_zoom(self, px, py, factor):
        """Zoom in by specified factor and preserve the relative location of
        where user double-clicked."""
        if self.sv_current_ov >= 0:
            old_sv_scale_ov = self.sv_scale_ov
            # Recalculate scaling factor:
            self.sv_scale_ov = utils.fit_in_range(
                factor * old_sv_scale_ov,
                self.VIEWER_OV_ZOOM_F1,
                self.VIEWER_OV_ZOOM_F1 * self.VIEWER_OV_ZOOM_F2**99)
                # 99 is max slider value
            self.cfg['viewport']['sv_scale_ov'] = str(self.sv_scale_ov)
            ratio = self.sv_scale_ov / old_sv_scale_ov
            self.horizontalSlider_SV.blockSignals(True)
            self.horizontalSlider_SV.setValue(
                log(self.sv_scale_ov / self.VIEWER_OV_ZOOM_F1,
                    self.VIEWER_OV_ZOOM_F2))
            self.horizontalSlider_SV.blockSignals(False)
            # Preserve mouse click position:
            current_offset_x_ov = int(self.cfg['viewport']['sv_offset_x_ov'])
            current_offset_y_ov = int(self.cfg['viewport']['sv_offset_y_ov'])
            new_offset_x_ov = int(
                ratio * current_offset_x_ov - (ratio - 1) * px)
            new_offset_y_ov = int(
                ratio * current_offset_y_ov - (ratio - 1) * py)
            self.cfg['viewport']['sv_offset_x_ov'] = str(new_offset_x_ov)
            self.cfg['viewport']['sv_offset_y_ov'] = str(new_offset_y_ov)
        elif self.sv_current_tile >= 0:
            old_sv_scale_tile = self.sv_scale_tile
            # Recalculate scaling factor:
            self.sv_scale_tile = utils.fit_in_range(
                factor * old_sv_scale_tile,
                self.VIEWER_TILE_ZOOM_F1,
                self.VIEWER_TILE_ZOOM_F1 * self.VIEWER_TILE_ZOOM_F2**99)
                # 99 is max slider value
            self.cfg['viewport']['sv_scale_tile'] = str(self.sv_scale_tile)
            ratio = self.sv_scale_tile / old_sv_scale_tile
            self.horizontalSlider_SV.blockSignals(True)
            self.horizontalSlider_SV.setValue(
                log(self.sv_scale_tile / self.VIEWER_TILE_ZOOM_F1,
                    self.VIEWER_TILE_ZOOM_F2))
            self.horizontalSlider_SV.blockSignals(False)
            # Preserve mouse click position:
            current_offset_x_tile = int(
                self.cfg['viewport']['sv_offset_x_tile'])
            current_offset_y_tile = int(
                self.cfg['viewport']['sv_offset_y_tile'])
            new_offset_x_tile = int(
                ratio * current_offset_x_tile - (ratio - 1) * px)
            new_offset_y_tile = int(
                ratio * current_offset_y_tile - (ratio - 1) * py)
            self.cfg['viewport']['sv_offset_x_tile'] = str(new_offset_x_tile)
            self.cfg['viewport']['sv_offset_y_tile'] = str(new_offset_y_tile)
        # Redraw viewport:
        self.sv_draw()

    def sv_change_grid_selection(self):
        self.sv_current_grid = self.comboBox_gridSelectorSV.currentIndex()
        self.cfg['viewport']['sv_current_grid'] = str(self.sv_current_grid)
        self.sv_update_tile_selector()

    def sv_change_tile_selection(self):
        self.sv_current_tile = self.comboBox_tileSelectorSV.currentIndex() - 1
        self.cfg['viewport']['sv_current_tile'] = str(self.sv_current_tile)
        if self.sv_current_tile >= 0:
            self.slice_view_index = 0
            self.lcdNumber_sliceIndicator.display(0)
            self.sv_current_ov = -1
            self.cfg['viewport']['sv_current_ov'] = '-1'
            self.comboBox_OVSelectorSV.blockSignals(True)
            self.comboBox_OVSelectorSV.setCurrentIndex(self.sv_current_ov + 1)
            self.comboBox_OVSelectorSV.blockSignals(False)
            self.sv_scale_tile = float(self.cfg['viewport']['sv_scale_tile'])
            self.horizontalSlider_SV.setValue(
                log(self.sv_scale_tile / 5.0, 1.04))
            self.sv_load_slices()

    def sv_change_ov_selection(self):
        self.sv_current_ov = self.comboBox_OVSelectorSV.currentIndex() - 1
        self.cfg['viewport']['sv_current_ov'] = str(self.sv_current_ov)
        if self.sv_current_ov >= 0:
            self.slice_view_index = 0
            self.lcdNumber_sliceIndicator.display(0)
            self.sv_current_tile = -1
            self.cfg['viewport']['sv_current_tile'] = '-1'
            self.comboBox_tileSelectorSV.blockSignals(True)
            self.comboBox_tileSelectorSV.setCurrentIndex(
                self.sv_current_tile + 1)
            self.comboBox_tileSelectorSV.blockSignals(False)
            self.sv_scale_ov = float(self.cfg["viewport"]["sv_scale_ov"])
            self.horizontalSlider_SV.setValue(log(self.sv_scale_ov, 1.03))
            self.sv_load_slices()

    def sv_load_selected(self):
        # use active tiles!!
        active_tiles = self.gm.get_active_tiles(self.selected_grid)
        if self.selected_tile in active_tiles:
            self.selected_tile = active_tiles.index(self.selected_tile)
        else:
            self.selected_tile = None
        if ((self.selected_grid is not None)
            and (self.selected_tile is not None)):
            self.sv_current_grid = self.selected_grid
            self.sv_current_tile = self.selected_tile
            self.comboBox_gridSelectorSV.blockSignals(True)
            self.comboBox_gridSelectorSV.setCurrentIndex(self.selected_grid)
            self.comboBox_gridSelectorSV.blockSignals(False)
            self.sv_update_tile_selector(self.selected_tile)
            self.comboBox_OVSelectorSV.blockSignals(True)
            self.comboBox_OVSelectorSV.setCurrentIndex(0)
            self.comboBox_OVSelectorSV.blockSignals(False)
            self.sv_current_ov = -1
        elif self.selected_ov is not None:
            self.sv_current_ov = self.selected_ov
            self.comboBox_OVSelectorSV.blockSignals(True)
            self.comboBox_OVSelectorSV.setCurrentIndex(self.sv_current_ov + 1)
            self.comboBox_OVSelectorSV.blockSignals(False)
            self.sv_current_tile = -1
            self.sv_update_tile_selector(-1)

        self.tabWidget.setCurrentIndex(1)
        QApplication.processEvents()
        self.sv_load_slices()

    def sv_img_within_boundaries(self, vx, vy, w_px, h_px, resize_ratio):
        visible = not ((-vx >= w_px * resize_ratio - 80)
                       or (-vy >= h_px * resize_ratio - 80)
                       or (vx >= self.VIEWER_WIDTH - 80)
                       or (vy >= self.VIEWER_HEIGHT - 80))
        return visible

    def sv_load_slices(self):
        # Reading the tiff files from SmartSEM generates warnings. They
        # are suppressed in the code below.
        # First show a "waiting" info, since loading the image may take a while:
        self.sv_qp.begin(self.sv_canvas)
        self.sv_qp.setBrush(QColor(0, 0, 0))
        if self.sv_instructions_displayed:
            position_rect = QRect(150, 380, 700, 40)
            self.sv_qp.setPen(QColor(0, 0, 0))
            self.sv_qp.drawRect(position_rect)
            self.sv_instructions_displayed = False

        self.sv_qp.setPen(QColor(255, 255, 255))
        position_rect = QRect(350, 380, 300, 40)
        self.sv_qp.drawRect(position_rect)
        self.sv_qp.drawText(position_rect,
                            Qt.AlignVCenter | Qt.AlignHCenter,
                            'Loading slices...')
        self.sv_qp.end()
        self.slice_viewer.setPixmap(self.sv_canvas)
        QApplication.processEvents()
        self.slice_view_images = []
        self.slice_view_index = 0
        self.lcdNumber_sliceIndicator.display(0)
        start_slice = int(self.cfg['acq']['slice_counter'])
        base_dir = self.cfg['acq']['base_dir']
        stack_name = base_dir[base_dir.rfind('\\') + 1:]

        slices_loaded = False
        if self.sv_current_ov >= 0:
            for i in range(0, -self.max_slices, -1):
                filename = (base_dir + '\\'
                            + utils.get_ov_save_path(
                            stack_name, self.sv_current_ov, start_slice + i))
                if os.path.isfile(filename):
                    self.slice_view_images.append(QPixmap(filename))
                    slices_loaded = True
                    utils.suppress_console_warning()

            self.sv_set_native_resolution()
            self.sv_draw()
        elif self.sv_current_tile >= 0:
            selected_tile = self.gm.get_active_tiles(
                self.sv_current_grid)[self.sv_current_tile]
            for i in range(0, -self.max_slices, -1):
                filename = (base_dir + '\\'
                            + utils.get_tile_save_path(
                            stack_name, self.sv_current_grid, selected_tile,
                            start_slice + i))
                if os.path.isfile(filename):
                    slices_loaded = True
                    self.slice_view_images.append(QPixmap(filename))
                    utils.suppress_console_warning()
            self.sv_set_native_resolution()
            # Draw the current slice:
            self.sv_draw()

        if not slices_loaded:
            self.sv_qp.begin(self.sv_canvas)
            self.sv_qp.setPen(QColor(255, 255, 255))
            self.sv_qp.setBrush(QColor(0, 0, 0))
            position_rect = QRect(350, 380, 300, 40)
            self.sv_qp.drawRect(position_rect)
            self.sv_qp.drawText(position_rect,
                                Qt.AlignVCenter | Qt.AlignHCenter,
                                'No images found')
            self.sv_qp.end()
            self.slice_viewer.setPixmap(self.sv_canvas)

    def sv_set_native_resolution(self):
        if self.sv_current_ov >= 0:
            previous_scaling_ov = self.sv_scale_ov
            # OV pixel size:
            ov_pixel_size = self.ovm.get_ov_pixel_size(self.sv_current_ov)
            self.sv_scale_ov = 1000 / ov_pixel_size
            ratio = self.sv_scale_ov/previous_scaling_ov
            current_offset_x_ov = int(self.cfg['viewport']['sv_offset_x_ov'])
            current_offset_y_ov = int(self.cfg['viewport']['sv_offset_y_ov'])
            dx = 500 - current_offset_x_ov
            dy = 400 - current_offset_y_ov
            new_offset_x_ov = int(current_offset_x_ov - ratio * dx + dx)
            new_offset_y_ov = int(current_offset_y_ov - ratio * dy + dy)
            self.cfg['viewport']['sv_offset_x_ov'] = str(new_offset_x_ov)
            self.cfg['viewport']['sv_offset_y_ov'] = str(new_offset_y_ov)
            self.cfg['viewport']['sv_scale_ov'] = str(self.sv_scale_ov)
            self.horizontalSlider_SV.setValue(log(self.sv_scale_ov, 1.03))
        elif self.sv_current_tile >= 0:
            previous_scaling = self.sv_scale_tile
            # Tile pixel size:
            tile_pixel_size = self.gm.get_pixel_size(self.sv_current_grid)
            self.sv_scale_tile = self.VIEWER_WIDTH / tile_pixel_size
            ratio = self.sv_scale_tile/previous_scaling
            current_offset_x = int(self.cfg['viewport']['sv_offset_x_tile'])
            current_offset_y = int(self.cfg['viewport']['sv_offset_y_tile'])
            dx = 500 - current_offset_x
            dy = 400 - current_offset_y
            new_offset_x = int(current_offset_x - ratio * dx + dx)
            new_offset_y = int(current_offset_y - ratio * dy + dy)
            self.cfg['viewport']['sv_offset_x_tile'] = str(new_offset_x)
            self.cfg['viewport']['sv_offset_y_tile'] = str(new_offset_y)
            # Todo:
            # Check if out of bounds.
            # Offsets must be adjusted to keep slice view centred:
            self.cfg['viewport']['sv_scale_tile'] = str(self.sv_scale_tile)
            self.horizontalSlider_SV.setValue(
                log(self.sv_scale_tile / 5.0, 1.04))
        # Redraw viewport:
        self.sv_draw()

    def sv_toggle_show_native_resolution(self):
        if self.checkBox_setNativeRes.isChecked():
            self.cfg['viewport']['show_native_resolution'] = 'True'
            self.show_native_res = True
            # Lock zoom:
            self.horizontalSlider_SV.setEnabled(False)
            self.sv_set_native_resolution()
        else:
            self.cfg['viewport']['show_native_resolution'] = 'False'
            self.horizontalSlider_SV.setEnabled(True)

    def sv_toggle_show_saturated_pixels(self):
        self.show_saturated_pixels = self.checkBox_showSaturated.isChecked()
        self.cfg['viewport']['show_saturated_pixels'] = str(
            self.show_saturated_pixels)
        self.sv_draw()

    def sv_draw(self):
        # Empty black canvas for slice viewer
        self.sv_canvas.fill(Qt.black)
        self.sv_qp.begin(self.sv_canvas)
        if self.sv_current_ov >= 0:
            viewport_pixel_size = 1000 / self.sv_scale_ov
            ov_pixel_size = self.ovm.get_ov_pixel_size(self.sv_current_ov)
            resize_ratio = ov_pixel_size / viewport_pixel_size
        else:
            viewport_pixel_size = 1000 / self.sv_scale_tile
            tile_pixel_size = self.gm.get_pixel_size(self.sv_current_grid)
            resize_ratio = tile_pixel_size / viewport_pixel_size

        if len(self.slice_view_images) > 0:
            offset_x = 0
            offset_y = 0
            if self.sv_current_ov >= 0:
                offset_x = int(self.cfg['viewport']['sv_offset_x_ov'])
                offset_y = int(self.cfg['viewport']['sv_offset_y_ov'])
            else:
                offset_x = int(self.cfg['viewport']['sv_offset_x_tile'])
                offset_y = int(self.cfg['viewport']['sv_offset_y_tile'])

            current_image = self.slice_view_images[-self.slice_view_index]

            w_px = current_image.size().width()
            h_px = current_image.size().height()

            visible, crop_area, vx, vy = self.mv_calculate_visible_area(
                offset_x, offset_y, w_px, h_px, resize_ratio)
            display_img = current_image.copy(crop_area)

            # Resize according to scale factor:
            current_width = display_img.size().width()
            display_img = display_img.scaledToWidth(
                current_width * resize_ratio)

            # Show saturated pixels?
            if self.cfg['viewport']['show_saturated_pixels'] == 'True':
                width = display_img.size().width()
                height = display_img.size().height()
                img = display_img.toImage()
                # Black:
                black_pixels = [QColor(0, 0, 0).rgb(),
                                QColor(1, 1, 1).rgb()]
                white_pixels = [QColor(255, 255, 255).rgb(),
                                QColor(254, 254, 254).rgb()]
                blue_pixel = QColor(0, 0, 255).rgb()
                red_pixel = QColor(255, 0, 0).rgb()
                for x in range(0, width):
                    for y in range(0, height):
                        pixel_value = img.pixel(x, y)
                        if pixel_value in black_pixels:
                            img.setPixel(x, y, blue_pixel)
                        if pixel_value in white_pixels:
                            img.setPixel(x, y, red_pixel)
                display_img = QPixmap.fromImage(img)

            self.sv_qp.drawPixmap(vx, vy, display_img)
            # Measuring tool:
            if self.sv_measure_active:
                self.sv_qp.setPen(QPen(QColor(255, 165, 0), 2, Qt.SolidLine))
                self.sv_qp.setBrush(QColor(0, 0, 0, 0))
                if not (self.measure_p1 == (None, None)):
                    p1_x = (self.measure_p1[0] * 1000 / viewport_pixel_size
                            + offset_x)
                    p1_y = (self.measure_p1[1] * 1000 / viewport_pixel_size
                            + offset_y)
                    self.sv_qp.drawEllipse(QPoint(p1_x, p1_y), 4, 4)
                    self.sv_qp.drawLine(p1_x, p1_y-10, p1_x, p1_y+10)
                    self.sv_qp.drawLine(p1_x-10, p1_y, p1_x+10, p1_y)
                if not (self.measure_p2 == (None, None)):
                    p2_x = (self.measure_p2[0] * 1000 / viewport_pixel_size
                            + offset_x)
                    p2_y = (self.measure_p2[1] * 1000 / viewport_pixel_size
                            + offset_y)
                    self.sv_qp.drawEllipse(QPoint(p2_x, p2_y), 4, 4)
                    self.sv_qp.drawLine(p2_x, p2_y-10, p2_x, p2_y+10)
                    self.sv_qp.drawLine(p2_x-10, p2_y, p2_x+10, p2_y)

                if self.measure_complete:
                    # Draw line between p1 and p2:
                    self.sv_qp.drawLine(p1_x, p1_y, p2_x, p2_y)
                    d = sqrt((self.measure_p1[0] - self.measure_p2[0])**2
                              + (self.measure_p1[1] - self.measure_p2[1])**2)
                    self.sv_qp.setPen(QPen(QColor(0, 0, 0), 1, Qt.SolidLine))
                    self.sv_qp.setBrush(QColor(0, 0, 0, 255))
                    self.sv_qp.drawRect(920, 780, 80, 20)
                    self.sv_qp.setPen(QPen(QColor(255, 165, 0), 1,
                                      Qt.SolidLine))
                    if d < 1:
                        self.sv_qp.drawText(925, 795,
                                         str((int(d * 1000))) + ' nm')
                    else:
                        self.sv_qp.drawText(925, 795,
                                         '{0:.2f}'.format(d) + ' µm')

        # Help panel:
        if self.help_panel_visible:
            self.sv_qp.drawPixmap(800, 475, self.sv_help_panel_img)

        self.sv_qp.end()
        self.slice_viewer.setPixmap(self.sv_canvas)
        # Update scaling label:
        if self.sv_current_ov >= 0:
            self.label_FOVSize_sliceViewer.setText(
                '{0:.2f} µm × '.format(self.VIEWER_WIDTH / self.sv_scale_ov)
                + '{0:.2f} µm'.format(self.VIEWER_HEIGHT / self.sv_scale_ov))
        else:
            self.label_FOVSize_sliceViewer.setText(
                '{0:.2f} µm × '.format(self.VIEWER_WIDTH / self.sv_scale_tile)
                + '{0:.2f} µm'.format(self.VIEWER_HEIGHT / self.sv_scale_tile))

    def sv_shift_fov(self, shift_vector):
        (dx, dy) = shift_vector
        if self.sv_current_ov >= 0:
            current_offset_x_ov = int(self.cfg['viewport']['sv_offset_x_ov'])
            current_offset_y_ov = int(self.cfg['viewport']['sv_offset_y_ov'])
            new_offset_x_ov = current_offset_x_ov - dx
            new_offset_y_ov = current_offset_y_ov - dy
            width, height = self.ovm.get_ov_size_px_py(self.sv_current_ov)
            viewport_pixel_size = 1000 / self.sv_scale_ov
            ov_pixel_size = self.ovm.get_ov_pixel_size(self.sv_current_ov)
            resize_ratio = ov_pixel_size / viewport_pixel_size
            if self.sv_img_within_boundaries(new_offset_x_ov, new_offset_y_ov,
                                             width, height, resize_ratio):
                self.cfg['viewport']['sv_offset_x_ov'] = str(new_offset_x_ov)
                self.cfg['viewport']['sv_offset_y_ov'] = str(new_offset_y_ov)
        else:
            current_offset_x = int(self.cfg['viewport']['sv_offset_x_tile'])
            current_offset_y = int(self.cfg['viewport']['sv_offset_y_tile'])
            new_offset_x = current_offset_x - dx
            new_offset_y = current_offset_y - dy
            width, height = self.gm.get_tile_size_px_py(self.sv_current_grid)
            viewport_pixel_size = 1000 / self.sv_scale_tile
            tile_pixel_size = self.gm.get_pixel_size(self.sv_current_grid)
            resize_ratio = tile_pixel_size / viewport_pixel_size
            if self.sv_img_within_boundaries(new_offset_x, new_offset_y,
                                             width, height, resize_ratio):
                self.cfg['viewport']['sv_offset_x_tile'] = str(new_offset_x)
                self.cfg['viewport']['sv_offset_y_tile'] = str(new_offset_y)

    def sv_toggle_measure(self):
        self.sv_measure_active = not self.sv_measure_active
        if self.sv_measure_active:
            self.mv_measure_active = False
        self.measure_p1 = (None, None)
        self.measure_p2 = (None, None)
        self.measure_complete = False
        self.update_measure_buttons()
        self.sv_draw()

    def sv_start_measure(self, dx, dy):
        if self.sv_current_ov >= 0:
            dx -= int(self.cfg['viewport']['sv_offset_x_ov'])
            dy -= int(self.cfg['viewport']['sv_offset_y_ov'])
            scale = float(self.cfg['viewport']['sv_scale_ov'])
        if self.sv_current_tile >= 0:
            dx -= int(self.cfg['viewport']['sv_offset_x_tile'])
            dy -= int(self.cfg['viewport']['sv_offset_y_tile'])
            scale = float(self.cfg['viewport']['sv_scale_tile'])
        if self.measure_p1 == (None, None) or self.measure_complete:
            self.measure_p1 = (dx / scale, dy / scale)
            self.measure_complete = False
            self.measure_p2 = None, None
            self.sv_draw()
        elif self.measure_p2 == (None, None):
            self.measure_p2 = (dx / scale, dy / scale)
            self.measure_complete = True
            self.sv_draw()

    def sv_reset_view(self):
        """Zoom out completely and centre current image."""
        if self.sv_current_ov >= 0:
            self.sv_scale_ov = self.VIEWER_OV_ZOOM_F1
            self.cfg['viewport']['sv_scale_ov'] = str(self.sv_scale_ov)
            self.horizontalSlider_SV.blockSignals(True)
            self.horizontalSlider_SV.setValue(0)
            self.horizontalSlider_SV.blockSignals(False)
            width, height = self.ovm.get_ov_size_px_py(self.sv_current_ov)
            viewport_pixel_size = 1000 / self.sv_scale_ov
            ov_pixel_size = self.ovm.get_ov_pixel_size(self.sv_current_ov)
            resize_ratio = ov_pixel_size / viewport_pixel_size
            self.cfg['viewport']['sv_offset_x_ov'] = str(
                int(500 - (width/2) * resize_ratio))
            self.cfg['viewport']['sv_offset_y_ov'] = str(
                int(400 - (height/2) * resize_ratio))
        elif self.sv_current_tile >= 0:
            self.sv_scale_tile = self.VIEWER_TILE_ZOOM_F1
            self.cfg['viewport']['sv_scale_tile'] = str(self.sv_scale_tile)
            self.horizontalSlider_SV.blockSignals(True)
            self.horizontalSlider_SV.setValue(0)
            self.horizontalSlider_SV.blockSignals(False)
            width, height = self.gm.get_tile_size_px_py(self.sv_current_grid)
            viewport_pixel_size = 1000 / self.sv_scale_tile
            tile_pixel_size = self.gm.get_pixel_size(self.sv_current_grid)
            resize_ratio = tile_pixel_size / viewport_pixel_size
            self.cfg['viewport']['sv_offset_x_tile'] = str(
                int(500 - (width/2) * resize_ratio))
            self.cfg['viewport']['sv_offset_y_tile'] = str(
                int(400 - (height/2) * resize_ratio))
        # Disable native resolution:
        self.cfg['viewport']['show_native_resolution'] = 'False'
        self.horizontalSlider_SV.setEnabled(True)
        self.checkBox_setNativeRes.setChecked(False)
        self.sv_draw()

    def sv_show_context_menu(self, p):
        px, py = p.x() - self.WINDOW_MARGIN_X, p.y() - self.WINDOW_MARGIN_Y
        if px in range(self.VIEWER_WIDTH) and py in range(self.VIEWER_HEIGHT):
            menu = QMenu()
            action1 = menu.addAction('Reset view for current image')
            action1.triggered.connect(self.sv_reset_view)
            menu.exec_(self.mapToGlobal(p))

# ===== Below: monitoring tab functions =======================================

    def m_initialize(self):
        self.m_current_grid = int(self.cfg['viewport']['m_current_grid'])
        self.m_current_tile = int(self.cfg['viewport']['m_current_tile'])
        self.m_current_ov = int(self.cfg['viewport']['m_current_ov'])
        self.m_from_stack = True

        self.histogram_canvas_template = QPixmap(400, 170)
        self.reslice_canvas_template = QPixmap(400, 560)
        self.plots_canvas_template = QPixmap(550, 560)
        self.m_tab_populated = False
        self.m_qp = QPainter()
        if self.cfg['sys']['simulation_mode'] == 'True':
            self.radioButton_fromSEM.setEnabled(False)

        self.radioButton_fromStack.toggled.connect(self.m_source_update)
        self.pushButton_reloadM.clicked.connect(self.m_show_statistics)
        self.comboBox_gridSelectorM.currentIndexChanged.connect(
            self.m_change_grid_selection)
        self.m_update_grid_selector(self.m_current_grid)
        self.comboBox_tileSelectorM.currentIndexChanged.connect(
            self.m_change_tile_selection)
        self.m_update_tile_selector(self.m_current_tile)
        self.comboBox_OVSelectorM.currentIndexChanged.connect(
            self.m_change_ov_selection)
        self.m_update_ov_selector(self.m_current_ov)

        # Empty histogram
        self.histogram_canvas_template.fill(QColor(255, 255, 255))
        self.m_qp.begin(self.histogram_canvas_template)
        self.m_qp.setPen(QColor(0, 0, 0))
        self.m_qp.drawRect(10, 9, 257, 151)

        self.m_qp.drawText(280, 30, 'Data source:')
        self.m_qp.drawText(280, 90, 'Mean: ')
        self.m_qp.drawText(280, 110, 'SD: ')
        self.m_qp.drawText(280, 130, 'Peak at: ')
        self.m_qp.drawText(280, 150, 'Peak count: ')
        self.m_qp.end()
        self.histogram_view.setPixmap(self.histogram_canvas_template)

        # Empty reslice canvas:
        self.reslice_canvas_template.fill(QColor(0, 0, 0))
        self.m_qp.begin(self.reslice_canvas_template)
        pen = QPen(QColor(255, 255, 255))
        self.m_qp.setPen(pen)
        position_rect = QRect(50, 260, 300, 40)
        self.m_qp.drawRect(position_rect)
        self.m_qp.drawText(position_rect,
                         Qt.AlignVCenter | Qt.AlignHCenter,
                         'Select image source from controls below.')
        pen.setWidth(2)
        self.m_qp.setPen(pen)
        # Two arrows to show x and z direction
        self.m_qp.drawLine(12, 513, 12, 543)
        self.m_qp.drawLine(12, 543,  9, 540)
        self.m_qp.drawLine(12, 543, 15, 540)
        self.m_qp.drawLine(12, 513, 42, 513)
        self.m_qp.drawLine(42, 513, 39, 510)
        self.m_qp.drawLine(42, 513, 39, 516)
        self.m_qp.drawText(10, 554, 'z')
        self.m_qp.drawText(48, 516, 'x')
        self.m_qp.end()
        self.reslice_view.setPixmap(self.reslice_canvas_template)
        # Plots:
        self.m_selected_plot_slice = None
        # Empty plots canvas:
        self.plots_canvas_template.fill(QColor(255, 255, 255))
        self.m_qp.begin(self.plots_canvas_template)
        # Four plot areas, draw axes:
        pen = QPen(QColor(0, 0, 0))
        pen.setWidth(2)
        self.m_qp.setPen(pen)
        self.m_qp.drawLine(0, 0, 0, 120)
        self.m_qp.drawLine(0, 146, 0, 266)
        self.m_qp.drawLine(0, 292, 0, 412)
        self.m_qp.drawLine(0, 438, 0, 558)
        # Labels:
        self.m_qp.setPen(QColor(25, 25, 112))
        self.m_qp.drawText(500, 15, 'Mean')
        self.m_qp.drawText(500, 161, 'ΔMean')
        self.m_qp.setPen(QColor(139, 0, 0))
        self.m_qp.drawText(500, 307, 'SD')
        self.m_qp.drawText(500, 453, 'ΔSD')
        # Midlines, dashed:
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        self.m_qp.setPen(pen)
        self.m_qp.drawLine(0, 60, 520, 60)
        self.m_qp.drawLine(0, 206, 520, 206)
        self.m_qp.drawLine(0, 352, 520, 352)
        self.m_qp.drawLine(0, 498, 520, 498)
        self.m_qp.setPen(QColor(25, 25, 112))
        self.m_qp.drawText(523, 210, '0.00')
        self.m_qp.setPen(QColor(139, 0, 0))
        self.m_qp.drawText(523, 502, '0.00')
        self.m_qp.end()
        self.plots_view.setPixmap(self.plots_canvas_template)

    def m_source_update(self):
        self.m_from_stack = self.radioButton_fromStack.isChecked()
        self.m_show_statistics()

    def m_update_grid_selector(self, current_grid=0):
        if current_grid >= self.number_grids:
            current_grid = 0
        self.comboBox_gridSelectorM.blockSignals(True)
        self.comboBox_gridSelectorM.clear()
        self.comboBox_gridSelectorM.addItems(self.gm.get_grid_str_list())
        self.comboBox_gridSelectorM.setCurrentIndex(current_grid)
        self.comboBox_gridSelectorM.blockSignals(False)

    def m_update_tile_selector(self, current_tile=-1):
        self.m_current_tile = current_tile
        self.cfg['viewport']['m_current_tile'] = str(current_tile)
        self.comboBox_tileSelectorM.blockSignals(True)
        self.comboBox_tileSelectorM.clear()
        self.comboBox_tileSelectorM.addItems(
            ['Select tile']
            + self.gm.get_active_tile_str_list(self.m_current_grid))
        self.comboBox_tileSelectorM.setCurrentIndex(current_tile + 1)
        self.comboBox_tileSelectorM.blockSignals(False)

    def m_update_ov_selector(self, current_ov=-1):
        if current_ov > self.number_ov:
            current_ov = 0
        self.comboBox_OVSelectorM.blockSignals(True)
        self.comboBox_OVSelectorM.clear()
        self.comboBox_OVSelectorM.addItems(
            ['Select OV'] + self.ovm.get_ov_str_list())
        self.comboBox_OVSelectorM.setCurrentIndex(current_ov + 1)
        self.comboBox_OVSelectorM.blockSignals(False)

    def m_change_grid_selection(self):
        self.m_current_grid = self.comboBox_gridSelectorM.currentIndex()
        self.cfg['viewport']['m_current_grid'] = str(self.m_current_grid)
        self.m_update_tile_selector()

    def m_change_tile_selection(self):
        self.m_current_tile = self.comboBox_tileSelectorM.currentIndex() - 1
        self.cfg['viewport']['m_current_tile'] = str(self.m_current_tile)
        if self.m_current_tile >= 0:
            self.m_current_ov = -1
        elif self.m_current_tile == -1: # no tile selected
            # Select OV 0 by default:
            self.m_current_ov = 0
        self.cfg['viewport']['m_current_ov'] = str(self.m_current_ov)
        self.comboBox_OVSelectorM.blockSignals(True)
        self.comboBox_OVSelectorM.setCurrentIndex(self.m_current_ov + 1)
        self.comboBox_OVSelectorM.blockSignals(False)
        self.m_show_statistics()

    def m_change_ov_selection(self):
        self.m_current_ov = self.comboBox_OVSelectorM.currentIndex() - 1
        self.cfg['viewport']['m_current_ov'] = str(self.m_current_ov)
        if self.m_current_ov >= 0:
            self.m_current_tile = -1
            self.cfg['viewport']['m_current_tile'] = '-1'
            self.comboBox_tileSelectorM.blockSignals(True)
            self.comboBox_tileSelectorM.setCurrentIndex(
                self.m_current_tile + 1)
            self.comboBox_tileSelectorM.blockSignals(False)
            self.m_show_statistics()

    def m_show_statistics(self):
        self.m_selected_plot_slice = None
        self.m_selected_slice_number = None
        if self.m_from_stack:
            self.m_tab_populated = True
            self.m_draw_reslice()
            self.m_draw_plots()
        self.m_draw_histogram()

    def m_reset_view(self):
        canvas = self.reslice_canvas_template.copy()
        self.m_qp.begin(canvas)
        self.m_qp.setBrush(QColor(0, 0, 0))
        self.m_qp.setPen(QColor(255, 255, 255))
        position_rect = QRect(50, 260, 300, 40)
        self.m_qp.drawRect(position_rect)
        self.m_qp.drawText(position_rect,
                         Qt.AlignVCenter | Qt.AlignHCenter,
                         'No reslice image available.')
        self.m_qp.end()
        self.reslice_view.setPixmap(canvas)
        self.plots_view.setPixmap(self.plots_canvas_template)
        self.histogram_view.setPixmap(self.histogram_canvas_template)

    def m_load_selected(self):
        self.m_from_stack = True
        self.radioButton_fromStack.setChecked(True)
        active_tiles = self.gm.get_active_tiles(self.selected_grid)
        if self.selected_tile in active_tiles:
            self.selected_tile = active_tiles.index(self.selected_tile)
        else:
            self.selected_tile = None
        if ((self.selected_grid is not None)
            and (self.selected_tile is not None)):
            self.m_current_grid = self.selected_grid
            self.m_current_tile = self.selected_tile
            self.comboBox_gridSelectorM.blockSignals(True)
            self.comboBox_gridSelectorM.setCurrentIndex(self.selected_grid)
            self.comboBox_gridSelectorM.blockSignals(False)
            self.m_update_tile_selector(self.selected_tile)
            self.m_current_ov = -1
            self.comboBox_OVSelectorM.blockSignals(True)
            self.comboBox_OVSelectorM.setCurrentIndex(0)
            self.comboBox_OVSelectorM.blockSignals(False)

        elif self.selected_ov is not None:
            self.m_current_ov = self.selected_ov
            self.comboBox_OVSelectorM.blockSignals(True)
            self.comboBox_OVSelectorM.setCurrentIndex(self.sv_current_ov + 1)
            self.comboBox_OVSelectorM.blockSignals(False)
            self.m_current_tile = -1
            self.comboBox_tileSelectorM.blockSignals(True)
            self.comboBox_tileSelectorM.setCurrentIndex(0)
            self.comboBox_tileSelectorM.blockSignals(False)
        else:
            self.m_reset_view()

        # Switch to Monitoring tab:
        self.tabWidget.setCurrentIndex(2)
        QApplication.processEvents()
        self.m_show_statistics()

    def m_draw_reslice(self):
        filename = None
        if self.m_current_ov >= 0:
            # get current data:
            filename = (self.cfg['acq']['base_dir']
                        + '\\workspace\\reslices\\r_OV'
                        + str(self.m_current_ov).zfill(utils.OV_DIGITS)
                        + '.png')
        elif self.m_current_tile >= 0:
            active_tiles = self.gm.get_active_tiles(self.m_current_grid)
            if self.m_current_tile < len(active_tiles):
                tile_number = active_tiles[self.m_current_tile]
                tile_key = ('g' + str(self.m_current_grid).zfill(utils.GRID_DIGITS)
                            + '_t' + str(tile_number).zfill(utils.TILE_DIGITS))
                filename = (self.cfg['acq']['base_dir']
                            + '\\workspace\\reslices\\r_' + tile_key + '.png')
            else:
                filename = None
        canvas = self.reslice_canvas_template.copy()
        if filename is not None and os.path.isfile(filename):
            current_reslice = QPixmap(filename)
            self.m_qp.begin(canvas)
            self.m_qp.setPen(QColor(0, 0, 0))
            self.m_qp.setBrush(QColor(0, 0, 0))
            self.m_qp.drawRect(QRect(30, 260, 340, 40))
            h = current_reslice.height()
            if h > 500:
                # Crop it to last 500:
                rect = QRect(0, h-500, 400, 500)
                current_reslice = current_reslice.copy(rect);
                h = 500
            self.m_qp.drawPixmap(0, 0, current_reslice)
            # Draw red line on currently selected slice:
            if self.m_selected_slice_number is not None:
                most_recent_slice = int(self.cfg['acq']['slice_counter'])
                self.m_qp.setPen(QColor(255, 0, 0))
                slice_y = most_recent_slice - self.m_selected_slice_number
                self.m_qp.drawLine(0, h - slice_y,
                                   400, h - slice_y)

            self.m_qp.setPen(QColor(255, 255, 255))
            if self.m_current_ov >= 0:
                self.m_qp.drawText(260, 523, 'OV ' + str(self.m_current_ov))
            else:
                self.m_qp.drawText(260, 523,
                    'Tile ' + str(self.m_current_grid)
                    + '.' + str(tile_number))
            self.m_qp.drawText(260, 543, 'Showing past ' + str(h) + ' slices')
            self.m_qp.end()
            self.reslice_view.setPixmap(canvas)
        else:
            # Clear reslice canvas:
            self.m_qp.begin(canvas)
            self.m_qp.setBrush(QColor(0, 0, 0))
            self.m_qp.setPen(QColor(255, 255, 255))
            position_rect = QRect(50, 260, 300, 40)
            self.m_qp.drawRect(position_rect)
            self.m_qp.drawText(position_rect,
                               Qt.AlignVCenter | Qt.AlignHCenter,
                               'No reslice image available.')
            self.m_qp.end()
            self.reslice_view.setPixmap(canvas)
            self.m_tab_populated = False

    def m_draw_plots(self):
        x_delta = 3
        # y coordinates for x-axes:
        mean_y_offset = 60
        mean_diff_y_offset = 206
        stddev_y_offset = 352
        stddev_diff_y_offset = 498
        slice_number_list = []
        mean_list = []
        stddev_list = []
        filename = None
        if self.m_current_ov >= 0:
            # get current data:
            filename = (self.cfg['acq']['base_dir']
                        + '\\meta\\stats\\OV'
                        + str(self.m_current_ov).zfill(utils.OV_DIGITS)
                        + '.dat')
        elif self.m_current_tile >= 0:
            active_tiles = self.gm.get_active_tiles(self.m_current_grid)
            if self.m_current_tile < len(active_tiles):
                tile_number = active_tiles[self.m_current_tile]
                tile_key = ('g' + str(self.m_current_grid).zfill(utils.GRID_DIGITS)
                            + '_t' + str(tile_number).zfill(utils.TILE_DIGITS))
                filename = (self.cfg['acq']['base_dir']
                            + '\\meta\\stats\\' + tile_key + '.dat')
            else:
                filename = None
        if filename is not None and os.path.isfile(filename):
            with open(filename, 'r') as file:
                for line in file:
                    values_str = line.split(';')
                    values = [x for x in values_str]
                    slice_number_list.append(int(values[0]))
                    mean_list.append(float(values[1]))
                    stddev_list.append(float(values[2]))
            # Shorten the lists to last 150 entries if larger than 150:
            N = len(mean_list)
            if N > 165:
                mean_list = mean_list[-165:]
                stddev_list = stddev_list[-165:]
                slice_number_list = slice_number_list[-165:]
                N = 165
            # Get average of the entries
            mean_avg = mean(mean_list)
            stddev_avg = mean(stddev_list)

            mean_diff_list = []
            stddev_diff_list = []

            for i in range(0, N-1):
                mean_diff_list.append(mean_list[i + 1] - mean_list[i])
                stddev_diff_list.append(stddev_list[i + 1] - stddev_list[i])

            max_mean_delta = 3
            for entry in mean_list:
                delta = abs(entry - mean_avg)
                if delta > max_mean_delta:
                    max_mean_delta = delta
            mean_scaling = 60 / max_mean_delta
            max_stddev_delta = 1
            for entry in stddev_list:
                delta = abs(entry - stddev_avg)
                if delta > max_stddev_delta:
                    max_stddev_delta = delta
            stddev_scaling = 60 / max_stddev_delta
            max_mean_diff = 3
            for entry in mean_diff_list:
                if abs(entry) > max_mean_diff:
                    max_mean_diff = abs(entry)
            mean_diff_scaling = 60 / max_mean_diff
            max_stddev_diff = 1
            for entry in stddev_diff_list:
                if abs(entry) > max_stddev_diff:
                    max_stddev_diff = abs(entry)
            stddev_diff_scaling = 60 / max_stddev_diff

            canvas = self.plots_canvas_template.copy()
            self.m_qp.begin(canvas)

            # Selected slice:
            if self.m_selected_plot_slice is not None:
                max_slices = len(slice_number_list)
                if self.m_selected_plot_slice >= max_slices:
                    self.m_selected_slice_number = slice_number_list[-1]
                    self.m_selected_plot_slice = max_slices - 1
                else:
                    self.m_selected_slice_number = slice_number_list[
                        self.m_selected_plot_slice]
                pen = QPen(QColor(105, 105, 105))
                pen.setWidth(1)
                pen.setStyle(Qt.DashLine)
                self.m_qp.setPen(pen)
                self.m_qp.drawLine(4 + self.m_selected_plot_slice * 3, 0,
                                   4 + self.m_selected_plot_slice * 3, 558)
                # Slice:
                self.m_qp.drawText(500, 550, 'Slice '
                    + str(self.m_selected_slice_number))
                # Data for selected slice:
                if self.m_selected_plot_slice < len(mean_list):
                    sel_mean = '{0:.2f}'.format(
                        mean_list[self.m_selected_plot_slice])
                else:
                    sel_mean = '-'
                if self.m_selected_plot_slice < len(mean_diff_list):
                    sel_mean_diff = '{0:.2f}'.format(
                        mean_diff_list[self.m_selected_plot_slice])
                else:
                    sel_mean_diff = '-'
                if self.m_selected_plot_slice < len(stddev_list):
                    sel_stddev = '{0:.2f}'.format(
                        stddev_list[self.m_selected_plot_slice])
                else:
                    sel_stddev = '-'
                if self.m_selected_plot_slice < len(stddev_diff_list):
                    sel_stddev_diff = '{0:.2f}'.format(
                        stddev_diff_list[self.m_selected_plot_slice])
                else:
                    sel_stddev_diff = '-'

                self.m_qp.drawText(500, 30, sel_mean)
                self.m_qp.drawText(500, 176, sel_mean_diff)
                self.m_qp.drawText(500, 322, sel_stddev)
                self.m_qp.drawText(500, 468, sel_stddev_diff)

            # Show axis means:
            self.m_qp.setPen(QColor(25, 25, 112))
            self.m_qp.drawText(523, 64, '{0:.2f}'.format(mean_avg))
            self.m_qp.setPen(QColor(139, 0, 0))
            self.m_qp.drawText(523, 356, '{0:.2f}'.format(stddev_avg))

            pen = QPen(QColor(25, 25, 112))
            pen.setWidth(1)
            self.m_qp.setPen(pen)
            previous_entry = -1
            x_pos = 4
            for entry in mean_list:
                if previous_entry > -1:
                    d1 = (previous_entry - mean_avg) * mean_scaling
                    d1 = utils.fit_in_range(d1, -60, 60)
                    d2 = (entry - mean_avg) * mean_scaling
                    d2 = utils.fit_in_range(d2, -60, 60)
                    self.m_qp.drawLine(x_pos, mean_y_offset - d1,
                                       x_pos + x_delta, mean_y_offset - d2)
                    x_pos += x_delta
                previous_entry = entry

            pen = QPen(QColor(119, 0, 0))
            pen.setWidth(1)
            self.m_qp.setPen(pen)
            previous_entry = -1
            x_pos = 4
            for entry in stddev_list:
                if previous_entry > -1:
                    d1 = (previous_entry - stddev_avg) * stddev_scaling
                    d1 = utils.fit_in_range(d1, -60, 60)
                    d2 = (entry - stddev_avg) * stddev_scaling
                    d2 = utils.fit_in_range(d2, -60, 60)
                    self.m_qp.drawLine(x_pos, stddev_y_offset - d1,
                                       x_pos + x_delta, stddev_y_offset - d2)
                    x_pos += x_delta
                previous_entry = entry

            pen = QPen(QColor(25, 25, 112))
            pen.setWidth(1)
            self.m_qp.setPen(pen)
            x_pos = 4
            for i in range(1, N-1):
                d1 = mean_diff_list[i-1] * mean_diff_scaling
                d1 = utils.fit_in_range(d1, -60, 60)
                d2 = mean_diff_list[i] * mean_diff_scaling
                d2 = utils.fit_in_range(d2, -60, 60)
                self.m_qp.drawLine(x_pos, mean_diff_y_offset - d1,
                                   x_pos + x_delta, mean_diff_y_offset - d2)
                x_pos += x_delta

            pen = QPen(QColor(119, 0, 0))
            pen.setWidth(1)
            self.m_qp.setPen(pen)
            x_pos = 4
            for i in range(1, N-1):
                d1 = stddev_diff_list[i-1] * stddev_diff_scaling
                d1 = utils.fit_in_range(d1, -60, 60)
                d2 = stddev_diff_list[i] * stddev_diff_scaling
                d2 = utils.fit_in_range(d2, -60, 60)
                self.m_qp.drawLine(x_pos, stddev_diff_y_offset - d1,
                                   x_pos + x_delta, stddev_diff_y_offset - d2)
                x_pos += x_delta

            self.m_qp.end()
            self.plots_view.setPixmap(canvas)
        else:
            self.plots_view.setPixmap(self.plots_canvas_template)
            self.m_tab_populated = False

    def m_draw_histogram(self):
        base_dir = self.cfg['acq']['base_dir']
        selected_file = ''
        slice_number = None
        if self.m_from_stack:
            success = False
            path = ''
            if self.m_current_ov >= 0:
                path = (base_dir + '\\overviews\\ov'
                        + str(self.m_current_ov).zfill(utils.OV_DIGITS))

            elif self.m_current_tile >= 0:
                active_tiles = self.gm.get_active_tiles(self.m_current_grid)
                if self.m_current_tile < len(active_tiles):
                    tile_number = active_tiles[self.m_current_tile]
                    path = (base_dir + '\\tiles\\g'
                            + str(self.m_current_grid).zfill(utils.GRID_DIGITS)
                            + '\\t' + str(tile_number).zfill(utils.TILE_DIGITS))
                else:
                    path = None

            if path is not None and os.path.exists(path):
                filenames = next(os.walk(path))[2]
                if len(filenames) > 165:
                    filenames = filenames[-165:]
                if filenames:
                    if self.m_selected_slice_number is None:
                        selected_file = path + '\\' + filenames[-1]
                    else:
                        slice_number_str = (
                            's' + str(self.m_selected_slice_number).zfill(
                                utils.SLICE_DIGITS))
                        for filename in filenames:
                            if slice_number_str in filename:
                                selected_file = path + '\\' + filename
                                break

        else:
            # Use current image in SmartSEM
            selected_file = base_dir + '\\workspace\\current_frame.tif'
            self.sem.save_frame(selected_file)
            self.m_reset_view()
            self.m_tab_populated = False

        if os.path.isfile(selected_file):
            img = np.array(Image.open(selected_file))
            success = True

        canvas = self.histogram_canvas_template.copy()
        if success:
            # calculate mean and SD:
            mean = np.mean(img)
            stddev = np.std(img)
            #Full histogram:
            hist, bin_edges = np.histogram(img, 256, [0, 256])

            hist_max = hist.max()
            peak = -1
            self.m_qp.begin(canvas)
            self.m_qp.setPen(QColor(25, 25, 112))

            for x in range(0, 256):
                gv_normalized = hist[x]/hist_max
                if gv_normalized == 1:
                    peak = x
                self.m_qp.drawLine(x + 11, 160,
                                   x + 11, 160 - gv_normalized * 147)
            if self.m_from_stack:
                try:
                    idx = selected_file.rfind('s')
                    slice_number = int(selected_file[idx+1:idx+6])
                except:
                    slice_number = -1
                if self.m_current_ov >= 0:
                    self.m_qp.drawText(
                        280, 50,
                        'OV ' + str(self.m_current_ov)
                        + ', slice ' + str(slice_number))
                elif self.m_current_grid >= 0:
                    self.m_qp.drawText(
                        280, 50,
                        'Tile ' + str(self.m_current_grid)
                        + '.' + str(tile_number)
                        + ', slice ' + str(slice_number))

            else:
                self.m_qp.drawText(280, 50, 'Current SmartSEM image')
            self.m_qp.drawText(345, 90, '{0:.2f}'.format(mean))
            self.m_qp.drawText(345, 110, '{0:.2f}'.format(stddev))
            self.m_qp.drawText(345, 130, str(peak))
            self.m_qp.drawText(345, 150, str(hist_max))

            self.m_qp.end()
            self.histogram_view.setPixmap(canvas)
        else:
            self.m_qp.begin(canvas)
            self.m_qp.setPen(QColor(25, 25, 112))
            self.m_qp.drawText(50, 90, 'No image found for selected source   ')
            self.m_qp.end()
            self.histogram_view.setPixmap(canvas)
