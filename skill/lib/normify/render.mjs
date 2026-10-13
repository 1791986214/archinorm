#!/usr/bin/env node
/**
 * 用 dsh-normify 0.5.4 引擎渲染本项目架构图（含契约转换 + 自动进入模块）
 *
 * 背景：archinorm 与 dsh-normify 的 tree.json 契约不同 —— 直接喂 archinorm 的
 * tree.json 会「静默白屏」（render 的 ok=true 但页面空白）。差异有 5 处：
 *   1. api_index  ：dsh 要求在 tree 顶层内嵌；archinorm 放在单独文件 api-index.json
 *   2. edges      ：dsh 要求顶层扁平边列表；archinorm 没有（要从 modules.deps 派生）
 *   3. aggregate  ：dsh 要求每个模块带 {descendant_count, own_api_count,
 *                    inherited_api_count, dep_out, dep_in}；archinorm 没有
 *                    （renderLevel 会读它，缺失即抛错）
 *   4. tree       ：dsh 要求模块带 tree 字段（树名）
 *   5. project/stats：dsh 用 project.{name,stats,trees,compiled_at}，
 *                    stats 字段名为 {tree_count,module_count,leaf_count,max_depth,api_count,dep_count}
 *                    而 archinorm 是 project.slug + 顶层 stats{modules,leaves,...}
 *
 * 另外 dsh-normify **只在 URL 带 `#module=<id>` 时才画图**（默认 hash 为空 → 主区空白），
 * 所以本脚本会在 HTML 末尾注入一行：无 hash 时自动进入第一个模块。
 *
 * 用法：
 *   node work/tools/render_normify.mjs [tree.json 路径] [输出 HTML 路径]
 * 默认：work/archinorm-workbench/tree.json → work/archinorm-workbench/normify.html
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderProject } from './engine/render.js';

const HERE = dirname(fileURLToPath(import.meta.url));      // work/tools
const WORK = resolve(HERE, '..');                           // work/

const treePath = resolve(process.argv[2] || join(WORK, 'archinorm-workbench/tree.json'));
const outPath = resolve(process.argv[3] || join(WORK, 'archinorm-workbench/normify.html'));
const projectName = process.argv[4] || '拿钱工具工作台';

if (!existsSync(treePath)) {
  console.error('✗ 找不到 tree.json：' + treePath);
  process.exit(1);
}

// ---------------------------------------------------------------- 读入 + 契约转换
const tree = JSON.parse(readFileSync(treePath, 'utf8'));
const mods = tree.modules || {};

// 1) api_index：优先用 tree 自带的；否则从同目录 api-index.json 搬进来
if (!tree.api_index) {
  const apiPath = join(dirname(treePath), 'api-index.json');
  if (existsSync(apiPath)) {
    tree.api_index = JSON.parse(readFileSync(apiPath, 'utf8'));
    console.log('· api_index  ← api-index.json（%d 个键）', Object.keys(tree.api_index).length);
  } else {
    tree.api_index = {};
    console.log('· api_index  ← 未找到 api-index.json，用空对象');
  }
}

// 2) edges + aggregate + tree：从 modules 派生
const children = {};
const depIn = {};
for (const [id, m] of Object.entries(mods)) {
  if (m.parent) (children[m.parent] = children[m.parent] || []).push(id);
  for (const d of (m.deps || [])) depIn[d.to] = (depIn[d.to] || 0) + 1;
}
const descCount = id => (children[id] || []).reduce((n, k) => n + 1 + descCount(k), 0);
const apiBelow = id => (children[id] || []).reduce((n, k) => n + (mods[k].apis || []).length + apiBelow(k), 0);

const edges = [];
for (const [id, m] of Object.entries(mods)) {
  m.tree = m.tree || id.split('.')[0];
  m.aggregate = {
    descendant_count: descCount(id),
    own_api_count: (m.apis || []).length,
    inherited_api_count: apiBelow(id),
    dep_out: (m.deps || []).length,
    dep_in: depIn[id] || 0
  };
  for (const d of (m.deps || [])) {
    const e = { from: id, to: d.to, kind: d.kind || 'call', cross_tree: false };
    if (d.label) e.label = d.label;
    if (d.from_api) e.from_api = d.from_api;
    if (d.to_api) e.to_api = d.to_api;
    edges.push(e);
  }
}
tree.edges = edges;

// 3) project / stats 改名
const st = tree.stats || {};
const stats = {
  tree_count: st.trees ?? (Array.isArray(tree.trees) ? tree.trees.length : 1),
  module_count: st.modules ?? Object.keys(mods).length,
  leaf_count: st.leaves ?? Object.values(mods).filter(m => m.is_leaf).length,
  max_depth: st.max_depth ?? 0,
  api_count: st.apis ?? Object.keys(tree.api_index).length,
  dep_count: st.deps ?? edges.length
};
tree.stats = stats;
tree.project = {
  name: projectName,
  stats,
  trees: Array.isArray(tree.trees) ? tree.trees : [Object.keys(mods).find(k => mods[k].parent === null)],
  compiled_at: (tree.project && (tree.project.compiled_at || tree.project.built_at)) || new Date().toISOString()
};

console.log('· edges      ← modules.deps（%d 条，带 API 锚点 %d 条）', edges.length, edges.filter(e => e.from_api).length);
console.log('· aggregate  ← 已补齐 %d 个模块', Object.keys(mods).length);
console.log('· stats      ← %s', JSON.stringify(stats));

// ---------------------------------------------------------------- 渲染
// 注意：renderProject(dir) 读的是 dir/tree.json —— 必须把转换后的数据
// 写进「临时目录」下的 tree.json，直接改文件名会让它读回未转换的原文件（会白屏）。
const stagingDir = join(dirname(treePath), '.normify-staging');
mkdirSync(stagingDir, { recursive: true });
writeFileSync(join(stagingDir, 'tree.json'), JSON.stringify(tree, null, 2), 'utf8');

const r = await renderProject(stagingDir, { out: 'normify.html', lang: 'zh', theme: 'dark' });
if (!r.ok) {
  console.error('✗ 渲染失败：', (r.errors || []).map(e => e.code).join(', '));
  process.exit(1);
}

// 移动 + 注入「自动进模块」（dsh-normify 默认 hash 为空时不画图）
const renderOut = join(stagingDir, 'normify.html');
let html = readFileSync(renderOut, 'utf8');
const firstRoot = Object.keys(mods).find(k => mods[k].parent === null) || Object.keys(mods)[0];
const inject = `<script>(function(){try{if(!location.hash){location.hash="#module=${firstRoot}";}}catch(e){}})();</script>\n`;
if (!html.includes('location.hash="#module=')) html = html.replace('</body>', inject + '</body>');

writeFileSync(outPath, html, 'utf8');
console.log('✓ 输出 %s（%d 字节）', outPath, Buffer.byteLength(html, 'utf8'));
console.log('  默认进入模块：%s', firstRoot);
