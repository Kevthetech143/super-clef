# Super Clef

Your agent asks in its own words; Super Clef finds the file in your connected notes, checks the claim, and remembers what you approved. The judge is Cloudflare **clef-flash** (Apache-2.0, 4-bit) running on a second Apple-silicon machine reached over ssh. It has its own terminal app, and makes no paid judge calls and needs no TypeSafe key.

Status: v0.3.0. The reference manual below covers every command; "the judge" means the clef model that checks your questions and claims (see "How the clef judge works").

## Use it

```
npm run clef                                  open the window (or: node bin/superclef.js)
node bin/superclef.js "your question"        one-shot question
node bin/superclef.js /check "a statement"    check a statement against your notes
node bin/superclef.js --version               super-clef 0.3.0
node bin/superclef.js setup                   check this Mac is ready (one time)
node bin/superclef.js connect <folder>        connect a folder of notes (.md)
node bin/superclef.js disconnect <name>       forget a connected folder (your files stay)
scripts/install-superclef.sh                  put `superclef` on your PATH (~/.local/bin)
```

Super Clef keeps its own state in `~/.local/state/super-clef` (override: `SUPERCLEF_STATE_DIR`). Set `SUPERCLEF_PRINCIPAL` to ask as a given agent (default `me`).

## Environment names

Set any of these as `SUPERCLEF_X`. Setups from before the rename may still use `SUPERJEV_X`; that name keeps working, and when both are set, `SUPERCLEF_X` wins. The skill folders are still named `skills/super-jev/...` (folder name kept for now); where a command below needs a path, type it as shown.

`STATE_DIR`, `PRINCIPAL`, `CLEF_HOST`, `CLEF_DIR`, `JUDGE`, `BIN_DIR`, `INSTALL_DIR`, `REPO_URL`, `SAVE_AFTER`, `AUTO_CACHE`, `PRIVATE_DIRS`, `GATE_CMD`, `NEW_FILE_SCAN`.

## Setup: the judge host

The clef judge runs on a second Apple-silicon machine reached over ssh (key login, `BatchMode`). There is no default host: set `SUPERCLEF_CLEF_HOST` to its ssh target (for example `user@clef-host`) before using Super Clef; without it every judge call stops with an error naming that variable. Optional: `SUPERCLEF_CLEF_DIR` (the clef folder on that machine, default `~/clef-test`). For the live scripts also set `EVALSET` (eval jsonl); `scripts/head-to-head.sh` also needs `OUT`, `WORK` and `JEV_STATE_DIR`. `SUPERCLEF_PRIVATE_DIRS` (colon-separated) lists folders the media door must never read.

## Prepare the judge machine

One-time setup on the second Apple-silicon machine. The steps follow how our own judge machine was built (Apple silicon, 16 GB, macOS, Python 3.12 venv made with uv, 5.8 GB model folder). Unverified: other RAM sizes (the code allows for about 12 GB peak) and a from-scratch run of these exact commands on a clean machine.

1. Make sure this Mac can `ssh user@clef-host` with a key and no password prompt (Super Clef uses `ssh -o BatchMode=yes`).
2. On the judge machine, make the folder and a Python 3.12 venv named `.venv` inside it. The folder must be `~/clef-test`, or set `SUPERCLEF_CLEF_DIR` to another one:
   ```
   mkdir -p ~/clef-test && cd ~/clef-test
   uv venv --python 3.12 .venv
   uv pip install --python .venv/bin/python mlx-vlm huggingface_hub
   ```
   `mlx-vlm` and `huggingface_hub` are the install line on the model card. Tested with mlx 0.32.3, mlx-vlm 0.7.4, mlx-lm 0.32.0, huggingface_hub 1.33.0, transformers 5.18.0. The image and video door also has pillow and opencv-python installed there (unverified whether they are the minimum).
3. Download the model into a folder named exactly `model4` (the client and the daemon load `model4` relative to the clef folder):
   ```
   .venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/clef-flash-4bit', local_dir='model4')"
   ```
   The source is the Hugging Face repo `mlx-community/clef-flash-4bit`: a 4-bit MLX conversion of `Cloudflare/clef-flash`. Its model card states `license: apache-2.0`. The download is 15 files and the loader `clef_mlx.py` comes inside the model folder, so there is nothing else to copy. Clef is not a chat model: only that loader runs it.
4. Check it from the judge machine, with the example from the model card (`cd ~/clef-test`, `sys.path.insert(0, "model4")`, `import clef_mlx`, `clef_mlx.load("model4").systemone({...})`; the full example is in `model4/README.md`). It should print per-question answers with probabilities.
5. Check it from this Mac: `export SUPERCLEF_CLEF_HOST=user@clef-host`, then `npm run e2e:clef` with `EVALSET` set (see above). It asks 2 questions and fails if nothing comes back or if payload files are left on the judge machine.

Not verified by me: step 4 and 5 were not re-run for this section (the model is loaded by other jobs on the live machine); the folder and package facts above were read from the live machine.

## How the clef judge works

- **Judge**: profile `clef` (default) in `skills/super-jev/judge_profiles.json`, behind the same judge seam (`judges.ask`). `lib/clef_client.py` pipes one short package over `ssh` to the clef directory (`SUPERCLEF_CLEF_DIR`, default `~/clef-test`) on a second Apple-silicon machine reached over ssh (`.venv/bin/python`, `clef_mlx`), under a lock so only one clef process runs at a time. The payload goes to a temp dir on the clef machine that a trap deletes after every call, success or failure. `SUPERCLEF_JUDGE=typesafe-jev` selects the hosted TypeSafe judge instead.
- **Short package** (harness report, shape A: pick one file or none): at most 4 files, each cut to about 120 tokens around the question's words, one question, about 600 tokens, 6-7 s on the M1 plus 3 s model load. The free shortlist (word search plus an idf-ranked table-of-contents list) replaces a table-of-contents pick.
- **Trust**: clef's "none", and any pick above 0.9, are low trust (it is overconfident when the answer is absent). Those files are listed as possible with a note, never confirmed, and are never saved automatically. A claim check is a lead: TRUE/FALSE carries a "confirm in the proof file" line and is not cached.
- **Your files**: `superclef connect <folder>` connects a folder of notes; `superclef disconnect <name>` forgets it (the originals are never touched). Connected sets are read in place; no file contents leave this Mac except the per-question package.
- **Images and video**: `superclef media connect|ask|list|remove`; clef reads them directly (no audio; cut-off text is not reliable).
- **Not done yet**: saving a new answer, `verify` and the Stop gate (they need the TypeSafe provider), and recall on questions whose wording differs from the file (the hosted judge reads table-of-contents pages for that; clef reads one short package).

## Tests

```
npm test                 full suite: node tests, then the Python skill tests (clef judge tests use a stub; no clef machine needed)
npm run e2e:clef         live: imports state, asks 2 questions from your eval jsonl through the clef machine, asserts a ranked list or honest not-found, prints times
```

---

# Reference manual


One judge between your agent and your data: the agent asks in its own words, Super Clef finds the file, checks the claim, permits the action, and remembers what you approved. Your agent stays responsible for the answer.

## Vision

- One judge sits between your agent and your data: the agent asks in its own words, Super Clef finds the file, checks the claim, permits the action, and remembers what you approved. Your agent stays responsible for the answer.
- Agents burn whole LLM turns on lookups, re-hunt the same answers daily, and state things the files never said. The judge is a fast, cheap model for yes/no and which-one questions; the LLM keeps the writing.
- The daily loop: ask → read the top file → answer → approve / miss / add. Connectors are how your data gets in; the cache fills only from your own approvals — nothing is cached that you did not approve.
- 1.0 promises the proven core: skill search, file navigate, connect + bulk prepare, check gate, permit gate, the harness loop. The core works well when it works; edges still want an agent in the seat — see KNOWN-QUIRKS.md and AGENTS.md.
- 1.0 does not promise unattended answering, semantic cache matching, automatic sync, or live browsing. Next: auto-catch, recipes, a judge-decided browser driver — each ships only after its own live bench.

## Quick start

People: [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md) — the full operating manual.
Agents: [AGENTS.md](AGENTS.md) — the numbered path and daily loop, plus
[wire-into-claude-code](docs/wire-into-claude-code.md) for the retrieval rule card and Stop-hook claim gate.
At a terminal: `npm run clef` opens the app ([docs/terminal-app.md](docs/terminal-app.md)). No key yet? `npm run demo` runs the loop once offline.

## The loop

`ask` → read the top file yourself → answer → `--miss` a bad saved one, `--add` a fact that has no file. A question you ask again saves itself.

Auto-save: when the same file wins the same question for you N times in a row (`SUPERCLEF_SAVE_AFTER`, default 2) on complete searches (a partial search neither counts nor resets) and passes the content check, the ranked list from the winning search is saved (up to 5 files, not an answer; the N wins are the evidence, so no extra claim check, and the secret scan and unchanged-file check still run; marked `approved_by: auto-save`); the next ask returns the whole list at once, in rank order, labelled saved, with no search, and you open the files; if any listed file changed it is withheld as STALE and searched live. Secret-held files are not saved, and a changed file is withheld as STALE; it says why. Opt out with `--no-auto` or `SUPERCLEF_AUTO_CACHE=0`. `--approve` meets the threshold at once (`approved_by: principal:NAME`). Every cache hit prints who approved it, and `--miss` on a cached question un-saves it. Matching is the same question after lowercasing, collapsing spaces and dropping trailing punctuation; nothing fuzzier. A saved answer lasts until its source file changes, with no clock expiry. Connectors are how data gets in: onboard a folder once, and it stays answerable.

## Maturity

| Door | Status |
| --- | --- |
| ask (the daily cycle) | LIVE |
| skill search | LIVE |
| file navigate | LIVE |
| connect + bulk prepare | LIVE |
| check gate | LIVE |
| permit gate | LIVE |
| harness loop (demo / replay) | LIVE |
| sweep | MEASURED — has live bench scripts |
| catalog | MEASURED — has live bench scripts |
| fetch | MEASURED — bench scripts exist; admission gate not yet met (see AGENTS.md) |
| chain-cli | EXPERIMENTAL — see src/experimental/ |
| derive-facts | EXPERIMENTAL — see src/experimental/ |
| investigate | EXPERIMENTAL — see src/experimental/ |
| passage-level search | EXPERIMENTAL |
| saved-answer approve reuse | EXPERIMENTAL |
| verify | EXPERIMENTAL |
| auto-catch | EXPERIMENTAL — 1.1 track |

LIVE = proven in daily use. MEASURED = exercised by live bench scripts. EXPERIMENTAL = moved aside; not deleted, not shipped.

## What 1.0 does not do

- Answer unattended — an agent stays in the seat for the final call.
- Match paraphrases from cache — cache hits are exact wording only.
- Sync automatically — data gets in through connectors you run. Nothing watches your folders. An ask that meets a changed set starts a bounded, best-effort background refresh; refreshing stays your step.
- Browse the web — doors work on connected local data only.
- Rewrite history — the scrub covers current files; history is untouched by design.

## Maintainer

Maintainer: Kevthetech143 — issues welcome via the miss template (`.github/ISSUE_TEMPLATE/miss.md`).

## Platform

Tested on macOS and Linux. Windows is untested.

## What this tool touches

| Scope | Detail |
|---|---|
| Reads | Your connected folders and configured skill roots. |
| Writes | State dir under your home — `$SUPERCLEF_STATE_DIR` or `~/.local/state/super-clef/` (Super Clef's own folder) (per-principal logs, the `_memory/` config and pointer store `setup.py` creates) — plus `skills/super-jev/prepare-cache/`, `skills/super-jev/ledger/` and `skills/super-jev/autoheal-state/` (background-refresh locks, cooldowns and logs that name your sets and files) in the checkout. The terminal app saves a key you paste to `~/.typesafe-api-key` (owner-only; the same file the setup steps export the key from), and `scripts/install-superclef.sh` writes a launcher at `~/.local/bin/superclef`. Older versions kept a config holding the key at `~/.config/superjev/config.json` (or `$XDG_CONFIG_HOME/superjev/`). |
| Leaves the machine | Sent to the TypeSafe provider: file text when `ask` reads a file to confirm an answer, descriptions (a builtin description quotes the file's first words) and questions (to rank files), and the claim plus evidence files you pass to `check`. A connect sends file text only with a model writer (the default when the `claude` CLI is installed): the writer model reads an excerpt of each file and TypeSafe checks each description against its file. `--writer builtin` sends nothing while connecting, unless you add `--findability`: that runs one ranking search per file, which sends the descriptions and that file's sample question. |
| Provider receives | The above; never files the secret scan holds — those stay local. |
| Never leaves | Files the secret scan holds, and files connect skips by default below a `--root` you connect (folders named `profile/` or `documents/`, hidden and generated folders, other file types), unless you pass one to `check` yourself; connect prints a `SKIP` line for each kind. |

## Uninstall

```bash
python3 skills/super-jev/setup.py --uninstall
```

Removes everything Super Clef wrote: the state directory (`$SUPERCLEF_STATE_DIR` or
`~/.local/state/super-clef`: the memory config, connected pointers, cached answers and
logs), `skills/super-jev/prepare-cache/`, `ledger/` and `autoheal-state/` in this
checkout, an older app's config (`~/.config/superjev/config.json`, which held the key),
the `superclef` launcher (and the old `superjev` one) in `~/.local/bin` if it carries the installer marker and points at this checkout, and any
`~/.claude/skills` links that point into this checkout. It deletes only the names Super Clef
writes in each folder; a file of yours in the same folder stays, and the output lists it.
It keeps `~/.typesafe-api-key`, your key file (hooks and agents read it too): delete it
yourself if you want the key gone. Your own files are never touched. Delete the checkout
folder to remove the code.

## Doors

- `ask` — `python3 ask.py` in `skills/super-jev/`: the daily ask loop front door over every connected pointer.
- `check` — `python3 dispatch.py check`: the claim gate over a claim or draft.
- `navigation` — `src/navigation-cli.ts`: navigate a file catalog for the best evidence files for one question.
- `skill-search` — `src/skill-search-cli.ts`: suggest which installed skills serve one request; advisory only.
- `permit` — `src/permit-cli.ts`: is this one harness action safe to run automatically?
- `permit` hard rules: destructive/irreversible actions are refused by hard code (before any model call) — documented in `docs/playbook.md`, see the permit row.
- `catalog` — `src/catalog-cli.ts`: maintenance door for fetch v2 catalogs (validate / learn / build).
- `catalog-build` — `src/catalog-build-cli.ts`: build a fetch v2 catalog JSON from a skills directory.
- `fetch` — `src/fetch-cli.ts`: score a catalog against one request and print only the top-k ids.
- `sweep` — `src/sweep-cli.ts`: process a record pile bigger than one call and prove nothing was skipped.
- Experimental (`chain-cli`, `derive-facts-cli`): see `docs/experimental/`.

## Coming next

- auto-catch: approved hits kept without a manual command.
- recipes: cache the how, run it live.
- browser driver: the judge decides, with an action permit before every click.

## Help us: report a miss

This is one team's daily driver made public. We want your misses. Open an issue with these five fields: what you asked; what came back; what you expected; which door; your Node and Python versions. Never paste private data or keys.

## License

MIT — see LICENSE.
