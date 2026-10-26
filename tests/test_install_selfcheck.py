#!/usr/bin/env python3
"""atlas 出厂护栏 —— 装配面 ⇔ 包面 ⇔ 契约面（2026-09-28 批 5 后加，事故见 `3508 §112`）。

**事故**：批 1 删掉原型环 5 件包内件，但 `install.sh` 的自检仍 `check` 其中 4 件
⇒ 新项目开户直接以「装配失败」退出（exit 1），且骨架仍创建已退役的 `product/prototype/`。
人眼复核连过两轮（`3508 §101`、`§104`）都没命中 —— 因为它不在 vault↔canonical 的
对账面上。故把下面几条判据钉成机器门：

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
  4. **`$var` 紧邻非 ASCII 必须写 `${var}`**（`set -u` 下会被吞进变量名 ⇒ 半途退出）。
  5. **环退役对称**（`rings/<r>/reference.md` ⇔ `skills/atlas-<r>/`）。
  6. **首建提示的两条硬约束**（2026-10-15 加）：`say` 行不得残留已退役环名（首建者是纯
     噪声，与判据 1 同族），且存量（`atlas-apply adopt`）与全新（`atlas-apply all`）两条
     开户入口都要在 —— 只给全新那条，存量项目开户即无从下手。

- 框架无关；纯标准库。判定：全部通过 → 0；任一违规 → 1。
- 副本态（`.atlas/`）没有 `install.sh` ⇒ 判据 1/2/4/6 **显式 skip**（`-rs` 可见），不静默通过。

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
# `say "..."` 整行（用户可见输出；判据 6 用）
SAY_RE = re.compile(r'\bsay\s+"(.*)"\s*$')
# 已退役环在提示里的残留词（判据 6 ①）：`rings/prototype/` 已删，中英文两种写法都不该露脸
RETIRED_RING_WORDS = ("原型", "prototype")
# 开户两条入口（判据 6 ②）：存量 adopt / 全新 all。只给一条 ⇒ 另一种形态的项目开户即无从下手
HINT_ENTRIES = ("atlas-apply adopt", "atlas-apply all")

# 包内变量前缀 → 包内相对目录（$ATLAS_DEST = <目标>/.atlas/，逐字镜像包内布局）
# 非环 skill 白名单（`3509 §95`）：它们不是「环」，不参与环退役对称判据。
NON_RING_SKILLS = ("apply", "design-review", "grill", "release")
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


def install_say_lines(text: str) -> list[str]:
    """install.sh **打到用户眼前**的行（`say "..."`；注释与普通语句不算）。

    只看注释不算数：判据要守的是首建者读到的那几行。
    """
    out: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = SAY_RE.search(line)
        if m:
            out.append(m.group(1))
    return out


def check_first_run_hint() -> dict:
    """首建提示（`say` 行）的两条硬约束（2026-10-15 重写后加，M50）。

    **缺陷本体**：首建尾巴原本挂着「（E1：原型环已移除）」—— 对刚装完的人是纯噪声，
    且与 ① 同族（源包已删环、提示还提它）；同时只给全新项目的全量环入口
    （`atlas-apply all`），**存量项目照着做是错的形态**（存量该走 `atlas-apply adopt`：
    只登记基线，不逆向考古）——开户时无从下手。两条都判：
      ① **无退役环残留**：`say` 行不得出现已退役环名（`原型` / `prototype`）；
      ② **双入口齐备**：存量（`atlas-apply adopt`）与全新（`atlas-apply all`）都要出现。
    """
    text = _read(INSTALL)
    if not text:
        return {"check": "首建提示（退役环残留 / 双入口）", "ok": True, "skip": True,
                "detail": "包内无 install.sh（副本态：装配面自检只在源包跑）"}
    lines = install_say_lines(text)
    if not lines:
        return {"check": "首建提示（退役环残留 / 双入口）", "ok": False, "skip": False,
                "detail": "未能从 install.sh 解析出任何 `say` 行（判据失效，fail-closed）"}
    bad = [f"提示残留退役环名「{w}」：{ln.strip()}"
           for ln in lines for w in RETIRED_RING_WORDS if w in ln]
    joined = "\n".join(lines)
    bad += [f"提示缺开户入口「{e}」" for e in HINT_ENTRIES if e not in joined]
    return {"check": "首建提示（退役环残留 / 双入口）", "ok": not bad, "skip": False,
            "detail": ("；".join(bad) + "（退役即删，提示里不留历史括注；两条入口见 `apply/reference.md` §1）"
                       if bad else
                       f"{len(lines)} 条用户可见 `say` 行：无退役环残留，双开户入口齐备")}


def scan() -> list[dict]:
    return [check_install_paths(), check_install_skeleton(), check_skill_refs(),
            check_var_before_nonascii(), check_ring_skill_symmetry(), check_first_run_hint()]


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


def test_first_run_hint_has_no_retired_ring_and_both_entries() -> None:
    res = check_first_run_hint()
    assert res["ok"], res["detail"]


def test_update_guard_refuses_dirty_touchpoints_and_force_overrides() -> None:
    """F34（R7，2026-10-15）：--update 的触点脏树守卫必须位于整包拷贝（rm -rf）**之前**
    —— 位置回归钉：改 .atlas/VERSION 后跑 update ⇒ exit 1 且未提交的 VERSION **未被
    rm -rf 卷走**；--force ⇒ 放行整包覆盖（守卫通知可见）。R6 现场教训（并行终端共写仓库
    致提交归属污染）的产品化。"""
    import subprocess
    import tempfile

    if not INSTALL.is_file():
        import pytest
        pytest.skip("包内无 install.sh（副本态）—— F34 集成用例要求源包态执行", allow_module_level=False)

    def sh(*a: str):
        r = subprocess.run(a, capture_output=True, env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin",
                                                        "LANG": "C.UTF-8"})
        return r.returncode, r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "proj"
        (root / ".atlas" / "scripts").mkdir(parents=True)
        (root / ".atlas" / "VERSION").write_text("stamped-by-fixture\n", encoding="utf-8")
        (root / ".trellis").mkdir()
        (root / ".trellis" / "workflow.md").write_text("# w\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        sh("git", "-C", str(root), "init", "-q")
        sh("git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
        sh("git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
           "commit", "-qm", "init")
        # 制造脏触点（.atlas 内未提交改动）
        (root / ".atlas" / "VERSION").write_text("dirty local edit\n", encoding="utf-8")
        r = sh("bash", str(PKG_ROOT / "install.sh"),
               "--update", "--target", str(root),
               "--no-skill", "--no-patch", "--no-wiring")
        assert r[0] == 1, r[1]
        assert "装配触点存在未提交改动" in r[1], r[1]
        # 位置钉：守卫在整包拷贝之前 ⇒ 未提交的 VERSION 未被 rm -rf 卷走
        assert (root / ".atlas" / "VERSION").read_text(encoding="utf-8") == "dirty local edit\n"
        # --force 放行：整包覆盖（源包拷入），守卫通知可见
        r2 = sh("bash", str(PKG_ROOT / "install.sh"),
                "--update", "--target", str(root),
                "--no-skill", "--no-patch", "--no-wiring", "--force")
        assert r2[0] == 0, r2[1]
        assert "感知到装配触点未提交改动" in r2[1], r2[1]
        stamped = (root / ".atlas" / "VERSION").read_text(encoding="utf-8")
        assert stamped != "dirty local edit\n" and stamped.count("\n") == 3, stamped
        # RFC-20261023-02 ②：真装配同点落基线 manifest（install.sh 落戳后硬校验其在场）。
        assert (root / ".atlas" / "MANIFEST.json").is_file(), "真装配未落下 .atlas/MANIFEST.json"


def test_f54_dry_run_writes_nothing_and_leaves_no_residue_on_fresh_target() -> None:
    """F54（issue #21，D92，2026-10-16）：--dry-run 不得产生任何装配态变更。

    恒等铁律「干跑不干」的破例闪位：版本戳落盘是旧脚本的唯一裸写（run() 外、无
    DRY_RUN 判据）⇒ `--update --dry-run` 里守卫被预览语义放行、载荷一文件未拷，
    戳却被更新为源包当前摘要 ⇒ 配合一次被守卫拒住的真跑 = 副本「戳新/内容旧」，
    而装配版本门（自写自读闭环）读到新戳报 ok「一致」。同族面：干跑首装经
    stamp_file 的 mkdir 残留 `<target>/.atlas/` ⇒ 卡随后的真首装（临时守卫判
    「已装配过」恒拒）。钉对两态双证：存量装配干跑 ⇒ VERSION 逐字节不变；全新
    target 干跑 ⇒ `.atlas/` 不在场。交互场景（干跑 + 被拒真跑）的完整时序在
    install.sh 内由同一闸门收口，不再单测硬排时序。
    """
    import subprocess
    import tempfile

    if not INSTALL.is_file():
        import pytest
        pytest.skip("包内无 install.sh（副本态）—— F54 集成用例要求源包态执行", allow_module_level=False)

    def sh(*a: str):
        r = subprocess.run(a, capture_output=True, env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin",
                                                        "LANG": "C.UTF-8"})
        return r.returncode, r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")

    with tempfile.TemporaryDirectory() as td:
        # ① 存量装配态干跑：VERSION 逐字节不变（旧路径 ⇒ 被真写为源包摘要 ⇒ 红）
        root = Path(td) / "proj"
        (root / ".atlas" / "scripts").mkdir(parents=True)
        (root / ".trellis").mkdir()
        (root / ".atlas" / "VERSION").write_text(
            "f54-fixture-stamp\n2026-10-16T00:00:00+08:00\nnowhere\n", encoding="utf-8")
        # RFC-20261023-02 ②（B2）：基线 manifest 也是装配态——干跑同样不得动它。
        (root / ".atlas" / "MANIFEST.json").write_text(
            '{"digest": "f54-fixture-stamp", "files": {"x": "y"}}\n', encoding="utf-8")
        before = (root / ".atlas" / "VERSION").read_bytes()
        before_m = (root / ".atlas" / "MANIFEST.json").read_bytes()
        r = sh("bash", str(PKG_ROOT / "install.sh"),
               "--update", "--target", str(root),
               "--no-skill", "--no-patch", "--no-wiring", "--dry-run")
        assert r[0] == 0, r[1]
        assert "[dry-run] 装配版本戳" in r[1], r[1]
        assert (root / ".atlas" / "VERSION").read_bytes() == before, "干跑真写了版本戳（恒等铁律破例）"
        assert (root / ".atlas" / "MANIFEST.json").read_bytes() == before_m, \
            "干跑真写了装配基线 manifest（M-new-5：摘干跑闸 ⇒ 本断言红）"

        # ② 全新 target 干跑：不残留 <target>/.atlas/（旧路径 stamp_file mkdir 副作用 ⇒ 红）
        fresh = Path(td) / "fresh"
        (fresh / ".trellis").mkdir(parents=True)   # 免 .trellis 缺席走 --force 预拦链路
        r2 = sh("bash", str(PKG_ROOT / "install.sh"),
                "--force", "--dry-run", "--target", str(fresh))
        assert r2[0] == 0, r2[1]
        assert not (fresh / ".atlas").exists(), "干跑首装残留 .atlas/（stamp_file mkdir 副作用）"


def test_f55_update_untracked_touchpoint_warns_and_proceeds_tracked_dirty_still_blocks() -> None:
    """F55（issue #22，D93，2026-10-16）：脏树守卫按 porcelain 状态列分两个真语义。

    整目录未跟踪（porcelain 折叠 `?? .atlas/`，git 无改动基线可护，属「包产物不入库」
    的合法形态）⇒ 不构成「脏」：WARN 放行，--update 不再恒拒 ⇒ --force 不再被逼成
    常规；WARN 必须双摘要可见化（副本版本戳 ⇔ 当前源包摘要——评审 B-1 下限口径）。
    已跟踪触点的未提交改动 ⇒ 拒路径逐字节不变（F34 主语义），且两桶皆非空时拒优先，
    拒绝不被可放行项遮蔽。

    变异口径：**前半**（未跟踪 ⇒ 放行）是变异钉——退回「只看路径列」⇒ 本测红
    （M78）；**后半**（已跟踪脏 ⇒ 拒 / --force 过）在旧路径本就绿，是防回归钉；
    **M77**（摘 F54 干跑闸）由上一条用例红。WARN 的双摘要文案带「当前源包」字样
    （匹配与不匹配两分支同查，避免对源包并发变更计时敏感——本仓并行会话常态）。
    """
    import subprocess
    import tempfile

    if not INSTALL.is_file():
        import pytest
        pytest.skip("包内无 install.sh（副本态）—— F55 集成用例要求源包态执行", allow_module_level=False)

    def sh(*a: str):
        r = subprocess.run(a, capture_output=True, env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin",
                                                        "LANG": "C.UTF-8"})
        return r.returncode, r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")

    def g(*a: str, cwd: Path):
        env = dict({"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "LANG": "C.UTF-8",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        r = subprocess.run(a, capture_output=True, env=env, cwd=str(cwd))
        assert r.returncode == 0, r.stdout + r.stderr
        return r

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "proj"
        (root / ".atlas" / "scripts").mkdir(parents=True)
        (root / ".atlas" / "VERSION").write_text("f55-fixture-stamp\nwhen\nnowhere\n", encoding="utf-8")
        (root / ".trellis").mkdir()
        (root / ".trellis" / "workflow.md").write_text("# w\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        g("git", "init", "-q", cwd=root)
        # 只提交指针文件，**有意不 add .atlas/** —— 拟 issue #22 现场形态（版面产物不入库）
        g("git", "add", "AGENTS.md", ".trellis/workflow.md", cwd=root)
        g("git", "commit", "-qm", "init", cwd=root)

        # 前半（变异钉 M78）：未跟踪 ⇒ WARN 放行，不再恒拒
        r = sh("bash", str(PKG_ROOT / "install.sh"),
               "--update", "--target", str(root),
               "--no-skill", "--no-patch", "--no-wiring")
        assert r[0] == 0, r[1]
        assert "未跟踪项" in r[1], r[1]
        assert "装配触点存在未提交改动" not in r[1], r[1]
        assert "当前源包" in r[1], r[1]   # 双摘要可见化（评审 B-1）
        stamped = (root / ".atlas" / "VERSION").read_text(encoding="utf-8").splitlines()[0]
        assert stamped != "f55-fixture-stamp" and len(stamped) == 16, r[1]  # 整包真刷新了

        # 后半（回归钉）：已跟踪脏 ⇒ 拒优先，--force 越过（F34 文案逐字节保留）
        (root / "AGENTS.md").write_text("# agents\n# dirty local edit\n", encoding="utf-8")
        r2 = sh("bash", str(PKG_ROOT / "install.sh"),
                "--update", "--target", str(root),
                "--no-skill", "--no-patch", "--no-wiring")
        assert r2[0] == 1, r2[1]
        assert "装配触点存在未提交改动" in r2[1], r2[1]
        r3 = sh("bash", str(PKG_ROOT / "install.sh"),
                "--update", "--target", str(root),
                "--no-skill", "--no-patch", "--no-wiring", "--force")
        assert r3[0] == 0, r3[1]
        assert "感知到装配触点未提交改动" in r3[1], r3[1]
        assert "另有未跟踪项" in r3[1], r3[1]   # 两桶可比可见，拒通知不吞未跟踪面

        # --force 不改指针文件（守卫只是放行，AGENTS.md 脏改动仍在场）⇒ 还原后复跑
        (root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        r4 = sh("bash", str(PKG_ROOT / "install.sh"),
                "--update", "--target", str(root),
                "--no-skill", "--no-patch", "--no-wiring")
        assert r4[0] == 0, r4[1]
        assert "当前源包" in r4[1], r4[1]


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


def test_layout_config_first_install_docs_and_update_readonly() -> None:
    """RFC-20261026-01：首装写配置 / 模板渲染 / update 只读 / 非法配置零写 / 双根拒绝。"""
    import subprocess
    import tempfile

    if not INSTALL.is_file():
        import pytest
        pytest.skip("包内无 install.sh（副本态）")

    def run(*a: str):
        r = subprocess.run(
            a, capture_output=True,
            env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "LANG": "C.UTF-8"},
        )
        return r.returncode, r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")

    def first(target: Path, *extra: str):
        (target / ".trellis").mkdir(parents=True)
        return run("bash", str(INSTALL), "--force", "--target", str(target),
                   "--no-skill", "--no-patch", "--no-wiring", *extra)

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        root = base / "default"
        root.mkdir()
        rc, out = first(root)
        assert rc == 0, out
        assert "assets_root: product" in (root / "atlas.config.yaml").read_text(encoding="utf-8")
        profile = (root / "product" / "stack-profile.yaml").read_text(encoding="utf-8")
        assert "cases_dir: product/e2e/cases" in profile, profile

        docs = base / "docs"
        docs.mkdir()
        rc, out = first(docs, "--assets-root", "docs")
        assert rc == 0, out
        assert "assets_root: docs" in (docs / "atlas.config.yaml").read_text(encoding="utf-8")
        assert (docs / "docs" / "stack-profile.yaml").is_file()
        assert not (docs / "product").exists()
        assert "cases_dir: docs/e2e/cases" in (docs / "docs" / "stack-profile.yaml").read_text(encoding="utf-8")

        before = (docs / "atlas.config.yaml").read_bytes()
        rc, out = run("bash", str(INSTALL), "--update", "--target", str(docs),
                      "--no-skill", "--no-patch", "--no-wiring")
        assert rc == 0, out
        assert (docs / "atlas.config.yaml").read_bytes() == before
        assert (docs / "docs" / "stack-profile.yaml").is_file()

        bad = base / "bad"
        bad.mkdir()
        rc, out = first(bad)
        assert rc == 0, out
        (bad / "atlas.config.yaml").write_text(
            "version: 1\nlayout:\n  assets_root: ../escape\n", encoding="utf-8")
        n_before = len(list((bad / ".atlas").rglob("*")))
        rc, out = run("bash", str(INSTALL), "--update", "--target", str(bad),
                      "--no-skill", "--no-patch", "--no-wiring")
        assert rc == 2, out
        assert len(list((bad / ".atlas").rglob("*"))) == n_before

        double = base / "double"
        double.mkdir()
        (double / "product" / "prd").mkdir(parents=True)
        rc, out = first(double, "--assets-root", "docs")
        assert rc == 2, out
        assert not (double / "atlas.config.yaml").exists()
        assert not (double / ".atlas").exists()
