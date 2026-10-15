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
  * 运行器 = `node-playwright` 单轨（2026-10-09 `3507 BO` 单轨化，原 `§B201-4`；`python-playwright` 已退役——声明即拒）；
  * **派生、可重生成**：重跑覆盖同页脚本与运行器配置；`_support/` 永不覆盖。
  * **`atlas-hold.ts`（§10.1，2026-10-12 控制台 node 轨迁移批）**：页面脚本经它引入
    `test` / `expect`——承载控制台「跑完留窗（ATLAS_KEEP_OPEN）+ 结果哨兵
    （ATLAS_RESULT_FILE）」；环境变量未设时行为与 `@playwright/test` 原生一致。
    py 时代等价物 = conftest.py（已随单轨化退役）。
  * **预置登录态**：以**真实登录**预置会话——端点 / 表单字段名 / 令牌键 / 存储键 = 取证值，
    登记在 `e2e.app_login` 段
    （段缺失 = 合法降级：跳过预置 + 明确警告；字段不齐 ⇒ 生成报错）；凭据只来自运行期
    环境变量 `ATLAS_APP_USER` / `ATLAS_APP_PASSWORD`（不读项目 `.env`、不硬编码）；
    未设置 ⇒ 跳过预置 + 明确警告；换取令牌失败 ⇒ 报错中止
    （不得静默续跑——那会退化成「未登录态跑用例」的假绿）。
    `app_login.mode: fabricated`（§5.8，2026-10-12）= 纯前端桩项目形态：不发真实登录请求，
    setup 直写固定假令牌进 storageState（必填收窄为 `storage_key`）。
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
**3** 前置未声明（`e2e.app_base_url` 为空）—— **3 不是失败**：调用方应判「未就绪」而不是「生成失败」，
且 `--json` 下 stdout 给出 `{"ok": false, "not_ready": "app_base_url", …}`。
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

CASE_BLOCK = re.compile(r"```atlas-case\s*\n(.*?)```", re.S)
RUNNERS = {"node-playwright": ".spec.ts"}  # 单轨（3507 BO）：python-playwright 已退役
# 前置未声明（例：`e2e.app_base_url` 为空）的**独立退出码**（`3509 §B110`）：
# 与真错（2）分开 ⇒ 调用方（`atlas_check`）判 **SKIP（未就绪）** 而不是 FAIL。
# 同一根因曾被判成两种结论（`E2E 真跑`=SKIP、`生成物最新`=FAIL）⇒ 永久红门 = 静音门（`§106`）。
NOT_READY = 3
# e2e.app_login 段的必填字段（段缺失 = 合法降级；段存在则须齐全，3509 §B101）
APP_LOGIN_FIELDS = ("endpoint", "username_field", "password_field", "token_key", "storage_key")
# e2e.app_login.mode（契约 §5.8/§7.1，2026-10-12）：real（缺省 = 真实登录语义）/
# fabricated（纯前端桩项目：setup 直写假令牌，必填收窄为 storage_key）。
APP_LOGIN_MODES = ("real", "fabricated")
# 网络边界打桩（契约 §5.8，2026-10-12）：`mock:` 行的方法枚举（行式语法见 parse_mock_line）。
MOCK_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# 分片 step / expected 的动词词表（契约 `rings/e2e/reference.md` §5.5，2026-09-23 定）
ACTION_VERBS = ("click", "fill", "select", "check", "uncheck", "press", "hover", "refresh", "goto", "waitFor", "download", "upload")
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
    code, _, _note = line.partition("#")
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


def ts_case(case: dict, url: str) -> str:
    cid = case["id"]
    ids = json.dumps(case.get("testid") or [], ensure_ascii=False)
    step_note = "\\n".join("//   - " + s for s in case.get("step", []))
    assert_note = "\\n".join("//   - " + s for s in case.get("expected", []))
    # 契约 §5.7（2026-09-30）：blocked/skipped ⇒ test.skip（状态真相源 = 索引）。
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
            # 契约 §7.1：带轮询的断言（不得退化为固定等待）
            loc = f"page.getByTestId('{tid}')"
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
            actions.append(
                f"await atlasDownload(page, '{tid}', {json.dumps(value, ensure_ascii=False)});"
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
            actions.append(
                f"await page.getByTestId('{tid}').setInputFiles("
                f"resolve(__dirname, '..', 'fixtures', {json.dumps(rel, ensure_ascii=False)}));"
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
            # 契约 §5.5（契约 §5.5）：值写作 `""` / `(空)` 时是**空串**，
            # 必须渲染成空串实参 —— 直接 json.dumps 会得到两个字面引号字符，
            # 与真实空串永不相等。（B173-1：断言经 atlasExpectValue 实现无关化。）
            if value.strip() in ('""', "(空)"):
                v = json.dumps("", ensure_ascii=False)
            line = f"await atlasExpectValue(page, '{tid}', {v});"
        elif verb == "countOptions":
            # 契约 §5.5（契约 §5.5）：数该元素内的 `option` 子元素个数。
            line = f"await expect(page.getByTestId('{tid}').locator('option')).toHaveCount(Number({v}));"
        elif verb == "checked":
            line = f"await expect(page.getByTestId('{tid}')).toBeChecked();"
        elif verb == "unchecked":
            line = f"await expect(page.getByTestId('{tid}')).not.toBeChecked();"
        elif verb == "attr":
            # 契约 §5.5（契约 §5.5）：`attr <testid> <name> <value>`。
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
    # 组装顺序：（每条 step + 它身后的锚断言）→ 终态断言；行动前断言（unchanged pre +
    # delta 采样）贴**第一个提交性动作**（§5.6 R9 / §B55——放所有 step 之前会把准备步骤
    # 未执行时的不可见元素误判成自相矛盾）；无提交性动作时退回第一个 step 之前
    # （校验器对此 FAIL，此处保持保守位置）。`actions` 与 `step` 一一对应，按序号对位。
    delta_pos = next((i for i, s in enumerate(case.get("step", []), start=1)
                      if any(w in s.split("#", 1)[0] for w in SUBMITTING_WORDS)), 1)
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
    body = (
        f"test({json.dumps(cid + ' ' + (case.get('_title') or ''), ensure_ascii=False)}, async ({{ page }}) => {{\n"
        f"  {step_note}\n  {assert_note}\n"
        f"{mock_open}"
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

    用例断言与零步基线**共用**本函数 —— 两条路径的断言语义因此不可能漂（复用而非复制）。
    表达式求值环境 = 页面文件 header 的 `tsVis` / `tsVisible` / `page`。
    """
    _, line = split_prefix(line)
    verb, tid, value, _note = parse_line(line)
    v = json.dumps(value, ensure_ascii=False)
    t = json.dumps(tid, ensure_ascii=False)
    if verb == "text":
        # 元素不可见 ⇒ **null**（基线 runner 跳过，不是 false）
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
        crit = [c for c in (data.get("checks") or []) if c.get("level") == "Critical"]
        return "critical", f"{d.name} 含 {len(crit)} 条 Critical"

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
    v0.1.0-beta.14 自愈与免阻断：当审查报告缺失（missing）或损坏（invalid）时，若处于 `origin: adopt`
    或 `e2e.review.mode` 为 auto-baseline / off / 未声明（review 为空）时，
    判定为放行并标记 `auto_heal=True`，绝不因报告缺失抛 exit 2 阻断写盘。
    当处于基线兜底态（level == 'baseline'）时，同样放行但记录 WARN 随行提示。
    返回 `(gate_ok, reasons, auto_heal)`。
    """
    reasons: list[str] = []
    level, detail = review_report_status(root / "product" / "e2e" / REVIEW_DIRNAME)
    origin = prof.get("origin") if prof else None
    e2e = prof.get("e2e") if prof else {}
    rev = e2e.get("review") if isinstance(e2e, dict) else None
    mode = rev.get("mode") if isinstance(rev, dict) else (rev if isinstance(rev, str) else None)

    has_empty_review = ("review" in e2e and rev is None)
    is_auto_baseline = (mode in ("auto", "auto-baseline", "off"))

    if level == "baseline":
        reasons.append(f"WARN: 独立审查未执行（基线报告兜底中：{detail}）—— 跑 python3 .atlas/scripts/gen_e2e_scripts.py --bootstrap-review 拉起独立审查")
        return True, reasons, False

    if level in ("missing", "invalid"):
        # adopt 模式、显式 review: null（review 为空）或配置为 auto-baseline/off 时自愈放行
        if origin == "adopt" or has_empty_review or is_auto_baseline:
            reasons.append(f"NOTICE: 审查报告处于 {level} 态，处于 adopt 模式或 review 免阻断通道，已启用自动自愈基线（rings/e2e §12.6）")
            return True, reasons, True

    if level != "ok":
        reasons.append(f"E2E 环审查报告不合格（{level}）：{detail}"
                       "（跑 rings/e2e/reference.md §12）")
    return (not reasons), reasons, False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--bootstrap-review", action="store_true",
                    help="输出机器可读的独立审查任务包 JSON（rings/e2e §12.6）并退出")
    args = ap.parse_args()
    root = Path(args.root).resolve()

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
    login_mode = (app_login or {}).get("mode") or "real"
    if app_login is not None and login_mode not in APP_LOGIN_MODES:
        print(f"ERROR: e2e.app_login.mode 非法: {login_mode!r}（允许 {list(APP_LOGIN_MODES)}；缺省 real）"
              "——契约见 shared/stack-profile.md §2 + rings/e2e/reference.md §5.8", file=sys.stderr)
        return 2
    if app_login is not None:
        # fabricated（契约 §5.8，2026-10-12）：纯前端桩项目——不发真实登录请求，
        # setup 直写假令牌 ⇒ 必填收窄为 storage_key（其余取证字段无消费方）。
        required = ("storage_key",) if login_mode == "fabricated" else APP_LOGIN_FIELDS
        missing = [k for k in required if not (app_login.get(k) or "").strip()]
        if missing:
            print(f"ERROR: e2e.app_login 段不完整（mode={login_mode}，缺 {missing}）——要么补齐，"
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
                    first = raw.split("#", 1)[0].strip().split(" ", 1)[0].strip()
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
        url = urls[page]
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
            + ("import { resolve } from 'node:path';\n" if page_uses_upload else "")
            + "// 契约 §7.1：`waitFor` 的超时默认值（与 python 侧同值）\n"
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
            "  // 找不到数值即响亮失败（永不静默当 0 处理）。\n"
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
            "async function atlasDownload(page, tid, pattern) {\n"
            "  const [download] = await Promise.all([\n"
            "    page.waitForEvent('download', { timeout: ATLAS_WAIT_TIMEOUT_MS }),\n"
            "    page.getByTestId(tid).click(),\n"
            "  ]);\n"
            "  const name = download.suggestedFilename();\n"
            "  expect(name, `下载文件名 ${name} 不匹配 ${pattern}`).toMatch(atlasGlob(pattern));\n"
            "}\n\n"
            + (ts_mock_helpers(mock_prefix, mock_mode) if (page_has_mocks := any(c.get("_mock") for c in items)) else "")
            + ts_zero_step_baseline(page, url, items, mock_vacuous=page_has_mocks) + "\n"
            + "\n".join(ts_case(c, url) for c in items)
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
    state_rel = ".atlas-auth/state.json"
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
        "  // 契约 rings/e2e §8：执行一次一条（并发 = 1）。零步基线必须先于改态用例，\n"
        "  // 并行调度会乱序 ⇒ 恒真误报 / 前提被前序用例污染。\n"
        "  workers: 1,\n"
        "  fullyParallel: false,\n"
        f"  use: {{ baseURL: process.env.ATLAS_BASE_URL ?? '{base}',  // E1 单段\n"
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
    endpoint = (app_login or {}).get("endpoint") or "/login"
    user_field = (app_login or {}).get("username_field") or "username"
    pass_field = (app_login or {}).get("password_field") or "password"
    token_key = (app_login or {}).get("token_key") or "access_token"
    storage_key = (app_login or {}).get("storage_key") or "access_token"
    if login_mode == "fabricated":
        # 契约 §5.8（2026-10-12）：纯前端桩项目 —— 不发真实登录请求，直写假令牌。
        # 真实登录语义（换取失败 ⇒ 报错中止）只属 real；fabricated 无凭据面、无网络面。
        setup_ts = (
            "// AUTO-GENERATED by atlas scripts/gen_e2e_scripts.py；重跑覆盖。\n"
            "import { test } from '@playwright/test';\n"
            "import { mkdirSync, writeFileSync } from 'node:fs';\n"
            "import { dirname } from 'node:path';\n\n"
            "test('atlas auth setup', async () => {\n"
            f"  const storageKey = {json.dumps(storage_key)};\n"
            f"  const stateFile = {json.dumps(state_rel)};\n"
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
