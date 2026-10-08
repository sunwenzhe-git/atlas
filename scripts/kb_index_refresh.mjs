#!/usr/bin/env bun
// KB 索引刷新(独立进程):调 open-zk-kb 包内 handleMaintain(action: "rebuild") 从盘上
// 文件重建索引,再无别的通道时用它。
//
// 为什么不经 MCP:`knowledge-maintain` 的 rebuild/embed/full 在同一个同步请求里做全量
// 重索引 + embedding 补嵌;本机 embedding 走默认本地模型(Xenova/all-MiniLM-L6-v2),
// 模型缓存(~/.cache/open-zk-kb/models)为空 ⇒ 每次都尝试从 HuggingFace CDN 下载,
// 网络不可达时要么秒拒要么长挂(2026-09-29 日志实证),MCP 客户端先报超时、服务端后跑完
// (3508 §134 ×2 + 本批 ×3 复现)。工具无异步等待句柄 ⇒ MCP 通道拿不到可用姿势;
// 独立进程 embeddingConfig 传 null ⇒ 完全离线,秒级完成。属 §B120「门无调度者」同族。
//
// 注意:① 跨进程写 SQLite(WAL),建议在 MCP 空闲时跑;② 重建后,长跑中的 MCP 服务
// 进程的内存基线仍是旧的(screening 侧可能告警),重启 MCP 服务后自愈;③ embed(语义
// 嵌入)不在本脚本做——要补嵌入需先解决模型获取(网络可达时缓存,或配 API provider,
// 或 config.yaml 写 `embeddings: {enabled: false}` 显式关掉,免得每次白试下载)。
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
    const args = { vault: path.join(os.homedir(), '.local', 'share', 'open-zk-kb') };
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === '--vault' && i + 1 < argv.length)
            args.vault = argv[++i];
        else {
            console.error(`未知参数: ${argv[i]}(用法: bun kb_index_refresh.mjs [--vault <path>])`);
            process.exit(2);
        }
    }
    return args;
}

async function main() {
    const args = parseArgs(process.argv.slice(2));
    const vault = path.resolve(args.vault);
    if (!fs.existsSync(vault)) {
        console.error(`SKIP: vault 不存在(${vault})`);
        process.exit(3);
    }
    const pkgRoot = [process.env.OPEN_ZK_KB_PKG, path.join(os.homedir(), '.pi', 'agent', 'npm', 'node_modules', 'open-zk-kb')]
        .filter(Boolean)
        .find((dir) => fs.existsSync(path.join(dir, 'package.json')));
    if (!pkgRoot) {
        console.error('SKIP: 找不到 open-zk-kb 包(设 OPEN_ZK_KB_PKG 指向包根)');
        process.exit(3);
    }
    const load = (rel) => import(pathToFileURL(path.join(pkgRoot, rel)).href);
    const { createNoteRepository } = await load('dist/storage/NoteRepository.js');
    const { getConfig } = await load('dist/config.js');
    const { handleMaintain } = await load('dist/tool-handlers.js');
    const { createGitVersioning } = await load('dist/git-versioning.js');

    const repo = createNoteRepository(vault);
    const config = getConfig();
    let gitVersioning;
    try {
        gitVersioning = config?.versioning?.enabled ? createGitVersioning(vault, config.versioning) : undefined;
    }
    catch {
        gitVersioning = undefined; // 非 git 目录(测试夹具):跳过版本快照,不影响索引重建
    }
    // embeddingConfig 传 null = 跳过 embedding 补嵌(离线、秒级);与服务端默认 local 模型的区别见文件头
    const output = await handleMaintain({ action: 'rebuild' }, repo, config, null, 'kb-index-refresh', gitVersioning);
    console.log(output);
    if (output.startsWith('Error:') || output.startsWith('Failed:') || output.startsWith('Unknown action:'))
        process.exit(1);
    const match = output.match(/Indexed (\d+) notes, (\d+) errors/);
    if (match && Number(match[2]) > 0)
        process.exit(1);
    console.log('下一步:bun kb_projection_check.mjs 验证投影一致');
}

main().catch((err) => {
    console.error(`环境错误: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(2);
});
