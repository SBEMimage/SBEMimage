# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""Tests for microtome_control.py. Currently only for base class.
TODO: Tests for different microtomes with mock hardware."""

import pytest

# Use the default configuration for all tests
from test_load_config import config, sysconfig

from microtome_control import Microtome

@pytest.fixture
def microtome():
    """Create and return microtome (base class) instance initialized with
    default configuration.
    """
    return Microtome(config, sysconfig)

def test_initial_config(microtome):
    assert microtome.device_name == 'NOT RECOGNIZED'
    assert len(microtome.stage_limits) == 4

def test_cut(microtome):
    # Calling cut() should raise an exception because the method is not
    # implemented in the base class.
    with pytest.raises(NotImplementedError):
        assert microtome.cut()

def test_stage_move_duration(microtome):
    speed_x, speed_y = microtome.motor_speed_x, microtome.motor_speed_y
    dx, dy = speed_x * 5, speed_y * 5   # XY distance travelled in 5 s
    # Moving from the origin to (dx, dy) should take exactly 5 s plus
    # the stage_move_wait_interval
    expected_duration = 5 + microtome.stage_move_wait_interval
    assert microtome.stage_move_duration(0, 0, dx, dy) == expected_duration
