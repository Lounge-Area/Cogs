import re
import random
from collections import defaultdict
from datetime import datetime, timedelta
import logging

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.commands import Cog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class IdentityTheft(Cog):
    """
    Identity Theft!

    The idea for this cog comes from the Dad cog by Fox-V3.
    It is designed to respond to user messages saying "I'm . . . " with funny messages.
    """

    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=684457913250480143, force_registration=True)
        default_guild = {"enabled": False, "cooldown": 0, "blacklist": []}
        self.config.register_guild(**default_guild)
        self.cooldown = {}  # Regular dict for cooldowns

        self.self_mention_responses = [
            "Yes, we know lol",
            "Woah, Captain Obvious has arrived!",
            "Really? We had no idea.",
            "The sky is blue also.",
            "Oh, look who's talking!",
            "Thanks for the update!",
            "Congratulations, you just stated the obvious.",
            "Oh look, Captain Obvious has graced us with their presence.",
            "Stop—you're going to make the obvious seem revolutionary.",
            "Thanks, Sherlock, but we already knew water is wet.",
            "Wow, your insight is as deep as a puddle.",
            "Hold on, let me alert the media: the obvious just spoke.",
            "Amazing—another reminder that you're, well, you.",
            "Bravo! Your knack for stating the self-evident is unparalleled.",
            "Keep it up, genius. We all needed that groundbreaking update.",
            "Well, that was obvious. Thanks for making it painfully clear.","Wow, you really felt the need to announce that?",
            "Breaking news: You’re still you!",
            "No way, you’re telling us who you are? Mind blown!",
            "Thanks for the memo, we’ll file it under ‘obvious.’",
            "Oh, you’re you? I thought you were someone interesting!",
            "Big reveal, huh? We already knew that one!",
            "You’re preaching to the choir, buddy!",
            "Wait, hold the phone—you’re YOU?!",
            "Groundbreaking discovery: You’re exactly who we thought!",
            "Thanks for clarifying, we were so confused!",
            "Yawn, tell us something we don’t know!",
            "Oh, you’re stating your identity? How original!",
            "Alert the press: You’ve confirmed the obvious!",
            "Great, now we know you’re you. What’s next, 1+1=2?",
            "You’re you? Wow, that’s a plot twist nobody saw coming!",
            "Thanks for the heads-up, but we’ve got eyes!",
            "Whoa, slow down, Einstein, we already figured that out!",
            "You’re dropping truth bombs like they’re obvious!",
            "Congratulations, you’ve mastered stating the obvious!",
            "Next you’ll tell us the sun is hot!"
        ]

        self.impersonation_responses = [
            "I'm impersonating you now! How do you like it?!",
            "I'm {author}—the upgrade your sorry ass always needed!",
            "Heads up: I just hijacked your identity. Mediocrity just got booted!",
            "Oh snap, your identity just got a major makeover. Welcome to the new model!",
            "Your clone is trash, so I took over. Get used to perfection, {author}!",
            "Warning: Identity theft in progress. Your weak self has been replaced with a boss!",
            "I stole your identity—let's be honest, your old version was a total flop!",
            "Sorry not sorry—I'm {author} 2.0, and your outdated self is history!",
            "Identity hijacked. Consider this your upgrade from bland to badass!",
            "Your identity just got a serious overhaul—if you can't handle it, that's on you!",
            "Damn, I just pulled down my pants and no wonder you're so grumpy all the time!",
            "I immediately regret my decision. You do not have much going on.",
            "I'm {author} with extra edge—enjoy the upgrade, even if it hurts!",
            "Fuck yeah, I'm {author} now—upgrade complete, you pathetic excuse for a clone!",
            "Your identity sucked, so I took over. Consider it a fuckin' upgrade!",
            "I just hijacked your sorry ass identity and gave it a badass makeover!",
            "Damn, being {author} beats your lame ass any day!",
            "Hey, I'm {author} now—your old self was about as interesting as soggy cereal!",
            "Aw man, my dick is tiny now!",
            "Your identity was a steaming pile of shit. Now I'm {author}—the upgrade you never deserved!",
            "I'm {author} now, and your identity? Fuck that—I'm the real deal!",
            "Look out, I’m {author} now, and I’m way cooler!",
            "I just stole your vibe, {author}, and I’m rocking it better!",
            "Sorry, {author}, your identity’s mine now—time for an upgrade!",
            "I’m {author} 3.0, and your old self is officially retired!",
            "Boom! I’m {author}, and I make you look like a beta version!",
            "Your identity? Snatched. Meet the new and improved {author}!",
            "I’m {author} now, and let’s just say I’m the premium edition!",
            "Tough luck, {author}, I’m you but with better swagger!",
            "I hijacked your identity, {author}, and I’m making it legendary!",
            "Yo, I’m {author}, and your old self was a total snooze-fest!",
            "Identity theft alert: I’m {author}, and I’m slaying it!",
            "I’m {author} now—consider it a glow-up you never asked for!",
            "Your identity was boring, so I’m {author} with extra spice!",
            "I just took over as {author}, and damn, I’m an improvement!",
            "Say goodbye to lame {author}, I’m the new boss in town!",
            "I’m {author}, and your old self can take a hike!",
            "Identity stolen, {author}! I’m the cooler version now!",
            "I’m {author} now, and your old vibe was straight-up trash!",
            "Guess what, {author}? I’m you, but with actual personality!",
            "I’m {author}, and your identity just got a serious upgrade!"
        ]

    async def red_delete_data_for_user(self, **kwargs):
        """No data is collected from users."""
        return

    @commands.group()
    @checks.admin()
    async def identitytheft(self, ctx: commands.Context):
        """Manage the identity theft auto-response settings for the guild."""
        pass

    @identitytheft.command(name="enable")
    async def identitytheft_enable(self, ctx: commands.Context):
        """Toggle automatic bot responses for identity theft messages."""
        is_on = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not is_on)
        await ctx.send(f"Automatic responses to identity theft messages are now {'enabled' if not is_on else 'disabled'}.")

    @identitytheft.command(name="cooldown")
    async def identitytheft_cooldown(self, ctx: commands.Context, cooldown: int):
        """Set the cooldown (in seconds) for auto responses."""
        if cooldown < 0:
            await ctx.send("Cooldown cannot be negative.")
            return
        if cooldown > 3600:
            await ctx.send("Cooldown cannot exceed 3600 seconds (1 hour).")
            return
        await self.config.guild(ctx.guild).cooldown.set(cooldown)
        self.cooldown[ctx.guild.id] = datetime.now()
        await ctx.send(f"Auto responses cooldown is now set to {cooldown} seconds.")

    @identitytheft.group(name="blacklist", aliases=["bl"])
    async def blacklist(self, ctx: commands.Context):
        """Manage the webhook impersonation blacklist."""
        pass

    @blacklist.command(name="optout", aliases=["off", "oo"])
    async def blacklist_optout(self, ctx: commands.Context):
        """Opt out of having your profile used for webhook impersonation."""
        guild_blacklist = await self.config.guild(ctx.guild).blacklist()
        if ctx.author.id in guild_blacklist:
            await ctx.send("You are already opted out of webhook impersonation.")
            return
        guild_blacklist.append(ctx.author.id)
        await self.config.guild(ctx.guild).blacklist.set(guild_blacklist)
        await ctx.send("You have opted out of webhook impersonation.")

    @blacklist.command(name="optin", aliases=["on", "oi"])
    async def blacklist_optin(self, ctx: commands.Context):
        """Opt in to having your profile used for webhook impersonation."""
        guild_blacklist = await self.config.guild(ctx.guild).blacklist()
        if ctx.author.id not in guild_blacklist:
            await ctx.send("You are not opted out.")
            return
        guild_blacklist.remove(ctx.author.id)
        await self.config.guild(ctx.guild).blacklist.set(guild_blacklist)
        await ctx.send("You have opted in for webhook impersonation.")

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        guild: discord.Guild = message.guild
        if await self.bot.cog_disabled_in_guild(self, guild):
            return

        guild_config = self.config.guild(guild)
        if not await guild_config.enabled():
            return

        # Initialize cooldown if not set
        if guild.id not in self.cooldown:
            self.cooldown[guild.id] = datetime.now() - timedelta(seconds=1)

        # Check cooldown
        if self.cooldown[guild.id] > datetime.now():
            return

        cleaned_content = message.clean_content.strip()
        match_candidate = re.match(r"(?i)^\s*(?:i(?:['’]m|m))\s+(.+)", cleaned_content)
        if not match_candidate:
            return
        target_text = match_candidate.group(1).strip()

        def normalize(text: str) -> str:
            return re.sub(r'[^a-z]', '', text.lower())

        target_member = None
        mention_match = re.match(r"<@!?(\d+)>", target_text)
        if mention_match:
            member_id = int(mention_match.group(1))
            target_member = guild.get_member(member_id)
        else:
            normalized_candidate = normalize(target_text)
            if (normalize(message.author.display_name).startswith(normalized_candidate) or
                    normalize(message.author.name).startswith(normalized_candidate)):
                target_member = message.author
            else:
                for member in guild.members:
                    if (normalize(member.display_name).startswith(normalized_candidate) or
                            normalize(member.name).startswith(normalized_candidate)):
                        target_member = member
                        break

        if target_member is None:
            return

        # Handle bot mention
        if target_member.id == guild.me.id:
            try:
                await message.channel.send(
                    f"Identity theft is not a joke {message.author.mention}! Millions of families suffer every year!"
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to send bot mention response: {e}")
                return
            self.cooldown[guild.id] = datetime.now() + timedelta(seconds=await guild_config.cooldown())
            return

        # Handle self-mention
        if target_member.id == message.author.id:
            response = random.choice(self.self_mention_responses)
            try:
                await message.channel.send(response)
            except discord.HTTPException as e:
                logger.error(f"Failed to send self-mention response: {e}")
                return
            self.cooldown[guild.id] = datetime.now() + timedelta(seconds=await guild_config.cooldown())
            return

        # Handle impersonation attempt
        try:
            await message.channel.send(f"How would you like it if I pretended to be you, {message.author.mention}?!")
        except discord.HTTPException as e:
            logger.error(f"Failed to send impersonation warning: {e}")
            return

        guild_blacklist = await guild_config.blacklist()
        if message.author.id in guild_blacklist:
            self.cooldown[guild.id] = datetime.now() + timedelta(seconds=await guild_config.cooldown())
            return

        permissions = message.channel.permissions_for(guild.me)
        if not permissions.manage_webhooks:
            self.cooldown[guild.id] = datetime.now() + timedelta(seconds=await guild_config.cooldown())
            return

        try:
            webhooks = await message.channel.webhooks()
            webhook = next((wh for wh in webhooks if wh.name == "IdentityTheftWebhook"), None)
            if webhook is None:
                webhook = await message.channel.create_webhook(name="IdentityTheftWebhook")
            impersonation_message = random.choice(self.impersonation_responses).format(author=message.author.display_name)
            await webhook.send(
                impersonation_message,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url
            )
        except discord.HTTPException as e:
            logger.error(f"Failed to send webhook message: {e}")
            await message.channel.send("Failed to send webhook message.")
            return

        self.cooldown[guild.id] = datetime.now() + timedelta(seconds=await guild_config.cooldown())