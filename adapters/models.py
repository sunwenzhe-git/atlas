#!/usr/bin/env python3
"""atlas 事实抽取适配器 —— models（E 类：数据模型清单）。

契约见 `.atlas/shared/stack-profile.md` §3（调用方式 / 输出 JSON / items 字段）。
本文件是**框架知识的合法落点**：适配器内部识别 ORM 声明式模型；atlas 核心不认任何框架。

做法：用标准库 `ast` **静态解析**（不 import、不执行）声明式模型文件，
逐字段产出一行 `items[]`，并把列级枚举收进顶层 `enums[]`。

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

ADAPTER = "models"
VERSION = "0.1.0"

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
