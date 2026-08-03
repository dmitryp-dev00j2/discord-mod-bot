import asyncio
import datetime
import logging
from collections import defaultdict
import discord
from discord.ext import commands

from modbot.storage import Storage
from modbot.rules import evaluate_message, FloodTracker
from modbot.audit import AuditTailer
from modbot.metrics import (
    start_metrics_server,
    MESSAGES_EVALUATED,
    FLOOD_ALERTS,
    ACTIONS_TAKEN,
    AUDIT_ENTRIES_PROCESSED,
)

log = logging.getLogger(__name__)


class ModBot(commands.Bot):
    """Custom discord client tracking mention floods and audit entries."""

    def __init__(self, db_path: str = "modbot.db", metrics_port: int = 9108, target_guild_id: int | None = None):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.moderation = True

        super().__init__(command_prefix="!modbot ", intents=intents)
        self.db_path = db_path
        self.metrics_port = metrics_port
        self.target_guild_id = target_guild_id
        self.store = Storage(self.db_path)
        self.flood_tracker = FloodTracker(window_seconds=10, max_mentions=7)
        self.audit_tailers: dict[int, AuditTailer] = {}
        self._bg_tasks: list[asyncio.Task] = []
        self._stopping = False

    async def setup_hook(self):
        await self.store.connect()
        start_metrics_server(self.metrics_port)
        log.info("store ready, prometheus exporter bound to port %d", self.metrics_port)

    async def on_ready(self):
        log.info("modbot connected as %s (id: %d)", self.user, self.user.id)
        for guild in self.guilds:
            if self.target_guild_id and guild.id != self.target_guild_id:
                continue
            if guild.id not in self.audit_tailers:
                tailer = AuditTailer(guild, self.store)
                self.audit_tailers[guild.id] = tailer
                task = asyncio.create_task(self._run_audit_loop(tailer))
                self._bg_tasks.append(task)

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if self.target_guild_id and message.guild.id != self.target_guild_id:
            return

        MESSAGES_EVALUATED.labels(guild=str(message.guild.id)).inc()

        # check raw mentions and burst frequency
        is_flood, count = self.flood_tracker.register(message.author.id, message)
        if is_flood:
            FLOOD_ALERTS.labels(guild=str(message.guild.id)).inc()
            await self._handle_flood(message, count)
            return

        action = evaluate_message(message)
        if action and action.should_delete:
            try:
                await message.delete()
                ACTIONS_TAKEN.labels(type="message_delete", reason=action.reason).inc()
                await self.store.log_incident(
                    guild_id=message.guild.id,
                    user_id=message.author.id,
                    action="delete",
                    reason=action.reason,
                    raw_content=message.content[:500],
                )
            except discord.Forbidden:
                log.warning("no perms to delete msg in channel %s", message.channel)
            except discord.HTTPException as err:
                log.error("failed deleting message %d: %s", message.id, err)

        await self.process_commands(message)

    async def _handle_flood(self, message: discord.Message, count: int):
        guild = message.guild
        log.warning("mention flood from user %s (%d) count=%d", message.author, message.author.id, count)
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        # FIXME: temporary timeout duration should come from server config table
        timeout_until = discord.utils.utcnow() + datetime.timedelta(minutes=15)
        try:
            member = guild.get_member(message.author.id)
            if member and not member.guild_permissions.administrator:
                await member.timeout(timeout_until, reason="automated: mention flood threshold exceeded")
                ACTIONS_TAKEN.labels(type="timeout", reason="mention_flood").inc()
                # print(f"DEBUG timeout applied to {member.id}")
        except discord.Forbidden:
            log.warning("missing timeout perms for user %d in guild %s", message.author.id, guild.name)
        except Exception as e:
            log.exception("unexpected error timing out user %d: %s", message.author.id, e)

        await self.store.log_incident(
            guild_id=guild.id,
            user_id=message.author.id,
            action="timeout_15m",
            reason=f"mention flood ({count} mentions in window)",
            raw_content=message.content[:500],
        )

    async def _run_audit_loop(self, tailer: AuditTailer):
        # poll interval is slightly jittered inside tailer
        while not self._stopping:
            try:
                new_entries = await tailer.poll()
                if new_entries:
                    AUDIT_ENTRIES_PROCESSED.labels(guild=str(tailer.guild.id)).inc(len(new_entries))
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("error in audit poll loop for guild %d: %s", tailer.guild.id, e)
            await asyncio.sleep(5.0)

    async def cleanup(self):
        self._stopping = True
        for task in self._bg_tasks:
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        await self.store.close()
        log.info("bot resources closed")
