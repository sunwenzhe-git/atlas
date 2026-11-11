#!/usr/bin/env python3
"""atlas 校验器 —— E2E 总索引（结构门 FAIL + 有意义门 FAIL/WARN）。

按 `rings/e2e/reference.md` §8.2：
  结构门：索引与列头、ID 唯一、行字段、分片链接可达、**索引↔分片标题一致**、分片块字段齐、
          无孤儿/死链、`pages` 合法、反向视图一致、词表、`关联AC` 格式与可达；
  有意义门：空/占位 FAIL，不可判定/纯跳转/瞬时断言/未复断言/“或”式/文案来源/**`initial:` 无理由** WARN，
          `intent` 缺失/模糊 FAIL、过短 WARN，断言数 <1 FAIL，`skipped` 无原因 FAIL。

主表列头见 `MAIN_COLUMNS`（契约 §3.2）。**无 `执行目标` 列**（2026-09-23 退役：原型补 mock
后端层后全部用例都能在原型期执行，该字段退化为常量；见契约 §5.4 / §10）。

- **框架无关**：本文件不得出现任何具体框架名。纯标准库。
- 判定：`PASS`/`WARN` → 退出码 0；`FAIL` → 1；门控态记 `N/A`。

启发式说明（契约明确划为「语义交 agent」的项不进本校验器；下列为可确定性判定的近似）：
  * 「纯跳转步骤」「瞬时断言」「持久化未复断言」「文案来源」按关键词/形态近似 → WARN。
  * 「持久化未复断言」的「写」按**提交性控件的 testid 语义段**近似，并执行契约 §5.6 R2 的
    例外 ①（expected 出现拒绝态 ⇒ 什么都没写）与例外 ②（登录 / 登出属鉴权）。
    **本项只判形态（用例里是否含 `refresh` 步骤），不构成契约 §5.6 R2 的证明** ——
    契约 §6.0 的 `C-new` 已把 R2 / R4 的判据归到**运行期门**（每页的 `test_<page>__zero_step_baseline`，
    契约 §5.6 R9）：能在初始态成立的断言不构成验证，而「初始态」文本期看不到。
  * 「goto 查询键须已声明」为**结构门 FAIL**（契约 §5.7 / §5.5 `参数:`，**2026-10-18 重靶**）：
    `goto` **可以**带查询串，但每个键必须同时满足 ① ∈ `e2e.query_preset.keys` **∧** ② ∈ 本用例
    `参数:` 声明；否则 FAIL。原靶仍在 FAIL 面内：原型专有的 `?state=` 那类**未声明**调试参数
    （= 「数据态直达」形态）照样红。重靶理由与取证见 `DESIGN.md` D109。
  * 「断言不自相矛盾」为**结构门 FAIL**（契约 §5.6 R7）：同一 testid 既断可见又断不可见，
    必有一条永远为真（假绿）——只能靠「一个可判定终态 = 一条用例」拆开。
  * `expected` 行首的 `initial:` 前缀（契约 §5.6 R9 的显式豁免通道）在判动词前剥离；
    `initial:` 后仍须是合法断言动词，否则仍记 FAIL。

用法：
    python3 validate_e2e_index.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import LayoutError, load_layout  # noqa: E402


def _format_list(items: list[str], max_show: int = 20) -> str:
    if not items:
        return ""
    if len(items) <= max_show:
        return f"{items}"
    return f"{items[:max_show]} (共 {len(items)} 项，截断前 {max_show} 项)"


def _fix(root: Path, action: str) -> str:
    cmd = ("python3 .atlas/scripts/atlas_check.py --fast"
           if (root / ".atlas/scripts/atlas_check.py").is_file()
           else "python3 scripts/atlas_check.py --fast")
    return f"｜修复: {action}｜复跑: {cmd}"

# 随包内核引导（`_support/`，2026-10-12 单源批）：用例块解析取 `_support/case_block.py`
# 单源实现（原与 gen_e2e_scripts 逐字节双拷贝；本文件被控制台经内核加载，见 _support/siblings.py）。
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.siblings import load_module  # noqa: E402


def _solution_root(root: Path) -> bool:
    """父仓模式（RFC-20261108-02）：`atlas.solution.yaml` 存在且 `mode: federated`。"""
    p = root / "atlas.solution.yaml"
    if not p.is_file():
        return False
    try:
        return re.search(r"^mode:\s*federated\s*$", p.read_text(encoding="utf-8"),
                         re.M) is not None
    except OSError:
        return False


def _declares_case_ids(root: Path) -> bool:
    p = root / "atlas.solution.yaml"
    if not p.is_file():
        return False
    try:
        return re.search(r"^\s+case_ids:\s*\S", p.read_text(encoding="utf-8"),
                         re.M) is not None
    except OSError:
        return False


def _ac_cell_ok(cell: str) -> bool:
    """`关联AC` 单元格合法 = 非空且**每个** token 整串匹配 AC 文法（逐 token，不整格 match）。"""
    tokens = split_acs(cell)
    return bool(tokens) and all(AC_RE.fullmatch(t) for t in tokens)


def _ac_unreachable(cell: str, source) -> bool:
    """单元格内**任一** token 不可达即判不可达（`source` = AC 定义集或 PRD 全文）。"""
    tokens = split_acs(cell)
    return not tokens or any(t not in source for t in tokens)


def _reader_version(root: Path) -> str:
    """工具自身版本（RFC §5.3 / v11 重要 3）：`reader_version` 不得由被检查仓决定。

    候选固定三条（全部是**工具自身**来源，被检查仓 `<root>/package.json` 不参与）：
    1. `<root>/.atlas/VERSION` —— 装配副本的版本戳；旧副本只有摘要形态 ⇒ 跳过；
    2. `<root>/.atlas/package.json` —— 装配副本自带的本包 `package.json`；
    3. `<工具包根>/package.json` —— 开发树（`validators/` 在包根下）与安装副本的兜底。
    中间级不可解析只继续回落，不提前判 unknown；三级全缺 ⇒ 返回 `""`，调用方记
    `reader_version_unknown` 并一律按 WARN 分级。第三级固定为工具包根 `package.json`
    （RFC v12 明确不再新增 `_support/_version.py`）。
    """
    candidates: list[Path] = [Path(root) / ".atlas" / "VERSION",
                              Path(root) / ".atlas" / "package.json",
                              Path(__file__).resolve().parents[1] / "package.json"]
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.name == "package.json":
            try:
                text = str(json.loads(text).get("version") or "")
            except ValueError:
                continue
        version = text.strip()
        if re.match(r"^v?\d+\.\d+\.\d+", version):
            return version
    return ""


def _version_at_least(version: str, target: tuple[int, int, int]) -> bool:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", version or "")
    if m is None:
        return False
    base = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if base != target:
        return base > target
    return not m.group(4)  # 同版本预发布 < 正式版


# RFC-20261111-03 §2.4：任务目录 `cases.md` 的「用例行」可判形态——
# 表格行（首列是「大写前缀 - 编号」形态）或 `atlas-case` 围栏标题。
# **不看 ID 前缀**是否 `E2E-*`，也不看表头写法（`编号` / `ID` / `序号` / `用例` 都算）；
# 靠前缀排除挡掉 AC 追溯表 / 需求表 / 任务表 / 决策·优先级·缺陷编号。
TASK_CASE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")
TASK_CASE_FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})\s*atlas-case\b")
# 明确不是用例 ID 的前缀：AC 追溯表、需求表、任务卡、决策/优先级/缺陷编号。
NON_CASE_PREFIX_RE = re.compile(r"^(?:AC|REQ|REQS?|T|D|P|P\d|DR|BUG|ISSUE)(?:-|$)")


def _looks_like_case_id(cell: str) -> bool:
    return bool(TASK_CASE_ID_RE.fullmatch(cell)) and not NON_CASE_PREFIX_RE.match(cell)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _task_case_lines(repo: Path) -> list[str]:
    """扫 `<repo>/.trellis/tasks/**/cases.md`（含 `archive/<month>/`）的用例行。

    表格行按「首列 ID 形态 + 前缀排除」判（表头写 `编号` / `ID` / `序号` / `用例`
    都不影响）；`atlas-case` 围栏标题恒认。
    """
    tasks = Path(repo) / ".trellis" / "tasks"
    if not tasks.is_dir():
        return []
    found: list[str] = []
    for p in sorted(tasks.rglob("cases.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(Path(repo)).as_posix()
        for i, line in enumerate(text.splitlines()):
            if TASK_CASE_FENCE_RE.match(line):
                found.append(f"{rel}:{i + 1}=atlas-case")
                continue
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = _cells(stripped)
            first = cells[0] if cells else ""
            if _looks_like_case_id(first):
                found.append(f"{rel}:{i + 1}={first}")
    return found


def _task_case_ids(repo: Path) -> set[str]:
    """扫 `<repo>/.trellis/tasks/**/cases.md` 中出现的合法用例 ID（RFC-20261111-03 §2.4）。"""
    tasks = Path(repo) / ".trellis" / "tasks"
    if not tasks.is_dir():
        return set()
    found: set[str] = set()
    for p in sorted(tasks.rglob("cases.md")):
        try:
            found |= set(CASE_ID_SCAN_RE.findall(p.read_text(encoding="utf-8")))
        except OSError:
            continue
    return found


# 保名兼容（本文件内与外部按名引用）
case_block = load_module("case_block")
parse_block = case_block.parse_block
# 查询串单源（`_support/url_merge.py`）：键提取 / 去 query 后的路径形态，与生成器**同一函数对象**
url_merge = load_module("url_merge")
# 用例 ID 文法体单源（正文归 rings/e2e/reference.md §5.3；锚点本处自留）
case_id = load_module("case_id")
stack_profile = load_module("stack_profile")
# 维度 token 单源（D153）：区间展开 / 中文邻接 / 疑似写法出声归 `_support/ac_coverage.py`。
ac_coverage = load_module("ac_coverage")
parse_dims_cell = ac_coverage.parse_dims_cell
# 契约 §5.5（2026-10-16，issue #R1/#R3）：行内注释剥除口径与内核**同一函数对象**（I3）——
# 剥注释口径**全域单源**（`_support/stack_profile.strip_inline_comment`，2026-10-17 D104 ⑦ 清偿）：
# `_code()` 是该口径在本文件的唯一出口，本文件内**不得**再出现 `split("#", 1)[0]`（MB8 钉守着）。
strip_inline_comment = stack_profile.strip_inline_comment

MAIN_COLUMNS = ["用例ID", "页面", "中文标题", "类型", "关联AC", "需求", "状态", "状态原因", "分片"]
REV_COLUMNS = ["页面", "断言落点用例", "链路经过用例"]

TYPES = {"smoke", "acceptance", "exception", "permission"}
STATES = {"red", "prototype-pass", "green", "blocked", "skipped"}
REASON_PREFIX = {"ENV_ISSUE", "NOT_IMPLEMENTED", "SPEC_AMBIGUOUS", "BLOCKED_DEP", "DEFERRED", "OUT_OF_SCOPE", "OTHER"}

ID_RE = re.compile(rf"^{case_id.GRAMMAR}$")
# `关联AC` 单值文法本体归 `_support/ac_coverage.py`（RFC-20261111-03 §1.6 多值口径同源），
# 本文件只保留旧名 `AC_RE` 供 PRD 表 / 索引格逐 token 使用。
AC_RE = ac_coverage.AC_REF_RE
split_acs = ac_coverage.split_acs
# RFC-20261111-03 §2.4：任务目录 `cases.md` 里的合法用例 ID。用显式边界而非 `\b`——
# `\b` 对 CJK 邻接失效（「用例E2E-HOME-001」会漏），显式边界又不会把 `...-0010` 的前缀误认成 ID。
CASE_ID_SCAN_RE = re.compile(rf"(?<![0-9A-Za-z-]){case_id.GRAMMAR}(?![0-9A-Za-z-])")
# D130 / Batch B（RFC-20261103-08）：E2E 维度列按**表头名**定位；唯一合法表头写死在这里，
# 表头不符 ⇒ 该表按「未声明」跳过（不按第 4 格位置吸收）。
E2E_DIM_HEADER = "适用覆盖维度"
# H（2026-11-04，评审第 3 条 / D156 单案）：前三列须按序为 `AC ID` / `场景` / `回指规则`。
# 第二列只认**显式两形态**：裸 `场景`（三列形态）与模板 canonical 写法
# `场景（Given / When / Then）`（`templates/prd/domain.md:107`）。不用前缀匹配——
# 前缀会放行 `场景数量` / `场景说明` 这类异义列（`REVIEW-20261104-02` §3）。
# 第一列 / 第三列逐字；列序严格，非 canonical 列序 ⇒ 该表按 N/A（逐表独立，坏表不擦好表）。
_CANONICAL_AC_HEAD = ("AC ID", "场景", "回指规则")
_SCENE_HEAD_FORMS = ("场景", "场景（Given / When / Then）")


def is_canonical_ac_header(hdr: list[str]) -> bool:
    """前三列是否按序为 canonical AC 表头（第二列仅 `_SCENE_HEAD_FORMS` 两形态）。"""
    if len(hdr) < 3:
        return False
    return (
        hdr[0] == _CANONICAL_AC_HEAD[0]
        and hdr[1] in _SCENE_HEAD_FORMS
        and hdr[2] == _CANONICAL_AC_HEAD[2]
    )
# 契约 §8.2（2026-09-25 补）：PRD 环登记「结构类 AC」的小节标题 ——
# 该小节内的 AC 其被测属性**只能在初始态观测**（骨架 / 默认面板 / 按数据渲染构成）。
STRUCT_LIST_HEAD = "#### 结构类 AC 清单"
STRUCT_AC_RE = re.compile(r"AC-[A-Z0-9]+-\d{3}")
# 契约 §8.2 / PRD 环 §五（2026-10-12 补，`3509 §B201-3`）：PRD 环登记「不可验 AC」的小节标题 ——
# 「AC 反向覆盖」门从零挂靠清单中**减去**本清单（豁免落点定形 = 本条的落地）。
UNVER_LIST_HEAD = "#### 不可验 AC 清单"
SHARD_RE = re.compile(r"cases/(?P<file>[^#)\s]+)#(?P<anchor>[a-z0-9-]+)")
HEAD = re.compile(r"^##\s+(E2E-[A-Za-z0-9-]+)\b.*$", re.M)
BLOCK = re.compile(r"```atlas-case\s*\n(.*?)```", re.S)
PLACEHOLDERS = ("TODO", "待补充", "TBD", "待定", "[FIELD:", "视情况而定", "后续补充")

EXPECTED_BLACK = ("正常", "无", "OK", "显示正确", "工作正常")
INTENT_BLACK = ("显示正确", "功能正常", "页面正常")
# 容忍性前提措辞（issue #47，D176）：把「实现现在恰好是什么」写成合法前提的措辞。
# 本项**刻意读注释**（§5.5「机器忽略 `#` 之后」的唯一例外）：容忍性假设天然写在
# step/expected 的注释尾巴或 precondition 散文里，只扫代码会漏、且业务文案（如「存量迁移」）
# 写在代码部分时不应误报。词表收窄到问题实证形态；行内 `容忍: <理由>` 显式豁免。
TOLERANT_BLACK = ("存量", "可能停在", "视情况", "随机", "取决于历史")
TOAST_WORDS = ("toast", "成功提示", "弹窗关闭")
# 契约 §5.6 R2：「持久化写」的机器近似 = 步骤里出现**提交性控件**的 testid 语义段。
# 刻意**不**列 编辑 / 修改 / 新建：它们在中文说明里多指「打开编辑器 / 打开新建弹窗」，
# 按它们命中的是说明文字而非落盘动作（本项目实测：按说明命中 4 条用例，全部为误报）。
WRITE_TID_WORDS = ("save", "submit", "confirm", "delete", "remove", "bind")
# 契约 §5.6 R2 例外 ②（鉴权）：登录 / 登出是会话动作，不是持久化写。
AUTH_TID_WORDS = ("login", "logout", "signin", "signout", "auth")
# 契约 §5.6 R2 例外 ①：校验被拒 = 什么都没写 ⇒ 不判。拒绝态由 expected 的形态判定。
REJECT_HINTS = ("error", "不能为空", "请输入", "非法", "无效", "不正确", "已存在")
REFRESH_WORDS = ("刷新", "reload", "refresh")
I18N_HINTS = (re.compile(r"\bt\("), re.compile(r"\b[a-z]+\.[a-z]+\.[a-z]+\b"), re.compile(r"\b[A-Z]{2,}_[A-Z_]+\b"))

# 分片 step / expected 的动词词表（契约 `rings/e2e/reference.md` §5.5，2026-09-23 定）
ACTION_VERBS = ("click", "fill", "select", "check", "uncheck", "press", "type", "hover", "refresh", "goto", "waitFor", "download", "upload", "dispatch")
ASSERT_VERBS = ("text", "contains", "count", "countOptions", "visible", "hidden", "enabled", "disabled", "checked", "unchecked", "value", "attr", "delta", "request")
# 契约 §5.6 R9：`expected` 行可加**行首前缀**，显式声明该断言的判据形状。
# 本校验器只负责**形态项**（前缀后是词表内的动词 / 不嵌套 / `unchanged:` 的用例有提交性动作）；
# **不判**断言是否空转，也不判初始态成不成立（那是运行期零步基线的职责，§6.0 C-new）。
EXEMPT_PREFIX = "initial:"
UNCHANGED_PREFIX = "unchanged:"
LINE_PREFIXES = (EXEMPT_PREFIX, UNCHANGED_PREFIX)
# 契约 §5.5：`after:<N>` = **步骤锚**（断言钉在第 N 条 step 之后的时点，`3509 §B57`）。
# 它不属豁免通道 —— 带锚的断言是**派生断言**，必须像无前缀断言一样参与零步基线。
AFTER_RE = re.compile(r"^after:(\d+)\s+(\S.*)$")


def _step_anchor(line: str) -> int | None:
    """读出行首步骤锚 `after:<N>`（无锚 → None）。调用处可直接拿真值判「它在不在终态那个时点」。"""
    m = AFTER_RE.match(line.lstrip())
    return int(m.group(1)) if m else None


def _strip_prefix(line: str) -> str:
    """剥行首前缀（豁免前缀 `initial:` / `unchanged:`，以及步骤锚 `after:<N>`）。"""
    m = AFTER_RE.match(line.lstrip())
    if m:
        line = m.group(2)
    s = line.lstrip()
    for p in LINE_PREFIXES:
        if s.startswith(p):
            return s[len(p):].lstrip()
    return line


def _code(line: str) -> str:
    """剥 `#` 之后的中文说明并去首尾空白（契约 §5.5：`#` 之后是给人读的说明、**机器忽略**）。

    凡按**文本内容**判定的门（黑名单词 / 长度 / 动词…）都必须先过这一层 —— 否则作者写在
    注释里的说明会反过来影响判定。实测事故（2026-09-25）：`expected 可判定` 的
    `EXPECTED_BLACK` 含「无」，而某条用例的**注释**里写了「无法区分」⇒ 被误报为
    「判定不了什么」。**同族第二例**，见 `3509 §B45`（那一条是「步骤非二选一」扫了 `#`）。
    """
    # 单源（D94 ③ 残余清偿，2026-10-17）：此前是 `line.split("#", 1)[0].strip()` = **第二份口径**
    # （任何 `#` 都截断）；`/console/#/…` 这类路径形态含 hash 的值会被砍断。
    return strip_inline_comment(line).strip()


def _norm_title(s: str) -> str:
    """标题归一：折叠空白后比对（分片标题可能带行尾 / 多重空格，索引单元格同理）。

    只归空白、不做大小写或标点归一 —— 契约 §8.2 的判据是「标题段**全等**」，
    过度归一会让「改一个字」这类真不一致逃过门。
    """
    return re.sub(r"\s+", " ", s).strip()


def _nested_prefix(line: str) -> bool:
    """前缀叠写 —— 三种语义不同，不得叠：① `unchanged: initial: …`（两条豁免通道）；
    ② `after:<N> initial:` / `after:<N> unchanged:`（步骤锚 vs 豁免通道：带锚的断言是派生断言，
    不可能又「本就该在初始态成立」）。
    """
    m = AFTER_RE.match(line.lstrip())
    if m:
        # 只剥锚、**不**再剥豁免前缀 —— 否则 `after:1 initial: …` 的 `initial:` 已被一并剥掉，
        # 这里就看不见叠写了（实测踩到）。
        return m.group(2).lstrip().startswith(LINE_PREFIXES)
    return any(_strip_prefix(line).lstrip().startswith(p) for p in LINE_PREFIXES)


# 契约 §5.6 R9：`unchanged:` 的「同类动作」= 提交性动作。复用 R2 那份词表（**不复制**），
# 另加 cancel / logout —— 「取消后关闭」「退出后重定向」类用例的反馈动作就是这两个。
# 矫正对话框（2026-10-01）引入 adopt / revert / discard——unchanged 同类动作判定据此扩展（WRITE_TID_WORDS 不动：discard/revert 不落盘）
UNCHANGED_ACTION_WORDS = WRITE_TID_WORDS + ("cancel", "logout", "adopt", "revert", "discard")
NO_TESTID_VERBS = ("refresh", "goto")  # 这两个动词不带 testid


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, level: str, detail: str = "") -> None:
        self.checks.append({"check": check, "level": level, "detail": detail})

    @property
    def status(self) -> str:
        levels = {c["level"] for c in self.checks}
        if "FAIL" in levels:
            return "FAIL"
        if "WARN" in levels:
            return "WARN"
        if self.checks and levels <= {"N/A"}:
            return "N/A"
        return "PASS"


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    out = []
    block: list[list[str]] = []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            block.append(split_row(line))
        elif block:
            out.append((block[0], [r for r in block[1:] if not all(set(c) <= set("-: ") for c in r)]))
            block = []
    if block:
        out.append((block[0], [r for r in block[1:] if not all(set(c) <= set("-: ") for c in r)]))
    return out


def seed_models_check(root: Path, blocks: dict[str, dict]) -> tuple[str, str]:
    """`seed:` 的实体 × 字段必须存在于 structure 的 `data-models` 事实（契约 §5.7，`3509 §98 ⑪`）。

    降级语义：无用例声明 `seed:` ⇒ `NA`（合法）；**无 models 事实** ⇒ `NA`（依赖适配器接线，
    见 `rings/structure/reference.md` §6.2）—— `NA` 是「未走到这一步」，**不是通过**。
    """
    seeds = {cid: (b.get("seed") or []) for cid, b in blocks.items() if b.get("seed")}
    if not seeds:
        return "NA", "无用例声明 `seed:`（契约 §5.7 的可选块）"
    spec = root / ".trellis" / "spec" / "structure"
    facts = sorted(spec.rglob("data-models*.md")) if spec.is_dir() else []
    if not facts:
        return "NA", f"无 models 事实（{spec}/**/data-models*.md 不存在）⇒ 跳过对账（不是通过）"
    models: dict[str, set[str]] = {}
    for f in facts:
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if not ln.startswith("|"):
                continue
            cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] and cells[0] != "表/模型" \
                    and not set(cells[0]) <= set("-: "):
                bucket = models.setdefault(cells[0], set())
                for raw_f in re.split(r'[/,]', cells[1]):
                    cleaned = raw_f.strip().strip("`")
                    if cleaned:
                        bucket.add(cleaned)
    if not models:
        return "NA", f"models 事实里无可用「表/模型」行（{len(facts)} 份文件）⇒ 跳过对账"
    bad: list[str] = []
    for cid, rows in seeds.items():
        for row in rows:
            toks = row.split()
            if len(toks) < 2 or toks[0] != "upsert":
                bad.append(f"{cid}: seed 行语法应为 `upsert <实体> <字段>=<值> …`（{row!r}）")
                continue
            ent = toks[1]
            if ent not in models:
                bad.append(f"{cid}: 实体 `{ent}` 不在 models 事实（{len(models)} 个表/模型）")
                continue
            for kv in toks[2:]:
                fname = kv.split("=", 1)[0]
                if fname not in models[ent]:
                    bad.append(f"{cid}: `{ent}.{fname}` 不在该表的字段列")
    return ("FAIL", "；".join(bad[:6])) if bad else \
        ("PASS", f"{len(seeds)} 条用例的 seed 与 {len(models)} 个表/模型对账通过")


def upload_fixture_check(root: Path, blocks: dict[str, dict], lay=None) -> tuple[str, str]:
    """`upload` 行的 fixture 引用闭环（契约 §5.5，B201-1，2026-10-12）。

    值 = 相对 `<资产根>/e2e/fixtures/` 的文件路径（资产根默认 `product/`；
    与 §5.8 mock 同基线、同一 fixtures 树）。
    判据（结构门）：**值形态**（非空 / 非绝对路径 / 无 `..` 段）+ **文件存在**。无用例声明
    `upload` ⇒ PASS（空集合法，N/A 不是通过的反面——空集就是合法形态）。生成器侧生成期
    同款检查（缺 ⇒ exit 2 列明）——两侧同步，防「校验器放行、生成器认不得」的半通状态。
    """
    uploads: list[tuple[str, str]] = []
    for cid, b in blocks.items():
        for s in b.get("step") or []:
            parts = _code(s).split(None, 2)
            if parts and parts[0] == "upload":
                uploads.append((cid, parts[2].strip() if len(parts) > 2 else ""))
    if not uploads:
        return "PASS", "无用例声明 `upload`（可选动作词）"
    fixtures = (lay or load_layout(root)).e2e_fixtures_dir
    bad: list[str] = []
    for cid, rel in uploads:
        if not rel:
            bad.append(f"{cid}: upload 缺文件路径参数")
        elif rel.startswith("/") or ".." in rel.split("/"):
            bad.append(f"{cid}: upload 值须为相对 fixtures/ 的路径（得 {rel!r}）")
        elif not (fixtures / rel).is_file():
            bad.append(f"{cid}: fixture 不存在：fixtures/{rel}")
    return ("FAIL", "；".join(bad[:6])) if bad else \
        ("PASS", f"{len(uploads)} 处 upload 的 fixture 引用均存在")


def tid_owner(tid: str, pages: list[str]) -> str | None:
    """按页面 slug 最长前缀匹配 testid 归属页。"""
    hits = [p for p in pages if tid == p or tid.startswith(p + "-")]
    return max(hits, key=len) if hits else None

def gather_shards(cases: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """返回 {id: block} 与 {file: page}。"""
    blocks: dict[str, dict] = {}
    pages: dict[str, str] = {}
    for md in sorted(cases.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        pages[md.name] = md.stem
        heads = list(HEAD.finditer(text))
        for i, m in enumerate(heads):
            seg = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
            b = BLOCK.search(seg)
            if not b:
                continue
            d = parse_block(b.group(1))
            d["_file"] = md.name
            # 原始块体（RFC-20261108-02：父仓「成员依赖」必填要区分「未写」与「写了空列表」）。
            d["_body"] = b.group(1)
            blocks[m.group(1)] = d
    return blocks, pages


def _route_hit(p: str, page_routes) -> bool:
    """路径 `p` 是否命中页面表 `路由` 列（契约 §8.2）：精确命中，或**非根路由**的子路径前缀命中
    （`/projects/x` 匹配 `/projects`；根路由 `/` 仅精确）。

    两侧都先 `strip_queries`：页面表 `路由` 列是路径形态，但可能携带宿主注入 query
    （`?switchAgent=…`）或 hash 查询；用例侧也可能带 `参数:` / `hash参数:` 的内联查询。
    单源：`goto` 路径与 `守卫` 路径两处判定共用本函数（二者是同一套「不得私藏路径」口径）。
    """
    p = url_merge.strip_queries(p)
    routes = [url_merge.strip_queries(r) for r in page_routes]
    if p in routes:
        return True
    return any(r != "/" and p.startswith(r + "/") for r in routes)


def collect_e2e_declared_dims(prd_files) -> dict[str, set[str]]:
    """逐表按**表头名**收集 AC 的 E2E 覆盖维度声明（Batch B，RFC-20261103-08）。

    与 D153 单源一致：表的切分走 `_support/ac_coverage.iter_md_tables`，单元格解析走
    `parse_dims_cell`。只有表头含 `适用覆盖维度` **且前三列为 canonical 列序**
    （`AC ID` / `场景…` / `回指规则`）的 AC 表才被采信，其余表按「未声明」跳过 ——
    逐表独立，一张错表头不会擦掉同文件的好表。
    """
    declared: dict[str, set[str]] = {}
    for p in prd_files:
        seg = p.read_text(encoding="utf-8")
        for header, rows in ac_coverage.iter_md_tables(seg):
            hdr = [ac_coverage.strip_md_cell(c) for c in header]
            if not is_canonical_ac_header(hdr) or E2E_DIM_HEADER not in hdr:
                continue
            ac_idx = hdr.index("AC ID")
            dim_idx = hdr.index(E2E_DIM_HEADER)
            for row in rows:
                if ac_idx >= len(row):
                    continue
                acid = ac_coverage.strip_md_cell(row[ac_idx])
                if not AC_RE.match(acid):
                    continue
                dims, _looks = parse_dims_cell(row[dim_idx] if dim_idx < len(row) else "")
                if dims:
                    declared[acid] = dims
    return declared


BACKEND_DIM_HEADER = "后端适用覆盖维度"


def collect_unaccepted_dim_tables(prd_files) -> list[dict]:
    """逐表收集「有维度内容但表头未被采信」的表（RFC-20261105-01，落点 b1）。

    与 `collect_e2e_declared_dims` 共用同一遍 `iter_md_tables` 扫描，但两个聚合**互不依赖、
    互不覆盖**：好表的声明照常统计，坏表的诊断也不因同文件存在好表而消失。
    判据（逐字实现 RFC §3.1）：
      已采信   := `is_canonical_ac_header(表头)` ∧ `适用覆盖维度` ∈ 表头
      有维度内容 := ∃ AC 行 ∃ 列 j≥3 使 `parse_dims_cell` 非空（不排除 `适用覆盖维度` 列）
      未采信有维度 := ¬已采信 ∧ 有维度内容
    reason 三分支互斥且穷尽（**不得**出现无兜底的 if/elif：落不到 reason 即 bug）：
      I1 ∧ ¬I2        ⇒ `header_ok_order_rejected`
      ¬I1 ∧ I3==后端列 ⇒ `backend_column`
      ¬I1 ∧ I3≠后端列 ⇒ `misspelled_header`
    诊断文案只含文件名 / 1 基列号 / 表头原文 / reason（**不含任何 AC ID**，RFC §5.1 H-1）。
    """
    out: list[dict] = []
    for p in prd_files:
        seg = p.read_text(encoding="utf-8")
        for header, rows in ac_coverage.iter_md_tables(seg):
            hdr = [ac_coverage.strip_md_cell(c) for c in header]
            if "AC ID" not in hdr:
                continue
            ac_idx = hdr.index("AC ID")
            # 列号 → 表头原文（只记 j≥3 且有维度内容的列；列序最小者 = I3）
            dim_cols: dict[int, str] = {}
            for row in rows:
                if ac_idx >= len(row):
                    continue
                if not AC_RE.match(ac_coverage.strip_md_cell(row[ac_idx])):
                    continue
                for j in range(3, len(row)):
                    dims, _looks = parse_dims_cell(row[j])
                    if dims:
                        dim_cols.setdefault(j, hdr[j] if j < len(hdr) else "")
            if not dim_cols:
                continue
            i1 = E2E_DIM_HEADER in hdr
            i2 = is_canonical_ac_header(hdr)
            if i1 and i2:
                continue  # 已采信：合法表整体不诊断
            if i1:
                # I1 ∧ ¬I2：表头名对、前三列/列序未通过（指向 `适用覆盖维度` 列）
                col = hdr.index(E2E_DIM_HEADER)
                reason = "header_ok_order_rejected"
            else:
                # ¬I1：I3 = 列序最小且表头非 `适用覆盖维度` 的维度列
                col = min(dim_cols)
                reason = ("backend_column" if dim_cols[col] == BACKEND_DIM_HEADER
                          else "misspelled_header")
            out.append({"file": p.name, "col": col + 1,
                        "header": hdr[col] if col < len(hdr) else "",
                        "reason": reason})
    return out


_UNACCEPTED_REASON_SUFFIX = {
    "misspelled_header": "",
    "backend_column": "= 后端列，非 E2E 列",
    "header_ok_order_rejected": "表头正确但列序未通过",
}


def format_unaccepted_dim_note(tables: list[dict]) -> str:
    """`未采信表=N（…）` 的唯一格式化出口（文案与渲染哨兵 `未采信表=` 耦合，改文案须同步渲染器）。"""
    if not tables:
        return ""
    parts = [
        f"{t['file']} 第{t['col']}列表头「{t['header']}」{_UNACCEPTED_REASON_SUFFIX[t['reason']]}"
        for t in tables
    ]
    return f"未采信表={len(tables)}（{'；'.join(parts)}）"


def validate(root: Path) -> Result:
    res = Result()
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        res.add("项目布局配置", "FAIL", str(exc))
        return res
    e2e = lay.e2e_dir
    index = e2e / "e2e-index.md"
    cases = e2e / "cases"
    shard_files = sorted(cases.glob("*.md")) if cases.is_dir() else []
    parent = _solution_root(root)
    if not index.is_file() and not shard_files:
        if parent:
            # RFC-20261108-02 §3.7：父仓模式不再判 N/A。
            if _declares_case_ids(root):
                res.add("门控态", "FAIL",
                        "父仓清单已声明 case_ids，但 e2e-index.md 缺失；"
                        "运行 atlas solution e2e init")
            else:
                res.add("门控态", "WARN",
                        "父仓 E2E 未初始化；运行 atlas solution e2e init")
            return res
        res.add("门控态", "N/A", "无索引且无分片 → 空骨架")
        return res

    text = index.read_text(encoding="utf-8") if index.is_file() else ""
    tabs = tables(text)
    main_header, main_rows = (tabs[0] if tabs else ([], []))

    res.add("索引与主表列头", "PASS" if index.is_file() and main_header == MAIN_COLUMNS else "FAIL",
             f"实际={main_header}；期望={MAIN_COLUMNS}")
    has_rev = "## 页面 ↔ 用例" in text
    res.add("反向视图小节存在", "PASS" if has_rev else "FAIL", "")

    # 行索引字典
    grid: list[dict] = []
    if main_header == MAIN_COLUMNS:
        for r in main_rows:
            grid.append(dict(zip(MAIN_COLUMNS, r + [""] * (len(MAIN_COLUMNS) - len(r)))))

    ids = [g["用例ID"] for g in grid]
    bad_id = [i for i in ids if not ID_RE.match(i)]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    res.add("ID 格式", "PASS" if not bad_id else "FAIL", f"违规={bad_id}")
    res.add("ID 全站唯一", "PASS" if not dup else "FAIL", f"重复={dup}")

    field_bad = []
    for g in grid:
        for col in MAIN_COLUMNS:
            if col in ("状态原因", "需求"):  # 需求为空 = 项目级基线用例（§5.2）
                continue
            if not g[col]:
                field_bad.append(f"{g['用例ID']}:{col}空")
        reason_ok = (g["状态"] in ("blocked", "skipped")) == bool(g["状态原因"])
        if not reason_ok:
            field_bad.append(f"{g['用例ID']}:状态原因/状态不匹配")
    res.add("行字段完整", "PASS" if not field_bad else "FAIL",
            (f"{_format_list(field_bad)}"
             + _fix(root, f"在索引行补齐缺失列（{', '.join(field_bad[:3])}）；"
                          "状态原因只在 blocked/skipped 时填写并与状态匹配"))
            if field_bad else "")

    # 分片块
    blocks, file_page = gather_shards(cases) if cases.is_dir() else ({}, {})
    needed = ("id", "pages", "precondition", "step", "expected", "testid")
    block_bad = []
    for cid, d in blocks.items():
        missing_keys = [k for k in needed if not d.get(k)]
        if missing_keys:
            block_bad.append(f"{cid}在{d.get('_file', '')}(缺:{','.join(missing_keys)})")
    res.add("分片块字段齐", "PASS" if not block_bad else "FAIL",
            (f"缺字段={_format_list(block_bad)}"
             + _fix(root, "在分片的 atlas-case 块补齐 "
                          "id/pages/precondition/step/expected/testid"))
            if block_bad else "")

    # 父仓「成员依赖」必填（RFC-20261108-02 §3.7 / §5.4）：缺失 FAIL、清单外成员 FAIL、
    # 共享用例（同一 case 被多个需求引用）的并集不一致 FAIL。成员依赖只服务 BLOCKED 与
    # 清单校验，不承担 stale 粒度。
    if parent:
        member_names: set[str] = set()
        consumers: dict[str, set[str]] = {}
        members_by_rid: dict[str, set[str]] = {}
        try:
            manifest = load_module("solution").load_manifest(root)
            member_names = {m["name"] for m in manifest["members"]}
            for r in manifest.get("requirements") or []:
                members_by_rid.setdefault(r["id"], set()).add(r["member"])
                for cid in r.get("case_ids") or []:
                    consumers.setdefault(cid, set()).add(r["id"])
        except Exception:  # noqa: BLE001 - 清单不可读时由清单门报错，这里不重复红
            member_names = set()
        dep_missing: list[str] = []
        dep_unknown: list[str] = []
        dep_union: list[str] = []
        for cid, d in blocks.items():
            if "成员依赖" not in case_block.block_keys(d.get("_body", "")):
                dep_missing.append(cid)
                continue
            vals = d.get("成员依赖") or []
            unknown = [v for v in vals if member_names and v not in member_names]
            if unknown:
                dep_unknown.append(f"{cid}:{unknown}")
            rids = consumers.get(cid, set())
            if len(rids) > 1:
                expected = set().union(*(members_by_rid.get(r, set()) for r in rids))
                if set(vals) != expected:
                    dep_union.append(f"{cid}: 期望={sorted(expected)} 实际={sorted(vals)}")
        res.add("成员依赖必填", "PASS" if not dep_missing else "FAIL",
                f"缺失={_format_list(dep_missing)}"
                + (_fix(root, "父仓用例块补 `成员依赖:`（空列表也写冒号，勿写 `[]`）")
                   if dep_missing else ""))
        res.add("成员依赖成员存在", "PASS" if not dep_unknown else "FAIL",
                f"清单外成员={_format_list(dep_unknown)}")
        res.add("成员依赖共享并集", "PASS" if not dep_union else "FAIL",
                f"不一致={_format_list(dep_union)}")

    orphan = sorted(set(blocks) - set(ids))
    dead = sorted(set(ids) - set(blocks))
    res.add("索引↔分片无孤儿/死链", "PASS" if not orphan and not dead else "FAIL",
             f"孤儿(分片有索引无)={_format_list(orphan)} 死链(索引有分片无)={_format_list(dead)}"
             + (_fix(root, "死链 ⇒ 补/修分片或删该索引行；"
                           "孤儿 ⇒ 补索引行或删分片")
                if orphan or dead else ""))

    # 分片链接可达 + 锚点标题
    # 索引↔分片标题一致（契约 §8.2，2026-09-25 补，依据 `3509 §B31`）：
    # 「锚点存在」与「标题文本相同」是两回事 —— 链接指向分片、但两处标题各写一个
    # 说法时（实测 `E2E-ASSETS-004`：索引写「素材列表…」、分片写「BGM 列表…」），
    # 旧的门只查锚点、照样全绿。故本项单列，按确定性判据 FAIL。
    link_bad = []
    title_bad = []
    for g in grid:
        m = SHARD_RE.search(g["分片"])
        if not m:
            link_bad.append(f"{g['用例ID']}:链接格式")
            continue
        f = e2e / "cases" / m.group("file")
        if not f.is_file():
            link_bad.append(f"{g['用例ID']}:文件缺")
            continue
        shard_text = f.read_text(encoding="utf-8")
        if not re.search(rf"^##\s+{re.escape(g['用例ID'])}\b", shard_text, re.M):
            link_bad.append(f"{g['用例ID']}:无标题锚点")
        hit = re.search(rf"^##\s+{re.escape(g['用例ID'])}\b[ \t]*(.*?)[ \t]*$", shard_text, re.M)
        shard_title = hit.group(1) if hit else ""
        if _norm_title(shard_title) != _norm_title(g["中文标题"]):
            title_bad.append(f"{g['用例ID']}:索引={g['中文标题']!r} 分片={shard_title!r}")
    res.add("分片链接可达", "PASS" if not link_bad else "FAIL", f"{_format_list(link_bad)}")
    res.add("索引↔分片标题一致", "PASS" if not title_bad else "FAIL", f"{_format_list(title_bad)}")

    # 用例第二落点（#54 / RFC-20261111-03 §2.4）：合法落点只有 `<assets>/e2e/cases/*.md` 与索引主表。
    # 任务目录 `.trellis/tasks/**/cases.md`（含 `archive/<month>/` 与成员任务目录）**只要有
    # 用例行**即报 `task_dir_case_duplicate`，不看 ID 前缀是否 `E2E-*`（`BE-SYNC-*` /
    # `HC-RECORD-*` / `TW-PUSH-*` 同属「用例先行」的第二落点）。版本分级：0.3.x WARN、
    # 0.4.0 起 FAIL；父仓未声明 `case_ids` / 清单不可读 ⇒ 本项 N/A 并在 detail 写明原因
    # （不是静默跳过）。父仓模式只在清单声明了 `case_ids` 时扫（成员目录由 `members[].path`
    # 定位）；单仓模式扫本仓任务目录。三个 `not_ready` 机制（生成器退出码 3 / 索引 N/A
    # 门控 / impact_report 跳过）各自独立存在，本项不合并、不改写它们。
    scans: list[tuple[str, Path]] = []
    skip_reason = ""
    if parent:
        try:
            _mf = load_module("solution").load_manifest(root)
        except Exception:  # noqa: BLE001 - 清单不可读由清单门另行判红
            _mf = None
            skip_reason = "清单不可读（不是「未声明 case_ids」），本项未测（由清单门另行判红）"
        if _mf is not None:
            if any(r.get("case_ids") for r in _mf["requirements"]):
                scans = [(m["name"], root / m["path"]) for m in _mf["members"]]
            else:
                skip_reason = "清单未声明 case_ids（无跨仓 E2E 落点），本项未测"
    else:
        scans = [("", root)]
    second_bad: list[str] = []
    for scope, repo in scans:
        stray_rows = _task_case_lines(repo)
        stray_ids = sorted(_task_case_ids(repo) - set(ids))
        parts: list[str] = []
        if stray_rows:
            parts.append(f"用例行={_format_list(stray_rows)}")
        if stray_ids:
            parts.append(f"索引外 ID={_format_list(stray_ids)}")
        if parts:
            second_bad.append(f"{scope + ':' if scope else ''}" + "；".join(parts))
    version = _reader_version(root)
    unknown_note = ("；reader_version_unknown：`.atlas/VERSION` / `.atlas/package.json` / "
                    "工具包 package.json 三级来源全缺，按 0.3.x 口径分级"
                    if not version else "")
    if skip_reason:
        res.add("用例第二落点", "N/A", skip_reason + unknown_note)
    elif second_bad:
        second_level = "FAIL" if _version_at_least(version, (0, 4, 0)) else "WARN"
        res.add("用例第二落点", second_level,
                "task_dir_case_duplicate: 任务目录 cases.md 出现用例行："
                + "；".join(second_bad)
                + _fix(root, "把用例迁入 <assets>/e2e/cases/ 并在索引主表登记；"
                             "任务目录 cases.md 不是合法落点")
                + unknown_note)
    else:
        res.add("用例第二落点", "PASS", "")

    # pages 合法性（E1：页清单唯一来源 = 索引页面表 §3.2；无页面表时退化为分片文件名）
    idx_text = text
    page_rows = [ln for ln in idx_text.splitlines()
                 if re.match(r"^\|\s*[a-z0-9][a-z0-9-]*\s*\|\s*/", ln)]
    # issue #49：是否启用第 5 列只看**表头**——任意第 5 列（如「备注」）不得被误当覆盖就绪。
    # 多张「页面/路由」表时优先选带 `覆盖就绪` 的表头；4 列表的行按缺省值回落。
    page_table_headers = [
        ln for ln in idx_text.splitlines()
        if ln.strip().startswith("|") and "页面" in ln and "路由" in ln
    ]
    page_table_header = next(
        (ln for ln in page_table_headers
         if any(c.strip().startswith("覆盖就绪")
                for c in ln.strip().strip("|").split("|"))),
        page_table_headers[0] if page_table_headers else "",
    )
    page_header_cells = (
        [c.strip() for c in page_table_header.strip().strip("|").split("|")]
        if page_table_header else []
    )
    coverage_header_index = next(
        (i for i, c in enumerate(page_header_cells) if c.startswith("覆盖就绪")),
        None,
    )
    has_coverage_column = coverage_header_index is not None
    known = None
    page_routes: list[str] = []
    if page_rows:
        known = set()
        routes: list[str] = []
        page_bad2: list[str] = []
        for ln in page_rows:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) < 2 or cells[0] in ("页面", "---"):
                continue
            slug, route = cells[0], cells[1]
            known.add(slug)
            if not route.startswith("/") or route in routes:
                page_bad2.append(f"{slug}:{route}")
            if (coverage_header_index is not None and len(cells) > coverage_header_index
                    and cells[coverage_header_index] not in ("", "—", "是", "否")):
                page_bad2.append(f"{slug}:覆盖就绪={cells[coverage_header_index]}")
            routes.append(route)
        page_routes = routes
        page_routes_map = {}
        for ln in page_rows:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in ("页面", "---"):
                page_routes_map[cells[0]] = cells[1]
        res.add("页面表合法", "PASS" if not page_bad2 else "FAIL",
                f"路由非/开头或重复 / 覆盖就绪取值非法={page_bad2[:8]}" if page_bad2 else "")
    if known is None:
        known = {md.stem for md in lay.e2e_cases_dir.glob("*.md")}
        res.add("页面表合法", "WARN", "索引无页面表（E1 起应有；暂按分片文件名推导页清单）")
    if known is not None and page_rows:
        miss = sorted({g["页面"] for g in grid} - known)
        if miss:
            res.add("页面表覆盖", "FAIL", f"主表引用但页面表缺={miss[:8]}")
        else:
            res.add("页面表覆盖", "PASS", "")
    if True:
        page_bad = []
        for g in grid:
            pgs = blocks.get(g["用例ID"], {}).get("pages", [])
            if g["页面"] not in pgs:
                page_bad.append(f"{g['用例ID']}:页面∉pages")
            for p in pgs:
                if p not in known:
                    page_bad.append(f"{g['用例ID']}:未知页 {p}")
        res.add("pages 合法性", "PASS" if not page_bad else "FAIL", f"{page_bad[:8]}")

    # 反向视图一致
    if has_rev and known is not None:
        rev_start = text.index("## 页面 ↔ 用例")
        rev_tabs = tables(text[rev_start:])
        rev_header, rev_rows = (rev_tabs[0] if rev_tabs else ([], []))
        derived: dict[str, tuple[set, set]] = {}
        for g in grid:
            pgs = blocks.get(g["用例ID"], {}).get("pages", [])
            derived.setdefault(g["页面"], (set(), set()))[0].add(g["用例ID"])
            for p in pgs:
                if p != g["页面"]:
                    derived.setdefault(p, (set(), set()))[1].add(g["用例ID"])
        mism = []
        if rev_header != REV_COLUMNS:
            mism.append(f"列头={rev_header}")
        for r in rev_rows:
            page = r[0]
            exp_own, exp_via = derived.get(page, (set(), set()))
            got_own = set(x.strip() for x in re.split(r"[,\s]+", r[1]) if x.strip())
            got_via = set(x.strip() for x in re.split(r"[,\s]+", r[2]) if x.strip())
            if got_own != exp_own or got_via != exp_via:
                mism.append(page)
        res.add("反向视图一致", "PASS" if not mism else "FAIL", f"不一致={mism[:8]}")
    else:
        res.add("反向视图一致", "N/A", "无反向视图或无原型")

    # 词表
    vocab_bad = []
    for g in grid:
        if g["类型"] not in TYPES:
            vocab_bad.append(f"{g['用例ID']}:类型={g['类型']}")
        if g["状态"] not in STATES:
            vocab_bad.append(f"{g['用例ID']}:状态={g['状态']}")
        if g["状态原因"]:
            pre, _, rest = g["状态原因"].partition("：")
            if pre not in REASON_PREFIX or not rest.strip():
                vocab_bad.append(f"{g['用例ID']}:状态原因={g['状态原因']}")
    res.add("词表", "PASS" if not vocab_bad else "FAIL", f"{vocab_bad[:8]}")

    # 关联AC（RFC-20261111-03 §1.6：一格可持多值，逐 token 整串匹配，不整格 match）
    ac_bad = [g["用例ID"] for g in grid if not _ac_cell_ok(g["关联AC"])]
    res.add("关联AC 格式", "PASS" if not ac_bad else "FAIL", f"{ac_bad[:8]}")
    prd_files = sorted(lay.prd_dir.glob("*-prd.md")) if lay.prd_dir.is_dir() else []
    if not prd_files:
        res.add("关联AC 可达", "N/A", "门控态：无域级 PRD")
    else:
        if parent:
            # 父仓模式（RFC-20261108-02 §3.7）：`关联AC` 必须命中 AC 表**定义行**，
            # 不是散文提及。定义行形态 = 表格首列 `AC-<CODE>-NNN`。
            defs: set[str] = set()
            for pf in prd_files:
                seg = pf.read_text(encoding="utf-8")
                defs |= {m.group(1) for m in
                         re.finditer(r"^\|\s*`?(AC-[A-Z0-9]+-\d{3})`?\s*\|", seg, re.M)}
            unreachable = [g["用例ID"] for g in grid if _ac_unreachable(g["关联AC"], defs)]
        else:
            corpus = "".join(p.read_text(encoding="utf-8") for p in prd_files)
            unreachable = [g["用例ID"] for g in grid if _ac_unreachable(g["关联AC"], corpus)]
        res.add("关联AC 可达", "PASS" if not unreachable else "FAIL", f"不可达={unreachable[:8]}")

    # AC 反向覆盖（追溯门，契约 §8.2；2026-10-04 补，`3509 §B186-2`）——追溯链末段
    # 「AC → E2E 用例」此前无门（`validate_prd.py` 参数 4 只盖「规则 ↔ AC」）⇒ 已实现域能带
    # 零挂靠 AC 收口（2026-10-04 实测：AC 129 / 索引已关联 80 / 已实现域零挂靠 9，其中
    # voice-library 6 条在该域独立审查 PASS + 走查单落盘之后仍在）。
    # 分级沿用 §8.1 testid 门先例：域内页面**全** `已实现` ⇒ 严判；含 `实现中` / `未开始` ⇒
    # 该域不参与（用例尚未长出，不是缺口）。**豁免落点已定形（2026-10-12，`3509 §B201-3`）**：
    # 域级 PRD §五 的「不可验 AC 清单」登记当前 UI 无观测面的 AC，本门从零挂靠清单中减去它
    # （落点 = PRD 侧，理由：可不可验是 AC 定义（应然）的属性；自洽门见 validate_prd.py）。
    # 覆盖关系是**派生量**（真相源 = 主表 `关联AC` 列 + 域级 PRD §五 AC 定义行），不落第 4 张
    # 手工表（`single-source.md` §4：同一信息两处正文即漂移）。
    # 页面级覆盖就绪（issue #49）：`覆盖就绪` 列可选，显式 `是` 让「实现中」页也参与 AC 覆盖对账；
    # 缺省 / `—` 回落到 `实现状态 == 已实现`，保持存量项目行为不变。
    page_ready: dict[str, bool] = {}
    dom_pages: dict[str, set[str]] = {}
    for ln in page_rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("页面", "---"):
            continue
        slug, status = cells[0], cells[3]
        coverage = (cells[coverage_header_index]
                    if coverage_header_index is not None and len(cells) > coverage_header_index
                    else "")
        if coverage == "是":
            page_ready[slug] = True
        elif coverage == "否":
            page_ready[slug] = False
        else:
            page_ready[slug] = status == "已实现"
        for dom in re.split(r"\s*·\s*", cells[2]):
            if dom and dom != "—":
                dom_pages.setdefault(dom, set()).add(slug)
    dom_acs: dict[str, set[str]] = {}
    dom_unver: dict[str, set[str]] = {}
    for pf in prd_files:
        seg = pf.read_text(encoding="utf-8")
        fm_text = seg.split("---")[1] if seg.startswith("---") else ""
        m_slug = re.search(r"^domain:\s*(\S+)", fm_text, re.M)
        if not m_slug:
            continue
        dom_acs[m_slug.group(1)] = {
            m.group(1) for m in re.finditer(r"^\|\s*`?(AC-[A-Z0-9]+-\d{3})`?\s*\|", seg, re.M)
        }
        # 不可验 AC 清单（豁免面，2026-10-12，`3509 §B201-3`）：只取小节内**表格行**的 AC
        # （至下一个标题止；说明散文里的 AC 提及不构成条目）；自洽（清单 ⊆ 本文档 AC 表）
        # 由 validate_prd.py 参数 4 检——两门分工不重叠。
        unver: set[str] = set()
        if UNVER_LIST_HEAD in seg:
            tail = seg.split(UNVER_LIST_HEAD, 1)[1]
            cut = re.search(r"^#{1,4} ", tail, re.M)
            zone = tail[:cut.start()] if cut else tail
            unver = {m.group(1) for m in
                     re.finditer(r"^\|\s*`?(AC-[A-Z0-9]+-\d{3})`?\s*\|", zone, re.M)}
        dom_unver[m_slug.group(1)] = unver
    if not dom_acs or not dom_pages:
        res.add("AC 反向覆盖", "N/A", "域级 PRD 无 `domain:` 声明，或索引无页面表")
    else:
        covered_ac = {ac for g in grid for ac in split_acs(g["关联AC"])}
        gaps: list[str] = []
        exempted: list[str] = []
        for dom in sorted(dom_acs):
            pages = dom_pages.get(dom, set())
            if not pages or not all(page_ready.get(p, False) for p in pages):
                continue
            missing = dom_acs[dom] - covered_ac
            unver = dom_unver.get(dom, set())
            hit = missing & unver
            if hit:
                exempted.append(f"{dom}:{len(hit)}")
            missing = sorted(missing - unver)
            if missing:
                gaps.append(f"{dom}:{'/'.join(missing)}")
        detail = f"覆盖就绪域零挂靠={gaps[:6]}" if gaps else ""
        if exempted:
            detail += ("；" if detail else "") + f"不可验豁免={exempted}"
        # 门级（2026-10-12，`3509 §B201-3`）：豁免落点已定形（PRD 侧「不可验 AC 清单」机器读取，
        # 上方减法）⇒ 升 FAIL 通道就绪；当前仍 WARN——**残留清欠在内容侧**（补 `关联AC` 或
        # 登记「不可验 AC 清单」），升档规则（零挂靠清零 + 清零态实测全绿一次 ⇒ WARN 分支改
        # FAIL，不设 profile 开关）登记在 `shared/gates.md` §3 的 AC⇔用例行，本文件的引用以它为锚
        # （2026-10-15 死指针修正，D79 ②：旧文案指向外仓 `product/issues.md` P9——台账不在本仓，
        # 外仓读者读不到。过早 FAIL 被量推翻的先例见 `3509 §B36`）。
        res.add("AC 反向覆盖", "PASS" if not gaps else "WARN",
                (detail + "；残留待裁决（清零后升 FAIL，规则在 shared/gates.md §3 AC⇔用例行）")
                if gaps else detail)

    # 解析口径归 `_support/ac_coverage.py::parse_dims_cell`（D153 单源，行为与 D130 逐字节一致）：
    # 区间展开、中文邻接、疑似写法出声；本文件不再自持第二份 parser。
    # Batch B（RFC-20261103-08）：列定位从「第 4 格位置」改为「表头名 `适用覆盖维度`」——
    # 表切分仍走同一 `_support`，逐表处理；表头不符的表按未声明跳过。
    declared_ac_dims = collect_e2e_declared_dims(prd_files)
    # RFC-20261105-01（b1）：诊断与 `declared_ac_dims` **无关**——一张好表不得压掉同文件坏表的
    # 诊断，故本量在四个出口（PASS / FAIL / N/A）之外独立计算、共用同一 `note` 拼接。
    dim_header_note = format_unaccepted_dim_note(collect_unaccepted_dim_tables(prd_files))

    covered_ac_dims: dict[str, set[str]] = {}
    bad_case_dims: list[str] = []
    for g in grid:
        # issue #49：只采信覆盖就绪页上的用例声明；未就绪页的维度缺口仍由该页自己的 AC 门暴露。
        if not page_ready.get(g["页面"], False):
            continue
        cid = g["用例ID"]
        blk = blocks.get(cid, {})
        dims: set[str] = set()
        for d_str in (blk.get("覆盖维度") or []):
            found, looks = parse_dims_cell(d_str)
            if not found and looks:
                bad_case_dims.append(f"{cid}:{d_str}")
            dims |= found
        # 多值 AC（RFC-20261111-03 §1.6）：该行声明的维度对**每个 token** 都算挂靠，
        # 否则第二个 AC 在下方 `:915` 的 `acid not in covered_ac_set` 处被静默 continue。
        for acid in split_acs(g["关联AC"]):
            covered_ac_dims.setdefault(acid, set()).update(dims)

    if not declared_ac_dims:
        res.add("AC × 覆盖维度", "N/A",
                "域级 PRD 验收标准表未声明「适用覆盖维度」列（按需启用）" + dim_header_note)
    else:
        dim_gaps: list[str] = []
        covered_ac_set = {ac for g in grid for ac in split_acs(g["关联AC"])}
        ac_pages: dict[str, set[str]] = {}
        for g in grid:
            for acid in split_acs(g["关联AC"]):
                ac_pages.setdefault(acid, set()).add(g["页面"])
        ready_acs: list[str] = []
        for dom in sorted(dom_acs):
            pages = dom_pages.get(dom, set())
            if not has_coverage_column and (
                not pages or not all(page_ready.get(p, False) for p in pages)
            ):
                continue
            for acid in sorted(dom_acs[dom]):
                if acid not in covered_ac_set or acid not in declared_ac_dims:
                    continue
                if not any(page_ready.get(p, False) for p in ac_pages.get(acid, set())):
                    continue
                ready_acs.append(acid)
                applicable = declared_ac_dims[acid]
                actual = covered_ac_dims.get(acid, set())
                missing = applicable - actual
                if missing:
                    dim_gaps.append(f"{acid}缺{','.join(sorted(missing))}")
        detail_parts = []
        if dim_gaps:
            detail_parts.append(f"维度缺口={dim_gaps[:6]}")
        if bad_case_dims:
            detail_parts.append(f"未知维度={bad_case_dims[:4]}")
        # 可评测集（2026-11-11 升 FAIL）：声明了适用维度 + 被用例挂靠 + 落在覆盖就绪页。
        # 等级取最严：有缺口 / 未知维度 ⇒ FAIL（此前 WARN，零成本实测后升档）。
        declared_acs = [
            ac for dom in dom_acs for ac in dom_acs[dom]
            if ac in declared_ac_dims and ac in covered_ac_set
        ]
        if dim_gaps or bad_case_dims:
            status = "FAIL"
            detail = "；".join(detail_parts)
        elif not ready_acs:
            # 休眠态不得读成已覆盖（此前输出「0 条…全量覆盖」= 假绿）。
            status = "N/A"
            if declared_acs:
                # 未就绪面 = 相关域的页面 ∪ AC 挂靠页（域级跳过 / 页级跳过都算「页未就绪」）。
                scope_pages = {p for ac in declared_acs for p in ac_pages.get(ac, set())}
                for dom, acs in dom_acs.items():
                    if any(ac in declared_acs for ac in acs):
                        scope_pages |= dom_pages.get(dom, set())
                not_ready = sorted(p for p in scope_pages if not page_ready.get(p, False))
                reason = "页未就绪，本项未测"
                if not_ready:
                    reason += f"（涉及页：{'、'.join(not_ready)}）"
                else:
                    reason = "无覆盖就绪页归属，本项未测"
            else:
                reason = "无「已声明适用覆盖维度且被用例挂靠」的 AC，本项未测"
            detail = "；".join(detail_parts + [reason])
        else:
            status = "PASS"
            detail = "；".join(detail_parts + [f"{len(ready_acs)} 条覆盖就绪 AC 声明维度全量覆盖"])
        res.add("AC × 覆盖维度", status, detail + dim_header_note)

    # 零证据用例须挂结构类 AC（契约 §8.2；2026-09-25 补，`3509 §B36` + `§B50`）：
    # `expected` **全部**带 `initial:` 的用例 = 零证据用例（它自己声明「不构成验证」）——
    # 只允许挂**结构类 AC**（PRD 环 §五「结构类 AC 清单」登记：该 AC 的被测属性只能在初始态观测）。
    # 否则该用例既没证据、它的 AC 又要求可派生的终态 ⇒ FAIL（要么补真断言，要么登记结构类 AC）。
    struct_acs: set[str] = set()
    for p in prd_files:
        seg = p.read_text(encoding="utf-8")
        if STRUCT_LIST_HEAD not in seg:
            continue
        tail = seg.split(STRUCT_LIST_HEAD, 1)[1]
        cut = re.search(r"^#{1,4} ", tail, re.M)
        struct_acs |= set(STRUCT_AC_RE.findall(tail[:cut.start()] if cut else tail))
    if not prd_files:
        res.add("零证据用例须挂结构类 AC", "N/A", "门控态：无域级 PRD")
    else:
        zero_evidence = [
            g for g in grid
            if blocks.get(g["用例ID"], {}).get("expected")
            and all(_step_anchor(e) is None and e.lstrip().startswith(EXEMPT_PREFIX)
                    for e in blocks[g["用例ID"]]["expected"])
        ]
        if not zero_evidence:
            # 空集合不是「全量覆盖」：没有对象时本项未测，不得输出 PASS。
            res.add("零证据用例须挂结构类 AC", "N/A", "零证据用例 0 条，本项未测")
        elif not struct_acs:
            res.add("零证据用例须挂结构类 AC", "N/A",
                    f"PRD 无「结构类 AC 清单」段，本项未测（零证据用例 {len(zero_evidence)} 条）")
        else:
            # 多值口径（RFC-20261111-03 §1.6）：**至少一个** token 属于结构类即可，不要求全部。
            zero_bad = [f"{g['用例ID']}({g['关联AC']})" for g in zero_evidence
                        if not any(t in struct_acs for t in split_acs(g["关联AC"]))]
            res.add("零证据用例须挂结构类 AC", "PASS" if not zero_bad else "FAIL",
                    f"全 initial: 但 AC 非结构类={zero_bad[:8]}")

    # ---- 有意义门 ----
    empty_exp, black_exp, n_assert, intent_bad, intent_short = [], [], [], [], []
    transient, persist_unverified, or_step, i18n = [], [], [], []
    verb_bad, assert_bad, goto_param, contradict = [], [], [], []
    goto_path: list[str] = []
    auth_bad: list[str] = []
    target_bad: list[str] = []   # `靶场:` 取值不在 `e2e.targets` 闭集内（多靶场，beta.16）
    guard_bad: list[str] = []
    session_bad: list[str] = []
    switch_bad: list[str] = []
    inject_bad: list[str] = []        # `参数:` 声明形态 / 白名单 / 死声明（契约 §5.5，2026-10-18）
    inject_value_bad: list[str] = []  # `goto` 查询值的形态（生成物单引号拼接面，见 §5.5）
    dual_carrier_bad: list[str] = []  # 同键同时出现在 `会话:` 与 `参数:`（前提不可解释）
    hash_inject_bad: list[str] = []   # `hash参数:` 声明形态 / 白名单 / 死声明（HashRouter，2026-10-22）
    hash_goto_param: list[str] = []   # `goto` hash 查询键未声明 / 白名单外
    hash_value_bad: list[str] = []    # `goto` hash 查询值形态
    hash_dual_carrier_bad: list[str] = []  # 同键同时出现在 `hash参数:` 与其他载体
    # 预设白名单（契约 §5.5 / `shared/stack-profile.md` §2）：`<载体>_preset.keys`。
    # 段缺失 / keys 为空 ⇒ 该靶场不允许任何该类预设（用例出现对应行即 FAIL）。
    # `session_preset`（2026-10-16，issue #13）与 `query_preset`（2026-10-18，`DESIGN.md` D109）
    # 同族：同为**前提面**，两个载体各一段。
    _prof_path = lay.stack_profile

    def _preset_keys(sub: str, field: str = "keys") -> set[str]:
        if not _prof_path.is_file():
            return set()
        try:
            cfg = stack_profile.parse_profile(_prof_path.read_text(encoding="utf-8")).get("e2e") or {}
        except Exception:
            return set()
        sub_cfg = cfg.get(sub) if isinstance(cfg, dict) else None
        if isinstance(sub_cfg, dict):
            return {str(k).strip() for k in (sub_cfg.get(field) or []) if str(k).strip()}
        return set()

    _session_keys = _preset_keys("session_preset")
    _query_keys = _preset_keys("query_preset")
    _hash_query_keys = _preset_keys("query_preset", "hash_keys")

    # 契约 §5.4/§5.5（多靶场，beta.16）：具名靶场登记表 `e2e.targets`（可选闭集）。
    # 用例 `靶场:` 名字必须 ∈ 此表；表内路由与页面表路由同属「登记地址」——
    # `goto` / `守卫` 路径门同样放行（地址仍单源于 stack-profile，不开放自由路径）。
    def _named_targets() -> dict[str, str]:
        if not _prof_path.is_file():
            return {}
        try:
            cfg = stack_profile.parse_profile(_prof_path.read_text(encoding="utf-8")).get("e2e") or {}
        except Exception:
            return {}
        t = cfg.get("targets") if isinstance(cfg, dict) else None
        if not isinstance(t, dict):
            return {}
        return {str(k).strip(): str(v or "").strip() for k, v in t.items() if str(k).strip()}

    _named_targets_map = _named_targets()
    _target_routes = list(_named_targets_map.values())
    nested_prefix, unchanged_no_action = [], []
    initial_no_reason = []
    after_bad = []
    waitfor_assert = []
    delta_bad = []
    request_bad = []
    cross_page_bad = []
    # R10 门用反查表 page_routes_map 已在页面表解析处（上方）构建
    for g in grid:
        d = blocks.get(g["用例ID"], {})
        raw_exp = d.get("expected", [])
        exp = [_strip_prefix(e) for e in raw_exp]
        intent = d.get("intent", "")
        step = d.get("step", [])
        # 动词合法性（契约 §5.5）：step 首个 token ∈ ACTION_VERBS；expected 首个 token ∈ ASSERT_VERBS
        for s in step:
            first = strip_inline_comment(s).split(" ", 1)[0].strip()
            if first not in ACTION_VERBS:
                verb_bad.append(f"{g['用例ID']}:{first}")
            # 契约 §5.5（2026-10-16 补，issue #R4）：`click` / `hover` 的**第三位**是步级开关，
            # 值域封闭 —— 仅允许 `native` 或省略。与生成器中止**双保险**（镜像 `auth` 白名单：
            # 文本期挡 + 生成期中止，防「校验器放行 / 生成器认不得」的半通态）。
            if first in ("click", "hover"):
                _sw = strip_inline_comment(s).split(None, 2)
                third = _sw[2].strip() if len(_sw) > 2 else ""
                if third and third != "native":
                    switch_bad.append(f"{g['用例ID']}:{first} <{third}>")
            elif first == "dispatch":
                # 契约 §5.5（2026-10-17）：`dispatch` 无第三位（值域封闭）——有值 ⇒ FAIL，
                # 与生成器中止双保险（镜像上两行的半通态防线）。
                _sw = strip_inline_comment(s).split(None, 2)
                if len(_sw) > 2 and _sw[2].strip():
                    switch_bad.append(f"{g['用例ID']}:{first} <{_sw[2].strip()}>")
        # 契约 §5.5 `参数:`（2026-10-18 新增，`DESIGN.md` D109）：**键清单（无值）**。
        # 值只住 `goto` 的查询串（单一来源，便于守卫导航取首跳、无需回灌 step）。
        # 形态 = `- <键>`；带 `=` / 含空白 / 重复 ⇒ FAIL；键不在白名单 ⇒ FAIL。
        _declared: list[str] = []
        _seen_declared: set[str] = set()
        for entry in d.get("参数") or []:
            k = strip_inline_comment(entry).strip()
            if not k:
                continue
            if "=" in k or any(ch.isspace() for ch in k):
                inject_bad.append(f"{g['用例ID']}:{k}（只声明键，值写在 goto 的查询串里）")
                continue
            if k in _seen_declared:
                inject_bad.append(f"{g['用例ID']}:{k}（重复声明）")
                continue
            _seen_declared.add(k)
            _declared.append(k)
            if k not in _query_keys:
                inject_bad.append(
                    f"{g['用例ID']}:{k}（不在 e2e.query_preset.keys，白名单={sorted(_query_keys)}）")
        # 契约 §5.7 / §5.5 `参数:`（**2026-10-18 重靶**，`DESIGN.md` D109）：`goto` **可以**带查询串，
        # 但每个键必须 ① ∈ `e2e.query_preset.keys` ∧ ② ∈ 本用例 `参数:` 声明——缺一即 FAIL。
        # 原靶仍在 FAIL 面内：原型专有的 `?state=` 那类**未声明**调试参数（= 「数据态直达」形态）照样红。
        # 值形态同时判：生成物里 URL 是**单引号拼接**面，值越形态即污染派生物。
        _used_inject: set[str] = set()
        for s in step:
            code = strip_inline_comment(s)
            parts = code.split(" ", 1)
            if len(parts) < 2 or parts[0] != "goto":
                continue
            for pair in url_merge.query_of(parts[1].strip()).split("&"):
                if not pair:
                    continue
                _k, _, _v = pair.partition("=")
                _k, _v = _k.strip(), _v.strip()
                if not _k:
                    goto_param.append(f"{g['用例ID']}:<空键>")
                    continue
                _used_inject.add(_k)
                if _k not in _query_keys:
                    goto_param.append(
                        f"{g['用例ID']}:{_k}（不在 e2e.query_preset.keys，白名单={sorted(_query_keys)}）")
                elif _k not in _declared:
                    goto_param.append(f"{g['用例ID']}:{_k}（未在本用例 `参数:` 内声明）")
                if _v and not url_merge.VALUE_RE.match(_v):
                    inject_value_bad.append(f"{g['用例ID']}:{_k}={_v}")
        for _k in _declared:
            if _k not in _used_inject:
                inject_bad.append(f"{g['用例ID']}:{_k}（声明了但没有任何 `goto` 用到 = 死声明）")
        # 契约 §5.5 `hash参数:`（2026-10-22，HashRouter）：`#` 之后 hash 查询串的键清单。
        # 值与 `参数:` 同纪律（单一来源 = `goto` 的 hash 查询串），但载体/白名单分开。
        _declared_hash: list[str] = []
        _seen_hash: set[str] = set()
        for entry in d.get("hash参数") or []:
            k = strip_inline_comment(entry).strip()
            if not k:
                continue
            if "=" in k or any(ch.isspace() for ch in k):
                hash_inject_bad.append(f"{g['用例ID']}:{k}（只声明键，值写在 goto 的 hash 查询串里）")
                continue
            if k in _seen_hash:
                hash_inject_bad.append(f"{g['用例ID']}:{k}（重复声明）")
                continue
            _seen_hash.add(k)
            _declared_hash.append(k)
            if k not in _hash_query_keys:
                hash_inject_bad.append(
                    f"{g['用例ID']}:{k}（不在 e2e.query_preset.hash_keys，白名单={sorted(_hash_query_keys)}）")
        _used_hash: set[str] = set()
        for s in step:
            code = strip_inline_comment(s)
            parts = code.split(" ", 1)
            if len(parts) < 2 or parts[0] != "goto":
                continue
            for pair in url_merge.hash_query_of(parts[1].strip()).split("&"):
                if not pair:
                    continue
                _k, _, _v = pair.partition("=")
                _k, _v = _k.strip(), _v.strip()
                if not _k:
                    hash_goto_param.append(f"{g['用例ID']}:<空键>")
                    continue
                _used_hash.add(_k)
                if _k not in _hash_query_keys:
                    hash_goto_param.append(
                        f"{g['用例ID']}:{_k}（不在 e2e.query_preset.hash_keys，白名单={sorted(_hash_query_keys)}）")
                elif _k not in _declared_hash:
                    hash_goto_param.append(f"{g['用例ID']}:{_k}（未在本用例 `hash参数:` 内声明）")
                if _v and not url_merge.VALUE_RE.match(_v):
                    hash_value_bad.append(f"{g['用例ID']}:{_k}={_v}")
        for _k in _declared_hash:
            if _k not in _used_hash:
                hash_inject_bad.append(f"{g['用例ID']}:{_k}（声明了但没有任何 `goto` 用到 = 死声明）")
        # 契约 §5.5（2026-09-30 补）：`goto` 路径必须命中页面表的「路由」列（唯一真相源）——
        # 挡「原型时代路径漂移」（实测 `goto /home` 而页面表为 `/`，真栈上 404 进 NotFound 页）。
        # 匹配规则：精确命中，或**非根路由**的子路径前缀命中（`/projects/x` 匹配 `/projects`，
        # 动态段用例友好）；根路由 `/` 仅精确匹配（否则一切路径都被它吞掉）。
        # `goto` 缺路径参数也是 FAIL（独立审查 D4：否则校验器放行、生成器渲染 `page.goto("")`）。
        for s in step:
            code = strip_inline_comment(s)
            parts = code.split(" ", 1)
            if parts[0] != "goto":
                continue
            if len(parts) < 2 or not parts[1].strip():
                goto_path.append(f"{g['用例ID']}:<缺路径>")
                continue
            if not page_routes:
                continue
            p = parts[1].strip()
            # 契约 §5.5（2026-10-18，D109 / 2026-10-22 hash 查询）：`goto` 可带常规查询与
            # hash 查询 ⇒ 路径门按**去双查询后的路径形态**匹配（`_route_hit` 内部同口径）。
            # 契约 §5.4/§5.5（多靶场，beta.16）：已登记靶场路由同属「登记地址」，同门放行。
            if _route_hit(p, page_routes) or _route_hit(p, _target_routes):
                continue
            goto_path.append(f"{g['用例ID']}:{p}")
        # 契约 §5.7（2026-09-30 补）：`auth` 取值白名单（preset | none）——文本期挡住，
        # 与生成器中止双保险（独立审查 D3：生成器白名单此前只覆盖 python 路径）。
        auth = d.get("auth", "preset")
        if auth not in ("preset", "none"):
            auth_bad.append(f"{g['用例ID']}:auth={auth}")
        # 契约 §5.4/§5.5（多靶场，beta.16）：`靶场:` 取值闭集 —— 名字必须 ∈ `e2e.targets`；
        # 整段未声明而用例钉名 ⇒ FAIL（与生成器中止双保险，不猜）。
        _target_decl = d.get("靶场")
        if isinstance(_target_decl, str) and _target_decl.strip() and _target_decl.strip() not in _named_targets_map:
            target_bad.append(f"{g['用例ID']}:{_target_decl.strip()}")
        # 契约 §5.5（2026-10-16 补，issue #13）：`会话:` 行形态 + 键白名单。
        # 与生成器中止**双保险**（文本期挡 + 生成期中止）：白名单是项目级声明，
        # 防把「数据态」走私成会话参数（§5.7 禁令不破）。
        _session_declared: set[str] = set()
        for entry in d.get("会话") or []:
            code = strip_inline_comment(entry)
            if "=" not in code:
                session_bad.append(f"{g['用例ID']}:缺 `=` → {code}")
                continue
            k, v = code.split("=", 1)
            k, v = k.strip(), v.strip()
            if not k or not v:
                session_bad.append(f"{g['用例ID']}:键或值为空 → {code}")
                continue
            _session_declared.add(k)
            if k not in _session_keys:
                session_bad.append(
                    f"{g['用例ID']}:{k}（不在 e2e.session_preset.keys，白名单={sorted(_session_keys)}）")
        # 契约 §5.5（2026-10-18，D109）：同一键不得同时由两个载体（`会话:` / `参数:`）承载 ——
        # 两个载体写同一键 = 前提不可解释（同 R7「自相矛盾」族）。
        for _k in sorted(_session_declared & set(_declared)):
            dual_carrier_bad.append(f"{g['用例ID']}:{_k}")
        # `hash参数:` 与 `参数:` / `会话:` 是两个不同消费面，同键双写同样不可解释。
        for _k in sorted(set(_declared_hash) & (set(_declared) | _session_declared)):
            hash_dual_carrier_bad.append(f"{g['用例ID']}:{_k}")
        # 契约 §5.5（2026-10-16 补，issue #23）：`守卫:` 值（具体路径）同样不得私藏于分片 ——
        # 它必须命中页面表 `路由` 列（同 §8.2 的前缀口径）。缺路径 / 越界 ⇒ FAIL。
        _guard = d.get("守卫")
        if isinstance(_guard, str) and _guard.strip():
            # 契约 §5.5（2026-10-16 补，issue #R3）：**门内取值路径自带剥注释**——即使日后
            # 出现绕过 `parse_block` 的带注释原始值（上游 F1 之后端到端已造不出污染值），
            # 本门也不把注释当路径。与 `goto` 门 / `会话` 门共用同一 `strip_inline_comment`。
            _guard_path = strip_inline_comment(_guard).strip()
            # 契约 §5.4/§5.5（多靶场，beta.16）：已登记靶场路由同属「登记地址」，同门放行。
            if page_routes and not _route_hit(_guard_path, page_routes) and not _route_hit(_guard_path, _target_routes):
                guard_bad.append(f"{g['用例ID']}:{_guard_path}")

        # 契约 §5.6 R7（2026-09-23 补；**2026-09-25 修正为真矛盾对**）：同一条用例内，对同一
        # testid 不得既断言「可见 / 有文案」又断言「不可见」—— 否则必有一条永远为真（假绿）。
        #
        # **修正理由（3509 §B43）**：原实现把 `disabled` 也归入「不可见」类，于是
        # 「disabled X + text X」被判矛盾 —— 而**禁用的按钮照样有文案**，两者可同时成立。
        # 契约 R7 的原文只说了「可见 / 有文案」对「不可见」，并未把 `disabled` 算进去。
        # 矛盾只存在于**两对**之间：
        #   ① `hidden` ↔ 存在类（visible / text / contains / count / value）；
        #   ② `enabled` ↔ `disabled`。
        # `disabled` 与存在类**不构成矛盾**（既可见又禁用的控件是常态）。
        PRESENCE = ("visible", "text", "contains", "count", "value")
        # 契约 §5.6 R7（2026-09-25 按 `§B57` 的步骤锚修正）：矛盾只在**同一时点**里成立 ——
        # 无锚断言属终态那一组，`after:<N>` 归第 N 条 step 之后那一组，两组之间**不跨组比较**。
        # 否则「`after:2 visible modal` + 终态 `initial: hidden modal`」（先开后取消）会被误判自相矛盾。
        verbs_by_slice: dict[tuple, set[str]] = {}
        for raw in raw_exp:
            e = _strip_prefix(raw)
            bits = _code(e).split(" ")
            if len(bits) >= 2 and bits[0] in ASSERT_VERBS and bits[0] != "request":
                verbs_by_slice.setdefault((_step_anchor(raw), bits[1]), set()).add(bits[0])
        for (slice_n, tid), verbs in verbs_by_slice.items():
            where = f"{g['用例ID']}:{tid}" + (f"@after:{slice_n}" if slice_n else "")
            if "hidden" in verbs and verbs & set(PRESENCE):
                contradict.append(where)
            elif "enabled" in verbs and "disabled" in verbs:
                contradict.append(where)
        for e in exp:
            first = _code(e).split(" ", 1)[0].strip()
            if first not in ASSERT_VERBS:
                assert_bad.append(f"{g['用例ID']}:{first}")
            # 契约 §5.5 / §8.2：`waitFor` 是**动作**，不是终态断言 ——
            # `expected` 是终态集合（§5.6 R9），写成断言会让「等一会儿」冒充验证。
            if first == "waitFor":
                waitfor_assert.append(g["用例ID"])
        # 契约 §5.5（2026-10-07 补，P5）：`delta <testid> <±N>` 相对断言的形态项。
        # ① 值必须 = 带符号整数 `±N`（无符号会与绝对值断言词形混淆）；② 不得与 `initial:` /
        #   `unchanged:` / `after:<N>` 叠写（delta 有自己的采样语义：行动前采样、行动后复读，
        #   叠加豁免通道/时点锚后语义不可解释）。（无 `step` 的情形由「分片块字段齐」门承接 ——
        #   step 必填非空，空 step 分片根本进不了本循环；生成器另有中止双保险。）
        for raw in raw_exp:
            body = _strip_prefix(raw)
            if _code(body).split(" ")[0] != "delta":
                continue
            toks = _code(body).split()
            if len(toks) < 3 or not re.fullmatch(r"[+-]\d+", toks[2]):
                delta_bad.append(f"{g['用例ID']}:值形态")
            m_anchor = AFTER_RE.match(raw.lstrip())
            if m_anchor is not None or (m_anchor.group(2) if m_anchor else raw).lstrip().startswith(LINE_PREFIXES):
                delta_bad.append(f"{g['用例ID']}:叠写")
        # D142：`request <api> <json-path> <expected>` 形态门。三态缺席语义、api 后缀、
        # 必须有 step（动作锚点）；`(空)` 因无法区分「缺失 / null」而拒绝。
        for raw in raw_exp:
            has_kind = raw.lstrip().startswith(LINE_PREFIXES)
            code = _code(_strip_prefix(raw))
            if not code.startswith("request "):
                continue
            mreq = re.match(r"^request\s+(\S+)\s+(\S+)\s+(.+)$", code)
            if not mreq:
                request_bad.append(f"{g['用例ID']}:形态（需 request <api> <path> <expected>）")
                continue
            api, _path, expected = mreq.groups()
            if has_kind:
                request_bad.append(f"{g['用例ID']}:与 initial/unchanged 叠写")
            if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", api):
                request_bad.append(f"{g['用例ID']}:api 须为带点后缀（{api}）")
            if expected.strip() == "(空)":
                request_bad.append(f"{g['用例ID']}:(空) 三态不明，请用 (缺席)/null/\"\"")
            if not step:
                request_bad.append(f"{g['用例ID']}:无 step（动作锚点不存在）")
        # 契约 §5.6 R10（2026-10-05 补，P11）：跨页用例终态断言必须落首列页（断言落点页）。
        # 多页用例中，未加 after: 步骤锚的 expected 断言如果在非首列页上求值，会因为目标 DOM 缺失而沦为空洞真。
        pgs = d.get("pages", [])
        if len(pgs) > 1 and known is not None and page_routes_map:
            lead_page = pgs[0]
            lead_route = page_routes_map.get(lead_page)
            # 最后一条 goto 的落点页（click 导航不算 —— R10 只管「steps 明确跳到别页后忘了回跳」）
            last_goto = None
            for s in step:
                parts = _code(s).split(" ", 1)
                if parts[0] == "goto" and len(parts) > 1:
                    last_goto = parts[1].strip()
            landed = None
            if last_goto:
                for slug, route in page_routes_map.items():
                    if route == last_goto or (route != "/" and last_goto.startswith(route + "/")):
                        landed = slug
                        break
            if landed is not None and landed != lead_page:
                # steps 终点不在首列页 ⇒ 终态 hidden 断言对非首列页 DOM 求值时，
                # 首列页元素必然缺席 ⇒ 空洞真（假绿族，R10 的本体）。
                # 存在类断言（visible/text/…）在错页上会如实红（非假绿），不归本门。
                for raw in raw_exp:
                    if _step_anchor(raw) is not None or raw.lstrip().startswith(EXEMPT_PREFIX):
                        continue
                    cleaned = _strip_prefix(raw)
                    toks = _code(cleaned).split()
                    if len(toks) >= 2 and toks[0] == "hidden":
                        tid = toks[1]
                        owner = tid_owner(tid, list(known))
                        if owner == lead_page:
                            cross_page_bad.append(
                                f"{g['用例ID']}:{tid} 归属首列页 {lead_page} 但 steps 终点在 {landed}（{last_goto}）"
                                " —— 须在断言前回跳 goto " + page_routes_map.get(lead_page, "/"))
        if not exp or any(any(w in e for w in PLACEHOLDERS) for e in exp):
            empty_exp.append(g["用例ID"])
        if len(exp) < 1:
            n_assert.append(g["用例ID"])
        if exp and all(any(w in _code(e) for w in EXPECTED_BLACK) or len(_code(e)) <= 2 for e in exp):
            black_exp.append(g["用例ID"])
        if not intent:
            intent_bad.append(g["用例ID"])
        elif len(intent) < 10:
            intent_short.append(g["用例ID"])
        elif any(w in intent for w in INTENT_BLACK):
            intent_bad.append(g["用例ID"])
        if exp and all(any(w in e for w in TOAST_WORDS) for e in exp):
            transient.append(g["用例ID"])
        # 契约 §5.6 R2：持久化写须刷新后复断言。
        # **无条件适用**（2026-09-23 起）：原型靶场的 mock 后端层刷新后仍在
        # （原型环 §5.1），故原型期与实现后同一条规则——不复断言，页内乐观更新
        # 会把什么都没做的用例判绿。
        # 「写」按**提交性控件的 testid 语义段**近似（WRITE_TID_WORDS），不按中文说明命中：
        # 说明里的「新建 / 编辑」多为打开编辑器或填入值（非落盘），会造成成片误报。
        # 例外 ①（校验被拒，什么都没写）与例外 ②（鉴权）由本启发式执行；
        # 例外 ③（纯导航 / 会话内短暂态）语义判不了，不进本校验器（§8 末注）。
        wrote = False
        for s in step:
            code = _code(s).lower()
            if any(w in code for w in AUTH_TID_WORDS):
                continue  # 例外 ②：登录 / 登出不是持久化写
            if any(w in code for w in WRITE_TID_WORDS):
                wrote = True
                break
        rejected = any(any(w in e for w in REJECT_HINTS) for e in exp)
        if wrote and not rejected and not any(any(w in s for w in REFRESH_WORDS) for s in step + exp):
            persist_unverified.append(g["用例ID"])
        # 契约 §5.5：`#` 之后是**给人读的中文说明，机器忽略** ⇒ 本项只扫 `#` 之前的机器部分。
        # （2026-09-25 修：原实现把整行含注释一起扫 ⇒ 「等矫正建议产出」这类
        # 含「等」字的正常中文说明会把用例误报为二选一，WARN 一多就没人看了。）
        if any(any(w in _code(s) for w in ("或", "或者", "e.g.", "等")) for s in step):
            or_step.append(g["用例ID"])
        if any(any(p.search(_code(e)) for p in I18N_HINTS) for e in exp):
            i18n.append(g["用例ID"])
        # 契约 §5.5（2026-09-25 补，3509 §B57）：步骤锚 `after:<N>` 必须是**合法且可达**的时点。
        # N 从 1 起、按分片 `step` 顺序编号；N > len(step) ⇒ 这条断言永远不会被采样 ⇒ FAIL。
        # 写法不合规（`after:x` / 缺空格）也在本项报出 —— 否则会以「expected 动词合法」的
        # 形式报一个看不懂的 verb（`after:x`）。
        for raw in raw_exp:
            body_code = _code(raw)
            if not body_code.startswith("after:"):
                continue
            m = AFTER_RE.match(body_code)
            if not m:
                after_bad.append(f"{g['用例ID']}:写法不合规 {body_code[:24]!r}")
            elif int(m.group(1)) < 1 or int(m.group(1)) > len(step):
                after_bad.append(f"{g['用例ID']}:after:{m.group(1)} 超出 step 条数({len(step)})")
        # 契约 §5.6 R9：`unchanged:` 的**形态项**（文本期可判的部分）
        raw_exp_local = raw_exp
        if any(_nested_prefix(e) for e in raw_exp_local):
            nested_prefix.append(g["用例ID"])
        # 契约 §5.6 R9（2026-09-25 补；`3509 §B36` 的「理由」那一半）：`initial:` 必须配**显式理由**。
        # 理由 = 行尾 `#` 之后的中文说明（与 §5.5 注释约定同源）。**只判「有没有」**：
        # 「理由够不够」是语义项（§6.0 `C-new` 不进文本期门）⇒ 本项只能停在 WARN。
        # 取证（2026-09-25）：全量 65 条 `initial:` 里 9 条无理由。
        for e in raw_exp:
            if e.lstrip().startswith(EXEMPT_PREFIX):
                # 理由 = **真注释**（内核口径：「# 前有空白/行首」）之后的内容。
                # 此前用 `partition("#")` 撞上路径里的 `#`（如 `/console/#/x`）⇒ 把路径尾巴当成理由 = 假「有理由」。
                _raw_code = strip_inline_comment(e)
                _note_text = e[len(_raw_code):].strip(" \t#")
                if not _note_text:
                    initial_no_reason.append(f"{g['用例ID']}:{e.strip()}")
        if any(e.lstrip().startswith(UNCHANGED_PREFIX) for e in raw_exp):
            # 「动作不改变它」若无动作可验，该断言就退化为纯豁免（回落为假绿）⇒ FAIL
            code = " ".join(_code(s).lower() for s in step)
            if not any(w in code for w in UNCHANGED_ACTION_WORDS):
                unchanged_no_action.append(g["用例ID"])

    res.add("expected 非空且无占位", "PASS" if not empty_exp else "FAIL", f"{_format_list(empty_exp)}")
    res.add("step 动词合法", "PASS" if not verb_bad else "FAIL", f"词表外={_format_list(verb_bad)}")
    # 契约 §5.5（2026-10-16 补，issue #R4）：`click` / `hover` 步级开关的值域（仅 `native` 或省略）。
    res.add("step 开关取值合法", "PASS" if not switch_bad else "FAIL",
            f"值域外={_format_list(switch_bad)}")
    res.add("goto 查询键须已声明", "PASS" if not goto_param else "FAIL",
            f"未声明 / 白名单外的查询键={_format_list(goto_param)}（契约 §5.7：`goto` 的查询键须 ∈ `e2e.query_preset.keys` 且 ∈ 本用例 `参数:`）" if goto_param else "")
    res.add("goto 路径 ∈ 页面表", "PASS" if not goto_path else "FAIL", f"页面表外路径={_format_list(goto_path)}")
    res.add("守卫 路径 ∈ 页面表", "PASS" if not guard_bad else "FAIL",
            f"页面表外路径={_format_list(guard_bad)}（契约 §5.5：守卫导航用的具体路径也不得私藏于分片）" if guard_bad else "")
    res.add("auth 取值合法", "PASS" if not auth_bad else "FAIL", f"白名单外（允许 preset|none）={_format_list(auth_bad)}")
    res.add("靶场 取值合法", "PASS" if not target_bad else "FAIL",
            f"不在 `e2e.targets` 闭集内 / 未登记即钉名={_format_list(target_bad)}（契约 §5.4/§5.5：具名靶场必须先在 stack-profile 登记）" if target_bad else "")
    res.add("会话 取值合法", "PASS" if not session_bad else "FAIL",
            f"形态非法 / 白名单外={_format_list(session_bad)}（契约 §5.5：键须在 `e2e.session_preset.keys` 内）" if session_bad else "")
    res.add("参数 声明有效", "PASS" if not inject_bad else "FAIL",
            f"`参数:` 声明不合法={_format_list(inject_bad)}（契约 §5.5：只声明键、须在 `e2e.query_preset.keys` 内、且须被某个 `goto` 用到）" if inject_bad else "")
    res.add("参数 值形态", "PASS" if not inject_value_bad else "FAIL",
            f"查询值含越形态字符={_format_list(inject_value_bad)}（契约 §5.5：禁空白 / 引号 / 反斜杠 / `&` / `#`）" if inject_value_bad else "")
    res.add("会话·参数 同键不叠写", "PASS" if not dual_carrier_bad else "FAIL",
            f"同键双载体={_format_list(dual_carrier_bad)}（契约 §5.5：两个载体写同一键 ⇒ 前提不可解释）" if dual_carrier_bad else "")
    res.add("goto hash 查询键须已声明", "PASS" if not hash_goto_param else "FAIL",
            f"未声明 / 白名单外的 hash 查询键={_format_list(hash_goto_param)}（契约 §5.5：`goto` 的 hash 查询键须 ∈ `e2e.query_preset.hash_keys` 且 ∈ 本用例 `hash参数:`）" if hash_goto_param else "")
    res.add("hash 参数 声明有效", "PASS" if not hash_inject_bad else "FAIL",
            f"`hash参数:` 声明不合法={_format_list(hash_inject_bad)}（契约 §5.5：只声明键、须在 `e2e.query_preset.hash_keys` 内、且须被某个 `goto` 的 hash 查询用到）" if hash_inject_bad else "")
    res.add("hash 参数 值形态", "PASS" if not hash_value_bad else "FAIL",
            f"hash 查询值含越形态字符={_format_list(hash_value_bad)}（契约 §5.5：禁空白 / 引号 / 反斜杠 / `&` / `#`）" if hash_value_bad else "")
    res.add("hash参数·其他载体 同键不叠写", "PASS" if not hash_dual_carrier_bad else "FAIL",
            f"同键双载体={_format_list(hash_dual_carrier_bad)}（契约 §5.5：`hash参数:` 与 `参数:`/`会话:` 不得写同一键）" if hash_dual_carrier_bad else "")
    res.add("断言不自相矛盾", "PASS" if not contradict else "FAIL",
            f"同一 testid 既断言可见又断言不可见={_format_list(contradict)}")
    res.add("expected 动词合法", "PASS" if not assert_bad else "FAIL", f"词表外={_format_list(assert_bad)}")
    res.add("waitFor 属动作", "PASS" if not waitfor_assert else "FAIL",
            f"`waitFor` 出现在 expected（应写在 step）= {_format_list(waitfor_assert)}")
    res.add("delta 相对断言形态", "PASS" if not delta_bad else "FAIL",
            f"`delta` 值须为 `±N` 且不得与豁免通道/步骤锚叠写 = {_format_list(delta_bad)}")
    res.add("request 断言形态", "PASS" if not request_bad else "FAIL",
            f"`request` 需 api 带点后缀 + json-path + 三态值，且必须有 step = {_format_list(request_bad)}")
    res.add("豁免前缀不嵌套", "PASS" if not nested_prefix else "FAIL", f"{_format_list(nested_prefix)}")
    res.add("步骤锚合法", "PASS" if not after_bad else "FAIL", f"{_format_list(after_bad)}")
    res.add("跨页终态断言落首列页", "PASS" if not cross_page_bad else "FAIL", f"{_format_list(cross_page_bad)}")
    res.add("initial 豁免带理由", "PASS" if not initial_no_reason else "WARN", f"{_format_list(initial_no_reason)}")
    res.add("unchanged 用例有提交性动作", "PASS" if not unchanged_no_action else "FAIL",
            f"无动作可验={_format_list(unchanged_no_action)}")
    res.add("断言数 ≥ 1", "PASS" if not n_assert else "FAIL", f"{_format_list(n_assert)}")
    res.add("expected 可判定", "PASS" if not black_exp else "WARN", f"黑名单={_format_list(black_exp)}")
    res.add("intent 完整", "PASS" if not intent_bad else "FAIL", f"缺失/模糊={_format_list(intent_bad)}")
    res.add("intent 长度", "PASS" if not intent_short else "WARN", f"过短={_format_list(intent_short)}")
    res.add("非瞬时断言", "PASS" if not transient else "WARN", f"{_format_list(transient)}")
    res.add("持久化写复断言", "PASS" if not persist_unverified else "WARN",
            f"{_format_list(persist_unverified)} (💡 提示: 包含写入/提交动作后，建议在 step 补充 `refresh` 并在 expected 复查断言，防乐观更新假阳性)" if persist_unverified else "")
    res.add("步骤非二选一", "PASS" if not or_step else "WARN", f"{_format_list(or_step)}")
    # 容忍前提措辞（issue #47，D176）：见 TOLERANT_BLACK 注释——扫 precondition 全文 +
    # step/expected 的注释尾巴（不扫代码部分），`容忍: <理由>` 显式豁免。
    tol_hits = []
    for cid, d in blocks.items():
        texts = [ln.strip() for ln in d.get("precondition", [])]
        for key in ("step", "expected"):
            for ln in d.get(key, []):
                raw = ln.strip()
                code = _code(raw)
                if code == raw:
                    continue  # 无注释尾巴
                texts.append(raw[len(code):].strip().lstrip("#").strip())
        for t in texts:
            if "容忍:" in t or "容忍：" in t:
                continue
            word = next((w for w in TOLERANT_BLACK if w in t), None)
            if word:
                tol_hits.append(f"{cid}:{word}")
    res.add("容忍前提措辞", "PASS" if not tol_hits else "WARN",
            (f"{_format_list(tol_hits)} (💡 改为显式前置复位或值断言；确属业务文案/已评估 ⇒ 行尾 `# 容忍: <理由>` 豁免)")
            if tol_hits else "")
    res.add("文案为渲染后文案", "PASS" if not i18n else "WARN", f"疑似 i18n/枚举={_format_list(i18n)}")
    # 契约 §5.7：结构化 `seed:` 的实体 × 字段 ⇔ structure 的 data-models 事实（静态对账）
    _lvl, _det = seed_models_check(root, blocks)
    res.add("seed × models 对账", _lvl, _det)
    # 契约 §5.5（B201-1，2026-10-12）：upload 行的 fixture 引用存在（值形态 + 文件存在）
    _lvl, _det = upload_fixture_check(root, blocks, lay)
    res.add("upload fixture 引用存在", _lvl, _det)
    # D143：manual.md 旧行 + `atlas-manual` 块（解析单源 `_support/manual_block.py`）
    manual_path = e2e / "manual.md"
    if not manual_path.is_file():
        res.add("manual 走查项形态", "N/A", "无 manual.md（可选增强）")
    else:
        try:
            from _support.manual_block import parse_manual
            manual_items = parse_manual(manual_path.read_text(encoding="utf-8"))
        except Exception as exc:  # 坏块必须响亮失败，不得静默忽略
            res.add("manual 走查项形态", "FAIL", f"解析失败：{exc}")
        else:
            manual_bad: list[str] = []
            seen_ids: set[str] = set()
            for m in manual_items:
                mid = m.get("id") or ""
                if not mid:
                    manual_bad.append("缺 ID")
                elif mid in seen_ids:
                    manual_bad.append(f"{mid}:ID 重复")
                seen_ids.add(mid)
                if m.get("page") not in known:
                    manual_bad.append(f"{mid}:页面不在页面表（{m.get('page')}）")
                steps = m.get("steps") or []
                for i, s in enumerate(steps, 1):
                    if not s.get("action") or not s.get("expect"):
                        manual_bad.append(f"{mid}:步骤{i} 缺操作/观察")
            res.add("manual 走查项形态", "PASS" if not manual_bad else "FAIL",
                    f"{_format_list(manual_bad)}" if manual_bad else "")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    res = validate(root)
    if args.json:
        print(json.dumps({"ok": res.status != "FAIL", "status": res.status,
                          "root": str(root), "checks": res.checks}, ensure_ascii=False, indent=2))
    else:
        print(f"validate_e2e_index @ {root}")
        for c in res.checks:
            line = f"  [{c['level']:<4}] {c['check']}"
            # RFC-20261105-01 b1：`N/A` 全开（既有 7 处 detail 均为固定中文短语）；`PASS` 仅在
            # detail 带诊断（字面量哨兵 `未采信表=`）时才多打一行——改 note 文案须同步此处。
            if c["detail"] and (c["level"] not in ("PASS",) or "未采信表=" in c["detail"]):
                line += f" —— {c['detail']}"
            print(line)
        print(res.status)
    return 1 if res.status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
