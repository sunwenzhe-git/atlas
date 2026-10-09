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
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const EXTENSION_NAME = "atlasharness";

interface AtlasProjectStatus {
  isAtlasProject: boolean;
  hasTrellis: boolean;
  hasStackProfile: boolean;
  version?: string;
}

function detectAtlasStatus(cwd: string): AtlasProjectStatus {
  const hasAtlasDir = existsSync(join(cwd, ".atlas"));
  const hasStackProfile = existsSync(join(cwd, "product", "stack-profile.yaml"));
  const hasTrellis = existsSync(join(cwd, ".trellis"));

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
    hasTrellis,
    hasStackProfile,
    version,
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
        { value: "status", label: "status", description: "查看当前工作区 Atlas 与 Trellis 状态" },
        { value: "console", label: "console", description: "打开可视化 E2E 走查控制台" },
        { value: "init", label: "init", description: "在当前项目装配 Atlas 与 Trellis 联动" },
        { value: "report", label: "report", description: "上报流水线设计缺陷或规则冲突" },
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
            `  - Trellis 接入: ${status.hasTrellis ? "已接入" : "未检测到 (.trellis/ 缺失)"}`,
            `  - 技术栈画像: ${status.hasStackProfile ? "已配置 (product/stack-profile.yaml)" : "未配置"}`,
          ];
          if (!status.isAtlasProject) {
            lines.push(``, `提示: 当前项目尚未接入 Atlas。使用 \`/atlas init\` 即可一键装配。`);
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
            ? ["python3", checkScript, "--root", ctx.cwd]
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
              ctx.ui.notify("🎉 Atlas 装配成功！已联动配置 Trellis 与 Skills。", "info");
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

        default: {
          ctx.ui.notify(
            `未知子命令 "${sub}"。可用选项: status, check, init, console, report`,
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

    // 设置状态栏
    if (ctx.hasUI && ctx.ui.setStatus) {
      ctx.ui.setStatus("atlas", `Atlas 🛡️ (${status.version || "active"})`);
    }

    // 若系统提示词中尚未提及 atlas 规则，轻量级注入 Project Harness 边界
    const prompt = event.systemPrompt ?? "";
    if (prompt.includes("atlas — 全流程工作流") || prompt.includes("Project Harness")) {
      return {};
    }

    const atlasContextNotice = `\n\n# Atlas Project Harness Notice\n` +
      `This project is governed by **Atlas** (.atlas/). ` +
      `All requirements and implementations must adhere to the deterministic specs in \`.atlas/shared/\`, ` +
      `Trellis plan steps (step 1.6 atlas apply), and verified E2E gates. ` +
      `Do not bypass or remove atlas validation gates.\n`;

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

    // 检查是否存在 surface-guard 脚本或快速门禁脚本
    const checkScript = join(ctx.cwd, ".atlas", "scripts", "atlas_check.py");
    if (!existsSync(checkScript)) return;

    // 只做轻量校验（若支持 --fast）
    try {
      const res = await pi.exec("python3", [checkScript, "--root", ctx.cwd, "--fast"], {
        timeout: 10_000,
      });
      if (res.code !== 0) {
        ctx.ui.notify("⚠️ Atlas 提示：本轮操作可能触发了机器门禁异常，建议使用 `/atlas check` 检查", "warning");
      }
    } catch {
      // 容错不阻断
    }
  });
}
