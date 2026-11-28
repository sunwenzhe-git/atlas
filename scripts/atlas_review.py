#!/usr/bin/env python3
"""实例⑤实现代码独立审查 —— 一键编排（RFC-20261103-05）。

把 `shared/closeout.md` 步骤 10 的 6 步手工命令收成一个入口，**只编排不重写判据**：

    inputs（可选）→ background（指针化）→ preview 取 N → CLI review 出 cli.json
    → scope manifest（coverage.completed / --reviewed-files）→ cli_review_convert
    → validate_review_report --scope-manifest → review_closure

无可用 CLI（impl_review 未配置 / llm 为 null / executor: session）时走**会话执行器**
（issue #68）：只产 `review-request.md` 派工包并以「待审」退出（exit 2，不是通过）；
当前会话派 fresh-context 子代理写 `<报告目录>/cli.json` 后复跑，从 scope manifest 继续。

用法：

    atlas review --unit <需求ID> --from main --to HEAD
    atlas review --unit <需求ID> --from main --to HEAD --delta-only \
        --base-sha <r1-head> --head-sha <修复后 head> --round 2
    atlas review ... --dry-run          # 只跑 preview（只读）+ 打印将执行命令，不写盘
    atlas review ... --cli <name>       # 覆盖 stack-profile 的 impl_review.cli

退出码：0 全步通过（WARN 不置红）；1 有 FAIL（converter/validator）；2 输入/前置错误
（含会话执行器的「待审」）；子步非 0/1/2 的原退出码透传（如外部 CLI 的 7）。纯标准库。
"""
# ATLAS_CHANGE_AUTO_V1
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
from _support.layout import LayoutError, load_layout  # noqa: E402
from _support import review_scope_core as scope_core  # noqa: E402
from _support.siblings import load_module  # noqa: E402
from _support.bug_backflow import (  # noqa: E402
    BackflowError, resolve_defect_root, review_anchor, validate_backflow,
)
from _support.bug_record import atomic_write_bytes, read_record  # noqa: E402
from _support.workflow_causes import exit_code_for  # noqa: E402
from _support.workflow_plan import load_tasks  # noqa: E402

stack_profile = load_module("stack_profile")

UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# 真 CLI flag 形态锁（测试与 shared/closeout.md 步骤 10 双向比对；改契约必须同步这里）
PREVIEW_FLAGS = ("--preview", "--from", "--to")
REVIEW_FLAGS = ("--audience", "--format", "--output", "--background-file", "--from", "--to")


def die(msg: str, code: int = 2) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def info(msg: str) -> None:
    print(msg)


def load_impl_review(root: Path) -> dict:
    """读 stack-profile 的 impl_review；缺段/缺文件 = 全 None（调用方按会话执行器处理）。"""
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        return {"cli": None, "llm": None, "executor": None, "error": str(exc)}
    p = lay.stack_profile
    if not p.is_file():
        return {"cli": None, "llm": None, "executor": None}
    try:
        data = stack_profile.parse_profile(p.read_text(encoding="utf-8"))
    except Exception as exc:  # 解析失败不裸崩；按未配处理并保留原因
        return {"cli": None, "llm": None, "executor": None, "error": str(exc)}
    impl = data.get("impl_review")
    if not isinstance(impl, dict):
        return {"cli": None, "llm": None, "executor": None}
    return {"cli": impl.get("cli"), "llm": impl.get("llm"),
            "executor": impl.get("executor")}


def resolve_executor(impl: dict, cli_override: str | None) -> tuple[str, str | None, str]:
    """执行器判定：cli（外部进程）/ session（当前会话派 fresh-context 子代理）。

    返回 (executor, cli, 说明)。未声明 executor 时：cli + llm 齐备才走 CLI，
    否则回落 session —— 不再用 SKIP 把「未配置」伪装成已走完（issue #68）。
    """
    if cli_override:
        return "cli", cli_override, "显式 --cli 覆盖"
    declared = str(impl.get("executor") or "").strip().lower()
    cli, llm = impl.get("cli"), impl.get("llm")
    if declared not in ("", "cli", "session"):
        raise SystemExit(die(f"impl_review.executor 只支持 cli|session，当前为 {declared!r}"))
    if declared == "cli":
        if not cli:
            raise SystemExit(die("impl_review.executor=cli 但 impl_review.cli 未配置"
                                 "（改 executor: session，或配置 cli + llm）"))
        return "cli", cli, ""
    if declared == "session":
        return "session", None, ""
    if cli and llm is not None:
        return "cli", cli, ""
    return "session", None, (
        "impl_review.llm 未配置，CLI 不可执行" if cli else "impl_review.cli 未配置")


def preview_argv(cli: str, ref_from: str | None = None, ref_to: str | None = None,
                 *, staged: bool = False) -> list[str]:
    if staged:
        return [cli, "review", "--preview"]
    return [cli, "review", "--preview", "--from", ref_from or "", "--to", ref_to or ""]


def review_argv(cli: str, ref_from: str | None = None, ref_to: str | None = None,
                out_json: Path = Path("cli.json"), background: Path = Path("background.md"),
                *, staged: bool = False) -> list[str]:
    base = [cli, "review", "--audience", "agent", "--format", "json",
            "--output", str(out_json), "--background-file", str(background)]
    if staged:
        return base
    return base + ["--from", ref_from or "", "--to", ref_to or ""]


def parse_preview_n(output: str) -> int | None:
    m = re.search(r"Will review\s*:?\s*(\d+)", output or "", re.I)
    return int(m.group(1)) if m else None


def _run(argv: list[str], root: Path, *, capture: bool = False):
    command = [str(x) for x in argv]
    if sys.platform == "win32" and command:
        executable = shutil.which(command[0])
        target = Path(executable or command[0]).expanduser()
        if target.is_file() and not executable \
                and target.suffix.lower() not in {".exe", ".cmd", ".bat"}:
            command = [sys.executable, *command]
    return subprocess.run(command, cwd=str(root), capture_output=capture,
                          text=True, encoding="utf-8", errors="replace")


def _show(pr, *, capture: bool) -> None:
    if capture:
        if pr.stdout:
            print(pr.stdout.rstrip())
        if pr.stderr:
            print(pr.stderr.rstrip(), file=sys.stderr)


def _asset_root(root: Path) -> tuple[str, str, str]:
    """返回 (prd 目录, 用例目录, 索引路径) 的布局值；布局失败回退 product/ 默认。"""
    try:
        lay = load_layout(root)
        return (lay.print_value("prd"), lay.print_value("e2e_cases"),
                lay.print_value("e2e_index"))
    except LayoutError:
        return "product/prd", "product/e2e/cases", "product/e2e/e2e-index.md"


def build_background(root: Path, outdir: Path, unit: str, args: argparse.Namespace,
                     inputs_dir: Path | None) -> Path:
    """背景文件：显式 --background 原样收编；否则生成**指针化** Markdown（不复制正文）。"""
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / "background.md"
    if args.background:
        src = Path(args.background)
        if not src.is_absolute():
            src = root / src
        if not src.is_file():
            raise SystemExit(die(f"--background 文件不存在：{src}"))
        text = src.read_text(encoding="utf-8")
        if not text.strip():
            raise SystemExit(die(f"--background 文件为空：{src}"))
        target.write_text(text, encoding="utf-8")
        return target
    default_prd, default_cases, _index = _asset_root(root)
    prd = args.prd or default_prd
    cases = args.cases or default_cases
    requirement = args.requirement or f".atlas/tasks/{unit}/prd.md"
    lines = [f"# 实现代码独立审查 — {unit}", "",
             "> 由 `atlas review` 组装（指针化，不复制正文）。", "",
             "## 需求卡", f"- `{requirement}`"
             + ("" if (root / requirement).is_file() else "（未找到，按当前代码事实调查）"),
             "", "## 受影响域 AC", f"- `{prd if prd.endswith('/') else prd + '/'}`", "",
             "## 相关用例断言", f"- `{cases if cases.endswith('/') else cases + '/'}`", ""]
    if inputs_dir is not None:
        lines += ["## 审查输入清单", f"- `{inputs_dir}/MANIFEST.json`", ""]
    lines += ["## 审查焦点三问",
              "见 `.atlas/shared/independent-review.md` §10.4（只引路径，不复制正文）。", ""]
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def run_inputs(root: Path, outdir: Path, enabled: bool) -> Path | None:
    if not enabled:
        return None
    inputs = outdir / "inputs"
    pr = _run([sys.executable, HERE / "make_review_inputs.py", "--root", root,
               "--out", str(inputs)], root, capture=True)
    _show(pr, capture=True)
    if pr.returncode != 0:
        print("WARN: make_review_inputs 失败（继续审查；background 不含 MANIFEST 指针）",
              file=sys.stderr)
        return None
    return inputs


def _coverage_paths(cli_json: Path, key: str = "completed") -> list[str]:
    try:
        data = json.loads(cli_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(die(f"读 {cli_json} 失败：{exc}"))
    coverage = ((data.get("manifest") or {}).get("coverage") or {}) if isinstance(data, dict) else {}
    completed = coverage.get(key) if isinstance(coverage, dict) else None
    paths: list[str] = []
    for item in completed or []:
        p = item.get("path") if isinstance(item, dict) else item
        if isinstance(p, str) and p.strip():
            paths.append(p.strip().replace("\\", "/"))
    return sorted(set(paths))


def write_review_request(unit: str, args: argparse.Namespace, background: Path,
                         inputs_dir: Path | None, cli_json: Path, agent_dir: Path) -> Path:
    """会话执行器派工包：给 fresh-context 子代理的指针清单 + 产出骨架（不复制正文）。"""
    mode = "暂存区（HEAD..INDEX）" if args.staged else f"{args.ref_from}..{args.ref_to}"
    manifest_ptr = (f"- 输入清单：`{inputs_dir / 'MANIFEST.json'}`（按清单读当前文件，不拷贝）"
                    if inputs_dir is not None else "- 输入清单：未生成（缺资产，按当前代码事实调查）")
    skeleton = {
        "status": "completed",
        "executor": "session-subagent",
        "summary": {"files_reviewed": 0, "comments": 0},
        "comments": [{
            "severity": "critical|high|medium|low",
            "category": "bug|security|performance|maintainability|test|style|documentation",
            "path": "src/a.ts", "start_line": 1, "end_line": 2,
            "existing_code": "<finding 指向代码的逐字摘录，1-5 行>",
            "content": "<问题描述 + 证据链（file:line）>", "suggestion_code": "",
        }],
        "warnings": [],
        "manifest": {"coverage": {
            "selected": [{"path": "src/a.ts"}],
            "completed": [{"path": "src/a.ts"}],
            "failed": [], "waived": [], "reused": [],
        }},
    }
    lines = [
        f"# 实现代码独立审查派工单 — {unit}", "",
        "> 由 `atlas review` 生成（`impl_review.executor: session`）。本文件是**指针**，不复制正文。", "",
        "## 独立性要求（硬）",
        "- 派一个 **fresh-context 子代理** 执行审查：**不得**继承实现/生成时的上下文。",
        "- 子代理只读下面的指针，不读整仓；**只写产物**，不得改业务代码、不得改暂存区。", "",
        "## 权威输入", f"- 背景：`{background}`", manifest_ptr,
        "- 审查焦点三问：`.atlas/shared/independent-review.md` §10.4", "",
        "## 探索预算（硬）",
        "- 只读本单指针与实审集（你产物 `manifest.coverage.selected[]` 的 N 个文件）；"
        "工具调用上界 **≤ N + 8 次**（N = 实审文件数，自行计数）。",
        "- 禁入 `product/reviews/`（含 findings/）与 `.atlas/tasks/` 的历史轮产物；"
        "round ≥ 2 的复审只审上轮 findings 涉及文件及其直接引用。",
        "- 逃生门：发现流程异常（脏工作区 / 轮次产物矛盾）允许扩面，"
        "但必须在 cli.json `warnings` 登记扩面理由。",
        "",
        "## 审查范围", f"- 模式：{mode}",
        "- 应审文件：在产物 `manifest.coverage.selected[]` 中逐项列出本次实审范围"
        "（缺该项 ⇒ 应审 N 不可得，转换器拒绝产出）", "",
        "## 产物", f"- 写到：`{cli_json}`",
        "- 每条 finding 必须带 `existing_code`：finding 指向代码的**逐字摘录**"
        "（1-5 行，从 diff 或相关文件原样复制，禁止改写/重排/缩进调整）——行号锚定复算输入，"
        "缺失按 unanchored 统计（不判错，RFC-20261122-08）。",
        "- 审查顺序：先审变更核心（heart），再审其后果（consequences），"
        "最后审胶水（glue：配置/注册/样板）。",
        "- 形态（CLI 同构 JSON，供 `cli_review_convert.py` 转换）：", "",
        "```json", json.dumps(skeleton, ensure_ascii=False, indent=2), "```", "",
        "## 完成后",
        "- 复跑 `atlas workflow verify --unit <ID>`（或 `atlas review --unit <ID> --staged`）："
        "读取本轮 `cli.json`，继续 scope manifest → 转换 → 校验 → 闭环。",
        "- `finish` 仍只认 `review.json` 为 PASS；本派工包本身**不是通过**。", "",
    ]
    target = agent_dir / "review-request.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def _split_paths(value: str | None) -> list[str]:
    return sorted({p.strip().replace("\\", "/") for p in (value or "").split(",") if p.strip()})


def _staged_paths(root: Path) -> list[str]:
    """`git diff --cached --name-only` 获取暂存区路径；非 git 仓或失败返回空。"""
    try:
        pr = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=str(root),
                            capture_output=True, text=True, timeout=15)
        if pr.returncode == 0:
            return sorted({ln.strip().replace("\\", "/") for ln in pr.stdout.splitlines() if ln.strip()})
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def seal_bug_anchor(root: Path, unit: str, outdir: Path) -> None:
    tasks_root = root / ".atlas" / "tasks"
    if not tasks_root.is_dir():
        return
    task = next((item for item in load_tasks(tasks_root, include_archived=True)
                 if item.get("id") == unit), None)
    if not task or not task.get("requirement_root"):
        return
    checked = validate_backflow(root, task)
    if not checked["applicable"]:
        return
    if checked["findings"]:
        raise BackflowError("；".join(checked["findings"]), cause=checked["cause"])
    req_root = resolve_defect_root(root, Path(str(task["requirement_root"])).name)
    record = read_record(req_root) if req_root is not None else None
    if req_root is None or record is None:
        raise BackflowError("变更/缺陷台账缺失", cause="bug_backflow_missing")
    review_file = outdir / "review.json"
    data = json.loads(review_file.read_text(encoding="utf-8"))
    data.pop("bug_backflow", None)
    data["change_backflow"] = review_anchor(root, req_root, record)
    atomic_write_bytes(review_file, json.dumps(data, ensure_ascii=False, indent=2,
                                               sort_keys=True).encode("utf-8") + b"\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--unit", required=True, help="需求 ID（执行层任务卡 id）")
    ap.add_argument("--staged", action="store_true", help="审暂存区改动（与 --from/--to 互斥）")
    ap.add_argument("--from", dest="ref_from", default=None, help="git 起 ref（preview 用）")
    ap.add_argument("--to", dest="ref_to", default=None, help="git 止 ref")
    ap.add_argument("--check-cmd", help="执行确定性检查命令（如 npm test 或 pytest），并入审查报告")
    ap.add_argument("--auto-fix", action="store_true", help="尝试自动修复机械类问题并复验一轮")
    ap.add_argument("--fix-cmd", help="显式自动修复命令（例如 npm run lint -- --fix）")
    ap.add_argument("--expected-files", type=int, help="应审 N（缺省 = preview 的 Will review）")
    ap.add_argument("--scope", default="", help="报告的一句话范围描述")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--delta-only", action="store_true")
    ap.add_argument("--base-sha", help="delta 基线 HEAD")
    ap.add_argument("--head-sha", help="delta 止点 HEAD")
    ap.add_argument("--reviewed-files", help="逗号分隔实审集（无 coverage 时必填）")
    ap.add_argument("--resolves", help="跨轮关闭声明文件")
    ap.add_argument("--escalate-to", help="round ≥ 4 升级复议人/团队")
    ap.add_argument("--escalate-reason", help="round ≥ 4 升级复议理由")
    ap.add_argument("--accept-scope-drift", help="用户确认接受内容漂移：当前 scope_sha256")
    ap.add_argument("--accept-by", help="确认人（--accept-scope-drift 时必填）")
    ap.add_argument("--accept-reason", help="确认理由（--accept-scope-drift 时必填）")
    ap.add_argument("--user-confirmed", action="store_true", help="确认内容漂移由用户显式作出")
    ap.add_argument("--cli", help="覆盖 stack-profile 的 impl_review.cli")
    ap.add_argument("--background", help="显式 background Markdown；缺省生成指针化文件")
    ap.add_argument("--requirement", help="需求卡路径（background 指针）")
    ap.add_argument("--prd", help="域级 PRD 目录/文件（background 指针）")
    ap.add_argument("--cases", help="用例分片目录（background 指针）")
    ap.add_argument("--out", help="报告目录（默认 product/reviews/<日期>-impl-review-<unit>）")
    ap.add_argument("--inputs", dest="inputs", action="store_true", default=True,
                    help="运行 make_review_inputs 生成指针清单（默认开）")
    ap.add_argument("--no-inputs", dest="inputs", action="store_false")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not UNIT_RE.fullmatch(args.unit):
        return die(f"unit「{args.unit}」含文件名不安全字符")
    if args.staged:
        if args.ref_from or args.ref_to:
            return die("--staged 与 --from/--to 互斥")
    else:
        if not (args.ref_from and args.ref_to):
            return die("--from 与 --to 必填（或传 --staged）")
    if args.round < 1:
        return die("round 必须 ≥ 1")
    impl = load_impl_review(root)
    executor, cli, why = resolve_executor(impl, args.cli)
    if executor == "cli" and impl.get("llm") is None:
        print("WARN: impl_review.llm 未配置，CLI 模型由执行器默认", file=sys.stderr)
    if executor == "cli" and not (shutil.which(cli) or Path(cli).expanduser().is_file()):
        return die(f"impl_review.cli 不存在/不可执行：{cli}")

    outdir = Path(args.out) if args.out else (
        root / "product" / "reviews" / f"{datetime.now().date().isoformat()}-impl-review-{args.unit}")
    if not outdir.is_absolute():
        outdir = root / outdir
    cli_json = outdir / "cli.json"
    scope_manifest = outdir / "scope-manifest.json"
    steps: list[dict] = []

    # 0) toolchain（确定性检查并轨，若指定 --check-cmd）
    if args.check_cmd:
        if args.dry_run:
            print(f"$ {args.check_cmd}（确定性工具链检查；dry-run 不跑）")
        else:
            info(f"toolchain: 运行检查 {args.check_cmd}")
            pr_chk = subprocess.run(args.check_cmd, shell=True, cwd=str(root),
                                    capture_output=True, text=True)
            _show(pr_chk, capture=True)
            chk_ok = pr_chk.returncode == 0
            steps.append({
                "name": "toolchain",
                "status": "ok" if chk_ok else "FAIL",
                "detail": f"exit={pr_chk.returncode}"
            })
            if not chk_ok:
                if args.auto_fix and args.fix_cmd:
                    info(f"toolchain: 尝试自动修复 {args.fix_cmd}")
                    subprocess.run(args.fix_cmd, shell=True, cwd=str(root), capture_output=True)
                else:
                    print(f"WARN: 确定性检查失败（exit={pr_chk.returncode}），继续执行审查以便汇总全部问题",
                          file=sys.stderr)

    inputs_dir: Path | None = None
    if executor == "cli":
        # 1) preview（只读；dry-run 也跑，为了报 N）
        preview = preview_argv(cli, args.ref_from, args.ref_to, staged=args.staged)
        if args.dry_run:
            print("$ " + " ".join(preview))
            pr = _run(preview, root, capture=True)
            _show(pr, capture=True)
            if pr.returncode != 0:
                return pr.returncode
            n = parse_preview_n(pr.stdout or "")
            if n is None:
                return die("preview 输出缺 `Will review N`（缺权威输入，不猜）")
        else:
            pr = _run(preview, root, capture=True)
            _show(pr, capture=True)
            if pr.returncode != 0:
                return pr.returncode
            n = parse_preview_n(pr.stdout or "")
            if n is None:
                return die("preview 输出缺 `Will review N`（缺权威输入，不猜）")
        expected = args.expected_files if args.expected_files is not None else n
        steps.append({"name": "preview", "status": "ok", "detail": f"Will review {n}"})
        info(f"preview: Will review {n}（应审 N = {expected}）")

        # 2) background + inputs
        if args.dry_run:
            print(f"$ # background → {outdir / 'background.md'}（指针化；dry-run 不写）")
            if args.inputs:
                print(f"$ {sys.executable} {HERE / 'make_review_inputs.py'} --root {root} "
                      f"--out {outdir / 'inputs'}")
        else:
            inputs_dir = run_inputs(root, outdir, args.inputs)
            bg = build_background(root, outdir, args.unit, args, inputs_dir)
            steps.append({"name": "background", "status": "ok", "detail": str(bg)})
            if inputs_dir:
                steps.append({"name": "inputs", "status": "ok",
                              "detail": str(inputs_dir / "MANIFEST.json")})
            else:
                steps.append({"name": "inputs", "status": "WARN", "detail": "未生成（或缺资产）"})

        # 3) CLI review
        review = review_argv(cli, args.ref_from, args.ref_to, cli_json,
                             outdir / "background.md", staged=args.staged)
        if args.dry_run:
            print("$ " + " ".join(review))
        else:
            pr = _run(review, root, capture=True)
            _show(pr, capture=True)
            if pr.returncode != 0:
                steps.append({"name": "cli_review", "status": "FAIL",
                              "detail": f"exit={pr.returncode}"})
                if args.json:
                    print(json.dumps({"unit": args.unit, "out": str(outdir), "steps": steps},
                                     ensure_ascii=False, indent=1))
                return pr.returncode
            if not cli_json.is_file():
                return die(f"CLI 未产出 {cli_json}（缺权威输入）")
            steps.append({"name": "cli_review", "status": "ok", "detail": str(cli_json)})
    else:
        # 会话执行器：本进程拉不起宿主子代理 ⇒ 产出派工包，等当前会话派 fresh-context
        # 子代理写 cli.json 后复跑（issue #68；契约 shared/independent-review.md §10.1）。
        if why:
            info(f"INFO: {why} ⇒ 会话执行器（派 fresh-context 子代理）")
        if args.dry_run:
            print(f"$ # 会话执行器：正式运行将生成 {outdir / 'review-request.md'}，"
                  f"等待会话子代理产出 {cli_json} 后复跑")
            return 0
        inputs_dir = run_inputs(root, outdir, args.inputs)
        bg = build_background(root, outdir, args.unit, args, inputs_dir)
        steps.append({"name": "background", "status": "ok", "detail": str(bg)})
        if inputs_dir:
            steps.append({"name": "inputs", "status": "ok",
                          "detail": str(inputs_dir / "MANIFEST.json")})
        else:
            steps.append({"name": "inputs", "status": "WARN", "detail": "未生成（或缺资产）"})
        if not cli_json.is_file():
            packet = write_review_request(args.unit, args, bg, inputs_dir, cli_json, outdir)
            steps.append({"name": "session_review", "status": "PENDING", "detail": str(packet)})
            rerun = f"atlas review --unit {args.unit}"
            rerun += " --staged" if args.staged else f" --from {args.ref_from} --to {args.ref_to}"
            rerun += f" --round {args.round}" if args.round != 1 else ""
            if args.json:
                print(json.dumps({"unit": args.unit, "out": str(outdir), "steps": steps,
                                  "status": "PENDING"}, ensure_ascii=False, indent=1))
            else:
                info(f"PENDING: 会话执行器待审（不是通过）—— 派工包 {packet}")
                info(f"  1) 派 fresh-context 子代理按派工包审查，写 {cli_json}")
                info(f"  2) 复跑 {rerun}（读取 cli.json 后继续转换/校验/收口）")
            return 2
        selected = _coverage_paths(cli_json, "selected")
        expected = args.expected_files if args.expected_files is not None else len(selected)
        if not expected:
            return die("会话审查缺 manifest.coverage.selected[]（应审 N 不可得）；"
                       "请按派工包补全或显式传 --expected-files")
        steps.append({"name": "session_review", "status": "ok", "detail": str(cli_json)})
        info(f"session: 读取会话子代理产物 {cli_json}（应审 N = {expected}）")

    # 4) scope manifest（只覆盖实审集；不覆盖全工作区）
    reviewed = _coverage_paths(cli_json) if cli_json.is_file() else []
    if not reviewed:
        reviewed = _split_paths(args.reviewed_files)
    if not reviewed and args.staged:
        reviewed = _staged_paths(root)
    if not reviewed:
        if not args.dry_run:
            return die("v4 需要实审文件列表：CLI coverage.completed 为空且未给 --reviewed-files")
        reviewed = ["<coverage.completed>"]
    if args.dry_run:
        hash_source = "index" if args.staged else "worktree"
        print(f"$ {sys.executable} {HERE / 'review_scope.py'} manifest --root {root} "
              f"--reviewed-files {','.join(reviewed)} --hash-source {hash_source} --out {scope_manifest}")
    else:
        try:
            base_ref = "HEAD" if args.staged else args.ref_from
            head_ref = "INDEX" if args.staged else args.ref_to
            hash_source = "index" if args.staged else "worktree"
            manifest = scope_core.build_manifest(root, reviewed,
                                                 base=base_ref, head=head_ref,
                                                 hash_source=hash_source)
            scope_core.atomic_write_json(scope_manifest, manifest)
        except scope_core.ScopeError as exc:
            return die(str(exc))
        steps.append({"name": "scope", "status": "ok",
                      "detail": f"{len(reviewed)} files / {manifest['scope_sha256'][:16]}…"})

    # 5) converter
    scope = args.scope or f"impl-review {args.unit}"
    conv = [sys.executable, HERE / "cli_review_convert.py", "--root", root,
            "--input", cli_json, "--out", outdir, "--unit", args.unit,
            "--round", str(args.round), "--expected-files", str(expected),
            "--reviewed-files", ",".join(reviewed), "--scope-manifest", scope_manifest,
            "--scope", scope]
    if args.delta_only:
        conv += ["--delta-only"]
        if args.base_sha:
            conv += ["--base-sha", args.base_sha]
        if args.head_sha:
            conv += ["--head-sha", args.head_sha]
    if args.resolves:
        conv += ["--resolves", args.resolves]
    if args.escalate_to:
        conv += ["--escalate-to", args.escalate_to]
    if args.escalate_reason:
        conv += ["--escalate-reason", args.escalate_reason]
    if args.accept_scope_drift:
        conv += ["--accept-scope-drift", args.accept_scope_drift]
    if args.accept_by:
        conv += ["--accept-by", args.accept_by]
    if args.accept_reason:
        conv += ["--accept-reason", args.accept_reason]
    if args.user_confirmed:
        conv += ["--user-confirmed"]
    # 行级锚定复算基准（RFC-20261122-08；模式推导先例 = :483-486 scope base/head）
    if args.staged:
        conv += ["--diff-staged"]
    elif args.base_sha and args.head_sha:
        conv += ["--diff-base", args.base_sha, "--diff-head", args.head_sha]
    elif args.ref_from and args.ref_to:
        conv += ["--diff-base", args.ref_from, "--diff-head", args.ref_to]
    if args.dry_run:
        print("$ " + " ".join(str(x) for x in conv))
    else:
        pr = _run(conv, root, capture=True)
        _show(pr, capture=True)
        if pr.returncode not in (0, 1):
            return pr.returncode
        steps.append({"name": "convert", "status": "ok" if pr.returncode == 0 else "FAIL",
                      "detail": f"exit={pr.returncode}"})

    if not args.dry_run:
        try:
            seal_bug_anchor(root, args.unit, outdir)
            steps.append({"name": "change_backflow_anchor", "status": "ok", "detail": "独立锚已封口"})
        except BackflowError as exc:
            return die(str(exc), exit_code_for(exc.cause))

    # 6) validator（只对本轮新产出报告带 --scope-manifest）
    val = [sys.executable, HERE / "validate_review_report.py", "--dir", outdir,
           "--scope-manifest", scope_manifest]
    if args.dry_run:
        print("$ " + " ".join(str(x) for x in val))
    else:
        pr = _run(val, root, capture=True)
        _show(pr, capture=True)
        if pr.returncode not in (0, 1):
            return pr.returncode
        steps.append({"name": "validate", "status": "ok" if pr.returncode == 0 else "FAIL",
                      "detail": f"exit={pr.returncode}"})

    # 7) closure（观察面；WARN 不置红）
    clo = [sys.executable, HERE / "review_closure.py", "--dir", outdir]
    if args.dry_run:
        print("$ " + " ".join(str(x) for x in clo))
    else:
        pr = _run(clo, root, capture=True)
        _show(pr, capture=True)
        if pr.returncode != 0:
            return pr.returncode
        steps.append({"name": "closure", "status": "ok", "detail": f"exit={pr.returncode}"})

    failed = any(s["status"] == "FAIL" for s in steps)
    if args.json:
        print(json.dumps({"unit": args.unit, "out": str(outdir), "steps": steps,
                          "status": "FAIL" if failed else "ok"},
                         ensure_ascii=False, indent=1))
    else:
        print(f"atlas review @ {outdir}   {'FAIL' if failed else 'ok'}   steps {len(steps)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
