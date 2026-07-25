# content-curator/app/services/pipeline.py
"""Processing pipeline — state machine for content processing.
pending → fetching → transcribing → cleaning → classifying → extracting → done/failed
"""
import hashlib
import logging
from datetime import datetime
from ..database import get_db
from ..config import get_setting, get_setting_json
from . import bilibili, vision, ai_summary, classifier, obsidian_writer

logger = logging.getLogger(__name__)

PIPELINE_STAGES = [
    "fetching", "transcribing", "cleaning", "classifying", "extracting"
]


def _update_status(content_id: int, status: str, **extra):
    """Update content status in DB with optional extra fields."""
    conn = get_db()
    fields = {"status": status}
    fields.update(extra)
    if status == "done":
        fields["processed_at"] = datetime.now().isoformat()
    elif status == "failed":
        fields["retry_count"] = (fields.get("retry_count", 0) or 0) + 1

    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [content_id]
    conn.execute(f"UPDATE contents SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()
    logger.info(f"Content {content_id} → {status}")


def _get_content(content_id: int) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM contents WHERE id=?", (content_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def _record_task(content_id: int, task_type: str, status: str, result: str = "", error: str = ""):
    conn = get_db()
    conn.execute(
        "INSERT INTO task_queue(content_id, task_type, status, started_at, finished_at, result, error) "
        "VALUES(?, ?, ?, datetime('now'), datetime('now'), ?, ?)",
        (content_id, task_type, status, result, error)
    )
    conn.commit()
    conn.close()


async def process_content(content_id: int) -> dict:
    """Main processing pipeline for a single content item."""
    content = _get_content(content_id)
    if not content:
        return {"success": False, "error": "content not found"}

    bvid = content.get("bvid", "")
    platform = content.get("platform", "bilibili")
    ad_filter_prompt = get_setting("ad_filter_prompt",
        "识别并删除赞助广告、推广、带货、优惠码、关注点赞求三连等无关信息。只保留有价值的知识性内容。")

    try:
        # ── Stage 1: fetching ──
        _update_status(content_id, "fetching")

        if platform == "bilibili":
            info = bilibili.get_video_info(bvid)
            if "error" in info:
                raise RuntimeError(f"fetch failed: {info['error']}")

            # Update content with fetched metadata
            _update_status(content_id, "fetching",
                title=info["title"], duration=info["duration"],
                cover=info["cover"], url=f"https://www.bilibili.com/video/{bvid}")

            content.update(info)
            content["title"] = info["title"]
            content["duration"] = info["duration"]

        elif platform == "wechat":
            from . import wechat
            article = wechat.fetch_article_text(content.get("url", ""))
            if not article:
                raise RuntimeError("wechat article fetch failed")
            content["title"] = article.get("title", content.get("title", ""))
            content["wechat_text"] = article.get("text", article)
            content["word_count"] = len(content["wechat_text"])

        _record_task(content_id, "fetch", "done", f"title={content.get('title','')}")

        # ── Stage 2: transcribing ──
        _update_status(content_id, "transcribing")

        subtitle_text = ""
        danmaku_text = ""

        if platform == "bilibili":
            # Try AI subtitle first (best quality)
            sub = bilibili.get_subtitle(str(content.get("aid", "")), str(content.get("cid", "")))
            if sub.get("has_subtitle"):
                subtitle_text = sub.get("text", "")
            else:
                # No subtitle → try Whisper
                from . import transcribe
                whisper_result = transcribe.transcribe_audio(bvid)
                subtitle_text = whisper_result.get("text", "")

            # Always get danmaku as supplementary
            danmaku_text = bilibili.get_danmaku(bvid)

        elif platform == "wechat":
            subtitle_text = content.get("wechat_text", "")

        _record_task(content_id, "transcribe", "done",
            f"subtitle={len(subtitle_text)}chars, danmaku={len(danmaku_text)}chars")

        # ── Stage 3: cleaning (AI ad removal) ──
        _update_status(content_id, "cleaning")

        cleaned_text = ai_summary.clean_content(subtitle_text, ad_filter_prompt)
        if not cleaned_text:
            cleaned_text = subtitle_text  # fallback to raw if cleaning fails

        _record_task(content_id, "clean", "done", f"cleaned={len(cleaned_text)}chars")

        # ── Stage 4: classifying ──
        _update_status(content_id, "classifying")

        category = classifier.classify_domain(content.get("title", ""), cleaned_text)
        sub_category = classifier.extract_sub_category(content.get("title", ""), cleaned_text)

        _update_status(content_id, "classifying",
            category=category, sub_category=sub_category)
        _record_task(content_id, "classify", "done", f"category={category}/{sub_category}")

        # ── Stage 5: extracting (keyframes + vision + summary) ──
        _update_status(content_id, "extracting")

        # Smart frame decision
        frame_decision = vision.should_use_frames(cleaned_text, content.get("title", ""))
        used_frames = frame_decision["should_use_frames"]
        frame_analysis = ""

        # Extract structured info from text
        info_detection = frame_decision.get("info_detection", {})
        structured_info = vision.extract_structured_info_text(info_detection)

        # Extract keyframes if needed
        if used_frames and platform == "bilibili":
            frames_resp = vision.extract_frames(
                bvid, str(content.get("aid", "")), str(content.get("cid", "")),
                content.get("duration", 0), count=6
            )
            if frames_resp.get("success") and frames_resp.get("frames"):
                frame_analysis = vision.analyze_frames(frames_resp["frames"], content.get("title", ""))

        # Generate AI summary
        summary = ai_summary.generate_summary(
            title=content.get("title", ""),
            up_name=content.get("up_name", ""),
            duration=content.get("duration", 0),
            subtitle=cleaned_text,
            danmaku=danmaku_text[:500],
            structured_info=structured_info,
            frame_analysis=frame_analysis,
            ad_filter_prompt=ad_filter_prompt
        )

        # Save Obsidian note
        note_path = obsidian_writer.save_note(
            content_data={
                "bvid": bvid,
                "title": content.get("title", ""),
                "up_name": content.get("up_name", ""),
                "up_uid": content.get("up_mid", content.get("up_uid", "")),
                "aid": content.get("aid", ""),
                "cid": content.get("cid", ""),
                "duration": content.get("duration", 0),
                "url": content.get("url", f"https://www.bilibili.com/video/{bvid}"),
                "cover": content.get("cover", ""),
                "pubdate": content.get("pubdate", 0),
                "platform": platform,
                "content_type": content.get("content_type", ""),
                "manual": not bool(content.get("creator_id")),
            },
            summary=summary,
            category=category,
            sub_category=sub_category,
            frame_analysis=frame_analysis,
            frame_decision=frame_decision,
            structured_info=structured_info,
            used_frames=used_frames
        )

        # Compute content hash for incremental review
        content_hash = hashlib.md5((summary + cleaned_text).encode()).hexdigest()[:12]

        # Extract and store pending claims
        claims = ai_summary.extract_claims(summary)
        if claims:
            conn = get_db()
            for c in claims:
                conn.execute(
                    "INSERT INTO pending_claims(content_id, claim, claim_type) VALUES(?, ?, ?)",
                    (content_id, c.get("claim", ""), c.get("type", "待验证"))
                )
            conn.commit()
            conn.close()

        # ── Done ──
        _update_status(content_id, "done",
            note_path=note_path,
            ai_summary=summary,
            structured_info=structured_info,
            used_frames=int(used_frames),
            frame_decision=str(frame_decision),
            content_hash=content_hash)

        # Update review state
        conn = get_db()
        conn.execute(
            "INSERT INTO review_state(content_id, last_hash, last_reviewed, review_status) "
            "VALUES(?, ?, datetime('now'), 'pending') "
            "ON CONFLICT(content_id) DO UPDATE SET last_hash=excluded.last_hash, review_status='pending'",
            (content_id, content_hash)
        )
        conn.commit()
        conn.close()

        _record_task(content_id, "process", "done", f"note={note_path}")

        return {
            "success": True,
            "content_id": content_id,
            "bvid": bvid,
            "title": content.get("title", ""),
            "category": category,
            "sub_category": sub_category,
            "used_frames": used_frames,
            "note_path": note_path,
            "claims_count": len(claims)
        }

    except Exception as e:
        error_msg = str(e)
        _update_status(content_id, "failed", error_msg=error_msg)
        _record_task(content_id, "process", "failed", error=error_msg)
        logger.exception(f"Pipeline failed for content {content_id}")
        return {"success": False, "content_id": content_id, "error": error_msg}


async def retry_content(content_id: int) -> dict:
    """Retry a failed content item — resets status to pending and reprocesses."""
    _update_status(content_id, "pending", error_msg=None)
    return await process_content(content_id)
