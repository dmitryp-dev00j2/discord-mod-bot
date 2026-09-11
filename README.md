# modbot

Discord bot I keep running on my servers to spot mention spam, store audit log events in SQLite, and push stats to Prometheus.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Create a `.env` file or export the variables in systemd:

```env
DISCORD_TOKEN=your_bot_token_here
MODBOT_DB_PATH=modbot.db
METRICS_PORT=9100
MENTION_LIMIT=7
MENTION_WINDOW_SEC=10
```

## Running

```bash
python -m modbot
```

Run test suite:
```bash
pytest
```

## Prometheus metrics

The bot exposes an HTTP server on `METRICS_PORT` (default 9100) scraping target:

- `modbot_messages_total{guild_id}` - counter of seen messages
- `modbot_mention_spams_total{guild_id}` - triggered mention flood actions
- `modbot_audit_events_total{action_type}` - audit entries polled and written to db
- `modbot_actions_taken_total{action}` - auto timeouts / kicks / deletions

<!-- checked: 2026-09-11 -->
