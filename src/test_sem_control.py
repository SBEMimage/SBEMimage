# -*- coding: utf-8 -*-

"""Tests for sem_control.py. Currently only for base class.
TODO: Tests for different SEMs with mock hardware."""

import pytest

# Use the default configuration for all tests
from test_load_config import config, sysconfig

from sem_control import SEM

@pytest.fixture
def sem():
    """Create and return SEM (base class) instance with default config."""
    return SEM(config, sysconfig)

def test_initial_config(sem):
    assert sem.device_name == 'ZEISS GeminiSEM'
    assert sem.target_eht == 1.5
    assert sem.simulation_mode
