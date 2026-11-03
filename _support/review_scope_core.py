#!/usr/bin/env python3
"""共享内核 —— 审查范围内容封口 + apply 基线（RFC-20261103-01）。

给实例⑤的 `review.json` v4 提供**内容锚**：不是「CLI 说审了这些路径」，而是
「这些路径在报告落盘时的内容摘要」。同一套机器同时服务 apply 起始脏工作区基线
（A4）：只记录、只告警，不阻断 Trellis 的 apply 边界。

纯标准库。路径只接受项目根内的相对路径；哈希按 1 MiB 分块流式读取；
超过 `MAX_HASH_BYTES` 的文件退化为 `size_mtime` 模式并显式标注，不冒充逐字节封口。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
MAX_HASH_BYTES = 10 * 1024 * 1024
HASH_SHA256 = "sha256"
HASH_SIZE_MTIME = "size_mtime"
HASH_ABSENT = "absent"
UNIT_RE_STR = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


class ScopeError(Exception):
    """输入/路径/状态错误（调用方按 exit 2 处理）。"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_rel(root: Path, raw: object) -> str:
    """项目根内相对路径；拒绝绝对路径、`..` 与逃逸到根外的解析结果。"""
    s = str(raw or "").strip().replace("\\", "/")
    if not s:
        raise ScopeError("路径为空")
    p = Path(s)
    if p.is_absolute():
        raise ScopeError(f"不接受绝对路径：{s}")
    if ".." in p.parts:
        raise ScopeError(f"不接受 `..`：{s}")
    if s.startswith("./"):
        s = s[2:]
    target = (root / s).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ScopeError(f"路径逃逸项目根：{s}")
    return s


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_status_map(root: Path) -> dict[str, str]:
    """`git status --porcelain -z` → {path: XY}；非 git 仓返回空表（状态只作人读）。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "-z", "--untracked-files=all"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    raw = out.stdout
    records = raw.split("\0")
    result: dict[str, str] = {}
    i = 0
    while i < len(records):
        rec = records[i]
        if not rec:
            i += 1
            continue
        if len(rec) < 4:
            i += 1
            continue
        xy, path = rec[:2], rec[3:]
        result[path.replace("\\", "/")] = xy.strip() or "clean"
        if xy[:1] in ("R", "C") or xy[1:2] in ("R", "C"):
            # `-z` 的 rename/copy：下一条是原路径，不属于当前条目
            i += 2
        else:
            i += 1
    return result


def entry_for(root: Path, rel: str, status_map: dict[str, str] | None = None) -> dict:
    """单个路径的内容条目。删除 ⇒ `absent`；大文件 ⇒ `size_mtime`。"""
    rel = normalize_rel(root, rel)
    p = root / rel
    status = (status_map or {}).get(rel, "clean")
    if not p.exists():
        # 只有 git 明确报删除的路径才允许 absent；否则是「审了一个不存在的文件」
        if status.startswith("D") or (len(status) > 1 and status[1] == "D"):
            return {"path": rel, "status": "D", "sha256": HASH_ABSENT,
                    "size": 0, "hash_mode": HASH_ABSENT}
        raise ScopeError(f"文件不存在：{rel}")
    if p.is_symlink():
        raise ScopeError(f"不接受符号链接：{rel}")
    if p.is_dir():
        raise ScopeError(f"不接受目录：{rel}")
    st = p.stat()
    if st.st_size > MAX_HASH_BYTES:
        return {"path": rel, "status": status, "sha256": f"{HASH_SIZE_MTIME}:{st.st_size}:{st.st_mtime_ns}",
                "size": st.st_size, "hash_mode": HASH_SIZE_MTIME}
    return {"path": rel, "status": status, "sha256": sha256_file(p),
            "size": st.st_size, "hash_mode": HASH_SHA256}


def scope_digest(files: list[dict]) -> str:
    """内容摘要：只哈希 `path + sha256 + hash_mode`，不掺 git 状态与 size（防状态噪声抖动）。

    大文件 `size_mtime` 模式的 `sha256` 字段已含 size + mtime_ns，仍参与哈希，
    但报告里 `hash_mode=size_mtime` 会显式标注「不可逐字节复算」。
    """
    lines: list[str] = []
    for item in sorted(files, key=lambda x: x["path"]):
        lines.append(f"{item['path']}\0{item['sha256']}\0{item.get('hash_mode', HASH_SHA256)}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def build_manifest(root: Path, paths: list[str], *, base: str | None = None,
                   head: str | None = None) -> dict:
    root = root.resolve()
    normalized = sorted({normalize_rel(root, p) for p in paths})
    if not normalized:
        raise ScopeError("实审集为空：至少给一个 reviewed file")
    status_map = _git_status_map(root)
    files = [entry_for(root, p, status_map) for p in normalized]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "root": str(root),
        "base": (base or "").strip(),
        "head": (head or "").strip(),
        "files": files,
        "scope_sha256": scope_digest(files),
    }


def load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScopeError(f"读 scope manifest {path} 失败：{exc}")
    if not isinstance(data, dict):
        raise ScopeError(f"{path} 顶层不是 JSON 对象")
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ScopeError(f"{path} 缺非空 files[]")
    for i, item in enumerate(files):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"].strip():
            raise ScopeError(f"{path} files[{i}] 缺 path")
        if not isinstance(item.get("sha256"), str) or not item["sha256"].strip():
            raise ScopeError(f"{path} files[{i}] 缺 sha256")
    if not isinstance(data.get("scope_sha256"), str) or not data["scope_sha256"].strip():
        raise ScopeError(f"{path} 缺 scope_sha256")
    return data


def verify_manifest(root: Path, manifest: dict) -> tuple[bool, dict, list[str]]:
    """按 manifest 的路径重算当前内容，返回 (ok, current_manifest, diffs)。"""
    paths = [item["path"] for item in manifest["files"]]
    current = build_manifest(root, paths, base=manifest.get("base"), head=manifest.get("head"))
    diffs: list[str] = []
    before = {item["path"]: item for item in manifest["files"]}
    after = {item["path"]: item for item in current["files"]}
    for path in sorted(set(before) | set(after)):
        if path not in after:
            diffs.append(f"{path}：当前不可读/不存在")
        elif path not in before:
            diffs.append(f"{path}：不在原清单")
        elif before[path].get("sha256") != after[path].get("sha256"):
            diffs.append(f"{path}：内容已变化")
    ok = current["scope_sha256"] == manifest["scope_sha256"] and not diffs
    return ok, current, diffs


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _unit(unit: str) -> str:
    import re
    if not re.fullmatch(UNIT_RE_STR, unit or ""):
        raise ScopeError(f"unit「{unit}」含文件名不安全字符")
    return unit


def baseline_path(root: Path, unit: str) -> Path:
    return root / ".atlas" / "runs" / _unit(unit) / "apply-baseline.json"


def baseline_begin(root: Path, unit: str) -> dict:
    root = root.resolve()
    unit = _unit(unit)
    status_map = _git_status_map(root)
    files = [entry_for(root, p, status_map) for p in sorted(status_map)]
    data = {"schema_version": SCHEMA_VERSION, "unit": unit, "created_at": now_iso(),
            "root": str(root), "files": files,
            "scope_sha256": scope_digest(files) if files else ""}
    atomic_write_json(baseline_path(root, unit), data)
    return data


def baseline_check(root: Path, unit: str, changed_files: list[str] | None = None) -> dict:
    root = root.resolve()
    unit = _unit(unit)
    path = baseline_path(root, unit)
    changed = {normalize_rel(root, p) for p in (changed_files or [])}
    if not path.is_file():
        return {"status": "WARN", "unit": unit, "detail": "基线缺失（未 begin）",
                "baseline": str(path), "overlap": [], "new_dirty": [],
                "changed_existing": [], "cleared_baseline": [], "unchanged": []}
    try:
        before = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "WARN", "unit": unit, "detail": f"基线不可读：{exc}",
                "baseline": str(path), "overlap": [], "new_dirty": [],
                "changed_existing": [], "cleared_baseline": [], "unchanged": []}
    before_map = {item["path"]: item for item in before.get("files", [])
                  if isinstance(item, dict) and isinstance(item.get("path"), str)}
    status_map = _git_status_map(root)
    current_map: dict[str, dict] = {}
    for p in sorted(status_map):
        try:
            current_map[p] = entry_for(root, p, status_map)
        except ScopeError:
            continue
    unchanged = {p for p in set(before_map) & set(current_map)
                 if before_map[p].get("sha256") == current_map[p].get("sha256")}
    new_dirty = sorted(set(current_map) - set(before_map))
    changed_existing = sorted(p for p in set(before_map) & set(current_map)
                              if before_map[p].get("sha256") != current_map[p].get("sha256"))
    # 基线内既有脏改动「从 status 消失」（被提交/还原）且又出现在本次改动里：
    # 无法区分是「本次把它提交了」还是「本次改了同路径」，仍算重叠（只 WARN）。
    cleared = sorted((set(before_map) - set(current_map)) & changed)
    overlap = sorted((set(new_dirty) | set(changed_existing) | set(cleared)) & changed)
    status = "WARN" if overlap else "PASS"
    return {"status": status, "unit": unit,
            "detail": ("与本次改动重叠，无法区分本次改动与既有脏改动" if overlap
                       else f"未变化基线 {len(unchanged)} 个；新增/变化 {len(new_dirty) + len(changed_existing)} 个"),
            "baseline": str(path), "overlap": overlap,
            "new_dirty": new_dirty, "changed_existing": changed_existing,
            "cleared_baseline": cleared, "unchanged": sorted(unchanged)}
