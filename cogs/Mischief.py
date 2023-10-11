import asyncio
import re
from datetime import datetime
from random import random, choice

import discord
import tortoise
from discord import AllowedMentions
from discord.ext import commands, tasks
from discord.ext.commands import BucketType

import utils.Utils
from cogs.BaseCog import BaseCog
from utils import Utils, Configuration, Logging
from utils.Database import MischiefRole


class Mischief(BaseCog):
    me_again = "me again"
    mischief_names = [
      "Cackling {name}",
      "Crabby {name}!",
      "Krilled {name}",
      "Spirit {name}",
      "Eye of {name}",
      "Spooky McSpooky {name}",
      "Dark {name}",
      "Corrupted {name}",
      "Shattered {name}",
      "LOCALIZE {name}",
      "QUEST_NIGHT_{name}",
      "{name}'s broken reflection",
      "{name} spoke too soon",
      "{name} splashed with dark water",
      "{name} look behind you",
      "{name} destroyer of candles",
      "{name} [0 cosmetics]",
      "{name} hoarder of candles",
      "{name} is stormlocked",
      "shard landed on {name}",
      "{name} oobed too deep",
      "{name} fell into GW",
      "Extinguished {name}",
      "crab{name}",
      "trick or {name}",
      "the spirit of {name}",
      "{name} got mantalulled",
      "{name} is behind you",
      "a curse upon {name}",
      "{name} the terrible",
      "{name} the horrible",
      "fear the {name}",
      "{name} [0 candles]",
      "Regrettable {name}",
      "{name} scissorhands",
      "{name} saladfingers",
      "{name} of the night",
      "{name} is one candle short",
      "{name} is krill certified",
      "{name} got server split",
      "{name} crashed in Eden",
      "Honking {name}",
      "Beaned {name}",
      "{name} missed 1 Eden Statue",
      "{name} the arsonist",
      "{name} is a toilet krill",
      "{name} has treats!",
      "{name} should be feared",
      "spooky scary {name}",
      "{name} steals candy from skykids",
      "{name} is looking for spells",
      "oh no, a ghost! {name}!",
      "{name} is a treat for the krills",
      "{name} cast a spell on Skybot",
      "{name} has released the crabs",
      "{name} the crab roaster",
      "{name} became krillbait"
    ]

    def __init__(self, bot):
        super().__init__(bot)
        self.cooldown_time = 600.0
        self.name_mischief_chance = 0.0
        self.name_cooldown_time = 60.0
        self.name_cooldown = dict()
        self.mischief_map = dict()
        self.role_counts = dict()

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        self.name_cooldown_time = float(Configuration.get_persistent_var("name_mischief_cooldown", 10.0))
        self.name_mischief_chance = float(Configuration.get_persistent_var("name_mischief_chance", 0.01))
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        for guild in self.bot.guilds:
            await self.init_guild(guild)

        if not self.role_count_task.is_running():
            self.role_count_task.start()
        if not self.name_task.is_running():
            self.name_task.start()

    def cog_unload(self):
        self.role_count_task.cancel()
        self.name_task.cancel()

    async def init_guild(self, guild):
        self.name_cooldown[str(guild.id)] = Configuration.get_persistent_var(f"name_cooldown_{guild.id}", dict())
        guild_row = await self.bot.get_guild_db_config(guild.id)
        self.mischief_map[guild.id] = dict()
        self.role_counts[guild.id] = dict()
        async for row in guild_row.mischief_roles.all():
            self.mischief_map[guild.id][row.alias] = guild.get_role(row.roleid)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        Configuration.del_persistent_var(f"name_cooldown_{guild.id}", True)

    @tasks.loop(seconds=1)
    async def name_task(self):
        # periodic task to run while cog is loaded
        now = datetime.now().timestamp()
        try:
            for guild in self.bot.guilds:
                updated_name_cooldown = {}
                haunted_role = discord.utils.get(guild.roles, name="haunted")
                if haunted_role is None:
                    # server must have a haunted role or this is ignored
                    continue

                for str_uid, mischief_name_obj in dict(self.name_cooldown[str(guild.id)]).items():
                    if (now - mischief_name_obj['timestamp']) < self.name_cooldown_time:
                        updated_name_cooldown[str_uid] = mischief_name_obj
                    else:
                        # reset name to normal
                        my_member = guild.get_member(int(str_uid))

                        if not my_member:
                            continue

                        if haunted_role in my_member.roles:
                            await my_member.remove_roles(haunted_role)

                        if mischief_name_obj['mischief_name'] == my_member.display_name:
                            # mischief name is still in use when mischief expires
                            # restore display name if member hasn't changed name
                            if mischief_name_obj['name_is_nick']:
                                edited_member = await my_member.edit(nick=mischief_name_obj['name_normal'])
                            else:
                                edited_member = await my_member.edit(nick=None)

                if updated_name_cooldown != self.name_cooldown[str(guild.id)]:
                    self.name_cooldown[str(guild.id)] = updated_name_cooldown
                    Configuration.set_persistent_var(f"name_cooldown_{guild.id}", updated_name_cooldown)
        except Exception as e:
            await utils.Utils.handle_exception("mischief name task error", self.bot, e)

    @tasks.loop(seconds=600)
    async def role_count_task(self):
        # periodic task to run while cog is loaded

        # remove expired cooldowns
        now = datetime.now().timestamp()

        try:
            cooldown = Configuration.get_persistent_var(f"mischief_cooldown", dict())
            updated_cooldown = {}
            # key for loaded dict is a string
            for str_uid, member_last_access_time in cooldown.items():
                if (now - member_last_access_time) < self.cooldown_time:
                    updated_cooldown[str_uid] = member_last_access_time
            Configuration.set_persistent_var(f"mischief_cooldown", updated_cooldown)
        except Exception as e:
            Logging.info("can't clear cooldown")
            await Utils.handle_exception("Mischief role_count_task cooldown exception", self.bot, e)

        # update role count storage (because it's slow)
        for guild in self.bot.guilds:
            for my_role in self.mischief_map[guild.id].values():
                try:
                    self.role_counts[guild.id][my_role.id] = len(my_role.members)
                except Exception as e:
                    Logging.info(f"can't update role counts for {my_role}")
                    await Utils.handle_exception("Mischief role_count_task counting roles exception", self.bot, e)
                    continue

    @commands.group(name="name_mischief", invoke_without_command=True)
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def name_mischief(self, ctx):
        await ctx.send(f"""
name mischief is at {self.name_mischief_chance*100}%
name cooldown is {self.name_cooldown_time} seconds
            """)

    @name_mischief.command()
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def set_chance(self, ctx, chance: float):
        self.name_mischief_chance = chance/100
        Configuration.set_persistent_var("name_mischief_chance", chance/100)
        await ctx.invoke(self.name_mischief)

    @name_mischief.command()
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def set_cooldown(self, ctx, seconds: int):
        self.name_cooldown_time = seconds
        Configuration.set_persistent_var("name_mischief_cooldown", seconds)
        await ctx.invoke(self.name_mischief)

    @commands.group(name="mischief", invoke_without_command=True)
    @commands.cooldown(1, 60, BucketType.member)
    @commands.max_concurrency(3, wait=True)
    async def mischief(self, ctx):
        # mods/admins can use this in guild. everyone else can use it in DM
        if ctx.guild and not await Utils.can_mod_official(ctx):
            return

        member_counts = Configuration.get_persistent_var(f"mischief_usage", dict())
        max_member_id = max(member_counts, key=member_counts.get)
        wishes_granted = sum(member_counts.values())
        guild = Utils.get_home_guild()
        max_user: discord.Member = guild.get_member(int(max_member_id))
        max_user_name = Utils.get_member_log_name(max_user)
        await ctx.send(f"{len(member_counts)} people have gotten mischief roles.\n"
                       f"I have granted {wishes_granted} wishes.\n"
                       f"{max_user_name} has wished the most, with {member_counts[max_member_id]} wishes granted.",
                       allowed_mentions=AllowedMentions.none())

    @mischief.command()
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def add_role(self, ctx, role: discord.Role):
        pattern = re.compile(r'^(the|a|an) +', re.IGNORECASE)
        alias = re.sub(pattern, '', role.name)
        guild_row = await self.bot.get_guild_db_config(ctx.guild.id)
        new_row, created = await MischiefRole.get_or_create(guild=guild_row, alias=alias, roleid=role.id)
        if created:
            self.mischief_map[ctx.guild.id][alias] = role
            self.role_counts[ctx.guild.id][role.id] = 0
            await ctx.send(f"`{role.name}` is now a Mischief role!")
        else:
            await ctx.send(f"`{role.name}` is already a Mischief role")

        await ctx.invoke(self.team_mischief)

    @mischief.command()
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def remove_role(self, ctx, role: discord.Role):
        guild_row = await self.bot.get_guild_db_config(ctx.guild.id)
        old_role = await MischiefRole.get_or_none(guild_id=guild_row.id, roleid=role.id)
        if old_role is None:
            await ctx.send(f"`{role.name}` is not a Mischief role, can't remove it")
        else:
            try:
                # remove role from database
                await old_role.delete()
                # remove role from map
                for alias, map_role in dict(self.mischief_map[ctx.guild.id]).items():
                    if map_role.id == role.id:
                        del self.mischief_map[ctx.guild.id][alias]
                        del self.role_counts[ctx.guild.id][role.id]
                        break
                await ctx.send(f"`{role.name}` is no longer a Mischief role!")
            except (tortoise.exceptions.OperationalError, KeyError):
                await ctx.send(f"I had some trouble. Trying to recover...")
                await self.init_guild(ctx.guild)

        await ctx.invoke(self.team_mischief)

    @commands.cooldown(1, 60, BucketType.member)
    @commands.max_concurrency(3, wait=True)
    @commands.command()
    async def team_mischief(self, ctx):
        guild = ctx.guild
        if not ctx.guild:
            guild = Utils.get_home_guild()
        elif not await Utils.can_mod_official(ctx):
            # members can only use this command in DMs
            return

        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0xFFBD1C,
            title="Mischief!")

        for this_role in self.mischief_map[guild.id].values():
            if guild.id not in self.role_counts:
                Logging.error(f"guild {guild.id} not available for team_mischief")
                continue

            if this_role.id not in  self.role_counts[guild.id]:
                Logging.error(f"role {this_role.id} not set for team_mischief in guild {guild.id}")
                continue

            member_count = self.role_counts[guild.id][this_role.id]
            embed.add_field(name=this_role.name, value=str(member_count), inline=True)

            if len(embed.fields) == 25:
                await ctx.send(embed=embed, allowed_mentions=AllowedMentions.none())
                embed = discord.Embed(
                    timestamp=ctx.message.created_at,
                    color=0xFFBD1C,
                    title="mischief continued...")

        await ctx.send(embed=embed, allowed_mentions=AllowedMentions.none())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            # no mischief for bots
            return

        on_message_tasks = [asyncio.create_task(self.mischief_namer(message))]

        for guild in self.bot.guilds:
            if guild.id in self.mischief_map and self.mischief_map[guild.id]:
                # apply mischief to any guilds the member is in
                my_member = guild.get_member(message.author.id)
                if my_member is not None and len(message.content) <= 60 and len(my_member.roles) > 1:
                    try:
                        dm_channel = await my_member.create_dm() # try to create DM channel
                    except Exception:
                        dm_channel = None  # Don't message member because creating DM channel failed

                    on_message_tasks.append(asyncio.create_task(self.role_mischief(message, my_member, dm_channel)))
        await asyncio.gather(*on_message_tasks)

    async def role_mischief(self, message, member, channel):
        now = datetime.now().timestamp()
        uid = member.id
        guild = member.guild
        triggers = [
            "i wish i was",
            "i wish i were",
            "i wish i could be",
            "i wish to be",
            "i wish to become",
            "i wish i could become",
            "i wish i could turn into",
            "i wish to turn into",
            "i wish you could make me",
            "i wish you would make me",
            "i wish you could turn me into",
            "i wish you would turn me into",
        ]

        remove = False
        pattern = re.compile(f"(?:skybot,? *)?({'|'.join(triggers)})(?: (a|an|the))? (.*)", re.I)
        result = pattern.match(message.content)

        if result is None:
            # no match. don't remove or add roles
            return

        # get selection out of matching message
        selection = result.group(3).lower().strip()
        if selection in ["myself", "myself again", "me"]:
            selection = Mischief.me_again

        if selection == Mischief.me_again:
            remove = True
        elif selection not in self.mischief_map[guild.id]:
            return

        # Selection is now validated
        # Check Cooldown
        cooldown = Configuration.get_persistent_var(f"mischief_cooldown", dict())
        member_last_access_time = 0 if str(uid) not in cooldown else cooldown[str(uid)]
        cooldown_elapsed = now - member_last_access_time
        remaining = self.cooldown_time - cooldown_elapsed

        ctx = await self.bot.get_context(message)
        if not await Utils.can_mod_official(ctx) and (cooldown_elapsed < self.cooldown_time):
            try:
                remaining_time = Utils.to_pretty_time(remaining)
                await channel.send(f"wait {remaining_time} longer before you make another wish...")
            except Exception:
                # no channel to message, or messaging failed
                pass
            return
        # END cooldown

        # remove all mischief roles
        for old_role in self.mischief_map[guild.id].values():
            try:
                if old_role in member.roles:
                    await member.remove_roles(old_role)
            except Exception:
                # member role already removed or something...
                pass

        try:
            member_counts = Configuration.get_persistent_var(f"mischief_usage", dict())
            member_count = 0 if str(uid) not in member_counts else member_counts[str(uid)]
            member_counts[str(uid)] = member_count + 1
            Configuration.set_persistent_var("mischief_usage", member_counts)
            cooldown = Configuration.get_persistent_var("mischief_cooldown", dict())
            cooldown[str(uid)] = now
            Configuration.set_persistent_var("mischief_cooldown", cooldown)
        except Exception as e:
            await Utils.handle_exception("mischief role tracking error", self.bot, e)

        if not remove:
            # add the selected role
            await member.add_roles(self.mischief_map[guild.id][selection])

        if channel is not None:
            try:
                if remove:
                    await channel.send("fine, you're demoted!")
                else:
                    await channel.send(f"""Congratulations, you are now **{selection}**!! You can wish again in my DMs if you want!
You can also use the `!team_mischief` command right here to find out more""")
            except Exception:
                # failed to message. ignore.
                pass

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # decrement role counts only for roles removed
        try:
            my_map = self.role_counts[after.guild.id]
            for role in before.roles:
                if role not in after.roles and role.id in my_map:
                    my_map[role.id] = my_map[role.id] - 1
                    # Logging.info(f"{after.display_name} --{role.name}")

            # increment role counts only for roles added
            for role in after.roles:
                if role not in before.roles and role.id in my_map:
                    my_map[role.id] = my_map[role.id] + 1
                    # Logging.info(f"{after.display_name} ++{role.name}")
        except KeyError:
            # caught before bot is fully initialized. ignore
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # decrement role counts for any tracked roles the departed member had
        try:
            my_map = self.role_counts[member.guild.id]
            for role in member.roles:
                if role.id in my_map:
                    my_map[role.id] = my_map[role.id] - 1
        except KeyError:
            # caught before bot is fully initialized. ignore
            pass

    async def mischief_namer(self, message):
        if not hasattr(message.author, "guild"):
            # guild required for nickname shenanigans
            return

        try:
            my_member = message.guild.get_member(message.author.id)
            if str(message.guild.id) in self.name_cooldown and \
                    str(my_member.id) not in self.name_cooldown[str(message.guild.id)]:
                roll = random()
                if roll < self.name_mischief_chance:
                    # await message.channel.send("spooky")
                    now = datetime.now().timestamp()
                    haunted_role = discord.utils.get(message.guild.roles, name="haunted")
                    await my_member.add_roles(haunted_role)
                    nick_limit = 32
                    random_name = choice(self.mischief_names)
                    old_name = my_member.display_name
                    is_nick = my_member.nick is not None
                    diff = nick_limit - len(random_name) + 6
                    chomped_name = old_name[0:diff]
                    mischief_name = random_name.format(name=chomped_name)

                    name_obj = {
                        "mischief_name": mischief_name,
                        "timestamp": int(now),
                        "name_normal": old_name,
                        "name_is_nick": 1 if is_nick else 0
                    }

                    self.name_cooldown[str(message.guild.id)][str(my_member.id)] = name_obj
                    edited_member = await my_member.edit(nick=mischief_name)
                    Configuration.set_persistent_var(
                        f"name_cooldown_{message.guild.id}",
                        self.name_cooldown[str(message.guild.id)]
                    )
        except Exception as e:
            Logging.info("mischief namer error")
            Logging.info(e)


async def setup(bot):
    await bot.add_cog(Mischief(bot))
