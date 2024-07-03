import numpy as np
import pytest
from sem_control_mock import SEM_Mock
from stage import Stage
import utils


TEST_CONFIG_FILE = 'array.ini'
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


def test_array_mock():
    # TODO: maybe split up
    sem = init_sem_mock()
    stage_position = (1, 1)
    stage = Stage(sem, None, False)
    stage.move_to_xy(stage_position)
    position = sem.get_stage_xy()
    assert position == stage_position


if __name__ == '__main__':
    test_array_mock()
