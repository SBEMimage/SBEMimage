from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class RunAutofocusDlg(QDialog):
    """Run the autofocus/autostigmator or both and use method specifed by
    user (SEM or MAPFoSt).
    """
    def __init__(self, autofocus, sem):
        super().__init__()
        self.autofocus = autofocus
        self.sem = sem
        self.use_autofocus = False
        self.use_autostig = False
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.autofocus_completed)
        self.new_wd_stig = None, None, None
        self.busy = False
        self.af_msg = None

        loadUi('gui/run_autofocus_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()

        if self.sem.device_name.startswith("ZEISS"):
            sem_method_name = "SmartSEM"
        elif self.sem.device_name.startswith("TESCAN"):
            sem_method_name = "TESCAN"
        else:
            sem_method_name = "SEM unsupported"

        self.comboBox_method.addItems([sem_method_name, 'MAPFoSt'])
        self.comboBox_method.setCurrentIndex(0)
        self.comboBox_mode.addItems(
            ['Autofocus + stig', 'Autofocus only', 'Autostig only'])
        self.comboBox_mode.setCurrentIndex(0)

        self.pushButton_run.clicked.connect(self.run_autofocus)
        self.pushButton_calibrate.clicked.connect(self.calibrate_af)

    def run_autofocus(self):
        self.busy = True
        self.pushButton_run.setText('Busy... please wait')
        self.pushButton_run.setEnabled(False)
        method = self.comboBox_method.currentIndex()
        mode = self.comboBox_mode.currentIndex()
        self.large_aberr = self.radioButton_large_aberr.isChecked()
        if method == 1:
            self.aberr_mode_bools = [mode<2, mode==0 or mode==2, mode==0 or mode==2]
            utils.run_log_thread(self.call_mapfost_af_routine)

        elif method == 0:
            if mode == 0:
                self.use_autofocus = True
                self.use_autostig = True
            elif mode == 1:
                self.use_autofocus = True
                self.use_autostig = False
            else:
                self.use_autofocus = False
                self.use_autostig = True
            utils.run_log_thread(self.call_sem_af_routine)

    def call_mapfost_af_routine(self):
        self.af_msg = self.autofocus.run_mapfost_af(self.aberr_mode_bools, self.large_aberr)
        self.finish_trigger.signal.emit()

    def call_sem_af_routine(self):
        self.af_msg = self.autofocus.run_sem_af(
            self.use_autofocus, self.use_autostig)
        self.finish_trigger.signal.emit()

    def autofocus_completed(self):
        self.busy = False
        self.pushButton_run.setText('Run')
        self.pushButton_run.setEnabled(True)
        if 'ERROR' in self.af_msg:
            self.new_wd_stig = None, None, None
            QMessageBox.warning(
                self, 'SEM Autofocus error',
                'An error occurred while running the SEM Autofocus',
                QMessageBox.Ok)
            utils.log_error('SEM', self.af_msg)
        else:
            self.new_wd_stig = self.sem.get_wd(), *self.sem.get_stig_xy()
            QMessageBox.information(
                self, 'SEM Autofocus completed',
                f'New working distance and stigmation:\n'
                f'{utils.format_wd_stig(*self.new_wd_stig)}',
                QMessageBox.Ok)
            utils.log_info('SEM', self.af_msg)
            self.accept()

    def calibrate_af(self):
        method = self.comboBox_method.currentIndex()
        if method == 0 :
            QMessageBox.information(
                self, 'SmartSEM AF',
                'calibration not available',
                QMessageBox.Ok)
        elif method ==1:
            self.pushButton_calibrate.setText('Busy... please wait')
            self.pushButton_calibrate.setEnabled(False)
            self.busy = True
            QMessageBox.question(
                self, 'Defocus calibration.','Defocus calibration \n Please make sure the SEM is well focused. \n Click OK to proceed.',
                QMessageBox.Ok)
            msg = self.autofocus.calibrate_mapfost_af(calib_mode="defocus")

            user_reply = QMessageBox.question(
                self, 'Defocus calibration','Probe convergence angle is ' + str(msg) + "\n" + "Please update the ini file." + "\n" +
                                            "Click Ok to proceed with Astig calibration"
                , QMessageBox.Ok| QMessageBox.Cancel)

            utils.log_info('SEM ', 'The probe convergence angle is ' + str(msg))
            self.accept()

            if user_reply == QMessageBox.Ok:
                user_reply = QMessageBox.question(
                    self, 'Astig calibration.',' Astig Calibration \n Please make sure the SEM is well focused. \n Click OK to proceed.',
                    QMessageBox.Ok | QMessageBox.Cancel)
                if user_reply == QMessageBox.Ok:
                    msg = self.autofocus.calibrate_mapfost_af(calib_mode="astig")
                    QMessageBox.question(
                        self, 'Astig calibration.', 'The astig rotation (deg) is ' + str(msg[0]) + "\n" +
                                                    'The astig scaling is ' + str(msg[1]) +
                                                    " \n Calibration complete. Please update the ini file", QMessageBox.Ok)
                    utils.log_info('SEM' , "Astig Rotation and Scaling : " + str(msg))
                self.accept()
                self.af_msg = "Calibration complete. Please update the ini file"
                self.new_wd_stig = self.sem.get_wd(), *self.sem.get_stig_xy()
                self.finish_trigger.signal.emit()

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if not self.busy:
            event.accept()
        else:
            event.ignore()
