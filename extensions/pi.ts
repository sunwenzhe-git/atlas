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
import {
  accessSync,
  closeSync,
  constants,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { tmpdir } from "node:os";
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

const GC_UNIT_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const GC_WRITE_TOOLS = new Set([
  "atlas_workflow_finish_preflight",
  "atlas_workflow_finish_deferred",
  "atlas_workflow_finish_commit",
  "atlas_workflow_finish_archive",
]);
const GC_MUTATING_WRITE_TOOLS = new Set([
  "atlas_workflow_finish_deferred",
  "atlas_workflow_finish_commit",
  "atlas_workflow_finish_archive",
]);
const GC_ALLOWED_TOOLS = new Set([
  "atlas_workflow_progress",
  "atlas_workflow_status",
  ...GC_WRITE_TOOLS,
]);
const GC_WRITE_RANK: Record<string, number> = {
  atlas_workflow_finish_preflight: 0,
  atlas_workflow_finish_deferred: 1,
  atlas_workflow_finish_commit: 2,
  atlas_workflow_finish_archive: 3,
};

type GcTicket = {
  unit: string;
  planSha256: string;
  sessionId: string;
  nonce: string;
  expiryMs: number;
  consumed: boolean;
  runId?: string;
  isWrite?: boolean;
  irreversibleAck?: boolean;
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
  isWrite: boolean;
  writeStarted: boolean;
  isUnknown: boolean;
  lockToken?: string;
  observations: GcObservation[];
  // 一次性能力标记：仅父工具即将调用的动作存在（tool_call 授权 + 子 execute 复核）
  nextAction: { index: number; id: string; tool: string; argsHash: string } | null;
};

type GcLockHandle = {
  lockToken: string;
  release: () => Promise<void>;
};

const gcActiveLocks = new Map<string, GcLockHandle>();

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

function gcFsyncDir(dirPath: string): void {
  try {
    const fd = openSync(dirPath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
    try {
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
  } catch {
    // 非 POSIX dir_fsync 文件系统尽最大努力
  }
}

function gcAssertNotSymlink(targetPath: string): void {
  if (!existsSync(targetPath)) return;
  const st = lstatSync(targetPath);
  if (st.isSymbolicLink()) {
    throw new Error(`禁止 symlink 路径：${targetPath}`);
  }
}

function gcAtomicWriteText(targetPath: string, text: string): void {
  const dir = dirname(targetPath);
  mkdirSync(dir, { recursive: true });
  gcAssertNotSymlink(dir);
  gcAssertNotSymlink(targetPath);
  const tmp = `${targetPath}.tmp-${randomBytes(4).toString("hex")}`;
  const flags = constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0);
  const fd = openSync(tmp, flags, 0o644);
  try {
    writeFileSync(fd, text, "utf8");
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(tmp, targetPath);
  gcFsyncDir(dir);
}

function gcWriteExclusiveText(targetPath: string, text: string): void {
  const dir = dirname(targetPath);
  mkdirSync(dir, { recursive: true });
  gcAssertNotSymlink(dir);
  const flags = constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0);
  const fd = openSync(targetPath, flags, 0o644);
  try {
    writeFileSync(fd, text, "utf8");
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  gcFsyncDir(dir);
}

function gcReadMarker(cwd: string, unit: string): Record<string, unknown> | null {
  const p = gcMarkerPath(cwd, unit);
  if (!existsSync(p)) return null;
  gcAssertNotSymlink(p);
  return JSON.parse(readFileSync(p, "utf-8")) as Record<string, unknown>;
}

function gcMarkerIsUnknown(cwd: string, unit: string): boolean {
  try {
    const mk = gcReadMarker(cwd, unit);
    return mk?.state === "UNKNOWN";
  } catch {
    return false;
  }
}

function gcMarkerPath(cwd: string, unit: string): string {
  if (!GC_UNIT_RE.test(unit)) throw new Error(`非法 unit：${unit}`);
  return join(cwd, ".atlas", "runs", "continuations", "isolated", `${unit}.json`);
}

function gcWriteMarker(cwd: string, unit: string, payload: Record<string, unknown>, opts?: { allowOverwriteUnknown?: boolean }): void {
  const p = gcMarkerPath(cwd, unit);
  if (!opts?.allowOverwriteUnknown && gcMarkerIsUnknown(cwd, unit) && payload.state !== "UNKNOWN") {
    throw new Error(`禁止覆写 ${unit} 的 UNKNOWN 治理封锁标记`);
  }
  gcAtomicWriteText(p, JSON.stringify({ unit, ...payload }, null, 2) + "\n");
}

const GC_TERMINAL_STATES = new Set(["SUCCEEDED", "CLOSED_FAILED", "REVOKED"]);

function gcRunDir(cwd: string, runId: string): string {
  const safe = /^[A-Za-z0-9_-]{1,80}$/.test(runId) ? runId : "";
  if (!safe) throw new Error(`非法 run_id：${runId}`);
  const contDir = join(cwd, ".atlas", "runs", "continuations");
  mkdirSync(contDir, { recursive: true });
  gcAssertNotSymlink(contDir);
  const dir = join(contDir, safe);
  mkdirSync(dir, { recursive: true });
  gcAssertNotSymlink(dir);
  for (const sub of ["raw-receipts", "evidence"]) {
    const subDir = join(dir, sub);
    mkdirSync(subDir, { recursive: true });
    gcAssertNotSymlink(subDir);
    gcFsyncDir(subDir);
  }
  gcFsyncDir(dir);
  return dir;
}

function gcHasLauncher(envName: "ATLAS_GC_LAUNCHER" | "ATLAS_GC_WRITE_LAUNCHER"): boolean {
  const launcher = process.env[envName];
  if (!launcher || !existsSync(launcher)) return false;
  try {
    accessSync(launcher, constants.X_OK);
    return true;
  } catch {
    return false;
  }
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

/** 异步净化启动器（支持 write launcher、stdin 租约 token 与 AbortSignal 终止）。 */
function gcLauncherAsync(
  cwd: string,
  launcherEnv: "ATLAS_GC_LAUNCHER" | "ATLAS_GC_WRITE_LAUNCHER",
  gcLog: string,
  scriptPath: string,
  args: string[],
  timeoutMs: number,
  opts?: { input?: string; signal?: AbortSignal },
): Promise<{ code: number; stdout: string; stderr: string; aborted: boolean }> {
  const launcher = process.env[launcherEnv];
  if (!launcher) {
    return Promise.resolve({
      code: 126,
      stdout: "",
      stderr: `${launcherEnv} 未冻结：须先冻结净化启动器`,
      aborted: false,
    });
  }
  return new Promise((resolve) => {
    const child = spawn(launcher, [gcLog, scriptPath, ...args], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    let aborted = false;
    let killTimer: ReturnType<typeof setTimeout> | null = null;

    const triggerKill = (reason: string) => {
      aborted = true;
      stderr += `\n${reason}`;
      try {
        child.kill("SIGTERM");
      } catch {
        // ignore
      }
      if (!killTimer) {
        killTimer = setTimeout(() => {
          try {
            child.kill("SIGKILL");
          } catch {
            // ignore
          }
        }, 2000);
      }
    };

    const timeoutTimer = setTimeout(() => triggerKill("timeout"), timeoutMs);
    const onAbort = () => triggerKill("aborted");
    if (opts?.signal) {
      if (opts.signal.aborted) {
        triggerKill("aborted");
      } else {
        opts.signal.addEventListener("abort", onAbort, { once: true });
      }
    }

    child.stdout?.on("data", (d) => {
      stdout += d.toString();
    });
    child.stderr?.on("data", (d) => {
      stderr += d.toString();
    });

    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutTimer);
      if (killTimer) clearTimeout(killTimer);
      if (opts?.signal) opts.signal.removeEventListener("abort", onAbort);
      resolve({ code: aborted ? 124 : (code ?? 126), stdout, stderr, aborted });
    });

    child.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutTimer);
      if (killTimer) clearTimeout(killTimer);
      if (opts?.signal) opts.signal.removeEventListener("abort", onAbort);
      resolve({ code: 126, stdout, stderr: `${stderr}\n${err.message}`, aborted });
    });

    try {
      if (opts?.input !== undefined) {
        child.stdin?.write(opts.input);
      }
      child.stdin?.end();
    } catch {
      // ignore EPIPE
    }
  });
}

/** 抢占共享长生命周期 OS WriteLock（在 claim 与写动作之前；EOF 自动释放）。 */
function gcAcquireLockHold(cwd: string, unit: string, runId: string): Promise<GcLockHandle> {
  const launcher = process.env.ATLAS_GC_WRITE_LAUNCHER || process.env.ATLAS_GC_LAUNCHER;
  const continueScript = join(cwd, ".atlas", "scripts", "atlas_continue.py");
  if (!launcher) {
    return Promise.reject(new Error("未配置净化启动器，无法启动 lock-hold"));
  }
  if (!existsSync(continueScript)) {
    return Promise.reject(new Error("缺 atlas_continue.py，无法启动 lock-hold"));
  }
  const lockToken = randomBytes(16).toString("hex");
  return new Promise((resolve, reject) => {
    const child = spawn(
      launcher,
      ["/dev/null", continueScript, "lock-hold", "--root", cwd, "--unit", unit, "--run-dir", runId],
      { cwd, stdio: ["pipe", "pipe", "pipe"] },
    );
    let stdout = "";
    let stderr = "";
    let ready = false;
    let exited = false;
    let exitPromiseResolve: (() => void) | null = null;
    const exitPromise = new Promise<void>((res) => {
      exitPromiseResolve = res;
    });

    const timer = setTimeout(() => {
      if (!ready) {
        try { child.kill("SIGTERM"); } catch { /* ignore */ }
        reject(new Error(`lock-hold 超时：${stderr.slice(0, 160)}`));
      }
    }, 10_000);

    const release = async (): Promise<void> => {
      if (exited) return;
      try {
        child.stdin?.end();
      } catch {
        // ignore
      }
      const killFallback = setTimeout(() => {
        if (!exited) {
          try { child.kill("SIGTERM"); } catch { /* ignore */ }
        }
      }, 1000);
      await Promise.race([
        exitPromise,
        new Promise<void>((res) => setTimeout(res, 2000)),
      ]);
      clearTimeout(killFallback);
    };

    child.stdout?.on("data", (d) => {
      stdout += d.toString();
      if (!ready && stdout.includes("LOCKED\n")) {
        ready = true;
        clearTimeout(timer);
        resolve({ lockToken, release });
      }
    });
    child.stderr?.on("data", (d) => {
      stderr += d.toString();
    });
    child.on("close", (code) => {
      exited = true;
      exitPromiseResolve?.();
      if (!ready) {
        clearTimeout(timer);
        reject(new Error(`写锁抢占失败（rc=${code}）：${(stderr || stdout).trim().slice(0, 200)}`));
      }
    });
    child.on("error", (err) => {
      exited = true;
      exitPromiseResolve?.();
      if (!ready) {
        clearTimeout(timer);
        reject(new Error(`lock-hold 启动失败：${err.message}`));
      }
    });
    try {
      child.stdin?.write(JSON.stringify({ token: lockToken }) + "\n");
    } catch (err: any) {
      clearTimeout(timer);
      reject(new Error(`lock-hold stdin 写入失败：${err?.message ?? err}`));
    }
  });
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
  const res = spawnSync(PYTHON, ["-B", script, "--root", cwd, flag, key], { encoding: "utf8" });
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
          // v16 M3 门校准：只读链（progress/status）收窄为已装配；P2 写链强制要求全开户 + 双启动器 + 两段确认。
          if (!status.isAtlasProject) {
            ctx.ui.notify("Guarded Continuation：项目未装配 Atlas，拒绝签发票据", "warning");
            return;
          }
          const unit = args.trim().split(/\s+/)[1];
          if (!unit || !GC_UNIT_RE.test(unit)) {
            ctx.ui.notify("用法：/atlas approve-continuation <unit>（合法任务标识）", "warning");
            return;
          }
          const plan = gcPlanBytes(ctx.cwd, unit);
          if (!plan) {
            ctx.ui.notify(`计划不存在：.atlas/tasks/${unit}/continuation.json（人审后落盘）`, "warning");
            return;
          }
          let planActions: Array<{ id: string; tool: string; args: Record<string, string> }> = [];
          try {
            const parsed = JSON.parse(plan.bytes.toString("utf8")) as {
              schema: number;
              unit: string;
              actions: typeof planActions;
            };
            if (parsed.schema !== 1 || parsed.unit !== unit) throw new Error("schema/unit 不一致");
            const seenWriteTools: string[] = [];
            for (const a of parsed.actions) {
              if (!GC_ALLOWED_TOOLS.has(a.tool)) throw new Error(`非法动作 ${a.tool}`);
              if (!a.args || a.args.unit !== unit || Object.keys(a.args).length !== 1) {
                throw new Error("args 只允许 {unit}");
              }
              if (a.tool in GC_WRITE_RANK) {
                if (seenWriteTools.includes(a.tool)) throw new Error(`写动作不允许重复：${a.tool}`);
                const last = seenWriteTools[seenWriteTools.length - 1];
                if (last && GC_WRITE_RANK[a.tool] <= GC_WRITE_RANK[last]) {
                  throw new Error(`P2 写链动作顺序非法：${last} -> ${a.tool}`);
                }
                if (a.tool !== "atlas_workflow_finish_preflight" && !seenWriteTools.includes("atlas_workflow_finish_preflight")) {
                  throw new Error(`P2 写动作 ${a.tool} 前必须先有 preflight`);
                }
                seenWriteTools.push(a.tool);
              }
              planActions.push(a);
            }
          } catch (e: any) {
            ctx.ui.notify(`计划契约校验失败：${e.message}`, "warning");
            return;
          }
          const isWritePlan = planActions.some((a) => GC_WRITE_TOOLS.has(a.tool));
          const hasMutatingWrite = planActions.some((a) => GC_MUTATING_WRITE_TOOLS.has(a.tool));
          if (isWritePlan) {
            if (status.onboarding !== "done") {
              ctx.ui.notify(
                `Guarded Continuation P2 写链要求完整开户（当前：${ONBOARDING_LABEL[status.onboarding]}），先补齐 PRD 与 _meta.json`,
                "warning",
              );
              return;
            }
            if (!gcHasLauncher("ATLAS_GC_LAUNCHER") || !gcHasLauncher("ATLAS_GC_WRITE_LAUNCHER")) {
              ctx.ui.notify("Guarded Continuation P2 写链要求 ATLAS_GC_LAUNCHER 与 ATLAS_GC_WRITE_LAUNCHER 均已冻结且可执行", "warning");
              return;
            }
          }
          if (gcTickets.has(unit) || gcActive?.unit === unit) {
            ctx.ui.notify(`unit ${unit} 已有治理态，先 revoke 或 recover`, "warning");
            return;
          }
          if (gcIsolatedUnits.has(unit)) {
            ctx.ui.notify(`unit ${unit} 处于隔离/封锁状态，先 /atlas recover-continuation ${unit}`, "warning");
            return;
          }
          const existingMarker = gcMarkerPath(ctx.cwd, unit);
          if (existsSync(existingMarker)) {
            const mk = JSON.parse(readFileSync(existingMarker, "utf-8")) as { state?: string };
            if (mk.state && !GC_TERMINAL_STATES.has(mk.state)) {
              ctx.ui.notify(`unit ${unit} 有非终态标记（${mk.state}），先 /atlas recover-continuation ${unit}`, "warning");
              return;
            }
          }
          const runId = `gc-${Date.now()}-${randomBytes(4).toString("hex")}`;
          let preflightNote = "";
          if (isWritePlan) {
            const continueScript = join(ctx.cwd, ".atlas", "scripts", "atlas_continue.py");
            if (!existsSync(continueScript)) {
              ctx.ui.notify("采纳仓缺 .atlas/scripts/atlas_continue.py，无法运行 P2 预检", "warning");
              return;
            }
            const tmpLogDir = mkdtempSync(join(tmpdir(), "atlas-gc-preflight-"));
            try {
              const pre = gcLauncher(
                ctx.cwd,
                join(tmpLogDir, "git-calls.jsonl"),
                continueScript,
                ["preflight", "--root", ctx.cwd, "--unit", unit],
                60_000,
              );
              if (pre.code !== 0) {
                let reason = (pre.stderr || pre.stdout).trim();
                try {
                  const parsed = JSON.parse(pre.stdout.trim().split("\n").pop() || "{}") as { detail?: string; cause?: string };
                  reason = `${parsed.cause ?? "preflight_failed"}: ${parsed.detail ?? reason}`;
                } catch { /* keep raw */ }
                ctx.ui.notify(`P2 纯只读预检未通过，拒绝签发票据：${reason.slice(0, 300)}`, "warning");
                return;
              }
              try {
                const preObj = JSON.parse(pre.stdout.trim().split("\n").pop() || "{}") as {
                  head_commit?: string;
                  staged_files?: string[];
                  archive_dest?: string;
                };
                preflightNote =
                  `\n预检 HEAD=${(preObj.head_commit ?? "").slice(0, 12)}，` +
                  `暂存文件 ${(preObj.staged_files ?? []).length} 个，归档目标 ${preObj.archive_dest ?? "?"}`;
              } catch { /* optional */ }
            } finally {
              try { rmSync(tmpLogDir, { recursive: true, force: true }); } catch { /* ignore */ }
            }
          }
          const listing = planActions
            .map((a, i) => `  ${i + 1}. ${a.id}: ${a.tool}({unit:"${a.args.unit}"})`)
            .join("\n");
          const onboardingNote = !isWritePlan && status.onboarding !== "done"
            ? `\n⚠️ 结构基线未就绪（${ONBOARDING_LABEL[status.onboarding]}）：只读链不受影响；写链（P2）必须先补开户。`
            : "";
          const okConfirm1 = await ctx.ui.confirm(
            `批准 continuation 计划 ${unit}？`,
            `run_id: ${runId}\n计划哈希: ${plan.sha256.slice(0, 16)}…\n动作链（${isWritePlan ? "P2 写链" : "P1 只读链"}）：\n${listing}\n票据 5 分钟内有效、一次消费；ARMED 期间默认拒绝所有模型工具。${preflightNote}${onboardingNote}`,
          );
          if (!okConfirm1) {
            ctx.ui.notify("已取消：未签发票据", "info");
            return;
          }
          let irreversibleAck = false;
          if (isWritePlan) {
            const okConfirm2 = await ctx.ui.confirm(
              `二次确认：不可逆业务写链 ${unit}（${runId}）`,
              hasMutatingWrite
                ? `本次动作将真实写入 deferred.md / task.json(completed) / git commit / archive 迁出。\n写启动后若发生非零、中断或三方校验不确定将立即转入 UNKNOWN 并持久封锁，严格禁止自动重放。确认显式授权执行？`
                : `本次 P2 计划仅含预检（无不可逆写动作），仍将绑定 run_id=${runId} 并在双路径审计。确认继续？`,
            );
            if (!okConfirm2) {
              ctx.ui.notify("已取消二次确认：未签发票据（仓库零写盘）", "info");
              return;
            }
            irreversibleAck = true;
          }
          gcWriteMarker(ctx.cwd, unit, {
            state: "ARMED",
            mode: isWritePlan ? "write" : "read",
            run_id: runId,
            plan_sha256: plan.sha256,
            session_id: ctx.sessionManager.getSessionId(),
            armed_at: new Date().toISOString(),
          });
          gcTickets.set(unit, {
            unit,
            planSha256: plan.sha256,
            sessionId: ctx.sessionManager.getSessionId(),
            nonce: randomBytes(8).toString("hex"),
            expiryMs: Date.now() + 5 * 60_000,
            consumed: false,
            runId,
            isWrite: isWritePlan,
            irreversibleAck,
          });
          ctx.ui.notify(`✅ ${unit} 已 ARMED（run_id=${runId}，票据 5 分钟有效、一次消费）。模型现在只能调用 atlas_continue。`, "info");
          break;
        }

        case "revoke-continuation": {
          const unit = args.trim().split(/\s+/)[1];
          if (!unit || !GC_UNIT_RE.test(unit)) {
            ctx.ui.notify("用法：/atlas revoke-continuation <unit>", "warning");
            return;
          }
          const existingMarkerPath = gcMarkerPath(ctx.cwd, unit);
          if (existsSync(existingMarkerPath)) {
            let mk: { state?: string; run_id?: string } = {};
            try {
              mk = JSON.parse(readFileSync(existingMarkerPath, "utf-8")) as { state?: string; run_id?: string };
            } catch {
              ctx.ui.notify(`标记损坏，禁止直接 revoke；请走 /atlas recover-continuation ${unit}`, "warning");
              return;
            }
            const protectedStates = new Set(["UNKNOWN", "ISOLATED", "WRITING", "RUNNING", "RECORDED", "AUDIT_FAILED"]);
            if ((mk.state && protectedStates.has(mk.state)) || (mk.run_id && !GC_TERMINAL_STATES.has(mk.state ?? ""))) {
              ctx.ui.notify(
                `拒绝撤销：${unit} 当前处于 ${mk.state}（run_id=${mk.run_id ?? "-"}），请先走 /atlas recover-continuation ${unit}（严禁洗白 UNKNOWN/未审计态）`,
                "warning",
              );
              return;
            }
          }
          gcTickets.delete(unit);
          if (gcActive?.unit === unit) {
            ctx.ui.notify(`unit ${unit} 有活跃 run（${gcActive.runId}），拒绝覆盖；等待审计结束`, "warning");
            return;
          }
          gcWriteMarker(ctx.cwd, unit, { state: "REVOKED", revoked_at: new Date().toISOString() });
          ctx.ui.notify(`✅ ${unit} 票据已撤销`, "info");
          break;
        }

        case "recover-continuation": {
          // P1 重试审计（不重跑动作）；P2 UNKNOWN/崩溃只读诊断后经人类确认仅写 CLOSED_FAILED（严禁自动重放）。
          const unit = args.trim().split(/\s+/)[1];
          if (!unit || !GC_UNIT_RE.test(unit)) {
            ctx.ui.notify("用法：/atlas recover-continuation <unit>", "warning");
            return;
          }
          const markerPath = gcMarkerPath(ctx.cwd, unit);
          if (!existsSync(markerPath)) {
            ctx.ui.notify(`无治理标记：${markerPath}`, "warning");
            return;
          }
          const marker = JSON.parse(readFileSync(markerPath, "utf-8")) as {
            state: string;
            run_id?: string;
            parent_tool_call_id?: string;
            expected_parent_result_sha256?: string;
          };
          if (GC_TERMINAL_STATES.has(marker.state)) {
            ctx.ui.notify(`unit ${unit} 已是终态 ${marker.state}，无需 recover`, "info");
            return;
          }
          const continueScript = join(ctx.cwd, ".atlas", "scripts", "atlas_continue.py");
          const runDirForWal = marker.run_id ? join(ctx.cwd, ".atlas", "runs", "continuations", marker.run_id) : "";
          const hasWal = Boolean(runDirForWal && existsSync(join(runDirForWal, "wal.jsonl")));
          const missingReceipt = Boolean(runDirForWal && !existsSync(join(runDirForWal, "execution-receipt.json")));
          if (marker.state === "UNKNOWN" || marker.state === "WRITING" || hasWal || (marker.run_id && missingReceipt && marker.state !== "ARMED")) {
            let diagText = `marker.state=${marker.state}, run_id=${marker.run_id ?? "-"}`;
            if (marker.run_id && existsSync(continueScript) && gcHasLauncher("ATLAS_GC_LAUNCHER")) {
              const tmpDir = mkdtempSync(join(tmpdir(), "atlas-gc-diag-"));
              try {
                const diagRes = gcLauncher(
                  ctx.cwd,
                  join(tmpDir, "git-calls.jsonl"),
                  continueScript,
                  ["diagnose-unknown", "--root", ctx.cwd, "--unit", unit, "--run-dir", marker.run_id],
                  30_000,
                );
                if (diagRes.code === 0 && diagRes.stdout.trim()) {
                  diagText = diagRes.stdout.trim();
                }
              } finally {
                try { rmSync(tmpDir, { recursive: true, force: true }); } catch { /* ignore */ }
              }
            }
            const okResolve = await ctx.ui.confirm(
              `崩溃/UNKNOWN 恢复确认（零自动重放）：${unit}`,
              `只读诊断结果：\n${diagText.slice(0, 700)}\n\n严禁自动重放任何写动作。确认人工已核对现态并将其关闭为 CLOSED_FAILED？`,
            );
            if (!okResolve) {
              ctx.ui.notify("已取消恢复：保持封锁状态，等待人工检查", "info");
              return;
            }
            gcIsolatedUnits.delete(unit);
            gcWriteMarker(
              ctx.cwd,
              unit,
              {
                state: "CLOSED_FAILED",
                resolved_from_unknown: true,
                previous_state: marker.state,
                run_id: marker.run_id ?? null,
                resolved_at: new Date().toISOString(),
              },
              { allowOverwriteUnknown: true },
            );
            ctx.ui.notify(`✅ ${unit} 已人工关闭为 CLOSED_FAILED（零自动重放）`, "info");
            return;
          }
          if (!marker.run_id || !marker.parent_tool_call_id || !marker.expected_parent_result_sha256) {
            ctx.ui.notify(`标记缺 run 上下文（${marker.state}）：需人工核对后处置`, "warning");
            return;
          }
          gcIsolatedUnits.delete(unit);
          gcPendingAudit.push({
            unit,
            runId: marker.run_id,
            parentToolCallId: marker.parent_tool_call_id,
            expectedHash: marker.expected_parent_result_sha256,
          });
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
      const res = await pi.exec(PYTHON, ["-B", checkScript, "--root", ctx.cwd, "--fast", "--json"], {
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
        const rawPath = join(runDirPath, "raw-receipts", `${run.observations.length + 1}-${resultSha.slice(0, 16)}.json`);
        const receiptText = JSON.stringify({
          canonical_hash: resultSha,
          result,
          toolCallId, toolName,
          args: { unit: params.unit },
          written_at: new Date().toISOString(),
        }, null, 2) + "\n";
        gcWriteExclusiveText(rawPath, receiptText);
        gcRawCommits.set(toolCallId, {
          resultSha256: resultSha,
          fileSha256: createHash("sha256").update(receiptText).digest("hex"),
          receiptPath: rawPath,
        });
        return result;
      },
    };
  }

  function gcMakeP2Child(
    toolName: string,
    subcommand: "preflight" | "write-deferred" | "write-commit" | "write-archive",
    opts: { mutating: boolean; destructive: boolean; timeoutMs: number },
  ) {
    return {
      name: toolName,
      label: toolName,
      description: `Atlas P2 写链动作 ${subcommand}（Guarded Continuation 内部子工具，仅由 atlas_continue 嵌套调用）`,
      exposure: "codemode" as const,
      annotations: { readOnlyHint: !opts.mutating, destructiveHint: opts.destructive, openWorldHint: false },
      parameters: Type.Object({ unit: Type.String({ description: "任务单元 ID" }) }),
      async execute(toolCallId: string, params: { unit: string }, signal: AbortSignal, _onUpdate: unknown, childCtx: ExtensionContext) {
        const cwd = childCtx.cwd;
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
        if (!run || run.phase !== "RUNNING" || !run.nextAction) {
          return {
            content: [{ type: "text" as const, text: `${toolName}: 无 RUNNING 治理窗口或动作序号缺失` }],
            details: { tool: toolName, unit: params.unit, exit_code: -1, json_ok: false, authorized: true },
            isError: true,
          };
        }
        const runDirPath = join(cwd, ".atlas", "runs", "continuations", run.runId);
        const gcLog = join(runDirPath, "git-calls.jsonl");
        const continueScript = join(cwd, ".atlas", "scripts", "atlas_continue.py");
        const gcOffset = gcGitLogOffsets.get(gcLog) ?? 0;
        const gcSizeBefore = existsSync(gcLog) ? statSync(gcLog).size : 0;
        const t0 = Date.now();
        const cliArgs = opts.mutating
          ? [subcommand, "--root", cwd, "--unit", params.unit, "--run-dir", run.runId,
             "--action-index", String(run.nextAction.index), "--action-id", run.nextAction.id]
          : [subcommand, "--root", cwd, "--unit", params.unit];
        const launcherEnv = opts.mutating ? "ATLAS_GC_WRITE_LAUNCHER" : "ATLAS_GC_LAUNCHER";
        const stdinInput = opts.mutating ? JSON.stringify({ lock_token: run.lockToken ?? "" }) : undefined;
        const res = await gcLauncherAsync(cwd, launcherEnv, gcLog, continueScript, cliArgs, opts.timeoutMs, {
          input: stdinInput,
          signal,
        });
        const cliDurationMs = Date.now() - t0;
        const exitCode = res.code;
        let jsonOk = false;
        let parsedOut: Record<string, unknown> = {};
        try {
          const line = res.stdout.trim().split("\n").filter(Boolean).pop() ?? "";
          parsedOut = JSON.parse(line) as Record<string, unknown>;
          jsonOk = true;
        } catch {
          jsonOk = false;
        }
        let gitCallsOk = true;
        try {
          if (gcSizeBefore > gcOffset) gitCallsOk = false;
          const sizeAfter = existsSync(gcLog) ? statSync(gcLog).size : gcSizeBefore;
          if (sizeAfter > gcOffset) {
            const chunk = readFileSync(gcLog, "utf-8").slice(gcOffset);
            for (const ln of chunk.split("\n")) {
              if (!ln.trim()) continue;
              const rec = JSON.parse(ln) as { rc: number; cmd?: string[] };
              // allow rev-parse/git calls recorded cleanly; rc!=0 only allowed if caller expects? In P2 all allowed git calls must exit 0.
              if (rec.rc !== 0) gitCallsOk = false;
            }
            gcGitLogOffsets.set(gcLog, sizeAfter);
          }
        } catch {
          gitCallsOk = false;
        }
        const isError = exitCode !== 0 || !jsonOk || !gitCallsOk || res.aborted;
        const result = {
          content: [{
            type: "text" as const,
            text: isError
              ? `${toolName} FAILED unit=${params.unit} (exit=${exitCode} json_ok=${jsonOk} git_ok=${gitCallsOk} aborted=${res.aborted})`
              : `${toolName} ok unit=${params.unit}`,
          }],
          details: {
            tool: toolName,
            unit: params.unit,
            exit_code: exitCode,
            json_ok: jsonOk,
            git_calls_ok: gitCallsOk,
            aborted: res.aborted,
            stdout_bytes: res.stdout.length,
            cli_duration_ms: cliDurationMs,
            wal_commit_payload: parsedOut.wal_commit_payload ?? null,
          },
          isError,
        };
        const resultSha = gcResultHash(result);
        const rawPath = join(runDirPath, "raw-receipts", `${run.observations.length + 1}-${resultSha.slice(0, 16)}.json`);
        const receiptText = JSON.stringify({
          canonical_hash: resultSha,
          result,
          toolCallId, toolName,
          args: { unit: params.unit },
          written_at: new Date().toISOString(),
        }, null, 2) + "\n";
        gcWriteExclusiveText(rawPath, receiptText);
        gcRawCommits.set(toolCallId, {
          resultSha256: resultSha,
          fileSha256: createHash("sha256").update(receiptText).digest("hex"),
          receiptPath: rawPath,
        });
        return result;
      },
    };
  }

  pi.registerTool(gcMakeChild("atlas_workflow_progress", "progress"));
  pi.registerTool(gcMakeChild("atlas_workflow_status", "status"));
  pi.registerTool(gcMakeP2Child("atlas_workflow_finish_preflight", "preflight", { mutating: false, destructive: false, timeoutMs: 60_000 }));
  pi.registerTool(gcMakeP2Child("atlas_workflow_finish_deferred", "write-deferred", { mutating: true, destructive: false, timeoutMs: 60_000 }));
  pi.registerTool(gcMakeP2Child("atlas_workflow_finish_commit", "write-commit", { mutating: true, destructive: true, timeoutMs: 60_000 }));
  pi.registerTool(gcMakeP2Child("atlas_workflow_finish_archive", "write-archive", { mutating: true, destructive: true, timeoutMs: 60_000 }));

  // — 父工具：模型只见它；execute 先前检查 + P2 抢锁 → 原子 claim 票据 —
  pi.registerTool({
    name: "atlas_continue",
    label: "atlas_continue",
    description:
      "Run the human-approved continuation chain for a unit (P1 read-only or P2 governed write chain). " +
      "Requires the human to have approved via /atlas approve-continuation first. Args: {unit} only.",
    exposure: "model-only",
    executionMode: "sequential", // §5.3：父工具串行化声明（PoC 单槽 gcActive）
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
    parameters: Type.Object({ unit: Type.String({ description: "任务单元 ID，与已批准计划一致" }) }),
    async execute(toolCallId: string, params: { unit: string }, signal: AbortSignal, _onUpdate, ctx) {
      const cwd = ctx.cwd;
      const fail = (reason: string) => ({
        content: [{ type: "text" as const, text: `atlas_continue FAILED unit=${params.unit}: ${reason}` }],
        details: { unit: params.unit, actions_ok: false, fail_reason: reason },
        isError: true,
      });
      if (!GC_UNIT_RE.test(params.unit)) return fail("非法 unit 标识");
      const st = detectAtlasStatus(cwd);
      if (!st.isAtlasProject) return fail("项目未装配 Atlas");
      const peek = gcTickets.get(params.unit);
      if (!peek || peek.consumed) return fail("无有效票据（先由人类 /atlas approve-continuation 签发）");
      if (peek.expiryMs < Date.now()) { gcTickets.delete(params.unit); return fail("票据已过期"); }
      if (peek.sessionId !== ctx.sessionManager.getSessionId()) return fail("票据绑定其他 session");
      const peekPlan = gcPlanBytes(cwd, params.unit);
      if (!peekPlan || peek.planSha256 !== peekPlan.sha256) return fail("计划哈希与票据不一致（计划被改）");
      const isWritePlan = Boolean(peek.isWrite);
      const runId = peek.runId ?? `gc-${Date.now()}-${randomBytes(4).toString("hex")}`;
      if (isWritePlan) {
        if (st.onboarding !== "done") return fail("P2 写链要求项目完整开户");
        if (!gcHasLauncher("ATLAS_GC_LAUNCHER") || !gcHasLauncher("ATLAS_GC_WRITE_LAUNCHER")) {
          return fail("P2 写链要求 ATLAS_GC_LAUNCHER 与 ATLAS_GC_WRITE_LAUNCHER 均已冻结");
        }
        if (!peek.irreversibleAck || !peek.runId) {
          return fail("P2 写链票据缺少 runId 或二次不可逆确认");
        }
      }

      // P2：claim 之前先抢占共享长生命周期 WriteLock；失败零落盘且保留票据
      let lockHandle: GcLockHandle | null = null;
      let handedToAudit = false;
      try {
        if (isWritePlan) {
          try {
            lockHandle = await gcAcquireLockHold(cwd, params.unit, runId);
          } catch (lockErr: any) {
            return fail(`共享写锁抢占失败：${lockErr?.message ?? lockErr}`);
          }
        }
        // 原子 claim 票据（复核与消费）
        const ticket = gcTickets.get(params.unit);
        if (!ticket || ticket.consumed || ticket.expiryMs < Date.now()) {
          return fail("票据在锁抢占期间失效");
        }
        if (ticket.sessionId !== ctx.sessionManager.getSessionId() || ticket.planSha256 !== (gcPlanBytes(cwd, params.unit)?.sha256 ?? "")) {
          return fail("票据上下文在 claim 前变化");
        }
        ticket.consumed = true;
        gcTickets.delete(params.unit);
        if (lockHandle) {
          gcActiveLocks.set(runId, lockHandle);
        }

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
          phase: "RUNNING",
          isWrite: isWritePlan,
          writeStarted: false,
          isUnknown: false,
          lockToken: lockHandle?.lockToken,
          observations: [], nextAction: null,
        };
        gcWriteMarker(cwd, params.unit, {
          state: "RUNNING", run_id: runId, parent_tool_call_id: toolCallId,
          plan_sha256: ticket.planSha256, claimed_at: new Date().toISOString(),
        });
        const gcLog = join(runDirPath, "git-calls.jsonl");
        const continueScript = join(cwd, ".atlas", "scripts", "atlas_continue.py");
        const workflowScript = join(cwd, ".atlas", "scripts", "atlas_workflow.py");
        if (!existsSync(continueScript) || !existsSync(workflowScript)) {
          gcWriteMarker(cwd, params.unit, { state: "ISOLATED", run_id: runId, parent_tool_call_id: toolCallId, reason: "缺审计/动作脚本（零前缀窗口）" });
          gcIsolatedUnits.add(params.unit);
          return fail("采纳仓缺 atlas_continue.py / atlas_workflow.py（P1/P2 未部署）");
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
          // 5) 逐动作：verify → guard 前移 → 能力标记 → 真实嵌套 → 三方可账 → (P2 WAL 提交/UNKNOWN)
          const obsMap = new Map<string, GcObservation>();
          let terminalReason = "chain_ok";
          for (let i = 0; i < planDoc.actions.length; i++) {
            const action = planDoc.actions[i];
            const verr = gcLauncher(cwd, gcLog, continueScript,
              ["verify", "--root", cwd, "--unit", params.unit, "--run-dir", runId, "--phase", `pre-action-${i + 1}`], 30_000);
            if (verr.code !== 0) {
              if (gcActive.writeStarted) {
                gcActive.isUnknown = true;
                gcLauncher(cwd, gcLog, continueScript,
                  ["wal-mark-unknown", "--root", cwd, "--unit", params.unit, "--run-dir", runId,
                   "--action-index", String(i + 1), "--action-id", action.id, "--tool", action.tool,
                   "--reason", `verify 失败(动作${i + 1}): ${(verr.stderr || verr.stdout).slice(0, 120)}`], 15_000);
                gcWriteMarker(cwd, params.unit, {
                  state: "UNKNOWN", run_id: runId, parent_tool_call_id: toolCallId,
                  action_index: i + 1, action_id: action.id, tool: action.tool,
                  reason: `verify 失败(动作${i + 1})`,
                });
                gcIsolatedUnits.add(params.unit);
                terminalReason = "UNKNOWN";
              } else {
                terminalReason = `verify 失败(动作${i + 1})`;
              }
              break;
            }
            const guardOk = gcGuardOk(action.guard, obsMap);
            if (!guardOk) { terminalReason = `FALLBACK_REQUIRED: guard false @${action.id}`; break; }
            const isMutatingAction = GC_MUTATING_WRITE_TOOLS.has(action.tool);
            if (isMutatingAction) {
              gcActive.writeStarted = true;
              gcWriteMarker(cwd, params.unit, {
                state: "WRITING", run_id: runId, parent_tool_call_id: toolCallId,
                action_index: i + 1, action_id: action.id, tool: action.tool,
              });
            }
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
            const d = (outcome.result?.details ?? {}) as {
              exit_code?: number;
              json_ok?: boolean;
              wal_commit_payload?: Record<string, unknown> | null;
            };
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
              const reason = threeWayOk
                ? `action ${action.id} isError`
                : `action ${action.id} 三方可账失败（raw 回执与最终值不一致）`;
              if (gcActive.writeStarted) {
                gcActive.isUnknown = true;
                gcLauncher(cwd, gcLog, continueScript,
                  ["wal-mark-unknown", "--root", cwd, "--unit", params.unit, "--run-dir", runId,
                   "--action-index", String(i + 1), "--action-id", action.id, "--tool", action.tool,
                   "--reason", reason], 15_000);
                gcWriteMarker(cwd, params.unit, {
                  state: "UNKNOWN", run_id: runId, parent_tool_call_id: toolCallId,
                  action_index: i + 1, action_id: action.id, tool: action.tool, reason,
                });
                gcIsolatedUnits.add(params.unit);
                terminalReason = "UNKNOWN";
              } else {
                terminalReason = reason;
              }
              break;
            }
            if (isMutatingAction) {
              const wc = gcLauncher(cwd, gcLog, continueScript,
                ["wal-commit", "--root", cwd, "--unit", params.unit, "--run-dir", runId,
                 "--action-index", String(i + 1), "--action-id", action.id, "--tool", action.tool,
                 "--detail-json", JSON.stringify(d.wal_commit_payload ?? {})], 15_000);
              if (wc.code !== 0) {
                const reason = `wal-commit 失败: ${(wc.stderr || wc.stdout).slice(0, 160)}`;
                gcActive.isUnknown = true;
                gcLauncher(cwd, gcLog, continueScript,
                  ["wal-mark-unknown", "--root", cwd, "--unit", params.unit, "--run-dir", runId,
                   "--action-index", String(i + 1), "--action-id", action.id, "--tool", action.tool,
                   "--reason", reason], 15_000);
                gcWriteMarker(cwd, params.unit, {
                  state: "UNKNOWN", run_id: runId, parent_tool_call_id: toolCallId,
                  action_index: i + 1, action_id: action.id, tool: action.tool, reason,
                });
                gcIsolatedUnits.add(params.unit);
                terminalReason = "UNKNOWN";
                break;
              }
            }
          }
          // 6) record：原子写执行回执（RECORDED）→ 追加封印 →（若未进 UNKNOWN 才更新 marker 为 RECORDED）
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
          gcAtomicWriteText(payloadPath, JSON.stringify({
            run_id: runId, unit: params.unit, plan_sha256: ticket.planSha256,
            status: gcActive.isUnknown ? "UNKNOWN" : "RECORDED",
            terminal_reason: terminalReason,
            session_id: ctx.sessionManager.getSessionId(),
            parent_tool_call_id: toolCallId, parent_tool_name: "atlas_continue",
            expected_parent_result_sha256: expectedParentHash,
            input_manifest_sha256: inputManifestSha,
            actions: gcActive.observations,
          }, null, 2) + "\n");
          const rec = gcLauncher(cwd, gcLog, continueScript,
            ["record", "--root", cwd, "--unit", params.unit, "--run-dir", runId, "--receipt-json", payloadPath], 30_000);
          if (rec.code !== 0) {
            if (!gcActive.isUnknown && !gcMarkerIsUnknown(cwd, params.unit)) {
              gcWriteMarker(cwd, params.unit, { state: "ISOLATED", run_id: runId, parent_tool_call_id: toolCallId, reason: "record 失败" });
            }
            gcIsolatedUnits.add(params.unit);
            return fail(`record 失败: ${(rec.stderr || rec.stdout).slice(0, 200)}`);
          }
          gcActive.phase = "RECORDED";
          if (!gcActive.isUnknown && !gcMarkerIsUnknown(cwd, params.unit)) {
            gcWriteMarker(cwd, params.unit, {
              state: "RECORDED", run_id: runId, parent_tool_call_id: toolCallId,
              plan_sha256: ticket.planSha256,
              expected_parent_result_sha256: expectedParentHash,
              terminal_reason: terminalReason,
              recorded_at: new Date().toISOString(),
            });
          }
          pi.appendEntry("atlas-continuation-seal", {
            runId, unit: params.unit,
            sessionId: ctx.sessionManager.getSessionId(),
            parentToolCallId: toolCallId, parentToolName: "atlas_continue",
            expectedParentResultHash: expectedParentHash,
            expectedActions: planDoc.actions.map((a) => ({ index: a.id, tool: a.tool })),
            sealedAt: new Date().toISOString(),
          });
          gcPendingAudit.push({ unit: params.unit, runId, parentToolCallId: toolCallId, expectedHash: expectedParentHash });
          handedToAudit = true;
          return {
            content: parentResult.content,
            details: parentResult.details,
            isError: parentResult.isError,
          };
        } catch (e: any) {
          if (gcActive?.writeStarted) {
            gcActive.isUnknown = true;
            try {
              gcLauncher(cwd, gcLog, continueScript,
                ["wal-mark-unknown", "--root", cwd, "--unit", params.unit, "--run-dir", runId,
                 "--reason", String(e?.message ?? e)], 15_000);
            } catch { /* ignore */ }
            gcWriteMarker(cwd, params.unit, {
              state: "UNKNOWN", run_id: runId, parent_tool_call_id: toolCallId,
              reason: String(e?.message ?? e),
            });
            gcIsolatedUnits.add(params.unit);
          } else if (!gcMarkerIsUnknown(cwd, params.unit)) {
            const state = gcActive?.phase === "CLAIMED_NO_RUN" ? "CLAIMED_NO_RUN" : "ISOLATED";
            gcWriteMarker(cwd, params.unit, {
              state, run_id: runId, parent_tool_call_id: toolCallId,
              reason: String(e?.message ?? e),
            });
            if (state === "ISOLATED") gcIsolatedUnits.add(params.unit);
          }
          return fail(String(e?.message ?? e));
        } finally {
          gcActive = null;
        }
      } finally {
        if (!handedToAudit && lockHandle) {
          gcActiveLocks.delete(runId);
          await lockHandle.release();
        }
      }
    },
  });

  // — agent_settled / session_shutdown：同一审计函数（M2：双路径都必须活着；结束即释放 write.lock）—
  async function gcRunAudit(_pi: ExtensionAPI, ctx: ExtensionContext, unitFilter?: string): Promise<void> {
    const jobs = gcPendingAudit.splice(0).filter((j) => !unitFilter || j.unit === unitFilter);
    for (const job of jobs) {
      const cwd = ctx.cwd;
      const runDirPath = join(cwd, ".atlas", "runs", "continuations", job.runId);
      const unknownLocked = gcMarkerIsUnknown(cwd, job.unit);
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
          if (!unknownLocked && !gcMarkerIsUnknown(cwd, job.unit)) {
            gcWriteMarker(cwd, job.unit, { state: "ISOLATED", run_id: job.runId, parent_tool_call_id: job.parentToolCallId, reason: "session 缺父结果或封印" });
          }
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
        gcAtomicWriteText(join(runDirPath, "host-record.json"), JSON.stringify(hostRecord, null, 2) + "\n");
        const sessionFile = ctx.sessionManager.getSessionFile();
        const continueScript = join(cwd, ".atlas", "scripts", "atlas_continue.py");
        if (!sessionFile || !existsSync(continueScript)) {
          if (!unknownLocked && !gcMarkerIsUnknown(cwd, job.unit)) {
            gcWriteMarker(cwd, job.unit, { state: "ISOLATED", run_id: job.runId, parent_tool_call_id: job.parentToolCallId, reason: "缺 session 文件或审计脚本" });
          }
          gcIsolatedUnits.add(job.unit);
          continue;
        }
        const res = gcLauncher(cwd, join(runDirPath, "git-calls.jsonl"), continueScript,
          ["audit", "--root", cwd, "--unit", job.unit, "--run-dir", job.runId,
           "--session", sessionFile, "--host-record", join(runDirPath, "host-record.json"),
           "--atlas-version", detectAtlasStatus(cwd).version ?? "poc"], 60_000);
        let verdict = "";
        let archivedTaskDir: string | undefined;
        try {
          const outObj = JSON.parse(res.stdout.trim().split("\n").filter(Boolean).pop() ?? "{}") as {
            verdict?: string;
            archived_task_dir?: string;
          };
          verdict = outObj.verdict ?? "";
          archivedTaskDir = outObj.archived_task_dir;
        } catch { /* fallthrough */ }

        if (verdict === "UNKNOWN" || unknownLocked || gcMarkerIsUnknown(cwd, job.unit)) {
          gcIsolatedUnits.add(job.unit);
          if (!gcMarkerIsUnknown(cwd, job.unit)) {
            gcWriteMarker(cwd, job.unit, {
              state: "UNKNOWN", run_id: job.runId, parent_tool_call_id: job.parentToolCallId,
              reason: "审计发现 WAL UNKNOWN / 悬空 INTENT，保持封锁禁止自动重放",
            });
          }
          if (ctx.hasUI && ctx.ui.notify) {
            ctx.ui.notify(
              `🚨 Guarded Continuation：${job.unit} 处于 UNKNOWN 封锁（${job.runId}），禁止自动重放；请运行 /atlas recover-continuation ${job.unit}`,
              "warning",
            );
          }
          continue;
        }

        if (res.code === 0 && verdict === "SUCCEEDED") {
          gcWriteMarker(cwd, job.unit, {
            state: "SUCCEEDED", run_id: job.runId,
            parent_tool_call_id: job.parentToolCallId,
            certificate: join(runDirPath, "certificate.json"),
            archived_task_dir: archivedTaskDir ?? null,
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
          gcIsolatedUnits.add(job.unit);
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
          if (!gcMarkerIsUnknown(cwd, job.unit)) {
            gcWriteMarker(cwd, job.unit, { state: "ISOLATED", run_id: job.runId, parent_tool_call_id: job.parentToolCallId, reason: String(e?.message ?? e) });
          }
          gcIsolatedUnits.add(job.unit);
        } catch { /* 尽力持久化 */ }
      } finally {
        const lh = gcActiveLocks.get(job.runId);
        if (lh) {
          gcActiveLocks.delete(job.runId);
          await lh.release();
        }
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
