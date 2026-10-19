#!/usr/bin/env python3
"""atlas 结构环校验器 —— 按 `rings/structure/reference.md` §7 校验清单对结构产物做机器校验。

- **框架无关**：本文件不得出现任何具体框架名（共享契约 global-rules.md §1）。
- 纯标准库；对 `<项目根>/.trellis/spec/structure/` 可回归。
- 输出 PASS / FAIL；有 FAIL 时非零退出。

用法：
    python3 validate_structure.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# profile 单源解析（2026-10-12 单源批口径，与 `validate_stack_profile` 同一条加载路径；
# 判定面白名单不在内核、各消费者自持——本处只取 `adapters` 的**声明值**，形态/合法性
# 校验仍归 `validate_stack_profile`）。
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.siblings import load_module  # noqa: E402

_sp_profile = load_module("stack_profile")

DEFAULT_MAX_TOTAL = 9500
DOMAIN_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

TABLE_DIRECTORY_MAP = ["路径", "类型", "职责（一句话）", "域", "备注"]
TABLE_ROUTES = ["页面/路由", "域", "用途", "关键交互", "实现状态", "来源文件"]
TABLE_DATA_MODELS = ["表/模型", "字段", "类型", "约束/默认", "关系", "枚举"]
TABLE_APIS = ["方法", "路径", "用途", "请求要点", "响应要点", "来源模块"]

FORBIDDEN = ["TODO", "待补充", "TBD", "待定", "(To be filled)", "[FIELD:]", "视情况而定", "后续补充"]

SECRET_RES = [
    re.compile(r"\bsk-[A-Za-z0-9]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|passwd|password|secret|access[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})"),
]
PATH_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,6}$")


class Result:
    def __init__(self) -> None:
        self.ok = True
        self.rows: list[dict] = []
        self.warns: list[dict] = []

    def add(self, check: str, ok: bool, detail: str = "") -> None:
        if not ok:
            self.ok = False
        self.rows.append({"check": check, "ok": ok, "detail": detail})

    def add_warn(self, check: str, detail: str) -> None:
        # WARN = 提示补，不置红、不影响退出码（契约 §7「校验器记 WARN」的通道）
        self.warns.append({"check": check, "detail": detail})


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def norm_cell(c: str) -> str:
    return c.strip().strip("`").replace("\\|", "|").strip()


def split_row(ln: str) -> list[str]:
    """按**未转义**的 `|` 切分表格行；单元格内的 `\\|` 还原为 `|`（与 refresh_structure
    的 render_table 转义配对，2026-10-04：字段类型 `datetime | None` 一类含竖线的值
    曾被裸切分撑列，行被 len 过滤静默丢弃）。"""
    s = ln.strip()
    body = s[1:-1] if s.endswith("|") else s[1:]
    return [norm_cell(c) for c in re.split(r"(?<!\\)\|", body)]


def first_table(text: str) -> list[str] | None:
    lines = text.splitlines()
    for i in range(len(lines) - 1):
        if not lines[i].lstrip().startswith("|"):
            continue
        sep = lines[i + 1]
        if re.match(r"^\s*\|?[\s:|-]+\|", sep) and "-" in sep:
            return split_row(lines[i])
    return None


def table_rows(text: str, header: list[str]) -> list[dict]:
    lines = text.splitlines()
    for i in range(len(lines) - 1):
        if not lines[i].lstrip().startswith("|"):
            continue
        if not re.match(r"^\s*\|?[\s:|-]+\|", lines[i + 1]) or "-" not in lines[i + 1]:
            continue
        rows = []
        for ln in lines[i + 2:]:
            if not ln.lstrip().startswith("|"):
                break
            cells = split_row(ln)
            if len(cells) == len(header):
                rows.append(dict(zip(header, cells)))
        return rows
    return []


def frontmatter(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    return text[3:end]


def paths_block(fm: str) -> tuple[bool, str]:
    lines = fm.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*paths\s*:\s*(.*)$", ln)
        if not m:
            continue
        if m.group(1).strip():
            return False, "paths 是标量（malformed）"
        j = i + 1
        items = []
        while j < len(lines) and (not lines[j].strip() or re.match(r"^\s+-", lines[j])):
            if lines[j].strip():
                items.append(lines[j].strip())
            j += 1
        return (bool(items), "" if items else "paths 列表为空")
    return False, "缺 paths 键"


def read_max_total(root: Path) -> int:
    cfg = root / ".trellis" / "config.yaml"
    if cfg.is_file():
        m = re.search(r"^\s*max_total_chars:\s*(\d+)", cfg.read_text(encoding="utf-8"), re.M)
        if m:
            return int(m.group(1))
    return DEFAULT_MAX_TOTAL


def _path_candidates(text: str):
    for tok in re.findall(r"`([^`\n]+)`", text):
        t = re.sub(r":\d+(?:-\d+)?$", "", tok.strip())
        if t.startswith(("~", "http://", "https://", "{", "<", "/", "npm ", "pip ", "python3 ", "bash ")):
            continue
        if "/" not in t:
            continue
        if not (PATH_EXT_RE.search(t) or "*" in t):
            continue
        if any(ch in t for ch in " ()<>|{}"):
            continue
        yield t


# categories.A/H 的合法处置 token（**枚举判定**，契约 `rings/structure/reference.md` §7）
_CAT_TOKENS = ("covered", "skipped", "added")
# token 之后必须是**显式分隔符**或串尾：散文（取证文本）只准接在分隔符之后
_CAT_EVIDENCE_SEP = "：:（(，,。；;、）)"
# 可选标签前缀（F17 容错：`A: covered` / `H：covered`）。字符集排除分隔符与换行，
# 长度封顶 6——防「一整段散文 + 冒号 + token」绕行（如 `本轮不做，因为：added`）。
_CAT_LABEL_RE = re.compile(r"^[^：:（(，,。；;、）)\n]{1,6}[：:]")


def _as_cat_token(s: str) -> str:
    """`s` 若以合法 token **声明**开头（token 后接显式分隔符或串尾）⇒ 返回该 token。"""
    s = s.strip()
    for kw in _CAT_TOKENS:
        if s == kw or (s.startswith(kw) and s[len(kw)] in _CAT_EVIDENCE_SEP):
            return kw
    return ""


def _cat_token(val: str) -> str:
    """从 `categories.A/H` 取值里取出**声明位置**上的处置 token；不识别 ⇒ `""`。

    为何不能全文找关键词（2026-10-15 修，issue #6 现场实证）：契约对这两个字段的语义是
    **枚举判定**（A: `covered|skipped`；H: `covered|added`，adopt 下不得 `skipped`），
    而旧实现是「文本里出现过该词即算」⇒ 把**描述未完成**的措辞判成**已完成**：

        '待核准：…核准后补写为 added'   → 'added'    # 说的正是尚未补写
        'covered 与否未定，也不含其他词' → 'covered'
        '这个类别 stayed skipped 因为没人管' → 'skipped'
        '本轮不做'                      → '本轮不做'  # 唯一正确报红的形态

    新判据锚定**声明位置**：允许一个可选 `<标签>:` 前缀（保住 F17 的 `A: covered` /
    `H：covered`），随后必须是枚举 token，且 token 之后跟显式分隔符或串尾。
    token 后直接接非分隔符内容（`covered 与否未定`）⇒ 不识别 ⇒ `""` ⇒ 必然 FAIL。
    """
    s = val.strip()
    t = _as_cat_token(s)
    if t:
        return t
    m = _CAT_LABEL_RE.match(s)
    return _as_cat_token(s[m.end():]) if m else ""


# D 类形态 token（2026-10-15：跨产物声明一致判据用）。template 的 `categories.D` 三态 =
# 清单（用户确认无描述）| 指针（有机器可读描述：<地址，可在仓外>）| 未取证：<取证>。
# 锚定判据与 `_cat_token` 同款（F38 一族）：token 必须在声明位（首位或可选 `<标签>:`
# 前缀之后）、后接显式分隔符或串尾——散文里「提到指针」≠ 声明为指针。
_D_FORM_TOKENS = ("清单", "指针", "未取证")
# 接线不相容形态（`shared/stack-profile.md` §3.5）：指针 / 未取证形态下该类别**不得接**
# 源码枚举适配器（adapters.api 应置 null）。
_D_WIRE_INCOMPATIBLE = ("指针", "未取证")


def _d_form_token(val: str) -> str:
    """`categories.D` 取值里**声明位置**上的形态 token；不识别 ⇒ `""`（未声明）。

    顺序与 `_cat_token` 同款（2026-10-15 实测咬合：标签前缀正则会把「未取证」本身
    当 `<标签>:` 前缀吃掉）——先试声明位直取，标签前缀匹配只是兜底。"""
    def _direct(s: str) -> str:
        for kw in _D_FORM_TOKENS:
            if s == kw or (s.startswith(kw) and s[len(kw)] in _CAT_EVIDENCE_SEP):
                return kw
        return ""

    s = val.strip()
    t = _direct(s)
    if t:
        return t
    m = _CAT_LABEL_RE.match(s)
    return _direct(s[m.end():]) if m else ""


def _pointer_declared(t: str) -> bool:
    """`apis.md` 是否**声明**了指针形态（2026-10-15 F44 重写，F38 同族锚定）。

    旧判据 = 无锚定子串 `"真相源" in t` —— 全文**提到**「真相源」即算指针 ⇒ 清单型
    `apis.md` 的语义段只要写一句「本域接口真相源由网关维护」，整表就被误判
    「清单与指针混写」FAIL（issue #6 同族疾病在兄弟判据上的残留）。

    新判据锚定**声明位置**（与 `_cat_token` / `_d_form_token` 同款）：某个
    **行首**（或表格**单元格**首）出现 token，其后接显式分隔符或就此结束才算
    ——契约 §4 D「有 → 记真相源入口 + 访问方式」的落笔形态就是行首 `真相源：…`。
    散文里的「…真相源由网关维护…」提及一律不算；真按指针落笔时豁免照常成立。"""
    for ln in t.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            for c in cells:
                if c.startswith("真相源") and (c == "真相源"
                                               or c[len("真相源")] in _CAT_EVIDENCE_SEP):
                    return True
            continue
        if s.startswith("真相源") and (len(s) == len("真相源")
                                        or s[len("真相源")] in _CAT_EVIDENCE_SEP):
            return True
    return False


def validate(root: Path) -> Result:
    res = Result()
    spec = root / ".trellis" / "spec" / "structure"

    if not spec.is_dir():
        res.add("域模型", False, f"缺少结构事实根 {spec}")
        return res

    meta_path = spec / "_meta.json"
    if not meta_path.is_file():
        res.add("域模型", False, "缺少 _meta.json")
        return res
    try:
        meta = json.loads(read(meta_path))
    except (OSError, json.JSONDecodeError) as e:
        res.add("域模型", False, f"_meta.json 无法解析: {e}")
        return res

    # 绿地豁免：apps[].path 均不存在（尚无应用代码）时，域清单与 global 事实允许为空骨架
    app_paths = [a.get("path") for a in (meta.get("apps") or [])
                 if isinstance(a, dict) and a.get("path")]
    greenfield = bool(app_paths) and not any((root / ap).exists() for ap in app_paths)

    domains = meta.get("domains") or []
    ids = [d.get("id") for d in domains if isinstance(d, dict)]
    bad_ids = [i for i in ids if not (isinstance(i, str) and DOMAIN_ID_RE.match(i))]
    dup = sorted({i for i in ids if i and ids.count(i) > 1})
    no_globs = [d.get("id") for d in domains
                if not (isinstance(d, dict) and isinstance(d.get("globs"), list) and d.get("globs"))]
    disk = sorted(p.stem for p in (spec / "domains").glob("*.md")) if (spec / "domains").is_dir() else []
    res.add("域模型 · domains[]", (bool(domains) or greenfield) and not bad_ids and not dup,
            f"greenfield={greenfield} 非法 id={bad_ids} 重复={dup} 空 globs={no_globs}")
    res.add("域模型 · 域目录与 domains[] 一致",
            disk == sorted(ids) or (greenfield and not ids),
            f"greenfield={greenfield} 磁盘={disk} meta={sorted(ids)}")

    # 类别覆盖
    globals_missing = [n for n in ("directory-map.md", "routes.md")
                       if not (spec / "global" / n).is_file()]
    cat = meta.get("categories") or {}
    a_ok = isinstance(cat.get("A"), str) and _cat_token(cat["A"]) in ("covered", "skipped")
    h_ok_vals = ("covered", "added", "skipped") if greenfield else ("covered", "added")
    h_ok = isinstance(cat.get("H"), str) and _cat_token(cat["H"]) in h_ok_vals
    role_issues = []
    # F33（R8 收束，2026-10-15）：D 类**指针形态豁免**——AP 已经有机器可读描述
    # （OpenAPI/Swagger/graphql 等）时，领域适配器会存入 `global/apis-shared.md` 指针行
    # （`真相源` 与 `spec_entry`），而非领域级的 `apis.md` 清单。覆盖判据读它：
    # 如果指针行指向的领域 (apps[] 包含子名称) 匹配，则该领域的 `apis.md` 缺失合规，且
    # 不再被迫手写域级指针文件（F1 病根）。
    shared_apis_md = spec / "global" / "apis-shared.md"

    def _pointer_covers(app_names: list) -> bool:
        """F33 判据：`global/apis-shared.md` 存在且至少一行指针同时满足：
        ① 表内含 `真相源`（refresh_structure 的指针行渲染特征）；② `来源模块` 列
        命中该域任一 app 名（domains[].apps 与表行交集）。"""
        if not app_names or not shared_apis_md.is_file():
            return False
        t = read(shared_apis_md)
        for line in t.splitlines():
            if line.strip().startswith("| —") and "真相源" in line:
                # 指针行：`| — | <spec_entry> | … | <来源模块(app 名)> | …`
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                # 真相源入口行形态：`| — | <spec_entry> | … | <app 名> |`（六列表头，
                # 来源模块列 = cells[5]）。**精确等于**——非智能子串匹配（在 `other-app` 中
                # 误匹配 `app` 会导致假豁免：变更本应将 FAIL 变为 PASS）。
                if any(app == cells[5] for app in app_names if len(cells) >= 6):
                    return True
        return False
    for role in ("current", "legacy"):
        base = spec / role
        if not base.is_dir():
            continue
        domains_by_id = {d.get("id"): d for d in (meta.get("domains") or []) if isinstance(d, dict)}
        for sub in sorted(p for p in base.iterdir() if p.is_dir()):
            if sub.name not in ids:
                role_issues.append(f"{role}/{sub.name} 不在 domains[]")
                continue
            for req in ("apis.md", "data-models.md"):
                if (sub / req).is_file():
                    continue
                if req == "apis.md" and _pointer_covers(
                        (domains_by_id.get(sub.name, {}).get("apps") or [])):
                    continue  # F33 指针形态合规
                role_issues.append(f"{role}/{sub.name} 缺 {req}")
    res.add("类别覆盖 · global/", (not globals_missing) or greenfield,
            f"greenfield={greenfield} 缺 {globals_missing}")
    res.add("类别覆盖 · 域级 apis/data-models", not role_issues, "；".join(role_issues))
    res.add("类别覆盖 · categories A/H", a_ok and h_ok,
            f"A={cat.get('A')!r} H={cat.get('H')!r}"
            f"（处置须**声明在字段首位**：A ∈ covered|skipped；"
            f"H ∈ {'covered|added|skipped（greenfield）' if greenfield else 'covered|added'}；"
            f"散文/取证只准接在 `：` 或 `（` 之后）")

    # 事实载体 truth_carriers（issue #25，2026-10-19）：允许无根 README 的项目声明 A/H 事实落点
    carriers = meta.get("truth_carriers")
    if carriers is not None:
        if not isinstance(carriers, dict):
            res.add("类别覆盖 · 事实载体", False, f"truth_carriers 应为映射对象，实得 {type(carriers).__name__}")
        else:
            carrier_issues = []
            for raw_k, rel_path in carriers.items():
                if not isinstance(rel_path, str) or not rel_path.strip():
                    carrier_issues.append(f"{raw_k}: 路径为空")
                    continue
                p = root / rel_path.strip()
                if not p.is_file():
                    carrier_issues.append(f"{raw_k} 载体文件不存在: {rel_path}")
                else:
                    try:
                        if p.stat().st_size == 0:
                            carrier_issues.append(f"{raw_k} 载体文件为空: {rel_path}")
                    except OSError:
                        carrier_issues.append(f"{raw_k} 载体文件不可读: {rel_path}")
            res.add("类别覆盖 · 事实载体", not carrier_issues,
                    "；".join(carrier_issues) if carrier_issues else "载体文件均存在且非空")

    # 适配器缺口登记（F42，2026-10-15，issue #3 ④）
    # 接线前置未满足时（适配器 0 命中 / 产出不自洽），契约要求「不接线 + 把缺口登记下来」。
    # 不登记的话两种处境在产物里**同形**（都是 `maintained_by: agent`）：
    #   (a) 设计结论「源即真相，不接」——缺口是设计结论；
    #   (b) **工具覆盖不足**（逐件判定表判「接」，但本栈 0 命中）——缺口是工具的问题。
    # 采用者会把 (b) 读成 (a)，而该类别的 `structure ↔ 代码` 对账平面**永久缺口**、且没人
    # 知道它不是预期的（`§B118` 的反面：把工具覆盖不足伪装成审慎的设计结论，同样是伪装）。
    gaps = meta.get("adapter_gaps")
    if gaps:
        if not isinstance(gaps, dict):
            res.add("适配器缺口 · 形态", False,
                    f"adapter_gaps 应为对象（类别 → 取证），实得 {type(gaps).__name__}")
        else:
            res.add_warn("适配器缺口",
                         "；".join(f"{k}: {v}" for k, v in sorted(gaps.items()))
                         + "（接线前置未满足 ⇒ 该类别的对账平面缺口；确认是设计结论还是工具覆盖不足）")

    # D 类接线态 ⇔ 形态声明 ⇔ 缺口登记（2026-10-15）：接线态跨两个产物
    # （`product/stack-profile.yaml` 的 adapters.api ⇔ 本产物的 `categories.D` / `adapter_gaps`）。
    # 契约 `shared/stack-profile.md` §3.5：D 类为**指针 / 未取证**形态时不得接源码枚举
    # 适配器（adapters.api 应置 null）——此前无任何机器判据，接线态与形态声明混写没门咬。
    # 三态纪律：profile 不存在 / adapters.api 未声明 ⇒ 不产行（profile 缺失由
    # `validate_stack_profile` 独立响亮 FAIL，本器不重复告警）。
    api_decl: object = None
    prof_path = root / "product" / "stack-profile.yaml"
    if prof_path.is_file():
        _prof = _sp_profile.parse_profile(prof_path.read_text(encoding="utf-8"))
        adapters_decl = _prof.get("adapters")
        api_decl = adapters_decl.get("api") if isinstance(adapters_decl, dict) else None
    if api_decl:
        d_val = cat.get("D") if isinstance(cat.get("D"), str) else ""
        d_form = _d_form_token(d_val)
        gaps_obj = meta.get("adapter_gaps")
        g_api = (gaps_obj or {}).get("api") if isinstance(gaps_obj, dict) else None
        why = []
        if d_form in _D_WIRE_INCOMPATIBLE:
            why.append(f"categories.D 声明为「{d_form}」形态（{d_val}）")
        if g_api:
            why.append(f"adapter_gaps 登记 api：{g_api}")
        if why:
            res.add_warn("D 类接线态与形态声明混写",
                         f"adapters.api = {api_decl!r} 已接线，但 {'；'.join(why)}"
                         "——§3.5 该形态不得接源码枚举适配器：把 adapters.api 退回 null，"
                         "或把 categories.D 改为「清单（用户确认无描述）」并给取证")

    # 元数据一致 · apps / product
    res.add("元数据 · product/apps", bool(meta.get("product")) and isinstance(meta.get("apps"), list) and meta.get("apps"),
            "缺 product 或 apps[]")

    # global/routes.md 域列
    routes_md = spec / "global" / "routes.md"
    if routes_md.is_file():
        rtext = read(routes_md)
        header = first_table(rtext) or []
        unknown = []
        if "域" not in header:
            unknown.append("routes.md 无「域」列")
        else:
            for row in table_rows(rtext, header):
                cell = row.get("域", "")
                for tok in re.split(r"[/、,，]", cell):
                    tok = tok.strip().strip("`")
                    if tok and tok not in ("—", "-", "各域") and tok not in ids:
                        unknown.append(tok)
        res.add("域模型 · routes 域列 ⊆ domains", not unknown, "；".join(sorted(set(unknown))))

        # 语义列留空 ⇒ WARN 指名（`§B121`：契约承诺必须配判据；「—」是合法占位，不算留空）
        header = first_table(rtext) or []
        gaps = []
        for row in table_rows(rtext, header):
            empty = [c for c in ("用途", "关键交互", "实现状态") if not row.get(c, "").strip()]
            if empty:
                gaps.append(f"{row.get('页面/路由', '?')} 缺 {'/'.join(empty)}")
        if gaps:
            res.add_warn("routes 语义列", "；".join(gaps))

    # D 形态（F44：指针形态判据改**锚定声明**——全文子串 `"真相源" in t` 会把清单型
    # 文件语义段里的提及误判成指针 ⇒ 「清单与指针混写」假 FAIL；F38 同族 diseases）
    d_issues = []
    for p in sorted(spec.glob("*/*/apis.md")):
        t = read(p)
        head = first_table(t)
        is_list = head == TABLE_APIS
        is_pointer = _pointer_declared(t)
        rel = p.relative_to(spec).as_posix()
        if is_list and is_pointer:
            d_issues.append(f"{rel} 清单与指针混写")
        elif not is_list and not is_pointer:
            d_issues.append(f"{rel} 既非清单也非指针")
    res.add("D 形态", not d_issues, "；".join(d_issues))

    # 指针预算
    max_total = read_max_total(root)
    tour = spec / "tour.md"
    tour_len = len(read(tour)) if tour.is_file() else 0
    over = []
    for d in domains:
        did = d.get("id")
        p = spec / "domains" / f"{did}.md"
        total = tour_len + (len(read(p)) if p.is_file() else 0)
        if total > max_total:
            over.append(f"{did}={total}")
    res.add("指针预算 L1+L2", not over, f"上限 {max_total}；超出 {over}")

    # 注入结构
    inj = []
    for p in [tour] + sorted((spec / "domains").glob("*.md")):
        if not p.is_file():
            inj.append(f"缺 {p.name}")
            continue
        ok, why = paths_block(frontmatter(read(p)) or "")
        if not ok:
            inj.append(f"{p.name}: {why}")
    res.add("注入结构 paths 块列表", not inj, "；".join(inj))

    # 占位符（F31，2026-10-15：token 级判据只作用于 `TODO`）
    # 病根：`FORBIDDEN` 含大写 `TODO`，域码恰为 todo 的项目在结构文档里引用
    # 用例 ID（`E2E-TODO-004`）时被逐行子串误杀。修法：**裸 token** 判——
    # `TODO` 前后邻字符非 `[\w-]` 才算命中；`E2E-TODO-004` 内的 `-TODO-` 两端
    # 都是 `-` ⇒ 不命中。裸 `TODO`/`TODO:` 照报（冒号不在豁免字符内）。
    # 其余 FORBIDDEN 词保持原逐行子串语义（CJK 复合词宏观边界非本次目标）。
    todo_bare_re = re.compile(r"(?<![\w-])TODO(?![\w-])")
    place = []
    for p in sorted(spec.rglob("*.md")):
        for n, ln in enumerate(read(p).splitlines(), 1):
            for word in FORBIDDEN:
                if word == "TODO":
                    if todo_bare_re.search(ln):
                        place.append(f"{p.relative_to(spec)}:{n} 含「TODO」")
                elif word in ln:
                    place.append(f"{p.relative_to(spec)}:{n} 含「{word}」")
    res.add("占位符", not place, "；".join(place))

    # 表格列
    col_issues = []
    dm = spec / "global" / "directory-map.md"
    if dm.is_file() and first_table(read(dm)) != TABLE_DIRECTORY_MAP:
        col_issues.append(f"directory-map 列头={first_table(read(dm))}")
    if routes_md.is_file():
        head = first_table(read(routes_md)) or []
        if head != TABLE_ROUTES and head != ["应用"] + TABLE_ROUTES:
            col_issues.append(f"routes 列头={head}")
    for p in sorted(spec.glob("*/*/data-models.md")):
        if first_table(read(p)) != TABLE_DATA_MODELS:
            col_issues.append(f"{p.relative_to(spec)} 列头不符")
    for p in sorted(spec.glob("*/*/apis.md")):
        head = first_table(read(p))
        if head is not None and head != TABLE_APIS and not _pointer_declared(read(p)):
            col_issues.append(f"{p.relative_to(spec)} 列头={head}")
    res.add("表格列", not col_issues, "；".join(col_issues))

    # 来源可定位（先按项目根解析，再按各 app 根解析——短引用允许 app 相对）
    app_paths = [a.get("path") for a in (meta.get("apps") or []) if isinstance(a, dict) and a.get("path")]

    def resolves(target: str) -> bool:
        # F34b（R8 收束，2026-10-15）：兄弟 spec 相对引用合法——结构文档里的
        # `global/routes.md`、`domains/demo.md` 等 <spec> 内相对路径，解析锚 =
        # **结构 spec 根**（`.trellis/spec/structure/`）；项目根与 app 根锚保留在前优先。
        bases = [root] + [root / ap for ap in app_paths] + [spec]
        if "*" in target:
            return any(any(b.glob(target)) for b in bases)
        return any((b / target).exists() for b in bases)

    missing = []
    for p in sorted(spec.rglob("*.md")):
        for tok in _path_candidates(read(p)):
            target = re.sub(r":\d+(?:-\d+)?$", "", tok)
            if not resolves(target):
                missing.append(f"{p.relative_to(spec)} -> {tok}")
    res.add("来源可定位", not missing, "；".join(sorted(set(missing))))

    # 密钥泄漏
    leaks = []
    for p in sorted(spec.rglob("*.md")):
        for n, ln in enumerate(read(p).splitlines(), 1):
            for rx in SECRET_RES:
                m = rx.search(ln)
                if m:
                    leaks.append(f"{p.relative_to(spec)}:{n} 疑似密钥值")
                    break
    res.add("密钥泄漏", not leaks, "；".join(leaks))

    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    res = validate(root)
    if args.json:
        status = "PASS" if res.ok else "FAIL"
        if res.ok and res.warns:
            status = "WARN"
        print(json.dumps({"ok": res.ok, "status": status,
                          "root": str(root), "checks": res.rows, "warns": res.warns},
                         ensure_ascii=False, indent=2))
    else:
        print(f"validate_structure @ {root}")
        for r in res.rows:
            flag = "OK  " if r["ok"] else "FAIL"
            line = f"  [{flag}] {r['check']}"
            if r["detail"] and not r["ok"]:
                line += f" —— {r['detail']}"
            print(line)
        for w in res.warns:
            print(f"  [WARN] {w['check']} —— {w['detail']}")
        print("FAIL" if not res.ok else ("WARN" if res.warns else "PASS"))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
