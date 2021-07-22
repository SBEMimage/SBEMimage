# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module handles all email notifications (status reports and error
messages and remote commands.
"""

import os
import json
import imaplib
import smtplib
import requests

from time import sleep
from PIL import Image
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import formatdate
from email import encoders, message_from_string

import utils


class Notifications:
    def __init__(self, config, sysconfig, main_controls_trigger):
        """Load all settings."""
        self.cfg = config
        self.syscfg = sysconfig
        self.main_controls_trigger = main_controls_trigger

        # E-mail settings from sysconfig (read only)
        self.email_account = self.syscfg['email']['account']
        self.smtp_server = self.syscfg['email']['smtp_server']
        self.imap_server = self.syscfg['email']['imap_server']

        self.user_email_addresses = [self.cfg['monitoring']['user_email'],
                                     self.cfg['monitoring']['cc_user_email']]

        # The password needed to access the e-mail account used by SBEMimage
        # to receive remote commands. The user can set this password in a
        # dialog at runtime
        self.remote_cmd_email_pw = ''

        # Status report
        self.status_report_ov_list = json.loads(
            self.cfg['monitoring']['report_ov_list'])
        self.status_report_tile_list = json.loads(
            self.cfg['monitoring']['report_tile_list'])
        self.send_logfile = (
            self.cfg['monitoring']['send_logfile'].lower() == 'true')
        self.send_additional_logs = (
            self.cfg['monitoring']['send_additional_logs'].lower() == 'true')
        self.send_viewport_screenshot = (
            self.cfg['monitoring']['send_viewport_screenshot'].lower()
            == 'true')
        self.send_ov = (self.cfg['monitoring']['send_ov'].lower() == 'true')
        self.send_tiles = (
            self.cfg['monitoring']['send_tiles'].lower() == 'true')
        self.send_ov_reslices = (
            self.cfg['monitoring']['send_ov_reslices'].lower() == 'true')
        self.send_tile_reslices = (
            self.cfg['monitoring']['send_tile_reslices'].lower() == 'true')
        self.remote_commands_enabled = (
            self.cfg['monitoring']['remote_commands_enabled'].lower() == 'true')

        # Metadata server settings (VIME)
        self.metadata_server_url = self.syscfg['metaserver']['url']
        self.metadata_server_admin_email = (
            self.syscfg['metaserver']['admin_email'])

    def save_to_cfg(self):
        self.cfg['monitoring']['user_email'] = self.user_email_addresses[0]
        self.cfg['monitoring']['cc_user_email'] = self.user_email_addresses[1]

        self.cfg['monitoring']['report_ov_list'] = str(
            self.status_report_ov_list)
        self.cfg['monitoring']['report_tile_list'] = json.dumps(
            self.status_report_tile_list)

        self.cfg['monitoring']['send_logfile'] = str(self.send_logfile)
        self.cfg['monitoring']['send_additional_logs'] = str(
            self.send_additional_logs)
        self.cfg['monitoring']['send_viewport_screenshot'] = str(
            self.send_viewport_screenshot)
        self.cfg['monitoring']['send_ov'] = str(self.send_ov)
        self.cfg['monitoring']['send_tiles'] = str(self.send_tiles)
        self.cfg['monitoring']['send_ov_reslices'] = str(self.send_ov_reslices)
        self.cfg['monitoring']['send_tile_reslices'] = str(
            self.send_tile_reslices)
        self.cfg['monitoring']['remote_commands_enabled'] = str(
            self.remote_commands_enabled)

        self.syscfg['metaserver']['url'] = self.metadata_server_url
        self.cfg['sys']['metadata_server_url'] = self.metadata_server_url
        self.syscfg['metaserver']['admin_email'] = (
            self.metadata_server_admin_email)
        self.cfg['sys']['metadata_server_admin'] = (
            self.metadata_server_admin_email)

    def send_email(self, subject, main_text, attached_files=[],
                   recipients=[]):
        """Send e-mail with subject and main_text (body) and attached_files as
        attachments. Send it by default to the user email addresses specified in
        configuration.
        Return (True, None) if email is sent successfully, otherwise return
        (False, error message).
        """
        if not recipients:
            recipients = self.user_email_addresses
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_account
            msg['To'] = self.user_email_addresses[0]
            if self.user_email_addresses[1]:
                msg['Cc'] =  self.user_email_addresses[1]
            msg['Date'] = formatdate(localtime = True)
            msg['Subject'] = subject
            msg.attach(MIMEText(main_text))
            for f in attached_files:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(open(f, 'rb').read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition',
                                'attachment; filename="{0}"'.format(
                                    os.path.basename(f)))
                msg.attach(part)
            mail_server = smtplib.SMTP(self.smtp_server)
            #mail_server = smtplib.SMTP_SSL(smtp_server)
            mail_server.sendmail(self.email_account,
                                 recipients,
                                 msg.as_string())
            mail_server.quit()
            return True, None
        except Exception as e:
            return False, str(e)

    def send_status_report(self, base_dir, stack_name, slice_counter,
                           recent_main_log, incident_log, vp_screenshot):
        """Compile a status report and send it via e-mail."""

        attachment_list = []  # files to be attached
        temp_file_list = []   # files to be deleted after email is sent
        missing_list = []     # files to be attached that could not be found
        # Status messages returned by this function to be added to main log
        status_msg1, status_msg2 = '', ''

        if self.send_logfile:
            # Generate log file from current content of log in Main Controls
            self.main_controls_trigger.transmit(
                'GET CURRENT LOG' + recent_main_log)
            sleep(0.5)  # wait for file to be written
            if not os.path.isfile(recent_main_log):
                sleep(1)
            if os.path.isfile(recent_main_log):
                attachment_list.append(recent_main_log)
                temp_file_list.append(recent_main_log)
            else:
                missing_list.append(recent_main_log)
        if self.send_additional_logs:
            if os.path.isfile(incident_log):
                attachment_list.append(incident_log)
            else:
                missing_list.append(incident_log)
        if self.send_viewport_screenshot:
            if os.path.isfile(vp_screenshot):
                attachment_list.append(vp_screenshot)
            else:
                missing_list.append(vp_screenshot)
        if self.send_ov:
            # Attach OV(s) saved in workspace
            for ov_index in self.status_report_ov_list:
                ov_path = os.path.join(
                    base_dir, 'workspace',
                    'OV' + str(ov_index).zfill(utils.OV_DIGITS) + '.bmp')
                if os.path.isfile(ov_path):
                    attachment_list.append(ov_path)
                else:
                    missing_list.append(ov_path)
        if self.send_tiles:
            for tile_key in self.status_report_tile_list:
                grid_index, tile_index = tile_key.split('.')
                save_path = os.path.join(
                    base_dir, utils.tile_relative_save_path(
                        stack_name, grid_index, tile_index, slice_counter))
                if os.path.isfile(save_path):
                    # If it exists, load image and crop it
                    tile_image = Image.open(save_path)
                    r_width, r_height = tile_image.size
                    cropped_tile_filename = os.path.join(
                        base_dir, 'workspace', 'tile_g'
                        + str(grid_index).zfill(utils.GRID_DIGITS)
                        + 't' + str(tile_index).zfill(utils.TILE_DIGITS)
                        + '_cropped.png')
                    tile_image.crop((int(r_width/3), int(r_height/3),
                         int(2*r_width/3), int(2*r_height/3))).save(
                         cropped_tile_filename)
                    temp_file_list.append(cropped_tile_filename)
                    attachment_list.append(cropped_tile_filename)
                else:
                    missing_list.append(save_path)
        if self.send_ov_reslices:
            for ov_index in self.status_report_ov_list:
                save_path = utils.ov_reslice_save_path(base_dir, ov_index)
                if os.path.isfile(save_path):
                    ov_reslice_img = Image.open(save_path)
                    height = ov_reslice_img.size[1]
                    cropped_ov_reslice_save_path = os.path.join(
                        base_dir, 'workspace', 'reslice_OV'
                        + str(ov_index).zfill(utils.OV_DIGITS) + '.png')
                    if height > 1000:
                        ov_reslice_img.crop(0, height - 1000, 400, height).save(
                            cropped_ov_reslice_save_path)
                    else:
                        ov_reslice_img.save(cropped_ov_reslice_save_path)
                    attachment_list.append(cropped_ov_reslice_save_path)
                    temp_file_list.append(cropped_ov_reslice_save_path)
                else:
                    missing_list.append(save_path)
        if self.send_tile_reslices:
            for tile_key in self.status_report_tile_list:
                grid_index, tile_index = tile_key.split('.')
                save_path = utils.tile_reslice_save_path(
                    base_dir, grid_index, tile_index)
                if os.path.isfile(save_path):
                    reslice_img = Image.open(save_path)
                    height = reslice_img.size[1]
                    cropped_reslice_save_path = os.path.join(
                        base_dir, 'workspace', 'reslice_tile_g'
                        + str(grid_index).zfill(utils.GRID_DIGITS)
                        + 't' + str(tile_index).zfill(utils.TILE_DIGITS)
                        + '.png')
                    if height > 1000:
                        reslice_img.crop(0, height - 1000, 400, height).save(
                            cropped_reslice_save_path)
                    else:
                        reslice_img.save(cropped_reslice_save_path)
                    attachment_list.append(cropped_reslice_save_path)
                    temp_file_list.append(cropped_reslice_save_path)
                else:
                    missing_list.append(save_path)

        # Send report email
        msg_subject = (f'Status report (slice {slice_counter}) '
                       f'for acquisition {stack_name}')
        msg_text = 'See attachments.'
        if missing_list:
            msg_text += ('\n\nThe following file(s) could not be attached. '
                         'Please review your e-mail report settings.\n\n')
            for file in missing_list:
                msg_text += (file + '\n')
        success, send_error = self.send_email(
            msg_subject, msg_text, attachment_list)

        # Clean up temporary files
        cleanup_success = True
        cleanup_exception = ''
        for file in temp_file_list:
            try:
                os.remove(file)
            except Exception as e:
                cleanup_success = False
                cleanup_exception = str(e)
        return success, send_error, cleanup_success, cleanup_exception

    def send_error_report(self, stack_name, slice_counter, error_state,
                          recent_main_log, vp_screenshot):
        """Send a notification by email that an error has occurred."""

        attachment_list = []  # files to be attached
        # Status messages returned by this function to be added to main log
        status_msg1, status_msg2 = '', ''
         # Generate log file from current content of log in Main Controls
        self.main_controls_trigger.transmit(
            'GET CURRENT LOG' + recent_main_log)
        sleep(0.5)  # wait for file to be written
        if not os.path.isfile(recent_main_log):
            sleep(1)

        msg_subject = (f'Error (slice {slice_counter}) '
                       f'during acquisition {stack_name}')
        error_description = (f'An error has occurred: '
                             + utils.Errors[error_state]
                             + '\n\nThe acquisition has been paused. '
                             + 'See attached log file for details.')

        if os.path.isfile(recent_main_log):
            attachment_list.append(recent_main_log)
        else:
            error_description += '\n\nLog file could not be attached.'
        if vp_screenshot is not None:
            attachment_list.append(vp_screenshot)
        else:
            error_description += '\n\nViewport screenshot could not be attached.'

        success, error_msg = self.send_email(
            msg_subject, error_description, attachment_list)
        if success:
            status_msg1 = 'Error notification email sent.'
        else:
            status_msg1 = ('ERROR sending notification email: '
                           + error_msg)
        # Remove temporary log file of most recent entries
        try:
            if os.path.isfile(recent_main_log):
                os.remove(recent_main_log)
        except Exception as e:
            status_msg2 = ('ERROR while trying to remove '
                           'temporary file: ' + str(e))
        return status_msg1, status_msg2

    def get_remote_command(self):
        """Check email account if command was received from one of the
        allowed email addresses. If yes, return it."""
        try:
            mail_server = imaplib.IMAP4_SSL(self.imap_server)
            mail_server.login(self.email_account, self.remote_cmd_email_pw)
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
                        msg = message_from_string(
                            response_part[1].decode('utf-8'))
                        subject = msg['subject'].strip().lower()
                        sender = msg['from']
                mail_server.logout()
                # Check sender and subject
                # Sender email must be main user email or cc email
                sender_allowed = (self.user_email_addresses[0] in sender
                                  or self.user_email_addresses[1] in sender)
                allowed_commands = ['pause', 'stop', 'continue',
                                    'start', 'restart', 'report']
                if (subject in allowed_commands) and sender_allowed:
                    return subject
                else:
                    return 'NONE'
            else:
                return 'NONE'
        except:
            return 'ERROR'

    def metadata_put_request(self, endpoint, data):
        """Send a PUT request to the metadata server."""
        exception_str = ''
        try:
            r = requests.put(self.metadata_server_url + endpoint, json=data)
            status = r.status_code
        except Exception as e:
            status = 100
            exception_str = str(e)
        return status, exception_str

    def metadata_post_request(self, endpoint, data):
        """Send a POST request to the metadata server."""
        exception_str = ''
        try:
            r = requests.post(self.metadata_server_url + endpoint, json=data)
            status = r.status_code
        except Exception as e:
            status = 100
            exception_str = str(e)
        return status, exception_str

    def metadata_get_request(self, endpoint):
        """Send a GET request to the metadata server."""
        command = None
        msg = None
        exception_str = ''
        try:
            r = requests.get(self.metadata_server_url + endpoint)
            received = json.loads(r.content)
            status = r.status_code
            if 'command' in received:
                command = received['command']
            if 'message' in received:
                msg = received['message']
            if 'version' in received:
                msg = received['version']
        except Exception as e:
            status = 100
            msg = 'Metadata server request failed.'
            exception_str = str(e)
        return status, command, msg, exception_str

    def send_session_metadata(self, project_name, stack_name, session_metadata):
        """Send session metadata to the server. This method is called when an
        acquisition (= session) is started.
        """
        return self.metadata_put_request(
            '/project/' + project_name
            + '/stack/' + stack_name
            + '/session/metadata', session_metadata)

    def send_slice_completed(self, project_name, stack_name,
                             slice_complete_metadata):
        """Send a confirmation (timestamp and slice counter) when the
        acquisition of a slice has been completed.
        """
        return self.metadata_put_request(
           '/project/' + project_name
            + '/stack/' + stack_name
            + '/slice/completed', slice_complete_metadata)

    def send_session_stopped(self, project_name, stack_name,
                             session_stopped_metadata):
        """Send a confirmation (timestamp and error state) when the acquisition
        has been stopped by the user or because of an error.
        """
        return self.metadata_put_request(
            '/project/' + project_name
            + '/stack/' + stack_name
            + '/session/stopped', session_stopped_metadata)

    def send_tile_metadata(self, project_name, stack_name, tile_metadata):
        """Send tile metadata after each tile acquisition."""
        return self.metadata_post_request(
           '/project/' + project_name
            + '/stack/' + stack_name
            + '/tile/completed', tile_metadata)

    def send_ov_metadata(self, project_name, stack_name, ov_metadata):
        """Send overview metadata after each overview acquisition."""
        return self.metadata_post_request(
           '/project/' + project_name
            + '/stack/' + stack_name
            + '/ov/completed', ov_metadata)

    def read_server_message(self, project_name, stack_name):
        """Read a message from the metadata server."""
        return self.metadata_get_request(
           '/project/' + project_name
            + '/stack/' + stack_name
            + '/signal/read')
