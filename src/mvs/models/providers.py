"""统一Responses风格消息给Chat Completions与Anthropic，保留工具调用对应关系。"""

import json
from typing import Any

import httpx

from mvs.benchmarks.provider import ProviderConfig, ProviderError, ResponsesProvider


def chat_history(instructions: str, history: list[dict]) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": instructions}]
    for item in history:
        kind = item.get("type")
        if kind == "function_call":
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": item["call_id"],
                            "type": "function",
                            "function": {"name": item["name"], "arguments": item["arguments"]},
                        }
                    ],
                }
            )
        elif kind == "function_call_output":
            messages.append(
                {"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]}
            )
        elif item.get("role"):
            content = item.get("content", "")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content)
            messages.append({"role": item["role"], "content": content})
    return messages


class CompatibleProvider(ResponsesProvider):
    def __init__(self, config: ProviderConfig, protocol: str) -> None:
        super().__init__(config)
        self.protocol = protocol

    async def complete(self, instructions: str, history: list[dict], tools: list[dict]) -> dict:
        if self.protocol == "responses":
            return await super().complete(instructions, history, tools)
        base = self.config.base_url.rstrip("/")
        base = base if base.endswith("/v1") else base + "/v1"
        messages = chat_history(instructions, history)
        if self.protocol == "chat_completions":
            body = {
                "model": self.config.model,
                "messages": messages,
                "max_completion_tokens": self.config.max_output_tokens,
            }
            if tools:
                body.update(
                    tools=[
                        {
                            "type": "function",
                            "function": {k: v for k, v in tool.items() if k != "type"},
                        }
                        for tool in tools
                    ],
                    parallel_tool_calls=False,
                )
            url, headers = base + "/chat/completions", {}
        elif self.protocol == "anthropic":
            converted = []
            for message in messages[1:]:
                if message["role"] == "tool":
                    converted.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": message["tool_call_id"],
                                    "content": message["content"],
                                }
                            ],
                        }
                    )
                elif message.get("tool_calls"):
                    converted.append(
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": call["id"],
                                    "name": call["function"]["name"],
                                    "input": json.loads(call["function"]["arguments"]),
                                }
                                for call in message["tool_calls"]
                            ],
                        }
                    )
                else:
                    converted.append({"role": message["role"], "content": message["content"]})
            body = {
                "model": self.config.model,
                "system": instructions,
                "messages": converted,
                "max_tokens": self.config.max_output_tokens,
            }
            if tools:
                body["tools"] = [
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "input_schema": tool["parameters"],
                    }
                    for tool in tools
                ]
            url, headers = (
                base + "/messages",
                {"x-api-key": self.config.api_key, "anthropic-version": "2023-06-01"},
            )
        else:
            raise ProviderError("unsupported_protocol")
        try:
            response = await self.http.post(url, json=body, headers=headers)
        except httpx.TimeoutException:
            raise ProviderError("provider_timeout") from None
        except httpx.HTTPError:
            raise ProviderError("provider_network_error") from None
        if response.status_code != 200:
            raise ProviderError("provider_http_error", response.status_code)
        try:
            raw = response.json()
            if self.protocol == "chat_completions":
                choice = raw["choices"][0]
                message = choice["message"]
                output = [
                    {
                        "type": "function_call",
                        "name": call["function"]["name"],
                        "call_id": call["id"],
                        "arguments": call["function"]["arguments"],
                    }
                    for call in message.get("tool_calls", [])
                ]
                if message.get("content"):
                    output.append(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": message["content"]}],
                        }
                    )
                u = raw.get("usage")
                usage = (
                    None
                    if u is None
                    else {
                        "input_tokens": u["prompt_tokens"],
                        "output_tokens": u["completion_tokens"],
                        "total_tokens": u["total_tokens"],
                    }
                )
                complete = choice.get("finish_reason") in {"stop", "tool_calls"}
            else:
                output = []
                for block in raw["content"]:
                    if block["type"] == "tool_use":
                        output.append(
                            {
                                "type": "function_call",
                                "name": block["name"],
                                "call_id": block["id"],
                                "arguments": json.dumps(block["input"]),
                            }
                        )
                    elif block["type"] == "text":
                        output.append(
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": block["text"]}],
                            }
                        )
                u = raw.get("usage")
                usage = (
                    None
                    if u is None
                    else {
                        "input_tokens": u["input_tokens"]
                        + u.get("cache_read_input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0),
                        "output_tokens": u["output_tokens"],
                    }
                )
                if usage:
                    usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
                complete = raw.get("stop_reason") in {"end_turn", "tool_use"}
            return {
                "id": raw.get("id"),
                "model": raw.get("model"),
                "output": output,
                "usage": usage,
                "status": "completed" if complete else "incomplete",
            }
        except (KeyError, TypeError, ValueError):
            raise ProviderError("provider_invalid_response") from None


class RoutedProvider:
    """仅模型请求失败时切换；工具执行永远不在此处重放。"""

    def __init__(self, providers: list[Any]) -> None:
        if not providers:
            raise ValueError("模型路由不能为空")
        self.providers = providers

    async def complete(self, instructions: str, history: list[dict], tools: list[dict]) -> dict:
        for index, provider in enumerate(self.providers):
            try:
                result = await provider.complete(instructions, history, tools)
                result["route_index"] = index
                return result
            except ProviderError as exc:
                if index == len(self.providers) - 1 or (
                    exc.status is not None and exc.status not in {429, 502, 503, 504}
                ):
                    raise
        raise ProviderError("all_routes_failed")

    async def close(self) -> None:
        for provider in self.providers:
            await provider.close()
