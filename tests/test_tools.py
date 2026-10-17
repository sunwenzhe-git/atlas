#!/usr/bin/env python3
"""出厂测试 —— `3509 §B87`（变异证明工具）与 `§B90`（薄桩在 adopt 下列两块）。

只为这两条新增/改动的**工具**钉行为；各环校验器的测试在 `test_validators.py`。
"""
from __future__ import annotations

import ast
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
        report = (td / "out" / "happy.txt").read_text(encoding="utf-8")
        assert report.count("sha256") >= 2
        # 2026-10-17 独立评审：报告必须含**注入 diff** —— 否则「反向破坏的是不是自述那一处」
        # 无法独立复现，证据止于作者自述（现场实例：某轮变异自述「判据被绕过 ⇒ status 变 ok」，
        # 注入后实际红因是夹具缺字段导致的运行期崩，从未触到该断言）。
        assert "## 注入 diff" in report, report
        assert "-ok" in report and "+bad" in report, report


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
        assert data["adapter_version"] == "0.2.0"
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


def _load_pkg_digest():
    return load("pkg_digest", "scripts/pkg_digest.py")


def test_f37_digest_covers_files_under_node_modules_prefix() -> None:
    """F37（2026-10-15）：源包位于 npm 全局安装路径 `<prefix>/lib/node_modules/<pkg>` 时，
    摘要必须**非空且随内容变**。

    旧口径拿**绝对** parts 判 `SKIP_DIRS` ⇒ 每个文件都命中 `node_modules` 被滤掉 ⇒
    摘要恒为 `sha256('')[:16]`，而 install.sh 落戳与 atlas_check 重算两侧同错 ⇒ 恒等 ⇒
    「装配版本」门在任何内容漂移下都不报红（issue #1 现场实证）。本钉把「装配版本」门
    从「只会通过的门」拽回可证伪。
    """
    import hashlib

    pd = _load_pkg_digest()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "lib" / "node_modules" / "atlas-project-harness"
        (root / "shared").mkdir(parents=True)
        (root / "shared" / "closeout.md").write_text("v1\n", encoding="utf-8")
        d1 = pd.digest(root)
        assert d1 != hashlib.sha256(b"").hexdigest()[:16], "空摘要 ⇒ 门恒等恒 ok（F37 病根）"
        (root / "shared" / "closeout.md").write_text("v2\n", encoding="utf-8")
        assert pd.digest(root) != d1, "改装配集内文件必须摆动摘要"


def test_f37_empty_assembly_raises_instead_of_empty_digest() -> None:
    """F37：装配集为空（一个可摘要文件都没有）⇒ 响亮报错，不得静默返回空摘要。

    「装配 0 文件」不是一次合法装配；空摘要流过落戳就等于把门设成恒等。
    """
    pd = _load_pkg_digest()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "docs").mkdir(parents=True)          # 非装配集目录 ⇒ 摘要覆盖不到
        (root / "docs" / "readme.md").write_text("x\n", encoding="utf-8")
        try:
            pd.digest(root)
        except pd.EmptyAssembly:
            pass
        else:
            raise AssertionError("空装配必须抛 EmptyAssembly，而不是返回空摘要")


def _run_tests_adapter(root: Path, *extra: str):
    out_json = root / "tests.json"
    cmd = [sys.executable, str(PKG_ROOT / "adapters" / "tests.py"),
           "--root", str(root), "--out", str(out_json), *extra]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res, (json.loads(out_json.read_text(encoding="utf-8")) if out_json.is_file() else None)


def _mk_profile(root: Path, apps: str = "  - name: svc\n    path: svc\n    kind: backend\n") -> None:
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(
        f"product: legacy-test\norigin: adopt\napps:\n{apps}", encoding="utf-8")


def test_f40_ts_test_with_only_pytest_config_gets_no_command() -> None:
    """F40（2026-10-15，issue #4 现场）：根有 `pytest.ini`、全仓唯一测试文件是 `.test.ts`
    ⇒ `run_command` 必须**留空**并出声，绝不产「`.test.ts` + `python3 -m pytest`」这种
    自相矛盾条目。

    为何要紧：该产出「非空且形态合法」⇒ 骗过 §6.2 的接线前置（`§B118` 只识别「产出为空」），
    把错误事实喂进事实区，且它会随 `refresh_structure --chain` 反复回来。

    变异证明：把 runner 退回「只看配置存在性」⇒ `run_command == RUN_PYTEST`，本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk_profile(root)
        (root / "pytest.ini").write_text("[pytest]\nmarkers =\n    ac: x\n", encoding="utf-8")
        (root / "svc").mkdir()
        (root / "svc" / "util.test.ts").write_text("// t\n", encoding="utf-8")
        res, data = _run_tests_adapter(root)
        assert res.returncode == 0, res.stderr                  # WARN 不得置非零（否则砍链）
        assert len(data["items"]) == 1
        assert data["items"][0]["location"].endswith("util.test.ts")
        assert data["items"][0]["run_command"] is None, data["items"][0]
        assert "WARN" in res.stderr and "util.test.ts" in res.stderr, res.stderr


def test_f40_node_family_runner_comes_from_node_config() -> None:
    """F40 正控：JS/TS 测试按**同族配置**取命令（playwright > vitest > jest > npm test）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk_profile(root)
        (root / "vitest.config.ts").write_text("export default {}\n", encoding="utf-8")
        (root / "svc").mkdir()
        (root / "svc" / "a.test.ts").write_text("t\n", encoding="utf-8")
        _, data = _run_tests_adapter(root)
        assert data["items"][0]["run_command"] == "npx vitest run", data["items"][0]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk_profile(root)
        (root / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
        (root / "svc").mkdir()
        (root / "svc" / "b.spec.ts").write_text("t\n", encoding="utf-8")
        _, data = _run_tests_adapter(root)
        assert data["items"][0]["run_command"] == "npx playwright test", data["items"][0]
        assert data["items"][0]["type"] == "e2e", data["items"][0]


def test_f40_root_config_found_under_app_scope() -> None:
    """F40：`--app` 调用（域级类别的主路径）**不得漏掉项目根的配置**。

    旧实现用同一遍遍历取配置与测试文件，而 `iter_files(base=app_path)` 只走 app 目录 ⇒
    落在项目根的 `pytest.ini` 拿不到，命令被静默降级成 null。配置是**项目级**的，探测必须
    扫整项目；测试文件盘点才按 app 收窄。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _mk_profile(root)
        (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (root / "svc").mkdir()
        (root / "svc" / "test_notes.py").write_text("def test_x(): pass\n", encoding="utf-8")
        _, data = _run_tests_adapter(root, "--app", "svc")
        assert [i["location"] for i in data["items"]] == ["svc/test_notes.py"], data["items"]
        assert data["items"][0]["run_command"] == "python3 -m pytest", data["items"][0]


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


# ---------------------------------------------------------------- 用例 ID 文法单源
#
# 两条断言都是**结构性**判据，不按固定子串找：固定子串只覆盖「逐字复制」，
# 等价改写（`[A-Z\d]`、相邻字符串拼接、f-string 片段、`re.escape`）都绕得过去。
_TAIL_ANCHOR = re.compile(r"\\d\{3\}|\{3\}")


def _case_id_grammar_holders() -> list[str]:
    """持有「含 `E2E-` 且含三位尾号锚」字符串常量的文件（包根相对路径，已排序）。

    按**常量内容**判而不是按固定子串判 —— 否则 `[A-Z0-9]` 写成 `[A-Z\\d]` 这种
    语义等价的一行改写即可绕过「唯一实现」那半条断言。
    """
    holders: set[str] = set()
    for d in ("scripts", "validators", "_support", "extensions"):
        base = PKG_ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and "E2E-" in node.value and _TAIL_ANCHOR.search(node.value)):
                    holders.add(str(p.relative_to(PKG_ROOT)))
                    break
    return sorted(holders)


def _case_id_actual_consumers() -> list[str]:
    """实际取用单源的文件（AST 检出，不看注释 / docstring 里的提及）。

    检出形态：属性访问 `case_id.GRAMMAR`，或调用 `load_module("case_id")`。
    """
    users: set[str] = set()
    for d in ("scripts", "validators", "_support", "extensions"):
        base = PKG_ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Attribute) and node.attr == "GRAMMAR"
                        and isinstance(node.value, ast.Name) and node.value.id == "case_id"):
                    users.add(str(p.relative_to(PKG_ROOT)))
                    break
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "load_module" and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "case_id"):
                    users.add(str(p.relative_to(PKG_ROOT)))
                    break
    return sorted(users)


def test_f45_e2e_case_id_grammar_single_implementation_and_registered_consumers() -> None:
    r"""F45（契约 §5.3）：用例 ID 文法体只允许一处实现（`_support/case_id.py`），
    且取用者集合 ⇔ `CONSUMERS` 登记表。

    ① **唯一实现** —— 任何「含 `E2E-` 且含三位尾号锚」的字符串常量只允许出现在
       `_support/case_id.py`。已咬合：逐字复制 / 字符类等价改写（`[A-Z\d]`）/
       相邻字符串拼接 / 更松的 `\w+` 形态。
    ② **登记面** —— 实际取用者（AST 检出）必须恰好等于 `CONSUMERS`：登记了却没接上、
       接上了却没登记，两个方向都红。

    **已知残留（登记，非静默）**：把文法**拆到多个常量再拼装**（如
    `re.compile("E2E-" + "[A-Z0-9]+-" + r"\d{3}")`）或经 `re.escape` 构造的写法绕过本门 ——
    它按**常量内容**判，不看运行期拼装结果。该形态属刻意构造，且与「按源码文本找正则」这一
    路线的边界一致（同族局限见 `tests/test_canonical_consistency.py` 的否决词钉白名单局限）。
    另注：`scripts/gen_e2e_scripts.py` 与 `scripts/e2e_console.py` 另有**更宽松**的 ID 文本
    匹配（`E2E-\S+` / 表行前缀），它们不实现本文法体、也未经本门 —— 见契约 §5.3 的边界说明。
    """
    ci = load("case_id", "_support/case_id.py")

    holders = _case_id_grammar_holders()
    assert holders == ["_support/case_id.py"], (
        f"文法常量应只存在于 _support/case_id.py；实况={holders}"
        "（新增取用者请经 load_module(\"case_id\") 取用，并登记进 CONSUMERS）"
    )

    actual = _case_id_actual_consumers()
    declared = sorted(ci.CONSUMERS)
    assert actual == declared, (
        f"实际取用者={actual} 与 CONSUMERS 登记表={declared} 不一致"
        "（少登记 ⇒ 补进 CONSUMERS；假登记 ⇒ 去掉或接上单源）"
    )


def test_f47_npm_files_cover_assembly_list() -> None:
    """F45（2026-10-16，issue #17；RFC-20261016-01 D85）：装配面**三张表**必须同步 ——
    `install.sh` 拷贝列表 ⇔ `pkg_digest.ASSEMBLY_COVER_DIRS`（F30 已钉）⇔ **`package.json.files`**
    （本钉补的第三条腿）。

    为何要补：第三张表漏了 `tests` ⇒ npm 分发不含 `tests/`，而 install.sh 第 1 步要拷它、
    pkg_digest 把它算进摘要 ⇒ 经 npm 全局包装配的项目**恒无** `.atlas/tests` ⇒ `atlas_check`
    全量模式的包自检门恒红（采用者侧自己修不了的红，而 `--fast` 一跑就 OK）。

    变异：把 `tests` 从 `package.json.files` 摘掉 ⇒ 本用例红（M-R8）。
    """
    import pytest

    install_sh = PKG_ROOT / "install.sh"
    pkg_json = PKG_ROOT / "package.json"
    if not install_sh.is_file() or not pkg_json.is_file():
        pytest.skip("包内无 install.sh / package.json（副本态）——同步钉要求源包态执行")

    m = re.search(r"for pkg_dir in ([a-z /_]+);", install_sh.read_text(encoding="utf-8"))
    assert m, "install.sh 的 pkg_dir 循环没找到"
    pkg_dirs = {d for d in m.group(1).strip().split()}
    files = set(json.loads(pkg_json.read_text(encoding="utf-8")).get("files") or [])
    missing = sorted(pkg_dirs - files)
    assert not missing, (
        f"install.sh 会拷 {missing}，但 package.json.files 不发布它们 ⇒ 经 npm 装配的项目副本"
        "缺这些目录（issue #17：`.atlas/tests` 恒缺 ⇒ 包自检门恒红，而源包态跑不出来）")
