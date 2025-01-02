import time
import typing
from datetime import datetime
from enum import Enum
from typing import Optional

import discord
from discord import app_commands, InteractionResponse, Interaction
from discord.ext.commands import Context, Greedy, is_owner, guild_only, command

from cogs.BaseCog import BaseCog
from utils import Utils, Logging
from utils.Logging import TCol
from utils.Utils import interaction_response


class SyncValues(Enum):
    Current ="~"
    GlobalToLocal = "*"
    ClearTree = "^"

class Basic(BaseCog):

    async def cog_check(self, ctx):
        return await Utils.permission_official_mute(ctx)

    async def cog_unload(self):
        Logging.info("unload Basic", TCol.Cyan)

    async def cog_load(self):
        Logging.info("load Basic", TCol.Cyan)

    @command(aliases=["ping"], hidden=True)
    async def ping_pong(self, ctx: Context):
        """show ping times"""
        t1 = time.perf_counter()
        message = await ctx.send(":ping_pong:")
        t2 = time.perf_counter()
        rest = round((t2 - t1) * 1000)
        latency = round(self.bot.latency * 1000, 2)
        edited_message = await message.edit(
            content=f":hourglass: REST API ping is {rest} ms | Websocket ping is {latency} ms :hourglass:")

    @app_commands.command(description="Get discord time stamps")
    @app_commands.describe(request_formats="Available formats: d D t T f F R s")
    @guild_only()
    async def timestamp(
            self,
            interaction: Interaction,
            request_formats: str = ""):
        """Print timestamp for current time. TODO: print timestamp for a given datetime or offset

        Parameters
        ----------
        interaction
        request_formats
            Available formats: d D t T f F R s
        """
        if interaction.user.bot:
            return

        now = int(datetime.now().timestamp())
        formats = {
            'd': f"<t:{now}:d>",
            'D': f"<t:{now}:D>",
            't': f"<t:{now}:t>",
            'T': f"<t:{now}:T>",
            'f': f"<t:{now}:f>",
            'F': f"<t:{now}:F>",
            'R': f"<t:{now}:R>",
            's': f"{now}"
        }
        dates_formatted = []

        format_requested = False
        for arg in set(request_formats):
            if arg in formats:
                dates_formatted.append(f"`{formats[arg]}` {formats[arg]}")
                format_requested = True

        if not format_requested:
            for arg in formats:
                dates_formatted.append(f"`{formats[arg]}` {formats[arg]}")

        if dates_formatted:
            output = "\n".join(dates_formatted)
        else:
            output = "No valid format requested"

        await interaction_response(interaction).send_message(output, ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command()
    @app_commands.default_permissions(manage_channels=True)
    async def sync_app_commands(
            self,
            interaction: Interaction,
            operation: Optional[SyncValues],
            guild: str = None) -> None:
        ctx = await Context.from_interaction(interaction)

        if not await self.bot.is_owner(interaction.user):
            # Permissions prevent most from seeing the command, but owner is required
            await interaction_response(interaction).send_message(f"you're not <@{self.bot.owner_id}>,  you can't do that!")
            return

        guilds = []
        if ctx.valid:
            if guild:
                for candidate_guild in self.bot.guilds:
                    if candidate_guild.name == guild:
                        guilds.append(candidate_guild.id)
            await self.do_sync(ctx, guilds=guilds, spec=operation.value if operation else "")
        else:
            await interaction_response(interaction).send_message("can't sync from here")

    @sync_app_commands.autocomplete('guild')
    async def guild_autocomplete(
            self,
            interaction: discord.Interaction,
            current: str) -> typing.List[app_commands.Choice[str]]:
        guilds = [guild for guild in self.bot.guilds]
        ret = [
            app_commands.Choice(name=guild.name, value=guild.name)
            for guild in guilds if current.lower() in guild.name.lower()
        ]
        return ret

    @is_owner()
    @guild_only()
    @command(aliases=["sync"])
    async def app_command_sync(
            self,
            ctx: Context,
            guilds: Greedy[discord.Object] = None,
            spec: Optional[SyncValues] = None) -> None:
        """
        Sync commands by guild or globally

        Parameters
        -----------
        ctx
        guilds: list
            Guilds to sync. Omit for global sync
        spec: str
            Sync type: [~]current [*]global to local [^]clear tree"""
        validated_guilds = []
        # Logging.info("guilds: "+repr(guilds))
        if guilds:
            for i in guilds:
                validated_guilds.append(i.id)
        # Logging.info("my_guilds: "+repr(validated_guilds))
        # Logging.info("spec: "+repr(spec))
        await self.do_sync(ctx, validated_guilds, spec.value if spec else '')

    async def do_sync(self, ctx, guilds: typing.List[int] = None, spec: str = "") -> None:
        if not guilds:
            if spec == SyncValues.Current.value:
                synced = await self.bot.tree.sync(guild=ctx.guild)
            elif spec == SyncValues.GlobalToLocal.value:
                self.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await self.bot.tree.sync(guild=ctx.guild)
            elif spec == SyncValues.ClearTree.value:
                self.bot.tree.clear_commands(guild=ctx.guild)
                await self.bot.tree.sync(guild=ctx.guild)
                synced = []
            else:
                synced = await self.bot.tree.sync()

            await ctx.send(
                f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}"
            )
            return

        ret = 0
        Logging.info("do guilds: " + repr(guilds))
        for guild_id in guilds:
            try:
                a_guild = self.bot.get_guild(guild_id)
                if a_guild is None or a_guild not in self.bot.guilds:
                    continue
                await self.bot.tree.sync(guild=a_guild)
            except discord.HTTPException:
                pass
            else:
                ret += 1

        await ctx.send(f"Synced the tree to {ret}/{len(guilds)}.")

    ####
    # app command groups
    # fun_group = Group(
    #     name='fun',
    #     description='Reaction controls',
    #     default_permissions=Permissions(ban_members=True))
    #
    # subgroup = Group(parent=fun_group, name='unfun', description='sub group?')
    #
    # @fun_group.command(description="Bops a member")
    # @app_commands.describe(member="The member to bop")
    # async def bop(self, interaction: Interaction, member: discord.Member):
    #     await interaction_response(interaction).send_message(f"bop {member.mention}")
    #
    # @fun_group.command(description="Unbops a member")
    # @app_commands.describe(member="The member to unbop")
    # async def unbop(self, interaction: Interaction, member: discord.Member):
    #     await interaction_response(interaction).send_message(f"unbop {member.mention}")
    #
    # @subgroup.command(description="Slaps a member")
    # @app_commands.describe(member="the member to slap")
    # async def botslap(self, interaction: Interaction, member: discord.Member):
    #     await interaction_response(interaction).send_message(f"botslap {member.mention}")
    ####


async def setup(bot):
    await bot.add_cog(Basic(bot))
