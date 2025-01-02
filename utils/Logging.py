import functools
import typing
import logging
import os
import sys
from enum import Enum
from logging.handlers import TimedRotatingFileHandler

from discord import TextChannel

BOT_LOG_CHANNEL: typing.Union[TextChannel, None] = None

LOGGER = logging.getLogger('thatskybot')
DISCORD_LOGGER = logging.getLogger('discord')


class TCol(Enum):
    Header = '\033[95m'
    Blue = '\033[94m'
    Cyan = '\033[96m'
    Green = '\033[92m'
    Warning = '\033[93m'
    Fail = '\033[91m'
    End = '\033[0m'
    Bold = '\033[1m'
    Underline = '\033[4m'


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


def log_format(subject:str, *styles:TCol)->str:
    output = subject
    for style in styles:
        output = f"{style.value}{output}{TCol.End.value}"
    return output


def color_log(log_func):
    @functools.wraps(log_func)
    def color_wrapper(message:str, *styles:TCol, **kwargs):
        log_func(log_format(message, *styles), **kwargs)
    return color_wrapper


@color_log
def debug(message, **kwargs):
    LOGGER.debug(message, **kwargs)


@color_log
def info(message, **kwargs):
    LOGGER.info(message, **kwargs)


@color_log
def warn(message, **kwargs):
    LOGGER.warning(message, **kwargs)


@color_log
def error(message, **kwargs):
    LOGGER.error(message, **kwargs)
