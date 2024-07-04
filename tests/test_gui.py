import pytest
import sys
from qtpy.QtWidgets import QApplication

from main_controls import MainControls
from test_common import init_read_configs, init_log


TEST_CONFIG_FILE = 'mock.ini'
TEST_SYSCONFIG_FILE = 'mock.cfg'


def test_gui_mock():
    # TODO: find testing Qt GUI (using github actions) ~ like napari (viewer) testing
    # TODO: import image, load grids/OVs/stub-OV (with generated data)
    init_log()
    config, sysconfig = init_read_configs(TEST_CONFIG_FILE, TEST_SYSCONFIG_FILE)

    qapp = QApplication(sys.argv)
    main_controls = MainControls(config, sysconfig, TEST_CONFIG_FILE)   # opens GUI Control and View window

    #sbem.exec()     # exec() is a blocking call; for debugging only


if __name__ == '__main__':
    test_gui_mock()
