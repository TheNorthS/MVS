import time

import pytest

from mvs.domain.errors import ShellError
from mvs.infrastructure.native.isolated import isolated_operation


async def test_isolated_conversion_and_cpu_timeout():
    assert await isolated_operation(
        {
            "operation": "adapt",
            "options": [{"name": "n", "value": "2", "position": 0}],
            "schema": {"type": "object", "properties": {"n": {"type": "integer"}}},
        }
    ) == {"n": 2}
    start = time.monotonic()
    with pytest.raises(ShellError) as exc:
        await isolated_operation(
            {
                "operation": "adapt",
                "options": [{"name": "text", "value": "a" * 30000 + "!", "position": 0}],
                "schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "pattern": "^(a+)+$"}},
                },
            }
        )
    assert exc.value.code == "LIMIT_EXCEEDED"
    assert time.monotonic() - start < 10
