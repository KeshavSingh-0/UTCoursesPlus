"""Thin wrapper around the Anthropic SDK. Structured output is validated by Pydantic; the
language model never sees degree-audit text beyond what requirements parsing sends, and never
edits schedules."""

from typing import TypeVar

from pydantic import BaseModel

from . import settings

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """No API key set, or the call was refused."""


def get_client():
    import anthropic

    key = settings.get_key()
    if not key:
        raise LLMUnavailable(
            "No API key is set. Open the AI models screen, paste your Anthropic key and save it."
        )
    return anthropic.Anthropic(api_key=key)


def structured(
    client, schema: type[T], system: str, user: str, max_tokens: int = 8000, task: str = "default"
) -> T:
    resp = client.messages.parse(
        model=settings.model_for(task),
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
