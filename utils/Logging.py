import typing
from dataclasses import dataclass
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

from discord import TextChannel

BOT_LOG_CHANNEL: typing.Union[TextChannel, None] = None

LOGGER = logging.getLogger('thatskybot')
DISCORD_LOGGER = logging.getLogger('discord')


@dataclass
class TCol:
    cHeader = '\033[95m'
    cOkBlue = '\033[94m'
    cOkCyan = '\033[96m'
    cOkGreen = '\033[92m'
    cWarning = '\033[93m'
    cFail = '\033[91m'
    cEnd = '\033[0m'
    cBold = '\033[1m'
    cUnderline = '\033[4m'


def init():
    LOGGER.setLevel(logging.DEBUG)

    DISCORD_LOGGER.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    DISCORD_LOGGER.addHandler(handler)

    if not os.path.isdir("logs"):
        os.mkdir("logs")
    handler = TimedRotatingFileHandler(filename='logs/thatskybot.log', encoding='utf-8', when="midnight",
                                       backupCount=30)
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    DISCORD_LOGGER.addHandler(handler)
    LOGGER.addHandler(handler)


async def bot_log(message=None, embed=None):
    if BOT_LOG_CHANNEL is not None:
        return await BOT_LOG_CHANNEL.send(content=message, embed=embed)


def debug(message):
    LOGGER.debug(message)


def info(message):
    LOGGER.info(message)


def warn(message):
    LOGGER.warning(message)


def error(message):
    LOGGER.error(message)
