# https://doc.qt.io/qtforpython-6/overviews/qtest-overview.html

import pytest
import sys
from time import sleep
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QApplication, QMessageBox

from test_common import init_read_configs, init_log
from main_controls import MainControls


class TestGuiMock:
    TEST_CONFIG_FILE = 'mock.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    def test_gui_mock(self, qtbot, tmp_path):
        # TODO: import image, load grids/OVs/stub-OV (with generated data)
        init_log()
        config, sysconfig = init_read_configs(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)
        # Set base path to temp path
        base_dir = str(tmp_path)
        config['acq']['mock_prev_acq_dir'] = base_dir
        config['acq']['base_dir'] = base_dir
        main_controls = MainControls(config, sysconfig, self.TEST_CONFIG_FILE)  # opens GUI Control and View window
        if qtbot:
            qtbot.addWidget(main_controls)

        #main_controls.pushButton_SEMSettings.click()
        #main_controls.pushButton_grabFrame.click()
        #main_controls.pushButton_startAcq.click()
        main_controls.start_acquisition()

        # https://stackoverflow.com/questions/59147908/how-to-click-on-qmessagebox-with-pytest-qt

        #qtbot.waitUntil(main_controls.about_box.isVisible)
        #qtbot.waitUntil(not main_controls.busy)
        if qtbot:
            messagebox = qtbot.QApplication.activeWindow()
            messagebox.button(QMessageBox.Yes).click()
        # or qtbot.mouseClick(yes_button, Qt.LeftButton, delay=1) or qtbot.click(dialog.button)

        # TODO: new dialogs need to come from qtbot root window
        while True:
            QApplication.processEvents()
            sleep(1e-3)
            if not main_controls.busy:
                break

        for _ in range(10):
            QApplication.processEvents()
            sleep(1e-1)


if __name__ == '__main__':
    from pathlib import Path
    import tempfile
    #from pytestqt.qtbot import QtBot
    #qtbot = QtBot(None)
    qapp = QApplication(sys.argv)
    qtbot = None

    path = Path(tempfile.TemporaryDirectory().name)
    TestGuiMock().test_gui_mock(qtbot, path)
