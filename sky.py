import asyncio
import os
import signal
import sys
from typing import Optional
from asyncio import shield

import discord
import sentry_sdk
from aerich import Command
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import ConnectionClosed, Intents, AllowedMentions, HTTPException, Embed
from discord.ext import commands
from discord.ext.commands import Bot, Context
from prometheus_client import CollectorRegistry
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from tortoise import Tortoise

import utils.tortoise_settings
from utils import Logging, Configuration, Utils, Emoji, Database, Lang, dbbackup
from utils.Database import BotAdmin, Guild, AdminRole
from utils.Logging import TCol
from utils.PrometheusMon import PrometheusMon

running = None


class Skybot(Bot):
    loaded = False
    metrics_reg = CollectorRegistry()
    data = dict()

    def __init__(self, *args, loop=None, **kwargs):
        super().__init__(*args, loop=loop, **kwargs)
        self.shutting_down = False
        self.metrics = PrometheusMon(self)
        self.config_channels = dict()
        self.db_keepalive = None
        self.my_name = type(self).__name__
        self.loaded = False
        sys.path.append(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "sky-python-music-sheet-maker",
                         "python"))

    async def setup_hook(self):
        Logging.info(f'{TCol.cUnderline}{TCol.cWarning}setup_hook start{TCol.cEnd}{TCol.cEnd}')

        await Database.init()
        Logging.info('db init is done')

        await Lang.load_local_overrides()
        Logging.info(f"Locales loaded\n\tguild: {Lang.GUILD_LOCALES}\n\tchannel: {Lang.CHANNEL_LOCALES}")

        for cog in Configuration.get_var("cogs"):
            try:
                Logging.info(f"load cog {TCol.cOkCyan}{cog}{TCol.cEnd}")
                await self.load_extension("cogs." + cog)
                Logging.info(f"\t{TCol.cOkGreen}loaded{TCol.cEnd}")
            except Exception as e:
                await Utils.handle_exception(
                    f"{TCol.cFail}Failed to load cog{TCol.cEnd} {TCol.cWarning}{cog}{TCol.cEnd}",
                    self,
                    e)
        Logging.info(f"{TCol.cBold}{TCol.cOkGreen}Cog loading complete{TCol.cEnd}{TCol.cEnd}")
        self.db_keepalive = self.loop.create_task(self.keep_db_alive())
        self.loaded = True
        Logging.info(f'{TCol.cUnderline}{TCol.cWarning}setup_hook end{TCol.cEnd}{TCol.cEnd}')

    async def on_ready(self):
        Logging.info(f'{TCol.cUnderline}{TCol.cWarning}on_ready start{TCol.cEnd}{TCol.cEnd}')
        Logging.BOT_LOG_CHANNEL = self.get_channel(Configuration.get_var("log_channel"))
        Emoji.initialize(self)

        Logging.info(f"{TCol.cUnderline}{TCol.cWarning}{self.my_name} on_ready complete{TCol.cEnd}{TCol.cEnd}")
        await Logging.bot_log(f"{Configuration.get_var('bot_name', 'this bot')} startup complete")

    async def get_guild_log_channel(self, guild_id):
        # TODO: cog override for logging channel
        return await self.get_guild_config_channel(guild_id, 'log')

    async def get_guild_rules_channel(self, guild_id):
        return await self.get_guild_config_channel(guild_id, 'rules')

    async def get_guild_welcome_channel(self, guild_id):
        return await self.get_guild_config_channel(guild_id, 'welcome')

    async def get_guild_entry_channel(self, guild_id):
        return await self.get_guild_config_channel(guild_id, 'entry')

    async def get_guild_maintenance_channel(self, guild_id):
        return await self.get_guild_config_channel(guild_id, 'maintenance')

    async def get_guild_config_channel(self, guild_id, name):
        config = await self.get_guild_db_config(guild_id)
        if config:
            return self.get_channel(getattr(config, f'{name}channelid'))
        return None

    async def get_guild_db_config(self, guild_id):
        try:
            if guild_id in Utils.GUILD_CONFIGS:
                return Utils.GUILD_CONFIGS[guild_id]
            row, created = await Guild.get_or_create(serverid=guild_id)
            Utils.GUILD_CONFIGS[guild_id] = row
            return row
        except Exception as e:
            Utils.get_embed_and_log_exception("--------Failed to get config--------", self, e)
            return None

    async def permission_manage_bot(self, ctx: Context):
        is_admin = await self.member_is_admin(ctx.author.id)
        # Logging.info(f"admin: {'yes' if is_admin else 'no'}")
        if is_admin:
            return True

        if ctx.guild:
            guild_row = await self.get_guild_db_config(ctx.guild.id)
            config_role_ids = Configuration.get_var("admin_roles", [])  # roles saved in the config
            db_admin_roles = await guild_row.admin_roles.filter()  # Roles saved in the db for this guild
            db_admin_role_ids = [row.roleid for row in db_admin_roles]
            admin_role_ids = db_admin_role_ids + config_role_ids
            admin_roles = Utils.id_list_to_roles(ctx.guild, admin_role_ids)

            for role in ctx.author.roles:
                if role in admin_roles:
                    return True

    async def member_is_admin(self, member_id):
        is_owner = await self.is_owner(self.get_user(member_id))
        is_db_admin = await BotAdmin.get_or_none(userid=member_id) is not None
        in_admins = member_id in Configuration.get_var("ADMINS", [])
        if False:
            Logging.info(f"owner: {'yes' if is_owner else 'no'}")
            Logging.info(f"db_admin: {'yes' if is_db_admin else 'no'}")
            Logging.info(f"in_admins: {'yes' if in_admins else 'no'}")
        return is_db_admin or is_owner or in_admins

    async def guild_log(self, guild_id: int, msg: Optional[str] = None, embed: Optional[Embed] = None):
        if not (msg or embed):
            # can't send nothing, so return none
            return None

        channel = await self.get_guild_log_channel(guild_id)
        if channel:
            try:
                sent = await channel.send(content=msg, embed=embed, allowed_mentions=AllowedMentions.none())
                return sent
            except HTTPException:
                pass
        
        # No channel, or send failed. Send notice in bot server:
        sent = await Logging.bot_log(f"server {guild_id} is misconfigured for logging. Failed message:"
                                     f"```{msg}```", embed=embed)
        return sent

    async def close(self):
        Logging.info("Shutting down?")
        if not self.shutting_down:
            Logging.info("Shutting down...")
            self.shutting_down = True
            if self.db_keepalive:
                self.db_keepalive.cancel()
            await Tortoise.close_connections()
            for cog in list(self.cogs):
                Logging.info(f"{TCol.cWarning}unloading{TCol.cEnd} cog {TCol.cOkCyan}{cog}{TCol.cEnd}")
                c = self.get_cog(cog)
                if hasattr(c, "shutdown"):
                    await c.shutdown()
                await self.unload_extension(f"cogs.{cog}")
                Logging.info(f"\t{TCol.cWarning}unloaded{TCol.cEnd}")
            Logging.info(f"{TCol.cWarning}cog unloading complete{TCol.cEnd}")
        return await super().close()

    async def on_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(str(error))
        elif isinstance(error, commands.CheckFailure):
            pass
        elif isinstance(error, commands.CommandOnCooldown):
            if ctx.command.name in ['krill']:
                # commands in this list have custom cooldown handler
                return
            await ctx.send(str(error))
        elif isinstance(error, commands.MaxConcurrencyReached):
            await ctx.send(f"Too many people are using the `{ctx.invoked_with}` command right now. Try again later")
        elif isinstance(error, commands.MissingRequiredArgument):
            self.help_command.context = ctx
            await ctx.send(
                f"""
{Emoji.get_chat_emoji('NO')} You are missing a required command argument: `{ctx.current_parameter.name}`
{Emoji.get_chat_emoji('WRENCH')} Command usage: `{self.help_command.get_command_signature(ctx.command)}`
                """)
        elif isinstance(error, commands.BadArgument):
            self.help_command.context = ctx
            await ctx.send(
                f"""
{Emoji.get_chat_emoji('NO')} Failed to parse the ``{ctx.current_parameter.name}`` parameter: ``{error}``
{Emoji.get_chat_emoji('WRENCH')} Command usage: `{self.help_command.get_command_signature(ctx.command)}`
                """)
        elif isinstance(error, commands.BadLiteralArgument):
            self.help_command.context = ctx
            await ctx.send(f"Parameter `{error.param.name}` must be one of "
                           f"`{', '.join(error.literals)}` but you said `{error.argument}`")
        elif isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.UnexpectedQuoteError):
            self.help_command.context = ctx
            await ctx.send(
                f"""
{Emoji.get_chat_emoji('NO')} There are quotes in there that I don't like
{Emoji.get_chat_emoji('WRENCH')} Command usage: `{self.help_command.get_command_signature(ctx.command)}`
                """)
        else:
            await Utils.handle_exception("Command execution failed", self,
                                         error.original if hasattr(error, "original") else error, ctx=ctx)
            # notify caller
            e = Emoji.get_chat_emoji('BUG')
            if ctx.channel.permissions_for(ctx.me).send_messages:
                await ctx.send(f"{e} Something went wrong while executing that command {e}")

    async def keep_db_alive(self):
        while not self.is_closed():
            # simple query to ping the db
            query = "select 1"
            conn = Tortoise.get_connection("default")
            await conn.execute_query(query)
            await asyncio.sleep(3600)


async def run_db_migrations():
    try:
        Logging.info(f'{TCol.cUnderline}{TCol.cOkBlue}######## dg migrations ########{TCol.cEnd}{TCol.cEnd}')
        command = Command(
            tortoise_config=utils.tortoise_settings.TORTOISE_ORM,
            app=utils.tortoise_settings.app_name
        )
        await command.init()
        result = await command.upgrade(False)
        if result:
            Logging.info(f"{TCol.cOkGreen}##### db migrations done: #####{TCol.cEnd}")
            Logging.info(result)
        else:
            Logging.info(f"{TCol.cWarning}##### no migrations found #####{TCol.cEnd}")
    except Exception as e:
        Utils.get_embed_and_log_exception(f"DB migration failure", Utils.BOT, e)
        exit()
    Logging.info(f'{TCol.cOkGreen}###### end dg migrations ######{TCol.cEnd}')


def before_send(event, hint):
    if 'exc_info' in hint:
        exc_type, exc_value, tb = hint['exc_info']
        for t in [ConnectionClosed, ClientOSError, ServerDisconnectedError]:
            if isinstance(exc_value, t):
                return
    return event


async def can_help(ctx):
    return ctx.author.guild_permissions.mute_members or await this_bot.permission_manage_bot(ctx)


async def can_admin(ctx):
    async def predicate(c):
        return await c.bot.permission_manage_bot(c)
    return commands.check(predicate)


async def persistent_data_job(work_item: Configuration.PersistentAction):
    """Perform persistent data i/o job

    Parameters
    ----------
    work_item: Configuration.PersistentAction
    """
    Configuration.do_persistent_action(work_item)


async def queue_worker(name, queue, job, shielded=False):
    """Generic queue worker

    Parameters
    ----------
    name
    queue:
        the queue to pull work items from
    job:
        the job that will be done on work items
    shielded:
        boolean indicating whether the job will be shielded from cancellation
    """
    global running
    global this_bot
    try:
        # Logging.info(f"\t{TCol.cOkGreen}start{TCol.cEnd} {TCol.cOkCyan}`{name}`{TCol.cEnd} worker")
        while True:
            # Get a work_item from the queue
            work_item = await queue.get()
            try:
                if shielded:
                    await shield(job(work_item))
                else:
                    await asyncio.create_task(job(work_item))
            except asyncio.CancelledError:
                Logging.info(f"job cancelled for worker {name}")
                if not this_bot:
                    Logging.info(f"stopping worker {name}")
                    raise
                Logging.info(f"worker {name} continues")
            except Exception as e:
                await Utils.handle_exception("worker unexpected exception", Utils.BOT, e)
            queue.task_done()
    finally:
        # Logging.info(f"{name} worker is finished")
        return


async def main():
    # start_monitoring(seconds_frozen=10, test_interval=100)

    global running
    running = True
    Logging.init()
    Logging.info(f"Launching {Configuration.get_var('bot_name', 'this bot')}!")
    my_token = Configuration.get_var("token")

    dsn = Configuration.get_var('SENTRY_DSN', '')
    dsn_env = Configuration.get_var('SENTRY_ENV', 'Dev')
    Logging.info(f"DSN info - dsn:{dsn} env:{dsn_env}")

    if dsn != '':
        sentry_sdk.init(dsn, before_send=before_send, environment=dsn_env, integrations=[AioHttpIntegration()])

    # perform db backup before any connections are made to db
    utils.dbbackup.backup_database()

    loop = asyncio.get_running_loop()
    await run_db_migrations()

    Configuration.PERSISTENT_AIO_QUEUE = asyncio.Queue()
    persistent_data_task = asyncio.create_task(
        queue_worker("Persistent Queue",
                     Configuration.PERSISTENT_AIO_QUEUE,
                     persistent_data_job))

    # start the client
    prefix = Configuration.get_var("bot_prefix")
    intents = Intents(
        members=True,
        messages=True,
        guild_messages=True,
        dm_messages=True,
        dm_typing=False,
        guild_typing=False,
        message_content=True,
        guilds=True,
        bans=True,
        emojis_and_stickers=True,
        presences=False,
        reactions=True)
    global this_bot
    this_bot = Skybot(
        loop=loop,
        command_prefix=commands.when_mentioned_or(prefix),
        case_insensitive=True,
        allowed_mentions=AllowedMentions(everyone=False, users=True, roles=False, replied_user=True),
        intents=intents)
    this_bot.help_command = commands.DefaultHelpCommand(command_attrs=dict(name='snelp', checks=[can_help]))
    Utils.BOT = this_bot

    try:
        for signal_name in ('SIGINT', 'SIGTERM'):
            loop.add_signal_handler(getattr(signal, signal_name), lambda: asyncio.ensure_future(this_bot.close()))
    except NotImplementedError:
        pass

    try:
        async with this_bot:
            await this_bot.start(my_token)
    except KeyboardInterrupt:
        pass
    finally:
        this_bot.loaded = False
        running = False
        Logging.info(f"{TCol.cWarning}shutdown finally?{TCol.cEnd}")
        # Wait until all queued jobs are done, then cancel worker.
        if Configuration.PERSISTENT_AIO_QUEUE.qsize() > 0:
            Logging.info(f"there are {Configuration.PERSISTENT_AIO_QUEUE.qsize()} persistent data items left...")
            await Configuration.PERSISTENT_AIO_QUEUE.join()
        persistent_data_task.cancel("shutdown")
        try:
            await persistent_data_task
        except asyncio.CancelledError:
            pass

        if not this_bot.is_closed():
            await this_bot.close()

this_bot: Optional[Skybot] = None

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        # Who knows... log this.
        Logging.error(f"Unhandled exception: {ex}")
    finally:
        Logging.info(f"{TCol.cOkGreen}bot shutdown complete{TCol.cEnd}")
