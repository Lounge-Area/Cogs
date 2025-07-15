import logging
from datetime import datetime
from pathlib import Path

import discord
from piccolo.conf.apps import AppConfig
from piccolo.engine.sqlite import SQLiteEngine
from piccolo.table import Table
from piccolo.columns import Integer, Varchar, Array, Timestamp
from redbot.core import commands, Config
from redbot.core.data_manager import cog_data_path

log = logging.getLogger("red.flare.cleanup_giveaways")

DB = SQLiteEngine(path=str(cog_data_path(raw_name="Giveaways") / "giveaways.sqlite"))

class GiveawayEntry(Table, db=DB):
    guild_id = Integer()
    message_id = Integer(index=True)
    entrants = Array(base_column=Integer())
    created_at = Timestamp(default=datetime.now)

APP_CONFIG = AppConfig(
    app_name="giveaways",
    migrations_folder_path=str(Path(__file__).parent / "migrations"),
    table_classes=[GiveawayEntry],
)

GIVEAWAY_KEY = "GIVEAWAY"

class CleanupGiveaways(commands.Cog):
    """A cog to clean up invalid giveaway Config and database entries."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=874783520, force_registration=True)

    async def init(self) -> None:
        """Initialize the SQLite database for giveaways."""
        await self.bot.wait_until_ready()
        try:
            async with DB.transaction():
                await GiveawayEntry.create_table(if_not_exists=True).run()
                log.info("GiveawayEntry table created or verified in cleanup_giveaways.")
        except Exception as exc:
            log.error("Failed to create or verify GiveawayEntry table: ", exc_info=exc)
            raise

    @commands.is_owner()
    @commands.command()
    async def cleanup_giveaways(self, ctx: commands.Context) -> None:
        """Clean up invalid giveaway Config and database entries."""
        await ctx.defer()
        async with DB.transaction():
            data = await self.config.custom(GIVEAWAY_KEY).all()
            valid_giveaways = []
            invalid_count = 0
            fixed_count = 0

            # Check Config entries
            for guild_id, guild in data.items():
                for msgid, giveaway in guild.items():
                    # Handle legacy 'title' key
                    if "title" in giveaway and "prize" not in giveaway:
                        log.warning(f"Giveaway {msgid} in guild {guild_id} uses legacy 'title' key, mapping to 'prize'.")
                        giveaway["prize"] = giveaway["title"]
                        await self.config.custom(GIVEAWAY_KEY, guild_id, str(msgid)).set(giveaway)
                        fixed_count += 1
                    # Check required keys
                    required_keys = ["guildid", "channelid", "messageid", "endtime", "prize", "emoji"]
                    if not all(key in giveaway for key in required_keys):
                        log.error(f"Clearing invalid giveaway {msgid} from Config in guild {guild_id}")
                        await self.config.custom(GIVEAWAY_KEY, guild_id, str(msgid)).clear()
                        invalid_count += 1
                        continue
                    valid_giveaways.append((int(guild_id), int(msgid)))

            # Check database entries
            db_entries = await GiveawayEntry.select(
                GiveawayEntry.guild_id, GiveawayEntry.message_id, GiveawayEntry.created_at
            ).run()
            for entry in db_entries:
                guild_id = entry["guild_id"]
                message_id = entry["message_id"]
                created_at = entry["created_at"]
                if (guild_id, message_id) not in valid_giveaways:
                    log.warning(f"Deleting orphaned database entry for giveaway {message_id} in guild {guild_id}")
                    await GiveawayEntry.delete().where(GiveawayEntry.message_id == message_id).run()
                    invalid_count += 1
                elif not isinstance(created_at, datetime):
                    log.warning(f"Invalid created_at for giveaway {message_id}, resetting.")
                    await GiveawayEntry.update({GiveawayEntry.created_at: datetime.now()}).where(
                        GiveawayEntry.message_id == message_id
                    ).run()
                    fixed_count += 1

            await ctx.send(
                f"Cleanup complete. Fixed {fixed_count} giveaways (mapped 'title' to 'prize'). "
                f"Removed {invalid_count} invalid entries."
            )
            log.info(
                f"Cleanup complete. Fixed {fixed_count} giveaways, removed {invalid_count} invalid entries."
            )

def setup(bot):
    bot.add_cog(CleanupGiveaways(bot))