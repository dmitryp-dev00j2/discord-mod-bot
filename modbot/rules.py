import re
import time
import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional, List, Tuple
import discord

INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discord(?:app)?\.com/invite)/([a-zA-Z0-9\-]+)",
    re.IGNORECASE,
)

# users pinging same raw @everyone in codeblocks or plain text without actual mention permission
RAW_EVERYONE_RE = re.compile(r"@(everyone|here)")


@dataclass
class RuleViolation:
    rule: str
    description: str
    matched: str = ""


class RuleEngine:
    """Evaluates incoming messages against spam, invite, and mention heuristics."""

    def __init__(
        self,
        max_mentions: int = 5,
        dup_burst_count: int = 4,
        dup_window_sec: float = 10.0,
    ):
        self.max_mentions = max_mentions
        self.dup_burst_count = dup_burst_count
        self.dup_window_sec = dup_window_sec
        self.allowed_invite_codes = set()
        # (guild_id, user_id) -> deque of (hash, timestamp)
        self._user_history = defaultdict(lambda: deque(maxlen=20))

    def clean_stale_history(self, now: float):
        # occasional prune so memory doesn't just grow forever on dead servers
        for key in list(self._user_history.keys()):
            q = self._user_history[key]
            while q and now - q[0][1] > self.dup_window_sec * 2:
                q.popleft()
            if not q:
                del self._user_history[key]

    def check_invites(self, content: str) -> Optional[RuleViolation]:
        matches = INVITE_RE.findall(content)
        for code in matches:
            if code.lower() not in self.allowed_invite_codes:
                return RuleViolation(
                    rule="invite_link",
                    description=f"Unauthorized discord invite: {code}",
                    matched=code,
                )
        return None

    def check_mentions(self, message: discord.Message) -> Optional[RuleViolation]:
        # deduplicate user IDs in case the client duplicates mentions
        user_ids = {u.id for u in message.mentions if not u.bot}
        role_ids = {r.id for r in message.role_mentions}
        total = len(user_ids) + len(role_ids)

        if message.mention_everyone:
            total += 1

        if total > self.max_mentions:
            return RuleViolation(
                rule="mention_flood",
                description=f"Mention count ({total}) exceeded limit of {self.max_mentions}",
                matched=str(total),
            )
        return None

    def check_duplicate_burst(
        self, guild_id: int, user_id: int, raw_text: str, now: float
    ) -> Optional[RuleViolation]:
        if not raw_text or len(raw_text.strip()) < 8:
            # ignore short 'lol', 'ok', emojis etc
            return None

        normalized = " ".join(raw_text.strip().lower().split())
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()

        history = self._user_history[(guild_id, user_id)]
        history.append((digest, now))

        cutoff = now - self.dup_window_sec
        recent_matches = sum(1 for h, ts in history if h == digest and ts >= cutoff)

        if recent_matches >= self.dup_burst_count:
            return RuleViolation(
                rule="duplicate_burst",
                description=f"Sent identical message {recent_matches} times in {self.dup_window_sec}s",
                matched=raw_text[:50],
            )
        return None

    def evaluate(self, message: discord.Message) -> List[RuleViolation]:
        if message.author.bot or not message.guild:
            return []

        now = time.monotonic()
        violations = []

        inv = self.check_invites(message.content)
        if inv:
            violations.append(inv)

        m = self.check_mentions(message)
        if m:
            violations.append(m)

        # FIXME: skip duplicate check if user is whitelisted mod/admin
        dup = self.check_duplicate_burst(message.guild.id, message.author.id, message.content, now)
        if dup:
            violations.append(dup)

        if len(self._user_history) > 1000:
            self.clean_stale_history(now)

        return violations
