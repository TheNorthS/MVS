import asyncio
import sys
import time
from pathlib import Path

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


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS RSS监测专用验证")
async def test_darwin_memory_monitor_stops_allocation(tmp_path):
    script = tmp_path / "allocate.py"
    script.write_text(
        "import time\nchunks=[]\n"
        "while True:\n chunks.append(bytearray(8*1024*1024))\n time.sleep(0.02)\n"
    )
    from mvs.infrastructure.native import posix_launcher

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(posix_launcher.__file__)),
        "64",
        "3",
        sys.executable,
        str(script),
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(5):
            _, stderr = await process.communicate()
        assert process.returncode == -9, stderr.decode(errors="replace")
    finally:
        if process.returncode is None:
            import os
            import signal

            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
