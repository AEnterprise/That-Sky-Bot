import re
import typing
from datetime import datetime, timedelta

import pytz
from discord import app_commands, Interaction, InteractionResponse
from discord.ext import commands
from pytz import UnknownTimeZoneError

from cogs.BaseCog import BaseCog
from utils import Utils, Lang


class Eden(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.cool_down = dict()

    @app_commands.command(description="Show information about reset time (and countdown) for Eye of Eden")
    @app_commands.describe(public="Show the response to others? Default is to show only you you")
    async def eden_reset(self, interaction: Interaction, public: bool = False):
        cid = interaction.channel.id
        server_zone = pytz.timezone("America/Los_Angeles")

        # get a timestamp of today with the correct hour, eden reset is 7am UTC
        dt = datetime.now().astimezone(server_zone).replace(hour=0, minute=0, second=0, microsecond=0)
        # sunday is weekday 7
        days_to_go = (6 - dt.weekday()) or 7
        reset_time = dt + timedelta(days=days_to_go)
        time_left = reset_time - datetime.now().astimezone(server_zone)
        pretty_countdown = Utils.to_pretty_time(time_left.total_seconds())

        reset_timestamp_formatted = f"<t:{int(reset_time.timestamp())}:F>"
        er_response = Lang.get_locale_string("eden/reset",
                                             interaction,
                                             reset=reset_timestamp_formatted,
                                             countdown=pretty_countdown)
        msg = f"{er_response}"
        r = typing.cast(InteractionResponse, interaction.response)
        await r.send_message(msg, ephemeral=not public)


async def setup(bot):
    await bot.add_cog(Eden(bot))
