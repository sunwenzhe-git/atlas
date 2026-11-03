#!/usr/bin/env python3
"""E2E 触发段（RFC-20261103-07 D2）：实现完成时归因就绪状态，并**委托既有执行器**。

它不新增门、不生成脚本、不启动控制台：
  * 未就绪 ⇒ 打印缺什么 + 退出码 0（不阻塞收尾）；
  * 就绪 + `--run` ⇒ 调用既有执行器（`atlas_verify.py`；`--page` 时退到 `atlas_check --page`）；
  * 始终打印控制台命令——review 由人执行。

**不得**调用 `gen_e2e_scripts.py --apply`：生成前必须有 E2E 环独立审查报告
（`rings/e2e/reference.md` §12），触发器绕过它就是把未审用例写进仓库。

用法：
    python3 .atlas/scripts/e2e_trigger.py --root . [--page <slug>] [--run] [--json]

退出码：**0** 归因完成（含未就绪）；**1** 委托的执行器失败；**2** 参数错。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas_check as ac  # noqa: E402

# 归因 → 给人看的待办（措辞面向使用者，不含框架名）
HINTS = {
    "gate_off": "本项目未接入 E2E（无分片、无脚本目录）——设计结论，无需动作。",
    "not_declared": "靶场未声明：在 stack-profile 的 e2e.app_base_url 填入真实应用地址。",
    "not_generated": "用例脚本未生成：先过 E2E 环独立审查，再运行 gen_e2e_scripts.py --apply。",
    "app_login_undeclared": "登录形态未声明：按 e2e 环契约的人工会话取出路径录一份会话。",
    "env_not_ready": "靶场不可达：先拉起真实应用，再重跑本命令。",
}


def _console_cmd() -> str:
    return "python3 .atlas/scripts/e2e_console.py --root ."


def _delegate(root: Path, page: str | None) -> int:
    """委托既有执行器；不复制真跑逻辑。"""
    scripts = root / ".atlas" / "scripts"
    if page:
        cmd = [sys.executable, str(scripts / "atlas_check.py"), "--root", ".", "--page", page]
    else:
        verify = scripts / "atlas_verify.py"
        cmd = ([sys.executable, str(verify), "--root", "."] if verify.is_file()
               else [sys.executable, str(scripts / "atlas_check.py"), "--root", "."])
    return subprocess.call(cmd, cwd=str(root))


def main() -> int:
    ap = argparse.ArgumentParser(description="E2E 触发段：归因 + 委托")
    ap.add_argument("--root", default=".", help="项目根")
    ap.add_argument("--page", default=None, help="只处理该页（可选）")
    ap.add_argument("--run", action="store_true", help="就绪时委托既有执行器真跑")
    ap.add_argument("--json", action="store_true", help="机读输出")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    try:
        lay = ac.load_layout(root)
    except Exception as exc:  # 坏配置不能判红，如实报告即可
        print(f"e2e_trigger：布局不可解析（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 2

    prof = lay.stack_profile
    text = prof.read_text(encoding="utf-8") if prof.is_file() else ""
    base_url = ac._profile_scalar(text, "app_base_url")
    reachable = ac._url_reachable(base_url)[0] if base_url else None
    reason = ac.e2e_readiness(text, lay.e2e_cases_dir, lay.e2e_scripts_dir, args.page, reachable)

    # 未声明登录形态不阻断真跑（人工会话可兜底），其余未就绪态一律不跑
    runnable = reason in (None, "app_login_undeclared")
    payload = {
        "ready": runnable,
        "skip_reason": reason,
        "base_url": base_url or None,
        "console": _console_cmd(),
        "ran": False,
    }

    if not args.json:
        if reason:
            print(f"E2E 触发段：未就绪（{reason}）")
            print(f"  {HINTS.get(reason, '')}")
        else:
            print("E2E 触发段：就绪")
        print(f"  控制台（人工 review）：{_console_cmd()}")

    if args.run and runnable:
        payload["ran"] = True
        rc = _delegate(root, args.page)
        payload["exit_code"] = rc
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return rc

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
