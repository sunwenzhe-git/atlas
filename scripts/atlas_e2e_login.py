#!/usr/bin/env python3
"""`atlas e2e login` —— 一次性人工登录入口（RFC-20261112-01 v1 / C）。

为什么存在：控制台与运行器每次执行都开**临时 browser context**，普通浏览器里的登录态不会被
复用；此前只能手工 `playwright codegen --save-storage=...`，令牌过期后再导一次。本命令把
「打开完整靶场地址 → 人登录 → probe 判定 → 落盘」标准化为一个入口，产物 `source: imported`。

纪律（与 RFC / `rings/e2e/reference.md` §7.1 同口径）：

* 只在 `e2e.app_login.mode: real` 下可用；`fabricated` / `none` 调用即失败。
* `e2e.app_login.probe` 必填；probe 不通过 ⇒ **不写盘**、不覆盖旧 state、退出非 0。
* **无人值守环境不弹窗**（非 TTY / CI / 无图形会话）⇒ 明确提示并退出码 3。
* state / meta 原子写、`0600`；meta 只放哈希与指纹。

用法：
    atlas e2e login [--root .] [--timeout 300]
    python3 .atlas/scripts/atlas_e2e_login.py [--root .] [--timeout 300] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
from _support.siblings import load_module  # noqa: E402
from _support.layout import LayoutError, load_layout  # noqa: E402

auth_state = load_module("auth_state")
pw_runner = load_module("pw_runner")
stack_profile = load_module("stack_profile")

LOGIN_SCRIPT = r"""
const fs = require('node:fs');
const { chromium } = require('@playwright/test');

const baseUrl = process.argv[2];
const statePath = process.argv[3];
const probeUrl = process.argv[4];
const timeoutMs = Number(process.argv[5] || 300000);
const probeTimeoutMs = Number(process.env.ATLAS_PROBE_TIMEOUT_MS || 3000);

async function looksAuthenticated(page) {
  const headers = {};
  try {
    const values = await page.evaluate(() => {
      const out = {};
      for (let i = 0; i < localStorage.length; i += 1) {
        const k = localStorage.key(i);
        if (k) out[k] = localStorage.getItem(k) || '';
      }
      return out;
    });
    const preferred = ['token', 'access_token', 'accessToken', 'userToken'];
    for (const name of preferred) {
      if (values[name]) { headers.Authorization = 'Bearer ' + values[name]; break; }
    }
  } catch (_) { /* 页面尚未就绪 */ }
  try {
    const resp = await page.request.get(probeUrl, { headers, timeout: probeTimeoutMs });
    const ctype = (resp.headers()['content-type'] || '').split(';')[0].trim().toLowerCase();
    return resp.ok() && ctype === 'application/json';
  } catch (_) {
    return false;
  }
}

(async () => {
  const browser = await chromium.launch({ headless: false });
  let context;
  try {
    context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' }).catch(() => {});
    console.log('[atlas] 浏览器已打开：请在窗口内完成登录；检测到可用会话后自动保存。');
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 1000));
      const pages = context.pages();
      const target = pages.length ? pages[pages.length - 1] : page;
      if (await looksAuthenticated(target)) {
        await context.storageState({ path: statePath });
        console.log('[atlas] 已检测到可用会话，storageState 已导出。');
        await browser.close();
        process.exit(0);
      }
    }
    console.error('[atlas] 等待登录超时：未检测到 probe 通过；未写入任何文件。');
    await browser.close();
    process.exit(4);
  } catch (err) {
    try { await browser.close(); } catch (_) {}
    console.error('[atlas] 登录流程失败: ' + ((err && err.message) || err));
    process.exit(5);
  }
})();
"""


def _error(msg: str, code: int = 2, *, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def _unattended_reason() -> str:
    if os.environ.get("CI"):
        return "检测到 CI 环境"
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "标准输入 / 输出不是终端（无人值守）"
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "Linux 无图形会话（DISPLAY / WAYLAND_DISPLAY 未设置）"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--timeout", type=int, default=300, help="等待人工登录的秒数（默认 300）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    try:
        lay = load_layout(root)
    except LayoutError as exc:
        return _error(f"项目布局配置非法：{exc}", as_json=args.json)
    if not lay.stack_profile.is_file():
        return _error(f"缺少 {lay.print_value('stack_profile')}", as_json=args.json)
    prof = stack_profile.parse_profile(lay.stack_profile.read_text(encoding="utf-8"))
    e2e = prof.get("e2e") if isinstance(prof.get("e2e"), dict) else {}
    app_login = e2e.get("app_login") if isinstance(e2e.get("app_login"), dict) else {}
    mode = str(app_login.get("mode") or "real")
    if mode != "real":
        return _error(
            f"`atlas e2e login` 只在 app_login.mode=real 下可用（当前 {mode}）："
            "fabricated / none 不需要人工会话",
            as_json=args.json,
        )
    probe = app_login.get("probe")
    errors = auth_state.probe_config_errors(probe)
    if errors:
        return _error(
            "e2e.app_login.probe 缺失或非法："
            + "；".join(errors)
            + "（real 模式必须能判定会话可用性，见 rings/e2e/reference.md §7.1）",
            as_json=args.json,
        )
    base_url = str(e2e.get("app_base_url") or "").strip()
    if not base_url:
        return _error("e2e.app_base_url 未声明（登录需要完整地址，含 organId 等 query）", as_json=args.json)

    reason = _unattended_reason()
    if reason:
        return _error(
            f"{reason}：本命令需要人完成登录，不在此环境弹窗。请在本地终端直接运行 "
            "`atlas e2e login`；无人值守环境请预置 state 或改用 app_login.mode: real 的"
            " ATLAS_APP_USER / ATLAS_APP_PASSWORD 自动登录（CI 不承诺可复现，D103）",
            code=3, as_json=args.json,
        )

    node = shutil.which("node")
    if not node:
        return _error("未找到 node（本命令依赖 e2e 运行器的 node 与 @playwright/test）", as_json=args.json)
    nm = e2e.get("node_modules")
    pw_bin, nm_dir, source, why = pw_runner.resolve(root, str(nm) if nm else None)
    if pw_bin is None:
        return _error(f"node-playwright 不可用：{why}", as_json=args.json)
    br_ok, br_detail = pw_runner.probe_browser(lay.e2e_scripts_dir)
    if not br_ok:
        return _error(f"浏览器未就绪：{br_detail}", as_json=args.json)

    probe_target = auth_state.probe_url(base_url, probe)
    fd, tmp_state = tempfile.mkstemp(prefix="atlas-e2e-login-", suffix=".json")
    os.close(fd)
    os.unlink(tmp_state)
    tmp_state_path = Path(tmp_state)
    script_path = None
    try:
        fd, script_tmp = tempfile.mkstemp(prefix="atlas-e2e-login-", suffix=".cjs")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(LOGIN_SCRIPT)
        script_path = Path(script_tmp)
        env = {**os.environ}
        if nm_dir:
            env["NODE_PATH"] = str(nm_dir)
        print(f"[atlas] 打开 {base_url}；等待登录（最多 {args.timeout}s）……")
        proc = subprocess.run(
            [node, str(script_path), base_url, str(tmp_state_path), probe_target, str(args.timeout * 1000)],
            env=env, timeout=args.timeout + 60,
        )
        if proc.returncode != 0:
            return _error(
                "未保存登录态：人工登录未完成或会话未通过初步检测（旧 state 未被修改）",
                code=proc.returncode or 4, as_json=args.json,
            )
        state = auth_state.read_json(tmp_state_path)
        if state is None:
            return _error("登录脚本未产出可解析的 storageState（旧 state 未被修改）", as_json=args.json)
        tenant_hint = auth_state.tenant_warning(state, base_url)
        if tenant_hint:
            print(f"[atlas] 告警：{tenant_hint}", file=sys.stderr)
        # Python 侧按同一契约复核 probe：只有通过才落盘（node 侧只负责检测「登录已完成」）。
        ok, why_probe, status = auth_state.run_probe(base_url, probe, state)
        if not ok:
            return _error(
                f"probe 未通过：{why_probe}（未写入 state / meta，旧文件保持不变）",
                code=6, as_json=args.json,
            )
        meta = auth_state.write_state(
            root, state, source="imported", base_url=base_url,
            probe={"ok": True, "status": status},
        )
    except subprocess.TimeoutExpired:
        return _error("等待登录超时（旧 state 未被修改）", as_json=args.json)
    finally:
        for p in (tmp_state_path, script_path):
            try:
                if p and Path(p).is_file():
                    Path(p).unlink()
            except OSError:
                pass

    state_path, meta_path = auth_state.state_paths(root)
    out = {
        "ok": True,
        "state": str(state_path),
        "meta": str(meta_path),
        "source": meta.get("source"),
        "fingerprint": str(meta.get("base_url_fingerprint") or "")[:12],
        "next": "回到控制台点「执行用例」，或运行 atlas check",
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"[atlas] 登录态已保存：{state_path}")
        print(f"[atlas] meta：{meta_path}（source=imported，指纹 {out['fingerprint']}…）")
        print(f"[atlas] 下一步：{out['next']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
