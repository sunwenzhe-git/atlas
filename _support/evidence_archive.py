#!/usr/bin/env python3
"""atlas 共享内核 —— E2E 运行证据归档（evidence archive；RFC-20261104-01 S1）。

守一件事：把 `<e2e>/scripts/.atlas-run/` 的**证据面**（`trace.zip` /
`test-failed-*.png` / `*.webm`）复制到根级 `.atlas-evidence/<run-id>/`，并写
可独立消费的 `manifest.json`。**判分面**（`results.json` / `.last-run.json`）
永不复制。

三条硬约束：
- **只复制、不判定**：归档不参与任何 ok / verdict 判定；失败只落 WARN。
- **只增不删**：源文件与旧归档都不删；目录独占创建（同秒碰撞 `-2` 顺延）。
- **证据面 ⇄ 判分面分离**（`rings/e2e/reference.md` §7「运行目录二分」）。

纯标准库（`zipfile` 只被消费方测试使用，本模块不依赖第三方）。
`ATLAS_PYTHON`（缺省 `python3`）只需能跑标准库；teardown 在无 python3 时落
WARN、不翻红。

CLI（供 `globalTeardown` 调用）：
  python3 _support/evidence_archive.py --phase post-run --root <项目根>
  python3 _support/evidence_archive.py --phase fail --root <项目根> --run-dir <dir>
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

SCHEMA = "atlas-evidence-manifest-v1"
INDEX_SCHEMA = "atlas-evidence-index-v1"
EVIDENCE_DIRNAME = ".atlas-evidence"
RUN_DIRNAME = ".atlas-run"
PHASE_SUFFIX = {"pre-run": "pre", "fail": "fail", "post-run": "post-run"}


# ---------------------------------------------------------------- 基础工具


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-")
    return s[:48] or "run"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _display_path(path: Path, root: Path) -> str:
    """清单里的路径：根内用相对路径；仓库外（D194 证据根）用绝对路径。"""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- 布局发现


def _load_layout_module():
    """按文件路径加载兄弟 `layout.py`，兼容源包 / 装配 / 独立加载。"""
    key = "_atlas_evidence_archive_layout"
    if key in sys.modules:
        return sys.modules[key]
    import importlib.util

    path = Path(__file__).with_name("layout.py")
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 装配损坏
        raise RuntimeError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def discover_scripts_dir(root: Path) -> Path:
    """项目根 → `<e2e>/scripts`（优先 `atlas.config.yaml` / `stack-profile.yaml`）。"""
    try:
        return Path(_load_layout_module().load_layout(root).e2e_scripts_dir)
    except Exception:
        return Path(root) / "product" / "e2e" / "scripts"


# ---------------------------------------------------------------- 白名单


def is_evidence_file(name: str) -> bool:
    """证据面白名单（封闭集合；`results.json` / `.last-run.json` 一律不认）。"""
    if name == "trace.zip":
        return True
    if name.endswith(".webm"):
        return True
    return name.startswith("test-failed") and name.endswith(".png")


def collect_evidence(run_dir: Path) -> list[Path]:
    if not run_dir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(run_dir.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        if is_evidence_file(p.name):
            out.append(p)
    return out


# ---------------------------------------------------------------- trace 轴


def load_trace_policy(scripts_dir: Path) -> dict | None:
    """读生成期的逐用例策略清单；缺失 / 坏形状 ⇒ None（调用方落 WARN）。"""
    path = Path(scripts_dir) / ".atlas-trace-policy.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data:
        return None
    if not all(isinstance(v, dict) and isinstance(v.get("request_assertion"), bool)
               for v in data.values()):
        return None
    return data


def case_trace_enabled(policy: dict | None, case_id: str, request_trace: bool | None = None) -> bool | None:
    """逐用例 `trace_enabled`：策略未知 / 缺该案 ⇒ None（未知，不得当 N/A）。"""
    if not isinstance(policy, dict):
        return None
    entry = policy.get(case_id)
    if not isinstance(entry, dict) or not isinstance(entry.get("request_assertion"), bool):
        return None
    if request_trace is None:
        request_trace = os.environ.get("ATLAS_REQUEST_TRACE") == "1"
    return (not entry["request_assertion"]) or bool(request_trace)


def trace_axis(policy: dict | None, failed_cases: list[str], trace_present: bool,
               request_trace: bool | None = None) -> dict:
    """trace 轴与归档轴**分开判**：`trace: off` ⇒ 该案 N/A，但 PNG 归档仍 PASS。"""
    cases: dict[str, str] = {}
    warnings: list[str] = []
    if not failed_cases:
        return {"status": "N/A", "cases": {}, "warnings": []}
    for cid in sorted(set(failed_cases)):
        enabled = case_trace_enabled(policy, cid, request_trace)
        if enabled is None:
            cases[cid] = "unknown"
            warnings.append(f"{cid}: trace 策略未知（缺 .atlas-trace-policy.json 或该案条目）⇒ WARN")
        elif enabled and not trace_present:
            cases[cid] = "missing"
            warnings.append(f"{cid}: trace_enabled=True 但归档无 trace.zip ⇒ WARN")
        elif enabled:
            cases[cid] = "pass"
        else:
            cases[cid] = "na"
    if "unknown" in cases.values() or "missing" in cases.values():
        status = "WARN"
    elif cases and all(v == "na" for v in cases.values()):
        status = "N/A"
    else:
        status = "PASS"
    return {"status": status, "cases": cases, "warnings": warnings}


def failed_case_ids(run_dir: Path) -> list[str]:
    """从 Playwright JSON 报告读失败用例 ID（标题首词 = `E2E-*`）。"""
    rf = Path(run_dir) / "results.json"
    try:
        data = json.loads(rf.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    failed: list[str] = []

    def walk(suite: dict) -> None:
        for spec in suite.get("specs", []) or []:
            title = (spec.get("title") or "").strip()
            cid = title.split(None, 1)[0] if title else ""
            if not cid.startswith("E2E-"):
                continue
            statuses = [t.get("status") for t in spec.get("tests", []) or []]
            if "unexpected" in statuses:
                failed.append(cid)
        for sub in suite.get("suites", []) or []:
            walk(sub)

    for s in data.get("suites", []) or []:
        walk(s)
    return sorted(set(failed))


# ---------------------------------------------------------------- 索引 / 锁


@contextlib.contextmanager
def _index_lock(evidence: Path):
    evidence.mkdir(parents=True, exist_ok=True)
    lock = evidence / ".index.lock"
    fh = lock.open("a+")
    try:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):  # Windows / 只读 FS：退化为尽力而为
            pass
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        fh.close()


def _read_index(evidence: Path) -> dict:
    path = evidence / "index.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") == INDEX_SCHEMA and isinstance(data.get("files"), dict):
            return data
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    # 损坏 ⇒ 按各 manifest 重建（不静默丢去重信息）
    files: dict[str, str] = {}
    for manifest in sorted(evidence.glob("*/manifest.json")):
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            for item in m.get("files", []):
                sha = item.get("sha256")
                rel = item.get("path")
                if isinstance(sha, str) and isinstance(rel, str):
                    files.setdefault(sha, rel)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return {"schema": INDEX_SCHEMA, "files": files}


# ---------------------------------------------------------------- 归档主流程


def _new_run_dir(evidence: Path, base: str) -> tuple[Path, str | None]:
    """独占创建；碰撞 `-2` 顺延（绝不覆盖既有一份）。"""
    for i in range(1, 1000):
        name = base if i == 1 else f"{base}-{i}"
        candidate = evidence / name
        try:
            candidate.mkdir()
            return candidate, (None if i == 1 else name)
        except FileExistsError:
            continue
    raise RuntimeError(f"无法为 {base} 独占创建证据目录")


def archive_run_artifacts(
    root: Path,
    *,
    source: str,
    phase: str,
    scripts_hash: str | None = None,
    run_dir: Path | None = None,
    evidence_dir: Path | None = None,
    trace_policy: dict | None = None,
    failed_cases: list[str] | None = None,
    request_trace: bool | None = None,
) -> dict:
    """归档一次运行的证据面；**永不为判定负责**（失败只落 WARN）。"""
    root = Path(root)
    if phase not in PHASE_SUFFIX:
        raise ValueError(f"未知 phase {phase!r}")
    scripts_dir = discover_scripts_dir(root)
    run_dir = Path(run_dir) if run_dir is not None else scripts_dir / RUN_DIRNAME
    evidence = Path(evidence_dir) if evidence_dir is not None else root / EVIDENCE_DIRNAME

    result: dict = {"status": "N/A", "phase": phase, "source": source,
                    "dir": None, "files": [], "warnings": [], "partial": False,
                    "trace": {"status": "N/A", "cases": {}, "warnings": []}}

    # 符号链接越界（`shared/layout.md` §1.1「解析后仍须落在项目根内」同源）。
    # D194：调用方**显式**指定 `evidence_dir` 时，仓库外落点是合法设计（控制台 run 的证据根在
    # `<cache>/atlas-e2e/<slug>/evidence/`）⇒ 不做根内包含判定；缺省路径仍须落在根内。
    if evidence_dir is None and (evidence.is_symlink() or evidence.exists()):
        if not _is_within(evidence, root):
            result.update(status="WARN")
            result["warnings"].append(f"证据目录解析到项目根外：{evidence} ⇒ 拒绝写入")
            return result

    files = collect_evidence(run_dir)
    if phase == "fail" and failed_cases is None:
        failed_cases = failed_case_ids(run_dir)
    if not files:
        # 失败批但一件证据都没有：仍要如实判 trace 轴（策略未知/应有却缺 ⇒ WARN，
        # 不得因为「没东西可复制」就报 N/A 假绿）。
        if phase == "fail" and failed_cases:
            if trace_policy is None:
                trace_policy = load_trace_policy(scripts_dir)
            result["trace"] = trace_axis(trace_policy, failed_cases, False, request_trace)
            if result["trace"]["status"] == "WARN":
                result["status"] = "WARN"
                result["partial"] = True
                result["warnings"].extend(result["trace"]["warnings"])
        return result

    trace_present = any(p.name == "trace.zip" for p in files)
    if trace_policy is None:
        trace_policy = load_trace_policy(scripts_dir)
    result["trace"] = trace_axis(trace_policy, failed_cases or [], trace_present, request_trace)
    if "missing" in result["trace"]["cases"].values():
        result["partial"] = True  # trace 应存在而缺席 ⇒ 该次证据集不完整

    try:
        evidence.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.update(status="WARN")
        result["warnings"].append(f"证据目录不可写：{exc}")
        return result

    base = f"{_stamp()}-{_slug(source)}-{PHASE_SUFFIX[phase]}"
    try:
        with _index_lock(evidence):
            out_dir, collision = _new_run_dir(evidence, base)
            if collision:
                result["warnings"].append(f"同名目录已存在 ⇒ 顺延为 {collision}")
            index = _read_index(evidence)
            index_files: dict[str, str] = dict(index.get("files") or {})
            entries: list[dict] = []
            rel_dir = _display_path(out_dir, root)
            for src in files:
                rel_src = src.relative_to(run_dir)
                try:
                    sha = _sha256(src)
                except OSError as exc:
                    result.update(status="WARN", partial=True)
                    result["warnings"].append(f"{rel_src}: 读取失败 {exc}")
                    continue
                deduped = index_files.get(sha)
                if deduped and (evidence / deduped).is_file():
                    entries.append({"path": deduped, "sha256": sha, "bytes": src.stat().st_size,
                                    "deduped_from": deduped})
                    continue
                dest = out_dir / rel_src
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
                    if _sha256(dest) != sha:
                        dest.unlink(missing_ok=True)
                        raise OSError("复制后 sha256 不一致")
                except OSError as exc:
                    result.update(status="WARN", partial=True)
                    result["warnings"].append(f"{rel_src}: 复制失败 {exc}")
                    continue
                rel_dest = _display_path(dest, root)
                entries.append({"path": rel_dest, "sha256": sha, "bytes": src.stat().st_size})
                index_files[sha] = rel_dest

            manifest = {
                "schema": SCHEMA,
                "phase": phase,
                "source": source,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "run_id": out_dir.name,
                "partial": bool(result["partial"]),
                "scripts_hash": scripts_hash,
                "files": entries,
                "trace": result["trace"],
            }
            if phase == "fail":
                # 只记录「本批确实失败」；post-run 永不携带 verdict（teardown 不判定）。
                manifest["verdict"] = "fail"
            _atomic_json(out_dir / "manifest.json", manifest)
            index["files"] = index_files
            _atomic_json(evidence / "index.json", index)

        result["dir"] = rel_dir
        result["files"] = entries
        result["partial"] = bool(manifest["partial"])
        if result["trace"]["status"] == "WARN":
            result["status"] = "WARN"
            result["warnings"].extend(result["trace"]["warnings"])
        elif result["status"] == "N/A":
            result["status"] = "PASS"
    except Exception as exc:  # 归档器自身异常 ⇒ WARN，不吞掉运行判定
        result.update(status="WARN", partial=True)
        result["warnings"].append(f"归档异常：{type(exc).__name__}: {exc}")
    return result


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E2E 运行证据归档（只复制、不判定）")
    ap.add_argument("--root", required=True, help="项目根")
    ap.add_argument("--phase", required=True, choices=sorted(PHASE_SUFFIX), help="归档点")
    ap.add_argument("--source", default="global-teardown", help="来源标识")
    ap.add_argument("--scripts-hash", default=None, help="本批脚本指纹（可选）")
    ap.add_argument("--run-dir", default=None, help="覆盖 .atlas-run 位置")
    ap.add_argument("--evidence-dir", default=None, help="覆盖 .atlas-evidence 位置")
    ap.add_argument("--json", action="store_true", help="stdout 输出机读结果")
    args = ap.parse_args(argv)
    try:
        result = archive_run_artifacts(
            Path(args.root), source=args.source, phase=args.phase,
            scripts_hash=args.scripts_hash,
            run_dir=Path(args.run_dir) if args.run_dir else None,
            evidence_dir=Path(args.evidence_dir) if args.evidence_dir else None,
        )
    except Exception as exc:  # CLI **永不**非 0（teardown 吞异常的另一半）
        print(f"[atlas-evidence] WARN 归档异常：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    if result["status"] == "WARN":
        print(f"[atlas-evidence] WARN {'; '.join(result['warnings'])[:400]}", file=sys.stderr)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[atlas-evidence] {result['status']} {result['dir'] or '-'} ({len(result['files'])} 件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
