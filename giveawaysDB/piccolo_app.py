from piccolo.conf.apps import AppConfig
from piccolo.columns import BigInt, Array, Timestamp
from piccolo.table import Table
from piccolo.engine.sqlite import SQLiteEngine
from redbot.core.data_manager import cog_data_path

# SQLite configuration
DB = SQLiteEngine(path=str(cog_data_path(raw_name="Giveaways") / "giveaways.db"))

class GiveawayEntry(Table, db=DB):
    guild_id = BigInt()
    message_id = BigInt(index=True)
    entrants = Array(base_column=BigInt())
    created_at = Timestamp()
    updated_at = Timestamp(auto_update=True)

APP_CONFIG = AppConfig(
    app_name="giveaways",
    migrations_folder_path="",
    table_classes=[GiveawayEntry],
)