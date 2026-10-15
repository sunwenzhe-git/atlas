#!/usr/bin/env python3
"""atlas 项目接线（apply-wiring）回归测试。

覆盖：
  1. AGENTS.md atlas 指针块写入与幂等更新；
  2. .trellis/config.yaml after_finish hook 登记与幂等；
  3. Python 工程探测与 pytest 配置兜底（R6.2 对账定稿：pyproject.toml 优先承载、
     既有 ini 只补 marker、pythonpath 环境补丁随 F23 退役不再注入、非 Python 跳过）。
     探测**只认声明**：出厂模板的 `backend_test:` 是注释示例，按 raw 文本匹配会把纯前端
     项目判成 Python（2026-10-15 存量事故）⇒ 回归夹具 = `templates/stack-profile.yaml`
     逐字节；误建的 ini 走退役对称清理（内容逐字节相等才删）。
  4. `.gitignore` 第 5 触点（2026-10-15，issue #8 后所有接线项目都需要）：
     已有文件才追加 `.adapter-out/`、`.adapter-out` 子串幂等、`!.adapter-out` 负模式
     不打架、无文件不首创。**无退役对称**（单向追加），由测试钉住这一不对称语义。
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
WIRING_SCRIPT = PKG_ROOT / "patches" / "project-wiring" / "apply-wiring.py"


def load_wiring():
    spec = importlib.util.spec_from_file_location("apply_wiring_mod", WIRING_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_wire_python_scaffold_created_ini_only_carries_markers() -> None:
    """R6.2：无任何 pytest 配置 ⇒ 新建 pytest.ini 只承载 marker 注册；
    `pythonpath = .` 环境补丁随 F23 退役（适配器已输出 python3 -m pytest）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "applied"
        path, text = res["_write"]
        assert "markers" in text and "ac" in text
        assert "pythonpath" not in text, "pythonpath 补丁必须随 F23 退役"
        path.write_text(text, encoding="utf-8")

        # 再次运行：幂等跳过
        res2 = wiring.wire_python_scaffold(root)
        assert res2["status"] == "skipped"
        assert "已包含 marker 注册" in res2["detail"]


def test_wire_python_scaffold_pyproject_toml_takes_priority() -> None:
    """R6.2：pyproject.toml 已有 [tool.pytest...] 段 ⇒ skip，种种不另立/不复活 pytest.ini
    （防「接线复活被清掉的补丁」病理：legacy 清桩实测）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\nmarkers = [\n    "ac: x",\n]\n', encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "skipped" and "pyproject.toml" in res["detail"]


def test_wire_python_scaffold_existing_ini_gets_marker_only() -> None:
    """R6.2：既有 pytest.ini 只补缺失的 marker 注册；不注入 pythonpath、不动其他配置。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (root / "pytest.ini").write_text("[pytest]\naddopts = -v\n", encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "applied"
        path, text = res["_write"]
        assert "markers" in text and "ac" in text
        assert "pythonpath" not in text, "不得注入 pythonpath（F23 已修根因）"
        assert "addopts = -v" in text, "既有配置不得破坏"


def test_wire_python_scaffold_skips_non_python_projects() -> None:
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "skipped"
        assert "非 Python 工程" in res["detail"]


def test_wire_python_scaffold_skips_factory_template_frontend_project() -> None:
    """事故回归（2026-10-15，存量实测）：**出厂模板**的 profile 里 `backend_test:` 段是
    **注释示例**（那行注释含 `framework: pytest`），旧判据按 raw 文本逐字匹配 ⇒ 用模板开户的
    **每个**项目都被判成 Python 工程 ⇒ 纯前端仓库里凭空多出一个 pytest.ini。

    判据：模板原样 + 无 Python 特征文件 ⇒ `is_python_project` 必须为假、门必须 skip、
    **不得**落下 pytest.ini。（旧测用空目录当夹具 ⇒ 永远看不到这个形态，故本测以
    `templates/stack-profile.yaml` 逐字节为夹具。）"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir()
        (root / "product" / "stack-profile.yaml").write_bytes(
            (PKG_ROOT / "templates" / "stack-profile.yaml").read_bytes())
        (root / "package.json").write_text('{"name":"v2"}', encoding="utf-8")
        assert wiring.is_python_project(root) is False, "模板注释不得当声明用"
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "skipped" and "非 Python 工程" in res["detail"], res
        assert not (root / "pytest.ini").exists(), "纯前端项目不得被建 pytest.ini"


def test_wire_python_scaffold_honours_declared_backend_test_section() -> None:
    """反向判据：**声明**（未注释）的 `backend_test:` / `framework: pytest` ⇒ 仍按 Python 认。
    防「修误判时把真 Python 项目一起修没了」。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir()
        (root / "product" / "stack-profile.yaml").write_text(
            "product: x\nbackend_test:\n  command: pytest backend/tests\n  framework: pytest\n",
            encoding="utf-8")
        assert wiring.is_python_project(root) is True
        assert wiring.wire_python_scaffold(root)["status"] == "applied"


def test_wire_python_scaffold_removes_own_stray_ini_in_non_python_project() -> None:
    """退役对称：非 Python 工程里躺着一份**逐字节等于兜底内容**的 pytest.ini ⇒ 那是本脚本
    早先误建的，必须清掉（存量仓库的修复通道；判据事故见上面那条回归）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pytest.ini").write_text(wiring.MARKERS_INI, encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "removed" and res["_remove"] == root / "pytest.ini", res
        res["_remove"].unlink()  # 模拟 --apply 的写盘动作
        assert not (root / "pytest.ini").exists()


def test_wire_python_scaffold_keeps_user_edited_ini() -> None:
    """用户改过的 pytest.ini（内容 ≠ 兜底内容）⇒ 一字不动，只跳过（「只删自己写的」）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        edited = wiring.MARKERS_INI + "\naddopts = -v\n"
        (root / "pytest.ini").write_text(edited, encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "skipped" and "_remove" not in res, res
        assert (root / "pytest.ini").read_text(encoding="utf-8") == edited


def test_wire_config_upgrades_legacy_apply_hook_in_place() -> None:
    """C1（R7）：存量 `--apply` hook ⇒ 原位升级为 `--chain`；**不得**插入第二行
    （否则旧+新双 hook 常驻，每次 finish refresh 跑两遍——R6 现场教训变体）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = root / ".trellis" / "config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            "hooks:\n"
            "  after_finish:\n"
            '    - "python3 .atlas/scripts/refresh_structure.py --root . --apply"\n',
            encoding="utf-8")
        res = wiring.wire_config(root)
        assert res["status"] == "applied" and "in-place" in res["detail"], res
        new_text = res["_write"][1]
        res["_write"][0].write_text(new_text, encoding="utf-8")  # 应用写盘，再验幂等
        assert new_text.count("refresh_structure.py") == 1, new_text
        assert "--chain" in new_text and "--apply" not in new_text

        # 幂等：已是 --chain ⇒ skipped
        res2 = wiring.wire_config(root)
        assert res2["status"] == "skipped", res2


def test_wire_config_preserves_custom_hook_without_second_line() -> None:
    """C1：前缀命令尾是自定义形态（非 --apply/--chain）⇒ 尊重自定 hook，不再插入。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = root / ".trellis" / "config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            "hooks:\n"
            "  after_finish:\n"
            '    - "python3 .atlas/scripts/refresh_structure.py --root . --custom-flag"\n',
            encoding="utf-8")
        res = wiring.wire_config(root)
        assert res["status"] == "skipped" and "自定义" in res["detail"], res


# ---------------------------------------------------------------- pi 宿主扩展（第 4 触点）


def test_wire_pi_extension_skips_without_pi_dir() -> None:
    """非 pi 宿主 ⇒ 跳过，且**不得**替用户创建 `.pi/`（不自动创建宿主目录）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        res = wiring.wire_pi_extension(root)
        assert res and all(r["status"] == "skipped" for r in res), res
        assert not (root / ".pi").exists(), "不得替用户创建宿主目录"


def test_wire_pi_extension_installs_and_registers_surgically() -> None:
    """真实 `settings.json` 形态：往 `extensions[]` **插一行**——位置对、其余内容与格式
    逐字节不动、JSON 合法、复跑幂等；扩展本体逐字节等于包面 `extensions/pi.ts`。"""
    wiring = load_wiring()
    original = (
        '{\n'
        '  "enableSkillCommands": true,\n'
        '  "extensions": [\n'
        '    "./extensions/trellis/index.ts"\n'
        '  ],\n'
        '  "prompts": [\n'
        '    "./prompts"\n'
        '  ]\n'
        '}\n'
    )
    expected = (
        '{\n'
        '  "enableSkillCommands": true,\n'
        '  "extensions": [\n'
        '    "./extensions/atlas/index.ts",\n'
        '    "./extensions/trellis/index.ts"\n'
        '  ],\n'
        '  "prompts": [\n'
        '    "./prompts"\n'
        '  ]\n'
        '}\n'
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".pi").mkdir()
        (root / ".pi" / "settings.json").write_text(original, encoding="utf-8")

        res = {r["file"]: r for r in wiring.wire_pi_extension(root)}
        assert res[".pi/extensions/atlas/index.ts"]["status"] == "applied", res
        assert res[".pi/settings.json"]["status"] == "applied", res
        for r in res.values():  # 应用写盘
            if r.get("_write"):
                p, t = r["_write"]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(t, encoding="utf-8")

        assert (root / ".pi" / "settings.json").read_text(encoding="utf-8") == expected, \
            "外科式插入：只该多出那一个元素，其余逐字节不动"
        assert (root / ".pi" / "extensions" / "atlas" / "index.ts").read_text(encoding="utf-8") \
            == (PKG_ROOT / "extensions" / "pi.ts").read_text(encoding="utf-8")
        cfg = json.loads((root / ".pi" / "settings.json").read_text(encoding="utf-8"))
        assert cfg["extensions"][0] == wiring.PI_EXT_ENTRY and cfg["enableSkillCommands"] is True

        again = {r["file"]: r["status"] for r in wiring.wire_pi_extension(root)}
        assert set(again.values()) == {"skipped"}, again


def test_wire_pi_extension_does_not_guess_settings_shape() -> None:
    """`settings.json` 里没有 `extensions` 数组 ⇒ **不猜结构、不写盘**，只报要手加的那一行；
    且扩展本体仍照常落地（两件事解耦，不因登记失败而丢文件）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".pi").mkdir()
        (root / ".pi" / "settings.json").write_text('{\n  "enableSkillCommands": true\n}\n',
                                                    encoding="utf-8")
        res = {r["file"]: r for r in wiring.wire_pi_extension(root)}
        assert res[".pi/extensions/atlas/index.ts"]["status"] == "applied", res
        reg = res[".pi/settings.json"]
        assert reg["status"] == "skipped" and "_write" not in reg, reg
        assert wiring.PI_EXT_ENTRY in reg["detail"], reg


def test_pi_extension_carries_onboarding_state() -> None:
    """**弱判据（形态）**：宿主扩展必须带「开户态」判定 —— 「装配 ≠ 开户」在 pi 侧的另一面
    （`/atlas status` 报开户态、未开户时注入 adopt 指引、未开户不跑 `--fast` 免每轮噪声）。

    `extensions/pi.ts` 是 TypeScript：本仓无 ts 工具链、无执行级测试 ⇒ 只能钉形态，
    **语义归人工评审**（同 `test_backfill_contract` 的声明口径）。"""
    src = (PKG_ROOT / "extensions" / "pi.ts").read_text(encoding="utf-8")
    missing = [f for f in ('type Onboarding', '"none" | "partial" | "done"',
                           "_meta.json", "atlas-apply adopt",
                           'if (status.onboarding !== "done") return;')
               if f not in src]
    assert not missing, f"宿主扩展缺「开户态」判据片段：{missing}"


_PI_DRIVER = r'''
// 由 test_pi_extension_onboarding_behaviour 生成：假宿主 + 真扩展，把两个钩子与 /atlas status
// 的输出来出来。只依赖 node builtins 与扩展自身。
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import ext from "__PI_TS__";

const commands: Record<string, any> = {};
const hooks: Record<string, any> = {};
let execCount = 0;
let lastNotice = "";
let statusText = "";

const ui = {
  notify: (m: string) => { lastNotice = m; },
  setStatus: (_k: string, v: string) => { statusText = v; },
};
const pi: any = {
  registerCommand: (n: string, d: any) => { commands[n] = d; },
  on: (e: string, f: any) => { hooks[e] = f; },
  exec: async () => { execCount += 1; return { code: 0, stdout: "", stderr: "" }; },
};
ext(pi);

function makeProject(name: string, opts: { prd: boolean; meta: boolean }): string {
  const root = mkdtempSync(join(tmpdir(), "pi-ext-"));
  mkdirSync(join(root, ".atlas"), { recursive: true });
  writeFileSync(join(root, ".atlas", "VERSION"), "fixture-version\n");
  // 三个态都放上门禁脚本：这样「未开户不跑 --fast」只能归因于开户态闸，而不是"脚本不在"
  mkdirSync(join(root, ".atlas", "scripts"), { recursive: true });
  writeFileSync(join(root, ".atlas", "scripts", "atlas_check.py"), "print('ok')\n");
  mkdirSync(join(root, "product"), { recursive: true });
  writeFileSync(join(root, "product", "stack-profile.yaml"), "product: x\norigin: adopt\n");
  mkdirSync(join(root, ".trellis", "spec", "structure"), { recursive: true });
  if (opts.prd) {
    mkdirSync(join(root, "product", "prd"), { recursive: true });
    writeFileSync(join(root, "product", "prd", "prd.md"), "# prd\n");
  }
  if (opts.meta) writeFileSync(join(root, ".trellis", "spec", "structure", "_meta.json"), "{}\n");
  return root;
}

const cases: Record<string, { prd: boolean; meta: boolean }> = {
  "未开户": { prd: false, meta: false },
  "开户中": { prd: true, meta: false },
  "已开户": { prd: true, meta: true },
};

const out: Record<string, any> = {};
for (const [label, opts] of Object.entries(cases)) {
  const root = makeProject(label, opts);
  // ① before_agent_start 注入
  const injected = await hooks["before_agent_start"]({ systemPrompt: "" }, { cwd: root, hasUI: true, ui });
  const notice = String(injected?.systemPrompt ?? "");
  const bar = statusText;
  // ② turn_end 是否跑门禁
  execCount = 0;
  await hooks["turn_end"]({ outcome: "completed", toolResults: [{}] }, { cwd: root, hasUI: true, ui });
  // ③ /atlas status
  lastNotice = "";
  await commands["atlas"].handler("status", { cwd: root, hasUI: true, ui });
  out[label] = { notice, bar, execCount, status: lastNotice };
}

console.log(JSON.stringify(out));
'''


def test_pi_extension_onboarding_behaviour() -> None:

    """**执行级**判据（bun 可用时）：把真扩展挂到假宿主上，验「装配 ≠ 开户」三态的行为 ——
      * 未开户/开户中 ⇒ 注入的是**开户指引**（含 `atlas-apply adopt`），不是契约守则；
      * 已开户 ⇒ 注入 Project Harness 契约守则；
      * 未开户 ⇒ `turn_end` **不跑** `--fast`（否则每轮弹同一句警告，纯噪声）；
      * `/atlas status` 一律报开户态。
    bun 缺席 ⇒ 显式 skip（不是通过）。
    """
    import shutil
    import subprocess

    bun = shutil.which("bun")
    if not bun:
        import pytest
        pytest.skip("无 bun ⇒ pi 扩展执行级判据跳过（形态判据仍由上一测试守着）")

    pi_ts = PKG_ROOT / "extensions" / "pi.ts"
    driver = _PI_DRIVER.replace("__PI_TS__", pi_ts.as_posix())
    with tempfile.TemporaryDirectory() as td:
        drv = Path(td) / "driver.ts"
        drv.write_text(driver, encoding="utf-8")
        run = subprocess.run([bun, "run", str(drv)], capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stdout + run.stderr
        data = json.loads(run.stdout.strip().splitlines()[-1])

    assert "尚未开户" in data["未开户"]["notice"], data["未开户"]
    assert "atlas-apply adopt" in data["未开户"]["notice"], data["未开户"]
    assert "Project Harness Notice" not in data["未开户"]["notice"], "未开户不该只注入契约守则"
    assert data["未开户"]["execCount"] == 0, "未开户不得跑 --fast（每轮噪声）"

    assert "尚未开户" in data["开户中"]["notice"], data["开户中"]
    assert data["开户中"]["execCount"] == 0, "开户中同样不跑 --fast"

    assert "Project Harness Notice" in data["已开户"]["notice"], data["已开户"]
    assert data["已开户"]["execCount"] == 1, "已开户才跑 --fast"

    for label in ("未开户", "开户中", "已开户"):
        assert "开户态" in data[label]["status"], data[label]
    assert "未开户（装配完成" in data["未开户"]["status"]
    assert "已开户" in data["已开户"]["status"]


# ---------------------------------------------------------------- .gitignore 兜底（第 5 触点）


def test_wire_gitignore_appends_and_is_idempotent() -> None:
    """已有 `.gitignore` 且未忽略 `.adapter-out` ⇒ 追加一行；重跑幂等（字节不变）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        gi = root / ".gitignore"
        gi.write_text("node_modules/\n", encoding="utf-8")
        res = wiring.wire_gitignore(root)
        assert res["status"] == "applied", res
        gi.write_text(res["_write"][1], encoding="utf-8")
        assert gi.read_text(encoding="utf-8") == "node_modules/\n.adapter-out/\n"

        res2 = wiring.wire_gitignore(root)
        assert res2["status"] == "skipped" and "_write" not in res2, res2
        assert gi.read_text(encoding="utf-8") == "node_modules/\n.adapter-out/\n"


def test_wire_gitignore_skips_any_existing_adapter_out_form() -> None:
    """内容已含 `.adapter-out` 子串（等价写法 `.adapter-out` / `.adapter-out/*`）⇒ 幂等跳过。

    子串判据的理由：不猜用户写的形态是否与本行等价——已收住 `.adapter-out` 后任何追加
    都只会造重复行，宁跳不叠。"""
    wiring = load_wiring()
    for content in (".adapter-out\n", ".adapter-out/*\n"):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".gitignore").write_text("node_modules/\n" + content, encoding="utf-8")
            res = wiring.wire_gitignore(root)
            assert res["status"] == "skipped" and "_write" not in res, (content, res)
            assert (root / ".gitignore").read_text(encoding="utf-8") \
                == "node_modules/\n" + content, "等价写法下不得追加重复行"


def test_wire_gitignore_skips_when_user_negation_present() -> None:
    """`!.adapter-out` 负模式 ⇒ 跳过，不与用户既有规则打架（意见相反时不动手）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".gitignore").write_text("node_modules/\n!.adapter-out/\n", encoding="utf-8")
        res = wiring.wire_gitignore(root)
        assert res["status"] == "skipped" and "_write" not in res, res
        assert "负模式" in res["detail"], res


def test_wire_gitignore_never_creates_missing_file() -> None:
    """无 `.gitignore` ⇒ 不首创（根级 gitignore 是用户自有文件），只给建议行。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        res = wiring.wire_gitignore(root)
        assert res["status"] == "skipped" and "_write" not in res, res
        assert not (root / ".gitignore").exists(), "不得替用户首创"
        assert ".adapter-out/" in res["detail"], res


def test_wire_gitignore_handles_missing_trailing_newline() -> None:
    """文件不以换行收尾 ⇒ 先补边界再追加；用户末行不得被并进新行。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".gitignore").write_text("node_modules/", encoding="utf-8")  # 无尾部换行
        res = wiring.wire_gitignore(root)
        assert res["status"] == "applied", res
        assert res["_write"][1] == "node_modules/\n.adapter-out/\n", res["_write"][1]
