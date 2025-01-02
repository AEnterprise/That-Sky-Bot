import typing

import yaml
import operator

from discord import Interaction
from discord.ext.commands import Context
from functools import reduce  # forward compatibility for Python 3
from utils import Logging, Configuration, Utils
from utils.Database import Localization, Guild

LANG = dict()
loaded = False
locales_loaded = False
locales = ('en_US', 'ja_JP')
ALL_LOCALES = 'ALL_LOCALES'
L_ERR = "~~LOCALIZATION ERROR~~"
GUILD_LOCALES = dict()
CHANNEL_LOCALES = dict()


async def load_local_overrides():
    global GUILD_LOCALES, CHANNEL_LOCALES
    guild_ids = [guild.id for guild in Utils.BOT.guilds]
    guild_rows = await Guild.filter(serverid__in=guild_ids)
    for row in guild_rows:
        await row.fetch_related()
    channel_locales = await Localization.all()
    GUILD_LOCALES = {row.serverid: row.defaultlocale for row in guild_rows}
    CHANNEL_LOCALES = {row.channelid: row.locale for row in channel_locales}


def get_by_path(root, items):
    try:
        """Access a nested object in root by item sequence."""
        return reduce(operator.getitem, items, root)
    except KeyError as ex:
        return None


def load():
    global LANG, loaded
    with open("lang.yaml") as file:
        LANG = yaml.safe_load(file)
    loaded = True


def load_locales():
    global LANG, locales_loaded
    with open("lang_keys.yaml") as file:
        LANG['keys'] = yaml.safe_load(file)
    for locale in locales:
        with open(f"langs/{locale}.yaml") as file:
            LANG[locale] = yaml.safe_load(file)
    locales_loaded = True


def get_string(key, **kwargs):
    if not loaded:
        load()

    key_list = key.split("/")
    obj = LANG
    for i in key_list:
        if i not in obj:
            raise KeyError(f"Unknown lang key: {i}")

        if isinstance(obj[i], str):
            return obj[i].format(**kwargs)
        elif isinstance(obj[i], dict):
            obj = obj[i]


def get_defaulted_locale(ctx: typing.Union[Context, Interaction, str]):
    locale = 'en_US'
    if isinstance(ctx, Interaction) or isinstance(ctx, Context):
        if isinstance(ctx, Interaction):
            interaction = typing.cast(Interaction, ctx)
            cid = interaction.channel.id
        else:
            # TODO: move guild/channel checks to LangConfig, store in dict,
            #  update there on guild events and config changes
            cid = ctx.channel.id

        if ctx.guild is None:
            # DM - default the language
            locale = Configuration.get_var('broadcast_locale', 'en_US')
            if locale == ALL_LOCALES:
                return locales
            return [locale]

        # TODO: create lookup table so we don't hit database every time
        #  github issue #91
        # Bot default is English
        gid = ctx.guild.id
        if gid in GUILD_LOCALES:
            # server locale overrides bot default
            locale = GUILD_LOCALES[gid]
        if cid in CHANNEL_LOCALES:
            # channel locale overrides server
            locale = CHANNEL_LOCALES[cid]
    elif isinstance(ctx, str):
        # String assumes caller knows better and is overriding all else
        if ctx == ALL_LOCALES:
            return locales
        if ctx not in locales:
            if ctx != '':
                Logging.info(f"Locale string override '{ctx}' not found. Defaulting.")
        else:
            locale = ctx
    else:
        Logging.info(f"Cannot derive locale from context: {ctx}")
        locale = False

    if locale not in locales:
        Logging.info(f"Missing locale {locale} - defaulting to English")
        locale = 'en_US'
    return [locale]


def get_locale_string(key, ctx='', **arg_dict) -> str:
    global LANG, locales_loaded
    locale = get_defaulted_locale(ctx)

    if not locale:
        return L_ERR

    if not locales_loaded:
        load_locales()

    output = []
    # locale is a list or tuple. may be a single item or multiple
    for item in locale:
        locale_lang = LANG[item]
        key_list = key.split("/")

        # Check that keys point to a valid path in base keys
        obj = LANG['keys']

        if get_by_path(obj, key_list[:-1]) is None or key_list[-1] not in get_by_path(obj, key_list[:-1]):
            raise KeyError(f"Lang key is not in lang_keys: {key}")
        if get_by_path(obj, key_list) is not None:
            raise KeyError(f"Lang key is not terminal: {key}")

        obj = get_by_path(locale_lang, key_list)

        # keys were found. Now check locale for value:
        if isinstance(obj, str):
            try:
                output.append(obj.format(**arg_dict))
            except KeyError as e:
                output.append(obj)
        else:
            # Maybe string is not defined in lang file.
            Logging.info(f"localized lang string failed for key {key} in locale {item}")
            output.append(L_ERR)
    return '\n'.join(output)
