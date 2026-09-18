---
name: paperboy
description: Fetch, filter, and summarize news/articles from configured RSS sources into a daily markdown digest in an Obsidian vault. Trigger with "fetch my newspaper", "run paperboy", "check my feed".
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/*) Bash(python3 *) Bash(date *) Bash(mkdir *) Bash(test *) Bash(ls *) Bash(grep *) Bash(find *) Bash(awk *) Bash(wc *) Bash(cat *) Bash(echo *) Bash(basename *) Bash(open obsidian://*) Read Write WebFetch WebSearch
---

## What I do

I fetch news from the user's configured sources (RSS feeds, the 1440 daily newsletter, subreddits), filter items against the user's stated interests, summarize the keepers, and write a single markdown digest file into an Obsidian vault. The vault holds the interests file, the source list, per-source state (seen item IDs), the story ledger, and all digest output — nothing lives outside it.

### Source types

- `rss` — standard RSS 2.0 feed; one candidate per `<item>`.
- `1440-sitemap` — the 1440 daily newsletter; URL points to a sitemap.xml. fetch.py walks the sitemap, fetches each newsletter page in the backfill window, and parses it into per-blurb candidates. Weekday editions use a "Need To Know" section; weekend editions use "One Big Headline" + "Quick Hits". Both are extracted. These candidates come **pre-summarized** with inline citation links to the underlying source articles, so Step 6 (summarize) is short-circuited for them.
- `reddit-sub` — a subreddit listing. URL is a subreddit page (e.g., `https://www.reddit.com/r/<sub>/`); fetch.py converts it to the equivalent `.json` endpoint and parses each post as a candidate. A bare subreddit URL defaults to top-of-day; users can override by appending a listing path (`/hot/`, `/new/`, `/rising/`, `/top/`, `/controversial/`). Reddit posts are polymorphic — fetch.py routes the `url` field to whatever WebFetch can actually summarize: external article for link posts, `old.reddit.com/<permalink>` for self-text, image, video, or reddit-hosted media posts. The user-facing reddit.com comments page is always exposed as `discussion_url`.
- `alternate` / `paywall` — not scanned. Passed through to Step 5 for paywall handling.

### Workflow

Step numbers below are the same ones used in "Agent Instructions"; there is no second numbering.

1. **Locate vault and migrate** — resolve `$PAPERBOY_VAULT_DIR`, seed on first run, apply schema migrations every run.
2. **Fetch candidates** via `scripts/fetch.py` — new-to-us items across all sources, already deduplicated by URL.
3. **Load interests** from the vault.
4. **Classify, cluster, and suppress repeats** — one pass: keep/skip against interests, group candidates covering the same story, and drop stories already covered on a previous day.
5. **Paywall handling** — swap paywalled URLs for a non-paywalled source covering the same story.
6. **Summarize** each keeper via `WebFetch`.
7. **Write digest** to `feed/YYYY-MM-DD-HHMMSS.md`.
8. **Finalize state** via `scripts/finalize.py` — marks fetched items seen and records the run's stories.
9. **Report to user** — including every warning verbatim.
10. **Open the vault in Obsidian** (only when the user asked to see it).

### Vault layout

```
$PAPERBOY_VAULT_DIR/
├── interests.md           # User's keep/skip rules — read at every run
├── sources.md             # Source list (slug | url | type)
├── state/
│   ├── <source-slug>.json # Per-source: seen_ids[], last_fetched_at
│   └── stories.json       # Rolling story ledger for cross-day repeat detection
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

#### Step 1 — Locate vault, seed, and migrate

Resolve the vault path from `PAPERBOY_VAULT_DIR` (default `~/Documents/PaperboyVault`).

Run this on **every** run — it is idempotent, never overwrites anything the user wrote, and is how existing vaults pick up schema additions from newer versions:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/init.py" --migrate
```

Then check whether `<vault>/sources.md` existed before this run. If the script printed `Created: ... sources.md`, **this is a first run** — walk the user through setup before doing anything else:

1. Briefly state what paperboy will do (fetch configured sources, classify against their stated interests, write a digest into a vault).
2. Tell them the resolved vault path and the env vars that influence behavior, with defaults (see Configuration below). Most users only ever set `PAPERBOY_VAULT_DIR`.
3. Note that paperboy is designed for **Obsidian** — link rendering and the optional "open it" step (Step 10) assume a vault opened there. **Obsidian is not required**, though: the digest is plain markdown and any markdown reader works.
4. **Direct them to inspect and edit the two seed files to fit their tastes**:
   - `interests.md` — the keep/skip rules the classifier uses. The seed is intentionally generic; a tighter, more personal version produces a better feed.
   - `sources.md` — which feeds to pull from. The seed includes HN, Lobsters, Christian Science Monitor (USA + World), the 1440 newsletter, one example subreddit, and the preferred-alternate / paywalled-site lists.
5. Ask whether to proceed now with the seeded defaults or pause while they edit. Do not run Step 2 until they confirm.

If the script printed `Migrated sources.md — appended: ...`, mention that in the Step 9 report so the user knows new sections are waiting for review.

#### Step 2 — Fetch candidates

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/fetch.py" > /tmp/paperboy-candidates.json
```

Read `/tmp/paperboy-candidates.json`. The JSON object contains:

- `counts` — `{sources_configured, sources_failed, raw_items, url_duplicates_merged, candidates}`. Use these verbatim in the digest header; do not recount.
- `candidates` — each has `n` (short handle; use this to refer to candidates in your own classify output), `title`, `url`, `sources` (a list of `{slug, discussion_url?}` — more than one entry means fetch.py already merged an exact-URL duplicate), `pub_iso`, `pub_precision` (`datetime` / `date` / `unknown`), `description`. Pre-summarized 1440 blurbs also carry `pre_summarized: true` and `citations` (list of `[text, url]` pairs).
- `recent_stories` — stories kept or suppressed within the last `PAPERBOY_STORY_WINDOW_DAYS`. Each has `key`, `headline`, `gist`, `first_seen`, `last_seen`, `times_seen`. Used in Step 4.
- `alternates` / `paywall_domains` — the user's `alternate` / `paywall` entries, used in Step 5.
- `errors` / `warnings` — see below.
- `manifest_path` — where fetch.py recorded every fetched item ID. Step 8 reads it directly; **you never need to handle item IDs yourself.**

**URL-level deduplication already happened.** fetch.py merges candidates sharing a normalized article URL (host/path/query, tracking params stripped) and combines their source lists. Do not attempt URL dedup again. 1440 blurbs are never URL-merged.

If `candidates` is empty, tell the user "Nothing new since the last run", relay any warnings, and stop. Do not write a digest file and do not call finalize.

**Handling `errors`.** Each entry is `{source, kind, message}`. `kind` is authoritative — do not re-infer it from the message text:

| `kind` | Meaning | What to do |
|---|---|---|
| `transient` | Network timeout, DNS failure, 5xx | Mention in the Step 9 report; likely fixes itself |
| `blocked` | Origin returned 401/403 | Mention in the report; the source may need replacing |
| `config` | 404/410 — the URL in `sources.md` looks wrong | Tell the user to check that source's URL |
| `unsupported` | paperboy's tooling can't handle this source | Collect the slug into `unsupported_sources`; Steps 7 and 9 point the user at <https://github.com/rezrov/claude-marketplace/issues> |

No error kind blocks the run — other sources continue regardless.

**Handling `warnings`.** Each entry is `{kind, source, message}`. Warnings are non-fatal but mean something is quietly degrading (a feed returning nothing, a corrupt state file, a 1440 template change, paywall handling sitting inactive). **Relay every warning verbatim in the Step 9 report.** Do not summarize them away — the user's runner ships that report to their phone, and this is the only way a silent degradation reaches them.

#### Step 3 — Load interests

```
Read $PAPERBOY_VAULT_DIR/interests.md
```

#### Step 4 — Classify, cluster, and suppress repeats

Do this as **one batched pass** over all candidates — a single prompt to yourself returning one decision per candidate. Batching matters: clustering requires seeing every candidate at once, and it is the cheapest way to run this.

For each candidate emit one line: `n | verdict | story-key | reason`

**Verdicts:**

- `keep` — passes the interests file, and is the **primary** entry for its story.
- `dup` — covers the same story as a `keep` in *this* run. Not summarized separately; rendered as an "Also covered" link under the primary.
- `repeat` — matches a `recent_stories` entry from a **previous** run and adds no material development. Not rendered as an article; listed in the Skipped section with the date it was first covered.
- `skip` — fails the interests file.

**`story-key`** is a short stable kebab-case slug naming the underlying event, not the headline — e.g. `fed-rate-hike-sept-2026`, `iran-houthi-red-sea`. Required for `keep`, `dup`, and `repeat`; use `-` for `skip`.

> **Reuse keys.** If a candidate matches a `recent_stories` entry, reuse that entry's exact `key`. This is what makes cross-day suppression work: a new key for the same story defeats it.

**Clustering (within this run).** Group candidates that cover the same underlying event even when their URLs differ — the same story routinely arrives from HN, Morning Brew, and 1440 on the same day. Give every member the same `story-key`. Then pick exactly one primary, in this order:

1. A candidate whose `url` points at original reporting (the outlet that did the work).
2. Otherwise a `pre_summarized` 1440 blurb (curated, already cited).
3. Otherwise the candidate with the longest `description`.

Mark the primary `keep` and every other member `dup`.

**Cross-day suppression.** Compare each would-be `keep` against `recent_stories`:

- Genuinely new information since `last_seen` — new facts, new numbers, an escalation, a resolution, an official response — is **`keep`**, and the reason must start with `follow-up:` so Step 7 renders the follow-up marker.
- A restatement, a recap, or another outlet covering the same beat with nothing added is **`repeat`**.
- When it is genuinely unclear whether there is new information, prefer `repeat`. The user wants a tight feed, and the Skipped section still shows it.

**`reason`:**

- `keep` → ≤12 words explaining the match; becomes "Why this matched". Prefix with `follow-up:` when suppression was overridden.
- `dup` → the `n` of the primary, e.g. `dup of 14`.
- `repeat` → `already covered YYYY-MM-DD` using the matched story's `first_seen`.
- `skip` → one code from `opinion`, `clickbait`, `politics-noise`, `sensational`, `off-topic`, `thin`, `promo`, `local`, `classifier-error`, optionally followed by `: ` and ≤8 clarifying words.

Marginal calls err toward **skip** — the user prefers a tight feed over a noisy one. Political commentary, sensationalism, punditry, and thin rewrites are always skip unless `interests.md` explicitly says otherwise.

Every candidate must receive exactly one verdict, so that `keep + dup + repeat + skip` equals `counts.candidates`. Step 7's header depends on that reconciling.

#### Step 5 — Detect paywalls and find alternates

For each `keep` where `pre_summarized` is **false** (1440 blurbs skip this step), check whether the article URL points to a paywalled site. If yes, look for the same story at a non-paywalled source and swap to it before summarizing.

If `paywall_domains` is empty, this step is inactive — skip it. fetch.py will have emitted a `no-paywall-config` warning; just relay it in Step 9.

**What counts as paywalled.** Extract each `paywall_domains` entry's host (lowercased, leading `www.` stripped — e.g. `nytimes.com`) into a set. A candidate is paywalled if its `url`, parsed the same way, matches one of these hosts exactly or as a subdomain (both `nytimes.com` and `cooking.nytimes.com` count).

**Preferred alternates.** `alternates` lists non-paywalled sources the user prefers. Extract their hosts the same way and treat the array order as preference order. If it is empty, pick from any non-paywalled result.

**Procedure** for each paywalled candidate:

1. Load `WebSearch` if not already available: `ToolSearch(query="select:WebSearch")`
2. Run `WebSearch` with the article's `title` as the query. If the title is fewer than 6 words or feels generic, append the most distinctive proper noun or phrase from the `description`. Ask for the top ~10 results.
3. Filter the results:
   - **Drop** any result whose host matches a paywall domain (including the original).
   - **Drop** aggregator/clickbait domains: `news.google.com`, `news.yahoo.com`, `flipboard.com`, `medium.com`, generic `*.substack.com` (unless the user listed that subdomain as an alternate).
4. From the remainder, pick the highest-ranked result matching a preferred alternate (in the user's order); otherwise the highest-ranked result whose title plausibly covers the same story (substantive headline overlap, not just shared keywords). When in doubt, move to the next result rather than guessing.
5. **If a match is found**, attach `alternate_url` (Step 6 fetches this) and `original_paywalled_url` (Step 7 cites this on the "Via" line). Leave the candidate's `url` alone.
6. **If no usable match is found**, attach `alternate_searched: true` and `alternate_found: false`. Step 6 still tries the original URL.

Run multiple paywalled candidates' searches in parallel (separate `WebSearch` calls in one message).

#### Step 6 — Summarize keepers

For each `keep` candidate (never for `dup`, `repeat`, or `skip`):

- **If `pre_summarized` is true** (1440 blurbs): skip WebFetch entirely. The `description` field IS the summary — copy it through verbatim. Do not re-summarize, paraphrase, or trim.
- **Otherwise:**
  1. Load `WebFetch` if not already available: `ToolSearch(query="select:WebFetch")`
  2. Choose the fetch URL: `alternate_url` if Step 5 set one, else `url`.
  3. Fetch with this prompt (verbatim): `Read this article and return a 2-4 sentence neutral summary of its substantive content. Ignore navigation, ads, related links, and comments. Do not repeat the title and do not editorialize. If the page is paywalled and only a dek/excerpt is visible, briefly note that and summarize what is visible.`
  4. **Use WebFetch's response as the summary** — do not re-summarize it in the main context (the article body should never enter your context; that's the point). If the response is clearly malformed (well over 4 sentences, contains nav/UI cruft, or just echoes the title), trim it once and move on; otherwise pass it through verbatim.
  5. If WebFetch fails outright (network error, 404, timeout), fall back to a 2-4 sentence summary written from the candidate's `description` and append ` *(summary from feed description)*`. If you fell back because the **alternate** URL failed, append ` *(alternate fetch failed; summary from feed description)*` instead — the original was paywalled, so going back to it isn't useful.

Run independent WebFetch calls in parallel where there is more than one keeper.

#### Step 7 — Write digest

Create `$PAPERBOY_VAULT_DIR/feed/YYYY-MM-DD-HHMMSS.md` where the timestamp is the current local time at invocation (fetch time, not content time).

```markdown
# Paperboy — YYYY-MM-DD HH:MM

Fetched {raw_items} items across {sources_configured} sources ({url_duplicates_merged} duplicates merged) — kept {K}, {R} repeats suppressed, {S} skipped.

---

## [Article Title](article-url)

**Source:** [<friendly-name>](<discussion-url>) · **Published:** YYYY-MM-DD HH:MM UTC
**Why this matched:** <reason from Step 4>

<2-4 sentence summary>

---
```

Order items most recently published first; `pub_precision: unknown` goes last.

**Published rendering.** Honesty about precision matters — never invent a time:
- `pub_precision: datetime` → `2026-09-17 21:48 UTC`
- `pub_precision: date` → `2026-09-17` followed by ` *(date only)*` (1440's sitemap carries no time of day)
- `pub_precision: unknown` → `unknown`

**Source rendering:**
- Friendly names by slug: `hn-*` → `HN`, `lobsters-*` → `Lobsters`, `csm-*` → `CSM`, `1440` → `1440`, `morning-brew` → `Morning Brew`, `reddit-*` → `r/<subreddit>` (extract from `discussion_url`, preserving casing). For anything else, title-case the slug.
- If a source entry has `discussion_url`, link the friendly name to it: `[HN](https://news.ycombinator.com/item?id=...)`. Otherwise render it as plain text.
- A candidate merged by fetch.py has several entries in `sources` — render each separately, each linked to its own discussion page: `[HN](hn-url), [Lobsters](lobsters-url)`.

**Also-covered rendering** (when the story had `dup` members): append a line under the **Source:** line listing each `dup`, linked to its own article URL and labelled with its friendly source name:

```markdown
**Also covered:** [Morning Brew](url) · [1440](url)
```

**Follow-up rendering** (when Step 4 kept an item whose reason began `follow-up:`): append to the **Source:** line `· **Follow-up:** first covered YYYY-MM-DD`.

**Alternate-source rendering** (only when `alternate_url` is set):
- Append `· **Via:** [<alt-host>](<alternate-url>) (original [<orig-host>](<original-paywalled-url>) is paywalled)` to the **Source:** line.
- Hosts are lowercased with leading `www.` stripped (e.g. `apnews.com`).
- If `alternate_searched: true` but `alternate_found: false`, append `· **Note:** paywalled (no alternate found)` instead. The heading still links to the original `url`.

**Unsupported-source notice.** If `unsupported_sources` from Step 2 is non-empty, insert this immediately after the "Fetched ..." line and before the first `---`. Use it **only** for `kind: unsupported` — transient, blocked, and config errors belong in the Step 9 report, not here.

```markdown
> **Heads up:** paperboy couldn't handle the source(s) `<slug1>`, `<slug2>` with the current version of the skill. To request official support for new source types or feed formats, file an issue at <https://github.com/rezrov/claude-marketplace/issues>.
```

**Pre-summarized item rendering (1440):**
- The `description` already contains inline `[link text](url)` citations as part of the body — render it verbatim (do NOT rewrite the inline link text).
- After the body, append a `**Cited:**` line listing every entry in `citations`, **replacing each citation's link text with the URL's registrable host** (lowercased, leading `www.` stripped). The original citation text is discarded for this line:
  - `["Acme announces foo", "https://www.news.com/articles/123.html"]` → `[news.com](https://www.news.com/articles/123.html)`
  - `["report PDF", "https://reports.example.co.uk/x.pdf"]` → `[reports.example.co.uk](https://reports.example.co.uk/x.pdf)`
- Join with ` · `: `**Cited:** [news.com](url1) · [bbc.com](url2)`
- Keep duplicates if several citations resolve to the same host, so each underlying source stays clickable.

**Skipped section.** Close the digest with every `skip` and `repeat`, so the filter stays inspectable and tunable:

```markdown
## Skipped (X items)

- [<title>](<article-url>) — <source> — <reason>
```

List `repeat` entries first (they carry `already covered YYYY-MM-DD`), then `skip` entries. Use the candidate's `url` for the link. Do not omit any — the count in the heading must match the number of bullets.

#### Step 8 — Finalize state

fetch.py already recorded every fetched item ID in the manifest, so you only supply the run's stories:

```bash
echo '{"stories":[{"key":"fed-rate-hike-sept-2026","headline":"Fed raises rates a quarter point","gist":"First hike since 2023; range now 3.75-4%","status":"kept"}]}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/finalize.py"
```

Include one entry for every distinct `story-key` you assigned a `keep` or `repeat` verdict (not `dup` — those share their primary's key, and not `skip`). `gist` must be ≤15 words describing what happened, because it is what tomorrow's run compares against.

Including `repeat` stories is deliberate: it rolls the suppression window forward so an ongoing story with no developments stays suppressed.

Finalize marks manifest IDs seen, caps each seen list to `PAPERBOY_SEEN_CAP`, updates `last_fetched_at`, and merges the story ledger.

#### Step 9 — Report to user

Tell the user:
- Where the digest was written (full path)
- Counts: kept, repeats suppressed, skipped, duplicates merged
- If any keepers were rerouted through an alternate source: how many (one sentence — the digest's **Via:** lines show which)
- **Every entry in `warnings`, verbatim.** These are the silent-degradation signals and the user's runner forwards this report to their phone.
- Every entry in `errors`, with its `kind`
- If `init.py --migrate` appended sections to `sources.md`, say so and ask them to review it
- **If `unsupported_sources` is non-empty:** name the slug(s) and point to <https://github.com/rezrov/claude-marketplace/issues>. This duplicates the digest notice intentionally — the user sees it in chat whether or not they open the digest.

Do not open the file or summarize its contents — the user will read it in Obsidian.

#### Step 10 — Open the vault in Obsidian (conditional)

Run this **only** if the user's request expressed intent to view the digest — "show it to me", "open it", "let me see it", etc. Skip otherwise, and skip if Step 2 produced no candidates or the digest was not written.

```bash
open "obsidian://open?vault=$(basename "${PAPERBOY_VAULT_DIR:-$HOME/Documents/PaperboyVault}")"
```

This focuses Obsidian on the vault by its registered name (the vault directory's basename). Do not attempt to open a specific file — `obsidian://open` with `file=` requires the file to already be indexed, and the vault may not have refreshed yet.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PAPERBOY_VAULT_DIR` | `~/Documents/PaperboyVault` | Obsidian vault root |
| `PAPERBOY_BACKFILL_DAYS` | `7` | Max lookback for backdated items; also first-run cap |
| `PAPERBOY_STORY_WINDOW_DAYS` | `7` | How far back Step 4 looks for cross-day repeats |
| `PAPERBOY_STORY_RETENTION_DAYS` | `30` | How long the story ledger keeps entries |
| `PAPERBOY_SEEN_CAP` | `2000` | Max seen IDs retained per source |
| `PAPERBOY_MANIFEST` | `/tmp/paperboy-manifest.json` | Where fetch.py hands item IDs to finalize.py |

### Error Handling

- **Vault missing**: init.py creates and seeds it; offer to let the user review the seeds before continuing
- **Source fetch fails**: skip that source, record in `errors[]` with a `kind`, continue — never fail the run
- **Unsupported source**: track in `unsupported_sources`; surface in the digest notice (Step 7) and the chat report (Step 9)
- **Classifier output malformed**: re-prompt once, then `skip` that candidate with reason `classifier-error`
- **Article fetch fails**: fall back to the feed description, noted in the digest
- **Alternate fetch fails**: fall back to the feed description with "alternate fetch failed". Do NOT retry the original paywalled URL — it was bypassed for a reason
- **WebSearch returns no usable alternate**: leave the candidate on its original URL and note "paywalled (no alternate found)"
- **Digest write fails**: do NOT call finalize — the next run will re-fetch the same items

### Notes

- **State is committed last, deliberately.** Crash-safe: if anything fails before the digest is written, the next run re-fetches the same items.
- **All fetched IDs get marked seen**, whatever their verdict. The filter's job is to prevent resurfacing; tuning happens via `interests.md`.
- **Item IDs never enter your context.** fetch.py writes them to the manifest and finalize.py reads it. Do not reconstruct them.
- **Backfill window is a crawl bound, not a filter.** Items older than `PAPERBOY_BACKFILL_DAYS` that appear in a feed today are ignored — otherwise a source reshuffling its archive would flood the digest.
- **Two layers of deduplication.** fetch.py merges *identical URLs* mechanically (Step 2); you merge *the same story told by different outlets* with judgment (Step 4). Never redo the first in the second.
- **1440 blurbs are never URL-merged** but they ARE story-clustered — a 1440 blurb and a Morning Brew article about the same event are one story.
- **Reddit posts are polymorphic.** fetch.py routes the candidate's `url` to whatever WebFetch can summarize: external sites for link posts, `old.reddit.com/<permalink>` for self-text/image/video posts. For image-only posts the summary may effectively describe the title plus what's visible; that's the best available.
- **No subagents.** Everything runs in the main context — fetches are cheap, classification benefits from the interests file being in context, summarization is per-item WebFetch + write.
- **Do not modify `interests.md` or `sources.md` automatically.** The user owns those files. `init.py --migrate` only ever appends missing schema sections.
- **Paywall handling is policy-respecting, not paywall-bypassing.** Paperboy never tries to bypass a paywall. It looks for the same news story at a non-paywalled source (typically wire services like AP, Reuters, BBC, NPR, or the user's listed alternates) and summarizes from that. If no alternate exists, the original URL stands.
