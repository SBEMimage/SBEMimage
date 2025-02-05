from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QLineEdit, QMessageBox
from qtpy.uic import loadUi
from validate_email import validate_email

import utils


class EmailMonitoringSettingsDlg(QDialog):
    """Adjust settings for e-mail monitoring: e-mail addresses, status report
    options, and remote control through e-mail commands.
    """

    def __init__(self, acquisition, notifications):
        super().__init__()
        self.acq = acquisition
        self.notifications = notifications
        loadUi('gui/email_monitoring_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.lineEdit_notificationEmail.setText(
            self.notifications.user_email_addresses[0])
        self.lineEdit_secondaryNotificationEmail.setText(
            self.notifications.user_email_addresses[1])
        self.spinBox_reportInterval.setValue(self.acq.status_report_interval)
        self.lineEdit_selectedOV.setText(str(
            self.notifications.status_report_ov_list)[1:-1])
        self.lineEdit_selectedTiles.setText(str(
            self.notifications.status_report_tile_list)[1:-1].replace('\'', ''))
        self.checkBox_sendLogFile.setChecked(self.notifications.send_logfile)
        self.checkBox_sendIncidentLogFile.setChecked(
            self.notifications.send_additional_logs)
        self.checkBox_sendViewport.setChecked(
            self.notifications.send_viewport_screenshot)
        self.checkBox_sendOverviews.setChecked(self.notifications.send_ov)
        self.checkBox_sendOverviews.stateChanged.connect(
            self.update_ov_list_input)
        self.checkBox_sendTiles.setChecked(self.notifications.send_tiles)
        self.checkBox_sendTiles.stateChanged.connect(
            self.update_tile_list_input)
        self.checkBox_sendOVReslices.setChecked(
            self.notifications.send_ov_reslices)
        self.checkBox_sendOVReslices.stateChanged.connect(
            self.update_ov_list_input)
        self.checkBox_sendTileReslices.setChecked(
            self.notifications.send_tile_reslices)
        self.checkBox_sendTileReslices.stateChanged.connect(
            self.update_tile_list_input)
        self.checkBox_allowEmailControl.setChecked(
            self.notifications.remote_commands_enabled)
        self.checkBox_allowEmailControl.stateChanged.connect(
            self.update_remote_option_input)
        self.update_remote_option_input()
        self.spinBox_remoteCheckInterval.setValue(
            self.acq.remote_check_interval)
        self.lineEdit_account.setText(self.notifications.email_account)
        # Show password as string of asterisks
        self.lineEdit_password.setEchoMode(QLineEdit.Password)
        self.lineEdit_password.setText(self.notifications.remote_cmd_email_pw)

    def update_ov_list_input(self):
        self.lineEdit_selectedOV.setEnabled(
            (self.checkBox_sendOverviews.isChecked()
             or self.checkBox_sendOVReslices.isChecked()))

    def update_tile_list_input(self):
        self.lineEdit_selectedTiles.setEnabled(
            (self.checkBox_sendTiles.isChecked()
             or self.checkBox_sendTileReslices.isChecked()))

    def update_remote_option_input(self):
        status = self.checkBox_allowEmailControl.isChecked()
        self.spinBox_remoteCheckInterval.setEnabled(status)
        self.lineEdit_password.setEnabled(status)

    def accept(self):
        error_str = ''
        email1 = self.lineEdit_notificationEmail.text()
        email2 = self.lineEdit_secondaryNotificationEmail.text()
        if validate_email(email1):
            self.notifications.user_email_addresses[0] = email1
        else:
            error_str = (
                'First user e-mail address incorrectly formatted or missing.')
        # Second user e-mail is optional
        if validate_email(email2) or not email2:
            self.notifications.user_email_addresses[1] = (
                self.lineEdit_secondaryNotificationEmail.text())
        else:
            error_str = 'Second user e-mail address incorrectly formatted.'
        self.acq.status_report_interval = self.spinBox_reportInterval.value()

        success, ov_list = utils.validate_ov_list(
            self.lineEdit_selectedOV.text())
        if success:
            self.notifications.status_report_ov_list = ov_list
        else:
            error_str = 'List of selected overviews incorrectly formatted.'

        success, tile_list = utils.validate_tile_list(
            self.lineEdit_selectedTiles.text())
        if success:
            self.notifications.status_report_tile_list = tile_list
        else:
            error_str = 'List of selected tiles incorrectly formatted.'

        self.notifications.send_logfile = self.checkBox_sendLogFile.isChecked()
        self.notifications.send_additional_logs = (
            self.checkBox_sendIncidentLogFile.isChecked())
        self.notifications.send_viewport_screenshot = (
            self.checkBox_sendViewport.isChecked())
        self.notifications.send_ov = (
            self.checkBox_sendOverviews.isChecked())
        self.notifications.send_tiles = (
            self.checkBox_sendTiles.isChecked())
        self.notifications.send_ov_reslices = (
            self.checkBox_sendOVReslices.isChecked())
        self.notifications.send_tile_reslices = (
            self.checkBox_sendTileReslices.isChecked())
        self.notifications.remote_commands_enabled = (
            self.checkBox_allowEmailControl.isChecked())
        self.acq.remote_check_interval = (
            self.spinBox_remoteCheckInterval.value())
        self.notifications.remote_cmd_email_pw = self.lineEdit_password.text()
        if not error_str:
            super().accept()
        else:
            QMessageBox.warning(self, 'Error', error_str, QMessageBox.Ok)
