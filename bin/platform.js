#!/usr/bin/env node
/**
 * CLI 的平台探测助手（bin/atlas.js 专用）。
 *
 * 背景：Atlas 装配器是 install.sh（bash + python3 + grep/sed/cp）。Windows 原生
 * PowerShell/CMD 不提供这套环境，而 `C:\Windows\System32\bash.exe` 只是 WSL 的中继
 * 壳——未安装发行版时它只会抛 `execvpe(/bin/bash) failed`。所以这里不拿系统 bash
 * 兜底，只认 Git Bash 的绝对路径（Git Bash 自带 grep/sed/cp，能满足 install.sh）。
 *
 * 所有函数都接受显式的 platform/env，便于在非 Windows 宿主上做单测。
 */
'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const IS_WIN = process.platform === 'win32';
// 在 Git Bash 里调用 atlas 时 MSYS 已把自身 usr/bin 摆在 PATH 最前，直接 `bash` 即可。
const IS_GIT_BASH = IS_WIN && !!process.env.MSYSTEM;

function joinFor(platform) {
  return platform === 'win32' ? path.win32.join : path.join;
}

/** Trellis CLI 的探测命令：POSIX 用 which，Windows 用 where（which 在原生 Windows 不存在）。 */
function trellisProbe(platform = process.platform) {
  return platform === 'win32'
    ? { cmd: 'where', args: ['trellis'] }
    : { cmd: 'which', args: ['trellis'] };
}

/** Git for Windows 的常见安装位置（不含 System32 的 WSL 中继壳）。 */
function bashCandidates(platform = process.platform, env = process.env) {
  if (platform !== 'win32') return ['bash'];
  const join = joinFor(platform);
  const roots = [
    env.ProgramFiles,
    env['ProgramFiles(x86)'],
    env.LOCALAPPDATA ? join(env.LOCALAPPDATA, 'Programs') : null,
  ].filter(Boolean);
  return roots.flatMap((root) => [
    join(root, 'Git', 'bin', 'bash.exe'),
    join(root, 'Git', 'usr', 'bin', 'bash.exe'),
  ]);
}

function resolveBash(platform = process.platform) {
  if (platform !== 'win32') return 'bash';
  if (IS_GIT_BASH) return 'bash';
  return bashCandidates(platform).find((p) => fs.existsSync(p)) || null;
}

// ---------------------------------------------------------------- Python 探测
// Atlas 校验器要求 Python 3.10+。Windows 原生没有 python3（python.org 只装
// python.exe / py.exe；`python3.exe` 多为 WindowsApps 商店 stub），所以：
//   * win32  : py -3 → where python（排除 WindowsApps）→ 实跑 --version 验版式
//   * POSIX  : python3 → python
// 只认能跑出 `Python 3.10+` 的解释器；版本不符或 stub 一律跳过。

const PYTHON_MIN = 10;

function pythonCandidates(platform = process.platform) {
  if (platform === 'win32') {
    return [
      { cmd: 'py', args: ['-3'] },
      { cmd: 'python', args: [] },
    ];
  }
  return [
    { cmd: 'python3', args: [] },
    { cmd: 'python', args: [] },
  ];
}

function parsePythonVersion(output) {
  const m = /Python\s+(\d+)\.(\d+)\.(\d+)/i.exec(output || '');
  if (!m) return null;
  return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]) };
}

function versionSupported(version) {
  return !!version && version.major === 3 && version.minor >= PYTHON_MIN;
}

/** Windows: `where python` 的真实路径，剔除 WindowsApps 商店 stub。 */
function windowsPythonPaths(env = process.env) {
  const res = spawnSync('where', ['python'], { encoding: 'utf8', env, timeout: 5000 });
  if (res.status !== 0) return [];
  return (res.stdout || '')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((p) => p && !/\\windowsapps\\/i.test(p));
}

/** 实跑 `--version`，返回可用的解释器描述；没有 3.10+ 返回 null。 */
function resolvePython(platform = process.platform, env = process.env) {
  const candidates = [];
  for (const cand of pythonCandidates(platform)) {
    if (platform === 'win32' && cand.cmd === 'python') {
      // 裸 `python` 可能是 WindowsApps stub（会弹商店）；只认真实路径。
      for (const p of windowsPythonPaths(env)) candidates.push({ cmd: p, args: [] });
    } else {
      candidates.push(cand);
    }
  }
  for (const cand of candidates) {
    const res = spawnSync(cand.cmd, [...cand.args, '--version'], {
      encoding: 'utf8',
      env,
      timeout: 5000,
    });
    if (res.error || res.status !== 0) continue;
    const version = parsePythonVersion(`${res.stdout || ''}${res.stderr || ''}`);
    if (versionSupported(version)) {
      return { cmd: cand.cmd, args: cand.args, version };
    }
  }
  return null;
}

/**
 * 传给 bash 的参数：Windows 路径的反斜杠会被 bash 当转义符吃掉，
 * 只把「路径型参数」的值换成正斜杠（其余参数原样保留）。
 */
function normalizeBashArgs(argv, platform = process.platform) {
  if (platform !== 'win32') return argv;
  const PATH_FLAGS = new Set(['--target', '--assets-root', '--adr-dir']);
  const out = [...argv];
  for (let i = 0; i < out.length - 1; i++) {
    if (PATH_FLAGS.has(out[i])) out[i + 1] = out[i + 1].replace(/\\/g, '/');
  }
  return out;
}

/**
 * 返回可用于启动的 trellis 入口；未安装返回 null。
 * Windows 下 where 会同时列出无扩展名的 sh 入口与 .cmd/.exe；Node 不能直接拉起
 * .cmd，所以优先 .exe，其次 .cmd/.bat。
 */
function detectTrellis(platform = process.platform) {
  const { cmd, args } = trellisProbe(platform);
  const res = spawnSync(cmd, args, { encoding: 'utf8' });
  if (res.status !== 0) return null;
  if (platform !== 'win32') return 'trellis';
  const hits = (res.stdout || '')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  return hits.find((p) => /\.exe$/i.test(p))
    || hits.find((p) => /\.(cmd|bat)$/i.test(p))
    || hits[0]
    || null;
}

module.exports = {
  IS_WIN,
  IS_GIT_BASH,
  trellisProbe,
  bashCandidates,
  resolveBash,
  normalizeBashArgs,
  detectTrellis,
  pythonCandidates,
  parsePythonVersion,
  versionSupported,
  resolvePython,
};
