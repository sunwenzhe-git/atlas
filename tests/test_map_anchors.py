#!/usr/bin/env python3
"""docs/map 实现地图的锚存活性门（2026-10-25 用户拍板，docs/map 二期 ③）。

对账平面：**docs/map/*.md 与 atlas-map.html 里的文件锚 ⇔ 仓内实码**。
先例：`tests/test_canonical_consistency.py` 守 shared/ 契约（同为「仓内文档 ⇔ 实码」，
走出厂测试面而非 VALIDATORS——docs/map 是 atlas 自仓资产，不装配进 .atlas/）。

三档语义（响亮原则；DRIFT 在本测试面一律置红，修法 = 改文档或 `--fix`）：
  * path_missing  —— 锚指路径不存在 ⇒ 红（含 atlas-map.html 的 DETAIL/tip 文件条目）；
  * symbol_drift  —— 符号仍在文件里、但不在锚定行窗口（±3）⇒ 红，报「旧 → 新」；
  * symbol_gone   —— 邻接符号在目标文件中已不存在 ⇒ 红；
  * bare_anchor   —— 代码目标的 `path:line` 锚无邻接符号 ⇒ 红（锚形态收进值域：
                      必须写成 符号（`path:line`）——与 D98 动词值域封闭同哲学）；
  * doc_link / snapshot_drift —— 同目录 md 互链存活 / index.md 数字快照机器实收
                      （README 徽章漂移先例的 docs/map 版，口径复用 canonical 的
                      `^check ` 与 `tests/test_*.py` glob）。

显式盲区（登记于 `shared/gates.md` 2.6）：
  * 目标仓运行态路径（`product/` `.trellis/` `.adapter-out/` `.atlas/`）不在校验域；
  * `.md` 目标的无 § 邻接行锚只验「行存活」（节标题锚定不做符号对账）；
  * 锚的**语义正确性**（那行是否仍是作者想指的那行）机器判不了——符号匹配是近似。

变异钉（出厂级，本轮实测）：M151 路径消失必红 / M152 行号漂移必红且 --fix 复绿 /
M153 符号消失必红 / M154 无符号裸锚必红。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = PKG_ROOT / "docs" / "map"

# atlas 自有源码的校验值域（锚指这些顶层才算「本仓可判」）
OWNED_PREFIXES = (
    "adapters/", "scripts/", "shared/", "tests/", "apply/", "rings/",
    "skills/", "patches/", "_support/", "templates/", "validators/",
    "bin/", "docs/", "duty-review/",
)
OWNED_ROOT_FILES = {"install.sh", "DESIGN.md", "README.md", "CHANGELOG.md"}

ANCHOR_RE = re.compile(r"`([^`\s]+):(\d+)(?:-(\d+))?`")  # `path:line` / `path:l1-l2`
TOK_RE = re.compile(r"`([^`\s]+)`")
MD_LINK_RE = re.compile(r"\]\(([^)#\s]+\.md)\)")
HTML_FILE_RE = re.compile(r"\['([^']+)'(?:,'([^']*)')?\]")


def _is_owned(path: str) -> bool:
    top = path.split("/")[0]
    return top in OWNED_ROOT_FILES or path.startswith(OWNED_PREFIXES)


def _strip_section(path: str) -> str:
    return re.sub(r"\s*§.*$", "", path)


def _resolve(path: str, repo: Path) -> Path | None:
    """全路径优先；裸文件名（如 `_graph.py`）在自有树内唯一命中才认。"""
    p = path.split("::")[0]
    if (repo / p).is_file():
        return repo / p
    base = Path(p).name
    hits: list[Path] = []
    for pref in OWNED_PREFIXES:
        d = repo / pref
        if d.is_dir():
            hits += [x for x in d.rglob(base) if x.is_file()]
    if (repo / base).is_file() and base in OWNED_ROOT_FILES:
        hits.append(repo / base)
    return hits[0] if len(hits) == 1 else None


def _candidates(ctx: str, anchor_tok: str) -> list[str]:
    """符号候选：反引号 token（剥尾 ()）+ 邻近 identifier 型 token（含 desc 的 FN() 形态）。
    锚 token 自身先抹掉，防「路径里的片段」被当成符号（自匹配假漂移）。"""
    masked = ctx.replace(anchor_tok, " " * len(anchor_tok))
    out: list[str] = []
    for m in TOK_RE.finditer(masked):
        tok = m.group(1)
        name = tok.rstrip("()")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name):
            out.append(name)
    for name in re.findall(r"[A-Za-z_][A-Za-z0-9_]*\(\)", masked):
        out.append(name.rstrip("()"))
    head = re.match(r"^[\W_0-9]*([A-Za-z][A-Za-z0-9_]*)", masked)
    if head:
        out.append(head.group(1))  # 首词（html desc 惯例：'query 查询族:…'）
    for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", masked):
        if ("_" in t) or t.isupper() or any(c.isupper() for c in t[1:]):
            out.append(t)
    seen: set[str] = set()
    res: list[str] = []
    for n in out:
        if n not in seen:
            seen.add(n)
            res.append(n)
    return res


def _sym_hit_lines(name: str, lines: list[str]) -> list[int]:
    """符号变体（点号全串 → 末段）在文件中的出现行（1 起）。"""
    for variant in (name, name.rsplit(".", 1)[-1]):
        hits = [i for i, ln in enumerate(lines, 1) if variant in ln]
        if hits:
            return hits
    return []


def _looks_like_path(path: str) -> bool:
    """锚的路径段须像仓内文件：含 `/`，或带已知扩展名的裸文件名（`_graph.py` 形态）。
    排除 `127.0.0.1:4190` 这类 host:port 散文。"""
    return "/" in path or bool(re.match(r"^[\w.-]+\.(py|md|js|sh|ya?ml|json|ts)$", path))


def check_anchor(tok: str, start: int, end: int, ctx: str, where: str,
                 repo: Path, full_tok: str | None = None) -> dict | None:
    if not _looks_like_path(tok):
        return None
    path = _strip_section(tok)
    target = _resolve(path, repo)
    if target is None or not target.is_file():
        return {"sev": "FAIL", "code": "path_missing", "where": where,
                "msg": f"`{tok}` 目标不存在（{path}）"}
    lines = target.read_text(encoding="utf-8").splitlines()
    if start > len(lines):
        return {"sev": "FAIL", "code": "path_missing", "where": where,
                "msg": f"`{tok}` 行号 {start} 超出文件末行 {len(lines)}"}

    rel = target.relative_to(repo).as_posix()
    if target.suffix == ".md":
        m = re.search(r"§(\d+(?:\.\d+)?)", ctx)
        if not m:
            return None  # .md 弱锚：行存活即过（盲区声明）
        sec = m.group(1)
        window = lines[max(0, start - 4): end + 3]
        if any(sec in ln and ln.lstrip().startswith("#") for ln in window) or \
           any(re.match(r"^#{1,6}\s*" + re.escape(sec) + r"[\s\.、:：（(]", ln) for ln in window):
            return None
        new = next((i for i, ln in enumerate(lines, 1)
                    if re.match(r"^#{1,6}\s*" + re.escape(sec) + r"[\s\.、:：（(]", ln)), None)
        return {"sev": "FAIL", "code": "symbol_drift", "where": where,
                "msg": f"`{tok}` 窗口内无 §{sec} 标题"
                       + (f"（新位置约 {rel}:{new}）" if new else "（全文件未找到该节）")
                       + "；--fix 不改写 § 锚，请手工对位"}

    cands = _candidates(ctx, tok)
    if not cands:
        return {"sev": "FAIL", "code": "bare_anchor", "where": where,
                "msg": f"`{tok}` 无邻接符号——请改写成 符号（`path:line`）形态"}
    hit_map = {c: _sym_hit_lines(c, lines) for c in cands}
    live = {c: hs for c, hs in hit_map.items() if hs}
    if not live:
        return {"sev": "FAIL", "code": "symbol_gone", "where": where,
                "msg": f"`{tok}` 邻接符号 {cands} 在 {rel} 中均不存在（删除或改名？）"}
    window = range(max(1, start - 3), end + 4)
    if any(any(x in window for x in hs) for hs in live.values()):
        return None
    # 锚指函数体/docstring/常量块：窗口上方最近 def/class（或模块级大写赋值）名在候选中 ⇒ 活
    above = lines[max(0, start - 40): start - 1]
    for ln in reversed(above):
        m2 = re.match(r"\s*(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", ln)
        if m2:
            if any(m2.group(1) == c or f".{m2.group(1)}" in c for c in cands):
                return None
            break
    for ln in reversed(above):
        m2 = re.match(r"([A-Z_][A-Z0-9_]*)\s*=", ln)
        if m2 and m2.group(1) in cands:
            return None
        if re.match(r"\s*(?:def|class)\s", ln):
            break
    best = min(((c, min(hs)) for c, hs in live.items()),
               key=lambda x: min(abs(h - start) for h in live[x[0]]))
    return {"sev": "FAIL", "code": "symbol_drift", "where": where,
            "full_tok": full_tok or f"{tok}:{start}" + (f"-{end}" if end != start else ""),
            "new": best[1], "rel": rel,
            "msg": f"`{tok}` 符号 {best[0]} 已漂移到 {rel}:{best[1]}（旧 {tok}）"
                   f"；python3 tests/test_map_anchors.py --fix 可改写"}


def check_path_token(tok: str, where: str, repo: Path) -> dict | None:
    if any(ch in tok for ch in "<>{}*"):
        return None  # 占位符 / 集合简写 / glob 简写不在本门值域
    p = _strip_section(tok)
    if "/" not in p and p not in OWNED_ROOT_FILES:
        return None  # 无斜杠的裸名（可能是运行态文件名）不判
    if not _is_owned(p):
        return None  # 目标仓运行态路径：显式盲区
    if p.endswith("/"):
        return None if (repo / p).is_dir() else {
            "sev": "FAIL", "code": "path_missing", "where": where,
            "msg": f"`{tok}` 目录不存在"}
    if (repo / p).is_dir():
        return None  # 无尾斜线的目录（`skills/atlas-release`）也算活
    if _resolve(p, repo) is None:
        return {"sev": "FAIL", "code": "path_missing", "where": where,
                "msg": f"`{tok}` 路径不存在（{p}）"}
    return None


def collect_docs(repo: Path) -> list[dict]:
    """docs/map/*.md + atlas-map.html 全量校验；返回违规清单。"""
    out: list[dict] = []
    docs_dir = repo / "docs" / "map"
    md_files = sorted(docs_dir.glob("*.md"))
    for f in md_files:
        for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            where = f"docs/map/{f.name}:{i}"
            for m in ANCHOR_RE.finditer(ln):
                tok, s, e = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
                v = check_anchor(tok, s, e, ln, where, repo, full_tok=m.group(0)[1:-1])
                if v:
                    out.append(v)
            anchored_spans = [(m.start(), m.end()) for m in ANCHOR_RE.finditer(ln)]
            for m in TOK_RE.finditer(ln):
                if any(s <= m.start() < e for s, e in anchored_spans):
                    continue  # 行号锚的整段 token 不再当纯路径复检
                v = check_path_token(m.group(1), where, repo)
                if v:
                    out.append(v)
            for m in MD_LINK_RE.finditer(ln):
                if not (docs_dir / m.group(1)).is_file():
                    out.append({"sev": "FAIL", "code": "doc_link", "where": where,
                                "msg": f"同目录文档链接 {m.group(1)} 不存在"})
    html = docs_dir / "atlas-map.html"
    if html.is_file():
        for m in HTML_FILE_RE.finditer(html.read_text(encoding="utf-8")):
            entry, desc = m.group(1), m.group(2) or ""
            where = "docs/map/atlas-map.html"
            am = re.match(r"^([^:]+):(\d+)$", entry)
            if am:
                v = check_anchor(am.group(1), int(am.group(2)), int(am.group(2)),
                                 desc or entry, where, repo, full_tok=entry)
            else:
                v = check_path_token(entry, where, repo)
            if v:
                out.append(v)
    return out


# ---------------- index.md 数字快照 ⇔ 机器实收 ----------------

def _derive_snapshot(repo: Path) -> dict[str, int]:
    import ast
    out: dict[str, int] = {}
    chk = repo / "scripts" / "atlas_check.py"
    if chk.is_file():
        tree = ast.parse(chk.read_text(encoding="utf-8"))
        for node in ast.walk(tree):  # AST 实收（README 徽章漂移先例的口径），不碰注释/文档串
            if isinstance(node, ast.Assign) and any(
                    getattr(t, "id", "") == "VALIDATORS" for t in node.targets):
                out["校验器"] = len(node.value.elts)
    if (repo / "tests").is_dir():
        out["出厂测试文件"] = len(list((repo / "tests").glob("test_*.py")))
    if (repo / "skills").is_dir():
        out["skills"] = len([d for d in (repo / "skills").iterdir() if d.is_dir()])
    if (repo / "rings").is_dir():
        out["环"] = len(list((repo / "rings").glob("*/reference.md")))
    if (repo / "shared").is_dir():
        out["共享契约"] = len(list((repo / "shared").glob("*.md")))
    if (repo / "_support").is_dir():
        out["共享内核"] = len(list((repo / "_support").glob("*.py")))
    inst = repo / "install.sh"
    if inst.is_file():
        out["install.sh 自检声明"] = len(re.findall(r"^check ", inst.read_text(encoding="utf-8"), re.M))
    scripts = list((repo / "scripts").glob("*.py")) if (repo / "scripts").is_dir() else []
    if scripts:
        out["最大单件"] = max(len(p.read_text(encoding="utf-8").splitlines()) for p in scripts)
    return out


def check_snapshot(repo: Path) -> list[dict]:
    idx = (repo / "docs" / "map" / "index.md").read_text(encoding="utf-8")
    section = idx[idx.index("## 数字快照"):]
    section = section[:section.index("\n## ")] if "\n## " in section else section
    derived = _derive_snapshot(repo)
    out: list[dict] = []
    for m in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", section, re.M):
        name, val = m.group(1).strip(), m.group(2)
        if name in ("量", "---") or name not in derived:
            continue  # 编排门行 8 类需语义识别：显式不校验（盲区）
        num = re.search(r"(\d+)\s*行", val) or re.search(r"(\d+)", val)
        if not num or int(num.group(1)) != derived[name]:
            out.append({"sev": "FAIL", "code": "snapshot_drift",
                        "where": "docs/map/index.md",
                        "msg": f"数字快照「{name}」文档 {num.group(1) if num else '无数字'}"
                               f" ≠ 实况 {derived[name]}"})
    return out


def fix_drifts(repo: Path) -> int:
    """把 symbol_drift（代码目标）在 docs 内就地重写为新行号。"""
    import collections
    fixes: dict[Path, list[tuple[str, str]]] = collections.defaultdict(list)
    for v in collect_docs(repo):
        if v["code"] == "symbol_drift" and "full_tok" in v:
            old = v["full_tok"]
            new = re.sub(r":\d+(-\d+)?$", f":{v['new']}", old)
            fixes[repo / "docs" / "map" / Path(v["where"].split(":")[0]).name].append((old, new))
    n = 0
    for path, subs in fixes.items():
        text = path.read_text(encoding="utf-8")
        for old, new in subs:
            if old in text:
                text = text.replace(old, new)
                n += 1
        path.write_text(text, encoding="utf-8")
    return n


# ---------------- 「始终最新」保活（2026-10-25 用户要求：html 与活文档不许过期） ----------------
# 三类可机器判的过期：版本串漂（index/html 锚定版本 ≠ package.json）、行数声明漂
# （md 表格与括注里的「N 行」、html 文件条目描述里的「N 行」≠ 实况 wc）、计数串漂
# （html「出厂测试 ×N / 契约 ×N / 内核 ×N / tests/ N 文件」≠ 实收）。语义内容仍归发版刷新纪律。

def _pkg_version(repo: Path) -> str:
    import json
    return json.loads((repo / "package.json").read_text(encoding="utf-8"))["version"]


def check_freshness(repo: Path) -> list[dict]:
    out: list[dict] = []
    ver = _pkg_version(repo)
    derived = _derive_snapshot(repo)
    where_idx = "docs/map/index.md"
    idx = (repo / "docs" / "map" / "index.md").read_text(encoding="utf-8")
    m = re.search(r"锚定版本\**\s*[:：]\s*\**\s*v([\d][\w.\-]+)", idx)
    if not m:
        out.append({"sev": "FAIL", "code": "version_stale", "where": where_idx,
                    "msg": "index.md 缺「锚定版本」行"})
    elif m.group(1) != ver:
        out.append({"sev": "FAIL", "code": "version_stale", "where": where_idx,
                    "msg": f"index.md 锚定版本 v{m.group(1)} ≠ package.json {ver}——发版后须刷新 docs/map"})
    html_p = repo / "docs" / "map" / "atlas-map.html"
    html = html_p.read_text(encoding="utf-8") if html_p.is_file() else ""
    for vm in re.finditer(r"v(\d+\.\d+\.\d+[\w.\-]*)", html):
        if vm.group(1) != ver:
            out.append({"sev": "FAIL", "code": "version_stale", "where": "docs/map/atlas-map.html",
                        "msg": f"html 版本串 v{vm.group(1)} ≠ package.json {ver}"})
            break

    def _claim(path_tok: str, n: int, where: str):
        target = _resolve(_strip_section(path_tok), repo)
        if target is None or not target.is_file():
            return  # 路径存活已由锚门承担；这里只管「行数对不对」
        real = len(target.read_text(encoding="utf-8").splitlines())
        if real != n:
            out.append({"sev": "FAIL", "code": "linecount_stale", "where": where,
                        "msg": f"`{path_tok}` 声明 {n} 行 ≠ 实况 {real} 行"})

    for f in sorted((repo / "docs" / "map").glob("*.md")):
        text = f.read_text(encoding="utf-8")
        where = f"docs/map/{f.name}"
        for pm in re.finditer(r"`([^`]+)`\((\d+)\s*行", text):
            _claim(pm.group(1), int(pm.group(2)), where)
        for pm in re.finditer(r"\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|", text):
            _claim(pm.group(1), int(pm.group(2)), where)
    if html:
        for em in HTML_FILE_RE.finditer(html):
            entry, desc = em.group(1), em.group(2) or ""
            for dm in re.finditer(r"(\d+)\s*行", desc):
                _claim(re.sub(r":\d+$", "", entry), int(dm.group(1)), "docs/map/atlas-map.html")
        for pat, key in ((r"出厂测试 ×(\d+)", "出厂测试文件"),
                         (r"tests/ (\d+) 文件", "出厂测试文件"),
                         (r"契约 ×(\d+)", "共享契约"),
                         (r"内核 ×(\d+)", "共享内核")):
            for cm in re.finditer(pat, html):
                if int(cm.group(1)) != derived[key]:
                    out.append({"sev": "FAIL", "code": "snapshot_drift", "where": "docs/map/atlas-map.html",
                                "msg": f"html「{cm.group(0)}」≠ 实况 {derived[key]}"})
    return out




# ---------------- 出厂测试 ----------------

def test_docs_map_anchors_alive() -> None:
    vs = collect_docs(PKG_ROOT)
    assert not vs, "docs/map 锚存活违规 " + str(len(vs)) + " 条:\n" + \
        "\n".join(f"[{v['code']}] {v['where']} {v['msg']}" for v in vs)


def test_docs_map_snapshot_matches_reality() -> None:
    if not (PKG_ROOT / "docs" / "map" / "index.md").is_file():
        import pytest
        pytest.skip("docs/map 不在场(采纳仓装配态;map 工程自用门,缺席 = 如实态非失败——2026-10-25 真发现:beta.8 装配进无 docs/map 采纳仓必红,补缺席守卫)")
    vs = check_snapshot(PKG_ROOT)
    assert not vs, "数字快照与实况不符:\n" + \
        "\n".join(v["msg"] for v in vs)


def test_map_claims_fresh() -> None:
    if not (PKG_ROOT / "docs" / "map" / "index.md").is_file():
        import pytest
        pytest.skip("docs/map 不在场(同上:缺席守卫,2026-10-25 补)")
    vs = check_freshness(PKG_ROOT)
    assert not vs, "docs/map 声明过期(版本/行数/计数):\n" + \
        "\n".join(f"[{v['code']}] {v['msg']}" for v in vs)


def test_m155_stale_claims_must_fail(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    (repo / "scripts" / "a.py").write_text("x = 1\n" * 3, encoding="utf-8")
    (repo / "package.json").write_text('{"version": "0.2.0-beta.6"}', encoding="utf-8")
    (repo / "docs" / "map" / "index.md").write_text(
        "> 锚定版本:v0.1.0\n\n`a`(`scripts/a.py:1`),`scripts/a.py`(99 行)\n", encoding="utf-8")
    vs = check_freshness(repo)
    codes = {v["code"] for v in vs}
    assert "version_stale" in codes and "linecount_stale" in codes, \
        "M155：版本串漂与行数声明漂必须红（喂坏输入未咬 = 假门）"


def _mk_repo(tmp: Path) -> Path:
    (tmp / "scripts").mkdir()
    (tmp / "docs" / "map").mkdir(parents=True)
    return tmp


def test_m151_missing_anchor_path_must_fail(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    (repo / "scripts" / "alive.py").write_text("def keep():\n    pass\n", encoding="utf-8")
    (repo / "docs" / "map" / "a.md").write_text(
        "`keep`(`scripts/gone.py:1`) 死路径\n", encoding="utf-8")
    vs = collect_docs(repo)
    assert any(v["code"] == "path_missing" for v in vs), \
        "M151：指向不存在文件的锚必须红（喂坏输入未咬 = 假门）"


def test_m152_drifted_line_must_fail_and_fix_recovers(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    (repo / "scripts" / "a.py").write_text(
        "x = 1\nx = 2\nx = 3\nx = 4\nx = 5\nx = 6\nx = 7\nx = 8\nx = 9\nx = 10\n\ndef fresh():\n    pass\n",
        encoding="utf-8")
    (repo / "docs" / "map" / "a.md").write_text(
        "`fresh`(`scripts/a.py:1`) 漂移\n", encoding="utf-8")
    vs = collect_docs(repo)
    d = next((v for v in vs if v["code"] == "symbol_drift"), None)
    assert d is not None and d["new"] == 12, "M152：符号在、行号漂必须红并报新行号"
    assert fix_drifts(repo) == 1
    assert "`scripts/a.py:12`" in (repo / "docs" / "map" / "a.md").read_text(encoding="utf-8")
    assert not [v for v in collect_docs(repo) if v["code"] == "symbol_drift"], \
        "M152：--fix 改写后必须复绿"


def test_m153_removed_symbol_must_fail(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    (repo / "scripts" / "a.py").write_text("def other():\n    pass\n", encoding="utf-8")
    (repo / "docs" / "map" / "a.md").write_text(
        "`gone_fn`(`scripts/a.py:1`) 符号已删\n", encoding="utf-8")
    vs = collect_docs(repo)
    assert any(v["code"] == "symbol_gone" for v in vs), \
        "M153：邻接符号在目标文件消失必须红"


def test_m154_bare_line_anchor_must_fail(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    (repo / "scripts" / "a.py").write_text("def fresh():\n    pass\n", encoding="utf-8")
    (repo / "docs" / "map" / "a.md").write_text(
        "说明文字(`scripts/a.py:1`) 无符号\n", encoding="utf-8")
    vs = collect_docs(repo)
    assert any(v["code"] == "bare_anchor" for v in vs), \
        "M154：无邻接符号的裸行号锚必须红（锚形态收进值域）"


if __name__ == "__main__":
    if "--fix" in sys.argv:
        print(f"已改写 {fix_drifts(PKG_ROOT)} 处漂移锚")
    else:
        bad = collect_docs(PKG_ROOT) + check_snapshot(PKG_ROOT) + check_freshness(PKG_ROOT)
        for v in bad:
            print(f"[{v['code']}] {v['where']} {v['msg']}")
        print(f"docs/map 锚门：{'红 ' + str(len(bad)) + ' 条' if bad else '全绿'}")
        sys.exit(1 if bad else 0)
