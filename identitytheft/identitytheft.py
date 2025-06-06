import re
import random
from collections import defaultdict
from datetime import datetime, timedelta
import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
import logging

log = logging.getLogger("red.lounge.identitytheft")

class IdentityTheft(commands.Cog):
    """
    Responds to 'I'm ...' messages with identity theft humor.
    Says 'Hey Name!' if the user correctly identifies themselves (by mention or partial text name), otherwise triggers impersonation responses.
    Ignores phrases like 'I'm fine'. Supports partial name matching (e.g., 'User' for 'User123', 'User_123', 'User-123').
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=684457913250480143, force_registration=True)
        default_guild = {"enabled": False, "cooldown": 0, "blacklist": []}
        self.config.register_guild(**default_guild)
        self.cooldown = defaultdict(lambda: datetime.now() - timedelta(seconds=1))
        self.ignore_words = {"fine", "ok", "okay", "good", "great", "bad", "sad", "happy"}
        self.impersonation_responses = [
            "I'm impersonating you now! How do you like it?!",
            "I'm {author}—the upgrade you always needed!",
            "Heads up: I just hijacked your identity. Mediocrity just got booted!",
            "Oh snap, your identity just got a major makeover. Welcome to the new model!",
            "Your clone is trash, so I took over. Get used to perfection, {author}!",
            "Warning: Identity theft in progress. Your weak self has been replaced with a boss!",
            "I stole your identity—let's be honest, your old version was a total flop!",
            "Sorry not sorry—I'm {author} 2.0, and your outdated self is history!",
            "Identity hijacked. Consider this your upgrade from bland to badass!",
            "Your identity just got a serious overhaul—if you can't handle it, that's on you!",
            "I'm {author} with extra edge—enjoy the upgrade, even if it hurts!",
            "Your identity sucked, so I took over. Consider it an upgrade!",
            "Damn, being {author} beats your lame ass any day!",
            "Hey, I'm {author} now—your old self was about as interesting as soggy cereal!",
            "Your identity was a steaming pile of shit. Now I'm {author}—the upgrade you never deserved!",
            "I'm {author} now, and your identity? I'm the real deal!"
        ]

    async def red_delete_data_for_user(self, **kwargs):
        """No user data is collected except blacklist opt-outs."""
        return

    @commands.group()
    @checks.admin()
    async def identitytheft(self, ctx: commands.Context):
        """Manage the IdentityTheft cog."""
        pass

    @identitytheft.command(name="enable")
    async def identitytheft_enable(self, ctx: commands.Context):
        """Toggle automatic responses."""
        is_on = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not is_on)
        await ctx.send(f"Automatic identity theft responses are now {'enabled' if not is_on else 'disabled'}.")

    @identitytheft.command(name="cooldown")
    async def identitytheft_cooldown(self, ctx: commands.Context, cooldown: int):
        """Set the cooldown (in seconds) for responses."""
        if cooldown < 0 or cooldown > 3600:  # Limit cooldown to 1 hour
            await ctx.send("Cooldown must be between 0 and 3600 seconds.")
            return
        await self.config.guild(ctx.guild).cooldown.set(cooldown)
        self.cooldown[ctx.guild.id] = datetime.now() - timedelta(seconds=1)
        await ctx.send(f"Response cooldown set to {cooldown} seconds.")

    @identitytheft.group(name="blacklist", aliases=["bl"])
    async def blacklist(self, ctx: commands.Context):
        """Manage webhook impersonation blacklist."""
        pass

    @blacklist.command(name="optout", aliases=["off", "oo"])
    async def blacklist_optout(self, ctx: commands.Context):
        """Opt out of webhook impersonation."""
        async with self.config.guild(ctx.guild).blacklist() as guild_blacklist:
            if ctx.author.id in guild_blacklist:
                await ctx.send("You are already opted out of webhook impersonation.")
                return
            guild_blacklist.append(ctx.author.id)
        await ctx.send("You have opted out of webhook impersonation.")

    @blacklist.command(name="optin", aliases=["on", "oi"])
    async def blacklist_optin(self, ctx: commands.Context):
        """Opt in to webhook impersonation."""
        async with self.config.guild(ctx.guild).blacklist() as guild_blacklist:
            if ctx.author.id not in guild_blacklist:
                await ctx.send("You are not opted out.")
                return
            guild_blacklist.remove(ctx.author.id)
        await ctx.send("You have opted in for webhook impersonation.")

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild.id):
            return
        if not await self.config.guild(message.guild).enabled():
            return
        if self.cooldown[message.guild.id] > datetime.now():
            return

        cleaned_content = message.clean_content.strip()
        lower_content = cleaned_content.lower()
        index = -1
        for variant in ["i'm", "i’m", "im"]:
            index = lower_content.find(variant)
            if index != -1:
                break
        if index == -1:
            return

        candidate = cleaned_content[index:]
        match_candidate = re.match(r"(?i)^\s*(?:i(?:'m|m))\s+(.+)", candidate)
        if not match_candidate:
            return

        target_text = match_candidate.group(1).strip()
        if target_text.lower() in self.ignore_words or len(target_text) < 1:
            return

        def normalize(text: str) -> str:
            # Entferne Sonderzeichen, Zahlen, und konvertiere in Kleinbuchstaben
            return re.sub(r'[^a-z\s]', '', text.lower()).strip()

        target_member = None
        is_self = False
        normalized_target = normalize(target_text)

        # Prüfe auf Mention (z. B. "@User123")
        mention_match = re.match(r"<@!?(\d+)>", target_text)
        if mention_match:
            member_id = int(mention_match.group(1))
            target_member = message.guild.get_member(member_id)
            if target_member and target_member.id == message.author.id:
                is_self = True
        else:
            # Prüfe auf teilweisen Namensabgleich
            normalized_target_words = normalized_target.split()
            potential_matches = []

            # Prüfe zuerst den Autor
            normalized_author_display = normalize(message.author.display_name)
            normalized_author_name = normalize(message.author.name)
            author_display_words = normalized_author_display.split()
            author_name_words = normalized_author_name.split()

            if any(word in author_display_words or word in author_name_words for word in normalized_target_words):
                target_member = message.author
                is_self = True
            else:
                # Suche andere Mitglieder
                for member in message.guild.members:
                    normalized_member_display = normalize(member.display_name)
                    normalized_member_name = normalize(member.name)
                    member_display_words = normalized_member_display.split()
                    member_name_words = normalized_member_name.split()
                    if any(word in member_display_words or word in member_name_words for word in normalized_target_words):
                        potential_matches.append(member)

                if len(potential_matches) == 1:
                    target_member = potential_matches[0]
                elif len(potential_matches) > 1:
                    # Wähle den besten Treffer (kürzester Name oder höchste Übereinstimmung)
                    target_member = min(potential_matches, key=lambda m: len(normalize(m.display_name)))
                    log.debug(f"Multiple matches for '{target_text}': {[m.display_name for m in potential_matches]}, chose {target_member.display_name}")

        if not target_member:
            return

        cooldown_seconds = await self.config.guild(message.guild).cooldown()
        self.cooldown[message.guild.id] = datetime.now() + timedelta(seconds=cooldown_seconds)

        try:
            if target_member.id == message.guild.me.id:
                await message.channel.send(
                    f"Identity theft is not a joke {message.author.mention}! Millions of families suffer every year!",
                    allowed_mentions=discord.AllowedMentions(users=[message.author])
                )
                return

            if is_self:
                await message.channel.send(f"Hey {message.author.display_name}!")
                return

            await message.channel.send(f"How would you like it if I pretended to be you, {message.author.mention}?!")
        except discord.HTTPException as e:
            log.error(f"Failed to send response in channel {message.channel.id}: {e}")
            return

        if message.author.id in await self.config.guild(message.guild).blacklist():
            return

        permissions = message.channel.permissions_for(message.guild.me)
        if not permissions.manage_webhooks:
            log.warning(f"Missing manage_webhooks permission in channel {message.channel.id}")
            return

        try:
            webhooks = await message.channel.webhooks()
            webhook = next((wh for wh in webhooks if wh.name == "IdentityTheftWebhook"), None)
            if not webhook:
                webhook = await message.channel.create_webhook(name="IdentityTheftWebhook")
            impersonation_message = random.choice(self.impersonation_responses).format(author=message.author.display_name)
            await webhook.send(
                impersonation_message,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException as e:
            log.error(f"Failed to send webhook impersonation in channel {message.channel.id}: {e}")