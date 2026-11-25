import asyncio
import json

import httpx
import pytest

from mvs.benchmarks.provider import ProviderConfig, ProviderError
from mvs.management.backup import backup, restore
from mvs.management.gate import RuntimeGate
from mvs.management.store import StateStore
from mvs.models.providers import CompatibleProvider, RoutedProvider
from mvs.security.rules import permitted, validate_rules


def test_vault_migration_history_and_encrypted_backup(tmp_path):
    root = tmp_path / "source"
    store = StateStore(root)
    token = store.initialize()
    revision, state = store.read()
    state["secrets"]["MVS_SECRET_TEST"] = "unique-secret-value"
    store.save(revision, state)
    raw = store.db.execute("SELECT body FROM state").fetchone()[0]
    assert "unique-secret-value" not in raw and "$encrypted" in raw
    assert store.historical(1)["secrets"] == {}
    store.close()
    archive = tmp_path / "snapshot.mvsb"
    backup(root, archive, "long-backup-password")
    assert b"unique-secret-value" not in archive.read_bytes()
    with pytest.raises(ValueError):
        restore(archive, tmp_path / "bad", "wrong-password")
    restore(archive, tmp_path / "recovered", "long-backup-password")
    restored = StateStore(tmp_path / "recovered")
    assert restored.read()[1]["secrets"]["MVS_SECRET_TEST"] == "unique-secret-value"
    assert restored.authenticate(token)
    restored.close()


async def test_parallel_gate_writer_waits():
    gate = RuntimeGate()
    entered = 0
    release = asyncio.Event()
    both = asyncio.Event()

    async def reader():
        nonlocal entered
        async with gate.read():
            entered += 1
            if entered == 2:
                both.set()
            await release.wait()

    tasks = [asyncio.create_task(reader()) for _ in range(2)]
    await asyncio.wait_for(both.wait(), 1)

    async def writer():
        async with gate:
            return True

    writing = asyncio.create_task(writer())
    await asyncio.sleep(0)
    assert not writing.done()
    release.set()
    await asyncio.gather(*tasks)
    assert await writing


def test_parameter_rules():
    rules = {
        "demo": {
            "tools": ["echo"],
            "arguments": {
                "echo": {
                    "type": "object",
                    "properties": {"text": {"enum": ["ok"]}},
                    "required": ["text"],
                }
            },
        }
    }
    assert permitted(rules, "demo", "tools", "echo")
    assert permitted(rules, "demo", "tools", "echo", {"text": "ok"})
    assert not permitted(rules, "demo", "tools", "echo", {"text": "bad"})
    assert not permitted(rules, "demo", "tools", "add")
    with pytest.raises(ValueError):
        validate_rules({"demo": {"tools": ["echo"], "arguments": {"echo": {"pattern": "(a+)+$"}}}})


@pytest.mark.parametrize("protocol", ["chat_completions", "anthropic"])
async def test_model_adapters(protocol):
    provider = CompatibleProvider(
        ProviderConfig("https://invalid.example/v1", "fixture", "key"), protocol
    )
    await provider.http.aclose()

    def respond(request):
        body = json.loads(request.content)
        if protocol == "chat_completions":
            assert body["messages"][-1]["role"] == "tool"
            return httpx.Response(
                200,
                json={
                    "model": "fixture",
                    "choices": [{"finish_reason": "stop", "message": {"content": "done"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                },
            )
        assert body["messages"][-1]["content"][0]["type"] == "tool_result"
        return httpx.Response(
            200,
            json={
                "model": "fixture",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "done"}],
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        )

    provider.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    result = await provider.complete(
        "system",
        [
            {"role": "user", "content": "hi"},
            {"type": "function_call", "name": "tool", "arguments": "{}", "call_id": "c"},
            {"type": "function_call_output", "call_id": "c", "output": "ok"},
        ],
        [],
    )
    assert result["usage"]["total_tokens"] == 13
    assert result["output"][0]["content"][0]["text"] == "done"
    await provider.close()


async def test_failover_only_for_transient_model_errors():
    calls = []

    class Provider:
        def __init__(self, status):
            self.status = status

        async def complete(self, *args):
            calls.append(self.status)
            if self.status:
                raise ProviderError("provider_http_error", self.status)
            return {"output": []}

        async def close(self):
            return None

    routed = RoutedProvider([Provider(503), Provider(None)])
    assert (await routed.complete("", [], []))["route_index"] == 1
    assert calls == [503, None]
    calls.clear()
    with pytest.raises(ProviderError):
        await RoutedProvider([Provider(401), Provider(None)]).complete("", [], [])
    assert calls == [401]
