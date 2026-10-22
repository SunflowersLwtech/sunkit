"""Provider selection switches shared by the harness, scripts, and release gates.

Every switch defaults to the original provider, so a run that sets none of these
variables behaves exactly as before.
"""

from __future__ import annotations

from pathlib import Path

try:
    from scripts.env_utils import env_value
except ImportError:  # imported with scripts/ on sys.path
    from env_utils import env_value

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT / ".env"

TTS_PROVIDERS = ("gemini", "cartesia")
TTS_SCRIPTS = {"gemini": "scripts/gemini_tts.py", "cartesia": "scripts/cartesia_tts.py"}
# Providers whose voiceover_manifest.json describes real synthesized speech.
REAL_TTS_PROVIDERS = frozenset(TTS_PROVIDERS)

VISUAL_AUDIT_MODES = ("gemini", "deterministic")
DOUYIN_UPLOADERS = ("social-auto-upload", "ego")

# Status recorded for a model audit that the selected mode does not run. It is
# never "pass": only the deterministic-audit mode may accept it at release time.
AUDIT_NOT_USED = "not-used"


def _choice(key: str, choices: tuple[str, ...], env_file: Path | None) -> str:
    value = env_value(key, env_file or DEFAULT_ENV_FILE).strip().lower()
    if not value:
        return choices[0]
    if value not in choices:
        raise SystemExit(f"{key} must be one of {', '.join(choices)}; got {value!r}")
    return value


def tts_provider(env_file: Path | None = None) -> str:
    return _choice("SEARCHPO_TTS_PROVIDER", TTS_PROVIDERS, env_file)


def tts_script(env_file: Path | None = None) -> str:
    return TTS_SCRIPTS[tts_provider(env_file)]


def visual_audit_mode(env_file: Path | None = None) -> str:
    return _choice("SEARCHPO_VISUAL_AUDIT", VISUAL_AUDIT_MODES, env_file)


def douyin_uploader(env_file: Path | None = None) -> str:
    return _choice("SEARCHPO_DOUYIN_UPLOADER", DOUYIN_UPLOADERS, env_file)
