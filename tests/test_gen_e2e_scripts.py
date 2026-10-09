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
        assert "await page.getByTestId('home-cta-btn').click();" in text, text
        # expected → 断言（不是只做存在性检查）
        assert 'await expect(page.getByTestId(\'home-title\')).toHaveText("首页");' in text, text
        assert "await expect(page.getByTestId('home-cta-btn')).toBeVisible();" in text, text
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
        pre = text.index("await expect(page.getByTestId('home-create-project-modal')).toBeHidden();")
        arrange = text.index("await page.getByTestId('home-cta-btn').click();")
        submit = text.index("await page.getByTestId('home-create-submit-btn').click();")
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
        target = "await expect(page.getByTestId('home-create-project-modal')).toBeHidden();"
        first = text.index(target)
        submit = text.index("await page.getByTestId('home-create-submit-btn').click();")
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
        assert "await expect(page.getByTestId('home-cta-btn')).toBeVisible();" in text, text
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
    c = text.index("await page.getByTestId('home-cta-btn').click();")
    a = text.index("await expect(page.getByTestId('home-cta-btn')).toBeVisible();")
    z = text.index("await expect(page.getByTestId('home-cta-btn')).toBeHidden();")
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
        guard = ("for (const id of [\"home-cta-btn\", \"home-title\"]) {\n"
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
    """契约 §7.1（3509 §B101）：stack-profile 未声明 e2e.app_login = **合法降级**——
    生成成功 + 生成期 WARN；setup 以占位默认值发射（凭据缺失 ⇒ 空 state + 警告，
    不发真实登录请求）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # app_login 是 e2e 段最后一个键（夹具约定）⇒ 切到它之前 = 整段去掉
        make(root, profile=PROFILE.split("  app_login:")[0])
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "e2e.app_login" in r.stderr, r.stderr          # 生成期 WARN（不静默）
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
