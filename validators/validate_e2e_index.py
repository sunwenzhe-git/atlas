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
  * 「goto 不带查询参数」为**结构门 FAIL**（契约 §5.7）：原型专有调试参数（`?state=` 等）
    在真实应用上不存在，用例一旦依赖它就过不了第二段。
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

MAIN_COLUMNS = ["用例ID", "页面", "中文标题", "类型", "关联AC", "需求", "状态", "状态原因", "分片"]
REV_COLUMNS = ["页面", "断言落点用例", "链路经过用例"]

TYPES = {"smoke", "acceptance", "exception", "permission"}
STATES = {"red", "prototype-pass", "green", "blocked", "skipped"}
REASON_PREFIX = {"ENV_ISSUE", "NOT_IMPLEMENTED", "SPEC_AMBIGUOUS", "BLOCKED_DEP", "DEFERRED", "OUT_OF_SCOPE", "OTHER"}

ID_RE = re.compile(r"^E2E-[A-Z0-9]+-\d{3}$")
AC_RE = re.compile(r"^AC-[A-Z0-9]+-\d{3}$")
# 契约 §8.2（2026-09-25 补）：PRD 环登记「结构类 AC」的小节标题 ——
# 该小节内的 AC 其被测属性**只能在初始态观测**（骨架 / 默认面板 / 按数据渲染构成）。
STRUCT_LIST_HEAD = "#### 结构类 AC 清单"
STRUCT_AC_RE = re.compile(r"AC-[A-Z0-9]+-\d{3}")
SHARD_RE = re.compile(r"cases/(?P<file>[^#)\s]+)#(?P<anchor>[a-z0-9-]+)")
HEAD = re.compile(r"^##\s+(E2E-[A-Za-z0-9-]+)\b.*$", re.M)
BLOCK = re.compile(r"```atlas-case\s*\n(.*?)```", re.S)
PLACEHOLDERS = ("TODO", "待补充", "TBD", "待定", "[FIELD:", "视情况而定", "后续补充")

EXPECTED_BLACK = ("正常", "无", "OK", "显示正确", "工作正常")
INTENT_BLACK = ("显示正确", "功能正常", "页面正常")
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
ACTION_VERBS = ("click", "fill", "select", "check", "uncheck", "press", "hover", "refresh", "goto", "waitFor", "download")
ASSERT_VERBS = ("text", "contains", "count", "countOptions", "visible", "hidden", "enabled", "disabled", "checked", "unchecked", "value", "attr", "delta")
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
    return line.split("#", 1)[0].strip()


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
    models: dict[str, str] = {}
    for f in facts:
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if not ln.startswith("|"):
                continue
            cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] and cells[0] != "表/模型" \
                    and not set(cells[0]) <= set("-: "):
                models.setdefault(cells[0], cells[1])
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
            blocks[m.group(1)] = d
    return blocks, pages


def validate(root: Path) -> Result:
    res = Result()
    e2e = root / "product" / "e2e"
    index = e2e / "e2e-index.md"
    cases = e2e / "cases"
    shard_files = sorted(cases.glob("*.md")) if cases.is_dir() else []
    if not index.is_file() and not shard_files:
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
    res.add("行字段完整", "PASS" if not field_bad else "FAIL", f"{field_bad[:8]}")

    # 分片块
    blocks, file_page = gather_shards(cases) if cases.is_dir() else ({}, {})
    needed = ("id", "pages", "precondition", "step", "expected", "testid")
    block_bad = [i for i, d in blocks.items() if any(not d.get(k) for k in needed)]
    res.add("分片块字段齐", "PASS" if not block_bad else "FAIL", f"缺字段={block_bad[:8]}")

    orphan = sorted(set(blocks) - set(ids))
    dead = sorted(set(ids) - set(blocks))
    res.add("索引↔分片无孤儿/死链", "PASS" if not orphan and not dead else "FAIL",
             f"孤儿(分片有索引无)={orphan[:6]} 死链(索引有分片无)={dead[:6]}")

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
    res.add("分片链接可达", "PASS" if not link_bad else "FAIL", f"{link_bad[:8]}")
    res.add("索引↔分片标题一致", "PASS" if not title_bad else "FAIL", f"{title_bad[:8]}")

    # pages 合法性（E1：页清单唯一来源 = 索引页面表 §3.2；无页面表时退化为分片文件名）
    idx_text = text
    page_rows = [ln for ln in idx_text.splitlines()
                 if re.match(r"^\|\s*[a-z0-9][a-z0-9-]*\s*\|\s*/", ln)]
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
            routes.append(route)
        page_routes = routes
        page_routes_map = {}
        for ln in page_rows:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in ("页面", "---"):
                page_routes_map[cells[0]] = cells[1]
        res.add("页面表合法", "PASS" if not page_bad2 else "FAIL",
                f"路由非/开头或重复={page_bad2[:8]}" if page_bad2 else "")
    if known is None:
        known = {md.stem for md in (root / "product" / "e2e" / "cases").glob("*.md")}
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

    # 关联AC
    ac_bad = [g["用例ID"] for g in grid if not AC_RE.match(g["关联AC"])]
    res.add("关联AC 格式", "PASS" if not ac_bad else "FAIL", f"{ac_bad[:8]}")
    prd_files = sorted((root / "product" / "prd").glob("*-prd.md")) if (root / "product" / "prd").is_dir() else []
    if not prd_files:
        res.add("关联AC 可达", "N/A", "门控态：无域级 PRD")
    else:
        corpus = "".join(p.read_text(encoding="utf-8") for p in prd_files)
        unreachable = [g["用例ID"] for g in grid if g["关联AC"] not in corpus]
        res.add("关联AC 可达", "PASS" if not unreachable else "FAIL", f"不可达={unreachable[:8]}")

    # AC 反向覆盖（追溯门，契约 §8.2；2026-10-04 补，`3509 §B186-2`）——追溯链末段
    # 「AC → E2E 用例」此前无门（`validate_prd.py` 参数 4 只盖「规则 ↔ AC」）⇒ 已实现域能带
    # 零挂靠 AC 收口（2026-10-04 实测：AC 129 / 索引已关联 80 / 已实现域零挂靠 9，其中
    # voice-library 6 条在该域独立审查 PASS + 走查单落盘之后仍在）。
    # 分级沿用 §8.1 testid 门先例：域内页面**全** `已实现` ⇒ 严判；含 `实现中` / `未开始` ⇒
    # 该域不参与（用例尚未长出，不是缺口）。**首版 WARN 不 FAIL**——「不可验 AC」的机器可解析
    # 豁免落点未定型（`§B36` 过早 FAIL 被量推翻的先例）；落点定形即升 FAIL。
    # 覆盖关系是**派生量**（真相源 = 主表 `关联AC` 列 + 域级 PRD §五 AC 定义行），不落第 4 张
    # 手工表（`single-source.md` §4：同一信息两处正文即漂移）。
    dom_status: dict[str, set[str]] = {}
    for ln in page_rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("页面", "---"):
            continue
        for dom in re.split(r"\s*·\s*", cells[2]):
            if dom and dom != "—":
                dom_status.setdefault(dom, set()).add(cells[3])
    dom_acs: dict[str, set[str]] = {}
    for pf in prd_files:
        seg = pf.read_text(encoding="utf-8")
        fm_text = seg.split("---")[1] if seg.startswith("---") else ""
        m_slug = re.search(r"^domain:\s*(\S+)", fm_text, re.M)
        if not m_slug:
            continue
        dom_acs[m_slug.group(1)] = {
            m.group(1) for m in re.finditer(r"^\|\s*`?(AC-[A-Z0-9]+-\d{3})`?\s*\|", seg, re.M)
        }
    if not dom_acs or not dom_status:
        res.add("AC 反向覆盖", "N/A", "域级 PRD 无 `domain:` 声明，或索引无页面表")
    else:
        covered_ac = {g["关联AC"] for g in grid}
        gaps: list[str] = []
        for dom in sorted(dom_acs):
            if dom_status.get(dom) != {"已实现"}:
                continue
            missing = sorted(dom_acs[dom] - covered_ac)
            if missing:
                gaps.append(f"{dom}:{'/'.join(missing)}")
        res.add("AC 反向覆盖", "PASS" if not gaps else "WARN",
                f"已实现域零挂靠={gaps[:6]}" if gaps else "")

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
        zero_bad = [f"{g['用例ID']}({g['关联AC']})" for g in zero_evidence if g["关联AC"] not in struct_acs]
        res.add("零证据用例须挂结构类 AC", "PASS" if not zero_bad else "FAIL",
                f"全 initial: 但 AC 非结构类={zero_bad[:8]}")

    # ---- 有意义门 ----
    empty_exp, black_exp, n_assert, intent_bad, intent_short = [], [], [], [], []
    transient, persist_unverified, or_step, i18n = [], [], [], []
    verb_bad, assert_bad, goto_param, contradict = [], [], [], []
    goto_path: list[str] = []
    auth_bad: list[str] = []
    nested_prefix, unchanged_no_action = [], []
    initial_no_reason = []
    after_bad = []
    waitfor_assert = []
    delta_bad = []
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
            first = s.split("#", 1)[0].strip().split(" ", 1)[0].strip()
            if first not in ACTION_VERBS:
                verb_bad.append(f"{g['用例ID']}:{first}")
        # 契约 §5.7（2026-09-23 补）：用例**不得**依赖原型专有的调试/演示参数。
        # `goto` 带查询参数 ⇒ FAIL —— 那种手段在真实应用上不存在，用例过不了第二段。
        for s in step:
            code = s.split("#", 1)[0].strip()
            parts = code.split(" ", 1)
            if parts[0] == "goto" and "?" in (parts[1] if len(parts) > 1 else ""):
                goto_param.append(f"{g['用例ID']}:{parts[1].strip()}")
        # 契约 §5.5（2026-09-30 补）：`goto` 路径必须命中页面表的「路由」列（唯一真相源）——
        # 挡「原型时代路径漂移」（实测 `goto /home` 而页面表为 `/`，真栈上 404 进 NotFound 页）。
        # 匹配规则：精确命中，或**非根路由**的子路径前缀命中（`/projects/x` 匹配 `/projects`，
        # 动态段用例友好）；根路由 `/` 仅精确匹配（否则一切路径都被它吞掉）。
        # `goto` 缺路径参数也是 FAIL（独立审查 D4：否则校验器放行、生成器渲染 `page.goto("")`）。
        for s in step:
            code = s.split("#", 1)[0].strip()
            parts = code.split(" ", 1)
            if parts[0] != "goto":
                continue
            if len(parts) < 2 or not parts[1].strip():
                goto_path.append(f"{g['用例ID']}:<缺路径>")
                continue
            if not page_routes:
                continue
            p = parts[1].strip()
            if p in page_routes:
                continue
            if any(r != "/" and p.startswith(r + "/") for r in page_routes):
                continue
            goto_path.append(f"{g['用例ID']}:{p}")
        # 契约 §5.7（2026-09-30 补）：`auth` 取值白名单（preset | none）——文本期挡住，
        # 与生成器中止双保险（独立审查 D3：生成器白名单此前只覆盖 python 路径）。
        auth = d.get("auth", "preset")
        if auth not in ("preset", "none"):
            auth_bad.append(f"{g['用例ID']}:auth={auth}")
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
            bits = e.split("#", 1)[0].strip().split(" ")
            if len(bits) >= 2 and bits[0] in ASSERT_VERBS:
                verbs_by_slice.setdefault((_step_anchor(raw), bits[1]), set()).add(bits[0])
        for (slice_n, tid), verbs in verbs_by_slice.items():
            where = f"{g['用例ID']}:{tid}" + (f"@after:{slice_n}" if slice_n else "")
            if "hidden" in verbs and verbs & set(PRESENCE):
                contradict.append(where)
            elif "enabled" in verbs and "disabled" in verbs:
                contradict.append(where)
        for e in exp:
            first = e.split("#", 1)[0].strip().split(" ", 1)[0].strip()
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
        # 契约 §5.6 R10（2026-10-05 补，P11）：跨页用例终态断言必须落首列页（断言落点页）。
        # 多页用例中，未加 after: 步骤锚的 expected 断言如果在非首列页上求值，会因为目标 DOM 缺失而沦为空洞真。
        pgs = d.get("pages", [])
        if len(pgs) > 1 and known is not None and page_routes_map:
            lead_page = pgs[0]
            lead_route = page_routes_map.get(lead_page)
            # 最后一条 goto 的落点页（click 导航不算 —— R10 只管「steps 明确跳到别页后忘了回跳」）
            last_goto = None
            for s in step:
                parts = s.split("#", 1)[0].strip().split(" ", 1)
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
                    toks = cleaned.split("#", 1)[0].strip().split()
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
            code = s.split("#", 1)[0].lower()
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
        if any(any(w in s.split("#", 1)[0] for w in ("或", "或者", "e.g.", "等")) for s in step):
            or_step.append(g["用例ID"])
        if any(any(p.search(_code(e)) for p in I18N_HINTS) for e in exp):
            i18n.append(g["用例ID"])
        # 契约 §5.5（2026-09-25 补，3509 §B57）：步骤锚 `after:<N>` 必须是**合法且可达**的时点。
        # N 从 1 起、按分片 `step` 顺序编号；N > len(step) ⇒ 这条断言永远不会被采样 ⇒ FAIL。
        # 写法不合规（`after:x` / 缺空格）也在本项报出 —— 否则会以「expected 动词合法」的
        # 形式报一个看不懂的 verb（`after:x`）。
        for raw in raw_exp:
            body_code = raw.split("#", 1)[0].strip()
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
                _code_part, _sep, _note_text = e.partition("#")
                if not _sep or not _note_text.strip():
                    initial_no_reason.append(f"{g['用例ID']}:{e.strip()}")
        if any(e.lstrip().startswith(UNCHANGED_PREFIX) for e in raw_exp):
            # 「动作不改变它」若无动作可验，该断言就退化为纯豁免（回落为假绿）⇒ FAIL
            code = " ".join(s.split("#", 1)[0].lower() for s in step)
            if not any(w in code for w in UNCHANGED_ACTION_WORDS):
                unchanged_no_action.append(g["用例ID"])

    res.add("expected 非空且无占位", "PASS" if not empty_exp else "FAIL", f"{empty_exp[:8]}")
    res.add("step 动词合法", "PASS" if not verb_bad else "FAIL", f"词表外={verb_bad[:8]}")
    res.add("goto 不带查询参数", "PASS" if not goto_param else "FAIL", f"依原型调试参数的用例={goto_param[:8]}")
    res.add("goto 路径 ∈ 页面表", "PASS" if not goto_path else "FAIL", f"页面表外路径={goto_path[:8]}")
    res.add("auth 取值合法", "PASS" if not auth_bad else "FAIL", f"白名单外（允许 preset|none）={auth_bad[:8]}")
    res.add("断言不自相矛盾", "PASS" if not contradict else "FAIL",
            f"同一 testid 既断言可见又断言不可见={contradict[:8]}")
    res.add("expected 动词合法", "PASS" if not assert_bad else "FAIL", f"词表外={assert_bad[:8]}")
    res.add("waitFor 属动作", "PASS" if not waitfor_assert else "FAIL",
            f"`waitFor` 出现在 expected（应写在 step）= {waitfor_assert[:8]}")
    res.add("delta 相对断言形态", "PASS" if not delta_bad else "FAIL",
            f"`delta` 值须为 `±N` 且不得与豁免通道/步骤锚叠写 = {delta_bad[:8]}")
    res.add("豁免前缀不嵌套", "PASS" if not nested_prefix else "FAIL", f"{nested_prefix[:8]}")
    res.add("步骤锚合法", "PASS" if not after_bad else "FAIL", f"{after_bad[:8]}")
    res.add("跨页终态断言落首列页", "PASS" if not cross_page_bad else "FAIL", f"{cross_page_bad[:8]}")
    res.add("initial 豁免带理由", "PASS" if not initial_no_reason else "WARN", f"{initial_no_reason[:8]}")
    res.add("unchanged 用例有提交性动作", "PASS" if not unchanged_no_action else "FAIL",
            f"无动作可验={unchanged_no_action[:8]}")
    res.add("断言数 ≥ 1", "PASS" if not n_assert else "FAIL", f"{n_assert[:8]}")
    res.add("expected 可判定", "PASS" if not black_exp else "WARN", f"黑名单={black_exp[:8]}")
    res.add("intent 完整", "PASS" if not intent_bad else "FAIL", f"缺失/模糊={intent_bad[:8]}")
    res.add("intent 长度", "PASS" if not intent_short else "WARN", f"过短={intent_short[:8]}")
    res.add("非瞬时断言", "PASS" if not transient else "WARN", f"{transient[:8]}")
    res.add("持久化写复断言", "PASS" if not persist_unverified else "WARN", f"{persist_unverified[:8]}")
    res.add("步骤非二选一", "PASS" if not or_step else "WARN", f"{or_step[:8]}")
    res.add("文案为渲染后文案", "PASS" if not i18n else "WARN", f"疑似 i18n/枚举={i18n[:8]}")
    # 契约 §5.7：结构化 `seed:` 的实体 × 字段 ⇔ structure 的 data-models 事实（静态对账）
    _lvl, _det = seed_models_check(root, blocks)
    res.add("seed × models 对账", _lvl, _det)
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
            if c["detail"] and c["level"] not in ("PASS", "N/A"):
                line += f" —— {c['detail']}"
            print(line)
        print(res.status)
    return 1 if res.status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
