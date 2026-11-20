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
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from _support import review_scope_core as scope_core
from _support.layout import LayoutError, load_layout
from _support.siblings import load_module
from _support.workflow_plan import ARCHIVE_DIR, load_tasks, atomic_write_json, UNIT_RE


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


def _acceptance_evidence(lay) -> dict:
    """用户验收走查留痕：`<e2e>/reviews/*-acceptance-*/README.md`（缺 ⇒ SKIP，人工责任）。"""
    reviews = lay.e2e_reviews_dir
    if not reviews.is_dir():
        return {"status": "SKIP", "reason": "无 E2E 验收走查留痕目录（人工责任）"}
    docs = sorted(p for p in reviews.glob("*-acceptance-*")
                  if p.is_dir() and (p / "README.md").is_file())
    if not docs:
        return {"status": "SKIP", "reason": "未见 *-acceptance-*/README.md（用户验收走查为人工责任）"}
    latest = docs[-1]
    return {"status": "PASS", "path": str(latest.relative_to(lay.root)),
            "reason": "找到验收走查留痕"}


def check_e2e_precondition(root: Path, task: dict) -> dict:
    """收口前把 E2E 结论纳入校验输入（issue #69）。

    - 与本任务 AC 关联的用例存在 `red` ⇒ `FAIL`（阻断收口）；
    - 索引缺失 / 任务卡无 AC / 本任务 AC 未出现在索引 / 含 `skipped` ⇒ `SKIP`（显式记录原因，
      不静默当作通过）；
    - 其余（`green` / `blocked` 带原因）⇒ `PASS`。
    验收走查留痕单独记录，不改变 E2E 结论（缺留痕 = `SKIP`，人工责任）。
    """
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        return {"status": "SKIP", "reason": f"布局不可解析：{exc}"}
    index = lay.e2e_index
    if not index.is_file():
        return {"status": "SKIP", "reason": f"未找到 E2E 索引（{index.relative_to(root)}）：按人工责任处理"}
    try:
        mod = load_module("validate_e2e_index")
        tabs = mod.tables(index.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 —— 坏索引不能把收口判红，但必须显式 SKIP
        return {"status": "SKIP", "reason": f"E2E 索引不可解析：{exc}"}
    if not tabs:
        return {"status": "SKIP", "reason": "E2E 索引无可解析表格"}
    matched = next(((h, r) for h, r in tabs if h == mod.MAIN_COLUMNS), None)
    if matched is None:
        return {"status": "SKIP",
                "reason": f"E2E 主表列头不可识别（期望 {mod.MAIN_COLUMNS}）"}
    header, rows = matched
    grid = [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in rows]
    acs = [str(a) for a in (task.get("acs") or []) if str(a).strip()]
    if not acs:
        return {"status": "SKIP", "reason": "任务卡未声明 AC，无法定位 E2E 适用面", "acs": []}
    scoped = [g for g in grid if any(a in (g.get("关联AC") or "") for a in acs)]
    if not scoped:
        return {"status": "SKIP", "reason": f"本任务 AC 未出现在 E2E 索引：{acs}", "acs": acs}
    counts = dict(Counter((g.get("状态") or "") for g in scoped))
    cases = [g.get("用例ID") or "?" for g in scoped]
    red = [cid for cid, g in zip(cases, scoped) if (g.get("状态") or "") == "red"]
    skipped = [cid for cid, g in zip(cases, scoped) if (g.get("状态") or "") == "skipped"]
    out = {"acs": acs, "cases": cases, "counts": counts,
           "acceptance": _acceptance_evidence(lay)}
    if red:
        out.update(status="FAIL", reason=f"E2E 关联用例存在 red：{red}")
    elif skipped:
        out.update(status="SKIP", reason=f"E2E 关联用例含 skipped（不得当通过）：{skipped}")
    else:
        out.update(status="PASS", reason=f"E2E 关联用例无 red（{counts}）")
    return out


def archive_task(root: Path, tasks_root: Path, t_dir: Path, t_id: str) -> dict:
    """把已收口任务移到 `.atlas/tasks/archive/<id>/`（幂等；失败显式报错，issue #70）。"""
    if not UNIT_RE.match(t_id):
        raise FinishError(f"非法任务标识：{t_id!r}")
    dest = tasks_root / ARCHIVE_DIR / t_id
    if t_dir == dest:
        return {"status": "already", "path": str(dest.relative_to(root))}
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(t_dir), str(dest))
    except OSError as exc:
        raise FinishError(f"归档失败：{t_dir} → {dest}（{exc}）") from exc
    return {"status": "moved", "path": str(dest.relative_to(root))}


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
    archive_dest = tasks_root / ARCHIVE_DIR / t_id
    if t_dir != archive_dest and archive_dest.exists():
        raise FinishError(f"归档目标已存在：{archive_dest}（源目录仍在 {t_dir}；请人工核对后处理）")
    if not force:
        passed, reason = check_task_review_passed(root, t_id)
        if not passed:
            raise FinishError(f"任务 {t_id} 无法收口：{reason}")

    e2e = check_e2e_precondition(root, task)
    if e2e["status"] == "FAIL":
        raise FinishError(f"任务 {t_id} 无法收口：{e2e['reason']}")

    # 更新 task.json 状态为 completed（E2E 前置结论一并落盘，issue #69）
    task_json_file = t_dir / "task.json"
    if task_json_file.is_file():
        try:
            meta = json.loads(task_json_file.read_text(encoding="utf-8"))
        except Exception:
            meta = task
    else:
        meta = task

    meta["status"] = "completed"
    meta["e2e_precondition"] = e2e
    atomic_write_json(task_json_file, meta)

    # 归档（issue #70）：completed 任务移出活跃区；幂等，失败显式报错
    archived = archive_task(root, tasks_root, t_dir, t_id)

    # 检查整体工作流是否全部收工（含归档任务）
    all_tasks = load_tasks(tasks_root, include_archived=True)
    total = len(all_tasks)
    completed_count = sum(1 for t in all_tasks if t.get("status") == "completed")

    return {
        "unit": t_id,
        "status": "completed",
        "total_tasks": total,
        "completed_tasks": completed_count,
        "all_done": (total > 0 and completed_count == total),
        "e2e_precondition": e2e,
        "archived": archived,
    }
