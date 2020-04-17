# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This modules provides various constants and helper functions."""

import os
import datetime
import json
import re

import numpy as np

from time import sleep
from queue import Queue
from serial.tools import list_ports

from PyQt5.QtCore import QObject, pyqtSignal

# Size of the Viewport canvas. This is currently fixed and values other
# than 1000 and 800 are not fully supported/tested. In the future, these could
# become parameters to allow resizing of the Viewport window.
VP_WIDTH = 1000
VP_HEIGHT = 800

# XY margins between display area and the top-left corner of the Viewport
# window. These margins must be subtracted from the coordinates provided
# when the user clicks onto the window.
VP_MARGIN_X = 20
VP_MARGIN_Y = 40

# Zoom parameters to convert between the scale factors and the position
# of the zoom sliders in the Viewport (VP) and the Slice-by-Slice viewer
# (SV). Zoom settings for tiles and for OVs are stored separately because
# tiles and OVs usually differ in pixel size by an order of magnitude.
VP_ZOOM_MICROTOME_STAGE = (0.2, 1.05)
VP_ZOOM_SEM_STAGE = (0.0055, 1.085)
SV_ZOOM_OV = (1.0, 1.03)
SV_ZOOM_TILE = (5.0, 1.04)

# Number of digits used to format image file names.
OV_DIGITS = 3         # up to 999 overview images
GRID_DIGITS = 4       # up to 9999 grids
TILE_DIGITS = 4       # up to 9999 tiles per grid
SLICE_DIGITS = 5      # up to 99999 slices per stack

# Regular expressions for checking user input of tiles and overviews
RE_TILE_LIST = re.compile('^((0|[1-9][0-9]*)[.](0|[1-9][0-9]*))'
                          '([ ]*,[ ]*(0|[1-9][0-9]*)[.](0|[1-9][0-9]*))*$')
RE_OV_LIST = re.compile('^([0-9]+)([ ]*,[ ]*[0-9]+)*$')

ERROR_LIST = {
    0: 'No error',

    # First digit 1: DM communication
    101: 'DM script initialization error',
    102: 'DM communication error (command could not be sent)',
    103: 'DM communication error (unresponsive)',
    104: 'DM communication error (return values could not be read)',

    # First digit 2: 3View/SBEM hardware
    201: 'Stage error (XY target position not reached)',
    202: 'Stage error (Z target position not reached)',
    203: 'Stage error (Z move too large)',
    204: 'Cutting error',
    205: 'Sweeping error',
    206: 'Z mismatch error',

    # First digit 3: SmartSEM/SEM
    301: 'SmartSEM API initialization error',
    302: 'Grab image error',
    303: 'Grab incomplete error',
    304: 'Frozen frame error',
    305: 'SmartSEM unresponsive error',
    306: 'EHT error',
    307: 'Beam current error',
    308: 'Frame size error',
    309: 'Magnification error',
    310: 'Scan rate error',
    311: 'WD error',
    312: 'STIG XY error',
    313: 'Beam blanking error',

    # First digit 4: I/O error
    401: 'Primary drive error',
    402: 'Mirror drive error',
    403: 'Overwrite file error',
    404: 'Load image error',

    # First digit 5: Other errors during acq
    501: 'Maximum sweeps error',
    502: 'Overview image error (outside of range)',
    503: 'Tile image error (outside of range)',
    504: 'Tile image error (slice-by-slice comparison)',
    505: 'Autofocus error (SmartSEM)' ,
    506: 'Autofocus error (heuristic)',
    507: 'WD/STIG difference error',
    508: 'Metadata server error',

    # First digit 6: reserved for user-defined errors
    601: 'Test case error',

    # First digit 7: error in configuration
    701: 'Configuration error'
}

# List of selectable colours for grids (0-9), overviews (10)
# acquisition indicator (11):
COLOUR_SELECTOR = [
    [255, 0, 0],        #0  red (default colour for grid 0)
    [0, 255, 0],        #1  green
    [255, 255, 0],      #2  yellow
    [0, 255, 255],      #3  cyan
    [128, 0, 0],        #4  dark red
    [0, 128, 0],        #5  dark green
    [255, 165, 0],      #6  orange (also used for measuring tool)
    [255, 0, 255],      #7  pink
    [173, 216, 230],    #8  grey
    [184, 134, 11],     #9  brown
    [0, 0, 255],        #10 blue (used only for OVs)
    [50, 50, 50],       #11 dark grey for stub OV border
    [128, 0, 128, 80]   #12 transparent violet (to indicate live acq)
]

class Trigger(QObject):
    """A custom QObject for receiving notifications and commands from threads.
    The trigger signal is emitted by calling signal.emit(). The queue can
    be used to send commands: queue.put(cmd) puts a cmd into the
    queue, and queue.get() reads the cmd and empties the queue.
    """
    signal = pyqtSignal()
    queue = Queue()

    def transmit(self, cmd):
        """Transmit a single command."""
        self.queue.put(cmd)
        self.signal.emit()


def try_to_open(file_name, mode):
    """Try to open file and retry twice if unsucessful."""
    file_handle = None
    success = True
    try:
        file_handle = open(file_name, mode)
    except:
        sleep(2)
        try:
            file_handle = open(file_name, mode)
        except:
            sleep(10)
            try:
                file_handle = open(file_name, mode)
            except:
                success = False
    return success, file_handle

def create_subdirectories(base_dir, dir_list):
    """Create subdirectories given in dir_list in the base folder base_dir."""
    try:
        for dir_name in dir_list:
            new_dir = os.path.join(base_dir, dir_name)
            if not os.path.exists(new_dir):
                os.makedirs(new_dir)
        return True, ''
    except Exception as e:
        return False, str(e)

def fit_in_range(value, min_value, max_value):
    """Make the given value fit into the range min_value..max_value"""
    if value < min_value:
        value = min_value
    elif value > max_value:
        value = max_value
    return value

def format_log_entry(msg):
    """Add timestamp and align msg for logging purposes"""
    timestamp = str(datetime.datetime.now())
    # Align colon (msg must begin with a tag of up to five capital letters,
    # such as 'STAGE' followed by a colon)
    i = msg.find(':')
    if i == -1:   # colon not found
        i = 0
    return (timestamp[:22] + ' | ' + msg[:i] + (6-i) * ' ' + msg[i:])

def show_progress_in_console(progress):
    """Show character-based progress bar in console window"""
    print('\r[{0}] {1}%'.format(
        '.' * int(progress/10)
        + ' ' * (10 - int(progress/10)),
        progress), end='')

def ov_save_path(base_dir, stack_name, ov_index, slice_counter):
    return os.path.join(
        base_dir, 'overviews', 'ov' + str(ov_index).zfill(OV_DIGITS),
        stack_name + '_ov' + str(ov_index).zfill(OV_DIGITS)
        + '_s' + str(slice_counter).zfill(SLICE_DIGITS) + '.tif')

def ov_debris_save_path(base_dir, stack_name, ov_index, slice_counter,
                        sweep_counter):
    return os.path.join(
        base_dir, 'overviews', 'debris',
        stack_name + '_ov' + str(ov_index).zfill(OV_DIGITS)
        + '_s' + str(slice_counter).zfill(SLICE_DIGITS)
        + '_' + str(sweep_counter) + '.tif')

def tile_relative_save_path(stack_name, grid_index, tile_index, slice_counter):
    return os.path.join(
        'tiles', 'g' + str(grid_index).zfill(GRID_DIGITS),
        't' + str(tile_index).zfill(TILE_DIGITS),
        stack_name + '_g' + str(grid_index).zfill(GRID_DIGITS)
        + '_t' + str(tile_index).zfill(TILE_DIGITS)
        + '_s' + str(slice_counter).zfill(SLICE_DIGITS) + '.tif')

def rejected_tile_save_path(base_dir, stack_name, grid_index, tile_index,
                            slice_counter, fail_counter):
    return os.path.join(
        base_dir, 'tiles', 'rejected',
        stack_name + '_g' + str(grid_index).zfill(GRID_DIGITS)
        + '_t' + str(tile_index).zfill(TILE_DIGITS)
        + '_s' + str(slice_counter).zfill(SLICE_DIGITS)
        + '_'  + str(fail_counter) + '.tif')

def tile_preview_save_path(base_dir, grid_index, tile_index):
    return os.path.join(
        base_dir, 'workspace', 'g' + str(grid_index).zfill(GRID_DIGITS)
         + '_t' + str(tile_index).zfill(TILE_DIGITS) + '.png')

def tile_reslice_save_path(base_dir, grid_index, tile_index):
    return os.path.join(
        base_dir, 'workspace', 'reslices',
        'r_g' + str(grid_index).zfill(GRID_DIGITS)
        + '_t' + str(tile_index).zfill(TILE_DIGITS) + '.png')

def ov_reslice_save_path(base_dir, ov_index):
    return os.path.join(
        base_dir, 'workspace', 'reslices',
        'r_OV' + str(ov_index).zfill(OV_DIGITS) + '.png')

def tile_id(grid_index, tile_index, slice_counter):
    return (str(grid_index).zfill(GRID_DIGITS)
            + '.' + str(tile_index).zfill(TILE_DIGITS)
            + '.' + str(slice_counter).zfill(SLICE_DIGITS))

def validate_tile_list(input_str):
    input_str = input_str.strip()
    success = True
    if not input_str:
        tile_list = []
    else:
        if RE_TILE_LIST.match(input_str):
            tile_list = [s.strip() for s in input_str.split(',')]
        else:
            tile_list = []
            success = False
    return success, tile_list

def validate_ov_list(input_str):
    input_str = input_str.strip()
    success = True
    if not input_str:
        ov_list = []
    else:
        if RE_OV_LIST.match(input_str):
            ov_list = [int(s) for s in input_str.split(',')]
        else:
            ov_list = []
            success = False
    return success, ov_list

def suppress_console_warning():
    # Suppress TIFFReadDirectory warnings that otherwise flood console window
    print('\x1b[19;1H' + 80*' ' + '\x1b[19;1H', end='')
    print('\x1b[18;1H' + 80*' ' + '\x1b[18;1H', end='')

def calculate_electron_dose(current, dwell_time, pixel_size):
    """Calculate the electron dose.
    The current is multiplied by the elementary charge of an electron
    (1.602 * 10^−19 C) and the dwell time to obtain the total charge per pixel.
    This charge is divided by the area of a single pixel.

    Args:
        current (float): beam current in pA
        dwell_time (float): dwell time in microseconds
        pixel_size (float): xy pixel size in nm

    Returns:
        dose (float): electron dose in electrons per nanometre
    """
    return (current * 10**(-12) / (1.602 * 10**(-19))
            * dwell_time * 10**(-6) / (pixel_size**2))

def get_indexes_from_user_string(userString):
    '''inspired by the substackMaker of ImageJ \n
    https://imagej.nih.gov/ij/developer/api/ij/plugin/SubstackMaker.html
    Enter a range (2-30), a range with increment (2-30-2), or a list (2,5,3)
    '''
    userString = userString.replace(' ', '')
    if ',' in userString and '.' in userString:
        return None
    elif ',' in userString:
        splitIndexes = [int(splitIndex) for splitIndex in userString.split(',')
                        if splitIndex.isdigit()]
        if len(splitIndexes) > 0:
            return splitIndexes
    elif '-' in userString:
        splitIndexes = [int(splitIndex) for splitIndex in userString.split('-')
                        if splitIndex.isdigit()]
        if len(splitIndexes) == 2 or len(splitIndexes) == 3:
            splitIndexes[-1] = splitIndexes[-1] + 1 # inclusive is more natural (2-5 = 2,3,4,5)
            return range(*splitIndexes)
    elif userString.isdigit():
        return [int(userString)]
    return None

def get_days_hours_minutes(duration_in_seconds):
    minutes, seconds = divmod(int(duration_in_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return days, hours, minutes

def get_serial_ports():
    return [port.device for port in list_ports.comports()]

def round_xy(coordinates):
    x, y = coordinates
    return [round(x, 3), round(y, 3)]

# ----------------- Functions for geometric transforms (MagC) ------------------
def affineT(x_in, y_in, x_out, y_out):
    X = np.array([[x, y, 1] for (x,y) in zip(x_in, y_in)])
    Y = np.array([[x, y, 1] for (x,y) in zip(x_out, y_out)])
    aff, res, rank, s = np.linalg.lstsq(X, Y)
    return aff

def applyAffineT(x_in, y_in, aff):
    input = np.array([ [x, y, 1] for (x,y) in zip(x_in, y_in)])
    output = np.dot(input, aff)
    x_out, y_out = output.T[0:2]
    return x_out, y_out

def invertAffineT(aff):
    return np.linalg.inv(aff)

def getAffineRotation(aff):
    return np.rad2deg(np.arctan2(aff[1][0], aff[1][1]))

def getAffineScaling(aff):
    x_out, y_out = applyAffineT([0,1000], [0,1000], aff)
    scaling = (np.linalg.norm([x_out[1]-x_out[0], y_out[1]-y_out[0]])
               / np.linalg.norm([1000,1000]))
    return scaling

def rigidT(x_in,y_in,x_out,y_out):
    A_data = []
    for i in range(len(x_in)):
        A_data.append( [-y_in[i], x_in[i], 1, 0])
        A_data.append( [x_in[i], y_in[i], 0, 1])

    b_data = []
    for i in range(len(x_out)):
        b_data.append(x_out[i])
        b_data.append(y_out[i])

    A = np.matrix( A_data )
    b = np.matrix( b_data ).T
    # Solve
    c = np.linalg.lstsq(A, b)[0].T
    c = np.array(c)[0]

    displacements = []
    for i in range(len(x_in)):
        displacements.append(np.sqrt(
        np.square((c[1]*x_in[i] - c[0]*y_in[i] + c[2] - x_out[i]) +
        np.square(c[1]*y_in[i] + c[0]*x_in[i] + c[3] - y_out[i]))))

    return c, np.mean(displacements)

def applyRigidT(x,y,coefs):
    x,y = map(lambda x: np.array(x),[x,y])
    x_out = coefs[1]*x - coefs[0]*y + coefs[2]
    y_out = coefs[1]*y + coefs[0]*x + coefs[3]
    return x_out,y_out

def getRigidRotation(coefs):
    return np.rad2deg(np.arctan2(coefs[0], coefs[1]))

def getRigidScaling(coefs):
    return coefs[1]
# -------------- End of functions for geometric transforms (MagC) --------------

# ----------------- MagC utils ------------------
def sectionsYAML_to_sections_landmarks(sectionsYAML):
    ''' The two dictionaries 'sections' and 'landmarks'
    are structured the following way.

    Section number N is accessed like this
    sections[N]['center'] : [x,y]
    sections[N]['angle'] : a (in degrees)

    The ROI is defined inside section number N
    sections['tissueROI-N']['center'] : [x,y]
    The ROI defined in one single section can be
    propagated to all other sections.

    "Source" represents the pixel coordinates in the LM overview
    wafer image.
    "Target" represents the dimensioned coordinates in the physical
    stage coordinates.
    landmarks[N]['source']: [x,y]
    landmarks[N]['target']: [x,y]
    '''
    sections = {}
    for sectionId, sectionXYA in sectionsYAML['tissue'].items():
        sections[int(sectionId)] = {
        'center': [float(a) for a in sectionXYA[:2]],
        'angle': float( (-sectionXYA[2] + 90) % 360)}
    if 'tissueROI' in sectionsYAML:
        tissueROIIndex = int(list(sectionsYAML['tissueROI'].keys())[0])
        sections['tissueROI-' + str(tissueROIIndex)] = {
        'center': sectionsYAML['tissueROI'][tissueROIIndex]}

    landmarks = {}
    if 'landmarks' in sectionsYAML:
        for landmarkId, landmarkXY in sectionsYAML['landmarks'].items():
            landmarks[int(landmarkId)] = {
            'source': landmarkXY}
    return sections, landmarks

# # def sections_landmarks_to_sectionsYAML(sections, landmarks):
    # # sectionsYAML = {}
    # # sectionsYAML['landmarks'] = {}
    # # sectionsYAML['tissue'] = {}
    # # sectionsYAML['magnet'] = {}
    # # sectionsYAML['tissueROI'] = {}
    # # sectionsYAML['sourceROIsFromSbemimage'] = {}

    # # for landmarkId, landmarkDic in enumerate(landmarks):
        # # sectionsYAML['landmark'][landmarkId] = landmarkDic['source']
    # # for tissueId, tissueDic in enumerate(sections):
        # # sectionsYAML['tissue'][tissueId] = [
            # # tissueDic['center'][0],
            # # tissueDic['center'][1],
            # # (-tissueDic['angle'] - 90) % 360]

# -------------- End of MagC utils --------------