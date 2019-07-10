# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module controls the acquisition process."""

import os
import shutil
import time
import datetime
import json

from time import sleep
from PIL import Image
from scipy.misc import imsave
from dateutil.relativedelta import relativedelta
from PyQt5.QtWidgets import QMessageBox

import utils


class Stack():

    def __init__(self, config, sem, microtome, stage,
                 overview_manager, grid_manager, coordinate_system,
                 image_inspector, autofocus, acq_queue, acq_trigger):
        self.cfg = config
        self.sem = sem
        self.microtome = microtome
        self.stage = stage
        self.ovm = overview_manager
        self.gm = grid_manager
        self.cs = coordinate_system
        self.img_inspector = image_inspector
        self.af = autofocus
        self.queue = acq_queue
        self.trigger = acq_trigger

        self.email_pw = ''  # provided by user at runtime

        self.ERROR_LIST = {
            0: 'No error',

            # First digit 1: DM communication
            101: 'DM script initialization error',
            102: 'DM communication error (command could not be sent)',
            103: 'DM communication error (unresponsive)',
            104: 'DM communication error (return values could not be read)',

            # First digit 2: 3View/SBEM hardware
            201: 'Stage error (XY target position not reached)',
            202: 'Stage error (Z target position not reached)',
            203: 'Stage error (Z move too large)',
            204: 'Cutting error',
            205: 'Sweeping error',
            206: 'Z mismatch error',

            # First digit 3: SmartSEM/SEM
            301: 'SmartSEM API initialization error',
            302: 'Grab image error',
            303: 'Grab incomplete error',
            304: 'Frozen frame error',
            305: 'SmartSEM unresponsive error',
            306: 'EHT error',
            307: 'Beam current error',
            308: 'Frame size error',
            309: 'Magnification error',
            310: 'Scan rate error',
            311: 'WD error',
            312: 'STIG XY error',
            313: 'Beam blanking error',

            # First digit 4: I/O error
            401: 'Primary drive error',
            402: 'Mirror drive error',
            403: 'Overwrite file error',
            404: 'Load image error',

            # First digit 5: Other errors during acq
            501: 'Maximum sweeps error',
            502: 'Overview image error (outside of range)',
            503: 'Tile image error (outside of range)',
            504: 'Tile image error (slice-by-slice comparison)',
            505: 'Autofocus error (SmartSEM)' ,
            506: 'Autofocus error (heuristic)',
            507: 'WD/STIG difference error',
            508: 'Metadata server error',

            # First digit 6: reserved for user-defined errors
            601: 'Test case error'
        }

        self.acq_setup()

    def acq_setup(self):
        """Set up all variables for a new stack acquisition, or update
           variables for restarting a stack.
        """
        self.error_state = 0
        self.error_cause = ''
        self.pause_state = None
        self.acq_paused = (self.cfg['acq']['paused'] == 'True')
        self.stack_completed = False
        self.report_requested = False
        self.slice_counter = int(self.cfg['acq']['slice_counter'])
        self.number_slices = int(self.cfg['acq']['number_slices'])
        self.slice_thickness = int(self.cfg['acq']['slice_thickness'])
        self.total_z_diff = float(self.cfg['acq']['total_z_diff'])
        self.stage_z_position = None  # updated when stack (re)started.
        if self.microtome is not None:
            self.full_cut_duration = self.microtome.get_full_cut_duration()
            self.sweep_distance = self.microtome.get_sweep_distance()
        else:
            self.full_cut_duration = 0
            self.sweep_distance = None
        self.eht_off_after_stack = (
            self.cfg['acq']['eht_off_after_stack'] == 'True')
        # Was previous acq interrupted by error or paused inbetween by user?
        self.acq_interrupted = (self.cfg['acq']['interrupted'] == 'True')
        self.acq_interrupted_at = json.loads(self.cfg['acq']['interrupted_at'])
        self.tiles_acquired = json.loads(self.cfg['acq']['tiles_acquired'])
        self.grids_acquired = json.loads(self.cfg['acq']['grids_acquired'])
        # E-mail settings:
        self.email_account = self.cfg['sys']['email_account']
        self.smtp_server = self.cfg['sys']['email_smtp']
        self.imap_server = self.cfg['sys']['email_imap']
        self.user_email_addresses = [self.cfg['monitoring']['user_email'],
                                     self.cfg['monitoring']['cc_user_email']]
        self.base_dir = self.cfg['acq']['base_dir']
        # Extract the name of the stack from the base directory:
        self.stack_name = self.base_dir[self.base_dir.rfind('\\') + 1:]
        self.viewport_filename = None
        # Mirror drive: same folder, only drive letter changes:
        self.mirror_drive = self.cfg['sys']['mirror_drive']
        self.mirror_drive_directory = (self.cfg['sys']['mirror_drive']
                                       + self.base_dir[2:])
        # Metadata to server:
        self.metadata_server = (self.cfg['sys']['metadata_server_url']
                                 + '/project/'
                                 + self.cfg['sys']['metadata_project_name']
                                 + '/stack/'
                                 + self.stack_name)
        self.send_metadata = (self.cfg['sys']['send_metadata'] == 'True')
        # The following two features (mirror drive, overviews) can not be
        # enabled/disabled during a run. Other features such as debris
        # detection and monitoring can be enabled/disabled during a run
        self.use_mirror_drive = (self.cfg['sys']['use_mirror_drive'] == 'True')
        self.take_overviews = (self.cfg['acq']['take_overviews'] == 'True')
        self.use_adaptive_focus = False

        # autofocus and autostig interval status:
        self.autofocus_stig_current_slice = (False, False)

        # locked focus params:
        self.wd_stig_locked = False
        self.mag_locked = False
        self.locked_wd = None
        self.locked_stig_x, self.locked_stig_y = None, None
        self.locked_mag = None

        # Focus parameters for current grid, initialized with current settings:
        if self.cfg['sys']['simulation_mode'] == 'False':
            self.wd_current_grid = self.sem.get_wd()
            self.stig_x_current_grid, self.stig_y_current_grid = (
                self.sem.get_stig_xy())

        # Alternating plus/minus deltas for wd and stig, needed for
        # heuristic autofocus, otherwise 0
        self.wd_delta, self.stig_x_delta, self.stig_y_delta = 0, 0, 0
        # List of tiles to be processed for heuristic autofocus:
        self.heuristic_af_queue = []

        # Variables used for reply from main program:
        self.user_reply = None
        self.user_reply_received = False
        self.image_rejected_by_user = False

    def get_remote_password(self):
        return self.email_pw

    def set_remote_password(self, pw):
        """Set the password needed to access the e-mail account used by
           SBEMimage to receive remote commands. The user can set this
           password in a dialog.
        """
        self.email_pw = pw

    def calculate_estimates(self):
        """Calculate the current electron dose (range), the dimensions of
        the stack, the estimated duration of the stack acquisition, the storage
        requirements, and the estimated time/date of completion.

        Returns:
            min_dose (float): Minimum electron dose of current stack setup
                              (usually occurs during OV acquisition)
            max_dose (float): Maximum electron dose of current stack setup
                              (usually occurs during grid acquisition)
            total_grid_area (float): Total area of selected tiles (in µm²)
            total_z (float): Total Z depth of target number of slices in µm
            total_data_in_GB (float): Size of the stack to be acquired (in GB)
            total_imaging_time (float): Total raw imaging time
            total_stage_move_time (float): Total duration of stage moves
            total_cut_time (float): Total time for cuts with the knife
            date_estimate (str): Date and time of expected completion
        """
        N = self.number_slices
        if N == 0:    # 0 slices is a valid setting. It means: image the current
            N = 1     # surface, but do not cut afterwards.
        take_overviews = self.cfg['acq']['take_overviews'] == 'True'
        current = self.sem.get_beam_current()
        min_dose = max_dose = None
        total_cut_time = self.number_slices * self.full_cut_duration
        total_grid_area = 0
        total_data = 0
        total_stage_move_time = 0
        total_imaging_time = 0

        max_offset_slice_number = max(
            self.gm.get_max_acq_interval_offset(),
            self.ovm.get_max_ov_acq_interval_offset())
        max_interval_slice_number = max(
            self.gm.get_max_acq_interval(),
            self.ovm.get_max_ov_acq_interval())

        # Calculate estimates until max_offset_slice_number, then starting from
        # max_offset_slice_number for max_interval_slice_number, then
        # extrapolate until target slice number N.

        def calculate_for_slice_range(from_slice, to_slice):
            """Run through stack (from_slice..to_slice) to calculate exact
            raw imaging time, stage move durations, and amount of image data.
            """
            imaging_time = 0
            stage_move_time = 0
            amount_of_data = 0
            # Start at stage position of OV 0
            x0, y0 = self.cs.get_ov_centre_s(0)
            for slice_counter in range(from_slice, to_slice):
                if take_overviews:
                    # Run through all overviews
                    for ov_number in range(self.ovm.get_number_ov()):
                        if self.ovm.is_slice_active(ov_number, slice_counter):
                            x1, y1 = self.cs.get_ov_centre_s(ov_number)
                            stage_move_time += (
                                self.stage.calculate_stage_move_duration(
                                    x0, y0, x1, y1))
                            x0, y0 = x1, y1
                            imaging_time += self.ovm.get_ov_cycle_time(ov_number)
                            frame_size = (self.ovm.get_ov_width_p(ov_number)
                                          * self.ovm.get_ov_height_p(ov_number))
                            amount_of_data += frame_size
                # Run through all grids
                for grid_number in range(self.gm.get_number_grids()):
                    if self.gm.is_slice_active(grid_number, slice_counter):
                        for tile_number in self.gm.get_active_tiles(grid_number):
                            x1, y1 = self.gm.get_tile_coordinates_s(
                                grid_number, tile_number)
                            stage_move_time += (
                                self.stage.calculate_stage_move_duration(
                                    x0, y0, x1, y1))
                            x0, y0 = x1, y1
                        number_active_tiles = self.gm.get_number_active_tiles(
                            grid_number)
                        imaging_time += (
                            self.gm.get_tile_cycle_time(grid_number)
                            * number_active_tiles)
                        frame_size = (self.gm.get_tile_width_p(grid_number)
                                      * self.gm.get_tile_height_p(grid_number))
                        amount_of_data += frame_size * number_active_tiles
                # Move back to starting position
                if take_overviews:
                    x1, y1 = self.cs.get_ov_centre_s(0)
                    stage_move_time += (
                        self.stage.calculate_stage_move_duration(
                            x0, y0, x1, y1))
                    x0, y0 = x1, y1

            return imaging_time, stage_move_time, amount_of_data
        # ========== End of calculate_for_slice_range() ==========

        if N <= max_offset_slice_number + max_interval_slice_number:
            # Calculate for all slices:
            imaging_time_0, stage_move_time_0, amount_of_data_0 = (
                calculate_for_slice_range(0, N))
            imaging_time_1, stage_move_time_1, amount_of_data_1 = 0, 0, 0
        else:
            # First part (up to max_offset_slice_number):
            imaging_time_0, stage_move_time_0, amount_of_data_0 = (
                calculate_for_slice_range(0, max_offset_slice_number))
            # Fraction of remaining slices that are acquired in regular intervals:
            imaging_time_1, stage_move_time_1, amount_of_data_1 = (
                calculate_for_slice_range(
                    max_offset_slice_number,
                    max_offset_slice_number + max_interval_slice_number))
            # Extrapolate for the remaining number of slices:
            if N > max_offset_slice_number + max_interval_slice_number:
                factor = (N - max_offset_slice_number) / max_interval_slice_number
                imaging_time_1 *= factor
                stage_move_time_1 *= factor
                amount_of_data_1 *= factor

        total_imaging_time = imaging_time_0 + imaging_time_1
        total_stage_move_time = stage_move_time_0 + stage_move_time_1
        total_data = amount_of_data_0 + amount_of_data_1

        # Calculate grid area and electron dose range
        for grid_number in range(self.gm.get_number_grids()):
            number_active_tiles = self.gm.get_number_active_tiles(
                grid_number)
            total_grid_area += (number_active_tiles
                                * self.gm.get_tile_width_d(grid_number)
                                * self.gm.get_tile_height_d(grid_number))
            dwell_time = self.gm.get_dwell_time(grid_number)
            pixel_size = self.gm.get_pixel_size(grid_number)
            dose = utils.calculate_electron_dose(current, dwell_time, pixel_size)
            if (min_dose is None) or (dose < min_dose):
                min_dose = dose
            if (max_dose is None) or (dose > max_dose):
                max_dose = dose

        if take_overviews:
            for ov_number in range(self.ovm.get_number_ov()):
                dwell_time = self.ovm.get_ov_dwell_time(ov_number)
                pixel_size = self.ovm.get_ov_pixel_size(ov_number)
                dose = utils.calculate_electron_dose(
                    current, dwell_time, pixel_size)
                if (min_dose is None) or (dose < min_dose):
                    min_dose = dose
                if (max_dose is None) or (dose > max_dose):
                    max_dose = dose

        total_z = (self.number_slices * self.slice_thickness) / 1000
        total_data_in_GB = total_data / (10**9)
        total_duration = total_imaging_time + total_stage_move_time + total_cut_time

        # Calculate date and time of completion
        now = datetime.datetime.now()
        fraction_completed = self.slice_counter / N
        completion_date = now + relativedelta(
            seconds=int(total_duration * (1 - fraction_completed)))
        date_estimate = str(completion_date)[:19].replace(' ', ' at ')

        # Return all estimates, to be displayed in main window GUI:
        return (min_dose, max_dose, total_grid_area, total_z, total_data_in_GB,
                total_imaging_time, total_stage_move_time, total_cut_time,
                date_estimate)

    def create_subdirectories(self, dir_list):
        """Create subdirectories given in dir_list in the base folder"""
        try:
            for dir_name in dir_list:
                new_dir = self.base_dir + '\\' + dir_name
                if not os.path.exists(new_dir):
                    os.makedirs(new_dir)
            return True
        except:
            return False

    def mirror_subdirectories(self, dir_list):
        """Mirror subdirectories given in dir_list"""
        try:
            for dir_name in dir_list:
                new_mirror_dir = self.mirror_drive_directory + '\\' + dir_name
                if not os.path.exists(new_mirror_dir):
                    os.makedirs(new_mirror_dir)
            return True
        except:
            return False

    def mirror_files(self, file_list):
        """Copy files given in file_list to mirror drive, keep path."""
        try:
            for file_name in file_list:
                dst_file_name = self.mirror_drive + file_name[2:]
                shutil.copy(file_name, dst_file_name)
        except:
            # Log in viewport window:
            log_str = (str(self.slice_counter) + ': WARNING ('
                       + 'Could not mirror file(s))')
            self.error_log_file.write(log_str + '\n')
            # Signal to main window to update log in viewport:
            self.transmit_cmd('VP LOG' + log_str)
            sleep(2)
            # Try again:
            try:
                for file_name in file_list:
                    dst_file_name = self.mirror_drive + file_name[2:]
                    shutil.copy(file_name, dst_file_name)
            except:
                self.add_to_main_log('CTRL: Copying file(s) to mirror '
                                     'drive failed.')
                self.pause_acquisition(2)
                self.error_state = 402

    def set_up_acq_subdirectories(self):
        """Set up and mirror all subdirectories for the stack acquisition"""
        subdirectory_list = [
            'meta',
            'meta\\logs',
            'meta\\stats',
            'overviews',
            'overviews\\stub',
            'overviews\\debris',
            'tiles',
            'tiles\\rejected',
            'workspace',
            'workspace\\viewport',
            'workspace\\reslices'
        ]
        # Add subdirectories for overviews, grids, tiles:
        for ov_number in range(self.ovm.get_number_ov()):
            ov_dir = 'overviews\\ov' + str(ov_number).zfill(utils.OV_DIGITS)
            subdirectory_list.append(ov_dir)
        for grid_number in range(self.gm.get_number_grids()):
            grid_dir = 'tiles\\g' + str(grid_number).zfill(utils.GRID_DIGITS)
            subdirectory_list.append(grid_dir)
            for tile_number in self.gm.get_active_tiles(grid_number):
                tile_dir = grid_dir + '\\t' + str(
                    tile_number).zfill(utils.TILE_DIGITS)
                subdirectory_list.append(tile_dir)
        # Create the directories:
        success = self.create_subdirectories(subdirectory_list)
        if not success:
            self.pause_acquisition(1)
            self.error_state = 401
        elif self.use_mirror_drive:
            success = self.mirror_subdirectories(subdirectory_list)
            if not success:
                self.pause_acquisition(2)
                self.error_state = 402

    def set_up_acq_logs(self):
        """Create all acquisition log files and copy them to the mirror drive"""
        # Get timestamp for this run:
        timestamp = str(datetime.datetime.now())[:22].translate(
            {ord(i):None for i in ' :.'})
        # Save current configuration file with timestamp in log folder:
        config_filename = (self.base_dir + '\\meta\\logs\\config_'
                           + timestamp + '.txt')
        f = open(config_filename, 'w')
        self.cfg.write(f)
        f.close()
        # Save current grid setup:
        gridmap_filename = self.gm.save_grid_setup(timestamp)
        # Create main log file:
        self.main_log_filename = (self.base_dir + '\\meta\\logs\\'
                                  + 'log_' + timestamp + '.txt')
        # Log file for most recent entries (used for status report):
        self.recent_log_filename = (self.base_dir + '\\meta\\logs\\'
                                    + 'log_' + timestamp + '_mostrecent.txt')
        # A buffer_size of 1 ensures that all log entries are immediately
        # written to disk:
        buffer_size = 1
        self.main_log_file = open(self.main_log_filename, 'w', buffer_size)
        # Set up imagelist file:
        self.imagelist_filename = (self.base_dir + '\\meta\\logs\\'
                                   + 'imagelist_' + timestamp + '.txt')
        self.imagelist_file = open(self.imagelist_filename, 'w', buffer_size)
        # Log files for debris and errors:
        self.debris_log_filename = (self.base_dir + '\\meta\\logs\\'
                                    + 'debris_log_' + timestamp + '.txt')
        self.debris_log_file = open(self.debris_log_filename,
                                    'w', buffer_size)
        self.error_log_filename = (self.base_dir + '\\meta\\logs\\'
                                   + 'error_log_' + timestamp + '.txt')
        self.error_log_file = open(self.error_log_filename, 'w', buffer_size)

        self.metadata_filename = (self.base_dir + '\\meta\\logs\\'
                                    + 'metadata_' + timestamp + '.txt')
        self.metadata_file = open(self.metadata_filename, 'w', buffer_size)

        # Note that the config file and the gridmap file are only saved once
        # in the beginning of the acquisition. The other log files are updated
        # continously during the acq.
        log_file_list = [
            config_filename,
            gridmap_filename,
            self.main_log_filename,
            self.imagelist_filename,
            self.debris_log_filename,
            self.error_log_filename,
            self.metadata_filename
        ]
        # Copy all log files to mirror drive:
        if self.use_mirror_drive:
            self.mirror_files(log_file_list)
            # Handle for imagelist file on mirror drive:
            self.mirror_imagelist_file = open(
                self.mirror_drive
                + self.imagelist_filename[2:],
                'w', buffer_size)

# ===================== STACK ACQUISITION THREAD run() ========================

    def run(self):
        """Run acquisition in a thread started from main_controls.py."""
        self.acq_setup()
        self.set_up_acq_subdirectories()
        self.set_up_acq_logs()

        self.main_log_file.write('*** SBEMimage log for acquisition '
                                 + self.cfg['acq']['base_dir'] + ' ***\n\n')
        if self.acq_paused:
            self.main_log_file.write('\n*** STACK ACQUISITION RESTARTED ***\n')
            self.add_to_main_log('CTRL: Stack restarted.')
            self.acq_paused = False
        else:
            self.main_log_file.write('\n*** STACK ACQUISITION STARTED ***\n')
            self.add_to_main_log('CTRL: Stack started.')

        number_ov = self.ovm.get_number_ov()
        number_grids = self.gm.get_number_grids()
        self.first_ov = [True] * number_ov
        self.img_inspector.reset_tile_stats()

        if self.use_mirror_drive:
            self.add_to_main_log(
                'CTRL: Mirror drive directory: ' + self.mirror_drive_directory)

        # save current configuration to disk:
        self.transmit_cmd('SAVE CFG')
        # Update progress bar and slice counter:
        self.transmit_cmd('UPDATE PROGRESS')

        # Metadata summary for this run
        # Write summary to disk and send to remote server (if feature enabled)
        wd = 0 # placeholder for now
        timestamp = int(time.time())
        grid_list = [
            str(i).zfill(utils.GRID_DIGITS) for i in range(number_grids)]
        session_metadata = {
            'timestamp': timestamp,
            'eht': self.sem.get_eht(),
            'beam_current': self.sem.get_beam_current(),
            'stig_parameters': self.sem.get_stig_xy(),
            'working_distance': wd,
            'slice_thickness': self.slice_thickness,
            'grids': grid_list,
            'grid_origins': [],
            'pixel_sizes': self.gm.get_pixel_size_list(),
            'dwell_times': self.gm.get_dwell_time_list(),
            'contrast': float(self.cfg['sem']['bsd_contrast']),
            'brightness': float(self.cfg['sem']['bsd_brightness']),
            'email_addresses: ': [self.cfg['monitoring']['user_email'],
                                  self.cfg['monitoring']['cc_user_email']]
            }
        self.metadata_file.write('SESSION: ' + str(session_metadata) + '\n')
        # Send to server?
        if self.send_metadata:
            url = self.metadata_server + '/session/metadata'
            response = utils.meta_server_put_request(url, session_metadata)
            if response == 100:
                self.error_state = 508
                self.pause_acquisition(1)
                self.add_to_main_log('CTRL: Error sending session metadata '
                                     'to server.')
            elif response == 200:
                self.add_to_main_log(
                    'CTRL: Metadata server active.')

        # Set SEM to target parameters. EHT is assumed to be on!
        self.sem.apply_beam_settings()
        self.sem.set_beam_blanking(1)
        sleep(1)

        for grid_number in range(number_grids):
            if not self.gm.is_adaptive_focus_active(grid_number):
                self.gm.set_initial_wd_stig_for_grid(grid_number,
                                                     self.wd_current_grid,
                                                     self.stig_x_current_grid,
                                                     self.stig_y_current_grid)
            else:
                # Set stig values to current settings for each tile if adaptive
                # focus used
                self.gm.set_stig_for_grid(grid_number,
                                          self.stig_x_current_grid,
                                          self.stig_y_current_grid)

        for ov_number in range(number_ov):
            self.ovm.set_ov_wd(ov_number, 0)
            self.ovm.set_ov_stig_xy(ov_number, 0, 0)

        # Show current focus/stig settings:
        self.log_wd_stig(self.wd_current_grid,
                         self.stig_x_current_grid,
                         self.stig_y_current_grid)

        # Make sure DM script uses the correct motor speed calibration
        # (This information is lost when script crashes.)
        success = self.stage.update_motor_speed()
        if not success:
            self.error_state = 101
            self.pause_acquisition(1)
            self.add_to_main_log('3VIEW: ERROR: Could not set '
                                 'motor speed calibration')

        # Get current z position of stage:
        self.stage_z_position = self.stage.get_z()
        if self.stage_z_position is None or self.stage_z_position < 0:
            # try again:
            self.stage_z_position = self.stage.get_z()
            if self.stage_z_position is None or self.stage_z_position < 0:
                self.error_state = 104
                self.stage.reset_error_state()
                self.pause_acquisition(1)
                self.add_to_main_log('CTRL: Error reading initial Z position.')
        # Check for Z mismatch:
        if self.microtome is not None and self.microtome.get_error_state() == 206:
            self.microtome.reset_error_state()
            self.error_state = 206
            self.pause_acquisition(1)
            # Show warning dialog:
            self.transmit_cmd('Z WARNING')

        self.transmit_cmd('UPDATE Z')

        self.stage.get_xy()
        self.transmit_cmd('UPDATE XY')

        # ========================= ACQUISITION LOOP ==========================
        while not (self.acq_paused or self.stack_completed):
            # Mark one line in log file for easier orientation:
            self.add_to_main_log(
                'CTRL: ****************************************')
            # Show current slice counter and z position:
            self.add_to_main_log('CTRL: slice ' + str(self.slice_counter)
                + ', Z:' + '{0:6.3f}'.format(self.stage_z_position))

            # Autofocus for this slice? (Method 0)
            self.autofocus_stig_current_slice = (
                self.af.is_active_current_slice(self.slice_counter))

            # For autofocus method 1, focus slightly up or down depending
            # on slice number:
            if self.af.is_active() and self.af.get_method() == 1:
                sign = 1 if self.slice_counter % 2 else -1
                deltas = self.af.get_heuristic_deltas()
                self.wd_delta = sign * deltas[0]
                self.stig_x_delta = sign * deltas[1]
                self.stig_y_delta = sign * deltas[2]
                self.add_to_main_log('CTRL: Heuristic autofocus active.')
                self.add_to_main_log(
                    'CTRL: DIFF_WD: {0:+.4f}'.format(self.wd_delta * 1000)
                    + ', DIFF_STIG_X: {0:+.2f}'.format(self.stig_x_delta)
                    + ', DIFF_STIG_Y: {0:+.2f}'.format(self.stig_x_delta))

            # ============= Overview (OV) image acquisition ===================
            if self.take_overviews:
                use_debris_detection = (
                    self.cfg['acq']['use_debris_detection'] == 'True')
                max_number_sweeps = int(
                    self.cfg['debris']['max_number_sweeps'])
                continue_after_max_sweeps = (
                    self.cfg['debris']['continue_after_max_sweeps'] == 'True')

                for ov_number in range(number_ov):
                    if (self.error_state > 0) or (self.pause_state == 1):
                        break
                    if self.ovm.is_slice_active(ov_number, self.slice_counter):
                        ov_accepted = False
                        sweep_limit = False
                        sweep_counter = 0
                        fail_counter = 0
                        # ================ OV acquisition loop ================
                        while (not ov_accepted
                               and not sweep_limit
                               and not self.pause_state == 1
                               and fail_counter < 3):

                            ov_filename, ov_accepted = (
                                self.acquire_overview(ov_number))

                            if (self.error_state in [303, 404]
                                and not self.image_rejected_by_user):
                                # Image incomplete or cannot be loaded,
                                # try again:
                                fail_counter += 1
                                if fail_counter < 3:
                                    self.add_to_main_log(
                                        'CTRL: OV problem detected. '
                                        'Trying again.')
                                self.img_inspector.discard_last_ov(ov_number)
                                sleep(1)
                                if fail_counter == 3:
                                    self.pause_acquisition(1)
                                else:
                                    self.error_state = 0
                            elif self.error_state > 0:
                                break
                            elif (not ov_accepted
                                  and not self.pause_state == 1
                                  and (use_debris_detection
                                  or self.first_ov[ov_number])):
                                # Save image with debris:
                                self.save_debris_image(ov_filename,
                                                       sweep_counter)
                                self.img_inspector.discard_last_ov(ov_number)
                                # Try to remove debris:
                                if (sweep_counter < max_number_sweeps):
                                    self.remove_debris()
                                    sweep_counter += 1
                                elif sweep_counter == max_number_sweeps:
                                    sweep_limit = True
                        # ============= OV acquisition loop end ===============

                        if (not ov_accepted
                            and self.error_state == 0
                            and not self.pause_state == 1):
                            if not continue_after_max_sweeps:
                                self.pause_acquisition(1)
                                self.error_state = 501
                                self.add_to_main_log(
                                    'CTRL: Max. number of sweeps reached. ')
                            else:
                                # Continue, but let user know:
                                ov_accepted = True
                                self.add_to_main_log(
                                    'CTRL: Max. number of sweeps reached, '
                                    'but continuing as specified.')

                        self.first_ov[ov_number] = False

                        if ov_accepted:
                            # Write stats to disk:
                            success = self.img_inspector.save_ov_stats(
                                ov_number, self.slice_counter)
                            if not success:
                                self.add_to_main_log(
                                    'CTRL: Error saving OV mean/SD to disk.')
                            success = self.img_inspector.save_ov_reslice(
                                ov_number)
                            if not success:
                                self.add_to_main_log(
                                    'CTRL: Error saving OV reslice to disk.')
                        # Mirror:
                        if self.use_mirror_drive:
                            self.mirror_files([ov_filename])
                        if sweep_counter > 0:
                            log_str = (str(self.slice_counter)
                                       + ': Debris, ' + str(sweep_counter)
                                       + ' sweep(s)')
                            self.debris_log_file.write(log_str + '\n')
                            # Signal to main window to update log in viewport:
                            self.transmit_cmd('VP LOG' + log_str)
                    else:
                        self.add_to_main_log(
                            'CTRL: Skip OV %d (intervallic acquisition)'
                            % ov_number)

            if (self.acq_interrupted
                    and self.acq_interrupted_at[0] >= number_grids):
                # Grid in which interruption occured has been deleted.
                self.acq_interrupted = False
                self.cfg['acq']['interrupted'] = 'False'
                self.interrupted_at = []
                self.cfg['acq']['interrupted_at'] = '[]'
                self.tiles_acquired = []
                self.cfg['acq']['tiles_acquired'] = '[]'

            # =================== Grid acquistion loop ========================
            for grid_number in range(number_grids):
                if self.error_state > 0 or self.pause_state == 1:
                        break

                if self.gm.is_slice_active(grid_number, self.slice_counter):
                    num_active_tiles = self.gm.get_number_active_tiles(
                        grid_number)
                    self.add_to_main_log('CTRL: Grid ' + str(grid_number)
                                  + ', number of active tiles: '
                                  + str(num_active_tiles))
                    if (num_active_tiles > 0
                        and not (self.pause_state == 1)
                        and (self.error_state == 0)):
                        if grid_number in self.grids_acquired:
                            self.add_to_main_log('CTRL: Grid '
                                + str(grid_number) + ' already acquired. '
                                'Skipping. ')
                        else:
                            if (self.af.is_active()
                                    and self.af.get_method() == 0
                                    and (self.autofocus_stig_current_slice[0]
                                    or self.autofocus_stig_current_slice[1])):
                                self.do_autofocus_before_grid_acq(grid_number)
                            self.handle_autofocus_adjustments(grid_number)
                            self.acquire_grid(grid_number)
                else:
                    self.add_to_main_log(
                        'CTRL: Skip grid %d (intervallic acquisition)'
                        % grid_number)
            # ================ Grid acquistion loop end =======================

            # Reset interruption info if affected grid acquired:
            if (self.pause_state != 1
                    and self.acq_interrupted
                    and self.acq_interrupted_at[0] in self.grids_acquired):
                # Reset interruption info:
                self.cfg['acq']['interrupted_at'] = '[]'
                self.interrupted_at = []
                self.cfg['acq']['interrupted'] = 'False'
                self.acq_interrupted = False

            if not self.acq_interrupted:
                self.grids_acquired = []
                self.cfg['acq']['grids_acquired'] = '[]'

            # Save current viewport:
            self.viewport_filename = (self.base_dir + '\\workspace\\viewport\\'
                + self.stack_name + '_viewport_' + 's'
                + str(self.slice_counter).zfill(utils.SLICE_DIGITS) + '.png')
            self.transmit_cmd('GRAB VP SCREENSHOT' + self.viewport_filename)
            # Give main controls time to grab and save viewport screenshot:
            time_out = 0
            while not os.path.isfile(self.viewport_filename) and time_out < 20:
                sleep(0.1)
                time_out += 1

            timestamp = int(time.time())
            slice_complete_metadata = {
                'timestamp': timestamp,
                'completed_slice': self.slice_counter}
            self.metadata_file.write('SLICE COMPLETE: '
                                      + str(slice_complete_metadata) + '\n')

            if self.send_metadata:
                # Notify remote server that slice has been imaged
                url = self.metadata_server + '/slice/completed'
                response = utils.meta_server_put_request(
                    url, slice_complete_metadata)
                if response == 100:
                    self.error_state = 508
                    self.pause_acquisition(1)
                    self.add_to_main_log('CTRL: Error sending slice complete '
                                         'signal to server.')

                # Get commands or messages from server:
                url = self.metadata_server + '/signal/read'
                (status, command, msg) = utils.meta_server_get_request(url)
                if status == 100:
                    self.error_state = 508
                    self.pause_acquisition(1)
                    self.add_to_main_log('CTRL: Error during get request '
                                         'to server.')
                elif status == 200:
                    if command in ['STOP', 'PAUSE']:
                        self.pause_acquisition(1)
                        self.add_to_main_log(
                            'CTRL: Stop signal from metadata server '
                            'received.')
                        if self.cfg['acq']['use_email_monitoring'] == 'True':
                            # Send notification email:
                            msg_subject = ('Stack ' + self.stack_name
                                           + ' PAUSED remotely')
                            success = utils.send_email(
                                self.smtp_server,
                                self.email_account,
                                self.user_email_addresses,
                                msg_subject,
                                'Pause command received from metadata server.')
                        if success:
                            self.add_to_main_log(
                                'CTRL: Notification e-mail sent.')
                        else:
                            self.add_to_main_log(
                                'CTRL: ERROR sending notification email.')
                        self.transmit_cmd('REMOTE STOP')
                    if command == 'SHOWMESSAGE':
                        self.transmit_cmd('SHOW MSG' + msg)
                else:
                    self.add_to_main_log(
                        'CTRL: Unknown signal from metadata server '
                        'received.')

            # ======================= E-mail monitoring =======================
            use_email_monitoring = (
                self.cfg['acq']['use_email_monitoring'] == 'True')
            remote_commands_enabled = (
                self.cfg['monitoring']['remote_commands_enabled'] == 'True')
            remote_check_interval = int(
                self.cfg['monitoring']['remote_check_interval'])
            scheduled_report = (
                self.slice_counter
                % int(self.cfg['monitoring']['report_interval']) == 0)
            # If remote commands are enabled, check email account:
            if (use_email_monitoring and remote_commands_enabled
                and self.slice_counter % remote_check_interval == 0):
                self.process_remote_commands()

            # Check if report should be sent:
            if (use_email_monitoring
                    and (self.slice_counter > 0)
                    and (scheduled_report or self.report_requested)):
                self.send_status_report()

            # Check if single slice acquisition -> NO CUT
            if self.number_slices == 0:
                self.pause_acquisition(1)

            # ========================== CUTTING ==============================
            if (self.pause_state != 1) and (self.error_state == 0):
                if self.microtome is not None:
                    self.perform_cutting_sequence()
                self.reset_interruption_info()

            # Imaging and cutting for current slice completed.

            # Save current cfg to disk:
            self.transmit_cmd('SAVE CFG')

            self.transmit_cmd('UPDATE PROGRESS')
            if self.slice_counter == self.number_slices:
                self.stack_completed = True

            # Copy log file to mirror disk
            # (Error handling in self.mirror_files())
            if self.use_mirror_drive:
                self.mirror_files([self.main_log_filename])
            sleep(0.1)

        # ===================== END OF ACQUISITION LOOP =======================

        if self.af.is_active():
            for grid_number in range(number_grids):
                self.handle_autofocus_adjustments(grid_number)
            self.transmit_cmd('DRAW MV')
            if self.af.get_method() == 1:
                self.wd_delta, self.stig_x_delta, self.stig_y_delta = 0, 0, 0
                self.set_grid_wd_stig()

        if self.error_state > 0:
            self.process_error_state()

        if self.stack_completed and not (self.number_slices == 0):
            self.add_to_main_log('CTRL: Stack completed.')
            self.transmit_cmd('COMPLETION STOP')
            if use_email_monitoring:
                # Send notification email:
                msg_subject = 'Stack ' + self.stack_name + ' COMPLETED.'
                success = utils.send_email(self.smtp_server,
                                           self.email_account,
                                           self.user_email_addresses,
                                           msg_subject,
                                           '')
                if success:
                    self.add_to_main_log('CTRL: Notification e-mail sent.')
                else:
                    self.add_to_main_log(
                        'CTRL: ERROR sending notification email.')
            if self.eht_off_after_stack:
                self.sem.turn_eht_off()
                self.add_to_main_log(
                    'SEM: EHT turned off after stack completion.')

        if self.acq_paused:
            self.add_to_main_log('CTRL: Stack paused.')

        # Update acquisition status:
        self.transmit_cmd('ACQ NOT IN PROGRESS')
        # Write last entry in log and close log file.
        self.main_log_file.write('*** END OF LOG ***\n')
        # Close all log files:
        self.main_log_file.close()
        self.imagelist_file.close()
        if self.use_mirror_drive:
            self.mirror_imagelist_file.close()
        self.debris_log_file.close()
        self.error_log_file.close()
        self.metadata_file.close()
        # Finally, copy files to mirror drive:
        if self.use_mirror_drive:
            self.mirror_files([self.main_log_filename,
                               self.debris_log_filename,
                               self.error_log_filename,
                               self.metadata_filename])

    # =============== END OF STACK ACQUISITION THREAD run() ===================

    def process_remote_commands(self):
        self.add_to_main_log('CTRL: Checking for remote commands.')
        command = utils.get_remote_command(self.imap_server,
                                           self.email_account,
                                           self.email_pw,
                                           self.user_email_addresses)
        # Send command to main program via trigger, queue:
        if command in ['stop', 'pause']:
            self.add_to_main_log('CTRL: STOP/PAUSE remote command received.')
            utils.send_email(self.smtp_server,
                             self.email_account,
                             self.email_account,
                             'Command received',
                             '')
            self.pause_acquisition(2)
            success = utils.send_email(self.smtp_server,
                                       self.email_account,
                                       self.user_email_addresses,
                                       'Remote stop',
                                       'The acquisition was paused remotely.')
            if not success:
                self.add_to_log('CTRL: Error sending confirmation email.')
            self.transmit_cmd('REMOTE STOP')
        if command in ['continue', 'start', 'restart']:
            pass
            # TODO: let user continue paused acq with remote command
        if command == 'report':
            self.add_to_main_log('CTRL: REPORT remote command received.')
            utils.send_email(self.smtp_server,
                             self.email_account,
                             self.email_account,
                             'Command received',
                             '')
            self.report_requested = True
        if command == 'ERROR':
            self.add_to_main_log('CTRL: ERROR checking for remote commands.')

    def process_error_state(self):
        # Has a failure occured? Write info into log, send notification, pause:
        error_str = self.ERROR_LIST[self.error_state]
        # Log in main window:
        self.add_to_main_log('CTRL: ' + error_str)
        # Log in viewport window:
        log_str = str(self.slice_counter) + ': ERROR (' + error_str + ')'
        self.error_log_file.write(log_str + '\n')
        # Signal to main window to update log in viewport:
        self.transmit_cmd('VP LOG' + log_str)
        # Send notification e-mail about error:
        if self.cfg['acq']['use_email_monitoring'] == 'True':
            # Generate log file from current content of log:
            self.transmit_cmd('GET CURRENT LOG' + self.recent_log_filename)
            sleep(0.5) # wait for file to be written.
            if self.viewport_filename is not None:
                attachment_list = [self.recent_log_filename,
                                   self.viewport_filename]
            else:
                attachment_list = [self.recent_log_filename]
            msg_subject = ('Stack ' + self.stack_name + ': slice '
                           + str(self.slice_counter) + ', ERROR')
            success = utils.send_email(self.smtp_server,
                                       self.email_account,
                                       self.user_email_addresses,
                                       msg_subject,
                                       error_str,
                                       attachment_list)
            if success:
                self.add_to_main_log('CTRL: Error notification email sent.')
            else:
                self.add_to_main_log('CTRL: ERROR sending notification email.')
        # Tell main window that there was an error:
        self.transmit_cmd('ERROR PAUSE')

    def send_status_report(self):
        """Compile a status report and send it via e-mail."""
        attachment_list = []
        temp_file_list = []
        missing_list = []
        tile_list = json.loads(self.cfg['monitoring']['watch_tiles'])
        ov_list = json.loads(self.cfg['monitoring']['watch_ov'])
        if self.cfg['monitoring']['send_logfile'] == 'True':
            # Generate log file from current content of log:
            self.transmit_cmd('GET CURRENT LOG' + self.recent_log_filename)
            sleep(0.5) # wait for file be written.
            attachment_list.append(self.recent_log_filename)
        if self.cfg['monitoring']['send_additional_logs'] == 'True':
            attachment_list.append(self.debris_log_filename)
            attachment_list.append(self.error_log_filename)
        if self.cfg['monitoring']['send_viewport'] == 'True':
            if os.path.isfile(self.viewport_filename):
                attachment_list.append(self.viewport_filename)
            else:
                missing_list.append(self.viewport_filename)
        if (self.cfg['monitoring']['send_ov'] == 'True'):
            for ov_number in ov_list:
                save_path = self.base_dir + '\\' + utils.get_ov_save_path(
                            self.stack_name, ov_number, self.slice_counter)
                if os.path.isfile(save_path):
                    attachment_list.append(save_path)
                else:
                    missing_list.append(save_path)

        if (self.cfg['monitoring']['send_tiles'] == 'True'):
            for tile_key in tile_list:
                [grid_number, tile_number] = tile_key.split('.')
                save_path = self.base_dir + '\\' + utils.get_tile_save_path(
                            self.stack_name, grid_number, tile_number,
                            self.slice_counter)
                if os.path.isfile(save_path):
                    # If it exists, load image and crop it:
                    tile_image = Image.open(save_path)
                    (r_width, r_height) = tile_image.size
                    cropped_tile_filename = (
                        self.base_dir
                        + '\\workspace\\tile_g'
                        + str(grid_number).zfill(utils.GRID_DIGITS)
                        + 't' + str(tile_number).zfill(utils.TILE_DIGITS)
                        + '_cropped.tif')
                    tile_image.crop((int(r_width/3), int(r_height/3),
                         int(2*r_width/3), int(2*r_height/3))).save(
                         cropped_tile_filename)
                    temp_file_list.append(cropped_tile_filename)
                    attachment_list.append(cropped_tile_filename)
                else:
                    missing_list.append(save_path)

        if self.cfg['monitoring']['send_ov_reslices'] == 'True':
            for ov_number in ov_list:
                save_path = (self.base_dir + '\\'
                             + utils.get_ov_reslice_save_path(ov_number))
                if os.path.isfile(save_path):
                    ov_reslice_img = Image.open(save_path)
                    height = ov_reslice_img.size[1]
                    cropped_ov_reslice_save_path = (
                        self.base_dir + '\\workspace\\reslice_OV'
                        + str(ov_number).zfill(utils.OV_DIGITS) + '.png')
                    if height>1000:
                        ov_reslice_img.crop(0, height-1000, 400, height).save(
                            cropped_ov_reslice_save_path)
                    else:
                        ov_reslice_img.save(cropped_ov_reslice_save_path)
                    attachment_list.append(cropped_ov_reslice_save_path)
                    temp_file_list.append(cropped_ov_reslice_save_path)
                else:
                    missing_list.append(save_path)

        if self.cfg['monitoring']['send_tile_reslices'] == 'True':
            for tile_key in tile_list:
                [grid_number, tile_number] = tile_key.split('.')
                save_path = (self.base_dir + '\\'
                             + utils.get_tile_reslice_save_path(
                             grid_number, tile_number))
                if os.path.isfile(save_path):
                    reslice_img = Image.open(save_path)
                    height = reslice_img.size[1]
                    cropped_reslice_save_path = (
                        self.base_dir + '\\workspace\\reslice_tile_g'
                        + str(grid_number).zfill(utils.GRID_DIGITS)
                        + 't' + str(tile_number).zfill(utils.TILE_DIGITS)
                        + '.png')
                    if height>1000:
                        reslice_img.crop(0, height-1000, 400, height).save(
                            cropped_reslice_save_path)
                    else:
                        reslice_img.save(cropped_reslice_save_path)
                    attachment_list.append(cropped_reslice_save_path)
                    temp_file_list.append(cropped_reslice_save_path)
                else:
                    missing_list.append(save_path)

        # Send report email:
        msg_subject = ('Status report for stack ' + self.stack_name
                       + ': slice ' + str(self.slice_counter))
        msg_text = 'See attachments.'
        if missing_list:
            msg_text += ('\n\nThe following file(s) could not be attached. '
                         'Please review your e-mail report settings.\n\n')
            for file in missing_list:
                msg_text += (file + '\n')

        success = utils.send_email(self.smtp_server,
                                   self.email_account,
                                   self.user_email_addresses,
                                   msg_subject,
                                   msg_text,
                                   attachment_list)
        if success:
            self.add_to_main_log('CTRL: Status report e-mail sent.')
        else:
            self.add_to_main_log('CTRL: ERROR sending status report e-mail.')
        # clean up:
        for file in temp_file_list:
            os.remove(file)
        self.report_requested = False

    def perform_cutting_sequence(self):
        """Carry out a single cut. This function is called when the microtome
        is active and skipped if the SEM stage is active."""
        old_stage_z_position = self.stage_z_position
        # Move to new z position:
        self.stage_z_position = (self.stage_z_position
                                 + (self.slice_thickness / 1000))
        self.add_to_main_log('3VIEW: Move to new Z: ' + '{0:.3f}'.format(
            self.stage_z_position))
        self.microtome.move_stage_to_z(self.stage_z_position)
        # Show new Z position in main window:
        self.transmit_cmd('UPDATE Z')
        # Check if there were microtome problems:
        self.error_state = self.microtome.get_error_state()
        if self.error_state in [103, 202]:
            self.add_to_main_log('CTRL: Problem detected. Trying again.')
            self.error_state = 0
            self.microtome.reset_error_state()
            # Try again after 3 sec delay:
            sleep(3)
            self.microtome.move_stage_to_z(self.stage_z_position)
            # Show new Z position in main window:
            self.transmit_cmd('UPDATE Z')
            # Read new error_state:
            self.error_state = self.microtome.get_error_state()

        if self.error_state == 0:
            self.add_to_main_log('3VIEW: Cutting in progress ('
                          + str(self.slice_thickness)
                          + ' nm cutting thickness).')
            # do the cut (near, cut, retract, clear)
            self.microtome.do_full_cut()
            # Process tiles for heuristic autofocus during cut:
            if self.heuristic_af_queue:
                self.process_heuristic_af_queue()
                # Apply all corrections to tiles:
                self.add_to_main_log('CTRL: Applying corrections to WD/STIG')
                self.af.apply_heuristic_tile_corrections()
            else:
                sleep(self.full_cut_duration)
            duration_exceeded = self.microtome.check_for_cut_cycle_error()
            if duration_exceeded:
                self.add_to_main_log(
                    'CTRL: Warning: Cut cycle took longer than specified.')
            self.error_state = self.microtome.get_error_state()
            self.microtome.reset_error_state()
        if self.error_state > 0:
            self.add_to_main_log('CTRL: Problem detected.')
            # Try to move back to previous Z position:
            self.add_to_main_log('3VIEW: Attempt to move back to old Z: '
                                 + '{0:.3f}'.format(old_stage_z_position))
            self.microtome.move_stage_to_z(old_stage_z_position)
            # Show new Z position in main window:
            self.transmit_cmd('UPDATE Z')
            self.microtome.reset_error_state()
            self.pause_acquisition(1)
        else:
            self.add_to_main_log('3VIEW: Cut completed.')
            self.slice_counter += 1
            self.cfg['acq']['slice_counter'] = str(self.slice_counter)
            self.total_z_diff += self.slice_thickness/1000
            self.cfg['acq']['total_z_diff'] = str(self.total_z_diff)
        sleep(1)

    def process_heuristic_af_queue(self):
        start_time = datetime.datetime.now()
        for tile_key in self.heuristic_af_queue:
            self.perform_heuristic_autofocus(tile_key)
            current_time = datetime.datetime.now()
            time_elapsed = current_time - start_time
        self.heuristic_af_queue = []
        remaining_cutting_time = (
            self.full_cut_duration - time_elapsed.total_seconds())
        if remaining_cutting_time > 0:
            sleep(remaining_cutting_time)

    def acquire_overview(self, ov_number, move_required=True):
        """Acquire an overview image with error handling and image inspection"""
        move_success = True
        ov_save_path = None
        ov_accepted = False

        ov_stage_position = self.cs.get_ov_centre_s(ov_number)
        # Move to OV stage coordinates if required:
        if move_required:
            self.add_to_main_log(
                '3VIEW: Moving stage to OV %d position.' % ov_number)
            self.stage.move_to_xy(ov_stage_position)
            if self.stage.get_error_state() > 0:
                self.stage.reset_error_state()
                # Update error log in viewport window with warning message:
                log_str = (str(self.slice_counter) + ': WARNING ('
                           + 'Move to OV%d position failed)'
                           % ov_number)
                self.error_log_file.write(log_str + '\n')
                self.transmit_cmd('VP LOG' + log_str)
                # Try again
                sleep(2)
                self.stage.move_to_xy(ov_stage_position)
                self.error_state = self.stage.get_error_state()
                if self.error_state > 0:
                    self.add_to_main_log('CTRL: Stage failed to move to '
                                         'OV position.')
                    self.pause_acquisition(1)
                    move_success = False
                else:
                    # Show new stage coordinates in GUI:
                    self.transmit_cmd('UPDATE XY')
        if move_success:
            self.add_to_main_log(
                'SEM: Acquiring OV at X:'
                + '{0:.3f}'.format(ov_stage_position[0])
                + ', Y:' + '{0:.3f}'.format(ov_stage_position[1]))
            # Set specified OV frame settings:
            self.sem.apply_frame_settings(
                self.ovm.get_ov_size_selector(ov_number),
                self.ovm.get_ov_pixel_size(ov_number),
                self.ovm.get_ov_dwell_time(ov_number))
            ov_wd = self.ovm.get_ov_wd(ov_number)
            # Use specified OV working distance if available (unavailable = 0)
            if ov_wd > 0:
                self.sem.set_wd(ov_wd)
                self.add_to_main_log(
                    'SEM: Using user-specified WD: '
                    '{0:.6f}'.format(ov_wd * 1000))
            # Path and filename of overview image to be acquired:
            ov_save_path = (self.base_dir
                            + '\\'
                            + utils.get_ov_save_path(self.stack_name,
                                                     ov_number,
                                                     self.slice_counter))
            # Indicate the overview being acquired in the viewport
            self.transmit_cmd('ACQ IND OV' + str(ov_number))
            # Grab the image from SmartSEM
            self.sem.acquire_frame(ov_save_path)
            # Remove indicator colour
            self.transmit_cmd('ACQ IND OV' + str(ov_number))

            # Check if OV saved and show in viewport
            if os.path.isfile(ov_save_path):

                # Inspect the acquired image:
                (ov_img, mean, stddev,
                 range_test_passed,
                 load_error, grab_incomplete) = (
                    self.img_inspector.process_ov(ov_save_path,
                                                  ov_number,
                                                  self.slice_counter))
                # Show OV in viewport and display mean and stddev
                # if no load error:
                if not load_error:
                    self.add_to_main_log(
                        'CTRL: OV: M:'
                        + '{0:.2f}'.format(mean)
                        + ', SD:' + '{0:.2f}'.format(stddev))
                    workspace_save_path = (self.base_dir + '\\workspace\\OV'
                                           + str(ov_number).zfill(3) + '.bmp')
                    imsave(workspace_save_path, ov_img)
                    self.ovm.update_ov_file_list(ov_number, workspace_save_path)
                    # Signal to update viewport:
                    self.transmit_cmd('MV UPDATE OV' + str(ov_number))
                if load_error:
                    self.error_state = 404
                    ov_accepted = False
                    # don't pause yet, will try again
                elif grab_incomplete:
                    self.error_state = 303
                    ov_accepted = False
                    # don't pause yet, will try again
                elif ((self.cfg['acq']['monitor_images'] == 'True')
                    and not range_test_passed):
                    ov_accepted = False
                    self.error_state = 502    # OV image error
                    self.pause_acquisition(1)
                    self.add_to_main_log(
                        'CTRL: OV outside of mean/stddev limits. ')
                else:
                    # OV seems ok in principle.
                    ov_accepted = True
                    # Check for debris:
                    if self.first_ov[ov_number]:
                        self.transmit_cmd('ASK DEBRIS FIRST OV')
                        # The command above causes message box to be displayed
                        # and variables self.user_reply_received and
                        # self.user_reply to be updated
                        while not self.user_reply_received:
                            sleep(0.1)
                        ov_accepted = (
                            self.user_reply == QMessageBox.Yes)
                        if self.user_reply == QMessageBox.Abort:
                            self.pause_acquisition(1)
                        self.user_reply_received = False

                    elif (self.cfg['acq']['use_debris_detection'] == 'True'):
                        # Detect potential debris:
                        debris_detected, msg = self.img_inspector.detect_debris(
                            ov_number,
                            int(self.cfg['debris']['detection_method']))
                        self.add_to_main_log(msg)
                        if debris_detected:
                            ov_accepted = False
                            # Ask user?
                            if self.cfg['acq']['ask_user'] == 'True':
                                self.transmit_cmd('ASK DEBRIS CONFIRMATION')
                                while not self.user_reply_received:
                                    sleep(0.1)
                                ov_accepted = (
                                    self.user_reply == QMessageBox.No)
                                if self.user_reply == QMessageBox.Abort:
                                    self.pause_acquisition(1)
                                self.user_reply_received = False
            else:
                self.add_to_main_log('CTRL: OV acquisition failure.')
                self.error_state = 502
                self.pause_acquisition(1)
                ov_accepted = False

        # Check for "Ask User" override:
        if (self.cfg['acq']['ask_user'] == 'True'
                and self.error_state in [303, 502]):
            self.transmit_cmd('ASK IMAGE ERROR OVERRIDE')
            while not self.user_reply_received:
                sleep(0.1)
            if self.user_reply == QMessageBox.Yes:
                # Proceed anyway, reset error state and accept OV:
                self.error_state = 0
                ov_accepted = True
            else:
                self.image_rejected_by_user = True
            self.user_reply_received = False

        return ov_save_path, ov_accepted

    def save_debris_image(self, ov_file_name, sweep_counter):
        debris_save_path = (self.base_dir
                            + '\\overviews\\debris\\'
                            + ov_file_name[ov_file_name.rfind('\\') + 1:-4]
                            + '_' + str(sweep_counter) + '.tif')
        # Copy current ov_file, TODO: error handling
        shutil.copy(ov_file_name, debris_save_path)

        if self.use_mirror_drive:
            self.mirror_files([debris_save_path])

    def save_rejected_tile(self, tile_save_path, fail_counter):
        rejected_tile_save_path = (
            self.base_dir + '\\tiles\\rejected\\'
            + tile_save_path[tile_save_path.rfind('\\') + 1:-4]
            + '_' + str(fail_counter) + '.tif')
        # Move tile to folder 'rejected', TODO: error handling
        shutil.copy(tile_save_path, rejected_tile_save_path)

    def remove_debris(self):
        """Try to remove detected debris by sweeping the surface. Microtome must
        be active for this function. Cannot be used with SEM stage."""
        self.add_to_main_log('CTRL: Sweeping to remove debris.')
        self.microtome.do_sweep(self.stage_z_position)
        if self.microtome.get_error_state() > 0:
            self.microtome.reset_error_state()
            self.add_to_main_log('CTRL: Problem during sweep. Trying again.')
            # Print warning in viewport window:
            log_str = (str(self.slice_counter)
                       + ': WARNING (' + 'Problem during sweep)')
            self.error_log_file.write(log_str + '\n')
            self.transmit_cmd('VP LOG' + log_str)
            # Trying again after 3 sec:
            sleep(3)
            self.microtome.do_sweep(self.stage_z_position)
            # check if there was again an error during sweeping:
            if self.microtome.get_error_state() > 0:
                self.microtome.reset_error_state()
                self.error_state = 205
                self.pause_acquisition(1)
                self.add_to_main_log('CTRL: Error during second sweep '
                                     'attempt.')

    def acquire_tile(self, grid_number, tile_number):
        """Acquire the specified tile with error handling and inspection."""

        tile_img = None
        relative_save_path = utils.get_tile_save_path(
            self.stack_name, grid_number, tile_number, self.slice_counter)
        save_path = (self.base_dir + '\\' + relative_save_path)
        tile_id = str(grid_number) + '.' + str(tile_number)
        tile_accepted = False  # meaning if True: tile quality is ok
        tile_selected = False  # meaning if False: tile discarded
        tile_skipped = False   # meaning if True: tile already acquired

        # Criterion whether to retake image:
        retake_img = (
            ([grid_number, tile_number] == self.acq_interrupted_at)
            and not (tile_number in self.tiles_acquired))
        # Check if file already exists:
        if (not os.path.isfile(save_path) or retake_img):
            # Read target coordinates for current tile:
            stage_x, stage_y = self.gm.get_tile_coordinates_s(
                grid_number, tile_number)
            # Move to that position:
            self.add_to_main_log('3VIEW: Moving stage to position '
                          'of tile %s' % tile_id)
            self.stage.move_to_xy((stage_x, stage_y))
            # The move function waits for the specified stage move wait interval
            # Check if there were microtome problems:
            # If yes, try one more time before pausing acquisition.
            if self.stage.get_error_state() > 0:
                self.stage.reset_error_state()
                self.add_to_main_log('CTRL: Problem detected (XY '
                              'stage move). Trying again.')
                # Error_log in viewport window:
                error_log_str = (str(self.slice_counter)
                    + ': WARNING (Problem with XY stage move)')
                self.error_log_file.write(error_log_str + '\n')
                # Signal to main window to update log in viewport:
                self.transmit_cmd('VP LOG' + error_log_str)
                sleep(2)
                # Try to move to tile position again:
                self.add_to_main_log('3VIEW: Moving stage to position '
                              'of tile ' + tile_id)
                self.stage.move_to_xy((stage_x, stage_y))
                # Check again if there is a failure:
                self.error_state = self.stage.get_error_state()
                self.stage.reset_error_state()
                # If yes, pause stack:
                if self.error_state > 0:
                    self.add_to_main_log(
                        'CTRL: Problem detected (XY '
                        'stage move failed). Stack will '
                        'be paused.')
        else:
            if tile_number in self.tiles_acquired:
                tile_skipped = True
                tile_accepted = True
                self.add_to_main_log(
                    'CTRL: Tile %s already acquired. Skipping.' % tile_id)
            else:
                # If tile already exists without being listed as acquired
                # and no indication of previous interruption:
                # pause because risk of overwriting data!
                self.error_state = 403
                self.add_to_main_log('CTRL: Problem detected. ')
                self.add_to_main_log(
                    'CTRL: Tile %s: Image file already exists!' %tile_id)

        # Proceed if no error has ocurred and tile not skipped:
        if self.error_state == 0 and not tile_skipped:

            # Show updated stage coordinates in main window:
            self.transmit_cmd('UPDATE XY')

            # Perform autofocus (method 0, SmartSEM) on current tile?
            if (self.af.is_active() and self.af.get_method() == 0
                    and self.af.is_tile_selected(grid_number, tile_number)
                    and (self.autofocus_stig_current_slice[0] or
                         self.autofocus_stig_current_slice[1])):
                do_move = False  # already at tile stage position
                self.perform_zeiss_autofocus(
                    *self.autofocus_stig_current_slice,
                    do_move, grid_number, tile_number)
                # For tracking mode 0: Adjust wd/stig of other tiles:
                if self.af.get_tracking_mode() == 0:
                    self.af.approximate_tile_wd_stig(grid_number)
                    self.transmit_cmd('DRAW MV')

            # Check mag if locked:
            if self.mag_locked and not self.error_state in [505, 506, 507]:
                self.check_locked_mag()
            # Check focus if locked:
            if (self.wd_stig_locked
                and not self.error_state in [505, 506, 507]):
                self.check_locked_wd_stig()

            # Now acquire the frame:
            # (even if failure detected. May be helpful.)
            self.add_to_main_log('SEM: Acquiring tile at X:'
                          + '{0:.3f}'.format(stage_x)
                          + ', Y:' + '{0:.3f}'.format(stage_y))
            # Indicate current tile in Viewport:
            self.transmit_cmd('ACQ IND TILE'
                              + str(grid_number) + '.' + str(tile_number))
            # Grab frame:
            self.sem.acquire_frame(save_path)
            # Remove indication in Viewport:
            self.transmit_cmd('ACQ IND TILE'
                              + str(grid_number) + '.' + str(tile_number))
            # Copy to mirror drive:
            if self.use_mirror_drive:
                self.mirror_files([save_path])
            # Check if image was saved and process it:
            if os.path.isfile(save_path):
                (tile_img, mean, stddev,
                 range_test_passed, slice_by_slice_test_passed,
                 tile_selected,
                 load_error, grab_incomplete, frozen_frame_error) = (
                    self.img_inspector.process_tile(
                        save_path,
                        grid_number,
                        tile_number,
                        self.slice_counter))

                if not load_error:
                    self.add_to_main_log('CTRL: Tile ' + tile_id
                                  + ': M:' + '{0:.2f}'.format(mean)
                                  + ', SD:' + '{0:.2f}'.format(stddev))
                    # New thumbnail available, show it:
                    self.transmit_cmd('DRAW MV')

                    tile_accepted = True
                    # When monitoring enabled check if tile ok:
                    if self.cfg['acq']['monitor_images'] == 'True':
                        if not range_test_passed:
                            tile_accepted = False
                            self.error_state = 503
                            self.add_to_main_log(
                                'CTRL: Tile outside of permitted mean/SD '
                                'range!')
                        if (slice_by_slice_test_passed is not None
                            and not slice_by_slice_test_passed):
                            tile_accepted = False
                            self.error_state = 504
                            self.add_to_main_log(
                                'CTRL: Tile above mean/SD slice-by-slice '
                                'thresholds.')
                    # Check for frozen or incomplete frames:
                    if frozen_frame_error:
                        tile_accepted = False
                        self.error_state = 304
                        self.add_to_main_log('CTRL: Tile ' + tile_id
                            + ': SmartSEM frozen frame error!')
                    elif grab_incomplete:
                        tile_accepted = False
                        self.error_state = 303
                        self.add_to_main_log('CTRL: Tile ' + tile_id
                            + ': SmartSEM grab incomplete error!')
                    if self.error_state in [505, 506, 507]:
                        # Don't accept tile if autofocus error has ocurred:
                        tile_accepted = False
                else:
                    tile_accepted = False
                    self.error_state = 404 # load error
            else:
                # File was not saved -> tile image error:
                self.add_to_main_log('CTRL: Tile image acquisition failure. ')
                self.error_state = 302

        # Check for "Ask User" override:
        if (self.cfg['acq']['ask_user'] == 'True'
                and self.error_state in [303, 304, 503, 504]):
            self.transmit_cmd('ASK IMAGE ERROR OVERRIDE')
            while not self.user_reply_received:
                sleep(0.1)
            if self.user_reply == QMessageBox.Yes:
                # Proceed anyway, reset error state and accept tile:
                self.error_state = 0
                tile_accepted = True
            else:
                self.image_rejected_by_user = True
            self.user_reply_received = False

        return (tile_img, relative_save_path, save_path,
                tile_accepted, tile_skipped, tile_selected)

    def acquire_grid(self, grid_number):
        """Acquire all active tiles of grid specified by grid_number"""

        self.use_adaptive_focus = self.gm.is_adaptive_focus_active(grid_number)
        # Get size and active tiles  (using list() to get a copy)
        active_tiles = list(self.gm.get_active_tiles(grid_number))

        # WD and stig must be adjusted for each tile if adaptive focus active
        # of if autofocus is used with "track all" or "best fit" option.
        # Otherwise self.wd_current_grid, self.stig_x_current_grid,
        # and self.stig_y_current_grid are used.
        adjust_wd_stig_for_each_tile = (
            self.use_adaptive_focus
            or (self.af.is_active() and self.af.get_tracking_mode() < 2))

        if self.pause_state != 1:
            self.add_to_main_log(
                'CTRL: Starting acquisition of active '
                'tiles in grid %d' % grid_number)
            # Switch to specified settings of the current grid
            self.sem.apply_frame_settings(
                self.gm.get_tile_size_selector(grid_number),
                self.gm.get_pixel_size(grid_number),
                self.gm.get_dwell_time(grid_number))

            # Delay necessary for Gemini? (change of mag)
            sleep(0.2)
            # Lock magnification:
            self.lock_mag()

            if self.acq_interrupted:
                # Remove tiles that are no longer active from acquired_tiles list
                acq_tmp = list(self.tiles_acquired)
                for tile in acq_tmp:
                    if not (tile in active_tiles):
                        self.tiles_acquired.remove(tile)

            tile_width, tile_height = self.gm.get_tile_size_px_py(grid_number)

            # Set WD and stig settings for the current grid and lock the settings:
            if not adjust_wd_stig_for_each_tile:
                self.set_grid_wd_stig()
                self.lock_wd_stig()

            # ===================== Grid acquisition loop =========================
            for tile_number in active_tiles:
                fail_counter = 0
                tile_accepted = False
                tile_id = str(grid_number) + '.' + str(tile_number)
                # Individual WD/stig adjustment for tile, if necessary:
                if adjust_wd_stig_for_each_tile:
                    new_wd = self.gm.get_tile_wd(grid_number, tile_number)
                    new_stig_xy = self.gm.get_tile_stig_xy(grid_number, tile_number)
                    self.sem.set_wd(new_wd)
                    self.sem.set_stig_xy(*new_stig_xy)
                    self.log_wd_stig(new_wd, new_stig_xy[0], new_stig_xy[1])
                # Acquire the current tile, up to three attempts:
                while not tile_accepted and fail_counter < 3:
                    (tile_img, relative_save_path, save_path,
                     tile_accepted, tile_skipped, tile_selected) = (
                        self.acquire_tile(grid_number, tile_number))

                    if (self.error_state in [302, 303, 304, 404]
                            and not self.image_rejected_by_user) :
                        self.save_rejected_tile(save_path, fail_counter)
                        # Try again, problem may disappear:
                        fail_counter += 1
                        if fail_counter == 3:
                            # Pause after third failed attempt
                            self.pause_acquisition(1)
                        else:
                            # Remove the file to avoid overwrite error:
                            os.remove(save_path)
                            self.add_to_main_log(
                            'CTRL: Trying again to image tile.')
                            # Reset error state:
                            self.error_state = 0
                    elif self.error_state > 0:
                        self.pause_acquisition(1)
                        break
                # end of tile aquisition while loop

                if tile_accepted and tile_selected and not tile_skipped:
                    # Write tile's name and position into imagelist:
                    self.register_accepted_tile(relative_save_path,
                                                grid_number, tile_number,
                                                tile_width, tile_height)
                    # Save stats and reslice:
                    success = self.img_inspector.save_tile_stats(
                        grid_number, tile_number, self.slice_counter)
                    if not success:
                        self.add_to_main_log(
                            'CTRL: Error saving tile mean and SD to disk.')
                    success = self.img_inspector.save_tile_reslice(
                        grid_number, tile_number)
                    if not success:
                        self.add_to_main_log(
                            'CTRL: Error saving tile reslice to disk.')

                    # If heuristic autofocus enabled and tile selected as
                    # reference tile, prepare tile for processing:
                    if (self.af.is_active() and self.af.get_method() == 1
                            and self.af.is_tile_selected(grid_number, tile_number)):
                        tile_key = str(grid_number) + '.' + str(tile_number)
                        self.af.crop_tile_for_heuristic_af(
                            tile_img, tile_key)
                        self.heuristic_af_queue.append(tile_key)

                elif (not tile_selected
                      and not tile_skipped
                      and self.error_state == 0):
                    self.add_to_main_log(
                        'CTRL: Tile %s was discarded by image inspector.' %tile_id)
                    # Delete file:
                    try:
                        os.remove(save_path)
                    except:
                        self.add_to_main_log(
                            'CTRL: Tile image file could not be deleted.')
                # Was acq paused by user or interrupted by error? Save current pos:
                if self.pause_state == 1:
                    self.save_interruption_point(grid_number, tile_number)
                    break
            # ================== End of grid acquisition loop =====================

            if len(active_tiles) == len(self.tiles_acquired):
                # Grid is complete, add it to the grids_acquired list:
                self.grids_acquired.append(grid_number)
                self.cfg['acq']['grids_acquired'] = str(self.grids_acquired)
                # Empty the tile list since all tiles were acquired:
                self.tiles_acquired = []
                self.cfg['acq']['tiles_acquired'] = '[]'


    def register_accepted_tile(self, save_path, grid_number, tile_number,
                               tile_width, tile_height):
        """Register the tile image in the image list file and the metadata
           file. Send metadata to remote server.
        """
        timestamp = int(time.time())
        tile_id = utils.get_tile_id(grid_number, tile_number,
                                    self.slice_counter)
        global_x, global_y = (
            self.gm.get_tile_coordinates_for_registration(
                grid_number, tile_number))
        global_z = int(self.total_z_diff * 1000)
        tileinfo_str = (save_path + ';'
                         + str(global_x) + ';'
                         + str(global_y) + ';'
                         + str(global_z) + ';'
                         + str(self.slice_counter) + '\n')
        self.imagelist_file.write(tileinfo_str)
        # Write to mirror:
        if self.use_mirror_drive:
            self.mirror_imagelist_file.write(tileinfo_str)
        self.tiles_acquired.append(tile_number)
        self.cfg['acq']['tiles_acquired'] = str(
            self.tiles_acquired)
        wd = 0
        tile_metadata = {
            'timestamp': timestamp,
            'tileid': tile_id,
            'filename': save_path.replace('\\', '/'),
            'tile_width': tile_width,
            'tile_height': tile_height,
            'working_distance': wd,
            'glob_x': global_x,
            'glob_y': global_y,
            'glob_z': global_z,
            'slice_counter': self.slice_counter}
        self.metadata_file.write('TILE: ' + str(tile_metadata) + '\n')
        # Server notification:
        if self.send_metadata:
            url = self.metadata_server + '/tile/metadata/update'
            response = utils.meta_server_post_request(url, tile_metadata)
            if response == 100:
                self.error_state = 508
                self.pause_acquisition(1)
                self.add_to_main_log('CTRL: Error sending tile metadata '
                                     'to server.')

    def perform_zeiss_autofocus(self, do_focus, do_stig, do_move,
                                grid_number, tile_number):
        """Run SmartSEM autofocus at current stage position if do_move == False,
           otherwise move to grid_number.tile_number position beforehand.
        """
        if do_move:
            # Read target coordinates for current tile:
            stage_x, stage_y = self.gm.get_tile_coordinates_s(
                grid_number, tile_number)
            # Move to that position:
            self.add_to_main_log(
                '3VIEW: Moving stage to position of tile '
                + str(grid_number) + '.' + str(tile_number) + ' for autofocus')
            self.stage.move_to_xy((stage_x, stage_y))
            # The move function waits for the specified stage move wait interval
            # Check if there were microtome problems:
            # If yes, try one more time before pausing acquisition.
            if self.stage.get_error_state() > 0:
                self.stage.reset_error_state()
                self.add_to_main_log('CTRL: Problem detected (XY '
                              'stage move). Trying again.')
                # Error_log in viewport window:
                error_log_str = (str(self.slice_counter)
                    + ': WARNING (Problem with XY stage move)')
                self.error_log_file.write(error_log_str + '\n')
                # Signal to main window to update log in viewport:
                self.transmit_cmd('VP LOG' + error_log_str)
                sleep(2)
                # Try to move to tile position again:
                self.add_to_main_log(
                    '3VIEW: Moving stage to position of tile '
                    + str(grid_number) + '.' + str(tile_number))
                self.stage.move_to_xy((stage_x, stage_y))
                # Check again if there is a failure:
                self.error_state = self.stage.get_error_state()
                self.stage.reset_error_state()
                # If yes, pause stack:
                if self.error_state > 0:
                    self.add_to_main_log(
                        'CTRL: Problem detected (XY stage move failed).')
        if self.error_state == 0 and (do_focus or do_stig):
            if do_focus and do_stig:
                af_type = '(focus+stig)'
            elif do_focus:
                af_type = '(focus only)'
            elif do_stig:
                af_type = '(stig only)'
            self.add_to_main_log('CTRL: Running SmartSEM AF procedure '
                                 + af_type + ' for tile '
                                 + str(grid_number) + '.' + str(tile_number))
            return_msg = self.af.run_zeiss_af(do_focus, do_stig)
            self.add_to_main_log(return_msg)
            if 'ERROR' in return_msg:
                self.error_state = 505
            else:
                # Save settings for current tile:
                self.gm.set_tile_wd(grid_number, tile_number, self.sem.get_wd())
                self.gm.set_tile_stig_xy(grid_number, tile_number,
                                        *self.sem.get_stig_xy())

                # Show updated WD in viewport:
                self.transmit_cmd('DRAW MV')

            # Restore grid settings for tile acquisition:
            self.sem.apply_frame_settings(
                self.gm.get_tile_size_selector(grid_number),
                self.gm.get_pixel_size(grid_number),
                self.gm.get_dwell_time(grid_number))
            # Delay necessary for Gemini (change of mag):
            sleep(0.2)

    def do_autofocus_before_grid_acq(self, grid_number):
        """If non-active tiles are selected for the SmartSEM autofocus, call the
        autofocus on them one by one before the grid acquisition starts."""
        autofocus_tiles = self.af.get_ref_tiles_in_grid(grid_number)
        active_tiles = self.gm.get_active_tiles(grid_number)
        # Perform Zeiss autofocus for non-active autofocus tiles:
        for tile in autofocus_tiles:
            if tile not in active_tiles:
                do_move = True
                self.perform_zeiss_autofocus(
                    *self.autofocus_stig_current_slice,
                    do_move, grid_number, tile)
                if self.error_state != 0 or self.pause_state == 1:
                    # Immediately pause and save interruption info
                    if not self.acq_paused:
                        self.pause_acquisition(1)
                    self.save_interruption_point(grid_number, t)
                    break

    def perform_heuristic_autofocus(self, tile_key):
        self.add_to_main_log('CTRL: Processing tile %s for '
            'heuristic autofocus ' %tile_key)
        self.af.process_image_for_heuristic_af(tile_key)
        wd_corr, sx_corr, sy_corr, within_range = (
            self.af.get_heuristic_corrections(tile_key))
        if wd_corr is not None:
            self.add_to_main_log('CTRL: New corrections: '
                                 + '{0:.6f}, '.format(wd_corr)
                                 + '{0:.6f}, '.format(sx_corr)
                                 + '{0:.6f}'.format(sy_corr))
            if not within_range:
                # The difference in WD/STIG was too large.
                self.error_state = 507
                self.pause_acquisition(1)
        else:
            self.add_to_main_log('CTRL: No estimates computed (need one additional slice) ')

    def handle_autofocus_adjustments(self, grid_number):
        # Apply average WD/STIG from reference tiles
        # if tracking mode "Average" is selected:
        if self.af.is_active() and self.af.get_tracking_mode() == 2:
            if self.af.get_method() == 0:
                self.add_to_main_log(
                    'CTRL: Applying average WD/STIG parameters '
                    '(SmartSEM autofocus).')
            elif self.af.get_method() == 1:
                self.add_to_main_log(
                    'CTRL: Applying average WD/STIG parameters '
                    '(heuristic autofocus).')
            # Compute new grid average for WD and STIG:
            avg_grid_wd, avg_grid_stig_x, avg_grid_stig_y = (
                self.af.get_ref_tile_average_wd_stig(grid_number))
            if (avg_grid_wd is not None
                    and avg_grid_stig_x is not None
                    and avg_grid_stig_y is not None):
                # TODO: Check if difference within acceptable range
                # Apply:
                self.wd_current_grid = avg_grid_wd
                self.stig_x_current_grid = avg_grid_stig_x
                self.stig_y_current_grid = avg_grid_stig_y
                # Update grid:
                self.gm.set_wd_stig_for_grid(
                    grid_number, avg_grid_wd, avg_grid_stig_x, avg_grid_stig_y)
                #else:
                #    self.add_to_main_log(
                #        'CTRL: Error: Difference in WD/STIG too large.')
                #    self.error_state = 507
                #    self.pause_acquisition(1)

        # If "Individual + Approximate" mode selected - approximate the working
        # distances and stig parameters for all non-autofocus tiles that are
        # active:
        if (self.af.is_active()
            and self.af.get_tracking_mode() == 0):
            self.af.approximate_tile_wd_stig(grid_number)

        # If adaptive focus active, adjust focus for grid(s):
        # TODO

    def lock_wd_stig(self):
        self.locked_wd = self.sem.get_wd()
        self.locked_stig_x = self.sem.get_stig_x()
        self.locked_stig_y = self.sem.get_stig_y()
        self.wd_stig_locked = True

    def lock_mag(self):
        self.locked_mag = self.sem.get_mag()
        self.mag_locked = True
        self.add_to_main_log(
            'SEM: Locked magnification: ' + str(self.locked_mag))

    def set_grid_wd_stig(self):
        """Set wd/stig to target values for the current grid and add deltas
        for heuristic autofocus"""
        wd = self.wd_current_grid + self.wd_delta
        stig_x = self.stig_x_current_grid + self.stig_x_delta
        stig_y = self.stig_y_current_grid + self.stig_y_delta
        self.sem.set_wd(wd)
        self.sem.set_stig_xy(stig_x, stig_y)
        self.log_wd_stig(wd, stig_x, stig_y)

    def check_locked_wd_stig(self):
        """Check if wd/stig was accidentally changed and restore targets."""
        change_detected = False
        diff_wd = abs(self.sem.get_wd() - self.locked_wd)
        diff_stig_x = abs(self.sem.get_stig_x() - self.locked_stig_x)
        diff_stig_y = abs(self.sem.get_stig_y() - self.locked_stig_y)

        if diff_wd > 0.000001:
            change_detected = True
            self.add_to_main_log(
                'CTRL: Warning: Change in working distance detected.')
            #Fix it:
            self.add_to_main_log('CTRL: Resetting working distance.')
            self.sem.set_wd(self.locked_wd)
        if (diff_stig_x > 0.000001 or diff_stig_y > 0.000001):
            change_detected = True
            self.add_to_main_log(
                'CTRL: Warning: Change in stigmation settings detected.')
            #Fix it:
            self.add_to_main_log('CTRL: Resetting stigmation parameters.')
            self.sem.set_stig_xy(self.locked_stig_x, self.locked_stig_y)
        if change_detected:
            self.transmit_cmd('FOCUS ALERT')

    def check_locked_mag(self):
        """Check if mag was accidentally changed and restore target mag."""
        current_mag = self.sem.get_mag()
        if current_mag != self.locked_mag:
            self.add_to_main_log(
                'CTRL: Warning: Change in magnification detected.')
            self.add_to_main_log(
                'CTRL: Current mag: ' + str(current_mag)
                + '; target mag: ' + str(self.locked_mag))
            #Fix it:
            self.add_to_main_log('CTRL: Resetting magnification.')
            self.sem.set_mag(self.locked_mag)
            self.transmit_cmd('MAG ALERT')

    def log_wd_stig(self, wd, stig_x, stig_y):
        self.add_to_main_log(
            'SEM: WD/STIG_XY: '
            + '{0:.6f}'.format(wd * 1000)
            + ', {0:.6f}'.format(stig_x)
            + ', {0:.6f}'.format(stig_y))

    def set_user_reply(self, reply):
        """Receive a user reply from main window."""
        self.user_reply = reply
        self.user_reply_received = True

    def reset_acquisition(self):
        self.slice_counter = 0
        self.cfg['acq']['slice_counter'] = '0'
        self.total_z_diff = 0
        self.cfg['acq']['total_z_diff'] = '0.0'
        self.stack_completed = False
        self.cfg['acq']['paused'] = 'False'
        self.cfg['acq']['interrupted'] = 'False'
        self.cfg['acq']['interrupted_at'] = '[]'
        self.cfg['acq']['tiles_acquired'] = '[]'
        self.cfg['acq']['grids_acquired'] = '[]'

    # TODO: Remove unnecessary getters and setters, use direct access.
    def get_slice_counter(self):
        return self.slice_counter

    def set_slice_counter(self, slice_counter):
        self.slice_counter = slice_counter
        self.cfg['acq']['slice_counter'] = str(slice_counter)

    def get_number_slices(self):
        return self.number_slices

    def set_number_slices(self, number_slices):
        self.number_slices = number_slices
        self.cfg['acq']['number_slices'] = str(number_slices)

    def get_slice_thickness(self):
        return self.slice_thickness

    def set_slice_thickness(self, slice_thickness):
        self.slice_thickness = slice_thickness
        self.cfg['acq']['slice_thickness'] = str(slice_thickness)

    def get_total_z_diff(self):
        return self.total_z_diff

    def set_total_z_diff(self, z_diff):
        self.total_z_diff = z_diff
        self.cfg['acq']['total_z_diff'] = str(z_diff)

    def is_paused(self):
        return (self.cfg['acq']['paused'] == 'True')

    def transmit_cmd(self, cmd):
        """Transmit command to the main window thread."""
        self.queue.put(cmd)
        self.trigger.s.emit()

    def add_to_main_log(self, msg):
        """Add entry to the log in the main window"""
        msg = utils.format_log_entry(msg)
        # Store entry in main log file:
        self.main_log_file.write(msg + '\n')
        # Send entry to main window via queue and trigger:
        self.queue.put(msg)
        self.trigger.s.emit()

    def pause_acquisition(self, pause_state):
        """Pause the current acquisition."""
        if pause_state == 1:   # Pause immediately after the current image
            self.pause_state = 1
            self.acq_paused = True
            self.cfg['acq']['paused'] = 'True'
        elif pause_state == 2:   # Pause after finishing current slice and cutting
            self.pause_state = 2
            self.acq_paused = True
            self.cfg['acq']['paused'] = 'True'

    def save_interruption_point(self, grid_number, tile_number):
        """Save grid/tile position where interruption occured."""
        self.acq_interrupted = True
        self.cfg['acq']['interrupted'] = 'True'
        self.acq_interrupted_at = [grid_number, tile_number]
        self.cfg['acq']['interrupted_at'] = str(self.acq_interrupted_at)

    def reset_interruption_info(self):
        self.acq_interrupted = False
        self.cfg['acq']['interrupted'] = 'False'
        self.acq_interrupted_at = []
        self.cfg['acq']['interrupted_at'] = '[]'
        self.acquired_tiles = []
        self.cfg['acq']['tiles_acquired'] = '[]'
        self.acquired_grids = []
        self.cfg['acq']['grids_acquired'] = '[]'
