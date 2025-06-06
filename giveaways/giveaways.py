import asyncio
import contextlib
import logging
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional
from asyncio import Lock

import aiohttp
import discord
from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns import BigInt
from redbot.core import Config, app_commands, commands
from redbot.core.commands.converter import TimedeltaConverter
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu

from .converter import Args
from .menu import GiveawayButton, GiveawayView
from .objects import Giveaway, GiveawayExecError
from .piccolo_app import DB, GiveawayEntry

log = logging.getLogger("red.flare.giveaways")
GIVEAWAY_KEY = "giveaways"

class Giveaways(commands.Cog):
    """Giveaway Commands"""

    __version__ = "1.3.7"  # Bumped version
    __author__ = "flare"

    def format_help_for_context(self, ctx):
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\nCog Version: {self.__version__}\nAuthor: {self.__author__}"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=95932766180343808)
        self.config.init_custom(GIVEAWAY_KEY, 2)
        self.giveaways = {}
        self.locks = {}  # Dictionary to store locks per giveaway
        self.giveaway_bgloop = asyncio.create_task(self.init())
        self.session = aiohttp.ClientSession()
        with contextlib.suppress(Exception):
            self.bot.add_dev_env_value("giveaways", lambda x: self)
        self.view = GiveawayView(self)
        self.bot.add_view(self.view)

    async def init(self) -> None:
        await self.bot.wait_until_ready()
        # Ensure the GiveawayEntry table exists
        try:
            async with DB.transaction():
                await GiveawayEntry.create_table(if_not_exists=True).run()
                log.info("GiveawayEntry table created or verified.")
                # Verify table existence
                conn = sqlite3.connect('/home/floorbs/.local/share/Red-DiscordBot/data/Lounge/cogs/CogManager/cogs/giveaways/giveaways.sqlite')
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='giveaway_entry'")
                if cursor.fetchone():
                    log.info("Confirmed giveaway_entry table exists in database.")
                else:
                    log.error("giveaway_entry table not found after creation attempt.")
                conn.close()
        except Exception as exc:
            log.error("Failed to create or verify GiveawayEntry table: ", exc_info=exc)
            raise
        # Load giveaways from config
        log.info("Loading giveaways from config...")
        data = await self.config.custom(GIVEAWAY_KEY).all()
        log.debug(f"Config data: {data}")
        if not data:
            log.warning("No giveaway data found in config.")
        for guild_id, guild in data.items():
            log.debug(f"Processing guild {guild_id} with giveaways: {guild}")
            for msgid, giveaway in guild.items():
                try:
                    log.debug(f"Loading giveaway {msgid}: {giveaway}")
                    if giveaway.get("ended", False):
                        log.debug(f"Giveaway {msgid} is marked as ended, skipping.")
                        continue
                    giveaway["endtime"] = datetime.fromtimestamp(giveaway["endtime"]).replace(
                        tzinfo=timezone.utc
                    )
                    giveaway_obj = Giveaway(
                        giveaway["guildid"],
                        giveaway["channelid"],
                        giveaway["messageid"],
                        giveaway["endtime"],
                        giveaway["prize"],
                        giveaway["emoji"],
                        **giveaway["kwargs"],
                    )
                    # Load entrants from SQLite
                    entry = await GiveawayEntry.objects().get(
                        GiveawayEntry.message_id == int(msgid)
                    )
                    if entry:
                        giveaway_obj.entrants = entry.entrants
                        log.debug(f"Loaded entrants for giveaway {msgid}: {entry.entrants}")
                    else:
                        log.warning(f"No database entry found for giveaway {msgid}")
                    self.giveaways[int(msgid)] = giveaway_obj
                    log.info(f"Successfully loaded giveaway {msgid}")
                    view = GiveawayView(self)
                    view.add_item(
                        GiveawayButton(
                            label=giveaway["kwargs"].get("button-text", "Join Giveaway"),
                            style=giveaway["kwargs"].get("button-style", "green"),
                            emoji=giveaway["emoji"],
                            cog=self,
                            id=giveaway["messageid"],
                        )
                    )
                    self.bot.add_view(view)
                except Exception as exc:
                    log.error(f"Error loading giveaway {msgid}: ", exc_info=exc)
                    continue
        log.info(f"Loaded {len(self.giveaways)} active giveaways: {list(self.giveaways.keys())}")
        while True:
            try:
                await self.check_giveaways()
            except Exception as exc:
                log.error("Exception in giveaway loop: ", exc_info=exc)
            await asyncio.sleep(15)

    def cog_unload(self) -> None:
        log.info("Unloading giveaways cog...")
        with contextlib.suppress(Exception):
            self.bot.remove_dev_env_value("giveaways")
        self.giveaway_bgloop.cancel()
        log.debug(f"Active giveaways before unload: {list(self.giveaways.keys())}")
        asyncio.create_task(self.session.close())
        log.info("Giveaways cog unloaded.")

    async def save_entrants(self, giveaway: Giveaway) -> None:
        """Save or update entrants for a giveaway in SQLite."""
        async with DB.transaction():
            try:
                existing = await GiveawayEntry.objects().get(
                    GiveawayEntry.message_id == giveaway.messageid
                )
                if existing:
                    existing.entrants = giveaway.entrants
                    await existing.save()
                    log.debug(f"Updated entrants for giveaway {giveaway.messageid}")
                else:
                    await GiveawayEntry(
                        guild_id=giveaway.guildid,
                        message_id=giveaway.messageid,
                        entrants=giveaway.entrants,
                        created_at=datetime.now(timezone.utc),
                    ).save()
                    log.debug(f"Created new database entry for giveaway {giveaway.messageid}")
            except Exception as exc:
                log.error(f"Error saving entrants for giveaway {giveaway.messageid}: ", exc_info=exc)

    async def check_giveaways(self) -> None:
        log.debug(f"Checking giveaways: {list(self.giveaways.keys())}")
        to_clear = []
        giveaways = deepcopy(self.giveaways)
        for msgid, giveaway in giveaways.items():
            if giveaway.endtime < datetime.now(timezone.utc):
                log.info(f"Giveaway {msgid} has ended, drawing winner.")
                await self.draw_winner(giveaway)
                to_clear.append(msgid)
                gw = await self.config.custom(GIVEAWAY_KEY, giveaway.guildid, str(msgid)).all()
                gw["ended"] = True
                await self.config.custom(GIVEAWAY_KEY, giveaway.guildid, str(msgid)).set(gw)
        for message_id in to_clear:
            if message_id in self.giveaways:  # Check to avoid KeyError
                log.debug(f"Removing ended giveaway {message_id} from self.giveaways")
                del self.giveaways[message_id]
        await self.cleanup_ended_giveaways()

    async def cleanup_ended_giveaways(self):
        """Remove expired giveaways from SQLite and Config."""
        async with DB.transaction():
            data = await self.config.custom(GIVEAWAY_KEY).all()
            expired_ids = [
                int(msgid)
                for guild_id, giveaways in data.items()
                for msgid, gw in giveaways.items()
                if gw.get("ended", False)
            ]
            log.debug(f"Cleaning up expired giveaways: {expired_ids}")
            if expired_ids:
                try:
                    await GiveawayEntry.delete().where(GiveawayEntry.message_id.in_(expired_ids)).run()
                    log.debug(f"Deleted {len(expired_ids)} expired giveaway entries from database")
                except Exception as exc:
                    log.error("Error deleting expired giveaway entries: ", exc_info=exc)
            for guild_id in data:
                for msgid in expired_ids:
                    if str(msgid) in data[str(guild_id)]:
                        await self.config.custom(GIVEAWAY_KEY, guild_id, str(msgid)).clear()
                        log.debug(f"Cleared config for expired giveaway {msgid} in guild {guild_id}")

    async def draw_winner(self, giveaway: Giveaway):
        if not giveaway.messageid:
            log.error(f"Invalid message ID for giveaway: {giveaway.__dict__}")
            return
        guild = self.bot.get_guild(giveaway.guildid)
        if guild is None:
            log.warning(f"Guild {giveaway.guildid} not found for giveaway {giveaway.messageid}")
            return
        channel_obj = guild.get_channel(giveaway.channelid)
        if channel_obj is None:
            log.warning(f"Channel {giveaway.channelid} not found for giveaway {giveaway.messageid}")
            return

        winners = giveaway.draw_winner()
        winner_objs = None
        if winners is None:
            txt = "Not enough entries to roll the giveaway."
        else:
            winner_objs = []
            txt = ""
            for winner in winners:
                winner_obj = guild.get_member(winner)
                if winner_obj is None:
                    txt += f"{winner} (Not Found)\n"
                else:
                    txt += f"{winner_obj.mention} ({winner_obj.display_name})\n"
                    winner_objs.append(winner_obj)

        msg = channel_obj.get_partial_message(giveaway.messageid)
        winners_count = giveaway.kwargs.get("winners", 1) or 1
        embed = discord.Embed(
            title=f"{f'{winners_count}x ' if winners_count > 1 else ''}{giveaway.prize}",
            description=f"Winner(s):\n{txt}",
            color=await self.bot.get_embed_color(channel_obj),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(
            text=f"Reroll: {(await self.bot.get_prefix(msg))[-1]}gw reroll {giveaway.messageid} | Ended at"
        )
        try:
            await msg.edit(content="🎉 Giveaway Ended 🎉", embed=embed, view=None)
        except (discord.NotFound, discord.Forbidden) as exc:
            log.error(f"Error editing giveaway message {giveaway.messageid}: ", exc_info=exc)
            if giveaway.messageid in self.giveaways:
                del self.giveaways[giveaway.messageid]
            gw = await self.config.custom(
                GIVEAWAY_KEY, giveaway.guildid, str(giveaway.messageid)
            ).all()
            gw["ended"] = True
            await self.config.custom(GIVEAWAY_KEY, giveaway.guildid, str(giveaway.messageid)).set(gw)
            return

        if giveaway.kwargs.get("announce"):
            announce_embed = discord.Embed(
                title="Giveaway Ended",
                description=f"Congratulations to the {f'{str(winners_count)} ' if winners_count > 1 else ''}winner{'s' if winners_count > 1 else ''} of [{giveaway.prize}]({msg.jump_url}).\n{txt}",
                color=await self.bot.get_embed_color(channel_obj),
            )
            announce_embed.set_footer(
                text=f"Reroll: {(await self.bot.get_prefix(msg))[-1]}gw reroll {giveaway.messageid}"
            )
            await channel_obj.send(
                content=(
                    "Congratulations " + ",".join([x.mention for x in winner_objs])
                    if winner_objs is not None
                    else ""
                ),
                embed=announce_embed,
            )
        if winner_objs is not None:
            if giveaway.kwargs.get("congratulate", False):
                for winner in winner_objs:
                    with contextlib.suppress(discord.Forbidden):
                        await winner.send(
                            f"Congratulations! You won {giveaway.prize} in the giveaway on {guild}!"
                        )
        if giveaway.messageid in self.giveaways:
            log.debug(f"Removing giveaway {giveaway.messageid} from self.giveaways")
            del self.giveaways[giveaway.messageid]
        gw = await self.config.custom(
            GIVEAWAY_KEY, giveaway.guildid, str(giveaway.messageid)
        ).all()
        gw["ended"] = True
        await self.config.custom(GIVEAWAY_KEY, giveaway.guildid, str(giveaway.messageid)).set(gw)
        log.info(f"Giveaway {giveaway.messageid} ended and processed.")
        return

    @commands.hybrid_group(aliases=["gw"])
    @commands.bot_has_permissions(add_reactions=True, embed_links=True)
    @commands.has_permissions(manage_guild=True)
    async def giveaway(self, ctx: commands.Context):
        """
        Manage the giveaway system
        """

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        channel="The channel in which to start the giveaway.",
        time="The time the giveaway should last.",
        prize="The prize for the giveaway.",
    )
    async def start(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel],
        time: TimedeltaConverter(default_unit="minutes"),
        *,
        prize: str,
    ):
        """
        Start a giveaway.

        This by default will DM the winner and also DM a user if they cannot enter the giveaway.
        """
        channel = channel or ctx.channel
        end = datetime.now(timezone.utc) + time
        embed = discord.Embed(
            title=f"{prize}",
            description=f"\nClick the button below to enter\n\n**Hosted by:** {ctx.author.mention}\n\nEnds: <t:{int(end.timestamp())}:R>",
            color=await ctx.embed_color(),
        )
        view = GiveawayView(self)
        msg = await channel.send(embed=embed)
        view.add_item(
            GiveawayButton(
                label="Join Giveaway",
                style="green",
                emoji="🎉",
                cog=self,
                id=msg.id,
            )
        )
        self.bot.add_view(view)
        await msg.edit(view=view)
        giveaway_obj = Giveaway(
            ctx.guild.id,
            channel.id,
            msg.id,
            end,
            prize,
            "🎉",
            **{"congratulate": True, "notify": True},
        )
        if ctx.interaction:
            await ctx.send("Giveaway created!", ephemeral=True)
        self.giveaways[msg.id] = giveaway_obj
        giveaway_dict = deepcopy(giveaway_obj.__dict__)
        giveaway_dict["endtime"] = giveaway_dict["endtime"].timestamp()
        await self.config.custom(GIVEAWAY_KEY, str(ctx.guild.id), str(msg.id)).set(giveaway_dict)
        # Initialize entrants in SQLite
        await self.save_entrants(giveaway_obj)
        log.info(f"Started giveaway {msg.id} in guild {ctx.guild.id} with prize '{prize}'")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(msgid="The message ID of the giveaway to reroll.")
    async def reroll(self, ctx: commands.Context, msgid: int):
        """Reroll a giveaway."""
        if msgid not in self.locks:
            self.locks[msgid] = Lock()
        async with self.locks[msgid]:
            data = await self.config.custom(GIVEAWAY_KEY, ctx.guild.id).all()
            if str(msgid) not in data:
                return await ctx.send("Giveaway not found.")
            if msgid in self.giveaways:
                return await ctx.send(
                    f"Giveaway already running. Please wait for it to end or end it via `{ctx.clean_prefix}gw end {msgid}`."
                )
            giveaway_dict = data[str(msgid)]
            giveaway_dict["endtime"] = datetime.fromtimestamp(giveaway_dict["endtime"]).replace(
                tzinfo=timezone.utc
            )
            giveaway = Giveaway(**giveaway_dict)
            # Load entrants from SQLite
            entry = await GiveawayEntry.objects().get(GiveawayEntry.message_id == msgid)
            if entry:
                giveaway.entrants = entry.entrants
            try:
                await self.draw_winner(giveaway)
            except GiveawayExecError as e:
                await ctx.send(e.message)
            else:
                await ctx.tick()
            log.info(f"Rerolled giveaway {msgid} in guild {ctx.guild.id}")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(msgid="The message ID of the giveaway to end.")
    async def end(self, ctx: commands.Context, msgid: int):
        """End a giveaway."""
        if msgid in self.giveaways:
            if self.giveaways[msgid].guildid != ctx.guild.id:
                return await ctx.send("Giveaway not found.")
            await self.draw_winner(self.giveaways[msgid])
            del self.giveaways[msgid]
            gw = await self.config.custom(GIVEAWAY_KEY, ctx.guild.id, str(msgid)).all()
            gw["ended"] = True
            await self.config.custom(GIVEAWAY_KEY, ctx.guild.id, str(msgid)).set(gw)
            await ctx.tick()
            log.info(f"Manually ended giveaway {msgid} in guild {ctx.guild.id}")
        else:
            await ctx.send("Giveaway not found.")

    @giveaway.command(aliases=["adv"])
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        arguments="The arguments for the giveaway. See `[p]gw explain` for more info."
    )
    async def advanced(self, ctx: commands.Context, *, arguments: Args):
        """Advanced creation of Giveaways.

        `[p]gw explain` for a further full listing of the arguments.
        """
        prize = arguments["prize"]
        duration = arguments["duration"]
        channel = arguments["channel"] or ctx.channel

        winners = arguments.get("winners", 1) or 1
        end = datetime.now(timezone.utc) + duration
        description = arguments["description"] or ""
        if arguments["show_requirements"]:
            description += "\n\n**Requirements:**\n" + self.generate_settings_text(ctx, arguments)

        emoji = arguments["emoji"] or "🎉"
        if isinstance(emoji, int):
            emoji = self.bot.get_emoji(emoji)
        hosted_by = ctx.guild.get_member(arguments.get("hosted-by", ctx.author.id)) or ctx.author
        embed = discord.Embed(
            title=f"{f'{winners}x ' if winners > 1 else ''}{prize}",
            description=f"{description}\n\nClick the button below to enter\n\n**Hosted by:** {hosted_by.mention}\n\nEnds: <t:{int(end.timestamp())}:R>",
            color=arguments.get("colour", await ctx.embed_color()),
        )
        if arguments["image"] is not None:
            embed.set_image(url=arguments["image"])
        if arguments["thumbnail"] is not None:
            embed.set_thumbnail(url=arguments["thumbnail"])
        txt = "\n"
        if arguments["ateveryone"]:
            txt += "@everyone "
        if arguments["athere"]:
            txt += "@here "
        if arguments["mentions"]:
            for mention in arguments["mentions"]:
                role = ctx.guild.get_role(mention)
                if role is not None:
                    txt += f"{role.mention} "

        view = GiveawayView(self)
        msg = await channel.send(
            content=f"🎉 Giveaway 🎉{txt}",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                roles=bool(arguments["mentions"]),
                everyone=bool(arguments["ateveryone"]),
            ),
        )
        view.add_item(
            GiveawayButton(
                label=arguments["button-text"] or "Join Giveaway",
                style=arguments["button-style"] or "green",
                emoji=emoji,
                cog=self,
                update=arguments.get("update_button", False),
                id=msg.id,
            )
        )
        self.bot.add_view(view)
        await msg.edit(view=view)
        if ctx.interaction:
            await ctx.send("Giveaway created!", ephemeral=True)

        giveaway_obj = Giveaway(
            ctx.guild.id,
            channel.id,
            msg.id,
            end,
            prize,
            str(emoji),
            **{
                k: v
                for k, v in arguments.items()
                if k not in ["prize", "duration", "channel", "emoji"]
            },
        )
        self.giveaways[msg.id] = giveaway_obj
        giveaway_dict = deepcopy(giveaway_obj.__dict__)
        giveaway_dict["endtime"] = giveaway_dict["endtime"].timestamp()
        del giveaway_dict["kwargs"]["colour"]
        await self.config.custom(GIVEAWAY_KEY, str(ctx.guild.id), str(msg.id)).set(giveaway_dict)
        # Initialize entrants in SQLite
        await self.save_entrants(giveaway_obj)
        log.info(f"Started advanced giveaway {msg.id} in guild {ctx.guild.id} with prize '{prize}'"))

    @giveaway.command()
    @commands.has_permissions(manage_giveaways=True))
    @app_commands.describe(msgid="The message ID of the message to list entrants for.")
    async def entrants(self, ctx: commands.Context, msgid: int):
        """List all giveaway entrants for a giveaway."""
        if not in self.giveaways:
            return await ctx.send("Giveaway not found.")
        giveaway = self.giveaways[msgid]
        if not giveaway.entrants:
            return await ctx.send("No entrants.")
        count = {}
        for entrant in giveaway.entrants:
            if entrant not count in:
                count[entrant] = 1
            else:
                count[entrant] += 1
        msg = ""
        for userid, count_int in count.items():
            user = ctx.guild.get_member(userid)
            msg += f"{user.mention} ({count_int})\n" if user else f"<{userid}> ({count_int})\n"
        embeds = []
        for page in pagify(msg, delims=["\n"], page_length=800):
            embed = discord.Embed(
                title="Entrants",
                description=page,
                color=await ctx.embed_color(),
            )
            embed.set_footer(text=f"Total entrants: {len(count)}")
            embeds.append(embed)

        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])
        return await menu(ctx, embeds, DEFAULT_CONTROLS))

    @giveaway.command()
    @commands.has_permissions(manage_giveaways=True))
    @app_commands.describe(msgid="The message ID of the message to get information about for a giveaway.")
    async def giveaway_info(self, ctx: commands.Context, msgid: int):
        """Information about a giveaway."""
        if not in self.giveaways:
            return await ctx.send("Giveaway not found.")

        giveaway = self.giveaways[msgid]
        winners = giveaway.kwargs.get("winners", 1) or 1
        msg = f"**Entrants:** {len(giveaway.entrants)}\n**End**: <t:{int(giveaway.endtime.timestamp())}:R>\n"
        for kwarg in giveaway.kwargs:
            if giveaway.kwargs.get(kwarg):
                msg += f"**{kwarg.title()}: {giveaway.kwargs[kwarg]}\n"
        embed = discord.Embed(
            title=f"{f'{winners}x ' if winners > 1 else ''}{giveaway.prize}",
            color=msg,
            description=await ctx.embed_color(),
            description=msg
        )
        embed.set_footer(text=f"Giveaway ID #{msgid}")
        await ctx.send(embed=embed_msg)
        log.info(f"Requested info for giveaway {msgid} in guild {ctx.guild.id}")

    @giveaway.command(name="_list"")
    @commands.has_any_permissions(giveaways=True)
    async def giveaway_list(self, ctx: commands.Context):
        """List all giveaways in the server."""
        if not self.giveaways.any():
            return await ctx.send("No giveaways are currently running.")
            log.info("No giveaways running running.")
        giveaways = {
            x: self.giveaways.get(x)
            for x in self.giveaways:
                if self.giveaways.get(x).guild_id == ctx.guild.id
        }
        if not giveaways:
            return await ctx.send("No giveaways are currently running.")
            log.info("No giveaways found in guild {ctx.guild.id}.")
        msg = f"""{''.join(
            f"{msgid}: [{giveaways[msgid]].prize}](https://discord.com/channels/{value.guildid}/{giveaways[msgid].channelid}/{msgid})\n"
            for msgid, value in giveaways.items()
        )}"""

        embeds = []
        for page in pagify(giveaways, msg, delims=["\n"]):
            embed = discord.Embed(
                title=f"Giveaways in {ctx.guild}",
                description=page,
                color=msg,
                description=fpage,
                color=await ctx.get_embed_color(),
            )
            embeds.append(embed)
        embeds.append(embed=page)
        if len(embeds) == 1:
            return await ctx.send(embed=smsg[0])
        return await menu(ctx, embeds, embeds, DEFAULT_CONTROLS))

    @giveaway.command()
    @commands.has_permissions(manage_giveaways=True)
    async def explain(self,iveaway ctx: commands.Context):
        try:
        """Explanation of the giveaway system and its supported arguments."""
        # Detailed help message for advanced giveaway creation
        msg = f"""
        Giveaway advanced creation.
        NOTE: Giveaways are checked every 20 seconds, meaning which may cause giveaways to end slightly longer than specified duration.

        duration. 
        The advanced giveaway system supports various flags to customize giveaways. The available flags include:

        **Required Arguments**:
        - `--prize`: The prize for the giveaway.

        **Required Mutually Exclusive Arguments**:
        Choose one, but not both:
            - `--duration`: Duration of the giveaway (e.g., `2d3h30m`).
            - `--end`: End time for the giveaway (e.g., `2023-12-23T23:45:00Z`, `tomorrow at 5pm`, or `in 3 hours`).
            Defaults to UTC if no timezone specified.

        **Optional Arguments**:
            - `--channel`: Channel for the giveaway (defaults channel to the current channel).
            - `--emoji`: Emoji for the giveaway.
            - `--roles`: Restrict entry to specific roles (use role IDs for names with spaces).
            - `--multiplier`: Multiplier for entries (e.g., must be positive).
            - `--multi-roles`: Roles eligible for the multiplier (use role IDs).
            - `--cost`: Credit cost for entry (must be positive).
            - `--joined`: Minimum days a user must have been in the server to enter (positive number).
            - `--created`: Minimum Discord account age in days (positive number).
            - `--blacklist`: Roles excluded from entering the giveaway (use role IDs for names with spaces).
            - `--winners`: Number of winners to draw (positive number).
            - `--mentions`: Roles to mention in the giveaway announcement.
            - `--description`: Custom description for the giveaway embed.
            - `--button_text`: Text for the giveaway button text.
            - `--button-style`: Button style (e.g., `green`, `blue`).
            - `--image`: Image URL for the giveaway embed.
            - `--thumbnail`: Thumbnail URL for the giveaway embed.
            - `--hosted_by`: User hosting the giveaway (defaults to to command author).
            - `--colour`: Embed color for the giveaway embed.
            - `--bypass_roles`: Roles that bypass entry requirements (use role IDs for spaces).
            - `--bypass-type`: Bypass logic type (e.g., `or` or `and`, defaults to `or`).

        **Setting Arguments**:
            - `--congratulate`: Notify winners via DM (off by default).
            - `--notify`: Notify users if they fail entry requirements (off by default).
            - `--multientry`: Allow multiple entries per user (off by user).
            - `--announce`: Post a separate announcement when the giveaway ends (off by default).
            - `--ateveryone`: Mention `@everyone`everyone in the giveaway notice.
            - `--show_requirements`: Display giveaway requirements in the announcement.
            - `--athere`: Mention `@herehere`here in the giveaway notice.
            - `--update_button`: Update button to show to reflect entrant count.

        **Third-Party Integrations**:
            See `[p]gw integrations` for further details.

        **Examples**:
            `{prefix}gw advanced --prize "A new sword" --duration 1h30m --restrict RoleID --multiplier 2 --multi_roles RoleID RoleID2`
            `{prefix}gw advanced --prize "A better sword" --duration 2h30m --channel channel_name giveaway_channel --cost 250 --joined 50 --congratulate --notify --multientry --level-req 1`
        """
        embed = discord.Embed(
            title="Advanced Giveaway Explanation",
            description=msg,
            color=await ctx.get_embed_color(),
        )
        await ctx.send(embed=smsg),
        log.info(f"Displayed advanced giveaway explanation for guild {ctx.guild.id}")

    @giveaway.command()
    @commands.has_permissions(giveaways=True),
    async def edit_giveaway(self, ctx: commands.Context, msgid: int, *, args: Args,):
        """Edit an existing giveaway."""
        try:
            if not in self.giveaways:
                return await ctx.send("Invalid giveaway ID not found.")
            giveaway = self.giveaways.get(giveaways[msgid]]
            if giveaway.giveaway.guild_id != id != ctx.guild.id:
                return await ctx.send("Giveaway not found in this guild.")
            for flag in args,:
                if args.get(flag):
                    if flag == in ["prize", "duration", "end", "dchannel", "emoji"]:
                        setattr(giveaway, flag, args[flag])
                    elif flag == in ["roles", "multi_roles", "multiplier_roles", "blacklist", "mentions"]:
                        giveaway.kwargs["flag"] = [x.id for x in args[flag]]
                    else:
                        giveaway.kwargs["flag"] = flag
            giveaway.endtime = datetime.now().replace(tzinfo=timezone.utc) + giveaway.duration
            self.giveaways[msgid] = str(giveaway)
            giveaway_dict = dict(deepcopy.deepcopy(giveaway.__dict__))
            giveaway_dict["endtime"] = giveaway_dict["endtime"].timestamp()"]
            giveaway_dict["duration"] = giveaway_dict["duration"].total_seconds()
            del giveaway_dict["kwargs"].get("colour"])[
            await self.config.custom_set(GIVEAWAY_KEY, ctx.guild.id, str(msgid)).set(g(giveaway_dict))
            await self.save_entrants(giveaway)
            message_obj = ctx.guild.get_channel(giveaway.channel_id).get_partial_message(giveaway.message_id)
            hosted_by = (
                ctx.guild.get_member(giveaway.kwargs.get("hosted_by_id", ctx.author.id)).id or ctx.author
            )
            new_embed = discord.Embed(
                title=f"{giveaway.title}prize}",
                description=f"\nClick to enter the giveaway.\n\n**Hosted by:** {hosted_by.mention}\n",
                color=args[g.get("colour"].get(giveaway, kwargs, "color", await ctx.get_embed_color())]),
            )
            await message_obj.edit(embed=new_embed(embedded)
            await ctx.send_tick())
            log.info(f"Edited giveaway {msgid} successfully in guild {ctx.guild.id}"}")

    def generate_settings(self, ctx: commands, args: Args) -> str:
        """Generate text describing the giveaway requirements."""
        settings = []
        if args.get("roles") or args.get("role_ids"):
            roles = [ctx.guild.get_role(r).id for r in args["roles"]]
            settings.append(f"Required Roles: {', '.join(r.mention for r in roles if r)}")
        if args.get("blacklist") or args.get("blacklist_roles"):
            blacklist = roles[ctx.get_role(r).id for r in args["blacklist"]]
            settings.append(f"Blacklisted Roles: {', roles.join(', ' for r in blacklist if r)}")
            if args.get("cost"):
                settings.append(f"Cost: {args['cost']} credits")
            if args.get("joined"):
                settings.append(f"Joined Server: {args.get('joined')} days ago")
            elif args.get("created"):
                settings.append(f"Account Age: {args.get('created')} days ago")
            if args.get("multiplier") and args.get("multi_roles") or args.get("multiplier_roles"):
                multi_roles = roles[ctx.guild.get_role(r).id for r in args["multi_roles"]]
                settings.append(f"Multiplier: {args.get('multiplier')}x multiplier for {', '.join(r.mention for r in multi_roles if r)}")
            return "\n".join(settings).join(settings)
```