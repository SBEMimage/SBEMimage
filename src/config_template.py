# -*- coding: utf-8 -*-

#==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2018 Benjamin Titze,
#   Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
#==============================================================================

"""This module updates older or non-compliant configuration files to match the
   most recent default.ini and system.cfg.
"""

# The following constants must be updated if entries are added to or
# deleted from the default configuration files
CFG_TEMPLATE_FILE = '..\\cfg\\default.ini'
CFG_NUMBER_SECTIONS = 10
CFG_NUMBER_KEYS = 178

SYSCFG_TEMPLATE_FILE = '..\\cfg\\system.cfg'
SYSCFG_NUMBER_SECTIONS = 7
SYSCFG_NUMBER_KEYS = 20

import os
from configparser import ConfigParser

def process_cfg(current_cfg, current_syscfg, is_default_cfg=False):

    cfg_template = None
    cfg_load_success = True
    cfg_valid = True
    cfg_changed = False
    syscfg_template = None
    syscfg_load_success = True
    syscfg_valid = True
    syscfg_changed = False

    if is_default_cfg:
        cfg_valid = check_number_of_entries(current_cfg, 0)
        syscfg_valid = check_number_of_entries(current_syscfg, 1)
    else:
        # Load default configuration. This file must be up-to-date. It is always
        # bundled with each new version of SBEMimage.
        if os.path.isfile(CFG_TEMPLATE_FILE):
            cfg_template = ConfigParser()
            try:
                with open(CFG_TEMPLATE_FILE, 'r') as file:
                    cfg_template.read_file(file)
            except:
                cfg_load_success = False
        if os.path.isfile(SYSCFG_TEMPLATE_FILE):
            syscfg_template = ConfigParser()
            try:
                with open(SYSCFG_TEMPLATE_FILE, 'r') as file:
                    syscfg_template.read_file(file)
            except:
                syscfg_load_success = False
        if cfg_load_success:
            cfg_valid = check_number_of_entries(cfg_template, 0)
        if syscfg_load_success:
            syscfg_valid = check_number_of_entries(syscfg_template, 1)

        if (cfg_load_success and syscfg_load_success
                and cfg_valid and syscfg_valid):
            # Compare default config to current user config:
            for section in cfg_template.sections():
                # Go through all sections and keys:
                for key in cfg_template[section]:
                    if current_cfg.has_option(section, key):
                        cfg_template[section][key] = current_cfg[section][key]
                    else:
                        cfg_changed = True
            # Compare sys default config:
            for section in syscfg_template.sections():
                for key in syscfg_template[section]:
                    if current_syscfg.has_option(section, key):
                        syscfg_template[section][key] = current_syscfg[section][key]
                    else:
                        syscfg_changed = True

    success = (cfg_load_success and syscfg_load_success
               and cfg_valid and syscfg_valid)

    changes = [cfg_changed, syscfg_changed]

    # cfg_template and syscfg_template are updated versions of the current
    # configuration
    return success, changes, cfg_template, syscfg_template

def check_number_of_entries(cfg, type=0):
    all_sections = cfg.sections()
    section_count = len(all_sections)
    key_count = 0
    for section in all_sections:
        key_count += len(cfg[section])
    if type == 0:
        return (section_count == CFG_NUMBER_SECTIONS
                and key_count == CFG_NUMBER_KEYS)
    else:
        return (section_count == SYSCFG_NUMBER_SECTIONS
                and key_count == SYSCFG_NUMBER_KEYS)
