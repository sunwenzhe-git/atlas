#!/usr/bin/env python3
"""atlas 项目接线（apply-wiring）回归测试。

覆盖：
  1. AGENTS.md atlas 指针块写入与幂等更新；
  2. .atlas/config.yaml after_archive hook 登记、幂等与 after_finish 迁移；
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
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from adapters.ac import pytest as ac_pytest  # noqa: E402
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
        res = wiring.wire_project(root)
        assert res["status"] == "applied"
        path, text = res["_write"]
        assert "markers" in text and "ac" in text
        assert "pythonpath" not in text, "pythonpath 补丁必须随 F23 退役"
        path.write_text(text, encoding="utf-8")

        # 再次运行：幂等跳过
        res2 = wiring.wire_project(root)
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
        res = wiring.wire_project(root)
        assert res["status"] == "skipped" and "pyproject.toml" in res["detail"]


def test_wire_python_scaffold_existing_ini_gets_marker_only() -> None:
    """R6.2：既有 pytest.ini 只补缺失的 marker 注册；不注入 pythonpath、不动其他配置。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (root / "pytest.ini").write_text("[pytest]\naddopts = -v\n", encoding="utf-8")
        res = wiring.wire_project(root)
        assert res["status"] == "applied"
        path, text = res["_write"]
        assert "markers" in text and "ac" in text
        assert "pythonpath" not in text, "不得注入 pythonpath（F23 已修根因）"
        assert "addopts = -v" in text, "既有配置不得破坏"


def test_wire_python_scaffold_skips_non_python_projects() -> None:
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        res = wiring.wire_project(root)
        assert res["status"] == "skipped"
        assert "非本 extractor 工程" in res["detail"]


def test_wire_python_scaffold_skips_factory_template_frontend_project() -> None:
    """事故回归（2026-10-15，存量实测）：**出厂模板**的 profile 里 `backend_test:` 段是
    **注释示例**（那行注释含 `framework: pytest`），旧判据按 raw 文本逐字匹配 ⇒ 用模板开户的
    **每个**项目都被判成 Python 工程 ⇒ 纯前端仓库里凭空多出一个 pytest.ini。

    判据：模板原样 + 无 Python 特征文件 ⇒ `is_python_project` 必须为假、门必须 skip、
    **不得**落下 pytest.ini。（旧测用空目录当夹具 ⇒ 永远看不到这个形态，故本测以
    `templates/stack-profile.yaml` 逐字节为夹具。）

    变异证明 **M51a**：探测退回 raw 文本匹配 ⇒ 本用例（模板夹具回归）红。
    """
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir()
        (root / "product" / "stack-profile.yaml").write_bytes(
            (PKG_ROOT / "templates" / "stack-profile.yaml").read_bytes())
        (root / "package.json").write_text('{"name":"v2"}', encoding="utf-8")
        assert ac_pytest.is_python_project(root) is False, "模板注释不得当声明用"
        res = wiring.wire_project(root)
        assert res["status"] == "skipped" and "非本 extractor 工程" in res["detail"], res
        assert not (root / "pytest.ini").exists(), "纯前端项目不得被建 pytest.ini"


def test_wire_python_scaffold_honours_declared_backend_test_section() -> None:
    """反向判据：显式 `framework: pytest` / `extractor: pytest` ⇒ 仍按 Python 认。
    防「修误判时把真 Python 项目一起修没了」。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir()
        (root / "product" / "stack-profile.yaml").write_text(
            "product: x\nbackend_test:\n  command: pytest backend/tests\n  framework: pytest\n",
            encoding="utf-8")
        assert ac_pytest.is_python_project(root) is True
        assert wiring.wire_project(root)["status"] == "applied"

        (root / "product" / "stack-profile.yaml").write_text(
            "product: x\nbackend_test:\n  extractor: pytest\n  test_dir: backend/tests\n",
            encoding="utf-8")
        assert ac_pytest.is_python_project(root) is True


def test_wire_python_scaffold_skips_framework_neutral_backend_test() -> None:
    """`backend_test:` 是框架中立段：非 Python 项目声明它不得被塞 pytest.ini。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir()
        (root / "product" / "stack-profile.yaml").write_text(
            "product: x\nbackend_test:\n  extractor: vitest\n  test_dir: backend/src\n",
            encoding="utf-8")
        assert ac_pytest.is_python_project(root) is False
        res = wiring.wire_project(root)
        assert res["status"] == "skipped", res
        assert not (root / "pytest.ini").exists()


def test_wire_python_scaffold_removes_own_stray_ini_in_non_python_project() -> None:
    """退役对称：非 Python 工程里躺着一份**逐字节等于兜底内容**的 pytest.ini ⇒ 那是本脚本
    早先误建的，必须清掉（存量仓库的修复通道；判据事故见上面那条回归）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pytest.ini").write_text(ac_pytest.MARKERS_INI, encoding="utf-8")
        res = wiring.wire_project(root)
        assert res["status"] == "removed" and res["_remove"] == root / "pytest.ini", res
        res["_remove"].unlink()  # 模拟 --apply 的写盘动作
        assert not (root / "pytest.ini").exists()


def test_wire_python_scaffold_keeps_user_edited_ini() -> None:
    """用户改过的 pytest.ini（内容 ≠ 兜底内容）⇒ 一字不动，只跳过（「只删自己写的」）。

    变异证明 **M51b**：摘掉「逐字节相等才清」护栏 ⇒ 本用例红（用户文件被误删）。
    """
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        edited = ac_pytest.MARKERS_INI + "\naddopts = -v\n"
        (root / "pytest.ini").write_text(edited, encoding="utf-8")
        res = wiring.wire_project(root)
        assert res["status"] == "skipped" and "_remove" not in res, res
        assert (root / "pytest.ini").read_text(encoding="utf-8") == edited


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
        '    "./extensions/other/index.ts"\n'
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
        '    "./extensions/other/index.ts"\n'
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
  mkdirSync(join(root, ".atlas", "spec", "structure"), { recursive: true });
  if (opts.prd) {
    mkdirSync(join(root, "product", "prd"), { recursive: true });
    writeFileSync(join(root, "product", "prd", "prd.md"), "# prd\n");
  }
  if (opts.meta) writeFileSync(join(root, ".atlas", "spec", "structure", "_meta.json"), "{}\n");
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


def test_pi_extension_carries_failure_signature_gate() -> None:
    """**弱判据（形态）**：`turn_end` 的失败判据必须是「失败签名差分」而非裸退出码
    （issue #67：裸退出码把历史遗留 FAIL 每轮复读，告警疲劳，真新增被淹没）。

    钉住四件：`--json` 机器可读失败集消费面、签名基线落运行态、sha256 签名差分、
    不可解析静默不误报。语义归下一测试的执行级判据。"""
    src = (PKG_ROOT / "extensions" / "pi.ts").read_text(encoding="utf-8")
    missing = [f for f in ('"--fast", "--json"',
                           "pi-turn-failures.json",
                           'createHash("sha256")',
                           "!base.has(sig)",
                           "if (!Array.isArray(payload?.failures)) return;")
               if f not in src]
    assert not missing, f"宿主扩展缺「失败签名差分」判据片段：{missing}"


_PI_FAILSIG_DRIVER = r'''
// 由 test_pi_extension_failure_signature_behaviour 生成：假宿主 + 真扩展，把 turn_end 的
// 失败签名差分全场景过一遍（issue #67 §5）。exec 打桩成按序吐 `atlas_check --fast --json`
// 的产物（不真跑门禁）；基线文件真落临时项目目录，判「提醒几次 + 基线里剩什么」。
import { mkdirSync, mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import ext from "__PI_TS__";

function makeProject(): string {
  const root = mkdtempSync(join(tmpdir(), "pi-failsig-"));
  mkdirSync(join(root, ".atlas"), { recursive: true });
  writeFileSync(join(root, ".atlas", "VERSION"), "fixture-version\n");
  mkdirSync(join(root, ".atlas", "scripts"), { recursive: true });
  writeFileSync(join(root, ".atlas", "scripts", "atlas_check.py"), "print('ok')\n");
  mkdirSync(join(root, "product", "prd"), { recursive: true });
  writeFileSync(join(root, "product", "prd", "prd.md"), "# prd\n");
  writeFileSync(join(root, "product", "stack-profile.yaml"), "product: x\norigin: adopt\n");
  mkdirSync(join(root, ".atlas", "spec", "structure"), { recursive: true });
  writeFileSync(join(root, ".atlas", "spec", "structure", "_meta.json"), "{}\n");
  return root;
}

const A1 = { name: "generated", code: 1, detail: "drift X" };
const A2 = { name: "generated", code: 1, detail: "drift Y" }; // 同门不同详情 ⇒ 新签名
const B = { name: "e2e", code: 2, detail: "case 005 red" };
const payload = (failures: any[]) =>
  JSON.stringify({ root: ".", ok: failures.length === 0, rows: [], failures });

const script: Array<{ code: number; stdout: string }> = [];
let cursor = 0;
let notifies = 0;
let last = "";
const hooks: Record<string, any> = {};
const pi: any = {
  registerCommand: () => {},
  on: (e: string, f: any) => { hooks[e] = f; },
  exec: async () => {
    const r = script[cursor++];
    return { code: r.code, stdout: r.stdout, stderr: "" };
  },
};
const ui = {
  notify: (m: string) => { notifies += 1; last = m; },
  setStatus: () => {},
};
ext(pi);

function baselineOf(root: string): string[] | null {
  try {
    const raw = JSON.parse(readFileSync(join(root, ".atlas", "runs", "pi-turn-failures.json"), "utf-8"));
    return Object.entries(raw.signatures).map(([sig, m]: [string, any]) => sig.slice(0, 4) + ":" + m.name);
  } catch {
    return null; // 无基线
  }
}

async function turn(root: string) {
  await hooks["turn_end"]({ outcome: "completed", toolResults: [{}] }, { cwd: root, hasUI: true, ui });
  return { notifies, last, baseline: baselineOf(root) };
}

const out: Record<string, any> = {};

// ① 主场景：同项目连续轮次（全绿 → A 首现 → A 复读 → 新增 B → A 变详情 → 全绿 → A 复发 → 不可解析）
const root = makeProject();
const steps: any[] = [];
script.push({ code: 0, stdout: payload([]) });
steps.push(await turn(root));
script.push({ code: 1, stdout: payload([A1]) });
steps.push(await turn(root));
script.push({ code: 1, stdout: payload([A1]) });
steps.push(await turn(root));
script.push({ code: 1, stdout: payload([A1, B]) });
steps.push(await turn(root));
script.push({ code: 1, stdout: payload([A2, B]) });
steps.push(await turn(root));
script.push({ code: 0, stdout: payload([]) });
steps.push(await turn(root));
script.push({ code: 1, stdout: payload([A1]) });
steps.push(await turn(root));
script.push({ code: 1, stdout: "Traceback (most recent call last):\n  ..." });
steps.push(await turn(root));
out.main = steps;

// ② 升级路径：基线缺失 + 首轮就带历史失败 ⇒ 静默落基线（issue #67 trade-off）
const root2 = makeProject();
notifies = 0; last = ""; // 计数按场景清零：本断言只关心这个项目自己的动静
script.push({ code: 1, stdout: payload([A1]) });
out.upgrade = await turn(root2);

console.log(JSON.stringify(out));
'''


def test_pi_extension_failure_signature_behaviour() -> None:
    """**执行级**判据（bun 可用时）：`turn_end` 失败判据 = 失败签名差分（issue #67 §5）——
      * 全绿静默且建空基线；失败 A 首现告警、复读静默（主诉：不再逐轮复读）；
      * 新增 B ⇒ 只告警 B；A 详情变化 ⇒ 再告警 A；
      * 全绿收缩回写基线 ⇒ A 复发能再提醒一次；
      * 输出不可解析 ⇒ 静默且基线原地不动（执行异常不伪装成门禁回归）；
      * 升级路径（无基线 + 首轮带历史失败）⇒ 静默落基线。
    bun 缺席 ⇒ 显式 skip（不是通过）。"""
    import shutil
    import subprocess

    bun = shutil.which("bun")
    if not bun:
        import pytest
        pytest.skip("无 bun ⇒ pi 扩展执行级判据跳过（形态判据仍由上一测试守着）")

    pi_ts = PKG_ROOT / "extensions" / "pi.ts"
    driver = _PI_FAILSIG_DRIVER.replace("__PI_TS__", pi_ts.as_posix())
    with tempfile.TemporaryDirectory() as td:
        drv = Path(td) / "driver.ts"
        drv.write_text(driver, encoding="utf-8")
        run = subprocess.run([bun, "run", str(drv)], capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stdout + run.stderr
        data = json.loads(run.stdout.strip().splitlines()[-1])

    main, up = data["main"], data["upgrade"]
    n = [s["notifies"] for s in main]
    assert n[0] == 0 and main[0]["baseline"] == [], main[0]          # 全绿首轮：静默 + 空基线
    assert n[1] == 1 and "generated" in main[1]["last"], main[1]     # A 首现 ⇒ 告警点名
    assert n[2] == 1, main[2]                                        # 同一 A 复读 ⇒ 静默（主诉）
    assert n[3] == 2 and "e2e" in main[3]["last"] \
        and "generated" not in main[3]["last"], main[3]              # 新增 B ⇒ 只告警 B
    assert n[4] == 3 and "generated" in main[4]["last"] \
        and "e2e" not in main[4]["last"], main[4]                    # A 变详情 ⇒ 只再告警 A
    assert n[5] == 3 and main[5]["baseline"] == [], main[5]          # 全绿 ⇒ 静默 + 基线收缩为空
    assert n[6] == 4, main[6]                                        # A 复发 ⇒ 再提醒一次
    assert n[7] == 4 and main[7]["baseline"] == main[6]["baseline"] != [], main[7]
                                                                     # 不可解析 ⇒ 静默且基线不动
    assert up["notifies"] == 0 and up["baseline"] \
        and len(up["baseline"]) == 1, up                             # 升级路径 ⇒ 静默落基线


# ---------------------------------------------------------------- .gitignore 兜底（第 5 触点）


ATLAS_IGNORE_BLOCK = (
    "# atlas：装配包不入库；规范与任务账本入库（install.py 幂等维护）\n"
    ".atlas/*\n"
    "!.atlas/tasks/\n"
    "!.atlas/spec/\n"
)


def test_wire_gitignore_appends_and_is_idempotent() -> None:
    """已有 `.gitignore` ⇒ 追加 `.adapter-out/` 与 `.atlas` 白名单；重跑幂等（字节不变）。

    变异证明 **M65**：摘掉 `.gitignore` 触点 ⇒ 本用例红（第五触点不再落盘；本测即注册行
    所指的 fifth-touchpoint 用例，旧名 `test_gitignore_fifth_touchpoint_appends_idempotently`
    已退役为现名）。
    """
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        gi = root / ".gitignore"
        gi.write_text("node_modules/\n", encoding="utf-8")
        res = wiring.wire_gitignore(root)
        assert res["status"] == "applied", res
        gi.write_text(res["_write"][1], encoding="utf-8")
        assert gi.read_text(encoding="utf-8") == "node_modules/\n.adapter-out/\n" + ATLAS_IGNORE_BLOCK

        res2 = wiring.wire_gitignore(root)
        assert res2["status"] == "skipped" and "_write" not in res2, res2
        assert gi.read_text(encoding="utf-8") == "node_modules/\n.adapter-out/\n" + ATLAS_IGNORE_BLOCK


def test_wire_gitignore_appends_atlas_block_when_adapter_out_present() -> None:
    """`.adapter-out` 已以等价写法收住 ⇒ 不重复追加，只补 `.atlas` 白名单；重跑幂等。"""
    wiring = load_wiring()
    for content in (".adapter-out\n", ".adapter-out/*\n"):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gi = root / ".gitignore"
            gi.write_text("node_modules/\n" + content, encoding="utf-8")
            res = wiring.wire_gitignore(root)
            assert res["status"] == "applied", (content, res)
            text = res["_write"][1]
            assert text == "node_modules/\n" + content + ATLAS_IGNORE_BLOCK, (content, text)
            gi.write_text(text, encoding="utf-8")
            res2 = wiring.wire_gitignore(root)
            assert res2["status"] == "skipped" and "_write" not in res2, (content, res2)


def test_wire_gitignore_skips_adapter_out_negation_but_still_adds_atlas() -> None:
    """`!.adapter-out` 负模式 ⇒ 不追加 `.adapter-out`，但 atlas 块仍按默认口径补。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        gi = root / ".gitignore"
        gi.write_text("node_modules/\n!.adapter-out/\n", encoding="utf-8")
        res = wiring.wire_gitignore(root)
        assert res["status"] == "applied", res
        text = res["_write"][1]
        assert text == "node_modules/\n!.adapter-out/\n" + ATLAS_IGNORE_BLOCK, text
        assert text.count(".adapter-out/") == 1, "不得与用户负模式打架"


def test_wire_gitignore_respects_user_atlas_rules() -> None:
    """用户已手写任意 `.atlas` 规则 ⇒ 保留其口径，不追加默认块。"""
    wiring = load_wiring()
    for content in (
        ".atlas/*\n!.atlas/tasks/\n!.atlas/spec/\n",
        ".atlas/\n",
        "!.atlas/legacy/\n",
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gi = root / ".gitignore"
            gi.write_text("node_modules/\n" + content, encoding="utf-8")
            res = wiring.wire_gitignore(root)
            text = res["_write"][1] if "_write" in res else gi.read_text(encoding="utf-8")
            assert "# atlas：装配包不入库" not in text, (content, text)
            assert "保留用户口径" in res["detail"] or res["status"] == "skipped", (content, res)


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
        assert res["_write"][1] == "node_modules/\n.adapter-out/\n" + ATLAS_IGNORE_BLOCK, \
            res["_write"][1]


def test_wire_python_scaffold_skips_external_extractor_command() -> None:
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir()
        (root / "product" / "stack-profile.yaml").write_text(
            "product: x\nbackend_test:\n  extractor_command: java -jar tools/ac.jar\n  test_dir: src/test\n",
            encoding="utf-8")
        res = wiring.wire_project(root)
        assert res["status"] == "skipped", res
        assert not (root / "pytest.ini").exists()
