#!/usr/bin/env python3
"""atlas 结构环校验器 —— 按 `rings/structure/reference.md` §7 校验清单对结构产物做机器校验。

- **框架无关**：本文件不得出现任何具体框架名（共享契约 global-rules.md §1）。
- 纯标准库；对 `<项目根>/.trellis/spec/structure/` 可回归。
- 输出 PASS / FAIL；有 FAIL 时非零退出。

用法：
    python3 validate_structure.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_MAX_TOTAL = 9500
DOMAIN_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

TABLE_DIRECTORY_MAP = ["路径", "类型", "职责（一句话）", "域", "备注"]
TABLE_ROUTES = ["页面/路由", "域", "用途", "关键交互", "实现状态", "来源文件"]
TABLE_DATA_MODELS = ["表/模型", "字段", "类型", "约束/默认", "关系", "枚举"]
TABLE_APIS = ["方法", "路径", "用途", "请求要点", "响应要点", "来源模块"]

FORBIDDEN = ["TODO", "待补充", "TBD", "待定", "(To be filled)", "[FIELD:]", "视情况而定", "后续补充"]

SECRET_RES = [
    re.compile(r"\bsk-[A-Za-z0-9]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|passwd|password|secret|access[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})"),
]
PATH_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,6}$")


class Result:
    def __init__(self) -> None:
        self.ok = True
        self.rows: list[dict] = []
        self.warns: list[dict] = []

    def add(self, check: str, ok: bool, detail: str = "") -> None:
        if not ok:
            self.ok = False
        self.rows.append({"check": check, "ok": ok, "detail": detail})

    def add_warn(self, check: str, detail: str) -> None:
        # WARN = 提示补，不置红、不影响退出码（契约 §7「校验器记 WARN」的通道）
        self.warns.append({"check": check, "detail": detail})


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def norm_cell(c: str) -> str:
    return c.strip().strip("`").replace("\\|", "|").strip()


def split_row(ln: str) -> list[str]:
    """按**未转义**的 `|` 切分表格行；单元格内的 `\\|` 还原为 `|`（与 refresh_structure
    的 render_table 转义配对，2026-10-04：字段类型 `datetime | None` 一类含竖线的值
    曾被裸切分撑列，行被 len 过滤静默丢弃）。"""
    s = ln.strip()
    body = s[1:-1] if s.endswith("|") else s[1:]
    return [norm_cell(c) for c in re.split(r"(?<!\\)\|", body)]


def first_table(text: str) -> list[str] | None:
    lines = text.splitlines()
    for i in range(len(lines) - 1):
        if not lines[i].lstrip().startswith("|"):
            continue
        sep = lines[i + 1]
        if re.match(r"^\s*\|?[\s:|-]+\|", sep) and "-" in sep:
            return split_row(lines[i])
    return None


def table_rows(text: str, header: list[str]) -> list[dict]:
    lines = text.splitlines()
    for i in range(len(lines) - 1):
        if not lines[i].lstrip().startswith("|"):
            continue
        if not re.match(r"^\s*\|?[\s:|-]+\|", lines[i + 1]) or "-" not in lines[i + 1]:
            continue
        rows = []
        for ln in lines[i + 2:]:
            if not ln.lstrip().startswith("|"):
                break
            cells = split_row(ln)
            if len(cells) == len(header):
                rows.append(dict(zip(header, cells)))
        return rows
    return []


def frontmatter(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    return text[3:end]


def paths_block(fm: str) -> tuple[bool, str]:
    lines = fm.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*paths\s*:\s*(.*)$", ln)
        if not m:
            continue
        if m.group(1).strip():
            return False, "paths 是标量（malformed）"
        j = i + 1
        items = []
        while j < len(lines) and (not lines[j].strip() or re.match(r"^\s+-", lines[j])):
            if lines[j].strip():
                items.append(lines[j].strip())
            j += 1
        return (bool(items), "" if items else "paths 列表为空")
    return False, "缺 paths 键"


def read_max_total(root: Path) -> int:
    cfg = root / ".trellis" / "config.yaml"
    if cfg.is_file():
        m = re.search(r"^\s*max_total_chars:\s*(\d+)", cfg.read_text(encoding="utf-8"), re.M)
        if m:
            return int(m.group(1))
    return DEFAULT_MAX_TOTAL


def _path_candidates(text: str):
    for tok in re.findall(r"`([^`\n]+)`", text):
        t = re.sub(r":\d+(?:-\d+)?$", "", tok.strip())
        if t.startswith(("~", "http://", "https://", "{", "<", "/", "npm ", "pip ", "python3 ", "bash ")):
            continue
        if "/" not in t:
            continue
        if not (PATH_EXT_RE.search(t) or "*" in t):
            continue
        if any(ch in t for ch in " ()<>|{}"):
            continue
        yield t


def validate(root: Path) -> Result:
    res = Result()
    spec = root / ".trellis" / "spec" / "structure"

    if not spec.is_dir():
        res.add("域模型", False, f"缺少结构事实根 {spec}")
        return res

    meta_path = spec / "_meta.json"
    if not meta_path.is_file():
        res.add("域模型", False, "缺少 _meta.json")
        return res
    try:
        meta = json.loads(read(meta_path))
    except (OSError, json.JSONDecodeError) as e:
        res.add("域模型", False, f"_meta.json 无法解析: {e}")
        return res

    # 绿地豁免：apps[].path 均不存在（尚无应用代码）时，域清单与 global 事实允许为空骨架
    app_paths = [a.get("path") for a in (meta.get("apps") or [])
                 if isinstance(a, dict) and a.get("path")]
    greenfield = bool(app_paths) and not any((root / ap).exists() for ap in app_paths)

    domains = meta.get("domains") or []
    ids = [d.get("id") for d in domains if isinstance(d, dict)]
    bad_ids = [i for i in ids if not (isinstance(i, str) and DOMAIN_ID_RE.match(i))]
    dup = sorted({i for i in ids if i and ids.count(i) > 1})
    no_globs = [d.get("id") for d in domains
                if not (isinstance(d, dict) and isinstance(d.get("globs"), list) and d.get("globs"))]
    disk = sorted(p.stem for p in (spec / "domains").glob("*.md")) if (spec / "domains").is_dir() else []
    res.add("域模型 · domains[]", (bool(domains) or greenfield) and not bad_ids and not dup,
            f"greenfield={greenfield} 非法 id={bad_ids} 重复={dup} 空 globs={no_globs}")
    res.add("域模型 · 域目录与 domains[] 一致",
            disk == sorted(ids) or (greenfield and not ids),
            f"greenfield={greenfield} 磁盘={disk} meta={sorted(ids)}")

    # 类别覆盖
    globals_missing = [n for n in ("directory-map.md", "routes.md")
                       if not (spec / "global" / n).is_file()]
    cat = meta.get("categories") or {}
    a_ok = isinstance(cat.get("A"), str) and cat["A"].split("：")[0].split(":")[0].strip() in ("covered", "skipped")
    h_ok_vals = ("covered", "added", "skipped") if greenfield else ("covered", "added")
    h_ok = isinstance(cat.get("H"), str) and cat["H"].split("：")[0].split(":")[0].strip() in h_ok_vals
    role_issues = []
    for role in ("current", "legacy"):
        base = spec / role
        if not base.is_dir():
            continue
        for sub in sorted(p for p in base.iterdir() if p.is_dir()):
            if sub.name not in ids:
                role_issues.append(f"{role}/{sub.name} 不在 domains[]")
                continue
            for req in ("apis.md", "data-models.md"):
                if not (sub / req).is_file():
                    role_issues.append(f"{role}/{sub.name} 缺 {req}")
    res.add("类别覆盖 · global/", (not globals_missing) or greenfield,
            f"greenfield={greenfield} 缺 {globals_missing}")
    res.add("类别覆盖 · 域级 apis/data-models", not role_issues, "；".join(role_issues))
    res.add("类别覆盖 · categories A/H", a_ok and h_ok, f"A={cat.get('A')!r} H={cat.get('H')!r}")

    # 元数据一致 · apps / product
    res.add("元数据 · product/apps", bool(meta.get("product")) and isinstance(meta.get("apps"), list) and meta.get("apps"),
            "缺 product 或 apps[]")

    # global/routes.md 域列
    routes_md = spec / "global" / "routes.md"
    if routes_md.is_file():
        rtext = read(routes_md)
        header = first_table(rtext) or []
        unknown = []
        if "域" not in header:
            unknown.append("routes.md 无「域」列")
        else:
            for row in table_rows(rtext, header):
                cell = row.get("域", "")
                for tok in re.split(r"[/、,，]", cell):
                    tok = tok.strip().strip("`")
                    if tok and tok not in ("—", "-", "各域") and tok not in ids:
                        unknown.append(tok)
        res.add("域模型 · routes 域列 ⊆ domains", not unknown, "；".join(sorted(set(unknown))))

        # 语义列留空 ⇒ WARN 指名（`§B121`：契约承诺必须配判据；「—」是合法占位，不算留空）
        header = first_table(rtext) or []
        gaps = []
        for row in table_rows(rtext, header):
            empty = [c for c in ("用途", "关键交互", "实现状态") if not row.get(c, "").strip()]
            if empty:
                gaps.append(f"{row.get('页面/路由', '?')} 缺 {'/'.join(empty)}")
        if gaps:
            res.add_warn("routes 语义列", "；".join(gaps))

    # D 形态
    d_issues = []
    for p in sorted(spec.glob("*/*/apis.md")):
        t = read(p)
        head = first_table(t)
        is_list = head == TABLE_APIS
        is_pointer = "真相源" in t
        rel = p.relative_to(spec).as_posix()
        if is_list and is_pointer:
            d_issues.append(f"{rel} 清单与指针混写")
        elif not is_list and not is_pointer:
            d_issues.append(f"{rel} 既非清单也非指针")
    res.add("D 形态", not d_issues, "；".join(d_issues))

    # 指针预算
    max_total = read_max_total(root)
    tour = spec / "tour.md"
    tour_len = len(read(tour)) if tour.is_file() else 0
    over = []
    for d in domains:
        did = d.get("id")
        p = spec / "domains" / f"{did}.md"
        total = tour_len + (len(read(p)) if p.is_file() else 0)
        if total > max_total:
            over.append(f"{did}={total}")
    res.add("指针预算 L1+L2", not over, f"上限 {max_total}；超出 {over}")

    # 注入结构
    inj = []
    for p in [tour] + sorted((spec / "domains").glob("*.md")):
        if not p.is_file():
            inj.append(f"缺 {p.name}")
            continue
        ok, why = paths_block(frontmatter(read(p)) or "")
        if not ok:
            inj.append(f"{p.name}: {why}")
    res.add("注入结构 paths 块列表", not inj, "；".join(inj))

    # 占位符
    place = []
    for p in sorted(spec.rglob("*.md")):
        for n, ln in enumerate(read(p).splitlines(), 1):
            for word in FORBIDDEN:
                if word in ln:
                    place.append(f"{p.relative_to(spec)}:{n} 含「{word}」")
    res.add("占位符", not place, "；".join(place))

    # 表格列
    col_issues = []
    dm = spec / "global" / "directory-map.md"
    if dm.is_file() and first_table(read(dm)) != TABLE_DIRECTORY_MAP:
        col_issues.append(f"directory-map 列头={first_table(read(dm))}")
    if routes_md.is_file():
        head = first_table(read(routes_md)) or []
        if head != TABLE_ROUTES and head != ["应用"] + TABLE_ROUTES:
            col_issues.append(f"routes 列头={head}")
    for p in sorted(spec.glob("*/*/data-models.md")):
        if first_table(read(p)) != TABLE_DATA_MODELS:
            col_issues.append(f"{p.relative_to(spec)} 列头不符")
    for p in sorted(spec.glob("*/*/apis.md")):
        head = first_table(read(p))
        if head is not None and head != TABLE_APIS and "真相源" not in read(p):
            col_issues.append(f"{p.relative_to(spec)} 列头={head}")
    res.add("表格列", not col_issues, "；".join(col_issues))

    # 来源可定位（先按项目根解析，再按各 app 根解析——短引用允许 app 相对）
    app_paths = [a.get("path") for a in (meta.get("apps") or []) if isinstance(a, dict) and a.get("path")]

    def resolves(target: str) -> bool:
        bases = [root] + [root / ap for ap in app_paths]
        if "*" in target:
            return any(any(b.glob(target)) for b in bases)
        return any((b / target).exists() for b in bases)

    missing = []
    for p in sorted(spec.rglob("*.md")):
        for tok in _path_candidates(read(p)):
            target = re.sub(r":\d+(?:-\d+)?$", "", tok)
            if not resolves(target):
                missing.append(f"{p.relative_to(spec)} -> {tok}")
    res.add("来源可定位", not missing, "；".join(sorted(set(missing))))

    # 密钥泄漏
    leaks = []
    for p in sorted(spec.rglob("*.md")):
        for n, ln in enumerate(read(p).splitlines(), 1):
            for rx in SECRET_RES:
                m = rx.search(ln)
                if m:
                    leaks.append(f"{p.relative_to(spec)}:{n} 疑似密钥值")
                    break
    res.add("密钥泄漏", not leaks, "；".join(leaks))

    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    res = validate(root)
    if args.json:
        status = "PASS" if res.ok else "FAIL"
        if res.ok and res.warns:
            status = "WARN"
        print(json.dumps({"ok": res.ok, "status": status,
                          "root": str(root), "checks": res.rows, "warns": res.warns},
                         ensure_ascii=False, indent=2))
    else:
        print(f"validate_structure @ {root}")
        for r in res.rows:
            flag = "OK  " if r["ok"] else "FAIL"
            line = f"  [{flag}] {r['check']}"
            if r["detail"] and not r["ok"]:
                line += f" —— {r['detail']}"
            print(line)
        for w in res.warns:
            print(f"  [WARN] {w['check']} —— {w['detail']}")
        print("FAIL" if not res.ok else ("WARN" if res.warns else "PASS"))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
