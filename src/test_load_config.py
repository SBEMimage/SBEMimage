# -*- coding: utf-8 -*-

"""Load the default user and system configuration."""

import os
from configparser import ConfigParser

from config_template import process_cfg

# Load default user and system configurations
config = ConfigParser()
with open(os.path.join('..', 'cfg', 'default.ini'), 'r') as file:
    config.read_file(file)
sysconfig = ConfigParser()
with open(os.path.join('..', 'cfg', 'system.cfg'), 'r') as file:
    sysconfig.read_file(file)

def test_process_config():
    success, exceptions, _, _, _, _ = process_cfg(config, sysconfig)
    assert success