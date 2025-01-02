import typing
from typing import Optional, Union, Any

import discord
from discord import Message, TextChannel, Embed, Member, Guild, InteractionResponse, Interaction, Role
from discord.ext.commands import Context

from sky import Skybot

BOT: Skybot
GUILD_CONFIGS: dict


async def permission_manage_bot(ctx: Context) -> bool: ...


async def guild_log(
        guild_id: int,
        msg: Optional[str] = None,
        embed: Optional[Embed] = None) -> typing.Union[None, Message]: ...


class BaseEnum: ...


async def handle_exception(
        exception_type: str,
        exception: Exception,
        message: Optional[Message]=None,
        ctx: Optional[Union[Context, Interaction]]=None,
        *args,
        **kwargs) -> None: ...


def get_chanconf_description(bot: Skybot, id: int) -> str: ...


async def get_guild_maintenance_channel(guild_id: int) -> TextChannel: ...


def get_embed_and_log_exception(
        exception_type: str,
        exception: Exception,
        message: Optional[Message] = None,
        ctx: Optional[Union[Context, Interaction]] = None,
        *args,
        **kwargs) -> Union[None, Embed]: ...


async def permission_official_mute(ctx: Context) -> bool: ...


async def permission_official_ban(ctx: Context) -> bool: ...


async def can_mod_official(ctx: Union[Context, Interaction]) -> bool: ...


def permission_official(member_id: int, permission_name: str) -> bool: ...


async def get_user(uid, fetch=True) -> Union[None, discord.User]: ...


def to_pretty_time(seconds: Union[int, float]) -> str: ...


def get_member_log_name(member: Union[discord.User, discord.Member]) -> str: ...


async def clean(
        text,
        guild: Optional[Guild] = None,
        markdown: Optional[bool] = True,
        links: Optional[bool] = True,
        emoji: Optional[bool] = True) -> str: ...


def paginate(
        input_data: str,
        max_lines: int = 20,
        max_chars: int = 1900,
        prefix: str = "",
        suffix: str = "") -> list[str]: ...


def is_power_of_two(num: int) -> bool: ...


def can_help(ctx: Context) -> bool: ...


async def get_guild_log_channel(guild_id: int) -> Union[None, TextChannel]: ...


def get_new_uuid_str() -> str: ...


def get_home_guild() -> Optional[Guild]: ...


def interaction_response(interaction: Interaction) -> InteractionResponse: ...


def id_list_to_roles(guild: Guild, id_list: list[int]) -> list[Role]: ...


def get_bitshift(param): ...


def get_channel_description(bot: Skybot, channel_id: int) -> str: ...


def trim_message(message: str, limit: int) -> str: ...


def check_is_owner(interaction: Interaction) -> bool: ...


def fetch_from_disk(filename: str, alternative: Optional[str] = None): ...


def escape_markdown(text: str) -> str: ...


def save_to_disk(filename, data, ext="json", fields=None) -> None: ...


def pages_to_embed(content: str, embed: discord.Embed, field_name: str = "Contents"): ...