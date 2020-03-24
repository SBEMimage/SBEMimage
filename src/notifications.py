# -*- coding: utf-8 -*-

# ==============================================================================
#   SBEMimage, ver. 2.0
#   Acquisition control software for serial block-face electron microscopy
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module handles all email notifications (status reports and error
messages and remote commands."""

import os
import json
import imaplib
import smtplib

from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import formatdate
from email import encoders, message_from_string

import utils


class Notifications:
    def __init__(self, config, sysconfig):
        """Load all settings."""
        self.cfg = config
        self.syscfg = sysconfig

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
        self.send_logfile = str(self.cfg['monitoring']['send_logfile'])
        self.send_additional_logs = str(
            self.cfg['monitoring']['send_additional_logs'])
        self.send_viewport_screenshot = str(
            self.cfg['monitoring']['send_viewport_screenshot'])
        self.send_ov = str(self.cfg['monitoring']['send_ov'])
        self.send_tiles = str(self.cfg['monitoring']['send_tiles'])
        self.send_ov_reslices = str(self.cfg['monitoring']['send_ov_reslices'])
        self.send_tile_reslices = str(
            self.cfg['monitoring']['send_tile_reslices'])
        self.remote_commands_enabled = str(
            self.cfg['monitoring']['remote_commands_enabled'])

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

    def send_email(self, subject, main_text, attached_files=[]):
        """Send email to user email addresses specified in configuration, with
        subject and main_text (body) and attached_files as attachments.
        Return (True, None) if email is sent successfully, otherwise return
        (False, error message)."""
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
                                 self.user_email_addresses,
                                 msg.as_string())
            mail_server.quit()
            return True, None
        except Exception as e:
            return False, str(e)

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

