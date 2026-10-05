#!/usr/bin/env python3
"""Super Clef has no TypeSafe retrieval or navigation provider (no key, no paid calls). The memory runtime
runs this where Super Jev's config named its Jev provider; it says so and makes no call. Sets that have a
prepare-cache are searched by the word search and the clef judge instead; a set with none is reported as not
searched, never as not found."""
import json
import sys

sys.stdin.read()
print(json.dumps({"status": "error", "kind": "unknown",
                  "reason": "Super Clef has no TypeSafe provider (no key, no paid calls); this set has no prepared file list to search"}))
