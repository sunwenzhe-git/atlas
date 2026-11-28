"""RFC-20261125-01 P4 receipt counterexamples, including M250.

Removing the reconstructed write-tree comparison must turn the tree-mismatch
test red. The real four-stage proof is stored at
.atlas/runs/mutation-proof/M250.txt.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.governance_schema import canonical_digest, validate_receipt
from _support.semantic_contracts import semantic_digests
from _support.workflow_receipt import ReceiptError, build_receipt, receipt_mode, verify_receipt as _verify_receipt
from validators.validate_receipt import main as validate_main

RECEIPT_REL = ".atlas/runs/workflow-receipt.json"
PATCH_REL = ".atlas/runs/workflow-receipt/staged.patch"
REVIEW_REL = "product/reviews/2026-11-25-impl-review-01/review.json"


def verify_receipt(*args, **kwargs):
    kwargs.setdefault("replay_validators", False)
    return _verify_receipt(*args, **kwargs)


def write(root: Path, rel: str, data: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def fixture(root: Path) -> str:
    write(root, "src/app.txt", "base\n")
    write(root, "README.md", "unchanged base file\n")
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "user.email", "receipt@example.test")
    git(root, "config", "user.name", "Receipt Test")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    return git(root, "rev-parse", "HEAD")


def contracts(root: Path, base: str | None = None) -> dict[str, str]:
    commit = base or "0" * 40
    values = {
        "expected": {"schema_version": 1, "clauses": [{"clause_id": "R-07", "contracts": []}]},
        "observed": {"schema_version": 1, "base": {"commit": commit, "digest": "0" * 64},
                     "head": {"commit": commit, "digest": "0" * 64}, "adapter_version": "fixture",
                     "facts": [], "sources": [], "changed_paths": [], "coverage": {"parsed": 0, "unverified_fields": [], "parse_errors": []}},
        "graph": {"schema_version": 1, "expected_digest": "0" * 64,
                  "observed_digest": "0" * 64, "edges": []},
    }
    for name, value in values.items():
        write(root, f"contracts/{name}.json", json.dumps(value))
    return {name: canonical_digest(value) for name, value in values.items()}


def review(root: Path) -> None:
    from _support.workflow_receipt import _staged_scope_digest
    staged = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACDMR").splitlines()
    write(root, REVIEW_REL, json.dumps({"status": "PASS", "ok": True, "unit": "01",
                                       "review_scope": {"sha256": _staged_scope_digest(root, staged)}}))


def make_receipt(root: Path, base: str, *, seed_contracts: bool = True, stage_topology: bool = True,
                 reset_base: bool = True, **overrides):
    if reset_base:
        git(root, "reset", "--mixed", base)
    if seed_contracts:
        digests = contracts(root, base)
    else:
        digests = overrides.get("semantic_digests") or semantic_digests(root)
    write(root, "src/app.txt", "staged text\n")
    write(root, "assets/blob.bin", b"\x00\xffbinary\x00payload\n")
    git(root, "add", "contracts", "src/app.txt", "assets/blob.bin")
    if (root / "compose.yaml").is_file():
        git(root, "add", "compose.yaml")
    if stage_topology and (root / ".adapter-out/topology.json").is_file():
        git(root, "add", ".adapter-out/topology.json")
    review(root)
    kwargs = {
        "root": root, "unit": "01", "task_id": "01", "requirement_id": "REQ-07",
        "clause_ids": ["R-07"], "base": base,
        "incident_ids": ["INC-20261125-001"], "resolves_incidents": [],
        "doc_ids": ["DOC-guide"], "topology_refs": [], "topology_required": False,
        "migration_required": False, "classification_required": False,
        "semantic_digests": digests,
        "validators": [
            {"module": "semantic", "verdict": "PASS", "rc": 0, "digest": digests["graph"]},
            {"module": "docs", "verdict": "WARN", "rc": 0, "digest": "1" * 64},
        ],
        "in_scope_modules": ["semantic", "docs"],
        "module_modes": {"semantic": "enforce", "docs": "enforce"},
        "review_path": REVIEW_REL, "review_origin": "workflow", "force": False,
        "workflow_version": "0.4.0-beta.8",
    }
    kwargs.update(overrides)
    return build_receipt(**kwargs)


def load(root: Path) -> dict:
    return json.loads((root / RECEIPT_REL).read_text(encoding="utf-8"))


def save(root: Path, value: dict) -> None:
    write(root, RECEIPT_REL, json.dumps(value))


def test_positive_receipt_saves_binary_patch_hashes_tree_and_all_bindings(tmp_path):
    base = fixture(tmp_path)
    receipt = make_receipt(tmp_path, base)
    patch = (tmp_path / PATCH_REL).read_bytes()
    assert b"GIT binary patch" in patch and b"workflow-review-origin.json" in patch
    assert receipt["staged_patch"] == {"path": PATCH_REL, "sha256": hashlib.sha256(patch).hexdigest()}
    assert receipt["tree_hash"] != git(tmp_path, "write-tree")
    assert git(tmp_path, "ls-files", "--", ".atlas/runs/workflow-review-origin.json") == ""
    assert receipt["base"] == base and receipt["diff_range"]
    assert receipt["unit"] == "01" and receipt["task_id"] == "01"
    assert receipt["requirement_id"] == "REQ-07" and receipt["clause_ids"] == ["R-07"]
    assert receipt["incident_ids"] == ["INC-20261125-001"]
    assert receipt["doc_ids"] == ["DOC-guide"]
    assert receipt["semantic_expected_digest"] == canonical_digest(read_json(tmp_path / "contracts/expected.json"))
    assert receipt["semantic_observed_digest"] == canonical_digest(read_json(tmp_path / "contracts/observed.json"))
    assert receipt["semantic_graph_digest"] == canonical_digest(read_json(tmp_path / "contracts/graph.json"))
    assert receipt["module_modes"] == {"semantic": "enforce", "docs": "enforce"}
    assert receipt["generated_at"] and receipt["workflow_version"]
    assert validate_receipt(receipt) == []
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "PASS" and result["rc"] == 0, result
    from _support.governance_schema import load_schema, validate
    assert validate(result, load_schema("governance-common")) == []
    assert validate(verify_receipt(tmp_path, mode="off"), load_schema("governance-common")) == []


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_fresh_checkout_rebuilds_tree_with_temporary_index_and_preserves_real_index(tmp_path):
    base = fixture(tmp_path)
    receipt = make_receipt(tmp_path, base)
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(tmp_path), str(fresh)], check=True, timeout=30)
    write(fresh, RECEIPT_REL, json.dumps(receipt))
    shutil.copytree(tmp_path / ".atlas/runs/workflow-receipt", fresh / ".atlas/runs/workflow-receipt")
    before_index = hashlib.sha256((fresh / ".git/index").read_bytes()).hexdigest()
    before_worktree = (fresh / "src/app.txt").read_bytes()
    result = verify_receipt(fresh, mode="enforce")
    assert result["verdict"] == "PASS" and result["rc"] == 0, result
    assert hashlib.sha256((fresh / ".git/index").read_bytes()).hexdigest() == before_index
    assert (fresh / "src/app.txt").read_bytes() == before_worktree
    assert not list((fresh / ".git").glob("atlas-receipt-index-*"))


def test_typechange_to_symlink_invalidates_all_review_scopes(tmp_path):
    from _support.workflow_receipt import _review_summary, _tree_scope_digest
    from _support.workflow_finish import _scope_matches

    base = fixture(tmp_path)
    receipt = make_receipt(tmp_path, base)
    original_scope = receipt["review"]["scope_sha256"]
    git(tmp_path, "rm", "-q", "--cached", "src/app.txt")
    (tmp_path / "src/app.txt").unlink()
    try:
        (tmp_path / "src/app.txt").symlink_to("../README.md")
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("当前 Windows 用户没有创建符号链接的特权")
        raise
    git(tmp_path, "add", "src/app.txt")
    assert not _scope_matches(tmp_path, {"review_scope": {"sha256": original_scope}})[0]
    with pytest.raises(ReceiptError, match="暂存内容"):
        _review_summary(tmp_path, REVIEW_REL)
    assert _tree_scope_digest(tmp_path, base, git(tmp_path, "write-tree")) != original_scope


def test_replay_migration_index_excludes_receipt_only_origin(tmp_path, monkeypatch):
    import _support.workflow_receipt as receipt_module

    base = fixture(tmp_path)
    write(tmp_path, "src/app.txt", "staged\n")
    git(tmp_path, "add", "src/app.txt")
    tree = git(tmp_path, "write-tree")
    script = write(tmp_path, "replay_migration.py", """import json, subprocess, sys
tracked = subprocess.check_output(['git','ls-files','--','.atlas/runs/workflow-review-origin.json'], text=True)
print(json.dumps({'verdict':'UNVERIFIED' if tracked else 'PASS','rc':2 if tracked else 0,'findings':[]}))
sys.exit(2 if tracked else 0)
""")
    evidence = tmp_path / ".atlas/runs/workflow-receipt/validator-evidence/.adapter-out/migration/manifest.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n")
    receipt = {"validator_code_sha256": {}, "in_scope_modules": ["migration"],
               "validator_evidence": {".adapter-out/migration/manifest.json": hashlib.sha256(evidence.read_bytes()).hexdigest()},
               "module_modes": {"migration": "enforce"}, "base": base,
               "validators": [{"module": "migration", "verdict": "PASS", "rc": 0,
                               "digest": canonical_digest({"verdict": "PASS", "rc": 0, "findings": []})}]}
    monkeypatch.setattr(receipt_module, "_validator_code_hashes", lambda _scope: {})
    monkeypatch.setitem(receipt_module.VALIDATOR_FILES, "migration", str(script))
    assert receipt_module._replay_validators(tmp_path, receipt, tree) is None


def test_base_unreachable_and_patch_not_applicable_are_unverified_rc2(tmp_path):
    base = fixture(tmp_path)
    receipt = make_receipt(tmp_path, base)
    receipt["base"] = "f" * 40
    save(tmp_path, receipt)
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result
    receipt = make_receipt(tmp_path, base)
    write(tmp_path, PATCH_REL, b"this is not a git patch\n")
    receipt["staged_patch"]["sha256"] = hashlib.sha256((tmp_path / PATCH_REL).read_bytes()).hexdigest()
    save(tmp_path, receipt)
    from _support.workflow_receipt import ORIGIN_REL
    origin = json.loads((tmp_path / ORIGIN_REL).read_text())
    origin["patch_sha256"] = receipt["staged_patch"]["sha256"]
    write(tmp_path, ORIGIN_REL, json.dumps(origin))
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result


def test_tree_mismatch_and_patch_hash_mismatch_are_fail_rc1(tmp_path):
    base = fixture(tmp_path)
    receipt = make_receipt(tmp_path, base)
    receipt["tree_hash"] = "f" * 40
    save(tmp_path, receipt)
    from _support.workflow_receipt import ORIGIN_REL
    origin = json.loads((tmp_path / ORIGIN_REL).read_text())
    origin["tree_hash"] = receipt["tree_hash"]
    write(tmp_path, ORIGIN_REL, json.dumps(origin))
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result
    receipt = make_receipt(tmp_path, base)
    with (tmp_path / PATCH_REL).open("ab") as stream:
        stream.write(b"tampered\n")
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result


def test_scope_missing_required_module_and_result_sets_are_rejected(tmp_path):
    base = fixture(tmp_path)
    receipt = make_receipt(tmp_path, base)
    receipt["in_scope_modules"] = ["docs"]
    receipt["module_modes"] = {"docs": "enforce"}
    receipt["validators"] = [receipt["validators"][1]]
    save(tmp_path, receipt)
    errors = validate_receipt(receipt)
    assert any("semantic" in item for item in errors)
    assert verify_receipt(tmp_path, mode="enforce")["verdict"] == "FAIL"
    receipt = make_receipt(tmp_path, base)
    receipt["module_modes"] = {"semantic": "enforce"}
    save(tmp_path, receipt)
    assert validate_receipt(receipt)
    receipt = make_receipt(tmp_path, base)
    receipt["validators"][0]["verdict"] = "UNVERIFIED"
    receipt["validators"][0]["rc"] = 2
    save(tmp_path, receipt)
    assert validate_receipt(receipt)
    assert verify_receipt(tmp_path, mode="enforce")["verdict"] == "FAIL"


def test_old_receipt_and_forged_review_are_blocked(tmp_path):
    base = fixture(tmp_path)
    receipt = make_receipt(tmp_path, base)
    receipt["schema_version"] = 0
    save(tmp_path, receipt)
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result
    receipt = make_receipt(tmp_path, base)
    write(tmp_path, REVIEW_REL, json.dumps({"status": "FAIL", "ok": False}))
    git(tmp_path, "add", REVIEW_REL)
    save(tmp_path, receipt)
    result = verify_receipt(tmp_path, mode="enforce", check_current_tree=True)
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result


def test_direct_review_and_force_cannot_mint_or_verify_receipt(tmp_path):
    base = fixture(tmp_path)
    with pytest.raises(ReceiptError, match="workflow"):
        make_receipt(tmp_path, base, review_origin="direct")
    with pytest.raises(ReceiptError, match="force"):
        make_receipt(tmp_path, base, force=True)
    make_receipt(tmp_path, base)
    assert verify_receipt(tmp_path, mode="enforce", review_origin="direct")["verdict"] == "FAIL"
    assert verify_receipt(tmp_path, mode="enforce", force=True)["verdict"] == "FAIL"


def test_quoted_receipt_mode_is_enforce_and_invalid_mode_fails_closed(tmp_path):
    base = fixture(tmp_path)
    (tmp_path / ".atlas").mkdir(exist_ok=True)
    (tmp_path / ".atlas/config.yaml").write_text('receipt_mode: "enforce"\n', encoding="utf-8")
    assert receipt_mode(tmp_path) == "enforce"
    (tmp_path / ".atlas/config.yaml").write_text("receipt_mode: enforced\n", encoding="utf-8")
    with pytest.raises(ReceiptError, match="配置非法"):
        receipt_mode(tmp_path)


def test_partial_staging_does_not_weaken_review_scope(tmp_path):
    base = fixture(tmp_path)
    make_receipt(tmp_path, base)
    write(tmp_path, "src/app.txt", "unstaged replacement\n")
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "PASS"
    assert verify_receipt(tmp_path, mode="enforce", check_current_tree=True)["verdict"] == "PASS"


def test_finish_scope_uses_index_for_partial_staging_and_deletion(tmp_path):
    from _support.workflow_finish import _scope_matches, staged_files
    from _support.workflow_receipt import _staged_scope_digest
    fixture(tmp_path)
    write(tmp_path, "src/app.txt", "staged B\n")
    git(tmp_path, "add", "src/app.txt")
    scope = {"sha256": _staged_scope_digest(tmp_path, staged_files(tmp_path))}
    write(tmp_path, "src/app.txt", "unstaged C\n")
    assert _scope_matches(tmp_path, scope)[0]
    git(tmp_path, "rm", "-fq", "src/app.txt")
    scope = {"sha256": _staged_scope_digest(tmp_path, staged_files(tmp_path))}
    assert _scope_matches(tmp_path, scope)[0]


def test_missing_workflow_origin_in_rebuilt_tree_blocks_handwritten_pass(tmp_path, monkeypatch):
    base = fixture(tmp_path)
    make_receipt(tmp_path, base)
    import _support.workflow_receipt as receipt_module
    original = receipt_module._tree_bytes

    def without_origin(root, tree, rel):
        if rel == receipt_module.ORIGIN_REL:
            return None
        return original(root, tree, rel)

    monkeypatch.setattr(receipt_module, "_tree_bytes", without_origin)
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("来源标记" in item["message"] for item in result["findings"])


def test_current_tree_and_old_task_receipt_are_blocked_at_finish_boundary(tmp_path):
    base = fixture(tmp_path)
    make_receipt(tmp_path, base)
    write(tmp_path, "src/app.txt", "changed after receipt\n")
    git(tmp_path, "add", "src/app.txt")
    result = verify_receipt(tmp_path, mode="enforce", check_current_tree=True)
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert verify_receipt(tmp_path, mode="enforce", expected_unit="02")["verdict"] == "FAIL"


def test_working_tree_semantic_tamper_does_not_rewrite_receipt_but_current_tree_blocks(tmp_path):
    base = fixture(tmp_path)
    make_receipt(tmp_path, base)
    write(tmp_path, "contracts/graph.json", json.dumps({"changed": True}))
    git(tmp_path, "add", "contracts/graph.json")
    assert verify_receipt(tmp_path, mode="enforce")["verdict"] == "PASS"
    result = verify_receipt(tmp_path, mode="enforce", check_current_tree=True)
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result


def test_classification_receipt_requires_enforce_decision_and_replays_evidence(tmp_path):
    from _support.classification_contract import build_classification_corpora
    from scripts.atlas_calibrate import calibrate

    if sys.platform == "win32":
        pytest.skip(
            "Windows checkout 会转换测量数据的文本行尾；校准摘要按逐字节绑定，"
            "当前平台无法复现 POSIX 的生成/重放字节一致前提"
        )

    def prediction_file(path, split, samples):
        rows = []
        for sample in samples:
            expected = sample["expected"]
            if expected == "abstain":
                top1, top2, score, score2 = "initial", "change", 0.50, 0.40
            else:
                top1, top2, score, score2 = expected, ("change" if expected != "change" else "initial"), 0.99, 0.01
            rows.append({"id": sample["id"], "scorer_version": "fixture-scorer@1", "candidates": [
                {"type": top1, "score": score, "evidence": ["fixture-top1"]},
                {"type": top2, "score": score2, "evidence": ["fixture-top2"]},
            ]})
        path.write_text(json.dumps({"split": split, "scorer_version": "fixture-scorer@1", "samples": rows}))
        return path

    base = fixture(tmp_path)
    corpora = build_classification_corpora()
    calibration = prediction_file(tmp_path / "calibration.json", "calibration", corpora["calibration"])
    heldout = prediction_file(tmp_path / "heldout.json", "held-out", corpora["held-out"])
    assert calibrate(tmp_path, calibration, heldout, owner="owner", decision="shadow")["rc"] == 0
    validators = [
        {"module": "semantic", "verdict": "PASS", "rc": 0, "digest": "1" * 64},
        {"module": "docs", "verdict": "PASS", "rc": 0, "digest": "2" * 64},
        {"module": "classification", "verdict": "PASS", "rc": 0, "digest": "3" * 64},
    ]
    options = dict(classification_required=True, validators=validators,
                   in_scope_modules=["semantic", "docs", "classification"],
                   module_modes={"semantic": "enforce", "docs": "enforce", "classification": "enforce"},
                   classification_result={"schema_version": 1, "module": "classification", "mode": "enforce",
                                          "input_digest": "a" * 64, "related": [], "decision": "explicit",
                                          "type": "bug", "verdict": "PASS", "rc": 0},
                   classification_input_digest="a" * 64)
    with pytest.raises(ReceiptError, match="分类结果"):
        make_receipt(tmp_path, base, **{**options, "classification_result": {"decision": "abstain"}})
    with pytest.raises(ReceiptError, match="input_digest"):
        make_receipt(tmp_path, base, **{**options, "classification_input_digest": "b" * 64})
    invalid_auto = {"schema_version": 1, "module": "classification", "mode": "enforce",
                    "input_digest": "a" * 64, "related": [], "decision": "auto", "type": "bug",
                    "top1": "bug", "top2": "change", "score": 0, "top2_score": 1, "margin": -1,
                    "scorer_version": "fixture-scorer@1", "evidence": [], "verdict": "PASS", "rc": 0}
    with pytest.raises(ReceiptError, match="分数"):
        make_receipt(tmp_path, base, **{**options, "classification_result": invalid_auto})
    make_receipt(tmp_path, base, **options)
    blocked = verify_receipt(tmp_path, mode="enforce")
    assert blocked["verdict"] == "UNVERIFIED" and blocked["rc"] == 2, blocked
    assert calibrate(tmp_path, calibration, heldout, owner="owner", decision="enforce", mode="enforce")["rc"] == 0
    receipt = make_receipt(tmp_path, base, **options)
    checked = verify_receipt(tmp_path, mode="enforce")
    assert checked["verdict"] == "PASS", json.dumps(checked, ensure_ascii=False)
    from _support.workflow_receipt import ORIGIN_REL
    with pytest.raises(ReceiptError, match="schema/scope"):
        make_receipt(tmp_path, base, **{**options, "validators": []})
    assert git(tmp_path, "ls-files", "--", ORIGIN_REL) == ""
    assert verify_receipt(tmp_path, mode="enforce")["verdict"] == "PASS"
    receipt = load(tmp_path)
    receipt["validator_code_sha256"]["classification"] = "0" * 64
    save(tmp_path, receipt)
    tampered = _verify_receipt(tmp_path, mode="enforce")
    assert tampered["verdict"] == "FAIL" and tampered["rc"] == 1, tampered
    receipt = make_receipt(tmp_path, base, **options)
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(tmp_path), str(fresh)], check=True, timeout=30)
    write(fresh, RECEIPT_REL, json.dumps(receipt))
    shutil.copytree(tmp_path / ".atlas/runs/workflow-receipt", fresh / ".atlas/runs/workflow-receipt")
    result = verify_receipt(fresh, mode="enforce")
    assert result["verdict"] == "PASS" and result["rc"] == 0, json.dumps(result, ensure_ascii=False)


def test_fresh_receipt_replays_in_scope_topology_validator(tmp_path):
    from _support.runtime_topology import check_topology, refresh_topology
    base = fixture(tmp_path)
    write(tmp_path, "compose.yaml", "services:\n  api:\n    image: demo/api:1\n")
    refreshed = refresh_topology(tmp_path, project="shop", environment="dev", cluster="local",
                                 release="r1", scan_globs=["compose.yaml"])
    assert refreshed["verdict"] == "PASS"
    checked = check_topology(tmp_path, mode="enforce")
    git(tmp_path, "add", "compose.yaml")
    if sys.platform == "win32":
        pytest.skip(
            "Windows checkout 行尾转换导致 compose.yaml 的逐字节 hash 与真实工作区不同；"
            "receipt 重放要求同一字节，平台无法满足"
        )
    receipt = make_receipt(tmp_path, base, clause_ids=[], incident_ids=[], doc_ids=[],
                           topology_required=True, validators=[{
                               "module": "topology", "verdict": checked["verdict"],
                               "rc": checked["rc"], "digest": canonical_digest(checked)}],
                           in_scope_modules=["topology"], module_modes={"topology": "enforce"})
    result = _verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "PASS", json.dumps(result, ensure_ascii=False)
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(tmp_path), str(fresh)], check=True, timeout=30)
    write(fresh, RECEIPT_REL, json.dumps(receipt))
    shutil.copytree(tmp_path / ".atlas/runs/workflow-receipt", fresh / ".atlas/runs/workflow-receipt")
    result = _verify_receipt(fresh, mode="enforce")
    assert result["verdict"] == "PASS", result
    evidence = fresh / ".atlas/runs/workflow-receipt/validator-evidence/.adapter-out/topology.json"
    evidence.write_text("{}")
    result = _verify_receipt(fresh, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result
    receipt["validator_evidence"][".adapter-out/topology.json"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    save(fresh, receipt)
    result = _verify_receipt(fresh, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result
    assert any("与重建 tree 冲突" in item["message"] for item in result["findings"])


def test_receipt_rejects_historical_head_semantic_store(tmp_path):
    base = fixture(tmp_path)
    contracts(tmp_path)
    observed = json.loads((tmp_path / "contracts/observed.json").read_text())
    observed["head"]["commit"] = "1" * 40
    (tmp_path / "contracts/observed.json").write_text(json.dumps(observed))
    make_receipt(tmp_path, base, seed_contracts=False,
                 semantic_digests={name: canonical_digest(json.loads((tmp_path / f"contracts/{name}.json").read_text()))
                                   for name in ("expected", "observed", "graph")})
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result
    assert any("base/head" in item["message"] for item in result["findings"])


def test_receipt_rejects_semantic_base_older_than_receipt_base(tmp_path):
    base = fixture(tmp_path)
    contracts(tmp_path)
    observed = json.loads((tmp_path / "contracts/observed.json").read_text())
    observed["base"]["commit"] = base
    observed["head"]["commit"] = base
    (tmp_path / "contracts/observed.json").write_text(json.dumps(observed))
    git(tmp_path, "commit", "--allow-empty", "-qm", "new base")
    newer = git(tmp_path, "rev-parse", "HEAD")
    make_receipt(tmp_path, newer, seed_contracts=False,
                 semantic_digests={name: canonical_digest(json.loads((tmp_path / f"contracts/{name}.json").read_text()))
                                   for name in ("expected", "observed", "graph")})
    result = verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result
    assert any("base/head" in item["message"] for item in result["findings"])


def test_fresh_evidence_cannot_resurrect_staged_deletion(tmp_path):
    from _support.runtime_topology import check_topology, refresh_topology
    fixture(tmp_path)
    write(tmp_path, "compose.yaml", "services:\n  api:\n    image: demo/api:1\n")
    refresh_topology(tmp_path, project="shop", environment="dev", cluster="local",
                     release="r1", scan_globs=["compose.yaml"])
    git(tmp_path, "add", "compose.yaml", ".adapter-out/topology.json")
    git(tmp_path, "commit", "-qm", "topology base")
    base = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "rm", "--cached", "-q", ".adapter-out/topology.json"], cwd=tmp_path, check=True)
    checked = check_topology(tmp_path, mode="enforce")
    make_receipt(tmp_path, base, reset_base=False, stage_topology=False,
                 clause_ids=[], incident_ids=[], doc_ids=[], topology_required=True,
                 validators=[{"module": "topology", "verdict": checked["verdict"],
                              "rc": checked["rc"], "digest": canonical_digest(checked)}],
                 in_scope_modules=["topology"], module_modes={"topology": "enforce"})
    result = _verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result
    assert any("已暂存删除" in item["message"] for item in result["findings"])


def test_fresh_topology_replay_matches_out_of_scope_dynamic_warning(tmp_path):
    from _support.runtime_topology import check_topology, refresh_topology
    fixture(tmp_path)
    write(tmp_path, "compose.yaml", "services:\n  api:\n    image: '${IMAGE}'\n")
    refresh_topology(tmp_path, project="shop", environment="dev", cluster="local", release="r1",
                     scan_globs=["compose.yaml"], owner="platform", due="2099-12-31")
    git(tmp_path, "add", "compose.yaml", ".adapter-out/topology.json")
    git(tmp_path, "commit", "-qm", "dynamic topology base")
    base = git(tmp_path, "rev-parse", "HEAD")
    checked = check_topology(tmp_path, mode="enforce")
    assert checked["verdict"] == "UNVERIFIED"
    scoped = {**checked, "verdict": "WARN", "cause": None, "rc": 0,
              "findings": [{"cause": "observation", "message": "动态拓扑字段不在本任务暂存面"}]}
    if sys.platform == "win32":
        pytest.skip(
            "Windows checkout 行尾转换导致 compose.yaml 的逐字节 hash 与真实工作区不同；"
            "receipt 重放要求同一字节，平台无法满足"
        )
    make_receipt(tmp_path, base, clause_ids=[], incident_ids=[], doc_ids=[], topology_required=True,
                 validators=[{"module": "topology", "verdict": "WARN", "rc": 0,
                              "digest": canonical_digest(scoped)}],
                 in_scope_modules=["topology"], module_modes={"topology": "enforce"})
    result = _verify_receipt(tmp_path, mode="enforce")
    assert result["verdict"] == "PASS", result


def test_schema_required_types_and_module_mode_enum(tmp_path):
    base = fixture(tmp_path)
    receipt = make_receipt(tmp_path, base)
    assert validate_receipt({k: v for k, v in receipt.items() if k != "tree_hash"})
    assert validate_receipt({**receipt, "topology_required": "false"})
    assert validate_receipt({**receipt, "module_modes": {"semantic": "shadow", "docs": "enforce"}})
    assert validate_receipt({**receipt, "validators": []})


def test_cli_returns_real_rc_and_off_is_unverified(tmp_path):
    base = fixture(tmp_path)
    make_receipt(tmp_path, base)
    result = subprocess.run([sys.executable, str(PKG_ROOT / "scripts/verify_receipt.py"),
                             "--root", str(tmp_path), "--mode", "enforce", "--json"],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["verdict"] == "UNVERIFIED"
    assert validate_main(["--root", str(tmp_path), "--mode", "off", "--json"]) == 2
