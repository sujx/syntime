import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const yaml = require('js-yaml');
const copy = yaml.load(readFileSync(new URL('../source/_data/copy.yml', import.meta.url), 'utf8'));
const s = readFileSync(new URL('../public/index.html', import.meta.url), 'utf8');
const strip = (h) => h.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<[^>]+>/g, ' ');

test('S6-5 ALPHA banner is in the first screen, above the nav content', () => {
  assert.match(s, /class="alpha"/);
  assert.ok(s.indexOf('class="alpha"') < s.indexOf('class="nav"'), 'banner must sit above nav');
  assert.ok(strip(s).includes(copy.alpha_banner.text));
  const st = copy.labels.badge_pill_state[copy.alpha_banner.badge];
  assert.match(s, new RegExp(`class="pill ${st}"[^>]*>${copy.labels.badges[copy.alpha_banner.badge]}<`));
});

test('S6-5 banner contains no seal-red', () => {
  const css = readFileSync(new URL('../source/css/main.css', import.meta.url), 'utf8');
  assert.doesNotMatch(css.match(/\.alpha[^}]*\{[^}]*\}/g).join(''), /--seal-red|#C0392B/);
});

test('nav links mirror copy.nav.anchors and drop the prototype #screens', () => {
  const block = (s.match(/<nav class="nav-links"[\s\S]*?<\/nav>/) || [''])[0];
  assert.ok(block, 'nav-links block missing');
  assert.equal([...block.matchAll(/<a /g)].length, copy.nav.anchors.length);
  for (const a of copy.nav.anchors) assert.ok(block.includes(`href="${a.href}"`), `missing ${a.href}`);
  assert.doesNotMatch(block, /#screens/);
});

test('§6-5 first-screen clearance: banner pads past the fixed nav, nav top stays transcribed', () => {
  const css = readFileSync(new URL('../source/css/main.css', import.meta.url), 'utf8');
  assert.match((css.match(/\.alpha\{[^}]*\}/) || [''])[0], /padding:calc\(var\(--space-3\) \+ 70px\)/);
  assert.doesNotMatch(css, /^\.nav\{[^}]*top:calc/m, '.nav{top} must stay 12px as transcribed');
});
