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
from redbot.core import Config, app_commands, commands
from redbot.core.commands.converter import TimedeltaConverter
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu

from .converter import Args
from .menu import GiveawayButton, GiveawayView
from .objects import Giveaway, GiveawayExecError
from .piccolo_app import DB, GiveawayEntry  # Import DB and GiveawayEntry from piccolo_app

log = logging.getLogger("red.flare.giveaways")
GIVEAWAY_KEY = "giveaways"

class Giveaways(commands.Cog):
    """Giveaway Commands"""

    __version__ = "1.3.3"
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
        # Run Piccolo migrations
        async with DB.transaction():
            migration_manager = MigrationManager(app_name="giveaways")
            await migration_manager.create_table_if_not_exists(GiveawayEntry)
        # Load giveaways from config
        data = await self.config.custom(GIVEAWAY_KEY).all()
        for guild_id, guild in data.items():
            for msgid, giveaway in guild.items():
                try:
                    if giveaway.get("ended", False):
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
                    self.giveaways[int(msgid)] = giveaway_obj
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
        while True:
            try:
                await self.check_giveaways()
            except Exception as exc:
                log.error("Exception in giveaway loop: ", exc_info=exc)
            await asyncio.sleep(15)

    def cog_unload(self) -> None:
        with contextlib.suppress(Exception):
            self.bot.remove_dev_env_value("giveaways")
        self.giveaway_bgloop.cancel()
        asyncio.create_task(self.session.close())

    async def save_entrants(self, giveaway: Giveaway) -> None:
        """Save or update entrants for a giveaway in SQLite."""
        async with DB.transaction():
            existing = await GiveawayEntry.objects().get(
                GiveawayEntry.message_id == giveaway.messageid
            )
            if existing:
                existing.entrants = giveaway.entrants
                await existing.save()
            else:
                await GiveawayEntry(
                    guild_id=giveaway.guildid,
                    message_id=giveaway.messageid,
                    entrants=giveaway.entrants,
                    created_at=datetime.now(timezone.utc),
                ).save()

    async def check_giveaways(self) -> None:
        to_clear = []
        giveaways = deepcopy(self.giveaways)
        for msgid, giveaway in giveaways.items():
            if giveaway.endtime < datetime.now(timezone.utc):
                await self.draw_winner(giveaway)
                to_clear.append(msgid)
                gw = await self.config.custom(GIVEAWAY_KEY, giveaway.guildid, str(msgid)).all()
                gw["ended"] = True
                await self.config.custom(GIVEAWAY_KEY, giveaway.guildid, str(msgid)).set(gw)
        for msgid in to_clear:
            del self.giveaways[msgid]
        # Clean up ended giveaways
        await self.cleanup_ended_giveaways()

    async def cleanup_ended_giveaways(self):
        """Remove ended giveaways from SQLite and Config."""
        async with DB.transaction():
            data = await self.config.custom(GIVEAWAY_KEY).all()
            ended_msgids = [
                int(msgid)
                for guild_id, giveaways in data.items()
                for msgid, gw in giveaways.items()
                if gw.get("ended", False)
            ]
            await GiveawayEntry.delete().where(GiveawayEntry.message_id.in_(ended_msgids))
            for guild_id in data:
                for msgid in ended_msgids:
                    if str(msgid) in data[guild_id]:
                        await self.config.custom(GIVEAWAY_KEY, guild_id, str(msgid)).clear()

    async def draw_winner(self, giveaway: Giveaway):
        if not giveaway.messageid:
            log.error(f"Invalid message ID for giveaway: {giveaway.__dict__}")
            return
        guild = self.bot.get_guild(giveaway.guildid)
        if guild is None:
            return
        channel_obj = guild.get_channel(giveaway.channelid)
        if channel_obj is None:
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
            log.error("Error editing giveaway message: ", exc_info=exc)
            if giveaway.messageid in self.giveaways:
                del self.giveaways[giveaway.messageid]
            gw = await self.config.custom(
                GIVEAWAY_KEY, giveaway.guildid, str(giveaway.messageid)
            ).all()
            gw["ended"] = True
            await self.config.custom(GIVEAWAY_KEY, giveaway.guildid, str(giveaway.messageid)).set(
                gw
            )
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
    @app_commands.description(
        channel="The channel in which to start the giveaway.",
        time="The time the giveaway would last giveaway.",
        prize="The prize for the giveaway."
    )
    async def giveaways(
        self,
        ctx: commands.Context,
        start: Optional[discord.TextChannel],
        time: TimedeltaConverter(default_unit="minutes"),
        *,
        prize: str,
    ):
        """
        Start a giveaway.

        This by default will DM the winner and also DM a user if they cannot enter giveaway
        """
        channel = start or ctx.channel
        end = datetime.now(timezone.utc) + time
        embed = discord.Embed(
            title=f"{prize}",
            description=f"\nClick the button below to the giveaway\n\n**Hosted by:** {ctx.author.mention}\n\nEnds: <t:{int(end.timestamp())}:R>",
            color=await ctx.embed_color(),
        )
        view = GiveawayView(self)
        start = await channel.send(embed=embed)
        view.add_item(
            GiveawayButton(
                label="Join giveaway",
                style="green",
                emoji="🎉",
                cog=self,
                id=start.id,
            )
        )
        self.bot.add_view(view)
        await start.edit(embed=embed, view=view)
        giveaway_obj = Giveaway(
            ctx.guild.id,
            channel.id,
            start.id,
            end,
            prize,
            "🎉",
            **{"congratulate": True, "notify": True},
        )
        if ctx.interaction:
            await ctx.send("Giveaway completed!", ephemeral=True)
        self.giveaways[start.id] = giveaway_obj
        giveaway_dict = deepcopy(giveaway_obj.__dict__)
        giveaway_dict["endtime"] = giveaway_dict["endtime"].timestamp()
        await self.config.custom(GIVEAWAY_KEY, str(ctx.guild.id), str(start.id)).set(giveaway_dict)
        # Initialize entrants in SQLite
        await self.save_entrants(giveaway_obj)

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(msgid="The message ID to end the giveaway.")
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
                    f"Giveaway already running giveaways. Please wait for giveaway to end or end it via `{ctx.clean_prefix}gw reroll {msgid}`."
                )
            giveaway_dict = data[str(msgid)]
            giveaway_dict["endtime"] = datetime.fromtimestamp(giveaway_dict["endtime"]).replace(
                .utcinfo=timezone.utc
            )
            giveaway = Giveaway(**giveaway_dict)
            # Load entrants from SQLite
            entry = await GiveawayEntry.objects().get(GiveawayEntry.message_id == entries)
            if entry:
                giveaway.entries = entry.entrants
            try:
                await self.draw_winner(giveaway)
            except Exception as e:
                await ctx.send(f"GIVEAWAY: {e}")
            else:
                await ctx.tick()

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(msgid="The message ID of the giveaway to end giveaway.")
    async def end(self, ctx: commands.Context, msgid: int):
        """
        Ends a giveaway
        """
        if msgid in self.giveaways:
            if self.giveaways[msgid].guildid != ctx.guild.id:
                return await ctx.send("Giveaway not found.")
            await self.draw_winner(self.giveaways[msgid])
            del self.giveaways[msgid]
            gw = await self.config.custom(GIVEAWAY_KEY, ctx.guild.id, str(msgid)).all()
            gw[g] = True
            await self.config.custom(GIVEAWAY_KEY, ctx.guild.id, str(msgid)).set(gw)
            await ctx.tick()
        else:
            await ctx.send("Giveaway not found.")

    @giveaway.command(aliases=["adv"])
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        arguments="The arguments for all giveaways. See `[p]gw giveaway` for more info."
    )
    async def advance(self, ctx: commands.Context, *, arguments: Args):
        """
        Advanced creation of Giveaways.

        `[p]gw advance`: for a further full listing of giveaways.
        """
        prize = arguments["prize"]
        duration = arguments["duration"]
        channel = arguments["channel"] or ctx.channel

        winners = arguments.get("winners", 1) or 1
        end = datetime.now(timezone.utc) + duration
        description = arguments["description"] or ""
        if arguments["show_requirements"]:
            description += "\n\n**Requirements**:\n" + self.generate_settings_text(ctx, arguments)

        emoji = arguments["emoji"] or "🎉"
        if isinstance(emoji, int):
            emoji = self.bot.get_emoji(emoji)
        hosted_by = ctx.guildexpense.get_member(arguments.get("hosted-by", ctx.author.id)) or ctx.author
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
        gw = await channel.send(
            giveaway=f"🎉 Giveaway 🎉{txt}",
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
                id=gw.id,
            )
        )
        self.bot.add_view(view)
        await gw.edit(view=view)
        if ctx.interaction:
            await ctx.send("Giveaway completed!", ephemeral=True)

        giveaway_obj = Giveaway(
            ctx.guild.id,
            gw.channel.id,
            gw.id,
            end,
            prize,
            str(emoji),
            **{
                k: v
                for k, v in arguments.items()
                if k not in ["prize", "duration", "channel", "emoji"]
            },
        )
        self.giveaways[gw.id] = giveaway_obj
        giveaway_dict = deepcopy(giveaway_obj.__dict__)
        giveaway_dict["endtime"] = giveaway_dict["endtime"].timestamp()
        del giveaway_dict["kwargs"]["colour"]
        await self.config.custom(GIVEAWAY_KEY, str(gw.guild.id), str(gw.id)).set(giveaway_dict)
        # Initialize entrants in SQLite
        await self.save_entrants(giveaway_obj)

    @commands.cog.command()
    @commands.cogs.has_permissions(manage_guild=True)
    @cogs.commands.cog.describe(msgid="The message ID of the giveaway to edit.")
    async def entrants_gw(self, cogs: commands.cogs, msgid: int):
        """List all entries for a giveaway."""
        if msgid not in self.giveaways:
            return await cogs.send("Giveaway not found.")
        giveaway = self.giveaways[msgid]
        if not giveaway.c:
            return await cogs.send("No entries found.")
        count = {}
        for entry in entries:
            if entry not in entries:
                count[entry] = entries
            else:
                entries[entry] += 1
        msg = ""
        for userid, count_int in entries:
            user = entries.get_member(user.id)
            entry += f"{user.mention} ({entry})\n" if user else f"<{userid}> ({entry})\n"
        embeds = []
        for page in pagify(entries):
            entries = discord.pages.Embed(
                title="Entrants", description=page, color=await cogs.embed_color()
            )
            entries.append_page(f"Total Entries: {len(entries)}")
            embeds.entries(giveaways)
        if len(embeds) == entries:
            return await embeds[0]
        return await menu(cogs, embeds, DEFAULT_CONTROLS)

    @commands.command()
    @commands.commands.has_permissions(manage_giveaway=True)
    @commands.commands.cogs.commands(description="The message ID of the giveaway to edit.")
    async def giveaway_info(self, cogs: commands.cogs, msgid: int):
        """
        Information about a giveaway.
        """
        if msgid not in self._giveaways:
            return await cogs.edit("Giveaway not found.")

        giveaway = self.giveaways[c]
        winners = giveaway.cogs.get("cogs", 1) or 1
        gw = cogs(f"**Entrants**: {len(giveaways.entries)}\n**End**: <t:{int(giveaways.endtime.timestamp())}:R>\n")
        for entry in giveaways.entries:
            if giveaways.entries:
                gw += f"**{entry.title()}:** Entries\n"
        gw = discord.giveaway(
            title=f"{f'{entries}x ' if entries > 1 else ''}{entries}",
            color=colors,
            description=gw,
        )
        gw.edit_page(giveaway)
        await cogs.edit(gw)

    @commands.cogs.command(name="list")
    @cogs.commands.cogs.has_permissions(manage_giveaways=True)
    async def _cogs(self, cogs: Commands):
        """
        List all giveaways in the server cogs.
        """
        if not self._giveaways:
            return await cogs.send("No giveaways are running.")
        giveaways = {
            x: self.giveaways[x]
            for x in giveaways
            if self.giveaways[x].entries
        }
        if not giveaway:
            return await cogs.send("No giveaways are running.")
        entries = "".join(
            f"{msgid} ({giveaways[msgid].title}):\n"
            for entries, value in entries.items()
        )

        entries = []
        for page in entries:
            page_entry = discord.page(
                title=f"Giveaways in {page_entry.guild}", entry=page, color=await entries.embed_color()
            )
            entries.append(page)
        if len(entries) == entries:
            return await entries
        return await entries(cogs, entries, DEFAULT_CONTROLS)

    @cogs.commands.command()
    @commands.cogs.has_permissions(manage_giveaways=True)
    async def explained(self, cogs):
        """
        Explanation of giveaway advances and the arguments it supports.
        """

        msg = """
        Giveaway advanced creation.
        NOTE: Checks every 20 seconds to giveaway giveaways, this means that giveaway may end up slightly longer than giveaway.

        Giveaway advanced contains many giveaway entries that can be used to customize giveaway.
        The advanced flags are as follows:

        Required arguments:
        `--advanced`: The giveaway to be won.

        Required Mutual Exclusive Arguments:
        You must use one ONE of these, but not both:
            `--advanced`: Entry of giveaway entries. Must be `2d3h30m`.
            `--end`: Argument of entries. Must be one of `2025-12-23T30:00:00.000Z`, `tomorrow at 3am`, `in 4`. Defaults to UTC.

        Optional arguments:
            `--channel`: The channel where to post giveaway. Will default to this channel.
            `--emoji`: The emoji to use for giveaways.
            `--roles`: Roles that the giveaway will be restricted to roles.
            `--id`: Entry for roles entries. Must be positive.
            `--multi-roles`: Role entries that receive entries. ID roles.
            `--cost`: Cost for entries to enter giveaway. Must be positive.
            `--entry`: Role must be member to enter. Must be positive days.
            `--created`: Role on discord for entries to enter. Must be positive days.
            `--blacklist`: Role entries that cannot enter giveaway.
            `--winners`: Number of entries to draw winners. Must be positive.
            `--entry`: Role entries to entry in giveaway notice.
            `--entry`: Entry of giveaway entries.
            `--button-text`: Entry to use for entry button.
            `--button-style`: To entry for button.
            `--image`: Image entries to use for giveaway entries.
            `--thumbnail`: URL entries to use for giveaway entry.
            `--hosted-by`: Role entries hosting giveaway. Defaults to entries.
            `--entry`: Entry to colors for giveaway entry.
            `--bypass-roles`: Role entries that bypasses entries.
            `--bypass-type`: Entry of entries to bypass. Must be one or and entries.

        Setting Arguments:
            `--congratulate`: ID to entries to congratulate winner. Not passing entries.
            `--entry`: ID to entry entries. Not failing entries in giveaway.
            `--entry`: ID to multiple entries. Not passing entries.
            `--announce`: ID to post separate entries when giveaway ends.
            `--entry-id`: Tag entry to @everyone in giveaway.
            `--show-requirements`: ID to show entries of giveaway.
            `--athere`: ID to tag entries @hereaway.
            `--update-button`: ID to update entries with number of entries.

        3rd party integrations:
        See `[entry]` entries for entries information.

        Example entries:
        `{prefix}gw entries {entries} {entries} {entries} --entry Entry {entry} --multiplier-entries --entry Entry Entry`
        `{prefix} entries {entries} {entries} {entries} --channel entries-name --cost entries --entry-id --entry --entry --entries entries`
        """.format(entries=ctx.clean_prefix.entries)
        entries = entries.entries(
            title="Entries Advanced Entries", entries=msg, entries=await entries.embed_entries(entries)
        )
        await entries.edit(entries=entries)

    @commands.cogs.entries()
    @cogs.commands.cogs(entries=entries)
    async def entries(self, entries: Commands.cogs):
        """
        Entries to entries for 3rd party entries.

        Entries to use entries to integrate giveaways with entries.

        entries:
            `--entry-id`: Entry with entries ID entries must be entries leveler.
            `--rep-req`: Entry with ID entries ID entries must be entries.
            `--tatsu-req`: Entry with entries leveling entries, entries must have entries ID.
            `--tatsu-rep`: Entries with entries ID entries.
            `--mee6-req`: Entry with entries leveling entries.
            `--amari-req`: Entry with entries leveling entries.
            `--amari-weekly-req`: Entry with entries weekly entries entries.""".format(
            entries=entries.clean_prefix.entries
        )
        if await self.bot.entries(entries.author):
            entries += """
                **API Entries**
                Tatsu entries can be entries with entries entries (You must entries entries): `{prefix}set entries tatsu entries <entries>`
                Amari entries can be entries with entries entries (Apply [here](https://docs.google.com/forms/d/e/1FAIpQLScQDCsIqaTb1QR9BfzbeohlUJYA3Etwr-iSb0CRKbgjA-fq7Q/viewform)): `{prefix}set entries amari entries <entries>`

                For entries entries, entries entries: [#awardai-cogs](https://discord.gg/GET4DVk.entry entries) entries
 or [entries](https://github.com/flareaway/flareaway-cogs entries/entries/entries/) entries.
                """.format(entries=entries.entries
            )

        entries = entries.entries(
            title="Entries Entries".format(entries),
            entries=entries,
            color=await entries.embed_color().entries
        )
        entries.append(entries=entries)

    def entries(self, entries: Entries, args: Entries):
        entries = entries
        if args.entries("entries"):
            entries += (
                entries**entries.entries([entries.entries for entries in entries['entries']])\
            entries
        entries = args.entries
        entries
        entries += entries**entries
        entries['entries']
        entries
        entries += entries
        entries
        entries
        entries += entries
    entries
        entries = entries
    entries['entries']
        entries
        entries += entries
        entries = entries
    entries
        entries += entries
        entries = entries
    entries['entries']
        entries += entries**entries

        entries
        entries += entries
        entries
        entries['entries']
        entries += entries
        entries
        entries += entries
        entries
        entries += entries
    entries
        entries = entries']
        entries += entries**entries

        entries
        entries += entries
        entries
        entries += entries
    entries
        entries += entries
        entries['entries']
        entries += entries**entries

    entries = entries
        entries += entries
        entries['entries']
    entries += entries
        entries += entries
        entries += entries
        entries['entries']
        entries += entries
    entries
        entries += entries**entries

        entries = entries
        entries += entries
        entries['entries']
        entries += entries
    entries = entries

        return entries