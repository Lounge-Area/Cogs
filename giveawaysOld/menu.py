import logging
import discord
from discord.ui import Button, View
from .objects import AlreadyEnteredError, GiveawayEnterError, GiveawayError

log = logging.getLogger("red.flare.giveaways")

class GiveawayView(View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

BUTTON_STYLE = {
    "blurple": discord.ButtonStyle.primary,
    "grey": discord.ButtonStyle.secondary,
    "green": discord.ButtonStyle.success,
    "red": discord.ButtonStyle.danger,
    "gray": discord.ButtonStyle.secondary,
}

class GiveawayButton(Button):
    def __init__(self, label: str, style: str, emoji, cog, id, update=False):
        super().__init__(
            label=label,
            style=BUTTON_STYLE.get(style, discord.ButtonStyle.green),
            emoji=emoji,
            custom_id=f"giveaway_button:{id}"
        )
        self.default_label = label
        self.update = update
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if interaction.message.id not in self.cog.giveaways:
            await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
            return

        giveaway = self.cog.giveaways[interaction.message.id]
        await interaction.response.defer()
        try:
            await giveaway.add_entrant(interaction.user)  # Ensure this is awaited
            await self.cog.save_giveaway(giveaway)
            await interaction.followup.send(
                f"You have been entered into the giveaway for {giveaway.title}.",
                ephemeral=True
            )
        except AlreadyEnteredError as e:
            giveaway.remove_entrant(interaction.user.id)
            await self.cog.save_giveaway(giveaway)
            await interaction.followup.send(
                "You have been removed from the giveaway.",
                ephemeral=True
            )
        except GiveawayEnterError as e:
            await interaction.followup.send(f"{e.message}", ephemeral=True)
        except GiveawayError as e:
            log.error(f"Error processing giveaway {giveaway.id} entry: {str(e)}", exc_info=e)
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
        
        if self.update:
            await self.update_label(giveaway, interaction)

    async def update_label(self, giveaway, interaction):
        try:
            if len(giveaway.entrants) >= 1:
                self.label = f"{self.default_label} ({len(giveaway.entrants)})"
            else:
                self.label = self.default_label
            await interaction.message.edit(view=self.view)
        except discord.HTTPException as e:
            log.error(f"Failed to update button label for giveaway {giveaway.id}: {str(e)}")