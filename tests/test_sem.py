# https://docs.pytest.org/en/7.1.x/getting-started.html
# https://docs.pytest.org/en/7.1.x/how-to/tmp_path.html#tmp-path-handling

import numpy as np
import pytest

from image_io import *
from stage import Stage
from test_utils import init_sem


class TestSem:
    TEST_CONFIG_FILE = 'mock.ini'
    TEST_SYSCONFIG_FILE = 'mock.cfg'

    @pytest.fixture
    def sem(self):
        return init_sem(self.TEST_CONFIG_FILE, self.TEST_SYSCONFIG_FILE)

    def test_stage(self, sem):
        stage_position = (0.5, 1)
        stage = Stage(sem, None, False)
        stage.move_to_xy(stage_position)
        position = sem.get_stage_xy()
        assert position == stage_position

    def test_detector(self, sem):
        detectors = sem.get_detector_list()
        assert len(detectors) > 0
        detector = detectors[0]
        sem.set_detector(detector)
        assert sem.get_detector() == detector

    def test_beam(self, sem):
        beam_voltage = 5    # [kV]
        beam_current = 300  # [pA]
        sem.set_eht(beam_voltage)
        assert sem.get_eht() == beam_voltage
        sem.set_beam_current(beam_current)
        assert sem.get_beam_current() == beam_current
        sem.set_beam_blanking(True)

    def test_acq_settings(self, sem):
        stage_position = (0.5, 1)
        mag = 2500
        frame_size_selector = 0
        pixel_size = 40   # [nm]
        scan_rate_selector = 0
        dwell_time = 0.1
        scan_rotation = 30
        wd = 0.01
        stig_xy = 0.001, -0.001

        sem.move_stage_to_xy(stage_position)
        assert sem.get_stage_xy() == stage_position
        sem.set_frame_size(frame_size_selector)
        assert sem.get_frame_size_selector() == frame_size_selector
        assert sem.get_frame_size() == sem.STORE_RES[frame_size_selector]
        sem.set_pixel_size(pixel_size)
        assert sem.get_pixel_size() == pixel_size
        sem.set_mag(mag)
        assert sem.get_mag() == mag
        #sem.set_scan_rate(scan_rate_selector)
        #assert sem.get_scan_rate() == scan_rate_selector
        sem.set_dwell_time(dwell_time)
        assert sem.dwell_time == dwell_time
        sem.set_scan_rotation(scan_rotation)
        assert sem.scan_rotation == scan_rotation
        sem.set_wd(wd)
        assert sem.get_wd() == wd
        sem.set_stig_xy(*stig_xy)
        assert tuple(sem.get_stig_xy()) == tuple(stig_xy)

    def test_acq(self, sem, tmp_path):
        output_filename = str(tmp_path / 'test.ome.tif')
        pixel_size = 40   # [nm]
        pixel_size_um = pixel_size / 1e3
        stage_position = (0.5, 1)
        stage = Stage(sem, None, False)
        stage.move_to_xy(stage_position)

        sem.set_pixel_size(pixel_size)
        stage = Stage(sem, None, False)
        if sem.acquire_frame(output_filename, stage):
            image = imread(output_filename)
            assert isinstance(image, np.ndarray)
            image_metadata = imread_metadata(output_filename)
            assert image_metadata['pixel_size'][0] == pixel_size_um
            assert tuple(image_metadata['position']) == tuple(stage_position)
        else:
            pytest.fail('Acquisition failed')


if __name__ == '__main__':
    from pathlib import Path
    import tempfile

    test = TestSem()
    test_sem = init_sem(TestSem.TEST_CONFIG_FILE, TestSem.TEST_SYSCONFIG_FILE)
    temp_path = Path(tempfile.TemporaryDirectory().name)
    test.test_stage(test_sem)
    test.test_detector(test_sem)
    test.test_beam(test_sem)
    test.test_acq_settings(test_sem)
    test.test_acq(test_sem, temp_path)
