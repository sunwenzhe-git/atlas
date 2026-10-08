# patches/project-wiring

把 atlas 的**入口指针**与**收口 hook** 幂等写进目标项目，让新项目的 agent 一开会话就知道「本项目用 atlas、契约在哪、需求级怎么走」。

补的是两处此前靠手工、且会被 `trellis update` 冲掉的接线（`install.sh` 原本不碰它们）：

| # | 接线 | 落点 | 作用 |
|---|---|---|---|
| A | **AGENTS.md 指针** | `<项目根>/AGENTS.md` 的 `<!-- TRELLIS:END -->` **之后**（`<!-- ATLAS:START/END -->` 区块） | 位于 Trellis 区块外 ⇒ 不被 `trellis update` 覆盖；给出契约路径、skills、需求级 1.6 步、收口门 |
| B | **`after_finish` hook** | `<项目根>/.trellis/config.yaml` | 每个任务 Finish 后跑 `refresh_structure.py --apply` 刷结构事实（决策 D38） |

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
- `config.yaml`：hook 命令已在 → `skipped`；有 `hooks:` 块则并入 `after_finish`，无则末尾新增 `hooks:` 块。
- `.yaml` 写入前做**轻量结构护栏**（不依赖 PyYAML）：顶层 `hooks:` 必须唯一、hook 命令必须存在，否则报 `error` 且不写。
- **可重放**：`trellis update` 冲掉 `config.yaml` 的本地 hook 或 AGENTS.md 指针后，重跑 `install.sh`（或本接线器 `--apply`）即恢复。

## 确认门

改 `<项目根>/AGENTS.md` 与 `.trellis/config.yaml` 属 `shared/global-rules.md` §7 的确认门动作；由 `install.sh` 在用户显式安装时执行。

## 回归测试

`atlas/tests/test_project_wiring.py`：验证「TRELLIS:END 之后插入 / 幂等 / 缺文件创建 / 区块更新 / config 三种落位（无 hooks、有 hooks 无 after_finish、有 after_finish）/ dry-run 不写 / 标记不成对报错不改」。
