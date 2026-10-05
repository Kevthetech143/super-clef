import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

test('organizer JSON reports the package.json version', () => {
  const cli = new URL('../src/cli.ts', import.meta.url).pathname;
  const example = new URL('../examples/organizer.json', import.meta.url).pathname;
  const r = spawnSync('node', [cli, 'organize', example, '--demo'], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(JSON.parse(r.stdout).version, pkg.version);
});
