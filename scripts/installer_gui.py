"""Windows/macOS/Linux桌面图形安装入口，需要已安装带Tk的Python。"""

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

root = tk.Tk()
root.title("MVS 安装向导")
root.geometry("550x260")
path = tk.StringVar()
base = Path(__file__).resolve().parent
bundled = next(base.glob("*.whl"), None)
if bundled:
    path.set(str(bundled))
ttk.Label(root, text="MVS 工具管理平台", font=("", 18)).pack(pady=20)
ttk.Label(root, text="选择发布wheel。安装完成后自动初始化本机实例。").pack()
ttk.Entry(root, textvariable=path, width=65).pack(pady=12)
ttk.Button(
    root,
    text="选择安装包",
    command=lambda: path.set(filedialog.askopenfilename(filetypes=[("Python wheel", "*.whl")])),
).pack()
status = tk.StringVar(value="需要联网下载依赖；不会覆盖已有配置。")
ttk.Label(root, textvariable=status).pack(pady=12)


def install():
    chosen = Path(path.get())
    if not chosen.is_file():
        messagebox.showerror("安装失败", "请选择有效wheel")
        return
    button.config(state="disabled")
    status.set("正在安装，请稍候…")

    def work():
        try:
            offline = base / "install.py"
            if offline.exists() and (base / "manifest.json").exists():
                subprocess.run([__import__("sys").executable, str(offline)], check=True)
                root.after(0, lambda: status.set("离线安装完成，运行 mvs serve --open。"))
                return
            subprocess.run(
                ["uv", "tool", "install", "--python", "3.12", "--force", str(chosen) + "[console]"],
                check=True,
            )
            binary = subprocess.check_output(["uv", "tool", "dir", "--bin"], text=True).strip()
            executable = Path(binary) / ("mvs.exe" if __import__("os").name == "nt" else "mvs")
            subprocess.run([str(executable), "init"], check=True)
            root.after(0, lambda: status.set("安装完成！运行 mvs serve --open 打开后台。"))
        except Exception:
            root.after(0, lambda: status.set("安装失败，请检查uv、网络和安装包。"))
        finally:
            root.after(0, lambda: button.config(state="normal"))

    threading.Thread(target=work, daemon=True).start()


button = ttk.Button(root, text="安装并初始化", command=install)
button.pack()
root.mainloop()
