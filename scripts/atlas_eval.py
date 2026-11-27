#!/usr/bin/env python3
"""atlas eval —— 消融与跨仓宿主对照跑分器（RFC-20261103-06 / RFC-20261126-03）。

做两件事：
1. `run`：同一仓内同一组 case、base/candidate 两个 commit 对照出机读 ledger；
2. `host`：跨仓宿主对照——把 `atlas` 源仓的 `--harness-base` 与 `--harness-cand`
   （git ref 或 `WORKTREE`）分别装配到外部宿主仓（如 `atlas-playground`）的
   两份隔离 worktree 中，跑完注册表用例并采集 `check-events.jsonl` 增量；
3. `gate`：对 `run` 或 `host` 产出的 `ledger.json` 判回归（`pass→fail` / `anchor_missing`
   / `new_red` / `gate_green` 下降 ⇒ exit 1）。

**不宣称净收益 / 反事实**——那是 `research/` 台账的口径，本工具只记录「同一 case 在
两个版本的可复算状态」。

    atlas eval run  --cases <registry.json> --base <sha> --candidate <sha> --out <dir>
                    [--timeout 300] [--retries 1] [--worktree-root <dir>] [--keep-worktrees]
    atlas eval host --cases <registry.json> --harness-base <ref> --harness-cand <ref|WORKTREE>
                    [--harness-root <dir>] [--host-root <dir>] [--host-ref <ref>] [--out <dir>]
                    [--timeout 300] [--retries 1] [--worktree-root <dir>] [--keep-worktrees]
                    [--no-skill] [--no-wiring] [--allow-noop]
    atlas eval gate --ledger <file> [--out <file>]

隔离 = `git worktree add --detach`（run 前先 `worktree prune`，跨双仓统一最外层
`try...finally` 清理，部分失败自动回滚已建项）；case 命令跨平台 `split_command` + `shell=False`
（与 `ablation.py run` 同口径），cwd = 各自 worktree 项目根，逐 case 独立 timeout。
`host` 模式默认**启用** skills 与接线装配（写进隔离 `<host_wt>`，不触碰用户 `~/`），
保证 `skills/` 与 `agent-pointer.md` 变更真正进入被测面（M258）；`WORKTREE` 模式
通过 `pkg_digest` + `install.py` sha256 拒绝空跑同态对照（M257）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# 随包内核引导（`_support/`）：跨平台 argv 拆分单源。此前直用 `shlex.split`，
# 其默认 posix=True 在 Windows 上把反斜杠当转义符吃掉（`C:\a\b.py` → `C:ab.py`）；
# POSIX（macOS/Linux）侧行为不变，故此处替换对 macOS 无影响。
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.argv_split import split_command as _split_command  # noqa: E402

SCHEMA_VERSION = 1
PKG_ROOT = Path(__file__).resolve().parents[1]
LEG_NOTE = ("单项目单环境有限 case 集；不宣称净收益 / 反事实；结果不可外推"
            "（口径承自 research/2026-10-25-net-contribution-ledger.md）。")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
FAIL_SIDE = ("fail", "error", "timeout")


class EvalSetupError(RuntimeError):
    """worktree 建树 / 装配 / 同态守卫等前置失败（exit 2，交由外层统一清理）。"""


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

def _add_worktree(repo: Path, sha: str, dest: Path,
                  tracked: list[tuple[Path, Path]]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = _git(repo, "worktree", "add", "--detach", str(dest), sha)
    if r.returncode != 0:
        raise EvalSetupError(f"git worktree add {dest} 失败：{r.stderr.strip()[-300:]}")
    tracked.append((repo, dest))
    return dest


def _cleanup_tracked_worktrees(tracked: list[tuple[Path, Path]], workroot: Path) -> None:
    for repo, dest in reversed(tracked):
        r = _git(repo, "worktree", "remove", "--force", str(dest))
        if r.returncode != 0:
            print(f"WARN: git worktree remove {dest} 失败：{r.stderr.strip()[-200:]}",
                  file=sys.stderr)
    seen_repos: set[Path] = set()
    for repo, _dest in tracked:
        if repo not in seen_repos:
            seen_repos.add(repo)
            _git(repo, "worktree", "prune")
    shutil.rmtree(workroot, ignore_errors=True)


def make_worktrees(root: Path, base_sha: str, cand_sha: str,
                   workroot: Path) -> tuple[Path, Path]:
    """建 base/candidate 两份 worktree；任一失败回滚已建项（不留半套现场）。"""
    workroot.mkdir(parents=True, exist_ok=True)
    base_dir, cand_dir = workroot / "base", workroot / "candidate"
    created: list[tuple[Path, Path]] = []
    try:
        _add_worktree(root, base_sha, base_dir, created)
        _add_worktree(root, cand_sha, cand_dir, created)
    except EvalSetupError as exc:
        _cleanup_tracked_worktrees(created, workroot)
        raise SystemExit(die(str(exc)))
    return base_dir, cand_dir


def cleanup_worktrees(root: Path, base_dir: Path, cand_dir: Path, workroot: Path) -> None:
    _cleanup_tracked_worktrees([(root, base_dir), (root, cand_dir)], workroot)


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
        argv = _split_command(command)
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
            pr = subprocess.run(_split_command(command), cwd=str(d), capture_output=True,
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


# ------------------------------------------------------------------ run & host 共用执行/统计

def _execute_case_loop(registry: dict, base_dir: Path, cand_dir: Path,
                       timeout: int, retries: int) -> tuple[list[dict], dict]:
    collector = _split_command(str(registry["anchor_collector"])) if registry.get("anchor_collector") else None
    cases_out: list[dict] = []
    for case in registry["cases"]:
        a_ok, a_detail = check_anchor(case["anchor"], cand_dir, timeout, collector)
        a_ok_base, a_detail_base = check_anchor(case["anchor"], base_dir, timeout, collector)
        if a_ok_base:
            base_status, b_ms, b_detail = run_case(case["command"], base_dir, timeout)
        else:
            # candidate 新增：base 侧锚都不存在，跑了也是必红——跳过并如实记 skipped
            base_status, b_ms, b_detail = "skipped", None, ""
        c_status, c_ms, c_detail = run_case(case["command"], cand_dir, timeout)
        # 节拍类防抖（口径承自 duty-review/bugs.md 同根归纳②）：p→f 在 candidate
        # 侧复跑确认，复跑绿 ⇒ 不定罪
        retries_used = 0
        if base_status == "pass" and c_status in FAIL_SIDE and retries > 1 and a_ok:
            for attempt in range(2, retries + 1):
                retries_used = attempt - 1
                c_status, c_ms2, c_detail2 = run_case(case["command"], cand_dir, timeout)
                if c_status == "pass":
                    c_ms, c_detail = c_ms2, c_detail2
                    break
        detail = c_detail if c_status in FAIL_SIDE else (b_detail or c_detail)
        cases_out.append({
            "id": case["id"], "kind": case.get("kind") or "",
            "anchor": case["anchor"], "anchor_ok": a_ok,
            "anchor_detail": a_detail,
            "anchor_ok_base": a_ok_base,
            "anchor_detail_base": a_detail_base,
            "base_status": base_status, "candidate_status": c_status,
            "base_ms": b_ms, "candidate_ms": c_ms,
            "retries_used": retries_used,
            "detail": detail[:400],
        })
        flag = "ok" if a_ok else "MISSING"
        flag_b = "ok" if a_ok_base else "missing(base)"
        print(f"  {case['id']:<12} {base_status:>7} → {c_status:<7} "
              f"anchor cand={flag} base={flag_b}"
              + (f" retries={retries_used}" if retries_used else ""))
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
    return cases_out, summary


def _resolve_cwd(raw: str | Path) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else (Path.cwd() / p)


def _assembly_signature(harness_dir: Path) -> tuple[str, str]:
    """计算源包装配集摘要 + install.py sha256（M257：WORKTREE anti-noop 判据）。"""
    installer = harness_dir / "install.py"
    if not installer.is_file():
        raise EvalSetupError(
            f"不支持无 install.py 的历史基线：{harness_dir}（仅支持 >= 479d958 的 Atlas 源仓）")
    scripts_dir = str(PKG_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from pkg_digest import EmptyAssembly, digest  # noqa: E402
    try:
        asm_digest = digest(harness_dir)
    except (EmptyAssembly, OSError, ValueError) as exc:
        raise EvalSetupError(f"无法计算装配摘要 {harness_dir}：{exc}")
    installer_sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    return asm_digest, installer_sha


def _assemble_host(harness_dir: Path, host_wt: Path, *,
                   no_skill: bool, no_wiring: bool, timeout: int) -> None:
    """将指定版本 Atlas 装配进隔离宿主 worktree。

    M258：默认不传 `--no-skill` / `--no-wiring`，使 `skills/` 与 `agent-pointer.md`
    真正写入隔离 `<host_wt>`（不触碰用户 `~/`）。
    """
    installer = harness_dir / "install.py"
    if not installer.is_file():
        raise EvalSetupError(f"缺少 install.py：{harness_dir}")
    cmd = [sys.executable, str(installer), "--target", str(host_wt), "--update", "--force"]
    if no_skill:
        cmd.append("--no-skill")
    if no_wiring:
        cmd.append("--no-wiring")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    try:
        pr = subprocess.run(cmd, cwd=str(harness_dir), capture_output=True, text=True,
                            timeout=timeout, env=env, shell=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvalSetupError(f"装配失败（{harness_dir} → {host_wt}）：{exc}")
    if pr.returncode != 0:
        detail = ((pr.stdout or "") + "\n" + (pr.stderr or "")).strip()[-400:]
        raise EvalSetupError(
            f"install.py --update 退出码 {pr.returncode}（{harness_dir} → {host_wt}）：{detail}")


def _count_nonempty_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
               if ln.strip())


def _summarize_events_delta(path: Path, start_nonempty: int) -> dict:
    """只读读取 case 阶段新增的 check-events.jsonl 行（剔除 ablation_id 与损坏行）。"""
    out = {"runs": 0, "parse_errors": 0, "fail_rows": 0, "warn_rows": 0,
           "ok_rows": 0, "total_duration_ms": 0, "by_gate": {}}
    if not path.is_file():
        return out
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if ln.strip()]
    for raw in lines[start_nonempty:]:
        try:
            ev = json.loads(raw)
        except ValueError:
            out["parse_errors"] += 1
            continue
        if not isinstance(ev, dict) or not isinstance(ev.get("rows"), list):
            out["parse_errors"] += 1
            continue
        if ev.get("ablation_id") is not None:
            continue
        out["runs"] += 1
        for row in ev["rows"]:
            if not isinstance(row, dict):
                continue
            name, status = row.get("name"), row.get("status")
            dur = row.get("duration_ms")
            if not isinstance(name, str) or not isinstance(status, str):
                continue
            bucket = out["by_gate"].setdefault(
                name, {"fail": 0, "warn": 0, "ok": 0, "duration_ms": 0})
            if status == "FAIL":
                out["fail_rows"] += 1
                bucket["fail"] += 1
            elif status == "WARN":
                out["warn_rows"] += 1
                bucket["warn"] += 1
            elif status in ("ok", "PASS"):
                out["ok_rows"] += 1
                bucket["ok"] += 1
            if isinstance(dur, (int, float)) and not isinstance(dur, bool):
                d_int = int(round(dur))
                out["total_duration_ms"] += d_int
                bucket["duration_ms"] += d_int
    return out


def _render_host_summary(ledger: dict) -> str:
    s = ledger["summary"]
    g = ledger["gate_green"]
    ev = ledger.get("check_events_delta") or {}
    lines = [
        "# Atlas 跨仓宿主沙箱对照报告 (`atlas eval host`)",
        "",
        f"- **生成时间**：{ledger['generated_at']}",
        f"- **源包仓 (`harness_root`)**：`{ledger['harness_root']}`",
        f"- **宿主仓 (`host_root`)**：`{ledger['host_root']}` @ `{ledger['host_ref']}`",
        f"- **对照版本**：`{ledger['base'][:12]}` → `{ledger['candidate']}`",
        f"- **汇总**：" + " / ".join(f"`{k}={v}`" for k, v in s.items())
        + f" · `gate_green`: `{g.get('base')} → {g.get('candidate')}`",
        "",
        "| Case | Kind | Base | Cand | Base(ms) | Cand(ms) | Anchor |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in ledger["cases"]:
        lines.append(
            f"| `{c['id']}` | {c['kind'] or '—'} | {c['base_status']} | {c['candidate_status']} "
            f"| {c['base_ms'] if c['base_ms'] is not None else '—'} "
            f"| {c['candidate_ms'] if c['candidate_ms'] is not None else '—'} "
            f"| {'ok' if c['anchor_ok'] else 'MISSING'} |"
        )
    if ev:
        lines += [
            "",
            "## 运行态轨迹增量 (`check-events.jsonl`)",
            f"- **base**：runs={ev['base']['runs']} · fail_rows={ev['base']['fail_rows']} "
            f"· warn_rows={ev['base']['warn_rows']} · total_ms={ev['base']['total_duration_ms']}",
            f"- **candidate**：runs={ev['candidate']['runs']} · fail_rows={ev['candidate']['fail_rows']} "
            f"· warn_rows={ev['candidate']['warn_rows']} · total_ms={ev['candidate']['total_duration_ms']}",
        ]
    lines += ["", f"> {ledger['note']}"]
    return "\n".join(lines) + "\n"


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
        cases_out, summary = _execute_case_loop(
            registry, base_dir, cand_dir, args.timeout, args.retries)
        gate_green = measure_gate(registry.get("gate_command"), base_dir, cand_dir,
                                  args.timeout)
    finally:
        if base_dir is not None:
            if args.keep_worktrees:
                print(f"KEEP: worktrees 保留在 {workroot}")
            else:
                cleanup_worktrees(root, base_dir, cand_dir, workroot)

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


def cmd_host(args: argparse.Namespace) -> int:
    harness_root = Path(args.harness_root).resolve() if args.harness_root else PKG_ROOT.resolve()
    if not (harness_root / "install.py").is_file() or not (harness_root / ".git").exists():
        return die(
            f"--harness-root 必须是含 install.py 与 .git 的 Atlas 源仓：{harness_root}（请显式传 --harness-root）")
    host_root = Path(args.host_root).resolve() if args.host_root else Path(args.root).resolve()
    if not (host_root / ".git").exists():
        return die(f"--host-root 必须是 git 仓库：{host_root}")
    registry_path = _resolve_cwd(args.cases)
    registry = load_registry(registry_path)

    host_ref_raw = args.host_ref or str(registry.get("host_ref") or "HEAD")
    host_sha = resolve_sha(host_root, host_ref_raw)
    harness_base_sha = resolve_sha(harness_root, args.harness_base)
    is_worktree = (args.harness_cand == "WORKTREE")
    harness_cand_sha = None if is_worktree else resolve_sha(harness_root, args.harness_cand)
    if not is_worktree and harness_base_sha == harness_cand_sha and not args.allow_noop:
        return die("harness-base 与 harness-cand 是同一 commit（同态对照，拒绝空跑；确需重放请传 --allow-noop）")

    _git(harness_root, "worktree", "prune")
    _git(host_root, "worktree", "prune")
    workroot = (_resolve_cwd(args.worktree_root) if args.worktree_root
                else Path(tempfile.mkdtemp(prefix="atlas-eval-host-")))
    workroot.mkdir(parents=True, exist_ok=True)
    tracked_worktrees: list[tuple[Path, Path]] = []
    try:
        base_harness_dir = _add_worktree(
            harness_root, harness_base_sha, workroot / "harness-base", tracked_worktrees)
        cand_harness_dir = (
            harness_root if is_worktree
            else _add_worktree(harness_root, harness_cand_sha,
                               workroot / "harness-cand", tracked_worktrees)
        )
        base_sig = _assembly_signature(base_harness_dir)
        cand_sig = _assembly_signature(cand_harness_dir)
        if base_sig == cand_sig and not args.allow_noop:  # M257: WORKTREE 同态拒绝
            raise EvalSetupError(
                "candidate 与 harness-base 的装配集摘要及 install.py 完全一致（无差异可测，拒绝空跑；"
                "若只改了非装配文件并确需重放，请传 --allow-noop）")

        base_host_dir = _add_worktree(
            host_root, host_sha, workroot / "host-base", tracked_worktrees)
        cand_host_dir = _add_worktree(
            host_root, host_sha, workroot / "host-cand", tracked_worktrees)
        _assemble_host(base_harness_dir, base_host_dir,
                       no_skill=args.no_skill, no_wiring=args.no_wiring, timeout=args.timeout)
        _assemble_host(cand_harness_dir, cand_host_dir,
                       no_skill=args.no_skill, no_wiring=args.no_wiring, timeout=args.timeout)

        events_rel = Path(".atlas") / "runs" / "check-events.jsonl"
        before_base = _count_nonempty_lines(base_host_dir / events_rel)
        before_cand = _count_nonempty_lines(cand_host_dir / events_rel)
        cases_out, summary = _execute_case_loop(
            registry, base_host_dir, cand_host_dir, args.timeout, args.retries)
        # 在 measure_gate 之前截取 case 阶段增量，避免 gate_command 污染事件账
        check_events_delta = {
            "base": _summarize_events_delta(base_host_dir / events_rel, before_base),
            "candidate": _summarize_events_delta(cand_host_dir / events_rel, before_cand),
        }
        gate_green = measure_gate(registry.get("gate_command"), base_host_dir, cand_host_dir,
                                  args.timeout)
    except EvalSetupError as exc:
        return die(str(exc))
    finally:
        if args.keep_worktrees and tracked_worktrees:
            print(f"KEEP: worktrees 保留在 {workroot}")
        elif not args.keep_worktrees:
            _cleanup_tracked_worktrees(tracked_worktrees, workroot)

    outdir = _resolve_cwd(args.out) if args.out else (host_root / ".atlas" / "runs" / "eval-host")
    outdir.mkdir(parents=True, exist_ok=True)
    registry_sha = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    cand_label = f"WORKTREE({harness_cand_sha or resolve_sha(harness_root, 'HEAD')[:12]})" if is_worktree else harness_cand_sha
    ledger = {
        "schema_version": SCHEMA_VERSION,
        "mode": "host",
        "generated_at": now_iso(),
        "root": str(host_root),
        "harness_root": str(harness_root),
        "host_root": str(host_root),
        "host_ref": host_sha,
        "base": harness_base_sha,
        "candidate": cand_label,
        "registry_sha256": registry_sha,
        "case_ids": [c["id"] for c in cases_out],
        "note": LEG_NOTE,
        "cases": cases_out,
        "summary": summary,
        "gate_green": gate_green,
        "check_events_delta": check_events_delta,
    }
    (outdir / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")
    (outdir / "summary.md").write_text(_render_host_summary(ledger), encoding="utf-8")
    warns = [gate_green.get("warn")] if gate_green.get("warn") else []
    for c in cases_out:
        if not c["anchor_ok"]:
            warns.append(f"{c['id']} 锚缺失：{c['anchor_detail']}")
    print(f"atlas eval host @ {outdir / 'ledger.json'}   cases {len(cases_out)}   "
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

    h = sub.add_parser("host", help="跨仓宿主对照：源包 base/candidate 分别装配到外部宿主隔离跑分")
    h.add_argument("--cases", required=True, help="case 注册表 JSON（相对 cwd 解析）")
    h.add_argument("--harness-base", required=True, help="Atlas 源包基线 ref/sha")
    h.add_argument("--harness-cand", required=True, help="Atlas 源包候选 ref/sha 或 WORKTREE")
    h.add_argument("--harness-root", help="Atlas 源包 git 仓（默认脚本所在源包根）")
    h.add_argument("--host-root", help="外部宿主仓路径（默认顶层 --root / cwd）")
    h.add_argument("--host-ref", help="宿主仓基准 ref/sha（默认取注册表 host_ref，否则 HEAD）")
    h.add_argument("--out", help="输出目录（默认 <host_root>/.atlas/runs/eval-host）")
    h.add_argument("--timeout", type=int, default=300, help="每步/case 超时秒数")
    h.add_argument("--retries", type=int, default=1,
                   help="pass→fail 时 candidate 侧复跑确认次数（默认 1 = 不复跑）")
    h.add_argument("--worktree-root", dest="worktree_root", help="worktree 根目录（默认系统临时目录）")
    h.add_argument("--keep-worktrees", dest="keep_worktrees", action="store_true",
                   help="保留 worktree 现场（调试）")
    h.add_argument("--no-skill", dest="no_skill", action="store_true",
                   help="显式跳过 skill 装配（默认启用以验证 skills/ 改动）")
    h.add_argument("--no-wiring", dest="no_wiring", action="store_true",
                   help="显式跳过接线装配（默认启用以验证 agent-pointer.md 改动）")
    h.add_argument("--allow-noop", dest="allow_noop", action="store_true",
                   help="允许装配摘要一致的同态重放")
    h.set_defaults(func=cmd_host)

    g = sub.add_parser("gate",
                       help="判回归：pass→fail / 锚缺失 / 新增即红 / gate_green 下降")
    g.add_argument("--ledger", required=True, help="atlas eval run 产出的 ledger.json")
    g.add_argument("--out", help="判定结果 JSON 输出路径（相对 ledger.root 解析）")
    g.set_defaults(func=cmd_gate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
