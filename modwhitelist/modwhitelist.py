import discord
from redbot.core import commands, Config
import logging

log = logging.getLogger("red.lounge.modwhitelist")

class ModWhitelist(commands.Cog):
    """Cog zum Whitelisten von Kanälen, um Moderationsaktionen aller Cogs zu verhindern."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        self.config.register_guild(whitelisted_channels=[])

    async def red_delete_data_for_user(self, **kwargs):
        """Keine Nutzerdaten gespeichert."""
        return

    @commands.Cog.listener("on_message_delete")
    async def on_message_delete(self, message: discord.Message):
        """Stellt gelöschte Nachrichten in whitelisted Kanälen wieder her."""
        if message.author.bot or not message.guild:
            return
        whitelisted_channels = await self.config.guild(message.guild).whitelisted_channels()
        if message.channel.id not in whitelisted_channels:
            return
        # Nachricht wurde in einem whitelisted Kanal gelöscht
        try:
            # Sende die Nachricht erneut, um die Löschung rückgängig zu machen
            content = message.content or "*(Keine Inhalte, z. B. Embed oder Anhang)*"
            await message.channel.send(
                f"**Wiederhergestellte Nachricht von {message.author.mention}:**\n{content}",
                allowed_mentions=discord.AllowedMentions.none()
            )
            log.info(f"Nachricht von {message.author.id} in Kanal {message.channel.id} wiederhergestellt.")
        except discord.errors.Forbidden:
            log.warning(f"Keine Berechtigung, Nachricht in Kanal {message.channel.id} wiederherzustellen.")
        except discord.errors.HTTPException as e:
            if e.status == 429:  # Rate limit
                await asyncio.sleep(5)
                await message.channel.send(
                    f"**Wiederhergestellte Nachricht von {message.author.mention}:**\n{content}",
                    allowed_mentions=discord.AllowedMentions.none()
                )
            else:
                log.error(f"Fehler beim Wiederherstellen in Kanal {message.channel.id}: {e}")

    @commands.is_owner()
    @commands.command()
    async def addwhitelist(self, ctx, channel: discord.TextChannel):
        """Fügt einen Kanal zur Moderations-Whitelist hinzu."""
        async with self.config.guild(ctx.guild).whitelisted_channels() as whitelist:
            if channel.id not in whitelist:
                whitelist.append(channel.id)
                await ctx.send(f"Kanal {channel.mention} zur Whitelist hinzugefügt.")
            else:
                await ctx.send(f"Kanal {channel.mention} ist bereits in der Whitelist.")

    @commands.is_owner()
    @commands.command()
    async def removewhitelist(self, ctx, channel: discord.TextChannel):
        """Entfernt einen Kanal aus der Whitelist."""
        async with self.config.guild(ctx.guild).whitelisted_channels() as whitelist:
            if channel.id in whitelist:
                whitelist.remove(channel.id)
                await ctx.send(f"Kanal {channel.mention} aus der Whitelist entfernt.")
            else:
                await ctx.send(f"Kanal {channel.mention} ist nicht in der Whitelist.")

    @commands.is_owner()
    @commands.command()
    async def listwhitelist(self, ctx):
        """Listet alle whitelisted Kanäle auf."""
        whitelist = await self.config.guild(ctx.guild).whitelisted_channels()
        if whitelist:
            channels = [ctx.guild.get_channel(cid).mention for cid in whitelist if ctx.guild.get_channel(cid)]
            await ctx.send(f"Whitelisted Kanäle: {', '.join(channels)}")
        else:
            await ctx.send("Keine Kanäle in der Whitelist.")

async def setup(bot):
    await bot.add_cog(ModWhitelist(bot))