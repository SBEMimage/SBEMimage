#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage – https://github.com/SBEMimage
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2021 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""sbemimage.py launches the application.

First, the start-up dialog is shown (ConfigDlg in main_controls_dlg_windows.py),
and the user is asked to select a user configuration file. The application
attempts to load the user configuration file (.ini) and the associated system
configuration file (.cfg). If the configuration is loaded successfully, the
QMainWindow MainControls (in main_controls.py) is launched.

Use 'python sbemimage.py' or call the batch file SBEMimage.bat to run SBEMimage.
"""

import os
import sys

# Required for version installed with pynsist installer
if os.path.exists('..\\Python') and os.path.exists('..\\pkgs'):
    import site
    scriptdir, script = os.path.split(__file__)
    pkgdir = os.path.join(scriptdir, '..', 'pkgs')
    # Ensure .pth files in pkgdir are handled properly and ensure importing
    # local modules works.
    site.addsitedir(pkgdir)
    site.addsitedir(scriptdir)
    sys.path.insert(0, pkgdir)
    sys.path.append(scriptdir)

import platform
import ctypes
import traceback
import colorama # needed to suppress TIFFReadDirectory warnings in the console
from configparser import ConfigParser
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from main_controls_dlg_windows import ConfigDlg
from config_template import process_cfg, load_device_presets
from main_controls import MainControls
import utils


# VERSION contains the current version/release date information for the
# master branch (for example, '2020.07 R2020-07-28'). For the current version
# in the dev (development) branch, it must contain the tag 'dev'.
# Following https://www.python.org/dev/peps/pep-0440/#public-version-identifiers
VERSION = '2021.04 dev'


# Hook for uncaught/Qt exceptions
def excepthook(exc_type, exc_value, exc_tb):
    message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print("Exception hook caught: " + message)
    utils.log_exception(message)

sys.excepthook = excepthook


def main():
    """Load configuration and run QApplication.

    Let user select configuration file. Preselect the configuration from the
    previous run (saved in status.dat), otherwise default.ini.
    Quit if default.ini can't be found, or if user/system configuration cannot
    be loaded.
    """

    utils.logging_init('CTRL', '***** New SBEMimage session *****')

    # Check Windows version
    if not (platform.system() == 'Windows'
            and platform.release() in ['7', '10']):
        print('This version of SBEMimage requires Windows 7 or 10. '
              'Program aborted.\n')
        os.system('cmd /k')  # keep console window open
        sys.exit()

    if platform.release() == '10':
        # High dpi scaling for Windows 10
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        # TODO: This does not work well for 150% and other scale factors.
        # Qt elements and fonts in the GUI don't scale in the correct ratios.

    SBEMimage = QApplication(sys.argv)
    app_id = 'SBEMimage ' + VERSION
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)

    colorama.init()
    os.system('cls')
    if 'dev' in VERSION.lower():
        title_str = 'SBEMimage - Console - DEVELOPMENT VERSION'
        version_info = f'DEVELOPMENT VERSION ({VERSION})'
    else:
        title_str = 'SBEMimage - Console'
        version_info = 'Version ' + VERSION
    os.system('title ' + title_str)

    line_of_stars = '*' * (len(version_info) + 10)
    print(f'{line_of_stars}\n'
          f'     SBEMimage\n'
          f'     {version_info}\n'
          f'{line_of_stars}\n')

    configuration_loaded = False
    default_configuration = False
    presets_loaded = False

    if (os.path.isfile('..\\cfg\\default.ini')
            and os.path.isfile('..\\cfg\\system.cfg')):
        # Ask user to select .ini file
        startup_dialog = ConfigDlg(VERSION)
        startup_dialog.exec_()
        dlg_response = startup_dialog.get_ini_file()
        device_presets_selection = startup_dialog.device_presets_selection
        if dlg_response == 'abort':
            configuration_loaded = False
            print('Program aborted by user.\n')
            sys.exit()
        else:
            try:
                # Attempt to load the configuration files and start up the app.
                # Logging to central log file starts at this point.
                config_file = dlg_response
                if config_file == 'default.ini':
                    default_configuration = True
                print(f'Loading configuration file {config_file} ...', end='')
                config = ConfigParser()
                config_file_path = os.path.join('..', 'cfg', config_file)
                with open(config_file_path, 'r') as file:
                    config.read_file(file)
                print(' Done.\n')

                # Load associated system configuration file
                sysconfig_file = config['sys']['sys_config_file']
                if default_configuration and sysconfig_file != 'system.cfg':
                    sysconfig_file = 'system.cfg'
                    config['sys']['sys_config_file'] = 'system.cfg'
                print(f'Loading system settings file {sysconfig_file} ...',
                      end='')
                sysconfig = ConfigParser()
                sysconfig_file_path = os.path.join('..', 'cfg', sysconfig_file)
                with open(sysconfig_file_path, 'r') as file:
                    sysconfig.read_file(file)
                configuration_loaded = True
                print(' Done.\n')
                utils.log_info('CTRL', 
                    f'Configuration files {config_file} and {sysconfig_file} '
                    f'loaded.')
            except Exception as e:
                configuration_loaded = False
                config_error = ('\nError while loading configuration! '
                                'Program aborted.\n Exception: ' + str(e))
                utils.log_error('CTRL', config_error)
                print(config_error)
                # Keep terminal window open when run from batch file
                os.system('cmd /k')
                sys.exit()
    else:
        # Quit if default.ini doesn't exist
        configuration_loaded = False
        default_not_found = 'default.ini and/or system.cfg not found. Program aborted.\n'
        print(default_not_found)
        utils.log_error('CTRL', default_not_found)
        os.system('cmd /k')
        sys.exit()

    if configuration_loaded:
        # Check selected .ini file and ensure there are no missing entries.
        # Configuration must match template configuration in default.ini.
        if default_configuration:
            # Check if number of entries correct (no other checks at the moment)
            success, exceptions, _, _, _, _ = process_cfg(config, sysconfig,
                                                          is_default_cfg=True)
        else:
            # Check and update if necessary: obsolete entries are ignored,
            # missing/new entries are added with default values.
            (success, exceptions,
             cfg_changed, syscfg_changed,
             config, sysconfig) = (
                process_cfg(config, sysconfig))

            if success and device_presets_selection != [None, None]:
                # Attempt to load presets into system configuration
                selected_sem, selected_microtome = device_presets_selection
                success, exc = load_device_presets(
                    sysconfig, selected_sem, selected_microtome)
                exceptions += '; ' + exc
                if success:
                    syscfg_changed = True
                    presets_loaded = True

        if success:
            if default_configuration:
                utils.log_info(
                    'CTRL', 'Default configuration loaded (read-only).')
                print('Default configuration loaded (read-only).\n')
            else:
                ch_str = 'Configuration loaded and checked: '
                if cfg_changed and syscfg_changed:
                    ch_str += 'config and sysconfig updated'
                elif cfg_changed:
                    ch_str += 'config updated'
                elif syscfg_changed:
                    ch_str += "sysconfig updated"
                else:
                    ch_str += 'complete, no updates'
                utils.log_info('CTRL', ch_str)
                print(ch_str + '\n')

            if presets_loaded:
                devices_str = ''
                if selected_sem is not None:
                    devices_str = selected_sem
                if selected_microtome is not None:
                    if devices_str:
                        devices_str += ' + ' + selected_microtome
                    else:
                        devices_str = selected_microtome
                devices_str = 'Device presets loaded for ' + devices_str + '.'       
            else:
                devices_str = 'Device setup: ' + sysconfig['device']['sem'] + ', '
                if config['sys']['use_microtome'].lower() == 'false':
                    devices_str += 'no microtome'
                else:
                    devices_str += sysconfig['device']['microtome']

            utils.log_info('CTRL', devices_str)
            print(devices_str + '\n')
 
            # Remove status.dat. This file will be recreated when the program
            # terminates normally. The start-up dialog checks if status.dat
            # exists and displays a warning message if not.
            if os.path.isfile('..\\cfg\\status.dat'):
                os.remove('..\\cfg\\status.dat')

            # Switch to dark style (experimental) if specified in user config
            if config['sys']['use_dark_mode_gui'].lower() == 'true':
                import qdarkstyle
                SBEMimage.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5'))

            print('Please wait while SBEMimage is starting up...\n')

            # Launch Main Controls window. The Viewport window (see viewport.py)
            # is launched from Main Controls.
            try:
                SBEMimage_main_window = MainControls(config,
                                                     sysconfig,
                                                     config_file,
                                                     VERSION)
                sys.exit(SBEMimage.exec_())
            except Exception as e:
                print('\nAn exception occurred during this SBEMimage session:\n')
                utils.logger.propagate = True
                utils.log_exception("Exception")
                print('\nProgram aborted.')
                print('Please submit a bug report at '
                      'https://github.com/SBEMimage/SBEMimage/issues and '
                      'include all lines in /SBEMimage/log/SBEMimage.log '
                      'after the entry "ERROR : Exception".')
                os.system('cmd /k')
                sys.exit()

        else:
            config_error = ('Error(s) while checking configuration file(s): '
                            + exceptions + '\n'
                            + 'Program aborted.\n')
            utils.log_error('CTRL', config_error)
            print(config_error)
            os.system('cmd /k')
            sys.exit()


if __name__ == '__main__':
    main()
