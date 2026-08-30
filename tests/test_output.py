"""Tests for output helpers: slugify, filename generation, timestamp formatting."""

import pytest
from ytsum.output import _slugify, format_ts


class TestSluggify:
    def test_basic_ascii(self):
        assert _slugify("Hello World") == "hello-world"

    def test_german_umlauts(self):
        assert _slugify("Über den Dächern") == "ueber-den-daechern"

    def test_sharp_s(self):
        assert _slugify("Straße") == "strasse"

    def test_special_chars_become_hyphens(self):
        assert _slugify("AI & LLMs: What's Next?") == "ai-llms-what-s-next"

    def test_max_len_respected(self):
        long = "a" * 100
        result = _slugify(long, max_len=20)
        assert len(result) <= 20

    def test_no_leading_trailing_hyphens(self):
        result = _slugify("  ---test---  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_empty_string_returns_video(self):
        assert _slugify("") == "video"

    def test_only_special_chars_returns_video(self):
        assert _slugify("!@#$%") == "video"

    def test_unicode_accents_stripped(self):
        result = _slugify("café résumé")
        assert result == "cafe-resume"


class TestFormatTs:
    def test_minutes_and_seconds(self):
        assert format_ts(123) == "2:03"

    def test_zero(self):
        assert format_ts(0) == "0:00"

    def test_exactly_one_hour(self):
        assert format_ts(3600) == "1:00:00"

    def test_hours_minutes_seconds(self):
        assert format_ts(3661) == "1:01:01"

    def test_sub_minute(self):
        assert format_ts(45) == "0:45"

    def test_leading_zero_on_seconds(self):
        assert format_ts(61) == "1:01"
