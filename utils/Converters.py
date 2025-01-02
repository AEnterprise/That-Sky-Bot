import pytz
from discord import HTTPException
from discord.ext.commands import Converter, BadArgument, UserConverter
from pytz import UnknownTimeZoneError

from utils import Utils
from utils.Constants import ID_MATCHER


class Timezone(Converter):
    async def convert(self, ctx, argument):
        try:
            return pytz.timezone(argument)
        except UnknownTimeZoneError:
            raise BadArgument("Unknown timezone")


class DiscordUser(Converter):

    def __init__(self, id_only=False) -> None:
        super().__init__()
        self.id_only = id_only

    async def convert(self, ctx, argument):
        user = None
        match = ID_MATCHER.match(argument)
        if match is not None:
            argument = match.group(1)
        try:
            user = await UserConverter().convert(ctx, argument)
        except BadArgument:
            try:
                user = await Utils.get_user(
                    await RangedInt(min=20000000000000000, max=9223372036854775807).convert(ctx, argument))
            except (ValueError, HTTPException):
                pass

        if user is None or (self.id_only and str(user.id) != argument):
            raise BadArgument('user_conversion_failed')
        return user


class RangedInt(Converter):

    def __init__(self, min=None, max=None) -> None:
        self.min = min
        self.max = max

    async def convert(self, ctx, argument) -> int:
        try:
            argument = int(argument)
        except ValueError:
            raise BadArgument('NaN')
        else:
            if self.min is not None and argument < self.min:
                raise BadArgument(f'number is below minimum: {min}')
            elif self.max is not None and argument > self.max:
                raise BadArgument(f'number is above maximum: {max}')
            else:
                return argument
