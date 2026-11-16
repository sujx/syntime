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
});

test('quickstart step 1 carries no clone line (template owns it)', () => {
  assert.doesNotMatch(copy.quickstart.steps[0].code, /git clone/);
  assert.match(copy.quickstart.steps[0].code, /^cd SynTime\/syntime\/backend/);
});

test('every TODO placeholder is still visibly a placeholder pre-publish', () => {
  assert.match(P.github_repo, /^TODO_/);
  assert.match(P.dockerhub_namespace, /^TODO_/);
});
