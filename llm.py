"""The Groq LLM, paced to the free-tier token budget, plus JSON parsing.

Groq's free tier allows 8,000 tokens per minute, counting the prompt and the
reserved output. A long contract can use most of that in one call, so calls
wait for budget here instead of failing with a 429 halfway through a review.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

import config


class MissingKeyError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_llm() -> ChatGroq:
    if not config.GROQ_API_KEY:
        raise MissingKeyError(
            "GROQ_API_KEY is not set. Add it to .env (local) or to the app's secrets "
            "(Streamlit Community Cloud). A free key is available at https://console.groq.com."
        )
    return ChatGroq(
        model=config.LLM_MODEL,
        temperature=config.LLM_TEMPERATURE,
        api_key=config.GROQ_API_KEY,
        reasoning_effort=config.LLM_REASONING_EFFORT,
        max_retries=4,
        timeout=120,
    )


# --- Token budget ------------------------------------------------------------
# A token bucket that refills continuously, the way Groq replenishes its
# per-minute limit. A call waits only for the tokens it is short of.
_lock = threading.Lock()
_capacity = config.TOKENS_PER_MINUTE * config.TOKEN_BUDGET_SAFETY
_bucket = {"tokens": _capacity, "at": time.monotonic()}


def estimate_tokens(text: str) -> int:
    # ~3.5 characters per token for English legal prose, rounded up.
    return int(len(text) / 3.5) + 50


def _wait_for_budget(tokens: int, on_wait: Callable[[float], None] | None) -> None:
    rate = _capacity / 60.0
    tokens = min(tokens, _capacity)
    while True:
        with _lock:
            now = time.monotonic()
            _bucket["tokens"] = min(_capacity, _bucket["tokens"] + (now - _bucket["at"]) * rate)
            _bucket["at"] = now
            if _bucket["tokens"] >= tokens:
                _bucket["tokens"] -= tokens
                return
            wait = (tokens - _bucket["tokens"]) / rate + 0.5
        if on_wait:
            on_wait(wait)
        time.sleep(wait)


def invoke(
    system: str,
    user: str,
    max_tokens: int,
    history: list[BaseMessage] | None = None,
    on_wait: Callable[[float], None] | None = None,
) -> str:
    """One chat completion, paced against the per-minute token budget."""
    messages: list[BaseMessage] = [SystemMessage(system), *(history or []), HumanMessage(user)]
    prompt_chars = sum(len(str(m.content)) for m in messages)
    _wait_for_budget(estimate_tokens("x" * prompt_chars) + max_tokens, on_wait)
    reply = get_llm().invoke(messages, max_tokens=max_tokens)
    return str(reply.content)


# --- JSON --------------------------------------------------------------------
def parse_json(raw: str) -> Any:
    """Parse the model's JSON, tolerating code fences and leading/trailing prose."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    salvaged = salvage_list(text)
    if salvaged:
        return {"findings": salvaged, "entries": salvaged, "truncated": True}
    raise ValueError("The model did not return valid JSON.")


def salvage_list(text: str) -> list[dict]:
    """Recover the complete objects from a JSON list cut off by the token cap.

    A long answer can stop mid-item. Every object that closed before the cut
    is still valid evidence; only the unfinished last one is lost.
    """
    start = text.find("[")
    if start < 0:
        return []
    items, depth, in_string, escaped, item_start = [], 0, False, False, None
    for index in range(start + 1, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                item_start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and item_start is not None:
                try:
                    items.append(json.loads(text[item_start : index + 1]))
                except json.JSONDecodeError:
                    pass
                item_start = None
        elif char == "]" and depth == 0:
            break
    return items


def invoke_json(system: str, user: str, max_tokens: int, on_wait=None) -> Any:
    """invoke() + parse_json(), with one retry that asks for strict JSON."""
    raw = invoke(system, user, max_tokens, on_wait=on_wait)
    try:
        return parse_json(raw)
    except ValueError:
        raw = invoke(system, user + "\n\nReturn ONLY valid JSON. No prose, no code fences.", max_tokens, on_wait=on_wait)
        return parse_json(raw)
