import re
import json
import asyncio
import collections
from collections.abc import ItemsView
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union, Literal, List

import discord
from discord.ext.commands import Context, ChannelNotFound, CommandError, BadArgument
from discord.utils import utcnow
from discord import AllowedMentions, Message, TextChannel
from discord.ext import commands, tasks
from discord.errors import NotFound, HTTPException, Forbidden
from tortoise.exceptions import MultipleObjectsReturned, DoesNotExist, IntegrityError, TransactionManagementError, \
    OperationalError, IncompleteInstanceError
from tortoise.query_utils import Prefetch

from cogs.BaseCog import BaseCog
from utils.AutoResponderEvent import ArEvent, ArEventFactory
from utils.AutoResponderFlags import ArFlags
from utils.AutoResponderRule import ArRule
from utils import Lang, Utils, Questions, Emoji, Configuration, Logging
from utils.Database import AutoResponder, AutoResponderChannel, AutoResponse, AutoResponderChannelType, AutoResponseType


@dataclass
class ArPager:
    active_page: int = 0
    message: discord.Message = None


class ArCommandMode:
    Add: str = "add"
    Remove: str = "remove"
    Edit: str = "edit"
    Enable: str = "enable"
    Disable: str = "disable"
    List: str = "list"
    ResponseCommandModes = Literal["add", "remove", "edit", "enable", "disable"]
    ChannelCommandModes = Literal["add", "remove"]
    GlobalIgnoreCommandModes = Literal["add", "remove", "list"]


class ArResponseType:
    Public: str = "public"
    Log: str = "log"
    Mod: str = "mod"
    ResponseTypes = Literal["public", "log", "mod"]


class ArChannelType:
    Ignore: str = "ignore"
    Listen: str = "listen"
    Response: str = "response"
    Log: str = "log"
    Mod: str = "mod"
    ChannelTypes = Literal["ignore" ,"listen" ,"response" ,"log" ,"mod"]


class AutoResponders(BaseCog):
    trigger_length_max = 300
    action_expiry_default = 86400
    cold_ping_default_threshold = 600

    def __init__(self, bot):
        super().__init__(bot)
        self.awaiting_delete = dict()
        self.triggers = dict()
        self.mod_messages = dict()
        self.mod_action_expiry = dict()
        self.ar_list = dict()
        self.ar_list_messages = dict()
        self.loaded = False

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        for guild in self.bot.guilds:
            await self.init_guild(guild)
        await self.reload_triggers()
        await self.reload_mod_actions()
        if not self.clean_old_autoresponders.is_running():
            self.clean_old_autoresponders.start()

    def cog_unload(self):
        self.clean_old_autoresponders.cancel()

    async def init_guild(self, guild):
        self.awaiting_delete[guild.id] = dict()
        self.triggers[guild.id] = dict()
        self.mod_messages[guild.id] = dict()
        self.ar_list[guild.id] = []
        self.ar_list_messages[guild.id] = dict()
        self.mod_action_expiry[guild.id] = Configuration.get_var(
            f'auto_action_expiry_seconds_{guild.id}',
            AutoResponders.action_expiry_default
        )

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.triggers[guild.id]
        del self.mod_messages[guild.id]
        del self.ar_list[guild.id]
        del self.ar_list_messages[guild.id]
        del self.mod_action_expiry[guild.id]
        try:
            Configuration.del_persistent_var(f"mod_messages_{guild.id}", True)
            del Configuration.MASTER_CONFIG[f'auto_action_expiry_seconds_{guild.id}']
            Configuration.save()
        except Exception:
            Logging.error(f"Could not save config when removing auto_action_expiry_seconds_{guild.id}")
        await AutoResponder.filter(serverid=guild.id).delete()

    @staticmethod
    async def nope(ctx: Context, msg: str = None):
        msg = msg or Lang.get_locale_string('common/nope', ctx)
        await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} {msg}")

    @staticmethod
    async def get_db_trigger(guild_id: int, trigger: str):
        if guild_id is None or trigger is None:
            return None
        return await AutoResponder.get_or_none(serverid=guild_id, trigger=trigger)

    @staticmethod
    def validate_replies(reply_list: list) -> Optional[list[str]]:
        output = []
        for reply in reply_list:
            if reply is not None and reply != "":
                output.append(reply)

        if not output:
            return None
        return output

    async def cog_check(self, ctx: Context):
        if ctx.guild is None:
            return False
        return ctx.author.guild_permissions.ban_members or await self.bot.permission_manage_bot(ctx)

    async def reload_mod_actions(self, ctx: Optional[Context] = None):
        guilds = self.bot.guilds if ctx is None else [ctx.guild]
        for guild in guilds:
            self.mod_messages[guild.id] = dict()
            saved_mod_messages = Configuration.get_persistent_var(f"mod_messages_{guild.id}")
            if saved_mod_messages:
                for channel_id, actions in saved_mod_messages.items():
                    # Convert json str keys to int
                    channel_id = int(channel_id)
                    if channel_id not in self.mod_messages[guild.id]:
                        self.mod_messages[guild.id][channel_id] = dict()
                    for message_id, action_dict in actions.items():
                        message_id = int(message_id)
                        self.mod_messages[guild.id][channel_id][message_id] = action_dict

    @tasks.loop(seconds=60)
    async def clean_old_autoresponders(self):
        for guild_id, channels in self.mod_messages.items():
            for channel_id, messages in channels.items():
                for message_id, action in self.mod_action_items_view(dict(messages)):
                    now = datetime.now().timestamp()
                    if (now - action['event_time']) > self.mod_action_expiry[guild_id]:
                        #  expire very old mod action messages --- remove reacts and add "expired" react
                        try:
                            del self.mod_messages[guild_id][channel_id][message_id]
                            Configuration.set_persistent_var(f"mod_messages_{guild_id}", self.mod_messages[guild_id])

                            guild = self.bot.get_guild(guild_id)
                            channel = guild.get_channel(channel_id)
                            message = await channel.fetch_message(message_id)
                            await message.clear_reactions()

                            # replace mod action list with acting mod name and datetime
                            my_embed = message.embeds[0]
                            start = message.created_at
                            react_time = utcnow()
                            time_d = Utils.to_pretty_time((react_time - start).seconds)
                            my_embed.set_field_at(-1,
                                                  name="Expired",
                                                  value=f'No action taken for {time_d}',
                                                  inline=True)
                            edited_message = await message.edit(embed=my_embed)
                            await edited_message.add_reaction(Emoji.get_emoji("SNAIL"))
                        except Exception:
                            pass
                        pass

    async def reload_triggers(self, ctx: Optional[Context] = None):
        guilds = self.bot.guilds if ctx is None else [ctx.guild]
        for guild in guilds:
            # Empty the triggers
            self.triggers[guild.id] = dict()

            # Fetch from database
            for ar_row in await AutoResponder.filter(serverid=guild.id).order_by('id').prefetch_related(
                Prefetch(
                    'channels',
                    queryset=AutoResponderChannel.filter(type=AutoResponderChannelType.log),
                    to_attr='log_channels'),
                Prefetch(
                    'channels',
                    queryset=AutoResponderChannel.filter(type=AutoResponderChannelType.response),
                    to_attr='response_channels'),
                Prefetch(
                    'channels',
                    queryset=AutoResponderChannel.filter(type=AutoResponderChannelType.listen),
                    to_attr='listen_channels'),
                Prefetch(
                    'channels',
                    queryset=AutoResponderChannel.filter(type=AutoResponderChannelType.ignore),
                    to_attr='ignored_channels'),
                Prefetch(
                    'channels',
                    queryset=AutoResponderChannel.filter(type=AutoResponderChannelType.mod),
                    to_attr='mod_channels'),
                Prefetch(
                    'responses',
                    queryset=AutoResponse.filter(type=AutoResponseType.mod).limit(1),
                    to_attr='mod_responses'),
                Prefetch(
                    'responses',
                    queryset=AutoResponse.filter(type=AutoResponseType.log).limit(1),
                    to_attr='log_responses'),
                Prefetch(
                    'responses',
                    queryset=AutoResponse.filter(type=AutoResponseType.public),
                    to_attr='reply_responses')):

                ############################################################
                # TODO: remove below section after db migration is confirmed
                #
                #
                if ar_row.listenchannelid:
                    # move to AutoResponderChannel
                    my_id = ar_row.listenchannelid
                    try:
                        row, created = await AutoResponderChannel.get_or_create(
                            channelid=my_id,
                            type=AutoResponderChannelType.listen,
                            autoresponder=ar_row
                        )
                        ar_row.listenchannelid = 0
                        await ar_row.save()
                        Logging.info(f"migrated listen channel {my_id} for ar_id {ar_row.id}")
                    except (IntegrityError, TransactionManagementError):
                        Logging.info(f"migration failed for ar listen channel {my_id} for ar_id {ar_row.id}")

                if ar_row.responsechannelid:
                    # move to AutoResponderChannel
                    my_id = ar_row.responsechannelid
                    try:
                        row, created = await AutoResponderChannel.get_or_create(
                            channelid=my_id,
                            type=AutoResponderChannelType.response,
                            autoresponder=ar_row
                        )
                        ar_row.responsechannelid = 0
                        await ar_row.save()
                        Logging.info(f"migrated response channel {my_id} for ar_id {ar_row.id}")
                    except (IntegrityError, TransactionManagementError):
                        Logging.info(f"migration failed for ar response channel {my_id} for ar_id {ar_row.id}")

                if ar_row.logchannelid:
                    # move to AutoResponderChannel
                    my_id = ar_row.logchannelid
                    try:
                        row, created = await AutoResponderChannel.get_or_create(
                            channelid=my_id,
                            type=AutoResponderChannelType.log,
                            autoresponder=ar_row
                        )
                        ar_row.logchannelid = 0
                        await ar_row.save()
                        Logging.info(f"migrated log channel {my_id} for ar_id {ar_row.id}")
                    except (IntegrityError, TransactionManagementError):
                        Logging.info(f"migration failed for ar log channel {my_id} for ar_id {ar_row.id}")
                #
                #
                # TODO: remove above section after db migration is confirmed
                ############################################################

                if ar_row.trigger in self.triggers[guild.id]:
                    await Logging.bot_log(f"Duplicate trigger: {ar_row.id}) {ar_row.trigger}")
                    continue

                self.triggers[guild.id][ar_row.trigger] = await ArRule.from_db_row(ar_row)
        self.loaded = True

    async def list_auto_responders(self, ctx: Context):
        """Create paginated list of autoresponders, using embeds

        Embed Limits

        Total Characters In Embed: 6000
        Total Fields: 25
        Field Name: 256
        Field Value: 1024
        Footer Text: 2048
        Author Name: 256
        Title: 256
        Description: 2048
        Embeds Per Message: 10

        General Limits

        Username: 80
        Message Content: 2000
        Message Files: 10
        """

        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("autoresponder/list", ctx, server_name=ctx.guild.name))

        if len(self.triggers[ctx.guild.id].keys()) > 0:
            guild_triggers = self.triggers[ctx.guild.id]

            my_list = []
            for trigger, rule in guild_triggers.items():
                my_list.append(rule.get_info())

            list_page = []
            self.ar_list[ctx.guild.id] = []
            for line in my_list:
                # split to groups of 10, max 2000 char
                if len(list_page) == 8 or len(''.join(list_page) + line + 50*'_') > 2000:
                    self.ar_list[ctx.guild.id].append(list_page)
                    list_page = []
                list_page.append(line)
            if list_page:
                # one more page to attach
                self.ar_list[ctx.guild.id].append(list_page)

            embed.add_field(name="page", value=f"1 of {len(self.ar_list[ctx.guild.id])}", inline=False)
            list_message = await ctx.send(embed=embed,
                                          content='\n'.join(self.ar_list[ctx.guild.id][0]),
                                          allowed_mentions=AllowedMentions.none())
            for emoji in ['LEFT', 'RIGHT']:
                await list_message.add_reaction(Emoji.get_emoji(emoji))
            self.ar_list_messages[ctx.guild.id][list_message.id] = ArPager(0, list_message)
        else:
            await ctx.send(Lang.get_locale_string("autoresponder/none_set", ctx))

    @staticmethod
    def trigger_items_view(triggers: dict) -> ItemsView[str, ArRule]:
        return triggers.items()

    @staticmethod
    def mod_action_items_view(events: dict) -> ItemsView[int, dict]:
        return events.items()

    def find_trigger_by_id(self, guild_id, ar_id):
        for trigger, data in AutoResponders.trigger_items_view(self.triggers[guild_id]):
            if data.id == ar_id:
                return trigger
        return None

    def get_rule_by_id(self, guild_id: int, ar_id: int):
        return self.triggers[guild_id][self.find_trigger_by_id(guild_id, ar_id)]

    async def choose_trigger(self, ctx: Context, trigger: Union[int, str]):
        if trigger is not None:
            try:
                # check for trigger by db id
                my_id = int(trigger)
                trigger_by_id = self.find_trigger_by_id(ctx.guild.id, my_id)
                if trigger_by_id is not None:
                    if str(trigger) in self.triggers[ctx.guild.id]:
                        # TODO: detect trigger text that also matches id and offer a choice
                        #  e.g. if trigger "134" and ar id 134 are different rules, choose
                        pass
                    return trigger_by_id
            except ValueError:
                if trigger in self.triggers[ctx.guild.id]:
                    return trigger
                msg = Lang.get_locale_string(
                    'autoresponder/not_found', ctx, trigger=trigger)
                await ctx.send(f"{Emoji.get_chat_emoji('NO')} {msg}")
                raise

        options = []
        trigger_str_by_id = dict()
        options.append(f"{Lang.get_locale_string('autoresponder/available_triggers', ctx)}")
        prompt_messages = []

        async def clean_dialog():
            nonlocal prompt_messages
            for item in prompt_messages:
                try:
                    await item.delete()
                    await asyncio.sleep(0.1)
                except Exception as e:
                    await Utils.handle_exception("Autoresponder choose_trigger clean_dialog exception", self.bot, e)
                    pass

        for trigger_string, data in AutoResponders.trigger_items_view(self.triggers[ctx.guild.id]):
            available_triggers = '\n'.join(options)
            option = f"{data.id} ) {data.short_description()}"
            if len(f"{available_triggers}\n{option}") > 1000:
                prompt_messages.append(await ctx.send(available_triggers))  # send current options, save message
                options = ["**...**"]  # reinitialize w/ "..." continued indicator
            options.append(option)
            trigger_str_by_id[data.id] = trigger_string
        options = '\n'.join(options)
        prompt_messages.append(await ctx.send(options))  # send current options, save message
        prompt = Lang.get_locale_string('autoresponder/which_trigger', ctx)

        try:
            chosen_trigger = int(await Questions.ask_text(self.bot,
                                                          ctx.channel,
                                                          ctx.author,
                                                          prompt,
                                                          locale=ctx,
                                                          delete_after=True))
            if chosen_trigger in trigger_str_by_id.keys():
                chosen_trigger = trigger_str_by_id[chosen_trigger]
                chosen: ArRule = self.triggers[ctx.guild.id][chosen_trigger]
                await ctx.send(
                    Lang.get_locale_string(
                        'autoresponder/you_chose', ctx, value=chosen.short_description()))
                await clean_dialog()
                return chosen_trigger
            raise ValueError
        except (ValueError, asyncio.TimeoutError):
            await clean_dialog()
            key_dump = ', '.join(str(x) for x in trigger_str_by_id)
            await self.nope(ctx, Lang.get_locale_string("autoresponder/expect_integer", ctx, keys=key_dump))
            raise

    async def validate_trigger(self, ctx: Context, trigger):
        if len(trigger) == 0:
            msg = Lang.get_locale_string('autoresponder/empty_trigger', ctx)
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {msg}")
        elif len(trigger) > AutoResponders.trigger_length_max:
            msg = Lang.get_locale_string('autoresponder/trigger_too_long', ctx)
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {msg}")
        elif trigger in self.triggers[ctx.guild.id]:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} Trigger exists already. Duplicates not allowed.")
        else:
            p1 = re.compile(r"(\[|, )'")
            p2 = re.compile(r"'(, |])")
            fixed = p1.sub(r'\1"', trigger)
            fixed = p2.sub(r'"\1', fixed)
            try:
                json.loads(fixed)
                return fixed
            except json.decoder.JSONDecodeError:
                return trigger
        return False

    @commands.group(name="autoresponder", aliases=['ar'])
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def autor(self, ctx: Context):
        """Show a list of autoresponder tags and their flags"""
        if ctx.invoked_subcommand is None:
            await self.list_auto_responders(ctx)

    @autor.command()
    @commands.guild_only()
    async def info(self, ctx: Context, trigger: str = None):
        """Show detailed information about an auto-responder

        Parameters
        ----------
        ctx
        trigger
            The trigger or auto-responder ID to view
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        rule: ArRule = self.triggers[ctx.guild.id][trigger]
        embeds = await ctx.invoke(self.get_raw, trigger=trigger, return_embeds=True)
        await ctx.send(rule.get_info(), embeds=embeds)

    @autor.command(aliases=["flags", "lf"])
    @commands.guild_only()
    async def list_flags(self, ctx: Context, trigger: str = None):
        """List settings for a trigger/response

        Parameters
        ----------
        ctx
        trigger: str
            Optionally name the trigger to select. If trigger is omitted, bot dialog will request it.
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        trigger_obj: ArRule = self.triggers[ctx.guild.id][trigger]
        await ctx.send(
            f"{trigger_obj.short_description()}: {trigger_obj.flags.get_flags_description()}")

    @autor.command(aliases=["raw"])
    @commands.guild_only()
    async def get_raw(self, ctx: Context, trigger: str = None, return_embeds: bool = False):
        """View raw trigger/response text for a given autoresponder

        Parameters
        ----------
        ctx
        trigger: str
            Optionally name the trigger to select. If trigger is omitted, bot dialog will request it.
        return_embeds: bool
            If set, suppress message sending, and return list of embeds instead
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        row = await AutoResponder.get_or_none(serverid=ctx.guild.id, trigger=trigger)
        if trigger is None or row is None:
            await self.nope(ctx)
            return

        embeds = []
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0xffe900,
            title=Lang.get_locale_string("autoresponder/raw", ctx, server_name=ctx.guild.name))

        embed.add_field(name="Raw trigger", value=trigger, inline=False)
        embeds.append(embed)

        async def describe(input_label, embed_color, input_deque):
            my_embed = discord.Embed(
                timestamp=ctx.message.created_at,
                color=embed_color,
                title=f"**{input_label}** responses")
            if len(input_deque) == 0:
                return None
            else:
                i = 1
                j = 1
                while input_deque:
                    response = input_deque.popleft()
                    wrap = "" if response.active else "~~"
                    label = j if response.active else f"{j} [DISABLED]"
                    response_str = await Utils.clean(str(response))
                    while len(response_str) > 1000:
                        output = response_str[:1000]
                        response_str = response_str[1000:]
                        my_embed.add_field(
                            name=label if i == 1 else f"{label} (part {i})",
                            value=f"{wrap}{output}{wrap}",
                            inline=False)
                        i += 1
                    my_embed.add_field(
                        name=label if i == 1 else f"{label} (part {i})",
                        value=f"{wrap}{response_str}{wrap}",
                        inline=False)
                    j += 1
            return my_embed

        embeds.append(
            await describe(
                "public",
                0xc8ff00,
                collections.deque(self.triggers[ctx.guild.id][trigger].responses[str(AutoResponseType.public)])))
        embeds.append(
            await describe(
                "mod",
                0x5ed900,
                collections.deque(self.triggers[ctx.guild.id][trigger].responses[str(AutoResponseType.mod)])))
        embeds.append(
            await describe(
                "log",
                0x00954a,
                collections.deque(self.triggers[ctx.guild.id][trigger].responses[str(AutoResponseType.log)])))

        embeds = [x for x in embeds if x is not None]
        if return_embeds:
            return embeds
        else:
            await ctx.send(embeds=embeds)

    @autor.group(name='settings', aliases=['set'], invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def ar_conf_set(self, ctx: Context):
        """List auto-responder global settings if no subcommand is given."""

        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=f"Auto-responder settings for {ctx.guild.name}")

        action_expiry = Configuration.get_var(
            f'auto_action_expiry_seconds_{ctx.guild.id}',
            AutoResponders.action_expiry_default)
        cold_ping_time = Configuration.get_var(
            f'autoresponder_max_mentionable_age_{ctx.guild.id}',
            AutoResponders.cold_ping_default_threshold)
        a, b, c, ignore_description = await ArRule.get_global_ignore_channels(self.bot, ctx.guild.id)

        embed.add_field(
            name="Cold Ping Threshold",
            value=cold_ping_time,
            inline=False)
        embed.add_field(
            name="Mod Action Expiration",
            value=action_expiry,
            inline=False)
        embed.add_field(
            name="Global Ignore Channels",
            value=ignore_description,
            inline=False)

        await ctx.send(embed=embed)

    @ar_conf_set.command(aliases=['action_expiration'])
    @commands.guild_only()
    async def action_expiry_seconds(self, ctx: Context, expiry_seconds: int = 0):
        """Set the amount of time (in seconds) after which unused mod-action messages expire.

        Parameters
        ----------
        ctx
        expiry_seconds
            Time in seconds. (e.g. 3600 for one hour, 86400 for one day) Default is 1 day.
        """
        if expiry_seconds == 0:
            expiry_seconds = AutoResponders.action_expiry_default

        old_exp = self.mod_action_expiry[ctx.guild.id]
        exp = Utils.to_pretty_time(expiry_seconds)
        if old_exp == expiry_seconds:
            await ctx.send(f"mod action message expiration time is already {exp}")
            return
        try:
            # save to configuration and local var last in case saving config raises error
            Configuration.MASTER_CONFIG[f'auto_action_expiry_seconds_{ctx.guild.id}'] = expiry_seconds
            Configuration.save()
            self.mod_action_expiry[ctx.guild.id] = expiry_seconds
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} "
                           f"Configuration saved. Autoresponder mod action messages are now valid for {exp}")
        except Exception:
            await ctx.send(f"Failed while saving configuration. check the logs...")

    @ar_conf_set.command(aliases=['cold_ping_threshold'])
    async def ping_time(self, ctx: Context, max_age: int):
        """Set the time (in seconds) beyond which auto-response is no longer allowed to ping members

        Parameters
        ----------
        ctx
        max_age
            Threshold value, in seconds
        """
        max_age = int(max_age)
        if max_age < 0:
            await ctx.send(f"Sorry, I can't wait less than zero time, or else I'd have to ping everyone in advance")
            return

        Configuration.MASTER_CONFIG[f'autoresponder_max_mentionable_age_{ctx.guild.id}'] = max_age
        Configuration.save()

        if max_age == 0:
            await ctx.send(f"Well now **nobody** gets pings. That's not fair to ME!")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} "
                           f"Okay, messages older than {Utils.to_pretty_time(max_age)} won't get cold pings")

    @autor.command()
    @commands.guild_only()
    async def reload(self, ctx: Context):
        """Reload all AutoResponders for the current guild from database"""
        await self.reload_triggers(ctx)
        await ctx.send("reloaded:")
        await self.list_auto_responders(ctx)

    @autor.command()
    @commands.guild_only()
    async def create(self, ctx: Context, trigger: str, *, reply: str = None):
        """Add a new trigger/response

        Specify the trigger string and the response.
        Flags are unset when initialized, so newly created responders will not be active.
        Use `autoresponder set_flag` to activate

        Parameters
        ----------
        ctx
        trigger
            The trigger to respond to. String (in quotes if there are spaces) or `«["quoted"]»` JSON array.
            `«["one", "two"]»` will match a message with one **AND** two
            `«[["one", "two"]]»` will match a message with one **OR** two
            `«[["one", "two"],["three", "four"]]»` will match `one three`, `one four`, `two three`, or `two four`
        reply
            Public response to comments that match the trigger. To specify multiple responses, terminate each response
            with both a semicolon and newline.
            Add responses and response types later with the `autoresponder response add [type]` command.
            All auto-responses can include these tokens (include curly braces):
            {author} mentions the user who triggered
            {channel} mentions the channel in which response was triggered
            {link} links to the message that triggered response
            {trigger_message} contents of the message that matched the trigger
            {matched} the token or list of tokens that matched the trigger
        """
        trigger = await self.validate_trigger(ctx, trigger)
        if not trigger:
            await ctx.send(Lang.get_locale_string('autoresponder/not_updating', ctx))
            return

        # Multiple replies may be given, but each reply must be terminated with a semicolon and newline `;\n`
        replies = re.split(r' *; *\n', reply)
        # remove semicolon from the last entry in case of common input mistake
        last = replies[-1:][0]
        last = re.sub(r';$', '', last)
        replies[-1:] = [last]

        validated_replies = set(AutoResponders.validate_replies(replies))
        if validated_replies is None:
            await ctx.send(f"{Emoji.get_chat_emoji('WHAT')} {Lang.get_locale_string('autoresponder/empty_reply', ctx)}")
            return

        ar_row = await self.get_db_trigger(ctx.guild.id, trigger)
        if ar_row is None:
            try:
                ar_row = await AutoResponder.create(serverid=ctx.guild.id, trigger=trigger)
                for this_reply in validated_replies:
                    response_row = await AutoResponse.create(
                        autoresponder=ar_row,
                        type=AutoResponseType.public,
                        response=this_reply)

                await self.reload_triggers(ctx)
                added_message = Lang.get_locale_string('autoresponder/added', ctx,
                                                       trigger=trigger, trigid=ar_row.id)
                await ctx.send(f"{Emoji.get_chat_emoji('YES')} {added_message}")
            except (IntegrityError, OperationalError) as e:
                await Utils.handle_exception("Create AR Failure", self.bot, e)
        else:
            await ctx.send(Lang.get_locale_string('autoresponder/not_updating', ctx))
            return

    @autor.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: Context, trigger: str = None):
        """Remove a trigger/response.

        Parameters
        ----------
        ctx
        trigger
            Optionally name the trigger to select. If trigger is omitted, bot dialog will request it.
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        try:
            # Assemble feedback
            rule: ArRule = self.triggers[ctx.guild.id][trigger]
            desc = rule.short_description('')
            msg = Lang.get_locale_string('autoresponder/removed', ctx, trigger=desc)

            # Delete from db and memory
            ar_row = await AutoResponder.get(serverid=ctx.guild.id, trigger=trigger)
            await ar_row.delete()
            del self.triggers[ctx.guild.id][trigger]

            # respond and reload from db
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {msg}")
            await self.reload_triggers(ctx)
        except MultipleObjectsReturned:
            await ctx.send(f"Something wrong in the database... too many matches to trigger ```{trigger}```")
        except DoesNotExist:
            await ctx.send(f"I didn't find a matching AutoResponder with trigger ```{trigger}```")
        except Exception as e:
            await Utils.handle_exception("unknown AR Remove exception", self.bot, e)

    # TODO: ar subscribe
    #  command to subscribe to matches
    #  ar subscription table with subscriber IDs
    #  send alert in guild log:
    #   `{trigger}` {link} [@mentions...]
    #   ```content```

    @autor.command()
    @commands.guild_only()
    async def response(self,
                       ctx: Context,
                       mode: ArCommandMode.ResponseCommandModes,
                       response_type: ArResponseType.ResponseTypes,
                       trigger: str = None,
                       *, response: str = None):
        """Add, remove, or edit a response of any type for a given AutoResponder

        Parameters
        ----------
        ctx
        mode
            Add|Remove|Edit|Enable|Disable
        response_type
            Public|Log|Mod
        trigger
            An autoresponder trigger or ID
        response
            The response to modify
        """
        # !ar response add|remove|edit public|mod|log [trigger|id] [reply|id]
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            raise BadArgument  # TODO: test and maybe replace other CommandErrors

        response_types = {
            ArResponseType.Public: AutoResponseType.public,
            ArResponseType.Log: AutoResponseType.log,
            ArResponseType.Mod: AutoResponseType.mod
        }
        my_rule: ArRule = self.triggers[ctx.guild.id][trigger]
        my_type = response_types[response_type]

        try:
            my_responses = list(my_rule.responses[str(my_type)])
        except KeyError:
            raise CommandError

        my_responses = [x for x in my_responses]
        choice_list = []
        available_count = 0

        for i, r in enumerate(my_responses):
            prefix = f"{i+1} ) " + ("~~" if not r.active else '')
            clean_response = await Utils.clean(r)
            suffix = "~~ **[DISABLED]**" if not r.active else ''
            choice_list.append(f"{prefix}{clean_response}{suffix}")
            if ((mode == ArCommandMode.Enable and not r.active) or
                    (mode == ArCommandMode.Disable and r.active) or
                    (mode in [ArCommandMode.Edit, ArCommandMode.Remove])):
                available_count += 1

        choice_list = '\n'.join(choice_list)

        async def list_existing():
            # list existing responses for type
            await ctx.send(f"**{response_type}** responses for ar id {my_rule.id}:\n"
                           f"{choice_list}",
                           allowed_mentions=AllowedMentions.none())

        if mode in [ArCommandMode.Remove,
                    ArCommandMode.Edit,
                    ArCommandMode.Enable,
                    ArCommandMode.Disable] and available_count == 0:
            await ctx.send(f"ar id {my_rule.id} has no responses available to {mode}")
            return

        if mode == ArCommandMode.Remove:
            response_type_count = len(my_responses)

            if response_type_count == 0:
                await ctx.send(f"There are no **{response_type}** responses configured. Can't remove what's not there.")
                return

            if response_type_count == 1:
                if my_type == AutoResponseType.public:
                    # public response is not optional, so a single response can not be removed
                    await ctx.send("AutoResponder must have at least one public response. Edit the existing response "
                                   "or add a new one before removing this one.")
                    return
                elif not response:
                    # log and mod responses are optional, so a single response can be removed
                    response = my_responses[0]

        prompts = {
            ArCommandMode.Add: f"How should I respond to {my_rule.short_description()}?",
            ArCommandMode.Remove: f"Which response should I remove from {my_rule.short_description()}?",
            ArCommandMode.Edit: f"Which response for {my_rule.short_description()} should I edit?",
            ArCommandMode.Enable: f"Which response for {my_rule.short_description()} should I enable?",
            ArCommandMode.Disable: f"Which response for {my_rule.short_description()} should I disable?",
        }

        # prompt for response to add|remove|edit
        if not response:
            await list_existing()
            prompt = prompts[mode]
            response = await Questions.ask_text(self.bot,
                                                ctx.channel,
                                                ctx.author,
                                                prompt,
                                                locale=ctx,
                                                delete_after=False,
                                                escape=False)

        try:
            if int(response):
                # Check if the answer is a number from the zero-indexed list
                try:
                    response = my_responses[int(response)-1]
                except IndexError:
                    pass
        except (ValueError, TypeError):
            pass

        # if search by numer fails or prompt is string, convert response to AutoResponse model
        if not isinstance(response, AutoResponse):
            for r in my_responses:
                if str(r) == str(response):
                    response = r

        # finally, if we failed to find an existing model when editing or removing, bail out
        if (mode in (ArCommandMode.Edit,
                     ArCommandMode.Remove,
                     ArCommandMode.Enable,
                     ArCommandMode.Disable) and
                not isinstance(response, AutoResponse)):
            await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} Failed to find a response that matches `{response}`")
            return

        # TODO: multi-response handling
        escaped_response = await Utils.clean(response)

        if mode == ArCommandMode.Add:
            for existing_response in my_responses:
                if str(existing_response) == str(response):
                    await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} matched an existing response. nothing to do")
                    return
            await AutoResponse.create(autoresponder=my_rule.ar_row, type=my_type, response=response)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} Added `{escaped_response}` to ar rule {my_rule.id}")
        elif mode == ArCommandMode.Remove:
            # Remove response row
            await response.delete()
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} Removed `{escaped_response}` from ar rule {my_rule.id}")
        elif mode == ArCommandMode.Edit:
            # Edit response row
            await ctx.send(f"Editing this {response_type} response in ar rule {my_rule.id}: ```{escaped_response}```")
            new_response = await Questions.ask_text(self.bot,
                                                    ctx.channel,
                                                    ctx.author,
                                                    "What would you like the new response to be?",
                                                    locale=ctx,
                                                    delete_after=False,
                                                    escape=False)
            try:
                response.response = new_response
                await response.save()
                await ctx.send(f"{Emoji.get_chat_emoji('YES')} Response updated!")
            except (IntegrityError, IncompleteInstanceError) as e:
                await Utils.handle_exception("Failed response edit", self.bot, e)
                raise CommandError
        elif mode == ArCommandMode.Enable:
            if response.active:
                await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} The selected response is already enabled")
                return
            response.active = True
            await response.save()
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} Enabled the response:\n```{escaped_response}```")
        elif mode == ArCommandMode.Disable:
            if not response.active:
                await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} The selected response is already disabled")
                return
            response.active = False
            await response.save()
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} Disabled the response:\n```{escaped_response}```")
        await self.reload_triggers(ctx)

    @autor.command(aliases=["edit", "trigger", "st"])
    @commands.guild_only()
    async def set_trigger(self, ctx: Context, trigger: str = None, *, new_trigger: str = None):
        """Update tan autoresponder trigger

        Parameters
        ----------
        ctx
        trigger: str
            The trigger to edit (must be quoted string if spaces)
        new_trigger: str
            The new trigger to replace the old (no need for quotes)
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            raise CommandError

        # trigger = await Utils.clean(trigger, links=False)
        if new_trigger is None:
            try:
                new_trigger = await Questions.ask_text(self.bot,
                                                       ctx.channel,
                                                       ctx.author,
                                                       Lang.get_locale_string("autoresponder/prompt_trigger", ctx),
                                                       escape=False,
                                                       locale=ctx)
            except asyncio.TimeoutError:
                # empty trigger emits message when validated below. pass exception
                pass

        new_trigger = await self.validate_trigger(ctx, new_trigger)
        if new_trigger is not False:
            trigger = await AutoResponder.get_or_none(serverid=ctx.guild.id, trigger=trigger)
            if trigger is None:
                await self.nope(ctx)
            else:
                trigger.trigger = new_trigger
                await trigger.save()
                await self.reload_triggers(ctx)

                await ctx.send(
                    f"{Emoji.get_chat_emoji('YES')} "
                    f"{Lang.get_locale_string('autoresponder/updated', ctx, trigger=new_trigger)}"
                )

    @autor.command(aliases=["chance"])
    @commands.guild_only()
    async def set_chance(self, ctx: Context, trigger: str = None, *, chance: float = None):
        """Set the probability for matching message to trigger a response

        Parameters
        ----------
        ctx
        trigger: str
            Trigger text
        chance:
            Probability of triggering autoresponder, expressed as a percentage with up to 2 decimal places, e.g. 35.15
        """
        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            raise CommandError

        if chance is None:
            try:
                chance = float(await Questions.ask_text(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    Lang.get_locale_string("autoresponder/prompt_chance", ctx),
                    escape=False,
                    locale=ctx))
            except asyncio.TimeoutError:
                return

        try:
            ar_row = await self.get_db_trigger(ctx.guild.id, trigger)
            if ar_row is None:
                await self.nope(ctx)
                return

            chance = int(chance * 100)
            ar_row.chance = chance
            await ar_row.save()
        except Exception as e:
            await Utils.handle_exception("autoresponder set_chance exception", self.bot, e)
        await ctx.send(
            Lang.get_locale_string('autoresponder/chance_set', ctx,
                                   chance=chance/100,
                                   trigger=self.triggers[ctx.guild.id][trigger].short_description('')))
        await self.reload_triggers(ctx)

    @autor.command(aliases=['ignore'])
    @commands.guild_only()
    async def global_ignore(self,
                            ctx: Context,
                            mode: ArCommandMode.GlobalIgnoreCommandModes,
                            *, channels: str = ''):
        """List, add, or remove channels to the global ignore list. ALL autoresponders ignore messages in channels on
        the global ignore list.

        Parameters
        ----------
        ctx
        mode
            Add, Remove, or List
        channels
            The channels to add/remove from global ignore list
        """
        global_ignore_rows, global_ignore_channels, global_ignore_channel_ids, ignore_description = \
            await ArRule.get_global_ignore_channels(self.bot, ctx.guild.id)

        if mode == ArCommandMode.List:
            await ctx.send(ignore_description)
            return

        feedback = []

        async def clean_and_convert_channel_input(in_str):
            nonlocal feedback
            in_str = re.sub(r'\u2060', '', in_str)  # remove word-sep char that comes from copy/paste channel mentions
            cleaned = re.sub(r'\s+', ' ', in_str)  # remove multiple spaces
            my_inputs = cleaned.split(' ')

            my_channels = []
            for channel_input in my_inputs:
                if not channel_input:
                    continue
                conv = commands.TextChannelConverter()
                try:
                    channel = await conv.convert(ctx, channel_input)
                    my_channels.append(channel)
                except ChannelNotFound:
                    feedback.append(f"{Emoji.get_chat_emoji('WARNING')} "
                                    f"I'm sorry, I couldn't find a channel that matches `{channel_input}`.")
            return my_channels

        converted_channels = await clean_and_convert_channel_input(channels)

        if not converted_channels:
            try:
                channels_input = await Questions.ask_text(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    f"{ignore_description}\nWhich channel(s) should I {mode}?",
                    escape=False,
                    locale=ctx)
                if channels_input.startswith(Configuration.get_var("bot_prefix")):
                    return
                converted_channels = await clean_and_convert_channel_input(channels_input)
            except asyncio.TimeoutError:
                return

        channel_ids = [c.id for c in converted_channels if converted_channels]

        if not channel_ids:
            feedback.append(f"{Emoji.get_chat_emoji('WARNING')} There are no channels to {mode}. Try again")
            await ctx.send('\n'.join(feedback))
            return

        can_add = []
        can_remove: List[AutoResponderChannel] = []
        cannot_add = []
        cannot_remove = []

        for row in global_ignore_rows:
            # If a row is in input ids, then it can be removed and can not be added
            if row.channelid in channel_ids:
                can_remove.append(row)
                cannot_add.append(row.channelid)

        for channel_id in channel_ids:
            # if an input id is not in existing list of rows, then it can be added and can not be removed
            if channel_id not in global_ignore_channel_ids:
                can_add.append(channel_id)
                cannot_remove.append(channel_id)

        if mode == ArCommandMode.Add:
            for channel_id in cannot_add:
                feedback.append(f"{Emoji.get_chat_emoji('WARNING')} "
                                f"The channel {self.bot.get_channel(channel_id).mention} "
                                f"is already globally ignored.")
            for channel_id in can_add:
                try:
                    await AutoResponderChannel.create(
                        channelid=channel_id,
                        type=AutoResponderChannelType.ignore)
                except (IntegrityError, IncompleteInstanceError):
                    feedback.append(f"{Emoji.get_chat_emoji('WARNING')} "
                                    f"Failed to add {channel_id} to global ignore list.")
                feedback.append(f"{Emoji.get_chat_emoji('YES')} "
                                f"All AutoResponders will now ignore {self.bot.get_channel(channel_id).mention}.")
        elif mode == ArCommandMode.Remove:
            for channel_id in cannot_remove:
                # Did not find existing global ignore channel
                feedback.append(f"{Emoji.get_chat_emoji('WARNING')} "
                                f"The channel {self.bot.get_channel(channel_id).mention} is not ignored, "
                                f"so it can't be removed.")
            for row in can_remove:
                try:
                    await row.delete()
                except OperationalError:
                    feedback.append(f"{Emoji.get_chat_emoji('WARNING')} "
                                    f"Failed to remove {row.channelid} from global ignore list.")
                feedback.append(f"AutoResponders no longer ignore {self.bot.get_channel(row.channelid).mention}.")
        if feedback:
            await ctx.send('\n'.join(feedback))

    @autor.command(aliases=['channel'])
    @commands.guild_only()
    async def channels(self,
                       ctx: Context,
                       mode: ArCommandMode.ChannelCommandModes,
                       channel_type: ArChannelType.ChannelTypes,
                       trigger: str = None,
                       channel: TextChannel = None):
        """Add or remove a channel for AutoResponder handling

        Parameters
        ----------
        ctx
        mode
            Add or remove
        channel_type
            Ignore, listen, response, log, or mod
        trigger
            Trigger id or text
        channel
            Channel to configure
        """

        types = {
            ArChannelType.Listen: AutoResponderChannelType.listen,
            ArChannelType.Response: AutoResponderChannelType.response,
            ArChannelType.Log: AutoResponderChannelType.log,
            ArChannelType.Ignore: AutoResponderChannelType.ignore,
            ArChannelType.Mod: AutoResponderChannelType.mod
        }

        channel_type_enum = types[channel_type]

        try:
            trigger = await self.choose_trigger(ctx, trigger)
        except (ValueError, asyncio.TimeoutError):
            return

        rule: ArRule = self.triggers[ctx.guild.id][trigger]

        channel_groups = {
            ArChannelType.Listen: rule.listen_channels,
            ArChannelType.Response: rule.response_channels,
            ArChannelType.Log: rule.log_channels,
            ArChannelType.Ignore: rule.ignored_channels,
            ArChannelType.Mod: rule.mod_channels
        }

        list_raw = [f"{i+1} ) <#{c}>" for i, c in enumerate(channel_groups[channel_type])]
        channel_list = '\n'.join(list_raw) if list_raw else "[NONE]"

        if mode == ArCommandMode.Remove:
            channel_type_count = len(list_raw)

            if channel_type_count == 0:
                await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} "
                               f"There are no **{channel_type}** channels configured. "
                               f"Can't remove what's not there.")
                return

            if not channel and channel_type_count == 1:
                # only one channel in the selected type. select it automatically for removal
                channel = self.bot.get_channel(channel_groups[channel_type][0])

        try:
            # Attempt to use converted channel to get id
            channel_id = channel.id
        except AttributeError:
            try:
                lang_key = f"autoresponder/prompt_channel_{mode}_{channel_type}"

                if mode == ArCommandMode.Remove and channel_type_enum == AutoResponderChannelType.response:
                    # more than one response channel is set. how did we get here?
                    await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} "
                                   f"Error condition! Too many response channels set. You should probably remove "
                                   f"channels until you see one or zero response channels")

                channel_input = await Questions.ask_text(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    Lang.get_locale_string(lang_key,
                                           ctx,
                                           channel_list=channel_list),
                    escape=False,
                    locale=ctx)
                try:
                    conv = commands.TextChannelConverter()
                    Logging.info(conv)
                    channel = await conv.convert(ctx, channel_input)
                    Logging.info(channel)
                except (CommandError, BadArgument):
                    try:
                        if int(channel_input) <= 0:
                            raise ValueError
                        if int(channel_input) > 0:
                            # Check if the answer is a 1-indexed choice from the zero-indexed list
                            chosen_index = int(channel_input) - 1
                            if int(channel_input) > len(channel_groups[channel_type]):
                                await ctx.send(
                                    f"{Emoji.get_chat_emoji('WARNING')} "
                                    f"I'm sorry, but `{channel_input}` isn't in my list of {channel_type} channels, "
                                    f"and isn't an index from the list above")
                                return
                            chosen_channel_id = channel_groups[channel_type][chosen_index]
                            channel = self.bot.get_channel(chosen_channel_id)
                    except (ValueError, IndexError, TypeError):
                        await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} "
                                       f"I'm sorry, I couldn't find a channel that matches `{channel_input}`")
                        return
                channel_id = channel.id
            except asyncio.TimeoutError:
                return

        ar_row = await self.get_db_trigger(ctx.guild.id, trigger)

        if not ar_row or not channel_id:
            raise CommandError

        if mode == ArCommandMode.Remove:
            try:
                row = await AutoResponderChannel.get_or_none(
                    type=channel_type_enum,
                    autoresponder=ar_row,
                    channelid=channel_id)
                if row:
                    await row.delete()
                    await ctx.send(f"{Emoji.get_chat_emoji('NO')} " + Lang.get_locale_string(
                        "autoresponder/channel_unset",
                        ctx,
                        channel_type=channel_type,
                        channel_desc=Utils.get_channel_description(self.bot, channel_id),
                        trigger=self.triggers[ctx.guild.id][trigger].short_description('')))
                else:
                    await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} "
                                   f"channel {channel.mention} is not a {channel_type} channel for ar id {ar_row.id}")
            except OperationalError:
                await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} Failed to remove channel {channel.mention} "
                               f"from `{channel_type}` channels matching `{trigger}`")
        elif mode == ArCommandMode.Add:
            if channel_type_enum == AutoResponderChannelType.response:
                try:
                    # Enforce a single response channel
                    row = await AutoResponderChannel.get(
                        type=AutoResponderChannelType.response, autoresponder=ar_row)
                    row.channelid = channel_id
                    await row.save()
                except DoesNotExist:
                    await AutoResponderChannel.create(
                        type=AutoResponderChannelType.response, autoresponder=ar_row, channelid=channel_id)
                except MultipleObjectsReturned:
                    multiple_rows = await AutoResponderChannel.filter(
                        type=AutoResponderChannelType.response, autoresponder=ar_row)
                    for row in multiple_rows:
                        await row.delete()
                    await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} "
                                   f"I found too many response rows, so I deleted all of them. Start again! "
                                   f"{Emoji.get_chat_emoji('WARNING')}")
            else:
                # TODO: if channel_type_enum == AutoResponderChannelType.ignore
                #  and count of listen channels > 0
                #  prompt that this will unset "listen" channels, confirm, then unset listen channels
                #  prompt: setting an ignore channel means that listen channel(s) will be unset. Proceed? [y/n]
                try:
                    new_row, created = await AutoResponderChannel.get_or_create(
                        channelid=channel_id,
                        type=channel_type_enum,
                        autoresponder=ar_row)
                except (IntegrityError, TransactionManagementError):
                    await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} "
                                   f"Failed to create database row. Check the logs or something.")
                    raise

                if not created:
                    await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} That entry already exists")
                    return
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} "+Lang.get_locale_string(
                "autoresponder/channel_set",
                ctx,
                channel=channel.mention,
                channel_type=channel_type,
                trigger=self.triggers[ctx.guild.id][trigger].short_description('')))

        await self.reload_triggers(ctx)

    @autor.command(aliases=["sf"])
    @commands.guild_only()
    async def set_flag(self, ctx: Context, trigger: str = None, flag_index: int = None, value: bool = None):
        """Set an on/off option for a trigger/response

        Parameters
        ----------
        ctx
        trigger: str
            Optionally name the trigger to select. If trigger is omitted, bot dialog will request it.
        flag_index: int
            Flag number
        value: bool
            Set the selected flag on or off
        """
        ar_row = None
        while ar_row is None:
            try:
                trigger = await self.choose_trigger(ctx, trigger)
            except (ValueError, asyncio.TimeoutError):
                return

            # get db trigger based on raw trigger
            ar_row = await self.get_db_trigger(ctx.guild.id, trigger)
        try:
            ar_rule: ArRule = self.triggers[ctx.guild.id][trigger]
            options = [f"{Utils.get_bitshift(int(i))}) {i}" for i in ArFlags]

            if flag_index is None or flag_index < 0:
                options = '\n'.join(options)
                flag_index = int(await Questions.ask_text(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    Lang.get_locale_string('autoresponder/which_flag', ctx, options=options),
                    locale=ctx))

            my_ar_flag = ArFlags.init_by_bitshift(flag_index)

            if value is None:
                def choose(val):
                    nonlocal value
                    value = bool(val)

                await Questions.ask(
                    self.bot,
                    ctx.channel,
                    ctx.author,
                    Lang.get_locale_string(
                        'autoresponder/on_or_off',
                        ctx,
                        subject=str(my_ar_flag)),
                    [
                        Questions.Option(f"YES", 'On', handler=choose, args=[True]),
                        Questions.Option(f"NO", 'Off', handler=choose, args=[False])
                    ],
                    delete_after=True, show_embed=True, locale=ctx)

            if value:
                ar_row.flags = ar_row.flags | int(my_ar_flag)
            else:
                ar_row.flags = ar_row.flags & ~(int(my_ar_flag))

            await ar_row.save()
            modified_flags = ArFlags(ar_row.flags)

            my_emoji = "YES" if value else "NO"
            actioned = "activated" if value else "deactivated"
            output = [f"{Emoji.get_chat_emoji(my_emoji)} `{my_ar_flag}` flag {actioned}"]
            warnings = []
            if ArFlags.MOD_ACTION in modified_flags:
                if not ar_rule.response_channels:
                    warnings.append(Lang.get_locale_string('autoresponder/mod_action_warning', ctx))
                if ArFlags.DM_RESPONSE in modified_flags:
                    warnings.append(f"`dm_response` is not effective because `mod_action` is set")
            else:
                # mod action is not set
                if ArFlags.DELETE_WHEN_TRIGGER_DELETED in modified_flags:
                    warnings.append(f"`delete_when_trigger_deleted` is not effective because `mod_action` is not set")
                if ArFlags.DELETE_ON_MOD_RESPOND in modified_flags:
                    warnings.append(f"`delete_on_mod_respond` is not effective because `mod_action` is not set")

            warnings = [f"{Emoji.get_chat_emoji('WARNING')} {x}" for x in warnings]
            output += warnings
            output.append(modified_flags.get_flags_description(f"{Emoji.get_chat_emoji('YES')} ar {ar_row.id}"))
            await ctx.send("\n".join(output))
            await self.reload_triggers(ctx)
        except asyncio.TimeoutError:
            pass
        except ValueError:
            await self.nope(ctx)

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        """Message listener: match text with triggers and decide whether and how to respond"""
        await self.bot.wait_until_ready()

        # check these first to avoid conflicts/exceptions
        not_in_guild = not hasattr(message.channel, "guild") or message.channel.guild is None
        if message.author.bot or not_in_guild:
            return

        guild = message.channel.guild

        prefix = Configuration.get_var("bot_prefix")
        ctx = await self.bot.get_context(message)
        can_command = await self.cog_check(ctx)
        command_context = message.content.startswith(prefix, 0) and can_command
        is_mod = message.author.guild_permissions.mute_members or await self.bot.permission_manage_bot(ctx)

        if guild.id not in self.triggers or command_context:
            # Guild not initialized or AR items empty? Ignore.
            return

        # search guild auto-responders
        for trigger, rule in AutoResponders.trigger_items_view(self.triggers[guild.id]):
            try:
                # Instantiation of event handles initial behaviors.
                my_event = await ArEventFactory.evaluate_event(self.bot, message, rule, is_mod)
            except Exception as e:
                await Utils.handle_exception("AutoResponder Unknown Failure", self.bot, e)
                continue
            if my_event is None:
                # All actions for the matched rule completed, or no match. Evaluate the next rule
                continue

            if my_event.has_mod_action():
                await self.add_mod_action(my_event)
            else:
                sent = await my_event.send_public_response()

                # Responding in other channels is usually for mods and logs
                # so do only allow future delete if response is sent in the triggering channel
                delete_in_future = rule.flag_is_set(ArFlags.DELETE_WHEN_TRIGGER_DELETED)
                response_in_trigger_channel = my_event.response_channel == message.channel

                if sent and response_in_trigger_channel and delete_in_future:
                    self.future_delete(
                        rule.id,
                        guild.id,
                        message.channel.id,
                        message.id,
                        sent.id)

    def future_delete(self, ar_id: int, guild_id: int, channel_id: int, message_id: int, response_id: int):
        """Track watch for message delete on specific messages, so bot can remove own responses to those messages

        Parameters
        ----------
        ar_id
            AutoResponders row ID
        guild_id
            The guild's ID
        channel_id
            ID of the channel where response was sent
        message_id
            ID of the message that triggered response
        response_id
            ID of the response message

        Returns
        -------

        """
        # TODO: can future delete be handled by ArEvent? use cog to broadcast delete events

        # Do not queue for delete if the trigger is no longer active
        rule = self.get_rule_by_id(guild_id, ar_id)
        if not rule.flag_is_set(ArFlags.ACTIVE):
            return

        if guild_id not in self.awaiting_delete:
            self.awaiting_delete[guild_id] = dict()
        if channel_id not in self.awaiting_delete[guild_id]:
            self.awaiting_delete[guild_id][channel_id] = dict()
        if message_id not in self.awaiting_delete[guild_id][channel_id]:
            self.awaiting_delete[guild_id][channel_id][message_id] = []
        # message_id is key to a list, so many responses can be removed if necessary
        self.awaiting_delete[guild_id][channel_id][message_id].append(response_id)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        gid = payload.guild_id
        cid = payload.channel_id
        mid = payload.message_id
        if gid in self.awaiting_delete and cid in self.awaiting_delete[gid] and mid in self.awaiting_delete[gid][cid]:
            delete_ids = self.awaiting_delete[gid][cid][mid]
            del self.awaiting_delete[gid][cid][mid]
            try:
                channel = self.bot.get_channel(cid)
                for response_id in delete_ids:
                    # message = await channel.fetch_message(response_id)
                    message = channel.get_partial_message(response_id)
                    await message.delete()
            except (Forbidden, NotFound, HTTPException):
                Logging.info(f"ar waiter failed to deleted response to message {gid}/{cid}/{mid}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        my_event = None
        message = None

        try:
            channel = self.bot.get_channel(event.channel_id)
            my_guild = self.bot.get_guild(channel.guild.id)
            member = my_guild.get_member(event.user_id)
            user_is_bot = event.user_id == self.bot.user.id
            # TODO: change to role-based?
            has_permission = member.guild_permissions.mute_members or await self.bot.member_is_admin(event.user_id)
            if user_is_bot or not has_permission:
                return

            if event.message_id in self.ar_list_messages[channel.guild.id]:
                await self.update_list_message(self.ar_list_messages[channel.guild.id][event.message_id], event)
                return

            if event.message_id in self.mod_messages[channel.guild.id][channel.id]:
                my_event = ArEvent.from_dict(
                    self.bot,
                    self.mod_messages[channel.guild.id][channel.id].pop(event.message_id))
                message = await channel.fetch_message(event.message_id)
                Configuration.set_persistent_var(
                    f"mod_messages_{channel.guild.id}",
                    self.mod_messages[channel.guild.id])
        except (KeyError, AttributeError, HTTPException):
            # couldn't find channel, message, member, or action
            return
        except Exception as e:
            await Utils.handle_exception("auto-responder generic exception", self.bot, e)
            return

        if my_event:
            await self.do_mod_action(my_event, member, message, event.emoji)

    async def update_list_message(self, my_pager: ArPager, event):
        direction = 0
        if str(event.emoji) == str(Emoji.get_emoji("RIGHT")):
            direction = 1
        elif str(event.emoji) == str(Emoji.get_emoji("LEFT")):
            direction = -1
        # Updating a list message
        if direction == 0:
            return

        page = my_pager.active_page
        try:
            guild_id = my_pager.message.channel.guild.id
            my_ar_list = self.ar_list[guild_id]
            step = 1 if direction > 0 else -1
            next_page = (my_pager.active_page + step) % len(my_ar_list)
            embed = my_pager.message.embeds[0]
            embed.set_field_at(-1, name="page", value=f"{next_page+1} of {len(self.ar_list[guild_id])}", inline=False)
            page = next_page
            await my_pager.message.remove_reaction(event.emoji, self.bot.get_user(event.user_id))
            edited_message = await my_pager.message.edit(content='\n'.join(my_ar_list[next_page]), embed=embed)
            my_pager.message = edited_message
        except Exception as e:
            await Utils.handle_exception('AR Pager Failed', self.bot, e)
        my_pager.active_page = page

    async def add_mod_action(self, ar_event):
        """Send mod action message and queue followup actions

        Parameters
        ----------
        ar_event: ArEvent
        """
        # TODO: send mod message with mod_action, fallback on log message, fall back on response
        mod_action_msg = await ar_event.send_mod_action_message()
        if mod_action_msg is None:
            return

        gid = ar_event.guild_id

        # init dict where necessary
        if ar_event.mod_action_channel_id not in self.mod_messages[gid]:
            self.mod_messages[gid][ar_event.mod_action_channel_id] = dict()

        self.mod_messages[gid][ar_event.mod_action_channel_id][mod_action_msg.id] = ar_event.as_dict()
        Configuration.set_persistent_var(f"mod_messages_{gid}", self.mod_messages[gid])

    async def do_mod_action(self, ar_event, member, message, emoji):
        """Perform a mod action, triggered by react

        Parameters
        ----------
        ar_event: ArEvent
            The saved action to execute
        member: discord.Member
            The member performing the action
        message: discord.Message
            The mod action message that received a mod reaction
        emoji: discord.Emoji
            The emoji that was added
        """
        try:
            trigger_channel = self.bot.get_channel(ar_event.channel_id)
            trigger_message = await trigger_channel.fetch_message(ar_event.message_id)
        except (HTTPException, AttributeError):
            trigger_message = None

        m = self.bot.metrics

        if str(emoji) == str(Emoji.get_emoji("YES")):
            # delete mod action message, leave the triggering message
            await message.delete()
            m.auto_responder_mod_pass.inc()
            return

        await message.clear_reactions()

        # replace mod action list with acting mod name and datetime
        my_embed = message.embeds[0]
        start = message.created_at
        react_time = utcnow()
        time_d = Utils.to_pretty_time((react_time-start).seconds)
        my_embed.set_field_at(-1, name="Handled by", value=member.mention, inline=True)

        if trigger_message is None:
            my_embed.add_field(name="Deleted", value=":snail: message removed before action was taken.")

        my_embed.add_field(name="Action Used", value=emoji, inline=True)
        my_embed.add_field(name="Reaction Time", value=time_d, inline=True)
        await message.edit(embed=my_embed)

        if str(emoji) == str(Emoji.get_emoji("CANDLE")):
            # do nothing
            m.auto_responder_mod_manual.inc()
            pass
        if str(emoji) == str(Emoji.get_emoji("WARNING")):
            # send auto-response in the triggering channel
            m.auto_responder_mod_auto.inc()
            if trigger_message is not None:
                msg = await ar_event.get_formatted_response(AutoResponseType.public)
                if not msg:
                    await self.bot.guild_log(
                        ar_event.guild_id,
                        f"No responses configured for AR id {ar_event.autoresponder_id}")
                    return

                # disallow mentions when age of triggering message is too great
                max_age = Configuration.get_var(
                    f'autoresponder_max_mentionable_age_{ar_event.guild_id}',
                    AutoResponders.cold_ping_default_threshold)
                allow_mentions = (datetime.now().timestamp() - trigger_message.created_at.timestamp()) < max_age
                mentions = AllowedMentions(users=True) if allow_mentions else AllowedMentions.none()

                use_reply = ar_event.rule.flag_is_set(ArFlags.USE_REPLY)
                delete_now = ar_event.rule.flag_is_set(ArFlags.DELETE_ON_MOD_RESPOND)
                future_delete = ar_event.rule.flag_is_set(ArFlags.DELETE_WHEN_TRIGGER_DELETED)

                public_response = await trigger_message.channel.send(
                    content=msg,
                    allowed_mentions=mentions,
                    reference=trigger_message if use_reply else None)

                # delete_now takes precedence over future_delete
                if delete_now:
                    await ar_event.trigger_message.delete()
                elif future_delete:
                    self.future_delete(
                        ar_event.autoresponder_id,
                        ar_event.guild_id,
                        ar_event.channel_id,
                        ar_event.message_id,
                        public_response.id)

        if str(emoji) == str(Emoji.get_emoji("NO")):
            # delete the triggering message
            m.auto_responder_mod_delete_trigger.inc()
            if trigger_message is not None:
                await trigger_message.delete()


async def setup(bot):
    await bot.add_cog(AutoResponders(bot))
