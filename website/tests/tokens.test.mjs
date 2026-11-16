import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

const css = readFileSync(new URL('../source/css/main.css', import.meta.url), 'utf8');
// 视觉基准：仓库根的宣传站原型（样式与结构照抄，**文字一概不取**）。
// 它在 git 仓库之外（/home/sujx/Projects/SynTime/ 不是仓库、未版本化），
// 所以缺位时**跳过**这几条，而不是让整个文件在 import 阶段崩掉、把别的判据一起带走。
const PROTO_URL = new URL('../../../高保真原型_宣传站.html', import.meta.url);
const hasProto = existsSync(PROTO_URL);
const proto = hasProto ? readFileSync(PROTO_URL, 'utf8').split(/\r?\n/) : [];
const src = hasProto ? {} : { skip: '原型 HTML 不在约定路径，转录判据无从比对' };

const grab = (s) => (s.match(/:root\{[\s\S]*?\n\}/) || [''])[0].replace(/\s+/g, '');
// 只豁免营销专用的三个新增 Token，其余 Token（含 --shadow-xs…xl）必须逐字一致
const MARKETING_ONLY = /--(aurora-light|aurora-dark|shadow-brand):[^;]+;/g;

// 转录范围表 —— 与 Step 8「照抄」行一一对应。改这张表必须同时改 Step 8 与 T13 的偏差段。
const RANGES = [[13, 50], [51, 61], [62, 83], [84, 105], [115, 120], [205, 212], [218, 225],
  [226, 240], [241, 251], [252, 283], [284, 296], [297, 308], [309, 318], [319, 327], [328, 347]];
const DROP = new Set([324, 332, 341, 342]);                       // 作废的浮卡 / mock 声明
const SUB = new Map([[280, '  font-size:12px;color:#8FA0C8}']]);  // 唯一登记的改写（--sidebar-text 本站未定义）
const APPENDIX = '/* ============ V1.1–V1.3 增补结构（设计方案 §0-6 / §2.1） ============ */';

function transcribedWanted() {
  const out = [];
  for (const [a, b] of RANGES) {
    for (let n = a; n <= b; n++) {
      if (DROP.has(n)) continue;
      const line = SUB.get(n) ?? proto[n - 1];
      assert.ok(line !== undefined, `原型没有第 ${n} 行——范围表错了`);
      if (line.trim() !== '') out.push(line);
    }
  }
  return out;
}

test('main.css 转录区逐行等于原型范围表（漏抄与自造都当场红）', src, () => {
  const lines = css.split(/\r?\n/);
  const cut = lines.indexOf(APPENDIX);
  assert.ok(cut > 100, '找不到增补段标记——转录区与 Task 4–9 的追加区失去边界');
  const got = lines.slice(0, cut).filter((l) => l.trim() !== '');
  const want = transcribedWanted();
  assert.ok(want.length > 200, `期望行数异常（${want.length}）——范围表或原型路径错了`);
  assert.deepEqual(got, want);
  // 边界是双向的：转录区逐字之外，增补段也不许另立第二份同名规则来源。
  // 注释里的 `.nav{top:12px}` 是 R16 的理由文字、不是规则，故两处都先剥注释再数。
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, '');
  assert.equal((bare.match(/\.nav\{/g) || []).length, 1, '.nav{ 规则全站只能有一条（转录区的那条）');
  const after = lines.slice(cut).join('\n').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.ok(!after.includes('.nav{'), 'APPENDIX 段里不得再写 .nav{ 规则');
  assert.doesNotMatch(css, /top:calc/, '全站不得出现 top:calc——.nav{top} 必须保持转录的 12px');
});

test(':root token block is a byte-faithful transcription of the baseline', src, () => {
  const want = grab(readFileSync(PROTO_URL, 'utf8')).replace(MARKETING_ONLY, '');
  const got = grab(css).replace(MARKETING_ONLY, '');
  assert.ok(want.length > 400, 'failed to locate prototype :root — check the path');
  assert.equal(got, want);
});

test('every design.md colour token is present', () => {
  for (const m of want_shades()) assert.ok(css.includes(m), `missing token ${m}`);
  function want_shades() {
    const out = [];
    for (const n of [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]) out.push(`--primary-${n}:`);
    for (const n of [25, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900]) out.push(`--gray-${n}:`);
    for (const p of ['danger', 'success', 'warning'])
      for (const n of [50, 500, 600]) out.push(`--${p}-${n}:`);
    return out;
  }
});

test('seal-red stays on brand surfaces (design.md §2 discipline)', () => {
  // 不数出现次数：次数是今天的快照，不是规则；T9 给页脚徽记上印章红是合法的。
  // 规则是「谁能用印章红」——变量与 `192,57,43` 字面量都只许待在品牌选择器里。
  const rules = (css.replace(/\/\*[\s\S]*?\*\//g, '').match(/[^{}]+\{[^}]*\}/g) || []);
  const offenders = rules
    .filter((r) => /var\(--seal-red\)|192,57,43/.test(r.slice(r.indexOf('{') + 1)))
    .map((r) => r.slice(0, r.indexOf('{')).trim());
  assert.ok(offenders.length > 0, '印章红一处都没有——转录丢了 .seal 的阴影字面量');
  for (const sel of offenders) {
    assert.match(sel, /\.seal|\.wm|\.foot/, `印章红进了非品牌选择器：${sel}`);
  }
});

test('discarded mock CSS never enters main.css', () => {
  // 原型 `:106-113` 浮卡、`:121-204` 迷你应用 mockup、`:213-217` `.pbar*` 已作废：速览改用真截图。
  // 取前缀即可覆盖派生名（`.mk` 命中 `.mk-row`，`.donut` 命中 `.donut-c`）。
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const sel of ['.ss-brand', '.shot-side', '.mk', '.mtbl', '.donut', '.ev-row', '.mcard', '.mchart',
    '.pbar', '.f-chip', '.fc-1', '.fc-2', 'floatY']) {
    assert.ok(!bare.includes(sel), `discarded mock selector ${sel} present in main.css`);
  }
});

test('every animation name has its @keyframes', () => {
  // 漏抄一条 @keyframes 是**静默失效**：`062e5bc` 曾把 `cardIn` 丢掉而 20 条测试全绿。
  const defined = new Set([...css.matchAll(/@keyframes\s+([\w-]+)/g)].map((m) => m[1]));
  const used = [...css.matchAll(/animation:\s*([\w-]+)/g)].map((m) => m[1]).filter((n) => n !== 'none');
  assert.ok(used.length > 0, '一条 animation 都没有——转录丢了整段');
  for (const n of used) assert.ok(defined.has(n), `animation:${n} 没有对应的 @keyframes`);
});

test('every transcribed section has at least one live anchor selector', () => {
  // 结构层只转录一次（T3 Step 8）；漏抄某段会让 Task 4–9 的 markup 无声无样式
  for (const sel of ['.hero .wrap', '.hero-visual', '.browser', '.nav-links', '.seal.s52', '.pill.ok',
    '.feat-grid', '.shot-frame', '.qs-grid', '.about-grid', '.faq-card', '.foot-bottom', '.io.in']) {
    assert.ok(css.includes(sel), `missing transcribed selector ${sel}`);
  }
});

test('增补段圆点色引用语义 Token，不在 CSS 里再抄一份十六进制', () => {
  // 转录区 `.b-dot`（原型 :118）只有尺寸；颜色在原型里是 span 的内联 style（原型 :401），
  // 而内联样式不进本站，所以颜色由 APPENDIX 补——但必须挂到 Token 层已有的三个语义色上，
  // 否则同一个颜色就有了第二个来源（改 Token 时圆点不会跟着变，正是 Token 单一来源要避免的）。
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, '');            // 注释里也写着十六进制，先剥掉再判
  const want = ['--danger-500', '--warning-500', '--success-500'];
  for (let n = 1; n <= 3; n++) {
    const m = bare.match(new RegExp(`\\.b-dot:nth-child\\(${n}\\)\\{background:([^}]*)\\}`));
    assert.ok(m, `.b-dot:nth-child(${n}) 没有 background 规则——浏览器框的圆点会渲染成透明`);
    assert.equal(m[1], `var(${want[n - 1]})`,
      `.b-dot:nth-child(${n}) 的颜色必须是 var(${want[n - 1]})，不得写十六进制副本`);
  }
  const cut = css.indexOf(APPENDIX);
  assert.ok(cut > 0, '找不到增补段标记');
  assert.doesNotMatch(css.slice(cut).replace(/\/\*[\s\S]*?\*\//g, ''), /#(?:E85A5A|F5A623|1FB56B)/i,
    '圆点的十六进制副本不得再出现在增补段——颜色只有一个来源（:root 的 Token）');
});

test('圆点用到的三个 Token 与原型 :401 的内联色逐字符相等', src, () => {
  // 上条判据把圆点挂到 Token，本条钉住「挂对了」：Token 的值必须仍然等于原型那三枚内联色，
  // 否则圆点会在 Token 层被悄悄换色。等式两边都现读，不靠注释自证。
  const line = proto[400];                                          // 原型第 401 行
  assert.ok(/class="b-dot"/.test(line), `原型 :401 不再是 .b-dot 那一行（${line}）——判据要跟着基准搬家`);
  const hexes = [...line.matchAll(/background:#([0-9A-Fa-f]{6})/g)].map((m) => m[1].toUpperCase());
  assert.deepEqual(hexes, ['E85A5A', 'F5A623', '1FB56B'], '原型 :401 的内联圆点色变了，需复核 Token 层');
  for (const [tok, hex] of [['--danger-500', 'E85A5A'], ['--warning-500', 'F5A623'], ['--success-500', '1FB56B']]) {
    const m = css.match(new RegExp(`${tok}:\\s*#([0-9A-Fa-f]{6})`));
    assert.ok(m, `Token ${tok} 在 :root 里找不到`);
    assert.equal(m[1].toUpperCase(), hex, `${tok} 已不等于原型圆点色 #${hex}`);
  }
});
