"""
Audio transcription service.

Downloads audio from Bilibili via yt-dlp, then transcribes it using either
the SiliconFlow cloud API or local faster-whisper, depending on configuration.
"""

import os
import subprocess
from pathlib import Path

import httpx

from ..config import get_whisper_config, get_ai_config, CACHE_DIR, COOKIES_FILE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SF_API_KEY = os.environ.get("SF_API_KEY", "")

# Default SiliconFlow API base (can be overridden in app config)
_SF_API_BASE_DEFAULT = "https://api.siliconflow.cn/v1"

# yt-dlp download timeout (seconds)
_YTDLP_TIMEOUT = 600

# Audio file size limit for cloud upload (25 MB – OpenAI-compatible API limit)
_CLOUD_MAX_BYTES = 25 * 1024 * 1024


def _get_sf_api_base() -> str:
    """Return the SiliconFlow API base URL from AI config or env."""
    try:
        ai_cfg = get_ai_config()
        base = ai_cfg.get("api_base", "") or ai_cfg.get("sf_api_base", "")
        if base:
            return base.rstrip("/")
    except Exception:
        pass
    return os.environ.get("SF_API_BASE", _SF_API_BASE_DEFAULT)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_audio(bvid: str) -> Path:
    """Download audio for a Bilibili video via yt-dlp.

    Args:
        bvid: Bilibili BV id (e.g. ``"BV1xx411c7mD"``).

    Returns:
        Path to the downloaded ``audio.wav`` file.

    Raises:
        RuntimeError: if yt-dlp fails.
    """
    url = f"https://www.bilibili.com/video/{bvid}"
    out_dir = Path(CACHE_DIR) / bvid
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / "audio.wav"

    if wav_path.exists() and wav_path.stat().st_size > 0:
        # Already downloaded — reuse cached file
        return wav_path

    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "-x",
        "--audio-format", "wav",
        "--audio-quality", "5",
        "--no-warnings",
        "--no-check-certificates",
        "-o", str(out_dir / "audio.%(ext)s"),
    ]

    if COOKIES_FILE and Path(COOKIES_FILE).exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])

    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_YTDLP_TIMEOUT,
        )
    except FileNotFoundError:
        raise RuntimeError("yt-dlp is not installed or not in PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"yt-dlp timed out after {_YTDLP_TIMEOUT}s for {bvid}")

    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"yt-dlp failed: {stderr}")

    # yt-dlp may produce audio.webm then convert; verify final wav exists
    if not wav_path.exists():
        # yt-dlp might place it as audio.wav already
        candidates = list(out_dir.glob("audio.*"))
        if candidates:
            wav_path = candidates[0]
        else:
            raise RuntimeError(
                f"yt-dlp completed but no audio file found in {out_dir}"
            )

    return wav_path


# ---------------------------------------------------------------------------
# Cloud transcription (SiliconFlow API)
# ---------------------------------------------------------------------------

def transcribe_cloud(audio_path: str) -> dict:
    """Transcribe audio via SiliconFlow (or compatible OpenAI-style) API.

    If the API key is unavailable or the endpoint doesn't support audio
    transcription, returns an empty result with an error message.

    Returns:
        ``{text, segments}`` on success, or ``{text: "", segments: [],
        error: "..."}`` on failure.
    """
    audio = Path(audio_path)
    if not audio.exists():
        return {"text": "", "segments": [], "error": f"Audio file not found: {audio_path}"}

    if not SF_API_KEY:
        return {
            "text": "",
            "segments": [],
            "error": "SF_API_KEY not set — cloud transcription unavailable",
        }

    api_base = _get_sf_api_base()
    endpoint = f"{api_base}/audio/transcriptions"

    file_size = audio.stat().st_size
    if file_size > _CLOUD_MAX_BYTES:
        return {
            "text": "",
            "segments": [],
            "error": (
                f"Audio file too large for cloud API: "
                f"{file_size / 1024 / 1024:.1f} MB "
                f"(max {_CLOUD_MAX_BYTES / 1024 / 1024:.0f} MB). "
                "Use local transcription instead."
            ),
        }

    headers = {
        "Authorization": f"Bearer {SF_API_KEY}",
    }

    try:
        with open(audio, "rb") as f:
            files = {"file": (audio.name, f, "audio/wav")}
            data = {
                "model": "FunAudioLLM/SenseVoiceSmall",
                "response_format": "verbose_json",
            }
            with httpx.Client(timeout=300.0) as client:
                resp = client.post(endpoint, headers=headers, files=files, data=data)
    except httpx.TimeoutException:
        return {
            "text": "",
            "segments": [],
            "error": "Cloud transcription request timed out",
        }
    except Exception as exc:
        return {"text": "", "segments": [], "error": f"Request failed: {exc}"}

    if resp.status_code != 200:
        return {
            "text": "",
            "segments": [],
            "error": f"API returned HTTP {resp.status_code}: {resp.text[:500]}",
        }

    try:
        data = resp.json()
    except Exception:
        # API may return plain text
        return {
            "text": resp.text.strip(),
            "segments": [],
        }

    text = data.get("text", "")
    segments_raw = data.get("segments", [])

    segments: list[dict] = []
    for seg in segments_raw:
        segments.append({
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "text": seg.get("text", "").strip(),
        })

    return {"text": text, "segments": segments}


# ---------------------------------------------------------------------------
# Local transcription (faster-whisper)
# ---------------------------------------------------------------------------

def transcribe_local(audio_path: str) -> dict:
    """Transcribe audio locally using faster-whisper.

    Model size and language come from the whisper config.
    Device is CPU (Pi 5) with int8 compute for minimal memory.

    Returns:
        ``{text, segments: [{start, text}]}``
    """
    audio = Path(audio_path)
    if not audio.exists():
        return {"text": "", "segments": [], "error": f"Audio file not found: {audio_path}"}

    cfg = get_whisper_config()
    model_size = cfg.get("model_size", "base")
    language = cfg.get("language") or None

    # Lazy import — faster-whisper is optional and slow to load
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {
            "text": "",
            "segments": [],
            "error": "faster-whisper not installed. Install with: pip install faster-whisper",
        }

    try:
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
        )
    except Exception as exc:
        return {
            "text": "",
            "segments": [],
            "error": f"Failed to load whisper model '{model_size}': {exc}",
        }

    try:
        segments_iter, info = model.transcribe(
            str(audio),
            language=language,
            beam_size=5,
            vad_filter=True,
        )
    except Exception as exc:
        return {
            "text": "",
            "segments": [],
            "error": f"Transcription failed: {exc}",
        }

    segments: list[dict] = []
    full_text_parts: list[str] = []

    for seg in segments_iter:
        seg_text = seg.text.strip()
        segments.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg_text,
        })
        full_text_parts.append(seg_text)

    full_text = " ".join(full_text_parts).strip()

    return {"text": full_text, "segments": segments}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def transcribe_audio(bvid: str) -> dict:
    """Download audio for *bvid* and transcribe it.

    The transcription backend (cloud or local) is determined by the
    ``mode`` field in whisper config:
      - ``"cloud"``: SiliconFlow API
      - ``"local"``: faster-whisper on CPU
      - fallback: try cloud first, then local on failure

    Returns:
        ``{text, segments: [{start, text}], duration}``
    """
    # Step 1: download audio
    try:
        audio_path = download_audio(bvid)
    except RuntimeError as exc:
        return {
            "text": "",
            "segments": [],
            "duration": 0,
            "error": str(exc),
        }

    # Step 2: determine mode
    cfg = get_whisper_config()
    mode = cfg.get("mode", "local")

    result: dict = {}

    if mode == "cloud":
        result = transcribe_cloud(str(audio_path))
        # If cloud fails, fallback to local
        if result.get("error") and not result.get("text"):
            print(f"[transcribe] Cloud failed: {result['error']} — falling back to local")
            result = transcribe_local(str(audio_path))
    elif mode == "local":
        result = transcribe_local(str(audio_path))
    else:
        # Unknown mode — try local as safe default
        result = transcribe_local(str(audio_path))

    # Step 3: compute rough duration from segments (if available)
    duration = 0.0
    segments = result.get("segments", [])
    if segments:
        # Try to use the end time of the last segment
        last_seg = segments[-1]
        if "end" in last_seg:
            duration = float(last_seg["end"])
        elif "start" in last_seg:
            # Fallback: use last start time
            duration = float(last_seg["start"])

    return {
        "text": result.get("text", ""),
        "segments": segments,
        "duration": duration,
        **({"error": result["error"]} if "error" in result else {}),
    }
