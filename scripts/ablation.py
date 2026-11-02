#!/usr/bin/env python3
"""消融事务工具（P3 首切片；RFC-20261101-04）。

把「物理摘除只在隔离副本」的手工流程收成可恢复的事务：

  begin   解析补丁 -> 项目外快照 -> apply -> active/marker
  restore 全路径 preflight -> 三方比对 -> 写回 before -> smoke -> 复算
  status  查看当前事务（只读）

真相源在项目外 `<state-root>/roots/<root_hash>/active.json`；项目内
`.atlas/ABLATION` 只是提示。状态根默认 `~/.atlas-ablation/`，可用
`--state-root` 或 `ATLAS_ABLATION_HOME` 覆盖。

安全口径（与 research/2026-10-23-ablation-differential.md §5 对齐）：
- 不自动还原；冲突拒绝写入；不把备份放进项目；
- 不提供生产级 `ATLAS_ABLATE` 开关；MVP 只支持现有普通文件的修改/删除；
- gate 的读取逻辑单源在本文件 `inspect_root()`，atlas_check 只调用。
"""
from __future__ import annotations

import argparse
import difflib
import fcntl
import getpass
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
STATE_ENV = "ATLAS_ABLATION_HOME"
DEFAULT_STATE_ROOT = "~/.atlas-ablation"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_HASH_BYTES = 10 * 1024 * 1024


class AblationError(Exception):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise AblationError(f"时间不可解析：{value!r}（{exc}）") from exc


def _state_root(arg: str | None) -> Path:
    raw = arg or os.environ.get(STATE_ENV) or DEFAULT_STATE_ROOT
    return Path(raw).expanduser().resolve()


def _ensure_state_root(state: Path) -> None:
    if state.exists():
        if not state.is_dir():
            raise AblationError(f"state-root 不是目录：{state}")
        return
    state.mkdir(parents=True, exist_ok=True)
    os.chmod(state, 0o700)


def _root_hash(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def _root_id(root: Path) -> str:
    st = root.stat()
    return f"{st.st_dev}:{st.st_ino}"


def _root_dir(state: Path, root: Path) -> Path:
    return state / "roots" / _root_hash(root)


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AblationError(f"读 {path} 失败：{exc}") from exc
    if not isinstance(data, dict):
        raise AblationError(f"{path} 顶层不是 object")
    return data


def _active_path(root_dir: Path) -> Path:
    return root_dir / "active.json"


def _read_active(root_dir: Path) -> dict | None:
    path = _active_path(root_dir)
    if not path.exists():
        return None
    data = _load_json(path)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise AblationError(f"active schema_version 不支持：{data.get('schema_version')!r}")
    return data


def _write_active(root_dir: Path, data: dict) -> None:
    _atomic_json(_active_path(root_dir), data)


def _remove_active(root_dir: Path) -> None:
    try:
        _active_path(root_dir).unlink()
    except FileNotFoundError:
        pass


def _marker_path(root: Path) -> Path:
    return root / ".atlas" / "ABLATION"


def _write_marker(root: Path, active: dict) -> None:
    _atomic_json(_marker_path(root), {
        "schema_version": SCHEMA_VERSION,
        "id": active["id"],
        "scope": active.get("scope", ""),
        "started": active.get("started", ""),
        "timebox_min": active.get("timebox_min", 60),
    })


def _remove_marker(root: Path) -> None:
    try:
        _marker_path(root).unlink()
    except FileNotFoundError:
        pass


def _lock(root_dir: Path):
    root_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(root_dir, 0o700)
    f = (root_dir / ".lock").open("a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise AblationError("另一个 ablation 进程持有锁")
    return f


def _unlock(f) -> None:
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()


def _git(root: Path, *args: str, text: bool = True):
    cmd = ["git", "-C", str(root), *args]
    return subprocess.run(cmd, capture_output=True, text=text)


def _git_text(root: Path, *args: str) -> str:
    p = _git(root, *args)
    if p.returncode != 0:
        raise AblationError(f"git {' '.join(args)} 失败：{p.stderr.strip()[-300:]}")
    return p.stdout


def _git_toplevel(root: Path) -> None:
    top = Path(_git_text(root, "rev-parse", "--show-toplevel").strip()).resolve()
    if top != root.resolve():
        raise AblationError(f"root 必须是 git 顶层（实际 {top}）")


def _status_records(root: Path) -> list[tuple[str, str]]:
    p = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "-z"],
                       capture_output=True)
    if p.returncode != 0:
        raise AblationError("git status 失败（git 不可用或不是仓库）")
    out = p.stdout.decode("utf-8", "surrogateescape")
    records = [r for r in out.split("\0") if r]
    parsed: list[tuple[str, str]] = []
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if not rec:
            continue
        parsed.append((rec[:2], rec[3:]))
        if rec[0] in "RC":
            i += 1                      # 旧路径 + 新路径；MVP 不改 rename
    return parsed


def _is_tracked(root: Path, rel: str) -> bool:
    p = _git(root, "ls-files", "--error-unmatch", "--", rel)
    return p.returncode == 0


def _patch_paths(root: Path, patch: Path) -> list[str]:
    p = subprocess.run(["git", "-C", str(root), "apply", "--numstat", "-z", str(patch)],
                       capture_output=True)
    if p.returncode != 0:
        raise AblationError(
            f"git apply --numstat 失败：{p.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    paths: list[str] = []
    for rec in p.stdout.split(b"\0"):
        if not rec:
            continue
        fields = rec.split(b"\t")
        if len(fields) != 3:
            raise AblationError("补丁 --numstat 形态不支持（非三元组）")
        added, deleted, raw = fields
        if added == b"-" or deleted == b"-":
            raise AblationError("MVP 不支持 binary 补丁")
        paths.append(raw.decode("utf-8", "surrogateescape"))
    return paths


def _patch_summary(root: Path, patch: Path) -> None:
    out = _git_text(root, "apply", "--summary", str(patch))
    for line in out.splitlines():
        s = line.strip()
        if s.startswith(("create mode", "mode change", "rename", "copy", "symlink")):
            raise AblationError(f"MVP 不支持该补丁形态：{s}")


def _has_symlink_parent(root: Path, rel: Path) -> bool:
    parts = rel.parts
    for i in range(1, len(parts)):
        if os.path.islink(root / Path(*parts[:i])):
            return True
    return False


def _normalize_rel(root: Path, raw: str) -> str:
    if not raw or "\0" in raw:
        raise AblationError("空路径 / NUL 路径")
    p = Path(raw)
    if p.is_absolute() or ".." in p.parts:
        raise AblationError(f"路径越界：{raw}")
    target = (root / p).resolve(strict=False)
    try:
        rel = target.relative_to(root.resolve())
    except ValueError as exc:
        raise AblationError(f"路径越界：{raw}") from exc
    if not rel.parts or rel.parts[0] == ".git":
        raise AblationError(f"路径不允许：{raw}")
    if rel.as_posix() == ".atlas/ABLATION":
        raise AblationError("不允许消融项目内 ABLATION 标记")
    if _has_symlink_parent(root, rel):
        raise AblationError(f"路径含 symlink 父目录：{raw}")
    return rel.as_posix()


def _ensure_state_outside(root: Path, state: Path) -> None:
    try:
        state.resolve().relative_to(root.resolve())
    except ValueError:
        return
    raise AblationError("state-root 不得在项目内")


def _host_mode(root: Path) -> str:
    if ((root / "scripts" / "atlas_check.py").is_file()
            and (root / "validators").is_dir()):
        return "source"
    if (root / ".atlas" / "VERSION").is_file():
        return "adopter"
    return "unknown"


def _host_warning(root: Path, mode: str, rels: list[str]) -> str | None:
    if mode == "source" and any(r.startswith(".atlas/") for r in rels):
        return "source 模式消融落在 .atlas/（可能测的是装配副本）"
    if mode == "adopter" and any(not r.startswith(".atlas/") for r in rels):
        return "adopter 模式消融落在 .atlas/ 之外（可能测的是源包面）"
    return None


def _entry_at(root: Path, rel: str) -> dict:
    p = root / rel
    try:
        st = p.lstat()
    except FileNotFoundError:
        return {"type": "absent"}
    if stat.S_ISLNK(st.st_mode):
        return {"type": "symlink", "link_target": os.readlink(p)}
    if not stat.S_ISREG(st.st_mode):
        return {"type": "other"}
    return {"type": "file", "sha256": _sha(p), "size": st.st_size,
            "mode": oct(st.st_mode & 0o777)}


def _manifest(root: Path, rels: list[str]) -> dict:
    entries = {}
    for rel in rels:
        entry = _entry_at(root, rel)
        if entry["type"] == "symlink":
            raise AblationError(f"MVP 不支持 symlink：{rel}")
        if entry["type"] == "other":
            raise AblationError(f"MVP 只支持普通文件：{rel}")
        entries[rel] = entry
    return {"schema_version": SCHEMA_VERSION, "entries": entries}


def _entry_equal(left: dict, right: dict) -> bool:
    if left.get("type") != right.get("type"):
        return False
    if left.get("type") != "file":
        return True
    return all(left.get(k) == right.get(k) for k in ("sha256", "size", "mode"))


def _any_changed(before: dict, after: dict) -> bool:
    entries_b = before.get("entries", {})
    entries_a = after.get("entries", {})
    return any(not _entry_equal(entries_b[k], entries_a[k])
               for k in sorted(set(entries_b) | set(entries_a)))


def _backup(root: Path, id_dir: Path, before: dict) -> None:
    for rel, entry in before["entries"].items():
        if entry["type"] != "file":
            continue
        src = root / rel
        dst = id_dir / "before" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if _sha(dst) != entry["sha256"]:
            raise AblationError(f"before 备份校验失败：{rel}")
        os.chmod(dst, int(entry["mode"], 8))


def _restore_entry(root: Path, id_dir: Path, rel: str, entry: dict) -> None:
    target = root / rel
    if entry["type"] == "absent":
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return
    src = id_dir / "before" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    os.chmod(target, int(entry["mode"], 8))


def _smoke_arg(value: str | None) -> dict | None:
    if not value:
        return None
    argv = shlex.split(value)
    if not argv:
        raise AblationError("--smoke 不能为空")
    trivial = len(argv) == 1 and argv[0] in {"true", ":"}
    return {"argv": argv, "trivial": trivial}


def _run_smoke(root: Path, smoke: dict, ablation_id: str,
               timeout: int = 300) -> dict:
    env = dict(os.environ)
    env["ATLAS_ABLATION_ID"] = ablation_id
    try:
        p = subprocess.run(smoke["argv"], cwd=str(root), env=env,
                           capture_output=True, text=True, timeout=timeout)
        return {"argv": smoke["argv"], "rc": p.returncode,
                "stdout": p.stdout[-65536:], "stderr": p.stderr[-65536:]}
    except FileNotFoundError as exc:
        return {"argv": smoke["argv"], "rc": 127, "stdout": "", "stderr": str(exc)}
    except subprocess.TimeoutExpired as exc:
        return {"argv": smoke["argv"], "rc": 124, "stdout": "",
                "stderr": f"timeout: {exc}"}


def _write_result(id_dir: Path, result: dict) -> None:
    _atomic_json(id_dir / "result.json", result)


def _conflict_diff(root: Path, rel: str, before: dict, after: dict,
                   current: dict) -> list[str]:
    def text_of(entry: dict, source: str | None = None) -> list[str] | None:
        if entry.get("type") != "file":
            return None
        path = Path(source) if source else root / rel
        try:
            return path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return None
    cur = text_of(current)
    b = text_of(before)
    a = text_of(after)
    if cur is None or b is None or a is None:
        return []
    return list(difflib.unified_diff(b or [], cur or [],
                                     fromfile=f"before/{rel}", tofile=f"current/{rel}",
                                     lineterm=""))


def _result_base(active: dict, status: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "id": active.get("id"),
            "status": status, "finished": _now_iso(),
            "hash_verified": False, "smoke_verified": False}


def cmd_begin(args) -> int:
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise AblationError(f"root 不存在：{root}")
    if not ID_RE.match(args.id):
        raise AblationError("--id 只允许 [A-Za-z0-9._-]，且不得以符号开头")
    if not args.scope.strip():
        raise AblationError("--scope 不能为空")
    if args.timebox <= 0:
        raise AblationError("--timebox 必须为正整数（分钟）")
    patch = Path(args.patch).expanduser().resolve()
    if not patch.is_file():
        raise AblationError(f"patch 不存在：{patch}")
    state = _state_root(args.state_root)
    _ensure_state_outside(root, state)
    _ensure_state_root(state)
    root_dir = _root_dir(state, root)
    lock = _lock(root_dir)
    try:
        if _read_active(root_dir) is not None:
            raise AblationError("该 root 已有 active 消融；先 restore")
        _git_toplevel(root)
        _patch_summary(root, patch)
        raw_paths = _patch_paths(root, patch)
        if not raw_paths:
            raise AblationError("补丁没有任何触达路径")
        rels = sorted({_normalize_rel(root, p) for p in raw_paths})
        for rel in rels:
            target = root / rel
            if target.is_symlink() or not target.is_file():
                raise AblationError(f"MVP 只支持修改/删除现有普通文件：{rel}")
        mode = _host_mode(root)
        warning = _host_warning(root, mode, rels)
        status = _status_records(root)
        touched = set(rels)
        for xy, path in status:
            if path in touched:
                if _is_tracked(root, path):
                    raise AblationError(f"触碰集合内的 tracked 文件有未提交改动：{path}")
                continue
            if xy != "??" and not args.allow_dirty:
                raise AblationError(
                    f"触碰集合外的 tracked 文件有未提交改动：{path}（--allow-dirty 登记放行）")
        smoke = _smoke_arg(args.smoke)
        plan = {
            "schema_version": SCHEMA_VERSION, "id": args.id, "root": str(root),
            "root_id": _root_id(root), "host_mode": mode, "host_warning": warning,
            "scope": args.scope, "owner": args.owner, "started": _now_iso(),
            "timebox_min": args.timebox, "smoke": smoke, "smoke_baseline_rc": None,
            "patch_sha256": _sha(patch),
            "git_head": _git_text(root, "rev-parse", "HEAD").strip(),
            "git_branch": _git_text(root, "rev-parse", "--abbrev-ref", "HEAD").strip(),
            "git_dirty": bool(status), "python_version": sys.version.split()[0],
            "entries": rels,
        }
        id_dir = root_dir / args.id
        if id_dir.exists():
            raise AblationError(f"state dir 已存在：{id_dir}")
        _atomic_json(id_dir / "plan.json", plan)
        active = {
            "schema_version": SCHEMA_VERSION, "status": "pending", "id": args.id,
            "root": str(root), "root_id": plan["root_id"], "state_dir": str(id_dir),
            "host_mode": mode, "host_warning": warning, "scope": args.scope,
            "owner": args.owner, "started": plan["started"],
            "timebox_min": args.timebox, "plan": str(id_dir / "plan.json"),
            "before_manifest": str(id_dir / "manifest.before.json"),
            "after_manifest": str(id_dir / "manifest.after.json"),
        }
        try:
            _write_active(root_dir, active)
            _write_marker(root, active)
        except Exception:
            _remove_active(root_dir)
            _remove_marker(root)
            shutil.rmtree(id_dir, ignore_errors=True)
            raise
        try:
            before = _manifest(root, rels)
            _backup(root, id_dir, before)
            _atomic_json(id_dir / "manifest.before.json", before)
            if smoke:
                baseline = _run_smoke(root, smoke, args.id)
                plan["smoke_baseline_rc"] = baseline["rc"]
                _atomic_json(id_dir / "plan.json", plan)
                if baseline["rc"] != 0:
                    raise AblationError(f"baseline smoke 失败（rc={baseline['rc']}）")
                if _any_changed(before, _manifest(root, rels)):
                    raise AblationError("baseline smoke 改动了触达文件")
        except Exception:
            _remove_active(root_dir)
            _remove_marker(root)
            shutil.rmtree(id_dir, ignore_errors=True)
            raise
        try:
            check = _git(root, "apply", "--check", str(patch))
            if check.returncode != 0:
                raise AblationError(f"git apply --check 失败：{check.stderr.strip()[-300:]}")
            apply = _git(root, "apply", str(patch))
            if apply.returncode != 0:
                raise AblationError(f"git apply 失败：{apply.stderr.strip()[-300:]}")
        except Exception:
            if not _any_changed(before, _manifest(root, rels)):
                _remove_active(root_dir)
                _remove_marker(root)
                shutil.rmtree(id_dir, ignore_errors=True)
            raise
        after = _manifest(root, rels)
        if not _any_changed(before, after):
            _remove_active(root_dir)
            _remove_marker(root)
            shutil.rmtree(id_dir, ignore_errors=True)
            raise AblationError("apply 后没有任何字节变化")
        _atomic_json(id_dir / "manifest.after.json", after)
        extra = {(xy, p) for xy, p in _status_records(root)} - set(status)
        unexpected = []
        for xy, path in extra:
            if xy == "??" and (path == ".atlas/" or path.startswith(".atlas/")):
                continue          # 项目内 ABLATION 提示；不是补丁改动
            if _normalize_rel(root, path) not in touched:
                unexpected.append(path)
        if unexpected:
            raise AblationError(f"apply 改动了触达集合外的路径：{unexpected[:3]}")
        active.update(status="active", after_manifest=str(id_dir / "manifest.after.json"))
        _write_active(root_dir, active)
        print(f"ablation begin {args.id}: status=active scope={args.scope} "
              f"timebox={args.timebox}min host={mode} paths={len(rels)}")
        print(f"ATLAS_ABLATION_ID={args.id}")
        return 0
    finally:
        _unlock(lock)


def cmd_restore(args) -> int:
    root = Path(args.root).expanduser().resolve()
    state = _state_root(args.state_root)
    root_dir = _root_dir(state, root)
    lock = _lock(root_dir)
    try:
        active = _read_active(root_dir)
        if active is None:
            raise AblationError("该 root 没有 active 消融")
        if active.get("id") != args.id:
            raise AblationError(f"active id={active.get('id')} 与 --id={args.id} 不一致")
        if active.get("root") != str(root) or active.get("root_id") != _root_id(root):
            raise AblationError("active 与当前 root 不一致（路径/root_id）")
        plan = _load_json(Path(active["plan"]))
        id_dir = Path(active["state_dir"]).resolve()
        try:
            id_dir.relative_to(root_dir.resolve())
        except ValueError as exc:
            raise AblationError("active.state_dir 越出 state-root") from exc
        before = _load_json(Path(active["before_manifest"]))
        if before.get("schema_version") != SCHEMA_VERSION:
            raise AblationError("before manifest schema 不支持")
        after_path = Path(active.get("after_manifest", ""))
        after = _load_json(after_path) if after_path.is_file() else None
        entries_b = before.get("entries", {})
        entries_a = after.get("entries", {}) if after else {}
        if not isinstance(entries_b, dict) or not entries_b:
            raise AblationError("before manifest 为空")
        for rel, entry in entries_b.items():
            _normalize_rel(root, rel)
            if entry.get("type") != "file":
                continue
            backup = id_dir / "before" / rel
            if not backup.is_file() or _sha(backup) != entry.get("sha256"):
                result = _result_base(active, "restore_failed")
                result["error"] = f"before 备份缺失/哈希不符：{rel}"
                _write_result(id_dir, result)
                print(f"ERROR: {result['error']}", file=sys.stderr)
                return 2
        result = _result_base(active, "completed")
        current = {rel: _entry_at(root, rel) for rel in entries_b}
        conflicts = []
        for rel, cur in current.items():
            if _entry_equal(cur, entries_b[rel]):
                continue
            if after is not None and rel in entries_a and _entry_equal(cur, entries_a[rel]):
                continue
            conflicts.append(rel)
        if conflicts:
            conflict_path = id_dir / "conflict.json"
            _atomic_json(conflict_path, {
                "schema_version": SCHEMA_VERSION, "id": active["id"],
                "paths": {rel: {"current": current[rel],
                                "before": entries_b.get(rel),
                                "after": entries_a.get(rel),
                                "diff": _conflict_diff(root, rel, entries_b.get(rel, {}),
                                                       entries_a.get(rel, {}), current[rel])}
                          for rel in conflicts},
            })
            result.update(status="aborted", conflicts=conflicts, conflict_file=str(conflict_path))
            _write_result(id_dir, result)
            print(f"ERROR: restore 冲突，未写入任何文件：{conflicts[:5]}", file=sys.stderr)
            return 2
        # 全路径 preflight 通过；写回 before（只写 current == after 的）
        for rel, entry in entries_b.items():
            if _entry_equal(current[rel], entry):
                continue
            _restore_entry(root, id_dir, rel, entry)
        recheck = {rel: _entry_at(root, rel) for rel in entries_b}
        if any(not _entry_equal(recheck[rel], entries_b[rel]) for rel in entries_b):
            result.update(status="restore_failed", error="写回后哈希不等于 before")
            _write_result(id_dir, result)
            print("ERROR: 写回后哈希不等于 before", file=sys.stderr)
            return 2
        smoke = plan.get("smoke")
        if smoke:
            run = _run_smoke(root, smoke, active["id"],
                             timeout=int(plan.get("smoke_timeout", 300)))
            result["smoke"] = run
            if run["rc"] != 0:
                result.update(status="restore_failed", error=f"smoke rc={run['rc']}")
                _write_result(id_dir, result)
                print(f"ERROR: smoke 失败（rc={run['rc']}）", file=sys.stderr)
                return 2
            if _any_changed(before, _manifest(root, entries_b.keys())):
                result.update(status="restore_failed", error="smoke 改动了触达文件")
                _write_result(id_dir, result)
                print("ERROR: smoke 改动了触达文件", file=sys.stderr)
                return 2
        result["hash_verified"] = True
        result["smoke_verified"] = bool(smoke and not smoke.get("trivial"))
        result["status"] = "completed" if result["smoke_verified"] else "completed_hash_only"
        _write_result(id_dir, result)
        _remove_active(root_dir)
        _remove_marker(root)
        print(f"ablation restore {args.id}: {result['status']} "
              f"hash_verified={result['hash_verified']} smoke_verified={result['smoke_verified']}")
        return 0
    finally:
        _unlock(lock)


def cmd_status(args) -> int:
    root = Path(args.root).expanduser().resolve()
    state = _state_root(args.state_root)
    root_dir = _root_dir(state, root)
    active = _read_active(root_dir) if root_dir.exists() else None
    if active is None:
        print(f"no active ablation for {root}")
        return 0
    if args.id and active.get("id") != args.id:
        raise AblationError(f"active id={active.get('id')} 与 --id={args.id} 不一致")
    try:
        started = _parse_time(active["started"])
        deadline = started.timestamp() + int(active.get("timebox_min", 60)) * 60
        remaining = int(deadline - datetime.now().timestamp()) // 60
    except Exception:
        remaining = None
    marker_ok = False
    try:
        marker = _load_json(_marker_path(root))
        marker_ok = marker.get("id") == active.get("id")
    except Exception:
        pass
    print(f"ablation {active.get('id')} status={active.get('status')} root={root}")
    print(f"  scope={active.get('scope')} host={active.get('host_mode')} "
          f"started={active.get('started')} remaining_min={remaining}")
    print(f"  marker_ok={marker_ok} host_warning={active.get('host_warning')}")
    return 0


def inspect_root(root: Path, state_root: str | None = None) -> dict:
    """Gate 单源：只读检查当前 root 的消融事务。永不抛异常。"""
    try:
        state = _state_root(state_root)
        if not state.exists():
            return {"status": "na", "detail": "无消融状态目录（未做实验）"}
        root_dir = _root_dir(state, root)
        active = _read_active(root_dir) if root_dir.exists() else None
        marker = _marker_path(root)
        if active is None:
            if marker.exists():
                return {"status": "warn", "detail": "项目内存在 ABLATION 提示但无 active 真相源"}
            return {"status": "na", "detail": "无 active 消融（未做实验）"}
        if active.get("root") != str(root.resolve()):
            return {"status": "warn", "detail": "active.root 与当前 root 不一致"}
        if active.get("root_id") != _root_id(root):
            return {"status": "warn", "detail": "active.root_id 与当前目录不一致（重建/搬移？）"}
        try:
            plan = _load_json(Path(active["plan"]))
            before = _load_json(Path(active["before_manifest"]))
            after = _load_json(Path(active["after_manifest"]))
        except Exception as exc:
            return {"status": "warn", "detail": f"plan/manifest 不可读：{exc}"}
        if before.get("schema_version") != SCHEMA_VERSION:
            return {"status": "warn", "detail": "before manifest schema 不支持"}
        try:
            marker_data = _load_json(marker)
        except Exception:
            marker_data = {}
        if marker_data.get("id") != active.get("id"):
            return {"status": "warn", "detail": "项目内 ABLATION 标记缺失/ID 不一致"}
        entries_b = before.get("entries", {})
        entries_a = after.get("entries", {})
        if not isinstance(entries_b, dict) or not entries_b:
            return {"status": "warn", "detail": "before manifest 为空"}
        id_dir = Path(active["state_dir"]).resolve()
        try:
            id_dir.relative_to(root_dir.resolve())
        except ValueError:
            return {"status": "warn", "detail": "active.state_dir 越出 state-root"}
        for rel, entry in entries_b.items():
            try:
                _normalize_rel(root, rel)
            except AblationError as exc:
                return {"status": "warn", "detail": f"manifest 路径异常：{exc}"}
            if entry.get("type") == "file":
                backup = id_dir / "before" / rel
                if not backup.is_file() or _sha(backup) != entry.get("sha256"):
                    return {"status": "warn", "detail": f"before 备份缺失/哈希不符：{rel}"}
        current = {rel: _entry_at(root, rel) for rel in entries_b}
        all_before = all(_entry_equal(current[rel], entries_b[rel]) for rel in entries_b)
        all_after = all(
            rel in entries_a and _entry_equal(current[rel], entries_a[rel])
            for rel in entries_b)
        if active.get("status") != "active":
            return {"status": "warn",
                    "detail": f"事务状态={active.get('status')}（未完成）"}
        if not all_before and not all_after:
            if any(not (_entry_equal(current[rel], entries_b[rel])
                        or (rel in entries_a and _entry_equal(current[rel], entries_a[rel])))
                   for rel in entries_b):
                return {"status": "warn", "detail": "触达文件被第三人改动"}
            return {"status": "warn", "detail": "部分路径与 after 不一致"}
        if all_before:
            return {"status": "warn", "detail": "已还原但 active 未清除（半关闭）"}
        try:
            started = _parse_time(active["started"])
            deadline = started.timestamp() + int(active.get("timebox_min", 60)) * 60
            remaining = int((deadline - datetime.now().timestamp()) // 60)
        except Exception:
            return {"status": "warn", "detail": "started/timebox 不可解析"}
        if remaining < 0:
            return {"status": "warn", "detail": f"超时未关闭（{-remaining} 分钟）"}
        result_path = id_dir / "result.json"
        if result_path.exists():
            try:
                res = _load_json(result_path)
                if res.get("status") in ("completed", "completed_hash_only"):
                    return {"status": "warn", "detail": "result 已完成但 active 未清除"}
            except Exception:
                pass
        return {"status": "ok", "detail": f"消融进行中（{active.get('id')}，剩余 {remaining} 分钟）"}
    except Exception as exc:
        return {"status": "warn", "detail": f"状态不可核：{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("begin")
    b.add_argument("--id", required=True)
    b.add_argument("--root", default=".")
    b.add_argument("--patch", required=True)
    b.add_argument("--scope", required=True)
    b.add_argument("--state-root", default=None)
    b.add_argument("--timebox", type=int, default=60)
    b.add_argument("--smoke", default=None)
    b.add_argument("--owner", default=getpass.getuser())
    b.add_argument("--allow-dirty", action="store_true")
    r = sub.add_parser("restore")
    r.add_argument("--id", required=True)
    r.add_argument("--root", default=".")
    r.add_argument("--state-root", default=None)
    s = sub.add_parser("status")
    s.add_argument("--id", default=None)
    s.add_argument("--root", default=".")
    s.add_argument("--state-root", default=None)
    args = ap.parse_args()
    try:
        if args.cmd == "begin":
            return cmd_begin(args)
        if args.cmd == "restore":
            return cmd_restore(args)
        return cmd_status(args)
    except AblationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
