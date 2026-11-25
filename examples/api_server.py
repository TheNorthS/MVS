"""Run with uv run --extra api python examples/api_server.py; token from environment."""

import os

import uvicorn
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from mvs.api.app import create_app
from mvs.config import load_config
from mvs.security.policy import Principal

if __name__ == "__main__":
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    app = create_app(
        load_config("configs/servers.example.yaml"),
        {os.environ["MVS_API_TOKEN"]: Principal("local", "local", frozenset({"admin"}))},
        {("local", "local"): {"demo"}},
    )
    uvicorn.run(app, host="127.0.0.1", port=8080)
