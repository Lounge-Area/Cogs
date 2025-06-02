import discord
from redbot.core import commands, Config
import logging
import asyncio

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

    async def is_channel_whitelisted(self, guild: discord.Guild, channel_id: int) -> bool:
        """Prüft, ob ein Kanal in der Whitelist ist."""
        whitelisted_channels = await self.config.guild(guild).whitelisted_channels()
        return channel_id in whitelisted_channels

    @commands.Cog.listener("on_message_delete")
    async def on_message_delete(self, message: discord.Message):
        """Stellt gelöschte Nachrichten in whitelisted Kanälen wieder her."""
        if message.author.bot or not message.guild:
            return
        if await self.is_channel_whitelisted(message.guild, message.channel.id):
            try:
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

    @commands.Cog.listener("on_message_edit")
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Verhindert Bearbeitungen in whitelisted Kanälen, indem die ursprüngliche Nachricht wiederhergestellt wird."""
        if before.author.bot or not before.guild or before.content == after.content:
            return
        if await self.is_channel_whitelisted(before.guild, before.channel.id):
            try:
                await after.delete()
                await before.channel.send(
                    f"**Wiederhergestellte Nachricht von {before.author.mention}:**\n{before.content}",
                    allowed_mentions=discord.AllowedMentions.none()
                )
                log.info(f"Bearbeitung von {before.author.id} in Kanal {before.channel.id} rückgängig gemacht.")
            except discord.errors.Forbidden:
                log.warning(f"Keine Berechtigung, Bearbeitung in Kanal {before.channel.id} rückgängig zu machen.")
            except discord.errors.HTTPException as e:
                log.error(f"Fehler beim Rückgängigmachen der Bearbeitung in Kanal {before.channel.id}: {e}")

    @commands.Cog.listener("on_member_ban")
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """Hebt Bans in whitelisted Kanälen auf."""
        whitelisted_channels = await self.config.guild(guild).whitelisted_channels()
        if not whitelisted_channels:
            return
        try:
            await guild.unban(user, reason="Moderationsaktion in whitelisted Kanal verhindert.")
            log.info(f"Ban von {user.id} in Gilde {guild.id} aufgehoben.")
            for channel_id in whitelisted_channels:
                channel = guild.get_channel(channel_id)
                if channel:
                    await channel.send(f"**Ban von {user.mention} aufgehoben, da Moderationsaktionen in diesem Kanal verhindert werden.**")
        except discord.errors.Forbidden:
            log.warning(f"Keine Berechtigung, Ban von {user.id} in Gilde {guild.id} aufzuheben.")
        except discord.errors.HTTPException as e:
            log.error(f"Fehler beim Aufheben des Bans in Gilde {guild.id}: {e}")

    @commands.Cog.listener("on_member_remove")
    async def on_member_remove(self, member: discord.Member):
        """Prüft, ob ein Mitglied gekickt wurde, und lädt es in whitelisted Kanälen wieder ein."""
        whitelisted_channels = await self.config.guild(member.guild).whitelisted_channels()
        if not whitelisted_channels:
            return
        try:
            async for entry in member.guild.audit_logs(action=discord.AuditLogAction.kick, limit=1):
                if entry.target.id == member.id and entry.created_at > discord.utils.utcnow() - discord.utils.time_snowflake(discord.utils.time_to_snowflake(5)):
                    try:
                        invite = await member.guild.text_channels[0].create_invite(max_uses=1, reason="Wiederherstellung nach Kick in whitelisted Kanal")
                        await member.send(f"Du wurdest aus {member.guild.name} gekickt, aber in einem whitelisted Kanal wiederhergestellt. Verwende diesen Invite, um zurückzukehren: {invite.url}")
                        log.info(f"Invite an {member.id} gesendet nach Kick in Gilde {member.guild.id}.")
                    except discord.errors.Forbidden:
                        log.warning(f"Keine Berechtigung, Invite für {member.id} in Gilde {member.guild.id} zu erstellen.")
                    except discord.errors.HTTPException as e:
                        log.error(f"Fehler beim Erstellen des Invites für {member.id} in Gilde {member.guild.id}: {e}")
        except discord.errors.Forbidden:
            log.warning(f"Keine Berechtigung, Audit-Logs in Gilde {member.guild.id} zu lesen.")

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