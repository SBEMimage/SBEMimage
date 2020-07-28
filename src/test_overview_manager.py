# -*- coding: utf-8 -*-

"""Tests for overview_manager.py"""

import sys
import pytest

# QApplication needed because QPixmap is used in overview_manager.py
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)

# Use the default configuration for all tests
from test_load_config import config, sysconfig

from overview_manager import OverviewManager
from coordinate_system import CoordinateSystem
from sem_control import SEM

@pytest.fixture
def ov_manager():
    # Create CoordinateSystem instance
    cs = CoordinateSystem(config, sysconfig)
    # Create SEM (base class) instance
    sem = SEM(config, sysconfig)
    # Create and return GridManager instance
    return OverviewManager(config, sem, cs)

def test_initial_overview_config(ov_manager):
    assert ov_manager.number_ov == 1
    assert ov_manager.use_auto_debris_area

def test_create_new_overviews(ov_manager):
    ov_manager.add_new_overview()
    ov_manager.add_new_overview()
    assert ov_manager.number_ov == 3
    ov_manager.delete_overview()
    assert ov_manager.number_ov == 2

def test_overview_methods(ov_manager):
    ov_manager[0].centre_sx_sy = 0, 0
    width, height = ov_manager[0].width_d(), ov_manager[0].height_d()
    top_left_dx, top_left_dy, _, _ = ov_manager[0].bounding_box()
    assert top_left_dx == -width / 2
    assert top_left_dy == -height / 2
