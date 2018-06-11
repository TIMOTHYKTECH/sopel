import sopel.module
import smtplib
from email.mime.text import MIMEText
import re
from sopel.config.types import StaticSection, ValidatedAttribute
import logging


logger = logging.getLogger(__name__)

channel_notify_key = 'notify_nicks'
nick_email_key = 'notify_email'

# https://stackoverflow.com/questions/201323/how-to-validate-an-email-address-using-a-regular-expression/201378#201378  # noqa
valid_email = re.compile(
    r"(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~"
    r'-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|'
    r'\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]'
    r'*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:(2(5[0'
    r'-5]|[0-4][0-9])|1[0-9][0-9]|[1-9]?[0-9]))\.){3}(?:(2(5[0-5]|['
    r'0-4][0-9])|1[0-9][0-9]|[1-9]?[0-9])|[a-z0-9-]*[a-z0-9]:(?:[\x'
    r'01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b'
    r'\x0c\x0e-\x7f])+)\])'
)



def get_notification_list(bot, channel):
    notify_list = bot.db.get_channel_value(channel, channel_notify_key)
    if notify_list is None:
        notify_list = list()
    return notify_list

def get_nick_email(bot, nick):
     return bot.db.get_nick_value(nick, nick_email_key)

class NotifySection(StaticSection):
    email_address = ValidatedAttribute('email_address', str)
    password = ValidatedAttribute('password', str)
    smtp_host = ValidatedAttribute('smtp_host', str)
    smtp_port = ValidatedAttribute('smtp_port', int, default=587)
    email_subject = ValidatedAttribute(
        'email_subject', str,
        default='{bot_nick} - {nick} joined {channel}'
    )
    email_body = ValidatedAttribute(
        'email_body', str,
        default='{nick} joined {channel}'
    )


    @property
    def is_configured(self):
        return not any(
            [x is None for x in [
                 self.email_address,
                 self.password,
                 self.smtp_host,
                 self.smtp_port
            ]]
        )


def configure(config):
    config.define_section('notify', NotifySection)
    config.notify.configure_setting(
        'email_address',
        'The from-address the bot will use when notifying each user:'
    )
    config.notify.configure_setting(
        'password',
        'The password to use when logging in to the SMTP server:'
    )
    config.notify.configure_setting(
        'smtp_host', 'The domain name of or ip of the SMTP server:'
    )
    config.notify.configure_setting(
        'email_subject', 'The subject of the email '
        '(bot_nick, nick, and channel are available'
        ' as format string keys):'
    )
    config.notify.configure_setting(
        'email_body', 'The body of the email '
        '(bot_nick, nick, and channel are available'
        ' as format string keys):'
    )


def setup(bot):
    bot.config.define_section('notify', NotifySection)


@sopel.module.require_privmsg
@sopel.module.commands('set_email')
@sopel.module.example('.set_email anonymous@example.com')
def set_email(bot, trigger):
    """ Associates an email address with a nick """
    if not bot.config.notify.is_configured:
        bot.say('not configured')
        return
    if valid_email.match(trigger.group(2)) is not None:
        bot.db.set_nick_value(
            trigger.nick, nick_email_key, trigger.group(2)
        )
        bot.say('"{}" associated with "{}"'.format(
                trigger.group(2), str(trigger.nick)
        ))
    else:
        bot.say('"{}" doesn\'t look like a valid email address'
                .format(str(trigger.group(2)))
        )


@sopel.module.commands('notify')
@sopel.module.example('.notify')
def add_notify(bot, trigger):
    if not bot.config.notify.is_configured:
        bot.say('not configured')
        return
    if trigger.sender.is_nick():
        bot.say(
            'run this command in a channel to be notified '
            'when a user joins the channel'
        )
        return
    if get_nick_email(bot, trigger.nick) is None:
        bot.say(
            'you have not configured your email, you can '
            'do so by sending .set_email <email> in a '
            'private message to me'
        )
        return
    # get existing config
    directory = bot.db.get_channel_value(
        trigger.sender, channel_notify_key
    )
    # initialize if it doesn't exist
    if directory is None:
        directory = list()
    # add key if it doesn't exist
    if trigger.nick not in directory:
        directory.append(trigger.nick)
        bot.db.set_channel_value(
            trigger.sender, channel_notify_key, directory
        )
        bot.say("{}: I'll notify you when users join this channel")
    else:
        bot.say('you\'re already on the notification list')


@sopel.module.rule('.*')
@sopel.module.event('JOIN')
def notify_on_join(bot, trigger):
    if not bot.config.notify.is_configured:
        return
    if trigger.nick  == bot.nick:
        return

    # create dictionary and remove person who logged
    notify_nicks = get_notification_list(bot, trigger.sender)
    # don't notify users they themselves entered the chat
    if str(trigger.nick) in notify_nicks:
        notify_nicks.remove(str(trigger.nick))

    if len(notify_nicks) == 0:
        return

    sender_email = bot.config.notify.email_address
    sender_pass = bot.config.notify.password
    sender_smtp = bot.config.notify.smtp_host
    sender_port = bot.config.notify.smtp_port

    to_addresses = list(map(
        lambda nick: get_nick_email(bot, nick), notify_nicks
    ))
    message = bot.config.notify.email_body.format(
        bot_nick=str(bot.nick),
        nick=str(trigger.nick),
        channel=str(trigger.sender)
    )

    msg = MIMEText(message)
    msg['Subject'] = bot.config.notify.email_subject.format(
        bot_nick=str(bot.nick),
        nick=str(trigger.nick),
        channel=str(trigger.sender)
    )
    msg['To'] = ', '.join(to_addresses)
    msg['From'] = sender_email
    try:
        server = smtplib.SMTP(sender_smtp, sender_port)
        server.ehlo()
        server.starttls()
        server.login(sender_email,sender_pass)
        server.sendmail(sender_email, list(to_addresses), msg.as_string())
        server.close()
    except Exception as e:
        logger.exception('Failed when trying to send email')
