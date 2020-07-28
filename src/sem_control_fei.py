# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module provides the commands to operate the SEM. Only the functions
that are actually required in SBEMimage have been implemented."""

from time import sleep

import json
import pythoncom
from win32com.client import VARIANT  # required for API function calls

from sem_control import SEM
from utils import ERROR_LIST


class SEM_Quanta(SEM):   # or: SEM_XTLib(SEM)

    def __init__(self, config, sysconfig):
        pass
