#!/usr/bin/env bun
// KB 投影对账门:open-zk-kb 索引快照(.index/knowledge.db)⇔ vault 本体,逐篇逐字段比对。
//
// 为什么需要:open-zk-kb 包内无文件监听(实测 dist 无 fs.watch/chokidar),索引只在 MCP
// 工具调用时更新 ⇒ 盘上手改 vault 文件(双通道修订的常规路径)永远不会被重索引,投影
// 会静默漂移——2026-09-29 实测 `3501` 的索引快照滞留 12 天前旧文(3508 §134,§B103 同族)。
//
// 怎么对账:用包自己的解析器(沙箱实例,零语义复刻)对每个 vault md 文件做与
// rebuildFromFilesUnlocked 相同的字段推导,与 DB 行逐列比对;外加集合对账
//(盘上有索引无 = UNINDEXED / 索引有盘上无 = ORPHAN)。只读:真实 DB 以 readonly 打开,
// 沙箱实例落在临时目录,本脚本不写任何状态。
//
// 退出码:0 = 投影一致;1 = 有漂移(逐篇列出,可定位到具体 note);2 = 用法/环境错误;
// 3 = SKIP(未就绪:bun / open-zk-kb 包 / 索引 DB 缺失——SKIP 不是通过)。
//
// 修漂移:跑 `bun kb_index_refresh.mjs`(独立进程重建索引,不经 MCP,无请求层超时),
// 再跑本脚本验证转绿。
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
    const args = { vault: path.join(os.homedir(), '.local', 'share', 'open-zk-kb'), json: false };
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === '--vault' && i + 1 < argv.length)
            args.vault = argv[++i];
        else if (argv[i] === '--json')
            args.json = true;
        else {
            console.error(`未知参数: ${argv[i]}(用法: bun kb_projection_check.mjs [--vault <path>] [--json])`);
            process.exit(2);
        }
    }
    return args;
}

function findPackageRoot() {
    const candidates = [
        process.env.OPEN_ZK_KB_PKG,
        path.join(os.homedir(), '.pi', 'agent', 'npm', 'node_modules', 'open-zk-kb'),
    ].filter(Boolean);
    for (const dir of candidates) {
        if (fs.existsSync(path.join(dir, 'package.json')))
            return dir;
    }
    return undefined;
}

async function main() {
    const args = parseArgs(process.argv.slice(2));
    const pkgRoot = findPackageRoot();
    if (!pkgRoot) {
        console.error('SKIP: 找不到 open-zk-kb 包(设 OPEN_ZK_KB_PKG 指向包根,或确认 ~/.pi/agent/npm/node_modules/open-zk-kb 存在)');
        process.exit(3);
    }
    const vault = path.resolve(args.vault);
    const dbPath = path.join(vault, '.index', 'knowledge.db');
    if (!fs.existsSync(dbPath)) {
        console.error(`SKIP: 索引 DB 不存在(${dbPath})——open-zk-kb 从未在此 vault 上跑过`);
        process.exit(3);
    }

    const load = (rel) => import(pathToFileURL(path.join(pkgRoot, rel)).href);
    const { createNoteRepository, NoteRepository } = await load('dist/storage/NoteRepository.js');
    const { walkMarkdownFiles, isGeneratedStructuralMarkdown } = await load('dist/storage/path-resolver.js');
    const { VALID_LIFECYCLES } = await load('dist/types.js');
    const { Database } = await import('bun:sqlite');

    // 沙箱解析器:与索引器同一套解析语义,落在临时目录,不触碰真实 DB
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'kb-projection-check-'));
    const sandbox = createNoteRepository(tmp);

    const db = new Database(dbPath, { readonly: true });
    const rows = db
        .prepare('SELECT id, path, title, kind, status, lifecycle, type, tags, summary, guidance, context, content, created_at, updated_at FROM notes')
        .all();
    db.close();

    const vaultReal = fs.realpathSync(vault);
    const files = walkMarkdownFiles(vaultReal);
    const allFiles = new Set(files);
    const byPath = new Map();
    for (const row of rows)
        byPath.set(path.resolve(row.path), row);

    // 与 rebuildFromFilesUnlocked 相同的字段推导(语义对齐的锚点)
    function deriveNote(filePath, raw) {
        const { frontmatter, body } = sandbox.parseFrontmatter(raw);
        const id = frontmatter.id || path.basename(filePath).match(/^(\d{16}|\d{12})/)?.[1] || '';
        if (!id)
            return { id: '' , frontmatter };
        const title = frontmatter.title || sandbox.extractTitle(body);
        const kind = frontmatter.kind || 'observation';
        const status = frontmatter.status || 'fleeting';
        const rawLifecycle = frontmatter.lifecycle || 'living';
        const lifecycle = VALID_LIFECYCLES.has(rawLifecycle) ? rawLifecycle : 'living';
        const noteType = frontmatter.type || 'atomic';
        const tags = Array.isArray(frontmatter.tags) ? frontmatter.tags : [];
        const isStructural = kind === 'index' || kind === 'log';
        const bodyAfterTitle = isStructural ? body : body.replace(NoteRepository.TITLE_PATTERN, '');
        const bodySections = sandbox.parseBodySections(bodyAfterTitle);
        const dateToMs = (value) => (value ? new Date(value).getTime() : undefined);
        return {
            id,
            frontmatter,
            derived: {
                id,
                title,
                kind,
                status,
                lifecycle,
                type: noteType,
                tags: JSON.stringify(tags),
                summary: bodySections.summary || frontmatter.tagline || frontmatter.summary || '',
                guidance: bodySections.guidance || frontmatter.guidance || '',
                context: bodySections.context || frontmatter.context || '',
                content: bodySections.content || bodyAfterTitle,
                created_at: dateToMs(frontmatter.created),
                updated_at: dateToMs(frontmatter.updated),
            },
        };
    }

    const issues = [];
    for (const filePath of files) {
        const rel = path.relative(vaultReal, filePath);
        const raw = fs.readFileSync(filePath, 'utf-8');
        const { id, frontmatter, derived } = deriveNote(filePath, raw);
        if (!id) {
            if (isGeneratedStructuralMarkdown(vaultReal, filePath, frontmatter))
                continue; // 生成的结构文件(Home/log/review 等)不入索引,与 rebuild 同规
            issues.push({ path: rel, status: 'UNPARSEABLE', detail: '无 frontmatter id 且非生成结构文件' });
            continue;
        }
        const row = byPath.get(path.resolve(filePath));
        if (!row) {
            issues.push({ path: rel, status: 'UNINDEXED', detail: 'vault 有文件,索引无行(手改新增未被索引)' });
            continue;
        }
        const diffs = [];
        for (const [field, value] of Object.entries(derived)) {
            if (value === undefined || (typeof value === 'number' && Number.isNaN(value)))
                continue; // frontmatter 缺日期列时 rebuild 落 Date.now(),不可复现 ⇒ 跳过该列
            // updated_at/created_at 是双语义混合:rebuild 写 frontmatter 日期(UTC 零点),
            // store/appendLog 写 wall-clock(2026-09-29 实测:polyvoice/log.md 行值 = 文件 mtime)
            // ⇒ 只按 UTC 日粒度对账,毫秒级差异不是漂移
            if ((field === 'created_at' || field === 'updated_at') && typeof value === 'number') {
                const rowValue = Number(row[field]);
                if (Math.floor(rowValue / 86400000) === Math.floor(value / 86400000))
                    continue;
                diffs.push(field);
                continue;
            }
            if (String(row[field] ?? '') !== String(value))
                diffs.push(field);
        }
        if (diffs.length > 0)
            issues.push({ path: rel, status: 'DRIFTED', detail: `字段不一致: ${diffs.join(', ')}` });
    }
    for (const row of rows) {
        const resolved = path.resolve(row.path);
        if (!allFiles.has(resolved))
            issues.push({ path: path.relative(vaultReal, resolved), status: 'ORPHAN', detail: '索引有行,vault 无文件' });
    }
    fs.rmSync(tmp, { recursive: true, force: true });

    issues.sort((a, b) => a.path.localeCompare(b.path));
    const summary = `RESULT: files=${files.length} rows=${rows.length} issues=${issues.length}`;
    if (args.json) {
        console.log(JSON.stringify({ summary, files: files.length, rows: rows.length, issues }, null, 2));
    }
    else {
        for (const issue of issues)
            console.log(`${issue.status.padEnd(11)} ${issue.path}  (${issue.detail})`);
        console.log(summary);
        if (issues.length > 0)
            console.log('漂移修法:bun kb_index_refresh.mjs(独立进程重建索引)后复跑本脚本验证转绿');
    }
    process.exit(issues.length > 0 ? 1 : 0);
}

main().catch((err) => {
    console.error(`环境错误: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(2);
});
