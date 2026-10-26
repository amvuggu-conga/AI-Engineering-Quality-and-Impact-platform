"""Pluggable LLM providers.

``AIQ_LLM_PROVIDER`` selects the backend:

* ``none`` (default): no LLM; the platform runs fully on deterministic analysis.
* ``openai``: any OpenAI-compatible Chat Completions endpoint (OpenAI, vLLM, LiteLLM proxy,
  Ollama, Bedrock/Vertex gateways...). Set ``AIQ_LLM_BASE_URL`` for non-OpenAI hosts.
* ``azure-openai``: Azure OpenAI; ``AIQ_LLM_BASE_URL`` = ``https://<res>.openai.azure.com/openai/deployments/<deployment>``.
* ``anthropic``: Anthropic Messages API.
* ``package.module:ClassName``: your own class implementing ``LLMProvider``.

The LLM is used for synthesis (change summary, requirement alignment, root-cause narrative,
failure triage). Every LLM output is grounded on evidence collected deterministically and is
optional: if the call fails, the deterministic result is used and the report says so.
"""

from __future__ import annotations

import importlib
import json
import logging
import re
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger(__name__)


class LLMProvider:
    name = "base"

    @property
    def available(self) -> bool:
        return True

    def complete(self, system: str, prompt: str, max_tokens: int = 1500) -> str:
        raise NotImplementedError

    def complete_json(self, system: str, prompt: str, max_tokens: int = 1500) -> dict[str, Any] | None:
        if not self.available:
            return None
        try:
            text = self.complete(system + "\nRespond with a single JSON object and nothing else.", prompt, max_tokens)
        except Exception as exc:  # provider/network failure must never break the pipeline
            log.warning("LLM call failed (%s): %s", self.name, exc)
            return None
        return parse_json_object(text)


class NoLLM(LLMProvider):
    name = "none"

    @property
    def available(self) -> bool:
        return False

    def complete(self, system: str, prompt: str, max_tokens: int = 1500) -> str:
        return ""


class OpenAICompatible(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None, model: str | None, base_url: str | None = None,
                 azure: bool = False, api_version: str | None = None, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.model = model or "gpt-4o-mini"
        self.azure = azure
        self.api_version = api_version or "2024-06-01"
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.http = httpx.Client(timeout=120, transport=transport)
        if azure:
            self.name = "azure-openai"

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, prompt: str, max_tokens: int = 1500) -> str:
        payload: dict[str, Any] = {"messages": [{"role": "system", "content": system},
                                                {"role": "user", "content": prompt}],
                                   "max_tokens": max_tokens, "temperature": 0.1}
        if self.azure:
            url = f"{self.base_url}/chat/completions?api-version={self.api_version}"
            headers = {"api-key": self.api_key or ""}
        else:
            url = f"{self.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            payload["model"] = self.model
        resp = self.http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""


class Anthropic(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str | None, base_url: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.model = model or "claude-sonnet-4-5"
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.http = httpx.Client(timeout=120, transport=transport)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, prompt: str, max_tokens: int = 1500) -> str:
        resp = self.http.post(f"{self.base_url}/v1/messages",
                              headers={"x-api-key": self.api_key or "", "anthropic-version": "2023-06-01"},
                              json={"model": self.model, "system": system, "max_tokens": max_tokens,
                                    "temperature": 0.1, "messages": [{"role": "user", "content": prompt}]})
        resp.raise_for_status()
        return "".join(b.get("text", "") for b in resp.json().get("content", []))


def parse_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                value = json.loads(m.group(0))
                return value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def build_llm(settings: Settings) -> LLMProvider:
    provider = (settings.llm_provider or "none").strip()
    if provider in ("", "none", "off"):
        return NoLLM()
    if provider == "openai":
        return OpenAICompatible(settings.llm_api_key, settings.llm_model, settings.llm_base_url)
    if provider in ("azure", "azure-openai"):
        return OpenAICompatible(settings.llm_api_key, settings.llm_model, settings.llm_base_url, azure=True,
                                api_version=settings.llm_api_version)
    if provider == "anthropic":
        return Anthropic(settings.llm_api_key, settings.llm_model, settings.llm_base_url)
    if ":" in provider:
        module_name, cls_name = provider.split(":", 1)
        cls = getattr(importlib.import_module(module_name), cls_name)
        return cls(settings)
    raise ValueError(f"Unknown AIQ_LLM_PROVIDER '{provider}'")
