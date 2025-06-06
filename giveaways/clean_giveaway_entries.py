import asyncio
import sqlite3
from datetime import datetime
from piccolo.engine import engine_finder
from piccolo.table import Table
from piccolo.columns import BigInt, JSONB, Timestamp

class GiveawayEntry(Table):
    guild_id = BigInt()
    message_id = BigInt(primary_key=True)
    entrants = JSONB()
    created_at = Timestamp()

async def clean_invalid_entries():
    db = engine_finder()
    try:
        # Connect to SQLite database
        conn = sqlite3.connect('/home/floorbs/.local/share/Red-DiscordBot/data/Lounge/cogs/CogManager/cogs/giveaways/giveaways.sqlite')
        cursor = conn.cursor()
        
        # Query all entries
        cursor.execute("SELECT message_id, created_at FROM giveaway_entry")
        rows = cursor.fetchall()
        
        for message_id, created_at in rows:
            try:
                # Attempt to parse created_at as ISO timestamp
                datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except ValueError:
                print(f"Invalid entry found: message_id={message_id}, created_at={created_at}")
                # Delete invalid entry
                await GiveawayEntry.delete().where(GiveawayEntry.message_id == message_id).run()
                print(f"Deleted invalid entry: message_id={message_id}")
        
        conn.close()
    except Exception as e:
        print(f"Error cleaning entries: {e}")
    finally:
        await db.close_connection()

if __name__ == "__main__":
    asyncio.run(clean_invalid_entries())