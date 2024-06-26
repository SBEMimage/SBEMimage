import pytest
import sys
from configparser import ConfigParser
from qtpy.QtWidgets import QApplication

from main_controls import MainControls
import utils


TEST_CONFIG_FILE = 'test.ini'
TEST_SYSCONFIG_FILE = 'test.cfg'


def test_gui_mock():
    utils.logging_init('TEST', 'Testing')
    config = utils.read_config(TEST_CONFIG_FILE)
    sysconfig = utils.read_config(TEST_SYSCONFIG_FILE)

    sbem = QApplication(sys.argv)
    main_controls = MainControls(config, sysconfig, TEST_CONFIG_FILE)   # opens GUI Control and View window

    #sbem.exec()     # exec() is a blocking call; for debugging only


if __name__ == '__main__':
    test_gui_mock()
