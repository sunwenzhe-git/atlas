#!/usr/bin/env python3
"""实例 ⑤「实现代码审查」的输出转换器：CLI 审查器 JSON ⇔ `review.json` 契约。

**问题**（`3509 §B100` 静默少审同族）：CLI 式审查器读 git diff 出结构化 findings，
但 (a) 严重度是四档（critical/high/medium/low），不是本契约的三档；
(b) 没有回退环 / unit / round / 应审实审对账；(c) **会对超大 diff 静默跳过文件**——
门若直接读它的输出，等于在门口信任模型结论 + 放走静默少审。

**解决方式**：转换器是唯一桥——CLI 的 JSON 是**输入侧证据**（原样留报告目录），
`review.json` 是**契约侧产物**（门禁只读它）。四档→三档映射**写死**；
应审 N（diff 文件数）/ 实审 M（coverage completed；无 coverage 才回退 summary）对账，
M < N ⇒ `WARN` 起步；CLI 不报实审数 / coverage 缺 completed ⇒ **拒绝产出**
（缺权威输入不得给「通过」，骨架 §2.6）。

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

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
from _support.siblings import load_module  # noqa: E402

review_policy = load_module("review_policy")

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


def _coverage_info(payload: dict) -> dict:
    """CLI coverage：completed 为实审权威；缺 completed / 形态错 ⇒ 拒绝产出。"""
    manifest = payload.get("manifest")
    coverage = manifest.get("coverage") if isinstance(manifest, dict) else None
    if not isinstance(coverage, dict):
        return {"present": False, "completed": [], "failed": [], "waived": [],
                "reused": [], "selected": [], "cli_status": "unknown"}
    if "completed" not in coverage or not isinstance(coverage["completed"], list):
        raise SystemExit(die("CLI coverage 缺 completed[] —— 无法判定实审文件，拒绝产出"))
    for key in ("failed", "waived", "reused", "selected"):
        if key in coverage and not isinstance(coverage[key], list):
            raise SystemExit(die(f"CLI coverage.{key} 必须为列表"))
    return {"present": True,
            "completed": review_policy.normalize_paths(coverage["completed"]),
            "failed": review_policy.normalize_paths(coverage.get("failed")),
            "waived": review_policy.normalize_paths(coverage.get("waived")),
            "reused": review_policy.normalize_paths(coverage.get("reused")),
            "selected": review_policy.normalize_paths(coverage.get("selected")),
            "cli_status": "unknown"}


def _parse_paths(value: str | None) -> list[str]:
    if not value:
        return []
    return review_policy.normalize_paths([p for p in value.split(",") if p.strip()])


def load_resolves(path_str: str) -> list[dict]:
    """读 `--resolves` 文件：`[...]` 或 `{"by": 缺省签字人, "resolves": [...]}`。

    形状判据单源在 `review_policy.resolves_shape_errors`（与 `review_closure.py` 同一套）；
    语义（能不能算关闭、对上哪条义务）归 `review_closure.py`，本器不判。
    """
    src = Path(path_str)
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(die(f"读 --resolves {src} 失败：{e}"))
    default_by = ""
    if isinstance(raw, dict):
        default_by = str(raw.get("by") or "").strip()
        entries = raw.get("resolves")
    elif isinstance(raw, list):
        entries = raw
    else:
        raise SystemExit(die("--resolves 文件必须是数组或 {by, resolves} 对象"))
    if not entries:
        raise SystemExit(die("--resolves 文件里没有任何声明（不给就不写该键）"))
    errs = review_policy.resolves_shape_errors(entries, "resolves")
    if errs:
        raise SystemExit(die(errs[0]))
    out: list[dict] = []
    for item in entries:
        entry = dict(item)
        if not str(entry.get("by") or "").strip() and default_by:
            entry["by"] = default_by          # 整批缺省签字人继承（真实手写实测逐条重复 13 次）
        out.append(entry)
    return out


def convert(payload: dict) -> tuple[list[dict], list[dict], int, bool, list[dict], dict]:
    """returns (checks, other, reviewed, budget_exceeded, warnings, coverage)"""
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
            fp = review_policy.compute_fingerprint(target, cat, detail)
            checks.append({"id": f"D{len(checks) + 1}", "level": SEVERITY_MAP[sev], **item,
                           "fingerprint": fp, "pre_existing": False, "disposition": "open",
                           "rollback": "implement"})  # 默认回退环；triage 可改判 prd/e2e 入 backfill
    warnings = [w for w in (payload.get("warnings") or []) if isinstance(w, dict)]
    raw_status = str(payload.get("status") or "").strip().lower()
    cli_status = raw_status if raw_status in review_policy.CLI_STATUSES else "unknown"
    if raw_status and raw_status not in review_policy.CLI_STATUSES:
        warnings.append({"file": "<cli>", "type": "status",
                         "message": f"未知 CLI status={raw_status!r}，按 unknown 记录"})
    cov = _coverage_info(payload)
    cov["cli_status"] = cli_status
    if cov["present"]:
        reviewed = len(cov["completed"])
        summary_count = summary["files_reviewed"]
        if summary_count != reviewed:
            warnings.append({"file": "<coverage>", "type": "coverage",
                             "message": f"summary.files_reviewed={summary_count} != "
                                        f"coverage.completed={reviewed}；以 coverage 为准"})
        if not cov["completed"] and not checks and not other:
            raise SystemExit(die("CLI coverage.completed 为空且无 findings —— 没有发生审查，拒绝产出"))
    else:
        reviewed = summary["files_reviewed"]
        # 无 coverage ⇒ M 只剩自评（`ocr scan` 通道就不产 coverage），点名而不静默
        warnings.append({"file": "<coverage>", "type": "coverage",
                         "message": "无 manifest.coverage ⇒ 实审数取 CLI 自评 "
                                    "summary.files_reviewed（无权威，M 可被高估）"})
        if cli_status == "failed" and not checks and not other:
            raise SystemExit(die("CLI status=failed 且无 findings —— 没有发生审查，拒绝产出"))
    return checks, other, reviewed, bool(summary.get("budget_exceeded")), warnings, cov


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
    ap.add_argument("--schema-version", type=int, default=None,
                    help="报告契约版本（缺省：delta=v3，非 delta=v2）")
    ap.add_argument("--escalate-to", help="round >= 4 轮次上限升级复议人/团队")
    ap.add_argument("--escalate-reason", help="round >= 4 轮次上限升级复议理由")
    ap.add_argument("--delta-only", action="store_true", help="是否为差量评审（首轮之后）")
    ap.add_argument("--base-sha", help="差量评审对比基线 HEAD SHA")
    ap.add_argument("--head-sha", help="差量评审的止点 SHA（v3 delta 必填；不得用 --to 兼取）")
    ap.add_argument("--reviewed-files", help="逗号分隔的实际审阅文件列表（v3 delta 无 coverage 时必填）")
    ap.add_argument("--resolves", help="跨轮关闭声明文件（[...] 或 {by, resolves}）；语义归 review_closure")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    schema_version = args.schema_version if args.schema_version is not None else (
        3 if args.delta_only else 2)

    if schema_version < 1:
        return die("schema_version 必须 ≥ 1")
    if args.round < 1:
        return die("round 必须 ≥ 1")
    # 轮次上限属**过程收敛纪律**（D129），与报告形态版本无关 ⇒ 不因 --schema-version 1 而放行
    # （校验器侧仍只对新落盘的 v2 报告判 escalation，避免回扫历史 v1 报告造成永久红门）。
    if args.round >= 4:
        if not (args.escalate_to and args.escalate_reason):
            return die(f"round={args.round} 达到 4 轮收敛上限：必须提供 --escalate-to 与 --escalate-reason 登记升级复议")
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
    checks, other, reviewed, budget, warnings, cov = convert(payload)
    # 声明在落盘前读完：形状错就不留半截产物
    resolves_entries = load_resolves(args.resolves) if args.resolves else []
    cli_status = cov["cli_status"]
    selected_files = cov["selected"]
    failed_files = cov["failed"]
    waived_files = cov["waived"]
    reused_files = cov["reused"]

    head_sha = (args.head_sha or "").strip()
    reviewed_files: list[str] = []
    if args.delta_only:
        if schema_version >= 3:
            explicit = _parse_paths(args.reviewed_files)
            reviewed_files = explicit or cov["completed"]
            if not reviewed_files:
                return die("v3 delta 缺 reviewed_files：给 coverage.completed 或 --reviewed-files")
            if not head_sha:
                return die("v3 delta 缺 head_sha：给 --head-sha（不得用 --to 兼取）")
        else:
            reviewed_files = sorted({c["target"].split(":")[0] for c in checks
                                     if "target" in c and c["target"] != "?"})

    delta_view = {"schema_version": schema_version, "delta_only": args.delta_only,
                  "head_sha": head_sha, "reviewed_files": reviewed_files,
                  "reviewed": reviewed, "expected": expected,
                  "failed_files": failed_files, "waived_files": waived_files,
                  "reused_files": reused_files}
    if cov["present"]:
        delta_view["completed_files"] = cov["completed"]
        delta_view["selected_files"] = selected_files
    delta_issues = review_policy.delta_warnings(delta_view, checks, other) if args.delta_only else []
    delta_notes = review_policy.delta_notes(delta_view) if args.delta_only else []

    # 状态映射（D129 统一策略内核 + Batch A：CLI partial/failed 只抬 WARN，不降级 Critical
    # + Batch B：delta 数量/成员/selected 对账只抬 WARN）
    warn_floor = reviewed < expected or budget or review_policy.cli_warn_floor(
        {"cli_status": cli_status, "failed_files": failed_files}) or bool(delta_issues)
    status = review_policy.calculate_status(checks, warn_floor=warn_floor,
                                            schema_version=schema_version)

    outdir = root / args.out
    findings = outdir / "findings"
    findings.mkdir(parents=True, exist_ok=True)
    unit_file = findings / f"{args.unit}.r{args.round}.json"
    if unit_file.is_file():
        return die(f"{unit_file} 已存在 —— 同 (unit, round) 不得覆盖，round 必须递增（骨架 §4）")

    review = {"schema_version": schema_version, "ok": status != "FAIL", "status": status,
              "root": str(root), "scope": args.scope, "unit": args.unit, "round": args.round,
              "expected": expected, "reviewed": reviewed, "budget_exceeded": budget,
              "cli_status": cli_status,
              "cli_warnings": [f"{w.get('file', '?')} [{w.get('type', '?')}] {w.get('message', '')}"
                               for w in warnings],
              "checks": checks, "other": other}
    if cov["present"]:
        review["completed_files"] = cov["completed"]
        review["selected_files"] = selected_files
        review["failed_files"] = failed_files
        review["waived_files"] = waived_files
        review["reused_files"] = reused_files
    if args.escalate_to:
        review["escalation"] = {"to": args.escalate_to, "reason": args.escalate_reason}
    if resolves_entries:
        review["resolves"] = resolves_entries
    if args.delta_only:
        review["delta_only"] = True
        if args.base_sha:
            review["base_sha"] = args.base_sha
        if head_sha:
            review["head_sha"] = head_sha
        review["reviewed_files"] = reviewed_files
        if delta_issues or delta_notes:
            review["delta_warnings"] = delta_issues + delta_notes

    unit_file.write_text(json.dumps(review, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (outdir / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")

    lines = [f"# 实现代码独立审查 —— {args.scope or args.unit}",
             "", "## 1. 审查总结", "",
             f"- 结论：**{STATUS_SUMMARY[status]}**（`{status}`；round {args.round}）",
             f"- **应审 {expected} / 实审 {reviewed}**" + ("（少审！见问题清单末尾）" if reviewed < expected else ""),
             f"- CLI 状态：`{cli_status}`；失败文件：{len(failed_files)} 个；"
             f"预算击穿：{'是' if budget else '否'}；CLI warnings：{len(warnings)} 条"]
    lines += [f"  - 失败文件：`{p}`" for p in failed_files]
    lines += [f"  - 豁免文件：`{p}`" for p in waived_files]
    lines += [f"  - 复用文件：`{p}`" for p in reused_files]
    lines += [f"  - `{w.get('file', '?')}` [{w.get('type', '?')}] {w.get('message', '')}"
              for w in warnings]
    if args.escalate_to:
        lines += [f"- **升级复议（round ≥ {args.round} 收敛上限）**：→ `{args.escalate_to}`："
                  f"{args.escalate_reason}"]
    if resolves_entries:
        lines += [f"- 跨轮关闭声明：{len(resolves_entries)} 条（`resolves`，由 "
                  f"`review_closure.py` 对账；非门，不改变本报告状态）"]
    if args.delta_only:
        all_delta = delta_issues + delta_notes
        lines += [f"- delta：base `{args.base_sha or '—'}` → head `{head_sha or '—'}`；"
                  f"reviewed_files {len(reviewed_files)} 个；对账 WARN {len(all_delta)} 条"]
        lines += [f"  - {issue}" for issue in all_delta]
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
          f"   CLI {cli_status} failed {len(failed_files)}   checks {len(checks)} + other {len(other)}")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
