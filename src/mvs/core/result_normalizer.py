import json
from uuid import uuid4

from mvs.core.schema_adapter import SchemaAdapter
from mvs.domain.errors import ShellError
from mvs.domain.models import ResultEnvelope, ToolInvocation


def preview(text: str, limit: int = 8192) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    return raw[:limit].decode("utf-8", errors="ignore"), len(raw) > limit


class ResultNormalizer:
    def __init__(self) -> None:
        self.assets: dict[str, dict] = {}
        self.asset_bytes = 0

    def normalize(
        self, result: dict, invocation: ToolInvocation, output_schema: dict | None, duration_ms: int
    ) -> ResultEnvelope:
        if len(json.dumps(result).encode()) > 4 * 1024 * 1024:
            raise ShellError("RESULT_TOO_LARGE", "Tool result exceeds 4 MiB")
        data = result.get("structured_content")
        success = not result.get("is_error", False)
        error = (
            None
            if success
            else (
                "COMMAND_FAILED" if result.get("backend") == "native" else "TOOL_EXECUTION_FAILED"
            )
        )
        if success and output_schema is not None:
            try:
                SchemaAdapter().validate(data, output_schema, max_bytes=4 * 1024 * 1024)
            except ShellError:
                error, success = "INVALID_TOOL_OUTPUT", False
        texts, refs, kinds = [], [], []
        for block in result.get("content", []):
            kind = block.get("type", "unknown")
            if kind == "text":
                texts.append(block.get("text", ""))
            else:
                size = len(json.dumps(block).encode())
                if self.asset_bytes + size > 16 * 1024 * 1024:
                    raise ShellError("RESULT_TOO_LARGE", "Asset quota exceeded")
                ref = "asset_" + uuid4().hex
                self.assets[ref] = block
                self.asset_bytes += size
                refs.append(ref)
                kinds.append(kind)
        return ResultEnvelope(
            invocation.request_id,
            invocation.server_id,
            invocation.tool_name,
            success,
            data,
            tuple(texts),
            tuple(refs),
            error,
            duration_ms,
            {"untrusted": True, "asset_types": kinds, "backend": result.get("backend", "mcp")},
        )
