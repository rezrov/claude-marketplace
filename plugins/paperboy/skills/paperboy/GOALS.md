# Paperboy — Goals & Future Work

Forward-looking notes for upgrades beyond v1.3. The current state of the skill is documented in `SKILL.md`. This file is for things we deliberately deferred, constraints to remember, and ideas worth picking up next.

---

## Standing constraints

- **Manual trigger only.** No scheduling inside the skill. The user drives cadence with their own runner (`~/.shellrc/bin/paperboy.sh`, cron + rclone + ntfy). Don't add cron/loop integration unless the user asks.
- **Token cost is high but accepted.** A run classifies the whole candidate set and WebFetches each keeper. The user has explicitly signed off on the cost in exchange for a tight, well-curated feed — but it's a "once a day" tool. Optimizations that reduce cost without reducing quality are welcome; optimizations that trade quality for cost are not.
- **Publisher respect.** Some article sources are blocked by WebFetch at the tool layer (Reuters, BBC, Bloomberg) and others 403 at the origin. The user's policy: feed-description fallbacks are sufficient — Paperboy's job is to send eyes to publishers, not to extract their content. Any future curl-based fallback must keep that posture.
- **Never spoof a browser UA.** See "User-Agent and publisher identification" below — the UA must stay truthful even where a browser string would open more doors.
- **Tight feeds.** Marginal items default to skip. The Skipped section at the bottom of every digest is the tuning surface — when something the user wanted got skipped, they edit `interests.md`.
- **Warnings must reach the user.** The runner ships the agent's final report to ntfy. Anything that degrades silently (a feed going empty, a template change, a corrupt state file) has to surface as a `warnings[]` entry that Step 9 relays verbatim. Tool stderr alone does NOT reach the runner's stdout — `claude -p` only emits the final assistant message, so the agent has to say it out loud.

---

## User-Agent and publisher identification

Paperboy identifies itself truthfully and never impersonates a browser:

```
Paperboy/<version> (Claude Code plugin; +https://github.com/rezrov/claude-marketplace; +https://github.com/anthropics/claude-code)
```

Every claim in that string is accurate — the plugin, the repo it lives in, and the runtime it actually runs under.

**Do not simplify this string without testing every source first.** At least one configured publisher varies its response by user-agent, and a "cleaner" UA silently took that source offline during the v1.3 work: the sitemap kept returning 200 while every article page began failing, so the source degraded to zero content rather than erroring loudly. The `no-blurbs` and `empty-feed` warnings now catch that class of failure, but the cheaper fix is not to reintroduce it.

If a source starts failing after a UA change, revert first and re-measure before theorising. Detailed per-publisher measurements are kept in an untracked local note alongside this repo rather than published here.

---

## Deferred features

### 1440 parser: In The Know section

`parser_1440.py` extracts "Need To Know" (weekday) and "One Big Headline" + "Quick Hits" (weekend). "In The Know" is still unparsed: short bullet items grouped under category headers (Sports/Entertainment/Culture, Science & Technology, Business & Markets) with `>` prefixes and embedded "More" links, one or two related items per bullet separated by `|`.

**To add:** detect category headers within the In The Know span, parse each `>`-prefixed paragraph as one or two candidates (split on `|` if both halves have their own bolded lede), handle mid-category sponsor blocks. The section-walking loop added in v1.3 makes this much easier than it was — it is now a matter of adding the header to `KEEP_SECTIONS` and special-casing the bullet split.

**Why deferred:** the In The Know structure is messier, and the highest-signal blurbs are in the sections we already parse.

### Etcetera section

Still skipped. Looks like book recs / today-in-history / quotes / puzzle links — likely low value for this user's interests. Confirm by inspecting a few samples before deciding.

### WebFetch fetch fallbacks

When WebFetch fails, v1.3 falls back to the RSS description. A curl-based fallback was designed but never built:

1. After WebFetch failure, retry with the truthful Paperboy UA.
2. Crude readability extraction: strip `<script>`, `<style>`, `<nav>`, `<footer>`, keep `<article>` / `<main>` text, truncate to ~8KB.
3. Honor `robots.txt` per-domain (cache the answer for one day). If disallowed, fall back to the RSS dek and note "publisher opts out of fetching".
4. Hard cap on quoted/inlined source text: no more than ~25 consecutive words from the article body.
5. No persistence: fetched body text lives in memory for the summary pass, then is discarded.

**Why deferred:** the user confirmed feed-description stubs are sufficient. Build only if the fallback rate becomes annoying — it currently runs under one item per day.

### Cross-source citation-aware dedup

Step 4's story clustering (v1.3) already merges a 1440 blurb and an HN post about the same event by judgment. A cheaper structural signal is available and unused: when an HN/Lobsters URL appears literally in a 1440 blurb's `citations`, that is a guaranteed match and could be merged mechanically in `fetch.py` before classification, saving the judgment call entirely.

**Why deferred:** the LLM pass handles it; this is a token optimization, not a correctness fix.

### Page-level state caching for 1440

The 1440 handler re-fetches every newsletter page in the backfill window on every run (~7 fetches). Per-blurb `seen_ids` prevents re-emitting blurbs but doesn't avoid the HTTP cost. Add a "page fully processed" cache only if it becomes a problem.

---

## Source roster — candidates

### Mastodon (revisit)

Dropped from v1 because the public trends endpoint on `mastodon.social` is multilingual and noisy. A hashtag-focused approach (per-tag RSS feeds at `https://mastodon.social/tags/<tag>.rss`) could work as plain `rss` sources — no new parser needed, just entries in `sources.md`.

### WSJ (paywall)

Dropped from v1 over subscription cost. RSS feeds exist (`feeds.a.dj.com/rss/...`) and provide headlines + short deks — enough to classify, not enough to summarize. Note that `wsj.com` is already in the seeded paywall list, so WSJ links arriving via HN now route through alternate-finding automatically.

### Other newsletter-style sources

The 1440 integration established a pattern: sitemap (or other index) → daily HTML page → per-blurb extraction → per-blurb candidates with `pre_summarized: true`. This likely applies to Axios AM, The Hustle, Morning Brew's newsletter edition, etc. Each needs its own `parser_*.py` and a new type in `SOURCE_HANDLERS`. The architecture is ready.

---

## Parser robustness — known minor issues

### Sponsor end detection

The parser exits sponsor mode on the literal "Please support our sponsors!" string, at the next known section header, or after 20 skipped paragraphs. The paragraph cap is the fragile path — it now emits a diagnostic when it fires, which surfaces as a `no-blurbs` warning if it swallows real content, so a regression is at least visible.

### Unknown layouts

If 1440 ships a third layout, the parser emits a diagnostic naming the section headers it *did* see, which reaches the user as a warning. That is how the weekend layout was found in the first place — the failure had been silent for months.

---

## Permissions

Path-scoped Read/Write prompts to the vault directory cannot be silenced from `SKILL.md`'s `allowed-tools` — those live in `.claude/settings.local.json`. The `fewer-permission-prompts` skill is the right tool for adding a project-level allowlist. Run it whenever path prompts get noisy.

---

## Token-cost notes

Done in v1.3 (all quality-neutral or quality-positive):

- **URL dedup moved into `fetch.py`** — ~13-20% of raw items are exact-URL repeats (mostly `lobsters-hot ∩ lobsters-new`), and they no longer reach the classifier at all.
- **Item IDs no longer round-trip through the context.** `fetch.py` writes a manifest; `finalize.py` reads it. Previously the agent echoed ~150 opaque IDs back as output tokens.
- **Story clustering and cross-day suppression** remove whole keepers before the summarize step, saving a WebFetch and a rendered entry each.
- **Skip reasons are codes plus ≤8 words** instead of free-form sentences, across ~60-70 skipped items per run.

Still available if cost ever bites:

- **Cheap keyword pre-filter** before LLM classification, dropping obvious skip-list items by title pattern. Trades classification accuracy for tokens.
- **Citation-aware structural dedup** for 1440 (see above).
- **Trimming `RSS_DESC_MAX_CHARS`** is NOT worth it — measured description medians are 90-323 chars against a 600-char cap, so only ~2% of items are truncated at all.
