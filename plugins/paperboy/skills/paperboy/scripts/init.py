#!/usr/bin/env python3
"""Seed a Paperboy vault with starter interests.md, sources.md, and dirs.

Idempotent: never overwrites existing files. Safe to re-run.
Seed templates live in ../seeds/ alongside this script's parent directory.
"""
import os
import sys
from pathlib import Path

VAULT = Path(os.environ.get("PAPERBOY_VAULT_DIR", os.path.expanduser("~/Documents/PaperboyVault")))
SEEDS = Path(__file__).resolve().parent.parent / "seeds"


def write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content)
    return True


def main() -> int:
    VAULT.mkdir(parents=True, exist_ok=True)
    (VAULT / "state").mkdir(exist_ok=True)
    (VAULT / "feed").mkdir(exist_ok=True)

    created = []
    for filename in ("interests.md", "sources.md"):
        seed_path = SEEDS / filename
        if not seed_path.exists():
            print(f"ERROR: seed file missing: {seed_path}", file=sys.stderr)
            return 1
        if write_if_missing(VAULT / filename, seed_path.read_text()):
            created.append(filename)

    print(f"Vault at: {VAULT}")
    if created:
        print(f"Created: {', '.join(created)}")
    else:
        print("Vault already initialized — no files changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
