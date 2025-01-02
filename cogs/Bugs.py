import asyncio
import re
import time
from asyncio import CancelledError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Literal, Union, List

import discord
from discord import (Forbidden, Embed, NotFound, HTTPException, TextChannel, AllowedMentions, app_commands,
                     Interaction, User, Permissions)
from discord.app_commands import Group
from discord.ext import commands, tasks
from discord.ext.commands import Context, UserInputError
from discord.utils import utcnow
from tortoise.exceptions import DoesNotExist, OperationalError, IntegrityError

from cogs.BaseCog import BaseCog
from sky import queue_worker
from utils import Questions, Emoji, Utils, Configuration, Lang, Logging
from utils.Constants import NUMBER_MATCHER
from utils.Database import BugReport, Attachments, BugReportingPlatform, BugReportingChannel
from utils.Database import Guild, BugReportFieldLength
from utils.Helper import Sender
from utils.Logging import TCol
from utils.Utils import get_member_log_name, interaction_response, permission_official_ban, permission_manage_bot


@dataclass()
class BugReportingAction:
    user: User
    channel: TextChannel
    interaction: Optional[Interaction] = None
    uuid: str = field(default_factory=Utils.get_new_uuid_str)


class BugReportCancelReason(Enum):
    User = "user"
    Sweep = "sweep"
    Unload = "unload"
    Shutdown = "shutdown"

    def __repr__(self):
        return self.value


class CommandMode:
    __slots__ = ()
    Add: str = "Add"
    Remove: str = "Remove"
    Edit: str = "Edit"
    AddRemove = Literal["Add", "Remove"]
    AddRemoveEdit = Literal["Add", "Remove", "Edit"]


class UserCanceledError(CancelledError):
    """Report canceled by user"""


class Bugs(BaseCog):

    bug_report_queue = asyncio.Queue()

    def __init__(self, bot):
        super().__init__(bot)
        self.ready_task = None
        self.bug_messages = set()
        self.in_progress = dict()
        self.sweeps = dict()
        self.blocking = set()
        self.maintenance_message = None
        self.maint_check_count = 0
        self.bug_tasks = []
        self.task_limit = 200
        self.shutting_down = False

        Logging.info(f"\tstarting {self.task_limit} bug tasks", TCol.Warning)
        self.bug_runner_tasks = [
            asyncio.create_task(
                queue_worker(f"Bug Queue {i}", self.bug_report_queue, self.run_bug_report))
            for i in range(self.task_limit)
        ]

    async def cog_unload(self):
        Logging.info(f"{self.qualified_name}::cog_unload", TCol.Bold, TCol.Warning)
        if self.bug_report_queue.qsize() > 0:
            Logging.info(f"\tthere are {self.bug_report_queue.qsize()} bug reports not yet started...")
            # TODO: add bugreportinguser[ 0+ device[hardware_info, os, sky_build], 0+ branch ]
            # TODO: clean DxDialog
            # TODO: warn queued users their reports won't start
            # TODO: cancel report
            # TODO: save bug progress
            # TODO: resume report when restarting? inform user report was interrupted by restart, re-ask last question
        Logging.info("\tCancel active bug runners...", TCol.Warning)
        for task in [*self.bug_runner_tasks, *self.bug_tasks, self.ready_task]:
            if not task.cancelled() and not task.done():
                task.cancel(
                    BugReportCancelReason.Shutdown.value
                    if self.shutting_down else
                    BugReportCancelReason.Unload.value)
        try:
            Logging.info("\tWait for bug tasks to end...", TCol.Warning)
            await asyncio.gather(*self.bug_tasks, return_exceptions=True)
            Logging.info("\t\tDone waiting.", TCol.Green)
        except CancelledError:
            pass
        except Exception as e:
            await Utils.handle_exception("unexpected bug task exception", e)

        try:
            Logging.info("\tWait for bug runners to end...", TCol.Warning)
            await asyncio.gather(*self.bug_runner_tasks, return_exceptions=True)
            Logging.info("\t\tDone waiting.", TCol.Green)
        except CancelledError:
            Logging.info("\t\tRunners gatherer was canceled.", TCol.Fail)
            pass
        except Exception as e:
            await Utils.handle_exception("unexpected bug runner exception", e)

        try:
            Logging.info("\tWait for ready to end... it should have ended ages ago", TCol.Warning)
            await self.ready_task
            Logging.info("\t\tDone waiting.", TCol.Green)
        except CancelledError:
            Logging.info("\t\tReady task was canceled.", TCol.Fail)
            pass
        except Exception as e:
            await Utils.handle_exception("unexpected ready_task exception", e)

        Logging.info("\tVerify empty bug queue...", TCol.Warning)
        self.verify_empty_bug_queue.cancel()
        Logging.info("\tCancel bug cleanup tasks...", TCol.Warning)
        cancelling = set(self.in_progress.values())
        Logging.info(cancelling)
        i=1
        for task in cancelling:
            Logging.info(f"\tcanceling {i}...")
            Logging.info(f"\t\ttask {i} is already done? {task.done()}")
            Logging.info(f"\t\ttask {i} is canceled? {task.cancelled()}")
            if not task.done() and not task.cancelled():
                Logging.info(f"task {i} is not done or canceled")
                Logging.info(task)
                task.cancel()
            i += 1
        Logging.info("\tdone queuing cancels...", TCol.Warning)
        if cancelling:
            await asyncio.gather(*cancelling, return_exceptions=True)
        Logging.info("\tdone canceling tasks...", TCol.Warning)
        Logging.info(f"{self.qualified_name}::cog_unload complete", TCol.Bold, TCol.Warning)

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        m = self.bot.metrics
        m.reports_in_progress.set_function(lambda: len(self.in_progress))
        # this count is only good for reports waiting to start
        # TODO: how to count number of workers that are working?
        # m.reports_in_progress.set_function(self.bug_report_queue.qsize)
        self.ready_task = asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        for guild in self.bot.guilds:
            await self.clean_and_send_trigger_messages(guild)

    async def clean_and_send_trigger_messages(self, guild: discord.Guild):
        Logging.info("\tcleaning bug messages")
        reporting_channel_ids = set()
        guild_row = await self.bot.get_guild_db_config(guild.id)
        for row in await guild_row.bug_channels.filter().prefetch_related('platform'):
            channel = self.bot.get_channel(row.channelid)
            shutdown_key = f"{guild_row.serverid}_{row.platform.platform}_{row.platform.branch}_shutdown"
            shutdown_id = Configuration.get_persistent_var(shutdown_key)

            if shutdown_id is not None and channel is not None:
                try:
                    Configuration.del_persistent_var(shutdown_key, True)
                except KeyError:
                    pass
                else:
                    try:
                        message = channel.get_partial_message(shutdown_id)
                        await message.delete()
                    except (NotFound, HTTPException):
                        pass
            reporting_channel_ids.add(row.channelid)
        try:
            await self.send_bug_report_messages(*reporting_channel_ids)
        except Exception as e:
            await Utils.handle_exception("bug clean messages failure", e)

    def enqueue_bug_report(self, user: User, channel: TextChannel, interaction: Optional[Interaction] = None):
        work_item = BugReportingAction(user, channel, interaction)
        self.bug_report_queue.put_nowait(work_item)
        Logging.info(f"{work_item.uuid} report for {Utils.get_member_log_name(user)} "
                     f"queued to position {self.bug_report_queue.qsize()}")

    async def run_bug_report(self, work_item: BugReportingAction):
        try:
            Logging.info(f"{work_item.uuid} Beginning bug report for "
                         f"{TCol.Cyan.value}{get_member_log_name(work_item.user)}{TCol.End.value}")
            this_task = self.bot.loop.create_task(self.report_bug(work_item))
            self.bug_tasks.append(this_task)
            await this_task
        except CancelledError as e:
            Logging.info(f"\t{work_item.uuid} run_bug_report canceled. "
                         f"channel {work_item.channel.id}, user {get_member_log_name(work_item.user)}")
            raise e
        else:
            Logging.info(f"{work_item.uuid} runner completed without exceptions")

    async def sweep_trash(self, user, ctx):
        await asyncio.sleep(Configuration.get_var("bug_trash_sweep_minutes") * 60)
        if user.id in self.in_progress:
            if not self.in_progress[user.id].done() or not self.in_progress[user.id].cancelled():
                await user.send(Lang.get_locale_string("bugs/sweep_trash", ctx))
            await self.delete_progress(user.id, BugReportCancelReason.Sweep.value)

    async def delete_progress(self, uid, msg: str=''):
        my_task = self.in_progress.pop(uid, None)
        if my_task is not None:
            try:
                my_task.cancel(msg)
                Logging.info(f"delete_progress: bug report for {uid}")
            except Exception as e:
                # ignore task cancel failures
                Logging.info(f"can't cancel task because {repr(e)}")
                pass

        my_sweep = self.sweeps.pop(uid, None)
        if my_sweep is not None:
            my_sweep.cancel()

    async def shutdown(self):
        """Called before cog_unload, only when shutting down bot."""
        self.shutting_down = True
        Logging.info("Bugs shutdown", TCol.Underline, TCol.Header)
        reported = set()
        for row in await BugReportingChannel.all().prefetch_related('guild', 'platform'):
            cid = row.channelid
            platform: str = row.platform.platform
            branch: str = row.platform.branch
            guild_id = row.guild.serverid
            for i in range(3):
                try:
                    channel = self.bot.get_channel(cid)

                    if channel is not None:
                        if cid not in reported:
                            await self.remove_bug_info_msg(channel)
                            shutdown_message = await channel.send(Lang.get_locale_string("bugs/shutdown_message"))
                            Configuration.set_persistent_var(f"{guild_id}_{platform}_{branch}_shutdown", shutdown_message.id)
                            Logging.info(f"\tsent shutdown message in #{channel.name}")
                            reported.add(cid)
                    else:
                        Logging.info(f"\tcannot send shutdown message in nonexistent channel <#{cid}>")
                    break
                except Exception as e:
                    Logging.info(f"attempt {i+1} failed to sent shutdown message in #{cid}: {e}")
            else:
                msg = f"\tFailed sending shutdown message to <#{cid}> in server {guild_id} for {platform}_{branch}"
                Logging.info(msg, TCol.Fail)
                await Utils.guild_log(guild_id, msg)

    async def send_bug_report_messages(self, *args: int):
        send_tasks = []
        for channel_id in args:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                await Logging.bot_log(f"can't send bug info to nonexistent channel {channel_id}")
                continue
            send_tasks.append(self.send_bug_info_impl(channel))
        await asyncio.gather(*send_tasks)

    async def send_bug_info_impl(self, channel):
        ctx = None
        tries = 0
        max_tries = 5
        message = None
        last_message = None
        while not ctx and tries < max_tries:
            tries += 1
            try:
                last_message = await channel.send('preparing bug reporting...')
                ctx = await self.bot.get_context(last_message)
                await self.remove_bug_info_msg(channel)
                message = await channel.send(
                    Lang.get_locale_string(
                        "bugs/bug_info",
                        ctx,
                        bug_emoji=Emoji.get_emoji('BUG')))
                self.bug_messages.add(message.id)
                await message.add_reaction(Emoji.get_emoji('BUG'))
                Configuration.set_persistent_var(f"{channel.guild.id}_{channel.id}_bug_message", message.id)
            except Exception as e:
                await Utils.guild_log(
                    channel.guild.id,
                    f'failed {tries} {"time" if tries == 1 else "times"} to send bug message in {channel.mention}')
                if tries == max_tries:
                    await Utils.handle_exception(
                        f"Bug report message failed to send in channel #{channel.name} ({channel.id})", e)
                await asyncio.sleep(0.5)

        if last_message is not None:
            await last_message.delete()

        if message is not None:
            Logging.info(f"Bug report message sent in channel #{channel.name} ({channel.id})")

    async def remove_bug_info_msg(self, channel):
        """Get channel persistent var to find message id of existing info message, then delete message and var"""
        bug_info_id = Configuration.get_persistent_var(f"{channel.guild.id}_{channel.id}_bug_message")

        if bug_info_id is not None:
            try:
                info_message = channel.get_partial_message(bug_info_id)
            except (NotFound, HTTPException):
                pass
            else:
                if info_message.id in self.bug_messages:
                    self.bug_messages.remove(info_message.id)
                await info_message.delete()
            finally:
                Configuration.del_persistent_var(f"{channel.guild.id}_{channel.id}_bug_message")

    @tasks.loop(seconds=30.0)
    async def verify_empty_bug_queue(self, ctx):
        if len(self.in_progress) > 0:

            if self.maint_check_count == 20:
                await ctx.send(Lang.get_locale_string('bugs/maint_check_fail', ctx, author=ctx.author.mention))
                self.verify_empty_bug_queue.cancel()
                return

            msg = f"There are {len(self.in_progress)} report(s) still in progress."
            if self.maintenance_message is None:
                self.maintenance_message = await ctx.send(msg)
            else:
                self.maint_check_count += 1
                edited_message = await self.maintenance_message.edit(content=msg + (" ." * self.maint_check_count))
            return

        if self.maint_check_count > 0:
            await self.maintenance_message.delete()
            await ctx.send(Lang.get_locale_string('bugs/bugs_all_done', ctx, author=ctx.author.mention))
        else:
            await ctx.send(Lang.get_locale_string('bugs/none_in_progress', ctx))

        self.maintenance_message = None
        self.verify_empty_bug_queue.cancel()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        guild_row = await self.bot.get_guild_db_config(guild.id)
        await guild_row.bug_channels.filter().delete()

    ####################
    # app commands
    ####################

    config_group = Group(
        name='bug_config',
        description='Bug Reporting Configuration',
        guild_only=True,
        default_permissions=Permissions(ban_members=True))

    @app_commands.command()
    async def bug_report(self, interaction: Interaction) -> None:
        """Report a bug!"""
        self.enqueue_bug_report(interaction.user, interaction.channel, interaction)
        await interaction_response(interaction).send_message(
            f"ok {interaction.user.mention}, starting a bug report. check your DMs!",
            ephemeral=True)

    @config_group.command()
    async def clean_reporting_messages(self, interaction: Interaction) -> None:
        """Re-send bug channel prompt messages"""
        await interaction_response(interaction).send_message(
            "Re-send bug channel prompt messages",
            ephemeral=True)

    @config_group.command()
    async def list_platforms(self, interaction: Interaction) -> None:
        """List bug report platforms and branches"""
        await self.send_bug_platform_list(interaction)

    @config_group.command()
    async def manage_platforms(
            self,
            interaction: Interaction,
            operation:CommandMode.AddRemove,
            platform: str,
            branch: str) -> None:
        """
        Manage bug report platforms and branches

        Parameters
        ----------
        interaction
        operation
            Add or Remove a platform to bug reporting options
        platform
            The platform to add/remove, e.g. "Android"
        branch
            The branch to add/remove, e.g. "Stable"
        -------
        """
        if operation == CommandMode.Add:
            await self.do_add_platform(interaction, platform, branch)
        elif operation == CommandMode.Remove:
            await self.do_remove_platform(interaction, platform, branch)

    @config_group.command()
    async def list_bug_channels(self, interaction: Interaction):
        """List bug report channels"""
        await self.send_bug_channel_list(interaction)

    @config_group.command()
    async def manage_channels(
            self,
            interaction: Interaction,
            operation: CommandMode.AddRemove,
            channel: TextChannel,
            platform: Optional[str] = None,
            branch: Optional[str] = None):
        """
        Manage bug report channels

        Parameters
        ----------
        interaction
        operation
            Add or Remove a platform to bug reporting options
        channel
            The channel to add/remove
        platform
            The platform to add/remove, e.g. "Android"
        branch
            The branch to add/remove, e.g. "Stable"
        -------
        """
        if operation == CommandMode.Add:
            if not platform or not branch:
                raise UserInputError("platform and branch must be specified in `Add` mode")
            await self.do_add_channel(interaction, channel, platform, branch)
        elif operation == CommandMode.Remove:
            await self.do_remove_channel(interaction, channel, platform, branch)

    @manage_platforms.autocomplete('platform')
    @manage_channels.autocomplete('platform')
    async def platform_autocomplete(
            self,
            interaction: discord.Interaction,
            current: str) -> List[app_commands.Choice[str]]:
        platforms = await BugReportingPlatform.all()
        platform_set = set()

        for row in platforms:
            platform_set.add(row.platform)

        ret = [
            app_commands.Choice(name=p, value=p)
            for p in platform_set if current.lower() in p.lower()
        ]
        return ret

    @manage_platforms.autocomplete('branch')
    @manage_channels.autocomplete('branch')
    async def branch_autocomplete(
            self,
            interaction: discord.Interaction,
            current: str) -> List[app_commands.Choice[str]]:
        branches = await BugReportingPlatform.all()
        branch_set = set()

        for row in branches:
            branch_set.add(row.branch)

        ret = [
            app_commands.Choice(name=b, value=b)
            for b in branch_set if current.lower() in b.lower()
        ]
        return ret

    ####################
    # chat commands
    ####################

    @commands.group(name='bug', invoke_without_command=True)
    async def bug(self, ctx: Context) -> None:
        """Report a bug!"""
        # remove command trigger message (unless we are in a DM already)
        if ctx.guild is not None:
            await ctx.message.delete()
        self.enqueue_bug_report(ctx.author, ctx.channel)

    @bug.command()
    @commands.check(permission_official_ban)
    async def cleanup(self, ctx) -> None:
        """Attempt to re-send bug channel prompt messages"""
        await ctx.send("Attempting to re-send bug channel prompt messages...")
        await self.after_ready()
        await ctx.send("Done! ||I think?||")

    @bug.group(name='platforms', aliases=['platform'], invoke_without_command=True)
    @commands.check(permission_manage_bot)
    async def platforms(self, ctx) -> None:
        """List bug report platforms"""
        await self.send_bug_platform_list(ctx)

    @bug.group(name='channels', invoke_without_command=True)
    @commands.guild_only()
    @commands.check(permission_manage_bot)
    async def channels(self, ctx) -> None:
        """List bug report channels"""
        await self.send_bug_channel_list(ctx)

    @platforms.command(aliases=['add'])
    @commands.check(permission_manage_bot)
    async def add_platform(self, ctx, platform, branch) -> None:
        """
        Add a platform/branch pair to the bug reporting options

        Parameters
        ----------
        ctx
        platform
            The name of the platform, e.g. "Android"
        branch
            The development branch, e.g. "Beta"
        """
        await self.do_add_platform(ctx, platform, branch)

    @platforms.command(aliases=['remove'])
    @commands.check(permission_manage_bot)
    async def remove_platform(self, ctx, platform, branch) -> None:
        """
        Remove a platform/branch pair from the bug reporting options
        Parameters
        ----------
        ctx
        platform
            The name of the platform, e.g. "Android"
        branch
            The development branch, e.g. "Beta"
        """
        await self.do_remove_platform(ctx, platform, branch)

    @channels.command(aliases=['add'])
    @commands.guild_only()
    @commands.check(permission_manage_bot)
    async def add_channel(self, ctx, channel: TextChannel, platform, branch) -> None:
        """
        Add a bug report channel to the bug reporting config
        Parameters
        ----------
        ctx
        channel
            The channel in which to report bugs
        platform
            The name of the platform, e.g. "Android"
        branch
            The development branch, e.g. "Beta"
        -------
        """
        await self.do_add_channel(ctx, channel, platform, branch)

    @channels.command(aliases=['remove'])
    @commands.guild_only()
    @commands.check(permission_manage_bot)
    async def remove_channel(self, ctx, channel: TextChannel, platform: str = None, branch: str = None) -> None:
        """
        Remove a bug report channel from the bug reporting config
        Parameters
        ----------
        ctx
        channel
            The channel to remove from bug reporting
        platform
            The name of the platform, e.g. "Android"
        branch
            The development branch, e.g. "Beta"
        -------
        """
        await self.do_remove_channel(ctx, channel, platform, branch)

    @bug.command()
    @commands.guild_only()
    @commands.check(permission_manage_bot)
    async def reset_active(self, ctx) -> None:
        """Reset active bug reports. Bot will attempt to DM users whose reports are canceled."""
        to_kill = self.bug_report_queue.qsize()
        # to_kill = len(self.in_progress)
        active_keys = [key for key in self.in_progress.keys()]
        for uid in active_keys:
            try:
                await self.delete_progress(uid)
                user = self.bot.get_user(uid)
                await user.send(Lang.get_locale_string('bugs/user_reset',
                                                       Configuration.get_var('broadcast_locale', 'en_US')))
                await ctx.send(Lang.get_locale_string('bugs/reset_success', uid=uid))
            except Exception as e:
                await ctx.send(Lang.get_locale_string('bugs/reset_fail', uid=uid))
        self.in_progress = dict()
        await ctx.send(Lang.get_locale_string('bugs/dead_bugs_cleaned',
                                              ctx,
                                              active_keys=len(active_keys),
                                              in_progress=len(self.in_progress)))

    @commands.command(aliases=["maintenance", "maint"])
    @commands.guild_only()
    @commands.check(permission_official_ban)
    async def bug_maintenance(self, ctx: Context, active: bool):
        """
        Bot maintenance mode.

        Closes bug reporting channels and opens bug maintenance channel.
        Watches active bug reports for 10 minutes or so to give people a chance to finish reports in progress.
        """
        for guild in self.bot.guilds:
            default_role = guild.default_role
            # show/hide maintenance channel
            maint_message_channel = await Utils.get_guild_maintenance_channel(guild.id)
            if maint_message_channel is None:
                message = f'maintenance channel is not configured for `{guild.name}`'
                await Utils.guild_log(guild.id, message)
                await ctx.send(message)
                continue

            try:
                channel_overwrite = maint_message_channel.overwrites_for(default_role)
                channel_overwrite.update(view_channel=active)
                await maint_message_channel.set_permissions(default_role, overwrite=channel_overwrite)

                guild_config = await self.bot.get_guild_db_config(guild.id)
                beta_role = None
                if guild_config and guild_config.betarole:
                    beta_role = guild.get_role(guild_config.betarole)
                    beta_overwrite = maint_message_channel.overwrites[beta_role]
                    beta_overwrite.update(read_messages=active)
                    await maint_message_channel.set_permissions(beta_role, overwrite=beta_overwrite)
                else:
                    message = f'beta role is not configured for `{guild.name}`'
                    await Utils.guild_log(guild.id, message)
                    await ctx.send(message)

                for row in await guild_config.bug_channels.filter():
                    cid = row.channelid
                    branch = (await row.platform.filter()).branch

                    # show/hide reporting channels
                    channel = guild.get_channel(cid)

                    channel_overwrite = channel.overwrites_for(default_role)
                    channel_overwrite.update(read_messages=False if active else True)
                    await channel.set_permissions(default_role, overwrite=channel_overwrite)

                    if re.search(r'beta', branch, re.I) and beta_role:
                        if beta_role in channel.overwrites:
                            beta_overwrite = channel.overwrites[beta_role]
                            beta_overwrite.update(read_messages=False if active else True)
                            await channel.set_permissions(beta_role, overwrite=beta_overwrite)
                        else:
                            await ctx.send(f"Channel {channel.mention} does not have a permission overwrite "
                                           f"for the {beta_role.mention} Role", allowed_mentions=AllowedMentions.none())
            except Exception as e:
                await ctx.send(
                    Lang.get_locale_string(
                        'bugs/report_channel_permissions_fail',
                        ctx,
                        channel=maint_message_channel.mention,
                        server=guild.name))
                await Utils.handle_exception("failed to set bug report channel permissions", e)
            else:
                if active:
                    self.maint_check_count = 0
                    if not self.verify_empty_bug_queue.is_running():
                        self.maintenance_message = None
                        self.verify_empty_bug_queue.start(ctx)
                    await ctx.send(Lang.get_locale_string('bugs/maint_on', ctx))
                else:
                    await ctx.send(Lang.get_locale_string('bugs/maint_off', ctx))

    ####################
    # command internals
    ####################

    async def send_bug_platform_list(self, ctx: Union[Context, Interaction]):
        platforms = dict()

        for row in await BugReportingPlatform.all():
            if row.branch in platforms:
                if row.platform in platforms[row.branch]:
                    await Utils.guild_log(ctx.guild.id, f"duplicate platform in db: {row.platform}/{row.branch}")
            if row.branch not in platforms:
                platforms[row.branch] = list()
            platforms[row.branch].append(row.platform)

        embed = Embed(
            color=0x50f3d7,
            title='Bug Reporting Platforms')

        for branch, platforms in platforms.items():
            embed.add_field(name=branch, value='\n'.join(platforms), inline=False)

        sender = Sender(ctx)
        if not platforms:
            await sender.send("There are no bug reporting platforms in my database")
        else:
            await sender.send(embed=embed)

    async def send_bug_channel_list(self, ctx: Union[Context, Interaction]):
        embed = Embed(
            color=0x50f3d7,
            title='Bug Reporting Channels')
        guild_row = await self.bot.get_guild_db_config(ctx.guild.id)
        guild_channels = []
        non_guild_channels = dict()
        for row in await BugReportingPlatform.all().prefetch_related("bug_channels"):
            for channel_row in row.bug_channels:
                channel = self.bot.get_channel(channel_row.channelid)
                if not channel:
                    await channel_row.delete()
                    continue
                description = f"{row.platform}/{row.branch}: {channel.mention}"
                await channel_row.fetch_related('guild')
                channel_serverid = channel_row.guild.serverid
                if channel_row.guild == guild_row:
                    guild_channels.append(description)
                else:
                    if channel_serverid not in non_guild_channels:
                        non_guild_channels[channel_serverid] = []
                    non_guild_channels[channel_serverid].append(description)
        if guild_channels:
            embed.add_field(name=f'`{ctx.guild.name}` server', value="\n".join(guild_channels))
        for guild_id, channel_list in non_guild_channels.items():
            server_name = self.bot.get_guild(guild_id).name or f"[{guild_id}][MISSING GUILD]"
            embed.add_field(name=f'`{server_name}` server', value="\n".join(channel_list))

        sender = Sender(ctx)
        if not guild_channels and not non_guild_channels:
            await sender.send("There are no configured bug reporting channels")
        else:
            await sender.send(embed=embed)

    async def do_add_platform(self, ctx: Union[Context, Interaction], platform: str, branch: str) -> None:
        row, create = await BugReportingPlatform.get_or_create(platform=platform, branch=branch)
        sender = Sender(ctx)
        if create:
            await sender.send(f"Ok, I added `{platform}/{branch}` to my database")
        else:
            await sender.send(f"That platform/branch combination is already in my database")

    async def do_remove_platform(self, ctx, platform: str, branch: str):
        row = await BugReportingPlatform.get_or_none(platform=platform, branch=branch)

        # TODO: delete trigger messages. delete bugreportingchannel associated with platform that's being removed.

        sender = Sender(ctx)
        if row is None:
            await sender.send(f"That platform/branch is not in my database")
        else:
            try:
                await row.delete()
                await sender.send(f"Ok, I removed `{platform}/{branch}` from my database")
            except OperationalError:
                await sender.send(f"I couldn't delete `{platform}/{branch}` from my database. I really tried, I promise!")

    async def do_add_channel(self, ctx: Union[Context, Interaction], channel: TextChannel, platform: str, branch: str):
        sender = Sender(ctx)
        try:
            guild_row = await Guild.get(serverid=ctx.guild.id)
        except DoesNotExist:
            await sender.send(f"I couldn't find a record for guild id {ctx.guild.id}... call a plumber!")
            return

        try:
            platform_row = await BugReportingPlatform.get(platform=platform, branch=branch)
        except DoesNotExist:
            await sender.send(f"I couldn't find a record for platform/branch `{platform}`/`{branch}`")
            return

        try:
            record, created = await BugReportingChannel.get_or_create(
                guild=guild_row, platform=platform_row, channelid=channel.id)
        except DoesNotExist:
            # database constraint has prevented creation of a new record
            await sender.send(f"bugs for `{platform}`/`{branch}` are already reported in another channel. To report in a "
                           f"new channel, remove the old one first.")
            return
        except IntegrityError:
            # channel already in use for reporting
            await sender.send(f"channel {channel.mention} is already in use for bug reporting")
            return

        if created:
            await sender.send(f"{channel.mention} will now be used to record `{platform}/{branch}` bug reports")
        else:
            await sender.send(f"{channel.mention} was already configured for `{platform}/{branch}` bug reports")

        # resend reporting messages
        await self.remove_bug_info_msg(channel)
        await self.send_bug_report_messages(channel.id)

    async def do_remove_channel(self, ctx: Union[Context, Interaction], channel: TextChannel, platform: str, branch: str):
        """Remove a bug report channel from the bug reporting options"""
        sender = Sender(ctx)

        filter_args = dict(channelid=channel.id, guild__serverid=ctx.guild.id)
        if platform:
            filter_args["platform__platform"] = platform
        if branch:
            filter_args["platform__branch"] = branch

        try:
            rows = await BugReportingChannel.filter(**filter_args)
            if not rows:
                await sender.send("no matching bug report channel found")
                return
        except OperationalError:
            await sender.send(f"Could not find {channel.mention} in my database")
            return

        # delete matching rows and compile string of results
        msg = ''
        for row in rows:
            try:
                await row.fetch_related('platform')
                s_platform = row.platform.platform
                s_branch = row.platform.branch
                row_msg = f"\n**removed:** {s_platform}/{s_branch}:{channel.mention}"
                await row.delete()
            except OperationalError:
                row_msg = f"\n**failed to remove:** {channel.mention}\n```{repr(dict(row))}```"
            msg += row_msg
        await sender.send(msg)
        await self.remove_bug_info_msg(channel)
        await self.clean_and_send_trigger_messages(ctx.guild)


    async def report_bug(self, work_item: BugReportingAction):
        user = work_item.user
        trigger_channel = work_item.channel
        interaction = work_item.interaction
        # fully ignore muted users
        m = self.bot.metrics
        last_message = [message async for message in trigger_channel.history(limit=1)]
        last_message = last_message[0]
        ctx = await self.bot.get_context(last_message)
        await asyncio.sleep(1)

        # Get member from home guild. failing that, check other bot.guilds for member
        guild = Utils.get_home_guild()
        member = guild.get_member(user.id)

        # only members of official guild allowed, and must be verified
        if not member or len(member.roles) < 2:
            return

        guild_config = await self.bot.get_guild_db_config(guild.id)
        guild_mute_role = guild.get_role(guild_config.mutedrole)
        if member and guild_mute_role and (guild_mute_role in member.roles):
            # member is muted in at least one server. hard pass on letting them report
            return

        if user.id in self.in_progress:
            # already tracking progress for this user
            if user.id in self.blocking:
                # user blocked from starting a new report. waiting for DM response
                msg = Lang.get_locale_string("bugs/stop_spamming", ctx, user=user.mention)
                r = interaction_response(interaction)
                if interaction:
                    if not r.is_done():
                        await r.send_message(msg, ephemeral=True, delete_after=10)
                else:
                    await ctx.send(msg, delete_after=10)
                return

            should_reset = False

            async def start_over():
                nonlocal should_reset
                should_reset = True

            # block more clicks to the initial trigger
            self.blocking.add(user.id)

            try:
                # ask if user wants to start over
                await Questions.ask(self.bot, trigger_channel, user,
                                    Lang.get_locale_string("bugs/start_over", ctx, user=user.mention),
                                    [
                                        Questions.Option("YES", Lang.get_locale_string("bugs/start_over_yes", ctx),
                                                         handler=start_over),
                                        Questions.Option("NO", Lang.get_locale_string("bugs/start_over_no", ctx))
                                    ], delete_after=True, show_embed=True, locale=ctx)
            except asyncio.TimeoutError:
                Logging.info(f"{work_item.uuid} Bug report restart prompt timed out for {get_member_log_name(user)}")
                return

            # unblock so user can react again
            if user.id in self.blocking:
                self.blocking.remove(user.id)

            if not should_reset:
                # in-progress report should not be reset. bail out
                Logging.info(f"{work_item.uuid} Bug report NOT restarting for {get_member_log_name(user)}")
                return

            # cancel running task, delete progress, and continue to start a new report
            await self.delete_progress(user.id, BugReportCancelReason.User.value)

        # Start a bug report
        task = self.bot.loop.create_task(self.actual_bug_reporter(work_item))
        sweep = self.bot.loop.create_task(self.sweep_trash(user, ctx))
        self.in_progress[user.id] = task
        self.sweeps[user.id] = sweep
        try:
            await task
        except asyncio.TimeoutError:
            Logging.info(f"{work_item.uuid} Report timed out for {get_member_log_name(user)}")
            return
        except UserCanceledError:
            Logging.info(
                f"{work_item.uuid} user {get_member_log_name(work_item.user)} canceled own report in channel {work_item.channel.id}")
            raise CancelledError("User Canceled")
        except CancelledError as e:
            Logging.info(f"{work_item.uuid} In-progress report for {get_member_log_name(user)} was canceled")
            raise e
        else:
            # Delete references, cancel cleanup task, log success
            self.in_progress.pop(user.id, None)
            sweep.cancel()
            self.sweeps.pop(user.id, None)
            Logging.info(f"{work_item.uuid} Bug report completed for {get_member_log_name(user)}")

    async def actual_bug_reporter(self, work_item:BugReportingAction):
        Logging.info(f"{work_item.uuid} begin actual_bug_reporter")
        user = work_item.user
        trigger_channel = work_item.channel
        m = self.bot.metrics
        active_question = None
        restarting = False
        cancelling = False
        # wrap everything so users can't get stuck in limbo
        channel = await user.create_dm()
        last_message = [message async for message in trigger_channel.history(limit=1)]
        last_message = last_message[0]
        ctx = await self.bot.get_context(last_message)
        try:

            # vars to store everything
            asking = True
            platform = ""
            branch = ""
            app_build = None
            platform_version = ''
            app_version = ''
            deviceinfo = ''
            title = ''
            actual = ''
            steps = ''
            expected = ''
            additional = False
            additional_text = ""
            attachments = False
            attachment_links = []
            report = None

            # define all the parts we need as inner functions for easier sinfulness

            async def abort():
                nonlocal asking
                await user.send(Lang.get_locale_string("bugs/abort_report", ctx))
                asking = False
                m.reports_abort_count.inc()
                m.reports_exit_question.observe(active_question)
                await self.delete_progress(user.id)

            def set_platform(p):
                nonlocal platform
                platform = p

            def set_branch(b):
                nonlocal branch
                branch = b

            def add_additional():
                nonlocal additional
                additional = True

            def add_attachments():
                nonlocal attachments
                attachments = True

            def verify_version(v):
                if "latest" in v:
                    return Lang.get_locale_string("bugs/latest_not_allowed", ctx)
                # TODO: double check if we actually want to enforce this
                if len(NUMBER_MATCHER.findall(v)) == 0:
                    return Lang.get_locale_string("bugs/no_numbers", ctx)
                if len(v) > BugReportFieldLength.generic_version:
                    return Lang.get_locale_string("bugs/love_letter", ctx)
                return True

            def max_length(length):
                def real_check(text):
                    if len(text) > length:
                        return Lang.get_locale_string("bugs/text_too_long", ctx, max=length)
                    return True

                return real_check

            async def send_report():
                # save report in the database
                br = await BugReport.create(reporter=user.id, platform=platform, deviceinfo=deviceinfo,
                                            platform_version=platform_version, branch=branch, app_version=app_version,
                                            app_build=app_build, title=title, steps=steps, expected=expected,
                                            actual=actual, additional=additional_text,
                                            reported_at=int(utcnow().timestamp()))
                for url in attachment_links:
                    await Attachments.create(report=br, url=url)

                # send report
                channel_name = f"{platform}_{branch}".lower()

                report_id_saved = False
                attachment_id_saved = False
                user_reported_channels = list()
                all_reported_channels = list()
                selected_platform = await BugReportingPlatform.get(platform=platform, branch=branch)

                for row in await BugReportingChannel.filter(platform=selected_platform):
                    report_channel = self.bot.get_channel(row.channelid)
                    message = await report_channel.send(
                        content=Lang.get_locale_string("bugs/report_header", ctx, id=br.id, user=user.mention),
                        embed=report)
                    attachment = None
                    if len(attachment_links) != 0:
                        key = "attachment_info" if len(attachment_links) == 1 else "attachment_info_plural"
                        attachment = await report_channel.send(
                            Lang.get_locale_string(f"bugs/{key}", ctx, id=br.id, links="\n".join(attachment_links)))

                    if report_channel.guild.id == Configuration.get_var('guild_id'):
                        # Only save report and attachment IDs for posts in the official server
                        if not report_id_saved and not attachment_id_saved:
                            if attachment is not None:
                                br.attachment_message_id = attachment.id
                                attachment_id_saved = True
                            br.message_id = message.id
                            report_id_saved = True
                            await br.save()
                            user_reported_channels.append(report_channel.mention)
                    else:
                        # guild is not the official server. if author is member, include user_reported_channels
                        this_guild = self.bot.get_guild(report_channel.guild.id)
                        if this_guild.get_member(user.id) is not None:
                            user_reported_channels.append(report_channel.mention)

                    all_reported_channels.append(report_channel)

                channels_mentions = []
                channels_ids = set()
                if not all_reported_channels:
                    await Logging.bot_log(f"no report channels for bug report #{br.id}\nuuid[{work_item.uuid}]")

                for report_channel in all_reported_channels:
                    channels_mentions.append(report_channel.mention)
                    channels_ids.add(report_channel.id)
                await channel.send(
                    Lang.get_locale_string("bugs/report_confirmation", ctx, channel_info=', '.join(channels_mentions)))
                await self.send_bug_report_messages(*channels_ids)

            async def restart():
                Logging.info(f"{work_item.uuid} restarting")
                nonlocal restarting
                restarting = True
                m.reports_restarted.inc()

                # Kill this report, then create a new work_item
                await self.delete_progress(user.id)
                self.enqueue_bug_report(user, trigger_channel)

            # start global report timer and question timer
            report_start_time = question_start_time = time.time()
            m.reports_started.inc()

            def update_metrics():
                nonlocal active_question
                nonlocal question_start_time

                now = time.time()
                question_duration = now - question_start_time
                question_start_time = now

                # Record the time taken to answer the previous question
                gauge = getattr(m, f"reports_question_{active_question}_duration")
                gauge.set(question_duration)

                active_question = active_question + 1

            active_question = 0
            await Questions.ask(self.bot, channel, user, Lang.get_locale_string("bugs/question_ready", ctx),
                                [
                                    Questions.Option("YES", "Press this reaction to answer YES and begin a report"),
                                    Questions.Option("NO", "Press this reaction to answer NO", handler=abort),
                                ], show_embed=True, locale=ctx)
            update_metrics()

            if asking:
                # question 1: android or ios?
                platforms = set()
                for platform_row in await BugReportingPlatform.all():
                    platforms.add(platform_row.platform)

                if len(platforms) == 0:
                    platform = "NONE"
                elif len(platforms) == 1:
                    platform = platforms.pop()
                else:
                    options = []
                    for platform_name in platforms:
                        options.append(
                            Questions.Option(
                                platform_name.upper(),
                                platform_name,
                                set_platform,
                                [platform_name]))
                    await Questions.ask(self.bot, channel, user, Lang.get_locale_string("bugs/question_platform", ctx),
                                        options, show_embed=True, locale=ctx)
                update_metrics()

                try:
                    # question 2: android/ios version
                    platform_version = await Questions.ask_text(
                        self.bot, channel, user,
                        Lang.get_locale_string("bugs/question_platform_version",
                                               ctx,
                                               platform=platform),
                        validator=verify_version, locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                try:
                    # question 3: hardware info
                    device_info_platform = Lang.get_locale_string(f"bugs/device_info_{platform.lower()}", ctx)
                    deviceinfo = await Questions.ask_text(
                        self.bot, channel, user,
                        Lang.get_locale_string("bugs/question_device_info",
                                               ctx, platform=platform,
                                               device_info_help=device_info_platform,
                                               max=BugReportFieldLength.deviceinfo),
                        validator=max_length(BugReportFieldLength.deviceinfo), locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                # question 4: stable or beta?
                branches = set()
                for platform_row in await BugReportingPlatform.all():
                    # select branches that are available for the chosen platform
                    if platform_row.platform == platform:
                        branches.add(platform_row.branch)
                if len(branches) == 0:
                    branch = "NONE"
                elif len(branches) == 1:
                    branch = branches.pop()
                else:
                    options = []
                    for branch_name in branches:
                        branch_display_name = "Live" if branch_name.lower() == 'stable' else branch_name
                        options.append(
                            Questions.Option(
                                branch_name.upper(),
                                branch_display_name,
                                set_branch,
                                [branch_name]))
                    await Questions.ask(self.bot, channel, user, Lang.get_locale_string("bugs/question_app_branch", ctx),
                                        options, show_embed=True, locale=ctx)
                update_metrics()

                try:
                    # question 5: app version
                    app_version = await Questions.ask_text(
                        self.bot, channel, user,
                        Lang.get_locale_string(
                            "bugs/question_app_version", ctx,
                            version_help=Lang.get_locale_string(f"bugs/version_{platform.lower()}", ctx)),
                        validator=verify_version, locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                try:
                    # question 6: sky app build number
                    app_build = await Questions.ask_text(
                        self.bot, channel, user,
                        Lang.get_locale_string("bugs/question_app_build", ctx),
                        validator=verify_version, locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                try:
                    # question 7: Title
                    title = await Questions.ask_text(
                        self.bot, channel, user,
                        Lang.get_locale_string("bugs/question_title", ctx, max=BugReportFieldLength.title),
                        validator=max_length(BugReportFieldLength.title), locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                try:
                    # question 8: "actual" - defect behavior
                    actual = await Questions.ask_text(
                        self.bot, channel, user,
                        Lang.get_locale_string("bugs/question_actual", ctx, max=BugReportFieldLength.actual),
                        validator=max_length(BugReportFieldLength.actual), locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                try:
                    # question 9: steps to reproduce
                    steps = await Questions.ask_text(
                        self.bot,
                        channel,
                        user,
                        Lang.get_locale_string("bugs/question_steps",
                                               ctx, max=BugReportFieldLength.steps),
                        validator=max_length(BugReportFieldLength.steps),
                        locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                try:
                    # question 10: expected behavior
                    expected = await Questions.ask_text(
                        self.bot, channel, user,
                        Lang.get_locale_string("bugs/question_expected", ctx, max=BugReportFieldLength.expected),
                        validator=max_length(BugReportFieldLength.expected), locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                try:
                    # question 11: attachments y/n
                    attachment_prompt = Lang.get_locale_string("bugs/question_attachments", ctx)
                    try:
                        platform_attachment_prompt = Lang.get_locale_string(
                            f"bugs/question_attachments_{platform.lower()}", ctx)
                        attachment_prompt += f"\n{platform_attachment_prompt}"
                    except KeyError:
                        pass
                    await Questions.ask(
                        self.bot, channel, user, attachment_prompt,
                        [
                            Questions.Option("YES",
                                             Lang.get_locale_string("bugs/attachments_yes", ctx),
                                             handler=add_attachments),
                            Questions.Option("NO", Lang.get_locale_string("bugs/skip_step", ctx))
                        ], show_embed=True, timeout=300, locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                if attachments:
                    # question 12: attachments
                    attachment_links = await Questions.ask_attachements(
                        self.bot, channel, user, timeout=300, locale=ctx)
                    attachment_links = set(attachment_links)
                # update metrics outside condition to keep count up-to-date and reflect skipped question as zero time
                update_metrics()

                try:
                    # question 13: additional info y/n
                    await Questions.ask(
                        self.bot, channel, user, Lang.get_locale_string("bugs/question_additional", ctx),
                        [
                            Questions.Option("YES",
                                             Lang.get_locale_string("bugs/additional_info_yes", ctx),
                                             handler=add_additional),
                            Questions.Option("NO", Lang.get_locale_string("bugs/skip_step", ctx))
                        ], show_embed=True, locale=ctx)
                    update_metrics()
                except KeyError:
                    # Expected when a question is not defined
                    pass

                if additional:
                    # question 14: additional info
                    additional_text = await Questions.ask_text(
                        self.bot, channel, user,
                        Lang.get_locale_string("bugs/question_additional_info", ctx),
                        validator=max_length(BugReportFieldLength.additional), locale=ctx)
                # update metrics outside condition to keep count up-to-date and reflect skipped question as zero time
                update_metrics()

                # assemble the report and show to user for review
                report = Embed(timestamp=datetime.now().astimezone(timezone.utc))
                avatar = user.avatar.replace(size=32).url if user.avatar else None
                report.set_author(name=f"{user} ({user.id})", icon_url=avatar)
                fields = [
                    {'name': "bugs/platform", 'value': f"{platform} {platform_version}", 'inline': True},
                    {'name': "bugs/app_version", 'value': app_version, 'inline': True},
                    {'name': "bugs/app_build", 'value': app_build, 'inline': True},
                    {'name': "bugs/device_info", 'value': deviceinfo, 'inline': False},
                    {'name': "bugs/title", 'value': title, 'inline': False},
                    {'name': "bugs/description", 'value': actual, 'inline': False},
                    {'name': "bugs/steps_to_reproduce", 'value': steps, 'inline': False},
                    {'name': "bugs/expected", 'value': expected, 'inline': True},
                ]

                for item in fields:
                    try:
                        report.add_field(
                            name=Lang.get_locale_string(item['name'], ctx),
                            value=item['value'],
                            inline=item['inline'])
                    except KeyError:
                        # Expected when a field title is not defined in Lang.yaml
                        pass

                if additional:
                    report.add_field(
                        name=Lang.get_locale_string("bugs/additional_info", ctx), value=additional_text, inline=False)

                await channel.send(
                    content=Lang.get_locale_string("bugs/report_header", ctx, id="##", user=user.mention), embed=report)
                if attachment_links:
                    attachment_message = ''
                    for a in attachment_links:
                        attachment_message += f"{a}\n"
                    await channel.send(attachment_message)

                review_time = 300
                await asyncio.sleep(1)

                # Question 15 - final review
                await Questions.ask(
                    self.bot, channel, user,
                    Lang.get_locale_string("bugs/question_ok", ctx, timeout=Questions.timeout_format(review_time)),
                    [
                        Questions.Option("YES", Lang.get_locale_string("bugs/send_report", ctx), send_report),
                        Questions.Option("NO", Lang.get_locale_string("bugs/mistake", ctx), restart)
                    ], show_embed=True, timeout=review_time, locale=ctx)
                Logging.info(f"{work_item.uuid} is {'not' if not restarting else ''} restarting...")
                update_metrics()
                report_duration = time.time() - report_start_time
                m.reports_duration.set(report_duration)
            else:
                return

        except Forbidden:
            m.bot_cannot_dm_member.inc()
            await trigger_channel.send(
                Lang.get_locale_string("bugs/dm_unable", ctx, user=user.mention),
                delete_after=30)
        except asyncio.TimeoutError:
            m.report_incomplete_count.inc()
            await channel.send(Lang.get_locale_string("bugs/report_timeout", ctx))
            if active_question is not None:
                m.reports_exit_question.observe(active_question)
        except CancelledError as ex:
            Logging.info(f"--- {work_item.uuid} is {'not' if not restarting else ''} restarting...")
            Logging.info(f"{work_item.uuid} Cancel actual bug reporter. user {get_member_log_name(user)}")
            if str(ex) == BugReportCancelReason.Unload.value:
                await channel.send(f"**I dropped my memory modules and have to clean up this mess. "
                                   f"Please try your report again.**")
            elif str(ex) == BugReportCancelReason.Shutdown.value:
                await channel.send(f"**My microprocessor overheated and might need a minute to cool down. "
                                   f"Please try your report again.**")
            elif str(ex) == BugReportCancelReason.User.value:
                await channel.send(f"**You canceled your previous report. Starting a new one.**")
            elif str(ex) == BugReportCancelReason.Sweep.value:
                minutes = Configuration.get_var("bug_trash_sweep_minutes")
                await channel.send(f"**Your report took too long. "
                                   f"Once you start a report, you have {minutes} minutes to finish, "
                                   f"so collect everything you need in advance!**")
            else:
                await channel.send(f"**The bot ran into unexpected trouble and your report got broken. Please try again.**")
            m.report_incomplete_count.inc()
            if active_question is not None:
                Logging.info(f"\t{work_item.uuid} bug report for {get_member_log_name(user)} canceled on question {active_question}")
                m.reports_exit_question.observe(active_question)
            if not restarting:
                Logging.info(f"\t{work_item.uuid} actual_bug_reporter not restarting. raising {repr(ex)}")
                cancelling = True
        except Exception as ex:
            await Utils.handle_exception("bug reporting", ex)
            raise ex
        # else:
        #     await self.delete_progress(user.id)

        if cancelling:
            Logging.info(f"\t{work_item.uuid} actual_bug_reporter canceled progress, raising CanceledError")
            raise UserCanceledError("stopping bug report")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        if event.message_id in self.bug_messages and event.user_id != self.bot.user.id:
            user = self.bot.get_user(event.user_id)
            channel = self.bot.get_channel(event.channel_id)
            try:
                message = channel.get_partial_message(event.message_id)
                await message.remove_reaction(event.emoji, user)
            except (NotFound, HTTPException) as e:
                await Utils.guild_log(
                    channel.guild.id,
                    f"Failed to clear bug report reaction in {channel.mention} "
                    f"for message id {event.message_id}. Is the bug reporting message missing?")
                try:
                    await channel.send(
                        f"Sorry {user.mention}, I got a crab stuck in my gears."
                        "If your bug report doesn't start, ask a mod for help.",
                        delete_after=10
                    )
                except Exception as e:
                    await Utils.handle_exception("bug invocation failure", e)
            self.enqueue_bug_report(user, channel)


async def setup(bot):
    await bot.add_cog(Bugs(bot))

async def teardown(bot):
    Logging.info("Bugs teardown", TCol.Underline, TCol.Header)
