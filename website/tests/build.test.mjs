import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const yaml = require('js-yaml');
const copy = yaml.load(readFileSync(new URL('../source/_data/copy.yml', import.meta.url), 'utf8'));
const pub = (p) => new URL(`../public/${p}`, import.meta.url);
// T13 Step 2b 第 5 条（R25 尾、T4 遗留 ④）：裸读换 existsSync + 可执行提示，照 honesty.test.mjs
// 的 html() 先例。产物缺位时抛裸 ENOENT 会把本文件其余判据一起带走，看起来像"测试坏了"而不是"没构建"。
const html = (p) => {
  assert.ok(existsSync(pub(p)),
    `public/${p} missing — 先跑 "npx hexo clean && npx hexo generate"（或 npm run build），本文件的判据读的是构建产物`);
  return readFileSync(pub(p), 'utf8');
};

// 全局约束 13 的泛化（T13 Step 2b）：判据按**空白分隔的 class token** 认，token 在属性值里排第几位都算，
// 但少一个、换成 `pillx`/`hero-copy` 这种同前缀的仍算红。`\bpill\b` 式的词边界写法会命中 `pills-row`，
// `\bhero\b` 会命中 `hero-copy`——那是松，不是宽容。属性之间的次序本来就由 `[^>]*` 兜住。
const classAttrSrc = (...tokens) =>
  `class="${tokens.map((t) => `(?=(?:[^"]*\\s)?${String(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=[\\s"]))`).join('')}[^"]*"`;
const classHas = (...tokens) => new RegExp(classAttrSrc(...tokens));
const tagHas = (tag, ...tokens) => new RegExp(`<${tag}\\b[^>]*${classAttrSrc(...tokens)}`);

test('hexo generate produced index.html with theme shell', () => {
  assert.ok(existsSync(pub('index.html')), 'public/index.html missing — run npm run build');
  const s = html('index.html');
  assert.match(s, /<html lang="zh-CN">/);
  // T13 Step 2b 第 5 条：整串字面量 `href="/css/main.css"` 把 root=/ 钉死在判据里——
  // 同一份模板在 alt-root（root:/SynTime/）构建下产物是 `/SynTime/css/main.css`，门会假红。
  // 改成「以 / 开头（绝对路径 = url_for 的产物）+ 以该资源路径结尾」：root 换值不换形状。
  const asset = (attr, path) => new RegExp(`${attr}="(?:/[^"]*)?${path}"`);
  assert.match(s, asset('href', '/css/main\\.css'));
  assert.match(s, asset('src', '/js/main\\.js'));
  assert.match(s, /<link rel="icon" href="data:image\/svg\+xml/);
});

test('build emits every asset the pages reference', () => {
  // 只查 index.html 的话，丢了 hexo-generator-sitemap（F3 同族）或 css/js 拷贝失败都会全绿
  for (const a of ['css/main.css', 'js/main.js', 'sitemap.xml']) {
    assert.ok(existsSync(pub(a)), `public/${a} missing`);
  }
});

test('no unresolved EJS or undefined leakage', () => {
  const s = html('index.html');
  assert.doesNotMatch(s, /<%[=%-]/);
  assert.doesNotMatch(s, /\bundefined\b/);
  assert.doesNotMatch(s, /\[object Object\]/);
});

// ---------------------------------------------------------------------------
// T10 交互脚本 source/js/main.js：行数预算 + DOM 契约 + 失败路径的诚实纪律
// ---------------------------------------------------------------------------

// 控制者裁定 D-1：禁词判据扫的是**代码**不是散文 —— 先剥 `/* */` 与 `//` 注释再断言。
// 这不是新发明，是本仓既有约定：T7 的模板门先剥 `<%# %>`（honesty.test.mjs「T7 模板门」那条），
// T9 的说明里「注释里的中文不进判据」同族。不剥的话，brief 自己派发的注释
// `/* 横幅关闭：仅本次会话（§2 段 1），不写 localStorage */` 会把它自己的
// `doesNotMatch(/localStorage/)` 判红 —— brief 的散文与 brief 的门互杀（取证见 task-10-report.md）。
// 已知局限（写在这里而不是假装它不存在）：这把剥离器不是词法器。字符串里出现 `//`
// （例如 "https://x"）会被当成行注释起点，把该行余下的**真代码**吞掉 = 假通过。
// 今天 main.js 没有这种字符串，下面 `!js.includes('://')` 一条把这条路钉红：
// 要往脚本里引 URL，请先把它换成真的解析器，而不是默默放宽判据。
const jsSrc = () => readFileSync(new URL('../source/js/main.js', import.meta.url), 'utf8');
const jsCode = () => jsSrc().replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');

// F4（审查 Minor 4）判据要用：把每个 `.catch(` 的**支路文本**按括号深度切出来。
// 为什么不用一条正则了事：谎报有三型 `.catch(function () { done(btn); })`、`.catch(() => done(btn))`、
// `.catch(done)`，前缀形态各异，而「支路里不许出现 done」只跟配对有关。切出来的支路只含圆括号以内的原文，
// 注释已被 jsCode() 剥掉，所以注释里举例写 `.catch(() => done(btn))` 顶替不了判据（台账 R27(a) 同族）。
const catchClauses = (code) => {
  const out = [];
  for (const m of code.matchAll(/\.catch\s*\(/g)) {
    let depth = 1, i = m.index + m[0].length;
    while (i < code.length && depth > 0) {
      if (code[i] === '(') depth++;
      else if (code[i] === ')') depth--;
      i++;
    }
    assert.ok(depth === 0, '.catch 的圆括号没配上，支路无从切');
    out.push(code.slice(m.index + m[0].length, i - 1));
  }
  return out;
};

// F5（审查 Minor 5）判据要用：分段控件那一段 = 从取容器到 done() 助手之前。
// 按「段」而不是全文钉，是因为全文钉会被别的同名写法顶掉 —— 与 M9（`.in` 被 reduce 分支顶掉）、
// M21（`hidden` 被横幅那行顶掉）同一类漏洞。右界取 done() 是脚本自己的结构约定（复制段在分段段之后）。
const segSection = (code) => {
  const s = code.search(/getElementById\(\s*['"]seg-shot['"]\s*\)/);
  assert.ok(s >= 0, "分段控件必须由 document.getElementById('seg-shot') 取容器");
  const e = code.indexOf('function done', s);
  assert.ok(e > s, '取不到分段控件那一段的右界（done() 助手必须排在 seg 段之后）');
  return code.slice(s, e);
};

test('main.js is within the 100-line budget and wired to the DOM contract', () => {
  const js = jsSrc();
  const code = jsCode();
  assert.ok(js.split('\n').filter(Boolean).length <= 100, 'budget is design-doc 4 脚本 ≤100 行');
  assert.match(code, /IntersectionObserver/);
  assert.match(code, /data-shot/);
  assert.match(code, /prefers-reduced-motion/);
  assert.doesNotMatch(code, /厂商|已上线|开发中|二期/, 'no Chinese literals — copy.yml owns text');
  // 四个禁词只是例子，真正的纪律是「脚本不持文案」：注释剥干净之后，代码里不许出现任何中文字符串字面量。
  // 没有这一条时，`btn.textContent = '已复制'` 这种第二来源能绕过禁词表（实测见报告 M22 那条注）。
  assert.doesNotMatch(code, /["'`][^"'`\n]*[\u4e00-\u9fff]/,
    'main.js 的代码里不许出现中文字符串字面量：文案的唯一来源是 copy.yml（设计方案 §3）');
  assert.match(code, /dataset\.labelDone|getAttribute\(['"]data-label-done/);
  // 契约的另一半：脚本必须**写**这些状态，光读到属性不算数（.in 与 hidden 是 T7/T10 的运行契约）
  // 出现两次不是冗余：reduce 分支同步加一次，观察器回调里加一次。
  // 只查「有没有 add('in')」会被 reduce 分支顶掉 —— 实测变异（把观察器那句改成
  // classList.toggle('in', false)）在单查版本下全绿（task-10-report.md M9），故按次数钉。
  // 将来若真把两处收成一个 reveal() 助手，本条要连着改，不许悄悄降成 1。
  assert.ok((code.match(/classList\.add\(['"]in['"]\)/g) || []).length >= 2,
    '.io 的解锁态 .in 要由脚本在**两条分支各加一次**（main.css 的 `.io.in{opacity:1}`）；模板侧由 T7 明令不得预置 in');
  assert.match(code, /isIntersecting/, '观察器回调要按 isIntersecting 判定，不看这个就等于没判定');
  assert.match(code, /\.hidden\s*=/, '面板与横幅的显隐走 hidden，不是 display/visibility（T7 DOM 契约）');
  // 面板那一半单独钉：只查 `.hidden =` 会被横幅那句顶掉 —— 实测变异（把面板改成 classList.toggle('off')）
  // 在只查一条的版本下全绿（task-10-report.md M21）。
  assert.match(code, /hidden\s*=\s*[^;\n]*data-shot/,
    '段 6 面板的显隐必须由「hidden 对 data-shot」这一句决定，换成 class 开关就不在 T7 的 DOM 契约上');
  assert.match(code, /pre\.innerText/,
    '<pre> 的文本走 innerText：与原型 :846 的取法一致，读的是**排版结果**。'
    + '今天 Task 8 出的是一行一个 <span>，换行是 span 之间的字面文本节点，textContent 同样逐字符保留'
    + '（实测 task-10-report-fix1.md F1：四个 qs-code-* 两两逐字节相同）；也**不是**因为 textContent '
    + '现在会丢换行才钉的 —— 钉 innerText 钉的是它读**排版结果**：将来 <pre> 里出现 <br> 或块级子节点时'
    + '它照样拿得到换行，实测同一结构 innerText 取到 "a\\nb\\nc"、textContent 取到 "abc"（行数差 2）');
  // F5（审查 Minor 5）：分段控件的**状态写**必须钉住。只钉「读属性」的话，删掉
  // `x.setAttribute('aria-selected', on)` 那一行，index.ejs 段 6 服务端渲染的 aria-selected
  // 在切 tab 之后就开始说谎，而原判据 70 条全绿（与 M9 / M21 同族：判读不判写）。
  const seg = segSection(code);
  assert.ok((seg.match(/classList\.toggle\(\s*['"]on['"]\s*,/g) || []).length >= 1,
    "seg 段必须写 classList.toggle('on', <第二参>) 的双参形态：只 add 不减或单参 toggle 都不会把上一个选中项落回去，两个 tab 能同时亮");
  assert.ok((seg.match(/setAttribute\(\s*['"]aria-selected['"]\s*,/g) || []).length >= 1,
    "seg 段必须写 setAttribute('aria-selected', …)：role=tablist 的选中态是 T7 的 DOM 契约，不跟着面板一起改就是给 AT 说谎");
  assert.ok(!js.includes('://'),
    'main.js 里出现 :// —— 上面的行注释剥离器会把字符串里的 // 当注释起点、吞掉同行真代码（假通过）；'
    + '先把它换成真词法器再引 URL');
});

test('T10 失败路径不谎报成功：复制失败不进 done，sessionStorage 抛错就留着横幅', () => {
  const code = jsCode();
  // brief Step 3 的诚实纪律：clipboard 拒绝 / execCommand 抛错时**不进** done()。
  // F4（审查 Minor 4）把上一行的判据**收窄**：原版禁一切 `.catch(`，连唯一正确的修法一起禁了 ——
  // writeText 会因权限或焦点丢失 reject，没有拒绝支路时浏览器往控制台打 Uncaught (in promise)
  // DOMException，那既不是静默也不是谎报，是第三种噪声（RED 证据：加了空 .catch 的 main.js 被原版判红）。
  // 收窄后的判据只禁说谎那一型：**支路里出现 done**。三条变异各证一型（function 体 / 箭头简写 / 直接传函数），
  // 其中 `.catch(() => done(btn))` 只有本条抓得到，下一条 `catch…{ done( }` 的 `\{` 匹配不上它。
  for (const clause of catchClauses(code)) {
    assert.ok(!/\bdone\b/.test(clause),
      '.catch 的支路里不许出现 done：复制没成却报已复制（brief Step 3 注 2）。现在这一支是 '
      + JSON.stringify(clause.trim().slice(0, 120)));
  }
  assert.doesNotMatch(code, /catch\s*\([^)]*\)\s*\{[^}]*\bdone\(/, 'catch 分支里不得调用 done()');
  // 隐私模式下 sessionStorage 会抛：读必须整段（含 banner.hidden=true）在 try 内，
  // 抛错的后果只能是「横幅还在」，而不是「横幅已关闭」。
  assert.match(code, /try\s*\{\s*if\s*\(sessionStorage\.getItem/,
    'sessionStorage.getItem 与它的 banner.hidden 赋值必须同在 try 内');
  assert.match(code, /try\s*\{\s*sessionStorage\.setItem/, 'sessionStorage.setItem 必须在 try 内');
  assert.match(code, /window\.isSecureContext/,
    'navigator.clipboard 只在安全上下文里用：非 https / 非 localhost 的 origin 上它是 undefined，'
    + '不判这一条就永远走不到 textarea 兜底');
  assert.match(code, /document\.execCommand\(['"]copy['"]\)/, '非安全上下文要有 textarea + execCommand 兜底');
});

// ---------------------------------------------------------------------------
// T11 响应式 + 可访问性 + SEO 收口
// ---------------------------------------------------------------------------
// brief Step 1 的三条 test 落在这里（裁定 R-5：每条自己读产物，本文件的模块级没有 `s`）；
// 三个必决项（R29 钉底 / R38 段 7 溢出 / R41 命中区）、T4 轮 2 的判据漏洞、台账 C4 也在这里收。
//
// CSS 扫描器的纪律（brief Interfaces 第 2 条 = 台账 R27(a)）：**按花括号深度扫之前先剥注释**。
// main.css 的理由注释里原样写着 `.nav{top:12px}`、`.alpha[hidden]{display:none}`、
// `.shot-frame{background:#fff}` 这类片段，不剥就是拿注释顶替真规则，三种后果都真踩过：
// 幻影块（假红）、块被游离 `}` 截断（假红）、注释里两处不配对相互抵消把媒体查询外的规则并进
// "块体"（假通过）。下面 cssRules() 是本文件的唯一扫描器，@media 里的规则单独打标记，
// 「顶层唯一来源」类判据一律先 filter 掉媒体覆写——与 honesty.test.mjs 的 appendixRules() 同族
// （两个 test 文件各自独立跑，不跨文件 import，这是本仓既有约定）。
const cssSrc = () => readFileSync(new URL('../source/css/main.css', import.meta.url), 'utf8');
const APPENDIX_MARK = 'V1.1–V1.3 增补结构';
const noCssComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const escRe = (x) => String(x).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const appendixText = () => {
  const css = cssSrc();
  const marker = css.indexOf(APPENDIX_MARK);
  assert.ok(marker > 0, `main.css 里找不到增补段标记「${APPENDIX_MARK}」，转录区与追加区失去边界`);
  return { css, marker, appendix: css.slice(marker) };
};

function cssRules(src) {
  const text = noCssComments(src).replace(/^[^{}]*\*\//, '');
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
      assert.ok(depth === 0, 'main.css 里有没配上的花括号，规则无从分堆');
      const prelude = chunk.slice(i, open).trim().replace(/\s+/g, ' ');
      const body = chunk.slice(open + 1, j - 1);
      if (/^@(media|supports)\b/.test(prelude)) walk(body, prelude);
      else if (prelude && !prelude.startsWith('@')) {
        out.push({ selectors: prelude.split(',').map((x) => x.trim()), decls: body, media });
      }
      i = j;
    }
  };
  walk(text, null);
  return out;
}
const topRules = () => cssRules(appendixText().appendix).filter((r) => !r.media);
const declares = (r, prop) => new RegExp(`(?:^|[;\\s])${prop}\\s*:`, 'i').test(r.decls.replace(/\s+/g, ' '));
const declOf = (r, prop) => (r.decls.replace(/\s+/g, ' ').match(new RegExp(`(?:^|[;\\s])${prop}\\s*:\\s*([^;]+)`)) || [])[1];
const withProp = (rules, sel, prop) => rules.filter((r) => r.selectors.includes(sel) && declares(r, prop));
// var(--space-*) 现量成 px（判据拒绝猜单位，同 honesty.test.mjs 首屏几何门的 varPx 思路）
const tokenPx = (name) => {
  const m = noCssComments(cssSrc()).match(new RegExp(`${name}:\\s*([\\d.]+)px`));
  assert.ok(m, `Token ${name} 在 :root 里量不出 px 值`);
  return Number(m[1]);
};
const pxOnly = (spec, what) => {
  const t = String(spec).trim();
  if (t === '0') return 0;          // CSS 允许无单位零长度（`padding:0 var(--space-2)` 就是这个形状）
  const v = t.match(/^var\((--[\w-]+)\)$/) ? tokenPx(RegExp.$1) : (() => {
    const m = t.match(/^([\d.]+)px$/);
    assert.ok(m, `${what}「${t}」不是 px 字面量也不是单个 var()——判据拒绝猜单位`);
    return Number(m[1]);
  })();
  return v;
};
// line-height 的两种写法都得认：`24px`（绝对）与 `1`（无单位倍数，× 本元素的 font-size）。
// 只认前者会把「line-height:1 命中 18px」这种真违规报成"判据算不动"，红消息就成了工具问题而非缺陷定位。
const lineHpx = (spec, fontPx, what) => {
  const t = String(spec).trim();
  if (/^var\(--[\w-]+\)$|^[\d.]+px$/.test(t)) return pxOnly(t, what);
  const m = t.match(/^([\d.]+)$/);
  assert.ok(m, `${what}「${t}」既不是 px / var()，也不是无单位倍数——判据拒绝猜单位`);
  return Number(m[1]) * fontPx;
};

// IntersectionObserver 的第二个实参（选项对象）：从 `new IntersectionObserver(` 起按**圆括号**深度
// 取到配对右括号，再在参数文本里按**花括号**深度取顶层 {}。为什么不用一条正则：回调函数体里
// 就有 `{}`，`/\{[^}]*\}/` 会先撞上回调体（假通过：threshold 写在别处也当量到了）。
function ioOptions(code) {
  const at = code.indexOf('IntersectionObserver(');
  assert.ok(at >= 0, 'main.js 里找不到 IntersectionObserver( 调用');
  let depth = 0, i = at + 'IntersectionObserver'.length, end = -1;
  for (; i < code.length; i++) {
    if (code[i] === '(') depth++;
    else if (code[i] === ')') { depth--; if (depth === 0) { end = i; break; } }
  }
  assert.ok(end > 0, 'IntersectionObserver( 的圆括号没配上，选项对象无从切');
  const args = code.slice(at + 'IntersectionObserver'.length + 1, end);
  const objs = [];
  for (let k = 0; k < args.length; k++) {
    if (args[k] !== '{') continue;
    let d = 1, m = k + 1;
    while (m < args.length && d > 0) {
      if (args[m] === '{') d++;
      else if (args[m] === '}') d--;
      m++;
    }
    objs.push(args.slice(k + 1, m - 1));
    k = m - 1;
  }
  // 回调函数体也是 {}：选项对象是**带 threshold/rootMargin 关键字**的那一个（顶层 {} 只有两个：回调 + 选项）
  return objs.find((o) => /threshold|rootMargin/.test(o)) || null;
}

test('T11 断点门：设计方案 §4 的四条响应要求逐条在位，且不新增 1439 档（裁定 R-1）', () => {
  const s = html('index.html');
  const rules = cssRules(cssSrc());
  const at = (q) => rules.filter((r) => r.media === `@media ${q}`);
  for (const q of ['(max-width:1279px)', '(max-width:900px)', '(min-width:2200px)']) {
    assert.ok(at(q).length > 0, `@media ${q} 整档不见了——T3 转录的断点体系（设计方案 §4）少一档`);
  }
  // 裁定 R-1：Step 1 原本要 `/@media \(max-width:1439px\)/` **存在**，控制者更正为**不许存在**——
  // design.md §6.1 的 1439 行全是应用内物件，营销页一个都没有，而它想补的
  // `.feat-grid{repeat(2,1fr)}` 已逐字在转录区 ≤1279 块里，再写一遍就是第二个来源。
  assert.equal(rules.filter((r) => r.media && /max-width:\s*1439px/.test(r.media)).length, 0,
    '不许新增 @media (max-width:1439px)：本站唯一的活动式响应规格是设计方案 §4，它只点名 ≤1279');

  // ① Hero 转单列（文上图下）
  const heroWrap = at('(max-width:1279px)').find((r) => r.selectors.includes('.hero .wrap'));
  assert.ok(heroWrap && /grid-template-columns:\s*1fr\b/.test(heroWrap.decls),
    '§4 要求①「Hero 转单列」不在 ≤1279 块里');
  assert.ok(s.search(classHas('hero-copy')) >= 0 && s.search(classHas('hero-copy')) < s.search(classHas('hero-visual')),
    '单列后「文上图下」靠 DOM 顺序：.hero-copy 必须排在 .hero-visual 之前（按 class token 认，不认属性值内的次序）');
  // ② 功能卡 3→2→1（三档各一个来源，谁也不许多一份）
  const gridSrc = (mediaQuery) => withProp(
    mediaQuery === null ? rules.filter((r) => !r.media) : at(mediaQuery), '.feat-grid', 'grid-template-columns');
  assert.equal(gridSrc(null).length, 1, '桌面 .feat-grid 列数只能有转录那一条来源');
  assert.match(declOf(gridSrc(null)[0], 'grid-template-columns'), /repeat\(3,\s*1fr\)/);
  assert.equal(gridSrc('(max-width:1279px)').length, 1, '≤1279 的 .feat-grid 降 2 列只能一条来源');
  assert.match(declOf(gridSrc('(max-width:1279px)')[0], 'grid-template-columns'), /repeat\(2,\s*1fr\)/);
  assert.match(declOf(gridSrc('(max-width:900px)')[0], 'grid-template-columns'), /^1fr$/);
  // ③ 导航锚点收起（≤1279）
  const links = at('(max-width:1279px)').find((r) => r.selectors.includes('.nav-links'));
  assert.ok(links && /display:\s*none/.test(links.decls), '§4 要求③「导航锚点收起」不在 ≤1279 块里');
  // ④ 移动端可读兜底：段 7 单列 + 页脚/导航日志收起；`.h1` 不许被覆写（裁定 R-2 已上交用户）
  const qsGrid = at('(max-width:900px)').find((r) => r.selectors.includes('.qs-grid'));
  assert.ok(qsGrid && /grid-template-columns:\s*1fr\b/.test(qsGrid.decls), '§4 要求④：≤900 段 7 必须塌单列');
  const h1Font = rules.filter((r) => r.selectors.includes('.h1') && declares(r, 'font-size'));
  assert.equal(h1Font.length, 1,
    '.h1 的字号只能有转录区那一条 clamp（裁定 R-2：设计方案 §1 自己的三个数互不相同，改首屏字号属视觉基准变更，'
    + '已上交用户在 T13 拍板；本轮加任何 .h1 覆写都是替用户做决定）');
  assert.match(declOf(h1Font[0], 'font-size'), /clamp\(34px/,
    '转录的 .h1 clamp 下限（34px）必须原样在位——它是本轮唯一不动的视觉基准之一');
  // 分类器自检：媒体覆写不许混进顶层（否则上面三条「唯一来源」在 T11 自己加断点时就假红）
  const synth = cssRules('.feat-grid{grid-template-columns:repeat(3,1fr)}'
    + '@media (max-width:1279px){.feat-grid{grid-template-columns:repeat(2,1fr)}}'
    + '/* .feat-grid{grid-template-columns:1fr} */');
  assert.equal(synth.filter((r) => !r.media && r.selectors.includes('.feat-grid')).length, 1,
    'cssRules 把 @media 里的覆写算进了顶层来源：断点判据一加分档就假红');
  assert.equal(synth.filter((r) => r.media).length, 1, 'cssRules 没把 @media 里的规则打上媒体标记');
  assert.equal(synth.filter((r) => r.decls.includes('grid-template-columns') && r.selectors.length !== 1).length, 0,
    'CSS 注释被当成了规则（台账 R27(a) 同族）：上面合成串的注释里就有一条 .feat-grid');
});

test('T11 a11y 门：地标、五张截图的 alt 与固有尺寸、reduced-motion、focus-visible（裁定 R-6：今天已绿）', () => {
  const s = html('index.html');
  assert.match(s, /<header[\s\S]*?<nav[\s\S]*?<\/nav>[\s\S]*?<\/header>/);
  assert.match(s, /<main/);
  assert.match(s, /<footer/);
  const imgs = [...s.matchAll(/<img\b[^>]*>/g)];
  assert.ok(imgs.length >= 5, `产物里只有 ${imgs.length} 张 <img>，少于 5 张说明有截图掉了`);
  for (const i of imgs) {
    assert.match(i[0], /alt="[^"]{4,}"/, '每张截图都要有真 alt 文案（设计方案 §4 可访问性）');
    assert.match(i[0], /width="\d+"/, '缺 width 会在图片入场时抖动布局');
    assert.match(i[0], /height="\d+"/, '缺 height 同上');
  }
  const css = cssSrc();
  assert.match(css, /@media \(prefers-reduced-motion:reduce\)/, 'reduced-motion 分支不在（设计方案 §4）');
  assert.match(css, /:focus-visible/, '键盘焦点光环不在（设计方案 §4：原型同款）');
});

test('T11 跳锚链接：Tab 第一击落进正文，未聚焦不占版面，id 契约交给 T12（裁定 R-4）', () => {
  const s = html('index.html');
  // id 就定 main：T12 的 page.ejs / post.ejs 沿用同一个 id，不许另起
  assert.match(s, /<main\b[^>]*\bid="main"/, '产物里没有 <main id="main">：skip link 的目标缺失');
  assert.equal((s.match(/\bid="main"/g) || []).length, 1, 'id="main" 必须全站唯一');
  const mainAt = s.search(/<main\b/);
  const before = s.slice(0, mainAt);
  const focusables = [...before.matchAll(/<(a|button|input|select|textarea)\b([^>]*)>/g)];
  assert.ok(focusables.length >= 1, '<main> 之前没有任何可聚焦元素——skip link 没渲染出来');
  assert.equal(focusables[0][1].toLowerCase(), 'a',
    '<main> 之前第一个可聚焦元素必须是 skip <a>，现在轮到 ' + focusables[0][1].toLowerCase()
    + '：Tab 第一击会把焦点交给横幅关闭按钮或导航，读屏用户跳不进正文');
  assert.match(focusables[0][2], /\bhref="#main"/, 'skip <a> 的 href 必须指向 #main（与上面 id="main" 配对）');
  assert.ok(s.search(classHas('skip')) >= 0 && s.search(classHas('skip')) < s.search(classHas('alpha')),
    'skip <a> 必须排在 .alpha 之前：它是文档里第一个 Tab 停靠点，排在横幅之后就晚了');

  // 渲染级：文案来自 copy.yml（约束 1：模板不写第二个中文来源）
  const lay = readFileSync(new URL('../themes/syntime/layout/layout.ejs', import.meta.url), 'utf8');
  const skipTag = [...lay.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/g)]
    .find((m) => classHas('skip').test(m[1]));
  assert.ok(skipTag, 'layout.ejs 里没有 class 含 skip token 的 <a>');
  assert.match(skipTag[2], new RegExp(`<%=\\s*C\\.labels\\.skip_link\\s*%>`),
    'skip 链接的文字必须由 C.labels.skip_link 出（写死中文就是第二个文案来源，且读屏名与判据脱钩）');
  assert.equal(typeof copy.labels.skip_link, 'string', 'copy.yml 缺 labels.skip_link');
  assert.ok(copy.labels.skip_link.trim().length >= 2, 'labels.skip_link 得是能念的短语');
  assert.ok(s.includes(`>${copy.labels.skip_link}</a>`),
    `产物里 skip 链接的文字必须逐字等于 labels.skip_link「${copy.labels.skip_link}」`);

  // CSS 级：不可见只能靠 transform / clip，不能靠 display 或 visibility——后两者把它从 Tab 顺序里删掉，
  // 「Tab 第一击可见」就永久失效（静态判据抓不到，只有这条写死）。
  const rules = cssRules(cssSrc());
  const skipRules = rules.filter((r) => r.selectors.some((x) => /^\.skip(:\w[\w-]*)?$/.test(x)));
  assert.ok(skipRules.length >= 1, 'main.css 里没有 .skip 规则：链接会常驻首屏，压掉横幅让位带');
  const base = skipRules.find((r) => r.selectors.includes('.skip'));
  assert.ok(base, '必须有裸 `.skip` 一条（聚焦态另算）');
  assert.equal(declares(base, 'display'), false, '.skip 不许写 display——display:none 把它从 Tab 顺序里删了');
  assert.doesNotMatch(base.decls, /visibility\s*:\s*hidden/, '.skip 不许 visibility:hidden，同样掉出 Tab 顺序');
  assert.match(base.decls.replace(/\s+/g, ' '), /position:\s*(fixed|absolute)/,
    '.skip 必须脱出文档流（fixed/absolute），否则它给首屏加高度，§6-5 首屏几何门被顶掉');
  assert.ok(/translate[Yy]?\(/.test(base.decls.replace(/\s+/g, ' ')) || /clip(?:-path)?:/.test(base.decls),
    '.skip 未聚焦时必须靠 transform/clip 藏起来');
  const unfurl = skipRules.find((r) => /:focus/.test(r.selectors.join(',')));
  assert.ok(unfurl, '缺 .skip:focus 展开规则：藏起来却不展开，Tab 到它就等于没做 skip link');
  assert.match(unfurl.decls.replace(/\s+/g, ' '), /transform:\s*none/, '.skip:focus 必须把 transform 收回来');
});

test('T11 SEO 门：canonical 与 og:url 同推导、og:image 指向真实文件（裁定 R-3 / R-7）', () => {
  const s = html('index.html');
  const attr = (re) => (s.match(re) || [])[1];
  const canon = attr(/<link rel="canonical" href="([^"]*)"/);
  assert.ok(canon !== undefined, '产物里没有 <link rel="canonical">');
  // 裁定 R-3 的实测点 ①：home。brief Step 4 的 `config.url + url_for(page.path)` 在 home 渲染成
  // `https://syntime.cn/index.html`，与 Step 1 期望的逐字 `href="https://syntime.cn/">` 永不会匹配。
  assert.equal(canon, 'https://syntime.cn/',
    `home 的 canonical 实到「${canon}」，应为 config.url 加斜杠且剥掉 index.html 尾缀`);
  const ogu = attr(/<meta property="og:url" content="([^"]*)"/);
  assert.equal(ogu, canon, `og:url「${ogu}」必须与 canonical 走同一推导，否则分享卡片与规范链接各说各话`);
  // 裁定 R-3 的实测点 ②（断言而非修复）：canonical 属"同一页面的规范地址"，与 root 无关。
  // page.permalink = config.url + '/' + path **不含 root**，而 url_for() 会把 root 前置——
  // alt-root（root: /SynTime/）构建下用后者就会长出 /SynTime/ 的 canonical（取证见报告）。
  assert.doesNotMatch(`${canon} ${ogu}`, /\/SynTime\//,
    'canonical / og:url 里出现了 /SynTime/：推导混进了 url_for(root)。alt-root 只改托管路径，不改页面身份');
  const headSrc = readFileSync(new URL('../themes/syntime/layout/partial/head.ejs', import.meta.url), 'utf8');
  assert.match(headSrc, /page\.permalink/, 'canonical 必须由 page.permalink 推导（绝对 URL、不含 root）');
  assert.match(headSrc, /\/index\\\.html\$/, '必须剥掉 index.html 尾缀（否则 home 的 canonical 带 /index.html）');
  assert.doesNotMatch(headSrc, /url_for\(page\.path\)/,
    'canonical/og:url 不许退回 `config.url + url_for(page.path)`：那条在 home 渲染出 /index.html，'
    + '且在 alt-root 构建下把 root 拼进 canonical（裁定 R-3 要断言的正是它）');
  assert.match(s, /<meta name="description" content=".+"/);
  assert.ok(s.includes(`<meta name="description" content="${copy.meta.description}">`),
    'description 必须逐字等于 copy.meta.description（文案单一来源）');
  assert.match(s, /<meta property="og:locale" content="zh_CN">/, '缺 og:locale（设计方案 §4 SEO）');
  const cfgTitle = (readFileSync(new URL('../_config.yml', import.meta.url), 'utf8')
    .match(/^title:[ \t]*(.+)$/m) || [])[1];
  assert.ok(cfgTitle, '_config.yml 里量不到 title，og:site_name 无从比对');
  assert.ok(s.includes(`<meta property="og:site_name" content="${cfgTitle.trim()}">`),
    `og:site_name 必须等于 _config.yml 的 title「${cfgTitle.trim()}」`);
  const ogimg = attr(/<meta property="og:image" content="([^"]*)"/);
  assert.equal(ogimg, 'https://syntime.cn/images/og-image.png', 'og:image 的路径与 copy.meta.og_image 脱钩了');
  // 裁定 R-7：只比字符串的话，图丢了照样全绿（本文件既有的资产存在门同族）
  assert.ok(existsSync(pub('images/og-image.png')),
    'public/images/og-image.png 不在——og:image 指向一个不存在的文件（抓取端表现为无图卡片）');
});

test('T11 模板转义门：url_for 的输出一律走 <%=%>，产物路径逐字节不变（brief Interfaces）', () => {
  const s = html('index.html');
  for (const f of ['../themes/syntime/layout/layout.ejs', '../themes/syntime/layout/partial/head.ejs',
    '../themes/syntime/layout/page.ejs', '../themes/syntime/layout/post.ejs']) {
    const src = readFileSync(new URL(f, import.meta.url), 'utf8');
    assert.doesNotMatch(src, /<%-\s*url_for/,
      `${f.split('/').pop()} 里有未转义的 url_for 输出（<%- 形态）：url_for 返回的是纯路径字符串，`
      + '它不需要原始 HTML 权限，写成 <%- 就是给"路径里出现引号"留门');
  }
  // 转义形态改了，产物必须逐字节等价（改了输出却把路径改坏 = 当场可见的红）
  assert.match(s, /<link rel="stylesheet" href="\/css\/main\.css">/);
  assert.match(s, /<script src="\/js\/main\.js"><\/script>/);
  assert.match(s, /<meta property="og:image" content="https:\/\/syntime\.cn\/images\/og-image\.png">/);
});

test('T11 chrome 门补漏：装配顺序 nav → body → footer → <script>（T4 轮 2 漏洞第 2 条）', () => {
  const lay = readFileSync(new URL('../themes/syntime/layout/layout.ejs', import.meta.url), 'utf8');
  const at = (needle) => lay.indexOf(needle);
  assert.ok(at("partial('partial/nav')") >= 0 && at('<%- body %>') >= 0 && at("partial('partial/footer')") >= 0,
    'layout.ejs 的三件套装配点不见了');
  assert.ok(at("partial('partial/footer')") < at('<script'),
    '页脚必须排在 <script src="/js/main.js"> 之前：脚本在解析时就要拿 DOM 节点，'
    + '把 <script> 提到页脚之前会拿到 null 而静默少绑事件（本门原先只钉 nav/body/footer 的相对顺序，没管脚本）');
});

test('T11 对比度门：深色段三行正文各有且只有一条 .85 覆写，且打在容器不在 span（Step 5 + 裁定 R-8）', () => {
  const { css, marker } = appendixText();
  const rules = cssRules(css.slice(marker));
  const top = rules.filter((r) => !r.media);
  for (const sel of ['.dark-sec .lead', '.dark-sec .qs-card p', '.dark-sec .qs-env']) {
    const hits = withProp(top, sel, 'color');
    assert.equal(hits.length, 1,
      `顶层 ${sel} 的 color 必须恰好一条覆写来源（现在 ${hits.length} 条${hits.length ? `：${hits.map((r) => r.selectors.join(','))}` : ''}）`
      + '；0 条 = §4 的 .85 下限没了，>1 条 = 第二个来源');
    const v = String(declOf(hits[0], 'color')).trim();
    const m = v.match(/^rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*(\.\d+|1|0(?:\.\d+)?)\s*\)$/);
    assert.ok(m, `${sel} 的覆写必须写成 rgba(255,255,255,α)，现在「${v}」`);
    assert.ok(Number(m[1]) >= 0.85, `设计方案 §4「深色段正文 rgba(255,255,255,.85)+」：现在 α=${m[1]}`);
  }
  // 裁定 R-8：实测 `.qs-env span` 自己不带 color，色是从 `.qs-env` 继承的 → 覆写打在容器上才是单一来源
  assert.equal(rules.filter((r) => r.selectors.some((x) => /\.qs-env span\b/.test(x)) && declares(r, 'color')).length, 0,
    '给 `.qs-env span` 另立一条 color 就是第二个来源（继承链已在 .qs-env 上，裁定 R-8）');
  // 让位记录：转录基准不动（§4 覆盖 §1 属有记录的让位，登记在 T13 Step 6 的 CHANGELOG）
  const trans = css.slice(0, marker);
  assert.ok(trans.includes('.dark-sec .lead{color:rgba(255,255,255,.66)}'),
    '转录区的 .66 必须原样在位——覆写是"追加在后面的更高优先级来源"，不是回改基准');
  assert.ok(trans.includes('.qs-card p{font-size:13px;color:rgba(255,255,255,.78)'),
    '转录区的 .78 同上');
});

test('T11 必决① R29：badge-note 钉底取 flex 方案，卡内末块变卡内底部', () => {
  const top = topRules();
  const card = top.filter((r) => r.selectors.includes('.feat-card'));
  assert.ok(card.some((r) => /display\s*:\s*flex/.test(r.decls.replace(/\s+/g, ' ')))
    && card.some((r) => /flex-direction\s*:\s*column/.test(r.decls.replace(/\s+/g, ' '))),
    '.feat-card 必须是 flex 列：设计稿 §2 段 5 / §3.2 表头写的是「卡内底部 12px badge_note」，'
    + '而块级布局下 .badge-note 只能是「卡内末块」——六卡等高由 .feat-grid 行拉伸产生，'
    + '正文短的三张卡 note 下方留白 71.88px（实测见报告）。选项 ② 要改仓库外的设计稿，不是一轮改动');
  const note = withProp(top, '.badge-note', 'margin-top');
  assert.equal(note.length, 1, '.badge-note 的 margin-top 只能一条来源');
  assert.equal(String(declOf(note[0], 'margin-top')).trim(), 'auto',
    '钉底靠 margin-top:auto：留 var(--space-3) 是"末块"写法（R29 的两条规则之一）');
  // auto 在内容正好填满时给 0，视觉下限必须由 .badge-note 自己的 padding-top 与上边框提供
  assert.ok(declares(note[0], 'padding-top'), 'margin-top:auto 之后，12px 下限只能靠 padding-top');
  assert.equal(pxOnly(declOf(note[0], 'padding-top'), '.badge-note 的 padding-top'), tokenPx('--space-3'));
});

test('T11 必决② R38：段 7 单列被 min-content 撑破，落 .qs-card{min-width:0}', () => {
  const top = topRules();
  const q = withProp(top, '.qs-card', 'min-width');
  assert.equal(q.length, 1,
    `.qs-card 的 min-width 顶层来源必须恰好一条（现在 ${q.length} 条）：`
    + '390px 档 1fr 列被 clone 行的 min-content 撑到 436.52px，而 .dark-sec{overflow:hidden} 把溢出静默藏掉');
  assert.equal(String(declOf(q[0], 'min-width')).trim(), '0',
    '.qs-card 的 min-width 必须是 0：grid 项的自动最小尺寸取 min-content，不收到 0 就永远撑破单列');
  // 转录区两条 1fr 声明不许动（逐字节基线由 tokens.test.mjs 把守，minmax(0,1fr) 不是选项）
  const { css, marker } = appendixText();
  assert.ok(css.slice(0, marker).includes('.qs-grid{display:grid;grid-template-columns:repeat(3,1fr)'),
    '转录区的 .qs-grid repeat(3,1fr) 不许改成 minmax(0,1fr)：那是破坏照抄契约（brief R38 已排除）');
});

test('T11 必决③ R41：.alpha-x 命中区纵向 ≥24px（WCAG 2.5.8 最小目标尺寸）', () => {
  const top = topRules();
  const xs = top.filter((r) => r.selectors.includes('.alpha-x'));
  assert.ok(xs.length >= 1, '找不到顶层 .alpha-x 规则');
  const one = (prop) => {
    const r = xs.find((x) => declares(x, prop));
    return r === undefined ? 0 : pxOnly(declOf(r, prop), `.alpha-x 的 ${prop}`);
  };
  const fontR = xs.find((x) => declares(x, 'font-size'));
  assert.ok(fontR, '.alpha-x 必须有 font-size：无单位 line-height 要靠它折算');
  const fontPx = pxOnly(declOf(fontR, 'font-size'), '.alpha-x 的 font-size');
  const lhR = xs.find((x) => declares(x, 'line-height'));
  const lineH = lhR === undefined ? 0 : lineHpx(declOf(lhR, 'line-height'), fontPx, '.alpha-x 的 line-height');
  const minH = one('min-height');
  const height = one('height');
  const padV = (() => {
    const p = xs.find((x) => declares(x, 'padding'));
    const t = xs.find((x) => declares(x, 'padding-top'));
    const b = xs.find((x) => declares(x, 'padding-bottom'));
    if (t || b) return one('padding-top') + one('padding-bottom');
    if (!p) return 0;
    const toks = String(declOf(p, 'padding')).trim().split(/\s+/);
    const first = pxOnly(toks[0], '.alpha-x 的 padding 首项');
    return toks.length >= 4 ? first + pxOnly(toks[2], '.alpha-x 的 padding 第三项') : first * 2;
  })();
  const box = Math.max(lineH, minH, height) + padV;
  assert.ok(box >= 24,
    `.alpha-x 的纵向命中盒 ${box}px 低于 WCAG 2.5.8 的 24px（line-height ${lineH} + 上下留白 ${padV}）：`
    + 'T10 brief  prescribed 的 font-size:18px/line-height:1 落出 34×18，属 plan-mandated 缺陷，本任务是收口点');
  assert.ok(!/font-size\s*:\s*2[5-9]px|font-size\s*:\s*[3-9]\dpx/.test(xs.map((r) => r.decls).join(';')),
    '命中区要靠留白而不是把 × 字形放大——字号一放大就是第二个视觉来源（设计方案 §2 段 1 的横幅版式）');
});

test('T11 .alpha 的「文字→徽章」间距收敛到单一来源（brief 附带项）', () => {
  const top = topRules();
  const gapSrc = [];
  if (top.some((r) => r.selectors.includes('.alpha .pill') && declares(r, 'margin-left'))) gapSrc.push('.alpha .pill 的 margin-left');
  const body = top.find((r) => r.selectors.includes('.alpha-body'));
  assert.ok(body, '找不到 .alpha-body 规则（T10 的结构判据也挂在它身上）');
  if (declares(body, 'column-gap')) gapSrc.push('.alpha-body 的 column-gap');
  if (declares(body, 'gap')) gapSrc.push('.alpha-body 的 gap');
  assert.equal(gapSrc.length, 1,
    `「文字→徽章」的水平间距现在有 ${gapSrc.length} 个来源（${gapSrc.join(' + ')}）：`
    + '实测 16px 是 gap:var(--space-2)=8 与 margin-left:var(--space-2)=8 叠加出来的，'
    + '两个来源任改其一都会让它跳，且窄屏徽章单独成行时被 margin-left 顶得偏离中线 4px');
  assert.ok(declares(body, 'row-gap'), '换行方向的行距要单独写（column-gap 收成 16px 后不能把行距一起带上）');
  assert.equal(pxOnly(declOf(body, 'column-gap'), '.alpha-body 的 column-gap'), 16,
    '收敛后桌面「文字→徽章」必须仍是 16px（与收敛前逐值相同，只是只剩一个来源）');
  assert.equal(pxOnly(declOf(body, 'row-gap'), '.alpha-body 的 row-gap'), tokenPx('--space-2'));
});

test('T11 入场阈值门：18px 高的 .shot-cap 贴边也要入场（brief 附带项）', () => {
  const code = jsCode();
  const opts = ioOptions(code);
  assert.ok(opts, 'IntersectionObserver 的选项对象取不到：判据无从读 threshold');
  const m = opts.replace(/\s+/g, ' ').match(/threshold\s*:\s*([\d.]+)/);
  if (m) assert.equal(Number(m[1]), 0,
    `.io 的 threshold 必须是 0（或不写）：实测 18px 高的 .shot-cap 在视口边线上方只差 0.37px 时，`
    + `0.12 要求 2.16px 可见，图注就永久停在 opacity:0（task-10-report.md §6.3 与本任务 CDP 复现一致）`);
  assert.match(opts.replace(/\s+/g, ' '), /rootMargin:\s*'0px 0px -40px 0px'/,
    'rootMargin 不动：它管"离底边线多远才入场"，与这次的贴边不亮无关');
  // 分类器自检：选项对象必须由关键字认出，回调函数体的 {} 不算
  const synth = ioOptions('const o=new IntersectionObserver(function (es) { for (const e of es) { o.up(e); } },'
    + " { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });");
  assert.match(String(synth), /threshold/, 'ioOptions 抓到了回调体而不是选项对象（假通过）');
  assert.ok(!/o\.up/.test(String(synth)), 'ioOptions 把回调函数体当成选项对象返回了');
});

// 从 src 里的 `writeText(` 起沿**圆括号链**走，按顺序取出 .then / .catch 步名。
// 为什么不是"取到第一个 ; 为止再正则匹配"：真代码的分支体里就有 `;`（`done(btn);`），
// 那样一切就把 .catch 切在链外，红线看着像"缺拒绝支路"而其实工具在骗人。
// 步进条件用 \s* 而不是 [ \t]*：main.js 把 .catch 另起一行，只认行内空白会假红。
function thenCatchChain(src) {
  const at = src.indexOf('writeText(');
  assert.ok(at >= 0, '找不到 writeText( 调用');
  const closeAt = (i) => {   // i 指向 (，返回配对 ) 的下标
    let depth = 0;
    for (; i < src.length; i++) {
      if (src[i] === '(') depth++;
      else if (src[i] === ')') { depth--; if (depth === 0) return i; }
    }
    return -1;
  };
  let pos = closeAt(at + 'writeText'.length);
  assert.ok(pos >= 0, 'writeText( 的圆括号没配上，链无从走');
  const steps = [];
  for (let guard = 0; guard < 8; guard++) {
    const m = src.slice(pos + 1).match(/^\s*\.(then|catch)\s*\(/);
    if (!m) break;
    steps.push(m[1]);
    pos = closeAt(pos + 1 + m[0].length - 1);
    assert.ok(pos >= 0, `.${m[1]}( 的圆括号没配上，链无从走`);
  }
  return steps;
}

test('T11 结转 C4：剪贴板拒绝支路的存在性（删掉它原来 70 条门全绿）', () => {
  const code = jsCode();
  // 既有那两条管的是"支路里别说谎"（F4 收窄后的形态），把整支 .catch 删掉它们照样绿
  // ——反事实见 task-10-fix1-f4red.txt 的 B 组。本条只钉存在性，两者不重叠。
  const steps = thenCatchChain(code);
  assert.deepEqual(steps, ['then', 'catch'],
    '复制必须写成 writeText(text).then(…成功进 done…).catch(…失败不进 done)：'
    + `现在这条链是 [${steps.join(', ') || '（无）'}]。少了 .catch 这一支，浏览器往控制台打 `
    + 'Uncaught (in promise) DOMException——权限被拒或焦点丢失时既不静默也不谎报，是第三种噪声');
  // 走链器自检（判据不能只是"读一下真产物"的仪式）：
  // ① 缺 .catch 的形态必须给出 ['then']；② 分支体里带嵌套圆括号与 ; 的链必须走到底。
  assert.deepEqual(thenCatchChain('a.writeText(t).then(function () { done(b); });'), ['then'],
    '走链器没把"缺 .catch"的形态认出来——C4 这条判据就是空转');
  assert.deepEqual(thenCatchChain('a.writeText(t).then(function () { f(g(b), 1); h(); }, function () { i(); })\n'
    + '.catch(function () { j(k(l)); });'), ['then', 'catch'],
    '走链器被分支体里的嵌套括号或换行带偏了（真代码就是这个形状，误判即假红）');
});

// ---------------------------------------------------------------------------
// T12 博客：/updates/ 列表页 + 首篇 ALPHA 公告
// 判据一律按**形状**写（裁定 T-4）：字面量 class="post-item" 命不中规格要求的
// class="feat-card post-item"（T-3），字面量 <time datetime=…> 命不中带 class 的
// <time class="post-date" datetime=…>。为绿去放宽既有门或迁就字面量都是禁手。
// ---------------------------------------------------------------------------

const UPDATES_PAGE = 'updates/index.html';
// T-1：Hexo 的 :title 取的是**文件名去掉日期前缀**的 slug，故文章文件名必须叫
// 2026-11-16-syntime-alpha.md，测试路径才落在下面这条上。
const ALPHA_POST = '2026-11-16/syntime-alpha/index.html';
const ALPHA_SRC = '../source/_posts/2026-11-16-syntime-alpha.md';

// 列表页只点名读这两个新产物：既有 tests/*.mjs 没有任何目录遍历
// （grep -rn "readdirSync|glob" 只命中 copy.yml 的对象遍历与 CSS 扫描器），
// 不点名就是"新产物对全产物门不可见"，丢文件也照样绿。
test('T12 /updates/ 列表页存在，且不回退渲染首页模板', () => {
  assert.ok(existsSync(pub(UPDATES_PAGE)),
    `public/${UPDATES_PAGE} missing — 需要先有 themes/syntime/layout/page.ejs 与 source/updates/index.md，再跑 npm run build`);
  const list = html(UPDATES_PAGE);
  // T-6：.sec-head 只有 text-align/max-width，裸 <h1> 会落到 UA 默认 2em，与首页标题体系脱节
  assert.match(list, /<h1\b[^>]*>更新日志<\/h1>/, '列表页标题须是 <h1 class="h2">（T-6 复用 Token）');
  assert.match(list, tagHas('article', 'post-item'), '文章卡片须复用既有 feat-card（T-3）');
  // T-11 的**操作项**照做（站内链接走 url_for(p.path)，不许换 p.permalink）；但它对渲染值的
  // 那句实测描述不成立：Post.virtual('path')（hexo/dist/models/post.js:45）返回的就是
  // post_permalink 的 stringify 结果 `2026-11-16/syntime-alpha/`，**不含 index.html**，
  // index.html 是 Router 落盘时才补的。列表 href 与 canonical 因此同形，见下方交叉断言。
  assert.match(list, /<a\b[^>]*href="(?:\/[^"]*)?\/2026-11-16\/syntime-alpha\/"/, '列表链接必须由 url_for(p.path) 出');
  assert.doesNotMatch(list, /https:\/\/syntime\.cn\/2026/, '不许直接吐 p.permalink（绝对 URL，换 root 全断）');
  // 交叉断言（判据不空转）：列表 href 必须与文章页自己的 canonical 指向同一个资源
  assert.ok(existsSync(pub(ALPHA_POST)), `${ALPHA_POST} 不存在，无从交叉比对`);
  const postCanon = (html(ALPHA_POST).match(/<link rel="canonical" href="([^"]*)"/) || [])[1] || '';
  assert.equal(postCanon.replace(/^https:\/\/syntime\.cn/, ''), '/2026-11-16/syntime-alpha/',
    '文章页 canonical 的 path 部分变了，上面那条列表 href 判据就得跟着重推');
  assert.doesNotMatch(list, classHas('hero'), 'page.ejs 缺失时 Hexo 回退 index.ejs，会把整个 Hero 画进 /updates/');
  assert.match(list, tagHas('header', 'nav'), 'layout.ejs 的 chrome 必须在（layout:false 会一起丢掉）');
  assert.match(list, tagHas('footer', 'foot'), '同上：页脚由 layout 装配');
  assert.doesNotMatch(list, classHas('io'), 'T-9：博客页不得进 .io 揭示集合，禁用 JS 时正文会消失');
  assert.doesNotMatch(list, /<%[=%-]|\bundefined\b|\[object Object\]/, 'EJS 泄漏');
});

test('T12 首篇 ALPHA 公告存在，路径与禁词都守住', () => {
  assert.ok(existsSync(pub(ALPHA_POST)),
    `public/${ALPHA_POST} missing — permalink 与 new_post_name 必须配对（见报告 T-1 实测矩阵）`);
  const post = html(ALPHA_POST);
  assert.match(post, tagHas('article', 'post'), '文章页的 <article class="post"> 缺失（`\bpost\b` 式词边界会命中 post-item/post-back/post-date，列表页卡片就能顶包）');
  assert.doesNotMatch(post, classHas('hero'), 'T12 Minor 2 结转：文章页也不许出现 Hero——原来只钉了 /updates/，删掉 post.ejs 时 Hexo 一样回退 index.ejs');
  assert.match(post, /ALPHA/);
  assert.doesNotMatch(post, /docker run|开箱即用|一键拉起|三条链路|T\+1/, '§6 诚实性：未成立的能力不许写成已成立');
  assert.match(post, /<time\b[^>]*datetime="2026-11-16"/, 'T-4：判据须容忍 time 上带 class');
  assert.doesNotMatch(post, classHas('io'), 'T-9');
  assert.doesNotMatch(post, /<%[=%-]|\bundefined\b|\[object Object\]/, 'EJS 泄漏');
  // 双前缀嵌套 = new_post_name 没配对（实测矩阵第 3 行），点名失败模式而不是只报 missing
  for (const bad of ['2026-11-16/2026-11-16-syntime-alpha/index.html']) {
    assert.ok(!existsSync(pub(bad)), `出现双前缀路径 public/${bad}：permalink 与 new_post_name 脱钩了`);
  }
});

// 列表预览的抽取器（与 page.ejs 的形状约定同源），自检见下方 fixture 断言
const firstPreview = (s) => {
  const m = s.match(/<article\b[^>]*\bclass="[^"]*\bpost-item\b[\s\S]*?<p>([\s\S]*?)<\/p>/);
  return m ? m[1].replace(/<[^>]+>/g, '').trim() : null;
};

test('T12 列表预览 = 公告正文首段**全文**（T-7：hexo-excerpt 未装，excerpt 支路是空转）', () => {
  const src = readFileSync(new URL(ALPHA_SRC, import.meta.url), 'utf8');
  const para = src.replace(/^---[\s\S]*?\n---[\s\S]*?/, '').split(/\n\s*\n/).map((x) => x.trim()).filter(Boolean)[0];
  assert.ok(para && para.length > 10, '公告正文首段没取到，判据会空转');
  const preview = firstPreview(html(UPDATES_PAGE));
  assert.ok(preview !== null, '列表页文章卡片里没有预览 <p>');
  // 全文相等而非 includes：来源被换掉（改回 p.excerpt / 别的段）或又被 slice(0,120) 截断，当场红
  assert.equal(preview, para, '预览必须逐字等于公告首段全文，不截断、不换源');
  // 抽取器自检：真实卡片形状（带 h3/time）、带内联标签的段、没有 <p> 的卡片都要认得，否则上条是空转
  assert.equal(firstPreview('<article class="feat-card post-item"><h3>t</h3><time>x</time><p>甲乙丙丁戊</p></article>'),
    '甲乙丙丁戊', '抽取器漏掉了带 h3/time 的卡片形状');
  assert.equal(firstPreview('<article class="feat-card post-item"><p>甲<b>乙</b>丙</p></article>'),
    '甲乙丙', '抽取器没剥掉内联标签');
  assert.equal(firstPreview('<article class="feat-card post-item"><h3>只有标题</h3></article>'), null,
    '抽取器在没有 <p> 时应返回 null，而不是误抓别处的段');
});

test('T12 返回链接文案来自 copy.labels.post_back（T-5：约束 1 模板里不得有别的中文来源）', () => {
  assert.equal(typeof copy.labels.post_back, 'string', 'labels.post_back 必须是字符串');
  assert.ok(copy.labels.post_back.length > 0);
  // 新 key 只能进 labels：data.test.mjs 钉着 Object.keys(copy).length === 14
  assert.ok(!('post_back' in copy), 'post_back 不得挂在 copy 顶层，那是第 15 个顶层 key');
  const postTpl = readFileSync(new URL('../themes/syntime/layout/post.ejs', import.meta.url), 'utf8')
    .replace(/<%#[\s\S]*?%>/g, '');   // 剥注释：同 honesty.test.mjs 的模板门纪律
  assert.doesNotMatch(postTpl, /全部更新/, 'post.ejs 硬写了返回链接文案，违反约束 1（单一来源）');
  assert.match(postTpl, /C\.labels\.post_back/, 'post.ejs 必须由 copy.labels.post_back 出文案');
  // page.ejs 首行取了 C 全程不用 = 死代码（T-5）
  const pageTpl = readFileSync(new URL('../themes/syntime/layout/page.ejs', import.meta.url), 'utf8');
  assert.doesNotMatch(pageTpl, /site\.data\.copy/, 'page.ejs 不消费 copy，<% const C = … %> 是死代码，删掉');
  const post = html(ALPHA_POST);
  assert.match(post, new RegExp(`${tagHas('p', 'post-back').source}[\\s\\S]{0,200}?href="(?:/[^"]*)?/updates/"`),
    '返回链接必须由 url_for 拼到 /updates/（root 换值不换形状）');
  assert.ok(post.includes(`>${copy.labels.post_back}</a>`), '产物里必须渲染出 labels.post_back 的字面值');
});

test('T12 非首页的导航锚点拼回首页（T-2：谓词用 is_current，is_home 在本站恒 false）', () => {
  const navBlock = (s) => (s.match(new RegExp(`${tagHas('nav', 'nav-links').source}[\\s\\S]*?<\\/nav>`)) || [''])[0];
  for (const f of [UPDATES_PAGE, ALPHA_POST]) {
    const block = navBlock(html(f));
    assert.ok(block, `${f} 找不到 nav-links 块`);
    assert.doesNotMatch(block, /href="#/, `${f} 上还留着裸锚点：点了不跳（T4 轮 1 的悬空锚点）`);
    for (const a of copy.nav.anchors) {
      // root 换值不换形状：`/SynTime/#foundation` 也算首页回链
      assert.ok(new RegExp(`href="(?:/[^"]*)?${escRe(a.href)}"`).test(block), `${f} 缺 ${a.href} 的首页回链`);
    }
  }
  // 首页必须仍是裸锚点：is_current('/') 在 home 为真。误用 is_home() 时这条与 honesty 那条一起红
  const home = navBlock(html('index.html'));
  assert.match(home, /href="#foundation"/, '首页导航被改写成 /#… 说明谓词用错了（is_home 恒 false）');
  assert.doesNotMatch(home, /href="\//, '首页 nav-links 里不该出现带 root 前缀的链接');
});

test('T12 两个新页的 skip link 都落得进正文（T-8：<main id="main"> 全站装配一次）', () => {
  for (const f of [UPDATES_PAGE, ALPHA_POST]) {
    const s = html(f);
    assert.match(s, /<a\b[^>]*\bhref="#main"/, `${f} 缺 skip link（应在 layout.ejs，别在页模板里再写一遍）`);
    assert.match(s, /<main\b[^>]*\bid="main"/, `${f} 的 <main> 缺 id="main"，skip 会落空`);
    assert.equal([...s.matchAll(/<main\b/g)].length, 1, `${f} 只能有一个 <main>`);
    assert.equal([...s.matchAll(/href="#main"/g)].length, 1, `${f} 的 skip link 不应重复装配`);
  }
});

test('T12 新页进 sitemap，且 sitemap 不指向不存在的产物', () => {
  const map = html('sitemap.xml');
  // 逐字取自现量产物：hexo-generator-sitemap 的模板对 page 用 `page.permalink`
  // （core page 的那条含 index.html），对 post 用 post.permalink（按 permalink 模式，不含）。
  // 于是 /updates/ 在 sitemap 里是 …/updates/index.html，而 canonical 是 …/updates/ ——
  // 与 home 早已存在的 …/index.html 同族（本任务不扩范围去改生成器模板，登记给 T13）。
  assert.match(map, /<loc>https:\/\/syntime\.cn\/updates\/index\.html<\/loc>/);
  assert.match(map, /<loc>https:\/\/syntime\.cn\/2026-11-16\/syntime-alpha\/<\/loc>/);
  // 反事实门（写这条的当场就是它抓到的 bug）：文章 frontmatter 的 tags 会让生成器把
  // locals.tags 逐条发进 sitemap，而本站没装 hexo-generator-tag，public/ 里没有 tags/release/
  // 这个文件——抓取端表现为 404。_config.yml 的 sitemap.tags/categories=false 关掉这条路。
  const locs = [...map.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
  assert.ok(locs.length >= 4, 'sitemap 空了或塌了，下面的逐条解析无从谈起');
  for (const loc of locs) {
    // T12 Minor 1（结转 R46）：方向反了。<loc> 里是 **XML 转义后**的文本，要拿到文件路径得
    // 把 `&amp;` 解回 `&`，而不是把 `&` 再转义一遍——后者今天无 & 所以 inert，
    // 第一条带 query string 的 URL 进来就假红。
    const p = loc.replace(/^https:\/\/syntime\.cn/, '').replace(/&amp;/g, '&');
    const cands = p.endsWith('/') ? [`${p}index.html`] : p.endsWith('.html') ? [p] : [`${p}/index.html`, p];
    assert.ok(cands.some((c) => existsSync(pub(c.replace(/^\//, '')))),
      `sitemap 里的 ${loc} 在 public/ 下没有对应产物（404）：要么补生成器，要么别再发这条 URL`);
  }
  assert.equal(locs.length, 4,
    '站点地图条目数变了（现量 4 条：post 1 + core page 2〔updates、index〕+ config.url 1）；'
    + '新增/丢失可索引页都该在这里显形，别只改这个数字');
});
