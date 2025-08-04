from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QMessageBox
from qtpy.uic import loadUi

import utils


class ImageMonitoringSettingsDlg(QDialog):
    """Adjust settings to monitor overviews and tiles. A test if a given image
    is within mean/SD range is performed for all acquired images if this feature
    is activated. Tile-by-tile comparisons are performed for the selected tiles
    only.
    """
    def __init__(self, image_inspector):
        super().__init__()
        self.img_inspector = image_inspector
        loadUi('gui/image_monitoring_settings_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.show()
        self.spinBox_meanMin.setValue(self.img_inspector.mean_lower_limit)
        self.spinBox_meanMax.setValue(self.img_inspector.mean_upper_limit)
        self.spinBox_stddevMin.setValue(self.img_inspector.stddev_lower_limit)
        self.spinBox_stddevMax.setValue(self.img_inspector.stddev_upper_limit)
        self.lineEdit_monitorTiles.setText(str(
            self.img_inspector.monitoring_tile_list)[1:-1].replace('\'', ''))
        self.doubleSpinBox_meanThreshold.setValue(
            self.img_inspector.tile_mean_threshold)
        self.doubleSpinBox_stdDevThreshold.setValue(
            self.img_inspector.tile_stddev_threshold)

    def accept(self):
        error_str = ''
        self.img_inspector.mean_lower_limit = self.spinBox_meanMin.value()
        self.img_inspector.mean_upper_limit = self.spinBox_meanMax.value()
        self.img_inspector.stddev_lower_limit = self.spinBox_stddevMin.value()
        self.img_inspector.stddev_upper_limit = self.spinBox_stddevMax.value()

        tile_str = self.lineEdit_monitorTiles.text().strip()
        if tile_str == 'all':
            self.img_inspector.monitoring_tile_list = ['all']
        else:
            success, tile_list = utils.validate_tile_list(tile_str)
            if success:
                self.img_inspector.monitoring_tile_list = tile_list
            else:
                error_str = 'List of selected tiles badly formatted.'

        self.img_inspector.tile_mean_threshold = (
            self.doubleSpinBox_meanThreshold.value())
        self.img_inspector.tile_stddev_threshold = (
            self.doubleSpinBox_stdDevThreshold.value())
        if not error_str:
            super().accept()
        else:
            QMessageBox.warning(self, 'Error', error_str, QMessageBox.Ok)
