"""Split and join command strings for direct subprocess execution, not a shell."""
from __future__ import annotations

import os
import shlex
import subprocess

__all__ = ["split_command", "split_command_posix", "join_command"]


def _split_windows(command: str) -> list[str]:
    """Parse with the same argv grammar Windows passes to CreateProcess."""
    import ctypes
    from ctypes import wintypes

    if "\0" in command:
        raise ValueError("embedded null character")
    # Keep ordinary single-quoted fragments working (they are common in Atlas
    # command strings), but quote them with Windows rules before the native
    # parser sees them.
    pieces: list[str] = []
    start = 0
    in_double = False
    i = 0
    while i < len(command):
        if command[i] == '"':
            backslashes = 0
            j = i - 1
            while j >= start and command[j] == "\\":
                backslashes += 1
                j -= 1
            if backslashes % 2 == 0:
                in_double = not in_double
        if command[i] == "'" and not in_double:
            end = command.find("'", i + 1)
            if end < 0:
                raise ValueError("No closing quotation")
            pieces.append(command[start:i])
            pieces.append(subprocess.list2cmdline([command[i + 1:end]]))
            i = end + 1
            start = i
            continue
        i += 1
    if start:
        command = "".join(pieces) + command[start:]

    parse = ctypes.WinDLL("shell32", use_last_error=True).CommandLineToArgvW
    parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    free = ctypes.WinDLL("kernel32").LocalFree
    free.argtypes = [wintypes.HLOCAL]
    free.restype = wintypes.HLOCAL

    marker = "atlas-argv-end"
    argc = ctypes.c_int()
    argv = parse(f"atlas {command} {marker}", ctypes.byref(argc))
    if not argv:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if argv[argc.value - 1] != marker:
            raise ValueError("No closing quotation")
        return argv[1:argc.value - 1]
    finally:
        free(argv)


def split_command(command: str) -> list[str]:
    """Use POSIX shlex or the Windows native argv grammar."""
    if os.name == "nt":
        return _split_windows(command)
    return shlex.split(command)


def split_command_posix(command: str) -> list[str]:
    """Force POSIX lexical splitting even on Windows."""
    return shlex.split(command)


def join_command(argv: list[str]) -> str:
    """Render argv so split_command() round-trips on this platform."""
    if not argv:
        return ""
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)
