"""OpenAI-compatible chat client with tool calling and provider failover.

Providers (tried in priority order, only if configured):
    OmniRoute  -> self-hosted gateway, ``{omniroute_url}/chat/completions``
    OpenRouter -> ``openrouter_url``
    Ollama     -> local, via its OpenAI-compatible ``/v1/chat/completions``

The agent always speaks the native OpenAI tool-calling format. If an endpoint rejects the
``tools`` parameter (many free/local models do), this client transparently falls back to a
text protocol (``<tool_call>{...}</tool_call>``) so the agent keeps working.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.config.settings import Settings

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_COOLDOWN_SECONDS = 60.0
# A provider that says "no credit" or "bad key" will keep saying it: do not try it on every message (each try costs the user seconds).
_LONG_COOLDOWN = {401: 900.0, 402: 600.0, 403: 900.0}
DEFAULT_MAX_TOKENS = 2048          # replies and tool calls are short; without a limit OpenRouter reserves the model's maximum and answers 402 to a small balance
_AFFORD_RE = re.compile(r"can only afford (\d+)", re.IGNORECASE)


@dataclass(slots=True)
class ChatResult:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # [{id, name, arguments: dict}]
    provider: str = ""
    model: str = ""

    def assistant_message(self) -> dict[str, Any]:
        """The assistant turn in native OpenAI format (to append to the running history)."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])},
                }
                for call in self.tool_calls
            ]
        return msg


@dataclass(slots=True)
class Endpoint:
    name: str
    url: str
    api_key: str
    models: list[str]
    timeout: float
    headers: dict[str, str] = field(default_factory=dict)


class ChatClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client
        self._owns_client = client is None
        self._cooldown: dict[str, float] = {}
        self._text_protocol: set[str] = set()  # endpoint:model keys that rejected native tools
        self.last_provider: str = ""
        self.stats: dict[str, Any] = {"calls": 0, "ok": 0, "failed": 0, "last_ok_at": None, "last_error": None,
                                      "last_provider": "", "last_model": ""}
        self._failures: dict[str, str] = {}      # model key -> kind of its latest failure; cleared by any success, read by explain_failure()

    # ── lifecycle ───────────────────────────────────────────────────
    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    # ── endpoint selection ──────────────────────────────────────────
    def endpoints(self) -> list[Endpoint]:
        s = self.settings
        provider = s.llm_provider.lower().strip()
        if provider == "mock":
            return []

        found: dict[str, Endpoint] = {}
        if s.omniroute_api_key or provider == "omniroute":
            found["omniroute"] = Endpoint(
                name="omniroute",
                url=f"{s.omniroute_url.rstrip('/')}/chat/completions",
                api_key=s.omniroute_api_key,
                models=[s.omniroute_model],
                timeout=float(s.omniroute_timeout),
            )
        if s.openrouter_api_key:
            found["openrouter"] = Endpoint(
                name="openrouter",
                url=s.openrouter_url,
                api_key=s.openrouter_api_key,
                models=[m for m in dict.fromkeys((s.openrouter_model, s.openrouter_fallback_model, s.openrouter_free_model)) if m],
                timeout=float(s.openrouter_timeout),
                headers={"HTTP-Referer": "https://tapan-ai.local", "X-Title": "TAPAN_AI"},
            )
        ollama_base = s.ollama_url.split("/api/")[0].rstrip("/")
        found["ollama"] = Endpoint(
            name="ollama",
            url=f"{ollama_base}/v1/chat/completions",
            api_key="",
            models=[s.ollama_model],
            timeout=float(s.ollama_timeout),
        )

        order = [provider] + [n for n in ("omniroute", "openrouter", "ollama") if n != provider]
        return [found[n] for n in order if n in found]

    @property
    def configured(self) -> bool:
        """True if at least one *remote/explicit* provider is set up (Ollama alone is best-effort)."""
        return any(e.name != "ollama" for e in self.endpoints()) or self.settings.llm_provider.lower() == "ollama"

    # ── failure bookkeeping ─────────────────────────────────────────
    def _record_failure(self, key: str, exc: Exception) -> None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 402, 403):
            kind = {401: "key", 402: "credit", 403: "key"}[status]
        elif status == 429:
            kind = "rate"
        elif isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)):
            kind = "network"
        else:
            kind = "other"
        self._failures[key] = kind
        self.stats["last_error"] = f"{key}: {type(exc).__name__}{f' {status}' if status else ''}: {str(exc)[:160]}"
        self._cooldown[key] = time.monotonic() + _LONG_COOLDOWN.get(status or 0, _COOLDOWN_SECONDS)

    def explain_failure(self) -> str:
        """Why the last attempt to reach a model failed, in words the owner can act on. '' when nothing has failed."""
        kinds = {k for key, k in self._failures.items() if not key.startswith("ollama:")} or set(self._failures.values())
        if "credit" in kinds:
            return ("The AI provider (OpenRouter) says the account is out of credit. Add a little credit at openrouter.ai/credits, "
                    "or set TAPAN_OPENROUTER_MODEL to a free model.")
        if "key" in kinds:
            return "The AI provider rejected the API key. It may have been rotated or revoked: set a new TAPAN_OPENROUTER_API_KEY."
        if "rate" in kinds:
            return "The AI provider is rate limiting requests right now. It usually clears within a minute."
        if "network" in kinds:
            return "I could not reach the AI provider (network problem). It usually comes back on its own."
        if kinds:
            return "The AI provider returned errors for every model I tried."
        return ""

    # ── public API ──────────────────────────────────────────────────
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.4,
        json_mode: bool = False,
    ) -> ChatResult | None:
        """Return the first successful completion, or None if every provider failed."""
        self.stats["calls"] += 1
        for endpoint in self.endpoints():
            for model in endpoint.models:
                key = f"{endpoint.name}:{model}"
                if self._cooldown.get(key, 0.0) > time.monotonic():
                    continue
                try:
                    result = await self._call(endpoint, model, key, messages, tools, temperature, json_mode)
                except Exception as exc:  # network error, 4xx/5xx, bad payload
                    logger.warning("LLM %s failed: %s", key, exc)
                    self._record_failure(key, exc)
                    continue
                if result is not None:
                    self._failures.clear()
                    self.last_provider = endpoint.name
                    self.stats.update(ok=self.stats["ok"] + 1, last_provider=endpoint.name, last_model=model, last_error=None,
                                      last_ok_at=datetime.now(timezone.utc).isoformat())
                    return result
        self.stats["failed"] += 1
        return None

    async def complete_vision(self, messages: list[dict[str, Any]], max_tokens: int = 700) -> ChatResult | None:
        """Like ``complete`` but for messages that carry pictures, using the vision model first and the primary model as a fallback.
        Only providers that can take pictures are tried (OpenRouter and OmniRoute); a local text-only model is skipped."""
        s = self.settings
        self.stats["calls"] += 1
        for endpoint in self.endpoints():
            if endpoint.name == "openrouter":
                models = [m for m in dict.fromkeys((s.vision_model, s.openrouter_model)) if m]
            elif endpoint.name == "omniroute":
                models = [s.omniroute_model]
            else:
                continue
            for model in models:
                key = f"{endpoint.name}:{model}:vision"
                if self._cooldown.get(key, 0.0) > time.monotonic():
                    continue
                try:
                    payload = self._payload(model, messages, None, 0.2, False)
                    payload["max_tokens"] = max_tokens
                    data = await self._post(endpoint, payload)
                    choices = data.get("choices") or []
                    content = _THINK_RE.sub("", str(((choices[0] if choices else {}).get("message") or {}).get("content") or "")).strip()
                except Exception as exc:  # network error, a model that cannot take pictures (400/404), bad payload
                    logger.warning("LLM %s failed on a picture: %s", key, type(exc).__name__)
                    self._record_failure(key, exc)
                    continue
                if content:
                    self._failures.clear()
                    self.stats.update(ok=self.stats["ok"] + 1, last_provider=endpoint.name, last_model=model, last_error=None,
                                      last_ok_at=datetime.now(timezone.utc).isoformat())
                    return ChatResult(content=content, tool_calls=[], provider=endpoint.name, model=model)
        self.stats["failed"] += 1
        return None

    # ── internals ───────────────────────────────────────────────────
    async def _call(
        self,
        endpoint: Endpoint,
        model: str,
        key: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        json_mode: bool,
    ) -> ChatResult | None:
        use_text = bool(tools) and key in self._text_protocol
        if use_text:
            payload = self._payload(model, self._to_text_protocol(messages, tools or []), None, temperature, json_mode)
        else:
            payload = self._payload(model, messages, tools, temperature, json_mode)

        try:
            data = await self._post(endpoint, payload)
        except httpx.HTTPStatusError as exc:
            # 400/422 with tools => the model/endpoint doesn't understand them. Retry once in text mode.
            if tools and not use_text and exc.response.status_code in (400, 404, 422):
                logger.info("%s rejected native tools; switching to text protocol", key)
                self._text_protocol.add(key)
                text_payload = self._payload(model, self._to_text_protocol(messages, tools), None, temperature, json_mode)
                data = await self._post(endpoint, text_payload)
                use_text = True
            else:
                raise

        choices = data.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        content = _THINK_RE.sub("", str(message.get("content") or "")).strip()
        calls = self._parse_native_calls(message.get("tool_calls"))

        if use_text or (tools and not calls and "<tool_call>" in content):
            parsed, content = self._parse_text_calls(content)
            calls = calls or parsed

        if not content and not calls:
            return None
        return ChatResult(content=content, tool_calls=calls, provider=endpoint.name, model=model)

    @staticmethod
    def _payload(
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        json_mode: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": DEFAULT_MAX_TOKENS}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def _post(self, endpoint: Endpoint, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", **endpoint.headers}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"
        response = await self._http().post(endpoint.url, headers=headers, json=payload, timeout=endpoint.timeout)
        if response.status_code == 402:
            # "...but can only afford N": the balance is small, not empty. Ask for less instead of giving up.
            m = _AFFORD_RE.search(response.text or "")
            affordable = int(m.group(1)) - 20 if m else 0
            if affordable >= 256 and affordable < int(payload.get("max_tokens") or 0):
                logger.info("%s: balance only covers %d tokens; retrying with that limit", endpoint.name, affordable)
                response = await self._http().post(endpoint.url, headers=headers, json={**payload, "max_tokens": affordable}, timeout=endpoint.timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse_native_calls(raw: Any) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for item in raw or []:
            fn = (item or {}).get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            args: Any = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except json.JSONDecodeError:
                    args = {"_invalid_json": args[:500]}
            calls.append(
                {"id": item.get("id") or f"call_{uuid.uuid4().hex[:8]}", "name": name, "arguments": args if isinstance(args, dict) else {}}
            )
        return calls

    # ── text-protocol adapter (for models without native tool calling) ──
    @staticmethod
    def _parse_text_calls(content: str) -> tuple[list[dict[str, Any]], str]:
        calls: list[dict[str, Any]] = []
        for match in _TOOL_CALL_RE.finditer(content):
            try:
                obj = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            name = obj.get("name") or obj.get("tool")
            if not name:
                continue
            args = obj.get("arguments") or obj.get("parameters") or {}
            calls.append({"id": f"call_{uuid.uuid4().hex[:8]}", "name": name, "arguments": args if isinstance(args, dict) else {}})
        return calls, _TOOL_CALL_RE.sub("", content).strip()

    @staticmethod
    def _to_text_protocol(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        catalogue = "\n".join(
            f"- {t['function']['name']}: {t['function'].get('description', '')}\n"
            f"  parameters (JSON schema): {json.dumps(t['function'].get('parameters', {}))}"
            for t in tools
        )
        protocol = (
            "\n\nYou can call tools. To call one, reply with ONLY one or more blocks of the form\n"
            '<tool_call>{"name": "<tool name>", "arguments": {...}}</tool_call>\n'
            "and nothing else. You will then receive the results and can continue. "
            "When you have the final answer, reply normally without any <tool_call> block.\n"
            f"Available tools:\n{catalogue}"
        )
        out: list[dict[str, Any]] = []
        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "system" and i == 0:
                out.append({"role": "system", "content": f"{msg.get('content', '')}{protocol}"})
            elif role == "assistant" and msg.get("tool_calls"):
                blocks = "".join(
                    '<tool_call>'
                    + json.dumps({"name": c["function"]["name"], "arguments": json.loads(c["function"]["arguments"] or "{}")})
                    + "</tool_call>"
                    for c in msg["tool_calls"]
                )
                out.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                out.append({"role": "user", "content": f"<tool_result name=\"{msg.get('name', '')}\">{msg.get('content', '')}</tool_result>"})
            else:
                out.append({"role": role, "content": msg.get("content") or ""})
        if out and out[0].get("role") != "system":
            out.insert(0, {"role": "system", "content": protocol.strip()})
        return out
