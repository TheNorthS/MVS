import argparse
import json

import httpx
import pytest

from mvs.benchmarks.provider import ProviderConfig, ProviderError, ResponsesProvider
from mvs.benchmarks.runner import run


@pytest.mark.parametrize(
    "status,payload,error",
    [
        (502, {"error": {"message": "secret-key"}}, "provider_http_error"),
        (200, {}, "provider_invalid_response"),
    ],
)
async def test_provider_errors_are_sanitized(status, payload, error):
    provider = ResponsesProvider(ProviderConfig("https://invalid.example/v1", "test", "secret-key"))
    await provider.http.aclose()
    provider.http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
    )
    try:
        with pytest.raises(ProviderError) as exc:
            await provider.complete("instructions", [], [])
        assert exc.value.code == error
        assert "secret-key" not in str(exc.value)
    finally:
        await provider.close()


async def test_responses_wire_contract_no_secret_artifact():
    config = ProviderConfig("https://invalid.example", "test", "secret-key")
    assert "secret-key" not in repr(config)
    provider = ResponsesProvider(config)
    await provider.http.aclose()

    def handle(request):
        assert request.url.path == "/v1/responses"
        assert request.headers["Authorization"] == "Bearer secret-key"
        data = json.loads(request.content)
        assert data["store"] is False
        assert data["parallel_tool_calls"] is False
        assert "secret-key" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "output": [],
                "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            },
        )

    provider.http = httpx.AsyncClient(
        headers={"Authorization": "Bearer secret-key"}, transport=httpx.MockTransport(handle)
    )
    try:
        assert (await provider.complete("instructions", [], []))["usage"]["total_tokens"] == 3
    finally:
        await provider.close()


async def test_resume_preserves_failed_episode_and_rejects_changed_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-no-network")
    calls = []

    class Provider:
        def __init__(self, config):
            self.config = config

        async def complete(self, *args):
            calls.append(1)
            raise ProviderError("provider_http_error", 502)

        async def close(self):
            pass

    monkeypatch.setattr("mvs.benchmarks.runner.ResponsesProvider", Provider)
    args = argparse.Namespace(
        output=str(tmp_path),
        model="test",
        codex_config=None,
        max_output_tokens=100,
        reasoning_effort="low",
        tasks=1,
        sizes=[20],
        modes=["native_tools"],
        max_rounds=2,
        seed=42,
        concurrency=1,
        max_total_tokens=10000,
    )
    await run(args)
    original = (tmp_path / "episodes/20_native_tools_task_00.json").read_bytes()
    await run(args)
    assert len(calls) == 1
    assert original == (tmp_path / "episodes/20_native_tools_task_00.json").read_bytes()
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["summary"][0]["total_tokens"] is None
    assert summary["summary"][0]["task_success_rate"] == 0
    args.model = "changed"
    with pytest.raises(ValueError, match="manifest differs"):
        await run(args)
