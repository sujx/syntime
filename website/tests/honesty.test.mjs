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
  // 图文配对按**面板下标 ↔ segments 下标**对齐（评审 Minor 1）：整段 g.match 只证明「段 6 某处有这张图」，
  // 把两面板的 image+alt+尺寸整组对调时 alt / 尺寸 / 图注全都对得上、src 也全都能找到 → 49 条全绿，
  // 而点「事件中心」出的却是「仪表盘」的图。段 6 是全站唯一可能图文不符的地方，§6 诚实性不容它静默通过。
  // 同时搜索范围也不再放到整页：dashboard.webp 被 Hero 共用（index.ejs:24），整页 s.match 会先命中
  // Hero 那枚 `<img class="shot" …>`，"速览段这张图写没写宽高"就成了替 Hero 背书（首轮 §5.1 / M11）。
  const panels = panelBlocks(g);
  assert.equal(panels.length, copy.gallery.segments.length, '面板数必须等于 segments.length，i↔i 配对无从对齐');
  panels.forEach((p, i) => {
    const seg = copy.gallery.segments[i];
    // 面板序=数据序不是巧合：模板按 segments[] 迭代出 data-shot=i。这条钉住前提，否则 i↔i 配对
    // 在面板被重排后会指错卡，而"配对"正是本轮要守的性质。
    assert.equal(attr(openOf(p), 'data-shot'), String(i),
      `第 ${i + 1} 个面板的 data-shot 不是 ${i}：面板序与 segments 序脱钩，图文配对判据指错卡`);
    const tag = (p.match(new RegExp(`<img\\b[^>]*\\bsrc="[^"]*${esc(seg.image)}"[^>]*>`)) || [''])[0];
    assert.ok(tag, `第 ${i + 1} 面板（${seg.title}）里没有 ${seg.image}——图与面板脱钩了，段 6 别处有这张图不算数`);
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
  });
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
  // 评审 Minor 2：`classTags(...)[0]` 可能是 undefined，直接喂 ioChk 就是 cls(undefined) 抛 TypeError——
  // 崩不是红。隔壁那条「有且只有一个 .seg-row」在**另一个 test()** 里，node:test 用例相互隔离救不了这里。
  const segRow = classTags(g, 'seg-row')[0];
  assert.ok(segRow, '段 6 没有 .seg-row 容器（原型 :504 的居中版式）——io 判据无从落地');
  ioChk(segRow, true);
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

// 评审 Important 1：门要判的是**属性级唯一来源**，不是 `.shot-frame{` 的出现次数。
// 数条数两头都坏：T11 加一条合法的 `@media (max-width:900px){.shot-frame{max-height:60vh}}` 会被判红，
// 而 `.shot-frame,.x{overflow:visible}` 这种合并选择器里的第二个 overflow 来源数不到（实测 49 条全绿）。
// 分堆走花括号深度（同 media900Blocks 的思路），扫描前先剥注释：本段注释里就原样写着
// `.shot-frame{background:#fff}`（main.css:275），不剥就是拿注释顶替真规则。
// media900Blocks 自己的那一行修仍按台账 R27(a) 归 T11，本门不越界替它改。
function appendixRules(src) {
  const text = src.replace(/\/\*[\s\S]*?\*\//g, '');
  const out = [];
  const walk = (chunk, media) => {
    for (let i = 0; i < chunk.length;) {
      const open = chunk.indexOf('{', i);
      if (open < 0) break;
      let depth = 1, j = open + 1;
      while (j < chunk.length && depth > 0) {
        if (chunk[j] === '{') depth++;
        else if (chunk[j] === '}') depth--;
        j++;
      }
      assert.ok(depth === 0, 'APPENDIX 里有没配上的花括号，规则无从分堆');
      const prelude = chunk.slice(i, open).trim();
      const body = chunk.slice(open + 1, j - 1);
      if (/^@(media|supports)\b/.test(prelude)) walk(body, true);
      else if (prelude && !prelude.startsWith('@')) {
        out.push({ selectors: prelude.split(',').map((x) => x.trim()), decls: body, media });
      }
      i = j;
    }
  };
  walk(text, false);
  return out;
}
// 命中条件 = 逗号分开的选择器里有一处**正好是** `.shot-frame`：`.shot-frame,.x` 命中，
// `.shot-frame img`（管的是图不是框）与 `.shot-frame:hover`（态）不算顶层第二个来源。
const onFrame = (r) => r.selectors.includes('.shot-frame');
const declares = (r, prop) => new RegExp(`(?:^|[;])\\s*${prop}\\s*:`, 'm').test(r.decls);

test('T7 CSS 门：.shot-frame 的封顶与可滚只有 APPENDIX 那一条覆写，白底仍归转录区', () => {
  const css = readCss();
  const marker = css.indexOf('V1.1–V1.3 增补结构');
  assert.ok(marker > 0, '找不到增补段标记，覆写区与转录区失去边界');
  const frame = appendixRules(css.slice(marker)).filter(onFrame);
  const top = frame.filter((r) => !r.media);
  const sourcesOf = (prop) => top.filter((r) => declares(r, prop));
  const names = (rs) => rs.map((r) => r.selectors.join(',')).join(' | ');
  for (const [prop, re, why] of [
    ['max-height', /max-height:\d+(?:\.\d+)?vh/, '四张截图长宽不一（2674 / 2556 / 1800），不封顶则切 tab 时页面高度跟着跳'],
    ['overflow', /overflow:auto/, '封顶后必须可滚：转录区 :140 是 overflow:hidden，整页截取的尾巴会永久裁在框外、滚也滚不到'],
  ]) {
    const where = sourcesOf(prop);
    assert.equal(where.length, 1,
      `顶层 .shot-frame 的 ${prop} 必须只有一个来源，现在 ${where.length} 个${where.length ? `（${names(where)}）` : ''}`
      + `。0 个 = 这条防线没了（${why}）；>1 个 = 桌面值有两个顶层来源。`
      + '按视口改值请写进 @media——媒体查询里的 .shot-frame 覆写本门允许（T11 的领地）。');
    assert.match(where[0].decls, re, why);
  }
  // 裁定 6：brief Step 4 的 background:var(--gray-25) 会覆掉逐字节基准的 #fff，属无因偏离，不加。
  // 底色不分视口，所以顶层与 @media 两堆一起按零来源判（不像 max-height 那样给媒体覆写开豁免）。
  assert.doesNotMatch(frame.map((r) => r.decls).join(';'), /background/,
    '底色只能有一条来源（转录区 :140 的 #fff）；要改底色请连基准一起改，别在附录里偷偷覆写');
  assert.ok(css.slice(0, marker).includes('.shot-frame{background:#fff'), '转录区的 .shot-frame 白底必须原样在位');
  // 分类器自检：「@media 覆写允许存在」不能只靠注释承诺（今天产物里还没有媒体覆写，
  // 只靠变异实验证明就等于把它留给 T11 去撞）。合成对照钉住分堆与剥注释两件事。
  const synth = appendixRules('/* .shot-frame{background:#eee} */ .shot-frame{max-height:70vh;overflow:auto}'
    + '@media (max-width:900px){.shot-frame{max-height:60vh}}');
  assert.equal(synth.filter((r) => onFrame(r) && !r.media && declares(r, 'max-height')).length, 1,
    '分堆器把 @media 里的覆写算进了顶层来源——T11 加响应式断点就是假红');
  assert.equal(synth.filter((r) => onFrame(r) && r.media).length, 1,
    '分堆器没把 @media 里的 .shot-frame 认成媒体覆写：两堆混一起，唯一来源就无从判');
  assert.equal(synth.filter((r) => r.decls.includes('background')).length, 0,
    'CSS 注释被当成了规则（台账 R27(a) 同族）：本段注释里就写着 `.shot-frame{background:#fff}`');
});

// ---------------------------------------------------------------------------
// T8 段 7：快速开始（暗极光 + 源码部署四步 + Docker `dev` 卡）
// ---------------------------------------------------------------------------

// 裁定 2（属性顺序无关，全局约束 13 同族）：brief 的 /<pre id="qs-code-2">([\s\S]*?)<\/pre>/
// 与 /<section id="quickstart"/ 都是**字面量顺序**判据——本主题的 markup 写 `class` 在前时它们
// 一处也匹配不到，判据会退化成 `match(...)[1]` 抛 TypeError（崩）或 ?? '' 空转（假通过）。
const preById = (src, id) =>
  (src.match(new RegExp(`<pre\\b[^>]*\\bid="${id}"[^>]*>([\\s\\S]*?)<\\/pre>`)) || [])[1];
const allPres = (src) => [...src.matchAll(/<pre\b[^>]*>([\s\S]*?)<\/pre>/g)].map((m) => m[1]);
// ejs 的 `<%= %>` 走 utils.escapeXML（& < > " ' 五个字符，实测 node_modules/ejs/lib/utils.js:71-82），
// 所以产物里是 &lt;自行生成&gt;。逐行比对 copy 前先按同一张表反解——反序执行会把 &amp;lt; 二次解码成 <。
const unesc = (x) => x.replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&#34;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
// 只剥 span 的开闭标签、不剥别的：`strip()` 用空格替换标签，会把 `<span>a</span><span>b</span>`
// 这种同一行两块也抹成"看着对"的形态，而本判据要钉的正是**一行一块**。
const preLines = (raw) => unesc(raw.replace(/<\/?span\b[^>]*>/g, '')).split('\n');
const spanPerLine = (raw, stepNo) => raw.split('\n').map((seg) => {
  const m = seg.match(/^<span\b[^>]*\bclass="([^"]*)"[^>]*>([\s\S]*?)<\/span>$/);
  assert.ok(m, `第 ${stepNo} 步的代码有一行不是**恰好一个** <span>…</span>（裁定 6 要的就是逐行一块）：${JSON.stringify(seg)}`);
  return { cls: m[1].trim().split(/\s+/), text: unesc(m[2]) };
});

test('S6-3 数据门：四步序号连续、命令文本只活在 copy.yml 里、Docker 形态档位是 dev', () => {
  assert.equal(copy.quickstart.steps.length, 4, '设计方案 §2.1 段 7 固定四步');
  assert.deepEqual(copy.quickstart.steps.map((st) => st.no), [1, 2, 3, 4]);
  assert.equal(copy.quickstart.planned.badge, 'dev', '镜像未发布，Docker 形态只能是 dev（§3.5 档位表）');
  for (const st of copy.quickstart.steps) {
    assert.ok(st.title && st.body && st.code, `第 ${st.no} 步缺 title/body/code`);
    assert.doesNotMatch(st.code, /docker run|docker-compose|docker compose/,
      `第 ${st.no} 步给了可执行的 docker 命令：V1.0 那条实测跑不通`);
  }
});

test('S6-3 全页禁区：任何代码块里都没有可执行的 docker 命令，宣传语两处绝迹', () => {
  const s = html('index.html');
  const blocks = allPres(s);
  // 先数块再判内容：段 7 没落地时 blocks 是空数组，for 循环空转 = 假通过（T6 评审同族的「-1 < n」）。
  assert.ok(blocks.length >= copy.quickstart.steps.length,
    `全页 <pre> 只有 ${blocks.length} 块，少于 steps.length=${copy.quickstart.steps.length}：禁令无从落地`);
  blocks.forEach((pre, i) => assert.doesNotMatch(pre, /docker run|docker-compose|docker compose/,
    `第 ${i + 1} 个代码块写了可执行命令：§6 诚实性 ③ 的当前禁区，且这条跑不通`));
  // 裁定 9：整页禁令只到这两句宣传语——copy.yml:229 的 FAQ 散文「一条 `docker run` 拉起的形态仍在
  // 开发中」是**说实话**而不是命令，扩大 ban 范围等于回头改内容层。
  assert.doesNotMatch(s, /开箱即用|一键拉起/, '§6 禁止表述进了产物');
});

test('代码块里没有凭据形状的字串（连接串内嵌口令 / 键值对明文口令）', () => {
  const blocks = allPres(html('index.html'));
  assert.ok(blocks.length >= copy.quickstart.steps.length, '<pre> 块数少于 steps.length，本判据会空转');
  for (const [i, pre] of blocks.entries()) {
    assert.doesNotMatch(pre, /:[A-Za-z0-9_+/=.\-]{6,}@/,
      `第 ${i + 1} 块：连接串里嵌了口令（postgresql://user:***@host）`);
    // 裁定 1：brief 原式 /PASSWORD|secret[_-]?key\s*=\s*[A-Za-z0-9]/i 的 alternation 在顶层，
    // 裸 `PASSWORD`（无等号）也判红，而 step 2 合法写着 SYNTIME_DB_PASSWORD=<你的口令>——自判自毙。
    // 等号提到分组外之后：真值 PASSWORD=abc123 仍红，转义后的占位符 PASSWORD=&lt;…&gt; 绿。
    assert.doesNotMatch(pre,
      /(?:PASSWORD|SECRET[_-]?KEY|API[_-]?KEY|ACCESS[_-]?KEY)\s*=\s*[A-Za-z0-9]/i,
      `第 ${i + 1} 块：凭据键等号后跟的是真值而非占位符`);
  }
});

test('secrets stay angle-bracket placeholders (HTML-escaped by EJS)', () => {
  const step2 = preById(html('index.html'), 'qs-code-2');
  assert.ok(step2, '产物里没有 <pre …id="qs-code-2">：step 2 的占位符判据无从落地');
  // 这里断言的是**转义后**的形态：模板走 `<%= %>`（裁定 6），改成 `<%- %>` 就变成裸 < >。
  assert.match(step2, /&lt;你的口令&gt;/, 'DB 口令位必须是转义后的 <你的口令>，不是值');
  assert.match(step2, /&lt;自行生成&gt;/, 'SECRET_KEY 位必须是转义后的 <自行生成>');
});

test('S6-3 段 7 结构：暗极光段 + .qs-grid 里四步 + dev 徽章的 Docker 卡 + 环境要求行', () => {
  const q = sectionById(html('index.html'), 'quickstart');
  assert.ok(q, 'public/index.html 里没有 <section id="quickstart">');
  const sec = classTags(q, 'dark-sec', 'section')[0];
  assert.ok(sec, '段 7 必须在 .dark-sec 上（设计方案 §2.1 段 7 = 暗极光）');
  assert.ok(cls(sec).includes('sec'), '段 7 的开标签丢了 .sec（72px 上下留白）');
  // 裁定 3：.qs-grid 是版式承重墙——.qs-grid{repeat(3,1fr)}（main.css:153）、.qs-full{grid-column:1/-1}
  // （:170）、≤900px 塌单列（:229）全挂在它身上；漏了容器则四步全宽竖排，而 tokens.test.mjs:109
  // 只断 CSS 里有 .qs-grid 这条规则，救不回 DOM。
  assert.equal(classTags(q, 'qs-grid').length, 1, '段 7 的卡必须包在唯一的 .qs-grid 里');
  assert.equal(classTags(q, 'step-n').length, copy.quickstart.steps.length, '序号圆点数必须等于四步');
  assert.equal(classTags(q, 'qs-card').length, copy.quickstart.steps.length + 1,
    '.qs-card 必须是四步 + Docker 卡共 5 张');
  for (const st of copy.quickstart.steps)
    assert.match(q, new RegExp(`<pre\\b[^>]*\\bid="qs-code-${st.no}"`), `第 ${st.no} 步没有自己的代码块`);
  // 裁定 7：不再新增 `class="pill info badge"` 这种 token 串字面量（台账约束 13，T13 统一扫）。
  // 按**文案**定位那枚徽章再判 token 集合：档位映射改了，判据跟着数据走，不用改判据本身。
  const tier = copy.quickstart.planned.badge;
  const devTxt = copy.labels.badges[tier];
  const spans = [...q.matchAll(/<span\b[^>]*\bclass="([^"]*)"[^>]*>([\s\S]*?)<\/span>/g)]
    .filter((m) => m[2].trim() === devTxt);
  assert.equal(spans.length, 1, `.quickstart 里应恰好一枚「${devTxt}」徽章，现在 ${spans.length} 枚`);
  const toks = spans[0][1].trim().split(/\s+/);
  for (const t of ['pill', pillState(tier), 'badge'])
    assert.ok(toks.includes(t), `Docker 卡徽章的 class 丢了 ${t}（现 "${spans[0][1]}"）：浅底 pill 是深底上的最高对比档`);
  assert.ok(strip(q).includes(copy.quickstart.planned.body),
    'Docker 卡的实话（镜像尚未发布 + 仍需两个依赖服务）没渲染出来');
  // 裁定 5：requirements 按原型 :726 的版式切成多个 span，**整行逐字出现**这种判据永远不可能绿。
  const parts = copy.quickstart.requirements.split('·').map((x) => x.trim());
  const envAt = classTags(q, 'qs-env')[0];
  assert.ok(envAt, '段 7 没有 .qs-env 容器：环境要求行无从落地');
  // .qs-env 内只有 <span>/<i>，没有嵌套 div，故惰性切到第一个 </div> 就是它自己
  const env = q.slice(envAt.index, q.indexOf('</div>', envAt.index));
  const items = [...env.matchAll(/<span\b[^>]*>([\s\S]*?)<\/span>/g)].map((m) => m[1]);
  assert.equal(items.length, parts.length,
    `.qs-env 的 span 数（${items.length}）必须等于按 · 切出的项数（${parts.length}）`);
  items.forEach((h, i) => {
    assert.match(h, /^<i><\/i>/, `环境要求第 ${i + 1} 项没有 .qs-env i 圆点（原型 :726 的版式）`);
    assert.ok(unesc(h.replace(/<[^>]+>/g, '')).includes(parts[i]),
      `环境要求第 ${i + 1} 项不是「${parts[i]}」：${h}`);
  });
  assert.doesNotMatch(env, /·/, '.qs-env 里残留 · —— 说明要么没切分，要么切了又整行再输一遍');
  assert.match(env, /Python 3\.12/, '环境要求必须写实值（V1.0 那行写的是 Docker）');
  // 入场锁：与 T7 同源——只许 io，`in` 由 T10 的 IntersectionObserver 加（main.css:213）
  for (const t of [...classTags(q, 'qs-card'), ...classTags(q, 'qs-env'), ...classTags(q, 'sec-head')])
    assert.ok(cls(t).includes('io') && !cls(t).includes('in'), `${t[1]}：段 7 的 io/in 与约定不一致`);
});

test('T8 逐行数据门：每步代码块与 copy.quickstart.steps[].code 逐行相等，step 1 的 clone 由占位符拼出', () => {
  const s = html('index.html');
  const want = (st) => (st.no === 1
    ? [`git clone ${copy.placeholders.github_url}.git`]
    : []).concat(st.code.trim().split('\n'));
  for (const st of copy.quickstart.steps) {
    const raw = preById(s, `qs-code-${st.no}`);
    assert.ok(raw, `第 ${st.no} 步没有代码块`);
    assert.deepEqual(preLines(raw), want(st),
      `第 ${st.no} 步的代码块与 copy.quickstart.steps[0].code 不逐行相等（多行 / 少行 / 改写都算）`);
    // 裁定 6 的空白纪律：`<pre>` 里可见空白全算内容——换行数必须恰好 lines.length-1，
    // 行首不得有模板带进去的缩进。
    assert.equal((raw.match(/\n/g) || []).length, want(st).length - 1,
      `第 ${st.no} 步的换行数不是 lines-1：模板往 <pre> 里喂了多余空白`);
    assert.doesNotMatch(raw, /\n[ \t]/, `第 ${st.no} 步的 <pre> 内容有行首缩进（pre 的空白全可见）`);
  }
  // clone 行的唯一来源是占位符（Task 2 的单一来源；copy.yml:168 的注释授权的正是这一处拼装）
  const first = preLines(preById(s, 'qs-code-1'))[0];
  assert.equal(first, `git clone ${copy.placeholders.github_url}.git`,
    'step 1 首行不是由 placeholders.github_url 现拼的 clone 命令');
  assert.equal((s.match(/git clone/g) || []).length, 1,
    '全页只许 step 1 那一处 git clone：别处再抄一份就是占位符之外的第二个来源');
});

test('T8 两色代码：# 开头的注释行走 .cmt、命令行走 .cmd，一行一块（不整块套一个 cmd）', () => {
  const s = html('index.html');
  const seen = { cmt: 0, cmd: 0 };
  for (const st of copy.quickstart.steps) {
    for (const g of spanPerLine(preById(s, `qs-code-${st.no}`), st.no)) {
      const wantCls = /^\s*#/.test(g.text) ? 'cmt' : 'cmd';
      assert.deepEqual(g.cls, [wantCls],
        `「${g.text.slice(0, 40)}」分到了 ${g.cls.join(' ')}，应为 ${wantCls}（main.css:168-169 的两色分工）`);
      seen[wantCls]++;
    }
  }
  // 整块套一个 <span class="cmd"> 的写法会把注释行也漆成命令蓝：两堆计数都能兜住它，
  // 但真正判死它的是上面逐行的「恰好一个 span」+ 逐行类名两条。
  assert.ok(seen.cmt > 0 && seen.cmd > 0,
    `段 7 必须同时出现 .cmt(${seen.cmt}) 与 .cmd(${seen.cmd})，单色就等于没做深色段的两色分工`);
});

test('T8 DOM 契约：每块 pre 配一枚 .copy-btn[data-copy]，data-label-done 来自 copy.labels（Task 10 依赖）', () => {
  const q = sectionById(html('index.html'), 'quickstart');
  const btns = [...q.matchAll(/<button\b[^>]*\bclass="([^"]*)"[^>]*>([\s\S]*?)<\/button>/g)]
    .filter((m) => m[1].trim().split(/\s+/).includes('copy-btn'));
  assert.equal(btns.length, copy.quickstart.steps.length, '复制按钮数必须等于代码块数');
  assert.deepEqual(btns.map((m) => (m[0].match(/data-copy="([^"]*)"/) || [])[1]),
    copy.quickstart.steps.map((st) => `qs-code-${st.no}`),
    'data-copy 必须逐块指向自己的 pre id，且按 DOM 序与 steps[] 同序——T10 只认这个配对键');
  for (const m of btns) {
    assert.equal(/data-label-done="([^"]*)"/.exec(m[0])[1], copy.labels.copy_done,
      'data-label-done 必须是 labels.copy_done：T10 点击后就把按钮文字换成它');
    assert.equal(/aria-label="([^"]*)"/.exec(m[0])[1], copy.quickstart.copy_hint,
      'copy_hint 在原型语言里是无障碍说明，必须挂 aria-label 而不是可见文字');
    assert.equal(unesc(m[2].trim()), copy.labels.copy_button, '按钮可见文案只能是 labels.copy_button');
  }
});

test('T8 模板门：段 7 由 C.quickstart.steps 迭代出，index.ejs 里不写死任何命令文本', () => {
  // 与 T5/T6/T7 的模板门同族：产物级判据抓不到「模板改回写死四步」——那种改法今天的产物照样全绿，
  // 但第五步一进 copy.yml 就不会出现。先剥 `<%# %>`：本段注释里就原样写着 manage.py 之类的字样。
  const idxSrc = readFileSync(new URL('../themes/syntime/layout/index.ejs', import.meta.url), 'utf8')
    .replace(/<%#[\s\S]*?%>/g, '');
  const sec = sectionById(idxSrc, 'quickstart');
  assert.ok(sec, 'themes/syntime/layout/index.ejs 里没有段 7 <section id="quickstart">');
  assert.equal([...sec.matchAll(/C\.quickstart\.steps\.forEach/g)].length, 1,
    '四步必须由一次 C.quickstart.steps.forEach 迭代出；写死四次就不再派生自 steps[]');
  assert.equal([...sec.matchAll(/\bid="qs-code-/g)].length, 1,
    '<pre> 的 id 只许模板里出现一次（出现四次说明有块不再跟着 steps[] 走）');
  for (const lit of ['manage.py', 'uv venv', 'celery -A', 'uv pip install'])
    assert.ok(!sec.includes(lit), `模板里写死了「${lit}」：命令文本的唯一来源是 copy.quickstart.steps[].code`);
  // 唯一允许的字面命令前缀 = clone 行，且必须与占位符拼在一起（copy.yml:168 的注释授权的正是这一处）
  assert.equal([...sec.matchAll(/git clone/g)].length, 1, 'git clone 字面量在段 7 模板只许出现在拼装那一处');
  assert.match(sec, /git clone[^<]*\$\{C\.placeholders\.github_url\}/,
    'step 1 首行必须是 `git clone ${C.placeholders.github_url}.git`：URL 只有一个来源（Task 2）');
  assert.doesNotMatch(sec, /<%-\s*st\.code|<%-\s*line\b/,
    '代码行必须走 `<%= %>` 转义：`<%- %>` 会让 <自行生成> 变成裸标签，R-1/R-2 的判据随之失明');
  assert.equal([...sec.matchAll(/C\.quickstart\.requirements\.split/g)].length, 1,
    '环境要求行只许按 · 切一次；两处切分就是「切了又整行再输一遍」的那类双处理');
});

test('T8 CSS 门：h3 内联徽章的对齐只有一条来源，且空转声明 position:static 不 ship', () => {
  // 裁定 8：CSS 只在有实测理由时加，加了就钉住它——对齐决定（vertical-align:middle）与
  // 「不 ship 死声明」两件事都得有判据，否则下一次目视走查会把它改回基线、或把 static 又塞回来。
  const css = readCss();
  const marker = css.indexOf('V1.1–V1.3 增补结构');
  assert.ok(marker > 0, '找不到增补段标记，转录区与追加区失去边界');
  assert.ok(!css.slice(0, marker).includes('.qs-card h3 .pill'),
    '.qs-card h3 .pill 是本站新结构（原型的 .qs-card 里没有徽章），只许出现在增补段');
  const mine = appendixRules(css.slice(marker)).filter((r) => !r.media
    && r.selectors.includes('.qs-card h3 .pill'));
  assert.equal(mine.length, 1,
    `.qs-card h3 .pill 的顶层规则必须恰好一条（现在 ${mine.length} 条）：对齐决定只能有一个来源；`
    + '按视口改值请写进 @media——媒体查询里的覆写本门允许（T11 的领地）');
  const decls = mine[0].decls.replace(/\s/g, '');
  for (const d of ['margin-left:var(--space-2)', 'vertical-align:middle'])
    assert.ok(decls.includes(d), `段 7 的徽章对齐丢了 ${d}（现 "${mine[0].decls.trim()}"）：`
      + '实测 24px 的 inline-flex pill 挂在 16px h3 基线上会下沉 4px');
  // 死声明：全站唯一给徽章绝对定位的规则是 `.feat-card>.pill.badge`（main.css:250），它在 .qs-card 里
  // 命不中——实测注入 `position:static` 后 h3 与徽章的 rect 逐值不变（task-8-report.md 对照 C 组）。
  // 只禁 static 这一种值：`.feat-card>.pill.badge` 自己的 position:absolute 是 T5 的活规则，不算空转。
  const dead = appendixRules(css.slice(marker))
    .filter((r) => /\.pill|\.badge/.test(r.selectors.join(','))
      && r.decls.replace(/\s/g, '').includes('position:static'));
  assert.equal(dead.length, 0,
    '增补段给 pill/badge 写了 position:static——本页没有任何规则把它们定位过，这是空转声明：'
    + dead.map((r) => r.selectors.join(',')).join(' | '));
});
