#!/bin/sh
# Key hook for the skill finder: search.sh runs it for every live search. With TYPESAFE_API_KEY
# in the environment it does nothing; otherwise it asks the provider command for the key.
# With no key and no provider (or a failing one) it falls back to --local-only and says so on stderr.
# See ENV-CONTRACT.md for the exact contract.
set -u
for arg in "$@"; do
  if [ "$arg" = "--local-only" ]; then
    exec bash "$(dirname "$0")/../launcher.sh" "$@"
  fi
done
LOCAL_NOTE='skill-search: no TypeSafe key, so this is a local-only ranking (unverified guesses)'
local_only() { printf '%s\n' "$LOCAL_NOTE" >&2; exec bash "$(dirname "$0")/../launcher.sh" "$@" --local-only; }
PROVIDER="${SKILL_SEARCH_PROVIDER_CMD:-}"
if [ -z "${TYPESAFE_API_KEY:-}" ]; then
  [ -n "$PROVIDER" ] || local_only "$@"
  KEY="$($PROVIDER 2>/dev/null)" || local_only "$@"
  [ -n "$KEY" ] || local_only "$@"
  TYPESAFE_API_KEY="$KEY"; export TYPESAFE_API_KEY
fi
exec bash "$(dirname "$0")/../launcher.sh" "$@"
