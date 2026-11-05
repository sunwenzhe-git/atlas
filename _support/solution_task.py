#!/usr/bin/env python3
"""atlas solution task —— 父级 requirement → 成员 Trellis 任务卡（Phase 1 增量）。

边界：
- 只在成员仓 `.trellis/tasks/` 创建任务卡 / `solution.md` 指针 / curated context；
- **不** start、**不** commit、**不**写代码/资产/PRD；
- 不创建父级 `.trellis`；父级 AC 正文仍在 `solution-prd.md`。

契约正文见 `shared/solution.md`；本模块不 import solution（由调用方传入 manifest），
避免循环加载。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

AC_RE = re.compile(r"AC-[A-Z0-9]+-\d{3}")
SLUG_BAD = re.compile(r"[/\\]|\.\.")


class TaskError(ValueError):
    """输入 / 预检错误（CLI exit 2）。"""


def _assets_root(root: Path) -> str:
    config = Path(root) / "atlas.config.yaml"
    if config.is_file():
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("assets_root:"):
                v = s.split(":", 1)[1].strip().strip("'\"")
                if v:
                    return v
    return "product"


def _task_py(member: Path) -> Path:
    return member / ".trellis" / "scripts" / "task.py"


def _run(member: Path, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_task_py(member)), *args],
        cwd=str(member), capture_output=True, text=True, timeout=timeout,
    )


def _probe(member: Path) -> None:
    task_py = _task_py(member)
    if not task_py.is_file():
        raise TaskError(f"{member.name}: 缺少 .trellis/scripts/task.py")
    try:
        create_help = _run(member, ["create", "--help"])
        context_help = _run(member, ["add-context", "--help"])
    except (OSError, subprocess.SubprocessError) as exc:
        raise TaskError(f"{member.name}: task.py 不可执行: {exc}") from exc
    text = (create_help.stdout or "") + (create_help.stderr or "")
    for flag in ("--slug", "--assignee", "--description", "--meta", "--no-start"):
        if flag not in text:
            raise TaskError(f"{member.name}: task.py create 缺能力 {flag}")
    ctx = (context_help.stdout or "") + (context_help.stderr or "")
    if "add-context" not in ctx and "argument" not in ctx:
        raise TaskError(f"{member.name}: task.py add-context 不可用")


def _task_json(member: Path) -> list[tuple[Path, dict]]:
    root = member / ".trellis" / "tasks"
    if not root.is_dir():
        return []
    out: list[tuple[Path, dict]] = []
    for path in sorted(root.rglob("task.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out.append((path.parent, data))
    return out


def _meta(data: dict) -> dict:
    meta = data.get("meta")
    return meta if isinstance(meta, dict) else {}


def find_task(member: Path, solution: str, requirement: str,
              member_name: str | None = None) -> tuple[Path, dict] | None:
    target = member_name or member.name
    for task_dir, data in _task_json(member):
        meta = _meta(data)
        if (meta.get("solution") == solution
                and meta.get("requirement") == requirement
                and meta.get("member") == target):
            return task_dir, data
    return None


def _slug_ok(slug: str) -> bool:
    return bool(slug) and not SLUG_BAD.search(slug) and not re.match(r"^\d{2}-\d{2}-", slug)


def _slug_collision(member: Path, slug: str) -> Path | None:
    tasks = member / ".trellis" / "tasks"
    if not tasks.is_dir():
        return None
    for path in sorted(tasks.rglob(f"*-{slug}")):
        if path.is_dir():
            return path
    return None


def _context_has(task_dir: Path, kind: str) -> bool:
    path = task_dir / f"{kind}.jsonl"
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        ref = str(item.get("file") or item.get("path") or "")
        if ref.endswith("solution.md"):
            return True
    return False


def _context_ok(task_dir: Path) -> bool:
    return all(_context_has(task_dir, kind) for kind in ("implement", "check"))


def _ensure_context(member: Path, task_dir: Path, rel: str) -> None:
    for kind in ("implement", "check"):
        if _context_has(task_dir, kind):
            continue
        c = _run(member, ["add-context", rel, kind, f"{rel}/solution.md",
                          "跨仓任务父级指针"])
        if c.returncode != 0:
            raise TaskError(f"{member.name}: add-context {kind} 失败: "
                            f"{(c.stderr or c.stdout)[-300:]}")


def _ac_defs(root: Path, assets_root: str) -> set[str]:
    prd = Path(root) / assets_root / "prd" / "solution-prd.md"
    if not prd.is_file():
        return set()
    defs: set[str] = set()
    for line in prd.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\|\s*`?(AC-[A-Z0-9]+-\d{3})`?\s*\|", line)
        if m:
            defs.add(m.group(1))
    return defs


def _pointer(root: Path, member: Path, data: dict, req: dict, assets_root: str) -> str:
    member_name = req["member"]
    manifest = os.path.relpath(Path(root) / "atlas.solution.yaml", member)
    prd = os.path.relpath(Path(root) / assets_root / "prd" / "solution-prd.md", member)
    contracts = [
        c["id"] for c in data.get("contracts") or []
        if c.get("producer") == member_name or c.get("consumer") == member_name
    ]
    lines = [
        "# 跨仓任务指针",
        "",
        f"- parent_solution: {data['solution']}",
        f"- parent_manifest: {manifest}",
        f"- parent_prd: {prd}",
        f"- requirement: {req['id']}",
        f"- acs: {','.join(req['acs'])}",
        f"- member: {req['member']}",
        f"- scope: {req['scope']}",
        f"- contracts: {', '.join(contracts) if contracts else '—'}",
        "",
        "> 父级 AC 正文只在 parent_prd；本文件只放指针与本地 scope，不复制需求。",
        "",
    ]
    return "\n".join(lines)


def _developer_name(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("name="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    return None


def _assignee(member: Path, req: dict) -> str:
    if req.get("assignee"):
        return str(req["assignee"])
    env = os.environ.get("TRELLIS_DEVELOPER")
    if env:
        return env
    own = _developer_name(member / ".trellis" / ".developer")
    if own:
        return own
    # Trellis 的 worktree 语义：成员本身是 worktree 时，回落到主工作树的 .developer。
    try:
        p = subprocess.run(["git", "-C", str(member), "worktree", "list", "--porcelain"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        p = None
    if p is not None and p.returncode == 0:
        for line in p.stdout.splitlines():
            if line.startswith("worktree "):
                main = Path(line.split(" ", 1)[1]).resolve()
                if main != member.resolve():
                    value = _developer_name(main / ".trellis" / ".developer")
                    if value:
                        return value
                break
    raise TaskError(f"{member.name}: 缺少 assignee 与可解析的 .trellis/.developer")


def _select(data: dict, requirement: str, members: list[str] | None) -> list[dict]:
    reqs = [r for r in data.get("requirements") or [] if r["id"] == requirement]
    if members:
        reqs = [r for r in reqs if r["member"] in members]
    if not reqs:
        raise TaskError(f"没有匹配的 requirement 条目: {requirement}")
    return reqs


def create_tasks(root: Path, data: dict, requirement: str,
                 members: list[str] | None = None, apply: bool = False,
                 resume: bool = False, update: bool = False) -> dict:
    root = Path(root).resolve()
    assets_root = _assets_root(root)
    reqs = _select(data, requirement, members)
    defs = _ac_defs(root, assets_root)
    by_name = {m["name"]: m for m in data["members"]}
    plans: list[dict] = []
    for req in reqs:
        member = (root / by_name[req["member"]]["path"]).resolve()
        if not member.is_dir():
            raise TaskError(f"{req['member']}: 成员路径不存在")
        if not _slug_ok(req["task_slug"]):
            raise TaskError(f"{req['id']}: task_slug 非法: {req['task_slug']!r}")
        missing = [ac for ac in req["acs"] if ac not in defs]
        if missing:
            raise TaskError(f"{req['id']}: AC 定义行不存在: {missing}")
        _probe(member)
        assignee = _assignee(member, req)
        existing = find_task(member, data["solution"], req["id"], req["member"])
        if update and not existing:
            raise TaskError(f"{req['member']}: --update 需要已存在的同 requirement 任务")
        if existing:
            task_dir, _ = existing
            pointer = task_dir / "solution.md"
            if update:
                plans.append({"member": req["member"], "member_path": str(member),
                              "task": str(task_dir), "action": "update",
                              "assignee": assignee, "req": req})
                continue
            if resume and pointer.is_file() and req["scope"] in pointer.read_text(
                    encoding="utf-8", errors="replace"):
                action = "skip" if _context_ok(task_dir) else "repair"
                plans.append({"member": req["member"], "member_path": str(member),
                              "task": str(task_dir), "action": action,
                              "assignee": assignee, "req": req})
                continue
            raise TaskError(f"{req['member']}: 已存在同 requirement 任务: {task_dir}"
                            "（可用 --resume 修复/跳过，或 --update 只更新指针）")
        collision = _slug_collision(member, req["task_slug"])
        if collision:
            raise TaskError(f"{req['member']}: task_slug 冲突: {collision}")
        plans.append({"member": req["member"], "member_path": str(member),
                      "task_slug": req["task_slug"], "assignee": assignee,
                      "action": "create", "scope": req["scope"], "req": req})
    if not apply:
        return {"apply": False, "plans": plans}

    done: list[dict] = []
    for plan in plans:
        req = plan["req"]
        member = Path(plan["member_path"])
        if plan["action"] in ("update", "repair"):
            task_dir = Path(plan["task"])
            (task_dir / "solution.md").write_text(
                _pointer(root, member, data, req, assets_root), encoding="utf-8")
            rel = task_dir.relative_to(member).as_posix()
            _ensure_context(member, task_dir, rel)
            done.append({"member": req["member"], "task": str(task_dir),
                         "action": plan["action"]})
            continue
        if plan["action"] == "skip":
            done.append({"member": req["member"], "task": plan["task"], "action": "skip"})
            continue
        title = f"[{req['acs'][0]}] {req['id']}"
        pointer = f"跨仓任务 {req['id']} / {','.join(req['acs'])}；详见 solution.md"
        p = _run(member, [
            "create", title, "--slug", req["task_slug"], "--assignee", plan["assignee"],
            "--description", pointer,
            "--meta", f"solution={data['solution']}",
            "--meta", f"requirement={req['id']}",
            "--meta", f"member={req['member']}",
            "--no-start",
        ])
        if p.returncode != 0:
            raise TaskError(f"{req['member']}: task.py create 失败: {(p.stderr or p.stdout)[-300:]}")
        found = find_task(member, data["solution"], req["id"], req["member"])
        if found is None:
            raise TaskError(f"{req['member']}: create 后找不到 meta 任务")
        task_dir, _ = found
        (task_dir / "solution.md").write_text(
            _pointer(root, member, data, req, assets_root), encoding="utf-8")
        rel = task_dir.relative_to(member).as_posix()
        _ensure_context(member, task_dir, rel)
        done.append({"member": req["member"], "task": str(task_dir), "action": "create"})
    return {"apply": True, "done": done}


def task_status(root: Path, data: dict, requirement: str | None = None) -> dict:
    root = Path(root).resolve()
    assets_root = _assets_root(root)
    defs = _ac_defs(root, assets_root)
    by_name = {m["name"]: m for m in data["members"]}
    reqs = data.get("requirements") or []
    warnings: list[str] = []
    if requirement:
        reqs = [r for r in reqs if r["id"] == requirement]
        if not reqs:
            warnings.append(f"requirement 不存在: {requirement}")
    rows = []
    for req in reqs:
        member = (root / by_name[req["member"]]["path"]).resolve()
        found = find_task(member, data["solution"], req["id"], req["member"]) \
            if member.is_dir() else None
        ac_missing = [ac for ac in req["acs"] if ac not in defs]
        pointer_ok = bool(found and (found[0] / "solution.md").is_file())
        context_ok = bool(found and _context_ok(found[0]))
        row = {"requirement": req["id"], "member": req["member"],
               "task": str(found[0]) if found else None,
               "acs": req["acs"], "ac_missing": ac_missing,
               "pointer": pointer_ok, "context": context_ok}
        rows.append(row)
        if not found:
            warnings.append(f"{req['id']}/{req['member']}: 成员任务缺失")
        elif not pointer_ok:
            warnings.append(f"{req['id']}/{req['member']}: solution.md 缺失")
        elif not context_ok:
            warnings.append(f"{req['id']}/{req['member']}: implement/check context 指针缺失")
        if ac_missing:
            warnings.append(f"{req['id']}: AC 定义行缺失 {ac_missing}")
    return {"requirements": rows, "warnings": warnings, "ok": not warnings}


def check_requirements(root: Path, data: dict) -> list[str]:
    return task_status(root, data)["warnings"]
