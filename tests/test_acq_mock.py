import numpy as np
import pytest
from image_io import imread, imread_metadata
from microtome_control_mock import Microtome_Mock
from sem_control_mock import SEM_Mock
from stage import Stage
import utils


TEST_CONFIG_FILE = 'test.ini'
TEST_SYSCONFIG_FILE = 'test.cfg'


def test_acq_mock(tmp_path):
    output_filename = str(tmp_path / 'test.ome.tif')
    stage_position = (1, 1)

    utils.logging_init('TEST', 'Testing')
    config = utils.read_config(TEST_CONFIG_FILE)
    sysconfig = utils.read_config(TEST_SYSCONFIG_FILE)

    sem = SEM_Mock(config, sysconfig)
    microtome = Microtome_Mock(config, sysconfig)
    stage = Stage(sem, microtome, False)
    stage.move_to_xy(stage_position)
    if sem.acquire_frame(output_filename, stage):
        image = imread(output_filename)
        assert isinstance(image, np.ndarray)
        image_metadata = imread_metadata(output_filename)
        assert tuple(image_metadata['position']) == tuple(stage_position)
    else:
        pytest.fail('Acquisition failed')


if __name__ == '__main__':
    import Path
    import tempfile
    test_acq_mock(Path(tempfile.TemporaryDirectory()))
