#!/usr/bin/env python3
"""atlas 流水线缺陷与设计冲突自感知上报工具。

由 Agent 在会话中遇到 Atlas 流水线结构性冲突、体验卡点或规则盲区时自动调用，
将结构化现场直推云端中心池（GitHub Issues），以便架构师集中排期、定案并升级。
纯标准库，零外部依赖。

用法：
    python3 atlas_report.py \
        --title "标题" \
        --kind design-conflict \
        --conflict "冲突本体说明" \
        --context "业务背景" \
        --proposal "建议方案" \
        --evidence "日志或代码"
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


def format_markdown(title: str, kind: str, conflict: str, context: str, proposal: str, evidence: str) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""### 📌 流水线自感知上报 (Pipeline RFC)

> **上报时间**：{now}  
> **问题类别**：`{kind}`  
> **上报来源**：Agent 自动感知归因

---

#### 1. 业务背景与触发时机 (Context)
{context or "未提供具体业务背景"}

#### 2. 冲突本体与设计不合理处 (Conflict & Design Flaw)
{conflict or "未详细展开冲突本体"}

#### 3. Agent 建议解法与权衡 (Proposal & Trade-offs)
{proposal or "未提供建议方案"}

#### 4. 现场客观证据 (Evidence)
```text
{evidence or "无附带代码片段或日志"}
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
    parser.add_argument("--context", default="", help="业务背景与触发时机")
    parser.add_argument("--proposal", default="", help="建议方案与权衡")
    parser.add_argument("--evidence", default="", help="客观报错输出或代码片段")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub 目标仓库 (默认: sunwenzhe-git/atlas)")
    parser.add_argument("--root", default=".", help="项目根目录")

    args = parser.parse_args()
    body = format_markdown(args.title, args.kind, args.conflict, args.context, args.proposal, args.evidence)
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
