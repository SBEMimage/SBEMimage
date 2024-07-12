# https://doc.qt.io/qtforpython-6/overviews/qtest-overview.html
# https://stackoverflow.com/questions/59147908/how-to-click-on-qmessagebox-with-pytest-qt

import pytest
import sys
from time import sleep
from qtpy.QtWidgets import QApplication

from test_common import *
from main_controls import MainControls


class TestGuiMock:
    TEST_CONFIG_FILE = 'mock.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    def test_gui_mock(self, tmp_path, qtbot):
        # TODO: import image, load grids/OVs/stub-OV (with generated data)
        init_log()
        if qtbot is None:
            qapp = QApplication(sys.argv)  # Required to run Qt

        config, sysconfig = init_read_configs(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)
        # Set base path to temp path
        base_dir = str(tmp_path)
        config['acq']['mock_prev_acq_dir'] = base_dir
        config['acq']['base_dir'] = base_dir
        main_controls = MainControls(config, sysconfig, self.TEST_CONFIG_FILE)  # opens GUI Control and View window

        timeout_s = 30
        main_controls.debug_mode = True
        if qtbot:
            qtbot.addWidget(main_controls)
        # main_controls.pushButton_startAcq.click()     # alternative: simulate button press
        main_controls.start_acquisition()

        if qtbot:
            qtbot.waitUntil(lambda: not main_controls.busy, timeout=timeout_s * 1000)
        else:
            while True:
                QApplication.processEvents()
                sleep(1e-3)
                if not main_controls.busy:
                    break

        sleep(5)


if __name__ == '__main__':
    from pathlib import Path
    import tempfile

    path = Path(tempfile.TemporaryDirectory().name)
    TestGuiMock().test_gui_mock(path, None)
