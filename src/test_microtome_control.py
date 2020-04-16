# -*- coding: utf-8 -*-

"""Tests for the microtome module.
"""

import pytest

import os
from configparser import ConfigParser

from microtome_control import Microtome, Microtome_3View, Microtome_katana

@pytest.fixture
def microtome():
    # Load default user and system configurations
    config = ConfigParser()
    with open(os.path.join('..', 'cfg', 'default.ini'), 'r') as file:
        config.read_file(file)
    sysconfig = ConfigParser()
    with open(os.path.join('..', 'cfg', 'system.cfg'), 'r') as file:
        sysconfig.read_file(file)
    # Create and return microtome instance
    return Microtome(config, sysconfig)

def test_something(microtome):
	assert microtome.device_name == 'Gatan 3View'



