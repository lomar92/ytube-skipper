"""Markdown + JSON rendering and file saving."""

import dataclasses
import json
import re
import textwrap
import unicodedata
from pathlib import Path

from .models import Analysis, CostReport, Transcript


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_ts(seconds: float) -> str:
    """123.4 -> '2:03'  or  '1:02:03' for >= 1 hour."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def youtube_link(video_id: str, seconds: float) -> str:
    return f"https://youtu.be/{video_id}?t={int(seconds)}"


# ---------------------------------------------------------------------------
# Shared label tables (Deutsch)
# ---------------------------------------------------------------------------

_VERDICT_LABEL_DE = {
    "watch":              "▶  Komplett anschauen",
    "watch_sections":     "⏩  Ausgewählte Abschnitte anschauen",
    "summary_sufficient": "📄  Zusammenfassung reicht — Video überspringen",
    "skip":               "⏭  Überspringen",
}

_VERDICT_LABEL_MD_EN = {
    "watch":              "Watch in full",
    "watch_sections":     "Watch selected sections",
    "summary_sufficient": "Summary sufficient — skip the video",
    "skip":               "Skip entirely",
}

_VERDICT_LABEL_MD_DE = {
    "watch":              "Komplett anschauen",
    "watch_sections":     "Ausgewählte Abschnitte anschauen",
    "summary_sufficient": "Zusammenfassung reicht — Video überspringen",
    "skip":               "Überspringen",
}

# Section headers per language (fallback: English)
_MD_HEADERS: dict[str, dict[str, str]] = {
    "Deutsch": {
        "verdict":     "Bewertung",
        "relevance":   "Relevanz",
        "time_saving": "Zeitvorteil",
        "thesis":      "Kernaussage",
        "points":      "Wichtigste Punkte",
        "relevant":    "Relevant für dich",
        "skip":        "Abschnitte überspringen",
        "visuals":     "Visuelle Inhalte",
        "no_points":   "_Keine Punkte extrahiert._",
        "no_relevant": "_Keine Profilübereinstimmungen._",
        "no_skip":     "_Keine Abschnitte markiert._",
        "footer":      "Analyse",
    },
    "English": {
        "verdict":     "Verdict",
        "relevance":   "Relevance",
        "time_saving": "Time Saving",
        "thesis":      "Core Thesis",
        "points":      "Key Points",
        "relevant":    "Relevant for You",
        "skip":        "Sections to Skip",
        "visuals":     "Visual Content",
        "no_points":   "_No key points extracted._",
        "no_relevant": "_No profile matches found._",
        "no_skip":     "_No sections marked._",
        "footer":      "Analysis",
    },
}


def _md_labels(language: str) -> dict[str, str]:
    """Return section header strings for the given language (falls back to English)."""
    return _MD_HEADERS.get(language, _MD_HEADERS["English"])


def _verdict_label_md(verdict: str, language: str) -> str:
    if language == "Deutsch":
        return _VERDICT_LABEL_MD_DE.get(verdict, verdict)
    return _VERDICT_LABEL_MD_EN.get(verdict, verdict)

_VERDICT_EMOJI = {
    "watch": "▶", "watch_sections": "⏩",
    "summary_sufficient": "📄", "skip": "⏭",
}


# ---------------------------------------------------------------------------
# Terminal renderer (keine Markdown-Syntax, sauber lesbar im CLI)
# ---------------------------------------------------------------------------

_W = 64   # Ausgabebreite
_SEP = "━" * _W
_SEP_THIN = "─" * _W


def _wrap(text: str, indent: int = 4) -> list[str]:
    prefix = " " * indent
    return [f"{prefix}{line}" for line in textwrap.wrap(text, width=_W - indent)]


def render_terminal(
    transcript: Transcript,
    analysis: Analysis,
    cost: CostReport,
) -> str:
    """Saubere Terminal-Ausgabe ohne Markdown-Syntax."""
    meta = transcript.meta
    verdict_label = _VERDICT_LABEL_DE.get(analysis.verdict, analysis.verdict)

    lines: list[str] = [
        _SEP,
        f"  {meta.title}",
        f"  {meta.channel}  ·  {format_ts(meta.duration)}  ·  {meta.upload_date}",
        _SEP,
        "",
        f"  BEWERTUNG     {verdict_label}",
        f"  Relevanz      {analysis.relevance_score}/10  —  {analysis.relevance_reason}",
        f"  Zeitvorteil   {analysis.time_saving}",
        "",
        f"  {_SEP_THIN}",
        "  KERNAUSSAGE",
        "",
        *_wrap(analysis.core_thesis),
        "",
        f"  {_SEP_THIN}",
        "  WICHTIGSTE PUNKTE",
        "",
    ]

    if analysis.key_points:
        for i, kp in enumerate(analysis.key_points, 1):
            ts_str = format_ts(kp.timestamp)
            # Erste Zeile mit Nummer und Zeitstempel
            prefix = f"  {i:2d}. [{ts_str}]  "
            wrap_width = _W - len(prefix)
            wrapped = textwrap.wrap(kp.thesis, width=max(wrap_width, 20))
            lines.append(f"{prefix}{wrapped[0] if wrapped else ''}")
            indent_cont = " " * len(prefix)
            for part in wrapped[1:]:
                lines.append(f"{indent_cont}{part}")
            lines.append(f"{indent_cont}{kp.youtube_link}")
            lines.append("")
    else:
        lines.append("    Keine Punkte extrahiert.")
        lines.append("")

    lines += [f"  {_SEP_THIN}", "  RELEVANT FÜR DICH", ""]
    if analysis.relevant_for_you:
        first_prefix = "    · "
        cont_prefix  = "      "
        for item in analysis.relevant_for_you:
            wrapped = textwrap.wrap(item, width=_W - len(first_prefix))
            if wrapped:
                lines.append(f"{first_prefix}{wrapped[0]}")
                for part in wrapped[1:]:
                    lines.append(f"{cont_prefix}{part}")
    else:
        lines.append("    Keine Profilübereinstimmungen gefunden.")
    lines.append("")

    if analysis.skip_ranges:
        lines += [f"  {_SEP_THIN}", "  ABSCHNITTE ÜBERSPRINGEN", ""]
        for sr in analysis.skip_ranges:
            lines.append(f"    · {format_ts(sr.start)} – {format_ts(sr.end)}  →  {sr.reason}")
        lines.append("")

    if analysis.visuals_only:
        lines += [f"  {_SEP_THIN}", "  VISUELLE INHALTE (wichtig)", ""]
        lines.extend(_wrap(analysis.visuals_only))
        lines.append("")

    lines += [
        _SEP,
        f"  {cost.model}  ·  ${cost.estimated_cost_usd:.4f} USD"
        f"  ·  {cost.input_tokens:,} / {cost.output_tokens:,} Tokens",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown renderer (für gespeicherte Dateien)
# ---------------------------------------------------------------------------

def render_markdown(
    transcript: Transcript,
    analysis: Analysis,
    cost: CostReport,
    with_frontmatter: bool = False,
    language: str = "Deutsch",
) -> str:
    """Full Markdown for saved .md files.
    with_frontmatter=True prepends Obsidian YAML frontmatter.
    language controls section headers and verdict labels."""
    meta = transcript.meta
    h = _md_labels(language)
    verdict_emoji = _VERDICT_EMOJI.get(analysis.verdict, "?")
    verdict_label = _verdict_label_md(analysis.verdict, language)

    lines: list[str] = [
        f"# {meta.title}",
        "",
        f"**Channel:** {meta.channel}  ",
        f"**Duration:** {format_ts(meta.duration)}  ",
        f"**Uploaded:** {meta.upload_date}  ",
        f"**URL:** {meta.url}  ",
        f"**Transcript:** {transcript.source.replace('_', ' ')}  ",
        f"**Language:** {transcript.language}",
        "",
        "---",
        "",
        f"## {verdict_emoji} {h['verdict']}: {verdict_label}",
        "",
        f"**{h['relevance']}:** {analysis.relevance_score}/10 — {analysis.relevance_reason}  ",
        f"**{h['time_saving']}:** {analysis.time_saving}",
        "",
        f"## {h['thesis']}",
        "",
        analysis.core_thesis,
        "",
        f"## {h['points']}",
        "",
    ]

    if analysis.key_points:
        for kp in analysis.key_points:
            ts_str = format_ts(kp.timestamp)
            lines.append(f"- **[{ts_str}]({kp.youtube_link})** — {kp.thesis}")
    else:
        lines.append(h["no_points"])
    lines.append("")

    lines += [f"## {h['relevant']}", ""]
    if analysis.relevant_for_you:
        for item in analysis.relevant_for_you:
            lines.append(f"- {item}")
    else:
        lines.append(h["no_relevant"])
    lines.append("")

    lines += [f"## {h['skip']}", ""]
    if analysis.skip_ranges:
        for sr in analysis.skip_ranges:
            lines.append(f"- **{format_ts(sr.start)} – {format_ts(sr.end)}** — {sr.reason}")
    else:
        lines.append(h["no_skip"])
    lines.append("")

    if analysis.visuals_only:
        lines += [f"## {h['visuals']}", "", f"> {analysis.visuals_only}", ""]

    lines += [
        "---",
        "",
        f"*{h['footer']}: {cost.model} · "
        f"${cost.estimated_cost_usd:.4f} USD · "
        f"{cost.input_tokens:,} in / {cost.output_tokens:,} out*",
    ]

    body = "\n".join(lines)
    if with_frontmatter:
        return _obsidian_frontmatter(transcript, analysis) + body
    return body


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------

def render_json(
    transcript: Transcript,
    analysis: Analysis,
    cost: CostReport,
) -> str:
    payload = {
        "transcript": dataclasses.asdict(transcript),
        "analysis": dataclasses.asdict(analysis),
        "cost": dataclasses.asdict(cost),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Filename slug generation
# ---------------------------------------------------------------------------

def _slugify(text: str, max_len: int = 45) -> str:
    """Wandelt beliebigen Text in einen Dateisystem-sicheren Slug um."""
    # Deutsche Umlaute explizit auflösen
    for src, dst in [("ä","ae"),("ö","oe"),("ü","ue"),("Ä","ae"),("Ö","oe"),("Ü","ue"),("ß","ss")]:
        text = text.replace(src, dst)
    # Unicode-Akzente entfernen (NFD-Normalisierung)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    # Alles außer Buchstaben/Ziffern → Bindestrich
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "video"


def _obsidian_frontmatter(transcript: Transcript, analysis: Analysis) -> str:
    """Generiert Obsidian-kompatibles YAML Frontmatter mit Tags."""
    tags: list[str] = ["youtube"]
    channel_tag = _slugify(transcript.meta.channel, max_len=20)
    if channel_tag:
        tags.append(channel_tag)
    for item in analysis.relevant_for_you:
        # Format: "[Thema]: was das Video sagt" oder "- Thema: ..."
        topic = item.split(":")[0].strip().lstrip("-•* []")
        slug = _slugify(topic, max_len=20)
        if slug and slug not in tags:
            tags.append(slug)
    tag_list = ", ".join(f'"{t}"' for t in tags)
    return (
        "---\n"
        f"tags: [{tag_list}]\n"
        f"kanal: \"{transcript.meta.channel}\"\n"
        f"datum: {transcript.meta.upload_date}\n"
        f"url: {transcript.meta.url}\n"
        f"relevanz: {analysis.relevance_score}/10\n"
        f"verdict: {analysis.verdict}\n"
        "---\n\n"
    )


def _build_filename(transcript: Transcript, analysis: Analysis) -> str:
    """
    Baut einen sprechenden Dateinamen aus Datum, Kanal und Kernaussage.
    Format: YYYY-MM-DD_kanal_kernaussage
    Fallback auf video_id falls core_thesis leer.
    """
    date = transcript.meta.upload_date or "0000-00-00"
    channel = _slugify(transcript.meta.channel, max_len=20)

    # Erste Satz der Kernaussage als Inhaltstitel
    thesis = analysis.core_thesis.split(".")[0] if analysis.core_thesis else ""
    if thesis:
        content = _slugify(thesis, max_len=50)
    else:
        content = transcript.meta.video_id

    return f"{date}_{channel}_{content}"


# ---------------------------------------------------------------------------
# File saving
# ---------------------------------------------------------------------------

def save_to_file(
    transcript: Transcript,
    analysis: Analysis,
    content: str,
    output_dir: Path = Path("out"),
) -> Path:
    """Schreibt in <output_dir>/<sprechender-name>.md (oder .json)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = "json" if content.lstrip().startswith("{") else "md"
    filename = _build_filename(transcript, analysis)
    path = output_dir / f"{filename}.{ext}"
    path.write_text(content, encoding="utf-8")
    return path
