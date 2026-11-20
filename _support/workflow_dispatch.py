#!/usr/bin/env python3
"""Atlas Workflow Dispatch —— 最小上下文装配与分发派单引擎 (Phase Implement)。

职责：
1. 选取就绪的下一个子任务（前置依赖已全部 completed）；
2. 进行最小上下文提取（Curated Context）：只提取当前任务卡、受影响域的 AC 指针、测试用例分片，
   坚决不注入全仓无关 spec 噪音；
3. 生成派工单指令文件（`dispatch.md`），供执行子代理或开发者查阅；
4. 将任务状态原子流转至 `in_progress`。

纯标准库实现。
"""
from __future__ import annotations

import json
from pathlib import Path

from _support.workflow_plan import load_tasks, PlanError
from _support.workflow_context import render_specs, select_specs


class DispatchError(ValueError):
    """派单调度异常。"""


def get_next_runnable_task(tasks_root: Path) -> dict | None:
    """寻找下一个可执行的任务（状态为 todo 且其依赖均已 completed）。"""
    tasks = load_tasks(tasks_root)
    completed_ids = {t["id"] for t in tasks if t.get("status") == "completed"}

    # 优先找已在 in_progress 的任务
    for t in tasks:
        if t.get("status") == "in_progress":
            return t

    # 寻找首个依赖全部满足的 todo 任务
    for t in tasks:
        if t.get("status") == "todo":
            deps = t.get("depends_on") or []
            if all(d in completed_ids for d in deps):
                return t
    return None


def _as_list(value) -> list[str]:
    """路径 / 域字段既可能是 list 也可能是单个字符串；空值归一为空列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v) for v in value if str(v).strip()]


def assemble_curated_context(root: Path, task: dict,
                             scope_paths: list[str] | None = None) -> str:
    """组装当前任务的最小上下文注入包。

    `scope_paths` = 本次改动文件/目录；缺省回落到任务卡的 `paths` 字段。
    只注入命中 `paths:` 的规范（最多 3 份），不注入全仓无关 spec。
    """
    root = root.resolve()
    t_id = task["id"]
    t_dir = Path(task.get("_dir") or (root / ".atlas" / "tasks" / t_id))
    # 显式 `--paths`（含空串）与「任务卡没有路径」要区分：前者不回落兜底，
    # 后者才允许走 `**` 导航兜底。
    if scope_paths is not None:
        scopes: list[str] | None = _as_list(scope_paths)
    else:
        scopes = _as_list(task.get("paths")) or None

    lines = [
        f"# 任务派发执行单 (Task Dispatch) — {task.get('title')}",
        "",
        f"**任务编号**：`{t_id}`",
        f"**状态**：`in_progress`",
        "",
        "## 1. 任务需求 (Task PRD)",
    ]

    prd_file = t_dir / "prd.md"
    if prd_file.is_file():
        lines.append(prd_file.read_text(encoding="utf-8").strip())
    else:
        lines.append(f"需求卡路径：`{prd_file.relative_to(root)}`（文件未找到）")

    lines.extend([
        "",
        "## 2. 权威验收标准 (AC Scope)",
    ])
    acs = task.get("acs") or []
    if acs:
        for ac in acs:
            lines.append(f"- **`{ac}`**：请严格对照此验收项实现业务逻辑")
    else:
        lines.append("- （无直接关联的业务 AC，遵循常规代码规范及单元测试）")

    # 关联受影响域 PRD 指针
    domains = _as_list(task.get("affected_domains"))
    lines.extend([
        "",
        "## 3. 受影响域架构透镜 (Domain Focus)",
    ])
    if domains:
        for d in domains:
            domain_prd = root / "product" / "prd" / f"{d}-prd.md"
            if domain_prd.is_file():
                lines.append(f"- 业务域 `{d}` PRD 索引：`{domain_prd.relative_to(root)}`")
            else:
                lines.append(f"- 业务域 `{d}`")
    else:
        lines.append("- 通用基础设施 / 跨域")

    # 最小结构上下文：按改动路径 / 受影响域自动注入
    spec_set = select_specs(root, paths=scopes, domains=domains)
    lines.extend([
        "",
        render_specs(spec_set, scope_paths=scopes, domains=domains),
    ])

    lines.extend([
        "",
        "## 5. 执行规范与完成定义 (Instructions for Agent)",
        "1. 请依据上述需求卡与 AC 断言完成代码修改；",
        "2. 修改完成后，请执行 `git add <改动文件>` 暂存修改；",
        "3. 运行暂存区独立审查与测试：",
        f"   ```bash",
        f"   atlas review --unit {t_id} --staged",
        f"   # 或: python3 scripts/atlas_review.py --unit {t_id} --staged",
        f"   ```",
        "4. 审查通过并生成 `review.json` 证明后，方可进行提交或进入下一任务。",
        "",
    ])
    return "\n".join(lines)


def dispatch_task(root: Path, task: dict, scope_paths: list[str] | None = None) -> Path:
    """执行派单流转：写入 dispatch.md 并将状态置为 in_progress。"""
    root = root.resolve()
    t_id = task["id"]
    t_dir = Path(task.get("_dir") or (root / ".atlas" / "tasks" / t_id))
    t_dir.mkdir(parents=True, exist_ok=True)

    # 写入上下文派单包
    ctx_text = assemble_curated_context(root, task, scope_paths=scope_paths)
    dispatch_file = t_dir / "dispatch.md"
    dispatch_file.write_text(ctx_text, encoding="utf-8")

    # 更新 task.json 状态
    task_json_file = t_dir / "task.json"
    if task_json_file.is_file():
        try:
            meta = json.loads(task_json_file.read_text(encoding="utf-8"))
        except Exception:
            meta = task
    else:
        meta = task

    meta["status"] = "in_progress"
    task_json_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return dispatch_file
