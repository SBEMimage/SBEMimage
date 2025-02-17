from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog
from qtpy.uic import loadUi

import utils


class TCPSettingsDlg(QDialog):
    """Specify the host and port for TCP requests during acquisition.
    Currently only used for remote control through the Napari SBEMViewer plugin.
    """

    def __init__(self, tcp_remote, acq):
        super().__init__()
        loadUi('gui/tcp_settings_dlg.ui', self)
        self.tcp_remote = tcp_remote
        self.acq = acq
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.lineEdit_host.setText(self.tcp_remote.host)
        self.spinBox_port.setValue(self.tcp_remote.port)
        self.pushButton_testConnection.clicked.connect(self._on_test_connection)
        self.show()

    def _on_test_connection(self):
        try:
            res = self.acq.send_data_tcp()
            self.acq.process_tcp_commands(res.get('commands', []))
        except ConnectionRefusedError:
            utils.log_info('CTRL', 'TCP Connection refused.')

    def accept(self):
        self.tcp_remote.host = self.lineEdit_host.text()
        self.tcp_remote.port = self.spinBox_port.value()
        super().accept()
