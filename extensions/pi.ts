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
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

const EXTENSION_NAME = "atlasharness";

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
}
