#!/usr/bin/env python3
"""全量消融编排（`atlas-ablate` 的唯一执行面）。

口径：一次触发 = 全量，不存在单机制模式。
范围：当前 `atlas_check.py` 的 `VALIDATORS` 全量 + 所有内联门行函数
（`check_*` 中调用 `rows.add` 的函数，调度器 `check_validators` 除外）。

载体：项目外隔离副本。全部摘除/还原只发生在副本里，目标工作树只读；
      不使用 `git apply`，因此不要求目标仓可写 git，也不产生 git 写操作。

协议：基线 N 轮（默认 3）→ 逐机制摘除 → 单轮观测 → 逐字节还原并复算 sha256。
输出：证据目录下的 catalog / baseline / runs / matrix / summary。
本工具只出观测矩阵，不宣称净收益、不建议删除、不自动修复。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
}
SEVERITY = {"FAIL": 4, "WARN": 3, "ok": 2, "SKIP": 1, "N/A": 0, "ABSENT": 0}


class FullAblationError(Exception):
    pass


class RestoreFailed(FullAblationError):
    pass


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ensure_outside(root: Path, out: Path) -> None:
    try:
        out.resolve().relative_to(root.resolve())
    except ValueError:
        return
    raise FullAblationError(f"证据目录不得在项目内：{out}")


def _check_rel(root: Path) -> str:
    for rel in (".atlas/scripts/atlas_check.py", "scripts/atlas_check.py"):
        if (root / rel).is_file():
            return rel
    raise FullAblationError(
        "当前目录不是 Atlas 项目根：找不到 .atlas/scripts/atlas_check.py 或 scripts/atlas_check.py")


def _validators_dir(root: Path, check_rel: str) -> Path:
    return (root / check_rel).parent.parent / "validators"


def _validators_tuple(tree: ast.Module) -> list[str]:
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(getattr(t, "id", None) == "VALIDATORS" for t in targets):
            value = node.value
            if isinstance(value, (ast.Tuple, ast.List)):
                return [e.value for e in value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    raise FullAblationError("atlas_check.py 无 VALIDATORS 元组：全量目录无法确定")


def _row_label(node: ast.AST) -> tuple[str, bool]:
    """返回（可匹配前缀, 是否动态）。动态标签按前缀匹配基线行名。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, False
    if isinstance(node, ast.JoinedStr):
        # 只取第一个格式化值之前的常量前缀；`f"布局提示（{code}）"` 得到
        # `布局提示（`，才能按前缀匹配基线的实际行名。
        prefix = ""
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                prefix += value.value
            else:
                break
        return prefix, True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, _ = _row_label(node.left)
        return left, True
    return "", True


def _row_calls(func: ast.AST) -> list[ast.Expr]:
    calls: list[ast.Expr] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            fn = node.value.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "add"
                    and isinstance(fn.value, ast.Name) and fn.value.id == "rows"
                    and node.value.args):
                calls.append(node)
    return calls


def _function_rows(func: ast.AST) -> tuple[list[str], bool]:
    labels: list[str] = []
    dynamic = False
    for call in _row_calls(func):
        label, dyn = _row_label(call.value.args[0])
        dynamic = dynamic or dyn
        if label and label not in labels:
            labels.append(label)
    return labels, dynamic


def build_catalog(root: Path) -> dict:
    check_rel = _check_rel(root)
    text = (root / check_rel).read_text(encoding="utf-8")
    tree = ast.parse(text)
    names = _validators_tuple(tree)
    vdir = _validators_dir(root, check_rel)
    entries: list[dict] = []
    for name in names:
        path = vdir / f"{name}.py"
        entries.append({
            "id": name,
            "kind": "validator",
            "target": str(path.relative_to(root)),
            "rows": [name],
            "dynamic": False,
            "present": path.is_file(),
        })
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("check_") or node.name == "check_validators":
            continue
        labels, dynamic = _function_rows(node)
        if not labels:
            continue
        entries.append({
            "id": node.name,
            "kind": "inline",
            "target": check_rel,
            "rows": labels,
            "dynamic": dynamic,
            "present": True,
        })
    if not entries:
        raise FullAblationError("全量目录为空：没有可消融的门机制")
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root.resolve()),
        "check_rel": check_rel,
        "validators_dir": str(vdir.relative_to(root)),
        "entries": entries,
        "counts": {
            "total": len(entries),
            "validators": sum(1 for e in entries if e["kind"] == "validator"),
            "inline": sum(1 for e in entries if e["kind"] == "inline"),
        },
    }


def _strip_rows(src: str, func_name: str) -> tuple[str, int]:
    """把指定函数内全部 `rows.add(...)` 语句替换为 `pass`，其余字节不动。"""
    tree = ast.parse(src)
    func = next((n for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == func_name), None)
    if func is None:
        raise FullAblationError(f"内联门函数不存在：{func_name}")
    calls = _row_calls(func)
    if not calls:
        raise FullAblationError(f"内联门函数没有 rows.add 可摘：{func_name}")
    lines = src.splitlines(keepends=True)
    starts: list[int] = []
    pos = 0
    for line in lines:
        starts.append(pos)
        pos += len(line.encode("utf-8"))
    data = src.encode("utf-8")
    for call in sorted(calls, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        start = starts[call.lineno - 1] + call.col_offset
        end = starts[call.end_lineno - 1] + call.end_col_offset
        data = data[:start] + b"pass  # ablated" + data[end:]
    out = data.decode("utf-8")
    ast.parse(out)
    return out, len(calls)


def _run_check(copy_root: Path, check_rel: str, fast: bool, timeout: int) -> dict:
    cmd = [sys.executable, str(copy_root / check_rel), "--root", ".", "--json"]
    if fast:
        cmd.append("--fast")
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=str(copy_root), capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"valid": False, "reason": f"timeout>{timeout}s", "rc": 124}
    except FileNotFoundError as exc:
        return {"valid": False, "reason": f"启动失败：{exc}", "rc": 127}
    elapsed = round((time.monotonic() - started) * 1000)
    if proc.returncode not in (0, 1):
        return {"valid": False, "rc": proc.returncode,
                "reason": f"rc={proc.returncode}；stderr={proc.stderr.strip()[-200:]}"}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"valid": False, "rc": proc.returncode,
                "reason": f"stdout 非 JSON：{exc}"}
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return {"valid": False, "rc": proc.returncode, "reason": "JSON 无 rows"}
    return {
        "valid": True,
        "rc": proc.returncode,
        "ok": bool(payload.get("ok")),
        "rows": rows,
        "elapsed_ms": elapsed,
        "finished": _now(),
    }


def _row_sum(rows: list[dict]) -> int:
    return sum(int(row.get("duration_ms") or 0) for row in rows)


def _signature(rows: list[dict]) -> dict[str, str]:
    return {str(row.get("name")): str(row.get("status")) for row in rows}


def _fast_baseline(copy_root: Path, check_rel: str, rounds: int, timeout: int) -> dict:
    runs: list[dict] = []
    for _ in range(rounds):
        run = _run_check(copy_root, check_rel, fast=True, timeout=timeout)
        if not run["valid"]:
            raise FullAblationError(f"基线测量无效：{run['reason']}")
        if not run["ok"]:
            failed = [f"{r.get('name')}={r.get('status')}" for r in run["rows"]
                      if r.get("status") == "FAIL"]
            raise FullAblationError(f"基线存在 FAIL，无法归因：{failed[:5]}")
        runs.append(run)
    signatures = [_signature(run["rows"]) for run in runs]
    if any(sig != signatures[0] for sig in signatures[1:]):
        raise FullAblationError("基线状态在轮次间不稳定，无法归因")
    sums = [_row_sum(run["rows"]) for run in runs]
    ordered = sorted(sums)
    median = ordered[len(ordered) // 2]
    return {
        "rounds": len(runs),
        "runs": runs,
        "rows": runs[-1]["rows"],
        "signature": signatures[0],
        "row_sums": sums,
        "median_row_sum": median,
        "noise": max(sums) - min(sums),
    }


def _match(name: str, candidates) -> list[str]:
    return [c for c in candidates if c == name or c.startswith(name)]


def _copy_root(root: Path, work: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in EXCLUDE_DIRS}

    shutil.copytree(root, work, dirs_exist_ok=True, ignore=ignore, symlinks=False)


def _save_backup(out: Path, entry_id: str, path: Path, data: bytes) -> None:
    dest = out / "backup" / entry_id / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _mutate(copy_root: Path, entry: dict) -> tuple[Path, bytes, int, str]:
    path = copy_root / entry["target"]
    if not path.is_file():
        raise FullAblationError(f"目标文件不存在：{entry['target']}")
    original = path.read_bytes()
    mode = stat.S_IMODE(path.stat().st_mode)
    if entry["kind"] == "validator":
        path.unlink()
        action = "删除校验器文件"
    else:
        text, removed = _strip_rows(original.decode("utf-8"), entry["id"])
        path.write_text(text, encoding="utf-8")
        os.chmod(path, mode)
        action = f"摘除 {removed} 处 rows.add"
    return path, original, mode, action


def _restore(path: Path, original: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(original)
    os.chmod(path, mode)
    if _sha_file(path) != _sha_bytes(original):
        raise RestoreFailed(f"还原后 sha256 不一致：{path}")


def _verdict(baseline_status: dict[str, str], after_status: dict[str, str],
             target_names: list[str]) -> tuple[str, list[str], list[str]]:
    changed = [name for name in baseline_status
               if name not in target_names
               and after_status.get(name, "ABSENT") != baseline_status[name]]
    target_changes = [f"{name}: {baseline_status[name]}→{after_status.get(name, 'ABSENT')}"
                      for name in target_names
                      if after_status.get(name, "ABSENT") != baseline_status[name]]
    if changed:
        return "溢出：其他行变化", target_changes, changed
    if not target_changes:
        return "无可观测差异", [], []
    worsened = any(SEVERITY.get(after_status.get(name, "ABSENT"), 0)
                   > SEVERITY.get(baseline_status[name], 0) for name in target_names)
    return ("目标行恶化" if worsened else "目标行摘除/降级"), target_changes, []


def run_full(root: Path, out: Path, rounds: int, timeout: int,
             slow_timeout: int, keep_workdir: bool) -> dict:
    catalog = build_catalog(root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    work = Path(tempfile.mkdtemp(prefix="atlas-ablate-full-"))
    copy_root = work / "root"
    copy_root.mkdir()
    print(f"全量消融：{catalog['counts']['total']} 个机制"
          f"（{catalog['counts']['validators']} 校验器 + {catalog['counts']['inline']} 内联行）")
    print(f"隔离副本：{copy_root}")
    _copy_root(root, copy_root)

    check_rel = catalog["check_rel"]
    baseline = _fast_baseline(copy_root, check_rel, rounds, timeout)
    fast_names = list(baseline["signature"])
    (out / "baseline-fast.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION,
                    "rounds": baseline["rounds"],
                    "row_sums": baseline["row_sums"],
                    "median_row_sum": baseline["median_row_sum"],
                    "noise": baseline["noise"],
                    "signature": baseline["signature"],
                    "rows": baseline["rows"]},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"基线：{baseline['rounds']} 轮稳定；行耗时Σ={baseline['row_sums']} ms；"
          f"噪声带={baseline['noise']} ms")

    slow_entries = []
    for entry in catalog["entries"]:
        if not any(_match(label, fast_names) for label in entry["rows"]):
            slow_entries.append(entry)

    slow_run = None
    if slow_entries:
        print(f"非 fast 面：{len(slow_entries)} 个机制，先跑一次完整门册观测…")
        slow_run = _run_check(copy_root, check_rel, fast=False, timeout=slow_timeout)
        if slow_run["valid"]:
            (out / "baseline-full.json").write_text(
                json.dumps({"schema_version": SCHEMA_VERSION, **slow_run},
                           ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            print(f"非 fast 观测无效：{slow_run['reason']}（矩阵记为未覆盖，不当作 ok）")

    slow_sig = _signature(slow_run["rows"]) if slow_run and slow_run["valid"] else {}
    entries_out: list[dict] = []
    runs_dir = out / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    for entry in catalog["entries"]:
        entry_id = entry["id"]
        fast_targets: list[str] = []
        for label in entry["rows"]:
            fast_targets.extend(_match(label, fast_names))
        fast_targets = list(dict.fromkeys(fast_targets))
        slow_targets: list[str] = []
        for label in entry["rows"]:
            slow_targets.extend(_match(label, slow_sig))
        slow_targets = list(dict.fromkeys(slow_targets))

        record: dict = {
            "id": entry_id,
            "kind": entry["kind"],
            "target": entry["target"],
            "rows": entry["rows"],
            "restore_ok": True,
        }
        if not entry.get("present", True):
            record.update(surface="none", verdict="未覆盖：校验器文件不存在")
            entries_out.append(record)
            continue
        if not fast_targets and not slow_targets:
            record.update(surface="none",
                          verdict="未覆盖：基线无该行（前置未满足或条件行未出现）")
            entries_out.append(record)
            continue

        surface = "fast" if fast_targets else "slow"
        targets = fast_targets or slow_targets
        base_sig = baseline["signature"] if surface == "fast" else slow_sig
        base_status = {name: base_sig[name] for name in targets}
        if surface == "slow":
            red = [f"{n}={base_status[n]}" for n in targets
                   if base_status[n] in ("FAIL", "SKIP", "N/A")]
            if red:
                record.update(surface="slow", baseline_status=base_status,
                              verdict=f"不可归因：非 fast 基线为 {', '.join(red)}")
                entries_out.append(record)
                continue

        try:
            path, original, mode, action = _mutate(copy_root, entry)
        except FullAblationError as exc:
            record.update(surface=surface, verdict=f"未执行：{exc}")
            entries_out.append(record)
            continue
        _save_backup(out, entry_id, path, original)
        try:
            run = _run_check(copy_root, check_rel, fast=(surface == "fast"),
                             timeout=timeout if surface == "fast" else slow_timeout)
            if not run["valid"]:
                record.update(surface=surface, action=action,
                              verdict=f"测量无效：{run['reason']}")
            else:
                after_sig = _signature(run["rows"])
                after_status = {name: after_sig.get(name, "ABSENT") for name in targets}
                verdict, target_changes, changed_other = _verdict(
                    base_sig, after_sig, targets)
                delta = _row_sum(run["rows"]) - baseline["median_row_sum"] \
                    if surface == "fast" else None
                attributable = bool(
                    surface == "fast" and baseline["rounds"] >= 2
                    and delta is not None and abs(delta) > baseline["noise"])
                record.update({
                    "surface": surface,
                    "action": action,
                    "baseline_status": base_status,
                    "after_status": after_status,
                    "target_changes": target_changes,
                    "changed_other": changed_other,
                    "delta_row_sum_ms": delta,
                    "attributable": attributable,
                    "verdict": verdict,
                    "rc": run["rc"],
                    "elapsed_ms": run["elapsed_ms"],
                })
                (runs_dir / f"{entry_id}.json").write_text(
                    json.dumps({"schema_version": SCHEMA_VERSION, **record,
                                "rows": run["rows"]},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finally:
            try:
                _restore(copy_root / entry["target"], original, mode)
            except RestoreFailed as exc:
                record["restore_ok"] = False
                record["verdict"] = f"还原失败：{exc}"
                entries_out.append(record)
                _write_matrix(out, catalog, baseline, entries_out, slow_run)
                raise
        entries_out.append(record)

    _write_matrix(out, catalog, baseline, entries_out, slow_run)
    if not keep_workdir:
        shutil.rmtree(work, ignore_errors=True)
    return {"catalog": catalog, "baseline": baseline, "entries": entries_out}


def _write_matrix(out: Path, catalog: dict, baseline: dict,
                  entries: list[dict], slow_run: dict | None) -> None:
    counts = {
        "total": catalog["counts"]["total"],
        "ablated": sum(1 for e in entries if e.get("action")),
        "uncovered": sum(1 for e in entries if e.get("surface") == "none"),
        "not_attributable": sum(1 for e in entries
                                if str(e.get("verdict", "")).startswith("不可归因")),
        "invalid": sum(1 for e in entries if str(e.get("verdict", "")).startswith("测量无效")),
        "restore_failed": sum(1 for e in entries if not e.get("restore_ok", True)),
    }
    matrix = {
        "schema_version": SCHEMA_VERSION,
        "generated": _now(),
        "counts": counts,
        "baseline_fast": {
            "row_sums": baseline["row_sums"],
            "median_row_sum": baseline["median_row_sum"],
            "noise": baseline["noise"],
        },
        "baseline_full": ({"valid": slow_run["valid"], "ok": slow_run.get("ok"),
                           "rows": slow_run.get("rows", [])}
                          if slow_run else None),
        "entries": entries,
    }
    (out / "matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 全量消融矩阵",
        "",
        f"- 生成时间：{matrix['generated']}",
        f"- 机制总数：{counts['total']}；已摘除：{counts['ablated']}；"
        f"未覆盖：{counts['uncovered']}；无效：{counts['invalid']}；"
        f"还原失败：{counts['restore_failed']}",
        f"- 基线：{baseline['rounds']} 轮，行耗时Σ={baseline['row_sums']} ms，"
        f"中位={baseline['median_row_sum']} ms，噪声带={baseline['noise']} ms",
        "",
        "| 机制 | 类型 | 面 | 基线 → 摘除后 | 其他行变化 | Δ行耗时 ms | 可归因 | 判定 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        base = entry.get("baseline_status") or {}
        after = entry.get("after_status") or {}
        if base and after:
            transition = ", ".join(f"{k}: {base[k]}→{after.get(k, 'ABSENT')}"
                                   for k in base)
        elif base:
            transition = "—（未摘除）"
        else:
            transition = "—"
        changed = "、".join(entry.get("changed_other") or []) or "—"
        delta = entry.get("delta_row_sum_ms")
        delta_text = "—" if delta is None else str(delta)
        attributable = "是" if entry.get("attributable") else "否"
        lines.append(
            f"| `{entry['id']}` | {entry['kind']} | {entry.get('surface', '—')} | "
            f"{transition} | {changed} | {delta_text} | {attributable} | "
            f"{entry.get('verdict', '—')} |")
    lines += [
        "",
        "> 只出观测矩阵：不宣称净收益、不建议删除。Δ 在噪声带内或仅单样本时标「不可归因」。",
        "> 未覆盖项必须带原因；`E2E`/factory 等非 fast 行若基线为 FAIL/SKIP/N/A，不当作 ok。",
    ]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _check_active(root: Path) -> None:
    for rel in (".atlas/scripts/ablation.py", "scripts/ablation.py"):
        script = root / rel
        if not script.is_file():
            continue
        proc = subprocess.run(
            [sys.executable, str(script), "status", "--root", str(root),
             "--quiet", "--exit-active"],
            capture_output=True, text=True)
        if proc.returncode == 10:
            raise FullAblationError(
                "当前 root 有 active 消融事务；先由人处理并 restore 后再跑全量")
        return


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default=None,
                    help="证据目录（必须在项目外；缺省 ~/.atlas-ablation/full/<root>/<时间>）")
    ap.add_argument("--rounds", type=int, default=3, help="基线轮数（默认 3）")
    ap.add_argument("--timeout", type=int, default=300, help="每次 fast 检查超时秒数")
    ap.add_argument("--slow-timeout", type=int, default=1800,
                    help="非 fast 完整门册单次超时秒数")
    ap.add_argument("--catalog-only", action="store_true", help="只生成全量目录，不执行")
    ap.add_argument("--keep-workdir", action="store_true", help="保留隔离副本（排障用）")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: root 不存在：{root}", file=sys.stderr)
        return 2
    try:
        if args.rounds < 1:
            raise FullAblationError("--rounds 必须 ≥1")
        _check_active(root)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        root_hash = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
        out = (Path(args.out).expanduser().resolve() if args.out
               else Path("~/.atlas-ablation/full").expanduser() / root_hash / stamp)
        _ensure_outside(root, out)
        if args.catalog_only:
            catalog = build_catalog(root)
            out.mkdir(parents=True, exist_ok=True)
            (out / "catalog.json").write_text(
                json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            print(json.dumps(catalog["counts"], ensure_ascii=False))
            print(f"catalog: {out / 'catalog.json'}")
            return 0
        result = run_full(root, out, args.rounds, args.timeout,
                          args.slow_timeout, args.keep_workdir)
        counts = {
            "total": len(result["entries"]),
            "ablated": sum(1 for e in result["entries"] if e.get("action")),
            "uncovered": sum(1 for e in result["entries"]
                             if e.get("surface") == "none"),
            "not_attributable": sum(1 for e in result["entries"]
                                    if str(e.get("verdict", "")).startswith("不可归因")),
            "restore_failed": sum(1 for e in result["entries"]
                                  if not e.get("restore_ok", True)),
        }
        print(json.dumps(counts, ensure_ascii=False))
        print(f"matrix: {out / 'matrix.json'}")
        print(f"summary: {out / 'summary.md'}")
        return 0
    except RestoreFailed as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except FullAblationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
