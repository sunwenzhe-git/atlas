"""手工走查清单解析（D143）——旧单行格式 + 可选 `atlas-manual` 块，共用同一行式解析。

旧行：`- <ID> | <页面> | <标题> | <操作说明>`。
新块：`## <ID> <标题>` 后接 ```` ```atlas-manual ````；id/title 只从标题行取，块里只写
`page / precondition / step / evidence`。`step` 每行 `操作 | 观察 | 命令(可空)`，复用
`_support/case_block.parse_block` 的扁平数组语义，不引入第二套嵌套语法。

纯标准库；控制台（e2e_console.py）与校验器共用本模块，避免两份解析漂移。
"""
from __future__ import annotations

import re

from _support.case_block import parse_block

_HEADING = re.compile(r"^##\s+(MANUAL-[A-Za-z0-9-]+)\s+(.+?)\s*$")
_FENCE = "```atlas-manual"


def parse_manual(text: str) -> list[dict]:
    items: list[dict] = []
    heading: tuple[str, str] | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HEADING.match(line)
        if m:
            heading = (m.group(1), m.group(2).strip())
        if line.strip().startswith(_FENCE):
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            parsed = parse_block("\n".join(body), ("page", "evidence"))
            if "id" in parsed or "title" in parsed:
                raise ValueError("atlas-manual 块的 id/title 由 ## 标题行提供，块内不得再写")
            page = (parsed.get("page") or [""])[0].strip() if parsed.get("page") else ""
            steps: list[dict] = []
            for raw in parsed.get("step") or []:
                parts = [p.strip() for p in raw.split("|", 2)]
                steps.append({
                    "action": parts[0] if parts else "",
                    "expect": parts[1] if len(parts) > 1 else "",
                    "command": parts[2] if len(parts) > 2 else "",
                })
            id_, title = heading or ("", "")
            items.append({
                "id": id_, "page": page, "title": title,
                "note": f"结构化走查（{len(steps)} 步）" if steps else "",
                "precondition": list(parsed.get("precondition") or []),
                "steps": steps,
                "evidence": list(parsed.get("evidence") or []),
            })
            i += 1
            continue
        s = line.strip()
        if s.startswith("- "):
            parts = [x.strip() for x in s[2:].split("|")]
            if len(parts) >= 4:
                items.append({
                    "id": parts[0], "page": parts[1], "title": parts[2],
                    "note": " | ".join(parts[3:]),
                })
        i += 1
    return items
