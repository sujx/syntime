import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../source/css/main.css', import.meta.url), 'utf8');
// 视觉基准：仓库根的宣传站原型（V1.0 对齐，但 Token 层就是设计方案 §1 要求照抄的那一层）。
// 注意：该文件在 git 仓库之外（/home/sujx/Projects/SynTime/ 非仓库），未版本化。
const proto = readFileSync(
  new URL('../../../高保真原型_宣传站.html', import.meta.url), 'utf8');

const grab = (s) => (s.match(/:root\{[\s\S]*?\n\}/) || [''])[0].replace(/\s+/g, '');
// 只豁免营销专用的三个新增 Token，其余 Token（含 --shadow-xs…xl）必须逐字一致
const MARKETING_ONLY = /--(aurora-light|aurora-dark|shadow-brand):[^;]+;/g;

test(':root token block is a byte-faithful transcription of the baseline', () => {
  const want = grab(proto).replace(MARKETING_ONLY, '');
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

test('seal-red appears only in brand rules (design.md 2 discipline)', () => {
  assert.equal([...css.matchAll(/--seal-red/g)].length, 2, 'expected exactly: token decl + .seal background');
  // 原型的印章阴影走 rgba 字面量（`高保真原型_宣传站.html:53`），不吃变量；数 --seal-red 抓不住它
  const lit = [...css.matchAll(/([^{}]+)\{[^}]*192,57,43[^}]*\}/g)].map((m) => m[1].trim());
  assert.ok(lit.length > 0, 'prototype rgba seal shadow missing — transcription drifted');
  for (const sel of lit) assert.match(sel, /\.seal/, `seal-red literal leaked into ${sel}`);
});

test('discarded mock CSS never enters main.css', () => {
  // 原型 `:121-204`（迷你应用 mockup）与 `:213-217`（`.pbar*`）已作废：速览改用真截图。
  // 取前缀即可覆盖派生名（`.mk` 命中 `.mk-row`，`.donut` 命中 `.donut-c`）。
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const sel of ['.ss-brand', '.shot-side', '.mk', '.mtbl', '.donut', '.ev-row', '.mcard', '.mchart', '.pbar'])
    assert.ok(!bare.includes(sel), `discarded mock selector ${sel} present in main.css`);
  assert.ok(!bare.includes('.f-chip') && !bare.includes('.fc-1'), 'floating-chip CSS must stay dropped');
});

test('every transcribed section has at least one live anchor selector', () => {
  // 结构层只转录一次（T3 Step 8）；漏抄某段会让 Task 4–9 的 markup 无声无样式
  for (const sel of ['.hero .wrap', '.hero-visual', '.browser', '.nav-links', '.seal.s52', '.pill.ok',
    '.feat-grid', '.shot-frame', '.qs-grid', '.about-grid', '.faq-card', '.foot-bottom', '.io.in'])
    assert.ok(css.includes(sel), `missing transcribed selector ${sel}`);
});
