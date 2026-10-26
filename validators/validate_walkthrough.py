#!/usr/bin/env python3
"""atlas 校验器 —— 走查单确认门的机器面（`RFC-20261022-01` M1，2026-10-23）。

守一件事（对账平面 = **声明 ⇔ 凭据**）：

  `apply` 的三问门判定第 2 问写下「是」（= 本需求改变应然 UI / 流程）⇒ 该需求
  **受影响域级 PRD** 的「用户旅程走查」节必须已有用户确认行 `> 已确认：<日期>`。
  契约正文 = `shared/gates.md` §2.5「走查单确认门」+ `rings/prd/reference.md` §4·八；
  确认门本体是人侧门（内容对不对归人），本器只判**声明与凭据对得上**。

时空域（评审 P1-2）：
  - 只扫 `.trellis/tasks/*/` 中 `task.json.status ∈ {planning, in_progress}` 的任务；
  - 已归档（completed 等）不扫——「重派生删行」的合法失效与老记录不挂永久红账；
  - task 记录缺失 / 不可解析 ⇒ 该任务 **SKIP + 原因**（响亮，不假红）。

判据（四态出口，评审 P1-1）：
  - 第 2 问 =「是」⇒ 受影响域级 PRD（`资产根/prd/<domain>-prd.md`，资产根默认
    `product/`；域由 `atlas-apply.md` 内的路径引用解析）的走查节须有确认行；缺失 / 形态非法 ⇒ **FAIL**
    指名域与文件。
  - 三问小节在、但第 2 问**不可解析** ⇒ **WARN** 指名 + 要求人工核对
    （不可解析 ≠ 未走到：防「写歪措辞静默旁路」）。
  - 无 apply 记录 / 第 2 问 =「否」/ 三问小节缺席 ⇒ **SKIP** 带原因
    （存量 adopt 不误伤）。
  - 第 2 问 =「是」但报告里解析不到受影响域级 PRD ⇒ **WARN**（要求人工核对）。

显式盲区（不查什么）：
  - 三问判定本身的语义越轨（该答「是」的答成「否」）不设防——本器锁的是
    「写下的『是』与确认行的对账」，不是「是」判得对不对；
  - §3.2 第四形态（无需求卡修订）不在本门（由 closeout 宣称 sweep 承担）；
  - 走查内容对不对（语义，用户确认时判）。

框架无关；纯标准库。CLI：`python3 validate_walkthrough.py --root <项目根> [--json]`
输出 `{ok, status, checks[]}`；判定 PASS / WARN / SKIP → 退出码 0，FAIL → 1。
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

TASKS_RELPATH = Path(".trellis") / "tasks"
APPLY_RECORD = "atlas-apply.md"
ACTIVE_STATUSES = {"planning", "in_progress"}
# Trellis 三态里的归档态；其余未知值（`in-progress` 手滑 / `blocked` 一类）
# 必须**显式 SKIP 指名**，不得静默出域（评审 P1-1：静默继续 = 门失效）
ARCHIVED_STATUSES = {"completed"}

# 三问小节标题（`## 2. 三问门判定` / `### 三问门判定`；不绑定编号）
Q_SECTION_RE = re.compile(r"^#{2,6}\s+.*三问.*$", re.M)
# 第 2 问的行首形态：`2.` / `2、` / `第 2 问` / `第二问` / 列表项包裹
Q2_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:第\s*2\s*问|第二问|2\s*[.、)）])(?:\*\*)?")
# 答句必须以「是 / 否」开头（契约 §3.1 的机器可读形态；`是否` 不在此列——
# 它只出现在问题里，问题在 `？` 之前已被切走）
ANSWER_RE = re.compile(r"^[\s*`（(【\[]*(是|否)")

# 走查节标题（`## 八、用户旅程走查`；按关键词，不绑定序号）
WALKTHROUGH_HEADING_RE = re.compile(r"^#{2,6}\s+.*用户旅程走查.*$", re.M)
# 确认行：必须是引用行首的 `> 已确认：<日期>`；模板里的说明行（`> [初稿无「已确认」行…]`）
# 不匹配本前缀，因此「未确认」不会被误判成「形态非法」
CONFIRM_LINE_RE = re.compile(r"^\s*>\s*已确认\s*[：:]")
CONFIRM_VALUE_RE = re.compile(r"^\s*>\s*已确认\s*[：:]\s*(\S+)\s*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 受影响域：报告里对域级 PRD 的路径引用（`<资产根>/prd/<domain>-prd.md`；默认 product/）
DOMAIN_PRD_RE = re.compile(
    r"(?:^|[^\w./-])(?:[A-Za-z0-9_.-]+/)*prd/([A-Za-z0-9][A-Za-z0-9_-]*)-prd\.md")


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, status: str, detail: str = "") -> None:
        self.checks.append({"check": check, "status": status, "detail": detail})

    @property
    def status(self) -> str:
        statuses = [c["status"] for c in self.checks]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        if statuses and all(s == "SKIP" for s in statuses):
            return "SKIP"
        return "PASS"

    @property
    def ok(self) -> bool:
        return self.status != "FAIL"


def _section(text: str, heading_re: re.Pattern[str]) -> str | None:
    """取标题命中的小节正文（到下一个同级或更高级标题为止）。"""
    m = heading_re.search(text)
    if not m:
        return None
    start = m.end()
    rest = text[start:]
    nxt = re.search(r"^#{2,6}\s+", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def parse_task_status(task_dir: Path) -> tuple[str | None, str]:
    """→ (status, 原因)。记录缺失 / 不可解析 ⇒ (None, 原因)。"""
    record = task_dir / "task.json"
    if not record.is_file():
        return None, "无 task.json（任务记录缺失）"
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"task.json 不可解析（{type(e).__name__}）"
    if not isinstance(data, dict):
        return None, "task.json 顶层不是 object"
    status = data.get("status")
    if not isinstance(status, str) or not status.strip():
        return None, "task.json 缺 status 字段"
    return status.strip(), ""


def parse_question_two(apply_text: str) -> tuple[str, str]:
    """→ (state, detail)。state ∈ {yes, no, unparseable, no_section, no_line}。

    只读**已写下**的判定（不替模型判语义，备选 D 已否）。答句必须「是 / 否」开头；
    其余形态一律 unparseable（WARN），不得静默旁路。
    """
    sec = _section(apply_text, Q_SECTION_RE)
    if sec is None:
        return "no_section", "无三问门判定小节"
    found: list[tuple[str, str]] = []
    for raw in sec.splitlines():
        if not Q2_LINE_RE.match(raw):
            continue
        line = Q2_LINE_RE.sub("", raw, count=1)
        # 切走问题部分：`是否…？` / `需要…?`；答句在问号之后
        parts = re.split(r"[？?]", line, maxsplit=1)
        answer = parts[1] if len(parts) > 1 else line
        m = ANSWER_RE.match(answer.strip().lstrip("：:—- "))
        found.append((("yes" if m.group(1) == "是" else "no") if m else "unparseable",
                      raw.strip()))
    if not found:
        return "no_line", "三问小节存在但无第 2 问行"
    answers = {a for a, _ in found}
    if "unparseable" in answers:
        return "unparseable", found[0][1]
    if len(answers) > 1:
        # 小节里出现多条第 2 问行且判定相反（典型：引用模板行 + 本轮判定行）——
        # 不得按 first-match-wins 取一条（评审 P1-2：模板行可遮蔽真实判定）
        return "unparseable", "多条第 2 问行判定不一致：" + " / ".join(s for _, s in found[:3])
    return answers.pop(), found[0][1]


def walkthrough_confirmation(prd_text: str) -> tuple[str, str]:
    """→ (state, detail)。state ∈ {confirmed, missing_section, missing, malformed}。"""
    sec = _section(prd_text, WALKTHROUGH_HEADING_RE)
    if sec is None:
        return "missing_section", "缺「用户旅程走查」节"
    for raw in sec.splitlines():
        if not CONFIRM_LINE_RE.match(raw):
            continue
        m = CONFIRM_VALUE_RE.match(raw)
        if m and DATE_RE.match(m.group(1)):
            return "confirmed", m.group(1)
        return "malformed", raw.strip()
    return "missing", "节首无 `> 已确认：<日期>` 行（未确认，或重派生后未重确认）"


def affected_domains(apply_text: str) -> list[str]:
    return sorted(set(DOMAIN_PRD_RE.findall(apply_text)))


def check_task(root: Path, res: Result, task_dir: Path, lay) -> None:
    name = task_dir.name
    status, why = parse_task_status(task_dir)
    if status is None:
        res.add(f"task:{name}", "SKIP", f"任务记录不可判定（{why}）——不假红，人工核对")
        return
    if status not in ACTIVE_STATUSES:
        if status in ARCHIVED_STATUSES:
            return  # 时空域：已归档不扫
        # 未知 / 变体状态（`in-progress`、`Planning`、`blocked`…）必须可见跳过：
        # 静默出域 = 该任务整体绕过走查锁，正好是本 RFC 要防的「接线断」
        res.add(f"task:{name}", "SKIP",
                f"status={status!r} 不在已知集 {sorted(ACTIVE_STATUSES | ARCHIVED_STATUSES)}"
                "——不扫但不静默，请核对任务记录")
        return

    apply_path = task_dir / APPLY_RECORD
    if not apply_path.is_file():
        res.add(f"task:{name}", "SKIP", f"无 {APPLY_RECORD}（未走到 apply / 存量记录）")
        return
    try:
        apply_text = apply_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        res.add(f"task:{name}", "SKIP", f"{APPLY_RECORD} 不可读（{e}）——不假红")
        return

    state, detail = parse_question_two(apply_text)
    if state == "no_section":
        res.add(f"task:{name}", "SKIP", "无三问门判定小节（存量 apply 记录形态）")
        return
    if state == "no_line":
        res.add(f"task:{name}", "WARN",
                f"三问小节存在但第 2 问不可解析（{detail}）——不可解析 ≠ 未走到，请人工核对")
        return
    if state == "unparseable":
        res.add(f"task:{name}", "WARN",
                f"第 2 问答句形态不可解析：{detail!r}（应写成「是 / 否」开头）"
                "——不可解析 ≠ 未走到，请人工核对")
        return
    if state == "no":
        res.add(f"task:{name}", "SKIP", "第 2 问＝否（不触发行走查确认门）")
        return

    # state == "yes"
    domains = affected_domains(apply_text)
    if not domains:
        res.add(f"task:{name}", "WARN",
                f"第 2 问＝是，但报告里未引用任何 `{lay.print_value('prd')}/<domain>-prd.md`"
                "（受影响域不可解析）——请人工核对")
        return
    for domain in domains:
        rel = lay.prd_dir.relative_to(root) / f"{domain}-prd.md"
        prd = lay.prd_dir / f"{domain}-prd.md"
        label = f"task:{name} / {domain}"
        if not prd.is_file():
            res.add(label, "FAIL", f"第 2 问＝是，但受影响域级 PRD 不存在：{rel.as_posix()}")
            continue
        cstate, cdetail = walkthrough_confirmation(
            prd.read_text(encoding="utf-8", errors="replace"))
        if cstate == "confirmed":
            res.add(label, "PASS", f"{rel.as_posix()} 走查节已确认（{cdetail}）")
        elif cstate == "missing_section":
            res.add(label, "FAIL", f"第 2 问＝是，但 {rel.as_posix()} {cdetail}")
        elif cstate == "malformed":
            res.add(label, "FAIL",
                    f"{rel.as_posix()} 确认行形态非法：{cdetail!r}"
                    "（应为 `> 已确认：YYYY-MM-DD`）")
        else:
            res.add(label, "FAIL", f"第 2 问＝是，但 {rel.as_posix()} {cdetail}")


def run(root: Path) -> Result:
    res = Result()
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        res.add("项目布局配置", "FAIL", str(exc))
        return res
    tasks_root = root / TASKS_RELPATH
    if not tasks_root.is_dir():
        res.add("时空域", "SKIP",
                f"无 {TASKS_RELPATH.as_posix()}/（项目未接 Trellis 任务，未就绪非失败）")
        return res

    task_dirs = sorted(p for p in tasks_root.iterdir() if p.is_dir())
    if not task_dirs:
        res.add("时空域", "SKIP", f"{TASKS_RELPATH.as_posix()}/ 下无任务目录")
        return res

    for task_dir in task_dirs:
        check_task(root, res, task_dir, lay)

    if not res.checks:
        # 零行 ≠ PASS：全部任务都在时空域外（已归档）必须显式可见跳过
        res.add("时空域", "SKIP",
                "无在办任务（已归档或未识别状态不扫）")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="走查单确认门机器面（声明 ⇔ 凭据）")
    ap.add_argument("--root", required=True, help="项目根")
    ap.add_argument("--json", action="store_true", help="JSON 输出（stdout）")
    args = ap.parse_args(argv)

    res = run(Path(args.root))
    payload = {"ok": res.ok, "status": res.status, "checks": res.checks}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{res.status}  validate_walkthrough")
        for c in res.checks:
            line = f"  [{c['status']}] {c['check']}"
            if c["detail"]:
                line += f" — {c['detail']}"
            print(line)
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
