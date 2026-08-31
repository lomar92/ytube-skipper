# ytsum

YouTube Transcribe & Summarize CLI — analyses videos against your personal interest profile and helps you decide in under 60 seconds: watch, skip, or is the summary enough?

Works with 20-minute news clips and 3-hour podcasts alike.

---

## Requirements

- Python 3.11 or newer
- pip
- Gemini API key (free): https://aistudio.google.com → "Get API key"

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/lomar92/ytube-skipper ~/ytsum
cd ~/ytsum
```

### 2. Install dependencies

```bash
pip install -e .
```

This installs `ytsum` as a global CLI command and the following core packages:

| Package | Purpose |
|---|---|
| `openai` | OpenAI-compatible client (Gemini, Groq, Ollama) |
| `yt-dlp` | Video metadata and audio download |
| `youtube-transcript-api` | Fetch YouTube subtitles |
| `pyyaml` | Parse interests.yaml |

### 3. Optional dependencies

**Whisper** — transcription for videos without subtitles (~150 MB for the `base` model):

```bash
pip install -e ".[whisper]"
```

**Anthropic Claude** as an alternative LLM provider:

```bash
pip install -e ".[anthropic]"
```

---

## Shell Completion (Oh My Zsh)

The project includes an Oh My Zsh plugin with tab completion for all flags.

### Installation

**Step 1 — Link the plugin directory** (recommended — updates automatically when the repo changes):

```bash
ln -s ~/ytsum/completions ~/.oh-my-zsh/custom/plugins/ytsum
```

Or copy (requires manual update when flags change):

```bash
cp -r ~/ytsum/completions ~/.oh-my-zsh/custom/plugins/ytsum
```

**Step 2 — Enable the plugin** in `~/.zshrc`:

```bash
plugins=(... ytsum)
```

**Step 3 — Reload the shell:**

```bash
source ~/.zshrc
```

### What the completion provides

```bash
ytsum <url> <TAB>                          # all flags with descriptions
ytsum <url> --provider <TAB>               # gemini / groq / ollama / anthropic
ytsum <url> --provider anthropic --model <TAB>  # Claude models only
ytsum <url> --provider gemini --model <TAB>     # Gemini models only
ytsum <url> --whisper-model <TAB>          # tiny / base / small / medium / large-v2 / large-v3
ytsum <url> --vault <TAB>                  # directory completion
ytsum <url> --profile <TAB>               # *.yaml files
ytsum <url> --prompt <TAB>                # *.md files
```

`--no-whisper` and `--whisper-model` are mutually exclusive — once one is used, the other is no longer suggested.

---

## Configuration

### Set API key and vault permanently

Add to `~/.zshrc` (or `~/.bashrc`) and open a new terminal:

```bash
# ytsum
export GEMINI_API_KEY="your-key-here"
export YTSUM_VAULT="/path/to/your/vault"   # optional, for Obsidian integration
```

Alternatively: create a `.env` file in the project directory (only effective when ytsum is run from that folder):

```
GEMINI_API_KEY=your-key-here
YTSUM_VAULT=/path/to/your/vault
```

### Create interests.yaml

The interest profile controls scoring, detail depth, and analysis focus.
ytsum looks for `interests.yaml` in the current working directory by default.

```yaml
language: English   # output language for the entire analysis

always_relevant:
  - "Kurzgesagt – In a Nutshell"  # channel names — videos always score at least 7/10
  - "Veritasium"

keywords:
  - Fermentation          # bonus: +2 points if prominent in the video
  - Cycling
  - Astrophotography

high:                     # maximum coverage, full detail
  "Space & Astrophysics": "black holes, exoplanets, James Webb, dark matter, space missions"
  "Climate Tech & Energy": "solar, wind, battery storage, hydrogen, nuclear fusion"

medium:                   # mentioned when clearly relevant
  - Cooking & Food Science
  - Endurance Sports & Nutrition

low:                      # only when exceptionally significant
  - Architecture & Urban Planning
  - Philosophy of Mind
```

See `interests.yaml.example` for a full template with comments.

**Profile fields:**

| Field | Function | Score impact |
|---|---|---|
| `language` | Output language for all analysis fields | — |
| `always_relevant` | YouTube channel names | Minimum score 7/10 |
| `keywords` | Free keywords (hobbies, niche topics) | +2 points if prominent |
| `high` | Core topics with aspects | Maximum coverage |
| `medium` | Secondary topics | Mentioned when relevant |
| `low` | Fringe topics | Only at exceptional significance |

---

## Usage

### Basic command

```bash
ytsum https://www.youtube.com/watch?v=VIDEO_ID
```

Supported URL formats:
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`

### Multiple videos at once

```bash
ytsum <url1> <url2> <url3>
```

### Re-run analysis (bypass cache)

```bash
ytsum <url> --no-cache
```

Required after changes to the prompt template. Changes to `interests.yaml` automatically trigger a fresh analysis (profile hash changes).

---

## Saving

After the analysis you are interactively asked where to save (when `YTSUM_VAULT` is set):

```
  Save?  ★ High relevance
    [1] Local (./out/)
    [2] Vault (YouTube Notes/)
    [3] Both
    [n] No
  Input:
```

Without a configured vault, only the local option is shown:

```
  Save locally (./out/)? [y/n]:
```

**Filenames** are generated from date, channel, and core thesis — no cryptic IDs:

```
out/2024-11-15_veritasium_gravity-is-not-a-force-general-relativity-explained.md
```

---

## Obsidian Vault Integration

ytsum can save analyses directly into an [Obsidian](https://obsidian.md) vault as ready-to-use notes with YAML frontmatter.

### Setup

Set `YTSUM_VAULT` (or `--vault`) to the **exact folder** where notes should land.
ytsum saves directly into that directory — no subfolder is added automatically.

```bash
export YTSUM_VAULT="/path/to/your/vault/04 Ressourcen/YouTube Notizen"
ytsum <url>
```

Or per-run:

```bash
ytsum <url> --vault "/path/to/your/vault/04 Ressourcen/YouTube Notizen"
```

### Where files land

Notes are saved directly to `<YTSUM_VAULT>/<date>-<channel>-<title>.md`.
Point the path at any folder inside your vault — Obsidian subfolder, PARA section, language-specific directory, whatever fits your structure.

### Obsidian YAML frontmatter

Every vault note includes frontmatter that Obsidian reads natively:

```yaml
---
tags: ["youtube", "veritasium", "space-astrophysics"]
kanal: "Veritasium"
datum: 2024-11-15
url: https://youtu.be/...
relevanz: 9/10
verdict: watch
---
```

Tags are generated automatically from the channel name and the matched interest topics.
The `relevance` and `verdict` fields make it easy to filter and sort notes in Obsidian's database views or Dataview plugin.

---

## All CLI flags

```
ytsum URL [URL ...] [options]
```

| Flag | Default | Description |
|---|---|---|
| `--provider` | `gemini` | LLM provider: `gemini`, `anthropic`, `groq`, `ollama` |
| `--model MODEL` | Provider default | e.g. `gemini-2.5-pro`, `claude-sonnet-4-6` |
| `--profile PATH` | `./interests.yaml` | Path to the interest profile |
| `--save` | — | Save locally immediately without prompting |
| `--vault PATH` | `$YTSUM_VAULT` | Exact output directory for Obsidian notes (overrides env variable) |
| `--json` | — | JSON output instead of terminal view (--vault is ignored with JSON) |
| `--no-cache` | — | Bypass cache — reprocess everything |
| `--whisper-model SIZE` | `base` | Whisper size: `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3` |
| `--no-whisper` | — | No Whisper fallback — fail if no subtitles available |
| `--keep-audio` | — | Keep downloaded audio after Whisper transcription (default: delete). No effect when subtitles are found or `--no-whisper` is set |
| `--prompt PATH` | Built-in | Custom prompt template instead of `prompts/analysis.md` |

---

## LLM Providers

### Gemini (default, free)

API key at https://aistudio.google.com — Free Tier is sufficient.

```bash
ytsum <url>                                # gemini-3.6-flash (default)
ytsum <url> --model gemini-2.5-pro         # best quality, paid
ytsum <url> --model gemini-2.5-flash       # previous default, free tier
```

### Anthropic Claude

```bash
pip install -e ".[anthropic]"
export ANTHROPIC_API_KEY="sk-ant-..."
ytsum <url> --provider anthropic           # claude-sonnet-4-6 (default)
ytsum <url> --provider anthropic --model claude-opus-4-6
```

### Groq (free, very fast)

```bash
export GROQ_API_KEY="your-key"
ytsum <url> --provider groq                # llama-3.3-70b-versatile
```

### Ollama (local, no API key needed)

```bash
ollama pull llama3.2
ytsum <url> --provider ollama
ytsum <url> --provider ollama --model mistral
```

---

## Transcription

ytsum fetches transcripts in this priority order:

1. **YouTube subtitles (manual)** — instant, free, best quality
2. **YouTube auto-captions** — instant, free, sufficient for most videos
3. **Whisper** (fallback) — runs locally on CPU, takes a few minutes depending on video length

Whisper tips:
- `--whisper-model tiny` — fastest, good for short videos with clear speech
- `--whisper-model base` — default, good balance
- `--whisper-model large-v2` — high quality, significantly slower
- `--whisper-model large-v3` — best quality, significantly slower
- `--no-whisper` — abort immediately if no YouTube subtitles are available

Transcripts are cached — a video is never transcribed twice.

---

## Cache

```
~/.cache/ytsum/
├── transcripts/<video_id>.json          # permanent — valid regardless of profile changes
├── analyses/<video_id>_<hash>.json      # invalidated automatically when interests.yaml changes
└── audio/<video_id>.<ext>               # temporary — deleted after Whisper transcription by default
                                         # use --keep-audio to retain
```

Bypass cache entirely: `ytsum <url> --no-cache`

> **Upgrading from an earlier version?** Audio files from previous runs are not cleaned up automatically. Remove them with: `rm ~/.cache/ytsum/audio/*`

---

## Output verdict

| Verdict | Meaning |
|---|---|
| `watch` | Watch in full — highly relevant |
| `watch_sections` | Only specific sections are relevant — skip times provided |
| `summary_sufficient` | The summary is enough, skip the video |
| `skip` | Not relevant or poor quality |

---

## Long videos (Map-Reduce)

Videos exceeding ~60,000 tokens (~60 min of subtitles) are automatically split into chunks:

1. **Map** — each chunk is summarised independently with the interest profile as context
2. **Reduce** — all chunk summaries are merged into a final structured analysis

Progress is printed for each chunk.

---

## Customising the prompt

The LLM prompt lives in `ytsum/prompts/analysis.md` and can be edited directly.
Use a custom template: `ytsum <url> --prompt ./my-template.md`

Available placeholders:

| Placeholder | Content |
|---|---|
| `<<VIDEO_META>>` | Title, channel, duration, URL |
| `<<USER_PROFILE>>` | Formatted interest profile |
| `<<TRANSCRIPT>>` | Full transcript or chunk summaries |
| `<<LANGUAGE>>` | Output language from `interests.yaml` |

---

## Project structure

```
ytsum/
├── ytsum/
│   ├── cli.py           # Entry point + pipeline orchestration
│   ├── models.py        # Dataclasses: Segment, Transcript, Analysis, CostReport
│   ├── transcript.py    # YouTube subtitles + Whisper fallback
│   ├── profile.py       # interests.yaml loader + prompt formatting
│   ├── llm.py           # LLM calls + Map-Reduce for long videos
│   ├── cache.py         # JSON cache (atomic writes)
│   ├── output.py        # Terminal, Markdown, and JSON rendering
│   └── prompts/
│       └── analysis.md  # Editable LLM prompt template
├── completions/
│   ├── _ytsum           # Zsh completion spec
│   └── ytsum.plugin.zsh # Oh My Zsh plugin entry point
├── tests/
│   ├── test_transcript.py
│   ├── test_llm.py
│   └── test_output.py
├── interests.yaml.example  # Template — copy to interests.yaml
├── .env                    # API keys (never committed to git)
├── pyproject.toml
└── README.md
```

---

## Known limitations

- Videos behind age-gates or login walls fail at the metadata step
- Auto-generated subtitles for non-English content may have lower accuracy than Whisper
- Speaker diarization is heuristic only — regex detection of `"Name: text"` prefixes + gap-based turn assignment. Accurate multi-speaker attribution would require pyannote-audio (GPU dependency, not included)
