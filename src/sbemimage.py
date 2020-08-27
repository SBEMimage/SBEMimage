#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2020.07
#   https://github.com/SBEMimage
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""sbemimage.py launches the application.

First, the start-up dialog is shown (ConfigDlg in
main_controls_dlg_windows.py), and the user is asked to select a configuration
file.
Then the QMainWindow MainControls (in main_controls.py) is launched.

Use 'python sbemimage.py' or call the batch file SBEMimage.bat to run SBEMimage.
"""

import os
import sys
import platform
import ctypes
from configparser import ConfigParser
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
import colorama # needed to suppress TIFFReadDirectory warnings in the console

from main_controls_dlg_windows import ConfigDlg
from config_template import process_cfg
from main_controls import MainControls

# VERSION contains the current version/release date information for the
# master branch (for example, '2020.07 R2020-07-28'). For the current version
# in the dev (development) branch, it is set to 'dev'.
VERSION = 'dev'


def main():
    """Load configuration and run QApplication.

    Let user select configuration file. Preselect the configuration from the
    previous run (saved in status.dat), otherwise default.ini.
    Quit if default.ini can't be found, or if user/system configuration cannot
    be loaded.
    """
    # Check Windows version
    if not (platform.system() == 'Windows'
            and platform.release() in ['7', '10']):
        print('Error: This version of SBEMimage requires Windows 7 or 10. '
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
    if VERSION.lower() == 'dev':
        title_str = 'SBEMimage - Console - DEVELOPMENT VERSION'
        version_info = 'DEVELOPMENT VERSION'
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

    if (os.path.isfile('..\\cfg\\default.ini')
            and os.path.isfile('..\\cfg\\system.cfg')):
        # Ask user to select .ini file
        startup_dialog = ConfigDlg(VERSION)
        startup_dialog.exec_()
        dlg_response = startup_dialog.get_ini_file()
        if dlg_response == 'abort':
            configuration_loaded = False
            print('Program aborted by user.\n')
            sys.exit()
        else:
            try:
                config_file = dlg_response
                if config_file == 'default.ini':
                    default_configuration = True
                print(f'Loading configuration file {config_file} ...', end='')
                config = ConfigParser()
                config_file_path = os.path.join('..', 'cfg', config_file)
                with open(config_file_path, 'r') as file:
                    config.read_file(file)
                print(' Done.\n')

                # Load corresponding system configuration file
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
            except Exception as e:
                configuration_loaded = False
                print('\nError while loading configuration! '
                      'Program aborted.\n Exception: ' + str(e))
                # Keep terminal window open when run from batch file
                os.system('cmd /k')
                sys.exit()
    else:
        # Quit if default.ini doesn't exist
        configuration_loaded = False
        print('Error: default.ini and/or system.cfg not found. '
              'Program aborted.\n')
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

        if success:
            if default_configuration:
                print('Default configuration loaded (read-only).\n')
            else:
                if cfg_changed and syscfg_changed:
                    ch_str = 'config and sysconfig updated'
                elif cfg_changed:
                    ch_str = 'config updated'
                elif syscfg_changed:
                    ch_str = "sysconfig updated"
                else:
                    ch_str = 'complete, no updates'
                print('Configuration loaded and checked: ' + ch_str + '\n')

            # Remove status.dat. This file will be recreated when the program
            # terminates normally. The start-up dialog checks if status.dat
            # exists and displays a warning message if not.
            if os.path.isfile('..\\cfg\\status.dat'):
                os.remove('..\\cfg\\status.dat')

            print('Initializing SBEMimage. Please wait...\n')

            # Launch Main Controls window. The Viewport window (see viewport.py)
            # is launched from Main Controls.
            SBEMimage_main_window = MainControls(config,
                                                 sysconfig,
                                                 config_file,
                                                 VERSION)
            sys.exit(SBEMimage.exec_())
        else:
            print('Error(s) while checking configuration file(s): '
                  + exceptions + '\n'
                  + 'Program aborted.\n')
            os.system('cmd /k')
            sys.exit()

if __name__ == '__main__':
    main()
