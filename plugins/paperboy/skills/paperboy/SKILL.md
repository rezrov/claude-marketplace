---
name: paperboy
description: Fetch, filter, and summarize news/articles from configured RSS sources into a daily markdown digest in an Obsidian vault. Trigger with "fetch my newspaper", "run paperboy", "check my feed".
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/*) Bash(python3 *) Bash(date *) Bash(mkdir *) Bash(test *) Bash(ls *) Bash(grep *) Bash(find *) Bash(awk *) Bash(wc *) Bash(cat *) Bash(echo *) Bash(basename *) Bash(open obsidian://*) Read Write WebFetch
---

## What I do

I fetch news from the user's configured sources (RSS feeds and the 1440 daily newsletter), filter items against the user's stated interests, summarize the keepers, and write a single markdown digest file into an Obsidian vault. The vault holds the interests file, the source list, per-source state (seen item IDs), and all digest output — nothing lives outside it.

### Source types

- `rss` — standard RSS 2.0 feed; one candidate per `<item>`.
- `1440-sitemap` — the 1440 daily newsletter; URL points to a sitemap.xml. fetch.py walks the sitemap, fetches each newsletter page in the backfill window, and parses the "Need To Know" section into per-blurb candidates. These candidates come **pre-summarized** with inline citation links to the underlying source articles, so Step 6 (summarize) is short-circuited for them.
- `reddit-sub` — a subreddit listing. URL is a subreddit page (e.g., `https://www.reddit.com/r/<sub>/`); fetch.py converts it to the equivalent `.json` endpoint and parses each post as a candidate. A bare subreddit URL defaults to top-of-day; users can override by appending a listing path (`/hot/`, `/new/`, `/rising/`, `/top/`, `/controversial/`). Reddit posts are polymorphic — fetch.py routes the `url` field to whatever WebFetch can actually summarize: external article for link posts; `old.reddit.com/<permalink>` for self-text, image, video, or reddit-hosted media posts. The user-facing reddit.com comments page is always exposed as `discussion_url`.

### Workflow

1. **Locate vault** at `$PAPERBOY_VAULT_DIR` (default `~/Documents/PaperboyVault`). If missing, run init to seed it.
2. **Fetch candidates** via `scripts/fetch.py` — returns JSON of new-to-us items across all sources.
3. **Classify** each candidate against `interests.md` using LLM judgment. Output keep/skip + one-line rationale.
4. **Summarize** each keeper by fetching the article URL via `WebFetch` and writing a 2-4 sentence summary.
5. **Write digest** to `feed/YYYY-MM-DD-HHMMSS.md`.
6. **Finalize state** via `scripts/finalize.py` — commits all fetched item IDs as "seen" so they won't resurface.

### Vault layout

```
$PAPERBOY_VAULT_DIR/
├── interests.md           # User's keep/skip rules — read at every run
├── sources.md             # Source list (slug | url | type)
├── state/
│   └── <source-slug>.json # Per-source: seen_ids[], last_fetched_at
└── feed/
    └── YYYY-MM-DD-HHMMSS.md  # One digest per invocation
```

## When to use me

- User says "fetch my newspaper", "run paperboy", "check my news feed", "what's new"
- User wants an LLM-filtered aggregation of their news sources
- If the request also includes a "show me" / "open it" / "show it to me" intent, also run Step 10 to open the vault in Obsidian

## How to use me

### Agent Instructions

Invoke these steps in order. `$CLAUDE_SKILL_DIR` is the skill's own directory.

#### Step 1 — Locate vault and (on first run) onboard

Resolve the vault path from `PAPERBOY_VAULT_DIR` (default `~/Documents/PaperboyVault`). The vault holds `interests.md`, `sources.md`, `state/`, and `feed/`.

Check for `<vault>/sources.md`. If it exists, the vault is initialized — proceed to Step 2.

**Otherwise, this is a first run.** Walk the user through setup before doing anything else:

1. Briefly state what paperboy will do (fetch configured sources, classify against their stated interests, write a digest into a vault).
2. Tell them the resolved vault path and the two env vars that influence behavior, with defaults:
   - `PAPERBOY_VAULT_DIR` (default `~/Documents/PaperboyVault`) — vault location. To use a different path, the user should set this env var and re-run.
   - `PAPERBOY_BACKFILL_DAYS` (default `7`) — lookback window: caps first-run pulls and rejects items older than this on every run. Most users leave it.
3. Note that paperboy is designed for **Obsidian** — link rendering and the optional "open it" step (Step 10) assume a vault opened there. **Obsidian is not required**, though: the digest is plain markdown and any markdown reader works. Step 10 is skipped automatically when the user hasn't asked to view the digest.
4. Run init:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/init.py"
   ```
   This copies seed `interests.md` and `sources.md` from `${CLAUDE_SKILL_DIR}/seeds/` into the vault and creates `state/` and `feed/`. It is idempotent — existing files are never overwritten, so the user can safely edit and re-run.
5. Tell the user where the vault was created, and **direct them to inspect and edit the two seed files to fit their tastes**:
   - `interests.md` — the keep/skip rules the classifier uses. The seed is intentionally generic; a tighter, more personal version produces a better feed.
   - `sources.md` — which feeds to pull from. The seed includes HN, Lobsters, Christian Science Monitor (USA + World), the 1440 newsletter, and one example subreddit. Add, remove, or reslug freely.
6. Ask whether to proceed now with the seeded defaults or pause while they edit. Do not run Step 2 until they confirm.

#### Step 2 — Fetch candidates

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/fetch.py" > /tmp/paperboy-candidates.json
```

The script prints a JSON object `{fetched_at, vault, candidates: [...], errors: [...]}` to stdout. Each candidate has: `source`, `id`, `title`, `url`, `published` (raw RFC 822 or ISO), `pub_iso` (ISO 8601 or null), `description`. Optional fields: `discussion_url` (set when the source has a discussion/landing page for the item), `pre_summarized` (true for 1440 blurbs — skip Step 6's WebFetch), `citations` (list of `[text, url]` pairs for pre-summarized items).

Read `/tmp/paperboy-candidates.json`. If `candidates` is empty, tell the user "Nothing new since the last run." Do not write a digest file or call finalize. Stop here.

If `errors` is non-empty, list the failing sources for the user but continue with whatever succeeded.

#### Step 3 — Load interests

```
Read $PAPERBOY_VAULT_DIR/interests.md
```

#### Step 4 — Dedup across sources

Before classifying, merge candidates that point to the same external article so each story is classified, summarized, and rendered **once** with a combined source list.

- **Match key**: the candidate's `url` field, normalized (lowercased host, trailing slash stripped, `?utm_*` and `#fragment` removed). Apply only to RSS-type candidates — never dedupe `pre_summarized` (1440) blurbs against anything; they're standalone curated entries even when topically overlapping.
- **When two or more candidates share a normalized URL**: collapse them into a single merged candidate.
  - **Keep**: the earliest known `pub_iso` (fall back to any non-null one), the longest non-empty `title`, and the longest non-empty `description`.
  - **Combine**: collect every contributing source's slug + `discussion_url` into a list on the merged candidate (e.g., `sources: [{slug: "hn-frontpage", discussion_url: "..."}, {slug: "lobsters-feed", discussion_url: "..."}]`). Preserve order: earliest `pub_iso` first.
  - **IDs**: remember every original `id` per source — finalize (Step 7) must mark them all seen so neither source resurfaces the article.
- The merged candidate flows through Steps 5–6 as one item: one classify decision, one summary, one digest entry. The **Source:** line in Step 6 then renders every contributing source separately, each linked to its own `discussion_url` (e.g., `[HN](hn-url), [Lobsters](lobsters-url)`), per the source-rendering rule below.

#### Step 5 — Classify candidates

Evaluate each candidate against the interests file. Prefer batching: send all candidates in a single prompt to yourself, returning one decision per candidate. For each candidate produce:

- `keep`: boolean
- `rationale`: one line (used for "Why this matched" if kept; internal note if skipped)

Marginal calls should err toward **skip** — the user prefers a tight feed over a noisy one. Political commentary, sensationalism, punditry, and thin rewrites are always skip unless `interests.md` explicitly says otherwise.

#### Step 6 — Summarize keepers

For each candidate where `keep` is true:

- **If `pre_summarized` is true** (1440 blurbs): skip WebFetch entirely. The `description` field IS the summary — copy it through verbatim into the digest. Do not re-summarize, do not paraphrase, do not trim.
- **Otherwise** (RSS items):
  1. Load `WebFetch` if not already available:
     ```
     ToolSearch(query="select:WebFetch")
     ```
  2. Fetch the article URL with this prompt (verbatim): `Read this article and return a 2-4 sentence neutral summary of its substantive content. Ignore navigation, ads, related links, and comments. Do not repeat the title and do not editorialize. If the page is paywalled and only a dek/excerpt is visible, briefly note that and summarize what is visible.`
  3. **Use WebFetch's response as the summary** — do not re-summarize it in the main context (the article body should never enter your context; that's the point). If the response is clearly malformed (well over 4 sentences, contains nav/UI cruft, or just echoes the title), trim/clean it once and move on; otherwise pass it through verbatim.
  4. If WebFetch fails outright (network error, 404, timeout), fall back to a 2-4 sentence summary written from the candidate's RSS `description` field and append " *(summary from feed description)*" to the end so the user knows the article wasn't reachable.

#### Step 7 — Write digest

Create `$PAPERBOY_VAULT_DIR/feed/YYYY-MM-DD-HHMMSS.md` where the timestamp is the current local time at invocation (fetch time, not content time). Use this structure:

```markdown
# Paperboy — YYYY-MM-DD HH:MM

Fetched N candidates across M sources, kept K.

---

## [Article Title](article-url)

**Source:** [<friendly-name>](<discussion-url>) · **Published:** YYYY-MM-DD HH:MM UTC (or "unknown")
**Why this matched:** <one-line rationale from classifier>

<2-4 sentence summary>

---

## [Next Article Title](url)
...
```

Order items: most recently published first; items with unknown publish date go at the end.

**Source rendering:**
- Render source slugs as friendly names: `hn-*` → `HN`, `lobsters-*` → `Lobsters`, `csm-*` → `CSM`, `1440` → `1440`, `reddit-*` → `r/<subreddit>` (extract `<subreddit>` from the candidate's `discussion_url`, which has the form `https://www.reddit.com/r/<sub>/comments/...` — preserve the original casing).
- If the candidate has a `discussion_url` field, link the friendly name to that URL: `[HN](https://news.ycombinator.com/item?id=...)`. (For HN/Lobsters this is the post's discussion page; for 1440 it's the newsletter page; for Reddit it's the comments page.)
- If `discussion_url` is absent (e.g., CSM), render the friendly name as plain text.
- For cross-source dedup entries covering the same article across multiple discussion sites, render each source separately, each linked to its own discussion page: `[HN](hn-url), [Lobsters](lobsters-url)`.

**Pre-summarized item rendering (1440):**
- The `description` already contains inline `[link text](url)` citations as part of the body — render it verbatim (do NOT rewrite the inline link text).
- After the body, append a `**Cited:**` line listing every entry in `citations`, but **replace each citation's link text with the URL's base domain** (registrable host, lowercased, with any leading `www.` stripped). The original citation text is discarded for this line. Example:
  - citation `["Acme announces foo", "https://www.news.com/articles/123.html"]` → renders as `[news.com](https://www.news.com/articles/123.html)`
  - citation `["report PDF", "https://reports.example.co.uk/x.pdf"]` → renders as `[reports.example.co.uk](https://reports.example.co.uk/x.pdf)`
- Join the rendered citations with ` · `:
  ```
  **Cited:** [news.com](url1) · [bbc.com](url2) · [reuters.com](url3)
  ```
- If multiple citations resolve to the same base domain, keep them all (do not dedupe) so each underlying source remains clickable.
- This gives the reader both the in-context links (with their descriptive text) and a quick-jump roster of all underlying sources by domain.

Also include a collapsed "Skipped" section at the bottom listing every skipped item by title + source + one-line rationale. This gives the user feedback on the filter so they can tune `interests.md`.

```markdown
## Skipped (X items)

- [<title>](<article-url>) — <source> — <rationale>
- ...
```

Use the candidate's `url` field for the link — same URL that would have been used if the item were kept.

#### Step 8 — Finalize state

Build a JSON object mapping each source slug to the list of ALL candidate IDs from that source (both kept and skipped — we don't want skipped items to resurface either). Pipe it to the finalize script:

```bash
echo '{"hn-frontpage": ["id1", "id2"], ...}' | python3 "${CLAUDE_SKILL_DIR}/scripts/finalize.py"
```

Finalize updates each `state/<slug>.json` with new seen IDs, caps seen lists to most recent 2000 per source, and records `last_fetched_at`.

#### Step 9 — Report to user

Tell the user:
- Where the digest was written (full path)
- Count of kept vs skipped
- Any source fetch errors

Do not open the file or summarize its contents — the user will read it in Obsidian.

#### Step 10 — Open the vault in Obsidian (conditional)

Run this step **only** if the user's request expressed intent to view the digest — phrasings like "show it to me", "show me", "open it", "and open it in Obsidian", "let me see it", etc. Skip otherwise.

Also skip if Step 2 produced no candidates (nothing to show) or if the digest was not written.

```bash
open "obsidian://open?vault=$(basename "${PAPERBOY_VAULT_DIR:-$HOME/Documents/PaperboyVault}")"
```

This launches/focuses Obsidian on the vault using its registered name (the vault's directory basename). The user can then navigate to the just-written `feed/YYYY-MM-DD-HHMMSS.md`. Do not attempt to open a specific file — `obsidian://open` with a `file=` parameter requires the file to already be indexed, and the vault may not have refreshed yet.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PAPERBOY_VAULT_DIR` | `~/Documents/PaperboyVault` | Obsidian vault root |
| `PAPERBOY_BACKFILL_DAYS` | `7` | Max lookback for backdated items; also first-run cap |

### Error Handling

- **Vault missing**: run init.py, offer to let user review seeds before continuing
- **Source fetch fails (network/parse)**: skip source, record in `errors[]`, continue — do not fail the run
- **Classifier output malformed**: re-prompt once, then skip that candidate with "classifier error" rationale
- **Article fetch fails**: fall back to RSS description; note "summary from feed description" in the digest
- **Digest write fails**: do NOT call finalize — next run will re-fetch the same items

### Notes

- **State is committed last, deliberately.** Crash-safe: if anything fails before the digest is written, the next run re-fetches the same items.
- **All fetched IDs get marked seen**, kept or skipped. The filter's job is to prevent resurfacing; tuning happens via `interests.md`.
- **Backfill window is a crawl bound, not a filter.** Items older than `PAPERBOY_BACKFILL_DAYS` that appear in a feed today are ignored — otherwise a source reshuffling its archive would flood the digest.
- **First run is capped** to items with a known publish date within the backfill window, to avoid dumping a source's entire feed on day one.
- **Dedup across sources**: HN and Lobsters often post the same external URL. If two candidates share a URL, keep the one with the earliest known publish date and note both sources in the digest entry. 1440 blurbs are NOT URL-deduped against RSS sources — they're a curated pre-summary that adds value even when overlapping topically.
- **Reddit posts are polymorphic.** fetch.py routes the candidate's `url` to whatever WebFetch can actually summarize: external sites for link posts, `old.reddit.com/<permalink>` for self-text/image/video posts (the discussion page is where the substance lives, and old.reddit is more scrape-friendly than the JS-heavy new UI). The agent does not need special handling — Step 6's WebFetch prompt asks for a 2–4 sentence summary regardless of payload shape. For image-only posts, the resulting summary may effectively describe the title plus what's visible on the page; that's the best available given a Reddit post that is itself just a picture.
- **No subagents.** Everything runs in the main context — fetches are cheap, classification benefits from the interests file being in context, summarization is per-item WebFetch + write.
- **Do not modify `interests.md` or `sources.md` automatically.** The user owns those files.
