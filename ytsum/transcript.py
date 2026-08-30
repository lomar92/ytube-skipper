"""YouTube subtitle fetching + Whisper fallback + speaker detection."""

import re
import time
from pathlib import Path

import yt_dlp

from .models import NetworkError, Segment, Transcript, TranscriptError, VideoMeta


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def extract_video_id(url: str) -> str:
    """
    Parse video ID from watch?v=, youtu.be/, /shorts/ URLs.
    Raises ValueError on unrecognised format.
    """
    url = url.strip()

    # youtu.be/<id>
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # /shorts/<id>
    m = re.search(r"/shorts/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # watch?v=<id>
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # Bare 11-char ID
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url

    raise ValueError(
        f"Cannot extract video ID from: {url!r}\n"
        "Supported formats: watch?v=, youtu.be/, /shorts/"
    )


# ---------------------------------------------------------------------------
# Video metadata
# ---------------------------------------------------------------------------

def fetch_video_meta(video_id: str) -> VideoMeta:
    """yt-dlp metadata (title, channel, duration). No download."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "private" in msg.lower() or "unavailable" in msg.lower():
            raise TranscriptError("Video nicht zugänglich (privat oder nicht verfügbar).") from e
        raise NetworkError(f"yt-dlp Fehler: {e}\nNetzwerkverbindung prüfen.") from e

    # yt-dlp stores upload_date as YYYYMMDD
    raw_date = info.get("upload_date", "")
    upload_date = (
        f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        if len(raw_date) == 8 else raw_date
    )

    return VideoMeta(
        video_id=video_id,
        title=info.get("title", "Unknown Title"),
        channel=info.get("channel") or info.get("uploader", "Unknown Channel"),
        duration=int(info.get("duration") or 0),
        url=url,
        upload_date=upload_date,
    )


# ---------------------------------------------------------------------------
# YouTube subtitle fetching
# ---------------------------------------------------------------------------

def fetch_youtube_subtitles(
    video_id: str,
) -> tuple[list[Segment], str, str] | None:
    """
    Returns (segments, language, source) or None if unavailable.
    Tries manual subtitles before auto-generated; prefers DE then EN.
    """
    try:
        from youtube_transcript_api import (
            NoTranscriptFound,
            TranscriptsDisabled,
            YouTubeTranscriptApi,
        )
    except ImportError:
        raise ImportError(
            "youtube-transcript-api not installed. "
            "Install with: pip install youtube-transcript-api"
        )

    preferred_langs = ["de", "de-DE", "en", "en-US", "en-GB"]

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    except Exception:
        return None

    # Try manual first
    for source_label, finder in [
        ("manual_subtitles", transcript_list.find_manually_created_transcript),
        ("auto_subtitles", transcript_list.find_generated_transcript),
    ]:
        try:
            t = finder(preferred_langs)
            fetched = t.fetch()
            segments = [
                Segment(
                    start=entry["start"],
                    end=entry["start"] + entry.get("duration", 0),
                    text=_clean_subtitle_text(entry["text"]),
                )
                for entry in fetched
                if entry.get("text", "").strip()
            ]
            return segments, t.language_code, source_label
        except Exception:
            continue

    return None


def _clean_subtitle_text(text: str) -> str:
    """Strip common subtitle artefacts: HTML tags, [music], (applause)."""
    text = re.sub(r"<[^>]+>", "", text)          # HTML tags
    text = re.sub(r"\[[^\]]*\]", "", text)        # [Music], [Applause]
    text = re.sub(r"\([^)]*\)", "", text)         # (laughter)
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Audio download + Whisper
# ---------------------------------------------------------------------------

def download_audio(video_id: str, cache_dir: Path) -> Path:
    """Download audio-only stream via yt-dlp. Returns path to downloaded file."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_template = str(cache_dir / f"{video_id}.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get("ext", "m4a")
    except yt_dlp.utils.DownloadError as e:
        raise NetworkError(f"Audio-Download fehlgeschlagen: {e}\nNetzwerk prüfen oder später erneut versuchen.") from e

    path = cache_dir / f"{video_id}.{ext}"
    if not path.exists():
        # Fallback: find any matching file
        matches = list(cache_dir.glob(f"{video_id}.*"))
        if not matches:
            raise NetworkError(f"Downloaded audio file not found in {cache_dir}")
        path = matches[0]
    return path


def transcribe_with_whisper(
    audio_path: Path,
    model_size: str = "base",
) -> tuple[list[Segment], str]:
    """
    Run faster-whisper on audio_path.
    Returns (segments, detected_language).

    ★ faster-whisper is an optional dependency. Install with:
       pip install faster-whisper
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError(
            "faster-whisper ist nicht installiert.\n"
            "Installieren mit: pip install faster-whisper\n"
            "Oder --no-whisper nutzen um auf Untertitel zu bestehen."
        )

    print(f"  Lade Whisper-Modell '{model_size}'…")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    print(f"  Starte Transkription ({audio_path.name})…")
    raw_segments, info = model.transcribe(str(audio_path), beam_size=5)

    total_duration = info.duration or 0
    segments: list[Segment] = []
    start_time = time.time()
    last_pct = -1

    for seg in raw_segments:
        segments.append(Segment(start=seg.start, end=seg.end, text=seg.text.strip()))

        if total_duration > 0:
            pct = min(99, int(seg.end / total_duration * 100))
            if pct >= last_pct + 2:   # nur alle 2% neu zeichnen
                elapsed = time.time() - start_time
                eta = int((elapsed / max(pct, 1)) * (100 - pct))
                filled = pct // 5
                bar = "█" * filled + "░" * (20 - filled)
                if eta >= 60:
                    eta_str = f"{eta // 60}m {eta % 60:02d}s verbleibend"
                else:
                    eta_str = f"~{eta}s verbleibend"
                print(f"\r  [{bar}] {pct:3d}%  {eta_str}    ", end="", flush=True)
                last_pct = pct

    elapsed_total = int(time.time() - start_time)
    m, s = elapsed_total // 60, elapsed_total % 60
    print(f"\r  [{'█' * 20}] 100%  fertig in {m}m {s:02d}s                        ")

    return segments, info.language


# ---------------------------------------------------------------------------
# Speaker detection
# ---------------------------------------------------------------------------

_SPEAKER_PREFIX_RE = re.compile(r"^([A-Z][a-zA-Zäöüÿ\-\s]{1,30}):\s+(.*)")


def detect_speakers(segments: list[Segment]) -> list[Segment]:
    """
    Heuristic speaker diarization:
    1. If a segment text starts with 'Name: …', extract that as the speaker.
    2. Otherwise, assign a new "Speaker N" label when the gap to the previous
       segment exceeds 2 seconds (indicating a turn change).

    ★ This is a heuristic, not true diarization. For accurate speaker labels,
       install pyannote-audio (heavy GPU dependency, not included here).
    """
    current_speaker = "Speaker 1"
    speaker_counter = 1
    last_end: float = 0.0
    GAP_THRESHOLD = 2.0  # seconds

    result: list[Segment] = []
    for seg in segments:
        m = _SPEAKER_PREFIX_RE.match(seg.text)
        if m:
            current_speaker = m.group(1).strip()
            seg = Segment(
                start=seg.start,
                end=seg.end,
                text=m.group(2).strip(),
                speaker=current_speaker,
            )
        else:
            gap = seg.start - last_end
            if gap > GAP_THRESHOLD and last_end > 0:
                speaker_counter += 1
                current_speaker = f"Speaker {speaker_counter}"
            seg = Segment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                speaker=current_speaker,
            )
        last_end = seg.end
        result.append(seg)

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_transcript(
    video_id: str,
    use_whisper_fallback: bool = True,
    whisper_model: str = "base",
    cache_audio_dir: Path | None = None,
) -> Transcript:
    """
    Primary entry: YouTube subtitles first, Whisper fallback.
    Raises TranscriptError if neither works.
    """
    from .cache import cache_dir as get_cache_dir

    print(f"  Metadaten werden geladen…")
    meta = fetch_video_meta(video_id)
    from .output import format_ts
    dur_str = format_ts(meta.duration)
    print(f"  \"{meta.title}\" ({meta.channel}, {dur_str})")

    print("  Suche nach YouTube-Untertiteln…")
    result = fetch_youtube_subtitles(video_id)

    if result is not None:
        segments, language, source = result
        source_label = "manuelle Untertitel" if source == "manual_subtitles" else "automatische Untertitel"
        print(f"  Untertitel gefunden: {source_label} ({language}), {len(segments)} Segmente.")
        segments = detect_speakers(segments)
        return Transcript(meta=meta, language=language, segments=segments, source=source)

    if not use_whisper_fallback:
        raise TranscriptError(
            "Keine Untertitel verfügbar und --no-whisper ist gesetzt.\n"
            "Ohne --no-whisper wird automatisch Whisper als Fallback genutzt."
        )

    print("  Keine Untertitel gefunden — Fallback auf Whisper-Transkription.")
    print(f"  Hinweis: Bei {dur_str} Videolänge kann das einige Minuten dauern.")
    audio_cache = cache_audio_dir or (get_cache_dir() / "audio")
    audio_cache.mkdir(parents=True, exist_ok=True)

    print("  Audio wird heruntergeladen…")
    audio_path = download_audio(video_id, audio_cache)
    print(f"  Audio gespeichert: {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)")

    segments, language = transcribe_with_whisper(audio_path, model_size=whisper_model)
    segments = detect_speakers(segments)
    print(f"  Transkription abgeschlossen: {len(segments)} Segmente, Sprache: {language}")

    return Transcript(meta=meta, language=language, segments=segments, source="whisper")
