"""Tests for URL parsing in transcript.py."""

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
