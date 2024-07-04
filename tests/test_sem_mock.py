import numpy as np
import pytest

from image_io import *
from stage import Stage
from test_common import init_sem_mock


TEST_CONFIG_FILE = 'mock.ini'
TEST_SYSCONFIG_FILE = 'mock.cfg'


def test_sem_mock_stage():
    sem = init_sem_mock(TEST_CONFIG_FILE, TEST_SYSCONFIG_FILE)
    stage_position = (0.5, 1)
    stage = Stage(sem, None, False)
    stage.move_to_xy(stage_position)
    position = sem.get_stage_xy()
    assert position == stage_position


def test_sem_mock_acq(tmp_path):
    sem = init_sem_mock(TEST_CONFIG_FILE, TEST_SYSCONFIG_FILE)
    output_filename = str(tmp_path / 'test.ome.tif')
    stage_position = (0.5, 1)
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
    test_sem_mock_acq(Path(tempfile.TemporaryDirectory().name))
