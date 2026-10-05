// Super Clef's own terminal app and judge profile: no network, no clef machine, no key.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadJudgeProfile } from '../src/judge-profile.ts';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const BIN = join(ROOT, 'bin', 'superclef.js');
const PKG = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
const run = (...args: string[]) => spawnSync(process.execPath, [BIN, ...args], { encoding: 'utf8', env: { ...process.env, HOME: '/nonexistent-home' } });

test('the package is Super Clef: name, version, its own bin and npm scripts', () => {
  assert.equal(PKG.name, 'super-clef');
  assert.match(PKG.version, /^\d+\.\d+\.\d+$/);
  for (const f of ['README.md', 'CHANGELOG.md', 'skills/super-jev/SKILL.md']) {
    assert.ok(readFileSync(join(ROOT, f), 'utf8').includes(PKG.version), `${f} mentions ${PKG.version}`);
  }
  assert.deepEqual(PKG.bin, { superclef: 'bin/superclef.js' });
  for (const s of ['clef', 'test', 'e2e:clef']) assert.ok(PKG.scripts[s], `npm run ${s}`);
  assert.equal(PKG.scripts.jev, undefined, 'the Super Jev entry is renamed, not kept');
});

test('superclef --version prints "super-clef <version>" and nothing else', () => {
  const r = run('--version');
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, `super-clef ${PKG.version}\n`);
});

test('superclef --help leads with its own usage and names the clef judge nowhere as Super Jev', () => {
  const r = run('--help');
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /^Usage: superclef "your question"$/m);
  assert.ok(!/superjev/i.test(r.stdout.replace(/super-jev/g, '')), r.stdout);
});

test('import-state without --from-superjev is a usage error, not a copy', () => {
  const r = run('import-state');
  assert.equal(r.status, 2);
  assert.match(r.stderr, /Usage: superclef import-state --from-superjev/);
});

test('the default judge is clef: keyless, free, one short package', () => {
  const p = loadJudgeProfile(undefined, undefined, {});
  assert.equal(p.name, 'clef');
  assert.equal(p.kind, 'clef');
  assert.equal(p.keyRequired, false);
  assert.equal(p.inputUsdPerMtok, 0);
  assert.ok(p.windowTokens <= 2048);
  assert.equal(loadJudgeProfile('fake', undefined, {}).name, 'typesafe-jev', 'the fake test judge keeps the Jev numbers');
});

test("Super Clef never defaults to Super Jev's state or install folders", () => {
  const hits: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (name === 'node_modules' || name === '.git' || name === 'prepare-cache' || name === '__pycache__' || name === 'tests') continue;
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.(py|ts|js|mjs|sh)$/.test(name) && /\.local\/(state|share)\/super-jev/.test(readFileSync(p, 'utf8'))) hits.push(p.slice(ROOT.length));
    }
  };
  for (const d of ['src', 'skills', 'bin', 'scripts']) walk(join(ROOT, d));
  assert.deepEqual(hits.filter((h) => !h.endsWith('import_state.py')), [], 'only import-state may name Super Jev\'s state, and only to read it');
});
