#!/usr/bin/env python3
"""共享内核（`_support/`）的出厂测试 —— 单源守恒 + 结构唯一性 + 加载器行为。

依据（2026-10-12 单源批，ATLAS-UPSTREAM #198；`gates.md` 假绿测试义务）：
  * **黄金期望**：夹具 profile 文本经内核解析的结果 = 期望值 ⇒ 内核实现被改坏必红（M45）。
  * **结构唯一性守卫**：`def parse_profile` / `def parse_block` / `def strip_inline_comment` /
    `def yaml_scalar` 在整个包（scripts / validators / _support）**只准各出现在单源文件**——
    就地复制一份本地实现 ⇒ 红（M46，B197-1 漂移的结构根因守卫）。
  * **别名绑定**：消费者暴露的 `parse_profile` / `parse_block` 别名必须**就是**内核函数对象。
  * **加载器行为**：找不到 ⇒ 响亮 `FileNotFoundError`（不静默 None，M47）；同进程缓存同名同物。
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


sys.path.insert(0, str(PKG_ROOT))
from _support.siblings import load_module  # noqa: E402

sp = load_module("stack_profile")
cb = load_module("case_block")

# 冲突覆盖夹具：e2e 子块（§B101/B197-1/§5.8）+ backend_test + 行内注释 + 空值 + 引号 + 流式段
FIXTURE_PROFILE = """\
product: 测试产品   # 行内注释须剥
origin: greenfield
apps:
  - name: backend
    path: backend
    kind: backend
    role: landing
    stack: python
adapters:
  routes: null
  models: models
graph:
  backend: cgc
  pinned: "0.6.13"
e2e:
  runner: node-playwright
  app_base_url: http://127.0.0.1:8000
  seed:
    mode: declare
    hook: scripts/seed.py
  app_login:
    endpoint: /api/v1/login/access-token
    storage_key: access_token
  mock:
    mode: on
    api_prefix: /api/v1
backend_test:
  command: uv run pytest backend/tests
  mode: advisory
impl_review:
  cli: ocr
  llm: null
"""

# 黄金期望（内核语义 = 原 gen 实现与 vsp 对齐版的最大公约）。
EXPECT = {
    "product": "测试产品",
    "origin": "greenfield",
    "apps": [{"name": "backend", "path": "backend", "kind": "backend",
              "role": "landing", "stack": "python"}],
    "adapters_routes": None,
    "adapters_models": "models",
    "graph_backend": "cgc",
    "graph_pinned": "0.6.13",
    "e2e_runner": "node-playwright",
    "e2e_url": "http://127.0.0.1:8000",
    "seed_mode": "declare",
    "seed_hook": "scripts/seed.py",
    "login_endpoint": "/api/v1/login/access-token",
    "login_storage": "access_token",
    "mock_mode": "on",
    "mock_prefix": "/api/v1",
    "bt_command": "uv run pytest backend/tests",
    "bt_mode": "advisory",
}


def test_profile_golden_expectations() -> None:
    """黄金期望：夹具文本解析结果 = 期望值（内核被改坏 ⇒ 红；变异 M45 即删 e2e 子块分支）。"""
    d = sp.parse_profile(FIXTURE_PROFILE)
    e2e = d["e2e"]
    assert d["product"] == EXPECT["product"], d["product"]
    assert d["origin"] == EXPECT["origin"]
    assert d["apps"] == EXPECT["apps"], d["apps"]
    assert d["adapters"].get("routes") is None
    assert d["adapters"].get("models") == EXPECT["adapters_models"]
    assert d["graph"]["backend"] == EXPECT["graph_backend"]
    assert d["graph"]["pinned"] == EXPECT["graph_pinned"]
    assert e2e["runner"] == EXPECT["e2e_runner"]
    assert e2e["app_base_url"] == EXPECT["e2e_url"]
    assert e2e["seed"]["mode"] == EXPECT["seed_mode"]
    assert e2e["seed"]["hook"] == EXPECT["seed_hook"]
    assert e2e["app_login"]["endpoint"] == EXPECT["login_endpoint"]
    assert e2e["app_login"]["storage_key"] == EXPECT["login_storage"]
    assert e2e["mock"]["mode"] == EXPECT["mock_mode"]
    assert e2e["mock"]["api_prefix"] == EXPECT["mock_prefix"]
    assert d["backend_test"]["command"] == EXPECT["bt_command"]
    assert d["backend_test"]["mode"] == EXPECT["bt_mode"]


def test_profile_scalar_forms() -> None:
    """标量口径：null 家族 → None、引号剥离、顶层标量结束当前段（不吞进上一段）。

    null 家族只认 `null` / `~` / 空（2026-10-16 收窄，RFC-20261015-02）：裸 `none` 是
    **合法字符串**（`e2e.app_login.mode: none` = 靶场无访问门的显式声明，必须原样读出）——
    旧口径把它也归入 null ⇒ mode 被吞成 None，缺省判据读成 `real`（变异 M72：把收窄去掉
    ⇒ 本用例的第二组断言红）。
    """
    d = sp.parse_profile("prototype: null\norigin: adopt\ne2e:\n  runner: node-playwright\n")
    assert d["prototype"] is None
    assert d["origin"] == "adopt"          # 顶层标量结束段 —— 不吞进 prototype
    assert d["e2e"]["runner"] == "node-playwright"
    assert sp.yaml_scalar("'x'") == "x"
    assert sp.yaml_scalar("~") is None
    assert sp.strip_inline_comment("a: b   # 注释") == "a: b"
    # 裸 `none` 收窄后的口径：是字符串不是 null（None 同判——两种 Python 风写法都不是 null）
    assert sp.yaml_scalar("none") == "none"
    assert sp.yaml_scalar("None") == "None"
    assert sp.parse_profile("e2e:\n  app_login:\n    mode: none\n")["e2e"]["app_login"]["mode"] == "none"


def test_block_golden_and_shape() -> None:
    """用例块黄金期望：键空间 / `- ` 归集 / 带值追加 / 标量键（= 迁移前两处实现的语义）。"""
    body = """id: E2E-LOGIN-001
intent: 登录落列表
pages:
- login
precondition:
- 已登录
step:
- goto /login
- click btn-1
expected:
- visible title-1
- text title-1 欢迎
testid:
- login-page
"""
    d = cb.parse_block(body)
    assert d["pages"] == ["login"]
    assert d["precondition"] == ["已登录"]
    assert d["step"] == ["goto /login", "click btn-1"]
    assert d["expected"] == ["visible title-1", "text title-1 欢迎"]
    assert d["testid"] == ["login-page"]
    assert d["id"] == "E2E-LOGIN-001"      # 键空间外的标量键
    assert d["intent"] == "登录落列表"
    assert set(d) >= {"pages", "precondition", "seed", "mock", "step", "expected", "testid"}
    # 带值追加形态（`pages: login`）后当前键仍为 pages ⇒ 后续 `- ` 行继续归入（边缘语义，如实钉住）
    d2 = cb.parse_block("pages: login\n- extra\n")
    assert d2["pages"] == ["login", "extra"]


def test_block_scalar_strips_inline_comment_list_item_keeps_note() -> None:
    """I1（2026-10-16，issue #R1）：**标量键**的行内 `#` 注释被剥（机器面取值），
    **列表项逐字节不变**（其 `#` 是给人读的 note，由消费侧 `parse_line` 单点消费）。

    坏输入必红（变异 M83）：把标量分支还原为 `d[k] = v` ⇒ 第一条断言红
    （`/x/1   # 说明` 被整段当值，再作为 JS 字面量发射）。
    """
    d = cb.parse_block("守卫: /x/1   # 说明\nstep:\n- goto /x   # note\nintent: 一  # 二\n")
    assert d["守卫"] == "/x/1"                  # 标量：剥注释
    assert d["intent"] == "一"                  # 标量：剥注释（同口径）
    assert d["step"] == ["goto /x   # note"]    # 列表项：逐字节不变


def test_strip_inline_comment_is_one_function_object() -> None:
    """I3（2026-10-16，issue #R1/#R3/#F5）：「剥注释」口径全局只有**一个函数对象**
    （不是等价实现）—— 四消费者（内核 / 块体解析器 / 生成器 / 索引校验器）同一对象。

    这是「无共享通道 ⇒ 就地复制」的结构守卫：引用别名合法，**第二次实现**（哪怕输出
    相同）非法；`test_definitions_are_single_sourced` 从 `def <name>(` 面扣，本钉从
    对象同一性面扣（两面互补）。
    """
    gen = _load("gen_e2e_scripts", "scripts/gen_e2e_scripts.py")
    idx = _load("validate_e2e_index", "validators/validate_e2e_index.py")
    assert cb.strip_inline_comment is sp.strip_inline_comment
    assert gen.strip_inline_comment is sp.strip_inline_comment
    assert idx.strip_inline_comment is sp.strip_inline_comment


def test_no_second_comment_stripping_implementation_in_line_parsers() -> None:
    """D94 ③ 残余清偿（2026-10-17，变异 MB8）：**同一文件内不得再有第二份剥注释口径**。

    对象同一性钉（上一条）只能证明「别名指向同一对象」，证明不了「没人另写一份」
    —— `_code()` 曾是活样本：它有 `strip_inline_comment` 的别名在手，却仍写着
    `line.split("#", 1)[0].strip()`（任何 `#` 都截断），把 `/console/#/…` 这类路径砍断。
    本钉从**形态**面扣：行解析器（校验器 / 生成器）的**代码行**里不得出现 `split("#"`。

    变异 **MB8**：把 `_code()` 退回 `split("#", 1)[0]` ⇒ 本钉红。
    """
    offenders = []
    for rel in ("validators/validate_e2e_index.py", "scripts/gen_e2e_scripts.py"):
        for i, line in enumerate((PKG_ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or 'split("#", 1)[0]' in s and s.startswith("#"):
                continue          # 注释行不算实现
            if 'split("#"' in line:
                offenders.append(f"{rel}:{i}")
    assert not offenders, f"发现第二份剥注释口径（应用 `_code()` / `strip_inline_comment`）：{offenders}"


def test_definitions_are_single_sourced() -> None:
    """结构唯一性守卫（M46）：四个共享函数在全包只准各有一处定义（单源文件）。

    「无共享通道 ⇒ 就地复制」是 B197-1 漂移的结构根因；本守卫把根因钉死：
    任何文件（scripts/ validators/ _support/）里按 `def <name>(` 出现第二处 ⇒ 红。
    """
    allowed = {
        "parse_profile": "_support/stack_profile.py",
        "strip_inline_comment": "_support/stack_profile.py",
        "yaml_scalar": "_support/stack_profile.py",
        "parse_block": "_support/case_block.py",
    }
    found: dict[str, list[str]] = {k: [] for k in allowed}
    for sub in ("scripts", "validators", "_support"):
        for f in sorted((PKG_ROOT / sub).rglob("*.py")):
            if "__pycache__" in str(f):
                continue
            rel = f.relative_to(PKG_ROOT).as_posix()
            text = f.read_text(encoding="utf-8")
            for fn in allowed:
                if re.search(rf"^def {fn}\(", text, re.M):
                    found[fn].append(rel)
    bad = {fn: files for fn, files in found.items() if files != [allowed[fn]]}
    assert not bad, f"共享函数出现第二处定义（单源纪律被破坏）：{bad}"


def test_consumer_aliases_are_the_kernel_objects() -> None:
    """消费者暴露的别名必须就是内核函数对象（防「引用另一份实现」的再引入）。"""
    gen = _load("gen_e2e_scripts", "scripts/gen_e2e_scripts.py")
    vsp = _load("validate_stack_profile", "validators/validate_stack_profile.py")
    idx = _load("validate_e2e_index", "validators/validate_e2e_index.py")
    assert gen.parse_profile is sp.parse_profile
    assert gen.parse_block is cb.parse_block
    assert gen.strip_inline_comment is sp.strip_inline_comment
    assert vsp.parse_profile is sp.parse_profile
    assert vsp.strip_inline_comment is sp.strip_inline_comment
    assert vsp.yaml_scalar is sp.yaml_scalar
    assert idx.parse_block is cb.parse_block
    assert idx.strip_inline_comment is sp.strip_inline_comment


def test_loader_fails_loud_when_missing() -> None:
    """加载器：找不到 ⇒ 响亮 FileNotFoundError（不静默 None —— M47 变异点）。"""
    try:
        load_module("no_such_module_xyz_2026")
    except FileNotFoundError as exc:
        assert "no_such_module_xyz_2026" in str(exc)
    else:
        raise AssertionError("缺失模块未响亮报错（静默继续 = 门失效）")


def test_loader_caches_same_object() -> None:
    """加载器缓存：同名二次加载返回同一模块对象（防同进程双加载分叉）。"""
    a = load_module("stack_profile")
    b = load_module("stack_profile")
    assert a is b is sp
