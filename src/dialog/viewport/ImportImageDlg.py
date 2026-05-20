import datetime
import os
from qtpy.QtCore import Qt, QSize
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QDialog, QFileDialog, QMessageBox
from qtpy.uic import loadUi

import constants
import utils
from image_io import imread_metadata, imread, imwrite


class ImportImageDlg(QDialog):
    """Import an image into the viewport."""

    def __init__(self, imported_images, viewport_trigger, stage, start_path=None):
        self.start_path = start_path
        self.imported = imported_images
        self.viewport_trigger = viewport_trigger
        super().__init__()
        loadUi('gui/import_image_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.pushButton_selectFile.clicked.connect(self.select_file)
        self.pushButton_selectFile.setIcon(QIcon('img/selectdir.png'))
        self.pushButton_selectFile.setIconSize(QSize(16, 16))

        position = stage.get_center()
        self.doubleSpinBox_posX.setValue(position[0])
        self.doubleSpinBox_posY.setValue(position[1])

    def select_file(self):
        # Let user select image to be imported:
        if self.start_path:
            start_path = self.start_path
        else:
            start_path = 'C:/'
        selected_file = str(QFileDialog.getOpenFileName(
            self, 'Select image',
            start_path,
            filter='Images (*)'
            )[0])

        if selected_file:
            selected_file = os.path.normpath(selected_file)
            self.start_path = selected_file
            self.lineEdit_fileName.setText(selected_file)
            self.lineEdit_name.setText(
                utils.get_image_file_title(selected_file))
            try:
                metadata = imread_metadata(selected_file)
                pixel_size = metadata.get('pixel_size')
                if pixel_size:
                    pixel_size_nm = pixel_size[0] * 1e3
                    self.doubleSpinBox_pixelSize.setValue(pixel_size_nm)
                position = metadata.get('position')
                if position:
                    if isinstance(position[0], (list, tuple)):
                        position = position[0]
                    self.doubleSpinBox_posX.setValue(position[0])
                    self.doubleSpinBox_posY.setValue(position[1])
                rotation = metadata.get('rotation')
                if rotation is not None:
                    self.doubleSpinBox_rotation.setValue(rotation)
            except TypeError:
                QMessageBox.critical(self,
                                     'SBEMimage error',
                                     f'Unsupported image format: {selected_file}',
                                     QMessageBox.Ok)

    def accept(self):
        import_success = False
        error_msg = ''
        source_pixel_size = self.doubleSpinBox_pixelSize.value()
        selected_path = os.path.normpath(
            self.lineEdit_fileName.text())
        selected_filename = os.path.basename(selected_path)
        timestamp = str(datetime.datetime.now())
        # Remove extra characters from timestamp:
        timestamp = timestamp[:19].translate({ord(c): None for c in ' :-.'})
        filename, ext = selected_filename.split('.', 1)
        # format conversion
        if ext.lower() == 'zarr':
            ext = 'ome.zarr'
        elif not ext.lower() == 'ome.zarr':
            ext = 'ome.tif'
        if os.path.isfile(selected_path):
            try:
                source_pixel_size_um = [source_pixel_size * 1e-3] * 2   # nm -> um

                metadata = imread_metadata(selected_path)
                size = metadata['size'][0] * metadata['size'][1]
                if size > 10 * 1e6:
                    # if image dimension > 10MP scale down
                    target_pixel_size = 2 * 1e3
                    target_pixel_size_um = [2, 2]   # reduced pixel size
                else:
                    target_pixel_size = source_pixel_size
                    target_pixel_size_um = source_pixel_size_um

                image = imread(selected_path,
                               source_pixel_size_um=source_pixel_size_um,
                               target_pixel_size_um=target_pixel_size_um,
                               render=False)

                target_path = os.path.join(
                    self.imported.target_dir,
                    filename)
                target_path += '_' + timestamp + '.' + ext
                metadata['pixel_size'] = target_pixel_size_um

                imwrite(target_path, image, metadata=metadata, npyramid_add=constants.DEFAULT_PYRAMID_LEVELS)

                centre_sx_sy = [self.doubleSpinBox_posX.value(), self.doubleSpinBox_posY.value()]
                rotation = self.doubleSpinBox_rotation.value()
                flipped = self.checkBox_flipped.isChecked()
                transparency = self.doubleSpinBox_transparency.value()
                description = self.lineEdit_name.text()
                imported_image = self.imported.add_image(target_path, description, centre_sx_sy, rotation, flipped,
                                                         [], target_pixel_size, True, transparency)
                if imported_image.image is not None:
                    import_success = True

            except Exception as e:
                error_msg = str(e)

        if import_success:
            self.viewport_trigger.transmit('SHOW IMPORTED')
            super().accept()
        else:
            QMessageBox.warning(
                self, 'Error',
                'Error importing image file: ' + error_msg,
                QMessageBox.Ok)
