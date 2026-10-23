#!/usr/bin/env python3
"""atlas E2E —— 从用例分片生成可执行脚本（操作 + 断言）。

按 `rings/e2e/reference.md` §7（决策 D50/D67/D68；2026-09-23 由「testid 冒烟骨架」
改为「操作脚本」）：
  * 读 `product/e2e/cases/<page>.md` 的 `atlas-case` 块，**一页一脚本**；
  * 生成**可运行的操件脚本**：每条用例一个测试——`goto(<页面 URL>)` → 按 `step`
    **逐行执行动作**（动词表见契约 §5.5；含 click / fill / type / press 等）→ 按
    `expected` **逐行执行断言**（text / contains / count / visible / hidden /
    enabled / disabled / value）；`#` 之后的中文说明作为注释保留；
  * **动词解析失败即中止**：`step` / `expected` 出现词表外的动词 → 报错并列出违规行，
    不得静默跳过或降级为注释；
  * `testid:` 数组作为**元素齐全守卫**：每用例运行前按**自动等待**断言其列出的 testid 全部
    存在（运行器原生轮询断言）——真实应用是 SPA，`goto` 后元素异步渲染，即时存在性判定
    必红；真缺失时超时失败并点名缺失清单（不得退化成永久等待）；
  * **复杂逻辑放 `_support/`**（断言之外的计算、等待、多步组合；**不被覆盖**），
    生成脚本在存在时挂载调用 `hooks.deep_assert(<ID>, page)`；
  * 地址**不硬编码**：由运行器原生配置承载 `baseURL`，值 = `e2e.app_base_url`（E1 单段：
    唯一靶场 = 真实应用；为空 ⇒ 报错索取，不猜默认）；
  * 运行器 = `node-playwright` 单轨（2026-10-09 `3507 BO` 单轨化，原 `§B201-4`；`python-playwright` 已退役——声明即拒）；
  * **派生、可重生成**：重跑覆盖同页脚本与运行器配置；`_support/` 永不覆盖。
  * **`atlas-hold.ts`（§10.1，2026-10-12 控制台 node 轨迁移批）**：页面脚本经它引入
    `test` / `expect`——承载控制台「跑完留窗（ATLAS_KEEP_OPEN）+ 结果哨兵
    （ATLAS_RESULT_FILE）」；环境变量未设时行为与 `@playwright/test` 原生一致。
    py 时代等价物 = conftest.py（已随单轨化退役）。
  * **登录形态与预置（RFC-20261015-02，issue #11；2026-10-16）**：形态声明在 `e2e.app_login.mode`
    —— `real`（缺省 = 真实登录：OAuth2 表单 → 令牌 → 写进运行器 storageState）、
    `fabricated`（§5.8：纯前端桩不发请求直写假令牌，必填收窄 `storage_key`）、
    **`none`（靶场无访问门：不生成登录预置设施，也不打警告 —— 声明过的形态，不是降级）**。
    取证值（端点 / 表单字段名 / 令牌键 / 存储键）登记在段内；`mode: none` 下五个取证字段
    一律不得残留（含 `storage_key` —— 无门项目的存储键没有消费方，与 fabricated 的
    「收窄」相反是「全弃」）；段存在而字段不齐 ⇒ 生成报错。
    凭据只来自运行期环境变量 `ATLAS_APP_USER` / `ATLAS_APP_PASSWORD`（不读项目 `.env`、不硬编码）；
    未设置 ⇒ 跳过预置 + 明确警告；换取令牌失败 ⇒ 报错中止
    （不得静默续跑——那会退化成「未登录态跑用例」的假绿）。
    **段缺失 = 未声明（不再是「合法降级」）**：`validate_stack_profile` 已 WARN 指名；
    生成器升档点 = 下一次真跑准备日（见 `shared/gates.md`「E2E 真跑」行——届时改推
    `not_ready`：退出码 3 + 机读 `not_ready: "app_login"`）。
  * **网络边界打桩**（契约 §5.8，2026-10-12）：`mock:` 行（用例级）在 `e2e.mock.mode: on`
    时编译为**单条** `context.route` 派发表（pathname+method 命中、query 免疫；前缀内未命中
    fail-loud abort + 用例末审计断言点名；OPTIONS 自动 204 + CORS 头）；fixture 内容**生成期
    读入内联**（生成物 = 确定性派生物）；命中记 `atlas-mock` 注记 + `[atlas-mock]` 日志。
    **mode 未开而分片有 `mock:` 行 ⇒ 报错中止**（防全后端项目静默屏蔽真 API 回归）；
    未启用项目的生成物**零变化**（新 helper 只出现在 mock 页脚本头部）。

纯标准库；无任何框架名（运行器名只作为 `e2e.runner` 的值出现）。

用法：
    python3 gen_e2e_scripts.py --root <项目根> [--apply] [--json]

退出码（`3509 §B110`）：**0** 正常 · **2** 真错（缺 profile / 动词越界 / 审查门不过…） ·
**3** 前置未声明 —— **3 不是失败**：调用方应判「未就绪」而不是「生成失败」，
且 `--json` 下 stdout 给出 `{"ok": false, "not_ready": <键>, …}`。
当阶段键 = `app_base_url`（地址未声明）；`app_login` 未声明按 RFC-20261015-02 于
下一次真跑准备日并入同一通道（机读键 `"app_login"`，升档记录见 `shared/gates.md`「E2E 真跑」行）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# 随包内核引导（`_support/`，2026-10-12 单源批）：解析 / 加载口径一律经共享内核，
# 本文件不再自持副本（此前 parse_profile 三份 / spec 加载五处，见 `_support/stack_profile.py` 头注）。
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.siblings import load_module  # noqa: E402

_sp = load_module("stack_profile")
parse_profile = _sp.parse_profile  # 单源别名（原实现已并入 `_support/stack_profile.py`）
# 契约 §5.5（2026-10-16，issue #R1/#F5）：行内注释剥除口径与内核**同一函数对象**（I3）。
strip_inline_comment = _sp.strip_inline_comment
# 宿主注入型 base query 的转发（issue #27 / D104）：单源 `_support/url_merge.py`。
url_merge = load_module("url_merge")

CASE_BLOCK = re.compile(r"```atlas-case\s*\n(.*?)```", re.S)
RUNNERS = {"node-playwright": ".spec.ts"}  # 单轨（3507 BO）：python-playwright 已退役
# 前置未声明（例：`e2e.app_base_url` 为空）的**独立退出码**（`3509 §B110`）：
# 与真错（2）分开 ⇒ 调用方（`atlas_check`）判 **SKIP（未就绪）** 而不是 FAIL。
# 同一根因曾被判成两种结论（`E2E 真跑`=SKIP、`生成物最新`=FAIL）⇒ 永久红门 = 静音门（`§106`）。
NOT_READY = 3
# e2e.app_login 段的必填字段（mode: real 须全齐；fabricated 收窄为 storage_key；3509 §B101）
APP_LOGIN_FIELDS = ("endpoint", "username_field", "password_field", "token_key", "storage_key")
# e2e.app_login.mode（契约 §5.8/§7.1，2026-10-12；2026-10-16 增 none，RFC-20261015-02）：
# real（缺省 = 真实登录语义）/ fabricated（纯前端桩项目：setup 直写假令牌，必填收窄为 storage_key）/
# none（靶场无访问门：不生成登录预置设施、不打警告 —— 声明过的形态，不是降级）。
# 与既有词表同族（e2e.mock.mode off / e2e.review.mode off：在 X 段里用 mode 值声明「X 通道不需要」）。
APP_LOGIN_MODES = ("real", "fabricated", "none")
# 网络边界打桩（契约 §5.8，2026-10-12）：`mock:` 行的方法枚举（行式语法见 parse_mock_line）。
MOCK_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# 分片 step / expected 的动词词表（契约 `rings/e2e/reference.md` §5.5，2026-09-23 定）
ACTION_VERBS = ("click", "fill", "select", "check", "uncheck", "press", "type", "hover", "refresh", "goto", "waitFor", "download", "upload", "dispatch")
ASSERT_VERBS = ("text", "contains", "count", "countOptions", "visible", "hidden", "enabled", "disabled", "checked", "unchecked", "value", "attr", "delta")
NO_TESTID_VERBS = ("refresh", "goto")  # 这两个动词第二个 token 不是 testid（goto 的值是路径）
# 契约 §5.5（2026-10-16 补，issue #R4）：`click` / `hover` 默认追加 `{ force: true }`
# （动机：真实 UI 里悬浮遮罩 / 动画 / 父容器事件拦截会造出动作执行超时的**假红**）。
# **步级开关** `native` = 按运行器原生语义执行（不追加 `force`）；**值域封闭** = 仅 `native`
# 或省略，其它取值 ⇒ 报错中止（校验器邻位同步 FAIL，两条机器面双保险）。
FORCE_SWITCH = "native"
FORCE_SWITCH_VERBS = ("click", "hover")


def step_force_arg(verb: str, value: str, line: str, cid: str) -> str:
    """`click` / `hover` 的 `force` 参数串：缺省 `" { force: true }"`；`native` ⇒ `""`。

    契约 §5.5（2026-10-16，issue #R4）：第三位非 `native` 且非空 ⇒ 报错中止（镜像 `auth` /
    `download` 的「词表外取值即中止」纪律，不静默降级）。**适用边界**：被测属性本身是
    「可操作性 / 不可交互 / 用户不可达」的用例必须用 `native` —— `force` 会跳过
    *receives events / stable* 检查，使该属性**无法被证伪**。
    """
    v = value.strip()
    if v == FORCE_SWITCH:
        return ""
    if v:
        raise ValueError(
            f"{cid}: `{verb}` 第三位只允许 `{FORCE_SWITCH}` 或省略，得 {v!r}"
            f"：{line!r}（契约 §5.5）")
    return " { force: true }"

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

    机器只看注释之前；注释之后是给人读的中文说明。

    **剥注释口径 = 内核单源**（`_support/stack_profile.strip_inline_comment`，2026-10-17，issue #27 /
    `DESIGN.md` D104 ⑦）：此前用 `line.partition("#")`（**任何** `#` 都截断，D94 ② 对列表项的旧例外），
    而 `/console/#/app/agent/detail/1` 这类**路径形态含 hash** 的值会被砍成 `/console/`
    —— 现场：百炼/v2前端重生成后 step 的 `goto` 丢了 hash 段（守卫/基线正常，只有列表项受害）。
    改成内核口径后：`#` 前有空白/行首才算注释起点（且引号内不算），路径里的 `#` 原样保留。
    """
    code = strip_inline_comment(line)                      # 单源（D94 口径）
    note = (line[len(code):].lstrip(" \t#").strip()       # 注释正文（无注释 ⇒ 空）
            if code != line.rstrip() else "")
    parts = code.strip().split(None, 2)
    verb = parts[0] if parts else ""
    if verb in NO_TESTID_VERBS:
        return verb, "", (parts[1] if len(parts) > 1 else ""), note.strip()
    return verb, (parts[1] if len(parts) > 1 else ""), (parts[2] if len(parts) > 2 else ""), note.strip()


def parse_tid_nth(raw_tid: str) -> tuple[str, int | None]:
    """把 `<tid>[<N>]` 拆成 (base_tid, index)。无下标返回 (raw_tid, None)。（D120 / issue #31）"""
    m = re.match(r"^([a-z0-9-]+)\[(\d+)\]$", raw_tid)
    if m:
        return m.group(1), int(m.group(2))
    return raw_tid, None


def tid_locator(raw_tid: str) -> str:
    """返回定位器表达式：带下标发射 `.nth(N)`，不带下标发射 `.first()`（向后兼容）。"""
    base, idx = parse_tid_nth(raw_tid)
    if idx is not None:
        return f"page.getByTestId('{base}').nth({idx})"
    return f"page.getByTestId('{base}').first()"


# `strip_inline_comment` / `yaml_scalar` / `parse_profile` 已并入随包内核
# `_support/stack_profile.py`（2026-10-12 单源批）；别名 `parse_profile` 见文件头部。
# 其余消费者（validators/*）经 `_support.siblings.load_module(...)` 取用。
# `parse_block` 同批并入 `_support/case_block.py`（原与 validate_e2e_index 逐字节双拷贝）。
parse_block = load_module("case_block").parse_block


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


MOCK_FIXTURE_RE = r"fixtures/[\w./-]+\.json"


def parse_mock_line(line: str, api_prefix: str | None = None) -> dict:
    """`<METHOD> <path> -> <rhs>` → 桩表条目（契约 §5.8 的 `mock:` 行式语法）。

    rhs 为**封闭文法**（越界即 ValueError，不得静默降级）：
      `fixtures/<…>.json`                        单发（缺省 200）
      `status <N> fixtures/<…>.json`             单发带状态码
      `delay <N>ms fixtures/<…>.json`            延迟应答（1–5000ms；慢动作下 loading 态可见）
      `seq [N:]fixtures/…[, [N:]fixtures/…]`     按调用次序出队（队空运行期 fail-loud）
    `api_prefix` 非空时校验路径锚定（拦越界桩 / 误伤静态资源，契约锚定门）。
    """
    code = strip_inline_comment(line)   # 单源（D94 ③ 残余清偿，2026-10-17；任何 `#` 都截断是旧口径）
    left, arrow, rhs = code.partition("->")
    if not arrow:
        toks = code.strip().split(None, 2)
        if len(toks) == 3 and toks[0].upper() in MOCK_METHODS:
            left, rhs = f"{toks[0]} {toks[1]}", toks[2]
        else:
            raise ValueError(f"mock 行缺 `->`：{line!r}（契约 §5.8）")
    toks = left.strip().split()
    if len(toks) != 2:
        raise ValueError(f"mock 行左段应为 `<METHOD> <path>`：{line!r}（契约 §5.8）")
    method, path = toks[0].upper(), toks[1]
    if method not in MOCK_METHODS:
        raise ValueError(f"mock 方法 {toks[0]!r} 不在 {MOCK_METHODS} 内（契约 §5.8）")
    is_external = path.startswith("http://") or path.startswith("https://")
    if not is_external:
        if not path.startswith("/"):
            raise ValueError(f"mock 路径须以 / 开头或为全量外部 URL（以 http://、https:// 开头）：{path!r}（契约 §5.8）")
        if api_prefix is not None and not path.startswith(api_prefix):
            raise ValueError(f"mock 路径 {path!r} 不在 api_prefix {api_prefix!r} 内（锚定门，契约 §5.8）")
    r = rhs.strip()
    m = re.fullmatch(MOCK_FIXTURE_RE, r)
    if m:
        return {"method": method, "path": path, "status": 200, "delay_ms": 0, "seq": None, "ref": r}
    m = re.fullmatch(rf"status (\d{{3}}) ({MOCK_FIXTURE_RE})", r)
    if m:
        return {"method": method, "path": path, "status": int(m.group(1)), "delay_ms": 0,
                "seq": None, "ref": m.group(2)}
    m = re.fullmatch(rf"delay (\d{{1,4}})ms ({MOCK_FIXTURE_RE})", r)
    if m:
        n = int(m.group(1))
        if not 1 <= n <= 5000:
            raise ValueError(f"delay 须在 1–5000ms：{line!r}（契约 §5.8）")
        return {"method": method, "path": path, "status": 200, "delay_ms": n, "seq": None,
                "ref": m.group(2)}
    m = re.fullmatch(r"seq (.+)", r)
    if m:
        seq: list[dict] = []
        for item in m.group(1).split(","):
            sm = re.fullmatch(rf"(?:(\d{{3}}):)?({MOCK_FIXTURE_RE})", item.strip())
            if not sm:
                raise ValueError(f"seq 项非法 {item.strip()!r}（应 `[N:]fixtures/….json`，契约 §5.8）")
            seq.append({"status": int(sm.group(1) or 200), "ref": sm.group(2)})
        if not seq:
            raise ValueError(f"seq 至少一项：{line!r}（契约 §5.8）")
        return {"method": method, "path": path, "status": 200, "delay_ms": 0, "seq": seq, "ref": None}
    raise ValueError(f"mock 行右段语法不识：{r!r}（契约 §5.8）")


def compile_mock_entries(case: dict, api_prefix: str, e2e_root: Path, fixtures_root: Path | None = None) -> list[dict] | None:
    """把用例的 `mock:` 行编译为派发表条目（fixture 内容生成期内联；契约 §5.8）。

    内联而非运行期读盘：生成物 = **确定性派生物**，`atlas_check` 的「生成物最新」门
    看守 stale 内联（fixture 改了没重生成 ⇒ 门红），且运行期零路径解析（免 cwd / ESM 坑）。
    """
    lines = case.get("mock") or []
    if not lines:
        return None

    f_root = fixtures_root or (e2e_root / "fixtures")

    def body_of(ref: str) -> str:
        if ref.startswith("fixtures/"):
            rel = ref[len("fixtures/"):]
            p = f_root / rel
            if not p.is_file() and (e2e_root / ref).is_file():
                p = e2e_root / ref
        else:
            p = f_root / ref
        if not p.is_file():
            raise ValueError(f"fixture 不存在：{ref}（{case.get('id')} 的 mock 行；契约 §5.8）")
        return p.read_text(encoding="utf-8")

    out: list[dict] = []
    for line in lines:
        e = parse_mock_line(line, api_prefix)
        if e["seq"] is not None:
            for item in e["seq"]:
                item["body"] = body_of(item["ref"])
        else:
            e["body"] = body_of(e["ref"])
        out.append(e)
    return out


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


def session_env_name(key: str) -> str:
    """会话键 → 运行期覆盖用的环境变量名（`ATLAS_SESSION_<规范化键>`）。

    契约 §5.5（2026-10-16，issue #13）：取值优先级 = **运行期环境变量 > 用例声明值**；
    两者皆空 ⇒ 报错中止（不静默跑成默认态 = 假绿）。同 `app_login` 的凭据纪律：敏感值只经环境进入。
    """
    return "ATLAS_SESSION_" + re.sub(r"[^0-9A-Za-z]+", "_", key).strip("_").upper()


def ts_case(case: dict, url: str, base: str = "", esm: bool = False) -> str:
    cid = case["id"]
    # 契约 §5.5 `守卫:`（2026-10-16，issue #23）：**元素齐全守卫导航用的具体路径**。
    # 页面表 `路由` 列按 §3.1 只承载**业务段**（带参页面形如 `/x` 而真实路由为 `/x/:id`）⇒
    # 直接拿它导航会落到路由匹配不上的地址，守卫在 goto 后即红。有 `守卫:` 时用它，
    # 缺省回落页面表路由 ⇒ **对无参页面逐字节零变化**。
    # 宿主注入型 base query（issue #27 / D104）：守卫导航同样要带（`url` 已在调用侧合并，幂等）。
    # 契约 §5.5 `参数:`（2026-10-18，`DESIGN.md` D109）：用例声明的宿主注入 **URL 参数**
    # （值内联在首个带参 `goto` 里）——守卫导航取**同一来源**（`_inject_query`），否则守卫读的
    # 是**无前提的 DOM**：参数决定「哪些元素在场」的页面上，守卫会在 goto 后即红。
    _guard_target = (case.get("守卫") or "").strip() or url
    _inject_q = case.get("_inject_query") or ""
    if _inject_q:
        # `url` 在调用侧已并入 base query（幂等）；`守卫:` 是未合并的具体路径 —— 两者都按
        # 「追加到自身 query」处理（插在 hash 之前），随后的一次 merge 会把 base 去重并上来。
        _guard_target = url_merge.append_query(_guard_target, _inject_q)
    _inject_hq = case.get("_inject_hash_query") or ""
    if _inject_hq:
        # `hash参数:` 是 HashRouter 的 `#` 后查询前提；守卫导航必须带同一段，否则守卫读的是
        # 无前提的 DOM（快照页会停在「缺少快照标识」错误态）。没有 hash 路由 ⇒ 响亮失败。
        if "#" not in _guard_target:
            raise ValueError(f"{cid}: `hash参数:` 需要守卫/页面路由含 hash 段")
        _guard_target = url_merge.append_hash_query(_guard_target, _inject_hq)
    guard_url = url_merge.merge_base_query(_guard_target, base)
    # 契约 §5.5 / §7.1（"元素齐全守卫按自动等待判定"）：守卫 id 面 = **该用例 `testid:` 应然清单**
    # （实测：首步为 `goto`/`refresh` 的用例取 `step[0]` 会得到**空表** ⇒ 守卫静默消失）。
    # 2026-10-16（issue #R2）从 `first_step_tids`（猜）**回归**契约正文口径；空表本身是
    # 真信号（应然清单未声明 / 动态元素未打占位槽），由实现侧按 `reference.md` §4 的
    # 「hidden 占位槽」机制满足，不得以空表吸收。
    # 契约 §5.5（2026-10-16，R1 同类的守卫面侧）：`testid:` **项**与 `step:` 项同形，同样可带
    # 行内 `#` 说明 —— 逐项经同一 `strip_inline_comment`（与零步基线侧 `case_testids` 同口径）。
    # 不剥则守卫面发射带注释的 id（如 `["foo   # 行内说明"]`）⇒ `toHaveCount(1)` 恒不命中 ⇒ 假红。
    declared = [strip_inline_comment(t).strip() for t in (case.get("testid") or [])]
    ids = json.dumps(declared, ensure_ascii=False)
    # 契约 §5.5 / §7.1（DESIGN D114，2026-10-19，issue #26；同日**修正**）：元素齐全守卫 = **单段页面就绪锚点** ——
    #   ① 声明的 id 里「任意一个」在场 ⇒ 页面已渲染（`expect.poll` 原生轮询；一个都没出现 ⇒ 超时并点名
    #      整份清单，不静默）；守卫面**不会退化成空表**（锚点始终发射且带全量清单，回应 #R2 对空表的裁决）。
    #   ② 声明的其余 id **不在 goto 时刻要求运行时在场**：被 step 触达的由该 step 的原生自动等待承接，
    #      被 expected 触达的由断言的自动轮询承接（§5.5 §B99 语义不变）；**声明了却未被触达**的 id 只参与
    #      **静态双向集合校验**（它们往往正是为了满足该静态门而被声明的，见下修正理由）。
    #   ③ 动作产物元素初始态必然为 0：任何「用例开始时 count=1」都只能靠实现侧 hidden 占位槽凑，
    #      那是把测试义务搬进产品 DOM（D114 被否项）——故占位槽不再是必需形态。
    # **为何删掉「纯在场声明」段**（同日修正，现场证据）：静态双向集合门要求「源码里的每个实然 testid
    # 必须被某条用例的 `testid:` 声明」，于是「声明但不操作/不断言」是**唯一合法形态**；若又在 goto 时刻
    # 要求它运行时在场，就把「静态门的补全需求」误当成了「初始态断言」——现场两条合法用例因此死锁
    # （面板未打开时该元素必然为 0，Expected 1 / Received 0）。
    guard_block = f"  await atlasAwaitAnyDeclared(page, {ids}, ATLAS_WAIT_TIMEOUT_MS);\n"
    step_note = "\\n".join("//   - " + s for s in case.get("step", []))
    assert_note = "\\n".join("//   - " + s for s in case.get("expected", []))    # 契约 §5.7（2026-09-30）：blocked/skipped ⇒ test.skip（状态真相源 = 索引）。
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
            # refresh 落盘节拍参数化（先等后刷；对齐 F11 `ATLAS_SLOWMO` 注入先例）：启用**节流型
            # 自动保存**的项目（现场：距上次成功保存 <15s 则延迟落库）refresh 前不等待 ⇒ 编辑
            # 内容用例必然丢。具体毫秒数是项目侧运行时前提，不写死进生成器（业务常数出项目）；
            # 默认 0 ⇒ 生成物行为与既有契约一致。
            actions.append('await page.waitForTimeout(Number(process.env.ATLAS_REFRESH_SETTLE || "0"));')
            actions.append("await page.reload();")
        elif verb == "goto":
            # 宿主注入型 base query（issue #27 / D104）：step 的 goto 是**第二处**发射面。
            actions.append(f"await page.goto('{url_merge.merge_base_query(value, base)}');")
        elif verb == "click":
            actions.append(
                f"await {tid_locator(tid)}.click("
                f"{step_force_arg(verb, value, s, cid).strip()});")
        elif verb == "fill":
            actions.append(f"await {tid_locator(tid)}.fill({json.dumps(value, ensure_ascii=False)});")
        elif verb == "select":
            # 契约 §5.5（B173-1）：发射实现无关 helper，不再钉死原生 `<select>` ——
            # 语义 = 「选中 label 的那一项」，DOM 机制由 helper 按元素自适应。
            base_tid, idx = parse_tid_nth(tid)
            idx_arg = f", {idx}" if idx is not None else ""
            actions.append(f"await atlasSelect(page, '{base_tid}', {json.dumps(value, ensure_ascii=False)}{idx_arg});")
        elif verb == "check":
            actions.append(f"await {tid_locator(tid)}.check();")
        elif verb == "uncheck":
            actions.append(f"await {tid_locator(tid)}.uncheck();")
        elif verb == "press":
            actions.append(f"await {tid_locator(tid)}.press({json.dumps(value)});")
        elif verb == "type":
            # 契约 §5.5（D134，2026-10-23）：逐字键入 —— 触发 keydown/keypress/input 的真实
            # 按键链，供带掩码 / 受控输入的控件使用（`fill` 一次性写 DOM 不触发组件内部解析，
            # 如 Ant Design RangePicker 的日期输入）。**不先清空原值**；替换语义用 `fill`。
            if not value.strip():
                raise ValueError(
                    f"{cid}: `type` 需要输入文本，得空值：{s!r}（契约 §5.5）")
            actions.append(
                f"await {tid_locator(tid)}.pressSequentially({json.dumps(value, ensure_ascii=False)});")
        elif verb == "hover":
            actions.append(
                f"await {tid_locator(tid)}.hover("
                f"{step_force_arg(verb, value, s, cid).strip()});")
        elif verb == "dispatch":
            # 契约 §5.5（2026-10-17，v3 现场实证）：React 合成事件直发——`dispatchEvent('click')`
            # 绕过 hit-testing / 可点性检查的**整面**。动机（三跑/四跑实证）：该表面常态遮罩下
            # `native` 永远等不到「receives events」⇒ 整用例挂死；`force` 在动画窗口内被吞
            # （5s 轮询不动）。dispatch 不追加 force（它本就绕行，无此概念）——但被测属性是
            # 「可操作性 / 不可交互」的用例**不得用 dispatch**（同 native 适用边界）。
            if value.strip():
                raise ValueError(
                    f"{cid}: `dispatch` 只接受 `<testid>` 一个参数，得 {value.strip()!r}"
                    f"：{s!r}（契约 §5.5 值域封闭）")
            actions.append(f"await {tid_locator(tid)}.dispatchEvent('click');")
        elif verb == "waitFor":
            # 契约 §7.1：带轮询的断言（不得退化为固定等待）
            loc = tid_locator(tid)
            if value == "":
                actions.append(f"await expect({loc}).toBeVisible({{ timeout: ATLAS_WAIT_TIMEOUT_MS }});")
            else:
                actions.append(
                    f"await expect({loc}).toHaveText({json.dumps(value, ensure_ascii=False)}, "
                    "{ timeout: ATLAS_WAIT_TIMEOUT_MS, useInnerText: true });"
                )
        elif verb == "download":
            # 契约 §5.5（契约 §5.5）：先注册监听、再点击、再校验建议文件名（glob）。
            if not value.strip():
                raise ValueError(f"`download` 需要文件名 glob 参数: {s!r}（契约 §5.5）")
            base_tid, idx = parse_tid_nth(tid)
            idx_arg = f", {idx}" if idx is not None else ""
            actions.append(
                f"await atlasDownload(page, '{base_tid}', {json.dumps(value, ensure_ascii=False)}{idx_arg});"
            )
        elif verb == "upload":
            # 契约 §5.5（B201-1，2026-10-12）：`upload <testid> <值>`，值 = 相对
            # `product/e2e/fixtures/` 的文件路径（与 §5.8 mock 同一 fixtures 树；v1 单文件）。
            # 路径按**脚本文件位置**解析（spec 位于 <e2e>/scripts/，'..' → <e2e>）——
            # 两个真实载体 cwd 不同（控制台从 scripts 跑 / atlas_check 从项目根跑），
            # 不得内联构建机绝对路径、不得依赖进程 cwd。缺值 ⇒ 中止（镜像 download）；
            # fixture 存在性由 main() 的生成期检查把关（exit 2 列明）。
            rel = value.strip()
            if not rel:
                raise ValueError(f"`upload` 需要 fixtures 相对路径参数: {s!r}（契约 §5.5）")
            # D123（2026-10-20）：package.json `type: module` 的项目里生成物按 ESM 执行，
            # `__dirname` 不存在 ⇒ 按脚本文件位置解析需改用 import.meta.url；CJS 项目保持原形态。
            path_expr = (
                f"fileURLToPath(new URL('../fixtures/{rel}', import.meta.url))" if esm
                else f"resolve(__dirname, '..', 'fixtures', {json.dumps(rel, ensure_ascii=False)})"
            )
            actions.append(
                f"await {tid_locator(tid)}.setInputFiles({path_expr});"
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
            line = f"await expect({tid_locator(tid)}).toHaveText({v});"
        elif verb == "contains":
            base_tid, idx = parse_tid_nth(tid)
            nth_str = f".nth({idx})" if idx is not None else ".first()"
            line = f"await expect(page.getByTestId('{base_tid}').filter({{ hasText: {v} }}){nth_str}).toBeVisible();"
        elif verb == "count":
            base_tid, _ = parse_tid_nth(tid)
            line = f"await expect(page.getByTestId('{base_tid}')).toHaveCount(Number({v}));"
        elif verb == "visible":
            line = f"await expect({tid_locator(tid)}).toBeVisible();"
        elif verb == "hidden":
            line = f"await expect({tid_locator(tid)}).toBeHidden();"
        elif verb == "enabled":
            line = f"await expect({tid_locator(tid)}).toBeEnabled();"
        elif verb == "disabled":
            line = f"await expect({tid_locator(tid)}).toBeDisabled();"
        elif verb == "value":
            # 契约 §5.5（契约 §5.5）：值写作 `""` / `(空)` 时是**空串**，
            # 必须渲染成空串实参 —— 直接 json.dumps 会得到两个字面引号字符，
            # 与真实空串永不相等。（B173-1：断言经 atlasExpectValue 实现无关化。）
            if value.strip() in ('""', "(空)"):
                v = json.dumps("", ensure_ascii=False)
            base_tid, idx = parse_tid_nth(tid)
            idx_arg = f", {idx}" if idx is not None else ""
            line = f"await atlasExpectValue(page, '{base_tid}', {v}{idx_arg});"
        elif verb == "countOptions":
            # 契约 §5.5（契约 §5.5）：数该元素内的 `option` 子元素个数。
            line = f"await expect({tid_locator(tid)}.locator('option')).toHaveCount(Number({v}));"
        elif verb == "checked":
            line = f"await expect({tid_locator(tid)}).toBeChecked();"
        elif verb == "unchecked":
            line = f"await expect({tid_locator(tid)}).not.toBeChecked();"
        elif verb == "attr":
            # 契约 §5.5（契约 §5.5）：`attr <testid> <name> <value>`。
            aname, _, aval = value.strip().partition(" ")
            aval = aval.strip()
            if not aname or not aval:
                raise ValueError(f"`attr` 需要 `<name> <value>` 两个参数: {raw!r}（契约 §5.5）")
            if aval in ('""', "(空)"):
                # 契约 §5.5（2026-10-19 补，`DESIGN.md` D116）：`""` / `(空)` ⇒「该属性**缺席或为空串**」。
                # 为何不用 `toHaveAttribute(name, "")`：**实测**缺席时 `getAttribute` 得 `null`，
                # 该调用判 FAIL（半通状态）；`?? ''` 归一 + 轮询才是全档语义，且与探针表达式同形（单源）。
                line = (
                    f"await expect.poll(async () => (await {tid_locator(tid)}"
                    f".getAttribute({json.dumps(aname, ensure_ascii=False)})) ?? '').toBe('');"
                )
            else:
                line = (
                    f"await expect({tid_locator(tid)}).toHaveAttribute("
                    f"{json.dumps(aname, ensure_ascii=False)}, {json.dumps(aval, ensure_ascii=False)});"
                )
        elif verb == "delta":
            # 契约 §5.5（P5，2026-10-07）：`delta <tid> <±N>` 相对断言 —— 行动前采样
            # （贴第一个提交性动作）、行动后 `expect.poll` 轮询复读
            # （SPA 竞态安全），差值必须恰为 ±N。与豁免通道 / 步骤锚叠写 ⇒ 生成期中止
            # （校验器同判 FAIL，双保险）。
            if kind is not None or split_after(raw)[0] is not None:
                raise ValueError(f"`delta` 不得与 initial:/unchanged:/after: 叠写: {raw!r}（契约 §5.5）")
            if not re.fullmatch(r"[+-]\d+", value.strip()):
                raise ValueError(f"`delta` 值须为带符号整数 ±N: {raw!r}（契约 §5.5）")
            if not case.get("step"):
                raise ValueError(f"{cid}: delta 相对断言需要至少一条 step（行动前采样点不存在）")
            var = "__delta_" + re.sub(r"[^0-9a-zA-Z]", "_", tid)
            delta_pre.append(f"const {var} = await atlasIntOf({tid_locator(tid)});")
            line = (
                f"await expect.poll(() => atlasIntOf({tid_locator(tid)}), "
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
    # 组装顺序：（每条 step + 它身后的锚断言）→ 终态断言；行动前断言（unchanged pre +
    # delta 采样）贴**第一个提交性动作**（§5.6 R9 / §B55——放所有 step 之前会把准备步骤
    # 未执行时的不可见元素误判成自相矛盾）；无提交性动作时退回第一个 step 之前
    # （校验器对此 FAIL，此处保持保守位置）。`actions` 与 `step` 一一对应，按序号对位。
    delta_pos = next((i for i, s in enumerate(case.get("step", []), start=1)
                      if any(w in strip_inline_comment(s) for w in SUBMITTING_WORDS)), 1)
    seq: list[str] = [] if actions else list(pre)
    for _i, _act in enumerate(actions, start=1):
        if _i == delta_pos:
            seq.extend(delta_pre)
            seq.extend(pre)
        seq.append(_act)
        seq.extend(anchors.get(_i, []))
    seq.extend(terminal)
    # 契约 §5.8（2026-10-12）：mock 用例在全部断言后跑打桩审计——未桩请求 / seq 队列耗尽
    # 在此响亮失败（fail-loud），并把桩命中清单记入测试注记（证据披露）。
    if case.get("_mock") is not None:
        seq.append("await atlasMockAudit(__mock);")
    indented = "\n".join("  " + b for b in seq)
    # 派发表注册必须先于 goto（拦截不漏首屏请求的时序前提，契约 §5.8）。
    mock_open = ""
    if case.get("_mock") is not None:
        mock_open = ("  const __mock = await atlasMockTable(page, "
                     + json.dumps(case["_mock"], ensure_ascii=False) + ");\n")
    # 契约 §5.5 `会话:`（2026-10-16，issue #13）：**前提构造**——写进 sessionStorage 的
    # addInitScript 必须在首屏 `page.goto` **之前**注册（addInitScript 只对未来导航生效）。
    # 本调用也必须在元素齐全守卫之前（守卫读的就是该会话态下的 DOM）。
    session_open = ""
    if case.get("_session"):
        session_open = ("  await atlasSessionPreset(page, "
                        + json.dumps(case["_session"], ensure_ascii=False) + ");\n")
    body = (
        f"test({json.dumps(cid + ' ' + (case.get('_title') or ''), ensure_ascii=False)}, async ({{ page }}) => {{\n"
        f"  {step_note}\n  {assert_note}\n"
        f"{mock_open}"
        f"{session_open}"
        f"  await page.goto('{guard_url}');\n"
        f"{guard_block}"
        f"{indented}\n}});\n"
    )
    if wrap_open:
        indented_body = "\n".join("  " + ln for ln in body.rstrip("\n").splitlines())
        return wrap_open + indented_body + "\n" + wrap_close
    return body


def ts_assert_expr(line: str) -> str:
    """把一行断言渲染成 **awaitable 布尔表达式串**（`ts_assert` / 零步基线 runner 共用）。

    用例断言与零步基线**共用**本函数 —— 两条路径的断言语义因此不可能漂（复用而非复制）。
    表达式求值环境 = 页面文件 header 的 `tsVis` / `tsVisible` / `page`。
    """
    _, line = split_prefix(line)
    verb, tid, value, _note = parse_line(line)
    base_tid, idx = parse_tid_nth(tid)
    nth_idx = idx if idx is not None else 0
    nth_locator = f"page.getByTestId({json.dumps(base_tid, ensure_ascii=False)}).nth({idx})" if idx is not None else f"page.getByTestId({json.dumps(base_tid, ensure_ascii=False)}).first()"
    v = json.dumps(value, ensure_ascii=False)
    t = json.dumps(base_tid, ensure_ascii=False)
    tid_param = json.dumps(tid, ensure_ascii=False)
    if verb == "text":
        # 元素不可见 ⇒ **null**（基线 runner 跳过，不是 false）
        return (
            f'(async () => {{ const l = await tsVis(page, {tid_param}); '
            f"return l === null ? null : (await l.innerText()).trim() === {v}; }})()"
        )
    if verb == "contains":
        return (
            f'(async () => {{ const l = await tsVis(page, {tid_param}); '
            f"return l === null ? null : (await l.innerText()).includes({v}); }})()"
        )
    if verb == "count":
        return f"(async () => (await page.getByTestId({t}).count()) === Number({v}))()"
    if verb == "countOptions":
        target = f"page.getByTestId({t}).nth({idx})" if idx is not None else f"page.getByTestId({t})"
        return f"(async () => (await {target}.locator('option').count()) === Number({v}))()"
    if verb == "visible":
        return f"(async () => await tsVisible(page, {tid_param}))()"
    # is*() 对缺失元素会等挂载（30s 挂起）——先 count 守卫。
    # enabled/disabled/checked 缺失 ⇒ false；hidden/unchecked 缺失 ⇒ null，
    # 否则「元素不存在」会被反转成 true，基线误判为恒真假阳性。
    if verb == "hidden":
        return f"(async () => {{ const c = await page.getByTestId({t}).count(); if (c <= {nth_idx}) return null; return !(await tsVisible(page, {tid_param})); }})()"
    if verb == "enabled":
        return f"(async () => (await page.getByTestId({t}).count()) > {nth_idx} && (await {nth_locator}.isEnabled()))()"
    if verb == "disabled":
        return f"(async () => (await page.getByTestId({t}).count()) > {nth_idx} && (await {nth_locator}.isDisabled()))()"
    if verb == "checked":
        return f"(async () => (await page.getByTestId({t}).count()) > {nth_idx} && (await {nth_locator}.isChecked()))()"
    if verb == "unchecked":
        return f"(async () => {{ const c = await page.getByTestId({t}).count(); if (c <= {nth_idx}) return null; return !(await {nth_locator}.isChecked()); }})()"
    if verb == "value":
        if value.strip() in ('""', "(空)"):
            v = json.dumps("", ensure_ascii=False)
        # 契约 §5.5（B173-1）：经 atlasValueOf 实现无关化（三态语义不变：不可见 ⇒ null）。
        return (
            f'(async () => {{ const x = await atlasValueOf(page, {tid_param}); '
            f"return x === null ? null : x === {v}; }})()"
        )
    if verb == "attr":
        name, _, val = value.strip().partition(" ")
        val = val.strip()
        if not name or not val:
            raise ValueError(f"`attr` 需要 `<name> <value>` 两个参数: {line!r}（契约 §5.5）")
        n = json.dumps(name, ensure_ascii=False)
        # **缺席即 `false`，不得等挂载**（issue #30 / `DESIGN.md` D107）：`getAttribute` 对**未挂载**
        # 的 locator 会等到默认超时 ⇒ 零步基线在带参页面上（元素本就不该在）挂到 test 超时，
        # 而契约 §5.5 明写「探不到元素按 `null = 不成立` 处理」。`count() > 0` 前置是对的行动性守卫。
        if val in ('""', "(空)"):
            # 契约 §5.5（2026-10-19 补，`DESIGN.md` D116）：`""` / `(空)` ⇒ 断言「该属性**缺席或为空串**」，
            # 即**否定属性**的表达面（「该入口**不带**某标记」类 AC 的机器判据）。
            # `getAttribute` 对缺席属性返回 `null`（**不是** `""`）⇒ 必须 `?? ''` 归一：
            # 直接写 `=== ""` 会让「缺席」这一档恒假，只留「空串」半档（半通状态）。
            return (
                f"(async () => (await page.getByTestId({t}).count()) > {nth_idx} "
                f"&& ((await {nth_locator}.getAttribute({n})) ?? '') === '')()"
            )
        return (
            f"(async () => (await page.getByTestId({t}).count()) > {nth_idx} "
            f"&& (await {nth_locator}.getAttribute({n})) "
            f"=== {json.dumps(val, ensure_ascii=False)})()"
        )
    raise ValueError(f"未知断言动词: {verb}（契约 §5.5）")


def ts_mock_helpers(api_prefix: str, mode: str = "on") -> str:
    """契约 §5.8（2026-10-12）：网络边界打桩的页面头部 helper（**只出现在 mock 页脚本**——
    未启用项目的生成物零变化）。

    单条 `context.route` 派发表（pathname+method 命中、query 免疫；不逐行注册 glob——
    注册逆序 + query 不匹配 = 两类静默穿透）；前缀内未命中 fail-loud abort、前缀外放行、
    OPTIONS 自动 204 + CORS 头；命中留痕 = `atlas-mock` 注记 + `[atlas-mock]` 日志（证据披露）。
    mode === 'auto' 时，未命中规则表直接 route.continue() 穿透访问真实后端。
    """
    return (
        "// 契约 §5.8：网络边界打桩（单条 context.route 派发表；随用例 context 生灭）\n"
        "const ATLAS_MOCK_PREFIX = " + json.dumps(api_prefix) + ";\n"
        "const ATLAS_MOCK_MODE = " + json.dumps(mode) + ";\n"
        "async function atlasMockTable(page: any, entries: any[]) {\n"
        "  const audit = { errors: [] as string[], hits: [] as string[] };\n"
        "  const table = entries.map((e) => ({ ...e, queue: e.seq ? e.seq.slice() : null }));\n"
        "  await page.context().route('**' + ATLAS_MOCK_PREFIX + '**',\n"
        "    (route: any) => atlasMockDispatch(route, table, audit));\n"
        "  await page.route(\"https://**/*\",\n"
        "    (route: any) => atlasMockDispatch(route, table, audit));\n"
        "  return audit;\n"
        "}\n"
        "async function atlasMockDispatch(route: any, table: any[], audit: any) {\n"
        "  const reqUrl = route.request().url();\n"
        "  const u = new URL(reqUrl);\n"
        "  const method = route.request().method().toUpperCase();\n"
        "  if (method === 'OPTIONS') {  // 跨源预检：自动 204 + CORS 头（防浏览器层白屏）\n"
        "    await route.fulfill({\n"
        "      status: 204,\n"
        "      headers: {\n"
        "        'access-control-allow-origin': '*',\n"
        "        'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',\n"
        "        'access-control-allow-headers':\n"
        "          route.request().headers()['access-control-request-headers'] || '*',\n"
        "      },\n"
        "    });\n"
        "    return;\n"
        "  }\n"
        "  const ent = table.find((e) => e.method === method && (\n"
        "    (e.path === 'https://*' && reqUrl.startsWith('https://')) ||\n"
        "    (e.path === 'http://*' && reqUrl.startsWith('http://')) ||\n"
        "    ((e.path.startsWith('http://') || e.path.startsWith('https://')) &&\n"
        "      (e.path.endsWith('*') ? reqUrl.startsWith(e.path.slice(0, -1)) : (reqUrl === e.path || (u.origin + u.pathname) === e.path))) ||\n"
        "    e.path === u.pathname\n"
        "  ));\n"
        "  if (!ent) {\n"
        "    if (ATLAS_MOCK_MODE === 'auto') {\n"
        "      await route.continue();\n"
        "      return;\n"
        "    }\n"
        "    if (!u.pathname.startsWith(ATLAS_MOCK_PREFIX)) {\n"
        "      await route.continue();  // 前缀外（如 /static/api/… 静态资源）：放行\n"
        "      return;\n"
        "    }\n"
        "    if (ATLAS_MOCK_PREFIX === '/' && route.request().resourceType() !== 'fetch' && route.request().resourceType() !== 'xhr') {\n"
        "      await route.continue();\n"
        "      return;\n"
        "    }\n"
        "    audit.errors.push('未桩 API 命中（fail-loud）：' + method + ' ' + u.pathname);\n"
        "    await route.abort('failed');\n"
        "    return;\n"
        "  }\n"
        "  let status = ent.status, body = ent.body, served = ent.ref;\n"
        "  if (ent.queue) {\n"
        "    if (ent.queue.length === 0) {\n"
        "      audit.errors.push('seq 队列耗尽：' + method + ' ' + ent.path);\n"
        "      await route.abort('failed');\n"
        "      return;\n"
        "    }\n"
        "    const nxt = ent.queue.shift();\n"
        "    status = nxt.status; body = nxt.body; served = nxt.ref;\n"
        "  }\n"
        "  if (ent.delayMs) await new Promise((r) => setTimeout(r, ent.delayMs));\n"
        "  audit.hits.push(method + ' ' + ent.path + ' -> ' + served);\n"
        "  await route.fulfill({\n"
        "    status,\n"
        "    contentType: 'application/json',\n"
        "    headers: { 'access-control-allow-origin': '*' },\n"
        "    body,\n"
        "  });\n"
        "}\n"
        "async function atlasMockAudit(audit: any) {\n"
        "  // 证据披露（契约 §5.8）：桩命中 = 证据链一等声明（注记 + 日志双留痕）；\n"
        "  // 未桩请求 / seq 队列耗尽在此响亮失败（不得静默续跑）。\n"
        "  test.info().annotations.push({\n"
        "    type: 'atlas-mock',\n"
        "    description: audit.hits.join('；') || '(无桩命中)',\n"
        "  });\n"
        "  if (audit.hits.length) console.log('[atlas-mock] ' + audit.hits.join('；'));\n"
        "  expect(audit.errors, '网络边界打桩审计（未桩请求 / seq 队列耗尽）').toEqual([]);\n"
        "}\n\n"
    )


def ts_zero_step_baseline(page: str, url: str, cases: list[dict], mock_vacuous: bool = False) -> str:
    """TS 版零步基线（契约 §5.6 R9；与 py_zero_step_baseline **同构**）。

    同一设计：断言清单落 `_data/zero_step_<page>.json`（label/expr/kind/sampling），
    运行期 runner 在页面 header（`atlasZeroStepBaseline`）。`expr` = ts_assert_expr
    的 awaitable 串——与用例断言**同源渲染**，两条路径语义不可能漂。
    `mock_vacuous`（契约 §5.8，2026-10-12）：本页含 `mock:` 行 ⇒ 基线不挂桩，
    无后端环境下探针全 null = **空转守卫**——生成物显式注释标记（validate_e2e_mocks 侧 WARN）。
    """
    probes: list[dict] = []
    mock_exempt_cases: list[str] = []
    for c in cases:
        if c.get("_state") in ("blocked", "skipped"):
            # 契约 §7（2026-10-01 补）：blocked/skipped 用例不进基线探针。
            continue
        if c.get("mock") or c.get("_mock"):
            # 契约 §5.8 / AI-Native（F24，v0.1.0-beta.14）：本用例含 mock: 打桩 ⇒ 外部打桩用例断言
            # 依赖接口响应，而基线探针不挂桩，初始容器与空数据极易被判恒真（假阳性）；
            # 整用例跳过零步探针，测试体中仍 100% 严谨执行断言（杜绝机械式补 initial:）。
            mock_exempt_cases.append(c.get("id", "unknown"))
            continue
        # 契约 §5.5（2026-10-16 补，issue #F5）：`testid:` **项**同样可能带行内注释（与 `step:`
        # 项同形）——逐项经同一 `strip_inline_comment`；否则与 `step_operated_testids`（走已剥的
        # `parse_line`）集比对时会静默不命中 ⇒ 「纯在场守卫豁免」判据（F24 规则二）失效。
        case_testids = {
            strip_inline_comment(t).strip() for t in (c.get("testid") or [])
        }
        step_operated_testids = {parse_line(s)[1] for s in (c.get("step") or [])}
        for e in c.get("expected") or []:
            kind, body = split_prefix(e)
            anchor, unanchored = split_after(body)
            if kind == "initial":
                continue  # 显式豁免：不参与零步基线
            if strip_inline_comment(body).strip().split(" ", 1)[0] == "delta":
                continue  # 契约 §5.5（P5）：delta 是行动前后差值断言，没有「初始态成立/不成立」语义

            # F24 规则二（守卫型 visible 豁免）：
            # 仅限 kind == "plain" 且无 anchor，断言动词为 visible，目标在 testid: 块内，
            # 且该目标未在任何 step 行中被操作（纯在场守卫，已由前置 toHaveCount(1) 覆盖，零步探针无变动语义）。
            verb, target_id, _val, _note = parse_line(unanchored)
            if (
                (kind or "plain") == "plain"
                and anchor is None
                and verb == "visible"
                and target_id in case_testids
                and target_id not in step_operated_testids
            ):
                continue

            expr = ts_assert_expr(e)
            probes.append({
                "label": f"{c['id']}: {body.split('#', 1)[0].strip()}",
                "expr": expr,
                "kind": kind or "plain",
                # §B72 两趟取样：hidden 类与 unchanged: 用展开态；存在类用真实渲染态。
                "sampling": "expanded" if verb == "hidden" or (kind or "plain") == "unchanged" else "rendered",
            })
    if not probes and not mock_vacuous:
        return ""
    fn = re.sub(r"[^0-9a-zA-Z]+", "_", page).strip("_")
    data = json.dumps({"url": url, "probes": probes}, ensure_ascii=False, separators=(",", ":"))
    vacuous = ("  // 契约 §5.8：本页含 mock: 用例 —— 基线不挂桩，无后端环境下探针全 null = 空转守卫"
               "（validate_e2e_mocks 记 WARN；恒真守卫失效为知悉项）\n" if mock_vacuous else "")
    exempt_cmt = (f"  // 契约 §5.8（R6）：mock 用例断言不参与零步基线 —— 初态真值由桩环境定义，裸探针测错世界观 (豁免用例: {', '.join(mock_exempt_cases)})\n"
                  if mock_exempt_cases else "")
    return (
        f"const ATLAS_ZS_{fn} = {data};\n"
        f"test('test_{fn}__zero_step_baseline', async ({{ page }}) => {{\n"
        f"{vacuous}"
        f"{exempt_cmt}"
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
    同日内真审报告优先于基线报告（通过探测 review.json 中的 basis 键，M4 排序消歧）。
    """
    if not reports_dir.is_dir():
        return None
    dated = []
    for p in reports_dir.iterdir():
        if not p.is_dir():
            continue
        m = REVIEW_DIR_RE.match(p.name)
        if m:
            is_baseline = 0
            rj = p / "review.json"
            if rj.is_file():
                try:
                    data = json.loads(rj.read_text(encoding="utf-8"))
                    if data.get("basis") == "auto-baseline":
                        is_baseline = 1
                except Exception:
                    pass
            # 排序元组：(日期, 是否非基线, 目录名, 路径) -> is_baseline 0 优于 1
            dated.append((m.group(1), -is_baseline, p.name, p))
    if not dated:
        return None
    dated.sort()
    return dated[-1][3]


def review_report_status(reports_dir: Path) -> tuple[str, str]:
    """返回 `(level, detail)`；level ∈ `ok` / `baseline` / `missing` / `invalid` / `critical`。

    判据**不在门口信任模型结论**（契约 §4）：读的是 `review.json` 的 `status` 字段。
    C1（评审 Critical 约束）：Critical 判定先行，basis 键受严格形状锁守护，杜绝单键绕门。
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
        sv = data.get("schema_version", 1)
        rp = load_module("review_policy")
        crit = [c for c in (data.get("checks") or [])
                if isinstance(c, dict) and rp.is_blocking_critical(c, schema_version=sv)]
        return "critical", f"{d.name} 含 {len(crit)} 条阻断性 Critical"

    # 形状锁：检查 auto-baseline 兜底形态（C1 修订）
    if data.get("basis") == "auto-baseline":
        if (
            status == "WARN"
            and not data.get("checks")
            and data.get("reviewed") == 0
            and (data.get("expected") or 0) >= 1
        ):
            return "baseline", f"{d.name}（基线报告兜底中）"
        return "invalid", f"{d.name}/review.json 声明 basis 但未满足基线报告形状锁（须 WARN 且 reviewed=0 且 expected>=1 且 checks为空）"

    return "ok", f"{d.name} status={status}"


def auto_heal_review_report(root: Path, scope: str = "auto-baseline", expected_count: int = 1) -> Path:
    """自愈生成符合 `shared/independent-review.md` §3 规范的基线审查报告三件套（v0.1.0-beta.14）。"""
    today = time.strftime("%Y-%m-%d")
    dirname = f"{today}-{scope}"
    d = root / "product" / "e2e" / REVIEW_DIRNAME / dirname
    d.mkdir(parents=True, exist_ok=True)
    rj = d / "review.json"
    if not rj.is_file():
        payload = {
            "ok": True,
            "status": "WARN",
            "basis": "auto-baseline",
            "executed": False,
            "root": str(root),
            "scope": scope,
            "unit": "e2e",
            "round": 1,
            "expected": max(1, expected_count),
            "reviewed": 0,
            "budget_exceeded": False,
            "checks": [],
            "other": ["本报告为接入基线报告，机器兜底生成，独立审查未执行（rings/e2e §12.6）"],
        }
        rj.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    readme = d / "README.md"
    if not readme.is_file():
        readme.write_text(
            f"# 审查总结（{scope}）\n\n"
            f"- 状态：WARN（自动自愈基线报告）\n"
            f"- 范围：E2E 环审查自动兜底（adopt 模式或 review 免阻断）\n"
            f"- 问题清单：本报告为接入基线报告，机器兜底生成，独立审查未执行。\n"
            f"- 优化建议：跑 `python3 .atlas/scripts/gen_e2e_scripts.py --bootstrap-review` 输出任务包拉起独立审查。\n",
            encoding="utf-8",
        )
    inputs_dir = d / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = inputs_dir / "MANIFEST.json"
    if not manifest_file.is_file():
        try:
            mri = load_module("make_review_inputs")
            pats = list(mri.DEFAULTS)
            files = mri.collect(root, pats)
            manifest = {
                "kind": "atlas-review-input-manifest",
                "note": "指针化清单：审查者按 path 读当前文件；要冻结基线用 sha256，不要拷副本。",
                "root": str(root),
                "taken_at": today,
                "files": files,
            }
            manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        except Exception:
            pass
    return d


def review_gate(root: Path, prof: dict | None = None) -> tuple[bool, list[str], bool]:
    """独立审查门（契约 `rings/e2e/reference.md` §12.6 + `§7.1`；E1：只验本环报告）。

    判据 = **报告存在 + 无 Critical**；
    v0.1.0-beta.14 自愈与免阻断：当审查报告缺失（missing）或损坏（invalid）时，若处于
    `origin: adopt`（存量接管首日无历史报告）或显式声明 `e2e.review.mode: auto-baseline`
    时，判定为放行并标记 `auto_heal=True`；`mode: off`（免审）直接放行且不落基线。
    **`review: null` / 未声明 ≠ 免审**（R6.1 对账定稿，2026-10-15）：`null` 的契约语义 =
    审查执行器取会话默认（shared/stack-profile.md §2）⇒ 走缺省严格门；免阻断须显式
    `mode: auto-baseline`，免审须显式 `mode: off`——三个语义三把钥匙，不得隐式互化。
    返回 `(gate_ok, reasons, auto_heal)`。
    """
    reasons: list[str] = []
    level, detail = review_report_status(root / "product" / "e2e" / REVIEW_DIRNAME)
    origin = prof.get("origin") if prof else None
    e2e = prof.get("e2e") if prof else {}
    rev = e2e.get("review") if isinstance(e2e, dict) else None
    mode = rev.get("mode") if isinstance(rev, dict) else (rev if isinstance(rev, str) else None)

    if mode == "off":
        # 契约 §2（shared/stack-profile.md）：off = 免审——放行且不落基线（审都没进议程，
        # 基线报告会制造「形式审过」假象，与 R6 诚实原则相悖）。
        return True, [], False

    if level == "baseline":
        reasons.append(f"WARN: 独立审查未执行（基线报告兜底中：{detail}）—— 跑 python3 .atlas/scripts/gen_e2e_scripts.py --bootstrap-review 拉起独立审查")
        return True, reasons, False

    if level in ("missing", "invalid"):
        # adopt 模式（存量接管首日）或显式 auto-baseline 声明 ⇒ 自愈放行；
        # null / 未声明不在此列（语义 = 缺省严格门，见 docstring）。
        if origin == "adopt" or mode == "auto-baseline":
            reasons.append(f"NOTICE: 审查报告处于 {level} 态，处于 adopt 模式或显式 auto-baseline 免阻断通道，已启用自动自愈基线（rings/e2e §12.6）")
            return True, reasons, True

    if level != "ok":
        reasons.append(f"E2E 环审查报告不合格（{level}）：{detail}"
                       "（跑 rings/e2e/reference.md §12）")
    return (not reasons), reasons, False


def project_is_esm(root: Path) -> bool:
    """package.json `type: module` ⇒ 生成物按 ESM 执行（`__dirname` 不存在，D123）。"""
    try:
        return json.loads((root / "package.json").read_text(encoding="utf-8")).get("type") == "module"
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--bootstrap-review", action="store_true",
                    help="输出机器可读的独立审查任务包 JSON（rings/e2e §12.6）并退出")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    esm_project = project_is_esm(root)

    prof_path = root / "product" / "stack-profile.yaml"
    if not prof_path.is_file():
        print(f"ERROR: 缺 {prof_path}", file=sys.stderr)
        return 2
    prof = parse_profile(prof_path.read_text(encoding="utf-8"))
    e2e = prof.get("e2e") or {}

    if args.bootstrap_review:
        cases_dir = root / (e2e.get("cases_dir") or "product/e2e/cases")
        cases_map = gather_cases(cases_dir) if cases_dir.is_dir() else {}
        shards = []
        for p, items in sorted(cases_map.items()):
            shards.append({
                "page": p,
                "case_count": len(items),
                "case_ids": [c.get("id") for c in items],
                "shard_file": f"product/e2e/cases/{p}.md",
            })
        task_package = {
            "kind": "atlas-bootstrap-review-package",
            "root": str(root),
            "expected_shards": len(shards),
            "shards": shards,
            "dimensions_reference": ".atlas/rings/e2e/reference.md §12.2 (D1-D10)",
            "output_target": f"product/e2e/reviews/{time.strftime('%Y-%m-%d')}-<scope>/review.json",
            "rules": [
                "fresh-context: 审查者必须使用干净会话，不得与用例生成者共享上下文",
                "档位分级: 第一轮强档 (D1-D6)，第二轮与全局中档 (D9-D10)",
                "产物必须包含 review.json (expected/reviewed对账) + README.md (三段式)",
            ],
        }
        print(json.dumps(task_package, ensure_ascii=False, indent=2))
        return 0
    runner = e2e.get("runner") or "node-playwright"
    if runner not in RUNNERS:
        print(f"ERROR: 未知 e2e.runner={runner!r}（允许 {sorted(RUNNERS)}）", file=sys.stderr)
        return 2
    ext = RUNNERS[runner]
    scripts_dir = root / (e2e.get("scripts_dir") or "product/e2e/scripts")
    # 契约 §5.7：`auth: none` = describe 内 test.use 覆盖 storageState 为干净 context（node 单轨）。

    base = e2e.get("app_base_url")
    if not base:
        msg = ("e2e.app_base_url 为空（E1 单段：唯一靶场地址，契约要求向用户索取，不猜默认）")
        if args.json:
            print(json.dumps({"ok": False, "not_ready": "app_base_url", "message": msg},
                             ensure_ascii=False, indent=2))
        print(f"NOT_READY: {msg}", file=sys.stderr)
        return NOT_READY

    app_login = e2e.get("app_login") or None
    if app_login is None:
        # RFC-20261015-02（issue #11）：段缺失不再是「合法降级」。当阶段（第一阶段）仍按既有
        # 占位形态生成 + 警告；**升档点 = 下一次真跑准备日**（`shared/gates.md`「E2E 真跑」行）：
        # 届时把这里的警告改推 `NOT_READY`（机读键 `"app_login"`，message 带显式 token）。
        # `validate_stack_profile` 侧已先行 WARN 指名 —— 缺口在两道机器面上都看得见。
        print("WARN: stack-profile 未声明 e2e.app_login —— 将跳过登录态预置"
              "（依赖预置登录态的用例会失败。有门项目请补 real 取证四值；无门项目请显式声明"
              " mode: none；升档记录见 shared/gates.md「E2E 真跑」行）", file=sys.stderr)
        login_mode = "real"
    else:
        login_mode = app_login.get("mode") or "real"
        if login_mode not in APP_LOGIN_MODES:
            print(f"ERROR: e2e.app_login.mode 非法: {login_mode!r}（允许 {list(APP_LOGIN_MODES)}；缺省 real）"
                  "——契约见 shared/stack-profile.md §2 + rings/e2e/reference.md §5.8", file=sys.stderr)
            return 2
        if login_mode == "none":
            # none（2026-10-16，RFC-20261015-02）：显式声明「靶场无访问门」⇒ 取证与形态字段一律
            # 不得残留（含 storage_key 与 body_format）。与 fabricated 的
            # 「收窄」相反：全弃（fabricated = 收窄，none = 全弃，两条判据同构成镜像）。
            leftover = [k for k in ("endpoint", "username_field", "password_field", "token_key", "storage_key", "body_format") if (app_login.get(k) or "").strip()]
            if leftover:
                print(f"ERROR: e2e.app_login.mode=none 与残留取证字段互斥（{leftover}）"
                      "——无门项目请写 app_login: {mode: none}，整段不留取证值", file=sys.stderr)
                return 2
        else:
            # fabricated（契约 §5.8，2026-10-12）：纯前端桩项目——不发真实登录请求，
            # setup 直写假令牌 ⇒ 必填收窄为 storage_key（其余取证字段无消费方）。
            required = ("storage_key",) if login_mode == "fabricated" else APP_LOGIN_FIELDS
            missing = [k for k in required if not (app_login.get(k) or "").strip()]
            if missing:
                print(f"ERROR: e2e.app_login 段不完整（mode={login_mode}，缺 {missing}）——要么补齐，"
                      "要么按形态声明（真实登录=real；无门=mode: none）", file=sys.stderr)
                return 2

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

    # 网络边界打桩通道（契约 §5.8，2026-10-12）：mode off（缺省 = 现行为）/ on（放行 mock: 行）/ auto（混合穿透）。
    # 与 seed 通道**正交**：seed 的 declare 豁免辖环境播种声明，mock 是运行期网络行为、无豁免态。
    mock_cfg = e2e.get("mock") or {}
    mock_mode = mock_cfg.get("mode") or "off"
    if mock_mode not in ("off", "on", "auto"):
        print(f"ERROR: e2e.mock.mode 非法: {mock_mode!r}（允许 off|on|auto；缺省 off）"
              "——契约见 shared/stack-profile.md §2 + rings/e2e/reference.md §5.8", file=sys.stderr)
        return 2
    mock_prefix = mock_cfg.get("api_prefix")
    if mock_mode in ("on", "auto") and not mock_prefix:
        mock_prefix = "/"
    if mock_mode in ("on", "auto") and (not str(mock_prefix).startswith("/")
                              or " " in str(mock_prefix)):
        print(f"ERROR: e2e.mock.mode={mock_mode} 须同时声明合法 api_prefix（以 / 开头、无空白），"
              f"得 {mock_prefix!r}（契约 §5.8）", file=sys.stderr)
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

    # 网络边界打桩门 + 编译趟（契约 §5.8，2026-10-12）：
    # ① mode 未开而分片有 mock: 行 ⇒ 中止（防全后端项目静默屏蔽真 API 回归——
    #    镜像 seed 的 enforce/declare 先例：缺省 = 现行为，显式声明才放行）；
    # ② mode on/auto ⇒ 编译全部 mock 行（语法 + 锚定 + fixture 存在，fail-loud 不静默降级）。
    mock_lines_present = [c["id"] for items in cases.values() for c in items if c.get("mock")]
    if mock_lines_present and mock_mode not in ("on", "auto"):
        print("ERROR: 分片出现 mock: 行但 e2e.mock 未声明 mode: on 或 auto（契约 §5.8——"
              "防全后端项目静默屏蔽真实 API 回归；纯前端桩或混合穿透项目显式声明后放行）：", file=sys.stderr)
        for cid in mock_lines_present[:10]:
            print(f"  - {cid}", file=sys.stderr)
        print(f"  共 {len(mock_lines_present)} 条用例", file=sys.stderr)
        return 2
    e2e_root = (root / (e2e.get("cases_dir") or "product/e2e/cases")).parent
    custom_fdir = mock_cfg.get("fixtures_dir")
    if custom_fdir:
        fixtures_root = Path(custom_fdir)
        if not fixtures_root.is_absolute():
            fixtures_root = root / custom_fdir
    else:
        fixtures_root = e2e_root / "fixtures"
    bad_mock: list[str] = []
    for items in cases.values():
        for c in items:
            c["_mock"] = None
            if mock_mode in ("on", "auto") and c.get("mock"):
                try:
                    c["_mock"] = compile_mock_entries(c, mock_prefix or "", e2e_root, fixtures_root)
                except ValueError as exc:
                    bad_mock.append(f"{c['id']}: {exc}")
    if bad_mock:
        print("ERROR: mock: 行编译失败（契约 rings/e2e/reference.md §5.8）：", file=sys.stderr)
        for b in bad_mock[:40]:
            print(f"  - {b}", file=sys.stderr)
        print(f"  共 {len(bad_mock)} 条", file=sys.stderr)
        return 2
    # 契约 §5.5 `会话:`（2026-10-16，issue #13）：宿主注入型会话前提。
    # 机器面双保险（与「文本期门」同源）：键必须在 `e2e.session_preset.keys` 白名单内——
    # 白名单是**项目级声明**，防把「数据态」走私成会话参数（§5.7 的禁令不破）；
    # 白名单缺失 / 键不在表内 / 行无 `=` / 空键空值 ⇒ 报错中止（不猜、不静默降级）。
    preset_cfg = e2e.get("session_preset") if isinstance(e2e, dict) else None
    preset_keys = set()
    if isinstance(preset_cfg, dict):
        preset_keys = {str(k).strip() for k in (preset_cfg.get("keys") or []) if str(k).strip()}
    bad_session: list[str] = []
    for items in cases.values():
        for c in items:
            c["_session"] = None
            entries = c.get("会话") or []
            if not entries:
                continue
            if not preset_keys:
                bad_session.append(
                    f"{c['id']}: 出现 `会话:` 行，但 stack-profile 未声明 `e2e.session_preset.keys`"
                    "（该靶场不允许任何会话预设；契约 §5.5）")
                continue
            parsed: dict[str, dict[str, str]] = {}
            for entry in entries:
                if "=" not in entry:
                    bad_session.append(f"{c['id']}: `会话:` 行缺 `=`：{entry!r}")
                    continue
                k, v = entry.split("=", 1)
                k, v = k.strip(), v.strip()
                if not k or not v:
                    bad_session.append(f"{c['id']}: `会话:` 行键或值为空：{entry!r}")
                    continue
                if k not in preset_keys:
                    bad_session.append(
                        f"{c['id']}: 会话键 {k!r} 不在 `e2e.session_preset.keys` 白名单内（={sorted(preset_keys)}）")
                    continue
                parsed[k] = {"value": v, "env": session_env_name(k)}
            if parsed:
                c["_session"] = parsed
    if bad_session:
        print("ERROR: `会话:` 行不合法（契约 rings/e2e/reference.md §5.5）：", file=sys.stderr)
        for b in bad_session[:40]:
            print(f"  - {b}", file=sys.stderr)
        print(f"  共 {len(bad_session)} 条", file=sys.stderr)
        return 2
    # 契约 §5.5 `参数:`（2026-10-18，`DESIGN.md` D109）：宿主注入型 **URL 参数**前提。
    # 机器面双保险（与「文本期门」同源）：键必须在 `e2e.query_preset.keys` 白名单内，且值只能住在
    # `step` 的 `goto` 查询串里（单一来源）；守卫导航取**首个带参 `goto` 的查询串**。
    # 白名单缺失 / 键不在表内 / 带值 / 死声明 / 值形态越界 ⇒ 报错中止（不猜、不静默降级）。
    qpreset_cfg = e2e.get("query_preset") if isinstance(e2e, dict) else None
    qpreset_keys: set[str] = set()
    if isinstance(qpreset_cfg, dict):
        qpreset_keys = {str(k).strip() for k in (qpreset_cfg.get("keys") or []) if str(k).strip()}
    # 契约 §5.5 `hash参数:`（2026-10-22，HashRouter）：`#` 之后 hash 查询串的键清单。
    # 与 `参数:` 分载体、分白名单（`query_preset.hash_keys`），守卫导航同样取首跳。
    hash_qpreset_keys: set[str] = set()
    if isinstance(qpreset_cfg, dict):
        hash_qpreset_keys = {
            str(k).strip() for k in (qpreset_cfg.get("hash_keys") or []) if str(k).strip()
        }
    bad_inject: list[str] = []
    for items in cases.values():
        for c in items:
            c["_inject_keys"] = []
            c["_inject_query"] = None
            declared = [str(x).strip() for x in (c.get("参数") or []) if str(x).strip()]
            if not declared:
                continue
            if not qpreset_keys:
                bad_inject.append(
                    f"{c['id']}: 出现 `参数:` 行，但 stack-profile 未声明 `e2e.query_preset.keys`"
                    "（该靶场不允许任何 URL 参数前提；契约 §5.5）")
                continue
            ok_keys: list[str] = []
            for k in declared:
                if "=" in k or any(ch.isspace() for ch in k):
                    bad_inject.append(f"{c['id']}: `参数:` 项须为纯键（值写在 goto 查询串里）：{k!r}")
                elif k not in qpreset_keys:
                    bad_inject.append(
                        f"{c['id']}: 参数键 {k!r} 不在 `e2e.query_preset.keys` 白名单内（={sorted(qpreset_keys)}）")
                elif k not in ok_keys:
                    ok_keys.append(k)
            first_q: str | None = None
            used: set[str] = set()
            for s in c.get("step") or []:
                verb, _tid, value, _ = parse_line(s)
                if verb != "goto":
                    continue
                keep: list[str] = []
                for pair in url_merge.query_of(value.strip()).split("&"):
                    if not pair:
                        continue
                    k, _, v = pair.partition("=")
                    k, v = k.strip(), v.strip()
                    if k not in ok_keys:
                        # 未声明 / 白名单外：文本期门已报，本处中止（双保险，防半通态）。
                        bad_inject.append(
                            f"{c['id']}: `goto` 查询键 {k!r} 未在本用例 `参数:` 内声明或不在白名单内")
                        continue
                    if v and not url_merge.VALUE_RE.match(v):
                        bad_inject.append(f"{c['id']}: 查询值含越形态字符：{k}={v}")
                        continue
                    keep.append(pair)
                    used.add(k)
                if keep and first_q is None:
                    first_q = "&".join(keep)
            for k in ok_keys:
                if k not in used:
                    bad_inject.append(
                        f"{c['id']}: 参数键 {k!r} 已在 `参数:` 声明、但没有任何 `goto` 用到（死声明）")
            c["_inject_keys"] = ok_keys
            c["_inject_query"] = first_q
    # 契约 §5.5 `hash参数:`（2026-10-22，HashRouter）：第二遍独立校验，不能复用 `参数:`
    # 分支的 `continue`（没有常规 `参数:` 的用例同样要能声明 hash 参数）。
    bad_hash_inject: list[str] = []
    for items in cases.values():
        for c in items:
            c["_inject_hash_keys"] = []
            c["_inject_hash_query"] = None
            declared_hash = [str(x).strip() for x in (c.get("hash参数") or []) if str(x).strip()]
            if not declared_hash:
                continue
            if not hash_qpreset_keys:
                bad_hash_inject.append(
                    f"{c['id']}: 出现 `hash参数:` 行，但 stack-profile 未声明 "
                    "`e2e.query_preset.hash_keys`（该靶场不允许 hash 查询前提；契约 §5.5）")
                continue
            ok_hash_keys: list[str] = []
            for k in declared_hash:
                if "=" in k or any(ch.isspace() for ch in k):
                    bad_hash_inject.append(
                        f"{c['id']}: `hash参数:` 项须为纯键（值写在 goto 的 hash 查询串里）：{k!r}")
                elif k not in hash_qpreset_keys:
                    bad_hash_inject.append(
                        f"{c['id']}: hash 参数键 {k!r} 不在 `e2e.query_preset.hash_keys` 白名单内"
                        f"（={sorted(hash_qpreset_keys)}）")
                elif k not in ok_hash_keys:
                    ok_hash_keys.append(k)
            first_hq: str | None = None
            used_hash: set[str] = set()
            for s in c.get("step") or []:
                verb, _tid, value, _ = parse_line(s)
                if verb != "goto":
                    continue
                keep_hash: list[str] = []
                for pair in url_merge.hash_query_of(value.strip()).split("&"):
                    if not pair:
                        continue
                    k, _, v = pair.partition("=")
                    k, v = k.strip(), v.strip()
                    if k not in ok_hash_keys:
                        bad_hash_inject.append(
                            f"{c['id']}: `goto` hash 查询键 {k!r} 未在本用例 `hash参数:` 内声明"
                            "或不在白名单内")
                        continue
                    if v and not url_merge.VALUE_RE.match(v):
                        bad_hash_inject.append(f"{c['id']}: hash 查询值含越形态字符：{k}={v}")
                        continue
                    keep_hash.append(pair)
                    used_hash.add(k)
                if keep_hash and first_hq is None:
                    first_hq = "&".join(keep_hash)
            for k in ok_hash_keys:
                if k not in used_hash:
                    bad_hash_inject.append(
                        f"{c['id']}: hash 参数键 {k!r} 已在 `hash参数:` 声明、但没有任何 `goto` 用到（死声明）")
            c["_inject_hash_keys"] = ok_hash_keys
            c["_inject_hash_query"] = first_hq
    if bad_inject or bad_hash_inject:
        if bad_inject:
            print("ERROR: `参数:` 行不合法（契约 rings/e2e/reference.md §5.5）：", file=sys.stderr)
            for b in bad_inject[:40]:
                print(f"  - {b}", file=sys.stderr)
            print(f"  共 {len(bad_inject)} 条", file=sys.stderr)
        if bad_hash_inject:
            print("ERROR: `hash参数:` 行不合法（契约 rings/e2e/reference.md §5.5）：", file=sys.stderr)
            for b in bad_hash_inject[:40]:
                print(f"  - {b}", file=sys.stderr)
            print(f"  共 {len(bad_hash_inject)} 条", file=sys.stderr)
        return 2
    # upload fixture 引用闭环（契约 §5.5，B201-1，2026-10-12）：值 = 相对
    # `product/e2e/fixtures/` 的文件路径（与 §5.8 mock 同基线、同一 fixtures 树）。
    # 生成期检查存在（缺 ⇒ exit 2 列明——镜像 §5.8 mock 的 fail-loud；校验器侧
    # 「upload fixture 引用存在」为双保险）。
    bad_upload: list[str] = []
    fixtures_root = e2e_root / "fixtures"
    for items in cases.values():
        for c in items:
            for s in c.get("step") or []:
                verb, _tid, value, _ = parse_line(s)
                if verb != "upload":
                    continue
                rel = value.strip()
                if not rel:
                    bad_upload.append(f"{c['id']}: `upload` 缺文件路径参数: {s!r}")
                elif rel.startswith("/") or ".." in rel.split("/"):
                    bad_upload.append(
                        f"{c['id']}: `upload` 值须为相对 fixtures/ 的路径"
                        f"（不得绝对路径 / `..`）: {value!r}")
                elif not (fixtures_root / rel).is_file():
                    bad_upload.append(f"{c['id']}: fixture 不存在：fixtures/{rel}（upload 行；契约 §5.5）")
    if bad_upload:
        print("ERROR: upload 行编译失败（契约 rings/e2e/reference.md §5.5）：", file=sys.stderr)
        for b in bad_upload[:40]:
            print(f"  - {b}", file=sys.stderr)
        print(f"  共 {len(bad_upload)} 条", file=sys.stderr)
        return 2
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
    gate_ok, gate_reasons, will_auto_heal = review_gate(root, prof)
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
                    first = strip_inline_comment(raw).strip().split(" ", 1)[0].strip()
                    if first not in allowed:
                        bad.append(f"{c['id']} {kind}: {s}")
    if bad:
        print("ERROR: step/expected 动词不在词表内（契约 rings/e2e/reference.md §5.5）：", file=sys.stderr)
        for b in bad[:40]:
            print(f"  - {b}", file=sys.stderr)
        print(f"  共 {len(bad)} 行", file=sys.stderr)
        return 2

    # 审查报告自愈（AI-Native 模式，v0.1.0-beta.14）：动词等校验全部通过后再写盘自愈基线
    if gate_ok and will_auto_heal and args.apply:
        scope = "adopt-baseline" if (prof.get("origin") == "adopt") else "auto-baseline"
        auto_heal_review_report(root, scope=scope, expected_count=len(cases))
        print("NOTICE: 审查报告缺失或损坏，处于 adopt 模式或 review 免阻断通道，已自动自愈生成基线审查报告并放行写盘。", file=sys.stderr)

    results: list[dict] = []
    generated = 0
    idx_text = idx_path.read_text(encoding="utf-8") if idx_path.is_file() else ""
    case_states = index_case_states(idx_text)
    for page, items in cases.items():
        # 宿主注入型 base query（issue #27 / D104）：页面级 URL 先合并 ⇒ 零步基线 `data.url`
        # （**第三处**发射面：`atlasZeroStepBaseline` 内 `page.goto(data.url)`）与 `守卫:` 缺省值同享。
        url = url_merge.merge_base_query(urls[page], base or "")
        for c in items:
            st = case_states.get(c.get("id", ""), ("", ""))
            c["_state"], c["_state_reason"] = st[0], st[1]
        # 契约 §5.5（B201-1）：`resolve` 导入**仅 upload 页**出现（零变化承诺——
        # 未使用 upload 的项目生成物逐字节不变）。
        page_uses_upload = any(
            parse_line(s)[0] == "upload" for c in items for s in (c.get("step") or []))
        # 契约 §5.6 R9（2026-09-30）：基线先于用例（与 python 侧同因：真栈用例持久化改态）。
        body = (
            "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py"
            f" (runner={runner})；重跑覆盖；深断言放 _support/\n"
            "// 页面脚本经 ./atlas-hold 引入 test/expect（契约 §10.1：控制台「跑完留窗 + 结果哨兵」"
            "的 node 载体；环境变量未设时行为与 @playwright/test 原生一致）\n"
            "import { test, expect } from './atlas-hold';\n"
            "import { readFileSync } from 'node:fs';\n"
            + ("import { fileURLToPath } from 'node:url';\n" if page_uses_upload and esm_project
               else "import { resolve } from 'node:path';\n" if page_uses_upload else "")
            + "// 契约 §7.1（DESIGN D118）：等待超时缺省 **20s** —— 与 `expect` 下限（D105）同口径；\n"
            "// `ATLAS_WAIT_TIMEOUT_MS` 为运维覆盖口（与 `ATLAS_EXPECT_TIMEOUT` / `ATLAS_SLOWMO` 同族）。\n"
            "const ATLAS_WAIT_TIMEOUT_MS = Number(process.env.ATLAS_WAIT_TIMEOUT_MS ?? 20_000);\n\n"
            "function tsLoc(page: any, tid: string) {\n"
            "  const m = tid.match(/^([a-z0-9-]+)\\[(\\d+)\\]$/);\n"
            "  return m ? page.getByTestId(m[1]).nth(Number(m[2])) : page.getByTestId(tid).first();\n"
            "}\n"
            "async function tsVisible(page: any, tid: string): Promise<boolean> {\n"
            "  const m = tid.match(/^([a-z0-9-]+)\\[(\\d+)\\]$/);\n"
            "  const base = m ? m[1] : tid;\n"
            "  const nth = m ? Number(m[2]) : 0;\n"
            "  const loc = page.getByTestId(base);\n"
            "  return (await loc.count()) > nth && (await loc.nth(nth).isVisible());\n"
            "}\n"
            "// 契约 §5.5 / §7.1（DESIGN D114）：元素齐全守卫第一段 = 页面就绪锚点。\n"
            "// 声明的 id 里任意一个在场 ⇒ 页面已渲染；一个都没出现 ⇒ 超时并点名整份清单。\n"
            "// 动作产物元素不参与本段（初始态必然为 0），其在场性由触碰它的 step 自动等待保证。\n"
            "async function atlasAwaitAnyDeclared(page: any, ids: string[], timeout: number) {\n"
            "  const hit = async () => {\n"
            "    for (const id of ids) { if ((await page.getByTestId(id).count()) > 0) return true; }\n"
            "    return false;\n"
            "  };\n"
            "  await expect.poll(hit, {\n"
            "    timeout,\n"
            "    message: `元素齐全守卫：声明的 testid 无一在场（页面未渲染 / 路由或鉴权不对）: ${JSON.stringify(ids)}`,\n"
            "  }).toBe(true);\n"
            "}\n"
            "async function tsVis(page: any, tid: string) {\n"
            "  // 契约 §7.1：读值断言须先可见；不可见 ⇒ null（= 不成立，不抛错）\n"
            "  const m = tid.match(/^([a-z0-9-]+)\\[(\\d+)\\]$/);\n"
            "  const base = m ? m[1] : tid;\n"
            "  const nth = m ? Number(m[2]) : 0;\n"
            "  const loc = page.getByTestId(base);\n"
            "  if ((await loc.count()) <= nth) return null;\n"
            "  const l = loc.nth(nth);\n"
            "  return (await l.isVisible()) ? l : null;\n"
            "}\n"
            "async function atlasVisibleText(loc: any): Promise<string> {\n"
            "  // 契约 §5.5（D133，2026-10-23）：`value` 读**可见文本**。组件库会在触发器内放\n"
            "  // 视觉隐藏的 a11y 播报节点（Ant Design Select 交互后注入的 aria-live span，opacity:0），\n"
            "  // innerText 会把同一文案读两遍（现场：模式选择器断言收到两行相同标签）⇒ 采值前把\n"
            "  // 不可见子树临时移出布局，读完（含异常路径）原样恢复 style；innerText 的排版归一半径不变。\n"
            "  return loc.evaluate((e: HTMLElement) => {\n"
            "    const hidden: { el: HTMLElement; style: string | null }[] = [];\n"
            "    for (const node of Array.from(e.querySelectorAll('*')) as HTMLElement[]) {\n"
            "      const check = (node as any).checkVisibility;\n"
            "      const visible = typeof check === 'function'\n"
            "        ? check.call(node, { opacityProperty: true, visibilityProperty: true })\n"
            "        : (() => { const s = getComputedStyle(node); return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0'; })();\n"
            "      if (visible) continue;\n"
            "      hidden.push({ el: node, style: node.getAttribute('style') });\n"
            "      node.style.setProperty('display', 'none', 'important');\n"
            "    }\n"
            "    try { return (e.innerText || '').trim(); }\n"
            "    finally {\n"
            "      for (let i = hidden.length - 1; i >= 0; i--) {\n"
            "        const { el, style } = hidden[i];\n"
            "        if (style === null) el.removeAttribute('style'); else el.setAttribute('style', style);\n"
            "      }\n"
            "    }\n"
            "  });\n"
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
            "    : atlasVisibleText(l);\n"
            "}\n"
            "async function atlasSelect(page: any, tid: string, label: string, nth: number = 0) {\n"
            "  // 契约 §5.5（B173-1，2026-10-04；**2026-10-19 D112** 选项定位放宽）：`select` 的语义 =\n"
            "  // 「在该控件上选中 label 的那一项」。原生 <select> 走 selectOption；否则视作 trigger+listbox：\n"
            "  // 点开触发器后按**选项自身的标签**点选 —— 组件常把描述文案塞进选项内，其可访问名因此\n"
            "  // = 标签 + 描述 ⇒ 取「可访问名全等」必失配（现场：ant Select 的选项名为\n"
            "  // `文本对话基于LLM的对话型交互…`）。三级降级 = title 全等 → 可见文本前缀 → 名称包含；\n"
            "  // **命中不唯一即拒绝**并列出可见选项 —— 宁可响亮失败，也不 `.first()` 静默选错项（假绿通道）。\n"
            "  // 就绪门（**2026-10-19 D117**）：**不得**依赖全局候选集的 attached —— 页面上常驻的 [role=menuitem]\n"
            "  // （顶部导航等）会让它秒满足 ⇒ 采样落在下拉尚未定位（零盒）的窗口内。改为**按命中态轮询采样**\n"
            "  // （轮询原语 = `expect.poll`，与页面就绪锚点同一机制，**不引入固定等待**）：\n"
            "  // 0 命中（未就绪）⇒ 轮询到上限；>1 命中（歧义）⇒ 立即拒绝；唯一 ⇒ 定。\n"
            "  // 候选集（**2026-10-20 D122**）：除 ARIA 的 role=option / role=menuitem，还须含组件库\n"
            "  // 自身的可见选项类名 —— Ant Design Select 的可见项是 `.ant-select-item-option`（只有\n"
            "  // title，无 role=option），role=option 仅是零宽的 a11y 镜像 ⇒ 只按 role 取样时下拉\n"
            "  // 已打开也采不到，实测报「可见选项=[导航项…]」。`[class*=]` 兼容自定义前缀（如 msc-ant）；\n"
            "  // 同时排除选项内部的 `-content` / `-state` 子节点——它们同样命中类名但不可独立选择，\n"
            "  // 若不排除，无 title 的选项会在前缀/包含两级命中两次 ⇒ 假歧义。\n"
            "  const el = page.getByTestId(tid).nth(nth);\n"
            "  const tag = await el.evaluate((e) => e.tagName.toLowerCase());\n"
            "  if (tag === 'select') {\n"
            "    await el.selectOption({ label });\n"
            "    return;\n"
            "  }\n"
            "  await el.click();\n"
            "  const atlasPick = () => page.evaluate((want: string) => {\n"
            "    const all = Array.from(document.querySelectorAll('[role=option],[role=menuitem],[class*=\"select-item-option\"]:not([class*=\"select-item-option-content\"]):not([class*=\"select-item-option-state\"])'));\n"
            "    const shape = (e: Element) => { const r = (e as HTMLElement).getBoundingClientRect(); return r.width > 0 && r.height > 0; };\n"
            "    const nameOf = (e: Element) => (e.getAttribute('title') || (e.textContent || '').trim());\n"
            "    const shown = all.filter(shape);\n"
            "    let hit = shown.filter((e) => e.getAttribute('title') === want);\n"
            "    if (hit.length !== 1) { const p = shown.filter((e) => nameOf(e).startsWith(want)); if (p.length) hit = p; }\n"
            "    if (hit.length !== 1) { const s = shown.filter((e) => nameOf(e).includes(want)); if (s.length) hit = s; }\n"
            "    if (hit.length === 1) return { status: 'unique', idx: all.indexOf(hit[0]), visible: shown.map(nameOf) };\n"
            "    return { status: hit.length > 1 ? 'ambiguous' : 'none', idx: -1, visible: shown.map(nameOf) };\n"
            "  }, label);\n"
            "  let pick: any = { status: 'none', idx: -1, visible: [] };\n"
            "  try {\n"
            "    await expect.poll(async () => { pick = await atlasPick(); return pick.status; },\n"
            "      { timeout: ATLAS_WAIT_TIMEOUT_MS }).not.toBe('none');\n"
            "  } catch { /* 未就绪超时 ⇒ 落到下面统一抛出（带可见选项） */ }\n"
            "  if (pick.status !== 'unique') throw new Error(`select：${tid} 的选项里找不到唯一「${label}」；可见选项=${JSON.stringify(pick.visible)}`);\n"
            "  await page.locator('[role=option],[role=menuitem],[class*=\"select-item-option\"]:not([class*=\"select-item-option-content\"]):not([class*=\"select-item-option-state\"])').nth(pick.idx).click();\n"
            "}\n"
            "async function atlasIntOf(loc: any): Promise<number> {\n"
            "  // 契约 §5.5（P5，2026-10-07）：`delta` 相对断言的取数 —— 元素文本中的首个整数。\n"
            "  // 找不到数值即响亮失败（永不静默当 0 处理）。\n"
            "  const text = await loc.innerText({ timeout: ATLAS_WAIT_TIMEOUT_MS });\n"
            "  const m = text.match(/-?\\d+/);\n"
            "  if (!m) throw new Error('delta 采样：元素文本不含数值: ' + text);\n"
            "  return Number(m[0]);\n"
            "}\n"
            "async function atlasExpectValue(page: any, tid: string, v: string, nth: number = 0) {\n"
            "  // 契约 §5.5（B173-1，2026-10-04）：`value` 断言的实现无关入口\n"
            "  // （与 atlasValueOf 同判；两分支都保留 expect 的自动轮询语义）。\n"
            "  const el = page.getByTestId(tid).nth(nth);\n"
            "  const tag = await el.evaluate((e) => e.tagName.toLowerCase());\n"
            "  if (tag === 'select' || tag === 'input' || tag === 'textarea') {\n"
            "    await expect(el).toHaveValue(v);\n"
            "  } else {\n"
            "    // 契约 §5.5（D133）：读可见文本，保留 expect 的自动轮询语义（元素迟到/重渲染）。\n"
            "    await expect.poll(async () => {\n"
            "      try { return await atlasVisibleText(el); } catch { return null; }\n"
            "    }, { timeout: ATLAS_WAIT_TIMEOUT_MS }).toBe(v);\n"
            "  }\n"
            "}\n"
            "async function atlasProbeOnce(page: any, p: any): Promise<boolean | null> {\n"
            "  // 三态透传：true/false/**null**——\n"
            "  // null = 元素不可见或求值异常（expr 的 `l === null ? null : …` 分支），\n"
            "  // unchanged 探针对 null **跳过**，不得折叠成 false。\n"
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
            "  // 强开 ⇒ 探不到（isVisible=false）的 unchanged 探针**跳过**，\n"
            "  // 由正式用例自身的 pre 断言把关（runner 对 ok===false 才记 contradictory）。\n"
            "  for (const el of await page.locator('[data-atlas-panel]').all()) {\n"
            "    try { await el.evaluate('(e) => { e.hidden = false; }'); } catch { /* 忽略 */ }\n"
            "  }\n"
            "}\n"
            "async function atlasSessionPreset(page: any, preset: any) {\n"
            "  // 契约 §5.5 `会话:`：在**首屏文档起始前**把预设会话键值写进 sessionStorage。\n"
            "  // 为何是 sessionStorage 而不是 localStorage：storageState 只覆盖 localStorage，\n"
            "  // 而 localStorage 跳标签页 / 跳用例持续 ⇒ 会污染后续用例（含「不传参 ⇒ 保持可用」\n"
            "  // 类对照用例）；sessionStorage 天然按 tab / context 隔离。addInitScript 保证\n"
            "  // 每个新文档起始即生效（本调用必须在 `page.goto` 之前）。\n"
            "  // 取值优先级（Q2-C 裁定）：运行期环境变量 > 用例声明值；两者皆空 ⇒ 报错中止。\n"
            "  const resolved: Record<string, string> = {};\n"
            "  for (const [k, spec] of Object.entries(preset as Record<string, any>)) {\n"
            "    const fromEnv = process.env[(spec as any).env];\n"
            "    const value = fromEnv && fromEnv.length > 0 ? fromEnv : (spec as any).value;\n"
            "    if (!value) {\n"
            "      throw new Error(`会话预设 ${k} 无取值：用例未声明且环境变量 ${(spec as any).env} 未设置 ⇒ 拒绝以默认态续跑（假绿）`);\n"
            "    }\n"
            "    resolved[k] = value;\n"
            "  }\n"
            "  await page.addInitScript((kv: Record<string, string>) => {\n"
            "    for (const [k, v] of Object.entries(kv)) { try { window.sessionStorage.setItem(k, v); } catch { /* 忽略 */ } }\n"
            "  }, resolved);\n"
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
            "        // null（元素不可见/求值异常——如 Tab 未展开的面板）⇒ 跳过；\n"
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
            "// 契约 §5.5：`download` 的 glob 语义（`*` 任意串 / `?` 单字符）\n"
            "function atlasGlob(pattern) {\n"
            r"  return new RegExp('^' + pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&')"
            ".replace(/\\*/g, '.*').replace(/\\?/g, '.') + '$');\n"
            "}\n"
            "async function atlasDownload(page, tid, pattern, nth = 0) {\n"
            "  const [download] = await Promise.all([\n"
            "    page.waitForEvent('download', { timeout: ATLAS_WAIT_TIMEOUT_MS }),\n"
            "    page.getByTestId(tid).nth(nth).click(),\n"
            "  ]);\n"
            "  const name = download.suggestedFilename();\n"
            "  expect(name, `下载文件名 ${name} 不匹配 ${pattern}`).toMatch(atlasGlob(pattern));\n"
            "}\n\n"
            + (ts_mock_helpers(mock_prefix, mock_mode) if (page_has_mocks := any(c.get("_mock") for c in items)) else "")
            + ts_zero_step_baseline(page, url, items, mock_vacuous=page_has_mocks) + "\n"
            + "\n".join(ts_case(c, url, base or "", esm_project) for c in items)
        )
        write(scripts_dir / f"{page}{ext}", body, args.apply, results)
        # runner 切换后清理另一扩展名的旧页面脚本（否则双份同语义产物互斥漂移）
        other_ext = ".py"  # 单轨化（3507 BO）：清理旧 python 运行器残留页脚本
        stale = scripts_dir / f"{page}{other_ext}"
        if stale.is_file():
            stale.unlink()
            results.append({"file": str(stale) + "（旧 runner 清理）", "changed": True})
        generated += 1

    # 退役页清扫（F9，2026-10-14）：用例目录已不再枚举、但生成物仍留在 scripts_dir 的页脚本
    # —— Playwright 默认 glob 会在真跑时拾起它（R3 实测 2 failed）。只清带 AUTO-GENERATED
    # 头标记的生成物，绝不碰手写资产；dry-run 同样记 changed ⇒「生成物最新」门可见并
    # 明确要求 `--apply` 收口。
    for f in sorted(scripts_dir.glob(f"*{ext}")):
        retired_page = f.name[: -len(ext)]
        if retired_page in cases:
            continue
        try:
            head = f.read_text(encoding="utf-8")[:400]
        except OSError:
            continue
        if "AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py" not in head:
            continue
        if args.apply:
            f.unlink()
            results.append({"file": str(f) + "（退役页清扫）", "changed": True})
        else:
            results.append({"file": str(f) + "（退役页残留）", "changed": True})

    # 运行器原生配置：承载 baseURL（不硬编码在用例脚本里）
    # node 运行器全机制版（2026-09-30 拉平）：storageState 预置登录（setup 项目）、
    # auth:none 由用例 describe 内 test.use 覆盖（ts_case 渲染）。
    # mode: none（2026-10-16，RFC-20261015-02）：靶场无访问门 ⇒ 不生成「setup 项目 +
    # storageState」设施 —— 无门项目里那套编排没有被编排的对象（B124 同族教训：
    # 外加编排是对原设计的稀释）。用例级 `auth: none` 依然成立：describe 内 test.use
    # 显式给空 storageState，不依赖全局预置。
    state_rel = ".atlas-auth/state.json"
    if login_mode == "none":
        cfg = (
            "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py；重跑覆盖。\n"
            "import { defineConfig } from '@playwright/test';\n\n"
            "// app_login.mode=none（契约 shared/stack-profile.md §2 / rings/e2e §7.1）：\n"
            "// 靶场无访问门 ⇒ 无登录预置设施（setup 项目与 storageState 均不生成）。\n"
            "// 未登录前提的用例（auth: none）自带空 storageState，不依赖全局预置。\n"
            "export default defineConfig({\n"
            "  reporter: [\n"
            "    ['list'],\n"
            "    ['json', { outputFile: '.atlas-run/results.json' }],\n"
            "  ],\n"
            "  outputDir: '.atlas-run',\n"
            "  // 契约 rings/e2e §7.1（用例执行必须串行 = 并发 1，DESIGN D115）：零步基线必须先于改态用例，\n"
            "  // 并行调度会乱序 ⇒ 恒真误报 / 前提被前序用例污染。\n"
            "  workers: 1,\n"
            "  fullyParallel: false,\n"
            "  // 契约 rings/e2e §7（2026-10-17，issue #28 / `DESIGN.md` D105）：**断言超时的显式下限**。\n"
            "  // Playwright 的 expect 默认只等 5s；SPA 首屏（dev bundle 可达 10MB+，现场实测某项目 14s）\n"
            "  // 会因此把「元素还没渲染」误判成「元素不存在」= **假红**（本轮实测：接口全对、元素真在，却\n"
            "  // 3 failed 1 passed）。提升到 20s（仍远小于 test 超时），并留 `ATLAS_EXPECT_TIMEOUT` 覆盖口。\n"
            "  expect: { timeout: Number(process.env.ATLAS_EXPECT_TIMEOUT ?? 20_000) },\n"
            f"  use: {{ baseURL: process.env.ATLAS_BASE_URL ?? '{base}',\n"
            "    // 失败留证（2026-10-18，RFC-20261018-01）：失败才落 test-results/，全绿轮零产物；\n"
            "    // 生效咬合点 = 重装配（install --update / 首装），不溯及已装配副本。\n"
            "    trace: 'retain-on-failure',\n"
            "    screenshot: 'only-on-failure',\n"
            "    launchOptions: { slowMo: Number(process.env.ATLAS_SLOWMO || 0) } },\n"
            "  projects: [\n"
            "    { name: 'chromium',\n"
            "      use: { ...(process.env.ATLAS_PLAYWRIGHT_CHANNEL ? { channel: process.env.ATLAS_PLAYWRIGHT_CHANNEL } : {}) },\n"
            "    },\n"
            "  ],\n"
            "});\n"
        )
    else:
        cfg = (
            "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py；重跑覆盖。\n"
            "import { defineConfig } from '@playwright/test';\n\n"
            "// 会话预置登录（契约 §5.7 / §5.4）：setup 项目真实登录一次 → state 文件；\n"
            "// 凭据来自运行期环境变量 ATLAS_APP_USER / ATLAS_APP_PASSWORD（不读项目 .env、不硬编码）；\n"
            "// 未设置 ⇒ setup 写空 state 并警告（不静默）；换取失败 ⇒ setup 抛错中止（不静默续跑）。\n"
            "export default defineConfig({\n"
            "  reporter: [\n"
            "    ['list'],\n"
            "    ['json', { outputFile: '.atlas-run/results.json' }],\n"
            "  ],\n"
            "  outputDir: '.atlas-run',\n"
            "  // 契约 rings/e2e §7.1（用例执行必须串行 = 并发 1，DESIGN D115）：零步基线必须先于改态用例，\n"
            "  // 并行调度会乱序 ⇒ 恒真误报 / 前提被前序用例污染。\n"
            "  workers: 1,\n"
            "  fullyParallel: false,\n"
            "  // 契约 rings/e2e §7（2026-10-17，issue #28 / `DESIGN.md` D105）：**断言超时的显式下限**。\n"
            "  // Playwright 的 expect 默认只等 5s；SPA 首屏（dev bundle 可达 10MB+，现场实测某项目 14s）\n"
            "  // 会因此把「元素还没渲染」误判成「元素不存在」= **假红**（本轮实测：接口全对、元素真在，却\n"
            "  // 3 failed 1 passed）。提升到 20s（仍远小于 test 超时），并留 `ATLAS_EXPECT_TIMEOUT` 覆盖口。\n"
            "  expect: { timeout: Number(process.env.ATLAS_EXPECT_TIMEOUT ?? 20_000) },\n"
            f"  use: {{ baseURL: process.env.ATLAS_BASE_URL ?? '{base}',  // E1 单段\n"
            "    // 失败留证（2026-10-18，RFC-20261018-01）：失败才落 test-results/，全绿轮零产物；\n"
            "    // 生效咬合点 = 重装配（install --update / 首装），不溯及已装配副本。\n"
            "    trace: 'retain-on-failure',\n"
            "    screenshot: 'only-on-failure',\n"
            "    // F11（2026-10-14）：慢动作经 `ATLAS_SLOWMO` 注入——Playwright `test` CLI 无\n"
            "    // `--slowmo` 旗标（1.64 实测 unknown option）；未设 ⇒ 0，行为与原生一致。\n"
            "    launchOptions: { slowMo: Number(process.env.ATLAS_SLOWMO || 0) } },\n"
            "  projects: [\n"
            "    { name: 'setup', testMatch: /atlas-auth[.]setup[.]ts/ },\n"
            "    {\n"
            "      name: 'chromium',\n"
            "      dependencies: ['setup'],\n"
            "      use: { storageState: "
            + json.dumps(state_rel)
            + ", ...(process.env.ATLAS_PLAYWRIGHT_CHANNEL ? { channel: process.env.ATLAS_PLAYWRIGHT_CHANNEL } : {}) },\n"
            "    },\n"
            "  ],\n"
            "});\n"
        )
    write(scripts_dir / "playwright.config.ts", cfg, args.apply, results)

    # atlas-hold.ts（契约 §10.1，2026-10-12 控制台 node 轨迁移批）：页面脚本的 test/expect
    # 引入源——承载控制台「跑完留窗（人工 review）+ 结果哨兵」。py 时代该语义活在 conftest.py，
    # node 轨等价载体 = auto fixture（依赖 context ⇒ teardown 先于内置 context 关闭 ⇒ 可等人工关窗）。
    # 两环境变量都未设（直跑 / atlas_check 真跑门）⇒ 行为与 @playwright/test 原生一致。
    hold_ts = (
        "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py；重跑覆盖。\n"
        "import { test as base, expect } from '@playwright/test';\n"
        "import { writeFileSync } from 'node:fs';\n"
        "export * from '@playwright/test';\n\n"
        "// 契约 rings/e2e/reference.md §10.1：控制台逐条执行的两条运行期语义——\n"
        "//   ATLAS_RESULT_FILE：结果哨兵（持窗期间进程活着，控制台不能靠进程退出码判结果）；\n"
        "//   ATLAS_KEEP_OPEN=1：跑完**不自动关浏览器**，留给人手动 review（用户 2026-09-23 定）。\n"
        "const test = base.extend<{ atlasHold: void }>({\n"
        "  atlasHold: [async ({ context }, use, testInfo) => {\n"
        "    await use();\n"
        "    if (process.env.ATLAS_RESULT_FILE) {\n"
        "      try {\n"
        "        writeFileSync(process.env.ATLAS_RESULT_FILE,\n"
        "          JSON.stringify({ exitstatus: testInfo.status === 'passed' ? 0 : 1 }));\n"
        "      } catch { /* 哨兵写失败 ⇒ 控制台回落进程退出码 */ }\n"
        "    }\n"
        "    if (process.env.ATLAS_KEEP_OPEN !== '1') return;\n"
        "    // 留窗：本 fixture 依赖 context ⇒ teardown 先于内置 context 关闭；\n"
        "    // 轮询等人工关窗（关页 ⇒ pages 空；关整个浏览器 ⇒ 断连）再放行。\n"
        "    await new Promise<void>((resolve) => {\n"
        "      const timer = setInterval(() => {\n"
        "        let done = false;\n"
        "        try {\n"
        "          const b = context.browser();\n"
        "          done = context.pages().length === 0 || !b || !b.isConnected();\n"
        "        } catch {\n"
        "          done = true;\n"
        "        }\n"
        "        if (done) { clearInterval(timer); resolve(); }\n"
        "      }, 250);\n"
        "    });\n"
        "  }, { auto: true }],\n"
        "});\n"
        "export { test, expect };\n"
    )
    write(scripts_dir / "atlas-hold.ts", hold_ts, args.apply, results)
    # fabricated 段只要求 storage_key（§5.8）⇒ 其余取证键用 .get 兜默认，不假设存在。
    body_format = (app_login or {}).get("body_format") or "form"
    endpoint = (app_login or {}).get("endpoint") or "/login"
    user_field = (app_login or {}).get("username_field") or "username"
    pass_field = (app_login or {}).get("password_field") or "password"
    token_key = (app_login or {}).get("token_key") or "access_token"
    storage_key = (app_login or {}).get("storage_key") or "access_token"
    setup_ts: str | None = None
    if login_mode == "none":
        # RFC-20261015-02（issue #11）：靶场无访问门 ⇒ 无登录预置设施 —— setup 不生成，
        # 运行器配置也不含 setup 项目 / storageState（见上文 cfg 的 none 分支）。
        pass
    elif login_mode == "fabricated":
        # 契约 §5.8（2026-10-12）：纯前端桩项目 —— 不发真实登录请求，直写假令牌。
        # 真实登录语义（换取失败 ⇒ 报错中止）只属 real；fabricated 无凭据面、无网络面。
        # 幂等守卫：文件存在且非空时跳过覆写，保护开发者录制的真实会话。
        setup_ts = (
            "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py；重跑覆盖。\n"
            "import { test } from '@playwright/test';\n"
            "import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';\n"
            "import { dirname } from 'node:path';\n\n"
            "test('atlas auth setup', async () => {\n"
            f"  const storageKey = {json.dumps(storage_key)};\n"
            f"  const stateFile = {json.dumps(state_rel)};\n"
            "  if (existsSync(stateFile)) {\n"
            "    try {\n"
            "      const existing = readFileSync(stateFile, 'utf-8');\n"
            "      if (existing.trim() && JSON.parse(existing)) {\n"
            "        console.log('[atlas] 保留已有登录态文件，跳过覆写: ' + stateFile);\n"
            "        return;\n"
            "      }\n"
            "    } catch { /* 损坏文件则重新生成 */ }\n"
            "  }\n"
            "  console.warn('[atlas] app_login.mode=fabricated：不发真实登录请求，"
            "直写固定假令牌（纯前端桩项目，契约 §5.8）');\n"
            "  const origin = process.env.ATLAS_BASE_URL ?? " + json.dumps(base) + ";\n"
            "  const state = {\n"
            "    cookies: [] as unknown[],\n"
            "    origins: [{ origin, localStorage: [{ name: storageKey, value: 'atlas-fabricated-token' }] }],\n"
            "  };\n"
            "  mkdirSync(dirname(stateFile), { recursive: true });\n"
            "  writeFileSync(stateFile, JSON.stringify(state));\n"
            "});\n"
        )
    else:
        request_post_code = (
            "  let resp;\n"
            "  try {\n"
            "    resp = await request.post(endpoint, {\n"
            "      headers: { 'content-type': 'application/json' },\n"
            "      data: JSON.stringify({ [userField]: user, [passField]: password }),\n"
            "    });\n"
            "  } catch (err: any) {\n"
            "    throw new Error(`[atlas] 应用靶场登录请求发送失败: ${err?.message || err}；端点 ${endpoint}`);\n"
            "  }\n"
            if body_format == "json" else
            "  const form = new URLSearchParams({ [userField]: user, [passField]: password });\n"
            "  let resp;\n"
            "  try {\n"
            "    resp = await request.post(endpoint, {\n"
            "      headers: { 'content-type': 'application/x-www-form-urlencoded' },\n"
            "      data: form.toString(),\n"
            "    });\n"
            "  } catch (err: any) {\n"
            "    throw new Error(`[atlas] 应用靶场登录请求发送失败: ${err?.message || err}；端点 ${endpoint}`);\n"
            "  }\n"
        )
        setup_ts = (
            "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py；重跑覆盖。\n"
            "import { test, expect } from '@playwright/test';\n"
            "import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';\n"
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
            "  if (process.env.ATLAS_FORCE_LOGIN !== '1' && existsSync(stateFile)) {\n"
            "    try {\n"
            "      const existing = readFileSync(stateFile, 'utf-8');\n"
            "      const parsed = JSON.parse(existing.trim());\n"
            "      if (parsed && (Array.isArray(parsed.cookies) || Array.isArray(parsed.origins)) && (parsed.cookies?.length > 0 || parsed.origins?.length > 0)) {\n"
            "        console.log('[atlas] 保留已有登录态文件（如 codegen 产物），跳过覆写: ' + stateFile);\n"
            "        return;\n"
            "      }\n"
            "    } catch { /* 损坏文件则重新生成 */ }\n"
            "  }\n"
            "  if (!user || !password) {\n"
            "    console.warn('[atlas] 警告：未设置 ATLAS_APP_USER/ATLAS_APP_PASSWORD ⇒ 跳过登录预置（需要登录态的用例会失败）');\n"
            "    mkdirSync(dirname(stateFile), { recursive: true });\n"
            "    writeFileSync(stateFile, JSON.stringify({ cookies: [], origins: [] }));\n"
            "    return;\n"
            "  }\n"
            f"{request_post_code}"
            "  if (!resp.ok()) {\n"
            "    let bodySnippet = '';\n"
            "    try { bodySnippet = (await resp.text()).slice(0, 200); } catch {}\n"
            "    throw new Error(`[atlas] 应用靶场登录失败（HTTP ${resp.status()}）：核对服务可达 / ATLAS_APP_USER·ATLAS_APP_PASSWORD / 端点 ${endpoint}。响应=${bodySnippet}`);\n"
            "  }\n"
            "  let body: any;\n"
            "  try {\n"
            "    body = await resp.json();\n"
            "  } catch (err: any) {\n"
            "    let rawText = '';\n"
            "    try { rawText = (await resp.text()).slice(0, 200); } catch {}\n"
            "    throw new Error(`[atlas] 登录端点响应不是合法的 JSON（HTTP ${resp.status()}）：${rawText}`);\n"
            "  }\n"
            "  const token = tokenKey.split('.').reduce((acc: any, k: string) => acc?.[k], body);\n"
            "  if (!token || typeof token !== 'string') {\n"
            "    throw new Error(`[atlas] 登录响应无法通过键 '${tokenKey}' 提取到有效令牌字符串: 实际值=${JSON.stringify(token)}。响应体=${JSON.stringify(body).slice(0, 200)}`);\n"
            "  }\n"
            "  const origin = process.env.ATLAS_BASE_URL ?? " + json.dumps(base) + ";\n"
            "  const state = {\n"
            "    cookies: [] as unknown[],\n"
            "    origins: [{ origin, localStorage: [{ name: storageKey, value: token }] }],\n"
            "  };\n"
            "  mkdirSync(dirname(stateFile), { recursive: true });\n"
            "  writeFileSync(stateFile, JSON.stringify(state));\n"
            "});\n"
        )
    if login_mode != "none":
        # none ⇒ 无登录预置设施，atlas-auth.setup.ts 不生成（configured 分支见上）。
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
        seed = support / "hooks.ts"
        seed.write_text(
            "// 自定义深断言钩子放这里（生成器不覆盖本目录）。\n"
        , encoding="utf-8")

    out = {"root": str(root), "runner": runner, "base_url": base,
           "apply": args.apply, "generated": generated, "results": results,
           "review_gate": {"ok": gate_ok, "reasons": gate_reasons, "auto_healed": will_auto_heal}}
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
