#!/usr/bin/env python3
"""atlas 校验器 —— 台账机器化（`3509 §97` 定形 / `§B94` 撞号 / `§B96` 虚挂 / `§B113` 范围）。

守三件事（都是「看起来在跑、其实什么都没测」族的对治）：

  1. **编号撞号**：① 台账 `B<NN>` **跨卷**撞号（`max+1` 只管本卷 ⇒ 跨卷必撞，实测发生过；
     2026-09-29 `§B94` 发号侧落地：新条目一律轮次前缀形态 `B<纪要轮次>-<序号>`，撞号按**整串**唯一、
     两种形态通吃）；
     ② 纪要卷 `## <N>.` 撞号（同一卷内两个 §92 指两件事，实测）；③ **AC 号跨文件**撞号
     （同一个 `AC-XXX-NNN` 出现在两份域级 PRD，或同文件内重复）。
  2. **疑似已落地**（机器缩围 + 人终审，`§97` 收口 ③）：**未决**条目正文里引用的**路径**
     若在 canonical / 项目里已存在 ⇒ 疑似「已落地却仍挂在未决卷」（台账曾实测虚高 38%）。
     扫描范围 = **全卷两种条目形态**（`§B102`：首格条号 `| B1 |` 与次格标签 `|| C9 |` 同扫，
     不只 B 组）。
  3. **条目 schema**（`§97` 八字段定形 / `§B112` 残留清偿，2026-10-06）：未决条目行内必须带
     `类型：`（四闭集）与 `优先级：P0|P1|P2` 标签（其余六字段由现表形态承载，见
     `shared/knowledge.md` §9）⇒ 缺 ⇒ WARN 列名。
  4. **待裁决汇总**（`§97` 收口 ④ 裁决面，报告先行）：一行给出
     「未决 N 项：P0×M、P1×K、P2×J、未标级×U · 疑似 X 项 / 撞号 L 处」。

**定位**（`shared/knowledge.md`）：台账在 vault 里，经 `product/stack-profile.yaml` 的 `knowledge`
段定位 —— `vault`（根绝对路径）+ `dir`（vault 内 atlas 设计目录）。**卷角色由卷自身声明**：
正文里的 `> 卷角色：未决` / `> 卷角色：已决归档`；**未声明 ⇒ WARN**（不静默当成未决）。
`knowledge` 未启用（缺省 / `vault: null`）⇒ 依赖 vault 的项记 **`SKIP`**（响亮原则：显式可见
跳过 + 原因，不是通过），但**项目侧**的 AC 号撞号仍照跑。

- 框架无关；纯标准库。判定：`PASS` / `WARN` / `SKIP` → 退出码 0；`FAIL` → 1。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 台账条目行：`| B<NN> | … |`（未决卷与归档卷同形）
# `?…`? = ID 允许反引号包裹（实测形态：`| `B191-1` |`，2026-10-06 咬出裸正则漏抓 2 条）
LEDGER_ROW = re.compile(r"^\|\s*`?\s*(B\d+(?:-\d+)?)\s*`?\s*\|", re.M)  # §B94：含轮次前缀形态 B<NN>-<k>
# 条目行第二形态：首格空、次格标签 `|| C9 | … |`（A / C 节形态；`§B102`：对账范围 = 全卷）
LABEL_ROW = re.compile(r"^\|\s*\|\s*`?\s*([A-Z]+\d+(?:-\d+)?)\s*`?\s*\|", re.M)
# 条目 schema 行内标签（`3508 §97` 八字段：类型四闭集 / 优先级三档；2026-10-06 机器判据）
PRIORITY_TAG = re.compile(r"优先级[:：]\s*(P[0-2])(?!\d)")
TYPE_TAG = re.compile(r"类型[:：]\s*(产品裁定|流水线决策|台账处置|确认门)")
# 纪要卷节号：`## <N>.` / `## <N>.<M>.`（子号是合法的，`91.1` 先例）
JOURNAL_SEC = re.compile(r"^##\s+(\d+(?:\.\d+)?)\.\s", re.M)
# 卷角色声明（正文行，非 frontmatter —— 工具重写 frontmatter 的风险不落在正文）
ROLE_OPEN = re.compile(r"^>\s*卷角色：未决\s*$", re.M)
ROLE_ARCHIVE = re.compile(r"^>\s*卷角色：已决归档\s*$", re.M)
# 条目里引用的路径形态（反引号内、含 `/` 且像文件或目录）
PATH_TOKEN = re.compile(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_.-]*/?|[\w.-]+\.(?:md|py|json|yaml|yml))`")
# AC 号的**定义行**：表格首格 = 该 ID **且至少 3 列**（`| ID | 场景 | 回指规则 |`）。
# 两个假阳性源必须排除：① 引用（跨域回指 / 规则→AC 列）；② **结构类 AC 清单**（只有 2 列）。
# **`[^|\n]` 不能写成 `[^|]`**：后者会跨行吃掉后续内容 ⇒ 把 2 列行也当成 3 列（实测踩到，
# 四个 ID 被误报「同文件重复定义」；发现方式是逐条回读被点名的行，不是信门的数字）。
AC_DEF_ROW = re.compile(r"^\|\s*`?(AC-[A-Z0-9]+-\d+)`?\s*\|[^|\n]*\|[^|\n]*\|", re.M)
# AC 号（域级 PRD 内的应然资产编号）
AC_ID = re.compile(r"\bAC-[A-Z0-9]+-\d+\b")
# 「疑似已落地」只看 **canonical 包内路径**（高信号：契约 / 脚本 / 模板已落地）；
# 项目侧路径（`product/`、`.trellis/`）多为「指向产物」而非「修复已落地」⇒ 只计数不列名，避免噪声。
PKG_PREFIXES = ("shared/", "rings/", "apply/", "scripts/", "validators/",
                "templates/", "skills/", "tests/", ".atlas/")


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, level: str, detail: str = "") -> None:
        self.checks.append({"check": check, "level": level, "detail": detail})

    @property
    def status(self) -> str:
        levels = {c["level"] for c in self.checks}
        if "FAIL" in levels:
            return "FAIL"
        return "WARN" if "WARN" in levels else "PASS"


def strip_inline_comment(line: str) -> str:
    """去掉 YAML 行内注释：`#` 前有空白（或行首）且在引号外时截断。

    手写解析器必须自己处理 —— 否则 `vault: /path   # 说明` 会把注释当成值的一部分
    （实测踩到：vault 路径被读成 `/path   # 说明` ⇒ 目录不存在 ⇒ 台账卷定位不到）。
    """
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def read_knowledge(root: Path) -> tuple[str | None, str]:
    """从 `product/stack-profile.yaml` 读 `knowledge.vault` / `knowledge.dir`（手写解析，纯标准库）。"""
    p = root / "product" / "stack-profile.yaml"
    if not p.is_file():
        return None, "atlas"
    vault, dirname, in_knowledge = None, "atlas", False
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = strip_inline_comment(raw.rstrip())
        if not line.strip():
            continue
        if not line[:1].isspace():
            in_knowledge = line.strip().endswith(":") and line.strip().rstrip(":") == "knowledge"
            continue
        if not in_knowledge:
            continue
        m = re.match(r"^\s+(vault|dir):\s*(.*?)\s*$", line)
        if m:
            v = m.group(2).strip().strip("'\"")
            if m.group(1) == "vault":
                vault = None if v in ("", "null", "~", "None") else v
            else:
                dirname = v or "atlas"
    return vault, dirname


def ledger_volumes(vault_dir: Path) -> tuple[list[dict], list[str]]:
    """台账卷 = **声明了卷角色**且含条目行的 .md；返回（卷, 含条目但未声明角色的文件）。

    只看声明 —— 讨论纪要 / 决策记录里也会有 `| B31 | … |` 这样的**引用**行，
    若按「含 B 行」判卷，会把引用当定义 ⇒ 跨卷撞号成片假阳性（实测：B1–B16 全被误报）。
    """
    vols: list[dict] = []
    undeclared: list[str] = []
    if not vault_dir.is_dir():
        return vols, undeclared
    for f in sorted(vault_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if not LEDGER_ROW.findall(text):
            continue
        if ROLE_OPEN.search(text):
            role = "未决"
        elif ROLE_ARCHIVE.search(text):
            role = "已决归档"
        else:
            undeclared.append(f.name)
            continue
        vols.append({"path": f, "text": text, "ids": LEDGER_ROW.findall(text), "role": role})
    return vols, undeclared


def duplicate_journal_ids(vault_dir: Path) -> list[str]:
    """全卷 `## <N>.` 撞号（含历史卷）。"""
    bad: list[str] = []
    if not vault_dir.is_dir():
        return bad
    for f in sorted(vault_dir.glob("*.md")):
        nums = JOURNAL_SEC.findall(f.read_text(encoding="utf-8", errors="replace"))
        dup = sorted({n for n in nums if nums.count(n) > 1})
        if dup:
            bad.append(f"{f.name}: " + "、".join(f"§{n}×{nums.count(n)}" for n in dup))
    return bad


def journal_volume_overflow(vault_dir: Path, rounds: int = 30, chars: int = 60_000) -> list[str]:
    """当前纪要卷的**全文轮次**是否已达拆卷阈值（`shared/closeout.md` 步骤 4 轮次卷滚动，`3509 §B122`）。

    阈值：**≥ 30 轮或 ≥ 60k 字符**（任一命中）⇒ 当轮拆卷。
    计量口径：全文轮次 = 卷内 `## <N>.` 节的**唯一整数轮号**（子号 `N.M` 归入 N；`§0` 是常驻的
    「用户关键纠正」节、不是轮次，不计）；字符数 = 首个 `## <N>.` 节起至文末（= 全文轮次区，
    不含轮次索引 gist 表）。**历史卷不计**（文件名带 `archive`）——它们本就是拆卷产物。
    """
    out: list[str] = []
    if not vault_dir.is_dir():
        return out
    for f in sorted(vault_dir.glob("*.md")):
        # 只量**当前卷**：历史卷名为 `…-discussion-log-archive[-N].md`，天然不满足本后缀
        if not f.name.endswith("discussion-log.md"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        marks = list(JOURNAL_SEC.finditer(text))
        if not marks:
            continue
        nums = {m.group(1).split(".")[0] for m in marks}
        nums.discard("0")
        region = len(text[marks[0].start():])
        hits = [s for s, ok in ((f"{len(nums)} 轮 ≥ {rounds}", len(nums) >= rounds),
                               (f"{region / 1000:.1f}k 字符 ≥ {chars // 1000}k", region >= chars)) if ok]
        if hits:
            out.append(f"{f.name}: " + "、".join(hits) + " ⇒ 当轮拆卷")
    return out


def ac_id_collisions(root: Path) -> list[str]:
    """AC 号**定义**跨文件 / 同文件重复（域级 PRD 是 AC 的应然资产落点）。

    只数**定义行**（`^| AC-… |`）：引用（跨域回指 / 结构类清单 / 规则→AC 列）不是撞号。
    """
    prd = root / "product" / "prd"
    if not prd.is_dir():
        return []
    where: dict[str, list[str]] = {}
    bad: list[str] = []
    for f in sorted(prd.glob("*-prd.md")):
        ids = AC_DEF_ROW.findall(f.read_text(encoding="utf-8", errors="replace"))
        for i in set(ids):
            where.setdefault(i, []).append(f.name)
        inner = sorted({i for i in ids if ids.count(i) > 1})
        if inner:
            bad.append(f"{f.name} 内定义重复：{'、'.join(inner)}")
    for i, files in sorted(where.items()):
        if len(files) > 1:
            bad.append(f"{i} 被 {len(files)} 份文件定义：{'、'.join(files)}")
    return bad


def unresolved_refs(root: Path, volume: dict) -> list[str]:
    """未决条目引用的 `.atlas/<path>` 当前不存在 —— 可能是**待建**，也可能是**已删**。

    两者机器分不开（待建引用本来就是「修复还没做」的正常形态）⇒ 只做**缩围**给人核对，不判 FAIL。
    """
    bad: list[str] = []
    for m in re.finditer(r"`?\.atlas/([A-Za-z0-9_./-]+\.(?:md|py|json|yaml))`?", volume["text"]):
        rel = m.group(1)
        if not (root / ".atlas" / rel).exists():
            bad.append(f".atlas/{rel}")
    return sorted(set(bad))


def entry_rows(text: str) -> list[tuple[str, str]]:
    """未决 / 归档卷的**条目行**，两种形态都算（`§B102`：对账范围 = 全卷，不只 B 组）：

    `| B1 | 问题 | … |`（首格条号，允许反引号包裹）与 `|| C9 | 问题 | … |`（首格空、次格标签，
    A / C 节形态）。返回（条号, 行体）——行体供「疑似已落地」与 schema 判据扫描。
    """
    out = [(m.group(1), m.group(2))
           for m in re.finditer(r"^\|\s*`?\s*(B\d+(?:-\d+)?)\s*`?\s*\|(.*)$", text, re.M)]
    out += [(m.group(1), m.group(2))
            for m in re.finditer(r"^\|\s*\|\s*`?\s*([A-Z]+\d+(?:-\d+)?)\s*`?\s*\|(.*)$", text, re.M)]
    return out


def suspected_landed(root: Path, volume: dict) -> tuple[list[str], int]:
    """未决条目引用的**包内路径**若已存在 ⇒ 疑似「已落地却仍挂着」（机器缩围，人终审）。

    扫描两种条目形态（`§B102`）。返回（疑似清单, 被跳过的项目侧路径数）。
    """
    out: list[str] = []
    skipped = 0
    for bid, body in entry_rows(volume["text"]):
        hits: list[str] = []
        for tok in sorted(set(PATH_TOKEN.findall(body))):
            if not tok.startswith(PKG_PREFIXES):
                skipped += 1
                continue
            if (root / ".atlas" / tok).exists() or (root / tok).exists():
                hits.append(tok)
        if hits:
            out.append(f"{bid} → {', '.join(hits[:3])}"
                       + (f"（共 {len(hits)} 处）" if len(hits) > 3 else ""))
    return out, skipped


def schema_gaps(volume: dict) -> tuple[list[str], dict[str, int]]:
    """未决条目的「类型 / 优先级」行内标签判缺（`3508 §97` 八字段 schema 的机器判据）。

    八字段 = ID / 类型 / 优先级 / 问题 / 选项 / 推荐+理由 / 影响 / 状态；现表形态已承载其余六项
    （ID / 问题 / 影响 列 + 状态 = 卷角色 + 选项与推荐并入建议动作列），类型与优先级以**行内标签**
    承载（`shared/knowledge.md` §9）。返回（缺标签条号清单, 优先级计数含「未标级」）。
    """
    missing: list[str] = []
    counts = {"P0": 0, "P1": 0, "P2": 0, "未标级": 0}
    for eid, body in entry_rows(volume["text"]):
        pri = PRIORITY_TAG.search(body)
        if pri:
            counts[pri.group(1)] += 1
        else:
            counts["未标级"] += 1
        if not (pri and TYPE_TAG.search(body)):
            missing.append(eid)
    return missing, counts


# 契约 ⇔ 知识库时效映射（`shared/knowledge.md` §3 文档地图）
CONTRACT_NOTE_MAP: list[tuple[str, str, str]] = [
    ("rings/structure/reference.md", "*-structure-ring.md", "structure 环 (3502)"),
    ("rings/prd/reference.md", "*-prd-ring.md", "prd 环 (3503)"),
    ("rings/e2e/reference.md", "*-e2e-ring.md", "e2e 环 (3505)"),
    ("shared/stack-profile.md", "*-distribution.md", "分发/stack-profile (3506)"),
    ("shared/gates.md", "*-overview.md", "总览/gates (3501)"),
]


def locate_canonical_dir(root: Path) -> Path | None:
    for cand in [root / "atlas", root / ".atlas", root]:
        if (cand / "shared").is_dir() and (cand / "rings").is_dir():
            return cand
    return None


def extract_frontmatter_updated(text: str) -> str | None:
    m = re.search(r"^updated:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text, re.M)
    return m.group(1) if m else None


def get_git_modified_files(repo_dir: Path) -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "status", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=3
        )
        if proc.returncode != 0:
            return set()
        files = set()
        for line in proc.stdout.splitlines():
            if len(line) >= 4:
                p = line[3:].strip().split(" -> ")[-1].strip()
                files.add(p)
        return files
    except Exception:
        return set()


def get_git_file_commit_date(repo_dir: Path, rel_file: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "log", "-1", "--format=%cs", "--", rel_file],
            capture_output=True, text=True, check=False, timeout=3
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return None


def check_contract_freshness(root: Path, vault_dir: Path) -> list[str]:
    """契约 ⇔ 知识库时效对账门（gates.md §2.2，2026-10-08 机器门）：
    比对 canonical 契约与对应 vault 活页 Note 的修改时态。
    1. 工作区若改动了契约，检查对应 Note 是否同步处于改动状态（防漏提）；
    2. 若契约最近提交日期晚于 Note 的 updated 声明，提示滞后（防漏记）。
    """
    canon_dir = locate_canonical_dir(root)
    if not canon_dir:
        return []

    warnings: list[str] = []
    root_modified = get_git_modified_files(root)
    vault_modified = get_git_modified_files(vault_dir)

    for rel_contract, pattern, label in CONTRACT_NOTE_MAP:
        c_path = canon_dir / rel_contract
        if not c_path.is_file():
            continue

        notes = sorted(vault_dir.glob(pattern))
        if not notes:
            continue
        note_file = notes[0]
        note_text = note_file.read_text(encoding="utf-8", errors="replace")
        note_updated = extract_frontmatter_updated(note_text)

        try:
            c_rel_root = str(c_path.relative_to(root))
        except ValueError:
            c_rel_root = rel_contract

        # 检查 1：当前工作区契约改动检测
        if c_rel_root in root_modified:
            try:
                note_rel_vault = str(note_file.relative_to(vault_dir))
            except ValueError:
                note_rel_vault = note_file.name

            note_is_modified = any(note_rel_vault in f or note_file.name in f for f in vault_modified)
            if not note_is_modified and note_file.stat().st_mtime < c_path.stat().st_mtime - 1.0:
                warnings.append(f"{c_rel_root} 工作区已改动，但对应 {label} 未同步修改")
                continue

        # 检查 2：提交日期 vs Note updated 日期
        c_date = get_git_file_commit_date(root, c_rel_root)
        if c_date and note_updated:
            if c_date > note_updated:
                warnings.append(
                    f"{rel_contract}（提交 {c_date}）晚于对应 Note {note_file.name}（updated: {note_updated}）"
                )
    return warnings


def validate(root: Path) -> Result:
    res = Result()
    vault, dirname = read_knowledge(root)

    # ---- 项目侧：AC 号撞号（不依赖 vault，任何形态都跑）
    ac_bad = ac_id_collisions(root)
    res.add("AC 号跨文件唯一", "FAIL" if ac_bad else "PASS",
            "；".join(ac_bad[:4]) if ac_bad else "域级 PRD 内 AC 号无跨文件 / 同文件重复")

    # ---- vault 侧
    if not vault:
        res.add("知识库已启用", "SKIP",
                "stack-profile 的 knowledge.vault 为 null / 缺省 ⇒ 台账相关项跳过"
                "（shared/knowledge.md；不是通过）")
        res.add("待裁决汇总", "WARN" if ac_bad else "PASS",
                f"知识库未启用，无法统计未决条目；AC 号撞号 {len(ac_bad)} 处")
        return res

    vdir = Path(vault) / dirname
    res.add("知识库已启用", "PASS" if vdir.is_dir() else "WARN",
            f"{vdir}" + ("" if vdir.is_dir() else "（目录不存在：知识库未初始化？）"))

    vols, undeclared = ledger_volumes(vdir)
    if not vols:
        res.add("台账卷可定位", "WARN", f"{vdir} 下未找到声明卷角色且含条目的卷")
    else:
        res.add("台账卷可定位", "PASS",
                "；".join(f"{v['path'].name}({len(v['ids'])} 条, {v['role']})" for v in vols))

    # 看着像台账卷（标题含「清单」/「台账」）却没声明卷角色 ⇒ 可能漏声明（否则不报，
    # 否则讨论纪要 / 决策记录里引用 `| B31 | … |` 会永久 WARN ⇒ 长 WARN = 静音门）。
    looks_like = [f for f in undeclared
                  if re.search(r"^title:\s*.*(清单|台账)",
                               (vdir / f).read_text(encoding="utf-8", errors="replace"), re.M)]
    res.add("卷角色声明", "WARN" if looks_like else "PASS",
            ("标题像台账卷但缺 `> 卷角色：未决` / `> 卷角色：已决归档`：" + "、".join(looks_like))
            if looks_like else "台账卷均声明了卷角色")

    # 跨卷 B 号撞号（只比台账卷）
    seen: dict[str, list[str]] = {}
    for v in vols:
        for i in set(v["ids"]):
            seen.setdefault(i, []).append(v["path"].name)
    cross = {i: f for i, f in seen.items() if len(f) > 1}
    res.add("台账 B 号跨卷唯一", "FAIL" if cross else "PASS",
            "；".join(f"{i} 出现在 {len(f)} 卷" for i, f in sorted(cross.items())) if cross
            else f"{len(seen)} 个 B 号在 {len(vols)} 卷内唯一")

    # 纪要卷节号唯一
    jbad = duplicate_journal_ids(vdir)
    res.add("纪要卷编号唯一", "FAIL" if jbad else "PASS",
            "；".join(jbad) if jbad else "全卷 `## <N>.` 无重复")

    # 纪要卷滚动阈值（`closeout.md` 步骤 4；2026-10-04 补，`3509 §B188-1`）：拆卷义务此前零判据
    jover = journal_volume_overflow(vdir)
    res.add("纪要卷滚动阈值", "WARN" if jover else "PASS",
            "；".join(jover) if jover else "当前纪要卷全文轮次未达拆卷阈值")

    # 疑似已落地（仅未决卷；机器缩围 + 人终审）
    open_vols = [v for v in vols if v["role"] == "未决"]
    if not open_vols and vols:
        res.add("疑似已落地", "WARN", "没有声明 `> 卷角色：未决` 的卷 ⇒ 无法判断哪些条目仍开着")
        sus, skipped = [], 0
    else:
        sus, skipped = [], 0
        for v in open_vols:
            s, k = suspected_landed(root, v)
            sus += s
            skipped += k
        res.add("疑似已落地", "WARN" if sus else "PASS",
                (f"{len(sus)} 条（机器缩围，人终审；条目引用的**包内路径**已存在）："
                 + "；".join(sus[:6])
                 + (f"　另跳过 {skipped} 处项目侧路径引用（低信号，未列名）" if skipped else ""))
                if sus else "未决条目引用的包内路径均不存在（无「疑似已落地」）")

    # 未决条目引用的 canonical 路径当前不存在（缩围，人核对：待建 or 已删）
    miss: list[str] = []
    if open_vols:
        for v in open_vols:
            miss += unresolved_refs(root, v)
        res.add("未决条目引用可达", "WARN" if miss else "PASS",
                (f"{len(miss)} 处引用的 canonical 路径当前不存在"
                 "（可能是**待建**，也可能是**已删** —— 逐条核对）：" + "、".join(miss[:6]))
                if miss else "未决条目引用的 canonical 路径均存在")

    # 条目 schema（`3508 §97` 八字段：类型 / 优先级行内标签；`§B112` 残留清偿，2026-10-06）
    pri_counts = {"P0": 0, "P1": 0, "P2": 0, "未标级": 0}
    if open_vols:
        gaps: list[str] = []
        for v in open_vols:
            g, c = schema_gaps(v)
            gaps += g
            for k in pri_counts:
                pri_counts[k] += c[k]
        res.add("条目 schema（类型/优先级）", "WARN" if gaps else "PASS",
                (f"{len(gaps)} 条缺行内标签（`类型：` 四闭集 / `优先级：P0|P1|P2`，"
                 f"`shared/knowledge.md` §9 八字段）：" + "、".join(gaps[:8]))
                if gaps else "未决条目均带类型 / 优先级标签")

    # 契约 ⇔ 知识库时效对账（gates.md §2.2，2026-10-08 机器门）
    fresh_warns = check_contract_freshness(root, vdir)
    res.add("契约时效对账", "WARN" if fresh_warns else "PASS",
            (f"{len(fresh_warns)} 处契约疑似已演进但对应 Note 滞后：" + "；".join(fresh_warns[:5]))
            if fresh_warns else "canonical 契约与对应 vault 活页 Note 保持时效同步")

    # 待裁决汇总（§97 ④：报告先行，按优先级分行计数）
    n_open = sum(len(entry_rows(v["text"])) for v in open_vols)
    n_cross = len(cross)
    n_j = len(jbad)
    sus_n = len(sus) if open_vols else 0
    res.add("待裁决汇总", "PASS" if not (n_cross or n_j or ac_bad) else "FAIL",
            f"未决 {n_open} 项：P0×{pri_counts['P0']}、P1×{pri_counts['P1']}、"
            f"P2×{pri_counts['P2']}、未标级×{pri_counts['未标级']} · "
            f"疑似已落地 {sus_n} 项（待人工终审） · "
            f"撞号 {n_cross + n_j + len(ac_bad)} 处")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    res = validate(root)
    if args.json:
        print(json.dumps({"ok": res.status != "FAIL", "status": res.status,
                          "root": str(root), "checks": res.checks}, ensure_ascii=False, indent=2))
    else:
        print(f"validate_ledger @ {root}")
        for c in res.checks:
            line = f"  [{c['level']:<4}] {c['check']}"
            if c["detail"] and c["level"] != "PASS":
                line += f" —— {c['detail']}"
            print(line)
        print(res.status)
    return 1 if res.status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
