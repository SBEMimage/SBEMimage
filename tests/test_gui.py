# https://doc.qt.io/qtforpython-6/overviews/qtest-overview.html

#import pytest
import sys
from qtpy.QtCore import QObject
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QApplication

from main_controls import MainControls
from test_common import init_read_configs, init_log


class TestGuiMock(QObject):
    TEST_CONFIG_FILE = 'mock.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    #qapp = QApplication(sys.argv)   # required Qt operations. Needs to remain in context!

    def initTestCase(self):
        pass

    def test_gui_mock(self):
        # TODO: find testing Qt GUI (using github actions) ~ like napari (viewer) testing
        # TODO: import image, load grids/OVs/stub-OV (with generated data)
        init_log()
        config, sysconfig = init_read_configs(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)

        main_controls = MainControls(config, sysconfig, self.TEST_CONFIG_FILE)   # opens GUI Control and View window

        #sbem.exec()     # exec() is a blocking call; for debugging only


if __name__ == '__main__':
    TestGuiMock().test_gui_mock()
