import glob
import os
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QApplication, QMessageBox
from qtpy.uic import loadUi

import constants
import utils


class ExportDlg(QDialog):
    """Export image list in TrakEM2 format."""

    def __init__(self, acq):
        super().__init__()
        self.acq = acq
        loadUi('gui/export_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.pushButton_export.clicked.connect(self.export_list)
        self.spinBox_untilSlice.setValue(int(self.acq.slice_counter))
        self.show()

    def export_list(self):
        self.pushButton_export.setText('Busy')
        self.pushButton_export.setEnabled(False)
        QApplication.processEvents()
        base_dir = self.acq.base_dir
        target_grid_index = str(
            self.spinBox_gridNumber.value()).zfill(constants.GRID_DIGITS)
        pixel_size = self.doubleSpinBox_pixelSize.value()
        start_slice = self.spinBox_fromSlice.value()
        end_slice = self.spinBox_untilSlice.value()
        # Read all imagelist files into memory
        imagelist_str = []
        imagelist_data = []
        file_list = glob.glob(
            os.path.join(base_dir, 'meta', 'logs', 'imagelist*.txt'))
        file_list.sort()
        for file in file_list:
            with open(file) as f:
                imagelist_str.extend(f.readlines())
        if len(imagelist_str) > 0:
            # split strings, store entries in variables, find minimum x and y
            min_x = 10000000
            min_y = 10000000
            for line in imagelist_str:
                elements = line.split(';')
                # elements[0]: relative path to tile image
                # elements[1]: x coordinate in nm
                # elements[2]: y coordinate in nm
                # elements[3]: z coordinate in nm
                # elements[4]: slice number
                slice_number = int(elements[4])
                grid_index = elements[0][7:11]
                if (start_slice <= slice_number <= end_slice
                    and grid_index == target_grid_index):
                    x = int(int(elements[1]) / pixel_size)
                    if x < min_x:
                        min_x = x
                    y = int(int(elements[2]) / pixel_size)
                    if y < min_y:
                        min_y = y
                    imagelist_data.append([elements[0], x, y, slice_number])
            # Subtract minimum values to obtain bounding box with (0, 0) as
            # origin in top-left corner.
            for item in imagelist_data:
                item[1] -= min_x
                item[2] -= min_y
            # Write to output file
            try:
                output_file = os.path.join(base_dir,
                                           'trakem2_imagelist_slice'
                                           + str(start_slice)
                                           + 'to'
                                           + str(end_slice)
                                           + '.txt')
                with open(output_file, 'w') as f:
                    for item in imagelist_data:
                        f.write(item[0] + '\t'
                                + str(item[1]) + '\t'
                                + str(item[2]) + '\t'
                                + str(item[3]) + '\n')
            except Exception as e:
                QMessageBox.warning(
                    self, 'Error',
                    'An error ocurred while writing the output file: ' + str(e),
                    QMessageBox.Ok)
            else:
                QMessageBox.information(
                    self, 'Export completed',
                    f'A total of {len(imagelist_data)} tile entries were '
                    f'processed.\n\nThe output file\n'
                    f'trakem2_imagelist_slice{start_slice}to{end_slice}.txt\n'
                    f'was written to the current base directory\n'
                    f'{base_dir}.',
                    QMessageBox.Ok)
        else:
            QMessageBox.warning(
                self, 'Error',
                'No image metadata found.',
                QMessageBox.Ok)
        self.pushButton_export.setText('Export')
        self.pushButton_export.setEnabled(True)
        QApplication.processEvents()
