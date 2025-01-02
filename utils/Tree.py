import traceback
from inspect import stack

from discord import app_commands, InteractionResponded

from discord.interactions import Interaction

from utils import Logging
from utils.Utils import interaction_response


class CustomCommandTree(app_commands.CommandTree):
    # overriding the on_error method
    async def on_error(
        self,
        interaction: Interaction,
        error: app_commands.AppCommandError
    ):
        """Custom command tree"""
        sub_error = str(error)
        parts = sub_error.split(': ')
        # Remove the first part ("AppCommandError")
        if len(parts) > 1:
            parts = parts[1:]
        # bold the second part (Name of the raised exception)
        parts[0] = f"**{parts[0]}**"
        message = ': '.join(parts)

        Logging.error(error)
        Logging.info(traceback.print_stack())

        try:
            await interaction_response(interaction).send_message(
                message,
                ephemeral=True)
        except InteractionResponded:
            await interaction.followup.send(message, ephemeral=True)