#!/usr/bin/env python3
"""Atlas Guarded Continuation CLI（GDR PoC P1）。

子命令（全部只读面，除白名单运行证据外零写盘；Python 统一经净化启动器 -I -B 调用）：
  prepare  校验计划/任务态/输入闭集，生成 input-manifest.json（运行前全树快照）
  verify   重验计划哈希 + 任务态 + 全树快照未变（动作前 / record 前调用）
  record   原子写 execution-receipt.json（RECORDED；父工具返回前调用）
  audit    agent_settled 兜底后的最终审计：宿主记录 + raw 回执 + 封印 + guard 重放
           + 全树零变化 ⇒ certificate.json（SUCCEEDED）或 audit-failure.json

退出码封闭：0 = 通过；2 = 契约/环境失败（fail-closed，绝不吞错为 exit 0）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.guarded_continuation import (  # noqa: E402
    CONTINUATIONS_DIRNAME,
    PlanError,
    canonical_json,
    file_sha256,
    isolated_marker_path,
    load_plan,
    manifest_hash,
    read_json,
    replay_guards,
    run_dir,
    sha256_hex,
    write_exclusive,
    write_json_exclusive,
)

EXIT_OK = 0
EXIT_FAIL = 2

TREE_EXCLUDE_DIRS = {".git"}
# 全树对账排除面（§5.4）：.git、本次 run 目录白名单、精确隔离标记路径。
def _tree_entries(root: Path, run: Path | None, unit: str | None) -> dict:
    """全树内容哈希（os.walk，3.9+ 兼容；净化环境无 Path.walk[3.12+] 依赖）。"""
    import os
    exclude_files = set()
    if unit:
        exclude_files.add(str(isolated_marker_path(root, unit).relative_to(root)))
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
            rel = str(Path(dirpath, name).relative_to(root))
            if rel in exclude_files:
                continue
            try:
                entries[rel] = file_sha256(Path(dirpath, name))
            except OSError:
                entries[rel] = "unreadable"
    return entries


def _load_run_state(run: Path) -> dict:
    receipt = run / "execution-receipt.json"
    if not receipt.is_file():
        return {}
    return read_json(receipt)


def _task_state_ok(root: Path, unit: str) -> tuple[bool, str]:
    task_json = root / ".atlas" / "tasks" / unit / "task.json"
    if task_json.is_symlink() or not task_json.is_file():
        return False, f"task.json 缺失：{task_json}"
    try:
        task = read_json(task_json)
    except json.JSONDecodeError as e:
        return False, f"task.json 不可解析：{e}"
    if task.get("id") != unit:
        return False, f"task.id 与 unit 不一致：{task.get('id')!r}"
    if task.get("status") != "in_progress":
        return False, f"任务状态须为 in_progress，got {task.get('status')!r}"
    return True, ""


def cmd_prepare(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    try:
        plan = load_plan(root, args.unit)
    except PlanError as e:
        print(json.dumps({"status": "error", "cause": "plan", "detail": str(e)}))
        return EXIT_FAIL
    ok, why = _task_state_ok(root, args.unit)
    if not ok:
        print(json.dumps({"status": "error", "cause": "task_state", "detail": why}))
        return EXIT_FAIL
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
    try:
        plan = load_plan(root, args.unit)
    except PlanError as e:
        print(json.dumps({"status": "error", "cause": "plan", "detail": str(e)}))
        return EXIT_FAIL
    manifest_path = run / "input-manifest.json"
    if not manifest_path.is_file():
        print(json.dumps({"status": "error", "cause": "manifest", "detail": "prepare 缺失"}))
        return EXIT_FAIL
    manifest = read_json(manifest_path)
    if manifest["plan_sha256"] != plan["plan_sha256"]:
        print(json.dumps({"status": "error", "cause": "plan_stale",
                          "detail": "计划文件在 prepare 后发生变化"}))
        return EXIT_FAIL
    ok, why = _task_state_ok(root, args.unit)
    if not ok:
        print(json.dumps({"status": "error", "cause": "task_state", "detail": why}))
        return EXIT_FAIL
    tree = _tree_entries(root, run, args.unit)
    now_sha = sha256_hex(canonical_json(tree).encode("utf-8"))
    if now_sha != manifest["tree_sha256"]:
        changed = _tree_diff(manifest["tree"], tree)
        print(json.dumps({"status": "error", "cause": "tree_changed",
                          "detail": f"{len(changed)} paths changed", "sample": changed[:8]}))
        return EXIT_FAIL
    print(json.dumps({"status": "ok", "phase": args.phase or "pre-action"}))
    return EXIT_OK


def _tree_diff(old: dict, new: dict) -> list[str]:
    changed = [k for k in set(old) | set(new) if old.get(k) != new.get(k)]
    return sorted(changed)


def cmd_record(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    payload = json.loads(Path(args.receipt_json).read_text(encoding="utf-8"))
    required = {"run_id", "unit", "plan_sha256", "status", "actions", "terminal_reason",
                "expected_parent_result_sha256", "session_id", "parent_tool_call_id"}
    missing = required - set(payload)
    if missing:
        print(json.dumps({"status": "error", "cause": "receipt_schema", "detail": f"缺字段 {sorted(missing)}"}))
        return EXIT_FAIL
    if payload["run_id"] != args.run_dir or payload["unit"] != args.unit:
        print(json.dumps({"status": "error", "cause": "receipt_mismatch"}))
        return EXIT_FAIL
    receipt_path = run / "execution-receipt.json"
    sha = write_json_exclusive(receipt_path, payload)
    print(json.dumps({"status": "ok", "execution_receipt_sha256": sha}))
    return EXIT_OK


def cmd_audit(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    run = run_dir(root, args.run_dir)
    fail: dict = {}

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
    plan = load_plan_quiet(root, receipt["unit"])
    if plan is None:
        return _audit_fail(run, "plan_missing", {})
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
        # F5-A（评审 A）：supplemental evidence 交叉核对（两层对账的第二层；
        # 缺失/不一致即 AUDIT_FAILED——此前 evidence 层只写不读，形同虚设）
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

    # 4) 全树零变化：运行后快照必须与 prepare 一致
    manifest = read_json(run / "input-manifest.json")
    tree = _tree_entries(root, run, receipt["unit"])
    now_sha = sha256_hex(canonical_json(tree).encode("utf-8"))
    if now_sha != manifest["tree_sha256"]:
        return _audit_fail(run, "tree_changed", {"prepared": manifest["tree_sha256"], "now": now_sha})

    # 5) 实际父结果哈希：session 中父 toolResult 的规范哈希 == 封印预期
    actual = _parent_result_hash(Path(args.session), receipt["parent_tool_call_id"])
    if actual is None:
        return _audit_fail(run, "parent_result_missing", {})
    if actual != receipt["expected_parent_result_sha256"]:
        return _audit_fail(run, "parent_result_hash_mismatch",
                           {"expected": receipt["expected_parent_result_sha256"], "actual": actual})

    from _support.guarded_continuation import certificate_payload
    status = "SUCCEEDED" if chain_green else "CLOSED_FAILED"
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
    )
    write_json_exclusive(run / "certificate.json", cert)
    print(json.dumps({"status": "ok", "verdict": status,
                      "certificate": str(run / "certificate.json")}))
    return EXIT_OK


def _audit_fail(run: Path, reason: str, detail: dict) -> int:
    from _support.guarded_continuation import audit_failure_payload
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


def load_plan_quiet(root: Path, unit: str):
    try:
        return load_plan(root, unit)
    except PlanError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas_continue")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "verify", "record", "audit"):
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
    args = parser.parse_args(argv)
    fn = {"prepare": cmd_prepare, "verify": cmd_verify,
          "record": cmd_record, "audit": cmd_audit}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
