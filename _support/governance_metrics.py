"""RFC-20261125-01 §12 read-only governance metrics.

Inputs are check-events, the calibration ledger and an aggregate module-result
snapshot. Output contains counts, rates, percentiles and source digests only;
business text and finding bodies are never copied. Missing or zero-denominator
data is N/A, while malformed evidence is UNVERIFIED rather than a fabricated 0.

The default aggregate snapshot is .atlas/runs/governance-module-results.json:
clauses[{status}], finding_samples[{valid}], completed_units[{receipt_valid}],
repair_durations_ms[], incidents[{status}], docs[{status}] and
topology{total,covered}. Clause statuses are PASS/FAIL/STALE/UNVERIFIED;
incident statuses are detected/contained/resolved/closed; docs statuses are
PASS/STALE/UNVERIFIED. Percentiles use nearest rank. N/A clauses are not
included in the evaluated-clause denominator.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

from _support.governance_io import load_json, safe_path
from _support.governance_schema import canonical_digest

EVENTS_REL = ".atlas/runs/check-events.jsonl"
CALIBRATION_REL = ".atlas/runs/governance-calibration.json"
MODULE_RESULTS_REL = ".atlas/runs/governance-module-results.json"
_MISSING = object()


def percentile(values: list[int | float], percent: int | float) -> int | float | None:
    """Return the nearest-rank percentile; empty input has no numeric value."""
    if not values:
        return None
    if not 0 <= percent <= 100:
        raise ValueError("percent 必须在 [0,100]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def _rate(numerator: int, denominator: int, reason: str) -> dict:
    if denominator == 0:
        return {"value": None, "status": "N/A", "numerator": numerator,
                "denominator": denominator, "reason": reason}
    return {"value": numerator / denominator, "status": "PASS", "numerator": numerator,
            "denominator": denominator, "reason": None}


def _unverified(reason: str) -> dict:
    return {"value": None, "status": "UNVERIFIED", "numerator": None,
            "denominator": None, "reason": reason}


def _na_owner(value: dict, owner: str, due: str) -> dict:
    return {**value, "owner": owner, "due": due} if value.get("status") == "N/A" else value


def _source(path: Path, *, present: bool, status: str, reason: str | None = None,
            digest: str | None = None, **extra) -> dict:
    return {"path": str(path), "present": present, "status": status, "reason": reason,
            "sha256": digest, **extra}


def _file_source(root: Path, relative: str) -> tuple[dict, object]:
    path = safe_path(root, relative)
    if not path.exists():
        return _source(path, present=False, status="N/A", reason="source_missing"), _MISSING
    if not path.is_file() or path.is_symlink():
        return _source(path, present=True, status="UNVERIFIED", reason="source_not_regular_file"), _MISSING
    try:
        raw = path.read_bytes()
        value = load_json(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return _source(path, present=True, status="UNVERIFIED", reason=f"source_unreadable: {exc}",
                       digest=hashlib.sha256(raw).hexdigest() if 'raw' in locals() else None), _MISSING
    return _source(path, present=True, status="PASS", digest=hashlib.sha256(raw).hexdigest()), value


def _check_events(root: Path, supplied) -> tuple[dict, int]:
    errors = []
    events = []
    if supplied is not _MISSING:
        events = supplied if isinstance(supplied, list) else [supplied]
        digest = canonical_digest(events) if all(isinstance(item, dict) for item in events) else None
    else:
        path = safe_path(root, EVENTS_REL)
        if not path.exists():
            return _source(path, present=False, status="N/A", reason="source_missing", runs=0), 0
        if not path.is_file() or path.is_symlink():
            return _source(path, present=True, status="UNVERIFIED", reason="source_not_regular_file", runs=0), 0
        try:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            for line_number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("event must be object")
                    events.append(value)
                except (ValueError, json.JSONDecodeError) as exc:
                    errors.append(f"line {line_number}: {exc}")
        except (OSError, UnicodeError) as exc:
            return _source(path, present=True, status="UNVERIFIED", reason=f"source_unreadable: {exc}", runs=0), 0
        return _source(path, present=True, status="UNVERIFIED" if errors else "PASS",
                       reason="malformed_check_events" if errors else None,
                       digest=digest, runs=len(events), errors=len(errors)), len(events)
    for index, event in enumerate(events):
        if not isinstance(event, dict) or not isinstance(event.get("rows"), list):
            errors.append(f"event {index}: rows must be array")
        else:
            for row in event["rows"]:
                if not isinstance(row, dict) or not isinstance(row.get("name"), str) \
                        or not isinstance(row.get("status"), str):
                    errors.append(f"event {index}: invalid row")
    return _source(safe_path(root, EVENTS_REL), present=bool(events),
                   status="UNVERIFIED" if errors else "PASS" if events else "N/A",
                   reason="malformed_check_events" if errors else None if events else "source_empty",
                   digest=digest, runs=len(events), errors=len(errors)), len(events)


def _count_metric(rows: list, *, statuses: set[str], numerator: set[str], label: str) -> dict:
    if not isinstance(rows, list):
        return _unverified(f"{label} must be array")
    valid = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") not in statuses:
            return _unverified(f"{label} contains unknown status")
        valid.append(row["status"])
    if not valid:
        return _rate(0, 0, f"no_{label}_data")
    return _rate(sum(status in numerator for status in valid), len(valid), None)


def _module_metrics(payload) -> tuple[dict, dict]:
    if payload is _MISSING:
        payload = {"clauses": [], "finding_samples": [], "completed_units": [],
                   "repair_durations_ms": [], "incidents": [], "docs": [],
                   "topology": {"total": 0, "covered": 0}}
    if not isinstance(payload, dict):
        names = ("drift_rate", "unverified_coverage", "false_positive_rate", "bypass_rate",
                 "incident_unclosed_rate", "docs_stale_rate", "topology_coverage")
        metrics = {name: _unverified("module_results_not_object") for name in names}
        metrics["detection_fix_duration_ms"] = {
            "p50": None, "p95": None, "status": "UNVERIFIED", "samples": 0,
            "reason": "module_results_not_object"}
        return {}, metrics
    clauses = payload.get("clauses")
    clause_rows = clauses if isinstance(clauses, list) else []
    known_statuses = ("PASS", "FAIL", "STALE", "UNVERIFIED", "N/A", "WARN")
    clause_statuses = [row.get("status") for row in clause_rows
                       if isinstance(row, dict) and row.get("status") in known_statuses
                       and row.get("status") not in ("N/A", "WARN")]
    clause_errors = not isinstance(clauses, list) or len(clause_statuses) + sum(
        isinstance(row, dict) and row.get("status") in ("N/A", "WARN") for row in clause_rows) != len(clauses)
    evaluated = len(clause_statuses)
    drift = _unverified("clause_status_unknown") if clause_errors else _rate(
        sum(status in ("FAIL", "STALE") for status in clause_statuses), evaluated, "no_evaluated_clauses")
    unverified = _unverified("clause_status_unknown") if clause_errors else _rate(
        sum(status == "UNVERIFIED" for status in clause_statuses), evaluated, "no_evaluated_clauses")

    samples = payload.get("finding_samples")
    if not isinstance(samples, list):
        false_positive = _unverified("finding_samples_missing_or_invalid")
    elif any(not isinstance(row, dict) or not isinstance(row.get("valid"), bool) for row in samples):
        false_positive = _unverified("finding_sample_validity_unknown")
    else:
        false_positive = _rate(sum(not row["valid"] for row in samples), len(samples), "no_sampled_findings")

    units = payload.get("completed_units")
    if not isinstance(units, list):
        bypass = _unverified("completed_units_missing_or_invalid")
    elif any(not isinstance(row, dict) or not isinstance(row.get("receipt_valid"), bool) for row in units):
        bypass = _unverified("receipt_validity_unknown")
    else:
        bypass = _rate(sum(not row["receipt_valid"] for row in units), len(units), "no_completed_units")

    durations = payload.get("repair_durations_ms")
    if not isinstance(durations, list):
        detection_fix = {"p50": None, "p95": None, "status": "UNVERIFIED",
                         "samples": 0, "reason": "repair_durations_missing_or_invalid"}
    elif any(isinstance(value, bool) or not isinstance(value, (int, float))
             or not math.isfinite(value) or value < 0 for value in durations):
        detection_fix = {"p50": None, "p95": None, "status": "UNVERIFIED",
                         "samples": 0, "reason": "repair_duration_invalid"}
    else:
        detection_fix = {"p50": percentile(durations, 50), "p95": percentile(durations, 95),
                         "status": "PASS" if durations else "N/A", "samples": len(durations),
                         "reason": None if durations else "no_detection_fix_data"}

    incidents = _count_metric(payload.get("incidents"),
                              statuses={"detected", "contained", "resolved", "closed"},
                              numerator={"detected", "contained", "resolved"}, label="incidents")
    docs = _count_metric(payload.get("docs"), statuses={"PASS", "STALE", "UNVERIFIED"},
                         numerator={"STALE"}, label="docs")
    topology = payload.get("topology")
    if not isinstance(topology, dict):
        topology_coverage = _unverified("topology_coverage_missing_or_invalid")
    else:
        total, covered = topology.get("total"), topology.get("covered")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in (total, covered)) or covered > total:
            topology_coverage = _unverified("topology_counts_invalid")
        else:
            topology_coverage = _rate(covered, total, "no_topology_units")
    return {}, {
        "drift_rate": drift, "unverified_coverage": unverified,
        "false_positive_rate": false_positive, "bypass_rate": bypass,
        "detection_fix_duration_ms": detection_fix,
        "incident_unclosed_rate": incidents, "docs_stale_rate": docs,
        "topology_coverage": topology_coverage,
    }


def _calibration_metric(payload) -> dict:
    if payload is _MISSING:
        return {"status": "N/A", "decision": None, "reason": "calibration_missing"}
    if not isinstance(payload, dict):
        return {"status": "UNVERIFIED", "decision": None, "reason": "calibration_invalid"}
    metrics = payload.get("metrics", {})
    heldout = metrics.get("heldout", {}) if isinstance(metrics, dict) else {}
    passed = heldout.get("passed") is True if isinstance(heldout, dict) else False
    return {"status": "PASS" if passed else "UNVERIFIED", "decision": payload.get("decision"),
            "reason": None if passed else "calibration_gate_not_passed",
            "heldout_corpus_fingerprint": (payload.get("heldout") or {}).get("corpus_fingerprint")
            if isinstance(payload.get("heldout"), dict) else None}


def compute_metrics(root: str | Path, *, module_results=_MISSING,
                    check_events=_MISSING, calibration=_MISSING) -> dict:
    """Read source evidence and return formulas without writing any artifact."""
    root = Path(root).absolute()
    events_source, runs = _check_events(root, check_events)
    if module_results is _MISSING:
        module_source, modules = _file_source(root, MODULE_RESULTS_REL)
    else:
        module_source = _source(safe_path(root, MODULE_RESULTS_REL), present=module_results is not None,
                                status="PASS" if isinstance(module_results, dict) else "UNVERIFIED",
                                reason=None if isinstance(module_results, dict) else "module_results_invalid",
                                digest=canonical_digest(module_results))
        modules = module_results
    if calibration is _MISSING:
        calibration_source, calibration_value = _file_source(root, CALIBRATION_REL)
    else:
        calibration_source = _source(safe_path(root, CALIBRATION_REL), present=calibration is not None,
                                     status="PASS" if isinstance(calibration, dict) else "UNVERIFIED",
                                     reason=None if isinstance(calibration, dict) else "calibration_invalid",
                                     digest=canonical_digest(calibration))
        calibration_value = calibration
    _, metrics = _module_metrics(modules)
    owner = "Atlas"
    due = (date.today() + timedelta(days=365)).isoformat()
    metrics = {name: _na_owner(value, owner, due) for name, value in metrics.items()}
    calibration_metric = _na_owner(_calibration_metric(calibration_value), owner, due)
    sources = {"check_events": events_source, "calibration": calibration_source,
               "module_results": module_source}
    sources = {name: _na_owner(value, owner, due) for name, value in sources.items()}
    return {
        "schema_version": 1, "module": "metrics",
        "sources": sources,
        "check_events": {"runs": runs}, "metrics": metrics,
        "classification_calibration": calibration_metric,
    }
