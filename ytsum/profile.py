"""interests.yaml loading and prompt formatting."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import ProfileError


@dataclass
class Profile:
    high: dict[str, str]          # topic -> comma-separated aspects
    medium: list[str]
    low: list[str]
    always_relevant: list[str]    # Kanal-Namen — immer mindestens 7/10
    keywords: list[str]           # freie Keywords — Score +2 wenn prominent
    language: str                 # Ausgabesprache der Analyse (z.B. "Deutsch")
    _raw: str = field(default="", repr=False)   # raw YAML (für Hashing)


def load_profile(path: Path) -> Profile:
    """Lädt und validiert interests.yaml. Wirft ProfileError bei Fehler."""
    if not path.exists():
        raise ProfileError(
            f"Profil nicht gefunden: {path}\n"
            "Erstelle eine interests.yaml mit 'high', 'medium' und 'low' Sektionen."
        )

    raw = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        raise ProfileError(f"YAML-Fehler in {path}: {e}") from e

    if not isinstance(data, dict):
        raise ProfileError(f"{path}: Oberste Ebene muss ein YAML-Mapping sein.")

    high   = data.get("high") or {}
    medium = data.get("medium") or []
    low    = data.get("low") or []
    always   = data.get("always_relevant") or []
    keywords = data.get("keywords") or []
    lang     = str(data.get("language") or "Deutsch")

    if not isinstance(high, dict):
        raise ProfileError(f"{path}: 'high' muss ein Mapping sein (Thema: Aspekte).")
    if not isinstance(medium, list):
        raise ProfileError(f"{path}: 'medium' muss eine Liste sein.")
    if not isinstance(low, list):
        raise ProfileError(f"{path}: 'low' muss eine Liste sein.")
    if not isinstance(always, list):
        raise ProfileError(f"{path}: 'always_relevant' muss eine Liste sein.")
    if not isinstance(keywords, list):
        raise ProfileError(f"{path}: 'keywords' muss eine Liste sein.")

    if not any([high, medium, low, always, keywords]):
        raise ProfileError(f"{path}: Profil ist leer — mindestens ein Interesse eintragen.")

    return Profile(
        high={str(k): str(v) for k, v in high.items()},
        medium=[str(t) for t in medium],
        low=[str(t) for t in low],
        always_relevant=[str(c) for c in always],
        keywords=[str(k) for k in keywords],
        language=lang,
        _raw=raw,
    )


def profile_to_prompt_section(profile: Profile) -> str:
    """Rendert das Profil als strukturierten Textblock für den LLM-Prompt."""
    lines: list[str] = ["## Interessen-Profil des Nutzers"]

    if profile.always_relevant:
        lines.append("\n### Abonnierte Kanäle (immer relevant):")
        lines.append(
            "Videos von diesen Kanälen sind grundsätzlich relevant (Mindest-Score 7/10), "
            "unabhängig vom genauen Thema des Videos:"
        )
        for channel in profile.always_relevant:
            lines.append(f"- {channel}")

    if profile.high:
        lines.append("\n### Hohe Priorität (maximale Abdeckung, alle Details):")
        for topic, aspects in profile.high.items():
            lines.append(f"- **{topic}**: {aspects}")

    if profile.medium:
        lines.append("\n### Mittlere Priorität (erwähnen wenn klar relevant):")
        for topic in profile.medium:
            lines.append(f"- {topic}")

    if profile.low:
        lines.append("\n### Niedrige Priorität (nur wenn außergewöhnlich bedeutsam):")
        for topic in profile.low:
            lines.append(f"- {topic}")

    if profile.keywords:
        lines.append("\n### Bonus-Keywords (Relevanz +2 Punkte wenn prominent im Video):")
        lines.append(
            "Diese Themen interessieren den Nutzer, sind aber keiner Hauptkategorie zugeordnet. "
            "Erhöhe den Relevanz-Score um 2 Punkte wenn eines dieser Keywords ein zentrales Thema des Videos ist. "
            "Erwähne es in 'relevant_for_you'."
        )
        lines.append(", ".join(profile.keywords))

    return "\n".join(lines)


def profile_hash(profile: Profile) -> str:
    """SHA256 des rohen YAML-Inhalts — als Cache-Schlüssel-Komponente."""
    return hashlib.sha256(profile._raw.encode()).hexdigest()
