import numpy as np

from image_io import imwrite
import utils


_sem = None
_microtome = None


def init_log():
    utils.logging_init('TEST', 'Testing')


def init_read_configs(config_filename, test_config_filename):
    config = utils.read_config('../tests/resources/' + config_filename)
    sysconfig = utils.read_config('../tests/resources/' + test_config_filename)
    return config, sysconfig


def init_sem(config_filename, test_config_filename):
    global _sem
    if _sem is None:
        init_log()
        config, sysconfig = init_read_configs(config_filename, test_config_filename)
        device = sysconfig['device']['sem']

        if device == 'ZEISS MultiSEM':
            from sem_control_zeiss import SEM_MultiSEM
            _SEM = SEM_MultiSEM
        elif device.startswith('ZEISS'):
            from sem_control_zeiss import SEM_SmartSEM
            _SEM = SEM_SmartSEM
        elif device.startswith('TESCAN'):
            from sem_control_tescan import SEM_SharkSEM
            _SEM = SEM_SharkSEM
        elif device.startswith('TFS'):
            from sem_control_tfs import SEM_Phenom
            _SEM = SEM_Phenom
        elif device == 'Mock SEM':
            from sem_control_mock import SEM_Mock
            _SEM = SEM_Mock
        else:
            from sem_control import SEM
            _SEM = SEM

        _sem = _SEM(config, sysconfig)
        print(f'SEM: {_sem.device_name}')

    return _sem


def init_microtome(config_filename, test_config_filename):
    global _microtome
    if _microtome is None:
        init_log()
        config, sysconfig = init_read_configs(config_filename, test_config_filename)
        device = sysconfig['device']['microtome']

        if device == 'Gatan 3View':
            from microtome_control_gatan import Microtome_3View
            _Microtome = Microtome_3View
        elif device == 'ConnectomX katana':
            from microtome_control_katana import Microtome_katana
            _Microtome = Microtome_katana
        elif device == 'GCIB':
            from microtome_control_gcib import GCIB
            _Microtome = GCIB
        elif device == 'Mock Microtome':
            from microtome_control_mock import Microtome_Mock
            _Microtome = Microtome_Mock
        else:
            from microtome_control import Microtome
            _Microtome = Microtome

        _microtome = _Microtome(config, sysconfig)
        print(f'Microtome: {_microtome.device_name}')

    return _microtome


def create_image(filename, shape=(1000, 1000), bitsize=8):
    max_val = 2 ** bitsize - 1
    dtype = np.dtype(f'u{bitsize // 8}')
    image = np.random.randint(0, max_val, size=shape, dtype=dtype)
    imwrite(filename, image)
    return image
