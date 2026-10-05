#!/usr/bin/env node
// npm run e2e:clef -- the live end-to-end check of Super Clef's judge.
//  1. (nothing to import: connect your own folder first with `superclef connect <folder>`)
//  2. asks 2 questions from your eval jsonl file through the clef judge on the clef machine, live (saved answers off):
//     the first answerable one and the first absent one
//  3. asserts each is a ranked list or an honest not-found (the absent one never lists a confirmed file), that the answerable one really reached clef,
//     and that no payload is left on the clef machine
//  4. prints the time of each question and the total
// Needs: the clef machine reachable over ssh (SUPERJEV_CLEF_HOST), a folder connected with `superclef connect <folder>`, the eval file.
// Override: EVALSET=/path/to/file.jsonl, SUPERJEV_CLEF_HOST=user@host. Exit 0 only when every assertion holds.
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const EVALSET = process.env.EVALSET;
if (!EVALSET) { console.error('EVALSET is not set: set it to the path of the eval jsonl file'); process.exit(2); }
const HOST = process.env.SUPERJEV_CLEF_HOST;
if (!HOST) { console.error('SUPERJEV_CLEF_HOST is not set: set it to the ssh target of the clef machine, e.g. user@clef-host'); process.exit(2); }
const STATE = process.env.SUPERJEV_STATE_DIR ?? join(homedir(), '.local/state/super-clef');
const fails = [];
const check = (ok, what) => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${what}`); if (!ok) fails.push(what); };

const t0 = Date.now();

const rows = readFileSync(EVALSET, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
const picks = [rows.find((r) => !r.absent), rows.find((r) => r.absent)];

function lastTrace(principal) {
  const lines = readFileSync(join(STATE, principal, 'traces.jsonl'), 'utf8').split('\n').filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) { try { return JSON.parse(lines[i]); } catch { /* next */ } }
  return {};
}

for (const q of picks) {
  const t1 = Date.now();
  const r = spawnSync('python3', [join(ROOT, 'skills/super-jev/ask.py'), '--json', '--principal', q.principal, q.question],
    { encoding: 'utf8', env: { ...process.env, SUPERJEV_REPLAY: '1' }, timeout: 300000 });
  const secs = ((Date.now() - t1) / 1000).toFixed(1);
  let d = null;
  try { d = JSON.parse(r.stdout.split('\n').filter((l) => l.startsWith('{')).pop() ?? ''); } catch { /* checked below */ }
  const files = d?.files ?? [];
  const trace = lastTrace(q.principal);
  console.log(`\n${q.id} [${q.principal}] ${q.absent ? '(absent)' : '(answerable)'} ${q.question}\n  ${secs}s  outcome=${d?.outcome}  files=${files.length}  leans_none=${!!d?.leans_none}`);
  files.slice(0, 5).forEach((f, i) => console.log(`  ${i + 1}. [${f.tier}] ${f.path}`));
  const ranked = d?.outcome === 'found' && files.length > 0;
  const notFound = d?.outcome === 'not-found' && files.length === 0;
  check(ranked || notFound, `${q.id}: a ranked list or an honest not-found (got ${d?.outcome ?? 'no JSON'})`);
  if (!q.absent) {
    const c = trace.stages?.clef;
    check(!!c && !c.error && !!c.pick, `${q.id}: the clef judge on the clef machine returned a verdict (${c ? (c.error ?? `pick=${c.pick} p=${c.prob?.toFixed?.(2)}, judge ${c.judge_secs?.judge}s + load ${c.judge_secs?.load}s`) : 'no clef stage'})`);
  }
  // clef's 'none' is low trust: for the absent question nothing may be listed as confirmed; leads carry the leans-none note
  if (q.absent && ranked) check(files.every((f) => f.tier !== 'confirmed') && !!d.leans_none, `${q.id}: absent question lists no confirmed file, only leads with the leans-none note`);
}

const left = spawnSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', HOST, 'ls -d "$HOME"/.clefcall.* 2>/dev/null | wc -l'], { encoding: 'utf8' });
check(left.status === 0 && left.stdout.trim() === '0', `nothing left on the clef machine after the calls (${left.stdout.trim() || left.stderr.trim()} temp items)`);
console.log(`\ntotal time ${((Date.now() - t0) / 1000).toFixed(1)}s`);
process.exit(fails.length ? 1 : 0);
