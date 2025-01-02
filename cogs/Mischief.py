import asyncio
import dataclasses
import re
import string
from collections import OrderedDict
from datetime import datetime
from itertools import islice
from math import ceil
from random import random, choice
from time import time
from typing import List, Optional, Union

import discord
import numpy
import tortoise
from discord import AllowedMentions, Forbidden, HTTPException, app_commands, Interaction, Member, Role, Guild, NotFound, \
    Permissions
from discord.app_commands import AppCommandError, Range, Group
from discord.ext import commands, tasks
from discord.ext.commands import BucketType, CommandError, Context

import utils.Utils
from cogs.BaseCog import BaseCog
from utils import Utils, Configuration, Logging
from utils.Database import MischiefRole, MischiefName
from utils.Helper import Sender
from utils.Utils import get_member_log_name, interaction_response


@dataclasses.dataclass
class MischiefNameData():
    mischief_name: str
    timestamp: int
    name_normal: str
    name_is_nick: bool


class Mischief(BaseCog):
    me_again = "me again"
    me_again_display = "MYSELF (remove wishing role)"
    nick_length_limit = 38
    name_max_length = 36
    wish_max_length = 100
    wish_triggers = [
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
    mischief_old_names = [
        "{name} LOVES krills!",
        "{name} fears butterflies",
        "{name} is stuck under the map",
        "lost in fire trial: {name}",
        "server split {name}",
        "{name}, the AFK uber",
        "{name} missed Grandma again",
        "{name} is 1 ticket short",
        "{name}'s 234th resize",
        "the TS can't afford {name}",
        "{name} is watching 40 sunsets",
        "{name} is alone at vault door",
        "{name} asleep in dark water",
        "afk {name} IN the geyser",
        "orange light too high for {name}",
        "{name} cried during Duets",
        "crab race champion: {name}",
        "{name} is stranded on a mountain",
        "{name} won't light vault lanterns",
        "{name} doesn't know what WL is",
        "high five for {name}",
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
        Logging.info(f"\t{self.qualified_name}::init")

        self.cooldown_time: float = 600.0
        self.name_mischief_chance: float = 0.0
        self.name_cooldown_time: float = 60.0
        self.name_cooldown: dict = dict()
        self.mischief_map: dict[int, dict[str, Role]] = dict()
        self.mischief_names: dict[int, set[str]] = dict()
        self.role_counts: dict = dict()

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        self.cooldown_time = float(Configuration.get_persistent_var("role_mischief_cooldown", 600.0))
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
            Logging.info(f"\t{self.qualified_name} starting role_count_task")
            self.role_count_task.start()
        if not self.name_task.is_running():
            Logging.info(f"\t{self.qualified_name} starting name_task")
            self.name_task.start()

    def cog_unload(self):
        Logging.info(f"\t{self.qualified_name}::cog_unload")
        self.role_count_task.cancel()
        self.name_task.cancel()

    async def init_guild(self, guild: Guild):
        self.name_cooldown[str(guild.id)] = Configuration.get_persistent_var(f"name_cooldown_{guild.id}", dict())
        guild_row = await self.bot.get_guild_db_config(guild.id)
        self.mischief_map[guild.id] = dict()
        self.mischief_names[guild.id] = set()
        self.role_counts[guild.id] = dict()
        async for row in guild_row.mischief_names.all():
            self.mischief_names[guild.id].add(row.name)

        ###############
        # MIGRATE
        # TODO: DELETE
        for name in Mischief.mischief_old_names:
            row, created = await MischiefName.get_or_create(name=name, guild=guild_row)
        # TODO: DELETE
        # END MIGRATE
        ###############

        async for row in guild_row.mischief_roles.all():
            # TODO: remove defunct roles from db ?
            self.mischief_map[guild.id][row.alias.lower()] = guild.get_role(row.roleid) # puts None for missing role
            # TODO: event listener for role delete

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        Configuration.del_persistent_var(f"name_cooldown_{guild.id}", True)

    @tasks.loop(seconds=1)
    async def name_task(self):
        now = datetime.now().timestamp()
        try:
            for guild in self.bot.guilds:
                haunted_role = discord.utils.get(guild.roles, name="haunted")
                if haunted_role is None: # ignore server with no haunted role
                    continue

                if str(guild.id) not in self.name_cooldown:
                    return

                updated = False
                my_names: dict[str, dict] = dict(self.name_cooldown[str(guild.id)])
                for str_uid, mischief_name_obj in my_names.items():
                    mischief_name_obj = MischiefNameData(**mischief_name_obj)

                    if (now - mischief_name_obj.timestamp) >= self.name_cooldown_time:
                        # reset name to normal and remove from name_cooldown
                        updated = True
                        del self.name_cooldown[str(guild.id)][str_uid]
                        my_member = guild.get_member(int(str_uid))

                        if my_member is None:
                            continue

                        if haunted_role in my_member.roles:
                            await Mischief.do_remove_roles(my_member, haunted_role)
                            for i in range(5):
                                try:
                                    await my_member.remove_roles(haunted_role)
                                    break
                                except Forbidden:
                                    break
                                except HTTPException as e:
                                    Logging.info(f"failed {i+1}x to remove role `{haunted_role.name}` from {get_member_log_name(my_member)} : {e}")
                                    await asyncio.sleep(0.5)

                        if mischief_name_obj.mischief_name == my_member.display_name:
                            # mischief name is still in use when mischief expires
                            # restore display name if member hasn't changed name
                            if mischief_name_obj.name_is_nick:
                                await Mischief.do_set_nick(my_member, mischief_name_obj.name_normal)
                            else:
                                await Mischief.do_set_nick(my_member, None)
                if updated:
                    Configuration.set_persistent_var(f"name_cooldown_{guild.id}", self.name_cooldown[str(guild.id)])
        except Exception as e:
            await utils.Utils.handle_exception("mischief name task error", e)

    @tasks.loop(seconds=600)
    async def role_count_task(self):
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
            await Utils.handle_exception("Mischief role_count_task cooldown exception", e)

        # update role count storage (because it's slow)
        for guild in self.bot.guilds:
            if guild.id not in self.mischief_map:
                continue
            for my_role in self.mischief_map[guild.id].values():
                try:
                    self.role_counts[guild.id][my_role.id] = len(my_role.members)
                except AttributeError:
                    continue
                except Exception as e:
                    Logging.info(f"can't update role counts for {my_role}")
                    await Utils.handle_exception("Mischief role_count_task counting roles exception", e)
                    continue

    ############################
    # App Commands
    ############################

    mischief_config = Group(
        name='mischiefconfig',
        description='Mischief Configuration',
        guild_only=True,
        default_permissions=Permissions(ban_members=True))

    @mischief_config.command(name='showconfig')
    async def name_mischief_config(self, interaction: Interaction) -> None:
        """Show mischief settings"""
        await interaction_response(interaction).send_message(
            f"name mischief is at {self.name_mischief_chance * 100}%\n"
            f"name cooldown is {self.name_cooldown_time} seconds\n"
            f"wish cooldown is {self.cooldown_time} seconds",
            ephemeral=True)

    @mischief_config.command(name='sethauntingchance')
    async def app_set_chance(self, interaction: Interaction, chance: Range[float, 0.0, 100.0]) -> None:
        """
        Set the haunting chance (percent)

        Parameters
        ----------
        interaction
        chance
            Percentage chance for a haunting to occur on any given on_message event

        Returns
        -------
        None
        """
        pct_chance = chance/100
        self.name_mischief_chance = pct_chance
        Configuration.set_persistent_var("name_mischief_chance", pct_chance)
        await interaction_response(interaction).send_message(f"Ok, hauntings are at {chance}%")

    @mischief_config.command(name='sethauntingcooldown')
    async def app_set_cooldown(self, interaction: Interaction, seconds: Range[float, 10]) -> None:
        """
        Set the haunting cooldown time (in seconds)

        Parameters
        ----------
        interaction
        seconds
            The duration of hauntings in seconds

        Returns
        -------
        None
        """
        self.name_cooldown_time = seconds
        Configuration.set_persistent_var("name_mischief_cooldown", seconds)
        await interaction_response(interaction).send_message(f"Ok, hauntings will last {seconds} seconds")

    @mischief_config.command(name='setwishcooldown')
    async def app_set_wish_cooldown(self, interaction: Interaction, seconds: Range[int, 10]) -> None:
        """
        Set the wishing role cooldown time (in seconds)

        Parameters
        ----------
        interaction
        seconds
            The cooldown time in seconds to wait before a wishing role can be chosen again

        Returns
        -------
        None
        """
        self.cooldown_time = seconds
        Configuration.set_persistent_var("role_mischief_cooldown", seconds)
        await interaction_response(interaction).send_message(f"Wishing (role) cooldown is now {seconds} seconds")

    @mischief_config.command(name='listwishingroles')
    async def list_wishing_roles(self, interaction: Interaction) -> None:
        """
        Show a list of wishing roles

        Parameters
        ----------
        interaction

        Returns
        -------
        None
        """
        embed = discord.Embed(
            color=0xFFBD1C,
            title="Mischief Configuration")
        for alias, role in self.mischief_map[interaction.guild.id].items():
            value = f"__{role.name}__\n({role.id})" if role is not None else f"__{alias}__ None"
            embed.add_field(name="role", value=value)
        await interaction_response(interaction).send_message(embed=embed, allowed_mentions=AllowedMentions.none())

    @mischief_config.command(name='addwishingrole')
    async def add_wishing_role(self, interaction: Interaction, role: Role) -> None:
        """
        Add a wishing role

        Parameters
        ----------
        interaction
        role

        Returns
        -------
        None
        """

    @mischief_config.command(name='removewishingrole')
    async def remove_wishing_role(self, interaction: Interaction, alias: Range[str, 1, wish_max_length]) -> None:
        """
        Remove a wishing role

        Parameters
        ----------
        interaction
        alias
            The alias for the role to remove

        Returns
        -------
        None
        """
        if alias not in self.mischief_map[interaction.guild.id]:
            raise CommandError(f"alias {alias} does not exist")

        guild_row = await self.bot.get_guild_db_config(interaction.guild.id)
        delete_row = await MischiefRole.get_or_none(guild=guild_row, alias=alias)
        sender = Sender(interaction)
        message = ""
        delete_role_id = None

        if delete_row is None:
            message += f"\n`{alias}` was not a Mischief role isn't in my database. This might have worked anyway!"
        else:
            try:
                delete_role_id = delete_row.roleid
                # remove role from database
                await delete_row.delete()
            except (tortoise.exceptions.OperationalError):
                await sender.send(f"I had some trouble. Trying to recover...{message}", ephemeral=True)
                await self.init_guild(interaction.guild)
                return
        try:
            # remove role from tracking dicts
            del self.mischief_map[interaction.guild.id][alias]
            if delete_role_id is not None:
                del self.role_counts[interaction.guild.id][delete_role_id]

            await sender.send(f"`{alias}` is no longer a Mischief role!{message}", ephemeral=True)
        except KeyError:
            await sender.send(f"guild is not configured for this mischief role{message}", ephemeral=True)

    @mischief_config.command(name='listmischiefnames')
    async def list_mischief_names(self, interaction: Interaction) -> None:
        """List all mischief names"""
        embed = discord.Embed(title="Mischief Names", color=0xFFBD1C)
        for i in list(string.ascii_lowercase):
            pass

        paired = {}
        name_pattern = re.compile(r"\{name}", re.I)
        non_letter_pattern = re.compile(r"[^a-z]", re.I)
        for name in self.mischief_names[interaction.guild.id]:
            key = non_letter_pattern.sub('', name_pattern.sub("", name)).upper()
            if key not in paired:
                paired[key] = set()
            paired[key].add(name)

        group_size = 27 # 36 characters * 27 names = 972 characters + 26 newlines = 998
        sorted_keys = sorted(list(paired.keys()))

        sorted_names = [
            item
            for key in sorted_keys
            for item in paired[key]
        ]

        groups = [sorted_names[i:i + group_size] for i in range(0, len(sorted_names), group_size)]
        for group in groups:
            embed.add_field(name='Names', value="\n".join(group), inline=False)

        await interaction_response(interaction).send_message(embed=embed, allowed_mentions=AllowedMentions.none())

    @mischief_config.command(name='addmischiefname')
    async def add_mischief_name(self, interaction: Interaction, name: Range[str, 1, name_max_length]) -> None:
        """
        Add a mischief name

        Parameters
        ----------
        interaction
        name
            The name must include `{name}`

        Returns
        -------
        None
        """
        if '{name}' not in name:
            raise CommandError("The new name MUST include `{name}`")

        guild_row = await self.bot.get_guild_db_config(interaction.guild.id)
        row, created = await MischiefName.get_or_create(name=name, guild=guild_row)
        if not created:
            await interaction_response(interaction).send_message(f"Mischief name `{name}` already exists", ephemeral=True)
        else:
            self.mischief_names[interaction.guild.id].add(name)
            await interaction_response(interaction).send_message(f"Mischief name `{name}` added!")

    @mischief_config.command(name='removemischiefname')
    async def remove_mischief_name(self, interaction: Interaction, name: Range[str, 1, name_max_length]) -> None:
        """
        Remove a mischief name

        Parameters
        ----------
        interaction
        name
            The name to remove

        Returns
        -------
        None
        """
        row = await MischiefName.get_or_none(name=name, guild__serverid=interaction.guild.id)
        if name in self.mischief_names[interaction.guild.id]:
            self.mischief_names[interaction.guild.id].remove(name)
        if row is None:
            raise CommandError(f"Mischief name `{name}` does not exist")
        await row.delete()
        await interaction_response(interaction).send_message(f"Mischief name `{name}` removed!")

    @app_commands.command()
    async def wish_stats(self, interaction: Interaction) -> None:
        """
        See stats about wishes

        Parameters
        ----------
        interaction

        Returns
        -------
        None
        """
        guild = interaction.guild
        if not interaction.guild:
            guild = Utils.get_home_guild()
        await self.do_wish_stats(interaction, guild)

    @app_commands.guild_only()
    @app_commands.command(name='mischief_stats')
    async def app_mischief(self, interaction: Interaction) -> None:
        """Show mischief stats"""
        # TODO: make counts guild-specific
        member_counts = Configuration.get_persistent_var(f"mischief_usage", dict())
        max_member_id = max(member_counts, key=member_counts.get)
        wishes_granted = sum(member_counts.values())
        max_user = interaction.guild.get_member(int(max_member_id))
        max_user_name = Utils.get_member_log_name(max_user)
        messages = [
            f"{len(member_counts)} people have gotten mischief roles.",
            f"I have granted {wishes_granted} wishes."]
        if await Utils.can_mod_official(interaction):
            messages.append("\n__only mods can see this__:")
            messages.append(f"{max_user_name} has wished the most, with {member_counts[max_member_id]} wishes granted.")
        await interaction_response(interaction).send_message(
            "\n".join(messages),
            allowed_mentions=AllowedMentions.none(),
            ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="iwishtobecome")
    async def i_wish_i_was_a(self, interaction: Interaction, something: Range[str, 1, wish_max_length]) -> None:
        """
        Will your wish come true?

        Parameters
        ----------
        interaction
        something
            The role you want. Start typing to search for more

        Returns
        -------
        None
        """
        if something == Mischief.me_again_display:
            selection = None
        elif something.lower() in self.mischief_map[interaction.guild.id]:
            selection = something.lower()
        else:
            raise AppCommandError("You chose something I didn't recognize")

        sender = Sender(interaction)
        try:
            result = await self.do_wishing_role(interaction, interaction.user, selection)
        except NotFound as e:
            Logging.info(f"a role is missing... {e}")
            await sender.send("well this is embarrassing... I couldn't grant your wish", ephemeral=True)
            return

        if isinstance(result, float):
            now = int(time())
            then = now + int(result)
            await sender.send(f"you can make another wish <t:{then}:R>...", ephemeral=True)
        elif result is False:
            await sender.send("I couldn't grant your wish. I'm sorry :pweep:", ephemeral=True)
        elif result is True:
            if selection is None:
                await sender.send("fine, you're demoted!", ephemeral=True)
            else:
                selection_name = self.mischief_map[interaction.guild.id][selection].name
                await sender.send(
                    f"Congratulations, you are now **{selection_name}**!!\n"
                    f"You can also use the `/wish_stats` command right here to find out more",
                    ephemeral=True)

    @remove_mischief_name.autocomplete('name')
    async def mischief_name_autocomplete(
            self,
            interaction: Interaction,
            current: str) -> List[app_commands.Choice[str]]:
        """autocomplete mischief names"""
        names = sorted(self.mischief_names[interaction.guild.id])
        # generator for all cog names:
        pattern = re.compile(".*".join([letter for letter in current]), re.I)
        all_names = (name for name in names if pattern.search(name) is not None)
        # islice to limit to 25 options (discord API limit)
        some_names = list(islice(all_names, 25))

        ret = [app_commands.Choice(name=i, value=i) for i in some_names]
        return ret

    @remove_wishing_role.autocomplete("alias")
    @i_wish_i_was_a.autocomplete('something')
    async def wish_autocomplete(
            self,
            interaction: Interaction,
            current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for wishing roles"""
        me = OrderedDict([(Mischief.me_again, Mischief.me_again_display)])
        them = OrderedDict(sorted(self.mischief_map[interaction.guild.id].items()))
        aliases = OrderedDict(**me, **them)

        # generator for all cog names:
        all_aliases = (alias for alias, v in aliases.items() if
                       hasattr(v, 'name') and current.lower() in v.name.lower())
        # islice to limit to 25 options (discord API limit)
        some_aliases = list(islice(all_aliases, 25))

        # convert matched list into list of choices
        def get_name(alias):
            try:
                role = self.mischief_map[interaction.guild.id][alias]
            except KeyError:
                return alias
            return role.name if hasattr(role, 'name') else alias # role is None if missing role

        ret = [app_commands.Choice(name=get_name(c), value=c) for c in some_aliases]
        return ret

    ############################
    # Chat Commands
    ############################

    @commands.group(name="name_mischief", invoke_without_command=True)
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def name_mischief(self, ctx):
        await ctx.send(f"""
name mischief is at {self.name_mischief_chance*100}%
name cooldown is {self.name_cooldown_time} seconds
wish cooldown is {self.cooldown_time} seconds
            """)

    @name_mischief.command()
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def set_chance(self, ctx, chance: float):
        clamped_chance = max(min(chance, 100), 0)/100
        self.name_mischief_chance = clamped_chance
        Configuration.set_persistent_var("name_mischief_chance", clamped_chance)
        await ctx.invoke(self.name_mischief)

    @name_mischief.command()
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def set_cooldown(self, ctx, seconds: int):
        self.name_cooldown_time = float(max(seconds, 10))
        Configuration.set_persistent_var("name_mischief_cooldown", float(seconds))
        await ctx.invoke(self.name_mischief)

    @name_mischief.command()
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def set_wish_cooldown(self, ctx, seconds: int):
        self.cooldown_time = float(max(seconds, 10))
        Configuration.set_persistent_var("role_mischief_cooldown", float(seconds))
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
        max_user = guild.get_member(int(max_member_id))
        max_user_name = Utils.get_member_log_name(max_user)
        await ctx.send(f"{len(member_counts)} people have gotten mischief roles.\n"
                       f"I have granted {wishes_granted} wishes.\n"
                       f"{max_user_name} has wished the most, with {member_counts[max_member_id]} wishes granted.",
                       allowed_mentions=AllowedMentions.none())

    @mischief.command()
    @commands.guild_only()
    @commands.check(Utils.can_mod_official)
    async def add_role(self, ctx, role: discord.Role):
        if ctx.guild.id not in self.mischief_map:
            self.mischief_map[ctx.guild.id] = dict()
        if ctx.guild.id not in self.role_counts:
            self.role_counts[ctx.guild.id] = dict()

        pattern = re.compile(r'^(the|a|an) +', re.IGNORECASE)
        alias = re.sub(pattern, '', role.name).lower()

        if alias in self.mischief_map[ctx.guild.id]:
            await ctx.send(f" There's already a Mischief role with the name `{role.name}`")
            return

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
                guild_map: dict[str, discord.Role] = dict(self.mischief_map[ctx.guild.id])
                for alias, map_role in guild_map.items():
                    if map_role.id == role.id:
                        del self.mischief_map[ctx.guild.id][alias]
                        del self.role_counts[ctx.guild.id][role.id]
                        break
                await ctx.send(f"`{role.name}` is no longer a Mischief role!")
            except (tortoise.exceptions.OperationalError, KeyError):
                await ctx.send(f"I had some trouble. Trying to recover...")
                await self.init_guild(ctx.guild)
            except KeyError:
                await ctx.send(f"guild is not configured for this mischief role")

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
        await self.do_wish_stats(ctx, guild)

    ############################
    # Listeners
    ############################

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            # no mischief for bots
            return

        on_message_tasks = []
        if message.guild is not None: # Don't listen to DMs for name mischief
            on_message_tasks = [asyncio.create_task(self.mischief_namer(message))]

        for guild in self.bot.guilds:
            if guild.id in self.mischief_map and self.mischief_map[guild.id]:
                # apply mischief to any guilds the member is in
                my_member = guild.get_member(message.author.id)
                if my_member is not None and len(my_member.roles) > 1:
                    on_message_tasks.append(asyncio.create_task(self.role_mischief(message, my_member)))
        try:
            await asyncio.gather(*on_message_tasks)
        except (TypeError, HTTPException):
            pass
        except Exception as e:
            await Utils.handle_exception("Mischief on_message error", e, message)

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

    ############################
    # Command internals
    ############################

    async def do_wish_stats(self, ctx: Union[Context, Interaction], guild: Guild):
        sender = Sender(ctx)
        embed = discord.Embed(
            color=0xFFBD1C,
            title="Wish teams!")
        if guild.id not in self.mischief_map:
            raise CommandError(f"guild `{guild.name}` is not configured for Mischief roles")

        for this_role in self.mischief_map[guild.id].values():
            if guild.id not in self.role_counts:
                Logging.error(f"guild {guild.id} not available for team_mischief")
                continue

            if this_role.id not in self.role_counts[guild.id]:
                Logging.error(f"role {this_role.id} not set for team_mischief in guild {guild.id}")
                continue

            member_count = self.role_counts[guild.id][this_role.id]
            embed.add_field(name=this_role.name, value=str(member_count), inline=True)

            if len(embed.fields) == 25:
                await ctx.send(embed=embed, allowed_mentions=AllowedMentions.none())
                embed = discord.Embed(
                    color=0xFFBD1C,
                    title="mischief continued...")

        await sender.send(embed=embed, allowed_mentions=AllowedMentions.none(), ephemeral=True)

    async def do_wishing_role(
            self,
            ctx: Union[Context, Interaction],
            member: discord.Member,
            selection: Optional[str]) -> Union[bool, float]:
        """
        Assign a wishing role

        Parameters
        ----------
        ctx
        member
        selection

        Returns
        -------
        Union[bool, -1] Success or failure, or -1 for cooldown
        """
        uid = member.id
        guild = member.guild

        # Check Cooldown
        now = datetime.now().timestamp()
        cooldown = Configuration.get_persistent_var(f"mischief_cooldown", dict())
        member_last_access_time = 0 if str(uid) not in cooldown else cooldown[str(uid)]
        cooldown_elapsed: float = now - float(member_last_access_time)
        remaining: float = self.cooldown_time - cooldown_elapsed

        if not await Utils.can_mod_official(ctx) and (cooldown_elapsed < self.cooldown_time):
            # return cooldown time
            return float(remaining)
        # END cooldown

        # remove all mischief roles
        for old_role in list(self.mischief_map[guild.id].values()):
            try:
                if old_role in member.roles:
                    await member.remove_roles(old_role)
            except NotFound as e:
                Logging.info(f"role {old_role.name} ({old_role.id}) is missing. {e}")
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
            await Utils.handle_exception("mischief role tracking error", e)
            return False

        if selection is None:
            return True

        # add the selected role
        added = await Mischief.do_add_roles(member, self.mischief_map[guild.id][selection])
        if added:
            # TODO: add wish metrics, tag with userid and role name
            pass
        return added


    async def role_mischief(self, message, member):
        if not hasattr(member, "guild"):
            raise TypeError("can't figure out the guild")

        guild = member.guild

        longest_wish = (
                len(max(Mischief.wish_triggers, key=len)) + len(" the ") +
                len(max(list(self.mischief_map[guild.id].keys()), key=len)))

        if len(message.content) >= longest_wish:
            # message too long. don't bother checking.
            return

        pattern = re.compile(f"(?:skybot,? *)?({'|'.join(Mischief.wish_triggers)})(?: (a|an|the))? (.*)", re.I)
        result = pattern.match(message.content)

        if result is None:
            # not a wish. don't remove or add roles
            return

        # get selection out of matching message
        selection = result.group(3).lower().strip()
        if selection in ["myself", "myself again", "me", "me again"]:
            selection = None
        elif selection not in self.mischief_map[guild.id]:
            # no matching role. don't remove or add roles
            return

        # Selection is now validated
        ctx = await self.bot.get_context(message)
        result = await self.do_wishing_role(ctx, member, selection)

        try:
            dm_channel = await member.create_dm()  # try to create DM channel
            if isinstance(result, float):
                remaining_time = Utils.to_pretty_time(result)
                await dm_channel.send(f"wait {remaining_time} longer before you make another wish...")
            elif result is False:
                pass
            elif result is True:
                if selection is None:
                    await dm_channel.send("fine, you're demoted!")
                else:
                    await dm_channel.send(f"""Congratulations, you are now **{selection}**!! You can wish again in my DMs if you want!
            You can also use the `!team_mischief` command right here to find out more""")
        except (Forbidden, HTTPException):
            pass # DM failed. Ignore.

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
                    # Add haunted role
                    haunted_role = discord.utils.get(message.guild.roles, name="haunted")
                    role_added = await Mischief.do_add_roles(my_member, haunted_role)

                    # TODO: more name mishchief - name transform flags:
                    #  - all lowercase
                    #  - all uppercase
                    #  - reversed
                    #  - no vowels
                    #  - letters only
                    #  - replace [bracketed] or {bracketed} or (bracketed) with fake 'clan'

                    # Pick a random name template and insert member's old name into name template
                    random_name = choice(list(self.mischief_names[message.guild.id]))
                    old_name = my_member.display_name
                    is_nick = my_member.nick is not None
                    diff = Mischief.nick_length_limit - len(random_name)
                    chomped_name = old_name[0:diff]
                    mischief_name = random_name.format(name=chomped_name)

                    name_obj = MischiefNameData(
                        mischief_name=mischief_name,
                        timestamp=int(time()),
                        name_normal=old_name,
                        name_is_nick=is_nick
                    )

                    self.name_cooldown[str(message.guild.id)][str(my_member.id)] = dataclasses.asdict(name_obj)
                    Configuration.set_persistent_var(
                        f"name_cooldown_{message.guild.id}",
                        self.name_cooldown[str(message.guild.id)])

                    name_added = await Mischief.do_set_nick(my_member, mischief_name)

                    if role_added:
                        # TODO: add haunting metrics. tag with userid
                        pass
                    if name_added:
                        # TODO: add name metrics. tag with userid
                        pass

        except Exception as e:
            Logging.info(f"mischief namer error: {e}")

    @staticmethod
    async def do_add_roles(member: Member, role: Role) -> bool:
        log_name = get_member_log_name(member)
        for i in range(5):
            try:
                await member.add_roles(role)
                return True
            except Forbidden:
                Logging.info(f"Forbidden to add role `{role.name}` to {log_name}")
                break  # not allowed to add role
            except HTTPException as e:
                Logging.info(f"failed {i + 1}x to add role `{role.name}` to {log_name} : {e}")
                await asyncio.sleep(0.5) # wait before trying again
        return False

    @staticmethod
    async def do_remove_roles(member: Member, role: Role) -> bool:
        log_name = get_member_log_name(member)
        for i in range(5):
            try:
                await member.remove_roles(role)
                return True
            except Forbidden:
                Logging.info(f"Forbidden to remove role `{role.name}` from {log_name}")
                break  # not allowed to add role
            except HTTPException as e:
                Logging.info(f"failed {i + 1}x to remove role `{role.name}` from {log_name} : {e}")
                await asyncio.sleep(0.5) # wait before trying again
        return False

    @staticmethod
    async def do_set_nick(member, name):
        log_name = get_member_log_name(member)
        for i in range(5):
            try:
                await member.edit(nick=name)
                return True
            except Forbidden:
                Logging.info(f"Forbidden to set nick for {log_name}")
                break
            except HTTPException as e:
                Logging.info(f"failed {i+1}x to set nick for {log_name} : {e}")
                await asyncio.sleep(0.5) # wait before tyring again
        return False


async def setup(bot):
    await bot.add_cog(Mischief(bot))
