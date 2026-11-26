#!/usr/bin/env python3
"""Guarded Continuation（GDR PoC P1）回归测试。

三层判据（与 test_apply_wiring.py 同构：形态判据 + 执行级判据，bun 缺席显式 skip）：
  1. 计划契约 fail-closed：schema/unit/作者/封闭枚举/参数注入/guard 前向与重复引用/上限；
  2. atlas_continue CLI 四子命令：全树快照、两阶段审计、篡改必红（raw 回执文件字节面 +
     封印 + nestedCalls 完整性 + guard 重放 + 全树零变化）；
  3. bun 假宿主全环：ARMED → 治理默认拒绝直调 → 父工具嵌套双只读动作 → 封印 →
     agent_settled 审计 → certificate → 解锁（自含冻结净化启动器 + 只读 git 包装器）。
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support import guarded_continuation as gc  # noqa: E402

CONTINUE_CLI = PKG_ROOT / "scripts" / "atlas_continue.py"


def _run_cli(root: Path, unit: str, run_id: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(CONTINUE_CLI), *args,
         "--root", str(root), "--unit", unit, "--run-dir", run_id],
        capture_output=True, text=True, timeout=120,
    )


def _make_plan(root: Path, unit: str = "TEST-1") -> Path:
    task_dir = root / ".atlas" / "tasks" / unit
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(
        json.dumps({"id": unit, "status": "in_progress"}), encoding="utf-8")
    plan = task_dir / "continuation.json"
    plan.write_text(json.dumps({
        "schema": 1, "unit": unit, "author": "human",
        "actions": [
            {"id": "snapshot", "tool": "atlas_workflow_progress",
             "args": {"unit": unit}, "guard": {"kind": "always"}},
            {"id": "ledger", "tool": "atlas_workflow_status",
             "args": {"unit": unit},
             "guard": {"kind": "all_of", "refs": ["snapshot.exit_code", "snapshot.json_ok"]}},
        ],
    }, indent=2), encoding="utf-8")
    return plan


def _make_project() -> Path:
    root = Path(tempfile.mkdtemp(prefix="gc-test-"))
    (root / ".git").mkdir()  # 全树快照排除面只需要目录存在；CLI 不真调 git
    (root / "site.txt").write_text("hello\n", encoding="utf-8")
    _make_plan(root)
    return root


# ────────────────────────────────────────────────────────────── 1. 计划契约
def test_plan_contract_rejections() -> None:
    """fail-closed 面：schema/unit/作者/封闭枚举/参数注入/guard 前向与重复/上限。"""
    root = Path(tempfile.mkdtemp(prefix="gc-plan-"))
    base = json.loads(_make_plan(root).read_text(encoding="utf-8"))

    def attempt(mutate) -> None:
        plan = json.loads(json.dumps(base))
        mutate(plan)
        p = root / ".atlas" / "tasks" / "TEST-1" / "continuation.json"
        p.write_text(json.dumps(plan), encoding="utf-8")
        with pytest.raises(gc.PlanError):
            gc.load_plan(root, "TEST-1")

    attempt(lambda p: p.__setitem__("schema", 2))
    attempt(lambda p: p.__setitem__("unit", "OTHER"))
    attempt(lambda p: p.__setitem__("author", "model"))
    attempt(lambda p: p["actions"][0].__setitem__("tool", "atlas_workflow_finish"))
    attempt(lambda p: p["actions"][0].__setitem__("args", {"unit": "TEST-1", "cmd": "rm"}))
    attempt(lambda p: p["actions"][1]["guard"]["refs"].insert(0, "ledger.exit_code"))  # 前向/自引用
    attempt(lambda p: p["actions"][1].__setitem__("id", "snapshot"))  # 重复 ID
    attempt(lambda p: p.__setitem__("actions", [
        {"id": f"a{i}", "tool": "atlas_workflow_progress", "args": {"unit": "TEST-1"},
         "guard": {"kind": "always"}} for i in range(9)]))  # 超 8 动作
    attempt(lambda p: p["actions"][0]["guard"].__setitem__("kind", "when_model_says"))  # 未知 guard
    # 正本必须可加载
    p = root / ".atlas" / "tasks" / "TEST-1" / "continuation.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    loaded = gc.load_plan(root, "TEST-1")
    assert loaded["plan_sha256"] == gc.sha256_hex(p.read_bytes())


def test_guard_replay_zero_suffix() -> None:
    """guard=false / 动作失败后必须零宿主调用；多出的调用必被重放抓红。"""
    plan = gc.load_plan(Path(tempfile.mkdtemp(prefix="gc-rp-")) / "nonexist", "X") \
        if False else None
    plan_doc = {"actions": [
        {"id": "a", "tool": "atlas_workflow_progress", "args": {"unit": "U"},
         "guard": {"kind": "always"}},
        {"id": "b", "tool": "atlas_workflow_status", "args": {"unit": "U"},
         "guard": {"kind": "all_of", "refs": ["a.exit_code"]}},
    ]}
    ok_obs = {"a": {"ok": True, "exit_code": 0, "json_ok": True}}
    good = gc.replay_guards(plan_doc, ok_obs, ["atlas_workflow_progress", "atlas_workflow_status"])
    assert good["ok"] is True
    # a 失败 ⇒ b 零调用；宿主却调了两个 ⇒ 抓红
    bad = gc.replay_guards(plan_doc, {"a": {"ok": False, "exit_code": 1, "json_ok": True}},
                           ["atlas_workflow_progress", "atlas_workflow_status"])
    assert bad["ok"] is False
    # 前缀错位（跳过 a 直接调 b）
    skip = gc.replay_guards(plan_doc, ok_obs, ["atlas_workflow_status"])
    assert skip["ok"] is False


def test_canonical_hash_null_semantics() -> None:
    """null/undefined 同义缺席 + 键排序（TS/Python 双侧镜像的钉子）。"""
    a = gc.canonical_json({"b": 1, "a": 2, "c": None})
    assert a == '{"a":2,"b":1}'
    assert gc.canonical_json({"x": [{"k": None, "v": "s"}]}) == '{"x":[{"v":"s"}]}'
    result = {"content": [{"type": "text", "text": "ok"}],
              "details": {"unit": "U", "fail_reason": None}, "isError": False}
    h = gc.canonical_result_hash(result)
    assert h == gc.canonical_result_hash({k: v for k, v in result.items()})
    # 已知向量钉子（防双侧漂移）：固定形状哈希必须稳定
    assert h == gc.sha256_hex(gc.canonical_json({
        "content": [{"type": "text", "text": "ok"}],
        "details": {"unit": "U"}, "isError": False,
    }).encode("utf-8"))


def test_write_exclusive_is_immutable() -> None:
    """O_EXCL：重复写同一回执路径必须炸（防覆盖前序回执/并发运行互踩）。"""
    root = Path(tempfile.mkdtemp(prefix="gc-oexcl-"))
    p = root / "x.json"
    gc.write_json_exclusive(p, {"a": 1})
    with pytest.raises(FileExistsError):
        gc.write_json_exclusive(p, {"a": 2})


# ────────────────────────────────────────────────────────────── 2. CLI 四子命令
def _build_evidence(root: Path, run_id: str, git_repo: bool = False) -> dict:
    """构造一条完整合规证据链（模拟 TS 侧产物），返回 fixture 上下文。"""
    run = gc.run_dir(root, run_id)
    child_a = {"content": [{"type": "text", "text": "progress ok"}],
               "details": {"tool": "atlas_workflow_progress", "unit": "TEST-1",
                           "exit_code": 0, "json_ok": True}, "isError": False}
    child_b = {"content": [{"type": "text", "text": "status ok"}],
               "details": {"tool": "atlas_workflow_status", "unit": "TEST-1",
                           "exit_code": 0, "json_ok": True}, "isError": False}
    h1, f1 = gc.write_raw_receipt(run, 1, child_a, {"toolCallId": "callX/1"})
    h2, f2 = gc.write_raw_receipt(run, 2, child_b, {"toolCallId": "callX/2"})
    # supplemental evidence（F5-A：两层对账第二层，audit 现在会核对）
    for cid, h in (("callX/1", h1), ("callX/2", h2)):
        ev = {"kind": "supplemental", "child_tool_call_id": cid,
              "result_hash_observed": h, "observed_at": "2026-01-01T00:00:00Z"}
        (run / "evidence" / f"{cid.replace('/', '_')}.json").write_text(
            json.dumps(ev, indent=2), encoding="utf-8")
    parent = {"content": [{"type": "text", "text": "parent ok: 2 actions"}],
              "details": {"unit": "TEST-1", "actions_ok": True}, "isError": False}
    plan_sha = gc.sha256_hex(
        (root / ".atlas" / "tasks" / "TEST-1" / "continuation.json").read_bytes())
    receipt = {
        "run_id": run_id, "unit": "TEST-1", "plan_sha256": plan_sha,
        "status": "RECORDED", "terminal_reason": "chain_ok",
        "session_id": "sess-t", "parent_tool_call_id": "callX",
        "parent_tool_name": "atlas_continue",
        "expected_parent_result_sha256": gc.canonical_result_hash(parent),
        "input_manifest_sha256": "m" * 64,
        "actions": [
            {"action_index": 1, "action_id": "snapshot", "tool": "atlas_workflow_progress",
             "child_tool_call_id": "callX/1",
             "guard_result": True, "exit_code": 0, "json_ok": True, "ok": True,
             "cli_duration_ms": 3, "host_duration_ms": 4,
             "result_sha256": h1, "raw_receipt_sha256": f1,
             "raw_receipt_path": str(gc.raw_receipt_path(run, 1, h1[:16]))},
            {"action_index": 2, "action_id": "ledger", "tool": "atlas_workflow_status",
             "child_tool_call_id": "callX/2",
             "guard_result": True, "exit_code": 0, "json_ok": True, "ok": True,
             "cli_duration_ms": 2, "host_duration_ms": 2,
             "result_sha256": h2, "raw_receipt_sha256": f2,
             "raw_receipt_path": str(gc.raw_receipt_path(run, 2, h2[:16]))},
        ],
    }
    # execution-receipt.json 由 record CLI 写（O_EXCL）；这里只落 payload 供其消费
    seal = {"type": "custom", "customType": "atlas-continuation-seal", "id": "e-seal",
            "parentId": "e0", "data": {"runId": run_id, "sessionId": "sess-t",
                                       "parentToolCallId": "callX",
                                       "expectedParentResultHash": receipt["expected_parent_result_sha256"]}}
    msg = {"type": "message", "id": "e1", "parentId": "e-seal",
           "message": {"role": "toolResult", "toolCallId": "callX", "toolName": "atlas_continue",
                       "content": parent["content"], "details": parent["details"],
                       "isError": False,
                       "nestedCalls": {"calls": [
                           {"id": "callX/1", "name": "atlas_workflow_progress", "status": "ok", "durationMs": 4},
                           {"id": "callX/2", "name": "atlas_workflow_status", "status": "ok", "durationMs": 2}],
                           "complete": True}}}
    # session 文件必须落仓外（真实 Pi session 在 ~/.pi 下；仓内会咬全树零变化门）
    session = Path(tempfile.mkdtemp(prefix="gc-sess-")) / "session.jsonl"
    session.write_text(json.dumps(seal) + "\n" + json.dumps(msg) + "\n", encoding="utf-8")
    host = {"parent_tool_call_id": "callX",
            "nestedCalls": json.loads(msg["message"]["nestedCalls"] and json.dumps(msg["message"]["nestedCalls"])),
            "actual_parent_result_sha256": receipt["expected_parent_result_sha256"],
            "host_duration_ms": 9}
    host_record = run / "host-record.json"
    host_record.write_text(json.dumps(host), encoding="utf-8")
    return {"run": run, "session": session, "host_record": host_record, "receipt": receipt}


def test_cli_full_chain_and_tamper_negative() -> None:
    """正向四子命令 → SUCCEEDED 证书；篡改 raw 回执字节 → AUDIT_FAILED 必红。"""
    root = _make_project()
    run_id = "gc-t1"
    prep = _run_cli(root, "TEST-1", run_id, "prepare")
    assert prep.returncode == 0, prep.stderr
    ev = _build_evidence(root, run_id)
    rec = _run_cli(root, "TEST-1", run_id, "record",
                   "--receipt-json", str(ev["run"] / "receipt-payload-tmp.json")) \
        if False else None
    # record：从合规 payload 写入（手工构造 payload 文件）
    payload_path = ev["run"] / "receipt-payload.json"
    payload_path.write_text(json.dumps(ev["receipt"], ensure_ascii=False, indent=2), encoding="utf-8")
    rec = _run_cli(root, "TEST-1", run_id, "record", "--receipt-json", str(payload_path))
    assert rec.returncode == 0, rec.stderr
    audit = _run_cli(root, "TEST-1", run_id, "audit",
                     "--session", str(ev["session"]), "--host-record", str(ev["host_record"]))
    assert audit.returncode == 0, audit.stdout + audit.stderr
    cert = json.loads((ev["run"] / "certificate.json").read_text(encoding="utf-8"))
    assert cert["status"] == "SUCCEEDED"
    assert cert["host_nested_calls_complete"] is True
    assert cert["expected_parent_result_sha256"] == cert["actual_parent_result_sha256"]
    assert [s["tool"] for s in cert["substitutions"]] == [
        "atlas_workflow_progress", "atlas_workflow_status"]

    # 负向：篡改 raw 回执文件字节 ⇒ 重审计必红（同 run 不可重审计，换 run 重建）
    root2 = _make_project()
    prep2 = _run_cli(root2, "TEST-1", "gc-t2", "prepare")
    assert prep2.returncode == 0
    ev2 = _build_evidence(root2, "gc-t2")
    receipts = sorted((ev2["run"] / "raw-receipts").glob("1-*.json"))
    body = json.loads(receipts[0].read_text(encoding="utf-8"))
    body["result"]["details"]["exit_code"] = 99
    receipts[0].write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload2 = ev2["run"] / "receipt-payload.json"
    payload2.write_text(json.dumps(ev2["receipt"], ensure_ascii=False, indent=2), encoding="utf-8")
    assert _run_cli(root2, "TEST-1", "gc-t2", "record",
                    "--receipt-json", str(payload2)).returncode == 0
    audit2 = _run_cli(root2, "TEST-1", "gc-t2", "audit",
                      "--session", str(ev2["session"]), "--host-record", str(ev2["host_record"]))
    assert audit2.returncode == 2
    assert json.loads((ev2["run"] / "audit-failure.json").read_text(encoding="utf-8"))["reason"] == \
        "raw_receipt_tampered"


def test_cli_failed_chain_gets_closed_failed_not_succeeded() -> None:
    """评审 F1（Critical 伪成功）反例：动作 1 失败 ⇒ guard 前移短路、零后缀合规，
    机械对账全部通过，但证书必须是 CLOSED_FAILED——与成功链可区分，绝不签 SUCCEEDED。"""
    root = _make_project()
    run_id = "gc-f1"
    assert _run_cli(root, "TEST-1", run_id, "prepare").returncode == 0
    run = gc.run_dir(root, run_id)
    # 动作 1：progress 失败（exit 1）
    failed_child = {"content": [{"type": "text", "text": "progress FAILED"}],
                    "details": {"tool": "atlas_workflow_progress", "unit": "TEST-1",
                                "exit_code": 1, "json_ok": True}, "isError": True}
    h1, f1 = gc.write_raw_receipt(run, 1, failed_child, {"toolCallId": "callX/1"})
    ev1 = {"kind": "supplemental", "child_tool_call_id": "callX/1",
           "result_hash_observed": h1, "observed_at": "2026-01-01T00:00:00Z"}
    (run / "evidence" / "callX_1.json").write_text(json.dumps(ev1, indent=2), encoding="utf-8")
    parent = {"content": [{"type": "text", "text": "atlas_continue FAILED unit=TEST-1: action snapshot isError"}],
              "details": {"unit": "TEST-1", "actions_ok": False,
                          "fail_reason": "action snapshot isError"}, "isError": True}
    receipt = {
        "run_id": run_id, "unit": "TEST-1",
        "plan_sha256": gc.sha256_hex(
            (root / ".atlas" / "tasks" / "TEST-1" / "continuation.json").read_bytes()),
        "status": "RECORDED", "terminal_reason": "action snapshot isError",
        "session_id": "sess-t", "parent_tool_call_id": "callX",
        "parent_tool_name": "atlas_continue",
        "expected_parent_result_sha256": gc.canonical_result_hash(parent),
        "input_manifest_sha256": "m" * 64,
        "actions": [
            {"action_index": 1, "action_id": "snapshot", "tool": "atlas_workflow_progress",
             "child_tool_call_id": "callX/1",
             "guard_result": True, "exit_code": 1, "json_ok": True, "ok": False,
             "cli_duration_ms": 3, "host_duration_ms": 4,
             "result_sha256": h1, "raw_receipt_sha256": f1,
             "raw_receipt_path": str(gc.raw_receipt_path(run, 1, h1[:16]))},
        ],
    }
    payload = run / "receipt-payload.json"
    payload.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    assert _run_cli(root, "TEST-1", run_id, "record", "--receipt-json", str(payload)).returncode == 0
    seal = {"type": "custom", "customType": "atlas-continuation-seal", "id": "e-seal",
            "parentId": "e0", "data": {"runId": run_id, "sessionId": "sess-t",
                                       "parentToolCallId": "callX",
                                       "expectedParentResultHash": receipt["expected_parent_result_sha256"]}}
    msg = {"type": "message", "id": "e1", "parentId": "e-seal",
           "message": {"role": "toolResult", "toolCallId": "callX", "toolName": "atlas_continue",
                       "content": parent["content"], "details": parent["details"],
                       "isError": True,
                       "nestedCalls": {"calls": [
                           {"id": "callX/1", "name": "atlas_workflow_progress",
                            "status": "error", "durationMs": 4}], "complete": True}}}
    session = Path(tempfile.mkdtemp(prefix="gc-sess-")) / "session.jsonl"
    session.write_text(json.dumps(seal) + "\n" + json.dumps(msg) + "\n", encoding="utf-8")
    host_record = run / "host-record.json"
    host_record.write_text(json.dumps({
        "parent_tool_call_id": "callX", "nestedCalls": json.loads(_nested_json()) if False else msg["message"]["nestedCalls"],
        "actual_parent_result_sha256": receipt["expected_parent_result_sha256"],
        "host_duration_ms": 9}), encoding="utf-8")

    a = _run_cli(root, "TEST-1", run_id, "audit",
                 "--session", str(session), "--host-record", str(host_record))
    assert a.returncode == 0, a.stdout + a.stderr
    verdict = json.loads(a.stdout)["verdict"]
    assert verdict == "CLOSED_FAILED"
    cert = json.loads((run / "certificate.json").read_text(encoding="utf-8"))
    assert cert["status"] == "CLOSED_FAILED"


def _nested_json():
    return "{}"


def test_cli_verify_bites_tree_change() -> None:
    """prepare 后任何树内文件变化 ⇒ verify 拒收（全树零变化门）。"""
    root = _make_project()
    assert _run_cli(root, "TEST-1", "gc-v1", "prepare").returncode == 0
    (root / "site.txt").write_text("changed\n", encoding="utf-8")
    v = _run_cli(root, "TEST-1", "gc-v1", "verify", "--phase", "pre-action")
    assert v.returncode == 2
    assert json.loads(v.stdout)["cause"] == "tree_changed"


def test_cli_audit_rejects_missing_seal_and_incomplete_nested() -> None:
    """封印缺失 / nestedCalls 不完整 ⇒ fail-closed 两个独立红点。"""
    root = _make_project()
    assert _run_cli(root, "TEST-1", "gc-s1", "prepare").returncode == 0
    ev = _build_evidence(root, "gc-s1")
    # 封印缺失：session 只留 toolResult
    lines = ev["session"].read_text(encoding="utf-8").splitlines()
    ev["session"].write_text(lines[1] + "\n", encoding="utf-8")
    payload = ev["run"] / "receipt-payload.json"
    payload.write_text(json.dumps(ev["receipt"], ensure_ascii=False, indent=2), encoding="utf-8")
    assert _run_cli(root, "TEST-1", "gc-s1", "record", "--receipt-json", str(payload)).returncode == 0
    a = _run_cli(root, "TEST-1", "gc-s1", "audit",
                 "--session", str(ev["session"]), "--host-record", str(ev["host_record"]))
    assert a.returncode == 2
    assert json.loads((ev["run"] / "audit-failure.json").read_text(encoding="utf-8"))["reason"] == \
        "seal_missing"

    # nested 不完整：complete=false
    root2 = _make_project()
    assert _run_cli(root2, "TEST-1", "gc-s2", "prepare").returncode == 0
    ev2 = _build_evidence(root2, "gc-s2")
    host = json.loads(ev2["host_record"].read_text(encoding="utf-8"))
    host["nestedCalls"]["complete"] = False
    ev2["host_record"].write_text(json.dumps(host), encoding="utf-8")
    payload2 = ev2["run"] / "receipt-payload.json"
    payload2.write_text(json.dumps(ev2["receipt"], ensure_ascii=False, indent=2), encoding="utf-8")
    assert _run_cli(root2, "TEST-1", "gc-s2", "record", "--receipt-json", str(payload2)).returncode == 0
    a2 = _run_cli(root2, "TEST-1", "gc-s2", "audit",
                  "--session", str(ev2["session"]), "--host-record", str(ev2["host_record"]))
    assert a2.returncode == 2
    assert json.loads((ev2["run"] / "audit-failure.json").read_text(encoding="utf-8"))["reason"] == \
        "nested_incomplete"


# ────────────────────────────────────────────────────────────── 3. bun 假宿主全环
_LAUNCHER_TPL = """#!/bin/sh
set -u
GC_LOG="$1"; SCRIPT="$2"; shift 2
[ -n "$GC_LOG" ] || exit 126
[ -f "$SCRIPT" ] || { echo "launcher: script missing" >&2; exit 126; }
GITDIR=$(dirname "$(command -v git)")
export PATH="__LAUNCHER_BIN__:$GITDIR:/usr/bin:/bin"
exec env -i PATH="$PATH" HOME="$HOME" LANG="${LC_ALL:-en_US.UTF-8}" \\
  GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_OPTIONAL_LOCKS=0 \\
  ATLAS_GC_LOG="$GC_LOG" \\
  {python} -I -B "$SCRIPT" "$@"
"""

_WRAPPER_TPL = """#!/bin/sh
set -u
GC_LOG=${ATLAS_GC_LOG:-}
argv_sha=$(printf '%s\\n' "$*" | shasum -a 256 | cut -d' ' -f1)
deny() {
  printf '{"argv_sha256":"%s","rc":126}\\n' "$argv_sha" >> "$GC_LOG" 2>/dev/null
  echo "atlas-readonly-git: template not allowlisted: $*" >&2
  exit 126
}
for a in "$@"; do
  case "$a" in
    -c|--config-env|-C|--exec-path|--output|--ext-diff|--textconv) deny "$@" ;;
    *";"*|*"|"*) deny "$@" ;;
  esac
done
a1=${1:-}; a2=${2:-}; a3=${3:-}; a4=${4:-}; a5=${5:-}
case "$#|$a1|$a2|$a3|$a4|$a5" in
  '5|diff|--cached|--name-only|--diff-filter=ACDMRT|-z') : ;;
  '3|rev-parse|--verify|HEAD||') : ;;
  *) deny "$@" ;;
esac
REAL_GIT="${ATLAS_GC_REAL_GIT:-/usr/bin/git}"
"$REAL_GIT" "$@"
rc=$?
printf '{"argv_sha256":"%s","rc":%d}\\n' "$argv_sha" "$rc" >> "$GC_LOG"
exit $rc
"""

_PI_GC_DRIVER = r"""
// 由 test_gc_bun_fake_host_full_loop 生成：假宿主 + 真扩展，全环走
// approve → 治理默认拒绝直调 → 父工具嵌套双只读动作 → 封印 → settled 审计 → 证书。
import { mkdirSync, writeFileSync, copyFileSync, existsSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { execSync } from "node:child_process";
import { join } from "node:path";
import ext from "__PI_TS__";
const SCENARIO = "__SCENARIO__"; // settled | shutdown-only
const PLAN_FLIP = __PLAN_FLIP__; // status-first 计划形态

const handlers = {}; const tools = []; const commands = {};
const appended = []; const notified = [];
const pi = {
  registerTool: (t) => tools.push(t),
  registerCommand: (n, def) => { commands[n] = def.handler; },
  on: (ev, fn) => { (handlers[ev] ||= []).push(fn); },
  appendEntry: (customType, data) => appended.push({ customType, data }),
  exec: async () => ({ code: 0, stdout: "", stderr: "" }),
  getAllTools: () => tools, getActiveTools: () => [], setActiveTools: () => {},
};
ext(pi);

const root = mkdtempSync(join("/tmp", "gc-bun-"));
execSync(`git init -q ${root} && git -C ${root} config user.email t@t && git -C ${root} config user.name t`);
mkdirSync(join(root, ".atlas", "scripts"), { recursive: true });
mkdirSync(join(root, ".atlas", "tasks", "TEST-1"), { recursive: true });
mkdirSync(join(root, "product", "prd"), { recursive: true });
mkdirSync(join(root, ".atlas", "spec", "structure"), { recursive: true });
copyFileSync("__PKG__/scripts/atlas_continue.py", join(root, ".atlas", "scripts", "atlas_continue.py"));
copyFileSync("__PKG__/scripts/atlas_workflow.py", join(root, ".atlas", "scripts", "atlas_workflow.py"));
execSync(`cp -R __PKG__/_support/. ${join(root, ".atlas", "_support")}`);
execSync(`rm -rf ${join(root, ".atlas", "_support", "__pycache__")}`);
writeFileSync(join(root, "product", "prd", "prd.md"), "# prd\n");
writeFileSync(join(root, "site.txt"), "hello\n");
writeFileSync(join(root, ".atlas", "tasks", "TEST-1", "task.json"), JSON.stringify({ id: "TEST-1", status: "in_progress" }));
const actions = PLAN_FLIP
  ? [ { id: "ledger", tool: "atlas_workflow_status", args: { unit: "TEST-1" }, guard: { kind: "always" } },
      { id: "snapshot", tool: "atlas_workflow_progress", args: { unit: "TEST-1" },
        guard: { kind: "all_of", refs: ["ledger.exit_code", "ledger.json_ok"] } } ]
  : [ { id: "snapshot", tool: "atlas_workflow_progress", args: { unit: "TEST-1" }, guard: { kind: "always" } },
      { id: "ledger", tool: "atlas_workflow_status", args: { unit: "TEST-1" },
        guard: { kind: "all_of", refs: ["snapshot.exit_code", "snapshot.json_ok"] } } ];
writeFileSync(join(root, ".atlas", "tasks", "TEST-1", "continuation.json"), JSON.stringify({
  schema: 1, unit: "TEST-1", author: "human", actions }));
execSync(`git -C ${root} add -A && git -C ${root} commit -qm init`);

const sessionFile = join(root, "..", `gc-bun-session-${Date.now()}.jsonl`);
const branch = [];
let nested = 0;
const ctx = {
  cwd: root, hasUI: true,
  ui: { confirm: async () => true, notify: (m) => notified.push(String(m).slice(0, 40)) },
  sessionManager: { getSessionId: () => "sess-t", getSessionFile: () => sessionFile, getBranch: () => branch },
};
ctx.executeTool = async (name, args, opts) => {
  nested += 1;
  const toolCallId = `callP/${nested}`;
  const tool = tools.find((t) => t.name === name);
  if (!tool) return { toolCall: { id: toolCallId, name, arguments: args }, result: { content: [{ type: "text", text: "unknown" }] }, isError: true };
  for (const h of handlers["tool_call"] ?? []) {
    const block = await h({ toolName: name, toolCallId, input: args, parentToolCallId: "callP" }, ctx);
    if (block?.block) return { toolCall: { id: toolCallId, name, arguments: args }, result: { content: [{ type: "text", text: `BLOCKED: ${block.reason}` }] }, isError: true };
  }
  const result = await tool.execute(toolCallId, args, opts?.signal, null, ctx);
  for (const h of handlers["tool_result"] ?? []) {
    await h({ toolName: name, toolCallId, input: args, parentToolCallId: "callP",
              content: result.content, details: result.details, isError: result.isError }, ctx);
  }
  for (const h of handlers["tool_execution_end"] ?? []) {
    h({ toolCallId, toolName: name, parentToolCallId: "callP", durationMs: 2, isError: result.isError });
  }
  return { toolCall: { id: toolCallId, name, arguments: args }, result, isError: result.isError, durationMs: 2 };
};

const out = {};
await commands.atlas("approve-continuation TEST-1", ctx);
const marker1 = JSON.parse(readFileSync(join(root, ".atlas", "runs", "continuations", "isolated", "TEST-1.json"), "utf-8"));
out.armed = marker1.state;
let blockVerdict = null;
for (const h of handlers["tool_call"] ?? []) blockVerdict = await h({ toolName: "read", toolCallId: "d1", input: {}, parentToolCallId: undefined }, ctx);
out.direct_blocked = !!blockVerdict?.block;

const parentTool = tools.find((t) => t.name === "atlas_continue");
const ret = await parentTool.execute("callP", { unit: "TEST-1" }, undefined, null, ctx);
out.parent_ok = ret.isError === false && ret.details?.actions_ok === true;
out.actions = (ret.details?.observations ?? []).map((o) => o.tool);
const runDir0 = join(root, ".atlas", "runs", "continuations", appended[0]?.data?.runId ?? "x");
out.evidence_count = existsSync(join(runDir0, "evidence"))
  ? readdirSync(join(runDir0, "evidence")).length : -1;

branch.push({ type: "custom", customType: appended[0]?.customType, data: appended[0]?.data, id: "e-seal", parentId: "e0" });
// nestedCalls 从父 observations 动态合成（顺序/名称与真实宿主行为一致，不写死）
const nestedCalls = { calls: (ret.details?.observations ?? []).map((o, i) => ({
  id: o.child_tool_call_id ?? `callP/${i + 1}`, name: o.tool, status: o.ok ? "ok" : "error", durationMs: 2 })), complete: true };
branch.push({ type: "message", id: "e1", parentId: "e-seal",
  message: { role: "toolResult", toolCallId: "callP", toolName: "atlas_continue",
             content: ret.content, details: ret.details, isError: ret.isError,
             nestedCalls } });
writeFileSync(sessionFile, branch.map((b) => JSON.stringify(b)).join("\n") + "\n");
// M2 验收：shutdown-only 场景完全绕过 agent_settled，仅 session_shutdown 兜底审计
const settleHandlers = SCENARIO === "shutdown-only" ? [] : (handlers["agent_settled"] ?? []);
for (const h of settleHandlers) await h({}, ctx);
if (SCENARIO === "shutdown-only") {
  for (const h of handlers["session_shutdown"] ?? []) await h({}, ctx);
}

const marker2 = JSON.parse(readFileSync(join(root, ".atlas", "runs", "continuations", "isolated", "TEST-1.json"), "utf-8"));
out.final_state = marker2.state;
const runId = appended[0]?.data?.runId;
out.certificate = existsSync(join(root, ".atlas", "runs", "continuations", runId, "certificate.json"));
let after = null;
for (const h of handlers["tool_call"] ?? []) after = await h({ toolName: "read", toolCallId: "d2", input: {}, parentToolCallId: undefined }, ctx);
out.unlocked_after_audit = !after?.block;
console.log("P1DRIVER " + JSON.stringify(out));
"""


def test_gc_bun_fake_host_full_loop() -> None:
    """执行级（bun 可用时）：治理 ARMED → 默认拒绝直调 → 嵌套链 → 封印 → 审计 → 证书 → 解锁。
    bun 或 shasum 缺席 ⇒ 显式 skip。自含冻结净化启动器 + 只读 git 包装器（临时目录）。"""
    bun = shutil.which("bun")
    if not bun:
        pytest.skip("无 bun ⇒ pi 扩展执行级判据跳过")
    if not shutil.which("shasum"):
        pytest.skip("无 shasum ⇒ 只读 git 包装器不可冻结，跳过")

    launcher_dir = Path(tempfile.mkdtemp(prefix="gc-frozen-"))
    bin_dir = launcher_dir / "bin"
    bin_dir.mkdir()
    py = shutil.which("python3") or "/usr/bin/python3"
    launcher = _LAUNCHER_TPL.replace("__LAUNCHER_BIN__", str(bin_dir)).replace("{python}", py)
    (launcher_dir / "launcher.sh").write_text(launcher, encoding="utf-8")
    (bin_dir / "git").write_text(_WRAPPER_TPL, encoding="utf-8")
    for f in (launcher_dir / "launcher.sh", bin_dir / "git"):
        f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    env = dict(os.environ)
    env["ATLAS_GC_LAUNCHER"] = str(launcher_dir / "launcher.sh")
    scenarios = [
        ("settled", "false"),
        ("shutdown-only", "false"),   # M2：settled 缺席 ⇒ shutdown 兜底审计
        ("settled", "true"),          # 评审 F5：status-first 计划形态（首动作零 git 调用）
    ]
    for scenario, plan_flip in scenarios:
        driver = (_PI_GC_DRIVER
                  .replace("__PI_TS__", (PKG_ROOT / "extensions" / "pi.ts").as_posix())
                  .replace("__PKG__", str(PKG_ROOT))
                  .replace("__SCENARIO__", scenario)
                  .replace("__PLAN_FLIP__", plan_flip))
        drv = Path(tempfile.mkdtemp(prefix="gc-drv-")) / "driver.ts"
        drv.write_text(driver, encoding="utf-8")
        run = subprocess.run([bun, "run", str(drv)], capture_output=True, text=True,
                             timeout=300, env=env)
        assert run.returncode == 0, run.stdout + run.stderr
        line = [l for l in run.stdout.splitlines() if l.startswith("P1DRIVER ")][-1]
        data = json.loads(line.split(" ", 1)[1])
        tag = f"[{scenario}/flip={plan_flip}]"

        assert data["armed"] == "ARMED", (tag, data)
        assert data["direct_blocked"] is True, (tag, "治理窗口必须默认拒绝直调")
        assert data["parent_ok"] is True, (tag, data)
        expected_actions = (["atlas_workflow_status", "atlas_workflow_progress"]
                            if plan_flip == "true"
                            else ["atlas_workflow_progress", "atlas_workflow_status"])
        assert data["actions"] == expected_actions, (tag, data)
        assert data["evidence_count"] == 2, (tag, "supplemental evidence 每动作一份（F5-A）")
        assert data["final_state"] == "SUCCEEDED", (tag, data)
        assert data["certificate"] is True, (tag, data)
        assert data["unlocked_after_audit"] is True, (tag, "审计终态后必须解锁")
