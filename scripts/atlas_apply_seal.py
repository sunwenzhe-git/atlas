#!/usr/bin/env python3
"""封条签发 / 续签的唯一写入口（RFC-20261111-03 §1.3.6 / §1.4 / §3.2）。

只写 `<assets_root>/reviews/apply/<member>/<task>.seal.json`；锁与锚由
`atlas solution lock --update` 写，本工具不碰锁。

    python3 scripts/atlas_apply_seal.py --root . \
        --seal product/reviews/apply/web/T-001.seal.json \
        --card .trellis/tasks/01-xxx/prd.md --e2e-status ready \
        --case case-login --owner @alice

签发后请提交封条，再跑 `atlas solution lock --update` 并独立提交。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _support.siblings import load_module  # noqa: E402

AC_LINE_RE = re.compile(r"^[ \t]*atlas-acceptance:[ \t]*(.+?)\s*$", re.M)


def _card_acs(card: Path | None) -> list[str]:
    if card is None or not card.is_file():
        return []
    text = card.read_text(encoding="utf-8", errors="replace")
    # 只认代码块外的专用行
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    m = AC_LINE_RE.search(body)
    if not m or m.group(1).startswith("none"):
        return []
    return [t.strip() for t in re.split(r"[,，、]", m.group(1)) if t.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--seal", required=True)
    ap.add_argument("--kind", default="binding",
                    choices=("binding", "backfill", "legacy"))
    ap.add_argument("--card", default=None)
    ap.add_argument("--acceptance-acs", default=None,
                    help="逗号分隔；缺省从 --card 的 atlas-acceptance 行读")
    ap.add_argument("--e2e-status", default="n/a",
                    choices=("ready", "not_ready", "n/a"))
    ap.add_argument("--case", action="append", default=[])
    ap.add_argument("--owner", default=None)
    ap.add_argument("--gap-reason", default=None)
    ap.add_argument("--gap-owner", default=None)
    ap.add_argument("--gap-due", default=None)
    ap.add_argument("--first-seen-at", default=None)
    ap.add_argument("--moved-from", default=None)
    ap.add_argument("--reason", action="append", default=[],
                    help="重签原因（重复给出）")
    ap.add_argument("--previous-case", action="append", default=[],
                    help="换路径 / 改选择器时保留的旧用例 ID")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    solution = load_module("solution")
    seal = load_module("solution_seal")
    try:
        data = solution.load_manifest(root)
        lock = solution.read_lock(root)
        path = args.seal.strip()
        if not seal.is_seal_path(path):
            raise solution.SolutionError(
                f"--seal 必须形如 <assets_root>/reviews/apply/<member>/<task>.seal.json")
        assets_root = path.split("/reviews/apply/", 1)[0]
        if lock and lock.get("layout_assets_root") \
                and assets_root != lock.get("layout_assets_root"):
            raise solution.SolutionError(
                f"--seal 的资产根 {assets_root} 与锁 {lock.get('layout_assets_root')} 不一致")
        if seal.worktree_dirty(root, path):
            raise solution.SolutionError(
                f"{path} 工作树不干净；先提交或还原再签发（封条是唯一写入口）")
        if args.card:
            card_rel = args.card
            if not (root / card_rel).is_file():
                raise solution.SolutionError(f"--card 不存在: {card_rel}")
        acs = ([] if args.acceptance_acs is None
               else [t.strip() for t in
                     re.split(r"[,，、]", args.acceptance_acs) if t.strip()])
        if args.acceptance_acs is None:
            acs = _card_acs(root / args.card if args.card else None)
        gap = None
        if args.e2e_status in ("not_ready", "n/a"):
            if not (args.gap_reason and args.gap_owner and args.gap_due):
                raise solution.SolutionError(
                    "e2e.status 为 not_ready / n/a 时必须给 "
                    "--gap-reason / --gap-owner / --gap-due")
            gap = {"reason": args.gap_reason, "owner": args.gap_owner,
                   "due": args.gap_due}
        if gap is not None:
            # 写侧与读侧同口径（T-32 / §2.4 决策 3）：due 必须是真实日期且落在
            # [exemption_start_origin, min(first_seen_origin+90d, cutover)]。
            # 首签无锁锚时回落到本次签署时刻（compute_anchor 会把它写成 origin）。
            anchor = ((lock or {}).get("seal_anchors") or {}).get(path) or {}
            origin = (anchor.get("exemption_start_origin")
                      or anchor.get("exemption_started_at"))
            first_seen = anchor.get("first_seen_origin") or args.first_seen_at
            if not origin:
                origin = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            probe = {"e2e": {"gap": gap}, "__origin": origin,
                     "__first_seen_origin": first_seen or origin}
            due_findings = seal._due_findings(probe, path, data)
            if due_findings:
                raise solution.SolutionError(due_findings[0]["message"])
        moved_from = ({"path": args.moved_from}
                      if args.moved_from else None)
        payload = seal.build_seal_payload(
            root, data, path, assets_root=assets_root, kind=args.kind,
            card_path=args.card, acceptance_acs=acs,
            e2e_status=args.e2e_status, case_ids=args.case, gap=gap,
            owner=args.owner, first_seen_at=args.first_seen_at,
            moved_from=moved_from, reasons=args.reason)
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    except solution.SolutionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except seal.SealError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    summary = {"seal": str(target), "renewal_seq": payload["renewal_seq"],
               "previous_seal_commit": payload["previous_seal_commit"],
               "upstream": [u["role"] for u in payload["upstream"]],
               "next": "提交封条后运行 atlas solution lock --update 并独立提交"}
    if args.json:
        print(json.dumps({**summary, "payload": payload},
                         ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
