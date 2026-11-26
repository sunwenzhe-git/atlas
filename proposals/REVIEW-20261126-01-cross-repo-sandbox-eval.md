# 对抗评审记录：`RFC-20261126-03`（跨仓宿主沙箱对照与自进化巡检裁决对齐）

> 评审编号：REVIEW-20261126-01  
> 评审角色：fresh-context 只读对抗评审子 Agent（`cba373a7-1352-400f-a8df-eea351bd7a66`）  
> 目标提案：`proposals/RFC-20261126-03-cross-repo-sandbox-eval-and-patrol-alignment.md`  
> 终审结论：**Round 1 驳回 → v2 修订 → Round 2 通过（零遗留 Blocker / Major）**

---

## Round 1（驳回：4 Blocker + 2 Major）

1. **[Blocker-1] `install.py --no-skill --no-wiring` 假绿**：核查 `install.py:430-438,613-755` 与 `apply-wiring.py` 均只写 `<target>` 不碰 `~/`；默认加 `--no-skill --no-wiring` 会使快车道 `skills/` 与 `agent-pointer.md` 改动从未进入沙箱。
2. **[Blocker-2] `bin/atlas.js` 路由与 `--root` 冲突**：`bin/atlas.js:598-610` 优先执行宿主 `.atlas/scripts/atlas_eval.py` 且注入 `--root <cwd>`，会令采纳仓调用 `atlas eval host` 命中旧脚本并错绑 `--harness-root`。
3. **[Blocker-3] `duty_signals.sh` 源仓自影与噪声**：`atlas/.atlas/runs/check-events.jsonl` 存在 87 行全 `SKIP` 噪声；`atlas-playground` 含 `git_dirty` WIP 行与 `N/A` 耗时行；detached worktree 下 `../atlas-playground` 不可达。
4. **[Blocker-4] `atlas-playground` 现态与历史 `install.py` 边界**：`HEAD=2492b43` 为故意造的 `HOME-DARK-MODE` FAIL 夹具；pre-`479d958` 无 `install.py`。
5. **[Major-1] 双仓 cleanup 泄漏 / `WORKTREE` anti-noop / `check-events` 采集窗口 / Tier A vs B 分离**。
6. **[Major-2] `shared/gates.md` §2.1 锚、`docs/map/` 同步、`proposals/README.md` 路径全覆盖、重写 §2.2 反方与可执行证伪条件**。

---

## Round 2（通过：全部 Blocker/Major 闭环）

- Blocker-1~4 与 Major-1~2 均已在 RFC v2 中实质修正：移除 `--no-skill --no-wiring` 默认屏蔽、修 `bin/atlas.js` `host` 直走 `PKG_ROOT`、`duty_signals.sh` 用 `git-common-dir` 防源仓自影并清洗噪声、`atlas-playground` 锚定 `baseline-post-t5`、补齐双仓统一 `finally` 清理与 `WORKTREE` anti-noop、修正门册 §2.1 与 `docs/map/` 联动。
- **Minor 两条**：① `§2.2` 区分提交前（`HEAD vs WORKTREE`）与提交后（`HEAD~1 vs HEAD`）复现命令；② `proposals/README.md` 补全根级文件车道兜底与 `shared/gates.md` 行数锚检查。已随实施一并处理。
