#!/usr/bin/env python3
"""Guarded Continuation —— 计划契约、封闭参数、回执与证书（RFC：GDR PoC P1）。

纯标准库；不执行任何父动作链（动作由 Pi 父工具经 ctx.executeTool 真实嵌套发起）。
本模块只负责：计划 schema 校验、规范哈希、guard 重放、运行目录、回执与证书 IO。

口径纪律（与 extensions/pi.ts 的 TS 侧镜像约束，双侧必须逐字节一致）：
- 规范哈希 = 对 {"content","details","structuredContent","isError"} 做稳定序列化后 sha256；
  稳定序列化 = 键排序 + 丢弃 None/undefined 值 + json.dumps(separators=(",",":"),
  ensure_ascii=False)。字符串/整数/布尔/null/数组/对象之外（浮点）不进哈希面。
- 哈希不得进入被哈希对象（P0 实测坑：子工具返回值内嵌自身哈希导致父重算必不等）。
- nestedCalls 不保存结果，只能证明名称/参数/状态/耗时 ⇒ 最终证书必须绑定
  「宿主 nestedCalls + raw-receipts（权威）+ supplemental evidence + 追加封印」两层对账。

状态机（§4.4）：
  DRAFT -> APPROVED/ARMED -> FROZEN -> RUNNING -> RECORDED -> AUDITING
            -> SUCCEEDED | AUDIT_FAILED | CLOSED_FAILED；异常分支 ISOLATED。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

# ────────────────────────────────────────────────────────────────────────── 常量
SCHEMA_VERSION = 1
# 封闭动作枚举（首版只读面；check_fast/finish/gen_* 一律拒绝）
ALLOWED_TOOLS = ("atlas_workflow_progress", "atlas_workflow_status")
MAX_ACTIONS = 8
MAX_CANONICAL_ARGS_BYTES = 16 * 1024
GUARD_FACT_KEYS = ("exit_code", "json_ok")

CONTINUATIONS_DIRNAME = os.path.join(".atlas", "runs", "continuations")
ISOLATED_DIRNAME = os.path.join(CONTINUATIONS_DIRNAME, "isolated")
RUN_ARTIFACTS = ("raw-receipts", "evidence")


class PlanError(Exception):
    """计划契约违例（fail-closed：任何 schema/路径/guard 问题都停在这）。"""


# ────────────────────────────────────────────────────────────────── 规范哈希
def _drop_none(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _drop_none(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_drop_none(x) for x in v]
    return v


def canonical_json(value: Any) -> str:
    """稳定序列化：键排序、丢 None、紧凑分隔符、不转义非 ASCII。

    与 pi.ts 侧 `stable()`（P0 已实测双侧一致）逐字节镜像；浮点不进哈希面。
    """
    return json.dumps(_drop_none(value), sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))


def canonical_result_hash(result: dict) -> str:
    """工具结果规范哈希：{content, details, structuredContent, isError}。"""
    payload = {
        "content": result.get("content"),
        "details": result.get("details"),
        "structuredContent": result.get("structuredContent"),
        "isError": result.get("isError"),
    }
    return sha256_hex(canonical_json(payload).encode("utf-8"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_hex(path.read_bytes())


# ────────────────────────────────────────────────────────────────── 计划契约
def plan_path(root: Path, unit: str) -> Path:
    if not unit or unit != Path(unit).name or unit in (".", ".."):
        raise PlanError(f"非法 unit：{unit!r}")
    return root / ".atlas" / "tasks" / unit / "continuation.json"


def load_plan(root: Path, unit: str) -> dict:
    """读计划并做全量 schema 校验（fail-closed）；返回附带 plan_sha256 的 dict。"""
    path = plan_path(root, unit)
    if path.is_symlink() or not path.is_file():
        raise PlanError(f"计划不存在或为 symlink：{path}")
    raw = path.read_bytes()
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PlanError(f"计划不可解析：{e}") from e
    _validate_plan(plan, unit)
    plan["plan_sha256"] = sha256_hex(raw)
    plan["_plan_path"] = str(path)
    return plan


def _reject(plan: dict, msg: str) -> None:
    raise PlanError(msg)


def _validate_plan(plan: dict, unit: str) -> None:
    if not isinstance(plan, dict):
        _reject(plan, "计划必须是对象")
    if plan.get("schema") != SCHEMA_VERSION:
        _reject(plan, f"schema 必须为 {SCHEMA_VERSION}")
    if plan.get("unit") != unit:
        _reject(plan, f"unit 与目录不一致：{plan.get('unit')!r} != {unit!r}")
    if plan.get("author") != "human":
        # author 只是说明字段，不是授权（授权唯一来自人类 approve 命令票据）
        _reject(plan, "author 必须为 \"human\"（说明字段，非授权）")
    actions = plan.get("actions")
    if not isinstance(actions, list) or not (1 <= len(actions) <= MAX_ACTIONS):
        _reject(plan, f"actions 必须为 1..{MAX_ACTIONS} 个")
    seen_ids: set[str] = set()
    defined_ids: set[str] = set()
    total_args_bytes = 0
    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            _reject(plan, f"actions[{idx}] 必须为对象")
        aid = action.get("id")
        if not isinstance(aid, str) or not aid or aid in seen_ids:
            _reject(plan, f"actions[{idx}].id 非空且唯一，got {aid!r}")
        seen_ids.add(aid)
        tool = action.get("tool")
        if tool not in ALLOWED_TOOLS:
            _reject(plan, f"actions[{idx}].tool {tool!r} 不在封闭枚举 {ALLOWED_TOOLS}")
        args = action.get("args")
        if not isinstance(args, dict) or set(args) != {"unit"} or args["unit"] != unit:
            _reject(plan, f"actions[{idx}].args 只允许 {{unit: <与本任务一致的 unit>}}")
        encoded = json.dumps(args, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        total_args_bytes += len(encoded)
        if total_args_bytes > MAX_CANONICAL_ARGS_BYTES:
            _reject(plan, f"规范参数总量超过 {MAX_CANONICAL_ARGS_BYTES} 字节")
        _validate_guard(action.get("guard"), idx, defined_ids, plan)
        defined_ids.add(aid)
    # 计划不跨任务复用：run 目录/票据绑定在执行期由调用方持有，这里只锁契约。


def _validate_guard(guard: Any, idx: int, defined_ids: set[str], plan: dict) -> None:
    if not isinstance(guard, dict):
        _reject(plan, f"actions[{idx}].guard 必须为对象")
    kind = guard.get("kind")
    if kind == "always":
        return
    if kind == "all_of":
        refs = guard.get("refs")
        if not isinstance(refs, list) or not refs:
            _reject(plan, f"actions[{idx}] all_of.refs 必须非空数组")
        for ref in refs:
            if not isinstance(ref, str) or "." not in ref:
                _reject(plan, f"actions[{idx}] guard 引用形如 <action_id>.<fact>，got {ref!r}")
            aid, fact = ref.split(".", 1)
            if aid not in defined_ids:
                _reject(plan, f"actions[{idx}] guard 引用 {ref!r}：未知/前向/重复 ID 皆拒绝")
            if fact not in GUARD_FACT_KEYS:
                _reject(plan, f"actions[{idx}] guard 事实键仅 {GUARD_FACT_KEYS}，got {fact!r}")
        return
    _reject(plan, f"actions[{idx}] guard.kind 仅 always/all_of，got {kind!r}")


def canonical_args_hash(args: dict) -> str:
    return sha256_hex(canonical_json(args).encode("utf-8"))


# ────────────────────────────────────────────────────────────────── guard 求值
def observed_facts(observation: dict) -> dict:
    """从单动作观察回执提取 guard 事实：exit_code（==0 谓词）、json_ok。"""
    return {
        "exit_code": observation.get("exit_code") == 0,
        "json_ok": bool(observation.get("json_ok")),
    }


def evaluate_guard(guard: dict, observations: dict[str, dict]) -> tuple[bool, list[str]]:
    """求值当前动作 guard；只消费已观察回执（不消费模型预测）。

    返回 (通过?, 引用事实值列表)。exit_code 谓词固定 ==0；json_ok = 可解析 JSON。
    """
    if guard.get("kind") == "always":
        return True, []
    values: list[str] = []
    for ref in guard.get("refs", []):
        aid, fact = ref.split(".", 1)
        obs = observations.get(aid)
        if obs is None:
            return False, values
        facts = observed_facts(obs)
        values.append(f"{ref}={facts[fact]}")
        if not facts[fact]:
            return False, values
    return True, values


def replay_guards(plan: dict, observations: dict[str, dict],
                  host_call_names: list[str]) -> dict:
    """审计重放：逐动作重算 guard，断言「guard=false 后零宿主调用、失败后零后续调用」。

    host_call_names = 宿主 nestedCalls 的顺序动作名序列（来自 session 宿主记录）。
    返回 {ok, detail}；任何违例 ok=False。
    """
    executed: dict[str, dict] = {}
    expected_calls: list[str] = []
    stopped = False
    for action in plan["actions"]:
        aid = action["id"]
        ok, _ = evaluate_guard(action["guard"], executed)
        if stopped or not ok:
            stopped = True
            continue
        expected_calls.append(action["tool"])
        # 观察回执里该动作必须成功（失败即停，不允许后继）
        obs = observations.get(aid)
        if obs is None or not obs.get("ok"):
            stopped = True
            continue
        executed[aid] = obs
    detail = {
        "expected_calls": expected_calls,
        "actual_calls": host_call_names,
        "prefix_match": host_call_names == expected_calls[:len(host_call_names)]
        if len(host_call_names) <= len(expected_calls) else False,
        "zero_suffix": len(host_call_names) == len(expected_calls),
    }
    ok = detail["prefix_match"] and detail["zero_suffix"]
    return {"ok": ok, "detail": detail}


# ────────────────────────────────────────────────────────────────── 运行目录 IO
def run_dir(root: Path, run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    if not safe or safe != run_id or len(run_id) > 80:
        raise PlanError(f"非法 run_id：{run_id!r}")
    base = root / CONTINUATIONS_DIRNAME / run_id
    for sub in ("raw-receipts", "evidence"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def isolated_marker_path(root: Path, unit: str) -> Path:
    return root / ISOLATED_DIRNAME / f"{unit}.json"


def write_exclusive(path: Path, text: str) -> None:
    """O_EXCL 不可变写：已存在即失败（防并发运行互相覆盖 / 防覆盖前序回执）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_json_exclusive(path: Path, payload: dict) -> str:
    """O_EXCL 写 JSON（追加换行）；返回**落盘字节的** sha256（含换行，与 file_sha256 对账面一致）。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_exclusive(path, text)
    return sha256_hex(text.encode("utf-8"))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def raw_receipt_path(run: Path, action_index: int, child_hash: str) -> Path:
    return run / "raw-receipts" / f"{action_index}-{child_hash}.json"


def write_raw_receipt(run: Path, action_index: int, result: dict, meta: dict) -> tuple[str, str]:
    """权威原始回执（子工具 execute 在最终结果确定后、返回前写；O_EXCL）。

    返回 (result_sha256, raw_receipt_sha256)：前者 = 结果规范哈希（语义面），
    后者 = 回执文件字节哈希（完整性面）；证书 substitutions 两个字段分列。
    """
    h = canonical_result_hash(result)
    payload = {"canonical_hash": h, "result": result, **meta}
    file_sha = write_json_exclusive(raw_receipt_path(run, action_index, h[:16]), payload)
    return h, file_sha


def manifest_hash(run: Path, subdir: str) -> str:
    """目录内逐文件摘要清单的规范哈希（raw-receipts / git-calls / evidence 通用）。"""
    entries = []
    base = run / subdir
    if base.is_dir():
        for p in sorted(base.rglob("*")):
            if p.is_file():
                entries.append({"path": str(p.relative_to(run)), "sha256": file_sha256(p)})
    elif subdir == "git-calls.jsonl":
        p = run / subdir
        if p.is_file():
            entries.append({"path": subdir, "sha256": file_sha256(p)})
    return sha256_hex(canonical_json(entries).encode("utf-8"))


# ────────────────────────────────────────────────────────────────── 证书 v1
def certificate_payload(*, run_id: str, unit: str, plan_sha256: str,
                        atlas_version: str, session_id: str,
                        parent_tool_call_id: str, parent_tool_name: str,
                        expected_parent_result_sha256: str,
                        actual_parent_result_sha256: str,
                        host_nested_calls: dict, session_seal: dict,
                        execution_receipt_sha256: str,
                        input_manifest_sha256: str,
                        raw_receipts_manifest_sha256: str,
                        git_calls_manifest_sha256: str,
                        substitutions: list[dict], status: str) -> dict:
    """证书字段面（§6.2）。certificate 只证明「一个父工具内发生了 N 次嵌套动作，
    扩观测了结果，session 宿主记录与回执对账通过」；token 归因不在证书内。"""
    return {
        "schema": SCHEMA_VERSION,
        "run_id": run_id,
        "unit": unit,
        "plan_sha256": plan_sha256,
        "atlas_version": atlas_version,
        "session_id": session_id,
        "parent_tool_call_id": parent_tool_call_id,
        "parent_tool_name": parent_tool_name,
        "expected_parent_result_sha256": expected_parent_result_sha256,
        "actual_parent_result_sha256": actual_parent_result_sha256,
        "host_nested_calls_sha256": sha256_hex(canonical_json(host_nested_calls).encode("utf-8")),
        "host_nested_calls_complete": host_nested_calls.get("complete") is True,
        "session_seal_entry_id": session_seal.get("entry_id"),
        "session_seal_sha256": sha256_hex(canonical_json(session_seal.get("data")).encode("utf-8")),
        "execution_receipt_sha256": execution_receipt_sha256,
        "input_manifest_sha256": input_manifest_sha256,
        "raw_receipts_manifest_sha256": raw_receipts_manifest_sha256,
        "git_calls_manifest_sha256": git_calls_manifest_sha256,
        "substitutions": substitutions,
        "status": status,
    }


def audit_failure_payload(run: Path, reason: str, detail: dict) -> dict:
    return {"schema": SCHEMA_VERSION, "run_id": run.name,
            "status": "AUDIT_FAILED", "reason": reason, "detail": detail}
