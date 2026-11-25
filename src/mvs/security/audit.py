import json
import logging
import re
from typing import Any

SENSITIVE = re.compile(r"password|secret|token|authorization|api.?key|credential", re.I)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE.search(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def audit(event: dict) -> None:
    logging.getLogger("mvs.audit").info(json.dumps(redact(event), ensure_ascii=False))
