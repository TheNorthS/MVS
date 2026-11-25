"""隔离处理不可信Schema/管道计算，JSON协议只选择固定操作，不执行动态代码。"""

import json
import sys
from typing import Any

from mvs.core.schema_adapter import SchemaAdapter, check_schema
from mvs.domain.errors import ShellError
from mvs.parser.ast import RawOption
from mvs.pipeline.transforms import transform
from mvs.pipeline.types import pipe_value


def main() -> None:
    result: Any
    payload = json.loads(sys.stdin.buffer.read(5 * 1024 * 1024))
    try:
        if payload["operation"] == "adapt":
            result = SchemaAdapter().adapt(
                tuple(RawOption(**option) for option in payload["options"]), payload["schema"]
            )
        elif payload["operation"] == "transform":
            result = transform(
                pipe_value(payload["data"]), payload["verb"], tuple(payload["args"])
            ).value
        elif payload["operation"] == "validate":
            SchemaAdapter().validate(payload["data"], payload["schema"], max_bytes=4 * 1024 * 1024)
            result = True
        elif payload["operation"] == "check_schema":
            check_schema(payload["schema"])
            result = True
        else:
            raise ShellError("INVALID_ARGUMENT", "未知隔离操作")
        print(json.dumps({"result": result}, ensure_ascii=False))
    except ShellError as exc:
        print(json.dumps({"error": exc.as_dict()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
