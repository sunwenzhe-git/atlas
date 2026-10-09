#!/usr/bin/env node
const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const PKG_ROOT = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const command = args[0] || 'help';

function printHelp() {
  console.log(`
Atlas — 践行 Project Harness 的全流程 AI 编程工作流治理引擎

用法:
  atlas <command> [options]

命令:
  init      一键初始化并装配 Atlas 工作流到当前项目（或指定目录）
  check     运行项目级资产与门禁全套检查
  console   启动本地 E2E 用例评审控制台 (http://127.0.0.1:4190)
  report    将流水线设计冲突或缺陷自感知上报至云端设计池
  version   查看当前版本
  help      查看帮助信息

示例:
  atlas init                  # 在当前项目初始化装配
  atlas init --target /path   # 在指定项目初始化装配
  atlas check --fast          # 运行快速门禁体检
  atlas console               # 启动可视化 E2E 评审控制台
  atlas report --title "..."  # 上报流水线设计缺陷或规则冲突
`);
}

switch (command) {
  case 'init': {
    const installScript = path.join(PKG_ROOT, 'install.sh');
    const passthroughArgs = args.slice(1);
    
    // 如果没有指定 --target，默认使用当前工作目录
    let hasTarget = false;
    let targetDir = process.cwd();
    for (let i = 0; i < passthroughArgs.length; i++) {
      if (passthroughArgs[i] === '--target' && passthroughArgs[i + 1]) {
        targetDir = path.resolve(passthroughArgs[i + 1]);
        hasTarget = true;
        break;
      }
    }
    const finalArgs = hasTarget ? passthroughArgs : ['--target', targetDir, ...passthroughArgs];
    
    // Trellis 环境检测与自动初始化引导
    const trellisDir = path.join(targetDir, '.trellis');
    if (!fs.existsSync(trellisDir)) {
      const hasTrellis = spawnSync('which', ['trellis']).status === 0;
      if (hasTrellis) {
        console.log('\n[Atlas] 检测到目标项目尚未初始化 Trellis (.trellis/ 缺失)。');
        console.log('[Atlas] 正在自动运行 trellis init 初始化状态机骨架...');
        const initRes = spawnSync('trellis', ['init'], {
          cwd: targetDir,
          stdio: 'inherit',
          env: process.env,
        });
        if (initRes.status !== 0) {
          console.warn('[Atlas] ⚠️ 警告: trellis init 执行异常，继续执行 Atlas 装配...');
        }
      } else {
        console.warn('\n[Atlas] ⚠️ 提示: 未检测到 Trellis CLI。');
        console.warn('[Atlas] Atlas 需求级执行依赖 Trellis，建议稍后安装:');
        console.warn('        npm install -g @mindfoldhq/trellis\n');
      }
    }

    const res = spawnSync('bash', [installScript, ...finalArgs], {
      stdio: 'inherit',
      env: process.env,
    });

    // 自动挂载 Pi Agent 扩展 (如果环境存在 ~/.pi)
    try {
      const os = require('os');
      const homeDir = os.homedir();
      if (fs.existsSync(path.join(homeDir, '.pi'))) {
        const piExtDir = path.join(homeDir, '.pi', 'agent', 'extensions');
        fs.mkdirSync(piExtDir, { recursive: true });
        const srcExt = path.join(PKG_ROOT, 'extensions', 'pi.ts');
        if (fs.existsSync(srcExt)) {
          fs.copyFileSync(srcExt, path.join(piExtDir, 'atlasharness.ts'));
          console.log('\n[Atlas] 🚀 已自动挂载 Pi Agent 扩展: ~/.pi/agent/extensions/atlasharness.ts');
          console.log('[Atlas]    可在 Pi 中使用 /atlas 命令驱动全流程。\n');
        }
      }
    } catch (_) {}

    process.exit(res.status || 0);
    break;
  }

  case 'check': {
    const passthroughArgs = args.slice(1);
    const targetDir = process.cwd();
    const scriptPath = path.join(targetDir, '.atlas', 'scripts', 'atlas_check.py');
    const fallbackScript = path.join(PKG_ROOT, 'scripts', 'atlas_check.py');
    const runScript = fs.existsSync(scriptPath) ? scriptPath : fallbackScript;

    const res = spawnSync('python3', [runScript, '--root', targetDir, ...passthroughArgs], {
      stdio: 'inherit',
      env: process.env,
    });
    process.exit(res.status || 0);
    break;
  }

  case 'console': {
    const passthroughArgs = args.slice(1);
    const targetDir = process.cwd();
    const scriptPath = path.join(targetDir, '.atlas', 'scripts', 'e2e_console.py');
    const fallbackScript = path.join(PKG_ROOT, 'scripts', 'e2e_console.py');
    const runScript = fs.existsSync(scriptPath) ? scriptPath : fallbackScript;

    console.log(`正在启动 E2E 用例评审控制台... (目标目录: ${targetDir})`);
    const res = spawnSync('python3', [runScript, '--root', targetDir, ...passthroughArgs], {
      stdio: 'inherit',
      env: process.env,
    });
    process.exit(res.status || 0);
    break;
  }

  case 'report': {
    const passthroughArgs = args.slice(1);
    const targetDir = process.cwd();
    const scriptPath = path.join(targetDir, '.atlas', 'scripts', 'atlas_report.py');
    const fallbackScript = path.join(PKG_ROOT, 'scripts', 'atlas_report.py');
    const runScript = fs.existsSync(scriptPath) ? scriptPath : fallbackScript;

    const res = spawnSync('python3', [runScript, '--root', targetDir, ...passthroughArgs], {
      stdio: 'inherit',
      env: process.env,
    });
    process.exit(res.status || 0);
    break;
  }

  case '-v':
  case '--version':
  case 'version': {
    const pkg = require(path.join(PKG_ROOT, 'package.json'));
    console.log(`atlasharness v${pkg.version}`);
    break;
  }

  case '-h':
  case '--help':
  case 'help':
  default:
    printHelp();
    break;
}
