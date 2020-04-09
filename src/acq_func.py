# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module contains four functions that are called manually: (1) Overview
   acquisition (to refresh the displayed OV in the viewport), (2) Stub overview
   acquisition, (3) Manual sweep command (when the user wants to remove debris),
   (4) Manual stage move
"""

import os
import datetime
from time import sleep
from PIL import Image

import utils

def acquire_ov(base_dir, selection, sem, stage, ovm, cs,
               viewport_trigger, viewport_queue):
    # Update current xy position:
    stage.get_xy()
    viewport_queue.put('UPDATE XY')
    viewport_trigger.s.emit()
    success = True
    if selection == -1: # acquire all OVs
        start, end = 0, ovm.number_ov
    else:
        start, end = selection, selection + 1 # acquire only one OV
    # Acquisition loop:
    for i in range(start, end):
        viewport_queue.put('3VIEW: Moving stage to OV %d position.' % i)
        viewport_trigger.s.emit()
        # Move to OV stage coordinates:
        stage.move_to_xy(ovm[i].centre_sx_sy)
        # Check to see if error ocurred:
        if stage.error_state > 0:
            success = False
            stage.reset_error_state()
        if success:
            # update stage position in GUI:
            viewport_queue.put('UPDATE XY')
            viewport_trigger.s.emit()
            # Set specified OV frame settings:
            sem.apply_frame_settings(ovm[i].frame_size_selector,
                                     ovm[i].pixel_size,
                                     ovm[i].dwell_time)
            save_path = os.path.join(
                base_dir, 'workspace', 'OV' + str(i).zfill(3) + '.bmp')
            viewport_queue.put('SEM: Acquiring OV %d.' % i)
            viewport_trigger.s.emit()
            # Indicate the overview being acquired in the viewport
            viewport_queue.put('ACQ IND OV' + str(i))
            viewport_trigger.s.emit()
            success = sem.acquire_frame(save_path)
            # Remove indicator colour
            viewport_queue.put('ACQ IND OV' + str(i))
            viewport_trigger.s.emit()
            # Show updated OV:
            viewport_queue.put('DRAW VP')
            viewport_trigger.s.emit()
            if success:
                ovm[i].vp_file_path = save_path
        if not success:
            break # leave loop if error has occured
    if success:
        viewport_queue.put('REFRESH OV SUCCESS')
        viewport_trigger.s.emit()
    else:
        viewport_queue.put('REFRESH OV FAILURE')
        viewport_trigger.s.emit()

def acquire_stub_ov(sem, stage, ovm, stack,
                    stub_dlg_trigger, stub_dlg_queue, abort_queue):
    """Acquire a large tiled overview image of user-defined size that covers a
    part of or the entire stub (SEM sample holder).

    This function, which acquires the tiles one by one and combines them into
    one large image, is called in a thread from StubOVDlg.
    """
    success = True      # Set to False if an error occurs during acq process
    aborted = False     # Set to True when user clicks the 'Abort' button

    # Update current XY position and display it in Main Controls GUI
    stage.get_xy()
    stub_dlg_queue.put('UPDATE XY')
    stub_dlg_trigger.s.emit()

    if stage.use_microtome:
        # When using the microtome stage, make sure the DigitalMicrograph script
        # uses the correct motor speeds (this information is lost when script
        # crashes.)
        success = stage.update_motor_speed()

    if success:
        width, height = ovm['stub'].width_p(), ovm['stub'].height_p()
        full_stub_image = Image.new('L', (width, height))
        # Set acquisition parameters
        sem.apply_frame_settings(ovm['stub'].frame_size_selector,
                                 ovm['stub'].pixel_size,
                                 ovm['stub'].dwell_time)

        image_counter = 0
        number_cols = ovm['stub'].size[1]
        tile_width = ovm['stub'].tile_width_p()
        tile_height = ovm['stub'].tile_height_p()
        overlap = ovm['stub'].overlap
        # Activate all tiles, which will automatically sort active tiles to
        # minimize motor move durations
        ovm['stub'].activate_all_tiles()

        for tile_index in ovm['stub'].active_tiles:
            if not abort_queue.empty():
                # Check if user has clicked 'Abort' button in dialog GUI
                if abort_queue.get() == 'ABORT':
                    stub_dlg_queue.put('STUB OV ABORT')
                    stub_dlg_trigger.s.emit()
                    success = False
                    aborted = True
                    break
            target_x, target_y = ovm['stub'][tile_index].sx_sy
            # Only acquire tile if it is within stage limits
            if stage.pos_within_limits((target_x, target_y)):
                stage.move_to_xy((target_x, target_y))
                if stage.error_state > 0:
                    stage.reset_error_state()
                    # Try once more
                    sleep(3)
                    stage.move_to_xy((target_x, target_y))
                    if stage.error_state > 0:
                        success = False
                        stage.reset_error_state()
                else:
                    # Show new stage coordinates in main control window
                    stub_dlg_queue.put('UPDATE XY')
                    stub_dlg_trigger.s.emit()
                    save_path = os.path.join(
                        stack.base_dir, 'workspace',
                        'stub' + str(tile_index).zfill(2) + '.bmp')
                    success = sem.acquire_frame(save_path)
                    sleep(0.5)
                    if success:
                        # Paste tile into full_stub_image
                        x = tile_index % number_cols
                        y = tile_index // number_cols
                        current_tile = Image.open(save_path)
                        position = (x * (tile_width - overlap),
                                    y * (tile_height - overlap))
                        full_stub_image.paste(current_tile, position)
                    else:
                        sem.reset_error_state()

            if not success:
                break

            # Update progress bar in dialog window
            image_counter += 1
            percentage_done = int(
                image_counter / ovm['stub'].number_tiles * 100)
            stub_dlg_queue.put(
                'UPDATE PROGRESS' + str(percentage_done))
            stub_dlg_trigger.s.emit()

        # Write full stub over image to disk unless acq aborted
        if not aborted:
            stub_dir = os.path.join(stack.base_dir, 'overviews', 'stub')
            if not os.path.exists(stub_dir):
                os.makedirs(stub_dir)
            timestamp = str(datetime.datetime.now())
            # Remove some characters from timestap to get a valid file name
            timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
            stub_overview_file_name = os.path.join(
                stack.base_dir, 'overviews', 'stub',
                stack.stack_name + '_stubOV_s'
                + str(stack.slice_counter).zfill(5)
                + '_' + timestamp + '.png')
            full_stub_image.save(stub_overview_file_name)
            ovm['stub'].vp_file_path = stub_overview_file_name

    if success:
        # Signal to dialog window that stub OV acquisition was successful
        stub_dlg_queue.put('STUB OV SUCCESS')
        stub_dlg_trigger.s.emit()
    elif not aborted:
        # Signal to dialog window that stub OV acquisition failed
        stub_dlg_queue.put('STUB OV FAILURE')
        stub_dlg_trigger.s.emit()

def manual_sweep(microtome, main_controls_trigger, main_controls_queue):
    """Perform sweep requested by user in Main Controls window."""
    success = True
    z_position = microtome.get_stage_z(wait_interval=1)
    if (z_position is not None) and (z_position >= 0):
        microtome.do_sweep(z_position)
        if microtome.error_state > 0:
            success = False
            microtome.reset_error_state()
    else:
        success = False
        microtome.reset_error_state()
    if success:
        main_controls_queue.put('MANUAL SWEEP SUCCESS')
        main_controls_trigger.s.emit()
    else:
        main_controls_queue.put('MANUAL SWEEP FAILURE')
        main_controls_trigger.s.emit()

def manual_stage_move(stage, target_position,
                      viewport_trigger, viewport_queue):
    """Perform stage move to target_position requested by user in Viewport."""
    # Update current xy position
    stage.get_xy()
    viewport_queue.put('UPDATE XY')
    viewport_trigger.s.emit()
    success = True
    stage.move_to_xy(target_position)
    if stage.error_state > 0:
        success = False
        stage.reset_error_state()
    if success:
        viewport_queue.put('UPDATE XY')
        viewport_trigger.s.emit()
        viewport_queue.put('MANUAL MOVE SUCCESS')
        viewport_trigger.s.emit()
    else:
        viewport_queue.put('MANUAL MOVE FAILURE')
        viewport_trigger.s.emit()
