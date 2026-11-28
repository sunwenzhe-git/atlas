#!/usr/bin/env bash
#
# atlas installer —— 把 atlas 包装配到目标项目。
#
# 用法：
#   bash install.sh [--target <项目根>] [--update] [--force] [--dry-run] [--no-skill] [--no-wiring]
#                   [--assets-root <dir>] [--adr-dir <dir>]
#
# 装配行为：
#   1. 整包装配到 <目标>/.atlas/（shared / rings / apply / templates / adapters /
#      validators / patches / _support / extensions；RFC-20261114-01 起不含出厂测试目录）。
#      .atlas/ 属包产物：白名单子目录默认刷新，
#      `.atlas/runs/`（运行态：E2E 汇总 / check 事件 / write-claims）保留不删。
#   2. 每个 skills/atlas-*/ 以一个瘦桩 SKILL.md 装到各平台 skill 目录。
#   3. 清理历史遗留的单入口 skill（<平台>/skills/atlas）。
#   4. 建资产根与执行层骨架（默认 product/；已有内容永不覆盖）。
#   5. 项目接线：AGENTS.md 的 atlas 指针段、extractor 测试配置、`.gitignore`、
#      pi 宿主扩展（幂等，用 --no-wiring 跳过）。
#      属 global-rules §7 确认门动作，由本次显式安装触发。
#
# 模式：
#   --update: 刷新已有项目的 .atlas/ 资产与平台 Skills 瘦桩（要求目标已初始化 .atlas/）。
#   --assets-root / --adr-dir: 首次安装选择项目级资产根（默认 product/）与可选 ADR 根；
#      写入项目根 atlas.config.yaml（git 跟踪）。--update 只读配置，不重新选择。
#   --update 的触点守卫：已跟踪触点存在未提交改动 ⇒ 拒（--force 越过）；触点整目录
#   未跟踪（如 .atlas/ 不入库）⇒ WARN 放行、不消费 --force（覆盖自负，先回灌更稳）。
#
# 幂等：.atlas/ 与 skill 瘦桩默认刷新（属包下发物，用 --no-skill 跳过 skill）；
#       资产根下的既有内容永不覆盖；AGENTS.md 指针段与接线触点就地更新、重跑即恢复。
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

# 解释器探测（Git Bash 里 python.org 只提供 python.exe，没有 python3）：
#   ATLAS_PYTHON 显式覆盖 > python3 > python > py -3；都不行 ⇒ fail-closed（exit 2）。
#
# **必须验证候选真的能跑**，不能只看 `command -v`：Windows 上
# `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe` 是应用商店的**别名占位壳**，
# `command -v python3` 命中，但执行时直接以 rc=49 退出且**零输出**（未安装应用时）。
# 只看名字会把「没装 Python」误报成「install.py 莫名失败」（实测 rc=49/无 stderr）。
_atlas_py_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
    >/dev/null 2>&1
}
PY=""
if [ -n "${ATLAS_PYTHON:-}" ]; then
  if _atlas_py_ok "$ATLAS_PYTHON"; then
    PY="$ATLAS_PYTHON"
  else
    echo "错误：ATLAS_PYTHON 指向的解释器不可用或低于 Python 3.10：$ATLAS_PYTHON" >&2
    exit 2
  fi
else
  for cand in python3 python py; do
    command -v "$cand" >/dev/null 2>&1 || continue
    if [ "$cand" = "py" ]; then
      # Windows py launcher：`py -3` 才是选 Python 3 的形态
      if py -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
           >/dev/null 2>&1; then
        exec py -3 "$SCRIPT_DIR/install.py" "$@"
      fi
      continue
    fi
    if _atlas_py_ok "$cand"; then
      PY="$cand"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  echo "错误：未找到可用的 Python 3.10+（试过 python3 / python / py -3）。" >&2
  echo "      若已安装，请用 ATLAS_PYTHON 指定完整路径。" >&2
  exit 2
fi

exec "$PY" "$SCRIPT_DIR/install.py" "$@"
