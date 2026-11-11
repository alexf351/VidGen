"""Windows: which programs have a file open.

Windows will not rename or delete a file that another program has open, and the error only
says "in use". The Restart Manager (the service installers use to ask "what is holding this
file?") names the programs, so VidGen can say "21.mp3 is held open by ffmpeg.exe" and can end
an ffmpeg of its own that was left running by a job that hung. Everything here fails soft: on
any other system, or if the lookup itself fails, there is simply no answer.
"""

from __future__ import annotations

import os
from pathlib import Path

OURS = ("ffmpeg", "ffprobe")          # the only programs VidGen itself starts on a run's files


def holders(path: Path) -> list[tuple[int, str]]:
    """[(process id, program name)] of everything that has `path` open. [] when nothing does,
    when it cannot be found out, and always off Windows."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class RM_UNIQUE_PROCESS(ctypes.Structure):
            _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", FILETIME)]

        class RM_PROCESS_INFO(ctypes.Structure):
            _fields_ = [("Process", RM_UNIQUE_PROCESS), ("strAppName", wintypes.WCHAR * 256),
                        ("strServiceShortName", wintypes.WCHAR * 64), ("ApplicationType", ctypes.c_int),
                        ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD),
                        ("bRestartable", wintypes.BOOL)]

        rm = ctypes.WinDLL("rstrtmgr")
        session = wintypes.DWORD(0)
        key = ctypes.create_unicode_buffer(33)                      # CCH_RM_SESSION_KEY + 1
        if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
            return []
        try:
            files = (wintypes.LPCWSTR * 1)(str(path))
            if rm.RmRegisterResources(session, 1, files, 0, None, 0, None) != 0:
                return []
            needed, count, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
            code = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
            if code not in (0, 234) or needed.value == 0:           # 234 = ERROR_MORE_DATA: there are some
                return []
            infos = (RM_PROCESS_INFO * needed.value)()
            count = wintypes.UINT(needed.value)
            if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reasons)) != 0:
                return []
            out = []
            for i in range(count.value):
                pid = int(infos[i].Process.dwProcessId)
                out.append((pid, _image_name(pid) or str(infos[i].strAppName)))
            return out
        finally:
            rm.RmEndSession(session)
    except Exception:
        return []


def _image_name(pid: int) -> str:
    """The program's file name ("ffmpeg.exe"), or "" when Windows will not say."""
    try:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return Path(buf.value).name
        finally:
            kernel.CloseHandle(handle)
    except Exception:
        return ""


def is_ours(name: str) -> bool:
    stem = Path(str(name)).stem.lower()
    return stem in OURS


def describe(found: list[tuple[int, str]]) -> str:
    """"ffmpeg.exe (PID 4312) and chrome.exe (PID 880)", or "" for nothing."""
    names = [f"{name or 'a program'} (PID {pid})" for pid, name in found]
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)


def end_leftovers(found: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """End the ffmpeg / ffprobe processes in `found`, never this process and never anything
    else. Only call this when no job is working on the run: an ffmpeg that still has a run's
    file open then is one a hung or interrupted job left behind. Returns the ones ended."""
    import signal
    ended = []
    for pid, name in found:
        if pid == os.getpid() or not is_ours(name):
            continue
        try:
            os.kill(pid, signal.SIGTERM)                            # TerminateProcess on Windows
            ended.append((pid, name))
        except OSError:
            pass
    return ended
