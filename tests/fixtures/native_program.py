"""测试夹具：固定管理员程序，不能从虚拟命令提交源码。"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

mode, value = sys.argv[1:3]
if mode == "echo":
    print(
        json.dumps(
            {"value": value, "cwd": os.getcwd(), "secret": os.environ.get("MVS_UNRELATED_SECRET")},
            ensure_ascii=False,
        )
    )
elif mode == "fail":
    print("failure detail", file=sys.stderr)
    raise SystemExit(7)
elif mode == "flood":
    while True:
        print("x" * 4096, flush=True)
elif mode == "sleep":
    time.sleep(20)
elif mode == "tree":
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "child", value])
    Path(value + ".pid").write_text(str(process.pid))
    time.sleep(20)
elif mode == "child":
    time.sleep(1.5)
    Path(value).write_text("child survived")
