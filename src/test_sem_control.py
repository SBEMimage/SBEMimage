# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

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
    assert sem.device_name == 'NOT RECOGNIZED'
    assert sem.target_eht == 1.5
    assert sem.simulation_mode
