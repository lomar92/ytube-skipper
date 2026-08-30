"""Tests for XML response parsing in llm.py."""

import pytest
from ytsum.llm import parse_llm_response


# Minimal valid LLM response
_VALID_RESPONSE = """
<verdict>watch_sections</verdict>
<relevance_score>7</relevance_score>
<relevance_reason>Covers AI safety topics highly relevant to the profile.</relevance_reason>
<time_saving>20 of 60 minutes are directly relevant</time_saving>
<core_thesis>The speaker argues that current LLMs are fundamentally unsafe because alignment is unsolved. She cites several failure modes observed in production deployments. The audience reaction was sceptical but engaged.</core_thesis>
<key_points>
<point>
<thesis>Ilya argues that reward hacking is the central unsolved problem in alignment.</thesis>
<timestamp>120</timestamp>
</point>
<point>
<thesis>Audience member challenges the speaker on whether RLHF mitigates the core risks.</thesis>
<timestamp>350</timestamp>
</point>
</key_points>
<relevant_for_you>
- [AI Safety]: Speaker covers reward hacking and alignment failure modes in depth
- [LLMs]: Discusses production deployment failures
</relevant_for_you>
<skip_ranges>
<range>
<start>0</start>
<end>60</end>
<reason>intro</reason>
</range>
</skip_ranges>
<visuals_only>None.</visuals_only>
"""


class TestParseLlmResponse:
    def test_verdict_parsed(self):
        analysis = parse_llm_response(_VALID_RESPONSE, "dQw4w9WgXcQ", 3600)
        assert analysis.verdict == "watch_sections"

    def test_relevance_score_clamped(self):
        analysis = parse_llm_response(_VALID_RESPONSE, "dQw4w9WgXcQ", 3600)
        assert 0 <= analysis.relevance_score <= 10
        assert analysis.relevance_score == 7

    def test_key_points_count(self):
        analysis = parse_llm_response(_VALID_RESPONSE, "dQw4w9WgXcQ", 3600)
        assert len(analysis.key_points) == 2

    def test_key_point_youtube_link(self):
        analysis = parse_llm_response(_VALID_RESPONSE, "dQw4w9WgXcQ", 3600)
        kp = analysis.key_points[0]
        assert kp.youtube_link == "https://youtu.be/dQw4w9WgXcQ?t=120"
        assert kp.timestamp == 120.0

    def test_skip_ranges_parsed(self):
        analysis = parse_llm_response(_VALID_RESPONSE, "dQw4w9WgXcQ", 3600)
        assert len(analysis.skip_ranges) == 1
        assert analysis.skip_ranges[0].start == 0
        assert analysis.skip_ranges[0].end == 60
        assert analysis.skip_ranges[0].reason == "intro"

    def test_visuals_none_string_becomes_none(self):
        analysis = parse_llm_response(_VALID_RESPONSE, "dQw4w9WgXcQ", 3600)
        assert analysis.visuals_only is None

    def test_relevant_for_you_stripped(self):
        analysis = parse_llm_response(_VALID_RESPONSE, "dQw4w9WgXcQ", 3600)
        assert len(analysis.relevant_for_you) == 2
        assert analysis.relevant_for_you[0].startswith("[AI Safety]")

    def test_invalid_verdict_falls_back(self):
        bad = _VALID_RESPONSE.replace("<verdict>watch_sections</verdict>", "<verdict>nonsense</verdict>")
        analysis = parse_llm_response(bad, "dQw4w9WgXcQ", 3600)
        assert analysis.verdict == "summary_sufficient"

    def test_missing_score_falls_back(self):
        bad = _VALID_RESPONSE.replace("<relevance_score>7</relevance_score>", "<relevance_score>abc</relevance_score>")
        analysis = parse_llm_response(bad, "dQw4w9WgXcQ", 3600)
        assert analysis.relevance_score == 5

    def test_empty_response_returns_defaults(self):
        analysis = parse_llm_response("", "dQw4w9WgXcQ", 3600)
        assert analysis.verdict == "summary_sufficient"
        assert analysis.key_points == []
        assert analysis.skip_ranges == []

    def test_video_id_stored(self):
        analysis = parse_llm_response(_VALID_RESPONSE, "dQw4w9WgXcQ", 3600)
        assert analysis.video_id == "dQw4w9WgXcQ"

    def test_skip_range_with_none_reason_ignored(self):
        none_range = _VALID_RESPONSE.replace(
            "<reason>intro</reason>", "<reason>None</reason>"
        )
        analysis = parse_llm_response(none_range, "dQw4w9WgXcQ", 3600)
        assert analysis.skip_ranges == []
