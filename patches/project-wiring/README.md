# patches/project-wiring

把 atlas 的**入口指针**、**测试配置**、**宿主扩展**与 **`.gitignore` 兜底**幂等写进目标项目，让新项目的 agent 一开会话就知道「本项目用 atlas、契约在哪、需求级怎么走」。

| # | 接线 | 落点 | 作用 |
|---|---|---|---|
| A | **AGENTS.md 指针** | `<项目根>/AGENTS.md` 的 `<!-- ATLAS:START/END -->` 区块 | 给出契约路径、skills、`atlas workflow` 步骤、收口门 |
| B | **extractor 测试配置** | `<项目根>/<测试配置>`（仅声明栈） | 由 `adapters/ac/` 的 extractor 提供；无 hook 的栈跳过 |
| C | **pi 宿主扩展** | `<项目根>/.pi/extensions/atlas/index.ts` + `.pi/settings.json` 的 `extensions[]` | `/atlas` 命令与「未开户」提示 |
| D | **`.gitignore`** | `<项目根>/.gitignore`（仅已存在时） | 追加 `.adapter-out/`，避免中间产物常驻未跟踪噪声 |

## 内容

| 文件 | 作用 |
|---|---|
| `apply-wiring.py` | 幂等接线器（缺省 dry-run，`--apply` 才写） |
| `agent-pointer.md` | AGENTS.md 指针段的正文（不含标记，标记由脚本包裹） |

## 用法

```bash
python3 apply-wiring.py --target <项目根>            # 干跑
python3 apply-wiring.py --target <项目根> --apply     # 写入
```

`install.sh` 在装配时自动以 `--apply` 调用；`--no-wiring` 可跳过。

## 幂等与可重放

- AGENTS.md：区块已存在则**按源整段替换**（不新建重复段）；文件不存在则创建；标记单侧存在 → 报 `error` 且**不改文件**。
- `.gitignore`：已含 `.adapter-out` 子串或 `!.adapter-out` 负模式 ⇒ 跳过；文件不存在 ⇒ 不首创（只给建议行）。
- `.pi/settings.json`：只往 `extensions[]` 插一行；结构判读不了 ⇒ 跳过并给出要手加的行。
- **可重放**：重跑 `install.sh`（或本接线器 `--apply`）即对齐。

## 确认门

改 `<项目根>/AGENTS.md`、测试配置、`.gitignore`、`.pi/settings.json` 属 `shared/global-rules.md` §7 的确认门动作；由 `install.sh` 在用户显式安装时执行。

## 回归测试

`atlas/tests/test_project_wiring.py`：验证「置顶注入（BOM / front-matter 之后）/ 存量尾部块迁移到头部 / 幂等 / 缺文件创建 / 区块更新 / dry-run 不写 / 标记不成对与多对报错不改」（RFC-20261126-02）。
