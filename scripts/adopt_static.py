"""Adopt 静态抽取编排（RFC-20261119-03 Phase 3）。

只读编排：调用 `adapters/` 里的框架解析器，产出 `.adapter-out/adopt/` 下的
`facts.json` / `ac-draft.json` / `ac-draft.md`。**不执行目标代码、不跑目标仓测试、
不依赖 JDK/Maven/Gradle。** 框架字面量只在 `adapters/`，本脚本保持框架无关。

用法：
    python3 scripts/adopt_static.py --root <项目根> [--out .adapter-out/adopt]
    python3 scripts/adopt_static.py --root <项目根> --verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"
if str(ADAPTERS) not in sys.path:
    sys.path.insert(0, str(ADAPTERS))

import java_tests  # noqa: E402
import java_web  # noqa: E402
import _jpa  # noqa: E402


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(root: Path) -> str:
    try:
        p = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _fingerprints(root: Path) -> dict[str, str]:
    files = java_web.java_sources(root) + java_web.java_sources(root, tests=True)
    out: dict[str, str] = {}
    for f in sorted(set(files)):
        try:
            out[f.relative_to(root).as_posix()] = _sha256(f)
        except OSError:
            continue
    return out


def collect(root: Path) -> dict:
    web = java_web.parse_project(root)
    tests = java_tests.parse_project(root)
    items, enums, _ = _jpa.parse_project(java_web.java_sources(root), root)
    warnings = list(web.get("parse_warnings", [])) + list(tests.get("parse_warnings", []))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(root),
        "root": str(root),
        "source_fingerprints": _fingerprints(root),
        "endpoints": web.get("endpoints", []),
        "entities": items,
        "enums": enums,
        "ac_drafts": tests.get("ac_drafts", []),
        "parse_warnings": warnings,
    }


def _render_md(facts: dict) -> str:
    lines = [
        "# Adopt AC 草稿（静态推导）",
        "",
        "> 本文件由 `scripts/adopt_static.py` 只读生成。所有条目 `confirmed: false`，",
        "> **禁止直接作为验收判据**；必须由人逐条确认后才能进入 PRD。",
        "",
        f"- 生成时间：{facts['generated_at']}",
        f"- commit：{facts['git_commit'] or '（未知）'}",
        f"- 端点：{len(facts['endpoints'])}；实体字段：{len(facts['entities'])}；"
        f"AC 草稿：{len(facts['ac_drafts'])}",
        "",
    ]
    for draft in facts["ac_drafts"]:
        lines.extend([
            f"## {draft['id']} {draft['display_name']}",
            "",
            f"- 来源：`{draft['source']['file']}:{draft['source']['line']}`"
            f" / `{draft['source']['test']}`",
            f"- 置信度：`{draft['confidence']}`；Mock 依赖："
            f"`{str(draft['mock_dependent']).lower()}`；确认：`false`",
            "",
        ])
        if draft["assertions"]:
            lines.append("断言原文：")
            lines.extend(f"- `{a}`" for a in draft["assertions"])
        else:
            lines.append("断言原文：（未抽到可静态判定的断言）")
        lines.append("")
    if facts["parse_warnings"]:
        lines.extend(["## 解析警告", ""])
        lines.extend(f"- {w}" for w in facts["parse_warnings"])
        lines.append("")
    return "\n".join(lines)


def write(root: Path, out_dir: Path) -> dict:
    facts = collect(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "ac-draft.json").write_text(
        json.dumps({"schema_version": 1, "ac_drafts": facts["ac_drafts"]},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "ac-draft.md").write_text(_render_md(facts), encoding="utf-8")
    return facts


def verify(root: Path, out_dir: Path) -> tuple[bool, list[str]]:
    path = out_dir / "facts.json"
    if not path.is_file():
        return False, [f"facts.json 不存在：{path}"]
    try:
        facts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"facts.json 不可读：{exc}"]
    problems: list[str] = []
    for rel, want in (facts.get("source_fingerprints") or {}).items():
        f = root / rel
        if not f.is_file():
            problems.append(f"源文件已删除：{rel}")
            continue
        if _sha256(f) != want:
            problems.append(f"源文件已变化：{rel}")
    return (not problems), problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Adopt 静态抽取（只读）")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default=".adapter-out/adopt")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    if args.verify:
        ok, problems = verify(root, out_dir)
        if args.json:
            print(json.dumps({"ok": ok, "problems": problems}, ensure_ascii=False))
        else:
            print(f"[adopt] stale={'否' if ok else '是'}；{len(problems)} 个问题")
            for p in problems:
                print(f"  - {p}")
        return 0 if ok else 1
    facts = write(root, out_dir)
    if args.json:
        print(json.dumps({
            "ok": True,
            "out": str(out_dir),
            "endpoints": len(facts["endpoints"]),
            "entities": len(facts["entities"]),
            "ac_drafts": len(facts["ac_drafts"]),
            "warnings": len(facts["parse_warnings"]),
        }, ensure_ascii=False))
    else:
        print(f"[adopt] {len(facts['endpoints'])} 端点 / {len(facts['entities'])} 实体字段 / "
              f"{len(facts['ac_drafts'])} AC 草稿 -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
