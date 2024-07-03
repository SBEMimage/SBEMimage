import pytest
from microtome_control_mock import Microtome_Mock
import utils


TEST_CONFIG_FILE = 'mock.ini'
TEST_SYSCONFIG_FILE = 'test.cfg'


_microtome = None


def init_microtome_mock():
    global _microtome
    if _microtome is None:
        utils.logging_init('TEST', 'Testing')
        config = utils.read_config(TEST_CONFIG_FILE)
        sysconfig = utils.read_config(TEST_SYSCONFIG_FILE)
        _microtome = Microtome_Mock(config, sysconfig)
    return _microtome


def test_microtome_mock():
    microtome = init_microtome_mock()
    stage_position = (1, 1)
    duration = microtome.stage_move_duration(0, 0, stage_position[0], stage_position[1])
    assert duration > 0
    microtome.move_stage_to_xy(stage_position)
    position = microtome.get_stage_xy()
    assert position == stage_position
    microtome.do_sweep(0)


if __name__ == '__main__':
    test_microtome_mock()
