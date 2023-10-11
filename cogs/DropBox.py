import asyncio
import io
from asyncio import CancelledError

import aiohttp
import discord
import tortoise.exceptions
from discord import Forbidden, Embed, NotFound, HTTPException
from discord.ext import commands, tasks
from discord.utils import utcnow
from tortoise.exceptions import DoesNotExist

import utils.Logging
from utils.Logging import TCol
from cogs.BaseCog import BaseCog
from utils import Lang, Questions, Utils, Logging
from utils.Database import DropboxChannel


class DropBox(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.dropboxes = dict()
        self.responses = dict()
        self.drop_messages = dict()
        self.delivery_in_progress = dict()
        self.delete_in_progress = dict()
        self.clean_in_progress = False

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")

        for guild in self.bot.guilds:
            # fetch dropbox channels per server
            await self.init_guild(guild.id)
            for row in await DropboxChannel.filter(serverid=guild.id):
                self.dropboxes[guild.id][row.sourcechannelid] = row

        # TODO: replace with asyncio queue?
        if not self.deliver_to_channel.is_running():
            self.deliver_to_channel.start()
        if not self.clean_channels.is_running():
            self.clean_channels.start()

    async def init_guild(self, guild_id):
        self.dropboxes[guild_id] = dict()
        self.drop_messages[guild_id] = dict()
        self.delivery_in_progress[guild_id] = dict()
        self.delete_in_progress[guild_id] = dict()

    def cog_unload(self):
        self.deliver_to_channel.cancel()
        self.clean_channels.cancel()

    async def cog_check(self, ctx):
        return ctx.guild is not None \
            and (ctx.author.guild_permissions.ban_members or await self.bot.permission_manage_bot(ctx))

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.dropboxes[guild.id]
        del self.drop_messages[guild.id]
        del self.delivery_in_progress[guild.id]
        del self.delete_in_progress[guild.id]
        await DropboxChannel.filter(serverid=guild.id).delete()

    # TODO: replace with asyncio queue?
    @tasks.loop(seconds=10.0)
    async def deliver_to_channel(self):
        send_tasks = []
        for guild_id, guild_queue in self.drop_messages.items():
            for channel_id, message_queue in guild_queue.items():
                try:
                    # get dropbox channel
                    drop_channel = self.bot.get_channel(self.dropboxes[guild_id][channel_id].targetchannelid)
                    working_queue = dict(message_queue)
                    for message_id, message in working_queue.items():
                        if channel_id not in self.delivery_in_progress[guild_id]:
                            self.delivery_in_progress[guild_id][channel_id] = set()
                        if message_id not in self.delivery_in_progress[guild_id][channel_id]:
                            self.delivery_in_progress[guild_id][channel_id].add(message_id)
                            send_tasks.append(self.bot.loop.create_task(self.drop_message_impl(message, drop_channel)))
                except Exception as e:
                    pass
        try:
            if send_tasks:
                await asyncio.gather(*send_tasks)
        except CancelledError as e:
            raise e
        except Exception as e:
            await Utils.handle_exception("Dropbox gather send tasks failed", self.bot, e)

    async def drop_message_impl(self, source_message, drop_channel):
        """
        handles copying to dropbox, sending confirm message in channel, sending dm receipt, and deleting original
        for each message in any dropbox
        """
        guild_id = source_message.channel.guild.id
        source_channel_id = source_message.channel.id
        source_message_id = source_message.id

        # get the ORM row for this dropbox.
        drop = None
        if source_channel_id in self.dropboxes[guild_id]:
            drop = self.dropboxes[guild_id][source_channel_id]
        else:
            # should only return one entry because of how rows are added
            drop = await DropboxChannel.filter(serveri=guild_id, sourcechannelid=source_channel_id)

        # the embed to display who was the author in dropbox channel
        embed = Embed(
            timestamp=source_message.created_at,
            color=0x663399)
        avatar = source_message.author.avatar.replace(size=32) if source_message.author.avatar else None
        embed.set_author(name=f"{source_message.author} ({source_message.author.id})",
                         icon_url=avatar)
        embed.add_field(name="Author link", value=source_message.author.mention)
        ctx = await self.bot.get_context(source_message)

        pages = Utils.paginate(source_message.content)
        page_count = len(pages)

        if source_message.author.dm_channel is None:
            await source_message.author.create_dm()
        dm_channel = source_message.author.dm_channel

        attachment_names = []
        delivery_success = None
        last_drop_message = None

        try:
            # send embed and message to dropbox channel
            for attachment in source_message.attachments:
                try:
                    buffer = io.BytesIO()
                    await attachment.save(buffer)
                    await drop_channel.send(file=discord.File(buffer, attachment.filename))
                    attachment_names.append(attachment.filename)
                except Exception as attach_e:
                    await drop_channel.send(
                        Lang.get_locale_string('dropbox/attachment_fail', ctx, author=source_message.author.mention))
            
            if len(pages) == 0:
                # means no text content included
                if len(attachment_names) < 1:
                    # if there aren't any attachments, include a message indicating that
                    last_drop_message = await drop_channel.send(
                        embed=embed, content=Lang.get_locale_string('dropbox/msg_blank', ctx))
                else:
                    last_drop_message = await drop_channel.send(embed=embed)
            else:
                # deliver all the pages of text content
                for i, page in enumerate(pages[:-1]):
                    if len(pages) > 1:
                        page = f"**{i+1} of {page_count}**\n{page}"
                    await drop_channel.send(page)
                last_page = pages[-1] if page_count == 1 else f"**{page_count} of {page_count}**\n{pages[-1]}"
                last_drop_message = await drop_channel.send(embed=embed, content=last_page)
            
            # TODO: try/ignore: add reaction for "claim" "flag" "followup" "delete"
            msg = Lang.get_locale_string('dropbox/msg_delivered', ctx, author=source_message.author.mention)
            await ctx.send(msg)
            delivery_success = True
        except Exception as e:
            delivery_success = False
            msg = Lang.get_locale_string('dropbox/msg_not_delivered', ctx, author=source_message.author.mention)
            await ctx.send(msg)
            await self.bot.guild_log(guild_id, "broken dropbox...? Call alex, I guess")
            await Utils.handle_exception("dropbox delivery failure", self.bot, e)

        try:
            # delete original message, the confirmation of sending is deleted in clean_channels loop
            await source_message.delete()
            del self.drop_messages[guild_id][source_channel_id][source_message_id]
            set(self.delivery_in_progress[guild_id][source_channel_id]).remove(source_message_id)
        except discord.errors.NotFound as e:
            # ignore missing message
            pass

        # give senders a moment before spam pinging them the copy
        await asyncio.sleep(1)

        try:
            # try sending dm receipts and report in dropbox channel if it was sent or not
            if drop and drop.sendreceipt:
                # get the locale versions of the messages for status, receipt header, and attachments ready to be sent
                status_msg = Lang.get_locale_string(
                    'dropbox/msg_delivered' if delivery_success else 'dropbox/msg_not_delivered', ctx, author="")
                receipt_msg_header = Lang.get_locale_string('dropbox/msg_receipt', ctx, channel=ctx.channel.mention)
                if len(attachment_names) == 0:
                    attachment_msg = ""
                else:
                    attachment_msg_key = 'dropbox/receipt_attachment_plural' if len(attachment_names) > 1 else 'dropbox/receipt_attachment_singular'
                    attachment_msg = Lang.get_locale_string(
                        attachment_msg_key, 
                        ctx, 
                        number=len(attachment_names), 
                        attachments=", ".join(attachment_names)
                    )
                # might as well try to stuff in as few pages as possible
                dm_header_pages = Utils.paginate(f"{status_msg}\n{receipt_msg_header}\n{attachment_msg}")

                for page in dm_header_pages:
                    await dm_channel.send(page)

                if len(pages) == 0:
                    # no text content
                    if len(attachment_names) < 1:
                        # if no text and no attachments, then send a response that there wasn't any text content
                        await dm_channel.send(content=Lang.get_locale_string('dropbox/msg_blank', ctx))
                else:
                    # send the page(s) in code blocks to dm.
                    for i, page in enumerate(pages[:-1]):
                        if len(pages) > 1:
                            page = f"**{i+1} of {page_count}**\n```{page}```"
                        await dm_channel.send(page)
                            
                    last_page = f'```{pages[-1]}```' if page_count == 1 else f"**{page_count} of {page_count}**\n```{pages[-1]}```"
                    await dm_channel.send(last_page)
                if delivery_success and last_drop_message is not None:
                    embed.add_field(name="receipt status", value="sent")
                    # this is used if drop first before dms to add status to embed
                    edited_message = await last_drop_message.edit(embed=embed)
        except Exception as e:
            Logging.info("Dropbox DM receipt failed, not an issue so ignoring exception and giving up")
            if drop.sendreceipt and delivery_success:
                embed.add_field(name="receipt status", value="failed")
                # this is used if drop first before dms to add status to embed
                if last_drop_message is not None:
                    edited_message = await last_drop_message.edit(embed=embed)

    @tasks.loop(seconds=3.0)
    async def clean_channels(self):
        if self.clean_in_progress:
            return

        self.clean_in_progress = True

        for guild in self.bot.guilds:
            for channel_id, drop in dict(self.dropboxes[guild.id]).items():
                if drop.deletedelayms == 0:
                    # do not clear from dropbox channels with no delay set.
                    continue

                channel = None
                # Look for channel history. Try 10 times to fetch channel history
                # this API call fails on startup because connection is not made yet.
                now = utcnow()
                channel = self.bot.get_channel(channel_id)
                if channel_id not in self.delete_in_progress[guild.id]:
                    self.delete_in_progress[guild.id][channel_id] = set()

                try:
                    clean_tasks = []
                    async for message in channel.history(limit=20):
                        # check if message is queued for delivery
                        if (channel_id in self.drop_messages[guild.id]) and\
                                (message.id in self.drop_messages[guild.id][channel_id]):
                            # don't delete messages that are queued
                            continue
                        my_member = guild.get_member(message.author.id)
                        if my_member is None:
                            continue
                        is_mod = my_member.guild_permissions.ban_members or await self.bot.member_is_admin(my_member.id)
                        age = (now-message.created_at).seconds
                        expired = age > drop.deletedelayms / 1000

                        try:
                            queued_for_delete = message.id in self.delete_in_progress[guild.id][channel_id]
                        except KeyError:
                            # bot is restarting - stop processing and pick this up next time
                            break

                        # periodically clear out expired messages sent by bot and non-mod
                        if expired and not queued_for_delete and (message.author.bot or not is_mod):
                            self.delete_in_progress[guild.id][channel_id].add(message.id)
                            self.bot.loop.create_task(self.clean_message(message))
                        else:
                            pass
                    if clean_tasks:
                        await asyncio.gather(*clean_tasks)
                except (CancelledError, asyncio.TimeoutError, discord.DiscordServerError, NotFound, RuntimeError) as e:
                    # I think these are safe to ignore...
                    pass
                except aiohttp.ClientOSError:
                    await self.bot.guild_log(guild.id, f"Dropbox client error. Probably safe to ignore, but check "
                                                       f"your dropbox channels to make sure they are clean.")
                    continue
                except RuntimeError as e:
                    await self.bot.guild_log(guild.id, f"Dropbox error for guild `{guild.name}`. What's broken?")
                    # fall through and report
                except Exception as e:
                    # ignore but log
                    await Utils.handle_exception('dropbox clean failure', self.bot, e)
                    continue
        self.clean_in_progress = False

    async def clean_message(self, message):
        try:
            await message.delete()
            self.delete_in_progress[message.channel.guild.id][message.channel.id].remove(message.id)
        except (NotFound, HTTPException, Forbidden) as e:
            # ignore delete failure. we'll try again next time
            await Utils.handle_exception('dropbox clean_message failure', self.bot, e)

    @commands.group(name="dropbox", invoke_without_command=True)
    @commands.guild_only()
    async def dropbox(self, ctx):
        """List the dropbox settings. Use sub-commands to configure dropboxes

        Parameters
        ----------
        ctx
        """
        # list dropbox channels
        embed = Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("dropbox/list", ctx, server_name=ctx.guild.name))
        for source, dropbox in self.dropboxes[ctx.guild.id].items():
            source_channel = self.bot.get_channel(source)
            target_channel = self.bot.get_channel(dropbox.targetchannelid)
            embed.add_field(name=f"From",
                            value=Utils.get_channel_description(self.bot, source_channel.id),
                            inline=True)
            embed.add_field(name=f"To",
                            value=Utils.get_channel_description(self.bot, target_channel.id),
                            inline=True)
            embed.add_field(name=f"Delete After",
                            value=Utils.to_pretty_time(dropbox.deletedelayms/1000) or "off",
                            inline=True)
            embed.add_field(name=f"send receipt",
                            value=dropbox.sendreceipt,
                            inline=True)
            embed.add_field(name="__                                             __",
                            value="__                                             __",
                            inline=False)
        if len(self.dropboxes[ctx.guild.id]) == 0:
            embed.add_field(name="Not Set", value="Add dropboxes using `dropbox add` command")
        await ctx.send(embed=embed)

    @dropbox.command()
    @commands.guild_only()
    async def add(self, ctx, source_channel: discord.TextChannel, target_channel: discord.TextChannel):
        """Add a dropbox channel. Messages sent by non-moderator members will be delivered from the source channel to a
        destination channel. Destination can be public or private, as long as the bot has access.

        Parameters
        ----------
        ctx
        sourceid
            ID of the source channel
        targetid
            ID of the destination channel

        Returns
        -------

        """
        sourceid = source_channel.id
        targetid = target_channel.id

        # validate channel ids
        source_channel = self.bot.get_channel(sourceid)
        target_channel = self.bot.get_channel(targetid)
        if not source_channel:
            await ctx.send(Lang.get_locale_string('dropbox/channel_not_found', ctx, channel_id=sourceid))
        if not target_channel:
            await ctx.send(Lang.get_locale_string('dropbox/channel_not_found', ctx, channel_id=targetid))
        if not source_channel or not target_channel:
            # valid source and target channels are required
            return

        # initialize to None for the case of adding a new entry
        update_entry = None

        # channel descriptions
        source_description = Utils.get_channel_description(self.bot, sourceid)
        new_target_description = Utils.get_channel_description(self.bot, targetid)
        old_target_description = ""

        def update(choice):
            nonlocal update_entry
            update_entry = choice

        if sourceid in self.dropboxes[ctx.guild.id]:
            # existing source channel. ask user to confirm
            old_target_description = Utils.get_channel_description(
                self.bot,
                self.dropboxes[ctx.guild.id][sourceid].targetchannelid)
            try:
                await Questions.ask(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    Lang.get_locale_string('dropbox/override_confirmation',
                                           ctx,
                                           source=source_description,
                                           old_target=old_target_description,
                                           new_target=new_target_description),
                    [
                        Questions.Option('YES', handler=lambda: update(True)),
                        Questions.Option('NO', handler=lambda: update(False))
                    ], delete_after=True, locale=ctx)
            except asyncio.TimeoutError as e:
                update(False)

        if update_entry is False:
            # user chose not to update
            await ctx.send(Lang.get_locale_string('dropbox/not_updating', ctx))
            return

        if update_entry:
            # user chose to update
            msg = Lang.get_locale_string('dropbox/updated',
                                         ctx,
                                         source=source_description,
                                         old_target=old_target_description,
                                         new_target=new_target_description)
        else:
            # no existing source. adding a new dropbox
            msg = Lang.get_locale_string('dropbox/added',
                                         ctx,
                                         source=source_description,
                                         target=new_target_description)

        try:
            # update local mapping and save to db
            db_row, created = await DropboxChannel.get_or_create(serverid=ctx.guild.id, sourcechannelid=sourceid)
            db_row.targetchannelid = targetid
            await db_row.save()
            self.dropboxes[ctx.guild.id][sourceid] = db_row
        except Exception as e:
            await Utils.handle_exception("Failed to update dropbox channel", self.bot, e)
            await ctx.send("Can't save dropox channel.")
            return

        # message success to user
        await ctx.send(msg)

    @dropbox.command()
    @commands.guild_only()
    async def remove(self, ctx, source_channel: discord.TextChannel):
        """Remove a dropbox channel. Stop delivering messages from the given channel.

        Parameters
        ----------
        ctx
        source_channel: discord.TextChannel
            ID of the source channel.

        Returns
        -------

        """
        sourceid = source_channel.id
        source_description = Utils.get_channel_description(self.bot, sourceid)
        if sourceid not in self.dropboxes[ctx.guild.id]:
            await ctx.send(Lang.get_locale_string('dropbox/not_removed', ctx, source=source_description))
            return

        try:
            drop_row = await DropboxChannel.get(serverid=ctx.guild.id,
                                                sourcechannelid=sourceid)
            await drop_row.delete()
            del self.dropboxes[ctx.guild.id][sourceid]
        except DoesNotExist:
            await ctx.send("no such channel to remove from dropboxes")
        except tortoise.exceptions.MultipleObjectsReturned:
            await ctx.send("too many dropbox channels match that id???")
        except Exception as e:
            await Utils.handle_exception('dropbox delete failure', self.bot, e)
            raise e
        await ctx.send(Lang.get_locale_string('dropbox/removed', ctx, source=source_description))

    @dropbox.command(aliases=['delay', 'delete_delay'])
    @commands.guild_only()
    async def set_delay(self, ctx, channel: discord.TextChannel, delay: float):
        """Set the lifespan for response messages in the channel

        Also applies to any non-mod messages, so the delay time must be greater than the initial wait for message drops.

        Parameters
        ----------
        ctx
        channel: discord.TextChannel
            Channel mention or ID
        delay: int
            Time until responses expire (seconds)
        """
        if channel.id in self.dropboxes[ctx.guild.id]:
            drop_row = self.dropboxes[ctx.guild.id][channel.id]
            drop_row.deletedelayms = int(delay * 1000)
            await drop_row.save()
            t = Utils.to_pretty_time(delay)
            await ctx.send(Lang.get_locale_string('dropbox/set_delay_success', ctx, channel=channel.mention, time=t))
        else:
            await ctx.send(Lang.get_locale_string('dropbox/set_delay_fail', ctx, channel=channel.mention))

    @dropbox.command()
    @commands.guild_only()
    async def set_receipt(self, ctx, source_channel: discord.TextChannel, receipt_setting: bool):
        """Enable/disable DM receipts. When set, a copy of each dropbox message is sent by DM to the author.

        Parameters
        ----------
        ctx
        source_channel: discord.TextChannel
            Channel mention or ID
        receipt_setting: bool
            Boolean (on or off, 0 or 1, yes or no)
        """
        if source_channel.id in self.dropboxes[ctx.guild.id]:
            drop_row = self.dropboxes[ctx.guild.id][source_channel.id]
            drop_row.sendreceipt = receipt_setting
            await drop_row.save()
            msg = Lang.get_locale_string('dropbox/receipt_set_false', ctx, channel=source_channel.mention)
            if receipt_setting:
                msg = Lang.get_locale_string('dropbox/receipt_set_true', ctx, channel=source_channel.mention)
            await ctx.send(msg)

    @commands.Cog.listener()
    async def on_message(self, message: discord.message):
        try:
            guild_id = message.channel.guild.id
            message_not_in_guild = not hasattr(message.channel, "guild") or message.channel.guild is None
            author_not_in_guild = not hasattr(message.author, "guild")
            channel_not_in_dropboxes = message.channel.id not in self.dropboxes[guild_id]
            is_mod = message.author.guild_permissions.ban_members or await self.bot.member_is_admin(message.author.id)
        except Exception as e:
            return

        if message.author.bot or message_not_in_guild or author_not_in_guild or \
                channel_not_in_dropboxes or is_mod:
            # check for dropbox matching channel id
            # ignore bots and mods/admins
            return

        # queue this message id for delivery/deletion
        if message.channel.id not in self.drop_messages[guild_id]:
            self.drop_messages[guild_id][message.channel.id] = dict()
        self.drop_messages[guild_id][message.channel.id][message.id] = message


async def setup(bot):
    await bot.add_cog(DropBox(bot))
