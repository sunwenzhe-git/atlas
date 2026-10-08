#!/usr/bin/env python3
"""`adapters/routes.py` 的「喂坏输入必红」判据（`3509 §B118`，2026-09-28）。

**为什么要它**：`§B118` 的只读探针发现 —— 适配器对真实项目产出 **0 条**，而
`structure↔代码` 那个平面正等着接线 ⇒ 「适配器认不认本栈」必须先有机器判据，
否则接线就是把缺口伪装成配门。

三侧：
  1. **文件式路由**（TanStack/Next 同族）：`routes/` 下文件即路由，`index` → 父路径、
     `$x` → `:x`、`.` 是段分隔、`_`/`__` 前缀段不成路由、`routeTree.gen` 跳过；
  2. **空产出**：目录里只有 layout/生成物 ⇒ `items` 为空（接线前置判据的负例）；
  3. **去重**：同一 `path` + 同一源文件只留一份。

变异 M18：摘掉 `collect_file_based_routes` 的调用 ⇒ 第 1 侧红。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PKG_ROOT / "adapters" / "routes.py"

PROFILE = """product: 夹具
apps:
  - name: frontend
    path: frontend
    kind: frontend
    role: landing
    stack: 夹具
"""

FILES = {
    "frontend/src/routes/__root.tsx": "// 根：不成路由\n",
    "frontend/src/routes/_layout.tsx": "// 路径无关布局\n",
    "frontend/src/routes/index.tsx": "// 首页\n",
    "frontend/src/routes/login.tsx": "// 登录\n",
    "frontend/src/routes/_layout/config.tsx": "// 配置\n",
    "frontend/src/routes/_layout/projects.$id.tsx": "// 项目详情\n",
    "frontend/src/routeTree.gen.ts": "// 生成物，必须跳过\n",
}


def mk(root: Path, files: dict | None = None) -> None:
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(PROFILE, encoding="utf-8")
    for rel, body in (files if files is not None else FILES).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def run(root: Path) -> dict:
    out = root / "out.json"
    p = subprocess.run([sys.executable, str(ADAPTER), "--root", str(root), "--out", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_file_based_routes_are_recognised() -> None:
    """文件式路由：`index`→父路径、`$x`→`:x`、`.`=段分隔、`_`/`__` 不成路由、生成物跳过。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        items = run(root)["items"]
        paths = sorted(i["path"] for i in items)
        assert paths == ["/", "/config", "/login", "/projects/:id"], paths
        dyn = next(i for i in items if i["path"] == "/projects/:id")
        assert dyn["params"] == ["id"], dyn
        assert not any("_layout" in i["path"] or "__root" in i["path"] for i in items), paths
        assert not any("routeTree" in i["source_file"] for i in items), items


def test_empty_output_when_only_layouts() -> None:
    """接线前置的负例：目录里只有 layout / 生成物 ⇒ 产出为空（这种项目**不得接线**）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"frontend/src/routes/__root.tsx": "// 根\n",
                  "frontend/src/routes/_layout.tsx": "// 布局\n",
                  "frontend/src/routeTree.gen.ts": "// 生成物\n"})
        assert run(root)["items"] == []


def test_duplicate_path_and_source_collapsed() -> None:
    """同一 `path` + 同一源文件只留一份（三种识别方式可能对同一文件各命一次）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        items = run(root)["items"]
        keys = [(i["path"], i["source_file"]) for i in items]
        assert len(keys) == len(set(keys)), keys
