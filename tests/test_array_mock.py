import numpy as np
import pytest
import sys
from qtpy.QtWidgets import QApplication

from coordinate_system import CoordinateSystem
from image_io import *
from ImportedImage import ImportedImages
from grid_manager import GridManager
from test_common import *


class TestArrayMock:
    TEST_CONFIG_FILE = 'array.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    qapp = QApplication(sys.argv)   # required Qt operations e.g. QPixMap. Needs to remain in context!

    def test_array_mock(self, tmp_path):
        # TODO: maybe split up?
        config, sysconfig = init_read_configs(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)
        cs = CoordinateSystem(config, sysconfig)
        sem = init_sem_mock(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)
        gm = GridManager(config, sem, cs)
        assert len(gm.array_data.get_rois()) > 0
        imported = ImportedImages(config, tmp_path)

        array_image_source_path = '../array/example/wafer_example1.jpg'
        array_image_path = str(tmp_path / 'imported' / 'wafer_example1.ome.tiff')
        metadata = imread_metadata(array_image_source_path)
        source_pixel_size_um = [1, 1]
        target_pixel_size_um = [2, 2]
        target_pixel_size = 2 * 1e3
        image = imread(array_image_source_path,
                       source_pixel_size_um=source_pixel_size_um, target_pixel_size_um=target_pixel_size_um)
        metadata['pixel_size'] = target_pixel_size_um
        imwrite(array_image_path, image, metadata, npyramid_add=4)
        metadata_b = imread_metadata(array_image_path)
        assert metadata_b['pixel_size'] == target_pixel_size_um
        assert len(metadata_b['sizes']) > 1
        image_b = imread(array_image_path)
        assert np.allclose(image, image_b)

        imported.add_image(array_image_path, '', (1000, 2000), 30, False, [], target_pixel_size, True, 0, is_array=True)
        array_image = imported.find_array_image()
        assert array_image
        gm.array_update_data_image_properties(array_image)
        gm.array_create_grids(array_image)
        assert gm.number_grids > 1


if __name__ == '__main__':
    from pathlib import Path
    import tempfile

    path = Path(tempfile.TemporaryDirectory().name)
    TestArrayMock().test_array_mock(path)
