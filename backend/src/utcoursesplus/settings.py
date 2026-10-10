"""App settings kept on this computer: the API key and which model runs each job. The file lives in the
gitignored data folder and is readable only by you. The key is never sent back to the browser."""

import json
import os
from typing import Any

from .config import DATA_DIR

PATH = DATA_DIR / "settings.json"
TASKS = {
    "preferences": "Plain-English preferences",
    "audit": "Degree audit reading",
    "syllabus": "Syllabus reading",
}
# Current Claude models, used when the live model list cannot be fetched
FALLBACK_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]
DEFAULT_MODEL = "claude-opus-5-5"


def _read() -> dict[str, Any]:
    try:
        return json.loads(PATH.read_text())
    except (OSError, ValueError):
        return {}


def _write(d: dict[str, Any]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(d, indent=2))
    try:
        PATH.chmod(0o600)
    except OSError:
        pass


def key_source() -> str | None:
    if _read().get("anthropic_key"):
        return "saved"
    return "environment" if os.environ.get("ANTHROPIC_API_KEY") else None


def get_key() -> str | None:
    return _read().get("anthropic_key") or os.environ.get("ANTHROPIC_API_KEY") or None


def key_hint(key: str | None = None) -> str | None:
    k = key if key is not None else get_key()
    if not k:
        return None
    return f"{k[:7]}...{k[-4:]}" if len(k) > 16 else "saved"


def default_model() -> str:
    return _read().get("default_model") or os.environ.get("UTCP_MODEL") or DEFAULT_MODEL


def model_for(task: str) -> str:
    return (_read().get("models") or {}).get(task) or default_model()


def update(
    *,
    key: str | None = None,
    clear_key: bool = False,
    default: str | None = None,
    models: dict[str, str] | None = None,
) -> None:
    d = _read()
    if clear_key:
        d.pop("anthropic_key", None)
    elif key:
        d["anthropic_key"] = key.strip()
    if default:
        d["default_model"] = default.strip()
    if models is not None:
        d["models"] = {t: m.strip() for t, m in models.items() if t in TASKS and m and m.strip()}
    _write(d)


def public_view() -> dict[str, Any]:
    d = _read()
    return {
        "key_source": key_source(),
        "key_hint": key_hint(),
        "default_model": default_model(),
        "models": {t: (d.get("models") or {}).get(t) or "" for t in TASKS},
        "tasks": TASKS,
        "fallback_models": FALLBACK_MODELS,
    }
