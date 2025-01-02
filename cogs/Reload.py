import asyncio
import importlib
import os
from itertools import islice
from typing import List

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded, ExtensionFailed, ExtensionNotFound, NoEntryPointError, \
    ExtensionAlreadyLoaded

from cogs.BaseCog import BaseCog
from utils import Logging, Emoji, Reloader, Utils, Configuration, Lang
from utils.Helper import Sender
from utils.Logging import TCol
from utils.Utils import check_is_owner, interaction_response


class Reload(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)

    async def cog_check(self, ctx):
        return await Utils.permission_manage_bot(ctx)

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
                await Utils.handle_exception("Reload after_ready exception", e)
                pass

    @app_commands.command(name="reload")
    @app_commands.describe(module="The cog to reload")
    @app_commands.check(check_is_owner)
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    async def reload_cog(self, interaction: discord.Interaction, module: str):
        """Reload the specified module"""
        sender = Sender(interaction)
        cog = module

        await interaction_response(interaction).defer() # thinking...

        if cog in self.bot.cogs:
            complete = False
            msg = ''

            try:
                Logging.info(f"trying to reload {cog}...")
                Logging.info(f"\t{TCol.Warning.value}Shutting down{TCol.End.value} cog {TCol.Cyan.value}{cog}{TCol.End.value}")
                if hasattr(cog, "shutdown"):
                    await cog.shutdown()
                await self.bot.reload_extension(f"cogs.{cog}")
            except ExtensionNotLoaded:
                msg = f"\t{cog} isn't loaded, can't reload."
            except ExtensionFailed as e:
                msg = f"\t**{cog}** failed while loading... {e}"
            except NoEntryPointError:
                msg = f"\t{cog} has no setup method."
            except ExtensionNotFound:
                msg = f"\t**{cog}** not found."
            else:
                complete = True
                msg = f'**{cog}** was reloaded by {interaction.user.name}'
                await Logging.bot_log(msg)
            finally:
                if complete:
                    await sender.send(msg, ephemeral=True)
        else:
            await sender.send(f"{Emoji.get_chat_emoji('NO')} I can't find that cog.", ephemeral=True)

    @reload_cog.autocomplete('module')
    async def module_autocomplete(
            self,
            interaction: discord.Interaction,
            current: str) -> List[app_commands.Choice[str]]:

        if not check_is_owner(interaction):
            return []

        cogs = list(self.bot.cogs.keys())

        # generator for all cog names:
        all_matching_commands = (i for i in cogs if current.lower() in i.lower())
        # islice to limit to 25 options (discord API limit)
        some_cogs = list(islice(all_matching_commands, 25))
        some_cogs.sort()
        # convert matched list into list of choices
        ret = [app_commands.Choice(name=c, value=c) for c in some_cogs]
        return ret

    @commands.command()
    async def reload(self, ctx, *, cog: str):
        """
        Reload a cog

        Be sure that cog has no unsaved data, in-progress uses, etc. or is just so borked that it needs to be kicked
        cog: The name of the cog to reload
        """
        if cog in self.bot.cogs:
            try:
                Logging.info(f"trying to reload {cog}...")
                Logging.info(f"\t{TCol.Warning.value}Shutting down{TCol.End.value} cog {TCol.Cyan.value}{cog}{TCol.End.value}")
                if hasattr(cog, "shutdown"):
                    await cog.shutdown()
                await self.bot.reload_extension(f"cogs.{cog}")
            except ExtensionNotLoaded:
                Logging.info(f"\t{cog} isn't loaded, can't reload...")
                await ctx.send(f'**{cog}** did not load.')
            except ExtensionFailed as e:
                Logging.info(f"\t{cog} failed while loading... {e}")
                await ctx.send(f'**{cog}** failed while loading.')
            except NoEntryPointError:
                Logging.info(f"\t{cog} has no setup method?...")
                await ctx.send(f'**{cog}** has no setup method.')
            except ExtensionNotFound:
                Logging.info(f"\t{cog} not found...")
                await ctx.send(f'**{cog}** not found.')
            else:
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
