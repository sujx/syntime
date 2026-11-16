import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const yaml = require('js-yaml');
const copy = yaml.load(readFileSync(new URL('../source/_data/copy.yml', import.meta.url), 'utf8'));
const strip = (h) => h.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<[^>]+>/g, ' ');
// copy 文本要进 new RegExp：先转义正则元字符，否则文案里出现 ( ) [ ] . + 时会被当成语法而非字面量
const esc = (x) => String(x).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// 判据加强③：honesty 读的是构建产物。缺位时给一条可执行提示（对齐 build.test.mjs 的 existsSync 守卫），
// 而不是在模块加载阶段抛裸 ENOENT、把本文件其余判据一起带走。故产物在**用例内**读，不在顶层读。
const pub = (p) => new URL(`../public/${p}`, import.meta.url);
const html = (p) => {
  assert.ok(existsSync(pub(p)),
    `public/${p} missing — 先跑 "npx hexo clean && npx hexo generate"，本文件的判据读的是构建产物`);
  return readFileSync(pub(p), 'utf8');
};
const readCss = () => readFileSync(new URL('../source/css/main.css', import.meta.url), 'utf8');

test('S6-5 ALPHA banner is in the first screen, above the nav content', () => {
  const s = html('index.html');
  assert.match(s, /class="alpha"/);
  assert.ok(s.indexOf('class="alpha"') < s.indexOf('class="nav"'), 'banner must sit above nav');
  // 判据加强①：横幅的文字与徽章只在 `.alpha` → `<header class="nav"` 这一段里搜。
  // 整页搜的话，T5–T9 一旦出现任何 dev 卡（`pill info` + 「开发中」），删掉横幅徽章也能转绿——顶包。
  const from = s.indexOf('class="alpha"');
  const to = s.indexOf('<header class="nav"');
  assert.ok(to > from, '切片标记缺失：产物里 .alpha 必须在 <header class="nav"> 之前');
  const banner = s.slice(from, to);
  assert.ok(strip(banner).includes(copy.alpha_banner.text), '横幅文字必须落在 .alpha 之内');
  const st = copy.labels.badge_pill_state[copy.alpha_banner.badge];
  const txt = copy.labels.badges[copy.alpha_banner.badge];
  // Fix round 1 裁定：class 与徽章文字之间用 [\s\S]*?。实测 `[^>]*` 是否定字符类、本来就含 \n，
  // 所以旧写法并未因换行静默失效（两种写法在当前产物上都为真）；此处取更宽容的形态以防别的回流，
  // 徽章文字错位/丢失仍然判红（见报告的反证 mutant）。
  assert.match(banner, new RegExp(`class="pill ${esc(st)}"[\\s\\S]*?>${esc(txt)}<`),
    `.alpha 里没有 ${txt} 徽章（应为 pill ${st}）；页面别处的同名 pill 不算数`);
});

test('S6-5 banner contains no seal-red', () => {
  const css = readCss();
  assert.doesNotMatch(css.match(/\.alpha[^}]*\{[^}]*\}/g).join(''), /--seal-red|#C0392B/);
});

test('nav links mirror copy.nav.anchors and drop the prototype #screens', () => {
  const s = html('index.html');
  const block = (s.match(/<nav class="nav-links"[\s\S]*?<\/nav>/) || [''])[0];
  assert.ok(block, 'nav-links block missing');
  assert.equal([...block.matchAll(/<a /g)].length, copy.nav.anchors.length);
  for (const a of copy.nav.anchors) assert.ok(block.includes(`href="${a.href}"`), `missing ${a.href}`);
  assert.doesNotMatch(block, /#screens/);
});

test('copy.nav carries no dead brand key', () => {
  // 品牌区的出口是 .seal 字形 + .wm 的 Syn/Time + .wm-sub 副标（partial/nav.ejs），
  // 全站零消费方（themes/ tests/ source/ grep 皆空），留着 `brand` 就是一个没人读的中文死键。
  // 本条钉住「已删除」这个决定：键回流即红，避免再长出第二个品牌文案来源。
  assert.ok(!('brand' in copy.nav),
    'copy.nav.brand 是零引用死键（T4 fix round 2 已删）；要挂品牌文案请走 .wm/.wm-sub 的数据化，别复活这个键');
  const s = html('index.html');
  const brand = (s.match(/<div class="brand">[\s\S]*?<\/nav>/) || [''])[0];
  assert.ok(brand, 'nav 的品牌区 .brand 缺失');
  for (const sel of ['class="seal"', 'class="wm"', 'class="wm-sub"']) {
    assert.ok(brand.includes(sel), `品牌区必须由 ${sel} 出，现在找不到`);
  }
});

test('§6-5 first-screen clearance: banner pads past the fixed nav, nav top stays transcribed', () => {
  const css = readCss();
  // 判据加强②：不再断言字面量 `padding:calc(var(--space-3) + 70px)`——语义完全相同的
  // `padding-top:calc(70px + var(--space-3))` 会假红；而 70 这个常数本来就是从
  // .nav{top} + .nav-inner{height} + .nav 上下两条 border 推出来的。改成读这四要素现算 pill 底边，
  // 再断言横幅的 padding-top >= 它：几何一变判据自己跟着变，抄来的常数骗不了它。
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, '');   // R16 的理由注释里也写着 `.nav{top:12px}`，先剥注释
  const decl = (rule, prop) => (rule.match(new RegExp(`(?:^|[;\\s])${prop}:([^;]+)`)) || [])[1];
  const navRule = (bare.match(/\.nav\{([^}]*)\}/) || [])[1];
  const innerRule = (bare.match(/\.nav-inner\{([^}]*)\}/) || [])[1];
  const alphaRule = (bare.match(/\.alpha\{([^}]*)\}/) || [])[1];
  assert.ok(navRule && innerRule && alphaRule, '.nav / .nav-inner / .alpha 有规则解析不出来，判据无从计算');
  const asPx = (v, what) => {
    const m = String(v).trim().match(/^([\d.]+)px$/);
    assert.ok(m, `${what}「${String(v).trim()}」不是 px 字面量——判据拒绝猜单位`);
    return Number(m[1]);
  };
  const varPx = (name) => {
    const m = bare.match(new RegExp(`${name}:\\s*([\\d.]+)px`));
    assert.ok(m, `Token ${name} 在 :root 里量不出 px 值`);
    return Number(m[1]);
  };
  // padding 简写的第一项 = top；必须按括号深度切，`calc(a + b)` 里的空格不能当分隔符
  const firstToken = (v) => {
    let depth = 0, cur = '';
    for (const ch of v.replace(/\s+/g, ' ').trim()) {
      if (ch === '(') depth++;
      else if (ch === ')') depth--;
      if (ch === ' ' && depth === 0) { if (cur) return cur; cur = ''; continue; }
      cur += ch;
    }
    return cur;
  };
  const pxValue = (spec, what) => {
    let v = spec.replace(/var\((--[\w-]+)\)/g, (_, n) => `${varPx(n)}px`).trim();
    let m = v.match(/^calc\(([\s\S]*)\)$/);
    while (m) { v = m[1].trim(); m = v.match(/^calc\(([\s\S]*)\)$/); }
    let total = 0;
    for (const term of v.split(/(?=[+-])/)) {
      const t = term.trim();
      if (!t) continue;
      const n = t.match(/^([+-]?)\s*([\d.]+)px?$/);
      assert.ok(n, `${what}「${spec}」里「${t}」算不出 px——判据只认 px / var() / calc 的加减`);
      total += (n[1] === '-' ? -1 : 1) * Number(n[2]);
    }
    return total;
  };
  const sideBorder = (side) => {
    const one = decl(navRule, `border-${side}`);
    const all = decl(navRule, 'border');
    const w = one !== undefined ? firstToken(one) : (all === undefined ? undefined : firstToken(all));
    return w === undefined ? 0 : asPx(w, `.nav 的 ${side} 边框`);
  };
  const navTop = asPx(decl(navRule, 'top'), '.nav{top}');
  const innerH = asPx(decl(innerRule, 'height'), '.nav-inner{height}');
  const pillBottom = navTop + innerH + sideBorder('top') + sideBorder('bottom');
  const ptDecl = decl(alphaRule, 'padding-top');
  const padDecl = decl(alphaRule, 'padding');
  assert.ok(ptDecl !== undefined || padDecl !== undefined, '.alpha 既无 padding-top 也无 padding，首屏没有留白');
  const padTop = pxValue(ptDecl !== undefined ? ptDecl : firstToken(padDecl), '.alpha 顶部留白');
  assert.ok(padTop >= pillBottom,
    `横幅文字顶边落在 padding-top ${padTop}px，固定导航 pill 底边在 ${pillBottom}px`
    + `（.nav{top} ${navTop} + .nav-inner{height} ${innerH} + 上下边框 ${sideBorder('top')}/${sideBorder('bottom')}）`
    + ' → 横幅会被 pill 盖住，违反 §6 诚实性 ⑤「首屏可见」');
  assert.doesNotMatch(css, /^\.nav\{[^}]*top:calc/m, '.nav{top} must stay 12px as transcribed');
});

test('global chrome is assembled in layout, not per page', () => {
  const lay = readFileSync(new URL('../themes/syntime/layout/layout.ejs', import.meta.url), 'utf8');
  const idx = readFileSync(new URL('../themes/syntime/layout/index.ejs', import.meta.url), 'utf8');
  assert.match(lay, /partial\('partial\/nav'\)/);
  assert.match(lay, /partial\('partial\/footer'\)/);
  assert.ok(lay.indexOf("partial('partial/nav')") < lay.indexOf('<%- body %>'), 'nav must precede body');
  assert.doesNotMatch(idx, /partial\('partial\/nav'\)/, 'index must not re-render the nav');
});

// 固有尺寸**现量**（判据加强④）：优先 ImageMagick identify，退到 PIL（后端 venv 优先，再退系统 python3）。
// 两条路都走不通就当场失败并说明是哪条断了——绝不允许回退成注释里那个"记得是 2880"的数字。
function intrinsicSize(file) {
  const p = file.pathname;
  const tried = [];
  const run = (cmd, args, parse) => {
    try { return parse(execFileSync(cmd, args, { encoding: 'utf8' })); }
    catch (e) { tried.push(`${cmd} → ${e.code || e.message}`); return null; }
  };
  const toWH = (tool) => (out) => {
    const m = out.trim().match(/^(\d+)\s+(\d+)$/);
    assert.ok(m, `${tool} 输出「${out.trim()}」不是 "宽 高"`);
    return { w: Number(m[1]), h: Number(m[2]), tool };
  };
  const byIM = run('identify', ['-format', '%w %h', p], toWH('ImageMagick identify'));
  if (byIM) return byIM;
  for (const py of [new URL('../../backend/.venv/bin/python', import.meta.url).pathname, 'python3']) {
    const byPIL = run(py, ['-c', 'import sys;from PIL import Image;print(*Image.open(sys.argv[1]).size)', p],
      toWH(`PIL @ ${py}`));
    if (byPIL) return byPIL;
  }
  assert.fail(`量不出 ${p} 的固有尺寸，因此 width/height 无从校验。试过：${tried.join(' | ')}。`
    + ' 装上 ImageMagick（identify）或带 PIL 的 python 再跑——把尺寸写死在测试里等于放弃这条 CLS 防线。');
}

test('S6-4 + CLS: Hero copy is on the page and img.shot carries the file\'s measured intrinsic size', () => {
  const s = html('index.html');
  for (const [what, txt] of [['title', copy.hero.title], ['subtitle', copy.hero.subtitle], ['caption', copy.hero.caption]]) {
    assert.ok(strip(s).includes(txt), `Hero 的 ${what} 没进页面：${txt}`);
  }
  // 全局约束 13：属性顺序无关（`<img src=… class="shot">` 一样要认，写死顺序就是假失败的来源）
  const tag = (s.match(/<img\b[^>]*\bclass="shot"[\s\S]*?>/) || [''])[0];
  assert.ok(tag, 'Hero 的 img.shot 缺失');
  assert.ok(new RegExp(`alt="${esc(copy.hero.screenshot_alt)}"`).test(tag),
    'img.shot 的 alt 必须取自 copy.hero.screenshot_alt（§6 诚实性 ④ 的「设计稿非实况」标注在此）');
  assert.match(tag, /loading="eager"/, '首屏 Hero 图不得懒加载（§6 性能项）');
  const src = (tag.match(/src="([^"]+)"/) || [])[1] || '';
  const tail = src.slice(src.indexOf('/images/'));
  assert.ok(tail.startsWith('/images/'), `src「${src}」里没有 /images/ —— 找不到要量的文件`);
  const file = new URL(`../source${tail}`, import.meta.url);
  assert.ok(existsSync(file), `img.shot 指向 ${tail}，但 source${tail} 不在，判据无从测量`);
  const { w, h, tool } = intrinsicSize(file);
  const attr = (name) => Number((tag.match(new RegExp(`${name}="(\\d+)"`)) || [])[1]);
  assert.ok(attr('width') > 0 && attr('height') > 0, `img.shot 缺 width/height 属性（实测 ${tool} ${w}×${h}）`);
  assert.equal(attr('width'), w, `${tool} 实测 ${tail} 宽 ${w}：width 属性写错就是给浏览器错的宽高比，反而制造 CLS`);
  assert.equal(attr('height'), h, `${tool} 实测 ${tail} 高 ${h}：height 属性必须等于固有高度`);
});

// 徽章态一律经 copy.labels.badge_pill_state 现取，判据里不写死 ok / warn（定位条那两处 info 是
// 设计方案 §2.1 段 3 的直接要求，与徽章映射表无关）。
const pillState = (b) => copy.labels.badge_pill_state[b];
// 全局约束 13：切 section / 卡片一律用属性顺序无关的形式（`id` 与 `class` 谁在前都认）。
const sectionById = (src, id) =>
  (src.match(new RegExp(`<section\\b[^>]*\\bid="${id}"[\\s\\S]*?<\\/section>`)) || [''])[0];

test('S6-1 数据门：地基四条齐备且档位全是 shipped', () => {
  assert.equal(copy.foundation.items.length, 4);
  for (const it of copy.foundation.items) {
    assert.equal(it.badge, 'shipped', `地基卡「${it.title}」档位是 ${it.badge}，S6-1 要求 shipped`);
  }
});

test('S6-1 渲染门：徽章逐卡落在 .feat-card 内、态派生自数据，整段不许出现别的态', () => {
  const s = html('index.html');
  const cardHtml = sectionById(s, 'foundation');
  assert.ok(cardHtml, 'public/index.html 里没有 <section id="foundation">');
  // 渲染门与数据门各自成立（Important 1c）：把 items[i].badge 改成 partial 再 hexo generate，
  // 红的是这一条——页面**真的**画出了非 shipped 态徽章。只留断数据那条，等于「只禁止改字典，不禁止页面画错」。
  for (const state of [...new Set(Object.keys(copy.labels.badge_pill_state)
    .filter((b) => b !== 'shipped').map(pillState))]) {
    assert.equal([...cardHtml.matchAll(new RegExp(`class="pill ${esc(state)} badge"`, 'g'))].length, 0,
      `地基段渲染出了 ${state} 态徽章：S6-1 的四条必须是 shipped 态（设计方案 §3.5）`);
  }
  // 卡数守恒（Important 1 第 2 条）：把 .feat-card 换成 <div> 时，逐卡判据会因为扫不到开标签而空转，这条先红。
  assert.equal([...cardHtml.matchAll(/<article\b[^>]*\bclass="feat-card/g)].length, copy.foundation.items.length,
    '地基段 .feat-card 数量必须等于 copy.foundation.items.length');
  const cards = [...cardHtml.matchAll(/<article\b[^>]*\bclass="feat-card[^"]*"[\s\S]*?<\/article>/g)].map((m) => m[0]);
  assert.equal(cards.length, copy.foundation.items.length, '按 <article…>…</article> 切不出 items.length 张地基卡');
  // 逐卡、卡内、派生自数据（Important 1 第 1 条）。评审给的写法是对整段 assert.match 惰性扫描，
  // 这里切到每张卡自己的片段再判：惰性扫描只需「某张卡之后存在一枚对的徽章」，四枚堆在第一张卡里也绿。
  cards.forEach((card, i) => {
    const it = copy.foundation.items[i];
    assert.match(card, new RegExp(`class="pill ${esc(pillState(it.badge))} badge"`),
      `地基第 ${i + 1} 卡「${it.title}」的 ${pillState(it.badge)} 徽章没渲染在卡内`);
  });
  assert.equal([...cardHtml.matchAll(new RegExp(`class="pill ${esc(pillState('shipped'))} badge"`, 'g'))].length,
    copy.foundation.items.length, '地基段 shipped 态徽章数必须等于 items.length');
});

test('S6-1 模板门：地基徽章由 partial(partial/badge) 的迭代变量出，index.ejs 不手写 pill', () => {
  // 先剥 EJS 注释：index.ejs 段 4 的说明注释里就原样写着 `<section id="foundation"`，
  // 不剥的话切片会从注释起，判据在改注释时莫名其妙地变。
  const idxSrc = readFileSync(new URL('../themes/syntime/layout/index.ejs', import.meta.url), 'utf8')
    .replace(/<%#[\s\S]*?%>/g, '');
  const sec = sectionById(idxSrc, 'foundation');
  assert.ok(sec, 'themes/syntime/layout/index.ejs 里没有地基段 <section id="foundation">');
  assert.match(sec, /partial\('partial\/badge',\s*\{badge:\s*it\.badge/,
    "地基段徽章必须走 partial('partial/badge', {badge: it.badge…})，badge 的实参是迭代变量而不是字面量");
  assert.equal([...sec.matchAll(/partial\('partial\/badge'/g)].length, 1,
    '地基段只该有循环里那一次 partial 调用；多出来就说明有徽章不再派生自 items[]');
  // 这三条专杀 Important 1a：删掉 partial、在 </section> 前硬写四枚 <span class="pill ok badge">。
  // 那种改法在产物上仍是 4 枚、逐卡判据也照样绿，只有模板源级判据能拦住——渲染与数据就此脱钩，
  // 将来某卡改档（partial/dev）也不会红，因为它根本不再读 items[].badge。
  assert.doesNotMatch(idxSrc, /class="pill ok badge"/,
    'index.ejs 里不得出现手写的 class="pill ok badge"');
  assert.doesNotMatch(sec, /<span\b[^>]*\bclass="pill/,
    '地基段不得直接写 <span class="pill…">，徽章一律经 partial/partial/badge 出');
});

test('pills row renders all 4 positioning pills', () => {
  const s = html('index.html');
  assert.equal(copy.pills.length, 4);
  // 先切容器再计数：ALPHA 横幅自己就是一枚 pill info（dev→info，public/index.html:24），
  // 页级 matchAll(/class="pill info"/g) 会得到 5，把横幅那枚算进定位条头上。
  const row = (s.match(/<div\b[^>]*\bclass="pills-row"[\s\S]*?<\/div>/) || [''])[0];
  assert.ok(row, '段 3 的 .pills-row 容器缺失');
  assert.equal([...row.matchAll(/class="pill info"/g)].length, copy.pills.length,
    '定位条必须是 pills.length 枚 pill info（横幅那枚 pill info 在 .alpha 里，不在本容器内）');
  assert.equal([...row.matchAll(/<span\b[^>]*\bclass="pill\b/g)].length, copy.pills.length,
    '定位条里的 pill 总数就是 pills.length（`pill\b` 是为了不把容器自己的 class="pills-row" 数进来）');
  for (const p of copy.pills) assert.ok(strip(row).includes(p), `定位条缺文案：${p}`);
  assert.doesNotMatch(s, /Docker 一键拉起/, 'V1.1 removed this pill (no image published)');
});

// 扫出 src 里所有 @media (max-width:900px) 的**块体**：按花括号深度配对找闭合。
// 不用惰性正则 `[\s\S]*?\}\s*(?=@media|\/\*|$)`（评审给的是起点）：实测两种错法——
// ① 块内再嵌一层 @media 时它只认到第一层，把含覆写的那个块扫漏（假失败）；
// ② 900 块之后紧跟普通规则时它一路并进同一个"块体"，覆写掉到媒体查询外（桌面也塌单列）照样判绿（假通过）。
// 取证见 task-5-report.md 的 Fix round 1 / Minor 2。
function media900Blocks(src) {
  const out = [];
  for (const m of src.matchAll(/@media \(max-width:900px\)\s*\{/g)) {
    let depth = 1, j = m.index + m[0].length;
    while (j < src.length && depth > 0) {
      if (src[j] === '{') depth++;
      else if (src[j] === '}') depth--;
      j++;
    }
    assert.ok(depth === 0, 'APPENDIX 里有 @media (max-width:900px) 的花括号没配上，判据无从切块');
    out.push(src.slice(m.index + m[0].length, j - 1));
  }
  return out;
}

test('地基 2×2 在手机上塌成单列（.feat-grid-2 两条规则都在 APPENDIX）', () => {
  const css = readCss();
  const marker = css.indexOf('V1.1–V1.3 增补结构');
  const head = css.slice(0, marker), tail = css.slice(marker);
  assert.ok(!head.includes('.feat-grid-2'), '.feat-grid-2 是本站新 class，不得进转录区');
  assert.match(tail, /\.feat-grid-2\{grid-template-columns:repeat\(2,1fr\)\}/);
  // 扫全表而不是只看第一个 900 块（Minor 2）：T11 极可能再补一条 ≤900，
  // 覆写落在第二个块里时旧写法的 match 会假失败。
  const blocks = media900Blocks(tail);
  assert.ok(blocks.length >= 1, 'APPENDIX 里没有 ≤900 断点');
  assert.ok(blocks.some((b) => /\.feat-grid-2\{grid-template-columns:1fr\}/.test(b)),
    '缺 ≤900 的单列覆写：附录里的 repeat(2,1fr) 会因源码顺序赢过转录区 .feat-grid{1fr}，手机上仍是两列');
});
