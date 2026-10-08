#!/usr/bin/env python3
"""atlas E2E —— 从用例分片生成可执行脚本（操作 + 断言）。

按 `rings/e2e/reference.md` §7（决策 D50/D67/D68；2026-09-23 由「testid 冒烟骨架」
改为「操作脚本」）：
  * 读 `product/e2e/cases/<page>.md` 的 `atlas-case` 块，**一页一脚本**；
  * 生成**可运行的操件脚本**：每条用例一个测试——`goto(<页面 URL>)` → 按 `step`
    **逐行执行动作**（click / fill / select / check / uncheck / press / hover /
    refresh / goto）→ 按 `expected` **逐行执行断言**（text / contains / count /
    visible / hidden / enabled / disabled / value）；`#` 之后的中文说明作为注释保留；
  * **动词解析失败即中止**：`step` / `expected` 出现词表外的动词 → 报错并列出违规行，
    不得静默跳过或降级为注释；
  * `testid:` 数组作为**元素齐全守卫**：每用例运行前按**自动等待**断言其列出的 testid 全部
    存在（运行器原生轮询断言）——真实应用是 SPA，`goto` 后元素异步渲染，即时存在性判定
    必红；真缺失时超时失败并点名缺失清单（不得退化成永久等待）；
  * **复杂逻辑放 `_support/`**（断言之外的计算、等待、多步组合；**不被覆盖**），
    生成脚本在存在时挂载调用 `hooks.deep_assert(<ID>, page)`；
  * 地址**不硬编码**：由运行器原生配置承载 `baseURL`，值 = `e2e.app_base_url`（E1 单段：
    唯一靶场 = 真实应用；为空 ⇒ 报错索取，不猜默认）；
  * 运行器由 `e2e.runner` 决定（`python-playwright` / `node-playwright`），脚本扩展名随运行器；
  * **派生、可重生成**：重跑覆盖同页脚本与运行器配置；`_support/` 永不覆盖。
  * **预置登录态**：以**真实登录**预置会话——端点 / 表单字段名 / 令牌键 / 存储键 = 取证值，
    登记在 `e2e.app_login` 段
    （段缺失 = 合法降级：跳过预置 + 明确警告；字段不齐 ⇒ 生成报错）；凭据只来自运行期
    环境变量 `ATLAS_APP_USER` / `ATLAS_APP_PASSWORD`（不读项目 `.env`、不硬编码）；
    未设置 ⇒ 跳过预置 + 明确警告；换取令牌失败 ⇒ 报错中止
    （不得静默续跑——那会退化成「未登录态跑用例」的假绿）。

纯标准库；无任何框架名（运行器名只作为 `e2e.runner` 的值出现）。

用法：
    python3 gen_e2e_scripts.py --root <项目根> [--apply] [--json]

退出码（`3509 §B110`）：**0** 正常 · **2** 真错（缺 profile / 动词越界 / 审查门不过…） ·
**3** 前置未声明（`e2e.app_base_url` 为空）—— **3 不是失败**：调用方应判「未就绪」而不是「生成失败」，
且 `--json` 下 stdout 给出 `{"ok": false, "not_ready": "app_base_url", …}`。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CASE_BLOCK = re.compile(r"```atlas-case\s*\n(.*?)```", re.S)
RUNNERS = {"python-playwright": ".py", "node-playwright": ".spec.ts"}
# 前置未声明（例：`e2e.app_base_url` 为空）的**独立退出码**（`3509 §B110`）：
# 与真错（2）分开 ⇒ 调用方（`atlas_check`）判 **SKIP（未就绪）** 而不是 FAIL。
# 同一根因曾被判成两种结论（`E2E 真跑`=SKIP、`生成物最新`=FAIL）⇒ 永久红门 = 静音门（`§106`）。
NOT_READY = 3
# e2e.app_login 段的必填字段（段缺失 = 合法降级；段存在则须齐全，3509 §B101）
APP_LOGIN_FIELDS = ("endpoint", "username_field", "password_field", "token_key", "storage_key")

# 分片 step / expected 的动词词表（契约 `rings/e2e/reference.md` §5.5，2026-09-23 定）
ACTION_VERBS = ("click", "fill", "select", "check", "uncheck", "press", "hover", "refresh", "goto", "waitFor", "download")
ASSERT_VERBS = ("text", "contains", "count", "countOptions", "visible", "hidden", "enabled", "disabled", "checked", "unchecked", "value", "attr", "delta")
NO_TESTID_VERBS = ("refresh", "goto")  # 这两个动词第二个 token 不是 testid（goto 的值是路径）
# 契约 §5.6 R9：`expected` 行可加**行首前缀**，显式声明该断言的判据形状。
#   `initial:`   —— 「本就该在初始态成立」⇒ 完全豁免零步基线（单向）。
#   `unchanged:` —— 「本用例的被测属性是『该动作不改变它』」⇒ 生成物在**行动前**断言其成立、
#                   在**行动后**复断言；零步基线期望**反向**（初始成立 = 正常，初始不成立 = 自相矛盾）。
# 未加前缀的断言一律不得在初始态成立 —— 否则即「恒真断言」（用例什么都没验）。
PREFIXES = ("initial:", "unchanged:")
# 契约 §5.5：`after:<N>` = **步骤锚**（断言钉在第 N 条 step 之后的时点），见 `split_after`。
AFTER_RE = re.compile(r"^after:(\d+)\s+(\S.*)$")
# 契约 §5.6 R9：`unchanged:` 表达的是「**该动作**不改变它」，而「该动作」= 提交性动作
# ⇒ 「行动前」的采样点必须**贴着第一个提交性动作**，不能放在所有 step 之前。
# 词表与 `validate_e2e_index.py` 的 `UNCHANGED_ACTION_WORDS` 同源（契约 §5.6 R2 的提交性控件词表）。
# 矫正对话框（2026-10-01）引入 adopt / revert / discard 三个提交性控件动作——unchanged 用例的放置锚与 R9 同类动作判定据此扩展
SUBMITTING_WORDS = ("save", "submit", "confirm", "delete", "remove", "bind", "cancel", "logout", "adopt", "revert", "discard")
UNCHANGED = "unchanged"


def split_after(line: str) -> tuple[int | None, str]:
    """拆出「步骤锚」前缀 `after:<N>`（N 从 1 起 = 分片里第 N 条 `step` 执行完之后）。

    契约 §5.5（2026-09-25 补，`3509 §B57`）：把断言**钉在某个 step 之后的时点**，
    用于「先准备、再提交」型用例的**中途态取证**（取消后关闭 = 终态等于初态且无派生入口）。
    它只能与普通断言动词连用 —— 与 `initial:` / `unchanged:` **不得叠写**（叠写时本函数先剥
    锚、剩下的 `initial:` 会撞断言动词词表 ⇒ 生成器报错；文本期门另有专项 FAIL）。
    """
    m = AFTER_RE.match(line.lstrip())
    if not m:
        return None, line
    return int(m.group(1)), m.group(2)


def split_prefix(line: str) -> tuple[str | None, str]:
    """拆出行首前缀，返回 (前缀名 或 None, 去掉前缀的行)。

    `initial:` / `unchanged:` **共用本函数**（单点解析）⇒ 两条通道的语义不会漂。
    步骤锚 `after:<N>` 在此一并剥掉（它是「时点」而不是「豁免通道」，由 `split_after` 单读）。
    """
    _anchor, line = split_after(line)
    s = line.lstrip()
    for p in PREFIXES:
        if s.startswith(p):
            return p[:-1], s[len(p):].lstrip()
    return None, line


def parse_line(line: str) -> tuple[str, str, str, str]:
    """把 `<动词> <testid> [<值>]  # 中文说明` 拆成 (verb, testid, value, note)。

    机器只看 `#` 之前；`#` 之后是给人读的中文说明。
    """
    code, _, note = line.partition("#")
    parts = code.strip().split(None, 2)
    verb = parts[0] if parts else ""
    if verb in NO_TESTID_VERBS:
        return verb, "", (parts[1] if len(parts) > 1 else ""), note.strip()
    return verb, (parts[1] if len(parts) > 1 else ""), (parts[2] if len(parts) > 2 else ""), note.strip()


def py_action(line: str) -> str:
    verb, tid, value, note = parse_line(line)
    tail = f"  # {note}" if note else ""
    v = json.dumps(value, ensure_ascii=False)
    if verb == "refresh":
        return f"page.reload(){tail}"
    if verb == "goto":
        return f"page.goto({v}){tail}"
    if verb == "waitFor":
        # 契约 §7.1：`waitFor` 必须渲染为**带轮询的断言**，不得退化为固定等待。
        if value == "":
            return f'_wait_for_visible(page, "{tid}"){tail}'
        return f'_wait_for_text(page, "{tid}", {v}){tail}'
    if verb == "download":
        # 契约 §5.5（2026-09-25 新增，3509 §B26）：触发下载并校验建议下载文件名（glob）。
        # 必须是「先注册监听 → 再点击 → 再断言」：下载是动作的副作用，事后无法补取证。
        # 固定形状由 header 的 `_download` 助手容纳，此处只传参。
        if not value.strip():
            raise ValueError(f"`download` 需要文件名 glob 参数: {line!r}（契约 §5.5）")
        return f'_download(page, "{tid}", {v}){tail}'
    if verb == "click":
        return f'_loc(page, "{tid}").click(){tail}'
    if verb == "fill":
        return f'_loc(page, "{tid}").fill({v}){tail}'
    if verb == "select":
        return f'_select(page, "{tid}", {v}){tail}'
    if verb == "check":
        return f'_loc(page, "{tid}").check(){tail}'
    if verb == "uncheck":
        return f'_loc(page, "{tid}").uncheck(){tail}'
    if verb == "press":
        return f'_loc(page, "{tid}").press({v}){tail}'
    if verb == "hover":
        return f'_loc(page, "{tid}").hover(){tail}'
    raise ValueError(f"未知动作动词: {verb}（契约 §5.5）")


def py_assert_expr(line: str) -> tuple[str, str | None]:
    """把一行断言渲染成 (表达式, 失败消息)。

    正式用例（`py_assert`）与零步基线（`py_zero_step_baseline`）**共用**本函数 ——
    两条路径的断言语义因此不可能漂（复用而非复制）。
    """
    _, line = split_prefix(line)
    verb, tid, value, _note = parse_line(line)
    v = json.dumps(value, ensure_ascii=False)
    if verb == "text":
        return (
            f'_vis(page, "{tid}").inner_text().strip() == {v}',
            f'_loc(page, "{tid}").inner_text()',
        )
    if verb == "contains":
        return f'{v} in _vis(page, "{tid}").inner_text()', None
    if verb == "count":
        return f'page.get_by_test_id("{tid}").count() == int({v})', None
    if verb == "countOptions":
        # 契约 §5.5（2026-09-25 新增）：数该元素内的 `option` 子元素个数。
        # 用于「枚举选项个数」类断言 —— 原来的 `count` 只能数到 `select` 自身（永远 1）吧。
        return f'_loc(page, "{tid}").locator("option").count() == int({v})', None
    if verb == "visible":
        return f'_visible(page, "{tid}")', None
    if verb == "hidden":
        return f'not _visible(page, "{tid}")', None
    # is*() 对缺失元素会等挂载 ⇒ 先 count 守卫（与 TS 侧同构）
    if verb == "enabled":
        return f'page.get_by_test_id("{tid}").count() > 0 and _loc(page, "{tid}").is_enabled()', None
    if verb == "disabled":
        return f'page.get_by_test_id("{tid}").count() > 0 and _loc(page, "{tid}").is_disabled()', None
    if verb == "checked":
        return f'page.get_by_test_id("{tid}").count() > 0 and _loc(page, "{tid}").is_checked()', None
    if verb == "unchecked":
        return f'not (page.get_by_test_id("{tid}").count() > 0 and _loc(page, "{tid}").is_checked())', None
    if verb == "value":
        # 契约 §5.5（2026-09-25 补空值分支）：值写作 `""` / `(空)` 时表示**空串**。
        # 不补这一支则 `json.dumps('""')` 会得到字面量 `"\"\""` —— 与真实空串永远不相等，
        # 于是「清除选区后为空」这类断言只能靠「少断言」回避（3509 §B39）。
        # （B173-1：经 _value_of 实现无关化 —— 原生表单元素读值，combobox 读触发器文本。）
        if value.strip() in ('""', "(空)"):
            return f'_value_of(page, "{tid}") == ""', None
        return f'_value_of(page, "{tid}") == {v}', None
    if verb == "attr":
        # 契约 §5.5（2026-09-25 新增，3509 §B35）：元素属性 `<name>` 的值等于 `<value>`。
        # 值段 = `<name> <value>`：`name` 取**首个空白前**的 token，其余全部为 `value`（可含空格）。
        # **不要求可见**（用 `_loc` 而非 `_vis`）—— 与 `enabled` / `checked` 同理：
        # 属性可读性与渲染可见性正交（隐藏节点的属性照样有值）。
        # 属性不存在时 `get_attribute()` 返回 `None` ⇒ 与任何字符串都不等 ⇒ 断言失败。
        name, _, val = value.strip().partition(" ")
        val = val.strip()
        if not name or not val:
            raise ValueError(f"`attr` 需要 `<name> <value>` 两个参数: {line!r}（契约 §5.5）")
        n = json.dumps(name, ensure_ascii=False)
        return (
            f'_loc(page, "{tid}").get_attribute({n}) == {json.dumps(val, ensure_ascii=False)}',
            f'_loc(page, "{tid}").get_attribute({n})',
        )
    if verb == "delta":
        # 契约 §5.5（P5，2026-10-07）：相对断言的**行动后**复读比较。行动前采样（`__delta_<tid>`）
        # 由 `py_case` 在第一个提交性动作之前发射（零步基线不收 delta —— 无初始态语义）。
        if not re.fullmatch(r"[+-]\d+", value.strip()):
            raise ValueError(f"`delta` 值须为带符号整数 ±N: {line!r}（契约 §5.5）")
        var = "__delta_" + re.sub(r"[^0-9a-zA-Z]+", "_", tid)
        n = int(value.strip())
        return (
            f'_int_of(_loc(page, "{tid}").inner_text()) == {var} + {n}',
            f'"期望较行动前 {n:+d}，行动前基准 = " + str({var})',
        )
    raise ValueError(f"未知断言动词: {verb}（契约 §5.5）")


def py_assert(line: str) -> str:
    kind, line = split_prefix(line)
    _verb, _tid, _value, note = parse_line(line)
    tail = f"  # {note}" if note else ""
    expr, msg = py_assert_expr(line)
    if kind == UNCHANGED:
        # 本用例的被测属性是「该动作不改变它」⇒ 这一处是**动作后**的复断言。
        # 消息是字面量，必须渲染成合法的 python 字符串字面量（直接裸写会撞引号 / 全角括号）。
        head = json.dumps(
            "「unchanged:」断言在**动作后**不成立（本用例的被测属性是「该动作不改变它」）",
            ensure_ascii=False,
        )
        msg = f'{head} + "；实际 = " + str({msg})' if msg else head
    return f"assert {expr}, {msg}{tail}" if msg else f"assert {expr}{tail}"


def py_unchanged_pre(line: str) -> str:
    """`unchanged:` 的**行动前**断言（契约 §5.6 R9）。

    采样于**第一个提交性动作之前**（不是「所有 `step` 之前」）：契约说该前缀表达的是
    「**该动作**不改变它」，而「该动作」就是那个提交性动作。

    为何不能放在所有 `step` 之前：用例自带的**准备步骤**（切页签 / 打开抽屉）还没执行时，
    目标元素可能根本不可见 ⇒ 一条**合法**用例被判「自相矛盾」（实测踩到：
    `E2E-ASSETS-003` / `E2E-CONFIG-003`，`3509 §B55`）。
    """
    _, body = split_prefix(line)
    expr, _msg = py_assert_expr(body)
    return (
        f'assert {expr}, "`unchanged:` 断言在**行动前**就不成立 —— 该用例声称「动作不改变它」，'
        f'而它一开始就不成立（用例自相矛盾）"'
    )


def _strip_inline_comment(s: str) -> str:
    """剥行内 `#` 注释（引号外）。

    与 `validate_stack_profile.py` 的口径一致：真实 profile 写作
    `runner: python-playwright   # python-playwright | node-playwright`，
    不剥就会把整段注释当成值。
    """
    out: list[str] = []
    q = None
    for ch in s:
        if q:
            if ch == q:
                q = None
            out.append(ch)
            continue
        if ch in ("'", '"'):
            q = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def parse_profile(text: str) -> dict:
    data: dict = {"prototype": {}, "e2e": {}}
    section = None
    sub = None  # 一级子块（目前只有 e2e.app_login，3509 §B101）：更深缩进的键归子块
    for raw in text.splitlines():
        line = _strip_inline_comment(raw.rstrip())
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not line[:1].isspace() and line.endswith(":"):
            section = line[:-1].strip()
            sub = None
            continue
        if section not in ("prototype", "e2e"):
            continue
        m = re.match(r"^(\s+)([\w.-]+):\s*(.*?)\s*$", line)
        if not m:
            continue
        indent, key = len(m.group(1)), m.group(2)
        v = m.group(3).strip().strip("'\"")
        v = None if v.lower() in ("", "null", "~") else v
        if section == "e2e" and key == "app_login" and indent == 2 and v is None:
            sub = "app_login"
            data[section].setdefault("app_login", {})
            continue
        # `e2e.seed.hook`（契约 §5.7，2026-09-28）：数据播种通道（项目自定实现，路径相对项目根）
        if section == "e2e" and key == "seed" and indent == 2 and v is None:
            sub = "seed"
            data[section].setdefault("seed", {})
            continue
        if sub is not None and indent > 2:
            data[section][sub][key] = v
            continue
        sub = None
        data[section][key] = v
    return data


def parse_block(body: str) -> dict:
    d: dict = {"pages": [], "precondition": [], "seed": [], "step": [], "expected": [], "testid": []}
    key = None
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("- ") and key:
            d[key].append(s[2:].strip())
            continue
        if ":" in s:
            k, v = s.split(":", 1)
            k, v = k.strip(), v.strip()
            if k in d:
                key = k
                if v:
                    d[k].append(v)
            else:
                d[k] = v
                key = None
    return d


def gather_cases(cases: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for md in sorted(cases.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        titles: dict[str, str] = {}
        for line in text.splitlines():
            m = re.match(r"^##\s+(E2E-\S+)\s+(.*)$", line)
            if m:
                titles[m.group(1)] = m.group(2).strip()
        items = []
        for block in CASE_BLOCK.findall(text):
            d = parse_block(block)
            if d.get("id"):
                d["_title"] = titles.get(d["id"], "")
                d["_shard"] = f"product/e2e/cases/{md.name}"
                items.append(d)
        out[md.stem] = items
    return out


def index_case_states(index_text: str) -> dict[str, tuple[str, str]]:
    """索引主表的状态真相源（契约 §5.1：状态/状态原因只在索引）：`{用例ID: (状态, 状态原因)}`。"""
    states: dict[str, tuple[str, str]] = {}
    for ln in index_text.splitlines():
        if not ln.startswith("| E2E-"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 8:
            states[cells[0]] = (cells[6], cells[7].strip())
    return states


def page_urls(index_text: str) -> dict[str, str]:
    """页面 URL = 索引**页面表**（契约 §3.2）的 `路由` 列——唯一来源，不从文件系统派生（E1）。"""
    urls: dict[str, str] = {}
    for ln in index_text.splitlines():
        m = re.match(r"^\|\s*([a-z0-9][a-z0-9-]*)\s*\|\s*(/\S*)\s*\|", ln)
        if m and m.group(1) != "页面":
            urls[m.group(1)] = m.group(2)
    return urls


def py_header(runner: str) -> str:
    return (
        f'# AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py (runner={runner})\n'
        "# 重跑覆盖本文件；复杂逻辑请放 _support/（不被覆盖）。\n"
        "from __future__ import annotations\n\n"
        "import json\n"
        "import fnmatch\n"
        "import re\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "from playwright.sync_api import expect\n\n"
        "try:  # 可选：_support/hooks.py 提供 deep_assert(case_id, page)\n"
        "    from _support import hooks  # type: ignore\n"
        "except Exception:  # pragma: no cover\n"
        "    hooks = None\n\n"
        "_HERE = Path(__file__).resolve().parent\n\n"
        "def _loc(page, tid):\n"
        "    return page.get_by_test_id(tid).first\n\n"
        "def _assert_testids(page, ids):\n"
        "    # 元素齐全守卫（契约 §7.1）：**自动等待**判定 —— 真实应用是 SPA，goto 后元素\n"
        "    # 异步渲染，即时 count() 必红；真缺失时超时失败并点名缺失清单（无永久等待后门）。\n"
        "    missing = []\n"
        "    for t in ids:\n"
        "        try:\n"
        "            expect(page.get_by_test_id(t)).to_have_count(1, timeout=_WAIT_TIMEOUT_MS)\n"
        "        except AssertionError:\n"
        "            missing.append(t)\n"
        "    assert not missing, f\"缺少 data-testid: {missing}\"\n\n"
        "def _select(page, tid, value):\n"
        "    # 契约 §5.5（B173-1）：实现无关 select —— 语义 = 「选中 label 的那一项」。\n"
        "    # 原生 <select> 走 select_option；否则视作 trigger+listbox 组合。\n"
        "    loc = _loc(page, tid)\n"
        "    if loc.evaluate(\"e => e.tagName.toLowerCase()\") != \"select\":\n"
        "        loc.click()\n"
        "        page.get_by_role(\"option\", name=value, exact=True).first.click()\n"
        "        return\n"
        "    try:\n"
        "        loc.select_option(value=value)\n"
        "    except Exception:\n"
        "        loc.select_option(label=value)\n\n"
        "def _value_of(page, tid):\n"
        "    # 契约 §5.5（B173-1）：读「控件当前值」的实现无关入口（与 TS atlasValueOf 同构）：\n"
        "    # 原生表单元素读 input 值；否则视作 trigger+listbox，当前值 = 触发器可见文本。\n"
        "    loc = _vis(page, tid)\n"
        "    if loc.evaluate(\"e => e.tagName.toLowerCase()\") in (\"select\", \"input\", \"textarea\"):\n"
        "        return loc.input_value()\n"
        "    return loc.inner_text().strip()\n\n"
        "def _visible(page, tid):\n"
        "    loc = page.get_by_test_id(tid)\n"
        "    return loc.count() > 0 and loc.first.is_visible()\n\n"
        "def _vis(page, tid):\n"
        '    """契约 §7.1：读元素值的断言（text / contains / value）须先断言**可见**。\n\n'
        "    隐藏元素同样有文本与取值（面板未展开时 inner_text() 照样返回），\n"
        "    只比值会把「面板未展开」误判为通过。\n"
        '    """\n'
        "    loc = _loc(page, tid)\n"
        '    assert loc.is_visible(), f"{tid} 不可见，其文案/取值不构成断言依据"\n'
        "    return loc\n\n"
        "_WAIT_TIMEOUT_MS = 10_000\n\n"
        "def _download(page, tid, pattern):\n"
        '    """契约 §5.5：`download` 动作 —— 先注册下载监听、再点击，最后校验建议文件名（glob）。\n\n'
        "    `fnmatch` 语义（`*` 任意串 / `?` 单字符）；断言的是**文件名**而非内容（§5.5）。\n"
        '    """\n'
        "    with page.expect_download(timeout=_WAIT_TIMEOUT_MS) as _dl:\n"
        "        _loc(page, tid).click()\n"
        "    _name = _dl.value.suggested_filename\n"
        '    assert fnmatch.fnmatch(_name, pattern), f"下载文件名 {_name} 不匹配 {pattern}"\n\n'
        "def _wait_for_visible(page, tid, timeout_ms=_WAIT_TIMEOUT_MS):\n"
        '    """契约 §7.1：`waitFor` 渲染为**带轮询的断言**，不得退化为固定等待。"""\n'
        "    expect(page.get_by_test_id(tid).first).to_be_visible(timeout=timeout_ms)\n\n"
        "def _wait_for_text(page, tid, value, timeout_ms=_WAIT_TIMEOUT_MS):\n"
        '    """等到该 testid 的**渲染后可见文案**等于 value（`use_inner_text` 与 `text` 断言同源）。"""\n'
        "    expect(page.get_by_test_id(tid).first).to_have_text(value, use_inner_text=True, timeout=timeout_ms)\n\n"
        "def _int_of(text):\n"
        '    """契约 §5.5（P5）：`delta` 相对断言的取数 —— 元素文本中的**首个整数**。\n\n'
        "    找不到数值即响亮失败（永不静默当 0 处理）。\n"
        '    """\n'
        "    m = re.search(r\"-?\\d+\", text)\n"
        "    assert m, f\"delta 采样：元素文本不含数值: {text!r}\"\n"
        "    return int(m.group(0))\n\n"
        "def _atlas_expand_panels(page):\n"
        "    # 契约 §5.6 R9：`hidden` 类与 `unchanged:` 断言在**展开全部面板**后的状态下取样\n"
        "    # （`data-atlas-panel` 标的是 Tab 级面板）。不展开 ⇒ 面板整体的 hidden 会把断言测到\n"
        "    # 的东西从「元素本身」偷换成「面板」（面板内 `hidden X` 恒真）。依据 3509 §B49。\n"
        "    page.eval_on_selector_all(\"[data-atlas-panel]\", \"els => els.forEach(e => { e.hidden = false; })\")\n\n"
        "def _atlas_probe(page, probes, sampling, initial_true, contradictory):\n"
        '    """按 `sampling` 筛出本趟要取的断言并逐条求值（两趟共用，不复制判定逻辑）。"""\n'
        '    for p in probes:\n'
        '        if p["sampling"] != sampling:\n'
        "            continue\n"
        "        try:\n"
        '            ok = bool(eval(p["expr"], globals(), {"page": page}))\n'
        "        except AssertionError:\n"
        "            continue\n"
        '        if p["kind"] == "unchanged":\n'
        "            if not ok:\n"
        '                contradictory.append(p["label"])\n'
        "        elif ok:\n"
        '            initial_true.append(p["label"])\n\n'
        "def _atlas_zero_step_baseline(page, data_path):\n"
        '    """契约 §5.6 R9 零步基线 —— **数据驱动**（断言清单落在 `_data/zero_step_*.json`）。\n\n'
        "    清单由生成器从各用例 `expected` 逐条渲染（渲染逻辑与用例断言**同源**，\n"
        "    不在运行期二次解释）；本函数只负责在**未执行任何 step** 的初始态逐条求值：\n"
        "      * `kind=plain` 初始成立 ⇒ 恒真断言（用例什么都没验）⇒ FAIL；\n"
        "      * `kind=unchanged` 初始**不**成立 ⇒ 用例自相矛盾 ⇒ FAIL；\n"
        "      * `initial:` 不入清单（显式豁免）。\n"
        "    **按动词分状态取样两趟**（契约 §5.6 R9，2026-09-25 补，3509 §B72）：\n"
        "      第一趟先**按真实渲染**取存在类断言（面板未展开）；随后展开 Tab 级面板，\n"
        "      第二趟取 `hidden` 类与 `unchanged:`。单一状态无法同时满足两类要求。\n"
        "    判据「以返回值判定」而非「没抛异常」——`_vis` 对隐藏元素的守卫会抛 AssertionError，\n"
        "    那是「不成立」而不是「成立」（2026-09-24 实测踩到：命中数被放大一倍）。\n"
        '    """\n'
        '    data = json.loads(Path(data_path).read_text(encoding="utf-8"))\n'
        '    page.goto(data["url"])\n'
        "    initial_true: list[str] = []\n"
        "    contradictory: list[str] = []\n"
        '    _atlas_probe(page, data["probes"], "rendered", initial_true, contradictory)\n'
        "    _atlas_expand_panels(page)\n"
        '    _atlas_probe(page, data["probes"], "expanded", initial_true, contradictory)\n'
        "    problems = []\n"
        "    if contradictory:\n"
        '        problems.append("`unchanged:` 断言在初始态就不成立（它声称动作不改变它，而它一开始就不成立）=> 用例自相矛盾：\\n  - " + "\\n  - ".join(contradictory))\n'
        "    if initial_true:\n"
        '        problems.append("初始态即成立的断言（恒真，用例什么都没验）：\\n  - " + "\\n  - ".join(initial_true))\n'
        '    assert not problems, "\\n".join(problems)\n\n'
    )


def parse_seed_line(line: str) -> tuple[str, dict]:
    """`upsert <实体> <字段>=<值> …` → `(实体, {字段: 值})`（契约 §5.7 的 `seed:` 行式语法）。"""
    toks = line.split()
    if len(toks) < 2 or toks[0] != "upsert":
        raise ValueError(f"seed 行语法应为 `upsert <实体> <字段>=<值> …`：{line!r}")
    entity, fields = toks[1], {}
    for kv in toks[2:]:
        if "=" not in kv:
            raise ValueError(f"seed 行的字段应为 `字段=值`：{kv!r}（行：{line!r}）")
        k, v = kv.split("=", 1)
        fields[k] = v
    return entity, fields


def py_case(case: dict, url: str) -> str:
    cid = case["id"]
    fn = re.sub(r"[^0-9a-zA-Z]+", "_", cid).lower()
    title = case.get("_title", "")
    lines = []
    # 契约 §5.7（2026-09-30 补）：`auth: none` → 挂 marker，conftest 的 page fixture
    # 据此给**干净 context**（剥预置 storageState）——「未登录前提」的机制化，不再依赖
    # 页内退出控件的存在。取值白名单外**中止**（不猜、不静默降级）。
    auth = case.get("auth", "preset")
    if auth not in ("preset", "none"):
        raise ValueError(f"{cid}: auth 取值应为 preset|none，得 {auth!r}")
    state = case.get("_state", "")
    state_reason = case.get("_state_reason", "")
    if state in ("blocked", "skipped"):
        # 契约 §7（2026-09-30 补）：状态真相源 = 索引。blocked/skipped 用例仍生成
        # （正文唯一源不变），但发 skip——真跑不会把「合法不可跑」跑成红。
        reason = state_reason or state
        lines.append(f"@pytest.mark.skip(reason={json.dumps('[' + state + '] ' + reason, ensure_ascii=False)})")
    if auth == "none":
        lines.append("@pytest.mark.atlas_auth_none")
    lines += [f"def test_{fn}(page):", f'    """{cid} {title}']
    if case.get("intent"):
        lines.append(f"    intent: {case['intent']}")
    # shared/single-source.md §2：用例正文的**唯一源**是分片文件（`cases/*.md`）。
    # 生成物里只留指针，不复制作例块 —— 复制会造出第二处正文，且让每次改用例都重写整文件。
    lines.append(f"    用例正文（唯一源）：{case.get('_shard', '')}#{cid.lower()}")
    lines.append('    """')
    lines.append(f'    page.goto("{url}")')
    ids = case.get("testid") or []
    lines.append(f"    _assert_testids(page, {json.dumps(ids, ensure_ascii=False)})")
    # 契约 §5.7：结构化 `seed:` 行 → 逐条调用播种钩子（幂等 upsert；每条用例独立播种）。
    # 未声明通道时 `_seed` 会**明确警告**（生成期另有一条 WARN），不静默。
    for s in case.get("seed") or []:
        entity, fields = parse_seed_line(s)
        lines.append(f"    _seed(page, {entity!r}, {fields!r})")
    # 契约 §5.6 R9：`unchanged:` 的**行动前**断言 —— 采样于**第一个提交性动作之前**
    # （不是「所有 step 之前」：那会把用例自带的准备步骤落在采样之后，目标还不可见 ⇒ 误判自相矛盾）。
    pre = ["    " + py_unchanged_pre(e) for e in case.get("expected", [])
           if split_prefix(e)[0] == UNCHANGED]
    # 契约 §5.5（P5，2026-10-07）：`delta` 相对断言的**行动前采样** —— 与 `unchanged:` 同点
    # （第一个提交性动作之前）：「递增」的基准 = 动作发生前一刻的值，准备步骤不污染基准。
    delta_pres: list[tuple[str, str, int]] = []
    for e in case.get("expected", []):
        if split_prefix(e)[0] is not None:
            continue
        verb, tid, value, _ = parse_line(e)
        if verb != "delta":
            continue
        if not re.fullmatch(r"[+-]\d+", value.strip()):
            raise ValueError(f"`delta` 值须为带符号整数 ±N: {e!r}（契约 §5.5）")
        var = "__delta_" + re.sub(r"[^0-9a-zA-Z]+", "_", tid)
        delta_pres.append((var, tid, int(value.strip())))
    steps = case.get("step", [])
    if delta_pres and not steps:
        raise ValueError(f"{cid}: delta 相对断言需要至少一条 step（行动前采样点不存在）")
    first_submit = next((i for i, s in enumerate(steps)
                         if any(w in s.split("#", 1)[0] for w in SUBMITTING_WORDS)), None)
    # 契约 §5.5：`after:<N>` 把断言插到第 N 条 step **之后**（中途态取证，`3509 §B57`）。
    anchors: dict[int, list[str]] = {}
    for e in case.get("expected", []):
        _n, _ = split_after(e)
        if _n is not None:
            anchors.setdefault(_n, []).append(e)
    if not steps:
        lines.extend(pre)
    else:
        # 无提交性动作时退回「第一个 step 之前」：文本期门已对此 FAIL，此处保持保守位置。
        for i, s in enumerate(steps, start=1):
            if (i - 1) == (first_submit if first_submit is not None else 0):
                lines.extend(pre)
                lines.extend(f'    {var} = _int_of(_loc(page, "{tid}").inner_text())'
                             for var, tid, _n in delta_pres)
            lines.append("    " + py_action(s))
            lines.extend("    " + py_assert(e) for e in anchors.get(i, []))
    for e in case.get("expected", []):
        if split_after(e)[0] is None:      # 锚已随其 step 发射，避免重复
            lines.append("    " + py_assert(e))
    lines.append(f'    if hooks:\n        hooks.deep_assert("{cid}", page)')
    return "\n".join(lines) + "\n"


def py_zero_step_baseline(page: str, url: str, cases: list[dict]) -> tuple[str, dict | None]:
    """契约 §5.6 R9 —— 本页零步基线的**产出**（薄函数文本 + 数据清单）。

    旧实现把每页每条断言内联成 lambda，占生成物体积 17–27% 且每次改用例整文件重写；
    现改为「清单落 `_data/zero_step_<page>.json` + 运行期固定 runner」（runner 在 `py_header`）。
    判据、`initial:` 豁免、`unchanged:` 期望反向、逐条指名用例与断言 —— **全部不变**。

    **不再按「断言表达式串」去重**（3509 §B33）：同形的 plain 断言被先出现的
    `unchanged:` 折叠 ⇒ 后者永不点名（假阴性）。同一断言在不同用例里本就应各自判定。
    """
    probes: list[dict] = []
    for c in cases:
        if c.get("_state") in ("blocked", "skipped"):
            # 契约 §7（2026-10-01 补）：状态真相源 = 索引——blocked/skipped 用例不进真跑红面
            # （生成语义②），其断言同样不进零步基线探针。否则部分实现页上「合法不可跑」用例的
            # `hidden` 探针会在未实现面板上判真，把基线打成假红（实测：projects 页 016）。
            continue
        for e in c.get("expected") or []:
            kind, body = split_prefix(e)
            if kind == "initial":
                continue  # 显式豁免：不参与零步基线
            if body.split("#", 1)[0].strip().split(" ", 1)[0] == "delta":
                continue  # 契约 §5.5（P5）：delta 是行动前后差值断言，没有「初始态成立/不成立」语义
            expr, _msg = py_assert_expr(e)
            verb = body.split("#", 1)[0].strip().split(" ", 1)[0].strip()
            probes.append({
                "label": f"{c['id']}: {body.split('#', 1)[0].strip()}",
                "expr": expr,
                "kind": kind or "plain",
                # 契约 §5.6 R9（2026-09-25 补；`3509 §B72`）：**按动词分状态取样**。
                # 单一取样状态无法同时满足两类要求（两种误报都实测踩过）：
                #   * 面板内 `hidden X` 在**未展开**时恒真 ⇒ `hidden` 类必须在**展开后**取样；
                #   * 面板内 `visible X` / `text X` 在**展开后**恒真 ⇒ 存在类必须在**真实渲染**时取样。
                # `unchanged:` 一律用展开态：它的期望方向相反（判据是「必须已成立」），
                # 用更宽松的态才不会把合法用例误判为自相矛盾。
                "sampling": "expanded" if verb == "hidden" or (kind or "plain") == "unchanged" else "rendered",
            })
    if not probes:
        return "", None
    fn = re.sub(r"[^0-9a-zA-Z]+", "_", page).strip("_")
    text = (
        f"def test_{fn}__zero_step_baseline(page):\n"
        '    \"\"\"契约 §5.6 R9 零步基线：本页全部用例 `expected` 断言的并集，在**未执行任何 step** 的初始态逐条求值。\n'
        "    两类失败：无前缀者在初始态成立 ⇒ 恒真断言；`unchanged:` 者在初始态不成立 ⇒ 用例自相矛盾。\n"
        f'    断言清单（数据）：_data/zero_step_{fn}.json\n'
        '    \"\"\"\n'
        f'    _atlas_zero_step_baseline(page, _HERE / "_data" / "zero_step_{fn}.json")\n'
    )
    payload = {"page": page, "url": url, "probes": probes}
    return text, payload


REV_TITLE = "## 页面 ↔ 用例"


def render_reverse_view(index_text: str, cases: dict) -> str | None:
    """按 `rings/e2e/reference.md` §3.2 由**主表 + 分片 `pages:`** 重写反向视图。

    该小节是 100% 派生信息（主表已有 `页面` 列），按 `shared/single-source.md` §2
    「同一信息两处正文判为漂移」⇒ 不再手工维护，改由生成器重写。
    列与判据与 `validate_e2e_index.py` 的「反向视图一致」检查同源：
    断言落点用例 = 主表 `页面` 命中者；链路经过用例 = `pages:` 含该页但落点不在该页者。
    """
    if REV_TITLE not in index_text:
        return None
    order: list[str] = []
    idx_page: dict[str, str] = {}
    for line in index_text.splitlines():
        m = re.match(r"^\|\s*(E2E-\S+)\s*\|\s*([^|]+?)\s*\|", line)
        if m:
            idx_page[m.group(1)] = m.group(2)
    if not idx_page:
        return None
    owner: dict[str, list[str]] = {}
    via: dict[str, list[str]] = {}
    for page, items in cases.items():
        for c in items:
            cid, home = c.get("id"), idx_page.get(c.get("id"))
            if not cid or not home:
                continue
            owner.setdefault(home, [])
            if cid not in owner[home]:
                owner[home].append(cid)
            for p in c.get("pages") or []:
                if p != home:
                    via.setdefault(p, [])
                    if cid not in via[p]:
                        via[p].append(cid)
    for line in index_text.split(REV_TITLE, 1)[1].splitlines():
        m = re.match(r"^\|\s*([a-z0-9][a-z0-9-]*)\s*\|", line)
        if m and m.group(1) not in order:
            order.append(m.group(1))
    for page in sorted(set(owner) | set(via)):
        if page not in order:
            order.append(page)
    rank = {cid: i for i, cid in enumerate(idx_page)}          # 用例顺序 = 索引主表顺序
    key = lambda cid: rank.get(cid, len(rank))
    out = [REV_TITLE, "", "| 页面 | 断言落点用例 | 链路经过用例 |", "|---|---|---|"]
    for p in order:
        out.append("| %s | %s | %s |" % (p, ", ".join(sorted(owner.get(p, []), key=key)),
                                        ", ".join(sorted(via.get(p, []), key=key))))
    return index_text.split(REV_TITLE, 1)[0].rstrip("\n") + "\n\n" + "\n".join(out) + "\n"


def ts_case(case: dict, url: str) -> str:
    cid = case["id"]
    ids = json.dumps(case.get("testid") or [], ensure_ascii=False)
    step_note = "\\n".join("//   - " + s for s in case.get("step", []))
    assert_note = "\\n".join("//   - " + s for s in case.get("expected", []))
    # 契约 §5.7（2026-09-30）：blocked/skipped ⇒ test.skip（状态真相源 = 索引，与 python 侧同义）。
    state = case.get("_state", "")
    state_reason = case.get("_state_reason", "")
    if state in ("blocked", "skipped"):
        # 标题含用例 ID：playwright 对同文件重复 test 标题报错，多条 blocked 用例共用
        # 同一状态原因时必须以 ID 区分（2026-10-01 projects 页首跑实测）。
        reason = f"[{state}] {cid}: {state_reason or state}"
        return (
            f"test.skip({json.dumps(reason, ensure_ascii=False)}, async () => {{\n"
            f"  // {cid}（用例正文唯一源：分片；状态真相源 = 索引）\n"
            "});\n"
        )
    auth = case.get("auth", "preset")
    if auth not in ("preset", "none"):
        raise ValueError(f"{cid}: auth 取值应为 preset|none，得 {auth!r}")
    wrap_open, wrap_close = "", ""
    if auth == "none":
        # 契约 §5.7：未登录前提 ⇒ describe 作用域覆盖预置 storageState 为干净 context。
        wrap_open = (
            "test.describe('atlas auth none', () => {\n"
            "  test.use({ storageState: { cookies: [], origins: [] } });\n"
        )
        wrap_close = "});\n"
    actions: list[str] = []
    for s in case.get("step", []):
        verb, tid, value, _ = parse_line(s)
        if verb == "refresh":
            actions.append("await page.reload();")
        elif verb == "goto":
            actions.append(f"await page.goto('{value}');")
        elif verb == "click":
            actions.append(f"await page.getByTestId('{tid}').click();")
        elif verb == "fill":
            actions.append(f"await page.getByTestId('{tid}').fill({json.dumps(value, ensure_ascii=False)});")
        elif verb == "select":
            # 契约 §5.5（B173-1）：发射实现无关 helper，不再钉死原生 `<select>` ——
            # 语义 = 「选中 label 的那一项」，DOM 机制由 helper 按元素自适应。
            actions.append(f"await atlasSelect(page, '{tid}', {json.dumps(value, ensure_ascii=False)});")
        elif verb == "check":
            actions.append(f"await page.getByTestId('{tid}').check();")
        elif verb == "uncheck":
            actions.append(f"await page.getByTestId('{tid}').uncheck();")
        elif verb == "press":
            actions.append(f"await page.getByTestId('{tid}').press({json.dumps(value)});")
        elif verb == "hover":
            actions.append(f"await page.getByTestId('{tid}').hover();")
        elif verb == "waitFor":
            # 契约 §7.1：带轮询的断言（不得退化为固定等待）—— 与 python 侧同义
            loc = f"page.getByTestId('{tid}')"
            if value == "":
                actions.append(f"await expect({loc}).toBeVisible({{ timeout: ATLAS_WAIT_TIMEOUT_MS }});")
            else:
                actions.append(
                    f"await expect({loc}).toHaveText({json.dumps(value, ensure_ascii=False)}, "
                    "{ timeout: ATLAS_WAIT_TIMEOUT_MS, useInnerText: true });"
                )
        elif verb == "download":
            # 契约 §5.5（与 python 侧同源同义）：先注册监听、再点击、再校验建议文件名（glob）。
            if not value.strip():
                raise ValueError(f"`download` 需要文件名 glob 参数: {s!r}（契约 §5.5）")
            actions.append(
                f"await atlasDownload(page, '{tid}', {json.dumps(value, ensure_ascii=False)});"
            )
        else:
            raise ValueError(f"未知动作动词: {verb}（契约 §5.5）")
    pre: list[str] = []
    delta_pre: list[str] = []               # 契约 §5.5（P5）：`delta` 行动前采样，贴第一个提交性动作
    anchors: dict[int, list[str]] = {}      # 契约 §5.5：`after:<N>` 的断言，按 step 序号挂
    terminal: list[str] = []
    for raw in case.get("expected", []):
        kind, e = split_prefix(raw)
        verb, tid, value, _ = parse_line(e)
        v = json.dumps(value, ensure_ascii=False)
        if verb == "text":
            line = f"await expect(page.getByTestId('{tid}')).toHaveText({v});"
        elif verb == "contains":
            line = f"await expect(page.getByTestId('{tid}')).toContainText({v});"
        elif verb == "count":
            line = f"await expect(page.getByTestId('{tid}')).toHaveCount(Number({v}));"
        elif verb == "visible":
            line = f"await expect(page.getByTestId('{tid}')).toBeVisible();"
        elif verb == "hidden":
            line = f"await expect(page.getByTestId('{tid}')).toBeHidden();"
        elif verb == "enabled":
            line = f"await expect(page.getByTestId('{tid}')).toBeEnabled();"
        elif verb == "disabled":
            line = f"await expect(page.getByTestId('{tid}')).toBeDisabled();"
        elif verb == "value":
            # 契约 §5.5（与 python 侧同源同义）：值写作 `""` / `(空)` 时是**空串**，
            # 必须渲染成空串实参 —— 直接 json.dumps 会得到两个字面引号字符，
            # 与真实空串永不相等。（B173-1：断言经 atlasExpectValue 实现无关化。）
            if value.strip() in ('""', "(空)"):
                v = json.dumps("", ensure_ascii=False)
            line = f"await atlasExpectValue(page, '{tid}', {v});"
        elif verb == "countOptions":
            # 契约 §5.5（与 python 侧同源同义）：数该元素内的 `option` 子元素个数。
            line = f"await expect(page.getByTestId('{tid}').locator('option')).toHaveCount(Number({v}));"
        elif verb == "checked":
            line = f"await expect(page.getByTestId('{tid}')).toBeChecked();"
        elif verb == "unchecked":
            line = f"await expect(page.getByTestId('{tid}')).not.toBeChecked();"
        elif verb == "attr":
            # 契约 §5.5（与 python 侧同源同义）：`attr <testid> <name> <value>`。
            aname, _, aval = value.strip().partition(" ")
            aval = aval.strip()
            if not aname or not aval:
                raise ValueError(f"`attr` 需要 `<name> <value>` 两个参数: {raw!r}（契约 §5.5）")
            line = (
                f"await expect(page.getByTestId('{tid}')).toHaveAttribute("
                f"{json.dumps(aname, ensure_ascii=False)}, {json.dumps(aval, ensure_ascii=False)});"
            )
        elif verb == "delta":
            # 契约 §5.5（P5，2026-10-07）：`delta <tid> <±N>` 相对断言 —— 行动前采样
            # （贴第一个提交性动作，与 py 侧同点）、行动后 `expect.poll` 轮询复读
            # （SPA 竞态安全），差值必须恰为 ±N。与豁免通道 / 步骤锚叠写 ⇒ 生成期中止
            # （校验器同判 FAIL，双保险）。
            if kind is not None or split_after(raw)[0] is not None:
                raise ValueError(f"`delta` 不得与 initial:/unchanged:/after: 叠写: {raw!r}（契约 §5.5）")
            if not re.fullmatch(r"[+-]\d+", value.strip()):
                raise ValueError(f"`delta` 值须为带符号整数 ±N: {raw!r}（契约 §5.5）")
            if not case.get("step"):
                raise ValueError(f"{cid}: delta 相对断言需要至少一条 step（行动前采样点不存在）")
            var = "__delta_" + re.sub(r"[^0-9a-zA-Z]", "_", tid)
            delta_pre.append(f"const {var} = await atlasIntOf(page.getByTestId('{tid}'));")
            line = (
                f"await expect.poll(() => atlasIntOf(page.getByTestId('{tid}')), "
                f"{{ timeout: ATLAS_WAIT_TIMEOUT_MS }}).toBe({var} + {int(value.strip())});"
            )
        else:
            raise ValueError(f"未知断言动词: {verb}（契约 §5.5）")
        _n, _ = split_after(raw)
        if _n is not None:
            anchors.setdefault(_n, []).append(line)   # 钉在第 _n 条 step **之后**
        else:
            if kind == UNCHANGED:
                pre.append(line)  # 契约 §5.6 R9：行动前必须成立
            terminal.append(line)
    # 组装顺序：行动前断言 → （每条 step + 它身后的锚断言）→ 终态断言。
    # `actions` 与 `step` 一一对应（每个动作分支只 append 一次），故可直接按序号对位。
    # `delta` 的行动前采样贴**第一个提交性动作**（与 `unchanged:` 先例同点、与 py 侧同构）；
    # 无提交性动作时退回第一个 step 之前（校验器对此 FAIL，此处保持保守位置）。
    delta_pos = next((i for i, s in enumerate(case.get("step", []), start=1)
                      if any(w in s.split("#", 1)[0] for w in SUBMITTING_WORDS)), 1)
    seq: list[str] = list(pre)
    for _i, _act in enumerate(actions, start=1):
        if _i == delta_pos and delta_pre:
            seq.extend(delta_pre)
        seq.append(_act)
        seq.extend(anchors.get(_i, []))
    seq.extend(terminal)
    indented = "\n".join("  " + b for b in seq)
    body = (
        f"test({json.dumps(cid + ' ' + (case.get('_title') or ''), ensure_ascii=False)}, async ({{ page }}) => {{\n"
        f"  {step_note}\n  {assert_note}\n"
        f"  await page.goto('{url}');\n"
        f"  for (const id of {ids}) {{\n    await expect(page.getByTestId(id)).toHaveCount(1);\n  }}\n"
        f"{indented}\n}});\n"
    )
    if wrap_open:
        indented_body = "\n".join("  " + ln for ln in body.rstrip("\n").splitlines())
        return wrap_open + indented_body + "\n" + wrap_close
    return body


def ts_assert_expr(line: str) -> str:
    """把一行断言渲染成 **awaitable 布尔表达式串**（`ts_assert` / 零步基线 runner 共用）。

    与 `py_assert_expr` 逐动词同构（复用而非复制）：语义漂移面只有这一处。
    表达式求值环境 = 页面文件 header 的 `tsVis` / `tsVisible` / `page`。
    """
    _, line = split_prefix(line)
    verb, tid, value, _note = parse_line(line)
    v = json.dumps(value, ensure_ascii=False)
    t = json.dumps(tid, ensure_ascii=False)
    if verb == "text":
        # 与 python `_vis` 语义对齐：元素不可见 ⇒ **null**（基线 runner 跳过，不是 false）
        return (
            f'(async () => {{ const l = await tsVis(page, {t}); '
            f"return l === null ? null : (await l.innerText()).trim() === {v}; }})()"
        )
    if verb == "contains":
        return (
            f'(async () => {{ const l = await tsVis(page, {t}); '
            f"return l === null ? null : (await l.innerText()).includes({v}); }})()"
        )
    if verb == "count":
        return f"(async () => (await page.getByTestId({t}).count()) === Number({v}))()"
    if verb == "countOptions":
        return f"(async () => (await page.getByTestId({t}).locator('option').count()) === Number({v}))()"
    if verb == "visible":
        return f"(async () => await tsVisible(page, {t}))()"
    if verb == "hidden":
        return f"(async () => !(await tsVisible(page, {t})))()"
    # is*() 对缺失元素会等挂载（30s 挂起）——先 count 守卫：缺失 ⇒ false（基线探针安全跳过）
    if verb == "enabled":
        return f"(async () => (await page.getByTestId({t}).count()) > 0 && (await page.getByTestId({t}).first().isEnabled()))()"
    if verb == "disabled":
        return f"(async () => (await page.getByTestId({t}).count()) > 0 && (await page.getByTestId({t}).first().isDisabled()))()"
    if verb == "checked":
        return f"(async () => (await page.getByTestId({t}).count()) > 0 && (await page.getByTestId({t}).first().isChecked()))()"
    if verb == "unchecked":
        return f"(async () => !((await page.getByTestId({t}).count()) > 0 && (await page.getByTestId({t}).first().isChecked())))()"
    if verb == "value":
        if value.strip() in ('""', "(空)"):
            v = json.dumps("", ensure_ascii=False)
        # 契约 §5.5（B173-1）：经 atlasValueOf 实现无关化（三态语义不变：不可见 ⇒ null）。
        return (
            f'(async () => {{ const x = await atlasValueOf(page, {t}); '
            f"return x === null ? null : x === {v}; }})()"
        )
    if verb == "attr":
        name, _, val = value.strip().partition(" ")
        val = val.strip()
        if not name or not val:
            raise ValueError(f"`attr` 需要 `<name> <value>` 两个参数: {line!r}（契约 §5.5）")
        n = json.dumps(name, ensure_ascii=False)
        return (
            f"(async () => (await page.getByTestId({t}).first().getAttribute({n})) "
            f"=== {json.dumps(val, ensure_ascii=False)})()"
        )
    raise ValueError(f"未知断言动词: {verb}（契约 §5.5）")


def ts_zero_step_baseline(page: str, url: str, cases: list[dict]) -> str:
    """TS 版零步基线（契约 §5.6 R9；与 py_zero_step_baseline **同构**）。

    同一设计：断言清单落 `_data/zero_step_<page>.json`（label/expr/kind/sampling），
    运行期 runner 在页面 header（`atlasZeroStepBaseline`）。`expr` = ts_assert_expr
    的 awaitable 串——与用例断言**同源渲染**，两条路径语义不可能漂。
    """
    probes: list[dict] = []
    for c in cases:
        if c.get("_state") in ("blocked", "skipped"):
            # 契约 §7（2026-10-01 补）：与 py 侧同构——blocked/skipped 用例不进基线探针。
            continue
        for e in c.get("expected") or []:
            kind, body = split_prefix(e)
            if kind == "initial":
                continue  # 显式豁免：不参与零步基线
            if body.split("#", 1)[0].strip().split(" ", 1)[0] == "delta":
                continue  # 契约 §5.5（P5）：delta 是行动前后差值断言，没有「初始态成立/不成立」语义
            expr = ts_assert_expr(e)
            verb = body.split("#", 1)[0].strip().split(" ", 1)[0].strip()
            probes.append({
                "label": f"{c['id']}: {body.split('#', 1)[0].strip()}",
                "expr": expr,
                "kind": kind or "plain",
                # §B72 两趟取样：hidden 类与 unchanged: 用展开态；存在类用真实渲染态。
                "sampling": "expanded" if verb == "hidden" or (kind or "plain") == "unchanged" else "rendered",
            })
    if not probes:
        return ""
    fn = re.sub(r"[^0-9a-zA-Z]+", "_", page).strip("_")
    data = json.dumps({"url": url, "probes": probes}, ensure_ascii=False, separators=(",", ":"))
    return (
        f"const ATLAS_ZS_{fn} = {data};\n"
        f"test('test_{fn}__zero_step_baseline', async ({{ page }}) => {{\n"
        f"  await atlasZeroStepBaseline(page, ATLAS_ZS_{fn});\n"
        "});\n"
    )


def write(path: Path, content: str, apply: bool, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    changed = not path.is_file() or path.read_text(encoding="utf-8") != content
    results.append({"file": str(path), "changed": changed})
    if apply and changed:
        path.write_text(content, encoding="utf-8")


REVIEW_DIRNAME = "reviews"
# 审查报告目录形态：`<YYYY-MM-DD>-<范围>`（契约 `shared/independent-review.md` §1 末注）。
REVIEW_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")
REVIEW_LEVELS = {"PASS", "WARN", "FAIL"}


def latest_review_report(reports_dir: Path) -> Path | None:
    """取**目录名日期前缀最大**的那份报告目录（契约 §4「报告定位」）。

    不引入指针文件：落点形态 `<日期>-<范围>` 已是契约固定的 ⇒ 可机器排序。
    """
    if not reports_dir.is_dir():
        return None
    dated = []
    for p in reports_dir.iterdir():
        if not p.is_dir():
            continue
        m = REVIEW_DIR_RE.match(p.name)
        if m:
            dated.append((m.group(1), p.name, p))
    if not dated:
        return None
    dated.sort()
    return dated[-1][2]


def review_report_status(reports_dir: Path) -> tuple[str, str]:
    """返回 `(level, detail)`；level ∈ `ok` / `missing` / `invalid` / `critical`。

    判据**不在门口信任模型结论**（契约 §4）：读的是 `review.json` 的 `status` 字段，
    它不是由本脚本根据模型输出推出来的，而是审查器自己落的盘。
    """
    d = latest_review_report(reports_dir)
    if d is None:
        return "missing", f"{reports_dir} 下没有 <YYYY-MM-DD>-<范围> 形式的审查报告"
    rj = d / "review.json"
    if not rj.is_file():
        return "invalid", f"{rj.relative_to(reports_dir.parent.parent.parent)} 不存在"
    try:
        data = json.loads(rj.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — 仅用于报出原因
        return "invalid", f"{d.name}/review.json 解析失败：{exc}"
    status = data.get("status")
    if status not in REVIEW_LEVELS:
        return "invalid", f"{d.name}/review.json 的 status={status!r} 不在 {sorted(REVIEW_LEVELS)} 内"
    if status == "FAIL":
        crit = [c for c in (data.get("checks") or []) if c.get("level") == "Critical"]
        return "critical", f"{d.name} 含 {len(crit)} 条 Critical"
    return "ok", f"{d.name} status={status}"


def review_gate(root: Path) -> tuple[bool, list[str]]:
    """独立审查门（契约 `rings/e2e/reference.md` §12.6 + `§7.1`；E1：只验本环报告）。

    判据 = **报告存在 + 无 Critical**（可机器判）；报告缺失 **= 未审，不是「通过」**。
    """
    reasons: list[str] = []
    level, detail = review_report_status(root / "product" / "e2e" / REVIEW_DIRNAME)
    if level != "ok":
        reasons.append(f"E2E 环审查报告不合格（{level}）：{detail}"
                       "（跑 rings/e2e/reference.md §12）")
    return (not reasons), reasons


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    prof_path = root / "product" / "stack-profile.yaml"
    if not prof_path.is_file():
        print(f"ERROR: 缺 {prof_path}", file=sys.stderr)
        return 2
    prof = parse_profile(prof_path.read_text(encoding="utf-8"))
    e2e = prof.get("e2e") or {}
    runner = e2e.get("runner") or "python-playwright"
    if runner not in RUNNERS:
        print(f"ERROR: 未知 e2e.runner={runner!r}（允许 {sorted(RUNNERS)}）", file=sys.stderr)
        return 2
    ext = RUNNERS[runner]
    scripts_dir = root / (e2e.get("scripts_dir") or "product/e2e/scripts")
    # 契约 §5.7（2026-09-30）：`auth: none` 当前只在 python 运行器路径实现
    # （2026-09-30 拉平：node 运行器已实现 auth:none——describe 内 test.use 覆盖
    # storageState 为干净 context；原「node 遇 auth:none 诚实中止」守卫随之移除。）

    base = e2e.get("app_base_url")
    if not base:
        msg = ("e2e.app_base_url 为空（E1 单段：唯一靶场地址，契约要求向用户索取，不猜默认）")
        if args.json:
            print(json.dumps({"ok": False, "not_ready": "app_base_url", "message": msg},
                             ensure_ascii=False, indent=2))
        print(f"NOT_READY: {msg}", file=sys.stderr)
        return NOT_READY

    app_login = e2e.get("app_login") or None
    if app_login is not None:
        missing = [k for k in APP_LOGIN_FIELDS if not (app_login.get(k) or "").strip()]
        if missing:
            print(f"ERROR: e2e.app_login 段不完整（缺 {missing}）——要么补齐全部字段，"
                  "要么整段删除（未声明 = 合法降级：跳过登录预置 + 明确警告）", file=sys.stderr)
            return 2
    else:
        print("WARN: stack-profile 未声明 e2e.app_login —— 将跳过登录态预置"
              "（生成物与运行期均会警告；依赖预置登录态的用例会失败）", file=sys.stderr)

    # 数据播种通道（契约 §5.7，2026-09-28）：`e2e.seed.hook`（项目自定实现，路径相对项目根）。
    # `e2e.seed.mode`（B197-1，2026-10-07）：声明 / 发射解耦开关——enforce（缺省 = 现行为，
    # 每用例运行期播种）/ declare（`seed:` 行只参与静态对账，不发射运行期播种）。
    seed_cfg = e2e.get("seed") or {}
    seed_hook = seed_cfg.get("hook")
    seed_mode = seed_cfg.get("mode") or "enforce"
    if seed_mode not in ("declare", "enforce"):
        print(f"ERROR: e2e.seed.mode 非法: {seed_mode!r}（允许 declare|enforce；缺省 enforce）"
              "——契约见 shared/stack-profile.md §2 + rings/e2e/reference.md §5.7", file=sys.stderr)
        return 2

    cases = gather_cases(root / "product" / "e2e" / "cases")
    # 响亮原则：用例写了 `seed:` 但没声明通道 ⇒ 生成期就 WARN（否则只能等运行期才发現）。
    # declare 模式下无运行期播种面 ⇒ 不发此 WARN（改发 hook 无用警告）。
    if seed_hook is None and seed_mode == "enforce":
        seeded = [c["id"] for items in cases.values() for c in items if c.get("seed")]
        if seeded:
            print(f"WARN: {len(seeded)} 条用例写了 `seed:` 但 stack-profile 未声明 e2e.seed.hook"
                  f" ⇒ 生成物会在运行期跳过播种并警告（例：{seeded[:3]}）", file=sys.stderr)
    if seed_mode == "declare" and seed_hook:
        print("WARN: e2e.seed.hook 已声明但 seed.mode=declare ⇒ 运行期不播种、hook 不生效"
              "（B197-1；只取声明层 = seed×models 静态对账）", file=sys.stderr)
    if seed_mode == "declare":
        # declare 分流（B197-1）：清空 case 的 seed 发射面。静态对账不受影响——
        # validate_e2e_index 的 seed×models 门直接读分片文件，不经生成器。
        for items in cases.values():
            for c in items:
                c["seed"] = []
    idx_path = root / (e2e.get("index") or "product/e2e/e2e-index.md")
    urls = page_urls(idx_path.read_text(encoding="utf-8")) if idx_path.is_file() else {}
    if not cases:
        print("no cases（门控态或未建用例）；不生成脚本。")
        return 0
    miss_route = sorted(set(cases) - set(urls))
    if miss_route:
        print(f"ERROR: 索引页面表缺路由：{miss_route}（页面表 = {idx_path}，契约 §3.2）",
              file=sys.stderr)
        return 2

    # 独立审查门（契约 §12.6 / §7.1）：存在性挂在**写盘动作**上；dry-run 只报状态。
    gate_ok, gate_reasons = review_gate(root)
    if not gate_ok and args.apply:
        print("ERROR: 独立审查门未通过（rings/e2e/reference.md §12.6），拒绝写盘：", file=sys.stderr)
        for r in gate_reasons:
            print(f"  - {r}", file=sys.stderr)
        return 2

    # 动词合法性（契约 §5.5）：词表外的动词 → 中止并列出违规行
    bad: list[str] = []
    for _page, items in cases.items():
        for c in items:
            for kind, allowed in (("step", ACTION_VERBS), ("expected", ASSERT_VERBS)):
                for s in c.get(kind) or []:
                    # 契约 §5.6 R9：`expected` 行可带 `initial:` / `unchanged:` 前缀（显式声明判据形状），
                    # 判动词前先剥离；`step` 行出现前缀则按普通动词校验 ⇒ 自然 FAIL。
                    raw = split_prefix(s)[1] if kind == "expected" else s
                    first = raw.split("#", 1)[0].strip().split(" ", 1)[0].strip()
                    if first not in allowed:
                        bad.append(f"{c['id']} {kind}: {s}")
    if bad:
        print("ERROR: step/expected 动词不在词表内（契约 rings/e2e/reference.md §5.5）：", file=sys.stderr)
        for b in bad[:40]:
            print(f"  - {b}", file=sys.stderr)
        print(f"  共 {len(bad)} 行", file=sys.stderr)
        return 2

    results: list[dict] = []
    data_files: set[str] = set()
    generated = 0
    idx_text = idx_path.read_text(encoding="utf-8") if idx_path.is_file() else ""
    case_states = index_case_states(idx_text)
    for page, items in cases.items():
        url = urls[page]
        for c in items:
            st = case_states.get(c.get("id", ""), ("", ""))
            c["_state"], c["_state_reason"] = st[0], st[1]
        if runner == "python-playwright":
            # 契约 §5.6 R9：每页一条零步基线（只 goto，逐条求值全部用例的断言并集）。
            # ** emission order = 执行 order（pytest 按定义序）**：基线必须**先于**用例——
            #   真栈时代用例会持久化改库状态（实测 config 批：005 后 provider 恒「不可用」），
            #   基线后跑会把「断言因前序用例改态而成立」误判成「初始态恒真」假红。
            baseline, payload = py_zero_step_baseline(page, url, items)
            if baseline:
                body = py_header(runner) + baseline + "\n\n" + "\n\n".join(
                    py_case(c, url) for c in items)
                fn = re.sub(r"[^0-9a-zA-Z]+", "_", page).strip("_")
                data_files.add(f"zero_step_{fn}.json")
                # 紧凑序列化：这是**数据**（只有断言变化时才变），不进人工/agent 的阅读面
                write(scripts_dir / "_data" / f"zero_step_{fn}.json",
                      json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                      args.apply, results)
            else:
                body = py_header(runner) + "\n\n".join(
                    py_case(c, url) for c in items)
            # 标题来自分片 `## <ID> 标题`；此处 best-effort 注入
        else:
            # 契约 §5.6 R9（2026-09-30）：基线先于用例（与 python 侧同因：真栈用例持久化改态）。
            body = (
                "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py"
                f" (runner={runner})；重跑覆盖；深断言放 _support/\n"
                "import { test, expect } from '@playwright/test';\n"
                "import { readFileSync } from 'node:fs';\n"
                "// 契约 §7.1：`waitFor` 的超时默认值（与 python 侧同值）\n"
                "const ATLAS_WAIT_TIMEOUT_MS = 10_000;\n\n"
                "function tsLoc(page: any, tid: string) {\n"
                "  return page.getByTestId(tid).first();\n"
                "}\n"
                "async function tsVisible(page: any, tid: string): Promise<boolean> {\n"
                "  const loc = page.getByTestId(tid);\n"
                "  return (await loc.count()) > 0 && (await loc.first().isVisible());\n"
                "}\n"
                "async function tsVis(page: any, tid: string) {\n"
                "  // 契约 §7.1：读值断言须先可见；不可见 ⇒ null（= 不成立，不抛错）\n"
                "  const l = page.getByTestId(tid).first();\n"
                "  return (await l.isVisible()) ? l : null;\n"
                "}\n"
                "async function atlasValueOf(page: any, tid: string): Promise<string | null> {\n"
                "  // 契约 §5.5（B173-1，2026-10-04）：`value` 断言/探针的实现无关入口。\n"
                "  // 原生表单元素读 input 值；否则视作 trigger+listbox 组合（如 Radix/shadcn\n"
                "  // Select），其「当前值」= 触发器可见文本。E2E 只断言行为，不约束组件实现。\n"
                "  const l = await tsVis(page, tid);\n"
                "  if (l === null) return null;\n"
                "  const tag = await l.evaluate((e) => e.tagName.toLowerCase());\n"
                "  return (tag === 'select' || tag === 'input' || tag === 'textarea')\n"
                "    ? l.inputValue()\n"
                "    : (await l.innerText()).trim();\n"
                "}\n"
                "async function atlasSelect(page: any, tid: string, label: string) {\n"
                "  // 契约 §5.5（B173-1，2026-10-04）：`select` 动词的实现无关入口 ——\n"
                "  // 语义 = 「在该控件上选中 label 的那一项」。原生 <select> 走 selectOption；\n"
                "  // 否则视作 trigger+listbox 组合：点开触发器后按可访问名点选 option。\n"
                "  const el = page.getByTestId(tid).first();\n"
                "  const tag = await el.evaluate((e) => e.tagName.toLowerCase());\n"
                "  if (tag === 'select') {\n"
                "    await el.selectOption({ label });\n"
                "    return;\n"
                "  }\n"
                "  await el.click();\n"
                "  await page.getByRole('option', { name: label, exact: true }).first().click();\n"
                "}\n"
                "async function atlasIntOf(loc: any): Promise<number> {\n"
                "  // 契约 §5.5（P5，2026-10-07）：`delta` 相对断言的取数 —— 元素文本中的首个整数。\n"
                "  // 找不到数值即响亮失败（永不静默当 0 处理；与 python `_int_of` 同构）。\n"
                "  const text = await loc.innerText({ timeout: ATLAS_WAIT_TIMEOUT_MS });\n"
                "  const m = text.match(/-?\\d+/);\n"
                "  if (!m) throw new Error('delta 采样：元素文本不含数值: ' + text);\n"
                "  return Number(m[0]);\n"
                "}\n"
                "async function atlasExpectValue(page: any, tid: string, v: string) {\n"
                "  // 契约 §5.5（B173-1，2026-10-04）：`value` 断言的实现无关入口\n"
                "  // （与 atlasValueOf 同判；两分支都保留 expect 的自动轮询语义）。\n"
                "  const el = page.getByTestId(tid).first();\n"
                "  const tag = await el.evaluate((e) => e.tagName.toLowerCase());\n"
                "  if (tag === 'select' || tag === 'input' || tag === 'textarea') {\n"
                "    await expect(el).toHaveValue(v);\n"
                "  } else {\n"
                "    await expect(el).toHaveText(v, { useInnerText: true });\n"
                "  }\n"
                "}\n"
                "async function atlasProbeOnce(page: any, p: any): Promise<boolean | null> {\n"
                "  // 三态透传（与 python runner 同判）：true/false/**null**——\n"
                "  // null = 元素不可见或求值异常（expr 的 `l === null ? null : …` 分支），\n"
                "  // unchanged 探针对 null **跳过**（python 侧 except-continue 的等价），不得折叠成 false。\n"
                "  try {\n"
                "    const v = await eval(p.expr);\n"
                "    return v === null ? null : v ? true : false;\n"
                "  } catch {\n"
                "    return null;\n"
                "  }\n"
                "}\n"
                "async function atlasExpandPanels(page: any) {\n"
                "  // §B49：hidden/unchanged 断言在展开全部 Tab 级面板后取样（hidden 属性语义）。\n"
                "  // CSS 类隐藏（shadcn data-[state=inactive]:hidden 等）在 React 重渲染下无法稳定\n"
                "  // 强开 ⇒ 与 python 侧同判：探不到（isVisible=false）的 unchanged 探针**跳过**，\n"
                "  // 由正式用例自身的 pre 断言把关（runner 对 ok===false 才记 contradictory）。\n"
                "  for (const el of await page.locator('[data-atlas-panel]').all()) {\n"
                "    try { await el.evaluate('(e) => { e.hidden = false; }'); } catch { /* 忽略 */ }\n"
                "  }\n"
                "}\n"
                "async function atlasZeroStepBaseline(page: any, data: any) {\n"
                "  // 契约 §5.6 R9：初始态观测（数据驱动；两趟取样 §B72）。\n"
                "  // 判据『以返回值判定』而非『没抛异常』——tsVis 对隐藏元素返回 null = 不成立。\n"
                "  await page.goto(data.url);\n"
                "  // SPA 安定：React 异步渲染/API 响应会重渲染并冲掉手改的展开样式，\n"
                "  // 两趟取样都必须在**安定态**；networkidle 不可达环境超时降级为继续。\n"
                "  await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => { });\n"
                "  const initialTrue: string[] = [];\n"
                "  const contradictory: string[] = [];\n"
                "  for (const pass of ['rendered', 'expanded'] as const) {\n"
                "    for (const p of data.probes) {\n"
                "      if (p.sampling !== pass) continue;\n"
                "      if (pass === 'expanded') await atlasExpandPanels(page);  // 每条前重展开（重渲染会冲掉，幂等廉价）\n"
                "      const ok = await atlasProbeOnce(page, p);\n"
                "      if (p.kind === 'unchanged') {\n"
                "        // 与 python 侧同判：null（元素不可见/求值异常——如 Tab 未展开的面板）⇒ 跳过；\n"
                "        // 零步基线无 step 无法展开交互面板，该面由正式用例自身的 pre 断言把关。\n"
                "        if (ok === false) contradictory.push(p.label);\n"
                "      } else if (ok === true) {\n"
                "        initialTrue.push(p.label);\n"
                "      }\n"
                "    }\n"
                "  }\n"
                "  const misses = [...initialTrue, ...contradictory];\n"
                "  expect(misses, `零步基线（恒真/自相矛盾）：${misses.join('；')}`).toEqual([]);\n"
                "}\n\n"
                "// 契约 §5.5：`download` 的 glob 语义（与 python 侧 `fnmatch` 同义：* 任意串 / ? 单字符）\n"
                "function atlasGlob(pattern) {\n"
                r"  return new RegExp('^' + pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&')"
                ".replace(/\\*/g, '.*').replace(/\\?/g, '.') + '$');\n"
                "}\n"
                "async function atlasDownload(page, tid, pattern) {\n"
                "  const [download] = await Promise.all([\n"
                "    page.waitForEvent('download', { timeout: ATLAS_WAIT_TIMEOUT_MS }),\n"
                "    page.getByTestId(tid).click(),\n"
                "  ]);\n"
                "  const name = download.suggestedFilename();\n"
                "  expect(name, `下载文件名 ${name} 不匹配 ${pattern}`).toMatch(atlasGlob(pattern));\n"
                "}\n\n"
                + ts_zero_step_baseline(page, url, items) + "\n"
                + "\n".join(ts_case(c, url) for c in items)
            )
        write(scripts_dir / f"{page}{ext}", body, args.apply, results)
        # runner 切换后清理另一扩展名的旧页面脚本（否则双份同语义产物互斥漂移）
        other_ext = next(e for e, r in RUNNERS.items() if e != ext and RUNNERS[e] != ext) if False else (
            ".py" if ext == ".spec.ts" else ".spec.ts")
        stale = scripts_dir / f"{page}{other_ext}"
        if stale.is_file():
            stale.unlink()
            results.append({"file": str(stale) + "（旧 runner 清理）", "changed": True})
        generated += 1

    # 运行器原生配置：承载 baseURL（不硬编码在用例脚本里）
    if runner == "python-playwright":
        cfg = (
            "# AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py；重跑覆盖。\n"
            "import json\n"
            "import os\n"
            "import pytest\n\n"
            f'_DEFAULT_BASE = "{base}"  # E1 单段：唯一靶场 = 真实应用（e2e.app_base_url）\n'
            f"_PAGE_FILES = ({', '.join(repr(f'{p}.py') for p in sorted(cases))},)\n\n\n"
            '@pytest.fixture(scope="session")\n'
            "def base_url():\n"
            '    return os.environ.get("ATLAS_BASE_URL", _DEFAULT_BASE)\n\n\n'
            '# 人工 review（2026-09-23）：如需跑完**不自动关窗**、由人手动关闭，\n'
            '# 设 ATLAS_KEEP_OPEN=1（并可设 ATLAS_RESULT_FILE=<路径>）——控制台就是这么用的。\n'
            'import sys\n'
            "_KEEP_OPEN = os.environ.get(\"ATLAS_KEEP_OPEN\") == \"1\"\n"
            '_OUTCOME = pytest.StashKey()\n\n\n'
            'def _write_result(exitstatus):\n'
            '    path = os.environ.get("ATLAS_RESULT_FILE")\n'
            '    if not path:\n'
            '        return\n'
            '    try:\n'
            '        with open(path, "w", encoding="utf-8") as fh:\n'
            '            json.dump({"exitstatus": int(exitstatus)}, fh)\n'
            '    except Exception:\n'
            '        pass\n\n\n'
            'def pytest_runtest_makereport(item, call):\n'
            '    if call.when == "call":\n'
            '        item.stash[_OUTCOME] = call.excinfo is None\n\n\n'
            '# 应用靶场真实登录（契约 §5.4 / §7.1）：\n'
            '#   * 端点 / 表单字段名 / 令牌键 / 前端读取的存储键 = 取证值，登记在\n'
            '#     product/stack-profile.yaml 的 e2e.app_login 段（shared/stack-profile.md §2），\n'
            '#     生成时烘进 _APP_LOGIN；段缺失 = 合法降级（跳过登录预置 + 明确警告）。\n'
            '#   * 凭据只来自运行期环境变量 ATLAS_APP_USER / ATLAS_APP_PASSWORD\n'
            '#     （不读项目 .env、不硬编码）；未设置 ⇒ 跳过预置并打印警告（不静默）。\n'
            '#   * 换取令牌失败（网络 / 凭据 / 端点变更）⇒ 报错中止 —— 不得静默续跑成假绿。\n'
            f'_APP_LOGIN = {app_login!r}  # None = stack-profile 未声明 e2e.app_login\n'
            f'_SEED = {seed_hook!r}  # None = stack-profile 未声明 e2e.seed.hook（合法降级 + 明确警告）\n\n\n'
            'def _seed(page, entity, fields):\n'
            '    """用例级数据播种（契约 §5.7）：幂等 upsert；未声明通道 ⇒ **明确警告**（不静默）。\n\n'
            '    接口语义 = 「输入实体清单 ⇒ 保证存在」；实现由项目自定（`e2e.seed.hook`）。\n'
            '    """\n'
            '    if _SEED is None:\n'
            '        print(f"[atlas] 警告：未声明 e2e.seed.hook ⇒ 跳过播种 {entity}"\n'
            '              "（依赖该数据的断言会失败）", file=sys.stderr, flush=True)\n'
            '        return\n'
            '    import importlib.util as _ilu\n'
            '    import os as _os\n'
            '    root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))\n'
            '    target = _os.path.join(root, _SEED)\n'
            '    if not _os.path.isfile(target):\n'
            '        raise RuntimeError(f"[atlas] e2e.seed.hook 指向的文件不存在：{target}"\n'
            '                           "（product/stack-profile.yaml 的 e2e.seed.hook）")\n'
            '    _spec = _ilu.spec_from_file_location("atlas_seed_hook", target)\n'
            '    _mod = _ilu.module_from_spec(_spec)\n'
            '    _spec.loader.exec_module(_mod)\n'
            '    _mod.upsert(entity, fields)  # 幂等；已存在则更新\n\n\n'
            'def _atlas_app_token(base_url, user, password):\n'
            '    """应用靶场：**真实登录**换取令牌（session 级，一次）。\n\n'
            '    失败必须响亮：网络不通 / 凭据错误 / 端点变更都抛 RuntimeError 中止，\n'
            '    不静默返回 —— 静默 = 「未登录态跑用例」的假绿。\n'
            '    """\n'
            '    import urllib.parse\n'
            '    import urllib.request\n'
            '    path = _APP_LOGIN["endpoint"]\n'
            '    form = {_APP_LOGIN["username_field"]: user, _APP_LOGIN["password_field"]: password}\n'
            '    url = base_url.rstrip("/") + path\n'
            '    data = urllib.parse.urlencode(form).encode("utf-8")\n'
            '    req = urllib.request.Request(url, data=data, method="POST",\n'
            '                                 headers={"Content-Type": "application/x-www-form-urlencoded"})\n'
            '    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 回环地址直连，绕代理\n'
            '    try:\n'
            '        with opener.open(req, timeout=10) as resp:\n'
            '            token = (json.loads(resp.read().decode("utf-8")) or {}).get(_APP_LOGIN["token_key"])\n'
            '    except Exception as exc:\n'
            '        raise RuntimeError(\n'
            '            f"[atlas] 应用靶场登录失败（{url}，user={user}）：{exc!r}"\n'
            '            f"—— 核对服务可达 / ATLAS_APP_USER·ATLAS_APP_PASSWORD / 端点是否仍为 {path}") from exc\n'
            '    if not token:\n'
            '        raise RuntimeError(f"[atlas] 应用靶场登录响应无 {_APP_LOGIN[\'token_key\']}（{url}）—— 端点契约可能已变更")\n'
            '    return token\n\n\n'
            'def _app_context_args(args, base_url, app_user, app_password):\n'
            '    """应用靶场的会话预置：未声明 e2e.app_login 或凭据缺 ⇒ 跳过 + 明确警告；齐 ⇒ 真实登录换令牌。"""\n'
            '    if _APP_LOGIN is None:\n'
            '        print("[atlas] 警告：stack-profile 未声明 e2e.app_login（应用靶场登录预置的取证配置），"\n'
            '              "跳过登录态预置；依赖预置登录态的用例会失败", file=sys.stderr, flush=True)\n'
            '        return args\n'
            '    if not (app_user and app_password):\n'
            '        print("[atlas] 警告：应用靶场未设 ATLAS_APP_USER / ATLAS_APP_PASSWORD，"\n'
            '              "跳过登录态预置；依赖预置登录态的用例（先退出再制造未登录前提）会失败",\n'
            '              file=sys.stderr, flush=True)\n'
            '        return args\n'
            '    args["storage_state"] = {"cookies": [], "origins": [{\n'
            '        "origin": base_url.rstrip("/"),\n'
            '        "localStorage": [{"name": _APP_LOGIN["storage_key"],\n'
            '                          "value": _atlas_app_token(base_url, app_user, app_password)}],\n'
            '    }]}\n'
            '    return args\n\n\n'
            'def _context_args(browser_context_args, base_url, app_user=None, app_password=None):\n'
            '    args = dict(browser_context_args)\n'
            '    return _app_context_args(args, base_url, app_user, app_password)\n\n\n'
            '@pytest.fixture(scope="session")\n'
            'def browser_context_args(browser_context_args, base_url):\n'
            '    """契约 §5.4（E1 单段）：以真实登录预置会话。\n\n'
            '    凭据来自运行期环境变量 ATLAS_APP_USER / ATLAS_APP_PASSWORD\n'
            '    （未设 ⇒ 跳过预置并警告；换取失败即中止）。\n'
            '    需要「未登录」前提的用例：块内声明 `auth: none`（⇒ page fixture 剥预置 storageState）；\n'
            '    存量以页内退出控件制造未登录态的写法仍合法（E2E 环契约 §5.7）。\n'
            '    """\n'
            '    return _context_args(browser_context_args, base_url,\n'
            '                         app_user=os.environ.get("ATLAS_APP_USER"),\n'
            '                         app_password=os.environ.get("ATLAS_APP_PASSWORD"))\n\n\n'
            '@pytest.fixture\n'
            'def page(request, browser, browser_context_args):\n'
            '    """覆盖运行器自带的 page：ATLAS_KEEP_OPEN=1 时跑完**不关窗**，留给人手动关。\n\n'
            '    默认（未设该环境变量）行为与原生一致：用例结束即关 context。\n'
            '    持窗模式是为单条跑 + 人工 review 设计（跑整包会同时留下多个窗口）。\n\n'
            '    **为何等在本 fixture 的 teardown 里、而不在 pytest_sessionfinish**：\n'
            '    实测（2026-09-23）session 级 browser fixture 在 sessionfinish **之前**就拆了，\n'
            '    那时 page 已 closed ⇒ 在 sessionfinish 里等信息于空等，进程照样退。\n'
            '    而这里等能用：结果先写哨兵文件，控制台据此判通过/失败，进程再持窗等人手动关。\n'
            '    """\n'
            '    ctx_args = browser_context_args\n'
            '    if request.node.get_closest_marker("atlas_auth_none") is not None:\n'
            '        # 块内 `auth: none`：该用例声明「未登录前提」⇒ 干净 context（剥预置 storage_state）。\n'
            '        # 双键名都剥：Playwright Python API 主键为 snake_case，camelCase 为历史防御。\n'
            '        ctx_args = {k: v for k, v in browser_context_args.items()\n'
            '                    if k not in ("storage_state", "storageState")}\n'
            '    ctx = browser.new_context(**ctx_args)\n'
            '    p = ctx.new_page()\n'
            '    if not _KEEP_OPEN:\n'
            '        yield p\n'
            '        ctx.close()\n'
            '        return\n'
            '    yield p\n'
            '    _write_result(0 if request.node.stash.get(_OUTCOME, False) else 1)\n'
            '    print("ATLAS-HOLD: 用例已结束，浏览器窗口保留；关闭窗口后本进程退出",\n'
            '          file=sys.__stdout__, flush=True)\n'
            '    try:\n'
            '        p.wait_for_event("close", timeout=0)   # timeout=0 = 无限等，等人手动关窗\n'
            '    except Exception:\n'
            '        pass\n\n\n'
            'def pytest_sessionfinish(session, exitstatus):\n'
            '    """非持窗路径（或持窗路径未走到 fixture teardown）时，把结果落哨兵文件。"""\n'
            '    path = os.environ.get("ATLAS_RESULT_FILE")\n'
            '    if path and not os.path.exists(path):\n'
            '        _write_result(exitstatus)\n\n\n'
            "def pytest_configure(config):\n"
            '    # 独立审查 D3（2026-09-30）：注册 auth marker，消除 PytestUnknownMarkWarning 噪声。\n'
            '    config.addinivalue_line(\n'
            '        "markers",\n'
            '        "atlas_auth_none: 块内 auth: none —— 本用例用干净 context（无预置登录态）",\n'
            '    )\n'
            "    # 契约 §7.1：一页一脚本的文件名是 <page>.py，pytest 默认只收 test_*.py。\n"
            "    # 按页面文件名扩 python_files（而不是自建 Module）：pytest 自己按路径去重，\n"
            "    # 显式点名 <page>.py::<test> 时不会把同一条用例收两遍。\n"
            "    # （复审 D3 Major：两个 pytest_configure 会互相遮蔽，必须合并为一个。）\n"
            "    for _name in _PAGE_FILES:\n"
            '        config.addinivalue_line("python_files", _name)\n\n\n'
        )
        write(scripts_dir / "conftest.py", cfg, args.apply, results)
        # 清理已无对应页的零步基线清单（否则会留孤儿数据文件）
        data_dir = scripts_dir / "_data"
        if data_dir.is_dir():
            for stale in sorted(data_dir.glob("zero_step_*.json")):
                if stale.name not in data_files and args.apply:
                    stale.unlink()
    else:
        # node 运行器全机制版（2026-09-30 拉平）：storageState 预置登录（setup 项目）、
        # auth:none 由用例 describe 内 test.use 覆盖（ts_case 渲染）。
        state_rel = ".atlas-auth/state.json"
        cfg = (
            "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py；重跑覆盖。\n"
            "import { defineConfig } from '@playwright/test';\n\n"
            "// 会话预置登录（契约 §5.7 / §5.4）：setup 项目真实登录一次 → state 文件；\n"
            "// 凭据来自运行期环境变量 ATLAS_APP_USER / ATLAS_APP_PASSWORD（不读项目 .env、不硬编码）；\n"
            "// 未设置 ⇒ setup 写空 state 并警告（不静默）；换取失败 ⇒ setup 抛错中止（不静默续跑）。\n"
            "export default defineConfig({\n"
            "  reporter: [['list']],\n"
            "  outputDir: '.atlas-run',\n"
            "  // 契约 rings/e2e §8：执行一次一条（并发 = 1）。零步基线必须先于改态用例，\n"
            "  // 并行调度会乱序 ⇒ 恒真误报 / 前提被前序用例污染。\n"
            "  workers: 1,\n"
            "  fullyParallel: false,\n"
            f"  use: {{ baseURL: process.env.ATLAS_BASE_URL ?? '{base}' }},  // E1 单段\n"
            "  projects: [\n"
            "    { name: 'setup', testMatch: /atlas-auth[.]setup[.]ts/ },\n"
            "    {\n"
            "      name: 'chromium',\n"
            "      dependencies: ['setup'],\n"
            "      use: { storageState: "
            + json.dumps(state_rel) +
            " },\n"
            "    },\n"
            "  ],\n"
            "});\n"
        )
        write(scripts_dir / "playwright.config.ts", cfg, args.apply, results)
        endpoint = app_login["endpoint"] if app_login else "/login"
        user_field = app_login["username_field"] if app_login else "username"
        pass_field = app_login["password_field"] if app_login else "password"
        token_key = app_login["token_key"] if app_login else "access_token"
        storage_key = app_login["storage_key"] if app_login else "access_token"
        setup_ts = (
            "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py；重跑覆盖。\n"
            "import { test, expect } from '@playwright/test';\n"
            "import { mkdirSync, writeFileSync } from 'node:fs';\n"
            "import { dirname } from 'node:path';\n\n"
            "test('atlas auth setup', async ({ request }) => {\n"
            "  const user = process.env.ATLAS_APP_USER;\n"
            "  const password = process.env.ATLAS_APP_PASSWORD;\n"
            f"  const endpoint = {json.dumps(endpoint)};\n"
            f"  const userField = {json.dumps(user_field)};\n"
            f"  const passField = {json.dumps(pass_field)};\n"
            f"  const tokenKey = {json.dumps(token_key)};\n"
            f"  const storageKey = {json.dumps(storage_key)};\n"
            f"  const stateFile = {json.dumps(state_rel)};\n"
            "  if (!user || !password) {\n"
            "    console.warn('[atlas] 警告：未设置 ATLAS_APP_USER/ATLAS_APP_PASSWORD ⇒ 跳过登录预置（需要登录态的用例会失败）');\n"
            "    mkdirSync(dirname(stateFile), { recursive: true });\n"
            "    writeFileSync(stateFile, JSON.stringify({ cookies: [], origins: [] }));\n"
            "    return;\n"
            "  }\n"
            "  const form = new URLSearchParams({ [userField]: user, [passField]: password });\n"
            "  const resp = await request.post(endpoint, {\n"
            "    headers: { 'content-type': 'application/x-www-form-urlencoded' },\n"
            "    data: form.toString(),\n"
            "  });\n"
            "  if (!resp.ok()) {\n"
            "    throw new Error(`[atlas] 应用靶场登录失败（HTTP ${resp.status()}）：核对服务可达 / ATLAS_APP_USER·ATLAS_APP_PASSWORD / 端点 ${endpoint}`);\n"
            "  }\n"
            "  const token = (await resp.json())[tokenKey];\n"
            "  const origin = process.env.ATLAS_BASE_URL ?? " + json.dumps(base) + ";\n"
            "  const state = {\n"
            "    cookies: [] as unknown[],\n"
            "    origins: [{ origin, localStorage: [{ name: storageKey, value: token }] }],\n"
            "  };\n"
            "  mkdirSync(dirname(stateFile), { recursive: true });\n"
            "  writeFileSync(stateFile, JSON.stringify(state));\n"
            "});\n"
        )
        write(scripts_dir / "atlas-auth.setup.ts", setup_ts, args.apply, results)
        gitignore = scripts_dir / ".gitignore"
        if not gitignore.is_file():
            write(gitignore, ".atlas-auth/\n.atlas-run/\n", args.apply, results)

    # 索引的 `## 页面 ↔ 用例` 反向视图：100% 派生 ⇒ 由生成器重写（3509 §B64）。
    idx_path = root / "product" / "e2e" / "e2e-index.md"
    if idx_path.is_file():
        rebuilt = render_reverse_view(idx_path.read_text(encoding="utf-8"), cases)
        if rebuilt is not None:
            write(idx_path, rebuilt, args.apply, results)

    # _support/：永不覆盖（仅缺失时建）。
    support = scripts_dir / "_support"
    if not support.exists():
        support.mkdir(parents=True, exist_ok=True)
        seed = support / ("__init__.py" if runner == "python-playwright" else "hooks.ts")
        seed.write_text(
            "# 自定义深断言钩子放这里（生成器不覆盖本目录）。\n"
            "# python: 定义 deep_assert(case_id, page)\n"
            if runner == "python-playwright"
            else "// 自定义深断言钩子放这里（生成器不覆盖本目录）。\n"
        , encoding="utf-8")

    out = {"root": str(root), "runner": runner, "base_url": base,
           "apply": args.apply, "generated": generated, "results": results,
           "review_gate": {"ok": gate_ok, "reasons": gate_reasons}}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"gen_e2e_scripts @ {root}  runner={runner} base_url={base}")
        for r in results:
            print(f"  {'~' if r['changed'] else '='} {r['file']}")
        print(f"生成 {generated} 个页面脚本{'（dry-run，加 --apply 写盘）' if not args.apply else ''}")
        if gate_ok:
            print("独立审查门：ok")
        else:
            print("独立审查门：未通过（dry-run 不阻断；--apply 会拒绝写盘）")
            for r in gate_reasons:
                print(f"  - {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
