#!/usr/bin/env python3
"""Guarded Continuation —— 计划契约、封闭参数、长生命周期锁、WAL、回执与证书（P1+P2）。

纯标准库；不执行任何父动作链（动作由 Pi 父工具经 ctx.executeTool 真实嵌套发起）。
本模块负责：
- P1+P2 计划 schema 校验（只读枚举 + P2 finish 四切面枚举，禁 force/任意 argv）；
- 规范哈希（与 extensions/pi.ts 的 gcStable 逐字节镜像，哈希不进被哈希对象）；
- 长生命周期写锁 WriteLock（跨平台排他锁：POSIX fcntl.flock / Windows msvcrt.locking，
  经 `_support/filelock.py` 单源；O_CREAT|O_RDWR|O_NOFOLLOW，
  禁 O_TRUNC、释放禁 unlink，支持租约校验，杜绝一次性 CLI O_EXCL 模拟锁）；
- 目录 fsync（fsync_dir）与 O_NOFOLLOW 安全建目录（safe_mkdir_nofollow）；
- 逐动作 intent/WAL（wal.jsonl）与 UNKNOWN 崩溃诊断（禁止自动重放）；
- P2 写集精确对账、归档后路径解析与文件内容守恒核验；
- 两阶段回执与证书构建。

状态机（§4.4 + P2）：
  DRAFT -> APPROVED/ARMED -> FROZEN -> RUNNING -> WRITING -> RECORDED -> AUDITING
            -> SUCCEEDED | AUDIT_FAILED | CLOSED_FAILED；异常分支 ISOLATED / UNKNOWN。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time

# 跨平台文件锁单源（POSIX fcntl.flock ⇄ Windows msvcrt.locking）。
# Windows 无 fcntl：此前本模块在 import 阶段即 ModuleNotFoundError，致 atlas workflow
# 整条需求级执行链起不来。锁原语缺失时本模块 fail-closed，不静默放行。
from _support.filelock import unlock as _unlock_file
from _support.filelock import lock_exclusive_nonblocking as _lock_exclusive_nonblocking
# 跨平台进程探活单源：`os.kill(pid, 0)` 在 Windows 上是**杀进程**而非探活（实测
# `TerminateProcess(handle, 0)`，不抛异常），租约核验会把持锁进程杀掉。
from _support.process_probe import pid_exists
from pathlib import Path
from typing import Any

# ────────────────────────────────────────────────────────────────────────── 常量
SCHEMA_VERSION = 1
READONLY_TOOLS = ("atlas_workflow_progress", "atlas_workflow_status")
WRITE_TOOLS = (
    "atlas_workflow_finish_preflight",
    "atlas_workflow_finish_deferred",
    "atlas_workflow_finish_commit",
    "atlas_workflow_finish_archive",
)
# P2 封闭动作枚举：P1 只读 + P2 finish 四切面；check_fast/gen_*/任意 shell/原始 finish 一律拒绝
ALLOWED_TOOLS = READONLY_TOOLS + WRITE_TOOLS
MAX_ACTIONS = 8
MAX_CANONICAL_ARGS_BYTES = 16 * 1024
GUARD_FACT_KEYS = ("exit_code", "json_ok")
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

CONTINUATIONS_DIRNAME = os.path.join(".atlas", "runs", "continuations")
ISOLATED_DIRNAME = os.path.join(CONTINUATIONS_DIRNAME, "isolated")
LOCKS_DIRNAME = os.path.join(CONTINUATIONS_DIRNAME, "locks")
WRITE_LOCK_REL = os.path.join(LOCKS_DIRNAME, "write.lock")
RUN_ARTIFACTS = ("raw-receipts", "evidence")


class PlanError(Exception):
    """计划契约违例（fail-closed：任何 schema/路径/guard 问题都停在这）。"""


class WriteLockError(RuntimeError):
    """共享长生命周期写锁冲突 / 非法路径 / 租约验证失败。"""


# ────────────────────────────────────────────────────────────────── 目录 fsync / O_NOFOLLOW
def fsync_dir(path: Path) -> None:
    """对目录 fd 执行 os.fsync，确保 rename/unlink/创建对崩溃持久化（POSIX）。"""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def assert_no_symlink_components(base: Path, target: Path) -> None:
    """校验 base 到 target 之间没有任何链接（symlink / Windows junction）或越界。"""
    base_abs = base.absolute()
    if _is_link_like(base_abs):
        raise PlanError(f"项目根不得为 symlink：{base_abs}")
    resolved_base = base_abs.resolve()
    rel = target.absolute().relative_to(base_abs)
    cur = base_abs
    for part in rel.parts:
        cur = cur / part
        if _is_link_like(cur):
            raise PlanError(f"路径含 symlink，拒绝：{cur}")
    if target.exists() and target.resolve() != target.absolute() and not target.resolve().is_relative_to(resolved_base):
        raise PlanError(f"路径逃逸项目根：{target}")


def _is_link_like(path: Path) -> bool:
    """判断路径是否为 symlink **或 Windows 重解析点（junction / mount point）**。

    POSIX 只需 `is_symlink()`；Windows 上目录 junction（`mklink /J`）与挂载点
    **不是** symlink —— `Path.is_symlink()` / `os.path.islink()` / `lstat().st_mode`
    三者一律返回 False（实测），但内核层同样会重定向路径，绕过 symlink 守卫。
    故 Windows 侧额外读 `st_reparse_tag`：非 0 即重解析点，按链接处置（fail-closed）。
    """
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    if os.name == "nt":
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return False
        except OSError:
            return True
        if getattr(st, "st_reparse_tag", 0):
            return True
    return False


def safe_mkdir_nofollow(root: Path, rel_parts: tuple[str, ...]) -> Path:
    """逐级安全建目录并验证非链接。

    POSIX：经 `dir_fd` + `O_DIRECTORY|O_NOFOLLOW` 逐级建与验证（保持原实现，
    该路径下 symlink 在 open 时即被内核拒绝，无 TOCTOU 窗口）。

    Windows：不支持 `dir_fd`，且 `os.open()` 无法打开目录（`O_DIRECTORY` 不存在，
    实测 `PermissionError 13`）。改走 lstat 逐级校验 + 逐级 `mkdir`：每一段在**建之前
    与建之后**都过 `_is_link_like`（含 junction），最后整体复算 `resolve()` 是否仍在
    根内。安全性来自「逐段拒绝链接 + 终态越界复算」而非内核级 dirfd 原子性，故额外
    要求根路径本身为真实目录（下方已校验）。
    """
    root_abs = root.absolute()
    if _is_link_like(root_abs) or not root_abs.is_dir():
        raise PlanError(f"项目根非法或为 symlink：{root_abs}")

    if os.name == "nt":
        return _safe_mkdir_nofollow_windows(root_abs, rel_parts)

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    cur_path = root_abs
    cur_fd = os.open(cur_path, flags)
    try:
        for part in rel_parts:
            if not part or part in (".", "..") or "/" in part or "\\" in part:
                raise PlanError(f"非法目录段：{part!r}")
            try:
                os.mkdir(part, 0o755, dir_fd=cur_fd)
                os.fsync(cur_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, flags, dir_fd=cur_fd)
            st = os.fstat(next_fd)
            if not os.path.stat.S_ISDIR(st.st_mode):
                os.close(next_fd)
                raise PlanError(f"路径非普通目录：{cur_path / part}")
            os.close(cur_fd)
            cur_fd = next_fd
            cur_path = cur_path / part
    finally:
        try:
            os.close(cur_fd)
        except OSError:
            pass
    return cur_path


def _safe_mkdir_nofollow_windows(root_abs: Path, rel_parts: tuple[str, ...]) -> Path:
    """Windows 分支：无 dir_fd / 无法 open 目录，改走 lstat 逐段校验（含 junction）。

    每段在建前、建后各判一次链接；末尾复算 `resolve()` 必须仍落在根内，
    防止中途被替换为 junction 后逃逸。
    """
    cur_path = root_abs
    resolved_root = root_abs.resolve()
    for part in rel_parts:
        if not part or part in (".", "..") or "/" in part or "\\" in part:
            raise PlanError(f"非法目录段：{part!r}")
        next_path = cur_path / part
        # 建前：已存在则必须是真实目录（拒绝 symlink / junction / 普通文件）
        if next_path.exists() or _is_link_like(next_path):
            if _is_link_like(next_path):
                raise PlanError(f"路径含链接（symlink/junction），拒绝：{next_path}")
            if not next_path.is_dir():
                raise PlanError(f"路径非普通目录：{next_path}")
        else:
            try:
                next_path.mkdir()
            except FileExistsError:  # 并发建出，交给下面复查
                pass
        # 建后复查：防「建的过程中被替换」
        if _is_link_like(next_path) or not next_path.is_dir():
            raise PlanError(f"路径非普通目录：{next_path}")
        resolved_next = next_path.resolve()
        if not resolved_next.is_relative_to(resolved_root):
            raise PlanError(f"路径逃逸项目根：{next_path}")
        cur_path = next_path
    return cur_path


# ────────────────────────────────────────────────────────────────── 共享长生命周期写锁
def write_lock_path(root: Path) -> Path:
    return root / WRITE_LOCK_REL


class WriteLock:
    """跨进程共享长生命周期写锁（非阻塞排他锁，POSIX fcntl.flock / Windows msvcrt.locking）。

    纪律：
    - 仅以 O_CREAT|O_RDWR|O_NOFOLLOW 打开（严禁 O_TRUNC，防竞态清掉在途持锁元数据）；
    - 仅在加锁成功后才 ftruncate(0)+写入所有者元数据+fsync+dir_fsync；
    - 释放时解锁+close，严禁 unlink 锁文件（防 POSIX 多 inode 击穿互斥）。
    """

    def __init__(self, root: Path, *, holder: str, unit: str = "", run_id: str = "",
                 token: str | None = None) -> None:
        self.root = Path(root).resolve()
        self.holder = holder
        self.unit = unit
        self.run_id = run_id
        self.token = token or secrets.token_hex(16)
        self.fd: int | None = None
        self.lock_file = write_lock_path(self.root)

    def acquire(self) -> dict[str, Any]:
        safe_mkdir_nofollow(self.root, (".atlas", "runs", "continuations", "locks"))
        assert_no_symlink_components(self.root, self.lock_file)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.lock_file, flags, 0o644)
        try:
            try:
                _lock_exclusive_nonblocking(fd)
            except BlockingIOError as exc:
                owner = self._read_owner_unlocked(fd)
                os.close(fd)
                raise WriteLockError(
                    f"写锁已被占用（holder={owner.get('holder', '?')} "
                    f"pid={owner.get('pid', '?')} unit={owner.get('unit', '?')} "
                    f"run_id={owner.get('run_id', '?')}）"
                ) from exc
            meta = {
                "schema": SCHEMA_VERSION,
                "pid": os.getpid(),
                "holder": self.holder,
                "unit": self.unit,
                "run_id": self.run_id,
                "token_sha256": sha256_hex(self.token.encode("utf-8")),
                "acquired_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            payload = (json.dumps(meta, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, payload)
            os.fsync(fd)
            fsync_dir(self.lock_file.parent)
            self.fd = fd
            return meta
        except Exception:
            if self.fd is None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise

    @staticmethod
    def _read_owner_unlocked(fd: int) -> dict[str, Any]:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 4096).decode("utf-8", errors="replace").strip()
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def release(self) -> None:
        if self.fd is not None:
            fd = self.fd
            self.fd = None
            try:
                _unlock_file(fd)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass

    def __enter__(self) -> "WriteLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()


def verify_write_lock_lease(root: Path, run_id: str, unit: str, token: str) -> dict[str, Any]:
    """受控 P2 写子工具租约核验：确认锁确实被活着的 lock-hold 持有且 token/run_id/unit 匹配。"""
    if not token:
        raise WriteLockError("缺少写锁租约 token（stdin 未传入）")
    root = Path(root).resolve()
    lp = write_lock_path(root)
    assert_no_symlink_components(root, lp)
    if not lp.is_file():
        raise WriteLockError("写锁文件不存在（未启动长生命周期持锁）")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lp, flags)
    try:
        try:
            # 非阻塞探测：如果还能拿到排他锁，说明没有活跃持锁者！立即释放并拒绝。
            _lock_exclusive_nonblocking(fd)
            _unlock_file(fd)
            raise WriteLockError("写锁当前无人持有（lock-hold 已退出或失效）")
        except BlockingIOError:
            pass
        raw = lp.read_text(encoding="utf-8")
        meta = json.loads(raw)
    finally:
        os.close(fd)
    holder_pid = meta.get("pid")
    if not isinstance(holder_pid, int) or holder_pid <= 0:
        raise WriteLockError("写锁 holder_pid 非法")
    # 探活走 `_support/process_probe.py` 单源：POSIX 仍是 `os.kill(pid, 0)`（逐字节
    # 不变），Windows 改只读 `OpenProcess`+`GetExitCodeProcess`。**不能**直接
    # `os.kill(pid, 0)`：Windows 上那是 `TerminateProcess`，核验一次就把持锁进程杀了
    # （实测进程以 3221225794 退出且不抛异常），随后必然误报「不存活」。
    if not pid_exists(holder_pid):
        raise WriteLockError(f"写锁持有进程 {holder_pid} 不存活")
    if meta.get("run_id") != run_id or meta.get("unit") != unit:
        raise WriteLockError("写锁绑定 run_id/unit 不匹配")
    expected_sha = sha256_hex(token.encode("utf-8"))
    if meta.get("token_sha256") != expected_sha:
        raise WriteLockError("写锁租约 token 校验失败")
    return meta


# ────────────────────────────────────────────────────────────────── 规范哈希
def _drop_none(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _drop_none(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_drop_none(x) for x in v]
    return v


def canonical_json(value: Any) -> str:
    """稳定序列化：键排序、丢 None、紧凑分隔符、不转义非 ASCII。

    与 pi.ts 侧 `gcStable()`（P0 已实测双侧一致）逐字节镜像；浮点不进哈希面。
    """
    return json.dumps(_drop_none(value), sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))


def canonical_result_hash(result: dict) -> str:
    """工具结果规范哈希：{content, details, structuredContent, isError}。"""
    payload = {
        "content": result.get("content"),
        "details": result.get("details"),
        "structuredContent": result.get("structuredContent"),
        "isError": result.get("isError"),
    }
    return sha256_hex(canonical_json(payload).encode("utf-8"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_hex(path.read_bytes())


# ────────────────────────────────────────────────────────────────── 计划契约
def is_write_plan(plan: dict) -> bool:
    """计划是否包含任一 P2 写链工具（只读 preflight 亦归 P2 写链装配面，但仅写动作启用写保护）。"""
    return any(a.get("tool") in WRITE_TOOLS for a in (plan.get("actions") or []))


def has_mutating_write_actions(plan: dict) -> bool:
    """计划是否包含会实际写盘的 P2 动作（deferred / commit / archive）。"""
    mutating = {
        "atlas_workflow_finish_deferred",
        "atlas_workflow_finish_commit",
        "atlas_workflow_finish_archive",
    }
    return any(a.get("tool") in mutating for a in (plan.get("actions") or []))


def resolve_task_dir(root: Path, unit: str, archived_task_dir: str | None = None) -> tuple[Path, bool]:
    """解析任务卡目录（活跃区或 wal 记录的归档路径）；返回 (path, is_archived)。"""
    if not unit or not UNIT_RE.fullmatch(unit):
        raise PlanError(f"非法 unit：{unit!r}")
    root_abs = root.resolve()
    tasks_root = root_abs / ".atlas" / "tasks"
    active = tasks_root / unit
    if archived_task_dir:
        cand = Path(archived_task_dir)
        if not cand.is_absolute():
            cand = root_abs / cand
        cand_resolved = cand.resolve()
        archive_root = (tasks_root / "archive").resolve()
        if archive_root not in cand_resolved.parents or cand_resolved.name != unit:
            raise PlanError(f"非法归档任务目录：{archived_task_dir}")
        assert_no_symlink_components(root_abs, cand)
        return cand_resolved, True
    if active.is_dir():
        assert_no_symlink_components(root_abs, active)
        return active, False
    # 兜底仅按 archive/<YYYY-MM>/<unit> 精确查找（不按 date.today() 猜月）
    archive_root = tasks_root / "archive"
    if archive_root.is_dir():
        matches = sorted(
            p for p in archive_root.glob(f"*/{unit}")
            if p.is_dir() and not p.is_symlink()
        )
        if len(matches) == 1:
            assert_no_symlink_components(root_abs, matches[0])
            return matches[0].resolve(), True
        if len(matches) > 1:
            raise PlanError(f"发现多个归档目录 {matches}")
    return active, False


def plan_path(root: Path, unit: str, archived_task_dir: str | None = None) -> Path:
    t_dir, _ = resolve_task_dir(root, unit, archived_task_dir=archived_task_dir)
    return t_dir / "continuation.json"


def load_plan(root: Path, unit: str, archived_task_dir: str | None = None) -> dict:
    """读计划并做全量 schema 校验（fail-closed）；返回附带 plan_sha256 的 dict。"""
    path = plan_path(root, unit, archived_task_dir=archived_task_dir)
    if path.is_symlink() or not path.is_file():
        raise PlanError(f"计划不存在或为 symlink：{path}")
    raw = path.read_bytes()
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PlanError(f"计划不可解析：{e}") from e
    _validate_plan(plan, unit)
    plan["plan_sha256"] = sha256_hex(raw)
    plan["_plan_path"] = str(path)
    return plan


def _reject(plan: dict, msg: str) -> None:
    raise PlanError(msg)


def _validate_plan(plan: dict, unit: str) -> None:
    if not isinstance(plan, dict):
        _reject(plan, "计划必须是对象")
    if plan.get("schema") != SCHEMA_VERSION:
        _reject(plan, f"schema 必须为 {SCHEMA_VERSION}")
    if plan.get("unit") != unit:
        _reject(plan, f"unit 与目录不一致：{plan.get('unit')!r} != {unit!r}")
    if plan.get("author") != "human":
        # author 只是说明字段，不是授权（授权唯一来自人类 approve 命令票据）
        _reject(plan, "author 必须为 \"human\"（说明字段，非授权）")
    if "force" in plan:
        _reject(plan, "计划顶层禁止 force 字段")
    actions = plan.get("actions")
    if not isinstance(actions, list) or not (1 <= len(actions) <= MAX_ACTIONS):
        _reject(plan, f"actions 必须为 1..{MAX_ACTIONS} 个")
    seen_ids: set[str] = set()
    defined_ids: set[str] = set()
    total_args_bytes = 0
    seen_write_order: list[str] = []
    write_rank = {name: idx for idx, name in enumerate(WRITE_TOOLS)}
    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            _reject(plan, f"actions[{idx}] 必须为对象")
        aid = action.get("id")
        if not isinstance(aid, str) or not aid or aid in seen_ids:
            _reject(plan, f"actions[{idx}].id 非空且唯一，got {aid!r}")
        seen_ids.add(aid)
        tool = action.get("tool")
        if tool not in ALLOWED_TOOLS:
            _reject(plan, f"actions[{idx}].tool {tool!r} 不在封闭枚举 {ALLOWED_TOOLS}")
        if tool in write_rank:
            # P2 写动作严格保序且不能出现两次（不可先归档再提交/不可无预检直接提交）
            if tool in seen_write_order:
                _reject(plan, f"P2 写链动作 {tool!r} 不允许重复出现")
            if seen_write_order and write_rank[tool] <= write_rank[seen_write_order[-1]]:
                _reject(plan, f"P2 写链动作顺序非法：{seen_write_order[-1]} 后不能接 {tool}")
            if tool != "atlas_workflow_finish_preflight" and "atlas_workflow_finish_preflight" not in seen_write_order:
                _reject(plan, f"P2 写动作 {tool!r} 之前必须先有 atlas_workflow_finish_preflight")
            seen_write_order.append(tool)
        args = action.get("args")
        if not isinstance(args, dict) or set(args) != {"unit"} or args["unit"] != unit:
            _reject(plan, f"actions[{idx}].args 只允许 {{unit: <与本任务一致的 unit>}}（禁止 force/cmd）")
        encoded = json.dumps(args, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        total_args_bytes += len(encoded)
        if total_args_bytes > MAX_CANONICAL_ARGS_BYTES:
            _reject(plan, f"规范参数总量超过 {MAX_CANONICAL_ARGS_BYTES} 字节")
        _validate_guard(action.get("guard"), idx, defined_ids, plan)
        defined_ids.add(aid)


def _validate_guard(guard: Any, idx: int, defined_ids: set[str], plan: dict) -> None:
    if not isinstance(guard, dict):
        _reject(plan, f"actions[{idx}].guard 必须为对象")
    kind = guard.get("kind")
    if kind == "always":
        return
    if kind == "all_of":
        refs = guard.get("refs")
        if not isinstance(refs, list) or not refs:
            _reject(plan, f"actions[{idx}] all_of.refs 必须非空数组")
        for ref in refs:
            if not isinstance(ref, str) or "." not in ref:
                _reject(plan, f"actions[{idx}] guard 引用形如 <action_id>.<fact>，got {ref!r}")
            aid, fact = ref.split(".", 1)
            if aid not in defined_ids:
                _reject(plan, f"actions[{idx}] guard 引用 {ref!r}：未知/前向/重复 ID 皆拒绝")
            if fact not in GUARD_FACT_KEYS:
                _reject(plan, f"actions[{idx}] guard 事实键仅 {GUARD_FACT_KEYS}，got {fact!r}")
        return
    _reject(plan, f"actions[{idx}] guard.kind 仅 always/all_of，got {kind!r}")


def canonical_args_hash(args: dict) -> str:
    return sha256_hex(canonical_json(args).encode("utf-8"))


# ────────────────────────────────────────────────────────────────── guard 求值
def observed_facts(observation: dict) -> dict:
    """从单动作观察回执提取 guard 事实：exit_code（==0 谓词）、json_ok。"""
    return {
        "exit_code": observation.get("exit_code") == 0,
        "json_ok": bool(observation.get("json_ok")),
    }


def evaluate_guard(guard: dict, observations: dict[str, dict]) -> tuple[bool, list[str]]:
    """求值当前动作 guard；只消费已观察回执（不消费模型预测）。"""
    if guard.get("kind") == "always":
        return True, []
    values: list[str] = []
    for ref in guard.get("refs", []):
        aid, fact = ref.split(".", 1)
        obs = observations.get(aid)
        if obs is None:
            return False, values
        facts = observed_facts(obs)
        values.append(f"{ref}={facts[fact]}")
        if not facts[fact]:
            return False, values
    return True, values


def replay_guards(plan: dict, observations: dict[str, dict],
                  host_call_names: list[str]) -> dict:
    """审计重放：逐动作重算 guard，断言「guard=false 后零宿主调用、失败后零后续调用」。"""
    executed: dict[str, dict] = {}
    expected_calls: list[str] = []
    stopped = False
    for action in plan["actions"]:
        aid = action["id"]
        ok, _ = evaluate_guard(action["guard"], executed)
        if stopped or not ok:
            stopped = True
            continue
        expected_calls.append(action["tool"])
        obs = observations.get(aid)
        if obs is None or not obs.get("ok"):
            stopped = True
            continue
        executed[aid] = obs
    detail = {
        "expected_calls": expected_calls,
        "actual_calls": host_call_names,
        "prefix_match": host_call_names == expected_calls[:len(host_call_names)]
        if len(host_call_names) <= len(expected_calls) else False,
        "zero_suffix": len(host_call_names) == len(expected_calls),
    }
    ok = detail["prefix_match"] and detail["zero_suffix"]
    return {"ok": ok, "detail": detail}


# ────────────────────────────────────────────────────────────────── 运行目录 IO
def run_dir(root: Path, run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    if not safe or safe != run_id or len(run_id) > 80:
        raise PlanError(f"非法 run_id：{run_id!r}")
    root_abs = root.resolve()
    base = safe_mkdir_nofollow(root_abs, (".atlas", "runs", "continuations", run_id))
    for sub in ("raw-receipts", "evidence"):
        safe_mkdir_nofollow(base, (sub,))
    return base


def isolated_marker_path(root: Path, unit: str) -> Path:
    if not unit or not UNIT_RE.fullmatch(unit):
        raise PlanError(f"非法 unit：{unit!r}")
    return root / ISOLATED_DIRNAME / f"{unit}.json"


def write_exclusive(path: Path, text: str) -> None:
    """O_EXCL 不可变写 + fsync + dir_fsync（已存在即失败）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise PlanError(f"父目录不得为 symlink：{path.parent}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o644)
    # newline="" 禁用换行转换：Windows 上文本模式会把 "\n" 写成 "\r\n"，导致落盘字节
    # 与调用方随后计算的 sha256（基于未转换的理想字节）不一致——写读回对账恒判篡改
    # （实测 raw_receipt_tampered 假阳性）。本函数承诺「落盘字节 == 传入 text」，故必须
    # 显式关闭转换。
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    fsync_dir(path.parent)


def write_json_exclusive(path: Path, payload: dict) -> str:
    """O_EXCL 写 JSON（追加换行）；返回落盘字节 sha256。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_exclusive(path, text)
    return sha256_hex(text.encode("utf-8"))


def atomic_write_json_durable(path: Path, payload: dict) -> str:
    """临时文件 fsync + os.replace + dir_fsync；返回落盘字节 sha256。"""
    if path.parent.is_symlink():
        raise PlanError(f"父目录不得为 symlink：{path.parent}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return sha256_hex(text.encode("utf-8"))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def raw_receipt_path(run: Path, action_index: int, child_hash: str) -> Path:
    return run / "raw-receipts" / f"{action_index}-{child_hash}.json"


def write_raw_receipt(run: Path, action_index: int, result: dict, meta: dict) -> tuple[str, str]:
    """权威原始回执（O_EXCL + fsync + dir_fsync）。"""
    h = canonical_result_hash(result)
    payload = {"canonical_hash": h, "result": result, **meta}
    file_sha = write_json_exclusive(raw_receipt_path(run, action_index, h[:16]), payload)
    return h, file_sha


def manifest_hash(run: Path, subdir: str) -> str:
    """目录内逐文件摘要清单的规范哈希（raw-receipts / git-calls / wal / evidence 通用）。"""
    entries = []
    base = run / subdir
    if base.is_dir():
        for p in sorted(base.rglob("*")):
            if p.is_file():
                entries.append({"path": str(p.relative_to(run)), "sha256": file_sha256(p)})
    elif subdir in ("git-calls.jsonl", "wal.jsonl"):
        p = run / subdir
        if p.is_file():
            entries.append({"path": subdir, "sha256": file_sha256(p)})
    return sha256_hex(canonical_json(entries).encode("utf-8"))


# ────────────────────────────────────────────────────────────────── WAL / INTENT / UNKNOWN
def wal_path(run: Path) -> Path:
    return run / "wal.jsonl"


def append_wal(run: Path, entry: dict) -> dict:
    """向 wal.jsonl 追加一行并 fsync + dir_fsync。"""
    p = wal_path(run)
    if p.is_symlink() or p.parent.is_symlink():
        raise PlanError(f"WAL 路径含 symlink：{p}")
    existing, truncated = read_wal(run)
    if truncated:
        raise PlanError("WAL 存在未闭合尾部半行，禁止继续追加写（须人工诊断）")
    seq = len(existing) + 1
    record = {
        "seq": seq,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **entry,
    }
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(p, flags, 0o644)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    fsync_dir(p.parent)
    return record


def read_wal(run: Path) -> tuple[list[dict], bool]:
    """容错读取 wal.jsonl；尾部半行/坏 JSON 记 has_truncated_tail=True（不抛异常）。"""
    p = wal_path(run)
    if not p.is_file():
        return [], False
    entries: list[dict] = []
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    has_truncated_tail = False
    for idx, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
            if not isinstance(obj, dict):
                raise ValueError("not dict")
            entries.append(obj)
        except ValueError:
            if idx == len(lines) - 1:
                has_truncated_tail = True
            else:
                has_truncated_tail = True
                break
    return entries, has_truncated_tail


def wal_state_summary(entries: list[dict], has_truncated_tail: bool) -> dict[str, Any]:
    """从 WAL 条目汇总已 COMMITTED 动作、悬空 INTENT、UNKNOWN 与归档路径。"""
    committed: list[dict] = []
    intents: dict[int, dict] = {}
    committed_idx: set[int] = set()
    unknown_entries: list[dict] = []
    archived_task_dir: str | None = None
    pre_archive_files: dict[str, str] | None = None
    expected_task_sha256: str | None = None
    expected_plan_sha256: str | None = None
    head_before: str | None = None
    deferred_meta: dict[str, Any] = {}

    for e in entries:
        phase = e.get("phase")
        aidx = e.get("action_index")
        if phase == "INTENT" and isinstance(aidx, int):
            intents[aidx] = e
            if e.get("head_before") and head_before is None:
                head_before = e.get("head_before")
            if e.get("tool") == "atlas_workflow_finish_archive":
                if isinstance(e.get("pre_archive_files"), dict):
                    pre_archive_files = e["pre_archive_files"]
                if e.get("expected_archive_dir"):
                    archived_task_dir = e["expected_archive_dir"]
                if e.get("expected_task_sha256"):
                    expected_task_sha256 = e["expected_task_sha256"]
                if e.get("expected_plan_sha256"):
                    expected_plan_sha256 = e["expected_plan_sha256"]
        elif phase == "COMMITTED" and isinstance(aidx, int):
            committed_idx.add(aidx)
            committed.append(e)
            if e.get("tool") == "atlas_workflow_finish_deferred":
                deferred_meta = dict(e.get("meta") or {})
            if e.get("tool") == "atlas_workflow_finish_commit" and e.get("actual_task_sha256"):
                expected_task_sha256 = e["actual_task_sha256"]
            if e.get("tool") == "atlas_workflow_finish_archive":
                if e.get("archived_task_dir"):
                    archived_task_dir = e["archived_task_dir"]
        elif phase == "UNKNOWN":
            unknown_entries.append(e)

    dangling_intents = [intents[i] for i in sorted(intents) if i not in committed_idx]
    is_unknown = bool(unknown_entries or dangling_intents or has_truncated_tail)
    committed_tools = [str(c.get("tool") or "") for c in committed]
    return {
        "committed": committed,
        "committed_tools": committed_tools,
        "dangling_intents": dangling_intents,
        "unknown_entries": unknown_entries,
        "has_truncated_tail": has_truncated_tail,
        "is_unknown": is_unknown,
        "archived_task_dir": archived_task_dir if "atlas_workflow_finish_archive" in committed_tools else None,
        "candidate_archive_dir": archived_task_dir,
        "pre_archive_files": pre_archive_files,
        "expected_task_sha256": expected_task_sha256,
        "expected_plan_sha256": expected_plan_sha256,
        "head_before": head_before,
        "deferred_meta": deferred_meta,
    }


def diagnose_unknown(root: Path, run: Path, unit: str) -> dict[str, Any]:
    """崩溃恢复只读诊断：比对 WAL 与磁盘/git 现态，严禁重放任何写动作。"""
    import subprocess
    root_abs = Path(root).resolve()
    entries, truncated = read_wal(run)
    summary = wal_state_summary(entries, truncated)
    active_dir = root_abs / ".atlas" / "tasks" / unit
    cand_arch = summary.get("candidate_archive_dir")
    arch_exists = bool(cand_arch and (root_abs / cand_arch).is_dir())
    head_now = ""
    try:
        pr = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root_abs),
                            capture_output=True, text=True, timeout=15)
        if pr.returncode == 0:
            head_now = pr.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head_now = ""
    return {
        "unit": unit,
        "run_id": run.name,
        "wal_entries": len(entries),
        "has_truncated_tail": truncated,
        "committed_tools": summary["committed_tools"],
        "dangling_intents": [
            {"action_index": d.get("action_index"), "action_id": d.get("action_id"),
             "tool": d.get("tool"), "target_paths": d.get("target_paths")}
            for d in summary["dangling_intents"]
        ],
        "unknown_entries": summary["unknown_entries"],
        "active_task_exists": active_dir.is_dir(),
        "archive_dir": cand_arch,
        "archive_exists": arch_exists,
        "head_before": summary.get("head_before"),
        "head_now": head_now,
        "auto_replay_allowed": False,
    }


def authorized_write_set(root: Path, unit: str, committed_tools: list[str], *,
                         deferred_meta: dict[str, Any] | None = None,
                         archived_task_dir: str | None = None,
                         pre_archive_files: dict[str, str] | None = None) -> set[str]:
    """根据已 COMMITTED 的 P2 动作集合推导允许变更的项目根相对路径精确集合。"""
    allowed: set[str] = set()
    active_rel = f".atlas/tasks/{unit}"
    meta = deferred_meta or {}
    if "atlas_workflow_finish_deferred" in committed_tools:
        if meta.get("deferred_written", True):
            allowed.add(f"{active_rel}/deferred.md")
        if meta.get("receipt_written"):
            allowed.add(".atlas/runs/workflow-receipt.json")
            allowed.add(".atlas/runs/workflow-review-origin.json")
            for p in meta.get("receipt_files") or []:
                allowed.add(str(p))
            allowed.add(".atlas/runs/workflow-receipt/*")
        if meta.get("topology_written"):
            for p in meta.get("topology_files") or []:
                allowed.add(str(p))
            allowed.add(".adapter-out/topology*")
            allowed.add(".atlas/spec/structure/global/runtime-topology.md")
    if "atlas_workflow_finish_commit" in committed_tools:
        allowed.add(f"{active_rel}/task.json")
    if "atlas_workflow_finish_archive" in committed_tools and archived_task_dir:
        # 归档迁出：活跃区原全部文件（包含随卡文件）+ 归档目标区对应文件
        if pre_archive_files:
            for rel_name in pre_archive_files:
                allowed.add(f"{active_rel}/{rel_name}")
                allowed.add(f"{archived_task_dir}/{rel_name}")
        allowed.add(f"{active_rel}/*")
        allowed.add(f"{archived_task_dir}/*")
        # 归档前可能刚写入的 deferred.md / task.json
        allowed.add(f"{active_rel}/deferred.md")
        allowed.add(f"{active_rel}/task.json")
        allowed.add(f"{archived_task_dir}/deferred.md")
        allowed.add(f"{archived_task_dir}/task.json")
    return allowed


def path_in_authorized_set(rel: str, allowed: set[str]) -> bool:
    rel = rel.replace("\\", "/")
    if rel in allowed:
        return True
    for pat in allowed:
        if pat.endswith("/*") and rel.startswith(pat[:-1]):
            return True
        if pat.endswith("*") and not pat.endswith("/*") and rel.startswith(pat[:-1]):
            return True
    return False


def verify_archive_conservation(root: Path, unit: str, archived_task_dir: str,
                                pre_archive_files: dict[str, str],
                                expected_task_sha256: str | None,
                                expected_plan_sha256: str | None) -> tuple[bool, str]:
    """核验归档迁出与逐文件 SHA256 守恒：源目录消失、目标存在、非改动文件逐字节一致。"""
    root_abs = root.resolve()
    active_dir = root_abs / ".atlas" / "tasks" / unit
    if active_dir.exists() or active_dir.is_symlink():
        return False, f"归档后原活跃任务目录仍存在：{active_dir}"
    dest_dir = root_abs / archived_task_dir
    if not dest_dir.is_dir() or dest_dir.is_symlink():
        return False, f"归档目标目录不存在或为 symlink：{archived_task_dir}"
    for rel_name, old_sha in pre_archive_files.items():
        dest_file = dest_dir / rel_name
        if not dest_file.is_file() or dest_file.is_symlink():
            return False, f"归档后缺失文件：{archived_task_dir}/{rel_name}"
        if file_sha256(dest_file) != old_sha:
            return False, f"归档后文件内容漂移：{archived_task_dir}/{rel_name}"
    task_file = dest_dir / "task.json"
    if not task_file.is_file():
        return False, "归档后缺失 task.json"
    if expected_task_sha256 and file_sha256(task_file) != expected_task_sha256:
        return False, "归档后 task.json 指纹与提交期不一致"
    try:
        task_obj = read_json(task_file)
    except Exception as exc:
        return False, f"归档后 task.json 不可解析：{exc}"
    if task_obj.get("status") != "completed":
        return False, f"归档后 task.status 须为 completed，got {task_obj.get('status')!r}"
    plan_file = dest_dir / "continuation.json"
    if expected_plan_sha256:
        if not plan_file.is_file() or file_sha256(plan_file) != expected_plan_sha256:
            return False, "归档后 continuation.json 缺失或哈希漂移"
    return True, ""


# ────────────────────────────────────────────────────────────────── 证书 v1（P1+P2）
def certificate_payload(*, run_id: str, unit: str, plan_sha256: str,
                        atlas_version: str, session_id: str,
                        parent_tool_call_id: str, parent_tool_name: str,
                        expected_parent_result_sha256: str,
                        actual_parent_result_sha256: str,
                        host_nested_calls: dict, session_seal: dict,
                        execution_receipt_sha256: str,
                        input_manifest_sha256: str,
                        raw_receipts_manifest_sha256: str,
                        git_calls_manifest_sha256: str,
                        substitutions: list[dict], status: str,
                        wal_manifest_sha256: str | None = None,
                        archived_task_dir: str | None = None,
                        plan_path_after_archive: str | None = None,
                        certificate_path: str | None = None) -> dict:
    """证书字段面（§6.2 + P2 归档/WAL 扩展，None 值经 canonical_json 自动忽略以兼容 P1）。"""
    payload = {
        "schema": SCHEMA_VERSION,
        "run_id": run_id,
        "unit": unit,
        "plan_sha256": plan_sha256,
        "atlas_version": atlas_version,
        "session_id": session_id,
        "parent_tool_call_id": parent_tool_call_id,
        "parent_tool_name": parent_tool_name,
        "expected_parent_result_sha256": expected_parent_result_sha256,
        "actual_parent_result_sha256": actual_parent_result_sha256,
        "host_nested_calls_sha256": sha256_hex(canonical_json(host_nested_calls).encode("utf-8")),
        "host_nested_calls_complete": host_nested_calls.get("complete") is True,
        "session_seal_entry_id": session_seal.get("entry_id"),
        "session_seal_sha256": sha256_hex(canonical_json(session_seal.get("data")).encode("utf-8")),
        "execution_receipt_sha256": execution_receipt_sha256,
        "input_manifest_sha256": input_manifest_sha256,
        "raw_receipts_manifest_sha256": raw_receipts_manifest_sha256,
        "git_calls_manifest_sha256": git_calls_manifest_sha256,
        "substitutions": substitutions,
        "status": status,
    }
    if wal_manifest_sha256 is not None:
        payload["wal_manifest_sha256"] = wal_manifest_sha256
    if archived_task_dir is not None:
        payload["archived_task_dir"] = archived_task_dir
    if plan_path_after_archive is not None:
        payload["plan_path_after_archive"] = plan_path_after_archive
    if certificate_path is not None:
        payload["certificate_path"] = certificate_path
    return payload


def audit_failure_payload(run: Path, reason: str, detail: dict) -> dict:
    return {"schema": SCHEMA_VERSION, "run_id": run.name,
            "status": "AUDIT_FAILED", "reason": reason, "detail": detail}
