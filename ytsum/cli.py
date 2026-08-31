"""argparse entry point + top-level pipeline orchestration."""

import argparse
import os
import sys
import time
from pathlib import Path

from .cache import load_analysis, load_transcript, save_analysis, save_transcript
from .llm import PROVIDERS, analyze_video, default_model_for
from .models import NetworkError, TranscriptError
from .output import render_json, render_markdown, render_terminal, save_to_file
from .profile import ProfileError, load_profile, profile_hash
from .transcript import extract_video_id, get_transcript


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    provider_names = list(PROVIDERS.keys())

    parser = argparse.ArgumentParser(
        prog="ytsum",
        description="Summarise YouTube videos against your interest profile.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ytsum https://www.youtube.com/watch?v=VIDEO_ID
  ytsum <url> --provider anthropic --model claude-sonnet-4-6
  ytsum <url> --provider groq
  ytsum <url> --provider ollama --model llama3.2
  ytsum <url> --json --save
  ytsum <url> --no-cache
""",
    )
    parser.add_argument(
        "urls",
        nargs="+",
        metavar="URL",
        help="YouTube URL(s) to analyse (watch?v=, youtu.be/, /shorts/)",
    )
    parser.add_argument(
        "--provider",
        default="gemini",
        choices=provider_names,
        help="LLM provider (default: gemini). Env vars: GEMINI_API_KEY / ANTHROPIC_API_KEY / GROQ_API_KEY",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Model ID (default: provider's default, e.g. gemini-3.6-flash)",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("interests.yaml"),
        metavar="PATH",
        help="Path to interests.yaml (default: ./interests.yaml)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="JSON output instead of terminal view (--vault is ignored with JSON)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save locally immediately without prompting (./out/<date-channel-title>.md)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip reading and writing the local cache",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        metavar="SIZE",
        choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
        help="Whisper model size for audio fallback (default: base)",
    )
    parser.add_argument(
        "--no-whisper",
        action="store_true",
        help="Fail if no subtitles — do not fall back to Whisper",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep downloaded audio file after Whisper transcription (default: delete after use). "
             "No effect when YouTube subtitles are found or --no-whisper is set. "
             "File is kept at ~/.cache/ytsum/audio/<id>.<ext>",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=None,
        metavar="PATH",
        help='Obsidian vault root — saves to <vault>/YouTube Notes/ with YAML frontmatter',
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=None,
        metavar="PATH",
        help="Custom LLM prompt template (default: bundled prompts/analysis.md)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Per-video pipeline
# ---------------------------------------------------------------------------

def _step(n: int, total: int, label: str) -> float:
    """Schritt-Header ausgeben und Startzeit zurückgeben."""
    print(f"\n  ── Schritt {n}/{total}: {label}", file=sys.stderr)
    return time.time()


def _ok(t0: float, detail: str = "") -> None:
    elapsed = time.time() - t0
    suffix = f"  ({detail})" if detail else ""
    print(f"     ✓ fertig in {elapsed:.1f}s{suffix}", file=sys.stderr)


def process_video(url: str, args: argparse.Namespace, profile) -> int:
    """Full pipeline for one URL. Returns exit code: 0 = ok, 1 = error."""
    try:
        video_id = extract_video_id(url)
    except ValueError as e:
        print(f"[FEHLER] {e}", file=sys.stderr)
        return 1

    phash = profile_hash(profile)
    use_cache = not args.no_cache
    model = args.model or default_model_for(args.provider)

    print(f"\n{'━' * 60}", file=sys.stderr)
    print(f"  URL:      {url}", file=sys.stderr)
    print(f"  Anbieter: {args.provider}  |  Modell: {model}", file=sys.stderr)
    print(f"{'━' * 60}", file=sys.stderr)

    # ----- Schritt 1: Transkript -----
    transcript = None
    if use_cache:
        transcript = load_transcript(video_id)
        if transcript:
            print(f"\n  ── Schritt 1/3: Transkript", file=sys.stderr)
            print(f"     ✓ Cache-Treffer — Transkript wird wiederverwendet.", file=sys.stderr)

    if transcript is None:
        t0 = _step(1, 3, "Transkript laden")
        try:
            transcript = get_transcript(
                video_id,
                use_whisper_fallback=not args.no_whisper,
                whisper_model=args.whisper_model,
                keep_audio=args.keep_audio,
            )
        except TranscriptError as e:
            print(f"\n[FEHLER] {e}", file=sys.stderr)
            return 1
        except NetworkError as e:
            print(f"\n[NETZWERKFEHLER] {e}", file=sys.stderr)
            return 1
        except ImportError as e:
            print(f"\n[ABHÄNGIGKEIT FEHLT] {e}", file=sys.stderr)
            return 1

        seg_count = len(transcript.segments)
        if use_cache:
            save_transcript(transcript)
            _ok(t0, f"{seg_count} Segmente gespeichert")
        else:
            _ok(t0, f"{seg_count} Segmente")

    # ----- Schritt 2: Analyse -----
    analysis = None
    cost = None
    if use_cache:
        cached = load_analysis(video_id, phash)
        if cached:
            analysis, cost = cached
            print(f"\n  ── Schritt 2/3: KI-Analyse", file=sys.stderr)
            print(f"     ✓ Cache-Treffer — Analyse wird wiederverwendet.", file=sys.stderr)

    if analysis is None:
        t0 = _step(2, 3, f"KI-Analyse mit {model}")
        try:
            analysis, cost = analyze_video(
                transcript,
                profile,
                model=model,
                provider=args.provider,
                prompt_path=args.prompt,
            )
        except (EnvironmentError, ImportError) as e:
            print(f"\n[KONFIGURATIONSFEHLER] {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"\n[API-FEHLER] {e}", file=sys.stderr)
            return 1

        if use_cache:
            save_analysis(video_id, phash, analysis, cost)
        _ok(t0, f"{cost.input_tokens:,} Tokens → ${cost.estimated_cost_usd:.4f}")

    # ----- Schritt 3: Ausgabe -----
    _step(3, 3, "Ergebnis")
    print()

    if args.output_json:
        # JSON: direkt ausgeben, optional speichern
        output = render_json(transcript, analysis, cost)
        print(output)
        if args.save:
            path = save_to_file(transcript, analysis, output)
            print(f"\n  Gespeichert: {path}", file=sys.stderr)
    else:
        # Terminal: saubere Ansicht
        print(render_terminal(transcript, analysis, cost))

        # Interaktiv fragen: lokal, Vault oder beides?
        save_local, save_vault = _ask_where_to_save(
            score=analysis.relevance_score,
            force_local=args.save,
            vault=args.vault,
        )

        if save_local:
            md_content = render_markdown(transcript, analysis, cost, language=profile.language)
            path = save_to_file(transcript, analysis, md_content)
            print(f"\n  Lokal gespeichert:    {path}", file=sys.stderr)

        if save_vault:
            vault_dir = args.vault / "YouTube Notes"
            md_vault = render_markdown(transcript, analysis, cost, with_frontmatter=True, language=profile.language)
            path = save_to_file(transcript, analysis, md_vault, output_dir=vault_dir)
            print(f"\n  Vault gespeichert: {path}", file=sys.stderr)

    return 0


def _ask_where_to_save(
    score: int,
    force_local: bool,
    vault: "Path | None",
) -> "tuple[bool, bool]":
    """
    Fragt interaktiv wo die Analyse gespeichert werden soll.
    Gibt (save_local, save_vault) zurück.
    """
    hint = ""
    if score >= 7:
        hint = "  ★ Relevanz hoch"
    elif score <= 3:
        hint = "  (Relevanz niedrig)"

    if vault is None:
        # Kein Vault konfiguriert — nur lokale Abfrage
        if force_local:
            return True, False
        try:
            answer = input(f"\n  Lokal speichern (./out/)?{hint} [j/n]: ").strip().lower()
            return answer in ("j", "ja", "y", "yes"), False
        except (EOFError, KeyboardInterrupt):
            return False, False

    # Vault konfiguriert — erweiterte Auswahl anzeigen
    if force_local:
        # --save gesetzt → lokal direkt, Vault noch fragen
        try:
            answer = input(f"\n  Auch in Vault speichern?{hint} [j/n]: ").strip().lower()
            return True, answer in ("j", "ja", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            return True, False

    try:
        prompt = (
            f"\n  Speichern?{hint}\n"
            "    [1] Lokal (./out/)\n"
            "    [2] Vault (YouTube Notes/)\n"
            "    [3] Beides\n"
            "    [n] Nein\n"
            "  Eingabe: "
        )
        answer = input(prompt).strip().lower()
        save_local = answer in ("1", "3")
        save_vault = answer in ("2", "3")
        return save_local, save_vault
    except (EOFError, KeyboardInterrupt):
        return False, False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    """Load .env from CWD if it exists (no hard dependency on python-dotenv)."""
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:   # don't overwrite existing env vars
            os.environ[key] = value


def main() -> None:
    """Registered in pyproject.toml as the 'ytsum' command."""
    _load_dotenv()

    args = parse_args()

    # YTSUM_VAULT env var als Fallback wenn --vault nicht angegeben
    if args.vault is None and os.environ.get("YTSUM_VAULT"):
        args.vault = Path(os.environ["YTSUM_VAULT"])

    # Validate API key for the chosen provider early
    cfg = PROVIDERS[args.provider]
    key_env = cfg.get("api_key_env")
    if key_env and not os.environ.get(key_env):
        print(
            f"[FEHLER] {key_env} ist nicht gesetzt.\n"
            f"In die .env Datei eintragen oder exportieren:\n"
            f"  export {key_env}=dein-api-key",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        profile = load_profile(args.profile)
    except ProfileError as e:
        print(f"[PROFIL-FEHLER] {e}", file=sys.stderr)
        sys.exit(1)

    exit_codes: list[int] = []
    for url in args.urls:
        try:
            code = process_video(url, args, profile)
        except Exception as e:
            print(f"[UNERWARTETER FEHLER] {e}", file=sys.stderr)
            code = 1
        exit_codes.append(code)

    sys.exit(max(exit_codes))


if __name__ == "__main__":
    main()
