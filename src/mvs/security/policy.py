from dataclasses import dataclass

from mvs.domain.models import ServerConfig, ToolDescriptor
from mvs.security.rules import permitted


@dataclass(frozen=True)
class Principal:
    principal_id: str
    tenant_id: str
    roles: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PolicyDecision:
    outcome: str
    reason: str


class PolicyEngine:
    def __init__(
        self,
        configs: dict[str, ServerConfig],
        grants: dict[tuple[str, str], set[str]] | None = None,
        rules: dict[tuple[str, str], list[dict]] | None = None,
    ) -> None:
        self.configs = configs
        self.grants = grants or {}
        self.rules = rules or {}

    def permits(
        self, principal: Principal, server: str, kind: str, name: str, args: dict | None = None
    ) -> bool:
        restrictions = self.rules.get((principal.tenant_id, principal.principal_id))
        return restrictions is None or any(
            permitted(rule, server, kind, name, args) for rule in restrictions
        )

    def authorize_discovery(self, principal: Principal, server_id: str) -> PolicyDecision:
        config = self.configs.get(server_id)
        allowed = self.grants.get((principal.tenant_id, principal.principal_id), set())
        return PolicyDecision(
            "allow" if config and config.enabled and server_id in allowed else "deny",
            "Trusted discovery grant required",
        )

    def authorize_call(
        self, principal: Principal, tool: ToolDescriptor, arguments: dict
    ) -> PolicyDecision:
        if self.authorize_discovery(principal, tool.server_id).outcome != "allow":
            return PolicyDecision("deny", "No server grant")
        config = self.configs[tool.server_id]
        if not self.permits(principal, tool.server_id, "tools", tool.name, arguments):
            return PolicyDecision("deny", "参数或工具不在用户授权范围")
        if tool.name in config.approval_tools:
            return PolicyDecision("approval_required", "Administrator approval required")
        return PolicyDecision(
            "allow" if tool.name in config.allowed_tools else "deny",
            "Explicit tool allowlist required",
        )

    def authorize_result(self, principal: Principal, owner: tuple[str, str]) -> PolicyDecision:
        return PolicyDecision(
            "allow" if owner == (principal.tenant_id, principal.principal_id) else "deny",
            "Results are private to their owner and tenant",
        )

    def visible_servers(self, principal: Principal) -> set[str]:
        return {
            key
            for key in self.configs
            if self.authorize_discovery(principal, key).outcome == "allow"
        }

    def visible_tools(self, principal: Principal, tools: dict) -> dict:
        return {
            key: tool
            for key, tool in tools.items()
            if self.authorize_discovery(principal, tool.server_id).outcome == "allow"
            and tool.name
            in (
                self.configs[tool.server_id].allowed_tools
                + self.configs[tool.server_id].approval_tools
            )
            and self.permits(principal, tool.server_id, "tools", tool.name)
        }
