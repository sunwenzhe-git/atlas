#!/usr/bin/env python3
"""JPA 模型解析 helper（框架知识的合法落点）。

跨文件解析 `@Entity` / `@MappedSuperclass` / `@Embeddable`，合并父类字段与
`@Embedded` 内嵌字段；不做 JPA 继承策略推断（只合并 mapped superclass），
不猜数据库命名策略（无 `@Table` 时表名 = 类名）。纯标准库。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CLASS_RE = re.compile(
    r"\b(?:class|record)\s+([A-Za-z_]\w*)"
    r"(?:\s+extends\s+([A-Za-z_]\w*))?[^{]*\{"
)
FIELD_RE = re.compile(
    r"^\s*(?:private|protected|public)?\s*"
    r"(?:static\s+|final\s+|volatile\s+|transient\s+)*"
    r"([A-Za-z_][\w.<>, ?\[\]]*)\s+(\w+)\s*(?:=.*)?;\s*$"
)
ENUM_RE = re.compile(r"\benum\s+([A-Za-z_]\w*)\s*\{([^}]*)\}", re.S)


def _strip_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    quote = ""
    in_line = False
    in_block = False
    while i < n:
        if in_line:
            if text[i] == "\n":
                in_line = False
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue
        if in_block:
            if text.startswith("*/", i):
                in_block = False
                out.append("  ")
                i += 2
            else:
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue
        if quote:
            out.append(text[i])
            if text[i] == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if text[i] == quote:
                quote = ""
            i += 1
            continue
        if text.startswith("//", i):
            in_line = True
            out.append("  ")
            i += 2
            continue
        if text.startswith("/*", i):
            in_block = True
            out.append("  ")
            i += 2
            continue
        if text[i] in "'\"":
            quote = text[i]
        out.append(text[i])
        i += 1
    return "".join(out)


def _match_brace(text: str, open_pos: int) -> int | None:
    depth = 0
    i = open_pos
    quote = ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _ann_value(annotations: str, name: str) -> str:
    m = re.search(
        r"@%s\s*\(\s*(?:[A-Za-z_]+\s*=\s*)?\"((?:\\.|[^\"\\])*)\"" % re.escape(name),
        annotations,
    )
    return m.group(1) if m else ""


def _has(annotations: str, name: str) -> bool:
    return bool(re.search(r"@%s\b" % re.escape(name), annotations))


def _annotations_before(text: str, pos: int) -> str:
    prefix = text[max(0, pos - 1200):pos]
    cut = max(prefix.rfind("}"), prefix.rfind(";"))
    tail = prefix[cut + 1:] if cut >= 0 else prefix
    return "\n".join(ln.strip() for ln in tail.splitlines() if ln.strip().startswith("@"))


def _fields(body: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pending: list[str] = []
    skip_depth = 0
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if skip_depth > 0:
            skip_depth += line.count("{") - line.count("}")
            continue
        if re.search(r"\b(?:class|record|enum)\s+\w+[^{]*\{", s):
            skip_depth = line.count("{") - line.count("}")
            pending = []
            continue
        if s.startswith("@"):
            pending.append(s)
            continue
        m = FIELD_RE.match(line)
        if not m or "(" in line or re.search(r"\bstatic\b", line):
            if s.endswith(";") or "}" in s:
                pending = []
            continue
        ann = "\n".join(pending)
        pending = []
        if _has(ann, "Transient"):
            continue
        typ, field = m.group(1).strip(), m.group(2)
        if typ in {"return", "throw", "new", "else", "case", "break", "continue",
                   "assert", "yield"} or re.search(r"\breturn\b", s):
            continue
        field = _ann_value(ann, "Column") or _ann_value(ann, "TableField") or field
        flags: list[str] = []
        if _has(ann, "Id") or _has(ann, "EmbeddedId") or _has(ann, "TableId"):
            flags.append("主键")
        if _has(ann, "GeneratedValue"):
            flags.append("自增")
        if re.search(r"@Column\b[^)]*nullable\s*=\s*false", ann):
            flags.append("非空")
        if re.search(r"@Column\b[^)]*unique\s*=\s*true", ann):
            flags.append("唯一")
        lm = re.search(r"@Column\b[^)]*length\s*=\s*(\d+)", ann)
        if lm:
            flags.append(f"长度={lm.group(1)}")
        relation = None
        if any(_has(ann, a) for a in ("ManyToOne", "OneToMany", "OneToOne", "ManyToMany")):
            relation = typ
        rows.append({
            "field": field,
            "type": typ,
            "constraints": "，".join(flags) if flags else None,
            "default": None,
            "relation": relation,
            "enum": typ if _has(ann, "Enumerated") else None,
            "embedded": _has(ann, "Embedded") or _has(ann, "EmbeddedId"),
        })
    return rows


def parse_classes(text: str, rel: str) -> list[dict[str, Any]]:
    clean = _strip_comments(text)
    defs: list[dict[str, Any]] = []
    for m in CLASS_RE.finditer(clean):
        ann = _annotations_before(clean, m.start())
        kind = None
        if _has(ann, "Entity"):
            kind = "entity"
        elif _has(ann, "MappedSuperclass"):
            kind = "mapped"
        elif _has(ann, "Embeddable"):
            kind = "embeddable"
        elif _has(ann, "TableName"):
            kind = "mybatis"
        else:
            kind = "plain"
        open_pos = m.end() - 1
        close = _match_brace(clean, open_pos)
        if close is None:
            continue
        defs.append({
            "name": m.group(1),
            "extends": m.group(2),
            "kind": kind,
            "table": _ann_value(ann, "Table") or _ann_value(ann, "TableName") or m.group(1),
            "fields": _fields(clean[open_pos + 1:close]),
            "rel": rel,
        })
    return defs


def _enum_map(texts: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for text in texts:
        for m in ENUM_RE.finditer(_strip_comments(text)):
            values = [v.strip().split()[0] for v in m.group(2).split(",")
                      if v.strip() and not v.strip().startswith("@")]
            out[m.group(1)] = values
    return out


def parse_project(files: list[Path], root: Path) -> tuple[list[dict], list[dict], list[str]]:
    defs: list[dict[str, Any]] = []
    texts: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = f.relative_to(root).as_posix()
        texts.append(text)
        defs.extend(parse_classes(text, rel))
    if not defs:
        return [], [], []
    by_name = {d["name"]: d for d in defs}
    embeddables = {d["name"]: d for d in defs if d["kind"] == "embeddable"}
    enums_map = _enum_map(texts)

    def resolve(defn: dict[str, Any], stack: set[str], prefix: str = "",
                merge_plain: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        index: dict[str, int] = {}

        def add(row: dict[str, Any]) -> None:
            name = row["field"]
            if name in index:
                out[index[name]] = row
            else:
                index[name] = len(out)
                out.append(row)

        base = by_name.get(defn.get("extends") or "")
        merge = base is not None and base["name"] not in stack and (
            base["kind"] == "mapped" or (merge_plain and base["kind"] in ("plain", "mybatis"))
        )
        if merge:
            for row in resolve(base, stack | {defn["name"]}, prefix, merge_plain):
                add(row)
        for row in defn["fields"]:
            name = prefix + row["field"]
            if row["embedded"] and row["type"] in embeddables:
                for nested in resolve(embeddables[row["type"]], stack | {defn["name"]}, name + "."):
                    add(nested)
                continue
            copy = dict(row)
            copy["field"] = name
            add(copy)
        return out

    items: list[dict] = []
    enums: list[dict] = []
    for d in defs:
        if d["kind"] not in ("entity", "mybatis"):
            continue
        table = d["table"]
        for row in resolve(d, set(), "", d["kind"] == "mybatis"):
            row = dict(row)
            row.pop("embedded", None)
            row["table"] = table
            row["source_file"] = d["rel"]
            if row.get("enum") and row["type"] in enums_map:
                enums.append({
                    "table": table,
                    "field": row["field"],
                    "values": [{"value": v, "meaning": ""} for v in enums_map[row["type"]]],
                })
            items.append(row)
    sources = sorted({row["source_file"] for row in items})
    return items, enums, sources
