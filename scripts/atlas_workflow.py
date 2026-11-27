#!/usr/bin/env python3
"""Atlas Workflow —— 自建全流程执行层调度总入口 (RFC-20261119-02 / D204)。

整合完整生命周期：
  Plan（大任务自动拆解）→ Dispatch（最小上下文分发）→ Verify（暂存区自动审查与测试并轨）→ Finish（收口归档）

用法：
  atlas workflow plan --unit <ID> [--requirement <TEXT_OR_FILE|需求落点>]
  atlas workflow dispatch [--unit <ID>]
  atlas workflow verify --unit <ID> [--staged] [--check-cmd <CMD>]
  atlas workflow finish --unit <ID>
  atlas workflow status [--unit <ID>] [--all]
  atlas workflow progress --unit <ID>   # 只读进度探针（RFC-20261122-02，不写盘不改状态）
  atlas workflow archive [--unit <ID>]
  atlas workflow run --unit <ID> [--requirement <TEXT_OR_FILE|需求落点>] [--check-cmd <CMD>]

退出码（封闭分配，RFC-20261122-07，单源 `_support/workflow_causes.py`）：
  0 成功；1 判定失败·门红（扣预算类）；2 用法错误/前置不满足/环境异常/流程顺序（不扣）；
  3 verify 尝试预算超限暂停（要求人工）；130=中断（SIGINT 信号死亡天然产生，
  无 die() 路径发出）。4–129 与 131+ 不分配。同一位点不同 cause 不同码：
  finish 的门红（review 未过/封口红/新鲜度/E2E red）⇒ 1，其 no_review_report/
  environment 类 ⇒ 2。纯标准库。
"""
# ATLAS_CHANGE_AUTO_V1
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from _support.layout import LayoutError, load_layout  # noqa: E402
from _support.bug_backflow import (  # noqa: E402
    CHANGE_TYPES, resolve_defect_root, strict_requirement_fields, validate_backflow,
)
from _support.workflow_plan import (  # noqa: E402
    decompose_requirement, write_task_card, load_tasks, PlanError,
    ARCHIVE_DIR, REQUIREMENT_ITEMS_FILE, REQUIREMENT_DOC_FILE, detect_requirement_root,
    requirement_pointer_text, requirement_relation_findings,
    logical_requirement_root_ref, resolve_requirement_root
)
from _support.workflow_verify import (  # noqa: E402
    coverage_matrix_findings, requirement_root_findings, read_requirement_status,
    mechanism_doc_findings, mechanism_dead_declare_findings,
    mechanism_declaration_verdict, discover_mechanism_docs
)
from _support.workflow_dispatch import (  # noqa: E402
    get_next_runnable_task, dispatch_task, DispatchError
)
from _support.workflow_finish import (  # noqa: E402
    finish_task, check_task_review_passed, FinishError, archive_task, archive_month,
    scan_review_rounds, deferred_open_count
)
from _support.workflow_receipt import create_workflow_origin
from _support.workflow_causes import (  # noqa: E402
    EXIT_BUDGET, EXIT_USAGE, FALLBACK_CAUSE, charged_count, exit_code_for, load_attempts,
    max_verify_attempts, record_attempt
)
from _support.workflow_context import select_specs, render_specs  # noqa: E402
from _support.workflow_progress import progress_snapshot, render_progress  # noqa: E402
from _support.guarded_continuation import WriteLock, WriteLockError  # noqa: E402


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
    req_root: Path | None = None
    req_rel: str | None = None
    if args.requirement:
        p = Path(args.requirement)
        if not p.is_absolute():
            p = root / p
        # 需求落点模式判定（RFC-20261122-03）：指向含 requirement.md 的目录或该文件本身；
        # 否则直填模式（旧行为逐字节不变）。
        req_root = detect_requirement_root(p, root)
        if req_root is not None:
            try:
                if resolve_requirement_root(root, req_root) is None:
                    return die(f"需求落点路径非法：{req_root}（须位于配置资产根的 requirements/<slug>/）")
                req_rel = logical_requirement_root_ref(root, req_root)
                req_text = (req_root / REQUIREMENT_DOC_FILE).read_text(encoding="utf-8")
                # 确认门软校验（纪律面 WARN，不拦停；状态机：候选→已确认→已拆→已收口）
                status = read_requirement_status(req_root)
                relation_findings = requirement_relation_findings(root, req_root)
            except (LayoutError, OSError) as exc:
                return die(f"需求落点不可读或布局非法：{exc}")
            if status is None:
                print("WARN（需求落点）: requirement.md 缺「**状态**：」状态行——确认门未留痕"
                      "（RFC-20261122-03）", file=sys.stderr)
            elif status == "候选":
                print("WARN（需求落点）: 落点状态 = 候选（未确认先拆）——先过确认门再拆卡",
                      file=sys.stderr)
            for finding in relation_findings:
                print(f"WARN（需求落点）: {finding}", file=sys.stderr)
        elif p.is_file():
            req_text = p.read_text(encoding="utf-8")
        else:
            ref_text = str(args.requirement).strip()
            try:
                assets_rel = load_layout(root).assets_root.resolve().relative_to(
                    root.resolve()).as_posix()
                requirement_prefix = f"{assets_rel}/requirements/"
            except (LayoutError, ValueError):
                requirement_prefix = "product/requirements/"
            path_like = (Path(ref_text).is_absolute()
                         or ref_text.startswith("requirements/")
                         or ref_text.startswith(requirement_prefix))
            if path_like:
                return die(f"需求落点引用无法解析：{args.requirement}")
            req_text = args.requirement
    else:
        req_text = f"需求工作单元 {args.unit}"

    try:
        tasks = decompose_requirement(root, req_text, args.unit)
    except PlanError as exc:
        return die(str(exc))

    tasks_dir = _tasks_root(root)
    try:
        existing_tasks = load_tasks(tasks_dir, include_archived=True)
        reserved_archive_ids = {
            t["id"] for t in existing_tasks
            if ARCHIVE_DIR in Path(t["_dir"]).relative_to(tasks_dir).parts
        }
    except PlanError as exc:
        return die(str(exc))
    archive_dir = tasks_dir / ARCHIVE_DIR
    if archive_dir.is_dir():
        for child in archive_dir.iterdir():
            if not child.is_dir():
                continue
            if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", child.name):
                reserved_archive_ids.update(
                    grandchild.name for grandchild in child.iterdir()
                    if grandchild.is_dir())
            else:
                reserved_archive_ids.add(child.name)
    for t in tasks:
        if t["id"] in reserved_archive_ids:
            return die(f"任务 ID {t['id']} 已存在于归档命名空间，禁止重建同 ID 活跃卡")
    created: list[dict] = []
    for t in tasks:
        paths = [str(p) for p in (getattr(args, "paths", None) or []) if str(p).strip()]
        if paths:
            t["paths"] = paths
        if req_root is not None:
            assert req_rel is not None
            # 落点模式：卡 §1 正文指针化——需求正文唯一住址在落点，卡不复制正文
            t["details"] = requirement_pointer_text(req_rel)
        t_dir = tasks_dir / t["id"]
        if not args.dry_run:
            # plan 显式给过 --requirement ⇒ 需求驱动卡：同步写条目表 + 覆盖矩阵骨架
            # （#72/#73 开工前置产物；重跑不覆盖已填内容；落点模式写领取引用表）。
            write_task_card(t_dir, t, with_requirement_items=bool(args.requirement),
                            requirement_root_rel=req_rel)
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
        if req_root is not None:
            print(f"  落点模式：条目正文唯一住址 = {req_rel}/items.md；"
                  "开工前在卡 requirement-items.md 写领取引用行（RFC-20261122-03）")
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
            if target_task.get("requirement_root"):
                print(f"  开工前：在卡 requirement-items.md 写领取引用行"
                      f"（来源 = {target_task['requirement_root']}#<ID>，RFC-20261122-03）；"
                      "verify 前补全 coverage-matrix.md 四列覆盖（#73，空格/UNRESOLVED ⇒ WARN）")
            else:
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
    """同 (unit, round) 的 findings 不得覆盖（骨架 §4）：按已有轮次自动递增。

    轮号按日重置（只扫当日目录）；RFC-20261122-02 起走 `_support` 公共构造
    `scan_review_rounds`，命名契约单源（探针跨日扫描共用同一构造）。
    """
    rounds = [r for (_d, r, _p) in
              scan_review_rounds(root, unit, day=date.today().isoformat())]
    return max(rounds) + 1 if rounds else 1


def _mech_verdict_lines(violations: list[dict]) -> list[str]:
    """判决 FAIL 人读行（RFC-20261123-01 §2.2）：每条带出路 + 可复制申报行/落点
    （治手打路径口径分歧与 run 子卡解析后「申报放错目录」）。"""
    lines: list[str] = []
    for v in violations:
        if v["kind"] == "undeclared":
            preview = "、".join(v["hits"][:3]) + ("…" if len(v["hits"]) > 3 else "")
            lines.append(
                f"{v['doc']} 可能被本次改动触及（命中 {len(v['hits'])} 文件：{preview}）"
                f"但未跟改且未申报——查看该机制篇是否跟改：跟改后一并暂存，或在 "
                f"{v['declare_path']} 加行：{v['template']}")
        elif v["kind"] == "invalid_paths":
            bad = ", ".join(repr(g) for g in v["hits"])
            lines.append(
                f"{v['doc']} 的 mechanism-paths 含非法 glob {bad}："
                "词表只认字面路径与 dir/**（两档，RFC-20261123-01）——修正后重跑")
        else:
            lines.append(
                f"申报文件不可解析（fail-closed）：{v['hits'][0]}——修正 "
                f"{v['declare_path']}（合法行 = `- <篇路径>: not-involved: <理由>`，"
                "RFC-20261123-01）")
    return lines


def _topology_precheck_needed(root: Path, topology: dict, staged: list[str]) -> bool:
    from _support.runtime_topology import scan_sources
    scan_globs = topology.get("inputs", {}).get("scan_globs") or []
    current, errors = scan_sources(root, scan_globs)
    baseline = set(topology.get("source_files") or [])
    staged = set(staged)
    matched = any(fnmatch.fnmatch(path, pattern)
                  or (pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]))
                  for path in staged for pattern in scan_globs)
    return bool(errors or matched or staged & (set(current) | baseline))


def _check_staged_topology(root: Path, mode: str) -> dict:
    from _support.runtime_topology import check_topology
    with tempfile.TemporaryDirectory(prefix="atlas-workflow-topology-") as temporary:
        source_root = Path(temporary)
        checked_out = subprocess.run(["git", "checkout-index", "--all", f"--prefix={source_root}/"],
                                     cwd=root, capture_output=True, text=True, timeout=60)
        if checked_out.returncode != 0:
            return {"rc": 2, "cause": "topology_unverified",
                    "findings": [{"message": "staged index 不可物化：" + checked_out.stderr.strip()}]}
        return check_topology(root, mode=mode, source_root=source_root)
def _change_task(root: Path, unit: str) -> dict | None:
    try:
        tasks = load_tasks(_read_tasks_root(root), include_archived=True)
    except PlanError:
        return None
    return next((item for item in tasks if item.get("id") == unit), None)


def _change_kind(root: Path, task: dict | None) -> str | None:
    if not task or not task.get("requirement_root"):
        return None
    req_root = resolve_defect_root(root, Path(str(task["requirement_root"])).name)
    if req_root is None:
        return None
    fields, findings = strict_requirement_fields(req_root)
    if findings:
        return None
    kind = fields.get("类型")
    return kind if kind in CHANGE_TYPES else None


def _run_change_backflow(root: Path, task: dict) -> tuple[int, dict, str]:
    cmd = [sys.executable, str(HERE / "atlas_change.py"), "--root", str(root),
           "run", "--unit", task["id"], "--from", "staged", "--auto-stage", "--json"]
    try:
        result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                                errors="replace", timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        return 2, {"status": "error", "cause": "environment",
                   "message": f"自动回推无法启动：{exc}"}, ""
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        payload = {"status": "error", "cause": "environment",
                   "message": (result.stderr or result.stdout or "自动回推无 JSON 输出").strip()}
    if not isinstance(payload, dict):
        payload = {"status": "error", "cause": "environment",
                   "message": "自动回推输出不是 object"}
    return result.returncode, payload, (result.stderr or "").strip()


def _change_pause(args: argparse.Namespace, tasks_root: Path, unit: str, *,
                  cmd: str, cause: str, message: str, code: int | None = None) -> int:
    record_attempt(tasks_root, unit, cmd=cmd, cause=cause)
    if args.json:
        print(json.dumps({"unit": unit, "status": "paused", "paused_reason": cause,
                          "message": message}, ensure_ascii=False, indent=2))
    rc = exit_code_for(cause) if code is None else code
    return die(message, code=rc)


def _verify_change_backflow(args: argparse.Namespace, root: Path, task: dict | None) -> int | None:
    if args.dry_run or _change_kind(root, task) is None:
        return None
    assert task is not None
    if not args.json:
        print(f"atlas workflow verify @ {args.unit} 自动执行变更/缺陷回推...")
    rc, payload, stderr = _run_change_backflow(root, task)
    if rc != 0:
        cause = str(payload.get("cause") or "bug_backflow_invalid")
        conflicts = payload.get("conflicts") if isinstance(payload.get("conflicts"), list) else []
        message = str(payload.get("message") or stderr or "自动回推失败")
        if conflicts:
            message = "回推存在未签字冲突：" + "、".join(
                str(item.get("id") or item.get("path") or "?")
                for item in conflicts if isinstance(item, dict))
        return _change_pause(args, _read_tasks_root(root), args.unit, cmd="verify",
                             cause=cause, message=message, code=rc if rc in (1, 2) else None)
    checked = validate_backflow(root, task)
    if checked["findings"]:
        cause = checked["cause"] or "bug_backflow_pending"
        message = "；".join(checked["findings"])
        return _change_pause(args, _read_tasks_root(root), args.unit, cmd="verify",
                             cause=cause, message=message)
    if not args.json:
        print(f"  自动回推通过：stage={payload.get('stage', '?')}，"
              f"source={payload.get('source_sha256', '-')}")
    return None


def cmd_verify(args: argparse.Namespace, root: Path) -> int:
    if not args.unit:
        return die("verify 步骤必须指定 --unit <ID>")

    review_script = HERE / "atlas_review.py"
    tasks_root = _read_tasks_root(root)
    if not args.dry_run and not _has_staged_changes(root):
        # 前置态不扣预算（RFC-20261122-07 双轨），但入记账留观测痕
        record_attempt(tasks_root, args.unit, cmd="verify", cause="staged_empty")
        return _verify_paused(args, args.unit, "staged_empty",
                              "暂存区为空：请先实现并 `git add`，再运行 verify")
    change_task = _change_task(root, args.unit)
    change_rc = _verify_change_backflow(args, root, change_task)
    if change_rc is not None:
        return change_rc
    # 尝试预算门（RFC-20261122-07 §3.1.1；gates.md §2.1 同名行）：charged ≥ 上限
    # ⇒ 拒绝继续该单元（退出码 3 + budget_exceeded 留痕行），停下要求人工——不是放行。
    if not args.dry_run:
        charged = charged_count(tasks_root, args.unit)
        limit = max_verify_attempts(root)
        if charged >= limit:
            record_attempt(tasks_root, args.unit, cmd="verify", cause="budget_exceeded")
            return _verify_paused(
                args, args.unit, "budget_exceeded",
                f"任务 {args.unit} verify 尝试预算超限（charged {charged}/{limit}）：停下人工判断"
                "——修复实现后重试；确需放宽改 .atlas/config.yaml 的 "
                "workflow.max_verify_attempts；直跑 `atlas review --staged` 属绕行面（人工责任）")
    round_no = getattr(args, "round", None) or _next_review_round(root, args.unit)
    # 机制文档触及申报判决（RFC-20261123-01，前置判定带）：触及未跟改未申报 /
    # mechanism-paths 词表非法 ⇒ FAIL rc1 + 扣预算，拦在审查启动前（忘申报不烧
    # 一轮审查 token）。dry-run 不判决不记账不出红（与 staged_empty/预算门同契）。
    mech_docs = None
    if not args.dry_run:
        mech_docs = discover_mechanism_docs(root)
        violations = mechanism_declaration_verdict(
            root, _staged_files(root), tasks_root, args.unit, docs=mech_docs)
        if violations:
            cause = ("mechanism_paths_invalid"
                     if any(v["kind"] == "invalid_paths" for v in violations)
                     else "mechanism_undeclared")
            record_attempt(tasks_root, args.unit, cmd="verify", cause=cause)
            for line in _mech_verdict_lines(violations):
                print(f"FAIL（机制文档）: {line}", file=sys.stderr)
            if args.json:
                print(json.dumps({"unit": args.unit, "status": "gate_fail",
                                  "cause": cause,
                                  "violations": [{"doc": v["doc"], "kind": v["kind"],
                                                  "hits": v["hits"]}
                                                 for v in violations]},
                                 ensure_ascii=False, indent=2))
            return 1
    topology_path = root / ".adapter-out/topology.json"
    if not args.dry_run and topology_path.is_file():
        from _support.runtime_topology import topology_mode
        try:
            topology_data = json.loads(topology_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            topology_data = {}
        try:
            precheck = _topology_precheck_needed(root, topology_data, _staged_files(root))
        except (OSError, ValueError) as exc:
            topology = {"rc": 2, "cause": "topology_unverified",
                        "findings": [{"message": f"Topology 预检不可判定：{exc}"}]}
        else:
            if precheck:
                topology = _check_staged_topology(root, topology_mode(root))
            else:
                topology = {"rc": 0, "cause": None, "findings": []}
        if topology["rc"] != 0:
            record_attempt(tasks_root, args.unit, cmd="verify", cause=topology["cause"])
            if args.json:
                print(json.dumps({"unit": args.unit, "status": "gate_fail",
                                  "cause": topology["cause"], "findings": topology["findings"]},
                                 ensure_ascii=False, indent=2))
            for finding in topology["findings"]:
                print(f"FAIL（Topology）: {finding['message']}", file=sys.stderr)
            return topology["rc"]
    if not args.dry_run:
        from _support.docs_governance import DocsGovernanceError, check_docs_for_ids, docs_mode
        from _support.incident import IncidentError, configured_mode as incident_mode, validate_task_incidents

        task = next((item for item in load_tasks(_read_tasks_root(root)) if item.get("id") == args.unit), None)
        if task is None:
            return die(f"任务卡不存在：{args.unit}", exit_code_for("no_task_card"))
        governed = []
        try:
            if task.get("resolves_incidents"):
                governed.extend(validate_task_incidents(
                    root, task, force=False,
                    mode="off" if incident_mode(root) == "off" else "enforce"))
            if task.get("doc_ids"):
                governed.append(check_docs_for_ids(root, task.get("doc_ids") or [], mode=docs_mode(root)))
        except (IncidentError, DocsGovernanceError, OSError, ValueError) as exc:
            governed.append({"module": "governance", "rc": 2, "cause": "environment",
                             "findings": [{"message": f"治理引用无法校验：{exc}"}]})
        for result in governed:
            if result.get("rc") == 0:
                continue
            cause = result.get("cause") or {
                "incident": "incident_unverified", "docs": "docs_unverified",
            }.get(result.get("module"), "environment")
            record_attempt(tasks_root, args.unit, cmd="verify", cause=cause)
            if args.json:
                print(json.dumps({"unit": args.unit, "status": "gate_fail", "cause": cause,
                                  "findings": result["findings"]}, ensure_ascii=False, indent=2))
            for finding in result["findings"]:
                print(f"FAIL（{result.get('module', 'Governance')}）: {finding['message']}", file=sys.stderr)
            return result["rc"]
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
    # 落点模式（RFC-20261122-03）：逐卡对账之外再跑跨卡落点覆盖性与状态机对账。
    if pr.returncode == 0 and not args.dry_run:
        passed, review_dir, review_cause = check_task_review_passed(root, args.unit)
        if not passed:
            return die(review_dir, exit_code_for(review_cause))
        has_head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root,
                                  capture_output=True, timeout=15).returncode == 0
        if has_head:
            try:
                create_workflow_origin(root, args.unit,
                                      (Path(review_dir) / "review.json").relative_to(root).as_posix())
            except (OSError, ValueError) as exc:
                return die(f"workflow verify 来源标记写入失败：{exc}", EXIT_USAGE)
        for finding in coverage_matrix_findings(_read_tasks_root(root) / args.unit):
            print(f"WARN（需求条目覆盖）: {finding}", file=sys.stderr)
        for finding in requirement_root_findings(root):
            print(f"WARN（需求落点）: {finding}", file=sys.stderr)
        # 机制文档提示族残部（RFC-20261122-04 + RFC-20261123-01）：触及已升格
        # 申报判决门（前置判定带）；此处只剩死 paths / 词表点名 / 死测试锚 /
        # 申报死行 WARN，不改退出码。
        for finding in mechanism_doc_findings(root, docs=mech_docs):
            print(f"WARN（机制文档）: {finding}", file=sys.stderr)
        for finding in mechanism_dead_declare_findings(root, tasks_root, args.unit,
                                                       docs=mech_docs):
            print(f"WARN（机制文档）: {finding}", file=sys.stderr)
    # 失败入记账（RFC-20261122-07 双轨）：rc==1 = 报告（含 --check-cmd 并轨段）未过
    # ⇒ 扣预算；rc==2 = 会话待审 PENDING（审查未执行）⇒ 不扣；其余原生码归一为 1。
    if pr.returncode != 0 and not args.dry_run:
        cause = "no_review_report" if pr.returncode == 2 else "blocking_critical"
        record_attempt(tasks_root, args.unit, cmd="verify", cause=cause)
        rc = pr.returncode if pr.returncode in (0, 1, 2) else 1
        if args.json:
            print(json.dumps({"unit": args.unit, "status": "paused",
                              "paused_reason": cause}, ensure_ascii=False, indent=2))
        return rc
    # 本命令的退出码契约 = 0/1/2/3；子步的原生码（如 7）归一到 1。
    return pr.returncode if pr.returncode in (0, 1, 2, 3) else 1


def _verify_paused(args: argparse.Namespace, unit: str, cause: str, msg: str) -> int:
    """verify 前置/预算暂停出口：人读文案不变；--json 追加机器可读 paused_reason。"""
    if args.json:
        print(json.dumps({"unit": unit, "status": "paused", "paused_reason": cause},
                         ensure_ascii=False, indent=2))
    return die(msg, code=exit_code_for(cause))


def _finish_change_backflow(args: argparse.Namespace, root: Path,
                            task: dict) -> int | None:
    if _change_kind(root, task) is None:
        return None
    checked = validate_backflow(root, task)
    if not checked["findings"]:
        return None
    if not args.json:
        print(f"atlas workflow finish @ {args.unit} 检测到回推缺失/过期，自动补跑...")
    rc, payload, stderr = _run_change_backflow(root, task)
    if rc != 0:
        cause = str(payload.get("cause") or "bug_backflow_invalid")
        conflicts = payload.get("conflicts") if isinstance(payload.get("conflicts"), list) else []
        message = str(payload.get("message") or stderr or "自动回推失败")
        if conflicts:
            message = "回推存在未签字冲突：" + "、".join(
                str(item.get("id") or item.get("path") or "?")
                for item in conflicts if isinstance(item, dict))
        return _change_pause(args, _read_tasks_root(root), args.unit, cmd="finish",
                             cause=cause, message=message, code=rc if rc in (1, 2) else None)
    checked = validate_backflow(root, task)
    if checked["findings"]:
        cause = checked["cause"] or "bug_backflow_pending"
        return _change_pause(args, _read_tasks_root(root), args.unit, cmd="finish",
                             cause=cause, message="；".join(checked["findings"]))
    return _change_pause(
        args, _read_tasks_root(root), args.unit, cmd="finish",
        cause="change_backflow_reverify_required",
        message="自动回推已生成或更新产物；请重跑 verify 生成新鲜审查锚后再 finish")


def cmd_finish(args: argparse.Namespace, root: Path) -> int:
    if not args.unit:
        return die("finish 步骤必须指定 --unit <ID>")

    tasks_dir = _read_tasks_root(root)
    all_tasks = load_tasks(tasks_dir, include_archived=True)
    target_task = next((t for t in all_tasks if t["id"] == args.unit), None)
    if not target_task:
        return die(f"未找到任务卡 {args.unit}（不能对账本外任务收口）", code=2)

    if args.dry_run:
        print(f"$ # 校验 {args.unit} 的 review.json + E2E 前置 + 结构事实新鲜度，流转 completed 并归档 (dry-run)")
        return 0

    change_rc = _finish_change_backflow(args, root, target_task)
    if change_rc is not None:
        return change_rc

    lock_held = getattr(args, "_lock_held", False)
    try:
        res = finish_task(root, target_task, force=args.force, _lock_held=lock_held)
    except FinishError as exc:
        # 失败按 cause 双轨记账 + 分流退出码（RFC-20261122-07 §3.1.2：同一位点
        # 不同 cause 不同码——门红/扣预算 ⇒ 1；前置/顺序/环境 ⇒ 2）。
        cause = getattr(exc, "cause", None) or FALLBACK_CAUSE
        record_attempt(tasks_dir, args.unit, cmd="finish", cause=cause)
        rc = exit_code_for(cause)
        if args.json:
            print(json.dumps({"unit": args.unit, "status": "paused",
                              "paused_reason": cause}, ensure_ascii=False, indent=2))
        return die(str(exc), code=rc)

    res["change_backflow"] = res.get("bug_backflow")
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"atlas workflow finish @ {args.unit}   status: completed")
        e2e = res.get("e2e_precondition") or {}
        print(f"  E2E 前置：{e2e.get('status', '?')} —— {e2e.get('reason', '')}")
        st = res.get("structure_freshness") or {}
        print(f"  结构事实：{st.get('status', '?')} —— {st.get('reason', '')}")
        acceptance = e2e.get("acceptance") or {}
        if acceptance:
            print(f"  验收走查：{acceptance.get('status', '?')} —— {acceptance.get('reason', '')}")
        arch = res.get("archived") or {}
        if arch:
            print(f"  归档：{arch.get('status')} -> {arch.get('path')}")
        change = res.get("change_backflow") or {}
        if change.get("applicable"):
            print(f"  变更/缺陷回推：{len(change.get('artifacts') or [])} 个封印产物；审查锚 {change.get('review')}")
        req_root = target_task.get("requirement_root")
        closeout = res.get("requirement_closeout")
        if req_root and closeout:
            if closeout["product_fact_writeback"] == "conditional":
                print(f"  回写提醒：缺陷 {req_root} 先比对既有产品事实；"
                      "仅当事实缺失或错误时回写，否则只关闭缺陷。")
            elif closeout["product_fact_writeback"] == "required":
                print(f"  回写提醒：① 需求落点 {req_root} 的条目按域沉淀回产品事实"
                      "（FN/R/AC/文案规范表 + 变更记录）；② 落点状态行推进为「已收口」。")
            else:
                for finding in closeout.get("findings", []):
                    print(f"  回写阻断：{finding}")
                if not closeout.get("findings"):
                    print(f"  回写提醒：需求落点 {req_root} 仍有未归档或未 completed 关联卡，"
                          "暂不推进落点状态。")
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
               if archive_month(Path(t["_dir"]), tasks_dir, t["id"]) is None]
    if args.dry_run:
        print(f"$ # 归档 {len(pending)} 项到 {tasks_dir / 'archive'}/{date.today():%Y-%m}"
              "（dry-run 不移动）")
        return 0
    if args.unit and pending and pending[0].get("status") != "completed":
        # 顺序错归「前置不满足」（RFC-20261122-07 退出码语义修正：非门红）
        return die(f"任务 {args.unit} 尚未 completed，不能归档", code=2)
    if not pending:
        print("无待归档项（目标任务已归档或无可归档任务）")
        return 0
    moved: list[dict] = []
    for t in pending:
        if t.get("status") != "completed":
            print(f"跳过 {t['id']}：status={t.get('status')}（只归档 completed）")
            continue
        try:
            info = archive_task(root, tasks_dir, Path(t["_dir"]), t["id"],
                                _lock_held=getattr(args, "_lock_held", False))
        except FinishError as exc:
            # 归档类异常全为不扣预算类（state_transition/environment/no_task_card）⇒ 2
            return die(str(exc),
                       code=exit_code_for(getattr(exc, "cause", None) or FALLBACK_CAUSE))
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
        # 尝试记账与 deferred 聚合（RFC-20261122-07 §3.1.1/§3.1.3）：逐卡附加，不改既有键
        limit = max_verify_attempts(root)
        for t in all_tasks:
            rows, bad = load_attempts(tasks_dir, t["id"])
            charged = sum(1 for r in rows if r.get("charged") is True)
            t["attempts"] = {"charged": charged, "uncharged": max(len(rows) - charged, 0),
                             "limit": limit, "bad_lines": bad}
            t["deferred_open"] = deferred_open_count(Path(t["_dir"]))
        print(json.dumps({"tasks": all_tasks}, ensure_ascii=False, indent=2))
        return 0

    print(f"atlas workflow 任务台账（共 {len(all_tasks)} 项）：")
    limit = max_verify_attempts(root)
    for t in all_tasks:
        stat = t.get("status", "unknown")
        icon = "✓" if stat == "completed" else ("▶" if stat == "in_progress" else "○")
        suffix = " [archived]" if t.get("_archived") else ""
        print(f"  {icon} [{t['id']}] {t.get('title')} ({stat}){suffix}")
        if t.get("acs"):
            print(f"      ACs: {', '.join(t['acs'])}")
        # 尝试记账 + deferred 聚合（含归档卡：归档路径已知可读）
        rows, bad = load_attempts(tasks_dir, t["id"])
        charged = sum(1 for r in rows if r.get("charged") is True)
        notes: list[str] = []
        if rows or bad:
            notes.append(f"attempts: charged {charged}/{limit}，"
                         f"uncharged {max(len(rows) - charged, 0)}"
                         + (f"，坏行 {bad}" if bad else ""))
        open_def = deferred_open_count(Path(t["_dir"]))
        if open_def:
            notes.append(f"deferred 开放 {open_def}")
        if notes:
            print(f"      {'；'.join(notes)}")
    return 0


def cmd_progress(args: argparse.Namespace, root: Path) -> int:
    """只读进度探针（RFC-20261122-02）：聚合四格既有证据，不写盘、不改状态、不做 AC 级判定。"""
    if not args.unit:
        return die("progress 步骤必须指定 --unit <ID>")
    if getattr(args, "dry_run", False):
        print(f"$ # progress dry-run：只读探针，不写盘、不改状态（探针本身即只读）")
        return 0
    snap = progress_snapshot(root, args.unit)
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0
    print(render_progress(snap))
    return 0


def _has_staged_changes(root: Path) -> bool:
    try:
        pr = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=str(root),
                            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return pr.returncode == 0 and bool(pr.stdout.strip())


def _staged_files(root: Path) -> list[str]:
    """暂存区改动清单（--no-renames：改名两侧都算改动，防丢旧路径的机制篇命中）。"""
    try:
        pr = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--no-renames", "-z"], cwd=str(root),
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    if pr.returncode != 0:
        return []
    return [item for item in pr.stdout.split("\0") if item]


def _with_unit(args: argparse.Namespace, unit: str, *, lock_held: bool | None = None) -> argparse.Namespace:
    ns = argparse.Namespace(**vars(args))
    ns.unit = unit
    if lock_held is not None:
        ns._lock_held = lock_held
    return ns


def cmd_run(args: argparse.Namespace, root: Path) -> int:
    """跑通闭环：Plan -> Dispatch -> Verify -> Finish。

    前置：实现已按派工单完成并 `git add` 暂存（Atlas 不写业务实现）。
    暂存区为空时停在 Dispatch 之后，给出下一步指令并返回 2。
    """
    if args.dry_run:
        print("$ # run dry-run：plan → dispatch → verify → finish（不写盘、不改状态）")
        return 0
    sub_args = _with_unit(args, args.unit, lock_held=True)
    print(f"=== [1/4] 执行 Plan 规划阶段 ===")
    rc = cmd_plan(sub_args, root)
    if rc != 0:
        return rc

    print(f"\n=== [2/4] 执行 Dispatch 分发派单 ===")
    rc = cmd_dispatch(sub_args, root)
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
    rc = cmd_verify(_with_unit(sub_args, run_unit, lock_held=True), root)
    if rc != 0:
        print(f"Verify 未通过，工作流终止在当前单元。修复后可重试 verify。")
        return rc

    print(f"\n=== [4/4] 执行 Finish 确认收口 ===")
    return cmd_finish(_with_unit(sub_args, run_unit, lock_held=True), root)


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

    # progress（RFC-20261122-02 只读探针）
    p_prog = sub.add_parser("progress", parents=[common],
                            help="只读进度探针：聚合派工/暂存/审查轮次/覆盖矩阵四格"
                                 "（不写盘、不改状态、不做 AC 级判定）")
    p_prog.add_argument("--unit", required=True, help="进度查询的任务标识（须精确 ID，组标识会列成员）")

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
        "progress": cmd_progress,
        "archive": cmd_archive,
        "run": cmd_run,
    }
    handler = dispatch_map.get(args.subcommand)
    if not handler:
        return die(f"未知子命令：{args.subcommand}")
    try:
        mutating = args.subcommand in ("plan", "dispatch", "verify", "finish", "archive", "run")
        if mutating and not getattr(args, "dry_run", False):
            with WriteLock(root, holder=f"workflow-{args.subcommand}", unit=getattr(args, "unit", None) or ""):
                args._lock_held = True
                return handler(args, root)
        return handler(args, root)
    except WriteLockError as exc:
        return die(f"写链互斥锁冲突：{exc}", code=2)
    except PlanError as exc:
        return die(str(exc))


if __name__ == "__main__":
    sys.exit(main())
