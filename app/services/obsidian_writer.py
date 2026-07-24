"""
Obsidian note writing service.

Persists curated video notes into an Obsidian Vault as Markdown files with
YAML frontmatter, saves keyframe images as attachments, maintains per-domain
MOC (Map of Content) indexes, and provides related-note discovery via tag
overlap.
"""

from __future__ import annotations

import re
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from ..config import get_vault_path, CACHE_DIR
from .classifier import extract_knowledge_tags


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────
BILI_NOTES_DIR = Path("B站笔记")
MOC_DIR = BILI_NOTES_DIR / "MOC"
ATTACHMENTS_DIR = Path("attachments")
SKIP_DIRS = {"MOC", "自查报告"}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _vault_root() -> Path:
    """Return the vault root as a Path (resolved)."""
    vp = get_vault_path()
    if isinstance(vp, str):
        return Path(vp)
    return Path(vp)


def _notes_root() -> Path:
    return _vault_root() / BILI_NOTES_DIR


def _moc_root() -> Path:
    return _vault_root() / MOC_DIR


def _attachments_root() -> Path:
    return _vault_root() / ATTACHMENTS_DIR


def _sanitize_filename(name: str, max_len: int = 80) -> str:
    """Sanitize a title for use as a filesystem filename."""
    # Remove characters that are problematic on common filesystems.
    safe = re.sub(r'[\\/:*?"<>|\n\r\t]', "", name)
    safe = re.sub(r"\s+", " ", safe).strip()
    if len(safe) > max_len:
        safe = safe[:max_len].rstrip()
    return safe or "untitled"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Parse YAML frontmatter from markdown text.
    Supports both inline `tags: [a, b]` and multi-line `tags:\\n  - a\\n  - b` formats.
    Returns (metadata_dict, body_text).
    """
    meta: dict = {}
    if not text.startswith("---"):
        return meta, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return meta, text

    fm_block = parts[1]
    body = parts[2]
    fm_lines = fm_block.splitlines()

    i = 0
    while i < len(fm_lines):
        line = fm_lines[i].strip()
        if not line or line.startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()

        if not val:
            # Could be multi-line YAML list — check following lines
            list_items = []
            j = i + 1
            while j < len(fm_lines):
                next_line = fm_lines[j].strip()
                if next_line.startswith("- "):
                    item_val = next_line[2:].strip().strip("\"'")
                    list_items.append(item_val)
                    j += 1
                elif next_line.startswith("-"):
                    item_val = next_line[1:].strip().strip("\"'")
                    list_items.append(item_val)
                    j += 1
                else:
                    break
            if list_items:
                meta[key] = list_items
                i = j
                continue
            meta[key] = ""
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if inner:
                meta[key] = [x.strip().strip("'\"") for x in inner.split(",")]
            else:
                meta[key] = []
        else:
            if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
                val = val[1:-1]
            meta[key] = val
        i += 1

    return meta, body


def _read_note_metadata(path: Path) -> dict | None:
    """Read frontmatter metadata from a note file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    meta, _ = _parse_frontmatter(text)
    if not meta:
        return None

    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    return {
        "title": meta.get("title", path.stem),
        "category": meta.get("category", ""),
        "sub_category": meta.get("sub_category", ""),
        "sub_category_display": meta.get("sub_category", ""),
        "up": meta.get("up", ""),
        "bvid": meta.get("bvid", ""),
        "tags": tags,
        "date": meta.get("date", ""),
        "path": str(path),
    }


def _iter_note_files() -> list[Path]:
    """Return all .md note files under B站笔记/, skipping MOC and 自查报告."""
    root = _notes_root()
    if not root.exists():
        return []

    notes: list[Path] = []
    for p in root.rglob("*.md"):
        # Skip files inside SKIP_DIRS directories.
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        notes.append(p)
    return notes


# ──────────────────────────────────────────────────────────────────────────────
# 8. Duration formatting
# ──────────────────────────────────────────────────────────────────────────────
def format_duration(sec: int) -> str:
    """Format seconds into a human-readable string like ``1:02:03`` or ``3:45``."""
    if sec is None or sec < 0:
        return "00:00"
    sec = int(sec)
    hours = sec // 3600
    minutes = (sec % 3600) // 60
    seconds = sec % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


# ──────────────────────────────────────────────────────────────────────────────
# 7. Note path computation
# ──────────────────────────────────────────────────────────────────────────────
def get_note_path(category: str, bvid: str, title: str) -> Path:
    """
    Compute a safe note path:

        vault/B站笔记/{category}/{bvid}_{sanitized_title}.md

    The ``category`` component is also sanitised.  Parent directories are NOT
    created here — callers that write to the path should ``mkdir(parents=True)``.
    """
    safe_cat = _sanitize_filename(category, max_len=60) or "未分类"
    safe_title = _sanitize_filename(title)
    filename = f"{bvid}_{safe_title}.md"
    return _notes_root() / safe_cat / filename


# ──────────────────────────────────────────────────────────────────────────────
# 1. save_note
# ──────────────────────────────────────────────────────────────────────────────
def _copy_keyframes(content_data: dict, note_dir: Path, bvid: str) -> list[str]:
    """
    Copy keyframe images from cache into vault/attachments.

    Looks for a list of source paths in ``content_data["cache_frames"]``.
    If absent, tries to discover frames from a cache directory using the bvid.

    Returns a list of attachment filenames (basenames) that were saved.
    """
    saved: list[str] = []
    attachments_dir = _attachments_root()
    attachments_dir.mkdir(parents=True, exist_ok=True)

    source_frames: list[str | Path] = []

    # Explicit list passed by caller.
    cache_frames = content_data.get("cache_frames")
    if cache_frames:
        source_frames = list(cache_frames)

    # Fallback: look for a cache directory derived from bvid.
    if not source_frames:
        bvid_val = content_data.get("bvid", bvid)
        if bvid_val:
            try:
                cache_base = CACHE_DIR if isinstance(CACHE_DIR, Path) else Path(CACHE_DIR)
            except Exception:
                cache_base = Path("/tmp") / "bili_cache"

            frame_dir = cache_base / bvid_val / "frames"
            if frame_dir.is_dir():
                source_frames = sorted(frame_dir.glob("*.jpg")) + sorted(frame_dir.glob("*.png"))

    for src in source_frames:
        src_path = Path(src)
        if not src_path.is_file():
            continue
        # Hash the filename to avoid collisions while keeping deterministic names.
        ext = src_path.suffix or ".jpg"
        hashed = hashlib.md5(f"{bvid}:{src_path.name}".encode()).hexdigest()[:12]
        dest_name = f"{bvid}_{hashed}{ext}"
        dest_path = attachments_dir / dest_name
        try:
            shutil.copy2(src_path, dest_path)
            saved.append(dest_name)
        except (OSError, shutil.SameFileError):
            continue

    return saved


def _build_frontmatter(
    content_data: dict,
    category: str,
    sub_category: str,
    tags: list[str],
    used_frames: bool,
    frame_decision: dict,
) -> str:
    """Build YAML frontmatter block."""
    now = datetime.now().strftime("%Y-%m-%d")
    duration_str = format_duration(content_data.get("duration", 0))

    lines: list[str] = ["---"]
    lines.append(f"title: \"{content_data.get('title', '')}\"")
    lines.append(f"category: \"{category}\"")
    lines.append(f"sub_category: \"{sub_category}\"")
    lines.append(f"date: {now}")
    lines.append(f"up: \"{content_data.get('up_name', '')}\"")
    lines.append(f"up_uid: \"{content_data.get('up_uid', '')}\"")
    lines.append(f"bvid: {content_data.get('bvid', '')}")
    lines.append(f"aid: {content_data.get('aid', '')}")
    lines.append(f"cid: {content_data.get('cid', '')}")
    lines.append(f"duration: {duration_str}")
    lines.append(f"url: {content_data.get('url', '')}")
    lines.append(f"cover: {content_data.get('cover', '')}")
    lines.append(f"pubdate: {content_data.get('pubdate', '')}")
    lines.append(f"used_frames: {str(used_frames).lower()}")

    if frame_decision:
        lines.append(f"frame_decision: \"{frame_decision.get('decision', '')}\"")

    if tags:
        tag_str = ", ".join(tags)
        lines.append(f"tags: [{tag_str}]")
    else:
        lines.append("tags: []")

    lines.append("---")
    return "\n".join(lines)


def _build_wikilinks(tags: list[str]) -> str:
    """Build Obsidian wikilinks for related knowledge entities."""
    if not tags:
        return ""
    links = [f"[[{t}]]" for t in tags]
    return " ".join(links)


def save_note(
    content_data: dict,
    summary: str,
    category: str,
    sub_category: str,
    frame_analysis: str,
    frame_decision: dict,
    structured_info: str,
    used_frames: bool,
) -> str:
    """
    Save a Markdown note to the Obsidian Vault.

    ``content_data`` keys: bvid, title, up_name, up_uid, aid, cid, duration,
    url, cover, pubdate — and optionally ``cache_frames`` (list of image paths).

    The note is written to ``vault/B站笔记/{category}/{bvid}_{title}.md`` with:
      • YAML frontmatter (all metadata + knowledge tags)
      • Summary section
      • Related knowledge links (Obsidian wikilinks)
      • Frame analysis section (if available)
      • Structured info section (if available)

    Keyframe images are copied to ``vault/attachments/`` and embedded in the note.

    After saving, the per-domain MOC is updated.

    Returns the note path string.
    """
    vault = _vault_root()
    bvid = content_data.get("bvid", "")
    title = content_data.get("title", "untitled")

    note_path = get_note_path(category, bvid, title)
    note_path.parent.mkdir(parents=True, exist_ok=True)

    # Save keyframes and build image embeds.
    saved_frames = _copy_keyframes(content_data, note_path.parent, bvid)
    image_embeds = "\n".join(f"![[{fname}]]" for fname in saved_frames)

    # Extract knowledge tags for frontmatter + related links.
    tags = extract_knowledge_tags(title, summary)

    # Build frontmatter.
    frontmatter = _build_frontmatter(content_data, category, sub_category, tags, used_frames, frame_decision)

    # Build body.
    body_parts: list[str] = [frontmatter, ""]

    # Title heading
    body_parts.append(f"# {title}")
    body_parts.append("")

    # Metadata table
    body_parts.append("## 📌 基本信息")
    body_parts.append("")
    body_parts.append(f"- **UP主**: {content_data.get('up_name', '')}")
    body_parts.append(f"- **时长**: {format_duration(content_data.get('duration', 0))}")
    body_parts.append(f"- **发布时间**: {content_data.get('pubdate', '')}")
    body_parts.append(f"- **链接**: {content_data.get('url', '')}")
    if sub_category:
        body_parts.append(f"- **子分类**: {sub_category}")
    body_parts.append("")

    # Summary
    body_parts.append("## 📝 摘要")
    body_parts.append("")
    body_parts.append(summary or "")
    body_parts.append("")

    # Related knowledge links
    wikilinks = _build_wikilinks(tags)
    if wikilinks:
        body_parts.append("## 🔗 相关知识")
        body_parts.append("")
        body_parts.append(wikilinks)
        body_parts.append("")

    # Frame analysis
    if frame_analysis:
        body_parts.append("## 🎬 帧分析")
        body_parts.append("")
        body_parts.append(frame_analysis)
        body_parts.append("")

    # Frame images
    if image_embeds:
        body_parts.append("### 关键帧")
        body_parts.append("")
        body_parts.append(image_embeds)
        body_parts.append("")

    # Frame decision
    if frame_decision:
        body_parts.append("### 帧决策")
        body_parts.append("")
        decision_text = frame_decision.get("decision", "")
        if decision_text:
            body_parts.append(f"**决策**: {decision_text}")
        reason = frame_decision.get("reason", "")
        if reason:
            body_parts.append(f"**原因**: {reason}")
        body_parts.append("")

    # Structured info
    if structured_info:
        body_parts.append("## 📋 结构化信息")
        body_parts.append("")
        body_parts.append(structured_info)
        body_parts.append("")

    note_text = "\n".join(body_parts)
    note_path.write_text(note_text, encoding="utf-8")

    # Update MOC.
    try:
        update_moc(category, bvid, title, sub_category)
    except Exception:
        pass

    return str(note_path)


# ──────────────────────────────────────────────────────────────────────────────
# 2 & 6. MOC management
# ──────────────────────────────────────────────────────────────────────────────
def update_moc(category: str, bvid: str, title: str, sub_category: str = "") -> None:
    """
    Maintain a MOC (Map of Content) index file per domain.

    Scans all notes in ``vault/B站笔记/{category}/``, groups them by
    sub_category, and regenerates ``vault/B站笔记/MOC/{category}.md``.
    """
    moc_root = _moc_root()
    moc_root.mkdir(parents=True, exist_ok=True)

    category_dir = _notes_root() / _sanitize_filename(category, max_len=60)
    if not category_dir.is_dir():
        return

    notes: list[dict] = []
    for md_file in sorted(category_dir.glob("*.md")):
        meta = _read_note_metadata(md_file)
        if meta is None:
            # Fallback: derive from filename.
            parts = md_file.stem.split("_", 1)
            notes.append({
                "title": parts[1] if len(parts) > 1 else md_file.stem,
                "bvid": parts[0] if len(parts) > 0 else "",
                "sub_category": "",
            })
        else:
            notes.append(meta)

    # Group by sub_category.
    grouped: dict[str, list[dict]] = defaultdict(list)
    for note in notes:
        sub = note.get("sub_category", "") or ""
        grouped[sub].append(note)

    # Build MOC content.
    moc_path = moc_root / f"{_sanitize_filename(category, max_len=60)}.md"
    lines: list[str] = [
        "---",
        f'category: "{category}"',
        f"date: {datetime.now().strftime('%Y-%m-%d')}",
        "---",
        "",
        f"# {category} · MOC",
        "",
        f"> 共 {len(notes)} 篇笔记",
        "",
    ]

    for sub_cat in sorted(grouped.keys()):
        sub_notes = grouped[sub_cat]
        header = sub_cat if sub_cat else "其他"
        lines.append(f"## {header} ({len(sub_notes)})")
        lines.append("")
        for note in sub_notes:
            note_title = note.get("title", "")
            note_bvid = note.get("bvid", "")
            # Obsidian wikilink by filename (without extension).
            safe_title = _sanitize_filename(note_title)
            link_target = f"{note_bvid}_{safe_title}" if note_bvid else safe_title
            lines.append(f"- [[{link_target}|{note_title}]]")
        lines.append("")

    moc_path.write_text("\n".join(lines), encoding="utf-8")


def generate_all_mocs() -> dict:
    """
    Regenerate all MOC indexes across every category directory.

    Returns ``{"mocs_generated": int, "count": int}`` where ``count`` is the
    total number of notes indexed.
    """
    notes_root = _notes_root()
    categories: set[str] = set()

    if notes_root.is_dir():
        for entry in notes_root.iterdir():
            if entry.is_dir() and entry.name not in SKIP_DIRS:
                categories.add(entry.name)

    mocs_generated = 0
    total_count = 0

    for cat in categories:
        cat_dir = notes_root / cat
        note_files = [f for f in cat_dir.glob("*.md") if f.is_file()]
        if not note_files:
            continue
        # Reuse update_moc which scans and regenerates.
        # We pass a dummy bvid/title since it re-scans the whole directory.
        update_moc(cat, "", "", "")
        mocs_generated += 1
        total_count += len(note_files)

    return {"mocs_generated": mocs_generated, "count": total_count}


# ──────────────────────────────────────────────────────────────────────────────
# 3. Related note discovery
# ──────────────────────────────────────────────────────────────────────────────
def find_related_notes(title: str, summary: str, category: str, max_results: int = 5) -> list[dict]:
    """
    Find related notes by knowledge-tag overlap.

    Scans ``vault/B站笔记/**/*.md`` (skipping MOC and 自查报告), extracts tags
    from frontmatter, computes Jaccard-style overlap with the current note's
    knowledge tags (extracted from title+summary), and returns the top matches.

    Each result dict: ``{"title": str, "relation": str, "score": float}``.
    ``relation`` is a human label like ``"标签重叠 (3个共同标签)"``.
    """
    current_tags = set(extract_knowledge_tags(title, summary))
    results: list[dict] = []

    for note_path in _iter_note_files():
        meta = _read_note_metadata(note_path)
        if meta is None:
            continue

        note_tags = set(meta.get("tags", []))
        if not note_tags:
            continue

        overlap = current_tags & note_tags
        if not overlap:
            continue

        # Score: overlap size relative to the smaller tag set.
        min_size = min(len(current_tags), len(note_tags)) or 1
        score = len(overlap) / min_size

        results.append({
            "title": meta.get("title", note_path.stem),
            "relation": f"标签重叠 ({len(overlap)}个共同标签)",
            "score": round(score, 3),
        })

    # Sort by score descending then title.
    results.sort(key=lambda x: (-x["score"], x["title"]))
    return results[:max_results]


# ──────────────────────────────────────────────────────────────────────────────
# 4 & 5. Note listing / metadata
# ──────────────────────────────────────────────────────────────────────────────
def read_all_notes_metadata() -> list[dict]:
    """
    Read all notes' frontmatter metadata from the vault.

    Each dict contains: title, category, sub_category, up, bvid, tags, date.
    Skips MOC and 自查报告 directories.
    """
    notes: list[dict] = []
    for note_path in _iter_note_files():
        meta = _read_note_metadata(note_path)
        if meta is None:
            continue
        # Clean up for external consumption.
        notes.append({
            "title": meta.get("title", ""),
            "category": meta.get("category", ""),
            "sub_category": meta.get("sub_category", ""),
            "sub_category_display": meta.get("sub_category", ""),
            "up": meta.get("up", ""),
            "bvid": meta.get("bvid", ""),
            "tags": meta.get("tags", []),
            "date": meta.get("date", ""),
        })
    return notes


def list_notes() -> list[dict]:
    """
    List all notes with metadata for API response.

    Same data as ``read_all_notes_metadata()`` but augmented with the note's
    relative path for convenience.
    """
    notes: list[dict] = []
    vault = _vault_root()
    for note_path in _iter_note_files():
        meta = _read_note_metadata(note_path)
        if meta is None:
            continue
        try:
            rel_path = str(note_path.relative_to(vault))
        except ValueError:
            rel_path = str(note_path)
        notes.append({
            "title": meta.get("title", ""),
            "category": meta.get("category", ""),
            "sub_category": meta.get("sub_category", ""),
            "sub_category_display": meta.get("sub_category", ""),
            "up": meta.get("up", ""),
            "bvid": meta.get("bvid", ""),
            "tags": meta.get("tags", []),
            "date": meta.get("date", ""),
            "path": rel_path,
        })
    return notes
