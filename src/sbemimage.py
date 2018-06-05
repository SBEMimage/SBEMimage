#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""SBEMimage.py launches the application.
   Use 'python SBEMimage.py' or call the batch file SBEMimage.bat.
"""

import os
import sys
import ctypes
from configparser import ConfigParser
from PyQt5.QtWidgets import QApplication
import colorama # needed to suppress TIFFReadDirectory warnings in the console

from dlg_windows import ConfigDlg
from main_controls import MainControls

VERSION = '2.0 (R2018-06-05)'

def main():
    """Load configuration and run QApplication.
    Let user select configuration file. Preselect the configuration from the
    previous run (saved in status.dat), otherwise default.ini.
    Quit if default.ini can't be found.
    Check if configuration can be loaded and if it's compatible with the
    current version of SBEMimage. If not, quit.
    """
    SBEMimage = QApplication(sys.argv)
    app_id = 'SBEMimage ' + VERSION
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    colorama.init()
    os.system('cls')
    os.system('title SBEMimage - Console')
    print('***********************************\n'
          '     SBEMimage\n'
          '     Version %s\n'
          '***********************************\n' % VERSION)

    configuration_loaded = False
    compatible = False

    if os.path.isfile('..\\cfg\\default.ini'):
        # Ask user to select .ini file:
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
                print('Loading configuration file %s ...'
                      % config_file, end='')
                config = ConfigParser()
                with open('..\\cfg\\' + config_file, 'r') as file:
                    config.read_file(file)
                print(' Done.\n')
                # Load corresponding system settings file
                sysconfig_file = config['sys']['sys_config_file']
                print('Loading system settings file %s ...'
                      % sysconfig_file, end='')
                sysconfig = ConfigParser()
                with open('..\\cfg\\' + sysconfig_file, 'r') as file:
                    sysconfig.read_file(file)
                configuration_loaded = True
                print(' Done.\n')
            except:
                configuration_loaded = False
                print('\nError while loading configuration! Program aborted.\n')
                # Keep terminal window open when run from batch file
                os.system('cmd /k')
                sys.exit()
    else:
        # Quit if default.ini doesn't exist
        configuration_loaded = False
        print('Error: No default configuration found. Program aborted.\n')
        os.system('cmd /k')
        sys.exit()

    if configuration_loaded:
        # Check compatibility of .ini file and SBEMimage version
        try:
            compatible = config['sys']['compatible_version'] == VERSION[:3]
        except:
            compatible = False
        if compatible:
            # Remove status file. It will be recreated when program terminates
            # normally.
            if os.path.isfile('..\\cfg\\status.dat'):
                os.remove('..\\cfg\\status.dat')
            print('Initializing SBEMimage. Please wait...\n')
            # Launch Main Controls. Viewport is launched from Main Controls.
            SBEMimage_main_window = MainControls(config,
                                                 sysconfig,
                                                 config_file,
                                                 VERSION)
            sys.exit(SBEMimage.exec_())
        else:
            print('Selected configuration file is incomplete or incompatible '
                  'with version %s.\n' % VERSION[:3])
            os.system('cmd /k')
            sys.exit()

if __name__ == '__main__':
    main()
