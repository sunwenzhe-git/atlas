#!/usr/bin/env node
/**
 * 平台无关的 Python 启动器（装配进 `.atlas/scripts/run_python.js`，供 `.trellis/config.yaml`
 * 的 after_archive 钩子调用）。
 *
 * 为什么需要它：Trellis 以 `subprocess.Popen(cmd, shell=True)` 执行钩子——POSIX 走 /bin/sh，
 * Windows 走 cmd.exe；而 `python3` 在原生 Windows 只可能命中 WindowsApps 商店 stub。
 * 钩子命令又是 **git 跟踪的** `.trellis/config.yaml`，写死某个平台的名字必然在另一端坏掉。
 * Node 是 Atlas 的硬依赖（CLI 就是 Node），所以用 Node 做启动器，运行时解析 Python 3.10+。
 *
 * 用法：
 *   node .atlas/scripts/run_python.js <脚本路径（相对项目根）> [args...]
 *
 * 退出码：脚本自身的退出码；找不到 Python 3.10+ ⇒ 1；缺参数 ⇒ 2。
 * 失败信息写 stderr（Trellis 钩子 fail-open，会把它带进 WARN）。
 */
'use strict';

const { spawnSync } = require('child_process');

const MIN_MINOR = 10;
const WIN = process.platform === 'win32';

function parseVersion(output) {
  const m = /Python\s+(\d+)\.(\d+)\.(\d+)/i.exec(output || '');
  if (!m) return null;
  return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]) };
}

function windowsPythonPaths(env) {
  const res = spawnSync('where', ['python'], { encoding: 'utf8', env, timeout: 5000 });
  if (res.status !== 0) return [];
  return (res.stdout || '')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((p) => p && !/\\windowsapps\\/i.test(p));
}

function candidates(env) {
  if (!WIN) {
    return [
      { cmd: 'python3', args: [] },
      { cmd: 'python', args: [] },
    ];
  }
  const out = [{ cmd: 'py', args: ['-3'] }];
  for (const p of windowsPythonPaths(env)) out.push({ cmd: p, args: [] });
  return out;
}

function resolvePython(env) {
  for (const cand of candidates(env)) {
    const res = spawnSync(cand.cmd, [...cand.args, '--version'], {
      encoding: 'utf8',
      env,
      timeout: 5000,
    });
    if (res.error || res.status !== 0) continue;
    const version = parseVersion(`${res.stdout || ''}${res.stderr || ''}`);
    if (version && version.major === 3 && version.minor >= MIN_MINOR) {
      return { cmd: cand.cmd, args: cand.args, version };
    }
  }
  return null;
}

function main() {
  const argv = process.argv.slice(2);
  const script = argv[0];
  if (!script) {
    console.error('用法: node .atlas/scripts/run_python.js <脚本路径（相对项目根）> [args...]');
    return 2;
  }
  const env = { ...process.env, PYTHONUTF8: '1' };
  const py = resolvePython(env);
  if (!py) {
    console.error('[run_python] 未找到可用的 Python 3.10+（POSIX: python3/python；Windows: py -3 或真实 python.exe）。');
    console.error('[run_python] 结构事实刷新被跳过；安装 Python 3.10+ 后重跑 `atlas update` 即恢复。');
    return 1;
  }
  const res = spawnSync(py.cmd, [...py.args, script, ...argv.slice(1)], {
    stdio: 'inherit',
    env,
  });
  if (res.error) {
    console.error(`[run_python] 启动失败: ${res.error.message}`);
    return 1;
  }
  return typeof res.status === 'number' ? res.status : 1;
}

process.exit(main());
