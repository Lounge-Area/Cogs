import discord
from redbot.core import commands, Config
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

class ModWhitelist(commands.Cog):
    """Cog zum Whitelisten von Kanälen für Moderationsaktionen."""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        self.config.register_guild(whitelisted_channels=[])

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignoriere Bots und DMs
        if message.author.bot or not message.guild:
            return
        # Prüfe, ob der Kanal in der Whitelist ist
        whitelisted_channels = await self.config.guild(message.guild).whitelisted_channels()
        if message.channel.id in whitelisted_channels:
            return  # Keine Moderation in whitelisted Kanälen
        # Standard-Moderationslogik (z. B. Filter, Spam-Erkennung) hier
        # Beispiel: Prüfe auf verbotene Wörter (passe an deine Bedürfnisse an)
        forbidden_words = ["badword1", "badword2"]  # Ersetze durch deine Liste
        if any(word in message.content.lower() for word in forbidden_words):
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention}, diese Nachricht wurde wegen verbotener Wörter gelöscht.")
            except discord.Forbidden:
                pass

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