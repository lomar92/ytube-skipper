"""JSON-based per-video caching in ~/.cache/ytsum/."""

import json
import os
import re
from dataclasses import asdict
from pathlib import Path

from .models import (
    Analysis,
    CostReport,
    KeyPoint,
    Segment,
    SkipRange,
    Transcript,
    VideoMeta,
)

# YouTube video IDs are exactly 11 characters: alphanumeric, hyphen, underscore.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _validate_video_id(video_id: str) -> None:
    """Reject malformed IDs to prevent path-traversal attacks on cache files."""
    if not _VIDEO_ID_RE.match(video_id):
        raise ValueError(f"Invalid video_id: {video_id!r}")


def cache_dir() -> Path:
    """~/.cache/ytsum/ (XDG-compliant, created on first use)."""
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / "ytsum"
    d.mkdir(parents=True, exist_ok=True)
    return d


def transcript_cache_path(video_id: str) -> Path:
    _validate_video_id(video_id)
    d = cache_dir() / "transcripts"
    d.mkdir(exist_ok=True)
    return d / f"{video_id}.json"


def analysis_cache_path(video_id: str, profile_hash: str) -> Path:
    _validate_video_id(video_id)
    d = cache_dir() / "analyses"
    d.mkdir(exist_ok=True)
    return d / f"{video_id}_{profile_hash[:8]}.json"


# ---------------------------------------------------------------------------
# Deserializers
# ---------------------------------------------------------------------------

def _segment_from_dict(d: dict) -> Segment:
    return Segment(
        start=d["start"],
        end=d["end"],
        text=d["text"],
        speaker=d.get("speaker"),
    )


def _transcript_from_dict(d: dict) -> Transcript:
    return Transcript(
        meta=VideoMeta(**d["meta"]),
        language=d["language"],
        segments=[_segment_from_dict(s) for s in d["segments"]],
        source=d["source"],
    )


def _analysis_from_dict(d: dict) -> Analysis:
    key_points = [
        KeyPoint(**kp) for kp in d.get("key_points", [])
    ]
    skip_ranges = [
        SkipRange(**sr) for sr in d.get("skip_ranges", [])
    ]
    return Analysis(
        video_id=d["video_id"],
        verdict=d["verdict"],
        relevance_score=d["relevance_score"],
        relevance_reason=d["relevance_reason"],
        time_saving=d["time_saving"],
        core_thesis=d["core_thesis"],
        key_points=key_points,
        relevant_for_you=d.get("relevant_for_you", []),
        skip_ranges=skip_ranges,
        visuals_only=d.get("visuals_only"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_transcript(video_id: str) -> Transcript | None:
    """Return cached Transcript or None."""
    path = transcript_cache_path(video_id)
    if not path.exists():
        return None
    try:
        return _transcript_from_dict(json.loads(path.read_text()))
    except Exception:
        return None


def save_transcript(transcript: Transcript) -> None:
    """Serialize and write atomically via temp-file + rename."""
    path = transcript_cache_path(transcript.meta.video_id)
    data = {
        "meta": asdict(transcript.meta),
        "language": transcript.language,
        "segments": [asdict(s) for s in transcript.segments],
        "source": transcript.source,
    }
    _atomic_write(path, data)


def load_analysis(video_id: str, profile_hash: str) -> tuple[Analysis, CostReport] | None:
    """Return cached (Analysis, CostReport) or None."""
    path = analysis_cache_path(video_id, profile_hash)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
        analysis = _analysis_from_dict(d["analysis"])
        cost = CostReport(**d["cost"])
        return analysis, cost
    except Exception:
        return None


def save_analysis(
    video_id: str,
    profile_hash: str,
    analysis: Analysis,
    cost: CostReport,
) -> None:
    """Serialize and write atomically."""
    path = analysis_cache_path(video_id, profile_hash)
    data = {
        "analysis": asdict(analysis),
        "cost": asdict(cost),
    }
    _atomic_write(path, data)


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)   # atomic on POSIX
