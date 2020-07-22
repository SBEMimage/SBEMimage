# -*- coding: utf-8 -*-

"""Tests for grid_manager.py"""

import pytest

import os
from configparser import ConfigParser

from grid_manager import GridManager
from sem_control import SEM
from coordinate_system import CoordinateSystem

@pytest.fixture
def grid_manager():
    # Load default user and system configurations
    config = ConfigParser()
    with open(os.path.join('..', 'cfg', 'default.ini'), 'r') as file:
        config.read_file(file)
    sysconfig = ConfigParser()
    with open(os.path.join('..', 'cfg', 'system.cfg'), 'r') as file:
        sysconfig.read_file(file)
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





