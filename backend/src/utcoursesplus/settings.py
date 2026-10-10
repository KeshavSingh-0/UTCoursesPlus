"""App settings kept on this computer: API keys for the AI providers you use and which provider and model runs
each job. The file lives in the gitignored data folder and is readable only by you. Keys are never sent back
to the browser; only a short hint is."""

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
# id -> label, environment variable, OpenAI-compatible base URL (None: Anthropic's own SDK), key shape hint
PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {"label": "Anthropic (Claude)", "env": "ANTHROPIC_API_KEY", "base": None, "hint": "sk-ant-"},
    "openai": {
        "label": "OpenAI",
        "env": "OPENAI_API_KEY",
        "base": "https://api.openai.com/v1",
        "hint": "sk-",
    },
    "gemini": {
        "label": "Google (Gemini)",
        "env": "GEMINI_API_KEY",
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "hint": "AIza",
    },
    "xai": {"label": "xAI (Grok)", "env": "XAI_API_KEY", "base": "https://api.x.ai/v1", "hint": "xai-"},
    "custom": {
        "label": "Other (OpenAI-compatible)",
        "env": "CUSTOM_LLM_API_KEY",
        "base": "",
        "hint": "",
    },
}
# Used when the live model list cannot be fetched. Lists change often; "Test the key" shows what yours can use.
FALLBACK_MODELS = {
    "anthropic": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"],
    "openai": ["gpt-5", "gpt-5-mini"],
    "gemini": ["gemini-2.5-pro", "gemini-2.5-flash"],
    "xai": ["grok-4", "grok-4-fast"],
    "custom": [],
}
DEFAULT_SPEC = "anthropic:claude-opus-5-5"


def _read() -> dict[str, Any]:
    try:
        d = json.loads(PATH.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    # settings written before several providers were supported
    if "anthropic_key" in d:
        d.setdefault("keys", {})["anthropic"] = d.pop("anthropic_key")
    if "default_model" in d:
        d.setdefault("default", f"anthropic:{d.pop('default_model')}")
    if isinstance(d.get("models"), dict):
        d.setdefault("tasks", {}).update({t: f"anthropic:{m}" for t, m in d.pop("models").items() if m})
    return d


def _write(d: dict[str, Any]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(d, indent=2))
    try:
        PATH.chmod(0o600)
    except OSError:
        pass


def split_spec(spec: str) -> tuple[str, str]:
    """'openai:gpt-5' -> ('openai', 'gpt-5'). A bare model name is treated as an Anthropic model."""
    if ":" in spec:
        p, m = spec.split(":", 1)
        if p in PROVIDERS:
            return p, m.strip()
    return "anthropic", spec.strip()


def valid_spec(spec: str) -> bool:
    return ":" in spec and spec.split(":", 1)[0] in PROVIDERS and bool(spec.split(":", 1)[1].strip())


def key_source(provider: str = "anthropic") -> str | None:
    if (_read().get("keys") or {}).get(provider):
        return "saved"
    return "environment" if os.environ.get(PROVIDERS[provider]["env"]) else None


def get_key(provider: str = "anthropic") -> str | None:
    return (_read().get("keys") or {}).get(provider) or os.environ.get(PROVIDERS[provider]["env"]) or None


def key_hint(provider: str = "anthropic", key: str | None = None) -> str | None:
    k = key if key is not None else get_key(provider)
    if not k:
        return None
    return f"{k[:7]}...{k[-4:]}" if len(k) > 16 else "saved"


def base_url(provider: str) -> str | None:
    if provider == "custom":
        return (_read().get("custom_base_url") or os.environ.get("CUSTOM_LLM_BASE_URL") or "").rstrip(
            "/"
        ) or None
    return PROVIDERS[provider]["base"]


def default_spec() -> str:
    spec = _read().get("default") or os.environ.get("UTCP_MODEL") or DEFAULT_SPEC
    p, m = split_spec(spec)
    return f"{p}:{m}"


def resolve(task: str) -> tuple[str, str]:
    spec = (_read().get("tasks") or {}).get(task) or default_spec()
    return split_spec(spec)


def configured() -> bool:
    return key_source(resolve("default")[0]) is not None


def update(
    *,
    keys: dict[str, str] | None = None,
    clear_keys: list[str] | None = None,
    custom_base_url: str | None = None,
    default: str | None = None,
    tasks: dict[str, str] | None = None,
) -> None:
    d = _read()
    d.pop("models", None)
    ks = d.setdefault("keys", {})
    for p in clear_keys or []:
        ks.pop(p, None)
    for p, k in (keys or {}).items():
        if p in PROVIDERS and k and k.strip():
            ks[p] = k.strip()
    if custom_base_url is not None:
        d["custom_base_url"] = custom_base_url.strip().rstrip("/")
    if default:
        d["default"] = default.strip()
    if tasks is not None:
        d["tasks"] = {t: m.strip() for t, m in tasks.items() if t in TASKS and m and m.strip()}
    _write(d)


def public_view() -> dict[str, Any]:
    d = _read()
    return {
        "providers": {
            p: {
                "label": info["label"],
                "key_source": key_source(p),
                "key_hint": key_hint(p),
                "env_var": info["env"],
                "key_prefix": info["hint"],
                "fallback_models": FALLBACK_MODELS[p],
            }
            for p, info in PROVIDERS.items()
        },
        "custom_base_url": d.get("custom_base_url") or "",
        "default": default_spec(),
        "tasks": {t: (d.get("tasks") or {}).get(t) or "" for t in TASKS},
        "task_names": TASKS,
    }
