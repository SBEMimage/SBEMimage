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

from time import sleep
from queue import Queue
from logging import StreamHandler
from logging.handlers import RotatingFileHandler

from skimage.transform import ProjectiveTransform
from skimage.measure import ransac
from serial.tools import list_ports
from qtpy.QtCore import QObject, Signal, QSize
from qtpy.QtGui import QIcon, QPixmap, QImage

from constants import *


window_icon = QIcon()


def get_window_icon():
    if window_icon.isNull():
        window_icon.addFile('../img/icon_16px.ico', QSize(16, 16))
        window_icon.addFile('../img/icon_48px.ico', QSize(48, 48))
    return window_icon


class Trigger(QObject):
    """A custom QObject for receiving notifications and commands from threads.
    The trigger signal is emitted by calling signal.emit(). The queue can
    be used to send commands: queue.put(cmd) puts a cmd into the
    queue, and queue.get() reads the cmd and empties the queue.
    """
    signal = Signal()
    queue = Queue()

    def transmit(self, cmd):
        """Transmit a single command."""
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
            log_exception(e)

    thread = threading.Thread(target=run_log)
    thread.start()


logger: logging.Logger
qt_text_handler = QtTextHandler()


def logging_init(*message):
    global logger
    dirtree = os.path.dirname(LOG_FILENAME)
    if not os.path.exists(dirtree):
        os.makedirs(dirtree)

    logger = logging.getLogger("SBEMimage")
    logger.setLevel(logging.INFO)   # important: anything below this will be filtered irrespective of handler level
    # logging_add_handler(StreamHandler(), level=logging.ERROR)   # filter messages to console log handler
    logging_add_handler(RotatingFileHandler(
        LOG_FILENAME, maxBytes=LOG_MAX_FILESIZE, backupCount=LOG_MAX_FILECOUNT))
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

def ov_save_path(base_dir, stack_name, ov_index, slice_counter):
    return os.path.join(
        base_dir, ov_relative_save_path(stack_name, ov_index, slice_counter))

def ov_relative_save_path(stack_name, ov_index, slice_counter):
    return os.path.join(
        'overviews', 'ov' + str(ov_index).zfill(OV_DIGITS),
        stack_name + '_ov' + str(ov_index).zfill(OV_DIGITS)
        + '_s' + str(slice_counter).zfill(SLICE_DIGITS) + OV_IMAGE_FORMAT)

def ov_debris_save_path(base_dir, stack_name, ov_index, slice_counter,
                        sweep_counter):
    return os.path.join(
        base_dir, 'overviews', 'debris',
        stack_name + '_ov' + str(ov_index).zfill(OV_DIGITS)
        + '_s' + str(slice_counter).zfill(SLICE_DIGITS)
        + '_' + str(sweep_counter) + TEMP_IMAGE_FORMAT)

def tile_relative_save_path(stack_name, grid_index, tile_index, slice_counter):
    return os.path.join(
        'tiles', 'g' + str(grid_index).zfill(GRID_DIGITS),
        't' + str(tile_index).zfill(TILE_DIGITS),
        stack_name + '_g' + str(grid_index).zfill(GRID_DIGITS)
        + '_t' + str(tile_index).zfill(TILE_DIGITS)
        + '_s' + str(slice_counter).zfill(SLICE_DIGITS) + GRIDTILE_IMAGE_FORMAT)

def rejected_tile_save_path(base_dir, stack_name, grid_index, tile_index,
                            slice_counter, fail_counter):
    return os.path.join(
        base_dir, 'tiles', 'rejected',
        stack_name + '_g' + str(grid_index).zfill(GRID_DIGITS)
        + '_t' + str(tile_index).zfill(TILE_DIGITS)
        + '_s' + str(slice_counter).zfill(SLICE_DIGITS)
        + '_'  + str(fail_counter) + GRIDTILE_IMAGE_FORMAT)

def tile_preview_save_path(base_dir, grid_index, tile_index):
    return os.path.join(
        base_dir, 'workspace', 'g' + str(grid_index).zfill(GRID_DIGITS)
         + '_t' + str(tile_index).zfill(TILE_DIGITS) + GRIDTILE_IMAGE_FORMAT)

def tile_reslice_save_path(base_dir, grid_index, tile_index):
    return os.path.join(
        base_dir, 'workspace', 'reslices',
        'r_g' + str(grid_index).zfill(GRID_DIGITS)
        + '_t' + str(tile_index).zfill(TILE_DIGITS) + GRIDTILE_IMAGE_FORMAT)

def ov_reslice_save_path(base_dir, ov_index):
    return os.path.join(
        base_dir, 'workspace', 'reslices',
        'r_OV' + str(ov_index).zfill(OV_DIGITS) + OV_IMAGE_FORMAT)

def tile_id(grid_index, tile_index, slice_counter):
    return (str(grid_index).zfill(GRID_DIGITS)
            + '.' + str(tile_index).zfill(TILE_DIGITS)
            + '.' + str(slice_counter).zfill(SLICE_DIGITS))

def overview_id(ov_index, slice_counter):
    return (str(ov_index).zfill(OV_DIGITS)
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


def image_to_QPixmap(image):
    height, width = image.shape[:2]
    return QPixmap(QImage(color_image(uint8_image(image)), width, height, QImage.Format_RGB888))


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


def uint8_image(image):
    if image.dtype.kind == 'f':
        image *= 255
    elif image.dtype.itemsize != 1:
        factor = 2 ** (8 * (image.dtype.itemsize - 1))
        image //= factor
    return image.astype(np.uint8)


def norm_image_minmax(image0):
    if len(image0.shape) == 3 and image0.shape[2] == 4:
        image, alpha = image0[..., :3], image0[..., 3]
    else:
        image, alpha = image0, None
    normimage = cv2.normalize(image, None, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_32F)
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
    normimage = np.clip((image - min_value) / (max_value - min_value), 0, 1).astype(np.float32)
    if alpha is not None:
        normimage = np.dstack([normimage, alpha])
    return normimage


def resize_image(image, new_size):
    return cv2.resize(image, new_size)


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
                                   residual_threshold=2, max_trials=10000, random_state=0)
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
