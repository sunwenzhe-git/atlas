#!/usr/bin/env node
const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const PKG_ROOT = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const command = args[0] || 'help';

function printHelp() {
  console.log(`
Atlas — 工业级 Spec-Driven 全流程 Vibecoding 工作流治理引擎

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
    for (let i = 0; i < passthroughArgs.length; i++) {
      if (passthroughArgs[i] === '--target') {
        hasTarget = true;
        break;
      }
    }
    const finalArgs = hasTarget ? passthroughArgs : ['--target', process.cwd(), ...passthroughArgs];
    
    const res = spawnSync('bash', [installScript, ...finalArgs], {
      stdio: 'inherit',
      env: process.env,
    });
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
    console.log(`atlas-workflow v${pkg.version}`);
    break;
  }

  case '-h':
  case '--help':
  case 'help':
  default:
    printHelp();
    break;
}
