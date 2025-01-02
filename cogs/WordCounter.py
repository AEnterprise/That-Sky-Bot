import asyncio
import re

import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Lang, Utils, Emoji, Configuration, Logging
from utils.Database import CountWord


class WordCounter(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.words = dict()

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        self.words = dict()
        for guild in self.bot.guilds:
            await self.init_guild(guild)

    async def init_guild(self, guild):
        my_words = set()
        # fetch words and build matching pattern
        for row in await CountWord.filter(serverid=guild.id):
            my_words.add(re.escape(row.word))
        self.words[guild.id] = "|".join(my_words)

    async def cog_check(self, ctx):
        if ctx.guild is None:
            return False
        return ctx.author.guild_permissions.ban_members or await Utils.permission_manage_bot(ctx)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.words[guild.id]
        await CountWord.filter(serverid=guild.id).delete()

    @commands.group(name="wordcounter", aliases=['wordcount', 'word_count', 'countword', 'count_word'], invoke_without_command=True)
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def word_counter(self, ctx: commands.Context):
        """Show a list of counted words"""
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("word_counter/list_words", ctx, server_name=ctx.guild.name))

        word_list = set()
        # TODO: get guild->words
        for row in await CountWord.filter(serverid=ctx.guild.id):
            word_list.add(row.word)

        if word_list != set():
            # word list is not empty set
            value = ""
            for word in word_list:
                word_cleaned = re.escape(word)
                if len(value) + len(word_cleaned) > 1000:
                    embed.add_field(name="\u200b", value=value)
                    value = ""
                value = f"{value}{word_cleaned}\n"
            embed.add_field(name="\u200b", value=value)
            await ctx.send(embed=embed)
        else:
            await ctx.send(Lang.get_locale_string("word_counter/no_words", ctx))

    @word_counter.command(aliases=["new"])
    @commands.guild_only()
    async def add(self, ctx: commands.Context, *, word: str):
        """command_add_help"""
        row = await CountWord.get_or_none(serverid=ctx.guild.id, word=word)
        if row is None:
            await CountWord.create(serverid=ctx.guild.id, word=word)
            await self.init_guild(ctx.guild)
            emoji = Emoji.get_chat_emoji('YES')
            msg = Lang.get_locale_string('word_counter/word_added', ctx, word=word)
            await ctx.send(f"{emoji} {msg}")
        else:
            await ctx.send(Lang.get_locale_string('word_counter/word_found', ctx, word=word))

    @word_counter.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx:commands.Context, *, word):
        """command_remove_help"""
        row = await CountWord.get_or_none(serverid=ctx.guild.id, word=word)
        if row is not None:
            await row.delete()
            await self.init_guild(ctx.guild)
            emoji = Emoji.get_chat_emoji('YES')
            msg = Lang.get_locale_string('word_counter/word_removed', ctx, word=word)
        else:
            emoji = Emoji.get_chat_emoji('NO')
            msg = Lang.get_locale_string('word_counter/word_not_found', ctx, word=word)
        await ctx.send(f"{emoji} {msg}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        prefix = Configuration.get_var("bot_prefix")
        ctx = await self.bot.get_context(message)
        is_boss = await self.cog_check(ctx)
        command_context = message.content.startswith(prefix, 0) and is_boss
        not_in_guild = not hasattr(message.channel, "guild") or message.channel.guild is None

        if command_context or not_in_guild:
            return

        m = self.bot.metrics
        try:
            pattern = re.compile(self.words[message.guild.id], re.IGNORECASE)
            # find all matches and reduce to unique set
            words = set(pattern.findall(message.content))
            for word in words:
                # increment counters
                word = str(word).lower()
                m.word_counter.labels(word=word, guild_name=message.guild.name, guild_id=message.guild.id).inc()
        except KeyError:
            # Guild not present or not initialized. Ignore.
            pass


async def setup(bot):
    await bot.add_cog(WordCounter(bot))
