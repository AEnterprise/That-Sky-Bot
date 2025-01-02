import asyncio

import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Lang, Logging
from utils import Utils
from utils.Database import Guild, BotAdmin
from utils.Logging import TCol


class PermissionConfig(BaseCog):
    def __init__(self, bot):
        self.admin_roles = dict()
        self.mod_roles = dict()
        self.trusted_roles = dict()
        self.command_permissions = dict()
        self.after_ready_task = None
        super().__init__(bot)

    async def cog_unload(self):
        await self.after_ready_task

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        self.after_ready_task = asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        for guild in self.bot.guilds:
            self.init_guild(guild)
        for guild in self.bot.guilds:
            await self.load_guild(guild)

    def init_guild(self, guild):
        self.admin_roles[guild.id] = set()
        self.mod_roles[guild.id] = set()
        self.trusted_roles[guild.id] = set()
        self.command_permissions[guild.id] = dict()

    async def load_guild(self, guild):
        guild_row, created = await Guild.get_or_create(serverid=guild.id)
        try:
            for row in await guild_row.admin_roles:
                role = guild.get_role(row.roleid)
                if role:
                    self.admin_roles[guild.id].add(role.id)
                else:
                    await row.delete()
            for row in await guild_row.mod_roles:
                role = guild.get_role(row.roleid)
                if role:
                    self.mod_roles[guild.id].add(role.id)
                else:
                    await row.delete()
            for row in await guild_row.trusted_roles:
                role = guild.get_role(row.roleid)
                if role:
                    self.trusted_roles[guild.id].add(role.id)
                else:
                    await row.delete()
            for row in await guild_row.command_permissions:
                member = guild.get_member(row.userid)
                if member:
                    self.command_permissions[guild.id][member.id] = row
                else:
                    await row.delete()
        except KeyError:
            Logging.info(f"Role loading failed in {guild.id}", TCol.Fail)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.admin_roles[guild.id]
        del self.mod_roles[guild.id]
        del self.trusted_roles[guild.id]
        del self.command_permissions[guild.id]

        # remove all configured guild permissions
        guild_row = await self.bot.get_guild_db_config(guild.id)
        await guild_row.admin_roles.filter().delete()
        await guild_row.mod_roles.filter().delete()
        await guild_row.trusted_roles.filter().delete()
        await guild_row.command_permissions.filter().delete()

    async def cog_check(self, ctx):
        # Minimum permission for all permissions commands: manage_server
        if ctx.guild:
            if ctx.author.guild_permissions.manage_guild or await Utils.permission_manage_bot(ctx):
                return True
            for role in ctx.author.roles:
                if role.id in self.admin_roles[ctx.guild.id]:
                    return True
        if await Utils.permission_manage_bot(ctx):
            return True
        return False

    @commands.group(name="permission_config", aliases=["permission", "permissions"], invoke_without_command=True)
    @commands.guild_only()
    async def permission_config(self, ctx):
        is_bot_admin = await Utils.permission_manage_bot(ctx)

        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("permission_config/info", ctx, server_name=ctx.guild.name))
        embed.add_field(name='Configurable Permissions',
                        value=f"Trusted Roles, Mod Roles, Admin Roles{', Bot Admins' if is_bot_admin else ''}",
                        inline=False)

        admin_roles = set()
        mod_roles = set()
        trusted_roles = set()
        user_permissions = set()

        guild_row = await Guild.get(serverid=ctx.guild.id)

        for row in await guild_row.admin_roles:
            role = ctx.guild.get_role(row.roleid)
            if role:
                admin_roles.add(role.mention)
        for row in await guild_row.mod_roles:
            role = ctx.guild.get_role(row.roleid)
            if role:
                mod_roles.add(role.mention)
        for row in await guild_row.trusted_roles:
            role = ctx.guild.get_role(row.roleid)
            if role:
                trusted_roles.add(role.mention)
        for row in await guild_row.command_permissions:
            member = ctx.guild.get_member(row.userid)
            if member:
                member_desc = Utils.get_member_log_name(member)
                desc = f"{member_desc} - `{'ALLOW' if row.allow else 'DENY'}`: `{row.command}`"
                user_permissions.add(desc)

        no_roles_string = "None"

        embed.add_field(name="Admin Roles", value='\n'.join(admin_roles) if len(admin_roles) > 0 else no_roles_string, inline=False)
        embed.add_field(name="Mod Roles", value='\n'.join(mod_roles) if len(mod_roles) > 0 else no_roles_string, inline=False)
        embed.add_field(name="Trusted Roles", value='\n'.join(trusted_roles) if len(trusted_roles) > 0 else no_roles_string, inline=False)
        embed.add_field(name="User Permissions", value='\n'.join(user_permissions) if len(user_permissions) > 0 else no_roles_string, inline=False)

        if is_bot_admin:
            bot_admins = set()
            for row in await BotAdmin.all():
                user = self.bot.get_user(row.userid)
                bot_admins.add(f"{user.mention} {str(user)} ({user.id})")
            embed.add_field(name="Bot Admins", value='\n'.join(bot_admins) if len(bot_admins) > 0 else no_roles_string, inline=False)

        await ctx.send(embed=embed)

    @permission_config.command()
    @commands.is_owner()
    @commands.guild_only()
    async def reload(self, ctx: commands.Context):
        await self.cog_load()
        await ctx.send("reloaded permissions from db...")
        await ctx.invoke(self.permission_config)

    # TODO: set user permission
    # TODO: add role to [admin|mod|trusted]
    # TODO: add user to bot_admins


async def setup(bot):
    await bot.add_cog(PermissionConfig(bot))
