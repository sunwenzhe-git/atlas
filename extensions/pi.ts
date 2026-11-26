/**
 * Atlas — Pi Agent Extension (atlasharness)
 *
 * 将 Atlas (Project Harness) 与 Pi Agent (Agent Harness) 深度联动的官方扩展。
 * 
 * 核心职责：
 * 1. 注册 `/atlas` 交互命令（/atlas check, /atlas init, /atlas console, /atlas status 等）
 * 2. 状态机感知与提示注入（在 before_agent_start 挂载 Atlas 机器蓝图指引）
 * 3. 交付面安全守卫（在 turn_end 检查是否破坏项目机器契约）
 */

import type {
  ExtensionAPI,
  ExtensionCommandContext,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { Type } from "typebox";

const EXTENSION_NAME = "atlasharness";

// ═══════════════════════════════════════════════════════════════════════════
// Guarded Continuation（GDR PoC P1）——计划契约只读链
//
// 方案：handoff/2026-11-26-atlas-guarded-continuation-plan-v15.md（v16 增量 M1/M2）。
// 边界：父工具经 ctx.executeTool 真实嵌套（P0 已证）；Python 只做契约校验/回执/审计；
// 全部 Python 调用经净化启动器（env -i + python -I -B + 只读 git 包装器）。
// 票据只存扩展内存；持久面仅 .atlas/runs/continuations/{<run_id>/,isolated/<unit>.json}。
// ═══════════════════════════════════════════════════════════════════════════

type GcTicket = {
  unit: string;
  planSha256: string;
  sessionId: string;
  nonce: string;
  expiryMs: number;
  consumed: boolean;
};

type GcObservation = {
  action_index: number;
  action_id: string;
  tool: string;
  child_tool_call_id: string;
  guard_result: boolean;
  guard_refs: string[];
  exit_code: number;
  json_ok: boolean;
  ok: boolean;
  cli_duration_ms: number;
  host_duration_ms: number | null;
  result_sha256: string;
  raw_receipt_sha256: string;
  raw_receipt_path: string;
};

type GcRun = {
  unit: string;
  runId: string;
  sessionId: string;
  parentToolCallId: string;
  planSha256: string;
  phase: "CLAIMED_NO_RUN" | "RUNNING" | "RECORDED";
  observations: GcObservation[];
  // 一次性能力标记：仅父工具即将调用的动作存在（tool_call 授权 + 子 execute 复核）
  nextAction: { index: number; id: string; tool: string; argsHash: string } | null;
};

// 父私有 raw 回执台账：子工具 execute 在返回前预提交；后续钩子改值不可触及（P0 实证）。
const gcRawCommits = new Map<string, { resultSha256: string; fileSha256: string; receiptPath: string }>();
// 子调用授权表：tool_call 钩子登记，子 execute 一次性消费并复核参数哈希。
const gcCapAuth = new Map<string, { tool: string; argsHash: string }>();
// 已签发未消费票据（内存；秘密不落盘）。
const gcTickets = new Map<string, GcTicket>();
// 治理窗口：同一时刻至多一个活跃 run。
let gcActive: GcRun | null = null;
// 待审计任务（agent_settled / session_shutdown 兜底消费）。
const gcPendingAudit: Array<{ unit: string; runId: string; parentToolCallId: string; expectedHash: string }> = [];
// 持久非终态隔离标记恢复面（session_start 重建 ⇒ 默认拒绝模型工具）。
const gcIsolatedUnits = new Set<string>();
// 宿主耗时采集（tool_execution_end）。
const gcHostDurations = new Map<string, number>();
// 只读 git 包装器日志的已消费字节偏移（增量窗口）。
const gcGitLogOffsets = new Map<string, number>();
// P0 实测坑：哈希不得进入被哈希对象。
function gcStable(v: unknown): string {
  if (v === null || v === undefined || typeof v !== "object") return JSON.stringify(v) ?? "null";
  if (Array.isArray(v)) return "[" + v.map(gcStable).join(",") + "]";
  const o = v as Record<string, unknown>;
  return (
    "{" +
    Object.keys(o)
      .filter((k) => o[k] !== undefined && o[k] !== null) // null/undefined 同义缺席（镜像 Python _drop_none）
      .sort()
      .map((k) => JSON.stringify(k) + ":" + gcStable(o[k]))
      .join(",") +
    "}"
  );
}

function gcSha(v: unknown): string {
  return createHash("sha256").update(gcStable(v)).digest("hex");
}

function gcResultHash(result: {
  content?: unknown;
  details?: unknown;
  structuredContent?: unknown;
  isError?: unknown;
}): string {
  return gcSha({
    content: result.content,
    details: result.details,
    structuredContent: result.structuredContent,
    isError: result.isError,
  });
}

function gcMarkerPath(cwd: string, unit: string): string {
  return join(cwd, ".atlas", "runs", "continuations", "isolated", `${unit}.json`);
}

function gcWriteMarker(cwd: string, unit: string, payload: Record<string, unknown>): void {
  const dir = join(cwd, ".atlas", "runs", "continuations", "isolated");
  mkdirSync(dir, { recursive: true });
  const p = gcMarkerPath(cwd, unit);
  const tmp = `${p}.tmp-${randomBytes(4).toString("hex")}`;
  writeFileSync(tmp, JSON.stringify({ unit, ...payload }, null, 2) + "\n");
  renameSync(tmp, p);
}

const GC_TERMINAL_STATES = new Set(["SUCCEEDED", "AUDIT_FAILED", "CLOSED_FAILED", "REVOKED"]);

function gcRunDir(cwd: string, runId: string): string {
  const safe = /^[A-Za-z0-9_-]{1,80}$/.test(runId) ? runId : "";
  if (!safe) throw new Error(`非法 run_id：${runId}`);
  const dir = join(cwd, ".atlas", "runs", "continuations", safe);
  mkdirSync(join(dir, "raw-receipts"), { recursive: true });
  mkdirSync(join(dir, "evidence"), { recursive: true });
  return dir;
}

/** 净化启动器调用（env -i + python -I -B + 只读 git 包装器）。launcher 未冻结 ⇒ fail-closed。 */
function gcLauncher(
  cwd: string,
  gcLog: string,
  scriptPath: string,
  args: string[],
  timeoutMs: number,
): { code: number; stdout: string; stderr: string } {
  const launcher = process.env.ATLAS_GC_LAUNCHER;
  if (!launcher) {
    return { code: 126, stdout: "", stderr: "ATLAS_GC_LAUNCHER 未冻结：P1 需先冻结净化启动器" };
  }
  const res = spawnSync(launcher, [gcLog, scriptPath, ...args], {
    cwd,
    encoding: "utf8",
    timeout: timeoutMs,
  });
  return { code: res.status ?? 126, stdout: res.stdout ?? "", stderr: res.stderr ?? "" };
}

function gcPlanBytes(cwd: string, unit: string): { bytes: Buffer; sha256: string } | null {
  const p = join(cwd, ".atlas", "tasks", unit, "continuation.json");
  if (!existsSync(p)) return null;
  const bytes = readFileSync(p);
  return { bytes, sha256: createHash("sha256").update(bytes).digest("hex") };
}

/** guard 求值：只消费已观察回执（exit_code 谓词固定 ==0；json_ok = 可解析 JSON）。 */
function gcGuardOk(guard: { kind: string; refs?: string[] } | undefined, obs: Map<string, GcObservation>): boolean {
  if (!guard || guard.kind === "always") return true;
  if (guard.kind === "all_of") {
    for (const ref of guard.refs ?? []) {
      const [aid, fact] = ref.split(".");
      const o = obs.get(aid);
      if (!o) return false;
      if (fact === "exit_code" && o.exit_code !== 0) return false;
      if (fact === "json_ok" && !o.json_ok) return false;
    }
    return true;
  }
  return false;
}

/**
 * Python 解释器口径（与 `bin/platform.js` 的 resolvePython 同向，但本文件会被单独
 * 拷到 `.pi/extensions/atlas/index.ts`，不能跨包 require）：Windows 原生没有
 * `python3`（python.org 只装 `python.exe`）；`ATLAS_PYTHON` 可显式覆盖。
 */
const PYTHON = process.env.ATLAS_PYTHON || (process.platform === "win32" ? "python" : "python3");

/**
 * 开户态（2026-10-15 补）：**装配 ≠ 开户**。
 *
 * `atlas init` 只装配线束（`.atlas/` / 资产根骨架（默认 `product/`） / AGENTS.md 指针 / 测试配置）；
 * 「开户」另有产物，且只有该轮真产出才算数：
 *   * `<资产根>/prd/prd.md`                 —— 全局 PRD（`adopt` 最小必填集必产；默认 `product/prd/prd.md`）
 *   * `.atlas/spec/structure/_meta.json` —— 域清单（`structure` 全量的机器视图）
 * 骨架期这两个文件都不存在（目录里只有 `.gitkeep`）⇒ **不能拿「目录非空」当信号**。
 * 「半开通」（只有其一）是常态：开户按产物存在与否**断点续跑**（`apply/reference.md` §1）。
 */
type Onboarding = "none" | "partial" | "done";

const ONBOARDING_LABEL: Record<Onboarding, string> = {
  none: "未开户（装配完成，尚无开户产物）",
  partial: "开户进行中（PRD 与结构事实只有其一）",
  done: "已开户",
};

interface AtlasProjectStatus {
  isAtlasProject: boolean;
  hasStructure: boolean;
  hasStackProfile: boolean;
  onboarding: Onboarding;
  version?: string;
  stackProfileRel: string;
  prdRel: string;
  layoutNote?: string;
}

function layoutValue(cwd: string, key: string, absolute: boolean): string | null {
  const script = join(cwd, ".atlas", "_support", "layout.py");
  if (!existsSync(script)) return null;
  const flag = absolute ? "--print-abs" : "--print";
  const res = spawnSync(PYTHON, [script, "--root", cwd, flag, key], { encoding: "utf8" });
  if (res.status !== 0) return null;
  const out = (res.stdout || "").trim();
  return out || null;
}

function detectAtlasStatus(cwd: string): AtlasProjectStatus {
  const hasAtlasDir = existsSync(join(cwd, ".atlas"));
  const hasConfig = existsSync(join(cwd, "atlas.config.yaml"));
  const stackProfileAbs = layoutValue(cwd, "stack_profile", true)
    ?? join(cwd, "product", "stack-profile.yaml");
  const stackProfileRel = layoutValue(cwd, "stack_profile", false)
    ?? "product/stack-profile.yaml";
  const prdAbs = layoutValue(cwd, "prd", true) ?? join(cwd, "product", "prd");
  const prdRel = layoutValue(cwd, "prd", false) ?? "product/prd";
  const hasStackProfile = existsSync(stackProfileAbs);
  const hasStructure = existsSync(join(cwd, ".atlas", "spec", "structure", "_meta.json"));
  const layoutReady = !hasConfig || layoutValue(cwd, "assets_root", false) !== null;
  const layoutNote = hasConfig && !layoutReady
    ? "自定义布局未解析（Python 缺席 / 旧装配 / 配置非法），按默认 product 判定"
    : undefined;

  // 开户产物 = 上面 Onboarding 注里点名的两个文件
  const hasPrd = existsSync(join(prdAbs, "prd.md"));
  const hasStructureMeta = existsSync(
    join(cwd, ".atlas", "spec", "structure", "_meta.json"),
  );
  const onboarding: Onboarding =
    hasPrd && hasStructureMeta ? "done" : hasPrd || hasStructureMeta ? "partial" : "none";

  let version: string | undefined;
  const versionFile = join(cwd, ".atlas", "VERSION");
  if (existsSync(versionFile)) {
    try {
      version = readFileSync(versionFile, "utf-8").trim().slice(0, 16);
    } catch {
      // ignore
    }
  }

  return {
    isAtlasProject: hasAtlasDir || hasStackProfile,
    hasStructure,
    hasStackProfile,
    onboarding,
    version,
    stackProfileRel,
    prdRel,
    layoutNote,
  };
}

export default function (pi: ExtensionAPI) {
  // ──────────────────────────────────────────────────────────────────────────
  // 1. 注册 /atlas 命令
  // ──────────────────────────────────────────────────────────────────────────

  pi.registerCommand("atlas", {
    description: "Atlas Project Harness 控制台与工作流管理",
    getArgumentCompletions: async (prefix: string) => {
      const subcommands = [
        { value: "check", label: "check", description: "运行 Atlas 确定性门禁体检" },
        { value: "status", label: "status", description: "查看当前工作区 Atlas 状态与结构基线" },
        { value: "console", label: "console", description: "打开可视化 E2E 走查控制台" },
        { value: "init", label: "init", description: "在当前项目装配 Atlas 工作流" },
        { value: "report", label: "report", description: "上报流水线设计缺陷或规则冲突" },
        { value: "change", label: "change", description: "需求变更/缺陷落点、diff 回推台账与查询" },
        { value: "bug", label: "bug", description: "change 的缺陷兼容别名" },
        { value: "approve-continuation", label: "approve-continuation <unit>", description: "人类专用：审查并批准 continuation 计划（签发一次性票据，ARMED 5 分钟）" },
        { value: "revoke-continuation", label: "revoke-continuation <unit>", description: "人类专用：撤销票据/治理标记" },
        { value: "recover-continuation", label: "recover-continuation <unit>", description: "人类专用：重试 ISOLATED 单元的审计（只重试审计）" },
      ];
      return subcommands.filter((s) => s.value.startsWith(prefix));
    },
    handler: async (args: string, ctx: ExtensionCommandContext) => {
      const sub = (args.trim().split(/\s+/)[0] || "status").toLowerCase();
      const status = detectAtlasStatus(ctx.cwd);

      switch (sub) {
        case "status": {
          const lines = [
            `【Atlas Project Harness 状态】`,
            `  - 工作目录: ${ctx.cwd}`,
            `  - Atlas 已装配: ${status.isAtlasProject ? `是 (版本: ${status.version || "dev"})` : "否"}`,
            `  - 开户态: ${ONBOARDING_LABEL[status.onboarding]}`,
            `  - 结构基线: ${status.hasStructure ? "已就绪" : "未就绪 (.atlas/spec/structure/_meta.json 缺失)"}`,
            `  - 技术栈画像: ${status.hasStackProfile ? `已配置 (${status.stackProfileRel})` : "未配置"}`,
          ];
          if (status.layoutNote) {
            lines.push(`  - 布局: ${status.layoutNote}`);
          }
          if (!status.isAtlasProject) {
            lines.push(``, `提示: 当前项目尚未接入 Atlas。使用 \`/atlas init\` 即可一键装配。`);
          } else if (status.onboarding !== "done") {
            lines.push(
              ``,
              `提示: **装配 ≠ 开户** —— 开户产物 = ${status.prdRel}/prd.md 与 .atlas/spec/structure/_meta.json。`,
              `      现在${ONBOARDING_LABEL[status.onboarding]}；用户说「把项目接入 Atlas 工作流」时`,
              `      直接唤起技能 \`/atlas-apply adopt\`（存量：只登记既有基线 + 开户最小集，`,
              `      不重写老 PRD/用例）。开户按产物存在与否断点续跑，不吃掉已完成的部分。`,
            );
          }
          ctx.ui.notify(lines.join("\n"), status.isAtlasProject ? "info" : "warning");
          break;
        }

        case "check": {
          if (!status.isAtlasProject) {
            ctx.ui.notify("当前项目未装配 Atlas，请先运行 `/atlas init`", "warning");
            return;
          }
          ctx.ui.notify("正在执行 Atlas 全流程门禁体检...", "info");
          const checkScript = join(ctx.cwd, ".atlas", "scripts", "atlas_check.py");
          const cmdArgs = existsSync(checkScript)
            ? [PYTHON, checkScript, "--root", ctx.cwd]
            : ["atlas", "check", "--fast"];

          try {
            const res = await pi.exec(cmdArgs[0], cmdArgs.slice(1), { timeout: 60_000 });
            if (res.code === 0) {
              ctx.ui.notify("✅ Atlas 门禁校验全部通过！", "info");
            } else {
              const err = (res.stderr || res.stdout || "").trim();
              ctx.ui.notify(`❌ Atlas 门禁校验发现问题:\n${err.slice(0, 500)}`, "error");
            }
          } catch (e: any) {
            ctx.ui.notify(`执行 atlas check 失败: ${e.message}`, "error");
          }
          break;
        }

        case "init": {
          ctx.ui.notify("启动 Atlas 一键装配向导...", "info");
          try {
            const res = await pi.exec("atlas", ["init", "--target", ctx.cwd], { timeout: 120_000 });
            if (res.code === 0) {
              ctx.ui.notify("🎉 Atlas 装配成功！已配置 Skills 与项目接线。", "info");
            } else {
              ctx.ui.notify(`装配遇到问题:\n${(res.stderr || res.stdout).slice(0, 400)}`, "error");
            }
          } catch (e: any) {
            ctx.ui.notify(`执行 atlas init 失败: ${e.message}`, "error");
          }
          break;
        }

        case "console": {
          if (!status.isAtlasProject) {
            ctx.ui.notify("当前项目未装配 Atlas，无法启动控制台", "warning");
            return;
          }
          ctx.ui.notify("正在启动 Atlas E2E 走查控制台 (atlas console)...", "info");
          try {
            await pi.exec("atlas", ["console"], { timeout: 5_000 });
          } catch (e: any) {
            ctx.ui.notify(`启动控制台异常: ${e.message}`, "warning");
          }
          break;
        }

        case "change":
        case "bug": {
          const changeArgs = args.trim().split(/\s+/).slice(1);
          try {
            const res = await pi.exec("atlas", [sub, ...changeArgs], { timeout: 120_000 });
            const output = (res.stdout || res.stderr || "").trim();
            ctx.ui.notify(output || `atlas ${sub} 退出码 ${res.code}`, res.code === 0 ? "info" : "warning");
          } catch (e: any) {
            ctx.ui.notify(`执行 atlas ${sub} 失败: ${e.message}`, "warning");
          }
          break;
        }

        case "approve-continuation": {
          // 人类专用命令；模型无入口。先同步检查信任/装配态，失败仅提示不写盘。
          // v16 M3 门校准：只读链（progress/status）的 read-set 不消费结构事实，
          // 开户门收窄为「已装配」；结构基线未就绪降级为 approve 提示（写链 P2 须全开户）。
          if (!status.isAtlasProject) {
            ctx.ui.notify("Guarded Continuation：项目未装配 Atlas，拒绝签发票据", "warning");
            return;
          }
          const unit = args.trim().split(/\s+/)[1];
          if (!unit) {
            ctx.ui.notify("用法：/atlas approve-continuation <unit>", "warning");
            return;
          }
          const plan = gcPlanBytes(ctx.cwd, unit);
          if (!plan) {
            ctx.ui.notify(`计划不存在：.atlas/tasks/${unit}/continuation.json（人审后落盘）`, "warning");
            return;
          }
          let planActions: Array<{ id: string; tool: string; args: Record<string, string> }> = [];
          try {
            const parsed = JSON.parse(plan.bytes.toString("utf8")) as { schema: number; unit: string; actions: typeof planActions };
            if (parsed.schema !== 1 || parsed.unit !== unit) throw new Error("schema/unit 不一致");
            const allowed = new Set(["atlas_workflow_progress", "atlas_workflow_status"]);
            for (const a of parsed.actions) {
              if (!allowed.has(a.tool)) throw new Error(`非法动作 ${a.tool}`);
              if (!a.args || a.args.unit !== unit) throw new Error("args 只允许 {unit}");
              planActions.push(a);
            }
          } catch (e: any) {
            ctx.ui.notify(`计划契约校验失败：${e.message}`, "warning");
            return;
          }
          if (gcTickets.has(unit) || gcActive?.unit === unit) {
            ctx.ui.notify(`unit ${unit} 已有治理态，先 revoke`, "warning");
            return;
          }
          // F7（评审 B）：ISOLATED/非终态标记存在时禁止再 ARMED（防旧 run 永不审计）
          if (gcIsolatedUnits.has(unit)) {
            ctx.ui.notify(`unit ${unit} 处于 ISOLATED，先 /atlas recover-continuation ${unit} 重试审计`, "warning");
            return;
          }
          const existingMarker = gcMarkerPath(ctx.cwd, unit);
          if (existsSync(existingMarker)) {
            const mk = JSON.parse(readFileSync(existingMarker, "utf-8")) as { state?: string };
            if (mk.state && !GC_TERMINAL_STATES.has(mk.state)) {
              ctx.ui.notify(`unit ${unit} 有非终态标记（${mk.state}），先 recover 或 revoke`, "warning");
              return;
            }
          }
          const listing = planActions
            .map((a, i) => `  ${i + 1}. ${a.id}: ${a.tool}({unit:"${a.args.unit}"})`)
            .join("\n");
          const onboardingNote = status.onboarding !== "done"
            ? `\n⚠️ 结构基线未就绪（${ONBOARDING_LABEL[status.onboarding]}）：只读链不受影响；写链（P2）必须先补开户。`
            : "";
          const okConfirm = await ctx.ui.confirm(
            `批准 continuation 计划 ${unit}？`,
            `计划哈希 ${plan.sha256.slice(0, 16)}…\n动作链（封闭枚举，只读）：\n${listing}\n票据 5 分钟内有效、一次消费；ARMED 期间默认拒绝所有模型工具。${onboardingNote}`,
          );
          if (!okConfirm) {
            ctx.ui.notify("已取消：未签发票据", "info");
            return;
          }
          gcWriteMarker(ctx.cwd, unit, {
            state: "ARMED", plan_sha256: plan.sha256,
            session_id: ctx.sessionManager.getSessionId(),
            armed_at: new Date().toISOString(),
          });
          gcTickets.set(unit, {
            unit, planSha256: plan.sha256,
            sessionId: ctx.sessionManager.getSessionId(),
            nonce: randomBytes(8).toString("hex"),
            expiryMs: Date.now() + 5 * 60_000,
            consumed: false,
          });
          ctx.ui.notify(`✅ ${unit} 已 ARMED（票据 5 分钟有效、一次消费）。模型现在只能调用 atlas_continue。`, "info");
          break;
        }

        case "revoke-continuation": {
          const unit = args.trim().split(/\s+/)[1];
          if (!unit) {
            ctx.ui.notify("用法：/atlas revoke-continuation <unit>", "warning");
            return;
          }
          gcTickets.delete(unit);
          if (gcActive?.unit === unit) {
            ctx.ui.notify(`unit ${unit} 有活跃 run（${gcActive.runId}），标记撤销；审计仍将执行`, "warning");
          }
          gcWriteMarker(ctx.cwd, unit, { state: "REVOKED", revoked_at: new Date().toISOString() });
          ctx.ui.notify(`✅ ${unit} 票据已撤销`, "info");
          break;
        }

        case "recover-continuation": {
          // 只重试审计；不重跑动作链。
          const unit = args.trim().split(/\s+/)[1];
          if (!unit) {
            ctx.ui.notify("用法：/atlas recover-continuation <unit>", "warning");
            return;
          }
          const markerPath = gcMarkerPath(ctx.cwd, unit);
          if (!existsSync(markerPath)) {
            ctx.ui.notify(`无治理标记：${markerPath}`, "warning");
            return;
          }
          const marker = JSON.parse(readFileSync(markerPath, "utf-8")) as { state: string; run_id?: string; parent_tool_call_id?: string; expected_parent_result_sha256?: string };
          if (GC_TERMINAL_STATES.has(marker.state)) {
            ctx.ui.notify(`unit ${unit} 已是终态 ${marker.state}，无需 recover`, "info");
            return;
          }
          if (!marker.run_id || !marker.parent_tool_call_id || !marker.expected_parent_result_sha256) {
            ctx.ui.notify(`标记缺 run 上下文（claimed_no_run 窗口？）：需人工确认零子调用后手工关闭`, "warning");
            return;
          }
          gcIsolatedUnits.delete(unit);
          gcPendingAudit.push({ unit, runId: marker.run_id, parentToolCallId: marker.parent_tool_call_id, expectedHash: marker.expected_parent_result_sha256 });
          await gcRunAudit(pi, ctx as unknown as ExtensionContext, unit);
          break;
        }

        default: {
          ctx.ui.notify(
            `未知子命令 "${sub}"。可用选项: status, check, init, console, report, change, bug`,
            "warning",
          );
        }
      }
    },
  });

  // ──────────────────────────────────────────────────────────────────────────
  // 2. before_agent_start 钩子：注入 Project Harness 契约指引
  // ──────────────────────────────────────────────────────────────────────────

  pi.on("before_agent_start", async (event, ctx: ExtensionContext) => {
    const status = detectAtlasStatus(ctx.cwd);
    if (!status.isAtlasProject) {
      return {};
    }

    // 设置状态栏（未开户给醒目态，别让"已装配"冒充"已接入"）
    if (ctx.hasUI && ctx.ui.setStatus) {
      ctx.ui.setStatus(
        "atlas",
        status.onboarding === "done" ? `Atlas 🛡️ (${status.version || "active"})` : "Atlas ⚠️ 未开户",
      );
    }

    const prompt = event.systemPrompt ?? "";
    const alreadyTold = prompt.includes("atlas — 全流程工作流") || prompt.includes("Project Harness");

    // 未开户 / 开户中：注入的是**下一步做什么**，不是契约守则 ——
    // 用户说「接入」时最常见的一脚踩空就在这里（仓库里已有 .atlas/，agent 判「已接入」）。
    if (status.onboarding !== "done") {
      if (prompt.includes("已装配但尚未开户")) return {};
      const onboardingNotice =
        `\n\n# Atlas: 已装配但尚未开户（装配 ≠ 开户）\n` +
        `This project has the Atlas harness **assembled** but is **not onboarded** ` +
        `(onboarding state: ${status.onboarding}). Onboarding artifacts are ` +
        `\`${status.prdRel}/prd.md\` and \`.atlas/spec/structure/_meta.json\` — both still missing.\n` +
        `When the user asks to 「把项目接入 Atlas 工作流」/「接入 Atlas」, run the skill ` +
        `\`atlas-apply adopt\` (existing project: register the baseline + minimal PRD only; ` +
        `do NOT rewrite old PRDs or invent legacy test cases). **Do not** conclude "already ` +
        `onboarded" just because \`.atlas/\` or the asset root exist, and do not ask the user ` +
        `whether they already onboarded. Onboarding resumes by artifact presence.\n`;
      return { systemPrompt: prompt + onboardingNotice };
    }

    // 已开户：轻量级注入 Project Harness 边界
    if (alreadyTold) {
      return {};
    }

    const atlasContextNotice = `\n\n# Atlas Project Harness Notice\n` +
      `This project is governed by **Atlas** (.atlas/). ` +
      `All requirements and implementations must adhere to the deterministic specs in \`.atlas/shared/\`, ` +
      `the atlas workflow (plan → dispatch → verify → finish), and verified E2E gates. ` +
      `Do not bypass or remove atlas validation gates.\n` +
      `If an Atlas rule or gate itself blocks a legitimate business shape (not your own bug), ` +
      `do not silently work around it (no commented-out rules, no \`--no-verify\`, no weakened ` +
      `assertions): report it with \`atlas report\` per \`.atlas/shared/global-rules.md\` §15, ` +
      `describing the design problem only (no product names, business terms, real data or business code), ` +
      `then tell the user and give the best temporary path forward.\n`;

    return {
      systemPrompt: prompt + atlasContextNotice,
    };
  });

  // ──────────────────────────────────────────────────────────────────────────
  // 3. turn_end 钩子：轻量级合规感知
  // ──────────────────────────────────────────────────────────────────────────

  pi.on("turn_end", async (event, ctx: ExtensionContext) => {
    // §6.4 机制化（评审 F3-B）：治理窗口内跳过 check 写面——check-events.jsonl 为追加型，
    // 建基线也救不了 tree_changed；A/B/C/D 各臂与治理链在此互斥。
    if (gcTickets.size > 0 || gcIsolatedUnits.size > 0 || gcPendingAudit.length > 0) return;
    if (event?.outcome !== "completed") return;
    if (!event?.toolResults?.length) return; // 没动工具 ⇒ 没写盘 ⇒ 不校验

    const status = detectAtlasStatus(ctx.cwd);
    if (!status.isAtlasProject) return;

    // 未开户 ⇒ `--fast` 必然红（stack-profile 占位符还没换）⇒ **不校验、不报警**：
    // 否则未开户项目每一轮工具调用后都弹同一句「门禁异常」，纯噪声。
    // 用户该看到的是「去开户」，那由 before_agent_start 的注入负责。
    if (status.onboarding !== "done") return;

    // 检查是否存在 surface-guard 脚本或快速门禁脚本
    const checkScript = join(ctx.cwd, ".atlas", "scripts", "atlas_check.py");
    if (!existsSync(checkScript)) return;

    // 只做轻量校验。失败判据 = **失败签名差分**（issue #67）：裸看退出码会把「历史遗留
    // 的 FAIL」在每一轮重复告警，真新增反而被淹没。签名 = sha256(门名+退出码+详情)，
    // 基线落 `.atlas/runs/pi-turn-failures.json`（运行态目录，不入库）：
    //   * 基线缺失/损坏 ⇒ 静默落基线（升级后第一轮不提示历史失败 —— 消噪声的代价）；
    //   * 当前相对基线**新增/变化** ⇒ 提示（只点名新红的门）；
    //   * 失败集合不变 ⇒ 静默；集合收缩 ⇒ 静默但回写基线（修复后复发才能再提醒一次）；
    //   * `--json` 输出不可解析 ⇒ 静默且不动基线（执行异常不得伪装成门禁回归）。
    try {
      const res = await pi.exec(PYTHON, [checkScript, "--root", ctx.cwd, "--fast", "--json"], {
        timeout: 10_000,
      });
      let payload: any;
      try {
        payload = JSON.parse(res.stdout || "");
      } catch {
        return; // 不可解析 ⇒ 检查本身没跑成，不判失败、不写基线
      }
      if (!Array.isArray(payload?.failures)) return; // 形态不对同上：宁静默，不误报

      const current = new Map<string, { name: string; code: unknown }>();
      for (const f of payload.failures) {
        const sig = createHash("sha256")
          .update(`${f?.name ?? ""}\n${String(f?.code ?? "")}\n${f?.detail ?? ""}`)
          .digest("hex")
          .slice(0, 16);
        current.set(sig, { name: String(f?.name ?? "未知门"), code: f?.code });
      }

      const baselinePath = join(ctx.cwd, ".atlas", "runs", "pi-turn-failures.json");
      const writeBaseline = () => {
        try {
          mkdirSync(join(ctx.cwd, ".atlas", "runs"), { recursive: true });
          writeFileSync(
            baselinePath,
            JSON.stringify({ v: 1, signatures: Object.fromEntries(current) }, null, 2),
          );
        } catch {
          // 写失败不阻断：最坏结果 = 下一轮重新静默建一次基线
        }
      };

      let baseline: Map<string, { name: string; code: unknown }> | null = null;
      try {
        const raw = JSON.parse(readFileSync(baselinePath, "utf-8"));
        if (raw && typeof raw === "object" && raw.signatures && typeof raw.signatures === "object") {
          baseline = new Map(Object.entries(raw.signatures));
        }
      } catch {
        baseline = null; // 缺失 / 损坏 ⇒ 视同首次
      }

      if (baseline === null) {
        writeBaseline(); // 首轮建基线：静默
        return;
      }
      const base = baseline;

      const fresh = [...current.entries()].filter(([sig]) => !base.has(sig));
      if (fresh.length === 0) {
        const sameSet = base.size === current.size &&
          [...base.keys()].every((sig) => current.has(sig));
        if (!sameSet) writeBaseline(); // 有失败被修掉 ⇒ 回写，复发才能再提醒
        return;
      }

      writeBaseline();
      const shown = fresh.slice(0, 3).map(([, m]) => `「${m.name}」`).join("、");
      const more = fresh.length > 3 ? ` 等 ${fresh.length} 道` : "";
      // 撞门时刻 = `global-rules.md` §15 的交付面之一：门**新增**红的那一刻把「这可能是
      // 流水线缺陷」的出口递到手边 —— 只写在契约正文里时，流程中段等不到任何提醒。
      ctx.ui.notify(
        "⚠️ Atlas 提示：检测到新增/变化的机器门禁失败" + more + "：" + shown +
          "，建议使用 `/atlas check` 查看详情。\n" +
          "   与上一轮基线相同的历史失败不再重复提醒。若这道门挡的是合情合理的业务形态（不是你的实现 bug）⇒ " +
          "那是流水线缺陷：按 `.atlas/shared/global-rules.md` §15 用 `atlas report` 沉淀现场，" +
          "别静默豁免 / 注释规则 / `--no-verify`。",
        "warning",
      );
    } catch {
      // 容错不阻断
    }
  });

  // ════════════════════════════════════════════════════════════════════════
  // Guarded Continuation 接线（P1）：治理钩子 + 父/子工具 + 双路径审计
  // ════════════════════════════════════════════════════════════════════════

  // — session_start：扫描非终态治理标记，重建默认拒绝（崩溃/reload 不丢封锁）—
  pi.on("session_start", async (_event, ctx: ExtensionContext) => {
    const isoDir = join(ctx.cwd, ".atlas", "runs", "continuations", "isolated");
    if (!existsSync(isoDir)) return;
    for (const name of readdirSync(isoDir)) {
      if (!name.endsWith(".json")) continue;
      const unit = name.replace(/\.json$/, "");
      try {
        const marker = JSON.parse(readFileSync(join(isoDir, name), "utf-8")) as { state?: string };
        if (marker.state && !GC_TERMINAL_STATES.has(marker.state)) {
          gcIsolatedUnits.add(unit); // 非终态 ⇒ 默认拒绝模型工具，等人类 recover
        }
      } catch {
        gcIsolatedUnits.add(unit); // 坏标记 fail-closed
      }
    }
  });

  // — tool_call：治理窗口默认拒绝所有模型工具，只放行父工具与精确授权子调用 —
  pi.on("tool_call", (event) => {
    // F2（评审）：RECORDED→审计窗口也必须封锁（防审计落地前改写 receipt/evidence）
    const armed = gcTickets.size > 0 || gcIsolatedUnits.size > 0 || gcPendingAudit.length > 0;
    if (!gcActive && !armed) return;
    if (event.toolName === "atlas_continue") return; // 父工具：execute 内部原子 claim 自验
    // 授权子调用：parentToolCallId + 动作名 + 规范参数哈希三方精确匹配，一次性登记
    if (
      gcActive &&
      event.parentToolCallId === gcActive.parentToolCallId &&
      gcActive.nextAction &&
      event.toolName === gcActive.nextAction.tool &&
      gcSha(event.input) === gcActive.nextAction.argsHash
    ) {
      gcCapAuth.set(event.toolCallId, { tool: event.toolName, argsHash: gcActive.nextAction.argsHash });
      return;
    }
    return {
      block: true,
      reason: `Guarded Continuation 治理窗口：${event.toolName} 未授权（ARMED/RUNNING 期间默认拒绝所有模型工具）`,
    };
  });

  // — tool_execution_end：宿主耗时采集（CLI 耗时与宿主耗时分列，§6.1）—
  pi.on("tool_execution_end", (event) => {
    if (typeof event.durationMs === "number") {
      gcHostDurations.set(event.toolCallId, event.durationMs);
    }
  });

  // — tool_result：supplemental evidence 仅为观测，不进权威对账面（P0 边界）—
  pi.on("tool_result", (event, ctx: ExtensionContext) => {
    if (!gcActive || !event.parentToolCallId || event.parentToolCallId !== gcActive.parentToolCallId) return;
    try {
      const runDirPath = join(ctx.cwd, ".atlas", "runs", "continuations", gcActive.runId);
      const evidence = {
        kind: "supplemental",
        child_tool_call_id: event.toolCallId,
        tool: event.toolName,
        result_hash_observed: gcResultHash({
          content: (event as unknown as { content?: unknown }).content,
          details: (event as unknown as { details?: unknown }).details,
          isError: (event as unknown as { isError?: unknown }).isError,
        }),
        observed_at: new Date().toISOString(),
      };
      writeFileSync(join(runDirPath, "evidence", `${event.toolCallId.replace(/[^A-Za-z0-9._-]/g, "_")}.json`), JSON.stringify(evidence, null, 2));
    } catch {
      // supplemental 失败不阻断主链；权威面是 raw-receipts
    }
  });

  // — 子工具工厂：只读 CLI 经净化启动器；raw 回执 O_EXCL 返回前写 + 哈希预提交 —
  function gcMakeChild(toolName: string, subcommand: "progress" | "status") {
    return {
      name: toolName,
      label: toolName,
      description: `Atlas 只读动作 ${subcommand}（Guarded Continuation 内部子工具，仅由 atlas_continue 嵌套调用）`,
      exposure: "codemode" as const,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
      parameters: Type.Object({ unit: Type.String({ description: "任务单元 ID" }) }),
      async execute(toolCallId: string, params: { unit: string }, signal: AbortSignal, _onUpdate: unknown, childCtx: ExtensionContext) {
        const cwd = childCtx.cwd;
        // 复核 1：能力表一次性消费（模型直调 / codemode 直调 / 陈旧标记 ⇒ 无授权即拒）
        const cap = gcCapAuth.get(toolCallId);
        gcCapAuth.delete(toolCallId);
        const argsHash = gcSha({ unit: params.unit });
        if (!cap || cap.tool !== toolName || cap.argsHash !== argsHash) {
          return {
            content: [{ type: "text" as const, text: `${toolName}: 未获父能力授权或参数不匹配` }],
            details: { tool: toolName, unit: params.unit, exit_code: -1, json_ok: false, authorized: false },
            isError: true,
          };
        }
        const run = gcActive;
        if (!run || run.phase !== "RUNNING") {
          return {
            content: [{ type: "text" as const, text: `${toolName}: 无 RUNNING 治理窗口` }],
            details: { tool: toolName, unit: params.unit, exit_code: -1, json_ok: false, authorized: true },
            isError: true,
          };
        }
        void signal;
        const runDirPath = join(cwd, ".atlas", "runs", "continuations", run.runId);
        const gcLog = join(runDirPath, "git-calls.jsonl");
        const workflowScript = join(cwd, ".atlas", "scripts", "atlas_workflow.py");
        // 只读 git 包装器日志按字节偏移增量消费：本动作窗口内任一非零 rc ⇒ 动作失败
        const gcOffset = gcGitLogOffsets.get(gcLog) ?? 0;
        const gcSizeBefore = existsSync(gcLog) ? statSync(gcLog).size : 0;
        const t0 = Date.now();
        const res = gcLauncher(cwd, gcLog, workflowScript,
          [subcommand, "--unit", params.unit, "--json", "--root", cwd], 15_000);
        const cliDurationMs = Date.now() - t0;
        const exitCode = res.code;
        let jsonOk = false;
        try {
          JSON.parse(res.stdout);
          jsonOk = true;
        } catch {
          jsonOk = false;
        }
        let gitCallsOk = true;
        try {
          if (gcSizeBefore > gcOffset) {
            // 上次消费后文件被截断/外写 ⇒ 记账面不可信，fail-closed
            gitCallsOk = false;
          }
          const sizeAfter = existsSync(gcLog) ? statSync(gcLog).size : gcSizeBefore;
          if (sizeAfter > gcOffset) {
            const chunk = readFileSync(gcLog, "utf-8").slice(gcOffset);
            for (const line of chunk.split("\n")) {
              if (!line.trim()) continue;
              const rec = JSON.parse(line) as { rc: number };
              if (rec.rc !== 0) gitCallsOk = false;
            }
            gcGitLogOffsets.set(gcLog, sizeAfter);
          }
          // 本动作窗口内零新记录 = 该 CLI 未发 git 调用（如 status）⇒ 合法，不判失败。
          // 绕过检测不靠日志行数（缺失与零调用不可区分），靠 PATH 冻结保证拦截面。
        } catch {
          gitCallsOk = false;
        }
        const isError = exitCode !== 0 || !jsonOk || !gitCallsOk;
        const result = {
          content: [{
            type: "text" as const,
            text: isError
              ? `${toolName} FAILED unit=${params.unit} (exit=${exitCode} json_ok=${jsonOk} git_ok=${gitCallsOk})`
              : `${toolName} ok unit=${params.unit}`,
          }],
          details: {
            tool: toolName, unit: params.unit,
            exit_code: exitCode, json_ok: jsonOk, git_calls_ok: gitCallsOk,
            stdout_bytes: res.stdout.length, cli_duration_ms: cliDurationMs,
          },
          isError,
        };
        // raw 回执：返回前 O_EXCL 写盘 + 预提交父私有台账（设计边界：哈希不进被哈希对象）
        const resultSha = gcResultHash(result);
        const receiptPath = join(runDirPath, "raw-receipts", `${run.observations.length + 1}-${resultSha.slice(0, 16)}.json`);
        const receiptText = JSON.stringify({
          canonical_hash: resultSha,
          result,
          toolCallId, toolName,
          args: { unit: params.unit },
          written_at: new Date().toISOString(),
        }, null, 2) + "\n";
        writeFileSync(receiptPath, receiptText, { flag: "wx" });
        gcRawCommits.set(toolCallId, {
          resultSha256: resultSha,
          fileSha256: createHash("sha256").update(receiptText).digest("hex"),
          receiptPath,
        });
        return result;
      },
    };
  }

  pi.registerTool(gcMakeChild("atlas_workflow_progress", "progress"));
  pi.registerTool(gcMakeChild("atlas_workflow_status", "status"));

  // — 父工具：模型只见它；execute 首个同步操作 = 原子 claim 票据 —
  pi.registerTool({
    name: "atlas_continue",
    label: "atlas_continue",
    description:
      "Run the human-approved read-only continuation chain for a unit (frozen plan: progress -> status). " +
      "Requires the human to have approved via /atlas approve-continuation first. Args: {unit} only.",
    exposure: "model-only",
    executionMode: "sequential", // §5.3：父工具串行化声明（PoC 单槽 gcActive）
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    parameters: Type.Object({ unit: Type.String({ description: "任务单元 ID，与已批准计划一致" }) }),
    async execute(toolCallId: string, params: { unit: string }, signal: AbortSignal, _onUpdate, ctx) {
      const cwd = ctx.cwd;
      const fail = (reason: string) => ({
        content: [{ type: "text" as const, text: `atlas_continue FAILED unit=${params.unit}: ${reason}` }],
        details: { unit: params.unit, actions_ok: false, fail_reason: reason },
        isError: true,
      });
      // 1) 同步复查项目信任/装配态（失败仅内存拒绝，不 claim、不写盘；v16 M3 收窄口径与 approve 一致）
      const st = detectAtlasStatus(cwd);
      if (!st.isAtlasProject) return fail("项目未装配 Atlas");
      // 2) 原子 claim 票据（任何 await 之前；双父并发只有一方成功）
      const ticket = gcTickets.get(params.unit);
      if (!ticket || ticket.consumed) return fail("无有效票据（先由人类 /atlas approve-continuation 签发）");
      if (ticket.expiryMs < Date.now()) { gcTickets.delete(params.unit); return fail("票据已过期"); }
      if (ticket.sessionId !== ctx.sessionManager.getSessionId()) return fail("票据绑定其他 session");
      if (ticket.planSha256 !== (gcPlanBytes(cwd, params.unit)?.sha256 ?? "")) return fail("计划哈希与票据不一致（计划被改）");
      ticket.consumed = true;
      gcTickets.delete(params.unit);
      // 3) 持久 CLAIMED_NO_RUN → 建 run 目录 → RUNNING
      const runId = `gc-${Date.now()}-${randomBytes(4).toString("hex")}`;
      gcWriteMarker(cwd, params.unit, {
        state: "CLAIMED_NO_RUN", run_id: runId,
        parent_tool_call_id: toolCallId, plan_sha256: ticket.planSha256,
        session_id: ctx.sessionManager.getSessionId(),
        claimed_at: new Date().toISOString(),
      });
      const runDirPath = gcRunDir(cwd, runId);
      if (!existsSync(join(runDirPath, "raw-receipts"))) return fail("run 目录建立失败");
      gcActive = {
        unit: params.unit, runId, sessionId: ctx.sessionManager.getSessionId(),
        parentToolCallId: toolCallId, planSha256: ticket.planSha256,
        phase: "RUNNING", observations: [], nextAction: null,
      };
      gcWriteMarker(cwd, params.unit, {
        state: "RUNNING", run_id: runId, parent_tool_call_id: toolCallId,
        plan_sha256: ticket.planSha256, claimed_at: new Date().toISOString(),
      });
      const gcLog = join(runDirPath, "git-calls.jsonl");
      const continueScript = join(cwd, ".atlas", "scripts", "atlas_continue.py");
      const workflowScript = join(cwd, ".atlas", "scripts", "atlas_workflow.py");
      if (!existsSync(continueScript) || !existsSync(workflowScript)) {
        gcActive = null;
        gcWriteMarker(cwd, params.unit, { state: "ISOLATED", run_id: runId, parent_tool_call_id: toolCallId, reason: "缺审计/动作脚本（零前缀窗口）" });
        gcIsolatedUnits.add(params.unit);
        return fail("采纳仓缺 atlas_continue.py / atlas_workflow.py（P1 未部署）");
      }
      try {
        // 4) prepare：契约校验 + 输入闭集快照
        const prep = gcLauncher(cwd, gcLog, continueScript,
          ["prepare", "--root", cwd, "--unit", params.unit, "--run-dir", runId], 30_000);
        let inputManifestSha = "";
        if (prep.code !== 0) {
          gcWriteMarker(cwd, params.unit, { state: "ISOLATED", run_id: runId, parent_tool_call_id: toolCallId, reason: `prepare 失败（零前缀窗口）: ${(prep.stderr || prep.stdout).slice(0, 120)}` });
          gcIsolatedUnits.add(params.unit);
          return fail(`prepare 失败: ${(prep.stderr || prep.stdout).slice(0, 200)}`);
        }
        try { inputManifestSha = (JSON.parse(prep.stdout) as { input_manifest_sha256?: string }).input_manifest_sha256 ?? ""; } catch { /* keep empty */ }
        const plan = gcPlanBytes(cwd, params.unit)!;
        const planDoc = JSON.parse(plan.bytes.toString("utf8")) as {
          actions: Array<{ id: string; tool: string; args: { unit: string }; guard: { kind: string; refs?: string[] } }>;
        };
        // 5) 逐动作：verify → guard 前移 → 能力标记 → 真实嵌套 → 三方可账
        const obsMap = new Map<string, GcObservation>();
        let terminalReason = "chain_ok";
        for (let i = 0; i < planDoc.actions.length; i++) {
          const action = planDoc.actions[i];
          const verr = gcLauncher(cwd, gcLog, continueScript,
            ["verify", "--root", cwd, "--unit", params.unit, "--run-dir", runId, "--phase", `pre-action-${i + 1}`], 30_000);
          if (verr.code !== 0) { terminalReason = `verify 失败(动作${i + 1})`; break; }
          const guardOk = gcGuardOk(action.guard, obsMap);
          if (!guardOk) { terminalReason = `FALLBACK_REQUIRED: guard false @${action.id}`; break; }
          const argsHash = gcSha(action.args);
          gcActive.nextAction = { index: i + 1, id: action.id, tool: action.tool, argsHash };
          const outcome = await ctx.executeTool(action.tool, action.args, { signal }) as {
            toolCall: { id: string; name: string; arguments: unknown };
            result: { content?: unknown; details?: Record<string, unknown> };
            isError: boolean;
            durationMs?: number;
          };
          gcActive.nextAction = null; // 能力一次性消费
          const childToolCallId = outcome.toolCall?.id ?? "";
          const committed = gcRawCommits.get(childToolCallId);
          const recomputed = gcResultHash({
            content: outcome.result?.content,
            details: outcome.result?.details,
            isError: outcome.isError,
          });
          let receiptBodySha: string | null = null;
          let receiptFileSha: string | null = null;
          if (committed) {
            try {
              const raw = readFileSync(committed.receiptPath);
              receiptFileSha = createHash("sha256").update(raw).digest("hex");
              receiptBodySha = (JSON.parse(raw.toString("utf8")) as { canonical_hash: string }).canonical_hash;
            } catch { receiptBodySha = null; }
          }
          const threeWayOk =
            !!committed &&
            committed.resultSha256 === receiptBodySha &&
            committed.resultSha256 === recomputed &&
            committed.fileSha256 === receiptFileSha;
          const d = (outcome.result?.details ?? {}) as { exit_code?: number; json_ok?: boolean };
          const observation: GcObservation = {
            action_index: i + 1, action_id: action.id, tool: action.tool,
            child_tool_call_id: childToolCallId,
            guard_result: true, guard_refs: action.guard?.refs ?? [],
            exit_code: Number(d.exit_code ?? -1), json_ok: d.json_ok === true,
            ok: !outcome.isError && threeWayOk,
            cli_duration_ms: Number(d.cli_duration_ms ?? 0),
            host_duration_ms: outcome.durationMs ?? gcHostDurations.get(childToolCallId) ?? null,
            result_sha256: committed?.resultSha256 ?? recomputed,
            raw_receipt_sha256: committed?.fileSha256 ?? receiptFileSha ?? "",
            raw_receipt_path: committed?.receiptPath ?? "",
          };
          gcActive.observations.push(observation);
          obsMap.set(action.id, observation);
          if (outcome.isError || !threeWayOk) {
            terminalReason = threeWayOk
              ? `action ${action.id} isError`
              : `action ${action.id} 三方可账失败（raw 回执与最终值不一致）`;
            break;
          }
        }
        // 6) record：原子写执行回执（RECORDED）→ 追加封印 →（治理态保持到 settle）
        const parentResult = {
          content: [{
            type: "text" as const,
            text: terminalReason === "chain_ok"
              ? `atlas_continue ok unit=${params.unit}: ${gcActive.observations.length} actions, no intermediate model requests`
              : `atlas_continue FAILED unit=${params.unit}: ${terminalReason}`,
          }],
          details: {
            unit: params.unit, actions_ok: terminalReason === "chain_ok",
            fail_reason: terminalReason === "chain_ok" ? null : terminalReason,
            observations: gcActive.observations.map((o) => ({
              action_id: o.action_id, tool: o.tool, exit_code: o.exit_code,
              json_ok: o.json_ok, result_sha256: o.result_sha256,
            })),
          },
          isError: terminalReason !== "chain_ok",
        };
        const expectedParentHash = gcResultHash(parentResult);
        const payloadPath = join(runDirPath, "receipt-payload.json");
        writeFileSync(payloadPath, JSON.stringify({
          run_id: runId, unit: params.unit, plan_sha256: ticket.planSha256,
          status: "RECORDED", terminal_reason: terminalReason,
          session_id: ctx.sessionManager.getSessionId(),
          parent_tool_call_id: toolCallId, parent_tool_name: "atlas_continue",
          expected_parent_result_sha256: expectedParentHash,
          input_manifest_sha256: inputManifestSha,
          actions: gcActive.observations,
        }, null, 2) + "\n");
        const rec = gcLauncher(cwd, gcLog, continueScript,
          ["record", "--root", cwd, "--unit", params.unit, "--run-dir", runId, "--receipt-json", payloadPath], 30_000);
        if (rec.code !== 0) {
          gcWriteMarker(cwd, params.unit, { state: "ISOLATED", run_id: runId, parent_tool_call_id: toolCallId, reason: "record 失败" });
          gcIsolatedUnits.add(params.unit);
          return fail(`record 失败: ${(rec.stderr || rec.stdout).slice(0, 200)}`);
        }
        gcActive.phase = "RECORDED";
        gcWriteMarker(cwd, params.unit, {
          state: "RECORDED", run_id: runId, parent_tool_call_id: toolCallId,
          plan_sha256: ticket.planSha256,
          expected_parent_result_sha256: expectedParentHash,
          terminal_reason: terminalReason,
          recorded_at: new Date().toISOString(),
        });
        pi.appendEntry("atlas-continuation-seal", {
          runId, unit: params.unit,
          sessionId: ctx.sessionManager.getSessionId(),
          parentToolCallId: toolCallId, parentToolName: "atlas_continue",
          expectedParentResultHash: expectedParentHash,
          expectedActions: planDoc.actions.map((a) => ({ index: a.id, tool: a.tool })),
          sealedAt: new Date().toISOString(),
        });
        gcPendingAudit.push({ unit: params.unit, runId, parentToolCallId: toolCallId, expectedHash: expectedParentHash });
        return {
          content: parentResult.content,
          details: parentResult.details,
          isError: parentResult.isError,
        };
      } catch (e: any) {
        const state = gcActive?.phase === "CLAIMED_NO_RUN" ? "CLAIMED_NO_RUN" : "ISOLATED";
        gcWriteMarker(cwd, params.unit, {
          state, run_id: runId, parent_tool_call_id: toolCallId,
          reason: String(e?.message ?? e),
        });
        if (state === "ISOLATED") gcIsolatedUnits.add(params.unit);
        return fail(String(e?.message ?? e));
      } finally {
        gcActive = null;
      }
    },
  });

  // — agent_settled / session_shutdown：同一审计函数（M2：双路径都必须活着）—
  async function gcRunAudit(_pi: ExtensionAPI, ctx: ExtensionContext, unitFilter?: string): Promise<void> {
    const jobs = gcPendingAudit.splice(0).filter((j) => !unitFilter || j.unit === unitFilter);
    for (const job of jobs) {
      const cwd = ctx.cwd;
      const runDirPath = join(cwd, ".atlas", "runs", "continuations", job.runId);
      try {
        const branch = ctx.sessionManager.getBranch() as Array<Record<string, unknown>>;
        let parentMsg: Record<string, unknown> | null = null;
        let sealEntry: Record<string, unknown> | null = null;
        for (const e of branch) {
          const m = (e.message ?? e) as Record<string, unknown>;
          if (m?.role === "toolResult" && m?.toolCallId === job.parentToolCallId) parentMsg = m;
          if (e.customType === "atlas-continuation-seal" &&
              (e.data as Record<string, unknown> | undefined)?.parentToolCallId === job.parentToolCallId) sealEntry = e;
        }
        if (!parentMsg || !sealEntry) {
          gcWriteMarker(cwd, job.unit, { state: "ISOLATED", run_id: job.runId, parent_tool_call_id: job.parentToolCallId, reason: "session 缺父结果或封印" });
          gcIsolatedUnits.add(job.unit);
          continue;
        }
        const actualHash = gcResultHash({
          content: parentMsg.content, details: parentMsg.details,
          structuredContent: parentMsg.structuredContent, isError: parentMsg.isError,
        });
        const hostRecord = {
          parent_tool_call_id: job.parentToolCallId,
          nestedCalls: parentMsg.nestedCalls ?? null,
          actual_parent_result_sha256: actualHash,
          host_duration_ms: gcHostDurations.get(job.parentToolCallId) ?? null,
        };
        writeFileSync(join(runDirPath, "host-record.json"), JSON.stringify(hostRecord, null, 2) + "\n");
        const sessionFile = ctx.sessionManager.getSessionFile();
        const continueScript = join(cwd, ".atlas", "scripts", "atlas_continue.py");
        if (!sessionFile || !existsSync(continueScript)) {
          gcWriteMarker(cwd, job.unit, { state: "ISOLATED", run_id: job.runId, parent_tool_call_id: job.parentToolCallId, reason: "缺 session 文件或审计脚本" });
          gcIsolatedUnits.add(job.unit);
          continue;
        }
        const res = gcLauncher(cwd, join(runDirPath, "git-calls.jsonl"), continueScript,
          ["audit", "--root", cwd, "--unit", job.unit, "--run-dir", job.runId,
           "--session", sessionFile, "--host-record", join(runDirPath, "host-record.json"),
           "--atlas-version", detectAtlasStatus(cwd).version ?? "poc"], 60_000);
        let verdict = "";
        try { verdict = (JSON.parse(res.stdout.trim().split("\n").filter(Boolean).pop() ?? "{}") as { verdict?: string }).verdict ?? ""; } catch { /* fallthrough */ }
        if (res.code === 0 && verdict === "SUCCEEDED") {
          gcWriteMarker(cwd, job.unit, {
            state: "SUCCEEDED", run_id: job.runId,
            parent_tool_call_id: job.parentToolCallId,
            certificate: join(runDirPath, "certificate.json"),
            audited_at: new Date().toISOString(),
          });
        } else if (res.code === 0 && verdict === "CLOSED_FAILED") {
          gcWriteMarker(cwd, job.unit, {
            state: "CLOSED_FAILED", run_id: job.runId,
            parent_tool_call_id: job.parentToolCallId,
            detail: "失败/回退链审计通过（零违规后续调用）；不签成功证书",
            audited_at: new Date().toISOString(),
          });
        } else {
          gcWriteMarker(cwd, job.unit, {
            state: "AUDIT_FAILED", run_id: job.runId,
            parent_tool_call_id: job.parentToolCallId,
            detail: (res.stdout || res.stderr).slice(0, 200),
            audited_at: new Date().toISOString(),
          });
        }
        if (ctx.hasUI && ctx.ui.notify) {
          ctx.ui.notify(
            res.code === 0
              ? `🛡️ Guarded Continuation：${job.unit} 审计通过，证书已签发（${job.runId}）`
              : `⚠️ Guarded Continuation：${job.unit} 审计失败（${job.runId}），保持封锁，可 /atlas recover-continuation ${job.unit} 重试审计`,
            res.code === 0 ? "info" : "warning",
          );
        }
      } catch (e: any) {
        try {
          gcWriteMarker(cwd, job.unit, { state: "ISOLATED", run_id: job.runId, parent_tool_call_id: job.parentToolCallId, reason: String(e?.message ?? e) });
          gcIsolatedUnits.add(job.unit);
        } catch { /* 尽力持久化 */ }
      }
    }
  }

  pi.on("agent_settled", async (_event, ctx: ExtensionContext) => {
    await gcRunAudit(pi, ctx);
  });
  pi.on("session_shutdown", async (_event, ctx: ExtensionContext) => {
    await gcRunAudit(pi, ctx); // M2 兜底：agent_settled 未跑（崩溃/直接退出）也审计
  });
}
