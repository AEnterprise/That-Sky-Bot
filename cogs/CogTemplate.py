import asyncio

import discord
from discord.ext import commands, tasks

from cogs.BaseCog import BaseCog
from utils import Logging
from utils.Logging import TCol


class CogName(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.guild_specific_lists = dict()

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        # initialize anything that should happen before login
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        for guild in self.bot.guilds:
            await self.init_guild(guild)
        if not self.periodic_task.is_running():
            self.periodic_task.start()

    async def shutdown(self):
        """
        Called before cog_unload, only when shutting down bot. Custom to this bot.
        """
        Logging.info(f"{self.qualified_name} shutdown", TCol.Underline, TCol.Header)

    async def cog_unload(self):
        self.periodic_task.cancel()

    async def init_guild(self, guild):
        # init guild-specific dicts and lists
        self.guild_specific_lists[guild.id] = []
        pass

    @tasks.loop(seconds=60)
    async def periodic_task(self):
        # periodic task to run while cog is loaded
        pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        # delete guild-specific dicts and lists, remove persistent vars, clean db
        del self.guild_specific_lists[guild.id]
        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # do something with messages
        pass


async def setup(bot):
    await bot.add_cog(CogName(bot))

async def teardown(bot):
    Logging.info("Cog teardown", TCol.Underline, TCol.Header)
