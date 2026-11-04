"""Language-model access for any provider. Anthropic uses its own SDK. OpenAI, Google Gemini, xAI and any other
OpenAI-compatible service share one small HTTP client that asks for a JSON object and validates it with Pydantic.
Structured output is always validated here; the model never sees degree-audit text beyond what requirements
parsing sends, and never edits schedules."""

import json
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from . import settings

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """No API key set, or the call was refused."""


class Router:
    """Stand-in client: the provider and model are chosen per task when the call is made."""


def get_client(task: str = "default") -> Router:
    """Fails early, with what to do, when the provider chosen for this task has no key."""
    _need_key(settings.resolve(task)[0])
    return Router()


def _need_key(provider: str) -> str:
    key = settings.get_key(provider)
    if not key:
        label = settings.PROVIDERS[provider]["label"]
        raise LLMUnavailable(
            f"No {label} API key is set. Open the AI models screen, paste a key and save it, or choose a model from a provider you have a key for."
        )
    return key


def _http_error(provider: str, e: httpx.HTTPError) -> LLMUnavailable:
    label = settings.PROVIDERS[provider]["label"]
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (401, 403):
            return LLMUnavailable(
                f"{label} rejected the key. Check that you pasted all of it and that it is still active."
            )
        if code == 404:
            return LLMUnavailable(
                f"{label} does not have that model or endpoint. Check the model name on the AI models screen."
            )
        if code == 429:
            return LLMUnavailable(
                f"{label} says the rate or spending limit was reached. Wait a moment or check your plan."
            )
        detail = ""
        try:
            detail = str((e.response.json().get("error") or {}).get("message") or "")[:200]
        except (ValueError, AttributeError):
            pass
        return LLMUnavailable(f"{label} returned an error ({code}). {detail}".strip())
    return LLMUnavailable(
        f"Could not reach {label} ({type(e).__name__}). Check your network and the address."
    )


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _base(provider: str) -> str:
    b = settings.base_url(provider)
    if not b:
        raise LLMUnavailable("Set the service address for the other provider on the AI models screen first.")
    return b


def list_models(provider: str, key: str) -> list[dict[str, str]]:
    """Model ids the key can use. Raises LLMUnavailable with a plain-language reason."""
    if provider == "anthropic":
        import anthropic

        try:
            return [
                {"id": m.id, "name": getattr(m, "display_name", m.id)}
                for m in anthropic.Anthropic(api_key=key).models.list(limit=100)
            ]
        except anthropic.AuthenticationError:
            raise LLMUnavailable(
                "Anthropic rejected that key. Check that you copied all of it and that it has not been revoked."
            ) from None
        except anthropic.PermissionDeniedError:
            raise LLMUnavailable(
                "That key is valid but is not allowed to list models. It may still work for the models you chose."
            ) from None
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            raise LLMUnavailable(
                f"Could not reach Anthropic ({type(e).__name__}). Check your network."
            ) from None
    try:
        r = httpx.get(f"{_base(provider)}/models", headers=_headers(key), timeout=30)
        r.raise_for_status()
        rows = r.json().get("data") or r.json().get("models") or []
    except httpx.HTTPError as e:
        raise _http_error(provider, e) from None
    except ValueError:
        raise LLMUnavailable("That service did not return a model list in the expected format.") from None
    ids = sorted({str(m.get("id") or m.get("name") or "").removeprefix("models/") for m in rows} - {""})
    return [{"id": i, "name": i} for i in ids]


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _json_text(text: str) -> str:
    t = _FENCE.sub("", text.strip())
    if not t.startswith("{"):
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            t = t[a : b + 1]
    return t


def _compat(provider: str, model: str, schema: type[T], system: str, user: str, max_tokens: int) -> T:
    key = _need_key(provider)
    sys_msg = (
        f"{system}\n\nReply with a single JSON object and nothing else. It must validate against this JSON "
        f"schema:\n{json.dumps(schema.model_json_schema())}"
    )
    messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}]
    last_err = ""
    for attempt in range(2):
        body: dict = {"model": model, "messages": messages, "response_format": {"type": "json_object"}}
        body["max_completion_tokens" if provider == "openai" else "max_tokens"] = max_tokens
        try:
            r = httpx.post(
                f"{_base(provider)}/chat/completions", headers=_headers(key), json=body, timeout=180
            )
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
        except httpx.HTTPError as e:
            raise _http_error(provider, e) from None
        except (ValueError, KeyError, IndexError):
            raise LLMUnavailable("That service answered in an unexpected format. Try again.") from None
        if msg.get("refusal"):
            raise LLMUnavailable("The model declined this request. Rephrase it or enter the values by hand.")
        text = msg.get("content") or ""
        try:
            return schema.model_validate_json(_json_text(text))
        except (ValidationError, ValueError) as e:
            last_err = str(e)[:400]
            messages = [
                *messages,
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": f"That did not validate: {last_err}\nReply again with only the corrected JSON object.",
                },
            ]
    raise LLMUnavailable(
        "The model did not return a usable structured answer. Try again or pick another model."
    )


def _anthropic(model: str, schema: type[T], system: str, user: str, max_tokens: int, client=None) -> T:
    if client is None or isinstance(client, Router):
        import anthropic

        client = anthropic.Anthropic(api_key=_need_key("anthropic"))
    resp = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )
    if resp.stop_reason == "refusal":
        raise LLMUnavailable("The model declined this request. Rephrase it or enter the values by hand.")
    if resp.parsed_output is None:
        raise LLMUnavailable("The model returned no structured result. Try again.")
    return resp.parsed_output


def structured(
    client, schema: type[T], system: str, user: str, max_tokens: int = 8000, task: str = "default"
) -> T:
    """Run one structured request with the provider and model chosen for this task. A client that is not the
    Router (a test double, or an already-built Anthropic client) is used as an Anthropic-style client."""
    if not isinstance(client, Router):
        return _anthropic(settings.resolve(task)[1], schema, system, user, max_tokens, client)
    provider, model = settings.resolve(task)
    if provider == "anthropic":
        return _anthropic(model, schema, system, user, max_tokens)
    return _compat(provider, model, schema, system, user, max_tokens)
