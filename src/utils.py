# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2016-2019 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This modules provides various constants and helper functions."""

import os
import datetime
import json
import re
import imaplib
import smtplib
import socket
import requests

import numpy as np

from time import sleep

from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import formatdate
from email import encoders, message_from_string

# Number of digits used to format image file names
OV_DIGITS = 3         # up to 999 overview images
GRID_DIGITS = 4       # up to 9999 grids
TILE_DIGITS = 4       # up to 9999 tiles per grid
SLICE_DIGITS = 5      # up to 99999 slices per stack

# Regular expressions for checking user input of tiles and overviews
RE_TILE_LIST = re.compile('^((0|[1-9][0-9]*)[.](0|[1-9][0-9]*))'
                          '([ ]*,[ ]*(0|[1-9][0-9]*)[.](0|[1-9][0-9]*))*$')
RE_OV_LIST = re.compile('^([0-9]+)([ ]*,[ ]*[0-9]+)*$')

# Set of selectable colours for grids:
COLOUR_SELECTOR = [
    [255, 0, 0],      # red
    [0, 255, 0],      # green
    [255, 255, 0],    # yellow
    [0, 255, 255],    # cyan
    [128, 0, 0],      # dark red
    [0, 128, 0],      # dark green
    [255, 165, 0],    # orange
    [255, 0, 255],    # pink
    [173, 216, 230],  # grey
    [184, 134, 11]    # brown
]


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
    return (success, file_handle)

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
    # Align colon (msg must begin with 'CTRL', 'SEM' or '3VIEW'):
    try:
        i = msg.index(':')
    except:
        i = 0
    return (timestamp[:22] + ' | ' + msg[:i] + (6-i) * ' ' + msg[i:])

def show_progress_in_console(progress):
    """Show character-based progress bar in console window"""
    print('\r[{0}] {1}%'.format(
        '.' * int(progress/10)
        + ' ' * (10 - int(progress/10)),
        progress), end='')

def get_ov_save_path(stack_name, ov_number, slice_counter):
    return ('overviews\\ov' + str(ov_number).zfill(OV_DIGITS) + '\\'
            + stack_name
            + '_ov' + str(ov_number).zfill(OV_DIGITS)
            + '_s' + str(slice_counter).zfill(SLICE_DIGITS)
            + '.tif')

def get_ov_debris_save_path(stack_name, ov_number, slice_counter, sw_counter):
    return ('overviews\\debris\\'
            + stack_name
            + '_ov' + str(ov_number).zfill(OV_DIGITS)
            + '_s' + str(slice_counter).zfill(SLICE_DIGITS)
            + '_' + str(sw_counter)
            + '.tif')

def get_tile_save_path(stack_name, grid_number, tile_number, slice_counter):
    return ('tiles\\g' + str(grid_number).zfill(GRID_DIGITS)
            + '\\t' + str(tile_number).zfill(TILE_DIGITS)
            + '\\' + stack_name
            + '_g' + str(grid_number).zfill(GRID_DIGITS)
            + '_t' + str(tile_number).zfill(TILE_DIGITS)
            + '_s' + str(slice_counter).zfill(SLICE_DIGITS)
            + '.tif')

def get_tile_preview_save_path(grid_number, tile_number):
    return ('workspace\\g' + str(grid_number).zfill(GRID_DIGITS)
            + '_t' + str(tile_number).zfill(TILE_DIGITS) + '.png')

def get_tile_reslice_save_path(grid_number, tile_number):
    return ('workspace\\reslices\\r_g' + str(grid_number).zfill(GRID_DIGITS)
            + '_t' + str(tile_number).zfill(TILE_DIGITS) + '.png')

def get_ov_reslice_save_path(ov_number):
    return ('workspace\\reslices\\r_OV'
            + str(ov_number).zfill(OV_DIGITS) + '.png')

def get_tile_id(grid_number, tile_number, slice_number):
    return (str(grid_number).zfill(GRID_DIGITS)
            + '.' + str(tile_number).zfill(TILE_DIGITS)
            + '.' + str(slice_number).zfill(SLICE_DIGITS))

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

def send_email(smtp_server, sender, recipients, subject, main_text, files=[]):
    try:
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = recipients[0]
        msg['Date'] = formatdate(localtime = True)
        msg['Subject'] = subject
        msg.attach(MIMEText(main_text))
        for f in files:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(open(f, 'rb').read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition',
                            'attachment; filename="{0}"'.format(
                                os.path.basename(f)))
            msg.attach(part)
        mail_server = smtplib.SMTP(smtp_server)
        #mail_server = smtplib.SMTP_SSL(smtp_server)
        mail_server.sendmail(sender, recipients, msg.as_string())
        mail_server.quit()
        return True
    except (socket.error, smtplib.SMTPException) as exc:
        print(exc)
        return False

def get_remote_command(imap_server, email_account, email_pw, allowed_senders):
    try:
        #print('Trying to log in to', imap_server, email_account, email_pw)
        mail_server = imaplib.IMAP4_SSL(imap_server)
        mail_server.login(email_account, email_pw)
        mail_server.list()
        mail_server.select('inbox')
        result, data = mail_server.search(None, 'ALL')
        if data is not None:
            id_list = data[0].split()
            latest_email_id = id_list[-1]
            # fetch the email body (RFC822) for latest_email_id
            result, data = mail_server.fetch(latest_email_id, '(RFC822)')
            for response_part in data:
                if isinstance(response_part, tuple):
                    msg = message_from_string(response_part[1].decode('utf-8'))
                    subject = msg['subject'].strip().lower()
                    sender = msg['from']
            mail_server.logout()
            # Check sender and subject
            # Sender email must be main user email or cc email:
            sender_allowed = (allowed_senders[0] in sender
                              or allowed_senders[1] in sender)
            allowed_commands = ['pause', 'stop', 'continue', 'start', 'restart',
                                'report']
            if (subject in allowed_commands) and sender_allowed:
                return subject
            else:
                return 'NONE'
        else:
            return 'NONE'
    except:
        return 'ERROR'

def meta_server_put_request(url, data):
    try:
        r = requests.put(url, json=data)
        status = r.status_code
    except:
        status = 100
    return status

def meta_server_post_request(url, data):
    try:
        r = requests.post(url, json=data)
        status = r.status_code
    except:
        status = 100
    return status

def meta_server_get_request(url):
    command = None
    msg = None
    try:
        r = requests.get(url)
        received = json.loads(r.content)
        status = r.status_code
        if 'command' in received:
            command = received['command']
        if 'message' in received:
            msg = received['message']
        if 'version' in received:
            msg = received['version']
    except:
        status = 100
        msg = 'Metadata server request failed.'
    return (status, command, msg)

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
    sections = {}
    landmarks = {}
    for sectionId, sectionXYA in sectionsYAML['tissue'].items():
        sections[int(sectionId)] = {
        'center': [float(a) for a in sectionXYA[:2]],
        'angle': float( (-sectionXYA[2] + 90) % 360)}
    if 'tissueROI' in sectionsYAML:
        tissueROIIndex = int(list(sectionsYAML['tissueROI'].keys())[0])
        sections['tissueROI-' + str(tissueROIIndex)] = {
        'center': sectionsYAML['tissueROI'][tissueROIIndex]}
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