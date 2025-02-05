from imreg_dft import translation
import numpy as np
import os
from math import atan, sqrt, atan2
from skimage.registration import phase_cross_correlation
from typing import Tuple
from qtpy.QtCore import Qt
from qtpy.QtGui import QPixmap
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import constants
import utils
from constants import Error
from image_io import imread


class StageCalibrationDlg(QDialog):
    """Dialog window to calibrate the stage (rotation angles and scale factors)
    and the motor speeds.

    The stage can be calibrated manually by providing shift vectors obtained
    from image comparisons, or with an automated procedure.
    To determine the (microtome) motor speeds, the user needs to run a
    script in Digital Micrograph. TODO: develop automated procedure to update
    motor speeds.
    """

    def __init__(self, coordinate_system, stage, sem, base_dir):
        super().__init__()
        self.cs = coordinate_system
        self.stage = stage
        self.sem = sem
        self.base_dir = base_dir

        self.x_shift_vector = [0, 0]
        self.y_shift_vector = [0, 0]
        self.motor_speed_x, self.motor_speed_y = None, None
        self.finish_trigger = utils.Trigger()
        self.finish_trigger.signal.connect(self.process_pixel_shifts)
        self.finish_trigger_motor_speeds = utils.Trigger()
        self.finish_trigger_motor_speeds.signal.connect(
            self.show_measured_motor_speeds)
        self.update_calc_trigger = utils.Trigger()
        self.update_calc_trigger.signal.connect(self.update_log)
        self.calc_exception = None
        self.busy = False

        # Choose frame_size_selector depending on device:
        # About 2k x 2k is a good default choice
        if self.sem.device_name.startswith("TESCAN"):
            self.frame_size_selector = 5
        elif sem.device_name.startswith("ZEISS"):
            self.frame_size_selector = 2
        else:  # Mock SEM
            self.frame_size_selector = 1

        loadUi('gui/stage_calibration_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.arrow_symbol1.setPixmap(QPixmap('img/arrow.png'))
        self.arrow_symbol2.setPixmap(QPixmap('img/arrow.png'))
        self.lineEdit_EHT.setText('{0:.2f}'.format(self.sem.target_eht))
        params = self.cs.stage_calibration
        self.doubleSpinBox_stageScaleFactorX.setValue(params[0])
        self.doubleSpinBox_stageScaleFactorY.setValue(params[1])
        self.doubleSpinBox_stageRotationX.setValue(params[2])
        self.doubleSpinBox_stageRotationY.setValue(params[3])
        self.doubleSpinBox_motorSpeedX.setValue(self.stage.motor_speed_x)
        self.doubleSpinBox_motorSpeedY.setValue(self.stage.motor_speed_y)
        self.comboBox_dwellTime.addItems(map(str, self.sem.DWELL_TIME))
        self.comboBox_dwellTime.setCurrentIndex(4)
        # TODO: use a list instead:
        self.comboBox_package.addItems(['cv2', 'imreg_dft', 'skimage'])
        self.pushButton_startImageAcq.clicked.connect(
            self.start_stage_calibration_procedure)
        if self.sem.simulation_mode:
            self.pushButton_startImageAcq.setEnabled(False)
        self.pushButton_helpCalibration.clicked.connect(self.show_help)
        self.pushButton_calcStage.clicked.connect(
            self.calculate_calibration_parameters_from_user_input)
        self.pushButton_measureMotorSpeeds.clicked.connect(
            self.measure_motor_speeds)
        # Show current calibration image size and update whenever pixel size
        # is changed by user
        self.show_calibration_image_size()
        self.spinBox_pixelsize.valueChanged.connect(self.show_calibration_image_size)

        # For now, disable motor speed section unless Gatan 3View is used
        if self.stage.device_name() != "Gatan 3View":
            self.doubleSpinBox_motorSpeedX.setEnabled(False)
            self.doubleSpinBox_motorSpeedY.setEnabled(False)
            self.pushButton_measureMotorSpeeds.setEnabled(False)

    def calibration_image_size(self) -> Tuple[float, float]:
        """Return the current size [width, height] of the calibration
        images in micrometres.
        """
        pixel_size = self.spinBox_pixelsize.value()
        resolution = self.sem.STORE_RES[self.frame_size_selector]
        width = resolution[0] * pixel_size / 1000
        height = resolution[1] * pixel_size / 1000
        return width, height

    def show_calibration_image_size(self):
        """Calculate and display the size of the calibration images."""
        width, height = self.calibration_image_size()
        self.label_imageSize.setText(f'{width:.1f} × {height:.1f}')

    def stage_moves_within_image_size(self) -> bool:
        """Check whether the specified X/Y move distances are within the
        calibration image size (with a minimum of 10% overlap expected).
        """
        width, height = self.calibration_image_size()
        move_distance = self.spinBox_shift.value()
        return ((width - move_distance >= 0.1 * width) and
                (height - move_distance >= 0.1 * height))

    def measure_motor_speeds(self):
        """Run the measurement routine in a thread."""
        self.busy = True  # This prevents user from closing the dialog window
        self.pushButton_measureMotorSpeeds.setEnabled(False)
        self.pushButton_startImageAcq.setEnabled(False)
        self.pushButton_measureMotorSpeeds.setText('Please wait... (~1 min)')
        utils.run_log_thread(self.run_motor_speed_measurement)

    def run_motor_speed_measurement(self):
        self.motor_speed_x, self.motor_speed_y = (
            self.stage.measure_motor_speeds())
        self.finish_trigger_motor_speeds.signal.emit()

    def show_measured_motor_speeds(self):
        self.busy = False
        self.pushButton_measureMotorSpeeds.setEnabled(True)
        self.pushButton_startImageAcq.setEnabled(True)
        self.pushButton_measureMotorSpeeds.setText('Measure XY motor speeds')
        if self.motor_speed_x is None or self.stage.error_state != Error.none:
            self.stage.reset_error_state()
            QMessageBox.warning(self, 'Error',
                                'XY motor speed measurement failed.',
                                QMessageBox.Ok)
            return
        user_choice = QMessageBox.information(
            self, 'Measured XY motor speeds',
            'Results:\nMotor speed X: ' + '{0:.1f}'.format(self.motor_speed_x)
            + ';\nMotor speed Y: ' + '{0:.1f}'.format(self.motor_speed_y)
            + '\n\nDo you want to use these values?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_choice == QMessageBox.Ok:
            self.doubleSpinBox_motorSpeedX.setValue(self.motor_speed_x)
            self.doubleSpinBox_motorSpeedY.setValue(self.motor_speed_y)

    def show_help(self):
        QMessageBox.information(
            self, 'Stage calibration procedure',
            'If you click on "Start automatic calibration", '
            'three images will be acquired and saved in the current base '
            'directory: start.tif, shift_x.tif, shift_y.tif. '
            'You can set the pixel size and dwell time for these images and '
            'specify how far the stage should move along the X and the Y axis. '
            'The X/Y moves must be small enough to allow some overlap between '
            'the test images. The frame size is set automatically. '
            'Make sure that structure is visible in the images, and that the '
            'beam is focused.\n'
            'The current stage position will be used as the starting '
            'position. The recommended starting position is the centre of the '
            'stage (0, 0).\n'
            'Shift vectors between the acquired images will be computed using '
            'a function from the selected package (cv2, imreg_dft or skimage). '
            'Angles and scale factors will then be computed from these '
            'shifts.\n\n'
            'Alternatively, you can manually provide the pixel shifts by '
            'looking at the calibration images start.tif, shift_x.tif, and '
            'shift_y.tif and measuring the difference (with ImageJ, for '
            'example) in the XY pixel position for some feature in the image. '
            'Click on "Calculate" to calculate the calibration parameters '
            'from these shifts.',
            QMessageBox.Ok)

    def start_stage_calibration_procedure(self):
        """Acquire three images to be used for the stage calibration.
        See text in information message box for explanation.
        """
        if not self.sem.is_eht_on():
            QMessageBox.warning(
                self, 'EHT off', 'EHT / high voltage is off. Please turn '
                'it on before starting the calibration.', QMessageBox.Ok)
            return

        if not self.stage_moves_within_image_size():
            QMessageBox.warning(
                self, 'X/Y move distance too large',
                'Ensure that the specified distance for X/Y moves '
                'is smaller than the width and height of the calibration '
                'images, so that at least 10% overlap is achieved.', QMessageBox.Ok)
            return

        reply = QMessageBox.information(
            self, 'Start calibration procedure',
            'This will acquire three images and save them in the current base '
            'directory: start.tif, shift_x.tif, shift_y.tif. '
            'Structure must be visible in the images, and the beam must be '
            'focused.\nThe current stage position will be used as the starting '
            'position. The recommended starting position is the centre of the '
            'stage (0, 0). Angles and scale factors will be computed from the '
            'shifts between the acquired test images.\n'
            'Proceed?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if reply == QMessageBox.Ok:
            self.busy = True
            self.plainTextEdit_calibLog.setPlainText('Acquiring images...')
            self.pushButton_startImageAcq.setText('Busy')
            self.pushButton_startImageAcq.setEnabled(False)
            self.pushButton_measureMotorSpeeds.setEnabled(False)
            self.pushButton_calcStage.setEnabled(False)
            # Acquire images in thread
            utils.run_log_thread(self.calibration_images_acq_thread)

    def calibration_images_acq_thread(self):
        """Acquisition thread for three images used for the stage calibration.
        Frame settings are fixed for now. Currently no error handling. XY shifts
        are computed from images with imreg_dft or skimage.
        """
        shift = self.spinBox_shift.value()
        pixel_size = self.spinBox_pixelsize.value()
        dwell_time = self.sem.DWELL_TIME[self.comboBox_dwellTime.currentIndex()]

        self.sem.apply_frame_settings(
            self.frame_size_selector, pixel_size, dwell_time)

        start_x, start_y = self.stage.get_xy()

        start_path = os.path.join(self.base_dir, 'start' + constants.TEMP_IMAGE_FORMAT)
        shift_x_path = os.path.join(self.base_dir, 'shift_x' + constants.TEMP_IMAGE_FORMAT)
        shift_y_path = os.path.join(self.base_dir, 'shift_y' + constants.TEMP_IMAGE_FORMAT)

        # Acquire first image at starting position
        self.sem.acquire_frame(start_path)
        # Shift along X stage
        self.stage.move_to_xy((start_x + shift, start_y))
        # Second image, at new X position (Y unchanged from starting position)
        self.sem.acquire_frame(shift_x_path)
        # Shift along Y direction, X back to starting position
        self.stage.move_to_xy((start_x, start_y + shift))
        # Acquire third and final image, at new Y position
        self.sem.acquire_frame(shift_y_path)
        # Move back to starting position
        self.stage.move_to_xy((start_x, start_y))
        # Show in log that calculation begins now
        self.update_calc_trigger.signal.emit()
        # Load images and calculate shifts:
        start_img = utils.grayscale_image(imread(start_path))
        shift_x_img = utils.grayscale_image(imread(shift_x_path))
        shift_y_img = utils.grayscale_image(imread(shift_y_path))

        self.calc_exception = None
        try:
            # # [::-1] to use x, y, z order
            if self.comboBox_package.currentIndex() == 0:  # cv2 calculation selected
                start_img = (start_img*255).astype(np.uint8)
                shift_x_img = (shift_x_img*255).astype(np.uint8)
                shift_y_img = (shift_y_img*255).astype(np.uint8)
                x_shift = utils.align_images_cv2(shift_x_img, start_img)
                y_shift = utils.align_images_cv2(shift_y_img, start_img)
            elif self.comboBox_package.currentIndex() == 1:
                x_shift = translation(
                    start_img, shift_x_img, filter_pcorr=3)['tvec'][::-1]
                y_shift = translation(
                    start_img, shift_y_img, filter_pcorr=3)['tvec'][::-1]
            else:  # use skimage.phase_cross_correlation
                x_shift = phase_cross_correlation(start_img, shift_x_img)[0][::-1]
                y_shift = phase_cross_correlation(start_img, shift_y_img)[0][::-1]
            x_shift = x_shift.astype(int)
            y_shift = y_shift.astype(int)
            self.x_shift_vector = [x_shift[0], x_shift[1]]
            self.y_shift_vector = [y_shift[0], y_shift[1]]
        except Exception as e:
            utils.log_exception(str(e))
            self.calc_exception = str(e)
        self.finish_trigger.signal.emit()

    def update_log(self):
        self.plainTextEdit_calibLog.appendPlainText(
            'Now computing pixel shifts...')

    def process_pixel_shifts(self):
        """Show the pixel shifts computed from the calibration images, and
        calculate the calibration parameters from these shifts.
        """
        self.pushButton_startImageAcq.setText('Start')
        self.pushButton_startImageAcq.setEnabled(True)
        self.pushButton_measureMotorSpeeds.setEnabled(True)
        self.pushButton_calcStage.setEnabled(True)
        if self.calc_exception is None:
            # Show the vectors in the textbox and the spinboxes
            self.plainTextEdit_calibLog.setPlainText(
                'Shift_X: [{0:.1f}, {1:.1f}], '
                'Shift_Y: [{2:.1f}, {3:.1f}]'.format(
                *self.x_shift_vector, *self.y_shift_vector))
            # Absolute values for the GUI
            if self.comboBox_package.currentIndex() == 2:
                self.spinBox_x2x.setValue(abs(self.x_shift_vector[0]))
                self.spinBox_x2y.setValue(abs(self.x_shift_vector[1]))
                self.spinBox_y2x.setValue(abs(self.y_shift_vector[0]))
                self.spinBox_y2y.setValue(abs(self.y_shift_vector[1]))
            else:
                self.spinBox_x2x.setValue(self.x_shift_vector[0])
                self.spinBox_x2y.setValue(self.x_shift_vector[1])
                self.spinBox_y2x.setValue(self.y_shift_vector[0])
                self.spinBox_y2y.setValue(self.y_shift_vector[1])

            # Now calculate parameters:
            self.calculate_calibration_parameters()
        else:
            QMessageBox.warning(
                self, 'Error',
                'An exception occured while computing the translations: '
                + self.calc_exception,
                QMessageBox.Ok)
            self.busy = False

    def calculate_calibration_parameters(self):
        """Calculate the calibration parameters (angles and scale factors) from
        the current shift vectors.
        """
        shift = self.spinBox_shift.value()
        pixel_size = self.spinBox_pixelsize.value()

        # Use absolute values for now, TODO: revisit for the Sigma stage
        delta_xx, delta_xy = (
            abs(self.x_shift_vector[0]), abs(self.x_shift_vector[1]))
        delta_yx, delta_yy = (
            abs(self.y_shift_vector[0]), abs(self.y_shift_vector[1]))
        # Rotation angles (in radians)
        rot_x = atan(delta_xy/delta_xx)
        rot_y = atan(delta_yx/delta_yy)
        # Scale factors
        scale_x = shift / (sqrt(delta_xx**2 + delta_xy**2) * pixel_size / 1000)
        scale_y = shift / (sqrt(delta_yx**2 + delta_yy**2) * pixel_size / 1000)

        # Alternative calc.
        x_abs = np.linalg.norm(self.x_shift_vector)
        y_abs = np.linalg.norm(self.y_shift_vector)
        # Rotation angles:
        rot_x_alt = np.arccos(self.x_shift_vector[0] / x_abs)
        rot_y_alt = np.arccos(self.y_shift_vector[1] / y_abs)
        # Scale factors:
        scale_x_alt = shift / (x_abs * pixel_size / 1000)
        scale_y_alt = shift / (y_abs * pixel_size / 1000)

        # Alternative calc. with atan2
        # This only works if the reference vector is (0, 0)
        rot2_x = atan2(self.x_shift_vector[1], self.x_shift_vector[0])
        rot2_y = atan2(self.y_shift_vector[0], self.y_shift_vector[1])

        scale_x = scale_x_alt
        scale_y = scale_y_alt
        rot_x = rot_x_alt
        rot_y = rot_y_alt

        self.busy = False
        user_choice = QMessageBox.information(
            self, 'Calculated parameters',
            'Results:\n'
            + 'Scale factor X: ' + '{0:.5f}'.format(scale_x)
            + ';\nScale factor Y: ' + '{0:.5f}'.format(scale_y)
            + '\nRotation X: ' + '{0:.5f}'.format(rot_x)
            + ';\nRotation Y: ' + '{0:.5f}'.format(rot_y)
            + '\n\nDo you want to use these values?',
            QMessageBox.Ok | QMessageBox.Cancel)
        if user_choice == QMessageBox.Ok:
            self.doubleSpinBox_stageScaleFactorX.setValue(scale_x)
            self.doubleSpinBox_stageScaleFactorY.setValue(scale_y)
            self.doubleSpinBox_stageRotationX.setValue(rot_x)
            self.doubleSpinBox_stageRotationY.setValue(rot_y)

    def calculate_calibration_parameters_from_user_input(self):
        """Calculate the rotation angles and scale factors from the user input.
        The user provides the pixel position of any object that can be
        identified in all three acquired test images. From this, the program
        calculates the difference the object was shifted in pixels, and the
        angle with respect to the x or y axis.
        """
        # Pixel position input from GUI
        x1x = self.spinBox_x1x.value()
        x1y = self.spinBox_x1y.value()
        x2x = self.spinBox_x2x.value()
        x2y = self.spinBox_x2y.value()
        y1x = self.spinBox_y1x.value()
        y1y = self.spinBox_y1y.value()
        y2x = self.spinBox_y2x.value()
        y2y = self.spinBox_y2y.value()

        # Distances in pixels
        delta_xx = x2x - x1x
        delta_xy = x2y - x1y
        delta_yx = y2x - y1x
        delta_yy = y2y - y1y
        if delta_xx == 0 or delta_yy == 0:
            QMessageBox.warning(
                self, 'Error computing stage calibration',
                'Please check your input values.',
                QMessageBox.Ok)
        else:
            self.plainTextEdit_calibLog.setPlainText(
                'Using pixel shifts specified on the right side as input...')
            self.x_shift_vector = [delta_xx, delta_xy]
            self.y_shift_vector = [delta_yx, delta_yy]
            self.calculate_calibration_parameters()

    def accept(self):
        if not self.busy:
            stage_params = [
                self.doubleSpinBox_stageScaleFactorX.value(),
                self.doubleSpinBox_stageScaleFactorY.value(),
                self.doubleSpinBox_stageRotationX.value(),
                self.doubleSpinBox_stageRotationY.value()]
            # Save and apply new stage calibration and motor speeds
            self.cs.save_stage_calibration(self.sem.target_eht, stage_params)
            self.cs.apply_stage_calibration()

            if self.stage.device_name() == "Gatan 3View":
                success = self.stage.set_motor_speeds(
                    self.doubleSpinBox_motorSpeedX.value(),
                    self.doubleSpinBox_motorSpeedY.value())
                if not success:
                    QMessageBox.warning(
                        self, 'Error updating motor speeds',
                        'Motor speeds could not be updated.',
                        QMessageBox.Ok)

            super().accept()

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if not self.busy:
            event.accept()
        else:
            event.ignore()
