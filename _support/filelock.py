"""跨平台文件锁单源（POSIX `fcntl.flock` ⇄ Windows `msvcrt.locking`）。

背景：本包多处需要**跨进程互斥**（`guarded_continuation.WriteLock` 的收口写锁、
`semantic_contracts._publication_lock` 的发布锁、`incident` / `evidence_archive` /
`ablation` 的台账锁）。此前这些点直接 `import fcntl`，在 Windows 上于 **import 阶段**
即 `ModuleNotFoundError`，导致 `atlas workflow` 整条需求级执行链起不来。

设计约束（与既有 POSIX 语义逐条对齐，不允许静默放宽）：

1. **非阻塞语义保留**：POSIX `LOCK_EX | LOCK_NB` ⇔ Windows `LK_NBLCK`；
   **阻塞语义保留**：POSIX `LOCK_EX` ⇔ Windows `LK_LOCK`。两者不可互换——
   `WriteLock` 依赖非阻塞抛错来实现「已被占用」的拒绝路径。
2. **异常契约不变**：POSIX 上 `flock(LOCK_NB)` 失败抛 `BlockingIOError`；
   Windows `msvcrt.locking` 失败抛 `PermissionError`（errno 13）。本模块**统一成
   `BlockingIOError`**，使调用方的 `except BlockingIOError` 在两端等价。
3. **锁定区域**：`msvcrt.locking` 锁定的是「从当前文件位置起 N 字节」，不是整文件，
   且**锁随文件区段存活**。调用方常在持锁后 `ftruncate(0)` + 重写元数据；只要锁区段
   落在数据区之外（`_WINDOWS_LOCK_OFFSET`），truncate / write 不会破坏锁的安全边界
   （实测：锁在 offset 0 时 truncate 后互斥仍有效，但高偏移更稳，见 `_windows_lock_region`）。
4. **不提供锁时的替代保证**：与 `docs_governance` 的 `fcntl = None` 降级不同——那里靠
   `O_APPEND` + 单次 `os.write` 的原子追加边界兜底。本模块服务的是**没有此类替代保证**
   的互斥点，故 **不支持「无锁降级」**：平台若无可用锁原语，直接抛
   `InterProcessLockError`（fail-closed），绝不静默放行。

纯标准库；不依赖本包内其它模块（避免 `_support` 内部循环依赖）。
"""
from __future__ import annotations

import errno
import os
import sys
import time

__all__ = [
    "InterProcessLockError",
    "lock_exclusive",
    "lock_exclusive_nonblocking",
    "unlock",
    "is_supported",
]

# Windows 上锁区段选在远高于实际元数据的位置（1 MiB），使调用方对文件头部的
# ftruncate / 重写不会影响锁区段。文件实际大小不变（锁定不写入）。
_WINDOWS_LOCK_OFFSET = 1024 * 1024

# 阻塞锁的重试间隔（秒）。语义对齐 POSIX `flock(LOCK_EX)` 的**无限等待**；
# 只是把「重试」从 CRT 内部挪到本模块，以便控制等待时长与异常口径。
_WINDOWS_BLOCKING_RETRY_SEC = 0.05


class InterProcessLockError(OSError):
    """当前平台无可用文件锁原语，或加锁过程出现非「已被占用」的失败。"""


def _fcntl():  # pragma: no cover - 平台分支
    try:
        import fcntl  # type: ignore[import-not-found]
    except ImportError:
        return None
    return fcntl


def _msvcrt():  # pragma: no cover - 平台分支
    try:
        import msvcrt  # type: ignore[import-not-found]
    except ImportError:
        return None
    return msvcrt


def is_supported() -> bool:
    """当前平台是否具备可用的跨进程文件锁原语。"""
    return _fcntl() is not None or _msvcrt() is not None


def _windows_lock_region(fd: int) -> int:
    """把 fd 定位到锁区段起点，返回该起点。"""
    os.lseek(fd, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
    return _WINDOWS_LOCK_OFFSET


def _lock(fd: int, *, blocking: bool) -> None:
    """在 fd 上加排他锁；`blocking=False` 时拿不到立刻抛 `BlockingIOError`。"""
    fcntl = _fcntl()
    if fcntl is not None:
        flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, flags)
        return

    msvcrt = _msvcrt()
    if msvcrt is None:  # pragma: no cover - 理论不可达
        raise InterProcessLockError(
            "当前平台既无 fcntl 也无 msvcrt，无法提供跨进程文件锁"
            f"（platform={sys.platform}）")

    if not blocking:
        _windows_lock_once(fd, msvcrt)
        return

    # **不能用 `msvcrt.LK_LOCK` 充当 POSIX 的阻塞 `flock(LOCK_EX)`**。
    # CRT 的 `LK_LOCK` 只重试 10 次、每次约 1 秒，约 10 秒后抛
    # `EDEADLK(36) Resource deadlock avoided` 而**放弃**；POSIX 的 `flock` 是
    # 无限期阻塞直到对方释放。二者不等价，而调用点（`evidence_archive` /
    # `incident`）用 `except OSError: pass` 兜底 ⇒ 拿不到锁时**静默无锁执行**，
    # 两个进程同时写台账，互斥保证消失（实测 LK_LOCK 在持锁者存活时约 9 秒放弃）。
    #
    # 故自行用非阻塞原语轮询，保住「一直等到拿到为止」的语义。
    while True:
        try:
            _windows_lock_once(fd, msvcrt)
            return
        except BlockingIOError:
            time.sleep(_WINDOWS_BLOCKING_RETRY_SEC)


def _windows_lock_once(fd: int, msvcrt) -> None:
    """Windows 单次**非阻塞**加锁；冲突统一抛 `BlockingIOError`。

    Windows 以 `PermissionError(errno 13)` 表达「区段已被锁定」。归一成 POSIX 的
    `BlockingIOError`，保证调用方 `except BlockingIOError` 两端同形。
    """
    _windows_lock_region(fd)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EDEADLK):
            raise BlockingIOError(
                errno.EAGAIN, "文件锁已被其它进程占用", getattr(exc, "filename", None)
            ) from exc
        raise


def _unlock(fd: int) -> None:
    fcntl = _fcntl()
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return

    msvcrt = _msvcrt()
    if msvcrt is None:  # pragma: no cover - 理论不可达
        raise InterProcessLockError(
            "当前平台既无 fcntl 也无 msvcrt，无法释放跨进程文件锁"
            f"（platform={sys.platform}）")
    _windows_lock_region(fd)
    try:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        # msvcrt 对「未持有的区段」解锁会抛 PermissionError(13)，而 POSIX flock(LOCK_UN)
        # 对未持锁的 fd 是无操作。调用点普遍写成 `try: flock(UN) finally: close(fd)` 或
        # `try: 解锁 except OSError: pass`，若在此处抛错会掩盖真正要上抛的异常，故对齐
        # POSIX 语义：解锁失败不抛出（释放本就不保证之前一定持锁）。
        pass


def lock_exclusive_nonblocking(fd: int) -> None:
    """排他锁，拿不到立刻抛 `BlockingIOError`（对齐 `flock(LOCK_EX|LOCK_NB)`）。"""
    _lock(fd, blocking=False)


def lock_exclusive(fd: int) -> None:
    """排他锁，阻塞直到拿到（对齐 `flock(LOCK_EX)`）。"""
    _lock(fd, blocking=True)


def unlock(fd: int) -> None:
    """释放锁（对齐 `flock(LOCK_UN)`）。"""
    _unlock(fd)
