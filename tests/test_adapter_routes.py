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

**声明式路由表**（2026-10-15 补，M52）：真实接入项目的路由表是 `src/entry/main/routes.tsx`
里的 `routesList` / `otherRouters` / `adminSubRoutes`——父目录不叫 `router`、后缀 `.tsx`、
绑定名不叫 `routes`。旧判据三闸叠加 ⇒ **0 条**（实测），故第 4/5 侧钉住新判据与两条误报防线：

  4. **声明式路由表**：非 `router/` 目录的 `.tsx` 里多张含 `rout` 的数组绑定（含反引号路径、
     `element: <X />`、无字面量 path 的常量条目跳过）；
  5. **注释行不是路由**：被 `//` 注掉的条目不得进 `items`（同理 `'https://x'` 里的 `//`
     不是注释，不得把数组砍断）。

变异 M52：把 `collect_js_routes` 的候选闸退回「父目录须为 `router`」⇒ 第 4 侧红。
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


ROUTER_TSX = """\
import { lazy } from 'react'
const Market = lazy(() => import('@/modules/market'))
const App = lazy(() => import('@/modules/app'))

interface RouteConfig {
  path: string
  element: unknown
}

export const routesList: RouteConfig[] = [
  { path: `/market`, titleKey: 'main.routes.appMarket', element: <Market /> },
  { path: '/app', titleKey: 'main.routes.app', element: <App /> },
]

export const otherRouters: RouteConfig[] = [
  { path: '/login', element: <Login /> },
  { path: IFRAME_ACCESS_DENIED_PATH, element: <Unauthorized /> },
]

// 管理模块的子菜单路由
export const adminSubRoutes: RouteConfig[] = [
  // { path: '/role-management', element: <RoleManagement /> },
  { path: '/api-key', titleKey: 'main.routes.apiKey', element: <ApiKey /> },
]
"""


def test_declarative_route_table_in_tsx() -> None:
    """声明式路由表：非 `router/` 目录、`.tsx` 后缀、多张含 `rout` 的数组绑定都要收。

    反引号路径要收；`path: SOME_CONST` 静态不可求值 ⇒ 跳过（宁缺，不产假路径）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"frontend/src/entry/main/routes.tsx": ROUTER_TSX})
        items = run(root)["items"]
        assert sorted(i["path"] for i in items) == ["/api-key", "/app", "/login", "/market"], items
        market = next(i for i in items if i["path"] == "/market")
        assert market["component"] == "Market", market
        assert market["name"] == "main.routes.appMarket", market
        assert market["source_file"] == "frontend/src/entry/main/routes.tsx:11", market
        # 常量 path 的条目静默跳过（保留其邻居，不是整表丢弃）
        assert not any("IFRAME" in str(i) for i in items), items


def test_commented_out_route_is_not_a_route() -> None:
    """被注掉的条目不得进 `items`；`'https://x'` 里的 `//` 不得把数组砍断。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"frontend/src/router/index.ts": """\
const routes: RouteConfig[] = [
  { path: 'https://docs.example.com/help', element: Docs },
  // { path: '/role-management', element: <RoleManagement /> },
  /* { path: '/upload-demo', element: <UploadDemo /> }, */
  { path: '/alive', element: <Alive /> },
]
"""})
        items = run(root)["items"]
        assert sorted(i["path"] for i in items) == [
            "/alive", "https://docs.example.com/help"], items
        assert not any("role-management" in i["path"] or "upload-demo" in i["path"] for i in items)

