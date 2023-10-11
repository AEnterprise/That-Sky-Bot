import asyncio
import os
import signal
import sys
from asyncio import shield

import sentry_sdk
from discord.ext import commands
from discord.ext.commands import Bot
from aiohttp import ClientOSError, ServerDisconnectedError
from discord import ConnectionClosed, Intents, AllowedMentions
from prometheus_client import CollectorRegistry
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from tortoise import Tortoise
from aerich import Command

import utils.tortoise_settings
from utils import Logging, Configuration, Utils, Emoji, Database, Lang, dbbackup
from utils.Logging import TCol
from utils.Database import BotAdmin, Guild
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
        self.db_keepalive = self.loop.create_task(self.keepDBalive())
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

    def get_config_channel(self, guild_id: int, channel_name: str):
        # TODO: replace usage with get_guild_*_channel above
        if Utils.validate_channel_name(channel_name):
            try:
                this_channel_id = self.config_channels[guild_id][channel_name]
                # TODO: catch keyerror and log in guild that channel is not configured
                return self.get_channel(this_channel_id)
            except Exception as ex:
                pass
        return None

    async def permission_manage_bot(self, ctx):
        is_admin = await self.member_is_admin(ctx.author.id)
        # Logging.info(f"admin: {'yes' if is_admin else 'no'}")
        has_admin_role = False
        if ctx.guild:
            for role in ctx.author.roles:
                if role in Configuration.get_var("admin_roles", []):
                    has_admin_role = True
        # Logging.info(f"has_admin_role: {'yes' if has_admin_role else 'no'}")
        return is_admin or has_admin_role

    async def member_is_admin(self, member_id):
        is_owner = await self.is_owner(self.get_user(member_id))
        is_db_admin = await BotAdmin.get_or_none(userid=member_id) is not None
        in_admins = member_id in Configuration.get_var("ADMINS", [])
        # Logging.info(f"owner: {'yes' if is_owner else 'no'}")
        # Logging.info(f"db_admin: {'yes' if is_db_admin else 'no'}")
        # Logging.info(f"in_admins: {'yes' if in_admins else 'no'}")
        return is_db_admin or is_owner or in_admins

    async def guild_log(self, guild_id: int, message=None, embed=None):
        channel = await self.get_guild_log_channel(guild_id)
        if channel and (message or embed):
            return await channel.send(content=message, embed=embed, allowed_mentions=AllowedMentions.none())
        return None

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

    async def on_command_error(bot, ctx: commands.Context, error):
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
            bot.help_command.context = ctx
            await ctx.send(
                f"""
{Emoji.get_chat_emoji('NO')} You are missing a required command argument: `{ctx.current_parameter.name}`
{Emoji.get_chat_emoji('WRENCH')} Command usage: `{bot.help_command.get_command_signature(ctx.command)}`
                """)
        elif isinstance(error, commands.BadArgument):
            bot.help_command.context = ctx
            await ctx.send(
                f"""
{Emoji.get_chat_emoji('NO')} Failed to parse the ``{ctx.current_parameter.name}`` parameter: ``{error}``
{Emoji.get_chat_emoji('WRENCH')} Command usage: `{bot.help_command.get_command_signature(ctx.command)}`
                """)
        elif isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.UnexpectedQuoteError):
            bot.help_command.context = ctx
            await ctx.send(
                f"""
{Emoji.get_chat_emoji('NO')} There are quotes in there that I don't like
{Emoji.get_chat_emoji('WRENCH')} Command usage: `{bot.help_command.get_command_signature(ctx.command)}`
                """)
        else:
            await Utils.handle_exception("Command execution failed", bot,
                                         error.original if hasattr(error, "original") else error, ctx=ctx)
            # notify caller
            e = Emoji.get_chat_emoji('BUG')
            if ctx.channel.permissions_for(ctx.me).send_messages:
                await ctx.send(f"{e} Something went wrong while executing that command {e}")

    async def keepDBalive(self):
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
    return ctx.author.guild_permissions.mute_members or await Utils.BOT.permission_manage_bot(ctx)


async def can_admin(ctx):
    async def predicate(ctx):
        return await ctx.bot.permission_manage_bot(ctx)
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
                if not Utils.BOT.loaded:
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
        presences=True,
        reactions=True)
    skybot = Skybot(
        loop=loop,
        command_prefix=commands.when_mentioned_or(prefix),
        case_insensitive=True,
        allowed_mentions=AllowedMentions(everyone=False, users=True, roles=False, replied_user=True),
        intents=intents)
    skybot.help_command = commands.DefaultHelpCommand(command_attrs=dict(name='snelp', checks=[can_help]))
    Utils.BOT = skybot

    try:
        for signal_name in ('SIGINT', 'SIGTERM'):
            loop.add_signal_handler(getattr(signal, signal_name), lambda: asyncio.ensure_future(skybot.close()))
    except NotImplementedError:
        pass

    try:
        async with skybot:
            await skybot.start(my_token)
    except KeyboardInterrupt:
        pass
    finally:
        Utils.BOT.loaded = False
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

        if not skybot.is_closed():
            await skybot.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # Who knows... log this.
        Logging.error(f"Unhandled exception: {e}")
    finally:
        Logging.info(f"{TCol.cOkGreen}bot shutdown complete{TCol.cEnd}")
