"""The estate report page, made safe to serve from the app's own address (security review 2026-11-24, H1).

The report is written by the anaplan-estate library from names in the exports: modules, line items, lists. Its
inline step escapes angle brackets but not quotes, so a name shaped like a markdown link could close the href and
add attributes of its own (an event handler, a style that covers the page). Two things stop that here, whatever the
library does:

- `safe` reads the page tag by tag and rewrites any tag that carries something a report never needs: an event
  handler, a link that is not to a place inside the page, a style on a link or one that positions or fetches, an
  attribute whose name is not a plain word. A page with nothing of the kind comes back byte for byte.
- `policy` allows exactly the library's own one script, by its hash, and nothing else: no inline script, no event
  handler attribute. The page is also sandboxed with no origin of its own, so even a script that ran could not read
  the app's cookie or call the app as the reader.
"""
from __future__ import annotations
import base64, hashlib, html, re
from html.parser import HTMLParser

_NAME = re.compile(r"^[a-z][a-z0-9:_-]*$")
_HREF = re.compile(r"^#[A-Za-z0-9_.:%-]*$")
_STYLE_OK = re.compile(r"^[A-Za-z0-9\s:;,.()%#'\"-]*$")
_STYLE_BAD = re.compile(r"position|inset|url\s*\(|expression|@import|behavior|z-index|javascript:|top\s*:|left\s*:|right\s*:|bottom\s*:", re.I)
_NO_STYLE = {"a", "code", "td", "th", "p", "li", "span", "strong", "em", "h1", "h2", "h3", "h4", "details", "summary"}
_URL_ATTRS = {"href", "xlink:href", "src", "action", "formaction", "poster", "data", "background", "srcdoc", "ping"}


def _keep(tag: str, name: str, value: str | None) -> bool:
    if not _NAME.match(name) or name.startswith("on"):
        return False
    v = value or ""
    if name in ("href", "xlink:href"):
        return bool(_HREF.match(v))
    if name == "src":
        return tag == "script" and v.startswith("https://cdnjs.cloudflare.com/")      # the library's own diagram script; the policy decides whether it loads
    if name in _URL_ATTRS:
        return False
    if name == "style":
        return tag not in _NO_STYLE and bool(_STYLE_OK.match(v)) and not _STYLE_BAD.search(v)
    return True


class _Safe(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.changed = 0

    def _tag(self, tag, attrs, close=""):
        kept = [(k, v) for k, v in attrs if _keep(tag, k, v)]
        if len(kept) == len(attrs):
            self.out.append(self.get_starttag_text())           # nothing to take out: exactly as it was written
            return
        self.changed += len(attrs) - len(kept)
        self.out.append("<" + tag + "".join(f" {k}" if v is None else f' {k}="{html.escape(v, quote=True)}"' for k, v in kept) + close + ">")

    def handle_starttag(self, tag, attrs): self._tag(tag, attrs)
    def handle_startendtag(self, tag, attrs): self._tag(tag, attrs, " /")
    def handle_endtag(self, tag): self.out.append(f"</{tag}>")
    def handle_data(self, data): self.out.append(data)
    def handle_entityref(self, name): self.out.append(f"&{name};")
    def handle_charref(self, name): self.out.append(f"&#{name};")
    def handle_comment(self, data): self.out.append(f"<!--{data}-->")
    def handle_decl(self, decl): self.out.append(f"<!{decl}>")
    def handle_pi(self, data): self.out.append(f"<?{data}>")
    def unknown_decl(self, data): self.out.append(f"<![{data}]>")


_LINK = re.compile(r"\]\((#[^)\n]*)\)")
_TARGET = re.compile(r"^#[A-Za-z0-9_.:%-]+$")


def plain_links(markdown: str) -> str:
    """The report's markdown with every link whose target is not a plain place in the page made into plain text, before
    the library reads it: a zero-width space between the ] and the ( and it is not a link. A name from an export that is
    shaped like a link then never becomes a tag at all, so there is no half-open tag to swallow the rest of the page."""
    return _LINK.sub(lambda m: m.group(0) if _TARGET.match(m.group(1)) else "]\u200b(" + m.group(1) + ")", markdown or "")


def safe(page: str) -> tuple[str, int]:
    """The page with every attribute a report never needs taken out, and how many were. Whatever the reader could not
    read as tags (a tag left open by a stray quote) is kept as text, escaped: nothing after it is lost."""
    p = _Safe()
    p.feed(page)
    rest = p.rawdata
    p.rawdata = ""
    p.close()
    if rest:
        p.out.append(html.escape(rest, quote=True))
        p.changed += 1
    return "".join(p.out), p.changed


def script_hashes(page: str) -> list[str]:
    return ["'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'"
            for s in re.findall(r"<script(?![^>]*\bsrc\b)[^>]*>(.*?)</script>", page, re.S | re.I) if s.strip()]


_OWN: list[str] | None = None


def policy() -> str:
    """The report page's own policy: the library's own inline script by hash (read from an empty report, so a name in
    an export can never be in it), inline styles, data: images, and nothing else. No 'unsafe-inline' for script, so
    no event handler attribute runs. Sandboxed without an origin."""
    global _OWN
    if _OWN is None:
        from anaplan_estate.htmlout import md_to_html
        _OWN = script_hashes(md_to_html("", "Estate report"))
    return ("default-src 'none'; script-src " + (" ".join(_OWN) or "'none'") + "; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'; sandbox allow-scripts allow-modals")
