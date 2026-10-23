#!/usr/bin/env bash
#
# atlas installer —— 把 atlas 包装配到目标项目。
#
# 用法：
#   bash install.sh [--target <项目根>] [--update] [--force] [--dry-run] [--no-skill] [--no-patch] [--no-wiring]
#
# 装配行为：
#   1. 整包装配到 <目标>/.atlas/（shared / rings / apply / templates / adapters /
#      validators / patches / tests）。.atlas/ 属包产物：白名单子目录默认刷新，
#      `.atlas/runs/`（运行态：E2E 汇总 / check 事件 / write-claims）保留不删。
#   2. 每个 skills/atlas-*/ 以一个瘦桩 SKILL.md 装到各平台 skill 目录。
#   3. 清理历史遗留的单入口 skill（<平台>/skills/atlas）。
#   4. 建 product/ 骨架（已有内容永不覆盖）。
#   5. 应用 .trellis/workflow.md 的 Plan 挂载补丁（atlas apply；锚点幂等，
#      用 --no-patch 跳过）。
#   6. 项目接线：AGENTS.md 的 atlas 指针段 + .trellis/config.yaml 的 after_finish
#      hook（幂等，用 --no-wiring 跳过）。
#      第 5、6 步属 global-rules §7 确认门动作，由本次显式安装触发。
#
# 模式：
#   --update: 刷新已有项目的 .atlas/ 资产与平台 Skills 瘦桩（要求目标已初始化 .atlas/）。
#   --update 的触点守卫：已跟踪触点存在未提交改动 ⇒ 拒（--force 越过）；触点整目录
#   未跟踪（如 .atlas/ 不入库）⇒ WARN 放行、不消费 --force（覆盖自负，先回灌更稳）。
#
# 幂等：.atlas/ 与 skill 瘦桩默认刷新（属包下发物，用 --no-skill 跳过 skill）；
#       product/ 下的既有内容永不覆盖；workflow.md 补丁只做锚点插入、重跑即恢复；
#       AGENTS.md 指针段与 config.yaml hook 就地更新、重跑即恢复。
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET=""
IS_UPDATE=0
FORCE=0
DRY_RUN=0
INSTALL_SKILL=1
INSTALL_PATCH=1
INSTALL_WIRING=1

while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --update) IS_UPDATE=1; shift ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --no-skill) INSTALL_SKILL=0; shift ;;
    --no-patch) INSTALL_PATCH=0; shift ;;
    --no-wiring) INSTALL_WIRING=0; shift ;;
    -h|--help)
      sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

[ -n "$TARGET" ] || TARGET="$(pwd)"
TARGET="$(cd "$TARGET" && pwd)"

say() { printf '%s\n' "$*"; }
run() { if [ "$DRY_RUN" -eq 1 ]; then say "  [dry-run] $*"; else "$@"; fi; }

# 当前源包内容摘要（F55 守卫双摘要可见化用；算法单点 = scripts/pkg_digest.py，
# 与 `.atlas/VERSION` 戳、atlas_check 装配版本门同源）。任何失败（python3 缺席 /
# EmptyAssembly）输出空 ⇒ 调用侧按「摘要不可核」说清，不虚报一致性。
compute_src_digest() {
  python3 - "$1" 2>/dev/null <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from pkg_digest import digest
try:
    print(digest(Path(sys.argv[1])))
except Exception:
    pass
PY
}

# ---------------------------------------------------------------- 前置检查

if [ "$IS_UPDATE" -eq 1 ]; then
  say "atlas updater (刷新工程线束)"
else
  say "atlas installer"
fi
say "  包目录 : $SCRIPT_DIR"
say "  目标项目: $TARGET"
say ""

if [ "$IS_UPDATE" -eq 1 ] && [ ! -d "$TARGET/.atlas" ]; then
  say "错误：目标项目尚未装配 atlas（$TARGET/.atlas 不存在），无法执行 update。"
  say "      如需首次装配，请执行: atlas init"
  exit 1
fi

if [ ! -d "$TARGET/.trellis" ]; then
  if command -v trellis >/dev/null 2>&1; then
    say "提示：目标项目尚未初始化 Trellis，尝试自动执行 trellis init..."
    (cd "$TARGET" && trellis init) || true
  fi
fi

if [ ! -d "$TARGET/.trellis" ]; then
  say "警告：目标项目没有 .trellis/（未初始化 Trellis）。"
  say "      atlas 的需求级衔接依赖 Trellis，请先在目标项目执行 trellis init。"
  say "      （如果未安装，请执行: npm i -g @mindfoldhq/trellis）"
  if [ "$FORCE" -ne 1 ]; then
    say "      如确认要继续，请加 --force。"
    exit 1
  fi
fi

# ── 临时守卫（2026-09-28 加；待回灌清单清零且无在路改造批后整段删除，连同 AGENTS.md §3 提醒行）──
# 背景：副本先改、源包后回灌是常态（ATLAS-UPSTREAM 规则）；分歧窗口内对已装配过的
# 目标重跑 install，第 1 步的 rm -rf 会用旧源包整包覆盖——副本侧已落地改动被冲掉
# （实例：原型环移除批在路，vault atlas/3508 §92）。
if [ "$DRY_RUN" -eq 0 ] && [ -d "$TARGET/.atlas" ] && [ "${ATLAS_ALLOW_OVERWRITE:-0}" != "1" ] && [ "$IS_UPDATE" -ne 1 ]; then
  say "错误：目标已装配过 atlas（$TARGET/.atlas 存在），本次运行会整包覆盖。"
  say "      副本侧可能有未回灌的本地改动（见目标项目 ATLAS-UPSTREAM.md）；覆盖会回退副本侧已落地改动。"
  say "      - 明知回退、仍要覆盖：ATLAS_ALLOW_OVERWRITE=1 重新运行"
  say "      - 给新项目开户：换一个没有 .atlas/ 的 --target"
  say "      - 只想预览改动：加 --dry-run"
  exit 1
fi

# ── 触点脏树守卫（F34，2026-10-15；F55 两语义拆分，2026-10-16 issue #22 / D93）──
# R6 现场教训：并行终端与沙箱会话共写仓库时，update 的 rm -rf 会把副本侧未提交的
# 线束改动一并卷走（提交归属被污染）。守卫必须位于整包拷贝（rm -rf）**之前**。
# F55（D93）：守卫读 porcelain **状态列**，分类后分两个真语义——已跟踪触点上的
# 未提交改动（git 有基线可护，覆盖丢真改动）⇒ 拒，--force 越过；触点整目录未跟踪
# （porcelain 折叠成 `?? .atlas/`，git 根本无基线可护，是「包产物不入库」的合法
# 形态）⇒ 不构成「脏」：WARN 放行 + 双摘要可见化（副本版本戳 ⇔ 当前源包摘要）。
# 旧路径只看路径列 ⇒ 未跟踪在场被折成 `.atlas/*` 命中 ⇒ 守卫恒拒，--force 被逼成
# 常规、守卫退化。两桶皆非空 ⇒ 拒优先，拒绝不被可放行项遮蔽。
if [ "$IS_UPDATE" -eq 1 ] && [ "$DRY_RUN" -eq 0 ] && command -v git >/dev/null 2>&1; then
  if git -C "$TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    DIRTY_TOUCH=""
    UNTRACKED_TOUCH=""
    while IFS= read -r raw; do
      [ -z "$raw" ] && continue
      raw_path="${raw:3}"
      case "$raw_path" in
        .atlas/*|.atlas|.trellis/workflow.md|.trellis/config.yaml|AGENTS.md)
          case "${raw:0:2}" in
            \?\?) UNTRACKED_TOUCH="$UNTRACKED_TOUCH $raw_path" ;;
            *) DIRTY_TOUCH="$DIRTY_TOUCH $raw_path" ;;
          esac ;;
      esac
    done < <(git -C "$TARGET" status --porcelain 2>/dev/null)
    if [ -n "$DIRTY_TOUCH" ]; then
      if [ "$FORCE" -eq 1 ]; then
        say "（--force：感知到装配触点未提交改动：${DIRTY_TOUCH} —— 整包覆盖自负）"
        if [ -n "$UNTRACKED_TOUCH" ]; then
          say "（另有未跟踪项：${UNTRACKED_TOUCH} —— git 对其无改动基线，覆盖自负）"
        fi
      else
        say "错误：装配触点存在未提交改动（${DIRTY_TOUCH}）；--update 的整包覆盖会冲掉"
        say "      副本侧未回灌的线束改动（含 .atlas/ 与指针文件）。"
        say "      - 先提交或 stash 后重跑"
        say "      - 明知覆盖、仍要继续：加 --force"
        exit 1
      fi
    elif [ -n "$UNTRACKED_TOUCH" ]; then
      COPY_STAMP=""
      if [ -f "$TARGET/.atlas/VERSION" ]; then
        IFS= read -r COPY_STAMP < "$TARGET/.atlas/VERSION" 2>/dev/null || true
      fi
      SRC_DIGEST="$(compute_src_digest "$SCRIPT_DIR" || true)"
      say "  [WARN] 装配触点存在未跟踪项：${UNTRACKED_TOUCH}——git 对未跟踪触点无改动基线可保护，"
      if [ -n "$COPY_STAMP" ] && [ -n "$SRC_DIGEST" ]; then
        if [ "$COPY_STAMP" = "$SRC_DIGEST" ]; then
          say "         本副本与当前源包一致（${COPY_STAMP}，无年轮差）；整包刷新照常进行。"
        else
          say "         本副本（${COPY_STAMP}）与当前源包（${SRC_DIGEST}）不一致——覆盖自负。"
        fi
      else
        say "         摘要不可核（副本无 .atlas/VERSION 或源包摘要不可算）——覆盖自负。"
      fi
      say "         副本侧若有未回灌的本地改动，覆盖即丢失：先按 ATLAS-UPSTREAM.md 回灌"
      say "         （scripts/backflow.py 三态对账）再刷新更稳。"
    fi
  fi
fi

# 探测目标项目实际使用的平台目录
PLATFORM_DIRS=()
if [ -d "$TARGET/.agents/skills" ]; then PLATFORM_DIRS+=(".agents/skills"); fi
if [ -d "$TARGET/.claude/skills" ]; then PLATFORM_DIRS+=(".claude/skills"); fi
if [ -d "$TARGET/.codex" ]; then PLATFORM_DIRS+=(".codex/skills"); fi

if [ "${#PLATFORM_DIRS[@]}" -eq 0 ]; then
  say "警告：未探测到任何平台 skill 目录，默认创建 .agents/skills/。"
  PLATFORM_DIRS=(".agents/skills")
fi

# ---------------------------------------------------------------- 1. 整包 → .atlas/

say "[1/6] 装配 atlas 包到 .atlas/"
ATLAS_DEST="$TARGET/.atlas"
for pkg_dir in shared rings apply scripts templates adapters validators patches tests _support extensions; do
  run rm -rf "$ATLAS_DEST/$pkg_dir"
done
run rm -f "$ATLAS_DEST/LICENSE"
run mkdir -p "$ATLAS_DEST"
for pkg_dir in shared rings apply scripts templates adapters validators patches tests _support extensions; do
  if [ -d "$SCRIPT_DIR/$pkg_dir" ]; then
    run cp -R "$SCRIPT_DIR/$pkg_dir" "$ATLAS_DEST/$pkg_dir"
    say "      -> .atlas/$pkg_dir"
  fi
done

if [ -f "$SCRIPT_DIR/LICENSE" ]; then
  run cp "$SCRIPT_DIR/LICENSE" "$ATLAS_DEST/LICENSE"
fi

# ---------------------------------------------------------------- 2. skill 瘦桩

if [ "$INSTALL_SKILL" -eq 1 ]; then
  say "[2/6] 装配 skill 瘦桩"
  SKILL_SRCS=("$SCRIPT_DIR"/skills/*)
  if [ ! -e "${SKILL_SRCS[0]}" ]; then
    say "      未发现 skills/*，跳过。"
  else
    for skill_src in "${SKILL_SRCS[@]}"; do
      [ -d "$skill_src" ] || continue
      name="$(basename "$skill_src")"
      for rel in "${PLATFORM_DIRS[@]}"; do
        dest="$TARGET/$rel/$name"
        run rm -rf "$dest"
        run mkdir -p "$TARGET/$rel"
        run cp -R "$skill_src" "$dest"
      done
      say "      -> ${name}（${#PLATFORM_DIRS[@]} 个平台）"
    done
  fi

  say "[3/6] 清理历史与退役 skill"
  for rel in "${PLATFORM_DIRS[@]}"; do
    legacy="$TARGET/$rel/atlas"
    if [ -e "$legacy" ]; then
      run rm -rf "$legacy"
      say "      - 移除 $rel/atlas（旧单入口）"
    fi
    # 退役环的瘦桩：源包 skills/ 已无此项 ⇒ install 不再下发，已装配过的项目须清掉，
    # 否则平台里会留一个指向已删契约的 skill（实例：E1 原型环退役 ⇒ atlas-prototype）。
    for stale in "$TARGET/$rel"/atlas-*; do
      [ -d "$stale" ] || continue
      stale_name="$(basename "$stale")"
      if [ ! -d "$SCRIPT_DIR/skills/$stale_name" ]; then
        run rm -rf "$stale"
        say "      - 移除 ${rel}/${stale_name}（源包已无此 skill）"
      fi
    done
  done

  # agent 配置（如 atlas-reviewer）
  if [ -d "$SCRIPT_DIR/agents" ]; then
    for agent_src in "$SCRIPT_DIR"/agents/*.md; do
      [ -f "$agent_src" ] || continue
      agent_name="$(basename "$agent_src")"
      for agent_base in ".agents" ".claude/agents" ".codex/agents"; do
        if [ "$agent_base" = ".agents" ] || [ -d "$TARGET/$(dirname "$agent_base")" ]; then
          run mkdir -p "$TARGET/$agent_base"
          run cp "$agent_src" "$TARGET/$agent_base/$agent_name"
        fi
      done
      say "      -> agent ${agent_name}"
    done
  fi
else
  say "[2/6] 跳过 skill（--no-skill）"
  say "[3/6] 跳过 skill 清理（--no-skill）"
fi

# ---------------------------------------------------------------- 4. 骨架

say "[4/6] 建立骨架"
for d in \
  ".trellis/spec/structure/domains" \
  ".trellis/spec/structure/global" \
  "product/e2e/cases"
do
  run mkdir -p "$TARGET/$d"
  [ -f "$TARGET/$d/.gitkeep" ] || run touch "$TARGET/$d/.gitkeep"
done

if [ -f "$TARGET/product/stack-profile.yaml" ]; then
  say "      = product/stack-profile.yaml 已存在，保留"
else
  run cp "$SCRIPT_DIR/templates/stack-profile.yaml" "$TARGET/product/stack-profile.yaml"
  say "      + product/stack-profile.yaml（草稿，需人工确认）"
fi

# ---------------------------------------------------------------- 5. Trellis workflow 补丁（遍历 patches/*/）

# 泛化（2026-10-04 回灌 #161/#162）：不再硬编码 workflow-plan-apply——遍历 patches/ 下
# 每个含 spec.json + apply-patches.py 的补丁包依序应用，新增包随装配自动生效。
apply_patch_pkg() {  # $1 = 包目录（绝对路径）
  local dir="$1" name out SUM
  name=$(basename "$dir")
  if [ "$DRY_RUN" -eq 1 ]; then
    run python3 "$dir/apply-patches.py" --target "$TARGET" --spec "$dir/spec.json"
    return
  fi
  if OUT=$(python3 "$dir/apply-patches.py" --target "$TARGET" --spec "$dir/spec.json" --apply 2>&1); then
    printf '%s\n' "$OUT" | sed 's/^/      | /'
    SUM=$(printf '%s' "$OUT" | grep -o '合计：.*' || true)
    case "$SUM" in
      *"applied=0 replaced=0 upgraded=0"*)
        say "      = ${name}：.trellis/workflow.md 已是最新（无改动；${SUM}）" ;;
      *)
        say "      -> .trellis/workflow.md（${name}；${SUM}）" ;;
    esac
  else
    printf '%s\n' "$OUT" | sed 's/^/      | /' || true
    say "      ⚠ ${name} 存在 error（锚点未命中，Trellis 模板可能已变）——不阻断装配。"
  fi
}

if [ "$INSTALL_PATCH" -eq 1 ]; then
  say "[5/6] 应用 Trellis workflow 补丁（patches/*/）"
  FOUND_ANY=0
  for spec in "$ATLAS_DEST"/patches/*/spec.json; do
    [ -f "$spec" ] || continue
    pkg_dir="${spec%/*}"
    [ -f "$pkg_dir/apply-patches.py" ] || continue
    # dry-run 时不实际拷贝，回退到源包目录，使补丁计划照样可见
    if [ "$DRY_RUN" -eq 1 ] && [ -f "$SCRIPT_DIR/patches/$(basename "$pkg_dir")/apply-patches.py" ]; then
      pkg_dir="$SCRIPT_DIR/patches/$(basename "$pkg_dir")"
    fi
    FOUND_ANY=1
    apply_patch_pkg "$pkg_dir"
  done
  [ "$FOUND_ANY" -eq 1 ] || say "      未发现含 apply-patches.py 的补丁包，跳过。"
else
  say "[5/6] 跳过 workflow 补丁（--no-patch）"
fi

# ---------------------------------------------------------------- 6. 项目接线

WIRING_DIR="$ATLAS_DEST/patches/project-wiring"
# dry-run 时不实际拷贝，回退到源包目录，使接线计划照样可见
if [ ! -f "$WIRING_DIR/apply-wiring.py" ] && [ -f "$SCRIPT_DIR/patches/project-wiring/apply-wiring.py" ]; then
  WIRING_DIR="$SCRIPT_DIR/patches/project-wiring"
fi
if [ "$INSTALL_WIRING" -eq 1 ]; then
  say "[6/6] 项目接线（AGENTS.md 指针 + after_finish hook）"
  if [ -f "$WIRING_DIR/apply-wiring.py" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      run python3 "$WIRING_DIR/apply-wiring.py" --target "$TARGET"
    else
      if python3 "$WIRING_DIR/apply-wiring.py" --target "$TARGET" --apply; then
        say "      -> AGENTS.md（atlas 指针段）+ .trellis/config.yaml（after_finish hook）"
      else
        say "      ⚠ 接线存在 error——不阻断装配（见上）。"
      fi
    fi
  else
    say "      未发现 patches/project-wiring/apply-wiring.py，跳过。"
  fi
else
  say "[6/6] 跳过项目接线（--no-wiring）"
fi

# ---------------------------------------------------------------- 图谱后端探测（可选能力）

# profile 声明了 graph.backend ⇒ 探测 cgc（缺 = 显式 WARN，不阻断——可选能力，
# 图谱消费者运行时按「not_ready / 响亮降级」三态处理；契约见 shared/stack-profile.md §2）。
if [ -f "$TARGET/product/stack-profile.yaml" ] && [ "$DRY_RUN" -eq 0 ]; then
  GRAPH_BACKEND="$(python3 - "$TARGET/product/stack-profile.yaml" <<'PY'
import re, sys
sec = None
for raw in open(sys.argv[1], encoding="utf-8"):
    line = re.sub(r"\s+#.*$", "", raw.rstrip())
    s = line.strip()
    if not s:
        continue
    if not line[:1].isspace():
        sec = s[:-1].strip() if s.endswith(":") else None
    elif sec == "graph":
        m = re.match(r"^\s*backend:\s*(\S+)", line)
        if m:
            print(m.group(1).strip("'\""))
PY
)"
  if [ -n "$GRAPH_BACKEND" ]; then
    say ""
    say "图谱后端探测（profile 声明 backend=${GRAPH_BACKEND}）"
    if [ "$GRAPH_BACKEND" != "cgc" ]; then
      say "  [WARN] 未知后端 ${GRAPH_BACKEND}（允许：cgc）——图谱消费者将显式报错"
    elif command -v cgc >/dev/null 2>&1; then
      say "  [OK]   cgc 可用（$(cgc --version 2>&1 | tail -1)）"
      say "      首次消费前如卡在索引，先做一次文法缓存预热（GitHub 资产直连不通时挂代理）："
      say "      https_proxy=http://127.0.0.1:7897 python3 -c \"from tree_sitter_language_pack import download; download(['python','typescript','javascript','tsx','bash','java'])\""
    else
      say "  [WARN] cgc 未安装——图谱消费者将显式 not_ready / 降级（pipx/uv tool install codegraphcontext）"
    fi
  fi
fi

# ---------------------------------------------------------------- 自检

say ""
say "自检"
FAIL=0
check() {
  if [ "$DRY_RUN" -eq 1 ]; then say "  [dry-run] check $1"; return; fi
  if [ -e "$2" ]; then say "  [OK]   $1"; else say "  [FAIL] $1 ($2)"; FAIL=1; fi
}

check "共享契约" "$ATLAS_DEST/shared/global-rules.md"
check "stack-profile 契约" "$ATLAS_DEST/shared/stack-profile.md"
check "单一真相源契约" "$ATLAS_DEST/shared/single-source.md"
check "布局契约" "$ATLAS_DEST/shared/layout.md"
check "门登记表" "$ATLAS_DEST/shared/gates.md"
check "收口清单" "$ATLAS_DEST/shared/closeout.md"
check "独立审查骨架契约" "$ATLAS_DEST/shared/independent-review.md"
check "structure 环契约" "$ATLAS_DEST/rings/structure/reference.md"
check "prd 环契约" "$ATLAS_DEST/rings/prd/reference.md"
check "e2e 环契约" "$ATLAS_DEST/rings/e2e/reference.md"
check "apply 契约" "$ATLAS_DEST/apply/reference.md"
check "workflow 补丁应用器" "$ATLAS_DEST/patches/workflow-plan-apply/apply-patches.py"
check "校验器 validate_structure" "$ATLAS_DEST/validators/validate_structure.py"
check "校验器 validate_stack_profile" "$ATLAS_DEST/validators/validate_stack_profile.py"
check "校验器 validate_prd" "$ATLAS_DEST/validators/validate_prd.py"
check "校验器 validate_testids" "$ATLAS_DEST/validators/validate_testids.py"
check "校验器 validate_e2e_index" "$ATLAS_DEST/validators/validate_e2e_index.py"
check "校验器 validate_design_exemptions" "$ATLAS_DEST/validators/validate_design_exemptions.py"
check "校验器 validate_e2e_mocks" "$ATLAS_DEST/validators/validate_e2e_mocks.py"
check "校验器 validate_ac_alignment" "$ATLAS_DEST/validators/validate_ac_alignment.py"
check "校验器 validate_adr" "$ATLAS_DEST/validators/validate_adr.py"
check "校验器 validate_walkthrough" "$ATLAS_DEST/validators/validate_walkthrough.py"
check "E2E 脚本生成器" "$ATLAS_DEST/scripts/gen_e2e_scripts.py"
check "结构事实刷新器" "$ATLAS_DEST/scripts/refresh_structure.py"
check "testid 薄桩生成器" "$ATLAS_DEST/scripts/gen_testid_stub.py"
check "审查输入清单生成器" "$ATLAS_DEST/scripts/make_review_inputs.py"
check "变异证明工具" "$ATLAS_DEST/scripts/mutation_proof.py"
check "atlas 自检器" "$ATLAS_DEST/scripts/atlas_check.py"
check "E2E 评审控制台" "$ATLAS_DEST/scripts/e2e_console.py"
check "控制台静态资源" "$ATLAS_DEST/templates/e2e/console/index.html"
check "适配器脚手架" "$ATLAS_DEST/adapters/_scaffold.py"
check "适配器指南" "$ATLAS_DEST/adapters/README.md"
check "图谱后端隔离层" "$ATLAS_DEST/adapters/_graph.py"
check "影响面基准报告器" "$ATLAS_DEST/scripts/impact_report.py"
check "回灌助手" "$ATLAS_DEST/scripts/backflow.py"
check "收口派生器" "$ATLAS_DEST/scripts/closeout_derive.py"
check "写面 claim 仲裁" "$ATLAS_DEST/scripts/write_claim.py"
check "共享内核（模块加载器）" "$ATLAS_DEST/_support/siblings.py"
check "共享内核（profile 解析）" "$ATLAS_DEST/_support/stack_profile.py"
check "共享内核（用例块解析）" "$ATLAS_DEST/_support/case_block.py"
check "共享内核（手工走查块解析）" "$ATLAS_DEST/_support/manual_block.py"
check "共享内核（用例 ID 文法）" "$ATLAS_DEST/_support/case_id.py"
check "共享内核（node 运行器判据）" "$ATLAS_DEST/_support/pw_runner.py"
check "共享内核（base query 转发）" "$ATLAS_DEST/_support/url_merge.py"
check "共享内核（审查策略单源）" "$ATLAS_DEST/_support/review_policy.py"
check "pi 宿主扩展" "$ATLAS_DEST/extensions/pi.ts"
check "结构模板" "$ATLAS_DEST/templates/structure/_meta.json"
check "PRD 模板" "$ATLAS_DEST/templates/prd/domain.md"
check "E2E 模板" "$ATLAS_DEST/templates/e2e/e2e-index.md"
check "ADR 模板" "$ATLAS_DEST/templates/adr/template.md"
check "审查指引模板" "$ATLAS_DEST/templates/reviews/README.md"
check "product/stack-profile" "$TARGET/product/stack-profile.yaml"
check "structure spec 根" "$TARGET/.trellis/spec/structure"
check "e2e 用例分片目录" "$TARGET/product/e2e/cases"

if [ "$INSTALL_PATCH" -eq 1 ] && [ "$DRY_RUN" -ne 1 ] && [ -f "$TARGET/.trellis/workflow.md" ]; then
  if grep -q "atlas:apply:plan-step-1-6" "$TARGET/.trellis/workflow.md"; then
    say "  [OK]   Plan 挂载补丁（atlas apply）"
  else
    say "  [WARN] Plan 挂载补丁未生效（workflow.md 锚点可能已变；见 patches/workflow-plan-apply/README.md）"
  fi
fi

if [ "$INSTALL_WIRING" -eq 1 ] && [ "$DRY_RUN" -ne 1 ]; then
  if [ -f "$TARGET/AGENTS.md" ] && grep -q "<!-- ATLAS:START -->" "$TARGET/AGENTS.md"; then
    say "  [OK]   AGENTS.md atlas 指针段"
  else
    say "  [WARN] AGENTS.md atlas 指针段未生效（见 patches/project-wiring/README.md）"
  fi
  if [ -f "$TARGET/.trellis/config.yaml" ] && grep -q "refresh_structure.py" "$TARGET/.trellis/config.yaml"; then
    say "  [OK]   after_finish hook（refresh_structure）"
  else
    say "  [WARN] after_finish hook 未生效（见 patches/project-wiring/README.md）"
  fi
fi

if [ "$INSTALL_SKILL" -eq 1 ] && [ "$DRY_RUN" -ne 1 ]; then
  first_platform="${PLATFORM_DIRS[0]}"
  for skill_src in "$SCRIPT_DIR"/skills/*; do
    [ -d "$skill_src" ] || continue
    name="$(basename "$skill_src")"
    entry="$TARGET/$first_platform/$name/SKILL.md"
    check "skill $name" "$entry"
    if [ -f "$entry" ] && ! grep -q "^name: $name$" "$entry"; then
      say "  [FAIL] $name SKILL.md frontmatter 的 name 与目录名不符"; FAIL=1
    fi
  done
fi

say ""
if [ "$FAIL" -ne 0 ]; then
  say "装配失败，见上面 [FAIL]。"
  exit 1
fi

# P3 装配版本戳（2026-10-05）：源包内容摘要落 <target>/.atlas/VERSION，副本侧
# atlas_check「装配版本」行周期复核——不一致 ⇒ WARN（源包已前进/落后，重装前先回灌对账）。
# F54（D92，2026-10-16 issue #21）：落戳挂 DRY_RUN 闸——全脚本其余写盘都经 run() /
# DRY_RUN 判据，唯独这一处是裸 heredoc ⇒ `--update --dry-run` 一次（此时守卫被预览
# 语义放行、载荷一文件未拷，戳却已被更新为源包当前摘要）+ 一次被守卫拒住的真跑 =
# 副本「戳新 / 内容旧」，被装配版本门（自写自读闭环）报成 ok「一致」。顺带关闭同族
# 面：旧路径干跑且源包新装的 stamp_file 含 mkdir ⇒ 全新 target 干跑会残留
# <target>/.atlas/，卡住随后的真首装（临时守卫判「已装配过」恒拒）。
if [ "$DRY_RUN" -eq 1 ]; then
  say "  [dry-run] 装配版本戳（未落盘：干跑不产生装配态变更）"
else
  if OUT="$(python3 - "$SCRIPT_DIR" "$TARGET/.atlas/VERSION" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from pkg_digest import stamp_file  # noqa: E402
print(stamp_file(Path(sys.argv[1]), Path(sys.argv[2])))
PY
)"; then
    say "  [ok] .atlas/VERSION 装配版本戳（${OUT}）"
  else
    # 硬错而非 WARN（F37，2026-10-15）：落戳失败 = 装配集为空（摘要算不出来）或脚本缺失。
    # 「装配 0 文件」不得被记成一次合法装配，且 WARN 会让后续步骤照常往下走。
    say "  [FAIL] 版本戳落盘失败：装配集为空或 pkg_digest 不可用 ⇒ 装配态无法对账。"
    say "         诊断：python3 \"$SCRIPT_DIR/scripts/pkg_digest.py\" \"$SCRIPT_DIR\""
    exit 1
  fi
fi

# 首建提示（2026-10-15 三易其稿，保留最终口径与理由）：
#   一稿问题：①「确认 product/stack-profile.yaml」读起来像要人肉改 YAML，而画像的确认门是
#     Agent 带用户逐项过（global-rules §7）；② 只给全新项目的全量环入口，存量项目开户时
#     无从下手；③ 挂着已退役环的历史括注（对首次安装者纯噪声）。
#   二稿问题：写了「大白话（= atlas-apply adopt）」这种**等号承诺** —— 那句话只是**意图**，
#     模式由 Agent 选；装配过的仓库里它还容易被判成「已接入」而根本不开户 ⇒ 确定性入口
#     （`/atlas-apply <模式>`）上主句，大白话降为可选说法。
#   **终稿（用户定稿）**：只留「首次开户（二选一）」这一段 —— 编号、"下一步"导语、
#     「装配 ≠ 开户」状态注、以及「接需求走 Trellis Plan」那条，全部砍掉。
#     状态注没丢，只是**换了归属**：它的读者是 Agent 与人（读文档时），不是刚装完盯着终端的人 ——
#     现由 AGENTS.md 指针段 / `/atlas status` / README / 存量接入指南 / `atlas apply` 帮助承载。
#   两条入口都列，并按目标是否已有源码痕迹把更可能的那条排在前面（只是提示，真形态由
#   Agent 与用户核对的 origin 落定）。
if [ "$IS_UPDATE" -eq 1 ]; then
  say "刷新完成。"
  say ""
  say "项目工程线束与各平台 Skills 瘦桩已对账刷新为最新版本。"
else
  FIRST_RUN_MARK=""
  for marker in package.json requirements.txt pyproject.toml go.mod Cargo.toml pom.xml build.gradle composer.json Gemfile src app pages frontend backend web mobile; do
    if [ -e "$TARGET/$marker" ]; then FIRST_RUN_MARK="$marker"; break; fi
  done

  say "装配完成。"
  say ""
  say "首次开户（二选一）："
  say "存量项目 → /atlas-apply adopt —— 只登记既有结构基线 + 开户最小集："
  say "           不重写老 PRD、不为老页面补历史用例。"
  say "全新项目 → /atlas-apply all —— structure → prd → e2e 逐环全量。"
  if [ -n "$FIRST_RUN_MARK" ]; then
    say "（检测到 ${FIRST_RUN_MARK}：看起来是前者；也可以只说「帮我把这个项目接入 Atlas 工作流」）"
  else
    say "（未检测到既有源码：看起来是后者；也可以只说「跑一下三环全量构建，建立应然基线」）"
  fi
  say "Agent 会先带你核对 product/stack-profile.yaml（origin / apps / role / adapters）"
  say "再落盘；占位符替换前 atlas check 判 FAIL 属预期，不是装坏了。"
fi
