import json
from itertools import islice
from json import JSONDecodeError
from typing import List

import discord
from discord import app_commands, Interaction, TextChannel
from discord.ext import commands

from sky import Skybot
from utils import Lang, Utils, Logging
from utils.Database import Localization
from utils.Utils import interaction_response


@app_commands.guild_only()
@app_commands.default_permissions(manage_channels=True)
class LangConfig(commands.GroupCog, group_name='language'):
    unset_str = "None"

    def __init__(self, bot):
        self.bot: Skybot = bot

    async def cog_load(self):
        Lang.load_locales()

    async def cog_check(self, ctx):
        return await Utils.permission_manage_bot(ctx) or (ctx.guild and ctx.author.guild_permissions.manage_channels)

    @commands.guild_only()
    @app_commands.command(name="show")
    async def lang_show(self, interaction: discord.Interaction) -> None:
        """Show language settings for this server"""
        channels = []
        embed = discord.Embed(
            timestamp=interaction.created_at,
            color=0x00FF99,
            title=Lang.get_locale_string(
                'lang/lang_settings_title',
                interaction,
                server_name=interaction.guild.name))

        guild_config_row = await self.bot.get_guild_db_config(interaction.guild.id)
        if guild_config_row:
            embed.add_field(name="Server default", value=guild_config_row.defaultlocale or "none")

        for row in await guild_config_row.locales:
            channels.append(self.bot.get_channel(row.channelid).mention)
            embed.add_field(name=f"#{self.bot.get_channel(row.channelid).name}",
                            value=row.locale,
                            inline=True)

        await interaction_response(interaction).send_message(embed=embed)

    # reload lang
    @commands.guild_only()
    @app_commands.command()
    async def reload(self, interaction: Interaction) -> None:
        """Reload language locale files"""
        Lang.load_locales()
        await interaction_response(interaction).send_message(
            Lang.get_locale_string('lang/reloaded', interaction, server_name=interaction.guild.name))

    # Set default server lang
    @commands.guild_only()
    @app_commands.command(name="setserverlocale")
    async def set_server_locale(self, interaction: Interaction, locale: str) -> None:
        """
        Set default locale for this server

        Parameters
        ----------
        interaction
        locale

        Returns
        -------
        None
        """
        if locale not in Lang.locales and locale != self.unset_str:
            await interaction_response(interaction).send_message(
                Lang.get_locale_string(
                    'lang/unknown_locale',
                    interaction,
                    locale=locale,
                    locale_lsit=Lang.locales))
            return

        if locale == self.unset_str:
            locale = ""

        guild_config_row = await self.bot.get_guild_db_config(interaction.guild.id)

        # Don't set/save if input arg is already default
        if locale == guild_config_row.defaultlocale:
            await interaction_response(interaction).send_message(
                Lang.get_locale_string(
                    'lang/default_not_changed',
                    interaction,
                    locale=locale,
                    server_name=interaction.guild.name))
            return

        guild_config_row.defaultlocale = locale
        await guild_config_row.save()
        await Lang.load_local_overrides()
        await interaction_response(interaction).send_message(
            Lang.get_locale_string(
                'lang/default_set',
                interaction,
                locale=locale,
                server_name=interaction.guild.name))

    # Set channel-specific locale
    @commands.guild_only()
    @app_commands.command(name="setchannellocale")
    async def set_channel_locale(
            self,
            interaction: Interaction,
            channel: TextChannel,
            locale: str ) -> None:
        """Set Locale for a specific channel

        Parameters
        ----------
        interaction
        channel
            The channel to set.
        locale
            The locale to use in this channel.
        """
        # TODO: add ALL_LOCALES as channel option

        localization_row = await Localization.get_or_none(guild__serverid=interaction.guild.id, channelid=channel.id)
        if localization_row is not None:
            Logging.info(f"{localization_row.channelid}: {localization_row.locale}")

        if locale not in Lang.locales and locale != self.unset_str:
            await interaction_response(interaction).send_message(
                Lang.get_locale_string(
                    'lang/unknown_locale',
                    interaction,
                    locale=locale,
                    locale_lsit=Lang.locales))
            return

        if locale == self.unset_str:
            if not localization_row:
                await interaction_response(interaction).send_message(
                    Lang.get_locale_string(
                        'lang/channel_not_unset',
                        interaction,
                        channel_mention=channel.mention))
            else:
                await localization_row.delete()
                await Lang.load_local_overrides()
                await interaction_response(interaction).send_message(
                    Lang.get_locale_string(
                        'lang/channel_unset',
                        interaction,
                        channel_mention=channel.mention))
            return

        if not localization_row:
            guild_config_row = await self.bot.get_guild_db_config(interaction.guild.id)
            localization_row = await Localization.create(guild=guild_config_row, channelid=channel.id)

        if localization_row.locale == locale:
            await interaction_response(interaction).send_message(
                Lang.get_locale_string(
                    'lang/channel_already_set',
                    interaction,
                    channel_mentino=channel.mention,
                    locale=locale))
            return

        localization_row.locale = locale
        await localization_row.save()
        await Lang.load_local_overrides()
        await interaction_response(interaction).send_message(
            Lang.get_locale_string(
                'lang/channel_set',
                interaction,
                channel_mention=channel.mention,
                locale=locale))

    # get translation string get_translation(locale, key, **kwargs)
    @commands.guild_only()
    @app_commands.command()
    async def test_language_key(self, interaction: Interaction, language_key: str, locale: str = '', *, json_args: str = ''):
        """
        Test a language key with localization

        ctx:
        lang_key:
        locale: name a locale to use, * for default (per server, channel), or "all" to show all localizations
        json_args: JSON-formatted string representing required tokens for the given key
        """
        try:
            arg_dict = json.loads(json_args)
        except JSONDecodeError:
            arg_dict = dict()

        if locale == '*':
            locale = interaction
        if locale.lower() in ['all', 'all_locales']: # TODO: autocomplete?
            locale = Lang.ALL_LOCALES

        defaulted_locale = Lang.get_defaulted_locale(locale)
        try:
            result = Lang.get_locale_string(language_key, locale, **arg_dict)
            await interaction_response(interaction).send_message(
                Lang.get_locale_string(
                    'lang/test',
                    interaction,
                    lang_key=language_key,
                    locale=defaulted_locale,
                    result=result))
        except Exception as ex:
            await interaction_response(interaction).send_message(
                Lang.get_locale_string(
                    'lang/test_failed',
                    interaction,
                    lang_key=language_key,
                    locale=defaulted_locale))

    @set_server_locale.autocomplete('locale')
    @set_channel_locale.autocomplete('locale')
    @test_language_key.autocomplete('locale')
    async def locale_autocomplete(
            self,
            interaction: discord.Interaction,
            current: str) -> List[app_commands.Choice[str]]:

        my_locales = set(Lang.locales)
        my_locales.add('None')
        my_locales.add('ALL_LOCALES')

        # generator for all cog names:
        all_matching_locales = (i for i in my_locales if current.lower() in i.lower())
        # islice to limit to 25 options (discord API limit)
        some_locales = list(islice(all_matching_locales, 25))
        # convert matched list into list of choices
        ret = [app_commands.Choice(name=c, value=c) for c in some_locales]
        return ret


    # TODO: set/save translation string? set_translation(locale, key, value)

    # TODO: SET ALIAS FOR COMMAND TRANSLATION

    # TODO DB list of alias->(command,locale)

    @commands.guild_only()
    @commands.command()
    async def alt_invoke(self, ctx, lang_key: str, locale: str = '', *, json_args: str = ''):
        # invoke another
        pass

    # Command alias suffix if possible?


async def setup(bot):
    await bot.add_cog(LangConfig(bot))
