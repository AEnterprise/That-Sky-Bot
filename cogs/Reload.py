import asyncio
import importlib
import os

from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded, ExtensionFailed, ExtensionNotFound, NoEntryPointError, \
    ExtensionAlreadyLoaded

from cogs.BaseCog import BaseCog
from utils import Logging, Emoji, Reloader, Utils, Configuration, Lang


class Reload(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)

    async def cog_check(self, ctx):
        return await self.bot.permission_manage_bot(ctx)

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")

        restart_mid = Configuration.get_persistent_var("bot_restart_message_id")
        restart_cid = Configuration.get_persistent_var("bot_restart_channel_id")
        author_id = Configuration.get_persistent_var("bot_restart_author_id")
        Configuration.del_persistent_var("bot_restart_message_id", True)
        Configuration.del_persistent_var("bot_restart_channel_id", True)
        Configuration.del_persistent_var("bot_restart_author_id", True)
        # TODO: write pop_persistent_var
        if restart_cid and restart_mid:
            try:
                channel = self.bot.get_channel(restart_cid)
                message = await channel.fetch_message(restart_mid)
                author = self.bot.get_user(author_id)
                await message.edit(content=f"Restart complete {author.mention}")
            except Exception as e:
                await Utils.handle_exception("Reload after_ready exception", self.bot, e)
                pass

    @commands.command()
    async def reload(self, ctx, *, cog: str):
        """
        Reload a cog

        Be sure that cog has no unsaved data, in-progress uses, etc. or is just so borked that it needs to be kicked
        cog: The name of the cog to reload
        """
        if cog in self.bot.cogs:
            try:
                await self.bot.reload_extension(f"cogs.{cog}")
            except ExtensionNotLoaded:
                await ctx.send(f'**{cog}** did not load.')
                return
            except ExtensionFailed:
                await ctx.send(f'**{cog}** failed while loading.')
                return
            except NoEntryPointError:
                await ctx.send(f'**{cog}** has no setup method.')
                return
            except ExtensionNotFound:
                await ctx.send(f'**{cog}** not found.')
                return

            await ctx.send(f'**{cog}** has been reloaded.')
            await Logging.bot_log(f'**{cog}** has been reloaded by {ctx.author.name}.')
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} I can't find that cog.")

    @commands.command()
    async def reload_lang(self, ctx):
        """
        Reload localization files
        """
        Lang.load()
        await ctx.send("Language file reloaded")

    @commands.command()
    async def reload_config(self, ctx):
        """
        Reload configuration from disk
        """
        Configuration.load()
        await ctx.send("Config file reloaded")

    @commands.command()
    async def load(self, ctx, cog: str):
        """
        Load a cog

        cog: Name of the cog to load
        """
        if os.path.isfile(f"cogs/{cog}.py"):
            try:
                await self.bot.load_extension(f"cogs.{cog}")
            except ExtensionNotLoaded:
                await ctx.send(f'**{cog}** did not load.')
                return
            except ExtensionFailed:
                await ctx.send(f'**{cog}** failed while loading.')
                return
            except NoEntryPointError:
                await ctx.send(f'**{cog}** has no setup method.')
                return
            except ExtensionNotFound:
                await ctx.send(f'**{cog}** not found.')
                return
            except ExtensionAlreadyLoaded:
                await ctx.send(f'**{cog}** is already loaded.')
                return

            if cog not in Configuration.MASTER_CONFIG["cogs"]:
                Configuration.MASTER_CONFIG["cogs"].append(cog)
                Configuration.save()

            await ctx.send(f"**{cog}** has been loaded!")
            await Logging.bot_log(f"**{cog}** has been loaded by {ctx.author.name}.")
            Logging.info(f"{cog} has been loaded")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} I can't find that cog.")

    @commands.command()
    async def unload(self, ctx, cog: str):
        """
        Unload a cog

        cog: Name of the cog to unload
        """
        if cog in ctx.bot.cogs:
            await self.bot.unload_extension(f"cogs.{cog}")
            if cog in Configuration.MASTER_CONFIG["cogs"]:
                Configuration.get_var("cogs").remove(cog)
                Configuration.save()
            await ctx.send(f'**{cog}** has been unloaded.')
            await Logging.bot_log(f'**{cog}** has been unloaded by {ctx.author.name}')
            Logging.info(f"{cog} has been unloaded")
        else:
            await ctx.send(f"{Emoji.get_chat_emoji('NO')} I can't find that cog.")

    @commands.command()
    async def hotreload(self, ctx):
        """
        Reload all cogs
        """
        message = await ctx.send("Hot reloading...")
        importlib.reload(Reloader)
        for c in Reloader.components:
            importlib.reload(c)
        Emoji.initialize(self.bot)
        Logging.info("Reloading all cogs...")
        temp = []
        for cog in self.bot.cogs:
            temp.append(cog)
        for cog in temp:
            await self.bot.unload_extension(f"cogs.{cog}")
            Logging.info(f'{cog} has been unloaded.')
            await self.bot.load_extension(f"cogs.{cog}")
            Logging.info(f'{cog} has been loaded.')

        await message.edit(content="Hot reload complete")

    @commands.command()
    @commands.check(Utils.can_mod_official)
    async def restart(self, ctx):
        """Restart the bot"""
        shutdown_message = await ctx.send("Restarting...")
        if shutdown_message:
            cid = shutdown_message.channel.id
            mid = shutdown_message.id
            Configuration.set_persistent_var("bot_restart_channel_id", cid)
            Configuration.set_persistent_var("bot_restart_message_id", mid)
            Configuration.set_persistent_var("bot_restart_author_id", ctx.author.id)
        await self.bot.close()


async def setup(bot):
    await bot.add_cog(Reload(bot))
