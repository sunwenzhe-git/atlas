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
  update    安全刷新当前项目中的 .atlas/ 工程线束与平台 Skills 至最新版本
  upgrade   自动拉取 npm 最新全局包升级全局 Atlas CLI
  check     运行项目级资产与门禁全套检查
  console   启动本地 E2E 用例评审控制台 (http://127.0.0.1:4190)
  report    将流水线设计冲突或缺陷自感知上报至云端设计池
  version   查看当前版本
  help      查看帮助信息

示例:
  atlas init                  # 在当前项目初始化装配
  atlas init --target /path   # 在指定项目初始化装配
  atlas update                # 刷新当前项目的工程线束与资产
  atlas update --dry-run      # 预览项目更新改动
  atlas upgrade               # 升级全局 CLI 至最新发布版
  atlas upgrade --tag beta    # 升级全局 CLI 至指定的 tag
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

    process.exit(res.status || 0);
    break;
  }

  case 'update': {
    const installScript = path.join(PKG_ROOT, 'install.sh');
    const passthroughArgs = args.slice(1);

    if (passthroughArgs.includes('-h') || passthroughArgs.includes('--help')) {
      console.log(`
Atlas update — 安全刷新当前项目中的 .atlas/ 工程线束与平台 Skills 至最新版本

用法:
  atlas update [options]

选项:
  --target <dir>    指定目标项目目录（默认为当前工作目录）
  --dry-run         仅预览将要刷新的文件与改动，不实际写入
  --no-skill        跳过 Skills 瘦桩刷新
  --no-patch        跳过 Trellis workflow 补丁刷新
  --no-wiring       跳过项目接线刷新
  -h, --help        查看帮助信息

说明:
  atlas update 会安全刷新当前项目中的 .atlas/ 契约、校验器、模板、脚本以及各平台
  Skills 瘦桩，并重新对账生成 .atlas/VERSION 装配版本戳。
  项目原有的业务资产（product/stack-profile.yaml、product/e2e/cases/ 等）将严格保留。
`);
      process.exit(0);
    }

    let hasTarget = false;
    let targetDir = process.cwd();
    for (let i = 0; i < passthroughArgs.length; i++) {
      if (passthroughArgs[i] === '--target' && passthroughArgs[i + 1]) {
        targetDir = path.resolve(passthroughArgs[i + 1]);
        hasTarget = true;
        break;
      }
    }

    const atlasDir = path.join(targetDir, '.atlas');
    if (!fs.existsSync(atlasDir)) {
      console.error(`\n[Atlas] 错误: 目标项目尚未装配 Atlas（未检测到 ${atlasDir}）。`);
      console.error(`        如需首次初始化装配项目，请运行: atlas init\n`);
      process.exit(1);
    }

    const pkg = require(path.join(PKG_ROOT, 'package.json'));
    const versionFile = path.join(atlasDir, 'VERSION');

    console.log(`\n[Atlas Update] 开始刷新目标项目工程线束与资产...`);
    console.log(`  目标项目 : ${targetDir}`);
    console.log(`  CLI 源包 : ${pkg.name} v${pkg.version}`);
    if (fs.existsSync(versionFile)) {
      try {
        const curVer = fs.readFileSync(versionFile, 'utf8').trim();
        console.log(`  现有装配 : ${curVer}`);
      } catch (_) {}
    }
    console.log('');

    const finalArgs = hasTarget ? passthroughArgs : ['--target', targetDir, ...passthroughArgs];

    const res = spawnSync('bash', [installScript, '--update', ...finalArgs], {
      stdio: 'inherit',
      env: {
        ...process.env,
        ATLAS_ALLOW_OVERWRITE: '1',
      },
    });

    if (res.status === 0) {
      console.log(`\n[Atlas Update] ✅ 项目工程线束与资产已成功刷新至 v${pkg.version}！\n`);
    } else {
      console.error(`\n[Atlas Update] ❌ 项目更新未完成 (退出码: ${res.status})。\n`);
    }

    process.exit(res.status || 0);
    break;
  }

  case 'upgrade': {
    const passthroughArgs = args.slice(1);
    let tag = 'latest';
    let isDryRun = false;

    for (let i = 0; i < passthroughArgs.length; i++) {
      if (passthroughArgs[i] === '-h' || passthroughArgs[i] === '--help') {
        console.log(`
Atlas upgrade — 自动拉取 npm 最新全局包升级全局 Atlas CLI

用法:
  atlas upgrade [options]

选项:
  --tag <tag>   指定发布的 npm dist-tag（默认: latest，可选: beta 等）
  --dry-run     仅预览升级安装命令，不实际执行
  -h, --help    查看帮助信息

说明:
  atlas upgrade 会调用 npm install -g 升级全局包 atlas-project-harness。
  升级成功后，可进入项目目录运行 atlas update 刷新项目内的工程线束与模板。
`);
        process.exit(0);
      }
      if (passthroughArgs[i] === '--tag' && passthroughArgs[i + 1]) {
        tag = passthroughArgs[i + 1];
        i++;
      } else if (passthroughArgs[i] === '--dry-run') {
        isDryRun = true;
      }
    }

    const pkg = require(path.join(PKG_ROOT, 'package.json'));
    const targetPkg = `${pkg.name}@${tag}`;

    console.log(`\n[Atlas Upgrade] 准备升级全局 CLI (${pkg.name})...`);
    console.log(`  当前版本 : v${pkg.version}`);
    console.log(`  目标包   : ${targetPkg}`);

    const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
    const installArgs = ['install', '-g', targetPkg];

    if (isDryRun) {
      console.log(`  [dry-run] 将执行命令: ${npmCmd} ${installArgs.join(' ')}\n`);
      process.exit(0);
    }

    console.log(`  正在执行: ${npmCmd} ${installArgs.join(' ')} ...\n`);
    const res = spawnSync(npmCmd, installArgs, {
      stdio: 'inherit',
      env: process.env,
    });

    if (res.status === 0) {
      console.log(`\n[Atlas Upgrade] ✅ 全局 Atlas CLI 已成功升级！`);
      console.log(`提示: 如需将现有项目中的 .atlas/ 工程线束刷新至最新版，请进入项目目录执行:`);
      console.log(`      atlas update\n`);
    } else {
      console.error(`\n[Atlas Upgrade] ❌ 升级失败 (退出码: ${res.status})。`);
      console.error(`常见原因与排查建议:`);
      console.error(`  1. 权限不足: 全局安装可能需要管理员权限，可尝试: sudo npm install -g ${targetPkg}`);
      console.error(`  2. 网络或代理问题: 请检查 npm 源或网络代理设置（如 http_proxy）\n`);
    }

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
    console.log(`${pkg.name} v${pkg.version}`);
    break;
  }

  case '-h':
  case '--help':
  case 'help':
    printHelp();
    break;

  case 'apply': {
    const sub = args.slice(1).join(' ') || 'adopt';
    console.error(`
[Atlas] 提示: 'apply' 是由 AI Coding Agent（如 Claude Code / Cursor / OpenCode）在会话中执行的认知编排技能，非终端独立脚本。

使用方式:
  1. 在 Agent 会话中直接输入大白话，例如:
     - "帮我把这个项目接入 Atlas 工作流" (对应 adopt 存量开户)
     - "跑一下三环全量构建，建立应然基线" (对应 all 全量构建)
  2. 或在支持 Slash Command 的平台中唤起技能:
     /atlas-apply ${sub}
`);
    process.exit(2);
    break;
  }

  default:
    if (command) {
      console.error(`\n[Atlas] 错误: 未知命令 '${command}'。\n`);
      printHelp();
      process.exit(2);
    }
    printHelp();
    break;
}
