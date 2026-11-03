#!/usr/bin/env python3
"""atlas eval —— 消融对照跑分器（RFC-20261103-06）。

只做一件事：同一组 case、base/candidate 两个 commit、一条命令跑完并出机读 ledger。
**不宣称净收益 / 反事实**——那是 `research/` 台账的口径，本工具只记录「同一 case 在
两个 commit 的可复算状态」。

    atlas eval run --cases <registry.json> --base <sha> --candidate <sha> --out <dir>
                   [--timeout 300] [--retries 1] [--worktree-root <dir>] [--keep-worktrees]
    atlas eval gate --ledger <file> [--out <file>]

隔离 = `git worktree add --detach`（base / candidate 各一份，run 前先 `worktree prune`，
部分失败自动回滚已建项）；case 命令 `shlex.split` + `shell=False`（与 `ablation.py run`
同口径），cwd = 各自 worktree 项目根，逐 case 独立 timeout。worktree 默认清理，
`--keep-worktrees` 留现场（配 `--worktree-root` 显式指定根目录，便于追查）。
注意：并发跑两次同 `--out` 会互相覆盖 ledger（单用户工具）。

回归判据只有三条：① 任一 case `pass→fail`（error/timeout 视作 fail 侧；默认单跑即判，
`--retries N` 可对 candidate 侧复跑 N 次确认，防节拍类抖动定罪——口径承自
`duty-review/bugs.md` 同根归纳②「首跑不坐实，复跑复现才改判」）⇒ FAIL；
② `anchor_missing` ⇒ FAIL（不静默 SKIP；锚缺失 case 不参与 pass/fail 分类）；
③ `gate_green` 下降 ⇒ FAIL（同一 ledger 内 base/candidate 对照；两侧都有整数才判，
解析不到 ok/PASS ⇒ null + WARN 跳过——源包态 `atlas_check` 大量 SKIP，不得把
「未装配」误判成回归）。另有 `new_red`（candidate 新增即红：base 侧锚都不存在）
⇒ FAIL，不落 f2f-WARN；`new_ok` / `fail2pass` 记录不判。`fail2fail` 只 WARN
（基线本来就红，不是本批回归）。ledger 头部继承研究台账的「单项目单环境、不可外推」腿注。

退出码：`run` 0 = 跑完（case 失败不改退出码，回归归 `gate` 判）；2 = 输入/前置错误。
`gate` 0 = 无回归；1 = 有回归/锚缺失/新增即红；2 = 输入错误。纯标准库。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
LEG_NOTE = ("单项目单环境有限 case 集；不宣称净收益 / 反事实；结果不可外推"
            "（口径承自 research/2026-10-25-net-contribution-ledger.md）。")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
FAIL_SIDE = ("fail", "error", "timeout")


def die(msg: str, code: int = 2) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _git(root: Path, *args: str):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def resolve_sha(root: Path, ref: str) -> str:
    r = _git(root, "rev-parse", ref)
    if r.returncode != 0:
        raise SystemExit(die(f"ref 无法解析：{ref}（{r.stderr.strip()[-200:]}）"))
    return r.stdout.strip()


# ------------------------------------------------------------------ 注册表

def load_registry(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(die(f"读 case 注册表 {path} 失败：{exc}"))
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(die(f"{path} schema_version 必须为 {SCHEMA_VERSION}"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit(die(f"{path} 缺非空 cases[]"))
    seen: set[str] = set()
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            raise SystemExit(die(f"{path} cases[{i}] 必须为对象"))
        cid = c.get("id")
        if not (isinstance(cid, str) and ID_RE.fullmatch(cid)):
            raise SystemExit(die(f"{path} cases[{i}].id 形状非法：{cid!r}"))
        if cid in seen:
            raise SystemExit(die(f"{path} 出现重复 case id：{cid}"))
        seen.add(cid)
        if not (isinstance(c.get("anchor"), str) and c["anchor"].strip()):
            raise SystemExit(die(f"{path} cases[{i}] 缺非空 anchor"))
        if not (isinstance(c.get("command"), str) and c["command"].strip()):
            raise SystemExit(die(f"{path} cases[{i}] 缺非空 command"))
    return data


# ------------------------------------------------------------------ worktree

def make_worktrees(root: Path, base_sha: str, cand_sha: str,
                   workroot: Path) -> tuple[Path, Path]:
    """建 base/candidate 两份 worktree；任一失败回滚已建项（不留半套现场）。"""
    workroot.mkdir(parents=True, exist_ok=True)
    base_dir, cand_dir = workroot / "base", workroot / "candidate"
    created: list[Path] = []
    for sha, d in ((base_sha, base_dir), (cand_sha, cand_dir)):
        r = _git(root, "worktree", "add", "--detach", str(d), sha)
        if r.returncode != 0:
            for c in created:
                _git(root, "worktree", "remove", "--force", str(c))
            raise SystemExit(die(f"git worktree add {d} 失败：{r.stderr.strip()[-300:]}"))
        created.append(d)
    return base_dir, cand_dir


def cleanup_worktrees(root: Path, base_dir: Path, cand_dir: Path, workroot: Path) -> None:
    for d in (base_dir, cand_dir):
        r = _git(root, "worktree", "remove", "--force", str(d))
        if r.returncode != 0:
            print(f"WARN: git worktree remove {d} 失败：{r.stderr.strip()[-200:]}",
                  file=sys.stderr)
    shutil.rmtree(workroot, ignore_errors=True)


# ------------------------------------------------------------------ case 执行

def check_anchor(anchor: str, cwd: Path, timeout: int,
                 collector: list[str] | None = None) -> tuple[bool, str]:
    """锚存在性：`path::node` ⇒ 收集器收集（**只按退出码判**——节点名含 error/timeout
    等子串不再误杀，2026-11-03 评审 B1 实测）；`path#fragment` ⇒ 文件含片段
    （登记口径：表格锚建议带行分隔符如 `#| D101 |`，防交叉引用误判存在）。"""
    if "::" in anchor:
        path, node = anchor.split("::", 1)
        argv = list(collector or [sys.executable, "-m", "pytest"])
        argv += ["--collect-only", "-q", f"{path}::{node}"]
        try:
            r = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                               timeout=timeout, shell=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"锚收集失败：{exc}"
        if r.returncode != 0:
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            return False, f"收集器退出码 {r.returncode}，锚不可收集 {anchor}：{out[-200:]}"
        return True, "ok"
    if "#" in anchor:
        path, frag = anchor.split("#", 1)
        p = cwd / path
        if not p.is_file():
            return False, f"锚文件不存在：{path}"
        text = p.read_text(encoding="utf-8", errors="ignore")
        if frag not in text:
            return False, f"锚片段不在 {path} 中：{frag}"
        return True, "ok"
    return False, "anchor 必须为 path#fragment 或 path::node"


def run_case(command: str, cwd: Path, timeout: int) -> tuple[str, int, str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return "error", 0, f"命令解析失败：{exc}"
    started = time.perf_counter()
    try:
        pr = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                            timeout=timeout, shell=False)
    except FileNotFoundError as exc:
        return "error", 0, f"解释器/命令不存在：{exc}"
    except PermissionError as exc:
        return "error", 0, f"无执行权限：{exc}"
    except subprocess.TimeoutExpired:
        return "timeout", timeout * 1000, "超时"
    ms = int((time.perf_counter() - started) * 1000)
    detail = ((pr.stdout or "") + (pr.stderr or "")).strip()[-400:]
    return ("pass" if pr.returncode == 0 else "fail"), ms, detail


def measure_gate(command: str | None, base_dir: Path, cand_dir: Path,
                 timeout: int) -> dict:
    """`gate_command` 在两个 worktree 各跑一次，数 `ok`/`PASS` 行；解析不到 ⇒ null + WARN。"""
    if not command:
        return {"base": None, "candidate": None,
                "warn": "未提供 gate_command：门全绿判据跳过（不 FAIL）"}
    counts: dict[str, int | None] = {"base": None, "candidate": None}
    warn = None
    for label, d in (("base", base_dir), ("candidate", cand_dir)):
        try:
            pr = subprocess.run(shlex.split(command), cwd=str(d), capture_output=True,
                                text=True, timeout=timeout, shell=False)
        except (FileNotFoundError, ValueError) as exc:
            warn = f"gate_command 不可执行/解析失败：{exc}"
            counts = {"base": None, "candidate": None}
            break
        except subprocess.TimeoutExpired:
            warn = "gate_command 超时"
            counts = {"base": None, "candidate": None}
            break
        counts[label] = sum(1 for line in (pr.stdout or "").splitlines()
                            if line.strip() and line.split(None, 1)[0] in ("ok", "PASS"))
    if counts["base"] == 0 and counts["candidate"] == 0:
        warn = "gate_command 输出解析不到 ok/PASS 行（可能未装配）：门全绿判据跳过"
        counts = {"base": None, "candidate": None}
    return {"base": counts["base"], "candidate": counts["candidate"], "warn": warn}


# ------------------------------------------------------------------ run

def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    registry_path = Path(args.cases)
    if not registry_path.is_absolute():
        registry_path = root / registry_path
    registry = load_registry(registry_path)
    base_sha = resolve_sha(root, args.base)
    cand_sha = resolve_sha(root, args.candidate)
    if base_sha == cand_sha:
        return die("base 与 candidate 是同一 commit（对照跑分无差异，不冒充跑分）")
    _git(root, "worktree", "prune")  # 先清历史残留（被杀进程留下的注册）
    if args.worktree_root:
        workroot = Path(args.worktree_root)
        if not workroot.is_absolute():
            workroot = root / workroot
    else:
        workroot = Path(tempfile.mkdtemp(prefix="atlas-eval-"))
    base_dir = cand_dir = None
    try:
        base_dir, cand_dir = make_worktrees(root, base_sha, cand_sha, workroot)
        collector = None
        if registry.get("anchor_collector"):
            collector = shlex.split(str(registry["anchor_collector"]))
        cases_out: list[dict] = []
        for case in registry["cases"]:
            a_ok, a_detail = check_anchor(case["anchor"], cand_dir, args.timeout, collector)
            a_ok_base, a_detail_base = check_anchor(case["anchor"], base_dir,
                                                    args.timeout, collector)
            if a_ok_base:
                base_status, b_ms, b_detail = run_case(case["command"], base_dir,
                                                       args.timeout)
            else:
                # candidate 新增：base 侧锚都不存在，跑了也是必红——跳过并如实记 skipped
                base_status, b_ms, b_detail = "skipped", None, ""
            c_status, c_ms, c_detail = run_case(case["command"], cand_dir, args.timeout)
            # 节拍类防抖（口径承自 duty-review/bugs.md 同根归纳②）：p→f 在 candidate
            # 侧复跑确认，复跑绿 ⇒ 不定罪
            retries_used = 0
            if (base_status == "pass" and c_status in FAIL_SIDE
                    and args.retries > 1 and a_ok):
                for attempt in range(2, args.retries + 1):
                    retries_used = attempt - 1
                    c_status, c_ms2, c_detail2 = run_case(case["command"], cand_dir,
                                                          args.timeout)
                    if c_status == "pass":
                        c_ms, c_detail = c_ms2, c_detail2
                        break
            detail = c_detail if c_status in FAIL_SIDE else (b_detail or c_detail)
            cases_out.append({"id": case["id"], "kind": case.get("kind") or "",
                              "anchor": case["anchor"], "anchor_ok": a_ok,
                              "anchor_detail": a_detail,
                              "anchor_ok_base": a_ok_base,
                              "anchor_detail_base": a_detail_base,
                              "base_status": base_status, "candidate_status": c_status,
                              "base_ms": b_ms, "candidate_ms": c_ms,
                              "retries_used": retries_used,
                              "detail": detail[:400]})
            flag = "ok" if a_ok else "MISSING"
            flag_b = "ok" if a_ok_base else "missing(base)"
            print(f"  {case['id']:<12} {base_status:>7} → {c_status:<7} "
                  f"anchor cand={flag} base={flag_b}"
                  + (f" retries={retries_used}" if retries_used else ""))
        gate_green = measure_gate(registry.get("gate_command"), base_dir, cand_dir,
                                  args.timeout)
    finally:
        if base_dir is not None:
            if args.keep_worktrees:
                print(f"KEEP: worktrees 保留在 {workroot}")
            else:
                cleanup_worktrees(root, base_dir, cand_dir, workroot)

    # 分类：candidate 侧锚缺失 = 无效 case 不参与；base 缺锚 + candidate 红 = 新增即红
    summary = {"pass2pass": 0, "pass2fail": 0, "fail2pass": 0, "fail2fail": 0,
               "anchor_missing": 0, "new_red": 0, "new_ok": 0}
    for c in cases_out:
        if not c["anchor_ok"]:
            summary["anchor_missing"] += 1
        elif not c["anchor_ok_base"] and c["candidate_status"] in FAIL_SIDE:
            summary["new_red"] += 1
        elif not c["anchor_ok_base"]:
            summary["new_ok"] += 1
        elif c["base_status"] == "pass" and c["candidate_status"] == "pass":
            summary["pass2pass"] += 1
        elif c["base_status"] == "pass":
            summary["pass2fail"] += 1
        elif c["candidate_status"] == "pass":
            summary["fail2pass"] += 1
        else:
            summary["fail2fail"] += 1
    outdir = Path(args.out) if args.out else root / ".atlas" / "runs" / "eval"
    if not outdir.is_absolute():
        outdir = root / outdir
    outdir.mkdir(parents=True, exist_ok=True)
    registry_sha = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    ledger = {"schema_version": SCHEMA_VERSION, "generated_at": now_iso(),
              "root": str(root), "base": base_sha, "candidate": cand_sha,
              "registry_sha256": registry_sha,
              "case_ids": [c["id"] for c in cases_out],
              "note": LEG_NOTE, "cases": cases_out, "summary": summary,
              "gate_green": gate_green}
    (outdir / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")
    warns = [gate_green.get("warn")] if gate_green.get("warn") else []
    for c in cases_out:
        if not c["anchor_ok"]:
            warns.append(f"{c['id']} 锚缺失：{c['anchor_detail']}")
    print(f"atlas eval run @ {outdir / 'ledger.json'}   cases {len(cases_out)}   "
          + " ".join(f"{k}={v}" for k, v in summary.items())
          + f"   gate_green {gate_green['base']}→{gate_green['candidate']}")
    for w in warns:
        print(f"  · WARN {w}")
    return 0


# ------------------------------------------------------------------ gate

def _load_ledger(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(die(f"读 ledger {path} 失败：{exc}"))
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(die(f"{path} schema_version 必须为 {SCHEMA_VERSION}"))
    if not isinstance(data.get("cases"), list):
        raise SystemExit(die(f"{path} 缺 cases[]"))
    return data


def cmd_gate(args: argparse.Namespace) -> int:
    ledger = _load_ledger(Path(args.ledger))
    regressions: list[dict] = []
    missing: list[dict] = []
    new_red: list[dict] = []
    f2f: list[dict] = []
    for c in ledger["cases"]:
        if not c.get("anchor_ok", False):
            missing.append(c)
        elif c.get("base_status") == "pass" and c.get("candidate_status") in FAIL_SIDE:
            regressions.append(c)
        elif c.get("anchor_ok_base") is False and c.get("candidate_status") in FAIL_SIDE:
            new_red.append(c)  # candidate 新增即红：不是「基线本来就红」
        elif c.get("base_status") in FAIL_SIDE and c.get("candidate_status") in FAIL_SIDE:
            f2f.append(c)
    green_drop = None
    green = ledger.get("gate_green") or {}
    if isinstance(green.get("base"), int) and isinstance(green.get("candidate"), int):
        if green["candidate"] < green["base"]:
            green_drop = f"gate_green 下降：{green['base']} → {green['candidate']}"
    else:
        print("WARN: gate_green 不完整（未提供 gate_command 或解析不到 ok/PASS 行）："
              "门全绿判据跳过")

    fails = []
    for c in regressions:
        fails.append(f"pass→fail：{c['id']}（{c.get('anchor')}）")
    for c in missing:
        fails.append(f"锚缺失：{c['id']}（{c.get('anchor_detail', '')[:120]}）")
    for c in new_red:
        fails.append(f"新增即红：{c['id']}（{c.get('anchor')}）")
    if green_drop:
        fails.append(green_drop)
    status = "FAIL" if fails else "PASS"
    print(f"atlas eval gate   {status}   cases {len(ledger['cases'])}   "
          f"regressions {len(regressions)}   anchor_missing {len(missing)}   "
          f"new_red {len(new_red)}   fail2fail {len(f2f)}")
    for f in fails:
        print(f"  · {f}")
    if f2f:
        print(f"  · WARN fail2fail（基线本来就红，不计回归）：{[c['id'] for c in f2f]}")
    if args.out:
        # 相对路径按 ledger 记录的项目根解析（与 run 的 --out 同口径）
        out = Path(args.out)
        if not out.is_absolute():
            base_root = Path(str(ledger.get("root") or Path.cwd()))
            out = base_root / out
        result = {"schema_version": SCHEMA_VERSION, "status": status,
                  "regressions": [c["id"] for c in regressions],
                  "anchor_missing": [c["id"] for c in missing],
                  "new_red": [c["id"] for c in new_red],
                  "fail2fail": [c["id"] for c in f2f], "gate_green_drop": green_drop,
                  "checked_at": now_iso()}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # `--root` 放顶层：`bin/atlas.js` 的转发形态是 `atlas_eval.py --root <dir> <sub> ...`
    ap.add_argument("--root", default=".", help="项目根（git 仓库）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="base/candidate 两 worktree 对照跑分，出机读 ledger")
    r.add_argument("--cases", required=True, help="case 注册表 JSON（指针索引）")
    r.add_argument("--base", required=True, help="基线 ref/sha")
    r.add_argument("--candidate", required=True, help="候选 ref/sha")
    r.add_argument("--out", help="ledger 输出目录（默认 .atlas/runs/eval）")
    r.add_argument("--timeout", type=int, default=300, help="每 case 超时秒数")
    r.add_argument("--retries", type=int, default=1,
                   help="pass→fail 时 candidate 侧复跑确认次数（默认 1 = 不复跑）")
    r.add_argument("--worktree-root", dest="worktree_root",
                   help="worktree 根目录（默认系统临时目录）")
    r.add_argument("--keep-worktrees", dest="keep_worktrees", action="store_true",
                   help="保留 worktree 现场（调试）")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("gate",
                       help="判回归：pass→fail / 锚缺失 / 新增即红 / gate_green 下降")
    g.add_argument("--ledger", required=True, help="atlas eval run 产出的 ledger.json")
    g.add_argument("--out", help="判定结果 JSON 输出路径（相对 ledger.root 解析）")
    g.set_defaults(func=cmd_gate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
