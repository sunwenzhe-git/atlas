#!/usr/bin/env python3
"""实例 ⑤「实现代码审查」的输出转换器：CLI 审查器 JSON ⇔ `review.json` 契约。

**问题**（`3509 §B100` 静默少审同族）：CLI 式审查器读 git diff 出结构化 findings，
但 (a) 严重度是四档（critical/high/medium/low），不是本契约的三档；
(b) 没有回退环 / unit / round / 应审实审对账；(c) **会对超大 diff 静默跳过文件**——
门若直接读它的输出，等于在门口信任模型结论 + 放走静默少审。

**解决方式**：转换器是唯一桥——CLI 的 JSON 是**输入侧证据**（原样留报告目录），
`review.json` 是**契约侧产物**（门禁只读它）。四档→三档映射**写死**；
应审 N（diff 文件数）/ 实审 M（CLI 汇总）对账，M < N ⇒ `WARN` 起步；
CLI 不报实审数 ⇒ **拒绝产出**（缺权威输入不得给「通过」，骨架 §2.6）。

用法：
    python3 .atlas/scripts/cli_review_convert.py \
        --input ocr.json --out product/impl/reviews/<日期>-<范围> \
        --unit <需求ID> --round 1 --scope "<一句话>" \
        --from main --to <task分支>          # 二选一：或 --expected-files N

- 输出三件：`findings/<unit>.r<round>.json`（不得覆盖，round 必须递增）、
  `review.json`、`README.md`（三段式）。纯标准库。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 严重度四档 → 三档，写死（骨架 §3 映射锁死；未知档位 = 输入侧契约违约，显式失败不猜）
SEVERITY_MAP = {"critical": "Critical", "high": "Major", "medium": "Major", "low": "Minor"}

# CLI category 闭集（骨架 §2.7：闭集外归 other，不计门禁，只作人工参考）
KNOWN_CATEGORIES = {"bug", "security", "performance", "maintainability",
                    "test", "style", "documentation"}

UNIT_RE = re.compile(r"^[\w.-]+$")

STATUS_SUMMARY = {"PASS": "通过", "WARN": "需修改", "FAIL": "需重大调整"}


def die(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 2


def count_diff_files(root: Path, ref_from: str, ref_to: str) -> int:
    """应审 N = diff 文件数（转换器自算，不信任调用方口报）。"""
    try:
        out = subprocess.run(["git", "-C", str(root), "diff", "--name-only", ref_from, ref_to],
                             capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(die(f"git diff {ref_from}..{ref_to} 失败：{e.stderr.strip()}"))
    return len([l for l in out.stdout.splitlines() if l.strip()])


def convert(payload: dict) -> tuple[list[dict], list[dict], int, bool, list[dict]]:
    """returns (checks, other, files_reviewed, budget_exceeded, warnings)"""
    summary = payload.get("summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("files_reviewed"), int):
        raise SystemExit(die("CLI 输出缺 summary.files_reviewed —— 无法判定实审数，"
                             "缺权威输入不得给「通过」（骨架 §2.6）"))
    comments = payload.get("comments")
    if not isinstance(comments, list):
        raise SystemExit(die("CLI 输出缺 comments[]（可为空列表，不可缺键）"))
    checks: list[dict] = []
    other: list[dict] = []
    for i, c in enumerate(comments):
        sev = (c.get("severity") or "").strip().lower()
        if sev not in SEVERITY_MAP:
            raise SystemExit(die(f"comments[{i}] 严重度「{sev or '缺失'}」不在四档闭集 —— 不猜，显式失败"))
        cat = (c.get("category") or "").strip().lower()
        path = c.get("path") or "?"
        start, end = c.get("start_line") or 0, c.get("end_line") or 0
        target = f"{path}:{start}-{end}" if start or end else f"{path}:?（定位失败，人工定位）"
        detail = (c.get("content") or "").strip()
        if c.get("suggestion_code"):
            detail = f"{detail}｜建议：{c['suggestion_code'].strip()}"
        item = {"check": cat if cat in KNOWN_CATEGORIES else "other",
                "target": target, "detail": detail}
        if item["check"] == "other":
            other.append(item)
        else:
            checks.append({"id": f"D{len(checks) + 1}", "level": SEVERITY_MAP[sev], **item,
                           "rollback": "implement"})  # 默认回退环；triage 可改判 prd/e2e 入 backfill
    warnings = [w for w in (payload.get("warnings") or []) if isinstance(w, dict)]
    return checks, other, summary["files_reviewed"], bool(summary.get("budget_exceeded")), warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--input", required=True, help="CLI 审查器的 --format json 输出文件")
    ap.add_argument("--out", required=True, help="报告目录（写 review.json / README.md / findings/）")
    ap.add_argument("--unit", required=True, help="扇出单元键（如需求 ID；文件名安全字符）")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--scope", default="")
    ap.add_argument("--from", dest="ref_from", help="git 起 ref（与 --to 同用，自算应审 N）")
    ap.add_argument("--to", dest="ref_to", help="git 止 ref")
    ap.add_argument("--expected-files", type=int, help="应审 N 显式传入（无 git ref 时）")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    if args.round < 1:
        return die("round 必须 ≥ 1")
    if not UNIT_RE.fullmatch(args.unit):
        return die(f"unit「{args.unit}」含文件名不安全字符")
    if bool(args.ref_from) != bool(args.ref_to):
        return die("--from 与 --to 必须同用")
    if args.ref_from and args.ref_to:
        expected = count_diff_files(root, args.ref_from, args.ref_to)
    elif args.expected_files is not None:
        expected = args.expected_files
    else:
        return die("应审 N 不可得：给 --from/--to（自算 diff 文件数）或 --expected-files")

    src = Path(args.input)
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return die(f"读输入 {src} 失败：{e}")
    checks, other, reviewed, budget, warnings = convert(payload)

    # 状态（写死）：Critical ⇒ FAIL；Major / M<N / 预算击穿 ⇒ WARN；否则 PASS
    levels = {c["level"] for c in checks}
    if "Critical" in levels:
        status = "FAIL"
    elif "Major" in levels or reviewed < expected or budget:
        status = "WARN"
    else:
        status = "PASS"

    outdir = root / args.out
    findings = outdir / "findings"
    findings.mkdir(parents=True, exist_ok=True)
    unit_file = findings / f"{args.unit}.r{args.round}.json"
    if unit_file.is_file():
        return die(f"{unit_file} 已存在 —— 同 (unit, round) 不得覆盖，round 必须递增（骨架 §4）")

    review = {"ok": status != "FAIL", "status": status, "root": str(root),
              "scope": args.scope, "unit": args.unit, "round": args.round,
              "expected": expected, "reviewed": reviewed, "budget_exceeded": budget,
              "checks": checks, "other": other}
    unit_file.write_text(json.dumps(review, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (outdir / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")

    lines = [f"# 实现代码独立审查 —— {args.scope or args.unit}",
             "", "## 1. 审查总结", "",
             f"- 结论：**{STATUS_SUMMARY[status]}**（`{status}`；round {args.round}）",
             f"- **应审 {expected} / 实审 {reviewed}**" + ("（少审！见问题清单末尾）" if reviewed < expected else ""),
             f"- 预算击穿：{'是' if budget else '否'}；CLI warnings：{len(warnings)} 条"]
    lines += [f"  - `{w.get('file', '?')}` [{w.get('type', '?')}] {w.get('message', '')}"
              for w in warnings]
    lines.append("")
    for level in ("Critical", "Major", "Minor"):
        group = [c for c in checks if c["level"] == level]
        if not group and level != "Minor":
            continue
        lines += ["", f"## 2.{'①②③'[('Critical', 'Major', 'Minor').index(level)]} {level}", ""]
        lines += [f"- **{c['id']}** `{c['target']}` [{c['check']}] {c['detail']}（回退环：{c['rollback']}）"
                  for c in group] or ["- （无）"]
    lines += ["", "## 3. 优化建议（other，不计门禁）", ""]
    lines += [f"- `{o['target']}` {o['detail']}" for o in other] or ["- （无）"]
    lines += ["", f"- triage 提示：AC / 断言本身的缺陷应把回退环改判 `prd` / `e2e` 并登记 backfill"
                  f"（`apply/reference.md` §5.2）；本转换器默认全部 `implement`。", ""]
    (outdir / "README.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"cli_review_convert @ {outdir}   {status}   应审 {expected} / 实审 {reviewed}"
          f"   checks {len(checks)} + other {len(other)}")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
