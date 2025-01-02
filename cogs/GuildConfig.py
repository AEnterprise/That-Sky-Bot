import asyncio
import re
from typing import Literal

import discord
from discord import (Role, TextChannel, AllowedMentions, Forbidden, HTTPException, NotFound, Interaction,
                    app_commands, Permissions, InteractionResponded, DiscordException)
from discord.ext import commands
from discord.app_commands import Group
from tortoise.exceptions import OperationalError

from cogs.BaseCog import BaseCog
from utils import Utils, Lang, Questions, Logging
from utils.Constants import COLOR_LIME
from utils.Database import Guild
from utils.Utils import interaction_response


class GuildConfig(BaseCog):
    power_task = dict()

    # app command groups
    guild_command = Group(
        name='server',
        description='Server Configuration',
        guild_only=True,
        default_permissions=Permissions(ban_members=True))

    def __init__(self, bot):
        super().__init__(bot)
        self.loaded_guilds = []

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        for guild in self.bot.guilds:
            try:
                await GuildConfig.init_guild(guild.id)
            except Exception as e:
                Logging.info(e)

    @staticmethod
    async def init_guild(guild_id):
        row, created = await Guild.get_or_create(serverid=guild_id)
        Utils.GUILD_CONFIGS[guild_id] = row
        return row

    def cog_unload(self):
        pass

    async def cog_check(self, ctx):
        if ctx.guild is None:
            return False
        return ctx.author.guild_permissions.ban_members or await Utils.permission_manage_bot(ctx)

    async def get_guild_config(self, guild_id):
        if guild_id in Utils.GUILD_CONFIGS:
            return Utils.GUILD_CONFIGS[guild_id]
        return await GuildConfig.init_guild(guild_id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await GuildConfig.init_guild(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del Utils.GUILD_CONFIGS[guild.id]
        # keep guild record and clear channel configs and default lang
        try:
            guild_row = await Guild.get(serverid=guild.id)
            guild_row.memberrole = 0
            guild_row.nonmemberrole = 0
            guild_row.mutedrole = 0
            guild_row.betarole = 0
            guild_row.welcomechannelid = 0
            guild_row.ruleschannelid = 0
            guild_row.logchannelid = 0
            guild_row.entrychannelid = 0
            guild_row.maintenancechannelid = 0
            guild_row.rulesreactmessageid = 0
            guild_row.defaultlocale = ''
            await guild_row.save()
        except Exception as e:
            await Utils.handle_exception(f"Failed to clear GuildConfig from server {guild.id}", e)

    @guild_command.command(description="View server settings")
    async def list_settings(self, interaction: Interaction):
        """
        List the guild settings
        """
        my_guild = Utils.GUILD_CONFIGS[interaction.guild.id]
        embed = discord.Embed(
            timestamp=interaction.created_at,
            color=COLOR_LIME,
            title=Lang.get_locale_string("guild_config/info_title", interaction, server_name=interaction.guild.name))

        role_description = "none"
        if my_guild.memberrole:
            role = interaction.guild.get_role(my_guild.memberrole)
            role_description = f"{role.mention} __{role.id}__" if role else f"~~{my_guild.memberrole}~~"

        embed.add_field(name="Member Role", value=role_description)

        role_description = "none"
        if my_guild.nonmemberrole:
            role = interaction.guild.get_role(my_guild.nonmemberrole)
            role_description = f"{role.mention} __{role.id}__" if role else f"~~{my_guild.nonmemberrole}~~"
        embed.add_field(name="Nonmember Role", value=role_description)

        role_description = "none"
        if my_guild.mutedrole:
            role = interaction.guild.get_role(my_guild.mutedrole)
            role_description = f"{role.mention} __{role.id}__" if role else f"~~{my_guild.mutedrole}~~"
        embed.add_field(name="Muted Role", value=role_description)

        role_description = "none"
        if my_guild.betarole:
            role = interaction.guild.get_role(my_guild.betarole)
            role_description = f"{role.mention} __{role.id}__" if role else f"~~{my_guild.betarole}~~"
        embed.add_field(name="Beta Role", value=role_description)

        channel_description = "none"
        if my_guild.welcomechannelid:
            channel = interaction.guild.get_channel(my_guild.welcomechannelid)
            channel_description = f"{channel.mention} __{channel.id}__" if channel else f"~~{my_guild.welcomechannelid}~~"
        embed.add_field(name="Welcome Channel", value=channel_description)

        channel_description = "none"
        if my_guild.ruleschannelid:
            channel = interaction.guild.get_channel(my_guild.ruleschannelid)
            channel_description = f"{channel.mention} __{channel.id}__" if channel else f"~~{my_guild.ruleschannelid}~~"
        embed.add_field(name="Rules Channel", value=channel_description)

        channel_description = "none"
        if my_guild.logchannelid:
            channel = interaction.guild.get_channel(my_guild.logchannelid)
            channel_description = f"{channel.mention} __{channel.id}__" if channel else f"~~{my_guild.logchannelid}~~"
        embed.add_field(name="Log Channel", value=channel_description)

        channel_description = "none"
        if my_guild.entrychannelid:
            channel = interaction.guild.get_channel(my_guild.entrychannelid)
            channel_description = f"{channel.mention} __{channel.id}__" if channel else f"~~{my_guild.entrychannelid}~~"
        embed.add_field(name="Entry Channel", value=channel_description)

        channel_description = "none"
        if my_guild.maintenancechannelid:
            channel = interaction.guild.get_channel(my_guild.maintenancechannelid)
            channel_description = f"{channel.mention} __{channel.id}__" if channel else f"~~{my_guild.maintenancechannelid}~~"
        embed.add_field(name="Maintenance Channel", value=channel_description)

        rules_id = my_guild.rulesreactmessageid if my_guild.rulesreactmessageid else 'none'
        embed.add_field(name="Rules React Message ID", value=rules_id)

        locale = my_guild.defaultlocale if my_guild.defaultlocale else 'none'
        embed.add_field(name="Default Locale", value=locale)

        await interaction_response(interaction).send_message(embed=embed, allowed_mentions=AllowedMentions.none())

    async def set_field(self, interaction: Interaction, field, val):
        my_guild = Utils.GUILD_CONFIGS[interaction.guild.id]
        r = interaction_response(interaction)
        try:
            setattr(my_guild, field, val.id)
            await my_guild.save()
            await GuildConfig.init_guild(interaction.guild.id)
            await r.send_message(f"Ok! `{field}` is now {val.mention} ({val.id})", allowed_mentions=AllowedMentions.none())
        except (OperationalError, KeyError, HTTPException, TypeError, ValueError, InteractionResponded) as e:
            log_msg = f"failed to set guild config `{field}` to {val.name}  ({val.id})"
            Logging.info(log_msg, exc_info=True)
            await Utils.handle_exception(log_msg, e)
            await r.send_message(log_msg, allowed_mentions=AllowedMentions.none())

    @guild_command.command(description="Modify server channel settings")
    @app_commands.describe(
        setting="The server channel configuration to change",
        channel="The channel")
    async def set_channel(
            self,
            interaction: Interaction,
            setting: Literal[
                'welcomechannelid',
                'ruleschannelid',
                'logchannelid',
                'entrychannelid',
                'maintenancechannelid'
            ],
            channel: TextChannel):
        """
        Set one of the base channel settings for Skybot in this guild
        """
        await self.set_field(interaction, setting, channel)

    @guild_command.command(description="Modify server role settings")
    @app_commands.describe(
        setting="The server role configuration to change",
        role="The role")
    async def set_role(
            self,
            interaction: Interaction,
            setting: Literal[
                'memberrole',
                'nonmemberrole',
                'mutedrole',
                'betarole'
            ],
            role: Role):
        """
        Set one of the base role settings for Skybot in this guild
        """
        await self.set_field(interaction, setting, role)

    @guild_command.command(description="Set react message ID")
    @app_commands.describe(msg="The react message")
    async def react_msg(
            self,
            interaction: Interaction,
            msg: str):
        """
        Set the rules react message id
        """
        my_guild = Utils.GUILD_CONFIGS[interaction.guild.id]
        r = interaction_response(interaction)

        my_id = int(msg)
        my_channel = interaction.guild.get_channel(my_guild.ruleschannelid)
        try:
            my_message = await my_channel.fetch_message(my_id)
        except (NotFound, Forbidden, HTTPException):
            await r.send_message(f"`{msg}` is not a message ID in the welcome channel")
            return

        try:
            my_guild.rulesreactmessageid = my_id
            await my_guild.save()
            await GuildConfig.init_guild(interaction.guild.id)
            await r.send_message(f"Ok! `rulesreactmessageid` is now `{my_id}`")
        except OperationalError:
            await r.send_message(f"I failed to save `rulesreactmessageid` value `{my_id}` in db")
        except DiscordException:
            Logging.info(f"I failed to send confirmation: `rulesreactmessageid` value set to `{my_id}`")
        except Exception as e:
            Logging.info(f"unexpected exception {e} while setting `rulesreactmessageid` value to `{my_id}`")

    @commands.command(aliases=["stop"])
    @commands.guild_only()
    async def stop_kick(self, ctx):
        if ctx.guild.id in self.power_task:
            self.power_task[ctx.guild.id].cancel()
            del self.power_task[ctx.guild.id]
            await ctx.send("Ok, I stopped the task")
        else:
            await ctx.send("No task to stop")

    @commands.command(aliases=["powerkick"])
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def power_kick(self, ctx):
        """
        Kick EVERYONE (except certain roles or channel members)
        """
        protected_roles = dict()
        protected_channels = dict()

        if ctx.guild.id in self.power_task:
            await ctx.send("power task is already in progress... try again later")
            return

        async def ask_for_roles():
            nonlocal protected_roles

            # prompt for roles to protect
            try:
                role_list = await Questions.ask_text(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    "Give me a list of role IDs to protect from kick (separated by spaces). Mods and higher will not be kicked.",
                    locale=ctx)
            except asyncio.TimeoutError as ex:
                return

            role_list = re.sub('[, ]+', ' ', role_list)
            role_list = role_list.strip().split(' ')
            protected_roles = set()

            for role_id in role_list:
                try:
                    a_role = ctx.guild.get_role(int(role_id))
                    if a_role:
                        protected_roles.add(a_role)
                except ValueError:
                    pass

            if not protected_roles:
                await ctx.send("You didn't give me any known role IDs. There will be NO protected roles")

        async def ask_for_channels():
            nonlocal protected_channels

            # prompt for channels to protect
            try:
                channel_list = await Questions.ask_text(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    "Give me a list of channel IDs to protect from kick (separated by spaces)",
                    locale=ctx)
            except asyncio.TimeoutError as ex:
                return

            channel_list = re.sub('[, ]+', ' ', channel_list)
            channel_list = channel_list.strip().split(' ')
            protected_channels = set()

            for channel_id in channel_list:
                try:
                    a_channel = ctx.guild.get_channel(int(channel_id))
                    if a_channel:
                        protected_channels.add(a_channel)
                except ValueError:
                    pass

            if not channel_list:
                await ctx.send("You didn't give me any known channel IDs. There will be NO protected channels")

        await ask_for_roles()
        await ask_for_channels()

        kick_members = set()
        protected_members = set()
        protected_roles_descriptions = []
        protected_channels_descriptions = []

        for this_role in protected_roles:
            protected_roles_descriptions.append(f"`{this_role.name} ({this_role.id})`")
            for member in this_role.members:
                protected_members.add(member)

        for this_channel in protected_channels:
            protected_channels_descriptions.append(f"`{this_channel.name} ({this_channel.id})`")
            for member in this_channel.members:
                protected_members.add(member)

        # protect bots, mods, and higher
        for member in ctx.guild.members:
            if (member.bot
                    or member.guild_permissions.ban_members
                    or member.guild_permissions.manage_channels
                    or await self.bot.member_is_admin(member.id)):
                protected_members.add(member)
            if member not in protected_members:
                kick_members.add(member)

        if not protected_members:
            await ctx.send("There are no members in the roles and/or channels you specified. Try again!")
            return

        protected_roles_descriptions = '\n'.join(protected_roles_descriptions)
        protected_channels_descriptions = '\n'.join(protected_channels_descriptions)

        prompt = ""
        if protected_roles_descriptions:
            prompt += f"These roles will be protected from power_kick:\n{protected_roles_descriptions}"
            prompt += "\n"
        if protected_channels_descriptions:
            prompt += f"These channels will be protected from power_kick:\n{protected_channels_descriptions}"
            prompt += "\n"
        prompt += f"That's a total of `{len(kick_members)}` members to kick," \
                  f" and `{len(protected_members)}` member(s) who will NOT be kicked"
        prompt += "\nI can't kick nobody. Try again, but do it better" if not kick_members else ''

        await ctx.send(prompt, allowed_mentions=AllowedMentions.none())

        if not kick_members:
            return

        show_protected_members = False
        kick_approved = False

        def show_protected():
            nonlocal show_protected_members
            show_protected_members = True

        def approve_kick():
            nonlocal kick_approved
            kick_approved = True

        try:
            await Questions.ask(
                self.bot, ctx.channel, ctx.author, "Would you like to see a list of members who will not be kicked?",
                [
                    Questions.Option('YES', 'Yes', handler=lambda: show_protected()),
                    Questions.Option('NO', 'No')
                ], show_embed=True, timeout=30, locale=ctx)
        except asyncio.TimeoutError as ex:
            pass

        if show_protected_members:
            protected_members_descriptions = []
            for this_member in protected_members:
                protected_members_descriptions.append(Utils.get_member_log_name(this_member))

            protected_members_descriptions = '\n'.join(protected_members_descriptions)
            protected_members_descriptions = Utils.paginate(protected_members_descriptions)
            for page in protected_members_descriptions:
                await ctx.send(page, allowed_mentions=AllowedMentions.none())

        try:
            await Questions.ask(
                self.bot, ctx.channel, ctx.author,
                "If that looks right, should I start kicking everyone else (it might take a little while)?",
                [
                    Questions.Option('YES', 'Yes', handler=lambda: approve_kick()),
                    Questions.Option('NO', 'No')
                ], show_embed=True, timeout=10, locale=ctx)
        except asyncio.TimeoutError as ex:
            return

        if kick_approved:
            # start task and exit command
            self.power_task[ctx.guild.id] = self.bot.loop.create_task(self.do_power_kick(ctx, protected_members))
            return
        else:
            await ctx.send(f"Ok, nobody was kicked")

    async def do_power_kick(self, ctx, protected_members):
        the_saved = []
        for member in ctx.guild.members:
            if member not in protected_members and \
                    not member.bot and \
                    not member.guild_permissions.ban_members and \
                    not member.guild_permissions.manage_channels and\
                    not await self.bot.member_is_admin(member.id):
                await ctx.send(f"kicking {Utils.get_member_log_name(member)}",
                               allowed_mentions=AllowedMentions.none())
                try:
                    await ctx.guild.kick(member)
                except Forbidden:
                    await ctx.send(f"I'm not allowed to kick {Utils.get_member_log_name(member)} (forbidden)",
                                   allowed_mentions=AllowedMentions.none())
                except HTTPException:
                    await ctx.send(f"I failed to kick {Utils.get_member_log_name(member)} (http exception)",
                                   allowed_mentions=AllowedMentions.none())
            else:
                the_saved.append(Utils.get_member_log_name(member))

        # list count of members who will remain
        the_saved_description = '\n'.join(the_saved)
        the_saved_description = Utils.paginate(the_saved_description)
        await ctx.send("`These members were not kicked:`")
        for page in the_saved_description:
            await ctx.send(page, allowed_mentions=AllowedMentions.none())

        # TODO: ping on task completion?
        del self.power_task[ctx.guild.id]


async def setup(bot):
    await bot.add_cog(GuildConfig(bot))
