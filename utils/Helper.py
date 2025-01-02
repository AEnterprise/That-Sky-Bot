from typing import Union

from discord import Embed, InteractionResponded, ui, ButtonStyle
from discord.ext.commands import Context
from discord.interactions import Interaction

from utils import Logging
from utils.Utils import interaction_response


class Sender:
    def __init__(self, ctx: Union[Context, Interaction]):
        self.ctx = ctx

    async def send(self, message: str = None, *, embed: Embed = None, ephemeral: bool = None, **kwargs):
        """Send a message"""
        if isinstance(self.ctx, Context):
            if 'ephemeral' in kwargs:
                del kwargs['ephemeral']
            await self.ctx.send(message, embed=embed, **kwargs)
        elif isinstance(self.ctx, Interaction):
            try:
                await interaction_response(self.ctx).send_message(message, embed=embed, ephemeral=ephemeral, **kwargs)
            except InteractionResponded:
                await self.ctx.followup.send(message, embed=embed, ephemeral=ephemeral)
        else:
            Logging.info(f"Sender must be either Context or Interaction. Found {repr(self.ctx)}")
            raise TypeError("Sender must be either Context or Interaction.")


class ConfirmView(ui.View):
    def __init__(self, user, timeout=60.0):
        super().__init__(timeout=timeout)
        self.value = None
        self.user = user

    async def interaction_check(self, interaction: Interaction):
        return interaction.user.id == self.user.id

    @ui.button(label='Confirm', style=ButtonStyle.green)
    async def confirm(self, interaction: Interaction, button: ui.Button):
        self.value = True
        self.stop()
        await self.disable_buttons(interaction, button)

    @ui.button(label='Cancel', style=ButtonStyle.grey)
    async def cancel(self, interaction: Interaction, button: ui.Button):
        self.value = False
        self.stop()
        await self.disable_buttons(interaction, button)

    async def disable_buttons(self, interaction: Interaction, button: ui.Button):
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True
                if item is button:
                    button.label = button.label + "ed"
                else:
                    self.remove_item(item)
        await interaction_response(interaction).edit_message(view=self)
