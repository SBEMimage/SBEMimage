# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""The following two functions check configuration files, and update older or
non-compliant configuration files to match default.ini and system.cfg.

TODO: Before merging the dev branch to master, add backward compatibility for
several entries in the system.cfg.
"""

import os
from configparser import ConfigParser


# The following constants must be updated if entries are added to or
# deleted from the default configuration files
CFG_TEMPLATE_FILE = '..\\cfg\\default.ini'  # Template of user configuration
CFG_NUMBER_SECTIONS = 12
CFG_NUMBER_KEYS = 213

SYSCFG_TEMPLATE_FILE = '..\\cfg\\system.cfg'  # Template of system configuration
SYSCFG_NUMBER_SECTIONS = 8
SYSCFG_NUMBER_KEYS = 50

# Presets file: contains presets for different devices
DEVICE_PRESETS_FILE = '..\\cfg\\device_presets.cfg'

# Backward compatibility for older system config files
LEGACY_DEVICE_NUMBERS = {0: 'Gatan 3View',
                         1: 'ZEISS Merlin',
                         2: 'ZEISS Sigma', 
                         3: 'ZEISS GeminiSEM', 
                         4: 'ZEISS Ultra Plus',
                         5: 'ConnectomX katana', 
                         6: 'GCIB'}


def process_cfg(current_cfg, current_syscfg, is_default_cfg=False):
    """Go through all sections and keys of the template configuration files and
    check whether entries are present in configuration files to be processed.
    If an entry cannot be found, use the entry from the template.
    """

    cfg_template = None
    cfg_load_success = True
    cfg_valid = True
    cfg_changed = False
    syscfg_template = None
    syscfg_load_success = True
    syscfg_valid = True
    syscfg_changed = False

    exceptions = ''

    if is_default_cfg:
        # Currently, the only validity check is verifying the number of entries.
        cfg_valid = check_number_of_entries(current_cfg, False)
        syscfg_valid = check_number_of_entries(current_syscfg, True)
    else:
        # Load default configuration. This file must be up-to-date. It is always
        # bundled with each new version of SBEMimage.
        cfg_template = ConfigParser()
        try:
            with open(CFG_TEMPLATE_FILE, 'r') as file:
                cfg_template.read_file(file)
        except Exception as e:
            cfg_load_success = False
            exceptions += str(e) + '; '
        syscfg_template = ConfigParser()
        try:
            with open(SYSCFG_TEMPLATE_FILE, 'r') as file:
                syscfg_template.read_file(file)
        except Exception as e:
            syscfg_load_success = False
            exceptions += str(e) + '; '
        if cfg_load_success:
            cfg_valid = check_number_of_entries(cfg_template, False)
        if syscfg_load_success:
            syscfg_valid = check_number_of_entries(syscfg_template, True)

        if (cfg_load_success and syscfg_load_success
                and cfg_valid and syscfg_valid):
            # If there are obsolete key names, update them and preserve
            # the entries.
            cfg_changed, syscfg_changed = (
                update_key_names(current_cfg, current_syscfg))
            # Compare default config to current user config.
            for section in cfg_template.sections():
                # Go through all sections and keys.
                for key in cfg_template[section]:
                    if current_cfg.has_option(section, key):
                        cfg_template[section][key] = current_cfg[section][key]
                    else:
                        cfg_changed = True
            # Compare sys default config.
            for section in syscfg_template.sections():
                for key in syscfg_template[section]:
                    if current_syscfg.has_option(section, key):
                        if key != 'recognized':
                            syscfg_template[section][key] = (
                                current_syscfg[section][key])
                        if key in ['sem', 'microtome']:
                            device = current_syscfg[section][key]
                            if len(device) == 1:
                                try:                            
                                    syscfg_template[section][key] = (
                                        LEGACY_DEVICE_NUMBERS[int(device)])
                                except (ValueError, KeyError):
                                    syscfg_template[section][key] = (
                                        'INVALID SELECTION')
                    else:
                        syscfg_changed = True

    success = (cfg_load_success and syscfg_load_success
               and cfg_valid and syscfg_valid)

    if not cfg_valid:
        exceptions += 'Invalid number of sections in config; '
    if not syscfg_valid:
        exceptions += 'Invalid number of sections in system config; '

    # cfg_template and syscfg_template are now the updated versions of the
    # current configuration
    return (success, exceptions,
            cfg_changed, syscfg_changed,
            cfg_template, syscfg_template)


def check_number_of_entries(cfg, is_sys_cfg=False):
    all_sections = cfg.sections()
    section_count = len(all_sections)
    key_count = 0
    for section in all_sections:
        key_count += len(cfg[section])
    if is_sys_cfg:
        return (section_count == SYSCFG_NUMBER_SECTIONS
                and key_count == SYSCFG_NUMBER_KEYS)
    else:
        return (section_count == CFG_NUMBER_SECTIONS
                and key_count == CFG_NUMBER_KEYS)


def update_key_names(cfg, syscfg):
    """Ensure backward compatibility for several key names."""
    cfg_changed, syscfg_changed = False, False
    if cfg.has_option('grids', 'wd_stig_data'):
        cfg['grids']['wd_stig_params'] = cfg['grids']['wd_stig_data']
        cfg_changed = True
    if cfg.has_option('grids', 'tile_size_px_py'):
        cfg['grids']['tile_size'] = cfg['grids']['tile_size_px_py']
        cfg_changed = True
    if cfg.has_option('grids', 'use_adaptive_focus'):
        cfg['grids']['use_wd_gradient'] = (
            cfg['grids']['use_adaptive_focus'])
        cfg_changed = True
    if cfg.has_option('grids', 'adaptive_focus_tiles'):
        cfg['grids']['wd_gradient_ref_tiles'] = (
            cfg['grids']['adaptive_focus_tiles'])
        cfg_changed = True
    if cfg.has_option('overviews', 'ov_size_px_py'):
        cfg['overviews']['ov_size'] = cfg['overviews']['ov_size_px_py']
        cfg_changed = True
    if syscfg.has_option('stage', 'microtome_motor_limits' ):
        syscfg['stage']['microtome_stage_limits'] = (
            syscfg['stage']['microtome_motor_limits'])
        syscfg_changed = True
    if syscfg.has_option('stage', 'sem_motor_limits' ):
        syscfg['stage']['sem_stage_limits'] = (
            syscfg['stage']['sem_motor_limits'])
        syscfg_changed = True
    if syscfg.has_option('stage', 'microtome_calibration_data' ):
        syscfg['stage']['microtome_calibration_params'] = (
            syscfg['stage']['microtome_calibration_data'])
        syscfg_changed = True
    if syscfg.has_option('stage', 'sem_calibration_data' ):
        syscfg['stage']['sem_calibration_params'] = (
            syscfg['stage']['sem_calibration_data'])
        syscfg_changed = True
    return cfg_changed, syscfg_changed


def load_device_presets(syscfg, selected_sem, selected_microtome):
    """Load presets for selected SEM/microtome from the file 
    DEVICE_PRESETS_FILE into the system configuration (syscfg).
    Return (True, '') if successful, otherwise (False, exception_str). 
    """
    if selected_sem is None and selected_microtome is None:
        return False, ''

    device_presets = ConfigParser()
    try:
        with open(DEVICE_PRESETS_FILE, 'r') as file:
            device_presets.read_file(file)
    except Exception as e:
        return False, str(e)

    if selected_sem:
        # Load SEM presets and write them into system configuration
        try:
            sem_presets = device_presets[selected_sem]
            for key in sem_presets:
                syscfg_section, syscfg_key = key.split('_', 1)
                syscfg[syscfg_section][syscfg_key] = sem_presets[key]
        except Exception as e:
            return False, str(e)

    if selected_microtome:
        # Load microtome presets and write them into system configuration
        try:
            microtome_presets = device_presets[selected_microtome]
            for key in microtome_presets:
                syscfg_section, syscfg_key = key.split('_', 1)
                syscfg[syscfg_section][syscfg_key] = microtome_presets[key]
        except Exception as e:
            return False, str(e)    

    return True, ''

