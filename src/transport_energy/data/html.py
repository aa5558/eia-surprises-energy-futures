"""Minimal HTML text extraction with the standard library (no lxml dependency)."""

from __future__ import annotations

from html.parser import HTMLParser


class _Tokens(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        t = " ".join(data.split())
        if t and not self._skip:
            self.out.append(t)


def text_tokens(html: str) -> list[str]:
    """Visible text as a list of whitespace-normalised chunks, one per text node."""
    p = _Tokens()
    p.feed(html)
    return p.out
