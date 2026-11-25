from mvs.config import load_config
from mvs.core.registry import Registry
from mvs.infrastructure.mcp.client_manager import ClientManager


async def test_real_registry_lifecycle():
    configs = load_config("configs/servers.example.yaml")
    manager = ClientManager(configs)
    registry = Registry(configs, manager)
    try:
        await registry.discover()
        assert registry.status["demo"] == "online"
        old = registry.get("demo", "add")
        await registry.refresh("demo")
        assert registry.get("demo", "add").revision == old.revision
        assert old.input_schema["properties"]["a"]["type"] == "integer"
    finally:
        await manager.close()
    assert manager.connections == {}
