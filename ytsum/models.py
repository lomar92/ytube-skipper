"""Data models and custom exceptions for ytsum."""

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class YtsumError(Exception):
    """Base exception for all ytsum errors."""


class TranscriptError(YtsumError):
    """Raised when a transcript cannot be fetched or processed."""


class ProfileError(YtsumError):
    """Raised when interests.yaml is missing or malformed."""


class NetworkError(YtsumError):
    """Raised on network / download failures."""


# ---------------------------------------------------------------------------
# Core data models
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    start: float          # seconds from video start
    end: float
    text: str
    speaker: str | None = None   # "Speaker 1" or a detected name


@dataclass
class VideoMeta:
    video_id: str
    title: str
    channel: str
    duration: int         # seconds
    url: str
    upload_date: str      # YYYY-MM-DD


@dataclass
class Transcript:
    meta: VideoMeta
    language: str         # "de", "en", …
    segments: list[Segment]
    source: Literal["manual_subtitles", "auto_subtitles", "whisper"]


@dataclass
class KeyPoint:
    thesis: str           # "X argues that Y because Z" — never a bare topic label
    timestamp: float      # seconds
    youtube_link: str     # https://youtu.be/<id>?t=<sec>


@dataclass
class SkipRange:
    start: float
    end: float
    reason: str           # "sponsor", "intro", "off-topic", …


@dataclass
class Analysis:
    video_id: str
    verdict: Literal["watch", "watch_sections", "summary_sufficient", "skip"]
    relevance_score: int          # 0-10
    relevance_reason: str         # one sentence
    time_saving: str              # "12 of 94 minutes relevant"
    core_thesis: str              # 3-5 sentences: claim + evidence + atmosphere/tenor
    key_points: list[KeyPoint]
    relevant_for_you: list[str]   # bullet lines referencing profile topics
    skip_ranges: list[SkipRange]
    visuals_only: str | None      # note when charts/demos are load-bearing


@dataclass
class CostReport:
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
