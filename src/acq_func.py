# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2019 Friedrich Miescher Institute for Biomedical Research, Basel.
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

def acquire_ov(base_dir, selection, sem, stage, ovm, cs, queue, trigger):
    # Update current xy position:
    stage.get_xy()
    queue.put('UPDATE XY')
    trigger.s.emit()
    success = True
    if selection == -1: # acquire all OVs
        start, end = 0, ovm.number_ov
    else:
        start, end = selection, selection + 1 # acquire only one OV
    # Acquisition loop:
    for i in range(start, end):
        queue.put(utils.format_log_entry(
            '3VIEW: Moving stage to OV %d position.' % i))
        trigger.s.emit()
        # Move to OV stage coordinates:
        stage.move_to_xy(ovm[i].centre_sx_sy)
        # Check to see if error ocurred:
        if stage.error_state > 0:
            success = False
            stage.reset_error_state()
        if success:
            # update stage position in GUI:
            queue.put('UPDATE XY')
            trigger.s.emit()
            # Set specified OV frame settings:
            sem.apply_frame_settings(ovm[i].frame_size_selector,
                                     ovm[i].pixel_size,
                                     ovm[i].dwell_time)
            save_path = base_dir + '\\workspace\\OV' + str(i).zfill(3) + '.bmp'
            queue.put(utils.format_log_entry(
                'SEM: Acquiring OV %d.' % i))
            trigger.s.emit()
            # Indicate the overview being acquired in the viewport
            queue.put('ACQ IND OV' + str(i))
            trigger.s.emit()
            success = sem.acquire_frame(save_path)
            # Remove indicator colour
            queue.put('ACQ IND OV' + str(i))
            trigger.s.emit()
            # Show updated OV:
            queue.put('MV UPDATE OV' + str(i))
            trigger.s.emit()
            if success:
                ovm[i].vp_file_path = save_path
        if not success:
            break # leave loop if error has occured
    if success:
        queue.put('OV SUCCESS')
        trigger.s.emit()
    else:
        queue.put('OV FAILURE')
        trigger.s.emit()

def acquire_stub_ov(base_dir, slice_counter, sem, stage,
                    ovm, queue, trigger, abort_queue):
    """Acquire a large overview image of user-defined size that can cover
       the entire stub.
    """
    success = True
    aborted = False
    # Update current xy position:
    stage.get_xy()
    queue.put('UPDATE STAGEPOS')
    trigger.s.emit()
    # Make sure DM script uses the correct motor speed calibration
    # (This information is lost when script crashes.)
    if stage.use_microtome:
        success = stage.update_motor_speed()

    if success:
        width, height = ovm['stub'].width_p(), ovm['stub'].height_p()
        full_stub_image = Image.new('L', (width, height))
        # Set acquisition parameters
        sem.apply_frame_settings(ovm['stub'].frame_size_selector,
                                 ovm['stub'].pixel_size,
                                 ovm['stub'].dwell_time)

        rows, cols = ovm['stub'].size
        image_number = rows * cols
        image_counter = 0
        tile_width = ovm['stub'].tile_width_p()
        tile_height = ovm['stub'].tile_height_p()
        overlap = ovm['stub'].overlap

        for row in range(rows):
            for col in range(cols):
                tile_index = row * cols + col
                if not abort_queue.empty():
                    if abort_queue.get() == 'ABORT':
                        queue.put('STUB OV ABORT')
                        trigger.s.emit()
                        success = False
                        aborted = True
                        break
                target_x, target_y = ovm['stub'][tile_index].sx_sy
                stage.move_to_xy((target_x, target_y))

                # Check to see if error ocurred:
                if stage.error_state > 0:
                    success = False
                    stage.reset_error_state()
                else:
                    # Show new stage coordinates in main control window:
                    queue.put('UPDATE STAGEPOS')
                    trigger.s.emit()
                    save_path = os.path.join(
                        base_dir, 'workspace',
                        'stub' + str(col) + str(row) + '.bmp')
                    success = sem.acquire_frame(save_path)
                    if success:
                        current_tile = Image.open(save_path)
                        position = (col * (tile_width - overlap),
                                    row * (tile_height - overlap))
                        full_stub_image.paste(current_tile, position)
                        image_counter += 1
                        percentage_done = int(image_counter / image_number * 100)
                        queue.put('UPDATE PROGRESS' + str(percentage_done))
                        trigger.s.emit()
                    if not success:
                        break

        # Write full mosaic to disk unless acq aborted:
        if not aborted:
            if not os.path.exists(os.path.join(base_dir, 'overviews', 'stub')):
                os.makedirs(os.path.join(base_dir, 'overviews', 'stub'))
            base_dir_name = base_dir[base_dir.rfind('\\') + 1:].translate(
                {ord(c): None for c in ' '})
            timestamp = str(datetime.datetime.now())
            # Remove some characters from timestap to get valid file name:
            timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
            stub_overview_file_name = os.path.join(
                base_dir, 'overviews', 'stub',
                base_dir_name + '_stubOV_s' + str(slice_counter).zfill(5)
                + '_' + timestamp + '.png')
            full_stub_image.save(stub_overview_file_name)
            ovm['stub'].vp_file_path = stub_overview_file_name

    if success:
        # Signal
        queue.put('STUB OV SUCCESS')
        trigger.s.emit()
    elif not aborted:
        queue.put('STUB OV FAILURE')
        trigger.s.emit()

def sweep(microtome, queue, trigger):
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
        queue.put('SWEEP SUCCESS')
        trigger.s.emit()
    else:
        queue.put('SWEEP FAILURE')
        trigger.s.emit()

def move(stage, target_pos, queue, trigger):
    # Update current xy position:
    stage.get_xy()
    queue.put('UPDATE XY')
    trigger.s.emit()
    success = True
    stage.move_to_xy(target_pos)
    if stage.error_state > 0:
        success = False
        stage.reset_error_state()
    if success:
        queue.put('UPDATE XY')
        trigger.s.emit()
        queue.put('MOVE SUCCESS')
        trigger.s.emit()
    else:
        queue.put('MOVE FAILURE')
        trigger.s.emit()
