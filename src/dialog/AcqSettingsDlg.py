import math
import os
import validators
from qtpy.QtCore import Qt, QSize
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QDialog, QFileDialog, QMessageBox
from qtpy.uic import loadUi

import utils
from sem.SEM_Mock import SEM_Mock


class AcqSettingsDlg(QDialog):
    """Dialog for adjusting acquisition settings."""

    def __init__(self, acquisition, notifications, use_microtome=True):
        super().__init__()
        self.acq = acquisition
        self.notifications = notifications
        if isinstance(self.acq.sem, SEM_Mock):
            loadUi('gui/acq_settings_dlg_mock.ui', self)
            self.update_mock_settings()
        else:
            loadUi('gui/acq_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_selectDir.clicked.connect(self.select_directory)
        self.pushButton_selectDir.setIcon(QIcon('img/selectdir.png'))
        self.pushButton_selectDir.setIconSize(QSize(16, 16))
        # Display current settings:
        self.lineEdit_baseDir.setText(self.acq.base_dir)
        self.lineEdit_baseDir.textChanged.connect(self.update_stack_name)
        self.update_stack_name()
        self.new_base_dir = ''
        self.spinBox_sliceThickness.setValue(self.acq.slice_thickness)
        self.update_target_settings()
        self.spinBox_sliceCounter.setValue(self.acq.slice_counter)
        self.doubleSpinBox_totalZDiff.setValue(self.acq.total_z_diff)
        self.checkBox_sendMetaData.setChecked(self.acq.send_metadata)
        self.update_server_lineedit()
        self.checkBox_sendMetaData.stateChanged.connect(
            self.update_server_lineedit)
        self.checkBox_EHTOff.setChecked(self.acq.eht_off_after_stack)
        self.lineEdit_metaDataServer.setText(
            self.notifications.metadata_server_url)
        self.lineEdit_adminEmail.setText(
            self.notifications.metadata_server_admin_email)
        self.lineEdit_projectName.setText(self.acq.metadata_project_name)
        # Disable two spinboxes when SEM stage used
        if not use_microtome:
            self.spinBox_sliceThickness.setEnabled(False)
            self.doubleSpinBox_totalZDiff.setEnabled(False)

    def select_directory(self):
        """Let user select the base directory for the stack acquisition.
        Note that the final subfolder name in the directory string is used as
        the name of the stack in SBEMimage.
        """
        if len(self.acq.base_dir) > 2:
            start_path = self.acq.base_dir[:3]
        else:
            start_path = 'C:/'
        self.lineEdit_baseDir.setText(
            str(QFileDialog.getExistingDirectory(
                self, 'Select Directory',
                start_path,
                QFileDialog.ShowDirsOnly)))

    def select_mock_directory(self):
        """Let user select a previous acquisition directory to use for mock SEM images."""
        self.lineEdit_mockDir.setText(
            str(QFileDialog.getExistingDirectory(
                self, 'Select Directory',
                'C:/',
                QFileDialog.ShowDirsOnly)))

    def update_server_lineedit(self):
        self.lineEdit_projectName.setEnabled(
            self.checkBox_sendMetaData.isChecked())

    def update_stack_name(self):
        base_dir = self.lineEdit_baseDir.text().rstrip(r'\\\/ ')
        self.label_stackName.setText(base_dir[os.path.normpath(base_dir).rfind(os.sep) + 1:])

    def update_target_settings(self):
        if self.acq.use_target_z_diff:
            self.comboBox_targetType.setCurrentIndex(1)
            self.doubleSpinBox_targetZDiff.setValue(self.acq.target_z_diff)
            self.update_number_slices()
            self.spinBox_numberSlices.hide()
        else:
            self.comboBox_targetType.setCurrentIndex(0)
            self.spinBox_numberSlices.setValue(self.acq.number_slices)
            self.update_target_z_diff()
            self.doubleSpinBox_targetZDiff.hide()
        self.comboBox_targetType.currentIndexChanged.connect(self.switch_target_spinbox)

    def update_mock_settings(self):
        self.pushButton_selectMockDir.clicked.connect(self.select_mock_directory)
        self.pushButton_selectMockDir.setIcon(QIcon('img/selectdir.png'))
        self.pushButton_selectMockDir.setIconSize(QSize(16, 16))
        if self.acq.sem.previous_acq_dir is not None:
            self.lineEdit_mockDir.setText(self.acq.sem.previous_acq_dir)
        index = self.comboBox_mockType.findText(self.acq.sem.mock_type)
        if index < 0:
            index = 0
        self.comboBox_mockType.setCurrentIndex(index)

    def update_target_z_diff(self):
        if self.slices_valid(self.acq.slice_counter, self.acq.number_slices):
            self.doubleSpinBox_targetZDiff.setValue(self.calculate_target_z_diff_from_number_slices())
        else:
            # If the slice values are invalid, just set the target z diff to the current total z diff
            self.doubleSpinBox_targetZDiff.setValue(self.acq.total_z_diff)

    def update_number_slices(self):
        if self.z_diff_valid(self.acq.target_z_diff, self.acq.total_z_diff):
            self.spinBox_numberSlices.setValue(self.calculate_number_slices_from_target_z_diff())
        else:
            # If Z diff values are invalid, just set the target number of slices to the current slice number
            self.spinBox_numberSlices.setValue(self.acq.slice_counter)

    def switch_target_spinbox(self):
        """ When target number of slices is used, a QSpinbox with integer steps is used.
        When target z diff is used, a QDoubleSpinbox with fractional steps is used.
        """
        slice_spin_box = self.spinBox_numberSlices
        depth_spin_box = self.doubleSpinBox_targetZDiff
        slice_spin_box.setVisible(not slice_spin_box.isVisible())
        depth_spin_box.setVisible(not depth_spin_box.isVisible())

    def calculate_number_slices_from_target_z_diff(self):
        z_to_cut_in_nanometer = round(
            (self.doubleSpinBox_targetZDiff.value() - self.doubleSpinBox_totalZDiff.value())*1000)
        # always rounds down to nearest whole slice, as we don't want to exceed the target depth
        n_slices_to_cut = math.floor(z_to_cut_in_nanometer/self.acq.slice_thickness)
        total_n_slices = n_slices_to_cut + self.spinBox_sliceCounter.value()

        return total_n_slices

    def calculate_target_z_diff_from_number_slices(self):
        # giving number_slices as 0, means just image current surface, so target z is same as total z
        if self.acq.number_slices == 0:
            return self.acq.total_z_diff
        else:
            n_slices = self.acq.number_slices - self.acq.slice_counter
            slice_thickness_microns = self.acq.slice_thickness / 1000
            target_z_diff = self.acq.total_z_diff + (n_slices * slice_thickness_microns)

            return target_z_diff

    def slices_valid(self, slice_counter, number_slices):
        return slice_counter <= number_slices or number_slices == 0

    def z_diff_valid(self, target_z_diff, total_z_diff):
        # target must be high enough to allow at least one slice to be taken
        return target_z_diff >= (total_z_diff + self.acq.slice_thickness/1000)

    def accept(self):
        success = True
        selected_dir = self.lineEdit_baseDir.text()
        # Remove trailing slashes and whitespace
        modified_dir = selected_dir.rstrip(r'\\\/ ')
        # Replace spaces and forward slashes
        modified_dir = modified_dir.replace(' ', '_')
        # Notify user if directory was modified
        if modified_dir != selected_dir:
            self.lineEdit_baseDir.setText(modified_dir)
            self.update_stack_name()
            QMessageBox.information(
                self, 'Base directory name modified',
                'The selected base directory was modified by removing '
                'trailing slashes and whitespace and replacing spaces with '
                'underscores and forward slashes with backslashes.',
                QMessageBox.Ok)
        # Check if path is a valid absolute path
        if not os.path.isabs(modified_dir):
            success = False
            QMessageBox.warning(
                self, 'Error',
                'Please specify the full path to the base directory. It '
                'must be an absolute path, for example: "D:/..."',
                QMessageBox.Ok)
        else:
            # If workspace directory does not yet exist, create it to test
            # whether path is valid and accessible
            workspace_dir = os.path.join(modified_dir, 'workspace')
            try:
                if not os.path.exists(workspace_dir):
                    os.makedirs(workspace_dir)
            except Exception as e:
                success = False
                QMessageBox.warning(
                    self, 'Error',
                    'The selected base directory is invalid or '
                    'inaccessible: ' + str(e),
                    QMessageBox.Ok)
        if isinstance(self.acq.sem, SEM_Mock):
            self.acq.sem.mock_type = self.comboBox_mockType.currentText()
            if 'previous' in self.acq.sem.mock_type.lower():
                mock_dir = self.lineEdit_mockDir.text()
                if os.path.exists(mock_dir) and os.path.isdir(mock_dir):
                    self.acq.sem.previous_acq_dir = mock_dir
                else:
                    success = False
                    QMessageBox.warning(
                        self, 'Error',
                        'The selected mock path does not exist, or is not a directory.',
                        QMessageBox.Ok)

        min_slice_thickness = 5
        if self.acq.syscfg['device']['microtome'] == '6':
            min_slice_thickness = 0
        if min_slice_thickness <= self.spinBox_sliceThickness.value() <= 200:
            self.acq.slice_thickness = self.spinBox_sliceThickness.value()

        number_slices = self.spinBox_numberSlices.value()
        target_z_diff = self.doubleSpinBox_targetZDiff.value()
        total_z_diff = self.doubleSpinBox_totalZDiff.value()
        slice_counter = self.spinBox_sliceCounter.value()

        # 0 index is target number of slices, 1 index is target z depth
        self.acq.use_target_z_diff = self.comboBox_targetType.currentIndex() == 1
        if not self.acq.use_target_z_diff and self.slices_valid(slice_counter, number_slices):
            # Keep target z difference in sync, for readability of config file
            target_z_diff = self.calculate_target_z_diff_from_number_slices()
            self.acq.slice_counter = slice_counter
            self.acq.total_z_diff = total_z_diff
        elif self.acq.use_target_z_diff and self.z_diff_valid(target_z_diff, total_z_diff):
            # Keep number of slices in sync, for readability of config file
            number_slices = self.calculate_number_slices_from_target_z_diff()
            self.acq.slice_counter = slice_counter
            self.acq.total_z_diff = total_z_diff
        self.acq.number_slices = number_slices
        self.acq.target_z_diff = target_z_diff

        self.acq.eht_off_after_stack = self.checkBox_EHTOff.isChecked()
        self.acq.send_metadata = self.checkBox_sendMetaData.isChecked()
        if self.checkBox_sendMetaData.isChecked():
            metadata_server_url = self.lineEdit_metaDataServer.text()
            if not validators.url(metadata_server_url):
                QMessageBox.warning(
                    self, 'Error',
                    'Metadata server URL is invalid. Change the URL in the '
                    'system configuration file.',
                    QMessageBox.Ok)
            self.acq.metadata_project_name = self.lineEdit_projectName.text()
        if self.acq.use_target_z_diff and not self.z_diff_valid(target_z_diff, total_z_diff):
                QMessageBox.warning(
                    self, 'Error',
                    'Target Z depth must be larger than or equal to ' +
                    chr(8710) + 'Z + the current slice thickness', QMessageBox.Ok)
                success = False
        elif not self.acq.use_target_z_diff and not self.slices_valid(slice_counter, number_slices):
                QMessageBox.warning(
                    self, 'Error',
                    'Slice counter must be smaller than or equal to '
                    'target number of slices.', QMessageBox.Ok)
                success = False
        if success:
            self.acq.base_dir = modified_dir
            if not self.acq.use_target_z_diff and self.acq.number_slices > self.acq.slice_counter:
                self.acq.stack_completed = False
            elif self.acq.use_target_z_diff and self.z_diff_valid(self.acq.target_z_diff, self.acq.total_z_diff):
                self.acq.stack_completed = False
            super().accept()
