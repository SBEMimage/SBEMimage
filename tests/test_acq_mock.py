import pytest
from configparser import ConfigParser

from sem_control_mock import SEM_Mock
from microtome_control_mock import Microtome_Mock
import utils


TEST_CONFIG_FILE = 'test.ini'
TEST_SYSCONFIG_FILE = 'test.cfg'


def read_config(filename):
    config = ConfigParser()
    with open(filename, 'r') as file:
        config.read_file(file)
    return config


def test_acq_mock():
    utils.logging_init('TEST', 'Testing')
    config = read_config(TEST_CONFIG_FILE)
    sysconfig = read_config(TEST_SYSCONFIG_FILE)

    sem = SEM_Mock(config, sysconfig)
    microtome = Microtome_Mock(config, sysconfig)


if __name__ == '__main__':
    test_acq_mock()
