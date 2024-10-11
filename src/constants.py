# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This modules provides various constants."""


from enum import Enum
import re


# VERSION contains the current version/release date information for the
# master branch (for example, '2020.07 R2020-07-28'). For the current version
# in the dev (development) branch, it must contain the tag 'dev'.
# Following https://www.python.org/dev/peps/pep-0440/#public-version-identifiers
VERSION = '2024.10.11 dev'


# Default and minimum size of the Viewport canvas.
VP_WIDTH = 1000
VP_HEIGHT = 800

# XY margins between display area and the top-left corner of the Viewport
# window. These margins must be subtracted from the coordinates provided
# when the user clicks onto the window.
VP_MARGIN_X = 20
VP_MARGIN_Y = 40

# Difference in pixels between the Viewport window width/height and the
# Viewport canvas width/height.
VP_WINDOW_DIFF_X = 50
VP_WINDOW_DIFF_Y = 150

# Scaling parameters to convert between the scale factors and the position
# of the zoom sliders in the Viewport (VP) and the Slice-by-Slice viewer
# (SV). Settings for tiles and for OVs are stored separately because
# tiles and OVs usually differ in pixel size by an order of magnitude.


def fov_to_slider_scaling(fov, max_scale=99):
    scale_min, scale_max = 1000 / fov[1], 1000 / fov[0]
    slider_factor = scale_min
    slider_power = (scale_max / scale_min) ** (1 / max_scale)
    return slider_factor, slider_power


VP_FOV_RANGE_MICROTOME_STAGE = (40, 5000)
VP_FOV_RANGE_SEM_STAGE = (50, 200000)
SV_FOV_RANGE_OV = (50, 1000)
SV_FOV_RANGE_TILE = (4, 200)

VP_SCALING_MICROTOME_STAGE = fov_to_slider_scaling(VP_FOV_RANGE_MICROTOME_STAGE)
VP_SCALING_SEM_STAGE = fov_to_slider_scaling(VP_FOV_RANGE_SEM_STAGE)
SV_SCALING_OV = fov_to_slider_scaling(SV_FOV_RANGE_OV)
SV_SCALING_TILE = fov_to_slider_scaling(SV_FOV_RANGE_TILE)


# Number of digits used to format image file names.
OV_DIGITS = 3         # up to 999 overview images
GRID_DIGITS = 4       # up to 9999 grids
TILE_DIGITS = 4       # up to 9999 tiles per grid
SLICE_DIGITS = 5      # up to 99999 slices per stack

PRESSURE_FROM_SEM = {"mbar": 1000, "Pa": 100000, "Torr": 750.061682704}
PRESSURE_TO_SEM = {"mbar": 0.001, "Pa": 0.00001, "Torr": 0.00133322368421}

# Regular expressions for checking user input of tiles and overviews
RE_TILE_LIST = re.compile('^((0|[1-9][0-9]*)[.](0|[1-9][0-9]*))'
                          '([ ]*,[ ]*(0|[1-9][0-9]*)[.](0|[1-9][0-9]*))*$')
RE_OV_LIST = re.compile('^([0-9]+)([ ]*,[ ]*[0-9]+)*$')

# Image format / extensions
DEFAULT_IMAGE_FORMAT = '.ome.tif'
STUBOV_IMAGE_FORMAT = DEFAULT_IMAGE_FORMAT
OV_IMAGE_FORMAT = DEFAULT_IMAGE_FORMAT
GRIDTILE_IMAGE_FORMAT = DEFAULT_IMAGE_FORMAT
FRAME_IMAGE_FORMAT = DEFAULT_IMAGE_FORMAT
TEMP_IMAGE_FORMAT = '.tif'
SCREENSHOT_FORMAT = '.png'

LOG_FILENAME = '../log/SBEMimage.log'
# Custom date/time / format to get '.' instead of ',' as millisecond separator
LOG_FORMAT = '%(asctime)s.%(msecs)03d %(levelname)s %(category)s: %(message)s'
LOG_FORMAT_SCREEN = '%(asctime)s | %(category)-5s : %(message)s'
LOG_FORMAT_DATETIME = '%Y-%m-%d %H:%M:%S'
LOG_MAX_FILESIZE = 10000000
LOG_MAX_FILECOUNT = 20


# TODO: replace values with auto()
class Error(Enum):
    none = 0

    # Movement
    move_init = 42
    move_params = 44
    move_unsafe = 45

    # DM communication
    dm_init = 101
    dm_comm_send = 102
    dm_comm_response = 103
    dm_comm_retval = 104

    # 3View/SBEM hardware
    stage_xy = 201
    stage_z = 202
    stage_z_move = 203
    cutting = 204
    sweeping = 205
    mismatch_z = 206

    # SmartSEM/SEM
    smartsem_api = 301
    grab_image = 302
    grab_incomplete = 303
    frame_frozen = 304
    smartsem_response = 305
    eht = 306
    beam_current = 307
    frame_size = 308
    magnification = 309
    scan_rate = 310
    working_distance = 311
    stig_xy = 312
    beam_blanking = 313
    hp_hv = 314
    fcc = 315
    aperture_size = 316
    high_current = 317
    mode_normal = 318
    brightness_contrast = 319

    # I/O error
    primary_drive = 401
    mirror_drive = 402
    file_overwrite = 403
    image_load = 404

    # Other errors during acq
    sweeps_max = 501
    overview_image = 502
    tile_image_range = 503
    tile_image_compare = 504
    autofocus_smartsem = 505
    autofocus_heuristic = 506
    wd_stig_difference = 507
    metadata_server = 508

    # Reserved for user-defined errors
    test_case = 601

    # Error in configuration
    configuration = 701

    # MultiSEM
    multisem_beam_control = 901
    multisem_imaging = 902
    multisem_alignment = 903
    multisem_failed_to_write = 904


Errors = {
    Error.none: 'No error',

    # Movement
    Error.move_init: 'Movement initialisation error',
    Error.move_params: 'Movement invalid parameter',
    Error.move_unsafe: 'Movement unsafe',

    # DM communication
    Error.dm_init: 'DM script initialisation error',
    Error.dm_comm_send: 'DM communication error (command could not be sent)',
    Error.dm_comm_response: 'DM communication error (unresponsive)',
    Error.dm_comm_retval: 'DM communication error (return values could not be read)',

    # 3View/SBEM hardware
    Error.stage_xy: 'Stage error (XY target position not reached)',
    Error.stage_z: 'Stage error (Z target position not reached)',
    Error.stage_z_move: 'Stage error (Z move too large)',
    Error.cutting: 'Cutting error',
    Error.sweeping: 'Sweeping error',
    Error.mismatch_z: 'Z mismatch error',

    # SmartSEM/SEM
    Error.smartsem_api: 'SmartSEM API initialisation error',
    Error.grab_image: 'Grab image error',
    Error.grab_incomplete: 'Grab incomplete error',
    Error.frame_frozen: 'Frozen frame error',
    Error.smartsem_response: 'SmartSEM unresponsive error',
    Error.eht: 'EHT error',
    Error.beam_current: 'Beam current error',
    Error.frame_size: 'Frame size error',
    Error.magnification: 'Magnification error',
    Error.scan_rate: 'Scan rate error',
    Error.working_distance: 'WD error',
    Error.stig_xy: 'STIG XY error',
    Error.beam_blanking: 'Beam blanking error',
    Error.hp_hv: 'HV/VP error',
    Error.fcc: 'FCC error',
    Error.aperture_size: 'Aperture size error',

    # MultiSEM
    Error.multisem_beam_control: 'Error: beam control',
    Error.multisem_imaging: 'Error: imaging not possible',
    Error.multisem_alignment: 'Error: auto alignment not possible',
    Error.multisem_failed_to_write: 'Error: failed to write metadata or thumbnails',

    # I/O error
    Error.primary_drive: 'Primary drive error',
    Error.mirror_drive: 'Mirror drive error',
    Error.file_overwrite: 'Overwrite file error',
    Error.image_load: 'Load image error',

    # Other errors during acq
    Error.sweeps_max: 'Maximum sweeps error',
    Error.overview_image: 'Overview image error (outside of range)',
    Error.tile_image_range: 'Tile image error (outside of range)',
    Error.tile_image_compare: 'Tile image error (slice-by-slice comparison)',
    Error.autofocus_smartsem: 'Autofocus error (SmartSEM)',
    Error.autofocus_heuristic: 'Autofocus error (heuristic)',
    Error.wd_stig_difference: 'WD/STIG difference error',
    Error.metadata_server: 'Metadata server error',

    # Reserved for user-defined errors
    Error.test_case: 'Test case error',

    # Error in configuration
    Error.configuration: 'Configuration error',

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
    [255, 165, 0],      #6  orange
    [255, 0, 255],      #7  pink
    [173, 216, 230],    #8  grey
    [184, 134, 11],     #9  brown
    [0, 0, 255],        #10 blue (used only for OVs)
    [50, 50, 50],       #11 dark grey for stub OV border
    [128, 0, 128, 80],  #12 transparent violet (to indicate live acq)
    [255, 195, 0]       #13 bright orange (active user flag, measuring tool)
]
