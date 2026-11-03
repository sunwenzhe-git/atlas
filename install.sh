#!/usr/bin/env bash
#
# atlas installer —— 把 atlas 包装配到目标项目。
#
# 用法：
#   bash install.sh [--target <项目根>] [--update] [--force] [--dry-run] [--no-skill] [--no-patch] [--no-wiring]
#                   [--assets-root <dir>] [--adr-dir <dir>]
#
# 装配行为：
#   1. 整包装配到 <目标>/.atlas/（shared / rings / apply / templates / adapters /
#      validators / patches / tests / _support / extensions）。.atlas/ 属包产物：白名单子目录默认刷新，
#      `.atlas/runs/`（运行态：E2E 汇总 / check 事件 / write-claims）保留不删。
#   2. 每个 skills/atlas-*/ 以一个瘦桩 SKILL.md 装到各平台 skill 目录。
#   3. 清理历史遗留的单入口 skill（<平台>/skills/atlas）。
#   4. 建资产根骨架（默认 product/；已有内容永不覆盖）。
#   5. 应用 .trellis/workflow.md 的 Plan 挂载补丁（atlas apply；锚点幂等，
#      用 --no-patch 跳过）。
#   6. 项目接线：AGENTS.md 的 atlas 指针段 + .trellis/config.yaml 的 after_archive
#      hook（幂等，用 --no-wiring 跳过）。
#      第 5、6 步属 global-rules §7 确认门动作，由本次显式安装触发。
#
# 模式：
#   --update: 刷新已有项目的 .atlas/ 资产与平台 Skills 瘦桩（要求目标已初始化 .atlas/）。
#   --assets-root / --adr-dir: 首次安装选择项目级资产根（默认 product/）与可选 ADR 根；
#      写入项目根 atlas.config.yaml（git 跟踪）。--update 只读配置，不重新选择。
#   --update 的触点守卫：已跟踪触点存在未提交改动 ⇒ 拒（--force 越过）；触点整目录
#   未跟踪（如 .atlas/ 不入库）⇒ WARN 放行、不消费 --force（覆盖自负，先回灌更稳）。
#
# 幂等：.atlas/ 与 skill 瘦桩默认刷新（属包下发物，用 --no-skill 跳过 skill）；
#       资产根下的既有内容永不覆盖；workflow.md 补丁只做锚点插入、重跑即恢复；
#       AGENTS.md 指针段与 config.yaml hook 就地更新、重跑即恢复。
#

# 2026-11-03（RFC-20261103-04 第 4 步）：装配逻辑已单源到 install.py（Python）。
# 本文件退化为薄 wrapper：保留头部用法说明（-h 语义不变），所有行为由 install.py 承载。
# 回滚 = 还原本文件为 bash 实现版（git 历史有完整拷贝）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/install.py" ]; then
  echo "错误：源包缺少 install.py（装配单源），无法继续装配。" >&2
  exit 1
fi

exec "${ATLAS_PYTHON:-python3}" "$SCRIPT_DIR/install.py" "$@"
