#!/usr/bin/env python3
"""实例⑤实现代码独立审查 —— 一键编排（RFC-20261103-05）。

把 `shared/closeout.md` 步骤 10 的 6 步手工命令收成一个入口，**只编排不重写判据**：

    inputs（可选）→ background（指针化）→ preview 取 N → CLI review 出 cli.json
    → scope manifest（coverage.completed / --reviewed-files）→ cli_review_convert
    → validate_review_report --scope-manifest → review_closure

用法：

    atlas review --unit <需求ID> --from main --to HEAD
    atlas review --unit <需求ID> --from main --to HEAD --delta-only \
        --base-sha <r1-head> --head-sha <修复后 head> --round 2
    atlas review ... --dry-run          # 只跑 preview（只读）+ 打印将执行命令，不写盘
    atlas review ... --cli <name>       # 覆盖 stack-profile 的 impl_review.cli

退出码：0 全步通过（WARN 不置红）；1 有 FAIL（converter/validator）；2 输入/前置错误；
子步非 0/1/2 的原退出码透传（如外部 CLI 的 7）。纯标准库。
"""
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
    """读 stack-profile 的 impl_review；缺段/缺文件 = None（调用方按 SKIP/未配处理）。"""
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        return {"cli": None, "llm": None, "error": str(exc)}
    p = lay.stack_profile
    if not p.is_file():
        return {"cli": None, "llm": None}
    try:
        data = stack_profile.parse_profile(p.read_text(encoding="utf-8"))
    except Exception as exc:  # 解析失败不裸崩；按未配处理并保留原因
        return {"cli": None, "llm": None, "error": str(exc)}
    impl = data.get("impl_review")
    if not isinstance(impl, dict):
        return {"cli": None, "llm": None}
    return {"cli": impl.get("cli"), "llm": impl.get("llm")}


def preview_argv(cli: str, ref_from: str, ref_to: str) -> list[str]:
    return [cli, "review", "--preview", "--from", ref_from, "--to", ref_to]


def review_argv(cli: str, ref_from: str, ref_to: str, out_json: Path,
                background: Path) -> list[str]:
    return [cli, "review", "--audience", "agent", "--format", "json",
            "--output", str(out_json), "--background-file", str(background),
            "--from", ref_from, "--to", ref_to]


def parse_preview_n(output: str) -> int | None:
    m = re.search(r"Will review\s*:?\s*(\d+)", output or "", re.I)
    return int(m.group(1)) if m else None


def _run(argv: list[str], root: Path, *, capture: bool = False):
    return subprocess.run([str(x) for x in argv], cwd=str(root), capture_output=capture,
                          text=True)


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
    requirement = args.requirement or f".trellis/tasks/{unit}/prd.md"
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


def _coverage_paths(cli_json: Path) -> list[str]:
    try:
        data = json.loads(cli_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(die(f"读 {cli_json} 失败：{exc}"))
    coverage = ((data.get("manifest") or {}).get("coverage") or {}) if isinstance(data, dict) else {}
    completed = coverage.get("completed") if isinstance(coverage, dict) else None
    paths: list[str] = []
    for item in completed or []:
        p = item.get("path") if isinstance(item, dict) else item
        if isinstance(p, str) and p.strip():
            paths.append(p.strip().replace("\\", "/"))
    return sorted(set(paths))


def _split_paths(value: str | None) -> list[str]:
    return sorted({p.strip().replace("\\", "/") for p in (value or "").split(",") if p.strip()})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--unit", required=True, help="需求 ID（Trellis task id）")
    ap.add_argument("--from", dest="ref_from", required=True, help="git 起 ref（preview 用）")
    ap.add_argument("--to", dest="ref_to", required=True, help="git 止 ref")
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
    if args.round < 1:
        return die("round 必须 ≥ 1")
    impl = load_impl_review(root)
    cli = args.cli or impl.get("cli")
    if not cli:
        return die("impl_review.cli 未配置（stack-profile），且未给 --cli")
    if impl.get("llm") is None:
        if not args.cli:
            print("SKIP: impl_review.llm 未配置（不是通过；配好 llm 或显式 --cli 覆盖）")
            return 0
        print("WARN: impl_review.llm 未配置，--cli 显式覆盖（模型由 CLI 默认）", file=sys.stderr)
    if not (shutil.which(cli) or Path(cli).expanduser().is_file()):
        return die(f"impl_review.cli 不存在/不可执行：{cli}")

    outdir = Path(args.out) if args.out else (
        root / "product" / "reviews" / f"{datetime.now().date().isoformat()}-impl-review-{args.unit}")
    if not outdir.is_absolute():
        outdir = root / outdir
    cli_json = outdir / "cli.json"
    scope_manifest = outdir / "scope-manifest.json"
    steps: list[dict] = []

    # 1) preview（只读；dry-run 也跑，为了报 N）
    preview = preview_argv(cli, args.ref_from, args.ref_to)
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
            steps.append({"name": "inputs", "status": "ok", "detail": str(inputs_dir / "MANIFEST.json")})
        else:
            steps.append({"name": "inputs", "status": "WARN", "detail": "未生成（或缺资产）"})

    # 3) CLI review
    review = review_argv(cli, args.ref_from, args.ref_to, cli_json,
                         outdir / "background.md")
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

    # 4) scope manifest（只覆盖实审集；不覆盖全工作区）
    reviewed = _coverage_paths(cli_json) if cli_json.is_file() else []
    if not reviewed:
        reviewed = _split_paths(args.reviewed_files)
    if not reviewed:
        if not args.dry_run:
            return die("v4 需要实审文件列表：CLI coverage.completed 为空且未给 --reviewed-files")
        reviewed = ["<coverage.completed>"]
    if args.dry_run:
        print(f"$ {sys.executable} {HERE / 'review_scope.py'} manifest --root {root} "
              f"--reviewed-files {','.join(reviewed)} --out {scope_manifest}")
    else:
        try:
            manifest = scope_core.build_manifest(root, reviewed,
                                                 base=args.ref_from, head=args.ref_to)
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
    if args.dry_run:
        print("$ " + " ".join(str(x) for x in conv))
    else:
        pr = _run(conv, root, capture=True)
        _show(pr, capture=True)
        if pr.returncode not in (0, 1):
            return pr.returncode
        steps.append({"name": "convert", "status": "ok" if pr.returncode == 0 else "FAIL",
                      "detail": f"exit={pr.returncode}"})

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
