# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module controls the Viewport window, which consists of three tabs:
    - the Viewport (methods/attributes concerning the Viewport tab are
                    tagged with 'vp_')
    - the Slice-by-Slice Viewer (sv_),
    - the Reslice/Statistics tab (m_ for 'monitoring')
"""

import os
import shutil
import yaml
import numpy as np
import threading
import scipy
from time import time, sleep
from PIL import Image
from math import log, sqrt, sin, cos, radians
from statistics import mean

from PyQt5.uic import loadUi
from PyQt5.QtWidgets import QWidget, QApplication, QMessageBox, QMenu
from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont, QIcon, QPen, \
                        QBrush, QKeyEvent, QFontMetrics
from PyQt5.QtCore import Qt, QObject, QRect, QPoint, QSize

import utils
import acq_func
from viewport_dlg_windows import StubOVDlg, FocusGradientTileSelectionDlg, \
                                 GridRotationDlg, TemplateRotationDlg, ImportImageDlg, \
                                 AdjustImageDlg, DeleteImageDlg
from main_controls_dlg_windows import MotorStatusDlg


class Viewport(QWidget):

    def __init__(self, config, sem, stage, coordinate_system,
                 ov_manager, grid_manager, imported_images,
                 autofocus, acquisition, img_inspector,
                 main_controls_trigger, template_manager):
        super().__init__()
        self.cfg = config
        self.sem = sem
        self.stage = stage
        self.cs = coordinate_system
        self.gm = grid_manager
        self.ovm = ov_manager
        self.tm = template_manager
        self.imported = imported_images
        self.autofocus = autofocus
        self.acq = acquisition
        self.img_inspector = img_inspector
        self.main_controls_trigger = main_controls_trigger

        # Set Viewport zoom parameters depending on which stage is used for XY
        if self.stage.use_microtome_xy:
            self.VP_ZOOM = utils.VP_ZOOM_MICROTOME_STAGE
        else:
            self.VP_ZOOM = utils.VP_ZOOM_SEM_STAGE
        # Set limits for viewport panning.
        self.VC_MIN_X, self.VC_MAX_X, self.VC_MIN_Y, self.VC_MAX_Y = (
            self.vp_dx_dy_range())

        # Shared control variables
        self.busy = False    # acquisition or other operation in progress
        self.active = True   # Viewport windows is active.
        # for mouse operations (dragging, measuring)
        self.doubleclick_registered = False
        self.zooming_in_progress = False
        self.drag_origin = (0, 0)
        self.drag_current = (0, 0)
        self.fov_drag_active = False
        self.tile_paint_mode_active = False
        self.measure_p1 = (None, None)
        self.measure_p2 = (None, None)
        self.measure_complete = False
        self.help_panel_visible = False
        self.stub_ov_centre = [None, None]

        # Set up trigger and queue to update viewport from the
        # acquisition thread or dialog windows.
        self.viewport_trigger = utils.Trigger()
        self.viewport_trigger.signal.connect(self._process_signal)

        self._load_gui()
        # Initialize viewport tabs:
        self._vp_initialize()  # Viewport
        self._sv_initialize()  # Slice-by-slice viewer
        self._m_initialize()   # Monitoring tab
        self.setMouseTracking(True)

        self.selected_template = False
        self.selected_grid, self.selected_tile = None, None
        self.selected_ov = None
        self.selected_imported = None

    def save_to_cfg(self):
        """Save viewport configuration to ConfigParser object."""
        self.cfg['viewport']['vp_current_grid'] = str(self.vp_current_grid)
        self.cfg['viewport']['vp_current_ov'] = str(self.vp_current_ov)
        self.cfg['viewport']['vp_tile_preview_mode'] = str(
            self.vp_tile_preview_mode)
        self.cfg['viewport']['show_labels'] = str(self.show_labels)
        self.cfg['viewport']['show_axes'] = str(self.show_axes)
        self.cfg['viewport']['show_stub_ov'] = str(self.show_stub_ov)
        self.cfg['viewport']['show_imported'] = str(self.show_imported)
        self.cfg['viewport']['show_native_resolution'] = str(
            self.show_native_res)
        self.cfg['viewport']['show_saturated_pixels'] = str(
            self.show_saturated_pixels)

        self.cfg['viewport']['sv_current_grid'] = str(self.sv_current_grid)
        self.cfg['viewport']['sv_current_tile'] = str(self.sv_current_tile)
        self.cfg['viewport']['sv_current_ov'] = str(self.sv_current_ov)

        self.cfg['viewport']['m_current_grid'] = str(self.m_current_grid)
        self.cfg['viewport']['m_current_tile'] = str(self.m_current_tile)
        self.cfg['viewport']['m_current_ov'] = str(self.m_current_ov)

    def _load_gui(self):
        loadUi('..\\gui\\viewport.ui', self)
        self.setWindowIcon(QIcon('..\\img\\icon_16px.ico'))
        self.setWindowTitle('SBEMimage - Viewport')
        # Display current settings:
        #self.setFixedSize(self.size())
        self.move(20, 20)
        # Deactivate buttons for imaging if in simulation mode
        if self.sem.simulation_mode:
            self.pushButton_refreshOVs.setEnabled(False)
            self.pushButton_acquireStubOV.setEnabled(False)
            self.checkBox_showStagePos.setEnabled(False)
        # Detect if tab is changed
        self.tabWidget.currentChanged.connect(self.tab_changed)

    def tab_changed(self):
        if self.tabWidget.currentIndex() == 2:  # Acquisition monitor
            # Update motor status
            self.m_show_motor_status()

    def restrict_gui(self, b):
        """Disable several GUI elements while SBEMimage is busy, for example
        when an acquisition is running."""
        self.busy = b
        b ^= True
        self.pushButton_refreshOVs.setEnabled(b)
        self.pushButton_acquireStubOV.setEnabled(b)
        if not b:
            self.radioButton_fromStack.setChecked(not b)
        self.radioButton_fromSEM.setEnabled(b)

    def update_grids(self):
        """Update the grid selectors after grid is added or deleted."""
        self.vp_current_grid = -1
        if self.sv_current_grid >= self.gm.number_grids:
            self.sv_current_grid = self.gm.number_grids - 1
            self.sv_current_tile = -1
        if self.m_current_grid >= self.gm.number_grids:
            self.m_current_grid = self.gm.number_grids - 1
            self.m_current_tile = -1
        self.vp_update_grid_selector()
        self.sv_update_grid_selector()
        self.sv_update_tile_selector()
        self.m_update_grid_selector()
        self.m_update_tile_selector()

    def update_ov(self):
        """Update the overview selectors after overview is added or deleted."""
        self.vp_current_ov = -1
        self.vp_update_ov_selector()
        self.sv_update_ov_selector()
        self.m_update_ov_selector()

    def _update_measure_buttons(self):
        """Display the measuring tool buttons as active or inactive."""
        if self.vp_measure_active:
            self.pushButton_measureViewport.setIcon(
                QIcon('..\\img\\measure-active.png'))
            self.pushButton_measureViewport.setIconSize(QSize(16, 16))
        else:
            self.pushButton_measureViewport.setIcon(
                QIcon('..\\img\\measure.png'))
            self.pushButton_measureViewport.setIconSize(QSize(16, 16))
        if self.sv_measure_active:
            self.pushButton_measureSliceViewer.setIcon(
                QIcon('..\\img\\measure-active.png'))
            self.pushButton_measureSliceViewer.setIconSize(QSize(16, 16))
        else:
            self.pushButton_measureSliceViewer.setIcon(
                QIcon('..\\img\\measure.png'))
            self.pushButton_measureSliceViewer.setIconSize(QSize(16, 16))

    def _draw_rectangle(self, qp, point0, point1, color, line_style=Qt.SolidLine):
        x0, y0 = point0
        x1, y1 = point1
        if x0 > x1:
            x1, x0 = x0, x1
        if y0 > y1:
            y1, y0 = y0, y1
        w = x1 - x0
        h = y1 - y0
        qp.setPen(QPen(QColor(*color), 1, line_style))
        qp.setBrush(QColor(255, 255, 255, 0))
        qp.drawRect(x0, y0, w, h)

    def _draw_measure_labels(self, qp):
        """Draw measure labels QPainter qp. qp must be active when calling this
        method."""
        def draw_measure_point(qp, x, y):
            qp.drawEllipse(QPoint(x, y), 4, 4)
            qp.drawLine(x, y - 10, x, y + 10)
            qp.drawLine(x - 10, y, x + 10, y)

        draw_in_vp = (self.tabWidget.currentIndex() == 0)
        tile_display = (self.sv_current_tile >= 0)

        qp.setPen(QPen(QColor(*utils.COLOUR_SELECTOR[13]), 2, Qt.SolidLine))
        qp.setBrush(QColor(0, 0, 0, 0))
        if self.measure_p1[0] is not None:
            if draw_in_vp:
                p1_x, p1_y = self.cs.convert_d_to_v(self.measure_p1)
            else:
                p1_x, p1_y = self.cs.convert_d_to_sv(
                    self.measure_p1, tile_display)
            draw_measure_point(qp, p1_x, p1_y)
        if self.measure_p2[0] is not None:
            if draw_in_vp:
                p2_x, p2_y = self.cs.convert_d_to_v(self.measure_p2)
            else:
                p2_x, p2_y = self.cs.convert_d_to_sv(
                    self.measure_p2, tile_display)
            draw_measure_point(qp, p2_x, p2_y)

        if self.measure_p2[0] is not None:
            # Draw line between p1 and p2
            qp.drawLine(p1_x, p1_y, p2_x, p2_y)
            distance = sqrt((self.measure_p1[0] - self.measure_p2[0])**2
                            + (self.measure_p1[1] - self.measure_p2[1])**2)
            qp.setPen(QPen(QColor(0, 0, 0), 1, Qt.SolidLine))
            qp.setBrush(QColor(0, 0, 0, 255))
            qp.drawRect(self.cs.vp_width - 80, self.cs.vp_height - 20, 80, 20)
            font = QFont()
            font.setPixelSize(12)
            qp.setFont(font)
            qp.setPen(QPen(QColor(*utils.COLOUR_SELECTOR[13]), 1, Qt.SolidLine))
            if distance < 1:
                qp.drawText(self.cs.vp_width - 75, self.cs.vp_height - 5,
                            str((int(distance * 1000))) + ' nm')
            else:
                qp.drawText(self.cs.vp_width - 75, self.cs.vp_height - 5,
                            '{0:.2f}'.format(distance) + ' µm')

    def grab_viewport_screenshot(self, save_path_filename):
        viewport_screenshot = self.grab()
        viewport_screenshot.save(save_path_filename)

    def show_in_incident_log(self, message):
        """Show the message in the Viewport's incident log
        (in the monitoring tab).
        """
        self.textarea_incidentLog.appendPlainText(message)

    def _process_signal(self):
        """Process signals from the acquisition thread or from dialog windows.
        """
        msg = self.viewport_trigger.queue.get()
        if msg == 'DRAW VP':
            self.vp_draw()
        elif msg == 'DRAW VP NO LABELS':
            self.vp_draw(suppress_labels=True, suppress_previews=True)
        elif msg == 'UPDATE XY':
            self.main_controls_trigger.transmit(msg)
        elif msg == 'STATUS IDLE':
            self.main_controls_trigger.transmit(msg)
        elif msg == 'STATUS BUSY STUB':
            self.main_controls_trigger.transmit(msg)
        elif msg == 'STATUS BUSY OV':
            self.main_controls_trigger.transmit(msg)
        elif msg.startswith('ACQ IND OV'):
            self.vp_toggle_ov_acq_indicator(
                int(msg[len('ACQ IND OV'):]))
        elif msg == 'MANUAL MOVE SUCCESS':
            self._vp_manual_stage_move_success(True)
        elif msg == 'MANUAL MOVE FAILURE':
            self._vp_manual_stage_move_success(False)
        elif msg == 'REFRESH OV SUCCESS':
            self._vp_overview_acq_success(True)
        elif msg == 'REFRESH OV FAILURE':
            self._vp_overview_acq_success(False)
        elif msg == 'STUB OV SUCCESS':
            self._vp_stub_overview_acq_success(True)
        elif msg == 'STUB OV FAILURE':
            self._vp_stub_overview_acq_success(False)
        else:
            self._add_to_main_log(msg)

    def _add_to_main_log(self, msg):
        """Add entry to the log in the main window via main_controls_trigger."""
        self.main_controls_trigger.transmit(utils.format_log_entry(msg))

    def closeEvent(self, event):
        """This overrides the QWidget's closeEvent(). Viewport must be
        deactivated first before the window can be closed."""
        if self.active:
            QMessageBox.information(self, 'Closing Viewport',
                'The Viewport window can only be closed by closing the main '
                'window of the application.', QMessageBox.Ok)
            event.ignore()
        else:
            event.accept()

# ======================= Below: event-handling methods ========================

    def setMouseTracking(self, flag):
        """Recursively activate or deactive mouse tracking in a widget."""
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
        px, py = p.x() - utils.VP_MARGIN_X, p.y() - utils.VP_MARGIN_Y
        mouse_pos_within_viewer = (
            px in range(self.cs.vp_width) and py in range(self.cs.vp_height))
        mouse_pos_within_plot_area = (
            px in range(445, 940) and py in range(22, 850))

        # --- MagC --- #
        self.control_down_at_mouse_press = (
            QApplication.keyboardModifiers() == Qt.ControlModifier)
        # keep in memory the origin when button pressed
        self.drag_origin_at_press_event = px, py
        #--------------#
        if ((event.button() == Qt.LeftButton)
            and (self.tabWidget.currentIndex() < 2)
            and mouse_pos_within_viewer):

            self.selected_grid, self.selected_tile = \
                self._vp_grid_tile_mouse_selection(px, py)
            self.selected_ov = self._vp_ov_mouse_selection(px, py)
            self.selected_imported = (
                self._vp_imported_img_mouse_selection(px, py))
            
            # Disable self.selected_template for now (causing runtime warnings)
            # TODO (Benjamin / Philipp): look into this
            # self.selected_template = self._vp_template_mouse_selection(px, py)
            
            # Shift pressed in first tab? Toggle active tiles.
            if ((self.tabWidget.currentIndex() == 0)
               and (QApplication.keyboardModifiers() == Qt.ShiftModifier)):
                if (self.vp_current_grid >= -2
                   and self.selected_grid is not None
                   and self.selected_tile is not None):
                    if self.busy:
                        user_reply = QMessageBox.question(self,
                            'Confirm tile activation',
                            'Stack acquisition in progress! Please confirm '
                            'that you want to activate/deactivate this tile. '
                            'The new selection will take effect after imaging '
                            'of the current slice is completed.',
                            QMessageBox.Ok | QMessageBox.Cancel)
                        if user_reply == QMessageBox.Ok:
                            new_tile_status = self.gm[
                                self.selected_grid].toggle_active_tile(
                                self.selected_tile)
                            if self.autofocus.tracking_mode == 1:
                                self.gm[
                                    self.selected_grid][
                                    self.selected_tile].autofocus_active ^= True
                            self._add_to_main_log(
                                f'CTRL: Tile {self.selected_grid}.'
                                f'{self.selected_tile}{new_tile_status}')
                            self.vp_update_after_active_tile_selection()
                            # Make sure folder exists:
                            self.main_controls_trigger.transmit(
                                'ADD TILE FOLDER')
                    else:
                        # If no acquisition in progress,
                        # first toggle current tile.
                        self.gm[self.selected_grid].toggle_active_tile(
                            self.selected_tile)
                        if self.autofocus.tracking_mode == 1:
                            self.gm[self.selected_grid][
                                    self.selected_tile].autofocus_active ^= True
                        self.vp_draw()
                        # Then enter paint mode until mouse button released.
                        self.tile_paint_mode_active = True

            # Check if Ctrl key is pressed -> Move OV
            elif ((self.tabWidget.currentIndex() == 0)
                and (QApplication.keyboardModifiers() == Qt.ControlModifier)
                and self.vp_current_ov >= -2
                and not self.busy):
                if self.selected_ov is not None and self.selected_ov >= 0:
                    self.ov_drag_active = True
                    self.drag_origin = (px, py)
                    self.stage_pos_backup = (
                        self.ovm[self.selected_ov].centre_sx_sy)
                else:
                    # Draw OV
                    self.ov_draw_active = True
                    self.drag_origin = px, py

            # Check if Alt key is pressed -> Move grid
            elif ((self.tabWidget.currentIndex() == 0)
                and (QApplication.keyboardModifiers() == Qt.AltModifier)
                and self.vp_current_grid >= -2
                and not self.busy):
                if self.selected_grid is not None and self.selected_grid >= 0:
                    self.grid_drag_active = True
                    self.drag_origin = px, py
                    # Save coordinates in case user wants to undo
                    self.stage_pos_backup = (
                        self.gm[self.selected_grid].origin_sx_sy)
                else:
                    # Draw grid
                    self.grid_draw_active = True
                    self.drag_origin = px, py

            # Check if ctrl+shift key is pressed -> Move template
            elif ((self.tabWidget.currentIndex() == 0)
                  and (QApplication.keyboardModifiers() == (Qt.ControlModifier | Qt.ShiftModifier))
                  and not self.busy):
                if self.selected_template:
                    self.template_drag_active = True
                    self.drag_origin = px, py
                    # Save coordinates in case user wants to undo
                    self.stage_pos_backup = self.tm.template.origin_sx_sy
                else:
                    # Draw template
                    self.template_draw_active = True
                    self.drag_origin = px, py

            # Check if Ctrl + Alt keys are pressed -> Move imported image
            elif ((self.tabWidget.currentIndex() == 0)
                and (QApplication.keyboardModifiers()
                    == (Qt.ControlModifier | Qt.AltModifier))):
                if self.selected_imported is not None:
                    self.imported_img_drag_active = True
                    self.drag_origin = px, py
                    # Save coordinates in case user wants to undo
                    self.stage_pos_backup = (
                        self.imported[self.selected_imported].centre_sx_sy)
            # No key pressed -> Panning
            elif (QApplication.keyboardModifiers() == Qt.NoModifier):
                # Move the viewport's FOV
                self.fov_drag_active = True
                # For now, disable showing saturated pixels (too slow)
                if self.show_saturated_pixels:
                    self.checkBox_showSaturated.setChecked(False)
                    self.show_saturated_pixels = False
                self.drag_origin = (p.x() - utils.VP_MARGIN_X,
                                    p.y() - utils.VP_MARGIN_Y)
        # Now check right mouse button for context menus and measuring tool
        if ((event.button() == Qt.RightButton)
                and (self.tabWidget.currentIndex() < 2)
                and mouse_pos_within_viewer):
            if self.tabWidget.currentIndex() == 0:
                if self.vp_measure_active:
                    self._vp_set_measure_point(px, py)
                else:
                    self.vp_show_context_menu(p)
            elif self.tabWidget.currentIndex() == 1:
                if self.sv_measure_active:
                    self._sv_set_measure_point(px, py)
                else:
                    self.sv_show_context_menu(p)

        # Left mouse click in statistics tab to select a slice
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
        self.doubleclick_registered = True

    def mouseMoveEvent(self, event):
        p = event.pos()
        px, py = p.x() - utils.VP_MARGIN_X, p.y() - utils.VP_MARGIN_Y
        # Show current stage and SEM coordinates at mouse position
        mouse_pos_within_viewer = (
            px in range(self.cs.vp_width) and py in range(self.cs.vp_height))
        if ((self.tabWidget.currentIndex() == 0)
                and mouse_pos_within_viewer):
            sx, sy = self.cs.convert_mouse_to_s((px, py))
            dx, dy = self.cs.convert_s_to_d([sx, sy])
            self.label_mousePos.setText(
                'Stage: {0:.1f}, '.format(sx)
                + '{0:.1f}; '.format(sy)
                + 'SEM: {0:.1f}, '.format(dx)
                + '{0:.1f}'.format(dy))
        else:
            self.label_mousePos.setText('-')

        # Move grid/OV or FOV:
        if self.grid_drag_active:
            # Change cursor appearence
            self.setCursor(Qt.SizeAllCursor)
            drag_vector = (px - self.drag_origin[0],
                           py - self.drag_origin[1])
            # Update drag origin
            self.drag_origin = px, py
            self._vp_reposition_grid(drag_vector)
        elif self.ov_drag_active:
            self.setCursor(Qt.SizeAllCursor)
            drag_vector = (px - self.drag_origin[0],
                           py - self.drag_origin[1])
            self.drag_origin = px, py
            self._vp_reposition_ov(drag_vector)
        elif self.template_drag_active:
            self.setCursor(Qt.SizeAllCursor)
            drag_vector = (px - self.drag_origin[0],
                           py - self.drag_origin[1])
            self.drag_origin = px, py
            self._vp_reposition_template(drag_vector)
        elif self.imported_img_drag_active:
            self.setCursor(Qt.SizeAllCursor)
            drag_vector = (px - self.drag_origin[0],
                           py - self.drag_origin[1])
            self.drag_origin = px, py
            self._vp_reposition_imported_img(drag_vector)
        elif self.fov_drag_active:
            self.setCursor(Qt.SizeAllCursor)
            drag_vector = self.drag_origin[0] - px, self.drag_origin[1] - py
            self.drag_origin = px, py
            if self.tabWidget.currentIndex() == 0:
                self._vp_shift_fov(drag_vector)
            if self.tabWidget.currentIndex() == 1:
                self._sv_shift_fov(drag_vector)
        elif self.tile_paint_mode_active:
            # Toggle tiles in "painting" mode.
            prev_selected_grid = self.selected_grid
            prev_selected_tile = self.selected_tile
            self.selected_grid, self.selected_tile = (
                self._vp_grid_tile_mouse_selection(px, py))
            # If mouse has moved to a new tile, toggle it
            if (self.selected_grid is not None
                and self.selected_tile is not None):
                if ((self.selected_grid == prev_selected_grid
                     and self.selected_tile != prev_selected_tile)
                     or self.selected_grid != prev_selected_grid):
                        self.gm[self.selected_grid].toggle_active_tile(
                            self.selected_tile)
                        if self.autofocus.tracking_mode == 1:
                            self.gm[self.selected_grid][
                                    self.selected_tile].autofocus_active ^= True
                        self.vp_draw()
            else:
                # Disable paint mode when mouse moved beyond grid edge.
                self.tile_paint_mode_active = False
        elif self.grid_draw_active:
            self.drag_current = px, py
            self.vp_draw()
        elif self.ov_draw_active:
            self.drag_current = px, py
            self.vp_draw()
        elif self.template_draw_active:
            self.drag_current = px, py
            self.vp_draw()

        elif ((self.tabWidget.currentIndex() == 0)
            and mouse_pos_within_viewer
            and self.vp_measure_active):
                # Change cursor appearence
                self.setCursor(Qt.CrossCursor)
                if self.measure_p1[0] is not None and not self.measure_complete:
                    self._vp_set_measure_point(px, py)
        elif ((self.tabWidget.currentIndex() == 1)
            and mouse_pos_within_viewer
            and self.sv_measure_active):
                self.setCursor(Qt.CrossCursor)
                if self.measure_p1[0] is not None and not self.measure_complete:
                    self._sv_set_measure_point(px, py)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if not self.vp_measure_active:
            self.setCursor(Qt.ArrowCursor)
        # Process doubleclick
        if self.doubleclick_registered:
            p = event.pos()
            px, py = p.x() - utils.VP_MARGIN_X, p.y() - utils.VP_MARGIN_Y
            if px in range(self.cs.vp_width) and py in range(self.cs.vp_height):
                if self.tabWidget.currentIndex() == 0:
                    self._vp_mouse_zoom(px, py, 2)
                elif self.tabWidget.currentIndex() == 1:
                    # Disable native resolution
                    self.sv_disable_native_resolution()
                    # Zoom in:
                    self._sv_mouse_zoom(px, py, 2)
            self.doubleclick_registered = False

        elif (event.button() == Qt.LeftButton):
            if self.grid_drag_active:
                user_reply = QMessageBox.question(
                    self, 'Repositioning grid',
                    'You have moved the selected grid. Please '
                    'confirm the new position. Click "Cancel" to undo.',
                    QMessageBox.Ok | QMessageBox.Cancel)
                if user_reply == QMessageBox.Cancel:
                    # Restore origin coordinates
                    self.gm[self.selected_grid].origin_sx_sy = (
                        self.stage_pos_backup)
                else:
                    self.ovm.update_all_debris_detections_areas(self.gm)
                    # ------ MagC ------#
                    if self.sem.magc_mode:
                        # in magc_mode, save the new grid location back
                        # to the source magc sections
                        self.gm.update_source_ROIs_from_grids()
                        # deactivate roi_mode because grid manually moved
                        self.gm.magc_roi_mode = False
                    #------------------------#

            if self.ov_drag_active:
                user_reply = QMessageBox.question(
                    self, 'Repositioning overview',
                    'You have moved the selected overview. Please '
                    'confirm the new position. Click "Cancel" to undo.',
                    QMessageBox.Ok | QMessageBox.Cancel)
                if user_reply == QMessageBox.Cancel:
                    # Restore centre coordinates
                    self.ovm[self.selected_ov].centre_sx_sy = (
                        self.stage_pos_backup)
                else:
                    # Remove current preview image from file list
                    self.ovm[self.selected_ov].vp_file_path = ''
                    self.ovm.update_all_debris_detections_areas(self.gm)
            if self.template_drag_active:
                self.template_drag_active = False
                user_reply = QMessageBox.question(
                    self, 'Repositioning template',
                    'You have moved the selected template. Please '
                    'confirm the new position. Click "Cancel" to undo.',
                    QMessageBox.Ok | QMessageBox.Cancel)
                if user_reply == QMessageBox.Cancel:
                    # Restore centre coordinates
                    self.tm.template.origin_sx_sy = self.stage_pos_backup

            if self.grid_draw_active or self.ov_draw_active or self.template_draw_active:
                x0, y0 = self.cs.convert_mouse_to_v(self.drag_origin)
                x1, y1 = self.cs.convert_mouse_to_v(self.drag_current)
                if x0 > x1:
                    x1, x0 = x0, x1
                if y0 > y1:
                    y1, y0 = y0, y1
                w = x1 - x0
                h = y1 - y0

            if self.grid_draw_active:
                if h != 0 and w != 0:
                    self.grid_draw_active = False
                    self.gm.draw_grid(x0, y0, w, h)
                    self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')
            if self.ov_draw_active:
                if h != 0 and w != 0:
                    self.ov_draw_active = False
                    self.ovm.draw_overview(x0, y0, w, h)
                    self.main_controls_trigger.transmit('OV SETTINGS CHANGED')
            if self.template_draw_active:
                if h != 0 and w != 0:
                    self.template_draw_active = False
                    self.tm.draw_template(x0, y0, w, h)
                    self.main_controls_trigger.transmit('TEMPLATE SETTINGS CHANGED')

            if self.tile_paint_mode_active:
                self.vp_update_after_active_tile_selection()
            if self.imported_img_drag_active:
                user_reply = QMessageBox.question(
                    self, 'Repositioning imported image',
                    'You have moved the selected imported image. Please '
                    'confirm the new position. Click "Cancel" to undo.',
                    QMessageBox.Ok | QMessageBox.Cancel)
                if user_reply == QMessageBox.Cancel:
                    # Restore centre coordinates
                    self.imported[self.selected_imported].centre_sx_sy = (
                        self.stage_pos_backup)

            if self.gm.magc_mode:
                # checking whether no other action than
                # simple section click was performed
                if not any([
                    self.grid_drag_active,
                    self.ov_drag_active,
                    self.tile_paint_mode_active,
                    self.imported_img_drag_active]):
                    p = event.pos()
                    px = p.x() - utils.VP_MARGIN_X
                    py = p.y() - utils.VP_MARGIN_Y
                    if self.drag_origin_at_press_event == (px, py):
                        if self.control_down_at_mouse_press:
                            if self.selected_grid is not None:
                                self.main_controls_trigger.transmit(
                                    'MAGC SET SECTION STATE-'
                                    + str(self.selected_grid)
                                    + '-toggle')
                            else:
                                self.main_controls_trigger.transmit(
                                    'MAGC SET SECTION STATE-99999-deselectall')
                        else:
                            if self.selected_grid is not None:
                                self.main_controls_trigger.transmit(
                                    'MAGC SET SECTION STATE-'
                                    + str(self.selected_grid)
                                    + '-select')

            self.fov_drag_active = False
            self.grid_drag_active = False
            self.ov_drag_active = False
            self.tile_paint_mode_active = False
            self.imported_img_drag_active = False

            # Update viewport
            self.vp_draw()
            self.main_controls_trigger.transmit('SHOW CURRENT SETTINGS')

        elif event.button() == Qt.RightButton:
            if self.vp_measure_active or self.sv_measure_active:
                self.measure_complete = True

    def wheelEvent(self, event):
        if self.tabWidget.currentIndex() == 1:
            if event.angleDelta().y() > 0:
                self.sv_slice_fwd()
            if event.angleDelta().y() < 0:
                self.sv_slice_bwd()
        if self.tabWidget.currentIndex() == 0:
            p = event.pos()
            px, py = p.x() - utils.VP_MARGIN_X, p.y() - utils.VP_MARGIN_Y
            mouse_pos_within_viewer = (
                px in range(self.cs.vp_width) and py in range(self.cs.vp_height))
            if mouse_pos_within_viewer:
                if event.angleDelta().y() > 0:
                    self._vp_mouse_zoom(px, py, 1.1)
                if event.angleDelta().y() < 0:
                    self._vp_mouse_zoom(px, py, 0.9)

    def keyPressEvent(self, event):
        # Move through slices in slice-by-slice viewer with PgUp/PgDn
        if (type(event) == QKeyEvent) and (self.tabWidget.currentIndex() == 1):
            if event.key() == Qt.Key_PageUp:
                self.sv_slice_fwd()
            elif event.key() == Qt.Key_PageDown:
                self.sv_slice_bwd()

    def resizeEvent(self, event):
        """Adjust the Viewport and Slice-by-slice viewer canvas when the window
        is resized.
        """
        self.cs.vp_width = event.size().width() - utils.VP_WINDOW_DIFF_X
        self.cs.vp_height = event.size().height() - utils.VP_WINDOW_DIFF_Y
        self.cs.update_vp_origin_dx_dy()
        self.vp_canvas = QPixmap(self.cs.vp_width, self.cs.vp_height)
        self.sv_canvas = QPixmap(self.cs.vp_width, self.cs.vp_height)
        self.vp_draw()
        self.sv_draw()

# ====================== Below: Viewport (vp) methods ==========================

    def _vp_initialize(self):
        # self.vp_current_grid and self.vp_current_ov store the grid(s) and
        # OV(s) currently selected in the viewport's drop-down lists in the
        # bottom left. The selection -1 corresponds to 'show all' and
        # -2 corresponds to 'hide all'. Numbers >=0 correspond to grid and
        # overview indices.
        self.vp_current_grid = int(self.cfg['viewport']['vp_current_grid'])
        self.vp_current_ov = int(self.cfg['viewport']['vp_current_ov'])
        self.vp_tile_preview_mode = int(
            self.cfg['viewport']['vp_tile_preview_mode'])
        # display options
        self.show_stub_ov = (
            self.cfg['viewport']['show_stub_ov'].lower() == 'true')
        self.show_imported = (
            self.cfg['viewport']['show_imported'].lower() == 'true')
        self.show_labels = (
            self.cfg['viewport']['show_labels'].lower() == 'true')
        self.show_axes = (
            self.cfg['viewport']['show_axes'].lower() == 'true')
        # By default, stage position indicator is not visible. Can be activated
        # by user in GUI
        self.show_stage_pos = False

        # Active user flag (highlighted text in the upper left corner of the
        # Viewport to show that a user is actively using the program.)
        self.active_user_flag_enabled = False
        self.active_user_flag_text = ''

        # The following variables store the tile or OV that is being acquired.
        self.tile_acq_indicator = [None, None]
        self.ov_acq_indicator = None

        # self.selected_grid, self.selected_tile etc. store the elements
        # most recenlty selected with a mouse click.
        self.selected_grid = None
        self.selected_tile = None
        self.selected_ov = None
        self.selected_imported = None
        # The following booleans are set to True when the corresponding
        # user actions are active.
        self.grid_draw_active = False
        self.ov_draw_active = False
        self.template_draw_active = False
        self.grid_drag_active = False
        self.ov_drag_active = False
        self.template_drag_active = False
        self.imported_img_drag_active = False
        self.vp_measure_active = False

        # Canvas
        self.vp_canvas = QPixmap(self.cs.vp_width, self.cs.vp_height)
        # Help panel
        self.vp_help_panel_img = QPixmap(
            os.path.join('..', 'img', 'help-viewport.png'))
        # QPainter object that is used throughout this modult to write to the
        # Viewport canvas
        self.vp_qp = QPainter()

        # Buttons
        self.pushButton_refreshOVs.clicked.connect(self.vp_acquire_overview)
        self.pushButton_acquireStubOV.clicked.connect(
            self._vp_open_stub_overview_dlg)
        self.pushButton_measureViewport.clicked.connect(self._vp_toggle_measure)
        self.pushButton_measureViewport.setIcon(
            QIcon(os.path.join('..', 'img', 'measure.png')))
        self.pushButton_measureViewport.setIconSize(QSize(16, 16))
        self.pushButton_measureViewport.setToolTip(
            'Measure with right mouse clicks')
        self.pushButton_helpViewport.clicked.connect(self.vp_toggle_help_panel)
        self.pushButton_helpSliceViewer.clicked.connect(self.vp_toggle_help_panel)
        # Slider for zoom
        self.horizontalSlider_VP.valueChanged.connect(
            self._vp_adjust_scale_from_slider)
        self.vp_adjust_zoom_slider()
        # Tile Preview selector:
        self.comboBox_tilePreviewSelectorVP.addItems(
            ['Hide tile previews',
             'Show tile previews',
             'Tile previews, no grid(s)',
             'Tile previews with gaps'])
        self.comboBox_tilePreviewSelectorVP.setCurrentIndex(
            self.vp_tile_preview_mode)
        self.comboBox_tilePreviewSelectorVP.currentIndexChanged.connect(
            self.vp_change_tile_preview_mode)

        # Connect and populate grid/tile/OV comboboxes:
        self.comboBox_gridSelectorVP.currentIndexChanged.connect(
            self.vp_change_grid_selection)
        self.vp_update_grid_selector()
        self.comboBox_OVSelectorVP.currentIndexChanged.connect(
            self.vp_change_ov_selection)
        self.vp_update_ov_selector()

        # Update all checkboxes with current settings
        self.checkBox_showLabels.setChecked(self.show_labels)
        self.checkBox_showLabels.stateChanged.connect(
            self.vp_toggle_show_labels)
        self.checkBox_showAxes.setChecked(self.show_axes)
        self.checkBox_showAxes.stateChanged.connect(self.vp_toggle_show_axes)
        self.checkBox_showImported.setChecked(self.show_imported)
        self.checkBox_showImported.stateChanged.connect(
            self.vp_toggle_show_imported)
        self.checkBox_showStubOV.setChecked(self.show_stub_ov)
        self.checkBox_showStubOV.stateChanged.connect(
            self.vp_toggle_show_stub_ov)
        self.checkBox_showStagePos.setChecked(self.show_stage_pos)
        self.checkBox_showStagePos.stateChanged.connect(
            self.vp_toggle_show_stage_pos)

    def vp_update_grid_selector(self):
        if self.vp_current_grid >= self.gm.number_grids:
            self.vp_current_grid = -1  # show all
        self.comboBox_gridSelectorVP.blockSignals(True)
        self.comboBox_gridSelectorVP.clear()
        self.comboBox_gridSelectorVP.addItems(
            ['Hide grids', 'All grids'] + self.gm.grid_selector_list())
        self.comboBox_gridSelectorVP.setCurrentIndex(
            self.vp_current_grid + 2)
        self.comboBox_gridSelectorVP.blockSignals(False)

    def vp_update_ov_selector(self):
        if self.vp_current_ov >= self.ovm.number_ov:
            self.vp_current_ov = -1  # show all
        self.comboBox_OVSelectorVP.blockSignals(True)
        self.comboBox_OVSelectorVP.clear()
        self.comboBox_OVSelectorVP.addItems(
            ['Hide OVs', 'All OVs'] + self.ovm.ov_selector_list())
        self.comboBox_OVSelectorVP.setCurrentIndex(
            self.vp_current_ov + 2)
        self.comboBox_OVSelectorVP.blockSignals(False)

    def vp_change_tile_preview_mode(self):
        prev_vp_tile_preview_mode = self.vp_tile_preview_mode
        self.vp_tile_preview_mode = (
            self.comboBox_tilePreviewSelectorVP.currentIndex())
        if self.vp_tile_preview_mode == 3:  # show tiles with gaps
            # Hide OVs to make sure that gaps are visible
            self.comboBox_OVSelectorVP.blockSignals(True)
            self.comboBox_OVSelectorVP.setCurrentIndex(0)
            self.vp_current_ov = -2
            self.comboBox_OVSelectorVP.blockSignals(False)
            # Also hide stub OV
            self.show_stub_ov = False
            self.checkBox_showStubOV.setChecked(False)
        elif prev_vp_tile_preview_mode == 3:
            # When switching back from view with gaps, show OVs again
            self.comboBox_OVSelectorVP.blockSignals(True)
            self.comboBox_OVSelectorVP.setCurrentIndex(1)
            self.vp_current_ov = -1
            self.comboBox_OVSelectorVP.blockSignals(False)
        self.vp_draw()

    def vp_change_grid_selection(self):
        self.vp_current_grid = self.comboBox_gridSelectorVP.currentIndex() - 2
        self.vp_draw()

    def vp_change_ov_selection(self):
        self.vp_current_ov = self.comboBox_OVSelectorVP.currentIndex() - 2
        self.vp_draw()

    def vp_toggle_show_labels(self):
        self.show_labels = self.checkBox_showLabels.isChecked()
        self.vp_draw()

    def vp_toggle_show_axes(self):
        self.show_axes = self.checkBox_showAxes.isChecked()
        self.vp_draw()

    def vp_toggle_show_stub_ov(self):
        self.show_stub_ov = self.checkBox_showStubOV.isChecked()
        self.vp_draw()

    def vp_toggle_show_imported(self):
        self.show_imported = self.checkBox_showImported.isChecked()
        self.vp_draw()

    def vp_toggle_tile_acq_indicator(self, grid_index, tile_index):
        if self.tile_acq_indicator[0] is None:
            self.tile_acq_indicator = [grid_index, tile_index]
        else:
            self.tile_acq_indicator = [None, None]
        self.vp_draw()

    def vp_toggle_ov_acq_indicator(self, ov_index):
        if self.ov_acq_indicator is None:
            self.ov_acq_indicator = ov_index
        else:
            self.ov_acq_indicator = None
        self.vp_draw()

    def vp_toggle_show_stage_pos(self):
        self.show_stage_pos ^= True
        self.vp_draw()

    def vp_activate_checkbox_show_stage_pos(self):
        self.show_stage_pos = True
        self.checkBox_showStagePos.blockSignals(True)
        self.checkBox_showStagePos.setChecked(True)
        self.checkBox_showStagePos.blockSignals(False)

    def vp_update_after_active_tile_selection(self):
        """Update debris detection areas, show updated settings and redraw
        Viewport after active tile selection has been changed by user."""
        self.ovm.update_all_debris_detections_areas(self.gm)
        self.main_controls_trigger.transmit('SHOW CURRENT SETTINGS')
        self.vp_draw()

    def vp_show_context_menu(self, p):
        """Show context menu after user has right-clicked at position p."""
        px, py = p.x() - utils.VP_MARGIN_X, p.y() - utils.VP_MARGIN_Y
        if px in range(self.cs.vp_width) and py in range(self.cs.vp_height):
            self.selected_grid, self.selected_tile = \
                self._vp_grid_tile_mouse_selection(px, py)
            self.selected_ov = self._vp_ov_mouse_selection(px, py)
            self.selected_imported = (
                self._vp_imported_img_mouse_selection(px, py))
            # Disable self.selected_template for now (causing runtime warnings)
            # TODO (Benjamin / Philipp): look into this
            # self.selected_template = self._vp_template_mouse_selection(px, py)
            sx, sy = self.cs.convert_mouse_to_s((px, py))
            dx, dy = self.cs.convert_s_to_d((sx, sy))
            current_pos_str = ('Move stage to X: {0:.3f}, '.format(sx)
                               + 'Y: {0:.3f}'.format(sy))
            self.selected_stage_pos = (sx, sy)
            grid_str = ''
            if self.selected_grid is not None:
                grid_str = f'in grid {self.selected_grid}'
            selected_for_autofocus = 'Select/deselect as'
            selected_for_gradient = 'Select/deselect as'
            if (self.selected_grid is not None
                and self.selected_tile is not None):
                selected = f'tile {self.selected_grid}.{self.selected_tile}'
                if self.gm[self.selected_grid][
                           self.selected_tile].autofocus_active:
                    selected_for_autofocus = (
                        f'Deselect tile {self.selected_grid}.'
                        f'{self.selected_tile} as')
                else:
                    selected_for_autofocus = (
                        f'Select tile {self.selected_grid}.'
                        f'{self.selected_tile} as')
                if self.gm[self.selected_grid][
                           self.selected_tile].wd_grad_active:
                    selected_for_gradient = (
                        f'Deselect tile {self.selected_grid}.'
                        f'{self.selected_tile} as')
                else:
                    selected_for_gradient = (
                        f'Select tile {self.selected_grid}.'
                        f'{self.selected_tile} as')
            elif self.selected_ov is not None:
                selected = f'OV {self.selected_ov}'
            else:
                selected = 'tile/OV'

            menu = QMenu()
            action_sliceViewer = menu.addAction(
                f'Load {selected} in Slice Viewer')
            action_sliceViewer.triggered.connect(self.sv_load_selected)
            action_focusTool = menu.addAction(f'Load {selected} in Focus Tool')
            action_focusTool.triggered.connect(self._vp_load_selected_in_ft)
            action_statistics = menu.addAction(f'Load {selected} statistics')
            action_statistics.triggered.connect(self.m_load_selected)

            menu.addSeparator()
            if self.selected_grid is not None:
                action_openGridSettings = menu.addAction(
                    f'Open settings of grid {self.selected_grid}'
                    f' | Shortcut &G')
            else:
                action_openGridSettings = menu.addAction(
                    'Open settings of selected grid')
            action_openGridSettings.triggered.connect(
                self._vp_open_grid_settings)
            action_selectAll = menu.addAction('Select all tiles ' + grid_str)
            action_selectAll.triggered.connect(self.vp_activate_all_tiles)
            action_deselectAll = menu.addAction(
                'Deselect all tiles ' + grid_str)
            action_deselectAll.triggered.connect(self.vp_deactivate_all_tiles)
            if self.selected_grid is not None:
                action_changeRotation = menu.addAction(
                    'Change rotation of ' + grid_str[3:])
            else:
                action_changeRotation = menu.addAction(
                    'Change rotation of selected grid')
            action_changeRotation.triggered.connect(
                self._vp_open_change_grid_rotation_dlg)

            if self.sem.magc_mode:
                action_moveGridCurrentStage = menu.addAction(
                    f'Move grid {self.selected_grid} to current stage position')
                action_moveGridCurrentStage.triggered.connect(
                    self._vp_manual_stage_move)
                if not ((self.selected_grid is not None)
                    and self.cs.magc_wafer_calibrated):
                    action_moveGridCurrentStage.setEnabled(False)

            menu.addSeparator()
            if self.autofocus.method == 2:
                action_selectAutofocus = menu.addAction(
                    selected_for_autofocus + ' focus tracking ref.')
            else:
                action_selectAutofocus = menu.addAction(
                    selected_for_autofocus + ' autofocus ref.')
            action_selectAutofocus.triggered.connect(
                self._vp_toggle_tile_autofocus)
            action_selectGradient = menu.addAction(
                selected_for_gradient + ' focus gradient ref.')
            action_selectGradient.triggered.connect(
                self._vp_toggle_wd_gradient_ref_tile)

            menu.addSeparator()
            action_move = menu.addAction(current_pos_str)
            action_move.triggered.connect(self._vp_manual_stage_move)
            action_stub = menu.addAction('Acquire stub OV at this position')
            action_stub.triggered.connect(self._vp_set_stub_ov_centre)

            # menu.addSeparator()
            # action_templateMatching = menu.addAction('Run Template Matching')
            # action_templateMatching.triggered.connect(self._vp_place_grids_template_matching)

            menu.addSeparator()
            action_import = menu.addAction('Import and place image')
            action_import.triggered.connect(self._vp_open_import_image_dlg)
            action_adjustImported = menu.addAction('Adjust imported image')
            action_adjustImported.triggered.connect(
                self._vp_open_adjust_image_dlg)
            action_deleteImported = menu.addAction('Delete imported image')
            action_deleteImported.triggered.connect(
                self._vp_open_delete_image_dlg)

            # ----- MagC items -----
            if self.sem.magc_mode:
                menu.addSeparator()
                # in MagC you only import wafer images from the MagC tab
                action_import.setEnabled(False)
                # in MagC you cannot remove the wafer image, the only
                # way is to Reset MagC
                action_deleteImported.setEnabled(False)
                # get closest grid
                self._closest_grid_number = self._vp_get_closest_grid_id(
                    self.selected_stage_pos)
                if self.gm.magc_selected_sections != []:
                    magc_selected_section = self.gm.magc_selected_sections[0]

            if (self.sem.magc_mode
                and self.selected_grid is not None):

                # propagate to all sections
                action_propagateToAll = menu.addAction(
                    'MagC | Propagate properties of grid '
                    + str(self.selected_grid)
                    + ' to all sections')
                action_propagateToAll.triggered.connect(
                    self.vp_propagate_grid_properties_to_all_sections)

                # propagate to selected sections
                action_propagateToSelected = menu.addAction(
                    'MagC | Propagate properties of grid '
                    + str(self.selected_grid)
                    + ' to selected sections')
                action_propagateToSelected.triggered.connect(
                    self.vp_propagate_grid_properties_to_selected_sections)

                # revert location to file-defined location
                action_revertLocation = menu.addAction(
                    'MagC | Revert location of grid  '
                    + str(self.selected_grid)
                    + ' to original file-defined location'
                    + ' | Shortcut &Z')
                action_revertLocation.triggered.connect(
                    self.vp_revert_grid_location_to_file)

                if self.gm.magc_sections_path == '':
                    action_propagateToAll.setEnabled(False)
                    action_propagateToSelected.setEnabled(False)
                    action_revertLocation.setEnabled(False)

            #---autofocus points---#
            if (self.sem.magc_mode
                and len(self.gm.magc_selected_sections) == 1):

                if (self.gm[magc_selected_section]
                    .magc_autofocus_points != []):

                    action_removeAutofocusPoint = menu.addAction(
                        'MagC | Remove last autofocus point of grid '
                        + str(magc_selected_section)
                        + ' | Shortcut &E')
                    action_removeAutofocusPoint.triggered.connect(
                        self.vp_remove_autofocus_point)

                    action_removeAllAutofocusPoint = menu.addAction(
                        'MagC | Remove all autofocus points of grid '
                        + str(magc_selected_section)
                        + ' | Shortcut &W')
                    action_removeAllAutofocusPoint.triggered.connect(
                        self.vp_remove_all_autofocus_point)

                action_addAutofocusPoint = menu.addAction(
                    'MagC | Add autofocus point to grid '
                    + str(magc_selected_section)
                    + ' | Shortcut &R')
                action_addAutofocusPoint.triggered.connect(
                    self.vp_add_autofocus_point)
            #----------------------#

            #---ROI---#
            if (self.sem.magc_mode
                and len(self.gm.magc_selected_sections) == 1):

                if (self.gm[magc_selected_section]
                    .magc_polyroi_points != []):

                    action_removePolyroiPoint = menu.addAction(
                        'MagC | Remove last ROI point of grid '
                        + str(magc_selected_section)
                        + ' | Shortcut &D')
                    action_removePolyroiPoint.triggered.connect(
                        self.vp_remove_polyroi_point)

                    action_removePolyroi = menu.addAction(
                        'MagC | Remove ROI of grid '
                        + str(magc_selected_section)
                        + ' | Shortcut &S')
                    action_removePolyroi.triggered.connect(
                        self.vp_remove_polyroi)

                action_addPolyroiPoint = menu.addAction(
                    'MagC | Add ROI point to grid '
                    + str(magc_selected_section)
                    + ' | Shortcut &F')
                action_addPolyroiPoint.triggered.connect(
                    self.vp_add_polyroi_point)
            #---------#

            # ----- End of MagC items -----

            if (self.selected_tile is None) and (self.selected_ov is None):
                action_sliceViewer.setEnabled(False)
                action_focusTool.setEnabled(False)
                action_statistics.setEnabled(False)
            if self.selected_grid is None:
                action_openGridSettings.setEnabled(False)
                action_selectAll.setEnabled(False)
                action_deselectAll.setEnabled(False)
            if self.selected_template is None and self.selected_grid is None:
                action_changeRotation.setEnabled(False)
            if self.selected_tile is None:
                action_selectAutofocus.setEnabled(False)
                action_selectGradient.setEnabled(False)
            if self.autofocus.tracking_mode == 1:
                action_selectAutofocus.setEnabled(False)
            if self.selected_imported is None:
                action_adjustImported.setEnabled(False)
            if self.imported.number_imported == 0:
                action_deleteImported.setEnabled(False)
            if self.busy:
                action_focusTool.setEnabled(False)
                action_openGridSettings.setEnabled(False)
                action_changeRotation.setEnabled(False)
                action_selectAll.setEnabled(False)
                action_deselectAll.setEnabled(False)
                action_selectGradient.setEnabled(False)
                action_move.setEnabled(False)
                action_stub.setEnabled(False)
                action_import.setEnabled(False)
            if self.sem.simulation_mode:
                action_move.setEnabled(False)
                action_stub.setEnabled(False)
            menu.exec_(self.mapToGlobal(p))

    def _vp_get_closest_grid_id(self, sx_sy):
        closest_id = (scipy.spatial.distance.cdist(
            [np.array(sx_sy)],
            [self.gm[id].centre_sx_sy for id in range(self.gm.number_grids)])
            .argmin())
        return closest_id

    def vp_add_autofocus_point(self):
        (self.gm[self.gm.magc_selected_sections[0]]
            .magc_add_autofocus_point(
                self.selected_stage_pos))
        self.vp_draw()

    def vp_remove_autofocus_point(self):
        (self.gm[self.gm.magc_selected_sections[0]]
            .magc_delete_last_autofocus_point())
        self.vp_draw()

    def vp_remove_all_autofocus_point(self):
        (self.gm[self.gm.magc_selected_sections[0]]
            .magc_delete_autofocus_points())
        self.vp_draw()

    def vp_remove_all_autofocus_point(self):
        (self.gm[self.gm.magc_selected_sections[0]]
            .magc_delete_autofocus_points())
        self.vp_draw()

    def vp_add_polyroi_point(self):
        (self.gm[self.gm.magc_selected_sections[0]]
            .magc_add_polyroi_point(
                self.selected_stage_pos))
        self.vp_draw()

    def vp_remove_polyroi_point(self):
        (self.gm[self.gm.magc_selected_sections[0]]
            .magc_delete_last_polyroi_point())
        self.vp_draw()

    def vp_remove_polyroi(self):
        (self.gm[self.gm.magc_selected_sections[0]]
            .magc_delete_polyroi())
        self.vp_draw()

    def _vp_load_selected_in_ft(self):
        self.main_controls_trigger.transmit('LOAD IN FOCUS TOOL')

    def _vp_set_stub_ov_centre(self):
        self.stub_ov_centre = self.selected_stage_pos
        self._vp_open_stub_overview_dlg()

    def vp_dx_dy_range(self):
        x_min, x_max, y_min, y_max = self.stage.limits
        dx, dy = [0, 0, 0, 0], [0, 0, 0, 0]
        dx[0], dy[0] = self.cs.convert_s_to_d((x_min, y_min))
        dx[1], dy[1] = self.cs.convert_s_to_d((x_max, y_min))
        dx[2], dy[2] = self.cs.convert_s_to_d((x_max, y_max))
        dx[3], dy[3] = self.cs.convert_s_to_d((x_min, y_max))
        return min(dx), max(dx), min(dy), max(dy)

    def vp_draw(self, suppress_labels=False, suppress_previews=False):
        """Draw all elements on Viewport canvas"""
        show_debris_area = (self.ovm.detection_area_visible
                            and self.acq.use_debris_detection)
        if self.ov_drag_active or self.grid_drag_active or self.template_drag_active:
            show_debris_area = False
        # Start with empty black canvas
        self.vp_canvas.fill(Qt.black)
        # Begin painting on canvas
        self.vp_qp.begin(self.vp_canvas)
        # First, show stub OV if option selected and stub OV image exists:
        if self.show_stub_ov and self.ovm['stub'].image is not None:
            self._vp_place_stub_overview()
            # self._place_template()
        # For MagC mode: show imported images before drawing grids
        # TODO: Think about more general solution to organize display layers.
        if (self.show_imported and self.imported.number_imported > 0
            and self.sem.magc_mode):
            for imported_img_index in range(self.imported.number_imported):
                self._vp_place_imported_img(imported_img_index)
        # Place OV overviews over stub OV:
        if self.vp_current_ov == -1:  # show all
            for ov_index in range(self.ovm.number_ov):
                self._vp_place_overview(ov_index,
                                        show_debris_area,
                                        suppress_labels)
        if self.vp_current_ov >= 0:  # show only the selected OV
            self._vp_place_overview(self.vp_current_ov,
                                    show_debris_area,
                                    suppress_labels)
        # Tile preview mode
        if self.vp_tile_preview_mode == 0:   # No previews, only show grid lines
            show_grid, show_previews, with_gaps = True, False, False
        elif self.vp_tile_preview_mode == 1: # Show previews with grid lines
            show_grid, show_previews, with_gaps = True, True, False
        elif self.vp_tile_preview_mode == 2: # Show previews without grid lines
            show_grid, show_previews, with_gaps = False, True, False
        elif self.vp_tile_preview_mode == 3: # Show previews with gaps, no grid
            show_grid, show_previews, with_gaps = False, True, True
        if suppress_previews:                # this parameter of vp_draw()
            show_previews = False            # overrides the tile preview mode

        if self.vp_current_grid == -1:  # show all grids
            for grid_index in range(self.gm.number_grids):
                self._vp_place_grid(grid_index,
                                    show_grid,
                                    show_previews,
                                    with_gaps,
                                    suppress_labels)
        if self.vp_current_grid >= 0:   # show only the selected grid
            self._vp_place_grid(self.vp_current_grid,
                                show_grid,
                                show_previews,
                                with_gaps,
                                suppress_labels)
        # Finally, show imported images
        if (self.show_imported and self.imported.number_imported > 0
            and not self.sem.magc_mode):
            for imported_img_index in range(self.imported.number_imported):
                self._vp_place_imported_img(imported_img_index)
        # Show stage boundaries (motor range limits)
        self._vp_draw_stage_boundaries()
        if self.show_axes:
            self._vp_draw_stage_axes()
        # Show interactive features
        if self.grid_draw_active:
            self._draw_rectangle(self.vp_qp, self.drag_origin, self.drag_current,
                                 utils.COLOUR_SELECTOR[0], line_style=Qt.DashLine)
        if self.ov_draw_active:
            self._draw_rectangle(self.vp_qp, self.drag_origin, self.drag_current,
                                 utils.COLOUR_SELECTOR[10], line_style=Qt.DashLine)
        if self.template_draw_active:
            self._draw_rectangle(self.vp_qp, self.drag_origin, self.drag_current,
                                 utils.COLOUR_SELECTOR[8], line_style=Qt.DashLine)
        if self.vp_measure_active:
            self._draw_measure_labels(self.vp_qp)
        # Show help panel
        if self.help_panel_visible:
            self.vp_qp.drawPixmap(self.cs.vp_width - 200,
                                  self.cs.vp_height - 550,
                                  self.vp_help_panel_img)
        # Simulation mode indicator
        if self.sem.simulation_mode:
            self._show_simulation_mode_indicator()
        # Active user flag
        if self.active_user_flag_enabled:
            self._show_active_user_flag()
        # Show current stage position
        if self.show_stage_pos:
            self._show_stage_position_indicator()
        self.vp_qp.end()
        # All elements have been drawn on the canvas, now show them in the
        # Viewport window.
        self.QLabel_ViewportCanvas.setPixmap(self.vp_canvas)
        # Update text labels (bottom of the Viewport window)
        self.label_FOVSize.setText(
            '{0:.1f}'.format(self.cs.vp_width / self.cs.vp_scale)
            + ' µm × '
            + '{0:.1f}'.format(self.cs.vp_height / self.cs.vp_scale) + ' µm')

    def _show_simulation_mode_indicator(self):
        """Draw simulation mode indicator on viewport canvas.
        QPainter object self.vp_qp must be active when calling this method.
        """
        self.vp_qp.setPen(QPen(QColor(0, 0, 0), 1, Qt.SolidLine))
        self.vp_qp.setBrush(QColor(0, 0, 0, 255))
        self.vp_qp.drawRect(0, 0, 120, 20)
        self.vp_qp.setPen(QPen(QColor(255, 0, 0), 1, Qt.SolidLine))
        font = QFont()
        font.setPixelSize(12)
        self.vp_qp.setFont(font)
        self.vp_qp.drawText(7, 15, 'SIMULATION MODE')

    def _show_active_user_flag(self):
        custom_text = 'ACTIVE USER: ' + self.active_user_flag_text
        self.vp_qp.setPen(QPen(QColor(0, 0, 0), 1, Qt.SolidLine))
        self.vp_qp.setBrush(QColor(0, 0, 0, 255))
        font = QFont()
        font.setPixelSize(16)
        metrics = QFontMetrics(font);
        self.vp_qp.drawRect(0, 0, metrics.width(custom_text) + 15, 30)
        self.vp_qp.setPen(
            QPen(QColor(*utils.COLOUR_SELECTOR[13]), 1, Qt.SolidLine))
        self.vp_qp.setFont(font)
        self.vp_qp.drawText(7, 21, custom_text)

    def _show_stage_position_indicator(self):
        """Draw red bullseye indicator at last known stage position.
        QPainter object self.vp_qp must be active when caling this method.
        """
        vx, vy = self.cs.convert_d_to_v(
            self.cs.convert_s_to_d(self.stage.last_known_xy))
        size = int(self.cs.vp_scale * 5)
        if size < 10:
            size = 10
        self.vp_qp.setPen(QPen(QColor(255, 0, 0), 2, Qt.SolidLine))
        self.vp_qp.setBrush(QColor(255, 0, 0, 0))
        self.vp_qp.drawEllipse(QPoint(vx, vy), size, size)
        self.vp_qp.setBrush(QColor(255, 0, 0, 0))
        self.vp_qp.drawEllipse(QPoint(vx, vy), int(size/2), int(size/2))
        self.vp_qp.drawLine(vx - 1.25 * size, vy, vx + 1.25 * size, vy)
        self.vp_qp.drawLine(vx, vy - 1.25 * size, vx, vy + 1.25 * size)

    def _vp_visible_area(self, vx, vy, w_px, h_px, resize_ratio):
        """Determine if an object at position vx, vy (Viewport coordinates) and
        size w_px, h_px at a given resize_ratio is visible in the Viewport and
        calculate its crop_area. Return visible=True if the object is visible,
        and its crop area and the new Viewport coordinates vx_cropped,
        vy_cropped. TODO: What about rotated elements?"""
        crop_area = QRect(0, 0, w_px, h_px)
        vx_cropped, vy_cropped = vx, vy
        visible = self._vp_element_visible(vx, vy, w_px, h_px, resize_ratio)
        if visible:
            if (vx >= 0) and (vy >= 0):
                crop_area = QRect(0, 0,
                                  (self.cs.vp_width - vx) / resize_ratio + 1,
                                  self.cs.vp_height / resize_ratio + 1)
            if (vx >= 0) and (vy < 0):
                crop_area = QRect(0, -vy / resize_ratio,
                                  (self.cs.vp_width - vx) / resize_ratio + 1,
                                  (self.cs.vp_height) / resize_ratio + 1)
                vy_cropped = 0
            if (vx < 0) and (vy < 0):
                crop_area = QRect(-vx / resize_ratio, -vy / resize_ratio,
                                  (self.cs.vp_width) / resize_ratio + 1,
                                  (self.cs.vp_height) / resize_ratio + 1)
                vx_cropped, vy_cropped = 0, 0
            if (vx < 0) and (vy >= 0):
                crop_area = QRect(-vx / resize_ratio, 0,
                                  (self.cs.vp_width) / resize_ratio + 1,
                                  (self.cs.vp_height - vy) / resize_ratio + 1)
                vx_cropped = 0
        return visible, crop_area, vx_cropped, vy_cropped

    def _vp_element_visible(self, vx, vy, width, height, resize_ratio,
                            pivot_vx=0, pivot_vy=0, angle=0):
        """Return True if element is visible, otherwise return False."""
        # Calculate the four corners of the unrotated bounding box
        points_x = [vx, vx + width * resize_ratio,
                    vx, vx + width * resize_ratio]
        points_y = [vy, vy, vy + height * resize_ratio,
                    vy + height * resize_ratio]
        if angle > 0:
            angle = radians(angle)
            # Rotate all coordinates with respect to the pivot:
            # (1) Subtract pivot coordinates
            # (2) Rotate corners
            # (3) Add pivot coordinates
            for i in range(4):
                points_x[i] -= pivot_vx
                points_y[i] -= pivot_vy
                x_rot = points_x[i] * cos(angle) - points_y[i] * sin(angle)
                y_rot = points_x[i] * sin(angle) + points_y[i] * cos(angle)
                points_x[i] = x_rot + pivot_vx
                points_y[i] = y_rot + pivot_vy
        # Find the maximum and minimum x and y coordinates:
        max_x, min_x = max(points_x), min(points_x)
        max_y, min_y = max(points_y), min(points_y)
        # Check if bounding box is entirely outside viewport
        if (min_x > self.cs.vp_width or max_x < 0
            or min_y > self.cs.vp_height or max_y < 0):
            return False
        return True

    def _vp_place_stub_overview(self):
        """Place stub overview image onto the Viewport canvas. Crop and resize
        the image before placing it. QPainter object self.vp_qp must be active
        when calling this method."""
        viewport_pixel_size = 1000 / self.cs.vp_scale
        resize_ratio = self.ovm['stub'].pixel_size / viewport_pixel_size
        mag_level = np.round(np.log2(resize_ratio))
        # set to 1 for resize_ratio >= 1 else store 2^-x down sizing
        mag_level = int(1 if mag_level >= 0 else 2**(-mag_level))
        mag_level = min(mag_level, 16)
        # Compute position of stub overview (upper left corner) and its
        # width and height
        dx, dy = self.ovm['stub'].origin_dx_dy
        dx -= self.ovm['stub'].tile_width_d() / 2
        dy -= self.ovm['stub'].tile_height_d() / 2
        vx, vy = self.cs.convert_d_to_v((dx, dy))

        width_px = self.ovm['stub'].width_p() // mag_level
        height_px = self.ovm['stub'].height_p() // mag_level
        resize_ratio = self.ovm['stub'].pixel_size * mag_level / viewport_pixel_size
        # Crop and resize stub OV before placing it
        visible, crop_area, vx_cropped, vy_cropped = self._vp_visible_area(
            vx, vy, width_px, height_px, resize_ratio)
        if visible:
            img = self.ovm['stub'].image(mag=mag_level)
            if img is None:
                return
            cropped_img = img.copy(crop_area)
            v_width = cropped_img.size().width()
            cropped_resized_img = cropped_img.scaledToWidth(
                v_width * resize_ratio)
            # Draw stub OV on canvas
            self.vp_qp.drawPixmap(vx_cropped, vy_cropped,
                                  cropped_resized_img)
            # Draw dark grey rectangle around stub OV
            pen = QPen(QColor(*utils.COLOUR_SELECTOR[11]), 2, Qt.SolidLine)
            self.vp_qp.setPen(pen)
            self.vp_qp.drawRect(vx - 1, vy - 1,
                                width_px * resize_ratio + 1,
                                height_px * resize_ratio + 1)

    def _vp_place_imported_img(self, index):
        """Place imported image specified by index onto the viewport canvas."""
        if self.imported[index].image is not None:
            viewport_pixel_size = 1000 / self.cs.vp_scale
            img_pixel_size = self.imported[index].pixel_size
            resize_ratio = img_pixel_size / viewport_pixel_size

            # Compute position of image in viewport:
            dx, dy = self.cs.convert_s_to_d(
                self.imported[index].centre_sx_sy)
            # Get width and height of the imported QPixmap:
            width = self.imported[index].image.width()
            height = self.imported[index].image.height()
            pixel_size = self.imported[index].pixel_size
            dx -= (width * pixel_size / 1000) / 2
            dy -= (height * pixel_size / 1000) / 2
            vx, vy = self.cs.convert_d_to_v((dx, dy))
            # Crop and resize image before placing it into viewport:
            visible, crop_area, vx_cropped, vy_cropped = self._vp_visible_area(
                vx, vy, width, height, resize_ratio)
            if visible:
                cropped_img = self.imported[index].image.copy(crop_area)
                v_width = cropped_img.size().width()
                cropped_resized_img = cropped_img.scaledToWidth(
                    v_width * resize_ratio)
                self.vp_qp.setOpacity(
                    1 - self.imported[index].transparency / 100)
                self.vp_qp.drawPixmap(vx_cropped, vy_cropped,
                                      cropped_resized_img)
                self.vp_qp.setOpacity(1)

    def _vp_place_overview(self, ov_index,
                           show_debris_area=False, suppress_labels=False):
        """Place OV overview image specified by ov_index onto the viewport
        canvas. Crop and resize the image before placing it.
        """
        # Load, resize and crop OV for display.
        viewport_pixel_size = 1000 / self.cs.vp_scale
        ov_pixel_size = self.ovm[ov_index].pixel_size
        resize_ratio = ov_pixel_size / viewport_pixel_size
        # Load OV centre in SEM coordinates.
        dx, dy = self.ovm[ov_index].centre_dx_dy
        # First, calculate origin of OV image with respect to
        # SEM coordinate system.
        dx -= self.ovm[ov_index].width_d() / 2
        dy -= self.ovm[ov_index].height_d() / 2
        width_px = self.ovm[ov_index].width_p()
        height_px = self.ovm[ov_index].height_p()
        # Convert to viewport window coordinates.
        vx, vy = self.cs.convert_d_to_v((dx, dy))

        if not suppress_labels:
            # Suppress the display of labels for performance reasons.
            # TODO: Reconsider this after refactoring complete.
            suppress_labels = (
                (self.gm.number_grids + self.ovm.number_ov) > 10
                and (self.cs.vp_scale < 1.0
                     or self.fov_drag_active
                     or self.grid_drag_active))

        # Crop and resize OV before placing it.
        visible, crop_area, vx_cropped, vy_cropped = self._vp_visible_area(
            vx, vy, width_px, height_px, resize_ratio)

        if not visible:
            return

        # Show OV label in upper left corner
        if self.show_labels and not suppress_labels:
            font_size = int(self.cs.vp_scale * 8)
            if font_size < 12:
                font_size = 12
            self.vp_qp.setPen(QColor(*utils.COLOUR_SELECTOR[10]))
            self.vp_qp.setBrush(QColor(*utils.COLOUR_SELECTOR[10]))
            if self.ovm[ov_index].active:
                width_factor = 3.6
            else:
                width_factor = 9
            ov_label_rect = QRect(
                vx, vy - int(4/3 * font_size),
                int(width_factor * font_size), int(4/3 * font_size))
            self.vp_qp.drawRect(ov_label_rect)
            self.vp_qp.setPen(QColor(255, 255, 255))
            font = QFont()
            font.setPixelSize(font_size)
            self.vp_qp.setFont(font)
            if self.ovm[ov_index].active:
                ov_label_text = 'OV %d' % ov_index
            else:
                ov_label_text = 'OV %d (inactive)' % ov_index
            self.vp_qp.drawText(ov_label_rect,
                                Qt.AlignVCenter | Qt.AlignHCenter,
                                ov_label_text)

        # If OV inactive return after drawing label
        if not self.ovm[ov_index].active:
            return

        cropped_img = self.ovm[ov_index].image.copy(crop_area)
        v_width = cropped_img.size().width()
        cropped_resized_img = cropped_img.scaledToWidth(
            v_width * resize_ratio)
        if not (self.ov_drag_active and ov_index == self.selected_ov):
            # Draw OV
            self.vp_qp.drawPixmap(vx_cropped, vy_cropped,
                                  cropped_resized_img)
        # Draw blue rectangle around OV.
        self.vp_qp.setPen(
            QPen(QColor(*utils.COLOUR_SELECTOR[10]), 2, Qt.SolidLine))
        if ((self.ov_acq_indicator is not None)
            and self.ov_acq_indicator == ov_index):
            self.vp_qp.setBrush(QColor(*utils.COLOUR_SELECTOR[12]))
        else:
            self.vp_qp.setBrush(QColor(0, 0, 0, 0))
        self.vp_qp.drawRect(vx, vy,
                            width_px * resize_ratio,
                            height_px * resize_ratio)

        if show_debris_area:
            # w3, w4 are fudge factors for clearer display
            w3 = utils.fit_in_range(self.cs.vp_scale/2, 1, 3)
            w4 = utils.fit_in_range(self.cs.vp_scale, 5, 9)

            area = self.ovm[ov_index].debris_detection_area
            if area:
                (top_left_dx, top_left_dy,
                 bottom_right_dx, bottom_right_dy) = area
                width = bottom_right_dx - top_left_dx
                height = bottom_right_dy - top_left_dy
                if width == self.ovm[ov_index].width_p():
                    w3, w4 = 3, 6

                pen = QPen(
                    QColor(*utils.COLOUR_SELECTOR[10]), 2, Qt.DashDotLine)
                self.vp_qp.setPen(pen)
                self.vp_qp.setBrush(QColor(0, 0, 0, 0))
                self.vp_qp.drawRect(vx + top_left_dx * resize_ratio - w3,
                                    vy + top_left_dy * resize_ratio - w3,
                                    width * resize_ratio + w4,
                                    height * resize_ratio + w4)

    def _vp_place_grid(self, grid_index,
                       show_grid=True, show_previews=False, with_gaps=False,
                       suppress_labels=False):
        """Place grid specified by grid_index onto the viewport canvas
        (including tile previews if option selected).
        """
        viewport_pixel_size = 1000 / self.cs.vp_scale
        grid_pixel_size = self.gm[grid_index].pixel_size
        resize_ratio = grid_pixel_size / viewport_pixel_size

        # Calculate coordinates of grid origin with respect to Viewport canvas
        dx, dy = self.gm[grid_index].origin_dx_dy
        origin_vx, origin_vy = self.cs.convert_d_to_v((dx, dy))

        # Calculate top-left corner of the (unrotated) grid
        dx -= self.gm[grid_index].tile_width_d() / 2
        dy -= self.gm[grid_index].tile_height_d() / 2
        topleft_vx, topleft_vy = self.cs.convert_d_to_v((dx, dy))

        width_px = self.gm[grid_index].width_p()
        height_px = self.gm[grid_index].height_p()
        theta = self.gm[grid_index].rotation
        use_rotation = theta > 0

        font = QFont()
        grid_colour_rgb = self.gm[grid_index].display_colour_rgb()
        grid_colour = QColor(*grid_colour_rgb, 255)
        indicator_colour = QColor(*utils.COLOUR_SELECTOR[12])

        # Suppress labels when zoomed out or when user is moving a grid or
        # panning the view, under the condition that there are >10 grids.
        # TODO: Revisit this restriction after refactoring and test with
        # MagC example grids.
        if not suppress_labels:
            suppress_labels = ((self.gm.number_grids + self.ovm.number_ov) > 10
                               and (self.cs.vp_scale < 1.0
                               or self.fov_drag_active
                               or self.grid_drag_active))

        visible = self._vp_element_visible(
            topleft_vx, topleft_vy, width_px, height_px, resize_ratio,
            origin_vx, origin_vy, theta)

        # Proceed only if at least a part of the grid is visible
        if not visible:
            return

        # Rotate the painter if grid has a rotation angle > 0
        if use_rotation:
            # Translate painter to coordinates of grid origin, then rotate
            self.vp_qp.translate(origin_vx, origin_vy)
            self.vp_qp.rotate(theta)
            # Translate to top-left corner
            self.vp_qp.translate(
                -self.gm[grid_index].tile_width_d() / 2 * self.cs.vp_scale,
                -self.gm[grid_index].tile_height_d() / 2 * self.cs.vp_scale)
            # Enable anti-aliasing in this case:
            # self.vp_qp.setRenderHint(QPainter.Antialiasing)
            # TODO: Try Antialiasing again - advantageous or not? What about
            # Windows 7 vs Windows 10?
        else:
            # Translate painter to coordinates of top-left corner
            self.vp_qp.translate(topleft_vx, topleft_vy)

        # Show grid label in upper left corner
        if self.show_labels and not suppress_labels:
            fontsize = int(self.cs.vp_scale * 8)
            if fontsize < 12:
                fontsize = 12
            font.setPixelSize(fontsize)
            self.vp_qp.setFont(font)
            self.vp_qp.setPen(grid_colour)
            self.vp_qp.setBrush(grid_colour)
            if self.gm[grid_index].active:
                width_factor = 5.3
            else:
                width_factor = 10.5
            grid_label_rect = QRect(0,
                                    -int(4/3 * fontsize),
                                    int(width_factor * fontsize),
                                    int(4/3 * fontsize))
            self.vp_qp.drawRect(grid_label_rect)
            if self.gm[grid_index].display_colour in [1, 2, 3]:
            # Use black for light and white for dark background colour
                self.vp_qp.setPen(QColor(0, 0, 0))
            else:
                self.vp_qp.setPen(QColor(255, 255, 255))
            # Show the grid label in different versions, depending on
            # whether grid is active
            if self.gm[grid_index].active:
                grid_label_text = 'GRID %d' % grid_index
            else:
                grid_label_text = 'GRID %d (inactive)' % grid_index
            self.vp_qp.drawText(grid_label_rect,
                                Qt.AlignVCenter | Qt.AlignHCenter,
                                grid_label_text)

        # If grid is inactive, only the label will be drawn, nothing else.
        # Reset the QPainter and return in this case
        if not self.gm[grid_index].active:
            self.vp_qp.resetTransform()
            return

        if with_gaps:
            # Use gapped tile grid in pixels (coordinates not rotated)
            tile_map = self.gm[grid_index].gapped_tile_positions_p()
        else:
            # Tile grid in pixels (coordinates not rotated)
            tile_map = self.gm[grid_index].tile_positions_p()

        tile_width_v = self.gm[grid_index].tile_width_d() * self.cs.vp_scale
        tile_height_v = self.gm[grid_index].tile_height_d() * self.cs.vp_scale

        font_size1 = int(tile_width_v/5)
        font_size1 = utils.fit_in_range(font_size1, 2, 120)
        font_size2 = int(tile_width_v/11)
        font_size2 = utils.fit_in_range(font_size2, 1, 40)

        if (show_previews
                and not self.fov_drag_active
                and not self.grid_drag_active
                and self.cs.vp_scale > 1.4):
            # Previews are disabled when FOV or grid are being dragged or
            # when sufficiently zoomed out.
            width_px = self.gm[grid_index].tile_width_p()
            height_px = self.gm[grid_index].tile_height_p()

            for tile_index in self.gm[grid_index].active_tiles:
                vx = tile_map[tile_index][0] * resize_ratio
                vy = tile_map[tile_index][1] * resize_ratio
                tile_visible = self._vp_element_visible(
                    topleft_vx + vx, topleft_vy + vy,
                    width_px, height_px, resize_ratio,
                    origin_vx, origin_vy, theta)
                if not tile_visible:
                    continue
                # Show tile preview
                preview_img = self.gm[grid_index][tile_index].preview_img
                if preview_img is not None:
                    tile_img = preview_img.scaledToWidth(tile_width_v)
                    self.vp_qp.drawPixmap(vx, vy, tile_img)

        # Display grid lines
        rows, cols = self.gm[grid_index].size
        grid_pen = QPen(grid_colour, 1, Qt.SolidLine)
        grid_brush_active_tile = QBrush(QColor(*grid_colour_rgb, 40),
                                        Qt.SolidPattern)
        grid_brush_transparent = QBrush(QColor(255, 255, 255, 0),
                                        Qt.SolidPattern)

        # Suppress labels when zoomed out or when user is moving a grid or
        # panning the view, under the condition that there are >10 grids.
        # TODO: Revisit this restriction after refactoring and test with
        # MagC example grids.
        if not suppress_labels:
            suppress_labels = ((self.gm.number_grids + self.ovm.number_ov) > 10
                               and (self.cs.vp_scale < 1.0
                               or self.fov_drag_active
                               or self.grid_drag_active))

        if ((tile_width_v * cols > 2 or tile_height_v * rows > 2)
            and not 'multisem' in self.sem.device_name.lower()):
            # Draw grid if at least 3 pixels wide or high.
            for tile_index in range(rows * cols):
                self.vp_qp.setPen(grid_pen)
                if self.gm[grid_index][tile_index].tile_active:
                    self.vp_qp.setBrush(grid_brush_active_tile)
                else:
                    self.vp_qp.setBrush(grid_brush_transparent)
                if (self.tile_acq_indicator[0] is not None and
                    (self.tile_acq_indicator == [grid_index, tile_index])):
                    self.vp_qp.setBrush(indicator_colour)
                # Draw tile rectangles.
                if show_grid:
                    self.vp_qp.drawRect(
                        tile_map[tile_index][0] * resize_ratio,
                        tile_map[tile_index][1] * resize_ratio,
                        tile_width_v, tile_height_v)
                if self.show_labels and not suppress_labels:
                    if self.gm[grid_index][tile_index].tile_active:
                        self.vp_qp.setPen(QColor(255, 255, 255))
                        font.setBold(True)
                    else:
                        self.vp_qp.setPen(grid_colour)
                        font.setBold(False)
                    pos_x = (tile_map[tile_index][0] * resize_ratio
                             + tile_width_v / 2)
                    pos_y = (tile_map[tile_index][1] * resize_ratio
                             + tile_height_v / 2)
                    position_rect = QRect(pos_x - tile_width_v / 2,
                                          pos_y - tile_height_v / 2,
                                          tile_width_v, tile_height_v)
                    # Show tile indices.
                    font.setPixelSize(int(font_size1))
                    self.vp_qp.setFont(font)
                    self.vp_qp.drawText(
                        position_rect, Qt.AlignVCenter | Qt.AlignHCenter,
                        str(tile_index))

                    # Show autofocus/gradient labels and working distance.
                    font = QFont()
                    font.setPixelSize(int(font_size2))
                    font.setBold(True)
                    self.vp_qp.setFont(font)
                    position_rect = QRect(
                        pos_x - tile_width_v,
                        pos_y - tile_height_v - tile_height_v/4,
                        2 * tile_width_v, 2 * tile_height_v)
                    show_grad_label = (
                        self.gm[grid_index][tile_index].wd_grad_active
                        and self.gm[grid_index].use_wd_gradient)
                    show_autofocus_label = (
                        self.gm[grid_index][tile_index].autofocus_active
                        and self.acq.use_autofocus
                        and (self.autofocus.method < 2 or self.autofocus.method == 3))
                    show_tracking_label = (
                        self.gm[grid_index][tile_index].autofocus_active
                        and self.acq.use_autofocus
                        and self.autofocus.method == 2)

                    if show_grad_label and show_autofocus_label:
                        self.vp_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'GRAD + AF')
                    elif show_grad_label and show_tracking_label:
                        self.vp_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'GRAD + TRACK')
                    elif show_grad_label:
                        self.vp_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'GRADIENT')
                    elif show_autofocus_label:
                        self.vp_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'AUTOFOCUS')
                    elif show_tracking_label:
                        self.vp_qp.drawText(position_rect,
                                            Qt.AlignVCenter | Qt.AlignHCenter,
                                            'TRACKED FOCUS')

                    font.setBold(False)
                    self.vp_qp.setFont(font)
                    if (self.gm[grid_index][tile_index].wd > 0
                        and (self.gm[grid_index][tile_index].tile_active
                             or show_grad_label
                             or show_autofocus_label
                             or show_tracking_label)):
                        position_rect = QRect(
                            pos_x - tile_width_v,
                            pos_y - tile_height_v
                            + tile_height_v / 4,
                            2 * tile_width_v, 2 * tile_height_v)
                        self.vp_qp.drawText(
                            position_rect,
                            Qt.AlignVCenter | Qt.AlignHCenter,
                            'WD: {0:.6f}'.format(
                                self.gm[grid_index][tile_index].wd * 1000))
        else:
            # Show the grid as a single pixel (for performance reasons when
            # zoomed out).
            self.vp_qp.setPen(grid_pen)
            self.vp_qp.drawPoint(tile_map[0][0] * resize_ratio,
                                 tile_map[0][1] * resize_ratio)

        # Reset painter (undo translation and rotation).
        self.vp_qp.resetTransform()

    def _place_template(self):
        if np.prod(self.tm.template.frame_size) == 0:
            return
        viewport_pixel_size = 1000 / self.cs.vp_scale
        grid_pixel_size = self.tm.pixel_size
        resize_ratio = grid_pixel_size / viewport_pixel_size

        # Calculate coordinates of grid origin with respect to Viewport canvas
        dx, dy = self.tm.template.origin_dx_dy
        origin_vx, origin_vy = self.cs.convert_d_to_v((dx, dy))

        # Calculate top-left corner of the (unrotated) grid
        dx -= self.tm.template.tile_width_d() / 2
        dy -= self.tm.template.tile_height_d() / 2
        topleft_vx, topleft_vy = self.cs.convert_d_to_v((dx, dy))

        width_px = self.tm.template.width_p()
        height_px = self.tm.template.height_p()
        theta = self.tm.template.rotation
        use_rotation = theta > 0

        font = QFont()
        grid_colour_rgb = self.tm.template.display_colour_rgb()
        grid_colour = QColor(*grid_colour_rgb, 255)

        visible = self._vp_element_visible(
            topleft_vx, topleft_vy, width_px, height_px, resize_ratio,
            origin_vx, origin_vy, theta)

        # Proceed only if at least a part of the grid is visible
        if not visible:
            return

        # Rotate the painter if grid has a rotation angle > 0
        if use_rotation:
            # Translate painter to coordinates of grid origin, then rotate
            self.vp_qp.translate(origin_vx, origin_vy)
            self.vp_qp.rotate(theta)
            # Translate to top-left corner
            self.vp_qp.translate(
                -self.tm.template.tile_width_d() / 2 * self.cs.vp_scale,
                -self.tm.template.tile_height_d() / 2 * self.cs.vp_scale)
            # Enable anti-aliasing in this case:
            # self.vp_qp.setRenderHint(QPainter.Antialiasing)
            # TODO: Try Antialiasing again - advantageous or not? What about
            # Windows 7 vs Windows 10?
        else:
            # Translate painter to coordinates of top-left corner
            self.vp_qp.translate(topleft_vx, topleft_vy)

        # Show grid label in upper left corner
        if self.show_labels:
            fontsize = int(self.cs.vp_scale * 8)
            if fontsize < 12:
                fontsize = 12
            font.setPixelSize(fontsize)
            self.vp_qp.setFont(font)
            self.vp_qp.setPen(grid_colour)
            self.vp_qp.setBrush(grid_colour)
            if self.tm.template.active:
                width_factor = 5.3
            else:
                width_factor = 10.5
            grid_label_rect = QRect(0,
                                    -int(4/3 * fontsize),
                                    int(width_factor * fontsize),
                                    int(4/3 * fontsize))
            self.vp_qp.drawRect(grid_label_rect)
            if self.tm.template.display_colour in [1, 2, 3]:
            # Use black for light and white for dark background colour
                self.vp_qp.setPen(QColor(0, 0, 0))
            else:
                self.vp_qp.setPen(QColor(255, 255, 255))

            self.vp_qp.drawText(grid_label_rect,
                                Qt.AlignVCenter | Qt.AlignHCenter,
                                'TEMPLATE')

        # Tile grid in pixels (coordinates not rotated)
        tile_map = self.tm.template.tile_positions_p()

        tile_width_v = self.tm.template.tile_width_d() * self.cs.vp_scale
        tile_height_v = self.tm.template.tile_height_d() * self.cs.vp_scale

        # Display grid lines
        rows, cols = self.tm.template.size
        grid_pen = QPen(grid_colour, 1, Qt.SolidLine)
        grid_brush_active_tile = QBrush(QColor(*grid_colour_rgb, 40),
                                        Qt.SolidPattern)
        if tile_width_v * cols > 2 or tile_height_v * rows > 2:
            # Draw grid if at least 3 pixels wide or high.
            for tile_index in range(rows * cols):
                self.vp_qp.setPen(grid_pen)
                self.vp_qp.setBrush(grid_brush_active_tile)
                # Draw tile rectangles.
                self.vp_qp.drawRect(
                    tile_map[tile_index][0] * resize_ratio,
                    tile_map[tile_index][1] * resize_ratio,
                    tile_width_v, tile_height_v)
        else:
            # Show the grid as a single pixel (for performance reasons when
            # zoomed out).
            self.vp_qp.setPen(grid_pen)
            self.vp_qp.drawPoint(tile_map[0][0] * resize_ratio,
                                 tile_map[0][1] * resize_ratio)

        # Reset painter (undo translation and rotation).
        self.vp_qp.resetTransform()

        # ---- Autofocus points in MagC mode ---- #
        if self.gm.magc_mode:
            focus_point_brush = QBrush(QColor(Qt.red), Qt.SolidPattern)
            self.vp_qp.setBrush(focus_point_brush)
            for autofocus_point in self.gm[grid_index].magc_autofocus_points:
                autofocus_point_v = self.cs.convert_to_v(autofocus_point)
                diameter = 2 * self.cs.vp_scale
                self.vp_qp.drawEllipse(
                    autofocus_point_v[0]-diameter/2,
                    autofocus_point_v[1]-diameter/2,
                    diameter,
                    diameter)
        #-----------------------------------------#

        # ---- Polygon ROI if MultiSEM ---- #
        if 'multisem' in self.sem.device_name.lower():
            roi_point_brush = QBrush(QColor(Qt.green), Qt.SolidPattern)
            self.vp_qp.setBrush(roi_point_brush)
            self.vp_qp.setPen(grid_pen)

            polyroi_number = len(self.gm[grid_index].magc_polyroi_points)
            for id,polyroi_point in enumerate(
                self.gm[grid_index].magc_polyroi_points):
                polyroi_point_v = self.cs.convert_to_v(polyroi_point)
                diameter = 2 * self.cs.vp_scale
                self.vp_qp.drawEllipse(
                    polyroi_point_v[0]-diameter/2,
                    polyroi_point_v[1]-diameter/2,
                    diameter,
                    diameter)

                next_polyroi_point_v = self.cs.convert_to_v(
                    self.gm[grid_index]
                        .magc_polyroi_points[(id+1)%polyroi_number])
                self.vp_qp.drawLine(
                    polyroi_point_v[0],
                    polyroi_point_v[1],
                    next_polyroi_point_v[0],
                    next_polyroi_point_v[1])
        #-------------------------------------#

    def _vp_draw_stage_boundaries(self):
        """Calculate and show bounding box around the area accessible to the
        stage motors."""
        x_min, x_max, y_min, y_max = self.stage.limits
        b_left = self.cs.convert_d_to_v(self.cs.convert_s_to_d((x_min, y_min)))
        b_top = self.cs.convert_d_to_v(self.cs.convert_s_to_d((x_max, y_min)))
        b_right = self.cs.convert_d_to_v(self.cs.convert_s_to_d((x_max, y_max)))
        b_bottom = self.cs.convert_d_to_v(self.cs.convert_s_to_d((x_min, y_max)))
        self.vp_qp.setPen(QColor(255, 255, 255))
        self.vp_qp.drawLine(b_left[0], b_left[1], b_top[0], b_top[1])
        self.vp_qp.drawLine(b_top[0], b_top[1], b_right[0], b_right[1])
        self.vp_qp.drawLine(b_right[0], b_right[1], b_bottom[0], b_bottom[1])
        self.vp_qp.drawLine(b_bottom[0], b_bottom[1], b_left[0], b_left[1])
        if self.show_labels:
            # Show coordinates of stage corners.
            font = QFont()
            font.setPixelSize(12)
            self.vp_qp.setFont(font)
            self.vp_qp.drawText(b_left[0] - 75, b_left[1],
                                'X: {0:.0f} µm'.format(x_min))
            self.vp_qp.drawText(b_left[0] - 75, b_left[1] + 15,
                                'Y: {0:.0f} µm'.format(y_min))
            self.vp_qp.drawText(b_top[0] - 20, b_top[1] - 25,
                                'X: {0:.0f} µm'.format(x_max))
            self.vp_qp.drawText(b_top[0] - 20, b_top[1] - 10,
                                'Y: {0:.0f} µm'.format(y_min))
            self.vp_qp.drawText(b_right[0] + 10, b_right[1],
                                'X: {0:.0f} µm'.format(x_max))
            self.vp_qp.drawText(b_right[0] + 10, b_right[1] + 15,
                                'Y: {0:.0f} µm'.format(y_max))
            self.vp_qp.drawText(b_bottom[0] - 20, b_bottom[1] + 15,
                                'X: {0:.0f} µm'.format(x_min))
            self.vp_qp.drawText(b_bottom[0] - 20, b_bottom[1] + 30,
                                'Y: {0:.0f} µm'.format(y_max))

    def _vp_draw_stage_axes(self):
        """Calculate and show the x axis and the y axis of the stage."""
        x_min, x_max, y_min, y_max = self.stage.limits
        x_axis_start = self.cs.convert_d_to_v(
            self.cs.convert_s_to_d((x_min - 100, 0)))
        x_axis_end = self.cs.convert_d_to_v(
            self.cs.convert_s_to_d((x_max + 100, 0)))
        y_axis_start = self.cs.convert_d_to_v(
            self.cs.convert_s_to_d((0, y_min - 100)))
        y_axis_end = self.cs.convert_d_to_v(
            self.cs.convert_s_to_d((0, y_max + 100)))
        self.vp_qp.setPen(QPen(QColor(255, 255, 255), 1, Qt.DashLine))
        self.vp_qp.drawLine(x_axis_start[0], x_axis_start[1],
                            x_axis_end[0], x_axis_end[1])
        self.vp_qp.drawLine(y_axis_start[0], y_axis_start[1],
                            y_axis_end[0], y_axis_end[1])
        if self.show_labels:
            font = QFont()
            font.setPixelSize(12)
            self.vp_qp.drawText(x_axis_end[0] + 10, x_axis_end[1],
                                'stage x-axis')
            self.vp_qp.drawText(y_axis_end[0] + 10, y_axis_end[1] + 10,
                                'stage y-axis')

    def _vp_set_measure_point(self, px, py):
        """Convert pixel coordinates where mouse was clicked to SEM coordinates
        in Viewport for starting or end point of measurement."""
        if self.measure_p1[0] is None or self.measure_complete:
            self.measure_p1 = self.cs.convert_mouse_to_v((px, py))
            self.measure_complete = False
            self.measure_p2 = (None, None)
        else:
            self.measure_p2 = self.cs.convert_mouse_to_v((px, py))
        self.vp_draw()

    def _vp_draw_zoom_delay(self):
        """Redraw the viewport without suppressing labels/previews after at
        least 0.3 seconds have passed since last mouse/slider zoom action."""
        finish_trigger = utils.Trigger()
        finish_trigger.signal.connect(self.vp_draw)
        current_time = self.time_of_last_zoom_action
        while (current_time - self.time_of_last_zoom_action < 0.3):
            sleep(0.1)
            current_time += 0.1
        self.zooming_in_progress = False
        finish_trigger.signal.emit()

    def vp_adjust_zoom_slider(self):
        """Adjust the position of the viewport sliders according to the current
        viewport scaling."""
        self.horizontalSlider_VP.blockSignals(True)
        self.horizontalSlider_VP.setValue(
            log(self.cs.vp_scale / self.VP_ZOOM[0], self.VP_ZOOM[1]))
        self.horizontalSlider_VP.blockSignals(False)

    def _vp_adjust_scale_from_slider(self):
        """Adjust the viewport scale according to the value currently set with
        the viewport slider. Recalculate the scaling factor and redraw the
        canvas."""
        self.time_of_last_zoom_action = time()
        if not self.zooming_in_progress:
            # Start thread to ensure viewport is drawn with labels and previews
            # after zooming completed.
            self.zooming_in_progress = True
            utils.run_log_thread(self._vp_draw_zoom_delay)
        # Recalculate scaling factor.
        self.cs.vp_scale = (
            self.VP_ZOOM[0]
            * (self.VP_ZOOM[1])**self.horizontalSlider_VP.value())
        # Redraw viewport with labels and previews suppressed.
        self.vp_draw(suppress_labels=True, suppress_previews=True)

    def _vp_mouse_zoom(self, px, py, factor):
        """Zoom with factor after user double-clicks at position px, py."""
        self.time_of_last_zoom_action = time()
        if not self.zooming_in_progress and not self.doubleclick_registered:
            # Start thread to ensure viewport is drawn with labels and previews
            # after zooming completed.
            self.zooming_in_progress = True
            utils.run_log_thread(self._vp_draw_zoom_delay)
        # Recalculate scaling factor.
        old_vp_scale = self.cs.vp_scale
        self.cs.vp_scale = utils.fit_in_range(
            factor * old_vp_scale,
            self.VP_ZOOM[0],
            self.VP_ZOOM[0] * (self.VP_ZOOM[1])**99)  # 99 is max slider value
        self.vp_adjust_zoom_slider()
        # Recentre, so that mouse position is preserved.
        current_centre_dx, current_centre_dy = self.cs.vp_centre_dx_dy
        x_shift = px - self.cs.vp_width // 2
        y_shift = py - self.cs.vp_height // 2
        scale_diff = 1 / self.cs.vp_scale - 1 / old_vp_scale
        new_centre_dx = current_centre_dx - x_shift * scale_diff
        new_centre_dy = current_centre_dy - y_shift * scale_diff
        new_centre_dx = utils.fit_in_range(
            new_centre_dx, self.VC_MIN_X, self.VC_MAX_X)
        new_centre_dy = utils.fit_in_range(
            new_centre_dy, self.VC_MIN_Y, self.VC_MAX_Y)
        # Set new vp_centre coordinates.
        self.cs.vp_centre_dx_dy = [new_centre_dx, new_centre_dy]
        # Redraw viewport.
        if self.doubleclick_registered:
            # Doubleclick is (usually) a single event: draw with labels/previews
            self.vp_draw()
        else:
            # Continuous zoom with the mouse wheel: Suppress previews
            # for smoother redrawing.
            self.vp_draw(suppress_labels=False, suppress_previews=True)

    def _vp_shift_fov(self, shift_vector):
        """Shift the Viewport's field of view (FOV) by shift_vector."""
        dx, dy = shift_vector
        current_centre_dx, current_centre_dy = self.cs.vp_centre_dx_dy
        new_centre_dx = current_centre_dx + dx / self.cs.vp_scale
        new_centre_dy = current_centre_dy + dy / self.cs.vp_scale
        new_centre_dx = utils.fit_in_range(
            new_centre_dx, self.VC_MIN_X, self.VC_MAX_X)
        new_centre_dy = utils.fit_in_range(
            new_centre_dy, self.VC_MIN_Y, self.VC_MAX_Y)
        self.cs.vp_centre_dx_dy = [new_centre_dx, new_centre_dy]
        self.vp_draw()

    def _vp_reposition_ov(self, shift_vector):
        """Shift the OV selected by the mouse click (self.selected_ov) by
        shift_vector."""
        dx, dy = shift_vector
        old_ov_dx, old_ov_dy = self.ovm[self.selected_ov].centre_dx_dy
        # Move OV along shift vector.
        new_ov_dx = old_ov_dx + dx / self.cs.vp_scale
        new_ov_dy = old_ov_dy + dy / self.cs.vp_scale
        # Set new OV centre and redraw.
        self.ovm[self.selected_ov].centre_sx_sy = self.cs.convert_d_to_s(
            (new_ov_dx, new_ov_dy))
        self.vp_draw()

    def _vp_reposition_template(self, shift_vector):
        """Shift the template by the mouse click (self.selected_ov) by
        shift_vector."""
        dx, dy = shift_vector
        old_ov_dx, old_ov_dy = self.tm.template.origin_dx_dy
        # Move OV along shift vector.
        new_ov_dx = old_ov_dx + dx / self.cs.vp_scale
        new_ov_dy = old_ov_dy + dy / self.cs.vp_scale
        # Set new OV centre and redraw.

        self.tm.template.origin_sx_sy = self.cs.convert_d_to_s(
            (new_ov_dx, new_ov_dy))
        self.vp_draw()

    def _vp_place_grids_template_matching(self):
        """Find candidate locations and place grids in VP using template matching."""
        self.tm.place_grids_template_matching(self.gm)
        self.main_controls_trigger.transmit('GRID SETTINGS CHANGED')

    def _vp_reposition_imported_img(self, shift_vector):
        """Shift the imported image selected by the mouse click
        (self.selected_imported) by shift_vector."""
        dx, dy = shift_vector
        old_origin_dx, old_origin_dy = self.cs.convert_s_to_d(
            self.imported[self.selected_imported].centre_sx_sy)
        new_origin_dx = old_origin_dx + dx / self.cs.vp_scale
        new_origin_dy = old_origin_dy + dy / self.cs.vp_scale
        # Set new centre coordinates.
        self.imported[self.selected_imported].centre_sx_sy = (
            self.cs.convert_d_to_s((new_origin_dx, new_origin_dy)))
        self.vp_draw()

    def _vp_reposition_grid(self, shift_vector):
        """Shift the grid selected by the mouse click (self.selected_grid)
        by shift_vector."""
        dx, dy = shift_vector
        old_grid_origin_dx, old_grid_origin_dy = (
            self.gm[self.selected_grid].origin_dx_dy)
        new_grid_origin_dx = old_grid_origin_dx + dx / self.cs.vp_scale
        new_grid_origin_dy = old_grid_origin_dy + dy / self.cs.vp_scale
        # Set new grid origin and redraw.
        self.gm[self.selected_grid].origin_sx_sy = (
            self.cs.convert_d_to_s((new_grid_origin_dx, new_grid_origin_dy)))
        self.vp_draw()

    def _vp_grid_tile_mouse_selection(self, px, py):
        """Get the grid index and tile index at the position in the viewport
        where user has clicked.
        """
        if self.vp_current_grid == -2:  # grids are hidden
            grid_range = []
            selected_grid, selected_tile = None, None
        elif self.vp_current_grid == -1:  # all grids visible
            grid_range = reversed(range(self.gm.number_grids))
            selected_grid, selected_tile = None, None
        elif self.vp_current_grid >= 0:  # one selected grid visible
            grid_range = range(self.vp_current_grid, self.vp_current_grid + 1)
            selected_grid, selected_tile = self.vp_current_grid, None

        # Go through all visible grids to check for overlap with mouse click
        # position. Check grids with a higher grid index first.
        for grid_index in grid_range:
            # Calculate origin of the grid with respect to viewport canvas
            dx, dy = self.gm[grid_index].origin_dx_dy
            grid_origin_vx, grid_origin_vy = self.cs.convert_d_to_v((dx, dy))
            pixel_size = self.gm[grid_index].pixel_size
            # Calculate top-left corner of unrotated grid
            dx -= self.gm[grid_index].tile_width_d() / 2
            dy -= self.gm[grid_index].tile_height_d() / 2
            grid_topleft_vx, grid_topleft_vy = self.cs.convert_d_to_v((dx, dy))
            cols = self.gm[grid_index].number_cols()
            rows = self.gm[grid_index].number_rows()
            overlap = self.gm[grid_index].overlap
            tile_width_p = self.gm[grid_index].tile_width_p()
            tile_height_p = self.gm[grid_index].tile_height_p()
            # Tile width in viewport pixels taking overlap into account
            tile_width_v = ((tile_width_p - overlap) * pixel_size
                            / 1000 * self.cs.vp_scale)
            tile_height_v = ((tile_height_p - overlap) * pixel_size
                             / 1000 * self.cs.vp_scale)
            # Row shift in viewport pixels
            shift_v = (self.gm[grid_index].row_shift * pixel_size
                       / 1000 * self.cs.vp_scale)
            # Mouse click position relative to top-left corner of grid
            x, y = px - grid_topleft_vx, py - grid_topleft_vy
            theta = radians(self.gm[grid_index].rotation)
            if theta > 0:
                # Rotate the mouse click coordinates if grid is rotated.
                # Use grid origin as pivot.
                x, y = px - grid_origin_vx, py - grid_origin_vy
                # Inverse rotation for (x, y).
                x_rot = x * cos(-theta) - y * sin(-theta)
                y_rot = x * sin(-theta) + y * cos(-theta)
                x, y = x_rot, y_rot
                # Correction for top-left corner.
                x += tile_width_p / 2 * pixel_size / 1000 * self.cs.vp_scale
                y += tile_height_p / 2 * pixel_size / 1000 * self.cs.vp_scale

            if not 'multisem' in self.sem.device_name.lower():
                # Check if mouse click position is within current grid's tile area
                # if the current grid is active
                if self.gm[grid_index].active and x >= 0 and y >= 0:
                    j = y // tile_height_v
                    if j % 2 == 0:
                        i = x // tile_width_v
                    elif x > shift_v:
                        # Subtract shift for odd rows
                        i = (x - shift_v) // tile_width_v
                    else:
                        i = cols
                    if (i < cols) and (j < rows):
                        selected_tile = int(i + j * cols)
                        selected_grid = grid_index
                        break
            else: # Check if mouse click position is within current ROI.
                polyroi_s = self.gm[grid_index].magc_polyroi_points
                if len(polyroi_s) > 2:
                    polyroi_v = [
                        self.cs.convert_to_v(point)
                        for point in polyroi_s]
                    if utils.is_point_inside_polygon((px, py), polyroi_v):
                        selected_grid = grid_index
                        break

            # Also check whether grid label clicked. This selects only the grid
            # and not a specific tile.
            f = int(self.cs.vp_scale * 8)
            if f < 12:
                f = 12
            # Active and inactive grids have different label widths
            if self.gm[grid_index].active:
                width_factor = 5.3
            else:
                width_factor = 10.5
            label_width = int(width_factor * f)
            label_height = int(4/3 * f)
            l_y = y + label_height
            if x >= 0 and l_y >= 0 and selected_grid is None:
                if x < label_width and l_y < label_height:
                    selected_grid = grid_index
                    selected_tile = None
                    break

        return selected_grid, selected_tile

    def _vp_ov_mouse_selection(self, px, py):
        """Return the index of the OV at the position in the viewport
        where user has clicked."""
        if self.vp_current_ov == -2:
            selected_ov = None
        elif self.vp_current_ov == -1:
            selected_ov = None
            for ov_index in reversed(range(self.ovm.number_ov)):
                # Calculate origin of the overview with respect to mosaic viewer
                dx, dy = self.ovm[ov_index].centre_dx_dy
                dx -= self.ovm[ov_index].width_d() / 2
                dy -= self.ovm[ov_index].height_d() / 2
                pixel_offset_x, pixel_offset_y = self.cs.convert_d_to_v((dx, dy))
                p_width = self.ovm[ov_index].width_d() * self.cs.vp_scale
                p_height = self.ovm[ov_index].height_d() * self.cs.vp_scale
                x, y = px - pixel_offset_x, py - pixel_offset_y
                # Check if the current OV is active and if mouse click position
                # is within its area
                if self.ovm[ov_index].active and x >= 0 and y >= 0:
                    if x < p_width and y < p_height:
                        selected_ov = ov_index
                        break
                    else:
                        selected_ov = None
                # Also check whether label clicked.
                f = int(self.cs.vp_scale * 8)
                if f < 12:
                    f = 12
                if self.ovm[ov_index].active:
                    width_factor = 3.6
                else:
                    width_factor = 9
                label_width = int(f * width_factor)
                label_height = int(4/3 * f)
                l_y = y + label_height
                if x >= 0 and l_y >= 0 and selected_ov is None:
                    if x < label_width and l_y < label_height:
                        selected_ov = ov_index
                        break
        elif self.vp_current_ov >= 0:
            selected_ov = self.vp_current_ov
        return selected_ov

    def _vp_imported_img_mouse_selection(self, px, py):
        """Return the index of the imported image at the position in the
        viewport where user has clicked."""
        if self.show_imported:
            for i in reversed(range(self.imported.number_imported)):
                # Calculate origin of the image with respect to the viewport.
                # Use width and heigh of the QPixmap (may be rotated
                # and therefore larger than original image).
                if self.imported[i].image is not None:
                    dx, dy = self.cs.convert_s_to_d(
                        self.imported[i].centre_sx_sy)
                    pixel_size = self.imported[i].pixel_size
                    width_d = (self.imported[i].image.size().width()
                               * pixel_size / 1000)
                    height_d = (self.imported[i].image.size().height()
                                * pixel_size / 1000)
                    dx -= width_d / 2
                    dy -= height_d / 2
                    pixel_offset_x, pixel_offset_y = self.cs.convert_d_to_v(
                        (dx, dy))
                    p_width = width_d * self.cs.vp_scale
                    p_height = height_d * self.cs.vp_scale
                    x, y = px - pixel_offset_x, py - pixel_offset_y
                    if x >= 0 and y >= 0:
                        if x < p_width and y < p_height:
                            return i
        return None

    def _vp_template_mouse_selection(self, px, py):
        if self.tm.template.origin_sx_sy is None:  # no template exists
            return False
        # Calculate origin of the grid with respect to viewport canvas
        selected_template = False
        template = self.tm.template
        dx, dy = template.origin_dx_dy
        grid_origin_vx, grid_origin_vy = self.cs.convert_d_to_v((dx, dy))
        pixel_size = template.pixel_size
        # Calculate top-left corner of unrotated grid
        dx -= template.tile_width_d() / 2
        dy -= template.tile_height_d() / 2
        grid_topleft_vx, grid_topleft_vy = self.cs.convert_d_to_v((dx, dy))
        cols = template.number_cols()
        rows = template.number_rows()
        overlap = template.overlap
        tile_width_p = template.tile_width_p()
        tile_height_p = template.tile_height_p()
        # Tile width in viewport pixels taking overlap into account
        tile_width_v = ((tile_width_p - overlap) * pixel_size
                        / 1000 * self.cs.vp_scale)
        tile_height_v = ((tile_height_p - overlap) * pixel_size
                         / 1000 * self.cs.vp_scale)
        # Row shift in viewport pixels
        shift_v = (template.row_shift * pixel_size
                   / 1000 * self.cs.vp_scale)
        # Mouse click position relative to top-left corner of grid
        x, y = px - grid_topleft_vx, py - grid_topleft_vy
        theta = radians(template.rotation)
        if theta > 0:
            # Rotate the mouse click coordinates if grid is rotated.
            # Use grid origin as pivot.
            x, y = px - grid_origin_vx, py - grid_origin_vy
            # Inverse rotation for (x, y).
            x_rot = x * cos(-theta) - y * sin(-theta)
            y_rot = x * sin(-theta) + y * cos(-theta)
            x, y = x_rot, y_rot
            # Correction for top-left corner.
            x += tile_width_p / 2 * pixel_size / 1000 * self.cs.vp_scale
            y += tile_height_p / 2 * pixel_size / 1000 * self.cs.vp_scale
        # Check if mouse click position is within current grid's tile area
        # if the current grid is active
        if template.active and x >= 0 and y >= 0:
            j = y // tile_height_v
            if j % 2 == 0:
                i = x // tile_width_v
            elif x > shift_v:
                # Subtract shift for odd rows.
                i = (x - shift_v) // tile_width_v
            else:
                i = cols
            if (i < cols) and (j < rows):
                selected_template = True

        # Also check whether template label clicked. This selects only the grid
        # and not a specific tile.
        f = int(self.cs.vp_scale * 8)
        if f < 12:
            f = 12
        # Active and inactive grids have different label widths
        if template.active:
            width_factor = 5.3
        else:
            width_factor = 10.5
        label_width = int(width_factor * f)
        label_height = int(4/3 * f)
        l_y = y + label_height
        if x >= 0 and l_y >= 0 and not selected_template:
            if x < label_width and l_y < label_height:
                selected_template = True

        return selected_template

    def vp_activate_all_tiles(self):
        """Activate all tiles in the selected grid (mouse selection)."""
        if self.selected_grid is not None:
            user_reply = QMessageBox.question(
                self, 'Set all tiles in grid to "active"',
                f'This will activate all tiles in grid {self.selected_grid}. '
                f'Proceed?',
                QMessageBox.Ok | QMessageBox.Cancel)
            if user_reply == QMessageBox.Ok:
                self.gm[self.selected_grid].activate_all_tiles()
                if self.autofocus.tracking_mode == 1:
                    self.gm.make_all_active_tiles_autofocus_ref_tiles()
                self._add_to_main_log('CTRL: All tiles in grid %d activated.'
                                     % self.selected_grid)
                self.vp_update_after_active_tile_selection()

    def vp_deactivate_all_tiles(self):
        """Deactivate all tiles in the selected grid (mouse selection)."""
        if self.selected_grid is not None:
            user_reply = QMessageBox.question(
                self, 'Deactivating all tiles in grid',
                f'This will deactivate all tiles in grid {self.selected_grid}. '
                f'Proceed?',
                QMessageBox.Ok | QMessageBox.Cancel)
            if user_reply == QMessageBox.Ok:
                self.gm[self.selected_grid].deactivate_all_tiles()
                if self.autofocus.tracking_mode == 1:
                    self.gm.delete_all_autofocus_ref_tiles()
                self._add_to_main_log('CTRL: All tiles in grid %d deactivated.'
                                     % self.selected_grid)
                self.vp_update_after_active_tile_selection()

    def _vp_open_grid_settings(self):
        self.main_controls_trigger.transmit(
            'OPEN GRID SETTINGS' + str(self.selected_grid))

    def _vp_move_grid_to_current_stage_position(self):
        """Move the selected grid to the current stage position (MagC)."""
        x, y = self.stage.get_xy()
        self.gm[self.selected_grid].centre_sx_sy = [x, y]
        self.gm[self.selected_grid].update_tile_positions()
        self.gm.magc_roi_mode = False
        self.gm.update_source_ROIs_from_grids()
        self.vp_draw()

    def _vp_toggle_tile_autofocus(self):
        """Toggle the autofocus reference status of the currently selected
        tile."""
        if self.selected_grid is not None and self.selected_tile is not None:
            self.gm[self.selected_grid][
                    self.selected_tile].autofocus_active ^= True
            self.vp_draw()

    def _vp_toggle_wd_gradient_ref_tile(self):
        """Toggle the wd gradient reference status of the currently selected
        tile."""
        if self.selected_grid is not None and self.selected_tile is not None:
            ref_tiles = self.gm[self.selected_grid].wd_gradient_ref_tiles
            if self.selected_tile in ref_tiles:
                ref_tiles[ref_tiles.index(self.selected_tile)] = -1
            else:
                # Let user choose the intended relative position of the tile:
                dialog = FocusGradientTileSelectionDlg(ref_tiles)
                if dialog.exec_():
                    if dialog.selected is not None:
                        ref_tiles[dialog.selected] = self.selected_tile
            self.gm[self.selected_grid].wd_gradient_ref_tiles = ref_tiles
            self.main_controls_trigger.transmit('UPDATE FT TILE SELECTOR')
            self.vp_draw()

    def _vp_toggle_measure(self):
        self.vp_measure_active = not self.vp_measure_active
        if self.vp_measure_active:
            self.sv_measure_active = False
        self.measure_p1 = (None, None)
        self.measure_p2 = (None, None)
        self.measure_complete = False
        self._update_measure_buttons()
        self.vp_draw()

    def vp_toggle_help_panel(self):
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
        self.vp_draw()
        self.sv_draw()

    def _vp_manual_stage_move(self):
        utils.log_info('CTRL', 'Performing user-requested stage move.')
        self.main_controls_trigger.transmit('RESTRICT GUI')
        self.restrict_gui(True)
        QApplication.processEvents()
        utils.run_log_thread(acq_func.manual_stage_move,
                             self.stage,
                             self.selected_stage_pos,
                             self.viewport_trigger)
        self.main_controls_trigger.transmit('STATUS BUSY STAGE MOVE')

    def _vp_manual_stage_move_success(self, success):
        # Show new stage position in Main Controls GUI
        self.main_controls_trigger.transmit('UPDATE XY')
        if success:
            utils.log_info('CTRL', 'User-requested stage move completed.')
        else:
            utils.log_error('CTRL', 'ERROR ocurred during manual stage move.')
            QMessageBox.warning(
                self, 'Error during stage move',
                'An error occurred during the requested stage move: '
                'The target position could not be reached after two attempts. '
                'Please check the status of your microtome or SEM stage.',
                QMessageBox.Ok)
        self.vp_draw()
        self.restrict_gui(False)
        self.main_controls_trigger.transmit('UNRESTRICT GUI')
        self.main_controls_trigger.transmit('STATUS IDLE')

    def vp_acquire_overview(self):
        """Acquire one selected or all overview images."""
        if self.vp_current_ov > -2:
            user_reply = None
            if (self.vp_current_ov == -1) and (self.ovm.number_ov > 1):
                user_reply = QMessageBox.question(
                    self, 'Acquisition of all overview images',
                    'This will acquire all active overview images.\n\n' +
                    'Do you wish to proceed?',
                    QMessageBox.Ok | QMessageBox.Cancel)
            if (user_reply == QMessageBox.Ok or self.vp_current_ov >= 0
                or (self.ovm.number_ov == 1 and self.vp_current_ov == -1)):
                self._add_to_main_log(
                    'CTRL: User-requested acquisition of OV image(s) started.')
                self.restrict_gui(True)
                self.main_controls_trigger.transmit('RESTRICT GUI')
                self.main_controls_trigger.transmit('STATUS BUSY OV')
                # Start OV acquisition thread
                utils.run_log_thread(acq_func.acquire_ov,
                                     self.acq.base_dir, self.vp_current_ov,
                                     self.sem, self.stage, self.ovm, self.img_inspector,
                                     self.main_controls_trigger, self.viewport_trigger)
        else:
            QMessageBox.information(
                self, 'Acquisition of overview image(s)',
                'Please select "All OVs" or a single OV from the '
                'pull-down menu.',
                QMessageBox.Ok)

    def _vp_overview_acq_success(self, success):
        if success:
            self._add_to_main_log(
                'CTRL: User-requested acquisition of overview(s) completed.')
        else:
            self._add_to_main_log(
                'CTRL: ERROR ocurred during acquisition of overview(s).')
            QMessageBox.warning(
                self, 'Error during overview acquisition',
                'An error occurred during the acquisition of the overview(s) '
                'at the current location(s). Please check the log for more '
                'information. If the stage failed to move to the target OV '
                'position, the most likely causes are incorrect XY stage '
                'limits or incorrect motors speeds.', QMessageBox.Ok)
        self.main_controls_trigger.transmit('UNRESTRICT GUI')
        self.restrict_gui(False)
        self.main_controls_trigger.transmit('STATUS IDLE')

    def _vp_open_stub_overview_dlg(self):
        centre_sx_sy = self.stub_ov_centre
        if centre_sx_sy[0] is None:
            # Use the last known position
            centre_sx_sy = self.ovm['stub'].centre_sx_sy
        dialog = StubOVDlg(centre_sx_sy,
                           self.sem, self.stage, self.ovm, self.acq,
                           self.img_inspector,
                           self.viewport_trigger)
        dialog.exec_()

    def _vp_stub_overview_acq_success(self, success):
        if success:
            self._add_to_main_log(
                'CTRL: Acquisition of stub overview image completed.')
            # Load and show new OV images:
            self.vp_show_new_stub_overview()
            # Reset user-selected stub_ov_centre
            self.stub_ov_centre = [None, None]
            # Copy to mirror drive
            if self.acq.use_mirror_drive:
                mirror_path = os.path.join(
                    self.acq.mirror_drive,
                    self.acq.base_dir[2:], 'overviews', 'stub')
                if not os.path.exists(mirror_path):
                    try:
                        os.makedirs(mirror_path)
                    except Exception as e:
                        self._add_to_main_log(
                            'CTRL: Creating directory on mirror drive failed: '
                            + str(e))
                try:
                    shutil.copy(self.ovm['stub'].vp_file_path, mirror_path)
                except Exception as e:
                    self._add_to_main_log(
                        'CTRL: Copying stub overview image to mirror drive '
                        'failed: ' + str(e))
        else:
            self._add_to_main_log('CTRL: ERROR ocurred during stub overview '
                                  'acquisition.')
        self.main_controls_trigger.transmit('STATUS IDLE')

    def _vp_open_change_grid_rotation_dlg(self):
        if self.selected_template:
            dialog = TemplateRotationDlg(self.tm, self.viewport_trigger)
        else:
            dialog = GridRotationDlg(self.selected_grid, self.gm,
                                     self.viewport_trigger, self.sem.magc_mode)
        if dialog.exec_():
            if self.ovm.use_auto_debris_area:
                self.ovm.update_all_debris_detections_areas(self.gm)
                self.vp_draw()

    def _vp_open_import_image_dlg(self):
        target_dir = os.path.join(self.acq.base_dir, 'imported')
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir)
            except Exception as e:
                QMessageBox.warning(
                    self, 'Could not create directory',
                    f'Could not create directory {target_dir} to save imported '
                    f'images. Make sure the drive/folder is available for '
                    f'write access. {str(e)}',
                    QMessageBox.Ok)
                return
        dialog = ImportImageDlg(self.imported, target_dir)
        if dialog.exec_():
            self.vp_draw()

    def _vp_open_adjust_image_dlg(self):
        dialog = AdjustImageDlg(self.imported, self.selected_imported,
                                self.sem.magc_mode, self.viewport_trigger)
        dialog.exec_()

    def _vp_open_delete_image_dlg(self):
        dialog = DeleteImageDlg(self.imported)
        if dialog.exec_():
            self.vp_draw()

    def vp_show_new_stub_overview(self):
        self.checkBox_showStubOV.setChecked(True)
        self.show_stub_ov = True
        self.vp_draw()

    def vp_show_overview_for_user_inspection(self, ov_index):
        """Show the overview image with ov_index in the centre of the Viewport
        with no grids, tile previews or other objects obscuring it.
        """
        # Switch to Viewport tab
        self.tabWidget.setCurrentIndex(0)
        # Preserve previous display settings
        vp_current_ov_prev = self.vp_current_ov
        vp_current_grid_prev = self.vp_current_grid
        vp_centre_dx_dy_prev = self.cs.vp_centre_dx_dy
        vp_scale_prev = self.cs.vp_scale
        # Show ov_index only and hide the grids
        self.vp_current_ov = ov_index
        self.vp_current_grid = -2
        # Position the viewing window and adjust the scale to show the full OV
        self.cs.vp_centre_dx_dy = self.ovm[ov_index].centre_dx_dy
        self.cs.vp_scale = (self.cs.vp_width - 100) / self.ovm[ov_index].width_d()
        self.vp_draw(suppress_labels=False, suppress_previews=True)
        # Revert to previous settings
        self.vp_current_ov = vp_current_ov_prev
        self.vp_current_grid = vp_current_grid_prev
        self.cs.vp_centre_dx_dy = vp_centre_dx_dy_prev
        self.cs.vp_scale = vp_scale_prev

    # ---------------------- MagC methods in Viewport --------------------------

    def vp_propagate_grid_properties_to_selected_sections(self):
        # TODO
        clicked_section_number = self.selected_grid

        # load original sections from file which might be different from
        # the grids adjusted in SBEMImage
        with open(self.gm.magc_sections_path, 'r') as f:
            sections, landmarks = utils.sectionsYAML_to_sections_landmarks(
            yaml.full_load(f))

        for selected_section in self.gm.magc_selected_sections:
            self.gm.propagate_source_grid_properties_to_target_grid(
                clicked_section_number,
                selected_section,
                sections)
        self.gm.update_source_ROIs_from_grids()
        self.vp_draw()
        self.main_controls_trigger.transmit('SHOW CURRENT SETTINGS') # update statistics in GUI
        self._add_to_main_log('Properties of grid '
            + str(clicked_section_number)
            + ' have been propagated to the selected sections')

    def vp_propagate_grid_properties_to_all_sections(self):
        # TODO
        clicked_section_number = self.selected_grid
        n_sections = self.gm.number_grids

        if self.gm.magc_sections_path != '':
            # load original sections from file which might be different from
            # the grids adjusted in SBEMImage
            with open(self.gm.magc_sections_path, 'r') as f:
                sections, landmarks = utils.sectionsYAML_to_sections_landmarks(
                yaml.full_load(f))
            for section in range(n_sections):
                self.gm.propagate_source_grid_properties_to_target_grid(
                    clicked_section_number,
                    section,
                    sections)

            self.gm.update_source_ROIs_from_grids()

            self.vp_draw()
            self.main_controls_trigger.transmit('SHOW CURRENT SETTINGS') # update statistics in GUI
            self.add_to_log('Properties of grid '
                + str(clicked_section_number)
                + ' have been propagated to all sections')

    def vp_revert_grid_location_to_file(self):
        clicked_section_number = self.selected_grid
        # load original sections from file which might be different from
        # the grids adjusted in SBEMImage
        with open(self.gm.magc_sections_path, 'r') as f:
            sections, landmarks = utils.sectionsYAML_to_sections_landmarks(
            yaml.full_load(f))

        source_location = sections[clicked_section_number]['center']
        # source_location is in LM image pixel coordinates
        if not self.cs.magc_wafer_calibrated:
            (self.gm[clicked_section_number]
                .centre_sx_sy) = list(map(float, source_location))
        else:
            # transform into wafer coordinates
            result = utils.applyAffineT(
                [source_location[0]],
                [source_location[1]],
                self.cs.magc_wafer_transform)
            target_location = [result[0][0], result[1][0]]
            self.gm[clicked_section_number].centre_sx_sy = target_location

        self.vp_draw()
        self.gm.update_source_ROIs_from_grids()
        self.main_controls_trigger.transmit('SHOW CURRENT SETTINGS') # update statistics in GUI

    # -------------------- End of MagC methods in Viewport ---------------------


# ================= Below: Slice-by-Slice Viewer (sv) methods ==================

    def _sv_initialize(self):
        self.slice_view_images = []
        self.slice_view_index = 0    # slice_view_index: 0..max_slices
        self.max_slices = 10         # default 10, can be increased by user
        # sv_current_grid, sv_current_tile and sv_current_ov stored the
        # indices currently selected in the drop-down lists.
        self.sv_current_grid = int(self.cfg['viewport']['sv_current_grid'])
        self.sv_current_tile = int(self.cfg['viewport']['sv_current_tile'])
        self.sv_current_ov = int(self.cfg['viewport']['sv_current_ov'])
        # display options
        self.show_native_res = (
            self.cfg['viewport']['show_native_resolution'].lower() == 'true')
        self.show_saturated_pixels = (
            self.cfg['viewport']['show_saturated_pixels'].lower() == 'true')

        self.sv_measure_active = False
        self.sv_canvas = QPixmap(self.cs.vp_width, self.cs.vp_height)
        # Help panel:
        self.sv_help_panel_img = QPixmap('..\\img\\help-sliceviewer.png')
        self.sv_qp = QPainter()

        self.pushButton_reloadSV.clicked.connect(self.sv_load_slices)
        self.pushButton_measureSliceViewer.clicked.connect(
            self.sv_toggle_measure)
        self.pushButton_measureSliceViewer.setIcon(
            QIcon('..\\img\\measure.png'))
        self.pushButton_measureSliceViewer.setIconSize(QSize(16, 16))
        self.pushButton_measureSliceViewer.setToolTip(
            'Measure with right mouse clicks')
        self.pushButton_sliceBWD.clicked.connect(self.sv_slice_bwd)
        self.pushButton_sliceFWD.clicked.connect(self.sv_slice_fwd)

        self.horizontalSlider_SV.valueChanged.connect(
            self._sv_adjust_scale_from_slider)
        self._sv_adjust_zoom_slider()

        self.comboBox_gridSelectorSV.currentIndexChanged.connect(
            self.sv_change_grid_selection)
        self.sv_update_grid_selector()
        self.comboBox_tileSelectorSV.currentIndexChanged.connect(
            self.sv_change_tile_selection)
        self.sv_update_tile_selector()
        self.comboBox_OVSelectorSV.currentIndexChanged.connect(
            self.sv_change_ov_selection)
        self.sv_update_ov_selector()

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
        self.spinBox_maxSlices.valueChanged.connect(self.sv_update_max_slices)
        # Show empty slice viewer canvas with instructions.
        self.sv_canvas.fill(Qt.black)
        self.sv_qp.begin(self.sv_canvas)
        self.sv_qp.setPen(QColor(255, 255, 255))
        position_rect = QRect(150, 380, 700, 40)
        self.sv_qp.drawRect(position_rect)
        self.sv_qp.drawText(
            position_rect, Qt.AlignVCenter | Qt.AlignHCenter,
            'Select tile or overview from controls below and click "(Re)load" '
            'to display the images from the most recent slices.')
        self.sv_instructions_displayed = True
        self.sv_qp.end()
        self.QLabel_SliceViewerCanvas.setPixmap(self.sv_canvas)

    def sv_update_grid_selector(self):
        if self.sv_current_grid >= self.gm.number_grids:
            self.sv_current_grid = 0
        self.comboBox_gridSelectorSV.blockSignals(True)
        self.comboBox_gridSelectorSV.clear()
        self.comboBox_gridSelectorSV.addItems(self.gm.grid_selector_list())
        self.comboBox_gridSelectorSV.setCurrentIndex(self.sv_current_grid)
        self.comboBox_gridSelectorSV.blockSignals(False)

    def sv_update_tile_selector(self):
        self.comboBox_tileSelectorSV.blockSignals(True)
        self.comboBox_tileSelectorSV.clear()
        self.comboBox_tileSelectorSV.addItems(
            ['Select tile']
            + self.gm[self.sv_current_grid].tile_selector_list())
        if self.sv_current_tile >= self.gm[self.sv_current_grid].number_tiles:
            self.sv_current_tile = -1
        self.comboBox_tileSelectorSV.setCurrentIndex(self.sv_current_tile + 1)
        self.comboBox_tileSelectorSV.blockSignals(False)

    def sv_update_ov_selector(self):
        if self.sv_current_ov >= self.ovm.number_ov:
            self.sv_current_ov = -1
        self.comboBox_OVSelectorSV.blockSignals(True)
        self.comboBox_OVSelectorSV.clear()
        self.comboBox_OVSelectorSV.addItems(
            ['Select OV'] + self.ovm.ov_selector_list())
        self.comboBox_OVSelectorSV.setCurrentIndex(self.sv_current_ov + 1)
        self.comboBox_OVSelectorSV.blockSignals(False)

    def sv_slice_fwd(self):
        if self.slice_view_index < 0:
            self.slice_view_index += 1
            self.lcdNumber_sliceIndicator.display(self.slice_view_index)
            # For now, disable showing saturated pixels (too slow)
            self.sv_disable_saturated_pixels()
            self.sv_draw()

    def sv_slice_bwd(self):
        if (self.slice_view_index > (-1) * (self.max_slices-1)) and \
           ((-1) * self.slice_view_index < len(self.slice_view_images)-1):
            self.slice_view_index -= 1
            self.lcdNumber_sliceIndicator.display(self.slice_view_index)
            self.sv_disable_saturated_pixels()
            self.sv_draw()

    def sv_update_max_slices(self):
        self.max_slices = self.spinBox_maxSlices.value()

    def _sv_adjust_scale_from_slider(self):
        # Recalculate scale factor
        # This depends on whether OV or a tile is displayed.
        if self.sv_current_ov >= 0:
            self.cs.sv_scale_ov = (
                utils.SV_ZOOM_OV[0]
                * utils.SV_ZOOM_OV[1]**self.horizontalSlider_SV.value())
        else:
            self.cs.sv_scale_tile = (
                utils.SV_ZOOM_TILE[0]
                * utils.SV_ZOOM_TILE[1]**self.horizontalSlider_SV.value())
        self.sv_disable_saturated_pixels()
        self.sv_draw()

    def _sv_adjust_zoom_slider(self):
        self.horizontalSlider_SV.blockSignals(True)
        if self.sv_current_ov >= 0:
            self.horizontalSlider_SV.setValue(
                log(self.cs.sv_scale_ov / utils.SV_ZOOM_OV[0],
                    utils.SV_ZOOM_OV[1]))
        else:
            self.horizontalSlider_SV.setValue(
                log(self.cs.sv_scale_tile / utils.SV_ZOOM_TILE[0],
                    utils.SV_ZOOM_TILE[1]))
        self.horizontalSlider_SV.blockSignals(False)

    def _sv_mouse_zoom(self, px, py, factor):
        """Zoom in by specified factor and preserve the relative location of
        where user double-clicked."""
        if self.sv_current_ov >= 0:
            old_sv_scale_ov = self.cs.sv_scale_ov
            current_vx, current_vy = self.cs.sv_ov_vx_vy
            # Recalculate scaling factor.
            self.cs.sv_scale_ov = utils.fit_in_range(
                factor * old_sv_scale_ov,
                utils.SV_ZOOM_OV[0],
                utils.SV_ZOOM_OV[0] * utils.SV_ZOOM_OV[1]**99)
                # 99 is max slider value
            ratio = self.cs.sv_scale_ov / old_sv_scale_ov
            # Preserve mouse click position.
            new_vx = int(ratio * current_vx - (ratio - 1) * px)
            new_vy = int(ratio * current_vy - (ratio - 1) * py)
            self.cs.sv_ov_vx_vy = [new_vx, new_vy]
        elif self.sv_current_tile >= 0:
            old_sv_scale_tile = self.cs.sv_scale_tile
            current_vx, current_vy = self.cs.sv_tile_vx_vy
            self.cs.sv_scale_tile = utils.fit_in_range(
                factor * old_sv_scale_tile,
                utils.SV_ZOOM_TILE[0],
                utils.SV_ZOOM_TILE[0] * utils.SV_ZOOM_TILE[1]**99)
            ratio = self.cs.sv_scale_tile / old_sv_scale_tile
            # Preserve mouse click position.
            new_vx = int(ratio * current_vx - (ratio - 1) * px)
            new_vy = int(ratio * current_vy - (ratio - 1) * py)
            self.cs.sv_tile_vx_vy = [new_vx, new_vy]
        self._sv_adjust_zoom_slider()
        self.sv_draw()

    def sv_change_grid_selection(self):
        self.sv_current_grid = self.comboBox_gridSelectorSV.currentIndex()
        self.sv_update_tile_selector()

    def sv_change_tile_selection(self):
        self.sv_current_tile = self.comboBox_tileSelectorSV.currentIndex() - 1
        if self.sv_current_tile >= 0:
            self.slice_view_index = 0
            self.lcdNumber_sliceIndicator.display(0)
            self.sv_current_ov = -1
            self.comboBox_OVSelectorSV.blockSignals(True)
            self.comboBox_OVSelectorSV.setCurrentIndex(self.sv_current_ov + 1)
            self.comboBox_OVSelectorSV.blockSignals(False)
            self._sv_adjust_zoom_slider()
            self.sv_load_slices()
        else:
            self.slice_view_images = []
            self.slice_view_index = 0
            self.sv_draw()

    def sv_change_ov_selection(self):
        self.sv_current_ov = self.comboBox_OVSelectorSV.currentIndex() - 1
        if self.sv_current_ov >= 0:
            self.slice_view_index = 0
            self.lcdNumber_sliceIndicator.display(0)
            self.sv_current_tile = -1
            self.comboBox_tileSelectorSV.blockSignals(True)
            self.comboBox_tileSelectorSV.setCurrentIndex(
                self.sv_current_tile + 1)
            self.comboBox_tileSelectorSV.blockSignals(False)
            self._sv_adjust_zoom_slider()
            self.sv_load_slices()
        else:
            self.slice_view_images = []
            self.slice_view_index = 0
            self.sv_draw()

    def sv_load_selected(self):
        if self.selected_grid is not None and self.selected_tile is not None:
            self.sv_current_grid = self.selected_grid
            self.sv_current_tile = self.selected_tile
            self.comboBox_gridSelectorSV.blockSignals(True)
            self.comboBox_gridSelectorSV.setCurrentIndex(self.selected_grid)
            self.comboBox_gridSelectorSV.blockSignals(False)
            self.sv_update_tile_selector()
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
            self.sv_update_tile_selector()
        self.tabWidget.setCurrentIndex(1)
        QApplication.processEvents()
        self.sv_load_slices()

    def sv_img_within_boundaries(self, vx, vy, w_px, h_px, resize_ratio):
        visible = not ((-vx >= w_px * resize_ratio - 80)
                       or (-vy >= h_px * resize_ratio - 80)
                       or (vx >= self.cs.vp_width - 80)
                       or (vy >= self.cs.vp_height - 80))
        return visible

    def sv_load_slices(self):
        if self.sv_current_grid is None and self.sv_current_ov is None:
            QMessageBox('No tile or overview selected for slice-by-slice '
                        'display.')
            return
        # Reading the tiff files from SmartSEM generates warnings. They
        # are suppressed in the code below.
        # First show a "waiting" info, since loading the images may take a
        # while.
        self.sv_qp.begin(self.sv_canvas)
        self.sv_qp.setBrush(QColor(0, 0, 0))
        if self.sv_instructions_displayed:
            # Erase initial explanatory message.
            position_rect = QRect(150, 380, 700, 40)
            self.sv_qp.setPen(QColor(0, 0, 0))
            self.sv_qp.drawRect(position_rect)
            self.sv_instructions_displayed = False

        self.sv_qp.setPen(QColor(255, 255, 255))
        position_rect = QRect(350, 380, 300, 40)
        self.sv_qp.drawRect(position_rect)
        self.sv_qp.drawText(position_rect, Qt.AlignVCenter | Qt.AlignHCenter,
                            'Loading slices...')
        self.sv_qp.end()
        self.QLabel_SliceViewerCanvas.setPixmap(self.sv_canvas)
        QApplication.processEvents()
        self.slice_view_images = []
        self.slice_view_index = 0
        self.lcdNumber_sliceIndicator.display(0)
        start_slice = self.acq.slice_counter

        if self.sv_current_ov >= 0:
            for i in range(self.max_slices):
                filename = utils.ov_save_path(
                    self.acq.base_dir, self.acq.stack_name,
                    self.sv_current_ov, start_slice - i)
                if os.path.isfile(filename):
                    self.slice_view_images.append(QPixmap(filename))
                    utils.suppress_console_warning()
            self.sv_set_native_resolution()
            self.sv_draw()
        elif self.sv_current_tile >= 0:
            for i in range(self.max_slices):
                filename = os.path.join(
                    self.acq.base_dir, utils.tile_relative_save_path(
                        self.acq.stack_name, self.sv_current_grid,
                        self.sv_current_tile, start_slice - i))
                if os.path.isfile(filename):
                    self.slice_view_images.append(QPixmap(filename))
                    utils.suppress_console_warning()
            self.sv_set_native_resolution()
            self.sv_draw()

        if not self.slice_view_images:
            self.sv_qp.begin(self.sv_canvas)
            self.sv_qp.setPen(QColor(255, 255, 255))
            self.sv_qp.setBrush(QColor(0, 0, 0))
            position_rect = QRect(350, 380, 300, 40)
            self.sv_qp.drawRect(position_rect)
            self.sv_qp.drawText(position_rect,
                                Qt.AlignVCenter | Qt.AlignHCenter,
                                'No images found')
            self.sv_qp.end()
            self.QLabel_SliceViewerCanvas.setPixmap(self.sv_canvas)

    def sv_set_native_resolution(self):
        if self.sv_current_ov >= 0:
            previous_scaling_ov = self.cs.sv_scale_ov
            ov_pixel_size = self.ovm[self.sv_current_ov].pixel_size
            self.cs.sv_scale_ov = 1000 / ov_pixel_size
            ratio = self.cs.sv_scale_ov / previous_scaling_ov
            current_vx, current_vy = self.cs.sv_ov_vx_vy
            dx = self.cs.vp_width // 2 - current_vx
            dy = self.cs.vp_height // 2 - current_vy
            new_vx = int(current_vx - ratio * dx + dx)
            new_vy = int(current_vy - ratio * dy + dy)
        elif self.sv_current_tile >= 0:
            previous_scaling = self.cs.sv_scale_tile
            tile_pixel_size = self.gm[self.sv_current_grid].pixel_size
            self.cs.sv_scale_tile = self.cs.vp_width / tile_pixel_size
            ratio = self.cs.sv_scale_tile / previous_scaling
            current_vx, current_vy = self.cs.sv_tile_vx_vy
            dx = self.cs.vp_width // 2 - current_vx
            dy = self.cs.vp_height // 2 - current_vy
            new_vx = int(current_vx - ratio * dx + dx)
            new_vy = int(current_vy - ratio * dy + dy)
            # Todo:
            # Check if out of bounds.
            self.horizontalSlider_SV.setValue(
                log(self.cs.sv_scale_tile / 5.0, 1.04))
        self._sv_adjust_zoom_slider()
        self.sv_draw()

    def sv_toggle_show_native_resolution(self):
        if self.checkBox_setNativeRes.isChecked():
            self.show_native_res = True
            # Lock zoom slider.
            self.horizontalSlider_SV.setEnabled(False)
            self.sv_set_native_resolution()
        else:
            self.show_native_res = False
            self.horizontalSlider_SV.setEnabled(True)

    def sv_disable_native_resolution(self):
        if self.show_native_res:
            self.show_native_res = False
            self.checkBox_setNativeRes.setChecked(False)
            self.horizontalSlider_SV.setEnabled(True)

    def sv_toggle_show_saturated_pixels(self):
        self.show_saturated_pixels = self.checkBox_showSaturated.isChecked()
        self.sv_draw()

    def sv_disable_saturated_pixels(self):
        if self.show_saturated_pixels:
            self.show_saturated_pixels = False
            self.checkBox_showSaturated.setChecked(False)

    def sv_draw(self):
        # Empty black canvas for slice viewer
        self.sv_canvas.fill(Qt.black)
        self.sv_qp.begin(self.sv_canvas)
        if self.sv_current_ov >= 0:
            viewport_pixel_size = 1000 / self.cs.sv_scale_ov
            ov_pixel_size = self.ovm[self.sv_current_ov].pixel_size
            resize_ratio = ov_pixel_size / viewport_pixel_size
        else:
            viewport_pixel_size = 1000 / self.cs.sv_scale_tile
            tile_pixel_size = self.gm[self.sv_current_grid].pixel_size
            resize_ratio = tile_pixel_size / viewport_pixel_size

        if len(self.slice_view_images) > 0:
            if self.sv_current_ov >= 0:
                vx, vy = self.cs.sv_ov_vx_vy
            else:
                vx, vy = self.cs.sv_tile_vx_vy

            current_image = self.slice_view_images[-self.slice_view_index]

            w_px = current_image.size().width()
            h_px = current_image.size().height()

            visible, crop_area, cropped_vx, cropped_vy = self._vp_visible_area(
                vx, vy, w_px, h_px, resize_ratio)
            display_img = current_image.copy(crop_area)

            if visible:
                # Resize according to scale factor:
                current_width = display_img.size().width()
                display_img = display_img.scaledToWidth(
                    current_width * resize_ratio)

                # Show saturated pixels?
                if self.show_saturated_pixels:
                    width = display_img.size().width()
                    height = display_img.size().height()
                    img = display_img.toImage()
                    # Show black pixels as blue and white pixels as red.
                    black_pixels = [QColor(0, 0, 0).rgb(),
                                    QColor(1, 1, 1).rgb()]
                    white_pixels = [QColor(255, 255, 255).rgb(),
                                    QColor(254, 254, 254).rgb()]
                    blue_pixel = QColor(0, 0, 255).rgb()
                    red_pixel = QColor(255, 0, 0).rgb()
                    for x in range(width):
                        for y in range(height):
                            pixel_value = img.pixel(x, y)
                            if pixel_value in black_pixels:
                                img.setPixel(x, y, blue_pixel)
                            if pixel_value in white_pixels:
                                img.setPixel(x, y, red_pixel)
                    display_img = QPixmap.fromImage(img)

                self.sv_qp.drawPixmap(cropped_vx, cropped_vy, display_img)
        # Measuring tool:
        if self.sv_measure_active:
            self._draw_measure_labels(self.sv_qp)
        # Help panel:
        if self.help_panel_visible:
            self.sv_qp.drawPixmap(self.cs.vp_width - 200,
                                  self.cs.vp_height - 325,
                                  self.sv_help_panel_img)

        self.sv_qp.end()
        self.QLabel_SliceViewerCanvas.setPixmap(self.sv_canvas)
        # Update scaling label
        if self.sv_current_ov >= 0:
            self.label_FOVSize_sliceViewer.setText(
                '{0:.2f} µm × '.format(self.cs.vp_width / self.cs.sv_scale_ov)
                + '{0:.2f} µm'.format(self.cs.vp_height / self.cs.sv_scale_ov))
        else:
            self.label_FOVSize_sliceViewer.setText(
                '{0:.2f} µm × '.format(self.cs.vp_width / self.cs.sv_scale_tile)
                + '{0:.2f} µm'.format(self.cs.vp_height / self.cs.sv_scale_tile))

    def _sv_shift_fov(self, shift_vector):
        dx, dy = shift_vector
        if self.sv_current_ov >= 0:
            vx, vy = self.cs.sv_ov_vx_vy
            width, height = self.ovm[self.sv_current_ov].frame_size
            viewport_pixel_size = 1000 / self.cs.sv_scale_ov
            ov_pixel_size = self.ovm[self.sv_current_ov].pixel_size
            resize_ratio = ov_pixel_size / viewport_pixel_size
            new_vx = vx - dx
            new_vy = vy - dy
            if self.sv_img_within_boundaries(new_vx, new_vy,
                                             width, height, resize_ratio):
                self.cs.sv_ov_vx_vy = [new_vx, new_vy]
        else:
            vx, vy = self.cs.sv_tile_vx_vy
            width, height = self.gm[self.sv_current_grid].frame_size
            viewport_pixel_size = 1000 / self.cs.sv_scale_tile
            tile_pixel_size = self.gm[self.sv_current_grid].pixel_size
            resize_ratio = tile_pixel_size / viewport_pixel_size
            new_vx = vx - dx
            new_vy = vy - dy
            if self.sv_img_within_boundaries(new_vx, new_vy,
                                             width, height, resize_ratio):
                self.cs.sv_tile_vx_vy = [new_vx, new_vy]
        self.sv_draw()

    def sv_toggle_measure(self):
        self.sv_measure_active = not self.sv_measure_active
        if self.sv_measure_active:
            self.vp_measure_active = False
        self.measure_p1 = (None, None)
        self.measure_p2 = (None, None)
        self.measure_complete = False
        self._update_measure_buttons()
        self.sv_draw()

    def _sv_set_measure_point(self, px, py):
        """Convert pixel coordinates where mouse was clicked to SEM coordinates
        relative to the origin of the image displayed in the Slice-by-Slice
        Viewer, for starting or end point of measurement."""
        if self.sv_current_ov >= 0:
            px -= self.cs.sv_ov_vx_vy[0]
            py -= self.cs.sv_ov_vx_vy[1]
            scale = self.cs.sv_scale_ov
        elif self.sv_current_tile >= 0:
            px -= self.cs.sv_tile_vx_vy[0]
            py -= self.cs.sv_tile_vx_vy[1]
            scale = self.cs.sv_scale_tile
        else:
            # Measuring tool cannot be used when no image displayed.
            return
        if self.measure_p1[0] is None or self.measure_complete:
            self.measure_p1 = px / scale, py / scale
            self.measure_complete = False
            self.measure_p2 = None, None
        else:
            self.measure_p2 = px / scale, py / scale
        self.sv_draw()

    def sv_reset_view(self):
        """Zoom out completely and centre current image."""
        if self.sv_current_ov >= 0:
            self.cs.sv_scale_ov = utils.SV_ZOOM_OV[0]
            width, height = self.ovm[self.sv_current_ov].frame_size
            viewport_pixel_size = 1000 / self.cs.sv_scale_ov
            ov_pixel_size = self.ovm[self.sv_current_ov].pixel_size
            resize_ratio = ov_pixel_size / viewport_pixel_size
            new_vx = int(self.cs.vp_width // 2 - (width // 2) * resize_ratio)
            new_vy = int(self.cs.vp_height // 2 - (height // 2) * resize_ratio)
        elif self.sv_current_tile >= 0:
            self.cs.sv_scale_tile = utils.SV_ZOOM_TILE[0]
            width, height = self.gm[self.sv_current_grid].frame_size
            viewport_pixel_size = 1000 / self.cs.sv_scale_tile
            tile_pixel_size = self.gm[self.sv_current_grid].pixel_size
            resize_ratio = tile_pixel_size / viewport_pixel_size
            new_vx = int(self.cs.vp_width // 2 - (width // 2) * resize_ratio)
            new_vy = int(self.cs.vp_height // 2 - (height // 2) * resize_ratio)
        # Disable native resolution
        self.sv_disable_native_resolution()
        self._sv_adjust_zoom_slider()
        self.sv_draw()

    def sv_show_context_menu(self, p):
        px, py = p.x() - utils.VP_MARGIN_X, p.y() - utils.VP_MARGIN_Y
        if px in range(self.cs.vp_width) and py in range(self.cs.vp_height):
            menu = QMenu()
            action1 = menu.addAction('Reset view for current image')
            action1.triggered.connect(self.sv_reset_view)
            menu.exec_(self.mapToGlobal(p))

# ================ Below: Monitoring tab (m) functions =================

    def _m_initialize(self):
        # Currently selected grid/tile/OV in the drop-down lists
        self.m_current_grid = int(self.cfg['viewport']['m_current_grid'])
        self.m_current_tile = int(self.cfg['viewport']['m_current_tile'])
        self.m_current_ov = int(self.cfg['viewport']['m_current_ov'])
        self.m_from_stack = True

        self.histogram_canvas_template = QPixmap(400, 170)
        self.reslice_canvas_template = QPixmap(400, 560)
        self.plots_canvas_template = QPixmap(550, 560)
        self.m_tab_populated = False
        self.m_qp = QPainter()
        if self.cfg['sys']['simulation_mode'].lower() == 'true':
            self.radioButton_fromSEM.setEnabled(False)

        self.radioButton_fromStack.toggled.connect(self._m_source_update)
        self.pushButton_reloadM.clicked.connect(self.m_show_statistics)
        self.pushButton_showMotorStatusDlg.clicked.connect(
            self._m_open_motor_status_dlg)
        self.comboBox_gridSelectorM.currentIndexChanged.connect(
            self.m_change_grid_selection)
        self.m_update_grid_selector()
        self.comboBox_tileSelectorM.currentIndexChanged.connect(
            self.m_change_tile_selection)
        self.m_update_tile_selector()
        self.comboBox_OVSelectorM.currentIndexChanged.connect(
            self.m_change_ov_selection)
        self.m_update_ov_selector()

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
        self.QLabel_histogramCanvas.setPixmap(self.histogram_canvas_template)

        # Empty reslice canvas:
        self.reslice_canvas_template.fill(QColor(0, 0, 0))
        self.m_qp.begin(self.reslice_canvas_template)
        pen = QPen(QColor(255, 255, 255))
        self.m_qp.setPen(pen)
        position_rect = QRect(50, 260, 300, 40)
        self.m_qp.drawRect(position_rect)
        self.m_qp.drawText(position_rect, Qt.AlignVCenter | Qt.AlignHCenter,
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
        self.QLabel_resliceCanvas.setPixmap(self.reslice_canvas_template)
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
        self.QLabel_plotCanvas.setPixmap(self.plots_canvas_template)

    def _m_source_update(self):
        self.m_from_stack = self.radioButton_fromStack.isChecked()
        # Choice of tile or OV is only enabled when using images from stack
        self.comboBox_gridSelectorM.setEnabled(self.m_from_stack)
        self.comboBox_tileSelectorM.setEnabled(self.m_from_stack)
        self.comboBox_OVSelectorM.setEnabled(self.m_from_stack)
        self.m_show_statistics()

    def m_update_grid_selector(self):
        if self.m_current_grid >= self.gm.number_grids:
            self.m_current_grid = 0
        self.comboBox_gridSelectorM.blockSignals(True)
        self.comboBox_gridSelectorM.clear()
        self.comboBox_gridSelectorM.addItems(self.gm.grid_selector_list())
        self.comboBox_gridSelectorM.setCurrentIndex(self.m_current_grid)
        self.comboBox_gridSelectorM.blockSignals(False)

    def m_update_tile_selector(self, current_tile=-1):
        self.m_current_tile = current_tile
        self.comboBox_tileSelectorM.blockSignals(True)
        self.comboBox_tileSelectorM.clear()
        self.comboBox_tileSelectorM.addItems(
            ['Select tile']
            + self.gm[self.m_current_grid].tile_selector_list())
        self.comboBox_tileSelectorM.setCurrentIndex(self.m_current_tile + 1)
        self.comboBox_tileSelectorM.blockSignals(False)

    def m_update_ov_selector(self):
        if self.m_current_ov > self.ovm.number_ov:
            self.m_current_ov = 0
        self.comboBox_OVSelectorM.blockSignals(True)
        self.comboBox_OVSelectorM.clear()
        self.comboBox_OVSelectorM.addItems(
            ['Select OV'] + self.ovm.ov_selector_list())
        self.comboBox_OVSelectorM.setCurrentIndex(self.m_current_ov + 1)
        self.comboBox_OVSelectorM.blockSignals(False)

    def m_change_grid_selection(self):
        self.m_current_grid = self.comboBox_gridSelectorM.currentIndex()
        self.m_update_tile_selector()

    def m_change_tile_selection(self):
        self.m_current_tile = self.comboBox_tileSelectorM.currentIndex() - 1
        if self.m_current_tile >= 0:
            self.m_current_ov = -1
        elif self.m_current_tile == -1: # no tile selected
            # Select OV 0 by default:
            self.m_current_ov = 0
        self.comboBox_OVSelectorM.blockSignals(True)
        self.comboBox_OVSelectorM.setCurrentIndex(self.m_current_ov + 1)
        self.comboBox_OVSelectorM.blockSignals(False)
        self.m_show_statistics()

    def m_change_ov_selection(self):
        self.m_current_ov = self.comboBox_OVSelectorM.currentIndex() - 1
        if self.m_current_ov >= 0:
            self.m_current_tile = -1
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
        self.QLabel_resliceCanvas.setPixmap(canvas)
        self.QLabel_plotCanvas.setPixmap(self.plots_canvas_template)
        self.QLabel_histogramCanvas.setPixmap(self.histogram_canvas_template)

    def m_load_selected(self):
        self.m_from_stack = True
        self.radioButton_fromStack.setChecked(True)
        if self.selected_grid is not None and self.selected_tile is not None:
            self.m_current_grid = self.selected_grid
            self.m_current_tile = self.selected_tile
            self.comboBox_gridSelectorM.blockSignals(True)
            self.comboBox_gridSelectorM.setCurrentIndex(self.m_current_grid)
            self.comboBox_gridSelectorM.blockSignals(False)
            self.m_update_tile_selector(self.m_current_tile)
            self.m_current_ov = -1
            self.comboBox_OVSelectorM.blockSignals(True)
            self.comboBox_OVSelectorM.setCurrentIndex(0)
            self.comboBox_OVSelectorM.blockSignals(False)

        elif self.selected_ov is not None:
            self.m_current_ov = self.selected_ov
            self.comboBox_OVSelectorM.blockSignals(True)
            self.comboBox_OVSelectorM.setCurrentIndex(self.m_current_ov + 1)
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
        """Draw the reslice of the selected tile or OV."""
        filename = None
        if self.m_current_ov >= 0:
            filename = os.path.join(
                self.acq.base_dir, 'workspace', 'reslices',
                'r_OV' + str(self.m_current_ov).zfill(utils.OV_DIGITS) + '.png')
        elif self.m_current_tile >= 0:
            tile_key = ('g' + str(self.m_current_grid).zfill(utils.GRID_DIGITS)
                        + '_t'
                        + str(self.m_current_tile).zfill(utils.TILE_DIGITS))
            filename = os.path.join(
                self.acq.base_dir, 'workspace', 'reslices',
                'r_' + tile_key + '.png')
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
                most_recent_slice = int(self.acq.slice_counter)
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
                    + '.' + str(self.m_current_tile))
            self.m_qp.drawText(260, 543, 'Showing past ' + str(h) + ' slices')
            self.m_qp.end()
            self.QLabel_resliceCanvas.setPixmap(canvas)
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
            self.QLabel_resliceCanvas.setPixmap(canvas)
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
            filename = os.path.join(
                self.acq.base_dir, 'meta', 'stats',
                'OV' + str(self.m_current_ov).zfill(utils.OV_DIGITS) + '.dat')
        elif self.m_current_tile >= 0:
            tile_key = ('g' + str(self.m_current_grid).zfill(utils.GRID_DIGITS)
                        + '_t'
                        + str(self.m_current_tile).zfill(utils.TILE_DIGITS))
            filename = os.path.join(
                self.acq.base_dir, 'meta', 'stats',
                tile_key + '.dat')
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
            # Shorten the lists to last 165 entries if larger than 165:
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
            self.QLabel_plotCanvas.setPixmap(canvas)
        else:
            self.QLabel_plotCanvas.setPixmap(self.plots_canvas_template)
            self.m_tab_populated = False

    def m_draw_histogram(self):
        selected_file = ''
        slice_number = None
        canvas = self.histogram_canvas_template.copy()

        if self.m_from_stack:
            path = None
            if self.m_current_ov >= 0:
                path = os.path.join(
                    self.acq.base_dir, 'overviews',
                    'ov' + str(self.m_current_ov).zfill(utils.OV_DIGITS))
            elif self.m_current_tile >= 0:
                path = os.path.join(
                    self.acq.base_dir, 'tiles',
                    'g' + str(self.m_current_grid).zfill(utils.GRID_DIGITS)
                    + '\\t' + str(self.m_current_tile).zfill(utils.TILE_DIGITS))

            if path is not None and os.path.exists(path):
                filenames = next(os.walk(path))[2]
                if len(filenames) > 165:
                    filenames = filenames[-165:]
                if filenames:
                    if self.m_selected_slice_number is None:
                        selected_file = os.path.join(path, filenames[-1])
                    else:
                        slice_number_str = (
                            's' + str(self.m_selected_slice_number).zfill(
                                utils.SLICE_DIGITS))
                        for filename in filenames:
                            if slice_number_str in filename:
                                selected_file = os.path.join(path, filename)
                                break

        else:
            # Use current image from SEM 
            selected_file = os.path.join(
                self.acq.base_dir, 'workspace', 'current_frame.tif')
            self.sem.save_frame(selected_file)
            self.m_reset_view()
            self.m_tab_populated = False

        if os.path.isfile(selected_file):
            img = np.array(Image.open(selected_file))
    
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
                        + '.' + str(self.m_current_tile)
                        + ', slice ' + str(slice_number))

            else:
                self.m_qp.drawText(280, 50, 'Current SmartSEM image')
            self.m_qp.drawText(345, 90, '{0:.2f}'.format(mean))
            self.m_qp.drawText(345, 110, '{0:.2f}'.format(stddev))
            self.m_qp.drawText(345, 130, str(peak))
            self.m_qp.drawText(345, 150, str(hist_max))

            self.m_qp.end()
            self.QLabel_histogramCanvas.setPixmap(canvas)
        else:
            self.m_qp.begin(canvas)
            self.m_qp.setPen(QColor(25, 25, 112))
            self.m_qp.drawText(50, 90, 'No image found for selected source   ')
            self.m_qp.end()
            self.QLabel_histogramCanvas.setPixmap(canvas)

    def _m_open_motor_status_dlg(self):
        dialog = MotorStatusDlg(self.stage)
        dialog.exec_()

    def m_show_motor_status(self):
        """Show recent motor warnings or errors if there are any."""
        self.label_xMotorStatus.setStyleSheet("color: black")
        self.label_xMotorStatus.setText('No recent warnings')
        self.label_yMotorStatus.setStyleSheet("color: black")
        self.label_yMotorStatus.setText('No recent warnings')
        self.label_zMotorStatus.setStyleSheet("color: black")
        self.label_zMotorStatus.setText('No recent warnings')

        if sum(self.stage.slow_xy_move_warnings) > 0:
            self.label_xMotorStatus.setStyleSheet("color: orange")
            self.label_xMotorStatus.setText('Recent warnings')
            self.label_yMotorStatus.setStyleSheet("color: orange")
            self.label_yMotorStatus.setText('Recent warnings')
        if sum(self.stage.failed_x_move_warnings) > 0:
            self.label_xMotorStatus.setStyleSheet("color: red")
            self.label_xMotorStatus.setText('Recent errors')
        if sum(self.stage.failed_y_move_warnings) > 0:
            self.label_yMotorStatus.setStyleSheet("color: red")
            self.label_yMotorStatus.setText('Recent errors')
        if sum(self.stage.failed_z_move_warnings) > 0:
            self.label_zMotorStatus.setStyleSheet("color: red")
            self.label_zMotorStatus.setText('Recent errors')