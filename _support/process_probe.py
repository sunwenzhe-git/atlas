"""跨平台进程存活探测单源（POSIX `os.kill(pid, 0)` ⇄ Windows `OpenProcess`）。

背景：`os.kill(pid, 0)` 在 Windows 上**不是探活，是杀进程**。CPython 的 Windows 实现
在 `sig` 不是 `CTRL_C_EVENT` / `CTRL_BREAK_EVENT` 时直接调 `TerminateProcess(handle, sig)`：

    >>> os.kill(pid, 0)        # Windows：TerminateProcess(handle, 0)
    >>> # 进程已死，且不抛任何异常 ⇒ 调用方以为「探活成功」

实测：对一个运行中的子进程调 `os.kill(pid, 0)`，子进程 `HasExited=True`、
`ExitCode=1`，而调用**返回 None 不抛异常**。POSIX 上同一个调用只是信号投递探测
（`sig=0` 不投递任何信号），进程毫发无损 —— 两端语义完全相反。

本模块把这个差异收敛到一处，保两条纪律：

1. **POSIX 行为逐字节不变**：仍然 `os.kill(pid, 0)`，异常分类沿用
   `ProcessLookupError`（不存在）/ `PermissionError`（存在但无权限）。
2. **Windows 绝不杀进程**：走 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` +
   `GetExitCodeProcess`，只读查询。三种失败分别处理（见 `_windows_pid_exists`）。

调用方须知：`pid_exists()` 只回答「这个 pid 现在是否对应一个活进程」，
**不保证 pid 未被复用**（任何平台都不保证）。需要更强身份保证时，调用方应自行
比对进程启动时间或其它标识。

纯标准库；不依赖本包内其它模块（避免 `_support` 内部循环依赖）。
"""
from __future__ import annotations

import os

__all__ = ["pid_exists"]

# Windows 常量（`PROCESS_QUERY_LIMITED_INFORMATION` = Vista+，对同用户进程足够且
# 比 `PROCESS_QUERY_INFORMATION` 权限要求更低；跨会话仍可能 ACCESS_DENIED）。
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87


def _windows_pid_exists(pid: int) -> bool:
    """Windows 探活：只读查询，**绝不**调用 `os.kill` / `TerminateProcess`。

    三种失败分支必须分开，否则会把「活着但无权限」误判成「已死」并触发误杀/误拒：

    - `ERROR_INVALID_PARAMETER`(87)：pid 不存在 ⇒ False（这是唯一能确定「已死」的答复）；
    - `ERROR_ACCESS_DENIED`(5)：进程存在但当前身份无权打开 ⇒ **True**（保守判存活）；
    - 其它错误：无法判定 ⇒ True（探活失败不得被解释成「已死」，否则租约会误拒）。
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        code = ctypes.get_last_error()
        if code == _ERROR_INVALID_PARAMETER:
            return False
        if code == _ERROR_ACCESS_DENIED:
            return True
        return True
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def pid_exists(pid: int) -> bool:
    """进程是否存活。

    POSIX：`os.kill(pid, 0)`（信号投递探测，不改动目标进程）。
    Windows：`OpenProcess` + `GetExitCodeProcess` 只读查询。

    `pid <= 0` 一律 False（`os.kill` 对 0 / 负数在 POSIX 上是**广播给进程组**的语义，
    绝不能拿来探活；Windows 上同样无意义）。
    """
    if not isinstance(pid, int) or pid <= 0:
        return False

    if os.name == "nt":
        try:
            return _windows_pid_exists(pid)
        except Exception:  # noqa: BLE001 —— ctypes 不可用 / DLL 异常：不能据此判「已死」
            return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
