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



# ---- D82/D83（2026-10-16，issue #15；RFC-20261016-01）----
#
# 两个病根：① 候选判据是**文件名**（含 `rout` 或父目录 `router`）⇒ 模块入口表（`index.*`）
# 被静默排除；② JSX `<Route>` 形态根本没有解析器。修后还必须做挂载前缀合成，否则模块相对
# 路径会撞行键（`(应用, 页面/路由)`）被 `dedup_by_row_key` 折叠成**假事实**。

_ENTRY = """\
import { lazy } from 'react'
const ModA = lazy(() => import('@/modules/mod-a'))
const ModB = lazy(() => import('@/modules/mod-b'))
export const routesList = [
  { path: '/a', element: <ModA /> },
  { path: '/b', element: <ModB /> },
]
"""

_MOD_TMPL = """\
import {{ HashRouter, Route, Routes }} from 'react-router-dom'
export default () => (
  <HashRouter{_BASE}>
    <Routes>
      <Route path="/" element={{<Home />}} />
      <Route path="/create" element={{<Create />}} />
      <Route path="/detail/:id" element={{<Detail />}} />
    </Routes>
  </HashRouter>
)
"""


def test_module_entry_table_is_scanned_and_prefixed() -> None:
    """D82：模块入口表（文件名 `index.*`，不含 `rout`）必须被扫到；D83：其模块相对路径必须
    用**挂载前缀**合成（站点表的 `(path → 懒加载模块)` 即挂载关系）。

    变异：候选闸还原成「文件名含 `rout`」⇒ 本用例红（只剩站点级 2 条）（M-R3）；
          前缀合成退化为直接产出模块相对路径 ⇒ `/create` 撞键断言红（M-R4）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {
            "frontend/src/entry/main/routes.tsx": _ENTRY,
            "frontend/src/modules/mod-a/index.tsx": _MOD_TMPL.format(_BASE=' basename="/a"'),
            "frontend/src/modules/mod-b/index.tsx": _MOD_TMPL.format(_BASE=' basename="/b"'),
        })
        out = run(root)
        paths = [i["path"] for i in out["items"]]
        # 站点表的 `/a` 与模块自己的 `path="/"`（合成后 `/a`）是**两条合法事实**
        # （不同 source_file）；同一目标文件内的重复行键由渲染层 `dedup_by_row_key` 折叠。
        assert sorted(set(paths)) == ["/a", "/a/create", "/a/detail/:id",
                                      "/b", "/b/create", "/b/detail/:id"], sorted(set(paths))
        # 绝不得有**裸模块相对路径**泄进全站表（那会与另一个模块的同名路径撞键）
        assert "/create" not in paths and "/detail/:id" not in paths, paths
        cov = out["route_coverage"]
        assert (cov["declared"], cov["site_level"], cov["mounted"]) == (3, 1, 2), cov
        assert cov["skipped"] == [], cov
        assert any(i["params"] == ["id"] for i in out["items"] if i["path"] == "/a/detail/:id")


def test_jsx_route_form_with_nesting() -> None:
    """D82：JSX `<Route>` 形态（含**同文件嵌套**）必须被解析；子路径 = 父路径 + 本地路径。

    变异：让 JSX 分支不解析 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"frontend/src/entry/main/routes.tsx": """\
import { Route, Routes } from 'react-router-dom'
export const AppRoutes = () => (
  <Routes>
    <Route path="user" element={<UserLayout />}>
      <Route path="create" element={<UserCreate />} />
      <Route path="detail/:id" element={<UserDetail />} />
    </Route>
    <Route path="/settings" element={<Settings />} />
    <Route path={ROUTES_DYNAMIC} element={<Dynamic />} />
  </Routes>
)
"""})
        out = run(root)
        paths = sorted(i["path"] for i in out["items"])
        assert paths == ["/settings", "/user", "/user/create", "/user/detail/:id"], paths
        cov = out["route_coverage"]
        assert (cov["declared"], cov["site_level"]) == (1, 1), cov


def test_unmounted_module_table_is_dropped_and_counted() -> None:
    """D83：模块级表但**挂载前缀求不出**（无入边 + `basename` 非字面量）⇒ 条目全部丢弃并计数
    出声——绝不产出模块相对路径（那会撞行键）。

    变异：让未解析文件照旧产出相对路径 ⇒ 本用例红（M-R5）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"frontend/src/modules/orphan/index.tsx": """\
import { HashRouter, Route, Routes } from 'react-router-dom'
const basename = getBasename('orphan')
export default () => (
  <HashRouter basename={basename}>
    <Routes><Route path="/create" element={<Create />} /></Routes>
  </HashRouter>
)
"""})
        out = run(root)
        assert out["items"] == [], out["items"]
        cov = out["route_coverage"]
        assert cov["declared"] == 1 and cov["skipped_items"] == 1, cov
        assert cov["skipped"][0]["file"].endswith("modules/orphan/index.tsx"), cov
        assert "基名不可求值" in cov["skipped"][0]["reason"], cov


def test_multi_mount_prefix_is_unresolved_and_counted() -> None:
    """D83 条 4（评审 F2）：同一模块被站点表**两条条目**引用 ⇒ 前缀取值不唯一 ⇒ 未解析 + 计数
    （宁缺不产假路径：任取一条都可能与公开 URL 不符）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {
            "frontend/src/entry/main/routes.tsx": """\
import { lazy } from 'react'
const ModA = lazy(() => import('@/modules/mod-a'))
export const routesList = [
  { path: '/a', element: <ModA /> },
  { path: '/alias', element: <ModA /> },
]
""",
            "frontend/src/modules/mod-a/index.tsx": """\
import { HashRouter, Route, Routes } from 'react-router-dom'
export default () => (
  <HashRouter basename="/a"><Routes><Route path="/create" element={<C />} /></Routes></HashRouter>
)
""",
        })
        out = run(root)
        assert sorted(i["path"] for i in out["items"]) == ["/a", "/alias"], out["items"]
        cov = out["route_coverage"]
        assert cov["mounted"] == 0 and len(cov["skipped"]) == 1, cov
        assert "不唯一" in cov["skipped"][0]["reason"] and "/a" in cov["skipped"][0]["reason"], cov


def test_alias_specifier_resolution_narrows_by_table_declaration() -> None:
    """D83 条 2（评审 F1）：别名标识符的解析**不是**拿尾段与 relpath 字面相等（那恒不命中），
    也不只看目录命中（同目录下多个文件会多命中）——而是「目录命中 + 该文件也声明表」过滤。

    变异：退回「尾段唯一相等」的字面实现 ⇒ 别名解析失效 ⇒ 该模块退化为站点级 ⇒
    `/create` 而非 `/m1/create` ⇒ 本用例红（M-R6）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {
            "frontend/src/entry/main/routes.tsx": """\
import { lazy } from 'react'
const ModOne = lazy(() => import('@/modules/mod-one'))
export const routesList = [{ path: '/m1', element: <ModOne /> }]
""",
            # 同目录下**两个**文件：只有一个声明路由表 ⇒ 过滤后唯一（否则多命中 ⇒ 未解析）
            "frontend/src/modules/mod-one/index.tsx": _MOD_TMPL.format(_BASE=""),
            "frontend/src/modules/mod-one/helper.tsx": "export const x = 1\n",
        })
        out = run(root)
        paths = sorted(set(i["path"] for i in out["items"]))
        assert paths == ["/m1", "/m1/create", "/m1/detail/:id"], paths
        assert out["route_coverage"]["mounted"] == 1, out["route_coverage"]


def test_sub_router_without_basename_and_without_mount_is_dropped() -> None:
    """D83 条 5（2026-10-16 变异取证补的钉）：子路由（本文件挂载了自己的 router）**既无入边又
    无 basename** 时必须判「未解析 + 计数」，不得因为「没有 basename 声明」就误判成站点级 ——
    那样会把模块相对路径静默泄成全站路径（评审 F2 的同族假事实）。

    变异：把判据退回「只看有没有 basename 声明」⇒ 本用例红（M-R7）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"frontend/src/modules/orphan/index.tsx": """\
import { HashRouter, Route, Routes } from 'react-router-dom'
export default () => (
  <HashRouter><Routes><Route path="/create" element={<Create />} /></Routes></HashRouter>
)
"""})
        out = run(root)
        assert out["items"] == [], out["items"]
        cov = out["route_coverage"]
        assert (cov["declared"], cov["site_level"], cov["skipped_items"]) == (1, 0, 1), cov
        assert "无挂载方" in cov["skipped"][0]["reason"], cov
