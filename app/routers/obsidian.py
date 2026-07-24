"""Obsidian note management endpoints."""
from fastapi import APIRouter, Query, HTTPException
from ..services import obsidian_writer

router = APIRouter()


@router.get("/notes")
async def list_notes():
    """List all notes in the Obsidian vault."""
    try:
        files = obsidian_writer._iter_note_files()
        notes = []
        for path in files:
            meta = obsidian_writer._read_note_metadata(path)
            if meta:
                notes.append(meta)
        return {"notes": notes, "count": len(notes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list notes: {str(e)}")


@router.get("/notes/{category}")
async def list_notes_by_category(category: str):
    """List notes in a specific category."""
    try:
        all_notes = []
        for path in obsidian_writer._iter_note_files():
            meta = obsidian_writer._read_note_metadata(path)
            if meta and meta.get("category", "") == category:
                all_notes.append(meta)
        return {"category": category, "notes": all_notes, "count": len(all_notes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notes/moc")
async def regenerate_mocs():
    """Regenerate all MOCs."""
    try:
        result = obsidian_writer.generate_all_mocs()
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notes/search")
async def search_notes(q: str = Query(...)):
    """Search notes by keyword in title and tags."""
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Search query 'q' is required")
    try:
        all_notes = []
        for path in obsidian_writer._iter_note_files():
            meta = obsidian_writer._read_note_metadata(path)
            if meta:
                all_notes.append(meta)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    query_lower = q.lower().strip()
    results = []
    for note in all_notes:
        title = note.get("title", "")
        tags = note.get("tags", [])
        title_match = query_lower in title.lower() if title else False
        tag_match = any(query_lower in str(t).lower() for t in tags) if tags else False
        if title_match or tag_match:
            results.append(note)
    return {"query": q, "results": results, "count": len(results)}
