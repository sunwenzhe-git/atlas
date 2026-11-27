"""跨平台命令行拆分单源（POSIX `shlex` ⇄ Windows `shlex(posix=False)`）。

背景：本包多处把「命令字符串」拆成 argv（`extractor_command`、`--smoke`、case 命令、
`legacy_migration.test_command`、`atlas_check` 的只读命令头判定）。此前一律用
`shlex.split(cmd)`，其默认 `posix=True` 会把**反斜杠当转义符**：

    >>> shlex.split(r'C:\\Users\\me\\python.exe C:\\tmp\\a.py')
    ['C:Usersmepython.exe', 'C:tmpa.py']        # ← 反斜杠全被吃掉

在 Windows 上这是**静默改义**：路径不存在、命令启动失败，报错信息还指向一个
语法上合法但不存在的路径，极难归因（实测 `ExtractError: 命令不存在：
C:UserspenziAppDataLocalPythonpython.exe`）。

设计约束：

1. **POSIX 行为绝不能变**：`posix=True` 是 POSIX 平台上 shell 语义的正确映射，
   改动它会破坏引号/转义/空参数语义（例如 `sh -c 'echo x'`）。故非 Windows 平台
   继续走 `shlex.split(cmd)`，逐字节等价。
2. **Windows 走 `posix=False`**：保留反斜杠、按空白切分、成对引号成组。这正是
   `CreateProcess` 的 argv 语义所要求的形态（Windows 无 shell 转义传统）。
3. **失败一律显式**：引号不闭合时 `shlex` 抛 `ValueError`，本模块**不吞**，由调用方
   决定是 `ExtractError` 还是判空。绝不返回「尽力而为的半截 argv」。
4. **纯标准库，无包内依赖**（避免 `_support` 循环依赖）。

调用方须知：`posix=False` 下引号**不被剥离**（`"a b"` → `'"a b"'`）。本模块在
Windows 分支统一剥掉**成对**的包裹引号，使结果可直接交给 `subprocess` 作为 argv
（`subprocess` 不会替你剥引号——带引号的 token 会被当作文件名的一部分，实测
`'"C:\\Program Files\\x.exe"'` 直接 `FileNotFoundError`）。
"""
from __future__ import annotations

import os
import shlex
import subprocess

__all__ = ["split_command", "split_command_posix", "join_command"]


def _strip_paired_quotes(token: str) -> str:
    """剥掉 token 两端**成对**的同一引号（`"a b"` → `a b`，`'a b'` → `a b`）。

    只剥成对的首尾同类引号：`a"b` 这类不含包裹语义的保持原样，避免改义。
    """
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "'"):
        return token[1:-1]
    return token


def split_command(command: str) -> list[str]:
    """按当前平台语义把命令串拆成 argv。

    - POSIX：`shlex.split(command)`（等价于 shell 词法，行为逐字节不变）。
    - Windows：`shlex.split(command, posix=False)` 后剥成对引号（保留反斜杠路径）。

    引号不闭合时抛 `ValueError`（与 `shlex.split` 一致，不吞）。
    """
    if os.name == "nt":
        return [_strip_paired_quotes(tok) for tok in shlex.split(command, posix=False)]
    return shlex.split(command)


def split_command_posix(command: str) -> list[str]:
    """**强制** POSIX 词法拆分（与宿主机无关）。

    仅用于「被解析的串本身是 POSIX 语法」的场合——例如校验/展示一条将要在
    容器或远端 POSIX 环境执行的命令。业务侧的命令字符串解析请用
    `split_command()`，否则在 Windows 上会重演反斜杠被吃的问题。
    """
    return shlex.split(command)


def join_command(argv: list[str]) -> str:
    """`split_command` 的逆运算：把 argv 拼回**可被同一平台重新解析**的命令串。

    为什么不能直接用 `shlex.join`：它固定按 POSIX 规则加单引号，而 POSIX 单引号
    在 Windows 上不是引号——`'C:\\a b'` 会被 `split_command` 当成字面量（引号
    保留在 token 里）⇒ 往返不闭合。Windows 侧改用 `subprocess.list2cmdline`，
    它是 `CreateProcess` 命令行编码的官方实现，与 `split_command(posix=False)`
    构成同一套词法。

    用途：把「实际执行的 argv」写进证据台账（`legacy_migration` 的
    `evidence.command`）后，人和机器都能按本平台重新解析回同一 argv。
    """
    if not argv:
        return ""
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)
