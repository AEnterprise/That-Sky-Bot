import asyncio
import re
from datetime import datetime
from functools import reduce
from random import randint, random, choice

import discord
import tortoise.exceptions
from discord import utils, NotFound
from discord.ext import commands
from discord.ext.commands import command, UserConverter, BucketType

from cogs.BaseCog import BaseCog
from utils import Configuration, Utils, Lang, Emoji, Logging, Questions
from utils.Database import KrillChannel, KrillConfig, OreoMap, OreoLetters, Guild, KrillByLines
from utils.Utils import CHANNEL_ID_MATCHER


class Krill(BaseCog):
    byline_types = [
        'normal',
        'return_home',
        'crab_attack'
    ]

    def __init__(self, bot):
        super().__init__(bot)
        self.configs = dict()
        self.krilled = dict()
        self.channels = dict()
        self.monsters = dict()
        self.ignored = set()
        self.loaded = False
        self.oreo_filter = dict()
        self.oreo_map = None
        self.oreo_defaults = Configuration.get_persistent_var('oreo_filter', dict(
            o=["o", "0", "Ø", "Ǒ", "ǒ", "Ǫ", "ǫ", "Ǭ", "ǭ", "Ǿ", "ǿ", "Ō", "ō", "Ŏ",
               "ŏ", "Ő", "ő", "ò", "ó", "ô", "õ", "ö", "Ò", "Ó", "Ô", "Õ", "Ö", "ỗ",
               "ở", "O", "ø", "⌀", "Ơ", "ơ", "ᵒ", "𝕠", "🅞", "⓪", "ⓞ", "Ⓞ", "ớ",
               "ồ", "🇴", "ợ", "口", "ỡ", "ờ", "ộ", "ố", "ổ", "ọ", "ỏ", "ロ", "ㅇ",
               "°", "⭕", "о", "О", "Ο", "𝐨", "𝐎", ],
            r=["r", "Ȑ", "Ʀ", "ȑ", "Ȓ", "ȓ", "ʀ", "ʁ", "Ŕ", "ŕ", "Ŗ", "ŗ", "Ř", "ř",
               "ℛ", "ℜ", "ℝ", "℞", "℟", "ʳ", "ᖇ", "ɹ", "𝕣", "🅡", "ⓡ", "Ⓡ", "🇷",
               "厂", "尺", "𝐫", ],
            e=["e", "ế", "3", "Ē", "ē", "Ĕ", "ĕ", "Ė", "ė", "ë", "Ę", "ę", "Ě", "ě",
               "Ȩ", "ȩ", "ɘ", "ə", "ɚ", "ɛ", "⋲", "⋳", "⋴", "⋵", "⋶", "⋷", "⋸",
               "⋹", "⋺", "⋻", "⋼", "⋽", "⋾", "⋿", "ᵉ", "E", "ǝ", "€", "𝕖", "🅔",
               "ⓔ", "Ⓔ", "ể", "é", "🇪", "ề", "已", "ệ", "ê", "ễ", "ẹ", "ẽ", "è",
               "ẻ", "巨", "ㅌ", "е", "ε", "𝐞", ],
            oh=["お"],
            re=["れ"],
            sp=[r"\s", r"\x00", r"\u200b", r"\u200c", r"\u200d", r"\.", r"\[", r"\]",
                r"\(", r"\)", r"\{", r"\}", r"\\", r"\-", r"_", r"="],
            n='{0,10}'
        ))

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        asyncio.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")
        await self.init_oreo_map()
        # Load channels
        for guild in self.bot.guilds:
            await self.init_guild(guild)
        self.loaded = True

    async def init_oreo_map(self):
        # Create oreo letter mapping
        my_letters = await OreoLetters.all()
        self.oreo_map, created = await OreoMap.get_or_create()
        if len(my_letters) == 0:
            # Stuff existing persistent vars into db. This is a migration from persistent to db
            # or initialization, and should only run if OreoLetters table is empty
            token_class_map = dict()
            token_class_map['o'] = self.oreo_map.letter_o
            token_class_map['r'] = self.oreo_map.letter_r
            token_class_map['e'] = self.oreo_map.letter_e
            token_class_map['oh'] = self.oreo_map.letter_oh
            token_class_map['re'] = self.oreo_map.letter_re
            token_class_map['sp'] = self.oreo_map.space_char
            for letter_class, class_num in token_class_map.items():
                for letter in self.oreo_defaults[letter_class]:
                    row, created = await OreoLetters.get_or_create(token=letter, token_class=class_num)
                    if letter == "":
                        # clean out bad letter?
                        await row.delete()

            my_letters = await OreoLetters.all()

        # marshall tokens for use by filter
        for row in my_letters:
            if row.token_class not in self.oreo_filter:
                self.oreo_filter[row.token_class] = set()
            if row.token == "":
                Logging.info(f"bad letter... id {row.id}")
                Logging.info(row)
                continue
            self.oreo_filter[row.token_class].add(re.escape(row.token))

        self.krilled = Configuration.get_persistent_var("krilled", dict())
        """
        for user_id, expiry in self.krilled.items():
            user = self.bot.get_user(user_id)
            # expiry = date(expiry)
            print(f"krilled: {user_id}")
            # if date gt expiry, unkrill, else schedule unkrilling
        """

    async def init_guild(self, guild):
        my_channels = set()
        # Get or create db entries for guild and krill config
        guild_row = await self.bot.get_guild_db_config(guild.id)
        self.configs[guild.id], created = await KrillConfig.get_or_create(guild=guild_row)
        for row in await KrillChannel.filter(serverid=guild.id):
            my_channels.add(row.channelid)
        self.channels[guild.id] = my_channels

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.init_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        # delete configs from db
        await KrillChannel.filter(serverid=guild.id).delete()
        await self.configs[guild.id].delete()

        # delete configs from memory
        del self.channels[guild.id]
        del self.configs[guild.id]

    async def trigger_krill(self, user_id):
        # TODO: read configured duration
        #  set expiry
        #  save user and expiry to persistent
        #  do krill attack
        #  schedule un-attack
        pass

    async def do_krill_attack(self, user_id):
        # TODO: apply krill role (dark gray)
        #  apply muted role
        #  deliver krill message
        #  react with flame
        #  listen to flame reaction for un-krill
        pass

    async def un_krill(self, user_id):
        # TODO: remove krill role
        #  remove mute role
        pass

    async def can_mod_krill(ctx):
        return await Utils.can_mod_official(ctx)

    async def can_admin_krill(ctx):
        return ctx.author.guild_permissions.manage_channels or await Utils.BOT.permission_manage_bot(ctx)

    async def can_krill(ctx):
        # mod, empty channel list, or matching channel required
        no_channels = ctx.cog.channels[ctx.guild.id] == set()
        channel_match = ctx.channel.id in ctx.cog.channels[ctx.guild.id]
        bypass = ctx.author.guild_permissions.mute_members or await Utils.BOT.permission_manage_bot(ctx)
        return bypass or no_channels or channel_match

    @commands.group(name="oreo", invoke_without_command=True)
    @commands.guild_only()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def oreo(self, ctx: commands.Context):
        """Show the oreo filter settings."""
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("krill/list_oreo_filter", ctx, server_name=ctx.guild.name))
        embed.add_field(name='Letter "o"', value=" ".join(self.oreo_filter[self.oreo_map.letter_o]))
        embed.add_field(name='Letter "r"', value=" ".join(self.oreo_filter[self.oreo_map.letter_r]))
        embed.add_field(name='Letter "e"', value=" ".join(self.oreo_filter[self.oreo_map.letter_e]))
        embed.add_field(name='Letter "お"', value=" ".join(self.oreo_filter[self.oreo_map.letter_oh]))
        embed.add_field(name='Letter "れ"', value=" ".join(self.oreo_filter[self.oreo_map.letter_re]))
        embed.add_field(name='Inter-letter space', value=", ".join(self.oreo_filter[self.oreo_map.space_char]))
        embed.add_field(name='Character count', value=self.oreo_map.char_count)
        await ctx.send(embed=embed)

    @oreo.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def sniff(self, ctx: commands.Context,  *, value=''):
        """Search a string for unfiltered characters."""
        checked = ""
        found = False
        pattern = self.get_oreo_patterns()['chars']

        # TODO: recognize emojis?
        for letter in value:
            if letter not in checked:
                checked = checked + letter
            else:
                continue
            if not pattern.search(letter):
                found = True
                await ctx.send(Lang.get_locale_string("krill/letter_not_found", ctx, letter=letter))
        if not found:
            await ctx.send(Lang.get_locale_string("krill/smells_clean", ctx, value=value))

    async def validate_oreo_letter(self, ctx, letter):
        categories = ['o', 'r', 'e', 'oh', 're', 'お', 'れ', 'sp']
        if letter not in categories:
            cat = ', '.join(categories)
            await ctx.send(Lang.get_locale_string("krill/invalid_letter_category", ctx, categories=cat))
            return False
        if letter == 'お':
            letter = 'oh'
        if letter == 'れ':
            letter = 're'
        map_map = dict(
            o=self.oreo_map.letter_o,
            r=self.oreo_map.letter_r,
            e=self.oreo_map.letter_e,
            oh=self.oreo_map.letter_oh,
            re=self.oreo_map.letter_re,
            sp=self.oreo_map.space_char
        )
        return map_map[letter]

    @oreo.command(aliases=["add", "letter"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def add_letter(self, ctx: commands.Context, letter, *, value):
        """Add a letter from the oreo filter."""
        letter = await self.validate_oreo_letter(ctx, letter)
        if not letter:
            return

        x = self.get_letter_description(letter)
        if letter != self.oreo_map.space_char:
            value = re.sub(r'[.*|\-\'\"+{\}\[\]`]', '', value)
            value = re.escape(value)
        if value in self.oreo_filter[letter]:
            await ctx.send(Lang.get_locale_string( "krill/letter_already_filtered", ctx, letter=x))
            return

        try:
            self.oreo_filter[letter].add(value)
            await OreoLetters.create(token_class=letter, token=value)
            await ctx.send(Lang.get_locale_string("krill/letter_filter_added", ctx, letter=value, category=x))
        except Exception as e:
            await Utils.handle_exception('Failed to add oreo filter letter', self.bot, e)

    def get_letter_description(self, letter):
        letter_map = dict()
        letter_map[self.oreo_map.letter_o] = "letter \"o\""
        letter_map[self.oreo_map.letter_r] = "letter \"r\""
        letter_map[self.oreo_map.letter_e] = "letter \"e\""
        letter_map[self.oreo_map.letter_oh] = "letter \"oh\""
        letter_map[self.oreo_map.letter_re] = "letter \"re\""
        letter_map[self.oreo_map.space_char] = "space"
        return letter_map[letter]

    @oreo.command(aliases=["remove"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def remove_letter(self, ctx: commands.Context, letter, *, value):
        """Remove a letter from the oreo filter."""
        letter = await self.validate_oreo_letter(ctx, letter)
        if not letter:
            return

        x = self.get_letter_description(letter)
        if value not in self.oreo_filter[letter]:
            await ctx.send(Lang.get_locale_string("krill/letter_not_filtered", ctx, letter=x))
            return

        try:
            letter_row = await OreoLetters.get(token_class=letter, token=value)
            await letter_row.delete()
            self.oreo_filter[letter].remove(value)
            await ctx.send(Lang.get_locale_string("krill/letter_filter_removed", ctx, letter=value, category=x))
        except tortoise.exceptions.DoesNotExist:
            await ctx.send(f"Can't delete `{value}` from the letter `{letter}` register because it's not in that list")
        except Exception as e:
            await Utils.handle_exception('Failed to remove oreo filter letter', self.bot, e)

    @oreo.command(aliases=["reset"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def reset_cooldown(self, ctx: commands.Context):
        """Clear the oreo cooldown list."""
        self.monsters = dict()
        await ctx.send(Lang.get_locale_string("krill/oreo_cooldown_reset", ctx))

    @oreo.command(aliases=["list", "monsters"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def list_monsters(self, ctx: commands.Context):
        """Show a list of everyone on oreo cooldown."""
        if not self.monsters:
            await ctx.send(Lang.get_locale_string("krill/no_monsters", ctx))
            return
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x663399,
            title=Lang.get_locale_string("krill/list_oreo_monsters", ctx, server_name=ctx.guild.name))
        for monster in self.monsters.keys():
            bad_person = Lang.get_locale_string("krill/bad_person", ctx)
            this_member = ctx.guild.get_member(monster)
            if this_member is None:
                # remove nonexistent member
                del self.monsters[monster]
            else:
                embed.add_field(name=bad_person, value=this_member.display_name, inline=False)
        await ctx.send(embed=embed)

    @oreo.command(aliases=["monster"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def add_monster(self, ctx: commands.Context, member: discord.Member):
        """Add a member to oreo monster list."""
        await ctx.message.delete()
        self.monsters[member.id] = datetime.now().timestamp()
        await ctx.send(Lang.get_locale_string("krill/monster_added", ctx, name=member.mention))

    @oreo.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def remove_monster(self, ctx: commands.Context, member: discord.Member):
        """Remove a member from oreo monster list."""
        if member.id in self.monsters.keys():
            del self.monsters[member.id]
            await ctx.send(Lang.get_locale_string("krill/monster_removed", ctx, name=member.mention))
        else:
            await ctx.send(Lang.get_locale_string("krill/member_not_found", ctx, name=member.mention))

    @oreo.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def ignore(self, ctx: commands.Context, member: discord.Member):
        """Add a member to krill command ignore list."""
        self.ignored.add(member.id)
        await ctx.send(Lang.get_locale_string("krill/member_ignored", ctx, name=member.mention))

    @oreo.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def unignore(self, ctx: commands.Context, member: discord.Member):
        """Remove a member from krill command ignore list."""
        if member.id in self.ignored:
            self.ignored.remove(member.id)
            await ctx.send(Lang.get_locale_string("krill/member_not_ignored", ctx, name=member.mention))
        else:
            await ctx.send(Lang.get_locale_string("krill/member_not_found", ctx, name=member.mention))

    def get_oreo_patterns(self):
        # o-ø º.o r...r e é 0 º oおれ
        # ((o|0|ø|º)[ .-]*)+((r|®)[ .-]*)+((e|é)[ .-]*)+((o|0|º)[ .-]*)+
        o = f"({'|'.join(self.oreo_filter[self.oreo_map.letter_o])})"
        r = f"({'|'.join(self.oreo_filter[self.oreo_map.letter_r])})"
        e = f"({'|'.join(self.oreo_filter[self.oreo_map.letter_e])})"
        oo = f"({'|'.join(self.oreo_filter[self.oreo_map.letter_oh])})"
        rr = f"({'|'.join(self.oreo_filter[self.oreo_map.letter_re])})"
        sp = f"({'|'.join(self.oreo_filter[self.oreo_map.space_char])})"
        n = self.oreo_map.char_count
        oreo_pattern = re.compile(f"({o}{sp}{n})+"
                                  f"("
                                  f"({r}{sp}{n})+"
                                  f"({e}{sp}{n})+"
                                  f"|"
                                  f"({e}{sp}{n})+"
                                  f"({r}{sp}{n})+"
                                  f")"
                                  f"({o}{sp}{n})+",
                                  re.IGNORECASE)

        # ((お|oh)[ .-]*)+((れ|re)[ .-]*)+((お|oh)[ .-]*)+
        oreo_jp_pattern = re.compile(f"({oo}{sp}{n})+({rr}{sp}{n})+({oo}{sp}{n})+", re.IGNORECASE)

        # (o|0|º)|(r|®)|(e|é)|(o|0|º|ø)|[ .-]|(お)|(れ)
        oreo_chars = re.compile(f"{o}|{r}|{e}|{sp}|{oo}|{rr}", re.IGNORECASE)

        or_pattern = re.compile(f"{o}(.*){r}", re.IGNORECASE)

        return dict(en=oreo_pattern, jp=oreo_jp_pattern, chars=oreo_chars, or_pattern=or_pattern)

    @commands.group(name="krill_config", aliases=['kcfg', 'kfg'], invoke_without_command=True)
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def krill_config(self, ctx):
        """
        Configure krill settings for your server
        """
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0xCC0000,
            title=Lang.get_locale_string("krill/config_title", ctx, server_name=ctx.guild.name))
        guild_krill_config = self.configs[ctx.guild.id]
        embed.add_field(name="__Return Home__", value=f"{guild_krill_config.return_home_freq}%")
        embed.add_field(name="__Shadow Roll__", value=f"{guild_krill_config.shadow_roll_freq}%")
        embed.add_field(name="__Krill Rider__", value=f"{guild_krill_config.krill_rider_freq}%")
        embed.add_field(name="__Crab__", value=f"{guild_krill_config.crab_freq}%")
        embed.add_field(name="__Allow Text__", value='Yes' if guild_krill_config.allow_text else 'No')
        embed.add_field(name="__Monster Duration__", value=Utils.to_pretty_time(guild_krill_config.monster_duration))
        await ctx.send(embed=embed)

    def blyine_type_disable(self, type):
        try:
            return int(type) | (1 << 14)  # set bit 14 to indicate disabled
        except TypeError as e:
            return 1 << 14

    def blyine_type_enable(self, type):
        try:
            return int(type) & ~(1 << 14)  # unset bit 14 to indicate enabled
        except TypeError as e:
            return 1 << 14

    def is_byline_enabled(self, type):
        try:
            return (int(type) >> 14) & 1
        except TypeError as e:
            return False

    def get_byline_type_id(self, id_or_value):
        for i, v in enumerate(self.byline_types):
            if str(id_or_value) == str(i) or str(id_or_value) == str(v):
                return {'id': i, 'type': v}
        return None

    async def list_bylines(self, ctx):
        embed = discord.Embed(
            timestamp=ctx.message.created_at,
            color=0x00CCFF,
            title=Lang.get_locale_string("krill/config_bylines_title", ctx, server_name=ctx.guild.name))

        guild_krill_config = self.configs[ctx.guild.id]
        await guild_krill_config.fetch_related('bylines')
        if len(guild_krill_config.bylines) > 0:
            bylines = list(guild_krill_config.bylines)
            bylines.sort(key=lambda x: x.type)

            for byline in bylines:
                byline_description = ""
                if byline.locale:
                    byline_description += f"\n{Utils.DISCORD_INDENT}Locale: {byline.locale}"
                if byline.channelid:
                    channel = ctx.guild.get_channel(byline.channelid)
                    byline_description += f"\n{Utils.DISCORD_INDENT}Channel: {channel.mention}"
                byline_type = self.get_byline_type_id(byline.type)
                type_description = byline_type['type'] if byline_type else "DISABLED"
                field_name = f"[{byline.id}]`[{type_description}]`"
                byline_description += f"\n{Utils.DISCORD_INDENT}message: {byline.byline}"

                # Limit of embed count per message. Requires new message
                embed_limit = 5500  # 5500 to be careful
                send_limit = 6000  # over this and we can't send the message
                if (len(embed.fields) == 25) or (len(embed) + len(byline_description) + len(field_name) > embed_limit):
                    if len(embed) <= send_limit:
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send(f"embed was too long ({len(embed)})... trying to log the error")
                        Logging.info(f'Bad KRILL embed:')
                        Logging.info(embed)
                    embed = discord.Embed(
                        color=0x663399,
                        title='...')

                embed.add_field(name=field_name,
                                value=byline.byline,
                                inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("None")

    @staticmethod
    async def nope(ctx, msg: str = None):
        msg = msg or Lang.get_locale_string('common/nope', ctx)
        await ctx.send(f"{Emoji.get_chat_emoji('WARNING')} {msg}")

    async def choose_byline(self, ctx, line_id):
        guild_bylines = await self.configs[ctx.guild.id].bylines.order_by('id')
        if line_id != 0:
            try:
                # check for trigger by db id
                for row in guild_bylines:
                    if row.id == line_id:
                        return row
            except tortoise.exceptions.DoesNotExist:
                no_bylines = "There are no krill bylines. Try making some first!"
                await ctx.send(f"{Emoji.get_chat_emoji('NO')} {no_bylines}")
                return

        # failed to find by id. Ask
        options = []
        keys = dict()
        options.append(f"{Lang.get_locale_string('krill/available_bylines', ctx)}")
        prompt_messages = []

        async def clean_dialog():
            nonlocal prompt_messages
            for msg in prompt_messages:
                try:
                    await msg.delete()
                    await asyncio.sleep(0.1)
                except Exception as e:
                    await Utils.handle_exception("Krill choose_byline clean_dialog exception", self.bot, e)
                    pass

        for row in guild_bylines:
            available_bylines = '\n'.join(options)
            option = f"{row.id} ) `{row.byline}`"
            if len(f"{available_bylines}\n{option}") > 1000:
                prompt_messages.append(await ctx.send(available_bylines))  # send current options, save message
                options = ["**...**"]  # reinitialize w/ "..." continued indicator
            options.append(option)
            keys[row.id] = row
        options = '\n'.join(options)
        prompt_messages.append(await ctx.send(options))  # send current options, save message
        prompt = Lang.get_locale_string('common/which_one', ctx)

        try:
            return_value = int(await Questions.ask_text(self.bot,
                                                        ctx.channel,
                                                        ctx.author,
                                                        prompt,
                                                        locale=ctx,
                                                        delete_after=True))
            if return_value in keys.keys():
                row = keys[return_value]
                await ctx.send(Lang.get_locale_string('common/you_chose_codeblock', ctx, value=row.byline))
                await clean_dialog()
                return row
            raise ValueError
        except (ValueError, asyncio.TimeoutError):
            await clean_dialog()
            key_dump = ', '.join(str(x) for x in keys)
            await self.nope(ctx, Lang.get_locale_string("common/expect_integer", ctx, keys=key_dump))
            raise

    async def choose_byline_type(self, ctx, line_id):

        try:
            if 0 <= int(line_id) < len(self.byline_types):
                return int(line_id)
        except TypeError:
            pass

        # failed to find by id. Ask
        options = []
        keys = dict()
        options.append(f"{Lang.get_locale_string('krill/available_bylines', ctx)}")
        prompt_messages = []

        async def clean_dialog():
            nonlocal prompt_messages
            for msg in prompt_messages:
                try:
                    await msg.delete()
                    await asyncio.sleep(0.1)
                except Exception as e:
                    await Utils.handle_exception("Krill choose_byline_type clean_dialog exception", self.bot, e)
                    pass

        for i, v in enumerate(self.byline_types):
            available_types = '\n'.join(options)
            option = f"{i} ) `{v}`"
            if len(f"{available_types}\n{option}") > 1000:
                prompt_messages.append(await ctx.send(available_types))  # send current options, save message
                options = ["**...**"]  # reinitialize w/ "..." continued indicator
            options.append(option)
            keys[i] = v
        options = '\n'.join(options)
        prompt_messages.append(await ctx.send(options))  # send current options, save message
        prompt = Lang.get_locale_string('common/which_one', ctx)

        try:
            return_value = int(await Questions.ask_text(self.bot,
                                                        ctx.channel,
                                                        ctx.author,
                                                        prompt,
                                                        locale=ctx,
                                                        delete_after=True))
            if return_value in keys.keys():
                chosen_type = keys[return_value]
                await ctx.send(Lang.get_locale_string('common/you_chose_codeblock', ctx, value=chosen_type))
                await clean_dialog()
                return return_value
            raise ValueError
        except (ValueError, asyncio.TimeoutError):
            await clean_dialog()
            key_dump = ', '.join(str(x) for x in keys)
            await self.nope(ctx, Lang.get_locale_string("common/expect_integer", ctx, keys=key_dump))
            raise

    @krill_config.group(name="byline", aliases=["by", "bylines"], invoke_without_command=True)
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def byline(self, ctx):
        """
        Configure krill bylines
        """
        await self.list_bylines(ctx)

    @byline.command(aliases=["add"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def add_byline(self, ctx, *, arg=''):
        """
        Add a new Krill byline

        arg: string - The line bot uses to attribute krill attacks. Must include `{mention}`
        """
        if not re.search('{mention}', arg):
            await ctx.send("You must include `{mention}` in every krill byline")
            return

        guild_krill_config = self.configs[ctx.guild.id]

        async def yes():
            try:
                await KrillByLines.get(krill_config=guild_krill_config, byline=arg)
            except tortoise.exceptions.DoesNotExist:
                # not found. may continue creating now
                pass
            else:
                # already exists. don't create.
                await ctx.send(Lang.get_locale_string('krill/duplicate_byline', ctx, byline=arg))
                return

            disabled = self.blyine_type_disable(1)
            await KrillByLines.create(krill_config=guild_krill_config, type=disabled, byline=arg)
            await ctx.send(Lang.get_locale_string('krill/add_byline', ctx, byline=arg))

        async def no():
            await ctx.send(Lang.get_locale_string('krill/not_changing_byline', ctx))

        try:
            formatted_byline = str(arg).format(mention=ctx.author.mention)
            await Questions.ask(self.bot,
                                ctx.channel,
                                ctx.author,
                                Lang.get_locale_string('krill/confirm_byline', ctx, formatted_byline=formatted_byline),
                                [
                                    Questions.Option('YES', handler=yes),
                                    Questions.Option('NO', handler=no)
                                ], delete_after=True, locale=ctx)
        except asyncio.TimeoutError as e:
            await ctx.send('try again later... but not too much later because you waited too long')

    # TODO:
    #  kfg byline set_channel
    #  kfg byline set_locale

    @byline.command(aliases=["settype", "type"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def set_byline_type(self, ctx, byline_id: int = 0, byline_type: int = None):
        """
        Set Krill byline type

        byline_id: integer id number for the line to set. If you don't know id, omit and bot will prompt for it.
        byline_type: The type of attack this byline responds to:
            [0] normal
            [1] return_home (krill evaded)
            [2] crab attack
        """
        try:
            my_byline = await self.choose_byline(ctx, byline_id)
        except ValueError:
            return

        try:
            my_type = await self.choose_byline_type(ctx, byline_type)
        except ValueError:
            return

        my_byline.type = str(my_type)
        await my_byline.save()
        await ctx.send(
            f"{Emoji.get_chat_emoji('YES')} byline [{my_byline.id}] type set to `{self.byline_types[my_type]}`"
        )

    @byline.command(aliases=["remove"])
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def remove_byline(self, ctx, byline_id: int = 0):
        """
        Remove a Krill byline

        byline_id: integer id number for the line to remove.
        If you don't know id, omit and bot will prompt for it.
        """
        try:
            my_byline = await self.choose_byline(ctx, byline_id)
            byline_id = my_byline.id
        except ValueError:
            return

        await my_byline.delete()
        await ctx.send(Lang.get_locale_string('krill/remove_byline', ctx, number=byline_id))

    @krill_config.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def return_home(self, ctx, percent: int = None):
        """
        Configure return-home frequency for krill command

        percent: integer percentage. Normalized with crab attack when return+crab > 100
          When return+crab < 100, the remainder is percentage for normal attack
        """
        guild_krill_config = self.configs[ctx.guild.id]
        if percent is None:
            await ctx.send(f"`Return home` chance is currently {guild_krill_config.return_home_freq}%")
            return
        guild_krill_config.return_home_freq = max(0, min(100, percent))  # clamp to percent range
        await guild_krill_config.save()
        await ctx.send(f"`Return home` chance is now {guild_krill_config.return_home_freq}%")

    @krill_config.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def shadow_roll(self, ctx, percent: int = None):
        """
        Configure shadow-roll frequency for krill command

        percent: integer percent chance that krill attack (non-return-home variety) or crab attack will
          end with shadow roll emoji
        """
        guild_krill_config = self.configs[ctx.guild.id]
        if percent is None:
            await ctx.send(f"`Shadow roll` chance is currently {guild_krill_config.shadow_roll_freq}%")
            return
        guild_krill_config.shadow_roll_freq = max(0, min(100, percent))  # clamp to percent range
        await guild_krill_config.save()
        await ctx.send(f"`Shadow roll` chance is now {guild_krill_config.shadow_roll_freq}%")

    @krill_config.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def krill_rider(self, ctx, percent: int = None):
        """
        Configure krill-rider frequency for krill command

        percent: integer percent chance that krill rider will appear. Crab/return-home is rolled before this.
        """
        guild_krill_config = self.configs[ctx.guild.id]
        if percent is None:
            await ctx.send(f"`Krill rider` chance is currently {guild_krill_config.krill_rider_freq}%")
            return
        guild_krill_config.krill_rider_freq = max(0, min(100, percent))  # clamp to percent range
        await guild_krill_config.save()
        await ctx.send(f"`Krill rider` chance is now {guild_krill_config.krill_rider_freq}%")

    @krill_config.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def crab(self, ctx, percent: int = None):
        """
        Configure crab-attack frequency for krill command

        percent: integer percentage. Normalized with return-home when return+crab > 100
        When return+crab < 100, the remainder is percentage for normal attack
        """
        guild_krill_config = self.configs[ctx.guild.id]
        if percent is None:
            await ctx.send(f"`Crab` chance is currently {guild_krill_config.crab_freq}%")
            return
        guild_krill_config.crab_freq = max(0, min(100, percent))  # clamp to percent range
        await guild_krill_config.save()
        await ctx.send(f"`Crab` chance is now {guild_krill_config.crab_freq}%")

    @krill_config.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def allow_text(self, ctx, allow: bool = None):
        """
        Configure text permission for krill command

        allow: Boolean - allow or deny text in krill messages
        """
        guild_krill_config = self.configs[ctx.guild.id]
        if allow is not None:
            guild_krill_config.allow_text = allow
            await guild_krill_config.save()
        await ctx.send(f"Text is {'' if guild_krill_config.allow_text else 'not'} allowed with krill command")

    @krill_config.command()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    @commands.guild_only()
    async def monster_duration(self, ctx, monster_time: int = None):
        """
        Configure text permission for krill command

        allow: Boolean - allow or deny text in krill messages
        """
        guild_krill_config = self.configs[ctx.guild.id]
        if monster_time is None:
            await ctx.send(f"Monster timeout is currently {Utils.to_pretty_time(guild_krill_config.monster_duration)}")
            return
        monster_time = min(32767, monster_time)  # signed smallint max
        guild_krill_config.monster_duration = monster_time
        await guild_krill_config.save()
        await ctx.send(f"Monster timeout is now {Utils.to_pretty_time(monster_time)}")

    @command()
    @commands.check(can_krill)
    @commands.cooldown(1, 300, BucketType.member)
    @commands.max_concurrency(3, wait=True)
    @commands.guild_only()
    async def krill(self, ctx, *, arg=''):
        """Krill attack!!!"""
        if ctx.message.author.id in self.ignored:
            return

        guild_krill_config = self.configs[ctx.guild.id]
        if not guild_krill_config.allow_text:
            arg = ''

        await ctx.typing()

        if ctx.message.author.id in self.monsters.keys():
            now = datetime.now().timestamp()
            penalty = guild_krill_config.monster_duration
            if self.monsters[ctx.author.id] + penalty > now:
                remain = (self.monsters[ctx.author.id] + penalty) - now
                await ctx.send(Lang.get_locale_string("krill/oreo_cooldown_message",
                                                      ctx,
                                                      name=ctx.author.mention,
                                                      time_remaining=Utils.to_pretty_time(remain)))
                return

        # TODO: remove emojis and check pattern
        #  remove all lowercase and re-check
        #  remove all uppercase and re-check
        #  only allow letters and emojis?

        patterns = self.get_oreo_patterns()
        oreo_pattern = patterns['en']
        oreo_jp_pattern = patterns['jp']
        dog_pattern = re.compile(r"\bdog\b|\bdoggo\b|\bcookie\b|\bbiscuit\b|\bcanine\b|\bperro\b", re.IGNORECASE)
        or_pattern = patterns['or_pattern']

        name_is_oreo = oreo_pattern.search(ctx.author.display_name) or oreo_jp_pattern.search(ctx.author.display_name)

        victim = re.sub(r'shadow_roll\s*|return_home\s*|krill_rider\s*|crab_attack\s*', '', arg)
        try:
            victim_user = await UserConverter().convert(ctx, victim)
            victim_user = ctx.message.guild.get_member(victim_user.id)
            victim_name = victim_user.nick or victim_user.name
        except Exception as e:
            victim_name = victim
            if re.search(r'@', victim_name):
                self.bot.get_command("krill").reset_cooldown(ctx)
                await ctx.send(Lang.get_locale_string("krill/dirty_trick", ctx, name=ctx.author.mention))
                return

        # remove pattern interference
        reg_clean = re.compile(r'[.\[\](){}\\|~*_`\'\"\-+]')
        victim_name = reg_clean.sub('', victim_name).rstrip().lstrip()

        if oreo_pattern.search(victim_name) or \
                oreo_jp_pattern.search(victim_name) or \
                name_is_oreo or \
                dog_pattern.search(victim_name):
            self.bot.get_command("krill").reset_cooldown(ctx)
            victim_name = "bad person" if name_is_oreo else ctx.author.mention
            await ctx.send(Lang.get_locale_string("krill/not_oreo", ctx, victim_name=victim_name))
            self.monsters[ctx.author.id] = datetime.now().timestamp()
            return

        # clean emoji and store non-emoji text for length evaluation
        emoji_used = Utils.EMOJI_MATCHER.findall(victim_name)
        non_emoji_text = Utils.EMOJI_MATCHER.sub('', victim_name)
        if len(non_emoji_text) > 40:
            await ctx.send(Lang.get_locale_string("krill/too_much_text", ctx))
            return
        if len(emoji_used) > 15:
            await ctx.send(Lang.get_locale_string("krill/too_many_emoji", ctx))
            return

        bad_emoji = set()
        for emoji in emoji_used:
            if utils.get(self.bot.emojis, id=int(emoji[2])) is None:
                bad_emoji.add(emoji[2])
        for bad_id in bad_emoji:
            # remove bad emoji
            this_match = re.compile(f'<(a?):([^: \n]+):{bad_id}>')
            victim_name = this_match.sub('', victim_name)

        #  check for /o(.*)r/ then use captured sequence to remove and re-check
        name_has_or = or_pattern.search(ctx.author.display_name)
        victim_has_or = or_pattern.search(victim_name)
        captured_pattern = []
        if victim_has_or:
            captured_pattern.append(victim_has_or.group(2))
        if name_has_or:
            captured_pattern.append(name_has_or.group(2))
        for pattern in captured_pattern:
            name_cleaned = re.sub(re.escape(pattern), '', victim_name)
            if oreo_pattern.match(name_cleaned):
                self.monsters[ctx.author.id] = datetime.now().timestamp()
                await ctx.send(f"you smell funny, {ctx.author.mention}")
                return

        # one more backup check
        victim_is_oreo = oreo_pattern.search(victim_name) or \
            oreo_jp_pattern.search(victim_name) or \
            dog_pattern.search(victim_name)
        if victim_is_oreo:
            self.monsters[ctx.author.id] = datetime.now().timestamp()
            await ctx.send(Lang.get_locale_string("krill/nice_try", ctx))
            return

        # Initial validation passed. Delete command message and check or start
        Logging.info(f"krill by {Utils.get_member_log_name(ctx.author)} - args: {arg}")
        try:
            await ctx.message.delete()
        except NotFound:
            # most likely a censored message. do not respond.
            return

        # EMOJI hard coded because... it must be exactly these
        head = utils.get(self.bot.emojis, id=640741616080125981)
        body = utils.get(self.bot.emojis, id=640741616281452545)
        tail = utils.get(self.bot.emojis, id=640741616319070229)
        red = utils.get(self.bot.emojis, id=641445732670373916)
        party_kid = utils.get(self.bot.emojis, id=817568025573326868)
        star = utils.get(self.bot.emojis, id=816861755582054451)
        blank = utils.get(self.bot.emojis, id=647913138758483977)
        return_home = utils.get(self.bot.emojis, id=816855701786984528)
        shadow_roll = utils.get(self.bot.emojis, id=816876601534709760)
        my_name = ctx.guild.get_member(self.bot.user.id).display_name
        ded_emoji = utils.get(self.bot.emojis, id=641445732246880282)

        # CRABS
        crab_dance = utils.get(self.bot.emojis, id=825802012615639060)
        crab_mad_1 = utils.get(self.bot.emojis, id=825922697094758440)
        crab_mad_2 = utils.get(self.bot.emojis, id=825922696881373185)
        crab_mad_3 = utils.get(self.bot.emojis, id=825922697031581717)
        crab_mods = utils.get(self.bot.emojis, id=825929190108168213)
        crab_walker_1 = utils.get(self.bot.emojis, id=826275692340707378)
        crab_walker_2 = utils.get(self.bot.emojis, id=826279059523895306)

        bot_emoji = u"\U0001F916"
        victim_is_skybot = re.search(rf"thatskybot|{my_name}|skybot|sky bot", victim_name)
        bonked_kid = bot_emoji if victim_is_skybot else ded_emoji

        args = arg.split(' ')
        byline_type = self.get_byline_type_id('normal')
        cheats = await Krill.can_mod_krill(ctx)
        going_home = ("return_home" in args and cheats) or False
        krill_riding = ('krill_rider' in args and cheats) or (random() < (guild_krill_config.krill_rider_freq/100))
        shadow_rolling = ("shadow_roll" in args and cheats) or (random() < (guild_krill_config.shadow_roll_freq/100))
        crab_attacking = ("crab_attack" in args and cheats) or False

        # krill rider freq is normal percentage, but only applies to regular and going-home krill attack
        if krill_riding:
            # alternate bodies
            # p.s. this will not work w/ a test bot because these emojis are on the official server
            # instead, the krill will look like "NoneNoneNone"
            body_id = choice([
                664262338874048512,
                664239237696323596,
                664237187184853012,
                664191324911697960,
                664242877492101159,
                664235527607812107,
                664234216145289216,
                664246386727845939,
                664230982169264135,
                664259346234081283,
                664256923784314898,
                664230982378979347,
                664251608212832256
            ])
            head = utils.get(self.bot.emojis, id=664191325104504880)
            tail = utils.get(self.bot.emojis, id=664191324869754881)
            body = utils.get(self.bot.emojis, id=body_id)

        # shadow roll freq is normal percentage, but only applies to regular and crab attack
        if shadow_rolling:
            bonked_kid = f"{bot_emoji}{shadow_roll}" if victim_is_skybot else shadow_roll

        def go_home():
            nonlocal going_home
            going_home = True

        def crab_attack():
            nonlocal crab_attacking, going_home
            going_home = False
            crab_attacking = True

        out = [
            dict(action=lambda: go_home(), raw=guild_krill_config.return_home_freq),
            dict(action=lambda: crab_attack(), raw=guild_krill_config.crab_freq),
            dict(action=None, raw=0)
        ]

        # return home and crab are percentage, unless they total more than 100
        # when more than 100, regular attack has 0 chance, and others are normalized
        chance_total = max(100, reduce(lambda x, y: x+y['raw'], out, 0))

        for item in out:
            item['normalized'] = item['raw'] / chance_total

        roll = random()
        tally = 0
        for item in out:
            if item['raw'] == 0:
                continue
            tally += item['normalized']
            if roll < tally:
                action = item['action']
                action()
                break

        if crab_attacking:
            going_home = False
            byline_type = self.get_byline_type_id('crab_attack')

            choices = [
                [crab_dance, crab_dance, crab_dance],
                [crab_mods, crab_mods, crab_mods],
                [crab_mad_1, crab_mad_2, crab_mad_3],
                [crab_walker_1, crab_walker_2, blank]
            ]
            my_crab = choice(choices)
            head = my_crab[0]
            body = my_crab[1]
            tail = my_crab[2]

        count = 0
        time_step = 1
        step = randint(1, 2)
        distance = step * 3
        sky_kid = ""
        spaces = str(blank) * distance
        space_step = str(blank) * step
        message = await ctx.send(f"{space_step}{victim_name} {red}{spaces}{head}{body}{tail}")

        # TODO: channel and locale detection
        bylines = await guild_krill_config.bylines
        byline = [byline.byline for byline in bylines if byline.type in (byline_type['id'], 0)]
        if not byline:
            byline = [Lang.get_locale_string("krill/summoned_by", ctx, name=ctx.author.mention)]
        summoned_by = await ctx.send(choice(byline).format(mention=ctx.author.mention, victim=victim_name))

        while distance > 0:
            sky_kid = return_home if count > 0 and going_home else red
            distance = distance - step
            spaces = str(blank) * distance
            message = await message.edit(content=f"{space_step}{victim_name} {sky_kid}{spaces}{head}{body}{tail}")
            await asyncio.sleep(time_step)
            count = count + 1

        step = randint(0, 2)
        distance = step*3
        count = 0
        secaps = ""
        if going_home:
            message = await message.edit(content=f"{space_step}{victim_name} {sky_kid}")
            await asyncio.sleep(time_step*2)
            return_type = self.get_byline_type_id('return_home')
            evaded_by = [byline for byline in bylines if byline.type == return_type['id']]
            # TODO: detect channel/locale
            summoned_by = await summoned_by.edit(content=choice(evaded_by).byline.format(mention=ctx.author.mention))
            message = await message.edit(content=f"{space_step}{victim_name} {party_kid}")
        else:
            if distance == 0:
                # no star animation. send final result
                message = await message.edit(content=f"{secaps}{star}{spaces}{bonked_kid} {victim_name}{spaces}{star}{spaces}{star}")
            else:
                # star animation
                while count < distance:
                    spaces = str(blank) * count
                    count = count + step
                    secaps = str(blank) * (distance - count)
                    message = await message.edit(content=f"{secaps}{star}{spaces}{bonked_kid} {victim_name}{spaces}{star}{spaces}{star}")
                    await asyncio.sleep(time_step)

        # await message.add_reaction(star)
        # TODO: add message id to persistent vars, listen for reactions.
        #  if reaction count >= 3 remove id from persistent
        #  announce victim has been rescued

    @krill.error
    async def krill_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            if ctx.message.author.guild_permissions.mute_members \
                    or await self.bot.permission_manage_bot(ctx) \
                    or ctx.channel.id not in self.channels[ctx.guild.id]:
                # Bypass cooldown for mute permission and for invocations outside allowed channels
                await ctx.reinvoke()
                return
            time_display = Utils.to_pretty_time(error.retry_after)
            await ctx.send(Lang.get_locale_string("krill/cooldown_message",
                                                  ctx,
                                                  name=ctx.author.mention,
                                                  time_remaining=time_display))

    @krill_config.group(name="krill_channel", aliases=['krillchan', 'channel'], invoke_without_command=True)
    @commands.guild_only()
    @commands.check(can_mod_krill)
    @commands.bot_has_permissions(embed_links=True)
    async def krill_channel(self, ctx: commands.Context):
        """Show a list of allowed channels"""
        # if ctx.invoked_subcommand is None:
        embed = discord.Embed(timestamp=ctx.message.created_at,
                              color=0x663399,
                              title=Lang.get_locale_string("krill/list_channels", ctx, server_name=ctx.guild.name))
        if len(self.channels[ctx.guild.id]) > 0:
            value = ""
            for channel_id in self.channels[ctx.guild.id]:
                channel_name = await Utils.clean(f"<#{channel_id}>", guild=ctx.guild)
                if len(channel_name) + len(f"{channel_id}") > 1000:
                    embed.add_field(name="\u200b", value=value)
                    value = ""
                value = f"{channel_name} - id:{channel_id}\n"
            embed.add_field(name="\u200b", value=value)
            await ctx.send(embed=embed)
        else:
            await ctx.send(Lang.get_locale_string("krill/no_channels", ctx))

    @krill_channel.command(aliases=["new"])
    @commands.check(can_mod_krill)
    @commands.guild_only()
    async def add(self, ctx: commands.Context, channel_id: str):
        """
        Allow krill command in a given channel

        channel_id: id for the channel to allow
        """
        # TODO: use Converter for channel_id
        channel_id = int(channel_id)
        channel = f"<#{channel_id}>"
        if CHANNEL_ID_MATCHER.fullmatch(channel) is None or ctx.guild.get_channel(channel_id) is None:
            await ctx.send(Lang.get_locale_string("krill/no_such_channel", ctx, channel_id=channel_id))
            return

        row = await KrillChannel.get_or_none(serverid=ctx.guild.id, channelid=channel_id)
        channel_name = await Utils.clean(channel, guild=ctx.guild)
        if row is None:
            await KrillChannel.create(serverid = ctx.guild.id, channelid=channel_id)
            self.channels[ctx.guild.id].add(channel_id)
            added = Lang.get_locale_string('krill/channel_added', ctx, channel=channel_name)
            await ctx.send(f"{Emoji.get_chat_emoji('YES')} {added}")
        else:
            await ctx.send(Lang.get_locale_string('krill/channel_found', ctx, channel=channel_name))

    @krill_channel.command(aliases=["del", "delete"])
    @commands.check(can_mod_krill)
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, channel_id):
        """
        Remove channel from krill-allowed channels

        channel_id: id for the channel to remove
        """
        channel_id = int(channel_id)
        channel = f"<#{channel_id}>"

        if channel_id in self.channels[ctx.guild.id]:
            krill_row = await KrillChannel.get(serverid=ctx.guild.id, channelid=channel_id)
            await krill_row.delete()
            self.channels[ctx.guild.id].remove(channel_id)
            removed = Lang.get_locale_string('krill/channel_removed', ctx, channel=channel_id)
            await ctx.send(
                f"{Emoji.get_chat_emoji('YES')} {removed}")
        else:
            not_found = Lang.get_locale_string('krill/channel_not_found', ctx, channel=channel_id)
            await ctx.send(
                f"{Emoji.get_chat_emoji('NO')} {not_found}")


async def setup(bot):
    await bot.add_cog(Krill(bot))
