import pytest

from test_utils import init_microtome_mock


class TestMicrotomeMock:
    TEST_CONFIG_FILE = 'mock.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    @pytest.fixture
    def microtome(self):
        return init_microtome_mock(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)

    def test_microtome_mock(self, microtome):
        stage_position = (0.5, 1)
        duration = microtome.stage_move_duration(0, 0, stage_position[0], stage_position[1])
        assert duration > 0
        microtome.move_stage_to_xy(stage_position)
        position = microtome.get_stage_xy()
        assert position == stage_position
        microtome.do_sweep(0)


if __name__ == '__main__':
    test = TestMicrotomeMock()
    test_microtome = init_microtome_mock(TestMicrotomeMock.TEST_CONFIG_FILE, TestMicrotomeMock.TEST_SYSCONFIG_FILE)
    test.test_microtome_mock(test_microtome)
