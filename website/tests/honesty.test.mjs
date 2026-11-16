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

// ---------------------------------------------------------------------------
// T6 段 5：功能特性六卡（徽章 + badge_note 强制出口）
// ---------------------------------------------------------------------------
const EXPECTED_TIERS = { settlement: 'partial', budget: 'partial', asset: 'partial',
  events: 'partial', governance: 'partial', export: 'dev' };

test('S6-1 数据门：六卡档位逐字等于设计稿 §3.5 能力表，且 partial/dev 必带 note', () => {
  assert.equal(copy.features.cards.length, 6);
  assert.deepEqual(Object.fromEntries(copy.features.cards.map((c) => [c.id, c.badge])), EXPECTED_TIERS);
  for (const c of copy.features.cards) {
    if (c.badge !== 'partial' && c.badge !== 'dev') continue;
    assert.ok(c.badge_note && c.badge_note.trim().length >= 20,
      `${c.id}: ${c.badge} 卡缺 badge_note 或过短（§6 诚实性 ②：一个徽章糊过去等于没标）`);
  }
});

test('S6-2 渲染门：徽章与 note 逐卡落位、态派生自数据、各态计数与档位表一致', () => {
  const sec = sectionById(html('index.html'), 'features');
  assert.ok(sec, 'public/index.html 里没有 <section id="features">');
  const cards = [...sec.matchAll(/<article\b[^>]*\bclass="feat-card[^"]*"[\s\S]*?<\/article>/g)].map((m) => m[0]);
  assert.equal(cards.length, copy.features.cards.length, '按 <article…>…</article> 切不出 6 张功能卡');
  cards.forEach((card, i) => {
    const c = copy.features.cards[i];
    const st = pillState(c.badge);
    // 徽章与 note 都必须在**这张卡自己的片段里**：整段 includes 会让「四枚徽章堆在第一张卡」
    // 或「所有 note 挤到最后一张卡」照样绿（T5 修复轮的同一族缺陷，别再犯）。
    assert.match(card, new RegExp(`class="pill ${esc(st)} badge"`),
      `第 ${i + 1} 卡「${c.title}」的 ${st} 徽章没渲染在卡内`);
    assert.match(card, new RegExp(`class="badge-note"[^>]*>\\s*${esc(c.badge_note.slice(0, 40))}`),
      `第 ${i + 1} 卡「${c.title}」的 badge_note 没渲染在卡内`);
    // 标题/正文也逐卡锁：只查徽章和 note 时，模板整个删掉 <h3> 和 <p> 仍能全绿。
    const text = strip(card);
    assert.ok(text.includes(c.title), `第 ${i + 1} 卡的标题「${c.title}」没渲染在卡内`);
    assert.ok(text.includes(c.body), `第 ${i + 1} 卡「${c.title}」的正文没渲染在卡内`);
  });
  // 绝对计数门：只断言「每卡都有自己的态」时，把两卡档位**互换**在整段层面看不出来；
  // 逐卡已能抓互换，这条再兜住「多画/少画徽章」，且红话直接指出是哪个态。
  for (const [tier, st] of Object.entries(copy.labels.badge_pill_state)) {
    const want = copy.features.cards.filter((c) => c.badge === tier).length;
    assert.equal([...sec.matchAll(new RegExp(`class="pill ${esc(st)} badge"`, 'g'))].length, want,
      `功能段 ${tier}→${st} 态徽章数应为 ${want}`);
  }
});

test('S6-1 模板门：徽章与图标都由迭代变量出，index.ejs 不手写 pill', () => {
  const idxSrc = readFileSync(new URL('../themes/syntime/layout/index.ejs', import.meta.url), 'utf8')
    .replace(/<%#[\s\S]*?%>/g, '');
  const sec = sectionById(idxSrc, 'features');
  assert.ok(sec, 'themes/syntime/layout/index.ejs 里没有段 5 <section id="features">');
  assert.match(sec, /partial\('partial\/badge',\s*\{badge:\s*c\.badge/,
    "徽章必须走 partial('partial/badge', {badge: c.badge…})，实参是迭代变量");
  assert.match(sec, /partial\('partial\/feat-icon',\s*\{id:\s*c\.id/,
    "图标必须走 partial('partial/feat-icon', {id: c.id…})");
  assert.equal([...sec.matchAll(/partial\('partial\/badge'/g)].length, 1,
    '段 5 只该有循环里那一次徽章调用；多出来就说明有卡不再派生自 cards[]');
  assert.doesNotMatch(sec, /<span\b[^>]*\bclass="pill/, '段 5 不得直接写 <span class="pill…">');
});

test('S6-3 no feature card body repeats a claim the note walks back', () => {
  const banned = /开箱即用|自动同步已上线|三条链路/;
  for (const c of copy.features.cards) {
    assert.doesNotMatch(c.title, banned, `${c.id}: title 含 §6 禁止表述`);
    assert.doesNotMatch(c.body, banned, `${c.id}: body 含 §6 禁止表述`);
  }
});

// 与 tokens.test.mjs:9-12 同一个原型路径与同一个「原型不在就 skip」先例；本文件此前不读原型。
const PROTO_URL = new URL('../../../高保真原型_宣传站.html', import.meta.url);
const normWs = (x) => x.replace(/\s+/g, '');

test('功能图标逐字节转录自原型 :464-489（按**标题**成对锁定：不重画、不串档、不整对互换）',
  existsSync(PROTO_URL) ? {} : { skip: '原型 HTML 不在约定路径，转录判据无从比对' }, () => {
    const proto = readFileSync(PROTO_URL, 'utf8');
    // 原型把「色底 + 图形」绑在**标题**上（`:464-489` 每卡的 f-ic 紧跟 h3），所以按标题取一对。
    // 两个都被否掉的写法：① 只查「这对色底+图形在原型某处存在」——抓得住图形配错色底，
    // 抓不住两卡**整对互换**（A 卡画 B 卡的真图标也算"转录正确"，而它标错了功能）；
    // ② 按数组下标对齐 pairs[i]——卡序是**内容**，copy.yml 调序就该跟着调，按序对齐会假失败。
    const blocks = [...proto.matchAll(
      /<div class="f-ic ([\w-]+)">(<svg[\s\S]*?<\/svg>)<\/div>\s*<h3>([^<]*)<\/h3>/g)];
    // 先数原始块再建 Map：只有 size 判据时，原型若多出第七块且标题与既有某卡重复，
    // Map 去重后仍是 6，断言照样绿，而重复标题那张卡的图标被静默丢掉了。
    assert.equal(blocks.length, 6, '原型里应恰好 6 个「色底+图形+标题」块——本判据的前提（原型那六张卡）变了');
    const byTitle = new Map(blocks.map((m) => [m[3], [m[1], normWs(m[2])]]));
    assert.equal(byTitle.size, 6, '原型六卡的 <h3> 标题有重复——标题不再是可用的配对键，改用别的配对方式');
    const cards = [...sectionById(html('index.html'), 'features')
      .matchAll(/<article\b[^>]*\bclass="feat-card[^"]*"[\s\S]*?<\/article>/g)].map((m) => m[0]);
    assert.equal(cards.length, copy.features.cards.length, '六卡的 <article> 切不出来');
    cards.forEach((card, i) => {
      const c = copy.features.cards[i];
      const m = card.match(/<div\b[^>]*\bclass="f-ic ([\w-]+)"[^>]*>([\s\S]*?)<\/div>/);
      assert.ok(m, `第 ${i + 1} 卡「${c.title}」里没有 .f-ic`);
      const svg = normWs((m[2].match(/<svg[\s\S]*?<\/svg>/) || [''])[0]);
      assert.ok(svg, `第 ${i + 1} 卡「${c.title}」的 .f-ic 里没有 <svg>`);
      const want = byTitle.get(c.title);
      assert.ok(want, `原型里没有标题为「${c.title}」的功能卡——判据靠标题配对，图标对应关系需重新确认`);
      assert.deepEqual([m[1], svg], want,
        `第 ${i + 1} 卡「${c.title}」的图标不是原型**同一张卡**的色底+图形逐字转录（原型 ${want[0]}，产物 ${m[1]}）：图标被重画、改写、配错色底或与别卡整对互换`);
    });
  });

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

// ---------------------------------------------------------------------------
// T7 段 6：界面速览（真截图 + `.seg` 切换 + `disclaimer`）
// ---------------------------------------------------------------------------

// class 命中一律按 **token 集合**判，不看属性序也不看兄弟 class 的书写顺序（全局约束 13）。
// 为什么不用 `[^"]*\bseg\b[^"]*`：`-` 本身就是非词字符，实测 node 里
// /<div\b[^>]*\bclass="[^"]*\bseg\b[^"]*"/.test('<div class="seg-row">') === true，
// 于是「.seg 控件」与「.seg-row 容器」在判据里失去区分——把两条不同的东西挂到同一个匹配上，
// 正是约束 13 要避免的那类耦合（控制者裁定 4 给的写法在此偏宽，故收紧为 token 判等）。
const classTags = (src, token, tag = 'div') =>
  [...src.matchAll(new RegExp(`<${tag}\\b[^>]*\\bclass="([^"]*)"[^>]*>`, 'g'))]
    .filter((m) => m[1].trim().split(/\s+/).includes(token));
const cls = (m) => m[1].trim().split(/\s+/);
const attr = (tag, name) => (tag.match(new RegExp(`\\b${name}="([^"]*)"`)) || [])[1];
// 面板按**开标签下标**切，不用惰性 `[\s\S]*?<\/div>`：panel 里套了 .shot-frame 的 `</div>`，
// 惰性版只切到 shot-frame 就断，图注整段落在切片外 → 逐面板判据空转（假通过的温床）。
const panelBlocks = (g) => {
  const at = classTags(g, 'shot-panel').map((m) => m.index);
  return at.map((i, n) => g.slice(i, at[n + 1] ?? g.lastIndexOf('</section>')));
};
const openOf = (blk) => (blk.match(/^<div\b[^>]*>/) || [''])[0];

test('S6-4 数据门：四段齐备、disclaimer 说出「非…实况」、被 includes 引用的文案不含 HTML 特殊字符', () => {
  assert.equal(copy.gallery.segments.length, 4, '界面速览固定 4 段（设计方案 §2.1 段 6）');
  for (const [i, seg] of copy.gallery.segments.entries()) {
    for (const k of ['title', 'image', 'alt']) {
      assert.ok(typeof seg[k] === 'string' && seg[k], `segments[${i}] 缺 ${k} 键`);
    }
    assert.match(seg.image, /^\/images\/gallery\/[\w-]+\.webp$/, `segments[${i}].image 不是站点内 webp 路径`);
  }
  // §6 诚实性 ④ 要的是**承认截图不是运行中的产品**这一半。brief 的 /非产品运行实况|非运行实况|设计稿/
  // 三支择一，比 data.test.mjs:59 已有的 /设计稿/ 更宽，等于没新增防线（改写掉「非实况」它照样绿）；
  // 这里钉住「非…实况 / 非…运行」这半句（设计方案 §2.1 段 6 的 V1.1 强制原文就含它），
  // 同时容许「非产品实际运行画面」「非运行中的产品」这类同义改写——/tmp/t7-datagate-probe.mjs 有四例对照。
  assert.match(copy.gallery.disclaimer, /非[^。]{0,14}(?:实况|运行)/,
    'gallery.disclaimer 必须承认截图「非…实况/非…运行」：只留「设计稿」是设计方案 §2.1 段 6 不接受的写法');
  // 下面的渲染门全部走 includes / indexOf 判**未解码的 HTML 字面量**（strip() 不解实体）。
  // 实测 copy.gallery 今天不含 < > & " （本条即哨兵），所以两种写法同值；将来有人往 alt / disclaimer
  // 里塞一个 & 或 <，`<%= %>` 会把它转义成 &amp;/&lt;，includes 静默失配 → 判据假绿，故当场红给它看。
  const dirty = [];
  const seen = [['disclaimer', copy.gallery.disclaimer], ['heading', copy.gallery.heading],
    ['subheading', copy.gallery.subheading],
    ...copy.gallery.segments.flatMap((sg, i) => [[`segments[${i}].alt`, sg.alt], [`segments[${i}].title`, sg.title]])];
  for (const [k, v] of seen) if (/[<>&"']/.test(String(v))) dirty.push(`${k}: ${v}`);
  assert.deepEqual(dirty, [],
    '这些字符会被 <%= %> 转义，而 includes 型判据读的是转义前的原文 → 静默失配（假绿）；改文案前先解耦判据');
});

test('S6-4 渲染门：disclaimer 逐字渲染在分段控件之上（控件缺失必须红，不接受 -1 < n）', () => {
  const g = sectionById(html('index.html'), 'gallery');
  assert.ok(g, 'public/index.html 里没有 <section id="gallery">');
  const d = classTags(g, 'disclaimer', 'p')[0];
  const seg = classTags(g, 'seg')[0];
  // 控制者裁定 4：brief 的 `indexOf('class="disclaimer"') < indexOf('class="seg"')` 在
  // disclaimer **整行缺失**时得到 -1 < n，为真 → 假通过。先各自断言存在，再比大小。
  assert.ok(d, '段 6 没有 <p class="disclaimer">');
  assert.ok(seg, '段 6 没有 .seg 分段控件');
  assert.ok(d.index > 0 && seg.index > 0, 'disclaimer 与 .seg 的下标都必须是真实存在的正值');
  assert.ok(d.index < seg.index,
    'disclaimer 必须在 .seg 之上（设计方案 §2.1 段 6「分段控件上方固定一行 disclaimer」）');
  assert.ok(strip(g).includes(copy.gallery.disclaimer),
    '页面上的 disclaimer 必须逐字等于 copy.gallery.disclaimer，模板不得另写一份');
  assert.equal(classTags(g, 'seg-row').length, 1, '段 6 必须有且只有一个 .seg-row 容器（原型 :504 的居中版式）');
});

test('S6-4 渲染门：四张真截图的 src / alt / 固有尺寸逐张现量比对文件字节，作废 mock DOM 已绝迹', () => {
  const s = html('index.html');
  const g = sectionById(s, 'gallery');
  assert.ok(g, 'public/index.html 里没有 <section id="gallery">');
  for (const seg of copy.gallery.segments) {
    // 只在**本段**里找这张图：dashboard.webp 同时被 Hero 用着（index.ejs:24），
    // 整页 s.match 会先命中 Hero 那枚 `<img class="shot" … width="2880" height="2556">`，
    // 于是"速览段的 dashboard 有没有写宽高"这条判据其实在替 Hero 背书——段 6 删掉宽高也照样绿。
    const tag = (g.match(new RegExp(`<img\\b[^>]*\\bsrc="[^"]*${esc(seg.image)}"[^>]*>`)) || [''])[0];
    assert.ok(tag, `段 6 没有 emit ${seg.image}`);
    assert.ok(new RegExp(`alt="${esc(seg.alt)}"`).test(tag), `${seg.image}: alt 必须逐字等于 copy 的 alt`);
    assert.match(tag, /loading="lazy"/, `${seg.image}: 段 6 在首屏之下必须懒加载（首屏 eager 那张归 Hero，另有判据）`);
    const file = new URL(`../source${seg.image}`, import.meta.url);
    assert.ok(existsSync(file), `copy 指向 ${seg.image}，但 source${seg.image} 不在，判据无从测量`);
    // 固有尺寸**现量**（复用本文件 :150 的 intrinsicSize）：模板 DIMS 与文件字节谁改了都当场红，
    // 判据里不再抄第二份尺寸表（控制者裁定 1）。
    const { w, h, tool } = intrinsicSize(file);
    const width = Number(attr(tag, 'width'));
    const height = Number(attr(tag, 'height'));
    assert.ok(width > 0 && height > 0, `${seg.image}: 产物没有 width/height 属性（${tool} 实测 ${w}×${h}）`);
    assert.equal(width, w, `${tool} 实测 ${seg.image} 宽 ${w}，产物写 ${width}：错的宽高比本身就是 CLS`);
    assert.equal(height, h, `${tool} 实测 ${seg.image} 高 ${h}，产物写 ${height}：模板 DIMS 已与文件字节脱钩`);
  }
  assert.doesNotMatch(s, /class="shot-side|class="mtbl|class="donut/, 'obsolete mockup DOM must be gone');
});

test('T7 DOM 契约：.seg button[data-shot] ↔ .shot-panel[data-shot]（Task 10 的 JS 全靠这条）', () => {
  const g = sectionById(html('index.html'), 'gallery');
  assert.ok(g, 'public/index.html 里没有 <section id="gallery">');
  const segTag = classTags(g, 'seg')[0];
  assert.ok(segTag, '段 6 没有 .seg 控件');
  // 按钮只可能在 .seg 里：从它的开标签切到它自己的 `</div>`（.seg 内不再嵌套 div）
  const segBlock = g.slice(segTag.index, g.indexOf('</div>', segTag.index));
  const btns = [...segBlock.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map((m) => m[0]);
  const panels = panelBlocks(g);
  assert.equal(btns.length, copy.gallery.segments.length, '按钮数必须等于 segments.length');
  assert.equal(panels.length, copy.gallery.segments.length, '面板数必须等于 segments.length');
  const btnKeys = btns.map((t) => attr(t, 'data-shot'));
  const panelKeys = panels.map((p) => attr(openOf(p), 'data-shot'));
  assert.equal(new Set(btnKeys).size, btns.length, '按钮的 data-shot 有重复：一键点亮两块，T10 无从配对');
  assert.deepEqual(panelKeys.sort(), btnKeys.sort(),
    'button 与 panel 的 data-shot 键集必须相等——T10 按它配对，缺一边就是点了没反应');
  const shown = panels.filter((p) => !/(^|\s)hidden(?=[\s>])/.test(openOf(p)));
  assert.equal(shown.length, 1, `初始必须恰好一块面板可见，现在 ${shown.length} 块`);
  assert.equal(attr(openOf(shown[0]), 'data-shot'), '0', '默认可见的必须是第 1 段（与 aria-selected 的 i===0 同源）');
  for (const t of btns) assert.ok(['true', 'false'].includes(attr(t, 'aria-selected')), '每枚按钮都要有 aria-selected');
  assert.equal(btns.filter((t) => attr(t, 'aria-selected') === 'true').length, 1, 'aria-selected="true" 必须恰好一枚');
  for (const t of btns) assert.match(t, /role="tab"/, '切换按钮必须是 role="tab"（分段控件的 ARIA 形态）');
  assert.match(segTag[0], /role="tablist"/, '.seg 容器必须是 role="tablist"');
  // 控制者裁定 2：`.io.in{opacity:1}`（main.css:213）是 T10 的运行契约，模板预置 `in` 会让
  // 速览的淡入永远不触发，还会把 T10 的入场 bug 掩成"看起来正常"。这里只许 io，一条都不许多。
  const ioChk = (tag, wantIo) => {
    const toks = cls(tag);
    assert.equal(toks.includes('io'), wantIo, `${tag[1]}：入场锁 io 的有无与原型不一致`);
    assert.ok(!toks.includes('in'), `${tag[1]}：模板不得预置 in——淡入由 T10 的 IntersectionObserver 加，不是写死`);
  };
  for (const f of classTags(g, 'shot-frame')) ioChk(f, true);
  assert.equal(classTags(g, 'shot-frame').length, copy.gallery.segments.length, '每块面板各一个 .shot-frame');
  ioChk(classTags(g, 'seg-row')[0], true);
  for (const c of classTags(g, 'shot-cap', 'p')) ioChk(c, true);
});

test('S6-4 诚实装置：每张面板自己的图注都带 disclaimer，不只首屏', () => {
  const g = sectionById(html('index.html'), 'gallery');
  const panels = panelBlocks(g);
  assert.equal(panels.length, copy.gallery.segments.length, '面板切不出来，逐面板判据无从落地');
  panels.forEach((p, i) => {
    const seg = copy.gallery.segments[i];
    const cap = (p.match(/<p\b[^>]*\bclass="[^"]*\bshot-cap\b[^"]*"[^>]*>([\s\S]*?)<\/p>/) || [])[1];
    assert.ok(cap, `第 ${i + 1} 面板没有自己的 .shot-cap`);
    // 逐面板、面板内：只对整个 section 做 includes 时，「四张图注里只有一张说实话」照样绿。
    assert.ok(cap.includes(seg.title), `第 ${i + 1} 面板的图注没有该段标题「${seg.title}」`);
    assert.ok(cap.includes(copy.gallery.disclaimer),
      `第 ${i + 1} 面板（${seg.title}）的图注没带 disclaimer：切到这一段就没人说实话了（§6 诚实性 ④ 是复数）`);
  });
});

test('T7 模板门：段 6 由 C.gallery.segments 迭代出，DIMS 键集与 copy 的图片一一对应，url_for 走转义形态', () => {
  // 与 T5/T6 的模板门同族：产物级判据抓不到「模板改回写死四段」——那种改法今天的产物照样全绿，
  // 但第五段一进 copy.yml 就不会出现（渲染与数据就此脱钩）。
  const idxSrc = readFileSync(new URL('../themes/syntime/layout/index.ejs', import.meta.url), 'utf8')
    .replace(/<%#[\s\S]*?%>/g, '');
  const sec = sectionById(idxSrc, 'gallery');
  assert.ok(sec, 'themes/syntime/layout/index.ejs 里没有段 6 <section id="gallery">');
  assert.equal([...sec.matchAll(/C\.gallery\.segments\.forEach/g)].length, 2,
    '按钮一轮、面板一轮两次迭代；少一次就说明有东西不再派生自 segments[]');
  assert.equal([...sec.matchAll(/<img\b/g)].length, 1, '段 6 只许一张模板化的 <img>：写死四张就不再派生自 segments[]');
  // DIMS 的键集 == copy 的图片集。换图 / 加第五段而忘补 DIMS 时 `DIMS[g.image][0]` 在渲染期抛
  // TypeError，而 `hexo generate` 的退出码仍是 0（task-6-report.md 取证纪律 1）——只有文本判据抓得住。
  const keys = [...sec.matchAll(/'(\/images\/gallery\/[\w.-]+)'/g)].map((m) => m[1]);
  assert.deepEqual(keys.sort(), copy.gallery.segments.map((x) => x.image).sort(),
    '模板 DIMS 的键必须与 copy.gallery.segments[].image 一一对应（多余的键是死数据，缺的键构建即崩）');
  assert.equal([...sec.matchAll(/\/images\/gallery\//g)].length, copy.gallery.segments.length,
    '段 6 的图片路径只许出现在 DIMS 的键上，别处再抄一份就是第二个来源');
  // 控制者裁定 7：`<%- url_for() %>` 是未转义输出，T11 要扫的就是这份清单；此处一律 `<%= %>`，
  // 这些路径不含 HTML 特殊字符，产物逐字节相同（已核），只是不再往清单里添条目。
  assert.doesNotMatch(sec, /<%-\s*url_for/, '段 6 的 url_for 必须走 <%= %> 转义形态');
  assert.doesNotMatch(sec, /class="shot-frame io in"/, '模板不得再出现 io in 形态');
});

test('T7 CSS 门：.shot-frame 的封顶与可滚只有 APPENDIX 那一条覆写，白底仍归转录区', () => {
  const css = readCss();
  const marker = css.indexOf('V1.1–V1.3 增补结构');
  assert.ok(marker > 0, '找不到增补段标记，覆写区与转录区失去边界');
  const rules = (css.slice(marker).replace(/\/\*[\s\S]*?\*\//g, '').match(/\.shot-frame\{[^}]*\}/g)) || [];
  assert.equal(rules.length, 1, '增补段里 .shot-frame 必须且只有一条覆写规则（0 条 = 封顶丢了，>1 条 = 同一属性两个来源）');
  const decls = rules[0].slice(rules[0].indexOf('{') + 1, -1);
  assert.match(decls, /max-height:\d+(?:\.\d+)?vh/,
    '四张截图长宽不一（2674 / 2556 / 1800），不封顶则切 tab 时页面高度跟着跳');
  assert.match(decls, /overflow:auto/,
    '封顶后必须可滚：转录区 :140 是 overflow:hidden，整页截取的尾巴会永久裁在框外、滚也滚不到');
  // 裁定 6：brief Step 4 的 background:var(--gray-25) 会覆掉逐字节基准的 #fff，属无因偏离，不加。
  assert.doesNotMatch(decls, /background/, '底色只能有一条来源（转录区 :140 的 #fff）；要改底色请连基准一起改，别在附录里偷偷覆写');
  assert.ok(css.slice(0, marker).includes('.shot-frame{background:#fff'), '转录区的 .shot-frame 白底必须原样在位');
});
