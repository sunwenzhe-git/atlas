#!/usr/bin/env python3
"""`apply backfill`（回流原语）的**契约符合性**判据（`3509 §99` 定形，批 6 第 6 项）。

**这是弱判据，必须显式声明**：它只检查「契约里这四项还在不在」（形态），
**不构成**「回填流程被正确执行」的证明 —— 执行面归 agent 纪律 + 各环门 + 台账挪卷
（`shared/gates.md` 的流程门行 + `shared/closeout.md`）。之所以仍要它：`§B74` 的教训是
「契约承诺存在但没人读 ⇒ 空头契约」，一条形态判据至少让这四项**不会静默消失**。

四项（缺一即 FAIL）：
  1. 模式表含 `backfill` 行；
  2. §5.2 回流原语小节存在；
  3. **分组**（按「上游目标 + 改动类型」）+ **攒批**（≤ 10 条/批）；
  4. **独立写面**（走 §5.1 仲裁）+ **闭环钩子**三条（下游重跑/重审 + 台账挪卷 + 各环门照跑）。

变异证明：M11 删掉「攒批 ≤ 10 条」⇒ 红；M12 删掉「台账随批挪卷」⇒ 红。
"""
from __future__ import annotations

from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = PKG_ROOT / "apply" / "reference.md"


def stub_path() -> Path | None:
    """瘦桩位置：源包 `skills/atlas-apply/SKILL.md`，或已装配项目的平台目录。

    副本态（`.atlas/`）**没有 `skills/`**（瘦桩装在 `.agents/skills/` / `.claude/skills/`）
    ⇒ 直接读 `PKG_ROOT/skills/...` 会在副本里报「缺文件」（实测：本文件首版就错了，
    出厂绿而副本 2 条红）。同 `test_install_selfcheck.skill_stub_dirs()` 的处理方式。
    """
    cand = PKG_ROOT / "skills" / "atlas-apply" / "SKILL.md"
    if cand.is_file():
        return cand
    for rel in (".agents/skills", ".claude/skills", ".codex/skills"):
        c = PKG_ROOT.parent / rel / "atlas-apply" / "SKILL.md"
        if c.is_file():
            return c
    return None

# (检查名, 必须同时出现的片段, 作用域)：作用域 `whole` = 全文；`5.2` = **只在 §5.2 小节内**。
# 为什么要限作用域：`≤ 10 条` 这类片段在**模式表里也出现** ⇒ 全文匹配时删掉 §5.2 里的那一份
# 仍然会通过（实测 M11 第一次没咬就是这个原因）。
REQUIRED = (
    ("模式表含 backfill 行", ("| **`backfill`**", "回流原语"), "whole"),
    ("§5.2 回流原语小节存在", ("### 5.2 回流原语",), "whole"),
    ("分组与攒批", ("上游目标 + 改动类型", "攒批", "≤ 10 条"), "5.2"),
    ("独立写面与闭环钩子", ("独立写面", "§5.1", "台账条目**随批收口挪卷**", "各环门照跑"), "5.2"),
    ("分型（裁决 / 退役各有通道）", ("裁决队列本体", "生命周期（`shared/global-rules.md` §11）"), "5.2"),
)


def section_52(text: str) -> str:
    """取 `### 5.2` 到下一个 `## ` / `### ` 之间的正文（不存在则返回空串）。"""
    i = text.find("### 5.2")
    if i < 0:
        return ""
    rest = text[i:]
    j = rest.find("\n## ", 1)
    k = rest.find("\n### ", 1)
    ends = [x for x in (j, k) if x > 0]
    return rest[: min(ends)] if ends else rest


def scan() -> list[dict]:
    text = CONTRACT.read_text(encoding="utf-8") if CONTRACT.is_file() else ""
    stub_file = stub_path()
    stub = stub_file.read_text(encoding="utf-8") if stub_file else ""
    if not text or not stub:
        return [{"check": "契约与瘦桩存在", "ok": False,
                 "detail": f"缺文件：契约={CONTRACT.is_file()} 瘦桩={stub_file}"}]
    out = [{"check": "契约与瘦桩存在", "ok": True, "detail": "apply/reference.md + skills/atlas-apply/SKILL.md"}]
    sec = section_52(text)
    for name, frags, scope in REQUIRED:
        body = text if scope == "whole" else sec
        missing = [f for f in frags if f not in body]
        where = "" if scope == "whole" else "（限 §5.2）"
        out.append({"check": name + where, "ok": not missing,
                    "detail": f"缺片段：{missing}" if missing else f"{len(frags)} 个片段齐"})
    out.append({"check": "瘦桩声明第 4 模式", "ok": "backfill" in stub,
                "detail": "" if "backfill" in stub else "skills/atlas-apply/SKILL.md 未提 backfill"})
    return out


def test_backfill_mode_is_documented() -> None:
    """四项（模式行 / §5.2 / 分组攒批 / 写面与闭环钩子）必须同时在契约里。"""
    bad = [c for c in scan() if not c["ok"]]
    assert not bad, "；".join(f"{c['check']}：{c['detail']}" for c in bad)


def test_backfill_stub_mentions_mode() -> None:
    """瘦桩必须能触发该模式（description 是 skill 唯一的触发面）。"""
    stub = stub_path()
    assert stub is not None, "未找到 atlas-apply 瘦桩（源包 skills/ 与平台目录均无）"
    assert "backfill" in stub.read_text(encoding="utf-8")


def main() -> int:
    import json
    import sys
    checks = scan()
    ok = all(c["ok"] for c in checks)
    if "--json" in sys.argv:
        print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print("test_backfill_contract @ apply backfill 契约符合性（弱判据：形态）")
        for c in checks:
            print(f"  [{'ok ' if c['ok'] else 'FAIL'}] {c['check']} —— {c['detail']}")
        print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
