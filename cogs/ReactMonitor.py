import asyncio
from dataclasses import dataclass
import json
import typing
from datetime import datetime
from uuid import uuid4

from discord.app_commands import Group
from tortoise.exceptions import OperationalError

import utils.Utils
from utils.Database import ReactWatch, WatchedEmoji, Guild, BugReportingChannel

import discord
from discord import NotFound, HTTPException, Forbidden, TextChannel, RawReactionActionEvent, app_commands, Interaction, \
    Permissions, InteractionResponse
from discord.ext import commands, tasks

from cogs.BaseCog import BaseCog
from utils import Utils, Configuration, Lang, Logging
from utils.Configuration import get_persistent_var as get_pvar
from utils.Configuration import set_persistent_var as set_pvar
from utils.Configuration import del_persistent_var as del_pvar


@dataclass(init=False)
class VarKeys:
    mutes: str = "react_mutes_"
    rbu_interrupt: str = "react_watch_interrupt"
    quick_react_time: str = "min_react_lifespan_"
    spam_muting_time: str = "react_spam_muting_time_"
    spam_muting_count: str = "react_spam_muting_count_"
    spam_alerting_time: str = "react_spam_alerting_time_"
    spam_alerting_count: str = "react_spam_alerting_count_"
    excluded_channels: str = "react_watch_excluded_channels_"


@dataclass(frozen=True)
class ReactData:
    time: float
    event: RawReactionActionEvent


class ReactMonitor(BaseCog):
    # app command groups
    clean_group = Group(
        name='react',
        description='Reaction controls',
        default_permissions=Permissions(ban_members=True))

    def __init__(self, bot):
        super().__init__(bot)
        Logging.info(f"{self.qualified_name}::init")
        self.excluded_channels = dict()
        self.spam_alerting_count = dict()
        self.react_watch_servers = set()
        self.spam_alerting_time = dict()
        self.spam_muting_count = dict()
        self.recent_reactions = dict()
        self.quick_react_time = dict()
        self.spam_muting_time = dict()
        self.react_removers = dict()
        self.mute_duration = dict()
        self.react_adds = dict()
        self.guilds = dict()
        self.emoji = dict()
        self.mutes = dict()
        self.started = False
        self.check = 0

    async def cog_check(self, ctx):
        return ctx.guild and (ctx.author.guild_permissions.ban_members or await self.bot.permission_manage_bot(ctx))

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        for guild in self.bot.guilds:
            await self.init_guild(guild.id)
        if not self.check_reacts.is_running():
            self.check_reacts.start()
        self.started = True

    def cog_unload(self):
        Logging.info("ReactMonitor::cog_unload")
        self.check_reacts.cancel()

    async def init_guild(self, guild_id):
        Logging.info(f"ReactMonitor::init_guild {guild_id}")
        watch, created = await ReactWatch.get_or_create(serverid=guild_id)
        self.mute_duration[guild_id] = watch.muteduration
        self.mutes[guild_id] = get_pvar(f"{VarKeys.mutes}{guild_id}", dict())
        self.spam_muting_time[guild_id] = get_pvar(f"{VarKeys.spam_muting_time}{guild_id}", 60)
        self.quick_react_time[guild_id] = get_pvar(f"{VarKeys.quick_react_time}{guild_id}", 0.5)
        self.spam_muting_count[guild_id] = get_pvar(f"{VarKeys.spam_muting_count}{guild_id}", 30)
        self.spam_alerting_time[guild_id] = get_pvar(f"{VarKeys.spam_alerting_time}{guild_id}", 30)
        self.spam_alerting_count[guild_id] = get_pvar(f"{VarKeys.spam_alerting_count}{guild_id}", 21)
        self.excluded_channels[guild_id] = get_pvar(f"{VarKeys.excluded_channels}{guild_id}", [])

        # track react add/remove per guild
        self.recent_reactions[guild_id] = dict()
        self.react_removers[guild_id] = dict()
        self.react_adds[guild_id] = dict()

        # list of emoji to watch
        self.emoji[guild_id] = dict()
        for e in await watch.emoji:
            self.emoji[guild_id][e.emoji] = e

        # enable listening if set in db
        if watch.watchremoves:
            await self.activate_react_watch(guild_id)

        self.guilds[guild_id], created = await Guild.get_or_create(serverid=guild_id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        Logging.info("ReactMonitor::on_guild_join")
        await self.init_guild(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        Logging.info("ReactMonitor::on_guild_remove")
        del_pvar(f"{VarKeys.spam_alerting_count}{guild.id}", True)
        del_pvar(f"{VarKeys.spam_alerting_time}{guild.id}", True)
        del_pvar(f"{VarKeys.spam_muting_count}{guild.id}", True)
        del_pvar(f"{VarKeys.quick_react_time}{guild.id}", True)
        del_pvar(f"{VarKeys.spam_muting_time}{guild.id}", True)
        del_pvar(f"{VarKeys.mutes}{guild.id}", True)
        del_pvar(f"{VarKeys.excluded_channels}{guild.id}")

        del self.mutes[guild.id]
        del self.react_adds[guild.id]
        del self.mute_duration[guild.id]
        del self.quick_react_time[guild.id]
        del self.spam_muting_time[guild.id]
        del self.excluded_channels[guild.id]
        del self.spam_alerting_time[guild.id]
        del self.spam_alerting_count[guild.id]
        del self.spam_muting_count[guild.id]
        del self.recent_reactions[guild.id]
        del self.react_removers[guild.id]
        del self.guilds[guild.id]
        del self.emoji[guild.id]
        if guild.id in self.react_watch_servers:
            await self.deactivate_react_watch(guild.id)
        watch = await ReactWatch.get(serverid=guild.id)
        for e in await watch.emoji:
            await e.delete()
        await watch.delete()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id not in self.mutes:
            return

        if str(member.id) in self.mutes[member.guild.id]:
            guild = member.guild
            guild_config = await self.bot.get_guild_db_config(guild.id)
            if guild_config and guild_config.mutedrole:
                try:
                    mute_role = guild.get_role(guild_config.mutedrole)
                    await member.add_roles(mute_role)
                    log_msg = f"{Utils.get_member_log_name(member)} joined while still muted " \
                              f"for banned reacts\n--- I **muted** them... **again**"
                    await self.bot.guild_log(guild.id, log_msg)
                except Exception as e:
                    await Utils.handle_exception("reactmon failed to mute member", self.bot, e)
            else:
                await self.bot.guild_log(
                    guild.id, "**I can't re-mute for reacts because `!guildconfig` mute role is not set.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event: RawReactionActionEvent):
        # TODO: queue emoji adds instead of processing via loop
        await self.store_reaction_action(event)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, event: RawReactionActionEvent):
        # TODO: queue emoji adds instead of processing via loop
        await self.store_reaction_action(event)

    async def store_reaction_action(self, event: RawReactionActionEvent):
        if not self.started or await self.is_user_event_ignored(event):
            return

        # Track event in a dict, with event timestamp as key
        now = datetime.now().timestamp()
        my_id = uuid4()
        try:
            self.recent_reactions[event.guild_id][my_id] = ReactData(time=now, event=event)
        except KeyError as e:
            Logging.debug(f"React Monitory Key error: {json.dumps(e)}")

    async def activate_react_watch(self, guild_id):
        # store setting in db, and add to list of listening servers
        watch = await ReactWatch.get(serverid=guild_id)
        watch.watchremoves = True
        await watch.save()
        self.react_watch_servers.add(guild_id)

    async def deactivate_react_watch(self, guild_id):
        # store setting in db, and remove from list of listening servers
        watch = await ReactWatch.get(serverid=guild_id)
        watch.watchremoves = False
        await watch.save()
        self.react_watch_servers.remove(guild_id)

    async def is_user_event_ignored(self, event: RawReactionActionEvent):
        ignored_channels = [row.channelid for row in await BugReportingChannel.all()]
        is_ignored_channel = event.channel_id in ignored_channels
        guild = self.bot.get_guild(event.guild_id)
        if not guild:
            # Don't listen to DMs
            return True
        is_excluded_channel = event.channel_id in self.excluded_channels[event.guild_id]
        is_bot = event.user_id == self.bot.user.id
        member = guild.get_member(event.user_id)

        if member is None:
            return True  # ignore reaction events from departing members

        is_mod = member and member.guild_permissions.ban_members
        is_admin = await self.bot.member_is_admin(event.user_id)
        has_admin = False

        for role in member.roles:
            # TODO: compare role to role, not role to int
            if role in Configuration.get_var("admin_roles", []):
                has_admin = True

        return is_bot or is_mod or is_admin or has_admin or is_ignored_channel or is_excluded_channel

    async def get_react_lifespan(self, guild_id) -> int:
        return max(self.quick_react_time[guild_id],
                   self.spam_alerting_time[guild_id],
                   self.spam_muting_time[guild_id])

    @tasks.loop(seconds=1.0)
    async def check_reacts(self):
        now = datetime.now().timestamp()
        for guild_id in self.recent_reactions:
            try:
                # Check for expiring mutes
                for user_id, mute_time in dict(self.mutes[guild_id]).items():
                    if float(mute_time) + float(self.mute_duration[guild_id]) < now:
                        try:
                            guild = self.bot.get_guild(guild_id)
                            guild_config = await self.bot.get_guild_db_config(guild_id)
                            if guild_config and guild_config.mutedrole:
                                mute_role = guild.get_role(guild_config.mutedrole)
                                member = guild.get_member(int(user_id))
                                if mute_role in member.roles:
                                    await member.remove_roles(mute_role)
                                del self.mutes[guild_id][user_id]
                        except Exception:
                            del self.mutes[guild_id][user_id]
                            await self.bot.guild_log(
                                guild_id,
                                f'Failed to unmute user ({user_id}) <@{user_id}>... did they leave the server?')

                # creat list of reaction adds
                rr = self.recent_reactions[guild_id]
                data: ReactData
                adds = {my_id: data for (my_id, data) in rr.items() if data.event.event_type == "REACTION_ADD"}
                for my_id, data in adds.items():
                    self.react_adds[guild_id][my_id] = data

                # cull out expired ones
                for my_id, data in dict(self.react_adds[guild_id]).items():
                    if data.time + (await self.get_react_lifespan(guild_id)) < now:
                        # add reaction is too far in the past. remove from the list
                        del self.react_adds[guild_id][my_id]

                # process recent reactions and remove each from the list.
                for my_id, data in dict(self.recent_reactions[guild_id]).items():
                    # remove this one from the list, ignoring exceptions
                    del self.recent_reactions[guild_id][my_id]

                    try:
                        if data.event.event_type == "REACTION_ADD":
                            await self.process_reaction_add(data)
                        if data.event.event_type == "REACTION_REMOVE":
                            await self.process_reaction_remove(data)
                    except Exception as ex:
                        await Utils.handle_exception('Failed to process a react', self.bot, ex)

            except Exception as ex:
                await Utils.handle_exception('react watch loop error...', self.bot, ex)

    @check_reacts.after_loop
    async def check_reacts_done(self):
        Logging.info("\t------ check reacts loop completed ------")

    async def process_reaction_add(self, data: ReactData):
        await self.spam_check(data)
        await self.apply_reaction_add_rules(data)

    async def spam_check(self, data: ReactData):
        member = data.event.member
        emoji_used = data.event.emoji
        guild = self.bot.get_guild(data.event.guild_id)
        channel = self.bot.get_channel(data.event.channel_id)

        alerting = []
        for my_id, data in self.react_adds[data.event.guild_id].items():
            pass

        # TODO: count reacts added within time interval
        # TODO: alert after alerting threshold
        # TODO: mute after muting threshold
        return

    # TODO: configure alerting threshold

    # TODO: configure muting threshold

    @commands.group(name="reactmonitor",
                    aliases=['reactmon', 'reactwatch', 'watcher'],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def react_monitor(self, ctx: commands.Context):
        """
        List the watched emoji and their settings
        """
        max_fields = 24
        watch = await ReactWatch.get(serverid=ctx.guild.id)
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=Utils.COLOR_LIME,
            title=Lang.get_locale_string("react_monitor/info_title", ctx, server_name=ctx.guild.name))

        embed.add_field(name="Monitor React Removal", value="Yes" if watch.watchremoves else "No")

        if watch.watchremoves:
            embed.add_field(name="Reaction minimum lifespan", value=f"{self.quick_react_time[ctx.guild.id]} seconds")
        embed.add_field(name="React spam alerting time",
                        value=utils.Utils.to_pretty_time(self.spam_alerting_time[ctx.guild.id]))
        embed.add_field(name="React spam muting time",
                        value=utils.Utils.to_pretty_time(self.spam_muting_time[ctx.guild.id]))
        embed.add_field(name="React spam alerting count",
                        value=utils.Utils.to_pretty_time(self.spam_alerting_count[ctx.guild.id]))
        embed.add_field(name="React spam muting count",
                        value=utils.Utils.to_pretty_time(self.spam_muting_count[ctx.guild.id]))
        embed.add_field(name="Mute duration", value=Utils.to_pretty_time(self.mute_duration[ctx.guild.id]))
        embed.add_field(name="__                                             __",
                        value="__                                             __",
                        inline=False)

        if ctx.guild.id in self.emoji:
            for key, emoji in self.emoji[ctx.guild.id].items():
                if len(embed.fields) == max_fields:
                    await ctx.send(embed=embed)
                    embed = discord.Embed(
                        color=Utils.COLOR_LIME,
                        title="...")
                embed.add_field(
                    name=f"{emoji.emoji}",
                    value=self.describe_emoji_watch_settings(emoji),
                    inline=True)

        await ctx.send(embed=embed)

    @staticmethod
    def describe_emoji_watch_settings(emoji):
        flags = [f"__*{name}*__" for name in ['log', 'remove', 'mute'] if getattr(emoji, name)]
        val = ' | '.join(flags) if flags else '__*no action*__'
        return val

    @react_monitor.command(aliases=["new", "edit", "update"])
    @commands.guild_only()
    async def add(self, ctx: commands.Context, emoji, log: bool = True, remove: bool = False, mute: bool = False):
        """
        Add an emoji to the reaction watchlist

        emoji: The emoji to add
        log: Boolean - Log use of this emoji
        remove: Boolean - Auto-remove when this emoji is used
        mute: Boolean - Auto-mute members who use this emoji
        """
        try:
            watch, created = await ReactWatch.get_or_create(serverid=ctx.guild.id)
            new_emoji, created = await WatchedEmoji.get_or_create(watcher_id=watch.id, emoji=emoji)
            new_emoji.log = log
            new_emoji.remove = remove
            new_emoji.mute = mute
            await new_emoji.save()
            self.emoji[ctx.guild.id][emoji] = new_emoji
        except Exception as e:
            await Utils.handle_exception("failed to add emoji to watch list", self.bot, e)

        await ctx.send(f"`{emoji}` is now on the watch list with settings:\n"
                       f"{self.describe_emoji_watch_settings(self.emoji[ctx.guild.id][emoji])}")

    @clean_group.command(description="Clean recent reacts from a member")
    @app_commands.describe(
        target="The member whose reacts should be removed",
        check_channel="Optional channel to check in. Leave blank to check all channels",
        count="Number of messages to check per channel, starting from the most recent")
    @app_commands.default_permissions(ban_members=True)
    @commands.guild_only()
    async def clean_by_user(
            self,
            interaction: Interaction,
            target: discord.User,
            check_channel: discord.TextChannel = None,
            count: int = 200):
        set_pvar(VarKeys.rbu_interrupt, False)
        r = typing.cast(InteractionResponse, interaction.response)
        channels = interaction.guild.channels if check_channel is None else [check_channel]
        await r.send_message(f"Looking for reacts on the {count} most recent messages in "
                             "all available channels" if check_channel is None else check_channel.mention)
        excluded_channels = self.excluded_channels[interaction.guild.id]
        for channel in channels:
            if isinstance(channel, TextChannel):
                if channel.id in excluded_channels:
                    await interaction.followup.send(f"<#{channel.id}> skipped")
                    continue
                try:
                    i = 0
                    await interaction.followup.send(f"checking <#{channel.id}>...")
                    async for message in channel.history(limit=count):
                        interrupt = get_pvar(VarKeys.rbu_interrupt, False)
                        if interrupt:
                            set_pvar(VarKeys.rbu_interrupt, False)
                            await interaction.followup.send(f"__remove react by user__ operation halted.")
                            return
                        i += 1
                        for react in message.reactions:
                            async for user in react.users():
                                if user.id == target.id:
                                    await message.clear_reaction(react.emoji)
                                    await interaction.followup.send(
                                        f"__{i}.__ react {react.emoji} by userid ({user.id}) "
                                        f"removed from message {message.jump_url}")
                                    continue
                except Forbidden:
                    await interaction.followup.send(f"I can't access message history in channel <#{channel.id}>")
        await interaction.followup.send("All done cleaning reacts")

    @clean_group.command(description="Abort any in-progress react cleanup process")
    @commands.guild_only()
    async def stop_clean_by_user(self, interaction: Interaction):
        r = typing.cast(InteractionResponse, interaction.response)
        set_pvar(VarKeys.rbu_interrupt, True)
        await r.send_message(f"aborting __remove react by user__ operation. If this doesn't work, KILL THE BOT!")

    @clean_group.command(description="List channels that are excluded from react spam cleanup")
    @commands.guild_only()
    async def list_excluded(self, interaction: Interaction):
        r = typing.cast(InteractionResponse, interaction.response)
        Logging.info(self.excluded_channels)
        excluded_channels = self.excluded_channels[interaction.guild_id]
        excluded_channels = [self.bot.get_channel(c).mention for c in excluded_channels]
        if not excluded_channels:
            await r.send_message(f"No channels are excluded from react remove_by_user")
        else:
            channel_list = "\n".join(excluded_channels)
            await r.send_message(f"Channels excluded from react remove_by_user:\n{channel_list}")

    @clean_group.command(description="Exclude channel from react spam cleanup")
    @app_commands.describe(channel="Channel to exclude")
    @commands.guild_only()
    async def exclude_channel(self, interaction: Interaction, channel: discord.TextChannel):
        r = typing.cast(InteractionResponse, interaction.response)
        excluded_channels = self.excluded_channels[interaction.guild_id]
        excluded_channels = set(excluded_channels)
        if channel.id not in excluded_channels:
            excluded_channels.add(channel.id)
            set_pvar(f"{VarKeys.excluded_channels}{interaction.guild_id}", list(excluded_channels))
            self.excluded_channels[interaction.guild_id] = list(excluded_channels)
            await r.send_message(f"Added {channel.mention} to react spam channel exclusion list")
            return
        await r.send_message(f"No channel added to exclusion list")

    @clean_group.command(description="Remove channel from exclusion list for react spam cleanup")
    @app_commands.describe(channel="Channels to remove from exclusion")
    @commands.guild_only()
    async def unexclude_channel(self, interaction: Interaction, channel: discord.TextChannel):
        r = typing.cast(InteractionResponse, interaction.response)
        excluded_channels = self.excluded_channels[interaction.guild_id]
        excluded_channels = set(excluded_channels)
        if channel.id in excluded_channels:
            excluded_channels.remove(channel.id)
            set_pvar(f"{VarKeys.excluded_channels}{interaction.guild_id}", list(excluded_channels))
            self.excluded_channels[interaction.guild_id] = list(excluded_channels)
            await r.send_message(f"Removed {channel.mention} from react spam channel exclusion list")
            return
        await r.send_message(f"No channel removed from exclusion list")

    @react_monitor.command(aliases=["rem", "del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, emoji):
        """
        Remove an emoji from the watch list
        :param ctx:
        :param emoji: The emoji to remove
        """
        try:
            watch_row = await WatchedEmoji.get(watcher__serverid=ctx.guild.id, emoji=emoji)
            await watch_row.delete()
            del self.emoji[ctx.guild.id][emoji]
            await ctx.send(f"I removed `{emoji}` from the watch list")
        except OperationalError:
            await ctx.send(f"I couldn't find `{emoji}` on the emoji watch list, so I didn't remove it.")
        except Exception as e:
            await Utils.handle_exception("react remove failed", self.bot, e)

    @react_monitor.command(aliases=['on'])
    @commands.guild_only()
    async def monitor_removal_on(self, ctx: commands.Context):
        """
        Turn ON monitor for spammy fast-removal of reactions
        """
        if ctx.guild.id in self.react_watch_servers:
            await ctx.send("React monitor is already on")
        else:
            await self.activate_react_watch(ctx.guild.id)
            await ctx.send("I'm on the lookout for reaction spam!")

    @react_monitor.command(aliases=['off'])
    @commands.guild_only()
    async def monitor_removal_off(self, ctx: commands.Context):
        """
        Turn OFF monitor for spammy fast-removal of reactions
        """
        if ctx.guild.id in self.react_watch_servers:
            await self.deactivate_react_watch(ctx.guild.id)
            await ctx.send("OK, I'll stop watching for reaction spams")
        else:
            await ctx.send("React monitor is already off")

    @react_monitor.command(aliases=["time", "reacttime"])
    @commands.guild_only()
    async def react_time(self, ctx: commands.Context, react_time: float):
        """
        Reacts removed before this duration will trigger react-watch

        react_time: time in seconds, floating point e.g. 0.25
        """
        self.quick_react_time[ctx.guild.id] = react_time
        set_pvar(f"{VarKeys.quick_react_time}{ctx.guild.id}", react_time)
        await ctx.send(f"Reactions that are removed before {react_time} seconds have passed will be flagged")

    @react_monitor.command(aliases=["list", "mutes"])
    @commands.guild_only()
    async def list_mutes(self, ctx: commands.Context):
        if self.mutes[ctx.guild.id]:
            react_muted = list()
            guild_config = await self.bot.get_guild_db_config(ctx.guild.id)
            mute_role = ctx.guild.get_role(guild_config.mutedrole)

            for member_id, timestamp in self.mutes[ctx.guild.id].items():
                member = ctx.guild.get_member(int(member_id))
                if member is not None:
                    long_name = Utils.get_member_log_name(member)
                    if mute_role not in member.roles:
                        # panic because role is not present when it should be
                        await ctx.send(f"{long_name} should be muted for banned reacts... but isn't. ***WHY NOT??***")
                    react_muted.append(long_name)

            names = "\n".join(react_muted)
            await ctx.send(f"__Members muted for banned reacts:__\n{names}")
        else:
            await ctx.send(f"Nobody is muted for banned reacts")

    @react_monitor.command(aliases=["purge", "purgemutes"])
    @commands.guild_only()
    async def purge_mutes(self, ctx: commands.Context):
        if self.mutes[ctx.guild.id]:
            react_unmuted = list()
            guild_config = await self.bot.get_guild_db_config(ctx.guild.id)
            mute_role = ctx.guild.get_role(guild_config.mutedrole)

            for member_id, timestamp in dict(self.mutes[ctx.guild.id]).items():
                member = ctx.guild.get_member(int(member_id))
                if member is not None:
                    await member.remove_roles(mute_role)
                    del self.mutes[ctx.guild.id][member_id]
                    long_name = Utils.get_member_log_name(member)
                    react_unmuted.append(long_name)

            names = "\n".join(react_unmuted)
            await ctx.send(f"__React mutes purged:__\n{names}")
        else:
            await ctx.send(f"Nobody is muted for banned reacts. Can't purge.")

    @react_monitor.command(aliases=["mutetime", "mute"])
    @commands.guild_only()
    async def mute_time(self, ctx: commands.Context, mute_time: float):
        """
        Set the duration for mutes given when mute-enabled reacts are used

        mute_time: time in seconds, floating point e.g. 0.25
        """
        self.mute_duration[ctx.guild.id] = mute_time
        watch, created = await ReactWatch.get_or_create(serverid=ctx.guild.id)
        watch.muteduration = mute_time
        await watch.save()
        t = Utils.to_pretty_time(mute_time)
        await ctx.send(f"Members will now be muted for {t} when they use restricted reacts")

    async def apply_reaction_add_rules(self, data: ReactData):
        """
        Enforce the rules on added reactions
        :param data:
        :return:
        """
        emoji_used = data.event.emoji
        member = data.event.member
        guild = self.bot.get_guild(data.event.guild_id)
        channel = self.bot.get_channel(data.event.channel_id)

        # Check emoji match list. log, remove, and mute:
        if str(emoji_used) in self.emoji[guild.id]:
            emoji_rule = self.emoji[guild.id][str(emoji_used)]
            if not emoji_rule.log and not emoji_rule.remove and not emoji_rule.mute:
                # No actions to take. Stop processing
                return
        else:
            return

        # check mute/warn list for reaction_add - log to channel
        # for reaction_add, remove if threshold for quick-remove is passed
        try:
            # message fetch is API call. Only do it if needed
            message = channel.get_partial_message(data.event.message_id)
        except (NotFound, HTTPException):
            # Can't track reactions on a message I can't find
            # Happens for deleted messages. Safe to ignore.
            # await Utils.handle_exception(f"Failed to get message {channel.id}/{data.event.message_id}", self, e)
            return

        log_msg = f"{Utils.get_member_log_name(member)} used emoji " \
                  f"[ {emoji_used} ] in #{channel.name}.\n" \
                  f"{message.jump_url}"

        if emoji_rule.remove:
            await message.clear_reaction(emoji_used)
            log_msg = f"{log_msg}\n--- I **removed** the reaction"

        if emoji_rule.mute:
            guild_config = await self.bot.get_guild_db_config(guild.id)
            if guild_config and guild_config.mutedrole:
                try:
                    mute_role = guild.get_role(guild_config.mutedrole)
                    await member.add_roles(mute_role)
                    self.mutes[guild.id][str(member.id)] = data.time
                    set_pvar(f"{VarKeys.mutes}{guild.id}", self.mutes[guild.id])
                    log_msg = f"{log_msg}\n--- I **muted** them"
                except Exception as e:
                    await Utils.handle_exception("reactmon failed to mute member", self.bot, e)
            else:
                await self.bot.guild_log(
                    guild.id, "**I can't mute for reacts because `!guildconfig` mute role is not set.")

        if emoji_rule.log or emoji_rule.remove or emoji_rule.mute:
            await self.bot.guild_log(guild.id, log_msg)

    async def process_reaction_remove(self, remove_data: ReactData):
        # TODO: Evaluate - count react removal and auto-mute for hitting threshold in given time?
        #  i.e. track react-remove-count per user over time. if count > x: mute/warn

        # Add user_id to dict of recent reaction removers with timestamp
        # now = datetime.now().timestamp()
        # self.react_removers[event.guild_id][event.user_id] = now

        event = remove_data.event
        # don't bother with ignored channels
        if event.message_id in self.excluded_channels[event.guild_id]:
            return

        # listening setting only applies to quick-remove
        server_is_listening = event.guild_id in self.react_watch_servers
        if not server_is_listening or await self.is_user_event_ignored(event):
            return

        # check recent reacts to see if they match the remove event
        data: ReactData
        for my_id, data in self.react_adds[event.guild_id].items():
            # Criteria for skipping an event in the list
            not_message = data.event.message_id != event.message_id
            not_user = data.event.user_id != event.user_id

            age = remove_data.time - data.time
            # only look at reacts that are removed within quick-react expiration time
            expired = 0 > age > self.quick_react_time[event.guild_id]
            if expired or not_message or not_user:
                # message id and user id must match remove event, and must not be expired
                continue

            # This user added a reaction that was removed within the warning time window
            guild = self.bot.get_guild(event.guild_id)
            emoji_used = str(event.emoji)
            channel = self.bot.get_channel(event.channel_id)

            # ping log channel with detail
            content = f"{Utils.get_member_log_name(guild.get_member(event.user_id))} " \
                      f"quick-removed [ {emoji_used} ] react from a message in {channel.mention}"
            try:
                message = await channel.fetch_message(event.message_id)
                content = f"{content}\n{message.jump_url}"
            except (NotFound, HTTPException):
                pass
            await self.bot.guild_log(guild.id, content)


async def setup(bot):
    await bot.add_cog(ReactMonitor(bot))
