#!/usr/bin/env python3
"""canonical 内**跨文件自洽**（`3509 §B111`，批 6 第 11 项）。

为什么单独一个文件：批 1（E1 契约面）与批 5 的复核都证明「canonical ↔ canonical」这条线上
**没人看** —— `shared/single-source.md` 的 testid 真相源与 `rings/e2e` 相反、`apply/reference.md`
第 29 行说「可临时启用原型环」而第 9 行说「环已移除」、模板的 `prototype:` 段头被删而两个子键
变成孤儿挂在 `knowledge:` 下。三类都属「文本之间互相否定」，而 vault↔canonical 与
装配面两条对账面都照不到它们。

三条判据（全部可机器判）：

  1. **环引用自明**：文本里的 `rings/<x>/`，若 `<x>` 不是现存环 ⇒ **该行必须带退役/历史标记**
     （否则就是「活口径引用已删环」——批次 1/5 缺陷的本体）；
  2. **模板键 ⊆ 契约字段**：`templates/stack-profile.yaml` 的段与子键必须是
     `shared/stack-profile.md` §2 声明过的（实测缺陷：孤儿键 `base_url` / `review` 挂在 `knowledge:` 下）；
  3. **shared 互引可达**：canonical 里引用的 `shared/<x>.md` 必须存在。

**显式盲区**（已写进 `shared/gates.md`）：**契约正文的语义自洽**机器判不了（例：「第 29 行与第 9 行
互相否定」需要读懂句意）⇒ 归人（`shared/closeout.md` 步骤 4 的 vault 同步复核 + 独立复核）。

变异证明：M7 契约里写一个**不带标记**的幽灵环引用 ⇒ 红；M8 模板加一个契约未声明的子键 ⇒ 红；
M9 契约里引用一个不存在的 shared 文件 ⇒ 红。
"""
from __future__ import annotations

import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]

# 退役 / 历史标记：出现这些词的行，允许引用已删环（引用的语境本身说明了它是历史）
RETIRE_MARKS = ("已退役", "退役", "已删", "删除", "已作废", "作废", "已移除", "历史", "冻结", "E1")
# 注意：**不得**把「原」「当时」当标记 —— `原型` 一词包含「原」⇒ 会把活口径引用放行（实测踩到）。
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}
TEXT_EXT = {".md", ".sh", ".py", ".yaml", ".yml", ".json"}


def canonical_text_files() -> list[Path]:
    out: list[Path] = []
    for p in PKG_ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in TEXT_EXT:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def actual_rings() -> set[str]:
    d = PKG_ROOT / "rings"
    return {p.parent.name for p in d.glob("*/reference.md")} if d.is_dir() else set()


def ring_refs() -> list[dict]:
    out: list[dict] = []
    for f in canonical_text_files():
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in re.finditer(r"rings/([a-z0-9-]+)/", line):
                out.append({"file": f.relative_to(PKG_ROOT).as_posix(), "line": i,
                            "ring": m.group(1), "text": line})
    return out


def check_ring_refs_self_marking() -> dict:
    rings = actual_rings()
    refs = ring_refs()
    if not rings or not refs:
        return {"check": "环引用自明", "ok": False, "skip": False,
                "detail": "未扫到环目录或环引用 —— 判据失效，fail-closed"}
    bad = [f"{r['file']}:{r['line']} → rings/{r['ring']}/（该行无退役标记）"
           for r in refs
           if r["ring"] not in rings and not any(mk in r["text"] for mk in RETIRE_MARKS)]
    return {"check": "环引用自明", "ok": not bad, "skip": False,
            "detail": ("；".join(bad[:5]) + "（引用已删环的行必须写明退役/历史）" if bad
                       else f"{len(refs)} 处环引用全部自明（现存环或带退役标记）")}


def contract_sections() -> dict[str, set[str]]:
    """`shared/stack-profile.md` §2 的「段 → 该段声明过的字段 token」。"""
    text = (PKG_ROOT / "shared" / "stack-profile.md").read_text(encoding="utf-8")
    sec = text.split("## 2. 字段契约", 1)[1].split("\n## 3.", 1)[0]
    out: dict[str, set[str]] = {}
    for part in re.split(r"^### ", sec, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        m = re.search(r"`([A-Za-z0-9_]+)", head)
        if not m:
            continue
        out.setdefault(m.group(1), set()).update(re.findall(r"`([A-Za-z0-9_.-]+)`", head + body))
    return out


def template_structure() -> dict[str, list[str]]:
    """`templates/stack-profile.yaml` 的「顶层段 → 子键」（注释行跳过）。"""
    out: dict[str, list[str]] = {}
    cur: str | None = None
    for raw in (PKG_ROOT / "templates" / "stack-profile.yaml").read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("#"):
            continue
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[:1].isspace():
            m = re.match(r"^([a-z_]+):", line)
            cur = m.group(1) if m else None
            if cur:
                out.setdefault(cur, [])
            continue
        if cur:
            m = re.match(r"^\s+(?:-\s+)?([a-z_]+):", line)
            if m:
                out[cur].append(m.group(1))
    return out


def check_template_keys() -> dict:
    sections = contract_sections()
    tpl = template_structure()
    if not sections or not tpl:
        return {"check": "模板键 ⊆ 契约字段", "ok": False, "skip": False,
                "detail": "未解析出契约段或模板段 —— 判据失效，fail-closed"}
    bad: list[str] = []
    for seg, keys in tpl.items():
        if seg not in sections:
            bad.append(f"模板有契约未声明的段 `{seg}:`")
            continue
        for k in keys:
            if k not in sections[seg]:
                bad.append(f"`{seg}.{k}` 不在契约 §2 的该段字段里")
    return {"check": "模板键 ⊆ 契约字段", "ok": not bad, "skip": False,
            "detail": ("；".join(bad[:5]) if bad
                       else f"{len(tpl)} 段 / {sum(len(v) for v in tpl.values())} 键全部在契约 §2 声明过")}


def check_contract_field_refs() -> dict:
    """**契约引用的 `stack-profile` 字段必须在 §2 声明过**（反向判据，`3509 §129`）。

    判据② 是单向的「模板键 ⊆ 契约字段」，挡不住反向缺口 —— 实测：`rings/e2e/reference.md` §5.7
    引用了 `e2e.seed.hook`，而字段契约 `shared/stack-profile.md` §2 的 `e2e` 表里**没有 `seed`**
    （同轮的兄弟字段 `app_login` 在契约 + 模板 + 产品三处都有）。⇒ 反向也要判。
    """
    contract = (PKG_ROOT / "shared" / "stack-profile.md").read_text(encoding="utf-8")
    sections = contract_sections()
    refs: dict[str, set[str]] = {}
    for f in canonical_text_files():
        if f.name == "stack-profile.md":
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        # `DESIGN.md` §12（决策记录）**整节自声明为历史**（表头写明「保留原文，供追溯」）⇒ 整节豁免；
        # 其余位置按「退役语境」逐行判（与判据① 同规则）。
        hist = range(0, 0)
        if f.name == "DESIGN.md":
            try:
                a = next(i for i, l in enumerate(lines) if l.startswith("## 12. 决策记录"))
                b = next(i for i, l in enumerate(lines) if l.startswith("## 13."))
                hist = range(a, b)
            except StopIteration:
                hist = range(0, 0)
        for i, line in enumerate(lines, 1):
            if (i - 1) in hist:
                continue
            if any(mk in line for mk in RETIRE_MARKS):
                continue
            for m in re.finditer(r"`(e2e|knowledge|adapters|apps|prototype)\.([a-z_]+)(?:\.[a-z_]+)?`", line):
                # 排除**文件名**（`shared/knowledge.md` 会被上面的正则读成 段=knowledge / 字段=md）
                if m.group(2) in ("md", "py", "json", "yaml", "yml", "sh", "ts", "tsx", "js", "txt"):
                    continue
                refs.setdefault(f"{m.group(1)}.{m.group(2)}", set()).add(
                    f"{f.relative_to(PKG_ROOT).as_posix()}:{i}")
    bad: list[str] = []
    for ref, where in sorted(refs.items()):
        seg, _, name = ref.partition(".")
        if seg not in sections or name not in sections[seg]:
            bad.append(f"`{ref}`（{sorted(where)[0]}）被引用但 §2 未声明")
    return {"check": "契约字段引用可达（反向）", "ok": not bad, "skip": False,
            "detail": ("；".join(bad[:5]) + "（契约引用的字段必须在 `shared/stack-profile.md` §2 声明，"
                       "退役语境除外）" if bad
                       else f"{len(refs)} 处字段引用全部在 §2 声明过（退役语境已排除）")}


def check_shared_refs() -> dict:
    files = {p.name for p in (PKG_ROOT / "shared").glob("*.md")}
    if not files:
        return {"check": "shared 互引可达", "ok": False, "skip": False,
                "detail": "shared/ 下无 .md —— 判据失效，fail-closed"}
    refs: dict[str, list[str]] = {}
    for f in canonical_text_files():
        for m in re.finditer(r"(?:\.atlas/)?shared/([a-z0-9-]+\.md)", f.read_text(encoding="utf-8", errors="replace")):
            refs.setdefault(m.group(1), []).append(f.relative_to(PKG_ROOT).as_posix())
    bad = [f"{r}（被 {len(w)} 处引用，例：{w[0]}）" for r, w in sorted(refs.items()) if r not in files]
    return {"check": "shared 互引可达", "ok": not bad, "skip": False,
            "detail": ("；".join(bad[:5]) if bad
                       else f"{len(refs)} 个被引用的 shared 文件全部存在（共 {len(files)} 份）")}


def check_registry_counts() -> dict:
    """**门总账里的计数必须与实况一致**（`3509 §B105` 的教训：写死计数无对账）。

    2026-09-28 独立审计拒收的直接原因之一：`gates.md` 写着「自检 31 项」「14 个测试文件 / 14/14」，
    而实况是 35 条 `check` 声明、16 个测试文件 —— **计数类陈述无门可判**。本判据把这三处钉住。
    """
    gates = (PKG_ROOT / "shared" / "gates.md").read_text(encoding="utf-8")
    # `install.sh` 是**源包专属件**（不装配进 `.atlas/`）⇒ 副本态跳过该子项（显式，不静默）。
    install_file = PKG_ROOT / "install.sh"
    install = install_file.read_text(encoding="utf-8") if install_file.is_file() else ""
    n_tests = len(list((PKG_ROOT / "tests").glob("test_*.py")))
    n_checks = len(re.findall(r"^check ", install, re.M))
    bad: list[str] = []
    for m in re.finditer(r"(\d+)\s*个\**\s*测试文件", gates):
        if int(m.group(1)) != n_tests:
            bad.append(f"「{m.group(1)} 个测试文件」≠ 实际 {n_tests}")
    for m in re.finditer(r"移除后\s*\**(\d+)/(\d+)\**", gates):
        if int(m.group(1)) != n_tests or int(m.group(2)) != n_tests:
            bad.append(f"「{m.group(1)}/{m.group(2)}」≠ 实际 {n_tests}/{n_tests}")
    if install:
        for m in re.finditer(r"自检（\**(\d+)\s*条\s*`check`\s*声明", gates):
            if int(m.group(1)) != n_checks:
                bad.append(f"「自检 {m.group(1)} 条 check 声明」≠ 实际 {n_checks}")
    # 校验器行数：`gates.md` 的「数量 = … 当前 N」必须 = `atlas_check.VALIDATORS` 长度
    ac = (PKG_ROOT / "scripts" / "atlas_check.py").read_text(encoding="utf-8")
    vm = re.search(r"^VALIDATORS = \(([^)]*)\)", ac, re.M)
    n_validators = len([x for x in vm.group(1).split(",") if x.strip()]) if vm else -1
    for m in re.finditer(r"当前\s*(\d+)\s*\)", gates):
        if int(m.group(1)) != n_validators:
            bad.append(f"「校验器数量 当前 {m.group(1)}」≠ 实际 {n_validators}")
    # 状态复述必漂（`3509 §126` 审计教训）：DESIGN.md §13 只准放指针，不得写推进状态。
    # `DESIGN.md` 与 `install.sh` 同为**源包专属件**（不装配进 `.atlas/`）⇒ 副本态显式跳过。
    design_file = PKG_ROOT / "DESIGN.md"
    design = design_file.read_text(encoding="utf-8") if design_file.is_file() else ""
    if design:
        sec13 = design.split("## 13. 待实现事项", 1)[-1].split("\n## 14.", 1)[0]
        for w in ("未落地", "落地未做", "尚无批次号", "已落地"):
            if w in sec13:
                bad.append(f"DESIGN.md §13 出现推进状态词「{w}」（本节只准放指针，状态归 `3509` 批 6 登记）")
    # 逐文件「N 条」：`gates.md` 里的 `tests/<file>.py` 后随的「N 条」必须 = 该文件 `def test_` 数
    # （2026-09-28 第三轮审计：此处曾写「55 条」而实为 54 —— 白名单只盯固定句式会漏逐文件计数）
    for m in re.finditer(r"`tests/([\w.]+\.py)`[^|]{0,80}?(\d+)\s*条", gates):
        f, n = m.group(1), int(m.group(2))
        pf = PKG_ROOT / "tests" / f
        if not pf.is_file():
            bad.append(f"gates.md 引用了不存在的测试文件 tests/{f}")
            continue
        real = len(re.findall(r"^def test_", pf.read_text(encoding="utf-8"), re.M))
        if n != real:
            bad.append(f"「tests/{f} {n} 条」≠ 实际 {real}")
    # 同一类：`DESIGN.md` 里若写死「N 个校验器」，必须 = `validators/validate_*.py` 数
    n_vfiles = len(list((PKG_ROOT / "validators").glob("validate_*.py")))
    for m in re.finditer(r"(\d+)\s*个校验器", design):
        if int(m.group(1)) != n_vfiles:
            bad.append(f"DESIGN.md 写「{m.group(1)} 个校验器」≠ 实际 {n_vfiles}")
    skips = []
    if not install:
        skips.append("副本态无 `install.sh` ⇒ 自检项数子项跳过")
    if not design:
        skips.append("副本态无 `DESIGN.md` ⇒ §13 状态词子项跳过")
    skipped = ("；" + "；".join(skips) + "（都不是通过）") if skips else ""
    return {"check": "门总账计数/状态对账", "ok": not bad, "skip": False,
            "detail": ("；".join(bad) + "（写死计数/复述状态必须随实况改，`3509 §B105`/`§125`）" if bad
                       else f"计数与状态与实际一致（测试文件 {n_tests}；自检 {n_checks} 条；校验器 {n_validators}；§13 无状态词）{skipped}")}


def scan() -> list[dict]:
    return [check_ring_refs_self_marking(), check_template_keys(), check_shared_refs(),
            check_registry_counts(), check_contract_field_refs()]


def test_contract_field_references_are_declared() -> None:
    res = check_contract_field_refs()
    assert res["ok"], res["detail"]


def test_ring_refs_are_self_marking() -> None:
    res = check_ring_refs_self_marking()
    assert res["ok"], res["detail"]


def test_template_keys_are_declared_in_contract() -> None:
    res = check_template_keys()
    assert res["ok"], res["detail"]


def test_shared_references_resolve() -> None:
    res = check_shared_refs()
    assert res["ok"], res["detail"]


def test_registry_counts_match_reality() -> None:
    """`gates.md` 的计数陈述 + `DESIGN.md §13` 的状态词禁令必须成立（`3509 §B105` / `§125`）。

    本判据是**固定句式白名单**（只覆盖已出现过的写法）—— `§126` 已指出这一局限：
    它判不了「换了写法的计数陈述」或其它文档里的状态矛盾；新增写法时须同步扩白名单。
    """
    res = check_registry_counts()
    assert res["ok"], res["detail"]



def check_gates_gates_are_scheduled() -> dict:
    """判据⑥（`3509 §B120`）：gates.md 2.1 登记的每个 `validators/validate_*.py`
    必须被 `atlas_check.VALIDATORS` 调度 —— 「在册不在跑」= 门失效本体（B120 的根）。
    连带把 2.2 的「数量 = VALIDATORS 长度，当前 N」钉到 len(VALIDATORS)，防计数漂移。

    变异证明 M27：从 `VALIDATORS` 摘掉一项 ⇒ 本判据红；还原 ⇒ 绿。
    """
    gates = (PKG_ROOT / "shared" / "gates.md").read_text(encoding="utf-8")
    parts = re.split(r"^### 2\.1 ", gates, maxsplit=1, flags=re.M)
    sec21 = re.split(r"^### 2\.2 ", parts[1], maxsplit=1, flags=re.M)[0] if len(parts) > 1 else ""
    registered: set[str] = set()
    for line in sec21.splitlines():
        if not line.startswith("| `"):
            continue
        cell = line.split("|")[1].strip().strip("`")
        m = re.fullmatch(r"validators/(validate_[a-z0-9_]+)\.py", cell)
        if m:
            registered.add(m.group(1))
    if not registered:
        return {"ok": False,
                "detail": "gates.md 2.1 未解析出任何 validators/validate_*.py 门 —— 判据失效，fail-closed"}
    ac = (PKG_ROOT / "scripts" / "atlas_check.py").read_text(encoding="utf-8")
    mv = re.search(r"VALIDATORS = \(([^)]*)\)", ac, re.S)
    if not mv:
        return {"ok": False, "detail": "atlas_check.py 未解析出 VALIDATORS —— 判据失效，fail-closed"}
    scheduled = set(re.findall(r'"(validate_[a-z0-9_]+)"', mv.group(1)))
    missing = sorted(registered - scheduled)
    if missing:
        return {"ok": False,
                "detail": f"2.1 登记但未被 atlas_check 调度：{missing}（§B120：在册不在跑 = 门失效）"}
    mc = re.search(r"数量 = `atlas_check\.VALIDATORS` 长度，当前 (\d+)", gates)
    if not mc:
        return {"ok": False, "detail": "gates.md 2.2 无「数量 = VALIDATORS 长度，当前 N」陈述 —— 判据失效"}
    if int(mc.group(1)) != len(scheduled):
        return {"ok": False,
                "detail": f"2.2 计数陈述「当前 {mc.group(1)}」≠ VALIDATORS 长度 {len(scheduled)}"}
    return {"ok": True,
            "detail": f"2.1 机器门 {len(registered)} 个全部被调度；2.2 计数一致（{len(scheduled)}）"}


def test_gate_registry_gates_are_scheduled_by_atlas_check() -> None:
    """判据⑥（`§B120`）：在册的每道机器门必须有调度者。"""
    res = check_gates_gates_are_scheduled()
    assert res["ok"], res["detail"]


def main() -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    checks = scan()
    ok = all(c["ok"] for c in checks)
    if args.json:
        print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print("test_canonical_consistency @ canonical 内跨文件自洽")
        for c in checks:
            print(f"  [{'ok ' if c['ok'] else 'FAIL'}] {c['check']} —— {c['detail']}")
        print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
