#!/usr/bin/env python3
"""Atlas Workflow Progress —— in_progress 任务进度只读探针 (RFC-20261122-02)。

四格聚合「做到哪」的**既有证据**（纯派生：不写盘、不改状态、零新字段、零新门）：
  派工（dispatch.md + AC/paths）· 实现（暂存区 diff ∩ paths，中性计数）
  审查（product/reviews 轮次，按〔日期,轮号〕排序）· 对账（coverage-matrix 填写进度）

口径纪律：
- 暂存区是仓库级：范围外文件**含其他在途任务的正常暂存**，不暗示跑偏（Major-3）；
- 轮号按日重置：跨日轮次不连续，计数必须按「跨 N 日共 M 轮」分段（Minor-4）；
- git 不可用与暂存为空分开呈现（复用 `staged_files` 的 `None`/`[]` 语义，Minor-6）；
- 命中 = 路径级存在性（`hit_path` 同 dispatch 口径），**非内容级证据**——AC 级结论
  只认 verify 与 review.json（Minor-10 盲区注记）。

纯标准库。
"""
from __future__ import annotations

import json
from pathlib import Path

from _support.workflow_context import hit_path
from _support.workflow_finish import scan_review_rounds, staged_files
from _support.workflow_plan import load_tasks
from _support.workflow_verify import MATRIX_COLUMNS, first_table

MATRIX_FILE = "coverage-matrix.md"
DISPATCH_FILE = "dispatch.md"
UNRESOLVED_TOKEN = "UNRESOLVED"


def _classify_staged(staged: list[str] | None, paths: list[str] | None) -> dict:
    """实现格：暂存文件按任务 paths 分内外（中性计数；None = 非 git 环境）。"""
    if staged is None:
        return {"kind": "unavailable", "inside": [], "outside": [],
                "note": "非 git 环境（无法读取暂存区）"}
    if not staged:
        return {"kind": "empty", "inside": [], "outside": [],
                "note": "暂存区为空（尚未 `git add`）"}
    globs = [str(p).strip() for p in (paths or []) if str(p).strip()]
    if not globs:
        return {"kind": "partial", "inside": [], "outside": sorted(staged),
                "note": f"暂存 {len(staged)} 文件；任务卡未声明 paths，无法分内外"}
    inside = [f for f in staged if any(hit_path(f, g) for g in globs)]
    outside = [f for f in staged if f not in inside]
    return {"kind": "partial", "inside": inside, "outside": outside,
            "note": "范围外含其他在途任务的正常暂存，不必然是跑偏"}


def _classify_matrix(task_dir: Path) -> dict:
    """对账格：coverage-matrix 逐列「已填 / 总行 / UNRESOLVED」（无矩阵不报错）。"""
    path = task_dir / MATRIX_FILE
    if not path.is_file():
        return {"present": False, "rows": 0, "columns": {},
                "note": "无矩阵（plan 未带 --requirement 的非需求驱动卡，不判）"}
    rows = first_table(path.read_text(encoding="utf-8", errors="replace"), MATRIX_COLUMNS)
    if rows is None:
        return {"present": True, "rows": 0, "columns": {},
                "note": "矩阵存在但无合法表（表头须含 " + " / ".join(MATRIX_COLUMNS) + "）"}
    header, data_rows = rows[0], rows[1:]
    col_idx = {name: next((i for i, c in enumerate(header) if name in c), None)
               for name in MATRIX_COLUMNS}
    columns: dict[str, dict] = {}
    for name, idx in col_idx.items():
        filled = unresolved = 0
        for row in data_rows:
            value = row[idx].strip() if (idx is not None and len(row) > idx) else ""
            if not value:
                continue
            if UNRESOLVED_TOKEN in value:
                unresolved += 1
            else:
                filled += 1
        columns[name] = {"filled": filled, "unresolved": unresolved}
    return {"present": True, "rows": len(data_rows), "columns": columns, "note": ""}


def _latest_review(rounds: list[tuple[str, int, Path]]) -> dict | None:
    """最近轮 = （目录日期, 轮号）排序最大者；结论读 `status`/`ok`（口径同终报）。"""
    if not rounds:
        return None
    date_str, round_no, path = rounds[-1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"date": date_str, "round": round_no, "status": "UNKNOWN", "ok": None}
    return {"date": date_str, "round": round_no,
            "status": str(data.get("status") or "unknown").strip().upper(),
            "ok": data.get("ok")}


def progress_snapshot(root: Path, unit: str) -> dict:
    """主入口：返回四格进度快照（纯只读；不做 AC 级判定）。"""
    root = Path(root)
    tasks_root = root / ".atlas" / "tasks"
    tasks = load_tasks(tasks_root, include_archived=True)

    target = next((t for t in tasks if t["id"] == unit), None)
    if target is None:
        # 组 ID（plan 拆出的 <unit>-NN）：不猜落点，列成员卡要求精确 ID。
        # 坏卡无需在此处理：load_tasks 对解析失败的卡指名抛 PlanError（被 main 捕获 die(2)），
        # 评审 Minor-8 假设的「静默跳过」路径不存在。
        members = sorted(t["id"] for t in tasks if t["id"].startswith(f"{unit}-"))
        if members:
            return {"unit": unit, "status": "group", "members": members}
        return {"unit": unit, "status": "missing"}

    snap: dict = {"unit": unit, "status": target.get("status", "unknown"),
                  "title": target.get("title", ""), "archived": bool(target.get("_archived"))}
    if snap["status"] in ("todo", "completed", "unknown"):
        return snap  # 终态/未派工/未知态：只报状态，不探四格

    task_dir = Path(target.get("_dir") or (tasks_root / unit))
    paths = [str(p) for p in (target.get("paths") or []) if str(p).strip()]
    acs = target.get("acs") or []
    rounds = scan_review_rounds(root, unit)
    snap["stages"] = {
        "dispatch": {"present": (task_dir / DISPATCH_FILE).is_file(),
                     "acs": len(acs), "paths": paths},
        "staged": _classify_staged(staged_files(root), paths),
        "review": {"days": len({d for d, _r, _p in rounds}),
                   "rounds": len(rounds), "latest": _latest_review(rounds)},
        "matrix": _classify_matrix(task_dir),
    }
    return snap


def render_progress(snap: dict) -> str:
    """终端四格渲染（--json 走 cmd 层直出 snapshot）。"""
    unit, status = snap["unit"], snap["status"]
    if status == "missing":
        return f"progress @ {unit}: 未找到任务卡（先 `atlas workflow plan`）"
    if status == "group":
        members = "、".join(snap.get("members") or [])
        return (f"progress @ {unit}: 组标识（plan 拆出成员卡），请给精确 ID。\n"
                f"  成员：{members}")
    if status == "todo":
        return f"progress @ {unit} ({status}): 未派工；先 `atlas workflow dispatch`"
    if status == "completed":
        suffix = " [archived]" if snap.get("archived") else ""
        return (f"progress @ {unit} ({status}){suffix}: 已收口；"
                "历史看 `atlas workflow status --all`")
    if status != "in_progress":
        return f"progress @ {unit}: 状态 {status}，不探进度（探针只对 in_progress 展开）"

    st = snap["stages"]
    disp = st["dispatch"]
    lines = [f"atlas workflow progress @ {unit} (in_progress) —— {snap.get('title', '')}",
             f"  派工：{'dispatch.md 已生成' if disp['present'] else 'dispatch.md 缺失'}；"
             f"AC {disp['acs']} 条"
             + (f"；paths: {', '.join(disp['paths'])}" if disp["paths"] else "；无 paths 声明")]
    sg = st["staged"]
    if sg["kind"] in ("unavailable", "empty"):
        lines.append(f"  实现：{sg['note']}")
    else:
        inside = "、".join(sg["inside"]) or "（无）"
        outside = "、".join(sg["outside"]) or "（无）"
        lines.append(f"  实现：暂存 paths 内 {len(sg['inside'])} / paths 外 {len(sg['outside'])}"
                     f" —— {sg['note']}")
        lines.append(f"        内：{inside}")
        lines.append(f"        外：{outside}")
    rv = st["review"]
    latest = rv["latest"]
    if latest:
        latest_text = (f"最近轮 {latest['date']} r{latest['round']}"
                       f" —— status={latest['status']}"
                       + (f" ok={str(latest['ok']).lower()}" if latest["ok"] is not None else ""))
    else:
        latest_text = "尚无审查轮次（先 `atlas workflow verify`）"
    lines.append(f"  审查：跨 {rv['days']} 日共 {rv['rounds']} 轮；{latest_text}")
    mx = st["matrix"]
    if not mx["present"] or mx["note"]:
        lines.append(f"  对账：{mx['note'] or '矩阵存在但无合法表'}")
    else:
        if mx["rows"] == 0:
            lines.append("  对账：矩阵骨架 0 数据行（条目枚举未填，#72 开工前置）")
        else:
            cols = "；".join(f"{name} {c['filled']}/{mx['rows']}"
                             + (f"（UNRESOLVED {c['unresolved']}）" if c["unresolved"] else "")
                             for name, c in mx["columns"].items())
            lines.append(f"  对账：矩阵 {mx['rows']} 行 —— {cols}")
    return "\n".join(lines)
