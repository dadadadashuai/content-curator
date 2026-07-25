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
    }
