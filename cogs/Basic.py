import time
import typing
from typing import Optional, Literal

import discord
from discord import app_commands, InteractionResponse, Interaction, Permissions
from discord.app_commands import Group
from discord.ext.commands import Context, hybrid_command, Greedy, is_owner, guild_only, command
from datetime import datetime

from cogs.BaseCog import BaseCog
from utils import Utils


class Basic(BaseCog):
    Sync_Current = "Current"
    Sync_GlobalToLocal = "Global to Local"
    Sync_ClearTree = "Clear Commands"

    async def cog_check(self, ctx):
        return await Utils.permission_official_mute(ctx)

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

    @command()
    async def now(self, ctx, request_formats: str = "f"):
        """Print timestamp for current time. TODO: print timestamp for a given datetime or offset

        Parameters
        ----------
        ctx
        request_formats
            The formats you want to see. Available formats: `dDtTfFRs`
        """
        if ctx.author.bot or not await Utils.can_mod_official(ctx):
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

        await ctx.send(output)

    @guild_only()
    @is_owner()
    @hybrid_command(aliases=["sync"])
    async def app_command_sync(
            self,
            ctx: Context,
            guilds: Greedy[discord.Object] = None,
            spec: Optional[
                Literal[Sync_Current, Sync_GlobalToLocal, Sync_ClearTree]] = None) -> None:
        """
        Sync commands by guild or globally

        Parameters
        -----------
        ctx
        guilds: list
            List of guilds to sync. Omit for global sync
        spec: str
            Override sync type. `Current`, `Global to Local`, or `Clear Commands`"""
        if not guilds:
            if spec == self.Sync_Current:
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == self.Sync_GlobalToLocal:
                ctx.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == self.Sync_ClearTree:
                ctx.bot.tree.clear_commands(guild=ctx.guild)
                await ctx.bot.tree.sync(guild=ctx.guild)
                synced = []
            else:
                synced = await ctx.bot.tree.sync()

            await ctx.send(
                f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}"
            )
            return

        ret = 0
        for guild in guilds:
            try:
                await ctx.bot.tree.sync(guild=guild)
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
    #     r = typing.cast(InteractionResponse, interaction.response)
    #     await r.send_message(f"bop {member.mention}")
    #
    # @fun_group.command(description="Unbops a member")
    # @app_commands.describe(member="The member to unbop")
    # async def unbop(self, interaction: Interaction, member: discord.Member):
    #     r = typing.cast(InteractionResponse, interaction.response)
    #     await r.send_message(f"unbop {member.mention}")
    #
    # @subgroup.command(description="Slaps a member")
    # @app_commands.describe(member="the member to slap")
    # async def botslap(self, interaction: Interaction, member: discord.Member):
    #     r = typing.cast(InteractionResponse, interaction.response)
    #     await r.send_message(f"botslap {member.mention}")
    ####


async def setup(bot):
    await bot.add_cog(Basic(bot))
