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


@router.get("/creators/{creator_id}/collections")
async def check_collections(creator_id: int):
    """Check B站 collections/合集 for a creator."""
    db = get_db()
    creator = db.execute("SELECT * FROM creators WHERE id=?", (creator_id,)).fetchone()
    if not creator:
        raise HTTPException(status_code=404, detail=f"Creator {creator_id} not found")
    if creator["platform"] != "bilibili":
        raise HTTPException(status_code=400, detail="Only bilibili supports collections")
    from ..services import bilibili
    collections = bilibili.check_collections(creator["uid"])
    return {"creator_id": creator_id, "collections": collections}


@router.post("/contents/batch-operations")
async def batch_operations(data: dict):
    """Batch operations on contents.
    Body: {action: 'reprocess'|'delete'|'skip'|'change_category', ids: [1,2,3], category?: '新领域'}
    """
    action = data.get("action", "")
    ids = data.get("ids", [])
    category = data.get("category", "")

    if not ids:
        raise HTTPException(status_code=400, detail="ids list required")

    db = get_db()
    results = []

    if action == "reprocess":
        from ..services import pipeline
        for cid in ids:
            r = await pipeline.process_content(cid)
            results.append({"id": cid, "success": r.get("success", False)})
    elif action == "delete":
        for cid in ids:
            # Also delete Obsidian note if exists
            row = db.execute("SELECT note_path FROM contents WHERE id=?", (cid,)).fetchone()
            if row and row["note_path"]:
                import os
                try: os.remove(row["note_path"])
                except: pass
            db.execute("DELETE FROM contents WHERE id=?", (cid,))
        db.commit()
        results.append({"deleted": len(ids)})
    elif action == "skip":
        for cid in ids:
            db.execute("UPDATE contents SET status='skipped' WHERE id=?", (cid,))
        db.commit()
        results.append({"skipped": len(ids)})
    elif action == "change_category":
        if not category:
            raise HTTPException(status_code=400, detail="category required for change_category")
        for cid in ids:
            db.execute("UPDATE contents SET category=? WHERE id=?", (category, cid))
        db.commit()
        results.append({"changed": len(ids), "category": category})
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    return {"action": action, "results": results}


@router.put("/contents/{content_id}/tags")
async def update_content_tags(content_id: int, data: dict):
    """Update custom tags for a content item."""
    tags = data.get("tags", [])
    db = get_db()
    import json
    db.execute("UPDATE contents SET content_tags=? WHERE id=?",
               (json.dumps(tags, ensure_ascii=False), content_id))
    db.commit()
    return {"content_id": content_id, "tags": tags}


@router.put("/contents/{content_id}/summary")
async def update_content_summary(content_id: int, data: dict):
    """Update AI summary text (for manual editing in review drawer)."""
    summary = data.get("summary", "")
    db = get_db()
    db.execute("UPDATE contents SET ai_summary=? WHERE id=?", (summary, content_id))
    db.commit()
    return {"content_id": content_id, "updated": True}


@router.post("/contents/aggregate")
async def aggregate_topics(data: dict):
    """AI-powered cross-source topic aggregation.
    Reads all done notes, groups by category, uses AI to extract topics and merge.
    """
    from ..services import ai_summary
    from ..config import get_vault_path
    from ..services import obsidian_writer
    import os

    db = get_db()
    done_items = db.execute(
        "SELECT id, title, category, ai_summary FROM contents WHERE status='done' ORDER BY category"
    ).fetchall()

    if not done_items:
        return {"error": "No completed content to aggregate"}

    # Group by category
    from collections import defaultdict
    by_cat = defaultdict(list)
    for item in done_items:
        cat = item["category"] or "未分类"
        by_cat[cat].append(dict(item))

    vault = get_vault_path()
    all_domain_dir = vault / "全领域"
    all_domain_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for cat, items in by_cat.items():
        if len(items) < 2:
            continue  # Skip single-item categories

        # Build context for AI
        notes_text = "\n\n---\n\n".join([
            f"【{i['title']}】\n{(i['ai_summary'] or '')[:1000]}"
            for i in items[:20]
        ])

        prompt = f"""你是知识聚合助手。以下是「{cat}」领域的多篇文章摘要。
请提取出该领域的核心主题（2-5个），每个主题合并所有相关文章的要点。

格式要求：
# 主题：xxx
## 要点1：xxx
- 关键事实（≤30字）
> 来源：[[初始分类/{cat}/标题1]]、[[初始分类/{cat}/标题2]]

## 要点2：xxx
- 关键事实
> 来源：[[初始分类/{cat}/标题3]]

注意事项：
- 每条要点≤30字，整篇≤300字
- 每组要点必须附来源[[]]
- 同一主题合并多来源，去重

文章摘要：
{notes_text}
"""
        try:
            from ..config import get_ai_config
            import os
            ai_cfg = get_ai_config()
            result = ai_summary._call_api(
                "你是知识聚合助手，只输出Markdown正文。",
                prompt, timeout=90, max_tokens=2000
            )

            # Write to 全领域/{category}.md
            cat_path = all_domain_dir / f"{cat}.md"
            cat_path.write_text(result, encoding="utf-8")
            results.append({"category": cat, "topics_file": str(cat_path), "notes_count": len(items)})
        except Exception as e:
            results.append({"category": cat, "error": str(e)})

    return {"aggregated": len(results), "results": results}


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
