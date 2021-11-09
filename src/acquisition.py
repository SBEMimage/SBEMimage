# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
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
import math

from time import sleep, time
from statistics import mean
from imageio import imwrite
from dateutil.relativedelta import relativedelta
from PyQt5.QtWidgets import QMessageBox

import utils
from utils import Error


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

        # Error state (see full list: utils.Errors) and further info
        # about the error in a string
        self.error_state = Error.none
        self.error_info = ''

        # Log file handles
        self.main_log_file = None
        self.imagelist_file = None
        self.imagelist_ov_file = None
        self.mirror_imagelist_file = None
        self.mirror_imagelist_ov_file = None
        self.incident_log_file = None
        self.metadata_file = None
        # Filename of current Viewport screenshot
        self.vp_screenshot_filename = None

        # Remove trailing slashes and whitespace from base directory string
        self.cfg['acq']['base_dir'] = self.cfg['acq']['base_dir'].rstrip(r'\/ ')
        self.base_dir = self.cfg['acq']['base_dir']
        # pause_state:
        # 1 -> pause immediately, 2 -> pause after completing current slice
        self.pause_state = None
        self.acq_paused = (self.cfg['acq']['paused'].lower() == 'true')
        self.stack_completed = False
        self.report_requested = False
        self.slice_counter = int(self.cfg['acq']['slice_counter'])
        self.number_slices = int(self.cfg['acq']['number_slices'])
        self.slice_thickness = int(self.cfg['acq']['slice_thickness'])
        # use_target_z_diff: Whether to use a target depth (true), or a target number of slices (false)
        self.use_target_z_diff = (
                self.cfg['acq']['use_target_z_diff'].lower() == 'true')
        self.target_z_diff = float(self.cfg['acq']['target_z_diff'])
        # total_z_diff: The total Z of sample removed in microns (only cuts
        # during acquisitions are taken into account)
        self.total_z_diff = float(self.cfg['acq']['total_z_diff'])
        # stage_z_position: The current Z position of the microtome/stage.
        # This variable is updated when the stack is (re)started by reading the
        # current Z position from the microtome/stage hardware.
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
        # tiles_acquired: List of tiles that were already acquired in the grid
        # in which the interruption occured.
        self.tiles_acquired = json.loads(self.cfg['acq']['tiles_acquired'])
        # grids_acquired: Grids (on the current slice) that had already been
        # acquired before the interruption occured.
        self.grids_acquired = json.loads(self.cfg['acq']['grids_acquired'])
        # mirror_drive: network/local drive for mirroring image data
        self.mirror_drive = self.cfg['sys']['mirror_drive']
        # mirror_drive_directory: same as base_dir, only drive letter changes
        self.mirror_drive_dir = os.path.join(
            self.mirror_drive, self.base_dir[2:])
        # send_metadata: True if metadata to be sent to metadata (VIME) server
        self.send_metadata = (
            self.cfg['sys']['send_metadata'].lower() == 'true')
        self.metadata_project_name = self.cfg['sys']['metadata_project_name']
        # The following two options (mirror drive, overviews) cannot be
        # enabled/disabled during a run.
        self.use_mirror_drive = (
            self.cfg['sys']['use_mirror_drive'].lower() == 'true')
        self.take_overviews = (
            self.cfg['acq']['take_overviews'].lower() == 'true')
        # The following options can be changed while acq is running
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
        # remote_check_interval: slice interval at which SBEMimage will check
        # e-mail account for remote commands
        self.remote_check_interval = int(
            self.cfg['monitoring']['remote_check_interval'])
        # Settings for sweeping when debris is detected
        self.max_number_sweeps = int(self.cfg['debris']['max_number_sweeps'])
        self.continue_after_max_sweeps = (
            self.cfg['debris']['continue_after_max_sweeps'].lower() == 'true')

        self.magc_mode = (self.cfg['sys']['magc_mode'].lower() == 'true')
        # Create text file for notes
        notes_file = os.path.join(self.base_dir, self.stack_name + '_notes.txt')
        if not os.path.isfile(notes_file):
            open(notes_file, 'a').close()

    @property
    def base_dir(self):
        return self._base_dir

    @base_dir.setter
    def base_dir(self, new_base_dir):
        self._base_dir = new_base_dir
        # Extract the name of the stack from the base directory
        self.stack_name = self.base_dir[self.base_dir.rfind('\\') + 1:]

    def save_to_cfg(self):
        """Save current state of attributes to ConfigParser object cfg."""
        self.cfg['acq']['base_dir'] = self.base_dir
        self.cfg['acq']['paused'] = str(self.acq_paused)
        self.cfg['acq']['slice_counter'] = str(self.slice_counter)
        self.cfg['acq']['number_slices'] = str(self.number_slices)
        self.cfg['acq']['slice_thickness'] = str(self.slice_thickness)
        self.cfg['acq']['total_z_diff'] = str(self.total_z_diff)
        self.cfg['acq']['use_target_z_diff'] = str(self.use_target_z_diff)
        self.cfg['acq']['target_z_diff'] = str(self.target_z_diff)

        self.cfg['acq']['interrupted'] = str(self.acq_interrupted)
        self.cfg['acq']['interrupted_at'] = str(self.acq_interrupted_at)
        self.cfg['acq']['tiles_acquired'] = str(self.tiles_acquired)
        self.cfg['acq']['grids_acquired'] = str(self.grids_acquired)

        self.cfg['sys']['mirror_drive'] = self.mirror_drive
        self.cfg['sys']['use_mirror_drive'] = str(self.use_mirror_drive)
        self.cfg['sys']['send_metadata'] = str(self.send_metadata)
        self.cfg['sys']['metadata_project_name'] = self.metadata_project_name
        self.cfg['acq']['take_overviews'] = str(self.take_overviews)
        self.cfg['acq']['use_email_monitoring'] = str(
            self.use_email_monitoring)
        self.cfg['acq']['use_debris_detection'] = str(
            self.use_debris_detection)
        self.cfg['acq']['ask_user'] = str(self.ask_user_mode)
        self.cfg['acq']['monitor_images'] = str(self.monitor_images)
        self.cfg['acq']['use_autofocus'] = str(self.use_autofocus)
        self.cfg['acq']['eht_off_after_stack'] = str(self.eht_off_after_stack)
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
        if self.use_target_z_diff:
            # calculate number of slices based on total Z difference, rounding down to nearest whole slice
            number_slices = math.floor((self.target_z_diff*1000)/self.slice_thickness)
        else:
            number_slices = self.number_slices
        N = number_slices
        if N == 0:  # 0 slices is a valid setting. It means: image the current
            N = 1  # surface, but do not cut afterwards.
        current = self.sem.target_beam_current
        min_dose = max_dose = None
        if self.microtome is not None:
            total_cut_time = (
                number_slices * self.microtome.full_cut_duration)
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
                        if (self.ovm[ov_index].slice_active(slice_counter)
                                and self.ovm[ov_index].active):
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
                    if (self.gm[grid_index].slice_active(slice_counter)
                            and self.gm[grid_index].active):
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

        total_z = (number_slices * self.slice_thickness) / 1000
        total_data_in_GB = total_data / (10**9)
        total_duration = (
            total_imaging_time + total_stage_move_time + total_cut_time)

        # Calculate date and time of completion
        now = datetime.datetime.now()
        if self.use_target_z_diff:
            fraction_completed = self.total_z_diff / total_z
        else:
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
            # TODO: with improved logging this is no longer needed -> remove?
            self.main_controls_trigger.transmit(utils.format_log_entry(
                'CTRL: Error while creating subdirectories: ' + exception_str))
            self.pause_acquisition(1)
            self.error_state = Error.primary_drive
        elif self.use_mirror_drive:
            success, exception_str = utils.create_subdirectories(
                self.mirror_drive_dir, subdirectory_list)
            if not success:
                self.main_controls_trigger.transmit(utils.format_log_entry(
                    'CTRL: Error while creating subdirectories on mirror '
                    'drive: ' + exception_str))
                self.pause_acquisition(1)
                self.error_state = Error.mirror_drive

    def set_up_acq_logs(self):
        """Create all acquisition log files and copy them to the mirror drive
        if applicable.
        """
        # Get timestamp for this run
        timestamp = str(datetime.datetime.now())[:22].translate(
            {ord(i):None for i in ' :.'})

        try:
            # Note that the config file and the gridmap file are only saved once
            # at the beginning of each run. The other log files are updated
            # continously during the run.

            # Save current configuration file with timestamp in log folder
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
            # Set up imagelist file, which contains the paths, file names and
            # positions of all acquired tiles
            self.imagelist_filename = os.path.join(
                self.base_dir, 'meta', 'logs',
                'imagelist_' + timestamp + '.txt')
            self.imagelist_file = open(self.imagelist_filename,
                                       'w', buffer_size)
            # Set up overview imagelist file, which contains the paths, file names and
            # positions of all acquired overviews
            self.imagelist_ov_filename = os.path.join(
                self.base_dir, 'meta', 'logs',
                'imagelist_ov_' + timestamp + '.txt')
            self.imagelist_ov_file = open(self.imagelist_ov_filename,
                                          'w', buffer_size)
            # Incident log for warnings, errors and debris detection events
            # (All incidents are also logged in the main log file.)
            self.incident_log_filename = os.path.join(
                self.base_dir, 'meta', 'logs',
                'incident_log_' + timestamp + '.txt')
            self.incident_log_file = open(self.incident_log_filename,
                                          'w', buffer_size)
            self.metadata_filename = os.path.join(
                self.base_dir, 'meta', 'logs', 'metadata_' + timestamp + '.txt')
            self.metadata_file = open(self.metadata_filename, 'w', buffer_size)
        except Exception as e:
            utils.log_error('CTRL', 'Error while setting up log files: ' + str(e))
            self.add_to_main_log(
                'CTRL: Error while setting up log files: ' + str(e))
            self.pause_acquisition(1)
            self.error_state = Error.primary_drive
        else:
            if self.use_mirror_drive:
                # Copy all log files to mirror drive
                self.mirror_files([
                    config_filename,
                    gridmap_filename,
                    self.main_log_filename,
                    self.imagelist_filename,
                    self.imagelist_ov_filename,
                    self.incident_log_filename,
                    self.metadata_filename])
                # Create file handle for imagelist files on mirror drive.
                # The imagelist files on the mirror drive are updated continously.
                # The other logfiles are copied at the end of each run.
                try:
                    self.mirror_imagelist_file = open(os.path.join(
                        self.mirror_drive, self.imagelist_filename[2:]),
                        'w', buffer_size)
                    self.mirror_imagelist_ov_file = open(os.path.join(
                        self.mirror_drive, self.imagelist_ov_filename[2:]),
                        'w', buffer_size)
                except Exception as e:
                    utils.log_error(
                        'CTRL',
                        'Error while creating imagelist files on mirror '
                        'drive: ' + str(e))
                    self.add_to_main_log(
                        'CTRL: Error while creating imagelist files on mirror '
                        'drive: ' + str(e))
                    self.pause_acquisition(1)
                    self.error_state = Error.mirror_drive

    def mirror_files(self, file_list):
        """Copy files in file_list to mirror drive, keep relative path."""
        try:
            for file_name in file_list:
                dst_file_name = os.path.join(self.mirror_drive, file_name[2:])
                shutil.copy(file_name, dst_file_name)
        except Exception as e:
            utils.log_warning('CTRL', 'WARNING (Could not mirror file(s))')
            self.add_to_incident_log('WARNING (Could not mirror file(s))')
            sleep(2)
            # Try again
            try:
                for file_name in file_list:
                    dst_file_name = os.path.join(
                        self.mirror_drive, file_name[2:])
                    shutil.copy(file_name, dst_file_name)
            except Exception as e:
                utils.log_error(
                    'CTRL',
                    'Copying file(s) to mirror drive failed: ' + str(e))
                self.add_to_main_log(
                    'CTRL: Copying file(s) to mirror drive failed: ' + str(e))
                self.pause_acquisition(1)
                self.error_state = Error.mirror_drive

    def load_acq_notes(self):
        """Read the contents of the notes text file and return them. Return
        None if the file does not exist.
        """
        notes_file = os.path.join(self.base_dir, self.stack_name + '_notes.txt')
        if not os.path.isfile(notes_file):
            return None
        with open(notes_file, mode='r') as f:
            notes = f.read()
        return notes

    def save_acq_notes(self, contents):
        """Save contents to the acquisition notes text file."""
        notes_file = os.path.join(self.base_dir, self.stack_name + '_notes.txt')
        with open(notes_file, mode='w') as f:
            f.write(contents)
        if self.use_mirror_drive:
            self.mirror_files([notes_file])

# ====================== STACK ACQUISITION THREAD run() ========================

    def run(self):
        # override exception catching to reset GUI on error
        try:
            self.run_acquisition()
        except:
            utils.log_exception("Exception")
            # Reset GUI
            self.main_controls_trigger.transmit('ACQ NOT IN PROGRESS')

    def run_acquisition(self):
        """Run acquisition in a thread started from main_controls.py."""

        self.reset_error_state()
        self.pause_state = None

        if self.use_mirror_drive:
            # Update the mirror drive directory. Both mirror drive and
            # base directory may have changed.
            self.mirror_drive_dir = os.path.join(
                self.mirror_drive, self.base_dir[2:])

        self.set_up_acq_subdirectories()
        self.set_up_acq_logs()

        # Proceed if no error has occurred during setup of folders and logs
        if self.error_state == Error.none:
            # autofocus and autostig status for the current slice
            self.autofocus_stig_current_slice = False, False

            # Focus parameters and magnification can be locked to certain
            # values while a grid is being acquired. If SBEMimage detects a
            # change (for example when the user accidentally touches a knob),
            # the correct values can be restored.
            self.wd_stig_locked = False
            self.mag_locked = False
            self.locked_wd = None
            self.locked_stig_x, self.locked_stig_y = None, None
            self.locked_mag = None

            # Global default settings for working distance and stimation,
            # initialized with the current settings read from the SEM
            self.wd_default = self.sem.get_wd()
            self.stig_x_default, self.stig_y_default = (
                self.sem.get_stig_xy())
            # The following variables store the current tile settings,
            # initialized with the defaults
            self.tile_wd = self.wd_default
            self.tile_stig_x = self.stig_x_default
            self.tile_stig_y = self.stig_y_default

            # Alternating plus/minus deltas for wd and stig, needed for
            # heuristic autofocus, otherwise set to 0
            self.wd_delta, self.stig_x_delta, self.stig_y_delta = 0, 0, 0
            # List of tiles to be processed for heuristic autofocus
            # during the cut cycle
            self.heuristic_af_queue = []
            # Reset current estimators and corrections
            self.autofocus.reset_heuristic_corrections()

            # Discard previous tile statistics in image inspector that are
            # used for tile-by-tile comparisons and quality checks.
            self.img_inspector.reset_tile_stats()

            # Variable used for user response from Main Controls
            self.user_reply = None

            # first_ov[index] is True for each overview image index for which
            # the user will be asked to confirm that the first acquired image
            # is free from debris. After confirmation, first_ov[index] is set
            # to False.
            self.first_ov = [True] * self.ovm.number_ov

            # Track the durations for grabbing, mirroring and inspecting tiles.
            # If the durations deviate too much from expected values,
            # warnings are shown in the log.
            self.tile_grab_durations = []
            self.tile_mirror_durations = []
            self.tile_inspect_durations = []

            # Start log for this run
            self.main_log_file.write('*** SBEMimage log for acquisition '
                                     + self.base_dir + ' ***\n\n')
            if self.acq_paused:
                utils.log_info('CTRL', 'Stack restarted.')
                self.main_log_file.write(
                    '\n*** STACK ACQUISITION RESTARTED ***\n')
                self.add_to_main_log('CTRL: Stack restarted.')
                self.acq_paused = False
            else:
                utils.log_info('CTRL', 'Stack started.')
                self.main_log_file.write(
                    '\n*** STACK ACQUISITION STARTED ***\n')
                self.add_to_main_log('CTRL: Stack started.')

            if self.use_mirror_drive:
                utils.log_info(
                    'CTRL',
                    'Mirror drive active: '
                    + self.mirror_drive_dir)
                self.add_to_main_log(
                    'CTRL: Mirror drive active: ' + self.mirror_drive_dir)

            # Save current configuration to disk:
            # Send signal to call save_settings() in main_controls.py
            self.main_controls_trigger.transmit('SAVE CFG')
            # Update progress bar and slice counter in Main Controls GUI
            self.main_controls_trigger.transmit('UPDATE PROGRESS')

            # Create metadata summary for this run, write it to disk and send it
            # to remote (VIME) server (if feature enabled).
            timestamp = int(time())
            grid_list = []
            grid_origin_list = []
            rotation_angle_list = []
            pixel_size_list = []
            dwell_time_list = []
            for grid_index in range(self.gm.number_grids):
                grid_list.append(str(grid_index).zfill(utils.GRID_DIGITS))
                grid_origin_list.append(self.gm[grid_index].origin_sx_sy.tolist())
                rotation_angle_list.append(self.gm[grid_index].rotation)
                pixel_size_list.append(self.gm[grid_index].pixel_size)
                dwell_time_list.append(self.gm[grid_index].dwell_time)
            session_metadata = {
                'timestamp': timestamp,
                'eht': self.sem.target_eht,
                'beam_current': self.sem.target_beam_current,
                'wd_stig_xy_default': [self.wd_default,
                                       self.stig_x_default,
                                       self.stig_y_default],
                'slice_thickness': self.slice_thickness,
                'grids': grid_list,
                'grid_origins': grid_origin_list,
                'rotation_angles': rotation_angle_list,
                'pixel_sizes': pixel_size_list,
                'dwell_times': dwell_time_list,
                'contrast': self.sem.bsd_contrast,
                'brightness': self.sem.bsd_brightness,
                'email_addresses: ': self.notifications.user_email_addresses
                }
            self.metadata_file.write('SESSION: ' + str(session_metadata) + '\n')
            if self.send_metadata:
                status, exc_str = self.notifications.send_session_metadata(
                    self.metadata_project_name, self.stack_name,
                    session_metadata)
                if status == 100:
                    self.error_state = Error.metadata_server
                    self.pause_acquisition(1)
                    utils.log_error(
                        'CTRL',
                        'Error sending session metadata '
                        'to server. ' + exc_str)
                    self.add_to_main_log('CTRL: Error sending session metadata '
                                         'to server. ' + exc_str)
                elif status == 200:
                    utils.log_info(
                        'CTRL',
                        'Session data sent. '
                        'Metadata server active.')
                    self.add_to_main_log(
                        'CTRL: Session data sent. Metadata server active.')

            # Set SEM to target high voltage and beam current.
            # EHT is assumed to be on at this point (PreStackDlg checks if EHT
            # is on when user wants to start the acq.)
            self.sem.apply_beam_settings()
            self.sem.set_beam_blanking(True)
            sleep(1)

            # Initialize focus parameters for all grids with defaults, but only
            # for those tiles that have not yet been initialized (there may be
            # existing focus settings from a previous run that must not be
            # overwritten!)
            for grid_index in range(self.gm.number_grids):
                if not self.gm[grid_index].use_wd_gradient:
                    self.gm[grid_index].set_wd_stig_xy_for_uninitialized_tiles(
                        self.wd_default,
                        [self.stig_x_default, self.stig_y_default])
                else:
                    # Set stig values to defaults for each tile if focus
                    # gradient is used, but don't change working distance
                    # because wd is calculated with gradient parameters.
                    self.gm[grid_index].set_stig_xy_for_all_tiles(
                        [self.stig_x_default, self.stig_y_default])

            # Show current focus/stig settings in the log
            utils.log_info('SEM',
                           'Current ' + utils.format_wd_stig(
                            self.wd_default, self.stig_x_default, self.stig_y_default))
            self.add_to_main_log('SEM: Current ' + utils.format_wd_stig(
                self.wd_default, self.stig_x_default, self.stig_y_default))

            # Make sure DM script uses the correct motor speeds
            # (When script crashes, default motor speeds are used.)
            if (self.microtome is not None
                    and self.microtome.device_name == 'Gatan 3View'):
                success = self.microtome.update_motor_speeds_in_dm_script()
                if not success:
                    self.error_state = self.microtome.error_state
                    self.error_info = self.microtome.error_info
                    self.microtome.reset_error_state()
                    self.pause_acquisition(1)
                    utils.log_error(
                        'STAGE',
                        'ERROR: Could not update '
                        'XY motor speeds.')
                    self.add_to_main_log('STAGE: ERROR: Could not update '
                                         'XY motor speeds.')

            # Get current Z position of microtome/stage
            self.stage_z_position = self.stage.get_z()
            if self.stage_z_position is None or self.stage_z_position < 0:
                # Try again
                sleep(1)
                self.stage_z_position = self.stage.get_z()
                if self.stage_z_position is None or self.stage_z_position < 0:
                    self.error_state = Error.dm_comm_retval
                    self.stage.reset_error_state()
                    self.pause_acquisition(1)
                    utils.log_error(
                        'STAGE',
                        'Error reading initial Z position.')
                    utils.log_warning(
                        'STAGE',
                        'Please ensure that the Z position is positive.')
                    self.add_to_main_log(
                        'STAGE: Error reading initial Z position.')
                    self.add_to_main_log(
                        'STAGE: Please ensure that the Z position is positive.')

            # Check for Z mismatch
            if self.microtome is not None and self.microtome.error_state == 206:
                self.microtome.reset_error_state()
                self.error_state = Error.mismatch_z
                self.pause_acquisition(1)
                # Show warning dialog in Main Controls GUI
                self.main_controls_trigger.transmit('Z WARNING')

            # Show current stage position (Z and XY) in Main Controls GUI
            self.main_controls_trigger.transmit('UPDATE Z')
            self.stage.get_xy()  # calling stage.get_xy() updates last_known_xy
            self.main_controls_trigger.transmit('UPDATE XY')

            # If an interruption occurred during the previous run and the
            # interruption occurred in a grid that is now deleted,
            # delete the interruption point.
            if (self.acq_interrupted
                    and self.acq_interrupted_at[0] >= self.gm.number_grids):
                utils.log_warning(
                    'CTRL',
                    f'Interruption point {str(self.acq_interrupted_at)} '
                    'reset because affected grid has been deleted.')
                self.add_to_main_log(
                    f'CTRL: Interruption point {str(self.acq_interrupted_at)} '
                    'reset because affected grid has been deleted.')
                self.acq_interrupted = False
                self.interrupted_at = []
                self.tiles_acquired = []

        # ========================= ACQUISITION LOOP ===========================

        while not (self.acq_paused or self.stack_completed):
            # Add line with stars in log file as a visual clue when a new
            # slice begins and show current slice counter and Z position.
            utils.log_info('CTRL',
                           '****************************************')
            utils.log_info('CTRL',
                           f'slice {self.slice_counter}, '
                           f'Z:{self.stage_z_position:6.3f}')
            self.add_to_main_log(
                'CTRL: ****************************************')
            self.add_to_main_log('CTRL: slice ' + str(self.slice_counter)
                + ', Z:' + '{0:6.3f}'.format(self.stage_z_position))

            # Counter for maintenance moves
            interval_counter_before = ((
                self.stage.total_xyz_move_counter[0][0]      # total X moves
                + self.stage.total_xyz_move_counter[1][0])   # total Y moves
                // self.stage.maintenance_move_interval)

            # First, acquire all overviews. On the first slice when (re)starting
            # an acquisition, the user will be asked to confirm that the
            # overviews are free from debris. All overviews are inspected and
            # debris detection is performed if enabled.
            if self.take_overviews:
                self.acquire_all_overviews()

            # Next, acquire all grids. If there was an interruption during the
            # previous run, the acquisition will resume at the interruption
            # point. Autofocus will be used for the grid acquision if enabled.
            self.acquire_all_grids()

            # Save a screenshot of the current content of the Viewport window
            # (saved in \workspace\viewport). The file is used for status
            # and error reports when e-mail monitoring is active.
            self.save_viewport_screenshot()

            # =========== E-mail monitoring / Receive server message ===========

            report_scheduled = (
                self.slice_counter % self.status_report_interval == 0)

            # If remote commands are enabled, check email account
            if (self.use_email_monitoring
                    and self.notifications.remote_commands_enabled
                    and self.slice_counter % self.remote_check_interval == 0):
                utils.log_info('CTRL', 'Checking for remote commands.')
                self.add_to_main_log('CTRL: Checking for remote commands.')
                self.process_remote_commands()

            # Send status report if scheduled or requested by remote command
            if (self.use_email_monitoring
                    and (self.slice_counter > 0)
                    and (report_scheduled or self.report_requested)):
                send_success, send_error, cleanup_success, cleanup_error = (
                    self.notifications.send_status_report(
                        self.base_dir, self.stack_name, self.slice_counter,
                        self.recent_log_filename, self.incident_log_filename,
                        self.vp_screenshot_filename))
                if send_success:
                    utils.log_info('CTRL', 'Status report e-mail sent.')
                else:
                    utils.log_error('CTRL', 'ERROR sending status report e-mail: '
                                    + send_error)
                if not cleanup_success:
                    utils.log_warning('CTRL', 'ERROR while trying to remove '
                                              'temporary file: ' + cleanup_error)
                self.report_requested = False

            if self.send_metadata:
                # If metadata server is enabled, check for messages and
                # process them.
                self.receive_msg_from_metadata_server()

            # Check if this is a single-slice acquisition -> NO CUT
            if self.number_slices == 0:
                self.pause_acquisition(1)

            # =========================== CUTTING ==============================

            if self.pause_state != 1 and self.error_state == Error.none:
                if self.microtome is not None:
                    # The method do_cut() carries out the cut cycle with error
                    # handling. Important: During the cut cycle, tiles are
                    # processed for the heuristic autofocus (if enabled).
                    # After a successful cut cycle, the slice_counter is
                    # increased (+1).
                    self.do_cut()

                if self.error_state == Error.none:
                    # Reset interruption status if cut completed without error
                    self.acq_interrupted = False
                    self.acq_interrupted_at = []
                    self.tiles_acquired = []
                    self.grids_acquired = []
                    # Confirm slice completion
                    self.confirm_slice_complete()
            # Imaging and cutting for the current slice have finished.
            # Save current configuration to disk, update progress in GUI,
            # and check if stack has been completed.
            self.main_controls_trigger.transmit('SAVE CFG')
            self.main_controls_trigger.transmit('UPDATE PROGRESS')

            if self.use_target_z_diff:
                # stop when cutting another slice at the current thickness would exceed the target z depth
                if (self.total_z_diff + (self.slice_thickness/1000)) > self.target_z_diff:
                    self.stack_completed = True
            else:
                if self.slice_counter == self.number_slices:
                    self.stack_completed = True

            # Copy log file to mirror disk
            # (Error handling in self.mirror_files())
            if self.use_mirror_drive:
                self.mirror_files([self.main_log_filename])
            sleep(0.1)

            # If enabled do maintenance moves at specified intervals
            if self.stage.use_maintenance_moves:
                interval_counter_after = ((
                    self.stage.total_xyz_move_counter[0][0]
                    + self.stage.total_xyz_move_counter[1][0])
                    // self.stage.maintenance_move_interval)
                if interval_counter_after > interval_counter_before:
                    self.do_maintenance_moves()

        # ===================== END OF ACQUISITION LOOP ========================

        if self.use_autofocus:
            # Do final autofocus adjustments and show updated working distances
            for grid_index in range(self.gm.number_grids):
                self.do_autofocus_adjustments(grid_index)
            self.main_controls_trigger.transmit('DRAW VP')
            if self.autofocus.method == 1:
                # Clear deltas and set focus parameters to defaults
                self.wd_delta, self.stig_x_delta, self.stig_y_delta = 0, 0, 0
                self.set_default_wd_stig()

        if self.error_state != Error.none:
            # If an error has occurred, show a message in the GUI and send an
            # e-mail alert if e-mail monitoring is active.
            self.process_error_state()

        if self.stack_completed and not self.number_slices == 0:
            utils.log_info('CTRL', 'Stack completed.')
            self.add_to_main_log('CTRL: Stack completed.')
            self.main_controls_trigger.transmit('COMPLETION STOP')
            if self.use_email_monitoring:
                # Send notification email
                msg_subject = 'Stack ' + self.stack_name + ' COMPLETED.'
                success, error_msg = self.notifications.send_email(
                    msg_subject, '')
                if success:
                    utils.log_info('CTRL', 'Notification e-mail sent.')
                    self.add_to_main_log('CTRL: Notification e-mail sent.')
                else:
                    utils.log_error('CTRL',
                                    'ERROR sending notification email: '
                                    + error_msg)
                    self.add_to_main_log(
                        'CTRL: ERROR sending notification email: ' + error_msg)
            if self.eht_off_after_stack:
                self.sem.turn_eht_off()
                utils.log_info('SEM',
                               'EHT turned off after stack completion.')
                self.add_to_main_log(
                    'SEM: EHT turned off after stack completion.')

        if self.acq_paused:
            utils.log_info('CTRL', 'Stack paused.')
            self.add_to_main_log('CTRL: Stack paused.')

        # Update acquisition status in Main Controls GUI
        self.main_controls_trigger.transmit('ACQ NOT IN PROGRESS')

        # Send signal to metadata sever that session has been stopped
        if self.send_metadata:
            session_stopped_status = {
                'timestamp': int(time()),
                'error_state': str(self.error_state)
            }
            status, exc_str = self.notifications.send_session_stopped(
                self.metadata_project_name, self.stack_name,
                session_stopped_status)
            if status == 100:
                self.error_state = Error.metadata_server
                self.pause_acquisition(1)
                utils.log_error('CTRL',
                                'Error sending "session stopped" '
                                'signal to VIME server. '
                                + exc_str)
                self.add_to_main_log('CTRL: Error sending "session stopped" '
                                     'signal to VIME server. ' + exc_str)

        # Add last entry to main log
        self.main_log_file.write('*** END OF LOG ***\n')

        # Copy log files to mirror drive. Error handling in self.mirror_files()
        if self.use_mirror_drive:
            self.mirror_files([self.main_log_filename,
                               self.incident_log_filename,
                               self.metadata_filename])
        # Close all log files
        if self.main_log_file is not None:
            self.main_log_file.close()
        if self.imagelist_file is not None:
            self.imagelist_file.close()
        if self.imagelist_ov_file is not None:
            self.imagelist_ov_file.close()
        if self.use_mirror_drive and self.mirror_imagelist_file is not None:
            self.mirror_imagelist_file.close()
            self.mirror_imagelist_ov_file.close()
        if self.incident_log_file is not None:
            self.incident_log_file.close()
        if self.metadata_file is not None:
            self.metadata_file.close()

    # ================ END OF STACK ACQUISITION THREAD run() ===================

    def process_remote_commands(self):
        """Check if user has sent an e-mail with a command to the e-mail
        account associated with this setup (see system configuration).
        Currently implemented: User can pause the acquisition or request a
        status report.
        """
        command = self.notifications.get_remote_command()
        if command in ['stop', 'pause']:
            # Send a confirmation e-mail to the account that receives the remote
            # commands. This moves the e-mail containing the command down in the
            # inbox, so that it won't be read again.
            self.notifications.send_email('Command received', '', [],
                                          [self.notifications.email_account])
            # Pause acquisition after current slice is complete (pause_state 2)
            # unless pause command pause_state 1 is already active
            if self.pause_state != 1:
                self.pause_acquisition(2)
            success, error_msg = self.notifications.send_email(
                'Remote stop', 'The acquisition was paused remotely.')
            if not success:
                utils.log_error(
                    'CTRL',
                    'Error sending confirmation email: '
                    + error_msg)
                self.add_to_main_log('CTRL: Error sending confirmation email: '
                                     + error_msg)
            # Signal to Main Controls that acquisition paused remotely
            self.main_controls_trigger.transmit('REMOTE STOP')
        elif command in ['continue', 'start', 'restart']:
            pass
            # TODO: let user continue paused acq with remote command
        elif command == 'report':
            utils.log_info('CTRL', 'REPORT remote command received.')
            self.add_to_main_log('CTRL: REPORT remote command received.')
            self.notifications.send_email('Command received', '', [],
                                          [self.notifications.email_account])
            self.report_requested = True
        elif command == 'ERROR':
            utils.log_error(
                'CTRL',
                'ERROR checking for remote commands.')
            self.add_to_main_log('CTRL: ERROR checking for remote commands.')

    def process_error_state(self):
        """Add error messages to the main log and the incident log and send a
        notification email. A pop-up alert message is shown in the Main
        Controls windows.
        """
        error_str = utils.Errors[self.error_state]
        utils.log_error(
            'CTRL',
            'ERROR (' + error_str + ')')
        self.add_to_main_log('CTRL: ' + error_str)
        self.add_to_incident_log('ERROR (' + error_str + ')')

        # Send notification e-mail
        if self.use_email_monitoring:
            status_msg1, status_msg2 = self.notifications.send_error_report(
                self.stack_name, self.slice_counter, self.error_state,
                self.recent_log_filename, self.vp_screenshot_filename)
            utils.log_info('CTRL', status_msg1)
            self.add_to_main_log('CTRL: ' + status_msg1)
            if status_msg2:
                utils.log_info('CTRL', status_msg2)
                self.add_to_main_log('CTRL: ' + status_msg2)
        # Send signal to Main Controls that there was an error.
        self.main_controls_trigger.transmit('ERROR PAUSE')

    def do_cut(self):
        """Carry out a single cut. This function is called at the end of a slice
        when the microtome is active and skipped if the SEM stage is active.
        During the cut cycle, all tiles in self.heuristic_af_queue are
        processed for the heuristic autofocus (if enabled).
        """
        old_stage_z_position = self.stage_z_position
        # Move to new Z position. stage_z_position stores Z position in microns.
        # slice_thickness is provided in nanometres!
        self.stage_z_position = (self.stage_z_position
                                 + (self.slice_thickness / 1000))
        utils.log_info(
            'STAGE',
            'Move to new Z: ' + '{0:.3f}'.format(self.stage_z_position))
        self.add_to_main_log(
            'STAGE: Move to new Z: ' + '{0:.3f}'.format(self.stage_z_position))
        self.microtome.move_stage_to_z(self.stage_z_position)
        # Show new Z position in Main Controls GUI
        self.main_controls_trigger.transmit('UPDATE Z')
        # Check if there were microtome errors
        self.error_state = self.microtome.error_state
        if self.error_state in [Error.dm_comm_response, Error.stage_z]:
            utils.log_error(
                'STAGE',
                'Problem during Z move. Trying again.')
            self.add_to_main_log(
                'STAGE: Problem during Z move. Trying again.')
            # Update incident log in Viewport with warning message
            self.add_to_incident_log(
                f'WARNING (Z move, error {self.error_state})')
            self.error_state = Error.none
            self.microtome.reset_error_state()
            # Try again after three-second delay
            sleep(3)
            self.microtome.move_stage_to_z(self.stage_z_position)
            self.main_controls_trigger.transmit('UPDATE Z')
            # Read new error_state
            self.error_state = self.microtome.error_state

        start_cut = time()
        if self.error_state == Error.none:
            utils.log_info(
                'KNIFE',
                'Cutting in progress ('
                + str(self.slice_thickness)
                + ' nm cutting thickness).')
            self.add_to_main_log('KNIFE: Cutting in progress ('
                                 + str(self.slice_thickness)
                                 + ' nm cutting thickness).')
            # Do the full cut cycle (near, cut, retract, clear)
            self.microtome.do_full_cut()
            # Process tiles for heuristic autofocus during cut
            if self.heuristic_af_queue:
                self.process_heuristic_af_queue()
                # Apply all corrections to tiles
                utils.log_info(
                    'CTRL',
                    'Applying corrections to WD/STIG.')
                self.add_to_main_log('CTRL: Applying corrections to WD/STIG.')
                self.autofocus.apply_heuristic_tile_corrections()
                # If there were jumps in WD/STIG above the allowed thresholds
                # (error 507), add message to the log.
                if self.error_state == Error.wd_stig_difference:
                    utils.log_error(
                        'CTRL',
                        'Error: Differences in WD/STIG too large.')
                    self.add_to_main_log(
                        'CTRL: Error: Differences in WD/STIG too large.')
            else:
                # TODO: why is that? all microtomes already wait for completion during do_full_cut.
                if not self.microtome.device_name == 'GCIB':
                    sleep(self.microtome.full_cut_duration)
                else:
                    utils.log_info('GCIB', 'Omitting post-cut sleep.')
                    self.add_to_main_log(
                        'GCIB: Omitting post-cut sleep.')
            cut_cycle_delay = self.microtome.check_cut_cycle_status()
            if cut_cycle_delay is not None and cut_cycle_delay > 0:
                utils.log_error(
                    'KNIFE',
                    f'Warning: Cut cycle took {cut_cycle_delay} s '
                    'longer than specified.')
                self.add_to_main_log(
                    f'KNIFE: Warning: Cut cycle took {cut_cycle_delay} s '
                    f'longer than specified.')
                self.add_to_incident_log(
                    f'WARNING (Cut cycle took {cut_cycle_delay} s too long.)')
            if self.microtome.error_state != Error.none:
                # Error state may be 507 at this point (after heuristic
                # adjustments), but an error during the cutting cycle is more
                # critical, so the error state will be overwritten with the
                # microtome's error state.
                self.error_state = self.microtome.error_state
                self.microtome.reset_error_state()
        if self.error_state != Error.none and self.error_state != Error.wd_stig_difference:
            utils.log_error('CTRL', 'Error during cut cycle.')
            utils.log_info(
                'STAGE',
                'Attempt to move back to previous Z: '
                f'{old_stage_z_position:.3f}')
            self.add_to_main_log('CTRL: Error during cut cycle.')
            # Try to move back to previous Z position
            self.add_to_main_log('STAGE: Attempt to move back to previous Z: '
                                 + '{0:.3f}'.format(old_stage_z_position))
            self.microtome.move_stage_to_z(old_stage_z_position)
            self.main_controls_trigger.transmit('UPDATE Z')
            self.microtome.reset_error_state()
            self.pause_acquisition(1)
        else:
            cut_duration = time() - start_cut
            if cut_duration < 60:
                cut_duration_str = f'{cut_duration:.1f} s'
            else:
                cut_duration_str = f'{cut_duration / 60:.2f} min'
            utils.log_info(
                'KNIFE',
                'Cut completed after ' + cut_duration_str)
            self.add_to_main_log(f'KNIFE: Cut completed after '
                                 f'{(time()-start_cut)/60:.2f} min.')
            self.slice_counter += 1
            self.total_z_diff += self.slice_thickness/1000
        sleep(1)

    def do_maintenance_moves(self, manual_run=False):
        """Move XY motors over the entire XY range."""
        if not manual_run:
            utils.log_info(
                'STAGE',
                'Carrying out XY stage maintenance moves.')
            self.add_to_main_log(
                'STAGE: Carrying out XY stage maintenance moves.')
        # First move to origin
        self.stage.move_to_xy((0, 0))
        # Show new stage coordinates in GUI
        self.main_controls_trigger.transmit('UPDATE XY')
        # Move to minimum X and Y coordinates
        self.stage.move_to_xy((self.stage.limits[0], self.stage.limits[2]))
        self.main_controls_trigger.transmit('UPDATE XY')
        # Move to maximum X and Y coordinates
        self.stage.move_to_xy((self.stage.limits[1], self.stage.limits[3]))
        self.main_controls_trigger.transmit('UPDATE XY')
        # Move back to the origin
        self.stage.move_to_xy((0, 0))
        self.main_controls_trigger.transmit('UPDATE XY')
        if not manual_run:
            utils.log_info(
                'STAGE',
                'XY stage maintenance moves completed.')
            self.add_to_main_log('STAGE: XY stage maintenance moves completed.')
            utils.log_info(
                'STAGE',
                'Next maintenance cycle after '
                f'{self.microtome.maintenance_move_interval} XY moves.')
            self.add_to_main_log(
                f'STAGE: Next maintenance cycle after '
                f'{self.microtome.maintenance_move_interval} XY moves.')
        if manual_run:
            # Signal to Main Controls that run is complete
            self.main_controls_trigger.transmit('MAINTENANCE FINISHED')

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
                self.error_state = Error.metadata_server
                self.pause_acquisition(1)
                utils.log_error('CTRL',
                                'Error sending "slice complete" '
                                'signal to server. ' + exc_str)
                self.add_to_main_log('CTRL: Error sending "slice complete" '
                                     'signal to server. ' + exc_str)

    def receive_msg_from_metadata_server(self):
        """Get commands or messages from the metadata server."""
        status, command, msg, exc_str = (
            self.notifications.read_server_message(
                self.metadata_project_name, self.stack_name))
        if status == 100:
            self.error_state = Error.metadata_server
            self.pause_acquisition(1)
            utils.log_error('CTRL: Error during get request '
                            'to server. ' + exc_str)
            self.add_to_main_log('CTRL: Error during get request '
                                 'to server. ' + exc_str)
        elif status == 200:
            if command in ['STOP', 'PAUSE']:
                self.pause_acquisition(1)
                utils.log_info(
                    'CTRL',
                    'Stop signal from metadata server received.')
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
                    utils.log_info(
                        'CTRL',
                        'Notification e-mail sent.')
                    self.add_to_main_log(
                        'CTRL: Notification e-mail sent.')
                else:
                    utils.log_error(
                        'CTRL',
                        'ERROR sending notification email: '
                        + error_msg)
                    self.add_to_main_log(
                        'CTRL: ERROR sending notification email: '
                        + error_msg)
                self.main_controls_trigger.transmit('REMOTE STOP')
            if command == 'SHOWMESSAGE':
                # Show message received from metadata server in GUI
                self.main_controls_trigger.transmit('SHOW MSG' + msg)
        else:
            utils.log_warning(
                'CTRL',
                'Unknown signal from metadata server received.')
            self.add_to_main_log(
                'CTRL: Unknown signal from metadata server received.')

    def save_viewport_screenshot(self):
        """Save a screenshot of the current contents of the Viewport window."""
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

    def process_heuristic_af_queue(self):
        """Process tiles in self.heuristic_af_queue for the heuristic autofocus.
        This method is called while the cut cycle is carried out. If processing
        takes less time than the cutting cycle, this method will wait for the
        extra time.
        """
        start_time = time()
        for tile_key in self.heuristic_af_queue:
            self.do_heuristic_autofocus(tile_key)
        end_time = time()
        time_elapsed = end_time - start_time
        self.heuristic_af_queue = []
        remaining_cutting_time = self.microtome.full_cut_duration - time_elapsed
        # only wait if not GCIB removal
        if (self.syscfg['device']['microtome'] != '6') and remaining_cutting_time > 0:
            sleep(remaining_cutting_time)

    def acquire_all_overviews(self):
        """Acquire all overview images with image inspection, debris detection,
        and error handling.
        """
        for ov_index in range(self.ovm.number_ov):
            if self.error_state != Error.none or self.pause_state == 1:
                break
            if not self.ovm[ov_index].active:
                utils.log_warning(
                    'CTRL',
                    f'OV {ov_index} inactive, skipped.')
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

                    relative_ov_save_path, ov_save_path, ov_accepted, rejected_by_user = (
                        self.acquire_overview(ov_index))

                    if (self.error_state in [Error.grab_incomplete, Error.image_load]
                        and not rejected_by_user):
                        # Image incomplete or cannot be loaded, try again
                        fail_counter += 1
                        if fail_counter < 3:
                            utils.log_error(
                                'CTRL',
                                f'Error {self.error_state} during '
                                'OV acquisition. Trying again.')
                            self.add_to_main_log(
                                f'CTRL: Error {self.error_state} during '
                                f'OV acquisition. Trying again.')
                        self.img_inspector.discard_last_ov(ov_index)
                        sleep(1)
                        if fail_counter == 3:
                            self.pause_acquisition(1)
                        else:
                            self.error_state = Error.none
                    elif self.error_state != Error.none:
                        self.pause_acquisition(1)
                        break
                    elif (not ov_accepted
                          and not self.pause_state == 1
                          and (self.use_debris_detection
                          or self.first_ov[ov_index])):
                        # Save image with debris
                        self.save_debris_image(ov_save_path, ov_index,
                                               sweep_counter)
                        self.img_inspector.discard_last_ov(ov_index)
                        # Try to remove debris
                        if sweep_counter < self.max_number_sweeps:
                            self.remove_debris()
                            sweep_counter += 1
                        elif sweep_counter == self.max_number_sweeps:
                            sweep_limit = True
                # ================== OV acquisition loop end ===================

                cycle_time_diff = (
                    self.sem.additional_cycle_time - self.sem.DEFAULT_DELAY)
                if cycle_time_diff > 0.15:
                    utils.log_warning(
                        'CTRL',
                        f'Warning: OV {ov_index} cycle time was '
                        f'{cycle_time_diff:.2f} s longer than '
                        'expected.')
                    self.add_to_main_log(
                        f'CTRL: Warning: OV {ov_index} cycle time was '
                        f'{cycle_time_diff:.2f} s longer than '
                        f'expected.')

                if (not ov_accepted
                        and self.error_state == Error.none
                        and not self.pause_state == 1):
                    if not self.continue_after_max_sweeps:
                        # Pause if maximum number of sweeps are reached
                        self.pause_acquisition(1)
                        self.error_state = Error.sweeps_max
                        utils.log_info(
                            'CTRL',
                            'Max. number of sweeps reached.')
                        self.add_to_main_log(
                            'CTRL: Max. number of sweeps reached.')
                    else:
                        # If user has set continue_after_max_sweeps to True
                        # continue acquisition, but let user know.
                        ov_accepted = True
                        utils.log_info(
                            'CTRL',
                            'CTRL: Max. number of sweeps reached, '
                            'but continuing as specified.')
                        self.add_to_main_log(
                            'CTRL: Max. number of sweeps reached, '
                            'but continuing as specified.')

                self.first_ov[ov_index] = False

                if ov_accepted:
                    # Write overview's name and position into imagelist_ov
                    self.register_accepted_ov(relative_ov_save_path, ov_index)
                    # Write stats and reslice to disk. If this does not work,
                    # show a warning in the log, but don't pause the acquisition
                    success, error_msg = (
                        self.img_inspector.save_ov_stats(
                            self.base_dir, ov_index,
                            self.slice_counter))
                    if not success:
                        utils.log_error(
                            'CTRL',
                            'Warning: Could not save OV mean/SD to disk: '
                            + error_msg)
                        self.add_to_main_log(
                            'CTRL: Warning: Could not save OV mean/SD to disk.')
                        self.add_to_main_log('CTRL: ' + error_msg)
                    success, error_msg = (
                        self.img_inspector.save_ov_reslice(
                            self.base_dir, ov_index))
                    if not success:
                        utils.log_error(
                            'CTRL',
                            'Warning: Could not save OV reslice to disk: '
                            + error_msg)
                        self.add_to_main_log(
                            'CTRL: Warning: Could not save OV reslice to disk.')
                        self.add_to_main_log('CTRL: ' + error_msg)
                    # Mirror the acquired overview
                    if self.use_mirror_drive:
                        self.mirror_files([ov_save_path])
                if sweep_counter > 0:
                    self.add_to_incident_log(
                        'Debris, ' + str(sweep_counter) + ' sweep(s)')
            else:
                utils.log_info(
                    'CTRL',
                    f'Skip OV {ov_index} (intervallic acquisition)')
                self.add_to_main_log(
                    'CTRL: Skip OV %d (intervallic acquisition)' % ov_index)

    def acquire_overview(self, ov_index, move_required=True):
        """Acquire an overview image with error handling and image inspection"""
        move_success = True
        ov_save_path = None
        ov_accepted = False
        rejected_by_user = False
        check_ov_acceptance = bool(self.cfg['overviews']['check_acceptance'].lower() == 'true')

        ov_stage_position = self.ovm[ov_index].centre_sx_sy
        # Move to OV stage coordinates if required (this method can be called
        # with move_required=False if the stage is already at the OV position.)
        if move_required:
            utils.log_info(
                'STAGE',
                'Moving to OV %d position.' % ov_index)
            self.add_to_main_log(
                'STAGE: Moving to OV %d position.' % ov_index)
            self.stage.move_to_xy(ov_stage_position)
            if self.stage.error_state != Error.none:
                utils.log_error(
                    'STAGE',
                    'Problem with XY move (error '
                    f'{self.stage.error_state}). Trying again.')
                self.add_to_main_log(
                    f'STAGE: Problem with XY move (error '
                    f'{self.stage.error_state}). Trying again.')
                # Update incident log in Viewport with warning message
                self.add_to_incident_log(
                    f'WARNING (XY move to OV{ov_index}, '
                    f'error {self.stage.error_state})')
                # Try again
                self.stage.reset_error_state()
                sleep(2)
                self.stage.move_to_xy(ov_stage_position)
                self.error_state = self.stage.error_state
                if self.error_state != Error.none:
                    utils.log_error(
                        'STAGE',
                        'Failed to move to OV position.')
                    self.add_to_main_log(
                        'STAGE: Failed to move to OV position.')
                    self.pause_acquisition(1)
                    self.stage.reset_error_state()
                    move_success = False
                else:
                    # Show new stage coordinates in GUI
                    self.main_controls_trigger.transmit('UPDATE XY')
        if move_success:
            # Set specified OV frame settings
            self.sem.apply_frame_settings(
                self.ovm[ov_index].frame_size_selector,
                self.ovm[ov_index].pixel_size,
                self.ovm[ov_index].dwell_time)
            # Use individual OV focus parameters if available
            # (if wd == 0, use current)
            ov_wd = self.ovm[ov_index].wd_stig_xy[0]
            if ov_wd > 0:
                self.sem.set_wd(ov_wd)
                stig_x, stig_y = self.ovm[ov_index].wd_stig_xy[1:3]
                self.sem.set_stig_xy(stig_x, stig_y)
                utils.log_info(
                    'SEM',
                    'Using specified '
                    + utils.format_wd_stig(ov_wd, stig_x, stig_y))
                self.add_to_main_log(
                    'SEM: Using specified '
                    + utils.format_wd_stig(ov_wd, stig_x, stig_y))

            # Path and filename of overview image to be acquired
            relative_ov_save_path = utils.ov_relative_save_path(self.stack_name, ov_index, self.slice_counter)
            ov_save_path = os.path.join(self.base_dir, relative_ov_save_path)

            utils.log_info(
                'SEM',
                'Acquiring OV at '
                f'X:{ov_stage_position[0]:.3f}, '
                f'Y:{ov_stage_position[1]:.3f}')
            self.add_to_main_log(
                'SEM: Acquiring OV at X:'
                + '{0:.3f}'.format(ov_stage_position[0])
                + ', Y:' + '{0:.3f}'.format(ov_stage_position[1]))

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
                    utils.log_info(
                        'CTRL',
                        f'OV: M:{mean:.2f}, '
                        f'SD:{stddev:.2f}')
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
                    self.error_state = Error.image_load
                    ov_accepted = False
                    # Don't pause yet, try again in OV acquisition loop.
                elif grab_incomplete and check_ov_acceptance:
                    self.error_state = Error.grab_incomplete
                    ov_accepted = False
                    # Don't pause yet, try again in OV acquisition loop.
                elif self.monitor_images and not range_test_passed and check_ov_acceptance:
                    ov_accepted = False
                    self.error_state = Error.overview_image    # OV image error
                    self.pause_acquisition(1)
                    utils.log_error(
                        'CTRL',
                        'OV outside of mean/stddev limits.')
                    self.add_to_main_log(
                        'CTRL: OV outside of mean/stddev limits. ')
                else:
                    # OV has passed all tests, but now check for debris
                    ov_accepted = True
                    # do not check if using GCIB
                    if self.first_ov[ov_index] and not self.syscfg['device']['microtome'] == '6':
                        self.main_controls_trigger.transmit(
                            'ASK DEBRIS FIRST OV' + str(ov_index))
                        # The command above causes a message box to be displayed
                        # in Main Controls. The user is asked if the first
                        # overview image acquired is clean and of good quality.
                        # user_reply (None by default) is updated when a
                        # response is received:
                        # "Image is fine" button clicked:    0
                        # "There is debris" button clicked:  1
                        # "Abort" button clicked:            2
                        while self.user_reply is None:
                            sleep(0.1)
                        ov_accepted = (self.user_reply == 0)
                        if self.user_reply == 2:
                            self.pause_acquisition(1)
                        self.user_reply = None

                    elif self.use_debris_detection:
                        # Detect potential debris
                        debris_detected, msg = self.img_inspector.detect_debris(
                            ov_index)
                        utils.log_info('CTRL', msg)
                        self.add_to_main_log('CTRL: ' + msg)
                        if debris_detected:
                            ov_accepted = False
                            # If 'Ask User' mode is active, ask user to
                            # confirm that debris was detected correctly.
                            if self.ask_user_mode:
                                self.main_controls_trigger.transmit(
                                    'ASK DEBRIS CONFIRMATION' + str(ov_index))
                                while self.user_reply is None:
                                    sleep(0.1)
                                # user_reply (None by default) is updated when a
                                # response is received:
                                # "Yes, there is debris" button clicked:  0
                                # "No debris, continue" button clicked:   1
                                # "Abort" button clicked:                 2
                                ov_accepted = (self.user_reply == 1)
                                if self.user_reply == 2:
                                    self.pause_acquisition(1)
                                self.user_reply = None
            else:
                utils.log_error(
                    'SEM',
                    'OV acquisition failure.')
                self.add_to_main_log('SEM: OV acquisition failure.')
                self.error_state = Error.grab_image
                self.pause_acquisition(1)
                ov_accepted = False

        # Check for "Ask User" override
        if self.ask_user_mode and self.error_state in [Error.grab_incomplete, Error.overview_image]:
            self.main_controls_trigger.transmit(
                'ASK IMAGE ERROR OVERRIDE')
            while self.user_reply is None:
                sleep(0.1)
            if self.user_reply == QMessageBox.Yes:
                # Proceed anyway, reset error state and accept OV
                self.reset_error_state()
                ov_accepted = True
            else:
                rejected_by_user = True
            self.user_reply = None

        return relative_ov_save_path, ov_save_path, ov_accepted, rejected_by_user

    def remove_debris(self):
        """Try to remove detected debris by sweeping the surface. Microtome must
        be active for this function.
        """
        utils.log_info(
            'KNIFE',
            'Sweeping to remove debris.')
        self.add_to_main_log('KNIFE: Sweeping to remove debris.')
        self.microtome.do_sweep(self.stage_z_position)
        if self.microtome.error_state != Error.none:
            self.microtome.reset_error_state()
            utils.log_error(
                'KNIFE',
                'Problem during sweep. Trying again.')
            self.add_to_main_log('KNIFE: Problem during sweep. Trying again.')
            self.add_to_incident_log('WARNING (Problem during sweep)')
            # Trying again after 3 sec
            sleep(3)
            self.microtome.do_sweep(self.stage_z_position)
            # Check if there was again an error during sweeping
            if self.microtome.error_state != Error.none:
                self.microtome.reset_error_state()
                self.error_state = Error.sweeping
                self.pause_acquisition(1)
                utils.log_error(
                    'KNIFE',
                    'Error during second sweep attempt.')
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
            utils.log_error(
                'CTRL',
                'Warning: Unable to save rejected OV image, ' + str(e))
            self.add_to_main_log(
                'CTRL: Warning: Unable to save rejected OV image, ' + str(e))
            self.add_to_incident_log(
                'WARNING: Unable to save rejected OV image.')
        if self.use_mirror_drive:
            self.mirror_files([debris_save_path])

    def acquire_all_grids(self):
        """Acquire all grids that are active, with error handling."""

        # Use (SmartSEM) autofocus/autostig (method 0) on this slice for the
        # grid acquisition depending on whether MagC mode is active, and
        # on the slice number and current autofocus settings.
        # Perform mapfost also prior to first removal.
        if self.magc_mode or (self.use_autofocus and self.autofocus.method == 3):
            self.autofocus_stig_current_slice = True, True
        else:
            self.autofocus_stig_current_slice = (
                self.autofocus.current_slice_active(self.slice_counter))

        # For heuristic autofocus (method 1), set the deltas for this slice
        # to focus slightly up (smaller working distance for even slice
        # counter) or down (larger working distance for odd slice counter).
        if self.use_autofocus and self.autofocus.method == 1:
            sign = 1 if self.slice_counter % 2 else -1
            self.wd_delta = sign * self.autofocus.wd_delta
            self.stig_x_delta = sign * self.autofocus.stig_x_delta
            self.stig_y_delta = sign * self.autofocus.stig_y_delta
            utils.log_info('CTRL', 'Heuristic autofocus active.')
            utils.log_info(
                'CTRL',
                f'DELTA_WD: {(self.wd_delta * 1000):+.4f}, '
                f'DELTA_STIG_X: {self.stig_x_delta:+.2f}, '
                f'DELTA_STIG_Y: {self.stig_x_delta:+.2f}')
            self.add_to_main_log('CTRL: Heuristic autofocus active.')
            self.add_to_main_log(
                'CTRL: DELTA_WD: {0:+.4f}'.format(self.wd_delta * 1000)
                + ', DELTA_STIG_X: {0:+.2f}'.format(self.stig_x_delta)
                + ', DELTA_STIG_Y: {0:+.2f}'.format(self.stig_x_delta))
        # fit a plane for
        if self.autofocus.tracking_mode == 3:  # global aberration gradient
            for grid_index in range(self.gm.number_grids):
                if self.error_state != Error.none or self.pause_state == 1:
                    break
                self.do_autofocus_before_grid_acq(grid_index)
            self.gm.fit_apply_aberration_gradient()
        for grid_index in range(self.gm.number_grids):
            if self.error_state != Error.none or self.pause_state == 1:
                break
            if not self.gm[grid_index].active:
                utils.log_info(
                    'CTRL',
                    f'Grid {grid_index} inactive, skipped.')
                self.add_to_main_log(
                    f'CTRL: Grid {grid_index} inactive, skipped.')
                continue
            if self.gm[grid_index].slice_active(self.slice_counter):
                num_active_tiles = self.gm[grid_index].number_active_tiles()
                utils.log_info('CTRL',
                               f'Grid {grid_index}, '
                               f'number of active tiles: '
                               f'{num_active_tiles}')
                self.add_to_main_log('CTRL: Grid ' + str(grid_index)
                                     + ', number of active tiles: '
                                     + str(num_active_tiles))

                # In MagC mode, use the grid index for autostig delay
                if self.magc_mode:
                    self.autofocus_stig_current_slice = (
                        self.autofocus_stig_current_slice[0],
                        (grid_index % self.autofocus.autostig_delay == 0))

                if (num_active_tiles > 0
                        and not self.pause_state == 1
                        and self.error_state == Error.none):
                    if grid_index in self.grids_acquired:
                        utils.log_info(
                            'CTRL',
                            f'Grid {grid_index} already acquired. '
                            f'Skipping.')
                        self.add_to_main_log(
                            f'CTRL: Grid {grid_index} already acquired. '
                            f'Skipping.')
                    elif (self.magc_mode
                          and grid_index not in self.gm.magc_checked_sections):
                        utils.log_info(
                            'CTRL',
                            f'Grid {grid_index} not checked. Skipping.')
                        self.add_to_main_log(
                            f'CTRL: Grid {grid_index} not checked. Skipping.')
                    else:
                        # Do autofocus on non-active tiles before grid acq
                        if (self.use_autofocus
                            and self.autofocus.method in [0, 3]  # zeiss or mapfost
                            and (self.autofocus_stig_current_slice[0]
                            or self.autofocus_stig_current_slice[1])
                            and not self.autofocus.tracking_mode == 3  # in that case these tiles have been visited already
                        ):
                            self.do_autofocus_before_grid_acq(grid_index)
                        # Adjust working distances and stigmation parameters
                        # for this grid with autofocus corrections
                        self.do_autofocus_adjustments(grid_index)
                        # Now acquire the grid (only active tiles, with
                        # image inspection and error handling, and with
                        # autofocus on reference tiles)
                        self.acquire_grid(grid_index)
            else:
                utils.log_info(
                    'CTRL',
                    f'Skip grid {grid_index} (intervallic acquisition)')
                self.add_to_main_log(
                    'CTRL: Skip grid %d (intervallic acquisition)' % grid_index)

        # Reset the interruption point (from the previous run) if the affected
        # grid was acquired
        if (self.pause_state != 1
                and self.acq_interrupted
                and self.acq_interrupted_at[0] in self.grids_acquired):
            self.interrupted_at = []
            self.acq_interrupted = False

        # If there was no (new) interuption, reset self.grids_acquired
        if not self.acq_interrupted:
            self.grids_acquired = []

    def acquire_grid(self, grid_index):
        """Acquire all active tiles of grid specified by grid_index"""

        # Get current active tiles (using list() to get a copy).
        # If the user changes the active tiles in this grid while the grid
        # is being acquired, the changes will take effect the next time
        # the grid is acquired.
        active_tiles = list(self.gm[grid_index].active_tiles)

        # Focus parameters must be adjusted for each tile individually if focus
        # gradient is active or if autofocus/tracked focus is used with
        # "track all" or "best fit" option.
        # Otherwise wd_default, stig_x_default, and stig_y_default are used.
        adjust_wd_stig = (
            self.gm[grid_index].use_wd_gradient
            or (self.use_autofocus and self.autofocus.tracking_mode < 2))
        self.tile_wd, self.tile_stig_x, self.tile_stig_y = 0, 0, 0

        # The grid's acquisition settings will be applied before the first
        # active tile in the grid is acquired. They remain unchanged for
        # all other tiles in the grid (adjust_acq_settings set to False).
        adjust_acq_settings = True

        if self.pause_state != 1:
            utils.log_info(
                'CTRL',
                f'Starting acquisition of active tiles in grid {grid_index}')
            self.add_to_main_log(
                'CTRL: Starting acquisition of active tiles in grid %d'
                % grid_index)

            if self.magc_mode:
                # In MagC mode: Track grid being acquired in Viewport
                grid_centre_d = self.gm[grid_index].centre_dx_dy
                self.cs.set_vp_centre_d(grid_centre_d)
                self.main_controls_trigger.transmit('DRAW VP')
                self.main_controls_trigger.transmit(
                    'MAGC SET SECTION STATE GUI-'
                    + str(grid_index)
                    + '-acquiring')

            if self.acq_interrupted:
                # Remove tiles that are no longer active from
                # tiles_acquired list
                acq_tmp = list(self.tiles_acquired)
                for tile in acq_tmp:
                    if not (tile in active_tiles):
                        self.tiles_acquired.remove(tile)

            # Set WD and stig settings for the current grid
            # and lock the settings unless individual adjustment is required
            if not adjust_wd_stig:
                # MagC: WD/stig is kept at the current values from grid to grid
                if not self.magc_mode:
                    self.set_default_wd_stig()
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
                tile_skipped = False
                tile_id = str(grid_index) + '.' + str(tile_index)

                # Acquire the current tile
                while not (tile_accepted or tile_skipped) and fail_counter < 2:

                    (tile_img, relative_save_path, save_path,
                     tile_accepted, tile_skipped, tile_selected,
                     rejected_by_user) = (
                        self.acquire_tile(grid_index, tile_index,
                                          adjust_wd_stig, adjust_acq_settings))
                    if not tile_skipped:
                        adjust_acq_settings = False

                    if (self.error_state in [Error.grab_image, Error.grab_incomplete, Error.frame_frozen, Error.image_load]
                            and not rejected_by_user):
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
                                utils.log_error(
                                    'CTRL',
                                    'Tile image file could not be '
                                    'removed: ' + str(e))
                                self.add_to_main_log(
                                    'CTRL: Tile image file could not be '
                                    'removed: ' + str(e))
                            # TODO: Try to solve frozen frame problem:
                            # if self.error_state == Error.frame_frozen:
                            #    self.handle_frozen_frame(grid_index)
                            utils.log_warning(
                                'SEM',
                                'Trying again to image tile.')
                            self.add_to_main_log(
                                'SEM: Trying again to image tile.')
                            # Reset error state
                            self.error_state = Error.none
                    elif self.error_state != Error.none:
                        self.pause_acquisition(1)
                        break
                # End of tile aquisition while loop

                if tile_accepted and tile_selected and not tile_skipped:
                    # Write tile's name and position into imagelist
                    self.register_accepted_tile(relative_save_path,
                                                grid_index, tile_index)
                    # Save stats and reslice
                    success, error_msg = self.img_inspector.save_tile_stats(
                        self.base_dir, grid_index, tile_index,
                        self.slice_counter)
                    if not success:
                        utils.log_error(
                            'CTRL',
                            'Warning: Could not save tile mean and SD '
                            'to disk: ' + error_msg)
                        self.add_to_main_log(
                            'CTRL: Warning: Could not save tile mean and SD '
                            'to disk.')
                        self.add_to_main_log(
                            'CTRL: ' + error_msg)
                    success, error_msg = self.img_inspector.save_tile_reslice(
                        self.base_dir, grid_index, tile_index)
                    if not success:
                        utils.log_error(
                            'CTRL',
                            'Warning: Could not save tile reslice to '
                            'disk:' + utils.log_error())
                        self.add_to_main_log(
                            'CTRL: Warning: Could not save tile reslice to '
                            'disk.')
                        self.add_to_main_log(
                            'CTRL: ' + error_msg)

                    # If heuristic autofocus is enabled and tile is selected as
                    # a reference tile, prepare tile for processing:
                    if (self.use_autofocus and self.autofocus.method == 1
                        and self.gm[grid_index][tile_index].autofocus_active):
                        tile_key = str(grid_index) + '.' + str(tile_index)
                        self.autofocus.prepare_tile_for_heuristic_af(
                            tile_img, tile_key)
                        self.heuristic_af_queue.append(tile_key)
                        del tile_img

                elif (not tile_selected
                      and not tile_skipped
                      and self.error_state == Error.none):
                    utils.log_info(
                        'CTRL',
                        f'Tile {tile_id} was discarded by image '
                        f'inspector.')
                    self.add_to_main_log(
                        f'CTRL: Tile {tile_id} was discarded by image '
                        f'inspector.')
                    # Delete file
                    try:
                        os.remove(save_path)
                    except Exception as e:
                        utils.log_error(
                            'CTRL',
                            'Tile image file could not be deleted: '
                            + str(e))
                        self.add_to_main_log(
                            'CTRL: Tile image file could not be deleted: '
                            + str(e))
                # Save current position if acquisition was paused by user
                # or interrupted by an error.
                if self.pause_state == 1:
                    self.set_interruption_point(grid_index, tile_index)
                    break
            # ================= End of tile acquisition loop ===================

            cycle_time_diff = (self.sem.additional_cycle_time
                               - self.sem.DEFAULT_DELAY)
            if cycle_time_diff > 0.15:
                utils.log_warning(
                    'CTRL',
                    f'Warning: Grid {grid_index} tile cycle time was '
                    f'{cycle_time_diff:.2f} s longer than expected.')
                self.add_to_main_log(
                    f'CTRL: Warning: Grid {grid_index} tile cycle time was '
                    f'{cycle_time_diff:.2f} s longer than expected.')

            # Show the average durations for grabbing, inspecting and mirroring
            # tiles in the current grid
            if self.tile_grab_durations and self.tile_inspect_durations:
                utils.log_info(
                    'CTRL',
                    f'Grid {grid_index}: avg. tile grab duration: '
                    f'{mean(self.tile_grab_durations):.1f} s '
                    f'(cycle time: {self.sem.current_cycle_time:.1f})')
                utils.log_info(
                    'CTRL',
                    f'Grid {grid_index}: avg. tile inspect '
                    f'duration: {mean(self.tile_inspect_durations):.1f} s')
                self.add_to_main_log(
                    f'CTRL: Grid {grid_index}: avg. tile grab duration: '
                    f'{mean(self.tile_grab_durations):.1f} s '
                    f'(cycle time: {self.sem.current_cycle_time:.1f})')
                self.add_to_main_log(
                    f'CTRL: Grid {grid_index}: avg. tile inspect '
                    f'duration: {mean(self.tile_inspect_durations):.1f} s')
            if self.use_mirror_drive and self.tile_mirror_durations:
                utils.log_info(
                    'CTRL',
                    f'Grid {grid_index}: avg. time to copy tile to '
                    f'mirror drive: {mean(self.tile_mirror_durations):.1f} s')
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
                        'MAGC SET SECTION STATE GUI-'
                        + str(grid_index)
                        + '-acquired')

    def acquire_tile(self, grid_index, tile_index,
                     adjust_wd_stig=False, adjust_acq_settings=False):
        """Acquire the specified tile with error handling and inspection.
        If adjust_wd_stig is True, the working distance and stigmation
        parameters will be adjusted for this tile. If adjust_acq_settings
        is True, the pixel size, dwell time and frame size will be adjusted
        according to the settings of the grid at grid_index.
        """

        tile_img = None  # NumPy array of acquired image (from img_inspector)
        tile_accepted = False  # if True: tile passed img_inspector checks
        tile_selected = False  # if True: tile selected to be saved to disk
        tile_skipped = False   # if True: tile skipped because it was already
                               # acquired or marked as acquired
        rejected_by_user = False   # if True: rejected by user (Ask user mode)

        relative_save_path = utils.tile_relative_save_path(
            self.stack_name, grid_index, tile_index, self.slice_counter)
        save_path = os.path.join(self.base_dir, relative_save_path)
        tile_id = str(grid_index) + '.' + str(tile_index)

        # If tile is at the interruption point and not in the list
        # self.tiles_acquired, retake it even if the image file already exists.
        retake_img = (
            (self.acq_interrupted_at == [grid_index, tile_index])
            and not (tile_index in self.tiles_acquired))

        # Skip the tile if it is in the interrupted grid and already listed
        # as acquired.
        if (self.acq_interrupted
                and self.acq_interrupted_at[0] == grid_index
                and tile_index in self.tiles_acquired):
            tile_skipped = True
            utils.log_info(
                'CTRL',
                f'Tile {tile_id} already acquired. Skipping.')
            self.add_to_main_log(
                'CTRL: Tile %s already acquired. Skipping.' % tile_id)

        if not tile_skipped:
            if not os.path.isfile(save_path) or retake_img:
                # If current tile has different focus settings from previous
                # tile, adjust working distance and stigmation for this tile
                if adjust_wd_stig and not self.magc_mode:
                    new_wd = (self.gm[grid_index][tile_index].wd
                              + self.wd_delta)
                    new_stig_x = (self.gm[grid_index][tile_index].stig_xy[0]
                                  + self.stig_x_delta)
                    new_stig_y = (self.gm[grid_index][tile_index].stig_xy[1]
                                  + self.stig_y_delta)
                    if ((new_wd != self.tile_wd)
                        or (new_stig_x != self.tile_stig_x)
                        or (new_stig_y != self.tile_stig_y)):
                        # Adjust and show new parameters in the main log
                        self.sem.set_wd(new_wd)
                        self.sem.set_stig_xy(new_stig_x, new_stig_y)
                        utils.log_info(
                            'SEM',
                            'Adjusted '
                            + utils.format_wd_stig(
                                new_wd, new_stig_x, new_stig_y))
                        self.add_to_main_log(
                            'SEM: Adjusted '
                            + utils.format_wd_stig(
                                new_wd, new_stig_x, new_stig_y))
                        self.tile_wd = new_wd
                        self.tile_stig_x = new_stig_x
                        self.tile_stig_y = new_stig_y

                # Read target coordinates for current tile
                stage_x, stage_y = self.gm[grid_index][tile_index].sx_sy
                # Move to that position
                utils.log_info(
                    'STAGE',
                    f'Moving to position of tile {tile_id}')
                self.add_to_main_log(
                    'STAGE: Moving to position of tile %s' % tile_id)
                self.stage.move_to_xy((stage_x, stage_y))
                # The move function waits for the motor move duration and the
                # specified stage move wait interval.
                # Check if there were microtome problems:
                # If yes, try one more time before pausing acquisition.
                if self.stage.error_state != Error.none:
                    utils.log_error(
                        'STAGE',
                        'Problem with XY move (error '
                        f'{self.stage.error_state}). Trying again.')
                    self.add_to_main_log(
                        f'STAGE: Problem with XY move (error '
                        f'{self.stage.error_state}). Trying again.')
                    # Add warning to incident log
                    self.add_to_incident_log(f'WARNING (XY move to {tile_id}, '
                                             f'error {self.stage.error_state})')
                    self.stage.reset_error_state()
                    sleep(2)
                    # Try to move to tile position again
                    utils.log_info(
                        'STAGE',
                        'Moving to position of tile ' + tile_id)
                    self.add_to_main_log(
                        'STAGE: Moving to position of tile ' + tile_id)
                    self.stage.move_to_xy((stage_x, stage_y))
                    # Check again if there is an error
                    self.error_state = self.stage.error_state
                    self.stage.reset_error_state()
                    # If yes, pause stack
                    if self.error_state != Error.none:
                        utils.log_error(
                            'STAGE',
                            'XY move failed. Stack will be paused.')
                        self.add_to_main_log(
                            'STAGE: XY move failed. Stack will be paused.')
            else:
                # If tile image file already exists and tile not supposed to
                # be reacquired (retake_img == False):
                # Pause because risk of overwriting data!
                self.error_state = Error.file_overwrite
                utils.log_warning(
                    'CTRL',
                    f'Tile {tile_id}: Image file already exists!')
                self.add_to_main_log(
                    'CTRL: Tile %s: Image file already exists!' %tile_id)

        # Proceed if no error has ocurred and tile not skipped:
        if self.error_state == Error.none and not tile_skipped:

            # Show updated XY stage coordinates in Main Controls GUI
            self.main_controls_trigger.transmit('UPDATE XY')

            # Call autofocus routine (method 0, SmartSEM) on current tile
            # if enabled and tile selected on this slice
            if (self.use_autofocus and self.autofocus.method in [0, 3]
                    and self.gm[grid_index][tile_index].autofocus_active
                    and (self.autofocus_stig_current_slice[0] or
                         self.autofocus_stig_current_slice[1])):
                do_move = False  # already at tile stage position
                self.do_autofocus(*self.autofocus_stig_current_slice,
                                  do_move, grid_index, tile_index)
                # The autofocus routine changes the acquisition settings.
                # They must be restored to the settings for the current grid.
                adjust_acq_settings = True
                # For tracking mode 0: Adjust wd/stig of other tiles
                if self.error_state == Error.none and self.autofocus.tracking_mode == 0:
                    self.autofocus.approximate_wd_stig_in_grid(grid_index)
                    self.main_controls_trigger.transmit('DRAW VP')

            if adjust_acq_settings:
                # Switch to specified acquisition settings of the current grid
                self.sem.apply_frame_settings(
                    self.gm[grid_index].frame_size_selector,
                    self.gm[grid_index].pixel_size,
                    self.gm[grid_index].dwell_time)

                # Delay necessary for Gemini? (change of mag)
                sleep(0.2)
                # Lock magnification: If user accidentally changes the mag
                # during the grid acquisition, SBEMimage will detect and
                # undo the change.
                self.lock_mag()

            # Check mag if locked
            if self.mag_locked and not self.error_state in [Error.autofocus_smartsem, Error.autofocus_heuristic, Error.wd_stig_difference]:
                self.check_locked_mag()
            # Check focus if locked
            if (self.wd_stig_locked
                    and not self.error_state in [Error.autofocus_smartsem, Error.autofocus_heuristic, Error.wd_stig_difference]):
                self.check_locked_wd_stig()

            # After all preliminary checks complete, now acquire the frame!
            # (Even if error has been detected. May be helpful.)
            utils.log_info(
                'SEM',
                f'Acquiring tile at X:{stage_x:.3f}, '
                f'Y:{stage_y:.3f}')
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
                utils.log_error(
                    'SEM',
                    'Warning: Grab overhead too large '
                    f'({grab_overhead:.1f} s).')
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
                    utils.log_warning(
                        'CTRL',
                        'Warning: Copying tile to mirror drive took too '
                        f'long ({mirror_duration:.1f} s).')
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
                    utils.log_warning(
                        'CTRL',
                        'Warning: Inspecting tile took too '
                        f'long ({inspect_duration:.1f} s).')
                    self.add_to_main_log(
                        f'CTRL: Warning: Inspecting tile took too '
                        f'long ({inspect_duration:.1f} s).')

                if not load_error:
                    # Assume tile_accepted, check against various errors below
                    tile_accepted = True
                    utils.log_info('CTRL',
                                   f'Tile {tile_id}: '
                                   f'M:{mean:.2f}, '
                                   f'SD:{stddev:.2f}')
                    self.add_to_main_log('CTRL: Tile ' + tile_id
                                         + ': M:' + '{0:.2f}'.format(mean)
                                         + ', SD:' + '{0:.2f}'.format(stddev))
                    # New preview available, show it (if tile previews active)
                    self.main_controls_trigger.transmit('DRAW VP')

                    if self.error_state in [Error.autofocus_smartsem, Error.autofocus_heuristic, Error.wd_stig_difference]:
                        # Don't accept tile if autofocus error has ocurred
                        tile_accepted = False
                    else:
                        # Check for frozen or incomplete frames
                        if frozen_frame_error:
                            tile_accepted = False
                            self.error_state = Error.frame_frozen
                            utils.log_error(
                                'SEM',
                                'Tile ' + tile_id
                                + ': SmartSEM frozen frame error!')
                            self.add_to_main_log(
                                'SEM: Tile ' + tile_id
                                + ': SmartSEM frozen frame error!')
                        elif grab_incomplete:
                            tile_accepted = False
                            self.error_state = Error.grab_incomplete
                            utils.log_error(
                                'SEM',
                                'Tile ' + tile_id
                                + ': SmartSEM grab incomplete error!')
                            self.add_to_main_log(
                                'SEM: Tile ' + tile_id
                                + ': SmartSEM grab incomplete error!')
                        elif self.monitor_images:
                            # Two additional checks if 'image monitoring'
                            # option is active
                            if not range_test_passed:
                                tile_accepted = False
                                self.error_state = Error.tile_image_range
                                utils.log_error(
                                    'CTRL',
                                    'Tile outside of permitted mean/SD '
                                    'range!')
                                self.add_to_main_log(
                                    'CTRL: Tile outside of permitted mean/SD '
                                    'range!')
                            elif (slice_by_slice_test_passed is not None
                                  and not slice_by_slice_test_passed):
                                tile_accepted = False
                                self.error_state = Error.tile_image_compare
                                utils.log_error(
                                    'CTRL',
                                    'Tile above mean/SD slice-by-slice '
                                    'thresholds.')
                                self.add_to_main_log(
                                    'CTRL: Tile above mean/SD slice-by-slice '
                                    'thresholds.')
                else:
                    # Tile image file could not be loaded
                    utils.log_error(
                        'CTRL',
                        'Error: Failed to load tile '
                        'image file.')
                    self.add_to_main_log('CTRL: Error: Failed to load tile '
                                         'image file.')
                    self.error_state = Error.image_load
            else:
                # File was not saved
                utils.log_error(
                    'SEM',
                    'Tile image acquisition failure.')
                self.add_to_main_log('SEM: Tile image acquisition failure. ')
                self.error_state = Error.grab_image

        # Check for "Ask User" override
        if self.ask_user_mode and self.error_state in [Error.grab_incomplete, Error.frame_frozen, Error.tile_image_range, Error.tile_image_compare]:
            self.main_controls_trigger.transmit('ASK IMAGE ERROR OVERRIDE')
            while self.user_reply is None:
                sleep(0.1)
            if self.user_reply == QMessageBox.Yes:
                # Follow user's request, reset error state and accept tile
                self.error_state = Error.none
                tile_accepted = True
            else:
                rejected_by_user = True
            self.user_reply = None

        return (tile_img, relative_save_path, save_path,
                tile_accepted, tile_skipped, tile_selected, rejected_by_user)

    def register_accepted_tile(self, relative_save_path,
                               grid_index, tile_index):
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
        tile_width, tile_height = self.gm[grid_index].frame_size
        tile_metadata = {
            'tileid': tile_id,
            'timestamp': timestamp,
            'filename': relative_save_path.replace('\\', '/'),
            'tile_width': tile_width,
            'tile_height': tile_height,
            'wd_stig_xy': [self.gm[grid_index][tile_index].wd,
                           *self.gm[grid_index][tile_index].stig_xy],
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
                self.error_state = Error.metadata_server
                self.pause_acquisition(1)
                utils.log_error('CTRL',
                                'Error sending tile metadata '
                                'to server. ' + exc_str)
                self.add_to_main_log('CTRL: Error sending tile metadata '
                                     'to server. ' + exc_str)

    def register_accepted_ov(self, relative_save_path, ov_index):
        """Register the overview image in the overview image list file and the metadata
        file. Send metadata to remote server.
        """
        timestamp = int(time())
        ov_id = utils.overview_id(ov_index, self.slice_counter)
        global_x, global_y = (self.ovm.overview_position_for_registration(ov_index))
        global_z = int(self.total_z_diff * 1000)
        overviewinfo_str = (relative_save_path + ';'
                        + str(global_x) + ';'
                        + str(global_y) + ';'
                        + str(global_z) + ';'
                        + str(self.slice_counter) + '\n')
        self.imagelist_ov_file.write(overviewinfo_str)
        # Write the same information to the ov_imagelist on the mirror drive
        if self.use_mirror_drive:
            self.mirror_imagelist_ov_file.write(overviewinfo_str)
        ov_width, ov_height = self.ovm[ov_index].frame_size
        ov_metadata = {
            'ov_id': ov_id,
            'timestamp': timestamp,
            'filename': relative_save_path.replace('\\', '/'),
            'ov_width': ov_width,
            'ov_height': ov_height,
            'wd_stig_xy': self.ovm[ov_index].wd_stig_xy,
            'glob_x': global_x,
            'glob_y': global_y,
            'glob_z': global_z,
            'slice_counter': self.slice_counter}
        self.metadata_file.write('OVERVIEW: ' + str(ov_metadata) + '\n')
        # Server notification
        if self.send_metadata:
            status, exc_str = self.notifications.send_ov_metadata(
                self.metadata_project_name, self.stack_name, ov_metadata)
            if status == 100:
                self.error_state = Error.metadata_server
                self.pause_acquisition(1)
                utils.log_error('CTRL',
                                'Error sending overview metadata '
                                'to server. ' + exc_str)
                self.add_to_main_log('CTRL: Error sending overview metadata '
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
            utils.log_error(
                'CTRL',
                'Warning: Unable to save rejected tile image, ' + str(e))
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

    def do_autofocus(self, do_focus, do_stig, do_move, grid_index, tile_index):
        """Run SmartSEM autofocus at current stage position if do_move == False,
        otherwise move to grid_index.tile_index position beforehand.
        """
        if do_move:
            # Read target coordinates for specified tile
            stage_x, stage_y = self.gm[grid_index][tile_index].sx_sy
            # Move to that position
            utils.log_info(
                'STAGE',
                'Moving to position of tile '
                + str(grid_index) + '.' + str(tile_index) + ' for autofocus')
            self.add_to_main_log(
                'STAGE: Moving to position of tile '
                + str(grid_index) + '.' + str(tile_index) + ' for autofocus')
            self.stage.move_to_xy((stage_x, stage_y))
            if self.stage.error_state != Error.none:
                self.stage.reset_error_state()
                utils.log_error(
                    'STAGE',
                    'Problem with XY move. Trying again.')
                self.add_to_main_log(
                    'STAGE: Problem with XY move. Trying again.')
                self.add_to_incident_log('WARNING (Problem with XY stage move)')
                sleep(2)
                # Try to move to tile position again
                utils.log_info(
                    'STAGE',
                    'Moving to position of tile '
                    + str(grid_index) + '.' + str(tile_index))
                self.add_to_main_log(
                    'STAGE: Moving to position of tile '
                    + str(grid_index) + '.' + str(tile_index))
                self.stage.move_to_xy((stage_x, stage_y))
                # Check again if there is an error
                self.error_state = self.stage.error_state
                self.stage.reset_error_state()
                # If yes, pause stack
                if self.error_state != Error.none:
                    utils.log_error(
                        'STAGE',
                        'XY move for autofocus failed.')
                    self.add_to_main_log('STAGE: XY move for autofocus failed.')
        if self.error_state != Error.none or not (do_focus or do_stig):
            return
        if do_focus and do_stig:
            af_type = '(focus+stig)'
        elif do_focus:
            af_type = '(focus only)'
        elif do_stig:
            af_type = '(stig only)'
        wd = self.sem.get_wd()
        sx, sy = self.sem.get_stig_xy()
        # added to adjust WD and stig values to tiles which are just used for autofocus!
        tile_wd = self.gm[grid_index][tile_index].wd
        tile_stig_x = self.gm[grid_index][tile_index].stig_xy[0]
        tile_stig_y = self.gm[grid_index][tile_index].stig_xy[1]
        if (tile_wd != wd) or (tile_stig_x != sx) or (tile_stig_y != sy):
            self.sem.set_wd(tile_wd)
            self.sem.set_stig_xy(tile_stig_x, tile_stig_y)
        # TODO: Use enum for method:
        if self.autofocus.method == 0:
            utils.log_info('SEM',
                           'Running SmartSEM AF procedure '
                           + af_type + ' for tile '
                           + str(grid_index) + '.' + str(tile_index))
            self.add_to_main_log('SEM: Running SmartSEM AF procedure '
                                 + af_type + ' for tile '
                                 + str(grid_index) + '.' + str(tile_index))
            autofocus_msg = 'SEM', self.autofocus.run_zeiss_af(do_focus, do_stig)
        elif self.autofocus.method == 3:
            msg = f'Running MAPFoSt AF procedure for tile {grid_index}.{tile_index} with initial WD/STIG_X/Y: ' \
                  f'{tile_wd*1000:.4f}, {tile_stig_x:.4f}, {tile_stig_y:.4f}'
            utils.log_info('SEM', msg)
            self.add_to_main_log(f'SEM: {msg}')
            # needed here because first slice required additional AF trials when using GCIB
            af_kwargs = dict(defocus_arr=self.autofocus.mapfost_defocus_trials, rot=self.autofocus.rot_angle_mafpsot,
                             scale=self.autofocus.scale_factor_mapfost, na=self.autofocus.na_mapfost,
                             log_func=self.add_to_main_log)
            if self.slice_counter == 1 and self.microtome.device_name == 'GCIB':
                af_kwargs['defocus_arr'] = [8, 8] + af_kwargs['defocus_arr']
                msg = f'Added additional [8, 8] µm defocus trials to MAPoSt AF procedure for tile ' \
                      f'{grid_index}.{tile_index}'
                utils.log_info('SEM', msg)
                self.add_to_main_log(f'SEM: {msg}')
            autofocus_msg = 'SEM', self.autofocus.run_mapfost_af(**af_kwargs)
        else:
            self.error_state = Error.autofocus_smartsem  # TODO: check if that code makes sense here
            return
        utils.log_info(*autofocus_msg)
        self.add_to_main_log(autofocus_msg[0] + ': ' + autofocus_msg[1])
        if 'ERROR' in autofocus_msg[1]:
            self.error_state = Error.autofocus_smartsem
        elif not self.autofocus.wd_stig_diff_below_max(tile_wd, tile_stig_x, tile_stig_y):
            msg = (f'Autofocus for tile {grid_index}.{tile_index} out of range with new values: {self.sem.get_wd()*1000} (WD), '
                   f'{self.sem.get_stig_xy()} (stig_xy).')
            utils.log_error('STAGE', msg)
            self.add_to_main_log(msg)
            self.add_to_incident_log(msg)
            self.error_state = Error.wd_stig_difference
        else:
            # Save settings for specified tile
            self.gm[grid_index][tile_index].wd = self.sem.get_wd()
            self.gm[grid_index][tile_index].stig_xy = list(
                self.sem.get_stig_xy())
            msg = f'Finished MAPFoSt AF procedure for tile {grid_index}.{tile_index} with final WD/STIG_X/Y: ' \
                  f'{self.gm[grid_index][tile_index].wd*1000:.4f}, {self.gm[grid_index][tile_index].stig_xy[0]:.4f},' \
                  f' {self.gm[grid_index][tile_index].stig_xy[1]:.4f}'
            utils.log_info('SEM', msg)
            self.add_to_main_log(f'SEM: {msg}')
            # Show updated WD label(s) in Viewport
            self.main_controls_trigger.transmit('DRAW VP')

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
                self.do_autofocus(
                    *self.autofocus_stig_current_slice,
                    do_move, grid_index, tile_index)
                if self.error_state != Error.none or self.pause_state == 1:
                    # Immediately pause and save interruption info
                    if not self.acq_paused:
                        self.pause_acquisition(1)
                    self.set_interruption_point(grid_index, tile_index)
                    break

    def do_heuristic_autofocus(self, tile_key):
        utils.log_info('CTRL',
                       f'Processing tile {tile_key} for '
                       f'heuristic autofocus ')
        self.add_to_main_log('CTRL: Processing tile %s for '
                             'heuristic autofocus ' %tile_key)
        self.autofocus.process_image_for_heuristic_af(tile_key)
        wd_corr, sx_corr, sy_corr, within_range = (
            self.autofocus.get_heuristic_corrections(tile_key))
        if wd_corr is not None:
            utils.log_info('CTRL',
                           'New corrections: '
                           f'{wd_corr:.6f}, '
                           f'{sx_corr:.6f}, '
                           f'{sy_corr:.6f}')
            self.add_to_main_log('CTRL: New corrections: '
                                 + '{0:.6f}, '.format(wd_corr)
                                 + '{0:.6f}, '.format(sx_corr)
                                 + '{0:.6f}'.format(sy_corr))
            if not within_range:
                # The difference in WD/STIG was too large.
                self.error_state = Error.wd_stig_difference
                self.pause_acquisition(1)
        else:
            utils.log_info(
                'CTRL',
                'No estimates computed (need one additional slice) ')
            self.add_to_main_log(
                'CTRL: No estimates computed (need one additional slice) ')

    def do_autofocus_adjustments(self, grid_index):
        # Apply average WD/STIG from reference tiles
        # if tracking mode "Average" is selected.
        if self.use_autofocus and self.autofocus.tracking_mode == 2:
            if self.autofocus.method == 0:
                utils.log_info(
                    'CTRL',
                    'Applying average WD/STIG parameters '
                    '(SmartSEM autofocus).')
                self.add_to_main_log(
                    'CTRL: Applying average WD/STIG parameters '
                    '(SmartSEM autofocus).')
            elif self.autofocus.method == 1:
                utils.log_info(
                    'CTRL',
                    'Applying average WD/STIG parameters '
                    '(heuristic autofocus).')
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

                # Apply corrections. At the moment, all reference tiles are
                # checked individually if the difference in wd/stig from
                # the autofocus correction is within the permissable limit,
                # so there is no need to check the averages.
                # TODO: Make this more robust, for example allow individual
                # deviations above the limit if the average is within the limit,
                # or use fallbacks to previous values, neighbouring tiles...
                self.wd_default = avg_grid_wd
                self.stig_x_default = avg_grid_stig_x
                self.stig_y_default = avg_grid_stig_y
                # Update grid
                self.gm[grid_index].set_wd_for_all_tiles(avg_grid_wd)
                self.gm[grid_index].set_stig_xy_for_all_tiles(
                    [avg_grid_stig_x, avg_grid_stig_y])

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
        utils.log_info(
            'SEM',
            'Locked magnification: ' + str(self.locked_mag))
        self.add_to_main_log(
            'SEM: Locked magnification: ' + str(self.locked_mag))

    def set_default_wd_stig(self):
        """Set wd/stig to target default values."""
        self.sem.set_wd(self.wd_default)
        self.sem.set_stig_xy(self.stig_x_default, self.stig_y_default)
        utils.log_info(
            'SEM',
            'Adjusted ' + utils.format_wd_stig(
            self.wd_default, self.stig_x_default, self.stig_y_default))
        self.add_to_main_log('SEM: Adjusted ' + utils.format_wd_stig(
            self.wd_default, self.stig_x_default, self.stig_y_default))

    def check_locked_wd_stig(self):
        """Check if wd/stig was accidentally changed and restore targets."""
        change_detected = False
        diff_wd = abs(self.sem.get_wd() - self.locked_wd)
        diff_stig_x = abs(self.sem.get_stig_x() - self.locked_stig_x)
        diff_stig_y = abs(self.sem.get_stig_y() - self.locked_stig_y)

        if diff_wd > 0.000001:
            change_detected = True
            utils.log_warning(
                'SEM',
                'Warning: Change in working distance detected.')
            self.add_to_main_log(
                'SEM: Warning: Change in working distance detected.')
            # Restore previous working distance
            self.sem.set_wd(self.locked_wd)
            utils.log_info(
                'SEM',
                'Restored previous working distance.')
            self.add_to_main_log('SEM: Restored previous working distance.')

        if (diff_stig_x > 0.000001 or diff_stig_y > 0.000001):
            change_detected = True
            utils.log_warning(
                'SEM',
                'Warning: Change in stigmation settings detected.')
            self.add_to_main_log(
                'SEM: Warning: Change in stigmation settings detected.')
            # Restore previous settings
            self.sem.set_stig_xy(self.locked_stig_x, self.locked_stig_y)
            utils.log_info(
                'SEM',
                'Restored previous stigmation settings.')
            self.add_to_main_log(
                'SEM: Restored previous stigmation parameters.')
        if change_detected:
            self.main_controls_trigger.transmit('FOCUS ALERT')

    def check_locked_mag(self):
        """Check if mag was accidentally changed and restore target mag."""
        current_mag = self.sem.get_mag()
        if current_mag != self.locked_mag:
            utils.log_warning(
                'SEM',
                'Warning: Change in magnification detected.')
            utils.log_info(
                'SEM',
                'Current mag: ' + str(current_mag)
                + '; target mag: ' + str(self.locked_mag))
            self.add_to_main_log(
                'SEM: Warning: Change in magnification detected.')
            self.add_to_main_log(
                'SEM: Current mag: ' + str(current_mag)
                + '; target mag: ' + str(self.locked_mag))
            # Restore previous magnification
            self.sem.set_mag(self.locked_mag)
            utils.log_info(
                'SEM',
                'Restored previous magnification.')
            self.add_to_main_log('SEM: Restored previous magnification.')
            self.main_controls_trigger.transmit('MAG ALERT')

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
        # TODO (BT): Remove this method and add log handler for the session logs
        """Add entry to the Main Controls log."""
        msg = utils.format_log_entry(msg)
        # Store entry in main log file
        if self.main_log_file is not None:
            self.main_log_file.write(msg + '\n')
        # Send entry to Main Controls via queue and trigger
        # self.main_controls_trigger.transmit(msg)

    def add_to_incident_log(self, msg):
        """Add msg to the incident log file (after formatting it) and show it
        in the incident log in the Viewport (monitoring tab).
        """
        timestamp = str(datetime.datetime.now())[:-7]
        msg = f'{timestamp} | Slice {self.slice_counter}: {msg}'
        if self.incident_log_file is not None:
            self.incident_log_file.write(msg + '\n')
        # Signal to main window to update incident log in Viewport
        self.main_controls_trigger.transmit('INCIDENT LOG' + msg)

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

    def set_interruption_point(self, grid_index, tile_index, during_acq=True):
        """Save grid/tile position where interruption occurred
        during an acquisition.
        """
        self.acq_interrupted = True
        self.acq_interrupted_at = [grid_index, tile_index]
        if not during_acq:
            # Mark grids/tiles before interruption point as acquired
            self.grids_acquired = []
            for g in range(self.gm.number_grids):
                if g == grid_index:
                    break
                self.grids_acquired.append(g)
            self.tiles_acquired = []
            for t in self.gm[grid_index].active_tiles:
                if t == tile_index:
                    break
                self.tiles_acquired.append(t)

    def reset_error_state(self):
        self.error_state = Error.none
        self.error_info = ''
