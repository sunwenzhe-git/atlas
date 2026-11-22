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

AC_RE = re.compile(r"AC-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{2,3}")
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ARCHIVE_DIR = "archive"  # `.atlas/tasks/archive/<YYYY-MM>/<ID>/`：已收口任务归档区（issue #70）


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
CLAIM_NONE_MARKER = "不承接需求条目"


def detect_requirement_root(ref: Path) -> Path | None:
    """`--requirement` 落点模式判定：指向含 `requirement.md` 的目录，或就是该文件本身。

    返回落点目录（requirement.md 所在目录）；非落点 ⇒ None（直填模式，旧行为不变）。
    """
    ref = Path(ref)
    if ref.is_dir() and (ref / REQUIREMENT_DOC_FILE).is_file():
        return ref
    if ref.is_file() and ref.name == REQUIREMENT_DOC_FILE:
        return ref.parent
    return None


def requirement_pointer_text(requirement_root_rel: str) -> str:
    """落点模式卡的 §1 正文指针：需求正文唯一住址在落点，本卡不复制正文。"""
    return (
        f"> 需求正文唯一住址：`{requirement_root_rel}`"
        "（requirement.md 确认稿 + work/需求PDF-全文.md 转换稿；RFC-20261122-03，本卡不复制正文）。\n"
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

    prd_text = render_prd_markdown(task)
    prd_path.write_text(prd_text, encoding="utf-8")

    prev = None
    if task_json_path.is_file():
        try:
            prev = json.loads(task_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = None

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
    if requirement_root_rel:
        meta["requirement_root"] = requirement_root_rel
    if isinstance(prev, dict):
        if prev.get("status") in ("todo", "in_progress", "completed"):
            meta["status"] = prev["status"]
        if isinstance(prev.get("created_at"), str) and prev["created_at"]:
            meta["created_at"] = prev["created_at"]
        # 重跑 plan（含 `atlas workflow run`）未显式给 --paths 时沿用已存路径，
        # 否则派工单的最小注入会退回 tour 兜底（状态机可重放的前提）。
        if "paths" not in meta and isinstance(prev.get("paths"), list):
            meta["paths"] = prev["paths"]
        # 同理：重跑未显式给落点时沿用已存落点（落点模式卡重跑不得退化成直填）。
        if "requirement_root" not in meta and isinstance(
                prev.get("requirement_root"), str) and prev["requirement_root"]:
            meta["requirement_root"] = prev["requirement_root"]
    atomic_write_json(task_json_path, meta)
    if with_requirement_items:
        if requirement_root_rel:
            write_claim_items(task_dir, task, requirement_root_rel)
        else:
            write_requirement_items(task_dir, task)
        write_coverage_matrix(task_dir, task)
    return task_dir


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
        rel = p.relative_to(tasks_root)
        archived = bool(rel.parts) and rel.parts[0] == ARCHIVE_DIR
        if archived and not include_archived:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlanError(f"任务卡损坏或不可读：{p}（{exc}）") from exc
        if not (isinstance(data, dict) and data.get("id")):
            raise PlanError(f"任务卡缺少 id：{p}")
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
