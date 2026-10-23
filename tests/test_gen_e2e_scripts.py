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
import shutil
import tempfile
from pathlib import Path

import pytest
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
        # 紧跟其后必须是**元素齐全守卫的页面就绪锚点**（D114 拆两段后的第一段；
        # 用例自身的 goto 在它之后）
        assert "atlasAwaitAnyDeclared(page," in seg[i_guard:i_guard + 200], seg[i_guard:i_guard + 200]


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


# ── D109（2026-10-18）：`参数:` —— 宿主注入型 URL 参数（内联 + 门重靶）─────────────
# base 带 query（模拟真项目：`?switchAgent=7202` 那类 tenant 前提）——**并集**与零变化的判别面。
PROFILE_QUERY = PROFILE.replace("app_base_url: http://127.0.0.1:8000",
                                "app_base_url: http://127.0.0.1:8000/?tenant=9"
                                ) + "  query_preset:\n    keys:\n      - flag\n"
QUERY_CASE = CASE.replace("step:", "参数:\n  - flag\nstep:", 1).replace(
    "  - click home-cta-btn          # 点击主操作按钮",
    "  - goto /home?flag=on          # 宿主以查询串注入前提后载入\n"
    "  - click home-cta-btn          # 点击主操作按钮")

# 契约 §5.5 `hash参数:`（2026-10-22，HashRouter）：`#` 之后的 hash 查询串。
# base query 仍在 `#` 之前（tenant），hash 参数在 `#` 之后，验证两者不会互相吞掉。
PROFILE_HASH = PROFILE.replace("app_base_url: http://127.0.0.1:8000",
                               "app_base_url: http://127.0.0.1:8000/?tenant=9"
                               ) + "  query_preset:\n    hash_keys:\n      - flag\n"
INDEX_HASH = INDEX.replace("| home | /home | home |", "| home | /home#/detail | home |")
HASH_CASE = CASE.replace("step:", "hash参数:\n  - flag\nstep:", 1).replace(
    "  - click home-cta-btn          # 点击主操作按钮",
    "  - goto /home#/detail?flag=on  # 宿主以 hash 查询串注入前提\n"
    "  - click home-cta-btn          # 点击主操作按钮")


def test_injected_param_carried_to_guard_and_goto() -> None:
    """`参数:` 的值（内联在 `goto` 里）必须到达**两处导航面**：元素齐全守卫 + 用例自己的 `goto`。

    为何守卫也要：参数决定「哪些元素在场」的页面上，守卫导航不带前提 ⇒ 守卫在 goto 后即红
    （D104 的「三处不是一处」同族教训）。并集口径：base 的 `tenant` 不得被丢掉。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=QUERY_CASE, profile=PROFILE_QUERY)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        seg = text[text.index("E2E-HOME-001"):]
        # 守卫导航（用例体首条 goto）与用例自己的 goto：都带 base ⊕ 内联参数
        assert seg.count("await page.goto('/home?tenant=9&flag=on');") >= 2, seg[:800]
        # 守卫紧随其后就是页面就绪锚点（而不是被 step 抢到前面）
        i_guard = seg.index("await page.goto('/home?tenant=9&flag=on');")
        assert "atlasAwaitAnyDeclared(page," in seg[i_guard:i_guard + 200], seg[i_guard:i_guard + 200]


def test_zero_step_baseline_carries_no_injected_param() -> None:
    """零步基线**不施加** `参数:`（前提构造不计入基线）——护栏：基线测试体里不得出现该参数。

    否则依赖该前提的断言会在基线（默认态）下成立 ⇒ 恒真门（§5.6 R9）误报。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=QUERY_CASE, profile=PROFILE_QUERY)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        # 基线的导航参数在**数据对象**里（测试体只是调 helper，故不能断言测试体）
        data_obj = text.split("const ATLAS_ZS_home = ", 1)[1].split("\n", 1)[0]
        assert "flag=on" not in data_obj, data_obj      # 前提构造不计入基线
        assert "tenant=9" in data_obj, data_obj        # base query 照旧（不是把基线整体关掉）


def test_injected_param_without_whitelist_aborts() -> None:
    """坏输入：项目未声明 `e2e.query_preset.keys` ⇒ 生成器 exit 2（不猜、不静默降级）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=QUERY_CASE, profile=PROFILE)
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "参数" in r.stderr, r.stderr


def test_injected_param_key_outside_whitelist_aborts() -> None:
    """坏输入：键在白名单外 ⇒ 生成器 exit 2。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=QUERY_CASE,
             profile=PROFILE + "  query_preset:\n    keys:\n      - otherFlag\n")
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "白名单" in r.stderr, r.stderr


def test_injected_param_dead_declaration_aborts() -> None:
    """坏输入：`参数:` 声明了键、但没有任何 `goto` 用到 ⇒ 生成器 exit 2（死声明）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=CASE.replace("step:", "参数:\n  - flag\nstep:", 1), profile=PROFILE_QUERY)
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "死声明" in r.stderr, r.stderr


def test_injected_param_bad_value_aborts() -> None:
    """坏输入：越形态的查询值 ⇒ 生成器 exit 2（不静默转义）。

    为何必须咬：生成物里 URL 嵌在 `page.goto('<url>')` 的**单引号内**。
    取值范围 = 不被 `parse_line` 的分词吞掉的字符（**空白**会被用例文本期的另一道门咬住，
    且 `parse_line` 会把它静默截断——两道门各管一段）。
    """
    for bad in ("flag=a'b", "flag=a\\\\b", "flag=a=b"):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make(root, case=QUERY_CASE.replace("goto /home?flag=on", f"goto /home?{bad}"),
                 profile=PROFILE_QUERY)
            r = run(root, "--apply")
            assert r.returncode == 2, (bad, r.returncode, r.stdout + r.stderr)
            assert "越形态" in r.stderr, (bad, r.stderr)
    # `&` 会被劈成第二个键（未声明）⇒ 同样是 exit 2（报的是键不在声明内）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=QUERY_CASE.replace("goto /home?flag=on", "goto /home?flag=a&b"),
             profile=PROFILE_QUERY)
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "未在本用例" in r.stderr, r.stderr


def test_hash_param_carried_to_guard_and_goto() -> None:
    """`hash参数:` 的值必须到达**守卫**与用例自己的 `goto`，且 base query 留在 `#` 之前。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=HASH_CASE, profile=PROFILE_HASH, index=INDEX_HASH)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        seg = text[text.index("E2E-HOME-001"):]
        merged = "await page.goto('/home?tenant=9#/detail?flag=on');"
        assert seg.count(merged) >= 2, seg[:900]
        i_guard = seg.index(merged)
        assert "atlasAwaitAnyDeclared(page," in seg[i_guard:i_guard + 200], seg[i_guard:i_guard + 200]


def test_zero_step_baseline_carries_no_hash_param() -> None:
    """零步基线**不施加** `hash参数:`（与 `参数:` 同纪律）——基线数据对象与测试体都不得出现。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=HASH_CASE, profile=PROFILE_HASH, index=INDEX_HASH)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        data_obj = text.split("const ATLAS_ZS_home = ", 1)[1].split("\n", 1)[0]
        assert "flag=on" not in data_obj, data_obj
        assert "tenant=9" in data_obj, data_obj
        marker = "test('test_home__zero_step_baseline'"
        baseline_body = text.split(marker, 1)[1].split("\ntest(", 1)[0]
        assert "flag=on" not in baseline_body, baseline_body


def test_hash_param_without_whitelist_aborts() -> None:
    """坏输入：项目未声明 `e2e.query_preset.hash_keys` ⇒ 生成器 exit 2。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=HASH_CASE, profile=PROFILE, index=INDEX_HASH)
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "hash_keys" in r.stderr, r.stderr


def test_hash_param_dead_declaration_aborts() -> None:
    """坏输入：`hash参数:` 声明了键、但没有任何 `goto` 的 hash 查询用到 ⇒ exit 2。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=CASE.replace("step:", "hash参数:\n  - flag\nstep:", 1),
             profile=PROFILE_HASH, index=INDEX_HASH)
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "死声明" in r.stderr, r.stderr


def test_hash_param_bad_value_aborts() -> None:
    """坏输入：hash 查询值含越形态字符 ⇒ 生成器 exit 2（不静默转义）。"""
    bad_case = HASH_CASE.replace("goto /home#/detail?flag=on", "goto /home#/detail?flag=a'b")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=bad_case, profile=PROFILE_HASH, index=INDEX_HASH)
        r = run(root, "--apply")
        assert r.returncode == 2, (r.returncode, r.stdout + r.stderr)
        assert "越形态" in r.stderr, r.stderr


def test_hash_query_merge_helpers() -> None:
    """`url_merge` 的 hash 查询原语：解析 / 追加 / 剥离 / 与 base query 求并集。"""
    spec = importlib.util.spec_from_file_location("gen_e2e_hash_merge", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    um = mod.url_merge
    assert um.hash_query_of("/a#/h?k=v") == "k=v"
    assert um.hash_query_of("/a?t=1#/h?k=v") == "k=v"
    assert um.hash_query_of("/a#/h") == ""
    assert um.hash_query_keys("/a#/h?k=v&x=1") == ["k", "x"]
    assert um.append_hash_query("/a#/h", "k=v") == "/a#/h?k=v"
    assert um.append_hash_query("/a#/h?x=1", "k=v") == "/a#/h?x=1&k=v"
    assert um.append_hash_query("/a#/h?k=old", "k=new") == "/a#/h?k=new"
    assert um.append_hash_query("/a", "k=v") == "/a"
    assert um.strip_query("/a?t=1#/h?k=v") == "/a#/h?k=v"
    assert um.strip_hash_query("/a?t=1#/h?k=v") == "/a?t=1#/h"
    assert um.strip_queries("/a?t=1#/h?k=v") == "/a#/h"
    assert um.merge_base_query("/a#/h?k=v", "http://h/?t=1") == "/a?t=1#/h?k=v"
    assert um.merge_base_query("/a#/h?k=v", "http://h/") == "/a#/h?k=v"


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
        assert "await page.getByTestId('home-cta-btn').first().click({ force: true });" in text, text
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
        arrange = text.index("await page.getByTestId('home-cta-btn').first().click({ force: true });")
        submit = text.index("await page.getByTestId('home-create-submit-btn').first().click({ force: true });")
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
        submit = text.index("await page.getByTestId('home-create-submit-btn').first().click({ force: true });")
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

    # 契约 §5.5（2026-10-19 补，`DESIGN.md` D116）：`""` / `(空)` ⇒「该属性**缺席或为空串**」。
    # 发射侧必须 `?? ''` 归一（缺席时 `getAttribute` 得 `null`，直接写 `== ""` 是半通状态）；
    # `toHaveAttribute(name, "")` 实测在缺席时 FAIL ⇒ 不得回退到它。
    for line in ('attr home-cta-btn aria-label ""', "attr home-cta-btn aria-label (空)"):
        out = ts(line)
        assert "?? '').toBe('')" in out, out
        assert 'toHaveAttribute("aria-label"' not in out, out

    # 非空期望逐字节不变（零回归承诺）：仍走 `toHaveAttribute` 原路径
    out = ts("attr home-cta-btn aria-label 说明")
    assert 'toHaveAttribute("aria-label", "说明")' in out, out
    assert "?? ''" not in out, out


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


def test_value_reads_visible_text_excluding_a11y_mirror() -> None:
    """契约 §5.5（D133，2026-10-23）：`value` 读**可见文本**，不得把视觉隐藏的 a11y
    播报节点算进去。

    现场（百炼/v3 邮件工作流）：Ant Design Select 在用户交互后向触发器内注入
    `aria-live` 播报 span（`opacity:0`），`innerText` 把选中文案读两遍
    （`模式一…\\n模式一…`）⇒ `value` 断言假红。本钉从生成物抽出 `atlasVisibleText`
    在 Node 里真求值：隐藏子树不计入、读完 style 原样恢复；同时钉发射面改用该助手。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
    assert "async function atlasVisibleText(" in text, text[:2000]
    assert "await atlasVisibleText(el)" in text, text
    # 探针侧（atlasValueOf）也必须走同一助手；只钉断言侧会让探针回退 innerText 仍绿
    assert "    : atlasVisibleText(l);" in text, "atlasValueOf 探针未走可见文本助手"
    # 回归：非原生元素不得再走 innerText 直读
    assert "toHaveText(v, { useInnerText: true })" not in text, text

    m = re.search(r"async function atlasVisibleText\(loc: any\): Promise<string> \{.*?\n\}\n", text, re.S)
    assert m, "未找到 atlasVisibleText 定义"
    # Node 不能直接 eval TS 注解：仅剥类型标注，逻辑逐字保留。
    js_src = (m.group(0)
              .replace("(loc: any): Promise<string>", "(loc)")
              .replace("(e: HTMLElement)", "(e)")
              .replace("const hidden: { el: HTMLElement; style: string | null }[] = []", "const hidden = []")
              .replace(" as HTMLElement[]", "")
              .replace("(node as any)", "node"))
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用，跳过可见文本求值")
    script = """
const factory = new Function(__SRC__ + "\\nreturn atlasVisibleText;");
const helper = factory();
function node({ text = "", opacity = 1, children = [] } = {}) {
  const n = {
    _hidden: false,
    _styleAttr: opacity === 0 ? "opacity: 0;" : null,
    children,
    text,
    style: { setProperty(name, value) { if (name === "display") { n._hidden = true; n._styleAttr = `display: ${value};`; } } },
    getAttribute(name) { return name === "style" ? n._styleAttr : null; },
    setAttribute(name, value) { if (name === "style") { n._styleAttr = value; n._hidden = /display\\s*:\\s*none/.test(String(value)); } },
    removeAttribute(name) { if (name === "style") { n._styleAttr = null; n._hidden = false; } },
    checkVisibility(opts = {}) { const opacityHidden = opts.opacityProperty === true && opacity === 0; return !n._hidden && !opacityHidden; },
    querySelectorAll() { return children.flatMap((c) => [c, ...c.querySelectorAll()]); },
  };
  Object.defineProperty(n, "innerText", {
    get() { return [n.text, ...children.filter((c) => !c._hidden).map((c) => c.innerText)].join(""); },
  });
  return n;
}
(async () => {
  const label = "模式一：读取邮件（获取全文，可带附件）";
  const shown = node({ text: label });
  const live = node({ text: label, opacity: 0 });
  const rootEl = node({ children: [shown, live] });
  const loc = { evaluate: async (fn) => fn(rootEl) };
  const value = await helper(loc);
  process.stdout.write(JSON.stringify({ value, restored: live.getAttribute("style"), hidden: live._hidden, label }));
})().catch((err) => { console.error(err); process.exit(1); });
"""
    script = script.replace("__SRC__", json.dumps(js_src, ensure_ascii=False))
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    assert got["value"] == got["label"], f"隐藏的 a11y 播报被计入 value：{got}"
    assert got["restored"] == "opacity: 0;", f"采值后未恢复隐藏节点原始 style：{got}"
    assert got["hidden"] is False, f"采值后隐藏节点仍处于 display:none：{got}"


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


def test_upload_renders_esm_safe_path_for_module_projects() -> None:
    """D123（2026-10-20）：`package.json` 声明 `type: module` 时生成物按 ESM 执行，
    `__dirname` 不存在（实测 ReferenceError）⇒ 路径须改用 `import.meta.url` 解析；
    CJS 项目保持 `resolve(__dirname, …)` 原形态（零变化承诺）。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-HOME-001",
        "_title": "投放音频样本",
        "step": ["goto /", "upload home-cta-btn uploads/sample.wav"],
        "expected": ["visible home-cta-btn"],
        "testid": ["home-cta-btn"],
    }
    spec = gn.ts_case(case, "/", "", True)
    assert ("setInputFiles(fileURLToPath(new URL('../fixtures/uploads/sample.wav', import.meta.url)));"
            in spec), spec
    assert "__dirname" not in spec, spec

    # 端到端：type=module 的项目 ⇒ 头部导入 node:url，产物无 __dirname
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=UPLOAD_CASE)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        fx = root / "product" / "e2e" / "fixtures" / "uploads"
        fx.mkdir(parents=True)
        (fx / "sample.wav").write_text("RIFF", encoding="utf-8")
        r = run(root, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        ts = spec_of(root)
    assert "import { fileURLToPath } from 'node:url';" in ts, ts
    assert "__dirname" not in ts, ts
    assert ("setInputFiles(fileURLToPath(new URL('../fixtures/uploads/sample.wav', import.meta.url)));"
            in ts), ts


# 契约 §7.1：§5.5 的**每一个**动作动词也必须有渲染分支并配样例（与断言动词同一道守恒门）。
ACTION_SAMPLES = {
    "click": "home-cta-btn",
    "fill": "home-title 首页",
    "select": "home-title 首页",
    "check": "home-cta-btn",
    "uncheck": "home-cta-btn",
    "press": "home-cta-btn Enter",
    "type": "home-title 首页",
    "hover": "home-cta-btn",
    "refresh": "",
    "goto": "/home",
    "waitFor": "home-cta-btn",
    "download": "home-cta-btn *.txt",
    "upload": "home-cta-btn uploads/sample.txt",
    "dispatch": "home-cta-btn",
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


def test_type_verb_emits_press_sequentially_without_clearing() -> None:
    """契约 §5.5（D134，2026-10-23）：`type` 渲染为 `pressSequentially`（逐字键入，
    不清空原值），支持 `[N]` 下标；空值 ⇒ 报错中止（不静默空转）。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-TYPE-001",
        "_title": "逐字输入日期",
        "step": ["type date-input[1] 2026-10-01"],
        "expected": ["visible date-input"],
        "testid": ["date-input"],
    }
    spec = gn.ts_case(case, "/")
    assert "await page.getByTestId('date-input').nth(1).pressSequentially(\"2026-10-01\");" in spec
    assert ".fill(" not in spec
    assert ".clear(" not in spec
    with pytest.raises(ValueError, match="type"):
        gn.ts_case({
            "id": "E2E-TYPE-002",
            "_title": "空值中止",
            "step": ["type date-input"],
            "expected": ["visible date-input"],
            "testid": ["date-input"],
        }, "/")


def test_dispatch_verb_emits_synthetic_event_without_force() -> None:
    """契约 §5.5（2026-10-17）：`dispatch` 渲染为 `dispatchEvent('click')`（合成事件直发，
    不做 hit-testing / 可点性检查，不追加 force）；无第三位（值域封闭，出现 ⇒ 报错中止）。
    同用例内的 `click` 仍走缺省 force——两动词互不波及。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-HOME-002",
        "_title": "合成事件直发",
        "step": ["dispatch home-cta-btn", "click home-cta-btn"],
        "expected": ["visible home-cta-btn"],
        "testid": ["home-cta-btn"],
    }
    spec = gn.ts_case(case, "/")
    assert "await page.getByTestId('home-cta-btn').first().dispatchEvent('click');" in spec, spec
    d = spec.index("dispatchEvent('click')")
    f = spec.index(".click({ force: true });")
    assert d < f, spec
    try:
        gn.ts_case({**case, "step": ["dispatch home-cta-btn native"]}, "/")
    except ValueError as e:
        assert "dispatch" in str(e) and "native" in str(e), e
    else:
        raise AssertionError("dispatch 第三位必须被拒（值域封闭），不得静默吸收")


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
    c = text.index("await page.getByTestId('home-cta-btn').first().click({ force: true });")
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
    """契约 §7.1（`3509 §B99`②）：元素齐全守卫必须**自动等待**判定。

    2026-10-19（DESIGN D114，issue #26）起守卫拆两段：① **页面就绪锚点**
    `atlasAwaitAnyDeclared(...)`（内部 `expect.poll` 原生轮询；一个都不在场 ⇒ 超时并点名整份清单）；
    ② **纯在场声明**（声明了但 step/expected 都没触达过的 id）仍逐个 `toHaveCount(1)`。
    CASE 夹具两项都被 step/expected 触达 ⇒ **只发锚点**、不得再发 presence 循环（否则即把
    测试义务推回实现侧）；锚点带**全量**清单，任何一段都不得退化为「即时 `count()` 判存在性」。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        # 守卫面 = 该用例 `testid:` **应然清单**（2026-10-16，issue #R2；CASE 夹具两项）
        anchor = ('await atlasAwaitAnyDeclared(page, ["home-cta-btn", "home-title"], '
                  'ATLAS_WAIT_TIMEOUT_MS);')
        assert anchor in text, text[:1200]
        # 两项均被触达 ⇒ 不得再出现「全量清单的 presence 循环」（D114；
        # helper 内部的 for 循环不在此列）
        assert 'for (const id of ["home-cta-btn", "home-title"])' not in text, text[:1200]
        # 自动等待而非即时判定：锚点内部走 expect.poll，且在失败消息里点名整份清单
        helper = text.split("async function atlasAwaitAnyDeclared")[1].split("\n}")[0]
        assert "expect.poll(" in helper, helper
        assert "无一在场" in helper, helper
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


def test_zero_step_probes_never_wait_for_attachment() -> None:
    """issue #30 / `DESIGN.md` D107：**零步基线的每个探针都必须「缺席即判不成立」，不得等挂载**。

    现场（百炼/v2前端）：`atlas_check --page app-agent-detail` ⇒ 两条真用例全绿，唯零步基线
    `Test timeout of 30000ms exceeded`。页面停在应用壳（带参页面的页级路由、无实例 id ⇒ 详情不渲染），
    而 `attr` 探针发射的是 `getByTestId(t).first().getAttribute(n)` —— **没有 `count()` 守卫**，
    Playwright 对**未挂载**元素的 `getAttribute` 会等到默认超时 ⇒ 4 探针 × 2 趟撑爆 test 预算。
    契约 §5.5 明写「基线在带参页面上探不到元素时按 `null = 不成立` 处理」，**等挂载 = 违反契约**。

    本钉对**全部**探针表达式做通用检查：每个 `expr` 必须带缺席守卫（`count()) > 0` 或 `tsVis(` /
    `tsVisible(` / `atlasValueOf(`）——防未来新增动词再犯同一个错。

    变异 **MB7**：摘掉 `attr` 探针的 `count() > 0` ⇒ 本钉红。
    """
    import json as _json, re as _re
    case = CASE.replace(
        "expected:\n  - text home-title 首页        # 页面标题文案为「首页」",
        "expected:\n"
        "  - disabled home-cta-btn       # 置灰\n"
        "  - enabled home-title          # 可用\n"
        "  - attr home-cta-btn aria-label 合规说明   # 属性\n"
        "  - text home-title 首页        # 页面标题文案为「首页」")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case)
        assert run(root, "--apply").returncode == 0
        spec = spec_of(root)
    m = _re.search(r"const ATLAS_ZS_home = (\{.*?\});\n", spec, _re.S)
    assert m, "未找到零步基线数据"
    probes = _json.loads(m.group(1))["probes"]
    assert probes, "夹具应产出探针"
    exprs = [p["expr"] for p in probes]
    assert any("getAttribute(" in e for e in exprs), "夹具应包含 attr 探针"
    bad = [e for e in exprs
           if not any(g in e for g in ("count()) > 0", "tsVis(", "tsVisible(", "atlasValueOf("))]
    assert not bad, f"这些探针会在元素缺席时等挂载（违反 §5.5）：{bad}"


def test_assert_probe_tristate_absent_and_present() -> None:
    """三态契约：元素缺失时 hidden/unchecked ⇒ null（基线跳过），
    visible/enabled/disabled/checked ⇒ false（不判恒真）。

    现场（2026-10-22，百炼/v3 工作流零步基线）：hidden/unchecked 探针在元素
    不存在时被 count 守卫反转成 true，基线把「面板未打开」误判为恒真。
    本钉按 **动词 × 场景** 真求值生成表达式，锁住三态；只查表达式里有没有
    count/tsVis 守卫（上一钉）无法发现这种反转。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用，跳过探针表达式求值")

    gn = _load_gen()
    verbs = ("visible", "hidden", "enabled", "disabled", "checked", "unchecked")
    exprs = {verb: gn.ts_assert_expr(f"{verb} home-item") for verb in verbs}
    scenarios = {
        "absent": {"present": False, "visible": False, "enabled": False, "checked": False},
        "present_off": {"present": True, "visible": False, "enabled": False, "checked": False},
        "present_on": {"present": True, "visible": True, "enabled": True, "checked": True},
    }
    expected = {
        "absent": {"visible": False, "hidden": None, "enabled": False,
                   "disabled": False, "checked": False, "unchecked": None},
        "present_off": {"visible": False, "hidden": True, "enabled": False,
                        "disabled": True, "checked": False, "unchecked": True},
        "present_on": {"visible": True, "hidden": False, "enabled": True,
                       "disabled": False, "checked": True, "unchecked": False},
    }
    script = """
const exprs = __EXPRS__;
const scenarios = __SCENARIOS__;
function makePage(s) {
  const loc = {
    count: async () => (s.present ? 1 : 0),
    first() { return this; },
    nth() { return this; },
    isVisible: async () => s.visible,
    isEnabled: async () => s.enabled,
    isDisabled: async () => !s.enabled,
    isChecked: async () => s.checked,
  };
  return { getByTestId: () => loc };
}
let page;
async function tsVisible(p, tid) {
  const loc = p.getByTestId(tid);
  if ((await loc.count()) === 0) return false;
  return await loc.first().isVisible();
}
(async () => {
  const out = {};
  for (const [name, state] of Object.entries(scenarios)) {
    page = makePage(state);
    out[name] = {};
    for (const [verb, expr] of Object.entries(exprs)) {
      out[name][verb] = await eval(expr);
    }
  }
  process.stdout.write(JSON.stringify(out));
})().catch((err) => { console.error(err); process.exit(1); });
"""
    script = script.replace("__EXPRS__", json.dumps(exprs, ensure_ascii=False))
    script = script.replace("__SCENARIOS__", json.dumps(scenarios))
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    assert got == expected, f"探针三态不符合契约：{json.dumps(got, ensure_ascii=False)}"


def test_runner_config_declares_expect_timeout_floor() -> None:
    """issue #28 / `DESIGN.md` D105：生成的运行器配置必须声明 **`expect.timeout` 下限**。

    现场（2026-10-17，百炼/v2前端真跑）：URL 链全对、元素真在（探针实测 `disabled=true` + 合规
    aria-label），却 `3 failed 1 passed` —— 因为守卫断言 `toHaveCount(1)` 继承 Playwright **默认 5s**
    的 expect 超时，而该应用首屏要 **14,184ms**（dev bundle 13.8MB）⇒ **假红**（把「还没渲染」
    判成「元素不存在」）。

    缺省 20s，`ATLAS_EXPECT_TIMEOUT` 可覆盖（运维口，与 `ATLAS_SLOWMO` 同族）。

    变异 **MB5**：从配置发射面摘掉 `expect: {` ⇒ 本钉红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        cfg = (root / "product" / "e2e" / "scripts" / "playwright.config.ts").read_text(encoding="utf-8")
        assert "expect: { timeout:" in cfg, cfg[:400]
        assert "20_000" in cfg and "ATLAS_EXPECT_TIMEOUT" in cfg, cfg[:400]


def test_wait_timeout_cap_is_20s_and_overridable() -> None:
    """`DESIGN.md` D118：生成物的等待超时上限 = **缺省 20s + `ATLAS_WAIT_TIMEOUT_MS` 覆盖口**。

    现场（2026-10-19，百炼/v2前端真跑）：整份首跑 `9 passed / 1 failed`，红的那条倒在**页面就绪锚点**
    的 10s 超时（`元素齐全守卫：声明的 testid 无一在场`）；同口径探针实测该元素 **2.2~2.5s** 出现，
    且 `disabled=true` + 合规 `aria-label` 全对 ⇒ 10s 比该应用**已知最坏首屏**（D105 实测
    **14,184ms**）还短 ⇒ 间歇性假红。同一个「等界面」不得有两个上限：本常量与 D105 的
    `expect` 下限取同值。

    变异 **MD118**：退回写死的 `const ATLAS_WAIT_TIMEOUT_MS = 10_000;` ⇒ 本钉红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        spec = spec_of(root)
        assert "process.env.ATLAS_WAIT_TIMEOUT_MS" in spec, spec[:600]
        assert "?? 20_000" in spec, spec[:600]
        assert "const ATLAS_WAIT_TIMEOUT_MS = 10_000;" not in spec, spec[:600]
        # 上限仍然是「上限」：锚点走轮询原语，不得因本改而变成固定等待。
        assert "await expect.poll(hit, {" in spec, spec[:1200]


def test_base_query_reaches_all_three_navigation_sites() -> None:
    """issue #27 / `DESIGN.md` D104：`e2e.app_base_url` 的 query（宿主注入型前提，如 tenant）
    必须被带到**三处**导航发射面：

    ① step 的 `goto`；② 元素齐全守卫（`守卫:` 缺省 = 页面表路由）；③ 零步基线的 `data.url`
    （运行期 `atlasZeroStepBaseline` 内 `page.goto(data.url)`）。

    评审 MUST（`proposals/REVIEW-2026-10-17-Bprime.md`）：作者原写「一处发射」是**低报**；
    漏任一处 ⇒ 该跳 tenant 缺席 ⇒ 应用停在「请选择业务空间」⇒ **白屏假红**（不是用例真失败）。

    变异 **M-B2**：`_support/url_merge.merge_base_query` 退回 identity ⇒ 本钉三处齐红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=PROFILE.replace("app_base_url: http://127.0.0.1:8000",
                                           "app_base_url: http://127.0.0.1:8000/?switchAgent=7202"),
             case=CASE.replace("  - click home-cta-btn          # 点击主操作按钮",
                               "  - goto /home/#/42             # 含 hash 的路径形态\n"
                               "  - click home-cta-btn          # 点击主操作按钮"))
        assert run(root, "--apply").returncode == 0
        spec = spec_of(root)
        assert "await page.goto('/home/?switchAgent=7202#/42');" in spec, "① step goto 未带 base query（含 hash 保真）"
        assert "await page.goto('/home?switchAgent=7202');" in spec, "② 守卫导航未带 base query"
        assert '"url":"/home?switchAgent=7202"' in spec, "③ 零步基线 data.url 未带 base query"


def test_base_query_absent_leaves_generation_byte_identical() -> None:
    """**零变化承诺**（`shared/gates.md`「生成物最新」门看守派生件）：base 不带 query 的项目，
    三处发射面必须**逐字节**保持旧形态 —— 新能力只在「base 带 query」一个分支生效。

    变异 **M-B3**：去掉 `merge_base_query` 的「base 无 query 短路」⇒ 本钉红（生成物多出 `?`）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=CASE.replace("  - click home-cta-btn          # 点击主操作按钮",
                                     "  - goto /home/#/42             # 含 hash 的路径形态\n"
                                     "  - click home-cta-btn          # 点击主操作按钮"))
        assert run(root, "--apply").returncode == 0
        spec = spec_of(root)
        assert "await page.goto('/home/#/42');" in spec
        assert "await page.goto('/home');" in spec
        assert '"url":"/home"' in spec
        assert "?switchAgent" not in spec
        assert "page.goto('/home/?" not in spec
    # 单元侧：无 query ⇒ 原样返回（不因「纯路径」被改动）
    spec = importlib.util.spec_from_file_location("gen_e2e_urlmerge", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    merge = mod.url_merge.merge_base_query
    assert merge("/a/b#/c", "http://h/x") == "/a/b#/c"
    assert merge("/a/b#/c", "http://h/x?t=1") == "/a/b?t=1#/c"
    # 非 `/` 开头（外部 URL / 相对 hash）：一律不动
    assert merge("https://e.com/p", "http://h/?t=1") == "https://e.com/p"
    assert merge("#/x", "http://h/?t=1") == "#/x"
    # 已带 `?`（= 用例内联的 `参数:`）：与 base **求并集** —— base 在前、同键 ⇒ 目标胜
    # （本分支 2026-10-17 落笔时记为「§5.7 下不可达，为未来扩展留位」；2026-10-18 随 `参数:` 转正）
    assert merge("/a?k=0#/c", "http://h/?t=1") == "/a?t=1&k=0#/c"
    assert merge("/a?t=9#/c", "http://h/?t=1") == "/a?t=9#/c"      # 同键：目标胜（逐用例比全局更具体）


def test_select_option_locating_is_label_based_and_rejects_ambiguity() -> None:
    """契约 §5.5（2026-10-19，`DESIGN.md` D112）：`select` 的选项定位**不得**取「可访问名全等」。

    现场：ant Select 的选项把描述文案塞进选项内 ⇒ 可访问名 = 标签 + 描述
    （实测 `文本对话基于LLM的对话型交互，适合进行复杂的多轮对话`）⇒ `{ name: label, exact: true }`
    恒不命中，用例卡在 30s 超时（不是断言失败，是定位失败）。
    定案 = 三级降级（title 全等 → 可见文本前缀 → 名称包含）+ **命中不唯一即拒绝**
    （宁可响亮失败，也不 `.first()` 静默选错项）。
    """
    case_text = CASE.replace(
        "  - click home-cta-btn          # 点击主操作按钮",
        "  - select home-cta-btn 首页    # 选项定位口径",
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case_text)
        assert run(root, "--apply").returncode == 0
        ts = spec_of(root)
        start = ts.index("async function atlasSelect(")
        body = ts[start:ts.index("\nasync function ", start + 1)]
        # ① 禁用形态：可访问名全等（= 本行治的那个病灶）
        assert "exact: true" not in body, body
        # ② 三级降级三枚标记齐（title 全等 / 前缀 / 包含）
        assert "e.getAttribute('title') === want" in body, body
        assert "startsWith(want)" in body, body
        assert "includes(want)" in body, body
        # ③ 唯一性判据 + 响亮失败（列出可见选项，让下一次失败可诊断）
        #    必须锚定**整条判据语句**：`hit.length` 这个子串在降级两行里也出现，
        #    只查子串 ⇒ 摘掉判据行钉子照样绿（MB14 实测：第一版判据就是废的）。
        #    （D117 起形态由 `ok:false` 改为三值 `status`；「歧义即拒 + 列出可见选项」意图不变）
        assert "if (hit.length === 1) return { status: 'unique', idx: all.indexOf(hit[0]), visible: shown.map(nameOf) }" in body, body
        assert "status: hit.length > 1 ? 'ambiguous' : 'none'" in body, body
        assert "可见选项=" in body, body
        # ④ 候选只取**几何可见**元素（避免 hidden 选项参与匹配）
        assert "getBoundingClientRect()" in body, body
        # ⑤ 原生分支仍在（实现无关：<select> 走 selectOption）
        assert "selectOption({ label })" in body, body
        # ⑥ 候选集含组件库可见选项类名（D122：Antd Select 的可见项无 role=option，仅 title）
        assert body.count('[class*="select-item-option"]') == 2, body
        # ⑦ 排除选项内部 -content / -state 子节点（否则无 title 时同一选项命中两次 ⇒ 假歧义）
        assert body.count(':not([class*="select-item-option-content"])') == 2, body
        assert body.count(':not([class*="select-item-option-state"])') == 2, body


def test_select_polls_until_options_are_positioned_and_refuses_ambiguity() -> None:
    """契约 §5.5（2026-10-19，`DESIGN.md` D117）：`select` 的就绪门**不得**依赖全局候选集的 attached。

    现场（v2 真跑，整份 ×3 遍中 2 次红）：页面上常驻 9~10 个 `[role=menuitem]` 顶部导航 ⇒ 旧就绪门
    （`[role=option],[role=menuitem]` 的 `attached`）被环境项秒满足 ⇒ 采样落在 rc-select 尚未定位
    （`getBoundingClientRect` 零盒）的窗口内 ⇒ 候选只剩导航项，报「可见选项=[应用市场,…]」。
    失败快照反证：触发器已 `[expanded]`、listbox 内两个选项都在 —— 采样比「可见」早了一步。
    定案 = **按命中态轮询采样**：0 命中（未就绪）⇒ 轮询到上限；>1 命中（歧义）⇒ 立即拒绝（D112 语义不变）；
    轮询原语 = `expect.poll`（与页面就绪锚点同一机制，**不引入固定等待** —— 首版用 `waitForTimeout` 做轮询间隔，
    被本文件既有门「生成物不得含固定等待」当场吹红，改回轮询原语）。
    """
    case_text = CASE.replace(
        "  - click home-cta-btn          # 点击主操作按钮",
        "  - select home-cta-btn 首页    # 选项定位口径",
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=case_text)
        assert run(root, "--apply").returncode == 0
        ts = spec_of(root)
        start = ts.index("async function atlasSelect(")
        body = ts[start:ts.index("\nasync function ", start + 1)]
        # ① 旧就绪门（全局候选集的 attached 等待）必须消失
        assert "waitFor({ state: 'attached'" not in body, body
        # ② 轮询原语 = expect.poll（**不得**用固定等待作轮询间隔）
        assert "await expect.poll(async () => { pick = await atlasPick(); return pick.status; }," in body, body
        assert ".not.toBe('none')" in body, body
        assert "waitForTimeout" not in body, body
        # ③ 命中态三值齐
        assert "status: 'unique'" in body, body
        assert "status: hit.length > 1 ? 'ambiguous' : 'none'" in body, body
        # ④ 歧义**立即**拒绝：轮询只为「未就绪」而设（只对 `none` 继续等）
        assert "return pick.status; }," in body, body
        # ⑤ 响亮失败文案不变（仍列出可见选项）
        assert "可见选项=" in body, body
        # ⑥ 原生分支仍在（实现无关）
        assert "selectOption({ label })" in body, body


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
        "await page.getByTestId('home-cta-btn').first().click({ force: true })"
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
    assert ts2.index("await page.getByTestId('home-tab-btn').first().click({ force: true })") < ts2.index(
        "const __delta_home_title = await atlasIntOf"
    ) < ts2.index("await page.getByTestId('home-save-btn').first().click({ force: true })"), ts2
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

        # 2b. D129：pre_existing Critical 经判定 status=WARN，不阻断生成器
        (bad_basis_dir / "review.json").write_text(
            json.dumps({
                "ok": True,
                "status": "WARN",
                "checks": [{"level": "Critical", "check": "存量隐患", "pre_existing": True}],
            }),
            encoding="utf-8",
        )
        level, detail = gen.review_report_status(rdir)
        assert level == "ok", (level, detail)

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


def test_guard_watches_case_testid_list_not_first_step() -> None:
    """**尺子重定向**（2026-10-16，issue #R2）：守卫面 = 该用例 `testid:` **应然清单**（契约
    §7.1「每条用例的 `testid:` 清单守卫」），**不**从 `step[0]` 猜。

    本用例重定向自 `test_guard_only_watches_first_step_target` —— 原判据把「空表」钉成期望
    （`step[0]` 无 testid ⇒ 守卫安全为空），而空表 = 空循环 = **守卫消失**，与契约正文相抵。
    **不删断言**：场景 1 的「动态元素不得出现在守卫面」**反转为**「守卫面 = 全部应然清单
    （含动态项）」；场景 2 的「空表」改为断言其 `testid:` 清单内容。
    「防死锁」意图的合法落点 = 契约 §4 的 **hidden 占位槽**机制（实现侧满足：动作产物元素
    以占位槽满足「用例开始时 count=1」）—— 故动态元素**就在**守卫面里，是否合规由实现侧承接。
    """
    gn = _load_gen()
    # 场景 1：动态元素已按契约 §4 打占位槽 ⇒ 守卫面 = 全部应然清单
    case1 = {
        "id": "E2E-DYNAMIC-001",
        "_title": "动态创建元素",
        "step": ["click static-create-btn", "click dynamic-item-delete-btn"],
        "expected": ["visible dynamic-item"],
        "testid": ["static-create-btn", "dynamic-item", "dynamic-item-delete-btn"],
    }
    spec1 = gn.ts_case(case1, "/dynamic")
    # D114：锚点带**全量**应然清单（含动态项）；三项均被 step/expected 触达 ⇒ 无 presence 循环
    assert ('await atlasAwaitAnyDeclared(page, ["static-create-btn", "dynamic-item", '
            '"dynamic-item-delete-btn"], ATLAS_WAIT_TIMEOUT_MS);' in spec1), spec1
    assert "for (const id of" not in spec1, spec1

    # 场景 2：step[0] 是无 testid 的 goto/refresh ⇒ 守卫面仍 = 该用例 `testid:` 清单（非空）
    case2 = {
        "id": "E2E-DYNAMIC-002",
        "_title": "刷新后检查",
        "step": ["refresh", "click static-btn"],
        "expected": ["visible static-btn"],
        "testid": ["static-btn"],
    }
    spec2 = gn.ts_case(case2, "/dynamic")
    assert 'await atlasAwaitAnyDeclared(page, ["static-btn"], ATLAS_WAIT_TIMEOUT_MS);' in spec2, spec2
    assert '["static-btn"]' in spec2.split("atlasAwaitAnyDeclared")[1].split(")")[0], spec2


def test_goto_first_step_keeps_guard_non_empty() -> None:
    """新增钉子（2026-10-16，issue #R2）：**首步为 `goto` 的用例 ⇒ 守卫面非空**。

    改前**零覆盖**（卢森堡批 6 条用例首步全是 `goto`，6/6 生成 `for (const id of [])`）。
    撤掉修复（守卫面改回 `first_step_tids`）⇒ 本钉子红；还原 ⇒ 绿。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-GOTO-FIRST-001",
        "_title": "带参页守卫导航",
        "step": ["goto /detail/1", "click detail-save-btn"],
        "expected": ["visible detail-save-btn"],
        "testid": ["detail-save-btn"],
    }
    spec = gn.ts_case(case, "/detail")
    # D114：锚点带该用例 `testid:` 清单且不得为空表（step[0] 是 goto 也不退化）
    assert 'await atlasAwaitAnyDeclared(page, ["detail-save-btn"], ATLAS_WAIT_TIMEOUT_MS);' in spec, spec
    assert '[]' != spec.split("atlasAwaitAnyDeclared")[1].split(")")[0].strip(), spec


def test_guard_id_face_strips_inline_comment() -> None:
    """守卫 id 面逐项剥行内注释（2026-10-16，R1 同类的**守卫面侧**）。

    `testid:` 项与 `step:` 项同形，同样可带行内 `#` 说明；不剥则守卫面发射带注释的 id
    ⇒ `toHaveCount(1)` 恒不命中 ⇒ 假红。与零步基线侧 `case_testids` 同口径（同一函数对象）。
    撤掉修复（守卫面回到原样发射）⇒ 本钉子红；还原 ⇒ 绿。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-TID-COMMENT-001",
        "_title": "应然清单项带行内说明",
        "step": ["click item-save-btn"],
        "expected": ["visible item-save-btn"],
        "testid": ["item-save-btn   # 行内说明"],
    }
    spec = gn.ts_case(case, "/item")
    # D114：注释剥离落在**锚点面**（原守卫面，现已拆两段的前一段）
    assert 'await atlasAwaitAnyDeclared(page, ["item-save-btn"], ATLAS_WAIT_TIMEOUT_MS);' in spec, spec
    assert "# 行内说明" not in spec.split("atlasAwaitAnyDeclared")[1].split(")")[0], spec


def test_guard_is_anchor_only_and_never_backfills_presence() -> None:
    """D114（issue #26，**同日修正**）：守卫 = **单段页面就绪锚点**，不对任何 id 在 goto 时刻做 presence 要求。

    为何删掉「纯在场声明」段（现场证据）：静态双向集合门要求「源码里的每个实然 testid 必须被某条用例的
    `testid:` 声明」，于是「声明但不操作 / 不断言」是**唯一合法形态**（正是补全该静态门的手段）；
    若又在 goto 时刻要求它运行时在场，就是把「静态门的补全需求」误当成了「初始态断言」——
    面板 / 弹层未打开时该元素必然为 0，合法用例死锁（Expected 1 / Received 0）。
    回退（恢复任一段 presence 循环：全量或子集）⇒ 本钉子红。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-SPLIT-001",
        "_title": "声明完整性 + 被触达混合",
        "step": ["click a-btn"],
        "expected": ["after:1 count b-item 2"],
        # shell-anchor 仅声明（从不被操作 / 断言）= 静态双向集合门的补全形态
        "testid": ["a-btn", "b-item", "shell-anchor"],
    }
    spec = gn.ts_case(case, "/p")
    # 锚点：带**全量**声明清单（守卫面不为空、也不被裁剪）
    assert ('await atlasAwaitAnyDeclared(page, ["a-btn", "b-item", "shell-anchor"], '
            'ATLAS_WAIT_TIMEOUT_MS);' in spec), spec
    # 任何 presence 循环都不得出现（全量、子集、空表皆不例外）
    assert "getByTestId(id)).toHaveCount(1)" not in spec, spec
    assert "for (const id of [" not in spec, spec


def test_config_declares_serial_execution() -> None:
    """契约 §7.1（`DESIGN` D115，2026-10-19）：生成的运行器配置**必须**声明串行执行。

    理由：靶场是共享有状态环境，同域用例互相污染前序状态；零步基线必须先于改态用例
    （并行调度会打乱定义序 ⇒ 恒真误报 / 前提被前序污染）。
    本钉同时钉**注释出处**：该纪律的正文在 §7.1；曾经漂到 §8（§8 实为校验清单
    8.1 validate_testids / 8.2 validate_e2e_index / 8.3 validate_e2e_mocks）⇒ 读注释的人找不到依据。
    变异 MD115：摘掉 config 的 `workers: 1` 发射 ⇒ 本钉红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root, "--apply").returncode == 0
        cfg = (root / "product" / "e2e" / "scripts" / "playwright.config.ts").read_text(encoding="utf-8")
        assert "workers: 1" in cfg, cfg[:900]
        assert "fullyParallel: false" in cfg, cfg[:900]
        assert "§7.1" in cfg, cfg[:900]
        assert "rings/e2e §8" not in cfg, cfg[:900]


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
            "type item-input 你好",
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
    assert "await page.getByTestId('item-btn').first().click({ force: true });" in spec
    assert "await page.getByTestId('item-card').first().hover({ force: true });" in spec
    assert "await page.getByTestId('item-input').first().fill(\"hello\");" in spec
    assert "await page.getByTestId('item-input').first().pressSequentially(\"你好\");" in spec
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


def test_setup_real_login_supports_dot_path_token_and_json_body_format() -> None:
    """issue #35：真实登录支持点号深路径取 token、json body_format 声明，并优先保留合法 stateFile。"""
    prof = PROFILE.split("  app_login:")[0] + (
        "  app_login:\n"
        "    mode: real\n"
        "    endpoint: /api/v1/auth/login\n"
        "    username_field: email\n"
        "    password_field: pass\n"
        "    token_key: data.token.access_token\n"
        "    storage_key: auth_jwt\n"
        "    body_format: json\n"
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, profile=prof)
        assert run(root, "--apply").returncode == 0
        setup = (root / "product" / "e2e" / "scripts" / "atlas-auth.setup.ts").read_text(encoding="utf-8")
        assert "application/json" in setup
        assert "JSON.stringify" in setup
        assert "tokenKey.split('.').reduce" in setup
        assert "保留已有登录态文件（如 codegen 产物），跳过覆写" in setup


# ── issue #R4（2026-10-16）：`click` / `hover` 的 `force` 默认 + `native` 步级开关 ──────
def test_click_hover_force_default_and_native_switch() -> None:
    """契约 §5.5（2026-10-16，issue #R4）：`click` / `hover` **缺省**发 `{ force: true }`
    （I4：默认路径逐字节不变）；第三位 `native` ⇒ 按运行器原生语义执行（**不**追加 force）。

    撤掉修复（`step_force_arg` 恒返 force）⇒ 本钉子的 `native` 部分红。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-FORCE-001",
        "_title": "可操作性被测属性",
        "step": ["click act-save-btn", "hover act-menu-btn native"],
        "expected": ["visible act-save-btn"],
        "testid": ["act-save-btn", "act-menu-btn"],
    }
    spec = gn.ts_case(case, "/act")
    # 缺省：force 保留（逐字节同改前）
    assert "await page.getByTestId('act-save-btn').first().click({ force: true });" in spec, spec
    # native：不追加 force，但保留 `.first()`（strict-mode 修复不得回退）
    assert "await page.getByTestId('act-menu-btn').first().hover();" in spec, spec
    assert "hover({ force: true })" not in spec, spec


def test_click_switch_value_domain_closed() -> None:
    """值域封闭（契约 §5.5）：第三位非 `native` 且非空 ⇒ 生成器**报错中止**（不静默降级）。"""
    gn = _load_gen()
    case = {
        "id": "E2E-FORCE-002",
        "_title": "坏开关",
        "step": ["click act-btn force"],
        "expected": ["visible act-btn"],
        "testid": ["act-btn"],
    }
    try:
        gn.ts_case(case, "/act")
    except ValueError as exc:
        assert "native" in str(exc), exc
    else:
        raise AssertionError("坏开关取值未报错（静默降级 = 值域未封闭）")

    # 端到端：坏值经真跑生成进程 ⇒ 非零退出
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bad = CASE.replace("  - click home-cta-btn          # 点击主操作按钮",
                           "  - click home-cta-btn force    # 坏开关")
        make(root, case=bad)
        r = run(root, "--apply")
        assert r.returncode != 0, (r.returncode, r.stdout, r.stderr)


def test_subscript_nth_index_emits_nth_locator() -> None:
    """契约 §5.5（D120 / issue #31）：同名多实例支持 [N] 序号索引，发射 .nth(N)。"""
    gn = _load_gen()
    case = {
        "id": "E2E-INDEX-001",
        "_title": "同名多实例索引",
        "step": [
            "click list-move-up-btn[1]",
            "fill list-name-input[2] 文本",
            "hover list-action-btn[0] native",
            "select list-category-select[1] 科技",
            "check list-checkbox[3]",
            "dispatch list-submit-btn[1]",
        ],
        "expected": [
            "visible list-item[1]",
            "text list-title[2] 标题二",
            "value list-name-input[2] 文本",
            "enabled list-move-up-btn[1]",
        ],
        "testid": ["list-move-up-btn", "list-name-input", "list-action-btn", "list-category-select", "list-checkbox", "list-submit-btn", "list-item", "list-title"],
    }
    spec = gn.ts_case(case, "/list")
    assert "page.getByTestId('list-move-up-btn').nth(1).click(" in spec, spec
    assert "page.getByTestId('list-name-input').nth(2).fill(\"文本\")" in spec, spec
    assert "page.getByTestId('list-action-btn').nth(0).hover()" in spec, spec
    assert "atlasSelect(page, 'list-category-select', \"科技\", 1)" in spec, spec
    assert "page.getByTestId('list-checkbox').nth(3).check()" in spec, spec
    assert "page.getByTestId('list-submit-btn').nth(1).dispatchEvent('click')" in spec, spec
    assert "page.getByTestId('list-item').nth(1)).toBeVisible()" in spec, spec
    assert "page.getByTestId('list-title').nth(2)).toHaveText(\"标题二\")" in spec, spec
    assert "atlasExpectValue(page, 'list-name-input', \"文本\", 2)" in spec, spec
    assert "page.getByTestId('list-move-up-btn').nth(1)).toBeEnabled()" in spec, spec


# ── 2026-10-18 v3 现场实证移植批（D111）：`refresh` 落盘节拍参数化 ─────────────────────
def test_refresh_emits_settle_wait_before_reload() -> None:
    """契约 §7.1 / §5.5 `refresh` 行（D111，v3 现场实证移植）：`refresh` 发射**先等后刷**——
    `ATLAS_REFRESH_SETTLE`（默认 0）注入的 `waitForTimeout` 先于 `reload`；节流型自动保存
    的项目运行时设置毫秒值 ⇒ 刷新前有落库等待窗。毫秒常数属项目侧**运行时**前提，生成器
    不写死（对齐 F11 `ATLAS_SLOWMO` 注入先例；默认 0 ⇒ 生成物行为与既有契约一致）。

    变异证明 **M95**：摘掉 waitForTimeout 发射行 ⇒ 本钉红（还原逐字节一致）。
    """
    gn = _load_gen()
    case = {
        "id": "E2E-REFRESH-001",
        "_title": "刷新后复断言",
        "step": ["refresh"],
        "expected": ["visible home-h1"],
        "testid": ["home-h1"],
    }
    spec = gn.ts_case(case, "/")
    settle = 'await page.waitForTimeout(Number(process.env.ATLAS_REFRESH_SETTLE || "0"));'
    assert settle in spec, spec
    assert spec.index(settle) < spec.index("await page.reload();"), spec


# ── issue #R1/S1（2026-10-16）：`testid:` 项带行内注释 ⇒ F24 规则二豁免仍生效 ────────
COMMENTED_TID_CASE = """# home 页面用例

## E2E-HOME-001 首页主操作可见

```atlas-case
id: E2E-HOME-001
intent: 打开首页后主操作按钮可见
pages:
  - home
precondition:
  - 已打开首页
step:
  - click home-title            # 操作另一元素（不碰 home-cta-btn）
expected:
  - visible home-cta-btn        # 纯在场守卫（已在守卫面覆盖）
testid:
  - home-cta-btn   # 行内说明（本项注释不得影响豁免判据）
  - home-title
```
"""


def test_testid_item_inline_comment_keeps_guard_only_visible_exemption() -> None:
    """F5（2026-10-16，issue #R1 同族未爆现场）：`testid:` **项**带行内注释时，
    「纯在场守卫豁免」（F24 规则二）仍生效 —— 该断言不产生零步探针。

    撤掉修复（`case_testids = set(c.get("testid") or [])`）⇒ 集合里是
    `home-cta-btn   # 行内说明` ⇒ `target_id in case_testids` 不命中 ⇒ 用例被误判为
    「非纯在场守卫」⇒ 探针非空 ⇒ 本钉子红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root, case=COMMENTED_TID_CASE)
        assert run(root, "--apply").returncode == 0
        text = spec_of(root)
        assert "const ATLAS_ZS_home" not in text, text[:1200]
        assert "test('test_home__zero_step_baseline'" not in text, text[:1200]


# ── RFC-20261018-01（2026-10-18）：E2E 真跑失败自动留证 ────────────────────────
# 契约条 = rings/e2e §7.1「失败留证（硬，失败才落盘）」；门行 = shared/gates.md 2.2。
# 证据源：gen_e2e_scripts.py:1549/1580（发版雷达首跑实锤「两轨模板无 trace 键」）；
# 悬空判据接线 = duty-review/bugs.md:17（hover 升判条件在等 trace / 连续截图）。

NONE_PROFILE = PROFILE.split("  app_login:")[0] + "  app_login:\n    mode: none\n"


def _cfg(root: Path) -> str:
    return (root / "product" / "e2e" / "scripts" / "playwright.config.ts").read_text(encoding="utf-8")


def test_failure_evidence_both_tracks_declare_trace() -> None:
    """RFC-20261018-01 钉 1（双轨同构）：`mode: none` 与预置登录**两轨**的
    `playwright.config.ts` 都必须声明 `trace` + `screenshot`——缺任一轨即红。

    双份同构漂移普查家族：模板是实质双份（1549/1580 两分支），一侧加了键另一侧漏了
    才是这类病灶的真形态（同 D82 ③ 文法单源普查的普查思路）。
    变异 MB10：摘掉任一轨 trace 键 ⇒ 本钉红。
    """
    with tempfile.TemporaryDirectory() as td_none, tempfile.TemporaryDirectory() as td_login:
        rn, rl = Path(td_none), Path(td_login)
        make(rn, profile=NONE_PROFILE)
        make(rl)                                   # 缺省 PROFILE 含 app_login 全字段 ⇒ 预置登录轨
        assert run(rn, "--apply").returncode == 0
        assert run(rl, "--apply").returncode == 0
        for tag, root in (("none", rn), ("login", rl)):
            cfg = _cfg(root)
            assert "trace: 'retain-on-failure'" in cfg, f"[{tag}] {cfg[:400]}"
            assert "screenshot: 'only-on-failure'" in cfg, f"[{tag}] {cfg[:400]}"


def test_failure_evidence_values_are_closed() -> None:
    """RFC-20261018-01 钉 2（值形态封闭）：两键值必须**恰为**
    `retain-on-failure` / `only-on-failure`——`on`（全量常录）之类意识形态越界 ⇒ 红。

    理由（RFC §2.2）：全量常录 = 磁盘成本 × 每用例且成功轮留证无消费方；
    `video` 缓行（trace 已是逐帧回放器），多一键 = 同构面 +2 无收益。
    变异 MB11：`retain-on-failure` 改 `on` ⇒ 本钉红；`video: on` 混入同理。
    """
    with tempfile.TemporaryDirectory() as td_none, tempfile.TemporaryDirectory() as td_login:
        rn, rl = Path(td_none), Path(td_login)
        make(rn, profile=NONE_PROFILE)
        make(rl)
        assert run(rn, "--apply").returncode == 0
        assert run(rl, "--apply").returncode == 0
        for tag, root in (("none", rn), ("login", rl)):
            cfg = _cfg(root)
            assert "trace: 'retain-on-failure'" in cfg, f"[{tag}] {cfg[:400]}"
            assert "video" not in cfg, f"[{tag}] video 缓行中不得出现 {cfg[:400]}"
            assert "trace: 'on'" not in cfg and "screenshot: 'on'" not in cfg, f"[{tag}] {cfg[:400]}"


def test_failure_evidence_has_no_override_switch() -> None:
    """RFC-20261018-01 钉 3（无覆盖口）：留证键随模板无条件发射，**不得**给环境开关
    （如 `ATLAS_E2E_EVIDENCE`）——加开关等于给「成功轮也留证」开后门（成功轮留证
    无消费方；留证对象 = 首跑失败现场，见 `duty-review/bugs.md` 节拍类判据）。
    """
    with tempfile.TemporaryDirectory() as td_none, tempfile.TemporaryDirectory() as td_login:
        rn, rl = Path(td_none), Path(td_login)
        make(rn, profile=NONE_PROFILE)
        make(rl)
        assert run(rn, "--apply").returncode == 0
        assert run(rl, "--apply").returncode == 0
        for tag, root in (("none", rn), ("login", rl)):
            cfg = _cfg(root)
            assert "EVIDENCE" not in cfg, f"[{tag}] {cfg[:400]}"




