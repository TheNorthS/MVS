"""Synthetic read-only business tasks. Oracles are never placed in model context."""

import hashlib
import json
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    task_id: str
    prompt: str
    tool: str
    arguments: dict


SPECS: list[tuple[str, str, dict]] = [
    ("stock", "Check current warehouse stock", {"sku": "SKU-482", "warehouse": "north"}),
    ("price", "Look up current product price in a currency", {"sku": "SKU-317", "currency": "EUR"}),
    ("order", "Fetch current order status", {"order_id": "ORD-931", "include_items": True}),
    ("shipment", "Track a shipment by tracking ID", {"tracking_id": "TRK-627"}),
    ("invoice", "Get outstanding invoice balance", {"invoice_id": "INV-208"}),
    (
        "exchange",
        "Convert a monetary amount between currencies",
        {"amount": 123.45, "source": "USD", "target": "EUR"},
    ),
    ("weather", "Fetch weather for a city and date", {"city": "Hangzhou", "date": "2026-11-20"}),
    ("employee", "Look up employee directory details", {"employee_id": "EMP-619"}),
    (
        "repository",
        "Search software repositories by topic and minimum stars",
        {"query": "mcp gateway", "min_stars": 250},
    ),
    ("customer", "Look up a customer account", {"customer_id": "CUS-325"}),
    (
        "usage",
        "Summarize API usage for a project and month",
        {"project": "atlas", "month": "2026-10"},
    ),
    ("subscription", "Read subscription status", {"subscription_id": "SUB-873"}),
    (
        "tax",
        "Calculate invoice tax from net amount and rate",
        {"net_amount": 1200.50, "rate": 0.13},
    ),
    (
        "route",
        "Find route distance between two cities",
        {"origin": "Shanghai", "destination": "Nanjing", "mode": "rail"},
    ),
    ("loyalty", "Read customer loyalty balance", {"customer_id": "CUS-719"}),
    (
        "capacity",
        "Get current available capacity of a warehouse",
        {"warehouse": "south", "unit": "pallet"},
    ),
    (
        "health",
        "Read current service health in a region",
        {"service": "checkout", "region": "ap-east"},
    ),
    (
        "appointments",
        "List free appointment slots for a doctor",
        {"doctor_id": "DOC-912", "date": "2026-11-21", "limit": 3},
    ),
    (
        "documents",
        "Search documents using a nested filter",
        {"query": "deployment", "filter": {"language": "zh", "published": True}},
    ),
    (
        "tickets",
        "Fetch support tickets by a list of IDs",
        {"ids": ["T-191", "T-782"], "include_closed": False},
    ),
]


def schema_for(value: object) -> dict:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, list):
        return {"type": "array", "items": schema_for(value[0])}
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {key: schema_for(v) for key, v in value.items()},
            "required": list(value),
            "additionalProperties": False,
        }
    return {"type": "string"}


def tools_for(size: int, seed: int = 42) -> list[dict]:
    if size not in (20, 50, 100, 200):
        raise ValueError("Tool size must be 20/50/100/200")
    tools = []
    for i in range(size):
        name, description, arguments = SPECS[i % len(SPECS)]
        if i >= 20:
            era = i // 20
            name = f"archive{era}_{name}"
            description = f"Historical snapshot batch {era}, NOT current data. " + description
        tools.append(
            {"name": name, "description": description, "input_schema": schema_for(arguments)}
        )
    random.Random(seed).shuffle(tools)
    return tools


def tasks() -> list[Task]:
    return [
        Task(
            f"task_{i:02}",
            f"{description}. Use current data, not archives. "
            f"Parameters: {json.dumps(arguments, ensure_ascii=False)}. "
            "Call the appropriate tool. Return only its verification_code as the final answer.",
            name,
            arguments,
        )
        for i, (name, description, arguments) in enumerate(SPECS)
    ]


def tool_result(name: str, arguments: dict) -> dict:
    payload = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False).encode()
    code = "v_" + hashlib.sha256(b"mvs-evaluation-fixture-v1:" + payload).hexdigest()[:20]
    return {"verification_code": code, "source_tool": name, "data": arguments, "untrusted": True}
