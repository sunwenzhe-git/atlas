#!/usr/bin/env python3
"""Atlas Workflow —— 自建全流程执行层调度总入口 (RFC-20261119-02 / D204)。

整合完整生命周期：
  Plan（大任务自动拆解）→ Dispatch（最小上下文分发）→ Verify（暂存区自动审查与测试并轨）→ Finish（收口归档）

用法：
  atlas workflow plan --unit <ID> [--requirement <TEXT_OR_FILE>]
  atlas workflow dispatch [--unit <ID>]
  atlas workflow verify --unit <ID> [--staged] [--check-cmd <CMD>]
  atlas workflow finish --unit <ID>
  atlas workflow status [--unit <ID>] [--all]
  atlas workflow archive [--unit <ID>]
  atlas workflow run --unit <ID> [--requirement <TEXT_OR_FILE>] [--check-cmd <CMD>]

退出码：0 成功；1 门禁未通过/失败；2 参数错误/输入缺失。纯标准库。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from _support.workflow_plan import (  # noqa: E402
    decompose_requirement, write_task_card, load_tasks, PlanError,
    REQUIREMENT_ITEMS_FILE
)
from _support.workflow_verify import coverage_matrix_findings  # noqa: E402
from _support.workflow_dispatch import (  # noqa: E402
    get_next_runnable_task, dispatch_task, DispatchError
)
from _support.workflow_finish import (  # noqa: E402
    finish_task, check_task_review_passed, FinishError, archive_task, archive_month
)
from _support.workflow_context import select_specs, render_specs  # noqa: E402


def die(msg: str, code: int = 2) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def _tasks_root(root: Path) -> Path:
    """Atlas 自有任务账本（`.atlas/tasks`）。"""
    return root / ".atlas" / "tasks"


def _read_tasks_root(root: Path) -> Path:
    """任务账本读取面 = `.atlas/tasks`（唯一落点）。"""
    return _tasks_root(root)


def _prune_orphan_cards(tasks_dir: Path, unit: str, keep: set[str]) -> None:
    """重跑 plan 后清理本轮不再生成的 todo 孤儿子卡（已派发/已完成不动）。"""
    pat = re.compile(rf"^{re.escape(unit)}-\d+$")
    if not tasks_dir.is_dir():
        return
    for d in sorted(tasks_dir.iterdir()):
        if not (d.is_dir() and pat.match(d.name) and d.name not in keep):
            continue
        status = "todo"
        task_json = d / "task.json"
        if task_json.is_file():
            try:
                status = str(json.loads(task_json.read_text(encoding="utf-8"))
                             .get("status") or "todo")
            except (OSError, json.JSONDecodeError):
                continue
        if status != "todo" or (d / "dispatch.md").exists():
            continue
        shutil.rmtree(d)
        print(f"  清理孤儿任务卡：{d.name}（本轮拆解已不再生成）")


def cmd_plan(args: argparse.Namespace, root: Path) -> int:
    req_text = ""
    if args.requirement:
        p = Path(args.requirement)
        if not p.is_absolute():
            p = root / p
        if p.is_file():
            req_text = p.read_text(encoding="utf-8")
        else:
            req_text = args.requirement
    else:
        req_text = f"需求工作单元 {args.unit}"

    try:
        tasks = decompose_requirement(root, req_text, args.unit)
    except PlanError as exc:
        return die(str(exc))

    tasks_dir = _tasks_root(root)
    created: list[dict] = []
    for t in tasks:
        paths = [str(p) for p in (getattr(args, "paths", None) or []) if str(p).strip()]
        if paths:
            t["paths"] = paths
        t_dir = tasks_dir / t["id"]
        if not args.dry_run:
            # plan 显式给过 --requirement ⇒ 需求驱动卡：同步写条目表 + 覆盖矩阵骨架
            # （#72/#73 开工前置产物；重跑不覆盖已填内容）。
            write_task_card(t_dir, t, with_requirement_items=bool(args.requirement))
        created.append({"id": t["id"], "title": t["title"], "dir": str(t_dir.relative_to(root))})

    if not args.dry_run:
        _prune_orphan_cards(tasks_dir, args.unit, {t["id"] for t in created})

    if args.json:
        print(json.dumps({"status": "ok", "unit": args.unit, "tasks": created},
                         ensure_ascii=False, indent=2))
    else:
        print(f"atlas workflow plan @ {args.unit}   生成 {len(created)} 个工作单元：")
        for item in created:
            print(f"  - [{item['id']}] {item['title']} -> {item['dir']}")
    return 0


def cmd_dispatch(args: argparse.Namespace, root: Path) -> int:
    tasks_dir = _read_tasks_root(root)
    # 显式 --unit 时连归档一起查：已 completed 的任务要给出「已完成」而不是「未找到」。
    all_tasks = load_tasks(tasks_dir, include_archived=bool(args.unit))
    if not all_tasks:
        return die(f"未找到任何任务卡（可在 {tasks_dir} 先运行 atlas workflow plan）")

    target_task = None
    if args.unit:
        target_task = next((t for t in all_tasks if t["id"] == args.unit), None)
        if not target_task:
            # plan 把大任务拆成 <unit>-NN 时，允许按组派发：取组内首个 in_progress，
            # 否则取首个依赖已满足的 todo。
            group = sorted((t for t in all_tasks if t["id"].startswith(f"{args.unit}-")),
                           key=lambda t: t["id"])
            completed_ids = {t["id"] for t in all_tasks if t.get("status") == "completed"}
            target_task = next((t for t in group if t.get("status") == "in_progress"), None)
            if not target_task:
                target_task = next(
                    (t for t in group
                     if t.get("status") == "todo"
                     and all(d in completed_ids for d in (t.get("depends_on") or []))),
                    None)
        if not target_task:
            return die(f"未找到指定任务 {args.unit}（或其可执行子任务）")
        status = target_task.get("status", "todo")
        if status == "completed":
            return die(f"任务 {target_task['id']} 已 completed，不能重复派发")
        if status not in ("todo", "in_progress"):
            return die(f"任务 {target_task['id']} 状态为 {status}，不可派发")
        completed_ids = {t["id"] for t in all_tasks if t.get("status") == "completed"}
        missing = [d for d in (target_task.get("depends_on") or []) if d not in completed_ids]
        if missing:
            return die(f"任务 {target_task['id']} 的前置依赖未完成：{', '.join(missing)}")
    else:
        target_task = get_next_runnable_task(tasks_dir)
        if not target_task:
            print("所有任务已完成或前置依赖未满足，无可分发任务。")
            return 0

    if args.dry_run:
        print(f"$ # 将为任务 {target_task['id']} 组装最小上下文并生成 dispatch.md (dry-run)")
        return 0

    try:
        disp_file = dispatch_task(root, target_task, scope_paths=getattr(args, "paths", None))
    except DispatchError as exc:
        return die(str(exc))

    if args.json:
        print(json.dumps({"status": "ok", "unit": target_task["id"], "dispatch": str(disp_file)},
                         ensure_ascii=False, indent=2))
    else:
        print(f"atlas workflow dispatch @ {target_task['id']} [in_progress]")
        print(f"  派工单就绪：{disp_file.relative_to(root)}")
        print(f"  请依据派工单实现代码，完成后暂存并运行 `atlas workflow verify --unit {target_task['id']}`")
        if (Path(disp_file).parent / REQUIREMENT_ITEMS_FILE).is_file():
            print("  开工前：填 requirement-items.md（条目表逐条枚举，#72）；"
                  "verify 前补全 coverage-matrix.md 四列覆盖（#73，空格/UNRESOLVED ⇒ WARN）")
    return 0


def cmd_context(args: argparse.Namespace, root: Path) -> int:
    """只读查询：按文件路径打印命中的结构规范，不写盘、不改状态。"""
    scope = [str(p) for p in (args.paths or []) if str(p).strip()]
    domains: list[str] = []

    if not scope:
        if not args.unit:
            return die("至少提供 --paths 或 --unit")
        tasks_dir = _read_tasks_root(root)
        task = next((t for t in load_tasks(tasks_dir) if t["id"] == args.unit), None)
        if not task:
            return die(f"未找到任务卡 {args.unit}")
        if isinstance(task.get("paths"), list):
            scope = [str(p) for p in task["paths"] if str(p).strip()]
        raw_domains = task.get("affected_domains")
        if isinstance(raw_domains, str):
            raw_domains = [raw_domains]
        domains = [str(d) for d in (raw_domains or []) if str(d).strip()]

    specs = select_specs(root, paths=scope or None, domains=domains)

    if args.json:
        print(json.dumps({
            "paths": scope,
            "specs": [{"rel": s["rel"], "paths": s["paths"]} for s in specs],
        }, ensure_ascii=False, indent=2))
        return 0

    print("只读预览：未写盘、未改状态；正式开工请用 `atlas workflow dispatch`。")
    print()
    print(render_specs(specs, scope_paths=scope, domains=domains))
    return 0


def _next_review_round(root: Path, unit: str) -> int:
    """同 (unit, round) 的 findings 不得覆盖（骨架 §4）：按已有轮次自动递增。"""
    findings = (root / "product" / "reviews"
                / f"{date.today().isoformat()}-impl-review-{unit}" / "findings")
    rounds: list[int] = []
    if findings.is_dir():
        pat = re.compile(rf"{re.escape(unit)}\.r(\d+)\.json")
        for p in findings.iterdir():
            m = pat.fullmatch(p.name)
            if m:
                rounds.append(int(m.group(1)))
    return max(rounds) + 1 if rounds else 1


def cmd_verify(args: argparse.Namespace, root: Path) -> int:
    if not args.unit:
        return die("verify 步骤必须指定 --unit <ID>")

    review_script = HERE / "atlas_review.py"
    if not args.dry_run and not _has_staged_changes(root):
        return die("暂存区为空：请先实现并 `git add`，再运行 verify", code=2)
    round_no = getattr(args, "round", None) or _next_review_round(root, args.unit)
    cmd = [
        sys.executable, str(review_script),
        "--root", str(root),
        "--unit", args.unit,
        "--staged",
        "--round", str(round_no),
    ]
    if args.check_cmd:
        cmd.extend(["--check-cmd", args.check_cmd])
    if getattr(args, "resolves", None):
        cmd.extend(["--resolves", args.resolves])
    if args.dry_run:
        cmd.append("--dry-run")

    if not args.json:
        print(f"atlas workflow verify @ {args.unit} 启动独立质检管线（round {round_no}）...")
    pr = subprocess.run(cmd, text=True)
    # 需求条目覆盖对账（#71/#72/#73，纪律面 WARN 起步）：独立审查通过后对账，
    # 缺口打到 stderr、不改退出码（升格 FAIL 另案）。
    if pr.returncode == 0 and not args.dry_run:
        for finding in coverage_matrix_findings(_read_tasks_root(root) / args.unit):
            print(f"WARN（需求条目覆盖）: {finding}", file=sys.stderr)
    # 本命令的退出码契约 = 0/1/2；子步的原生码（如 7）归一到 1。
    return pr.returncode if pr.returncode in (0, 1, 2) else 1


def cmd_finish(args: argparse.Namespace, root: Path) -> int:
    if not args.unit:
        return die("finish 步骤必须指定 --unit <ID>")

    tasks_dir = _read_tasks_root(root)
    all_tasks = load_tasks(tasks_dir, include_archived=True)
    target_task = next((t for t in all_tasks if t["id"] == args.unit), None)
    if not target_task:
        return die(f"未找到任务卡 {args.unit}（不能对账本外任务收口）", code=2)

    if args.dry_run:
        print(f"$ # 校验 {args.unit} 的 review.json + E2E 前置，流转 completed 并归档 (dry-run)")
        return 0

    try:
        res = finish_task(root, target_task, force=args.force)
    except FinishError as exc:
        return die(str(exc), code=1)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"atlas workflow finish @ {args.unit}   status: completed")
        e2e = res.get("e2e_precondition") or {}
        print(f"  E2E 前置：{e2e.get('status', '?')} —— {e2e.get('reason', '')}")
        acceptance = e2e.get("acceptance") or {}
        if acceptance:
            print(f"  验收走查：{acceptance.get('status', '?')} —— {acceptance.get('reason', '')}")
        arch = res.get("archived") or {}
        if arch:
            print(f"  归档：{arch.get('status')} -> {arch.get('path')}")
        print(f"  进度：{res['completed_tasks']}/{res['total_tasks']} 已完成")
        if res.get("all_done"):
            print("  ★ 全部工作单元已顺利完成收口！")
    return 0


def cmd_archive(args: argparse.Namespace, root: Path) -> int:
    """把已 completed 的任务迁入 `.atlas/tasks/archive/<YYYY-MM>/`（幂等，issue #70）。

    除活跃任务外，历史扁平存档（`archive/<id>/`）或缺/错月份层的目录也视为待归档，
    迁入当月以恢复判据与封条的扫描面。
    """
    tasks_dir = _read_tasks_root(root)
    all_tasks = load_tasks(tasks_dir, include_archived=True)
    if args.unit:
        targets = [t for t in all_tasks if t["id"] == args.unit]
        if not targets:
            return die(f"未找到任务卡 {args.unit}", code=2)
    else:
        targets = all_tasks
    pending = [t for t in targets
               if archive_month(Path(t["_dir"]), tasks_dir) is None]
    if args.dry_run:
        print(f"$ # 归档 {len(pending)} 项到 {tasks_dir / 'archive'}/{date.today():%Y-%m}"
              "（dry-run 不移动）")
        return 0
    if args.unit and pending and pending[0].get("status") != "completed":
        return die(f"任务 {args.unit} 尚未 completed，不能归档", code=1)
    if not pending:
        print("无待归档项（目标任务已归档或无可归档任务）")
        return 0
    moved: list[dict] = []
    for t in pending:
        if t.get("status") != "completed":
            print(f"跳过 {t['id']}：status={t.get('status')}（只归档 completed）")
            continue
        try:
            info = archive_task(root, tasks_dir, Path(t["_dir"]), t["id"])
        except FinishError as exc:
            return die(str(exc), code=1)
        moved.append({"id": t["id"], **info})
    if args.json:
        print(json.dumps({"archived": moved}, ensure_ascii=False, indent=2))
    else:
        print(f"atlas workflow archive   归档 {len(moved)} 项：")
        for item in moved:
            print(f"  - [{item['id']}] {item['status']} -> {item['path']}")
    return 0


def cmd_status(args: argparse.Namespace, root: Path) -> int:
    tasks_dir = _read_tasks_root(root)
    all_tasks = load_tasks(tasks_dir, include_archived=getattr(args, "all", False))
    if args.unit:
        all_tasks = [t for t in all_tasks
                     if t["id"] == args.unit or t["id"].startswith(f"{args.unit}-")]
    if not all_tasks:
        print(f"当前无工作流任务卡（目录：{tasks_dir}）")
        return 0

    if args.json:
        print(json.dumps({"tasks": all_tasks}, ensure_ascii=False, indent=2))
        return 0

    print(f"atlas workflow 任务台账（共 {len(all_tasks)} 项）：")
    for t in all_tasks:
        stat = t.get("status", "unknown")
        icon = "✓" if stat == "completed" else ("▶" if stat == "in_progress" else "○")
        suffix = " [archived]" if t.get("_archived") else ""
        print(f"  {icon} [{t['id']}] {t.get('title')} ({stat}){suffix}")
        if t.get("acs"):
            print(f"      ACs: {', '.join(t['acs'])}")
    return 0


def _has_staged_changes(root: Path) -> bool:
    try:
        pr = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=str(root),
                            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return pr.returncode == 0 and bool(pr.stdout.strip())


def _with_unit(args: argparse.Namespace, unit: str) -> argparse.Namespace:
    ns = argparse.Namespace(**vars(args))
    ns.unit = unit
    return ns


def cmd_run(args: argparse.Namespace, root: Path) -> int:
    """跑通闭环：Plan -> Dispatch -> Verify -> Finish。

    前置：实现已按派工单完成并 `git add` 暂存（Atlas 不写业务实现）。
    暂存区为空时停在 Dispatch 之后，给出下一步指令并返回 2。
    """
    if args.dry_run:
        print("$ # run dry-run：plan → dispatch → verify → finish（不写盘、不改状态）")
        return 0
    print(f"=== [1/4] 执行 Plan 规划阶段 ===")
    rc = cmd_plan(args, root)
    if rc != 0:
        return rc

    print(f"\n=== [2/4] 执行 Dispatch 分发派单 ===")
    rc = cmd_dispatch(args, root)
    if rc != 0:
        return rc

    # plan 可能把大任务拆成 <unit>-NN：Verify/Finish 必须落到实际被派发的那个任务卡上
    tasks_dir = _read_tasks_root(root)
    group = [t for t in load_tasks(tasks_dir)
             if t["id"] == args.unit or t["id"].startswith(f"{args.unit}-")]
    active = next((t for t in group if t.get("status") == "in_progress"), None)
    run_unit = active["id"] if active else args.unit

    if not _has_staged_changes(root):
        print(f"\n=== [3/4] Verify 暂不执行：暂存区为空 ===")
        print(f"  派工单：.atlas/tasks/{run_unit}/dispatch.md")
        print(f"  请实现并 `git add` 后重跑 `atlas workflow run --unit {args.unit}`"
              f"（或 `atlas workflow verify --unit {run_unit}`）")
        return 2

    print(f"\n=== [3/4] 执行 Verify 独立审查验收 ===")
    rc = cmd_verify(_with_unit(args, run_unit), root)
    if rc != 0:
        print(f"Verify 未通过，工作流终止在当前单元。修复后可重试 verify。")
        return rc

    print(f"\n=== [4/4] 执行 Finish 确认收口 ===")
    return cmd_finish(_with_unit(args, run_unit), root)


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS, help="项目根目录（缺省当前目录）")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON 格式结果")
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS, help="干跑演练，不写真实产物")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="项目根目录（缺省当前目录）")
    ap.add_argument("--json", action="store_true", default=False, help="输出 JSON 格式结果")
    ap.add_argument("--dry-run", action="store_true", default=False, help="干跑演练，不写真实产物")

    sub = ap.add_subparsers(dest="subcommand", required=True)

    # plan
    p_plan = sub.add_parser("plan", help="根据需求分解任务并生成任务卡 (Task Cards)", parents=[common])
    p_plan.add_argument("--unit", required=True, help="大任务标识")
    p_plan.add_argument("--requirement", help="需求说明文本或文件路径")
    p_plan.add_argument("--paths", nargs="+", default=None,
                        help="本次需求涉及的改动路径 glob（写入任务卡，派发时用于最小上下文注入）")

    # dispatch
    p_disp = sub.add_parser("dispatch", help="提取最小上下文并向执行侧分发任务", parents=[common])
    p_disp.add_argument("--unit", help="指定分发的任务标识（默认自动调度就绪任务）")
    p_disp.add_argument("--paths", nargs="+", default=None,
                        help="改动路径/目录（按 paths: 索引只注入命中的规范；缺省读任务卡）")

    # context
    p_ctx = sub.add_parser("context", parents=[common],
                           help="只读查询：按文件路径查看命中的结构规范（不写盘、不改状态）")
    p_ctx.add_argument("--paths", nargs="+", default=None, help="改动文件/目录（可多个）")
    p_ctx.add_argument("--unit", help="从任务卡取改动路径/受影响域（无 --paths 时生效）")

    p_ver = sub.add_parser("verify", help="对当前暂存区运行独立审查与测试并轨", parents=[common])
    p_ver.add_argument("--unit", required=True, help="被检验的任务标识")
    p_ver.add_argument("--staged", action="store_true", default=True, help="审查暂存区（默认开启）")
    p_ver.add_argument("--check-cmd", help="执行确定性测试命令（如 pytest/npm test）")
    p_ver.add_argument("--round", type=int, help="审查轮次（缺省按已有 findings 自动递增）")
    p_ver.add_argument("--resolves", help="跨轮关闭声明文件（上一轮 findings 的处置）")

    # finish
    p_fin = sub.add_parser("finish", help="检验审查证明并收口任务", parents=[common])
    p_fin.add_argument("--unit", required=True, help="收口的任务标识")
    p_fin.add_argument("--force", action="store_true", help="强制收口（跳过 review.json 存在性检查）")

    # status
    p_stat = sub.add_parser("status", help="查看当前所有任务流转状态", parents=[common])
    p_stat.add_argument("--unit", help="查看指定任务")
    p_stat.add_argument("--all", action="store_true",
                        help="包含 .atlas/tasks/archive/<YYYY-MM>/ 中已归档的任务")

    # archive
    p_arc = sub.add_parser("archive", parents=[common],
                           help="把已 completed 的活跃任务迁入 .atlas/tasks/archive/<YYYY-MM>/"
                                "（幂等一次性迁移）")
    p_arc.add_argument("--unit", help="只归档指定任务（缺省归档全部 completed）")

    # run (一键全流程)
    p_run = sub.add_parser("run", help="串联闭环（Plan -> Dispatch -> Verify -> Finish；需先按派工单实现并暂存）", parents=[common])
    p_run.add_argument("--unit", required=True, help="大任务标识")
    p_run.add_argument("--requirement", help="需求说明文本或文件路径")
    p_run.add_argument("--paths", nargs="+", default=None,
                       help="改动路径/目录（plan 写入任务卡，dispatch 时用于最小注入）")
    p_run.add_argument("--check-cmd", help="确定性检查命令")
    p_run.add_argument("--round", type=int, help="审查轮次（缺省自动递增）")
    p_run.add_argument("--resolves", help="跨轮关闭声明文件")
    p_run.add_argument("--force", action="store_true", help="允许无报告强制收口（测试用）")

    args = ap.parse_args()
    root = Path(args.root).resolve()

    dispatch_map = {
        "plan": cmd_plan,
        "dispatch": cmd_dispatch,
        "context": cmd_context,
        "verify": cmd_verify,
        "finish": cmd_finish,
        "status": cmd_status,
        "archive": cmd_archive,
        "run": cmd_run,
    }
    handler = dispatch_map.get(args.subcommand)
    if not handler:
        return die(f"未知子命令：{args.subcommand}")
    try:
        return handler(args, root)
    except PlanError as exc:
        return die(str(exc))


if __name__ == "__main__":
    sys.exit(main())
