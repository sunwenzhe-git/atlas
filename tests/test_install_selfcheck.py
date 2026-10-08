#!/usr/bin/env python3
"""atlas 出厂护栏 —— 装配面 ⇔ 包面 ⇔ 契约面（2026-09-28 批 5 后加，事故见 `3508 §112`）。

**事故**：批 1 删掉原型环 5 件包内件，但 `install.sh` 的自检仍 `check` 其中 4 件
⇒ 新项目开户直接以「装配失败」退出（exit 1），且骨架仍创建已退役的 `product/prototype/`。
人眼复核连过两轮（`3508 §101`、`§104`）都没命中 —— 因为它不在 vault↔canonical 的
对账面上。故把三条判据钉成机器门：

  1. **自检引用必须存在**：`install.sh` 每条 `check "<名>" "<路径>"`，凡指向包内
     （`$ATLAS_DEST/...`、`$PATCH_DIR/...`、`$WIRING_DIR/...`）的文件必须在包内存在；
     `$TARGET/...` 是目标项目侧产物，跳过；**无法判定的变量形态 ⇒ FAIL**（fail-closed：
     解析不了不得静默放过，同 `§B106` 的「缺列按最严」）。
  2. **骨架不得复活已退役环的目录**：`install.sh` 建的每个目录，在 `shared/layout.md`
     的目录树里不得标「已退役」（该文件已用此标记，如 `product/prototype/`）。
     一般化的退役登记表（`3508 §95` 定形）落地前，以 layout.md 的标记为准。
  3. **skill 瘦桩引用的契约必须存在**（副本态也能跑）：`skills/*/SKILL.md` 里出现的
     `.atlas/<...>` 路径逐个校验；`{a,b,c}` 花括号展开。事故同族：E1 后瘦桩仍指
     `rings/{prd,prototype,e2e,structure}`。

- 框架无关；纯标准库。判定：全部通过 → 0；任一违规 → 1。
- 副本态（`.atlas/`）没有 `install.sh` ⇒ 判据 1/2 **显式 skip**（`-rs` 可见），不静默通过。

用法：
    python3 test_install_selfcheck.py [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
INSTALL = PKG_ROOT / "install.sh"
LAYOUT = PKG_ROOT / "shared" / "layout.md"

# check "<名>" "<路径>"
CHECK_RE = re.compile(r'^\s*check\s+"([^"]+)"\s+"([^"]+)"', re.M)
# 脚本内简单赋值（用于展开 `$entry` 这类局部变量；不展开保留名）
ASSIGN_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"', re.M)
VAR_USE_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
# `$var` 紧邻非 ASCII（如 `$stale_name（`）⇒ bash 把多字节字符吞进变量名 ⇒
# `set -u` 报 unbound variable，install 半途退出（2026-09-28 实测：该分支只在
# 「目标已有退役桩」时才走到，空目录探针跑不到）⇒ 必须写 `${var}`。
VAR_ADJ_NONASCII_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?[^\x00-\x7f]")
# for d in \ ... do  之间的引号项
SKELETON_RE = re.compile(r"for\s+d\s+in\s+\\?\s*(.*?)\ndo\b", re.S)
QUOTED_RE = re.compile(r'"([^"]+)"')
# SKILL.md 里的 .atlas/... 引用（到 .md/.py 为止；**字符类必须含 `,`** ——
# 否则 `{prd,prototype,e2e,structure}` 整条引用匹配不上，静默不检查。
# 实测：漏 `,` 时变异 M3（把已删环塞回花括号）不咬，门成摆设）
ATLAS_REF_RE = re.compile(r"\.atlas/([A-Za-z0-9_./{},]+\.(?:md|py))")

# 包内变量前缀 → 包内相对目录（$ATLAS_DEST = <目标>/.atlas/，逐字镜像包内布局）
# 非环 skill 白名单（`3509 §95`）：它们不是「环」，不参与环退役对称判据。
NON_RING_SKILLS = ("apply", "design-review", "grill")
PKG_VARS = {
    "$ATLAS_DEST": "",
    "${ATLAS_DEST}": "",
    "$PATCH_DIR": "patches/workflow-plan-apply",
    "${PATCH_DIR}": "patches/workflow-plan-apply",
    "$WIRING_DIR": "patches/project-wiring",
    "${WIRING_DIR}": "patches/project-wiring",
}
# 目标项目侧产物：装配后才存在，不在包内校验
TARGET_VARS = ("$TARGET", "${TARGET}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _expand_locals(raw: str, assigns: dict[str, str], depth: int = 3) -> str:
    """展开脚本内局部变量（如 `$entry`），但**绝不**展开保留名 —— 否则
    `$ATLAS_DEST/shared/x` 会经 `ATLAS_DEST="$TARGET/.atlas"` 被降级成目标侧，
    把包内路径静默放行（门自己变成摆设）。"""
    reserved = {v.strip("${}") for v in list(PKG_VARS) + list(TARGET_VARS)}
    for _ in range(depth):
        new = VAR_USE_RE.sub(
            lambda m: m.group(0) if m.group(1) in reserved else assigns.get(m.group(1), m.group(0)),
            raw)
        if new == raw:
            break
        raw = new
    return raw


def resolve_check_path(raw: str, assigns: dict[str, str] | None = None) -> tuple[str, str]:
    """→ (状态, 包内相对路径)；状态 ∈ {pkg, target, unresolved}。

    判定顺序：先认保留名（包内 / 目标侧），**再**展开局部变量后重试 —— 顺序不能反。
    """
    assigns = assigns if assigns is not None else {}
    for var in TARGET_VARS:
        if raw.startswith(var):
            return "target", ""
    for var, prefix in PKG_VARS.items():
        if raw.startswith(var + "/"):
            rest = raw[len(var) + 1:]
            return "pkg", (f"{prefix}/{rest}" if prefix else rest)
    expanded = _expand_locals(raw, assigns)
    if expanded != raw:
        return resolve_check_path(expanded, assigns)
    return "unresolved", raw


def install_check_paths(text: str) -> list[dict]:
    assigns = dict(ASSIGN_RE.findall(text))
    out: list[dict] = []
    for name, raw in CHECK_RE.findall(text):
        status, pkg = resolve_check_path(raw, assigns)
        out.append({"name": name, "raw": raw, "status": status, "pkg": pkg})
    return out


def install_skeleton_dirs(text: str) -> list[str]:
    m = SKELETON_RE.search(text)
    return QUOTED_RE.findall(m.group(1)) if m else []


def retired_dir_names(layout_text: str) -> set[str]:
    """layout.md 目录树里标「已退役」的行 ⇒ 取该行第一个 `xxx/` 的末段。"""
    out: set[str] = set()
    for line in layout_text.splitlines():
        if "已退役" not in line:
            continue
        m = re.search(r"([A-Za-z0-9_.-]+)/", line)
        if m:
            out.add(m.group(1))
    return out


def skill_stub_dirs() -> list[Path]:
    """瘦桩位置：源包 `skills/*`，或已装配项目的平台目录（副本态无 `skills/`）。
    两种态都要能跑 —— 只在源包跑的门，恰好不在 agent 干活的地方（同 `§B92` 的教训）。"""
    cands = sorted((PKG_ROOT / "skills").glob("*/SKILL.md"))
    if cands:
        return cands
    for rel in (".agents/skills", ".claude/skills", ".codex/skills"):
        d = PKG_ROOT.parent / rel
        if d.is_dir():
            cands = sorted(d.glob("atlas-*/SKILL.md"))
            if cands:
                return cands
    return []


def skill_refs() -> list[dict]:
    """瘦桩里的 .atlas/ 引用（花括号展开）。"""
    out: list[dict] = []
    for stub in skill_stub_dirs():
        for ref in ATLAS_REF_RE.findall(_read(stub)):
            if "{" in ref:
                head, _, tail = ref.partition("{")
                alts, _, rest = tail.partition("}")
                for alt in alts.split(","):
                    out.append({"skill": stub.parent.name, "ref": f"{head}{alt}{rest}"})
            else:
                out.append({"skill": stub.parent.name, "ref": ref})
    return out


def check_install_paths() -> dict:
    text = _read(INSTALL)
    if not text:
        return {"check": "自检引用存在", "ok": True, "skip": True,
                "detail": "包内无 install.sh（副本态：装配面自检只在源包跑）"}
    missing, unresolved = [], []
    for item in install_check_paths(text):
        if item["status"] == "pkg":
            if not (PKG_ROOT / item["pkg"]).exists():
                missing.append(f'{item["name"]} → {item["pkg"]}')
        elif item["status"] == "unresolved":
            unresolved.append(f'{item["name"]} → {item["raw"]}')
    bad = missing + [f"无法判定（fail-closed）: {u}" for u in unresolved]
    return {"check": "自检引用存在", "ok": not bad, "skip": False,
            "detail": ("；".join(bad) if bad else f"{len(install_check_paths(text))} 条自检引用全部可达")}


def check_install_skeleton() -> dict:
    text = _read(INSTALL)
    if not text:
        return {"check": "骨架不含已退役目录", "ok": True, "skip": True,
                "detail": "包内无 install.sh（副本态）"}
    retired = retired_dir_names(_read(LAYOUT))
    dirs = install_skeleton_dirs(text)
    if not dirs:
        return {"check": "骨架不含已退役目录", "ok": False, "skip": False,
                "detail": "未能从 install.sh 解析出骨架目录列表（判据失效，fail-closed）"}
    bad = [d for d in dirs if d.rstrip("/").split("/")[-1] in retired]
    return {"check": "骨架不含已退役目录", "ok": not bad, "skip": False,
            "detail": ("；".join(f"{d} 已在 layout.md 标为已退役" for d in bad) if bad
                       else f"{len(dirs)} 个骨架目录均未标已退役（layout.md 标记口径）")}


def check_skill_refs() -> dict:
    refs = skill_refs()
    if not refs:
        return {"check": "skill 引用可达", "ok": False, "skip": False,
                "detail": "未找到任何 skill 瘦桩（skills/* 与平台目录均无）——判据失效，fail-closed"}
    bad = [f'{r["skill"]} → .atlas/{r["ref"]}' for r in refs if not (PKG_ROOT / r["ref"]).exists()]
    return {"check": "skill 引用可达", "ok": not bad, "skip": False,
            "detail": ("；".join(bad) + "（重跑 install.sh 可修）" if bad
                       else f"{len(refs)} 条 .atlas/ 引用全部存在")}


def check_ring_skill_symmetry() -> dict:
    """**环退役对称**（`3509 §95`）：`rings/<r>/reference.md` ⇔ `skills/atlas-<r>/`。

    退役时两处必须同删 —— E1 的活标本：源包删了 `rings/prototype/` 与 `skills/atlas-prototype/`，
    而 `install.sh` 仍引用它、平台目录里还留着旧桩（三处不一致，人眼两轮未命中）。
    两种态都跑：源包看 `skills/`，副本看平台目录（`skill_stub_dirs()`）。
    """
    stubs = skill_stub_dirs()
    if not stubs:
        return {"check": "环退役对称（rings ⇔ skills）", "ok": False, "skip": False,
                "detail": "未找到任何 skill 瘦桩 —— 判据失效，fail-closed"}
    skills = {p.parent.name[len("atlas-"):] for p in stubs if p.parent.name.startswith("atlas-")}
    rings = {p.parent.name for p in (PKG_ROOT / "rings").glob("*/reference.md")}
    skill_rings = skills - set(NON_RING_SKILLS)
    only_ring = sorted(rings - skill_rings)
    only_skill = sorted(skill_rings - rings)
    bad = ([f"有环无 skill：{only_ring}"] if only_ring else []) \
        + ([f"有 skill 无环：{only_skill}"] if only_skill else [])
    return {"check": "环退役对称（rings ⇔ skills）", "ok": not bad, "skip": False,
            "detail": ("；".join(bad) + "（退役时两处必须同删，`shared/global-rules.md` §11）"
                       if bad else
                       f"{len(rings)} 个环与对应 skill 一一对应（非环 skill：{sorted(NON_RING_SKILLS)}）")}


def check_var_before_nonascii() -> dict:
    text = _read(INSTALL)
    if not text:
        return {"check": "变量名分隔（set -u 安全）", "ok": True, "skip": True,
                "detail": "包内无 install.sh（副本态）"}
    bad = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in VAR_ADJ_NONASCII_RE.finditer(line):
            if not m.group(0).startswith("${"):
                bad.append(f"L{i}: {m.group(0)!r}")
    return {"check": "变量名分隔（set -u 安全）", "ok": not bad, "skip": False,
            "detail": ("；".join(bad) + "（改用 ${var}）" if bad
                       else "install.sh 内无 `$var` 紧邻非 ASCII 的写法")}


def scan() -> list[dict]:
    return [check_install_paths(), check_install_skeleton(), check_skill_refs(),
            check_var_before_nonascii(), check_ring_skill_symmetry()]


def test_install_selfcheck_paths_exist() -> None:
    res = check_install_paths()
    assert res["ok"], res["detail"]


def test_install_skeleton_has_no_retired_ring() -> None:
    res = check_install_skeleton()
    assert res["ok"], res["detail"]


def test_skill_stubs_reference_existing_contracts() -> None:
    res = check_skill_refs()
    assert res["ok"], res["detail"]


def test_install_has_no_var_touching_nonascii() -> None:
    res = check_var_before_nonascii()
    assert res["ok"], res["detail"]


def test_ring_and_skill_are_symmetric() -> None:
    res = check_ring_skill_symmetry()
    assert res["ok"], res["detail"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    checks = scan()
    ok = all(c["ok"] for c in checks)
    if args.json:
        print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print("test_install_selfcheck @ 装配面 ⇔ 包面 ⇔ 契约面")
        for c in checks:
            mark = "skip" if c.get("skip") else ("ok " if c["ok"] else "FAIL")
            print(f"  [{mark}] {c['check']} —— {c['detail']}")
        print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
