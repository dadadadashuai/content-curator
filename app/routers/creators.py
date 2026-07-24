"""Creator management CRUD endpoints."""
import json
from fastapi import APIRouter, Query, HTTPException
from ..database import get_db
from ..models import CreatorCreate, CreatorUpdate
from ..services import bilibili

router = APIRouter()


def _parse_json_field(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _creator_row_to_dict(row):
    return {
        "id": row["id"],
        "platform": row["platform"],
        "uid": row["uid"],
        "name": row["name"],
        "avatar": row["avatar"],
        "update_strategy": row["update_strategy"],
        "priority": row["priority"],
        "content_types": _parse_json_field(row["content_types"]),
        "custom_tags": _parse_json_field(row["custom_tags"]),
        "enabled": row["enabled"],
        "last_checked": row["last_checked"],
        "created_at": row["created_at"],
    }


@router.get("/creators")
async def list_creators(platform: str = Query(None)):
    db = get_db()
    if platform:
        rows = db.execute(
            "SELECT * FROM creators WHERE platform = ? ORDER BY created_at DESC",
            (platform,),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM creators ORDER BY created_at DESC").fetchall()
    return [_creator_row_to_dict(r) for r in rows]


@router.post("/creators")
async def create_creator(creator: CreatorCreate):
    db = get_db()
    name = creator.name
    if creator.platform == "bilibili" and not name and creator.uid:
        try:
            info = bilibili.get_user_info(creator.uid)
            if info and info.get("name"):
                name = info["name"]
        except Exception:
            pass

    ct_json = json.dumps(creator.content_types, ensure_ascii=False) if creator.content_types else "[]"
    tags_json = json.dumps(creator.custom_tags, ensure_ascii=False) if creator.custom_tags else "[]"

    cursor = db.execute(
        """INSERT INTO creators (platform, uid, name, update_strategy, priority,
           content_types, custom_tags, enabled)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
        (creator.platform, creator.uid, name, creator.update_strategy,
         creator.priority, ct_json, tags_json),
    )
    db.commit()
    creator_id = cursor.lastrowid
    row = db.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
    return _creator_row_to_dict(row)


@router.put("/creators/{creator_id}")
async def update_creator(creator_id: int, creator: CreatorUpdate):
    db = get_db()
    existing = db.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail=f"Creator {creator_id} not found")

    updates = {}
    if creator.name is not None:
        updates["name"] = creator.name
    if creator.update_strategy is not None:
        updates["update_strategy"] = creator.update_strategy
    if creator.priority is not None:
        updates["priority"] = creator.priority
    if creator.enabled is not None:
        updates["enabled"] = creator.enabled
    if creator.content_types is not None:
        updates["content_types"] = json.dumps(creator.content_types, ensure_ascii=False)
    if creator.custom_tags is not None:
        updates["custom_tags"] = json.dumps(creator.custom_tags, ensure_ascii=False)

    if updates:
        set_clauses = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [creator_id]
        db.execute(f"UPDATE creators SET {set_clauses} WHERE id = ?", vals)
        db.commit()

    row = db.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
    return _creator_row_to_dict(row)


@router.delete("/creators/{creator_id}")
async def delete_creator(creator_id: int, delete_notes: bool = Query(False)):
    db = get_db()
    creator = db.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
    if not creator:
        raise HTTPException(status_code=404, detail=f"Creator {creator_id} not found")
    db.execute("DELETE FROM creators WHERE id = ?", (creator_id,))
    db.commit()
    return {"message": f"Creator {creator_id} deleted"}


@router.get("/creators/{creator_id}/contents")
async def list_creator_contents(creator_id: int):
    db = get_db()
    creator = db.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
    if not creator:
        raise HTTPException(status_code=404, detail=f"Creator {creator_id} not found")
    rows = db.execute(
        "SELECT * FROM contents WHERE creator_id = ? ORDER BY created_at DESC",
        (creator_id,),
    ).fetchall()
    return [dict(r) for r in rows]
