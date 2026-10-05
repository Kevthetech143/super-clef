# Key hook contract — skill-search

The launcher and the generic super-jev runtime are secret-free: they never
read a secret file, never invoke a provider, never place a key in argv or
logs, and never print any `*KEY*` value. The model key for live search
reaches the runtime ONLY through environment inheritance: the launcher's
`subprocess.Popen` call passes its own environment to the child unchanged,
so a key exported before the launcher runs arrives at the runtime with no
launcher-side secret handling at all.

This directory holds the exact contract for supplying that key from a place
the shell cannot reach (a hook, a scheduler), plus the implementation
(`hook-wrapper.sh`). `search.sh` always runs a live search through the
wrapper. When `TYPESAFE_API_KEY` is already in the environment the wrapper does
nothing and the launcher runs at once; the secret-free launcher never
references the wrapper.

## Contract (exact)

1. The wrapper exports `TYPESAFE_API_KEY` into the ENVIRONMENT ONLY.
   The key must never appear in argv, in logs, or on stdout.
2. Inherited environment wins: if `TYPESAFE_API_KEY` is already set when the
   wrapper runs, the wrapper MUST NOT call the provider and MUST NOT
   overwrite the value.
3. No key, no provider, or a failing/empty provider: the wrapper runs the
   launcher with `--local-only`, prints the stderr note
   (`no TypeSafe key ... local-only`) only when `SKILL_SEARCH_VERBOSE=1`, and exits 0 with status `suggestions`
   and source `local`. It never claims a live search.
4. No keyless live claim: without a key in the environment, the runtime
   reports `fallback` honestly. A fallback is never a
   successful live search.
5. `--local-only` never needs a provider or a key. The launcher never
   invokes any provider command itself, on any flag combination.
6. No CA environment is required by this wiring. If a deployment's provider
   endpoint needs a private CA, add the site's usual CA variables
   (e.g. `SSL_CERT_FILE`) inside the deployment wrapper only.

## Provider command

`hook-wrapper.sh` reads the provider command from `SKILL_SEARCH_PROVIDER_CMD`
(e.g. `/usr/local/bin/my-provider api-key`). When that is unset and the key is
not in the environment, `search.sh` defaults it to
`deploy/local-key-provider.py` if that file exists on this machine (it is
gitignored and never shipped; copy `key-provider.example.py` to it). An
explicitly configured provider wins. With no key, no provider variable and
no such file, or a provider that fails or prints an empty key, the wrapper runs
the launcher with `--local-only`, prints the one-line stderr note and exits 0
(status `suggestions`, source `local`). The wrapper `exec`s the launcher so the
environment — including the key — is inherited, never re-typed.

## Verification (fake provider fixture)

- env reaches the child: `TYPESAFE_API_KEY=FAKE-...` exported before the
  launcher is visible to the fake runtime's environment.
- inherited precedence: pre-set `TYPESAFE_API_KEY` beats the provider's
  output; unset key falls back to the provider.
- provider failure: nonzero/empty provider output (or no key, no provider) ->
  the launcher runs with `--local-only`, one stderr note, exit 0, status
  `suggestions`, source `local`, never a live claim.
- no secret in outputs: the fake key value appears nowhere on stdout,
  stderr, or in any file the launcher/runtime writes.
- `--local-only` with no key and no provider configured completes against
  the local path.
