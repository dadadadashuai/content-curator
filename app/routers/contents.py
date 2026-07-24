"""Content list, import, and management endpoints."""
import json
from fastapi import APIRouter, Query, HTTPException
from ..database import get_db
from ..services import bilibili, pipeline

router = APIRouter()


def _parse_json_field(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


@router.get("/contents")
async def list_contents(
    status: str = Query(None),
    creator_id: int = Query(None),
    category: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    db = get_db()
    where_clauses = []
    params = []
    if status:
        where_clauses.append("c.status = ?")
        params.append(status)
    if creator_id is not None:
        where_clauses.append("c.creator_id = ?")
        params.append(creator_id)
    if category:
        where_clauses.append("c.category = ?")
        params.append(category)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    total = db.execute(
        f"SELECT COUNT(*) FROM contents c LEFT JOIN creators cr ON c.creator_id = cr.id WHERE {where_sql}",
        params,
    ).fetchone()[0]

    offset = (page - 1) * page_size
    rows = db.execute(
        f"""SELECT c.*, cr.name as up_name, cr.platform as creator_platform
        FROM contents c
        LEFT JOIN creators cr ON c.creator_id = cr.id
        WHERE {where_sql}
        ORDER BY c.created_at DESC
        LIMIT ? OFFSET ?""",
        params + [page_size, offset],
    ).fetchall()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/contents/{content_id}")
async def get_content(content_id: int):
    db = get_db()
    row = db.execute(
        """SELECT c.*, cr.name as up_name
        FROM contents c
        LEFT JOIN creators cr ON c.creator_id = cr.id
        WHERE c.id = ?""",
        (content_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")
    return dict(row)


@router.delete("/contents/{content_id}")
async def delete_content(content_id: int):
    db = get_db()
    db.execute("DELETE FROM contents WHERE id = ?", (content_id,))
    db.commit()
    return {"message": f"Content {content_id} deleted"}


@router.post("/contents/import")
async def bulk_import(data: dict):
    db = get_db()
    creator_id = data.get("creator_id")
    platform = data.get("platform", "bilibili")
    items = data.get("items", [])
    if not creator_id:
        raise HTTPException(status_code=400, detail="creator_id is required")
    if not items:
        raise HTTPException(status_code=400, detail="items list is required")

    inserted_ids = []
    skipped = 0
    for item in items:
        bvid = item.get("bvid", "")
        title = item.get("title", "")
        url = item.get("url", "")
        if bvid:
            existing = db.execute(
                "SELECT id FROM contents WHERE bvid = ? AND creator_id = ?",
                (bvid, creator_id),
            ).fetchone()
            if existing:
                skipped += 1
                continue
        cursor = db.execute(
            "INSERT INTO contents (creator_id, bvid, title, url, platform, status) VALUES (?, ?, ?, ?, ?, 'pending')",
            (creator_id, bvid, title, url, platform),
        )
        inserted_ids.append(cursor.lastrowid)
    db.commit()
    return {"imported": len(inserted_ids), "skipped": skipped, "content_ids": inserted_ids}


@router.get("/creators/{creator_id}/check")
async def check_new_videos(creator_id: int):
    """Check for new videos from a bilibili creator."""
    db = get_db()
    creator = db.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
    if not creator:
        raise HTTPException(status_code=404, detail=f"Creator {creator_id} not found")
    if creator["platform"] != "bilibili":
        raise HTTPException(status_code=400, detail="Only bilibili creators are supported")

    uid = creator["uid"]
    existing = db.execute(
        "SELECT bvid FROM contents WHERE creator_id = ? AND bvid IS NOT NULL",
        (creator_id,),
    ).fetchall()
    processed_bvids = {row["bvid"] for row in existing}

    try:
        all_videos = bilibili.get_all_videos_with_info(uid, processed_bvids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bilibili API error: {str(e)}")

    strategy = creator["update_strategy"] or "select"
    inserted = []
    for video in all_videos.get("videos", []):
        bvid = video.get("bvid", "")
        if not bvid or bvid in processed_bvids:
            continue
        cursor = db.execute(
            "INSERT INTO contents (creator_id, bvid, title, url, platform, status) VALUES (?, ?, ?, ?, 'bilibili', 'pending')",
            (creator_id, bvid, video.get("title", ""), f"https://www.bilibili.com/video/{bvid}"),
        )
        content_id = cursor.lastrowid
        inserted.append({"content_id": content_id, "bvid": bvid, "title": video.get("title", "")})
        if strategy == "auto":
            db.execute("INSERT INTO task_queue (content_id, task_type, status) VALUES (?, 'process', 'pending')", (content_id,))

    db.execute("UPDATE creators SET last_checked = datetime('now') WHERE id = ?", (creator_id,))
    db.commit()
    return {"creator_id": creator_id, "new_count": len(inserted), "new_videos": inserted, "strategy": strategy}


@router.post("/contents/batch-process")
async def batch_process(data: dict):
    content_ids = data.get("content_ids", [])
    if not content_ids:
        raise HTTPException(status_code=400, detail="content_ids list is required")
    results = []
    for cid in content_ids:
        result = await pipeline.process_content(cid)
        results.append({"content_id": cid, **result})
    success_count = sum(1 for r in results if r.get("success"))
    return {"total": len(content_ids), "success": success_count, "errors": len(content_ids) - success_count, "results": results}
