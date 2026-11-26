#!/usr/bin/env python3
"""RFC-20261125-01 §11/§15 calibration CLI and atomic ledger writer.

Thresholds are selected exclusively from calibration predictions. The frozen
held-out corpus is evaluated afterwards and cannot influence the selected pair.
No natural-language classifier or business text is implemented or persisted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.classification_contract import (  # noqa: E402
    CLASS_LABELS,
    ClassificationError,
    build_classification_corpora,
    calibration_generation,
    load_frozen_heldout,
    load_prediction_file,
    select_thresholds,
    evaluate_classification,
)
from _support.governance_io import atomic_write_bytes, atomic_write_json, load_json, safe_path  # noqa: E402
from _support.governance_schema import canonical_bytes  # noqa: E402

CALIBRATION_REL = ".atlas/runs/governance-calibration.json"
CALIBRATION_PREDICTIONS_REL = ".atlas/runs/governance-calibration-predictions.json"
HELDOUT_PREDICTIONS_REL = ".atlas/runs/governance-heldout-predictions.json"
CALIBRATION_GENERATIONS_REL = ".atlas/runs/governance-calibration/generations"


def _verify_pointer(root: Path, pointer: dict) -> tuple[dict, Path]:
    if not isinstance(pointer, dict):
        raise ValueError("calibration pointer 必须为对象")
    generation = pointer.get("generation")
    if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{64}", generation) \
            or pointer.get("path") != f"{CALIBRATION_GENERATIONS_REL}/{generation}":
        raise ValueError("calibration pointer generation/path 非法")
    directory = safe_path(root, pointer["path"])
    files = pointer.get("files")
    if not isinstance(files, dict) or set(files) != {
            "ledger.json", "calibration-predictions.json", "heldout-predictions.json"}:
        raise ValueError("calibration pointer files 清单非法")
    if not directory.is_dir() or directory.is_symlink():
        raise FileNotFoundError("calibration generation 目录缺失")
    entries = list(directory.iterdir())
    if {entry.name for entry in entries} != set(files) \
            or any(not entry.is_file() or entry.is_symlink() for entry in entries):
        raise ValueError("calibration generation 目录不完整")
    for name, expected in files.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"calibration generation hash 不符：{name}")
    snapshot = load_json(directory / "ledger.json")
    if calibration_generation(snapshot, (directory / "calibration-predictions.json").read_bytes(),
                              (directory / "heldout-predictions.json").read_bytes()) != generation:
        raise ValueError("calibration generation 与内容不符")
    core = {key: value for key, value in pointer.items()
            if key not in {"generation", "path", "files", "previous_generation", "previous_pointer"}}
    if snapshot != core:
        raise ValueError("calibration pointer 与 generation ledger 不一致")
    return snapshot, directory


def rollback_calibration(root: str | Path, mode: str = "shadow") -> dict:
    if mode == "off":
        return {"schema_version": 1, "module": "classification", "mode": mode,
                "verdict": "UNVERIFIED", "cause": None, "rc": 2, "decision": "shadow",
                "findings": [{"cause": "observation", "message": "calibration off，不能回滚"}]}
    root = Path(root).absolute()
    path = safe_path(root, CALIBRATION_REL)
    if not path.is_file() or path.is_symlink():
        raise ValueError("calibration pointer 缺失或不是普通文件")
    current = load_json(path)
    if not isinstance(current, dict):
        return {"schema_version": 1, "module": "classification", "mode": mode,
                "verdict": "UNVERIFIED", "cause": "calibration_unverified", "rc": 2,
                "decision": "shadow", "findings": [{"cause": "calibration_unverified",
                                                     "message": "calibration pointer 必须为对象"}]}
    previous = current.get("previous_pointer")
    if not isinstance(previous, dict) or previous.get("generation") != current.get("previous_generation"):
        raise ValueError("没有可回滚的 calibration 上一代")
    _snapshot, directory = _verify_pointer(root, previous)
    atomic_write_bytes(safe_path(root, CALIBRATION_PREDICTIONS_REL),
                       (directory / "calibration-predictions.json").read_bytes())
    atomic_write_bytes(safe_path(root, HELDOUT_PREDICTIONS_REL),
                       (directory / "heldout-predictions.json").read_bytes())
    atomic_write_json(path, previous)
    return {"schema_version": 1, "module": "classification", "mode": mode,
            "verdict": "WARN", "rc": 0, "cause": None, "decision": previous.get("decision", "shadow"),
            "generation": previous["generation"], "ledger_path": CALIBRATION_REL,
            "findings": [{"cause": "observation", "message": "calibration pointer 已回切上一代"}]}


def calibrate(root: str | Path, calibration_path: str | Path, heldout_path: str | Path, *,
              owner: str, decision: str = "shadow", mode: str = "shadow") -> dict:
    """Select on calibration, evaluate held-out, then atomically publish a ledger."""
    root = Path(root).absolute()
    safe_path(root, ".")
    if not isinstance(owner, str) or not owner.strip():
        raise ClassificationError("owner 不能为空")
    if decision not in ("shadow", "enforce"):
        raise ClassificationError("decision 必须为 shadow/enforce")
    if mode == "off":
        return {"schema_version": 1, "module": "classification", "mode": mode,
                "verdict": "UNVERIFIED", "cause": None, "rc": 2, "decision": "shadow",
                "eligible_for_enforce": False, "reasons": ["calibration off"]}
    corpora = build_classification_corpora()
    calibration_predictions, calibration_source = load_prediction_file(calibration_path, "calibration")
    heldout_predictions, heldout_source = load_prediction_file(heldout_path, "held-out")
    if calibration_source["scorer_version"] != heldout_source["scorer_version"]:
        raise ClassificationError("calibration/held-out scorer_version 必须一致")
    selected = select_thresholds(corpora["calibration"], calibration_predictions)
    thresholds = selected["thresholds"]
    heldout_metrics = evaluate_classification(corpora["held-out"], heldout_predictions,
                                              thresholds=thresholds)
    frozen = load_frozen_heldout()
    eligible = selected["feasible"] and heldout_metrics["passed"]
    final_decision = decision if eligible and mode == "enforce" else "shadow"
    reasons = []
    if not selected["feasible"]:
        reasons.append("calibration_no_feasible_threshold")
    reasons.extend(heldout_metrics["reasons"])
    samples = {
        "calibration": {label: sum(item["expected"] == label for item in corpora["calibration"])
                        for label in CLASS_LABELS},
        "heldout": heldout_metrics["samples_per_class"],
    }
    ledger = {
        "schema_version": 1, "module": "classification",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "owner": owner.strip(), "decision": final_decision,
        "decision_reason": "heldout_gates_passed" if eligible else "; ".join(reasons),
        "eligible_for_enforce": eligible,
        "heldout": {
            "spec_path": frozen["spec_path"], "spec_sha256": frozen["spec_sha256"],
            "corpus_fingerprint": frozen["corpus_fingerprint"], "tuning_allowed": False,
            "evaluation_only": True,
        },
        "samples": samples,
        "thresholds": thresholds,
        "threshold_selection": {
            "split": "calibration", "feasible": selected["feasible"],
            "calibration_fingerprint": calibration_source["fingerprint"],
            "calibration_predictions_path": CALIBRATION_PREDICTIONS_REL,
            "calibration_predictions_sha256": hashlib.sha256(Path(calibration_path).read_bytes()).hexdigest(),
            "heldout_prediction_fingerprint": heldout_source["fingerprint"],
            "heldout_predictions_path": HELDOUT_PREDICTIONS_REL,
            "heldout_predictions_sha256": hashlib.sha256(Path(heldout_path).read_bytes()).hexdigest(),
            "scorer_version": calibration_source["scorer_version"],
        },
        "metrics": {"calibration": selected, "heldout": heldout_metrics},
    }
    pointer_path = safe_path(root, CALIBRATION_REL)
    prior_pointer = None
    if pointer_path.exists() or pointer_path.is_symlink():
        if not pointer_path.is_file() or pointer_path.is_symlink():
            raise ValueError("calibration pointer 缺失或不是普通文件")
        prior_pointer = load_json(pointer_path)
        _verify_pointer(root, prior_pointer)
    calibration_raw = Path(calibration_path).read_bytes()
    heldout_raw = Path(heldout_path).read_bytes()
    payload = {
        "ledger.json": canonical_bytes(ledger) + b"\n",
        "calibration-predictions.json": calibration_raw,
        "heldout-predictions.json": heldout_raw,
    }
    generation = calibration_generation(ledger, calibration_raw, heldout_raw)
    generations = safe_path(root, CALIBRATION_GENERATIONS_REL)
    generations.mkdir(parents=True, exist_ok=True)
    final = safe_path(root, f"{CALIBRATION_GENERATIONS_REL}/{generation}")
    if final.exists():
        if not final.is_dir() or final.is_symlink():
            raise ValueError("校准代际路径不是普通目录")
        entries = list(final.iterdir())
        if {entry.name for entry in entries} != set(payload) \
                or any(not entry.is_file() or entry.is_symlink() for entry in entries) \
                or any((final / name).read_bytes() != raw for name, raw in payload.items()):
            raise ValueError("校准代际目录损坏，拒绝覆盖 last-known-good")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=f".{generation}.", dir=str(generations)))
        try:
            for name, raw in payload.items():
                atomic_write_bytes(temporary / name, raw)
            os.rename(temporary, final)
        finally:
            if temporary.exists():
                for child in temporary.iterdir():
                    child.unlink()
                temporary.rmdir()
    atomic_write_bytes(safe_path(root, CALIBRATION_PREDICTIONS_REL), calibration_raw)
    atomic_write_bytes(safe_path(root, HELDOUT_PREDICTIONS_REL), heldout_raw)
    if prior_pointer and prior_pointer.get("generation") == generation:
        previous_generation = prior_pointer.get("previous_generation")
        previous_pointer = prior_pointer.get("previous_pointer")
    else:
        previous_generation = prior_pointer.get("generation") if prior_pointer else None
        previous_pointer = prior_pointer
    pointer = {**ledger, "generation": generation, "path": f"{CALIBRATION_GENERATIONS_REL}/{generation}",
               "previous_generation": previous_generation, "previous_pointer": previous_pointer,
               "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(payload.items())}}
    atomic_write_json(safe_path(root, CALIBRATION_REL), pointer)
    return {
        "schema_version": 1, "module": "classification", "verdict": "PASS" if eligible else "UNVERIFIED",
        "rc": 0 if eligible else 2, "cause": None if eligible else "calibration_unverified",
        "eligible_for_enforce": eligible, "eligible": eligible, "decision": final_decision,
        "thresholds": thresholds, "reasons": reasons, "ledger_path": CALIBRATION_REL,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--calibration", help="external calibration predictions JSON")
    parser.add_argument("--held-out", help="external frozen held-out predictions JSON")
    parser.add_argument("--owner")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--decision", choices=("shadow", "enforce"), default="shadow")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default="shadow")
    args = parser.parse_args(argv)
    try:
        if args.rollback:
            if args.calibration or args.held_out or args.owner:
                parser.error("--rollback 不能与校准输入参数同用")
            result = rollback_calibration(args.root, mode=args.mode)
        else:
            if not args.calibration or not args.held_out or not args.owner:
                parser.error("校准模式必须提供 --calibration/--held-out/--owner")
            result = calibrate(args.root, args.calibration, args.held_out,
                               owner=args.owner, decision=args.decision, mode=args.mode)
    except (ClassificationError, OSError, ValueError, RuntimeError) as exc:
        result = {"schema_version": 1, "module": "classification", "verdict": "UNVERIFIED",
                  "rc": 2, "cause": "calibration_unverified", "decision": "shadow",
                  "eligible_for_enforce": False, "reasons": [str(exc)]}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] calibration rc={result['rc']} decision={result['decision']}")
        for reason in result.get("reasons", []):
            print(f"[{result['verdict']}] {reason}")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
