import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const yaml = require('js-yaml');

const copy = yaml.load(readFileSync(new URL('../source/_data/copy.yml', import.meta.url), 'utf8'));

test('copy.yml lives where Hexo actually loads it (F4)', () => {
  assert.ok(copy.hero, 'source/_data/copy.yml must parse and expose hero');
});

test('all 14 top-level keys present', () => {
  const keys = ['meta', 'placeholders', 'alpha_banner', 'labels', 'nav', 'hero', 'pills',
    'foundation', 'features', 'gallery', 'quickstart', 'positioning', 'faq', 'footer'];
  for (const k of keys) assert.ok(k in copy, `missing top-level key: ${k}`);
  assert.equal(Object.keys(copy).length, 14);
});

test('every badge value is one of the four legal states', () => {
  const legal = new Set(Object.keys(copy.labels.badges));
  const mapped = new Set(Object.keys(copy.labels.badge_pill_state));
  assert.deepEqual(legal, mapped);
  const seen = [...copy.foundation.items, ...copy.features.cards].map((c) => c.badge)
    .concat(copy.quickstart.planned.badge, copy.alpha_banner.badge);
  for (const b of seen) assert.ok(legal.has(b), `illegal badge: ${b}`);
  assert.deepEqual(copy.labels.badge_pill_state,
    { shipped: 'ok', partial: 'warn', dev: 'info', phase2: 'mute' });
});

test('hero has a visible caption for the design-mock disclaimer (S6 4)', () => {
  assert.equal(typeof copy.hero.caption, 'string');
  assert.match(copy.hero.caption, /设计稿/);
});
