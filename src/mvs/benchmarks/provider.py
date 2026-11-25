"""OpenAI Responses HTTP client. Secrets remain in memory and never enter artifacts."""

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import httpx


@dataclass
class ProviderConfig:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    reasoning_effort: str = "low"
    max_output_tokens: int = 2048
    timeout: float = 90

    @classmethod
    def load(cls, model: str, codex_config: str | None = None) -> "ProviderConfig":
        if codex_config:
            config = tomllib.loads(Path(codex_config).read_text(encoding="utf-8"))
            provider = config["model_providers"][config["model_provider"]]
            key = provider.get("experimental_bearer_token") or os.environ.get(
                provider.get("env_key") or "OPENAI_API_KEY", ""
            )
            base = provider["base_url"]
        else:
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise ValueError("Set OPENAI_API_KEY or pass an explicitly selected provider config")
        return cls(base, model, key)


class ProviderError(Exception):
    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class ResponsesProvider:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.http = httpx.AsyncClient(
            timeout=config.timeout,
            follow_redirects=False,
            headers={"Authorization": "Bearer " + config.api_key},
        )

    async def complete(self, instructions: str, history: list[dict], tools: list[dict]) -> dict:
        root = self.config.base_url.rstrip("/")
        url = root + ("/responses" if root.endswith("/v1") else "/v1/responses")
        body = {
            "model": self.config.model,
            "instructions": instructions,
            "input": history,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "reasoning": {"effort": self.config.reasoning_effort},
            "max_output_tokens": self.config.max_output_tokens,
            "store": False,
        }
        try:
            response = await self.http.post(url, json=body)
        except httpx.TimeoutException:
            raise ProviderError("provider_timeout") from None
        except httpx.HTTPError:
            raise ProviderError("provider_network_error") from None
        if response.status_code != 200:
            # Do not persist raw upstream errors: proxies sometimes include credentials/URLs.
            raise ProviderError("provider_http_error", response.status_code)
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            raise ProviderError("provider_invalid_json") from None
        if not isinstance(data.get("output"), list):
            raise ProviderError("provider_invalid_response")
        return data

    async def close(self) -> None:
        await self.http.aclose()
