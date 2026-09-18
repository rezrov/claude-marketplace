#!/usr/bin/env python3
"""Paperboy finalize helper.

Commits the run: marks every fetched item ID as seen, and records the stories
that were kept (or suppressed as repeats) so later runs can recognise them.

Seen IDs come from the manifest fetch.py wrote -- the agent does not have to
echo ~150 opaque IDs back, which keeps them out of the context window and
removes a class of transcription bug.

Usage:
    python3 finalize.py                       # manifest only
    echo '{"stories":[...]}' | finalize.py    # manifest + story ledger
    python3 finalize.py --manifest PATH
    echo '{"seen":{"slug":["id"]},"stories":[...]}' | finalize.py   # explicit

Stdin schema (all keys optional):
  {
    "seen":    { "<source-slug>": ["id", ...] },   # merged with the manifest
    "stories": [ { "key": "<stable-slug>",         # reused across days
                   "headline": "<short headline>",
                   "gist": "<<=15 words: what happened>",
                   "status": "kept" | "repeat" }, ... ]
  }

A bare { "<slug>": [ids] } map is still accepted for backward compatibility.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

VAULT = _common.VAULT
SEEN_CAP = int(os.environ.get("PAPERBOY_SEEN_CAP", "2000"))
STORY_RETENTION_DAYS = int(os.environ.get("PAPERBOY_STORY_RETENTION_DAYS", "30"))


def read_stdin_payload(warnings):
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        warnings.append({"kind": "bad-stdin", "source": "finalize",
                         "message": f"stdin was not valid JSON ({e}); ignoring it"})
        return {}
    if not isinstance(data, dict):
        warnings.append({"kind": "bad-stdin", "source": "finalize",
                         "message": "stdin JSON was not an object; ignoring it"})
        return {}
    # Legacy shape: a bare {slug: [ids]} map with no "seen"/"stories" keys.
    if "seen" not in data and "stories" not in data:
        return {"seen": data, "stories": []}
    return data


def load_manifest(path: Path, warnings) -> dict:
    if not path.exists():
        warnings.append({
            "kind": "manifest-missing", "source": "finalize",
            "message": f"manifest {path} not found; only IDs piped in via stdin "
                       "will be marked seen (items may resurface next run)",
        })
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        warnings.append({"kind": "manifest-corrupt", "source": "finalize",
                         "message": f"manifest {path} unreadable ({e})"})
        return {}
    return data if isinstance(data, dict) else {}


def merge_seen(seen_map: dict, warnings) -> list[str]:
    """Merge new IDs into each per-source state file. Returns report lines."""
    state_dir = _common.STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    report = []

    for slug, ids in sorted(seen_map.items()):
        if not isinstance(ids, list):
            warnings.append({"kind": "bad-input", "source": slug,
                             "message": "seen entry was not a list; skipped"})
            continue
        path = state_dir / f"{slug}.json"
        state = _common.load_state(path, warnings)

        seen = list(state.get("seen_ids", []))
        existing = set(seen)
        added = 0
        for i in ids:
            if i and i not in existing:
                seen.append(i)
                existing.add(i)
                added += 1
        if len(seen) > SEEN_CAP:
            seen = seen[-SEEN_CAP:]

        state["seen_ids"] = seen
        state["last_fetched_at"] = now
        try:
            path.write_text(json.dumps(state, indent=2))
        except OSError as e:
            warnings.append({"kind": "state-write-failed", "source": slug,
                             "message": f"could not write {path.name} ({e}); "
                                        "these items will resurface next run"})
            continue
        report.append(f"{slug}: +{added} new, {len(seen)} seen total")
    return report


def merge_stories(stories: list, warnings) -> str:
    """Update the rolling story ledger used for cross-day repeat detection."""
    path = _common.STATE_DIR / "stories.json"
    today = datetime.now(timezone.utc).date().isoformat()

    ledger = {"updated_at": None, "stories": []}
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict) and isinstance(loaded.get("stories"), list):
                ledger = loaded
            else:
                warnings.append({"kind": "state-corrupt", "source": "stories",
                                 "message": "stories.json had an unexpected shape; rebuilding it"})
        except (json.JSONDecodeError, OSError) as e:
            warnings.append({"kind": "state-corrupt", "source": "stories",
                             "message": f"stories.json unreadable ({e}); rebuilding it"})

    by_key = {s["key"]: s for s in ledger["stories"] if isinstance(s, dict) and s.get("key")}

    added = updated = 0
    for s in stories:
        if not isinstance(s, dict) or not s.get("key"):
            warnings.append({"kind": "bad-input", "source": "stories",
                             "message": f"story entry missing 'key'; skipped: {s!r}"[:200]})
            continue
        key = s["key"]
        if key in by_key:
            e = by_key[key]
            e["last_seen"] = today
            e["times_seen"] = int(e.get("times_seen", 1)) + 1
            # Refresh the human-readable fields; the newest phrasing is the
            # one most likely to match tomorrow's coverage.
            if s.get("headline"):
                e["headline"] = s["headline"]
            if s.get("gist"):
                e["gist"] = s["gist"]
            updated += 1
        else:
            by_key[key] = {
                "key": key,
                "headline": s.get("headline", ""),
                "gist": s.get("gist", ""),
                "first_seen": today,
                "last_seen": today,
                "times_seen": 1,
            }
            added += 1

    cutoff = (datetime.now(timezone.utc) - timedelta(days=STORY_RETENTION_DAYS)).date().isoformat()
    kept = [s for s in by_key.values() if (s.get("last_seen") or "") >= cutoff]
    pruned = len(by_key) - len(kept)
    kept.sort(key=lambda s: s.get("last_seen") or "", reverse=True)

    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    ledger["stories"] = kept
    try:
        path.write_text(json.dumps(ledger, indent=2))
    except OSError as e:
        warnings.append({"kind": "state-write-failed", "source": "stories",
                         "message": f"could not write stories.json ({e}); cross-day "
                                    "repeat detection will not see this run"})
        return "stories: WRITE FAILED"
    return (f"stories: +{added} new, {updated} updated, {pruned} pruned, "
            f"{len(kept)} tracked")


def main() -> int:
    warnings: list[dict] = []

    manifest_path = Path(_common.DEFAULT_MANIFEST)
    argv = sys.argv[1:]
    if argv and argv[0] == "--manifest" and len(argv) > 1:
        manifest_path = Path(argv[1])
        argv = argv[2:]
    elif argv and not argv[0].startswith("-"):
        # Backward compatibility: a bare path argument was a JSON payload file.
        payload_file = Path(argv[0])
        try:
            data = json.loads(payload_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"paperboy: ERROR [config] finalize: cannot read {payload_file} ({e})",
                  file=sys.stderr)
            return 1
        seen_map = data if ("seen" not in data and "stories" not in data) else data.get("seen", {})
        for line in merge_seen(seen_map, warnings):
            print(f"paperboy: {line}", file=sys.stderr)
        print(f"paperboy: {merge_stories(data.get('stories', []), warnings)}", file=sys.stderr)
        _common.emit_warnings(warnings)
        return 0

    payload = read_stdin_payload(warnings)

    seen_map = load_manifest(manifest_path, warnings)
    for slug, ids in (payload.get("seen") or {}).items():
        seen_map.setdefault(slug, [])
        if isinstance(ids, list):
            seen_map[slug].extend(ids)

    if not seen_map:
        warnings.append({"kind": "nothing-to-commit", "source": "finalize",
                         "message": "no seen IDs found in the manifest or on stdin; "
                                    "nothing was marked seen"})

    for line in merge_seen(seen_map, warnings):
        print(f"paperboy: {line}", file=sys.stderr)

    print(f"paperboy: {merge_stories(payload.get('stories') or [], warnings)}", file=sys.stderr)

    _common.emit_warnings(warnings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
