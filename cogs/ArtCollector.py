import asyncio
import re

import discord
from discord import NotFound, HTTPException
from discord.ext import commands

from utils import Lang, Utils, Emoji, Logging
from utils.Database import ArtChannel

from cogs.BaseCog import BaseCog
from utils.Utils import CHANNEL_ID_MATCHER


class ArtCollector(BaseCog):

    no_tag = "no_tag"
    listen_tag = "listen"

    def __init__(self, bot):
        super().__init__(bot)
        self.channels = dict()
        self.collection_channels = dict()

    async def cog_check(self, ctx):
        return ctx.author.guild_permissions.ban_members or await self.bot.permission_manage_bot(ctx)

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        # Load channels
        for guild in self.bot.guilds:
            await self.init_guild(guild)

    async def init_guild(self, guild):
        if guild.id not in self.collection_channels:
            self.collection_channels[guild.id] = set()
        if guild.id not in self.channels:
            self.channels[guild.id] = dict()
        for row in await ArtChannel.filter(serverid=guild.id):
            self.add_channel(guild.id, row.listenchannelid, row.collectionchannelid, row.tag)

    def add_channel(self, guild_id, listen_channel_id, collection_channel_id, tag):
        # [guild_id][listen][tag] = [collect_to]
        tag = tag or self.no_tag

        # listen channel is primary sort key
        if listen_channel_id not in self.channels[guild_id]:
            self.channels[guild_id][listen_channel_id] = dict()

        # tagged items go to corresponding channel
        self.channels[guild_id][listen_channel_id][tag] = collection_channel_id
        # flat set of channels that art is collected into, for easier listening
        self.collection_channels[guild_id].add(collection_channel_id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.channels[guild.id]
        del self.collection_channels[guild.id]
        await ArtChannel.filter(serverid=guild.id).delete()

    @commands.group(name="artchannel", aliases=['art_channel', 'artchan', 'ac'], invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def art_channel(self, ctx: commands.Context):
        """Show a list of art channels"""
        embed = discord.Embed(timestamp=ctx.message.created_at,
                              color=0x663399,
                              title=Lang.get_locale_string("art/list_channels", ctx, server_name=ctx.guild.name))
        if len(self.channels[ctx.guild.id]) > 0:
            value = ""
            for listen_channel_id, collection in self.channels[ctx.guild.id].items():
                listen_channel_name = await Utils.clean(f"<#{listen_channel_id}>", guild=ctx.guild)
                for tag in collection.keys():
                    channel_id = collection[tag]
                    collect_channel_name = await Utils.clean(f"<#{channel_id}>", guild=ctx.guild)
                    if len(collect_channel_name) + len(f"{channel_id}") > 1000:
                        embed.add_field(name="\u200b", value=value)
                        value = ""
                    print_tag = '' if tag is self.no_tag else f"\"#{tag}\""
                    value = f"{value}**{listen_channel_name}** {print_tag} -> **{collect_channel_name}**\n"
            embed.add_field(name="\u200b", value=value)
            await ctx.send(embed=embed)
        else:
            await ctx.send(Lang.get_locale_string("art/no_channels", ctx))

    @art_channel.command(aliases=["new"])
    @commands.guild_only()
    async def add(self, ctx: commands.Context, listen_channel_id: int, collect_channel_id: int, tag: str = ""):
        """
        Add channel to art collector setup.

        listen_channel_id: id of channel to listen in
        collect_channel_id: id of channel to collect into
        tag: [no_tag|listen|any random tag to track] (default "")
        """
        # TODO: use better Converter for channel_id
        # TODO: move "listen" tag to its own command, like "art_channel add_tracking_channel 12345"

        listen_channel_mention = f"<#{listen_channel_id}>"
        collect_channel_mention = f"<#{collect_channel_id}>"

        if CHANNEL_ID_MATCHER.fullmatch(listen_channel_mention) is None or ctx.guild.get_channel(listen_channel_id) is None:
            await ctx.send(Lang.get_locale_string('art/no_such_channel', ctx, listen_channel_id=listen_channel_id))
            return

        if CHANNEL_ID_MATCHER.fullmatch(collect_channel_mention) is None or ctx.guild.get_channel(collect_channel_id) is None:
            await ctx.send(Lang.get_locale_string('art/no_such_channel', ctx, collect_channel_id=collect_channel_id))
            return

        # Check if listen/collect/tag channel combo already exists
        row = await ArtChannel.get_or_none(
            serverid=ctx.guild.id,
            listenchannelid=listen_channel_id,
            collectionchannelid=collect_channel_id,
            tag=tag)
        listen_channel_name = await Utils.clean(listen_channel_mention, guild=ctx.guild)
        collect_channel_name = await Utils.clean(collect_channel_mention, guild=ctx.guild)

        if row is None:
            # no row found exactly matching channels and tag
            await ArtChannel.create(
                serverid=ctx.guild.id,
                listenchannelid=listen_channel_id,
                collectionchannelid=collect_channel_id,
                tag=tag)
            self.add_channel(ctx.guild.id, listen_channel_id, collect_channel_id, tag)
            channel_added_str = Lang.get_locale_string(
                'art/channel_added', ctx,
                listenchannel=listen_channel_mention,
                collectchannel=collect_channel_mention,
                tag=tag)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {channel_added_str}")
        else:
            # Don't overwrite existing
            await ctx.send(Lang.get_locale_string(
                'art/channel_found', ctx,
                listenchannel=listen_channel_mention,
                collectchannel=collect_channel_mention,
                tag=row.tag))

    @art_channel.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, listen_channel_id: int, collect_channel_id: int, tag=""):
        """
        Remove channel from art collector setup.

        listen_channel_id: id of channel to listen in
        collect_channel_id: id of channel to collect into
        tag: [no_tag|listen|any random tag to track] (default "")
        """
        key = tag or self.no_tag

        # Are we listening for tag in listenchannel, collecting into collectchannel?
        # must be very specific to remove from db.
        if listen_channel_id in self.channels[ctx.guild.id] and \
                key in self.channels[ctx.guild.id][listen_channel_id] and \
                self.channels[ctx.guild.id][listen_channel_id][key] == collect_channel_id:
            # TODO: fetch first, delete if exists, else message error
            try:
                art_row = await ArtChannel.get(serverid=ctx.guild.id,
                                               listenchannelid=listen_channel_id,
                                               collectionchannelid=collect_channel_id,
                                               tag=tag)
                await art_row.delete()
                # don't listen for this tag anymore. if no more tags, don't listen in this channel anymore
                del self.channels[ctx.guild.id][listen_channel_id][key]
                if not self.channels[ctx.guild.id][listen_channel_id]:
                    del self.channels[ctx.guild.id][listen_channel_id]

                lc_mention = self.bot.get_channel(listen_channel_id).mention
                cc_mention = self.bot.get_channel(collect_channel_id).mention
                channel_removed_str = Lang.get_locale_string(
                    'art/channel_removed', ctx,
                    listenchannel=lc_mention,
                    collectchannel=cc_mention,
                    tag=key)
                await ctx.send(f"{Emoji.get_chat_emoji('YES')} {channel_removed_str}")
            except Exception as e:
                await ctx.send(Lang.get_locale_string('art/remove_channel_failed', ctx))
                await Utils.handle_exception("Art collector remove exception", self.bot, e)
        else:
            channel_not_found_str = Lang.get_locale_string(
                'art/channel_not_found', ctx,
                listenchannel=listen_channel_id,
                collectchannel=collect_channel_id,
                tag=tag)
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} {channel_not_found_str}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Message listener. watch art channels for attachments. share attachments to collection channel
        optionally use tags for sort posts into tag collection channels.
        """
        try:
            if message.author.bot\
                    or not message.attachments\
                    or not hasattr(message.channel, "guild")\
                    or message.channel.guild is None\
                    or message.channel.id not in self.channels[message.channel.guild.id]:
                return
        except KeyError as ex:
            return

        ctx = await self.bot.get_context(message)
        tags = []

        for tag in self.channels[ctx.guild.id][message.channel.id].keys():
            tags.append(f"\\b{re.escape(tag)}\\b")
        tag_pattern = '|'.join(tags)
        tag_matcher = re.compile(tag_pattern, re.IGNORECASE)
        tags = tag_matcher.findall(message.content)

        async def do_collect(my_message, my_tag):
            content_shown = False
            my_channel = self.bot.get_channel(self.channels[ctx.guild.id][my_message.channel.id][my_tag.lower()])
            for attachment in my_message.attachments:
                embed = discord.Embed(
                    timestamp=my_message.created_at,
                    color=0x663399)
                embed.add_field(name="Author", value=my_message.author.mention)
                if my_tag is not self.no_tag:
                    embed.add_field(name="Tag", value=f"#{my_tag}")
                embed.add_field(name="Jump Link", value=f"[Go to message]({my_message.jump_url})")
                embed.add_field(name="URL", value=f"[Download]({attachment.url})")
                if my_message.content and not content_shown:
                    # Add message content to the first of multiples, when many attachments to a single my_message.
                    Utils.pages_to_embed(my_message.content, embed, "Message Content")
                    content_shown = True
                embed.set_image(url=attachment.url)
                sent = await my_channel.send(embed=embed)
                try:
                    await sent.add_reaction(Emoji.get_emoji("YES"))
                    await sent.add_reaction(Emoji.get_emoji("NO"))
                except (discord.DiscordServerError, discord.Forbidden):
                    # no reactions for you!
                    pass

        if tags:
            for tag in tags:
                await do_collect(message, tag)
        else:
            await do_collect(message, self.no_tag)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        """
        reaction listener for art collection channels.
        Clears reactions and on "no" reaction, removes post from collection
        """
        try:
            m_id = event.message_id
            u_id = event.user_id
            g_id = event.guild_id
            c_id = event.channel_id
            my_emoji = event.emoji
            my_member = event.member

            my_channel = self.bot.get_channel(c_id)
            my_guild = self.bot.get_guild(g_id)

            if c_id not in self.collection_channels[my_guild.id]:
                return

            user_is_bot = u_id == self.bot.user.id

            # TODO: add role-based check?
            has_permission = my_member.guild_permissions.mute_members or await self.bot.member_is_admin(my_member.id)

            if user_is_bot or not has_permission:
                return

            message = my_channel.get_partial_message(m_id)
            if str(my_emoji) == str(Emoji.get_emoji("NO")):
                # delete message
                await message.delete()
                return
            else:
                await message.clear_reactions()  # any reaction will remove the bot reacts

        except (NotFound, HTTPException, KeyError, AttributeError) as e:
            # couldn't find channel, message, member, or action
            return
        except Exception as e:
            await Utils.handle_exception("art collector generic exception", self.bot, e)
            return


async def setup(bot):
    await bot.add_cog(ArtCollector(bot))
