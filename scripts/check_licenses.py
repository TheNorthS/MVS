"""对许可证扫描产物执行可配置的显式拒绝策略；未知许可证保留待审查报告。"""

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("report")
parser.add_argument("--deny", action="append", default=["AGPL", "SSPL"])
args = parser.parse_args()
rows = json.loads(Path(args.report).read_text(encoding="utf-8"))
blocked = [
    {"name": row["Name"], "license": row.get("License", "UNKNOWN")}
    for row in rows
    if any(term.upper() in row.get("License", "").upper() for term in args.deny)
]
unknown = [row["Name"] for row in rows if row.get("License", "UNKNOWN") == "UNKNOWN"]
print(
    json.dumps(
        {"blocked": blocked, "unknown_requires_review": unknown}, ensure_ascii=False, indent=2
    )
)
raise SystemExit(1 if blocked else 0)
