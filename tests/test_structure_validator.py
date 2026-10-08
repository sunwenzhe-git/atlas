#!/usr/bin/env python3
"""`validators/validate_structure.py` 的「喂坏输入必红」判据（`3509 §119`，批 6 第 8 项配套）。

**为什么单独一个文件**：`shared/gates.md` 的取证等级盘点发现 —— 其余四个校验器都有
「坏输入 ⇒ FAIL」的用例，而 **`validate_structure` 一条都没有**（全仓测试文件里零提及）
⇒ 它的「会咬」从来没有证据。本文件补上，并把该门升为 `出厂级（本轮实测）`。

六侧坏输入（每侧对应一个真判据，不是形态摆设）：
  1. 缺 `_meta.json`；
  2. `domains[]` 的 id 非法 / 重复；
  3. `current/<域>/` 缺 `apis.md`（类别覆盖）；
  4. `tour.md` / `domains/*.md` 的 `paths:` 写成**标量**（不是块列表 ⇒ 不会被注入）；
  5. 表格里的「来源文件」指向**不存在**的路径；
  6. `directory-map.md` 的**列头**不符契约。

变异证明：M14 把「类别覆盖 · 域级 apis/data-models」判据改成恒 True ⇒ 第 3 侧红；
M26 把 routes 语义列判据改成恒不告警 ⇒ `test_structure_routes_empty_semantic_columns_warn` 红（`§B121`，WARN 通道）。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("validate_structure_under_test",
                                                  PKG_ROOT / "validators" / "validate_structure.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vst = _load()

META = {
    "product": "夹具产品",
    "apps": [{"name": "web", "path": "web"}],
    "domains": [{"id": "demo", "globs": ["web/**"]}],
    "categories": {"A": "skipped", "H": "covered"},
}
TOUR = """---
paths:
  - '**'
---

# 夹具结构速查

| 域 | 一句话 |
|---|---|
| demo | 夹具域 |
"""
DOMAIN_DOC = """---
paths:
  - 'web/**'
---

# demo 域

夹具域说明。
"""
DIRECTORY_MAP = """# 目录与模块地图

| 路径 | 类型 | 职责（一句话） | 域 | 备注 |
|---|---|---|---|---|
| web | 前端 | 夹具 | demo | |
"""
ROUTES = """# 路由与页面

| 页面/路由 | 域 | 用途 | 关键交互 | 实现状态 | 来源文件 |
|---|---|---|---|---|---|
| / | demo | 首页 | 无 | 未开始 | web |
"""
ROUTES_GAP = """# 路由与页面

| 页面/路由 | 域 | 用途 | 关键交互 | 实现状态 | 来源文件 |
|---|---|---|---|---|---|
| /login | — |  |  | — | web |
"""
APIS_POINTER = """# demo 接口

真相源：夹具自带接口描述；访问方式：夹具。
"""
DATA_MODELS = """# demo 数据模型

| 表/模型 | 字段 | 类型 | 约束/默认 | 关系 | 枚举 |
|---|---|---|---|---|---|
| 夹具表 | id | int | 主键 | 无 | 无 |
"""


def mk(root: Path, *, meta: dict | None = None, tour: str = TOUR,
       apis: str | None = APIS_POINTER, directory_map: str = DIRECTORY_MAP,
       routes: str = ROUTES) -> None:
    spec = root / ".trellis" / "spec" / "structure"
    (spec / "domains").mkdir(parents=True, exist_ok=True)
    (spec / "global").mkdir(parents=True, exist_ok=True)
    (spec / "current" / "demo").mkdir(parents=True, exist_ok=True)
    (root / "web").mkdir(exist_ok=True)                      # apps[].path 存在 ⇒ 非绿地
    (spec / "_meta.json").write_text(json.dumps(meta or META, ensure_ascii=False), encoding="utf-8")
    (spec / "tour.md").write_text(tour, encoding="utf-8")
    (spec / "domains" / "demo.md").write_text(DOMAIN_DOC, encoding="utf-8")
    (spec / "global" / "directory-map.md").write_text(directory_map, encoding="utf-8")
    (spec / "global" / "routes.md").write_text(routes, encoding="utf-8")
    if apis is not None:
        (spec / "current" / "demo" / "apis.md").write_text(apis, encoding="utf-8")
    (spec / "current" / "demo" / "data-models.md").write_text(DATA_MODELS, encoding="utf-8")


def _res(root: Path):
    # 注意：本校验器的 Result 用 `rows`（`ok: bool`），其余四个用 `checks`（`level: str`）
    return {c["check"]: c for c in vst.validate(root).rows}


def _tmp():
    import tempfile
    return tempfile.TemporaryDirectory()


def test_structure_baseline_passes() -> None:
    """正例必须先绿（否则后面各侧的红说明不了任何事）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root)
        res = _res(root)
        bad = [k for k, c in res.items() if c.get("ok") is False]
        assert not bad, {k: res[k]["detail"] for k in bad}


def test_structure_missing_meta_fails() -> None:
    with _tmp() as td:
        root = Path(td)
        mk(root)
        (root / ".trellis" / "spec" / "structure" / "_meta.json").unlink()
        res = _res(root)
        assert res["域模型"]["ok"] is False and "_meta.json" in res["域模型"]["detail"], res["域模型"]


def test_structure_bad_domain_ids_fail() -> None:
    with _tmp() as td:
        root = Path(td)
        meta = dict(META, domains=[{"id": "Demo_Bad", "globs": ["web/**"]},
                                   {"id": "demo", "globs": ["web/**"]}])
        mk(root, meta=meta)
        res = _res(root)
        assert res["域模型 · domains[]"]["ok"] is False, res["域模型 · domains[]"]


def test_structure_missing_role_file_fails() -> None:
    """类别覆盖：`current/<域>/` 缺 `apis.md` ⇒ FAIL。

    变异 M14：把该判据改成恒 True ⇒ 本用例红。
    """
    with _tmp() as td:
        root = Path(td)
        mk(root, apis=None)
        res = _res(root)
        assert res["类别覆盖 · 域级 apis/data-models"]["ok"] is False, \
            res["类别覆盖 · 域级 apis/data-models"]
        assert "apis.md" in res["类别覆盖 · 域级 apis/data-models"]["detail"]


def test_structure_scalar_paths_fail() -> None:
    """`paths:` 写成标量 ⇒ 不会被注入 ⇒ FAIL（契约要求块列表）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root, tour=TOUR.replace("paths:\n  - '**'", "paths: '**'"))
        res = _res(root)
        assert res["注入结构 paths 块列表"]["ok"] is False, res["注入结构 paths 块列表"]


def test_structure_unresolvable_source_file_fails() -> None:
    """表格里的「来源文件」指向不存在的路径 ⇒ FAIL（来源可定位）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root, routes=ROUTES.replace("| / | demo | 首页 | 无 | 未开始 | web |",
                                       "| / | demo | 首页 | 无 | 未开始 | `web/src/ghost.tsx` |"))
        res = _res(root)
        assert res["来源可定位"]["ok"] is False, res["来源可定位"]
        assert "ghost" in res["来源可定位"]["detail"]


def test_structure_wrong_table_columns_fail() -> None:
    """`directory-map.md` 列头与契约不一致 ⇒ FAIL（表格列）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root, directory_map=DIRECTORY_MAP.replace(
            "| 路径 | 类型 | 职责（一句话） | 域 | 备注 |", "| 路径 | 类型 | 说明 |"))
        res = _res(root)
        assert res["表格列"]["ok"] is False, res["表格列"]

def test_structure_routes_empty_semantic_columns_warn() -> None:
    """`§B121` 判据：语义列（用途/关键交互/实现状态）留空的行 ⇒ WARN 指名；WARN 不置红。"""
    with _tmp() as td:
        root = Path(td)
        mk(root, routes=ROUTES_GAP)
        v = vst.validate(root)
        assert v.ok, "WARN 不得置红"
        hits = [w for w in v.warns if w["check"] == "routes 语义列"]
        assert hits and "/login" in hits[0]["detail"] and "用途" in hits[0]["detail"], v.warns


def test_structure_routes_filled_semantic_columns_no_warn() -> None:
    """语义列补齐（或「—」占位）⇒ 无 WARN；占位与留空必须分得开。"""
    with _tmp() as td:
        root = Path(td)
        mk(root)  # 基线 ROUTES 语义列齐全
        v = vst.validate(root)
        assert not [w for w in v.warns if w["check"] == "routes 语义列"], v.warns

