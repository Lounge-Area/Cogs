from piccolo.conf.apps import AppConfig
from piccolo.columns import BigInt, Array, Timestamp
from piccolo.table import Table
from .giveaways import DB  # Import DB from giveaways.py

class GiveawayEntry(Table, db=DB):  # Explicitly bind to SQLite DB
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