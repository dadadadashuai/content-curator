"""
Vision / frame analysis service for B站 video keyframe extraction and VLM analysis.

Provides:
- detect_structured_info: regex-based detection of code, commands, URLs, config from subtitle text
- should_use_frames: decision logic for whether visual frame analysis is needed
- extract_frames: download video clip via yt-dlp, extract keyframes via ffmpeg
- analyze_frames: call SiliconFlow VLM API (Qwen3-VL-8B-Instruct) to analyze keyframes
- extract_structured_info_text: format structured info dict into readable text
"""

import os
import re
import base64
import subprocess
import shutil
from pathlib import Path
from typing import Any

import httpx

from ..config import CACHE_DIR, get_ai_config, COOKIES_FILE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Visual keywords that indicate frame analysis is worthwhile even if subtitles
# have high structured-info coverage.
VISUAL_KEYWORDS: list[str] = [
    "图表", "界面", "截图", "图解", "演示", "效果展示",
    "对比图", "流程图", "架构图", "dashboard", "ui", "可视化",
]

# Coverage threshold — if subtitle text has this much structured info, frames
# might be skippable (unless visual keywords are present in the title).
COVERAGE_THRESHOLD: float = 0.6

# Hard cap on how many frames we send to the VLM (to limit token cost).
VLM_MAX_FRAMES: int = 4

# yt-dlp download section — only grab the first 120 seconds.
DOWNLOAD_SECTION: str = "*0-120"

# Target video format string for yt-dlp (360p video + audio fallback chain).
YTDLP_FORMAT: str = "30016+30280/30011+30280/best"

# ---------------------------------------------------------------------------
# 1. detect_structured_info
# ---------------------------------------------------------------------------

# Regex patterns for structured information detection.

# Code blocks: fenced ``` or indented (4+ spaces) blocks of 3+ lines, or inline `code`.
_RE_FENCED_CODE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_RE_INDENTED_CODE = re.compile(
    r"(?:^ {4,}\S.*\n){3,}", re.MULTILINE
)
_RE_INLINE_CODE = re.compile(r"`[^`\n]{2,}`")

# Shell / CLI commands: lines starting with $ or # followed by a known command,
# or lines that look like "command --flag value".
_RE_SHELL_CMD = re.compile(
    r"^\s*(?:\$|>|#)\s*([\w./-]+(?:\s+[\w./=-]+)*)\s*$",
    re.MULTILINE,
)
_RE_BARE_CMD = re.compile(
    r"^\s*((?:pip|npm|yarn|docker|git|python|python3|node|go|cargo|"
    r"brew|apt|apt-get|yum|kubectl|helm|terraform|aws|gcloud|az|"
    r"curl|wget|ssh|scp|rsync|tar|unzip|chmod|chown|mkdir|cd|ls|cp|mv|"
    r"cat|echo|export|source|conda|venv|make|cmake|gcc|rustc|"
    r"systemctl|service|journalctl|ufw|iptables|nginx|redis-cli|"
    r"mongo|psql|mysql|sqlite3)\b.*)$",
    re.MULTILINE,
)

# URLs.
_RE_URL = re.compile(
    r"https?://[^\s<>'\"，。、）)】\]]+",
    re.IGNORECASE,
)

# Config items: KEY=VALUE, YAML "key: value", JSON-ish "key": "value",
# TOML "key = value", or common config file references.
_RE_ENV_CONFIG = re.compile(
    r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+)$",
    re.MULTILINE,
)
_RE_YAML_CONFIG = re.compile(
    r"^\s*([a-z_][\w-]*)\s*:\s+(\S+.*?)(?:\s*#.*)?$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_CONFIG_FILE_REF = re.compile(
    r"(?:^|\s)((?:~/|/)?[\w./-]+(?:\.(?:yml|yaml|toml|ini|conf|cfg|env|json|xml|properties))(?::\d+)?)",
    re.MULTILINE,
)


def detect_structured_info(text: str) -> dict[str, Any]:
    """Detect code, commands, URLs, and config from subtitle text using regex.

    Returns a dict with:
        has_code        — bool
        has_commands    — bool
        has_urls        — bool
        has_config      — bool
        code_blocks     — list[str]
        commands        — list[str]
        urls            — list[str]
        config_items    — list[str]
        coverage_score  — float (0-1), ratio of text lines containing structured info
    """
    if not text or not text.strip():
        return {
            "has_code": False,
            "has_commands": False,
            "has_urls": False,
            "has_config": False,
            "code_blocks": [],
            "commands": [],
            "urls": [],
            "config_items": [],
            "coverage_score": 0.0,
        }

    # --- Code blocks -------------------------------------------------------
    code_blocks: list[str] = []

    for m in _RE_FENCED_CODE.finditer(text):
        block = m.group(0).strip()
        # Strip the enclosing ``` fences for readability.
        inner = re.sub(r"^```[^\n]*\n?", "", block)
        inner = re.sub(r"\n?```$", "", inner)
        if inner.strip():
            code_blocks.append(inner.strip())

    for m in _RE_INDENTED_CODE.finditer(text):
        block = m.group(0).rstrip()
        # Dedent by removing the leading 4 spaces.
        dedented = re.sub(r"^ {4}", "", block, flags=re.MULTILINE)
        if dedented.strip() and dedented not in code_blocks:
            code_blocks.append(dedented)

    # Inline code (only if we don't already have fenced/indented coverage).
    if not code_blocks:
        inline_hits = _RE_INLINE_CODE.findall(text)
        if inline_hits:
            code_blocks.extend(inline_hits)

    has_code = len(code_blocks) > 0

    # --- Commands ----------------------------------------------------------
    commands: list[str] = []
    for m in _RE_SHELL_CMD.finditer(text):
        cmd = m.group(1).strip()
        if cmd and cmd not in commands:
            commands.append(cmd)

    for m in _RE_BARE_CMD.finditer(text):
        cmd = m.group(1).strip()
        if cmd and cmd not in commands:
            commands.append(cmd)

    has_commands = len(commands) > 0

    # --- URLs --------------------------------------------------------------
    urls: list[str] = []
    for m in _RE_URL.finditer(text):
        url = m.group(0).rstrip(".,;:!?)")
        if url and url not in urls:
            urls.append(url)
    has_urls = len(urls) > 0

    # --- Config items ------------------------------------------------------
    config_items: list[str] = []

    for m in _RE_ENV_CONFIG.finditer(text):
        item = f"{m.group(1)}={m.group(2).strip()}"
        if item not in config_items:
            config_items.append(item)

    for m in _RE_YAML_CONFIG.finditer(text):
        key = m.group(1)
        val = m.group(2).strip().strip("\"'")
        # Skip false positives (sentences that happen to have a colon).
        if len(val) < 200 and not val.endswith(("。", "，", "；")):
            item = f"{key}: {val}"
            if item not in config_items:
                config_items.append(item)

    for m in _RE_CONFIG_FILE_REF.finditer(text):
        ref = m.group(1).strip()
        if ref and ref not in config_items:
            config_items.append(ref)

    has_config = len(config_items) > 0

    # --- Coverage score ----------------------------------------------------
    # Compute the fraction of non-empty text lines that contain at least one
    # structured-info marker.  This gives a 0-1 score: 0 means the subtitle is
    # all prose, 1 means every line has code/cmd/url/config.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    total_lines = max(len(lines), 1)

    structured_line_count = 0
    for ln in lines:
        is_structured = (
            bool(_RE_FENCED_CODE.search(ln))
            or bool(_RE_INLINE_CODE.search(ln))
            or bool(_RE_SHELL_CMD.match(ln))
            or bool(_RE_BARE_CMD.match(ln))
            or bool(_RE_URL.search(ln))
            or bool(_RE_ENV_CONFIG.match(ln))
            or bool(_RE_YAML_CONFIG.match(ln))
            or bool(_RE_CONFIG_FILE_REF.search(ln))
            or ln.startswith("    ")  # indented (potential code)
        )
        if is_structured:
            structured_line_count += 1

    coverage_score = round(structured_line_count / total_lines, 4)

    return {
        "has_code": has_code,
        "has_commands": has_commands,
        "has_urls": has_urls,
        "has_config": has_config,
        "code_blocks": code_blocks,
        "commands": commands,
        "urls": urls,
        "config_items": config_items,
        "coverage_score": coverage_score,
    }


# ---------------------------------------------------------------------------
# 2. should_use_frames
# ---------------------------------------------------------------------------

def should_use_frames(subtitle_text: str, title: str = "") -> dict[str, Any]:
    """Decide whether visual frame analysis is needed.

    Logic:
        - If the subtitle has high structured-info coverage (>=0.6) AND
          the title contains no visual keywords → skip frames.
        - Otherwise, use frames.

    Returns:
        {should_use_frames: bool, reason: str, info_detection: dict}
    """
    info = detect_structured_info(subtitle_text or "")
    coverage = info["coverage_score"]
    title_lower = (title or "").lower()

    has_visual_keyword = any(kw.lower() in title_lower for kw in VISUAL_KEYWORDS)

    if coverage >= COVERAGE_THRESHOLD and not has_visual_keyword:
        return {
            "should_use_frames": False,
            "reason": (
                f"Subtitle coverage {coverage:.2f} >= {COVERAGE_THRESHOLD} "
                f"and no visual keywords in title — frames not needed."
            ),
            "info_detection": info,
        }

    if has_visual_keyword:
        return {
            "should_use_frames": True,
            "reason": (
                f"Title contains visual keyword(s) — frame analysis recommended "
                f"(coverage={coverage:.2f})."
            ),
            "info_detection": info,
        }

    return {
        "should_use_frames": True,
        "reason": (
            f"Subtitle coverage {coverage:.2f} < {COVERAGE_THRESHOLD} — "
            f"frames may contain additional structured info."
        ),
        "info_detection": info,
    }


# ---------------------------------------------------------------------------
# 3. extract_frames
# ---------------------------------------------------------------------------

def extract_frames(
    bvid: str,
    aid: str = "",
    cid: str = "",
    duration: int = 0,
    count: int = 6,
) -> dict[str, Any]:
    """Download a short video clip and extract keyframes as base64 images.

    Steps:
        1. Build the B站 URL from bvid.
        2. Download the first 120s at 360p via yt-dlp (with cookies).
        3. Use ffprobe to get the actual downloaded duration.
        4. Compute interval = duration / (count + 1).
        5. Extract *count* frames with ffmpeg at fps=1/interval.
        6. Convert each frame PNG to base64.
        7. Clean up the downloaded video file.

    Returns:
        {success: bool, bvid: str, frame_count: int, frames: [{name, size, base64}]}
    """
    result: dict[str, Any] = {
        "success": False,
        "bvid": bvid,
        "frame_count": 0,
        "frames": [],
    }

    if not bvid:
        result["error"] = "bvid is required"
        return result

    # Ensure cache dir exists.
    cache_dir = Path(CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Build the B站 video URL.
    video_url = f"https://www.bilibili.com/video/{bvid}"

    # Output video path.
    video_path = cache_dir / f"{bvid}_clip.mp4"
    # Frame output pattern.
    frame_prefix = cache_dir / f"{bvid}_frame"

    # --- Step 1: Download via yt-dlp ---------------------------------------
    ytdlp_cmd: list[str] = [
        "yt-dlp",
        "-f", YTDLP_FORMAT,
        "--merge-output-format", "mp4",
        "-o", str(video_path),
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
    ]

    # Attach cookies if available.
    cookies_path = str(COOKIES_FILE) if COOKIES_FILE else ""
    if cookies_path and Path(cookies_path).exists():
        ytdlp_cmd.extend(["--cookies", cookies_path])

    # Only download the first 120 seconds for long videos.
    ytdlp_cmd.extend(["--download-sections", DOWNLOAD_SECTION])
    ytdlp_cmd.append(video_url)

    try:
        subprocess.run(
            ytdlp_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        result["error"] = "yt-dlp download timed out (120s)"
        _cleanup(video_path, frame_prefix)
        return result
    except Exception as exc:
        result["error"] = f"yt-dlp failed: {exc}"
        _cleanup(video_path, frame_prefix)
        return result

    if not video_path.exists():
        result["error"] = "yt-dlp produced no output file"
        _cleanup(video_path, frame_prefix)
        return result

    # --- Step 2: Get actual duration via ffprobe ----------------------------
    actual_duration: float = float(duration) if duration > 0 else 0.0

    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            actual_duration = float(probe.stdout.strip())
    except Exception:
        pass  # Fall back to provided duration or a safe default.

    if actual_duration <= 0:
        actual_duration = 60.0  # Safe fallback.

    # --- Step 3: Compute interval & extract frames -------------------------
    # interval = duration / (count + 1) so frames are evenly distributed
    # across the clip (skipping the very start and very end).
    interval = max(actual_duration / (count + 1), 0.5)

    frame_pattern = str(frame_prefix) + "_%03d.jpg"

    ffmpeg_cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vf", f"fps=1/{interval}",
        "-frames:v", str(count),
        "-q:v", "2",
        frame_pattern,
    ]

    try:
        subprocess.run(
            ffmpeg_cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        result["error"] = "ffmpeg extraction timed out (60s)"
        _cleanup(video_path, frame_prefix)
        return result
    except Exception as exc:
        result["error"] = f"ffmpeg failed: {exc}"
        _cleanup(video_path, frame_prefix)
        return result

    # --- Step 4: Collect frames & convert to base64 ------------------------
    frames_out: list[dict[str, Any]] = []
    frame_files = sorted(cache_dir.glob(f"{bvid}_frame_*.jpg"))

    for fpath in frame_files:
        try:
            with open(fpath, "rb") as f:
                raw = f.read()
            b64 = base64.b64encode(raw).decode("utf-8")
            frames_out.append({
                "name": fpath.name,
                "size": fpath.stat().st_size,
                "base64": b64,
            })
        except Exception:
            continue

    # --- Step 5: Cleanup ---------------------------------------------------
    _cleanup(video_path, frame_prefix)

    result["success"] = len(frames_out) > 0
    result["frame_count"] = len(frames_out)
    result["frames"] = frames_out

    if not frames_out:
        result["error"] = "No frames were extracted"

    return result


def _cleanup(video_path: Path, frame_prefix: Path) -> None:
    """Remove the downloaded video and extracted frame files."""
    try:
        if video_path.exists():
            video_path.unlink()
    except Exception:
        pass

    try:
        parent = frame_prefix.parent
        stem = frame_prefix.name
        for f in parent.glob(f"{stem}*"):
            try:
                f.unlink()
            except Exception:
                pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 4. analyze_frames
# ---------------------------------------------------------------------------

# SiliconFlow VLM API endpoint.
VLM_API_URL: str = "https://api.siliconflow.cn/v1/chat/completions"

# Model identifier for Qwen3-VL-8B-Instruct on SiliconFlow.
VLM_MODEL: str = "Qwen/Qwen3-VL-8B-Instruct"

# HTTP timeout for VLM API calls (seconds).
VLM_TIMEOUT: int = 90

VLM_SYSTEM_PROMPT: str = (
    "你是一个视频帧分析助手。你将收到视频的关键帧截图，请仔细分析每一帧的内容，"
    "重点关注以下方面：\n"
    "1. 帧中出现的文字内容（代码、命令行、URL、配置信息等），如果能直接读取请标注 [文字可提取]；\n"
    "2. 工具界面、软件操作界面、终端窗口等可视化内容；\n"
    "3. 教学要点、步骤说明、流程展示等关键信息；\n"
    "4. 如果帧中的信息需要通过视觉理解才能获取（如界面布局、图表趋势、操作步骤等），"
    "请标注 [需视觉理解]。\n\n"
    "请以结构化的方式输出分析结果，按帧编号逐一描述。"
)


def analyze_frames(frames: list[dict[str, Any]], title: str = "") -> str:
    """Call SiliconFlow VLM API to analyze up to 4 keyframes.

    Each frame in *frames* must have a ``base64`` field containing the
    base64-encoded JPEG image data.

    Args:
        frames: List of frame dicts (as produced by :func:`extract_frames`).
        title:  Optional video title for context.

    Returns:
        A string containing the VLM analysis text.  On error, returns a
        description of the failure.
    """
    if not frames:
        return "无帧可分析。"

    # Limit to VLM_MAX_FRAMES to control token cost.
    selected = frames[:VLM_MAX_FRAMES]

    try:
        ai_config = get_ai_config()
    except Exception:
        ai_config = {}

    api_key = ""
    if isinstance(ai_config, dict):
        api_key = ai_config.get("sf_api_key", "") or ai_config.get("SF_API_KEY", "")
    if not api_key:
        # Try environment variable as fallback.
        api_key = os.environ.get("SF_API_KEY", "") or os.environ.get("SILICONFLOW_API_KEY", "")

    if not api_key:
        return "错误：未配置 SiliconFlow API Key，无法调用 VLM。"

    # --- Build the messages payload ----------------------------------------
    content_parts: list[dict[str, Any]] = []

    # Text instruction part.
    instruction = "请分析以下视频关键帧。"
    if title:
        instruction += f"\n视频标题：{title}"
    instruction += (
        "\n请逐一分析每帧内容，识别其中的文字（代码/命令/URL）、工具界面和教学要点。"
        "\n对可直接读取的文字标注 [文字可提取]，对需视觉理解的内容标注 [需视觉理解]。"
    )

    content_parts.append({"type": "text", "text": instruction})

    # Image parts.
    for idx, frame in enumerate(selected, 1):
        b64 = frame.get("base64", "")
        if not b64:
            continue
        content_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{b64}",
            },
        })

    messages = [
        {"role": "system", "content": VLM_SYSTEM_PROMPT},
        {"role": "user", "content": content_parts},
    ]

    payload = {
        "model": VLM_MODEL,
        "messages": messages,
        "max_tokens": 2048,
        "temperature": 0.3,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # --- Call the API ------------------------------------------------------
    try:
        with httpx.Client(timeout=VLM_TIMEOUT) as client:
            resp = client.post(VLM_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return f"VLM 请求超时（{VLM_TIMEOUT}s）。"
    except httpx.HTTPStatusError as exc:
        return f"VLM API 返回错误 {exc.response.status_code}: {exc.response.text[:500]}"
    except Exception as exc:
        return f"VLM 请求失败: {exc}"

    # --- Extract response text ---------------------------------------------
    try:
        choices = data.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")
            if isinstance(text, list):
                # Some APIs return content as a list of parts.
                text = " ".join(
                    p.get("text", "") for p in text if isinstance(p, dict)
                )
            return text.strip() or "VLM 返回了空内容。"
        return "VLM 响应中没有 choices。"
    except Exception as exc:
        return f"解析 VLM 响应失败: {exc}"


# ---------------------------------------------------------------------------
# 5. extract_structured_info_text
# ---------------------------------------------------------------------------

def extract_structured_info_text(info_detection: dict[str, Any]) -> str:
    """Format the structured info dict into a readable text string.

    This is intended to be prepended to or included in the AI summary prompt
    so the model knows what structured information was already detected in
    the subtitles.

    Args:
        info_detection: The dict returned by :func:`detect_structured_info`.

    Returns:
        A human-readable, structured text summary.
    """
    if not info_detection:
        return ""

    parts: list[str] = []

    coverage = info_detection.get("coverage_score", 0.0)
    parts.append(f"### 结构化信息检测 (覆盖率: {coverage:.1%})")
    parts.append("")

    # Code blocks
    code_blocks = info_detection.get("code_blocks", [])
    if code_blocks:
        parts.append("**检测到代码片段：**")
        for i, block in enumerate(code_blocks, 1):
            # Truncate long code blocks for readability.
            snippet = block if len(block) <= 500 else block[:500] + " ...[截断]"
            parts.append(f"```\n{snippet}\n```")
        parts.append("")

    # Commands
    commands = info_detection.get("commands", [])
    if commands:
        parts.append("**检测到命令行指令：**")
        for cmd in commands:
            snippet = cmd if len(cmd) <= 200 else cmd[:200] + " ..."
            parts.append(f"- `{snippet}`")
        parts.append("")

    # URLs
    urls = info_detection.get("urls", [])
    if urls:
        parts.append("**检测到链接：**")
        for url in urls:
            parts.append(f"- {url}")
        parts.append("")

    # Config items
    config_items = info_detection.get("config_items", [])
    if config_items:
        parts.append("**检测到配置信息：**")
        for item in config_items:
            snippet = item if len(item) <= 200 else item[:200] + " ..."
            parts.append(f"- `{snippet}`")
        parts.append("")

    # Summary flags
    flags: list[str] = []
    if info_detection.get("has_code"):
        flags.append("代码")
    if info_detection.get("has_commands"):
        flags.append("命令")
    if info_detection.get("has_urls"):
        flags.append("链接")
    if info_detection.get("has_config"):
        flags.append("配置")

    if flags:
        parts.append(f"**信息类型：** {', '.join(flags)}")
    else:
        parts.append("字幕中未检测到明显的结构化信息。")

    parts.append("")

    return "\n".join(parts)
