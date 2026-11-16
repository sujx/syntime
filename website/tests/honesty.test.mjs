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
  const tag = (s.match(/<img class="shot"[\s\S]*?>/) || [''])[0];
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

test('S6-1 foundation cards are all shipped and match the capability table', () => {
  assert.equal(copy.foundation.items.length, 4);
  for (const it of copy.foundation.items) assert.equal(it.badge, 'shipped');
  const s = html('index.html');
  const cardHtml = (s.match(/<section id="foundation"[\s\S]*?<\/section>/) || [''])[0];
  assert.ok(cardHtml, 'public/index.html 里没有 <section id="foundation">');
  assert.equal([...cardHtml.matchAll(/class="pill ok badge"/g)].length, 4);
});

test('pills row renders all 4 positioning pills', () => {
  const s = html('index.html');
  assert.equal(copy.pills.length, 4);
  for (const p of copy.pills) assert.ok(strip(s).includes(p), `missing pill: ${p}`);
  assert.doesNotMatch(s, /Docker 一键拉起/, 'V1.1 removed this pill (no image published)');
});

test('地基 2×2 在手机上塌成单列（.feat-grid-2 两条规则都在 APPENDIX）', () => {
  const css = readCss();
  const marker = css.indexOf('V1.1–V1.3 增补结构');
  const head = css.slice(0, marker), tail = css.slice(marker);
  assert.ok(!head.includes('.feat-grid-2'), '.feat-grid-2 是本站新 class，不得进转录区');
  assert.match(tail, /\.feat-grid-2\{grid-template-columns:repeat\(2,1fr\)\}/);
  const mq = (tail.match(/@media \(max-width:900px\)\{[\s\S]*?\}\s*\}/) || [''])[0];
  assert.match(mq, /\.feat-grid-2\{grid-template-columns:1fr\}/,
    '缺 ≤900 的单列覆写：附录里的 repeat(2,1fr) 会因源码顺序赢过转录区 .feat-grid{1fr}，手机上仍是两列');
});
