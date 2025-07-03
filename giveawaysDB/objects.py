import logging
import random
from datetime import datetime, timezone
from threading import Lock
from typing import List, Set, Optional

import discord
from redbot.core import bank

log = logging.getLogger("red.flare.giveaways")

class GiveawayError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

class GiveawayExecError(GiveawayError):
    pass

class GiveawayEnterError(GiveawayError):
    pass

class AlreadyEnteredError(GiveawayError):
    pass

class Giveaway:
    def __init__(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        end_time: datetime,
        title: str = None,
        emoji: str = "🎉",
        *,
        entrants: Set[int] = None,
        ended: bool = False,
        conditions: dict = None,
        host_id: int = None
    ) -> None:
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.id = str(message_id)  # Use message ID as giveaway ID
        self.end_time = end_time
        self.title = title or "Unnamed Giveaway"
        self.emoji = emoji
        self.entrants: Set[int] = set(entrants) if entrants else set()
        self.winners: List[int] = []
        self.ended = ended
        self.conditions = conditions or {}
        self.host_id = host_id
        self._lock = Lock()
        log.info(f"Initialized giveaway {self.id} in guild {self.guild_id}")

    async def add_entrant(self, user: discord.Member) -> None:
        with self._lock:
            if self.ended:
                raise GiveawayEnterError("Giveaway has ended")
            if not self.conditions.get("multientry", False) and user.id in self.entrants:
                raise AlreadyEnteredError("You have already entered this giveaway")
            
            if not await self._check_conditions(user):  # Await the async method
                raise GiveawayEnterError("You do not meet the giveaway entry conditions")
            
            self.entrants.add(user.id)
            log.debug(f"Added entrant {user.id} to giveaway {self.id}")

    def add_entrants_by_ids(self, user_ids: List[int]) -> None:
        with self._lock:
            if self.ended:
                raise GiveawayError("Cannot add entrants to an ended giveaway")
            for user_id in user_ids:
                if user_id not in self.entrants and self._validate_entrant(user_id):
                    self.entrants.add(user_id)
            log.debug(f"Manually added entrants {user_ids} to giveaway {self.id}")

    def _validate_entrant(self, user_id: int) -> bool:
        # Simplified validation; in practice, check guild membership
        return True  # Assume valid for manual addition; enhance as needed

    def remove_entrant(self, user_id: int) -> None:
        with self._lock:
            if user_id in self.entrants:
                self.entrants.remove(user_id)
                log.debug(f"Removed entrant {user_id} from giveaway {self.id}")

    def draw_winners(self) -> List[int]:
        with self._lock:
            if self.ended:
                raise GiveawayError("Giveaway has already ended")
            winner_count = self.conditions.get("winners", 1)
            if len(self.entrants) < winner_count:
                log.warning(f"Not enough entrants for giveaway {self.id}. Needed {winner_count}, got {len(self.entrants)}")
                return []
            
            self.winners = random.sample(list(self.entrants), min(winner_count, len(self.entrants)))
            self.ended = True
            log.info(f"Drew {len(self.winners)} winners for giveaway {self.id}: {self.winners}")
            return self.winners

    async def _check_conditions(self, user: discord.Member) -> bool:  # Changed to async def
        with self._lock:
            try:
                if self.conditions.get("roles"):
                    if not any(role_id in [r.id for r in user.roles] for role_id in self.conditions["roles"]):
                        return False
                
                if self.conditions.get("blacklist"):
                    if any(role_id in [r.id for r in user.roles] for role_id in self.conditions["blacklist"]):
                        return False
                
                if self.conditions.get("joined_days"):
                    join_days = (datetime.now(timezone.utc) - user.joined_at.replace(tzinfo=timezone.utc)).days
                    if join_days < self.conditions["joined_days"]:
                        return False
                
                if self.conditions.get("account_age_days"):
                    account_days = (datetime.now(timezone.utc) - user.created_at.replace(tzinfo=timezone.utc)).days
                    if account_days < self.conditions["account_age_days"]:
                        return False
                
                if self.conditions.get("cost"):
                    if not await bank.can_spend(user, self.conditions["cost"]):  # Await here is now valid
                        return False
                    await bank.withdraw_credits(user, self.conditions["cost"])  # Await here too
                
                return self._check_bypass_roles(user)
            except Exception as e:
                log.error(f"Error checking conditions for user {user.id} in giveaway {self.id}: {str(e)}")
                return False

    def _check_bypass_roles(self, user: discord.Member) -> bool:
        bypass_roles = self.conditions.get("bypass_roles", [])
        if not bypass_roles:
            return True
        
        bypass_type = self.conditions.get("bypass_type", "or")
        user_role_ids = {r.id for r in user.roles}
        
        if bypass_type == "and":
            return all(role_id in user_role_ids for role_id in bypass_roles)
        return any(role_id in user_role_ids for role_id in bypass_roles)

    def is_active(self) -> bool:
        with self._lock:
            return not self.ended and datetime.now(timezone.utc) < self.end_time

    def get_status(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "title": self.title,
                "entrants_count": len(self.entrants),
                "winners": self.winners,
                "end_time": self.end_time.isoformat(),
                "is_active": self.is_active(),
                "winner_count": self.conditions.get("winners", 1)
            }

    def __str__(self) -> str:
        return f"{self.title} - Ends at {self.end_time}"