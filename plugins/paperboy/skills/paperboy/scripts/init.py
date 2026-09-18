#!/usr/bin/env python3
"""Seed and migrate a Paperboy vault.

Two jobs, both idempotent and both safe to run on every invocation:

  seed     Create the vault dirs and copy starter interests.md / sources.md
           from ../seeds/. Existing files are never overwritten.

  migrate  Bring an already-initialized vault up to the current schema by
           APPENDING sections it is missing. A vault initialized before v1.2
           never received the `alternate` / `paywall` source sections, and
           because seeding refuses to overwrite, the paywall feature sat inert
           with no signal. --migrate closes that gap without touching anything
           the user has written.

Usage:
    python3 init.py              # seed only (first run)
    python3 init.py --migrate    # seed, then append any missing schema sections
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

VAULT = _common.VAULT
SEEDS = Path(__file__).resolve().parent.parent / "seeds"

# Heading -> the source `type` whose presence means the section already exists.
MIGRATIONS = [
    ("## Preferred alternates", "alternate"),
    ("## Paywalled sites", "paywall"),
]


def write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content)
    return True


def declared_types(text: str) -> set[str]:
    """Source types actually present as entries in a sources.md."""
    types = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        parts = [p.strip().strip("`") for p in line[1:].strip().split("|")]
        if len(parts) >= 3:
            types.add(parts[2])
    return types


def section_of(text: str, heading: str) -> str:
    """Return `heading` and everything under it, up to the next '## ' heading."""
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == heading)
    except StopIteration:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end]).rstrip()


def migrate_sources(vault_sources: Path, seed_sources: Path) -> list[str]:
    """Append any schema sections the vault's sources.md is missing."""
    if not vault_sources.exists() or not seed_sources.exists():
        return []

    current = vault_sources.read_text()
    seed = seed_sources.read_text()
    present = declared_types(current)

    additions = []
    for heading, type_name in MIGRATIONS:
        if type_name in present:
            continue
        block = section_of(seed, heading)
        if not block:
            print(f"paperboy: WARNING [migrate] seeds/sources.md has no {heading!r} "
                  f"section; cannot migrate '{type_name}'", file=sys.stderr)
            continue
        additions.append((heading, type_name, block))

    if not additions:
        return []

    parts = [current.rstrip(), ""]
    for heading, type_name, block in additions:
        parts.append("")
        parts.append(f"<!-- added by paperboy init.py --migrate (v{_common.version()}) -->")
        parts.append(block)
        parts.append("")
    vault_sources.write_text("\n".join(parts).rstrip() + "\n")
    return [f"{heading} ({type_name})" for heading, type_name, _ in additions]


def main() -> int:
    do_migrate = "--migrate" in sys.argv[1:]

    VAULT.mkdir(parents=True, exist_ok=True)
    (VAULT / "state").mkdir(exist_ok=True)
    (VAULT / "feed").mkdir(exist_ok=True)

    created = []
    for filename in ("interests.md", "sources.md"):
        seed_path = SEEDS / filename
        if not seed_path.exists():
            print(f"paperboy: ERROR [config] init: seed file missing: {seed_path}",
                  file=sys.stderr)
            return 1
        if write_if_missing(VAULT / filename, seed_path.read_text()):
            created.append(filename)

    print(f"Vault at: {VAULT}")
    if created:
        print(f"Created: {', '.join(created)}")
    else:
        print("Vault already initialized — no files created.")

    if do_migrate:
        added = migrate_sources(VAULT / "sources.md", SEEDS / "sources.md")
        if added:
            print(f"Migrated sources.md — appended: {', '.join(added)}")
            print("Review the appended sections and edit them to taste.")
        else:
            print("sources.md schema is current — nothing to migrate.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
