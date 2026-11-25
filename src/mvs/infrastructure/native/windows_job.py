"""挂起创建的 Windows 子进程先加入 Job，再恢复主线程，避免后代抢先脱离。"""

import ctypes
import sys
from ctypes import wintypes
from typing import Any


class ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("thread_id", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("base_priority", wintypes.LONG),
        ("delta_priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
    ]


class WindowsJob:
    def __init__(self, memory_mb: int | None = None, cpu_seconds: int | None = None) -> None:
        import win32job  # type: ignore[import-untyped]

        self.handle: Any = win32job.CreateJobObject(None, "")
        try:
            limits = win32job.QueryInformationJobObject(
                self.handle, win32job.JobObjectExtendedLimitInformation
            )
            limits["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            if memory_mb:
                limits["BasicLimitInformation"]["LimitFlags"] |= (
                    win32job.JOB_OBJECT_LIMIT_JOB_MEMORY
                )
                limits["JobMemoryLimit"] = memory_mb * 1024 * 1024
            if cpu_seconds:
                limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_JOB_TIME
                limits["BasicLimitInformation"]["PerJobUserTimeLimit"] = cpu_seconds * 10_000_000
            win32job.SetInformationJobObject(
                self.handle, win32job.JobObjectExtendedLimitInformation, limits
            )
        except Exception:
            self.close()
            raise

    def assign_and_resume(self, pid: int) -> None:
        import win32api  # type: ignore[import-untyped]
        import win32job  # type: ignore[import-untyped]

        process = win32api.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
        try:
            win32job.AssignProcessToJobObject(self.handle, process)
        finally:
            process.Close()
        kernel: Any
        if sys.platform == "win32":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        else:
            raise OSError("Windows Job仅支持Windows平台")
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenThread.restype = wintypes.HANDLE
        kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel.ResumeThread.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        snapshot = kernel.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        if snapshot == wintypes.HANDLE(-1).value:
            raise OSError("无法枚举挂起进程线程")
        resumed = False
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            more = kernel.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.process_id == pid:
                    thread = kernel.OpenThread(0x0002, False, entry.thread_id)
                    if not thread:
                        raise OSError("无法访问挂起线程")
                    try:
                        if kernel.ResumeThread(thread) == 0xFFFFFFFF:
                            raise OSError("无法恢复挂起线程")
                        resumed = True
                    finally:
                        kernel.CloseHandle(thread)
                more = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        if not resumed:
            raise OSError("挂起进程没有可恢复线程")

    def close(self) -> None:
        if self.handle is not None:
            self.handle.Close()
            self.handle = None
