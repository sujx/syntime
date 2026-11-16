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

test('no unresolved EJS or undefined leakage', () => {
  const s = html('index.html');
  assert.doesNotMatch(s, /<%[=%-]/);
  assert.doesNotMatch(s, /\bundefined\b/);
  assert.doesNotMatch(s, /\[object Object\]/);
});
