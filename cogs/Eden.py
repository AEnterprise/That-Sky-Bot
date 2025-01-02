import re
import typing
from datetime import datetime, timedelta

import pytz
from discord import app_commands, Interaction, InteractionResponse
from discord.ext import commands
from pytz import UnknownTimeZoneError

from cogs.BaseCog import BaseCog
from utils import Utils, Lang
from utils.Utils import interaction_response


class Eden(BaseCog):

    def __init__(self, bot):
        super().__init__(bot)
        self.cool_down = dict()

    @app_commands.command(description="Show information about reset time (and countdown) for Eye of Eden")
    @app_commands.describe(public="Show the response to others? Default is to show only you you")
    async def eden_reset(self, interaction: Interaction, public: typing.Literal['Yes', 'No'] = 'No'):
        server_zone = pytz.timezone("America/Los_Angeles")

        # get a timestamp of today with the correct hour, eden reset is 7am UTC
        dt = datetime.now().astimezone(server_zone).replace(hour=0, minute=0, second=0, microsecond=0)
        # sunday is weekday 7
        days_to_go = (6 - dt.weekday()) or 7
        reset_time = dt + timedelta(days=days_to_go)
        pretty_countdown = f"<t:{int(reset_time.timestamp())}:R>"
        reset_timestamp_formatted = f"<t:{int(reset_time.timestamp())}:F>"
        er_response = Lang.get_locale_string("eden/reset",
                                             interaction,
                                             reset=reset_timestamp_formatted,
                                             countdown=pretty_countdown)
        msg = f"{er_response}"
        await interaction_response(interaction).send_message(msg, ephemeral=public == "Yes")


async def setup(bot):
    await bot.add_cog(Eden(bot))
