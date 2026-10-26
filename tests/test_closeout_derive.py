#!/usr/bin/env python3
"""`scripts/closeout_derive.py` 回归测试（M2，`RFC-20261022-01` 批 2）。

触发表（主表 + 补表）是唯一真相源；本器只解析不复制。钉住：
  正控：改契约 ⇒ 1 → 2 → 5 → 7 全出，机器步骤标「自动」、人侧标「人工」；
        无条件行恒出；补表被解析；步骤跨行去重；
  告警宇宙：业务面文件只计条数、不出声；atlas 自有面未命中 ⇒ WARN 逐条；
  响亮失败：触发表引用空号（含已退役步骤 6）⇒ FAIL；表结构解析失败 ⇒ FAIL；
            git ref 不可用 ⇒ FAIL；语义触发行（缺陷修复 / 复盘）不得被路径派生。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "closeout_derive.py"


def _load():
    spec = importlib.util.spec_from_file_location("closeout_derive_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()

CONTRACT = """# atlas 共享契约 — 收口清单

## 1. 触发表（哪些事件要跑哪几步）

| 事件 | 必跑步骤 |
|---|---|
| 改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩 | 1 → 2 → 5 → 7 |
| 环退役 / 真相源迁移 / 产物改名 | 8（生命周期三件套） |
| 改 `DESIGN.md` §12 决策（尤其含「被否：」的行）/ 撤回或收窄某项能力宣称 | **1（含宣称 sweep）**：以该裁决的否决词**全仓 grep** |
| 缺陷修复类任务（bug fix） | **4**（修复验证 7 检查点）→ 1 → 7 |
| 影响面报告已产出（`.trellis/tasks/<ID>/impact.json` 存在）的收口 | 1（含 `impact_reconcile --task <ID>`，2026-10-07 起） |
| 独立审查报告落盘（①②④⑤ 任一实例） | 1（含 `validate_review_report --dir <报告目录>`，2026-10-06 起） |

| 任一工作单元收尾 | 1（至少） |
| 域 / 里程碑收口且出现 ≥2 次同类纠偏（或用户点名复盘） | **11**（harness 复盘，按需） |
| 结构环产出 / 刷新**域级文件** | 1（含**域清单确认门对账**） |

## 2. 步骤

> 编号口径：现行步骤 = 1–5、7–11；步骤 6 已退役，号码不回收。

### 步骤 1 — 门自检

```bash
python3 .atlas/scripts/atlas_check.py
```

### 步骤 2 — 装配面核对

### 步骤 3 — 变更风险定档

### 步骤 4 — 缺陷修复验证

### 步骤 5 — 回灌登记

### 步骤 7 — 提交

### 步骤 8 — 生命周期三件套

### 步骤 9 — 域收口验收走查

### 步骤 10 — 实现代码独立审查

### 步骤 11 — harness 复盘
"""


def _repo(tmp_path: Path, contract: str = CONTRACT) -> Path:
    root = tmp_path / "proj"
    (root / ".atlas" / "shared").mkdir(parents=True)
    (root / ".atlas" / "shared" / "closeout.md").write_text(contract, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "base"], cwd=root, check=True)
    return root


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("changed\n", encoding="utf-8")


def _res(root: Path, base: str = "HEAD") -> dict:
    return MOD.run(root, base)


# ---------------------------------------------------------------- 正控 / 语法


def test_contract_row_arrow_chain_and_labels(tmp_path) -> None:
    root = _repo(tmp_path)
    _touch(root, "shared/gates.md")
    res = _res(root)
    assert set(res["steps"]) == {"1", "2", "5", "7"}, res["steps"]
    text = res["text"]
    assert text.splitlines()[0] == "本清单不含语义触发行，正文自查"
    for n in (1, 2):
        assert f"[自动] 步骤 {n} " in text, text
    for n in (5, 7):
        assert f"[人工] 步骤 {n} " in text, text
    assert f"步骤 7 " in text and f"closeout.md §2" in text


def test_unconditional_row_always_present(tmp_path) -> None:
    root = _repo(tmp_path)
    _touch(root, "src/app.ts")
    res = _res(root)
    assert set(res["steps"]) == {"1"}, res["steps"]
    assert "任一工作单元收尾" in res["text"]


def test_supplementary_table_is_parsed(tmp_path) -> None:
    root = _repo(tmp_path)
    _touch(root, ".trellis/spec/structure/current/demo/facts.md")
    res = _res(root)
    assert "结构环产出" in res["text"], res["text"]


def test_steps_are_deduped_across_rows(tmp_path) -> None:
    root = _repo(tmp_path)
    _touch(root, "shared/gates.md")
    _touch(root, "DESIGN.md")
    _touch(root, ".trellis/spec/structure/current/demo/facts.md")
    text = _res(root)["text"]
    assert text.count("步骤 1 ") == 1, text


# ---------------------------------------------------------------- 告警宇宙


def test_business_file_is_counted_without_warning(tmp_path) -> None:
    root = _repo(tmp_path)
    _touch(root, "src/app.ts")
    _touch(root, "src/lib.ts")
    res = _res(root)
    assert res["business"] == 2
    assert "[WARN]" not in res["text"], res["text"]
    assert "业务面 2 个，只计条数" in res["text"]


def test_atlas_owned_unmatched_warns_each_path(tmp_path) -> None:
    root = _repo(tmp_path)
    _touch(root, "patches/unknown.py")
    _touch(root, "_support/unknown.py")
    res = _res(root)
    warns = [l for l in res["text"].splitlines() if l.startswith("[WARN]")]
    assert len(warns) == 2, res["text"]
    assert any("patches/unknown.py" in w for w in warns)
    assert any("_support/unknown.py" in w for w in warns)


def test_tests_dir_is_covered_by_script_row(tmp_path) -> None:
    """`tests/` 属「脚本」族：改回归钉不得落进「未命中」告警（真跑咬出的假信号）。"""
    root = _repo(tmp_path)
    _touch(root, "tests/test_something.py")
    res = _res(root)
    assert "[WARN]" not in res["text"], res["text"]
    assert set(res["steps"]) == {"1", "2", "5", "7"}, res["steps"]


# ---------------------------------------------------------------- 响亮失败


def test_dead_step_reference_fails(tmp_path) -> None:
    bad = CONTRACT.replace("| 环退役 / 真相源迁移 / 产物改名 | 8（生命周期三件套） |",
                           "| 环退役 / 真相源迁移 / 产物改名 | 6（生命周期三件套） |")
    root = _repo(tmp_path, bad)
    _touch(root, "rings/e2e/reference.md")
    try:
        _res(root)
    except MOD.DeriveError as e:
        assert "步骤 6" in str(e) and "空号" in str(e)
    else:
        raise AssertionError("引用已退役步骤 6 必须 FAIL")


def test_missing_table_fails_loudly(tmp_path) -> None:
    root = _repo(tmp_path, "# 收口清单\n\n## 2. 步骤\n\n### 步骤 1 — 门自检\n")
    _touch(root, "shared/gates.md")
    try:
        _res(root)
    except MOD.DeriveError as e:
        assert "触发表" in str(e)
    else:
        raise AssertionError("表结构缺失必须 FAIL，不得退化成空清单")


def test_bad_git_ref_fails(tmp_path) -> None:
    root = _repo(tmp_path)
    try:
        _res(root, "no-such-ref")
    except MOD.DeriveError as e:
        assert "git diff" in str(e)
    else:
        raise AssertionError("坏 ref 必须 FAIL")


# ---------------------------------------------------------------- 语义行不派生


def test_semantic_rows_never_derived(tmp_path) -> None:
    root = _repo(tmp_path)
    _touch(root, "src/app.ts")
    res = _res(root)
    assert "4" not in res["steps"] and "11" not in res["steps"], res["steps"]
    assert "缺陷修复类任务" not in res["text"]
    assert "harness 复盘" not in res["text"]


# ---------------------------------------------------------------- 真契约 / CLI


def test_real_canonical_contract_parses() -> None:
    rows = MOD.parse_table((PKG_ROOT / "shared" / "closeout.md").read_text(encoding="utf-8"))
    assert len(rows) >= 10, len(rows)
    existing = MOD.parse_existing_steps((PKG_ROOT / "shared" / "closeout.md").read_text(encoding="utf-8"))
    MOD.validate_step_references(rows, existing)  # 不抛 = 无空号


def test_cli_json_and_exit_codes(tmp_path, capsys) -> None:
    root = _repo(tmp_path)
    _touch(root, "shared/gates.md")
    assert MOD.main(["--root", str(root), "--diff-base", "HEAD", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and "1" in payload["steps"]

    bad = _repo(tmp_path / "bad", CONTRACT.replace(
        "| 环退役 / 真相源迁移 / 产物改名 | 8（生命周期三件套） |",
        "| 环退役 / 真相源迁移 / 产物改名 | 12（生命周期三件套） |"))
    assert MOD.main(["--root", str(bad), "--diff-base", "HEAD"]) == 2
    assert "[FAIL]" in capsys.readouterr().err


def test_non_git_project_fails_with_short_message(tmp_path, capsys) -> None:
    """评审 P2-2：非 git 项目不是坏 ref —— 短句拒绝，不刷整屏 git usage。"""
    root = tmp_path / "plain"
    (root / ".atlas" / "shared").mkdir(parents=True)
    (root / ".atlas" / "shared" / "closeout.md").write_text(CONTRACT, encoding="utf-8")
    assert MOD.main(["--root", str(root), "--diff-base", "HEAD"]) == 2
    err = capsys.readouterr().err
    assert "不是 git 仓库" in err
    assert "usage:" not in err.lower()


def test_event_path_tokens_follow_layout(tmp_path) -> None:
    """RFC-20261026-01：ADR / 审查报告前缀随资产根；布局配置本身归「契约」事件。"""
    (tmp_path / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: docs\n", encoding="utf-8")
    tokens = dict(MOD.event_path_tokens(tmp_path))
    assert tokens["ADR"] == ("docs/adr/",)
    assert tokens["独立审查报告"] == ("docs/reviews/", "docs/e2e/reviews/")
    assert "atlas.config.yaml" in tokens["契约"]
