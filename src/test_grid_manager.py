# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""Tests for grid_manager.py"""

import pytest

# Use the default configuration for all tests
from test_load_config import config, sysconfig

from grid_manager import GridManager
from sem_control import SEM
from coordinate_system import CoordinateSystem

@pytest.fixture
def grid_manager():
    # Create CoordinateSystem instance
    cs = CoordinateSystem(config, sysconfig)
    # Create SEM (base class) instance
    sem = SEM(config, sysconfig)
    # Create and return GridManager instance
    return GridManager(config, sem, cs)

def test_initial_config(grid_manager):
    assert grid_manager.number_grids == 1

def test_create_new_grids(grid_manager):
    grid_manager.add_new_grid()
    grid_manager.add_new_grid()
    assert grid_manager.number_grids == 3
    grid_manager.delete_grid()
    assert grid_manager.number_grids == 2

def test_manipulate_grids(grid_manager):
    grid_manager[0].size = 10, 10
    assert grid_manager[0].size == [10, 10]
    grid_manager[0].deactivate_all_tiles()
    assert grid_manager[0].number_active_tiles() == 0
    grid_manager[0].activate_all_tiles()
    assert grid_manager[0].number_active_tiles() == 100
