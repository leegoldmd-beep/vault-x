"""
Email Guard — Centralized send cap & kill switch enforcement.
All outbound email paths check this before sending.
"""
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger("email_guard")


async def get_guard_config(db):
    """Get the current guard settings from dawn_patrol_config."""
    config = await db.dawn_patrol_config.find_one({}, {"_id": 0})
    return {
        "kill_switch": (config or {}).get("kill_switch", False),
        "daily_send_cap": (config or {}).get("daily_send_cap", 30),
    }


async def get_daily_send_count(db):
    """Count emails sent today (UTC)."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    count = await db.email_tracking.count_documents({"created_at": {"$gte": today_start}})
    return count


async def can_send_email(db):
    """Check if sending is allowed. Returns (allowed: bool, reason: str)."""
    config = await get_guard_config(db)

    if config["kill_switch"]:
        logger.warning("Email blocked — kill switch is ON")
        return False, "Kill switch is active — all outbound email paused"

    cap = config["daily_send_cap"]
    if cap > 0:
        sent_today = await get_daily_send_count(db)
        if sent_today >= cap:
            logger.warning(f"Email blocked — daily cap reached ({sent_today}/{cap})")
            return False, f"Daily send cap reached ({sent_today}/{cap})"

    return True, "OK"


async def record_send(db, recipient, send_type="general"):
    """Record a send for cap tracking (called after successful send)."""
    await db.daily_send_log.insert_one({
        "recipient": recipient,
        "send_type": send_type,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    })
