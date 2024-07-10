# https://doc.qt.io/qtforpython-6/overviews/qtest-overview.html

import pytest
import sys
from time import sleep
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

    def test_gui_mock(self, tmp_path):
        # TODO: find testing Qt GUI (using github actions) ~ like napari (viewer) testing
        # TODO: import image, load grids/OVs/stub-OV (with generated data)
        init_log()
        config, sysconfig = init_read_configs(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)
        # Set base path to temp path
        base_dir = str(tmp_path)
        config['acq']['mock_prev_acq_dir'] = base_dir
        config['acq']['base_dir'] = base_dir
        main_controls = MainControls(config, sysconfig, self.TEST_CONFIG_FILE)   # opens GUI Control and View window

        #main_controls.pushButton_SEMSettings.click()
        #main_controls.pushButton_grabFrame.click()
        #main_controls.pushButton_startAcq.click()
        main_controls.start_acquisition()

        # TODO: this works if not paused on a dialog!
        while True:
            QApplication.processEvents()
            sleep(1e-3)
            if not main_controls.busy:
                break

        for _ in range(10):
            QApplication.processEvents()
            sleep(1e-1)

        print('done')

        #sbem.exec()     # exec() is a blocking call; for debugging only


if __name__ == '__main__':
    from pathlib import Path
    import tempfile

    path = Path(tempfile.TemporaryDirectory().name)
    TestGuiMock().test_gui_mock(path)
