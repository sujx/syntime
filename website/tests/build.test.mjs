import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

const pub = (p) => new URL(`../public/${p}`, import.meta.url);
const html = (p) => readFileSync(pub(p), 'utf8');

test('hexo generate produced index.html with theme shell', () => {
  assert.ok(existsSync(pub('index.html')), 'public/index.html missing — run npm run build');
  const s = html('index.html');
  assert.match(s, /<html lang="zh-CN">/);
  assert.match(s, /href="\/css\/main\.css"/);
  assert.match(s, /src="\/js\/main\.js"/);
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
// 这不是新发明，是本仓既有约定：T7 的模板门先剥 `<%# %>`（honesty.test.mjs:563-566），
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
    '.io 的解锁态 .in 要由脚本在**两条分支各加一次**（main.css:213）；模板侧由 T7 明令不得预置 in');
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
    + '它照样拿得到换行，实测同一结构 innerText 取到 "a\\nb\\nc"、textContent 取到 "abc"（行数差 2），'
    + 'textContent 唯一的优势是保留源码里的原始空白，那是 Task 8 的写法而非本行的契约');
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
