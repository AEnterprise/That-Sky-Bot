import asyncio

import discord
from discord.ext import commands

from cogs.BaseCog import BaseCog
from utils import Configuration, Emoji, Lang, Utils, Questions, Logging
from utils.Database import CustomCommand


class CustCommands(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.commands = dict()

    async def cog_check(self, ctx):
        return ((ctx.guild and ctx.author.guild_permissions.ban_members) or await self.bot.permission_manage_bot(ctx))

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
        self.commands[guild.id] = dict()
        for command in await CustomCommand.filter(serverid=guild.id):
            self.commands[guild.id][command.trigger] = command

    @staticmethod
    async def send_response(ctx, emoji_name, lang_key, **kwargs):
        if 'trigger' in kwargs:
            kwargs['trigger'] = kwargs['trigger'].encode('utf-8').decode('unicode-escape')

        msg = Lang.get_locale_string(f'custom_commands/{lang_key}', ctx, **kwargs)
        emoji = Emoji.get_chat_emoji(emoji_name)
        await ctx.send(f"{emoji} {msg}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        self.commands[guild.id] = dict()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        del self.commands[guild.id]
        await CustomCommand.filter(serverid=guild.id).delete()

    @commands.group(name="commands", aliases=['command'])
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def command(self, ctx: commands.Context):
        """Show a list of custom commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                timestamp=ctx.message.created_at,
                color=0x663399,
                title=Lang.get_locale_string("custom_commands/list_commands", ctx, server_name=ctx.guild.name))
            value = ""
            if len(self.commands[ctx.guild.id].keys()) > 0:
                for trigger in self.commands[ctx.guild.id].keys():
                    if len(value) + len(trigger) > 1000:
                        embed.add_field(name="\u200b", value=value)
                        value = ""
                    value = f"{value}{trigger}"
                    if self.commands[ctx.guild.id][trigger].deletetrigger:
                        value = f"{value} (delete trigger)"
                    value = f"{value}\n"
                embed.add_field(name="\u200b", value=value)
                await ctx.send(embed=embed)
            else:
                await ctx.send(Lang.get_locale_string("custom_commands/no_commands", ctx))

    @command.command(aliases=["set_delete", "unset_delete", "set_reply", "unset_reply"])
    @commands.guild_only()
    async def command_flag(self, ctx: commands.Context, trigger: str):
        """
        Command must be invoked with one of the aliases:

        set_delete, unset_delete, set_reply, unset_reply

        Sets and unsets the respective command flags based on alias used.
        """
        if ctx.invoked_with not in ctx.command.aliases:
            await ctx.send_help(ctx.command)
            return

        trigger = trigger.lower()
        trigger = await Utils.clean(trigger)
        flag_val = False

        # Coerce flag based on command alias
        if ctx.invoked_with.startswith('unset'):
            flag_val = False

        if ctx.invoked_with.startswith('set'):
            flag_val = True

        if ctx.invoked_with.endswith('delete'):
            flag = 'deletetrigger'

        if ctx.invoked_with.endswith('reply'):
            flag = 'reply'

        if len(trigger) > 20:
            emoji = 'WHAT'
            lang_key = 'trigger_too_long'
            tokens = dict()
        elif trigger in self.commands[ctx.guild.id]:
            try:
                setattr(self.commands[ctx.guild.id][trigger], flag, flag_val)
                await self.commands[ctx.guild.id][trigger].save()
            except Exception as e:
                await Utils.handle_exception("Custom Commands set flag exception", self.bot, e)
                raise commands.CommandError

            emoji = 'YES'
            lang_key = f'{flag}_trigger_updated'
            tokens = dict(trigger=trigger, value='ON' if flag_val else 'OFF')
        else:
            emoji = 'NO'
            lang_key = 'not_found'
            tokens = dict(trigger=trigger)
        await self.send_response(ctx, emoji, lang_key, **tokens)

    @command.command(aliases=["new", "add"])
    @commands.guild_only()
    async def create(self, ctx: commands.Context, trigger: str, *, response: str = None):
        """command_create_help"""
        if len(trigger) == 0:
            await self.send_response(ctx, "WHAT", 'empty_trigger')
        elif response is None or response == "":
            await self.send_response(ctx, "WHAT", 'empty_reply')
        elif len(trigger) > 20:
            await self.send_response(ctx, "WHAT", 'trigger_too_long')
        else:
            trigger = trigger.lower()
            cleaned_trigger = await Utils.clean(trigger)
            command = await CustomCommand.get_or_none(serverid=ctx.guild.id, trigger=cleaned_trigger)
            if command is None:
                command = await CustomCommand.create(serverid=ctx.guild.id, trigger=cleaned_trigger, response=response)
                self.commands[ctx.guild.id][cleaned_trigger] = command
                await self.send_response(ctx, "YES", 'command_added', trigger=trigger)
            else:
                async def yes():
                    await ctx.send(Lang.get_locale_string('custom_commands/updating_command', ctx))
                    await ctx.invoke(self.update, trigger, response=response)

                async def no():
                    await ctx.send(Lang.get_locale_string('custom_commands/not_updating_command', ctx))

                await Questions.ask(self.bot,
                                    ctx.channel,
                                    ctx.author,
                                    Lang.get_locale_string('custom_commands/override_confirmation', ctx),
                                    [
                                        Questions.Option('YES', handler=yes),
                                        Questions.Option('NO', handler=no)
                                    ], delete_after=True, locale=ctx)

    @command.command(aliases=["del", "delete"])
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, trigger: str):
        """command_remove_help"""
        trigger = trigger.lower()
        cleaned_trigger = await Utils.clean(trigger)

        tokens = dict()
        if len(cleaned_trigger) > 20:
            emoji = 'WHAT'
            lang_key = 'trigger_too_long'
        elif cleaned_trigger in self.commands[ctx.guild.id]:
            await self.commands[ctx.guild.id][cleaned_trigger].delete()
            del self.commands[ctx.guild.id][cleaned_trigger]
            emoji = 'YES'
            lang_key = 'command_removed'
            tokens = dict(trigger=trigger)
        else:
            emoji = 'NO'
            lang_key = 'not_found'
            tokens = dict(trigger=trigger)
        await self.send_response(ctx, emoji, lang_key, **tokens)

    @command.command(aliases=["edit", "set"])
    @commands.guild_only()
    async def update(self, ctx: commands.Context, trigger: str, *, response: str = None):
        """command_update_help"""
        trigger = trigger.lower()
        cleaned_trigger = await Utils.clean(trigger)
        tokens = dict()
        if response is None:
            emoji = 'NO'
            msg = 'empty_reply'
        else:
            command = await CustomCommand.get_or_none(serverid=ctx.guild.id, trigger=cleaned_trigger)
            if command is None:
                emoji = 'WARNING'
                msg = 'creating_command'
                await ctx.invoke(self.create, trigger, response=response)
            else:
                command.response = response
                await command.save()
                self.commands[ctx.guild.id][cleaned_trigger] = command
                emoji = 'YES'
                msg = 'command_updated'
                tokens = dict(trigger=trigger)

        await self.send_response(ctx, emoji, msg, **tokens)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not hasattr(message.channel, "guild") or message.channel.guild is None:
            return
        if message.guild.id not in self.commands:
            return
        prefix = Configuration.get_var("bot_prefix")
        if message.content.startswith(prefix, 0):
            for trigger in self.commands[message.guild.id]:
                cleaned_message = await Utils.clean(message.content.lower())
                if cleaned_message == prefix+trigger or (cleaned_message.startswith(trigger, len(prefix)) and cleaned_message[len(prefix+trigger)] == " "):
                    command = self.commands[message.guild.id][trigger]
                    reference = message if command.reply else None
                    command_content = command.response.replace("@", "@\u200b").format(author=message.author.mention)
                    if command.deletetrigger:
                        await message.delete()
                    await message.channel.send(command_content, reference=reference)


async def setup(bot):
    await bot.add_cog(CustCommands(bot))
