import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from mvs.api.app import create_app
from mvs.config import load_config
from mvs.security.policy import Principal


async def test_authenticated_api_real_stdio_and_traces(tmp_path):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    a, b = "a" * 32, "b" * 32
    app = create_app(
        load_config("configs/servers.example.yaml"),
        {a: Principal("a", "t", frozenset({"admin"})), b: Principal("b", "t")},
        {("t", "a"): {"demo"}},
        tmp_path,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            assert (await c.post("/api/v1/sessions", json={})).status_code == 401
            c.headers["Authorization"] = "Bearer " + a
            forged = await c.post("/api/v1/sessions", json={"principal_id": "other"})
            assert forged.status_code == 422
            session = (await c.post("/api/v1/sessions", json={})).json()["session_id"]
            result = await c.post(
                "/api/v1/shell/execute",
                json={"session_id": session, "command": "/mcp/demo/tools/add --a 2 --b 3"},
            )
            assert result.json()["data"] == {"result": 5}, result.text
            assert (await c.get("/api/v1/health/ready")).status_code == 200
            assert "mvs_shell_requests_total" in (await c.get("/metrics")).text
            c.headers["Authorization"] = "Bearer " + b
            assert (await c.get("/api/v1/servers")).json() == []
            assert (
                await c.post(
                    "/api/v1/shell/execute", json={"session_id": session, "command": "pwd"}
                )
            ).status_code == 404
            assert (await c.post("/api/v1/servers/demo/refresh")).status_code == 403
            assert (
                app.state.telemetry.registry.get_sample_value(
                    "mvs_policy_denials_total", {"server": "demo", "reason": "admin_required"}
                )
                == 1
            )
            assert (await c.get("/metrics")).status_code == 403
            assert (
                app.state.telemetry.registry.get_sample_value(
                    "mvs_policy_denials_total", {"server": "unknown", "reason": "admin_required"}
                )
                == 1
            )
    spans = exporter.get_finished_spans()
    assert any(
        span.name == "mvs.api.execute" and "mvs.request_id" in span.attributes for span in spans
    )
    tool_span = next(span for span in spans if span.name == "mvs.tool.invoke")
    shell_span = next(span for span in spans if span.name == "mvs.shell.execute")
    assert tool_span.context.trace_id == shell_span.context.trace_id
