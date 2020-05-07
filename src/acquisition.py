# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module controls the acquisition process for SBEM stacks or wafers.

The instance self.acq from class Acquisition is created in main_controls.py. Its
method run(), which contains the acquisition loop, is started in a thread from
main_controls.py.
"""

import os
import shutil
import datetime
import json

from time import sleep, time
from statistics import mean
from imageio import imwrite
from dateutil.relativedelta import relativedelta
from PyQt5.QtWidgets import QMessageBox

import utils


class Acquisition:

    def __init__(self, config, sysconfig, sem, microtome, stage,
                 overview_manager, grid_manager, coordinate_system,
                 image_inspector, autofocus, notifications,
                 main_controls_trigger):
        self.cfg = config
        self.syscfg = sysconfig
        self.sem = sem
        self.microtome = microtome
        self.stage = stage
        self.ovm = overview_manager
        self.gm = grid_manager
        self.cs = coordinate_system
        self.img_inspector = image_inspector
        self.autofocus = autofocus
        self.notifications = notifications
        self.main_controls_trigger = main_controls_trigger

        self.error_state = 0
        self.error_info = ''

        # Log file handles
        self.main_log_file = None
        self.imagelist_file = None
        self.mirror_imagelist_file = None
        self.debris_log_file = None
        self.error_log_file = None
        self.metadata_file = None

        # pause_state:
        # 1 -> pause immediately, 2 -> pause after completing current slice
        self.pause_state = None
        self.acq_paused = (self.cfg['acq']['paused'].lower() == 'true')
        self.stack_completed = False
        self.report_requested = False
        self.slice_counter = int(self.cfg['acq']['slice_counter'])
        self.number_slices = int(self.cfg['acq']['number_slices'])
        self.slice_thickness = int(self.cfg['acq']['slice_thickness'])
        # total_z_diff: The total Z of sample removed in microns.
        self.total_z_diff = float(self.cfg['acq']['total_z_diff'])
        # stage_z_position: The current Z position of the microtome/stage.
        # This variable is updated when the stack is (re)started by reading the
        # Z position from the microtome/stage hardware.
        self.stage_z_position = None
        # eht_off_after_stack: If set to True, switch off EHT automatically
        # after stack is completed.
        self.eht_off_after_stack = (
            self.cfg['acq']['eht_off_after_stack'].lower() == 'true')
        # Was previous acq interrupted by error or paused inbetween by user?
        self.acq_interrupted = (
            self.cfg['acq']['interrupted'].lower() == 'true')
        # acq_interrupted_at: Position provided as [grid_index, tile_index]
        self.acq_interrupted_at = json.loads(self.cfg['acq']['interrupted_at'])
        # tiles_acquired: Tiles that were already acquired in the the grid
        # where the interruption occured.
        self.tiles_acquired = json.loads(self.cfg['acq']['tiles_acquired'])
        # grids_acquired: Grids that have been acquired before interruption
        # occured.
        self.grids_acquired = json.loads(self.cfg['acq']['grids_acquired'])

        # Remove trailing slashes and whitespace from base directory string
        self.cfg['acq']['base_dir'] = self.cfg['acq']['base_dir'].rstrip(r'\/ ')
        self.base_dir = self.cfg['acq']['base_dir']
        self.vp_screenshot_filename = None
        self.mirror_drive = self.cfg['sys']['mirror_drive']
        # mirror_drive_directory: same as base_dir, only drive letter changes
        self.mirror_drive_dir = os.path.join(
            self.cfg['sys']['mirror_drive'], self.base_dir[2:])
        # send_metadata: True if metadata to be sent to metadata (VIME) server
        self.send_metadata = (
            self.cfg['sys']['send_metadata'].lower() == 'true')
        self.metadata_project_name = self.cfg['sys']['metadata_project_name']
        # The following two features (mirror drive, overviews) can not be
        # enabled/disabled during a run. Other features such as debris
        # detection and monitoring can be enabled/disabled during a run
        self.use_mirror_drive = (
            self.cfg['sys']['use_mirror_drive'].lower() == 'true')
        self.take_overviews = (
            self.cfg['acq']['take_overviews'].lower() == 'true')
        # Options that can be changed while acq is running
        self.use_email_monitoring = (
            self.cfg['acq']['use_email_monitoring'].lower() == 'true')
        self.use_debris_detection = (
            self.cfg['acq']['use_debris_detection'].lower() == 'true')
        self.ask_user_mode = (
            self.cfg['acq']['ask_user'].lower() == 'true')
        self.monitor_images = (
            self.cfg['acq']['monitor_images'].lower() == 'true')
        self.use_autofocus = (
            self.cfg['acq']['use_autofocus'].lower() == 'true')
        self.status_report_interval = int(
            self.cfg['monitoring']['report_interval'])

        self.remote_check_interval = int(
            self.cfg['monitoring']['remote_check_interval'])
        # Settings for sweeping when debris is detected
        self.max_number_sweeps = int(self.cfg['debris']['max_number_sweeps'])
        self.continue_after_max_sweeps = (
            self.cfg['debris']['continue_after_max_sweeps'].lower() == 'true')

        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')

    @property
    def base_dir(self):
        return self._base_dir

    @base_dir.setter
    def base_dir(self, new_base_dir):
        self._base_dir = new_base_dir
        # Extract the name of the stack from the base directory
        self.stack_name = self.base_dir[self.base_dir.rfind('\\') + 1:]

    def save_to_cfg(self):
        """Save current state of attributes to ConfigParser objects."""
        self.cfg['acq']['base_dir'] = self.base_dir
        self.cfg['acq']['paused'] = str(self.acq_paused)
        self.cfg['acq']['slice_counter'] = str(self.slice_counter)
        self.cfg['acq']['number_slices'] = str(self.number_slices)
        self.cfg['acq']['slice_thickness'] = str(self.slice_thickness)
        self.cfg['acq']['total_z_diff'] = str(self.total_z_diff)

        self.cfg['acq']['interrupted'] = str(self.acq_interrupted)
        self.cfg['acq']['interrupted_at'] = str(self.acq_interrupted_at)
        self.cfg['acq']['tiles_acquired'] = str(self.tiles_acquired)
        self.cfg['acq']['grids_acquired'] = str(self.grids_acquired)

        self.cfg['sys']['mirror_drive'] = self.mirror_drive
        self.cfg['sys']['use_mirror_drive'] = str(self.use_mirror_drive)
        self.cfg['sys']['send_metadata'] = str(self.send_metadata)
        self.cfg['sys']['metadata_project_name'] = self.metadata_project_name
        self.cfg['acq']['take_overviews'] = str(self.take_overviews)
        # Options that can be changed while acq is running
        self.cfg['acq']['use_email_monitoring'] = str(
            self.use_email_monitoring)
        self.cfg['acq']['use_debris_detection'] = str(
            self.use_debris_detection)
        self.cfg['acq']['ask_user'] = str(self.ask_user_mode)
        self.cfg['acq']['monitor_images'] = str(self.monitor_images)
        self.cfg['acq']['use_autofocus'] = str(self.use_autofocus)
        self.cfg['acq']['eht_off_after_stack'] = str(self.eht_off_after_stack)
        # Status report settings
        self.cfg['monitoring']['report_interval'] = str(
            self.status_report_interval)
        self.cfg['monitoring']['remote_check_interval'] = str(
            self.remote_check_interval)
        self.cfg['debris']['max_number_sweeps'] = str(self.max_number_sweeps)
        self.cfg['debris']['continue_after_max_sweeps'] = str(
            self.continue_after_max_sweeps)

    def calculate_estimates(self):
        """Calculate the current electron dose (range), the dimensions of
        the stack, the estimated duration of the stack acquisition, the storage
        requirements, and the estimated date and time of completion.

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
        current = self.sem.target_beam_current
        min_dose = max_dose = None
        if self.microtome is not None:
            total_cut_time = (
                self.number_slices * self.microtome.full_cut_duration)
        else:
            total_cut_time = 0
        total_grid_area = 0
        total_data = 0
        total_stage_move_time = 0
        total_imaging_time = 0

        # Default estimate: overhead per acquired frame for saving the frame on
        # primary drive and for inspection
        overhead_per_frame = 1.0
        # Add 0.5 s per frame when mirroring files
        if self.use_mirror_drive:
            overhead_per_frame += 0.5

        max_offset_slice_number = max(
            self.gm.max_acq_interval_offset(),
            self.ovm.max_acq_interval_offset())
        max_interval_slice_number = max(
            self.gm.max_acq_interval(),
            self.ovm.max_acq_interval())

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
            x0, y0 = self.ovm[0].centre_sx_sy
            for slice_counter in range(from_slice, to_slice):
                if self.take_overviews:
                    # Run through all overviews
                    for ov_index in range(self.ovm.number_ov):
                        if self.ovm[ov_index].slice_active(slice_counter):
                            x1, y1 = self.ovm[ov_index].centre_sx_sy
                            stage_move_time += (
                                self.stage.stage_move_duration(x0, y0, x1, y1))
                            x0, y0 = x1, y1
                            imaging_time += self.ovm[ov_index].tile_cycle_time()
                            imaging_time += overhead_per_frame
                            frame_size = (self.ovm[ov_index].width_p()
                                          * self.ovm[ov_index].height_p())
                            amount_of_data += frame_size
                # Run through all grids
                for grid_index in range(self.gm.number_grids):
                    if self.gm[grid_index].slice_active(slice_counter):
                        for tile_index in self.gm[grid_index].active_tiles:
                            x1, y1 = self.gm[grid_index][tile_index].sx_sy
                            stage_move_time += (
                                self.stage.stage_move_duration(x0, y0, x1, y1))
                            x0, y0 = x1, y1
                        number_active_tiles = (
                            self.gm[grid_index].number_active_tiles())
                        imaging_time += (
                            (self.gm[grid_index].tile_cycle_time()
                            + overhead_per_frame)
                            * number_active_tiles)
                        frame_size = (self.gm[grid_index].tile_width_p()
                                      * self.gm[grid_index].tile_height_p())
                        amount_of_data += frame_size * number_active_tiles
                # Add time to move back to starting position
                if self.take_overviews:
                    x1, y1 = self.ovm[0].centre_sx_sy
                    stage_move_time += (
                        self.stage.stage_move_duration(x0, y0, x1, y1))
                    x0, y0 = x1, y1

            return imaging_time, stage_move_time, amount_of_data
        # ========= End of inner function calculate_for_slice_range() ==========

        if N <= max_offset_slice_number + max_interval_slice_number:
            # Calculate for all slices
            imaging_time_0, stage_move_time_0, amount_of_data_0 = (
                calculate_for_slice_range(0, N))
            imaging_time_1, stage_move_time_1, amount_of_data_1 = 0, 0, 0
        else:
            # First part (up to max_offset_slice_number)
            imaging_time_0, stage_move_time_0, amount_of_data_0 = (
                calculate_for_slice_range(0, max_offset_slice_number))
            # Fraction of remaining slices that are acquired in
            # regular intervals
            imaging_time_1, stage_move_time_1, amount_of_data_1 = (
                calculate_for_slice_range(
                    max_offset_slice_number,
                    max_offset_slice_number + max_interval_slice_number))
            # Extrapolate for the remaining number of slices
            if N > max_offset_slice_number + max_interval_slice_number:
                factor = ((N - max_offset_slice_number)
                          / max_interval_slice_number)
                imaging_time_1 *= factor
                stage_move_time_1 *= factor
                amount_of_data_1 *= factor

        total_imaging_time = imaging_time_0 + imaging_time_1
        total_stage_move_time = stage_move_time_0 + stage_move_time_1
        total_data = amount_of_data_0 + amount_of_data_1

        # Calculate grid area and electron dose range
        for grid_index in range(self.gm.number_grids):
            number_active_tiles = self.gm[grid_index].number_active_tiles()
            total_grid_area += (number_active_tiles
                                * self.gm[grid_index].tile_width_d()
                                * self.gm[grid_index].tile_height_d())
            dwell_time = self.gm[grid_index].dwell_time
            pixel_size = self.gm[grid_index].pixel_size
            dose = utils.calculate_electron_dose(
                current, dwell_time, pixel_size)
            if (min_dose is None) or (dose < min_dose):
                min_dose = dose
            if (max_dose is None) or (dose > max_dose):
                max_dose = dose

        if self.take_overviews:
            for ov_index in range(self.ovm.number_ov):
                dwell_time = self.ovm[ov_index].dwell_time
                pixel_size = self.ovm[ov_index].pixel_size
                dose = utils.calculate_electron_dose(
                    current, dwell_time, pixel_size)
                if (min_dose is None) or (dose < min_dose):
                    min_dose = dose
                if (max_dose is None) or (dose > max_dose):
                    max_dose = dose

        total_z = (self.number_slices * self.slice_thickness) / 1000
        total_data_in_GB = total_data / (10**9)
        total_duration = (
            total_imaging_time + total_stage_move_time + total_cut_time)

        # Calculate date and time of completion
        now = datetime.datetime.now()
        fraction_completed = self.slice_counter / N
        remaining_time = int(total_duration * (1 - fraction_completed))
        completion_date = now + relativedelta(seconds=remaining_time)
        date_estimate = str(completion_date)[:19].replace(' ', ' at ')

        # Return all estimates, to be displayed in main window GUI
        return (min_dose, max_dose, total_grid_area, total_z, total_data_in_GB,
                total_imaging_time, total_stage_move_time, total_cut_time,
                date_estimate, remaining_time)

    def set_up_acq_subdirectories(self):
        """Set up and mirror all subdirectories for the stack acquisition."""
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
        # Add subdirectories for overviews, grids, tiles
        for ov_index in range(self.ovm.number_ov):
            ov_dir = os.path.join(
                'overviews', 'ov' + str(ov_index).zfill(utils.OV_DIGITS))
            subdirectory_list.append(ov_dir)
        for grid_index in range(self.gm.number_grids):
            grid_dir = os.path.join(
                'tiles', 'g' + str(grid_index).zfill(utils.GRID_DIGITS))
            subdirectory_list.append(grid_dir)
            for tile_index in self.gm[grid_index].active_tiles:
                tile_dir = os.path.join(
                    grid_dir, 't' + str(tile_index).zfill(utils.TILE_DIGITS))
                subdirectory_list.append(tile_dir)
        # Create the directories in the base directory and the mirror drive
        # (if applicable).
        success, exception_str = utils.create_subdirectories(
            self.base_dir, subdirectory_list)
        if not success:
            # Use transmit() here to add a message to the log instead of
            # add_to_main_log() because main log file is not open yet.
            self.main_controls_trigger.transmit(utils.format_log_entry(
                'CTRL: Error while creating subdirectories: ' + exception_str))
            self.pause_acquisition(1)
            self.error_state = 401
        elif self.use_mirror_drive:
            success, exception_str = utils.create_subdirectories(
                self.mirror_drive_dir, subdirectory_list)
            if not success:
                self.main_controls_trigger.transmit(utils.format_log_entry(
                    'CTRL: Error while creating subdirectories on mirror '
                    'drive: ' + exception_str))
                self.pause_acquisition(1)
                self.error_state = 402

    def set_up_acq_logs(self):
        """Create all acquisition log files and copy them to the mirror drive
        if applicable.
        """
        # Get timestamp for this run
        timestamp = str(datetime.datetime.now())[:22].translate(
            {ord(i):None for i in ' :.'})

        try:
            # Note that the config file and the gridmap file are only saved once
            # before starting an acquisition run. The other log files are
            # updated continously during the run.

            # Save current configuration file with timestamp in log folder.
            config_filename = os.path.join(
                self.base_dir, 'meta', 'logs', 'config_' + timestamp + '.txt')
            with open(config_filename, 'w') as f:
                self.cfg.write(f)
            # Save current grid setup
            gridmap_filename = self.gm.save_tile_positions_to_disk(
                self.base_dir, timestamp)
            # Create main log file, in which all entries are saved.
            # No line limit.
            self.main_log_filename = os.path.join(
                self.base_dir, 'meta', 'logs', 'log_' + timestamp + '.txt')
            # recent_log_filename: Log file for most recent entries shown in
            # the GUI (used for e-mail status reports and error reports).
            # Default max. number of lines is 2000. Can be set
            # in cfg['monitoring']['max_log_line_count'].
            self.recent_log_filename = os.path.join(
                self.base_dir, 'meta', 'logs',
                'log_' + timestamp + '_mostrecent.txt')
            # A buffer_size of 1 ensures that all log entries are immediately
            # written to disk
            buffer_size = 1
            self.main_log_file = open(self.main_log_filename, 'w', buffer_size)
            # Set up imagelist file, which contains the paths and file names
            # or all acquired tiles and their positions.
            self.imagelist_filename = os.path.join(
                self.base_dir, 'meta', 'logs',
                'imagelist_' + timestamp + '.txt')
            self.imagelist_file = open(self.imagelist_filename,
                                       'w', buffer_size)
            # Log files for debris notifications and error messages.
            # The error messages are also contained in the main log file.
            self.debris_log_filename = os.path.join(
                self.base_dir, 'meta', 'logs',
                'debris_log_' + timestamp + '.txt')
            self.debris_log_file = open(self.debris_log_filename,
                                        'w', buffer_size)
            self.error_log_filename = os.path.join(
                self.base_dir, 'meta', 'logs',
                'error_log_' + timestamp + '.txt')
            self.error_log_file = open(self.error_log_filename,
                                       'w', buffer_size)
            self.metadata_filename = os.path.join(
                self.base_dir, 'meta', 'logs', 'metadata_' + timestamp + '.txt')
            self.metadata_file = open(self.metadata_filename, 'w', buffer_size)
        except Exception as e:
            self.add_to_main_log(
                'CTRL: Error while setting up log files: ' + str(e))
            self.pause_acquisition(1)
            self.error_state = 401
        else:
            if self.use_mirror_drive:
                # Copy all log files to mirror drive
                self.mirror_files([
                    config_filename,
                    gridmap_filename,
                    self.main_log_filename,
                    self.imagelist_filename,
                    self.debris_log_filename,
                    self.error_log_filename,
                    self.metadata_filename])
                # File handle for imagelist file on mirror drive
                try:
                    self.mirror_imagelist_file = open(os.path.join(
                        self.mirror_drive, self.imagelist_filename[2:]),
                        'w', buffer_size)
                except Exception as e:
                    self.add_to_main_log(
                        'CTRL: Error while opening imagelist file on mirror '
                        'drive: ' + str(e))
                    self.pause_acquisition(1)
                    self.error_state = 402

    def mirror_files(self, file_list):
        """Copy files given in file_list to mirror drive, keep relative path."""
        try:
            for file_name in file_list:
                dst_file_name = os.path.join(self.mirror_drive, file_name[2:])
                shutil.copy(file_name, dst_file_name)
        except Exception as e:
            # Log in viewport window
            log_str = (str(self.slice_counter) + ': WARNING ('
                       + 'Could not mirror file(s))')
            self.error_log_file.write(log_str + ': ' + str(e) + '\n')
            # Signal to main window to update log in viewport tab that shows
            # warnings
            self.add_to_vp_log(log_str)
            sleep(2)
            # Try again
            try:
                for file_name in file_list:
                    dst_file_name = os.path.join(
                        self.mirror_drive, file_name[2:])
                    shutil.copy(file_name, dst_file_name)
            except Exception as e:
                self.add_to_main_log(
                    'CTRL: Copying file(s) to mirror drive failed: ' + str(e))
                self.pause_acquisition(1)
                self.error_state = 402

# ====================== STACK ACQUISITION THREAD run() ========================

    def run(self):
        """Run acquisition in a thread started from main_controls.py."""

        self.reset_error_state()
        self.pause_state = None

        if self.use_mirror_drive:
            self.mirror_drive_dir = os.path.join(
                self.mirror_drive, self.base_dir[2:])

        self.set_up_acq_subdirectories()
        self.set_up_acq_logs()

        # Proceed if no error has occurred during setup of folders and logs
        if self.error_state == 0:
            # autofocus and autostig interval status
            self.autofocus_stig_current_slice = False, False

            # locked focus params
            self.wd_stig_locked = False
            self.mag_locked = False
            self.locked_wd = None
            self.locked_stig_x, self.locked_stig_y = None, None
            self.locked_mag = None

            # Current focus parameters stored as global default settings
            self.wd_default = self.sem.get_wd()
            self.stig_x_default, self.stig_y_default = (
                self.sem.get_stig_xy())

            # Alternating plus/minus deltas for wd and stig, needed for
            # heuristic autofocus, otherwise set to 0
            self.wd_delta, self.stig_x_delta, self.stig_y_delta = 0, 0, 0
            # List of tiles to be processed for heuristic autofocus
            self.heuristic_af_queue = []

            # Variables used for user response from Main Controls
            self.user_reply = None
            self.user_reply_received = False
            self.image_rejected_by_user = False
            self.main_log_file.write('*** SBEMimage log for acquisition '
                                     + self.base_dir + ' ***\n\n')
            if self.acq_paused:
                self.main_log_file.write(
                    '\n*** STACK ACQUISITION RESTARTED ***\n')
                self.add_to_main_log('CTRL: Stack restarted.')
                self.acq_paused = False
            else:
                self.main_log_file.write(
                    '\n*** STACK ACQUISITION STARTED ***\n')
                self.add_to_main_log('CTRL: Stack started.')

            # first_ov[index] is True for each overview image index for which
            # the user will be asked to confirm that the first acquired image
            # is free from debris. After confirmation, first_ov[index] is set
            # to False.
            self.first_ov = [True] * self.ovm.number_ov

            # Track the durations for grabbing, mirroring and inspecting tiles
            self.tile_grab_durations = []
            self.tile_mirror_durations = []
            self.tile_inspect_durations = []

            # Discard previous tile statistics stored in image inspector that is
            # used for tile-by-tile comparisons and quality checks.
            self.img_inspector.reset_tile_stats()

            if self.use_mirror_drive:
                self.add_to_main_log(
                    'CTRL: Mirror drive directory: ' + self.mirror_drive_dir)

            # Save current configuration to disk
            # (send signal to call save_settings() in main_controls.py
            self.main_controls_trigger.transmit('SAVE CFG')
            # Update progress bar and slice counter in Main Controls GUI
            self.main_controls_trigger.transmit('UPDATE PROGRESS')

            # Create metadata summary for this run, write it to disk and send it
            # to remote server (if feature enabled).
            timestamp = int(time())
            grid_list = [str(i).zfill(utils.GRID_DIGITS)
                         for i in range(self.gm.number_grids)]
            session_metadata = {
                'timestamp': timestamp,
                'eht': self.sem.target_eht,
                'beam_current': self.sem.target_beam_current,
                'stig_parameters': (self.stig_x_default, self.stig_y_default),
                'working_distance': self.wd_default,
                'slice_thickness': self.slice_thickness,
                'grids': grid_list,
                'grid_origins': [],
                'pixel_sizes': [],
                'dwell_times': [],
                'contrast': self.sem.bsd_contrast,
                'brightness': self.sem.bsd_brightness,
                'email_addresses: ': self.notifications.user_email_addresses
                }
            self.metadata_file.write('SESSION: ' + str(session_metadata) + '\n')
            # Send to server?
            if self.send_metadata:
                status, exc_str = self.notifications.send_session_metadata(
                    self.metadata_project_name, self.stack_name,
                    session_metadata)
                if status == 100:
                    self.error_state = 508
                    self.pause_acquisition(1)
                    self.add_to_main_log('CTRL: Error sending session metadata '
                                         'to server. ' + exc_str)
                elif status == 200:
                    self.add_to_main_log(
                        'CTRL: Session data sent. Metadata server active.')

            # Set SEM to target parameters.
            # EHT is assumed to be on at this point
            # (PreStackDlg checks if EHT is on when user wants to start the acq.)
            self.sem.apply_beam_settings()
            self.sem.set_beam_blanking(1)
            sleep(1)

            # Initialize focus parameters for all grids, but only for those tiles
            # that have not yet been initialized (there may be focus settings
            # from previous runs!)
            for grid_index in range(self.gm.number_grids):
                if not self.gm[grid_index].use_wd_gradient:
                    self.gm[grid_index].set_wd_stig_xy_for_uninitialized_tiles(
                        self.wd_default, [self.stig_x_default, self.stig_y_default])
                else:
                    # Set stig values for each tile if focus gradient used, but
                    # don't change working distance because wd is calculated
                    # with gradient parameters.
                    self.gm[grid_index].set_stig_xy_for_all_tiles(
                        [self.stig_x_default, self.stig_y_default])

            # A setting of [0, 0, 0] for overview images means that the overviews
            # will be acquired with the current focus parameters.
            # If wd != 0, ovm[ov_index].wd_stig_xy will be used for the overview
            # at ov_index.
            for ov_index in range(self.ovm.number_ov):
                self.ovm[ov_index].wd_stig_xy = [0, 0, 0]

            # Show current focus/stig settings
            self.show_wd_stig_in_log(self.wd_default,
                                     self.stig_x_default,
                                     self.stig_y_default)

            # Make sure DM script uses the correct motor speeds
            # (This information is lost when script crashes.)
            if self.microtome is not None:
                success = self.stage.update_motor_speed()
                if not success:
                    self.error_state = 101
                    self.pause_acquisition(1)
                    self.add_to_main_log('STAGE: ERROR: Could not update '
                                         'XY motor speeds.')

            # Get current Z position of microtome/stage
            self.stage_z_position = self.stage.get_z()
            if self.stage_z_position is None or self.stage_z_position < 0:
                # Try again
                self.stage_z_position = self.stage.get_z()
                if self.stage_z_position is None or self.stage_z_position < 0:
                    self.error_state = 104
                    self.stage.reset_error_state()
                    self.pause_acquisition(1)
                    self.add_to_main_log(
                        'STAGE: Error reading initial Z position.')
            # Check for Z mismatch
            if self.microtome is not None and self.microtome.error_state == 206:
                self.microtome.reset_error_state()
                self.error_state = 206
                self.pause_acquisition(1)
                # Show warning dialog in Main Controls GUI
                self.main_controls_trigger.transmit('Z WARNING')

            # Show current stage position (Z and XY) in Main Controls GUI
            self.main_controls_trigger.transmit('UPDATE Z')
            self.stage.get_xy()  # calling stage.get_xy() updates last_known_xy
            self.main_controls_trigger.transmit('UPDATE XY')

        # ========================= ACQUISITION LOOP ===========================
        while not (self.acq_paused or self.stack_completed):
            # Add line with stars in log file as a visual clue when a new
            # slice begins; also add current slice counter and Z position.
            self.add_to_main_log(
                'CTRL: ****************************************')
            self.add_to_main_log('CTRL: slice ' + str(self.slice_counter)
                + ', Z:' + '{0:6.3f}'.format(self.stage_z_position))

            # Use (SmartSEM) autofocus/autostig on this slice depending on
            # whether MagC mode is active, and on the slice number and
            # current autofocus settings.
            if self.magc_mode:
                self.autofocus_stig_current_slice = (True, True)
            else:
                self.autofocus_stig_current_slice = (
                    self.autofocus.current_slice_active(self.slice_counter))

            # For heuristic autofocus (method 1), set the deltas for this slice
            # to focus slightly up (for even slice counter) or down (odd slice
            # counter).
            if self.use_autofocus and self.autofocus.method == 1:
                sign = 1 if self.slice_counter % 2 else -1
                self.wd_delta = sign * self.autofocus.wd_delta
                self.stig_x_delta = sign * self.autofocus.stig_x_delta
                self.stig_y_delta = sign * self.autofocus.stig_y_delta
                self.add_to_main_log('CTRL: Heuristic autofocus active.')
                self.add_to_main_log(
                    'CTRL: DIFF_WD: {0:+.4f}'.format(self.wd_delta * 1000)
                    + ', DIFF_STIG_X: {0:+.2f}'.format(self.stig_x_delta)
                    + ', DIFF_STIG_Y: {0:+.2f}'.format(self.stig_x_delta))

            if self.take_overviews:
                self.acquire_all_overviews()

            if (self.acq_interrupted
                    and self.acq_interrupted_at[0] >= self.gm.number_grids):
                # Grid in which interruption occured has been deleted.
                self.acq_interrupted = False
                self.interrupted_at = []
                self.tiles_acquired = []

            self.acquire_all_grids()

            # Reset interruption info if affected grid acquired
            if (self.pause_state != 1
                    and self.acq_interrupted
                    and self.acq_interrupted_at[0] in self.grids_acquired):
                self.interrupted_at = []
                self.acq_interrupted = False

            if not self.acq_interrupted:
                self.grids_acquired = []

            # Save screenshot of current viewport canvas
            self.vp_screenshot_filename = os.path.join(
                self.base_dir, 'workspace', 'viewport',
                self.stack_name + '_viewport_' + 's'
                + str(self.slice_counter).zfill(utils.SLICE_DIGITS) + '.png')
            self.main_controls_trigger.transmit('GRAB VP SCREENSHOT'
                                                + self.vp_screenshot_filename)
            # Allow enough time to grab and save viewport screenshot
            time_out = 0
            while (not os.path.isfile(self.vp_screenshot_filename)
                   and time_out < 20):
                sleep(0.1)
                time_out += 1

            # ======== E-mail monitoring / Signal from metadata server =========
            report_scheduled = (
                self.slice_counter % self.status_report_interval == 0)

            # If remote commands are enabled, check email account
            if (self.use_email_monitoring
                    and self.notifications.remote_commands_enabled
                    and self.slice_counter % self.remote_check_interval == 0):
                self.add_to_main_log('CTRL: Checking for remote commands.')
                self.process_remote_commands()

            # Send status report if scheduled or requested by remote command
            if (self.use_email_monitoring
                    and (self.slice_counter > 0)
                    and (report_scheduled or self.report_requested)):
                msg1, msg2 = self.notifications.send_status_report(
                    self.base_dir, self.stack_name, self.slice_counter,
                    self.recent_log_filename, self.debris_log_filename,
                    self.error_log_filename, self.vp_screenshot_filename)
                self.add_to_main_log(msg1)
                if msg2:
                    self.add_to_main_log(msg2)
                self.report_requested = False

            if self.send_metadata:
                # Get commands or messages from metadata server
                status, command, msg, exc_str = (
                    self.notifications.read_server_message(
                        self.metadata_project_name, self.stack_name))
                if status == 100:
                    self.error_state = 508
                    self.pause_acquisition(1)
                    self.add_to_main_log('CTRL: Error during get request '
                                         'to server. ' + exc_str)
                elif status == 200:
                    if command in ['STOP', 'PAUSE']:
                        self.pause_acquisition(1)
                        self.add_to_main_log(
                            'CTRL: Stop signal from metadata server received.')
                        if self.use_email_monitoring:
                            # Send notification email
                            msg_subject = ('Stack ' + self.stack_name
                                           + ' PAUSED remotely')
                            success, error_msg = self.notifications.send_email(
                                msg_subject,
                                'Pause command received from metadata server.')
                        if success:
                            self.add_to_main_log(
                                'CTRL: Notification e-mail sent.')
                        else:
                            self.add_to_main_log(
                                'CTRL: ERROR sending notification email: '
                                + error_msg)
                        self.main_controls_trigger.transmit('REMOTE STOP')
                    if command == 'SHOWMESSAGE':
                        # Show message received from metadata server in GUI
                        self.main_controls_trigger.transmit('SHOW MSG' + msg)
                else:
                    self.add_to_main_log(
                        'CTRL: Unknown signal from metadata server received.')

            # Check if single slice acquisition -> NO CUT
            if self.number_slices == 0:
                self.pause_acquisition(1)

            # =========================== CUTTING ==============================
            if (self.pause_state != 1) and (self.error_state == 0):
                if self.microtome is not None:
                    self.do_cut()
                if self.error_state == 0:
                    # Reset interruption status
                    self.acq_interrupted = False
                    self.acq_interrupted_at = []
                    self.tiles_acquired = []
                    self.grids_acquired = []
                    # Confirm slice completion
                    self.confirm_slice_complete()

            # Imaging and cutting for current slice completed.
            # Save current configuration to disk, update progress in GUI,
            # and check if stack is completed.
            self.main_controls_trigger.transmit('SAVE CFG')
            self.main_controls_trigger.transmit('UPDATE PROGRESS')
            if self.slice_counter == self.number_slices:
                self.stack_completed = True

            # Copy log file to mirror disk
            # (Error handling in self.mirror_files())
            if self.use_mirror_drive:
                self.mirror_files([self.main_log_filename])
            sleep(0.1)

        # ===================== END OF ACQUISITION LOOP ========================

        if self.use_autofocus:
            for grid_index in range(self.gm.number_grids):
                self.do_autofocus_adjustments(grid_index)
            self.main_controls_trigger.transmit('DRAW VP')
            if self.autofocus.method == 1:
                self.wd_delta, self.stig_x_delta, self.stig_y_delta = 0, 0, 0
                self.set_grid_wd_stig()

        if self.error_state > 0:
            self.process_error_state()

        if self.stack_completed and not (self.number_slices == 0):
            self.add_to_main_log('CTRL: Stack completed.')
            self.main_controls_trigger.transmit('COMPLETION STOP')
            if self.use_email_monitoring:
                # Send notification email
                msg_subject = 'Stack ' + self.stack_name + ' COMPLETED.'
                success, error_msg = self.notifications.send_email(
                    msg_subject, '')
                if success:
                    self.add_to_main_log('CTRL: Notification e-mail sent.')
                else:
                    self.add_to_main_log(
                        'CTRL: ERROR sending notification email: ' + error_msg)
            if self.eht_off_after_stack:
                self.sem.turn_eht_off()
                self.add_to_main_log(
                    'SEM: EHT turned off after stack completion.')

        if self.acq_paused:
            self.add_to_main_log('CTRL: Stack paused.')

        # Update acquisition status in Main Controls GUI
        self.main_controls_trigger.transmit('ACQ NOT IN PROGRESS')

        # Add last entry to main log
        self.main_log_file.write('*** END OF LOG ***\n')

        # Copy log files to mirror drive. Error handling in self.mirror_files()
        if self.use_mirror_drive:
            self.mirror_files([self.main_log_filename,
                               self.debris_log_filename,
                               self.error_log_filename,
                               self.metadata_filename])
        # Close all log files
        if self.main_log_file is not None:
            self.main_log_file.close()
        if self.imagelist_file is not None:
            self.imagelist_file.close()
        if self.use_mirror_drive and self.mirror_imagelist_file is not None:
            self.mirror_imagelist_file.close()
        if self.debris_log_file is not None:
            self.debris_log_file.close()
        if self.error_log_file is not None:
            self.error_log_file.close()
        if self.metadata_file is not None:
            self.metadata_file.close()

    # ================ END OF STACK ACQUISITION THREAD run() ===================

    def process_remote_commands(self):
        command = self.notifications.get_remote_command()
        if command in ['stop', 'pause']:
            self.notifications.send_email('Command received', '')
            self.pause_acquisition(2)
            success, error_msg = self.notifications.send_email(
                'Remote stop', 'The acquisition was paused remotely.')
            if not success:
                self.add_to_main_log('CTRL: Error sending confirmation email: '
                                     + error_msg)
            # Signal to Main Controls that acquisition paused remotely.
            self.main_controls_trigger.transmit('REMOTE STOP')
        elif command in ['continue', 'start', 'restart']:
            pass
            # TODO: let user continue paused acq with remote command
        elif command == 'report':
            self.add_to_main_log('CTRL: REPORT remote command received.')
            self.notifications.send_email('Command received', '')
            self.report_requested = True
        elif command == 'ERROR':
            self.add_to_main_log('CTRL: ERROR checking for remote commands.')

    def process_error_state(self):
        """Add information about the error to the main log, send a
        notification email, and pause the stack.
        """
        error_str = utils.ERROR_LIST[self.error_state]
        self.add_to_main_log('CTRL: ' + error_str)
        viewport_log_str = (
            str(self.slice_counter) + ': ERROR (' + error_str + ')')
        self.error_log_file.write(viewport_log_str + '\n')
        # Signal to main window to update error log in viewport
        self.main_controls_trigger.transmit('VP LOG' + viewport_log_str)
        # Send notification e-mail
        if self.use_email_monitoring:
            status_msg1, status_msg2 = self.notifications.send_error_report(
                self.stack_name, self.slice_counter, self.error_state,
                self.recent_log_filename, self.vp_screenshot_filename)
            self.add_to_main_log(status_msg1)
            if status_msg2:
                self.add_to_main_log(status_msg2)
        # Send signal to Main Controls that there was an error.
        self.main_controls_trigger.transmit('ERROR PAUSE')

    def do_cut(self):
        """Carry out a single cut. This function is called when the microtome
        is active and skipped if the SEM stage is active.
        """
        old_stage_z_position = self.stage_z_position
        # Move to new Z position. stage_z_position saves Z position in microns.
        # slice_thickness is provided in nanometres!
        self.stage_z_position = (self.stage_z_position
                                 + (self.slice_thickness / 1000))
        self.add_to_main_log('STAGE: Move to new Z: ' + '{0:.3f}'.format(
            self.stage_z_position))
        self.microtome.move_stage_to_z(self.stage_z_position)
        # Show new Z position in Main Controls GUI
        self.main_controls_trigger.transmit('UPDATE Z')
        # Check if there were microtome problems
        self.error_state = self.microtome.error_state
        if self.error_state in [103, 202]:
            self.add_to_main_log(
                'STAGE: Problem during Z move. Trying again.')
            self.error_state = 0
            self.microtome.reset_error_state()
            # Try again after three-second delay
            sleep(3)
            self.microtome.move_stage_to_z(self.stage_z_position)
            self.main_controls_trigger.transmit('UPDATE Z')
            # Read new error_state
            self.error_state = self.microtome.error_state

        if self.error_state == 0:
            self.add_to_main_log('KNIFE: Cutting in progress ('
                                 + str(self.slice_thickness)
                                 + ' nm cutting thickness).')
            # Do the full cut cycle (near, cut, retract, clear)
            self.microtome.do_full_cut()
            # Process tiles for heuristic autofocus during cut
            if self.heuristic_af_queue:
                self.process_heuristic_af_queue()
                # Apply all corrections to tiles
                self.add_to_main_log('CTRL: Applying corrections to WD/STIG.')
                self.autofocus.apply_heuristic_tile_corrections()
            else:
                sleep(self.microtome.full_cut_duration)
            duration_exceeded = self.microtome.check_for_cut_cycle_error()
            if duration_exceeded:
                self.add_to_main_log(
                    'KNIFE: Warning: Cut cycle took longer than specified.')
            self.error_state = self.microtome.error_state
            self.microtome.reset_error_state()
        if self.error_state > 0:
            self.add_to_main_log('STAGE: Z move failed.')
            # Try to move back to previous Z position
            self.add_to_main_log('STAGE: Attempt to move back to old Z: '
                                 + '{0:.3f}'.format(old_stage_z_position))
            self.microtome.move_stage_to_z(old_stage_z_position)
            self.main_controls_trigger.transmit('UPDATE Z')
            self.microtome.reset_error_state()
            self.pause_acquisition(1)
        else:
            self.add_to_main_log('KNIFE: Cut completed.')
            self.slice_counter += 1
            self.total_z_diff += self.slice_thickness/1000
        sleep(1)

    def confirm_slice_complete(self):
        """Confirm that the current slice is completely acquired without error
        and that the surface was cut. Write entry to metadata file and send
        notification to metadata server.
        """
        timestamp = int(time())
        slice_complete_metadata = {
            'timestamp': timestamp,
            'completed_slice': self.slice_counter}
        self.metadata_file.write('SLICE COMPLETE: '
                                  + str(slice_complete_metadata) + '\n')

        if self.send_metadata:
            # Notify remote server that slice has been imaged
            status, exc_str = self.notifications.send_slice_completed(
                self.metadata_project_name, self.stack_name,
                slice_complete_metadata)
            if status == 100:
                self.error_state = 508
                self.pause_acquisition(1)
                self.add_to_main_log('CTRL: Error sending "slice complete" '
                                     'signal to server. ' + exc_str)

    def process_heuristic_af_queue(self):
        """Process tiles for heuristic autofocus while cut cycle is carried out.
        If processing takes less time than the cutting cycle, this method will
        wait the extra time.
        """
        start_time = datetime.datetime.now()
        for tile_key in self.heuristic_af_queue:
            self.do_heuristic_autofocus(tile_key)
            current_time = datetime.datetime.now()
            time_elapsed = current_time - start_time
        self.heuristic_af_queue = []
        remaining_cutting_time = (
            self.microtome.full_cut_duration - time_elapsed.total_seconds())
        if remaining_cutting_time > 0:
            sleep(remaining_cutting_time)

    def acquire_all_overviews(self):
        """Acquire all overview images with image inspection, debris detection,
        and error handling.
        """
        for ov_index in range(self.ovm.number_ov):
            if (self.error_state > 0) or (self.pause_state == 1):
                break
            if not self.ovm[ov_index].active:
                self.add_to_main_log(
                    f'CTRL: OV {ov_index} inactive, skipped.')
                continue
            if self.ovm[ov_index].slice_active(self.slice_counter):
                ov_accepted = False
                sweep_limit = False
                sweep_counter = 0
                fail_counter = 0
                # ==================== OV acquisition loop =====================
                while (not ov_accepted
                       and not sweep_limit
                       and not self.pause_state == 1
                       and fail_counter < 3):

                    ov_filename, ov_accepted = (
                        self.acquire_overview(ov_index))

                    if (self.error_state in [303, 404]
                        and not self.image_rejected_by_user):
                        # Image incomplete or cannot be loaded, try again
                        fail_counter += 1
                        if fail_counter < 3:
                            self.add_to_main_log(
                                'CTRL: OV problem detected. Trying again.')
                        self.img_inspector.discard_last_ov(ov_index)
                        sleep(1)
                        if fail_counter == 3:
                            self.pause_acquisition(1)
                        else:
                            self.error_state = 0
                    elif self.error_state > 0:
                        break
                    elif (not ov_accepted
                          and not self.pause_state == 1
                          and (self.use_debris_detection
                          or self.first_ov[ov_index])):
                        # Save image with debris
                        self.save_debris_image(ov_filename, ov_index,
                                               sweep_counter)
                        self.img_inspector.discard_last_ov(ov_index)
                        # Try to remove debris
                        if (sweep_counter < self.max_number_sweeps):
                            self.remove_debris()
                            sweep_counter += 1
                        elif sweep_counter == self.max_number_sweeps:
                            sweep_limit = True
                # ================== OV acquisition loop end ===================

                cycle_time_diff = (
                    self.sem.additional_cycle_time - self.sem.DEFAULT_DELAY)
                if cycle_time_diff > 0.15:
                    self.add_to_main_log(
                        f'CTRL: Warning: OV {ov_index} cycle time was '
                        f'{cycle_time_diff:.2f} s longer than '
                        f'expected.')

                if (not ov_accepted
                    and self.error_state == 0
                    and not self.pause_state == 1):
                    if not self.continue_after_max_sweeps:
                        # Pause if maximum number of sweeps are reached
                        self.pause_acquisition(1)
                        self.error_state = 501
                        self.add_to_main_log(
                            'CTRL: Max. number of sweeps reached.')
                    else:
                        # If user has set continue_after_max_sweeps to True
                        # continue acquisition, but let user know.
                        ov_accepted = True
                        self.add_to_main_log(
                            'CTRL: Max. number of sweeps reached, '
                            'but continuing as specified.')

                self.first_ov[ov_index] = False

                if ov_accepted:
                    # Write stats and reslice to disk
                    success, error_msg = (
                        self.img_inspector.save_ov_stats(
                            self.base_dir, ov_index,
                            self.slice_counter))
                    if not success:
                        self.add_to_main_log(
                            'CTRL: Error saving OV mean/SD to disk.')
                        self.add_to_main_log('CTRL: ' + error_msg)
                    success, error_msg = (
                        self.img_inspector.save_ov_reslice(
                            self.base_dir, ov_index))
                    if not success:
                        self.add_to_main_log(
                            'CTRL: Error saving OV reslice to disk.')
                        self.add_to_main_log('CTRL: ' + error_msg)
                    # Mirror the acquired overview
                    if self.use_mirror_drive:
                        self.mirror_files([ov_filename])
                if sweep_counter > 0:
                    log_str = (str(self.slice_counter)
                               + ': Debris, ' + str(sweep_counter)
                               + ' sweep(s)')
                    self.debris_log_file.write(log_str + '\n')
                    self.add_to_vp_log(log_str)
            else:
                self.add_to_main_log(
                    'CTRL: Skip OV %d (intervallic acquisition)' % ov_index)

    def acquire_overview(self, ov_index, move_required=True):
        """Acquire an overview image with error handling and image inspection"""
        move_success = True
        ov_save_path = None
        ov_accepted = False

        ov_stage_position = self.ovm[ov_index].centre_sx_sy
        # Move to OV stage coordinates if required (this method can be called
        # with move_required=False if the stage is already at the OV position.)
        if move_required:
            self.add_to_main_log(
                'STAGE: Moving to OV %d position.' % ov_index)
            self.stage.move_to_xy(ov_stage_position)
            if self.stage.error_state > 0:
                self.stage.reset_error_state()
                # Update error log in viewport window with warning message:
                log_str = (str(self.slice_counter) + ': WARNING ('
                           + 'Move to OV%d position failed)' % ov_index)
                self.error_log_file.write(log_str + '\n')
                self.add_to_vp_log(log_str)
                # Try again
                sleep(2)
                self.stage.move_to_xy(ov_stage_position)
                self.error_state = self.stage.error_state
                if self.error_state > 0:
                    self.add_to_main_log(
                        'STAGE: Failed to move to OV position.')
                    self.pause_acquisition(1)
                    self.stage.reset_error_state()
                    move_success = False
                else:
                    # Show new stage coordinates in GUI
                    self.main_controls_trigger.transmit('UPDATE XY')
        if move_success:
            self.add_to_main_log(
                'SEM: Acquiring OV at X:'
                + '{0:.3f}'.format(ov_stage_position[0])
                + ', Y:' + '{0:.3f}'.format(ov_stage_position[1]))
            # Set specified OV frame settings
            self.sem.apply_frame_settings(
                self.ovm[ov_index].frame_size_selector,
                self.ovm[ov_index].pixel_size,
                self.ovm[ov_index].dwell_time)
            ov_wd = self.ovm[ov_index].wd_stig_xy[0]
            # Use specified OV focus parameters if available
            # (if wd == 0 use defaults)
            if ov_wd > 0:
                self.sem.set_wd(ov_wd)
                self.sem.set_stig_xy(self.ovm[ov_index].wd_stig_xy[1],
                                     self.ovm[ov_index].wd_stig_xy[2])
                self.add_to_main_log(
                    'SEM: Using user-specified WD: '
                    '{0:.6f}'.format(ov_wd * 1000))
                # TODO: Also show formatted stig_xy in log.

            # Path and filename of overview image to be acquired
            ov_save_path = utils.ov_save_path(
                self.base_dir, self.stack_name, ov_index, self.slice_counter)
            # Indicate the overview being acquired in the viewport
            self.main_controls_trigger.transmit('ACQ IND OV' + str(ov_index))
            # Acquire the image
            self.sem.acquire_frame(ov_save_path)
            # Remove indicator colour
            self.main_controls_trigger.transmit('ACQ IND OV' + str(ov_index))

            # Check if OV image file exists and show image in Viewport
            if os.path.isfile(ov_save_path):

                # Inspect the acquired image
                (ov_img, mean, stddev,
                 range_test_passed,
                 load_error, load_exception, grab_incomplete) = (
                    self.img_inspector.process_ov(ov_save_path,
                                                  ov_index,
                                                  self.slice_counter))
                # Show OV in viewport and display mean and stddev
                # if no load error
                if not load_error:
                    self.add_to_main_log(
                        'CTRL: OV: M:'
                        + '{0:.2f}'.format(mean)
                        + ', SD:' + '{0:.2f}'.format(stddev))
                    # Save the acquired image in the workspace folder
                    workspace_save_path = os.path.join(
                        self.base_dir, 'workspace',
                        'OV' + str(ov_index).zfill(3) + '.bmp')
                    imwrite(workspace_save_path, ov_img)
                    # Update the vp_file_path in the overview manager,
                    # thereby loading the overview as a QPixmap for display
                    # in the Viewport.
                    self.ovm[ov_index].vp_file_path = workspace_save_path
                    # Signal to update viewport
                    self.main_controls_trigger.transmit('DRAW VP')
                if load_error:
                    self.error_state = 404
                    ov_accepted = False
                    # Don't pause yet, try again in OV acquisition loop.
                elif grab_incomplete:
                    self.error_state = 303
                    ov_accepted = False
                    # Don't pause yet, try again in OV acquisition loop.
                elif (self.monitor_images and not range_test_passed):
                    ov_accepted = False
                    self.error_state = 502    # OV image error
                    self.pause_acquisition(1)
                    self.add_to_main_log(
                        'CTRL: OV outside of mean/stddev limits. ')
                else:
                    # OV has passed all tests, but now check for debris
                    ov_accepted = True
                    if self.first_ov[ov_index]:
                        self.main_controls_trigger.transmit(
                            'ASK DEBRIS FIRST OV' + str(ov_index))
                        # The command above causes a message box to be displayed
                        # in Main Controls. The user is asked if debris can be
                        # seen in the first overview image acquired.
                        # Variables user_reply_received and user_reply are
                        # updated when a response is received.
                        while not self.user_reply_received:
                            sleep(0.1)
                        ov_accepted = (self.user_reply == QMessageBox.Yes)
                        if self.user_reply == QMessageBox.Abort:
                            self.pause_acquisition(1)
                        self.user_reply_received = False

                    elif self.use_debris_detection:
                        # Detect potential debris
                        debris_detected, msg = self.img_inspector.detect_debris(
                            ov_index)
                        self.add_to_main_log(msg)
                        if debris_detected:
                            ov_accepted = False
                            # If 'Ask User' mode is active, ask user to
                            # confirm that debris was detected correctly.
                            if self.ask_user_mode:
                                self.main_controls_trigger.transmit(
                                    'ASK DEBRIS CONFIRMATION' + str(ov_index))
                                while not self.user_reply_received:
                                    sleep(0.1)
                                # The OV is accepted if the user replies 'No'
                                # to the question in the message box.
                                ov_accepted = (
                                    self.user_reply == QMessageBox.No)
                                if self.user_reply == QMessageBox.Abort:
                                    self.pause_acquisition(1)
                                self.user_reply_received = False
            else:
                self.add_to_main_log('SEM: OV acquisition failure.')
                self.error_state = 302
                self.pause_acquisition(1)
                ov_accepted = False

        # Check for "Ask User" override
        if (self.ask_user_mode and self.error_state in [303, 502]):
            self.main_controls_trigger.transmit(
                'ASK IMAGE ERROR OVERRIDE')
            while not self.user_reply_received:
                sleep(0.1)
            if self.user_reply == QMessageBox.Yes:
                # Proceed anyway, reset error state and accept OV
                self.reset_error_state()
                ov_accepted = True
            else:
                self.image_rejected_by_user = True
            self.user_reply_received = False

        return ov_save_path, ov_accepted

    def remove_debris(self):
        """Try to remove detected debris by sweeping the surface. Microtome must
        be active for this function.
        """
        self.add_to_main_log('KNIFE: Sweeping to remove debris.')
        self.microtome.do_sweep(self.stage_z_position)
        if self.microtome.error_state > 0:
            self.microtome.reset_error_state()
            self.add_to_main_log('KNIFE: Problem during sweep. Trying again.')
            # Add warning to log in Viewport
            log_str = (str(self.slice_counter)
                       + ': WARNING (' + 'Problem during sweep)')
            self.error_log_file.write(log_str + '\n')
            self.add_to_vp_log(log_str)
            # Trying again after 3 sec
            sleep(3)
            self.microtome.do_sweep(self.stage_z_position)
            # Check if there was again an error during sweeping
            if self.microtome.error_state > 0:
                self.microtome.reset_error_state()
                self.error_state = 205
                self.pause_acquisition(1)
                self.add_to_main_log(
                    'KNIFE: Error during second sweep attempt.')

    def save_debris_image(self, ov_file_name, ov_index, sweep_counter):
        debris_save_path = utils.ov_debris_save_path(
            self.base_dir, self.stack_name, ov_index, self.slice_counter,
            sweep_counter)
        # Copy current ov_file to folder 'debris'
        try:
            shutil.copy(ov_file_name, debris_save_path)
        except Exception as e:
            self.add_to_main_log(
                'CTRL: Warning: Unable to save rejected OV image, ' + str(e))
        if self.use_mirror_drive:
            self.mirror_files([debris_save_path])

    def acquire_all_grids(self):
        """Acquire all grids that are active, with error handling."""
        for grid_index in range(self.gm.number_grids):
            if self.error_state > 0 or self.pause_state == 1:
                break
            if not self.gm[grid_index].active:
                self.add_to_main_log(
                    f'CTRL: Grid {grid_index} inactive, skipped.')
                continue
            if self.gm[grid_index].slice_active(self.slice_counter):
                num_active_tiles = self.gm[grid_index].number_active_tiles()
                self.add_to_main_log('CTRL: Grid ' + str(grid_index)
                                     + ', number of active tiles: '
                                     + str(num_active_tiles))

                # In MagC mode, use the grid index for autostig delay
                if self.magc_mode:
                    self.autofocus_stig_current_slice = (
                        self.autofocus_stig_current_slice[0],
                        (grid_index % self.autofocus.autostig_delay == 0))

                if (num_active_tiles > 0
                        and not (self.pause_state == 1)
                        and (self.error_state == 0)):
                    if grid_index in self.grids_acquired:
                        self.add_to_main_log(
                            f'CTRL: Grid {grid_index} already acquired. '
                            f'Skipping.')
                    elif (self.magc_mode
                          and grid_index not in self.gm.magc_checked_sections):
                        self.add_to_main_log(
                            f'CTRL: Grid {grid_index} not checked. Skipping.')
                    else:
                        if (self.use_autofocus
                                and self.autofocus.method == 0
                                and (self.autofocus_stig_current_slice[0]
                                or self.autofocus_stig_current_slice[1])):
                            self.do_autofocus_before_grid_acq(grid_index)
                        self.do_autofocus_adjustments(grid_index)
                        self.acquire_grid(grid_index)
            else:
                self.add_to_main_log(
                    'CTRL: Skip grid %d (intervallic acquisition)' % grid_index)

    def acquire_grid(self, grid_index):
        """Acquire all active tiles of grid specified by grid_index"""

        # Get current active tiles (using list() to get a copy).
        # If the user changes the active tiles in this grid while the grid
        # is being acquired, the changes will take effect the next time
        # the grid is acquired.
        active_tiles = list(self.gm[grid_index].active_tiles)

        # Focus parameters must be adjusted for each tile individually if focus
        # gradient is activ or if autofocus is used with "track all" or
        # "best fit" option.
        # Otherwise self.wd_default, self.stig_x_default,
        # and self.stig_y_default are used.
        adjust_wd_stig_for_each_tile = (
            self.gm[grid_index].use_wd_gradient
            or (self.use_autofocus and self.autofocus.tracking_mode < 2))

        if self.pause_state != 1:
            self.add_to_main_log(
                'CTRL: Starting acquisition of active tiles in grid %d'
                % grid_index)

            if self.magc_mode:
                # In MagC mode: Track grid being acquired in Viewport
                grid_centre_d = self.gm[grid_index].centre_dx_dy
                self.cs.set_vp_centre_d(grid_centre_d)
                self.main_controls_trigger.transmit('DRAW VP')
                self.main_controls_trigger.transmit('SET SECTION STATE GUI-'
                    + str(grid_index)
                    + '-acquiring')

            # Switch to specified acquition settings of the current grid.
            self.sem.apply_frame_settings(
                self.gm[grid_index].frame_size_selector,
                self.gm[grid_index].pixel_size,
                self.gm[grid_index].dwell_time)

            # Delay necessary for Gemini? (change of mag)
            sleep(0.2)
            # Lock magnification: If user accidentally changes the mag during
            # the grid acquisition, SBEMimage will detect and undo the change.
            self.lock_mag()

            if self.acq_interrupted:
                # Remove tiles that are no longer active from
                # tiles_acquired list
                acq_tmp = list(self.tiles_acquired)
                for tile in acq_tmp:
                    if not (tile in active_tiles):
                        self.tiles_acquired.remove(tile)

            tile_width, tile_height = self.gm[grid_index].frame_size

            # Set WD and stig settings for the current grid
            # and lock the settings
            if not adjust_wd_stig_for_each_tile:
                # magc: WD/stig is kept to the current values from grid to grid
                if not self.magc_mode:
                    self.set_grid_wd_stig()
                self.lock_wd_stig()

            theta = self.gm[grid_index].rotation
            # TODO: Whether theta or (360 - theta) must be used here may be
            # device-specific. Look into that!
            if not self.magc_mode:
                theta = 360 - theta
            if theta > 0:
                # Enable scan rotation
                self.sem.set_scan_rotation(theta)

            # ============= Acquisition loop of all active tiles ===============
            for tile_index in active_tiles:
                fail_counter = 0
                tile_accepted = False
                tile_id = str(grid_index) + '.' + str(tile_index)
                # Individual WD/stig adjustment for tile, if necessary
                if adjust_wd_stig_for_each_tile and not self.magc_mode:
                    new_wd = self.gm[grid_index][tile_index].wd
                    new_stig_xy = self.gm[grid_index][tile_index].stig_xy
                    self.sem.set_wd(new_wd)
                    self.sem.set_stig_xy(*new_stig_xy)
                    self.show_wd_stig_in_log(
                        new_wd, new_stig_xy[0], new_stig_xy[1])
                # Acquire the current tile
                while not tile_accepted and fail_counter < 2:
                    (tile_img, relative_save_path, save_path,
                     tile_accepted, tile_skipped, tile_selected) = (
                        self.acquire_tile(grid_index, tile_index))

                    if (self.error_state in [302, 303, 304, 404]
                            and not self.image_rejected_by_user) :
                        self.save_rejected_tile(save_path, grid_index,
                                                tile_index, fail_counter)
                        # Try again
                        fail_counter += 1
                        if fail_counter == 2:
                            # Pause after second failed attempt
                            self.pause_acquisition(1)
                        else:
                            # Remove the file to avoid overwrite error
                            try:
                                os.remove(save_path)
                            except Exception as e:
                                self.add_to_main_log(
                                    'CTRL: Tile image file could not be '
                                    'removed: ' + str(e))
                            # TODO: Try to solve frozen frame problem:
                            # if self.error_state == 304:
                            #    self.handle_frozen_frame(grid_index)
                            self.add_to_main_log(
                                'SEM: Trying again to image tile.')
                            # Reset error state
                            self.error_state = 0
                    elif self.error_state > 0:
                        self.pause_acquisition(1)
                        break
                # End of tile aquisition while loop

                if tile_accepted and tile_selected and not tile_skipped:
                    # Write tile's name and position into imagelist
                    self.register_accepted_tile(relative_save_path,
                                                grid_index, tile_index,
                                                tile_width, tile_height)
                    # Save stats and reslice
                    success, error_msg = self.img_inspector.save_tile_stats(
                        self.base_dir, grid_index, tile_index,
                        self.slice_counter)
                    if not success:
                        self.add_to_main_log(
                            'CTRL: Error saving tile mean and SD to disk.')
                        self.add_to_main_log(
                            'CTRL: ' + error_msg)
                    success, error_msg = self.img_inspector.save_tile_reslice(
                        self.base_dir, grid_index, tile_index)
                    if not success:
                        self.add_to_main_log(
                            'CTRL: Error saving tile reslice to disk.')
                        self.add_to_main_log(
                            'CTRL: ' + error_msg)

                    # If heuristic autofocus is enabled and tile is selected as
                    # a reference tile, prepare tile for processing:
                    if (self.use_autofocus and self.autofocus.method == 1
                        and self.gm[grid_index][tile_index].autofocus_active):
                        tile_key = str(grid_index) + '.' + str(tile_index)
                        self.autofocus.crop_tile_for_heuristic_af(
                            tile_img, tile_key)
                        self.heuristic_af_queue.append(tile_key)
                        del tile_img

                elif (not tile_selected
                      and not tile_skipped
                      and self.error_state == 0):
                    self.add_to_main_log(
                        f'CTRL: Tile {tile_id} was discarded by image '
                        f'inspector.')
                    # Delete file
                    try:
                        os.remove(save_path)
                    except Exception as e:
                        self.add_to_main_log(
                            'CTRL: Tile image file could not be deleted: '
                            + str(e))
                # Save current position if acquisition was paused by user
                # or interrupted by an error.
                if self.pause_state == 1:
                    self.save_interruption_point(grid_index, tile_index)
                    break
            # ================= End of tile acquisition loop ===================

            cycle_time_diff = (self.sem.additional_cycle_time
                               - self.sem.DEFAULT_DELAY)
            if cycle_time_diff > 0.15:
                self.add_to_main_log(
                    f'CTRL: Warning: Grid {grid_index} tile cycle time was '
                    f'{cycle_time_diff:.2f} s longer than expected.')

            # Show the average durations for grabbing, inspecting and mirroring
            # tiles in the current grid
            if self.tile_grab_durations and self.tile_inspect_durations:
                self.add_to_main_log(
                    f'CTRL: Grid {grid_index}: avg. tile grab duration: '
                    f'{mean(self.tile_grab_durations):.1f} s '
                    f'(cycle time: {self.sem.current_cycle_time:.1f})')
                self.add_to_main_log(
                    f'CTRL: Grid {grid_index}: avg. tile inspect '
                    f'duration: {mean(self.tile_inspect_durations):.1f} s')
            if self.use_mirror_drive and self.tile_mirror_durations:
                self.add_to_main_log(
                    f'CTRL: Grid {grid_index}: avg. time to copy tile to '
                    f'mirror drive: {mean(self.tile_mirror_durations):.1f} s')
            # Clear duration lists for the next grid
            self.tile_grab_durations = []
            self.tile_inspect_durations = []
            self.tile_mirror_durations = []

            if theta > 0:
                # Disable scan rotation
                self.sem.set_scan_rotation(0)

            if len(active_tiles) == len(self.tiles_acquired):
                # Grid is complete, add it to the grids_acquired list
                self.grids_acquired.append(grid_index)
                # Empty the tile list since all tiles were acquired
                self.tiles_acquired = []

                if self.magc_mode:
                    grid_centre_d = self.gm[grid_index].centre_dx_dy
                    self.cs.set_vp_centre_d(grid_centre_d)
                    self.main_controls_trigger.transmit('DRAW VP')
                    self.main_controls_trigger.transmit(
                        'SET SECTION STATE GUI-'
                        + str(grid_index)
                        + '-acquired')

    def acquire_tile(self, grid_index, tile_index):
        """Acquire the specified tile with error handling and inspection."""

        tile_img = None
        relative_save_path = utils.tile_relative_save_path(
            self.stack_name, grid_index, tile_index, self.slice_counter)
        save_path = os.path.join(self.base_dir, relative_save_path)
        tile_id = str(grid_index) + '.' + str(tile_index)
        tile_accepted = False  # meaning if True: tile quality is ok
        tile_selected = False  # meaning if True: tile selected, will be saved
        tile_skipped = False   # meaning if True: tile already acquired

        # Criterion whether to retake image
        retake_img = (
            (self.acq_interrupted_at == [grid_index, tile_index])
            and not (tile_index in self.tiles_acquired))
        # Check if file already exists
        if (not os.path.isfile(save_path) or retake_img):
            # Read target coordinates for current tile
            stage_x, stage_y = self.gm[grid_index][tile_index].sx_sy
            # Move to that position
            self.add_to_main_log(
                'STAGE: Moving to position of tile %s' % tile_id)
            self.stage.move_to_xy((stage_x, stage_y))
            # The move function waits for the specified stage move wait interval
            # Check if there were microtome problems:
            # If yes, try one more time before pausing acquisition.
            if self.stage.error_state > 0:
                self.stage.reset_error_state()
                self.add_to_main_log(
                    'STAGE: Problem with XY move. Trying again.')
                # Add warning to log in viewport window
                error_log_str = (str(self.slice_counter)
                                 + ': WARNING (Problem with XY stage move)')
                self.error_log_file.write(error_log_str + '\n')
                self.add_to_vp_log(error_log_str)
                sleep(2)
                # Try to move to tile position again
                self.add_to_main_log(
                    'STAGE: Moving to position of tile ' + tile_id)
                self.stage.move_to_xy((stage_x, stage_y))
                # Check again if there is an error
                self.error_state = self.stage.error_state
                self.stage.reset_error_state()
                # If yes, pause stack
                if self.error_state > 0:
                    self.add_to_main_log(
                        'STAGE: XY move failed. Stack will be paused.')
        else:
            if tile_index in self.tiles_acquired:
                tile_skipped = True
                tile_accepted = True
                self.add_to_main_log(
                    'CTRL: Tile %s already acquired. Skipping.' % tile_id)
            else:
                # If tile already exists without being listed as acquired
                # and no indication of previous interruption:
                # Pause because risk of overwriting data!
                self.error_state = 403
                self.add_to_main_log(
                    'CTRL: Tile %s: Image file already exists!' %tile_id)

        # Proceed if no error has ocurred and tile not skipped:
        if self.error_state == 0 and not tile_skipped:

            # Show updated XY stage coordinates in Main Controls GUI
            self.main_controls_trigger.transmit('UPDATE XY')

            # Call autofocus routine (method 0, SmartSEM) on current tile?
            if (self.use_autofocus and self.autofocus.method == 0
                    and self.gm[grid_index][tile_index].autofocus_active
                    and (self.autofocus_stig_current_slice[0] or
                         self.autofocus_stig_current_slice[1])):
                do_move = False  # already at tile stage position
                self.do_zeiss_autofocus(*self.autofocus_stig_current_slice,
                                        do_move, grid_index, tile_index)
                # For tracking mode 0: Adjust wd/stig of other tiles
                if self.error_state == 0 and self.autofocus.tracking_mode == 0:
                    self.autofocus.approximate_wd_stig_in_grid(grid_index)
                    self.main_controls_trigger.transmit('DRAW VP')

            # Check mag if locked
            if self.mag_locked and not self.error_state in [505, 506, 507]:
                self.check_locked_mag()
            # Check focus if locked
            if (self.wd_stig_locked
                    and not self.error_state in [505, 506, 507]):
                self.check_locked_wd_stig()

            # After all preliminary checks complete, now acquire the frame!
            # (Even if error has been detected. May be helpful.)
            self.add_to_main_log('SEM: Acquiring tile at X:'
                                 + '{0:.3f}'.format(stage_x)
                                 + ', Y:' + '{0:.3f}'.format(stage_y))
            # Indicate current tile in Viewport
            self.main_controls_trigger.transmit(
                'ACQ IND TILE' + str(grid_index) + '.' + str(tile_index))
            start_time = time()
            # Acquire the frame
            self.sem.acquire_frame(save_path)
            # Time how long it takes to acquire the frame. Display a warning in
            # the log if the overhead is larger than 1.5 seconds.
            end_time = time()
            grab_duration = end_time - start_time
            self.tile_grab_durations.append(grab_duration)
            grab_overhead = grab_duration - self.sem.current_cycle_time
            if grab_overhead > 1.5:
                self.add_to_main_log(
                    f'SEM: Warning: Grab overhead too large '
                    f'({grab_overhead:.1f} s).')
            # Remove indication in Viewport
            self.main_controls_trigger.transmit(
                'ACQ IND TILE' + str(grid_index) + '.' + str(tile_index))

            # Copy image file to the mirror drive
            if self.use_mirror_drive:
                start_time = time()
                self.mirror_files([save_path])
                # Time how long it takes to copy the file. Add a warning if
                # it took longer than 1.5 seconds.
                end_time = time()
                mirror_duration = end_time - start_time
                self.tile_mirror_durations.append(mirror_duration)
                if mirror_duration > 1.5:
                    self.add_to_main_log(
                        f'CTRL: Warning: Copying tile to mirror drive took too '
                        f'long ({mirror_duration:.1f} s).')

            # Check if image was saved and process it
            if os.path.isfile(save_path):
                start_time = time()
                (tile_img, mean, stddev,
                 range_test_passed, slice_by_slice_test_passed, tile_selected,
                 load_error, load_exception,
                 grab_incomplete, frozen_frame_error) = (
                    self.img_inspector.process_tile(save_path,
                                                    grid_index, tile_index,
                                                    self.slice_counter))
                # Time the duration of process_tile()
                end_time = time()
                inspect_duration = end_time - start_time
                self.tile_inspect_durations.append(inspect_duration)
                if inspect_duration > 1.5:
                    self.add_to_main_log(
                        f'CTRL: Warning: Inspecting tile took too '
                        f'long ({inspect_duration:.1f} s).')

                if not load_error:
                    # Assume tile_accepted, check against various errors below
                    tile_accepted = True
                    self.add_to_main_log('CTRL: Tile ' + tile_id
                                         + ': M:' + '{0:.2f}'.format(mean)
                                         + ', SD:' + '{0:.2f}'.format(stddev))
                    # New preview available, show it (if tile previews active)
                    self.main_controls_trigger.transmit('DRAW VP')

                    if self.error_state in [505, 506, 507]:
                        # Don't accept tile if autofocus error has ocurred
                        tile_accepted = False
                    else:
                        # Check for frozen or incomplete frames
                        if frozen_frame_error:
                            tile_accepted = False
                            self.error_state = 304
                            self.add_to_main_log(
                                'SEM: Tile ' + tile_id
                                + ': SmartSEM frozen frame error!')
                        elif grab_incomplete:
                            tile_accepted = False
                            self.error_state = 303
                            self.add_to_main_log(
                                'SEM: Tile ' + tile_id
                                + ': SmartSEM grab incomplete error!')
                        elif self.monitor_images:
                            # Two additional checks if 'image monitoring'
                            # option is active
                            if not range_test_passed:
                                tile_accepted = False
                                self.error_state = 503
                                self.add_to_main_log(
                                    'CTRL: Tile outside of permitted mean/SD '
                                    'range!')
                            elif (slice_by_slice_test_passed is not None
                                  and not slice_by_slice_test_passed):
                                tile_accepted = False
                                self.error_state = 504
                                self.add_to_main_log(
                                    'CTRL: Tile above mean/SD slice-by-slice '
                                    'thresholds.')
                else:
                    # Tile image file could not be loaded
                    self.add_to_main_log('CTRL: Error: Failed to load tile '
                                         'image file.')
                    self.error_state = 404
            else:
                # File was not saved
                self.add_to_main_log('SEM: Tile image acquisition failure. ')
                self.error_state = 302

        # Check for "Ask User" override
        if self.ask_user_mode and self.error_state in [303, 304, 503, 504]:
            self.main_controls_trigger.transmit('ASK IMAGE ERROR OVERRIDE')
            while not self.user_reply_received:
                sleep(0.1)
            if self.user_reply == QMessageBox.Yes:
                # Follow user's request, reset error state and accept tile
                self.error_state = 0
                tile_accepted = True
            else:
                self.image_rejected_by_user = True
            self.user_reply_received = False

        return (tile_img, relative_save_path, save_path,
                tile_accepted, tile_skipped, tile_selected)

    def register_accepted_tile(self, relative_save_path, grid_index, tile_index,
                               tile_width, tile_height):
        """Register the tile image in the image list file and the metadata
        file. Send metadata to remote server.
        """
        timestamp = int(time())
        tile_id = utils.tile_id(grid_index, tile_index,
                                self.slice_counter)
        global_x, global_y = (
            self.gm.tile_position_for_registration(
                grid_index, tile_index))
        global_z = int(self.total_z_diff * 1000)
        tileinfo_str = (relative_save_path + ';'
                        + str(global_x) + ';'
                        + str(global_y) + ';'
                        + str(global_z) + ';'
                        + str(self.slice_counter) + '\n')
        self.imagelist_file.write(tileinfo_str)
        # Write the same information to the imagelist on the mirror drive
        if self.use_mirror_drive:
            self.mirror_imagelist_file.write(tileinfo_str)
        self.tiles_acquired.append(tile_index)
        tile_metadata = {
            'timestamp': timestamp,
            'tileid': tile_id,
            'filename': relative_save_path.replace('\\', '/'),
            'tile_width': tile_width,
            'tile_height': tile_height,
            'working_distance': self.gm[grid_index][tile_index].wd,
            'glob_x': global_x,
            'glob_y': global_y,
            'glob_z': global_z,
            'slice_counter': self.slice_counter}
        self.metadata_file.write('TILE: ' + str(tile_metadata) + '\n')
        # Server notification
        if self.send_metadata:
            status, exc_str = self.notifications.send_tile_metadata(
                self.metadata_project_name, self.stack_name, tile_metadata)
            if status == 100:
                self.error_state = 508
                self.pause_acquisition(1)
                self.add_to_main_log('CTRL: Error sending tile metadata '
                                     'to server. ' + exc_str)

    def save_rejected_tile(self, tile_save_path, grid_index, tile_index,
                           fail_counter):
        """Save rejected tile image in the 'rejected' subfolder."""
        rejected_tile_save_path = utils.rejected_tile_save_path(
            self.base_dir, self.stack_name, grid_index, tile_index,
            self.slice_counter, fail_counter)
        # Copy tile to folder 'rejected'
        try:
            shutil.copy(tile_save_path, rejected_tile_save_path)
        except Exception as e:
            self.add_to_main_log(
                'CTRL: Warning: Unable to save rejected tile image, ' + str(e))
        if self.use_mirror_drive:
            self.mirror_files([rejected_tile_save_path])

    def handle_frozen_frame(self, grid_index):
        """Workaround for when a frame in the grid specified by grid_index is
        frozen in SmartSEM and no further frames can be acquired ('frozen frame
        error'): Try to 'unfreeze' by switching to a different store resolution
        and then back to the grid's original store resolution.

        TODO: This is currently not in use because rather than continue at the
        tile where the frozen frame error was detected, SBEMimage should try to
        continue from the *previous* tile (because that tile is likely
        corrupted.) This needs changes in the acquisition loop.
        """
        target_store_res = self.gm[grid_index].frame_size_selector
        if target_store_res == 0:
            self.sem.set_frame_size(1)
        else:
            self.sem.set_frame_size(0)
        sleep(1)
        # Back to previous store resolution:
        self.sem.set_frame_size(target_store_res)

    def do_zeiss_autofocus(self, do_focus, do_stig, do_move,
                           grid_index, tile_index):
        """Run SmartSEM autofocus at current stage position if do_move == False,
        otherwise move to grid_index.tile_index position beforehand.
        """
        if do_move:
            # Read target coordinates for specified tile
            stage_x, stage_y = self.gm[grid_index][tile_index].sx_sy
            # Move to that position
            self.add_to_main_log(
                'STAGE: Moving to position of tile '
                + str(grid_index) + '.' + str(tile_index) + ' for autofocus')
            self.stage.move_to_xy((stage_x, stage_y))
            # The move function waits for the specified stage move wait interval
            # Check if there were microtome problems:
            # If yes, try one more time before pausing acquisition.
            if self.stage.error_state > 0:
                self.stage.reset_error_state()
                self.add_to_main_log(
                    'STAGE: Problem with XY move. Trying again.')
                # Update log in Viewport window with a warning
                error_log_str = (str(self.slice_counter)
                                 + ': WARNING (Problem with XY stage move)')
                self.error_log_file.write(error_log_str + '\n')
                # Signal to Main Controls to update log in Viewport
                self.add_to_vp_log(error_log_str)
                sleep(2)
                # Try to move to tile position again
                self.add_to_main_log(
                    'STAGE: Moving to position of tile '
                    + str(grid_index) + '.' + str(tile_index))
                self.stage.move_to_xy((stage_x, stage_y))
                # Check again if there is an error
                self.error_state = self.stage.error_state
                self.stage.reset_error_state()
                # If yes, pause stack
                if self.error_state > 0:
                    self.add_to_main_log('STAGE: XY move for autofocus failed.')
        if self.error_state == 0 and (do_focus or do_stig):
            if do_focus and do_stig:
                af_type = '(focus+stig)'
            elif do_focus:
                af_type = '(focus only)'
            elif do_stig:
                af_type = '(stig only)'
            wd = self.sem.get_wd()
            sx, sy = self.sem.get_stig_xy()
            self.add_to_main_log('SEM: Running SmartSEM AF procedure '
                                 + af_type + ' for tile '
                                 + str(grid_index) + '.' + str(tile_index))
            return_msg = self.autofocus.run_zeiss_af(do_focus, do_stig)
            self.add_to_main_log(return_msg)
            if 'ERROR' in return_msg:
                self.error_state = 505
            elif not self.autofocus.wd_stig_diff_below_max(wd, sx, sy):
                self.error_state = 507
            else:
                # Save settings for specified tile
                self.gm[grid_index][tile_index].wd = self.sem.get_wd()
                self.gm[grid_index][tile_index].stig_xy = list(
                    self.sem.get_stig_xy())

                # Show updated WD label(s) in Viewport
                self.main_controls_trigger.transmit('DRAW VP')

            # Restore grid settings for tile acquisition
            self.sem.apply_frame_settings(
                self.gm[grid_index].frame_size_selector,
                self.gm[grid_index].pixel_size,
                self.gm[grid_index].dwell_time)
            # Delay necessary for Gemini (change of mag)
            sleep(0.2)

    def do_autofocus_before_grid_acq(self, grid_index):
        """If non-active tiles are selected for the SmartSEM autofocus, call the
        autofocus on them one by one before the grid acquisition starts.
        """
        autofocus_ref_tiles = self.gm[grid_index].autofocus_ref_tiles()
        active_tiles = self.gm[grid_index].active_tiles
        # Perform Zeiss autofocus for non-active autofocus tiles
        for tile_index in autofocus_ref_tiles:
            if tile_index not in active_tiles:
                do_move = True
                self.do_zeiss_autofocus(
                    *self.autofocus_stig_current_slice,
                    do_move, grid_index, tile_index)
                if self.error_state != 0 or self.pause_state == 1:
                    # Immediately pause and save interruption info
                    if not self.acq_paused:
                        self.pause_acquisition(1)
                    self.save_interruption_point(grid_index, tile_index)
                    break

    def do_heuristic_autofocus(self, tile_key):
        self.add_to_main_log('CTRL: Processing tile %s for '
                             'heuristic autofocus ' %tile_key)
        self.autofocus.process_image_for_heuristic_af(tile_key)
        wd_corr, sx_corr, sy_corr, within_range = (
            self.autofocus.get_heuristic_corrections(tile_key))
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
            self.add_to_main_log(
                'CTRL: No estimates computed (need one additional slice) ')

    def do_autofocus_adjustments(self, grid_index):
        # Apply average WD/STIG from reference tiles
        # if tracking mode "Average" is selected.
        if self.use_autofocus and self.autofocus.tracking_mode == 2:
            if self.autofocus.method == 0:
                self.add_to_main_log(
                    'CTRL: Applying average WD/STIG parameters '
                    '(SmartSEM autofocus).')
            elif self.autofocus.method == 1:
                self.add_to_main_log(
                    'CTRL: Applying average WD/STIG parameters '
                    '(heuristic autofocus).')
            # Compute new grid average for WD and STIG
            avg_grid_wd = (
                self.gm[grid_index].average_wd_of_autofocus_ref_tiles())

            avg_grid_stig_x, avg_grid_stig_y = (
                self.gm[grid_index].average_stig_xy_of_autofocus_ref_tiles())

            if (avg_grid_wd is not None
                    and avg_grid_stig_x is not None
                    and avg_grid_stig_y is not None):
                # TODO: Check if difference within acceptable range
                # Apply:
                self.wd_default = avg_grid_wd
                self.stig_x_default = avg_grid_stig_x
                self.stig_y_default = avg_grid_stig_y
                # Update grid:
                self.gm[grid_index].set_wd_for_all_tiles(avg_grid_wd)
                self.gm[grid_index].set_stig_xy_for_all_tiles(
                    [avg_grid_stig_x, avg_grid_stig_y])
                #else:
                #    self.add_to_main_log(
                #        'CTRL: Error: Difference in WD/STIG too large.')
                #    self.error_state = 507
                #    self.pause_acquisition(1)

        # If "Individual + Approximate" mode selected - approximate the working
        # distances and stig parameters for all non-autofocus tiles that are
        # active:
        if (self.use_autofocus
            and self.autofocus.tracking_mode == 0):
            self.autofocus.approximate_wd_stig_in_grid(grid_index)

        # If focus gradient active, adjust focus for grid(s):
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
        """Set wd/stig to target default values and add deltas for heuristic
        autofocus.
        """
        wd = self.wd_default + self.wd_delta
        stig_x = self.stig_x_default + self.stig_x_delta
        stig_y = self.stig_y_default + self.stig_y_delta
        self.sem.set_wd(wd)
        self.sem.set_stig_xy(stig_x, stig_y)
        self.show_wd_stig_in_log(wd, stig_x, stig_y)

    def check_locked_wd_stig(self):
        """Check if wd/stig was accidentally changed and restore targets."""
        change_detected = False
        diff_wd = abs(self.sem.get_wd() - self.locked_wd)
        diff_stig_x = abs(self.sem.get_stig_x() - self.locked_stig_x)
        diff_stig_y = abs(self.sem.get_stig_y() - self.locked_stig_y)

        if diff_wd > 0.000001:
            change_detected = True
            self.add_to_main_log(
                'SEM: Warning: Change in working distance detected.')
            # Restore previous working distance
            self.sem.set_wd(self.locked_wd)
            self.add_to_main_log('SEM: Restored previous working distance.')

        if (diff_stig_x > 0.000001 or diff_stig_y > 0.000001):
            change_detected = True
            self.add_to_main_log(
                'SEM: Warning: Change in stigmation settings detected.')
            # Restore previous settings
            self.sem.set_stig_xy(self.locked_stig_x, self.locked_stig_y)
            self.add_to_main_log(
                'SEM: Restored previous stigmation parameters.')
        if change_detected:
            self.main_controls_trigger.transmit('FOCUS ALERT')

    def check_locked_mag(self):
        """Check if mag was accidentally changed and restore target mag."""
        current_mag = self.sem.get_mag()
        if current_mag != self.locked_mag:
            self.add_to_main_log(
                'SEM: Warning: Change in magnification detected.')
            self.add_to_main_log(
                'SEM: Current mag: ' + str(current_mag)
                + '; target mag: ' + str(self.locked_mag))
            # Restore previous magnification
            self.sem.set_mag(self.locked_mag)
            self.add_to_main_log('SEM: Restored previous magnification.')
            self.main_controls_trigger.transmit('MAG ALERT')

    def show_wd_stig_in_log(self, wd, stig_x, stig_y):
        """Display formatted focus parameters in the main log."""
        self.add_to_main_log(
            'SEM: WD/STIG_XY: '
            + '{0:.6f}'.format(wd * 1000)  # wd in metres, show in mm
            + ', {0:.6f}'.format(stig_x)
            + ', {0:.6f}'.format(stig_y))

    def set_user_reply(self, reply):
        """Receive a user reply from main window."""
        self.user_reply = reply
        self.user_reply_received = True

    def reset_acquisition(self):
        self.slice_counter = 0
        self.total_z_diff = 0
        self.stack_completed = False
        self.acq_paused = False
        self.acq_interrupted = False
        self.acq_interrupted_at = []
        self.tiles_acquired = []
        self.grids_acquired = []

    def add_to_main_log(self, msg):
        """Add entry to the Main Controls log."""
        msg = utils.format_log_entry(msg)
        # Store entry in main log file
        self.main_log_file.write(msg + '\n')
        # Send entry to Main Controls via queue and trigger
        self.main_controls_trigger.transmit(msg)

    def add_to_vp_log(self, msg):
        """Add entry to the Viewport log (monitoring tab)."""
        self.main_controls_trigger.transmit('VP LOG' + msg)

    def pause_acquisition(self, pause_state):
        """Pause the current acquisition."""
        # Pause immediately after the current image is acquired
        if pause_state == 1:
            self.pause_state = 1
            self.acq_paused = True
        # Pause after finishing current slice and cutting
        elif pause_state == 2:
            self.pause_state = 2
            self.acq_paused = True

    def save_interruption_point(self, grid_index, tile_index):
        """Save grid/tile position where interruption occured."""
        self.acq_interrupted = True
        self.acq_interrupted_at = [grid_index, tile_index]

    def reset_error_state(self):
        self.error_state = 0
        self.error_info = ''
