import asyncio
import logging
from datetime import datetime, timezone
from redbot.core import commands, Config
from redbot.core.data_manager import cog_data_path
from piccolo.engine.sqlite import SQLiteEngine
from piccolo.table import Table
from piccolo.columns import BigInt, Array, Timestamp

log = logging.getLogger("red.flare.cleanup_giveaways")
GIVEAWAY_KEY = "giveaways"

DB = SQLiteEngine(path=str(cog_data_path(raw_name="Giveaways") / "giveaways.sqlite"))

class GiveawayEntry(Table, db=DB):
    guild_id = BigInt()
    message_id = BigInt(index=True)
    entrants = Array(base_column=BigInt())
    created_at = Timestamp()
    updated_at = Timestamp(auto_update=True)

class CleanupGiveaways(commands.Cog):
    """Cleanup corrupted giveaway data."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=95932766180343808)

    @commands.command()
    @commands.is_owner()
    async def cleanup_giveaways(self, ctx):
        """Clean up corrupted giveaway data in Config and database."""
        log.info("Starting giveaway cleanup...")
        async with DB.transaction():
            # Check and recreate table if necessary
            try:
                await GiveawayEntry.create_table(if_not_exists=True).run()
                log.info("GiveawayEntry table verified or created.")
            except Exception as exc:
                log.error("Failed to verify/create GiveawayEntry table: ", exc_info=exc)
                await ctx.send("Failed to verify database table. Check logs.")
                return

            # Clean Config
            data = await self.config.custom(GIVEAWAY_KEY).all()
            invalid_giveaways = []
            for guild_id, guild in data.items():
                for msgid, giveaway in guild.items():
                    if not all(key in giveaway for key in ["guildid", "channelid", "messageid", "endtime", "prize", "emoji"]):
                        log.warning(f"Invalid giveaway {msgid} in guild {guild_id}: {giveaway}")
                        invalid_giveaways.append((guild_id, msgid))
                    else:
                        try:
                            datetime.fromtimestamp(giveaway["endtime"], tz=timezone.utc)
                        except (TypeError, ValueError):
                            log.warning(f"Invalid endtime for giveaway {msgid} in guild {guild_id}")
                            invalid_giveaways.append((guild_id, msgid))

            # Remove invalid Config entries
            for guild_id, msgid in invalid_giveaways:
                await self.config.custom(GIVEAWAY_KEY, str(guild_id), str(msgid)).clear()
                log.info(f"Cleared invalid giveaway {msgid} from Config in guild {guild_id}")

            # Clean database
            try:
                entries = await GiveawayEntry.select().run()
                for entry in entries:
                    if not isinstance(entry["created_at"], str) or not entry["created_at"]:
                        log.warning(f"Invalid created_at for giveaway {entry['message_id']}, resetting.")
                        await GiveawayEntry.update({
                            GiveawayEntry.created_at: datetime.now(timezone.utc),
                            GiveawayEntry.updated_at: datetime.now(timezone.utc)
                        }).where(GiveawayEntry.message_id == entry["message_id"]).run()
                    # Check for matching Config entry
                    config_data = await self.config.custom(GIVEAWAY_KEY, str(entry["guild_id"]), str(entry["message_id"])).all()
                    if not config_data:
                        log.warning(f"No Config entry for giveaway {entry['message_id']}, deleting database entry.")
                        await GiveawayEntry.delete().where(GiveawayEntry.message_id == entry["message_id"]).run()
            except Exception as exc:
                log.error("Error cleaning database entries: ", exc_info=exc)
                await ctx.send("Error cleaning database. Check logs.")
                return

        await ctx.send("Cleanup completed. Check logs for details.")
        log.info("Giveaway cleanup completed.")

def setup(bot):
    bot.add_cog(CleanupGiveaways(bot))