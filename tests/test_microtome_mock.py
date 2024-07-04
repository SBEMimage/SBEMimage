import pytest

from test_common import init_microtome_mock


TEST_CONFIG_FILE = 'mock.ini'
TEST_SYSCONFIG_FILE = 'mock.cfg'


def test_microtome_mock():
    microtome = init_microtome_mock(TEST_CONFIG_FILE, TEST_SYSCONFIG_FILE)
    stage_position = (0.5, 1)
    duration = microtome.stage_move_duration(0, 0, stage_position[0], stage_position[1])
    assert duration > 0
    microtome.move_stage_to_xy(stage_position)
    position = microtome.get_stage_xy()
    assert position == stage_position
    microtome.do_sweep(0)


if __name__ == '__main__':
    test_microtome_mock()
