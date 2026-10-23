#!/usr/bin/env python3
"""`scripts/write_claim.py` 回归测试（M3，`RFC-20261022-01` 批 3）。

对账平面 = 写面仲裁（§5.1：one writer per file）。钉住：
  - 每 claim 一个原子文件（`O_CREAT|O_EXCL`）；并发 take 同一文件**只有一个赢**；
  - 同任务重复 take 幂等；他人持有 ⇒ 退出非零 + 指名在办任务；
  - release 即删、幂等；拒绝释放他人的 claim；
  - 残留检查 = glob `*.json`（同目录其它文件不是 claim，逐文件清理不误删）；
  - 损坏 claim 响亮（take 拒绝 + 残留可见）；16 位哈希碰撞响亮；
  - `atlas_check` 的 `写面残留` 行：有残留 ⇒ WARN，无 ⇒ ok。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "write_claim.py"
ATLAS_CHECK = PKG_ROOT / "scripts" / "atlas_check.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load(SCRIPT, "write_claim_under_test")


def _claim_files(root: Path) -> list[Path]:
    return sorted(MOD.claims_dir(root).glob("*.json"))


# ---------------------------------------------------------------- take


def test_take_creates_atomic_claim_file(tmp_path) -> None:
    code, msg = MOD.take(tmp_path, "product/e2e/e2e-index.md", "T1")
    assert code == 0 and "取得写权" in msg
    files = _claim_files(tmp_path)
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["file"] == "product/e2e/e2e-index.md"
    assert data["task"] == "T1" and isinstance(data["pid"], int) and data["taken_at"]


def test_take_is_idempotent_for_same_task(tmp_path) -> None:
    MOD.take(tmp_path, "shared/gates.md", "T1")
    code, msg = MOD.take(tmp_path, "shared/gates.md", "T1")
    assert code == 0 and "已持有" in msg
    assert len(_claim_files(tmp_path)) == 1


def test_conflict_exits_nonzero_and_names_holder(tmp_path) -> None:
    MOD.take(tmp_path, "shared/gates.md", "T1")
    try:
        MOD.take(tmp_path, "shared/gates.md", "T2")
    except MOD.ClaimError as e:
        assert "T1" in str(e) and "不得抢占" in str(e)
    else:
        raise AssertionError("他人持有必须拒绝")
    assert json.loads(_claim_files(tmp_path)[0].read_text(encoding="utf-8"))["task"] == "T1"


def test_cli_conflict_exit_code(tmp_path, capsys) -> None:
    assert MOD.main(["take", "--root", str(tmp_path), "--file", "x.md", "--task", "T1"]) == 0
    assert MOD.main(["take", "--root", str(tmp_path), "--file", "x.md", "--task", "T2"]) == 2
    assert "冲突" in capsys.readouterr().err


def test_normalized_paths_share_one_claim(tmp_path) -> None:
    MOD.take(tmp_path, "./src/a.ts", "T1")
    code, msg = MOD.take(tmp_path, "src/a.ts", "T1")
    assert code == 0 and "已持有" in msg
    code, _ = MOD.take(tmp_path, "src/../src/a.ts", "T1")
    assert code == 0
    assert len(_claim_files(tmp_path)) == 1


def test_concurrent_take_exactly_one_wins(tmp_path) -> None:
    procs = [
        subprocess.Popen(
            [sys.executable, str(SCRIPT), "take", "--root", str(tmp_path),
             "--file", "shared/gates.md", "--task", f"T{i}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for i in range(8)
    ]
    codes = [p.wait() for p in procs]
    assert codes.count(0) == 1, codes
    assert codes.count(2) == 7, codes
    assert len(_claim_files(tmp_path)) == 1


# ---------------------------------------------------------------- release


def test_release_is_idempotent(tmp_path) -> None:
    MOD.take(tmp_path, "shared/gates.md", "T1")
    code, msg = MOD.release(tmp_path, "shared/gates.md", "T1")
    assert code == 0 and "释放" in msg
    code, msg = MOD.release(tmp_path, "shared/gates.md", "T1")
    assert code == 0 and "幂等" in msg
    assert not _claim_files(tmp_path)


def test_release_refuses_other_task(tmp_path) -> None:
    MOD.take(tmp_path, "shared/gates.md", "T1")
    try:
        MOD.release(tmp_path, "shared/gates.md", "T2")
    except MOD.ClaimError as e:
        assert "拒绝释放" in str(e) and "T1" in str(e)
    else:
        raise AssertionError("他人 claim 不得释放")
    assert len(_claim_files(tmp_path)) == 1


def test_release_without_task_cleans_up(tmp_path) -> None:
    MOD.take(tmp_path, "shared/gates.md", "T1")
    code, _ = MOD.release(tmp_path, "shared/gates.md")
    assert code == 0 and not _claim_files(tmp_path)


def test_release_does_not_touch_sibling_files(tmp_path) -> None:
    MOD.take(tmp_path, "shared/gates.md", "T1")
    keep = MOD.claims_dir(tmp_path) / "keep.txt"
    keep.write_text("not a claim\n", encoding="utf-8")
    MOD.release(tmp_path, "shared/gates.md")
    assert keep.is_file()
    assert MOD.scan_residuals(tmp_path) == []


# ---------------------------------------------------------------- 残留 / 损坏


def test_residual_scan_names_unreleased_claims(tmp_path) -> None:
    MOD.take(tmp_path, "shared/gates.md", "T1")
    MOD.take(tmp_path, "product/e2e/e2e-index.md", "T2")
    res = MOD.scan_residuals(tmp_path)
    assert len(res) == 2
    assert {r["task"] for r in res} == {"T1", "T2"}
    assert any(r["file"] == "shared/gates.md" for r in res)


def test_corrupt_claim_is_loud(tmp_path) -> None:
    MOD.take(tmp_path, "shared/gates.md", "T1")
    claim = _claim_files(tmp_path)[0]
    claim.write_text("{not json", encoding="utf-8")
    res = MOD.scan_residuals(tmp_path)
    assert len(res) == 1 and res[0]["task"] == "不可解析"
    try:
        MOD.take(tmp_path, "shared/gates.md", "T2")
    except MOD.ClaimError as e:
        assert "不可解析" in str(e)
    else:
        raise AssertionError("损坏 claim 必须响亮拒绝")


def test_hash_collision_is_loud(tmp_path) -> None:
    rel = MOD.normalize_file(tmp_path, "shared/gates.md")
    path = MOD.claim_path(tmp_path, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"file": "other/file.md", "task": "T0"}), encoding="utf-8")
    try:
        MOD.take(tmp_path, "shared/gates.md", "T1")
    except MOD.ClaimError as e:
        assert "碰撞" in str(e)
    else:
        raise AssertionError("哈希碰撞必须响亮")


# ---------------------------------------------------------------- atlas_check 消费面


def test_atlas_check_write_residual_row(tmp_path) -> None:
    acc = _load(ATLAS_CHECK, "atlas_check_under_test")
    rows = acc.Row()
    acc.check_write_claims(tmp_path, rows)
    assert rows.rows[-1]["status"] == "ok"

    MOD.take(tmp_path, "shared/gates.md", "T1")
    rows = acc.Row()
    acc.check_write_claims(tmp_path, rows)
    row = rows.rows[-1]
    assert row["status"] == "WARN" and "shared/gates.md" in row["detail"] and "T1" in row["detail"]
    assert not rows.failed  # 提醒面不置红


def test_case_variant_paths_share_one_claim(tmp_path) -> None:
    """评审 P1-4：大小写不敏感文件系统上 `README.md` / `readme.md` 是同一物理文件。"""
    MOD.take(tmp_path, "README.md", "T1")
    code, msg = MOD.take(tmp_path, "readme.md", "T1")
    assert code == 0 and "已持有" in msg
    try:
        MOD.take(tmp_path, "README.md", "T2")
    except MOD.ClaimError as e:
        assert "T1" in str(e) and "不得抢占" in str(e)
    else:
        raise AssertionError("大小写变体必须共享同一把锁")
    assert len(_claim_files(tmp_path)) == 1


def test_take_retries_when_claim_vanishes(tmp_path, monkeypatch) -> None:
    """评审 P1-3：EEXIST 与读取之间持有方 release ⇒ 重试一次拿锁，不得误拒。"""
    real_open = MOD.os.open
    state = {"first": True}

    def fake_open(path, flags, mode=0o777):
        if state["first"]:
            state["first"] = False
            p = Path(path)
            p.write_text('{"file": "shared/gates.md", "task": "GONE"}', encoding="utf-8")
            p.unlink()
            raise FileExistsError
        return real_open(path, flags, mode)

    monkeypatch.setattr(MOD.os, "open", fake_open)
    code, msg = MOD.take(tmp_path, "shared/gates.md", "T1")
    assert code == 0 and "取得写权" in msg
    assert len(_claim_files(tmp_path)) == 1


def test_release_empty_task_does_not_bypass(tmp_path) -> None:
    """评审 P2-5：`--task ""` 不得被当成「未传」而静默释放他人 claim。"""
    MOD.take(tmp_path, "shared/gates.md", "T1")
    try:
        MOD.release(tmp_path, "shared/gates.md", "")
    except MOD.ClaimError as e:
        assert "空串" in str(e)
    else:
        raise AssertionError("空串 task 必须拒绝")
    assert len(_claim_files(tmp_path)) == 1
