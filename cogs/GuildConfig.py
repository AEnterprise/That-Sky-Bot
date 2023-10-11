import asyncio
import re

import discord
from discord import Role, TextChannel, Message, AllowedMentions, Forbidden, HTTPException
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Utils, Lang, Questions, Logging
from utils.Database import Guild


class GuildConfig(BaseCog):
    power_task = dict()

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
                await self.init_guild(guild.id)
            except Exception as e:
                Logging.info(e)

    async def init_guild(self, guild_id):
        row, created = await Guild.get_or_create(serverid=guild_id)
        Utils.GUILD_CONFIGS[guild_id] = row
        return row

    def cog_unload(self):
        pass

    async def cog_check(self, ctx):
        if ctx.guild is None:
            return False
        return ctx.author.guild_permissions.ban_members or await self.bot.permission_manage_bot(ctx)

    async def get_guild_config(self, guild_id):
        if guild_id in Utils.GUILD_CONFIGS:
            return Utils.GUILD_CONFIGS[guild_id]
        return await self.init_guild(guild_id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild.id)

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
            await Utils.handle_exception(f"Failed to clear GuildConfig from server {guild.id}", self.bot, e)

    @commands.group(name="guildconfig",
                    aliases=['guild', 'guildconf'],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def guild_config(self, ctx: commands.Context):
        """
        List the guild settings
        """
        my_guild = Utils.GUILD_CONFIGS[ctx.guild.id]
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=Utils.COLOR_LIME,
            title=Lang.get_locale_string("guild_config/info_title", ctx, server_name=ctx.guild.name))

        role_description = "none"
        if my_guild.memberrole:
            role = ctx.guild.get_role(my_guild.memberrole)
            role_description = f"{role.name} ({role.id})"
        embed.add_field(name="Member Role", value=role_description)

        role_description = "none"
        if my_guild.nonmemberrole:
            role = ctx.guild.get_role(my_guild.nonmemberrole)
            role_description = f"{role.name} ({role.id})"
        embed.add_field(name="Nonmember Role", value=role_description)

        role_description = "none"
        if my_guild.mutedrole:
            role = ctx.guild.get_role(my_guild.mutedrole)
            role_description = f"{role.name} ({role.id})"
        embed.add_field(name="Muted Role", value=role_description)

        role_description = "none"
        if my_guild.betarole:
            role = ctx.guild.get_role(my_guild.betarole)
            role_description = f"{role.name} ({role.id})"
        embed.add_field(name="Beta Role", value=role_description)

        channel_description = "none"
        if my_guild.welcomechannelid:
            channel = ctx.guild.get_channel(my_guild.welcomechannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Welcome Channel", value=channel_description)

        channel_description = "none"
        if my_guild.ruleschannelid:
            channel = ctx.guild.get_channel(my_guild.ruleschannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Rules Channel", value=channel_description)

        channel_description = "none"
        if my_guild.logchannelid:
            channel = ctx.guild.get_channel(my_guild.logchannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Log Channel", value=channel_description)

        channel_description = "none"
        if my_guild.entrychannelid:
            channel = ctx.guild.get_channel(my_guild.entrychannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Entry Channel", value=channel_description)

        channel_description = "none"
        if my_guild.maintenancechannelid:
            channel = ctx.guild.get_channel(my_guild.maintenancechannelid)
            channel_description = f"{channel.name} ({channel.id})"
        embed.add_field(name="Maintenance Channel", value=channel_description)

        rules_id = my_guild.rulesreactmessageid if my_guild.rulesreactmessageid else 'none'
        embed.add_field(name="Rules React Message ID", value=rules_id)

        locale = my_guild.defaultlocale if my_guild.defaultlocale else 'none'
        embed.add_field(name="Default Locale", value=locale)

        await ctx.send(embed=embed)

    async def set_field(self, ctx, field, val):
        my_guild = Utils.GUILD_CONFIGS[ctx.guild.id]
        try:
            setattr(my_guild, field, val.id)
            await my_guild.save()
            await self.init_guild(ctx.guild.id)
            await ctx.send(f"Ok! `{field}` is now `{val.name} ({val.id})`")
        except Exception as e:
            await ctx.send(f"I failed to set `{field}` value to `{val.name} ({val.id})`")

    @guild_config.group(invoke_without_command=False)
    @commands.guild_only()
    async def set(self, ctx: commands.Context):
        """
        Set one of the base settings for Skybot in this guild
        """
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @set.command(aliases=['member', 'memberrole'])
    @commands.guild_only()
    async def member_role(self, ctx, role: Role):
        """
        Set the member role

        Used in cogs that read/set/unset the membership role in this server
        role: Role name or role id
        """
        await self.set_field(ctx, 'memberrole', role)

    @set.command(aliases=['nonmember', 'nonmemberrole'])
    @commands.guild_only()
    async def nonmember_role(self, ctx, role: Role):
        """
        Set the nonmember role

        Used in cogs that read/set/unset the nonmember role in this server
        role: Role name or role id
        """
        await self.set_field(ctx, 'nonmemberrole', role)

    @set.command(aliases=['muted', 'mutedrole'])
    @commands.guild_only()
    async def muted_role(self, ctx, role: Role):
        """
        Set the muted role

        Used in cogs that read/set/unset the muted role in this server
        role: Role name or role id
        """
        await self.set_field(ctx, 'mutedrole', role)

    @set.command(aliases=['beta', 'betarole'])
    @commands.guild_only()
    async def beta_role(self, ctx, role: Role):
        """
        Set the beta role

        Used in cogs that read/set/unset the beta role in this server
        role: Role name or role id
        """
        await self.set_field(ctx, 'betarole', role)

    @set.command(aliases=['welcome', 'welcomechannel'])
    @commands.guild_only()
    async def welcome_channel(self, ctx, chan: TextChannel):
        """
        Set the welcome channel

        Used in cogs that read/set/unset the welcome channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'welcomechannelid', chan)

    @set.command(aliases=['rules', 'ruleschannel'])
    @commands.guild_only()
    async def rules_channel(self, ctx, chan: TextChannel):
        """
        Set the rules channel

        Used in cogs that read/set/unset the rules channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'ruleschannelid', chan)

    @set.command(aliases=['log', 'logchannel'])
    @commands.guild_only()
    async def log_channel(self, ctx, chan: TextChannel):
        """
        Set the log channel

        Used in cogs that read/set/unset the log channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'logchannelid', chan)

    @set.command(aliases=['entry', 'entrychannel'])
    @commands.guild_only()
    async def entry_channel(self, ctx, chan: TextChannel):
        """
        Set the entry channel

        Used in cogs that read/set/unset the entry channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'entrychannelid', chan)

    @set.command(aliases=['maintenance', 'maintenancechannel'])
    @commands.guild_only()
    async def maintenance_channel(self, ctx, chan: TextChannel):
        """
        Set the maintenance channel

        Used in cogs that read/set/unset the maintenance channel in this server
        role: Channel name or channel id
        """
        await self.set_field(ctx, 'maintenancechannelid', chan)

    @set.command(aliases=['rulesmessage', 'rulesreactmessage'])
    @commands.guild_only()
    async def rules_react_message(self, ctx, msg: Message):
        """
        Set the rules react message id

        Used in cogs that read/set/unset the rulesreactmessageid in this server
        role: chanelid-messageid, messageid, or url
        """
        my_guild = Utils.GUILD_CONFIGS[ctx.guild.id]
        try:
            my_guild.rulesreactmessageid = msg.id
            await my_guild.save()
            await self.init_guild(ctx.guild.id)
            await ctx.send(f"Ok! `rulesreactmessageid` is now `{msg.id}`")
        except Exception as e:
            await ctx.send(f"I failed to set `rulesreactmessageid` value to `{msg.id}`")

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
