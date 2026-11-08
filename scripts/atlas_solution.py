#!/usr/bin/env python3
"""atlas solution —— 多仓方案层 CLI（Phase 1：federated）。

用法：
  atlas solution init --name <名> --member <名>=<路径> [--member ...] [--no-install]
  atlas solution adopt [--name <名>] [--member <名>=<路径> ...]
  atlas solution status [--json]
  atlas solution diff [--json]
  atlas solution check [--strict] [--json]
  atlas solution lock --update [--json]

Phase 1 只做只读整合；unified / 成员代码提交（commit）在 Phase 2。
`check --strict` 用于 CI：锁缺失 / 未跟踪 / 版本或契约漂移 / 成员 dirty / 缺 URL 判 FAIL。
契约正文见 `.atlas/shared/solution.md`。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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


def build_parser() -> argparse.ArgumentParser:
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

    p_lock = sub.add_parser("lock", help="查看或更新契约锁")
    _add_common(p_lock)
    p_lock.add_argument("--update", action="store_true", help="写入 atlas.solution.lock.json")

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

    p_e2e = sub.add_parser("e2e", help="父仓跨仓 E2E（一期）：status / verify / init")
    e2e_sub = p_e2e.add_subparsers(dest="e2e_cmd", required=True)
    p_es = e2e_sub.add_parser("status", help="只读选择器命中数 / BLOCKED / N/A")
    _add_common(p_es)
    p_es.add_argument("--requirement", default=None, help="只看指定 requirements[].id")
    p_ev = e2e_sub.add_parser("verify", help="只读跑父仓 E2E 专项检查（FAIL 退出 1）")
    _add_common(p_ev)
    p_ei = e2e_sub.add_parser("init", help="幂等创建父仓 e2e-index.md 骨架")
    _add_common(p_ei)
    p_ei.add_argument("--migrate", action="store_true",
                      help="为存量父仓用例批量补 成员依赖:（输出涉及清单）")
    return ap


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
                                      install=not args.no_install)
            data = {"manifest": str(path), "solution": args.name, "mode": "federated",
                    "members": len(members)}
            print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
                  else f"[OK] solution 清单已创建: {path}")
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
            data = core.check_solution(root, strict=args.strict)
            print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
                  else core.render_check(data))
            return 1 if data["overall"] == "FAIL" else 0

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
            path = core.write_lock(root, data)
            print(json.dumps({"lock": str(path)}, ensure_ascii=False, indent=2)
                  if args.json else f"[OK] 契约锁已更新: {path}")
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
                result = kernel.status(data, kernel.read_index(root), args.requirement)
                if args.json:
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                else:
                    print(f"solution e2e status: {result['verdict']}")
                    for row in result["requirements"]:
                        print(f"  {row['requirement']}: {row['state']}"
                              + (f" → {row['selected']}" if row["selected"] else "")
                              + (f" ({row['reason']})" if row["reason"] else ""))
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
