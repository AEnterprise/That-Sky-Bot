import asyncio
import os
import signal
import sys
from typing import Optional
from asyncio import shield

import sentry_sdk
from aerich import Command
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import ConnectionClosed, Intents, AllowedMentions
from discord.ext import commands
from discord.ext.commands import Bot
from prometheus_client import CollectorRegistry
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from tortoise import Tortoise

import utils.tortoise_settings
from utils import Logging, Configuration, Utils, Emoji, Database, Lang, dbbackup
from utils.Database import BotAdmin
from utils.Logging import TCol
from utils.PrometheusMon import PrometheusMon
from utils.Tree import CustomCommandTree

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
        Logging.info(f'setup_hook start', TCol.Warning)

        await Database.init()
        Logging.info('db init is done')

        await Lang.load_local_overrides()
        Logging.info(f"Locales loaded\n\tguild: {Lang.GUILD_LOCALES}\n\tchannel: {Lang.CHANNEL_LOCALES}")

        for cog in Configuration.get_var("cogs"):
            try:
                Logging.info(f"load cog {TCol.Cyan.value}{cog}{TCol.End.value}")
                await self.load_extension("cogs." + cog)
                Logging.info("\tloaded", TCol.Green)
            except Exception as e:
                msg = f"{TCol.Fail.value}Failed to load cog{TCol.End.value} {TCol.Warning.value}{cog}{TCol.End.value}"
                await Utils.handle_exception(msg, e)
        Logging.info("Cog loading complete", TCol.Bold, TCol.Green)
        self.db_keepalive = self.loop.create_task(self.keep_db_alive())
        self.loaded = True
        Logging.info('setup_hook end', TCol.Underline, TCol.Warning)

    async def on_ready(self):
        Logging.info('on_ready start', TCol.Underline, TCol.Warning)
        Logging.BOT_LOG_CHANNEL = self.get_channel(Configuration.get_var("log_channel"))
        Emoji.initialize(self)

        Logging.info(f"{self.my_name} on_ready complete", TCol.Underline, TCol.Warning)
        await Logging.bot_log(f"{Configuration.get_var('bot_name', 'this bot')} startup complete")

    async def close(self):
        Logging.info("Shutting down?")
        if not self.shutting_down:
            Logging.info("Shutting down...")
            self.shutting_down = True
            if self.db_keepalive:
                self.db_keepalive.cancel()
            await Tortoise.close_connections()
            for cog in list(self.cogs):
                Logging.info(f"{TCol.Warning.value}Shutting down{TCol.End.value} cog {TCol.Cyan.value}{cog}{TCol.End.value}")
                c = self.get_cog(cog)
                if hasattr(c, "shutdown"):
                    await c.shutdown()
                Logging.info(f"{TCol.Warning.value}unloading{TCol.End.value} cog {TCol.Cyan.value}{cog}{TCol.End.value}")
                await self.unload_extension(f"cogs.{cog}")
                Logging.info("\tunloaded", TCol.Warning)
            Logging.info("All cogs unloaded.", TCol.Warning)
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
            await Utils.handle_exception("Command execution failed",
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

    async def member_is_admin(self, member_id):
        is_owner = await self.is_owner(self.get_user(member_id))
        is_db_admin = await BotAdmin.get_or_none(userid=member_id) is not None
        in_admins = member_id in Configuration.get_var("ADMINS", [])
        if True:
            pass
            # Logging.info(f"owner: {'yes' if is_owner else 'no'}")
            # Logging.info(f"db_admin: {'yes' if is_db_admin else 'no'}")
            # Logging.info(f"in_admins: {'yes' if in_admins else 'no'}")
        return is_db_admin or is_owner or in_admins

    async def get_guild_db_config(self, guild_id):
        try:
            if guild_id in Utils.GUILD_CONFIGS:
                return Utils.GUILD_CONFIGS[guild_id]
            row, created = await Database.Guild.get_or_create(serverid=guild_id)
            Utils.GUILD_CONFIGS[guild_id] = row
            return row
        except Exception as e:
            Utils.get_embed_and_log_exception("--------Failed to get config--------", e)
            return None


async def run_db_migrations():
    try:
        Logging.info('######## dg migrations ########', TCol.Underline, TCol.Blue)
        command = Command(
            tortoise_config=utils.tortoise_settings.TORTOISE_ORM,
            app=utils.tortoise_settings.app_name
        )
        await command.init()
        result = await command.upgrade(False)
        if result:
            Logging.info("##### db migrations done: #####", TCol.Green)
            Logging.info(result)
        else:
            Logging.info("##### no migrations found #####", TCol.Warning)
    except Exception as e:
        Utils.get_embed_and_log_exception(f"DB migration failure", e)
        exit()
    Logging.info('###### end dg migrations ######', TCol.Green)


def before_send(event, hint):
    """exclude some exceptions from sentry reporting"""
    if 'exc_info' in hint:
        exc_type, exc_value, tb = hint['exc_info']
        # Don't report these exceptions to sentry
        for t in [ConnectionClosed, ClientOSError, ServerDisconnectedError]:
            if isinstance(exc_value, t):
                return
    return event


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
                Logging.info(f"job canceled for worker {name}")
                if not this_bot:
                    Logging.info(f"stopping worker {name}")
                    raise
                Logging.info(f"worker {name} continues")
            except Exception as e:
                await Utils.handle_exception("worker unexpected exception", e)
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
        tree_cls=CustomCommandTree,
        allowed_mentions=AllowedMentions(everyone=False, users=True, roles=False, replied_user=True),
        intents=intents)
    this_bot.help_command = commands.DefaultHelpCommand(command_attrs=dict(name='snelp', checks=[Utils.can_help]))
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
        Logging.info("shutdown finally?", TCol.Warning)
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
        Logging.info("bot shutdown complete", TCol.Green)
