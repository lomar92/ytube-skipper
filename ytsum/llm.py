"""LLM API calls (Gemini, Anthropic, Groq, Ollama) + Map-Reduce chunking."""

import os
import re
import sys
from pathlib import Path
from typing import Any

from .models import Analysis, CostReport, KeyPoint, SkipRange, Transcript
from .output import youtube_link
from .profile import Profile, profile_to_prompt_section


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, dict] = {
    "gemini": {
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-3.6-flash",
    },
    "groq": {
        "api_key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
    },
    "ollama": {
        "api_key_env": None,          # no key needed
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.2",
    },
    "anthropic": {
        "api_key_env": "ANTHROPIC_API_KEY",
        "base_url": None,             # native SDK, not OpenAI-compatible
        "default_model": "claude-sonnet-4-6",
    },
}


def default_model_for(provider: str) -> str:
    return PROVIDERS[provider]["default_model"]


# ---------------------------------------------------------------------------
# Pricing table (USD per 1M tokens)
# ---------------------------------------------------------------------------

_PRICING: dict[str, tuple[float, float]] = {
    # Gemini
    "gemini-3.6-flash":  (0.15, 0.60),   # estimated — check ai.google.dev for current pricing
    "gemini-2.5-flash":  (0.15, 0.60),
    "gemini-2.5-pro":    (1.25, 10.00),
    "gemini-2.0-flash":  (0.075, 0.30),
    "gemini-1.5-flash":  (0.075, 0.30),
    # Anthropic
    "claude-opus-4-6":          (15.00, 75.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80,  4.00),
    # Groq (approximate)
    "llama-3.3-70b-versatile":  (0.59, 0.79),
    # Ollama — local, no cost
    "_default":  (0.15, 0.60),   # assume Gemini Flash as fallback
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp_rate, out_rate = _PRICING.get(model, _PRICING["_default"])
    return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000


# ---------------------------------------------------------------------------
# Client factory + unified LLM call
# ---------------------------------------------------------------------------

def _make_client(provider: str) -> Any:
    """Return an SDK client for the given provider."""
    cfg = PROVIDERS[provider]

    if provider == "anthropic":
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic SDK not installed.\n"
                "Install with: pip install anthropic\n"
                "Or switch to Gemini: ytsum <url> --provider gemini"
            )
        return anthropic.Anthropic()

    # OpenAI-compatible providers (Gemini, Groq, Ollama)
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")

    api_key_env = cfg["api_key_env"]
    if api_key_env:
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise EnvironmentError(
                f"{api_key_env} is not set.\n"
                f"Export it: export {api_key_env}=your-key"
            )
    else:
        api_key = "ollama"   # placeholder — Ollama ignores it

    return OpenAI(api_key=api_key, base_url=cfg["base_url"])


def _call_llm(
    prompt: str,
    model: str,
    client: Any,
    provider: str,
    max_tokens: int = 4096,
) -> tuple[str, int, int]:
    """
    Unified LLM call that returns (text, input_tokens, output_tokens).
    Handles both the Anthropic SDK and OpenAI-compatible SDKs.
    """
    if provider == "anthropic":
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return (
            response.content[0].text,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
    else:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""
        in_tok = response.usage.prompt_tokens if response.usage else 0
        out_tok = response.usage.completion_tokens if response.usage else 0
        return text, in_tok, out_tok


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

def load_prompt_template(path: Path | None) -> str:
    if path is not None:
        return path.read_text(encoding="utf-8")
    bundled = Path(__file__).parent / "prompts" / "analysis.md"
    return bundled.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Transcript formatting helpers
# ---------------------------------------------------------------------------

def _format_ts(seconds: float) -> str:
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _segments_to_text(segments: list) -> str:
    lines: list[str] = []
    for seg in segments:
        ts = _format_ts(seg.start)
        speaker = f"[{seg.speaker}] " if seg.speaker else ""
        lines.append(f"[{ts}] {speaker}{seg.text}")
    return "\n".join(lines)


def _video_meta_block(transcript: Transcript) -> str:
    meta = transcript.meta
    return (
        f"Title: {meta.title}\n"
        f"Channel: {meta.channel}\n"
        f"Duration: {_format_ts(meta.duration)} ({meta.duration} seconds)\n"
        f"Upload date: {meta.upload_date}\n"
        f"URL: {meta.url}\n"
        f"Transcript source: {transcript.source.replace('_', ' ')}\n"
        f"Language: {transcript.language}"
    )


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_transcript(
    segments: list,
    max_tokens_per_chunk: int = 80_000,
    overlap_segments: int = 3,
) -> list[list]:
    """Split segments into chunks with slight overlap. 1 token ≈ 4 chars."""
    max_chars = max_tokens_per_chunk * 4
    chunks: list[list] = []
    current: list = []
    current_chars = 0

    for seg in segments:
        seg_chars = len(f"[{_format_ts(seg.start)}] {seg.text}\n")
        if current_chars + seg_chars > max_chars and current:
            chunks.append(current)
            current = current[-overlap_segments:] if len(current) > overlap_segments else current[:]
            current_chars = sum(len(f"[{_format_ts(s.start)}] {s.text}\n") for s in current)
        current.append(seg)
        current_chars += seg_chars

    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Map phase
# ---------------------------------------------------------------------------

def map_chunk(
    chunk: list,
    chunk_idx: int,
    total_chunks: int,
    profile: Profile,
    client: Any,
    model: str,
    provider: str,
) -> tuple[str, int, int]:
    """Summarize one chunk. Returns (summary, input_tokens, output_tokens)."""
    profile_section = profile_to_prompt_section(profile)
    transcript_text = _segments_to_text(chunk)
    start_ts = _format_ts(chunk[0].start)
    end_ts = _format_ts(chunk[-1].end)

    prompt = (
        f"You are summarizing part {chunk_idx + 1} of {total_chunks} of a video transcript.\n"
        f"This chunk covers {start_ts} – {end_ts}.\n\n"
        f"**Important — Output language:** Write your entire response in {profile.language}.\n\n"
        f"{profile_section}\n\n"
        "Focus on content relevant to the above interests. Extract:\n"
        "1. Key claims and arguments (with timestamps in seconds)\n"
        "2. Any skip-worthy sections (sponsors, tangents)\n"
        "3. Any visuals mentioned that are essential to understanding\n\n"
        f"Transcript chunk:\n{transcript_text}\n\n"
        f"Provide a concise but detailed summary in {profile.language}. Include exact timestamps (in seconds) for key moments."
    )
    return _call_llm(prompt, model, client, provider, max_tokens=2048)


# ---------------------------------------------------------------------------
# Reduce phase
# ---------------------------------------------------------------------------

def reduce_summaries(
    chunk_summaries: list[str],
    transcript: Transcript,
    profile: Profile,
    client: Any,
    model: str,
    provider: str,
    prompt_template: str,
) -> tuple[str, int, int]:
    """Merge chunk summaries into final structured analysis."""
    combined = "\n\n---\n\n".join(
        f"[Chunk {i + 1} of {len(chunk_summaries)}]\n{s}"
        for i, s in enumerate(chunk_summaries)
    )
    meta_block = _video_meta_block(transcript)
    profile_section = profile_to_prompt_section(profile)

    prompt = prompt_template.replace("<<VIDEO_META>>", meta_block)
    prompt = prompt.replace("<<USER_PROFILE>>", profile_section)
    prompt = prompt.replace("<<TRANSCRIPT>>", combined)
    prompt = prompt.replace("<<LANGUAGE>>", profile.language)

    return _call_llm(prompt, model, client, provider, max_tokens=8000)


# ---------------------------------------------------------------------------
# XML response parser
# ---------------------------------------------------------------------------

def _extract_tag(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else None


def parse_llm_response(response: str, video_id: str, duration: int) -> Analysis:
    """Extract XML-tagged sections. Falls back gracefully if tags are missing."""
    def get(tag: str) -> str:
        return _extract_tag(response, tag) or ""

    verdict_raw = get("verdict").lower()
    verdict = verdict_raw if verdict_raw in {"watch", "watch_sections", "summary_sufficient", "skip"} else "summary_sufficient"

    try:
        score = max(0, min(10, int(get("relevance_score"))))
    except ValueError:
        score = 5

    key_points: list[KeyPoint] = []
    for m in re.finditer(r"<point>(.*?)</point>", get("key_points"), re.DOTALL):
        pt = m.group(1)
        thesis = _extract_tag(pt, "thesis") or ""
        try:
            ts = float(_extract_tag(pt, "timestamp") or "0")
        except ValueError:
            ts = 0.0
        if thesis:
            key_points.append(KeyPoint(thesis=thesis, timestamp=ts, youtube_link=youtube_link(video_id, ts)))

    relevant_for_you = [
        line.strip().lstrip("•-* ").strip()
        for line in get("relevant_for_you").splitlines()
        if line.strip() and not line.strip().startswith("<")
    ]

    skip_ranges: list[SkipRange] = []
    for m in re.finditer(r"<range>(.*?)</range>", get("skip_ranges"), re.DOTALL):
        rt = m.group(1)
        reason = _extract_tag(rt, "reason") or ""
        try:
            start = float(_extract_tag(rt, "start") or "0")
            end = float(_extract_tag(rt, "end") or "0")
        except ValueError:
            start = end = 0.0
        if reason and reason.lower() != "none" and end > start:
            skip_ranges.append(SkipRange(start=start, end=end, reason=reason))

    visuals = get("visuals_only") or None
    if visuals and visuals.lower().rstrip(".") in {"none", ""}:
        visuals = None

    return Analysis(
        video_id=video_id,
        verdict=verdict,
        relevance_score=score,
        relevance_reason=get("relevance_reason") or "No reason provided.",
        time_saving=get("time_saving") or f"0 of {duration // 60} minutes relevant",
        core_thesis=get("core_thesis") or "Core thesis not extracted.",
        key_points=key_points,
        relevant_for_you=relevant_for_you,
        skip_ranges=skip_ranges,
        visuals_only=visuals,
    )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def analyze_video(
    transcript: Transcript,
    profile: Profile,
    model: str = "gemini-2.5-flash",
    provider: str = "gemini",
    prompt_path: Path | None = None,
) -> tuple[Analysis, CostReport]:
    """Single-pass for short videos; Map-Reduce for longer ones."""
    client = _make_client(provider)
    template = load_prompt_template(prompt_path)

    full_text = _segments_to_text(transcript.segments)
    estimated_tokens = len(full_text) / 4   # 1 token ≈ 4 chars

    SINGLE_PASS_THRESHOLD = 60_000

    if estimated_tokens <= SINGLE_PASS_THRESHOLD:
        print("  Single-pass analysis…", file=sys.stderr)
        meta_block = _video_meta_block(transcript)
        profile_section = profile_to_prompt_section(profile)
        prompt = template.replace("<<VIDEO_META>>", meta_block)
        prompt = prompt.replace("<<USER_PROFILE>>", profile_section)
        prompt = prompt.replace("<<TRANSCRIPT>>", full_text)
        prompt = prompt.replace("<<LANGUAGE>>", profile.language)
        raw, in_tok, out_tok = _call_llm(prompt, model, client, provider, max_tokens=8000)

    else:
        chunks = chunk_transcript(transcript.segments)
        print(f"  Long video — Map-Reduce ({len(chunks)} chunks)…", file=sys.stderr)
        summaries: list[str] = []
        total_in = total_out = 0

        for i, chunk in enumerate(chunks):
            print(
                f"    Chunk {i + 1}/{len(chunks)} ({_format_ts(chunk[0].start)} – {_format_ts(chunk[-1].end)})…",
                file=sys.stderr,
            )
            summary, in_t, out_t = map_chunk(chunk, i, len(chunks), profile, client, model, provider)
            summaries.append(summary)
            total_in += in_t
            total_out += out_t

        print("  Reducing summaries…", file=sys.stderr)
        raw, in_t, out_t = reduce_summaries(summaries, transcript, profile, client, model, provider, template)
        in_tok = total_in + in_t
        out_tok = total_out + out_t

    analysis = parse_llm_response(raw, transcript.meta.video_id, transcript.meta.duration)
    cost = CostReport(
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_cost_usd=compute_cost(model, in_tok, out_tok),
    )
    return analysis, cost
