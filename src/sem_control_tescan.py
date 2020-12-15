# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module provides the implementation of the TESCAN SharkSEM API."""

from sem_control import SEM


class SEM_SharkSEM(SEM):
    """Implements methods for remote control of TESCAN SEMs via the
    SharkSEM remote control API.
    """

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)   # Base class initialization
        if not self.simulation_mode:
            # Connect to remote API / handshake...
            pass
        else:
            self.sem_api = None

    def get_mag(self):
        """Read current magnification from SEM."""
        raise NotImplementedError

    def set_mag(self, target_mag):
        """Set SEM magnification to target_mag."""
        raise NotImplementedError

    def has_fcc(self):
        """Return True if FCC is fitted."""
        return False    # for testing

    # ...
