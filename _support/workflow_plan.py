#!/usr/bin/env python3
"""Atlas Workflow Plan —— 大任务拆解与任务卡结构化生成引擎 (Phase Plan)。

职责：
1. 读取业务需求输入（文本/Markdown），结合项目单源事实表（PRD、AC、架构透镜 FRAS）；
2. 自动拆分为平级有序的工作单元清单（Task DAG，严禁无限深度的子任务树）；
3. 生成符合 Atlas 契约规范的任务卡（`prd.md`，带 `atlas-acceptance:` 与四列 Confirmed 表）
   及元数据描述（`task.json`）。

纯标准库实现。
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

AC_RE = re.compile(r"AC-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{2,3}")
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PlanError(ValueError):
    """输入或规划预检错误。"""


def scan_known_acs(root: Path) -> dict[str, str]:
    """扫描项目内所有已知的 AC ID 及来源文件相对路径。"""
    root = root.resolve()
    prd_dir = root / "product" / "prd"
    acs: dict[str, str] = {}
    if not prd_dir.is_dir():
        return acs
    for p in sorted(prd_dir.rglob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        for m in AC_RE.finditer(text):
            ac_id = m.group(0)
            if ac_id not in acs:
                acs[ac_id] = rel
    return acs


def decompose_requirement(root: Path, requirement_text: str, unit: str) -> list[dict]:
    """将需求文本解析为结构化的任务单元列表 (Task DAG)。

    返回列表中的每一项包含：
    - id: 任务唯一标识（如 unit 或 unit-01）
    - title: 任务简述
    - acs: 关联的 AC 列表
    - depends_on: 前置依赖任务 ID 列表
    - affected_domains: 涉及的业务域
    - details: 任务详细说明
    """
    if not UNIT_RE.fullmatch(unit):
        raise PlanError(f"unit「{unit}」含有不合法字符")

    text = requirement_text.strip()
    if not text:
        raise PlanError("需求文本为空，无法进行任务分解")

    known_acs = scan_known_acs(root)
    mentioned_acs = [ac for ac in known_acs if ac in text]

    # 尝试解析多条任务小项（支持 - [ ] 或 ### 标题标记）
    sub_items = []
    lines = text.splitlines()
    curr_title = ""
    curr_body: list[str] = []

    for line in lines:
        m_task = re.match(r"^(?:###\s+|\d+\.\s+|-\s*\[[ x]\]\s*)(.+)$", line.strip())
        if m_task:
            if curr_title:
                sub_items.append((curr_title, "\n".join(curr_body)))
                curr_body = []
            curr_title = m_task.group(1).strip()
        else:
            curr_body.append(line)
    if curr_title:
        sub_items.append((curr_title, "\n".join(curr_body)))

    tasks: list[dict] = []
    if len(sub_items) > 1:
        # 分解为多任务平级 DAG
        prev_id = None
        for idx, (title, body) in enumerate(sub_items, start=1):
            t_id = f"{unit}-{idx:02d}"
            # 提取本任务包含的 AC
            item_acs = [ac for ac in mentioned_acs if ac in title or ac in body]
            tasks.append({
                "id": t_id,
                "title": title,
                "acs": item_acs,
                "depends_on": [prev_id] if prev_id else [],
                "affected_domains": _infer_domains(item_acs),
                "details": body.strip(),
            })
            prev_id = t_id
    else:
        # 单一工作单元
        first_line = lines[0].strip().lstrip("#").strip() if lines else unit
        tasks.append({
            "id": unit,
            "title": first_line or unit,
            "acs": mentioned_acs,
            "depends_on": [],
            "affected_domains": _infer_domains(mentioned_acs),
            "details": text,
        })

    return tasks


def _infer_domains(acs: list[str]) -> list[str]:
    """从 AC 命名规则（如 AC-HOME-001）反推域编码。"""
    domains = set()
    for ac in acs:
        parts = ac.split("-")
        if len(parts) >= 3:
            domains.add(parts[1].lower())
    return sorted(domains)


def render_prd_markdown(task: dict) -> str:
    """渲染符合 validate_task_card 校验契约的 prd.md。"""
    acs_str = ", ".join(task["acs"]) if task["acs"] else "none"
    lines = [
        f"# 任务需求卡 — {task['title']}",
        "",
        f"**任务编号**：`{task['id']}`  ",
        f"**前置依赖**：`{', '.join(task['depends_on']) if task['depends_on'] else '无'}`  ",
        f"**影响业务域**：`{', '.join(task['affected_domains']) if task['affected_domains'] else '通用'}`",
        "",
        "<!-- ATLAS:START -->",
        f"atlas-acceptance: {acs_str}",
        "<!-- ATLAS:END -->",
        "",
        "## 1. 任务背景与目标",
        task.get("details") or "根据需求完成相应模块改动及验收测试。",
        "",
        "## 2. 确认口径与证据台账 (Confirmed)",
        "",
        "| 确认项 | 确认口径 | 证据状态 | 证据指针 |",
        "|---|---|---|---|",
    ]
    if task["acs"]:
        for ac in task["acs"]:
            lines.append(f"| 验收基准 {ac} | 满足对应断言并经独立审查通过 | pending | N/A |")
    else:
        lines.append(f"| 功能实现 | 代码实现符合既有规范且测试绿灯 | pending | N/A |")

    lines.extend([
        "",
        "## 3. 变更范围与完成定义",
        "- [ ] 代码实现完成，无多余未跟踪修改",
        "- [ ] 暂存区通过 `atlas review --staged` 独立审查",
        "- [ ] 确定性测试/工具链全部通过",
        "",
    ])
    return "\n".join(lines)


def write_task_card(task_dir: Path, task: dict) -> Path:
    """写入单个任务卡目录（包含 prd.md 与 task.json）。

    重跑 plan 不得把已推进的状态打回 `todo`（状态机单调：todo < in_progress < completed）；
    已有 task.json 时沿用其 status 与 created_at。
    """
    task_dir.mkdir(parents=True, exist_ok=True)
    prd_path = task_dir / "prd.md"
    task_json_path = task_dir / "task.json"

    prd_text = render_prd_markdown(task)
    prd_path.write_text(prd_text, encoding="utf-8")

    prev = None
    if task_json_path.is_file():
        try:
            prev = json.loads(task_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = None

    meta = {
        "id": task["id"],
        "title": task["title"],
        "status": "todo",
        "depends_on": task["depends_on"],
        "affected_domains": task["affected_domains"],
        "acs": task["acs"],
        "created_at": date.today().isoformat(),
    }
    if task.get("paths"):
        meta["paths"] = list(task["paths"])
    if isinstance(prev, dict):
        if prev.get("status") in ("todo", "in_progress", "completed"):
            meta["status"] = prev["status"]
        if isinstance(prev.get("created_at"), str) and prev["created_at"]:
            meta["created_at"] = prev["created_at"]
        # 重跑 plan（含 `atlas workflow run`）未显式给 --paths 时沿用已存路径，
        # 否则派工单的最小注入会退回 tour 兜底（状态机可重放的前提）。
        if "paths" not in meta and isinstance(prev.get("paths"), list):
            meta["paths"] = prev["paths"]
    task_json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return task_dir


def load_tasks(tasks_root: Path) -> list[dict]:
    """读取所有任务元数据并进行依赖拓扑排序。"""
    if not tasks_root.is_dir():
        return []
    tasks: dict[str, dict] = {}
    for p in sorted(tasks_root.rglob("task.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "id" in data:
            data["_dir"] = str(p.parent)
            tasks[data["id"]] = data

    # 简单拓扑排序
    sorted_tasks: list[dict] = []
    visited: set[str] = set()

    def visit(tid: str, path: list[str]) -> None:
        if tid in path:
            raise PlanError(f"任务依赖成环：{' -> '.join(path + [tid])}")
        if tid in visited or tid not in tasks:
            return
        for dep in tasks[tid].get("depends_on") or []:
            visit(dep, path + [tid])
        visited.add(tid)
        sorted_tasks.append(tasks[tid])

    for tid in sorted(tasks.keys()):
        visit(tid, [])

    return sorted_tasks
