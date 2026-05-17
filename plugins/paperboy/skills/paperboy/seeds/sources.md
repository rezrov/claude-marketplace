# Paperboy Sources

One entry per line. Format: `- <slug> | <url> | <type>`

- `slug`: unique identifier, used for the state filename (`state/<slug>.json`) when applicable
- `url`: feed URL (active sources) or site URL (alternate / paywall entries)
- `type`: one of —
  - `rss`: standard RSS 2.0 feed
  - `1440-sitemap`: the 1440 newsletter (URL is a sitemap.xml; each newsletter page is fetched and parsed into per-blurb candidates that come pre-summarized)
  - `reddit-sub`: a subreddit listing (URL is a subreddit page like `https://www.reddit.com/r/<sub>/top/`; converted to the JSON endpoint and parsed per post)
  - `alternate`: not scanned. A **preferred non-paywalled source** to look at first when paperboy needs an alternate URL for a paywalled story.
  - `paywall`: not scanned. Marks a site as paywalled; selected articles from this site trigger alternate-finding and the digest notes both URLs.

Lines starting with `#` and blank lines are ignored.

## Active sources

- hn-frontpage      | https://hnrss.org/frontpage              | rss
- hn-newest         | https://hnrss.org/newest                 | rss
- lobsters-hot      | https://lobste.rs/rss                    | rss
- lobsters-new      | https://lobste.rs/newest.rss             | rss
- csm-usa           | https://rss.csmonitor.com/feeds/usa      | rss
- csm-world         | https://rss.csmonitor.com/feeds/world    | rss
- 1440              | https://join1440.com/sitemap/2.xml       | 1440-sitemap
- reddit-claudecode | https://www.reddit.com/r/ClaudeCode/     | reddit-sub

## Preferred alternates

When a selected article comes from a paywalled site (see below), paperboy searches for the same story at one of these sources first. Edit freely.

- apnews            | https://apnews.com                       | alternate
- npr               | https://www.npr.org                      | alternate
- bbc               | https://www.bbc.com                      | alternate
- reuters           | https://www.reuters.com                  | alternate
- axios             | https://www.axios.com                    | alternate
- guardian          | https://www.theguardian.com              | alternate
- csm               | https://www.csmonitor.com                | alternate

## Paywalled sites

If a selected article's URL is on one of these sites, paperboy looks for an alternate non-paywalled source for the same story and (if found) summarizes from the alternate. Edit freely — add any sites you want treated as paywalled.

- nyt               | https://www.nytimes.com                  | paywall
- wsj               | https://www.wsj.com                      | paywall
- wapo              | https://www.washingtonpost.com           | paywall
- bloomberg         | https://www.bloomberg.com                | paywall
- ft                | https://www.ft.com                       | paywall
- economist         | https://www.economist.com                | paywall
- newyorker         | https://www.newyorker.com                | paywall
- atlantic          | https://www.theatlantic.com              | paywall
- information       | https://www.theinformation.com           | paywall
- times-uk          | https://www.thetimes.co.uk               | paywall
- telegraph         | https://www.telegraph.co.uk              | paywall
- foreign-policy    | https://foreignpolicy.com                | paywall
- foreign-affairs   | https://www.foreignaffairs.com           | paywall
- bostonglobe       | https://www.bostonglobe.com              | paywall
- latimes           | https://www.latimes.com                  | paywall
