"""Windows 可移植性回归钉：跨平台文件锁 / 目录守卫 / 落盘字节一致性。

背景（本批引入的移植面）：本包此前在 `_support/guarded_continuation.py` 与
`_support/semantic_contracts.py` 顶部裸 `import fcntl`，Windows 上于 **import 阶段**
即 `ModuleNotFoundError`，致 `atlas workflow` 整条需求级执行链不可用（实测：22 个
测试模块收集失败、2404 → 不可收集）。本文件把三处修复各自钉住：

M-W1  **锁原语跨平台且语义等价**：非阻塞拿不到锁必须抛 `BlockingIOError`
       （POSIX `flock` 与 Windows `msvcrt` 的异常类型本就不同，此处锁住归一化）；
       持锁后 `ftruncate`+重写元数据不得破坏互斥（Windows 锁区段必须避开数据区）。
M-W2  **目录守卫不放行链接**：`safe_mkdir_nofollow` 拒绝 symlink，且 Windows 上
       还必须拒绝 **junction**（`mklink /J` 建的目录链接在 `is_symlink()` 上看不出来，
       实测为 False —— 不加 `st_reparse_tag` 判断就是静默放行逃逸）。
M-W3  **落盘字节 == 自报摘要**：`write_exclusive` 写出的字节必须与
       `write_json_exclusive` 返回的 sha256 对应同一份字节。文本模式在 Windows 上
       会把 `\n` 译成 `\r\n`，导致审计侧 `file_sha256(p) != file_sha` 恒判篡改
       （实测 `raw_receipt_tampered` 假阳性）。

平台口径：M-W1/M-W2 的 junction 段只在 Windows 上有意义，POSIX 上跳过（不是放宽，
是「该形态在该平台不存在」）；M-W3 两端都跑，且是两端都会暴露差异的恒等式检查。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support import filelock  # noqa: E402
from _support.guarded_continuation import (  # noqa: E402
    PlanError,
    append_wal,
    atomic_write_json_durable,
    assert_no_symlink_components,
    safe_mkdir_nofollow,
    write_exclusive,
    write_json_exclusive,
)

IS_WINDOWS = os.name == "nt"


# ─────────────────────────────────────────────────────────── M-W1 锁原语

def test_w1_lock_primitives_are_available_on_this_platform() -> None:
    """M-W1: 当前平台必须至少有一种锁原语，否则 `atlas workflow` 全链不可用。"""
    assert filelock.is_supported() is True


def test_w1_nonblocking_lock_raises_blocking_io_error(tmp_path: Path) -> None:
    """M-W1: 第二个持有者必须拿到 `BlockingIOError`（异常类型跨平台归一）。

    变异方向：把 Windows 分支的 `PermissionError → BlockingIOError` 归一化摘掉，
    本钉在 Windows 上即红（POSIX 仍绿 —— 这正是要钉的点：调用方 `except
    BlockingIOError` 必须两端同形，否则写链互斥在 Windows 上静默变成「拿不到就崩」）。
    """
    lock_file = tmp_path / "w.lock"
    fd1 = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    fd2 = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    try:
        filelock.lock_exclusive_nonblocking(fd1)
        with pytest.raises(BlockingIOError):
            filelock.lock_exclusive_nonblocking(fd2)
    finally:
        filelock.unlock(fd1)
        os.close(fd1)
        os.close(fd2)


def test_w1_lock_survives_truncate_and_rewrite(tmp_path: Path) -> None:
    """M-W1: 持锁后 `ftruncate(0)` + 重写元数据，互斥必须仍然有效。

    `WriteLock.acquire()` 正是「先加锁、再 ftruncate 写持有者元数据」；Windows 的
    `msvcrt.locking` 锁的是**文件区段**，若锁区段落进数据区就会被 truncate 冲掉。
    变异方向：把 `_WINDOWS_LOCK_OFFSET` 退回 0，本钉在 Windows 上观察到「第二个 fd
    也能拿到锁」即红。
    """
    lock_file = tmp_path / "w2.lock"
    fd1 = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    fd2 = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    try:
        filelock.lock_exclusive_nonblocking(fd1)
        os.lseek(fd1, 0, os.SEEK_SET)
        os.ftruncate(fd1, 0)
        os.lseek(fd1, 0, os.SEEK_SET)
        os.write(fd1, b'{"pid": 1}\n')
        with pytest.raises(BlockingIOError):
            filelock.lock_exclusive_nonblocking(fd2)
    finally:
        filelock.unlock(fd1)
        os.close(fd1)
        os.close(fd2)


def test_w1_unlock_on_unlocked_fd_is_noop(tmp_path: Path) -> None:
    """M-W1: 解锁未持有锁的 fd 不得抛错（对齐 POSIX `flock(LOCK_UN)` 语义）。

    调用点普遍写成 `try: 解锁 finally: close`；若解锁抛错会掩盖真正要上抛的异常。
    变异方向：摘掉 `_unlock` 里的 `except OSError: pass`，本钉在 Windows 上红。
    """
    lock_file = tmp_path / "w3.lock"
    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    try:
        filelock.unlock(fd)  # 不应抛出
    finally:
        os.close(fd)


# ─────────────────────────────────────────────────────────── M-W2 目录守卫

def test_w2_safe_mkdir_creates_and_is_idempotent(tmp_path: Path) -> None:
    """M-W2 正控：逐级建目录可用且幂等（两端都跑，防移植分支把正常路径弄坏）。"""
    p1 = safe_mkdir_nofollow(tmp_path, (".atlas", "runs", "continuations", "locks"))
    assert p1.is_dir()
    p2 = safe_mkdir_nofollow(tmp_path, (".atlas", "runs", "continuations", "locks"))
    assert p2 == p1


@pytest.mark.parametrize("bad", ["..", "a/b", "a\\b", ""])
def test_w2_safe_mkdir_rejects_illegal_segments(tmp_path: Path, bad: str) -> None:
    """M-W2 坏输入：非法目录段一律拒（含路径分隔符注入）。"""
    with pytest.raises(PlanError):
        safe_mkdir_nofollow(tmp_path, (bad,))


def test_w2_safe_mkdir_rejects_symlink_component(tmp_path: Path) -> None:
    """M-W2 坏输入：路径中的 symlink 段必须拒。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("本平台/权限不支持创建目录 symlink")
    with pytest.raises(PlanError):
        safe_mkdir_nofollow(tmp_path, ("link", "evil"))
    with pytest.raises(PlanError):
        assert_no_symlink_components(tmp_path, link / "x.txt")


@pytest.mark.skipif(IS_WINDOWS, reason="POSIX dir_fd/O_NOFOLLOW path")
def test_w2_safe_mkdir_normalizes_posix_symlink_open_error(tmp_path: Path) -> None:
    outside = tmp_path / "outside_posix"
    outside.mkdir()
    link = tmp_path / "link_posix"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("本平台/权限不支持创建目录 symlink")
    with pytest.raises(PlanError):
        safe_mkdir_nofollow(tmp_path, ("link_posix", "child"))


@pytest.mark.skipif(not IS_WINDOWS, reason="junction 是 Windows 专有重解析点")
def test_w2_safe_mkdir_rejects_windows_junction(tmp_path: Path) -> None:
    """M-W2 坏输入：Windows junction 必须当作链接拒绝。

    关键：junction 在 `Path.is_symlink()` / `os.path.islink()` / `lstat().st_mode`
    三者上**都是 False**（实测），只有 `st_reparse_tag` 非 0 才认得出。变异方向：
    把 `_is_link_like` 的 Windows 分支摘掉，本钉红 —— 而 POSIX 上的 symlink 钉仍然
    绿，因此这条是 junction 盲区唯一守门人。
    """
    outside = tmp_path / "outside_j"
    outside.mkdir()
    junction = tmp_path / "jump"
    res = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"无法创建 junction：{res.stderr or res.stdout}")
    # 先证「junction 在 is_symlink 上看不出来」，否则本钉会因为假前提而空转
    assert junction.is_symlink() is False
    assert getattr(os.lstat(junction), "st_reparse_tag", 0) != 0
    with pytest.raises(PlanError):
        safe_mkdir_nofollow(tmp_path, ("jump", "evil"))
    with pytest.raises(PlanError):
        assert_no_symlink_components(tmp_path, junction / "x.txt")


@pytest.mark.skipif(not IS_WINDOWS, reason="junction 是 Windows 专有重解析点")
def test_w2_protected_write_paths_reject_junction_parent(tmp_path: Path) -> None:
    """All mutation helpers must reject a junction, not just safe_mkdir."""
    outside = tmp_path / "outside_write"
    outside.mkdir()
    junction = tmp_path / "write_jump"
    res = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"无法创建 junction：{res.stderr or res.stdout}")
    run = junction / "run"
    with pytest.raises(PlanError):
        write_exclusive(junction / "new.txt", "x")
    with pytest.raises(PlanError):
        atomic_write_json_durable(junction / "new.json", {"x": 1})
    with pytest.raises(PlanError):
        append_wal(junction, {"phase": "INTENT"})
    assert not (outside / "new.txt").exists()
    assert not (outside / "new.json").exists()
    assert not run.exists()


# ─────────────────────────────────────────────────────────── M-W3 字节一致性

def test_w3_exclusive_write_bytes_match_reported_digest(tmp_path: Path, monkeypatch) -> None:
    """M-W3: `write_json_exclusive` 返回的 sha256 必须等于落盘字节的 sha256。

    这是审计链的恒等式：`atlas_continue` 用 `file_sha256(p) != action["raw_receipt_sha256"]`
    判篡改。文本模式在 Windows 把 `\n` 写成 `\r\n` ⇒ 落盘字节与自报摘要不同 ⇒
    **真链被判 `raw_receipt_tampered`**（实测，非假想）。变异方向：去掉
    `os.fdopen(..., newline="")` 的 `newline=""`，本钉在 Windows 上红（POSIX 绿）。
    """
    target = tmp_path / "raw.json"
    payload = {"b": 2, "a": 1, "note": "换行\n在中间"}
    reported = write_json_exclusive(target, payload)
    on_disk = hashlib.sha256(target.read_bytes()).hexdigest()
    assert on_disk == reported, (
        "落盘字节与自报摘要不一致：写入被文本模式做了换行转换（Windows CRLF）")
    # 语义也对得上：读回来就是同一份 JSON
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_w3_write_exclusive_does_not_translate_newlines(tmp_path: Path) -> None:
    """M-W3 对照：`write_exclusive` 原样落盘，不得插入 `\\r`。"""
    target = tmp_path / "text.txt"
    write_exclusive(target, "a\nb\n")
    assert target.read_bytes() == b"a\nb\n"


# ─────────────────────────────────────────────────────────── M-W4 argv 拆分
#
# 背景：`shlex.split(cmd)` 默认 `posix=True`，把**反斜杠当转义符吃掉**：
#     >>> shlex.split(r'C:\Users\me\python.exe C:\tmp\a.py')
#     ['C:Usersmepython.exe', 'C:tmpa.py']
# 于是 `extractor_command` / `--smoke` / case 命令在 Windows 上全部指向不存在的
# 路径，且报错信息语法合法、极难归因（实测 `ExtractError: 命令不存在：
# C:Userspenzi...python.exe`）。POSIX 侧必须**逐字节不变**——`posix=True` 是
# shell 词法的正确映射，改动它会破坏 `sh -c 'echo x'` 这类引号语义。

def test_w4_split_command_preserves_windows_paths() -> None:
    """M-W4: 反斜杠路径不得被吃掉；带空格的路径引号必须剥掉。"""
    from _support.argv_split import split_command

    raw = r'"C:\Program Files\Python\python.exe" D:\tmp\a.py --flag'
    got = split_command(raw)
    if IS_WINDOWS:
        assert got == [r"C:\Program Files\Python\python.exe", r"D:\tmp\a.py", "--flag"]
    else:
        # POSIX 侧：双引号内的反斜杠按 shell 规则保留（原 shlex 行为）
        assert got[0].endswith("python.exe") and got[-1] == "--flag"


def test_w4_split_command_matches_shlex_on_posix_semantics() -> None:
    """M-W4 对照：POSIX 语义的串在两端都不得改义（引号/空参数/单引号）。"""
    from _support.argv_split import split_command

    cases = [
        "python -m pytest -q",
        "sh -c 'echo x'",
        'node "a b.js" --x',
    ]
    for raw in cases:
        got = split_command(raw)
        if not IS_WINDOWS:
            import shlex
            assert got == shlex.split(raw), f"POSIX 行为被改动：{raw!r}"


def test_w4_unclosed_quote_raises_value_error() -> None:
    """M-W4 坏输入：引号未闭合必须显式失败，不得返回半截 argv。"""
    from _support.argv_split import split_command

    with pytest.raises(ValueError):
        split_command('python "unterminated')


def test_w4_round_trip_reaches_subprocess_with_original_argv() -> None:
    from _support.argv_split import join_command, split_command

    args = ["", 'embedded "quote"', 'C:\\work dir\\', "it's literal"]
    argv = [sys.executable, "-c", "import json, sys; print(json.dumps(sys.argv[1:]))", *args]
    parsed = split_command(join_command(argv))
    assert parsed == argv
    assert json.loads(subprocess.check_output(parsed, text=True)) == args


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows argv syntax")
def test_w4_windows_native_option_and_embedded_quote_round_trip() -> None:
    from _support.argv_split import join_command, split_command

    assert split_command('python --path="C:\\Program Files\\Atlas" --ok') == [
        "python", "--path=C:\\Program Files\\Atlas", "--ok"]
    argv = ["python", 'say "hello"', "C:\\work dir\\"]
    assert split_command(join_command(argv)) == argv


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows argv syntax")
def test_w4_space_path_does_not_depend_on_repo_checkout(tmp_path: Path) -> None:
    from _support.argv_split import split_command

    exe = tmp_path / "Project Harness" / "python.exe"
    assert " " in str(exe)
    command = subprocess.list2cmdline([str(exe), "--root", str(tmp_path / "a b")])
    assert split_command(command) == [str(exe), "--root", str(tmp_path / "a b")]


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows native command-line quoting")
def test_w4_single_quoted_python_argument_remains_compatible() -> None:
    from _support.argv_split import split_command

    command = (subprocess.list2cmdline([sys.executable])
               + " -c 'import sys; print(sys.argv[-1])' -- pre'fix with space'post")
    argv = split_command(command)
    assert subprocess.check_output(argv, text=True).strip() == "prefix with spacepost"


# ─────────────────────────────────────────────────────────── M-W5 shell 脚本 LF
#
# 背景：Windows 上 `core.autocrlf=true` 会在 **checkout 时**把 `.sh` 转成 CRLF，
# bash 读到的每行带 `\r`：`$'\r': command not found` / `set: pipefail: invalid option name`。
# 实测本仓 `install.sh` 在基线提交里是纯 LF（CRLF=0），但 Windows 上检出后变成
# 56 行全 CRLF ⇒ 源码直装整条路不可用。
#
# **判据必须打在「仓库内容 + 属性规则」上，不能打在工作区字节上**：
# 工作区是否已按属性重新检出，取决于用户何时 clone、`git am` 是否刷新、以及
# 本地 `core.autocrlf` 设置——那是**环境状态**，不是仓库正确性。实测反例：
# `git am` 应用补丁后，未改动文件的旧 CRLF 工作区副本会原样留着（`w/crlf`），
# 而 `i/lf` + `attr/text eol=lf` 都已正确；此时判工作区会让**正确的补丁**变红。
#
# 正确判据（`git ls-files --eol`）：所有 `.sh` 必须 `i/lf`（索引里是 LF）
# 且 attr 带 `eol=lf`。工作区状态仅作提示，不参与判定。

def test_w5_shell_scripts_are_lf_in_index_with_eol_attr() -> None:
    """M-W5: 仓内所有 `.sh` 在**索引**中必须是 LF，且属性规则为 `eol=lf`。

    变异方向：把 `.gitattributes` 里的 `*.sh text eol=lf` 删掉 ⇒ 本钉红
    （属性缺失时 attr 不含 eol=lf）。把 `.sh` 以 CRLF 提交 ⇒ i/crlf ⇒ 本钉红。
    """
    r = subprocess.run(["git", "ls-files", "--eol", "--", "*.sh"],
                       cwd=str(PKG_ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"git 不可用或非 git 工作树：{r.stderr.strip()[:120]}")

    problems = []
    seen = 0
    for line in r.stdout.splitlines():
        # 形如：`i/lf    w/crlf  attr/text eol=lf      \tinstall.sh`
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        seen += 1
        tokens = meta.split()
        # attr 段形如 `attr/text eol=lf`：`attr/text` 与 `eol=lf` 是两个独立 token，
        # 且 `eol=lf` 只在属性真正声明了 eol 时出现（缺省时只有 `attr/text`）。
        has_attr = any(t.startswith("attr/") for t in tokens)
        attrs = " ".join(t for t in tokens if t.startswith("attr/") or t.startswith("eol="))
        if not has_attr:
            problems.append(f"{path}: 无属性条目（.gitattributes 未覆盖 *.sh）")
        elif "eol=lf" not in attrs:
            problems.append(f"{path}: 属性未声明 eol=lf（实际 {attrs}）")
    if seen == 0:
        pytest.skip("仓内没有 .sh 文件")
    assert not problems, "shell 脚本的 LF 纪律未落实：\n  " + "\n  ".join(problems)


def test_w5_worktree_shell_scripts_lf_when_reported() -> None:
    """M-W5 提示项：工作区 `.sh` 若是 CRLF，应在**本机重新检出**后消失。

    本测试**不判失败**——工作区换行是环境状态（受 clone 时机、`git am`、本地
    `core.autocrlf` 影响），不是仓库正确性。但它把「本机当前是否有 CRLF 副本」
    如实打出来，便于使用者自行 `git checkout -- .` 修复。
    """
    r = subprocess.run(["git", "ls-files", "--eol", "--", "*.sh"],
                       cwd=str(PKG_ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("git 不可用")
    crlf = [ln.split("\t", 1)[1] for ln in r.stdout.splitlines()
            if "\t" in ln and "w/crlf" in ln]
    if crlf:
        print(f"\n[提示] 本机工作区以下 .sh 为 CRLF（执行 `git checkout -- .` 可修复）：{crlf}")
    assert True


def test_w5_gitattributes_declares_lf_for_shell() -> None:
    """M-W5: `.gitattributes` 必须显式声明 `*.sh eol=lf`（防 autocrlf 再犯）。"""
    ga = PKG_ROOT / ".gitattributes"
    assert ga.is_file(), "缺少 .gitattributes：Windows 上 core.autocrlf 会把 .sh 转成 CRLF"
    text = ga.read_text(encoding="utf-8")
    assert "*.sh" in text and "eol=lf" in text


# ─────────────────────────────────────────────────────────── M-W6 解释器探测
#
# 背景：Windows 上 `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe` 是应用商店的
# **别名占位壳**——`command -v python3` 命中，但执行时以 rc=49 退出且**零输出**
# （未安装商店版时）。`install.sh` 原实现只看 `command -v`，于是把「没装 Python」
# 误报成「install.py 莫名失败」（实测 rc=49 / 无 stderr）。

def test_w6_install_sh_probes_interpreter_by_execution_not_by_name() -> None:
    """M-W6: `install.sh` 必须**实跑**候选解释器验证版本，不能只看 `command -v`。

    判据分两层，缺一不可：
    1. **行为层**：`--help` 真跑一次必须 rc=0（说明 wrapper 能起来、解释器能跑）；
    2. **结构层**：源码里必须有实跑校验（`version_info`）与 `ATLAS_PYTHON` 覆盖通道。

    只做第 2 层是「字符串存在性检查」——把真逻辑注释掉、只留词，测试照样绿。
    故第 1 层是本钉的咬合力所在（变异方向：把探测改成只 `command -v`，第 1 层在
    装了 Store 假壳的机器上仍可能绿，但第 2 层会红；把 `--help` 委托弄断，第 1 层红）。
    """
    sh = (PKG_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "version_info" in sh, (
        "install.sh 未验证 Python 版本：Windows Store 的 python3.exe 假壳会以 rc=49 静默失败")
    assert "ATLAS_PYTHON" in sh, "install.sh 必须保留 ATLAS_PYTHON 显式覆盖通道"

    # 行为层：真跑一次。`--help` 由 install.py 承载，rc=0 说明 wrapper → 解释器 → 委托全链通。
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("本机无 bash，无法行为验证 install.sh（结构层已验）")
    # Windows 上 PATH 里的 bash 常是 WSL 中继壳（System32/WindowsApps）：
    # 与宿主不共享文件系统视图，跑本仓相对路径会假红 —— 显式跳过，不静默放宽。
    if os.name == "nt" and ("WindowsApps" in bash or "System32" in bash):
        pytest.skip(f"PATH 上的 bash 是 WSL 中继壳（{bash}），非 Git Bash；结构层已验")
    res = subprocess.run([bash, str(PKG_ROOT / "install.sh"), "--help"],
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, (
        f"install.sh --help 失败（rc={res.returncode}）："
        f"{(res.stderr or res.stdout).strip()[:300]}")


# ─────────────────────────────────────────────────────────── M-W7 进程探活
#
# 背景：`os.kill(pid, 0)` 在 POSIX 上是「信号投递探测」（sig=0 不投递任何信号），
# 在 **Windows 上是 `TerminateProcess(handle, 0)`** —— 不抛异常、直接杀进程：
#
#     >>> os.kill(pid, 0)      # Windows
#     >>> proc.poll()          # 3221225794 = 0xC0000005 STATUS_ACCESS_VIOLATION
#
# 原 `verify_write_lock_lease` 用它探活 ⇒ 租约核验一次就把持锁进程杀了，
# 随后必然误报「持有进程不存活」；`e2e_console._pid_alive` 同型（且永远返回 True）。

def test_w7_pid_probe_does_not_kill_the_target_process() -> None:
    """M-W7: 探活**不得**改变目标进程状态（Windows 上 `os.kill` 会杀进程）。

    变异方向：把 `process_probe.pid_exists` 的 Windows 分支换回 `os.kill(pid, 0)`，
    本钉在 Windows 上红（子进程被杀，`poll()` 非 None）。

    **为什么必须 sleep 再断言**：Windows 上 `TerminateProcess` 返回后，
    `Popen.poll()` 仍读到 `None` 约 0.5s 才反映退出（实测），立即断言会漏判——
    这正是本钉第一版的形式：变异未被发现。现在等到进程确实稳定再判。
    """
    from _support.process_probe import pid_exists

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert pid_exists(proc.pid) is True, "刚起的子进程必须判存活"
        # 连续探活多次：任何一次若走了 TerminateProcess，下面就会观测到退出
        assert pid_exists(proc.pid) is True
        assert pid_exists(proc.pid) is True
        # 给内核/句柄表留出反映退出的时间（实测约 0.5s），再判存活
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is None, (
            f"探活把子进程杀了（exit={proc.poll()}）："
            "Windows 上 os.kill(pid, 0) 是 TerminateProcess，不是探活")
        # 独立旁证：不依赖 Popen 缓存，直接用系统查询确认进程仍在
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {proc.pid}", "/NH"],
                               capture_output=True, text=True)
            assert str(proc.pid) in (r.stdout or ""), (
                f"system 查询显示 pid {proc.pid} 已不存在：探活杀掉了进程")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


def test_w7_pid_probe_reports_dead_after_exit() -> None:
    """M-W7 正控：进程退出后必须判「不存活」（否则探活恒真，租约核验形同虚设）。"""
    from _support.process_probe import pid_exists

    proc = subprocess.Popen([sys.executable, "-c", "pass"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.wait(timeout=30)
    assert pid_exists(proc.pid) is False


@pytest.mark.parametrize("pid", [0, -1, -9999])
def test_w7_pid_probe_rejects_nonpositive_pid(pid: int) -> None:
    """M-W7 坏输入：`pid <= 0` 必须判 False。

    POSIX 上 `os.kill(0, sig)` 是**广播给整个进程组**的语义，`os.kill(-1, sig)`
    广播给所有有权限的进程 —— 拿来做探活是灾难。探活入口必须先挡掉。
    """
    from _support.process_probe import pid_exists

    assert pid_exists(pid) is False


# ─────────────────────────────────────────────────────────── M-W8 阻塞锁语义
#
# 背景：`msvcrt.LK_LOCK` **不是** POSIX 的 `flock(LOCK_EX)`。CRT 只重试 10 次、
# 每次约 1 秒，约 10 秒后抛 `EDEADLK(36) Resource deadlock avoided` 而放弃
# （实测等待方在 9.08s 放弃，而持锁者仍活着）。POSIX 的 flock 是**无限期阻塞**。
#
# 影响：`evidence_archive._index_lock` 与 `incident._publish` 都写成
# `except OSError: pass` —— 拿不到锁就**静默无锁执行**，两个进程同时写台账，
# 互斥保证在 Windows 上消失且不报错。

def test_w8_blocking_lock_waits_rather_than_giving_up(tmp_path: Path) -> None:
    """M-W8: 阻塞锁必须在持有方释放后拿到，**不得**超时放弃。

    用线程而非进程：目的是测「等待不放弃」这一语义，不引入跨进程调度噪音。
    等待窗口取 12s —— 超过 CRT `LK_LOCK` 的 10 次重试上限（实测约 9s 放弃），
    因此本钉在旧实现（`LK_LOCK`）上必然红。

    用 `tmp_path` 而非 `TemporaryDirectory`：Windows 上目录清理发生在 fd 仍打开时
    会 `WinError 32`（实测），那是夹具问题，不该混进语义断言。
    """
    lock_file = tmp_path / "w8.lock"
    fd1 = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    fd2 = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    got: dict[str, object] = {}
    try:
        filelock.lock_exclusive(fd1)

        def waiter() -> None:
            started = time.monotonic()
            try:
                filelock.lock_exclusive(fd2)
                got["ok"] = True
            except OSError as exc:
                got["ok"] = False
                got["err"] = f"{type(exc).__name__} errno={getattr(exc, 'errno', '?')}"
            got["elapsed"] = time.monotonic() - started

        th = threading.Thread(target=waiter, daemon=True)
        th.start()
        time.sleep(12)
        assert not got, f"等待方在持有者释放前就返回了（放弃语义）：{got}"
        filelock.unlock(fd1)
        th.join(timeout=20)
        assert not th.is_alive(), "释放锁后等待方仍未拿到锁"
        assert got.get("ok") is True, f"等待方报错而非拿到锁：{got}"
    finally:
        for fd in (fd2, fd1):
            try:
                filelock.unlock(fd)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


def test_w8_blocking_lock_acquires_immediately_when_free(tmp_path: Path) -> None:
    """M-W8 正控：无人持锁时阻塞锁必须**立刻**返回（别把轮询写成无条件睡眠）。"""
    lock_file = tmp_path / "w8b.lock"
    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    try:
        started = time.monotonic()
        filelock.lock_exclusive(fd)
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, f"空锁上阻塞加锁耗时 {elapsed:.2f}s，轮询逻辑有问题"
        filelock.unlock(fd)
    finally:
        os.close(fd)


# ─────────────────────────────────────────────────────────── M-W9 Playwright

@pytest.mark.parametrize("dirname", ["Project Harness", "Project&Harness", "Project%TEMP%"])
def test_w9_playwright_invocation_preserves_paths_and_argv(tmp_path: Path, dirname: str) -> None:
    from scripts import atlas_check

    nm = tmp_path / dirname / "node_modules"
    if IS_WINDOWS:
        if shutil.which("node") is None:
            pytest.skip("Node.js is required for the Windows Playwright launcher")
        cli = nm / "@playwright" / "test" / "cli.js"
        source = "console.log(JSON.stringify([process.argv.slice(2), process.env.NODE_PATH]));"
    else:
        cli = nm / ".bin" / "playwright"
        source = '#!/bin/sh\nprintf "%s\\n" "$@" "$NODE_PATH"\n'
    cli.parent.mkdir(parents=True)
    cli.write_text(source, encoding="utf-8", newline="\n")
    cli.chmod(0o755)

    args = ["test", "-c", "playwright.config.ts", "case&name.spec.ts"]
    command, env = atlas_check._playwright_invocation(cli, nm, args[-1])
    assert isinstance(command, str) != IS_WINDOWS
    code, out = atlas_check.run(command, tmp_path, timeout=10, shell=isinstance(command, str), env=env)
    assert code == 0, out
    if IS_WINDOWS:
        assert json.loads(out) == [args, str(nm)]
    else:
        assert out.splitlines() == [*args, str(nm)]


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows drive/root syntax")
@pytest.mark.parametrize("pattern", [r"\outside\*.md", "D:drive-relative/*.md"])
def test_review_input_include_rejects_partial_windows_anchor(tmp_path: Path, pattern: str) -> None:
    script = PKG_ROOT / "scripts" / "make_review_inputs.py"
    proc = subprocess.run([sys.executable, str(script), "--root", str(tmp_path),
                           "--out", "review", "--include", pattern],
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONUTF8": "1"}, timeout=15)
    assert proc.returncode == 2, proc.stderr
    assert "--include" in proc.stderr and "必须在项目根内" in proc.stderr
    assert not (tmp_path / "review").exists()
