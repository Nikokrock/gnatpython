"""Email sending functions."""

from gnatpython.ex import Run
from logging import getLogger
import os
import smtplib
import socket

logger = getLogger('gnatpython.sendmail')


def sendmail(from_email, to_emails, mail_as_string, smtp_server,
             max_size=20, message_id=None):
    """Send an email with sendmail or stmplib.

    :param from_email: the address sending this email (e.g. user@example.com)
    :type from_email: str
    :param to_emails: A list of addresses to send this email to.
    :type to_emails: list[str]
    :param mail_as_string: the message to send (with headers)
    :type mail_as_string: str
    :param smtp_server: the smtp server name (hostname)
    :type smtp_server: str
    :param max_size: do not send the email via smptlib if bigger than
        'max_size' Mo.
    :type max_size: int
    :param message_id: the message id (for debugging purposes)
    :type message_id: str

    :return: boolean (sent / not sent)
    :rtype: bool

    We prefer running smtplib so we can manage the email size.
    We run sendmail in case it fails, assuming the max_size on the system
    is high enough - the advantage of sendmail is that it queues the
    email and retries a few times if the target server is unable
    to receive it.
    """
    mail_size = float(len(mail_as_string)) / (1024 * 1024)
    if mail_size >= max_size:
        # Message too big
        logger.error("!!! message file too big (>= %d Mo): %f Mo",
                     max_size, mail_size)
        return False

    def system_sendmail():
        """Run the system sendmail."""
        logger.debug('fall back on system sendmail')
        for sendmail in ('/usr/lib/sendmail', '/usr/sbin/sendmail'):
            if os.path.exists(sendmail):
                p = Run([sendmail] + to_emails, input="|" +
                        mail_as_string, output=None)
                return p.status == 0

        # No system sendmail, return False
        logger.debug('no system sendmail')
        return False

    result = False

    logger.debug('connect to smtp server: %s', smtp_server)
    try:
        s = smtplib.SMTP(smtp_server, timeout=120)
    except (socket.error, smtplib.SMTPException) as e:
        logger.debug(e)
        logger.debug('cannot connect to smtp server')
        result = system_sendmail()

    else:

        try:
            logger.debug('send email: %s', message_id)
            if not s.sendmail(from_email, to_emails, mail_as_string):
                # sendmail returns an empty dictionary if the message
                # was accepted for delivery to all addresses
                result = True
        except (socket.error, smtplib.SMTPException) as e:
            logger.debug(e)
            logger.debug("smtp server error: %s", smtp_server)
        finally:
            logger.debug('disconnect from smtp server')
            try:
                s.quit()
            except (socket.error, smtplib.SMTPException):
                # The message has already been delivered, ignore all errors
                # when terminating the session.
                logger.debug('disconnection failure')
                pass

        if not result:
            logger.warn('sendmail failed, retrying with system sendmail')
            result = system_sendmail()

    if result and message_id is not None:
        logger.debug('Message-ID: %s sent successfully', message_id)

    return result
