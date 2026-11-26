"""RFC-20261125-01 §10 workflow receipt creation and independent verification.

A receipt is not a signature. Its staged binary patch is replayed from base in
a temporary GIT_INDEX_FILE and the reconstructed write-tree is compared with
the recorded tree. Review provenance (workflow versus direct review) and force
are trusted workflow inputs; this module cannot distinguish a forged but
schema-valid review report without that wiring context.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from _support.governance_io import GovernancePathError, atomic_write_bytes, atomic_write_json, load_json, safe_path
from _support.governance_schema import canonical_bytes, canonical_digest, validate_receipt
from _support.semantic_contracts import semantic_digests as load_semantic_digests
from _support.layout import load_layout
from _support.runtime_topology import scope_topology_result
from _support import review_scope_core

RECEIPT_REL = ".atlas/runs/workflow-receipt.json"
PATCH_REL = ".atlas/runs/workflow-receipt/staged.patch"
REVIEW_ARTIFACT_REL = ".atlas/runs/workflow-receipt/review.json"
ORIGIN_REL = ".atlas/runs/workflow-review-origin.json"
CLASSIFICATION_RESULT_REL = ".atlas/runs/workflow-classification.json"
CALIBRATION_SOURCES = {
    "ledger": ".atlas/runs/governance-calibration.json",
    "calibration_predictions": ".atlas/runs/governance-calibration-predictions.json",
    "heldout_predictions": ".atlas/runs/governance-heldout-predictions.json",
}
MODES = ("shadow", "enforce", "off")


class ReceiptError(ValueError):
    """A receipt cannot safely be created or verified."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_bytes(root: Path, *args: str, env: dict | None = None) -> bytes:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=60,
                                env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReceiptError(f"git 不可用：{exc}") from exc
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise ReceiptError(message or f"git {' '.join(args)} 失败")
    return result.stdout


def _git(root: Path, *args: str, env: dict | None = None) -> str:
    return _git_bytes(root, *args, env=env).decode("utf-8", "replace").strip()


def receipt_mode(root: str | Path) -> str:
    return _mode(None, Path(root).absolute())


def _mode(value: str | None, root: Path) -> str:
    selected = value or os.environ.get("ATLAS_RECEIPT_MODE")
    if not selected:
        config = root / ".atlas/config.yaml"
        if config.is_file() and not config.is_symlink():
            config_text = config.read_text(encoding="utf-8")
            match = re.search(r"^\s*receipt_mode\s*:\s*['\"]?(shadow|enforce|off)['\"]?\b",
                              config_text, re.M)
            if re.search(r"^\s*receipt_mode\s*:", config_text, re.M) and not match:
                raise ReceiptError("receipt_mode 配置非法")
            selected = match.group(1) if match else None
    selected = selected or "shadow"
    if selected not in MODES:
        raise ReceiptError("mode 必须为 shadow/enforce/off")
    return selected


def _finding(message: str, cause: str = "receipt_stale", **extra) -> dict:
    return {"cause": cause, "message": message, **extra}


def _result(verdict: str, rc: int, findings: list[dict], cause: str | None = None,
            mode: str = "enforce", **extra) -> dict:
    if mode == "off":
        verdict, rc, cause = "UNVERIFIED", 2, None
    elif mode == "shadow":
        rc = 0
    return {"schema_version": 1, "module": "receipt", "mode": mode,
            "verdict": verdict, "cause": cause, "rc": rc, "findings": findings, **extra}


def receipt_error_result(exc: Exception, mode: str | None = None) -> dict:
    selected = "off" if mode == "off" else "shadow" if mode == "shadow" else "enforce"
    cause = None if selected == "off" else "receipt_unverified"
    return _result("UNVERIFIED", 2, [_finding(f"{type(exc).__name__}: {exc}", "observation")],
                   cause, selected, path=RECEIPT_REL)


def _workflow_context(review_origin: str, force: bool) -> None:
    if review_origin != "workflow":
        raise ReceiptError("receipt 必须由 workflow review 接线生成，直跑 review 不构成完成凭据")
    if force:
        raise ReceiptError("--force 不能生成或替代有效 receipt")


def _staged_scope_digest(root: Path, paths: list[str]) -> str:
    rows = []
    for rel in sorted(set(paths)):
        result = subprocess.run(["git", "show", f":{rel}"], cwd=root, capture_output=True, timeout=60)
        if result.returncode == 0:
            if len(result.stdout) > review_scope_core.MAX_HASH_BYTES:
                raise ReceiptError(f"暂存文件过大，review_scope 无法逐字节复核：{rel}")
            digest, mode = _sha(result.stdout), review_scope_core.HASH_SHA256
        else:
            digest, mode = review_scope_core.HASH_ABSENT, review_scope_core.HASH_ABSENT
        rows.append(f"{rel}\0{digest}\0{mode}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _review_summary(root: Path, rel: str) -> dict:
    path = safe_path(root, rel)
    if not path.is_file() or path.is_symlink():
        raise ReceiptError(f"review 报告缺失或为符号链接：{rel}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"review 报告不可读取：{rel}: {exc}") from exc
    if not isinstance(value, dict) or value.get("status") != "PASS" or value.get("ok") is False:
        raise ReceiptError(f"review 报告未通过或伪造：{rel}")
    scope = value.get("review_scope")
    if not isinstance(scope, dict) or not scope.get("sha256"):
        raise ReceiptError("review 报告缺 review_scope，不能绑定暂存内容")
    staged = [path for path in _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACDMRT", "-z").split("\0")
              if path and not path.startswith("product/reviews/") and path != ORIGIN_REL]
    if scope.get("sha256") != _staged_scope_digest(root, staged):
        raise ReceiptError("review_scope 与当前暂存内容不符")
    return {"path": rel, "artifact_path": REVIEW_ARTIFACT_REL, "sha256": _sha(raw),
            "status": "PASS", "scope_sha256": scope["sha256"]}


def _calibration_payload(root: Path) -> tuple[dict, dict[str, bytes], dict[str, str]]:
    evidence, payload = {}, {}
    for key, source_rel in CALIBRATION_SOURCES.items():
        source = safe_path(root, source_rel)
        if not source.is_file() or source.is_symlink():
            raise ReceiptError(f"classification_required 缺校准证据：{source_rel}")
        raw = source.read_bytes()
        destination_rel = f".atlas/runs/workflow-receipt/calibration/{Path(source_rel).name}"
        evidence[key] = {"path": destination_rel, "sha256": _sha(raw)}
        payload[destination_rel] = raw
    ledger = load_json(safe_path(root, CALIBRATION_SOURCES["ledger"]))
    generation_files = {}
    if ledger.get("generation"):
        directory = safe_path(root, ledger["path"])
        for name, expected in ledger.get("files", {}).items():
            source = directory / name
            if not source.is_file() or source.is_symlink() or _sha(source.read_bytes()) != expected:
                raise ReceiptError(f"classification generation 证据不可复核：{name}")
            rel = source.relative_to(root).as_posix()
            destination = f".atlas/runs/workflow-receipt/calibration-generation/{rel}"
            payload[destination] = source.read_bytes()
            generation_files[rel] = expected
    return evidence, payload, generation_files


def create_workflow_origin(root: str | Path, unit: str, review_path: str) -> dict:
    root = Path(root).absolute()
    review = _review_summary(root, review_path)
    origin = {
        "schema_version": 1, "unit": unit, "review_path": review_path,
        "review_sha256": review["sha256"], "review_scope_sha256": review["scope_sha256"],
        "base": _git(root, "rev-parse", "HEAD"),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    atomic_write_json(safe_path(root, ORIGIN_REL), origin)
    return origin


def validate_workflow_origin(root: str | Path, unit: str, review_path: str) -> None:
    root = Path(root).absolute()
    review = _review_summary(root, review_path)
    path = safe_path(root, ORIGIN_REL)
    if not path.is_file() or path.is_symlink():
        raise ReceiptError("缺 workflow verify 来源标记；直跑 review 不构成完成凭据")
    origin = load_json(path)
    if not isinstance(origin, dict) or origin.get("schema_version") != 1 \
            or origin.get("unit") != unit or origin.get("review_path") != review_path \
            or origin.get("review_sha256") != review["sha256"] \
            or origin.get("review_scope_sha256") != review["scope_sha256"] \
            or origin.get("base") != _git(root, "rev-parse", "HEAD"):
        raise ReceiptError("workflow verify 来源标记与当前 review/staged/base 不符")


def _classification_result(root: Path, value: dict | None, expected_digest: str | None = None) -> dict:
    if value is None:
        path = safe_path(root, CLASSIFICATION_RESULT_REL)
        if not path.is_file() or path.is_symlink():
            raise ReceiptError("classification_required 缺本任务分类结果")
        value = load_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != 1 \
            or value.get("module") != "classification" or value.get("mode") != "enforce" \
            or value.get("verdict") != "PASS" or value.get("rc") != 0 \
            or value.get("decision") not in ("explicit", "auto") \
            or value.get("type") not in ("initial", "change", "bug") \
            or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("input_digest", ""))) \
            or not isinstance(value.get("related"), list):
        raise ReceiptError("classification_required 的分类结果缺失、abstain、off 或非 enforce")
    if expected_digest is not None and value.get("input_digest") != expected_digest:
        raise ReceiptError("classification_required 分类结果 input_digest 与本任务不符")
    if value["decision"] == "auto":
        score, top2_score, margin = value.get("score"), value.get("top2_score"), value.get("margin")
        if not value.get("scorer_version") or value.get("top1") != value["type"] or not value.get("top2") \
                or any(isinstance(item, bool) or not isinstance(item, (int, float))
                       or not math.isfinite(item) or not 0 <= item <= 1 for item in (score, top2_score, margin)) \
                or not math.isclose(margin, score - top2_score, rel_tol=1e-12, abs_tol=1e-12) \
                or not isinstance(value.get("evidence"), list) or not value["evidence"] \
                or any(not isinstance(item, str) or not item.strip() for item in value["evidence"]):
            raise ReceiptError("auto 分类结果缺 scorer/top1/top2/分数/证据或分数不自洽")
    return value


VALIDATOR_FILES = {
    "migration": "validators/validate_migration.py",
    "semantic": "validators/validate_contracts.py",
    "incident": "validators/validate_incident.py",
    "docs": "validators/validate_docs_governance.py",
    "topology": "validators/validate_runtime_topology.py",
    "classification": "validators/validate_calibration.py",
}


def _validator_code_hashes(scope: list[str]) -> dict[str, str]:
    package = Path(__file__).resolve().parents[1]
    closure = hashlib.sha256()
    files = sorted([*package.glob("_support/**/*.py"), *package.glob("adapters/**/*.py"),
                    *package.glob("validators/**/*.py"), *package.glob("shared/schemas/*.json")])
    for path in files:
        closure.update(path.relative_to(package).as_posix().encode())
        closure.update(b"\0")
        closure.update(path.read_bytes())
        closure.update(b"\0")
    digest = closure.hexdigest()
    return {module: digest for module in VALIDATOR_FILES if module in scope}


def _validator_evidence(root: Path, scope: list[str]) -> tuple[dict, dict[str, bytes]]:
    layout = load_layout(root)
    assets = layout.assets_root.relative_to(root).as_posix()
    rendered = layout.spec_dir.relative_to(root).as_posix() + "/global/runtime-topology.md" \
        if hasattr(layout, "spec_dir") else ".atlas/spec/structure/global/runtime-topology.md"
    roots = {
        "migration": [".adapter-out/migration"],
        "semantic": ["contracts"],
        "incident": [f"{assets}/incidents"],
        "docs": [f"{assets}/docs"],
        "topology": [".adapter-out/topology.json", ".adapter-out/topology", rendered],
    }
    manifest, payload = {}, {}
    for module in scope:
        for rel in roots.get(module, []):
            path = safe_path(root, rel)
            files = [path] if path.is_file() else sorted(path.rglob("*")) if path.is_dir() else []
            for source in files:
                if not source.is_file() or source.is_symlink():
                    continue
                source_rel = source.relative_to(root).as_posix()
                raw = source.read_bytes()
                destination = f".atlas/runs/workflow-receipt/validator-evidence/{source_rel}"
                manifest[source_rel] = _sha(raw)
                payload[destination] = raw
    return manifest, payload


def build_receipt(*, root: str | Path, unit: str, task_id: str, base: str,
                  semantic_digests: dict[str, str] | None = None,
                  validators: list[dict], in_scope_modules: list[str],
                  module_modes: dict[str, str], review_path: str,
                  requirement_id: str | None = None, clause_ids: list[str] | None = None,
                  incident_ids: list[str] | None = None, resolves_incidents: list[str] | None = None,
                  doc_ids: list[str] | None = None, topology_refs: list[str] | None = None,
                  topology_required: bool = False, migration_required: bool = False,
                  classification_required: bool = False, classification_result: dict | None = None,
                  classification_input_digest: str | None = None, diff_range: str | None = None,
                  review_origin: str = "workflow", force: bool = False,
                  workflow_version: str = "0.4.0-beta.8", generated_at: str | None = None) -> dict:
    """Bind current staged bytes/tree and atomically save patch plus receipt."""
    root = Path(root).absolute()
    safe_path(root, ".")
    _workflow_context(review_origin, force)
    full_base = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    if not re.fullmatch(r"[0-9a-f]{40}", full_base):
        raise ReceiptError("base 不是完整 commit hash")
    required_digests = {"expected", "observed", "graph"}
    if "semantic" not in in_scope_modules:
        digests = {name: "0" * 64 for name in required_digests}
    else:
        digests = semantic_digests or {}
    if "semantic" in in_scope_modules and set(digests) != required_digests:
        try:
            digests = load_semantic_digests(root)
        except (OSError, ValueError, GovernancePathError) as exc:
            raise ReceiptError(f"三份 semantic digest 不可计算：{exc}") from exc
    review = _review_summary(root, review_path)
    review_raw = safe_path(root, review_path).read_bytes()
    generated_at = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    origin = {
        "schema_version": 1, "unit": unit, "review_path": review_path,
        "review_sha256": review["sha256"],
        "review_scope_sha256": review["scope_sha256"],
        "base": full_base, "generated_at": generated_at,
    }
    calibration_evidence, calibration_payload, calibration_generation_files = {}, {}, {}
    validator_evidence, validator_payload = _validator_evidence(root, in_scope_modules)
    validator_code_sha256 = _validator_code_hashes(in_scope_modules)
    if classification_required:
        if not re.fullmatch(r"[0-9a-f]{64}", str(classification_input_digest or "")):
            raise ReceiptError("classification_required 缺本任务 input_digest")
        _classification_result(root, classification_result, classification_input_digest)
        calibration_evidence, calibration_payload, calibration_generation_files = _calibration_payload(root)
    origin_path = safe_path(root, ORIGIN_REL)
    prior_origin = origin_path.read_bytes() if origin_path.is_file() and not origin_path.is_symlink() else None
    artifact_paths = [REVIEW_ARTIFACT_REL, PATCH_REL, RECEIPT_REL,
                      *calibration_payload, *validator_payload]
    backups = {}
    for rel in artifact_paths:
        path = safe_path(root, rel)
        backups[rel] = path.read_bytes() if path.is_file() and not path.is_symlink() else None
    try:
        atomic_write_json(origin_path, origin)
        with tempfile.TemporaryDirectory(prefix="atlas-receipt-build-index-") as temporary:
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / "index"))
            current_tree = _git(root, "write-tree")
            _git(root, "read-tree", current_tree, env=env)
            origin_raw = canonical_bytes(origin) + b"\n"
            blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=root,
                                  input=origin_raw, capture_output=True, timeout=60)
            if blob.returncode != 0:
                raise ReceiptError("workflow origin blob 不可写入")
            _git(root, "update-index", "--add", "--cacheinfo",
                 f"100644,{blob.stdout.decode().strip()},{ORIGIN_REL}", env=env)
            patch = _git_bytes(root, "diff", "--cached", "--binary", env=env)
            tree = _git(root, "write-tree", env=env)
        receipt = {
            "schema_version": 1, "unit": unit, "task_id": task_id,
            "requirement_id": requirement_id, "clause_ids": clause_ids or [],
            "incident_ids": incident_ids or [], "resolves_incidents": resolves_incidents or [],
            "doc_ids": doc_ids or [], "topology_refs": topology_refs or [],
            "topology_required": topology_required, "migration_required": migration_required,
            "classification_required": classification_required, "base": full_base,
            "diff_range": diff_range or f"{full_base}..index",
            "staged_patch": {"path": PATCH_REL, "sha256": _sha(patch)}, "tree_hash": tree,
            "semantic_expected_digest": digests["expected"],
            "semantic_observed_digest": digests["observed"],
            "semantic_graph_digest": digests["graph"], "validators": validators,
            "validator_evidence": validator_evidence,
            "validator_code_sha256": validator_code_sha256,
            "review": review, "origin": origin,
            "in_scope_modules": in_scope_modules, "module_modes": module_modes,
            "generated_at": generated_at, "workflow_version": workflow_version,
        }
        if classification_required:
            receipt["classification_input_digest"] = classification_input_digest
            receipt["classification_result"] = classification_result
            receipt["calibration_evidence"] = calibration_evidence
            receipt["calibration_generation_files"] = calibration_generation_files
        errors = validate_receipt(receipt)
        if errors:
            raise ReceiptError("receipt schema/scope: " + "; ".join(errors))
        atomic_write_bytes(safe_path(root, REVIEW_ARTIFACT_REL), review_raw)
        for rel, raw in calibration_payload.items():
            atomic_write_bytes(safe_path(root, rel), raw)
        for rel, raw in validator_payload.items():
            atomic_write_bytes(safe_path(root, rel), raw)
        atomic_write_bytes(safe_path(root, PATCH_REL), patch)
        atomic_write_json(safe_path(root, RECEIPT_REL), receipt)
        return receipt
    except Exception:
        if prior_origin is None:
            origin_path.unlink(missing_ok=True)
        else:
            atomic_write_bytes(origin_path, prior_origin)
        for rel, raw in backups.items():
            path = safe_path(root, rel)
            if raw is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, raw)
        raise


def _reconstruct_tree(root: Path, base: str, patch_path: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="atlas-receipt-index-") as temporary:
        index = Path(temporary) / "index"
        env = dict(os.environ, GIT_INDEX_FILE=str(index))
        try:
            _git(root, "read-tree", base, env=env)
            _git(root, "apply", "--cached", "--binary", str(patch_path), env=env)
            return _git(root, "write-tree", env=env)
        except ReceiptError as exc:
            raise ReceiptError(f"base+patch 无法重建 staged tree：{exc}") from exc


def _tree_without_origin(root: Path, tree: str) -> str:
    with tempfile.TemporaryDirectory(prefix="atlas-receipt-current-index-") as temporary:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / "index"))
        _git(root, "read-tree", tree, env=env)
        _git(root, "update-index", "--force-remove", "--", ORIGIN_REL, env=env)
        return _git(root, "write-tree", env=env)


def _tree_bytes(root: Path, tree: str, rel: str) -> bytes | None:
    try:
        return _git_bytes(root, "show", f"{tree}:{rel}")
    except ReceiptError:
        return None


def _tree_scope_digest(root: Path, base: str, tree: str) -> str:
    paths = [path for path in _git(root, "diff", "--name-only", "--diff-filter=ACDMRT", "-z",
                                   base, tree).split("\0")
             if path and not path.startswith("product/reviews/") and path != ORIGIN_REL]
    rows = []
    for rel in sorted(set(paths)):
        data = _tree_bytes(root, tree, rel)
        if data is None:
            digest, mode = review_scope_core.HASH_ABSENT, review_scope_core.HASH_ABSENT
        else:
            if len(data) > review_scope_core.MAX_HASH_BYTES:
                raise ReceiptError(f"暂存文件过大，review_scope 无法逐字节复核：{rel}")
            digest, mode = _sha(data), review_scope_core.HASH_SHA256
        rows.append(f"{rel}\0{digest}\0{mode}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _verify_semantic_digests(root: Path, receipt: dict, tree: str) -> dict | None:
    if "semantic" not in receipt["in_scope_modules"]:
        return None
    actual, stores = {}, {}
    for name in ("expected", "observed", "graph"):
        raw = _tree_bytes(root, tree, f"contracts/{name}.json")
        if raw is None:
            return {"verdict": "UNVERIFIED", "rc": 2, "cause": "receipt_unverified",
                    "findings": [_finding(f"重建 tree 缺 semantic {name} 库", "observation")]}
        try:
            stores[name] = json.loads(raw.decode("utf-8"))
            actual[name] = canonical_digest(stores[name])
        except (UnicodeError, json.JSONDecodeError) as exc:
            return {"verdict": "FAIL", "rc": 1, "cause": "receipt_stale",
                    "findings": [_finding(f"重建 tree 的 semantic {name} 库不可读取：{exc}")]}
    observed = stores["observed"]
    if observed.get("base", {}).get("commit") != observed.get("head", {}).get("commit") \
            or observed.get("base", {}).get("commit") != receipt["base"]:
        return {"verdict": "FAIL", "rc": 1, "cause": "receipt_stale",
                "findings": [_finding("完成态 semantic base/head 必须等于 receipt base 并重投影 staged tree")]}
    expected = {"expected": receipt["semantic_expected_digest"],
                "observed": receipt["semantic_observed_digest"],
                "graph": receipt["semantic_graph_digest"]}
    if actual != expected:
        return {"verdict": "FAIL", "rc": 1, "cause": "receipt_stale",
                "findings": [_finding("receipt 三份 semantic digest 与重建 tree 不符")]}
    return None


def _verify_calibration_evidence(root: Path, receipt: dict) -> dict | None:
    if not receipt["classification_required"]:
        return None
    try:
        _classification_result(root, receipt.get("classification_result"),
                               receipt.get("classification_input_digest"))
        with tempfile.TemporaryDirectory(prefix="atlas-receipt-calibration-") as temporary:
            evidence_root = Path(temporary)
            for key, source_rel in CALIBRATION_SOURCES.items():
                bound = receipt["calibration_evidence"][key]
                path = safe_path(root, bound["path"])
                if not path.is_file() or path.is_symlink():
                    raise ReceiptError(f"校准证据缺失或为符号链接：{bound['path']}")
                raw = path.read_bytes()
                if _sha(raw) != bound["sha256"]:
                    raise ReceiptError(f"校准证据 sha256 不符：{bound['path']}")
                destination = safe_path(evidence_root, source_rel)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            for rel, expected in receipt["calibration_generation_files"].items():
                path = safe_path(root, f".atlas/runs/workflow-receipt/calibration-generation/{rel}")
                if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != expected:
                    raise ReceiptError(f"校准代际证据不可复核：{rel}")
                destination = safe_path(evidence_root, rel)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(path.read_bytes())
            ledger = load_json(safe_path(evidence_root, CALIBRATION_SOURCES["ledger"]))
            classified = receipt["classification_result"]
            if classified["decision"] == "auto":
                if classified.get("scorer_version") != ledger.get("threshold_selection", {}).get("scorer_version"):
                    raise ReceiptError("分类结果 scorer_version 与校准账本不符")
                thresholds = ledger.get("thresholds") or {}
                if classified.get("thresholds") != thresholds or classified["score"] < thresholds.get("top1_score", 1) \
                        or classified["margin"] < thresholds.get("margin", 1):
                    raise ReceiptError("分类结果阈值或分数未达校准门槛")
            validator = Path(__file__).resolve().parents[1] / "validators" / "validate_calibration.py"
            checked = subprocess.run([sys.executable, str(validator), "--root", str(evidence_root), "--json"],
                                     capture_output=True, text=True, timeout=60)
            calibrated = json.loads(checked.stdout)
    except (OSError, ValueError, GovernancePathError, subprocess.SubprocessError,
            UnicodeError, json.JSONDecodeError) as exc:
        return {"verdict": "UNVERIFIED", "rc": 2, "cause": "receipt_unverified",
                "findings": [_finding(f"classification_required 校准证据不可重放：{exc}", "observation")]}
    if checked.returncode != 0 or calibrated.get("decision") != "enforce":
        return {"verdict": "UNVERIFIED", "rc": 2, "cause": "receipt_unverified",
                "findings": [_finding("classification_required 校准未通过或未决策 enforce："
                                      + json.dumps(calibrated, ensure_ascii=False, sort_keys=True))]}
    return None


def _origin_matches(origin: object, receipt: dict) -> bool:
    return isinstance(origin, dict) and origin.get("schema_version") == 1 \
        and origin.get("unit") == receipt["unit"] \
        and origin.get("review_path") == receipt["review"]["path"] \
        and origin.get("review_sha256") == receipt["review"]["sha256"] \
        and origin.get("review_scope_sha256") == receipt["review"].get("scope_sha256") \
        and origin.get("base") == receipt["base"] \
        and origin.get("generated_at") == receipt["generated_at"]


def _replay_validators(root: Path, receipt: dict, tree: str) -> dict | None:
    if receipt["validator_code_sha256"] != _validator_code_hashes(receipt["in_scope_modules"]):
        return {"verdict": "FAIL", "rc": 1, "cause": "receipt_stale",
                "findings": [_finding("validator 代码哈希与 receipt 绑定不符")]}
    scope = set(receipt["in_scope_modules"]) & set(VALIDATOR_FILES) - {"classification"}
    if not scope:
        return None
    package = Path(__file__).resolve().parents[1]
    try:
        with tempfile.TemporaryDirectory(prefix="atlas-receipt-replay-") as temporary:
            worktree = Path(temporary) / "tree"
            worktree.mkdir()
            index = Path(temporary) / "index"
            env = dict(os.environ, GIT_INDEX_FILE=str(index))
            _git(root, "read-tree", tree, env=env)
            _git(root, "update-index", "--force-remove", "--", ORIGIN_REL, env=env)
            checked_out = subprocess.run(["git", "checkout-index", "--all", f"--prefix={worktree}/"],
                                         cwd=root, env=env, capture_output=True, text=True, timeout=120)
            if checked_out.returncode != 0:
                raise ReceiptError("重建 tree 不可物化：" + checked_out.stderr.strip())
            git_dir = Path(_git(root, "rev-parse", "--git-dir"))
            if not git_dir.is_absolute():
                git_dir = root / git_dir
            replay_env = dict(os.environ, GIT_DIR=str(git_dir.resolve()),
                              GIT_WORK_TREE=str(worktree), GIT_INDEX_FILE=str(index))
            base_paths = {item for item in _git_bytes(root, "ls-tree", "-r", "-z", "--name-only",
                                                     receipt["base"]).decode("utf-8", "surrogateescape").split("\0") if item}
            tree_paths = {item for item in _git_bytes(root, "ls-tree", "-r", "-z", "--name-only",
                                                     tree).decode("utf-8", "surrogateescape").split("\0") if item}
            layout = load_layout(root)
            assets = layout.assets_root.relative_to(root).as_posix()
            rendered = layout.spec_dir.relative_to(root).as_posix() + "/global/runtime-topology.md" \
                if hasattr(layout, "spec_dir") else ".atlas/spec/structure/global/runtime-topology.md"
            allowed_prefixes = (".adapter-out/migration/", "contracts/", f"{assets}/incidents/",
                                f"{assets}/docs/", ".adapter-out/topology", rendered)
            for rel, expected in receipt["validator_evidence"].items():
                if not rel.startswith(allowed_prefixes):
                    raise ReceiptError(f"validator evidence 路径不在模块白名单：{rel}")
                if rel in base_paths and rel not in tree_paths:
                    raise ReceiptError(f"validator evidence 不得回填已暂存删除路径：{rel}")
                source = safe_path(root, f".atlas/runs/workflow-receipt/validator-evidence/{rel}")
                if not source.is_file() or source.is_symlink() or _sha(source.read_bytes()) != expected:
                    raise ReceiptError(f"validator evidence 不可复核：{rel}")
                destination = safe_path(worktree, rel)
                if destination.exists():
                    if not destination.is_file() or destination.is_symlink() or destination.read_bytes() != source.read_bytes():
                        raise ReceiptError(f"validator evidence 与重建 tree 冲突：{rel}")
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
            recorded = {item["module"]: item for item in receipt["validators"]}
            assets = load_layout(root).assets_root.relative_to(root).as_posix()
            prefixes = {"migration": ".adapter-out/migration", "semantic": "contracts",
                        "incident": f"{assets}/incidents", "docs": f"{assets}/docs",
                        "topology": ".adapter-out/topology"}
            for module in sorted(scope):
                if not any(rel.startswith(prefixes[module]) for rel in receipt["validator_evidence"]):
                    raise ReceiptError(f"{module} 缺 fresh validator evidence")
                command = [sys.executable, str(package / VALIDATOR_FILES[module]),
                           "--root", str(worktree), "--json"]
                if module != "migration":
                    command += ["--mode", receipt["module_modes"][module]]
                if module == "docs":
                    for doc_id in receipt["doc_ids"]:
                        command += ["--doc-id", doc_id]
                if module == "incident":
                    results = []
                    for incident_id in receipt["resolves_incidents"]:
                        checked = subprocess.run(command + ["--closed", incident_id], cwd=worktree,
                                                 env=replay_env, capture_output=True, text=True, timeout=180)
                        results.append(json.loads(checked.stdout))
                    if canonical_digest(results) != recorded[module]["digest"]:
                        raise ReceiptError("incident fresh closed-validator 聚合摘要对拍失败")
                    continue
                checked = subprocess.run(command, cwd=worktree, env=replay_env,
                                         capture_output=True, text=True, timeout=180)
                result = json.loads(checked.stdout)
                if module == "topology" and result.get("verdict") == "UNVERIFIED" \
                        and result.get("cause") == "topology_unverified":
                    topology_data = load_json(safe_path(worktree, ".adapter-out/topology.json"))
                    staged = {item for item in _git(root, "diff", "--name-only", "-z",
                                                   receipt["base"], tree).split("\0") if item}
                    result = scope_topology_result(result, topology_data, staged)
                if canonical_digest(result) != recorded[module]["digest"]:
                    raise ReceiptError(f"{module} fresh validator 摘要对拍失败：{checked.stdout}{checked.stderr}")
    except (OSError, ValueError, GovernancePathError, subprocess.SubprocessError,
            UnicodeError, json.JSONDecodeError) as exc:
        return {"verdict": "UNVERIFIED", "rc": 2, "cause": "receipt_unverified",
                "findings": [_finding(f"fresh validator 重放失败：{exc}", "observation")]}
    return None


def verify_receipt(root: str | Path, *, mode: str | None = None,
                   receipt_path: str = RECEIPT_REL, check_current_tree: bool = False,
                   review_origin: str = "workflow", force: bool = False,
                   expected_unit: str | None = None, expected_task_id: str | None = None,
                   expected_validator_digests: dict[str, str] | None = None,
                   replay_validators: bool = True) -> dict:
    """Verify schema/scope, artifacts, review binding and base+patch tree replay."""
    root = Path(root).absolute()
    selected = _mode(mode, root)
    if selected == "off":
        return _result("UNVERIFIED", 2, [_finding("receipt 模块 off，in-scope 不可判定", "observation")],
                       None, selected, path=receipt_path)
    try:
        _workflow_context(review_origin, force)
    except ReceiptError as exc:
        return _result("FAIL", 1, [_finding(str(exc))], "receipt_stale", selected, path=receipt_path)
    try:
        path = safe_path(root, receipt_path)
        if not path.is_file() or path.is_symlink():
            raise ReceiptError(f"receipt 缺失或为符号链接：{receipt_path}")
        receipt = load_json(path)
    except (OSError, ValueError, GovernancePathError) as exc:
        return _result("UNVERIFIED", 2, [_finding(str(exc), "observation")], "receipt_unverified", selected,
                       path=receipt_path)
    if not isinstance(receipt, dict):
        return _result("FAIL", 1, [_finding("receipt 顶层必须为对象")], "receipt_stale", selected,
                       path=receipt_path)
    if receipt.get("schema_version") != 1:
        return _result("FAIL", 1, [_finding("旧 receipt/schema_version 不受支持")], "receipt_stale",
                       selected, path=receipt_path)
    errors = validate_receipt(receipt)
    if errors:
        return _result("FAIL", 1, [_finding("receipt schema/scope: " + "; ".join(errors))],
                       "receipt_stale", selected, path=receipt_path)
    if expected_unit is not None and receipt["unit"] != expected_unit:
        return _result("FAIL", 1, [_finding("receipt unit 与当前任务不符")], "receipt_stale", selected)
    if expected_task_id is not None and receipt["task_id"] != expected_task_id:
        return _result("FAIL", 1, [_finding("receipt task_id 与当前任务不符")], "receipt_stale", selected)
    if expected_validator_digests is not None:
        actual_digests = {item["module"]: item["digest"] for item in receipt["validators"]}
        if actual_digests != expected_validator_digests:
            return _result("FAIL", 1, [_finding("receipt validator 摘要与当前复核结果不符")], "receipt_stale", selected)
    calibration_failure = _verify_calibration_evidence(root, receipt)
    if calibration_failure:
        return _result(**calibration_failure, mode=selected, path=receipt_path)
    try:
        patch_path = safe_path(root, receipt["staged_patch"]["path"])
        if not patch_path.is_file() or patch_path.is_symlink():
            raise ReceiptError("staged patch 缺失或为符号链接")
        patch = patch_path.read_bytes()
    except (OSError, ValueError, GovernancePathError) as exc:
        return _result("UNVERIFIED", 2, [_finding(str(exc), "observation")], "receipt_unverified", selected,
                       path=receipt["staged_patch"]["path"])
    if _sha(patch) != receipt["staged_patch"]["sha256"]:
        return _result("FAIL", 1, [_finding("staged patch sha256 与 receipt 不符")],
                       "receipt_stale", selected, path=receipt["staged_patch"]["path"])
    try:
        _git(root, "cat-file", "-e", f"{receipt['base']}^{{commit}}")
    except ReceiptError as exc:
        return _result("UNVERIFIED", 2, [_finding(f"base 不可达：{exc}", "observation")], "receipt_unverified",
                       selected, path=receipt_path)
    try:
        rebuilt = _reconstruct_tree(root, receipt["base"], patch_path)
    except ReceiptError as exc:
        return _result("UNVERIFIED", 2, [_finding(str(exc), "observation")], "receipt_unverified", selected,
                       path=receipt["staged_patch"]["path"])
    if rebuilt != receipt["tree_hash"]:
        return _result("FAIL", 1, [_finding(f"write-tree 对拍失败：重建 {rebuilt}，receipt {receipt['tree_hash']}")],
                       "receipt_stale", selected, path=receipt_path)
    semantic_failure = _verify_semantic_digests(root, receipt, rebuilt)
    if semantic_failure:
        return _result(**semantic_failure, mode=selected, path=receipt_path)
    try:
        review_path = safe_path(root, receipt["review"]["artifact_path"])
        if not review_path.is_file() or review_path.is_symlink():
            raise ReceiptError("receipt review artifact 缺失或为符号链接")
        review_raw = review_path.read_bytes()
        review = json.loads(review_raw.decode("utf-8"))
        if not isinstance(review, dict) or review.get("status") != "PASS" or review.get("ok") is False \
                or not isinstance(review.get("review_scope"), dict) or not review["review_scope"].get("sha256"):
            raise ReceiptError("review 报告状态/内容与 receipt 不符")
        if _sha(review_raw) != receipt["review"]["sha256"]:
            raise ReceiptError("review 报告 sha256 与 receipt 不符")
        if review["review_scope"]["sha256"] != _tree_scope_digest(root, receipt["base"], rebuilt) \
                or review["review_scope"]["sha256"] != receipt["review"]["scope_sha256"]:
            raise ReceiptError("review_scope 与重建 staged tree 不符")
        origin_raw = _tree_bytes(root, rebuilt, ORIGIN_REL)
        if origin_raw is None:
            raise ReceiptError("重建 tree 缺 workflow review 来源标记")
        origin = json.loads(origin_raw.decode("utf-8"))
        if not _origin_matches(origin, receipt) or origin != receipt["origin"]:
            raise ReceiptError("重建 tree 的 workflow review 来源标记与 receipt 不符")
    except ReceiptError as exc:
        return _result("FAIL", 1, [_finding(str(exc))], "receipt_stale", selected,
                       path=receipt["review"]["path"])
    except (OSError, UnicodeError, json.JSONDecodeError, GovernancePathError) as exc:
        return _result("FAIL", 1, [_finding(f"review 报告不可复核：{exc}")], "receipt_stale",
                       selected, path=receipt["review"]["path"])
    if replay_validators:
        validator_failure = _replay_validators(root, receipt, rebuilt)
        if validator_failure:
            return _result(**validator_failure, mode=selected, path=receipt_path)
    if check_current_tree:
        try:
            current = _git(root, "write-tree")
            expected_current = _tree_without_origin(root, receipt["tree_hash"])
            origin_path = safe_path(root, ORIGIN_REL)
            if not origin_path.is_file() or origin_path.is_symlink() \
                    or load_json(origin_path) != receipt["origin"]:
                raise ReceiptError("当前 workflow origin 文件与 receipt 不符")
        except ReceiptError as exc:
            return _result("UNVERIFIED", 2, [_finding(f"当前 staged tree/origin 不可读取：{exc}", "observation")],
                           "receipt_unverified", selected)
        if current != expected_current:
            return _result("FAIL", 1, [_finding("当前 staged tree（排除 receipt origin）与 receipt 不符")],
                           "receipt_stale", selected)
    return _result("PASS", 0, [], None, selected, path=receipt_path,
                   metrics={"base": receipt["base"], "tree_hash": rebuilt,
                            "patch_sha256": receipt["staged_patch"]["sha256"]})
