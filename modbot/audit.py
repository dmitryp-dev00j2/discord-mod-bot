import asyncio
import logging
from datetime import datetime, timezone
import discord

log = logging.getLogger(__name__)


class AuditTailer:
    """Polls Discord audit logs and records mod actions to SQLite."""

    def __init__(self, bot, storage, interval: float = 4.0):
        self.bot = bot
        self.storage = storage
        self.interval = interval
        self._last_id = {}
        self._task = None
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        await self.bot.wait_until_ready()
        while self._running:
            try:
                for guild in self.bot.guilds:
                    await self.poll_guild(guild)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("audit loop failed: %s", e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def poll_guild(self, guild: discord.Guild):
        me = guild.me or guild.get_member(self.bot.user.id)
        if not me or not me.guild_permissions.view_audit_log:
            return

        last_seen = self._last_id.get(guild.id)
        # fetch slightly larger window because discord occasionally inserts entries
        # with slightly delayed snowflake order when mod actions happen in quick bursts
        kwargs = {"limit": 15}
        if last_seen:
            kwargs["after"] = discord.Object(id=last_seen)

        entries = []
        try:
            async for entry in guild.audit_logs(**kwargs):
                entries.append(entry)
        except discord.Forbidden:
            return
        except discord.HTTPException as err:
            log.warning("failed to fetch audit log for %s: %s", guild.name, err)
            return

        if not entries:
            return

        if last_seen:
            entries.reverse()
        else:
            # first run on this guild, just prime the high watermark without dumping history
            self._last_id[guild.id] = entries[0].id
            return

        for entry in entries:
            if entry.id <= last_seen:
                continue
            self._last_id[guild.id] = max(self._last_id.get(guild.id, 0), entry.id)
            await self._handle_entry(guild, entry)

    async def _handle_entry(self, guild: discord.Guild, entry: discord.AuditLogEntry):
        action_name = None
        details = ""

        if entry.action == discord.AuditLogAction.ban:
            action_name = "ban"
        elif entry.action == discord.AuditLogAction.unban:
            action_name = "unban"
        elif entry.action == discord.AuditLogAction.kick:
            action_name = "kick"
        elif entry.action == discord.AuditLogAction.member_update:
            # member timeouts live under member_update with communication_disabled_until diff
            if hasattr(entry.after, "timed_out_until"):
                action_name = "timeout_set" if entry.after.timed_out_until else "timeout_cleared"
                if entry.after.timed_out_until:
                    details = f"until:{entry.after.timed_out_until.isoformat()}"
            elif hasattr(entry.after, "communication_disabled_until"):
                action_name = "timeout_set" if entry.after.communication_disabled_until else "timeout_cleared"
                if entry.after.communication_disabled_until:
                    details = f"until:{entry.after.communication_disabled_until.isoformat()}"

        if not action_name:
            return

        target_id = entry.target.id if entry.target else 0
        actor_id = entry.user.id if entry.user else 0

        # print(f"[audit] {guild.name}: {entry.user} -> {action_name} -> {entry.target}")
        await self.storage.record_audit_event(
            guild_id=guild.id,
            event_id=entry.id,
            action=action_name,
            actor_id=actor_id,
            target_id=target_id,
            reason=entry.reason or "",
            details=details,
            created_at=entry.created_at.replace(tzinfo=timezone.utc),
        )
