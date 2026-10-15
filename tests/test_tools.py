#!/usr/bin/env python3
"""出厂测试 —— `3509 §B87`（变异证明工具）与 `§B90`（薄桩在 adopt 下列两块）。

只为这两条新增/改动的**工具**钉行为；各环校验器的测试在 `test_validators.py`。
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mp = load("mutation_proof", "scripts/mutation_proof.py")
stub = load("gen_testid_stub", "scripts/gen_testid_stub.py")


# ---------------------------------------------------------------- B87 变异证明工具

def test_mutation_proof_happy_path() -> None:
    """基线 GREEN → 注入 RED → 逐字节还原 → GREEN ⇒ 构成证据。

    变异：让 `proof` 不再校验「还原后必须绿」⇒ 末一段断言红。
    """
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        t = td / "gate.txt"
        t.write_text("ok\n", encoding="utf-8")
        state = {"injected": False}

        def run():
            return (1, "red\n") if state["injected"] else (0, "green\n")

        def mutate(b: bytes) -> bytes:
            state["injected"] = True
            out = b.replace(b"ok", b"bad")
            # 还原发生在 proof 内部，这里用「注入标记」模拟门的红；还原后由 run 侧复位
            return out

        def run_and_reset():
            # 第一次调用（基线）后不变；注入后红；还原后（字节已回）自动复位
            if state["injected"] and t.read_bytes() == b"ok\n":
                state["injected"] = False
            return run()

        assert mp.proof("happy", t, mutate, run_and_reset, td / "out") is True
        assert (td / "out" / "happy.txt").read_text(encoding="utf-8").count("sha256") >= 2


def test_mutation_proof_rejects_noop_mutation() -> None:
    """注入**没有改变字节** ⇒ 抛 `MutationNotApplied`（`§B87` 的假阴性防线）。

    变异：把这条防线去掉（不再比较 mutated == before）⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        t = td / "gate.txt"
        t.write_text("ok\n", encoding="utf-8")
        try:
            mp.proof("noop", t, lambda b: b, lambda: (0, "green\n"), td / "out")
        except mp.MutationNotApplied:
            return
        raise AssertionError("锚点未命中却未抛 MutationNotApplied —— 会造出「门不咬」的假阴性")


def test_mutation_proof_reports_not_a_proof_when_gate_is_toothless() -> None:
    """注入后门**仍绿** ⇒ 本切片不构成证据（返回 False）。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        t = td / "gate.txt"
        t.write_text("ok\n", encoding="utf-8")
        assert mp.proof("toothless", t, lambda b: b.replace(b"ok", b"bad"),
                        lambda: (0, "green\n"), td / "out") is False


def test_mutation_proof_baseline_must_be_green() -> None:
    """基线本来是红的 ⇒ 本切片作废（返回 False），不拿它当证据。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        t = td / "gate.txt"
        t.write_text("ok\n", encoding="utf-8")
        assert mp.proof("baseline-red", t, lambda b: b.replace(b"ok", b"bad"),
                        lambda: (1, "red\n"), td / "out") is False


# ---------------------------------------------------------------- B90 薄桩两块清单

def _mk_adopt_root(td: Path, *, real: dict, proto: dict) -> Path:
    root = td
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(
        "product: 夹具\norigin: adopt\napps:\n  - name: web\n    path: web\n"
        "    kind: frontend\n    role: landing\n    stack: 展示\n"
        "adapters:\n  routes: null\nprototype:\n  dir: product/prototype\n"
        "e2e:\n  runner: python-playwright\n", encoding="utf-8")
    for rel, text in real.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (root / "product" / "prototype").mkdir(parents=True, exist_ok=True)
    for name, ids in proto.items():
        (root / "product" / "prototype" / name).write_text(
            "<main>" + "".join(f'<b data-testid="{i}"></b>' for i in ids) + "</main>",
            encoding="utf-8")
    return root


def test_stub_lists_want_and_actual_blocks() -> None:
    """E1 薄桩两块：① 分片应然（实现者的命名依据）② 前端实然（现状）。

    变异：只列第二块 ⇒ 应然名字从薄桩消失 ⇒ 红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = _mk_adopt_root(
            Path(td),
            real={"web/src/Page.vue": '<b data-testid="voices-page"></b>'},
            proto={"voices.html": ["voices-page", "voices-new-btn"]},
        )
        # 用例分片引用 voices-page 与 voices-new-btn ⇒ 第一块（应然）两行
        d = root / "product" / "e2e" / "cases"
        d.mkdir(parents=True, exist_ok=True)
        (d / "voices.md").write_text(
            "## E2E-VOICES-001 x\n\n```atlas-case\nid: E2E-VOICES-001\nstep:\n"
            "  - click voices-page\n  - click voices-new-btn\n```\n", encoding="utf-8")
        text, n = stub.render(root, ["web"])
        assert "## 第一块：分片应然" in text, text
        assert "## 第二块：前端实然" in text, text
        first = text.split("## 第二块", 1)[0]
        assert "`voices-new-btn`" in first, "应然名字没进第一块"
        assert n == 2, f"应然计数应 = 2，实际 {n}"
        second = text.split("## 第二块：前端实然", 1)[1]
        assert "`voices-page`" in second and "`voices-new-btn`" not in second, second


def test_stub_frontend_empty_lists_empty_actual() -> None:
    """前端无 data-testid ⇒ 第二块（实然）空标注；第一块（应然）照常（实现者的依据）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 夹具\napps:\n  - name: web\n    path: web\n"
            "    kind: frontend\n    role: landing\n    stack: 展示\n", encoding="utf-8")
        d = root / "product" / "e2e" / "cases"
        d.mkdir(parents=True)
        (d / "voices.md").write_text(
            "## E2E-VOICES-001 x\n\n```atlas-case\nid: E2E-VOICES-001\nstep:\n"
            "  - click voices-page\n```\n", encoding="utf-8")
        text, n = stub.render(root, ["web"])
        assert n == 1
        assert "| （空） | 前端暂无 `data-testid`（全部页未实现） |" in text, text


def test_f23_tests_adapter_python3_m_pytest() -> None:
    """F23（R6「融与化」）：adapters/tests.py 探测到 pytest 配置时输出 python3 -m pytest 命令形态。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: legacy-test\norigin: adopt\napps:\n  - name: svc\n    path: svc\n    kind: backend\n",
            encoding="utf-8",
        )
        (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        svc = root / "svc"
        svc.mkdir(parents=True)
        (svc / "test_notes.py").write_text("def test_x(): pass\n", encoding="utf-8")
        out_json = root / "tests.json"

        cmd = [
            sys.executable,
            str(PKG_ROOT / "adapters" / "tests.py"),
            "--root", str(root),
            "--out", str(out_json),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert data["adapter_version"] == "0.1.1"
        assert len(data["items"]) == 1
        assert data["items"][0]["run_command"] == "python3 -m pytest"


def test_f30_assembly_cover_in_sync_with_install_sh() -> None:
    """F30（R7，2026-10-15）：pkg_digest 装配集白名单 ⇔ install.sh 拷贝列表**双向同步钉**
    （防将来新增拷贝目录自成摘要盲区；含 docs-only 改动不再激发装配版本回环）。"""
    import pytest

    install_sh = PKG_ROOT / "install.sh"
    if not install_sh.is_file():
        pytest.skip("包内无 install.sh（副本态）——同步钉要求源包态执行")
    import importlib.util

    spec = importlib.util.spec_from_file_location("pkg_digest", PKG_ROOT / "scripts" / "pkg_digest.py")
    pd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pd)

    install_txt = install_sh.read_text(encoding="utf-8")
    m = re.search(r"for pkg_dir in ([a-z /_]+);", install_txt)
    assert m, install_txt
    pkg_dirs = {d for d in m.group(1).strip().split()}
    cover = pdo_cover = set(pd.ASSEMBLY_COVER_DIRS)

    # ① install.sh pkg_dir 循环里的每一笔必须都在摘要白名单
    missing = pkg_dirs - cover - {"LICENSE"}
    assert not missing, f"install.sh 拷贝了 {missing}，pkg_digest 未覆盖（摘要盲区）"
    # ② skills/* 是 [2/6] 拷贝集（不在 pkg_dir 循环）⇒ 必须也在白名单
    assert "skills/" in install_txt and "skills" in cover
    # ③ 非装配文件不进摘要：临时 math clone 中仅 docs 改动 ⇒ digest 不变
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for d in ("scripts", "docsx".replace("docsx", "docs")):
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "x.py").write_text("# keep\n", encoding="utf-8")
        (root / "docs" / "readme.md").write_text("docs v1\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text("v1\n", encoding="utf-8")
        d1 = pd.digest(root)
        (root / "docs" / "readme.md").write_text("docs v2\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text("v2\n", encoding="utf-8")
        (root / "scripts" / "x.py").write_text("# changed\n", encoding="utf-8")
        d2 = pd.digest(root)
        assert d1 != d2, "装配集内文件变化必须摘摆动"
        # docs 文件变动带同 change 一样受 scripts 驱动，拆分到纯净场景：
        with tempfile.TemporaryDirectory() as t2:
            root2 = Path(t2)
            (root2 / "scripts").mkdir(parents=True)
            (root2 / "scripts" / "x.py").write_text("# keep\n", encoding="utf-8")
            (root2 / "docs").mkdir(parents=True)
            (root2 / "docs" / "readme.md").write_text("v1\n", encoding="utf-8")
            d3 = pd.digest(root2)
            (root2 / "docs" / "readme.md").write_text("v2\n", encoding="utf-8")
            assert pd.digest(root2) == d3, "非装配集文件变动不得摆动摘要（F8 关门）"



def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"{'FAIL' if failed else 'PASS'} ({len(tests) - failed}/{len(tests)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
