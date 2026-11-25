"""Reproducible deterministic transport/routing benchmark; no model inference claims."""

import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path

from mcp import Client
from mcp.server import MCPServer

from mvs.domain.models import ServerConfig
from mvs.infrastructure.mcp.sdk_v2_adapter import SDKConnection
from mvs.services.shell_service import ShellService


async def benchmark():
    report = {
        "kind": "deterministic_in_process_mcp",
        "llm_task_success_rate": None,
        "llm_selection_accuracy": None,
        "total_tokens": None,
        "rows": [],
    }
    for size in (20, 50, 100, 200):
        server = MCPServer("benchmark")
        for index in range(size):

            def add(a: int, b: int) -> int:
                return a + b

            server.tool(name=f"add_{index}")(add)
        config = ServerConfig(
            "demo", command="unused", allowed_tools=tuple(f"add_{i}" for i in range(size))
        )
        with tempfile.TemporaryDirectory() as directory:
            service = ShellService({"demo": config}, storage_root=Path(directory))
            async with Client(server) as client:
                connection = SDKConnection(config)
                connection.client = client
                service.manager.connections["demo"] = connection
                await service.registry.refresh("demo")
                session = service.sessions.create("local", "local")
                definition_bytes = len(
                    json.dumps(
                        [tool.model_dump(mode="json") for tool in (await client.list_tools()).tools]
                    ).encode()
                )
                for mode in ("native_tools", "json_gateway", "mvs_shell"):
                    times, successes = [], 0
                    for i in range(20):
                        name = f"add_{i % size}"
                        start = time.perf_counter()
                        if mode == "mvs_shell":
                            response = await service.execute(
                                f"/mcp/demo/tools/{name} --a 2 --b 3", session
                            )
                            data = response.data
                        else:
                            args = {"a": 2, "b": 3}
                            if mode == "json_gateway":
                                args = service.adapter.adapt((), {"type": "object"}) | json.loads(
                                    json.dumps(args)
                                )
                            data = (await client.call_tool(name, args)).structured_content
                        times.append((time.perf_counter() - start) * 1000)
                        successes += data == {"result": 5}
                    report["rows"].append(
                        {
                            "tools": size,
                            "mode": mode,
                            "calls": 20,
                            "scripted_success_rate": successes / 20,
                            "median_ms": statistics.median(times),
                            "p95_ms": sorted(times)[18],
                            "native_definition_bytes": definition_bytes,
                            "total_tokens": None,
                            "interaction_rounds": 20,
                        }
                    )
                await service.close()
    return report


if __name__ == "__main__":
    output = asyncio.run(benchmark())
    destination = Path("artifacts/benchmarks/router/results.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))
