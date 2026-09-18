#!/usr/bin/env python3
"""Paperboy test suite.

Stdlib only, no network. Run from anywhere:

    python3 plugins/paperboy/tests/test_paperboy.py

The vault-dependent modules read PAPERBOY_VAULT_DIR at import time, so the env
var is set to a scratch dir before the imports below.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_SCRATCH = Path(tempfile.mkdtemp(prefix="paperboy-test-"))
os.environ["PAPERBOY_VAULT_DIR"] = str(_SCRATCH / "vault")
os.environ["PAPERBOY_MANIFEST"] = str(_SCRATCH / "manifest.json")

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "paperboy" / "scripts"
SEEDS = Path(__file__).resolve().parent.parent / "skills" / "paperboy" / "seeds"
sys.path.insert(0, str(SCRIPTS))

import _common          # noqa: E402
import fetch            # noqa: E402
import finalize         # noqa: E402
import init as vault_init  # noqa: E402
import parser_1440      # noqa: E402


class TestUrlHygiene(unittest.TestCase):
    def test_strips_tracking_params(self):
        self.assertEqual(
            _common.strip_tracking(
                "https://www.morningbrew.com/stories/x"
                "?utm_source=&utm_medium=syndication&utm_campaign=feed"),
            "https://www.morningbrew.com/stories/x")

    def test_keeps_meaningful_params(self):
        self.assertEqual(
            _common.strip_tracking("https://www.youtube.com/watch?v=abc&utm_source=x"),
            "https://www.youtube.com/watch?v=abc")
        self.assertEqual(
            _common.strip_tracking("https://news.ycombinator.com/item?id=1"),
            "https://news.ycombinator.com/item?id=1")

    def test_host_of_strips_www_as_a_prefix_not_a_charset(self):
        # str.lstrip('www.') would mangle these; removeprefix must be used.
        self.assertEqual(_common.host_of("https://wired.com/x"), "wired.com")
        self.assertEqual(_common.host_of("https://www.wired.com/x"), "wired.com")
        self.assertEqual(_common.host_of("https://web.example.com/x"), "web.example.com")

    def test_dedup_key_ignores_www_slash_and_param_order(self):
        a = _common.dedup_key("https://www.example.com/a/b/?x=1&y=2")
        b = _common.dedup_key("https://example.com/a/b?y=2&x=1#frag")
        self.assertEqual(a, b)

    def test_dedup_key_separates_distinct_articles(self):
        self.assertNotEqual(_common.dedup_key("https://e.com/a"),
                            _common.dedup_key("https://e.com/b"))


class TestCollapseDuplicates(unittest.TestCase):
    @staticmethod
    def _item(source, url, title, pub, desc="", ident=None, discussion=None):
        d = {"source": source, "id": ident or f"{source}:{url}", "url": url,
             "title": title, "pub_iso": pub, "pub_precision": "datetime",
             "description": desc}
        if discussion:
            d["discussion_url"] = discussion
        return d

    def test_merges_same_article_across_sources(self):
        raw = [
            self._item("hn-frontpage", "https://ex.com/story", "Story",
                       "2026-09-17T10:00:00+00:00", "short",
                       discussion="https://news.ycombinator.com/item?id=1"),
            self._item("lobsters-hot", "https://www.ex.com/story/", "A Longer Story Title",
                       "2026-09-17T09:00:00+00:00", "a much longer description",
                       discussion="https://lobste.rs/s/abc"),
        ]
        out, dupes = fetch.collapse_duplicates(raw)
        self.assertEqual(dupes, 1)
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual([s["slug"] for s in c["sources"]], ["hn-frontpage", "lobsters-hot"])
        self.assertEqual(c["pub_iso"], "2026-09-17T09:00:00+00:00")   # earliest
        self.assertEqual(c["title"], "A Longer Story Title")          # longest
        self.assertEqual(c["description"], "a much longer description")
        self.assertEqual(c["sources"][1]["discussion_url"], "https://lobste.rs/s/abc")

    def test_does_not_merge_distinct_articles(self):
        raw = [self._item("a", "https://ex.com/1", "One", "2026-09-17T10:00:00+00:00"),
               self._item("b", "https://ex.com/2", "Two", "2026-09-17T10:00:00+00:00")]
        out, dupes = fetch.collapse_duplicates(raw)
        self.assertEqual((len(out), dupes), (2, 0))

    def test_never_merges_pre_summarized_blurbs(self):
        # Two 1440 blurbs share the newsletter page URL but are separate stories.
        raw = [
            {"source": "1440", "id": "page:a", "url": "https://join1440.com/newsletter/p",
             "title": "A", "pub_iso": "2026-09-17T00:00:00+00:00", "pub_precision": "date",
             "description": "blurb a", "pre_summarized": True, "citations": []},
            {"source": "1440", "id": "page:b", "url": "https://join1440.com/newsletter/p",
             "title": "B", "pub_iso": "2026-09-17T00:00:00+00:00", "pub_precision": "date",
             "description": "blurb b", "pre_summarized": True, "citations": []},
        ]
        out, dupes = fetch.collapse_duplicates(raw)
        self.assertEqual((len(out), dupes), (2, 0))

    def test_merge_prefers_a_known_publish_time_over_none(self):
        raw = [self._item("a", "https://ex.com/1", "One", None),
               self._item("b", "https://ex.com/1", "One", "2026-09-17T08:00:00+00:00")]
        out, _ = fetch.collapse_duplicates(raw)
        self.assertEqual(out[0]["pub_iso"], "2026-09-17T08:00:00+00:00")


class TestErrorClassification(unittest.TestCase):
    def test_kinds(self):
        import socket
        import urllib.error
        cases = [
            (urllib.error.HTTPError("u", 404, "nf", {}, None), "config"),
            (urllib.error.HTTPError("u", 403, "forbidden", {}, None), "blocked"),
            (urllib.error.HTTPError("u", 503, "down", {}, None), "transient"),
            (urllib.error.URLError("dns"), "transient"),
            (socket.timeout("slow"), "transient"),
        ]
        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(fetch.classify_fetch_error(exc), expected)


NEWSLETTER = """<html><body>
<p>Need To Know</p>
<p>Fed Hikes Rates</p>
<p><span class="mso-font-fix-arial">The Fed raised rates
<a href="https://nbcnews.com/x">a quarter point</a> yesterday.</span></p>
<p>In partnership with Spot &amp; Tango</p>
<p><span class="mso-font-fix-arial">Buy our dog food.</span></p>
<p>Please support our sponsors!</p>
<p>Storm Makes Landfall</p>
<p><span class="mso-font-fix-arial">A hurricane hit
<a href="https://ap.org/y">the coast</a>.</span></p>
<p>In The Know</p>
<p>Sports</p>
<p><span class="mso-font-fix-arial">Should not be extracted.</span></p>
</body></html>"""


class TestParser1440(unittest.TestCase):
    def test_extracts_need_to_know_only(self):
        diag = []
        blurbs = parser_1440.extract_newsletter_blurbs(NEWSLETTER, diag)
        self.assertEqual([b["title"] for b in blurbs],
                         ["Fed Hikes Rates", "Storm Makes Landfall"])
        self.assertEqual(diag, [])

    def test_skips_sponsor_block(self):
        blurbs = parser_1440.extract_newsletter_blurbs(NEWSLETTER)
        self.assertNotIn("Buy our dog food.",
                         " ".join(b["description"] for b in blurbs))

    def test_captures_citations_as_markdown(self):
        blurbs = parser_1440.extract_newsletter_blurbs(NEWSLETTER)
        self.assertEqual(blurbs[0]["citations"], [["a quarter point", "https://nbcnews.com/x"]])
        self.assertIn("[a quarter point](https://nbcnews.com/x)", blurbs[0]["description"])

    def test_missing_section_reports_a_diagnostic(self):
        diag = []
        out = parser_1440.extract_newsletter_blurbs("<html><p>Hello</p></html>", diag)
        self.assertEqual(out, [])
        self.assertTrue(any("no known content section" in d for d in diag), diag)

    def test_no_paragraphs_reports_a_diagnostic(self):
        diag = []
        self.assertEqual(parser_1440.extract_newsletter_blurbs("<html></html>", diag), [])
        self.assertTrue(any("no <p> elements" in d for d in diag), diag)

    def test_unterminated_sponsor_block_reports_a_diagnostic(self):
        html = ('<html><p>Need To Know</p><p>In partnership with X</p>'
                '<p><span class="mso-font-fix-arial">ad copy</span></p></html>')
        diag = []
        parser_1440.extract_newsletter_blurbs(html, diag)
        self.assertTrue(any("sponsor block" in d for d in diag), diag)



# The weekend layout: "One Big Headline" + "Quick Hits". In Quick Hits the lede
# and the body are both body-class paragraphs; only boldness separates them.
WEEKEND = """<html><body>
<p>One Big Headline</p>
<p>Turn off the Lights</p>
<p><span class="mso-font-fix-arial">Night light exposure may harm
<a href="https://jama.org/x">the heart</a>.</span></p>
<p>Quick Hits</p>
<p><span class="mso-font-fix-arial"><strong>CIA releases 9/11 briefs.</strong></span></p>
<p><span class="mso-font-fix-arial">The agency published 69 documents
<a href="https://cia.gov/y">here</a>.</span></p>
<p><span class="mso-font-fix-arial"><strong>Discover more:</strong></span></p>
<p><span class="mso-font-fix-arial">A sub-header's links, not a new story.</span></p>
<p><span class="mso-font-fix-arial"><strong>Houthis seize Red Sea island.</strong></span></p>
<p><span class="mso-font-fix-arial">The militia took a choke point.</span></p>
<p>Etcetera</p>
<p><span class="mso-font-fix-arial">Not extracted.</span></p>
</body></html>"""


class TestParser1440Weekend(unittest.TestCase):
    def test_extracts_both_weekend_sections(self):
        diag = []
        blurbs = parser_1440.extract_newsletter_blurbs(WEEKEND, diag)
        self.assertEqual(diag, [])
        self.assertEqual(
            [b["title"] for b in blurbs],
            ["Turn off the Lights", "CIA releases 9/11 briefs.", "Houthis seize Red Sea island."])
        self.assertEqual([b["section"] for b in blurbs],
                         ["One Big Headline", "Quick Hits", "Quick Hits"])

    def test_bold_subheader_stays_with_its_blurb(self):
        # "Discover more:" ends in a colon -- a sub-header, not a new story.
        blurbs = parser_1440.extract_newsletter_blurbs(WEEKEND)
        cia = next(b for b in blurbs if b["title"].startswith("CIA"))
        self.assertIn("sub-header's links", cia["description_plain"])
        self.assertNotIn("Discover more:", [b["title"] for b in blurbs])

    def test_etcetera_is_not_extracted(self):
        blurbs = parser_1440.extract_newsletter_blurbs(WEEKEND)
        self.assertNotIn("Not extracted.",
                         " ".join(b["description_plain"] for b in blurbs))

    def test_weekday_titles_are_unaffected_by_bold_rule(self):
        # A weekday body paragraph containing *inline* bold must not be
        # mistaken for a Quick Hits lede.
        html = ('<html><p>Need To Know</p><p>A Real Title</p>'
                '<p><span class="mso-font-fix-arial">Body with an '
                '<strong>emphasised</strong> phrase in it.</span></p></html>')
        blurbs = parser_1440.extract_newsletter_blurbs(html)
        self.assertEqual([b["title"] for b in blurbs], ["A Real Title"])
        self.assertIn("emphasised", blurbs[0]["description_plain"])

    def test_unknown_layout_names_the_sections_it_saw(self):
        html = '<html><p>Weekly Roundup</p><p>Some text here</p></html>'
        diag = []
        self.assertEqual(parser_1440.extract_newsletter_blurbs(html, diag), [])
        self.assertTrue(any("no known content section" in d for d in diag), diag)


class TestVaultMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="paperboy-migrate-"))
        self.sources = self.tmp / "sources.md"

    def test_appends_missing_sections_and_is_idempotent(self):
        # A pre-v1.2 sources.md: active sources only, no alternate/paywall.
        self.sources.write_text(
            "# Paperboy Sources\n\n"
            "- hn-frontpage | https://hnrss.org/frontpage | rss\n"
            "- 1440 | https://join1440.com/sitemap/2.xml | 1440-sitemap\n")

        added = vault_init.migrate_sources(self.sources, SEEDS / "sources.md")
        self.assertEqual(len(added), 2, added)
        text = self.sources.read_text()
        types = vault_init.declared_types(text)
        self.assertIn("alternate", types)
        self.assertIn("paywall", types)
        self.assertIn("hn-frontpage", text)      # original content preserved

        again = vault_init.migrate_sources(self.sources, SEEDS / "sources.md")
        self.assertEqual(again, [])
        self.assertEqual(self.sources.read_text(), text)

    def test_leaves_a_current_sources_file_alone(self):
        self.sources.write_text((SEEDS / "sources.md").read_text())
        self.assertEqual(vault_init.migrate_sources(self.sources, SEEDS / "sources.md"), [])


class TestFinalize(unittest.TestCase):
    def setUp(self):
        _common.STATE_DIR.mkdir(parents=True, exist_ok=True)
        for f in _common.STATE_DIR.glob("*.json"):
            f.unlink()

    def test_merge_seen_appends_and_dedupes(self):
        w = []
        finalize.merge_seen({"src": ["a", "b"]}, w)
        finalize.merge_seen({"src": ["b", "c"]}, w)
        state = json.loads((_common.STATE_DIR / "src.json").read_text())
        self.assertEqual(state["seen_ids"], ["a", "b", "c"])
        self.assertIsNotNone(state["last_fetched_at"])
        self.assertEqual(w, [])

    def test_corrupt_state_warns_instead_of_failing_silently(self):
        (_common.STATE_DIR / "bad.json").write_text("{not json")
        w = []
        finalize.merge_seen({"bad": ["x"]}, w)
        self.assertTrue(any(x["kind"] == "state-corrupt" for x in w), w)

    def test_story_ledger_tracks_first_and_last_seen(self):
        w = []
        finalize.merge_stories([{"key": "fed-hike", "headline": "Fed hikes", "gist": "up 0.25"}], w)
        finalize.merge_stories([{"key": "fed-hike", "headline": "Fed hikes again"}], w)
        ledger = json.loads((_common.STATE_DIR / "stories.json").read_text())
        story = ledger["stories"][0]
        self.assertEqual(story["times_seen"], 2)
        self.assertEqual(story["headline"], "Fed hikes again")
        self.assertEqual(story["gist"], "up 0.25")        # retained, not blanked
        self.assertEqual(story["first_seen"], story["last_seen"])
        self.assertEqual(w, [])

    def test_story_entry_without_key_warns(self):
        w = []
        finalize.merge_stories([{"headline": "no key"}], w)
        self.assertTrue(any(x["kind"] == "bad-input" for x in w), w)

    def test_recent_stories_window_excludes_stale_entries(self):
        (_common.STATE_DIR / "stories.json").write_text(json.dumps({"stories": [
            {"key": "fresh", "headline": "f", "last_seen": "2999-01-01"},
            {"key": "stale", "headline": "s", "last_seen": "2000-01-01"},
        ]}))
        w = []
        keys = [s["key"] for s in fetch.load_recent_stories(w)]
        self.assertEqual(keys, ["fresh"])


class TestSourcesParsing(unittest.TestCase):
    def test_splits_active_alternate_and_paywall(self):
        p = Path(tempfile.mkdtemp()) / "sources.md"
        p.write_text(
            "# comment line ignored\n"
            "- hn | https://hnrss.org/frontpage | rss\n"
            "- apnews | https://apnews.com | alternate\n"
            "- nyt | https://www.nytimes.com | paywall\n"
            "not a list line\n")
        sources, alternates, paywalls = fetch.parse_sources_md(p)
        self.assertEqual([s["slug"] for s in sources], ["hn"])
        self.assertEqual([a["slug"] for a in alternates], ["apnews"])
        self.assertEqual([x["slug"] for x in paywalls], ["nyt"])

    def test_tolerates_backticked_fields(self):
        p = Path(tempfile.mkdtemp()) / "sources.md"
        p.write_text("- `hn` | `https://hnrss.org/frontpage` | `rss`\n")
        sources, _, _ = fetch.parse_sources_md(p)
        self.assertEqual(sources[0]["type"], "rss")


if __name__ == "__main__":
    unittest.main(verbosity=2)
