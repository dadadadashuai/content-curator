"""Note review and fact-checking endpoints."""
import os
import asyncio
import hashlib
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException
from ..database import get_db
from ..models import ClaimResolve
from ..services import obsidian_writer, ai_summary
from ..config import get_setting, get_vault_path

router = APIRouter()


@router.post("/review")
async def batch_review(
    mode: str = Query("auto"),
    batch_size: int = Query(10, ge=1, le=200),
):
    """Batch review notes for quality and fact-checking."""
    db = get_db()
    try:
        note_files = obsidian_writer._iter_note_files()
        if not note_files:
            return {"status": "no_notes", "message": "No notes found in vault"}

        to_review = note_files[:batch_size]
        notes_with_content = []
        for path in to_review:
            try:
                content = path.read_text(encoding="utf-8")
                meta, body = obsidian_writer._parse_frontmatter(content)
                if not meta:
                    continue
                notes_with_content.append({
                    "title": meta.get("title", path.stem),
                    "category": meta.get("category", ""),
                    "tags": meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
                    "up": meta.get("up", ""),
                    "body": body,
                })
            except Exception:
                continue

        if not notes_with_content:
            return {"status": "no_content", "message": "Could not read any note contents"}

        total = len(note_files)
        batch_info = {
            "total": total,
            "batch_start": 1,
            "batch_end": len(notes_with_content),
            "is_first": True,
            "is_last": len(notes_with_content) >= total,
        }
        review_text = ai_summary.review_notes_batch(notes_with_content, batch_info)

        vault = get_vault_path()
        report_dir = vault / "B站笔记" / "自查报告"
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"review_{timestamp}.md"

        report_content = f"---\ntitle: \"自查报告 {timestamp}\"\ndate: {datetime.now().strftime('%Y-%m-%d')}\ntype: review\n---\n\n# 自查报告\n\n> 审查笔记数: {len(notes_with_content)} | 模式: {mode}\n\n{review_text}\n"
        report_path.write_text(report_content, encoding="utf-8")

        return {
            "status": "completed",
            "reviewed_count": len(notes_with_content),
            "report_path": str(report_path),
            "review": review_text[:2000],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Review failed: {str(e)}")


@router.get("/review/pending")
async def list_pending_claims():
    """Get pending claims joined with content title/category."""
    db = get_db()
    rows = db.execute(
        """SELECT pc.*, c.title as content_title, c.category, c.creator_id,
               cr.name as creator_name
        FROM pending_claims pc
        LEFT JOIN contents c ON pc.content_id = c.id
        LEFT JOIN creators cr ON c.creator_id = cr.id
        WHERE pc.status = 'pending'
        ORDER BY pc.created_at DESC""",
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/review/resolve")
async def resolve_claim(data: dict):
    """Resolve a pending claim."""
    claim_id = data.get("claim_id")
    action = data.get("action", "confirm")
    correction = data.get("correction", "")
    if not claim_id:
        raise HTTPException(status_code=400, detail="claim_id is required")

    db = get_db()
    existing = db.execute(
        "SELECT * FROM pending_claims WHERE id = ?", (claim_id,)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

    status_map = {"confirm": "confirmed", "correct": "corrected", "remove": "removed"}
    new_status = status_map.get(action, "confirmed")

    db.execute(
        "UPDATE pending_claims SET status=?, correction=? WHERE id=?",
        (new_status, correction, claim_id),
    )
    db.commit()
    return {"status": "resolved", "claim_id": claim_id, "claim_status": new_status}


@router.get("/review/status")
async def review_status():
    """Return review state summary."""
    db = get_db()
    pending = db.execute(
        "SELECT COUNT(*) FROM pending_claims WHERE status='pending'"
    ).fetchone()[0]
    resolved = db.execute(
        "SELECT COUNT(*) FROM pending_claims WHERE status!='pending'"
    ).fetchone()[0]
    reviewed = db.execute(
        "SELECT COUNT(*) FROM review_state WHERE review_status='reviewed'"
    ).fetchone()[0]
    return {
        "notes_reviewed": reviewed,
        "pending_claims": pending,
        "resolved_claims": resolved,
        "total_claims": pending + resolved,
    }
