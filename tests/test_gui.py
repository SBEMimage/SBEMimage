# https://doc.qt.io/qtforpython-6/overviews/qtest-overview.html

import pytest
import sys
#from qtpy.QtCore import QObject
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QApplication

from test_common import init_read_configs, init_log
from main_controls import MainControls


#class TestGuiMock(QObject):
class TestGuiMock:
    TEST_CONFIG_FILE = 'mock.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    qapp = QApplication(sys.argv)   # required Qt operations. Exclude when using pytest-qt

    def test_gui_mock(self):
        # TODO: find testing Qt GUI (using github actions) ~ like napari (viewer) testing
        # TODO: import image, load grids/OVs/stub-OV (with generated data)
        init_log()
        config, sysconfig = init_read_configs(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)

        main_controls = MainControls(config, sysconfig, self.TEST_CONFIG_FILE)   # opens GUI Control and View window

        #main_controls.pushButton_SEMSettings.click()
        #main_controls.pushButton_grabFrame.click()
        #main_controls.pushButton_startAcq.click()

        #sbem.exec()     # exec() is a blocking call; for debugging only


if __name__ == '__main__':
    TestGuiMock().test_gui_mock()
