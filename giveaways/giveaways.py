import asyncio
import contextlib
import logging
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
from redbot.core.data_manager import cog_data_path

from .converter import Args
from .menu import GiveawayButton, GiveawayView
from .objects import Giveaway, GiveawayExecError
from .piccolo_app import DB, GiveawayEntry

log = logging.getLogger("red.flare.giveaways")
GIVEAWAY_KEY = "giveaways"

class Giveaways(commands.Cog):
    """Giveaway Commands"""

    __version__ = "1.0.3"
    __author__ = "flare"

    def format_help_for_context(self, ctx):
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\nCog Version: {self.__version__}\nAuthor: {self.__author__}"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=95932766180343808)
        self.config.init_custom(GIVEAWAY_KEY, 2)
        self.giveaways = {}
        self.locks = {}
        self.giveaway_bgloop = asyncio.create_task(self.init())
        self.session = aiohttp.ClientSession()
        with contextlib.suppress(Exception):
            self.bot.add_dev_env_value("giveaways", lambda x: self)
        self.view = GiveawayView(self)
        self.bot.add_view(self.view)

    async def init(self) -> None:
        await self.bot.wait_until_ready()
        try:
            async with DB.transaction():
                await GiveawayEntry.create_table(if_not_exists=True).run()
                log.info("GiveawayEntry table created or verified.")
        except Exception as exc:
            log.error("Failed to create or verify GiveawayEntry table: ", exc_info=exc)
            raise
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
                    # Handle legacy 'title' key by mapping to 'prize'
                    if "title" in giveaway and "prize" not in giveaway:
                        log.warning(f"Giveaway {msgid} uses legacy 'title' key, mapping to 'prize'.")
                        giveaway["prize"] = giveaway["title"]
                    if not all(key in giveaway for key in ["guildid", "channelid", "messageid", "endtime", "prize", "emoji"]):
                        log.error(f"Giveaway {msgid} missing required keys: {giveaway}")
                        continue
                    try:
                        endtime = datetime.fromtimestamp(giveaway["endtime"], tz=timezone.utc)
                        log.debug(f"Parsed endtime for giveaway {msgid}: {endtime}")
                    except (TypeError, ValueError) as exc:
                        log.error(f"Invalid endtime for giveaway {msgid}: {exc}")
                        continue
                    if endtime < datetime.now(timezone.utc):
                        log.warning(f"Giveaway {msgid} endtime {endtime} is in the past, marking as ended.")
                        giveaway["ended"] = True
                        await self.config.custom(GIVEAWAY_KEY, guild_id, str(msgid)).set(giveaway)
                        continue
                    giveaway_obj = Giveaway(
                        giveaway["guildid"],
                        giveaway["channelid"],
                        giveaway["messageid"],
                        endtime,
                        giveaway["prize"],
                        giveaway["emoji"],
                        **giveaway.get("kwargs", {}),
                    )
                    try:
                        entry = await GiveawayEntry.objects().get(
                            GiveawayEntry.message_id == int(msgid)
                        )
                        if entry:
                            if not isinstance(entry.created_at, datetime):
                                log.warning(f"Invalid created_at for giveaway {msgid}, resetting.")
                                entry.created_at = datetime.now(timezone.utc)
                                await entry.save()
                            giveaway_obj.entrants = entry.entrants
                            log.debug(f"Loaded entrants for giveaway {msgid}: {entry.entrants}")
                        else:
                            log.warning(f"No database entry found for giveaway {msgid}, creating empty entry.")
                            await GiveawayEntry(
                                guild_id=giveaway["guildid"],
                                message_id=int(msgid),
                                entrants=[],
                                created_at=datetime.now(timezone.utc),
                            ).save()
                    except Exception as exc:
                        log.error(f"Error loading entrants for giveaway {msgid}: ", exc_info=exc)
                        continue
                    self.giveaways[int(msgid)] = giveaway_obj
                    log.info(f"Successfully loaded giveaway {msgid}")
                    view = GiveawayView(self)
                    view.add_item(
                        GiveawayButton(
                            label=giveaway.get("kwargs", {}).get("button-text", "Join Giveaway"),
                            style=giveaway.get("kwargs", {}).get("button-style", "green"),
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

    async def cog_unload(self) -> None:
        log.info("Unloading giveaways cog...")
        try:
            for msgid, giveaway in self.giveaways.items():
                try:
                    await self.save_entrants(giveaway)
                    giveaway_dict = deepcopy(giveaway.__dict__)
                    giveaway_dict["endtime"] = giveaway_dict["endtime"].timestamp()
                    giveaway_dict["kwargs"] = giveaway_dict.get("kwargs", {})
                    await self.config.custom(GIVEAWAY_KEY, str(giveaway.guildid), str(msgid)).set(giveaway_dict)
                    log.debug(f"Saved giveaway {msgid} to config and database.")
                except Exception as exc:
                    log.error(f"Failed to save giveaway {msgid} during unload: ", exc_info=exc)
        except Exception as exc:
            log.error("Error during cog unload: ", exc_info=exc)
        with contextlib.suppress(Exception):
            self.bot.remove_dev_env_value("giveaways")
        self.giveaway_bgloop.cancel()
        log.debug(f"Active giveaways before unload: {list(self.giveaways.keys())}")
        await self.session.close()
        log.info("Giveaways cog unloaded.")

    async def save_entrants(self, giveaway: Giveaway) -> None:
        async with DB.transaction():
            try:
                existing = await GiveawayEntry.objects().get(
                    GiveawayEntry.message_id == giveaway.messageid
                )
                if existing:
                    existing.entrants = giveaway.entrants
                    existing.updated_at = datetime.now(timezone.utc)
                    if not isinstance(existing.created_at, datetime):
                        log.warning(f"Invalid created_at for giveaway {giveaway.messageid}, resetting.")
                        existing.created_at = datetime.now(timezone.utc)
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
                raise

    async def check_giveaways(self) -> None:
        log.debug(f"Checking giveaways: {list(self.giveaways.keys())}")
        to_clear = []
        giveaways = deepcopy(self.giveaways)
        for msgid, giveaway in giveaways.items():
            try:
                if giveaway.endtime < datetime.now(timezone.utc):
                    log.info(f"Giveaway {msgid} endtime {giveaway.endtime} is in the past, drawing winner.")
                    await self.draw_winner(giveaway)
                    to_clear.append(msgid)
                    gw = await self.config.custom(GIVEAWAY_KEY, str(giveaway.guildid), str(msgid)).all()
                    gw["ended"] = True
                    await self.config.custom(GIVEAWAY_KEY, str(giveaway.guildid), str(msgid)).set(gw)
            except Exception as exc:
                log.error(f"Error checking giveaway {msgid}: ", exc_info=exc)
        for message_id in to_clear:
            if message_id in self.giveaways:
                log.debug(f"Removing ended giveaway {message_id} from self.giveaways")
                del self.giveaways[message_id]
        await self.cleanup_ended_giveaways()

    async def cleanup_ended_giveaways(self):
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
            color=discord.Color.blue(),
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
                GIVEAWAY_KEY, str(giveaway.guildid), str(giveaway.messageid)
            ).all()
            gw["ended"] = True
            await self.config.custom(GIVEAWAY_KEY, str(giveaway.guildid), str(giveaway.messageid)).set(gw)
            return

        if giveaway.kwargs.get("announce"):
            announce_embed = discord.Embed(
                title="Giveaway Ended",
                description=f"Congratulations to the {f'{str(winners_count)} ' if winners_count > 1 else ''}winner{'s' if winners_count > 1 else ''} of [{giveaway.prize}]({msg.jump_url}).\n{txt}",
                color=discord.Color.blue(),
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
            GIVEAWAY_KEY, str(giveaway.guildid), str(giveaway.messageid)
        ).all()
        gw["ended"] = True
        await self.config.custom(GIVEAWAY_KEY, str(giveaway.guildid), str(giveaway.messageid)).set(gw)
        log.info(f"Giveaway {giveaway.messageid} ended successfully in guild {guild.id} with prize '{giveaway.prize}'")

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
        time: TimedeltaConverter,
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
            description=f"\nClick the button below to enter the giveaway\n\n**Hosted by:** {ctx.author.mention}\n\nEnds: <t:{int(end.timestamp())}:R>",
            color=discord.Color.blue(),
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
        if ctx.interaction:
            await ctx.send("Giveaway created!", ephemeral=True)
        giveaway_obj = Giveaway(
            ctx.guild.id,
            channel.id,
            msg.id,
            end,
            prize,
            "🎉",
            winners=1,
        )
        self.giveaways[msg.id] = giveaway_obj
        giveaway_dict = deepcopy(giveaway_obj.__dict__)
        giveaway_dict["endtime"] = giveaway_dict["endtime"].timestamp()
        await self.config.custom(GIVEAWAY_KEY, str(ctx.guild.id), str(msg.id)).set(giveaway_dict)
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
            data = await self.config.custom(GIVEAWAY_KEY, str(ctx.guild.id)).all()
            if str(msgid) not in data:
                return await ctx.send("Giveaway not found.")
            if msgid in self.giveaways:
                return await ctx.send(
                    f"Giveaway already running. Please wait for it to end or end it via `{ctx.clean_prefix}gw end {msgid}`."
                )
            giveaway_dict = data[str(msgid)]
            try:
                giveaway_dict["endtime"] = datetime.fromtimestamp(giveaway_dict["endtime"], tz=timezone.utc)
            except (TypeError, ValueError) as exc:
                log.error(f"Invalid endtime for reroll of giveaway {msgid}: {exc}")
                return await ctx.send("Invalid giveaway endtime. Check logs for details.")
            if not all(key in giveaway_dict for key in ["guildid", "channelid", "messageid", "prize", "emoji"]):
                log.error(f"Giveaway {msgid} missing required keys for reroll: {giveaway_dict}")
                return await ctx.send("Invalid giveaway data. Check logs for details.")
            giveaway = Giveaway(**giveaway_dict)
            try:
                entry = await GiveawayEntry.objects().get(GiveawayEntry.message_id == msgid)
                if entry:
                    if not isinstance(entry.created_at, datetime):
                        log.warning(f"Invalid created_at for giveaway {msgid}, resetting.")
                        entry.created_at = datetime.now(timezone.utc)
                        await entry.save()
                    giveaway.entrants = entry.entrants
            except Exception as exc:
                log.error(f"Error loading entrants for reroll of giveaway {msgid}: ", exc_info=exc)
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
            try:
                await self.draw_winner(self.giveaways[msgid])
                #del self.giveaways[msgid]
                gw = await self.config.custom(GIVEAWAY_KEY, str(ctx.guild.id), str(msgid)).all()
                gw["ended"] = True
                await self.config.custom(GIVEAWAY_KEY, str(ctx.guild.id), str(msgid)).set(gw)
                await ctx.tick()
                log.info(f"Manually ended giveaway {msgid} in guild {ctx.guild.id}")
            except Exception as exc:
                log.error(f"Error ending giveaway {msgid}: ", exc_info=exc)
                await ctx.send("Error ending giveaway. Check logs for details.")
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
            color=discord.Color.blue(),
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
        await self.save_entrants(giveaway_obj)
        log.info(f"Started advanced giveaway {msg.id} in guild {ctx.guild.id} with prize '{prize}'")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(msgid="The message ID of the giveaway to list entrants for.")
    async def entrants(self, ctx: commands.Context, msgid: int):
        """List all entrants for a giveaway."""
        if msgid not in self.giveaways:
            return await ctx.send("Giveaway not found.")
        giveaway = self.giveaways[msgid]
        if not giveaway.entrants:
            return await ctx.send("No entrants.")
        count = {}
        for entrant in giveaway.entrants:
            if entrant not in count:
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
                color=discord.Color.blue(),
            )
            embed.set_footer(text=f"Total entrants: {len(count)}")
            embeds.append(embed)
        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])
        return await menu(ctx, embeds, DEFAULT_CONTROLS)

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(msgid="The message ID of the giveaway to get info for.")
    async def info(self, ctx: commands.Context, msgid: int):
        """Information about a giveaway."""
        if msgid not in self.giveaways:
            return await ctx.send("Giveaway not found.")
        giveaway = self.giveaways[msgid]
        winners = giveaway.kwargs.get("winners", 1) or 1
        msg = f"**Entrants:** {len(giveaway.entrants)}\n**End**: <t:{int(giveaway.endtime.timestamp())}:R>\n"
        for kwarg in giveaway.kwargs:
            if giveaway.kwargs[kwarg]:
                msg += f"**{kwarg.title()}:** {giveaway.kwargs[kwarg]}\n"
        embed = discord.Embed(
            title=f"{f'{winners}x ' if winners > 1 else ''}{giveaway.prize}",
            color=discord.Color.blue(),
            description=msg,
        )
        embed.set_footer(text=f"Giveaway ID #{msgid}")
        await ctx.send(embed=embed)

    @giveaway.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def _list(self, ctx: commands.Context):
        """List all giveaways in the server."""
        if not self.giveaways:
            return await ctx.send("No giveaways are running.")
        giveaways = {
            x: self.giveaways[x]
            for x in self.giveaways
            if self.giveaways[x].guildid == ctx.guild.id
        }
        if not giveaways:
            return await ctx.send("No giveaways are running.")
        msg = "".join(
            f"{msgid}: [{giveaways[msgid].prize}](https://discord.com/channels/{value.guildid}/{giveaways[msgid].channelid}/{msgid})\n"
            for msgid, value in giveaways.items()
        )
        embeds = []
        for page in pagify(msg, delims=["\n"]):
            embed = discord.Embed(
                title=f"Giveaways in {ctx.guild}",
                description=page,
                color=discord.Color.blue(),
            )
            embeds.append(embed)
        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])
        return await menu(ctx, embeds, DEFAULT_CONTROLS)

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def explain(self, ctx: commands.Context):
        """Explanation of giveaway advanced and the arguments it supports."""
        msg = """
        Giveaway advanced creation.
        NOTE: Giveaways are checked every 15 seconds, this means that the giveaway may end up being slightly longer than the specified duration.

        Giveaway advanced contains many different flags that can be used to customize the giveaway.
        The flags are as follows:

        Required arguments:
        `--prize`: The prize to be won.

        Required Mutual Exclusive Arguments:
        You must one ONE of these, but not both:
        `--duration`: The duration of the giveaway. Must be in format such as `2d3h30m`.
        `--end`: The end time of the giveaway. Must be in format such as `2026-09-05T00:00+02:00`, `tomorrow at 3am`, `in 4 hours`. Defaults to UTC if no timezone is provided.

        Optional arguments:
        `--channel`: The channel to post the giveaway in. Will default to this channel if not specified.
        `--emoji`: The emoji to use for the giveaway.
        `--roles`: Roles that the giveaway will be restricted to. If the role contains a space, use their ID.
        `--multiplier`: Multiplier for those in specified roles. Must be a positive number.
        `--multi-roles`: Roles that will receive the multiplier. If the role contains a space, use their ID.
        `--cost`: Cost of credits to enter the giveaway. Must be a positive number.
        `--joined`: How long the user must be a member of the server for to enter the giveaway. Must be a positive number of days.
        `--created`: How long the user has been on discord for to enter the giveaway. Must be a positive number of days.
        `--blacklist`: Blacklisted roles that cannot enter the giveaway. If the role contains a space, use their ID.
        `--winners`: How many winners to draw. Must be a positive number.
        `--mentions`: Roles to mention in the giveaway notice.
        `--description`: Description of the giveaway.
        `--button-text`: Text to use for the button.
        `--button-style`: Style to use for the button.
        `--image`: Image URL to use for the giveaway embed.
        `--thumbnail`: Thumbnail URL to use for the giveaway embed.
        `--hosted-by`: User of the user hosting the giveaway. Defaults to the author of the command.
        `--colour`: Colour to use for the giveaway embed.
        `--bypass-roles`: Roles that bypass the requirements. If the role contains a space, use their ID.

        Setting Arguments:
        `--congratulate`: Whether or not to congratulate the winner. Not passing will default to off.
        `--notify`: Whether or not to notify a user if they failed to enter the giveaway. Not passing will default to off.
        `--multientry`: Whether or not to allow multiple entries. Not passing will default to off.
        `--announce`: Whether to post a separate message when the giveaway ends. Not passing will default to off.
        `--ateveryone`: Whether to tag @everyone in the giveaway notice.
        `--show-requirements`: Whether to show the requirements of the giveaway.
        `--athere`: Whether to tag @here in the giveaway notice.
        `--update-button`: Whether to update the button with the number of entrants.

        3rd party integrations:
        See `[p]gw integrations` for more information.

        Examples:
        `{prefix}gw advanced --prize A new sword --duration 1h30m --restrict Role ID --multiplier 2 --multi-roles RoleID RoleID2`
        `{prefix}gw advanced --prize A better sword --duration 2h3h30m --channel channel-name --cost 250 --joined 50 days --congratulate --notify --multientry --level-req 100`
        """.format(prefix=ctx.clean_prefix)
        embed = discord.Embed(
            title="Giveaway Advanced Explanation",
            description=msg,
            color=discord.Color.blue(),
        )
        await ctx.send(embed=embed)

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def edit(self, ctx, msgid: int, *, flags: Args):
        """Edit a giveaway.

        See `[p]gw explain` for more info on the flags.
        """
        if msgid not in self.giveaways:
            return await ctx.send("Giveaway not found.")
        giveaway = self.giveaways[msgid]
        if giveaway.guildid != ctx.guild.id:
            return await ctx.send("Giveaway not found.")
        for flag in flags:
            if flags[flag]:
                if flag in ["prize", "duration", "channel", "emoji"]:
                    setattr(giveaway, flag, flags[flag])
                elif flag in ["roles", "multi_roles", "blacklist", "mentions"]:
                    giveaway.kwargs[flag] = [x.id for x in flags[flag]]
                else:
                    giveaway.kwargs[flag] = flags[flag]
        giveaway.endtime = datetime.now(timezone.utc) + giveaway.duration
        self.giveaways[msgid] = giveaway
        giveaway_dict = deepcopy(giveaway.__dict__)
        giveaway_dict["endtime"] = giveaway_dict["endtime"].timestamp()
        giveaway_dict["duration"] = giveaway_dict["duration"].total_seconds()
        del giveaway_dict["kwargs"]["colour"]
        await self.config.custom(GIVEAWAY_KEY, str(ctx.guild.id), str(msgid)).set(giveaway_dict)
        await self.save_entrants(giveaway)
        message = ctx.guild.get_channel(giveaway.channelid).get_partial_message(giveaway.messageid)
        hosted_by = (
            ctx.guild.get_member(giveaway.kwargs.get("hosted_id", ctx.author.id)) or ctx.author
        )
        new_embed = discord.Embed(
            title=f"{giveaway.prize}",
            description=f"\nClick the button below to enter\n\n**Hosted by:** {hosted_by.mention}\n",
            color=discord.Color.blue(),
        )
        await message.edit(embed=new_embed)
        await ctx.tick()
        log.info(f"Edited giveaway {msgid} in guild {ctx.guild.id}")

    @giveaway.command()
    @commands.is_owner()
    async def debug_config(self, ctx: commands.Context):
        """Dump giveaway config data."""
        data = await self.config.custom(GIVEAWAY_KEY).all()
        await ctx.send(f"Config: {data}")

    def generate_settings_text(self, ctx: commands.Context, arguments: Args) -> str:
        """Generate text describing giveaway requirements."""
        settings = []
        if arguments.get("roles"):
            roles = [ctx.guild.get_role(r) for r in arguments["roles"]]
            settings.append(f"Required Roles: {', '.join(r.mention for r in roles if r)}")
        if arguments.get("blacklist"):
            blacklist = [ctx.guild.get_role(r) for r in arguments["blacklist"]]
            settings.append(f"Blacklisted Roles: {', '.join(r.mention for r in blacklist if r)}")
        if arguments.get("cost"):
            settings.append(f"Cost: {arguments['cost']} credits")
        if arguments.get("joined"):
            settings.append(f"Joined Server: {arguments['joined']} days")
        if arguments.get("created"):
            settings.append(f"Account Age: {arguments['created']} days")
        if arguments.get("multiplier") and arguments.get("multi_roles"):
            multi_roles = {ctx.guild.get_role(r) for r in arguments["multi_roles"] if ctx.guild.get_role(r) is not None}
            if multi_roles:
                settings.append(
                    f"Multiplier: {arguments['multiplier']}x for {', '.join(r.mention for r in multi_roles)}"
                )
        return "\n".join(settings)