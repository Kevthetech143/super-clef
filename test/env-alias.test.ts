// SUPERCLEF_X -> SUPERJEV_X through the one helper, at each style of TS entry (made-up values only).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { aliasEnv, ALIAS_NAMES } from '../src/env-alias.ts';
import { loadJudgeProfile } from '../src/judge-profile.ts';

const ROOT = new URL('..', import.meta.url).pathname;

test('aliasEnv: new name wins, empty and unset change nothing, same names as the python twin', () => {
  const e = aliasEnv({ SUPERCLEF_STATE_DIR: '/new', SUPERJEV_STATE_DIR: '/old', SUPERCLEF_PRINCIPAL: '', SUPERJEV_PRINCIPAL: 'keep', SUPERJEV_JUDGE: 'j' });
  assert.equal(e.SUPERJEV_STATE_DIR, '/new');
  assert.equal(e.SUPERJEV_PRINCIPAL, 'keep');
  assert.equal(e.SUPERJEV_JUDGE, 'j');
  const py = readFileSync(ROOT + 'skills/super-jev/superclef_env.py', 'utf8').match(/NAMES = \(([^)]*)\)/)![1];
  assert.deepEqual(ALIAS_NAMES, [...py.matchAll(/"(\w+)"/g)].map(m => m[1]));
});

test('library entry: loadJudgeProfile honours SUPERCLEF_JUDGE in a passed env and leaves that env untouched', () => {
  const env: NodeJS.ProcessEnv = { SUPERCLEF_JUDGE: 'typesafe-jev' };
  assert.equal(loadJudgeProfile(undefined, undefined, env).name, 'typesafe-jev');
  assert.equal(env.SUPERJEV_JUDGE, undefined);
});

test('script entry: fetch-cli run directly (no bin/superclef.js) sees SUPERCLEF_X', () => {
  const r = spawnSync(process.execPath, ['--import', './test/clean-env.ts', 'src/fetch-cli.ts', '--help'], { cwd: ROOT, encoding: 'utf8', env: { ...process.env, SUPERCLEF_JUDGE: 'no-such-judge' } });
  assert.match(r.stdout + r.stderr, /no-such-judge/);
});
