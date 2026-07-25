"""Processing pipeline control endpoints."""
from fastapi import APIRouter, Query, HTTPException
from ..database import get_db
from ..services import pipeline

router = APIRouter()


@router.post("/process/{content_id}")
async def process_content(content_id: int):
    db = get_db()
    content = db.execute("SELECT * FROM contents WHERE id = ?", (content_id,)).fetchone()
    if not content:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")
    result = await pipeline.process_content(content_id)
    return {"content_id": content_id, **result}


@router.post("/process/bvid/{bvid}")
async def process_by_bvid(bvid: str):
    """Directly process a video by BV number — no creator needed."""
    db = get_db()
    existing = db.execute("SELECT id FROM contents WHERE bvid = ?", (bvid,)).fetchone()
    if existing:
        content_id = existing["id"]
    else:
        cursor = db.execute(
            "INSERT INTO contents (bvid, platform, status, title, url) VALUES (?, 'bilibili', 'pending', ?, ?)",
            (bvid, bvid, f"https://www.bilibili.com/video/{bvid}"),
        )
        db.commit()
        content_id = cursor.lastrowid
    result = await pipeline.process_content(content_id)
    return {"content_id": content_id, **result}


@router.post("/process/bvid-batch")
async def process_bvid_batch(data: dict):
    """Batch process multiple BV numbers. Accept {bvids: 'BV1xxx\nBV2yyy'}."""
    raw = data.get("bvids", "")
    bvids = [line.strip() for line in raw.strip().split("\n") if line.strip() and line.strip().startswith("BV")]
    if not bvids:
        raise HTTPException(status_code=400, detail="No valid BV numbers found")
    results = []
    for bvid in bvids:
        db = get_db()
        existing = db.execute("SELECT id FROM contents WHERE bvid = ?", (bvid,)).fetchone()
        if existing:
            content_id = existing["id"]
        else:
            cursor = db.execute(
                "INSERT INTO contents (bvid, platform, status, title, url) VALUES (?, 'bilibili', 'pending', ?, ?)",
                (bvid, bvid, f"https://www.bilibili.com/video/{bvid}"),
            )
            db.commit()
            content_id = cursor.lastrowid
        r = await pipeline.process_content(content_id)
        results.append({"bvid": bvid, "success": r.get("success", False), "title": r.get("title", ""), "error": r.get("error", "")})
    success_count = sum(1 for r in results if r["success"])
    return {"total": len(bvids), "success": success_count, "failed": len(bvids) - success_count, "results": results}


@router.post("/process/retry/{content_id}")
async def retry_content(content_id: int):
    db = get_db()
    content = db.execute("SELECT * FROM contents WHERE id = ?", (content_id,)).fetchone()
    if not content:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")
    result = await pipeline.retry_content(content_id)
    return {"content_id": content_id, **result}


@router.get("/process/queue")
async def list_queue(status: str = Query(None)):
    db = get_db()
    if status:
        rows = db.execute(
            """SELECT tq.*, c.title as content_title, c.bvid, c.creator_id,
                   cr.name as creator_name
            FROM task_queue tq
            LEFT JOIN contents c ON tq.content_id = c.id
            LEFT JOIN creators cr ON c.creator_id = cr.id
            WHERE tq.status = ?
            ORDER BY tq.id DESC""",
            (status,),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT tq.*, c.title as content_title, c.bvid, c.creator_id,
                   cr.name as creator_name
            FROM task_queue tq
            LEFT JOIN contents c ON tq.content_id = c.id
            LEFT JOIN creators cr ON c.creator_id = cr.id
            ORDER BY tq.id DESC""",
        ).fetchall()
    return [dict(r) for r in rows]


@router.delete("/process/queue/{task_id}")
async def delete_task(task_id: int):
    """Delete a task from the queue."""
    db = get_db()
    db.execute("DELETE FROM task_queue WHERE id = ?", (task_id,))
    db.commit()
    return {"message": f"Task {task_id} deleted"}


@router.get("/process/stats")
async def process_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM contents").fetchone()[0]
    rows = db.execute("SELECT status, COUNT(*) as count FROM contents GROUP BY status").fetchall()
    status_map = {row["status"]: row["count"] for row in rows}

    # 24h stats
    done_24h = db.execute(
        "SELECT COUNT(*) FROM contents WHERE status='done' AND processed_at > datetime('now', '-1 day')"
    ).fetchone()[0]
    failed_24h = db.execute(
        "SELECT COUNT(*) FROM contents WHERE status='failed' AND processed_at > datetime('now', '-1 day')"
    ).fetchone()[0]

    # Queue length
    queue_len = db.execute("SELECT COUNT(*) FROM task_queue WHERE status='pending'").fetchone()[0]

    return {
        "total": total,
        "pending": status_map.get("pending", 0),
        "fetching": status_map.get("fetching", 0),
        "transcribing": status_map.get("transcribing", 0),
        "cleaning": status_map.get("cleaning", 0),
        "classifying": status_map.get("classifying", 0),
        "extracting": status_map.get("extracting", 0),
        "done": status_map.get("done", 0),
        "failed": status_map.get("failed", 0),
        "reviewing": status_map.get("reviewing", 0),
        "skipped": status_map.get("skipped", 0),
        "done_24h": done_24h,
        "failed_24h": failed_24h,
        "queue_length": queue_len,
    }


@router.post("/process/skip/{content_id}")
async def skip_content(content_id: int):
    """Mark a content as skipped."""
    db = get_db()
    db.execute("UPDATE contents SET status='skipped' WHERE id=?", (content_id,))
    db.commit()
    return {"content_id": content_id, "status": "skipped"}


@router.post("/process/approve/{content_id}")
async def approve_content(content_id: int):
    """Approve reviewed content — writes Obsidian note and marks as done."""
    from ..services import pipeline as pl
    db = get_db()
    row = db.execute("SELECT * FROM contents WHERE id=?", (content_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")
    if row["status"] != "reviewing":
        raise HTTPException(status_code=400, detail=f"Content is in '{row['status']}' state, must be 'reviewing' to approve")

    import json as _json
    from ..services import obsidian_writer

    content = dict(row)
    summary = content.get("ai_summary", "")
    structured_info = content.get("structured_info", "")
    used_frames = bool(content.get("used_frames", 0))
    try:
        frame_decision = _json.loads(content.get("frame_decision", "{}")) if content.get("frame_decision") else {}
    except:
        frame_decision = {}

    bvid = content.get("bvid", "")
    note_path = obsidian_writer.save_note(
        content_data={
            "bvid": bvid,
            "title": content.get("title", ""),
            "up_name": content.get("up_name", ""),
            "up_uid": content.get("up_uid", content.get("up_mid", "")),
            "aid": content.get("aid", ""),
            "cid": content.get("cid", ""),
            "duration": content.get("duration", 0),
            "url": content.get("url", f"https://www.bilibili.com/video/{bvid}"),
            "cover": content.get("cover", ""),
            "pubdate": content.get("pubdate", 0),
            "platform": content.get("platform", "bilibili"),
            "content_type": content.get("content_type", ""),
            "manual": not bool(content.get("creator_id")),
        },
        summary=summary,
        category=content.get("category", "未分类"),
        sub_category=content.get("sub_category", ""),
        frame_analysis="",
        frame_decision=frame_decision,
        structured_info=structured_info,
        used_frames=used_frames
    )

    conn = get_db()
    conn.execute("UPDATE contents SET status='done', note_path=?, processed_at=datetime('now') WHERE id=?",
                 (note_path, content_id))
    conn.commit()
    conn.close()
    return {"content_id": content_id, "status": "done", "note_path": note_path}


@router.get("/process/detail/{content_id}")
async def get_process_detail(content_id: int):
    """Get processing details for the side drawer — includes AI summary, structured info, frame decision."""
    db = get_db()
    row = db.execute("SELECT * FROM contents WHERE id=?", (content_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")
    d = dict(row)
    # Parse JSON fields
    import json as _json
    if d.get("frame_decision"):
        try: d["frame_decision"] = _json.loads(d["frame_decision"])
        except: pass
    return d
