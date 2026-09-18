#!/usr/bin/env python3
"""Shared helpers for the Paperboy scripts.

Keeps vault resolution, versioning, URL hygiene, and state I/O in one place so
fetch.py / init.py / finalize.py cannot drift apart.
"""
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

FALLBACK_VERSION = "1.3.0"
REPO_URL = "https://github.com/rezrov/claude-marketplace"
ISSUES_URL = f"{REPO_URL}/issues"
# Paperboy runs as a Claude Code plugin, and the UA says so. Both URLs are
# accurate: the first is where this code lives, the second is the runtime it
# runs under. Do not simplify this string without testing every configured
# source -- at least one publisher varies its response by user-agent, and a
# "cleaner" UA has silently taken a source offline before. See GOALS.md,
# "User-Agent and publisher identification". We never spoof a browser UA.
CLAUDE_CODE_URL = "https://github.com/anthropics/claude-code"

VAULT = Path(os.environ.get("PAPERBOY_VAULT_DIR", os.path.expanduser("~/Documents/PaperboyVault")))
STATE_DIR = VAULT / "state"
DEFAULT_MANIFEST = os.environ.get("PAPERBOY_MANIFEST", "/tmp/paperboy-manifest.json")


def version() -> str:
    """Read the plugin version from plugin.json so the UA never drifts."""
    try:
        p = Path(__file__).resolve().parents[3] / ".claude-plugin" / "plugin.json"
        v = json.loads(p.read_text()).get("version")
        if v:
            return str(v)
    except Exception:
        pass
    return FALLBACK_VERSION


def user_agent() -> str:
    return (f"Paperboy/{version()} (Claude Code plugin; "
            f"+{REPO_URL}; +{CLAUDE_CODE_URL})")


# --- URL hygiene -------------------------------------------------------------

# Query keys that are pure tracking noise. Anything matching a prefix in
# TRACKING_PREFIXES or present in TRACKING_KEYS is dropped from article URLs so
# the digest links stay clean and the dedup key stays stable.
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "_hs")
TRACKING_KEYS = {
    "fbclid", "gclid", "gbraid", "wbraid", "msclkid", "dclid", "yclid",
    "igshid", "mc_cid", "mc_eid", "ref_src", "ref_url", "cmpid", "cmp",
    "sref", "smid", "partner", "at_medium", "at_campaign",
}


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k in TRACKING_KEYS or k.startswith(TRACKING_PREFIXES)


def strip_tracking(url: str) -> str:
    """Remove tracking query params, preserving everything else verbatim."""
    if not url or not url.startswith(("http://", "https://")):
        return url
    try:
        s = urlsplit(url)
    except ValueError:
        return url
    if not s.query:
        return url
    kept = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True) if not _is_tracking(k)]
    return urlunsplit((s.scheme, s.netloc, s.path, urlencode(kept), s.fragment))


def host_of(url: str) -> str:
    """Lowercased host with a leading 'www.' removed. '' when unparseable."""
    try:
        return urlsplit(url).netloc.lower().split("@")[-1].split(":")[0].removeprefix("www.")
    except ValueError:
        return ""


def dedup_key(url: str) -> str:
    """Normalized identity for an article URL: host + path + meaningful query.

    Tracking params are already gone via strip_tracking; the remaining query is
    sorted so param order can't split a duplicate pair. Fragments are dropped.
    """
    if not url:
        return ""
    cleaned = strip_tracking(url)
    try:
        s = urlsplit(cleaned)
    except ValueError:
        return cleaned.lower()
    host = host_of(cleaned)
    path = s.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(s.query, keep_blank_values=True)))
    return f"{host}{path}?{query}" if query else f"{host}{path}"


# --- state I/O ---------------------------------------------------------------

def load_state(path: Path, warnings: list) -> dict:
    """Load a per-source state file.

    A corrupt state file used to be swallowed silently, which silently reset
    seen_ids and re-flooded the next digest with old items. Now it warns.
    """
    empty = {"seen_ids": [], "last_fetched_at": None}
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        warnings.append({
            "kind": "state-corrupt",
            "source": path.stem,
            "message": (
                f"state file {path.name} is unreadable ({e.__class__.__name__}); "
                "treating this source as never-fetched, which may resurface old items"
            ),
        })
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("seen_ids"), list):
        warnings.append({
            "kind": "state-corrupt",
            "source": path.stem,
            "message": f"state file {path.name} has an unexpected shape; treating as never-fetched",
        })
        return empty
    return data


def emit_warnings(warnings: list, errors: list = None) -> None:
    """Print human-readable warnings/errors to stderr.

    stderr is the channel the agent sees in its tool result, and the agent is
    required to relay these into its final report (which is what the runner's
    ntfy notification actually captures).
    """
    for e in errors or []:
        print(f"paperboy: ERROR [{e.get('kind', 'unknown')}] {e.get('source', '?')}: "
              f"{e.get('message', '')}", file=sys.stderr)
    for w in warnings:
        print(f"paperboy: WARNING [{w.get('kind', 'unknown')}] "
              f"{w.get('source') or 'vault'}: {w.get('message', '')}", file=sys.stderr)
