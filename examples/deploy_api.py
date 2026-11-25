"""Linux 部署入口：从环境变量加载 MCP 配置、独立令牌和服务器授权。"""

import os
from pathlib import Path

from fastapi import FastAPI

from mvs.api.app import create_app
from mvs.config import load_config
from mvs.security.policy import Principal


def create_app_from_env() -> FastAPI:
    configs = load_config(os.environ["MVS_CONFIG"])
    allowed = {
        item.strip() for item in os.environ["MVS_ALLOWED_SERVERS"].split(",") if item.strip()
    }
    if not allowed or not allowed <= configs.keys():
        raise ValueError("MVS_ALLOWED_SERVERS 必须是配置中存在的非空服务器列表")
    agent_token = os.environ["MVS_AGENT_TOKEN"]
    admin_token = os.environ["MVS_ADMIN_TOKEN"]
    if agent_token == admin_token:
        raise ValueError("模型客户端与管理员必须使用不同令牌")
    tenant = os.environ.get("MVS_TENANT_ID", "default")
    agent = Principal("agent", tenant)
    admin = Principal("operator", tenant, frozenset({"admin"}))
    if os.environ.get("MVS_TRACE_CONSOLE") == "1":
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
    return create_app(
        configs,
        {agent_token: agent, admin_token: admin},
        {(tenant, "agent"): allowed, (tenant, "operator"): allowed},
        Path(os.environ.get("MVS_STORAGE_ROOT", ".mvs")),
    )
