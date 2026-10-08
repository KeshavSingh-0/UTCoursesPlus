"""Thin wrapper around the Anthropic SDK. Structured output is validated by Pydantic; the
language model never sees degree-audit text beyond what requirements parsing sends, and never
edits schedules."""

import os
from typing import TypeVar

from pydantic import BaseModel

MODEL = os.environ.get("UTCP_MODEL", "claude-opus-5-5")
T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """No API key set, or the call was refused."""


def get_client():
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailable(
            "ANTHROPIC_API_KEY is not set. Export it in the terminal that runs the app, then restart."
        )
    return anthropic.Anthropic()


def structured(client, schema: type[T], system: str, user: str, max_tokens: int = 8000) -> T:
    resp = client.messages.parse(
        model=MODEL,
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
