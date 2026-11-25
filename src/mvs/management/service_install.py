"""注册当前用户级开机/登录服务；使用固定参数调用各平台服务管理器。"""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


def install_service(root: Path, remove: bool = False) -> None:
    executable = shutil.which("mvs")
    if not executable:
        raise ValueError("mvs不在PATH中")
    if sys.platform == "linux":
        directory = Path.home() / ".config/systemd/user"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "mvs.service"
        if remove:
            subprocess.run(["systemctl", "--user", "disable", "--now", "mvs.service"], check=True)
            path.unlink(missing_ok=True)
        else:

            def quote(value: str) -> str:
                return (
                    '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
                )

            path.write_text(
                "[Unit]\nDescription=MVS Console\nAfter=network-online.target\n"
                "[Service]\nType=simple\nExecStart="
                + quote(executable)
                + " serve --home "
                + quote(str(root))
                + "\nRestart=on-failure\nUMask=0077\n[Install]\nWantedBy=default.target\n",
                encoding="utf-8",
            )
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        if not remove:
            subprocess.run(["systemctl", "--user", "enable", "--now", "mvs.service"], check=True)
    elif sys.platform == "darwin":
        path = Path.home() / "Library/LaunchAgents/io.mvs.console.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        domain = f"gui/{os.getuid()}"
        if remove:
            subprocess.run(["launchctl", "bootout", domain, str(path)], check=True)
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(
                plistlib.dumps(
                    {
                        "Label": "io.mvs.console",
                        "ProgramArguments": [executable, "serve", "--home", str(root)],
                        "RunAtLoad": True,
                        "KeepAlive": True,
                    }
                )
            )
            subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    elif sys.platform == "win32":
        if remove:
            subprocess.run(["schtasks", "/Delete", "/TN", "MVS Console", "/F"], check=True)
        else:
            command = subprocess.list2cmdline([executable, "serve", "--home", str(root)])
            subprocess.run(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    "MVS Console",
                    "/SC",
                    "ONLOGON",
                    "/TR",
                    command,
                    "/F",
                ],
                check=True,
            )
            subprocess.run(["schtasks", "/Run", "/TN", "MVS Console"], check=True)
    else:
        raise ValueError("不支持的平台")
