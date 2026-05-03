#!/usr/bin/env python3
"""Paperboy finalize helper.

Accepts JSON on stdin (or a file path as argv[1]) mapping source slug to the
list of item IDs to mark seen. Merges into state/<slug>.json, caps each seen
list to the most recent SEEN_CAP entries, and updates last_fetched_at.

Input schema:
  { "<source-slug>": ["id1", "id2", ...], ... }
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("PAPERBOY_VAULT_DIR", os.path.expanduser("~/Documents/PaperboyVault")))
SEEN_CAP = int(os.environ.get("PAPERBOY_SEEN_CAP", "2000"))


def main() -> int:
    state_dir = VAULT / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) > 1:
        payload = json.loads(Path(sys.argv[1]).read_text())
    else:
        payload = json.loads(sys.stdin.read())

    now = datetime.now(timezone.utc).isoformat()
    for slug, ids in payload.items():
        path = state_dir / f"{slug}.json"
        state = {"seen_ids": [], "last_fetched_at": None}
        if path.exists():
            try:
                state = json.loads(path.read_text())
            except json.JSONDecodeError:
                pass

        seen = list(state.get("seen_ids", []))
        existing = set(seen)
        for i in ids:
            if i and i not in existing:
                seen.append(i)
                existing.add(i)
        if len(seen) > SEEN_CAP:
            seen = seen[-SEEN_CAP:]

        state["seen_ids"] = seen
        state["last_fetched_at"] = now
        path.write_text(json.dumps(state, indent=2))
        print(f"{slug}: {len(seen)} seen ids", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
