# -*- coding: utf-8 -*-

"""Tests for microtome_control.py."""

import pytest

# Use the default configuration for all tests
from test_load_config import config, sysconfig

from microtome_control import Microtome

@pytest.fixture
def microtome():
    """Create and return microtome (base class) instance"""
    return Microtome(config, sysconfig)

def test_initial_config(microtome):
	assert microtome.device_name == 'Gatan 3View'



