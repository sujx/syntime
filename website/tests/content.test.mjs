import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const yaml = require('js-yaml');
const raw = readFileSync(new URL('../source/_data/copy.yml', import.meta.url), 'utf8');
const copy = yaml.load(raw);
const P = copy.placeholders;

test('github/dockerhub URL is declared exactly once each', () => {
  assert.equal((raw.match(/https:\/\/github\.com\//g) || []).length, 1);
  assert.equal((raw.match(/https:\/\/hub\.docker\.com\//g) || []).length, 1);
});

test('all github hrefs alias the single placeholder', () => {
  const want = P.github_url;
  assert.equal(copy.nav.cta.href, want);
  assert.equal(copy.hero.ctas[0].href, want);
  assert.equal(copy.footer.links[0].href, want);
});

test('placeholders stay internally consistent (drift guard)', () => {
  assert.equal(P.github_url, `https://github.com/${P.github_repo}`);
  assert.equal(P.dockerhub_url, `https://hub.docker.com/r/${P.dockerhub_namespace}`);
  assert.equal(P.dockerhub_image, `${P.dockerhub_namespace}/syntime`);
});

test('no github/dockerhub string anywhere escapes the two placeholders', () => {
  const host = /(github\.com|hub\.docker\.com|git@github)/i;
  const bad = [];
  (function walk(node, path) {
    if (typeof node === 'string') {
      if (host.test(node) && node !== P.github_url && node !== P.dockerhub_url) bad.push(`${path}: ${node}`);
    } else if (Array.isArray(node)) {
      node.forEach((v, i) => walk(v, `${path}[${i}]`));
    } else if (node && typeof node === 'object') {
      for (const [k, v] of Object.entries(node)) walk(v, `${path}.${k}`);
    }
  })(copy, 'copy');
  assert.deepEqual(bad, []);
});

test('quickstart step 1 carries no clone line (template owns it)', () => {
  assert.doesNotMatch(copy.quickstart.steps[0].code, /git clone/);
  assert.match(copy.quickstart.steps[0].code, /^cd SynTime\/syntime\/backend/);
});

test('every URL placeholder is still visibly a placeholder pre-publish', () => {
  // 这是**发布前**门禁：真 owner / namespace 落地后本条会红，届时连同 copy.yml 的 `placeholders` 段
  // 那条「发布前需要改的 3 处：github_url / dockerhub_url / dockerhub_image」注释一起改
  // （F28/R41：跨文件出处按语句原文引，不按行号引）。
  assert.match(P.github_repo, /^TODO_/);
  assert.match(P.dockerhub_namespace, /^TODO_/);
  assert.match(P.github_url, /TODO_/);
  assert.match(P.dockerhub_url, /TODO_/);
  assert.match(P.dockerhub_image, /^TODO_/);
});
