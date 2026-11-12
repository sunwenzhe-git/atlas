#!/usr/bin/env python3
"""atlas solution —— 多仓方案层 CLI（Phase 1：federated）。

用法：
  atlas solution init --name <名> --member <名>=<路径> [--member ...] [--no-install]
  atlas solution adopt [--name <名>] [--member <名>=<路径> ...]
  atlas solution status [--json]
  atlas solution diff [--json]
  atlas solution check [--strict] [--lenient] [--json]
  atlas solution migrate --to 2 [--definition-path <路径>] [--check-members]
  atlas solution lock --update [--json]

Phase 1 只做只读整合；unified / 成员代码提交（commit）在 Phase 2。
`check --strict` 用于 CI：锁缺失 / 未跟踪 / 版本或契约漂移 / 成员 dirty / 缺 URL 判 FAIL。
契约正文见 `.atlas/shared/solution.md`。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load_solution():
    path = PKG_ROOT / "_support" / "solution.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_solution_task():
    path = PKG_ROOT / "_support" / "solution_task.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_task_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- task acceptance

AC_LINE_RE = re.compile(r"^[ \t]*atlas-acceptance:[ \t]*(.+?)\s*$")
ACS_SPLIT_RE = re.compile(r"[,，、]")
FENCE_RE = re.compile(r"^(```|~~~)")


def _card_without_ignored(text: str) -> str:
    """去围栏代码块与 HTML 注释块（I5），保留行结构。"""
    out: list[str] = []
    in_fence = False
    in_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
                line = line.split("-->", 1)[1]
                stripped = line.strip()
            else:
                out.append("")
                continue
        if not in_fence and "<!--" in line:
            head, _, tail = line.partition("<!--")
            if "-->" in tail:
                line = head + tail.split("-->", 1)[1]
                stripped = line.strip()
            else:
                in_comment = True
                line = head
                stripped = line.strip()
        if FENCE_RE.match(stripped):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def _card_has_acceptance(text: str) -> bool:
    """只认行首（允许缩进）的专用行；围栏 / HTML 注释内的不计（K-10 / K-12）。"""
    return any(AC_LINE_RE.match(line)
               for line in _card_without_ignored(text).splitlines())


def _pointer_acs(path: Path) -> list[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^[ \t]*[-*]?[ \t]*acs:[ \t]*(.+?)\s*$", text, re.M)
    if not m:
        return []
    return [t.strip() for t in ACS_SPLIT_RE.split(m.group(1)) if t.strip()]


def _run_task_acceptance_backfill(root: Path, data: dict, task_core, *,
                                  requirement: str | None, members: list[str],
                                  apply: bool) -> dict:
    """§1.3.7 / K-11：从指针 `acs:` 回填专用行；已存在即拒绝、不覆盖。"""
    plans: list[dict] = []
    warnings: list[str] = []
    refused: list[str] = []
    by_name = {m["name"]: m for m in data.get("members") or []}
    for req in data.get("requirements") or []:
        if requirement and req.get("id") != requirement:
            continue
        member_name = req.get("member")
        if members and member_name not in members:
            continue
        member = by_name.get(member_name)
        if member is None:
            warnings.append(f"{req.get('id')}: 成员 {member_name} 不在清单")
            continue
        member_dir = Path(root) / str(member["path"])
        found = task_core.find_task(member_dir, data["solution"], req["id"],
                                    member_name)
        if found is None:
            warnings.append(f"{req.get('id')}/{member_name}: 未找到任务卡（跳过）")
            continue
        card: Path = found[0] / "prd.md"
        if not card.is_file():
            warnings.append(f"{req.get('id')}/{member_name}: prd.md 缺失（跳过）")
            continue
        text = card.read_text(encoding="utf-8", errors="replace")
        if _card_has_acceptance(text):
            refused.append(str(card.relative_to(root)))
            continue
        acs = sorted(set(_pointer_acs(found[0] / "solution.md")))
        if not acs:
            acs = sorted({str(ac).strip() for ac in req.get("acs") or []
                          if str(ac).strip()})
        if not acs:
            warnings.append(f"{req.get('id')}/{member_name}: requirements.acs 为空"
                            "（不写 none，跳过）")
            continue
        line = "atlas-acceptance: " + ",".join(acs)
        if apply:
            prefix = text if (not text or text.endswith("\n")) else text + "\n"
            card.write_text(prefix + line + "\n", encoding="utf-8")
        plans.append({"card": str(card.relative_to(root)), "line": line,
                      "written": apply})
    return {"apply": apply, "plans": plans, "warnings": warnings,
            "refused": refused}


def _load_solution_e2e():
    path = PKG_ROOT / "_support" / "solution_e2e.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_e2e_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_member(raw: str) -> tuple[str, str, str]:
    if "=" not in raw:
        raise ValueError(f"--member 必须是 name=path 形式: {raw!r}")
    name, path = raw.split("=", 1)
    kind = "fullstack"
    if ":" in path:
        maybe_path, maybe_kind = path.rsplit(":", 1)
        if maybe_kind in ("frontend", "backend", "fullstack", "mobile"):
            path, kind = maybe_path, maybe_kind
    if not name.strip() or not path.strip():
        raise ValueError(f"--member 的 name/path 不能为空: {raw!r}")
    return name.strip(), path.strip(), kind


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", default=".", help="solution 根（默认当前目录）")
    p.add_argument("--json", action="store_true", help="输出 JSON")


def _package_version() -> str:
    path = PKG_ROOT / "package.json"
    try:
        return str(json.loads(path.read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError):
        return "0.0.0"


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def _semver_parts(version: str):
    m = _SEMVER.match(version.strip())
    if m is None:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))), \
        (m.group(4).split(".") if m.group(4) else [])


def _pre_lt(a: list[str], b: list[str]) -> bool:
    if not a:
        return False
    if not b:
        return True
    for x, y in zip(a, b):
        if x == y:
            continue
        xn, yn = x.isdigit(), y.isdigit()
        if xn and yn:
            return int(x) < int(y)
        if xn != yn:
            return xn
        return x < y
    return len(a) < len(b)


def semver_lt(a: str, b: str) -> bool:
    """严格 semver 比较（预发布 < 同版本正式版）；不可解析时退回字符串比较。"""
    pa, pb = _semver_parts(a), _semver_parts(b)
    if pa is None or pb is None:
        return a.strip() < b.strip()
    if pa[0] != pb[0]:
        return pa[0] < pb[0]
    return _pre_lt(pa[1], pb[1])


def _allow_dangling_acs_enabled(version: str) -> bool:
    """宽限是否仍可注册：`0.4.0` 未发布才允许（`0.4.0-beta.x < 0.4.0`）。"""
    return semver_lt(version, "0.4.0")


def build_parser(version: str | None = None) -> argparse.ArgumentParser:
    version = _package_version() if version is None else version
    ap = argparse.ArgumentParser(prog="atlas solution")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="创建 federated solution 清单与 solution 层骨架")
    _add_common(p_init)
    p_init.add_argument("--name", required=True, help="solution 名称")
    p_init.add_argument("--mode", default="federated", choices=["federated", "unified"],
                        help="Phase 1 只交付 federated；unified 显式报 Phase 2 未交付")
    p_init.add_argument("--member", action="append", default=[],
                        help="成员仓 name=path[:frontend|backend|fullstack|mobile]，可重复")
    p_init.add_argument("--assets-root", default="product")
    p_init.add_argument("--cutover", default=None,
                        help="验收切点 YYYY-MM-DD（默认 2027-03-31；往后推需同时给 "
                             "--anchor-review，且不超过默认 + 90 天）")
    p_init.add_argument("--anchor-review", default=None,
                        help="改切点的评审号（只用于 --cutover 晚于默认值时）")
    p_init.add_argument("--no-install", action="store_true", help="不自动装配 .atlas（测试/离线用）")

    p_adopt = sub.add_parser("adopt", help="检测已有成员资产并生成 federated 清单")
    _add_common(p_adopt)
    p_adopt.add_argument("--name", default=None)
    p_adopt.add_argument("--member", action="append", default=[])
    p_adopt.add_argument("--assets-root", default="product")
    p_adopt.add_argument("--no-install", action="store_true")

    p_status = sub.add_parser("status", help="只读聚合成员状态")
    _add_common(p_status)

    p_diff = sub.add_parser("diff", help="只读对账：成员相对锁的提交/文件改动")
    _add_common(p_diff)

    p_check = sub.add_parser("check", help="只读检查清单/守卫/锁；--strict 用于 CI 门禁")
    _add_common(p_check)
    p_check.add_argument("--strict", action="store_true",
                         help="锁缺失/未跟踪/漂移/dirty/缺 URL 判 FAIL，并返回非零")
    p_check.add_argument("--fix-acs", action="store_true",
                         help="dry-run 列出可移除的悬空 AC（行级保字节，不重生成清单）")
    p_check.add_argument("--apply", action="store_true",
                         help="与 --fix-acs 同用：写回后重跑 gate 定退出码")
    if _allow_dangling_acs_enabled(version):
        p_check.add_argument(
            "--allow-dangling-acs", action="store_true",
            help="临时宽限：只把 A 类悬空 AC 降为 WARN；将于 0.4.0 移除 / "
                 "最迟 2026-12-31；owner=@sunwenzhe")
    p_check.add_argument(
        "--lenient", action="store_true",
        help="开发早期放宽：成员工作区缺席记 SKIP；仓内存在封条时拒绝执行（exit 2）")
    p_check.add_argument(
        "--allow-unverifiable-chain", action="store_true",
        help="窄开关：只把「提交对象本地缺失」的 definition_commit_unverifiable 降为 WARN；"
             "不复用 --lenient")

    p_migrate = sub.add_parser("migrate", help="清单 v1 → v2（只补缺，不自动 lock）")
    _add_common(p_migrate)
    p_migrate.add_argument("--to", type=int, choices=[2], default=None,
                           help="目标清单 schema 版本（B-0 只支持 2）")
    p_migrate.add_argument("--definition-path", default=None,
                           help="定义源路径（<assets_root>/prd/<名>-prd.md；"
                                "多份候选时必须指定）")
    p_migrate.add_argument("--check-members", action="store_true",
                           help="只读：逐成员打印卡片 git add -f 命令（active 与 archive）")
    p_migrate.add_argument("--cutover", default=None,
                           help="验收切点 YYYY-MM-DD（默认 2027-03-31；往后推需同时给 "
                                "--anchor-review，且不超过默认 + 90 天）")
    p_migrate.add_argument("--anchor-review", default=None,
                           help="改切点的评审号（只用于 --cutover 晚于默认值时）")

    p_lock = sub.add_parser("lock", help="查看或更新契约锁")
    _add_common(p_lock)
    p_lock.add_argument("--update", action="store_true", help="写入 atlas.solution.lock.json")
    p_lock.add_argument("--assets-root", default=None,
                        help="改资产根（唯一出口；必须同时给 --anchor-review）")
    p_lock.add_argument("--anchor-review", default=None,
                        help="改资产根的评审号（REVIEW-YYYYMMDD-NN）")
    p_lock.add_argument("--seal", default=None,
                        help="多封条时指定封条路径（<assets_root>/reviews/apply/"
                             "<member>/<task>.seal.json）")

    p_seal = sub.add_parser("seal", help="封条生命周期：freeze / reanchor")
    seal_sub = p_seal.add_subparsers(dest="seal_cmd", required=True)
    p_sf = seal_sub.add_parser("freeze", help="冻结封条（只写锁 state/frozen_at）")
    _add_common(p_sf)
    p_sf.add_argument("--seal", required=False, default=None)
    p_sf.add_argument("--at", required=True, help="冻结提交（= 该路径 L[-1]）")
    p_sr = seal_sub.add_parser("reanchor", help="重锚：重写纪元起点并审计")
    _add_common(p_sr)
    p_sr.add_argument("--seal", required=False, default=None)
    p_sr.add_argument("--review", required=True, help="REVIEW-YYYYMMDD-NN")
    p_sr.add_argument("--from-a", required=True, dest="from_a",
                      help="不可达的旧首签提交 SHA")

    p_commit = sub.add_parser("commit", help="（Phase 2）按成员提交代码")
    _add_common(p_commit)
    p_commit.add_argument("--member", required=True)
    p_commit.add_argument("--paths", nargs="*", default=[])

    p_task = sub.add_parser("task", help="父级 requirement → 成员 Trellis 任务卡（Phase 1 增量）")
    task_sub = p_task.add_subparsers(dest="task_cmd", required=True)
    p_tc = task_sub.add_parser("create", help="创建成员任务卡（默认 dry-run）")
    _add_common(p_tc)
    p_tc.add_argument("--requirement", required=True, help="requirements[].id")
    p_tc.add_argument("--member", action="append", default=[], help="只处理指定成员，可重复")
    p_tc.add_argument("--dry-run", action="store_true", help="只打印计划（默认行为）")
    p_tc.add_argument("--apply", action="store_true", help="真正写入成员 .trellis/tasks")
    p_tc.add_argument("--resume", action="store_true", help="已存在且指针一致则跳过/补 context")
    p_tc.add_argument("--update", action="store_true", help="只更新 solution.md 指针")
    p_ts = task_sub.add_parser("status", help="只读查看 requirement → 成员任务")
    _add_common(p_ts)
    p_ts.add_argument("--requirement", default=None)
    p_ta = task_sub.add_parser("acceptance",
                               help="存量任务卡回填 atlas-acceptance 行（默认 dry-run）")
    _add_common(p_ta)
    p_ta.add_argument("--backfill", action="store_true", required=True,
                      help="从 solution.md 指针的 acs 生成专用行（已有则拒绝）")
    p_ta.add_argument("--requirement", default=None, help="只处理指定 requirements[].id")
    p_ta.add_argument("--member", action="append", default=[], help="只处理指定成员，可重复")
    p_ta.add_argument("--apply", action="store_true", help="真正写入成员任务卡")

    p_e2e = sub.add_parser("e2e", help="父仓跨仓 E2E（一期）：status / verify / init")
    e2e_sub = p_e2e.add_subparsers(dest="e2e_cmd", required=True)
    p_es = e2e_sub.add_parser("status", help="只读聚合视图：父仓跨仓用例 + 成员本地 E2E 摘要")
    _add_common(p_es)
    p_es.add_argument("--requirement", default=None, help="只看指定 requirements[].id")
    p_es.add_argument("--snapshot", action="store_true",
                      help="另写父仓只读快照到 <assets_root>/e2e/reviews/aggregate/")
    p_ev = e2e_sub.add_parser("verify", help="只读跑父仓 E2E 专项检查（FAIL 退出 1）")
    _add_common(p_ev)
    p_ei = e2e_sub.add_parser("init", help="幂等创建父仓 e2e-index.md 骨架")
    _add_common(p_ei)
    p_ei.add_argument("--migrate", action="store_true",
                      help="为存量父仓用例批量补 成员依赖:（输出涉及清单）")
    return ap


def _internal_error_report(core_mod, root: Path, exc: BaseException) -> dict:
    """RFC §3.2 第 4 层：未知异常 ⇒ 合法 JSON（`schema_version: 2`）+ 六段全进 `not_run[]`。

    异常从 `check_solution` 内部抛出时无法知道跑到第几步，按最保守口径「一段都没跑完」
    填满六项（RFC v31/S-2 用「完整六项」而不是子集）。
    """
    first = str(exc).splitlines()[0] if str(exc) else ""
    message = f"{type(exc).__name__}: {first}" if first else type(exc).__name__
    try:
        reader = core_mod.reader_version(root)
    except Exception:  # noqa: BLE001 - 报告本身不能再抛
        reader = ""
    return {
        "schema_version": 2,
        "ok": False,
        "reader_version": reader,
        "definition_source": None,
        "errors": [{"code": "internal_error", "message": message, "path": None}],
        "warnings": [],
        "info": [],
        "skipped": [],
        "downgrades": [],
        "not_run": list(core_mod.NOT_RUN_SEGMENTS),
    }


def _emit_internal_error(core_mod, root: Path, exc: BaseException, as_json: bool) -> int:
    """`internal_error` 是 exit 2 里唯一产 JSON 的出口；非 `--json` 走可读文案。"""
    report = _internal_error_report(core_mod, root, exc)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"[FAIL] internal_error: {report['errors'][0]['message']}", file=sys.stderr)
        print("未执行: " + "、".join(report["not_run"]), file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # `--root` 允许出现在子命令前（bin/atlas.js 就是这样传的）或后；先摘出来，
    # 避免 argparse 的主/子解析器默认值互相覆盖。支持 `--root <p>` 与 `--root=<p>`。
    root_arg = None
    rest: list[str] = []
    i = 0
    while i < len(raw):
        tok = raw[i]
        if tok == "--root":
            if i + 1 >= len(raw):
                print("[FAIL] --root 缺少路径", file=sys.stderr)
                return 2
            root_arg = raw[i + 1]
            i += 2
            continue
        if tok.startswith("--root="):
            root_arg = tok.split("=", 1)[1]
            i += 1
            continue
        rest.append(tok)
        i += 1
    raw = rest
    args = build_parser().parse_args(raw)
    if root_arg is not None:
        args.root = root_arg
    core = _load_solution()
    root = Path(args.root).resolve()
    try:
        if args.cmd == "init":
            if args.mode != "federated":
                raise core.SolutionError("unified 模式尚未交付（Phase 2）")
            members = [_parse_member(m) for m in args.member]
            path = core.init_solution(root, args.name, members,
                                      assets_root=args.assets_root,
                                      install=not args.no_install,
                                      cutover=args.cutover,
                                      anchor_review=args.anchor_review)
            data = {"manifest": str(path), "solution": args.name, "mode": "federated",
                    "members": len(members)}
            print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
                  else f"[OK] solution 清单已创建: {path}")
            if not args.json:
                manifest = core.load_manifest(root)
                if manifest["version"] == 2 and manifest.get("acceptance_cutover"):
                    print("     " + core._cutover_note(
                        manifest["acceptance_cutover"], args.cutover))
            return 0

        if args.cmd == "adopt":
            members = [_parse_member(m) for m in args.member] or None
            name = args.name or root.name
            path, adopted = core.adopt_solution(
                root, name, members, assets_root=args.assets_root,
                install=not args.no_install)
            data = {"manifest": str(path), "solution": name, "mode": "federated",
                    "members": [m["name"] for m in adopted]}
            print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
                  else f"[OK] solution 清单已创建: {path}\n成员: "
                       + "、".join(m["name"] for m in adopted))
            return 0

        if args.cmd == "status":
            data = core.status(root)
            print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
                  else core.render_status(data))
            return 0

        if args.cmd == "diff":
            data = core.diff_solution(root)
            print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
                  else core.render_diff(data))
            return 0

        if args.cmd == "check":
            allow = getattr(args, "allow_dangling_acs", False)
            if args.apply and not args.fix_acs:
                raise core.SolutionError("--apply 只能与 --fix-acs 同用")
            if args.lenient and core.has_apply_seal(root):
                # RFC §3.3：有封条必须严格态；拒绝执行靠工具，不靠夹具红。
                print("[FAIL] --lenient 仅限无封条", file=sys.stderr)
                return 2
            if not args.fix_acs:
                try:
                    data = core.check_solution(root, strict=args.strict,
                                               allow_dangling_acs=allow,
                                               lenient=args.lenient,
                                               allow_unverifiable_chain=(
                                                   args.allow_unverifiable_chain))
                except core.SolutionError:
                    # RFC §3.2 第 2 层：SolutionError 原样上抛（exit 2、无 JSON 报告）。
                    raise
                except Exception as exc:  # noqa: BLE001 - §3.2 第 4 层：unknown ⇒ internal_error
                    return _emit_internal_error(core, root, exc, args.json)
                print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
                      else core.render_check(data))
                return 1 if data["overall"] == "FAIL" else 0
            try:
                plan = core.fix_acs(root, core.load_manifest(root), apply=args.apply)
            except core.FixRefused as exc:
                print(f"[FAIL] {exc}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            elif not args.apply:
                for item in plan["removals"]:
                    print(f"[DRY-RUN] {item['requirement']}/{item['ac']}"
                          f" @ line {item['line']}")
                if not plan["removals"]:
                    print("[OK] 无悬空 AC，无需修复")
            else:
                for item in plan["removals"]:
                    print(f"[REMOVED] {item['requirement']}/{item['ac']}"
                          f" @ line {item['line']}")
            if not args.apply:
                return 0
            # 写成功不等于门变绿：退出码只由重跑结果决定。
            try:
                report = core.check_solution(root, strict=args.strict,
                                             allow_dangling_acs=allow,
                                             lenient=args.lenient,
                                             allow_unverifiable_chain=(
                                                 args.allow_unverifiable_chain))
            except core.SolutionError:
                raise
            except Exception as exc:  # noqa: BLE001 - 与主检查同口径
                return _emit_internal_error(core, root, exc, args.json)
            if not args.json:
                print(core.render_check(report))
            return 1 if report["overall"] == "FAIL" else 0

        if args.cmd == "migrate":
            data = core.load_manifest(root)
            if args.check_members:
                commands = core.card_tracking_commands(root, data)
                if args.json:
                    print(json.dumps({"commands": commands}, ensure_ascii=False, indent=2))
                elif commands:
                    print("[CHECK-MEMBERS] 逐成员卡片跟踪命令（只读，不执行）：")
                    for cmd in commands:
                        print(f"  {cmd}")
                else:
                    print("[CHECK-MEMBERS] 未发现需要跟踪的任务卡")
                if not args.to:
                    return 0
            if not args.to:
                raise core.SolutionError("migrate 需要 --to 2（或只用 --check-members）")
            result = core.migrate_manifest(root, to=args.to,
                                           definition_path=args.definition_path,
                                           cutover=args.cutover,
                                           anchor_review=args.anchor_review)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif not result["changed"]:
                print(f"[SKIP] {core.MANIFEST_NAME} 已是 v{result['to']}，无缺失字段")
            else:
                print(f"[OK] {core.MANIFEST_NAME} v{result['from']} → v{result['to']}；"
                      f"补: {'、'.join(result['added']) or '无'}")
                print("     " + core._cutover_note(result["acceptance_cutover"],
                                                  args.cutover))
                print("     下一步：提交清单 → atlas solution lock --update → 提交锁")
            return 0

        if args.cmd == "lock":
            if not args.update:
                lock = core.read_lock(root)
                if lock is None:
                    if args.json:
                        print(json.dumps({"lock": None,
                                          "warning": f"缺少 {core.LOCK_NAME}；运行 atlas solution lock --update"},
                                         ensure_ascii=False, indent=2))
                    else:
                        print(f"[WARN] 缺少 {core.LOCK_NAME}；运行 atlas solution lock --update")
                    return 0
                print(json.dumps(lock, ensure_ascii=False, indent=2) if args.json
                      else f"[OK] {core.LOCK_NAME} 已存在（{lock.get('locked_at')}）")
                return 0
            data = core.load_manifest(root)
            before = core.read_lock(root)
            path = core.write_lock(root, data, require_clean=True,
                                   assets_root=args.assets_root,
                                   anchor_review=args.anchor_review,
                                   seal=args.seal)
            change = core.definition_change_summary(before, core.read_lock(root))
            if args.json:
                print(json.dumps({"lock": str(path), "definition": change},
                                 ensure_ascii=False, indent=2))
            else:
                print(f"[OK] 契约锁已更新: {path}")
                for line in core.render_definition_change(change, args.anchor_review):
                    print(line)
            return 0

        if args.cmd == "seal":
            if args.seal_cmd == "freeze":
                result = core.freeze_seal(root, args.seal, args.at)
            else:
                result = core.reanchor_seal(root, args.seal, args.review,
                                            args.from_a)
            print(json.dumps(result, ensure_ascii=False, indent=2)
                  if args.json else "\n".join(f"{k}: {v}" for k, v in result.items()))
            return 0

        if args.cmd == "task":
            task_core = _load_solution_task()
            data = core.load_manifest(root)
            if args.task_cmd == "create":
                if args.apply and args.dry_run:
                    raise core.SolutionError("--apply 与 --dry-run 不能同时使用")
                result = task_core.create_tasks(
                    root, data, args.requirement,
                    members=args.member or None, apply=args.apply and not args.dry_run,
                    resume=args.resume, update=args.update,
                )
                if args.json:
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                elif not result["apply"]:
                    print("[DRY-RUN] 未写盘；确认后加 --apply")
                    for plan in result["plans"]:
                        print(f"  [{plan['action']}] {plan['member']} {plan.get('task_slug', '')}")
                else:
                    for item in result["done"]:
                        print(f"[{item['action']}] {item['member']}: {item['task']}")
                    print("任务已创建但未 start；请在成员仓用 /trellis:start 领取。")
                return 0
            if args.task_cmd == "acceptance":
                result = _run_task_acceptance_backfill(
                    root, data, task_core,
                    requirement=args.requirement,
                    members=args.member or [],
                    apply=args.apply)
                if result["refused"]:
                    for item in result["refused"]:
                        print(f"[FAIL] 已存在 atlas-acceptance 行，拒绝覆盖: {item}",
                              file=sys.stderr)
                    if args.json:
                        print(json.dumps(result, ensure_ascii=False, indent=2))
                    return 2
                if args.json:
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                elif not result["apply"]:
                    print("[DRY-RUN] 未写盘；确认后加 --apply")
                    for plan in result["plans"]:
                        print(f"  [{plan['card']}] {plan['line']}")
                else:
                    for plan in result["plans"]:
                        print(f"[written] {plan['card']}: {plan['line']}")
                for warning in result["warnings"]:
                    print(f"  [WARN] {warning}")
                return 0
            result = task_core.task_status(root, data, args.requirement)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"solution task status: {'OK' if result['ok'] else 'WARN'}")
                for row in result["requirements"]:
                    print(f"  {row['requirement']} / {row['member']}: "
                          f"{row['task'] or '缺失'}")
                for warning in result["warnings"]:
                    print(f"  [WARN] {warning}")
            return 0

        if args.cmd == "e2e":
            kernel = _load_solution_e2e()
            if not kernel.is_solution_root(root):
                raise core.SolutionError(
                    "不是父仓（需要 atlas.solution.yaml 且 mode: federated）")
            if args.e2e_cmd == "init":
                result = kernel.init(root, migrate=args.migrate)
                if args.json:
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                else:
                    print(f"[{'OK' if result['created'] else 'SKIP'}] "
                          f"父仓 E2E 索引: {result['index']}")
                    if result["migrated"]:
                        print(f"[MIGRATE] 补 成员依赖: 的用例 {len(result['migrated'])} 条：")
                        for item in result["migrated"]:
                            print(f"  - {item['file']}: {item['case'] or '(无 id)'}")
                    elif args.migrate:
                        print("[MIGRATE] 无需要迁移的用例")
                return 0

            data = core.load_manifest(root)
            if args.e2e_cmd == "status":
                result = kernel.status(data, kernel.read_index(root),
                                       args.requirement, root=root,
                                       snapshot=args.snapshot)
                if args.json:
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                else:
                    print(f"solution e2e status: {result['verdict']}")
                    for row in result["requirements"]:
                        print(f"  {row['requirement']}: {row['state']}"
                              + (f" → {row['selected']}" if row["selected"] else "")
                              + (f" ({row['reason']})" if row["reason"] else ""))
                    cases = result["parent"].get("cases") or []
                    if cases:
                        print("  父仓用例：")
                        for c in cases:
                            deps = "、".join(c["members"]) or "—"
                            print(f"    [{c['status']}/{c['review_state']}] {c['id']}"
                                  f" · 成员依赖={deps}"
                                  + (f" · {c['status_reason']}" if c["status_reason"] else ""))
                    for m in result.get("members") or []:
                        if m["state"] != "ok":
                            print(f"  成员 {m['name']}: {m['state']}（{m['reason']}）")
                            continue
                        counts = m["counts"]
                        review = m["review"]
                        print(f"  成员 {m['name']}: {counts['total']} 条"
                              f"（green {counts['green']} / red {counts['red']}"
                              f" / blocked {counts['blocked']} / skipped {counts['skipped']}）"
                              f" · review fresh {review['fresh']} / stale {review['stale']}"
                              f" / unreviewed {review['unreviewed']} / legacy {review['legacy']}"
                              f" · 最近提交 #{m['latest_seq']}")
                    if result.get("snapshot"):
                        print(f"  只读快照：{result['snapshot']}")
                    print("  本视图只读：成员评审以成员账本为准；本命令不写成员索引/账本。")
                return result["exit"]

            # verify：只判父仓 E2E 专项检查，不把无关的锁/契约 WARN 混进来。
            report = core.check_solution(root)
            checks = [c for c in report["checks"] if c["check"].startswith("父仓 E2E")]
            verdict = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "PASS"
            payload = {"verdict": verdict, "checks": checks,
                       "audit": report.get("e2e")}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"solution e2e verify: {verdict}")
                for c in checks:
                    print(f"  [{c['status']}] {c['check']}"
                          + (f" — {c['detail']}" if c["detail"] else ""))
            return 1 if verdict == "FAIL" else 0

        if args.cmd == "commit":
            print("[FAIL] solution commit 属于 Phase 2，尚未交付；"
                  "Phase 1 不修改成员仓。", file=sys.stderr)
            return 2
    except core.SolutionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 边界，响亮失败
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
