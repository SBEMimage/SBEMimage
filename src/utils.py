# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This modules provides various helper functions."""

import csv
import os
import datetime
import logging
import threading
import cv2
import numpy as np
import glob
from os.path import basename
from typing import Tuple, List

from configparser import ConfigParser
from time import sleep
from queue import Queue
from logging import StreamHandler
from logging.handlers import RotatingFileHandler

from skimage import draw
from skimage.transform import ProjectiveTransform
from skimage.measure import ransac
from skimage.io import imread, imsave, ImageCollection
from skimage.util import crop, img_as_ubyte
from skimage.registration import phase_cross_correlation
from skimage.transform import rescale, ProjectiveTransform

from serial.tools import list_ports
from qtpy.QtCore import QObject, Signal, QSize
from qtpy.QtGui import QIcon, QPixmap, QImage, QTransform
from scipy.ndimage import maximum_filter
from scipy.ndimage import interpolation
from shapely.geometry import Polygon, Point
from serial.tools import list_ports
from constants import *


window_icon = QIcon()


def get_window_icon():
    if window_icon.isNull():
        window_icon.addFile('img/icon_16px.ico', QSize(16, 16))
        window_icon.addFile('img/icon_48px.ico', QSize(48, 48))
    return window_icon


class Trigger(QObject):
    """A custom QObject for receiving notifications and commands from threads.
    The trigger signal is emitted by calling signal.emit(). The queue can
    be used to send commands: queue.put(cmd) puts a cmd into the
    queue, and queue.get() reads the cmd and empties the queue.
    """
    signal = Signal()
    queue = Queue()

    def transmit(self, cmd, *args, **kwargs):
        """Transmit a single command."""
        cmd = {'msg': cmd, 'args': args, 'kwargs': kwargs}
        self.queue.put(cmd)
        self.signal.emit()


class QtTextHandler(StreamHandler):
    def __init__(self):
        StreamHandler.__init__(self)
        self.buffer = []
        self.qt_trigger = None

    def set_output(self, qt_trigger):
        self.qt_trigger = qt_trigger
        for message in self.buffer:
            self.qt_trigger.transmit(message)
        self.buffer.clear()

    def emit(self, record):
        message = self.format(record)
        # Filter stack trace from main view
        if 'Traceback' in message:
            message = (message[:message.index('Traceback')]
                       + 'EXCEPTION occurred: See /SBEMimage/log/SBEMimage.log '
                       'and output in console window for details.')
        if self.qt_trigger:
            self.qt_trigger.transmit(message)
        else:
            self.buffer.append(message)


def run_log_thread(thread_function, *args):
    def run_log():
        try:
            thread_function(*args)
        except Exception as e:
            print('\nEXCEPTION occurred: See /SBEMimage/log/SBEMimage.log '
                  'and output in console window for details.\n')
            log_exception(str(e))

    thread = threading.Thread(target=run_log)
    thread.start()


logger: logging.Logger
qt_text_handler = QtTextHandler()


def logging_init(*message):
    global logger
    validate_output_path(LOG_FILENAME, is_file=True)
    logger = logging.getLogger("SBEMimage")
    logger.setLevel(logging.INFO)   # important: anything below this will be filtered irrespective of handler level
    # logging_add_handler(StreamHandler(), level=logging.ERROR)   # filter messages to console log handler
    logging_add_handler(RotatingFileHandler(
        LOG_FILENAME, maxBytes=LOG_MAX_FILESIZE, backupCount=LOG_MAX_FILECOUNT, encoding='utf-8'))
    logging_add_handler(qt_text_handler, format=LOG_FORMAT_SCREEN)

    # logger.propagate = False

    if message:
        log_info(*message)


def logging_add_handler(handler, format=LOG_FORMAT, date_format=LOG_FORMAT_DATETIME, level=logging.INFO):
    handler.setFormatter(logging.Formatter(fmt=format, datefmt=date_format))
    handler.setLevel(level)
    logger.addHandler(handler)


def set_log_text_handler(qt_trigger):
    qt_text_handler.set_output(qt_trigger)


def log(level, *pos_params, **key_params):
    category = ""
    if key_params:
        category = key_params['category']
        message = key_params['message']
    else:
        pos_params = pos_params[0]
        if len(pos_params) > 1:
            category = pos_params[0]
            message = " ".join(pos_params[1:])
        else:
            message = pos_params[0]
    logger.log(level=level, msg=message, extra={'category': category})


def log_info(*params):
    log(logging.INFO, params)


def log_warning(*params):
    log(logging.WARNING, params)


def log_error(*params):
    log(logging.ERROR, params)


def log_critical(*params):
    log(logging.CRITICAL, params)


def log_exception(message=""):
    logger.exception(message, extra={'category': 'EXC'})


def str_to_bool(value):
    if isinstance(value, str):
        return value.lower() == 'true'
    else:
        return bool(value)


def read_config(filename):
    config = ConfigParser()
    with open(filename, 'r') as file:
        config.read_file(file)
    return config


def validate_output_path(path, is_file=False):
    if is_file:
        path = os.path.dirname(path)
    if not os.path.exists(path):
        os.makedirs(path)


def try_to_open(file_name, mode):
    """Try to open file and retry twice if unsuccessful."""
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


def try_to_remove(file_name):
    """Try to remove file and retry twice if unsuccessful."""
    try:
        os.remove(file_name)
    except:
        sleep(2)
        try:
            os.remove(file_name)
        except:
            sleep(10)
            try:
                os.remove(file_name)
            except:
                return False
    return True


def load_csv(file_name):
    with open(file_name, 'r') as file:
        csv_reader = csv.reader(file)
        content = []
        for row in csv_reader:
            if len(row) == 1:
                row = row[0]
            content.append(row)
    return content


def create_subdirectories(base_dir, dir_list):
    """Create subdirectories given in dir_list in the base folder base_dir."""
    try:
        for dir_name in dir_list:
            validate_output_path(os.path.join(base_dir, dir_name))
        return True, ''
    except Exception as e:
        return False, str(e)


# TODO (BT): Remove format_log_entry, run through standard logging instead
def format_log_entry(msg):
    """Add timestamp and align msg for logging purposes"""
    timestamp = str(datetime.datetime.now())
    # Align colon (msg must begin with a tag of up to five capital letters,
    # such as 'STAGE' followed by a colon)
    i = msg.find(':')
    if i == -1:   # colon not found
        i = 0
    return (timestamp[:19] + ' | ' + msg[:i] + (6-i) * ' ' + msg[i:])

def format_wd_stig(wd, stig_x, stig_y):
    """Return a formatted string of focus parameters."""
    return ('WD/STIG_XY: '
            + '{0:.6f}'.format(wd * 1000)  # wd in metres, show in mm
            + ', {0:.6f}'.format(stig_x)
            + ', {0:.6f}'.format(stig_y))

def show_progress_in_console(progress):
    """Show character-based progress bar in console window"""
    print('\r[{0}] {1}%'.format(
        '.' * int(progress/10)
        + ' ' * (10 - int(progress/10)),
        progress), end='')

def calc_rotated_rect(polygon):
    return cv2.minAreaRect(np.array(polygon, dtype=np.float32))

def get_ov_basepath(stack_name, ov_index, slice_index=None):
    ov_string = 'ov' + str(ov_index).zfill(OV_DIGITS)
    slice_string = 's' + str(slice_index).zfill(SLICE_DIGITS) if slice_index is not None else None

    path = [
        'overviews',
        ov_string
    ]

    file = []
    if stack_name:
        file.append(stack_name)
    file.append(ov_string)
    if slice_string:
        file.append(slice_string)
    file = '_'.join(file) + OV_IMAGE_FORMAT
    return path, file

def get_ov_dirname(stack_name, ov_index):
    return get_ov_basepath(stack_name, ov_index)[0]

def get_ov_filename(stack_name, ov_index, slice_index=None):
    return get_ov_basepath(stack_name, ov_index, slice_index)[1]

def ov_save_path(base_dir, stack_name, ov_index, slice_index):
    return os.path.join(
        base_dir,
        str(ov_relative_save_path(stack_name, ov_index, slice_index)))

def ov_relative_save_path(stack_name, ov_index, slice_index=None):
    paths = get_ov_dirname(stack_name, ov_index)
    paths.append(get_ov_filename(stack_name, ov_index, slice_index))
    return os.path.join(*paths)

def ov_debris_save_path(base_dir, stack_name, ov_index, slice_index, sweep_index):
    return os.path.join(
        base_dir, 'overviews', 'debris',
        stack_name + '_ov' + str(ov_index).zfill(OV_DIGITS)
        + '_s' + str(slice_index).zfill(SLICE_DIGITS)
        + '_' + str(sweep_index) + TEMP_IMAGE_FORMAT)

def ov_reslice_save_path(base_dir, ov_index):
    filename = get_ov_filename('r', ov_index)
    return os.path.join(base_dir, 'workspace', 'reslices', filename)

def get_tile_basepath(stack_name, grid_index, array_index=None, roi_index=None, tile_index=None, slice_index=None):
    grid_string = 'g' + str(grid_index).zfill(GRID_DIGITS)
    array_string = 'a' + str(array_index).zfill(GRID_DIGITS) if array_index is not None else None
    roi_string = 'r' + str(roi_index).zfill(GRID_DIGITS) if roi_index is not None else None
    tile_string = 't' + str(tile_index).zfill(TILE_DIGITS) if tile_index is not None else None
    slice_string = 's' + str(slice_index).zfill(SLICE_DIGITS) if slice_index is not None else None

    path = ['tiles']
    file = []
    if stack_name:
        file.append(stack_name)
    if array_index is not None or roi_index is not None:
        if array_index is not None:
            path.append(array_string)
            file.append(array_string)
        if roi_index is not None:
            path.append(roi_string)
            file.append(roi_string)
    else:
        path.append(grid_string)
        file.append(grid_string)

    if tile_string:
        path.append(tile_string)
        file.append(tile_string)
    if slice_string:
        file.append(slice_string)
    file = '_'.join(file) + GRIDTILE_IMAGE_FORMAT
    return path, file

def get_tile_dirname(stack_name, grid_index, array_index=None, roi_index=None, tile_index=None):
    return get_tile_basepath(stack_name, grid_index, array_index, roi_index, tile_index)[0]

def get_tile_filename(stack_name, grid_index, array_index=None, roi_index=None, tile_index=None, slice_index=None):
    return get_tile_basepath(stack_name, grid_index, array_index, roi_index, tile_index, slice_index)[1]

def tile_relative_save_path(stack_name, grid_index, array_index=None, roi_index=None, tile_index=None, slice_index=None):
    paths = get_tile_dirname(stack_name, grid_index, array_index, roi_index, tile_index)
    paths.append(get_tile_filename(stack_name, grid_index, array_index, roi_index, tile_index, slice_index))
    return os.path.join(*paths)

def tile_preview_save_path(base_dir, grid_index, array_index=None, roi_index=None, tile_index=None):
    filename = get_tile_filename('', grid_index, array_index, roi_index, tile_index)
    return os.path.join(base_dir, 'workspace', filename)

def tile_reslice_save_path(base_dir, grid_index, array_index=None, roi_index=None, tile_index=None):
    filename = get_tile_filename('r', grid_index, array_index, roi_index, tile_index)
    return os.path.join(base_dir, 'workspace', 'reslices', filename)

def tile_id(grid_index, tile_index, slice_index):
    return (str(grid_index).zfill(GRID_DIGITS)
            + '.' + str(tile_index).zfill(TILE_DIGITS)
            + '.' + str(slice_index).zfill(SLICE_DIGITS))

def overview_id(ov_index, slice_index):
    return (str(ov_index).zfill(OV_DIGITS)
            + '.' + str(slice_index).zfill(SLICE_DIGITS))

def find_path_numeric_key(paths, label):
    for path in paths:
        if path.startswith(label):
            values = find_path_numeric(path)
            if len(values) > 0:
                return values[0]
    return None

def find_path_numeric(path):
    matches = re.findall(r'\d+', path)
    return [int(match) for match in matches]

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

# TODO: deprecated
def suppress_console_warning():
    # Suppress TIFFReadDirectory warnings that otherwise flood console window
    print('\x1b[19;1H' + 80*' ' + '\x1b[19;1H', end='')
    print('\x1b[18;1H' + 80*' ' + '\x1b[18;1H', end='')
    print('\x1b[17;1H' + 80*' ' + '\x1b[17;1H', end='')
    print('\x1b[16;1H' + 80*' ' + '\x1b[16;1H', end='')

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
            splitIndexes[1] = splitIndexes[1] + 1 # inclusive is more natural (2-5 = 2,3,4,5)
            return range(*splitIndexes)
    elif userString.isdigit():
        return [int(userString)]
    return None


def get_days_hours_minutes(duration_in_seconds):
    minutes, seconds = divmod(int(duration_in_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return days, hours, minutes

def get_hours_minutes(duration_in_seconds):
    minutes, seconds = divmod(int(duration_in_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return hours, minutes


def get_serial_ports():
    return [port.device for port in list_ports.comports()]


def convert_numpy_to_list(data):
    new_data = []
    is_list = False
    try:
        if not isinstance(data, str):
            # ignore string which is also iterable
            iter(data)
            is_list = True
    except TypeError:
        pass

    if isinstance(data, (np.ndarray, np.generic)):
        # also works on single numpy value
        data = data.tolist()

    if is_list:
        for x in data:
            new_data.append(convert_numpy_to_list(x))
    else:
        new_data = data
    return new_data


def serialise_list(data):
    return str(convert_numpy_to_list(data))


def round_xy(coordinates, digits=3):
    x, y = coordinates
    return [round(x, digits), round(y, digits)]


def round_floats(input_var, precision=3):
    """Round floats, or (nested) lists of floats."""
    if isinstance(input_var, float):
        return round(input_var, precision)
    if isinstance(input_var, list):
        return [round_floats(entry) for entry in input_var]
    return input_var


def get_image_file_title(filepath):
    title = os.path.splitext(os.path.basename(filepath))[0].rstrip('.ome')
    return title


def image_to_QPixmap(image):
    image = np.require(uint8_image(image), np.uint8, 'C')
    height, width = image.shape[:2]
    nchannels = image.shape[2] if image.ndim > 2 else 1
    bytes_per_line = nchannels * width
    if nchannels == 1:
        channel_format = QImage.Format_Grayscale8
    else:
        channel_format = QImage.Format_RGB888
    return QPixmap(QImage(image, width, height, bytes_per_line, channel_format))


def grayscale_image(image):
    nchannels = image.shape[2] if len(image.shape) > 2 else 1
    if nchannels == 4:
        return cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
    elif nchannels > 1:
        return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        return image


def color_image(image):
    nchannels = image.shape[2] if len(image.shape) > 2 else 1
    if nchannels == 1:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    else:
        return image


def int2float_image(image):
    source_dtype = image.dtype
    if not source_dtype.kind == 'f':
        maxval = 2 ** (8 * source_dtype.itemsize) - 1
        return image / np.float32(maxval)
    else:
        return image


def float2int_image(image, target_dtype=np.dtype(np.uint8)):
    source_dtype = image.dtype
    if source_dtype.kind not in ('i', 'u') and not target_dtype.kind == 'f':
        maxval = 2 ** (8 * target_dtype.itemsize) - 1
        return (image * maxval).astype(target_dtype)
    else:
        return image


def uint8_image(image):
    source_dtype = image.dtype
    if source_dtype.kind == 'f':
        image *= 255
    elif source_dtype.itemsize != 1:
        factor = 2 ** (8 * (source_dtype.itemsize - 1))
        image //= factor
    return image.astype(np.uint8)


def norm_image_minmax(image0):
    if len(image0.shape) == 3 and image0.shape[2] == 4:
        image, alpha = image0[..., :3], image0[..., 3]
    else:
        image, alpha = image0, None
    normimage = cv2.normalize(np.array(image), None, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_32F)
    if alpha is not None:
        normimage = np.dstack([normimage, alpha])
    return normimage


def norm_image_quantiles(image0, quantile=0.999):
    if len(image0.shape) == 3 and image0.shape[2] == 4:
        image, alpha = image0[..., :3], image0[..., 3]
    else:
        image, alpha = image0, None
    min_value = np.quantile(image, 1 - quantile)
    max_value = np.quantile(image, quantile)
    normimage = np.clip((image.astype(np.float32) - min_value) / (max_value - min_value), 0, 1)
    if alpha is not None:
        normimage = np.dstack([normimage, alpha])
    return normimage


def resize_image(image, new_size):
    if not isinstance(new_size, (tuple, list, np.ndarray)):
        # use single value for width; apply aspect ratio
        size = np.flip(image.shape[:2])
        new_size = new_size, new_size * size[1] // size[0]
    return cv2.resize(image, new_size)


def resize_image_max_pool(image, new_size):
    if not isinstance(new_size, (tuple, list, np.ndarray)):
        # use single value for width; apply aspect ratio
        size = np.flip(image.shape[:2])
        new_size = new_size, new_size * size[1] // size[0]
        
    # compute the max pooling with size calculated from the downsample factor
    height_factor = image.shape[0] / new_size[1]
    width_factor = image.shape[1] / new_size[0]
    max_filter = maximum_filter(image, size=(height_factor, width_factor))
    
    # sample points from the centre of each pooling cell
    height_samples = np.linspace(height_factor//2, image.shape[0]-height_factor//2-1, new_size[1]).astype(int)
    width_samples = np.linspace(width_factor//2, image.shape[1]-width_factor//2-1, new_size[0]).astype(int)
    coords = np.meshgrid(height_samples, width_samples, indexing='ij')
    return max_filter[coords]


def transform_to_QTransform(transform0):
    transform = np.transpose(transform0)
    qtransform = QTransform()
    t00, t01, t02 = transform[0]
    t10, t11, t12 = transform[1]
    if len(transform) >= 3:
        t20, t21, t22 = transform[2]
    else:
        t20, t21, t22 = 0, 0, 1
    qtransform.setMatrix(
        t00, t01, t02,
        t10, t11, t12,
        t20, t21, t22
        )
    return qtransform


def create_point_transform(source, target):
    source3d = np.array([x + [1] for x in source])
    target3d = np.array([x + [1] for x in target])
    solution, res, rank, s = np.linalg.lstsq(source3d, target3d, rcond=None)
    return solution.T


def create_transform(center=(0, 0), angle=0, scale=1, translate=(0, 0)):
    if isinstance(scale, (list, tuple)):
        scale1 = scale[0]
    else:
        scale1 = scale
    transform = cv2.getRotationMatrix2D(center, angle, scale1)
    if isinstance(scale, (list, tuple)):
        transform[1, :] *= scale[1] / scale[0]
    transform[:, 2] += translate
    return transform


def combine_transforms(transforms):
    combined_transform = None
    for transform in transforms:
        if len(transform) < 3:
            transform = np.vstack([transform, [0, 0, 1]])
        if combined_transform is None:
            combined_transform = transform
        else:
            combined_transform = np.dot(transform, combined_transform)
    return combined_transform


def apply_transform(point, transform):
    return np.dot(list(point) + [1], np.transpose(transform))[:2]


def transform_image(image, transform):
    (h, w) = image.shape[:2]
    cos = np.abs(transform[0, 0])
    sin = np.abs(transform[0, 1])
    new_width = int((h * sin) + (w * cos))
    new_height = int((h * cos) + (w * sin))
    return cv2.warpAffine(image, transform, (new_width, new_height))


def get_transform_angle(transform):
    return np.rad2deg(np.arctan2(transform[0][1], transform[0][0]))


def get_transform_scale(transform):
    return np.linalg.norm(transform[:, :2]) / np.linalg.norm([1, 1])


class TranslationTransform(ProjectiveTransform):
    """
    Helper Transform class for pure translations.
    """
    def estimate(self, src, dst):
        try:
            T = np.mean(dst, axis=0) - np.mean(src, axis=0)
        except ZeroDivisionError:
            print('ZeroDivisionError encountered. Results will be invalid!')
            self.params = np.nan * np.empty((3, 3))
            return False
        H = np.eye(3, 3)
        H[:2, -1] = T
        H[2, 2] = 1
        self.params = H
        return True


def align_images_cv2(src: np.ndarray, target: np.ndarray) -> np.ndarray:
    """
    Align (translation) two images with ORB, a SIFT variant, which extracts features in both images and matches them
    according to ``cv2.DESCRIPTOR_MATCHER_BRUTEFORCE_HAMMING``. The final translation vector is estimated using
    RANSAC with a fixed random state. Implementation is based on opencv (cv2 python module).

    Args:
        src: Source image.
        target: Target image.

    Returns:
        Translation vector as the displacement from `src` to `target`.
    """
    MAX_FEATURES = 2000
    GOOD_MATCH_PERCENT = 0.2
    # Detect ORB features and compute descriptors.
    orb = cv2.ORB_create(MAX_FEATURES, nlevels=12, patchSize=128)

    kp1, des1 = orb.detectAndCompute(src, None)
    kp2, des2 = orb.detectAndCompute(target, None)

    # Match features.
    # matcher = cv2.BFMatcher(cv2.NORM_HAMMING2)
    matcher = cv2.DescriptorMatcher_create(cv2.DESCRIPTOR_MATCHER_BRUTEFORCE_HAMMING)
    matches = matcher.match(des1, des2, None)
    # Sort matches by score
    matches = sorted(matches, key=lambda x: x.distance)

    # Remove not so good matches
    numGoodMatches = int(len(matches) * GOOD_MATCH_PERCENT)
    matches = matches[:numGoodMatches]
    # Extract location of good matches
    points1 = np.zeros((len(matches), 2), dtype=np.float32)
    points2 = np.zeros((len(matches), 2), dtype=np.float32)

    for i, match in enumerate(matches):
        points1[i, :] = kp1[match.queryIdx].pt
        points2[i, :] = kp2[match.trainIdx].pt

    # robustly estimate affine transform model with RANSAC
    transf = TranslationTransform  # AffineTransform
    model_robust, inliers = ransac((points1, points2), transf, min_samples=5,
                                   residual_threshold=2, max_trials=10000)
    affine_m = model_robust.params[:2]
    # displacement from im1 to im2
    return affine_m[:, -1]  # only return translation vector


def match_template(img: np.ndarray, templ: np.ndarray, thresh_match: float) -> np.ndarray:
    """

    Args:
        img: Image.
        templ: Template structure.
        thresh_match: Matching score threshold.

    Returns:
        Mean pixel locations of connected components with high matching score within `img` array.
    """
    import skimage.feature
    import scipy.ndimage
    import skimage.measure
    match = skimage.feature.match_template(img, templ, pad_input=True) > thresh_match
    # get connected components
    match, nb_matches = skimage.measure.label(match, background=0, return_num=True)
    locs = np.zeros((nb_matches, 3))
    for ix, sl in enumerate(scipy.ndimage.find_objects(match)):
        # store coordinate of this object
        locs[ix] = np.mean(match[sl] == (ix + 1)) + np.array([sl[0].start, sl[1].start])
    return locs.astype(int)



# -------------- AFSS computation utils --------------

def grad_img(data: np.ndarray) -> np.ndarray:
    scale = 1
    delta = 0
    ddepth = cv2.CV_32F

    # Compute gradients along x and y axes
    grad_x = cv2.Scharr(data, ddepth, 1, 0, scale=scale, delta=delta, borderType=cv2.BORDER_DEFAULT)
    grad_y = cv2.Scharr(data, ddepth, 0, 1, scale=scale, delta=delta, borderType=cv2.BORDER_DEFAULT)

    # Return the magnitude of the gradient (combined gradient in both x and y directions)
    return cv2.magnitude(grad_x, grad_y)


def imread_cv2(path: str) -> np.ndarray:
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE).astype(np.float32)

def create_mask(tile_size):
    width, height = tile_size
    center = (int(height / 2), int(width / 2))
    radius = int(height / 3)
    rr, cc = draw.disk(center, radius)
    mask = np.ones((height, width), dtype=bool)
    mask[rr, cc] = False
    return mask


def save_mask(mask, filename):
    try:
        imsave(filename, img_as_ubyte(mask))
    except Exception as e:
        log_exception(f"Failed to save {filename}: {e}")
        raise


def load_masks(path):
    masks = {}
    for fn in glob.glob(path + '\\mask_*.tif'):
        key = str.split(basename(fn), '.')[0]
        masks[key] = imread(fn)
    return masks


def load_image_collection(filenames: list) -> np.ndarray:
    return ImageCollection(filenames, conserve_memory=True).concatenate()


def register_image_collection(ic: np.ndarray) -> np.ndarray:
    shifts = []
    for i, img in enumerate(ic[:-1]):
        # Do not use (upsample_factor > 1) as it spoils the image information!
        shifts.append(phase_cross_correlation(ic[i], ic[i+1], upsample_factor=1))
    cumulative_shifts = np.cumsum(shifts, axis=0)
    return cumulative_shifts


def compute_shifts_cv2(files: List[str]):
    # Copmutes translation vectors between AFSS images
    def compute_shift(image1, image2):
        def negate_tuple(tup):
            return tuple(-x for x in tup)

        def fix_vec(vec: tuple) -> np.ndarray:
            vec = np.round(vec[::-1])
            vec = np.asarray(negate_tuple(vec))
            vec = np.reshape(vec, [1, 2])
            return vec

        shift_vec, error = cv2.phaseCorrelate(image1, image2)
        return fix_vec(shift_vec), error

    shift = 0.0
    for i in range(1, len(files)):
        ref = imread_cv2(files[i - 1])
        cur = imread_cv2(files[i])
        shift, err = compute_shift(ref, cur)
    return shift


def crop_image_collection(image_collection: np.ndarray, cumm_shifts: np.ndarray) -> np.ndarray:
    sX, sY = np.asarray(cumm_shifts)[:, 1], np.asarray(cumm_shifts)[:, 0]
    sx = np.array(np.round([abs(np.max(sX)), abs(np.min(sX))]), dtype=int)
    sy = np.array(np.round([abs(np.max(sY)), abs(np.min(sY))]), dtype=int)
    crop_vals = ([0, 0], sy, sx)
    return crop(image_collection, crop_vals)


def shift_collection(ic: np.ndarray, cumm_shifts: np.ndarray) -> np.ndarray:
    for i, im in enumerate(ic[1:]):
        ic[i+1] = interpolation.shift(im, cumm_shifts[i])
    return ic


def get_collection_mask(coll_xy_shape: Tuple[int, int]) -> np.ndarray:
    h, w = coll_xy_shape
    y, x = np.ogrid[:h, :w]
    center_y, center_x = h // 2, w // 2
    radius = h // 3
    mask = (y - center_y)**2 + (x - center_x)**2 > radius**2
    return mask


def validate_img_collection(img_coll) -> bool:
    # Verifies tile-image collection after registration and crop operations
    coll_valid = True

    # Check if the input image is valid (non-empty and non-None)
    if any(image is None or image.size == 0 for image in img_coll):
        coll_valid = False
    return coll_valid


def store_reg_coll(img_coll, filenames, prefix):
    # Save sharpness plots to project stats folder
    scale_down = True
    scale_fct = 0.1  # Downscaling the registered series saves disk space

    for j, fn in enumerate(filenames):
        reg_img_path = os.path.join(prefix, os.path.basename(fn))
        if scale_down:
            im_out = rescale(img_coll[j], scale_fct, anti_aliasing=False)
        else:
            im_out = img_coll[j]
        imsave(reg_img_path, im_out)
    return


def get_collection_sharpness(ic: np.ndarray, metric: str) -> list:
    """
    Computes sharpness of series of images to later estimate best focus/stig from AFSS series
    Args:
        ic: image collection of autofocus tile AFSS series
        metric: 'contrast' computes sharpness as standard deviation of image brightness 
                'edges' computes sharpness as a mean value of image convolved with Sobel operator
    """
    sh_arr = []

    x, y = np.shape(ic[0])
    mask = get_collection_mask((x, y))

    for img in ic:
        if metric == 'contrast':
            sh_arr.append(np.std(img))
        elif metric == 'edges':
            masked_grad_img = np.ma.array(grad_img(img), mask=mask, dtype=np.float32)
            sh_arr.append(np.mean(masked_grad_img))
    return sh_arr


def filter_outliers(data: np.ndarray, m=2., epsilon=1e-8) -> np.ndarray:
    d = np.abs(data - np.median(data))
    mdev = np.median(d) + epsilon  # Add epsilon to prevent division by very small values
    s = d / mdev
    return data[s < m]


def rmse(predictions: np.ndarray, targets: np.ndarray) -> float:
    """" Computes root mean squared error of fit values (predictions) to measured values (target)"""
    return np.sqrt(np.mean((predictions-targets)**2))


def get_weights(input_array: list, smallest_weight: float) -> list:
    """
    Linear weighing is applied to the input_array (list of diffs from afss_series optima)
    Values are recalibrated to the range [smallest_weight:1], where 1 is given to the
    lowest value from input array
    """
    def norm_data(arr: list) -> np.ndarray:
        arr = np.asarray(arr)
        arr *= -1   # inversion as highest weight (w=1.0) will be given to the lowest RMSE error
        arr -= min(arr)
        return arr/max(arr)
    weights = norm_data(input_array)
    fcts = smallest_weight * (1 - weights)
    return list(weights + fcts)


def afss_fit_linear(x_vals, y_vals, min_slope):
    """
    Perform linear fit on x AFSS series sharpness values, return max y-value,
    corresponding x-value, and fit RMSE of fitted line over x-range if
    fit_rmse < limit and |slope| >= min_slope.

    Args:
        x_vals: NumPy array of x values.
        y_vals: NumPy array of y values (must be same length as x_vals).
        min_slope: Float, minimum absolute slope for a valid fit.

    Returns:
        Tuple: (max_y, x_at_max_y, fit_rmse, plot x-range, plot y-range, fit outcome)
            - max_y: Max y-value of fitted line (at min or max x) if successful, else None.
            - x_at_max_y: x-value where max y occurs if successful, else None.
            - fit_rmse: RMSE of the fit if successful, else -1.

    Raises:
        ValueError: If arrays are empty, have fewer than 2 points, or have unequal lengths.
    """
    # Input validation
    if len(x_vals) == 0 or len(y_vals) == 0:
        raise ValueError("Input arrays cannot be empty")
    if len(x_vals) < 2:
        raise ValueError("At least two points are required for linear fit")
    if len(x_vals) != len(y_vals):
        raise ValueError("x_vals and y_vals must have equal length")

    # Ensure NumPy arrays
    x = np.asarray(x_vals)
    y = np.asarray(y_vals)

    # Compute x-range for plotting and max y calculation
    x_min, x_max = np.min(x), np.max(x)

    # Perform linear fit (y = mx + c)
    coefficients = np.polyfit(x, y, 1)  # Degree 1 for linear
    m, c = coefficients  # Slope and intercept

    # Calculate fitted y-values
    y_fitted = m * x + c

    # Calculate RMSE
    mse = np.mean((y - y_fitted) ** 2)
    fit_rmse = np.sqrt(mse)

    # Determine if fit is successful
    is_successful = abs(m) >= min_slope

    # Compute return values
    if is_successful:
        # Determine fit y-val at x-range border
        if m > 0:
            max_y = m * x_max + c
            x_at_max_y = x_max
        else:
            max_y = m * x_min + c
            x_at_max_y = x_min
    else:
        max_y = None
        x_at_max_y = None

    # Smooth line over x range for plotting
    x_fit = np.linspace(x_min, x_max, 100)
    y_fit = m * x_fit + c

    return x_at_max_y, max_y, fit_rmse, x_fit, y_fit, is_successful


def afss_fit_poly(x_vals: np.ndarray, y_vals: np.ndarray) -> tuple:
    """
    Fit AFSS series data with a polynomial and compute optimal point.

    Args:
        x_vals: Input x values
        y_vals: Input y values
    Returns:
        tuple: (x_opt, y_opt, RMSE, plot x-range, plot y-range, fit outcome)
    """

    # Fit sharpness values with second-order polynom
    x_min, x_max = min(x_vals), max(x_vals)
    x_fit = np.linspace(x_min, x_max, num=101, endpoint=True)
    cfs = np.polyfit(x_vals, y_vals, deg=2)
    fit = np.poly1d(cfs)
    fit_rmse = rmse(fit(x_vals), y_vals)

    # Verify sharpness values follow expected (negative) quadratic behavior
    is_successful = cfs[0] < 0
    if is_successful:
        x_opt = -cfs[1] / (2 * cfs[0])
        # Limit the resulting optimum to the range of WD/Stig deviation
        if x_opt < x_min:
            x_opt = x_min
        elif x_opt > x_max:
            x_opt = x_max
        y_opt = fit(x_opt)
    else:
        x_opt = None
        y_opt = None

    return x_opt, y_opt, fit_rmse, x_fit, fit(x_fit), is_successful

# -------------- EOF AFSS computation utils --------------