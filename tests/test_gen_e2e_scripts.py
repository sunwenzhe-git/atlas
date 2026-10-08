#!/usr/bin/env python3
"""atlas E2E 脚本生成器（G1/D68）回归测试。

    python3 atlas/tests/test_gen_e2e_scripts.py
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import json
import tempfile
from pathlib import Path

import re

PKG_ROOT = Path(__file__).resolve().parents[1]
GEN = PKG_ROOT / "scripts" / "gen_e2e_scripts.py"

PROFILE = """product: demo
apps:
  - name: app
    path: app
    kind: frontend
    role: landing
    stack: demo
prototype:
  dir: product/prototype
  base_url: http://127.0.0.1:4173
e2e:
  runner: python-playwright
  cases_dir: product/e2e/cases
  index: product/e2e/e2e-index.md
  scripts_dir: product/e2e/scripts
  app_base_url: http://127.0.0.1:8000
  # 取证配置（3509 §B101）：值故意不同于任何真实项目字面量——生成器若回潮硬编码即红
  app_login:
    endpoint: /test-login
    username_field: login_name
    password_field: login_pass
    token_key: session_token
    storage_key: app_session
"""

CASE = """# home 页面用例

## E2E-HOME-001 首页主操作可见

```atlas-case
id: E2E-HOME-001
intent: 打开首页后主操作按钮可点击且标题文案为「首页」
pages:
  - home
precondition:
  - 已打开首页
step:
  - click home-cta-btn          # 点击主操作按钮
expected:
  - text home-title 首页        # 页面标题文案为「首页」
  - visible home-cta-btn        # 主操作按钮可见
testid:
  - home-cta-btn
  - home-title
```
"""


def run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GEN), "--root", str(root), *extra],
        capture_output=True, text=True,
    )


INDEX = """# E2E 索引

| 页面 | 路由 | 域 |
|---|---|---|
| home | /home | home |

| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |
|---|---|---|---|---|---|---|---|---|
| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | | [cases/home.md#e2e-home-001](cases/home.md#e2e-home-001) |
"""


DOWNLOAD_CASE = CASE.replace(
    "  - click home-cta-btn          # 点击主操作按钮",
    "  - download home-cta-btn *.txt  # 触发导出并校验文件名模式",
)


def write_review(root: Path, ring: str, dirname: str, status: str,
                 level: str = "Critical") -> Path:
    """写一份符合 `shared/independent-review.md` §3 形态的审查报告。"""
    d = root / "product" / ring / "reviews" / dirname
    d.mkdir(parents=True, exist_ok=True)
    checks = ([] if status != "FAIL" else
              [{"id": "D1", "level": level, "check": "可证伪性",
                "target": "E2E-HOME-001", "detail": "fixture", "rollback": "e2e"}])
    (d / "review.json").write_text(json.dumps(
        {"ok": status != "FAIL", "status": status, "root": str(root),
         "scope": "fixture", "checks": checks, "other": []},
        ensure_ascii=False), encoding="utf-8")
    (d / "README.md").write_text("# 审查总结\n\n通过\n", encoding="utf-8")
    return d


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_e2e_scripts_under_test", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make(root: Path, profile: str = PROFILE, case: str = CASE, index: str = INDEX,
         review: bool = True) -> None:
    (root / "product" / "prototype").mkdir(parents=True, exist_ok=True)
    (root / "product" / "e2e" / "cases").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(profile, encoding="utf-8")
    (root / "product" / "prototype" / "home.html").write_text("<html></html>", encoding="utf-8")
    (root / "product" / "e2e" / "cases" / "home.md").write_text(case, encoding="utf-8")
    (root / "product" / "e2e" / "e2e-index.md").write_text(index, encoding="utf-8")
    if review:
        # 独立审查门（契约 §7.1 / §12.6）：`--apply` 前必须有「存在 + 无 Critical」的报告。
        # 夹具提供一份 PASS 报告 —— 相当于「这个项目已经审过」。
        write_review(root, "e2e", "2026-01-01-fixture", "PASS")


def test_seed_lines_emit_hook_calls_and_warn_without_channel() -> None:
    """契约 §5.7（2026-09-28）：`seed:` 行 → `_seed(page, 实体, 字段)` 调用；未声明通道 ⇒ **生成期 WARN**。

    变异 M17：摘掉 `py_case` 的 seed 发射 ⇒ 第一侧红。
    """
    case = CASE.replace("testid:\n",
                        "seed:\n  - upsert bgm-library name=片头曲 duration=30\ntestid:\n")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "WARN" in r.stderr and "e2e.seed.hook" in r.stderr, r.stderr
        gen = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert "_seed(page, 'bgm-library', {'name': '片头曲', 'duration': '30'})" in gen, gen[:1200]
        # 声明了通道 ⇒ 不再 WARN（段存在 = 合法；项目自定实现）
        make(root, case=case, profile=PROFILE.replace(
            "e2e:\n", "e2e:\n  seed:\n    hook: product/e2e/scripts/_support/seed.py\n"))
        r2 = run(root, "--apply")
        assert "e2e.seed.hook" not in r2.stderr, r2.stderr


def test_auth_none_emits_marker_and_conftest_filters_preset() -> None:
    """契约 §5.7（2026-09-30）：`auth: none` → 用例挂 `atlas_auth_none` marker，
    conftest 的 page fixture 剥预置 `storageState`；缺省（preset）不挂 marker。
    变异 M26：摘掉 marker 发射 ⇒ 第一断言红；摘掉 fixture 过滤 ⇒ 第二断言红。
    """
    case_none = CASE.replace("id: E2E-HOME-001", "auth: none\nid: E2E-HOME-001")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case_none)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        gen = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert "@pytest.mark.atlas_auth_none" in gen, gen[:800]
        conftest = (root / "product" / "e2e" / "scripts" / "conftest.py").read_text(encoding="utf-8")
        assert 'get_closest_marker("atlas_auth_none")' in conftest
        assert 'addinivalue_line' in conftest  # marker 注册（审查 D3：消 UnknownMark 噪声）
        assert conftest.count("def pytest_configure") == 1  # 复审 D3 Major：防双定义遮蔽
        assert 'k not in ("storage_state", "storageState")' in conftest  # 双键名（审查 D3 修正）
        # 缺省 preset：不挂 marker（同一夹具重跑，覆盖式生成）
        make(root, case=CASE)
        r2 = run(root, "--apply")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        gen2 = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert "@pytest.mark.atlas_auth_none" not in gen2


def test_auth_unknown_value_aborts() -> None:
    """契约 §5.7（2026-09-30）：`auth` 取值白名单外 ⇒ 生成器**中止**（不猜、不静默降级）。"""
    case_bad = CASE.replace("id: E2E-HOME-001", "auth: cookie\nid: E2E-HOME-001")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case_bad)
        r = run(root, "--apply")
        assert r.returncode != 0
        assert "auth" in (r.stderr + r.stdout)


def test_blocked_case_emits_skip_from_index_status() -> None:
    """契约 §7（2026-09-30）：状态真相源 = 索引——blocked/skipped 用例发
    `pytest.mark.skip`（原因 = 状态原因列），green/red 照常生成。
    变异 M28：摘掉 skip 发射 ⇒ blocked 用例被真跑成红（假红复活）。
    """
    index = INDEX.replace(
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |",
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | blocked | BLOCKED_DEP：依赖域未实现 |")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, index=index)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        gen = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert "@pytest.mark.skip" in gen and "BLOCKED_DEP" in gen, gen[:800]


def test_zero_step_baseline_emitted_before_cases() -> None:
    """契约 §5.6 R9（2026-09-30 补）：基线 = 「未执行任何 step 的初始态」观测，
    emission order = pytest 执行序 ⇒ 基线必须定义在用例**之前**（真栈时代用例
    持久化改库状态，基线后跑会把前序改态误判成初始态恒真——config 批实测）。
    变异 M29：改回尾部拼接 ⇒ 顺序断言红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        gen = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert gen.index("def test_home__zero_step_baseline") < gen.index("def test_e2e_home_001"), \
            "基线必须在用例之前定义"


NODE_INDEX = INDEX  # 同一索引形态
NODE_PROFILE = PROFILE.replace("runner: python-playwright", "runner: node-playwright")


def _gen_node(*, case: str = CASE, index: str = NODE_INDEX, profile: str = NODE_PROFILE):
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        make(r, profile=profile, case=case, index=index)
        res = run(r, "--apply")
        scripts = r / "product" / "e2e" / "scripts"
        texts = {p.name: p.read_text(encoding="utf-8") for p in scripts.glob("*.spec.ts")}
        cfg = (scripts / "playwright.config.ts").read_text(encoding="utf-8") if (scripts / "playwright.config.ts").is_file() else ""
        setup_ts = (scripts / "atlas-auth.setup.ts").read_text(encoding="utf-8") if (scripts / "atlas-auth.setup.ts").is_file() else ""
        return res, texts, cfg, setup_ts


def test_node_runner_emits_skip_baseline_first_and_setup() -> None:
    """契约 §B48 / #153（2026-09-30 拉平）：node 运行器与 python 面同机制——
    blocked 发 test.skip；零步基线定义在用例之前；生成 atlas-auth.setup.ts +
    setup 项目（storageState 预置登录）。变异 M31：摘掉任一发射 ⇒ 对应断言红。
    （2026-10-01 契约 §7：blocked 用例不进基线探针 ⇒ 夹具含一 active 用例承载基线；
    全 blocked 页无基线 = 合法，由 `test_zero_step_baseline_excludes_blocked_cases` 钉住。）
    """
    case = CASE + """
## E2E-HOME-002 blocked 用例

```atlas-case
id: E2E-HOME-002
intent: 合法不可跑的用例
pages:
  - home
precondition:
  - 已打开首页
step:
  - click home-cta-btn          # 点击主操作按钮
expected:
  - hidden home-modal           # 未实现面板内元素
testid:
  - home-cta-btn
  - home-modal
```
"""
    index = NODE_INDEX  # E2E-HOME-001 = red（active）；002 不在索引 ⇒ 生成期报缺失，故须登记
    index = index.replace(
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |",
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |\n"
        "| E2E-HOME-002 | home | blocked 用例 | smoke | AC-HOME-002 | | blocked | BLOCKED_DEP：x |")
    r, texts, cfg, setup_ts = _gen_node(case=case, index=index)
    assert r.returncode == 0, r.stdout + r.stderr
    home = texts.get("home.spec.ts")
    assert home is not None, texts
    assert "test.skip(" in home and "BLOCKED_DEP" in home, home[:600]
    # 基线必须先于用例（真栈改态防误判恒真）：基线标题位置 < 首个用例发射位置
    bpos = home.find("test('test_home__zero_step_baseline'")
    cpos = min(x for x in (home.find('test("E2E-'), home.find("test.skip(")) if x != -1)
    assert 0 < bpos < cpos, (bpos, cpos)
    assert "atlasZeroStepBaseline" in home
    assert "home-modal" not in home.split("test_home__zero_step_baseline")[1].split("test(")[0], \
        "blocked 用例断言混进了基线"  # 契约 §7（2026-10-01）
    # setup 项目 + 预置登录
    assert "name: 'setup'" in cfg and "storageState" in cfg, cfg
    assert "ATLAS_APP_USER" in setup_ts and "atlas auth setup" in setup_ts, setup_ts[:400]


def test_node_auth_none_wraps_describe_with_clean_storage() -> None:
    """契约 §5.7（2026-09-30 拉平）：node 侧 auth:none ⇒ describe 包裹 + 空 storageState 覆盖。
    变异 M32：摘掉包裹 ⇒ 未登录前提用例在 node 上带预置登录态跑（假绿通道）。
    """
    case = CASE.replace("id: E2E-HOME-001", "auth: none\nid: E2E-HOME-001")
    r, texts, _cfg, _setup = _gen_node(case=case)
    assert r.returncode == 0, r.stdout + r.stderr
    home = texts["home.spec.ts"]
    assert "test.describe('atlas auth none'" in home, home[:600]
    assert "storageState: { cookies: [], origins: [] }" in home


def test_generates_python_actions_and_asserts() -> None:
    """新契约（§7.1，2026-09-23）：产物是**操作脚本**——step 生成动作、expected 生成断言。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        script = root / "product" / "e2e" / "scripts" / "home.py"
        assert script.is_file()
        text = script.read_text(encoding="utf-8")
        assert 'page.goto("/home")' in text
        # step → 动作
        assert '_loc(page, "home-cta-btn").click()' in text, text
        # expected → 断言（不是只做存在性检查）
        assert 'inner_text().strip() == "首页"' in text, text
        assert '_visible(page, "home-cta-btn")' in text, text
        # 中文说明降为注释
        assert "# 点击主操作按钮" in text
        assert "def test_e2e_home_001(page)" in text
        compile(text, str(script), "exec")  # 生成物必须是合法 Python
        conftest = (root / "product" / "e2e" / "scripts" / "conftest.py").read_text(encoding="utf-8")
        assert "http://127.0.0.1:8000" in conftest      # baseURL（E1 单段 = e2e.app_base_url）在运行器配置
        assert "http://127.0.0.1:8000" not in text      # 用例脚本不硬编码地址
        assert (root / "product" / "e2e" / "scripts" / "_support" / "__init__.py").is_file()


def test_zero_step_baseline_expands_panels_before_probing() -> None:
    """契约 §5.6 R9（2026-09-25；2026-09-25 `§B72` 后重定向）：零步基线必须
    ① 含**面板展开**语句（`data-atlas-panel`）；② 展开必须发生在 **`hidden` 类取样的那一趟之前**。

    不展开 ⇒ 面板整体的 `hidden` 会把断言测到的东西从「**元素本身**」偷换成「**面板**」：
    面板内 `hidden X` 恒真（被误报为空转断言）。依据 `3509 §B49`。
    `§B72` 后取样分两趟：先**按真实渲染**取存在类（展开会抹掉这类真证据），
    再展开取 `hidden` 类。故本测试同时钉住**两趟的先后**。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        text = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert "[data-atlas-panel]" in text, text
        assert "e.hidden = false" in text, text
        # 顺序（数据驱动后判据落在 runner 内部）：
        # `page.goto` → 存在类取样（rendered）→ 展开面板 → `hidden` 类取样（expanded）
        goto_i = text.index('page.goto(data["url"])')
        rendered_i = text.index('"rendered", initial_true', goto_i)
        call_i = text.index("    _atlas_expand_panels(page)", goto_i)   # 定义行无缩进，故不会误锚
        expanded_i = text.index('"expanded", initial_true', call_i)
        assert goto_i < rendered_i < call_i < expanded_i, text


def test_zero_step_baseline_samples_per_verb_state() -> None:
    """契约 §5.6 R9 + §B72：**按动词分状态取样**——“`hidden` 类在展开态、存在类在真实渲染态”。

    两侧同测：① 清单里每条 probe 的 `sampling` 字段分类正确（`hidden` / `unchanged:` ⇒ `expanded`；
    其余含 `visible` / `text` / `count` / `attr` … ⇒ `rendered`）；
    ② runner 两趟都只取本趟的断言（即取样筛选真的生效，不只是写了个字段）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        case = CASE.replace(
            "  - visible home-cta-btn        # 主操作按钮可见",
            "  - visible home-cta-btn        # 主操作按钮可见\n"
            "  - hidden home-create-project-modal   # 弹窗初始关闭\n"
            "  - attr home-cta-btn data-theme dark  # 主题属性",
        )
        make(root, case=case)
        assert run(root, "--apply").returncode == 0
        script = root / "product" / "e2e" / "scripts" / "home.py"
        text = script.read_text(encoding="utf-8")
        probes = json.loads((script.parent / "_data" / "zero_step_home.json").read_text(encoding="utf-8"))["probes"]
        by_expr = {p["expr"]: p["sampling"] for p in probes}
        assert by_expr['_visible(page, "home-cta-btn")'] == "rendered", by_expr
        assert by_expr['not _visible(page, "home-create-project-modal")'] == "expanded", by_expr
        assert by_expr['_loc(page, "home-cta-btn").get_attribute("data-theme") == "dark"'] == "rendered", by_expr

        # ② 筛选真的生效：桩里 `rendered` / `expanded` 给**不同**快照 ——
        #    存在类拿的是「未展开」（面板内元素此时不可见），`hidden` 类拿的是「已展开」。
        #    一个合法用例（两条真证据）不得被报；下面两段变异各自都会让它变红。
        quiet = _run_baseline(text, _FakePage(
            visible={"home-cta-btn": False, "home-create-project-modal": False,
                     "home-title": True}, texts={"home-title": "别的东西"},
            expanded={"home-cta-btn": True, "home-create-project-modal": True,
                      "home-title": True},
        ), script)
        assert quiet is None, f"合法用例被误报：{quiet}"
        # 否定对照：真·恒真断言（文案在 rendered 态就已相等）仍必须被报出来
        noisy = _run_baseline(text, _FakePage(
            visible={"home-cta-btn": False, "home-create-project-modal": False,
                     "home-title": True}, texts={"home-title": "首页"},
            expanded={"home-cta-btn": True, "home-create-project-modal": True,
                      "home-title": True},
        ), script)
        assert noisy is not None and "text home-title 首页" in noisy, noisy


def test_zero_step_baseline_excludes_blocked_cases() -> None:
    """契约 §7（2026-10-01，projects 首跑批）：`blocked` / `skipped` 用例的断言
    **不进**零步基线探针——状态真相源 = 索引，「合法不可跑不进真跑红面」（生成语义②）
    对基线的同义延伸。否则部分实现页上，未实现面板内元素的 `hidden` 探针判真 ⇒ 基线假红
    （实测：`E2E-PROJECTS-016` 的 `hidden projects-enqueue-blocked-hint`）。
    变异对照：同一用例去掉索引状态（= 回潮旧行为）⇒ 探针必须回流。
    """
    blocked_case = CASE + """
## E2E-HOME-009 未实现面板的隐藏断言

```atlas-case
id: E2E-HOME-009
intent: 未实现面板内的元素隐藏
pages:
  - home
precondition:
  - 已打开首页
step:
  - click home-cta-btn          # 点击主操作按钮
expected:
  - hidden home-panel-x         # 未实现面板内的元素
testid:
  - home-cta-btn
  - home-panel-x
```
"""
    index = INDEX.replace(
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |",
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |\n"
        "| E2E-HOME-009 | home | 未实现面板的隐藏断言 | smoke | AC-HOME-009 | | blocked | "
        "NOT_IMPLEMENTED：面板未实现 |")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=blocked_case, index=index)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        data = json.loads((root / "product" / "e2e" / "scripts" / "_data" / "zero_step_home.json")
                          .read_text(encoding="utf-8"))
        labels = [p["label"] for p in data["probes"]]
        assert labels and all(not l.startswith("E2E-HOME-009") for l in labels), labels
        # 两侧同构：TS 版同样排除（直接调函数对照——状态缺省 = 回潮旧行为 ⇒ 探针回流）
        gen = load_generator()
        cases = [{"id": "E2E-HOME-009", "_state": "blocked", "_state_reason": "NOT_IMPLEMENTED：x",
                  "expected": ["hidden home-panel-x   # y"]}]
        assert gen.ts_zero_step_baseline("home", "/home", cases) == ""
        plain = [{"id": "E2E-HOME-009", "expected": ["hidden home-panel-x   # y"]}]
        ts_text = gen.ts_zero_step_baseline("home", "/home", plain)
        assert "E2E-HOME-009" in ts_text, ts_text[:400]
        _t, payload = gen.py_zero_step_baseline("home", "/home", cases)
        assert payload is None, payload
        _t2, payload2 = gen.py_zero_step_baseline("home", "/home", plain)
        assert payload2 and any("E2E-HOME-009" in p["label"] for p in payload2["probes"]), payload2


def test_unchanged_pre_is_sampled_right_before_the_submitting_action() -> None:
    """契约 §5.6 R9（2026-09-25 修，`3509 §B55`）：`unchanged:` 的「行动前」断言必须**贴着第一个提交性动作**采样。

    反例（修前行为）：把它放在**所有 step 之前** ⇒ 用例自带的**准备步骤**还没执行，
    目标元素可能根本不可见 ⇒ 一条**合法**用例被判「自相矛盾」。实测踩到：
    `E2E-ASSETS-003` 的 `unchanged: visible audio-assets-sfx-table`（要先切 SFX 页签）与
    `E2E-CONFIG-003` 的 `unchanged: contains config-tts-url …`（要先切 TTS 页签）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 在首个 step 之前插入一个**非提交性**的准备步骤（切页签）
        make(root, case=CASE_UNCHANGED.replace(
            "  - click home-create-submit-btn    # 空表单提交，触发校验错误",
            "  - click home-cta-btn              # 准备：先点主操作打开抽屉（非提交性）\n"
            "  - click home-create-submit-btn    # 空表单提交，触发校验错误",
        ))
        assert run(root, "--apply").returncode == 0
        text = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        pre = text.index("`unchanged:` 断言在**行动前**就不成立")
        arrange = text.index('_loc(page, "home-cta-btn").click()')
        submit = text.index('_loc(page, "home-create-submit-btn").click()')
        assert arrange < pre < submit, (
            "「行动前」采样点不对：应在准备步骤之后、提交性动作之前",
            text[max(0, pre - 300):pre + 120],
        )


def test_unknown_verb_aborts() -> None:
    """新门：step/expected 出现词表外的动词 → 中止并列出违规行，不静默降级（§5.5 / §7.1）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=CASE.replace("- click home-cta-btn", "- 点击主操作按钮"))
        r = run(root, "--apply")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "动词不在词表内" in r.stderr, r.stderr
        assert not (root / "product" / "e2e" / "scripts" / "home.py").exists()


def test_no_target_field_or_switch() -> None:
    """契约 §5.4 / §10（2026-09-23 退役）：产物里不得再有逐用例 `执行目标` 的承载物。

    原属性：契约不再有逐用例目标这一维 ⇒ 生成物里就不该有 marker（`@pytest.mark.atlas_target`）
    或目标开关（`--atlas-target`）。否则维度会从生成器一侧半复活：索引里已无该列，
    marker 只能静默缺失或写死常量（本项目实测到的就是后者：索引 44/44 `prototype`，
    而生成脚本残留 12 处 `app` marker）。

    **E1 追加（2026-09-28）**：`--target` 本身已随原型环退役——本用例同时守住「生成器
    不再有 target 实参、conftest 不再有靶场常量」。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        scripts = root / "product" / "e2e" / "scripts"
        text = (scripts / "home.py").read_text(encoding="utf-8")
        conftest = (scripts / "conftest.py").read_text(encoding="utf-8")
        assert "atlas_target" not in text, text
        assert "atlas-target" not in conftest, conftest
        assert "atlas_target" not in conftest, conftest
        assert "pytest_addoption" not in conftest, conftest
        assert "pytest_collection_modifyitems" not in conftest, conftest
        # E1：原型默认端口已退役；baseURL 唯一 = e2e.app_base_url
        assert "http://127.0.0.1:4173" not in conftest, conftest
        assert "http://127.0.0.1:8000" in conftest, conftest


def test_inline_comment_in_profile() -> None:
    """真实 profile 带行内注释（本项目 `stack-profile.yaml` 就如此）也必须能解析。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.replace(
            "  runner: python-playwright",
            "  runner: python-playwright   # python-playwright | node-playwright"))
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert (root / "product" / "e2e" / "scripts" / "home.py").is_file()


def test_idempotent() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        run(root, "--apply")
        r = run(root, "--apply", "--json")
        assert r.returncode == 0
        assert '"changed": false' in r.stdout, r.stdout


def test_dry_run_no_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        r = run(root)
        assert r.returncode == 0
        assert not (root / "product" / "e2e" / "scripts" / "home.py").exists()


def test_app_target_uses_app_base_url() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        run(root, "--apply")
        conftest = (root / "product" / "e2e" / "scripts" / "conftest.py").read_text(encoding="utf-8")
        assert "http://127.0.0.1:8000" in conftest


def test_node_runner_variant() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, PROFILE.replace("python-playwright", "node-playwright"))
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        spec = root / "product" / "e2e" / "scripts" / "home.spec.ts"
        assert spec.is_file()
        assert (root / "product" / "e2e" / "scripts" / "playwright.config.ts").is_file()
        ts = spec.read_text(encoding="utf-8")
        # node 运行器同样要生成动作与断言，不是只做存在性检查
        assert "getByTestId('home-cta-btn').click()" in ts, ts
        assert "toHaveText(\"首页\")" in ts or "toHaveText('首页')" in ts, ts


def test_app_target_without_url_reports_not_ready() -> None:
    """`3509 §B110`：前置未声明（`app_base_url: null`）⇒ **退出码 3 + 机读 `not_ready`**，与真错（2）分开。

    同一根因曾被 `atlas_check` 判成 SKIP 与 FAIL 两种结论 ⇒ 永久红门；本用例钉住「未就绪」是一等输出。
    变异：把 `return NOT_READY` 退回 `return 2` ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, PROFILE.replace("app_base_url: http://127.0.0.1:8000", "app_base_url: null"))
        r = run(root, "--apply", "--json")
        assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
        payload = json.loads(r.stdout)
        assert payload["ok"] is False and payload["not_ready"] == "app_base_url", payload
        assert "app_base_url" in payload["message"], payload
        assert not (root / "product" / "e2e" / "scripts" / "home.py").exists()


def test_conftest_declares_python_files_not_collect_hook() -> None:
    """契约 §7.1（2026-09-23 修）：收集规则走 `python_files`，不用 `pytest_collect_file` 自建 Module。

    原属性：**单条点名只跑一遍**。原实现下 pytest 的默认收集与自建 Module 各收一次，
    `<page>.py::<test>` 会被收两遍（实测 2 tests collected）——所以这里不看实现细节，
    直接在生成的工程里跑 `--collect-only` 数用例数。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        scripts = root / "product" / "e2e" / "scripts"
        conftest = (scripts / "conftest.py").read_text(encoding="utf-8")
        home = (scripts / "home.py").read_text(encoding="utf-8")
        assert 'addinivalue_line("python_files", _name)' in conftest
        assert "pytest_collect_file" not in conftest

        # 本项守的属性（2026-09-23 事故）：同一测试**不得被收集两次**。
        # 原实现额外用 `pytest_collect_file` 自建 Module，与 pytest 默认收集各收一次
        # ⇒ 显式点名一条会跑两遍（实测 `2 tests collected`）。
        # 2026-09-24 重定向：页文件现在还多一条零步基线（契约 §5.6 R9），
        # 故整文件收集数 = 文件里 `def test_` 的条数（而非写死 1）。
        single = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "home.py::test_e2e_home_001"],
            cwd=str(scripts), capture_output=True, text=True,
        )
        assert "1 test collected" in single.stdout, single.stdout + single.stderr
        whole = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=str(scripts), capture_output=True, text=True,
        )
        n_def = len(re.findall(r"^def test_", home, re.M))
        assert f"{n_def} tests collected" in whole.stdout, whole.stdout + whole.stderr
        ids = [ln.strip() for ln in whole.stdout.splitlines() if "::" in ln]
        assert len(ids) == len(set(ids)), f"同一条测试被收集两次（事故形态）：{ids}"


def test_value_asserts_require_visibility() -> None:
    """契约 §7.1（2026-09-23 补）：`text` / `contains` / `value` 须先断言元素**可见**。

    原实现只比 `inner_text()`：隐藏元素（面板未展开）照样有文本 ⇒ 假绿。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        text = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert 'assert _vis(page, "home-title").inner_text().strip() == "首页"' in text, text
        assert "def _vis(page, tid):" in text, text
        assert "loc.is_visible()" in text, text


def test_waitfor_renders_polling_assertions() -> None:
    """契约 §7.1（2026-09-25 补）：`waitFor` 必须渲染为**带轮询的断言**，不得退化为固定等待。

    固定等待在共享靶场必飘，且与断言是否成立无关 ⇒ 是新的假绿通道；
    条件式等待超时即失败、无后门。

    变异证明：把 `py_action` 的 `waitFor` 分支改为渲染 `page.wait_for_timeout(...)`
    ⇒ 本用例的「无固定等待」断言变红；把两个 `_wait_for_*` 助手删掉 ⇒ 助手断言变红。
    """
    case = CASE.replace(
        "  - click home-cta-btn          # 点击主操作按钮\n",
        "  - waitFor home-title 首页      # 等标题文案就绪（异步产出）\n"
        "  - waitFor home-cta-btn        # 等按钮可见\n",
    )
    assert case != CASE
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        script = root / "product" / "e2e" / "scripts" / "home.py"
        text = script.read_text(encoding="utf-8")
        assert '_wait_for_text(page, "home-title", "首页")' in text, text
        assert '_wait_for_visible(page, "home-cta-btn")' in text, text
        # 不得退化为固定等待 / sleep（与断言是否成立无关）
        assert "wait_for_timeout" not in text and "time.sleep" not in text, text
        # 轮询语义必须来自运行器原生断言 API
        assert "from playwright.sync_api import expect" in text, text
        assert "to_have_text(value, use_inner_text=True" in text, text
        assert "to_be_visible(timeout=timeout_ms)" in text, text
        compile(text, str(script), "exec")

        # 跨运行器守恒：node 侧同样必须渲染为**带轮询的断言**（不是固定等待）
        node_root = root / "node"
        make(node_root, PROFILE.replace("python-playwright", "node-playwright"), case=case)
        r2 = run(node_root, "--apply")
        assert r2.returncode == 0, r2.stderr + r2.stdout
        ts = (node_root / "product" / "e2e" / "scripts" / "home.spec.ts").read_text(encoding="utf-8")
        assert 'toHaveText("首页", { timeout: ATLAS_WAIT_TIMEOUT_MS, useInnerText: true })' in ts, ts
        assert "toBeVisible({ timeout: ATLAS_WAIT_TIMEOUT_MS })" in ts, ts
        assert "waitForTimeout" not in ts, ts


def test_conftest_target_constant_not_port() -> None:
    """契约 §5.4（E1 单段）：conftest 无靶场常量；登录预置只走真实登录路径。

    行为级：`_ATLAS_TARGET_IS_PROTOTYPE` / `_MOCK_NS` 已随原型环退役（生成物不得再有）；
    `_context_args` 无凭据时不注入 storage_state（走 app_login 的降级警告路径——夹具
    PROFILE 声明了 app_login 且测试用值异于任何真实项目字面量）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        scripts = root / "product" / "e2e" / "scripts"
        conftest = (scripts / "conftest.py").read_text(encoding="utf-8")
        assert "_ATLAS_TARGET_IS_PROTOTYPE" not in conftest, conftest
        assert "_MOCK_NS" not in conftest, conftest
        mod = _load_conftest(scripts / "conftest.py")
        # 无凭据 ⇒ 不注入（真实登录路径的降级分支）；端口字面量不参与判定
        assert "storage_state" not in mod._context_args({}, "http://127.0.0.1:8000"), "凭据缺 ⇒ 跳过"


def test_zero_step_baseline_covers_non_exempt_asserts() -> None:
    """契约 §5.6 R9：每页产一条零步基线，**未加 `initial:` 前缀**的断言全部进 probe 集合。

    变异证明（见本任务 `implement.md` §3）：把生成器里的 `assert not initial_true` 改成 `pass`，
    或把 `except AssertionError: return` 删掉，本用例与 `test_initial_prefix_exempts_from_baseline`
    即变红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        text = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert "def test_home__zero_step_baseline(page):" in text, text
        # 该页的基线函数**只**读清单、不执行任何 step（基线段 = 基线 def 到首个用例 def）
        baseline = text.split("def test_home__zero_step_baseline(page):", 1)[1].split("\ndef test_e2e_", 1)[0]
        assert "home-cta-btn\").click()" not in baseline, baseline
        probes = json.loads((root / "product" / "e2e" / "scripts" / "_data"
                             / "zero_step_home.json").read_text(encoding="utf-8"))["probes"]
        labels = [p["label"] for p in probes]
        assert "E2E-HOME-001: text home-title 首页" in labels, labels
        assert "E2E-HOME-001: visible home-cta-btn" in labels, labels
        # 命中即 FAIL（不得静默）
        assert "assert not problems" in text, text
        compile(text, "home.py", "exec")


CASE_UNCHANGED = """# home 页面用例

## E2E-HOME-009 取消新建后弹窗关闭且校验态不残留

```atlas-case
id: E2E-HOME-009
intent: 触发必填校验后点取消，弹窗关闭且校验错误不残留
pages:
  - home
precondition:
  - 已登录并位于 /
step:
  - click home-create-submit-btn    # 空表单提交，触发校验错误
  - click home-create-cancel-btn    # 取消
expected:
  - unchanged: hidden home-create-project-modal   # 弹窗关闭（本用例验的是该动作不改变它）
  - unchanged: hidden home-create-name-error      # 校验错误不残留
  - text home-title 首页
  - initial: visible home-project-list
  - visible home-cta-btn
testid:
  - home-create-submit-btn
  - home-create-cancel-btn
  - home-create-project-modal
  - home-cta-btn
  - home-title
  - home-create-name-error
```
"""


def test_unchanged_prefix_emits_pre_and_post_assertions() -> None:
    """契约 §5.6 R9：`unchanged:` 产出**行动前 + 行动后**两处断言（不是一条）。

    变异证明（本任务 `implement.md` §3）：把 `py_case` 里的行动前断言删掉 ⇒ 本用例变红；
    把 `py_assert` 的 `unchanged` 分支去掉（退化为普通断言）⇒「动作后」措辞消失，本用例变红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=CASE_UNCHANGED)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        text = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        pre = text.index("行动前")
        first_click = text.index('_loc(page, "home-create-submit-btn").click()')
        post = text.index("动作后")
        assert pre < first_click, "行动前断言必须在任何 step 之前"
        assert first_click < post, "行动后复断言必须在 step 之后"
        # 前缀不得作为代码泄进产物（docstring 里仍镜像分片原文，供人读）
        assert "assert unchanged:" not in text, text
        assert 'assert initial:' not in text, text
        compile(text, "home.py", "exec")


def test_unchanged_held_initially_is_not_a_hit_but_violation_is_contradiction() -> None:
    """契约 §5.6 R9 的三态判定：`unchanged:` 初始成立 = 正常；初始**不**成立 = 自相矛盾。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=CASE_UNCHANGED)
        assert run(root, "--apply").returncode == 0
        text = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        # 初始成立（弹窗确实关着）⇒ 不得报任何问题
        script = root / "product" / "e2e" / "scripts" / "home.py"
        ok = _run_baseline(text, _FakePage(
            visible={"home-create-project-modal": False, "home-cta-btn": False,
                     "home-create-name-error": False, "home-title": True},
            texts={"home-title": "别的东西"},
        ), script)
        assert ok is None, f"`unchanged:` 初始成立却被报为问题：{ok}"
        # 初始就不成立（弹窗开着）⇒ 自相矛盾告警
        bad = _run_baseline(text, _FakePage(
            visible={"home-create-project-modal": True, "home-cta-btn": False,
                     "home-create-name-error": False, "home-title": True},
            texts={"home-title": "别的东西"},
        ), script)
        assert bad is not None and "自相矛盾" in bad, bad
        assert "E2E-HOME-009: hidden home-create-project-modal" in bad, bad


def test_initial_prefix_exempts_from_baseline() -> None:
    """契约 §5.6 R9 的显式豁免通道：`initial:` 前缀的断言不参与零步基线，但仍须正常断言。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=CASE.replace(
            "- visible home-cta-btn        # 主操作按钮可见",
            "- initial: visible home-cta-btn   # 主操作按钮可见（页面骨架本就如此）"))
        r = run(root, "--apply")
        # 前缀后仍是合法动词 ⇒ 不得被动词词表拦下
        assert r.returncode == 0, r.stderr + r.stdout
        text = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        probes = json.loads((root / "product" / "e2e" / "scripts" / "_data"
                             / "zero_step_home.json").read_text(encoding="utf-8"))["probes"]
        exprs = " ".join(p["expr"] for p in probes)
        assert "home-cta-btn" not in exprs, exprs               # 已豁免，不进 probe 清单
        assert "home-title" in exprs, exprs                     # 未豁免的另一条仍在
        assert '_visible(page, "home-cta-btn")' in text, text    # 仍作为正式断言生成
        assert 'assert initial:' not in text, text

class _FakeVis:
    """替代生成物的 `_vis`：隐藏元素抛 AssertionError（与真实实现同语义）。"""

    def __init__(self, page, tid):
        self.page, self.tid = page, tid

    def inner_text(self) -> str:
        if not self.page.visible.get(self.tid):
            raise AssertionError(f"{self.tid} 不可见")
        return self.page.texts.get(self.tid, "")

    def get_attribute(self, name: str):
        """契约 §5.5 的 `attr` 动词（用 `_loc`，**不要求可见**）。

        属性未登记时返回 `None` —— 与真实 `get_attribute()` 对不存在的属性同语义，
        于是「属性不存在」与任何字符串都不相等（断言失败）。
        """
        return self.page.attrs.get((self.tid, name))


class _FakePage:
    def __init__(self, visible: dict, texts: dict | None = None, attrs: dict | None = None,
                 expanded: dict | None = None):
        self.visible, self.texts, self.attrs, self.url = dict(visible), texts or {}, attrs or {}, None
        self._expanded = dict(expanded) if expanded is not None else None

    def eval_on_selector_all(self, selector: str, expression: str):
        """零步基线的**面板展开**（契约 §5.6 R9 / `§B72`）。

        给了 `expanded` 就切到「面板已展开」的可见性快照 —— 两趟取样因此真的看到**不同状态**；
        不给时是 no-op（模拟「面板已展开后的元素自身状态」）。依据 `3509 §B49` 与 `§B72`。
        """
        if self._expanded is not None:
            self.visible = dict(self._expanded)
        return None

    def goto(self, url: str) -> None:
        self.url = url


def _run_baseline(script_text: str, page: object, script_path: Path) -> str | None:
    """抽出生成物里的零步基线（**薄函数 + header 里的 runner**），用桩全局执行。

    2026-09-25 起基线改为数据驱动：判定逻辑（`_atlas_zero_step_baseline` / `_atlas_expand_panels`）
    在页脚本 header 里，断言清单在 `_data/zero_step_<page>.json`。本桩只注入 `json` / `Path` /
    `_HERE` 与三个真实断言的替身，**不装浏览器**也能量判定语义。
    """
    i = script_text.index("def _atlas_expand_panels(page):")
    j = script_text.index("def test_", i)
    runner = script_text[i:j]
    _head, body = script_text.split("def test_home__zero_step_baseline(page):", 1)
    ns: dict = {
        "_visible": lambda p, tid: bool(p.visible.get(tid)),
        "_vis": lambda p, tid: _FakeVis(p, tid),
        "_loc": lambda p, tid: _FakeVis(p, tid),
        "_HERE": script_path.parent,
    }
    exec("import json\nfrom pathlib import Path\n" + runner, ns)
    exec("def test_home__zero_step_baseline(page):" + body, ns)
    try:
        ns["test_home__zero_step_baseline"](page)
    except AssertionError as exc:
        return str(exc)
    return None


def test_baseline_counts_by_return_value_not_by_absence_of_raise() -> None:
    """契约 §5.6 R9：判定必须看**返回值**，不能只看「没抛异常」。

    事故形态（2026-09-24 实测踩到）：`expected` 的 9 个断言动词**全部**渲染为布尔表达式，
    而 `_probe` 原来执行了表达式却丢掉返回值 ⇒ `visible audio-assets-sfx-table`
    （该元素在 `hidden` 面板里、`is_visible()` 为 False）也被计为「初始态即成立」。
    那门会变成**误报机器**：把 92 —其实是任意条— 断言一律报为恒真。

    变异证明（本任务 `implement.md` §3）：把 `if ok:` 改回「丢弃返回值、总是 append」⇒ 本用例变红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        text = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")

        # 初始态**不**成立（元素不可见 / 文案不匹配）⇒ 不得计入
        script = root / "product" / "e2e" / "scripts" / "home.py"
        quiet = _run_baseline(text, _FakePage(
            visible={"home-title": True, "home-cta-btn": False},
            texts={"home-title": "别的东西"},
        ), script)
        assert quiet is None, f"初始态不成立的断言被计为命中（误报）：{quiet}"

        # 初始态成立 ⇒ 必须逐条指名
        noisy = _run_baseline(text, _FakePage(
            visible={"home-title": True, "home-cta-btn": True},
            texts={"home-title": "首页"},
        ), script)
        assert noisy is not None, "初始态成立的断言没被抓到（漏报）"
        assert "E2E-HOME-001: text home-title 首页" in noisy, noisy
        assert "E2E-HOME-001: visible home-cta-btn" in noisy, noisy



def test_zero_step_baseline_names_every_use_of_a_same_shaped_assertion() -> None:
    """`3509 §B33`：零步基线**不得**按「断言表达式串」去重。

    旧行为：同一表达式串只探一次，label 记成 `A / B`；若**先出现**的是 `unchanged:`
    （期望方向相反），被它折叠进去的 plain 同形断言**永不点名** ⇒ 假阴性
    （实测 `E2E-LOGIN-005/006` 的 plain `visible login-page` 从未出现在任何命中清单里）。
    新行为：每条断言各自成条、label 各自带用例 ID。
    """
    two = CASE.replace("id: E2E-HOME-001",
                       "id: E2E-HOME-002").replace("# home 页面用例", "# home 页面用例")
    both = CASE + "\n" + two
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=both)
        assert run(root, "--apply").returncode == 0
        probes = json.loads((root / "product" / "e2e" / "scripts" / "_data"
                             / "zero_step_home.json").read_text(encoding="utf-8"))["probes"]
        same = [p for p in probes if p["expr"] == '_visible(page, "home-cta-btn")']
        labels = [p["label"] for p in same]
        assert len(same) == 2, f"同形断言被去重掩盖：{labels}"
        assert any("E2E-HOME-001" in x for x in labels) and any("E2E-HOME-002" in x for x in labels), labels


def test_reverse_view_regenerated_from_main_table() -> None:
    """`3509 §B64`：索引的 `## 页面 ↔ 用例` 是 100% 派生信息 ⇒ 由生成器重写。

    反向证明：先手工把该段改错，再一次 `--apply` 必须**纠正回来**（不是「只在新项目里生成一次」）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        # 夹具自带的 INDEX 无反向视图小节 ⇒ 补一段（本用例验的是「能重生成 + 能纠正手改」）
        p = root / "product" / "e2e" / "e2e-index.md"
        p.write_text(INDEX.rstrip("\n") + "\n\n## 页面 ↔ 用例\n\n"
                     "| 页面 | 断言落点用例 | 链路经过用例 |\n|---|---|---|\n"
                     "| home | E2E-HOME-999 | |\n", encoding="utf-8")
        assert run(root, "--apply").returncode == 0
        once = p.read_text(encoding="utf-8")
        assert "## 页面 ↔ 用例" in once and "E2E-HOME-001" in once.split("## 页面 ↔ 用例")[1]
        # 手工改错（模拟漏改/改错）⇒ 生成器必须纠正
        p.write_text(once.replace("| home | E2E-HOME-001", "| home | E2E-HOME-999"), encoding="utf-8")
        assert run(root, "--apply").returncode == 0
        fixed = p.read_text(encoding="utf-8")
        assert "E2E-HOME-999" not in fixed, "生成器未纠正被手改的反向视图"
        assert fixed == once, "反向视图重生成后与首次不一致（非幂等）"


# 契约 §7.1（2026-09-25 补）：§5.5 的**每一个**断言动词都必须在**两个运行器**里都有渲染
# 分支。只测一侧正是 `3509 §B48` 的成因；「python 侧补了、node 侧漏了」是同一族的下一个坑
# （实测：`countOptions` / `checked` / `unchecked` 三个动词只在 python 分支里有）。
ASSERT_SAMPLES = {
    "text": "home-title 首页",
    "contains": "home-title 首页",
    "count": "home-cta-btn 2",
    "countOptions": "home-cta-btn 9",
    "visible": "home-cta-btn",
    "hidden": "home-cta-btn",
    "enabled": "home-cta-btn",
    "disabled": "home-cta-btn",
    "checked": "home-cta-btn",
    "unchecked": "home-cta-btn",
    "value": "home-cta-btn 首页",
    "attr": "home-cta-btn data-theme dark",
    "delta": "home-title +1",
}


def _load_gen():
    spec = importlib.util.spec_from_file_location("atlas_gen_under_test", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_assert_verb_renders_in_both_runners() -> None:
    """契约 §7.1（2026-09-25 补，`3509 §B48` 的同族第二面）：

    ① 词表里出现新动词而没有样例 ⇒ 红（逼作者为**两个**运行器都想清楚渲染）；
    ② 样例表与词表不一致（少了已退役动词 / 多了未登记动词）⇒ 红；
    ③ 每个动词在 python 侧与 node 侧都要渲染成功（未知动词会 `raise ValueError`）。
    """
    gn = _load_gen()
    assert set(gn.ASSERT_VERBS) == set(ASSERT_SAMPLES), (
        f"词表与样例表不一致: 新动词={sorted(set(gn.ASSERT_VERBS) - set(ASSERT_SAMPLES))} "
        f"多余样例={sorted(set(ASSERT_SAMPLES) - set(gn.ASSERT_VERBS))}"
    )
    for verb, rest in ASSERT_SAMPLES.items():
        line = f"{verb} {rest}"
        gn.py_assert_expr(line)  # ③-a python 分支
        case = {
            "id": "E2E-HOME-001",
            "_title": "首页主操作可见",
            "step": ["goto /"],
            "expected": [line],
            "testid": ["home-cta-btn", "home-title"],
        }
        spec = gn.ts_case(case, "/")  # ③-b node 分支（认不得就 raise）
        assert "home-cta-btn" in spec or "home-title" in spec, (verb, spec)


def test_value_and_attr_keep_same_semantics_in_both_runners() -> None:
    """跨运行器**语义**守恒（不止「不报错」）：`value` 的空值写法与 `attr` 的属性比对，
    两个运行器必须表达同一件事。

    取证：`_support` 之外的用例语料里 `value … ""` 已被使用（「清除选区后为空」类），
    而 node 侧若不把 `""` / `(空)` 映射为空串，会渲染成 `toHaveValue('""')`（两个引号
    字符），与真实空串永不相等 —— 与 `3509 §B48` 同属「一侧能跑、另一侧认不得/认错」。
    """
    gn = _load_gen()

    def ts(line: str) -> str:
        case = {
            "id": "E2E-HOME-001",
            "_title": "首页主操作可见",
            "step": ["goto /"],
            "expected": [line],
            "testid": ["home-cta-btn"],
        }
        return gn.ts_case(case, "/")

    out = ts('value home-cta-btn ""')
    # B173-1：value 断言经 atlasExpectValue 实现无关化；空值仍渲染成真实空串实参
    assert 'atlasExpectValue(page, \'home-cta-btn\', "");' in out, out
    assert 'toHaveValue(\'""\')' not in out, out
    assert gn.py_assert_expr('value home-cta-btn ""')[0] == '_value_of(page, "home-cta-btn") == ""'

    out = ts("attr home-cta-btn data-theme dark")
    assert 'toHaveAttribute("data-theme", "dark")' in out, out
    assert gn.py_assert_expr("attr home-cta-btn data-theme dark")[0] == (
        '_loc(page, "home-cta-btn").get_attribute("data-theme") == "dark"'
    )


def test_select_and_value_are_implementation_agnostic() -> None:
    """契约 §5.5（B173-1，2026-10-04）：select 动词与 value 断言/探针**不得绑定原生 DOM**。

    背景：`selectOption` / `inputValue` 只作用于原生 `<select>` / 表单元素 ⇒ 组件实现
    被 E2E 应然逼死（Radix/shadcn Select 装不上；polyvoice /projects 七个下拉框实证）。
    用户判定「E2E 怎么可能会要求组件怎么实现」⇒ 发射器改出实现无关 helper：按元素
    tagName 自适应 —— 原生走原路径，否则视作 trigger+listbox 组合。三个运行器面
    （TS 动作 / TS 探针 / python）同判，`3508 §173` 纪要。
    """
    gn = _load_gen()
    # 用例体级：动作与断言都经实现无关 helper（helper 本体在页面 header，整文件级再验）
    spec = gn.ts_case(
        {
            "id": "E2E-HOME-001",
            "_title": "首页主操作可见",
            "step": ["select home-cta-btn 首页"],
            "expected": ["value home-cta-btn 首页"],
            "testid": ["home-cta-btn"],
        },
        "/",
    )
    assert "await atlasSelect(page, 'home-cta-btn'" in spec, spec
    assert "await atlasExpectValue(page, 'home-cta-btn'" in spec, spec
    # 探针（ts_assert_expr 与正式用例同源）也走 atlasValueOf，三态语义不变（不可见 ⇒ null）
    expr = gn.ts_assert_expr("value home-cta-btn 首页")
    assert "atlasValueOf(page" in expr, expr
    assert expr.endswith("return x === null ? null : x === \"首页\"; })()"), expr
    # python 侧同构：断言经 _value_of，动作经 _select（渲染分支存在）
    assert gn.py_assert_expr("value home-cta-btn 首页")[0] == '_value_of(page, "home-cta-btn") == "首页"'
    gn.py_action("select home-cta-btn 首页")
    # 整文件级：三件 helper 必须落在页面 header（与用例体同文件，node 侧运行期才不报未定义）
    case_text = CASE.replace(
        "  - click home-cta-btn          # 点击主操作按钮",
        "  - select home-cta-btn 首页    # B173-1：实现无关 select",
    ).replace(
        "  - text home-title 首页        # 页面标题文案为「首页」",
        "  - value home-cta-btn 首页     # B173-1：实现无关 value",
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case_text, profile=NODE_PROFILE)
        assert run(root, "--apply").returncode == 0
        ts = (root / "product" / "e2e" / "scripts" / "home.spec.ts").read_text(encoding="utf-8")
        assert "await atlasSelect(page, 'home-cta-btn'" in ts, ts
        assert "await atlasExpectValue(page, 'home-cta-btn'" in ts, ts
        for frag in (
            "async function atlasSelect(",
            "async function atlasValueOf(",
            "async function atlasExpectValue(",
        ):
            assert frag in ts, (frag, ts[:2000])


def test_download_renders_register_then_click_in_both_runners() -> None:
    """契约 §5.5 / §7.1（`3509 §B26`）：`download` 属**动作**，必须渲染为「**先注册下载监听 →
    再点击 → 校验建议文件名**」—— 下载是动作的副作用，事后无法补取证；只点击、或固定等待、
    或只点击不校验，都是把「下载发生过」这件事丢掉。两个运行器同义；glob 语义两侧一致。
    """
    gn = _load_gen()
    assert gn.py_action("download projects-export-prompt-btn *.txt") == (
        '_download(page, "projects-export-prompt-btn", "*.txt")'
    )
    case = {
        "id": "E2E-HOME-001",
        "_title": "导出并校验文件名",
        "step": ["goto /", "download projects-export-prompt-btn *.txt"],
        "expected": ["visible home-cta-btn"],
        "testid": ["projects-export-prompt-btn", "home-cta-btn"],
    }
    assert "await atlasDownload(page, 'projects-export-prompt-btn', \"*.txt\");" in gn.ts_case(case, "/")

    # 反向证据：缺文件名 glob 参数 ⇒ 两侧都报错（不得静默退化为「只点击」）
    for call in (
        lambda: gn.py_action("download projects-export-prompt-btn"),
        lambda: gn.ts_case({**case, "step": ["download projects-export-prompt-btn"]}, "/"),
    ):
        try:
            call()
        except ValueError as exc:
            assert "glob" in str(exc), exc
        else:  # pragma: no cover
            raise AssertionError("`download` 缺 glob 参数未报错")

    # 端到端：两侧生成物里都必须有「注册监听 → 点击 → 校验」的固定形状
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, PROFILE, case=DOWNLOAD_CASE)
        assert run(root, "--apply").returncode == 0
        py = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
    assert "with page.expect_download(" in py, py
    assert "fnmatch.fnmatch(_name, pattern)" in py, py
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, PROFILE.replace("python-playwright", "node-playwright"), case=DOWNLOAD_CASE)
        assert run(root, "--apply").returncode == 0
        ts = (root / "product" / "e2e" / "scripts" / "home.spec.ts").read_text(encoding="utf-8")
    assert "page.waitForEvent('download'" in ts, ts
    assert "download.suggestedFilename()" in ts, ts
    # glob→regex 的转义助手必须在**同一份生成物**里（否则 node 侧运行期报未定义）
    assert "function atlasGlob(pattern)" in ts and "atlasGlob(pattern)" in ts, ts


# 契约 §7.1（2026-09-25 补）：§5.5 的**每一个**动作动词也必须在两个运行器里都有渲染分支
# （与断言动词同一道守恒门；只测一侧就是 `3509 §B48` 的成因）。
ACTION_SAMPLES = {
    "click": "home-cta-btn",
    "fill": "home-title 首页",
    "select": "home-title 首页",
    "check": "home-cta-btn",
    "uncheck": "home-cta-btn",
    "press": "home-cta-btn Enter",
    "hover": "home-cta-btn",
    "refresh": "",
    "goto": "/home",
    "waitFor": "home-cta-btn",
    "download": "home-cta-btn *.txt",
}


def test_every_action_verb_renders_in_both_runners() -> None:
    """契约 §7.1：动作动词的逐项守恒（与断言动词同口径）。"""
    gn = _load_gen()
    assert set(gn.ACTION_VERBS) == set(ACTION_SAMPLES), (
        f"词表与样例表不一致: 新动词={sorted(set(gn.ACTION_VERBS) - set(ACTION_SAMPLES))} "
        f"多余样例={sorted(set(ACTION_SAMPLES) - set(gn.ACTION_VERBS))}"
    )
    for verb, rest in ACTION_SAMPLES.items():
        line = verb if not rest else f"{verb} {rest}"
        gn.py_action(line)  # python 分支
        case = {
            "id": "E2E-HOME-001",
            "_title": "首页主操作可见",
            "step": [line],
            "expected": ["visible home-cta-btn"],
            "testid": ["home-cta-btn"],
        }
        spec = gn.ts_case(case, "/")  # node 分支（认不得就 raise）
        assert "home-cta-btn" in spec, (verb, spec)


def test_step_anchor_emits_assertion_after_that_step() -> None:
    """契约 §5.5（2026-09-25 补，`3509 §B57`）：`after:<N>` 的断言必须发射在**第 N 条 step 之后**、
    终态断言之前；且它**不属豁免通道** —— 要进零步基线（与 `initial:` 的完全豁免相对）。
    两侧（python / node）同测。
    """
    case = CASE.replace(
        "  - visible home-cta-btn        # 主操作按钮可见",
        "  - after:1 visible home-cta-btn        # 点完后该按钮可见\n"
        "  - initial: hidden home-cta-btn        # 终态回到不可见（页面初值即如此）",
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case)
        assert run(root, "--apply").returncode == 0
        text = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        probes = json.loads((root / "product" / "e2e" / "scripts" / "_data"
                             / "zero_step_home.json").read_text(encoding="utf-8"))["probes"]
    click = text.index('_loc(page, "home-cta-btn").click()')
    anchored = text.index("assert _visible(page, \"home-cta-btn\")")
    terminal = text.index("assert not _visible(page, \"home-cta-btn\")")
    assert click < anchored < terminal, text
    # 步骤锚断言必须进基线（= 不是豁免通道）；`initial:` 那条不进
    exprs = " ".join(p["expr"] for p in probes)
    assert probes and all("not _visible" not in p["expr"] for p in probes), probes
    assert "assert initial:" not in text, text

    # node 侧同一顺序
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, PROFILE.replace("python-playwright", "node-playwright"), case=case)
        assert run(root, "--apply").returncode == 0
        ts = (root / "product" / "e2e" / "scripts" / "home.spec.ts").read_text(encoding="utf-8")
    c = ts.index("await page.getByTestId('home-cta-btn').click();")
    a = ts.index("await expect(page.getByTestId('home-cta-btn')).toBeVisible();")
    z = ts.index("await expect(page.getByTestId('home-cta-btn')).toBeHidden();")
    assert c < a < z, ts



def test_review_gate_blocks_apply_without_report() -> None:
    """契约 §12.6 / §7.1：报告缺失 = **未审**（不是「通过」）⇒ `--apply` 拒绝写盘。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, review=False)
        r = run(root, "--apply")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "独立审查门" in r.stderr, r.stderr
        assert not (root / "product" / "e2e" / "scripts" / "home.py").exists(), \
            "拒绝写盘必须真的不写盘"


def test_review_gate_blocks_apply_on_critical() -> None:
    """存在 `Critical`（`status == \"FAIL\"`）⇒ 同样断言 —— 带着缺陷生成脚本 = 把缺陷固定下来。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        write_review(root, "e2e", "2026-01-02-failing", "FAIL")
        r = run(root, "--apply")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "Critical" in r.stderr, r.stderr
        assert not (root / "product" / "e2e" / "scripts" / "home.py").exists()


def test_review_gate_dry_run_only_reports() -> None:
    """存在性挂在**写盘动作**上：dry-run 只报状态、不改退出码（仓库可能合法地停在半路）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, review=False)
        r = run(root, "--json")
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["review_gate"]["ok"] is False, out
        assert out["review_gate"]["reasons"], out


def test_review_gate_uses_latest_dated_report() -> None:
    """报告定位 = **目录名日期前缀最大**那份（契约 §4）——旧的 FAIL 不得把新的 PASS 压死。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        write_review(root, "e2e", "2025-12-31-old", "FAIL")
        assert run(root, "--apply").returncode == 0, "新的 PASS 应覆盖旧的 FAIL"
        write_review(root, "e2e", "2027-01-01-new", "FAIL")
        assert run(root, "--apply").returncode != 0, "更大的日期是 FAIL ⇒ 阻断"


def test_review_gate_rejects_malformed_report() -> None:
    """`review.json` 缺 / 坏 / `status` 不在词表内 ⇒ 视为**未通过**（不得默认放行）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        rj = root / "product" / "e2e" / "reviews" / "2026-01-01-fixture" / "review.json"
        rj.write_text("{ not json", encoding="utf-8")
        assert run(root, "--apply").returncode != 0
        rj.write_text(json.dumps({"ok": True, "status": "OK"}), encoding="utf-8")
        assert run(root, "--apply").returncode != 0, "词表外的 status 不得被当成通过"
        rj.unlink()
        assert run(root, "--apply").returncode != 0


def test_review_gate_levels_and_path_match_the_shared_contract() -> None:
    """**消费者守恒**：门的取值集合 / 路径形态 / 状态词表必须与契约正文逐项一致。

    「同一口径的消费者个数先数清」——本门的消费者是审查器产物（`review.json`），
    生产者（审查器）由契约 §3 声明形态。这里把两者钉在一起：
    改契约不改实现（或反之）⇒ 红。
    """
    gen = load_generator()
    shared = (PKG_ROOT / "shared" / "independent-review.md").read_text(encoding="utf-8")
    assert "{ok, status, checks[]}" in shared, "共享契约必须仍声明机读形态"
    assert 'status = "FAIL"' in shared and '\"Critical\"' in shared
    assert "product/<环>/reviews/<日期>-<范围>/" in shared
    assert gen.REVIEW_LEVELS == {"PASS", "WARN", "FAIL"}, gen.REVIEW_LEVELS
    assert gen.REVIEW_DIRNAME == "reviews"
    # 两个环契约各自声明了门禁与同一判据
    for ring in ("e2e",):
        text = (PKG_ROOT / "rings" / ring / "reference.md").read_text(encoding="utf-8")
        assert f"product/{ring}/reviews/<日期>-<范围>/" in text, ring
        assert "Critical" in text, ring


def test_assert_testids_uses_auto_wait_not_immediate_count() -> None:
    """契约 §7.1（2026-09-27 补，`3509 §B99`）：元素齐全守卫必须**自动等待**判定。

    真实应用是 SPA：`goto` 后元素异步渲染，即时 `count()` 判存在性对 app 段必红
    （实测：即时 count=0、自动等待后 testid 齐全；原型是静态 HTML 所以从未暴露）。
    守卫仍须在真缺失时**点名缺失清单**（超时即失败）——不得退化成永久等待。

    变异证明：把守卫改回即时 `count() == 0` ⇒ 本用例变红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        script = root / "product" / "e2e" / "scripts" / "home.py"
        text = script.read_text(encoding="utf-8")
        guard = text.split("def _assert_testids(page, ids):", 1)[1].split("\n\n", 1)[0]
        # 自动等待语义：运行器原生轮询断言 + 守卫超时（与 waitFor 同源默认）
        assert "expect(page.get_by_test_id(t)).to_have_count(1, timeout=_WAIT_TIMEOUT_MS)" in guard, guard
        assert "count() == 0" not in guard, guard
        # 真缺失仍点名：失败信息必须列出缺失清单
        assert 'assert not missing, f"缺少 data-testid: {missing}"' in guard, guard
        compile(text, str(script), "exec")


def _load_conftest(path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("conftest_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_conftest_app_target_real_login_preset() -> None:
    """契约 §5.4 / §7.1（2026-09-27 补，`3509 §B99`）：app 靶场以**真实登录**预置会话。

    `E2E-LOGIN-004/006` 首步 `click login-logout-btn`，注释写明「运行器预置了登录态」
    —— 只有 prototype 实现了（注入 mock 态），app 段没有 ⇒ 两条用例在真实应用上结构性不可过。
    凭据只来自运行期环境变量（不读 .env、不硬编码）；未设置 ⇒ 跳过 + 明确警告（不静默）；
    换取令牌失败（凭据错 / 连不上 / 端点变更）⇒ 报错中止（不得静默续跑成假绿）。

    变异证明：① conftest 模板的 app 分支改回「直接 return args」⇒ 本用例变红；
    ② 生成器改回硬编码端点/字段/键（不读 e2e.app_login，3509 §B101）⇒ 本用例变红
    （路径 / 表单字段 / 存储名全对不上）。
    """
    import contextlib
    import io
    import threading
    import urllib.parse
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
            form = urllib.parse.parse_qs(body)
            seen.update(path=self.path, form=form)
            if form.get("login_name", [""])[0] == "notoken":
                payload, code = b"{}", 200                       # 200 但无令牌：端点契约变更
            elif form.get("login_pass", [""])[0] == "right":
                payload, code = json.dumps({"session_token": "tok-e2e"}).encode(), 200
            else:
                payload, code = json.dumps({"detail": "login failed"}).encode(), 400
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make(root)
            assert run(root, "--apply").returncode == 0
            # 静态形态：端点 / 存储键 / 环境变量名都必须在生成物里
            conftest = (root / "product" / "e2e" / "scripts" / "conftest.py").read_text(encoding="utf-8")
            # 取证值来自 profile 的 e2e.app_login（shared/stack-profile.md §2，3509 §B101）——不是本项目字面量
            assert "'endpoint': '/test-login'" in conftest, conftest
            assert "'storage_key': 'app_session'" in conftest, conftest
            assert "'token_key': 'session_token'" in conftest, conftest
            assert 'os.environ.get("ATLAS_APP_USER")' in conftest, conftest
            assert 'os.environ.get("ATLAS_APP_PASSWORD")' in conftest, conftest
            mod = _load_conftest(root / "product" / "e2e" / "scripts" / "conftest.py")

            # 行为 ①：凭据未设置 ⇒ 跳过预置 + 明确警告（不静默）
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                args = mod._context_args({}, base, app_user=None, app_password=None)
            assert "storage_state" not in args, args
            assert "ATLAS_APP_USER" in err.getvalue(), err.getvalue()

            # 行为 ②：真实登录成功 ⇒ 令牌按前端读取的键写进 storage（origin 去尾斜杠）
            args = mod._context_args({}, base + "/", app_user="u@x", app_password="right")
            st = args["storage_state"]
            assert st["origins"][0]["origin"] == base, st
            assert st["origins"][0]["localStorage"] == [
                {"name": "app_session", "value": "tok-e2e"}], st
            assert seen["path"] == "/test-login", seen
            assert seen["form"]["login_name"] == ["u@x"], seen
            assert seen["form"]["login_pass"] == ["right"], seen

            # 行为 ③：凭据错误 / 连不上 ⇒ 响亮报错，不静默返回
            try:
                mod._context_args({}, base, app_user="u@x", app_password="wrong")
                raise SystemExit("登录失败却未报错 —— 门没咬")
            except RuntimeError as exc:
                assert "/test-login" in str(exc), exc
            try:
                mod._context_args({}, "http://127.0.0.1:1", app_user="u", app_password="p")
                raise SystemExit("连不上却未报错 —— 门没咬")
            except RuntimeError:
                pass

            # 行为 ④：响应缺令牌（端点契约变更）⇒ 报错
            try:
                mod._context_args({}, base, app_user="notoken", app_password="x")
                raise SystemExit("响应无令牌却未报错 —— 门没咬")
            except RuntimeError as exc:
                assert "session_token" in str(exc), exc
    finally:
        srv.shutdown()
        srv.server_close()


def test_conftest_app_target_without_app_login_degrades_loudly() -> None:
    """契约 §7.1（3509 §B101）：stack-profile 未声明 e2e.app_login = **合法降级**。

    生成成功 + 生成期 WARN；生成物 `_APP_LOGIN = None`；运行期即便给了凭据也只跳过 +
    明确警告（不静默、不发登录请求）——不能让「配置缺失」伪装成「登录成功/失败」。
    变异证明：删掉 None 守卫（未声明也照跑登录）⇒ 本用例变红。
    """
    import contextlib
    import io

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # app_login 是 e2e 段最后一个键（夹具约定）⇒ 切到它之前 = 整段去掉
        make(root, profile=PROFILE.split("  app_login:")[0])
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "e2e.app_login" in r.stderr, r.stderr          # 生成期 WARN（不静默）
        conftest = (root / "product" / "e2e" / "scripts" / "conftest.py").read_text(encoding="utf-8")
        assert "_APP_LOGIN = None" in conftest, conftest
        mod = _load_conftest(root / "product" / "e2e" / "scripts" / "conftest.py")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            args = mod._context_args({}, "http://127.0.0.1:9", app_user="u@x", app_password="p")
        assert "storage_state" not in args, args               # 给了凭据也不发登录请求
        assert "e2e.app_login" in err.getvalue(), err.getvalue()


def test_app_login_section_incomplete_fails_generation() -> None:
    """契约 §7.1 / shared/stack-profile.md §2（3509 §B101）：段存在但字段不齐 ⇒ 生成报错。

    半截配置不是合法降级——要么齐、要么整段不要。变异证明：删掉该校验 ⇒ 本用例变红。
    """
    broken = PROFILE.replace("    storage_key: app_session\n", "")
    assert "storage_key" not in broken, broken                # 夹具前提：确实缺了字段
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=broken)
        r = run(root, "--apply")
        assert r.returncode != 0, r.stdout
        assert "app_login 段不完整" in r.stderr, r.stderr
        assert "storage_key" in r.stderr, r.stderr


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


def test_seed_mode_declare_vs_enforce() -> None:
    """契约 §5.7 / stack-profile §2（B197-1，2026-10-07）：`e2e.seed.mode` 声明/发射解耦——

    * `declare` ⇒ `seed:` 行**不发射**运行期 `_seed` 调用（累加链项目合法形态：
      每用例独立播种会撤销链上破坏性动作）；
    * 缺省 / `enforce` ⇒ 现行为（发射 `_seed`；M17 的既有钉子不变）；
    * 非法 mode ⇒ 生成器 exit 2（响亮，不猜）。

    变异证明 M42：摘掉 declare 分流 ⇒ 本用例 declare 侧红（回到全发射）。
    """
    case_with_seed = CASE.replace(
        "  - click home-cta-btn          # 点击主操作按钮",
        "  - click home-cta-btn          # 点击主操作按钮\nseed:\n  - upsert chapter name=第一章",
    )
    # declare：生成物无 `_seed(`
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE + "  seed:\n    mode: declare\n", case=case_with_seed)
        assert run(root, "--apply").returncode == 0
        py = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert "_seed(" not in py, py[-2000:]
    # 缺省（未声明 mode）= enforce：有 `_seed(`（现行为不变）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE + "  seed:\n    mode: enforce\n", case=case_with_seed)
        assert run(root, "--apply").returncode == 0
        py = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert "_seed(" in py, py[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE, case=case_with_seed)
        assert run(root, "--apply").returncode == 0
        py = (root / "product" / "e2e" / "scripts" / "home.py").read_text(encoding="utf-8")
        assert "_seed(" in py, py[-2000:]
    # 非法 mode ⇒ exit 2 + 指名
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE + "  seed:\n    mode: auto\n", case=case_with_seed)
        p = run(root, "--apply")
        assert p.returncode == 2, (p.returncode, p.stdout + p.stderr)
        assert "seed.mode" in (p.stderr + p.stdout)


def test_delta_relative_assertion_both_runners() -> None:
    """契约 §5.5（P5，2026-10-07）：`delta` 相对断言两侧同构 —— 行动前采样贴**第一个提交性
    动作**（准备步骤不污染基准，与 `unchanged:` 先例同点）、行动后轮询复读（node `expect.poll`）；
    值形态 / 豁免通道叠写 / 缺 step ⇒ 生成期中止；零步基线**不收** delta（无初始态语义）。
    变异证明 M38：把 delta 的行动前采样摘掉（退化为行动后单点取数）⇒ 本用例的顺序断言红。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-HOME-001",
        "_title": "拆分后待生成递增",
        "step": ["click home-cta-btn"],
        "expected": ["delta home-title +1"],
        "testid": ["home-cta-btn", "home-title"],
    }
    ts = gn.ts_case(case, "/")
    assert ts.index("const __delta_home_title = await atlasIntOf") < ts.index(
        "await page.getByTestId('home-cta-btn').click()"
    ), ts
    assert (
        "await expect.poll(() => atlasIntOf(page.getByTestId('home-title')), "
        "{ timeout: ATLAS_WAIT_TIMEOUT_MS }).toBe(__delta_home_title + 1);"
    ) in ts, ts
    # 准备步骤不污染基准：采样在提交动作之前、在先行准备动作之后
    case2 = {
        "id": "E2E-HOME-002",
        "_title": "准备后提交",
        "step": ["click home-tab-btn", "click home-save-btn"],
        "expected": ["delta home-title +1"],
        "testid": ["home-tab-btn", "home-save-btn", "home-title"],
    }
    ts2 = gn.ts_case(case2, "/")
    assert ts2.index("await page.getByTestId('home-tab-btn').click()") < ts2.index(
        "const __delta_home_title = await atlasIntOf"
    ) < ts2.index("await page.getByTestId('home-save-btn').click()"), ts2
    # python 侧同构：行动前采样 + 行动后复读（含行动前基准与实际值的双面报错）
    py = gn.py_case(case2, "/")
    assert py.index("_loc(page, \"home-tab-btn\").click()") < py.index(
        "__delta_home_title = _int_of"
    ) < py.index("_loc(page, \"home-save-btn\").click()"), py
    assert '_int_of(_loc(page, "home-title").inner_text()) == __delta_home_title + 1' in py, py
    # 生成期中止三态：值形态 / 叠写 / 缺 step
    for kwargs, kw in (
        ({"expected": ["delta home-title 3"]}, "±N"),
        ({"expected": ["initial: delta home-title +1"]}, "叠写"),
        ({"step": [], "expected": ["delta home-title +1"]}, "step"),
    ):
        try:
            gn.ts_case({**case, **kwargs}, "/")
        except ValueError as exc:
            assert kw in str(exc), (kwargs, exc)
        else:  # pragma: no cover
            raise AssertionError(f"`delta` 非法形态未报错: {kwargs}")
    # 零步基线不收 delta（两侧）：基线探针清单里不得出现 delta 断言
    # （py 侧：同页另有普通断言时 data 才非 None —— 用带 text 的姊妹用例共同喂入）
    plain = {**case, "id": "E2E-HOME-002", "_title": "普通断言", "expected": ["text home-title 首页"]}
    _t, data = gn.py_zero_step_baseline("home", "/", [case, plain])
    assert data is not None and all("delta" not in p["label"] for p in data["probes"]), data
    assert "delta" not in gn.ts_zero_step_baseline("home", "/", [case, plain])


if __name__ == "__main__":
    sys.exit(main())
