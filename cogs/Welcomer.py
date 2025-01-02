import asyncio
import io
import re
import typing
from datetime import datetime

import discord
import requests
from discord.ext import commands
from discord.ext.commands import MemberConverter

from cogs.BaseCog import BaseCog
from utils import Logging, Utils, Lang


class Welcomer(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)

    def cog_unload(self):
        pass

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

    async def init_guild(self, guild):
        pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        pass

    async def cog_check(self, ctx):
        return await Utils.permission_manage_bot(ctx) or (ctx.guild and ctx.author.guild_permissions.ban_members)

    @commands.group(name="welcome", invoke_without_command=True)
    @commands.guild_only()
    async def welcome(self, ctx):
        """Configure welcome message settings"""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @welcome.command(aliases=['verify'])
    @commands.guild_only()
    @commands.check(Utils.permission_manage_bot)
    async def verify_invited(self, ctx, *, member_list=""):
        async with ctx.channel.typing():
            await ctx.send("This might take a while. rate limiting stops me searching all members quickly...")
            attachment_links = [str(a.url) for a in ctx.message.attachments]
            if attachment_links:
                if len(attachment_links) != 1:
                    await ctx.send(f"I can only handle one attachment for this command (or past in a list of names)")
                    return
                url = str(attachment_links[0])
                # download attachment and put it in a buffer
                u = requests.get(url)
                buffer = io.BytesIO()
                buffer.write(u.content)
                buffer.seek(0)  # start reading at the beginning
                with buffer as f:
                    names = [i.decode('UTF-8').strip() for i in f.readlines()]
            else:
                names = [i.strip() for i in member_list.splitlines()]

            members = []
            my_converter = MemberConverter()
            for name in names:
                try:
                    a_member = await my_converter.convert(ctx, name)
                    members.append(a_member)
                except Exception as e:
                    pass

            sus = []
            for member in ctx.guild.members:
                if member not in members:
                    sus.append(member)

            if not members:
                await ctx.send("You didn't give me any names to check. Try again with a list or file")
                return

            if sus:
                sus_list = [f"{member.display_name}#{member.discriminator} ({member.id})" for member in sus]
                sus_list = '\n'.join(sus_list)
                buffer = io.StringIO()
                buffer.write(sus_list)
                buffer.seek(0)

                await ctx.send(
                    content=f"yo, these members aren't on the approved list",
                    file=discord.File(buffer, f"impostors.txt"))
            else:
                await ctx.send("OMG, nobody sneaked into the server while I wasn't looking!")

    # TODO:
    #  store members invites
    #  store verified members
    #  match invites to verified members

    # @welcome.group(name="members", invoke_without_command=True)
    # @commands.guild_only()
    # @commands.check(Utils.permission_manage_bot)
    # async def members(self, ctx):
    #     # todo: list?
    #     pass
    #
    # @members.command()
    # @commands.guild_only()
    # @commands.check(Utils.permission_manage_bot)
    # async def remove(self, ctx, *, member_list):
    #     # todo: add individual by br-separated list, one, or by csv
    #     pass
    #
    # @members.command()
    # @commands.guild_only()
    # @commands.check(Utils.permission_manage_bot)
    # async def verify(self, ctx, *, member_list):
    #     # todo: add individual by br-separated list, one, or by csv
    #     pass
    #
    # @members.command()
    # @commands.guild_only()
    # @commands.check(Utils.permission_manage_bot)
    # async def verify_all(self, ctx):
    #     # todo: check all members whether they are on the list
    #     pass

    @welcome.command(aliases=["list", "muted"])
    @commands.guild_only()
    async def list_muted(self, ctx):
        """
        List muted members
        """
        guild_row = await self.bot.get_guild_db_config(ctx.guild.id)
        muted_role = ctx.guild.get_role(guild_row.mutedrole)
        untracked_mute = []
        for member in ctx.guild.members:
            if muted_role in member.roles:
                untracked_mute.append(Utils.get_member_log_name(member))
        if untracked_mute:
            msg = '\n'.join(untracked_mute)
            pages = Utils.paginate(msg)
            await ctx.send(f"**Members who are muted:**")
            for page in pages:
                await ctx.send(page)
        else:
            await ctx.send("I found no muted members.")

    @welcome.command(aliases=["shadows", "count_nonmembers"])
    @commands.guild_only()
    async def count_shadows(self, ctx):
        """
        Count members who have shadow role
        """
        members = self.bot.get_all_members()

        guild_row = await self.bot.get_guild_db_config(ctx.guild.id)
        nonmember_role = ctx.guild.get_role(guild_row.nonmemberrole)

        await ctx.send(f"counting members who have the shadow role...")
        count = 0
        multi_role_count = 0
        no_role_count = 0
        for member in members:
            if member.bot or member.guild.id != ctx.guild.id:
                # Don't count bots or members of other guilds
                continue

            # @everyone counts as a role
            if len(member.roles) == 1:
                no_role_count += 1

            if nonmember_role in member.roles:
                count = count + 1
                if len(member.roles) > 2:
                    # count members who have shadow role AND other role(s)
                    multi_role_count = multi_role_count + 1

        content = f"There are {count} members with \"{nonmember_role.name}\" role.\n"
        content += f"Among them, {multi_role_count} members have \"{nonmember_role.name}\" role *and* 1 or more other roles.\n"
        content += f"There are {no_role_count} members with no roles assigned."
        await ctx.send(content)

    @welcome.command()
    @commands.guild_only()
    async def darkness(self, ctx, time_delta: typing.Optional[int] = 1):
        """
        Add non-member role to members with no role

        time_delta: how far back (in days) to search for members with no roles
        add_role:
        """
        members = self.bot.get_all_members()
        no_role_members = []
        recent = []
        too_old = []
        now = datetime.now().timestamp()
        then = now - (time_delta * 60 * 60 * 24)

        for member in members:
            if member.bot or member.guild.id != ctx.guild.id:
                # Don't count bots or members of other guilds
                continue

            # @everyone counts as a role
            if len(member.roles) == 1:
                no_role_members.append(member)

                if member.joined_at.timestamp() > then:
                    # Joined within {time_delta} days and has no role
                    recent.append(member)
                else:
                    # Joined more than {time_delta} days ago and has no role
                    too_old.append(member)

        string_name = 'welcome/darkness' if (len(recent) == 1) else 'welcome/darkness_plural'
        await ctx.send(Lang.get_locale_string(string_name, ctx,
                                              unverified=len(recent),
                                              too_old=len(too_old)))

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
            if before.pending and not after.pending:
                # TODO: metrics logging?
                # member just accepted rules
                # don't add a role or this defeats security.
                pass

            # Only act if roles change, in case other bot (e.g. yagpdb.xyz) assigns a role.
            if before.roles != after.roles:
                # TODO: should this be configurable on|off?
                guild_row = await self.bot.get_guild_db_config(before.guild.id)
                member_role = before.guild.get_role(guild_row.memberrole)

                if member_role is None:
                    return

                member_after = member_role in after.roles

                # @everyone counts as 1 role
                has_no_roles = len(after.roles) == 1

                # No member role but at least 1 other role? add member role.
                if not has_no_roles and not member_after:
                    await after.add_roles(member_role)
        except Exception as e:
            await Utils.handle_exception("problem enforcing member role", e)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        pass

    @commands.Cog.listener()
    async def on_member_join(self, member):
        pass

    async def member_completed_join(self, member):
        # member role is already given by reaction handler
        # nonmember role is already taken by reaction handler
        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not hasattr(message.author, "guild"):
            return

        guild_row = await self.bot.get_guild_db_config(message.guild.id)
        log_channel = await Utils.get_guild_log_channel(message.guild.id)
        member_role = message.guild.get_role(guild_row.memberrole)
        nonmember_role = message.guild.get_role(guild_row.nonmemberrole)

        if message.author.id == 349977940198555660:  # is gearbot
            pattern = re.compile(r'\(``(\d+)``\) has re-joined the server before their mute expired')
            match = re.search(pattern, message.content)
            if match:
                user_id = int(match[1])
                # gearbot is handling it. never unmute this user
                muted_member = message.guild.get_member(user_id)
                muted_member_name = Utils.get_member_log_name(muted_member)
                await log_channel.send(
                    f'''
                    Gearbot re-applied mute when member re-joined: {muted_member_name}
                    I won't try to unmute them later.
                    ''')
                return

        if message.author.guild_permissions.mute_members or await self.bot.member_is_admin(message.author.id) or \
                (member_role is not None and member_role in message.author.roles):
            # is a mod or
            # message from regular member. no action to take.
            return

        if member_role is not None and member_role not in message.author.roles:
            # nonmember speaking somewhere other than welcome channel? Maybe we're not using the
            # welcome channel anymore? or something else went wrong... give them member role.
            try:
                await message.author.add_roles(member_role)
                if nonmember_role is not None and nonmember_role in message.author.roles:
                    Logging.info(f"{Utils.get_member_log_name(message.author)} - had shadow role when speaking. removing it!")
                    await message.author.remove_roles(nonmember_role)
            except Exception as e:
                try:
                    Logging.info(f"member join exception message: {message.content}")
                    Logging.info(f"member join exception user id: {message.author.id}")
                except Exception as ee:
                    pass
                await Utils.handle_exception("member join exception", e)


async def setup(bot):
    await bot.add_cog(Welcomer(bot))
