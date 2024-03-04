import asyncio
import re
import time
from dataclasses import dataclass

import discord

from utils.Utils import get_member_log_name
from sky import queue_worker
from asyncio import CancelledError
from datetime import datetime

from discord import Forbidden, Embed, NotFound, HTTPException, TextChannel, AllowedMentions
from discord.ext import commands, tasks
from discord.ext.commands import Context
from discord.utils import utcnow
from tortoise.exceptions import DoesNotExist, OperationalError, IntegrityError

import sky
from cogs.BaseCog import BaseCog
from utils import Questions, Emoji, Utils, Configuration, Lang, Logging
from utils.Database import BugReport, Attachments, BugReportingPlatform, BugReportingChannel
from utils.Database import Guild, BugReportFieldLength
from utils.Logging import TCol


@dataclass()
class BugReportingAction:
    author: discord.User
    channel: discord.TextChannel


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

        Logging.info(f"\t{TCol.cWarning}starting {self.task_limit} bug tasks{TCol.cEnd}")
        self.bug_runner_tasks = [
            asyncio.create_task(
                queue_worker(f"Bug Queue {i}", self.bug_report_queue, self.run_bug_report))
            for i in range(self.task_limit)
        ]

    async def cog_unload(self):
        if self.bug_report_queue.qsize() > 0:
            Logging.info(f"\tthere are {self.bug_report_queue.qsize()} bug reports not yet started...")
            # TODO: warn queued users their reports won't start
            # TODO: cancel report
            # TODO: save bug progress
            # TODO: resume report when restarting? inform user report was interrupted by restart, re-ask last question
        Logging.info(f"\t{TCol.cWarning}Cancel active bug runners...{TCol.cEnd}")
        for task in [*self.bug_runner_tasks, *self.bug_tasks, self.ready_task]:
            task.cancel()
        try:
            Logging.info(f"\t{TCol.cWarning}Wait for bug tasks to end...{TCol.cEnd}")
            await asyncio.gather(*self.bug_tasks)
            Logging.info(f"\t{TCol.cWarning}Wait for bug runners to end...{TCol.cEnd}")
            await asyncio.gather(*self.bug_runner_tasks)
        except CancelledError:
            pass
        except Exception as e:
            Logging.info(e)
        Logging.info(f"\t{TCol.cWarning}Verify empty bug queue...{TCol.cEnd}")
        self.verify_empty_bug_queue.cancel()
        Logging.info(f"\t{TCol.cWarning}Cancel bug cleanup tasks...{TCol.cEnd}")
        for task in self.sweeps:
            task.cancel()
        await asyncio.gather(*self.sweeps)
        Logging.info(f"\t{TCol.cOkGreen}Bugs unloaded{TCol.cEnd}")

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
        await self.clean_and_send_trigger_messages()

    async def clean_and_send_trigger_messages(self):
        Logging.info("\tcleaning bug messages")
        reporting_channel_ids = []
        for row in await BugReportingChannel.all().prefetch_related('guild', 'platform'):
            cid = row.channelid
            name = f"{row.platform.platform}_{row.platform.branch}"
            guild_id = row.guild.serverid
            channel = self.bot.get_channel(cid)
            shutdown_key = f"{guild_id}_{name}_shutdown"
            shutdown_id = Configuration.get_persistent_var(shutdown_key)

            if shutdown_id is not None and channel is not None:
                Configuration.del_persistent_var(shutdown_key)
                try:
                    message = channel.get_partial_message(shutdown_id)
                    await message.delete()
                except (NotFound, HTTPException):
                    pass
            reporting_channel_ids.append(cid)
        try:
            await self.send_bug_info(*reporting_channel_ids)
        except Exception as e:
            await Utils.handle_exception("bug clean messages failure", self.bot, e)

    async def can_mod(ctx):
        guild = Utils.get_home_guild()
        member = guild.get_member(ctx.author.id)
        return member.guild_permissions.mute_members or await Utils.BOT.permission_manage_bot(ctx)

    def enqueue_bug_report(self, user, channel):
        self.bug_report_queue.put_nowait(BugReportingAction(user, channel))

    async def run_bug_report(self, work_item: BugReportingAction):
        try:
            Logging.info(f"Beginning bug report for {TCol.cOkCyan}{get_member_log_name(work_item.author)}{TCol.cEnd}")
            this_task = self.bot.loop.create_task(self.report_bug(work_item.author, work_item.channel))
            self.bug_tasks.append(this_task)
            await this_task
        except CancelledError as e:
            # TODO: why is CancelledError not caught here during shutdown?
            Logging.info(f"channel {work_item.channel.id}, user {get_member_log_name(work_item.author)}")
            raise e
        except Exception as e:
            Logging.info(e)
            raise e

    async def sweep_trash(self, user, ctx):
        await asyncio.sleep(Configuration.get_var("bug_trash_sweep_minutes") * 60)
        if user.id in self.in_progress:
            if not self.in_progress[user.id].done() or not self.in_progress[user.id].canceled():
                await user.send(Lang.get_locale_string("bugs/sweep_trash", ctx))
            await self.delete_progress(user.id)

    async def delete_progress(self, uid):
        if uid in self.in_progress:
            try:
                self.in_progress[uid].cancel()
            except Exception as e:
                # ignore task cancel failures
                pass
            del self.in_progress[uid]
        if uid in self.sweeps:
            self.sweeps[uid].cancel()

    async def shutdown(self):
        for row in await BugReportingChannel.all().prefetch_related('guild', 'platform'):
            cid = 0
            guild_id = 0
            name = "none"
            try:
                cid = row.channelid
                platform = row.platform
                name = f"{platform.platform}_{platform.branch}"
                guild_id = row.guild.serverid
                channel = self.bot.get_channel(cid)

                if channel is not None:
                    message = await channel.send(Lang.get_locale_string("bugs/shutdown_message"))
                    Configuration.set_persistent_var(f"{guild_id}_{name}_shutdown", message.id)
                else:
                    Logging.info(f"Bugs cog can't send to nonexistent channel {cid}")
            except Exception as e:
                message = f"Failed sending shutdown message <#{cid}> in server {guild_id} for {name}"
                await self.bot.guild_log(guild_id, message)
                await Utils.handle_exception(message, self.bot, e)

    async def send_bug_info(self, *args):
        send_tasks = []
        for channel_id in args:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                await Logging.bot_log(f"can't send bug info to nonexistent channel {channel_id}")
                continue
            send_tasks.append(self.send_bug_info_impl(channel))
        await asyncio.gather(*send_tasks)

    async def send_bug_info_impl(self, channel):
        bug_info_id = Configuration.get_persistent_var(f"{channel.guild.id}_{channel.id}_bug_message")

        ctx = None
        tries = 0
        while not ctx and tries < 5:
            tries += 1
            try:
                last_message = await channel.send('preparing bug reporting...')
                ctx = await self.bot.get_context(last_message)

                if bug_info_id is not None:
                    try:
                        info_message = channel.get_partial_message(bug_info_id)
                    except (NotFound, HTTPException):
                        pass
                    else:
                        if info_message.id in self.bug_messages:
                            self.bug_messages.remove(info_message.id)
                        await info_message.delete()

                bug_emoji = Emoji.get_emoji('BUG')
                message = await channel.send(Lang.get_locale_string("bugs/bug_info", ctx, bug_emoji=bug_emoji))
                self.bug_messages.add(message.id)
                await message.add_reaction(bug_emoji)
                Configuration.set_persistent_var(f"{channel.guild.id}_{channel.id}_bug_message", message.id)
                Logging.info(f"Bug report message sent in channel #{channel.name} ({channel.id})")
                await last_message.delete()
            except Exception as e:
                await self.bot.guild_log(channel.guild.id, f'Having trouble sending bug message in {channel.mention}')
                await Utils.handle_exception(
                    f"Bug report message failed to send in channel #{channel.name} ({channel.id})", self.bot, e)
                await asyncio.sleep(0.5)

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

    @commands.command(aliases=["bugmaint", "maintenance", "maintenance_mode", "maint"])
    @commands.guild_only()
    @commands.check(can_mod)
    async def bug_maintenance(self, ctx, active: bool):
        """
        Bot maintenance mode.

        Closes bug reporting channels and opens bug maintenance channel.
        Watches active bug reports for 10 minutes or so to give people a chance to finish reports in progress.
        """
        for guild in self.bot.guilds:
            try:
                default_role = guild.default_role
                # show/hide maintenance channel
                maint_message_channel = await self.bot.get_guild_maintenance_channel(guild.id)
                if maint_message_channel is None:
                    message = f'maintenance channel is not configured for `{guild.name}`'
                    await self.bot.guild_log(guild.id, message)
                    await ctx.send(message)
                    continue

                channel_overwrite = maint_message_channel.overwrites_for(default_role)
                channel_overwrite.view_channel = active
                await maint_message_channel.set_permissions(default_role, overwrite=channel_overwrite)

                guild_config = await self.bot.get_guild_db_config(guild.id)
                beta_role = None
                if guild_config and guild_config.betarole:
                    beta_role = guild.get_role(guild_config.betarole)
                    beta_overwrite = maint_message_channel.overwrites[beta_role]
                    beta_overwrite.read_messages = active
                    await maint_message_channel.set_permissions(beta_role, overwrite=beta_overwrite)
                else:
                    message = f'beta role is not configured for `{guild.name}`'
                    await self.bot.guild_log(guild.id, message)
                    await ctx.send(message)

                for row in await guild_config.bug_channels.filter():
                    cid = row.channelid
                    branch = (await row.platform.filter()).branch

                    # show/hide reporting channels
                    channel = guild.get_channel(cid)

                    channel_overwrite = channel.overwrites_for(default_role)
                    channel_overwrite.read_messages = False if active else True
                    await channel.set_permissions(default_role, overwrite=channel_overwrite)

                    if re.search(r'beta', branch, re.I) and beta_role:
                        if beta_role in channel.overwrites:
                            beta_overwrite = channel.overwrites[beta_role]
                        else:
                            await ctx.send(f"Channel {channel.mention} does not have a permission overwrite "
                                           f"for the {beta_role.mention} Role", allowed_mentions=AllowedMentions.none())
                        beta_overwrite.read_messages = False if active else True
                        await channel.set_permissions(beta_role, overwrite=beta_overwrite)
            except Exception as e:
                await ctx.send(
                    Lang.get_locale_string(
                        'bugs/report_channel_permissions_fail',
                        ctx,
                        channel=maint_message_channel.mention,
                        server=guild.name))
                await Utils.handle_exception("failed to set bug report channel permissions", self.bot, e)
            else:
                if active:
                    self.maint_check_count = 0
                    if not self.verify_empty_bug_queue.is_running():
                        self.maintenance_message = None
                        self.verify_empty_bug_queue.start(ctx)
                    await ctx.send(Lang.get_locale_string('bugs/maint_on', ctx))
                else:
                    await ctx.send(Lang.get_locale_string('bugs/maint_off', ctx))

    @commands.group(name='bug', invoke_without_command=True)
    async def bug(self, ctx: Context):
        """Report a bug!"""
        # remove command to not flood chat (unless we are in a DM already)
        if ctx.guild is not None:
            await ctx.message.delete()
        self.enqueue_bug_report(ctx.author, ctx.channel)

    @bug.command()
    @commands.check(can_mod)
    async def cleanup(self, ctx):
        await ctx.send("Attempting to re-send bug channel prompt messages...")
        await self.after_ready()
        await ctx.send("Done! ||I think?||")

    @bug.group(name='platforms', aliases=['platform'], invoke_without_command=True)
    @commands.check(sky.can_admin)
    async def platforms(self, ctx):
        platforms = dict()

        for row in await BugReportingPlatform.all():
            if row.branch in platforms:
                if row.platform in platforms[row.branch]:
                    await self.bot.guild_log(ctx.guild.id, f"duplicate platform in db: {row.platform}/{row.branch}")
            if row.branch not in platforms:
                platforms[row.branch] = list()
            platforms[row.branch].append(row.platform)

        embed = Embed(
            timestamp=ctx.message.created_at,
            color=0x50f3d7,
            title='Bug Reporting Platforms')

        for branch, platforms in platforms.items():
            embed.add_field(name=branch, value='\n'.join(platforms), inline=False)

        if not platforms:
            await ctx.send("There are no bug reporting platforms in my database")
        else:
            await ctx.send(embed=embed)

    @platforms.command(aliases=['add'])
    @commands.check(sky.can_admin)
    async def add_platform(self, ctx, platform, branch):
        row, create = await BugReportingPlatform.get_or_create(platform=platform, branch=branch)
        if create:
            await ctx.send(f"Ok, I added `{platform}/{branch}` to my database")
        else:
            await ctx.send(f"That platform/branch combination is already in my database")

    @platforms.command(aliases=['remove'])
    @commands.check(sky.can_admin)
    async def remove_platform(self, ctx, platform, branch):
        row = await BugReportingPlatform.get_or_none(platform=platform, branch=branch)
        if row is None:
            await ctx.send(f"That platform/branch is not in my database")
        else:
            try:
                await row.delete()
                await ctx.send(f"Ok, I removed `{platform}/{branch}` from my database")
            except OperationalError:
                await ctx.send(f"I couldn't delete `{platform}/{branch}` from my database. I really tried, I promise!")

    @bug.group(name='channels', aliases=['channel'], invoke_without_command=True)
    @commands.guild_only()
    @commands.check(sky.can_admin)
    async def channels(self, ctx):
        # TODO: allow guild admins to use this, restricted to single guild
        embed = Embed(
            timestamp=ctx.message.created_at,
            color=0x50f3d7,
            title='Bug Reporting Channels')
        guild_row = await Guild.get_or_none(serverid=ctx.guild.id)
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
                    # TODO: get guild names and add to description
                    if channel_serverid not in non_guild_channels:
                        non_guild_channels[channel_serverid] = []
                    non_guild_channels[channel_serverid].append(description)
        if guild_channels:
            embed.add_field(name=f'`{ctx.guild.name}` server', value="\n".join(guild_channels))
        for guild_id, channel_list in non_guild_channels.items():
            server_name = self.bot.get_guild(guild_id).name or f"[{guild_id}][MISSING GUILD]"
            embed.add_field(name=f'`{server_name}` server', value="\n".join(channel_list))
        if not guild_channels and not non_guild_channels:
            await ctx.send("There are no configured bug reporting channels")
        else:
            await ctx.send(embed=embed)

    @channels.command(aliases=['remove'])
    @commands.guild_only()
    @commands.check(sky.can_admin)
    async def remove_channel(self, ctx, channel: TextChannel):
        try:
            row = await BugReportingChannel.get(channelid=channel.id)
            await row.fetch_related('platform')
            platform = row.platform.platform
            branch = row.platform.branch
            await row.delete()
            await ctx.send(f"Removed `{platform}`/`{branch}`/{channel.mention} from my database")
        except OperationalError:
            await ctx.send(f"Could not find {channel.mention} in my database")

    @channels.command(aliases=['add'])
    @commands.guild_only()
    @commands.check(sky.can_admin)
    async def add_channel(self, ctx, channel: TextChannel, platform, branch):
        try:
            guild_row = await Guild.get(serverid=ctx.guild.id)
        except DoesNotExist:
            await ctx.send(f"I couldn't find a record for guild id {ctx.guild.id}... call a plumber!")
            return

        try:
            platform_row = await BugReportingPlatform.get(platform=platform, branch=branch)
        except DoesNotExist:
            await ctx.send(f"I couldn't find a record for platform/branch `{platform}`/`{branch}`")
            return

        try:
            record, created = await BugReportingChannel.get_or_create(
                guild=guild_row, platform=platform_row, channelid=channel.id)
        except DoesNotExist:
            # database constraint has prevented creation of a new record
            await ctx.send(f"bugs for `{platform}`/`{branch}` are already reported in another channel. To report in a "
                           f"new channel, remove the old one first.")
            return
        except IntegrityError:
            # channel already in use for reporting
            await ctx.send(f"channel {channel.mention} is already in use for bug reporting")
            return

        if created:
            await ctx.send(f"{channel.mention} will now be used to record `{platform}/{branch}` bug reports")
        else:
            await ctx.send(f"{channel.mention} was already configured for `{platform}/{branch}` bug reports")

    @bug.command(aliases=["resetactive", "reset_in_progress", "resetinprogress", "reset", "clean"])
    @commands.guild_only()
    @commands.check(sky.can_admin)
    async def reset_active(self, ctx):
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

    async def report_bug(self, user, trigger_channel):
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
                await ctx.send(Lang.get_locale_string("bugs/stop_spamming", ctx, user=user.mention), delete_after=10)
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
                Logging.info(f"Bug report restart prompt timed out for {get_member_log_name(user)}")
                return

            # not starting over. remove blocking
            if user.id in self.blocking:
                self.blocking.remove(user.id)

            # cancel running task, delete progress, and fall through to start a new report
            await self.delete_progress(user.id)
            if not should_reset:
                # in-progress report should not be reset. bail out
                return

        # Start a bug report
        task = self.bot.loop.create_task(self.actual_bug_reporter(user, trigger_channel))
        sweep = self.bot.loop.create_task(self.sweep_trash(user, ctx))
        self.in_progress[user.id] = task
        self.sweeps[user.id] = sweep
        try:
            await task
        except asyncio.TimeoutError:
            Logging.info(f"Report timed out for {get_member_log_name(user)}")
            return
        except CancelledError as e:
            Logging.info(f"Cancelling in-progress report for {get_member_log_name(user)}")
            raise e

    async def actual_bug_reporter(self, user, trigger_channel):
        # wrap everything so users can't get stuck in limbo
        m = self.bot.metrics
        active_question = None
        restarting = False
        try:
            channel = await user.create_dm()
            last_message = [message async for message in trigger_channel.history(limit=1)]
            last_message = last_message[0]
            ctx = await self.bot.get_context(last_message)

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
                if len(Utils.NUMBER_MATCHER.findall(v)) == 0:
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
                    await Logging.bot_log(f"no report channels for bug report #{br.id}")

                for report_channel in all_reported_channels:
                    channels_mentions.append(report_channel.mention)
                    channels_ids.add(report_channel.id)
                await channel.send(
                    Lang.get_locale_string("bugs/report_confirmation", ctx, channel_info=', '.join(channels_mentions)))
                await self.send_bug_info(*channels_ids)

            async def restart():
                nonlocal restarting
                restarting = True
                m.reports_restarted.inc()
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
                report = Embed(timestamp=datetime.utcfromtimestamp(time.time()))
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
            Logging.info(f"Cancel actual bug reporter. user {get_member_log_name(user)}")
            await channel.send(f"The bot ran into unexpected trouble and your report got broken. Please try again.")
            m.report_incomplete_count.inc()
            if active_question is not None:
                m.reports_exit_question.observe(active_question)
            if not restarting:
                raise ex
        except Exception as ex:
            await Utils.handle_exception("bug reporting", self.bot, ex)
            raise ex
        finally:
            await self.delete_progress(user.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        if event.message_id in self.bug_messages and event.user_id != self.bot.user.id:
            user = self.bot.get_user(event.user_id)
            channel = self.bot.get_channel(event.channel_id)
            try:
                message = channel.get_partial_message(event.message_id)
                await message.remove_reaction(event.emoji, user)
            except (NotFound, HTTPException) as e:
                await self.bot.guild_log(
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
                    await Utils.handle_exception("bug invocation failure", self.bot, e)
            self.enqueue_bug_report(user, channel)


async def setup(bot):
    await bot.add_cog(Bugs(bot))
