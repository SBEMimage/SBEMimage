# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2022 Friedrich Miescher Institute for Biomedical Research, Basel,
#   SBEMimage developers, TESCAN Brno, s.r.o.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module provides the implementation of the TESCAN SharkSEM API."""
import time

from sem_control import SEM
from PIL import Image
from typing import Optional, List
import re

try:
    from tescansharksem.sem import Sem as SharkSEM
except:
    pass

__copyright__ = "Copyright (C) 2022 TESCAN Brno, s.r.o."
__author__ = "TESCAN Brno, s.r.o."


class SEM_SharkSEM(SEM):
    """Implements methods for remote control of TESCAN SEMs via the
    SharkSEM remote control API.
    """

    try:
        sem_api: SharkSEM
    except:
        pass
    dwell_time_ns: Optional[int] = None     # ns
    CHANNEL = 0                             # channel is constant now, should not be edited!
    DEFAULT_DETECTOR = 'LE BSE'             # default detector is constant now, should not be edited!
    current_detector = DEFAULT_DETECTOR     # current detector default is LE BSE for now

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)   # Base class initialization
        # Connection to SharkSEM can be acquired even in simulation mode
        # Connect
        timeout = 15 # sec
        # IP address and port should be provided via config file
        self.sem_api: SharkSEM = SharkSEM()
        ret_val = self.sem_api.Connect(self.ip_address, self.port)
        if ret_val != 0:
            raise ConnectionRefusedError('SharkSEM failed to connect. Please make sure TESCAN Essence is running.')
        if self.use_sem_stage:
            # Read current SEM stage coordinates
            self.last_known_x, self.last_known_y, self.last_known_z = (
                self.get_stage_xyz())


    ###########################################################################
    # EMPTY implementation
    ###########################################################################

    def get_stig_xy(self):
        """Read XY stigmation parameters (in %) from SEM, as a tuple"""
        return 0,0

    def set_stig_xy(self, target_stig_x, target_stig_y):
        """Set X and Y stigmation parameters (in %)."""
        return True

    def get_stig_x(self):
        """Read X stigmation parameter (in %) from SEM."""
        return 0

    def set_stig_x(self, target_stig_x):
        """Set X stigmation parameter (in %)."""
        return True

    def get_stig_y(self):
        """Read Y stigmation parameter (in %) from SEM."""
        return 0

    def set_stig_y(self, target_stig_y):
        """Set Y stigmation parameter (in %)."""
        return True

    def get_frame_size(self):
        pass

    ###########################################################################
    # EMPTY implementation - Zeiss-specific functions
    ###########################################################################

    def get_aperture_size(self):
        """Read aperture size (in μm) from SmartSEM."""
        # Zeiss-specific - not implemented for TESCAN
        return -1

    def set_aperture_size(self, aperture_size_index):
        """Save the aperture size (in μm) and set the SEM's beam to this
        aperture size."""
        super().set_aperture_size(aperture_size_index)
        # Setting SEM to target aperture size must be implemented in child class!
        # Zeiss-specific - not implemented for TESCAN
        return False

    def get_high_current(self):
        """Read high current mode from SmartSEM."""
        # Zeiss-specific - not implemented for TESCAN
        return False

    def set_high_current(self, high_current):
        """Save the target high current mode and set the SEM value."""
        super().set_high_current(high_current)
        # Setting SEM to target high current must be implemented in child class!
        # Zeiss-specific - not implemented for TESCAN
        return False

    def has_fcc(self):
        """This is ZEISS-specific"""
        # Zeiss-specific - not implemented for TESCAN
        return False

    ###########################################################################
    # IMPLEMENTED
    ###########################################################################

    def run_autofocus(self):
        """Run autofocus, break if it takes longer than 1 min."""
        MAX_WAIT_S = 60
        SLEEP_S = 0.5
        FLAG_WAIT_D = 1 << 11
        MAX_END_TIME = time.time() + MAX_WAIT_S

        self.sem_api.AutoWDFine(self.CHANNEL)   # TODO - add optional parameters?

        # Is busy Wait D
        while time.time() < MAX_END_TIME:
            if self.sem_api.IsBusy(FLAG_WAIT_D):
                time.sleep(SLEEP_S)
            else:
                return True
        # Did not finish on time
        return False

    def run_autostig(self):
        """Run autostig, break if it takes longer than 1 min."""
        MAX_WAIT_S = 60
        SLEEP_S = 0.5
        FLAG_WAIT_D = 1 << 11
        MAX_END_TIME = time.time() + MAX_WAIT_S

        self.sem_api.AutoStigmators(self.CHANNEL)   # TODO - add optional parameters?

        # Is busy Wait D
        while time.time() < MAX_END_TIME:
            if self.sem_api.IsBusy(FLAG_WAIT_D):
                time.sleep(SLEEP_S)
            else:
                return True
        # Did not finish on time
        return False

    def set_beam_blanking(self, enable_blanking):
        """Enable beam blanking if enable_blanking == True."""
        if enable_blanking:
            self.sem_api.ScSetBlanker(2)
        else:
            self.sem_api.ScSetBlanker(0)
        return True

    def has_vp(self):
        """Return True if VP is fitted."""
        return self.sem_api.VacGetVPMode() == 1

    def save_frame(self, save_path_filename):
        """Save the frame currently displayed in SmartSEM."""
        self.acquire_frame(save_path_filename)

    def acquire_frame(self, save_path_filename, extra_delay=0):
        """Acquire a full frame and save it to save_path_filename.
        All imaging parameters must be applied BEFORE calling this function.
        To avoid grabbing the image before it is acquired completely, an
        additional waiting period after the cycle time (extra_delay, in seconds)
        may be necessary. The delay specified in syscfg (self.DEFAULT_DELAY)
        is added by default for cycle times > 0.5 s."""

        detector_name = self.get_detector()
        # Make sure a valid available detector is selected
        if detector_name not in self.get_detector_list():
            # Select default detector
            detector_name = self.DEFAULT_DETECTOR

        detector: int
        detectors = self.sem_api.DtEnumDetectors()
        patternName: re.Pattern = re.compile(r'det\.(\d+)\.name=' + detector_name)
        matchName = re.search(patternName, detectors)
        if matchName:
            detector_index = matchName.group(1)
        else:
            return False
        patternIndex: re.Pattern = re.compile('det\.' + detector_index + '\.detector=(\d+)')
        matchIndex = re.search(patternIndex, detectors)
        if matchIndex:
            detector = int(matchIndex.group(1))
        else:
            return False

        # Scan
        self.sem_api.ScStopScan()

        CHANNEL = self.CHANNEL
        BITS = 8       # todo - if 16 bits are also made available, review the rest of the function - needs adjustments!

        width = self.__get_scan_window_width_px()
        height = self.__get_scan_window_height_px()

        dimension = max(width, height)
        left = (dimension - width) // 2
        top = (dimension - height) // 2
        right = dimension - left - 1
        bottom = dimension - top - 1

        self.sem_api.DtSelect(CHANNEL, detector)
        self.sem_api.DtEnable(CHANNEL, 1, BITS)

        # start single frame acquisition
        if self.dwell_time_ns is not None:
            self.sem_api.ScScanXY(0, dimension, dimension, left, top, right, bottom, 1, self.dwell_time_ns)
        else:
            self.sem_api.ScScanXY(0, dimension, dimension, left, top, right, bottom, 1)

        # fetch the image (blocking operation), list of strings containing the pixel data is returned
        img_str = self.sem_api.FetchImageEx((0,), width * height)

        # we must stop the scanning even after single scan
        self.sem_api.ScStopScan()

        # create and save the images (only here the 'Image' library is required)
        # todo - some parameters in following functions need to be changed in case of 16 bits
        img = Image.frombuffer("L", (width, height), img_str[0], "raw", "L", 0, 1)  # 8-bit grayscale
        img.save(save_path_filename)

        return True

    def get_chamber_pressure(self):
        """Read current chamber pressure from SmartSEM."""
        return self.sem_api.VacGetPressure(0)

    def get_vp_target(self):
        """Read current VP target pressure from SmartSEM."""
        return self.sem_api.VacGetVPPress()

    def set_hv(self):
        """Set HV (= High Vacuum)."""
        ret = self.sem_api.VacSetVPMode(0)
        return True if ret == 0 else False

    def set_vp(self):
        """Set VP (= Variable Pressure)."""
        ret = self.sem_api.VacSetVPMode(1)
        return True if ret == 0 else False

    def set_vp_target(self, target_pressure):
        """Set the VP target pressure."""
        self.sem_api.VacSetVPPress(target_pressure)
        return True

    def apply_beam_settings(self):
        """Set the SEM to the current target EHT voltage and beam current."""
        self.sem_api.HVSetVoltage(self.target_eht * 1000)
        self.sem_api.SetBeamCurrent(self.target_beam_current)
        while self.sem_api.IsBusy(2 ** 10):
            time.sleep(0.1)
        return True

    def set_mag(self, target_mag):
        """Set SEM magnification to target_mag."""
        pixel_size = self.MAG_PX_SIZE_FACTOR / (self.__get_scan_window_width_px() * target_mag)
        self.set_pixel_size(pixel_size)
        return True

    def get_detector_list(self) -> List[str]:
        """Return a list of all available detectors."""
        detectors: List[str] = []
        detectorEnum = self.sem_api.DtEnumDetectors()
        for match in re.finditer(r'^det\.\d+\.name=([^\n]+)$', detectorEnum, re.MULTILINE):
            detector = match.group(1)
            detectors.append(detector)
        return detectors

    def get_detector(self) -> str:
        """Return the currently selected detector."""
        return self.current_detector

    def set_detector(self, detector_name: str) -> None:
        """Select the detector specified by 'detector_name'."""
        if detector_name in self.get_detector_list():
            self.current_detector = detector_name

    def run_autofocus_stig(self):
        """Run combined autofocus and autostig, break if it takes longer than 1 min."""
        res = self.run_autofocus()
        if res is not True:
            return res
        return self.run_autostig()

    def __get_scan_window_width_px(self) -> int:
        """Returns scan window width in pixels"""
        return self.STORE_RES[self.grab_frame_size_selector][0]

    def __get_scan_window_height_px(self) -> int:
        """Returns scan window height in pixels"""
        return self.STORE_RES[self.grab_frame_size_selector][1]

    def __get_stage_xyz_mm(self) -> [float, float, float]:
        """Return stage x, y, z coordinates in mm
        Shortcut for SharkSEM command, automatically omits unneeded coordinates"""
        x: float  # mm
        y: float  # mm
        z: float  # mm
        try:
            x, y, z, _, _ = self.sem_api.StgGetPosition()
        except:
            try:
                x, y, z, _, _, _ = self.sem_api.StgGetPosition()
            except:
                raise TypeError('Unexpected count of stage coordinates')
        return x, y, z

    def __get_stage_xyz(self) -> [float, float, float]:
        """Return stage x, y, z coordinates in microns"""
        return [coordinate * 1000 for coordinate in self.__get_stage_xyz_mm()]

    def __set_stage_xyz(self, x: Optional[float] = None, y: Optional[float] = None, z: Optional[float] = None):
        """Moves stage to x, y, z coordinates in microns.
        All coordinates are optional. Omitted coordinates will stay unchanged"""
        self.last_known_x, self.last_known_y, self.last_known_z = self.__get_stage_xyz()

        if x is not None:
            self.last_known_x = x
        if y is not None:
            self.last_known_y = y
        if z is not None:
            self.last_known_z = z

        # Get coordinates in [mm]
        x_mm, y_mm, z_mm = (coord / 1000 for coord in (self.last_known_x, self.last_known_y, self.last_known_z))

        # Only set coordinates that need to be set
        # Only set x
        if y is None and z is None:
            self.sem_api.StgMoveTo(x_mm)
        # Only set x, y
        elif z is None:
            self.sem_api.StgMoveTo(x_mm, y_mm)
        # Set x, y, z
        else:
            self.sem_api.StgMoveTo(x_mm, y_mm, z_mm)

        # Wait for stage movement to finish
        while self.sem_api.StgIsBusy():
            time.sleep(0.1)

    def get_stage_x(self):
        """Read X stage position (in micrometres) from SEM."""
        self.last_known_x, _, _ = self.__get_stage_xyz()
        return self.last_known_x

    def get_stage_y(self):
        """Read Y stage position (in micrometres) from SEM."""
        _, self.last_known_y, _ = self.__get_stage_xyz()
        return self.last_known_y

    def get_stage_z(self):
        """Read Z stage position (in micrometres) from SEM."""
        _, _, self.last_known_z = self.__get_stage_xyz()
        return self.last_known_z

    def get_stage_xy(self):
        """Read XY stage position (in micrometres) from SEM, return as tuple"""
        self.last_known_x, self.last_known_y, _ = self.__get_stage_xyz()
        return self.last_known_x, self.last_known_y

    def get_stage_xyz(self):
        """Read XYZ stage position (in micrometres) from SEM, return as tuple"""
        self.last_known_x, self.last_known_y, self.last_known_z = self.__get_stage_xyz()
        return self.last_known_x, self.last_known_y, self.last_known_z

    def move_stage_to_x(self, x):
        """Move stage to coordinate x, provided in microns."""
        self.__set_stage_xyz(x=x)
        return True

    def move_stage_to_y(self, y):
        """Move stage to coordinate y, provided in microns."""
        self.__set_stage_xyz(y=y)
        return True

    def move_stage_to_z(self, z):
        """Move stage to coordinate y, provided in microns."""
        self.__set_stage_xyz(z=z)
        return True

    def move_stage_to_xy(self, coordinates):
        """Move stage to coordinates x and y, provided as tuple or list
        in microns."""
        x, y = coordinates
        self.__set_stage_xyz(x=x, y=y)
        return True

    def get_wd(self):
        """Return current working distance
        (in metres [because SmartSEM uses metres])."""
        return self.sem_api.GetWD() / 1000

    def set_wd(self, target_wd):
        """Set working distance to target working distance (in metres)"""
        self.sem_api.SetWD(target_wd * 1000)
        while self.sem_api.IsBusy(2 ** 10):
            time.sleep(0.1)
        return True

    def sem_stage_busy(self):
        return self.sem_api.StgIsBusy()

    def turn_eht_on(self):
        """Turn EHT (= high voltage) on. Return True if successful,
        otherwise False."""
        self.sem_api.HVBeamOn()
        while self.sem_api.IsBusy(2 ** 10):
            time.sleep(0.1)
        return True

    def turn_eht_off(self):
        """Turn EHT (= high voltage) off. Return True if successful,
        otherwise False."""
        self.sem_api.HVBeamOff()
        while self.sem_api.IsBusy(2 ** 10):
            time.sleep(0.1)
        return True

    def is_eht_on(self):
        """Return True if EHT is on."""
        return self.sem_api.HVGetBeam() == 1

    def is_eht_off(self):
        """Return True if EHT is off. This is not the same as "not is_eht_on()"
        because there are intermediate beam states between on and off."""
        return self.sem_api.HVGetBeam() == 0

    def get_eht(self):
        """Return current SmartSEM EHT setting in kV."""
        return self.sem_api.HVGetVoltage() / 1000

    def set_eht(self, target_eht):
        """Save the target EHT (in kV) and set the EHT to this target value."""
        # Call method in parent class
        super().set_eht(target_eht)
        # target_eht given in kV
        self.sem_api.HVSetVoltage(target_eht * 1000)
        return True

    def is_hv_on(self):
        """Return True if High Vacuum is on."""
        return self.sem_api.VacGetVPMode() == 0

    def is_vp_on(self):
        """Return True if VP is on."""
        return self.sem_api.VacGetVPMode() == 1

    def get_beam_current(self):
        """Read beam current (in pA) from SmartSEM."""
        return self.sem_api.GetBeamCurrent()

    def set_beam_current(self, target_current):
        """Save the target beam current (in pA) and set the SEM's beam to this
        target current."""
        super().set_beam_current(target_current)
        self.sem_api.SetBeamCurrent(target_current)
        while self.sem_api.IsBusy(2 ** 10):
            time.sleep(0.1)
        return True

    def get_mag(self):
        """Read current magnification from SEM."""
        mag = self.MAG_PX_SIZE_FACTOR / (self.__get_scan_window_width_px() * self.get_pixel_size())
        return mag

    def apply_grab_settings(self):
        """Set the SEM to the current grab settings (stored in
        self.grab_dwell_time, self.grab_pixel_size, and
        self.grab_frame_size_selector)."""
        self.apply_frame_settings(
            self.grab_frame_size_selector,
            self.grab_pixel_size,
            self.grab_dwell_time)

    def set_frame_size(self, frame_size_selector):
        """Set SEM to frame size specified by frame_size_selector."""
        self.grab_frame_size_selector = frame_size_selector
        return True

    def apply_frame_settings(self, frame_size_selector, pixel_size, dwell_time):
        """Set SEM to the specified frame settings (frame size, pixel size and
        dwell time)."""
        ret  = self.set_dwell_time(dwell_time)
        ret &= self.set_frame_size(frame_size_selector)
        ret &= self.set_pixel_size(pixel_size)
        return ret

    def get_frame_size_selector(self):
        """Read the current frame size selector from the SEM."""
        # Not possible for SharkSEM, using default/last size
        return False #self.grab_frame_size_selector

    def get_pixel_size(self):
        """Read current magnification from the SEM and convert it into
        pixel size in nm.
        """
        width_px: int = self.__get_scan_window_width_px()
        viewfield_nm = self.sem_api.GetViewField() * 1e6
        pixel_size_nm = viewfield_nm / width_px
        return pixel_size_nm

    def set_pixel_size(self, pixel_size):
        """Set SEM to the magnification corresponding to pixel_size."""
        # pixel_size is in [nm]
        width_px: int = self.__get_scan_window_width_px()
        new_viewfield_nm = width_px * pixel_size
        self.sem_api.SetViewField(new_viewfield_nm * 1e-6)
        while self.sem_api.IsBusy(2 ** 10):
            time.sleep(0.005)
        return True

    def set_scan_rotation(self, angle):
        """Set the scan rotation angle (in degrees)."""
        self.sem_api.SetGeometry(1, -angle, 0)
        return True

    def set_dwell_time(self, dwell_time):
        """Convert dwell time into scan rate and call self.set_scan_rate()
        """
        self.dwell_time_ns = dwell_time * 1000
        return True

    def get_scan_rate(self):
        """Read the current scan rate from the SEM"""
        return self.sem_api.ScGetSpeed() - 1

    def set_scan_rate(self, scan_rate_selector):
        """Set SEM to pixel scan rate specified by scan_rate_selector."""
        self.set_dwell_time(self.DWELL_TIME[scan_rate_selector])

    def disconnect(self):
        """Disconnect from the SEM."""
        self.sem_api.Disconnect()
        return True
