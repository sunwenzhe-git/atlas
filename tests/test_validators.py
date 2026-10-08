#!/usr/bin/env python3
"""atlas 三个校验器 + 原型静态服务器的回归测试。

    python3 atlas/tests/test_validators.py     # 脚本式
    pytest atlas/tests/test_validators.py      # pytest 式
"""
from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vt = load("validate_testids", "validators/validate_testids.py")
ve = load("validate_e2e_index", "validators/validate_e2e_index.py")
gn = load("gen_e2e_scripts", "scripts/gen_e2e_scripts.py")
vpr = load("validate_prd", "validators/validate_prd.py")
vsp = load("validate_stack_profile", "validators/validate_stack_profile.py")

TOKENS = ":root{--c:#111111}\n"
HOME_HTML = (
    "<!doctype html><html><head><style>:root{--c:#111111}</style></head>"
    '<body><a href="/?state=empty">空态</a>'
    '<button data-testid="home-cta-btn">开始</button>'
    '<h1 data-testid="home-title">首页</h1></body></html>'
)
README = """# 原型站

| 序 | 页 slug | 原型文件 | 原型 URL | 真实路由(模式) | 域 | 页面名称 | 状态 | 来源 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | home | product/prototype/home.html | / | / | — | 首页 | 已建 | PRD §七 | |
"""

CASE_GOOD = """
## E2E-HOME-001 首页加载并可进入空态

```atlas-case
id: E2E-HOME-001
intent: 打开首页后主操作按钮可见且可点击进入空态
pages:
  - home
precondition:
  - 已打开首页
step:
  - click home-cta-btn          # 点击主操作按钮
expected:
  - text home-title 首页        # 页面标题文案为「首页」
testid:
  - home-cta-btn
  - home-title
```
"""

INDEX_GOOD = """
# E2E 索引

| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |
|---|---|---|---|---|---|---|---|---|
| E2E-HOME-001 | home | 首页加载并可进入空态 | smoke | AC-HOME-001 | | red | | [cases/home.md#e2e-home-001](cases/home.md#e2e-home-001) |

## 页面 ↔ 用例

| 页面 | 断言落点用例 | 链路经过用例 |
|---|---|---|
| home | E2E-HOME-001 | |
"""


FM_DOMAIN = "---\ndoc: demo-prd\ndomain: demo\ndomain_name: 演示域\ndomain_code: DEMO\nversion: 1.0\ndate: 2026-09-25\nstatus: final\n---\n\n"
FM_GLOBAL = "---\ndoc: prd\nproduct: demo\nversion: 1.0\ndate: 2026-09-25\nstatus: final\n---\n\n"
def mk_stub(root: Path) -> None:
    """实现期薄桩（契约 §4.1）：`validate_testids` 要求它存在 —— 由生成器产出。"""
    d = root / ".trellis" / "spec" / "conventions"
    d.mkdir(parents=True, exist_ok=True)
    (d / "testid.md").write_text("---\npaths:\n  - '**'\n---\n\n# testid 约定\n", encoding="utf-8")


def mk_prototype(root: Path, home: str = HOME_HTML, readme: str = README) -> None:
    """E1：抽取源 = 前端源码（`data-testid` 按正则扫描，扩展名无关）⇒ 同一份 HTML 写进前端 app。"""
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(
        "product: demo\napps:\n  - name: web\n    path: web\n    kind: frontend\n"
        "    role: landing\n    stack: demo\n", encoding="utf-8")
    d = root / "web" / "src"
    d.mkdir(parents=True, exist_ok=True)
    (d / "home.html").write_text(home, encoding="utf-8")
    mk_stub(root)


def mk_cases(root: Path, case: str = CASE_GOOD) -> None:
    d = root / "product" / "e2e" / "cases"
    d.mkdir(parents=True, exist_ok=True)
    (d / "home.md").write_text(case, encoding="utf-8")


def mk_index(root: Path, text: str = INDEX_GOOD) -> None:
    d = root / "product" / "e2e"
    d.mkdir(parents=True, exist_ok=True)
    (d / "e2e-index.md").write_text(text, encoding="utf-8")


def _persist_warns(case: str) -> bool:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, case)
        mk_index(root)
        res = ve.validate(root)
        return any(c["check"] == "持久化写复断言" and c["level"] == "WARN" for c in res.checks)


def _title_level(case: str = CASE_GOOD, index: str = INDEX_GOOD) -> tuple[str, str]:
    """返回 (该检查的 level, detail)。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, case)
        mk_index(root, index)
        res = ve.validate(root)
        hit = [c for c in res.checks if c["check"] == "索引↔分片标题一致"]
        assert hit, [c["check"] for c in res.checks]
        return hit[0]["level"], hit[0]["detail"]


def _levels(case: str) -> dict[str, str]:
    """跑一遍校验器，返回 {检查项: level}。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, case)
        mk_index(root)
        return {c["check"]: c["level"] for c in ve.validate(root).checks}


def _index_levels(case: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, case)
        mk_index(root)
        res = ve.validate(root)
    return {c["check"]: c["level"] for c in res.checks}


def mk_prd(root: Path, listing: str = "| `AC-HOME-001` | 纯渲染构成，页面初值即终态 |") -> None:
    d = root / "product" / "prd"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prd.md").write_text(FM_GLOBAL + PRD_GLOBAL, encoding="utf-8")
    (d / "demo-prd.md").write_text(FM_DOMAIN + PRD_DEMO.format(ac="AC-HOME-001", rows=listing),
                                   encoding="utf-8")


def _levels_full(case: str, listing: str | None = None) -> dict[str, str]:
    """跑一遍 E2E 索引校验器；`listing` 非 None 时另建一份带结构类清单的域级 PRD。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, case)
        mk_index(root)
        if listing is not None:
            mk_prd(root, listing)
        return {c["check"]: c["level"] for c in ve.validate(root).checks}


PROFILE_BASE = """product: 测试产品
origin: {origin}
apps:
  - name: web
    path: web
    kind: frontend
    role: landing
    stack: 仅展示
adapters:
  routes: null
prototype:
  dir: product/prototype
e2e:
  runner: python-playwright
"""


def mk_profile(root: Path, text: str) -> None:
    d = root / "product"
    d.mkdir(parents=True, exist_ok=True)
    (d / "stack-profile.yaml").write_text(text, encoding="utf-8")
    (root / "web").mkdir(exist_ok=True)   # 让 apps[].path 存在 ⇒ 不引入无关 WARN


def _sp_check(res, name: str) -> dict:
    return [c for c in res.checks if c["check"] == name][0]


PRD_GLOBAL = """# 全局 PRD

范围形态：首建

## 零、待决策登记

| # | 待决策 | 状态 |
|---|---|---|

## 一、产品定位

演示用夹具。

## 二、目标用户与角色

单人。

## 三、核心场景

打开页面。

## 四、产品形态与入口

Web。

## 五、功能架构

| 域 slug | 中文名 | 一句话职责 | 域级文件 |
|---|---|---|---|
| `demo` | 演示域 | 用于夹具 | `product/prd/demo-prd.md` |

## 六、范围与处置 / 功能范围

### 6.1 功能范围

| 功能 / 能力 | 所属域 | 一句话说明 |
|---|---|---|
| 演示功能 | 演示域 | 用于夹具 |

## 七、页面结构全景

| 路由 | 用途 | 所属域 |
|---|---|---|
| `/demo` | 演示 | 演示域 |

## 八、非功能需求

无。

## 九、术语表

| 术语 | 定义 |
|---|---|
| 演示 | demo |

## 十、风险与依赖

无。

## 十一、修订记录

| 版本 | 日期 | 修订人 | 变更说明 |
|---|---|---|---|
| 1.0 | 2026-09-25 | 测试夹具 | 初始 |
"""


PRD_DEMO = """# demo 域 PRD

## 二、功能清单

| 功能编号 | 名称 | 说明 | 优先级 | 需求类别 |
|---|---|---|---|---|
| `FN-DEMO-001` | 演示功能 | 用于夹具 | P0 | 新增 |

## 四、业务规则（Rule Set）

| 规则 ID | 规则内容 | 所属功能 | 触发条件 | 优先级 | 影响范围 |
|---|---|---|---|---|---|
| `DEMO-R-001` | 演示规则一 | `FN-DEMO-001` | 打开页面 | P0 | 演示域 |
| `DEMO-R-002` | 演示规则二 | `FN-DEMO-001` | 保存 | P1 | 演示域 |

## 五、验收标准

| AC ID | 场景（Given / When / Then） | 回指规则 |
|---|---|---|
| `{ac}` | Given 已登录，When 打开页面，Then 按 mock 数据渲染 | `DEMO-R-001` |
| `AC-HOME-999` | Given 已登录，When 点击按钮，Then 出现新行 | `DEMO-R-002` |

#### 结构类 AC 清单

> 契约（PRD 环契约 §五「验收标准」）。

| AC ID | 为什么只能在初始态观测 |
|---|---|
{rows}

## 六、Assumptions & Defaults

## 七、变更记录
"""


def mk_prd_raw(root: Path, global_text: str, domain_text: str | None = None) -> None:
    d = root / "product" / "prd"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prd.md").write_text(global_text, encoding="utf-8")
    if domain_text is not None:
        (d / "demo-prd.md").write_text(domain_text, encoding="utf-8")


def _p4(root: Path) -> dict:
    return {c["check"]: c for c in vpr.validate(root).checks}["参数4 追溯完整"]


def _six_as_disposal(text: str) -> str:
    """把夹具的「功能范围表」改成「处置表」（供变更形态用）。"""
    text = text.replace("| 功能 / 能力 | 所属域 | 一句话说明 |",
                        "| 功能 / 能力 | 所属域 | 处置 | 理由 |")
    return text.replace("| 演示功能 | 演示域 | 用于夹具 |",
                        "| 演示功能 | 演示域 | 保留 | 夹具 |")


ADOPT_FM_DOMAIN = (
    "---\ndoc: prd-domain\ndomain: \"{slug}\"\ndomain_name: \"{name}\"\n"
    "domain_code: \"{code}\"\nversion: 0.1.0\ndate: 2026-09-27\nstatus: draft\n"
    "depends_on: []\n---\n\n"
)


# 「开户最小集」四节：一 域概述 / 二 功能清单 / 四 Rule Set / 五 验收标准。
# 三 功能详细说明（六件套）与 六 Assumptions **整节不出现**（契约 §4）。
ADOPT_PRD_DOMAIN = """# {name} — 域级 PRD

> 本文件是**应然**文档，不挂实现状态。
> 对应 structure 模块与页面见 `product/prd/README.md` 的追溯总表。

- **In Scope**：夹具用途。
- **Out of Scope**：无。
- **依赖域**：无。

---

## 一、域概述

| 项 | 内容 |
|---|---|
| 定位 | 夹具 |
| 边界 | 夹具 |
| 上游 | 无 |
| 下游 | 无 |

## 二、功能清单

| 功能编号 | 名称 | 说明 | 优先级 | 需求类别 |
|---|---|---|---|---|
| `FN-{code}-001` | 夹具功能 | 用于夹具 | P0 | 功能性 |

## 四、业务规则（Rule Set）

| 规则 ID | 规则内容 | 所属功能 | 触发条件 | 优先级 | 影响范围 |
|---|---|---|---|---|---|
| `{code}-R-001` | 夹具规则，可判定 | `FN-{code}-001` | 打开页面 | P0 | 全部 |

## 五、验收标准

| AC ID | 场景（Given / When / Then） | 回指规则 |
|---|---|---|
| `AC-{code}-001` | Given 已登录，When 打开页面，Then 1 秒内渲染出 1 行 | {ref} |
| `AC-{code}-002` | Given 已登录，When 打开页面，Then 首屏存在 1 个容器 | {ref} |

#### 结构类 AC 清单

| AC ID | 为什么只能在初始态观测 |
|---|---|
| `AC-{code}-002` | 骨架属性，只能初始态观测 |
"""


ADOPT_PRD_GLOBAL = """# 全局 PRD

范围形态：变更
覆盖度：增量起步
基线：`.trellis/spec/structure/`

## 五、功能架构

| 域 slug | 中文名 | 一句话职责 | 域级文件 |
|---|---|---|---|
{rows}

## 六、范围与处置 / 功能范围

### 6.2 功能处置

| 功能 / 能力 | 所属域 | 处置 | 理由 |
|---|---|---|---|
| 夹具功能 | 夹具 | 未覆盖（沿用实然） | 开户轮未审议 |

## 七、页面结构全景

| 路由 | 用途 | 所属域 |
|---|---|---|
| `/demo` | 夹具 | `demo1` |
"""


def mk_adopt_opening(root: Path, *, drop_domain: bool = False, blank_ref: bool = False,
                     legacy_rel_path: bool = False) -> None:
    """按契约 §4「开户最小集」铺一个 adopt 开户现场。

    drop_domain  → 少铺最后一份域级 PRD；
    blank_ref    → AC 的「回指规则」列清空；
    legacy_rel_path → 域级引用回退成模板旧写法 ../README.md。
    """
    d = root / "product" / "prd"
    d.mkdir(parents=True, exist_ok=True)
    # 夹具幂等：先清掉上一轮铺的域级文件 —— 否则「少铺一份」的变异会因为旧文件还在而假绿
    # （实测踩到：同名临时目录下三侧变异连铺，drop_domain 那侧一动不动）
    for old in d.glob("*-prd.md"):
        old.unlink()
    (d / "README.md").write_text("# 追溯总表\n\n夹具。\n", encoding="utf-8")
    slugs = ("demo1", "demo2")
    rows = "\n".join(f"| `{s}` | 夹具 | 夹具 | `product/prd/{s}-prd.md` |" for s in slugs)
    (d / "prd.md").write_text(FM_GLOBAL + ADOPT_PRD_GLOBAL.replace("{rows}", rows), encoding="utf-8")
    for i, s in enumerate(slugs):
        if drop_domain and i == len(slugs) - 1:
            continue
        code = s.upper()
        text = ADOPT_FM_DOMAIN.format(slug=s, name=f"夹具{code}", code=code)
        text += ADOPT_PRD_DOMAIN.format(name=f"夹具{code}", code=code,
                                        ref="" if blank_ref else f"`{code}-R-001`")
        if legacy_rel_path:
            text = text.replace("`product/prd/README.md`", "`../README.md`")
        (d / f"{s}-prd.md").write_text(text, encoding="utf-8")


def _p3(root: Path) -> dict:
    return {c["check"]: c for c in vpr.validate(root).checks}["参数3 链接可解析"]


def test_testids_gate_na() -> None:
    with tempfile.TemporaryDirectory() as td:
        assert vt.validate(Path(td)).status == "N/A"


def test_testids_pass() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root)
        assert vt.validate(root).status == "PASS"


def test_testids_mismatch_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("  - home-title\n", "  - home-missing\n"))
        assert vt.validate(root).status == "FAIL"


def test_testids_derived_from_step_and_expected() -> None:
    """`3509 §B40/§B64`：用例侧 testid 集合 = `testid:` 声明 **∪** step/expected 派生。

    旧行为：集合只从 `testid:` 块抽取 ⇒ 「断言了某 testid 却没列进去」直接 FAIL（要人肉补），
    且双向门对该 testid 的判定会落到**别的**用例头上（定位错人）。
    新行为：派生一半自动计入 ⇒ 漏列不再报错（这是**同步面削减**，不是放宽：原型侧孤儿仍 FAIL）。
    变异证明：把 `shard_testids` 退回「只读 `testid:` 块」⇒ 本用例变红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("  - home-title\n", ""))   # 只从清单里删，expected 仍在用
        res = vt.validate(root)
        assert res.status != "FAIL", [c for c in res.checks if c["level"] == "FAIL"]
        assert vt.case_testid_usage(root / "product" / "e2e" / "cases" / "home.md")[0][2] == {"home-cta-btn"}


def test_testids_orphan_still_fails_and_names_usages() -> None:
    """派生不削弱守备：原型上有、用例侧（声明 ∪ 派生）完全没有的 testid，仍 **FAIL**。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root, home=HOME_HTML.replace(
            '<h1 data-testid="home-title">首页</h1>',
            '<h1 data-testid="home-title">首页</h1><i data-testid="home-extra-btn"></i>'))
        mk_cases(root)
        res = vt.validate(root)
        assert res.status == "FAIL"
        detail = [c["detail"] for c in res.checks if c["check"] == "分页双向集合相等"][0]
        assert "home-extra-btn" in detail, detail


def test_testids_cross_page_reference_is_owned_by_target_page() -> None:
    """跨页断言是常态 ⇒ 按 **testid 归属页**归集（E1：页候选 = 分片名 ∪ 前端前缀）。

    旧口径按分片文件名归集 ⇒ `home.md` 里断言 `projects-title` 会被报成「home 缺失」。
    变异证明：把 `shard_testids` 改回「按文件名归集」⇒ 本用例红（缺失列表里 projects-title
    落到 home 页）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        (root / "web" / "src" / "projects.html").write_text(
            '<html><body><b data-testid="projects-tab-btn"></b></body></html>', encoding="utf-8")
        mk_cases(root, CASE_GOOD.replace("  - text home-title 首页        # 页面标题文案为「首页」",
                                         "  - text projects-title 工作台  # 跳到工作台后标题为「工作台」"))
        res = vt.validate(root)
        detail = [c["detail"] for c in res.checks if c["check"] == "分页双向集合相等"][0]
        assert '"page": "projects"' in detail, detail
        assert "projects-title" in detail and "缺失" in detail, detail
        assert res.status == "FAIL", detail


# ---- E1 页面表 `实现状态`（`3509 §B106`）----

def _with_page_table(state: str, slug: str = "home") -> str:
    """把 `INDEX_GOOD` 插一张页面表（含 `实现状态` 列）。"""
    return INDEX_GOOD.replace(
        "## 页面 ↔ 用例",
        "## 页面表（页 ↔ 路由）\n\n"
        "| 页面 | 路由 | 域 | 实现状态 |\n|---|---|---|---|\n"
        f"| {slug} | / | demo | {state} |\n\n## 页面 ↔ 用例",
    )


def test_testids_in_progress_page_gap_is_warn_not_fail() -> None:
    """`3509 §B106`：页 `实现状态 = 实现中` ⇒ 双向缺口降 WARN 并附清单（用例先行窗口内不得长红）。

    变异证明：把严重性判据退回「一律 FAIL」⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("  - home-title\n", "  - home-missing\n"))
        mk_index(root, _with_page_table("实现中"))
        res = vt.validate(root)
        row = [c for c in res.checks if c["check"] == "分页双向集合相等"][0]
        assert row["level"] == "WARN", row
        assert "home-missing" in row["detail"] and "实现中" in row["detail"], row
        assert res.status != "FAIL", [c for c in res.checks if c["level"] == "FAIL"]


def test_testids_implemented_state_keeps_fail() -> None:
    """同一缺口，`已实现` ⇒ 仍 FAIL：状态列不是放水阀（守备强度不因新增列而降低）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("  - home-title\n", "  - home-missing\n"))
        mk_index(root, _with_page_table("已实现"))
        assert vt.validate(root).status == "FAIL"


def test_testids_state_vocab_and_missing_column_fail_closed() -> None:
    """词表外取值 ⇒ FAIL（防拼写把严判静默降为 WARN）；**缺状态列 ⇒ 按 `已实现` 严判**。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("  - home-title\n", "  - home-missing\n"))
        mk_index(root, _with_page_table("进行中"))  # 词表外
        res = vt.validate(root)
        assert res.status == "FAIL"
        assert any(c["check"] == "页面表实现状态词表" and c["level"] == "FAIL" for c in res.checks)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("  - home-title\n", "  - home-missing\n"))
        mk_index(root, INDEX_GOOD.replace(
            "## 页面 ↔ 用例",
            "## 页面表\n\n| 页面 | 路由 | 域 |\n|---|---|---|\n| home | / | demo |\n\n## 页面 ↔ 用例"))
        assert vt.validate(root).status == "FAIL"  # 缺列 ⇒ 严判


def test_testids_page_table_is_slug_authority() -> None:
    """页 slug 词表以页面表为准：表外前缀（模板组件 `error-component`）归「未归属」WARN，
    不得被当成「有页但无分片」的待补页（旧口径从 testid 首段猜页 slug，`3509 §B106`）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        (root / "web" / "src" / "err.html").write_text(
            '<html><body><b data-testid="error-component"></b></body></html>', encoding="utf-8")
        mk_cases(root)
        mk_index(root, _with_page_table("已实现"))
        res = vt.validate(root)
        owner = [c for c in res.checks if c["check"] == "前端 testid 归属"][0]
        no_shard = [c for c in res.checks if c["check"] == "前端有页但无分片"][0]
        assert "error-component" in owner["detail"], owner
        assert no_shard["level"] == "PASS" and "error" not in no_shard["detail"], no_shard


# ---- 模板字面量 testid（2026-10-04 互锁修复）----

SHELL_TSX = """import { pageSlug } from "./lib/page-slug"

const NAV_ITEMS = [
  { key: "projects", label: "项目" },
  { key: "config", label: "配置" },
]

export function Shell({ pathname }: { pathname: string }) {
  const slug = pageSlug(pathname)
  return (
    <main data-testid={`${slug}-page`}>
      <nav data-testid={`${slug}-sidebar-nav`}>
        {NAV_ITEMS.map((item) => (
          <a key={item.key} data-testid={`${slug}-nav-${item.key}`}>{item.label}</a>
        ))}
      </nav>
      <button data-testid={`${slug}-theme-toggle-btn`}>切换主题</button>
    </main>
  )
}
"""

LOGIN_CASE_ONLY_SHELL = """## E2E-LOGIN-001 登录页

```atlas-case
id: E2E-LOGIN-001
intent: 外壳模板展开回归（只引用展开值）
pages:
  - login
precondition:
  - 已打开登录页
step:
  - goto /login                 # 打开登录页
expected:
  - visible login-page          # 整页容器可见
testid:
  - login-page
```
"""


def test_testids_template_literal_expansion_unblocks_strict() -> None:
    """`data-testid={`…${slug}…`}` 按页面表词表静态展开（`${item.key}` 用同文件静态属性）。

    回归（2026-10-04）：此前实然抽取漏扫模板字面量 ⇒ 外壳派生的 testid（`home-page` 族）
    在「已实现」页永远缺失 ⇒ 页面表状态无法如实升级（与最严门互锁）。变异证明：摘掉
    `TEMPLATE_TESTID_ATTR` 扫描 ⇒ 本用例红（home-page 缺失）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        (root / "web" / "src" / "Shell.tsx").write_text(SHELL_TSX, encoding="utf-8")
        mk_cases(root, CASE_GOOD.replace(
            "  - home-cta-btn\n  - home-title\n",
            "  - home-cta-btn\n  - home-title\n  - home-page\n  - home-nav-config\n"))
        mk_index(root, _with_page_table("已实现"))
        res = vt.validate(root)
        assert res.status == "PASS", [c for c in res.checks if c["level"] in ("FAIL", "WARN")]


def test_testids_template_literal_missing_still_fails() -> None:
    """展开不是放水：应然声明了模板派生 id、源码里模板已删 ⇒ 「已实现」页照 FAIL
    （展开值只补实然，不补应然；缺失判罚保留）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("  - home-cta-btn\n  - home-title\n",
                                         "  - home-cta-btn\n  - home-title\n  - home-page\n"))
        mk_index(root, _with_page_table("已实现"))
        res = vt.validate(root)
        assert res.status == "FAIL"
        detail = [c["detail"] for c in res.checks if c["check"] == "分页双向集合相等"][0]
        assert "home-page" in detail and "缺失" in detail, detail


def test_testids_template_expansion_not_orphan_judged() -> None:
    """展开值**不参与「多余」判罚**：外壳挂载范围静态未知（模板会展开进不挂外壳的页，
    例：`login-nav-*`），多余不可静态判定（盲区登记于 gates.md）；**字面量照判**——
    `home-extra-btn` 这类字面量多余在含外壳的夹具下仍 FAIL（见
    test_testids_orphan_still_fails_and_names_usages）。
    变异证明：把 orphan 判据退回「pset - ids」⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        (root / "web" / "src" / "Shell.tsx").write_text(SHELL_TSX, encoding="utf-8")
        mk_cases(root)
        d = root / "product" / "e2e" / "cases"
        (d / "login.md").write_text(LOGIN_CASE_ONLY_SHELL, encoding="utf-8")
        mk_index(root, _with_page_table("已实现").replace(
            "| home | / | demo | 已实现 |",
            "| home | / | demo | 已实现 |\n| login | /login | demo | 已实现 |"))
        res = vt.validate(root)
        assert res.status != "FAIL", [c for c in res.checks if c["level"] == "FAIL"]


def test_e2e_index_gate_na() -> None:
    with tempfile.TemporaryDirectory() as td:
        assert ve.validate(Path(td)).status == "N/A"


def test_e2e_index_pass() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root)
        mk_index(root)
        res = ve.validate(root)
        assert res.status in ("PASS", "WARN"), [(c["check"], c["level"], c["detail"]) for c in res.checks]


def test_e2e_index_verb_fail() -> None:
    """新门（契约 §5.5，2026-09-23）：step/expected 首 token 不在动词词表内 → FAIL。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("- click home-cta-btn", "- 点击主操作按钮"))
        mk_index(root)
        res = ve.validate(root)
        assert res.status == "FAIL", [(c["check"], c["level"]) for c in res.checks]
        assert any(c["check"] == "step 动词合法" and c["level"] == "FAIL" for c in res.checks)


def test_e2e_index_decidable_ignores_inline_comment() -> None:
    """契约 §5.5：`#` 之后是给人读的说明、**机器忽略** ⇒ 按文本判定的门不得扫注释。

    实测事故（2026-09-25）：`expected 可判定` 的 `EXPECTED_BLACK` 含「无」，而某条用例的
    **注释**里写了「无法区分」⇒ 被误报为「判定不了什么」（`3509 §B45` 的同族第二例）。

    两向都钉：① 注释含黑名单词但断言本身强 ⇒ **不得**报；② 断言本身就弱（黑名单词） ⇒ **必须**报。
    """
    def _blacklisted(case: str) -> bool:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mk_prototype(root)
            mk_cases(root, case)
            mk_index(root)
            res = ve.validate(root)
            return any(
                c["check"] == "expected 可判定" and c["level"] == "WARN" for c in res.checks
            )

    strong_but_noisy = CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- text home-title 首页        # 无法区分是否正常显示",
    )
    assert not _blacklisted(strong_but_noisy), "注释里的黑名单词把断言带崩了（扫了 `#` 之后）"

    weak_only = CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- text home-title 正常        # 页面标题",
    )
    assert _blacklisted(weak_only), "断言**本体**就弱（含黑名单词）却没被报出来（漏报）"


def test_e2e_index_new_assert_verbs_render_and_validate() -> None:
    """契约 §5.5（2026-09-25 扩展）：`checked` / `unchecked` / `countOptions` / `attr` 与
    `value` 的空值写法，必须在**两侧**同时成立 —— 校验器放行 **且** 生成器可渲染。

    只测一侧就是 `3509 §B48` 的成因：词表加了动词、生成器认不得 ⇒ 用例写到一半才炸。
    末条为**反向证据**：未知动词必须仍被拒，证明合法性检查没被这次扩展弄松。
    """
    exprs = {
        # is*() 先 count 守卫（缺失元素不挂起——projects 页基线实测 2026-10-02）
        "- checked home-cta-btn": 'page.get_by_test_id("home-cta-btn").count() > 0 and _loc(page, "home-cta-btn").is_checked()',
        "- unchecked home-cta-btn": 'not (page.get_by_test_id("home-cta-btn").count() > 0 and _loc(page, "home-cta-btn").is_checked())',
        "- countOptions home-cta-btn 9": '_loc(page, "home-cta-btn").locator("option").count() == int("9")',
        # B173-1：value 经 _value_of 实现无关化（原生表单读值，combobox 读触发器文本）
        '- value home-cta-btn ""': '_value_of(page, "home-cta-btn") == ""',
        # 3509 §B35：`attr <testid> <name> <value>`（**不要求可见** ⇒ 用 `_loc`）
        "- attr home-cta-btn data-theme dark": '_loc(page, "home-cta-btn").get_attribute("data-theme") == "dark"',
        # 值可含空格：`name` 取首个空白前的 token，其余全部为值
        "- attr home-cta-btn aria-label 开始 按钮": '_loc(page, "home-cta-btn").get_attribute("aria-label") == "开始 按钮"',
    }
    for line, want in exprs.items():
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mk_prototype(root)
            mk_cases(root, CASE_GOOD.replace("- text home-title 首页", line))
            mk_index(root)
            res = ve.validate(root)
            assert not any(
                c["check"] in ("expected 动词合法", "断言不自相矛盾") and c["level"] == "FAIL"
                for c in res.checks
            ), [(c["check"], c["level"], c["detail"]) for c in res.checks]
        # 生成器侧：`- ` 前缀由用例解析器剥，校验前需自行去掉
        expr, _msg = gn.py_assert_expr(line[2:])
        assert expr == want, (line, expr)
    # 反向证据：未知动词仍被拒
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("- text home-title 首页", "- checkedX home-cta-btn"))
        mk_index(root)
        res = ve.validate(root)
        assert any(
            c["check"] == "expected 动词合法" and c["level"] == "FAIL" for c in res.checks
        ), [(c["check"], c["level"]) for c in res.checks]


def test_e2e_index_title_must_match_shard() -> None:
    """契约 §8.2（2026-09-25 补，`3509 §B31`）：索引 `中文标题` == 分片
    `## <ID> <标题>` 的**标题段**（空白归一后全等）。

    「锚点存在」与「标题文本相同」是两件事：前者只证明链接指向分片，标题文本在索引与
    分片各存一份副本（实测 `E2E-ASSETS-004`：索引写「素材列表按数据渲染名称与元信息」、
    分片写「BGM 列表按数据渲染名称与元信息」）。
    两侧同测：一致 ⇒ PASS、任一侧改一个字 ⇒ FAIL 且指名用例 ID。
    """
    lv, _ = _title_level()
    assert lv == "PASS", lv

    # 空白归一：分片标题带行尾空白仍算一致（白名单极窄，只归空白）
    lv, _ = _title_level(CASE_GOOD.replace("## E2E-HOME-001 首页加载并可进入空态",
                                          "## E2E-HOME-001 首页加载并可进入空态   "))
    assert lv == "PASS", "行尾空白不该被判不一致（归一过度）"

    # 分片侧改一个字 ⇒ FAIL + 指名
    lv, detail = _title_level(CASE_GOOD.replace("首页加载并可进入空态", "首页加载并可进入空态页"))
    assert lv == "FAIL", lv
    assert "E2E-HOME-001" in detail, detail

    # 索引侧改一个字 ⇒ 同样 FAIL（两侧都要查，不能只查分片）
    lv, detail = _title_level(index=INDEX_GOOD.replace("首页加载并可进入空态", "首页加载后进入空态"))
    assert lv == "FAIL", lv
    assert "E2E-HOME-001" in detail, detail


def test_e2e_index_download_is_action_not_assertion() -> None:
    """契约 §5.5（`3509 §B26`）：`download` 属**动作**（写在 `step` 侧）。

    两侧同测：写在 `step` ⇒ 校验器放行（`step 动词合法` PASS）；写在 `expected` ⇒ 被拒
    （断言词表里没有它）—— 后者是**反向证据**：它证明这个词确实落在动作侧，而不是两边都收。
    """
    ok = _levels(CASE_GOOD.replace(
        "- click home-cta-btn          # 点击主操作按钮",
        "- download home-cta-btn *.txt  # 触发导出并校验文件名模式",
    ))
    assert ok["step 动词合法"] == "PASS", ok

    bad = _levels(CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- download home-cta-btn *.txt",
    ))
    assert bad["expected 动词合法"] == "FAIL", bad


def test_e2e_index_initial_requires_reason() -> None:
    """契约 §5.6 R9 + §8.2（2026-09-25 补，`3509 §B36` 的「理由」那一半）：

    带 `initial:` 前缀的 `expected` 行必须写**显式理由**（行尾 `#` 后的中文说明）。
    无理由 ⇒ **WARN**（不是 FAIL：理由「够不够」是语义项，按 §6.0 `C-new` 不进文本期门）。
    末条为**否定对照**：门不得泛化到无前缀的普通断言。
    """
    with_reason = CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- initial: text home-title 首页  # 默认渲染态：本用例不产生状态差异",
    )
    assert _levels(with_reason)["initial 豁免带理由"] == "PASS"
    assert _levels(CASE_GOOD)["initial 豁免带理由"] == "PASS"

    without_reason = CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- initial: text home-title 首页",
    )
    assert _levels(without_reason)["initial 豁免带理由"] == "WARN"


def test_e2e_index_persist_requires_refresh() -> None:
    """契约 §5.6 R2 的适用面（2026-09-23 起**无条件**；同日二次收口到提交性控件）：
    - 步骤含**提交性控件**（`-save-` / `-submit-` / `-confirm-` / `-delete-` / `-remove-` / `-bind-`）
      而无刷新后复断言 → WARN（门咬得住）；
    - 步骤不含提交性控件 → 不 WARN（否定对照，防门泛化到一切用例）；
    - 例外 ①（expected 出现拒绝态 ⇒ 校验被拒、什么都没写）→ 不 WARN；
    - 例外 ②（`login` / `logout` 类控件属鉴权）→ 不 WARN。

    原尺子是「仅 `执行目标=app`」——原型补 mock 后端层（原型环 §5.1）后，原型期的写
    同样落盘且刷新后仍在，写不复断言会把什么都没做的用例判绿。
    **为何按提交控件的 testid 而不按中文说明命中**：「新建 / 编辑」在说明里多为
    「打开编辑器 / 打开新建弹窗」，本项目实测按说明命中 4 条用例、**全部为误报**。
    """
    commit = CASE_GOOD.replace("click home-cta-btn          # 点击主操作按钮",
                               "click home-save-btn         # 保存")
    assert commit != CASE_GOOD
    assert _persist_warns(commit), "提交性控件 + 无刷新后复断言 → 应 WARN"
    assert not _persist_warns(CASE_GOOD), "无提交性控件 → 不应 WARN"
    # 例外 ①：expected 出现拒绝态
    rejected = commit.replace(
        "  - text home-title 首页        # 页面标题文案为「首页」\n",
        "  - text home-title 首页        # 页面标题文案为「首页」\n"
        "  - visible home-save-error        # 保存被本地校验拦下\n")
    assert rejected != commit
    assert not _persist_warns(rejected), "例外 ①：校验被拒 → 不应 WARN"
    # 例外 ②：鉴权控件——fixture 必须同时命中「提交词」与「鉴权词」，
    # 否则例外 ② 的断言是空转的（去掉例外也不会变红 ⇒ 护栏不算数）。
    auth = commit.replace("click home-save-btn", "click home-login-submit-btn")
    assert auth != commit and "submit" in auth
    assert not _persist_warns(auth), "例外 ②：登录提交属鉴权 → 不应 WARN"


def test_e2e_index_or_step_ignores_comment() -> None:
    """契约 §5.5（2026-09-25 修）：`#` 之后是给人读的中文说明，**机器忽略**。

    本项（步骤非二选一）原实现把整行含注释一起扫 ⇒ 中文说明里出现「等」（如
    「等矫正建议产出」）就把用例误报为二选一 —— WARN 一多就没人看了。

    变异证明：把判据退回「扫整行」（`w in s`）⇒ 本用例的「注释含等 ⇒ PASS」断言变红；
    机器部分真写了二选一仍须 WARN（防止修成永假）。
    """
    comment_has_deng = CASE_GOOD.replace(
        "  - click home-cta-btn          # 点击主操作按钮\n",
        "  - click home-cta-btn          # 等标题就绪或按钮出现后继续\n",
    )
    assert comment_has_deng != CASE_GOOD
    assert _index_levels(comment_has_deng)["步骤非二选一"] == "PASS"

    machine_or = CASE_GOOD.replace(
        "  - click home-cta-btn          # 点击主操作按钮\n",
        "  - click home-cta-btn 或 home-title  # 二选一（机器部分）\n",
    )
    assert machine_or != CASE_GOOD
    assert _index_levels(machine_or)["步骤非二选一"] == "WARN"


def test_e2e_index_waitfor_is_action_not_assertion() -> None:
    """契约 §5.5 / §8.2（2026-09-25 补）：`waitFor` 是**动作**，不是终态断言。

    `step` 侧须收进动作词表（否则异步产出的终态写不进用例资产 = `3509 §B41`）；
    `expected` 侧须**专名** FAIL —— `expected` 是终态集合（§5.6 R9），写成断言等于让「等一会儿」冒充验证。

    变异证明：① 把 `waitFor` 从 `ACTION_VERBS` 移除 ⇒ step 侧断言变红；
    ② 去掉「`waitFor` 属动作」检查（退回只剩「expected 动词合法」）⇒ expected 侧专名断言变红。
    """
    as_step = CASE_GOOD.replace(
        "  - click home-cta-btn          # 点击主操作按钮\n",
        "  - waitFor home-title 首页      # 等标题文案就绪\n",
    )
    assert as_step != CASE_GOOD
    lv = _index_levels(as_step)
    assert lv["step 动词合法"] == "PASS", lv
    assert lv["waitFor 属动作"] == "PASS", lv

    as_assert = CASE_GOOD.replace(
        "  - text home-title 首页        # 页面标题文案为「首页」\n",
        "  - waitFor home-title 首页     # 写错位置：等待写进了终态集合\n",
    )
    assert as_assert != CASE_GOOD
    lv2 = _index_levels(as_assert)
    assert lv2["waitFor 属动作"] == "FAIL", lv2
    assert lv2["expected 动词合法"] == "FAIL", lv2


def test_e2e_index_unchanged_requires_submitting_action() -> None:
    """契约 §5.6 R9（2026-09-25 补）：`unchanged:` 的**形态项**靠文本期判。

    声明「动作不改变它」的用例，其 `step` 里**必须**有提交性动作（`save`/`submit`/
    `confirm`/`delete`/`remove`/`bind`/`cancel`/`logout`）；否则无动作可验 ⇒ 该断言退化为
    纯豁免，又回到假绿。

    本项只判形态（只读分片文本）；「初始态必须成立」必须在**运行期**判（文本期看不到页面初值，
    §6.0 `C-new`）。两者合起来才是双向判定。

    变异证明：把 `UNCHANGED_ACTION_WORDS` 改成空元组 ⇒ 本用例的 FAIL 断言变红。
    """
    no_action = CASE_GOOD.replace(
        "  - text home-title 首页        # 页面标题文案为「首页」\n",
        "  - unchanged: visible home-cta-btn   # 取消后按钮仍在（动作不改变它）\n")
    assert no_action != CASE_GOOD
    assert _index_levels(no_action)["unchanged 用例有提交性动作"] == "FAIL"

    with_action = no_action.replace("click home-cta-btn          # 点击主操作按钮",
                                   "click home-create-cancel-btn   # 取消")
    assert with_action != no_action
    assert _index_levels(with_action)["unchanged 用例有提交性动作"] == "PASS"

    # 前缀后的动词仍须在词表内（前缀不得成为绕过动词门的手段）
    bad_verb = CASE_GOOD.replace("  - text home-title 首页        # 页面标题文案为「首页」", "  - unchanged: home-title")
    assert bad_verb != CASE_GOOD
    assert _index_levels(bad_verb)["expected 动词合法"] == "FAIL"

    # 两个前缀不得叠（语义各不相同）
    nested = CASE_GOOD.replace("  - text home-title 首页        # 页面标题文案为「首页」",
                               "  - unchanged: initial: visible home-cta-btn")
    assert nested != CASE_GOOD
    assert _index_levels(nested)["豁免前缀不嵌套"] == "FAIL"


def test_e2e_index_goto_with_query_fails() -> None:
    """契约 §5.7（2026-09-23 补）：用例**不得**依赖原型专有调试参数（`goto` 带 `?` ⇒ FAIL）。

    原属性：原型专有的演示/调试开关（`?state=` 等）在真实应用上不存在 ⇒ 依赖它的用例
    过不了第二段。事故取证：`E2E-LOGIN-003` 断言的就是 `?state=forbidden` 演示横幅自己的文案
    （`3509 §B20`）。否定对照：普通 `goto` 不应被判。
    """
    def fails(case: str) -> bool:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mk_prototype(root)
            mk_cases(root, case)
            mk_index(root)
            return any(c["check"] == "goto 不带查询参数" and c["level"] == "FAIL" for c in ve.validate(root).checks)
    assert fails(CASE_GOOD.replace("- click home-cta-btn", "- goto /home?state=empty"))
    assert not fails(CASE_GOOD.replace("- click home-cta-btn", "- goto /home"))


def test_e2e_index_no_contradictory_assert() -> None:
    """契约 §5.6 R7（2026-09-23 补）：同一 testid 不得既断言可见又断言不可见。

    事故：`ASSETS-002/003`、`VOICES-001` 先断言某卡片存在、删掉后又断言它消失 ⇒
    「存在」那条永远为真（假绿）。否定对照：只断一种的不应被判。
    """
    def fails(case: str) -> bool:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mk_prototype(root); mk_cases(root, case); mk_index(root)
            return any(c["check"] == "断言不自相矛盾" and c["level"] == "FAIL" for c in ve.validate(root).checks)

    bad = CASE_GOOD.replace(
        "  - text home-title 首页        # 页面标题文案为「首页」\n",
        "  - text home-title 首页        # 页面标题文案为「首页」\n  - hidden home-title       # 又断言它不可见\n")
    assert bad != CASE_GOOD
    assert fails(bad)                      # 同一 testid 双向断言 → FAIL
    assert not fails(CASE_GOOD)            # 对照：只断可见 → 不判
    # ---- 2026-09-25 修正（`3509 §B43`）：判据由「单一 POS 集 vs 单一 NEG 集」
    # 改为**真矛盾对**。以下四条把「仍然会咬」与「不再误报」各自钉死。
    _TEXT_LINE = "  - text home-title 首页        # 页面标题文案为「首页」\n"
    # ① 仍然会咬：`hidden` ↔ 存在类（此处 text）
    vis_hidden = CASE_GOOD.replace(
        _TEXT_LINE,
        "  - visible home-title          # 可见\n  - hidden home-title           # 又断言不可见 → 真矛盾\n")
    assert vis_hidden != CASE_GOOD
    assert fails(vis_hidden), "visible + hidden 必须仍判 FAIL"
    # ② 仍然会咬：`enabled` ↔ `disabled`
    both_usability = CASE_GOOD.replace(
        _TEXT_LINE,
        "  - enabled home-title          # 可用\n  - disabled home-title         # 又断言不可用 → 真矛盾\n")
    assert both_usability != CASE_GOOD
    assert fails(both_usability), "enabled + disabled 必须仍判 FAIL"
    # ③ 不再误报：`disabled` + `text`（禁用的按钮照样有文案）
    disabled_text = CASE_GOOD.replace(
        _TEXT_LINE,
        _TEXT_LINE + "  - disabled home-title         # 同时禁用（与「有文案」不矛盾）\n")
    assert disabled_text != CASE_GOOD
    assert not fails(disabled_text), "disabled + text 不应判 FAIL（3509 §B43 误报）"
    # ④ 不再误报：`visible` + `disabled`（既可见又禁用是常态）
    visible_disabled = CASE_GOOD.replace(
        _TEXT_LINE,
        "  - visible home-title          # 可见\n  - disabled home-title         # 同时禁用 → 不矛盾\n")
    assert visible_disabled != CASE_GOOD
    assert not fails(visible_disabled), "visible + disabled 不应判 FAIL"


def test_e2e_index_no_target_column() -> None:
    """契约 §3.2 / §10（2026-09-23 退役）：主表**不得**再有 `执行目标` 列。

    原属性：主表列头与契约逐字一致 —— 多出已退役的列就是契约漂移（旧索引/旧模板没清干净），
    必须 FAIL，不能默默当普通列读过去。
    """
    legacy = INDEX_GOOD.replace(
        "| 需求 | 状态 |", "| 需求 | 执行目标 | 状态 |").replace(
        "| E2E-HOME-001 | home | 首页加载并可进入空态 | smoke | AC-HOME-001 | | red |",
        "| E2E-HOME-001 | home | 首页加载并可进入空态 | smoke | AC-HOME-001 | | prototype | red |")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root)
        mk_index(root, legacy)
        res = ve.validate(root)
        assert res.status == "FAIL", [(c["check"], c["level"]) for c in res.checks]
        assert any(c["check"] == "索引与主表列头" and c["level"] == "FAIL" for c in res.checks)


def test_e2e_index_orphan_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root)
        mk_index(root, INDEX_GOOD.replace("E2E-HOME-001 | home", "E2E-HOME-002 | home"))
        assert ve.validate(root).status == "FAIL"


def test_e2e_index_step_anchor() -> None:
    """契约 §5.5（2026-09-25 补，`3509 §B57`）：`after:<N>` 步骤锚的形态项 ——
    合法（N ≤ step 条数）⇒ PASS；越界 / 写法不合规 ⇒ FAIL；与 `initial:` 叠写 ⇒ FAIL。
    """
    ok = _levels_full(CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- after:1 visible home-cta-btn   # 点完后该按钮可见"))
    assert ok["步骤锚合法"] == "PASS", ok
    assert ok["expected 动词合法"] == "PASS", ok

    over = _levels_full(CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- after:2 visible home-cta-btn   # 越过 step 条数"))
    assert over["步骤锚合法"] == "FAIL", over

    malformed = _levels_full(CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- after:x visible home-cta-btn"))
    assert malformed["步骤锚合法"] == "FAIL", malformed

    nested = _levels_full(CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- after:1 initial: visible home-cta-btn"))
    assert nested["豁免前缀不嵌套"] == "FAIL", nested


def test_e2e_index_r7_is_per_timepoint() -> None:
    """契约 §5.6 R7（2026-09-25 按 `§B57` 修正）：矛盾只在**同一时点**里成立 ——
    `after:1 visible X` 与终态 `hidden X` **不矛盾**（先开后关，正是被测属性）；
    同一时点（都无锚）里 `visible X` + `hidden X` 则必须是 FAIL。
    """
    cross = _levels_full(CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- after:1 visible home-cta-btn   # 点完后可见\n  - hidden home-cta-btn            # 终态不可见"))
    assert cross["断言不自相矛盾"] == "PASS", cross

    same = _levels_full(CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- visible home-cta-btn   # 可见\n  - hidden home-cta-btn    # 不可见"))
    assert same["断言不自相矛盾"] == "FAIL", same


def test_e2e_index_zero_evidence_requires_struct_ac() -> None:
    """契约 §8.2 + PRD 环 §五（2026-09-25 补，`3509 §B36` + `§B50`）：
    `expected` 全 `initial:` 的**零证据用例**，只允许挂**结构类 AC**（PRD §五 清单里登记的）。
    两侧同测：挂了 ⇒ PASS；清单里没有它 ⇒ FAIL。
    """
    all_initial = CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- initial: text home-title 首页   # 默认渲染态：本用例不产生状态差异")

    listed = _levels_full(all_initial, listing="| `AC-HOME-001` | 纯渲染构成，页面初值即终态 |")
    assert listed["零证据用例须挂结构类 AC"] == "PASS", listed

    unlisted = _levels_full(all_initial, listing="| `AC-HOME-999` | 另一条 AC |")
    assert unlisted["零证据用例须挂结构类 AC"] == "FAIL", unlisted
    # 否定对照：非全 `initial:` 的普通用例不受本项约束（即使清单里没有它的 AC）
    assert _levels_full(CASE_GOOD, listing="| `AC-HOME-999` | 另一条 AC |")["零证据用例须挂结构类 AC"] == "PASS"


def test_prd_struct_ac_list_must_reference_existing_ac() -> None:
    """契约 §4「五」（2026-09-25 补）：结构类 AC 清单是 E2E 那道门的**唯一输入** ——
    清单引用了本文档 AC 表里不存在的 AC ⇒ `validate_prd` 参数4 FAIL（否则门静默失效）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_prd(root, listing="| `AC-HOME-001` | 纯渲染 |")
        ok = {c["check"]: c["status"] for c in vpr.validate(root).checks}
        assert ok["参数4 追溯完整"] == "PASS", ok

        (root / "product" / "prd" / "demo-prd.md").write_text(
            FM_DOMAIN + PRD_DEMO.format(ac="AC-HOME-001", rows="| `AC-HOME-777` | 幽灵 AC |"),
            encoding="utf-8")
        bad = {c["check"]: c["status"] for c in vpr.validate(root).checks}
        assert bad["参数4 追溯完整"] == "FAIL", bad


def test_testids_extraction_strips_step_anchor() -> None:
    """契约 §5.5（2026-09-25 补，`3509 §B57`）：行首前缀必须在**每个**解析 `expected` 行的消费者里
    被剥掉 —— `validate_testids` 忘了剥锚时，`after:2 visible X` 的**动词**会被当成 testid
    （实测：本门报「原型无 `visible`」而 `validate_e2e_index` 全 PASS）。
    """
    case = CASE_GOOD.replace("- text home-title 首页        # 页面标题文案为「首页」",
                             "- after:1 visible home-cta-btn")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, case)
        mk_index(root)
        res = vt.validate(root)
    detail = [c["detail"] for c in res.checks if c["check"] == "分页双向集合相等"][0]
    assert "visible" not in detail, detail
    assert res.status != "FAIL", [(c["check"], c["level"], c["detail"]) for c in res.checks]


def test_stack_profile_origin_greenfield_pass() -> None:
    """显式 greenfield：枚举门 PASS；prototype 段非 null 照常判。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_profile(root, PROFILE_BASE.format(origin="greenfield"))
        res = vsp.validate(root)
        assert res.status == "PASS", [(c["check"], c["level"], c["detail"]) for c in res.checks]
        assert _sp_check(res, "origin 枚举")["level"] == "PASS"


def test_stack_profile_origin_missing_defaults_to_greenfield() -> None:
    """缺省 origin：WARN 提示（不 FAIL），形态仍按 greenfield（E1：prototype 段已退役
    ⇒ N/A，不再有「null 放行」之分；本钉子改守「缺省不是 adopt」）。

    这是「缺省保持现状」的钉子：缺省若被当成 adopt，`prototype` 为 null 会被静默放行。
    变异：把缺省改成 adopt ⇒ 本用例的 prototype 断言红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        text = PROFILE_BASE.format(origin="greenfield").replace("origin: greenfield\n", "")
        text = text.replace("prototype:\n  dir: product/prototype\n", "prototype: null\n")
        mk_profile(root, text)
        res = vsp.validate(root)
        assert _sp_check(res, "origin 枚举")["level"] == "WARN"
        assert _sp_check(res, "prototype 段（已退役 E1）")["level"] == "N/A"
        assert res.status == "WARN"


def test_stack_profile_origin_adopt_allows_null_prototype() -> None:
    """E1：prototype 段已退役 ⇒ 无论何值都记 N/A（不再有「合法降级 / 缺字段」之分）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        text = (PROFILE_BASE.format(origin="adopt")
                .replace("prototype:\n  dir: product/prototype\n", "prototype: null\n"))
        mk_profile(root, text)
        res = vsp.validate(root)
        c = _sp_check(res, "prototype 段（已退役 E1）")
        assert c["level"] == "N/A", c
        assert res.status == "PASS", [(x["check"], x["level"]) for x in res.checks]


def test_stack_profile_origin_invalid_fails() -> None:
    """非法 origin ⇒ FAIL（不许静默当成 greenfield 放过去）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_profile(root, PROFILE_BASE.format(origin="hybrid"))
        res = vsp.validate(root)
        assert res.status == "FAIL"
        assert _sp_check(res, "origin 枚举")["level"] == "FAIL"


def test_stack_profile_top_level_scalar_after_section_is_parsed() -> None:
    """段头之后的顶层标量必须被解析。

    旧实现只在「还没遇到任何段头」时读顶层标量 ⇒ `origin` 写在 `apps:` 之后会被吞掉，
    表现是「文件里明明写了 adopt，门却按 greenfield 判」—— 按文件顺序改变语义的静默错。
    变异：还原「section 不关闭」⇒ 本用例 parse 结果变 None 而红。
    """
    text = (
        "product: 测试产品\n"
        "apps:\n"
        "  - name: web\n"
        "    path: web\n"
        "    kind: frontend\n"
        "    role: landing\n"
        "    stack: 仅展示\n"
        "adapters:\n"
        "  routes: null\n"
        "origin: adopt\n"
        "prototype: null\n"
    )
    parsed = vsp.parse_profile(text)
    assert parsed["origin"] == "adopt", parsed
    assert parsed["prototype"] is None, parsed
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_profile(root, text)
        assert _sp_check(vsp.validate(root), "origin 枚举")["level"] == "PASS"


def test_stack_profile_seed_mode_gate() -> None:
    """stack-profile §2 / B197-1（2026-10-07）：`e2e.seed` 子段——键白名单（hook/mode）+
    `mode` 枚举（declare | enforce，缺省 enforce = 现行为）+ 未声明 = 合法降级。
    词表守恒：SEED_MODES ⊆ 模板 ⊆ 契约正文（照 ORIGINS 三处同步先例）。
    变异证明 M41：把 mode 枚举判据卸成恒真 ⇒ 非法值钉子红。
    """
    template = (PKG_ROOT / "templates" / "stack-profile.yaml").read_text(encoding="utf-8")
    contract = (PKG_ROOT / "shared" / "stack-profile.md").read_text(encoding="utf-8")
    for v in vsp.SEED_MODES:
        assert v in template, f"模板缺 seed.mode 取值：{v}"
        assert v in contract, f"契约缺 seed.mode 取值：{v}"
    for k in vsp.SEED_KEYS:
        assert k in contract, f"契约缺 e2e.seed 子键：{k}"

    def _gate(profile_text: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "product").mkdir(parents=True)
            (root / "product" / "stack-profile.yaml").write_text(profile_text, encoding="utf-8")
            res = vsp.validate(root)
            return {c["check"]: c for c in res.checks}

    base = """product: demo
apps:
  - name: app
    path: app
    kind: frontend
    role: landing
    stack: demo
e2e:
  runner: python-playwright
"""
    # 缺省（未声明 seed 段）= 合法降级
    rows = _gate(base)
    assert rows["e2e.seed（可选段）"]["level"] == "PASS", rows
    # declare / enforce 合法；非法值 FAIL 且点名允许值
    rows = _gate(base + "  seed:\n    mode: declare\n")
    assert rows["e2e.seed.mode 枚举"]["level"] == "PASS", rows
    rows = _gate(base + "  seed:\n    mode: enforce\n")
    assert rows["e2e.seed.mode 枚举"]["level"] == "PASS", rows
    rows = _gate(base + "  seed:\n    mode: auto\n")
    assert rows["e2e.seed.mode 枚举"]["level"] == "FAIL" and "auto" in rows["e2e.seed.mode 枚举"]["detail"], rows
    # 未知键 FAIL；seed 段标量形态 FAIL
    rows = _gate(base + "  seed:\n    mode: declare\n    zombie: 1\n")
    assert rows["e2e.seed 键白名单"]["level"] == "FAIL", rows
    rows = _gate(base + "  seed: null\n")
    assert rows["e2e.seed（可选段）"]["level"] == "PASS", rows  # null = 合法降级


def test_stack_profile_origin_vocabulary_in_sync() -> None:
    """词表守恒：校验器 ORIGINS ⊆ 模板 ⊆ 契约正文（同一词表三处同步）。

    变异：给 ORIGINS 加第三个值而不写进模板/契约 ⇒ 本用例红。
    """
    template = (PKG_ROOT / "templates" / "stack-profile.yaml").read_text(encoding="utf-8")
    contract = (PKG_ROOT / "shared" / "stack-profile.md").read_text(encoding="utf-8")
    for v in vsp.ORIGINS:
        assert v in template, f"模板缺 origin 取值：{v}"
        assert v in contract, f"契约缺 origin 取值：{v}"
    assert vsp.DEFAULT_ORIGIN in vsp.ORIGINS


def test_prd_shape_declaration_required_and_closed() -> None:
    """契约 §3：范围形态声明是机器门的第一输入 —— 缺 ⇒ FAIL；值非法 ⇒ FAIL 且**点名允许值**。

    变异：把 form is None 分支改成 pass ⇒ 「缺」侧红；把 DECL_ANY 点名退回「缺声明」⇒ 「非法」侧红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prd(root)
        assert _p4(root)["status"] == "PASS", _p4(root)

        mk_prd_raw(root, (FM_GLOBAL + PRD_GLOBAL).replace("范围形态：首建\n\n", ""))
        c = _p4(root)
        assert c["status"] == "FAIL" and "缺范围形态声明行" in c["detail"], c

        mk_prd_raw(root, (FM_GLOBAL + PRD_GLOBAL).replace("范围形态：首建", "范围形态：混成"))
        c = _p4(root)
        assert c["status"] == "FAIL" and "取值非法" in c["detail"] and "首建" in c["detail"], c


def test_prd_shape_must_match_section_six_form() -> None:
    """契约 §3/「六」二选一：声明与 §六 表形态必须一致（表头有 `处置` 列 ⇔ 变更）。两侧同测。

    变异：把 `has_dispose != (form == "变更")` 改成恒 False ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prd_raw(root, _six_as_disposal(FM_GLOBAL + PRD_GLOBAL))          # 首建 + 处置列
        c = _p4(root)
        assert c["status"] == "FAIL" and "§六 表形态与声明不一致" in c["detail"], c

        mk_prd_raw(root, (FM_GLOBAL + PRD_GLOBAL).replace(              # 变更 + 无处置列
            "范围形态：首建", "范围形态：变更\n覆盖度：全量\n基线：上一版")) 
        c = _p4(root)
        assert c["status"] == "FAIL" and "§六 表形态与声明不一致" in c["detail"], c


def test_prd_min_required_set_follows_coverage() -> None:
    """契约 §3 最小必填集：`增量起步` 只强制 五/六/七（其余章节可缺）；全量则要求全在。

    变异：`need` 恒取 MIN_SECTIONS ⇒ 「全量缺章节」侧红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        full = FM_GLOBAL + PRD_GLOBAL
        trimmed = re.sub(r"## (一|二|三|四|八|九|十|十一)、.*?(?=## |\Z)", "", full, flags=re.S)
        incr = _six_as_disposal(trimmed.replace(
            "范围形态：首建\n\n", "范围形态：变更\n覆盖度：增量起步\n基线：上一版 PRD\n\n"))
        dom = FM_DOMAIN + PRD_DEMO.format(ac="AC-HOME-001", rows="| `AC-HOME-001` | 纯渲染 |")
        mk_prd_raw(root, incr, dom)
        c = _p4(root)
        assert c["status"] == "PASS", c

        mk_prd_raw(root, trimmed, dom)                                  # 同样缺章节，但是「全量」
        c = _p4(root)
        assert c["status"] == "FAIL" and "缺必填章节" in c["detail"], c


def test_e2e_index_i18n_judge_ignores_comments() -> None:
    """`3509 §B95`：文案来源判据必须先剥 `#` 注释（与同文件另两处同族）。

    两侧同测：注释里出现 i18n 形态词 ⇒ 不得报；断言**本体**含 ⇒ 必须报。
    变异 M15：把 `_code(e)` 退回 `e` ⇒ 第一侧红。
    """
    good = CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- text home-title 首页        # 对应 i18n key `t(home.title)` 的渲染结果")
    assert _levels(good)["文案为渲染后文案"] != "WARN", _levels(good)
    bad = CASE_GOOD.replace(
        "- text home-title 首页        # 页面标题文案为「首页」",
        "- text home-title t(home.title)  # 直接断言 i18n key")
    assert _levels(bad)["文案为渲染后文案"] == "WARN", _levels(bad)


def _seed_levels(case: str, models: str | None) -> dict[str, str]:
    """跑一遍索引校验器，`models` 非 None 时另写一份 structure 的 `data-models.md` 事实。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, case)
        mk_index(root)
        if models is not None:
            d = root / ".trellis" / "spec" / "structure" / "current" / "demo"
            d.mkdir(parents=True, exist_ok=True)
            (d / "data-models.md").write_text(models, encoding="utf-8")
        return {c["check"]: c["level"] for c in ve.validate(root).checks}


MODELS_OK = """# 数据模型

| 表/模型 | 字段 | 类型 | 约束/默认 | 关系 | 枚举 |
|---|---|---|---|---|---|
| voice | name / engine | str | — | — | — |
"""


def test_e2e_index_seed_models_reconciliation() -> None:
    """契约 §5.7（2026-09-28，`3509 §98 ⑪`）：`seed:` 的实体 × 字段必须存在于 models 事实。

    四侧：无 `seed:` ⇒ NA；有 seed 但无 models 事实 ⇒ **NA（不是通过）**；
    有事实 + 实体不在 ⇒ FAIL；实体与字段都对 ⇒ PASS。
    变异 M16：摘掉 `validate()` 里对该判据的调用 ⇒ 本用例红（行消失）。
    """
    seed_ok = CASE_GOOD.replace("testid:\n", "seed:\n  - upsert voice name=旁白\ntestid:\n")
    seed_bad = CASE_GOOD.replace("testid:\n", "seed:\n  - upsert ghost name=x\ntestid:\n")
    assert _seed_levels(CASE_GOOD, None)["seed × models 对账"] == "NA"          # 无 seed
    no_facts = _seed_levels(seed_ok, None)
    assert no_facts["seed × models 对账"] == "NA", no_facts                        # 无事实 ⇒ NA
    assert _seed_levels(seed_ok, MODELS_OK)["seed × models 对账"] == "PASS"
    assert _seed_levels(seed_bad, MODELS_OK)["seed × models 对账"] == "FAIL"


def test_prd_ac_table_columns_enforced() -> None:
    """契约 §5 三列形态（2026-09-28 定，`3509 §B74`）：§五 AC 表同表含 `AC ID` + `回指规则`，
    且**不得**含 `样例类型`（已移交 E2E 环）。表列是契约承诺，无判据时文本与产物会长期不一致。

    变异：删掉 `样例类型` 分支 ⇒ 本用例第一侧红。
    """
    three = PRD_DEMO.format(ac="AC-HOME-001", rows="| `AC-HOME-001` | 纯渲染构成 |")
    six = three.replace(
        "| AC ID | 场景（Given / When / Then） | 回指规则 |\n|---|---|---|",
        "| AC ID | 样例类型 | 前置 Given | 操作 When | 预期 Then | 回指规则 |\n|---|---|---|---|---|---|")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prd_raw(root, PRD_GLOBAL, FM_DOMAIN + six)
        c = _p4(root)
        assert c["status"] == "FAIL" and "样例类型" in c["detail"], c
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prd(root)
        c = _p4(root)
        assert c["status"] == "PASS", c


def test_prd_trace_registers_uncovered_domains() -> None:
    """契约 §7 参数 4 ⑥（2026-09-28 补，`3509 §B75`）：`增量起步` 下没有域级文件的域，
    必须在追溯总表里有合法的「未覆盖（沿用实然）」登记行 —— 否则「本轮没覆盖哪些域」没有唯一登记点。

    变异：删掉 `uncovered < len(extra)` 判据 ⇒ 第一侧红；删掉行形态判据 ⇒ 第二侧红。
    """
    head = """# 追溯总表

## 一、域 ↔ 编号前缀

| 域 slug | 中文名 | 编号前缀 CODE | 域级文件 |
|---|---|---|---|
| `demo` | 演示域 | `DEMO` | `product/prd/demo-prd.md` |
| `other` | 另一域 | `OTHER` | `product/prd/other-prd.md` |

## 二、追溯总表

| 域 | 域级文件 | structure 模块 | 页面 | 功能数 | 规则数 | AC 数 | E2E 分片 | 范围摘要 |
|---|---|---|---|---|---|---|---|---|
"""
    covered = "| 演示域 | `demo-prd.md` | — | `/demo` | 1 | 2 | 2 | — | 已覆盖 |"
    uncovered = ("| 另一域 | —（未覆盖） | — | — | — | — | — | — "
                 "| 未覆盖（沿用实然）· 基线：`legacy/other/` |")
    dom = (FM_DOMAIN + PRD_DEMO.format(ac="AC-DEMO-001", rows="| `AC-DEMO-001` | 纯渲染 |")
           ).replace("AC-HOME-999", "AC-DEMO-999")
    full = FM_GLOBAL + PRD_GLOBAL
    trimmed = re.sub(r"## (一|二|三|四|八|九|十|十一)、.*?(?=## |\Z)", "", full, flags=re.S)
    incr = _six_as_disposal(trimmed.replace(
        "范围形态：首建\n\n", "范围形态：变更\n覆盖度：增量起步\n基线：上一版 PRD\n\n"))
    incr = incr.replace(
        "| `demo` | 演示域 | 用于夹具 | `product/prd/demo-prd.md` |",
        "| `demo` | 演示域 | 用于夹具 | `product/prd/demo-prd.md` |\n"
        "| `other` | 另一域 | 本轮未覆盖 | — |")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prd_raw(root, incr, dom)
        trace = root / "product" / "prd" / "README.md"
        trace.write_text(head + covered + "\n", encoding="utf-8")
        c = _p4(root)
        assert c["status"] == "FAIL" and "未覆盖行数" in c["detail"], c
        trace.write_text(head + covered + "\n" + uncovered + "\n", encoding="utf-8")
        c = _p4(root)
        assert c["status"] == "PASS", c
        # 第三侧：行形态非法（未覆盖行缺「未覆盖（沿用实然）」摘要）⇒ 仍 FAIL
        trace.write_text(head + covered + "\n"
                         + uncovered.replace("未覆盖（沿用实然）· 基线：`legacy/other/`", "待补") + "\n",
                         encoding="utf-8")
        c = _p4(root)
        assert c["status"] == "FAIL" and "行形态非法" in c["detail"], c


def test_prd_rule_must_be_cited_by_an_ac() -> None:
    """契约 §5 双向追溯（2026-09-26 补）：每条规则须被 ≥1 条 AC 回指。

    这条正是原「参数 5 Waste Test」的第一条判据 —— 此前从未被实现（恒 PASS 的空门）。
    变异：`uncited` 恒取 [] ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prd(root)
        assert _p4(root)["status"] == "PASS", _p4(root)

        body = FM_DOMAIN + PRD_DEMO.format(ac="AC-HOME-001", rows="| `AC-HOME-001` | 纯渲染 |")
        # 夹具已有 §四 规则表（含 `所属功能` 列）⇒ 删掉唯一回指 `DEMO-R-002` 的那条 AC，
        # 让该规则变成「无 AC 回指」（不再用注入 5 列规则行的旧手法）。
        body = body.replace(
            "| `AC-HOME-999` | Given 已登录，When 点击按钮，Then 出现新行 | `DEMO-R-002` |\n", "")
        mk_prd_raw(root, FM_GLOBAL + PRD_GLOBAL, body)
        c = _p4(root)
        assert c["status"] == "FAIL" and "DEMO-R-002" in c["detail"], c


def test_prd_rule_must_declare_features_and_cover_each_feature() -> None:
    """契约 §4「所属功能」列（2026-09-28，`3509 §B109`）：缺列 / 空值 / 幽灵功能号 / 功能无规则服务。

    四种都 FAIL —— 它们正是「功能 → 规则 → AC」链路的前一环。
    变异：把「功能无规则服务」判据去掉（`orphan_fn` 恒空）⇒ 本用例第 ④ 条变红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prd(root)
        assert _p4(root)["status"] == "PASS", _p4(root)

    def _run(mutate) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            body = FM_DOMAIN + PRD_DEMO.format(ac="AC-HOME-001", rows="| `AC-HOME-001` | 纯渲染 |")
            mk_prd_raw(root, FM_GLOBAL + PRD_GLOBAL, mutate(body))
            return _p4(root)

    c = _run(lambda b: b.replace(
        "| 规则 ID | 规则内容 | 所属功能 | 触发条件 | 优先级 | 影响范围 |",
        "| 规则 ID | 规则内容 | 触发条件 | 优先级 | 影响范围 |").replace(
        "|---|---|---|---|---|---|", "|---|---|---|---|---|", 1))            # ① 缺列
    assert c["status"] == "FAIL" and "所属功能" in c["detail"], c

    c = _run(lambda b: b.replace("| `DEMO-R-001` | 演示规则一 | `FN-DEMO-001` |",
                                 "| `DEMO-R-001` | 演示规则一 |  |"))                 # ② 空值
    assert c["status"] == "FAIL" and "未声明所属功能" in c["detail"], c

    c = _run(lambda b: b.replace("`FN-DEMO-001` | 打开页面",
                                 "`FN-DEMO-777` | 打开页面"))                      # ③ 幽灵功能号
    assert c["status"] == "FAIL" and "不存在的功能" in c["detail"], c

    c = _run(lambda b: b.replace(
        "| `FN-DEMO-001` | 演示功能 | 用于夹具 | P0 | 新增 |",
        "| `FN-DEMO-001` | 演示功能 | 用于夹具 | P0 | 新增 |\n"
        "| `FN-DEMO-002` | 孤儿功能 | 无任何规则服务 | P1 | 新增 |"))               # ④ 功能无规则服务
    assert c["status"] == "FAIL" and "功能无规则服务" in c["detail"], c


def test_prd_traceability_counts_must_match_reality() -> None:
    """契约 §7 参数 4 ⑤（2026-09-28，`3509 §B109`）：追溯总表的功能/规则/AC 计数必须等于
    按 `domain_code` 去重的实际数 —— 实测七域全过期（人维护、无判据）。

    变异：把该判据去掉 ⇒ 本用例第 ② 条变红。
    """
    def _run(fn: int, nr: int, na: int) -> dict:
        """夹具实际计数：功能 1（FN-DEMO-001）/ 规则 2 / AC 1（`AC-DEMO-001`）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            body = FM_DOMAIN + PRD_DEMO.format(ac="AC-DEMO-001", rows="| `AC-DEMO-001` | 纯渲染 |")
            mk_prd_raw(root, FM_GLOBAL + PRD_GLOBAL, body)
            (root / "product" / "prd" / "README.md").write_text(
                "# 追溯总表\n\n| 域 | 域级文件 | structure 模块 | 页面 | 功能数 | 规则数 | AC 数 |\n"
                "|---|---|---|---|---|---|---|\n"
                f"| 演示域 | `demo-prd.md` | — | `/` | {fn} | {nr} | {na} |\n", encoding="utf-8")
            return {c["check"]: c for c in vpr.validate(root).checks}["参数4 追溯总表计数"]

    assert _run(1, 2, 1)["status"] == "PASS", _run(1, 2, 1)
    bad = _run(1, 2, 9)
    assert bad["status"] == "FAIL" and "demo-prd.md" in bad["detail"], bad


def test_prd_domain_list_must_match_domain_files() -> None:
    """契约 §5：§五 域清单 ↔ 磁盘域级文件一一对应 —— 清单多 / 磁盘多都 FAIL。

    变异：把 `if extra or orphan` 改成恒 False ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prd(root)
        assert _p4(root)["status"] == "PASS", _p4(root)

        ghost_row = ("\n| `ghost` | 幽灵域 | 无文件 | `product/prd/ghost-prd.md` |")
        mk_prd_raw(root,
                   (FM_GLOBAL + PRD_GLOBAL).replace(
                       "| `demo` | 演示域 | 用于夹具 | `product/prd/demo-prd.md` |",
                       "| `demo` | 演示域 | 用于夹具 | `product/prd/demo-prd.md` |" + ghost_row),
                   FM_DOMAIN + PRD_DEMO.format(ac="AC-HOME-001", rows="| `AC-HOME-001` | 纯渲染 |"))
        c = _p4(root)
        assert c["status"] == "FAIL" and "ghost" in c["detail"], c


def test_prd_change_form_fields_and_revision_log_body() -> None:
    """契约 §3：`变更` 形态必须带 `覆盖度` 与 `基线`；全量形态下 `十一 修订记录` 正文不得为空。

    变异：删掉 `覆盖度`/`基线` 的必填分支 ⇒ 前两侧红；删掉 `十一` 空体分支 ⇒ 第三侧红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        dom = FM_DOMAIN + PRD_DEMO.format(ac="AC-HOME-001", rows="| `AC-HOME-001` | 纯渲染 |")
        plain = FM_GLOBAL + PRD_GLOBAL
        disp = _six_as_disposal(plain)                      # §六 = 处置表，配「变更」
        decl = "范围形态：首建\n\n"

        mk_prd_raw(root, disp.replace(decl, "范围形态：变更\n基线：上一版\n\n"), dom)
        c = _p4(root)
        assert c["status"] == "FAIL" and "覆盖度" in c["detail"], c

        mk_prd_raw(root, disp.replace(decl, "范围形态：变更\n覆盖度：全量\n\n"), dom)
        c = _p4(root)
        assert c["status"] == "FAIL" and "基线" in c["detail"], c

        empty11 = re.sub(r"## 十一、.*", "## 十一、修订记录\n\n", plain, flags=re.S)
        mk_prd_raw(root, empty11, dom)
        c = _p4(root)
        assert c["status"] == "FAIL" and "正文为空" in c["detail"], c


def test_testids_stub_missing_fails() -> None:
    """契约 §4.1（2026-09-26 补，`3509 §B73`）：薄桩由生成器产出 ⇒ **不存在即 FAIL**，不静默。

    变异：把「实现期薄桩存在」改成恒 PASS ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root)
        res = {c["check"]: c for c in vt.validate(root).checks}
        assert res["实现期薄桩存在"]["level"] == "PASS", res

        (root / ".trellis" / "spec" / "conventions" / "testid.md").unlink()
        res = {c["check"]: c for c in vt.validate(root).checks}
        assert res["实现期薄桩存在"]["level"] == "FAIL", res
        assert "gen_testid_stub" in res["实现期薄桩存在"]["detail"], res


def test_testids_adopt_extracts_from_real_ui() -> None:
    """契约 §4 + `single-source.md` §1（2026-09-26 补）：`origin: adopt` 时 testid 真相源 = **真实 UI**。

    两侧同测：真实 UI 里有的 testid ⇒ PASS；把它从真实 UI 去掉 ⇒ 用例引用变成「缺失(抽取源无)」FAIL。
    变异：`collect_testids` 的 adopt 分支退回读 `product/prototype/` ⇒ 本用例红（临时根里没有原型）。
    """
    profile = ("product: 老项目\norigin: adopt\napps:\n"
               "  - name: web\n    path: web\n    kind: frontend\n    role: landing\n"
               "    stack: 仅展示\nadapters:\n  routes: null\n")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "stack-profile.yaml").write_text(profile, encoding="utf-8")
        mk_stub(root)
        src = root / "web" / "src"
        src.mkdir(parents=True)
        (src / "HomePage.tsx").write_text(
            '<button data-testid="home-cta-btn">去</button>\n'
            "<h1 data-testid='home-title'>首页</h1>\n", encoding="utf-8")
        d = root / "product" / "e2e" / "cases"
        d.mkdir(parents=True)
        (d / "home.md").write_text(CASE_GOOD, encoding="utf-8")

        res = {c["check"]: c for c in vt.validate(root).checks}
        assert res["分页双向集合相等"]["level"] == "PASS", res
        assert vt.read_origin(root) == "adopt"

        (src / "HomePage.tsx").write_text('<button data-testid="home-cta-btn">去</button>\n',
                                          encoding="utf-8")
        res = {c["check"]: c for c in vt.validate(root).checks}
        assert res["分页双向集合相等"]["level"] == "FAIL", res


def test_testids_origin_readers_agree() -> None:
    """`origin` 的**词表守恒**（硬约束 7：同一口径的消费者数要先数清，并逐项守恒）。

    **三个**代码消费者：`validate_stack_profile.py`（枚举门）、`validate_testids.py`（选抽取源）、
    `validate_prd.py`（adopt 未开户记 N/A）。变异：任一侧加第三个取值 / 改默认值 ⇒ 本用例红。
    """
    assert vt.ORIGINS == vsp.ORIGINS, (vt.ORIGINS, vsp.ORIGINS)
    assert vt.DEFAULT_ORIGIN == vsp.DEFAULT_ORIGIN, (vt.DEFAULT_ORIGIN, vsp.DEFAULT_ORIGIN)
    assert vpr.ORIGINS == vsp.ORIGINS, (vpr.ORIGINS, vsp.ORIGINS)
    assert vpr.DEFAULT_ORIGIN == vsp.DEFAULT_ORIGIN, (vpr.DEFAULT_ORIGIN, vsp.DEFAULT_ORIGIN)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True, exist_ok=True)
        for val, expect in (("adopt", "adopt"), ("greenfield", "greenfield"),
                            (None, vt.DEFAULT_ORIGIN), ("hybrid", vt.DEFAULT_ORIGIN)):
            text = "product: demo\napps: []\n"
            if val is not None:
                text = f"product: demo\norigin: {val}\napps: []\n"
            (root / "product" / "stack-profile.yaml").write_text(text, encoding="utf-8")
            assert vt.read_origin(root) == expect, (val, vt.read_origin(root), expect)
            assert vpr.read_origin(root) == expect, (val, vpr.read_origin(root), expect)


def test_adopt_empty_asset_is_na_not_fail() -> None:
    """G1/G3（2026-09-26 补）：`origin: adopt` 且**尚未开户**时，四个门都记 `N/A` 而不是 FAIL ——
    旧项目接入的入场形态本来就是「资产为空、从第一条需求长起」（`apply/reference.md` §1 的 `adopt`）。

    两侧同测 + 端到端：adopt 空资产 ⇒ 四门无 FAIL；同一目录改成 greenfield ⇒ `validate_prd` 必须 FAIL
    （缺 `product/prd/prd.md` 是真错，不许被静默放过）。
    变异：把 `validate_prd` 的 adopt 分支改成恒 False ⇒ 本用例红。
    """
    app = "apps:\n  - name: web\n    path: web\n    kind: frontend\n" \
          "    role: landing\n    stack: 仅展示\n"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 老项目\norigin: adopt\n" + app, encoding="utf-8")
        checks = {c["check"]: c["status"] for c in vpr.validate(root).checks}
        assert checks.get("总判定") == "NA", checks
        for mod in (vt, ve):
            assert mod.validate(root).status != "FAIL", (mod.__name__, mod.validate(root).checks)

        # greenfield 侧：缺 `product/prd/prd.md` 是**真错**（早退路径只记参数 1，CLI 由 main 兜底判 FAIL）
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 新项目\norigin: greenfield\n" + app, encoding="utf-8")
        checks = {c["check"]: c["status"] for c in vpr.validate(root).checks}
        assert checks.get("参数1 文档头完整") == "FAIL", checks


def test_prd_adopt_opening_min_set_passes() -> None:
    """契约 §4「开户最小集」：`origin: adopt` 开户 = 全局最小必填集 + 每域一份**最小**域级 PRD
    （一/二/四/五 四节；三 六件套与 六 Assumptions **整节不出现**）。

    本用例钉住：**少两节 ≠ 少门** —— 同一套参数 1–4 照旧全咬。三侧变异各对应一个真错：
      ① 少一份域级 PRD      ⇒ 域清单↔域级文件不一致（参数 4 红）；
      ② AC「回指规则」列清空 ⇒ 规则无 AC 回指（参数 4 红）；
      ③ 域级引用回退成 `../README.md` ⇒ 链接不可解析（参数 3 红，`3509 §B86`）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_profile(root, PROFILE_BASE.format(origin="adopt").replace(
            "prototype:\n  dir: product/prototype\n", "prototype: null\n"))

        # 基线必须绿——否则后面三侧的红说明不了任何事（“先证基线 GREEN 再注入”）
        mk_adopt_opening(root)
        assert _p3(root)["status"] == "PASS", _p3(root)
        assert _p4(root)["status"] == "PASS", _p4(root)

        mk_adopt_opening(root, drop_domain=True)
        assert _p4(root)["status"] == "FAIL", "少了域级 PRD 却仍绿：域清单↔域级文件一一对应门没有咬"

        mk_adopt_opening(root, blank_ref=True)
        assert _p4(root)["status"] == "FAIL", "AC 不回指规则却仍绿：规则→AC 覆盖率门没有咬"

        mk_adopt_opening(root, legacy_rel_path=True)
        assert _p3(root)["status"] == "FAIL", "`../README.md` 解析不到却仍绿：链接可解析门没有咬"

        # 还原后必须回到绿（证明上面三侧的红是注入造成的，不是产物本来就坏）
        mk_adopt_opening(root)
        assert _p3(root)["status"] == "PASS" and _p4(root)["status"] == "PASS"



def test_goto_path_must_be_in_page_table() -> None:
    """契约 §5.5（2026-09-30）：`goto` 路径必须命中页面表路由列（唯一真相源）。
    匹配 = 精确或非根路由子路径前缀；根路由仅精确。
    变异 M27：摘掉校验器 `goto 路径 ∈ 页面表` 门 ⇒ 越界路径不报红（假绿复活）。
    """
    index = INDEX_GOOD.replace(
        "## 页面 ↔ 用例",
        "## 页面表（页 ↔ 路由）\n\n| 页面 | 路由 | 域 |\n|---|---|---|\n"
        "| home | / | demo |\n| projects | /projects | demo |\n\n## 页面 ↔ 用例")

    def levels(case: str) -> dict[str, tuple[str, str]]:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mk_prototype(root)
            mk_cases(root, case)
            mk_index(root, index)
            return {c["check"]: (c["level"], c["detail"]) for c in ve.validate(root).checks}

    bad = levels(CASE_GOOD.replace(
        "  - click home-cta-btn          # 点击主操作按钮",
        "  - goto /nowhere              # 越界路径（页面表外）\n"
        "  - click home-cta-btn          # 点击主操作按钮"))
    assert bad["goto 路径 ∈ 页面表"][0] == "FAIL", bad
    assert "/nowhere" in bad["goto 路径 ∈ 页面表"][1]

    ok = levels(CASE_GOOD.replace(
        "  - click home-cta-btn          # 点击主操作按钮",
        "  - goto /projects/p-1         # 子路径前缀命中 /projects\n"
        "  - click home-cta-btn          # 点击主操作按钮"))
    assert ok["goto 路径 ∈ 页面表"][0] == "PASS", ok



def test_goto_missing_path_and_auth_whitelist() -> None:
    """契约 §5.5/§5.7（2026-09-30，审查 D3/D4）：`goto` 缺路径参数 FAIL；
    `auth` 白名单外 FAIL（文本期挡 + 生成器中止双保险）。
    """
    def levels(case: str) -> dict[str, tuple[str, str]]:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mk_prototype(root)
            mk_cases(root, case)
            mk_index(root)
            return {c["check"]: (c["level"], c["detail"]) for c in ve.validate(root).checks}

    miss = levels(CASE_GOOD.replace(
        "  - click home-cta-btn          # 点击主操作按钮",
        "  - goto                        # 缺路径参数\n"
        "  - click home-cta-btn          # 点击主操作按钮"))
    assert miss["goto 路径 ∈ 页面表"][0] == "FAIL", miss
    assert "<缺路径>" in miss["goto 路径 ∈ 页面表"][1]

    bad_auth = levels(CASE_GOOD.replace(
        "id: E2E-HOME-001", "auth: cookie\nid: E2E-HOME-001"))
    assert bad_auth["auth 取值合法"][0] == "FAIL", bad_auth
    assert "cookie" in bad_auth["auth 取值合法"][1]

    ok = levels(CASE_GOOD.replace(
        "id: E2E-HOME-001", "auth: none\nid: E2E-HOME-001"))
    assert ok["auth 取值合法"][0] == "PASS", ok


# ---- AC 反向覆盖（追溯门，契约 §8.2；`3509 §B186-2`）----

def _demo_prd_single_ac() -> str:
    """`PRD_DEMO` 去掉 `AC-HOME-999` 行 ⇒ 域内只剩索引已覆盖的那条 AC。"""
    text = PRD_DEMO.format(ac="AC-HOME-001", rows="| `AC-HOME-001` | 纯渲染构成，页面初值即终态 |")
    return re.sub(r"^\|.*AC-HOME-999.*\|\n", "", text, flags=re.M)


def test_index_ac_reverse_coverage_warns_on_implemented_domain() -> None:
    """`3509 §B186-2`：域内页面全 `已实现`，而域级 §五 定义的 `AC-HOME-999` 无任何用例
    `关联AC` 指向 ⇒ 追溯门 **WARN** 且清单指名到域与 AC。

    变异证明：删掉本判据或把覆盖集算反 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD)
        mk_index(root, _with_page_table("已实现"))
        mk_prd(root)
        res = ve.validate(root)
        row = [c for c in res.checks if c["check"] == "AC 反向覆盖"][0]
        assert row["level"] == "WARN", row
        assert "demo" in row["detail"] and "AC-HOME-999" in row["detail"], row


def test_index_ac_reverse_coverage_pass_when_all_covered() -> None:
    """域内每条 AC 都被 ≥1 条 `关联AC` 指向 ⇒ PASS（门不是恒红：全覆盖时必须闭嘴）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD)
        mk_index(root, _with_page_table("已实现"))
        mk_prd_raw(root, FM_GLOBAL + PRD_GLOBAL, FM_DOMAIN + _demo_prd_single_ac())
        res = ve.validate(root)
        row = [c for c in res.checks if c["check"] == "AC 反向覆盖"][0]
        assert row["level"] == "PASS", row


def test_index_ac_reverse_coverage_skips_unimplemented_domain() -> None:
    """同一缺口，页面表 `实现中` ⇒ 该域不参与（用例尚未长出，不是缺口）⇒ 不 WARN。

    分级沿用 §8.1 testid 门先例；变异证明：把分级改成「一律严判」⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD)
        mk_index(root, _with_page_table("实现中"))
        mk_prd(root)
        res = ve.validate(root)
        row = [c for c in res.checks if c["check"] == "AC 反向覆盖"][0]
        assert row["level"] == "PASS", row


# ---- 域间依赖：`depends_on` ⇔ 全局 §五 mermaid 实线边集（`3509 §B186-1`）----

def _mk_dep(root: Path, demo_dep: str, edges: str) -> None:
    """两份域级 PRD（upstream / demo）+ 全局 §五 mermaid：只喂本判据所需的最小面。"""
    d = root / "product" / "prd"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prd.md").write_text(
        FM_GLOBAL + "# 全局 PRD\n\n## 五、功能架构\n\n```mermaid\nflowchart LR\n"
        + edges + "\n```\n", encoding="utf-8")
    for slug, name, code, dep in (("upstream", "上游域", "UP", ""),
                                  ("demo", "演示域", "DEMO", demo_dep)):
        (d / f"{slug}-prd.md").write_text(
            f"---\ndoc: prd-domain\ndomain: {slug}\ndomain_name: {name}\ndomain_code: {code}\n"
            f"version: 1.0\ndate: 2026-10-04\nstatus: final\ndepends_on: [{dep}]\n---\n\n# {name}\n",
            encoding="utf-8")


def _dep_check(root: Path) -> dict:
    return [c for c in vpr.validate(root).checks if c["check"] == "参数4 域间依赖"][0]


def test_prd_depends_on_solid_aligned_pass_and_dashed_ignored() -> None:
    """`depends_on` == §五 实线推导的上游集 ⇒ PASS；**虚线（数据回流）不入判据**。

    变异证明：把实线正则改成同时吃 `-.->` ⇒ 本用例红（upstream 会被要求 depends_on=[demo]）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk_dep(root, "upstream", "  UP[上游域] --> DM[演示域]\n  DM -.-> UP")
        row = _dep_check(root)
        assert row["status"] == "PASS", row


def test_prd_depends_on_dangling_fails() -> None:
    """指向域清单外的名字 ⇒ FAIL 且指名（悬空引用让「依赖序」不可用）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk_dep(root, "upstream, ghost-domain", "  UP[上游域] --> DM[演示域]")
        row = _dep_check(root)
        assert row["status"] == "FAIL", row
        assert "悬空引用" in row["detail"] and "ghost-domain" in row["detail"], row


def test_prd_depends_on_mismatch_solid_edges_fails() -> None:
    """§五 有实线 `UP --> DM` 而 `demo` 的 `depends_on` 为空 ⇒ FAIL（三处表达漂移的机器面）。

    变异证明：删掉本判据 ⇒ 本用例红。2026-10-04 实测收敛前 5/7 域即此形态。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk_dep(root, "", "  UP[上游域] --> DM[演示域]")
        row = _dep_check(root)
        assert row["status"] == "FAIL", row
        assert "与实线边集不一致" in row["detail"] and "demo" in row["detail"], row


def test_prd_depends_on_solid_cycle_fails() -> None:
    """实线子图成环 ⇒ FAIL 并给出环路径（成环 ⇒ 父任务铺设顺序无解）。

    变异证明：去掉成环判据 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk_dep(root, "upstream", "  UP[上游域] --> DM[演示域]\n  DM --> UP")
        row = _dep_check(root)
        assert row["status"] == "FAIL", row
        assert "实线成环" in row["detail"], row


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"{'FAIL' if failed else 'PASS'} ({len(tests) - failed}/{len(tests)})")
    return 1 if failed else 0


def test_e2e_index_delta_form_gate() -> None:
    """契约 §5.5 / §8.2（P5，2026-10-07）：`delta` 相对断言的**形态门** ——
    正例放行（校验器 + 生成器两侧：只测一侧就是 `§B48` 的成因）；值形态（无符号整数）、
    与 `initial:` 豁免通道叠写、无 `step` 用例 ⇒ **FAIL** 且指名形态。
    """
    # 正例：校验器放行（`delta` 已入断言词表）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk_prototype(root)
        mk_cases(root, CASE_GOOD.replace("- text home-title 首页", "- delta home-title +1"))
        mk_index(root)
        mk_stub(root)
        res = ve.validate(root)
        row = {c["check"]: c for c in res.checks}.get("delta 相对断言形态")
        assert row is not None and row["level"] == "PASS", res.checks
    # 反例两态：值形态 / 叠写 —— 各自 FAIL 且指名（缺 step 由「分片块字段齐」门承接——
    # step 必填非空，空 step 分片进不了本循环；生成器侧的中止在 test_gen_e2e_scripts 验）
    for line, kw in (
        ("- delta home-title 3", "值形态"),
        ("- initial: delta home-title +1", "叠写"),
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mk_prototype(root)
            mk_cases(root, CASE_GOOD.replace("- text home-title 首页", line))
            mk_index(root)
            mk_stub(root)
            res = ve.validate(root)
            row = {c["check"]: c for c in res.checks}.get("delta 相对断言形态")
            assert row is not None and row["level"] == "FAIL" and kw in row["detail"], row


if __name__ == "__main__":
    sys.exit(main())


# ---- 跨页终态断言落首列页（P11，契约 §5.6 R10；2026-10-06）----


def test_cross_page_terminal_assertion_must_target_lead_page(tmp_path: Path) -> None:
    """R10 机器门：多页用例的无锚终态断言，其 testid 须归属 pages 首列。

    空洞真实证形态（steps 终点在他页、断言打回首列页之外）⇒ FAIL；
    回跳修复（断言 testid 归属首列页）⇒ PASS。变异证明：摘掉本门 ⇒ 空洞真形态放行。
    """
    root = tmp_path
    e2e = root / "product" / "e2e"
    (e2e / "cases").mkdir(parents=True)
    index = e2e / "e2e-index.md"
    index.write_text(
        "# 索引\n\n"
        "| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| E2E-A-001 | a | 跨页用例 | acceptance | AC-A-001 |  | red |  | cases/a.md#e2e-a-001 |\n\n"
        "## 页面表（页 ↔ 路由）\n\n"
        "| 页面 | 路由 | 域 | 实现状态 |\n|---|---|---|---|\n"
        "| a | /a | dom | 已实现 |\n| b | /b | dom | 已实现 |\n\n"
        "## 页面 ↔ 用例\n\n| 页面 | 断言落点用例 | 链路经过用例 |\n|---|---|---|\n"
        "| a | E2E-A-001 |  |\n| b |  |  |\n",
        encoding="utf-8")
    bad = (
        "## E2E-A-001 跨页\n\n```atlas-case\n"
        "id: E2E-A-001\nintent: 删除后回跨页核对卡片不再出现（断言对象在首列页）\n"
        "pages:\n- a\n- b\nprecondition:\n- 已登录\n"
        "step:\n- goto /a\n- click x-del-btn\n- goto /b\n"
        "expected:\n- hidden a-card-1\ntestid:\n- a-card-1\n```\n")
    (e2e / "cases" / "a.md").write_text(bad, encoding="utf-8")
    (root / "frontend").mkdir()
    (root / "frontend" / "a.tsx").write_text(
        '<div data-testid="a-card-1" /><button data-testid="x-del-btn" />'
        '<div data-testid="b-page" />', encoding="utf-8")
    (root / "product" / "stack-profile.yaml").write_text(
        "product: t\napps:\n  - name: web\n    path: frontend\n    kind: frontend\n"
        "    role: landing\n    stack: x\n", encoding="utf-8")
    res = ve.validate(root)
    row = {c["check"]: c for c in res.checks}.get("跨页终态断言落首列页")
    assert row is not None and row["level"] == "FAIL", res.checks
    assert "a-card-1" in row["detail"], row

    # 回跳修复形态：断言 testid 归属首列页 ⇒ PASS
    good = bad.replace("- goto /b\nexpected:\n- hidden a-card-1",
                       "- goto /b\n- goto /a\nexpected:\n- hidden a-card-1")
    (e2e / "cases" / "a.md").write_text(good, encoding="utf-8")
    res2 = ve.validate(root)
    row2 = {c["check"]: c for c in res2.checks}.get("跨页终态断言落首列页")
    assert row2 is not None and row2["level"] == "PASS", res2.checks
