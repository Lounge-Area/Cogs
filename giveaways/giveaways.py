import asyncio
import logging
import uuid
import random
from datetime import datetime, timezone
from threading import Lock
from typing import List, Dict, Optional, Set
from copy import deepcopy

import discord
from redbot.core import commands, Config
from redbot.core.commands.converter import TimedeltaConverter
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu
from .objects import Giveaway
from .menu import GiveawayView, GiveawayButton
from .converter import Args

log = logging.getLogger("red.flare.giveaways")
GIVEAWAY_KEY = "giveaways"

class GiveawayError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

class GiveawayValidationError(GiveawayError):
    pass

class GiveawayEnterError(GiveawayError):
    pass

class AlreadyEnteredError(GiveawayError):
    pass

class Giveaways(commands.Cog):
    """Giveaway Commands"""

    __version__ = "1.0.4"
    __author__ = "flare"

    def format_help_for_context(self, ctx):
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\nCog Version: {self.__version__}\nAuthor: {self.__author__}"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=95932766180343808)
        self.config.init_custom(GIVEAWAY_KEY, 2)
        self.giveaways: Dict[int, Giveaway] = {}
        self.locks: Dict[int, Lock] = {}
        self.view = GiveawayView(self)
        self.bot.add_view(self.view)
        self.giveaway_bgloop = asyncio.create_task(self.init())

    async def init(self) -> None:
        await self.bot.wait_until_ready()
        log.info("Initializing giveaways cog...")
        await self.load_giveaways()
        await self.recover_crashed_giveaways()
        while True:
            try:
                await self.check_giveaways()
            except Exception as exc:
                log.error("Exception in giveaway loop: ", exc_info=exc)
            await asyncio.sleep(15)

    async def load_giveaways(self) -> None:
        data = await self.config.custom(GIVEAWAY_KEY).all()
        for guild_id, guild_data in data.items():
            for msg_id, giveaway_data in guild_data.items():
                try:
                    if giveaway_data.get("ended", False) and datetime.fromtimestamp(giveaway_data["endtime"], tz=timezone.utc) < datetime.now(timezone.utc):
                        continue
                    giveaway = Giveaway(
                        guild_id=int(guild_id),
                        channel_id=giveaway_data["channelid"],
                        message_id=int(msg_id),
                        end_time=datetime.fromtimestamp(giveaway_data["endtime"], tz=timezone.utc),
                        title=giveaway_data["title"],
                        emoji=giveaway_data.get("emoji", "🎉"),
                        entrants=set(giveaway_data.get("entrants", [])),
                        ended=giveaway_data.get("ended", False),
                        conditions=giveaway_data.get("kwargs", {}),
                        host_id=giveaway_data.get("host_id")
                    )
                    self.giveaways[int(msg_id)] = giveaway
                    self.bot.add_view(GiveawayView(self))
                    log.info(f"Loaded giveaway {msg_id} for guild {guild_id}")
                except Exception as exc:
                    log.error(f"Error loading giveaway {msg_id}: ", exc_info=exc)

    async def recover_crashed_giveaways(self) -> None:
        for msg_id, giveaway in list(self.giveaways.items()):
            if giveaway.is_active() and len(giveaway.entrants) == 0 and datetime.now(timezone.utc) > giveaway.end_time:
                log.warning(f"Recovering crashed giveaway {msg_id} - no entrants, ending now")
                await self.draw_winner(giveaway)
                del self.giveaways[msg_id]

    def cog_unload(self) -> None:
        log.info("Unloading giveaways cog...")
        self.giveaway_bgloop.cancel()
        log.info("Giveaways cog unloaded.")

    async def save_giveaway(self, giveaway: Giveaway) -> None:
        with giveaway._lock:
            giveaway_dict = {
                "guildid": giveaway.guild_id,
                "channelid": giveaway.channel_id,
                "messageid": giveaway.message_id,
                "title": giveaway.title,
                "endtime": giveaway.end_time.timestamp(),
                "emoji": giveaway.emoji,
                "entrants": list(giveaway.entrants),
                "ended": giveaway.ended,
                "kwargs": giveaway.conditions,
                "host_id": giveaway.host_id
            }
            await self.config.custom(GIVEAWAY_KEY, str(giveaway.guild_id), str(giveaway.message_id)).set(giveaway_dict)
            log.debug(f"Saved giveaway {giveaway.id} to config")

    async def check_giveaways(self) -> None:
        to_clear = []
        for msg_id, giveaway in deepcopy(self.giveaways).items():
            if not giveaway.is_active():
                log.info(f"Giveaway {msg_id} has ended, drawing winners")
                await self.draw_winner(giveaway)
                to_clear.append(msg_id)
        for msg_id in to_clear:
            if msg_id in self.giveaways:
                del self.giveaways[msg_id]
                log.debug(f"Removed ended giveaway {msg_id}")

    async def draw_winner(self, giveaway: Giveaway):
        guild = self.bot.get_guild(giveaway.guild_id)
        if not guild:
            log.error(f"Guild {giveaway.guild_id} not found for giveaway {giveaway.id}")
            return

        channel = guild.get_channel(giveaway.channel_id)
        if not channel:
            log.error(f"Channel {giveaway.channel_id} not found for giveaway {giveaway.id}")
            return

        try:
            winners = giveaway.draw_winners()
            winner_text = "No winners selected (not enough entrants)" if not winners else ""
            winner_objs = []
            if winners:
                winner_text = "\n".join(
                    f"{guild.get_member(w).mention} ({guild.get_member(w).display_name})" if guild.get_member(w) else f"<@{w}> (Not Found)"
                    for w in winners
                )
                winner_objs = [guild.get_member(w) for w in winners if guild.get_member(w)]

            winner_count = giveaway.conditions.get("winners", 1)
            title_prefix = f"{winner_count}x " if winner_count > 1 else ""
            embed = discord.Embed(
                title=f"{title_prefix}{giveaway.title}",
                description=f"Winner(s):\n{winner_text}",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"Reroll: {(await self.bot.get_prefix(None))[-1]}gw reroll {giveaway.message_id} | Ended at")
            
            msg = channel.get_partial_message(giveaway.message_id)
            await msg.edit(content="🎉 Giveaway Ended 🎉", embed=embed, view=None)
            
            if giveaway.conditions.get("announce") and winner_objs:
                announce_embed = discord.Embed(
                    title="Giveaway Ended",
                    description=f"Congratulations to the {f'{winner_count} ' if winner_count > 1 else ''}winner{'s' if winner_count > 1 else ''} of [{giveaway.title}]({msg.jump_url}).\n{winner_text}",
                    color=discord.Color.blue()
                )
                await channel.send(
                    content="Congratulations " + ",".join(m.mention for m in winner_objs),
                    embed=announce_embed
                )

            if giveaway.conditions.get("congratulate") and winner_objs:
                for winner in winner_objs:
                    try:
                        await winner.send(f"Congratulations! You won {giveaway.title} in {guild.name}!")
                    except discord.Forbidden:
                        log.warning(f"Could not DM winner {winner.id} for giveaway {giveaway.id}")

            await self.save_giveaway(giveaway)
            log.info(f"Giveaway {giveaway.id} ended successfully")
        except Exception as e:
            log.error(f"Error processing giveaway {giveaway.id} end: {str(e)}", exc_info=e)

    @commands.hybrid_group(aliases=["gw"])
    @commands.bot_has_permissions(add_reactions=True, embed_links=True)
    @commands.has_permissions(manage_guild=True)
    async def giveaway(self, ctx: commands.Context):
        """Manage the giveaway system"""
        pass

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def start(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel],
        time: TimedeltaConverter,
        winners: int,
        *,
        prize: str
    ):
        """Start a simple giveaway"""
        try:
            if winners < 1:
                raise GiveawayValidationError("Winner count must be at least 1")
            
            channel = channel or ctx.channel
            duration_minutes = time.total_seconds() / 60
            
            start_time = datetime.now(timezone.utc)
            end_time = start_time + TimedeltaConverter().convert(None, f"{duration_minutes}m")
            giveaway = Giveaway(
                guild_id=ctx.guild.id,
                channel_id=channel.id,
                message_id=0,  # Will be set after message is sent
                end_time=end_time,
                title=prize,
                emoji="🎉",
                conditions={"winners": winners},
                host_id=ctx.author.id
            )
            
            embed = discord.Embed(
                title=prize,
                description=f"Click the button to enter\n\n**Hosted by:** {ctx.author.mention}\nEnds: <t:{int(end_time.timestamp())}:R>",
                color=discord.Color.blue()
            )
            
            view = GiveawayView(self)
            msg = await channel.send(embed=embed)
            giveaway.message_id = msg.id
            
            view.add_item(GiveawayButton(
                label="Join Giveaway",
                style="green",
                emoji="🎉",
                cog=self,
                id=msg.id
            ))
            
            await msg.edit(view=view)
            self.giveaways[msg.id] = giveaway
            await self.save_giveaway(giveaway)
            
            if ctx.interaction:
                await ctx.send("Giveaway created!", ephemeral=True)
            else:
                await ctx.tick()
                
            log.info(f"Started giveaway {giveaway.id} in guild {ctx.guild.id}")
        except Exception as e:
            log.error(f"Error starting giveaway: {str(e)}", exc_info=e)
            await ctx.send(f"Error starting giveaway: {str(e)}")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def advanced(self, ctx: commands.Context, *, arguments: Args):
        """Advanced giveaway creation"""
        try:
            channel = arguments.get("channel") or ctx.channel
            duration = arguments["duration"]
            duration_minutes = duration.total_seconds() / 60
            
            start_time = datetime.now(timezone.utc)
            end_time = start_time + duration
            giveaway = Giveaway(
                guild_id=ctx.guild.id,
                channel_id=channel.id,
                message_id=0,
                end_time=end_time,
                title=arguments["prize"],
                emoji=arguments.get("emoji", "🎉"),
                conditions=arguments,
                host_id=arguments.get("hosted-by", ctx.author.id)
            )
            
            description = arguments.get("description", "")
            if arguments.get("show_requirements"):
                description += "\n\n**Requirements:**\n" + self.generate_settings_text(ctx, arguments)
            
            winner_count = arguments.get("winners", 1)
            title_prefix = f"{winner_count}x " if winner_count > 1 else ""
            embed = discord.Embed(
                title=f"{title_prefix}{arguments['prize']}",
                description=f"{description}\n\nClick the button to enter\n\n**Hosted by:** {ctx.guild.get_member(arguments.get('hosted-by', ctx.author.id)).mention}\nEnds: <t:{int(end_time.timestamp())}:R>",
                color=arguments.get("colour", discord.Color.blue())
            )
            
            if arguments.get("image"):
                embed.set_image(url=arguments["image"])
            if arguments.get("thumbnail"):
                embed.set_thumbnail(url=arguments["thumbnail"])
                
            content = "🎉 Giveaway 🎉"
            if arguments.get("ateveryone"):
                content += " @everyone"
            if arguments.get("athere"):
                content += " @here"
            if arguments.get("mentions"):
                content += " " + " ".join(f"<@&{r}>" for r in arguments["mentions"])
                
            view = GiveawayView(self)
            msg = await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    roles=bool(arguments.get("mentions")),
                    everyone=bool(arguments.get("ateveryone"))
                )
            )
            
            giveaway.message_id = msg.id
            view.add_item(GiveawayButton(
                label=arguments.get("button-text", "Join Giveaway"),
                style=arguments.get("button-style", "green"),
                emoji=arguments.get("emoji", "🎉"),
                cog=self,
                id=msg.id,
                update=arguments.get("update_button", False)
            ))
            
            await msg.edit(view=view)
            self.giveaways[msg.id] = giveaway
            await self.save_giveaway(giveaway)
            
            if ctx.interaction:
                await ctx.send("Giveaway created!", ephemeral=True)
            else:
                await ctx.tick()
                
            log.info(f"Started advanced giveaway {giveaway.id} in guild {ctx.guild.id}")
        except Exception as e:
            log.error(f"Error starting advanced giveaway: {str(e)}", exc_info=e)
            await ctx.send(f"Error starting giveaway: {str(e)}")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def end(self, ctx: commands.Context, msg_id: int):
        """End a giveaway early"""
        try:
            if msg_id not in self.giveaways or self.giveaways[msg_id].guild_id != ctx.guild.id:
                await ctx.send("Giveaway not found")
                return
                
            giveaway = self.giveaways[msg_id]
            await self.draw_winner(giveaway)
            del self.giveaways[msg_id]
            await ctx.tick()
            log.info(f"Manually ended giveaway {giveaway.id} in guild {ctx.guild.id}")
        except Exception as e:
            log.error(f"Error ending giveaway {msg_id}: {str(e)}", exc_info=e)
            await ctx.send(f"Error ending giveaway: {str(e)}")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def reroll(self, ctx: commands.Context, msg_id: int):
        """Reroll a giveaway"""
        try:
            data = await self.config.custom(GIVEAWAY_KEY, str(ctx.guild.id)).all()
            if str(msg_id) not in data:
                await ctx.send("Giveaway not found")
                return
                
            giveaway_data = data[str(msg_id)]
            if not giveaway_data.get("ended", False):
                await ctx.send("Giveaway is still active. End it first.")
                return
                
            giveaway = Giveaway(
                guild_id=ctx.guild.id,
                channel_id=giveaway_data["channelid"],
                message_id=msg_id,
                end_time=datetime.now(timezone.utc),  # Set to now for reroll
                title=giveaway_data["title"],
                emoji=giveaway_data.get("emoji", "🎉"),
                entrants=set(giveaway_data.get("entrants", [])),
                ended=False,
                conditions=giveaway_data.get("kwargs", {})
            )
            await self.draw_winner(giveaway)
            await ctx.tick()
            log.info(f"Rerolled giveaway {msg_id} in guild {ctx.guild.id}")
        except Exception as e:
            log.error(f"Error rerolling giveaway {msg_id}: {str(e)}", exc_info=e)
            await ctx.send(f"Error rerolling giveaway: {str(e)}")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def add_old(self, ctx: commands.Context, msg_id: int, prize: str, winners: int, ended: bool = False, *, args: str = ""):
        """Add an old giveaway with a specific message ID"""
        try:
            if msg_id in self.giveaways:
                await ctx.send("Giveaway with this ID already exists")
                return
            
            channel = ctx.channel
            arguments = await Args().convert(ctx, args) if args else {}
            arguments["winners"] = winners
            
            yesterday = datetime(2025, 7, 2, 20, 21, tzinfo=timezone.utc)  # Default to yesterday 20:21 CEST
            end_time = datetime.now(timezone.utc) if ended else yesterday
            
            giveaway = Giveaway(
                guild_id=ctx.guild.id,
                channel_id=channel.id,
                message_id=msg_id,
                end_time=end_time,
                title=prize,
                emoji=arguments.get("emoji", "🎉"),
                ended=ended,
                conditions=arguments,
                host_id=arguments.get("hosted-by", ctx.author.id)
            )
            
            self.giveaways[msg_id] = giveaway
            await self.save_giveaway(giveaway)
            
            winner_count = winners
            title_prefix = f"{winner_count}x " if winner_count > 1 else ""
            embed = discord.Embed(
                title=f"{title_prefix}{prize}",
                description=f"Winner(s): {'N/A' if not ended else 'No winners (not enough entrants)'}\nEnds: <t:{int(end_time.timestamp())}:R>",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc) if ended else None
            )
            embed.set_footer(text=f"Reroll: {(await self.bot.get_prefix(None))[-1]}gw reroll {msg_id} | Ended at" if ended else "Active")
            
            msg = channel.get_partial_message(msg_id)
            await msg.edit(content="🎉 Giveaway Ended 🎉" if ended else "🎉 Giveaway 🎉", embed=embed, view=None if ended else GiveawayView(self))
            
            await ctx.send(f"Added old giveaway {msg_id} {'(ended)' if ended else '(active)'}")
            log.info(f"Added old giveaway {msg_id} in guild {ctx.guild.id}")
        except Exception as e:
            log.error(f"Error adding old giveaway {msg_id}: {str(e)}", exc_info=e)
            await ctx.send(f"Error adding old giveaway: {str(e)}")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def add_entrants(self, ctx: commands.Context, msg_id: int, *user_ids: int):
        """Add entrants to a giveaway by user IDs"""
        try:
            if msg_id not in self.giveaways or self.giveaways[msg_id].guild_id != ctx.guild.id:
                await ctx.send("Giveaway not found")
                return
                
            giveaway = self.giveaways[msg_id]
            giveaway.add_entrants_by_ids(list(user_ids))
            await self.save_giveaway(giveaway)
            await ctx.send(f"Added {len(user_ids)} entrants to giveaway {msg_id}")
            log.info(f"Added entrants {user_ids} to giveaway {msg_id} in guild {ctx.guild.id}")
        except Exception as e:
            log.error(f"Error adding entrants to giveaway {msg_id}: {str(e)}", exc_info=e)
            await ctx.send(f"Error adding entrants: {str(e)}")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def entrants(self, ctx: commands.Context, msg_id: int):
        """List giveaway entrants"""
        try:
            if msg_id not in self.giveaways:
                await ctx.send("Giveaway not found")
                return
                
            giveaway = self.giveaways[msg_id]
            if not giveaway.entrants:
                await ctx.send("No entrants")
                return
                
            count = {}
            for entrant in giveaway.entrants:
                count[entrant] = count.get(entrant, 0) + 1
                
            msg = ""
            for user_id, count_int in count.items():
                user = ctx.guild.get_member(user_id)
                msg += f"{user.mention} ({count_int})\n" if user else f"<{user_id}> ({count_int})\n"
                
            embeds = []
            for page in pagify(msg, delims=["\n"], page_length=800):
                embed = discord.Embed(
                    title="Entrants",
                    description=page,
                    color=discord.Color.blue()
                )
                embed.set_footer(text=f"Total entrants: {len(count)}")
                embeds.append(embed)
                
            if len(embeds) == 1:
                await ctx.send(embed=embeds[0])
            else:
                await menu(ctx, embeds, DEFAULT_CONTROLS)
        except Exception as e:
            log.error(f"Error listing entrants for giveaway {msg_id}: {str(e)}", exc_info=e)
            await ctx.send(f"Error listing entrants: {str(e)}")

    @giveaway.command()
    @commands.has_permissions(manage_guild=True)
    async def info(self, ctx: commands.Context, msg_id: int):
        """Get giveaway information"""
        try:
            if msg_id not in self.giveaways:
                await ctx.send("Giveaway not found")
                return
                
            giveaway = self.giveaways[msg_id]
            status = giveaway.get_status()
            msg = (f"**Entrants:** {status['entrants_count']}\n"
                   f"**End**: <t:{int(giveaway.end_time.timestamp())}:R>\n"
                   f"**Status**: {'Active' if status['is_active'] else 'Ended'}\n")
            for key, value in giveaway.conditions.items():
                if value:
                    msg += f"**{key.title()}:** {value}\n"
                    
            winner_count = giveaway.conditions.get("winners", 1)
            title_prefix = f"{winner_count}x " if winner_count > 1 else ""
            embed = discord.Embed(
                title=f"{title_prefix}{giveaway.title}",
                description=msg,
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Giveaway ID: {giveaway.id}")
            await ctx.send(embed=embed)
        except Exception as e:
            log.error(f"Error getting info for giveaway {msg_id}: {str(e)}", exc_info=e)
            await ctx.send(f"Error getting giveaway info: {str(e)}")

    def generate_settings_text(self, ctx: commands.Context, arguments: Args) -> str:
        settings = []
        if arguments.get("roles"):
            roles = [ctx.guild.get_role(r) for r in arguments["roles"]]
            settings.append(f"Required Roles: {', '.join(r.mention for r in roles if r)}")
        if arguments.get("blacklist"):
            blacklist = [ctx.guild.get_role(r) for r in arguments["blacklist"]]
            settings.append(f"Blacklisted Roles: {', '.join(r.mention for r in blacklist if r)}")
        if arguments.get("cost"):
            settings.append(f"Cost: {arguments['cost']} credits")
        if arguments.get("joined_days"):
            settings.append(f"Joined Server: {arguments['joined_days']} days")
        if arguments.get("account_age_days"):
            settings.append(f"Account Age: {arguments['account_age_days']} days")
        if arguments.get("multiplier") and arguments.get("multi_roles"):
            multi_roles = [ctx.guild.get_role(r) for r in arguments["multi_roles"] if ctx.guild.get_role(r)]
            if multi_roles:
                settings.append(f"Multiplier: {arguments['multiplier']}x for {', '.join(r.mention for r in multi_roles)}")
        return "\n".join(settings)