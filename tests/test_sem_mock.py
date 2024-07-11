# https://docs.pytest.org/en/7.1.x/getting-started.html
# https://docs.pytest.org/en/7.1.x/how-to/tmp_path.html#tmp-path-handling

import numpy as np
import pytest

from image_io import *
from stage import Stage
from test_common import *


class TestSemMock:
    TEST_CONFIG_FILE = 'mock.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    def test_sem_mock_stage(self):
        sem = init_sem_mock(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)
        stage_position = (0.5, 1)
        stage = Stage(sem, None, False)
        stage.move_to_xy(stage_position)
        position = sem.get_stage_xy()
        assert position == stage_position

    def test_sem_mock_acq(self, tmp_path):
        sem = init_sem_mock(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)
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

    test = TestSemMock()
    test.test_sem_mock_stage()
    test.test_sem_mock_acq(Path(tempfile.TemporaryDirectory().name))
