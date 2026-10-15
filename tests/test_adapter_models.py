#!/usr/bin/env python3
"""`adapters/models.py` 的「喂坏输入必红」判据（`3509 §B118`，2026-09-28）。

**为什么要它**：同 `test_adapter_routes.py` —— 适配器对真实项目的产出是「接线」的前置，
必须有机器判据证明它认本栈的声明形态。

三侧：
  1. **SQLModel 式**：`class X(Base, table=True)` 才是表；**继承字段要合并**（`UserBase` 的 4 列也是该表的列）；
  2. **DTO 不算表**：`class UserCreate(UserBase)` / `class Message(SQLModel)` 无 `table=True` ⇒ 不入 `items`；
  3. **SQLAlchemy 式仍要工作**（回归：不能为了新形态把旧的弄坏）。

**TS 侧**（2026-10-15 补，M53）：前端 adopt 的 E 类事实 = 契约层声明文件里 `export` 的
`interface` / `type … = {`。第 4/5 侧钉住「收什么」与「不收什么」：

  4. **TS 声明体**：可空 / 只读 / 字面量联合 ⇒ 枚举 / `extends` 父字段并入 / 同文件模型引用 ⇒ 关系；
  5. **不收的**：非 `export` 的局部类型、`type X = 'a' | 'b'`（无字段体的别名——实测手写脚本正是在
     这里把类型别名当 `interface` 抽字段）、`*.d.ts`、以及**契约层路径之外**的组件 Props
     （那是 UI 管道，不是数据模型）。

变异 M19：把文件闸门退回「只认 `__tablename__` + `Column(`」⇒ 第 1 侧红。
变异 M53：把 `_ts_decl_file` 的准入判据摘掉（任意路径都收）⇒ 第 5 侧红。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PKG_ROOT / "adapters" / "models.py"

PROFILE = """product: 夹具
apps:
  - name: backend
    path: backend
    kind: backend
    role: landing
    stack: 夹具
"""

SQLMODEL = """import uuid
from sqlmodel import Field, SQLModel


class UserBase(SQLModel):
    email: str = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    full_name: str | None = None


class UserCreate(UserBase):
    password: str = Field(min_length=8)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str


class Message(SQLModel):
    message: str
"""

SQLALCHEMY = """from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Item(Base):
    __tablename__ = "item"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True)
"""


def mk(root: Path, body: str, name: str = "models.py") -> None:
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(PROFILE, encoding="utf-8")
    d = root / "backend" / "app"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


def run(root: Path, app: str = "backend") -> dict:
    out = root / "out.json"
    p = subprocess.run([sys.executable, str(ADAPTER), "--root", str(root),
                        "--app", app, "--out", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_sqlmodel_table_with_inherited_fields() -> None:
    """`table=True` 才算表；**继承字段必须合并**（否则事实区少列）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, SQLMODEL)
        items = run(root)["items"]
        tables = {i["table"] for i in items}
        assert tables == {"user"}, tables
        fields = [i["field"] for i in items]
        for f in ("id", "hashed_password", "email", "is_active", "full_name"):
            assert f in fields, fields
        pk = [i["field"] for i in items if (i.get("constraints") or "").find("主键") >= 0]
        assert pk == ["id"], pk


def test_dto_classes_are_not_tables() -> None:
    """`UserCreate(UserBase)` / `Message(SQLModel)` 无 `table=True` ⇒ 不入 items。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, SQLMODEL)
        tables = {i["table"] for i in run(root)["items"]}
        assert "usercreate" not in tables and "message" not in tables, tables


def test_sqlalchemy_style_still_works() -> None:
    """回归：SQLAlchemy 式（`__tablename__` + `Column(`）不能被新形态弄坏。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, SQLALCHEMY)
        items = run(root)["items"]
        assert {i["table"] for i in items} == {"item"}, items
        assert {i["field"] for i in items} == {"id", "name"}, items


PROFILE_TS = """product: 夹具
apps:
  - name: frontend
    path: frontend
    kind: frontend
    role: landing
    stack: 夹具
"""

TS_TYPES = """\
export interface PageQuery {
  current?: number
  readonly size: number
}

export interface Owner {
  name: string
}

export interface Item extends PageQuery {
  id: string
  kind: 'A' | 'B'
  owner: Owner
  tags: string[]
}

// 非 export 的局部类型：不是对外模型
interface LocalOnly {
  secret: string
}

// 无字段体的类型别名：不是模型（手写脚本正是在这里把别名当 interface 抽字段）
export type Flag = 'on' | 'off'
"""

TS_PROPS = """\
export interface CardProps {
  title: string
}
"""


def mk_ts(root: Path, files: dict) -> None:
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(PROFILE_TS, encoding="utf-8")
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")



def test_ts_interface_fields_enums_and_inheritance() -> None:
    """TS 契约层声明文件：可空 / 只读 / 字面量联合 ⇒ 枚举 / `extends` 父字段并入 / 同文件关系。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_ts(root, {"frontend/src/modules/x/types/index.ts": TS_TYPES})
        data = run(root, "frontend")
        items = data["items"]
        assert {i["table"] for i in items} == {"Item", "Owner", "PageQuery"}, items
        item = {i["field"]: i for i in items if i["table"] == "Item"}
        # `extends PageQuery` ⇒ 父字段并入（对照 SQLModel 继承合并）
        assert set(item) == {"id", "kind", "owner", "tags", "current", "size"}, sorted(item)
        assert item["current"]["constraints"] == "可空", item["current"]
        assert item["size"]["constraints"] == "只读", item["size"]
        assert item["owner"]["relation"] == "Owner", item["owner"]
        assert item["kind"]["enum"] == "枚举", item["kind"]
        assert data["enums"] == [{"table": "Item", "field": "kind",
                                  "values": [{"value": "A", "meaning": ""},
                                             {"value": "B", "meaning": ""}]}], data["enums"]


def test_ts_non_export_alias_and_component_props_are_not_models() -> None:
    """不收：非 `export` 的局部类型、无字段体的别名、契约层路径之外的组件 Props。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_ts(root, {
            "frontend/src/modules/x/types/index.ts": TS_TYPES,
            "frontend/src/modules/x/components/card/index.tsx": TS_PROPS,
        })
        items = run(root, "frontend")["items"]
        tables = {i["table"] for i in items}
        assert "LocalOnly" not in tables, tables     # 非 export
        assert "Flag" not in tables, tables          # 无字段体的别名
        assert "CardProps" not in tables, tables     # 组件 Props（UI 管道）
        assert not any("components/" in i["source_file"] for i in items), items

