#!/usr/bin/env python3
"""Parse 1440 newsletter HTML into per-blurb dicts.

v1.1 scope: extracts only the "Need To Know" featured blurbs (highest
signal-to-noise). Sponsor sections ("In partnership with X") are detected and
excluded. "In The Know" bullet items and "Etcetera" are not yet extracted.

Each blurb dict has:
  - title:             str  — the blurb's bolded heading
  - description:       str  — body text with inline `[link text](url)` citations
  - description_plain: str  — body text with link wrappers stripped
  - citations:         list of [text, url] pairs in order of appearance
  - blurb_slug:        str  — slugified title, suitable for use in a stable id
"""
import re
from html.parser import HTMLParser

SECTION_HEADERS = {"Need To Know", "In The Know", "Etcetera"}
KEEP_SECTION = "Need To Know"
SPONSOR_SKIP_MAX = 20  # safety cap when sponsor end marker isn't present


class _NewsletterParser(HTMLParser):
    """Walk the HTML and produce a flat sequence of paragraph descriptors.

    Each descriptor is {segments: [...], has_mso: bool}, where segments are
    either ('text', str) or ('link', text, href). Order is preserved so the
    rendering helpers can rebuild plain or markdown forms faithfully.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs = []
        self._in_p = False
        self._segments = []
        self._has_mso = False
        self._a_open = False
        self._a_href = ""
        self._a_text = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "p":
            self._in_p = True
            self._segments = []
            self._has_mso = False
        elif self._in_p:
            if tag == "span":
                cls = attrs_d.get("class") or ""
                if "mso-font-fix-arial" in cls:
                    self._has_mso = True
            elif tag == "a":
                self._a_open = True
                self._a_href = attrs_d.get("href") or ""
                self._a_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._a_open:
            text = "".join(self._a_text).strip()
            if text and self._a_href.startswith(("http://", "https://")):
                self._segments.append(("link", text, self._a_href))
            elif text:
                self._segments.append(("text", text))
            self._a_open = False
            self._a_href = ""
            self._a_text = []
        elif tag == "p" and self._in_p:
            self.paragraphs.append({
                "segments": list(self._segments),
                "has_mso": self._has_mso,
            })
            self._in_p = False

    def handle_data(self, data):
        if not self._in_p:
            return
        if self._a_open:
            self._a_text.append(data)
        else:
            self._segments.append(("text", data))


def _para_plain(p):
    parts = []
    for seg in p["segments"]:
        if seg[0] == "text":
            parts.append(seg[1])
        elif seg[0] == "link":
            parts.append(seg[1])
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _para_markdown(p):
    parts = []
    for seg in p["segments"]:
        if seg[0] == "text":
            parts.append(seg[1])
        elif seg[0] == "link":
            parts.append(f"[{seg[1]}]({seg[2]})")
    return re.sub(r"[ \t]+", " ", "".join(parts)).strip()


def _para_links(p):
    return [[seg[1], seg[2]] for seg in p["segments"] if seg[0] == "link"]


def _slugify(s, max_len=60):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:max_len] or "untitled"


def extract_newsletter_blurbs(html_text):
    """Return a list of blurb dicts from a 1440 newsletter page's HTML."""
    parser = _NewsletterParser()
    parser.feed(html_text)
    paragraphs = parser.paragraphs

    # Locate the Need To Know section bounds
    start_idx = None
    end_idx = len(paragraphs)
    for i, p in enumerate(paragraphs):
        text = _para_plain(p).strip("\xa0 \t")
        if text == KEEP_SECTION:
            start_idx = i + 1
        elif start_idx is not None and text in (SECTION_HEADERS - {KEEP_SECTION}):
            end_idx = i
            break

    if start_idx is None:
        return []

    section = paragraphs[start_idx:end_idx]

    blurbs = []
    pending_title = None
    pending_bodies = []
    sponsor_skip = False
    sponsor_count = 0

    def flush():
        nonlocal pending_title, pending_bodies
        if pending_title and pending_bodies:
            description_md = "\n\n".join(_para_markdown(p) for p in pending_bodies)
            description_plain = "\n\n".join(_para_plain(p) for p in pending_bodies)
            citations = []
            seen = set()
            for p in pending_bodies:
                for t, u in _para_links(p):
                    if u not in seen:
                        citations.append([t, u])
                        seen.add(u)
            if description_plain.strip():
                blurbs.append({
                    "title": pending_title,
                    "description": description_md,
                    "description_plain": description_plain,
                    "citations": citations,
                    "blurb_slug": _slugify(pending_title),
                })
        pending_title = None
        pending_bodies = []

    for p in section:
        text = _para_plain(p)
        if not text or text in (".", "\xa0", " "):
            continue

        if text.startswith("In partnership with"):
            flush()
            sponsor_skip = True
            sponsor_count = 0
            continue

        if sponsor_skip:
            sponsor_count += 1
            if "Please support our sponsors" in text or sponsor_count >= SPONSOR_SKIP_MAX:
                sponsor_skip = False
                sponsor_count = 0
            continue

        if p["has_mso"]:
            pending_bodies.append(p)
        else:
            flush()
            if len(text) >= 3:
                pending_title = text

    flush()
    return blurbs


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:
        html_text = open(sys.argv[1]).read()
    else:
        html_text = sys.stdin.read()
    blurbs = extract_newsletter_blurbs(html_text)
    json.dump(blurbs, sys.stdout, indent=2)
