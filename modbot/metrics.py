from prometheus_client import Counter, Gauge, Histogram, start_http_server
import logging

log = logging.getLogger(__name__)

MESSAGES_TOTAL = Counter(
    "modbot_messages_total",
    "Total Discord messages observed",
    ["guild_id"],
)

INFRACTIONS_TOTAL = Counter(
    "modbot_infractions_total",
    "Detected rule infractions",
    ["guild_id", "rule", "action"],
)

AUDIT_EVENTS_TOTAL = Counter(
    "modbot_audit_events_total",
    "Audit log entries ingested",
    ["guild_id", "action"],
)

AUDIT_PROCESSING_TIME = Histogram(
    "modbot_audit_processing_seconds",
    "Time spent pulling and analyzing audit tails",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

ACTIVE_TRACKERS = Gauge(
    "modbot_active_window_trackers",
    "Number of active in-memory rate buckets",
)


def start_metrics(port: int = 9100, host: str = "0.0.0.0"):
    """Spins up background HTTP server for scraping."""
    try:
        start_http_server(port, addr=host)
        log.info(f"metrics exporter listening on {host}:{port}")
    except OSError as e:
        # typically port already taken if running tests or reloaders
        log.warning(f"could not bind metrics port {port}: {e}")
