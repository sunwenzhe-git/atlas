#!/usr/bin/env python3
"""Atlas Workflow Plan —— 大任务拆解与任务卡结构化生成引擎 (Phase Plan)。

职责：
1. 读取业务需求输入（文本/Markdown，或需求落点 `<assets_root>/requirements/<slug>/`，
   RFC-20261122-03），结合项目单源事实表（PRD、AC、架构透镜 FRAS）；
2. 自动拆分为平级有序的工作单元清单（Task DAG，严禁无限深度的子任务树）；
3. 生成符合 Atlas 契约规范的任务卡（`prd.md`，带 `atlas-acceptance:` 与四列 Confirmed 表）
   及元数据描述（`task.json`）。

纯标准库实现。
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

from _support.layout import LayoutError, load_layout

AC_RE = re.compile(r"AC-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{2,3}")
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ARCHIVE_DIR = "archive"  # `.atlas/tasks/archive/<YYYY-MM>/<ID>/`：已收口任务归档区（issue #70）
ARCHIVE_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class PlanError(ValueError):
    """输入或规划预检错误。"""


def scan_known_acs(root: Path) -> dict[str, str]:
    """扫描项目内所有已知的 AC ID 及来源文件相对路径。"""
    root = root.resolve()
    prd_dir = root / "product" / "prd"
    acs: dict[str, str] = {}
    if not prd_dir.is_dir():
        return acs
    for p in sorted(prd_dir.rglob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        for m in AC_RE.finditer(text):
            ac_id = m.group(0)
            if ac_id not in acs:
                acs[ac_id] = rel
    return acs


def decompose_requirement(root: Path, requirement_text: str, unit: str) -> list[dict]:
    """将需求文本解析为结构化的任务单元列表 (Task DAG)。

    返回列表中的每一项包含：
    - id: 任务唯一标识（如 unit 或 unit-01）
    - title: 任务简述
    - acs: 关联的 AC 列表
    - depends_on: 前置依赖任务 ID 列表
    - affected_domains: 涉及的业务域
    - details: 任务详细说明
    """
    if not UNIT_RE.fullmatch(unit):
        raise PlanError(f"unit「{unit}」含有不合法字符")

    text = requirement_text.strip()
    if not text:
        raise PlanError("需求文本为空，无法进行任务分解")

    known_acs = scan_known_acs(root)
    mentioned_acs = [ac for ac in known_acs if ac in text]

    # 尝试解析多条任务小项（支持 - [ ] 或 ### 标题标记）
    sub_items = []
    lines = text.splitlines()
    curr_title = ""
    curr_body: list[str] = []

    for line in lines:
        m_task = re.match(r"^(?:###\s+|\d+\.\s+|-\s*\[[ x]\]\s*)(.+)$", line.strip())
        if m_task:
            if curr_title:
                sub_items.append((curr_title, "\n".join(curr_body)))
                curr_body = []
            curr_title = m_task.group(1).strip()
        else:
            curr_body.append(line)
    if curr_title:
        sub_items.append((curr_title, "\n".join(curr_body)))

    tasks: list[dict] = []
    if len(sub_items) > 1:
        # 分解为多任务平级 DAG
        prev_id = None
        for idx, (title, body) in enumerate(sub_items, start=1):
            t_id = f"{unit}-{idx:02d}"
            # 提取本任务包含的 AC
            item_acs = [ac for ac in mentioned_acs if ac in title or ac in body]
            tasks.append({
                "id": t_id,
                "title": title,
                "acs": item_acs,
                "depends_on": [prev_id] if prev_id else [],
                "affected_domains": _infer_domains(item_acs),
                "details": body.strip(),
            })
            prev_id = t_id
    else:
        # 单一工作单元
        first_line = lines[0].strip().lstrip("#").strip() if lines else unit
        tasks.append({
            "id": unit,
            "title": first_line or unit,
            "acs": mentioned_acs,
            "depends_on": [],
            "affected_domains": _infer_domains(mentioned_acs),
            "details": text,
        })

    return tasks


def _infer_domains(acs: list[str]) -> list[str]:
    """从 AC 命名规则（如 AC-HOME-001）反推域编码。"""
    domains = set()
    for ac in acs:
        parts = ac.split("-")
        if len(parts) >= 3:
            domains.add(parts[1].lower())
    return sorted(domains)


def render_prd_markdown(task: dict) -> str:
    """渲染符合 validate_task_card 校验契约的 prd.md。"""
    acs_str = ", ".join(task["acs"]) if task["acs"] else "none"
    lines = [
        f"# 任务需求卡 — {task['title']}",
        "",
        f"**任务编号**：`{task['id']}`  ",
        f"**前置依赖**：`{', '.join(task['depends_on']) if task['depends_on'] else '无'}`  ",
        f"**影响业务域**：`{', '.join(task['affected_domains']) if task['affected_domains'] else '通用'}`",
        "",
        "<!-- ATLAS:START -->",
        f"atlas-acceptance: {acs_str}",
        "<!-- ATLAS:END -->",
        "",
        "## 1. 任务背景与目标",
        task.get("details") or "根据需求完成相应模块改动及验收测试。",
        "",
        "## 2. 确认口径与证据台账 (Confirmed)",
        "",
        "| 确认项 | 确认口径 | 证据状态 | 证据指针 |",
        "|---|---|---|---|",
    ]
    if task["acs"]:
        for ac in task["acs"]:
            lines.append(f"| 验收基准 {ac} | 满足对应断言并经独立审查通过 | pending | N/A |")
    else:
        lines.append(f"| 功能实现 | 代码实现符合既有规范且测试绿灯 | pending | N/A |")

    lines.extend([
        "",
        "## 3. 变更范围与完成定义",
        "- [ ] 代码实现完成，无多余未跟踪修改",
        "- [ ] 暂存区通过 `atlas review --staged` 独立审查",
        "- [ ] 确定性测试/工具链全部通过",
        "",
    ])
    return "\n".join(lines)


def atomic_write_json(path: Path, data: dict) -> None:
    """任务账本写入必须原子：写临时文件后 os.replace，避免半截 JSON。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


REQUIREMENT_ITEMS_FILE = "requirement-items.md"
COVERAGE_MATRIX_FILE = "coverage-matrix.md"
# 需求落点（RFC-20261122-03）：`<assets_root>/requirements/<slug>/`
REQUIREMENT_DOC_FILE = "requirement.md"
REQUIREMENT_TYPES = ("初始需求", "需求变更", "缺陷")
REQUIREMENT_RELATED_RE = re.compile(
    r"^(?P<slug>[A-Za-z0-9][A-Za-z0-9._-]{0,63})#(?P<item>R-\d{2,3})$")
CLAIM_NONE_MARKER = "不承接需求条目"


def detect_requirement_root(ref: Path, root: Path | None = None) -> Path | None:
    """`--requirement` 落点模式判定：实体目录/文件，或唯一归档实体。"""
    ref = Path(ref)
    if ref.is_dir() and (ref / REQUIREMENT_DOC_FILE).is_file():
        return ref
    if ref.is_file() and ref.name == REQUIREMENT_DOC_FILE:
        return ref.parent
    if root is not None:
        try:
            return resolve_requirement_root(root, ref)
        except (LayoutError, OSError):
            return None
    return None


def strip_fences(text: str) -> str:
    """剥离 Markdown 围栏；关闭必须同字符且长度不短于开启。"""
    out: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_char is None:
            if match:
                fence_char = match.group(1)[0]
                fence_len = len(match.group(1))
                out.append("")
            else:
                out.append(line)
            continue
        if (match and match.group(1)[0] == fence_char
                and len(match.group(1)) >= fence_len and not match.group(2).strip()):
            fence_char = None
            fence_len = 0
        out.append("")
    return "\n".join(out)


def read_requirement_fields(req_root: Path) -> dict[str, str]:
    """读取需求落点首部元数据；围栏示例不参与。"""
    doc = Path(req_root) / REQUIREMENT_DOC_FILE
    if not doc.is_file() or doc.is_symlink():
        return {}
    text = strip_fences(doc.read_text(encoding="utf-8", errors="replace"))
    fields: dict[str, str] = {}
    for key in ("类型", "关联需求", "状态", "结论", "证据"):
        match = re.search(rf"^\*\*{re.escape(key)}\*\*[：:]\s*(.*?)\s*$", text, re.MULTILINE)
        if match:
            fields[key] = match.group(1).strip()
    return fields


def requirement_type(req_root: Path) -> str:
    """缺省类型为初始需求；显式非法值原样返回，不得静默默认。"""
    return read_requirement_fields(req_root).get("类型") or "初始需求"


def _requirement_item_exists(req_root: Path, item_id: str) -> bool:
    items = Path(req_root) / "items.md"
    if not items.is_file() or items.is_symlink():
        return False
    try:
        text = strip_fences(items.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    return re.search(
        rf"^\|\s*{re.escape(item_id)}\s*\|", text, re.MULTILINE,
    ) is not None


def _requirements_base(root: Path) -> Path:
    root = Path(root).resolve()
    assets = load_layout(root).assets_root.resolve()
    base = (assets / "requirements").resolve()
    if base.parent != assets or root not in base.parents:
        raise LayoutError("requirements 必须位于配置资产根内且不得经 symlink 逃逸")
    return base


def _valid_requirement_dir(path: Path, base: Path, slug: str,
                           month: str | None = None) -> bool:
    if path.is_symlink():
        return False
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", slug):
        return False
    if month is not None:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            return False
        if (base / "archive" / month).is_symlink():
            return False
    expected_parent = base if month is None else base / "archive" / month
    resolved = path.resolve()
    if resolved.name != slug or resolved.parent != expected_parent.resolve():
        return False
    if base not in resolved.parents:
        return False
    doc = resolved / REQUIREMENT_DOC_FILE
    items = resolved / "items.md"
    if doc.is_symlink() or not doc.is_file():
        return False
    try:
        if doc.resolve().parent != resolved:
            return False
        if items.exists() or items.is_symlink():
            if items.is_symlink() or not items.is_file() or items.resolve().parent != resolved:
                return False
        return True
    except OSError:
        return False


def _archived_slug_collisions(base: Path, slug: str) -> list[Path]:
    archive_path = base / "archive"
    if archive_path.is_symlink():
        raise LayoutError("requirements/archive 不得经 symlink 改道")
    archive = archive_path.resolve()
    if archive.parent != base:
        raise LayoutError("requirements/archive 必须留在配置资产根内")
    if not archive.is_dir():
        return []
    collisions: list[Path] = []
    for month in archive.iterdir():
        if not month.is_dir() and not month.is_symlink():
            continue
        candidate = month / slug
        if candidate.exists() or candidate.is_symlink():
            collisions.append(candidate)
    return collisions


def resolve_requirement_root_by_slug(root: Path, slug: str) -> Path | None:
    """按稳定 slug 解析唯一合法落点；任何同名归档碰撞都阻止活跃复用。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", slug):
        return None
    base = _requirements_base(root)
    active = base / slug
    collisions = _archived_slug_collisions(base, slug)
    active_valid = _valid_requirement_dir(active, base, slug)
    if active_valid:
        return None if collisions else active.resolve()
    if active.exists() or active.is_symlink() or len(collisions) != 1:
        return None
    archived = collisions[0]
    if not _valid_requirement_dir(archived, base, slug, archived.parent.name):
        return None
    return archived.resolve()


def normalize_requirement_ref(root: Path, ref: str | Path | None) -> str:
    """把活跃/归档实体统一为同一逻辑 slug 路径；非法路径保留规范化字面。"""
    if ref is None or not str(ref).strip():
        return ""
    root = Path(root).resolve()
    try:
        resolved = resolve_requirement_root(root, ref)
    except (LayoutError, OSError):
        resolved = None
    if resolved is not None:
        try:
            return logical_requirement_root_ref(root, resolved)
        except (LayoutError, OSError):
            pass
    ref_path = Path(ref)
    candidate = ref_path if ref_path.is_absolute() else root / ref_path
    try:
        candidate = candidate.resolve()
    except (OSError, RuntimeError):
        return str(ref).replace("\\", "/")
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return candidate.as_posix()


def resolve_requirement_root(root: Path, ref: str | Path) -> Path | None:
    """只接受配置资产根下的 requirements/<slug> 或其唯一归档实体。"""
    root = Path(root).resolve()
    base = _requirements_base(root)
    ref_path = Path(ref)
    candidate = ref_path if ref_path.is_absolute() else root / ref_path
    try:
        candidate = candidate.resolve()
    except RuntimeError as exc:
        raise OSError(str(exc)) from exc
    if root not in candidate.parents:
        return None
    try:
        logical = candidate.relative_to(base)
    except ValueError:
        return None
    if len(logical.parts) == 1:
        return resolve_requirement_root_by_slug(root, logical.name)
    if (len(logical.parts) == 3 and logical.parts[0] == "archive"
            and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", logical.parts[1])):
        resolved = resolve_requirement_root_by_slug(root, logical.name)
        return resolved if resolved == candidate else None
    return None


def logical_requirement_root_ref(root: Path, req_root: Path) -> str:
    """任务卡始终保存活跃形态逻辑路径，实体归档后仍可唯一回落。"""
    root = Path(root).resolve()
    resolved = resolve_requirement_root(root, req_root)
    if resolved is None:
        raise LayoutError(f"非法需求落点：{req_root}")
    base = _requirements_base(root)
    logical = resolved.relative_to(base)
    slug = logical.parts[2] if logical.parts[0] == "archive" else logical.parts[0]
    return (base / slug).relative_to(root).as_posix()


def requirement_relation_findings(root: Path, req_root: Path, *,
                                  require_report: bool = True) -> list[str]:
    """需求变更/缺陷的基线关联检查，返回 WARN 文案。"""
    req_root = Path(req_root).resolve()
    fields = read_requirement_fields(req_root)
    declared_type = fields.get("类型")
    if declared_type and declared_type not in REQUIREMENT_TYPES:
        return [f"需求类型非法：{declared_type!r}（允许：{'/'.join(REQUIREMENT_TYPES)}）"]
    kind = declared_type or "初始需求"
    findings: list[str] = []
    if kind in ("缺陷", "需求变更") and require_report:
        # 报告路径单源在 bug_record（本模块被其顶层引用，故惰性导入防循环）。
        from _support.bug_record import REPORT_PATH_CHOICES
        choices = REPORT_PATH_CHOICES[kind]
        if not any((req_root / rel).is_file() for rel in choices):
            if kind == "缺陷":
                findings.append(
                    f"缺陷类型缺 {' 或 '.join(choices)}：先落现象、期望、实际、复现与环境证据")
            else:
                findings.append(
                    f"需求变更类型缺 {' 或 '.join(choices)}：先落变更原因、范围与验收影响")
    related = fields.get("关联需求")
    if kind in ("需求变更", "缺陷") and not related:
        findings.append(f"{kind}的关联需求必填：指向既有需求落点")
        return findings
    if not related:
        return findings
    match = REQUIREMENT_RELATED_RE.fullmatch(related)
    if not match:
        findings.append(f"关联需求形态非法：{related!r}（须为 <slug>#R-NN）")
        return findings
    slug = match.group("slug")
    item_id = match.group("item")
    if slug == req_root.name:
        findings.append("关联需求不得自引")
        return findings
    try:
        target = resolve_requirement_root_by_slug(root, slug)
    except LayoutError as exc:
        return findings + [f"关联需求无法解析：{exc}"]
    if target is None:
        findings.append(
            f"关联需求找不到唯一落点（非法、slug 复用、归档歧义或路径越界）：{slug}")
        return findings
    target_status = read_requirement_fields(target).get("状态")
    if target_status not in ("已确认", "已拆", "已收口"):
        findings.append(
            f"关联需求基线状态非法：{slug} 当前 {target_status or '缺失'}，"
            "须为已确认/已拆/已收口")
    if not _requirement_item_exists(target, item_id):
        findings.append(f"关联需求条目不存在：{slug}#{item_id}")
        return findings
    seen = [req_root.name, slug]
    current = target
    while True:
        next_ref = read_requirement_fields(current).get("关联需求")
        if not next_ref:
            break
        next_match = REQUIREMENT_RELATED_RE.fullmatch(next_ref)
        if not next_match:
            break
        next_slug = next_match.group("slug")
        if next_slug in seen:
            findings.append(f"关联需求循环：{' → '.join(seen + [next_slug])}")
            break
        seen.append(next_slug)
        try:
            next_root = resolve_requirement_root_by_slug(root, next_slug)
        except LayoutError:
            break
        if next_root is None:
            break
        current = next_root
    return findings


def requirement_pointer_text(requirement_root_rel: str) -> str:
    """落点模式卡的 §1 正文指针：需求正文唯一住址在落点，本卡不复制正文。"""
    return (
        f"> 需求正文唯一住址：`{requirement_root_rel}`"
        "（requirement.md 确认稿 + 来源材料（`work/` 或落点根报告）；"
        "RFC-20261122-03，本卡不复制正文）。\n"
        f"> 本卡领取条目见本卡 `requirement-items.md` 领取引用表"
        "（来源 = `<落点路径>#<落点ID>`）；按权威源排序"
        "（需求原文 > 需求 PRD > 任务 PRD > 设计文档 > 代码惯例）回查落点。")


def write_claim_items(task_dir: Path, task: dict,
                      requirement_root_rel: str) -> Path:
    """落点模式卡条目领取表骨架（RFC-20261122-03）：只写引用行，不复制条目正文。

    条目正文唯一住址 = 落点 `items.md`；卡侧 `ID` = 落点条目 ID、
    `来源` = `<落点路径>#<落点ID>`。已存在则跳过——重跑 plan 不覆盖已填内容。
    """
    path = task_dir / REQUIREMENT_ITEMS_FILE
    if path.exists():
        return path
    path.write_text("\n".join([
        f"# 需求条目领取表 — {task['title']}",
        "",
        f"> 落点模式（RFC-20261122-03）：条目正文唯一住址在需求落点 `{requirement_root_rel}/items.md`；"
        "本卡**不复制正文**，只写领取引用行。",
        "> `ID` = 落点条目 ID（如 `R-01`）；`来源` = `<落点路径>#<落点ID>`（项目根相对 POSIX 路径）。",
        "> 条目↔卡允许共担（同一条目跨卡实现合法），覆盖性由 `atlas workflow verify` 跨卡对账。",
        "> 本卡确不承接需求条目时写：`领取条目数：0（本卡不承接需求条目）`。",
        "",
        "| ID | 来源 |",
        "|---|---|",
        "",
        "领取条目数：待填",
        "",
    ]), encoding="utf-8")
    return path


def write_requirement_items(task_dir: Path, task: dict) -> Path:
    """需求条目表骨架（#72 开工前置产物）：先枚举再动手。

    无外部需求原件的卡显式声明豁免（`条目总数：0（本卡无外部需求原件）`）；
    已存在则跳过——重跑 plan 不覆盖已填内容。
    """
    path = task_dir / REQUIREMENT_ITEMS_FILE
    if path.exists():
        return path
    path.write_text("\n".join([
        f"# 需求条目表 — {task['title']}",
        "",
        "> 开工前置产物（#72）：本卡承接的需求条目逐条枚举，**开工前完成**；"
        "原文逐字不改写，限定语（如「实际以接口为准」）必须保留。",
        "> 需求原件（PDF / 图片）先转成带页码锚的 Markdown 落本卡 `work/需求PDF-全文.md`"
        "（页码锚 `<!-- page N -->`，空白页保留裸锚，正文逐字可回查）；「页码」列对齐该锚。",
        "> 表格类需求按行拼接为一句，不改措辞；文末声明条目总数与页码分布，"
        "表行数必须等于声明总数。",
        "> 本卡确无外部需求原件时写：`条目总数：0（本卡无外部需求原件）`。",
        "",
        "| ID | 页码 | 章节 | 原文 |",
        "|---|---|---|---|",
        "",
        "条目总数：待填",
        "页码分布：待填",
        "",
    ]), encoding="utf-8")
    return path


def write_coverage_matrix(task_dir: Path, task: dict) -> Path:
    """需求条目覆盖矩阵骨架（#73）：行 = 条目 ID，列 = 四个资产面。

    已存在则跳过；矩阵格值词表与 verify 判据见 `_support/workflow_verify.py`。
    """
    path = task_dir / COVERAGE_MATRIX_FILE
    if path.exists():
        return path
    path.write_text("\n".join([
        f"# 需求条目覆盖矩阵 — {task['title']}",
        "",
        "> 每格只能是「覆盖（位置）」或「不涉及（理由）」，两者都给不出写 `UNRESOLVED`；"
        "留空格或存在 UNRESOLVED ⇒ `atlas workflow verify` WARN（纪律面起步，升格 FAIL 另案）。",
        "> 行 = `requirement-items.md` 的条目 ID；实现列以**当前代码**取证，"
        "文档说覆盖而代码没有按未覆盖处理。",
        "",
        "| ID | PRD | 设计文档 | 实现 | E2E |",
        "|---|---|---|---|---|",
        "",
    ]), encoding="utf-8")
    return path


def write_task_card(task_dir: Path, task: dict, *,
                    with_requirement_items: bool = False,
                    requirement_root_rel: str | None = None) -> Path:
    """写入单个任务卡目录（包含 prd.md 与 task.json）。

    重跑 plan 不得把已推进的状态打回 `todo`（状态机单调：todo < in_progress < completed）；
    已有 task.json 时沿用其 status 与 created_at。
    `with_requirement_items=True`（plan 显式给了 `--requirement`）时同步写需求条目表与
    条目覆盖矩阵骨架（#71/#72/#73：需求原文入库 → 条目枚举 → 覆盖对账）；
    `requirement_root_rel` 非空 ⇒ 落点模式（RFC-20261122-03）：卡条目表写**领取引用表**
    （正文唯一住址在落点），并把落点路径记入 task.json。
    """
    if task.get("id") == ARCHIVE_DIR:
        raise PlanError(f"任务标识 {ARCHIVE_DIR!r} 与归档目录保留名冲突")
    task_dir.mkdir(parents=True, exist_ok=True)
    prd_path = task_dir / "prd.md"
    task_json_path = task_dir / "task.json"

    prev = None
    if task_json_path.is_file():
        try:
            prev = json.loads(task_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = None

    prev_root = prev.get("requirement_root") if isinstance(prev, dict) else None
    effective_root = requirement_root_rel or (
        prev_root if isinstance(prev_root, str) and prev_root else None)
    if effective_root and not requirement_root_rel:
        task = {**task, "details": requirement_pointer_text(effective_root)}
    prd_text = render_prd_markdown(task)
    prd_path.write_text(prd_text, encoding="utf-8")

    meta = {
        "id": task["id"],
        "title": task["title"],
        "status": "todo",
        "depends_on": task["depends_on"],
        "affected_domains": task["affected_domains"],
        "acs": task["acs"],
        "created_at": date.today().isoformat(),
    }
    if task.get("paths"):
        meta["paths"] = list(task["paths"])
    if effective_root:
        meta["requirement_root"] = effective_root
    if isinstance(prev, dict):
        if prev.get("status") in ("todo", "in_progress", "completed"):
            meta["status"] = prev["status"]
        if isinstance(prev.get("created_at"), str) and prev["created_at"]:
            meta["created_at"] = prev["created_at"]
        # 重跑 plan（含 `atlas workflow run`）未显式给 --paths 时沿用已存路径，
        # 否则派工单的最小注入会退回 tour 兜底（状态机可重放的前提）。
        if "paths" not in meta and isinstance(prev.get("paths"), list):
            meta["paths"] = prev["paths"]
    atomic_write_json(task_json_path, meta)
    if with_requirement_items or effective_root:
        if effective_root:
            write_claim_items(task_dir, task, effective_root)
        else:
            write_requirement_items(task_dir, task)
        write_coverage_matrix(task_dir, task)
    return task_dir


def is_archived_task_dir(tasks_root: Path, task_dir: Path) -> bool:
    """只认 archive/<合法 YYYY-MM>/<任务ID> 三层归档形态。"""
    try:
        rel = Path(task_dir).relative_to(Path(tasks_root))
    except ValueError:
        return False
    return (len(rel.parts) == 3 and rel.parts[0] == ARCHIVE_DIR
            and ARCHIVE_MONTH_RE.fullmatch(rel.parts[1]) is not None)


def load_tasks(tasks_root: Path, *, include_archived: bool = False) -> list[dict]:
    """读取任务元数据并做依赖拓扑排序。

    `include_archived=False`（缺省）只扫**活跃**任务；归档在
    `<tasks_root>/archive/`（issue #70，由 finish / `atlas workflow archive` 迁入），
    带 `_archived: True` 标记，只能经 `include_archived=True` 或 `status --all` 看到。
    """
    if not tasks_root.is_dir():
        return []
    tasks: dict[str, dict] = {}
    for p in sorted(tasks_root.rglob("task.json")):
        rel = p.parent.relative_to(tasks_root)
        under_archive = bool(rel.parts) and rel.parts[0] == ARCHIVE_DIR
        archived_shape = is_archived_task_dir(tasks_root, p.parent)
        if under_archive and not include_archived:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PlanError(f"任务卡损坏或不可读：{p}（{exc}）") from exc
        if not (isinstance(data, dict) and isinstance(data.get("id"), str)
                and data["id"].strip()):
            raise PlanError(f"任务卡缺少合法字符串 id：{p}")
        if data["id"] in tasks:
            raise PlanError(f"任务 ID 重复：{data['id']}（{tasks[data['id']]['_dir']} / {p.parent}）")
        archived = archived_shape and rel.parts[2] == data["id"]
        data["_dir"] = str(p.parent)
        if archived:
            data["_archived"] = True
        tasks[data["id"]] = data

    # 简单拓扑排序
    sorted_tasks: list[dict] = []
    visited: set[str] = set()

    def visit(tid: str, path: list[str]) -> None:
        if tid in path:
            raise PlanError(f"任务依赖成环：{' -> '.join(path + [tid])}")
        if tid in visited or tid not in tasks:
            return
        for dep in tasks[tid].get("depends_on") or []:
            visit(dep, path + [tid])
        visited.add(tid)
        sorted_tasks.append(tasks[tid])

    for tid in sorted(tasks.keys()):
        visit(tid, [])

    return sorted_tasks
