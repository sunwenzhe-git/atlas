#!/usr/bin/env python3
"""Atlas 影子试点（research 工具，不进装配、不作为执行契约）。

用途：在**真实任务结束之后**单独跑一道门，记录「如果门被强制执行，会不会拦」，
但不改变工作流、不阻断任何东西。账本默认写项目外 `~/.atlas-shadow/<gate>.jsonl`。

安全边界：
  * 只跑指定的一个校验器；不改校验器、不改编排器。
  * 默认拒绝已知有写副作用的门（`validate_testids` / `validate_ac_alignment`）；
    要用必须显式 `--allow-side-effects`，并自行对副本执行。
  * 账本只存门名 / 状态 / 计数 / 耗时 / 输出哈希 / 校验器哈希 / 项目引用哈希；
    **不存校验器原文、项目绝对路径或项目名**（违反零业务上下文）。
  * `--label` 由操作者给，不得写产品名 / 业务数据；它只用于事后归因。
  * 写账本失败不影响退出码；账本是观测面，不是门。

用法：
    python3 research/shadow_pilot.py --root <项目根> --label <批次ID>
    python3 research/shadow_pilot.py --root <项目根> --gate validate_e2e_index \
        --out ~/.atlas-shadow/e2e-index.jsonl --label <批次ID>

退出码：PASS/WARN -> 0；FAIL -> 1；工具自身错误（缺门 / 拒绝副作用门）-> 2。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

SIDE_EFFECT_GATES = {"validate_testids", "validate_ac_alignment"}


def _git_state(root: pathlib.Path) -> tuple[str, bool]:
    head, dirty = "unknown", False
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                           capture_output=True, text=True, timeout=5)
        if p.returncode == 0:
            head = p.stdout.strip()
        p = subprocess.run(["git", "status", "--porcelain"], cwd=str(root),
                           capture_output=True, text=True, timeout=5)
        if p.returncode == 0:
            dirty = bool(p.stdout.strip())
    except Exception:
        pass
    return head, dirty


def _resolve_validator(root: pathlib.Path, gate: str) -> pathlib.Path | None:
    """项目已装配优先用 `.atlas/validators/`；否则用本工具所属源包的 `validators/`。"""
    installed = root / ".atlas" / "validators" / f"{gate}.py"
    if installed.is_file():
        return installed
    source = pathlib.Path(__file__).resolve().parents[1] / "validators" / f"{gate}.py"
    return source if source.is_file() else None


def _classify(exit_code: int, out: str) -> tuple[str, int, int, int]:
    fails = sum(1 for line in out.splitlines() if "[FAIL]" in line)
    warns = sum(1 for line in out.splitlines() if "[WARN]" in line)
    skips = sum(1 for line in out.splitlines() if "[SKIP]" in line or "[N/A" in line or "[NA " in line)
    if exit_code != 0:
        return "FAIL", fails, warns, skips
    if fails:
        return "INCONSISTENT", fails, warns, skips
    if warns:
        return "WARN", fails, warns, skips
    return "PASS", fails, warns, skips


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Atlas 影子试点（只记录，不阻断）")
    ap.add_argument("--root", default=".", help="项目根（校验器的 --root）")
    ap.add_argument("--gate", default="validate_e2e_index", help="校验器名（不含 .py）")
    ap.add_argument("--out", default=None,
                    help="账本路径；默认 ~/.atlas-shadow/<gate>.jsonl")
    ap.add_argument("--label", default="", help="批次 / 任务标识，便于事后归因")
    ap.add_argument("--allow-side-effects", action="store_true",
                    help="允许跑已知有写副作用的门；请自行对副本执行")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.root).resolve()
    if not root.is_dir():
        print(f"root 不存在：{root}", file=sys.stderr)
        return 2
    if args.gate in SIDE_EFFECT_GATES and not args.allow_side_effects:
        print(f"拒绝：{args.gate} 有写副作用；请对副本执行并加 --allow-side-effects", file=sys.stderr)
        return 2
    validator = _resolve_validator(root, args.gate)
    if validator is None:
        print(f"找不到校验器：{args.gate}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    proc = subprocess.run([sys.executable, str(validator), "--root", str(root)],
                          capture_output=True, text=True, timeout=1800)
    duration_ms = int((time.perf_counter() - started) * 1000)
    out = (proc.stdout or "") + (proc.stderr or "")
    status, fails, warns, skips = _classify(proc.returncode, out)
    head, dirty = _git_state(root)
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gate": args.gate,
        "validator_sha256": hashlib.sha256(validator.read_bytes()).hexdigest(),
        # 项目引用只存不可逆哈希，不落绝对路径 / 项目名。
        "root_ref": hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16],
        "label": args.label,
        "exit_code": proc.returncode,
        "would_be_status": status,
        "fail_lines": fails,
        "warn_lines": warns,
        "skip_lines": skips,
        "duration_ms": duration_ms,
        "output_sha256": hashlib.sha256(out.encode("utf-8")).hexdigest(),
        "git_head": head,
        "git_dirty": dirty,
        "ablation_id": os.environ.get("ATLAS_ABLATION_ID") or None,
    }
    out_path = pathlib.Path(args.out) if args.out else \
        pathlib.Path.home() / ".atlas-shadow" / f"{args.gate}.jsonl"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
    except Exception as exc:
        print(f"[WARN] 账本写失败（不影响影子结论）：{exc}", file=sys.stderr)
    print(f"{status} {args.gate} {duration_ms}ms fails={fails} warns={warns} "
          f"skips={skips} label={args.label or '-'} -> {out_path}")
    return 0 if status in ("PASS", "WARN", "INCONSISTENT") else 1


if __name__ == "__main__":
    sys.exit(main())
