#!/usr/bin/env python3
"""atlas 事实抽取适配器 —— models（E 类：数据模型清单）。

契约见 `.atlas/shared/stack-profile.md` §3（调用方式 / 输出 JSON / items 字段）。
本文件是**框架知识的合法落点**：适配器内部识别 ORM 声明式模型；atlas 核心不认任何框架。

两种来源（同一份 `items[]` 契约，互不排斥）：

* **Python 侧**：标准库 `ast` **静态解析**（不 import、不执行）声明式模型文件
  （SQLAlchemy `__tablename__` + `Column`、SQLModel `table=True`）。
* **TS 侧**（2026-10-15 补）：前端 adopt 的 E 类事实 = 对外类型声明。判据 = **契约层声明文件**
  （路径含 `types/` `api/` `dto/` … 目录，或文件名即 `types.ts` / `api.ts` …）里 **`export`
  的 `interface` / `type … = {`**；`?` ⇒ 可空、`readonly` ⇒ 只读、字面量联合 ⇒ 枚举、
  `extends` ⇒ 父字段并入。**为何要它**：不接 TS 侧时前端项目的 models 产出恒为 **0 条**，
  而 `models` 有对账方（seed × models 静态对账）⇒ 该平面从配门退回「agent 手写」；实测手写会
  产类型解析瑕疵（`type` 别名被当 `interface` 抽字段、泛型尾部多 `>`）。**为何收窄到契约层**：
  组件 Props / Ref / Context 也是 `export` 的，但它们不是数据模型（见 `_TS_DECL_DIRS` 处实测）。

用法：
    python3 models.py --root <代码根> [--app <name>] --out <json 路径>
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import strip_js_comments  # noqa: E402  # 同包共用工具（引号感知的注释剥离）

ADAPTER = "models"
VERSION = "0.2.0"

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "site-packages", "dist", "build",
    ".pyxle-build", ".next", ".turbo", ".mypy_cache", ".pytest_cache", "tests",
}


def die(msg: str) -> None:
    print(f"ERROR[{ADAPTER}]: {msg}", file=sys.stderr)
    sys.exit(1)


def iter_py(root: Path, app_path: str | None):
    base = root / app_path if app_path else root
    if not base.exists():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.startswith(".venv") and not d.endswith(".venv")
        )
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def load_apps(root: Path) -> list[dict]:
    p = root / "product" / "stack-profile.yaml"
    if not p.is_file():
        return []
    apps: list[dict] = []
    cur: dict | None = None
    in_apps = False
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("apps:"):
            in_apps = True
            continue
        if in_apps and line[:1] not in (" ", "\t"):
            in_apps = False
            cur = None
            continue
        if not in_apps:
            continue
        m = re.match(r"^\s*-\s*name:\s*(.+?)\s*$", line)
        if m:
            cur = {"name": m.group(1).strip().strip("'\"")}
            apps.append(cur)
            continue
        m = re.match(r"^\s+(path|role):\s*(.+?)\s*$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip().strip("'\"")
    return apps


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
    elif isinstance(node, ast.Name):
        return node.id
    return None


def _is_true(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _render(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse 覆盖 Python 3.9+
        return ""


def _strip_lambda(text: str) -> str:
    t = text.strip()
    if t.startswith("lambda"):
        _, _, body = t.partition(":")
        t = body.strip()
    return t


def _default_text(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    t = _strip_lambda(_render(node))
    if len(t) >= 2 and t[0] in "'\"" and t[-1] == t[0]:
        return t[1:-1]
    return t or None


def _index_columns(class_node: ast.ClassDef) -> dict[str, str]:
    """__table_args__ 里 Index("name", "col", ...) → {col: index name}。"""
    out: dict[str, str] = {}
    for stmt in class_node.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__table_args__" for t in stmt.targets):
            continue
        for elt in ast.walk(stmt.value):
            if isinstance(elt, ast.Call) and _call_name(elt) == "Index":
                idx_name = elt.args[0].value if elt.args and isinstance(elt.args[0], ast.Constant) else ""
                for a in elt.args[1:]:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        out[a.value] = idx_name or "index"
    return out


def parse_models(text: str) -> tuple[list[dict], list[dict]]:
    tree = ast.parse(text)
    items: list[dict] = []
    enums: list[dict] = []
    # 继承字段合并（2026-09-28 补，`3509 §B118`）：SQLModel 的表类**继承父类的字段**
    # （`class User(UserBase, table=True)` ⇒ 父类的 email / is_active / … 也是该表的列）⇒
    # 只看类自身 body 会**少列**（实测：`user` 表只抽到 3 列，实际 7 列）。
    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}

    def body_of(name: str, seen: set[str]) -> list:
        if name in seen or name not in classes:
            return []
        seen.add(name)
        node = classes[name]
        stmts = list(node.body)
        for b in node.bases:
            if isinstance(b, ast.Name):
                stmts += body_of(b.id, seen)
        return stmts

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        table = None
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__tablename__" for t in stmt.targets
            ) and isinstance(stmt.value, ast.Constant):
                table = stmt.value.value
        if not table:
            # SQLModel：`class X(Base, table=True)` ⇒ **只有 `table=True` 的类才是表**
            # （`UserCreate` / `UserPublic` 这类 DTO 不算）；表名默认 = 类名小写（SQLModel 约定）。
            if any(isinstance(k, ast.keyword) and k.arg == "table" and _is_true(k.value)
                   for k in node.keywords):
                table = node.name.lower()
        if not table:
            continue
        index_cols = _index_columns(node)
        for stmt in body_of(node.name, set()):
            #   ① SQLAlchemy：`x = Column(T, **kw)`   ② SQLModel：`x: T = Field(**kw)`
            relation = None
            enum_name = None
            enum_values: list[str] = []
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                field = stmt.target.id
                typ = _render(stmt.annotation) if stmt.annotation is not None else ""
                type_node = None
                if isinstance(stmt.value, ast.Call) and _call_name(stmt.value) == "Field":
                    kw = {k.arg: k.value for k in stmt.value.keywords}
                else:
                    kw = {}
            elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                    and isinstance(stmt.targets[0], ast.Name) \
                    and isinstance(stmt.value, ast.Call) and _call_name(stmt.value) == "Column":
                field = stmt.targets[0].id
                call = stmt.value
                type_node = call.args[0] if call.args else None
                typ = _render(type_node) if type_node is not None else ""
                if isinstance(type_node, ast.Call):
                    iname = _call_name(type_node)
                    if iname == "ForeignKey" and type_node.args and isinstance(type_node.args[0], ast.Constant):
                        relation = str(type_node.args[0].value)
                    if iname == "Enum":
                        enum_values = [a.value for a in type_node.args
                                       if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                        for kw in type_node.keywords:
                            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                                enum_name = str(kw.value.value)
                kw = {k.arg: k.value for k in call.keywords}
            else:
                continue
            flags: list[str] = []
            if _is_true(kw.get("primary_key")):
                flags.append("主键")
            if _is_true(kw.get("autoincrement")):
                flags.append("自增")
            if "nullable" in kw:
                flags.append("可空" if _is_true(kw.get("nullable")) else "非空")
            if _is_true(kw.get("unique")):
                flags.append("唯一")
            if _is_true(kw.get("index")) or field in index_cols:
                flags.append("索引")
            if "onupdate" in kw:
                flags.append("onupdate 同值")

            row = {
                "table": table,
                "field": field,
                "type": typ,
                "constraints": "，".join(flags) if flags else None,
                "default": _default_text(kw.get("default")),
                "relation": relation,
                "enum": enum_name or ("枚举" if enum_values else None),
            }
            items.append(row)
            if enum_values:
                enums.append({
                    "table": table,
                    "field": field,
                    "values": [{"value": v, "meaning": ""} for v in enum_values],
                })
    return items, enums


def iter_ts(root: Path, app_path: str | None):
    base = root / app_path if app_path else root
    if not base.exists():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.startswith(".venv") and not d.endswith(".venv")
        )
        for name in sorted(filenames):
            # `*.d.ts` 是库 / 打包器产物（不是本项目的模型声明）⇒ 跳过。
            if name.endswith((".ts", ".tsx")) and not name.endswith(".d.ts"):
                yield Path(dirpath) / name


# ---------------------------------------------------------------- TS：export 的 interface / type

# 只有 **`export` 的对外类型** 才算模型；`{` / `;` 之前的部分是声明头（可含 `extends A, B`）。
_TS_IFACE_RE = re.compile(
    r"(?m)^\s*export\s+(?:declare\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"(?:<[^{;]*?>)?\s*(?P<head>[^{;]*?)\{"
)
# `type X = { … }`：`=` 与 `{` 之间只许空白——这样 `type Status = 'a' | 'b'`（无字段体）
# 与 `type A = B`（别名）都不会被误当模型（实测手写脚本的 `TMCPType` 就是栽在这）。
_TS_TYPE_RE = re.compile(
    r"(?m)^\s*export\s+(?:declare\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"(?:<[^{;]*?>)?\s*=\s*\{"
)
_TS_MEMBER_RE = re.compile(r"^(?:readonly\s+)?([A-Za-z_$][\w$]*)\s*(\?)?\s*:\s*([\s\S]+)$")
_TS_LITERAL_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"")
# 顶层枚举声明两形态（无字段体 ⇒ 自身不成行，但字段引它时要知道取值）：
#   `export type Status = 'a' | 'b'` 与 `export enum Status { A = 'a', B = 'b' }`
_TS_ENUM_RE = re.compile(
    r"(?m)^\s*export\s+(?:declare\s+)?enum\s+([A-Za-z_$][\w$]*)\s*\{")
_TS_ALIAS_RE = re.compile(
    r"(?m)^\s*export\s+(?:declare\s+)?type\s+([A-Za-z_$][\w$]*)\s*"
    r"(?:<[^{;]*?>)?\s*=\s*([^;{\n]+)")

# 模型声明文件的**路径判据**：契约层目录（`types/` `api/` `dto/` …）或契约层文件名（`types.ts` …）。
# 为何必须收窄（2026-10-15 实测真项目）：不收窄时 149 个源文件里 87 个是组件 Props / Ref /
# Context（`IScriptEditModalProps`、`IWorkFlowStore`、`IRadioItemProps`…）——那是 UI 管道，
# 不是数据模型。事实表混进它们，等于让 agent 在噪声里找模型（`§B118` 同族：假事实比缺口更贵）。
_TS_DECL_DIRS = {
    "types", "type", "api", "apis", "model", "models",
    "dto", "dtos", "schema", "schemas", "interface", "interfaces",
}
_TS_DECL_FILE_RE = re.compile(r"^(?:api|apis|types?|models?|dtos?|schemas?)\.(?:ts|tsx)$")


def _ts_decl_file(rel: str) -> bool:
    """该文件是否**契约层声明文件**（模型抽取的准入判据）。"""
    segs = rel.split("/")
    return (any(s in _TS_DECL_DIRS for s in segs[:-1])
            or bool(_TS_DECL_FILE_RE.match(segs[-1])))


def _brace_end(text: str, start: int) -> int:
    """`text[start]` 是 `{` ⇒ 配对 `}` 的下标；未配对 ⇒ -1。引号 / 模板串内的括号不参与。"""
    depth = 0
    i, n = start, len(text)
    quote = ""
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _members(body: str) -> list[str]:
    """块内 depth==0 的成员片段：按 `;` / `,` / 换行切，嵌套 `{}`/`()`/`<>` 内的不切。

    `=>` 的 `>` **不降 depth**：否则 `(a: A) => void;` 之后永远碰不到 depth==0，
    整块会被并成一片（于是整个 interface 只剩一个字段）。
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    quote = ""
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(body[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in "{([<":
            depth += 1
        elif ch in "})]":
            depth = max(0, depth - 1)
        elif ch == ">" and not (buf and buf[-1] == "="):
            depth = max(0, depth - 1)
        if ch in ";\n," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def _ts_enum_values(typ: str) -> list[str]:
    """字符串字面量联合（`'SSE' | 'STREAMABLE_HTTP'`）⇒ 枚举取值；**≥2 个才算枚举**。

    去掉所有字面量后必须只剩 `|`：任何残留（如 `'a' | SomeType`）即判非枚举，绝不半收。
    """
    if "|" not in typ:
        return []
    if re.sub(r"'[^']*'|\"[^\"]*\"", "", typ).replace("|", "").strip():
        return []
    vals = [m.group(1) if m.group(1) is not None else m.group(2)
            for m in _TS_LITERAL_RE.finditer(typ)]
    return vals if len(vals) >= 2 else []


def _ts_relation(typ: str, names: set[str]) -> str | None:
    """字段类型就是本文件另一个模型（可带 `[]`）⇒ 关系；否则 None。

    只认**同文件**。跨文件的类型引用**直接丢弃**（2026-10-15 复核更正措辞）：渲染期
    `refresh_structure.py` 只按 `source_file` 做「行 → 域」归属，**不解析类型引用**；
    且 `关系` 是适配器列（`MODEL_HEADER` 全列都在 `enum` 集里），agent 也补不进去。
    这里不猜跨文件，是为了不产假关系（宁缺）。
    """
    t = re.sub(r"(\[\s*\])+$", "", typ.strip()).strip()
    return t if t in names else None


def _ts_enum_members(body: str) -> list[str]:
    """`export enum` 的成员 → 取值串（`A = 'a'` 取 `'a'` 的字面量；裸 `A` 取成员名）。"""
    vals: list[str] = []
    for member in _members(body):
        m = re.match(r"^([A-Za-z_$][\w$]*)\s*=\s*(.+)$", member)
        if m:
            lit = _TS_LITERAL_RE.match(m.group(2).strip())
            vals.append((lit.group(1) if lit and lit.group(1) is not None
                         else lit.group(2)) if lit else m.group(2).strip())
        elif re.fullmatch(r"[A-Za-z_$][\w$]*", member):
            vals.append(member)
    return vals


def _ts_enum_table(src: str) -> tuple[dict[str, list[str]], int]:
    """**同文件「别名 / 枚举名 → 取值」旁表**（2026-10-15 补，零契约改动）。

    为何要它：`type TMCPType = 'CUSTOMER' | …` 与 `export enum X {…}` 这两种声明
    **自身没有字段体**，进不了 `items[]`（`table · field` 是行键，接不住独立枚举——
    见 §3.2 的 `enums[]` 形状）。但**引用它们的字段**（`mcpType: TMCPType`）本可以拿到
    取值，旁表就是这一层：字段类型命中旁表 ⇒ 该行补 `枚举` + `enums[]` 取值。
    返回 (旁表, 识别到的声明数) —— 后者供「先量」统计。
    """
    table: dict[str, list[str]] = {}
    n = 0
    for m in _TS_ALIAS_RE.finditer(src):
        vals = _ts_enum_values(m.group(2))
        if vals:
            table[m.group(1)] = vals
            n += 1
    for m in _TS_ENUM_RE.finditer(src):
        end = _brace_end(src, m.end() - 1)
        if end < 0:
            continue
        vals = _ts_enum_members(src[m.end():end])
        if vals:
            table[m.group(1)] = vals
            n += 1
    return table, n


def _ts_blocks(src: str) -> dict[str, tuple[str, list[str]]]:
    """`{模型名: (块体, 父类型名列表)}`（interface 与 type 两种声明体）。"""
    blocks: dict[str, tuple[str, list[str]]] = {}
    for m in _TS_IFACE_RE.finditer(src):
        end = _brace_end(src, m.end() - 1)
        if end < 0:
            continue
        head = m.group("head") or ""
        parents = (re.findall(r"[A-Za-z_$][\w$]*", head.split("extends", 1)[1])
                   if "extends" in head else [])
        blocks[m.group("name")] = (src[m.end():end], parents)
    for m in _TS_TYPE_RE.finditer(src):
        end = _brace_end(src, m.end() - 1)
        if end < 0:
            continue
        blocks.setdefault(m.group("name"), (src[m.end():end], []))
    return blocks


def _ts_members_of(name: str, blocks: dict, seen: set[str]) -> list[str]:
    """`extends` 的父类型字段并入（对照 Python 侧的 SQLModel 继承合并）。"""
    if name in seen or name not in blocks:
        return []
    seen.add(name)
    body, parents = blocks[name]
    out = list(_members(body))
    for p in parents:
        out += _ts_members_of(p, blocks, seen)
    return out


def parse_ts_models(src: str) -> tuple[list[dict], list[dict], dict]:
    """`export` 的 interface / type 声明 → 每字段一行 + 顶层 `enums[]`（+ 先量统计）。"""
    blocks = _ts_blocks(src)
    names = set(blocks)
    alias, n_enum_decls = _ts_enum_table(src)
    items: list[dict] = []
    enums: list[dict] = []
    n_alias_refs = 0
    for table in sorted(blocks):
        for member in _ts_members_of(table, blocks, set()):
            m = _TS_MEMBER_RE.match(member)
            if not m:
                continue      # 方法签名 / 索引签名 / 注释残留：不是字段
            field, opt, typ = m.group(1), m.group(2), m.group(3).strip()
            flags: list[str] = []
            if opt:
                flags.append("可空")
            if member.lstrip().startswith("readonly"):
                flags.append("只读")
            vals = _ts_enum_values(typ)
            if not vals:
                t = re.sub(r"(\[\s*\])+$", "", typ.strip()).strip()
                if t in alias:                      # 字段引顶层别名 / enum ⇒ 旁表补取值
                    vals = alias[t]
                    n_alias_refs += 1
            items.append({
                "table": table,
                "field": field,
                "type": typ,
                "constraints": "，".join(flags) if flags else None,
                "default": None,
                "relation": _ts_relation(typ, names),
                "enum": "枚举" if vals else None,
            })
            if vals:
                enums.append({
                    "table": table,
                    "field": field,
                    "values": [{"value": v, "meaning": ""} for v in vals],
                })
    stats = {"enum_decls": n_enum_decls, "alias_refs": n_alias_refs}
    return items, enums, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--app", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        die(f"--root 不是目录: {root}")

    apps = load_apps(root)
    app_path = None
    if args.app:
        hit = next((a for a in apps if a.get("name") == args.app), None)
        if hit is None:
            die(f"--app {args.app} 不在 stack-profile.apps 中")
        app_path = hit.get("path") or hit.get("name")

    items: list[dict] = []
    enums: list[dict] = []
    source_files: list[str] = []
    for f in iter_py(root, app_path):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        # 两种声明风格都收：SQLAlchemy 式（`__tablename__` + `Column(`）与 **SQLModel 式**
        # （`class X(Base, table=True)` + 带注解的字段）。2026-09-28 实测（`3509 §B118`）：
        # 原闸门只认前者 ⇒ 本栈（SQLModel）整文件被跳过 ⇒ `models` 产出 0 条。
        sqlalchemy_style = "__tablename__" in text and "Column(" in text
        sqlmodel_style = bool(re.search(r"^\s*class\s+\w+\([^)]*\btable\s*=\s*True", text, re.M))
        if not (sqlalchemy_style or sqlmodel_style):
            continue
        try:
            file_items, file_enums = parse_models(text)
        except SyntaxError as e:
            print(f"WARN[{ADAPTER}]: 跳过无法解析的文件 {f}: {e}", file=sys.stderr)
            continue
        if not file_items:
            continue
        rel = f.relative_to(root).as_posix()
        source_files.append(rel)
        for it in file_items:
            it["source_file"] = rel
        items.extend(file_items)
        enums.extend(file_enums)

    # TS 侧：契约层声明文件里 `export` 的 interface / type 声明体（前端 adopt 的 E 类事实）。
    n_enum_decls = n_alias_refs = 0
    for f in iter_ts(root, app_path):
        rel = f.relative_to(root).as_posix()
        if not _ts_decl_file(rel):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        if not (_TS_IFACE_RE.search(text) or _TS_TYPE_RE.search(text)
                or _TS_ENUM_RE.search(text)):
            continue
        file_items, file_enums, stats = parse_ts_models(strip_js_comments(text))
        n_enum_decls += stats["enum_decls"]
        n_alias_refs += stats["alias_refs"]
        if not file_items:
            continue
        source_files.append(rel)
        for it in file_items:
            it["source_file"] = rel
        items.extend(file_items)
        enums.extend(file_enums)
    if n_enum_decls or n_alias_refs:
        # 「先量再动手」（global-rules.md §12）：独立枚举声明自身进不了 items（行键是
        # 表+字段，接不住无字段体的枚举），这里只报数量——是否要为它扩契约形状，等有数再定。
        print(f"[{ADAPTER}] 统计：顶层枚举/字面量别名声明 {n_enum_decls} 个（自身不成行）；"
              f"字段引用旁表补回取值 {n_alias_refs} 处", file=sys.stderr)

    out = {
        "category": "models",
        "items": items,
        "enums": enums,
        "source_files": sorted(source_files),
        "adapter_version": VERSION,
    }
    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[{ADAPTER}] {len(items)} 个字段 / {len(enums)} 个枚举 / {len(source_files)} 个源文件 -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
