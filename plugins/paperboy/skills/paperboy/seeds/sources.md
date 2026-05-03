# Paperboy Sources

One source per line. Format: `- <slug> | <url> | <type>`

- `slug`: unique identifier, used for the state filename (`state/<slug>.json`)
- `url`: feed URL
- `type`: one of —
  - `rss`: standard RSS 2.0 feed
  - `1440-sitemap`: the 1440 newsletter (URL is a sitemap.xml; each newsletter page is fetched and parsed into per-blurb candidates that come pre-summarized)
  - `reddit-sub`: a subreddit listing (URL is a subreddit page like `https://www.reddit.com/r/<sub>/top/`; converted to the JSON endpoint and parsed per post)

Lines starting with `#` and blank lines are ignored.

- hn-frontpage      | https://hnrss.org/frontpage              | rss
- hn-newest         | https://hnrss.org/newest                 | rss
- lobsters-hot      | https://lobste.rs/rss                    | rss
- lobsters-new      | https://lobste.rs/newest.rss             | rss
- csm-usa           | https://rss.csmonitor.com/feeds/usa      | rss
- csm-world         | https://rss.csmonitor.com/feeds/world    | rss
- 1440              | https://join1440.com/sitemap/2.xml       | 1440-sitemap
- reddit-claudecode | https://www.reddit.com/r/ClaudeCode/     | reddit-sub
