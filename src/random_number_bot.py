import base64
import configparser
import json
import logging
import re
import smtplib
import sys
import urllib
import uuid
from email.mime.text import MIMEText
from os import environ as env

sys.path.insert(0, 'src/vendor')
import praw
import requests

# for local testing, load environment variables from .env file
# from dotenv import load_dotenv  # type: ignore

# =============================================================================
# GLOBALS
# =============================================================================

VERSION = '1.3.0'

# Reads the config file
config = configparser.ConfigParser()


def set_config():
    config.add_section("Reddit")
    config.add_section("Email")
    config.add_section("RandomNumberBot")

    config.set("Reddit", "username", env['REDDIT_USERNAME'])
    config.set("Reddit", "password", env['REDDIT_PASSWORD'])
    config.set("Reddit", "client_id", env['REDDIT_CLIENT_ID'])
    config.set("Reddit", "client_secret", env['REDDIT_CLIENT_SECRET'])
    config.set("Email", "server", env['EMAIL_SERVER'])
    config.set("Email", "username", env['EMAIL_USERNAME'])
    config.set("Email", "password", env['EMAIL_PASSWORD'])
    config.set("RandomNumberBot", "dev_email", env['APP_DEV_EMAIL'])
    config.set("RandomNumberBot", "dev_user", env['APP_DEV_USERNAME'])
    config.set("RandomNumberBot", "random_org_api_key", env['APP_RANDOM_DOT_ORG_API_KEY'])


set_config()

bot_username = config.get("Reddit", "username")
bot_password = config.get("Reddit", "password")
client_id = config.get("Reddit", "client_id")
client_secret = config.get("Reddit", "client_secret")

print("bot_username:", env['REDDIT_USERNAME'])

EMAIL_SERVER = config.get("Email", "server")
EMAIL_USERNAME = config.get("Email", "username")
EMAIL_PASSWORD = config.get("Email", "password")

DEV_EMAIL = config.get("RandomNumberBot", "dev_email")

RUNNING_FILE = "random_number_bot.running"
DEV_USER_NAME = config.get("RandomNumberBot", "dev_user")
RANDOM_ORG_API_KEY = config.get("RandomNumberBot", "random_org_api_key")
RANDOM_ORG_API_URL = 'https://api.random.org/json-rpc/2/invoke'
HTTP_TIMEOUT = 30.0

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('RandomNumberBot')
logger.setLevel(logging.INFO)

# Reddit info
reddit = praw.Reddit(client_id=client_id,
                     client_secret=client_secret,
                     password=bot_password,
                     user_agent='random_number_bot by {DEV_USER_NAME}'
                     .format(DEV_USER_NAME=DEV_USER_NAME),
                     username=bot_username)

random_verification_url = 'https://api.random.org/signatures/form?format=json&random={random}&signature={signature}'
random_number_reply = """#{command_message} {random_numbers}

To verify the winner, click [this link]({random_verification_url_string}) with prepopulated values or paste the following values into their respective fields on the [random.org verify page](https://api.random.org/verify). More info about extensive verification and the bot can be found in [this post.](https://www.reddit.com/r/WatchURaffle/comments/8sbd92/information_about_the_bot_uboyandhisbot)

**Random:**

{verification_random}

**Signature:**

{verification_signature}

---

[^(Give Feedback)](https://www.reddit.com/message/compose/?to=BlobAndHisBoy&subject=Feedback) ^| [^(Version {version} Source Code)](https://github.com/jjmerri/random-number-bot-lambda) ^| [^(Tip BlobAndHisBoy)](https://blobware-tips.firebaseapp.com)

^(This bot is maintained and hosted by BlobAndHisBoy.)"""


def send_dev_pm(subject, body):
    """
    Sends Reddit PM to DEV_USER_NAME
    :param subject: subject of PM
    :param body: body of PM
    """
    reddit.redditor(DEV_USER_NAME).message(subject, body)


def send_dev_email(subject, body, email_addresses):
    sent_from = DEV_EMAIL

    msg = MIMEText(body.encode('utf-8'), 'plain', 'UTF-8')
    msg['Subject'] = subject

    server = smtplib.SMTP_SSL(EMAIL_SERVER, 465)
    server.ehlo()
    server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
    server.sendmail(sent_from, email_addresses, msg.as_string())
    server.close()


def check_mentions():
    processed_count = 0
    encountered_replied = False
    for mention in reddit.inbox.mentions(limit=None):
        try:
            # Refresh to ensure replies are loaded
            mention.refresh()
        except Exception:
            logger.exception('Failed to refresh mention {id}'.format(id=mention.id))
            continue

        already_replied = False
        try:
            for reply in mention.replies:
                if reply.author and str(reply.author).lower() == bot_username.lower():
                    already_replied = True
                    break
        except Exception:
            logger.exception('Error iterating replies for mention {id}'.format(id=mention.id))
            continue

        if already_replied:
            logger.info('Skipping mention {id} - already replied'.format(id=mention.id))
            encountered_replied = True
            try:
                mention.mark_read()
            except Exception:
                logger.exception('Failed to mark mention {id} as read while skipping'.format(id=mention.id))
        else:
            # Mark Read first in case there is an error we dont want to keep trying to process it
            try:
                mention.mark_read()
            except Exception:
                logger.exception('Failed to mark mention {id} as read prior to processing'.format(id=mention.id))
            process_mention(mention)

        processed_count += 1
        # Allow early stop only after we've inspected at least 5 mentions and seen one already replied
        if encountered_replied and processed_count >= 5:
            logger.info('Encountered previously replied mention and inspected {count} mentions; stopping early.'
                        .format(count=processed_count))
            break


def process_mention(mention):
    logger.info(
        'Processing comment by {author} for {context}'.format(author=str(mention.author), context=mention.context))

    command_regex = r'^([ ]+)?/?u/{bot_username}[ ]+(?P<param_1>[\d]+)([ ]+(?P<param_2>[\d]+))?([ ]+)?$'.format(
        bot_username=bot_username)
    match = re.search(command_regex, mention.body, re.IGNORECASE)

    command_message = ''
    num_randoms = 0
    num_slots = 0

    if match and match.group("param_1") and match.group("param_2"):
        command_message = 'Your escrow spots:'
        num_randoms = int(match.group("param_1"))
        num_slots = int(match.group("param_2"))
        if (num_randoms > num_slots):
            num_randoms, num_slots = num_slots, num_randoms
    elif match and match.group("param_1"):
        command_message = 'The winner is:'
        num_randoms = 1
        num_slots = int(match.group("param_1"))
    else:
        # could be a normal mention not a command so just return
        return

    request = get_rdo_request(num_randoms, num_slots, mention.id)

    responseData = {}
    try:
        response = requests.post(RANDOM_ORG_API_URL,
                                 data=json.dumps(request),
                                 headers={'content-type': 'application/json'},
                                 timeout=HTTP_TIMEOUT)
        responseData = response.json()

        logger.info('API response for comment by {author} for {context} is {response}'
                    .format(author=str(mention.author), context=mention.context, response=str(responseData)))
    except Exception as err:
        logger.exception('Error calling RandomOrg API')

    if (responseData and 'result' in responseData):
        responseResult = responseData['result']
        random_verification_url_string = random_verification_url.format(
            random=urllib.parse.quote_plus(
                base64.standard_b64encode(json.dumps(responseResult['random']).encode('utf-8')).decode("utf-8")),
            signature=urllib.parse.quote_plus(str(responseResult['signature']))
        )
        mention.reply(random_number_reply.format(command_message=command_message,
                                                 random_numbers=str(responseResult['random']['data']),
                                                 verification_random=json.dumps((responseResult['random'])),
                                                 verification_signature=str(responseResult['signature']),
                                                 random_verification_url_string=random_verification_url_string,
                                                 version=VERSION))
    else:
        logger.error(
            'Error getting random nums {num_randoms} {num_slots}'.format(num_randoms=num_randoms, num_slots=num_slots))
        logger.error(str(responseData))
        try:
            if num_slots == 1:
                mention.reply('The number of slots must be greater than 1. Please fix the call and try again.')
            else:
                mention.reply('There was an error getting your random numbers from random.org. Please try again. '
                              'If you continue to experience issues or the bot becomes unresponsive please contact {DEV_USER_NAME}.'
                              .format(DEV_USER_NAME=DEV_USER_NAME))
                send_dev_email("Error getting random nums",
                               'Error getting random nums {num_randoms} {num_slots}'.format(num_randoms=num_randoms,
                                                                                            num_slots=num_slots),
                               [DEV_EMAIL])
                send_dev_pm("Error getting random nums",
                            'Error getting random nums {num_randoms} {num_slots}'.format(num_randoms=num_randoms,
                                                                                         num_slots=num_slots))
        except Exception as err:
            logger.exception("Unknown error sending dev pm or email")


def get_rdo_request(num_randoms, num_slots, mentionId):
    return {'jsonrpc': '2.0', 'method': 'generateSignedIntegers',
            'params': {'apiKey': RANDOM_ORG_API_KEY, 'n': num_randoms, 'min': 1, 'max': num_slots,
                       'replacement': False, 'userData': {'mentionId': mentionId}},
            'id': uuid.uuid4().hex}


def execute(event, context):
    check_mentions()

    return {"statusCode": 200, "body": json.dumps({"message": "Random number bot has executed successfully!"})}


# for simpler local testing
# if __name__ == '__main__':
#     execute(None, None)
