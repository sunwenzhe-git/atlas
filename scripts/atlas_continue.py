#!/usr/bin/env python3
"""Atlas Guarded Continuation CLI（GDR P1 + P2 业务写链）。

子命令：
  只读 / 治理准备：
    preflight        纯只读收口预检（零写盘，P2 审批与运行前校验用）
    prepare          校验计划/任务态/输入闭集，生成 input-manifest.json
    verify           重验计划哈希 + WAL 阶段授权写集 + 任务态
    record           原子写 execution-receipt.json（RECORDED）
    audit            agent_settled / session_shutdown 兜底后的最终审计
    diagnose-unknown WAL / 磁盘 / HEAD 只读诊断（严禁重放写动作）
  P2 写链与长生命周期锁：
    lock-hold        持有共享 WriteLock（stdin 租约 token，stdout 打印 LOCKED\\n，EOF 释放）
    write-deferred   INTENT → 登记 deferred.md / staged 拓扑 / enforce receipt
    write-commit     INTENT → task.json=completed + 条件 git commit + 提交后指纹/非授权树复核
    write-archive    INTENT → pre_archive_files 登记 + archive_task + dir_fsync + 守恒复核
    wal-commit       三方校验通过后追加 WAL COMMITTED
    wal-mark-unknown 写启动后异常/不确定 ⇒ 追加 WAL UNKNOWN

退出码封闭：0 = 通过；2 = 契约/环境失败（fail-closed）。
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.guarded_continuation import (  # noqa: E402
    CONTINUATIONS_DIRNAME,
    PlanError,
    UNIT_RE,
    WRITE_LOCK_REL,
    WriteLock,
    WriteLockError,
    append_wal,
    assert_no_symlink_components,
    atomic_write_json_durable,
    audit_failure_payload,
    authorized_write_set,
    canonical_json,
    certificate_payload,
    diagnose_unknown,
    file_sha256,
    fsync_dir,
    has_mutating_write_actions,
    isolated_marker_path,
    load_plan,
    manifest_hash,
    path_in_authorized_set,
    read_json,
    read_wal,
    replay_guards,
    resolve_task_dir,
    run_dir,
    sha256_hex,
    verify_archive_conservation,
    verify_write_lock_lease,
    wal_state_summary,
    write_json_exclusive,
)
from _support.governance_schema import canonical_digest  # noqa: E402
from _support.runtime_topology import TopologyError, scope_topology_result, topology_mode  # noqa: E402
from _support.semantic_contracts import SemanticError  # noqa: E402
from _support.workflow_finish import (  # noqa: E402
    FinishError,
    _git_out,
    _refresh_staged_topology,
    archive_task,
    extract_deferred_findings,
    preflight_finish,
    staged_files as wf_staged_files,
)
from _support.workflow_plan import ARCHIVE_DIR, load_tasks  # noqa: E402
from _support.workflow_receipt import (  # noqa: E402
    ReceiptError,
    build_receipt,
    receipt_mode,
    verify_receipt,
)

EXIT_OK = 0
EXIT_FAIL = 2

TREE_EXCLUDE_DIRS = {".git"}


def _fail_json(cause: str, detail: str = "", **extra: object) -> int:
    payload = {"status": "error", "ok": False, "cause": cause, "detail": detail, **extra}
    print(json.dumps(payload, ensure_ascii=False))
    return EXIT_FAIL


def _resolve_git_dir(root: Path) -> Path | None:
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir:"):
            raw = text.split(":", 1)[1].strip()
            p = Path(raw)
            return p if p.is_absolute() else (root / p).resolve()
    return None


def _check_git_config_safety(root: Path) -> tuple[bool, str]:
    """拒绝非空 core.fsmonitor 或指向仓库外的 core.hooksPath（不依赖 git config CLI）。"""
    git_dir = _resolve_git_dir(root)
    if git_dir is None:
        return True, ""
    cfg_path = git_dir / "config"
    if not cfg_path.is_file():
        return True, ""
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(cfg_path.read_text(encoding="utf-8", errors="replace"))
    except configparser.Error as exc:
        return False, f"git config 不可解析：{exc}"
    if parser.has_section("core"):
        fsmon = (parser.get("core", "fsmonitor", fallback="") or "").strip()
        if fsmon and fsmon.lower() not in ("false", "0", "no"):
            return False, f"拒绝启用 core.fsmonitor={fsmon!r}"
        hooks = (parser.get("core", "hooksPath", fallback="") or
                 parser.get("core", "hookspath", fallback="") or "").strip()
        if hooks:
            hp = Path(hooks)
            hp_resolved = hp.resolve() if hp.is_absolute() else (root / hp).resolve()
            root_resolved = root.resolve()
            if root_resolved != hp_resolved and root_resolved not in hp_resolved.parents:
                return False, f"拒绝外部 core.hooksPath={hooks!r}"
    return True, ""


# 全树对账排除面：.git、本次 run 目录白名单、精确隔离标记路径、全局写锁文件。
def _tree_entries(root: Path, run: Path | None, unit: str | None) -> dict[str, str]:
    """全树内容哈希（os.walk，3.9+ 兼容；净化环境无 Path.walk[3.12+] 依赖）。"""
    exclude_files = {WRITE_LOCK_REL}
    if unit:
        exclude_files.add(str(isolated_marker_path(root, unit).relative_to(root)).replace("\\", "/"))
    entries: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        parts = set(rel_dir.parts)
        if parts & TREE_EXCLUDE_DIRS:
            dirnames[:] = []
            continue
        if run is not None:
            try:
                Path(dirpath).relative_to(run)
                dirnames[:] = []
                continue
            except ValueError:
                pass
        for name in filenames:
            rel = str(Path(dirpath, name).relative_to(root)).replace("\\", "/")
            if rel in exclude_files:
                continue
            try:
                entries[rel] = file_sha256(Path(dirpath, name))
            except OSError:
                entries[rel] = "unreadable"
    return entries


def _tree_diff(old: dict, new: dict) -> list[str]:
    changed = [k for k in set(old) | set(new) if old.get(k) != new.get(k)]
    return sorted(changed)


def _task_state_ok(
    root: Path,
    unit: str,
    *,
    expected_statuses: tuple[str, ...] = ("in_progress",),
    archived_task_dir: str | None = None,
) -> tuple[bool, str, dict | None, Path | None]:
    try:
        t_dir, _ = resolve_task_dir(root, unit, archived_task_dir=archived_task_dir)
    except PlanError as exc:
        return False, str(exc), None, None
    task_json = t_dir / "task.json"
    if task_json.is_symlink() or not task_json.is_file():
        return False, f"task.json 缺失：{task_json}", None, t_dir
    try:
        task = read_json(task_json)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"task.json 不可解析：{exc}", None, t_dir
    if task.get("id") != unit:
        return False, f"task.id 与 unit 不一致：{task.get('id')!r}", None, t_dir
    if task.get("status") not in expected_statuses:
        return (False,
                f"任务状态须为 {'/'.join(expected_statuses)}，got {task.get('status')!r}",
                None, t_dir)
    return True, "", task, t_dir


def _load_active_task(root: Path, unit: str) -> dict:
    if not UNIT_RE.fullmatch(unit):
        raise FinishError(f"非法 unit：{unit!r}", cause="no_task_card")
    tasks_dir = (Path(root).resolve() / ".atlas" / "tasks").resolve()
    t_dir = tasks_dir / unit
    if t_dir.is_symlink() or not t_dir.is_dir():
        raise FinishError(f"活跃任务卡不存在或已归档：{t_dir}", cause="no_task_card")
    all_tasks = load_tasks(tasks_dir, include_archived=False)
    task = next((t for t in all_tasks if t.get("id") == unit), None)
    if task is None:
        raise FinishError(f"未在活跃任务账本找到 {unit}", cause="no_task_card")
    return task


def _read_lock_token_stdin() -> str:
    raw = sys.stdin.read()
    if not raw.strip():
        raise WriteLockError("stdin 未收到写锁租约 JSON")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WriteLockError(f"stdin 写锁租约不可解析：{exc}") from exc
    tok = obj.get("lock_token") or obj.get("token") or ""
    if not isinstance(tok, str) or not tok:
        raise WriteLockError("stdin 写锁租约缺少 lock_token")
    return tok


def cmd_preflight(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    safe_git, why_git = _check_git_config_safety(root)
    if not safe_git:
        return _fail_json("git_config_unsafe", why_git)
    try:
        task = _load_active_task(root, args.unit)
        res = preflight_finish(root, task, force=False, require_full_onboarding=True)
    except FinishError as exc:
        return _fail_json(exc.cause or "preflight_failed", str(exc))
    except Exception as exc:  # noqa: BLE001
        return _fail_json("environment", str(exc))
    print(json.dumps(res, ensure_ascii=False))
    return EXIT_OK


def cmd_lock_hold(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not UNIT_RE.fullmatch(args.unit):
        return _fail_json("unit", f"非法 unit：{args.unit!r}")
    line = sys.stdin.readline()
    if not line.strip():
        return _fail_json("lock_lease", "stdin 缺少初始化 token JSON 行")
    try:
        tok_obj = json.loads(line)
        token = tok_obj.get("token") or tok_obj.get("lock_token") or ""
        if not isinstance(token, str) or len(token) < 8:
            return _fail_json("lock_lease", "lock_token 非法或过短")
    except json.JSONDecodeError as exc:
        return _fail_json("lock_lease", f"token JSON 不可解析：{exc}")

    def _on_term(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    try:
        with WriteLock(root, holder="pi-gc-p2", unit=args.unit,
                       run_id=args.run_dir, token=token):
            sys.stdout.write("LOCKED\n")
            sys.stdout.flush()
            try:
                sys.stdin.read()
            except OSError:
                pass
    except WriteLockError as exc:
        return _fail_json("write_lock_busy", str(exc))
    return EXIT_OK


def cmd_prepare(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    safe_git, why_git = _check_git_config_safety(root)
    if not safe_git:
        return _fail_json("git_config_unsafe", why_git)
    run = run_dir(root, args.run_dir)
    try:
        plan = load_plan(root, args.unit)
    except PlanError as e:
        return _fail_json("plan", str(e))
    ok, why, _, _ = _task_state_ok(root, args.unit)
    if not ok:
        return _fail_json("task_state", why)
    tree = _tree_entries(root, run, args.unit)
    manifest = {
        "schema": 1,
        "run_id": args.run_dir,
        "unit": args.unit,
        "plan_sha256": plan["plan_sha256"],
        "tree_entries": len(tree),
        "tree_sha256": sha256_hex(canonical_json(tree).encode("utf-8")),
        "tree": tree,
        "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_json_exclusive(run / "input-manifest.json", manifest)
    print(json.dumps({"status": "ok", "input_manifest_sha256": manifest["tree_sha256"],
                      "tree_entries": manifest["tree_entries"]}))
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    wal_entries, truncated = read_wal(run)
    wal = wal_state_summary(wal_entries, truncated)
    if wal["is_unknown"]:
        return _fail_json("wal_unknown", "WAL 存在 UNKNOWN / 悬空 INTENT / 尾部半行，禁止继续执行")
    archived_dir = wal["archived_task_dir"]
    committed_tools = wal["committed_tools"]
    try:
        plan = load_plan(root, args.unit, archived_task_dir=archived_dir)
    except PlanError as e:
        return _fail_json("plan", str(e))
    manifest_path = run / "input-manifest.json"
    if not manifest_path.is_file():
        return _fail_json("manifest", "prepare 缺失")
    manifest = read_json(manifest_path)
    if manifest["plan_sha256"] != plan["plan_sha256"]:
        return _fail_json("plan_stale", "计划文件在 prepare 后发生变化")
    expected_statuses = ("completed",) if "atlas_workflow_finish_commit" in committed_tools else ("in_progress",)
    ok, why, _, _ = _task_state_ok(root, args.unit,
                                   expected_statuses=expected_statuses,
                                   archived_task_dir=archived_dir)
    if not ok:
        return _fail_json("task_state", why)
    tree = _tree_entries(root, run, args.unit)
    now_sha = sha256_hex(canonical_json(tree).encode("utf-8"))
    if now_sha != manifest["tree_sha256"]:
        changed = _tree_diff(manifest["tree"], tree)
        if not committed_tools:
            return _fail_json("tree_changed", f"{len(changed)} paths changed", sample=changed[:8])
        allowed = authorized_write_set(
            root, args.unit, committed_tools,
            deferred_meta=wal.get("deferred_meta"),
            archived_task_dir=archived_dir,
            pre_archive_files=wal.get("pre_archive_files"),
        )
        unexpected = [rel for rel in changed if not path_in_authorized_set(rel, allowed)]
        if unexpected:
            return _fail_json("unauthorized_tree_change",
                              f"存在 {len(unexpected)} 个未授权变更路径", sample=unexpected[:8])
    print(json.dumps({"status": "ok", "phase": args.phase or "pre-action"}))
    return EXIT_OK


def _wal_precheck_no_replay(run: Path, action_index: int) -> tuple[bool, str]:
    entries, truncated = read_wal(run)
    wal = wal_state_summary(entries, truncated)
    if wal["is_unknown"]:
        return False, "WAL 处于 UNKNOWN / 悬空 INTENT / 半行状态，禁止写动作或重放"
    if any(int(e.get("action_index", -1)) == action_index for e in entries):
        return False, f"action_index={action_index} 已有 WAL 记录，禁止重复执行"
    return True, ""


def _dir_snapshot_hashes(base: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = str(p.relative_to(base)).replace("\\", "/")
            out[rel] = file_sha256(p)
    return out


def cmd_write_deferred(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    try:
        token = _read_lock_token_stdin()
        verify_write_lock_lease(root, args.run_dir, args.unit, token)
    except WriteLockError as exc:
        return _fail_json("write_lock_invalid", str(exc))
    ok_wal, why_wal = _wal_precheck_no_replay(run, args.action_index)
    if not ok_wal:
        return _fail_json("wal_replay_forbidden", why_wal)
    try:
        load_plan(root, args.unit)
        task = _load_active_task(root, args.unit)
        pre = preflight_finish(root, task, force=False, require_full_onboarding=True)
    except (PlanError, FinishError) as exc:
        return _fail_json(getattr(exc, "cause", None) or "preflight_failed", str(exc))

    t_dir = Path(pre["task_dir"])
    head_before = pre.get("head_commit") or ""
    deferred_path = t_dir / "deferred.md"
    target_paths = [str(deferred_path.relative_to(root)).replace("\\", "/")]
    if task.get("topology_required"):
        target_paths.extend([".adapter-out/topology.json", ".adapter-out/topology/*",
                             ".atlas/spec/structure/global/runtime-topology.md"])
    if receipt_mode(root) == "enforce":
        target_paths.extend([".atlas/runs/workflow-receipt.json", ".atlas/runs/workflow-receipt/*"])
    append_wal(run, {
        "phase": "INTENT",
        "action_index": args.action_index,
        "action_id": args.action_id,
        "tool": "atlas_workflow_finish_deferred",
        "head_before": head_before,
        "target_paths": target_paths,
    })

    # 执行隐写面：deferred + staged topology + enforce receipt
    try:
        deferred_info = extract_deferred_findings(root, task, t_dir)
        deferred_written = bool(deferred_path.is_file())

        # 重跑 _validate_finish_gates（或仅执行 topology + build/verify_receipt）
        from _support.workflow_finish import _validate_finish_gates
        tasks_root = (root / ".atlas" / "tasks").resolve()
        gates = _validate_finish_gates(
            root, task, t_dir, tasks_root,
            force=False, require_full_onboarding=True, mutate_topology=False,
        )
        topology_written = False
        topology_files: list[str] = []
        topology_result = None
        if task.get("topology_required"):
            topo_options = {}
            topology_path = root / ".adapter-out/topology.json"
            if topology_path.is_file():
                try:
                    tdata = json.loads(topology_path.read_text(encoding="utf-8"))
                    topo_options = tdata.get("inputs") or {}
                    pointer_path = root / ".adapter-out/topology/manifest.json"
                    if pointer_path.is_file():
                        topo_options.setdefault("adapter", json.loads(pointer_path.read_text()).get("adapter", "all"))
                except (OSError, ValueError):
                    topo_options = {}
            topo_options["mode"] = topology_mode(root)
            topology_result = _refresh_staged_topology(root, topo_options)
            if topology_result and topology_result.get("verdict") == "UNVERIFIED" \
                    and topology_result.get("cause") == "topology_unverified":
                tdata = json.loads((root / ".adapter-out/topology.json").read_text(encoding="utf-8"))
                staged = wf_staged_files(root)
                if staged is None:
                    raise TopologyError("暂存面不可判定，不能降级动态拓扑 scope")
                topology_result = scope_topology_result(topology_result, tdata, staged)
            if topology_result.get("rc") != 0:
                raise FinishError("topology 刷新失败", cause=topology_result.get("cause") or "topology_stale")
            topology_written = True
            topology_files = [".adapter-out/topology.json", ".atlas/spec/structure/global/runtime-topology.md"]

        receipt_written = False
        receipt_files: list[str] = []
        enforce_ctx = gates.get("enforce_ctx")
        if enforce_ctx is not None:
            governed_results = enforce_ctx["governed_results"]
            if topology_result is not None:
                governed_results = [
                    item for item in governed_results if item.get("module") != "topology"
                ] + [{key: topology_result[key] for key in ("module", "verdict", "rc")}
                     | {"digest": canonical_digest(topology_result)}]
            build_receipt(
                root=root, unit=args.unit, task_id=args.unit, base=enforce_ctx["base"],
                validators=governed_results, in_scope_modules=enforce_ctx["scope"],
                module_modes=enforce_ctx["module_modes"],
                review_path=(Path(gates["review_dir"]).absolute().relative_to(root).as_posix() + "/review.json"),
                requirement_id=task.get("requirement_root"), clause_ids=task.get("clause_ids") or [],
                incident_ids=task.get("incident_ids") or [], resolves_incidents=task.get("resolves_incidents") or [],
                doc_ids=task.get("doc_ids") or [], topology_refs=task.get("topology_refs") or [],
                topology_required=bool(task.get("topology_required")), migration_required=bool(task.get("source_manifest")),
                classification_required=bool(task.get("classification_required")),
                classification_result=gates["classification_result"],
                classification_input_digest=gates["expected_digest"],
                review_origin="workflow", force=False,
            )
            receipt_result = verify_receipt(
                root, mode="enforce", check_current_tree=True,
                expected_unit=args.unit, expected_task_id=args.unit,
                expected_validator_digests={item["module"]: item["digest"] for item in governed_results},
            )
            if receipt_result["rc"] != 0:
                raise FinishError("；".join(item["message"] for item in receipt_result["findings"]),
                                  cause=receipt_result.get("cause") or "receipt_unverified")
            receipt_written = True
            receipt_files = [".atlas/runs/workflow-receipt.json"]
    except (FinishError, TopologyError, ReceiptError, SemanticError, OSError, ValueError) as exc:
        append_wal(run, {
            "phase": "UNKNOWN",
            "action_index": args.action_index,
            "action_id": args.action_id,
            "tool": "atlas_workflow_finish_deferred",
            "reason": str(exc),
        })
        return _fail_json("write_deferred_failed", str(exc))

    meta = {
        "deferred_written": deferred_written,
        "deferred_registered": deferred_info.get("registered", 0),
        "topology_written": topology_written,
        "topology_files": topology_files,
        "receipt_written": receipt_written,
        "receipt_files": receipt_files,
    }
    print(json.dumps({"ok": True, "status": "ok", "unit": args.unit,
                      "wal_commit_payload": {"meta": meta}}, ensure_ascii=False))
    return EXIT_OK


def cmd_write_commit(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    try:
        token = _read_lock_token_stdin()
        verify_write_lock_lease(root, args.run_dir, args.unit, token)
    except WriteLockError as exc:
        return _fail_json("write_lock_invalid", str(exc))
    ok_wal, why_wal = _wal_precheck_no_replay(run, args.action_index)
    if not ok_wal:
        return _fail_json("wal_replay_forbidden", why_wal)
    try:
        load_plan(root, args.unit)
        task = _load_active_task(root, args.unit)
        pre = preflight_finish(root, task, force=False, require_full_onboarding=True)
    except (PlanError, FinishError) as exc:
        return _fail_json(getattr(exc, "cause", None) or "preflight_failed", str(exc))

    t_dir = Path(pre["task_dir"])
    task_json_file = t_dir / "task.json"
    if task_json_file.is_symlink():
        return _fail_json("symlink_forbidden", f"task.json 不得为 symlink：{task_json_file}")
    assert_no_symlink_components(root, task_json_file)
    head_before = pre.get("head_commit") or ""
    if not head_before:
        return _fail_json("environment", "无法取得 HEAD baseline")

    if task_json_file.is_file():
        try:
            meta = read_json(task_json_file)
        except Exception:
            meta = dict(task)
    else:
        meta = dict(task)
    meta.pop("_dir", None)
    meta.pop("_archived", None)
    receipt_res = None
    if receipt_mode(root) == "enforce":
        try:
            receipt_res = verify_receipt(root, mode="enforce", check_current_tree=True,
                                         expected_unit=args.unit, expected_task_id=args.unit)
            if receipt_res.get("rc") != 0:
                return _fail_json(receipt_res.get("cause") or "receipt_unverified",
                                  "；".join(f["message"] for f in receipt_res.get("findings", [])))
        except (ReceiptError, SemanticError, OSError, ValueError) as exc:
            return _fail_json("receipt_unverified", str(exc))

    meta["status"] = "completed"
    meta["e2e_precondition"] = pre["e2e_precondition"]
    meta["structure_freshness"] = pre["structure_freshness"]
    meta["governance_precondition"] = {
        "incidents": pre["governance_precondition"]["incidents"],
        "docs": pre["governance_precondition"]["docs"],
        "topology": pre["governance_precondition"]["topology"],
        "receipt": receipt_res,
    }
    expected_task_text = json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    expected_task_sha256 = sha256_hex(expected_task_text.encode("utf-8"))

    staged = wf_staged_files(root) or []
    expected_tree: str | None = None
    if staged:
        ok_wt, wt_out = _git_out(root, "write-tree")
        if not ok_wt or not wt_out.strip():
            return _fail_json("git_write_tree_failed", "git write-tree 失败")
        expected_tree = wt_out.strip().splitlines()[0]

    # 先写 INTENT，再变更磁盘与 git
    append_wal(run, {
        "phase": "INTENT",
        "action_index": args.action_index,
        "action_id": args.action_id,
        "tool": "atlas_workflow_finish_commit",
        "head_before": head_before,
        "expected_tree": expected_tree,
        "expected_task_sha256": expected_task_sha256,
        "target_paths": [str(task_json_file.relative_to(root)).replace("\\", "/")],
    })

    def _abort_unknown(reason: str) -> int:
        append_wal(run, {
            "phase": "UNKNOWN",
            "action_index": args.action_index,
            "action_id": args.action_id,
            "tool": "atlas_workflow_finish_commit",
            "reason": reason,
        })
        return _fail_json("post_commit_unknown", reason)

    try:
        actual_task_sha256 = atomic_write_json_durable(task_json_file, meta)
    except (OSError, PlanError) as exc:
        return _abort_unknown(f"写入 task.json 失败：{exc}")

    git_commit_status = "skipped_empty_staged"
    head_after = head_before
    if staged:
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_DIR")}
        pr = subprocess.run(
            ["git", "commit", "-m", f"chore(workflow): finish {args.unit}"],
            cwd=str(root), env=env_clean, capture_output=True, text=True, timeout=30,
        )
        if pr.returncode != 0:
            return _abort_unknown(f"git commit 失败（rc={pr.returncode}）：{(pr.stderr or pr.stdout).strip()[:200]}")
        git_commit_status = "committed"

    # 提交后期望指纹与非授权树复核
    if not task_json_file.is_file() or file_sha256(task_json_file) != expected_task_sha256:
        return _abort_unknown("提交后 task.json SHA256 与 expected_task_sha256 不一致")
    if actual_task_sha256 != expected_task_sha256:
        return _abort_unknown("atomic_write_json_durable 返回 SHA256 与 expected_task_sha256 不一致")

    if git_commit_status == "committed":
        ok_p, p_out = _git_out(root, "rev-parse", "--verify", "HEAD^")
        ok_t, t_out = _git_out(root, "rev-parse", "--verify", "HEAD^{tree}")
        ok_h, h_out = _git_out(root, "rev-parse", "HEAD")
        if not ok_p or p_out.strip().splitlines()[0] != head_before:
            return _abort_unknown("提交后 HEAD^ 与 head_before 不一致")
        if not ok_t or t_out.strip().splitlines()[0] != expected_tree:
            return _abort_unknown("提交后 HEAD^{tree} 与 expected_tree 不一致")
        if (wf_staged_files(root) or []):
            return _abort_unknown("提交后暂存区仍非空")
        head_after = h_out.strip().splitlines()[0] if ok_h and h_out else ""
    else:
        ok_h, h_out = _git_out(root, "rev-parse", "HEAD")
        if not ok_h or h_out.strip().splitlines()[0] != head_before:
            return _abort_unknown("空暂存跳过提交时 HEAD 意外变化")
        if (wf_staged_files(root) or []):
            return _abort_unknown("空暂存跳过提交但暂存区非空")

    # 核对工作树仅允许本 run 已提交动作授权路径变更（防 pre-commit hook 篡改）
    manifest_file = run / "input-manifest.json"
    if manifest_file.is_file():
        manifest = read_json(manifest_file)
        entries, truncated = read_wal(run)
        wal = wal_state_summary(entries, truncated)
        allowed = authorized_write_set(
            root, args.unit, wal["committed_tools"] + ["atlas_workflow_finish_commit"],
            deferred_meta=wal.get("deferred_meta"),
        )
        now_tree = _tree_entries(root, run, args.unit)
        changed = _tree_diff(manifest["tree"], now_tree)
        unexpected = [rel for rel in changed if not path_in_authorized_set(rel, allowed)]
        # 若刚刚提交成功，暂存实现文件从工作树视角的 HASH 与 HEAD commit 前同文件比较不变（除非 hook 修改）；
        # 若 manifest 里无某已暂存删除/新增导致差异，过滤 git commit 已接管的 staged 集？
        # 实际上 manifest 在 prepare 时（实现已暂存）捕获：若 hook 改了磁盘文件，now_tree != manifest["tree"]。
        if unexpected:
            return _abort_unknown(f"提交后工作树含未授权变更：{unexpected[:6]}")

    print(json.dumps({
        "ok": True,
        "status": "ok",
        "unit": args.unit,
        "git_commit": git_commit_status,
        "head_before": head_before,
        "head_after": head_after,
        "expected_task_sha256": expected_task_sha256,
        "wal_commit_payload": {"actual_task_sha256": expected_task_sha256, "head_after": head_after},
    }, ensure_ascii=False))
    return EXIT_OK


def cmd_write_archive(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    try:
        token = _read_lock_token_stdin()
        verify_write_lock_lease(root, args.run_dir, args.unit, token)
    except WriteLockError as exc:
        return _fail_json("write_lock_invalid", str(exc))
    ok_wal, why_wal = _wal_precheck_no_replay(run, args.action_index)
    if not ok_wal:
        return _fail_json("wal_replay_forbidden", why_wal)
    try:
        load_plan(root, args.unit)
        task = _load_active_task(root, args.unit)
    except (PlanError, FinishError) as exc:
        return _fail_json(getattr(exc, "cause", None) or "archive_precheck_failed", str(exc))

    if task.get("status") != "completed":
        return _fail_json("state_transition", f"归档要求任务已 completed，got {task.get('status')!r}")

    tasks_root = (root / ".atlas" / "tasks").resolve()
    t_dir = tasks_root / args.unit
    assert_no_symlink_components(root, t_dir)
    pre_files = _dir_snapshot_hashes(t_dir)
    expected_task_sha256 = pre_files.get("task.json")
    expected_plan_sha256 = pre_files.get("continuation.json")

    from datetime import date as _date
    expected_archive_dir = f".atlas/tasks/{ARCHIVE_DIR}/{_date.today().strftime('%Y-%m')}/{args.unit}"
    ok_h, h_out = _git_out(root, "rev-parse", "HEAD")
    head_before = h_out.strip().splitlines()[0] if ok_h and h_out else ""

    append_wal(run, {
        "phase": "INTENT",
        "action_index": args.action_index,
        "action_id": args.action_id,
        "tool": "atlas_workflow_finish_archive",
        "head_before": head_before,
        "expected_archive_dir": expected_archive_dir,
        "expected_task_sha256": expected_task_sha256,
        "expected_plan_sha256": expected_plan_sha256,
        "pre_archive_files": pre_files,
        "target_paths": [f".atlas/tasks/{args.unit}", expected_archive_dir],
    })

    def _abort_unknown(reason: str) -> int:
        append_wal(run, {
            "phase": "UNKNOWN",
            "action_index": args.action_index,
            "action_id": args.action_id,
            "tool": "atlas_workflow_finish_archive",
            "reason": reason,
        })
        return _fail_json("archive_unknown", reason)

    try:
        arch = archive_task(root, tasks_root, t_dir, args.unit, _lock_held=True)
    except FinishError as exc:
        return _abort_unknown(f"archive_task 失败：{exc}")

    archived_rel = arch.get("path", "").replace("\\", "/")
    if archived_rel != expected_archive_dir:
        return _abort_unknown(f"归档路径不符：got {archived_rel!r}, expected {expected_archive_dir!r}")

    ok_cons, why_cons = verify_archive_conservation(
        root, args.unit, archived_rel, pre_files, expected_task_sha256, expected_plan_sha256,
    )
    if not ok_cons:
        return _abort_unknown(f"归档守恒复核失败：{why_cons}")

    print(json.dumps({
        "ok": True,
        "status": "ok",
        "unit": args.unit,
        "archived_task_dir": archived_rel,
        "wal_commit_payload": {"archived_task_dir": archived_rel},
    }, ensure_ascii=False))
    return EXIT_OK


def cmd_wal_commit(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    entries, truncated = read_wal(run)
    wal = wal_state_summary(entries, truncated)
    if truncated:
        return _fail_json("wal_truncated", "WAL 存在尾部半行")
    if wal["unknown_entries"]:
        return _fail_json("wal_already_unknown", "WAL 已有 UNKNOWN，禁止 COMMITTED")
    has_intent = any(
        e.get("phase") == "INTENT" and e.get("action_index") == args.action_index and e.get("tool") == args.tool
        for e in entries
    )
    if not has_intent:
        return _fail_json("missing_intent", f"缺 action_index={args.action_index} tool={args.tool} 的 INTENT")
    extra: dict = {}
    if args.detail_json:
        try:
            loaded = json.loads(args.detail_json)
            if isinstance(loaded, dict):
                extra = loaded
        except json.JSONDecodeError as exc:
            return _fail_json("bad_detail_json", str(exc))
    rec = append_wal(run, {
        "phase": "COMMITTED",
        "action_index": args.action_index,
        "action_id": args.action_id,
        "tool": args.tool,
        **extra,
    })
    print(json.dumps({"status": "ok", "seq": rec["seq"]}, ensure_ascii=False))
    return EXIT_OK


def cmd_wal_mark_unknown(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    rec = append_wal(run, {
        "phase": "UNKNOWN",
        "action_index": args.action_index,
        "action_id": args.action_id,
        "tool": args.tool,
        "reason": args.reason,
    })
    print(json.dumps({"status": "ok", "verdict": "UNKNOWN", "seq": rec["seq"]}, ensure_ascii=False))
    return EXIT_OK


def cmd_diagnose_unknown(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    diag = diagnose_unknown(root, run, args.unit)
    print(json.dumps(diag, ensure_ascii=False))
    return EXIT_OK


def cmd_record(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    payload = json.loads(Path(args.receipt_json).read_text(encoding="utf-8"))
    required = {"run_id", "unit", "plan_sha256", "status", "actions", "terminal_reason",
                "expected_parent_result_sha256", "session_id", "parent_tool_call_id"}
    missing = required - set(payload)
    if missing:
        return _fail_json("receipt_schema", f"缺字段 {sorted(missing)}")
    if payload["run_id"] != args.run_dir or payload["unit"] != args.unit:
        return _fail_json("receipt_mismatch")
    receipt_path = run / "execution-receipt.json"
    sha = write_json_exclusive(receipt_path, payload)
    print(json.dumps({"status": "ok", "execution_receipt_sha256": sha}))
    return EXIT_OK


def cmd_audit(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)

    wal_entries, truncated = read_wal(run)
    wal = wal_state_summary(wal_entries, truncated)
    if wal["is_unknown"]:
        diag = diagnose_unknown(root, run, args.unit)
        atomic_write_json_durable(run / "unknown-diagnosis.json", diag)
        print(json.dumps({"status": "error", "verdict": "UNKNOWN",
                          "diagnosis": str(run / "unknown-diagnosis.json")}, ensure_ascii=False))
        return EXIT_FAIL

    receipt_path = run / "execution-receipt.json"
    if not receipt_path.is_file():
        return _audit_fail(run, "receipt_missing", {})
    receipt = read_json(receipt_path)

    # 1) 封印：从 session 文件读取 p0-seal/custom 条目（不能只信 TS 内存值）
    seal = _find_seal(Path(args.session), receipt["parent_tool_call_id"])
    if seal is None:
        return _audit_fail(run, "seal_missing", {})
    if seal.get("data", {}).get("expectedParentResultHash") != receipt["expected_parent_result_sha256"]:
        return _audit_fail(run, "seal_hash_mismatch", {"seal": seal.get("data")})

    # 2) 宿主记录：nestedCalls 完整性 + 与回执动作序列一致
    host = json.loads(Path(args.host_record).read_text(encoding="utf-8"))
    nested = host.get("nestedCalls") or {}
    calls = nested.get("calls") or []
    if nested.get("complete") is not True:
        return _audit_fail(run, "nested_incomplete", {"nested": nested})
    archived_dir = wal["archived_task_dir"]
    plan = load_plan_quiet(root, receipt["unit"], archived_task_dir=archived_dir)
    if plan is None:
        return _audit_fail(run, "plan_missing", {"archived_task_dir": archived_dir})
    replay = replay_guards(plan, {a["action_id"]: a for a in receipt["actions"]},
                           [c["name"] for c in calls])
    if not replay["ok"]:
        return _audit_fail(run, "guard_replay_failed", replay)
    # F1（评审 A/B 共认 Critical）：机械对账通过 ≠ 成功链。失败/回退链走 CLOSED_FAILED
    # （终态、解锁、不签成功证书）；只有全绿链才配 SUCCEEDED。
    chain_green = receipt.get("terminal_reason") == "chain_ok" and all(
        a.get("ok") is True for a in receipt["actions"])

    # 3) raw 回执逐动作对账：文件字节哈希（完整性）与结果规范哈希（语义）分列核对
    subs: list[dict] = []
    for action in receipt["actions"]:
        result_sha = action.get("result_sha256")
        file_sha = action.get("raw_receipt_sha256")
        path = action.get("raw_receipt_path")
        if not path or not result_sha or not file_sha:
            return _audit_fail(run, "raw_receipt_missing", {"action": action.get("action_id")})
        p = Path(path)
        if not p.is_file() or file_sha256(p) != file_sha:
            return _audit_fail(run, "raw_receipt_tampered", {"path": path})
        body = read_json(p)
        if body.get("canonical_hash") != result_sha:
            return _audit_fail(run, "raw_receipt_hash_mismatch", {"path": path})
        child_id = str(action.get("child_tool_call_id") or "")
        ev_path = run / "evidence" / (re.sub(r"[^A-Za-z0-9._-]", "_", child_id) + ".json") if child_id else None
        if not ev_path or not ev_path.is_file():
            return _audit_fail(run, "evidence_missing", {"action": action.get("action_id"), "child": child_id})
        ev_body = read_json(ev_path)
        if ev_body.get("result_hash_observed") != result_sha:
            return _audit_fail(run, "evidence_hash_mismatch", {"action": action.get("action_id")})
        subs.append({
            "action_index": action.get("action_index"),
            "action_id": action.get("action_id"),
            "tool": action.get("tool"),
            "child_tool_call_id": action.get("child_tool_call_id"),
            "guard_result": action.get("guard_result"),
            "exit_code": action.get("exit_code"),
            "result_sha256": result_sha,
            "raw_receipt_sha256": file_sha,
            "cli_duration_ms": action.get("cli_duration_ms"),
            "host_duration_ms": action.get("host_duration_ms"),
            "evidence_origin": "raw-receipt",
        })

    # 4) 全树写集对账：P1/无已提交写要求零变化；P2 仅允许 WAL 已 COMMITTED 动作声明的路径集合
    manifest = read_json(run / "input-manifest.json")
    tree = _tree_entries(root, run, receipt["unit"])
    now_sha = sha256_hex(canonical_json(tree).encode("utf-8"))
    committed_tools = wal["committed_tools"]
    if not committed_tools:
        if now_sha != manifest["tree_sha256"]:
            return _audit_fail(run, "tree_changed", {"prepared": manifest["tree_sha256"], "now": now_sha})
    else:
        changed = _tree_diff(manifest["tree"], tree)
        allowed = authorized_write_set(
            root, receipt["unit"], committed_tools,
            deferred_meta=wal.get("deferred_meta"),
            archived_task_dir=archived_dir,
            pre_archive_files=wal.get("pre_archive_files"),
        )
        unexpected = [rel for rel in changed if not path_in_authorized_set(rel, allowed)]
        if unexpected:
            return _audit_fail(run, "unauthorized_tree_change",
                               {"unexpected": unexpected[:16], "allowed": sorted(allowed)})
        if "atlas_workflow_finish_archive" in committed_tools:
            if not archived_dir or not isinstance(wal.get("pre_archive_files"), dict):
                return _audit_fail(run, "archive_wal_incomplete", {"wal": wal})
            ok_cons, why_cons = verify_archive_conservation(
                root, receipt["unit"], archived_dir, wal["pre_archive_files"],
                wal.get("expected_task_sha256"), wal.get("expected_plan_sha256"),
            )
            if not ok_cons:
                return _audit_fail(run, "archive_conservation_failed", {"detail": why_cons})
            if has_mutating_write_actions(plan) and chain_green:
                ok_st, why_st, _, _ = _task_state_ok(
                    root, receipt["unit"], expected_statuses=("completed",),
                    archived_task_dir=archived_dir,
                )
                if not ok_st:
                    return _audit_fail(run, "archived_task_invalid", {"detail": why_st})

    # 5) 实际父结果哈希：session 中父 toolResult 的规范哈希 == 封印预期
    actual = _parent_result_hash(Path(args.session), receipt["parent_tool_call_id"])
    if actual is None:
        return _audit_fail(run, "parent_result_missing", {})
    if actual != receipt["expected_parent_result_sha256"]:
        return _audit_fail(run, "parent_result_hash_mismatch",
                           {"expected": receipt["expected_parent_result_sha256"], "actual": actual})

    status = "SUCCEEDED" if chain_green else "CLOSED_FAILED"
    cert_path = run / "certificate.json"
    cert = certificate_payload(
        run_id=receipt["run_id"], unit=receipt["unit"],
        plan_sha256=receipt["plan_sha256"], atlas_version=args.atlas_version,
        session_id=receipt["session_id"],
        parent_tool_call_id=receipt["parent_tool_call_id"],
        parent_tool_name=receipt.get("parent_tool_name", "atlas_continue"),
        expected_parent_result_sha256=receipt["expected_parent_result_sha256"],
        actual_parent_result_sha256=actual,
        host_nested_calls=nested,
        session_seal={"entry_id": seal.get("id"), "data": seal.get("data")},
        execution_receipt_sha256=file_sha256(receipt_path),
        input_manifest_sha256=receipt.get("input_manifest_sha256", ""),
        raw_receipts_manifest_sha256=manifest_hash(run, "raw-receipts"),
        git_calls_manifest_sha256=manifest_hash(run, "git-calls.jsonl"),
        substitutions=subs, status=status,
        wal_manifest_sha256=manifest_hash(run, "wal.jsonl") if wal_entries else None,
        archived_task_dir=archived_dir,
        plan_path_after_archive=f"{archived_dir}/continuation.json" if archived_dir else None,
        certificate_path=str(cert_path),
    )
    write_json_exclusive(cert_path, cert)
    print(json.dumps({"status": "ok", "verdict": status,
                      "certificate": str(cert_path),
                      "archived_task_dir": archived_dir}))
    return EXIT_OK


def _audit_fail(run: Path, reason: str, detail: dict) -> int:
    # F7（评审 B）：失败记录可重试覆盖（非防篡改面；防篡改锚在 session 封印与 raw 回执）
    (run / "audit-failure.json").write_text(
        json.dumps(audit_failure_payload(run, reason, detail), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({"status": "error", "verdict": "AUDIT_FAILED", "reason": reason}))
    return EXIT_FAIL


def _read_session_entries(path: Path) -> list[dict]:
    """session 落盘为 JSONL（逐行一个 entry）；逐行解析，坏行 fail-closed。"""
    entries: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


def _find_seal(session_path: Path, parent_tool_call_id: str) -> dict | None:
    for entry in _read_session_entries(session_path):
        if entry.get("customType") == "atlas-continuation-seal" and \
           entry.get("data", {}).get("parentToolCallId") == parent_tool_call_id:
            return entry
    return None


def _parent_result_hash(session_path: Path, parent_tool_call_id: str) -> str | None:
    from _support.guarded_continuation import canonical_result_hash
    for entry in _read_session_entries(session_path):
        msg = entry.get("message") or {}
        if msg.get("role") == "toolResult" and msg.get("toolCallId") == parent_tool_call_id:
            return canonical_result_hash({
                "content": msg.get("content"),
                "details": msg.get("details"),
                "structuredContent": msg.get("structuredContent"),
                "isError": msg.get("isError"),
            })
    return None


def load_plan_quiet(root: Path, unit: str, archived_task_dir: str | None = None):
    try:
        return load_plan(root, unit, archived_task_dir=archived_task_dir)
    except PlanError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas_continue")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("preflight")
    p_pre.add_argument("--root", required=True)
    p_pre.add_argument("--unit", required=True)

    for name in ("prepare", "verify", "record", "audit", "lock-hold", "diagnose-unknown"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True)
        p.add_argument("--unit", required=True)
        p.add_argument("--run-dir", required=True)
        if name == "verify":
            p.add_argument("--phase", default="pre-action")
        if name == "record":
            p.add_argument("--receipt-json", required=True)
        if name == "audit":
            p.add_argument("--session", required=True, help="session .jsonl 落盘文件")
            p.add_argument("--host-record", required=True)
            p.add_argument("--atlas-version", default="poc")

    for name in ("write-deferred", "write-commit", "write-archive"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True)
        p.add_argument("--unit", required=True)
        p.add_argument("--run-dir", required=True)
        p.add_argument("--action-index", type=int, required=True)
        p.add_argument("--action-id", required=True)

    p_wc = sub.add_parser("wal-commit")
    p_wc.add_argument("--root", required=True)
    p_wc.add_argument("--unit", required=True)
    p_wc.add_argument("--run-dir", required=True)
    p_wc.add_argument("--action-index", type=int, required=True)
    p_wc.add_argument("--action-id", required=True)
    p_wc.add_argument("--tool", required=True)
    p_wc.add_argument("--detail-json", default="")

    p_wu = sub.add_parser("wal-mark-unknown")
    p_wu.add_argument("--root", required=True)
    p_wu.add_argument("--unit", required=True)
    p_wu.add_argument("--run-dir", required=True)
    p_wu.add_argument("--action-index", type=int, default=0)
    p_wu.add_argument("--action-id", default="unknown")
    p_wu.add_argument("--tool", default="atlas_continue")
    p_wu.add_argument("--reason", required=True)

    args = parser.parse_args(argv)
    fn = {
        "preflight": cmd_preflight,
        "prepare": cmd_prepare,
        "verify": cmd_verify,
        "record": cmd_record,
        "audit": cmd_audit,
        "lock-hold": cmd_lock_hold,
        "diagnose-unknown": cmd_diagnose_unknown,
        "write-deferred": cmd_write_deferred,
        "write-commit": cmd_write_commit,
        "write-archive": cmd_write_archive,
        "wal-commit": cmd_wal_commit,
        "wal-mark-unknown": cmd_wal_mark_unknown,
    }[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
