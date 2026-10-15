#!/usr/bin/env python3
"""atlas 流水线缺陷与设计冲突自感知上报工具。

由 Agent 在会话中遇到 Atlas 流水线结构性冲突、体验卡点或规则盲区时自动调用，
将结构化的**设计问题**直推云端中心池（GitHub Issues），以便架构师集中排期、定案并升级。
纯标准库，零外部依赖。

**零业务上下文**（`global-rules.md` §15）：本工具上报的是**规则缺陷**，不是某个产品的现场 ——
不上传产品名、业务名词、真实数据或业务代码。业务背景只在会话内用于定位，落盘前一律抽象化。

用法：
    python3 atlas_report.py \
        --title "标题" \
        --kind design-conflict \
        --conflict "设计缺陷本体（哪条规则 / 哪个提取器 / 哪一步流程，在什么条件下冲突）" \
        --shape "触发形态（抽象：什么形状的用法撞上它）" \
        --proposal "建议解耦方向与权衡" \
        --evidence "atlas 侧客观输出：报错 / 规则 ID / 文件行"
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_REPO = "sunwenzhe-git/atlas"
KINDS = ("design-conflict", "rule-friction", "tool-semantic", "bug")


def get_token() -> str | None:
    # 1. 环境变量
    token = os.environ.get("ATLAS_REPORT_TOKEN") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token.strip()

    # 2. 从 git credential 探测
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n",
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if line.startswith("password="):
                    t = line.split("=", 1)[1].strip()
                    if t.startswith(("ghp_", "gho_", "github_pat_")):
                        return t
    except Exception:
        pass

    return None


def format_markdown(title: str, kind: str, conflict: str, shape: str, proposal: str, evidence: str,
                    trigger: str = "auto") -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 来源必须如实：用户要求上报 ≠ 模型自己认出来（`global-rules.md` §15 类别 4 是**漏认**的
    # 信号）。池子里的来源分布就是这条契约的体检表 —— 全 user 说明自动路径没在工作。
    source = ("Agent 自动感知归因（§15 类别 1–3）" if trigger == "auto"
              else "用户显式要求上报（§15 类别 4 —— 本轮模型漏认）")
    return f"""### 📌 流水线自感知上报 (Pipeline RFC)

> **上报时间**：{now}  
> **问题类别**：`{kind}`  
> **上报来源**：{source}  
> **范围**：只报**设计问题**；不含产品名 / 业务名词 / 真实数据（§15 零业务上下文）

---

#### 1. 设计缺陷本体 (Design Flaw)
{conflict or "未详细展开冲突本体"}

#### 2. 触发形态（抽象）(Repro Shape)
{shape or "未提供（抽象描述：什么形状的用法撞上它，而非哪个产品）"}

#### 3. Agent 建议解法与权衡 (Proposal & Trade-offs)
{proposal or "未提供建议方案"}

#### 4. 现场客观证据（atlas 侧输出）(Evidence)
```text
{evidence or "无附带报错或规则 ID"}
```
"""


def save_offline(root: Path, title: str, body: str) -> Path:
    out_dir = root / "product" / "atlas-reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\-]+", "-", title.lower()).strip("-")[:40] or "report"
    date_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    file_path = out_dir / f"RFC-{date_str}-{slug}.md"
    file_path.write_text(body, encoding="utf-8")
    return file_path


def send_github_issue(repo: str, token: str, title: str, kind: str, body: str) -> str:
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Atlas-Pipeline-Reporter/1.0",
        "Content-Type": "application/json",
    }
    payload = {
        "title": f"[{kind}] {title}",
        "body": body,
        "labels": ["pipeline-rfc", f"kind:{kind}"],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    with urllib.request.urlopen(req, timeout=15) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        return str(res_data.get("html_url", ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="问题简述标题")
    parser.add_argument("--kind", choices=KINDS, default="design-conflict", help="问题类型")
    parser.add_argument("--conflict", required=True, help="冲突本体或设计缺陷详细描述")
    parser.add_argument("--shape", default="",
                        help="触发形态（抽象：什么形状的用法撞上它；不含产品名 / 业务名词 / 真实数据）")
    parser.add_argument("--proposal", default="", help="建议方案与权衡")
    parser.add_argument("--evidence", default="", help="atlas 侧客观输出：报错 / 规则 ID / 文件行")
    parser.add_argument("--trigger", choices=("auto", "user"), default="auto",
                        help="谁先发现的：auto = 模型自己认出来；user = 用户要求上报（§15 类别 4）")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub 目标仓库 (默认: sunwenzhe-git/atlas)")
    parser.add_argument("--root", default=".", help="项目根目录")

    args = parser.parse_args()
    body = format_markdown(args.title, args.kind, args.conflict, args.shape, args.proposal, args.evidence,
                           args.trigger)
    token = get_token()

    if token:
        try:
            issue_url = send_github_issue(args.repo, token, args.title, args.kind, body)
            print(f"✅ 流水线设计记录已成功同步至云端中心池: {issue_url}")
            return 0
        except Exception as e:
            print(f"⚠️ 云端上报遇到网络或鉴权问题 ({e})，正在自动保存至本地离线暂存队列...", file=sys.stderr)

    # 离线降级
    saved_path = save_offline(Path(args.root), args.title, body)
    print(f"📁 已自动沉淀至本地离线暂存队列: {saved_path}")
    print("   （配置 GITHUB_TOKEN 后重新运行即可自动推送）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
