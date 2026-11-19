"""atlas 校验器 —— Adopt 静态事实底稿 stale 守卫（RFC-20261119-03 Phase 3a）。

守一件事：`.adapter-out/adopt/facts.json` 里记录的所有源文件 sha256 必须与当前
工作树一致；源变 ⇒ FAIL（stale），但**不输出任何自动重录命令**（R1）。同时守住
AC 草稿的 `confirmed` 必须为 false——静态草稿不得自称已确认。

三态：
  - 未生成 facts.json ⇒ SKIP（前置未就绪，非失败）。
  - 源指纹不一致 / 源文件删除 / facts.json 不可解析 ⇒ FAIL。
  - 全部一致且 AC 草稿未确认 ⇒ PASS。

显式盲区：不判断事实语义是否正确、不执行 Java、不重跑抽取。

CLI：`python3 validate_adopt_facts.py --root <项目根> [--json]`
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

FACTS_REL = Path(".adapter-out") / "adopt" / "facts.json"


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, status: str, detail: str = "") -> None:
        self.checks.append({"check": check, "status": status, "detail": detail})

    @property
    def status(self) -> str:
        statuses = [c["status"] for c in self.checks]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        if statuses and all(s == "SKIP" for s in statuses):
            return "SKIP"
        return "PASS"

    @property
    def ok(self) -> bool:
        return self.status != "FAIL"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_adopt_facts(root: Path) -> Result:
    res = Result()
    path = root / FACTS_REL
    if not path.is_file():
        res.add("facts_exists", "SKIP",
                f"前置未生成（非失败）：无 {FACTS_REL.as_posix()}")
        return res
    try:
        facts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        res.add("facts_parse", "FAIL", f"facts.json 不可解析：{exc}")
        return res

    res.add("facts_parse", "PASS", f"已读取 {FACTS_REL.as_posix()}")
    if facts.get("schema_version") != 1:
        res.add("facts_schema", "FAIL",
                f"schema_version 应为 1，实际 {facts.get('schema_version')!r}")
    else:
        res.add("facts_schema", "PASS", "schema_version=1")

    fps = facts.get("source_fingerprints")
    if not isinstance(fps, dict) or not fps:
        res.add("source_fingerprints", "WARN", "未记录源指纹（无法判 stale）")
    else:
        changed: list[str] = []
        missing: list[str] = []
        for rel, want in fps.items():
            f = root / rel
            if not f.is_file():
                missing.append(rel)
            elif _sha256(f) != want:
                changed.append(rel)
        if changed or missing:
            parts = []
            if changed:
                parts.append(f"已变化 {len(changed)} 个（例：{changed[0]}）")
            if missing:
                parts.append(f"已删除 {len(missing)} 个（例：{missing[0]}）")
            res.add("source_fingerprints", "FAIL",
                    "源指纹不一致：" + "；".join(parts) +
                    "。需重新静态抽取并由人确认差异；不要用脚本批量重录。")
        else:
            res.add("source_fingerprints", "PASS", f"{len(fps)} 个源文件指纹一致")

    drafts = facts.get("ac_drafts")
    if not isinstance(drafts, list):
        res.add("ac_draft_confirmed", "FAIL", "ac_drafts 不是列表")
    else:
        bad = [d.get("id", "?") for d in drafts if d.get("confirmed") is not False]
        if bad:
            res.add("ac_draft_confirmed", "FAIL",
                    f"{len(bad)} 条 AC 草稿 confirmed 非 false（例：{bad[0]}）")
        else:
            res.add("ac_draft_confirmed", "PASS",
                    f"{len(drafts)} 条 AC 草稿均为待确认")
    return res


def main() -> int:
    parser = argparse.ArgumentParser(description="atlas Adopt 静态事实 stale 校验器")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    res = validate_adopt_facts(args.root.resolve())
    if args.json:
        print(json.dumps({"ok": res.ok, "status": res.status, "checks": res.checks},
                         ensure_ascii=False, indent=2))
    else:
        for c in res.checks:
            detail = f" —— {c['detail']}" if c.get("detail") else ""
            print(f"[{c['status']}] {c['check']}{detail}")
        print(f"\nFinal status: {res.status}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
