#!/usr/bin/env node
// `superclef`: Super Clef's own terminal app. A question, a claim check, or no words for the window.
//   superclef "your question"            ask your connected notes
//   superclef /check "a statement"       check it against your notes
//   superclef setup                      check this Mac is ready (one time)
//   superclef connect <folder>           connect a folder of .md notes (--name NAME to pick the name)
//   superclef disconnect <name>          forget a connected folder (pointer, file list, registry row); your files are not touched
//   superclef media connect <path>... | media ask "question" | media list | media remove <name>   images (png/jpg/webp) and video (mp4/mov), judged by clef itself
//   superclef --version                  super-clef <version>
// The window and the one-shot door live in src/jev-chat-cli.ts; the judge is clef on the clef machine.
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const VERSION = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8')).version;
const SKILL = join(ROOT, 'skills', 'super-jev');
const argv = process.argv.slice(2);
// SUPERCLEF_X is the public name for SUPERJEV_X (new name wins); internals keep reading SUPERJEV_*.
for (const n of ['STATE_DIR', 'PRINCIPAL', 'CLEF_HOST', 'CLEF_DIR', 'JUDGE', 'BIN_DIR', 'INSTALL_DIR', 'REPO_URL', 'SAVE_AFTER', 'AUTO_CACHE']) {
  if (process.env['SUPERCLEF_' + n]) process.env['SUPERJEV_' + n] = process.env['SUPERCLEF_' + n];
}

if (argv[0] === '--version' || argv[0] === '-v' || argv[0] === 'version') {
  console.log(`super-clef ${VERSION}`);
} else if (argv[0] === 'setup') {
  const r = spawnSync('python3', [join(SKILL, 'setup.py'), ...argv.slice(1)], { stdio: 'inherit' });
  process.exitCode = r.status ?? 1;
} else if (argv[0] === 'connect') {
  const dir = argv[1];
  if (!dir || dir.startsWith('-')) {
    console.error('Usage: superclef connect <folder> [--name NAME]   (a folder of .md notes)');
    process.exitCode = 2;
  } else {
    const i = argv.indexOf('--name');
    const name = (i > 0 && argv[i + 1]) || basename(resolve(dir)).toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^[^a-z0-9]+|-+$/g, '') || 'notes';
    const rest = argv.slice(2).filter((a, j, all) => a !== '--name' && all[j - 1] !== '--name');
    const r = spawnSync('python3', [join(SKILL, 'prepare_bulk.py'), '--root', resolve(dir), '--pointer', name,
      '--principal', process.env.SUPERJEV_PRINCIPAL || 'me', '--writer', 'builtin', ...rest], { stdio: 'inherit' });
    if (r.status === 0) console.log(`Connected as "${name}". Ask with: superclef "your question". Forget it with: superclef disconnect ${name}`);
    process.exitCode = r.status ?? 1;
  }
} else if (argv[0] === 'disconnect') {
  if (!argv[1] || argv[1].startsWith('-')) {
    console.error('Usage: superclef disconnect <name>   (the name superclef connect printed)');
    process.exitCode = 2;
  } else {
    const r = spawnSync('python3', [join(SKILL, 'prepare_bulk.py'), '--disconnect', '--pointer', argv[1]], { stdio: 'inherit' });
    process.exitCode = r.status ?? 1;
  }
} else if (argv[0] === 'import-state') {
  console.error('import-state was removed. Connect your folder with: superclef connect <folder>');
  process.exitCode = 2;
} else if (argv[0] === 'media') {
  const r = spawnSync('python3', [join(SKILL, 'clef_media.py'), ...argv.slice(1)], { stdio: 'inherit' });
  process.exitCode = r.status ?? 1;
} else {
  const { run } = await import('../src/jev-chat-cli.ts');
  process.exitCode = await run({ argv, env: process.env, stdin: process.stdin, stdout: process.stdout, stderr: process.stderr });
}
