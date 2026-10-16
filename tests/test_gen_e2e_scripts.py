#!/usr/bin/env python3
"""atlas E2E 脚本生成器（G1/D68）回归测试。

单轨化（B201-4 / 3507 BO，2026-10-09）：唯一运行器 = node-playwright（.spec.ts）；
python-playwright 发射面已整体退役——本文件原 py 侧钉子随批转换为 TS 面，
py 专属机制（conftest.py 发射 / pytest marker / `_data` 基线清单 / `_seed` 运行期
发射）的钉子删除，语义由 TS 等价面或项目真跑承接（见 `3508 §203`）。

    python3 atlas/tests/test_gen_e2e_scripts.py
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import difflib
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
  runner: node-playwright
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


def spec_of(root: Path, page: str = "home") -> str:
    return (root / "product" / "e2e" / "scripts" / f"{page}.spec.ts").read_text(encoding="utf-8")


def zs_probes(spec_text: str, page: str = "home") -> list[dict]:
    """抽出页面脚本内联的零步基线清单（`const ATLAS_ZS_<page> = {...}`）并解析。"""
    m = re.search(rf"const ATLAS_ZS_{page} = (\{{.*?\}});\n", spec_text, re.S)
    assert m, spec_text[:400]
    return json.loads(m.group(1))["probes"]


# ── issue #13（2026-10-16）：`会话:` 的发射与零步基线隔离 ────────────────────
PROFILE_SESSION = PROFILE + "  session_preset:\n    keys:\n      - env\n"
SESSION_CASE = CASE.replace("step:", "会话:\n  - env=staging\nstep:", 1)


# ── issue #23（2026-10-16）：`守卫:` —— 元素齐全守卫导航的具体路径 ───────────────
GUARD_CASE = CASE.replace("step:", "守卫: /home/42\nstep:", 1)


def test_guard_route_used_for_element_guard_navigation() -> None:
    """带 `守卫:` 时，用例体开头的**元素齐全守卫导航**用该具体路径（而非页面表业务段）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=GUARD_CASE)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        seg = text[text.index("E2E-HOME-001"):]
        i_guard = seg.index("await page.goto('/home/42')")
        # 紧跟其后必须是存在守卫（而用例自身的 goto 在它之后）
        assert "for (const id of" in seg[i_guard:i_guard + 200], seg[i_guard:i_guard + 200]


def test_guard_absent_keeps_output_byte_identical() -> None:
    """**零变化承诺**（契约 §5.8 同规）：无 `守卫:` 时生成物与今日逐字节一致。

    证法：同一用例分别带 / 不带 `守卫:` 各生成一次，两份产物**只允许差那一行**（守卫导航）。
    """
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        r1, r2 = Path(t1), Path(t2)
        make(r1, case=CASE)
        make(r2, case=GUARD_CASE)
        assert run(r1, "--apply").returncode == 0
        assert run(r2, "--apply").returncode == 0
        diff = [x for x in difflib.unified_diff(spec_of(r1).splitlines(),
                                                spec_of(r2).splitlines(), lineterm="")
                if x[:1] in ("+", "-") and not x.startswith(("+++", "---"))]
        assert len(diff) == 2, diff
        assert all("page.goto(" in x for x in diff), diff


def test_session_preset_emitted_before_first_goto() -> None:
    """`会话:` 编译为 addInitScript 注册，且必须**先于首屏 `page.goto`**。

    变异证明：把 `session_open` 挪到 `page.goto` 之后 ⇒ 本用例红（addInitScript 只对未来
    导航生效，后注 = 首屏拿不到会话态 = 用例实际在默认态下跑）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=SESSION_CASE, profile=PROFILE_SESSION)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        assert "await atlasSessionPreset(page," in text, text[:600]
        # 比较必须限定在**该用例体**内（页头里也有 `await page.goto(` —— 基线 helper）
        seg = text[text.index("E2E-HOME-001"):]
        assert seg.index("await atlasSessionPreset(page,") < seg.index("await page.goto("), seg[:400]


def test_session_preset_without_whitelist_aborts() -> None:
    """坏输入：项目未声明 `e2e.session_preset.keys` ⇒ 生成器 exit 2（不猜、不静默降级）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=SESSION_CASE, profile=PROFILE)
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "会话" in r.stderr, r.stderr


def test_session_preset_key_outside_whitelist_aborts() -> None:
    """坏输入：键在白名单外 ⇒ 生成器 exit 2。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=SESSION_CASE,
             profile=PROFILE + "  session_preset:\n    keys:\n      - otherFlag\n")
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "白名单" in r.stderr, r.stderr


def test_zero_step_baseline_carries_no_session() -> None:
    """零步基线**不施加** `会话:`（前提构造不计入基线）——护栏：基线测试体里不得出现
    `atlasSessionPreset`。否则依赖会话前提的断言会在基线（默认会话）下成立 ⇒ 恒真门误报。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=SESSION_CASE, profile=PROFILE_SESSION)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        marker = "test('test_home__zero_step_baseline'"
        assert marker in text, text[:600]
        baseline_body = text.split(marker, 1)[1].split("\ntest(", 1)[0]
        assert "atlasSessionPreset" not in baseline_body, baseline_body


def test_retired_python_runner_rejected() -> None:
    """单轨化（B201-4 / 3507 BO）：`python-playwright` 已退役——显式声明 ⇒ 生成器 exit 2
    响亮拒绝（不静默改行为）；校验器侧同判（`test_validators.py` 的 runner 枚举钉）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.replace("runner: node-playwright",
                                           "runner: python-playwright"))
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "python-playwright" in r.stderr, r.stderr
        assert not (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()


def test_seed_lines_warn_without_channel_and_mode_split() -> None:
    """契约 §5.7 / stack-profile §2（B197-1 + B201-4 单轨化）：

    * `seed:` 行的**运行期发射**随 py 运行器退役——node 轨从不发射播种调用
      （两 mode 生成物里均无 seed 调用；`seed:` 只参与 seed×models 静态对账）；
    * `mode: enforce`（缺省）且未声明 `e2e.seed.hook` ⇒ 生成期 WARN（响亮）；
      `mode: declare` ⇒ 不 WARN（累加链项目合法形态）；
    * 非法 mode ⇒ exit 2。
    """
    case = CASE.replace("testid:\n",
                        "seed:\n  - upsert bgm-library name=片头曲 duration=30\ntestid:\n")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case)  # 缺省 enforce + 无 hook ⇒ WARN
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "WARN" in r.stderr and "e2e.seed.hook" in r.stderr, r.stderr
        spec = spec_of(root)
        assert "bgm-library" not in re.sub(r"//.*", "", spec), "运行期播种发射面必须为零"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case, profile=PROFILE + "  seed:\n    mode: declare\n")
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "e2e.seed.hook" not in r.stderr, r.stderr
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case, profile=PROFILE + "  seed:\n    mode: auto\n")
        p = run(root, "--apply")
        assert p.returncode == 2, (p.returncode, p.stdout + p.stderr)
        assert "seed.mode" in (p.stderr + p.stdout)


def test_auth_none_wraps_describe_with_clean_storage() -> None:
    """契约 §5.7：`auth: none` ⇒ describe 包裹 + 空 storageState 覆盖（干净 context）。
    变异 M32：摘掉包裹 ⇒ 未登录前提用例带预置登录态跑（假绿通道）。
    """
    case = CASE.replace("id: E2E-HOME-001", "auth: none\nid: E2E-HOME-001")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        home = spec_of(root)
        assert "test.describe('atlas auth none'" in home, home[:600]
        assert "storageState: { cookies: [], origins: [] }" in home


def test_auth_unknown_value_aborts() -> None:
    """契约 §5.7：`auth` 取值白名单外 ⇒ 生成器**中止**（不猜、不静默降级）。"""
    case_bad = CASE.replace("id: E2E-HOME-001", "auth: cookie\nid: E2E-HOME-001")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case_bad)
        r = run(root, "--apply")
        assert r.returncode != 0
        assert "auth" in (r.stderr + r.stdout)


def test_runner_emits_skip_baseline_first_and_setup() -> None:
    """契约 §B48 / #153：blocked 发 test.skip；零步基线定义在用例**之前**（真栈用例
    持久化改态，基线后跑会把前序改态误判成初始态恒真）；生成 atlas-auth.setup.ts +
    setup 项目（storageState 预置登录）。变异 M31：摘掉任一发射 ⇒ 对应断言红。
    （2026-10-01 契约 §7：blocked 用例不进基线探针 ⇒ 夹具含一 active 用例承载基线。）
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
    index = INDEX.replace(
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |",
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |\n"
        "| E2E-HOME-002 | home | blocked 用例 | smoke | AC-HOME-002 | | blocked | BLOCKED_DEP：x |")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case, index=index)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        scripts = root / "product" / "e2e" / "scripts"
        home = (scripts / "home.spec.ts").read_text(encoding="utf-8")
        assert "test.skip(" in home and "BLOCKED_DEP" in home, home[:600]
        bpos = home.find("test('test_home__zero_step_baseline'")
        cpos = min(x for x in (home.find('test("E2E-'), home.find("test.skip(")) if x != -1)
        assert 0 < bpos < cpos, (bpos, cpos)
        assert "atlasZeroStepBaseline" in home
        assert "home-modal" not in home.split("test_home__zero_step_baseline")[1].split("test(")[0], \
            "blocked 用例断言混进了基线"  # 契约 §7（2026-10-01）
        cfg = (scripts / "playwright.config.ts").read_text(encoding="utf-8")
        setup_ts = (scripts / "atlas-auth.setup.ts").read_text(encoding="utf-8")
        assert "name: 'setup'" in cfg and "storageState" in cfg, cfg
        assert "ATLAS_APP_USER" in setup_ts and "atlas auth setup" in setup_ts, setup_ts[:400]


def test_generates_actions_and_asserts() -> None:
    """契约 §7.1：产物是**操作脚本**——step 生成动作、expected 生成断言（不是只做存在性检查）。

    单轨化追加面（B201-4）：py 时代产物不再发射——conftest.py / `_data/` 不存在；
    `_support/hooks.ts` 种子文件照旧（缺失时建）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        scripts = root / "product" / "e2e" / "scripts"
        text = (scripts / "home.spec.ts").read_text(encoding="utf-8")
        assert "await page.goto('/home');" in text, text
        # step → 动作
        assert "await page.getByTestId('home-cta-btn').first().click();" in text, text
        # expected → 断言（不是只做存在性检查）
        assert 'await expect(page.getByTestId(\'home-title\').first()).toHaveText("首页");' in text, text
        assert "await expect(page.getByTestId('home-cta-btn').first()).toBeVisible();" in text, text
        # 中文说明降为注释（step/expected 原文镜像在用例体头部，`# 说明` 形态保留）
        assert "# 点击主操作按钮" in text
        # 单轨化退役面不回流
        assert not (scripts / "conftest.py").exists()
        assert not (scripts / "_data").exists()
        assert (scripts / "_support" / "hooks.ts").is_file()
        cfg = (scripts / "playwright.config.ts").read_text(encoding="utf-8")
        assert "http://127.0.0.1:8000" in cfg      # baseURL（E1 单段 = e2e.app_base_url）在运行器配置
        assert "http://127.0.0.1:8000" not in text  # 用例脚本不硬编码地址


def test_zero_step_baseline_two_trip_sampling_with_panel_expansion() -> None:
    """契约 §5.6 R9 / §B72：**按动词分状态取样** + 面板展开——

    ① 内联清单（`ATLAS_ZS_<page>`）里每条 probe 的 `sampling` 分类正确（`hidden` /
    `unchanged:` ⇒ `expanded`；`visible` / `text` / `attr` ⇒ `rendered`）；
    ② 运行期两趟循环（`rendered` 先真实渲染、`expanded` 前展开面板）+ 展开目标
    `[data-atlas-panel]` 都必须落在**同一份生成物**里。
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
        text = spec_of(root)
        probes = zs_probes(text)
        by_label = {p["label"]: p["sampling"] for p in probes}
        assert by_label["E2E-HOME-001: visible home-cta-btn"] == "rendered", by_label
        assert by_label["E2E-HOME-001: hidden home-create-project-modal"] == "expanded", by_label
        assert by_label["E2E-HOME-001: attr home-cta-btn data-theme dark"] == "rendered", by_label
        # ② 运行期机制：两趟 + 展开（同文件 header）
        assert "for (const pass of ['rendered', 'expanded'] as const)" in text, text
        assert "atlasExpandPanels(page)" in text and "[data-atlas-panel]" in text, text


def test_zero_step_baseline_excludes_blocked_cases() -> None:
    """契约 §7（2026-10-01）：`blocked` / `skipped` 用例的断言**不进**零步基线探针——
    否则部分实现页上未实现面板内元素的 `hidden` 探针判真 ⇒ 基线假红。
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
        labels = [p["label"] for p in zs_probes(spec_of(root))]
        assert labels and all(not l.startswith("E2E-HOME-009") for l in labels), labels
    # 单元级对照：状态缺省（= 回潮旧行为）⇒ 探针回流
    gen = load_generator()
    cases = [{"id": "E2E-HOME-009", "_state": "blocked", "_state_reason": "NOT_IMPLEMENTED：x",
              "expected": ["hidden home-panel-x   # y"]}]
    assert gen.ts_zero_step_baseline("home", "/home", cases) == ""
    plain = [{"id": "E2E-HOME-009", "expected": ["hidden home-panel-x   # y"]}]
    assert "E2E-HOME-009" in gen.ts_zero_step_baseline("home", "/home", plain)


def test_unchanged_pre_is_sampled_right_before_the_submitting_action() -> None:
    """契约 §5.6 R9（`3509 §B55`）：`unchanged:` 的「行动前」断言必须**贴着第一个提交性动作**采样。

    反例：放在**所有 step 之前** ⇒ 准备步骤还没执行、目标元素可能不可见 ⇒
    合法用例被判「自相矛盾」（实测 `E2E-ASSETS-003` / `E2E-CONFIG-003`）。
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
        text = spec_of(root)
        pre = text.index("await expect(page.getByTestId('home-create-project-modal').first()).toBeHidden();")
        arrange = text.index("await page.getByTestId('home-cta-btn').first().click();")
        submit = text.index("await page.getByTestId('home-create-submit-btn').first().click();")
        assert arrange < pre < submit, (
            "「行动前」采样点不对：应在准备步骤之后、提交性动作之前",
            text[max(0, pre - 300):pre + 120],
        )


def test_unknown_verb_aborts() -> None:
    """step/expected 出现词表外的动词 → 中止并列出违规行，不静默降级（§5.5 / §7.1）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=CASE.replace("- click home-cta-btn", "- 点击主操作按钮"))
        r = run(root, "--apply")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "动词不在词表内" in r.stderr, r.stderr
        assert not (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()


def test_inline_comment_in_profile() -> None:
    """真实 profile 带行内注释（本项目 `stack-profile.yaml` 就如此）也必须能解析。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.replace(
            "  runner: node-playwright",
            "  runner: node-playwright   # 唯一合法运行器"))
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert (root / "product" / "e2e" / "scripts" / "home.spec.ts").is_file()


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
        assert not (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()


def test_app_target_uses_app_base_url() -> None:
    """baseURL 只落运行器配置（playwright.config.ts），用例脚本不硬编码地址（E1 单段）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        run(root, "--apply")
        cfg = (root / "product" / "e2e" / "scripts" / "playwright.config.ts").read_text(encoding="utf-8")
        assert "http://127.0.0.1:8000" in cfg
        assert "http://127.0.0.1:8000" not in spec_of(root)


def test_app_target_without_url_reports_not_ready() -> None:
    """`3509 §B110`：前置未声明（`app_base_url: null`）⇒ **退出码 3 + 机读 `not_ready`**，与真错（2）分开。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, PROFILE.replace("app_base_url: http://127.0.0.1:8000", "app_base_url: null"))
        r = run(root, "--apply", "--json")
        assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
        payload = json.loads(r.stdout)
        assert payload["ok"] is False and payload["not_ready"] == "app_base_url", payload
        assert "app_base_url" in payload["message"], payload
        assert not (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()


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

    变异证明：删掉行动前断言 ⇒ 出现次数断言红；退化为普通断言 ⇒ 顺序断言红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=CASE_UNCHANGED)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        text = spec_of(root)
        target = "await expect(page.getByTestId('home-create-project-modal').first()).toBeHidden();"
        first = text.index(target)
        submit = text.index("await page.getByTestId('home-create-submit-btn').first().click();")
        second = text.index(target, first + 1)
        assert first < submit < second, "行动前 / 行动后两处断言顺序不对"
        assert text.count(target) == 2, "unchanged: 必须恰好发射前 + 后两处"
        # 前缀不得作为代码泄进产物（注释镜像行以 `//   - ` 开头，允许）
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))
        assert "unchanged:" not in code and "initial:" not in code, code[:800]


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
        text = spec_of(root)
        probes = zs_probes(text)
        exprs = " ".join(p["expr"] for p in probes)
        assert "home-cta-btn" not in exprs, exprs               # 已豁免，不进 probe 清单
        assert "home-title" in exprs, exprs                     # 未豁免的另一条仍在
        assert "await expect(page.getByTestId('home-cta-btn').first()).toBeVisible();" in text, text
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))
        assert "initial:" not in code, code


def test_zero_step_baseline_covers_non_exempt_asserts() -> None:
    """契约 §5.6 R9：每页产一条零步基线，**未加 `initial:` 前缀**的断言全部进 probe 集合；
    基线测试体只调 `atlasZeroStepBaseline`（不执行任何 step）；命中即响亮失败
    （`expect(misses).toEqual([])` —— 不得静默）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        labels = [p["label"] for p in zs_probes(text)]
        assert "E2E-HOME-001: text home-title 首页" in labels, labels
        assert "E2E-HOME-001: visible home-cta-btn" in labels, labels
        baseline_block = text.split("test('test_home__zero_step_baseline'", 1)[1].split("test(", 1)[0]
        assert ".click()" not in baseline_block, baseline_block
        assert "expect(misses, `零步基线（恒真/自相矛盾）：${misses.join('；')}`).toEqual([]);" in text, text


def test_zero_step_baseline_names_every_use_of_a_same_shaped_assertion() -> None:
    """`3509 §B33`：零步基线**不得**按「断言表达式串」去重——每条断言各自成条、
    label 各自带用例 ID（否则被 `unchanged:` 折叠的 plain 同形断言永不点名 ⇒ 假阴性）。
    """
    two = CASE.replace("id: E2E-HOME-001", "id: E2E-HOME-002")
    both = CASE + "\n" + two
    index = INDEX.replace(
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |",
        "| E2E-HOME-001 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |\n"
        "| E2E-HOME-002 | home | 首页主操作可见 | smoke | AC-HOME-001 | | red | |")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=both, index=index)
        assert run(root, "--apply").returncode == 0
        probes = zs_probes(spec_of(root))
        same = [p for p in probes
                if p["expr"] == '(async () => await tsVisible(page, "home-cta-btn"))()']
        labels = [p["label"] for p in same]
        assert len(same) == 2, f"同形断言被去重掩盖：{labels}"
        assert any("E2E-HOME-001" in x for x in labels) and any("E2E-HOME-002" in x for x in labels), labels


def test_reverse_view_regenerated_from_main_table() -> None:
    """`3509 §B64`：索引的 `## 页面 ↔ 用例` 是 100% 派生信息 ⇒ 由生成器重写。

    反向证明：先手工把该段改错，再一次 `--apply` 必须**纠正回来**。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        p = root / "product" / "e2e" / "e2e-index.md"
        p.write_text(INDEX.rstrip("\n") + "\n\n## 页面 ↔ 用例\n\n"
                     "| 页面 | 断言落点用例 | 链路经过用例 |\n|---|---|---|\n"
                     "| home | E2E-HOME-999 | |\n", encoding="utf-8")
        assert run(root, "--apply").returncode == 0
        once = p.read_text(encoding="utf-8")
        assert "## 页面 ↔ 用例" in once and "E2E-HOME-001" in once.split("## 页面 ↔ 用例")[1]
        p.write_text(once.replace("| home | E2E-HOME-001", "| home | E2E-HOME-999"), encoding="utf-8")
        assert run(root, "--apply").returncode == 0
        fixed = p.read_text(encoding="utf-8")
        assert "E2E-HOME-999" not in fixed, "生成器未纠正被手改的反向视图"
        assert fixed == once, "反向视图重生成后与首次不一致（非幂等）"


# 契约 §7.1：§5.5 的**每一个**断言动词都必须有渲染分支并配样例（词表 ⇄ 样例表守恒；
# 单轨化后唯一运行器 = node）。只测一侧正是 `3509 §B48` 的成因。
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


def test_every_assert_verb_renders() -> None:
    """① 词表里出现新动词而没有样例 ⇒ 红（逼作者为渲染想清楚）；
    ② 样例表与词表不一致 ⇒ 红；③ 每个动词都要渲染成功（未知动词 `raise ValueError`）。
    """
    gn = _load_gen()
    assert set(gn.ASSERT_VERBS) == set(ASSERT_SAMPLES), (
        f"词表与样例表不一致: 新动词={sorted(set(gn.ASSERT_VERBS) - set(ASSERT_SAMPLES))} "
        f"多余样例={sorted(set(ASSERT_SAMPLES) - set(gn.ASSERT_VERBS))}"
    )
    for verb, rest in ASSERT_SAMPLES.items():
        line = f"{verb} {rest}"
        case = {
            "id": "E2E-HOME-001",
            "_title": "首页主操作可见",
            "step": ["goto /"],
            "expected": [line],
            "testid": ["home-cta-btn", "home-title"],
        }
        spec = gn.ts_case(case, "/")
        assert "home-cta-btn" in spec or "home-title" in spec, (verb, spec)


def test_value_and_attr_keep_same_semantics() -> None:
    """`value` 的空值写法与 `attr` 的属性比对语义钉死（`3509 §B48`「一侧能跑另一侧认错」族）：
    `""` / `(空)` 必须映射为真实空串，不是两个引号字符。
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

    out = ts("attr home-cta-btn data-theme dark")
    assert 'toHaveAttribute("data-theme", "dark")' in out, out


def test_select_and_value_are_implementation_agnostic() -> None:
    """契约 §5.5（B173-1）：select 动词与 value 断言/探针**不得绑定原生 DOM**——
    按元素 tagName 自适应（原生走原路径，否则 trigger+listbox 组合）。
    """
    gn = _load_gen()
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
    assert expr.endswith('return x === null ? null : x === "首页"; })()'), expr
    # 整文件级：三件 helper 必须落在页面 header（与用例体同文件，运行期才不报未定义）
    case_text = CASE.replace(
        "  - click home-cta-btn          # 点击主操作按钮",
        "  - select home-cta-btn 首页    # B173-1：实现无关 select",
    ).replace(
        "  - text home-title 首页        # 页面标题文案为「首页」",
        "  - value home-cta-btn 首页     # B173-1：实现无关 value",
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case_text)
        assert run(root, "--apply").returncode == 0
        ts = spec_of(root)
        assert "await atlasSelect(page, 'home-cta-btn'" in ts, ts
        assert "await atlasExpectValue(page, 'home-cta-btn'" in ts, ts
        for frag in (
            "async function atlasSelect(",
            "async function atlasValueOf(",
            "async function atlasExpectValue(",
        ):
            assert frag in ts, (frag, ts[:2000])


def test_download_renders_register_then_click() -> None:
    """契约 §5.5 / §7.1（`3509 §B26`）：`download` 属**动作**，必须渲染为「**先注册下载监听 →
    再点击 → 校验建议文件名**」—— 下载是动作的副作用，事后无法补取证。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-HOME-001",
        "_title": "导出并校验文件名",
        "step": ["goto /", "download projects-export-prompt-btn *.txt"],
        "expected": ["visible home-cta-btn"],
        "testid": ["projects-export-prompt-btn", "home-cta-btn"],
    }
    assert "await atlasDownload(page, 'projects-export-prompt-btn', \"*.txt\");" in gn.ts_case(case, "/")

    # 反向证据：缺文件名 glob 参数 ⇒ 报错（不得静默退化为「只点击」）
    try:
        gn.ts_case({**case, "step": ["download projects-export-prompt-btn"]}, "/")
    except ValueError as exc:
        assert "glob" in str(exc), exc
    else:  # pragma: no cover
        raise AssertionError("`download` 缺 glob 参数未报错")

    # 端到端：生成物里必须有「注册监听 → 点击 → 校验」的固定形状
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=DOWNLOAD_CASE)
        assert run(root, "--apply").returncode == 0
        ts = spec_of(root)
    assert "page.waitForEvent('download'" in ts, ts
    assert "download.suggestedFilename()" in ts, ts
    # glob→regex 的转义助手必须在**同一份生成物**里（否则运行期报未定义）
    assert "function atlasGlob(pattern)" in ts and "atlasGlob(pattern)" in ts, ts


UPLOAD_CASE = CASE.replace(
    "  - click home-cta-btn          # 点击主操作按钮",
    "  - upload home-cta-btn uploads/sample.wav  # 投放音频样本",
)


def test_upload_renders_set_input_files_with_cwd_free_path() -> None:
    """契约 §5.5 / §7.1（B201-1，2026-10-12）：`upload` 属**动作** —— 值 = 相对
    `product/e2e/fixtures/` 的文件路径（与 §5.8 mock 同一 fixtures 树）。

    渲染 pin：产物必须是 `setInputFiles(...)`，且路径**按脚本文件位置解析**
    （`resolve(__dirname, '..', 'fixtures', …)`，spec 位于 <e2e>/scripts/）——两个真实
    载体 cwd 不同（控制台从 scripts 跑 / atlas_check 从项目根跑），内联构建机绝对路径
    或依赖进程 cwd 都会在其中一个载体上炸（实测两载体下 `__dirname` 方案均可跑通）。
    缺值 / 缺 fixture 文件 ⇒ exit 2 列明（镜像 `download` / §5.8 mock 的 fail-loud）。
    零变化承诺：未用 upload 的页不引入 `node:path` 导入。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-HOME-001",
        "_title": "投放音频样本",
        "step": ["goto /", "upload home-cta-btn uploads/sample.wav"],
        "expected": ["visible home-cta-btn"],
        "testid": ["home-cta-btn"],
    }
    spec = gn.ts_case(case, "/")
    assert ('await page.getByTestId(\'home-cta-btn\').first().setInputFiles('
            'resolve(__dirname, \'..\', \'fixtures\', "uploads/sample.wav"));') in spec, spec
    assert "/Users/" not in spec and "/home/" not in spec, "不得内联构建机绝对路径"

    # 反向证据：缺值 ⇒ 报错（不得静默退化为「只定位不投放」）
    try:
        gn.ts_case({**case, "step": ["upload home-cta-btn"]}, "/")
    except ValueError as exc:
        assert "upload" in str(exc), exc
    else:  # pragma: no cover
        raise AssertionError("`upload` 缺值未报错")

    # 端到端：fixture 就位 ⇒ 生成成功；产物含解析导入 + 投放行
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=UPLOAD_CASE)
        fx = root / "product" / "e2e" / "fixtures" / "uploads"
        fx.mkdir(parents=True)
        (fx / "sample.wav").write_text("RIFF", encoding="utf-8")
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        ts = spec_of(root)
    assert "import { resolve } from 'node:path';" in ts, ts
    assert ('await page.getByTestId(\'home-cta-btn\').first().setInputFiles('
            'resolve(__dirname, \'..\', \'fixtures\', "uploads/sample.wav"));') in ts, ts

    # 缺 fixture 文件 ⇒ exit 2 列明（fail-loud；校验器侧「引用存在」为双保险）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=UPLOAD_CASE)
        (root / "product" / "e2e" / "fixtures").mkdir(parents=True, exist_ok=True)
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "fixture 不存在" in r.stderr and "sample.wav" in r.stderr, r.stderr
        assert not (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()

    # 缺值 ⇒ exit 2（主流程口径；上面的单元 ValueError 为渲染层双保险）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=UPLOAD_CASE.replace(" uploads/sample.wav", ""))
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "upload" in r.stderr, r.stderr

    # 零变化承诺（页级形态）：未用 upload 的页不得引入 node:path 导入
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        assert "node:path" not in spec_of(root), "未用 upload 的页必须零变化"


# 契约 §7.1：§5.5 的**每一个**动作动词也必须有渲染分支并配样例（与断言动词同一道守恒门）。
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
    "upload": "home-cta-btn uploads/sample.txt",
}


def test_every_action_verb_renders() -> None:
    """契约 §7.1：动作动词的逐项守恒（与断言动词同口径）。"""
    gn = _load_gen()
    assert set(gn.ACTION_VERBS) == set(ACTION_SAMPLES), (
        f"词表与样例表不一致: 新动词={sorted(set(gn.ACTION_VERBS) - set(ACTION_SAMPLES))} "
        f"多余样例={sorted(set(ACTION_SAMPLES) - set(gn.ACTION_VERBS))}"
    )
    for verb, rest in ACTION_SAMPLES.items():
        line = verb if not rest else f"{verb} {rest}"
        case = {
            "id": "E2E-HOME-001",
            "_title": "首页主操作可见",
            "step": [line],
            "expected": ["visible home-cta-btn"],
            "testid": ["home-cta-btn"],
        }
        spec = gn.ts_case(case, "/")
        assert "home-cta-btn" in spec, (verb, spec)


def test_step_anchor_emits_assertion_after_that_step() -> None:
    """契约 §5.5（`3509 §B57`）：`after:<N>` 的断言必须发射在**第 N 条 step 之后**、
    终态断言之前；且它**不属豁免通道** —— 要进零步基线（与 `initial:` 的完全豁免相对）。
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
        text = spec_of(root)
        probes = zs_probes(text)
    c = text.index("await page.getByTestId('home-cta-btn').first().click();")
    a = text.index("await expect(page.getByTestId('home-cta-btn').first()).toBeVisible();")
    z = text.index("await expect(page.getByTestId('home-cta-btn').first()).toBeHidden();")
    assert c < a < z, text
    # 步骤锚断言必须进基线（= 不是豁免通道）；`initial:` 那条不进
    assert probes and all("toBeHidden" not in p["expr"] for p in probes), probes
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))
    assert "initial:" not in code, code


def test_review_gate_blocks_apply_without_report() -> None:
    """契约 §12.6 / §7.1：报告缺失 = **未审**（不是「通过」）⇒ `--apply` 拒绝写盘。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, review=False)
        r = run(root, "--apply")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "独立审查门" in r.stderr, r.stderr
        assert not (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists(), \
            "拒绝写盘必须真的不写盘"


def test_review_gate_blocks_apply_on_critical() -> None:
    """存在 `Critical`（`status == "FAIL"`）⇒ 同样断言 —— 带着缺陷生成脚本 = 把缺陷固定下来。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        write_review(root, "e2e", "2026-01-02-failing", "FAIL")
        r = run(root, "--apply")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "Critical" in r.stderr, r.stderr
        assert not (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()


def test_review_gate_dry_run_only_reports() -> None:
    """存在性挂在**写盘动作**上：dry-run 只报状态、不改退出码。"""
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
    """**消费者守恒**：门的取值集合 / 路径形态 / 状态词表必须与契约正文逐项一致。"""
    gen = load_generator()
    shared = (PKG_ROOT / "shared" / "independent-review.md").read_text(encoding="utf-8")
    assert "{ok, status, checks[]}" in shared, "共享契约必须仍声明机读形态"
    assert 'status = "FAIL"' in shared and '"Critical"' in shared
    assert "product/<环>/reviews/<日期>-<范围>/" in shared
    assert gen.REVIEW_LEVELS == {"PASS", "WARN", "FAIL"}, gen.REVIEW_LEVELS
    assert gen.REVIEW_DIRNAME == "reviews"
    for ring in ("e2e",):
        text = (PKG_ROOT / "rings" / ring / "reference.md").read_text(encoding="utf-8")
        assert f"product/{ring}/reviews/<日期>-<范围>/" in text, ring
        assert "Critical" in text, ring


def test_review_gate_auto_heals_on_adopt() -> None:
    """v0.1.0-beta.14: 存量 adopt 模式下缺失审查报告时自动自愈放行，绝不抛 exit 2 阻断写盘。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.replace("product: demo", "product: demo\norigin: adopt"), review=False)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()
        reports = list((root / "product" / "e2e" / "reviews").glob("*-adopt-baseline/review.json"))
        assert len(reports) == 1, reports
        report_data = json.loads(reports[0].read_text(encoding="utf-8"))
        assert report_data["ok"] is True
        assert report_data["status"] == "WARN"
        assert report_data["basis"] == "auto-baseline"
        assert report_data["reviewed"] == 0
        assert report_data["expected"] >= 1


def test_review_gate_modes_triple_key_semantics() -> None:
    """R6.1 对账定稿（2026-10-15）：三个语义三把钥匙，不得隐式互化——
    ① `review: null`（= 执行器取会话默认，契约 shared/stack-profile.md §2）⇒ **缺省严格门**：
       缺报告 ⇒ --apply 拒写盘 exit 2；
    ② 显式 `mode: auto-baseline` ⇒ 缺报告自动自愈兜底放行（基线三件套如实 WARN）；
    ③ 显式 `mode: off`（免审）⇒ 放行且**不落基线**（审未进议程，不制造「形式审过」假象）。"""
    # ① null = 严格门（回归：此前把 null 当免阻断通道是语义漂移）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.replace("runner: node-playwright", "runner: node-playwright\n  review: null"), review=False)
        r = run(root, "--apply")
        assert r.returncode == 2 and "审查报告" in r.stderr, r.stderr + r.stdout
        assert not (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()

    # ② 显式 auto-baseline ⇒ 自愈兜底
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.replace(
            "runner: node-playwright", "runner: node-playwright\n  review:\n    mode: auto-baseline"), review=False)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()
        reports = list((root / "product" / "e2e" / "reviews").glob("*-auto-baseline/review.json"))
        assert len(reports) == 1, reports
        report_data = json.loads(reports[0].read_text(encoding="utf-8"))
        assert report_data["ok"] is True
        assert report_data["status"] == "WARN"
        assert report_data["basis"] == "auto-baseline"

    # ③ 显式 off ⇒ 免审放行、不落任何基线
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.replace(
            "runner: node-playwright", "runner: node-playwright\n  review:\n    mode: off"), review=False)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert (root / "product" / "e2e" / "scripts" / "home.spec.ts").exists()
        assert not list((root / "product" / "e2e" / "reviews").glob("*baseline*")), "off 模式不得落基线报告"


def test_mock_case_exempt_from_zero_step_baseline() -> None:
    """v0.1.0-beta.14: 含有 mock: 段的用例自动免除零步基线探针（防初始容器误报恒真）。"""
    mock_case = CASE.replace(
        "expected:\n  - text home-title 首页        # 页面标题文案为「首页」\n  - visible home-cta-btn        # 主操作按钮可见",
        "mock:\n  - GET /api/home -> fixtures/home.json\nexpected:\n  - text home-title 首页        # 页面标题文案为「首页」\n  - visible home-cta-btn        # 主操作按钮可见",
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product" / "e2e" / "fixtures").mkdir(parents=True, exist_ok=True)
        (root / "product" / "e2e" / "fixtures" / "home.json").write_text("{}", encoding="utf-8")
        make(root, profile=PROFILE.replace("runner: node-playwright", "runner: node-playwright\n  mock:\n    mode: on\n    api_prefix: /api"), case=mock_case)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        # 零步基线探针中不包含 mock 用例的任何断言
        assert "test('test_home__zero_step_baseline'" not in text or not zs_probes(text)
        # 但用例本身的测试体内仍完整保留 toBeVisible 断言
        assert "await expect(page.getByTestId('home-cta-btn').first()).toBeVisible();" in text


def test_testid_guard_uses_auto_wait_not_immediate_count() -> None:
    """契约 §7.1（`3509 §B99`②）：元素齐全守卫必须**自动等待**判定——

    `expect(...).toHaveCount(1)` 是运行器原生轮询断言（SPA 异步渲染下即时 `count()`
    判存在性必红）；守卫缺失 testid 时由 expect 超时失败并点名（不静默）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        guard = ("for (const id of [\"home-cta-btn\"]) {\n"
                 "    await expect(page.getByTestId(id)).toHaveCount(1);\n"
                 "  }")
        assert guard in text, text[:1200]
        assert ".count() > 0 && (await" not in text.split("test(")[0].split("tsVisible")[0], text[:600]


def test_setup_project_real_login_preset_shape() -> None:
    """契约 §5.4 / §7.1（`3509 §B99`① + §B101）：storageState 预置登录 = **真实登录**。

    单轨化（B201-4）：conftest 行为级钉子退役，本钉守住 setup 项目的**静态形态**——
    端点 / 字段 / 键全部来自 `e2e.app_login` 取证值（不硬编码项目字面量）；凭据只来自
    运行期环境变量；缺凭据 ⇒ 写空 state + 警告（不静默）；换取失败 ⇒ 抛错中止。
    （登录换取的**行为级**验证由项目七域真跑持续承接——真实端点 + 真实凭据。）
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        setup_ts = (root / "product" / "e2e" / "scripts" / "atlas-auth.setup.ts").read_text(encoding="utf-8")
        # 取证值来自 profile 的 e2e.app_login——不是任何真实项目字面量（回潮硬编码即红）
        assert 'const endpoint = "/test-login";' in setup_ts, setup_ts
        assert 'const storageKey = "app_session";' in setup_ts, setup_ts
        assert 'const tokenKey = "session_token";' in setup_ts, setup_ts
        assert "process.env.ATLAS_APP_USER" in setup_ts and "process.env.ATLAS_APP_PASSWORD" in setup_ts
        # 缺凭据 ⇒ 警告 + 空 state（不静默续跑）；失败 ⇒ 抛错
        assert "跳过登录预置" in setup_ts and "cookies: [], origins: []" in setup_ts, setup_ts
        assert "throw new Error(`[atlas] 应用靶场登录失败" in setup_ts, setup_ts


def test_setup_without_app_login_degrades_loudly() -> None:
    """契约 §7.1（RFC-20261015-02，2026-10-16 改判）：stack-profile 未声明 e2e.app_login =
    **未声明**（不再是「合法降级」）——第一阶段仍生成成功 + 生成期 WARN（升档 = 下一次真跑
    准备日推 `not_ready`，记录见 `shared/gates.md`「E2E 真跑」行）；setup 以占位默认值发射
    （凭据缺失 ⇒ 空 state + 警告，不发真实登录请求）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # app_login 是 e2e 段最后一个键（夹具约定）⇒ 切到它之前 = 整段去掉
        make(root, profile=PROFILE.split("  app_login:")[0])
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "e2e.app_login" in r.stderr, r.stderr          # 生成期 WARN（不静默）
        assert "mode: none" in r.stderr, r.stderr             # WARN 指路：无门项目的声明出口
        setup_ts = (root / "product" / "e2e" / "scripts" / "atlas-auth.setup.ts").read_text(encoding="utf-8")
        assert 'const endpoint = "/login";' in setup_ts, setup_ts  # 占位默认（未声明 ⇒ 非取证值）


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


def test_setup_mode_none_generates_no_login_facilities() -> None:
    """契约 §7.1 / shared/stack-profile.md §2（RFC-20261015-02，issue #11，2026-10-16）：
    `mode: none` = 靶场无访问门的**显式声明** ⇒ 不生成登录预置设施（`atlas-auth.setup.ts`
    不出、`playwright.config.ts` 无 storageState / setup 项目），也不打「未声明」警告
    ——声明过的形态不是降级。无门项目里那套编排没有被编排的对象（B124 同族教训）。
    变异证明 M71：none 分支仍走 storageState / setup 设施 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.split("  app_login:")[0] + "  app_login:\n    mode: none\n")
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "将跳过登录态预置" not in r.stderr, r.stderr      # 声明形态不打警告
        cfg = (root / "product" / "e2e" / "scripts" / "playwright.config.ts").read_text(encoding="utf-8")
        assert "storageState:" not in cfg, cfg                 # 预置绑定不生成（`storageState:` = 功能绑定，注释不计）
        assert "atlas-auth" not in cfg, cfg                    # setup 项目不生成
        assert "dependencies: ['setup']" not in cfg, cfg
        assert "baseURL" in cfg and "ATLAS_BASE_URL" in cfg, cfg  # 其余机制原样
        assert not (root / "product" / "e2e" / "scripts" / "atlas-auth.setup.ts").is_file()


def test_setup_mode_none_rejects_leftover_evidence_fields() -> None:
    """契约 shared/stack-profile.md §2（RFC-20261015-02）：`mode: none` 与残留取证字段互斥
    ——无门 ⇒ **全弃**（与 `fabricated` 的「收窄」相反，两条判据同构成镜像）⇒ 生成报错。
    变异证明：M69（摘掉互斥判据）⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.split("  app_login:")[0]
                  + "  app_login:\n    mode: none\n    storage_key: app_session\n")
        r = run(root, "--apply")
        assert r.returncode != 0, r.stdout
        assert "互斥" in r.stderr, r.stderr
        assert "storage_key" in r.stderr, r.stderr


def test_waitfor_renders_polling_assertions() -> None:
    """契约 §7.1（2026-09-25 补）：`waitFor` 必须渲染为**带轮询的断言**，不得退化为固定等待。

    固定等待在共享靶场必飘，且与断言是否成立无关 ⇒ 是新的假绿通道；
    条件式等待超时即失败、无后门。
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
        text = spec_of(root)
        # 轮询语义必须来自运行器原生断言 API
        assert 'toHaveText("首页", { timeout: ATLAS_WAIT_TIMEOUT_MS, useInnerText: true })' in text, text
        assert "toBeVisible({ timeout: ATLAS_WAIT_TIMEOUT_MS })" in text, text
        # 不得退化为固定等待 / sleep（与断言是否成立无关）
        assert "waitForTimeout" not in text, text


def test_value_asserts_route_through_visibility_first() -> None:
    """契约 §7.1：`text` / `contains` / `value` 须先断言元素**可见**——

    隐藏元素（面板未展开）照样有文本 ⇒ 假绿。TS 面的落点 = 读值断言统一经
    `tsVis`（不可见 ⇒ null = 不成立）与 `atlasExpectValue`（实现无关入口）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        assert "读值断言须先可见；不可见 ⇒ null（= 不成立，不抛错）" in text, text
        assert "async function tsVis(page: any, tid: string)" in text, text
        gn = _load_gen()
        spec = gn.ts_case(
            {"id": "E2E-HOME-001", "_title": "t", "step": ["goto /"],
             "expected": ['value home-title 首页'], "testid": ["home-title"]}, "/")
        assert "await atlasExpectValue(page, 'home-title'" in spec, spec


def test_delta_relative_assertion() -> None:
    """契约 §5.5（P5，2026-10-07）：`delta` 相对断言 —— 行动前采样贴**第一个提交性动作**
    （准备步骤不污染基准，与 `unchanged:` 先例同点）、行动后轮询复读（`expect.poll`）；
    值形态 / 豁免通道叠写 / 缺 step ⇒ 生成期中止；零步基线**不收** delta（无初始态语义）。
    变异证明 M38：把 delta 的行动前采样摘掉（退化为行动后单点取数）⇒ 顺序断言红。
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
        "await page.getByTestId('home-cta-btn').first().click()"
    ), ts
    assert (
        "await expect.poll(() => atlasIntOf(page.getByTestId('home-title').first()), "
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
    assert ts2.index("await page.getByTestId('home-tab-btn').first().click()") < ts2.index(
        "const __delta_home_title = await atlasIntOf"
    ) < ts2.index("await page.getByTestId('home-save-btn').first().click()"), ts2
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
    # 零步基线不收 delta
    plain = {**case, "id": "E2E-HOME-002", "_title": "普通断言", "expected": ["text home-title 首页"]}
    assert "delta" not in gn.ts_zero_step_baseline("home", "/", [case, plain])


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


if __name__ == "__main__":
    sys.exit(main())


# ---- 网络边界打桩（契约 §5.8，2026-10-12；对抗评审修订案落地）----

MOCK_CASE = CASE.replace(
    "precondition:\n  - 已打开首页\n",
    "precondition:\n  - 已打开首页\n"
    "mock:\n"
    "  - GET /api/v1/home -> fixtures/home/feed.json   # 单发（缺省 200）\n"
    "  - GET /api/v1/jobs/1 -> seq fixtures/home/p.json, 503:fixtures/home/e.json\n",
)
MOCK_PROFILE = PROFILE + "  mock:\n    mode: on\n    api_prefix: /api/\n"


def make_mock(root: Path) -> None:
    make(root, profile=MOCK_PROFILE, case=MOCK_CASE)
    fx = root / "product" / "e2e" / "fixtures" / "home"
    fx.mkdir(parents=True, exist_ok=True)
    (fx / "feed.json").write_text('{"items": []}\n', encoding="utf-8")
    (fx / "p.json").write_text('{"s": "pending"}\n', encoding="utf-8")
    (fx / "e.json").write_text('{"error": "x"}\n', encoding="utf-8")


def test_mock_compiles_to_single_dispatch_table() -> None:
    """契约 §5.8：`mock:` 行 ⇒ **单条** `context.route` 派发表（pathname+method 命中、
    query 免疫；不逐行注册 glob——注册逆序 + query 不匹配 = 两类静默穿透）；
    注册先于 goto、审计殿后；fixture 生成期内联；fail-loud（abort + 审计断言，不是
    continue）；CORS 预检；证据披露（atlas-mock 注记 + 日志行）；mock 页基线空转显式标记；
    **未启用项目的生成物零变化**（无 mock helper）。变异：route 计数 >1 / 退回 continue 即红。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_mock(root)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        spec = spec_of(root)
        assert spec.count("await page.context().route(") == 1, "必须单派发表，不逐行注册"
        assert "atlasMockTable" in spec and "atlasMockAudit" in spec
        assert "route.abort('failed')" in spec, "前缀内未命中必须 fail-loud abort"
        assert "route.continue()" in spec, "前缀外（静态资源）必须放行"
        assert "access-control-allow-origin" in spec, "跨源桩须补 CORS 头"
        assert "'atlas-mock'" in spec and "[atlas-mock]" in spec, "桩命中须双留痕（注记+日志）"
        # 时序：派发表注册先于本用例 goto；审计殿后（断言之后）
        i_mock = spec.index("const __mock = await atlasMockTable(")
        i_goto = spec.index("await page.goto(", i_mock)
        assert i_mock < i_goto
        assert spec.index("await atlasMockAudit(__mock);") > spec.index("toHaveText", i_goto)
        # fixture 生成期内联（零运行期路径解析）；seq 状态码前缀编译
        assert '"ref": "fixtures/home/feed.json"' in spec and '\\"items\\"' in spec
        assert '"status": 503' in spec
        # 派发机制面：pathname + method（query 免疫的实现判据）
        assert "u.pathname" in spec and "e.method === method" in spec
        # mock 页基线空转显式标记
        assert "空转守卫" in spec
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)  # 既有夹具（无 mock、未开通道）
        assert run(root, "--apply").returncode == 0
        assert "atlasMockTable" not in spec_of(root), "未启用项目的生成物必须零变化"


def test_mock_requires_explicit_mode_on_and_prefix() -> None:
    """契约 §5.8 防误用门（镜像 seed.mode 先例）：分片有 `mock:` 行而 `e2e.mock`
    未声明 `mode: on` ⇒ exit 2 点名用例（真实后端项目写桩 = 静默屏蔽真 API 回归）；
    `mode: on` 而 `api_prefix` 缺 ⇒ exit 2。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_mock(root)
        (root / "product" / "stack-profile.yaml").write_text(PROFILE, encoding="utf-8")  # 撤掉 mock 段
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "mode: on" in r.stderr and "E2E-HOME-001" in r.stderr, r.stderr
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_mock(root)
        (root / "product" / "stack-profile.yaml").write_text(
            PROFILE + "  mock:\n    mode: on\n", encoding="utf-8")  # on 而 prefix 缺 ⇒ 默认兜底为 /
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr
        assert 'const ATLAS_MOCK_PREFIX = "/";' in spec_of(root)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_mock(root)
        (root / "product" / "stack-profile.yaml").write_text(
            PROFILE + "  mock:\n    mode: on\n    api_prefix: bad prefix\n", encoding="utf-8")
        r = run(root, "--apply")
        assert r.returncode == 2 and "api_prefix" in r.stderr, r.stderr


def test_mock_mode_auto_continue_passthrough() -> None:
    """验证 mode: auto 下生成物具备未命中路由 route.continue() 穿透逻辑。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_mock(root)
        (root / "product" / "stack-profile.yaml").write_text(
            PROFILE + "  mock:\n    mode: auto\n", encoding="utf-8"
        )
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr
        spec = spec_of(root)
        assert 'const ATLAS_MOCK_MODE = "auto";' in spec
        assert 'const ATLAS_MOCK_PREFIX = "/";' in spec
        assert "if (ATLAS_MOCK_MODE === 'auto') {\n      await route.continue();\n      return;\n    }" in spec


def test_mock_grammar_anchor_fixture_fail_loud() -> None:
    """契约 §5.8 文法封闭 + 锚定门 + fixture 存在：三口均 exit 2 并点名（fail-loud，
    不静默降级）。"""
    good = "  - GET /api/v1/home -> fixtures/home/feed.json   # 单发（缺省 200）"
    bad_lines = [
        "  - FETCH /api/v1/home -> fixtures/home/feed.json",    # 方法枚举外
        "  - GET /v2/home -> fixtures/home/feed.json",          # 越界（不在 /api/ 内）
        "  - GET /api/v1/home -> fixtures/home/missing.json",   # fixture 不存在
        "  - GET /api/v1/home -> fixtures/home/feed.json extra",  # 右段语法不识
    ]
    for bad in bad_lines:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_mock(root)
            (root / "product" / "e2e" / "cases" / "home.md").write_text(
                MOCK_CASE.replace(good, bad), encoding="utf-8")
            r = run(root, "--apply")
            assert r.returncode == 2, (bad, r.returncode, r.stdout + r.stderr)
            assert "mock" in r.stderr, r.stderr


def test_app_login_fabricated_setup() -> None:
    """契约 §5.8/§7.1：`app_login.mode: fabricated` ⇒ setup 不发真实登录请求、直写固定
    假令牌（必填收窄为 storage_key，缺它 ⇒ exit 2）。真实登录语义只属缺省 real
    （既有 setup 断言由 test_runner_emits_skip_baseline_first_and_setup 承载）。"""
    fab = PROFILE.split("  app_login:")[0] + \
        "  app_login:\n    mode: fabricated\n    storage_key: app_session\n"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=fab)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        setup = (root / "product" / "e2e" / "scripts" / "atlas-auth.setup.ts").read_text(encoding="utf-8")
        assert "request.post" not in setup, "fabricated 不得发真实登录请求"
        assert "ATLAS_APP_USER" not in setup
        assert "atlas-fabricated-token" in setup and "app_session" in setup
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=fab.replace("    storage_key: app_session\n", ""))
        r = run(root, "--apply")
        assert r.returncode == 2 and "storage_key" in r.stderr, r.stderr


def test_atlas_hold_ts_emitted_and_imported_by_specs() -> None:
    """契约 §10.1 / §7.1（2026-10-12 控制台 node 轨迁移批）：
    ① 页面脚本必须从 `./atlas-hold` 引入 `test`/`expect`（不得直连 `@playwright/test`，
       否则控制台持窗+哨兵失效）；
    ② `atlas-hold.ts` 必须随 `--apply` 发射，包含 `ATLAS_RESULT_FILE` 哨兵写盘
       与 `ATLAS_KEEP_OPEN` 延时等人工关窗逻辑。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        spec = spec_of(root)
        assert "from './atlas-hold';" in spec, "页面脚本必须从 ./atlas-hold 引入"
        hold_file = root / "product" / "e2e" / "scripts" / "atlas-hold.ts"
        assert hold_file.is_file(), "必须发射 atlas-hold.ts"
        hold_src = hold_file.read_text(encoding="utf-8")
        assert "ATLAS_RESULT_FILE" in hold_src
        assert "ATLAS_KEEP_OPEN" in hold_src
        assert "context.pages().length === 0" in hold_src


def test_retired_page_spec_cleaned_and_visible() -> None:
    """F9（2026-10-14）：用例已退役（不再被枚举的页）残留在 scripts_dir 的生成物页脚本
    —— Playwright 默认 glob 会在真跑时拾起它（R3 实测 2 failed）。行为契约：
    dry-run 报 changed（「生成物最新」门可见、要求 `--apply` 收口）；`--apply` 清扫；
    无 AUTO-GENERATED 标记的手写文件**不得**被清扫。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        scripts = root / "product" / "e2e" / "scripts"
        orphan = scripts / "retired.spec.ts"
        orphan.write_text(
            "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py (runner=node-playwright)；"
            "重跑覆盖\nimport { test } from './atlas-hold';\n"
            "test('E2E-RETIRED-001 退役页残留', async () => {});\n",
            encoding="utf-8")
        handmade = scripts / "handmade.spec.ts"
        handmade.write_text("// 手写文件（无生成器标记），清扫必须绕开\n", encoding="utf-8")

        dry = run(root, "--json")
        assert dry.returncode == 0, dry.stderr
        data = json.loads(dry.stdout)
        listed = [r["file"] for r in data["results"] if r.get("changed")]
        assert any("retired.spec.ts" in f for f in listed), listed
        assert not any("handmade.spec.ts" in f for f in listed), listed

        assert run(root, "--apply").returncode == 0
        assert not orphan.exists(), "退役页残留必须被 --apply 清扫"
        assert handmade.exists(), "无生成器标记的手写文件不得被清扫"

        dry2 = run(root, "--json")
        data2 = json.loads(dry2.stdout)
        assert not any("retired.spec.ts" in r["file"] for r in data2["results"]), data2["results"]


def test_f24_zero_step_probe_exemptions() -> None:
    """F24（R6「融与化」）：
    1. 含 mock 的用例断言整组跳过零步基线探针集，并在生成物中显式披露豁免注释（点名用例 ID）；
    2. 普通非 mock 用例断言保持进入探针集（契约 §5.6 R9 守卫）；
    3. 纯 mock 页面在基线不挂桩环境下依然生成带空转守卫的基线测试。"""
    spec = importlib.util.spec_from_file_location("gen_e2e", GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    cases = [
        # 用例 1：含 mock 的用例（初态由桩环境定义，不参与裸基线探针）
        {
            "id": "E2E-HOME-MOCK",
            "mock": ["GET /api/quote -> fixtures/quote.json"],
            "testid": ["quote-card"],
            "expected": [
                "visible quote-card # 外部提醒区域",
                "text quote-card 今日箴言",
            ],
        },
        # 用例 2：普通用例（普通断言进探针）
        {
            "id": "E2E-HOME-REGULAR",
            "testid": ["home-cta-btn", "home-title", "home-container"],
            "step": ["click home-cta-btn"],
            "expected": [
                "visible home-container # 容器静态在场，未被 step 操作，在 testid 块内 ⇒ 规则二豁免",
                "visible home-cta-btn # 按钮被 step click 操作了 ⇒ 照入探针，遵守恒真守卫",
                "text home-title 首页 # 标题状态断言 ⇒ 照入探针",
            ],
        },
    ]

    code = gen.ts_zero_step_baseline("home", "http://127.0.0.1:8000/home", cases)
    assert code, "必须生成零步基线代码"
    # 1. 披露 mock 豁免注释并指名用例 ID
    assert "mock 用例断言不参与零步基线" in code
    assert "E2E-HOME-MOCK" in code

    # 解析嵌入的 probes JSON
    m = re.search(r"const ATLAS_ZS_home = (\{.*?\});", code)
    assert m, f"未提取到探针 JSON: {code}"
    zs_data = json.loads(m.group(1))
    probes = zs_data["probes"]
    labels = [p["label"] for p in probes]

    # 验证豁免：
    # mock 用例断言全都不在 probes
    assert not any("E2E-HOME-MOCK" in l for l in labels), labels
    # regular 用例中，未被 step 操作的容器 visible 豁免
    assert not any("visible home-container" in l for l in labels), labels

    # 验证普通用例断言照入：
    assert any("visible home-cta-btn" in l for l in labels), labels
    assert any("text home-title 首页" in l for l in labels), labels


def test_f21_baseline_shape_lock_and_sort_precedence() -> None:
    """F21（R6「融与化」）：
    1. 形状锁：basis 键必须满足 status=WARN 且 checks=[] 且 reviewed=0 且 expected>=1；
    2. Critical 先行：即使声明 basis 键，若 status=FAIL 且含 Critical，照旧被拒；
    3. 同日排序消歧：同一天内真审报告优于基线报告。"""
    spec = importlib.util.spec_from_file_location("gen_e2e", GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rdir = root / "product" / "e2e" / "reviews"
        rdir.mkdir(parents=True)

        # 1. 形状锁负向：带 basis 但 status 不是 WARN
        bad_basis_dir = rdir / "2026-10-15-bad-basis"
        bad_basis_dir.mkdir()
        (bad_basis_dir / "review.json").write_text(
            json.dumps({"ok": True, "status": "PASS", "basis": "auto-baseline", "expected": 1, "reviewed": 1}),
            encoding="utf-8",
        )
        level, _ = gen.review_report_status(rdir)
        assert level == "invalid", level

        # 2. Critical 先行：status=FAIL 且含 Critical，即使用 basis 也必须报 critical
        (bad_basis_dir / "review.json").write_text(
            json.dumps({
                "ok": False,
                "status": "FAIL",
                "basis": "auto-baseline",
                "checks": [{"level": "Critical", "check": "致命缺口"}],
            }),
            encoding="utf-8",
        )
        level, detail = gen.review_report_status(rdir)
        assert level == "critical" and "Critical" in detail, (level, detail)

        # 3. 同日排序消歧：同一天下存在基线报告与真审报告
        # 基线目录
        baseline_dir = rdir / "2026-10-16-adopt-baseline"
        baseline_dir.mkdir()
        (baseline_dir / "review.json").write_text(
            json.dumps({
                "ok": True,
                "status": "WARN",
                "basis": "auto-baseline",
                "expected": 1,
                "reviewed": 0,
                "checks": [],
            }),
            encoding="utf-8",
        )
        # 真审目录（字母排序可能在 baseline 后面或前面，如 2026-10-16-real-review）
        real_dir = rdir / "2026-10-16-real-review"
        real_dir.mkdir()
        (real_dir / "review.json").write_text(
            json.dumps({
                "ok": True,
                "status": "PASS",
                "expected": 1,
                "reviewed": 1,
                "checks": [],
            }),
            encoding="utf-8",
        )
        # 即使 baseline_dir 字母顺序排在 real 之前，latest 必须挑中 real_dir
        chosen = gen.latest_review_report(rdir)
        assert chosen == real_dir, f"挑中={chosen}, 预期={real_dir}"


def test_f21_bootstrap_review_cli() -> None:
    """F21: --bootstrap-review 输出机器可读任务包。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        r = run(root, "--bootstrap-review")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["kind"] == "atlas-bootstrap-review-package"
        assert data["expected_shards"] >= 1
        assert "D1-D10" in data["dimensions_reference"]


def test_guard_only_watches_first_step_target() -> None:
    """防守卫死锁：前置在场守卫仅断言 step[0] 的操作目标，动态 testid 不被提前判定死锁；
    若 step[0] 为 goto/refresh 等无 testid 操作，守卫安全为空。
    """
    gn = _load_gen()
    # 场景 1：step[0] 是有 testid 的动作，testid 列表包含动态元素
    case1 = {
        "id": "E2E-DYNAMIC-001",
        "_title": "动态创建元素",
        "step": ["click static-create-btn", "click dynamic-item-delete-btn"],
        "expected": ["visible dynamic-item"],
        "testid": ["static-create-btn", "dynamic-item", "dynamic-item-delete-btn"],
    }
    spec1 = gn.ts_case(case1, "/dynamic")
    # 守卫只断言 static-create-btn，绝不断言 dynamic-item
    assert "for (const id of [\"static-create-btn\"]) {" in spec1, spec1
    assert "dynamic-item" not in spec1.split("await page.goto")[1].split("for (const id")[1].split("}")[0]

    # 场景 2：step[0] 是无 testid 的 goto/refresh，守卫安全为空
    case2 = {
        "id": "E2E-DYNAMIC-002",
        "_title": "刷新后检查",
        "step": ["refresh", "click static-btn"],
        "expected": ["visible static-btn"],
        "testid": ["static-btn"],
    }
    spec2 = gn.ts_case(case2, "/dynamic")
    assert "for (const id of []) {" in spec2, spec2


def test_strict_mode_actions_and_asserts_use_first() -> None:
    """Strict Mode 兼容：单体动作与单体状态断言统一发射 .first() / .filter().first()，
    避免多实例同名元素抛出 strict mode violation；count 保持原样不加 .first()。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-STRICT-001",
        "_title": "多实例单体操作与断言",
        "step": [
            "click item-btn",
            "hover item-card",
            "fill item-input hello",
            "press item-input Enter",
            "check item-checkbox",
            "uncheck item-checkbox",
        ],
        "expected": [
            "visible item-card",
            "hidden item-badge",
            "enabled item-btn",
            "disabled item-del-btn",
            "checked item-checkbox",
            "unchecked item-checkbox",
            "text item-title 标题",
            "contains item-desc 关键字",
            "count item-card 3",
        ],
        "testid": ["item-btn", "item-card", "item-input", "item-checkbox", "item-badge", "item-del-btn", "item-title", "item-desc"],
    }
    spec = gn.ts_case(case, "/strict")
    # 动作全部带 .first()
    assert "await page.getByTestId('item-btn').first().click();" in spec
    assert "await page.getByTestId('item-card').first().hover();" in spec
    assert "await page.getByTestId('item-input').first().fill(\"hello\");" in spec
    assert "await page.getByTestId('item-input').first().press(\"Enter\");" in spec
    assert "await page.getByTestId('item-checkbox').first().check();" in spec
    assert "await page.getByTestId('item-checkbox').first().uncheck();" in spec
    # 断言带 .first()
    assert "await expect(page.getByTestId('item-card').first()).toBeVisible();" in spec
    assert "await expect(page.getByTestId('item-badge').first()).toBeHidden();" in spec
    assert "await expect(page.getByTestId('item-btn').first()).toBeEnabled();" in spec
    assert "await expect(page.getByTestId('item-del-btn').first()).toBeDisabled();" in spec
    assert "await expect(page.getByTestId('item-checkbox').first().isChecked()).toBe(true)" not in spec # 使用了 toBeChecked
    assert "await expect(page.getByTestId('item-checkbox').first()).toBeChecked();" in spec
    assert "await expect(page.getByTestId('item-checkbox').first()).not.toBeChecked();" in spec
    assert "await expect(page.getByTestId('item-title').first()).toHaveText(\"标题\");" in spec
    assert "await expect(page.getByTestId('item-desc').filter({ hasText: \"关键字\" }).first()).toBeVisible();" in spec
    # count 不加 .first()
    assert "await expect(page.getByTestId('item-card')).toHaveCount(Number(\"3\"));" in spec


def test_auth_setup_idempotent_preserves_existing_state() -> None:
    """真实会话保护：生成的 setup 脚本在 stateFile 存在且非空时跳过覆写，保护开发者录制会话。"""
    fab = PROFILE.split("  app_login:")[0] + \
        "  app_login:\n    mode: fabricated\n    storage_key: app_session\n"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=fab)
        assert run(root, "--apply").returncode == 0
        setup = (root / "product" / "e2e" / "scripts" / "atlas-auth.setup.ts").read_text(encoding="utf-8")
        assert "existsSync(stateFile)" in setup
        assert "readFileSync(stateFile" in setup
        assert "跳过覆写" in setup




