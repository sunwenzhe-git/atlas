#!/usr/bin/env python3
"""impact 对账门 —— `impact.json` 预测集 vs 收口时实际 git diff 的**双向差集**（B191-1，2026-10-07）。

**病根**（`3509 §B191-1` / 决策 `3507 BB` 决策 3）：图谱批 1 的 `impact.json` 只是 advisory
附件——「预测失准」与「越界改动」都靠人眼，对账门是图谱线从「省时间」升格为「有牙」的
最后一步。本器在收口时把两集合摆上台面：

  - **漏报（miss）** = 实际 diff 有、预测集没有 —— 改动落在了影响面基准之外（最危险：
    要么影响面预测漏了真波及，要么改了申报范围外的文件）；
  - **多报（over）** = 预测集有、实际 diff 没有 —— 预测偏宽（name 级静态面的已知属性，
    量化「命中率」的分母；WARN 攒 2–3 单真实需求数据后按命中率决定是否收紧/升 FAIL）。

判据（全部可机器判）：

  1. `impact.json` 存在且可解析（**报告不存在 = 未跑影响面，SKIP 不是通过**，exit 3）；
  2. **基准一致性**：报告 `head` ≠ 当前 HEAD ⇒ WARN 指名两个 head（报告生成后有过提交，
     差集解释权归人，不得静默对账）；`--diff-base` ≠ `inputs.diff_base` ⇒ WARN 指名；
  3. predicted 集 = `touched_files` ∪ `inputs.paths` ∪ ⋃`layers[].files`；actual = 
     `git diff --name-only <diff-base>`（与 impact_report 的 `--diff-base` 同语义）；
  4. 双向差集非空 ⇒ **WARN** + 双侧逐文件指名（WARN 不置红——先攒命中率数据，升 FAIL
     的触发物见 `3509 §B191-1`）。

用法：

    python3 impact_reconcile.py --root <项目根> --task <需求ID> --diff-base <git ref>

退出码：0 = ok / WARN（带明细）；3 = SKIP（impact.json 缺失 / 不可解析 / 非 git 仓库）。
纯标准库 + 复用 `scripts/impact_report.py` 的 git 调用形态。

**盲区（显式）**：untracked 文件不在 `git diff` 内（与 impact_report 同语义）；对账只判
**文件级**（符号级归语义审查）；本器只读，不替人解释差集。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = "impact-reconcile"


def die(msg: str) -> None:
    print(f"[{SCRIPT}] FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def skip(reason: str) -> int:
    print(json.dumps({"status": "skip", "reason": reason}, ensure_ascii=False))
    return 3


def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        die(f"git {' '.join(args)} 失败: {(p.stderr or '').strip()[:200]}")
    return p.stdout


def head_of(root: Path) -> str:
    p = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=str(root),
                       capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--task", default=None, help="需求 ID → .trellis/tasks/<ID>/impact.json")
    ap.add_argument("--impact", default=None, help="impact.json 路径（优先于 --task）")
    ap.add_argument("--diff-base", required=True,
                    help="git ref：实际改动 = diff --name-only <ref>（与 impact_report 同语义）")
    ap.add_argument("--out", default=None, help="对账报告落点（默认 = impact.json 同目录 impact-reconcile.json）")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        die(f"--root 不是目录: {root}")
    if not (root / ".git").exists():
        return skip("非 git 仓库（无 .git）——对账无 diff 可言")

    impact_path = (Path(args.impact).resolve() if args.impact
                   else root / ".trellis" / "tasks" / (args.task or "") / "impact.json")
    if not impact_path.is_file():
        return skip(f"impact.json 不存在: {impact_path}（影响面报告未跑——SKIP 不是通过）")
    try:
        report = json.loads(impact_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return skip(f"impact.json 不可解析: {exc}")
    if report.get("category") != "impact":
        return skip(f"不是 impact 报告（category={report.get('category')!r}）")

    warns: list[str] = []
    head_now = head_of(root)
    head_report = report.get("head") or ""
    if head_now != head_report:
        warns.append(f"基准 head 漂移：报告生成于 {head_report[:12] or '(空)'}，当前 {head_now[:12] or '(空)'}"
                     "——报告生成后有过提交，差集解释权归人")

    inputs = report.get("inputs") or {}
    base_report = inputs.get("diff_base")
    if base_report and base_report != args.diff_base:
        warns.append(f"diff-base 不一致：报告 inputs.diff_base={base_report!r}，本次 --diff-base={args.diff_base!r}")

    actual = {ln.strip() for ln in git(root, "diff", "--name-only", args.diff_base).splitlines() if ln.strip()}
    predicted: set[str] = set(inputs.get("paths") or [])
    predicted |= set(report.get("touched_files") or [])
    for layer in report.get("layers") or []:
        predicted |= set(layer.get("files") or [])

    miss = sorted(actual - predicted)
    over = sorted(predicted - actual)
    if miss:
        warns.append("漏报（实际改动在预测集外，逐文件）：\n  - " + "\n  - ".join(miss))
    if over:
        warns.append("多报（预测集未改，命中率分母，逐文件）：\n  - " + "\n  - ".join(over))

    status = "warn" if warns else "ok"
    payload = {
        "status": status,
        "impact": str(impact_path),
        "head_report": head_report,
        "head_now": head_now,
        "diff_base": args.diff_base,
        "predicted_count": len(predicted),
        "actual_count": len(actual),
        "miss": miss,
        "over": over,
        "warns": warns,
    }
    out = Path(args.out).resolve() if args.out else impact_path.parent / "impact-reconcile.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    head_line = (f"[{SCRIPT}] {status}: predicted {len(predicted)} / actual {len(actual)}"
                 f"（漏报 {len(miss)} · 多报 {len(over)}）→ {out}")
    print(head_line)
    for w in warns:
        print(f"  WARN {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
