"""Bilibili API service module.

Migrated & optimised from bili-helper/app.py for the content-curator FastAPI app.
Provides video metadata, AI subtitles, danmaku extraction, UP主 video listing,
and collection/合集 discovery via the B站 REST + player APIs, yt-dlp subprocess,
and a host-side helper proxy (HELPER_SERVER).
"""
from __future__ import annotations

import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from ..config import HEADERS, get_sessdata, COOKIES_FILE, HELPER_SERVER, CACHE_DIR

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
_BILI_VIEW_API = "https://api.bilibili.com/x/web-interface/view"
_BILI_PLAYER_API = "https://api.bilibili.com/x/player/wbi/v2"
_BILI_SEASONS_API = "https://api.bilibili.com/x/polymer/web-space/seasons_list"
_BILI_SPACE_API = "https://api.bilibili.com/x/space/arc/search"

_DEFAULT_TIMEOUT = 15.0
_DANMAKU_TEXT_LIMIT = 500
_YTDLP_TIMEOUT = 180
_HELPER_TIMEOUT = 120.0


# ── Auth / cookie helpers ─────────────────────────────────────────────────────
def _auth_headers(extra: dict | None = None) -> dict:
    """Build request headers with User-Agent and SESSDATA cookie."""
    hdrs = dict(HEADERS)
    sessdata = get_sessdata()
    if sessdata:
        hdrs["Cookie"] = f"SESSDATA={sessdata}"
    if extra:
        hdrs.update(extra)
    return hdrs


# ── Re-export get_sessdata for ergonomic `from .bilibili import get_sessdata` ──
def get_sessdata() -> str:  # noqa: F811 — intentional re-export
    """Re-export of config.get_sessdata (read SESSDATA from DB/cookies file)."""
    from ..config import get_sessdata as _gs
    return _gs()


# ── 1. Video info ────────────────────────────────────────────────────────────
def get_video_info(bvid: str) -> dict:
    """Fetch video details via B站 REST API.

    Returns dict with: bvid, aid, cid, title, desc, duration,
    up_name, up_mid, cover, pubdate, view, danmaku.
    On failure returns {"error": "..."}.
    """
    try:
        r = httpx.get(
            f"{_BILI_VIEW_API}?bvid={bvid}",
            headers=_auth_headers(),
            timeout=_DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            return {"error": j.get("message", "unknown")}
        d = j["data"]
        return {
            "bvid": bvid,
            "aid": d["aid"],
            "cid": d["cid"],
            "title": d["title"],
            "desc": d.get("desc", ""),
            "duration": d.get("duration", 0),
            "up_name": d["owner"]["name"],
            "up_mid": d["owner"]["mid"],
            "cover": d.get("pic", ""),
            "pubdate": d.get("pubdate", 0),
            "view": d["stat"]["view"],
            "danmaku": d["stat"]["danmaku"],
        }
    except Exception as e:
        logger.exception("get_video_info failed for %s", bvid)
        return {"error": str(e)}


# ── 2. Subtitles (AI-generated) ──────────────────────────────────────────────
def get_subtitle(aid: str, cid: str) -> dict:
    """Get AI subtitles via the player wbi/v2 API.

    Parses subtitle_url, downloads the JSON subtitle file, and extracts text.
    Returns {has_subtitle, line_count, text, lines} or {has_subtitle: False, ...}.
    """
    sessdata = get_sessdata()
    try:
        r = httpx.get(
            f"{_BILI_PLAYER_API}?aid={aid}&cid={cid}",
            headers=_auth_headers(),
            timeout=_DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            return {"has_subtitle": False, "error": j.get("message", "")}

        subs = j.get("data", {}).get("subtitle", {}).get("subtitles", [])
        if not subs:
            return {"has_subtitle": False}

        sub_url = "https:" + subs[0]["subtitle_url"]
        r2 = httpx.get(sub_url, timeout=_DEFAULT_TIMEOUT)
        r2.raise_for_status()
        sj = r2.json()
        body = sj.get("body", [])
        if not body:
            return {"has_subtitle": False}

        text = " ".join(item["content"] for item in body if "content" in item)
        lines = [
            {"from": b.get("from", 0), "content": b.get("content", "")}
            for b in body
        ]
        return {
            "has_subtitle": True,
            "line_count": len(body),
            "text": text,
            "lines": lines,
        }
    except Exception as e:
        logger.exception("get_subtitle failed for aid=%s cid=%s", aid, cid)
        return {"has_subtitle": False, "error": str(e)}


# ── 3. Danmaku via yt-dlp ────────────────────────────────────────────────────
def get_danmaku(bvid: str) -> str:
    """Get danmaku (弹幕) text via yt-dlp XML subtitle extraction.

    Uses `--write-subs --sub-format xml --sub-lang danmaku --skip-download`,
    reads the resulting .xml file, and parses <d> elements for text content.
    Truncates to 500 characters. Returns plain text (empty on failure).
    """
    cache_dir = Path(CACHE_DIR) / bvid
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(cache_dir / "%(id)s")

    cmd = [
        "yt-dlp",
        "--write-subs",
        "--sub-format", "xml",
        "--sub-lang", "danmaku",
        "--skip-download",
        "--cookies", COOKIES_FILE,
        "--no-warnings",
        "--no-check-certificates",
        "-o", out_tmpl,
        f"https://www.bilibili.com/video/{bvid}",
    ]

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_YTDLP_TIMEOUT,
        )
    except Exception:
        logger.exception("get_danmaku yt-dlp failed for %s", bvid)
        return ""

    # Locate the .danmaku.xml file (yt-dlp names it <id>.danmaku.xml)
    xml_files = sorted(cache_dir.glob("*.danmaku.xml"))
    if not xml_files:
        xml_files = sorted(cache_dir.glob("*.xml"))
    if not xml_files:
        logger.warning("get_danmaku: no XML file produced for %s", bvid)
        return ""

    try:
        tree = ET.parse(xml_files[0])
        root = tree.getroot()
        texts = []
        total = 0
        for d_elem in root.iter("d"):
            content = (d_elem.text or "").strip()
            if not content:
                continue
            if total + len(content) + 1 > _DANMAKU_TEXT_LIMIT:
                # Truncate the last item to fit the budget
                remaining = _DANMAKU_TEXT_LIMIT - total
                if remaining > 0:
                    texts.append(content[:remaining])
                break
            texts.append(content)
            total += len(content) + 1

        # Cleanup
        for f in xml_files:
            try:
                f.unlink()
            except OSError:
                pass

        return " ".join(texts)
    except Exception:
        logger.exception("get_danmaku XML parse failed for %s", bvid)
        return ""


# ── 4. UP主 video list ───────────────────────────────────────────────────────
def _fetch_bvids_from_helper(uid: str) -> list[str]:
    """Fetch BV ids from the host-side helper server (yt-dlp proxy)."""
    try:
        r = httpx.get(
            f"{HELPER_SERVER}/bvids?uid={uid}",
            timeout=_HELPER_TIMEOUT,
        )
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            logger.warning("helper server error for uid=%s: %s", uid, j["error"])
            return []
        return [b for b in j.get("bvids", []) if b.startswith("BV")]
    except Exception:
        logger.exception("helper server fetch failed for uid=%s", uid)
        return []


def _fetch_bvids_via_ytdlp(uid: str, limit: int = 0) -> list[str]:
    """Fallback: fetch BV ids in-process via yt-dlp flat-playlist."""
    cmd = [
        "yt-dlp", "--flat-playlist", "--print", "%(id)s",
        "--cookies", COOKIES_FILE,
        "--no-warnings",
        "--no-playlist-reverse",
        "--no-check-certificates",
        "--extractor-args", "bilibili:api_version=2",
    ]
    if limit > 0:
        cmd += ["--playlist-end", str(limit)]
    else:
        cmd += ["--playlist-end", "10000"]
    cmd.append(f"https://space.bilibili.com/{uid}/video")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_YTDLP_TIMEOUT
        )
        return [
            line.strip()
            for line in result.stdout.strip().split("\n")
            if line.strip().startswith("BV")
        ]
    except Exception:
        logger.exception("yt-dlp flat-playlist failed for uid=%s", uid)
        return []


def _fetch_up_videos_via_api(uid: str, limit: int = 0) -> list[dict]:
    """Fetch full UP主 video list via B站 space arc/search API (paginated).

    Returns list of {bvid, title, date}.
    """
    videos: list[dict] = []
    page = 1
    page_size = 50
    ytdlp_limit = limit if limit > 0 else 10000

    while True:
        try:
            r = httpx.get(
                f"{_BILI_SPACE_API}?mid={uid}&ps={page_size}&pn={page}&order=pubdate",
                headers=_auth_headers(),
                timeout=_DEFAULT_TIMEOUT,
            )
            j = r.json()
            if j.get("code") != 0:
                break
            vlist = j.get("data", {}).get("list", {}).get("vlist", [])
            if not vlist:
                break
            for v in vlist:
                bvid = v.get("bvid", "")
                if not bvid:
                    continue
                created = v.get("created", 0)
                date_str = (
                    time.strftime("%Y%m%d", time.localtime(created))
                    if created
                    else ""
                )
                videos.append({
                    "bvid": bvid,
                    "title": v.get("title", ""),
                    "date": date_str,
                })
                if 0 < limit <= len(videos):
                    return videos
                time.sleep(0.5)  # rate limit between pages
            if len(vlist) < page_size:
                break
            page += 1
            if len(videos) >= ytdlp_limit:
                break
        except Exception:
            logger.exception("space arc/search failed page=%s uid=%s", page, uid)
            break

    return videos


def get_up_videos(uid: str, limit: int = 0) -> list[dict]:
    """Get UP主 video list.

    Strategy:
    1. Try helper server at HELPER_SERVER/bvids?uid= (host yt-dlp proxy).
    2. Fallback to in-process yt-dlp flat-playlist.
    3. For each BV id fetched via helper/yt-dlp, we only have the id — enrich
       with title+date via the B站 view API (best-effort, 0.5s rate limit).
       If the B站 space arc/search API is reachable directly, prefer it since
       it returns title+date in one call.

    Returns list of {"bvid", "title", "date"}.
    """
    # Prefer the direct B站 API first (returns titles & dates in one pass)
    api_videos = _fetch_up_videos_via_api(uid, limit=limit)
    if api_videos:
        return api_videos

    # Fallback 1: helper server
    bvids = _fetch_bvids_from_helper(uid)
    # Fallback 2: in-process yt-dlp
    if not bvids:
        bvids = _fetch_bvids_via_ytdlp(uid, limit=limit)

    if not bvids:
        return []

    # Enrich each BV id with title + date via view API (rate-limited)
    videos: list[dict] = []
    hdrs = _auth_headers({"Referer": f"https://space.bilibili.com/{uid}"})
    for i, bvid in enumerate(bvids):
        if 0 < limit <= i:
            break
        entry = {"bvid": bvid, "title": "", "date": ""}
        try:
            r = httpx.get(
                f"{_BILI_VIEW_API}?bvid={bvid}",
                headers=hdrs,
                timeout=_DEFAULT_TIMEOUT,
            )
            j = r.json()
            if j.get("code") == 0:
                d = j["data"]
                entry["title"] = d.get("title", "")
                pubdate = d.get("pubdate", 0)
                entry["date"] = (
                    time.strftime("%Y%m%d", time.localtime(pubdate))
                    if pubdate
                    else ""
                )
        except Exception:
            logger.debug("enrich failed for %s", bvid)
        videos.append(entry)
        if i < len(bvids) - 1:
            time.sleep(0.5)

    return videos


# ── 5. Full video list with info + processed marking ─────────────────────────
def get_all_videos_with_info(
    uid: str, processed_bvids: set | None = None
) -> dict:
    """Get UP主's full video list with titles/durations, marking processed ones.

    1. Fetch BV id list via helper server (preferred) or in-process yt-dlp.
    2. Concurrently (5 threads) fetch each video's info via the REST view API.
    3. Mark each as processed/unprocessed against `processed_bvids`.

    Returns {uid, total, processed_count, unprocessed_count, videos}.
    On total failure returns {"error": "..."}.
    """
    if processed_bvids is None:
        processed_bvids = set()

    # 1. Get BV id list
    bvids = _fetch_bvids_from_helper(uid)
    if not bvids:
        # Fallback: in-process yt-dlp with retry
        for attempt in range(2):
            bvids = _fetch_bvids_via_ytdlp(uid, limit=200)
            if bvids:
                break
            time.sleep(3)

    if not bvids:
        return {"error": "获取视频列表失败，可能B站风控，请稍后重试"}

    # 2. Concurrent info fetch
    hdrs = _auth_headers({"Referer": f"https://space.bilibili.com/{uid}"})

    def _fetch_one(bvid: str) -> dict:
        info = {
            "bvid": bvid,
            "title": "(获取失败)",
            "duration": 0,
            "pubdate": 0,
            "play": 0,
            "processed": bvid in processed_bvids,
        }
        try:
            r = httpx.get(
                f"{_BILI_VIEW_API}?bvid={bvid}",
                headers=hdrs,
                timeout=10,
            )
            j = r.json()
            if j.get("code") == 0:
                d = j["data"]
                info["title"] = d.get("title", "(无标题)")
                info["duration"] = d.get("duration", 0)
                info["pubdate"] = d.get("pubdate", 0)
                info["play"] = d.get("stat", {}).get("view", 0)
        except Exception:
            logger.debug("concurrent fetch_info failed for %s", bvid)
        return info

    videos: list[dict] = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, bvid): bvid for bvid in bvids}
        for fut in as_completed(futures):
            try:
                videos.append(fut.result())
            except Exception:
                # Shouldn't happen since _fetch_one swallows errors, but guard anyway
                bvid = futures[fut]
                videos.append({
                    "bvid": bvid,
                    "title": "(获取失败)",
                    "duration": 0,
                    "pubdate": 0,
                    "play": 0,
                    "processed": bvid in processed_bvids,
                })

    # Preserve original BV order from the listing
    order = {bvid: i for i, bvid in enumerate(bvids)}
    videos.sort(key=lambda v: order.get(v["bvid"], 0))

    unprocessed_count = sum(1 for v in videos if not v["processed"])

    return {
        "uid": uid,
        "total": len(videos),
        "processed_count": len(videos) - unprocessed_count,
        "unprocessed_count": unprocessed_count,
        "videos": videos,
    }


# ── 6. get_sessdata — re-exported (defined above via config import) ──────────
# The `get_sessdata` symbol defined earlier in this module re-exports
# config.get_sessdata, satisfying `from .bilibili import get_sessdata`.


# ── 7. Collections / 合集 ───────────────────────────────────────────────────
def check_collections(uid: str) -> list[dict]:
    """Check for B站 collections/合集 via the polymer seasons_list API.

    Returns list of {season_id, title, count}.
    """
    try:
        r = httpx.get(
            f"{_BILI_SEASONS_API}?mid={uid}",
            headers=_auth_headers(),
            timeout=_DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            logger.warning(
                "check_collections API error uid=%s code=%s msg=%s",
                uid, j.get("code"), j.get("message"),
            )
            return []

        items = j.get("data", {}).get("items_lists", [])
        # Some API versions nest under "items" — handle both
        if not items:
            items = j.get("data", {}).get("items", [])

        result = []
        for item in items:
            result.append({
                "season_id": item.get("season_id") or item.get("id", ""),
                "title": item.get("title", ""),
                "count": item.get("ep_count")
                or item.get("count")
                or len(item.get("episodes", [])),
            })
            time.sleep(0.5)
        return result
    except Exception:
        logger.exception("check_collections failed for uid=%s", uid)
        return []


# ── 8. User info ─────────────────────────────────────────────────────────────
def get_user_info(uid: str) -> dict:
    """Fetch UP user info via B站 card API.
    Returns {name, avatar, sign, fans} or {} on failure.
    """
    try:
        r = httpx.get(
            f"https://api.bilibili.com/x/web-interface/card?mid={uid}",
            headers=_auth_headers(),
            timeout=_DEFAULT_TIMEOUT,
        )
        j = r.json()
        if j.get("code") != 0:
            return {}
        card = j.get("data", {}).get("card", {})
        return {
            "name": card.get("name", ""),
            "avatar": card.get("face", ""),
            "sign": card.get("sign", ""),
            "fans": j.get("data", {}).get("follower", 0),
        }
    except Exception:
        logger.debug("get_user_info failed for uid=%s", uid)
        return {}
