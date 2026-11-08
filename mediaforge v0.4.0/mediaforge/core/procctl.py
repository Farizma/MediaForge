"""Suspend / resume an OS process (used to pause ffmpeg mid-encode).

POSIX:   SIGSTOP / SIGCONT.
Windows: ntdll!NtSuspendProcess / NtResumeProcess (the same calls Process Explorer uses).
"""
from __future__ import annotations

import os
import signal
import sys


def _win(fn_name: str, pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_SUSPEND_RESUME = 0x0800
    k32, nt = ctypes.windll.kernel32, ctypes.windll.ntdll
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False
    try:
        fn = getattr(nt, fn_name)
        fn.argtypes = [wintypes.HANDLE]
        fn.restype = ctypes.c_long  # NTSTATUS, 0 = success
        return fn(handle) == 0
    finally:
        k32.CloseHandle(handle)


def suspend(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _win("NtSuspendProcess", pid)
    try:
        os.kill(pid, signal.SIGSTOP)
        return True
    except OSError:
        return False


def resume(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _win("NtResumeProcess", pid)
    try:
        os.kill(pid, signal.SIGCONT)
        return True
    except OSError:
        return False
