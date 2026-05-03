# Paperboy — Goals & Future Work

Forward-looking notes for upgrades beyond v1.1. Captured at the close of the build session that produced v1.1 (HN + Lobsters + CSM via RSS, plus 1440 via sitemap).

The current state of the skill is documented in `SKILL.md`. This file is for things we deliberately deferred, constraints to remember, and ideas worth picking up next.

---

## Standing constraints

- **Manual trigger only.** No scheduling. The user invokes Paperboy when they want to read; daily-ish cadence is the norm. Don't add cron/loop integration unless the user asks.
- **Token cost is high but accepted.** A typical run reads ~80 candidates, classifies all of them, and WebFetches each keeper. The user has explicitly signed off on the cost in exchange for a tight, well-curated feed — but it's a "once a day" tool, not a "check it five times" tool. Optimizations that reduce cost without reducing quality are welcome; optimizations that trade quality for cost are not.
- **Publisher respect.** Some article sources are blocked by WebFetch at the tool layer (Reuters, BBC, Bloomberg) and others 403 at the origin (Cloudflare-protected sites). The user's policy: feed-description fallbacks ("summary from feed description") are sufficient — Paperboy's job is to send eyes to publishers, not to extract their content. Any future curl-based bypass must keep that posture (see "v1.1 fetch fallbacks" below).
- **Tight feeds.** Marginal items default to skip. The Skipped section at the bottom of every digest is the tuning surface — when something the user wanted got skipped, they edit `interests.md`.

---

## Deferred features

### 1440 parser: In The Know section

`parser_1440.py` only extracts the "Need To Know" section in v1.1. The "In The Know" section contains short bullet items grouped under category headers (Sports/Entertainment/Culture, Science & Technology, Business & Markets, etc.) with `>` prefixes and embedded "More" links. Each bullet is one or two related items separated by `|`.

**To add:** detect category headers within the In The Know span, parse each `>`-prefixed paragraph as one or two candidates (split on `|` if both halves have their own bolded lede), handle mid-category sponsor blocks (e.g., NativePath was embedded between Sci-Tech and Business categories in the sample we built against). The 20-paragraph sponsor-skip cap in v1.1 already handles the embedded NativePath case via fallback.

**Why deferred:** the In The Know structure is messier than Need To Know, and the highest-signal blurbs (the featured ones) are all in Need To Know. Worth doing, but not blocking.

### Etcetera section

Skipped entirely in v1.1. Looks like book recs / today-in-history / quotes / puzzle links — likely low value for this user's interests. Confirm by inspecting a few samples before deciding whether to parse it.

### WebFetch fetch fallbacks

When WebFetch fails (publisher block at tool layer, or 403 at origin), v1.1 falls back to the RSS description. Yesterday we discussed but did NOT build a curl-based fallback. The plan was:

1. After WebFetch failure, retry with `curl -A "PaperboyBot/1.1 (personal news aggregator; +<contact>)"`.
2. Crude readability extraction: strip `<script>`, `<style>`, `<nav>`, `<footer>` tags, keep `<article>` / `<main>` text, truncate to ~8KB.
3. Honor `robots.txt` per-domain (cache the answer for one day). If the site disallows generic UAs on that path, fall back to the RSS dek and note "publisher opts out of fetching" in the digest.
4. Use a truthful UA (don't spoof Chrome). Anyone on an allowlist-only posture can block it deliberately.
5. Hard cap on quoted/inlined source text: no more than ~25 consecutive words from the article body.
6. No persistence: fetched body text lives in memory for the summary pass, then is discarded.

**Why deferred:** the user confirmed feed-description stubs are sufficient. Build this only if the fallback rate becomes annoying.

### Obsidian auto-open

`obsidian://open?vault=PaperboyVault&file=feed/<filename>.md` URI scheme can open the new digest in Obsidian after writing. Implementation: `open "obsidian://..."` via Bash on macOS after Step 6 succeeds. Skill-scoped, low-risk.

**Why deferred:** Obsidian auto-refreshes on filesystem changes, so the new digest shows up in the file list anyway. Auto-open is a small QOL win, not essential.

### Cross-source citation-aware dedup

Current dedup is by candidate URL. If 1440 cites an apnews article and HN also posts the same apnews article, both surface as separate keepers. v1.1 explicitly does NOT dedup these — 1440's blurb adds value (curated summary + multi-source context) even when topically overlapping with an HN post.

**Future option:** detect when an HN/Lobsters URL appears in a 1440 blurb's `citations` and merge the entries (1440 entry as primary, HN/Lobsters as a "Also discussed at" sub-link). Adds complexity; only worth it if the overlap noise gets bothersome.

### Page-level state caching for 1440

The 1440 handler currently re-fetches every newsletter page in the 7-day backfill window on every run. Per-blurb `seen_ids` prevents re-emitting blurbs but doesn't avoid the HTTP cost. ~7 fetches/run is fine for now; add a "page fully processed" cache only if it becomes a problem.

---

## Source roster — candidates

### Mastodon (revisit)

Dropped from v1 because the public trends endpoint on `mastodon.social` is multilingual and noisy. A hashtag-focused approach (user maintains a list of `#technology`, `#programming`, `#ai`, etc.) plus per-tag RSS feeds (`https://mastodon.social/tags/<tag>.rss`) could work. Best done as another `rss` source type — no new parser needed, just per-tag entries in `sources.md`.

### WSJ (paywall)

Dropped from v1 because of $16/mo subscription cost and hard paywall on article bodies. RSS feeds exist (`feeds.a.dj.com/rss/...`) and provide headlines + short deks — enough to classify, not enough to summarize without fetching. Revisit if the user decides the signal-to-cost is worth a subscription.

### 1440 (extensions)

The 1440 source is in v1.1 but only parses Need To Know blurbs (see Deferred Features above). Adding In The Know is the next natural step.

### Other newsletter-style sources

The 1440 integration established a pattern: sitemap (or other index) → daily HTML page → per-blurb extraction → per-blurb candidates with `pre_summarized: true`. This pattern likely applies to other curated newsletters (Axios AM, The Hustle, Morning Brew, etc.). Each would need its own parser_*.py module and a new source type registered in `SOURCE_HANDLERS` in `fetch.py`. The architecture is ready; just need the parsers.

---

## Parser robustness — known minor issues

### Need-To-Know "Humankind" feature

The Humankind one-liner ("🫶 Humankind: Watch …") in the Need To Know section appears as an mso-class body paragraph with no preceding non-mso title. v1.1 glues it onto the previous blurb's body (e.g., today's "Hollywood Mega-Merger" picked up a stray "cross the finish line" citation from the inline Humankind feature). Cosmetic; doesn't break classification. Could be addressed by recognizing the emoji-prefix pattern.

### Sponsor end detection

v1.1 exits sponsor mode on either the literal "Please support our sponsors!" string OR after 20 skipped paragraphs OR at the next top-level section header. The Spot & Tango block ends with the literal marker; the NativePath block doesn't (it ends at a category header within In The Know). The 20-paragraph cap caught NativePath in our sample but is fragile. If sponsor formatting changes, this breaks; revisit when we add In The Know parsing anyway.

---

## Permissions

Path-scoped Read/Write prompts to the vault directory (e.g., `Read(/Users/ron/Dropbox/projects/PaperboyVault/...)`) cannot be silenced from `SKILL.md`'s `allowed-tools` — those live in `.claude/settings.local.json`. The `fewer-permission-prompts` skill is the right tool for adding a project-level allowlist scanned from session transcripts. Run it whenever path prompts get noisy.

---

## Token-cost optimizations (only if cost becomes a real concern)

Notes, not commitments. The user signed off on current cost; only build these if the bill or latency starts to bite.

- **Cheap keyword pre-filter** before LLM classification: drop obvious skip-list items (sponsored content, gaming reviews, tutorials) by title pattern before sending to the classifier. Trades some classification accuracy for substantial token savings.
- **Smaller model for summarization**: WebFetch already uses a small fast model internally. The classification + summary-prompt construction in the main agent could batch keepers into one prompt to a cheaper model and pay one round-trip per ~10 items instead of one per item.
- **Skip Lobsters cross-source duplicates earlier**: Lobsters hot + new feeds share many URLs. fetch.py currently emits them as separate candidates and the LLM dedups in the digest pass. We could URL-dedup at fetch time and drop one before classification. Small win, simple to implement.
