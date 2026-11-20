#!/usr/bin/env python3
"""Atlas Workflow Finish —— 收口校验与账本流转引擎 (Phase Finish)。

职责：
1. 校验当前任务是否已通过独立审查（检查对应任务目录下或 reviews/ 下的 `review.json` 证明）；
2. 校验确定性测试/门禁是否全绿，无未解决的 Critical/Major findings；
3. 将任务状态原子流转至 `completed`；
4. 检查 DAG 中全部任务：若所有工作单元均已 completed，执行全局收口归档。

纯标准库实现。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from _support import review_scope_core as scope_core
from _support.workflow_plan import load_tasks, atomic_write_json, UNIT_RE


class FinishError(ValueError):
    """收口校验异常。"""


REVIEW_DIR_PREFIX_RE = r"^\d{4}-\d{2}-\d{2}-impl-review-"


def _staged_files(root: Path) -> list[str] | None:
    try:
        pr = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=str(root), capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if pr.returncode != 0:
        return None
    return [line.strip() for line in pr.stdout.splitlines() if line.strip()]


def _scope_matches(root: Path, data: dict) -> tuple[bool, str]:
    """检查报告落盘后暂存区内容未被替换（v4 内容封口）。"""
    scope = data.get("review_scope")
    if not isinstance(scope, dict) or not scope.get("sha256"):
        return True, ""  # 旧报告兼容：无内容锚，无法比对
    staged = _staged_files(root)
    if staged is None:
        return False, "无法读取暂存区，不能确认审查内容未被替换（请在 git 仓库内重跑 verify）"
    try:
        manifest = scope_core.build_manifest(root, staged)
    except Exception as exc:  # noqa: BLE001 —— 路径/状态异常一律视为不可封口
        return False, f"暂存区内容无法重算摘要：{exc}"
    if manifest.get("scope_sha256") != scope.get("sha256"):
        return False, "审查后暂存区内容已变化（review_scope 摘要不一致）；请重新运行 verify"
    return True, ""


def check_task_review_passed(root: Path, unit: str) -> tuple[bool, str]:
    """检查指定任务是否已产出合规的 review.json 且未被拦截。"""
    root = root.resolve()
    # 查找匹配的 review 报告目录
    reviews_dir = root / "product" / "reviews"
    if not reviews_dir.is_dir():
        return False, "未找到 product/reviews 目录（尚未执行独立审查）"

    candidates = sorted(
        p for p in reviews_dir.iterdir()
        if p.is_dir() and re.fullmatch(
            REVIEW_DIR_PREFIX_RE + re.escape(unit) + "$", p.name)
    )
    if not candidates:
        return False, f"未找到任务 {unit} 的审查报告（须先执行 atlas review --unit {unit} --staged）"

    latest_dir = candidates[-1]
    review_file = latest_dir / "review.json"
    if not review_file.is_file():
        return False, f"报告目录 {latest_dir.name} 缺少 review.json"

    try:
        data = json.loads(review_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"读取 {review_file} 失败：{exc}"

    # 检查 review.json 是否合规且无阻塞项。字段口径以 cli_review_convert 的实际产出为准：
    # `status ∈ {PASS, WARN, FAIL}` + `ok` —— PASS 已由 `review_policy.calculate_status` 保证
    # 「无阻断 Critical、无 Major、无 M≠N 等下限」，此处不重复实现严重度判定（判据单源）。
    status = str(data.get("status") or "").strip().upper()
    if status != "PASS":
        return False, f"审查报告状态未通过（status: {data.get('status')}；收口需 PASS，WARN/FAIL 均阻断）"
    if data.get("ok") is False:
        return False, "审查报告 ok=false（存在未解决的阻断问题）"

    matched, why = _scope_matches(root, data)
    if not matched:
        return False, why

    return True, str(latest_dir)


def finish_task(root: Path, task: dict, *, force: bool = False) -> dict:
    """完成单个任务的收口流转。"""
    root = root.resolve()
    t_id = task["id"]
    if not UNIT_RE.match(t_id):
        raise FinishError(f"非法任务标识：{t_id!r}")
    tasks_root = (root / ".atlas" / "tasks").resolve()
    t_dir = Path(task.get("_dir") or (tasks_root / t_id)).resolve()
    if t_dir != tasks_root and tasks_root not in t_dir.parents:
        raise FinishError(f"任务目录越界：{t_dir}（必须在 {tasks_root} 之内）")

    if not t_dir.is_dir():
        raise FinishError(f"任务目录不存在：{t_dir}")
    if not force:
        passed, reason = check_task_review_passed(root, t_id)
        if not passed:
            raise FinishError(f"任务 {t_id} 无法收口：{reason}")

    # 更新 task.json 状态为 completed
    task_json_file = t_dir / "task.json"
    if task_json_file.is_file():
        try:
            meta = json.loads(task_json_file.read_text(encoding="utf-8"))
        except Exception:
            meta = task
    else:
        meta = task

    meta["status"] = "completed"
    atomic_write_json(task_json_file, meta)

    # 检查整体工作流是否全部收工
    all_tasks = load_tasks(t_dir.parent)
    total = len(all_tasks)
    completed_count = sum(1 for t in all_tasks if t.get("status") == "completed")

    return {
        "unit": t_id,
        "status": "completed",
        "total_tasks": total,
        "completed_tasks": completed_count,
        "all_done": (total > 0 and completed_count == total),
    }
