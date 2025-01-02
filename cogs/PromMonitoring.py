import discord
from aiohttp import web
from discord.ext import commands
from prometheus_client.exposition import generate_latest

from cogs.BaseCog import BaseCog
from utils import Configuration, Logging
from utils.Logging import TCol


class PromMonitoring(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.running = True
        self.metric_server = None
        self.start_metrics = self.bot.loop.create_task(self.create_site())

    async def cog_unload(self):
        self.running = False
        if self.metric_server:
            await self.metric_server.stop()
        else:
            self.start_metrics.cancel()
        await self.start_metrics

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        guild_id = ctx.guild.id if ctx.guild is not None else 0
        self.bot.metrics.command_counter.labels(
            command_name=ctx.command.qualified_name,
            guild_id=guild_id
        ).inc()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        m = self.bot.metrics

        m.guild_messages.labels(
            guild_id=message.guild.id if message.guild is not None else 0
        ).inc()

        (m.own_message_raw_count if message.author.id == self.bot.user.id else m.bot_message_raw_count if message.author.bot else m.user_message_raw_count).inc()

    async def create_site(self):
        port = Configuration.get_var('METRICS_PORT', 8080)
        Logging.info(f"starting metrics server on port {port}", TCol.Warning)
        metrics_app = web.Application()
        metrics_app.add_routes([web.get("/metrics", self.serve_metrics)])

        runner = web.AppRunner(metrics_app)
        await runner.setup()
        site = web.TCPSite(runner, port=port, host='localhost')
        await site.start()

        self.metric_server = site

    async def serve_metrics(self, request):
        metrics_to_server = generate_latest(self.bot.metrics_reg).decode("utf-8")
        return web.Response(text=metrics_to_server, content_type="text/plain")


async def setup(bot):
    await bot.add_cog(PromMonitoring(bot))
