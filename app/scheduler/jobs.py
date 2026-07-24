# content-curator/app/scheduler/jobs.py
"""APScheduler jobs — periodic content checking and processing."""
import logging
import json
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..database import get_db
from ..config import get_setting, get_setting_json
from ..services import bilibili

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def check_updates():
    """Check all enabled creators for new content."""
    conn = get_db()
    creators = conn.execute(
        "SELECT * FROM creators WHERE enabled=1 AND update_strategy != 'paused'"
    ).fetchall()
    conn.close()

    for c in creators:
        c = dict(c)
        try:
            if c["platform"] == "bilibili":
                await _check_bilibili(c)
            # wechat checking can be added later
        except Exception as e:
            logger.error(f"Check failed for creator {c['name']}({c['uid']}): {e}")

    # Update last_checked for all
    conn = get_db()
    conn.execute(
        "UPDATE creators SET last_checked=datetime('now') WHERE enabled=1"
    )
    conn.commit()
    conn.close()


async def _check_bilibili(creator: dict):
    """Check a single bilibili creator for new videos."""
    conn = get_db()
    processed_rows = conn.execute(
        "SELECT bvid FROM contents WHERE creator_id=? AND bvid IS NOT NULL",
        (creator["id"],)
    ).fetchall()
    processed_bvids = {r["bvid"] for r in processed_rows}
    conn.close()

    result = bilibili.get_all_videos_with_info(creator["uid"], processed_bvids)
    new_videos = [v for v in result.get("videos", []) if not v.get("processed", False)]

    if not new_videos:
        logger.info(f"No new videos for {creator.get('name', creator['uid'])}")
        return

    logger.info(f"Found {len(new_videos)} new videos for {creator.get('name', creator['uid'])}")

    conn = get_db()
    for v in new_videos:
        # Insert as pending content
        conn.execute(
            "INSERT OR IGNORE INTO contents(creator_id, platform, bvid, title, duration, pub_date, status) "
            "VALUES(?, 'bilibili', ?, ?, ?, ?, 'pending')",
            (
                creator["id"],
                v.get("bvid", ""),
                v.get("title", ""),
                v.get("duration", 0),
                datetime.fromtimestamp(v.get("pubdate", 0)).isoformat() if v.get("pubdate") else None,
            )
        )

    # If auto strategy, enqueue all for processing
    if creator["update_strategy"] == "auto":
        new_rows = conn.execute(
            "SELECT id FROM contents WHERE creator_id=? AND status='pending'",
            (creator["id"],)
        ).fetchall()
        conn.commit()
        conn.close()

        # Process each (async, sequential to avoid rate limits)
        from ..services.pipeline import process_content
        for row in new_rows:
            try:
                await process_content(row["id"])
            except Exception as e:
                logger.error(f"Auto-process failed for content {row['id']}: {e}")
    else:
        conn.commit()
        conn.close()


def start_scheduler():
    """Initialize and start the scheduler."""
    schedule_config = get_setting_json("schedule_config", {})
    check_time = schedule_config.get("check_time", "09:00")

    hour, minute = 9, 0
    try:
        parts = check_time.split(":")
        hour, minute = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        pass

    # Daily check at configured time
    scheduler.add_job(
        check_updates,
        CronTrigger(hour=hour, minute=minute),
        id="check_updates",
        replace_existing=True
    )

    # Also check every 6 hours for realtime priority creators
    scheduler.add_job(
        check_updates,
        CronTrigger(hour="*/6"),
        id="check_realtime",
        replace_existing=True
    )

    scheduler.start()
    logger.info(f"Scheduler started — daily check at {hour:02d}:{minute:02d}, realtime every 6h")


def stop_scheduler():
    """Stop the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
