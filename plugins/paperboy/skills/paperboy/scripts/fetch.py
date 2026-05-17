#!/usr/bin/env python3
"""Paperboy fetch helper.

Reads sources.md from the vault, fetches each source according to its type,
diffs against per-source state, and emits new candidates as JSON on stdout.
Does not modify state.

Supported source types:
  - rss            : standard RSS 2.0 feed
  - 1440-sitemap   : 1440 newsletter; URL is a sitemap.xml that lists
                     /newsletter/<slug> pages with <lastmod> dates. Each newsletter
                     page is fetched and parsed into per-blurb candidates that
                     come pre-summarized with citation links.
  - reddit-sub     : a subreddit listing. URL is a subreddit page like
                     https://www.reddit.com/r/<sub>/ (defaults to top-of-day);
                     append /hot/, /new/, /rising/, /top/, or /controversial/
                     to override. fetch.py converts the URL to the corresponding
                     .json endpoint and parses each post. Reddit posts are
                     polymorphic (link / self-text / image / video); the
                     candidate's `url` is routed accordingly so WebFetch later
                     lands on a page worth summarizing.

Output schema:
  {
    "fetched_at": "<ISO 8601 UTC>",
    "vault": "<vault path>",
    "candidates": [
      {
        "source": "<slug>",
        "id": "<guid or synthetic>",
        "title": "<title>",
        "url": "<article URL>",
        "discussion_url": "<URL or absent>",   # set when the source has a discussion page
        "published": "<raw pubDate or ISO>",
        "pub_iso": "<ISO 8601 or null>",
        "description": "<summary or full body>",
        "pre_summarized": <bool>,              # absent or true; true means skip WebFetch
        "citations": [["<text>", "<url>"], ...] # absent unless pre_summarized
      },
      ...
    ],
    "errors": [ { "source": "<slug>", "error": "<message>" }, ... ]
  }
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

# Ensure sibling modules in this directory are importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
import parser_1440  # noqa: E402

VAULT = Path(os.environ.get("PAPERBOY_VAULT_DIR", os.path.expanduser("~/Documents/PaperboyVault")))
BACKFILL_DAYS = int(os.environ.get("PAPERBOY_BACKFILL_DAYS", "7"))
USER_AGENT = "Paperboy/1.1 (+https://github.com/anthropics/claude-code)"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
# RSS descriptions are only used as classifier signal (and as a fallback summary
# if WebFetch fails). Some feeds embed the full article body, which bloats the
# candidates JSON the agent ingests. Truncate to a dek-sized window. 1440
# pre-summarized blurbs go through a separate path and are NOT truncated.
RSS_DESC_MAX_CHARS = 600


def parse_sources_md(path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (active_sources, alternates, paywall_domains).

    Entries with type 'alternate' or 'paywall' are not scanned for news —
    they are passed through to the JSON output so the agent can consult them
    in the paywall-handling step.
    """
    sources, alternates, paywalls = [], [], []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or not line.startswith("-"):
            continue
        body = line[1:].strip()
        parts = [p.strip() for p in body.split("|")]
        if len(parts) < 3:
            continue
        entry = {"slug": parts[0], "url": parts[1], "type": parts[2]}
        if entry["type"] == "alternate":
            alternates.append(entry)
        elif entry["type"] == "paywall":
            paywalls.append(entry)
        else:
            sources.append(entry)
    return sources, alternates, paywalls


def _text(el, tag) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _truncate_desc(s: str) -> str:
    if len(s) <= RSS_DESC_MAX_CHARS:
        return s
    return s[:RSS_DESC_MAX_CHARS].rstrip() + "…"


def parse_rss(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        link = _text(item, "link")
        guid = _text(item, "guid") or link
        items.append({
            "id": guid,
            "title": _text(item, "title"),
            "url": link,
            "published": _text(item, "pubDate"),
            "description": _truncate_desc(_text(item, "description")),
        })
    return items


def parse_pub_date(s: str):
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_iso_date(s: str):
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {"seen_ids": [], "last_fetched_at": None}


def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_rss_source(source, seen, cutoff_dt, is_first_run):
    candidates, errors = [], []
    slug = source["slug"]
    try:
        xml_text = fetch_url(source["url"])
    except Exception as e:
        return [], [{"source": slug, "error": f"fetch: {e}"}]
    try:
        items = parse_rss(xml_text)
    except ET.ParseError as e:
        return [], [{"source": slug, "error": f"parse: {e}"}]

    for item in items:
        if not item["id"] or item["id"] in seen:
            continue
        pub = parse_pub_date(item["published"])
        if pub and pub < cutoff_dt:
            continue
        if is_first_run and pub is None:
            continue
        item["source"] = slug
        item["pub_iso"] = pub.isoformat() if pub else None
        # If the guid is itself a URL, treat it as the discussion page
        # (HN/Lobsters' guids are post URLs; CSM's are opaque hashes).
        if item["id"].startswith(("http://", "https://")):
            item["discussion_url"] = item["id"]
        candidates.append(item)
    return candidates, errors


def fetch_1440_sitemap_source(source, seen, cutoff_dt, is_first_run):
    candidates, errors = [], []
    slug = source["slug"]
    try:
        sitemap_xml = fetch_url(source["url"])
    except Exception as e:
        return [], [{"source": slug, "error": f"fetch sitemap: {e}"}]
    try:
        root = ET.fromstring(sitemap_xml)
    except ET.ParseError as e:
        return [], [{"source": slug, "error": f"parse sitemap: {e}"}]

    pages = []
    for url_el in root.findall(f"{SITEMAP_NS}url"):
        loc = (url_el.findtext(f"{SITEMAP_NS}loc") or "").strip()
        lastmod = (url_el.findtext(f"{SITEMAP_NS}lastmod") or "").strip()
        if "/newsletter/" not in loc:
            continue
        pub = parse_iso_date(lastmod)
        if pub is None:
            continue
        if pub < cutoff_dt:
            continue
        pages.append((loc, pub))

    pages.sort(key=lambda x: x[1], reverse=True)

    for page_url, pub in pages:
        try:
            page_html = fetch_url(page_url)
        except Exception as e:
            errors.append({"source": slug, "error": f"fetch {page_url}: {e}"})
            continue
        try:
            blurbs = parser_1440.extract_newsletter_blurbs(page_html)
        except Exception as e:
            errors.append({"source": slug, "error": f"parse {page_url}: {e}"})
            continue

        page_slug = page_url.rstrip("/").rsplit("/", 1)[-1]
        for b in blurbs:
            cid = f"{page_slug}:{b['blurb_slug']}"
            if cid in seen:
                continue
            cand = {
                "source": slug,
                "id": cid,
                "title": b["title"],
                "url": page_url,
                "discussion_url": page_url,
                "published": pub.isoformat(),
                "pub_iso": pub.isoformat(),
                "description": b["description"],
                "pre_summarized": True,
                "citations": b["citations"],
            }
            candidates.append(cand)

    return candidates, errors


REDDIT_LISTINGS = ("top", "hot", "new", "rising", "controversial")
REDDIT_TIMED_LISTINGS = ("top", "controversial")
REDDIT_MEDIA_DOMAINS = ("i.redd.it", "v.redd.it", "i.imgur.com", "imgur.com")


def _reddit_json_url(url: str) -> str:
    """Convert a subreddit listing URL into its .json equivalent.

    Examples:
      .../r/Foo/top/    → .../r/Foo/top.json?t=day&limit=25
      .../r/Foo/hot/    → .../r/Foo/hot.json?limit=25
      .../r/Foo/        → .../r/Foo/top.json?t=day&limit=25  (default)
      .../r/Foo/x.json? → returned as-is
    """
    base = url.split("?", 1)[0].rstrip("/")
    if base.endswith(".json"):
        return url
    last_seg = base.rsplit("/", 1)[-1]
    if last_seg in REDDIT_LISTINGS:
        suffix = "?t=day&limit=25" if last_seg in REDDIT_TIMED_LISTINGS else "?limit=25"
        return base + ".json" + suffix
    return base + "/top.json?t=day&limit=25"


def _reddit_is_media_post(post_hint: str, is_video: bool, domain: str) -> bool:
    if post_hint in ("image", "rich:video", "hosted:video"):
        return True
    if is_video:
        return True
    if domain in REDDIT_MEDIA_DOMAINS:
        return True
    return False


def parse_reddit_listing(json_text: str) -> list[dict]:
    data = json.loads(json_text)
    children = data.get("data", {}).get("children", [])
    items = []
    for c in children:
        d = c.get("data", {}) or {}
        if d.get("stickied") or d.get("removed_by_category"):
            continue
        post_id = d.get("name") or d.get("id")
        permalink = d.get("permalink") or ""
        if not post_id or not permalink:
            continue

        title = d.get("title") or ""
        discussion_url = "https://www.reddit.com" + permalink
        old_url = "https://old.reddit.com" + permalink

        is_self = bool(d.get("is_self"))
        domain = d.get("domain") or ""
        post_hint = d.get("post_hint") or ""
        is_video = bool(d.get("is_video"))
        external_url = d.get("url") or ""

        # Route the candidate's `url` to whatever WebFetch can actually
        # summarize. Self / image / video / reddit-hosted media posts have
        # nothing meaningful at an external URL, so we point at old.reddit.com
        # (more scrape-friendly than the JS-heavy new UI). External link posts
        # keep their linked URL.
        if is_self or domain.startswith("self.") or _reddit_is_media_post(post_hint, is_video, domain):
            article_url = old_url
        else:
            article_url = external_url or old_url

        # Description gives the classifier its body signal. For self-posts the
        # selftext IS the post; include a preview alongside the title.
        selftext = (d.get("selftext") or "").strip()
        description = f"{title}\n\n{selftext}" if (is_self and selftext) else title

        created = d.get("created_utc")
        try:
            pub_iso = (
                datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
                if created else None
            )
        except (TypeError, ValueError):
            pub_iso = None

        items.append({
            "id": post_id,
            "title": title,
            "url": article_url,
            "discussion_url": discussion_url,
            "published": pub_iso or "",
            "pub_iso": pub_iso,
            "description": _truncate_desc(description),
        })
    return items


def fetch_reddit_source(source, seen, cutoff_dt, is_first_run):
    candidates, errors = [], []
    slug = source["slug"]
    json_url = _reddit_json_url(source["url"])
    try:
        json_text = fetch_url(json_url)
    except Exception as e:
        return [], [{"source": slug, "error": f"fetch: {e}"}]
    try:
        items = parse_reddit_listing(json_text)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        return [], [{"source": slug, "error": f"parse: {e}"}]

    for item in items:
        if item["id"] in seen:
            continue
        pub = parse_iso_date(item.get("pub_iso"))
        if pub and pub < cutoff_dt:
            continue
        if is_first_run and pub is None:
            continue
        item["source"] = slug
        candidates.append(item)
    return candidates, errors


SOURCE_HANDLERS = {
    "rss": fetch_rss_source,
    "1440-sitemap": fetch_1440_sitemap_source,
    "reddit-sub": fetch_reddit_source,
}


def main() -> int:
    if not VAULT.exists():
        print(f"ERROR: Vault not found at {VAULT}", file=sys.stderr)
        return 1
    sources_md = VAULT / "sources.md"
    if not sources_md.exists():
        print(f"ERROR: {sources_md} not found — run init.py first", file=sys.stderr)
        return 1
    state_dir = VAULT / "state"
    state_dir.mkdir(exist_ok=True)

    cutoff = datetime.now(timezone.utc) - timedelta(days=BACKFILL_DAYS)
    candidates: list[dict] = []
    errors: list[dict] = []

    sources, alternates, paywall_domains = parse_sources_md(sources_md)

    for source in sources:
        slug = source["slug"]
        handler = SOURCE_HANDLERS.get(source.get("type", "rss"))
        if handler is None:
            errors.append({"source": slug, "error": f"unsupported type: {source.get('type')}"})
            continue

        state = load_state(state_dir / f"{slug}.json")
        seen = set(state.get("seen_ids", []))
        is_first_run = not seen

        cands, errs = handler(source, seen, cutoff, is_first_run)
        candidates.extend(cands)
        errors.extend(errs)

    candidates.sort(key=lambda c: c["pub_iso"] or "", reverse=True)

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "vault": str(VAULT),
        "candidates": candidates,
        "errors": errors,
        "alternates": alternates,
        "paywall_domains": paywall_domains,
    }
    json.dump(result, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
