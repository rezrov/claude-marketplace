#!/usr/bin/env python3
"""Parse 1440 newsletter HTML into per-blurb dicts.

1440 publishes two layouts. Weekday editions lead with "Need To Know"; weekend
editions use "One Big Headline" + "Quick Hits" instead. Both are extracted.
Sponsor sections ("In partnership with X") are detected and excluded. "In The
Know" bullet items and "Etcetera" are not yet extracted.

Blurb titles are recognised structurally: a non-body paragraph starts a blurb
(weekday layout), as does a fully-bold body paragraph (the Quick Hits layout,
where lede and body are both body-class but only the lede is bold).

Each blurb dict has:
  - title:             str  — the blurb's bolded heading
  - description:       str  — body text with inline `[link text](url)` citations
  - description_plain: str  — body text with link wrappers stripped
  - citations:         list of [text, url] pairs in order of appearance
  - blurb_slug:        str  — slugified title, suitable for use in a stable id

extract_newsletter_blurbs() takes an optional `diagnostics` list. When the
extraction comes up empty, it records *why* so the caller can warn instead of
silently emitting nothing.
"""
import re
from html.parser import HTMLParser

# Every section header we know how to recognise. Anything in this set ends the
# preceding section; anything in KEEP_SECTIONS also starts an extracted one.
SECTION_HEADERS = {
    "Need To Know", "In The Know", "Etcetera",   # weekday layout
    "One Big Headline", "Quick Hits",            # weekend layout
}
KEEP_SECTIONS = ("Need To Know", "One Big Headline", "Quick Hits")
KEEP_SECTION = KEEP_SECTIONS[0]  # retained for callers that referenced it
SPONSOR_SKIP_MAX = 20  # safety cap when sponsor end marker isn't present


class _NewsletterParser(HTMLParser):
    """Walk the HTML and produce a flat sequence of paragraph descriptors.

    Each descriptor is {segments: [...], has_mso: bool, all_bold: bool}, where
    segments are either ('text', str) or ('link', text, href). Order is
    preserved so the rendering helpers can rebuild plain or markdown forms
    faithfully. `all_bold` is True when every non-whitespace character in the
    paragraph sits inside <strong>/<b> -- the marker that distinguishes a Quick
    Hits lede from its body, since both carry the body class.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs = []
        self._in_p = False
        self._segments = []
        self._has_mso = False
        self._bold_depth = 0
        self._bold_text = 0
        self._plain_text = 0
        self._a_open = False
        self._a_href = ""
        self._a_text = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "p":
            self._in_p = True
            self._segments = []
            self._has_mso = False
            self._bold_depth = 0
            self._bold_text = 0
            self._plain_text = 0
        elif self._in_p:
            if tag in ("strong", "b"):
                self._bold_depth += 1
            elif tag == "span":
                cls = attrs_d.get("class") or ""
                if "mso-font-fix-arial" in cls:
                    self._has_mso = True
            elif tag == "a":
                self._a_open = True
                self._a_href = attrs_d.get("href") or ""
                self._a_text = []

    def handle_endtag(self, tag):
        if tag in ("strong", "b") and self._bold_depth:
            self._bold_depth -= 1
            return
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
                "all_bold": self._bold_text > 0 and self._plain_text == 0,
            })
            self._in_p = False

    def handle_data(self, data):
        if not self._in_p:
            return
        stripped = len(data.strip())
        if stripped:
            if self._bold_depth:
                self._bold_text += stripped
            else:
                self._plain_text += stripped
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


def extract_newsletter_blurbs(html_text, diagnostics=None):
    """Return a list of blurb dicts from a 1440 newsletter page's HTML.

    Walks the page section by section so both layouts work: weekday pages carry
    "Need To Know", weekend pages carry "One Big Headline" + "Quick Hits".

    `diagnostics` (optional list) collects short strings explaining an empty or
    surprising result, so the caller can surface a warning rather than treating
    a template change as "no news today".
    """
    diag = diagnostics if diagnostics is not None else []

    parser = _NewsletterParser()
    parser.feed(html_text)
    paragraphs = parser.paragraphs

    if not paragraphs:
        diag.append("no <p> elements found in the page HTML")
        return []

    blurbs = []
    section = None          # the section header we are currently inside
    pending_title = None
    pending_bodies = []
    sponsor_skip = False
    sponsor_count = 0
    seen_headers = []

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
                    "section": section,
                })
        pending_title = None
        pending_bodies = []

    for p in paragraphs:
        text = _para_plain(p)
        header = text.strip("\xa0 \t")

        # Section boundaries reset all in-flight state.
        if header in SECTION_HEADERS:
            flush()
            sponsor_skip = False
            sponsor_count = 0
            section = header
            seen_headers.append(header)
            continue

        if section not in KEEP_SECTIONS:
            continue

        if not text or text in (".", "\xa0", " "):
            continue

        if text.startswith("In partnership with"):
            flush()
            sponsor_skip = True
            sponsor_count = 0
            continue

        if sponsor_skip:
            sponsor_count += 1
            if "Please support our sponsors" in text:
                sponsor_skip = False
                sponsor_count = 0
            elif sponsor_count >= SPONSOR_SKIP_MAX:
                # Fell back to the paragraph cap instead of the literal end
                # marker. Works, but it is the fragile path -- note it.
                diag.append(
                    f"sponsor block in {section!r} ended via the {SPONSOR_SKIP_MAX}-paragraph "
                    "cap rather than an end marker"
                )
                sponsor_skip = False
                sponsor_count = 0
            continue

        # A blurb title is either a non-body paragraph (weekday layout) or a
        # fully-bold body paragraph (Quick Hits, where lede and body share the
        # body class and only boldness separates them). A bold run ending in a
        # colon is a sub-header inside a blurb ("Discover more:"), not a new
        # story -- keep it with the body it belongs to.
        is_title = (not p["has_mso"]) or (p.get("all_bold") and not text.rstrip().endswith(":"))
        if is_title:
            flush()
            if len(text) >= 3:
                pending_title = text
        else:
            pending_bodies.append(p)

    flush()

    if sponsor_skip:
        diag.append(
            "reached end of page still inside a sponsor block "
            "(no 'Please support our sponsors' marker seen)"
        )
    if not any(h in KEEP_SECTIONS for h in seen_headers):
        diag.append(
            "no known content section found (looked for "
            f"{', '.join(repr(k) for k in KEEP_SECTIONS)}; saw "
            f"{', '.join(repr(h) for h in seen_headers) or 'no section headers'} "
            f"among {len(paragraphs)} paragraphs)"
        )
    elif not blurbs:
        diag.append(
            f"sections {seen_headers!r} were found but yielded no title+body pairs "
            "(paragraph class markers may have changed)"
        )
    return blurbs


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:
        html_text = open(sys.argv[1]).read()
    else:
        html_text = sys.stdin.read()
    diagnostics = []
    blurbs = extract_newsletter_blurbs(html_text, diagnostics)
    json.dump(blurbs, sys.stdout, indent=2)
    for d in diagnostics:
        print(f"parser_1440: {d}", file=sys.stderr)
