import numpy as np
import pytest
from image_io import imread, imread_metadata
from sem_control_mock import SEM_Mock
from stage import Stage
import utils


TEST_CONFIG_FILE = 'mock.ini'
TEST_SYSCONFIG_FILE = 'test.cfg'


_sem = None


def init_sem_mock():
    global _sem
    if _sem is None:
        utils.logging_init('TEST', 'Testing')
        config = utils.read_config(TEST_CONFIG_FILE)
        sysconfig = utils.read_config(TEST_SYSCONFIG_FILE)
        _sem = SEM_Mock(config, sysconfig)
    return _sem


def test_sem_mock_stage():
    sem = init_sem_mock()
    # import array data
    # import array image
    # move/rotate array image
    # create array grids
    #assert position == stage_position


def test_sem_mock_acq(tmp_path):
    sem = init_sem_mock()
    output_filename = str(tmp_path / 'test.ome.tif')
    stage_position = (1, 1)
    stage = Stage(sem, None, False)
    stage.move_to_xy(stage_position)

    # TODO: feed data into mock sem
    stage = Stage(sem, None, False)
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

    test_sem_mock_stage()
    test_sem_mock_acq(Path(tempfile.TemporaryDirectory()))
