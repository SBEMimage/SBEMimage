import numpy as np

from image_io import imwrite
from microtome_control_mock import Microtome_Mock
from sem_control_mock import SEM_Mock
import utils


_sem = None
_microtome = None


def init_log():
    utils.logging_init('TEST', 'Testing')


def init_read_configs(config_filename, test_config_filename):
    config = utils.read_config('../tests/resources/' + config_filename)
    sysconfig = utils.read_config('../tests/resources/' + test_config_filename)
    return config, sysconfig


def init_mock_sem(config_filename, test_config_filename):
    global _sem
    if _sem is None:
        init_log()
        config, sysconfig = init_read_configs(config_filename, test_config_filename)
        _sem = SEM_Mock(config, sysconfig)
    return _sem


def init_microtome_mock(config_filename, test_config_filename):
    global _microtome
    if _microtome is None:
        init_log()
        config, sysconfig = init_read_configs(config_filename, test_config_filename)
        _microtome = Microtome_Mock(config, sysconfig)
    return _microtome


def create_image(filename, shape=(1000, 1000), bitsize=8):
    max_val = 2 ** bitsize - 1
    dtype = np.dtype(f'u{bitsize // 8}')
    image = np.random.randint(0, max_val, size=shape, dtype=dtype)
    imwrite(filename, image)
    return image
