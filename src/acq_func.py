# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module contains four functions that are called manually (by the user)
and not during acquisitions:
(1) Overview acquisition (to refresh the displayed OV in the viewport),
(2) Stub overview acquisition,
(3) Manual sweep command (when the user wants to remove debris),
(4) Manual stage move
"""

import os
import datetime
import numpy as np
import scipy.ndimage
from time import sleep
from skimage import io

import utils
from utils import Error


def acquire_ov(base_dir, selection, sem, stage, ovm, img_inspector,
               main_controls_trigger, viewport_trigger):
    check_ov_acceptance = bool(sem.cfg['overviews']['check_acceptance'].lower() == 'true')
    # Update current XY stage position
    stage.get_xy()
    success = True
    if selection == -1:
        # acquire all OVs
        start = 0
        end = ovm.number_ov
    else:
        # acquire only one OV
        start = selection
        end = selection + 1
    # Acquisition loop
    for ov_index in range(start, end):
        if not ovm[ov_index].active:
            continue
        main_controls_trigger.transmit(utils.format_log_entry(
            'STAGE: Moving to OV %d position.' % ov_index))
        # Move to OV stage coordinates
        stage.move_to_xy(ovm[ov_index].centre_sx_sy)
        # Check to see if error ocurred
        if stage.error_state != Error.none:
            stage.reset_error_state()
            sleep(1)
            # Try again
            stage.move_to_xy(ovm[ov_index].centre_sx_sy)
            if stage.error_state != Error.none:
                stage.reset_error_state()
                main_controls_trigger.transmit(utils.format_log_entry(
                    'STAGE: Second attempt to move to OV %d position failed.'
                    % ov_index))
                success = False
        if success:
            # Update stage position in Main Controls GUI and Viewport
            main_controls_trigger.transmit('UPDATE XY')
            sleep(0.1)
            main_controls_trigger.transmit('DRAW VP')
            # Use custom focus settings for this OV if available
            ov_wd = ovm[ov_index].wd_stig_xy[0]
            if ov_wd > 0:
                sem.set_wd(ov_wd)
                stig_x, stig_y = ovm[ov_index].wd_stig_xy[1:3]
                sem.set_stig_xy(stig_x, stig_y)
                main_controls_trigger.transmit(utils.format_log_entry(
                    'SEM: Using specified '
                    + utils.format_wd_stig(ov_wd, stig_x, stig_y)))
            # Set specified OV frame settings
            sem.apply_frame_settings(ovm[ov_index].frame_size_selector,
                                     ovm[ov_index].pixel_size,
                                     ovm[ov_index].dwell_time)
            save_path = os.path.join(
                base_dir, 'workspace', 'OV'
                + str(ov_index).zfill(3) + '.bmp')
            main_controls_trigger.transmit(utils.format_log_entry(
                'SEM: Acquiring OV %d.' % ov_index))
            # Indicate the overview being acquired in the viewport
            viewport_trigger.transmit('ACQ IND OV' + str(ov_index))
            success = sem.acquire_frame(save_path)
            # Remove indicator colour
            viewport_trigger.transmit('ACQ IND OV' + str(ov_index))
            _, _, _, load_error, _, grab_incomplete = (
                img_inspector.load_and_inspect(save_path))
            if load_error or grab_incomplete and check_ov_acceptance:
                # Try again
                sleep(0.5)
                main_controls_trigger.transmit(utils.format_log_entry(
                    'SEM: Second attempt: Acquiring OV %d.' % ov_index))
                viewport_trigger.transmit('ACQ IND OV' + str(ov_index))
                success = sem.acquire_frame(save_path)
                viewport_trigger.transmit('ACQ IND OV' + str(ov_index))
                sleep(1)
                _, _, _, load_error, _, grab_incomplete = (
                    img_inspector.load_and_inspect(save_path))
                if load_error or grab_incomplete:
                    success = False
                    if load_error:
                        cause = 'load error'
                    elif grab_incomplete:
                        cause = 'grab incomplete'
                    else:
                        cause = 'acquisition error'
                    main_controls_trigger.transmit(utils.format_log_entry(
                        f'SEM: Second attempt to acquire OV {ov_index} '
                        f'failed ({cause}).'))
            if success:
                ovm[ov_index].vp_file_path = save_path
            # Show updated OV
            viewport_trigger.transmit('DRAW VP')
        if not success:
            break # leave loop if error has occured
    if success:
        viewport_trigger.transmit('REFRESH OV SUCCESS')
    else:
        viewport_trigger.transmit('REFRESH OV FAILURE')


def acquire_stub_ov(sem, stage, ovm, acq, img_inspector,
                    stub_dlg_trigger, abort_queue):
    """Acquire a large tiled overview image of user-defined size that covers a
    part of or the entire stub (SEM sample holder).

    This function, which acquires the tiles one by one and combines them into
    one large image, is called in a thread from StubOVDlg.
    """
    success = True      # Set to False if an error occurs during acq process
    aborted = False     # Set to True when user clicks the 'Abort' button
    prev_vp_file_path = ovm['stub'].vp_file_path

    # Update current XY position and display it in Main Controls GUI
    stage.get_xy()
    stub_dlg_trigger.transmit('UPDATE XY')

    if stage.use_microtome_xy:
        # When using the microtome for XY moves, make sure the correct motor 
        # speeds are being set. This is currently only relevant for Gatan 3View.
        success = stage.update_motor_speed()

    if success:
        # NumPy array for final stitched image
        width, height = ovm['stub'].width_p(), ovm['stub'].height_p()
        full_stub_image = np.zeros((height, width), dtype=np.uint8)
        # Save current stub image to temp_save_path to show live preview
        # during the acquisition
        temp_save_path = os.path.join(
            acq.base_dir, 'workspace', 'temp_stub_ov.png')
        io.imsave(temp_save_path, full_stub_image,
                  check_contrast=False)
        ovm['stub'].vp_file_path = temp_save_path

        image_counter = 0
        first_tile = True
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
                    stub_dlg_trigger.transmit('STUB OV ABORT')
                    sleep(0.5)
                    success = False
                    aborted = True
                    break
            target_x, target_y = ovm['stub'][tile_index].sx_sy
            # Only acquire tile if it is within stage limits
            if stage.pos_within_limits((target_x, target_y)):
                stage.move_to_xy((target_x, target_y))
                if stage.error_state != Error.none:
                    stage.reset_error_state()
                    # Try once more
                    sleep(3)
                    stage.move_to_xy((target_x, target_y))
                    if stage.error_state != Error.none:
                        success = False
                        stage.reset_error_state()
                        stub_dlg_trigger.transmit(
                            f'The stage could not reach the target position of '
                            f'tile {tile_index} after two attempts. Please '
                            f'make sure that the XY stage limits and the XY '
                            f'motor speeds are set correctly.')

                if success:
                    # Show new stage coordinates in main control window
                    # and in Viewport (if stage position indicator active)
                    stub_dlg_trigger.transmit('UPDATE XY')
                    sleep(0.1)
                    stub_dlg_trigger.transmit('DRAW VP')
                    save_path = os.path.join(
                        acq.base_dir, 'workspace',
                        'stub' + str(tile_index).zfill(2) + '.tif')
                    if first_tile:
                        # Set acquisition parameters
                        sem.apply_frame_settings(
                            ovm['stub'].frame_size_selector,
                            ovm['stub'].pixel_size,
                            ovm['stub'].dwell_time)
                        first_tile = False
                    success = sem.acquire_frame(save_path)
                    sleep(0.5)
                    tile_img, _, _, load_error, _, grab_incomplete = (
                        img_inspector.load_and_inspect(save_path))
                    if load_error or grab_incomplete:
                        # Try again
                        sem.reset_error_state()
                        success = sem.acquire_frame(save_path)
                        sleep(1.5)
                        tile_img, _, _, load_error, _, grab_incomplete = (
                            img_inspector.load_and_inspect(save_path))
                        if load_error:
                            success = False
                            if load_error:
                                cause = 'load error'
                            elif grab_incomplete:
                                cause = 'grab incomplete'
                            else:
                                cause = 'acquisition error'
                            sem.reset_error_state()
                            stub_dlg_trigger.transmit(
                                f'Tile {tile_index} could not be successfully '
                                f'acquired after two attempts ({cause}).')
                    if success:
                        # Paste NumPy array of acquired tile (tile_img) into
                        # full_stub_image at the tile XY position
                        x = tile_index % number_cols
                        y = tile_index // number_cols
                        x_pos = x * (tile_width - overlap)
                        y_pos = y * (tile_height - overlap)
                        full_stub_image[y_pos:y_pos+tile_height,
                                        x_pos:x_pos+tile_width] = tile_img
                        # Save current stitched image and show it in Viewport
                        io.imsave(temp_save_path, full_stub_image,
                                  check_contrast=False)
                        # Setting vp_file_path to temp_save_path reloads the
                        # current png file as a QPixmap
                        ovm['stub'].vp_file_path = temp_save_path
                        stub_dlg_trigger.transmit('DRAW VP')
                        sleep(0.1)

            if not success:
                break

            # Update progress bar in dialog window
            image_counter += 1
            percentage_done = int(
                image_counter / ovm['stub'].number_tiles * 100)
            stub_dlg_trigger.transmit(
                'UPDATE PROGRESS' + str(percentage_done))

        # Write final full stub overview image and downsampled copies to disk unless acq aborted
        if not aborted:
            stub_dir = os.path.join(acq.base_dir, 'overviews', 'stub')
            if not os.path.exists(stub_dir):
                os.makedirs(stub_dir)
            timestamp = str(datetime.datetime.now())
            # Remove some characters from timestap to get a valid file name
            timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
            stub_overview_file_name = os.path.join(
                acq.base_dir, 'overviews', 'stub',
                acq.stack_name + '_stubOV_s'
                + str(acq.slice_counter).zfill(5)
                + '_' + timestamp + '.png')
            
            # Full stub OV image
            io.imsave(stub_overview_file_name, full_stub_image,
                      check_contrast=False)
            try:
                # Generate downsampled versions of stub OV
                for mag in [2, 4, 8, 16]:
                    vp_fname_mag = stub_overview_file_name[:-4] + f'_mag{mag}.png'
                    img_mag = scipy.ndimage.zoom(full_stub_image, 1 / mag, order=3)
                    io.imsave(vp_fname_mag, img_mag)
            except Exception as e:
                stub_dlg_trigger.transmit(
                    f'An exception occurred while saving downsampled copies'
                    f'of the acquired stub overview image: {str(e)}')

            ovm['stub'].vp_file_path = stub_overview_file_name
        else:
            # Restore previous stub OV
            ovm['stub'].vp_file_path = prev_vp_file_path
            stub_dlg_trigger.transmit('DRAW VP')

    if success:
        # Signal to dialog window that stub OV acquisition was successful
        stub_dlg_trigger.transmit('STUB OV SUCCESS')
    elif not aborted:
        # Signal to dialog window that stub OV acquisition failed
        stub_dlg_trigger.transmit('STUB OV FAILURE')


def manual_sweep(microtome, main_controls_trigger):
    """Perform sweep requested by user in Main Controls window."""
    z_position = microtome.get_stage_z(wait_interval=1)
    if (z_position is not None) and (z_position >= 0):
        microtome.do_sweep(z_position)
    if microtome.error_state != Error.none:
        microtome.reset_error_state()
        main_controls_trigger.transmit('MANUAL SWEEP FAILURE')
    else:
        main_controls_trigger.transmit('MANUAL SWEEP SUCCESS')


def manual_stage_move(stage, target_position, viewport_trigger):
    """Move stage to target_position (X, Y), requested by user in Viewport.
    This function is run in a thread started in viewport.py.
    """
    # Read current XY stage position to make sure that stage.last_known_xy
    # is up-to-date. Expected duration of the move is calculated with
    # stage.last_known_xy as the starting point.
    stage.get_xy()
    stage.move_to_xy(target_position)
    if stage.error_state != Error.none:
        stage.reset_error_state()
        sleep(1)
        # Try again
        stage.move_to_xy(target_position)
        if stage.error_state != Error.none:
            stage.reset_error_state()
            viewport_trigger.transmit('MANUAL MOVE FAILURE')
            return
    viewport_trigger.transmit('MANUAL MOVE SUCCESS')
