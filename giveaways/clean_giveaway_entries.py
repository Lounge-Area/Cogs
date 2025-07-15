import sqlite3
from datetime import datetime

def clean_invalid_entries():
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
                print(f"Valid entry: message_id={message_id}, created_at={created_at}")
            except ValueError:
                print(f"Invalid entry found: message_id={message_id}, created_at={created_at}")
                # Delete invalid entry
                cursor.execute("DELETE FROM giveaway_entry WHERE message_id = ?", (message_id,))
                conn.commit()
                print(f"Deleted invalid entry: message_id={message_id}")
        
        conn.close()
        print("Database cleanup completed.")
    except Exception as e:
        print(f"Error cleaning entries: {e}")

if __name__ == "__main__":
    clean_invalid_entries()