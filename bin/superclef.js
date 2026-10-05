#!/usr/bin/env node
// `superclef`: Super Clef's own terminal app. A question, a claim check, or no words for the window.
//   superclef "your question"            ask your connected notes
//   superclef /check "a statement"       check it against your notes
//   superclef import-state --from-superjev   give Super Clef the same connected files Super Jev has (read-only copy)
//   superclef media connect <path>... | media ask "question" | media list   images (png/jpg/webp) and video (mp4/mov), judged by clef itself
//   superclef --version                  super-clef <version>
// The window and the one-shot door live in src/jev-chat-cli.ts; the judge is clef on the clef machine.
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const VERSION = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8')).version;
const argv = process.argv.slice(2);

if (argv[0] === '--version' || argv[0] === '-v' || argv[0] === 'version') {
  console.log(`super-clef ${VERSION}`);
} else if (argv[0] === 'import-state') {
  if (!argv.includes('--from-superjev')) {
    console.error('Usage: superclef import-state --from-superjev [--json]');
    process.exitCode = 2;
  } else {
    const r = spawnSync('python3', [join(ROOT, 'skills', 'super-jev', 'import_state.py'), ...argv.slice(1)], { stdio: 'inherit' });
    process.exitCode = r.status ?? 1;
  }
} else if (argv[0] === 'media') {
  const r = spawnSync('python3', [join(ROOT, 'skills', 'super-jev', 'clef_media.py'), ...argv.slice(1)], { stdio: 'inherit' });
  process.exitCode = r.status ?? 1;
} else {
  const { run } = await import('../src/jev-chat-cli.ts');
  process.exitCode = await run({ argv, env: process.env, stdin: process.stdin, stdout: process.stdout, stderr: process.stderr });
}
