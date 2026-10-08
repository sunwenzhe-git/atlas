#!/usr/bin/env python3
"""`adapters/models.py` 的「喂坏输入必红」判据（`3509 §B118`，2026-09-28）。

**为什么要它**：同 `test_adapter_routes.py` —— 适配器对真实项目的产出是「接线」的前置，
必须有机器判据证明它认本栈的声明形态。

三侧：
  1. **SQLModel 式**：`class X(Base, table=True)` 才是表；**继承字段要合并**（`UserBase` 的 4 列也是该表的列）；
  2. **DTO 不算表**：`class UserCreate(UserBase)` / `class Message(SQLModel)` 无 `table=True` ⇒ 不入 `items`；
  3. **SQLAlchemy 式仍要工作**（回归：不能为了新形态把旧的弄坏）。

变异 M19：把文件闸门退回「只认 `__tablename__` + `Column(`」⇒ 第 1 侧红。
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


def run(root: Path) -> dict:
    out = root / "out.json"
    p = subprocess.run([sys.executable, str(ADAPTER), "--root", str(root),
                        "--app", "backend", "--out", str(out)],
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
