"""Tests for URL parsing and audio cleanup in transcript.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ytsum.transcript import extract_video_id


class TestExtractVideoId:
    def test_watch_url(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_watch_url_with_extra_params(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42&list=PLxyz") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url_with_params(self):
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=30") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_bare_id(self):
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_id_with_hyphens_and_underscores(self):
        assert extract_video_id("https://youtu.be/abc-def_ghi") == "abc-def_ghi"

    def test_strips_whitespace(self):
        assert extract_video_id("  https://youtu.be/dQw4w9WgXcQ  ") == "dQw4w9WgXcQ"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            extract_video_id("https://vimeo.com/12345")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            extract_video_id("")

    def test_partial_url_raises(self):
        with pytest.raises(ValueError):
            extract_video_id("youtube.com/watch")


# ---------------------------------------------------------------------------
# Audio cleanup tests — keep_audio flag
# ---------------------------------------------------------------------------

_FAKE_META = MagicMock(duration=120, title="Test", channel="TestCh")
_FAKE_TRANSCRIPT_DATA = (
    [MagicMock(start=0.0, end=1.0, text="Hello")],
    "en",
    "auto_subtitles",
)
_FAKE_WHISPER_RESULT = (
    [MagicMock(start=0.0, end=1.0, text="Hello", speaker=None)],
    "en",
)


def _make_audio_file(tmp_path: Path) -> Path:
    """Create a fake audio file in tmp_path and return its path."""
    audio = tmp_path / "dQw4w9WgXcQ.webm"
    audio.write_bytes(b"fake audio")
    return audio


def _base_patches(tmp_path: Path, whisper_side_effect=None):
    """Return a list of patches for all external I/O in get_transcript."""
    audio_path = _make_audio_file(tmp_path)
    whisper_return = {"return_value": _FAKE_WHISPER_RESULT} if whisper_side_effect is None else {"side_effect": whisper_side_effect}
    return audio_path, [
        patch("ytsum.transcript.fetch_video_meta", return_value=_FAKE_META),
        patch("ytsum.transcript.fetch_youtube_subtitles", return_value=None),
        patch("ytsum.transcript.download_audio", return_value=audio_path),
        patch("ytsum.transcript.transcribe_with_whisper", **whisper_return),
        patch("ytsum.transcript.detect_speakers", side_effect=lambda s: s),
    ]


@pytest.fixture()
def mock_whisper_deps(tmp_path):
    """Patch all external I/O so get_transcript runs without network/GPU."""
    audio_path, patches = _base_patches(tmp_path)
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        yield audio_path


class TestKeepAudio:
    def test_default_deletes_audio(self, mock_whisper_deps, tmp_path):
        """Default (keep_audio=False): audio file must not exist after transcription."""
        from ytsum.transcript import get_transcript

        audio_path = mock_whisper_deps
        # Pass cache_audio_dir=tmp_path to bypass the internal get_cache_dir call
        get_transcript("dQw4w9WgXcQ", cache_audio_dir=tmp_path)
        assert not audio_path.exists(), "Audio should be deleted by default"

    def test_keep_audio_retains_file(self, mock_whisper_deps, tmp_path):
        """keep_audio=True: audio file must still exist after transcription."""
        from ytsum.transcript import get_transcript

        audio_path = mock_whisper_deps
        get_transcript("dQw4w9WgXcQ", keep_audio=True, cache_audio_dir=tmp_path)
        assert audio_path.exists(), "Audio should be kept when --keep-audio is set"

    def test_audio_deleted_on_transcription_error(self, tmp_path):
        """Even if transcribe_with_whisper raises, audio must be cleaned up."""
        from ytsum.transcript import get_transcript

        audio_path, patches = _base_patches(tmp_path, whisper_side_effect=RuntimeError("GPU OOM"))
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with pytest.raises(RuntimeError, match="GPU OOM"):
                get_transcript("dQw4w9WgXcQ", cache_audio_dir=tmp_path)
        assert not audio_path.exists(), "Audio must be deleted even when transcription fails"

    def test_keep_audio_preserved_on_error(self, tmp_path):
        """With keep_audio=True, audio is kept even if transcription raises."""
        from ytsum.transcript import get_transcript

        audio_path, patches = _base_patches(tmp_path, whisper_side_effect=RuntimeError("GPU OOM"))
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with pytest.raises(RuntimeError):
                get_transcript("dQw4w9WgXcQ", keep_audio=True, cache_audio_dir=tmp_path)
        assert audio_path.exists(), "Audio should be retained on error when keep_audio=True"

    def test_argparse_keep_audio_default_false(self):
        """--keep-audio not specified → args.keep_audio is False."""
        import sys
        from unittest.mock import patch as _patch

        with _patch("sys.argv", ["ytsum", "https://youtu.be/dQw4w9WgXcQ"]):
            from ytsum.cli import parse_args
            args = parse_args()
        assert args.keep_audio is False

    def test_argparse_keep_audio_true(self):
        """--keep-audio specified → args.keep_audio is True."""
        from unittest.mock import patch as _patch

        with _patch("sys.argv", ["ytsum", "--keep-audio", "https://youtu.be/dQw4w9WgXcQ"]):
            from ytsum.cli import parse_args
            args = parse_args()
        assert args.keep_audio is True
