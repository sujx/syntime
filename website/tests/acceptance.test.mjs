import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const yaml = require('js-yaml');
const copy = yaml.load(readFileSync(new URL('../source/_data/copy.yml', import.meta.url), 'utf8'));
const css = readFileSync(new URL('../source/css/main.css', import.meta.url), 'utf8');

// 判据读的是构建产物：缺位时给可执行提示（照 honesty.test.mjs 的 existsSync 守卫先例），
// 而不是在模块加载阶段抛裸 ENOENT、把本文件其余判据一起带走。
const pub = (p) => {
  const u = new URL(`../public/${p}`, import.meta.url);
  assert.ok(existsSync(u),
    `public/${p} missing — 先跑 "npx hexo clean && npx hexo generate"，本文件的判据读的是构建产物`);
  return readFileSync(u, 'utf8');
};

/* --- 视觉 --- */
test('S6 visual: seal-red confined to brand rules', () => {
  const users = [...css.matchAll(/([^{}]+)\{[^}]*--seal-red[^}]*\}/g)].map((m) => m[1].trim());
  for (const sel of users) {
    assert.match(sel, /\.seal|:root|favicon|brand/i, `seal-red leaked into ${sel}`);
  }
});

test('S6 visual: aurora params match design doc 1 exactly', () => {
  assert.match(css, /--aurora-light:linear-gradient\(118deg,#6C5FC7 0%,#7E9FE3 30%,#93CFE9 52%,#BEE3D2 68%,#F1E2B6 85%,#F8ECD4 100%\)/);
  assert.match(css, /--aurora-dark:linear-gradient\(168deg,#2A2166 0%,#23337A 30%,#1E4E7E 55%,#17646B 80%,#4A3D20 100%\)/);
});

// :root 的 Token 表：把 var(--x) 解析成规格里的实际值再比对（全局约束 7「Token 单一来源」）。
// 不放宽判据：brief 原式给浅底只钉了第一个色标、深底只钉了第一个色标，这里两版各钉**两个**色标。
const rootBlock = (css.match(/:root\{([\s\S]*?)\n\}/) || [])[1] || '';
const TOKENS = {};
for (const m of rootBlock.matchAll(/(--[\w-]+):([^;]+)/g)) TOKENS[m[1]] = m[2].trim();

const resolveColor = (v) => {
  let out = v, seen = 0;
  while (seen++ < 8) {
    const next = out.replace(/var\((--[\w-]+)\)/g, (whole, name) =>
      Object.prototype.hasOwnProperty.call(TOKENS, name) ? TOKENS[name] : whole);
    if (next === out) break;
    out = next;
  }
  return out.toUpperCase();
};

// 取「选择器 → background 里第一个 linear-gradient 的参数表」，按括号深度切，
// 这样 var(--x) 里的右括号不会被当成渐变的结尾。
const gradientArgs = (selector) => {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = css.match(new RegExp(`${esc}\\{([^}]*)\\}`));
  assert.ok(m, `规则 ${selector} 在 main.css 里找不到——判据拒绝猜位置`);
  const body = m[1];
  const at = body.indexOf('linear-gradient(');
  assert.ok(at >= 0, `${selector} 没有 linear-gradient 背景`);
  let depth = 0, i = at + 'linear-gradient'.length;
  for (; i < body.length; i++) {
    if (body[i] === '(') depth++;
    else if (body[i] === ')') { depth--; if (depth === 0) break; }
  }
  assert.equal(depth, 0, `${selector} 的 linear-gradient 括号没闭合`);
  return body.slice(at + 'linear-gradient('.length, i);
};

// 色标表：第一项必须是 90deg（设计方案 §1 双色版的定义角度），其余按 :root 解析成十六进制大写。
// 本站 .wm 的渐变里没有带逗号的色标函数（如 rgba），故按逗号直接切。
const stops = (selector) => {
  const args = gradientArgs(selector).split(',').map((s) => s.trim());
  assert.equal((args.shift() || '').toLowerCase(), '90deg',
    `${selector} 的渐变角度不是 90deg`);
  return args.map(resolveColor);
};

test('S6 visual: Time wordmark has both light and dark variants', () => {
  assert.ok(Object.keys(TOKENS).length > 20,
    ':root 的 Token 表没解析出来——浅底色标写着 var(--primary-600)，解析失败就退化成比字面量');
  // 设计方案 §1「Time 渐变双色版」：浅底 #3B63D8→#17646B，深底必须换提亮版 #7EA4F5→#3FBFA9。
  assert.deepEqual(stops('.wm .t'), ['#3B63D8', '#17646B']);
  assert.deepEqual(stops('.on-dark .wm .t'), ['#7EA4F5', '#3FBFA9']);
});

/* --- 内容 --- */
const runs = (str) => str.match(/[\u4e00-\u9fff]+/g) || [];
// 允许集 = copy.yml 里作为独立中文词串出现过的文本
const allowed = new Set(runs(JSON.stringify(copy)));

test('S6 content: no Chinese literal in templates outside copy.yml', () => {
  const files = ['layout.ejs', 'index.ejs', 'page.ejs', 'post.ejs',
    'partial/head.ejs', 'partial/nav.ejs', 'partial/footer.ejs',
    'partial/badge.ejs', 'partial/feat-icon.ejs'];
  const offenders = [];
  for (const f of files) {
    const src = readFileSync(new URL(`../themes/syntime/layout/${f}`, import.meta.url), 'utf8')
      .replace(/<%#[\s\S]*?%>/g, '')      // EJS 注释
      .replace(/<!--[\s\S]*?-->/g, '')    // HTML 注释
      .replace(/\/\*[\s\S]*?\*\//g, ''); // 块注释
    for (const r of new Set(runs(src))) if (!allowed.has(r)) offenders.push(`${f}: ${r}`);
  }
  assert.deepEqual(offenders, [], 'hardcoded CJK not backed by copy.yml');
});

/* --- 工程（§6：root 可切换的前提是资源路径全部经 url_for） --- */
test('S6 engineering: templates never hardcode an absolute asset path', () => {
  const files = ['layout.ejs', 'index.ejs', 'page.ejs', 'post.ejs',
    'partial/head.ejs', 'partial/nav.ejs', 'partial/footer.ejs',
    'partial/badge.ejs', 'partial/feat-icon.ejs'];
  const offenders = [];
  for (const f of files) {
    const src = readFileSync(new URL(`../themes/syntime/layout/${f}`, import.meta.url), 'utf8')
      .replace(/<%#[\s\S]*?%>/g, '');
    // 钉的是「HTML 属性里出现以 / 开头的字面量路径」这种形状，不钉具体文件名：
    // root=/ 时 url_for 的输出恰好也是 /css/…，所以只能从模板侧判，产物侧判不出根。
    for (const m of src.matchAll(/(?:href|src|content)\s*=\s*["'](\/[^"'<%]*)["']/g)) offenders.push(`${f}: ${m[0]}`);
  }
  assert.deepEqual(offenders, [], '写死了以 / 开头的绝对路径：root 切到 /SynTime/ 后必 404（约束 8）');
});

test('S6 engineering: asset URLs in the built page carry one single root prefix', () => {
  const s = pub('index.html');
  // 只扫 href/src：og:image 与 canonical 走 config.url，按 F7 的已知限制**不认** root，
  // 那是本轮 CHANGELOG ⑤ 登记的处置口径（断言而非修复），不能混进这条资源门里。
  const prefixes = new Set();
  for (const m of s.matchAll(/(?:href|src)="([^"]*\/(?:css|js|images)\/[^"]*)"/g)) {
    prefixes.add(m[1].slice(0, m[1].indexOf(m[1].match(/(?:css|js|images)\//)[0])));
  }
  assert.ok(prefixes.size > 0, '产物里一个 css/js/images 资源引用都没有——门在空转');
  assert.equal(prefixes.size, 1,
    `资源前缀不止一个：${[...prefixes].join(' | ')} —— 有一处漏了 url_for，root 切换后必 404`);
});
