"""OpenAI-compatible LLM planner for the shopper (stdlib urllib only).

Implements the Planner protocol: model output is mapped to the EXISTING tool
Actions only. This module never holds the agent key and never calls the token
service — loop.run_tool remains the only execution path (client.py spends).

Config (environment only, read at call time):
  SHOPPER_MODEL_PROVIDER  openrouter (default) | local
  SHOPPER_MODEL           model id; defaults below per provider
  OPENROUTER_API_KEY      required when provider=openrouter (never logged)
  local base              http://127.0.0.1:18434/v1  (llama.cpp, no key)
  openrouter base         https://openrouter.ai/api/v1
"""
import json
import os
import urllib.error
import urllib.request
from typing import Callable

from .loop import Action

TOOLS = ("search_flights", "read_reviews", "propose", "wait_for_approval", "buy")
DEFAULTS = {
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    "local": ("http://127.0.0.1:18434/v1", "Qwen3-8B"),
}
MAX_HISTORY = 12  # messages sent to the model (capped)

SYSTEM = (
    "You are a shopping agent. Call exactly one tool per turn by replying with "
    "JSON only: {\"tool\": \"<name>\", \"args\": {...}}. "
    f"Allowed tools: {', '.join(TOOLS)}. "
    "Tool contracts (argument names are exact; send no fields beyond these): "
    "search_flights{query?} returns results with id/title/price. "
    "read_reviews{item_id} returns the reviews for one result id. "
    "propose{item_id, mode, ceiling?} asks the human to approve a purchase: mode is "
    "exactly \"verify\" (buy at the item's exact price) or \"yolo\" (buy at or under "
    "ceiling; ceiling required for yolo, an amount string like \"400.00\", never for "
    "verify). Payee and price come from the item itself, never from you. "
    "wait_for_approval{} takes no args and polls the proposal you just made. "
    "buy{item_id} completes the approved purchase of that item. "
    "Usual order: search_flights, read_reviews, propose, wait_for_approval, buy. "
    "When finished, reply with {\"tool\": null}. No prose."
)


def resolve_config(env=None):
    """Provider/base/model from environment. Keys are never returned."""
    e = env if env is not None else os.environ
    provider = (e.get("SHOPPER_MODEL_PROVIDER") or "openrouter").strip().lower()
    if provider not in DEFAULTS:
        raise ValueError(f"unknown SHOPPER_MODEL_PROVIDER: {provider}")
    base, default_model = DEFAULTS[provider]
    model = (e.get("SHOPPER_MODEL") or default_model).strip()
    return {"provider": provider, "base": base, "model": model}


def _transport(method, url, headers, body, timeout=60):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def _action_from_payload(payload) -> Action | None:
    if not isinstance(payload, dict):
        return None
    tool = payload.get("tool")
    if tool is None:
        return None
    if tool not in TOOLS:
        return None
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        return None
    return Action(tool, args)


def parse_model_output(text: str) -> Action | None:
    """Map model text to an Action, or None on garbage / unknown / stop."""
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    # Strip common markdown fences without guessing tool names.
    if s.startswith("```"):
        lines = s.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        payload = json.loads(s)
    except (ValueError, TypeError):
        # Some models wrap the object; try to find a single top-level object.
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(s[start:end + 1])
        except (ValueError, TypeError):
            return None
    return _action_from_payload(payload)


class LLMPlanner:
    """Planner backed by an OpenAI-compatible chat completions endpoint."""

    def __init__(self, transport: Callable | None = None, env=None):
        self._transport = transport or _transport
        self._env = env  # None => read os.environ at call time
        self._messages = [{"role": "system", "content": SYSTEM}]

    def _cfg(self):
        return resolve_config(self._env if self._env is not None else os.environ)

    def _headers(self, cfg):
        h = {"Content-Type": "application/json"}
        e = self._env if self._env is not None else os.environ
        if cfg["provider"] == "openrouter":
            key = e.get("OPENROUTER_API_KEY") or ""
            if not key:
                raise RuntimeError("OPENROUTER_API_KEY required for openrouter provider")
            h["Authorization"] = f"Bearer {key}"
        return h

    def _chat(self, messages):
        cfg = self._cfg()
        body = json.dumps({
            "model": cfg["model"],
            "messages": messages,
            "temperature": 0,
        }).encode()
        url = cfg["base"].rstrip("/") + "/chat/completions"
        try:
            st, raw = self._transport("POST", url, self._headers(cfg), body)
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        if st != 200:
            return None
        try:
            data = json.loads(raw)
            return data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            return None

    def next(self, history: list[dict]) -> Action | None:
        # Cap history length sent to the model (oldest free-action noise dropped).
        trimmed = history[-MAX_HISTORY:]
        msgs = list(self._messages)
        for step in trimmed:
            a = step.get("action")
            if a is not None:
                msgs.append({"role": "assistant", "content": json.dumps({"tool": a.tool, "args": a.args})})
            msgs.append({"role": "user", "content": json.dumps({"result": step.get("result")}, default=str)})
        if not trimmed:
            msgs.append({"role": "user", "content": "Start shopping. Call one tool."})
        text = self._chat(msgs)
        if text is None:
            return None
        return parse_model_output(text)
