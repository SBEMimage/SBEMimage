import pytest

from constants import Error
from test_utils import init_microtome


class TestMicrotome:
    TEST_CONFIG_FILE = 'mock.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    @pytest.fixture
    def microtome(self):
        return init_microtome(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)

    def test(self, microtome):
        stage_position = (0.5, 1)
        z_position = 0.1
        duration = microtome.stage_move_duration(0, 0, stage_position[0], stage_position[1])

        assert duration > 0
        microtome.move_stage_to_xy(stage_position)
        assert tuple(microtome.get_stage_xy()) == tuple(stage_position)
        microtome.move_stage_to_z(z_position)
        assert microtome.get_stage_z() == z_position
        microtome.do_sweep(0)
        assert microtome.error_state == Error.none


if __name__ == '__main__':
    test = TestMicrotome()
    test_microtome = init_microtome(TestMicrotome.TEST_CONFIG_FILE, TestMicrotome.TEST_SYSCONFIG_FILE)
    test.test(test_microtome)
