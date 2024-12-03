# https://doc.qt.io/qtforpython-6/overviews/qtest-overview.html
# https://stackoverflow.com/questions/59147908/how-to-click-on-qmessagebox-with-pytest-qt

import sys
from time import sleep
from qtpy.QtWidgets import QApplication

from test_utils import *
from main_controls import MainControls
from viewport_dlg_windows import ImportImageDlg, StubOVDlg


class TestGuiMock:
    TEST_CONFIG_FILE = 'mock.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    def test_gui_mock(self, tmp_path, qtbot):
        self.tmp_path = tmp_path
        self.qtbot = qtbot
        self.init()

        # open GUI Control and View window
        self.main_controls = MainControls(self.config, self.sysconfig, self.TEST_CONFIG_FILE)
        self.main_controls.test_mode = True
        if self.qtbot:
            self.qtbot.addWidget(self.main_controls)

        self.import_image()
        #self.acq_stub_ov()  # stuck on messagebox when done
        self.acquisition()

        if not qtbot:
            self.main_controls.close()
        # widget will now close, triggering main_controls close event

    def init(self):
        init_log()
        if self.qtbot is None:
            self.qapp = QApplication(sys.argv)  # Required to run Qt
        config, sysconfig = init_read_configs(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)
        # Set base path to temp path
        base_dir = str(self.tmp_path)
        config['acq']['mock_prev_acq_dir'] = base_dir
        config['acq']['base_dir'] = base_dir
        self.config = config
        self.sysconfig = sysconfig

    def import_image(self):
        filename = str(self.tmp_path / 'import_image.tiff')
        create_image(filename, (1000, 1000))
        imported_images = self.main_controls.imported
        viewport_trigger = self.main_controls.viewport.viewport_trigger
        stage = self.main_controls.stage
        dialog = ImportImageDlg(imported_images, viewport_trigger, stage)
        dialog.lineEdit_fileName.setText(filename)
        dialog.doubleSpinBox_transparency.setValue(50)
        dialog.accept()
        assert len(imported_images) > 0

    def acq_stub_ov(self):
        sem = self.main_controls.sem
        stage = self.main_controls.stage
        ovm = self.main_controls.ovm
        acq = self.main_controls.acq
        img_inspector = self.main_controls.img_inspector
        viewport_trigger = self.main_controls.viewport.viewport_trigger
        dialog = StubOVDlg((0, 0), sem, stage, ovm, acq, img_inspector, viewport_trigger)
        dialog.pushButton_acquire.click()

        while True:
            QApplication.processEvents()
            sleep(1e-3)
            if not self.main_controls.busy:
                break

    def acquisition(self):
        acq_timeout_s = 30

        # main_controls.pushButton_startAcq.click()     # alternative: simulate button press
        self.main_controls.start_acquisition()

        if self.qtbot:
            self.qtbot.waitUntil(lambda: not self.main_controls.busy, timeout=acq_timeout_s * 1000)
        else:
            while True:
                QApplication.processEvents()
                sleep(1e-3)
                if not self.main_controls.busy:
                    break
        sleep(5)


if __name__ == '__main__':
    from pathlib import Path
    import tempfile

    path = Path(tempfile.TemporaryDirectory().name)
    TestGuiMock().test_gui_mock(path, None)
