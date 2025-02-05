import os
from time import sleep
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class SendCommandDlg(QDialog):
    """Send a command to DM (for testing purposes)."""

    def __init__(self, microtome):
        super().__init__()
        self.microtome = microtome
        loadUi('gui/send_dm_command_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_sendCommand.clicked.connect(self.send_command)
        self.pushButton_checkResponse.clicked.connect(self.check_response)
        self.comboBox_command.addItems(
            ['Handshake',
             'MicrotomeStage_Cut',
             'MicrotomeStage_Retract',
             'MicrotomeStage_Clear',
             'MicrotomeStage_Near',
             'MicrotomeStage_FullCut',
             'MicrotomeStage_FullApproachCut',
             'MicrotomeStage_GetPositionX',
             'MicrotomeStage_GetPositionY',
             'MicrotomeStage_GetPositionXY',
             'MicrotomeStage_GetPositionZ',
             'MicrotomeStage_SetPositionX',
             'MicrotomeStage_SetPositionY',
             'MicrotomeStage_SetPositionXY',
             'MicrotomeStage_SetPositionXY_Confirm',
             'MicrotomeStage_SetPositionZ',
             'MicrotomeStage_SetPositionZ_Confirm',
             'SetMotorSpeedXY',
             'MeasureMotorSpeedXY',
             'StopScript'])
        self.comboBox_command.setEditable(True)

    def send_command(self):
        """Read the command string and the two parameters from the GUI elements
        and send them to DigitalMicrograph.
        """
        cmd = self.comboBox_command.currentText()
        param1 = self.doubleSpinBox_param1.value()
        param2 = self.doubleSpinBox_param2.value()

        # For some commands, ask for confirmation (for safety reasons)
        if cmd in ['MicrotomeStage_Cut', 'MicrotomeStage_Near',
                   'MicrotomeStage_FullCut', 'MicrotomeStage_FullApproachCut',
                   'MicrotomeStage_SetPositionZ',
                   'MicrotomeStage_SetPositionZ_Confirm', 'SetMotorSpeedXY']:
            user_reply = QMessageBox.question(
                self, 'Send command to DM',
                    f'Please confirm that you want to send the command {cmd} '
                    f'to the DigitalMicrograph script.',
                    QMessageBox.Ok | QMessageBox.Cancel)
            if user_reply == QMessageBox.Cancel:
                return

        # Clear output text field
        self.plainTextEdit_scriptResponse.setPlainText('')
        if (cmd.startswith('MicrotomeStage_SetPosition') or
                cmd.startswith('SetMotorSpeed')):
            self.microtome._send_dm_command(cmd, [param1, param2])
        else:
            self.microtome._send_dm_command(cmd)
        sleep(0.5)

    def check_response(self):
        """Read the output file DMcom.out and display its contents. Check for
        the existence of the other signal files.
        """
        if os.path.isfile(self.microtome.OUTPUT_FILE):
            return_values = self.microtome._read_dm_return_values()
        else:
            return_values = 'No output file generated'
        script_response = 'DMcom.out: ' + str(return_values) + '\n'
        # Check files
        if os.path.isfile(self.microtome.ACK_FILE):
            script_response += (
                'Command execution confirmed: '
                + self.microtome.ACK_FILE + '\n')
        if os.path.isfile(self.microtome.ACK_CUT_FILE):
            script_response += (
                'Cut execution confirmed: '
                + self.microtome.ACK_CUT_FILE + '\n')
        if os.path.isfile(self.microtome.WARNING_FILE):
            script_response += (
                'Warning: ' + self.microtome.WARNING_FILE + '\n')
        if os.path.isfile(self.microtome.ERROR_FILE):
            script_response += (
                'Error: ' + self.microtome.ERROR_FILE + '\n')
        # Error state
        script_response += (f'Error state: {self.microtome.error_state} '
                            f'{self.microtome.error_info}')
        # Display in GUI
        self.plainTextEdit_scriptResponse.setPlainText(script_response)
        self.microtome.reset_error_state()
