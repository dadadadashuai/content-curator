"""AI summary service — SiliconFlow (OpenAI-compatible) API wrapper.

Provides structured Markdown knowledge-note generation, content cleaning,
claim extraction & verification, and batch note review.
"""
import json
import logging
import os
import re
from typing import Any

import httpx

from ..config import get_ai_config
from ..utils.prompt_templates import (
    SYSTEM_SUMMARY_PROMPT,
    CLEAN_PROMPT,
    EXTRACT_CLAIMS_PROMPT,
    VERIFY_CLAIM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

SF_API_KEY = os.environ.get("SF_API_KEY", "")


# ---------------------------------------------------------------------------
#  Low-level API helper
# ---------------------------------------------------------------------------
def _call_api(
    system_prompt: str,
    user_prompt: str,
    *,
    timeout: float = 60.0,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Send a single chat-completion request and return the content string.

    Raises ``RuntimeError`` on non-200 responses or empty content.
    """
    if not SF_API_KEY:
        raise RuntimeError("SF_API_KEY environment variable is not set")

    ai_cfg = get_ai_config()
    api_base = ai_cfg.get("api_base", "https://api.siliconflow.cn/v1")
    model = ai_cfg.get("text_model", "deepseek-ai/DeepSeek-V3")
    _temp = temperature if temperature is not None else ai_cfg.get("temperature", 0.3)
    _max_tokens = max_tokens if max_tokens is not None else ai_cfg.get("max_tokens", 2500)

    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {SF_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": _temp,
        "max_tokens": _max_tokens,
        "stream": False,
    }

    resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(
            f"SiliconFlow API error {resp.status_code}: {resp.text[:500]}"
        )

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected API response structure: {str(data)[:500]}")

    if not content or not content.strip():
        raise RuntimeError("API returned empty content")
    return content.strip()


# ---------------------------------------------------------------------------
#  1. generate_summary
# ---------------------------------------------------------------------------
def generate_summary(
    title: str,
    up_name: str,
    duration: int,
    subtitle: str,
    danmaku: str,
    structured_info: dict,
    frame_analysis: str,
    ad_filter_prompt: str,
) -> str:
    """Generate a structured Markdown knowledge note from video content.

    Parameters
    ----------
    title : str           — video title
    up_name : str         — uploader name
    duration : int        — duration in seconds
    subtitle : str        — full subtitle / transcript text
    danmaku : str         — aggregated danmaku comments
    structured_info : dict — pre-extracted structured info from the pipeline
    frame_analysis : str   — vision-model frame analysis text
    ad_filter_prompt : str — user-editable ad-filtering instructions

    Returns
    -------
    str — Markdown knowledge note
    """
    # Build the system prompt with the ad-filter rules injected
    system = SYSTEM_SUMMARY_PROMPT.format(ad_filter_prompt=ad_filter_prompt)

    # ---- assemble the user message -----------------------------------------
    duration_str = f"{duration // 60}分{duration % 60}秒" if duration else "未知"

    structured_text = json.dumps(structured_info, ensure_ascii=False, indent=2) if structured_info else "无"

    # Truncate very long inputs to stay within model context limits
    max_sub = 12000
    max_dan = 4000
    max_frame = 4000

    if len(subtitle) > max_sub:
        subtitle = subtitle[:max_sub] + "\n...(字幕已截断)"
    if len(danmaku) > max_dan:
        danmaku = danmaku[:max_dan] + "\n...(弹幕已截断)"
    if len(frame_analysis) > max_frame:
        frame_analysis = frame_analysis[:max_frame] + "\n...(画面分析已截断)"

    user_msg = f"""## 视频信息
- 标题：{title}
- UP主：{up_name}
- 时长：{duration_str}

## 字幕内容
{subtitle}

## 弹幕内容
{danmaku}

## 结构化信息
{structured_text}

## 画面分析
{frame_analysis}
"""

    try:
        return _call_api(system, user_msg, timeout=90.0)
    except Exception as exc:
        logger.error("generate_summary failed for '%s': %s", title, exc)
        raise


# ---------------------------------------------------------------------------
#  2. clean_content
# ---------------------------------------------------------------------------
def clean_content(text: str, ad_filter_prompt: str) -> str:
    """Pre-clean raw text — remove ads / promotional content and noise.

    Lighter than a full summary; returns cleaned text only.
    """
    if not text or not text.strip():
        return text or ""

    system = "你是一个内容清洗助手，只输出清洗后的文本，不添加任何说明。"
    user = CLEAN_PROMPT.format(ad_filter_prompt=ad_filter_prompt) + text

    try:
        return _call_api(system, user, timeout=60.0, temperature=0.1, max_tokens=4000)
    except Exception as exc:
        logger.error("clean_content failed: %s", exc)
        # Fall back to the original text so the pipeline can continue
        return text


# ---------------------------------------------------------------------------
#  3. extract_claims
# ---------------------------------------------------------------------------
def extract_claims(text: str) -> list[dict]:
    """Extract all [待验证] / [矛盾] claims from *text*.

    Returns a list of ``{"claim": str, "type": str, "context": str}``.
    """
    if not text or not text.strip():
        return []

    # ---- fast path: regex for [待验证] / [矛盾] markers ------------------
    regex_claims: list[dict] = []
    for m in re.finditer(r"(.+?)\s*\[待验证\]", text):
        claim_text = m.group(1).strip().split("\n")[-1]  # last line of the match
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 80)
        regex_claims.append({
            "claim": claim_text,
            "type": "待验证",
            "context": text[start:end].strip(),
        })
    for m in re.finditer(r"(.+?)\s*\[矛盾\]", text):
        claim_text = m.group(1).strip().split("\n")[-1]
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 80)
        regex_claims.append({
            "claim": claim_text,
            "type": "矛盾",
            "context": text[start:end].strip(),
        })

    # If regex already found marked claims, return them
    if regex_claims:
        return regex_claims

    # ---- AI fallback: ask the model to find unmarked suspicious claims ----
    system = "你是一个信息审核助手。请严格按照要求的JSON格式输出。"
    user = EXTRACT_CLAIMS_PROMPT + text

    try:
        raw = _call_api(system, user, timeout=60.0, temperature=0.1, max_tokens=2000)
    except Exception as exc:
        logger.error("extract_claims AI fallback failed: %s", exc)
        return []

    # Parse JSON from the response (tolerate code-fence wrapping)
    return _parse_json_list(raw)


def _parse_json_list(raw: str) -> list[dict]:
    """Best-effort extraction of a JSON array from an LLM response."""
    # Strip code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = cleaned.rsplit("```", 1)[0].strip()

    # Try direct json.loads first
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # some models wrap the list under a key
            for v in result.values():
                if isinstance(v, list):
                    return v
    except json.JSONDecodeError:
        pass

    # Fallback: find the first JSON array substring
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("extract_claims: failed to parse JSON from response: %s", raw[:200])
    return []


# ---------------------------------------------------------------------------
#  4. verify_claim
# ---------------------------------------------------------------------------
def verify_claim(claim: str, claim_type: str, context: str) -> dict:
    """Fact-check a single claim via the API.

    Returns ``{claim, verdict, explanation, correction, reference}``.
    """
    system = "你是一个事实核查助手。请严格按照要求的JSON格式输出。"
    user = VERIFY_CLAIM_PROMPT.format(
        claim=claim,
        claim_type=claim_type,
        context=context,
    )

    try:
        raw = _call_api(system, user, timeout=60.0, temperature=0.1, max_tokens=1500)
    except Exception as exc:
        logger.error("verify_claim failed for '%s': %s", claim, exc)
        return {
            "claim": claim,
            "verdict": "unconfirmed",
            "explanation": f"验证请求失败: {exc}",
            "correction": None,
            "reference": None,
        }

    parsed = _parse_json_dict(raw)
    # Ensure all expected keys exist
    return {
        "claim": parsed.get("claim", claim),
        "verdict": parsed.get("verdict", "unconfirmed"),
        "explanation": parsed.get("explanation", ""),
        "correction": parsed.get("correction"),
        "reference": parsed.get("reference"),
    }


def _parse_json_dict(raw: str) -> dict:
    """Best-effort extraction of a JSON object from an LLM response."""
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = cleaned.rsplit("```", 1)[0].strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("verify_claim: failed to parse JSON from response: %s", raw[:200])
    return {}


# ---------------------------------------------------------------------------
#  5. review_notes_batch
# ---------------------------------------------------------------------------
def review_notes_batch(notes: list[dict], batch_info: dict) -> str:
    """Batch-review a list of Obsidian notes and return review Markdown.

    Parameters
    ----------
    notes : list[dict]  — each ``{title, category, tags, up, body}``
    batch_info : dict   — ``{total, batch_start, batch_end, is_first, is_last}``

    Returns
    -------
    str — Markdown review report
    """
    if not notes:
        return "## 审阅报告\n\n本批次无笔记需要审阅。\n"

    total = batch_info.get("total", len(notes))
    b_start = batch_info.get("batch_start", 1)
    b_end = batch_info.get("batch_end", len(notes))
    is_first = batch_info.get("is_first", True)
    is_last = batch_info.get("is_last", True)

    position_parts = [
        f"总笔记数: {total}",
        f"当前批次: 第 {b_start}-{b_end} 篇",
    ]
    if is_first:
        position_parts.append("本批次为首批")
    if is_last:
        position_parts.append("本批次为末批")
    batch_position = "\n".join(position_parts)

    system = REVIEW_SYSTEM_PROMPT.format(batch_position=batch_position)

    # Assemble the notes for the user message
    parts: list[str] = [f"## 待审阅笔记（共 {len(notes)} 篇）\n"]
    for i, note in enumerate(notes, start=b_start):
        title = note.get("title", f"未命名笔记{i}")
        category = note.get("category", "未分类")
        tags = note.get("tags", [])
        if isinstance(tags, list):
            tags_str = ", ".join(tags) if tags else "无"
        else:
            tags_str = str(tags) if tags else "无"
        up = note.get("up", "未知")
        body = note.get("body", "")

        # Truncate very long note bodies
        max_body = 2000
        if len(body) > max_body:
            body = body[:max_body] + "\n...(内容已截断)"

        parts.append(f"---\n\n### 笔记 {i}: {title}\n")
        parts.append(f"- 分类: {category}")
        parts.append(f"- 标签: {tags_str}")
        parts.append(f"- UP主: {up}")
        parts.append(f"\n**正文:**\n{body}\n")

    user_msg = "\n".join(parts)

    try:
        return _call_api(system, user_msg, timeout=120.0, temperature=0.3, max_tokens=4000)
    except Exception as exc:
        logger.error("review_notes_batch failed: %s", exc)
        return f"## 审阅报告\n\n⚠️ 批次审阅失败: {exc}\n\n请检查API配置后重试。\n"
